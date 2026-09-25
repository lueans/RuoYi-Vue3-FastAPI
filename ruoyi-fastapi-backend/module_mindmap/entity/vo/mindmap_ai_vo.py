"""AI 脑图接口模型。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from module_mindmap.ai.document import AI_ALLOWED_LAYOUTS

AI_INTENTS = frozenset({
    'create',
    'expand',
    'rewrite_branch',
    'condense_branch',
    'reorganize',
    'discuss',
})
MAX_MODEL_REF_LENGTH = 128
MAX_RETENTION_DAYS = 365
ASCII_CONTROL_END = 32
ASCII_FIRST_VISIBLE = ASCII_CONTROL_END + 1
ASCII_DELETE = 127
LANGUAGE_REGION_LENGTH = 2
LANGUAGE_SCRIPT_LENGTH = 4
ENV_CREDENTIAL_REF_PATTERN = re.compile(r'^env://[A-Z][A-Z0-9_]{1,127}$')
OUTPUT_LANGUAGE_PATTERN = re.compile(
    r'^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$'
)
MindmapNodeUid = Annotated[str, Field(min_length=1, max_length=64)]


class MindmapAiConnectorUpdateModel(BaseModel):
    """运营配置；credentialRef 只能指向服务端密钥，不接收明文密钥。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    enabled: bool | None = None
    rollout_percentage: int | None = Field(default=None, ge=0, le=100)
    credential_ref: str | None = Field(default=None, max_length=255)
    data_region: str | None = Field(default=None, max_length=64)
    retention_policy: str | None = Field(default=None, max_length=100)
    network_policy: Literal['adapter_default', 'deny'] | None = None
    model_allowlist: list[str] | None = Field(default=None, max_length=50)
    max_budget_usd: float | None = Field(default=None, ge=0.0001, le=1_000, allow_inf_nan=False)
    timeout_seconds: int | None = Field(default=None, ge=30, le=900)
    max_nodes: int | None = Field(default=None, ge=5, le=2_000)
    max_depth: int | None = Field(default=None, ge=2, le=32)
    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=100)

    @field_validator('credential_ref')
    @classmethod
    def validate_credential_ref(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            return ''
        if normalized.startswith('env://'):
            if not ENV_CREDENTIAL_REF_PATTERN.fullmatch(normalized):
                raise ValueError('credentialRef 中的环境变量名称无效')
        elif normalized.startswith('secret://'):
            secret_path = normalized.removeprefix('secret://')
            if not secret_path or any(
                ord(char) < ASCII_FIRST_VISIBLE or ord(char) == ASCII_DELETE
                for char in secret_path
            ):
                raise ValueError('credentialRef 中的密钥路径无效')
        else:
            raise ValueError('credentialRef 只能使用 env:// 或 secret:// 服务端密钥引用')
        return normalized

    @field_validator('retention_policy')
    @classmethod
    def validate_retention_policy(cls, value: str | None) -> str | None:
        if value is None or value == '':
            return value
        if not value.endswith('d') or not value[:-1].isdigit():
            raise ValueError('结果保留策略必须使用 1d 到 365d 格式')
        days = int(value[:-1])
        if not 1 <= days <= MAX_RETENTION_DAYS:
            raise ValueError('结果保留策略必须使用 1d 到 365d 格式')
        return f'{days}d'

    @field_validator('model_allowlist')
    @classmethod
    def normalize_model_allowlist(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            model_ref = item.strip()
            if not model_ref:
                continue
            if len(model_ref) > MAX_MODEL_REF_LENGTH:
                raise ValueError('模型引用不能超过 128 个字符')
            if model_ref not in normalized:
                normalized.append(model_ref)
        return normalized


class MindmapAiConnectorModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    agent_key: str
    display_name: str
    enabled: bool
    rollout_percentage: int
    credential_configured: bool
    data_region: str | None = None
    retention_policy: str | None = None
    network_policy: str
    model_allowlist: list[str]
    max_budget_usd: float
    timeout_seconds: int
    max_nodes: int
    max_depth: int
    retention_days: int
    max_concurrent_jobs: int
    health_status: str
    health_reason: str | None = None
    conformance_status: str
    conformance_report: dict[str, Any] | None = None
    last_health_time: datetime | None = None
    last_conformance_time: datetime | None = None
    manifest: dict[str, Any]


class MindmapAiScopeModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    type: Literal['document', 'branch', 'selectedNodes'] = 'document'
    root_uid: str | None = Field(default=None, min_length=1, max_length=64)
    node_uids: list[MindmapNodeUid] | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def validate_scope(self) -> MindmapAiScopeModel:
        if self.type == 'branch' and not self.root_uid:
            raise ValueError('分支范围必须提供 rootUid')
        if self.type == 'selectedNodes' and not self.node_uids:
            raise ValueError('选中节点范围必须提供 nodeUids')
        if self.node_uids:
            self.node_uids = list(dict.fromkeys(self.node_uids))
        return self


class MindmapAiSourceModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    type: Literal['none', 'local_snapshot', 'cloud_document', 'uploaded_artifact'] = 'none'
    document_id: str | None = Field(default=None, max_length=64)
    mindmap_id: int | None = Field(default=None, gt=0)
    revision: int | None = Field(default=None, ge=0)
    document_hash: str | None = Field(default=None, max_length=80)
    room_epoch: str | None = Field(default=None, max_length=64)
    scope: MindmapAiScopeModel = Field(default_factory=MindmapAiScopeModel)
    document: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None
    baseline_document: dict[str, Any] | None = None

    @model_validator(mode='after')
    def validate_source(self) -> MindmapAiSourceModel:
        if self.type == 'local_snapshot':
            if not self.document_id or self.revision is None or self.document is None:
                raise ValueError('本地脑图来源必须提供 documentId、revision 和 document')
            if self.mindmap_id is not None or self.room_epoch is not None or self.artifact is not None:
                raise ValueError('本地脑图来源不能携带云端脑图标识或上传文件')
        elif self.type == 'cloud_document':
            if self.mindmap_id is None:
                raise ValueError('云端脑图来源必须提供 mindmapId')
            if self.document_id is not None or self.artifact is not None:
                raise ValueError('云端脑图来源不能携带本地文档标识或上传文件')
        elif self.type == 'uploaded_artifact':
            if (
                self.document_id is not None
                or self.mindmap_id is not None
                or self.room_epoch is not None
            ):
                raise ValueError('上传文件来源不能携带本地或云端脑图标识')
            has_artifact = self.artifact is not None
            has_document = self.document is not None
            if has_artifact == has_document:
                raise ValueError('上传文件来源必须且只能提供 artifact 或 document')
        elif any((
            self.document_id is not None,
            self.mindmap_id is not None,
            self.revision is not None,
            self.document_hash is not None,
            self.room_epoch is not None,
            self.document is not None,
            self.artifact is not None,
            self.baseline_document is not None,
        )):
            raise ValueError('新建脑图来源不能携带现有文档或上传文件数据')
        return self


class MindmapAiParametersModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    language: str = Field(default='zh-CN', min_length=2, max_length=16)
    layout: str = Field(default='logicalStructure', min_length=1, max_length=50)
    max_depth: int = Field(default=6, ge=2, le=32)
    max_nodes: int = Field(default=100, ge=5, le=2000)
    density: Literal['concise', 'standard', 'detailed'] = 'standard'
    # 生成节奏只影响 add_nodes/update_nodes 的批次提示词；工具层硬上限不变。
    generation_mode: Literal['dfs_stream', 'bfs_stream', 'balanced', 'complete'] = 'balanced'

    @field_validator('language')
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = value.strip()
        if not OUTPUT_LANGUAGE_PATTERN.fullmatch(normalized):
            raise ValueError('AI 输出语言代码无效')
        parts = normalized.split('-')
        canonical = [parts[0].lower()]
        for part in parts[1:]:
            if len(part) == LANGUAGE_REGION_LENGTH and part.isalpha():
                canonical.append(part.upper())
            elif len(part) == LANGUAGE_SCRIPT_LENGTH and part.isalpha():
                canonical.append(part.title())
            else:
                canonical.append(part)
        return '-'.join(canonical)

    @field_validator('layout')
    @classmethod
    def validate_layout(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in AI_ALLOWED_LAYOUTS:
            raise ValueError('AI 目标布局无效')
        return normalized


class MindmapAiJobCreateModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    agent_key: str = Field(default='native_mindmap', min_length=1, max_length=64)
    model_id: int | None = Field(default=None, gt=0)
    intent: str = Field(default='create', min_length=1, max_length=32)
    prompt: str = Field(min_length=1, max_length=20_000)
    parameters: MindmapAiParametersModel = Field(default_factory=MindmapAiParametersModel)
    source: MindmapAiSourceModel = Field(default_factory=MindmapAiSourceModel)
    target: Literal['file', 'proposal', 'message'] = 'file'
    # preview 保留旧的 Artifact/Proposal 结果契约；direct 将 Agent 的每个
    # 已验证工具批次直接提交到云端脑图，任务不依赖当前页面存活。
    execution_mode: Literal['preview', 'direct'] = 'preview'

    @field_validator('prompt')
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('AI 脑图要求不能为空')
        return normalized

    @field_validator('intent')
    @classmethod
    def validate_intent(cls, value: str) -> str:
        if value not in AI_INTENTS:
            raise ValueError('不支持的 AI 脑图意图')
        return value

    @model_validator(mode='after')
    def validate_target(self) -> MindmapAiJobCreateModel:
        if self.intent == 'discuss':
            if self.target != 'message':
                raise ValueError('讨论模式只能生成文字消息')
        elif self.target == 'message':
            raise ValueError('只有讨论模式才能生成文字消息')
        if self.target == 'proposal' and self.source.type not in {'local_snapshot', 'cloud_document'}:
            raise ValueError('只有现有本地或云端脑图才能生成 proposal')
        if self.source.type == 'none' and self.intent not in {'create', 'discuss'}:
            raise ValueError('该意图必须提供脑图来源')
        if self.execution_mode == 'direct':
            if self.intent == 'discuss':
                raise ValueError('讨论模式不能直接写入脑图')
            if self.source.type != 'cloud_document' or self.source.mindmap_id is None:
                raise ValueError('直接写入模式必须使用可编辑的云端脑图')
            if self.target != 'file':
                raise ValueError('直接写入模式不生成提案或文字消息，target 必须为 file')
        return self


class MindmapAiArtifactValidateModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    artifact: dict[str, Any]
    require_passed: bool = True


class MindmapAiMessageModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    prompt: str = Field(min_length=1, max_length=20_000)
    artifact_id: str | None = Field(default=None, min_length=36, max_length=36)
    agent_key: str | None = Field(default=None, min_length=1, max_length=64)
    model_id: int | None = Field(default=None, gt=0)
    intent: str | None = Field(default=None, min_length=1, max_length=32)
    route: Literal['current', 'next'] = 'current'
    continuation_base: Literal[
        'artifact', 'current_document', 'current_snapshot',
    ] = 'artifact'
    expected_parent_status: Literal['applied', 'undone', 'completed_direct'] | None = None
    source: MindmapAiSourceModel | None = None

    @field_validator('prompt')
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('继续调整要求不能为空')
        return normalized

    @field_validator('intent')
    @classmethod
    def validate_intent(cls, value: str | None) -> str | None:
        if value is not None and value not in AI_INTENTS:
            raise ValueError('不支持的 AI 脑图意图')
        return value

    @model_validator(mode='after')
    def validate_continuation_source(self) -> MindmapAiMessageModel:
        if self.continuation_base == 'current_snapshot':
            if (
                self.source is None
                or self.source.type != 'local_snapshot'
                or not self.source.document_hash
                or self.expected_parent_status is None
            ):
                raise ValueError('本地当前快照续写必须提供完整内容、哈希与父任务状态')
        elif self.source is not None or self.expected_parent_status is not None:
            raise ValueError('只有本地当前快照续写可以携带 source 与父任务状态')
        return self


class MindmapAiCancelModel(BaseModel):
    """Cancellation intent; preserving a live draft creates an undoable result."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    preserve_draft: bool = False


class MindmapAiRetryParametersModel(BaseModel):
    """Retry-only parameter overrides; omitted fields inherit the failed turn."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    language: str | None = Field(default=None, min_length=2, max_length=16)
    layout: str | None = Field(default=None, min_length=1, max_length=50)
    max_depth: int | None = Field(default=None, ge=2, le=32)
    max_nodes: int | None = Field(default=None, ge=5, le=2000)
    density: Literal['concise', 'standard', 'detailed'] | None = None
    generation_mode: Literal[
        'dfs_stream', 'bfs_stream', 'balanced', 'complete',
    ] | None = None

    @field_validator('language')
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return MindmapAiParametersModel.validate_language(value)

    @field_validator('layout')
    @classmethod
    def validate_layout(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return MindmapAiParametersModel.validate_layout(value)


class MindmapAiJobRetryModel(BaseModel):
    """Create a fresh turn from a failed terminal job without provider-session reuse."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    agent_key: str | None = Field(default=None, min_length=1, max_length=64)
    model_id: int | None = Field(default=None, gt=0)
    prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    parameters: MindmapAiRetryParametersModel | None = None

    @field_validator('prompt')
    @classmethod
    def normalize_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError('重试要求不能为空')
        return normalized


class MindmapAiLocalApplyAckModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    document_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)
    result_hash: str = Field(min_length=1, max_length=80)


class MindmapAiLocalUndoAckModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    document_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=2)
    result_hash: str = Field(min_length=1, max_length=80)
    reverted_hash: str = Field(min_length=1, max_length=80)


class MindmapAiCloudSaveModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    folder_id: int | None = Field(default=None, gt=0)

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError('云端脑图名称不能为空')
        if any(ord(char) < ASCII_CONTROL_END or ord(char) == ASCII_DELETE for char in normalized):
            raise ValueError('云端脑图名称不能包含控制字符')
        return normalized


class MindmapAiCloudApplyModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    content_revision: int = Field(ge=1)
    base_hash: str = Field(min_length=1, max_length=80)
    room_epoch: str | None = Field(default=None, max_length=64)
    force_overwrite: bool = False


class MindmapAiJobModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: str
    session_id: str
    parent_job_id: str | None = None
    retry_of_job_id: str | None = None
    turn_index: int = Field(default=1, ge=1)
    agent_key: str
    adapter_version: str
    sdk_version: str | None = None
    runtime_version: str | None = None
    model_ref: str | None = None
    max_budget_usd: float
    timeout_seconds: int
    max_nodes: int
    max_depth: int
    retention_days: int
    intent: str
    target: str
    execution_mode: Literal['preview', 'direct'] = 'preview'
    source_type: str
    source_mindmap_id: int | None = None
    base_revision: int | None = None
    base_hash: str | None = None
    base_room_epoch: str | None = None
    status: str
    progress: int = Field(ge=0, le=100)
    title: str | None = None
    artifact_id: str | None = None
    proposal_id: str | None = None
    response_id: str | None = None
    usage: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_time: datetime
    update_time: datetime
    completed_time: datetime | None = None
    expires_time: datetime


class MindmapAiResponseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: str
    job_id: str
    content: str
    content_type: Literal['text/plain']
    created_time: datetime
    expires_time: datetime


class MindmapAiProposalModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: str
    job_id: str
    proposal_type: str
    base_document_id: str | None = None
    target_mindmap_id: int | None = None
    base_revision: int | None = None
    base_hash: str | None = None
    base_room_epoch: str | None = None
    scope: dict[str, Any]
    operations: list[dict[str, Any]]
    result_artifact_id: str
    result_hash: str
    impact: dict[str, Any]
    warnings: list[dict[str, Any]]
    status: str
    applied_revision: int | None = None
    created_time: datetime
    expires_time: datetime
