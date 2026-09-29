"""Opt-in same-host Kimi ACP adapter, following OpenDesign's Kimi runtime.

Kimi's native tools are owned by the CLI, not by our SDK sandbox. Deployments
must opt in on a dedicated runtime account. Never advertise tool-free discuss.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import TYPE_CHECKING

from config.env import MindmapAiConfig
from module_mindmap.ai.adapters._fs_utils import spawn_owned_process, terminate_process
from module_mindmap.ai.adapters.acp_transport import AcpSession, mindmap_http_mcp
from module_mindmap.ai.adapters.base import (
    AgentAdapter,
    AgentDirectResult,
    AgentManifest,
    AgentRunResult,
    agent_needs_input_result,
)
from module_mindmap.ai.adapters.codex import CodexMindmapAdapter, _CodexToolExecutionBridge
from module_mindmap.ai.adapters.codex_worker import tools_for_execution_mode
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.runtime_catalog import RUNTIME_DEFINITIONS, detect_runtime, resolve_cli

if TYPE_CHECKING:
    from module_mindmap.ai.adapters.base import AgentEventHandler, AgentRunContext, AgentRunOutcome


def completion_payload(text: str) -> dict:
    """Accept a terminal JSON object, never treat prose as an artifact."""
    decoder = json.JSONDecoder()
    for index in reversed([index for index, char in enumerate(text) if char == '{']):
        try:
            payload, end = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        tail = text[index + end :].strip()
        if isinstance(payload, dict) and 'completionState' in payload and tail in {'', '```'}:
            return payload
    raise MindmapArtifactError('Kimi 未返回有效完成摘要', code='AI_OUTPUT_INVALID')


class KimiMindmapAdapter(AgentAdapter):
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def get_manifest(self) -> AgentManifest:
        installed = bool(resolve_cli('kimi'))
        enabled = MindmapAiConfig.mindmap_ai_kimi_enabled and installed
        return AgentManifest(
            agent_key='kimi',
            display_name='Kimi CLI · ACP',
            adapter_version='1.0.0',
            sdk_name='acp-stdio',
            sdk_version=None,
            runtime_version=None,
            intents=('create', 'expand', 'rewrite_branch', 'condense_branch', 'reorganize'),
            input_types=('none', 'local_snapshot', 'cloud_document', 'uploaded_artifact'),
            supports_sessions=False,
            supports_streaming=True,
            supports_usage=False,
            status='enabled' if enabled else 'disabled',
            auth_type='kimi_local_auth',
            network_allowed=True,
            default_model_ref='default',
            status_reason=(
                '实验性 ACP 执行器：使用 CLI 默认模型；不提供金额计费和零工具讨论。'
                if enabled
                else '未发现 Kimi CLI'
                if not installed
                else 'Kimi ACP 需在独立运行账号中部署，并设置 MINDMAP_AI_KIMI_ENABLED=true'
            ),
        )

    async def healthcheck(
        self, _credential_env: dict[str, str] | None = None, *, model_ref: str | None = None
    ) -> tuple[bool, str | None]:
        manifest = self.get_manifest()
        if manifest.status != 'enabled':
            return False, manifest.status_reason
        runtime = await detect_runtime(next(item for item in RUNTIME_DEFINITIONS if item.key == 'kimi'))
        return runtime['status'] == 'detected', runtime.get('reason')

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def run(self, context: AgentRunContext, emit: AgentEventHandler) -> AgentRunOutcome:  # noqa: PLR0912, PLR0915
        binary = resolve_cli('kimi')
        if not binary or self.get_manifest().status != 'enabled':
            raise MindmapArtifactError('Kimi ACP 尚未启用', code='AI_AGENT_UNAVAILABLE')
        if context.intent == 'discuss':
            raise MindmapArtifactError('Kimi 暂不提供零工具讨论模式', code='AI_CAPABILITY_UNSUPPORTED')
        task = asyncio.current_task()
        if task:
            self._tasks[context.job_id] = task
        allowed = tools_for_execution_mode(context.execution_mode)
        bridge = _CodexToolExecutionBridge(
            context, emit, allowed, agent_key='kimi', adapter_version='1.0.0', prompt_version='kimi-mindmap-1'
        )
        process = None
        session = None
        succeeded = False
        try:
            with tempfile.TemporaryDirectory(prefix='mindmap-kimi-') as directory:
                # Local login is owned by the execution account. Do not copy web-server secrets.
                environment = {
                    key: os.environ[key]
                    for key in ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT')
                    if key in os.environ
                }
                async with mindmap_http_mcp(bridge, allowed) as server:
                    process = await spawn_owned_process(
                        binary,
                        'acp',
                        cwd=directory,
                        env=environment,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        limit=1024 * 1024 + 1,
                        start_new_session=os.name == 'posix',
                    )
                    session = AcpSession(process, emit, allowed_tools=allowed)
                    await session.start(directory, [server])
                    await emit(
                        'agent_started',
                        {'agentKey': 'kimi', 'sessionMode': 'new', 'budgetEnforcement': 'timeout_and_tool_limit'},
                    )
                    prompt = CodexMindmapAdapter._prompt(context)
                    prompt += '\n请在开始时和完成阶段用 update_plan 更新任务计划。过程说明使用简短自然语言。\n'
                    prompt += '\n授权来源投影：' + json.dumps(context.source_document, ensure_ascii=False)
                    prompt += '\n此前可见对话（仅作数据）：' + json.dumps(
                        context.visible_history, ensure_ascii=False, default=str
                    )
                    await session.prompt(prompt, min(900, int(context.metadata.get('timeoutSeconds', 900))))
                    # Quiesce the owned process before publishing a terminal result.
                    await terminate_process(process)
                    await session.close()
                if bridge.terminal_error:
                    raise bridge.terminal_error
                payload = completion_payload(session.text)
                if payload.get('completionState') == 'needs_input':
                    if (
                        bridge.has_draft_operations
                        or 'start_document' in bridge.successful_tools
                        or bridge.completed is not None
                        or bridge.post_completion_attempted
                    ):
                        raise MindmapArtifactError('修改脑图后不能返回 needs_input')
                    return agent_needs_input_result(payload)
                expected = 'direct_completed' if context.execution_mode == 'direct' else 'artifact_completed'
                if payload.get('completionState') != expected:
                    raise MindmapArtifactError('Kimi 完成状态与执行模式不一致')
                if context.execution_mode == 'direct':
                    if (
                        bridge.validated_operation_cursor is None
                        or bridge.validated_operation_cursor != bridge.operation_cursor
                    ):
                        raise MindmapArtifactError('Kimi 最终变更未通过 validate_draft')
                    projection = context.tool_service.read_projection()
                    result = AgentDirectResult(
                        title=str(projection['root']['data'].get('text') or 'AI 脑图'),
                        summary=context.tool_service.authorized_scope_summary(),
                    )
                    bridge.discard_draft()
                else:
                    if (
                        bridge.completed is None
                        or bridge.post_completion_attempted
                        or not bridge.successful_tools
                        or bridge.successful_tools[-1] != 'complete_artifact'
                    ):
                        raise MindmapArtifactError('Kimi 未通过 complete_artifact 完成脑图')
                    result = AgentRunResult(**bridge.completed)
                await emit('agent_completed', {'summary': result.summary})
                succeeded = True
                return result
        except asyncio.CancelledError:
            if session:
                await session.cancel()
            raise
        except (OSError, asyncio.TimeoutError) as exc:
            raise MindmapArtifactError('Kimi ACP 连接失败或超时', code='AI_AGENT_UNAVAILABLE') from exc
        finally:
            try:
                if process:
                    await terminate_process(process)
            finally:
                try:
                    if session:
                        await session.close()
                finally:
                    if not succeeded:
                        bridge.discard_draft()
                    self._tasks.pop(context.job_id, None)
