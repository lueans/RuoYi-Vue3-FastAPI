"""Trusted, single-use POSIX Codex launcher, enabled by explicit local consent.

Only local credentials are staged. Offers cannot select argv, directories,
environment, providers, MCP servers or plugins. Configuration isolation and
disabled tools are not an OS sandbox for a compromised installed executable.
"""

import asyncio
import importlib.util
import os
import stat
from importlib.metadata import version
from pathlib import Path

from .codex_policy import CLI_VERSION, CodexPolicy, startup_arguments
from .codex_session import CodexSession
from .execution import MAX_OFFER_BYTES, BridgeError, RunFailure, RunProtocolError, RunStopped, _load

MAX_AUTH_BYTES = 2 * 1024 * 1024


def bundled_binary():
    if os.name != 'posix' or any(importlib.util.find_spec(name) is None for name in ('codex_cli_bin', 'psutil')):
        raise BridgeError('本机 Codex 执行需要 macOS/Linux 和桥接的 codex 可选依赖')
    if version('openai-codex-cli-bin') != CLI_VERSION:
        raise BridgeError('Codex CLI 版本与桥接不兼容，请安装 codex 可选依赖的已验证版本')
    from codex_cli_bin import bundled_codex_path
    try:
        binary = bundled_codex_path().resolve(strict=True)
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise OSError
        return str(binary)
    except OSError:
        raise BridgeError('Codex 随包程序不可执行，请重新安装 codex 可选依赖') from None


def isolated_environment(root):
    root = Path(root)
    paths = {key: root / name for key, name in {
        'HOME': 'home', 'CODEX_HOME': 'codex', 'TMPDIR': 'tmp', 'XDG_CONFIG_HOME': 'config',
        'XDG_CACHE_HOME': 'cache', 'XDG_DATA_HOME': 'data', 'XDG_STATE_HOME': 'state',
    }.items()}
    for path in paths.values():
        path.mkdir(mode=0o700)
    return {**{key: str(path) for key, path in paths.items()}, 'TMP': str(paths['TMPDIR']),
            'TEMP': str(paths['TMPDIR']), 'PATH': os.defpath, 'LANG': 'C.UTF-8', 'NO_COLOR': '1'}


def stage_local_auth(environment):
    """Read only at explicit execution, never during scan/driver construction.

    Keychain-only logins are not borrowed. File auth is copied privately, never
    linked; refresh cannot overwrite the user's login. No config is copied.
    """
    key = os.environ.get('OPENAI_API_KEY')
    if key is not None:
        if not key.strip() or len(key) > 16_384 or any(c in key for c in ('\0', '\n', '\r')):
            raise RunFailure('AI_PROVIDER_AUTH_FAILED')
        # app-server does not bootstrap account/read from this env var. The
        # trusted policy sends account/login/start only to the private child,
        # AFTER validating its version/config. Do not inherit it in child env.
        return key
    source = Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex')).expanduser() / 'auth.json'
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_AUTH_BYTES:
                raise OSError
            raw = handle.read(MAX_AUTH_BYTES + 1)
        _load(raw, MAX_AUTH_BYTES)
        target = Path(environment['CODEX_HOME']) / 'auth.json'
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(raw)
    except (OSError, ValueError, RunProtocolError):
        raise RunFailure('AI_PROVIDER_AUTH_FAILED') from None


class CodexRunDriver:
    def __init__(self):
        self.binary = bundled_binary()
        from .process_owner import OwnedProcess, shield_cleanup
        self.owner = OwnedProcess()
        self._shield_cleanup = shield_cleanup
        self._directory = self._cleanup = self._launch = self.session = self.policy = None
        self._used = False
        self._workspace = None

    async def run(self, offer, channel):
        if self._used or self._cleanup is not None or offer.agent_key != 'codex':
            raise RunProtocolError
        self._used = True
        self.policy = CodexPolicy(offer)  # reject unknown price before reading a credential
        try:
            from .run_recovery import OwnedRun
            self._workspace = OwnedRun.create('codex')
            self._directory = str(self._workspace.path)
            environment = isolated_environment(self._directory)
            self.policy.local_api_key = stage_local_auth(environment)
            cwd = Path(self._directory) / 'workspace'
            cwd.mkdir(mode=0o700)
            self._launch = asyncio.create_task(self.owner.start(
                [self.binary, *startup_arguments(), 'app-server'], cwd=str(cwd), env=environment,
                limit=MAX_OFFER_BYTES, workspace=self._workspace,
            ))
            process = await asyncio.shield(self._launch)
            if self._cleanup is not None:
                raise RunStopped
            async def send(raw):
                process.stdin.write(raw.encode('utf-8'))
                await process.stdin.drain()
            self.session = CodexSession(process.stdout.readline, send, cwd=str(cwd), policy=self.policy)
            return await self.session.run(offer, channel)
        except (OSError, ValueError):
            # Local paths, auth errors and process diagnostics stay local.
            raise RunFailure('AI_AGENT_UNAVAILABLE') from None
        finally:
            self.policy.local_api_key = None
            await self.stop()

    async def stop(self):
        async def cleanup():
            if self._launch is not None:
                try:
                    await self._launch
                except Exception:
                    pass  # partial launch still requires ownership cleanup
            if self.session is not None:
                try:
                    await asyncio.wait_for(self.session.interrupt(), timeout=0.15)
                except (Exception, asyncio.CancelledError):
                    pass  # interrupt is best effort, process ownership is mandatory
            await self.owner.stop()
            if self._workspace is not None:
                self._workspace.cleanup()
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(cleanup())
        await self._shield_cleanup(self._cleanup)
