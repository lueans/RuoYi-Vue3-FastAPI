"""Trusted local Claude CLI driver for the opt-in device execution protocol."""

import asyncio
import importlib.util
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

from .discovery import resolve_binary
from .execution import MAX_OFFER_BYTES, MAX_REPLY_BYTES, BridgeError, RunFailure, RunProtocolError, _bounded, _load

WORKER = Path(__file__).with_name('claude_worker.py')
ENV_ALLOWLIST = frozenset({
    'HOME', 'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TMP', 'TEMP', 'USER', 'LOGNAME', 'TZ',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS',
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
})


def local_environment():
    # Only local process state. The server/run offer cannot supply env values.
    return {**{key: value for key, value in os.environ.items() if key in ENV_ALLOWLIST},
            'NO_COLOR': '1', 'PYTHONNOUSERSITE': '1'}


def local_binary():
    if os.name != 'posix' or any(importlib.util.find_spec(name) is None for name in ('claude_agent_sdk', 'psutil')):
        raise BridgeError('本机 Claude 执行需要 macOS/Linux 和桥接的 claude 可选依赖')
    if version('claude-agent-sdk') != '0.2.152':
        raise BridgeError('Claude SDK 版本与本机桥接不兼容，请按 claude 可选依赖安装已验证版本')
    binary = resolve_binary('claude')
    if not binary:
        raise BridgeError('本机尚未发现 Claude CLI，请先在终端安装并登录')
    return binary


class ClaudeRunDriver:
    def __init__(self):
        self.binary = local_binary()
        from .process_owner import OwnedProcess, shield_cleanup
        self._shield_cleanup = shield_cleanup
        self.owner = OwnedProcess()
        self._directory = None
        self._cleanup = None
        self._used = False
        self._workspace = None

    async def run(self, offer, channel):
        if self._used or self._cleanup is not None or offer.agent_key != 'claude':
            raise RunProtocolError
        self._used = True
        from .run_recovery import OwnedRun
        self._workspace = OwnedRun.create('claude')
        self._directory = str(self._workspace.path)
        process = await self.owner.start(
            [sys.executable, '-I', str(WORKER)], cwd=self._directory,
            env=local_environment(), limit=MAX_OFFER_BYTES, workspace=self._workspace,
        )
        payload = {**offer.identity, 'type': 'run', 'agentKey': offer.agent_key, 'intent': offer.intent,
                   'executionMode': offer.execution_mode, 'prompt': offer.prompt, 'tools': list(offer.tools),
                   'runtimePolicy': {'maxBudgetUsd': offer.max_budget_usd, 'timeoutSeconds': offer.timeout_seconds,
                                     'modelRef': offer.model_ref}}
        await self._send({'type': 'start', 'offer': payload, 'cliPath': self.binary})
        sequence, total = 0, 0
        while raw := await process.stdout.readline():
            total += len(raw)
            if total > 8 * MAX_OFFER_BYTES:
                raise RunProtocolError
            message = _load(raw, MAX_OFFER_BYTES)
            kind = message.get('type')
            if kind == 'tool_call':
                if (set(message) != {'type', 'sequence', 'toolName', 'arguments'}
                        or type(message['sequence']) is not int or message['sequence'] != sequence + 1):
                    raise RunProtocolError
                sequence = message['sequence']
                result = await channel.tool(message['toolName'], message['arguments'])
                await self._send({'type': 'tool_result', 'sequence': sequence, 'toolResult': result})
            elif kind == 'event':
                if message.get('kind') == 'thinking' and set(message) == {'type', 'kind'}:
                    await channel.thinking()
                elif message.get('kind') == 'public_text' and set(message) == {'type', 'kind', 'messageId', 'text', 'channel'}:
                    await channel.public_text(message['text'], message_id=message['messageId'], channel=message['channel'])
                else:
                    raise RunProtocolError
            elif kind == 'completed' and set(message) == {'type', 'completion'}:
                if not isinstance(message['completion'], dict):
                    raise RunProtocolError
                return message['completion']
            elif kind == 'failed' and set(message) == {'type', 'errorCode'} and message['errorCode'] in RunFailure.MESSAGES:
                raise RunFailure(message['errorCode'])
            else:
                raise RunProtocolError
        raise RunProtocolError

    async def _send(self, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(data) > MAX_REPLY_BYTES:
            raise RunProtocolError
        self.owner.process.stdin.write(data)
        await _bounded(self.owner.process.stdin.drain(), 15)

    async def stop(self):
        async def cleanup():
            await self.owner.stop()
            # Only remove the exact private directory created for this run,
            # and only after all owned processes have been confirmed stopped.
            if self._workspace is not None:
                self._workspace.cleanup()
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(cleanup())
        await self._shield_cleanup(self._cleanup)
