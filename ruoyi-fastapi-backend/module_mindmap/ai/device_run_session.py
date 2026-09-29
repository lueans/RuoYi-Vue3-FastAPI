"""Job-worker side of an outbound device execution channel.

The device runs the CLI, never owns a document or commits its own artifact.
All mutations use the same in-memory tool gateway / durable event sink as the
same-host adapters. Authentication and job/device/epoch checks are mandatory
callbacks supplied by the job dispatcher, not assertions from the device.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter
from pydantic.alias_generators import to_camel

from module_mindmap.ai.adapters.base import (
    AgentDirectResult,
    AgentEventHandler,
    AgentRunContext,
    AgentRunOutcome,
    AgentRunResult,
    agent_message_result,
    agent_needs_input_result,
    build_agent_discussion_prompt,
)
from module_mindmap.ai.adapters.codex import CodexMindmapAdapter, _CodexToolExecutionBridge
from module_mindmap.ai.adapters.codex_mcp_bridge import TOOL_DESCRIPTORS
from module_mindmap.ai.adapters.codex_worker import tools_for_execution_mode
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.runtime_trace import MAX_TRACE_CHARS, public_text

MAX_DEVICE_RUN_FRAME_BYTES = 2 * 1024 * 1024
MAX_DEVICE_REPLY_BYTES = 8 * 1024 * 1024
MAX_DEVICE_RUN_FRAMES = 2048
RUN_PROTOCOL_VERSION = 1
DEVICE_ADAPTER_VERSION = '1.0.0'
DEVICE_PROMPT_VERSION = 'device-mindmap-1'
ERROR_MESSAGES = {
    'AI_PROVIDER_AUTH_FAILED': '本机 Agent 登录失效，请在设备终端完成登录',
    'AI_RATE_LIMITED': '本机 Agent 供应商请求受限',
    'AI_TIMEOUT': '本机 Agent 任务超时',
    'AI_AGENT_UNAVAILABLE': '本机 Agent 执行中断',
    'AI_AGENT_CLEANUP_FAILED': '尚未确认本机 Agent 已停止，请检查设备上的 CLI',
    'AI_CAPABILITY_UNSUPPORTED': '本机 Agent 的模型或受限执行能力未经验证，请检查配置',
    'AI_BUDGET_EXCEEDED': '本机 Agent 已达到预算限制，或无法验证本轮用量',
}


class DeviceRunFenced(asyncio.CancelledError):
    """An obsolete device frame, distinct from cancelling the transport itself."""


@dataclass(frozen=True)
class DeviceRunBinding:
    """Server-issued identity; never reconstructed from an incoming frame."""

    run_id: str
    job_id: str
    user_id: int
    device_id: str
    execution_epoch: int
    connection_id: str
    agent_key: Literal['claude', 'codex', 'kimi']

    def __post_init__(self) -> None:
        for value in (self.run_id, self.job_id, self.device_id, self.connection_id):
            if str(UUID(value)) != value:
                raise ValueError('Invalid device run identity')
        if type(self.execution_epoch) is not int or self.execution_epoch < 1:
            raise ValueError('Invalid execution epoch')
        if type(self.user_id) is not int or self.user_id < 1 or self.agent_key not in {'claude', 'codex', 'kimi'}:
            raise ValueError('Invalid device run owner or Agent')


class _Frame(BaseModel):
    model_config = ConfigDict(extra='forbid', alias_generator=to_camel, hide_input_in_errors=True)
    protocol_version: int = Field(strict=True, ge=1, le=1)
    run_id: str = Field(min_length=36, max_length=36)
    execution_epoch: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1, le=MAX_DEVICE_RUN_FRAMES)


class _ToolCall(_Frame):
    type: Literal['tool_call']
    tool_name: str = Field(max_length=64, pattern=r'^[a-z_]+$')
    arguments: dict[str, Any]


class _Text(_Frame):
    type: Literal['public_text']
    channel: Literal['assistant', 'thinking_summary']
    text: str = Field(min_length=1, max_length=4000)
    message_id: str = Field(min_length=1, max_length=120, pattern=r'^[a-zA-Z0-9_:.-]+$')


class _Thinking(_Frame):
    type: Literal['thinking']


class _Heartbeat(_Frame):
    type: Literal['heartbeat']


class _Completion(BaseModel):
    model_config = ConfigDict(extra='forbid', alias_generator=to_camel, hide_input_in_errors=True)
    completion_state: Literal['artifact_completed', 'direct_completed', 'message_completed', 'needs_input']
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=20_000)
    content_type: Literal['text/plain'] = 'text/plain'
    questions: list[dict[str, str]] = Field(default_factory=list, max_length=3)


class _Completed(_Frame):
    type: Literal['completed']
    process_stopped: StrictBool
    completion: _Completion


class _Failed(_Frame):
    type: Literal['failed']
    error_code: Literal[
        'AI_PROVIDER_AUTH_FAILED', 'AI_RATE_LIMITED', 'AI_TIMEOUT',
        'AI_AGENT_UNAVAILABLE', 'AI_AGENT_CLEANUP_FAILED',
        'AI_CAPABILITY_UNSUPPORTED', 'AI_BUDGET_EXCEEDED',
    ]
    process_stopped: StrictBool


class _Stopped(_Frame):
    type: Literal['stopped']
    process_stopped: StrictBool


_FRAME_ADAPTER = TypeAdapter(Annotated[
    _ToolCall | _Text | _Thinking | _Heartbeat | _Completed | _Failed | _Stopped,
    Field(discriminator='type'),
])
RunAuthorizer = Callable[[DeviceRunBinding], Awaitable[bool]]


def _encode(value: object, limit: int = MAX_DEVICE_REPLY_BYTES) -> bytes:
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(data) > limit:
        raise MindmapArtifactError('设备执行消息超过上限', code='AI_INPUT_TOO_LARGE')
    return data


class DeviceRunSession:
    """Serial, replay-safe tool bridge; no provider credentials or raw frames."""

    def __init__(
        self, binding: DeviceRunBinding, context: AgentRunContext,
        emit: AgentEventHandler, authorize: RunAuthorizer, *, adapter_agent_key: str | None = None,
    ) -> None:
        if binding.job_id != context.job_id or binding.user_id != context.user_id or not callable(authorize):
            raise ValueError('Run context does not belong to this binding')
        self.binding = binding
        self.context = context
        self._emit = emit
        self._authorize = authorize
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._last_digest: str | None = None
        self._last_reply: bytes | None = None
        self._text_chars = 0
        self.phase: Literal['running', 'cancelling', 'completed', 'failed', 'stopped', 'closed'] = 'running'
        self.result: AgentRunOutcome | None = None
        self.error: MindmapArtifactError | None = None
        self.finished = asyncio.Event()
        self.allowed_tools = () if context.intent == 'discuss' else tools_for_execution_mode(context.execution_mode)
        self.gateway = _CodexToolExecutionBridge(
            context, self._emit_guarded, self.allowed_tools,
            agent_key=adapter_agent_key or binding.agent_key,
            adapter_version=DEVICE_ADAPTER_VERSION, prompt_version=DEVICE_PROMPT_VERSION,
        )

    def _identity(self) -> dict[str, Any]:
        return {'protocolVersion': RUN_PROTOCOL_VERSION, 'runId': self.binding.run_id,
                'executionEpoch': self.binding.execution_epoch}

    async def _check_authority(self) -> None:
        if await self._authorize(self.binding) is not True:
            self.request_cancel()
            raise MindmapArtifactError('设备或任务授权已失效，本轮已停止接收操作', code='AI_SANDBOX_VIOLATION')
        if self.phase != 'running':
            raise DeviceRunFenced

    async def _emit_guarded(self, kind: str, payload: dict[str, Any]) -> None:
        if self.phase != 'running':
            raise asyncio.CancelledError
        await self._check_authority()
        await self._emit(kind, payload)

    async def offer(self) -> dict[str, Any]:
        await self._check_authority()
        if self.phase != 'running':
            raise MindmapArtifactError('设备任务已停止', code='AI_TASK_CANCELLED')
        # Context metadata contains platform credentials; never serialize it.
        prompt = (build_agent_discussion_prompt(self.context) if self.context.intent == 'discuss'
                  else CodexMindmapAdapter._prompt(self.context))
        if self.context.intent != 'discuss':
            prompt += '\n先调用 read_projection 获取当前授权投影。不要读取本地项目文件。'
        offer = {
            **self._identity(), 'type': 'run', 'agentKey': self.binding.agent_key,
            'intent': self.context.intent, 'executionMode': self.context.execution_mode,
            'prompt': prompt, 'tools': [{'name': name, **TOOL_DESCRIPTORS[name]} for name in self.allowed_tools],
        }
        # Closed public runtime policy, not the credential-bearing metadata.
        offer['runtimePolicy'] = {
            'maxBudgetUsd': self.context.metadata.get('maxBudgetUsd', 1.0),
            'timeoutSeconds': self.context.metadata.get('timeoutSeconds', 900),
            'modelRef': self.context.metadata.get('modelRef'),
        }
        # Detach nested schemas from the module-level tool registry.
        return json.loads(_encode(offer, MAX_DEVICE_RUN_FRAME_BYTES))

    def request_cancel(self) -> dict[str, Any]:
        # Synchronous fencing before waiting on an in-flight tool or transport.
        if self.phase == 'running':
            self.phase = 'cancelling'
        return {**self._identity(), 'type': 'cancel'}

    def _finish(self, phase: Literal['completed', 'failed', 'stopped']) -> None:
        self.phase = phase
        self.gateway.discard_draft()
        self.finished.set()

    def _complete(self, value: _Completion) -> AgentRunOutcome:
        state = value.completion_state
        if state == 'needs_input':
            if (self.gateway.has_draft_operations or 'start_document' in self.gateway.successful_tools
                    or self.gateway.completed is not None or self.gateway.post_completion_attempted
                    or value.content is not None):
                raise MindmapArtifactError('修改脑图后不能请求补充信息')
            return agent_needs_input_result({
                'completionState': state, 'title': value.title, 'questions': value.questions,
            })
        if self.context.intent == 'discuss':
            if state != 'message_completed' or value.questions:
                raise MindmapArtifactError('讨论模式只能返回消息')
            return agent_message_result({
                'completionState': state, 'title': value.title, 'content': value.content, 'contentType': value.content_type,
            })
        if value.content is not None or value.questions:
            raise MindmapArtifactError('脑图完成摘要不能携带额外正文或问题')
        if state == 'direct_completed' and self.context.execution_mode == 'direct':
            if (self.gateway.validated_operation_cursor is None
                    or self.gateway.validated_operation_cursor != self.gateway.operation_cursor):
                raise MindmapArtifactError('最后一次脑图修改尚未通过 validate_draft')
            projection = self.context.tool_service.read_projection()
            return AgentDirectResult(
                title=str(projection['root']['data'].get('text') or 'AI 脑图'),
                summary=self.context.tool_service.authorized_scope_summary(),
            )
        if state != 'artifact_completed' or self.context.execution_mode != 'preview':
            raise MindmapArtifactError('设备完成状态与本轮契约不一致')
        if (self.gateway.completed is None or self.gateway.post_completion_attempted
                or not self.gateway.successful_tools or self.gateway.successful_tools[-1] != 'complete_artifact'):
            raise MindmapArtifactError('设备尚未通过 complete_artifact 完成脑图')
        return AgentRunResult(**self.gateway.completed)

    async def handle(self, raw: bytes | str) -> bytes:  # noqa: PLR0912, PLR0915
        async with self._lock:
            try:
                if isinstance(raw, str):
                    raw = raw.encode('utf-8')
                if len(raw) > MAX_DEVICE_RUN_FRAME_BYTES:
                    raise ValueError
                frame = _FRAME_ADAPTER.validate_json(raw)
                canonical = _encode(frame.model_dump(by_alias=True), MAX_DEVICE_RUN_FRAME_BYTES)
                digest = hashlib.sha256(canonical).hexdigest()
                if frame.run_id != self.binding.run_id or frame.execution_epoch != self.binding.execution_epoch:
                    raise ValueError
                if self.phase in {'completed', 'failed', 'stopped'}:
                    # Only a last terminal acknowledgement can be repeated.
                    if frame.sequence == self._sequence and digest == self._last_digest and isinstance(frame, (_Completed, _Failed, _Stopped)):
                        return self._last_reply
                    raise ValueError
                if self.phase == 'closed':
                    raise ValueError
                if self.phase == 'cancelling' and not isinstance(frame, (_Stopped, _Failed)):
                    raise DeviceRunFenced
                if self.phase == 'running':
                    await self._check_authority()
                if frame.sequence == self._sequence:
                    if digest != self._last_digest:
                        raise ValueError
                    return self._last_reply
                stopping = self.phase == 'cancelling' and isinstance(frame, (_Stopped, _Failed))
                if frame.sequence != self._sequence + 1 and not (stopping and frame.sequence > self._sequence):
                    raise ValueError
                reply: dict[str, Any] = {**self._identity(), 'type': 'ack', 'sequence': frame.sequence}
                if isinstance(frame, _ToolCall):
                    if frame.tool_name not in self.allowed_tools:
                        raise MindmapArtifactError('设备请求未授权的工具', code='AI_SANDBOX_VIOLATION')
                    reply['toolResult'] = await self.gateway.call(frame.tool_name, frame.arguments)
                    if self.gateway.terminal_error:
                        raise self.gateway.terminal_error
                elif isinstance(frame, _Text):
                    self._text_chars += len(frame.text)
                    if self._text_chars > MAX_TRACE_CHARS:
                        raise MindmapArtifactError('设备公开过程超过上限', code='AI_INPUT_TOO_LARGE')
                    kind = 'assistant_delta' if frame.channel == 'assistant' else 'thinking_summary'
                    await self._emit_guarded(kind, {'messageId': frame.message_id, 'text': public_text(frame.text, 4000),
                                                    'visibility': 'visible' if frame.channel == 'assistant' else 'summary'})
                elif isinstance(frame, _Thinking):
                    await self._emit_guarded('thinking_state', {'stage': 'thinking', 'visibility': 'status'})
                elif isinstance(frame, _Completed):
                    if frame.process_stopped is not True:
                        raise MindmapArtifactError('设备进程尚未停止，不能接受结果', code='AI_AGENT_CLEANUP_FAILED')
                    if self.gateway.terminal_error:
                        raise self.gateway.terminal_error
                    self.result = self._complete(frame.completion)
                    self._finish('completed')
                elif isinstance(frame, _Stopped):
                    if self.phase != 'cancelling' or frame.process_stopped is not True:
                        raise MindmapArtifactError('设备未确认停止', code='AI_AGENT_CLEANUP_FAILED')
                    self._finish('stopped')
                elif isinstance(frame, _Failed):
                    code = frame.error_code if frame.process_stopped else 'AI_AGENT_CLEANUP_FAILED'
                    self.error = MindmapArtifactError(ERROR_MESSAGES[code], code=code)
                    self._finish('failed')
                encoded = _encode(reply)
                self._sequence = frame.sequence
                self._last_digest = digest
                self._last_reply = encoded
                return encoded
            except asyncio.CancelledError:
                self.request_cancel()
                raise
            except Exception as exc:
                self.error = (exc if isinstance(exc, MindmapArtifactError)
                              else MindmapArtifactError('设备执行协议无效', code='AI_SANDBOX_VIOLATION'))
                self.request_cancel()
                raise self.error from exc

    async def close(self) -> None:
        self.request_cancel()
        async with self._lock:
            self.gateway.discard_draft()
            self.phase = 'closed'
            self.finished.set()
