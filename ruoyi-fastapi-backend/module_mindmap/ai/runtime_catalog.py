"""Same-host CLI discovery, adapted from OpenDesign runtimes/definitions.

Known binaries are probed concurrently in an empty temporary cwd. HTTP clients
cannot submit executable paths or shell fragments for this privileged process.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import tempfile
import time
from dataclasses import dataclass

from module_mindmap.ai.adapters._fs_utils import spawn_owned_process, terminate_process
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.runtime_paths import resolve_cli


@dataclass(frozen=True)
class RuntimeDefinition:
    key: str
    name: str
    binary: str
    protocol: str
    package: str | None = None


RUNTIME_DEFINITIONS = (
    RuntimeDefinition('claude', 'Claude Code', 'claude', 'claude-stream-json', 'claude_agent_sdk'),
    RuntimeDefinition('codex', 'Codex', 'codex', 'codex-app-server', 'openai_codex'),
    RuntimeDefinition('kimi', 'Kimi CLI', 'kimi', 'acp-json-rpc'),
)
_cache: dict[str, dict] = {}
_scan_state = {'scanned_at': 0.0}
_scan_lock = asyncio.Lock()
MAX_PROBE_BYTES = 65536
SCAN_CACHE_SECONDS = 30
MAX_VERSION_CHARS = 80


async def _probe(path: str, args: list[str]) -> str:
    with tempfile.TemporaryDirectory(prefix='mindmap-agent-probe-') as directory:
        process = await spawn_owned_process(
            path,
            *args,
            cwd=directory,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={
                **{
                    key: os.environ[key]
                    for key in ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT')
                    if key in os.environ
                },
                'NO_COLOR': '1',
                'COLUMNS': '200',
            },
            start_new_session=os.name == 'posix',
        )
        try:

            async def read() -> bytes:
                data = bytearray()
                while chunk := await process.stdout.read(8192):
                    data.extend(chunk)
                    if len(data) > MAX_PROBE_BYTES:
                        raise ValueError('probe output limit')
                await process.wait()
                if process.returncode:
                    raise ValueError('probe failed')
                return bytes(data)

            raw = await asyncio.wait_for(read(), 6)
            return raw.decode('utf-8', errors='replace')
        finally:
            await terminate_process(process)


async def detect_runtime(definition: RuntimeDefinition) -> dict:
    path = resolve_cli(definition.binary)
    result = {
        'agentKey': definition.key,
        'displayName': definition.name,
        'protocol': definition.protocol,
        'location': 'runtime_host',
        'installed': bool(path),
        'version': None,
        'status': 'not_installed',
        'capabilities': [],
        'checkedAt': int(time.time() * 1000),
    }
    result['sdkInstalled'] = bool(definition.package and importlib.util.find_spec(definition.package))
    result['executionSource'] = 'local_cli' if path else 'sdk_bundled' if result['sdkInstalled'] else 'unavailable'
    if definition.key == 'claude' and result['sdkInstalled']:
        result['executionSource'] = 'sdk_bundled'
    if not path:
        return result
    tasks = [asyncio.create_task(_probe(path, arguments)) for arguments in (['--version'], ['-p', '--help'] if definition.key == 'claude' else ['--help'])]
    try:
        version, help_text = await asyncio.gather(*tasks)
        match = re.search(r'\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?', version)
        result.update(version=match.group() if match and len(match.group()) <= MAX_VERSION_CHARS else None, status='detected')
        result['capabilities'] = [
            name
            for flag, name in {
                '--include-partial-messages': 'partial_messages',
                '--thinking-display': 'thinking_summary',
                '--session-mirror': 'session_mirror',
                '--resume': 'resume',
            }.items()
            if flag in help_text
        ]
        if definition.key == 'claude' and 'session_mirror' in result['capabilities']:
            result['executionSource'] = 'local_cli'
        if definition.key == 'kimi' and 'acp' not in help_text:
            result.update(status='incompatible', reason='当前 CLI 未声明 ACP 模式')
    except (OSError, ValueError, asyncio.TimeoutError, MindmapArtifactError):
        result.update(status='probe_failed', reason='版本或能力探测失败，请检查 CLI 安装')
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return result


async def discover_runtimes(*, refresh: bool = False) -> list[dict]:
    async with _scan_lock:
        if not refresh and _cache and time.monotonic() - _scan_state['scanned_at'] < SCAN_CACHE_SECONDS:
            return [dict(item) for item in _cache.values()]
        results = await asyncio.gather(*(detect_runtime(item) for item in RUNTIME_DEFINITIONS))
        _cache.clear()
        _cache.update({item['agentKey']: item for item in results})
        _scan_state['scanned_at'] = time.monotonic()
        return results


def claude_cli_options() -> dict:
    """Use a detected CLI only when it can preserve our durable SDK sessions."""
    capabilities = _cache.get('claude', {}).get('capabilities', [])
    options: dict = {'include_partial_messages': True}
    if 'session_mirror' in capabilities and (path := resolve_cli('claude')):
        options['cli_path'] = path
    return options
