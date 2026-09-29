"""Trusted local Kimi launcher, enabled only by explicit local CLI consent.

Kimi money usage is unavailable over the audited ACP interface. Construction
requires explicit LOCAL acknowledgement of timeout/tool-count-only limits;
neither a remote offer nor saved pairing config can grant that consent.
"""

import asyncio
import importlib.util
import os
import shutil
from pathlib import Path

from .discovery import resolve_binary
from .execution import MAX_OFFER_BYTES, BridgeError, RunFailure, RunProtocolError, RunStopped, _bounded
from .kimi_policy import CLI_VERSION, isolated_environment, stage_local_auth, validate_offer, write_configuration


def local_command():
    if os.name != 'posix' or any(importlib.util.find_spec(name) is None for name in ('psutil', 'starlette', 'uvicorn')):
        raise BridgeError('本机 Kimi 执行需要 macOS/Linux 和桥接的 kimi 可选依赖')
    binary = resolve_binary('kimi')
    if not binary:
        raise BridgeError('未找到本机 Kimi Code CLI；需要已验证的 2.1.1 版本')
    node = shutil.which('node')
    return [binary], str(Path(node).resolve().parent) if node else None


class KimiRunDriver:
    def __init__(self, *, accept_unmetered_budget=False):
        if accept_unmetered_budget is not True:
            raise BridgeError('Kimi 不支持金额上限；必须在本机明确接受仅超时和工具次数限制')
        self.argv, self.node_directory = local_command()
        from .kimi_mcp import KimiToolGateway
        from .kimi_session import KimiSession
        from .process_owner import OwnedProcess, shield_cleanup
        self._gateway_type, self._session_type = KimiToolGateway, KimiSession
        self.owner, self.probe_owner = OwnedProcess(), OwnedProcess()
        self._shield_cleanup = shield_cleanup
        self._used = False
        self._directory = self._cleanup = self._launch = self.session = self.gateway = None
        self._probe_launch = None
        self._workspace = None

    async def run(self, offer, channel):
        if self._used or self._cleanup is not None:
            raise RunProtocolError
        self._used = True
        validate_offer(offer)
        try:
            from .run_recovery import OwnedRun
            self._workspace = OwnedRun.create('kimi')
            self._directory = str(self._workspace.path)
            environment = isolated_environment(self._directory, node_directory=self.node_directory)
            cwd = Path(self._directory) / 'workspace'
            cwd.mkdir(mode=0o700)
            # Probe with a PRIVATE, credential-free home before reading any
            # local login. Legacy Python Kimi CLI versions are not accepted.
            self._probe_launch = asyncio.create_task(self.probe_owner.start(
                [*self.argv, '--version'], env=environment, cwd=str(cwd), workspace=self._workspace))
            process = await asyncio.shield(self._probe_launch)
            try:
                raw = await _bounded(process.stdout.read(65537), 6)
                await _bounded(process.wait(), 1)
                if process.returncode or raw.decode('utf-8').strip() != CLI_VERSION:
                    raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
            finally:
                await self.probe_owner.stop()
            if self._cleanup is not None:
                raise RunStopped
            provider = stage_local_auth(environment)
            write_configuration(environment, offer, provider)
            del provider
            self.gateway = self._gateway_type(offer, channel)
            await self.gateway.start()
            if self._cleanup is not None:
                raise RunStopped
            self._launch = asyncio.create_task(self.owner.start(
                [*self.argv, 'acp'], cwd=str(cwd), env=environment, limit=MAX_OFFER_BYTES, workspace=self._workspace,
            ))
            process = await asyncio.shield(self._launch)
            if self._cleanup is not None:
                raise RunStopped
            async def send(raw):
                process.stdin.write(raw.encode('utf-8'))
                await process.stdin.drain()
            self.session = self._session_type(process.stdout.readline, send, cwd=str(cwd), gateway=self.gateway)
            return await self.session.run(offer, channel)
        except asyncio.TimeoutError:
            raise RunFailure('AI_TIMEOUT') from None
        except (OSError, UnicodeError, ValueError):
            raise RunFailure('AI_AGENT_UNAVAILABLE') from None
        finally:
            await self.stop()

    async def stop(self):
        async def cleanup():
            if self.gateway is not None:
                self.gateway.disable()
            for launch in (self._probe_launch, self._launch):
                if launch is None:
                    continue
                try:
                    await launch
                except Exception:
                    pass
            if self.session is not None:
                try:
                    await _bounded(self.session.interrupt(), 0.15)
                except (Exception, asyncio.CancelledError):
                    pass
            try:
                await self.probe_owner.stop()
                await self.owner.stop()
            finally:
                if self.gateway is not None:
                    await self.gateway.close()
            if self._workspace is not None:
                self._workspace.cleanup()
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(cleanup())
        await self._shield_cleanup(self._cleanup)
