"""User-owned runtimes; platform jobs still own all document operations."""

import asyncio

from config.env import MindmapAiConfig
from module_mindmap.ai.adapters.base import (
    AgentAdapter,
    AgentEventHandler,
    AgentManifest,
    AgentRunContext,
    AgentRunOutcome,
)
from module_mindmap.ai.device_run_session import DEVICE_ADAPTER_VERSION
from module_mindmap.ai.device_runtime import device_runtime_enabled
from module_mindmap.ai.document import MindmapArtifactError

DEVICE_AGENT_KEY = 'device_claude'


class _DeviceAdapter(AgentAdapter):
    runtime: str
    display_name: str
    sdk_name: str
    sdk_version: str

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def get_manifest(self) -> AgentManifest:
        enabled = device_runtime_enabled(self.runtime)
        return AgentManifest(
            agent_key=f'device_{self.runtime}', display_name=self.display_name, adapter_version=DEVICE_ADAPTER_VERSION,
            sdk_name=self.sdk_name, sdk_version=self.sdk_version, runtime_version=None,
            intents=('create', 'expand', 'rewrite_branch', 'condense_branch', 'reorganize', 'discuss'),
            input_types=('none', 'local_snapshot', 'cloud_document', 'uploaded_artifact'),
            supports_sessions=False, supports_streaming=True, supports_usage=False,
            status='enabled' if enabled else 'disabled', result_types=('artifact', 'message'),
            auth_type='user_device', network_allowed=True,
            default_model_ref=getattr(MindmapAiConfig, f'mindmap_ai_{self.runtime}_model'),
            status_reason=(('需连接本机 Codex；预算按回报用量估算，非硬费用上限' if self.runtime == 'codex'
                            else '需连接本机 Kimi 2.1.1；无金额上限，仅限制时间与工具次数' if self.runtime == 'kimi'
                            else '需选择本人已配对且显式启用 Claude 执行的电脑')
                           if enabled else '管理员尚未启用此本机 Agent'),
        )

    async def run(self, context: AgentRunContext, emit: AgentEventHandler) -> AgentRunOutcome:
        execute = context.metadata.get('_executeDevice')
        if self.get_manifest().status != 'enabled' or not callable(execute):
            raise MindmapArtifactError('缺少平台绑定的设备执行上下文', code='AI_AGENT_UNAVAILABLE')
        task = asyncio.current_task()
        if task is None:
            raise MindmapArtifactError('设备执行不在异步任务中', code='AI_AGENT_UNAVAILABLE')
        self._tasks[context.job_id] = task
        try:
            return await execute(context, emit)
        finally:
            if self._tasks.get(context.job_id) is task:
                self._tasks.pop(context.job_id, None)

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True  # cancellation requested, NOT process-stop confirmation


class DeviceClaudeAdapter(_DeviceAdapter):
    runtime = 'claude'
    display_name = 'Claude · 我的电脑'
    sdk_name = 'device-claude-agent-sdk'
    sdk_version = '0.2.152'


class DeviceCodexAdapter(_DeviceAdapter):
    runtime = 'codex'
    display_name = 'Codex · 我的电脑'
    sdk_name = 'device-codex-app-server'
    sdk_version = '0.147.0'


class DeviceKimiAdapter(_DeviceAdapter):
    runtime = 'kimi'
    display_name = 'Kimi · 我的电脑'
    sdk_name = 'device-kimi-acp'
    sdk_version = '2.1.1'
