"""OpenDesign-style bounded discovery, running on the user's own computer."""

import asyncio
import os
import re
import shutil
import signal
import tempfile
from pathlib import Path

BINARIES = ('claude', 'codex', 'kimi')
MAX_PROBE_BYTES = 65536
PROBE_TIMEOUT = 6
MAX_VERSION_CHARS = 80


def resolve_binary(binary: str) -> str | None:
    if binary not in BINARIES:
        raise ValueError('Unknown Agent')
    found = shutil.which(binary)
    if found:
        return str(Path(found).resolve())
    for directory in (Path.home() / '.local/bin', Path.home() / '.npm-global/bin',
                      Path('/opt/homebrew/bin'), Path('/usr/local/bin')):
        candidate = directory / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


async def probe(binary: str, argument: str, *, print_mode: bool = False, isolated_home: bool = False) -> str:
    # No shell, model requests, login commands, user-supplied arguments, or
    # application credentials. HOME allows a CLI to resolve its own install.
    if argument not in {'--version', '--help'} or (print_mode and argument != '--help'):
        raise ValueError('Unsupported probe')
    with tempfile.TemporaryDirectory(prefix='mindmap-agent-scan-') as cwd:
        environment = {**{key: os.environ[key] for key in ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ},
                       'NO_COLOR': '1'}
        if isolated_home:
            for key, directory in {'HOME': 'home', 'XDG_CONFIG_HOME': 'config', 'XDG_CACHE_HOME': 'cache',
                                   'XDG_DATA_HOME': 'data', 'XDG_STATE_HOME': 'state'}.items():
                private = Path(cwd) / directory
                private.mkdir(mode=0o700)
                environment[key] = str(private)
            environment.update(TMPDIR=cwd, TMP=cwd, TEMP=cwd)
        launch = asyncio.create_task(asyncio.create_subprocess_exec(
            binary, *(['-p'] if print_mode else []), argument, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=environment, start_new_session=True,
        ))
        try:
            process = await asyncio.shield(launch)
            async def read() -> str:
                output = bytearray()
                while chunk := await process.stdout.read(8192):
                    output.extend(chunk)
                    if len(output) > MAX_PROBE_BYTES:
                        raise ValueError('Probe output exceeded limit')
                await process.wait()
                if process.returncode:
                    raise ValueError('Probe failed')
                return output.decode('utf-8', errors='replace')
            return await asyncio.wait_for(read(), timeout=PROBE_TIMEOUT)
        finally:
            # Kill the isolated group even if the launcher exited but a child
            # still holds stdout. A cancelled spawn can already own a process,
            # so settle it before removing the private probe directory.
            async def cleanup():
                process = await launch
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()

            stopped = asyncio.create_task(cleanup())
            interrupted = False
            while not stopped.done():
                try:
                    await asyncio.shield(stopped)
                except asyncio.CancelledError:
                    interrupted = True
            stopped.result()
            if interrupted:
                raise asyncio.CancelledError


async def detect(binary: str) -> dict:
    path = resolve_binary(binary)
    result = {'agentKey': binary, 'installed': bool(path), 'version': None,
              'status': 'not_installed', 'capabilities': []}
    if not path:
        return result
    tasks = [
        asyncio.create_task(probe(path, '--version')),
        asyncio.create_task(probe(path, '--help', print_mode=binary == 'claude')),
    ]
    try:
        version, help_text = await asyncio.gather(*tasks)
        match = re.search(r'\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?', version)
        result.update(version=match.group() if match and len(match.group()) <= MAX_VERSION_CHARS else None, status='detected')
        flags = {'--include-partial-messages': 'partial_messages', '--session-mirror': 'session_mirror',
                 '--resume': 'resume'}
        result['capabilities'] = [name for flag, name in flags.items() if flag in help_text]
        if binary == 'kimi':
            if re.search(r'\bacp\b', help_text):
                result['capabilities'].append('acp')
            else:
                result['status'] = 'incompatible'
    except (OSError, ValueError, asyncio.TimeoutError):
        result['status'] = 'probe_failed'
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return result


async def discover() -> list[dict]:
    if os.name != 'posix':
        raise RuntimeError('This bridge currently supports macOS and Linux only')
    return list(await asyncio.gather(*(detect(binary) for binary in BINARIES)))
