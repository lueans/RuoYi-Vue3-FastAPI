"""AI 脑图任务编排、Artifact 与 Proposal 服务。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
import uuid
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from config.database import AsyncSessionLocal
from config.env import MindmapAiConfig
from exceptions.exception import ServiceException, ServiceWarning
from module_ai.dao.ai_model_dao import AiModelDao
from module_ai.entity.do.ai_model_do import AiModels
from module_mindmap.ai.adapters.base import (
    AgentDirectResult,
    AgentMessageResult,
    AgentNeedsInputResult,
    AgentRunContext,
    map_adapter_exception,
    normalize_agent_input_questions,
    normalize_agent_message,
    run_adapter_with_transient_retries,
)
from module_mindmap.ai.adapters.conformance import build_agent_conformance_report
from module_mindmap.ai.adapters.factory import get_mindmap_agent_registry
from module_mindmap.ai.change_summary import (
    CHANGE_SUMMARY_VERSION,
    has_complete_change_evidence,
    summarize_committed_node_changes,
)
from module_mindmap.ai.checkpoint_crypto import MindmapAiCheckpointCrypto
from module_mindmap.ai.credentials import resolve_connector_credential
from module_mindmap.ai.diff import build_document_diff
from module_mindmap.ai.document import (
    AI_MAX_FILE_BYTES,
    AI_MAX_NODE_COUNT,
    MindmapArtifactError,
    build_smm_artifact,
    canonical_json_bytes,
    compute_document_hash,
    document_from_mindmap_detail,
    normalize_ai_editable_source_document,
    validate_smm_artifact,
)
from module_mindmap.ai.proposal_operations import (
    PROPOSAL_INTEGRITY_ERROR_CODE,
    materialize_editor_document_from_proposal,
    normalize_proposal_operations_for_apply,
    verify_proposal_document_integrity,
)
from module_mindmap.ai.tool_contract import MindmapToolService, normalize_tag_suggestions
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiCloudApplyModel,
    MindmapAiCloudSaveModel,
    MindmapAiConnectorModel,
    MindmapAiConnectorUpdateModel,
    MindmapAiJobCreateModel,
    MindmapAiJobModel,
    MindmapAiJobRetryModel,
    MindmapAiLocalApplyAckModel,
    MindmapAiLocalUndoAckModel,
    MindmapAiMessageModel,
    MindmapAiProposalModel,
    MindmapAiResponseModel,
)
from module_mindmap.entity.vo.mindmap_vo import MindmapContentBatchModel, MindmapModel
from module_mindmap.service.mindmap_ai_metrics import (
    record_mindmap_ai_event,
    record_mindmap_ai_run,
)
from module_mindmap.service.mindmap_ai_mutation_gateway import MindmapAiMutationGateway, _document_from_detail
from module_mindmap.service.mindmap_ai_tag_catalog import load_ai_tag_catalog
from module_mindmap.service.mindmap_comment_service import MindmapCommentService
from module_mindmap.service.mindmap_service import MindmapService
from utils.ai_util import AiUtil
from utils.crypto_util import CryptoUtil
from utils.log_util import logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

TERMINAL_JOB_STATUSES = frozenset({
    'ready',
    'applied',
    'undone',
    'completed_file',
    'completed_no_change',
    'completed_direct',
    'needs_review',
    'rejected',
    'stale',
    'cancelled',
    'failed',
    'expired',
    'needs_input',
    'completed_message',
})
RETRYABLE_JOB_STATUSES = frozenset({'failed', 'cancelled', 'expired', 'stale'})
RETENTION_ELIGIBLE_JOB_STATUSES = TERMINAL_JOB_STATUSES
RETAINED_AUDIT_JOB_STATUSES = frozenset({'applied', 'undone', 'completed_file', 'completed_direct'})
RETENTION_SHUTDOWN_TIMEOUT_SECONDS = 5.0
ACTIVE_JOB_STATUSES = frozenset({
    'queued', 'preparing', 'running', 'validating', 'cancel_requested',
})
WAITING_TURN_STATUS = 'waiting_turn'
WAITING_FOLLOWUP_ROUTES = frozenset({'current', 'next'})
JOB_STATUS_PREDECESSORS: dict[str, frozenset[str]] = {
    'preparing': frozenset({'queued'}),
    'running': frozenset({'preparing'}),
    'validating': frozenset({'running'}),
    'queued': frozenset({'preparing', 'running', 'validating', WAITING_TURN_STATUS}),
    'cancelled': ACTIVE_JOB_STATUSES | {WAITING_TURN_STATUS},
    # A direct-write task may have already committed earlier batches before a
    # later batch races with a collaborator. Keep that outcome distinct from
    # a provider failure so the UI can ask the user to resync/retry knowingly.
    'stale': ACTIVE_JOB_STATUSES,
    'failed': frozenset({'queued', 'preparing', 'running', 'validating'}),
    'needs_input': frozenset({'running'}),
}
AI_DRAFT_PREVIEW_KEY_PREFIX = 'mindmap:ai:draft-preview:'
AI_DRAFT_PREVIEW_TTL_SECONDS = 60 * 60
AI_DRAFT_PREVIEW_FRAME_TTL_SECONDS = 5 * 60
AI_DRAFT_PREVIEW_MAX_VERSION = 1_000_000
AI_DRAFT_PREVIEW_MAX_FRAMES = 16
CONNECTOR_HEALTHCHECK_TIMEOUT_SECONDS = 65.0
AI_DRAFT_PREVIEW_MAX_TOTAL_BYTES = 8 * 1024 * 1024
AI_DRAFT_PREVIEW_MAX_LATEST_BYTES = 2 * 1024 * 1024
AI_DRAFT_CHECKPOINT_MAX_PLAINTEXT_BYTES = AI_DRAFT_PREVIEW_MAX_TOTAL_BYTES
AI_DRAFT_CHECKPOINT_MAX_CIPHERTEXT_BYTES = 12 * 1024 * 1024
AI_EVENT_SAFE_FIELDS = frozenset({
    'status', 'progress', 'agentKey', 'stage', 'toolName', 'step', 'totalSteps',
    'actionCount', 'tools', 'errorCode', 'errorMessage',
    'hasResponse', 'summary', 'parentJobId', 'retryOfJobId', 'turnIndex', 'artifactId', 'proposalId',
    'previewAvailable', 'previewVersion', 'previewEpoch', 'changeCount', 'issueCount', 'messageType',
    'intent', 'sourceType', 'revision', 'mindmapId', 'contentRevision', 'usage',
    'rebasedFromRevision', 'forceOverwrite',
    'sessionMode', 'continuationBase', 'budgetEnforcement', 'responseId', 'executionMode',
    'directCommit', 'operationGroupId', 'operationCount', 'affectedUids', 'commentCount',
    'changeSummary', 'changeSummaryVersion',
    'questions', 'route', 'queuePosition',
    'completionReason',
    'suggestions',
})
AI_EVENT_SUMMARY_FIELDS = frozenset({
    'nodeCount', 'treeDepth', 'bytes', 'issueCount', 'status', 'changeSummary',
})
AI_EVENT_USAGE_FIELDS = frozenset({'inputTokens', 'outputTokens', 'totalTokens'})
AI_TIMELINE_EVENT_PAGE_SIZE = 1_000
AI_PROMPT_MAX_LENGTH = 20_000
AI_DISCUSSION_HISTORY_MAX_MESSAGES = 20
AI_DISCUSSION_HISTORY_MAX_CHARS = 40_000
AI_SESSION_INITIAL_TITLE_MAX_LENGTH = 36
_SESSION_TITLE_CONTROL_PATTERN = re.compile(r'[\x00-\x1f\x7f]')
AI_JOB_LEASE_KEY_PREFIX = 'mindmap:ai:job-lease:'
_RENEW_JOB_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], tonumber(ARGV[2]))
end
return 0
"""
_RELEASE_JOB_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
_PUBLISH_DRAFT_EXECUTION_SCRIPT = """
-- mindmap-ai:publish-draft-execution
if redis.call('exists', KEYS[1]) == 1 then
    return 0
end
local current_epoch = redis.call('get', KEYS[2])
local incoming_epoch = tonumber(ARGV[1])
if not incoming_epoch then
    return 0
end
if current_epoch then
    local parsed_current_epoch = tonumber(current_epoch)
    if not parsed_current_epoch or parsed_current_epoch > incoming_epoch then
        return 0
    end
end
redis.call('set', KEYS[2], ARGV[1], 'EX', tonumber(ARGV[2]))
return 1
"""
_STORE_DRAFT_PREVIEW_SCRIPT = """
-- mindmap-ai:store-draft-preview
if redis.call('exists', KEYS[1]) == 1 then
    return -1
end
if redis.call('get', KEYS[2]) ~= ARGV[1] then
    return -2
end
local current_value = redis.call('get', KEYS[3])
if ARGV[2] == '0' then
    if current_value then
        return 0
    end
elseif current_value ~= ARGV[3] then
    return 0
end
for index = 5, #KEYS do
    redis.call('del', KEYS[index])
end
if ARGV[4] == '1' then
    redis.call('set', KEYS[4], ARGV[5], 'EX', tonumber(ARGV[6]))
else
    redis.call('del', KEYS[4])
end
redis.call('set', KEYS[3], ARGV[7], 'EX', tonumber(ARGV[8]))
return 1
"""
_DELETE_DRAFT_PREVIEW_SCRIPT = """
-- mindmap-ai:delete-draft-preview
local terminal_epoch = redis.call('get', KEYS[1])
if terminal_epoch and terminal_epoch ~= ARGV[1] then
    return -1
end
local current_epoch = redis.call('get', KEYS[2])
if current_epoch and current_epoch ~= ARGV[1] then
    return -2
end
local current_value = redis.call('get', KEYS[3])
if not current_epoch and current_value then
    local decoded_ok, decoded = pcall(cjson.decode, current_value)
    if decoded_ok and decoded.executionEpoch
        and tostring(decoded.executionEpoch) ~= ARGV[1] then
        return -3
    end
end
if ARGV[2] == '0' then
    if current_value then
        return 0
    end
elseif current_value ~= ARGV[3] then
    return 0
end
for index = 3, #KEYS do
    redis.call('del', KEYS[index])
end
return 1
"""
_MARK_DRAFT_TERMINAL_SCRIPT = """
-- mindmap-ai:mark-draft-terminal
local terminal_epoch = redis.call('get', KEYS[1])
if terminal_epoch and terminal_epoch ~= ARGV[1] then
    return -1
end
local current_epoch = redis.call('get', KEYS[2])
if current_epoch and current_epoch ~= ARGV[1] then
    return -2
end
local current_value = redis.call('get', KEYS[3])
if not current_epoch and current_value then
    local decoded_ok, decoded = pcall(cjson.decode, current_value)
    if decoded_ok and decoded.executionEpoch
        and tostring(decoded.executionEpoch) ~= ARGV[1] then
        return -3
    end
end
if ARGV[2] == '0' then
    if current_value then
        return 0
    end
elseif current_value ~= ARGV[3] then
    return 0
end
redis.call('set', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[4]))
for index = 3, #KEYS do
    redis.call('del', KEYS[index])
end
return 1
"""
_DRAFT_PREVIEW_CAS_RETRIES = 8
_CURRENT_JOB_LEASE_TOKEN: ContextVar[str | None] = ContextVar(
    'mindmap_ai_job_lease_token',
    default=None,
)
_CURRENT_JOB_EXECUTION_EPOCH: ContextVar[int | None] = ContextVar(
    'mindmap_ai_job_execution_epoch',
    default=None,
)


@dataclass(frozen=True, slots=True)
class AgentRuntimePolicy:
    model_allowlist: tuple[str, ...]
    max_budget_usd: float
    timeout_seconds: int
    max_nodes: int
    max_depth: int
    max_concurrent_jobs: int
    retention_days: int


@dataclass(frozen=True, slots=True)
class DraftPreviewRun:
    """把 Adapter 的本地操作游标映射为同一 job 内跨恢复单调的版本。"""

    epoch: int
    version_offset: int


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _request_with_undo_baseline(payload: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Attach server-only raw bytes after public-model validation/fingerprinting."""
    result = dict(payload)
    result.pop('_directUndoBaseline', None)
    if baseline:
        result['_directUndoBaseline'] = baseline
    return result


def _restore_preview_document(request: MindmapAiJobCreateModel, document: dict[str, Any]) -> dict[str, Any]:
    if request.source.document is None:
        return document
    tools = MindmapToolService(
        base_document=request.source.document,
        scope=request.source.scope.model_dump(by_alias=True, exclude_none=True),
        trusted_source=True,
    )
    return tools.restore_checkpoint_projection(document)


def _raw_direct_undo_baseline(job: Any) -> dict[str, Any] | None:
    payload = _json_loads(getattr(job, 'request_json', None), {})
    baseline = payload.get('_directUndoBaseline')
    if not isinstance(baseline, dict) or any((
        baseline.get('schemaVersion') != 1,
        baseline.get('mindmapId') != job.source_mindmap_id,
        baseline.get('revision') != job.base_revision,
        baseline.get('documentHash') != getattr(job, 'base_hash', None),
        not isinstance(baseline.get('document'), dict),
    )):
        return None
    try:
        normalized, _summary = normalize_ai_editable_source_document(baseline['document'])
    except (MindmapArtifactError, TypeError, ValueError):
        return None
    return baseline['document'] if compute_document_hash(normalized) == baseline['documentHash'] else None


def _initial_session_title(prompt: str) -> str:
    """Create a deterministic title before any provider response exists."""
    normalized = ' '.join(_SESSION_TITLE_CONTROL_PATTERN.sub(' ', prompt).split())
    return normalized[:AI_SESSION_INITIAL_TITLE_MAX_LENGTH] or '新对话'


def _json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _is_high_impact_proposal(proposal: Any) -> bool:
    impact = _json_loads(getattr(proposal, 'impact_json', None), {})
    return isinstance(impact, dict) and impact.get('highImpact') is True


def _waiting_followup_route(job: Any) -> str:
    """Read the durable route selected for a queued follow-up.

    ``queueRoute`` was added after the first queue implementation.  Existing
    rows intentionally fall back to ``current`` so an upgrade never strands a
    message waiting for a route value that was not persisted at creation time.
    """
    payload = _json_loads(getattr(job, 'request_json', None), {})
    route = payload.get('queueRoute') if isinstance(payload, dict) else None
    return route if route in WAITING_FOLLOWUP_ROUTES else 'current'


def _proposal_integrity_service_exception(exc: BaseException) -> ServiceException:
    return ServiceException(
        data={'errorCode': PROPOSAL_INTEGRITY_ERROR_CODE},
        message='AI 脑图提案完整性校验失败，请重新生成任务',
    )


def _session_accepts_work(session: Any, *, now: datetime | None = None) -> bool:
    """An active label cannot revive a session past its retention deadline."""
    if session is None or getattr(session, 'status', None) != 'active':
        return False
    expires_time = getattr(session, 'expires_time', None)
    return not isinstance(expires_time, datetime) or expires_time > (now or datetime.now())


def _manifest_supports_result(manifest: Any, result_type: str) -> bool:
    """Keep pre-discussion third-party manifests artifact-only by default."""
    declared = getattr(manifest, 'result_types', ('artifact',))
    return isinstance(declared, (tuple, list, set, frozenset)) and result_type in declared


def _stable_create_fingerprint(request_model: MindmapAiJobCreateModel) -> str:
    """Hash only client intent, never mutable server-fetched cloud contents."""
    request_payload = request_model.model_dump(by_alias=True, exclude_none=True)
    if request_model.source.type == 'cloud_document':
        source_payload = request_payload.get('source') or {}
        for field in (
            'document',
            'baselineDocument',
            'revision',
            'documentHash',
            'roomEpoch',
        ):
            source_payload.pop(field, None)
    fingerprint_payload = {'operation': 'create', 'request': request_payload}
    return hashlib.sha256(canonical_json_bytes(fingerprint_payload)).hexdigest()


def _stable_followup_fingerprint(
    parent_job_id: str,
    model: MindmapAiMessageModel,
) -> str:
    fingerprint_payload = {
        'operation': 'followup',
        'parentJobId': parent_job_id,
        'message': model.model_dump(by_alias=True, exclude_none=True),
    }
    return hashlib.sha256(canonical_json_bytes(fingerprint_payload)).hexdigest()


def _stable_retry_fingerprint(
    retry_of_job_id: str,
    model: MindmapAiJobRetryModel,
) -> str:
    """Fingerprint only the user's retry intent, before mutable cloud state is fetched."""
    fingerprint_payload = {
        'operation': 'retry',
        'retryOfJobId': retry_of_job_id,
        'overrides': model.model_dump(by_alias=True, exclude_unset=True),
    }
    return hashlib.sha256(canonical_json_bytes(fingerprint_payload)).hexdigest()


_LEGACY_GENERATED_NODE_LIMIT_PATTERN = re.compile(
    r'\A生成结果包含 (?P<actual>[1-9]\d{0,8}) 个节点，超过上限 '
    r'(?P<limit>[1-9]\d{0,8})\Z',
)
_LEGACY_RESULT_STRUCTURE_LIMIT_PATTERN = re.compile(
    r'\AAgent 输出超过任务结构上限（(?:最终节点|累计新增节点) '
    r'(?P<actual>[1-9]\d{0,8})/(?P<limit>[1-9]\d{0,8})，最终层级 '
    r'(?P<depth>[1-9]\d{0,8})/(?P<depth_limit>[1-9]\d{0,8})）\Z',
)
_LEGACY_ARTIFACT_LIMIT_PATTERN = re.compile(
    r'\AAI 脑图(?:节点数量|层级)不能超过[1-9]\d{0,8}\Z',
)
_LEGACY_ARTIFACT_BYTE_LIMIT_PATTERN = re.compile(
    r'\AAI 脑图(?:规范文档|文件)不能超过[1-9]\d{0,8}字节\Z',
)


def _compatible_persisted_error_code(
    error_code: Any,
    error_message: Any,
) -> Any:
    """Narrowly repair result-budget codes persisted before classification v2."""
    if (
        error_code not in {'AI_OUTPUT_INVALID', 'AI_INPUT_TOO_LARGE'}
        or not isinstance(error_message, str)
    ):
        return error_code
    node_match = _LEGACY_GENERATED_NODE_LIMIT_PATTERN.fullmatch(error_message)
    if node_match is not None and int(node_match['actual']) > int(node_match['limit']):
        return 'AI_BUDGET_EXCEEDED'
    structure_match = _LEGACY_RESULT_STRUCTURE_LIMIT_PATTERN.fullmatch(error_message)
    if structure_match is not None and (
        int(structure_match['actual']) > int(structure_match['limit'])
        or int(structure_match['depth']) > int(structure_match['depth_limit'])
    ):
        return 'AI_BUDGET_EXCEEDED'
    if (
        _LEGACY_ARTIFACT_LIMIT_PATTERN.fullmatch(error_message) is not None
        or _LEGACY_ARTIFACT_BYTE_LIMIT_PATTERN.fullmatch(error_message) is not None
    ):
        return 'AI_BUDGET_EXCEEDED'
    return error_code


def _safe_persisted_scalar(value: Any) -> str | int | float | bool | None:
    """Return a JSON-safe scalar for event/checkpoint/cache summaries.

    Provider telemetry is not trusted input.  In particular, NaN/Infinity are
    valid Python floats but invalid JSON when ``allow_nan=False`` is used by
    the durable serializers.  Filtering them at this shared boundary keeps a
    malformed progress frame from aborting an otherwise valid AI turn.
    """
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _safe_draft_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    """Use the same content-free scalar projection for durable/cache summaries."""
    return {
        key: safe_item
        for key, item in (summary or {}).items()
        if key in AI_EVENT_SUMMARY_FIELDS
        and (safe_item := _safe_persisted_scalar(item)) is not None
    }


def _safe_change_summary(value: Any) -> dict[str, int]:
    """Normalize the content-free direct-write counters for API/event output."""
    result = {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 0}
    if not isinstance(value, dict):
        return result
    aliases = {
        'added': ('added', 'createdCount'),
        'updated': ('updated', 'updatedCount'),
        'moved': ('moved', 'movedCount'),
        'deleted': ('deleted', 'deletedCount'),
    }
    for output_key, candidates in aliases.items():
        raw = next((value[key] for key in candidates if key in value), 0)
        if isinstance(raw, bool):
            raw = 0
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            parsed = 0
        result[output_key] = max(0, parsed)
    result['total'] = sum(result[key] for key in aliases)
    return result


def _merge_change_summary(
    target: dict[str, int],
    incoming: Any,
) -> dict[str, int]:
    normalized = _safe_change_summary(incoming)
    for key in ('added', 'updated', 'moved', 'deleted'):
        target[key] = max(0, int(target.get(key, 0))) + normalized[key]
    target['total'] = sum(target[key] for key in ('added', 'updated', 'moved', 'deleted'))
    return target


async def _direct_job_change_result(db: AsyncSession, job: Any) -> dict[str, Any]:  # noqa: PLR0912
    """Resolve a versioned net summary from this task's durable commits only.

    Counts in old events are operation totals, so prefer canonical logs even
    when those counts exist. If retention removed any required log, fall back
    to the complete terminal receipt (or legacy batch totals), explicitly at
    the legacy version; never mislabel a partial reconstruction as net impact.
    """
    commits: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    event_cursor = 0
    terminal: dict[str, Any] | None = None
    while True:
        event_page = await MindmapAiDao.list_events(
            db,
            str(job.id),
            event_cursor,
            limit=AI_TIMELINE_EVENT_PAGE_SIZE,
        )
        if not event_page:
            break
        for event in event_page:
            payload = _json_loads(event.payload_json, {})
            if not isinstance(payload, dict):
                continue
            direct_commit = payload.get('directCommit')
            if event.event_type == 'draft_changed' and isinstance(direct_commit, dict):
                if direct_commit.get('idempotentReplay') is True:
                    continue
                group_id = str(direct_commit.get('operationGroupId') or '')
                if group_id and group_id in seen_group_ids:
                    continue
                if group_id:
                    seen_group_ids.add(group_id)
                commits.append(direct_commit)
            elif event.event_type == 'direct_completed':
                summary = payload.get('changeSummary')
                if isinstance(summary, dict):
                    terminal = {
                        'changeSummary': _safe_change_summary(summary),
                        'changeSummaryVersion': (
                            CHANGE_SUMMARY_VERSION
                            if payload.get('changeSummaryVersion') == CHANGE_SUMMARY_VERSION else 1
                        ),
                    }
        next_cursor = int(event_page[-1].sequence)
        if len(event_page) < AI_TIMELINE_EVENT_PAGE_SIZE or next_cursor <= event_cursor:
            break
        event_cursor = next_cursor

    if terminal and terminal['changeSummaryVersion'] == CHANGE_SUMMARY_VERSION:
        return terminal
    changes = []
    if seen_group_ids and getattr(job, 'source_mindmap_id', None):
        changes = await MindmapContentDao.get_changes_by_mutations(
            db, int(job.source_mindmap_id), sorted(seen_group_ids),
        )
    by_group = {str(change.client_mutation_id): change for change in changes}
    groups = []
    complete = True
    for commit in commits:
        change = by_group.get(str(commit.get('operationGroupId') or ''))
        if change is not None and isinstance(change.operations, list):
            groups.append(change.operations)
        elif commit.get('operationCount') == 0 and not _safe_change_summary(commit.get('changeSummary'))['total']:
            # Pure comments / no-op batches have no document change-log row.
            continue
        else:
            complete = False
    if complete and has_complete_change_evidence(groups) and (commits or terminal is None):
        return {
            'changeSummary': summarize_committed_node_changes(groups),
            'changeSummaryVersion': CHANGE_SUMMARY_VERSION,
        }
    if terminal:
        return terminal
    # Legacy per-batch totals are only needed when neither a complete net
    # reconstruction nor a durable terminal receipt can answer the request.
    # Do not compute/discard every batch's projection on the normal v2 path.
    fallback = _safe_change_summary(None)
    for commit in commits:
        change = by_group.get(str(commit.get('operationGroupId') or ''))
        summary = (
            summarize_committed_node_changes([change.operations])
            if change is not None and isinstance(change.operations, list)
            else commit.get('changeSummary')
        )
        _merge_change_summary(fallback, summary)
    return {'changeSummary': fallback, 'changeSummaryVersion': 1}


def _safe_event_payload(payload: dict[str, Any]) -> dict[str, Any]:  # noqa: PLR0912, PLR0915
    """把供应商事件收敛为不含 prompt、节点正文和完整文档的审计摘要。"""
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in AI_EVENT_SAFE_FIELDS or value is None:
            continue
        if key == 'summary':
            if isinstance(value, dict):
                summary = _safe_draft_summary(value)
                if 'changeSummary' in value:
                    summary['changeSummary'] = _safe_change_summary(value['changeSummary'])
                output[key] = summary
            continue
        if key == 'tools':
            if isinstance(value, list):
                output[key] = [str(item)[:64] for item in value[:80]]
            continue
        if key == 'questions':
            try:
                output[key] = [
                    question.to_dict()
                    for question in normalize_agent_input_questions({
                        'completionState': 'needs_input',
                        'questions': value,
                    })
                ]
            except MindmapArtifactError:
                continue
            continue
        if key == 'suggestions':
            try:
                output[key] = normalize_tag_suggestions(value)
            except MindmapArtifactError:
                continue
            continue
        if key == 'usage':
            if isinstance(value, dict):
                output[key] = {
                    item_key: item_value
                    for item_key, item_value in value.items()
                    if item_key in AI_EVENT_USAGE_FIELDS
                    and isinstance(item_value, int)
                    and not isinstance(item_value, bool)
                    and item_value >= 0
                }
            continue
        if key == 'directCommit':
            if isinstance(value, dict):
                safe_commit: dict[str, Any] = {}
                for item_key in (
                    'contentRevision',
                    'operationGroupId',
                    'operationCount',
                    'commentCount',
                    'proposalId',
                ):
                    item_value = value.get(item_key)
                    if isinstance(item_value, (str, int)) and not isinstance(item_value, bool):
                        safe_commit[item_key] = str(item_value)[:100] if isinstance(item_value, str) else item_value
                replay = value.get('idempotentReplay')
                if isinstance(replay, bool):
                    safe_commit['idempotentReplay'] = replay
                uids = value.get('affectedUids')
                if isinstance(uids, list):
                    safe_commit['affectedUids'] = [str(uid)[:64] for uid in uids[:200]]
                if 'changeSummary' in value:
                    safe_commit['changeSummary'] = _safe_change_summary(value.get('changeSummary'))
                output[key] = safe_commit
            continue
        if key == 'changeSummary':
            output[key] = _safe_change_summary(value)
            continue
        if key == 'affectedUids':
            if isinstance(value, list):
                output[key] = [str(uid)[:64] for uid in value[:200]]
            continue
        safe_value = _safe_persisted_scalar(value)
        if isinstance(safe_value, str):
            output[key] = safe_value[:500]
        elif safe_value is not None:
            output[key] = safe_value
    if 'errorCode' in output:
        output['errorCode'] = _compatible_persisted_error_code(
            output['errorCode'],
            output.get('errorMessage'),
        )
    return output


def _event_json(payload: dict[str, Any]) -> str:
    """唯一的事件持久化序列化入口，避免新增事件时绕过隐私字段白名单。"""
    return _json_dumps(_safe_event_payload(payload))


def sanitize_mindmap_ai_event_payload(payload: Any) -> dict[str, Any]:
    """读取历史事件时再次收敛字段，兼容升级前可能存在的宽松 payload。"""
    return _safe_event_payload(payload) if isinstance(payload, dict) else {}


def _validate_job_result_artifact(
    artifact: dict[str, Any],
    *,
    max_node_count: int = AI_MAX_NODE_COUNT,
    expected_artifact_id: str | None = None,
    expected_agent_key: str | None = None,
    expected_adapter_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """在任务边界重新签发校验结论，不能信任 Adapter 自报的 passed。"""
    try:
        validated, summary = validate_smm_artifact(
            artifact,
            require_passed=True,
            max_node_count=max_node_count,
        )
    except MindmapArtifactError as exc:
        if exc.code == 'AI_INPUT_TOO_LARGE':
            # At this boundary the source input was already normalized before
            # the provider ran. A size overflow therefore belongs to generated
            # output budget, not to the user's input classification.
            raise MindmapArtifactError(str(exc), code='AI_BUDGET_EXCEEDED') from exc
        raise
    manifest = validated.get('manifest')
    generator = manifest.get('generator') if isinstance(manifest, dict) else None
    if (
        (expected_artifact_id is not None and manifest.get('artifactId') != expected_artifact_id)
        or (
            expected_agent_key is not None
            and (
                not isinstance(generator, dict)
                or generator.get('agentKey') != expected_agent_key
            )
        )
        or (
            expected_adapter_version is not None
            and (
                not isinstance(generator, dict)
                or generator.get('adapterVersion') != expected_adapter_version
            )
        )
    ):
        raise MindmapArtifactError(
            'Agent Artifact 身份与任务快照不一致',
            code='AI_OUTPUT_INVALID',
        )
    return validated, summary


def _job_model(job: Any) -> MindmapAiJobModel:
    request_payload = _json_loads(getattr(job, 'request_json', None), {})
    execution_mode = request_payload.get('executionMode', 'preview')
    if execution_mode not in {'preview', 'direct'}:
        execution_mode = 'preview'
    return MindmapAiJobModel(
        id=job.id,
        sessionId=job.session_id,
        parentJobId=job.parent_job_id,
        retryOfJobId=job.retry_of_job_id,
        turnIndex=job.turn_index,
        agentKey=job.agent_key,
        adapterVersion=job.adapter_version,
        sdkVersion=job.sdk_version,
        runtimeVersion=job.runtime_version,
        modelRef=job.model_ref,
        maxBudgetUsd=float(getattr(job, 'max_budget_usd', MindmapAiConfig.mindmap_ai_max_budget_usd)),
        timeoutSeconds=int(getattr(job, 'timeout_seconds', MindmapAiConfig.mindmap_ai_job_timeout_seconds)),
        maxNodes=int(getattr(job, 'max_nodes', 2_000)),
        maxDepth=int(getattr(job, 'max_depth', 32)),
        retentionDays=int(
            getattr(job, 'retention_days', MindmapAiConfig.mindmap_ai_artifact_retention_days)
        ),
        intent=job.intent,
        target=job.target,
        executionMode=execution_mode,
        sourceType=job.source_type,
        sourceMindmapId=job.source_mindmap_id,
        baseRevision=job.base_revision,
        baseHash=job.base_hash,
        baseRoomEpoch=job.base_room_epoch,
        status=job.status,
        progress=job.progress,
        title=job.title,
        artifactId=job.artifact_id,
        proposalId=job.proposal_id,
        responseId=getattr(job, 'response_id', None),
        usage=_json_loads(job.usage_json),
        errorCode=_compatible_persisted_error_code(job.error_code, job.error_message),
        errorMessage=job.error_message,
        createdTime=job.created_time,
        updateTime=job.update_time,
        completedTime=job.completed_time,
        expiresTime=job.expires_time,
    )


class MindmapAiTaskManager:
    """在 API 进程中执行任务；事实状态始终持久化到数据库。"""

    _tasks: dict[str, asyncio.Task[None]] = {}
    _draft_preview_runs: dict[str, DraftPreviewRun] = {}
    # Expected cloud revision for the next direct mutation batch. This is a
    # process-local fast path; the persisted job baseline remains the recovery
    # fallback after a worker restart.
    _direct_commit_revisions: dict[str, int] = {}
    _claimed_execution_epochs: dict[str, int] = {}
    _recovery_task: asyncio.Task[None] | None = None
    _recovery_stop_event: asyncio.Event | None = None
    _lease_lost_tasks: set[asyncio.Task[Any]] = set()
    _detached_adapter_tasks: set[asyncio.Task[Any]] = set()
    _shutting_down = False
    _redis: Any | None = None

    @classmethod
    def configure_redis(cls, redis: Any) -> None:
        cls._redis = redis

    @staticmethod
    def _job_lease_key(job_id: str) -> str:
        return f'{AI_JOB_LEASE_KEY_PREFIX}{job_id}'

    @classmethod
    async def _acquire_job_lease(cls, job_id: str, token: str) -> bool:
        """抢占跨 worker 执行租约；Redis 未配置时保留单进程测试兼容性。"""
        if cls._redis is None:
            return True
        try:
            return bool(await cls._redis.set(
                cls._job_lease_key(job_id),
                token,
                nx=True,
                ex=int(MindmapAiConfig.mindmap_ai_job_lease_ttl_seconds),
            ))
        except Exception:
            # Redis 是多 worker 下的唯一执行权依据。连接状态未知时宁可等待
            # 下一轮恢复，也不能冒险同时运行两个外部 Agent。
            logger.exception(f'AI 脑图任务租约获取失败，将稍后重试: job_id={job_id}')
            return False

    @classmethod
    async def _release_job_lease(cls, job_id: str, token: str) -> None:
        if cls._redis is None:
            return
        try:
            await cls._redis.eval(
                _RELEASE_JOB_LEASE_SCRIPT,
                1,
                cls._job_lease_key(job_id),
                token,
            )
        except Exception:
            # 租约带 TTL，即使主动释放失败也会自动回收。
            logger.warning(f'AI 脑图任务租约释放失败，将等待 TTL 回收: job_id={job_id}')

    @classmethod
    async def _owns_job_lease(cls, job_id: str, token: str) -> bool:
        if cls._redis is None:
            return True
        try:
            return await cls._redis.get(cls._job_lease_key(job_id)) == token
        except Exception:
            logger.warning(f'AI 脑图任务租约所有权校验失败: job_id={job_id}')
            return False

    @classmethod
    async def _owns_current_job_lease(cls, job_id: str) -> bool:
        token = _CURRENT_JOB_LEASE_TOKEN.get()
        return token is None or await cls._owns_job_lease(job_id, token)

    @classmethod
    async def _touch_job_heartbeat(cls, job_id: str, execution_epoch: int) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await MindmapAiDao.touch_active_job(
                    db,
                    job_id,
                    execution_epoch,
                )
                await db.commit()
        except Exception:
            logger.warning(f'AI 脑图任务数据库心跳刷新失败: job_id={job_id}')

    @classmethod
    async def _renew_job_lease(
        cls,
        job_id: str,
        token: str,
        lease_lost: asyncio.Event,
        execution_epoch: int,
    ) -> None:
        redis = cls._redis
        if redis is None:
            return
        ttl = int(MindmapAiConfig.mindmap_ai_job_lease_ttl_seconds)
        interval = max(1.0, min(ttl / 3, ttl - 1.0))
        loop = asyncio.get_running_loop()
        confirmed_until = loop.time() + ttl
        while not lease_lost.is_set():
            await asyncio.sleep(min(interval, max(0.1, confirmed_until - loop.time())))
            try:
                renewed = await redis.eval(
                    _RENEW_JOB_LEASE_SCRIPT,
                    1,
                    cls._job_lease_key(job_id),
                    token,
                    ttl,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                if loop.time() >= confirmed_until:
                    logger.error(f'AI 脑图任务租约续期超时，停止旧执行者: job_id={job_id}')
                    lease_lost.set()
                    return
                logger.warning(f'AI 脑图任务租约续期暂时失败: job_id={job_id}')
                continue
            if int(renewed or 0) != 1:
                logger.warning(f'AI 脑图任务租约已被接管，停止旧执行者: job_id={job_id}')
                lease_lost.set()
                return
            confirmed_until = loop.time() + ttl
            await cls._touch_job_heartbeat(job_id, execution_epoch)

    @staticmethod
    def _draft_preview_key(job_id: str) -> str:
        # Redis Cluster requires every key touched by one Lua script to share a
        # slot. Job ids are server-issued UUIDs, so they are safe hash tags.
        return f'{AI_DRAFT_PREVIEW_KEY_PREFIX}{{{job_id}}}'

    @classmethod
    def _draft_preview_version_key(cls, job_id: str, operation_cursor: int) -> str:
        return f'{cls._draft_preview_key(job_id)}:version:{operation_cursor}'

    @classmethod
    def _draft_preview_terminal_key(cls, job_id: str) -> str:
        return f'{cls._draft_preview_key(job_id)}:terminal'

    @classmethod
    def _draft_preview_execution_key(cls, job_id: str) -> str:
        return f'{cls._draft_preview_key(job_id)}:execution-epoch'

    @classmethod
    async def _publish_execution_epoch(cls, job_id: str, execution_epoch: int) -> bool:
        if cls._redis is None:
            return False
        try:
            published = await cls._redis.eval(
                _PUBLISH_DRAFT_EXECUTION_SCRIPT,
                2,
                cls._draft_preview_terminal_key(job_id),
                cls._draft_preview_execution_key(job_id),
                str(execution_epoch),
                AI_DRAFT_PREVIEW_TTL_SECONDS,
            )
            return int(published or 0) == 1
        except Exception:
            logger.warning(f'AI 脑图执行轮次缓存围栏写入失败: job_id={job_id}')
            return False

    @staticmethod
    def _draft_preview_history_checkpoint(
        payload_jsons: list[str],
    ) -> tuple[int | None, int | None]:
        """从历史 SSE 元数据中取最大版本，兼容旧实现已经产生的版本回退。"""
        max_version: int | None = None
        max_epoch: int | None = None
        for payload_json in payload_jsons:
            payload = _json_loads(payload_json, {})
            if not isinstance(payload, dict):
                continue
            version = payload.get('previewVersion')
            if (
                isinstance(version, int)
                and not isinstance(version, bool)
                and 0 <= version <= AI_DRAFT_PREVIEW_MAX_VERSION
            ):
                max_version = version if max_version is None else max(max_version, version)
            epoch = payload.get('previewEpoch')
            if isinstance(epoch, int) and not isinstance(epoch, bool) and epoch >= 1:
                max_epoch = epoch if max_epoch is None else max(max_epoch, epoch)
        return max_version, max_epoch

    @staticmethod
    def _draft_checkpoint_values(
        *,
        job_id: str,
        document: dict[str, Any],
        operations: list[Any],
        initial_state: dict[str, Any] | None,
        preview_version: int,
        preview_epoch: int,
        summary: dict[str, Any] | None,
        expires_time: datetime,
    ) -> dict[str, Any]:
        """Build an encrypted checkpoint without exposing content to events/logs."""
        normalized_document, _normalized_summary = normalize_ai_editable_source_document(
            document,
        )
        serialized_document = _json_dumps(normalized_document)
        serialized_operations = _json_dumps(operations)
        serialized_initial_state = (
            _json_dumps(initial_state) if isinstance(initial_state, dict) else None
        )
        document_bytes = len(serialized_document.encode('utf-8'))
        plaintext_bytes = sum(len(item.encode('utf-8')) for item in (
            serialized_document,
            serialized_operations,
            serialized_initial_state or '',
        ))
        if (
            document_bytes > AI_DRAFT_PREVIEW_MAX_LATEST_BYTES
            or plaintext_bytes > AI_DRAFT_CHECKPOINT_MAX_PLAINTEXT_BYTES
        ):
            raise MindmapArtifactError(
                'AI 实时草稿超过持久检查点容量上限',
                code='AI_OUTPUT_INVALID',
            )
        document_hash = compute_document_hash(normalized_document)

        def encrypt_part(kind: str, serialized_payload: str) -> str:
            return MindmapAiCheckpointCrypto.encrypt_envelope({
                'schemaVersion': 1,
                'jobId': job_id,
                'previewVersion': preview_version,
                'previewEpoch': preview_epoch,
                'documentHash': document_hash,
                'kind': kind,
                'payload': _json_loads(serialized_payload),
            })

        document_ciphertext = encrypt_part('document', serialized_document)
        operations_ciphertext = encrypt_part('operations', serialized_operations)
        initial_state_ciphertext = (
            encrypt_part('initialState', serialized_initial_state)
            if serialized_initial_state is not None
            else None
        )
        ciphertext_bytes = sum(len(item.encode('utf-8')) for item in (
            document_ciphertext,
            operations_ciphertext,
            initial_state_ciphertext or '',
        ))
        if ciphertext_bytes > AI_DRAFT_CHECKPOINT_MAX_CIPHERTEXT_BYTES:
            raise MindmapArtifactError(
                'AI 实时草稿密文超过持久检查点容量上限',
                code='AI_OUTPUT_INVALID',
            )
        return {
            'job_id': job_id,
            'preview_version': preview_version,
            'preview_epoch': preview_epoch,
            'document_ciphertext': document_ciphertext,
            'operations_ciphertext': operations_ciphertext,
            'initial_state_ciphertext': initial_state_ciphertext,
            'document_hash': document_hash,
            'summary_json': _json_dumps(_safe_draft_summary(summary)),
            'expires_time': expires_time,
        }

    @staticmethod
    def _draft_checkpoint_preview(
        checkpoint: Any,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any] | None:
        """Decrypt and authenticate a durable checkpoint.

        Any decryption, JSON, expiry, or hash failure is treated as unavailable;
        exception details and plaintext are intentionally never logged.
        """
        if checkpoint is None:
            return None
        try:
            version = int(checkpoint.preview_version)
            epoch = int(checkpoint.preview_epoch)
            if (
                version < 0
                or version > AI_DRAFT_PREVIEW_MAX_VERSION
                or epoch < 1
                or (expected_version is not None and version != expected_version)
                or checkpoint.expires_time <= datetime.now()
            ):
                return None
            def decrypt_part(ciphertext: str, kind: str) -> Any:
                envelope = MindmapAiCheckpointCrypto.decrypt_envelope(ciphertext)
                if not isinstance(envelope, dict) or any((
                    envelope.get('schemaVersion') != 1,
                    envelope.get('jobId') != str(checkpoint.job_id),
                    envelope.get('previewVersion') != version,
                    envelope.get('previewEpoch') != epoch,
                    envelope.get('documentHash') != str(checkpoint.document_hash),
                    envelope.get('kind') != kind,
                )):
                    raise ValueError('invalid checkpoint envelope')
                return envelope.get('payload')

            raw_document = decrypt_part(checkpoint.document_ciphertext, 'document')
            if not isinstance(raw_document, dict):
                return None
            raw_operations = decrypt_part(checkpoint.operations_ciphertext, 'operations')
            if not isinstance(raw_operations, list):
                return None
            if checkpoint.initial_state_ciphertext:
                raw_initial_state = decrypt_part(
                    checkpoint.initial_state_ciphertext,
                    'initialState',
                )
                if not isinstance(raw_initial_state, dict):
                    return None
            document, _summary = normalize_ai_editable_source_document(raw_document)
            if compute_document_hash(document) != checkpoint.document_hash:
                return None
            summary = _json_loads(checkpoint.summary_json, {})
            if not isinstance(summary, dict):
                summary = {}
            return {
                'schemaVersion': 1,
                'jobId': str(checkpoint.job_id),
                'operationCursor': version,
                'previewEpoch': epoch,
                'document': document,
                'summary': _safe_draft_summary(summary),
                'updatedTime': checkpoint.update_time.isoformat(),
            }
        except Exception:
            logger.warning(
                'AI 脑图持久草稿无法解密或校验，已按不可用处理: '
                f'job_id={getattr(checkpoint, "job_id", "unknown")}'
            )
            return None

    @classmethod
    async def _begin_draft_preview_run(
        cls,
        job_id: str,
        *,
        persisted_version: int | None = None,
        persisted_epoch: int | None = None,
        execution_epoch: int | None = None,
    ) -> DraftPreviewRun:
        """为一次执行分配新的预览 epoch，避免恢复后版本回退。

        Adapter 的 operation cursor 每次运行都会从 0 开始。Redis 中的最新
        全局版本是上一轮已经向客户端公布的事实，因此新一轮从其后一位开始；
        旧的精确版本帧仍保留到短 TTL，历史 SSE 事件仍可按原版本读取。
        """
        previous_version = (
            persisted_version
            if isinstance(persisted_version, int)
            and not isinstance(persisted_version, bool)
            and 0 <= persisted_version <= AI_DRAFT_PREVIEW_MAX_VERSION
            else -1
        )
        previous_epoch = (
            persisted_epoch
            if isinstance(persisted_epoch, int)
            and not isinstance(persisted_epoch, bool)
            and persisted_epoch >= 1
            else (1 if previous_version >= 0 else 0)
        )
        if cls._redis is not None:
            try:
                current = _json_loads(
                    await cls._redis.get(cls._draft_preview_key(job_id)),
                    None,
                )
            except Exception:
                logger.warning(f'AI 脑图实时草稿 epoch 读取失败: job_id={job_id}')
                current = None
            if isinstance(current, dict) and current.get('jobId') == job_id:
                raw_version = current.get('operationCursor')
                if (
                    isinstance(raw_version, int)
                    and not isinstance(raw_version, bool)
                    and 0 <= raw_version <= AI_DRAFT_PREVIEW_MAX_VERSION
                ):
                    previous_version = max(previous_version, raw_version)
                raw_epoch = current.get('previewEpoch')
                if (
                    isinstance(raw_epoch, int)
                    and not isinstance(raw_epoch, bool)
                    and raw_epoch >= 1
                ):
                    previous_epoch = max(previous_epoch, raw_epoch)
                elif previous_version >= 0:
                    # 升级前的缓存没有 epoch；把它视为第一轮。
                    previous_epoch = max(previous_epoch, 1)
        version_offset = max(0, previous_version + 1)
        run = DraftPreviewRun(
            epoch=max(1, previous_epoch + 1, int(execution_epoch or 0)),
            version_offset=version_offset,
        )
        cls._draft_preview_runs[job_id] = run
        return run

    @classmethod
    def _draft_preview_coordinates(
        cls,
        job_id: str,
        local_operation_cursor: int,
    ) -> tuple[int, int] | None:
        run = cls._draft_preview_runs.get(job_id) or DraftPreviewRun(
            epoch=1,
            version_offset=0,
        )
        local_cursor = max(0, int(local_operation_cursor))
        version = run.version_offset + local_cursor
        if version > AI_DRAFT_PREVIEW_MAX_VERSION:
            logger.warning(f'AI 脑图实时草稿版本超过上限: job_id={job_id}')
            return None
        return version, run.epoch

    @classmethod
    async def _store_draft_preview(  # noqa: PLR0912, PLR0915
        cls,
        job_id: str,
        document: dict[str, Any],
        *,
        operation_cursor: int,
        expected_execution_epoch: int,
        preview_epoch: int = 1,
        summary: dict[str, Any] | None = None,
    ) -> bool:
        if cls._redis is None:
            return False
        execution_epoch = int(expected_execution_epoch)
        if execution_epoch < 1:
            return False
        cursor = max(0, min(int(operation_cursor), AI_DRAFT_PREVIEW_MAX_VERSION))
        try:
            normalized_document, _normalized_summary = (
                normalize_ai_editable_source_document(document)
            )
        except MindmapArtifactError:
            return False
        value = {
            'schemaVersion': 1,
            'jobId': job_id,
            'operationCursor': cursor,
            'previewEpoch': max(1, int(preview_epoch)),
            'document': normalized_document,
            'documentHash': compute_document_hash(normalized_document),
            'summary': _safe_draft_summary(summary),
            'updatedTime': datetime.now().isoformat(),
            'executionEpoch': execution_epoch,
        }
        serialized_value = _json_dumps(value)
        frame_size = len(serialized_value.encode('utf-8'))
        if frame_size > AI_DRAFT_PREVIEW_MAX_LATEST_BYTES:
            logger.warning(f'AI 脑图实时草稿超过缓存上限: job_id={job_id}')
            return False
        terminal_key = cls._draft_preview_terminal_key(job_id)
        execution_key = cls._draft_preview_execution_key(job_id)
        latest_key = cls._draft_preview_key(job_id)
        exact_key = cls._draft_preview_version_key(job_id, cursor)
        for _attempt in range(_DRAFT_PREVIEW_CAS_RETRIES):
            try:
                current_json = await cls._redis.get(latest_key)
            except Exception:
                logger.warning(f'AI 脑图实时草稿写入失败: job_id={job_id}')
                return False
            current = _json_loads(current_json, None)
            frame_sizes = {
                int(item_key): item_value
                for item_key, item_value in (
                    current.get('previewFrameSizes', {}).items()
                    if isinstance(current, dict)
                    and isinstance(current.get('previewFrameSizes'), dict)
                    else []
                )
                if str(item_key).isdigit()
                and 0 <= int(item_key) <= AI_DRAFT_PREVIEW_MAX_VERSION
                and isinstance(item_value, int)
                and not isinstance(item_value, bool)
                and item_value >= 0
            }
            frame_times = {
                int(item_key): float(item_value)
                for item_key, item_value in (
                    current.get('previewFrameTimes', {}).items()
                    if isinstance(current, dict)
                    and isinstance(current.get('previewFrameTimes'), dict)
                    else []
                )
                if str(item_key).isdigit()
                and 0 <= int(item_key) <= AI_DRAFT_PREVIEW_MAX_VERSION
                and isinstance(item_value, (int, float))
                and not isinstance(item_value, bool)
                and math.isfinite(float(item_value))
            }
            cutoff = time.time() - AI_DRAFT_PREVIEW_FRAME_TTL_SECONDS
            expired_versions = [
                version
                for version in frame_sizes
                if frame_times.get(version, 0) < cutoff
            ]
            for expired_version in expired_versions:
                frame_sizes.pop(expired_version, None)
                frame_times.pop(expired_version, None)
            if frame_size <= AI_DRAFT_PREVIEW_MAX_TOTAL_BYTES:
                frame_sizes[cursor] = frame_size
                frame_times[cursor] = time.time()
            else:
                frame_sizes.pop(cursor, None)
                frame_times.pop(cursor, None)
            evicted_versions = [
                version for version in expired_versions if version not in frame_sizes
            ]
            while (
                len(frame_sizes) > AI_DRAFT_PREVIEW_MAX_FRAMES
                or sum(frame_sizes.values()) > AI_DRAFT_PREVIEW_MAX_TOTAL_BYTES
            ):
                evicted = min(frame_sizes)
                frame_sizes.pop(evicted)
                frame_times.pop(evicted, None)
                evicted_versions.append(evicted)
            latest_value = value
            if (
                isinstance(current, dict)
                and current.get('jobId') == job_id
                and current.get('executionEpoch') == execution_epoch
                and isinstance(current.get('document'), dict)
                and isinstance(current.get('operationCursor'), int)
                and not isinstance(current.get('operationCursor'), bool)
                and current['operationCursor'] > cursor
            ):
                latest_value = current
            latest_value = {
                **latest_value,
                'availableVersions': sorted(frame_sizes),
                'previewFrameSizes': {
                    str(version): frame_sizes[version]
                    for version in sorted(frame_sizes)
                },
                'previewFrameTimes': {
                    str(version): frame_times[version]
                    for version in sorted(frame_times)
                    if version in frame_sizes
                },
                'latestPreviewBytes': frame_sizes.get(
                    int(latest_value['operationCursor']),
                    frame_size,
                ),
            }
            evicted_keys = list(dict.fromkeys(
                cls._draft_preview_version_key(job_id, version)
                for version in evicted_versions
                if version != cursor
            ))
            keys = [terminal_key, execution_key, latest_key, exact_key, *evicted_keys]
            try:
                stored = await cls._redis.eval(
                    _STORE_DRAFT_PREVIEW_SCRIPT,
                    len(keys),
                    *keys,
                    str(execution_epoch),
                    '1' if current_json is not None else '0',
                    current_json or '',
                    '1' if cursor in frame_sizes else '0',
                    serialized_value,
                    AI_DRAFT_PREVIEW_FRAME_TTL_SECONDS,
                    _json_dumps(latest_value),
                    AI_DRAFT_PREVIEW_TTL_SECONDS,
                )
            except Exception:
                logger.warning(f'AI 脑图实时草稿写入失败: job_id={job_id}')
                return False
            if int(stored or 0) == 1:
                return True
            if int(stored or 0) < 0:
                return False
        logger.warning(f'AI 脑图实时草稿 CAS 重试耗尽: job_id={job_id}')
        return False

    @classmethod
    async def get_draft_preview(
        cls,
        job_id: str,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        if cls._redis is None:
            return None
        if version is not None:
            version = max(
                0,
                min(int(version), AI_DRAFT_PREVIEW_MAX_VERSION),
            )
            key = cls._draft_preview_version_key(job_id, version)
        else:
            key = cls._draft_preview_key(job_id)
        try:
            value = _json_loads(await cls._redis.get(key), None)
        except Exception:
            logger.warning(f'AI 脑图实时草稿读取失败: job_id={job_id}')
            return None
        if not isinstance(value, dict) or value.get('jobId') != job_id:
            return None
        if not isinstance(value.get('document'), dict):
            return None
        if version is not None and value.get('operationCursor') != version:
            return None
        return value

    @classmethod
    async def delete_draft_preview(
        cls,
        job_id: str,
        expected_execution_epoch: int,
    ) -> bool:
        if cls._redis is None:
            return False
        execution_epoch = int(expected_execution_epoch)
        terminal_key = cls._draft_preview_terminal_key(job_id)
        execution_key = cls._draft_preview_execution_key(job_id)
        latest_key = cls._draft_preview_key(job_id)
        for _attempt in range(_DRAFT_PREVIEW_CAS_RETRIES):
            try:
                current_json = await cls._redis.get(latest_key)
            except Exception:
                logger.warning(f'AI 脑图实时草稿清理失败: job_id={job_id}')
                return False
            current = _json_loads(current_json, None)
            versions = current.get('availableVersions', []) if isinstance(current, dict) else []
            keys = [terminal_key, execution_key, latest_key]
            keys.extend(
                cls._draft_preview_version_key(job_id, version)
                for version in versions
                if isinstance(version, int)
                and not isinstance(version, bool)
                and 0 <= version <= AI_DRAFT_PREVIEW_MAX_VERSION
            )
            keys = list(dict.fromkeys(keys))
            try:
                deleted = await cls._redis.eval(
                    _DELETE_DRAFT_PREVIEW_SCRIPT,
                    len(keys),
                    *keys,
                    str(execution_epoch),
                    '1' if current_json is not None else '0',
                    current_json or '',
                )
            except Exception:
                logger.warning(f'AI 脑图实时草稿清理失败: job_id={job_id}')
                return False
            if int(deleted or 0) == 1:
                return True
            if int(deleted or 0) < 0:
                return False
        logger.warning(f'AI 脑图实时草稿清理 CAS 重试耗尽: job_id={job_id}')
        return False

    @classmethod
    async def mark_draft_terminal(
        cls,
        job_id: str,
        expected_execution_epoch: int,
    ) -> bool:
        """Atomically fence late writers and erase this execution's plaintext."""
        if cls._redis is None:
            return False
        execution_epoch = int(expected_execution_epoch)
        terminal_key = cls._draft_preview_terminal_key(job_id)
        execution_key = cls._draft_preview_execution_key(job_id)
        latest_key = cls._draft_preview_key(job_id)
        for _attempt in range(_DRAFT_PREVIEW_CAS_RETRIES):
            try:
                current_json = await cls._redis.get(latest_key)
            except Exception:
                logger.warning(f'AI 脑图终态缓存围栏写入失败: job_id={job_id}')
                return False
            current = _json_loads(current_json, None)
            versions = current.get('availableVersions', []) if isinstance(current, dict) else []
            keys = [terminal_key, execution_key, latest_key]
            keys.extend(
                cls._draft_preview_version_key(job_id, version)
                for version in versions
                if isinstance(version, int)
                and not isinstance(version, bool)
                and 0 <= version <= AI_DRAFT_PREVIEW_MAX_VERSION
            )
            keys = list(dict.fromkeys(keys))
            try:
                marked = await cls._redis.eval(
                    _MARK_DRAFT_TERMINAL_SCRIPT,
                    len(keys),
                    *keys,
                    str(execution_epoch),
                    '1' if current_json is not None else '0',
                    current_json or '',
                    AI_DRAFT_PREVIEW_TTL_SECONDS,
                )
            except Exception:
                # No non-atomic delete fallback: an unfenced cache is safer than
                # deleting first and allowing a delayed writer to resurrect it.
                logger.warning(f'AI 脑图终态缓存围栏写入失败: job_id={job_id}')
                return False
            if int(marked or 0) == 1:
                return True
            if int(marked or 0) < 0:
                logger.warning(f'AI 脑图旧执行轮次终态围栏被拒绝: job_id={job_id}')
                return False
        logger.warning(f'AI 脑图终态缓存围栏 CAS 重试耗尽: job_id={job_id}')
        return False

    @staticmethod
    def _enforce_result_policy(
        summary: dict[str, int],
        usage: dict[str, Any],
        *,
        max_nodes: int,
        max_depth: int,
        max_budget_usd: float,
        source_summary: dict[str, int] | None = None,
        scoped_summary: dict[str, int] | None = None,
        created_count: int | None = None,
    ) -> None:
        effective_summary = scoped_summary or summary
        if source_summary is None:
            node_limit_exceeded = effective_summary['nodeCount'] > max_nodes
            depth_limit = max_depth
        else:
            node_limit_exceeded = int(created_count or 0) > max_nodes
            # 已有脑图可能在任务开始前就超过用户本次生成上限。此时只阻止
            # Agent 继续加深，而不因未修改的历史结构误判整项任务失败。
            depth_limit = max(max_depth, source_summary['treeDepth'])
        if node_limit_exceeded or effective_summary['treeDepth'] > depth_limit:
            node_usage = (
                f'最终节点 {effective_summary["nodeCount"]}/{max_nodes}'
                if source_summary is None
                else f'累计新增节点 {int(created_count or 0)}/{max_nodes}'
            )
            raise MindmapArtifactError(
                f'Agent 输出超过任务结构上限（{node_usage}，'
                f'最终层级 {effective_summary["treeDepth"]}/{depth_limit}）',
                code='AI_BUDGET_EXCEEDED',
            )
        reported_cost = usage.get('totalCostUsd')
        if reported_cost is None or isinstance(reported_cost, bool):
            return
        try:
            cost = float(reported_cost)
        except (TypeError, ValueError) as exc:
            raise MindmapArtifactError(
                'Agent 返回的成本用量无法核验',
                code='AI_BUDGET_EXCEEDED',
            ) from exc
        if not math.isfinite(cost) or cost < 0:
            raise MindmapArtifactError(
                'Agent 返回的成本用量无法核验',
                code='AI_BUDGET_EXCEEDED',
            )
        if cost > max_budget_usd:
            raise MindmapArtifactError(
                f'Agent 报告成本 ${cost:.4f}，超过任务预算 ${max_budget_usd:.4f}',
                code='AI_BUDGET_EXCEEDED',
            )

    @staticmethod
    def _enforce_usage_policy(
        usage: dict[str, Any],
        *,
        max_budget_usd: float,
    ) -> None:
        reported_cost = usage.get('totalCostUsd')
        if reported_cost is None or isinstance(reported_cost, bool):
            return
        try:
            cost = float(reported_cost)
        except (TypeError, ValueError) as exc:
            raise MindmapArtifactError(
                'Agent 返回的成本用量无法核验',
                code='AI_BUDGET_EXCEEDED',
            ) from exc
        if not math.isfinite(cost) or cost < 0:
            raise MindmapArtifactError(
                'Agent 返回的成本用量无法核验',
                code='AI_BUDGET_EXCEEDED',
            )
        if cost > max_budget_usd:
            raise MindmapArtifactError(
                f'Agent 报告成本 ${cost:.4f}，超过任务预算 ${max_budget_usd:.4f}',
                code='AI_BUDGET_EXCEEDED',
            )

    @classmethod
    def schedule(cls, job_id: str) -> bool:
        if cls._shutting_down:
            return False
        current = cls._tasks.get(job_id)
        if current is not None and not current.done():
            return False
        task = asyncio.create_task(
            cls._run_scheduled_job(job_id),
            name=f'mindmap-ai:{job_id}',
        )
        cls._tasks[job_id] = task

        def forget_finished_run(_task: asyncio.Task[None]) -> None:
            if cls._tasks.get(job_id) is _task:
                cls._tasks.pop(job_id, None)
                cls._draft_preview_runs.pop(job_id, None)
                cls._claimed_execution_epochs.pop(job_id, None)
                cls._direct_commit_revisions.pop(job_id, None)

        task.add_done_callback(forget_finished_run)
        return True

    @classmethod
    async def _prepare_claimed_job(cls, job_id: str) -> int | None:
        """在已持有租约时把遗留状态收敛到可运行或取消终态。"""
        async with AsyncSessionLocal() as db:
            # Keep the global completion/deletion lock order: job first, then
            # session. A session tombstone is committed before its job-cancel
            # sweep, so recovery must fence that crash window before invoking
            # any paid provider.
            job = await MindmapAiDao.get_job(db, job_id, for_update=True)
            if job is None or job.status in TERMINAL_JOB_STATUSES:
                await db.rollback()
                return None
            session = await MindmapAiDao.get_session(
                db,
                job.session_id,
                for_update=True,
            )
            if not await cls._owns_current_job_lease(job_id):
                await db.rollback()
                return None
            if not _session_accepts_work(session):
                now = datetime.now()
                changed = await MindmapAiDao.transition_job_status(
                    db,
                    job_id,
                    ACTIVE_JOB_STATUSES,
                    {
                        'status': 'cancelled',
                        'progress': 100,
                        'error_code': 'AI_TASK_CANCELLED',
                        'error_message': '会话已结束，任务已取消',
                        'completed_time': now,
                    },
                )
                if changed:
                    await MindmapAiDao.delete_draft_checkpoint(db, job_id)
                    await MindmapAiDao.add_event(
                        db,
                        job_id,
                        'status_changed',
                        _event_json({
                            'status': 'cancelled',
                            'progress': 100,
                            'errorCode': 'AI_TASK_CANCELLED',
                            'errorMessage': '会话已结束，任务已取消',
                        }),
                    )
                await db.commit()
                if changed:
                    await cls.mark_draft_terminal(
                        job_id,
                        int(getattr(job, 'execution_epoch', 0) or 0),
                    )
                return None
            claimed_status = str(job.status)
            if claimed_status == 'cancel_requested':
                changed = await MindmapAiDao.transition_job_status(
                    db,
                    job_id,
                    ACTIVE_JOB_STATUSES,
                    {
                        'status': 'cancelled',
                        'progress': 100,
                        'error_code': 'AI_TASK_CANCELLED',
                        'error_message': '任务已取消',
                        'completed_time': datetime.now(),
                    },
                )
                if changed:
                    await MindmapAiDao.delete_draft_checkpoint(db, job_id)
                    await db.commit()
                    await cls.mark_draft_terminal(
                        job_id,
                        int(getattr(job, 'execution_epoch', 0) or 0),
                    )
                else:
                    await db.rollback()
                return None
            if claimed_status not in {'queued', 'preparing', 'running', 'validating'}:
                await db.rollback()
                return None
            if claimed_status != 'queued':
                changed = await MindmapAiDao.transition_job_status(
                    db,
                    job_id,
                    {'preparing', 'running', 'validating'},
                    {
                        'status': 'queued',
                        'progress': 0,
                        'error_code': None,
                        'error_message': None,
                    },
                )
                if not changed:
                    await db.rollback()
                    return None
            execution_epoch = max(0, int(getattr(job, 'execution_epoch', 0) or 0)) + 1
            await MindmapAiDao.update_job(
                db,
                job_id,
                {'execution_epoch': execution_epoch},
            )
            await db.commit()
            cls._claimed_execution_epochs[job_id] = execution_epoch
            await cls._publish_execution_epoch(job_id, execution_epoch)
            return execution_epoch

    @classmethod
    async def _run_scheduled_job(cls, job_id: str) -> None:
        token = f'{uuid.uuid4()}:{job_id}'
        if not await cls._acquire_job_lease(job_id, token):
            return
        lease_lost = asyncio.Event()
        renewal_task: asyncio.Task[None] | None = None
        run_task: asyncio.Task[None] | None = None
        lost_waiter: asyncio.Task[bool] | None = None
        context_token = _CURRENT_JOB_LEASE_TOKEN.set(token)
        execution_epoch_token = None
        try:
            execution_epoch = await cls._prepare_claimed_job(job_id)
            if execution_epoch is None or lease_lost.is_set():
                return
            execution_epoch_token = _CURRENT_JOB_EXECUTION_EPOCH.set(execution_epoch)
            renewal_task = asyncio.create_task(
                cls._renew_job_lease(
                    job_id,
                    token,
                    lease_lost,
                    execution_epoch,
                ),
                name=f'mindmap-ai-lease:{job_id}',
            )
            run_task = asyncio.create_task(
                cls._run_job(job_id),
                name=f'mindmap-ai-runner:{job_id}',
            )
            lost_waiter = asyncio.create_task(
                lease_lost.wait(),
                name=f'mindmap-ai-lease-watch:{job_id}',
            )
            done, _pending = await asyncio.wait(
                {run_task, lost_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if run_task in done:
                await run_task
                return
            cls._lease_lost_tasks.add(run_task)
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        except asyncio.CancelledError:
            if run_task is not None and not run_task.done():
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)
            raise
        finally:
            if run_task is not None:
                cls._lease_lost_tasks.discard(run_task)
            if lost_waiter is not None:
                lost_waiter.cancel()
                await asyncio.gather(lost_waiter, return_exceptions=True)
            if renewal_task is not None:
                renewal_task.cancel()
                await asyncio.gather(renewal_task, return_exceptions=True)
            await cls._release_job_lease(job_id, token)
            if execution_epoch_token is not None:
                _CURRENT_JOB_EXECUTION_EPOCH.reset(execution_epoch_token)
            _CURRENT_JOB_LEASE_TOKEN.reset(context_token)

    @classmethod
    async def recover_pending(cls) -> int:
        """分页发现可运行/可接管任务；真正执行权由逐任务租约仲裁。"""
        if cls._shutting_down:
            return 0
        scheduled = 0
        async with AsyncSessionLocal() as db:
            waiting_jobs = await MindmapAiDao.list_waiting_jobs(db)
        # A process can stop after committing the parent's terminal artifact but
        # before the child release transaction. Re-run the release check during
        # recovery so an already persisted next turn never waits forever.
        for waiting_job in waiting_jobs:
            await cls._wake_waiting_followups(str(waiting_job.parent_job_id or ''))
        cursor_created_time: datetime | None = None
        cursor_id: str | None = None
        batch_size = int(MindmapAiConfig.mindmap_ai_recovery_batch_size)
        stale_before = datetime.now() - timedelta(
            seconds=int(MindmapAiConfig.mindmap_ai_job_lease_ttl_seconds),
        )
        while not cls._shutting_down:
            async with AsyncSessionLocal() as db:
                jobs = await MindmapAiDao.list_recoverable_jobs(
                    db,
                    stale_before=stale_before,
                    after_created_time=cursor_created_time,
                    after_id=cursor_id,
                    limit=batch_size,
                )
            if not jobs:
                break
            for job in jobs:
                scheduled += int(cls.schedule(str(job.id)))
            last_job = jobs[-1]
            cursor_created_time = last_job.created_time
            cursor_id = str(last_job.id)
            if len(jobs) < batch_size:
                break
        return scheduled

    @classmethod
    async def _recovery_loop(cls) -> None:
        assert cls._recovery_stop_event is not None
        interval = float(MindmapAiConfig.mindmap_ai_recovery_interval_seconds)
        while not cls._recovery_stop_event.is_set():
            try:
                await asyncio.wait_for(cls._recovery_stop_event.wait(), timeout=interval)
                continue
            except asyncio.TimeoutError:
                pass
            try:
                await cls.recover_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('AI 脑图任务周期恢复失败，将在下一周期重试')

    @classmethod
    def start(cls) -> None:
        cls._shutting_down = False
        if cls._recovery_task is not None and not cls._recovery_task.done():
            return
        cls._recovery_stop_event = asyncio.Event()
        cls._recovery_task = asyncio.create_task(
            cls._recovery_loop(),
            name='mindmap-ai-recovery',
        )

    @classmethod
    async def shutdown(cls) -> None:
        cls._shutting_down = True
        recovery_task = cls._recovery_task
        if cls._recovery_stop_event is not None:
            cls._recovery_stop_event.set()
        if recovery_task is not None:
            recovery_task.cancel()
            await asyncio.gather(recovery_task, return_exceptions=True)
        cls._recovery_task = None
        cls._recovery_stop_event = None
        tasks = list(cls._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        cls._tasks.clear()
        cls._draft_preview_runs.clear()
        cls._claimed_execution_epochs.clear()
        cls._lease_lost_tasks.clear()
        cls._redis = None

    @classmethod
    async def _ensure_direct_undo_receipt(
        cls,
        db: AsyncSession,
        job: Any,
    ) -> str | None:
        """Create the durable undo anchor before the first direct mutation.

        Direct jobs intentionally do not create a preview Proposal.  The
        existing undo table is still a durable, conditional receipt, so a
        stopped or partially failed direct turn can be reverted without
        inventing a second document snapshot.  The job id is used as the
        receipt id because it is stable across retries and already exposed to
        the client as the task identity.
        """
        request_payload = _json_loads(getattr(job, 'request_json', None), {})
        if (
            request_payload.get('executionMode', 'preview') != 'direct'
            or getattr(job, 'source_type', None) != 'cloud_document'
            or not getattr(job, 'source_mindmap_id', None)
        ):
            return None
        receipt_id = str(getattr(job, 'proposal_id', '') or job.id)
        existing = await MindmapAiDao.get_undo(db, receipt_id, int(job.user_id))
        if existing is not None:
            if getattr(existing, 'status', None) == 'available' and _raw_direct_undo_baseline(job) is None:
                await MindmapAiDao.update_undo(db, receipt_id, {'status': 'blocked'})
            if not getattr(job, 'proposal_id', None):
                await MindmapAiDao.update_job(db, str(job.id), {
                    'proposal_id': receipt_id,
                })
                try:
                    job.proposal_id = receipt_id
                except Exception:
                    pass
            return receipt_id
        source = request_payload.get('source')
        source_document = (
            source.get('baselineDocument') or source.get('document')
            if isinstance(source, dict)
            else None
        )
        if not isinstance(source_document, dict):
            raise MindmapArtifactError(
                '直写任务缺少可撤销的云端基线',
                code='AI_OUTPUT_INVALID',
            )
        normalized_before, _summary = normalize_ai_editable_source_document(
            source_document,
            max_node_count=AI_MAX_NODE_COUNT,
        )
        raw_before = _raw_direct_undo_baseline(job)
        before_hash = compute_document_hash(normalized_before)
        now = datetime.now()
        await MindmapAiDao.add_undo(db, {
            'proposal_id': receipt_id,
            'user_id': int(job.user_id),
            'mindmap_id': int(job.source_mindmap_id),
            'before_document_json': _json_dumps(raw_before or normalized_before),
            'before_hash': before_hash,
            'applied_hash': before_hash,
            'applied_revision': int(job.base_revision or 1),
            # Older rows have only the lossy Agent projection. Keep their
            # receipt visible, but never pretend it can restore original bytes.
            'status': 'available' if raw_before is not None else 'blocked',
            'created_time': now,
            'expires_time': getattr(job, 'expires_time', None) or now,
        })
        await MindmapAiDao.update_job(db, str(job.id), {
            'proposal_id': receipt_id,
        })
        try:
            job.proposal_id = receipt_id
        except Exception:
            pass
        return receipt_id

    @staticmethod
    async def _record_direct_undo_commit(
        db: AsyncSession, job: Any, receipt_id: str, result: dict[str, Any],
    ) -> None:
        receipt = await MindmapAiDao.get_undo(db, receipt_id, int(job.user_id))
        previous_revision = int(getattr(receipt, 'applied_revision', job.base_revision) or 1)
        revision = int(result['contentRevision'])
        replay = bool(result.get('idempotentReplay'))
        step = int(int(result.get('operationCount') or 0) > 0 and not replay)
        blocked = (
            _raw_direct_undo_baseline(job) is None
            or getattr(receipt, 'status', None) != 'available'
            or bool(result.get('concurrentMerge'))
            or revision != previous_revision + step
        )
        values = {'applied_revision': revision, 'applied_hash': result.get('documentHash')}
        if blocked:
            # Whole-document undo is safe only across an uninterrupted chain
            # of this task's commits. Once foreign work is absorbed, later AI
            # commits/no-ops must never make the receipt available again.
            values['status'] = 'blocked'
        await MindmapAiDao.update_undo(db, receipt_id, values)

    @staticmethod
    def _project_committed_preview(
        job: Any, document: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Keep cloud truth without broadening the task's authorized projection."""
        request = _json_loads(getattr(job, 'request_json', None), {})
        source = request.get('source') or {}
        normalized_document, _summary = normalize_ai_editable_source_document(document)
        tool = MindmapToolService(
            base_document=normalized_document,
            scope=source.get('scope') if isinstance(source, dict) else None,
            trusted_source=True,
        )
        return tool.read_projection(), tool.authorized_scope_summary()

    @staticmethod
    def _tag_catalog_target_mindmap_id(request: MindmapAiJobCreateModel) -> int | None:
        # A file result belongs to the requesting user, even when its input
        # came from a shared map. Only edits of that existing map inherit its
        # owner's tag-binding restrictions.
        if request.execution_mode == 'direct' or request.target == 'proposal':
            return request.source.mindmap_id
        return None

    @staticmethod
    async def _resolve_run_source_document(
        db: AsyncSession,
        job: Any,
        request: MindmapAiJobCreateModel,
        recovered_preview: dict[str, Any] | None,
        *,
        has_draft_history: bool,
    ) -> dict[str, Any] | None:
        # Legacy direct checkpoints can contain pre-commit tool values. They
        # are coordinates for resuming playback, not authority for restarting
        # writes. Recover the complete current cloud tree; the new tool then
        # reapplies the original scope before exposing anything to the agent.
        if request.execution_mode == 'direct' and (recovered_preview is not None or has_draft_history):
            detail = await MindmapAiMutationGateway.read_document(
                db, int(request.source.mindmap_id), int(job.user_id),
            )
            document, _summary = normalize_ai_editable_source_document(_document_from_detail(detail))
            return document
        return (
            _restore_preview_document(request, recovered_preview['document'])
            if recovered_preview is not None else request.source.document
        )

    @classmethod
    async def _validate_tag_suggestions(
        cls, db: AsyncSession, job: Any, payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        suggestions = normalize_tag_suggestions(payload.get('suggestions'))
        target_uids = {uid for suggestion in suggestions for uid in suggestion['nodeUids']}
        if not target_uids:
            return suggestions
        request = _json_loads(getattr(job, 'request_json', None), {})
        if request.get('executionMode') == 'direct':
            detail = await MindmapAiMutationGateway.read_document(
                db, int(job.source_mindmap_id), int(job.user_id),
            )
            projection, _summary = cls._project_committed_preview(job, _document_from_detail(detail))
        else:
            checkpoint = await MindmapAiDao.get_draft_checkpoint(db, str(job.id))
            preview = cls._draft_checkpoint_preview(checkpoint)
            projection = preview['document'] if preview is not None else None
            if projection is None:
                source = request.get('source') or {}
                if isinstance(source, dict) and isinstance(source.get('document'), dict):
                    projection, _summary = cls._project_committed_preview(job, source['document'])
        allowed_uids: set[str] = set()
        pending = [projection.get('root')] if isinstance(projection, dict) else []
        while pending:
            node = pending.pop()
            if not isinstance(node, dict):
                continue
            allowed_uids.add(str((node.get('data') or {}).get('uid') or ''))
            pending.extend(node.get('children') or [])
        if not target_uids <= allowed_uids:
            raise MindmapArtifactError('标签建议引用了任务授权范围以外的节点', code='AI_OUTPUT_INVALID')
        return suggestions

    @classmethod
    async def _commit_direct_draft(
        cls,
        db: AsyncSession,
        job: Any,
        operations: list[dict[str, Any]],
        operation_cursor: int,
    ) -> dict[str, Any] | None:
        """Commit one Agent draft delta through the authoritative map gateway."""
        request_payload = _json_loads(getattr(job, 'request_json', None), {})
        if request_payload.get('executionMode', 'preview') != 'direct':
            return None
        if job.source_type != 'cloud_document' or not job.source_mindmap_id:
            raise MindmapArtifactError(
                '直接写入任务缺少云端脑图目标',
                code='AI_DOCUMENT_CONFLICT',
            )
        if not operations:
            return None
        source = request_payload.get('source') or {}
        scope = source.get('scope') if isinstance(source, dict) else None
        # ``operation_cursor`` is the globally monotonic preview cursor, not
        # the adapter-local cursor. A recovered worker starts its in-memory
        # DraftOperation list at zero again; using the local value here would
        # reuse an earlier mutation id for a different batch.
        mutation_id = f'ai:{job.id}:{int(operation_cursor)}'
        expected_revision = cls._direct_commit_revisions.get(
            str(job.id),
            int(job.base_revision or 1),
        )
        try:
            result = await MindmapAiMutationGateway.apply_draft_operations(
                db,
                int(job.source_mindmap_id),
                operations,
                int(job.user_id),
                mutation_id=mutation_id,
                scope=scope if isinstance(scope, dict) else None,
                user_name=f'ai-agent:{job.agent_key}',
                expected_revision=expected_revision,
                commit=False,
                broadcast=False,
            )
            committed_revision = result.get('contentRevision')
            if isinstance(committed_revision, int) and committed_revision >= expected_revision:
                # The surrounding _emit transaction still contains the draft
                # checkpoint and event. Advance the process-local baseline only
                # after that outer transaction commits successfully.
                result['_nextExpectedRevision'] = committed_revision
            return result
        except ServiceWarning as exc:
            message = str(exc.message or '脑图已被其他协作者修改，AI 直写需要重新同步')
            raise MindmapArtifactError(
                message,
                code='AI_DOCUMENT_CONFLICT',
            ) from exc
        except ServiceException as exc:
            # The mutation gateway deliberately uses the application's
            # ServiceException for permission, integrity and CAS failures.
            # This callback runs inside the Agent's required-event path; let a
            # domain failure retain a stable AI error code instead of being
            # mistaken for an event-table outage (which used to surface as
            # ``AI_AGENT_UNAVAILABLE: 实时事件持久化失败``).
            message = str(exc.message or '脑图当前状态不允许继续直写，请重新读取后重试')
            raise MindmapArtifactError(
                message,
                code='AI_DOCUMENT_CONFLICT',
            ) from exc
        except IntegrityError as exc:
            # A duplicate comment/mutation receipt is a domain-level replay
            # race, not an event-store outage.  Preserve a retryable conflict
            # code so the worker can stop cleanly and the UI can resync.
            raise MindmapArtifactError(
                'AI 直写幂等提交发生冲突，请重新同步后重试',
                code='AI_DOCUMENT_CONFLICT',
            ) from exc
        except (TypeError, ValueError) as exc:
            # A malformed provider operation is a terminal contract failure,
            # not a persistence outage.  Keep the original exception private.
            raise MindmapArtifactError(
                'AI 直写操作未通过脑图内容校验',
                code='AI_OUTPUT_INVALID',
            ) from exc

    @classmethod
    async def _emit(  # noqa: PLR0912, PLR0915
        cls,
        job_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if not await cls._owns_current_job_lease(job_id):
            return
        async with AsyncSessionLocal() as db:
            job = await MindmapAiDao.get_job(db, job_id, for_update=True)
            if not await cls._owns_current_job_lease(job_id):
                await db.rollback()
                return
            expected_execution_epoch = _CURRENT_JOB_EXECUTION_EPOCH.get()
            if (
                job is None
                or (
                    expected_execution_epoch is not None
                    and int(getattr(job, 'execution_epoch', -1)) != expected_execution_epoch
                )
                or job.status in TERMINAL_JOB_STATUSES
                or job.status == 'cancel_requested'
            ):
                return
            event_payload = dict(payload)
            if event_type == 'tag_suggestions':
                # This event is recoverable advice, never a document mutation.
                event_payload = {
                    'suggestions': await cls._validate_tag_suggestions(db, job, event_payload),
                }
            preview_state = event_payload.pop('previewState', None)
            operations = event_payload.pop('operations', None)
            initial_state = event_payload.pop('initialState', None)
            direct_commit: dict[str, Any] | None = None
            direct_undo_id: str | None = None
            coordinates: tuple[int, int] | None = None
            if event_type == 'draft_changed' and isinstance(operations, list):
                operation_cursor = int(event_payload.get('operationCursor') or 0)
                coordinates = cls._draft_preview_coordinates(job_id, operation_cursor)
                if coordinates is None:
                    raise MindmapArtifactError(
                        'AI 实时草稿版本超过上限，无法继续直写',
                        code='AI_BUDGET_EXCEEDED',
                    )
                direct_commit = await cls._commit_direct_draft(
                    db,
                    job,
                    operations,
                    coordinates[0],
                )
                if direct_commit is not None:
                    committed_document = direct_commit.pop('_committedDocument', None)
                    if not isinstance(committed_document, dict):
                        raise MindmapArtifactError(
                            'AI 直写提交未返回权威正文，无法保存实时检查点',
                            code='AI_DOCUMENT_CONFLICT',
                        )
                    preview_state, committed_summary = cls._project_committed_preview(job, committed_document)
                    event_payload['summary'] = committed_summary
                    if (
                        int(direct_commit.get('operationCount') or 0) > 0
                        or int(direct_commit.get('commentCount') or 0) > 0
                    ):
                        direct_undo_id = await cls._ensure_direct_undo_receipt(db, job)
                    if direct_undo_id and isinstance(
                        direct_commit.get('contentRevision'), int,
                    ):
                        await cls._record_direct_undo_commit(db, job, direct_undo_id, direct_commit)
                    event_payload['directCommit'] = {
                        'contentRevision': direct_commit.get('contentRevision'),
                        'operationGroupId': direct_commit.get('operationGroupId'),
                        'operationCount': direct_commit.get('operationCount', len(operations)),
                        'affectedUids': direct_commit.get('affectedUids', []),
                        'commentCount': direct_commit.get('commentCount', 0),
                        'changeSummary': direct_commit.get(
                            'changeSummary',
                            {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 0},
                        ),
                        'idempotentReplay': bool(direct_commit.get('idempotentReplay')),
                        'proposalId': direct_undo_id,
                    }
                    event_payload['changeSummary'] = direct_commit.get(
                        'changeSummary',
                        {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 0},
                    )
            cache_after_commit: dict[str, Any] | None = None
            if event_type == 'draft_changed':
                event_payload['changeCount'] = len(operations) if isinstance(operations, list) else 0
                event_payload.pop('operationCursor', None)
                if coordinates is not None:
                    preview_version, preview_epoch = coordinates
                    event_payload['previewVersion'] = preview_version
                    event_payload['previewEpoch'] = preview_epoch
            checkpoint_coordinates: tuple[int, int] | None = None
            if event_type == 'draft_changed' and coordinates is not None:
                checkpoint_coordinates = coordinates
            elif event_type == 'draft_initialized':
                raw_version = event_payload.get('previewVersion')
                raw_epoch = event_payload.get('previewEpoch')
                if (
                    isinstance(raw_version, int)
                    and not isinstance(raw_version, bool)
                    and 0 <= raw_version <= AI_DRAFT_PREVIEW_MAX_VERSION
                    and isinstance(raw_epoch, int)
                    and not isinstance(raw_epoch, bool)
                    and raw_epoch >= 1
                ):
                    checkpoint_coordinates = (raw_version, raw_epoch)
            if isinstance(preview_state, dict) and checkpoint_coordinates is not None:
                preview_version, preview_epoch = checkpoint_coordinates
                checkpoint_values = cls._draft_checkpoint_values(
                    job_id=job_id,
                    document=preview_state,
                    operations=operations if isinstance(operations, list) else [],
                    initial_state=initial_state if isinstance(initial_state, dict) else None,
                    preview_version=preview_version,
                    preview_epoch=preview_epoch,
                    summary=event_payload.get('summary'),
                    expires_time=job.expires_time,
                )
                try:
                    _checkpoint, checkpoint_changed = await MindmapAiDao.upsert_draft_checkpoint(
                        db,
                        checkpoint_values,
                    )
                except ValueError as exc:
                    # The DAO raises ValueError only when a replayed preview
                    # coordinate is paired with a different document hash.
                    # That is a stale/ambiguous draft frame, not a database
                    # outage; preserve a stable domain code so adapters do
                    # not turn it into AgentEventDeliveryError.
                    await db.rollback()
                    if '坐标冲突' in str(exc):
                        raise MindmapArtifactError(
                            'AI 实时草稿版本冲突，请重新同步后重试',
                            code='AI_DOCUMENT_CONFLICT',
                        ) from exc
                    raise MindmapArtifactError(
                        'AI 实时草稿检查点数据无效',
                        code='AI_OUTPUT_INVALID',
                    ) from exc
                checkpoint_matches = (
                    int(_checkpoint.preview_epoch) == preview_epoch
                    and int(_checkpoint.preview_version) == preview_version
                    and str(_checkpoint.document_hash) == checkpoint_values['document_hash']
                )
                event_payload['previewAvailable'] = checkpoint_matches
                if checkpoint_changed and expected_execution_epoch is not None:
                    cache_after_commit = {
                        'document': preview_state,
                        'operation_cursor': preview_version,
                        'preview_epoch': preview_epoch,
                        'summary': event_payload.get('summary'),
                        'expected_execution_epoch': expected_execution_epoch,
                    }
            elif event_type in {'draft_changed', 'draft_initialized'}:
                event_payload['previewAvailable'] = False
            safe_payload = _safe_event_payload(event_payload)
            try:
                event_record = await MindmapAiDao.add_event(
                    db,
                    job_id,
                    event_type,
                    _json_dumps(safe_payload),
                )
            except IntegrityError as exc:
                # A duplicate event sequence can occur when a recovered
                # worker races a late frame from the previous lease.  The
                # direct mutation/checkpoint are staged in this transaction,
                # so roll them back together and surface a retryable domain
                # conflict rather than an infrastructure persistence error.
                await db.rollback()
                raise MindmapArtifactError(
                    'AI 实时事件序号冲突，请重新同步后重试',
                    code='AI_DOCUMENT_CONFLICT',
                ) from exc
            # add_event returns None when a concurrent terminal transition
            # makes this frame stale. No checkpoint (and especially no direct
            # document mutation) may commit without its durable event/audit
            # anchor in that case. Rolling back for every event also prevents
            # a late preview frame from resurrecting a terminal task's draft.
            if event_record is None:
                await db.rollback()
                return
            try:
                await db.commit()
            except IntegrityError as exc:
                # Some dialects defer unique/FK checks until commit.  Keep
                # the same classification as the flush path above while
                # allowing genuine operational/database errors to retain the
                # AgentEventDeliveryError path for diagnostics.
                await db.rollback()
                raise MindmapArtifactError(
                    'AI 实时事件提交发生冲突，请重新同步后重试',
                    code='AI_DOCUMENT_CONFLICT',
                ) from exc
            # The direct document mutation is staged in this same transaction
            # as the checkpoint and event. Only notify collaborators after the
            # commit succeeds; otherwise a client could reload a revision that
            # is later rolled back with the task event.
            if direct_commit is not None and job.source_mindmap_id:
                next_revision = direct_commit.get('_nextExpectedRevision')
                if isinstance(next_revision, int):
                    cls._direct_commit_revisions[job_id] = next_revision
                await MindmapAiMutationGateway.publish_direct_commit(
                    int(job.source_mindmap_id),
                    direct_commit,
                )
        # Redis is a disposable read cache. Populate it only after the durable
        # checkpoint and its content-free event metadata commit together.
        if cache_after_commit is not None:
            try:
                await cls._store_draft_preview(job_id, **cache_after_commit)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A cache outage must not turn an already committed document
                # mutation + audit event into a provider failure. The durable
                # checkpoint remains the recovery source for the next poll.
                logger.exception(
                    f'AI 脑图实时草稿缓存写入异常，已保留数据库检查点: job_id={job_id}',
                )

    @classmethod
    async def _set_status(
        cls,
        job_id: str,
        status: str,
        progress: int,
        **values: Any,
    ) -> bool:
        lease_token = _CURRENT_JOB_LEASE_TOKEN.get()
        terminal_execution_epoch = int(_CURRENT_JOB_EXECUTION_EPOCH.get() or 0)
        if lease_token is not None and not await cls._owns_job_lease(job_id, lease_token):
            return False
        predecessors = JOB_STATUS_PREDECESSORS.get(status)
        if predecessors is None:
            raise RuntimeError(f'未声明的 AI 任务状态迁移: {status}')
        async with AsyncSessionLocal() as db:
            if lease_token is not None:
                job = await MindmapAiDao.get_job(db, job_id, for_update=True)
                expected_execution_epoch = _CURRENT_JOB_EXECUTION_EPOCH.get()
                if (
                    job is None
                    or (
                        expected_execution_epoch is not None
                        and int(getattr(job, 'execution_epoch', -1))
                        != expected_execution_epoch
                    )
                    or not await cls._owns_job_lease(job_id, lease_token)
                ):
                    await db.rollback()
                    return False
                terminal_execution_epoch = int(
                    getattr(job, 'execution_epoch', terminal_execution_epoch) or 0
                )
            changed = await MindmapAiDao.transition_job_status(
                db,
                job_id,
                predecessors,
                {'status': status, 'progress': progress, **values},
            )
            if not changed:
                await db.rollback()
                return False
            event_payload = {'status': status, 'progress': progress}
            if values.get('error_code'):
                event_payload['errorCode'] = values['error_code']
            if values.get('error_message'):
                event_payload['errorMessage'] = str(values['error_message'])[:500]
            await MindmapAiDao.add_event(
                db,
                job_id,
                'status_changed',
                _event_json(event_payload),
            )
            terminal_status = status in TERMINAL_JOB_STATUSES
            if terminal_status:
                await MindmapAiDao.delete_draft_checkpoint(db, job_id)
            await db.commit()
        if terminal_status:
            await cls.mark_draft_terminal(job_id, terminal_execution_epoch)
        return True

    @classmethod
    async def _wake_waiting_followups(  # noqa: PLR0912, PLR0915
        cls,
        parent_job_id: str,
    ) -> None:
        """Release prompts submitted during a turn after its result is durable."""
        released_ids: list[str] = []
        try:
            async with AsyncSessionLocal() as db:
                parent = await MindmapAiDao.get_job(db, parent_job_id, for_update=True)
                if parent is None:
                    return
                if parent.status in {
                    'cancelled', 'failed', 'expired', 'stale', 'rejected',
                }:
                    await db.rollback()
                    await cls._close_waiting_followups(
                        parent_job_id,
                        parent_status=str(parent.status),
                    )
                    return
                if parent.status not in {
                    'ready', 'applied', 'undone', 'completed_file',
    'completed_no_change', 'completed_direct', 'needs_review', 'completed_message',
                }:
                    return
                # A review result is visible in the canvas, but its proposed
                # write has not been accepted yet.  Do not let a queued child
                # consume that unconfirmed artifact.  The explicit apply or
                # reject path wakes/closes children after its own commit.
                if parent.status == 'needs_review':
                    return
                waiting_jobs = await MindmapAiDao.list_waiting_followups(
                    db,
                    parent_job_id,
                    for_update=True,
                )
                if not waiting_jobs:
                    return
                # A user may submit several follow-up prompts while one turn is
                # running. Keep them as a real queue: release only the oldest
                # child and attach any legacy siblings to that child so the
                # next result becomes the source for the following turn.
                waiting_jobs.sort(
                    key=lambda item: (
                        int(getattr(item, 'turn_index', 0) or 0),
                        getattr(item, 'created_time', datetime.min),
                        str(getattr(item, 'id', '')),
                    ),
                )
                next_waiting_job = waiting_jobs[0]
                deferred_jobs = waiting_jobs[1:]
                waiting_job = next_waiting_job
                waiting_route = _waiting_followup_route(waiting_job)
                # ``next`` is deliberately tied to an accepted result.  A
                # ready proposal is only a preview; starting its successor
                # here would make the successor depend on a document change
                # the user may still reject.  Check this before reading the
                # artifact so the waiting path has no observable side effect.
                if (
                    waiting_route == 'next'
                    and parent.status == 'ready'
                    and parent.proposal_id
                ):
                    await db.rollback()
                    return
                artifact_document = None
                artifact_hash = None
                if parent.artifact_id:
                    artifact = await MindmapAiDao.get_artifact(
                        db,
                        parent.artifact_id,
                        parent.user_id,
                    )
                    if artifact is not None:
                        artifact_payload = _json_loads(artifact.content_json, {})
                        artifact_document = artifact_payload.get('document')
                        artifact_hash = artifact_payload.get('manifest', {}).get('documentHash')
                for waiting_job in deferred_jobs:
                    deferred_route = _waiting_followup_route(waiting_job)
                    await MindmapAiDao.update_job(db, waiting_job.id, {
                        'parent_job_id': next_waiting_job.id,
                    })
                    await MindmapAiDao.add_event(
                        db,
                        waiting_job.id,
                        'queue_reparented',
                        _event_json({
                            'status': WAITING_TURN_STATUS,
                            'progress': 0,
                            'parentJobId': next_waiting_job.id,
                            'route': deferred_route,
                        }),
                    )
                waiting_job = next_waiting_job
                values: dict[str, Any] = {
                    'status': 'queued',
                    'progress': 0,
                    'error_code': None,
                    'error_message': None,
                }
                # Direct turns have no historical artifact in older rows (and
                # deliberately write the authoritative document in place).
                # A queued child must nevertheless be rebased to the document
                # that the parent actually left behind; carrying the frozen
                # request snapshot here would make the child run against a
                # stale CAS revision after the parent completed.
                parent_request_payload = _json_loads(
                    getattr(parent, 'request_json', None),
                )
                direct_authoritative_parent = (
                    getattr(parent, 'source_type', None) == 'cloud_document'
                    and getattr(parent, 'source_mindmap_id', None)
                    and (
                        parent.status == 'completed_direct'
                        or (
                            parent.status == 'undone'
                            and (
                                parent_request_payload.get('executionMode') == 'direct'
                                or getattr(parent, 'proposal_id', None) == str(parent.id)
                            )
                        )
                    )
                )
                if direct_authoritative_parent:
                    request_payload = _json_loads(waiting_job.request_json, {})
                    source_payload = request_payload.get('source') or {}
                    if source_payload.get('type') != 'cloud_document':
                        raise MindmapArtifactError(
                            '排队直写任务缺少云端脑图来源',
                            code='AI_FOLLOWUP_BASE_INVALID',
                        )
                    authoritative_request = dict(request_payload)
                    authoritative_request['source'] = dict(source_payload)
                    authoritative_model = MindmapAiJobCreateModel.model_validate(
                        authoritative_request,
                    )
                    undo_baseline: dict[str, Any] = {}
                    (
                        authoritative_document,
                        authoritative_revision,
                        authoritative_hash,
                        authoritative_mindmap_id,
                        authoritative_room_epoch,
                    ) = await MindmapAiService._prepare_source_for_job(
                        db,
                        authoritative_model,
                        parent.user_id,
                        capture_editor_document=undo_baseline,
                    )
                    if (
                        not isinstance(authoritative_document, dict)
                        or authoritative_mindmap_id != parent.source_mindmap_id
                    ):
                        raise MindmapArtifactError(
                            '无法冻结排队任务的最新云端脑图基线',
                            code='AI_FOLLOWUP_BASE_INVALID',
                        )
                    source_payload = dict(source_payload)
                    source_payload['document'] = authoritative_document
                    source_payload['baselineDocument'] = authoritative_document
                    source_payload['revision'] = authoritative_revision
                    source_payload['documentHash'] = authoritative_hash
                    source_payload['roomEpoch'] = authoritative_room_epoch
                    source_payload['mindmapId'] = authoritative_mindmap_id
                    request_payload['source'] = source_payload
                    values.update({
                        'request_json': _json_dumps(_request_with_undo_baseline(request_payload, undo_baseline)),
                        'source_type': 'cloud_document',
                        'base_revision': authoritative_revision,
                        'base_hash': authoritative_hash,
                        'base_room_epoch': authoritative_room_epoch,
                    })
                elif isinstance(artifact_document, dict):
                    request_payload = _json_loads(waiting_job.request_json, {})
                    source_payload = request_payload.get('source') or {}
                    source_type = source_payload.get('type')
                    if source_type in {'local_snapshot', 'cloud_document'}:
                        if parent.status in {'applied', 'undone'}:
                            # Once the parent has been accepted (or undone),
                            # the next turn must start from the authoritative
                            # document, not the old cumulative proposal base.
                            # Cloud documents are re-read after the write
                            # barrier; local documents use the applied artifact
                            # or the original baseline for an undo.
                            if source_type == 'cloud_document':
                                authoritative_request = dict(request_payload)
                                authoritative_request['source'] = dict(source_payload)
                                authoritative_model = MindmapAiJobCreateModel.model_validate(
                                    authoritative_request,
                                )
                                undo_baseline = {}
                                (
                                    authoritative_document,
                                    authoritative_revision,
                                    authoritative_hash,
                                    authoritative_mindmap_id,
                                    authoritative_room_epoch,
                                ) = await MindmapAiService._prepare_source_for_job(
                                    db,
                                    authoritative_model,
                                    parent.user_id,
                                    capture_editor_document=undo_baseline,
                                )
                                if (
                                    not isinstance(authoritative_document, dict)
                                    or authoritative_mindmap_id != parent.source_mindmap_id
                                ):
                                    raise MindmapArtifactError(
                                        '无法冻结排队任务的最新云端脑图基线',
                                        code='AI_FOLLOWUP_BASE_INVALID',
                                    )
                                source_payload['document'] = authoritative_document
                                source_payload['baselineDocument'] = authoritative_document
                                source_payload['revision'] = authoritative_revision
                                source_payload['documentHash'] = authoritative_hash
                                source_payload['roomEpoch'] = authoritative_room_epoch
                                request_payload = _request_with_undo_baseline(request_payload, undo_baseline)
                                values['base_revision'] = authoritative_revision
                                values['base_hash'] = authoritative_hash
                                values['base_room_epoch'] = authoritative_room_epoch
                            else:
                                proposal = await MindmapAiDao.get_proposal(
                                    db,
                                    parent.proposal_id,
                                    parent.user_id,
                                ) if parent.proposal_id else None
                                if parent.status == 'applied':
                                    authoritative_document = artifact_document
                                    authoritative_hash = artifact_hash or compute_document_hash(
                                        authoritative_document,
                                    )
                                else:
                                    authoritative_document = (
                                        source_payload.get('baselineDocument')
                                        or source_payload.get('document')
                                    )
                                    authoritative_document, _summary = (
                                        normalize_ai_editable_source_document(
                                            authoritative_document,
                                        )
                                    )
                                    authoritative_hash = compute_document_hash(
                                        authoritative_document,
                                    )
                                source_payload['document'] = authoritative_document
                                source_payload['baselineDocument'] = authoritative_document
                                source_payload['documentHash'] = authoritative_hash
                                applied_revision = getattr(proposal, 'applied_revision', None)
                                if applied_revision is not None:
                                    authoritative_revision = int(applied_revision)
                                    if parent.status == 'undone':
                                        authoritative_revision += 1
                                    source_payload['revision'] = authoritative_revision
                                    values['base_revision'] = authoritative_revision
                                values['base_hash'] = authoritative_hash
                        else:
                            original_document = (
                                source_payload.get('baselineDocument')
                                or source_payload.get('document')
                            )
                            source_payload['baselineDocument'] = original_document
                            source_payload['document'] = artifact_document
                            if artifact_hash:
                                source_payload['documentHash'] = artifact_hash
                            values['base_hash'] = waiting_job.base_hash
                        request_payload['source'] = source_payload
                    else:
                        request_payload['source'] = {
                            'type': 'uploaded_artifact',
                            'scope': source_payload.get('scope') or {'type': 'document'},
                            'document': artifact_document,
                        }
                        request_payload['target'] = 'file'
                    values['request_json'] = _json_dumps(request_payload)
                    values['source_type'] = request_payload['source']['type']
                    if 'base_hash' not in values:
                        values['base_hash'] = waiting_job.base_hash
                await MindmapAiDao.update_job(db, waiting_job.id, values)
                await MindmapAiDao.add_event(
                    db,
                    waiting_job.id,
                    'status_changed',
                    _event_json({
                        'status': 'queued',
                        'progress': 0,
                        'parentJobId': parent_job_id,
                        'route': waiting_route,
                    }),
                )
                released_ids.append(str(waiting_job.id))
                await db.commit()
        except Exception:
            logger.exception(f'AI 排队轮次释放失败: parent_job_id={parent_job_id}')
            return
        for released_id in released_ids:
            MindmapAiTaskManager.schedule(released_id)
        if released_ids:
            record_mindmap_ai_event('job_released')

    @classmethod
    async def _close_waiting_followups(
        cls,
        parent_job_id: str,
        *,
        parent_status: str,
    ) -> None:
        """Finish queued prompts when their parent can no longer produce a base.

        A waiting child is deliberately not started from a failed or cancelled
        parent: doing so could silently use a stale document revision or a
        partial draft. Keep the message and let the user resend it explicitly
        against the current canvas instead of leaving an invisible queue item
        behind forever.
        """
        try:
            async with AsyncSessionLocal() as db:
                root = await MindmapAiDao.get_job(
                    db,
                    parent_job_id,
                    for_update=True,
                )
                if root is None:
                    return
                session_jobs = await MindmapAiDao.list_jobs_for_session(
                    db,
                    root.session_id,
                    for_update=True,
                )
                by_parent: dict[str, list[Any]] = {}
                for session_job in session_jobs:
                    if session_job.status != WAITING_TURN_STATUS:
                        continue
                    by_parent.setdefault(str(session_job.parent_job_id or ''), []).append(session_job)
                waiting_jobs: list[Any] = []
                pending_parent_ids = [str(parent_job_id)]
                seen_parent_ids: set[str] = set()
                while pending_parent_ids:
                    current_parent_id = pending_parent_ids.pop(0)
                    if current_parent_id in seen_parent_ids:
                        continue
                    seen_parent_ids.add(current_parent_id)
                    children = by_parent.get(current_parent_id, [])
                    waiting_jobs.extend(children)
                    pending_parent_ids.extend(str(child.id) for child in children)
                if not waiting_jobs:
                    return
                now = datetime.now()
                error_code = 'AI_PARENT_TASK_CANCELLED'
                error_message = (
                    '上一轮 AI 任务已取消，排队要求暂未执行；请基于当前脑图重新发送。'
                    if parent_status == 'cancelled'
                    else '上一轮 AI 结果未被采纳，排队要求暂未执行；请基于当前脑图重新发送。'
                    if parent_status == 'rejected'
                    else '上一轮 AI 任务未完成，排队要求暂未执行；请基于当前脑图重新发送。'
                )
                for waiting_job in waiting_jobs:
                    await MindmapAiDao.update_job(db, waiting_job.id, {
                        'status': 'cancelled',
                        'progress': 100,
                        'error_code': error_code,
                        'error_message': error_message,
                        'completed_time': now,
                    })
                    await MindmapAiDao.add_event(
                        db,
                        waiting_job.id,
                        'status_changed',
                        _event_json({
                            'status': 'cancelled',
                            'progress': 100,
                            'errorCode': error_code,
                            'errorMessage': error_message,
                            'parentJobId': waiting_job.parent_job_id or parent_job_id,
                            'route': 'next',
                        }),
                    )
                await db.commit()
        except Exception:
            # Cancellation must still return the authoritative parent status if
            # a best-effort queue cleanup loses a database race. Recovery scans
            # waiting descendants again, so swallowing this error cannot start
            # a stale child or lose the user's message.
            logger.exception(
                f'AI 排队轮次收敛失败，将由恢复任务重试: parent_job_id={parent_job_id}'
            )
        record_mindmap_ai_event('queued_followup_closed')

    @classmethod
    async def _resolve_native_model(cls, db: AsyncSession, user_id: int, model_id: int | None) -> Any:
        if model_id is not None:
            record = await AiModelDao.get_ai_model_detail_by_id(db, model_id)
            if record is not None and record.user_id not in {None, user_id}:
                record = None
        else:
            record = (await db.execute(
                select(AiModels)
                .where(
                    AiModels.status == '0',
                    or_(AiModels.user_id.is_(None), AiModels.user_id == user_id),
                )
                .order_by(AiModels.model_sort.asc(), AiModels.model_id.asc())
                .limit(1)
            )).scalars().first()
        if record is None or record.status != '0':
            raise MindmapArtifactError('没有可用的 AI 模型配置', code='AI_PROVIDER_AUTH_FAILED')
        provider = str(getattr(record, 'provider', '') or '').strip()
        base_url = getattr(record, 'base_url', None)
        # DashScope's OpenAI-compatible endpoint must be constructed through
        # the DashScope/OpenAI adapter.  Passing it to Claude can otherwise
        # fail later with an opaque provider error (and needlessly decrypt a
        # credential first).
        if provider.lower() == 'anthropic' and base_url and 'dashscope.aliyuncs.com/compatible-mode' in str(base_url).lower():
            raise MindmapArtifactError(
                '当前地址是 DashScope 兼容接口，请将提供商改为 DashScope 或 OpenAI 后重试。',
                code='AI_MODEL_CONFIG_INVALID',
            )
        try:
            api_key = getattr(record, 'api_key', None)
            real_api_key = CryptoUtil.decrypt(api_key) if api_key else None
        except Exception as exc:
            logger.warning('AI 模型密钥解密失败: provider=%s, model=%s', provider, getattr(record, 'model_code', None))
            raise MindmapArtifactError(
                'AI 模型密钥无法解密，请重新保存密钥后重试。',
                code='AI_MODEL_CONFIG_INVALID',
            ) from exc
        try:
            return AiUtil.get_model_from_factory(
                provider=provider,
                model_code=getattr(record, 'model_code', ''),
                model_name=getattr(record, 'model_name', None),
                api_key=real_api_key,
                base_url=base_url,
                temperature=getattr(record, 'temperature', None),
                max_tokens=getattr(record, 'max_tokens', None),
            )
        except Exception as exc:
            logger.warning('AI 模型构造失败: provider=%s, model=%s', provider, getattr(record, 'model_code', None))
            raise MindmapArtifactError(
                'AI 模型配置无效，请检查提供商、模型和接口地址后重试。',
                code='AI_MODEL_CONFIG_INVALID',
            ) from exc

    @staticmethod
    def _agent_context_metadata(
        *,
        model: Any,
        model_ref: str | None,
        max_budget_usd: float,
        timeout_seconds: int,
        retention_days: int,
        credential_env: dict[str, str],
    ) -> dict[str, Any]:
        """构造传给 Adapter 的服务端策略快照。"""
        return {
            'model': model,
            'modelRef': model_ref,
            'maxBudgetUsd': max_budget_usd,
            'timeoutSeconds': timeout_seconds,
            'retentionDays': retention_days,
            'credentialEnv': credential_env,
        }

    @classmethod
    async def _await_adapter_result(
        cls,
        job_id: str,
        runner_call: Any,
        timeout_seconds: int | None = None,
        *,
        cancel_grace_seconds: float | None = None,
        discard_result: Callable[[Any], Awaitable[None]] | None = None,
    ) -> Any:
        """等待 Adapter，并跨 worker 观察持久化取消状态。"""
        task = asyncio.create_task(runner_call, name=f'mindmap-ai-adapter:{job_id}')
        cleanup_attempted = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (
            timeout_seconds or MindmapAiConfig.mindmap_ai_job_timeout_seconds
        )
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    await cls._cancel_adapter_task(
                        task,
                        job_id,
                        grace_seconds=cancel_grace_seconds,
                    )
                    cleanup_attempted = True
                    raise TimeoutError
                done, _pending = await asyncio.wait({task}, timeout=min(0.5, remaining))
                if task in done:
                    result = task.result()
                    try:
                        async with AsyncSessionLocal() as db:
                            job = await MindmapAiDao.get_job(db, job_id)
                        if job is None or job.status in {'cancel_requested', 'cancelled'}:
                            raise asyncio.CancelledError
                    except BaseException:
                        if discard_result is not None:
                            try:
                                await discard_result(result)
                            except BaseException:
                                logger.exception(
                                    '丢弃迟到 Adapter 结果时清理 SDK 会话失败: '
                                    f'job_id={job_id}'
                                )
                        raise
                    return result
                async with AsyncSessionLocal() as db:
                    job = await MindmapAiDao.get_job(db, job_id)
                if job is None or job.status in {'cancel_requested', 'cancelled'}:
                    await cls._cancel_adapter_task(
                        task,
                        job_id,
                        grace_seconds=cancel_grace_seconds,
                    )
                    cleanup_attempted = True
                    raise asyncio.CancelledError
        finally:
            if not task.done() and not cleanup_attempted:
                await cls._cancel_adapter_task(
                    task,
                    job_id,
                    grace_seconds=cancel_grace_seconds,
                )

    @classmethod
    async def _cancel_adapter_task(
        cls,
        task: asyncio.Task[Any],
        job_id: str,
        *,
        grace_seconds: float | None = None,
    ) -> bool:
        """有界等待 Adapter 响应取消，防止第三方实现吞掉 CancelledError。"""
        if task.done():
            cls._consume_task_exception(task)
            return True
        task.cancel()
        grace = (
            float(grace_seconds)
            if grace_seconds is not None
            else float(MindmapAiConfig.mindmap_ai_adapter_cancel_grace_seconds)
        )
        done, _pending = await asyncio.wait({task}, timeout=max(0.0, grace))
        if task in done:
            cls._consume_task_exception(task)
            return True

        logger.error(
            f'AI 脑图 Adapter 在取消宽限期内未退出，已隔离迟到结果: job_id={job_id}'
        )
        cls._detached_adapter_tasks.add(task)

        def forget_detached(done_task: asyncio.Task[Any]) -> None:
            cls._detached_adapter_tasks.discard(done_task)
            cls._consume_task_exception(done_task)

        task.add_done_callback(forget_detached)
        return False

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[Any]) -> None:
        try:
            task.exception()
        except BaseException:
            pass

    @staticmethod
    def _owned_external_session_id(
        result: Any,
        parent_external_session_id: str | None,
    ) -> str | None:
        """Validate explicit provider-session ownership without claiming a parent."""
        session_id = getattr(result, 'external_session_id', None)
        created = getattr(result, 'external_session_created', False)
        if created is not True:
            if session_id and session_id != parent_external_session_id:
                raise MindmapArtifactError(
                    'Agent 未声明新建 SDK 会话的所有权',
                    code='AI_SESSION_UNAVAILABLE',
                )
            return None
        if not isinstance(session_id, str) or not session_id:
            raise MindmapArtifactError(
                'Agent 返回的新建 SDK 会话标识无效',
                code='AI_SESSION_UNAVAILABLE',
            )
        if parent_external_session_id is not None and session_id == parent_external_session_id:
            # A buggy or malicious adapter must never trick the service into
            # deleting the reusable parent on a later validation failure.
            raise MindmapArtifactError(
                'Agent 错误声明了父 SDK 会话的所有权',
                code='AI_SESSION_UNAVAILABLE',
            )
        return session_id

    @staticmethod
    def _resolve_parent_external_session_id(
        parent_job: Any,
        *,
        agent_key: str,
        supports_sessions: bool,
    ) -> str | None:
        """Restore a same-Agent parent session without silently starting over.

        Cross-Agent and session-less follow-ups intentionally rebuild from the
        persisted artifact.  A ``needs_input`` parent is also an immutable
        terminal turn: its answer creates a fresh provider turn from the frozen
        source plus the user's supplement, and must never revive the provider
        session that produced the clarification request.  Other same-Agent
        follow-ups that advertise durable sessions fail closed when their
        encrypted reference is absent or corrupt.
        """
        if parent_job is None:
            raise MindmapArtifactError(
                '父 AI 任务不存在，无法恢复会话',
                code='AI_SESSION_UNAVAILABLE',
            )
        if getattr(parent_job, 'status', None) == 'needs_input':
            return None
        if parent_job.agent_key != agent_key or not supports_sessions:
            return None
        encrypted_ref = getattr(parent_job, 'external_session_ref', None)
        if not isinstance(encrypted_ref, str) or not encrypted_ref:
            raise MindmapArtifactError(
                '父 AI 任务缺少可恢复的 SDK 会话引用',
                code='AI_SESSION_UNAVAILABLE',
            )
        try:
            external_session_id = CryptoUtil.decrypt(encrypted_ref)
        except Exception as exc:
            raise MindmapArtifactError(
                'AI SDK 会话引用无法恢复',
                code='AI_SESSION_UNAVAILABLE',
            ) from exc
        if not isinstance(external_session_id, str) or not external_session_id:
            raise MindmapArtifactError(
                'AI SDK 会话引用无法恢复',
                code='AI_SESSION_UNAVAILABLE',
            )
        return external_session_id

    @staticmethod
    def _same_provider_session_contract(parent_job: Any, job: Any) -> bool:
        """Whether two platform turns may share one provider SDK session."""
        return bool(
            parent_job is not None
            and parent_job.intent == job.intent
            and parent_job.target == job.target
        )

    @classmethod
    async def _visible_discussion_history(
        cls,
        db: AsyncSession,
        job: Any,
    ) -> tuple[dict[str, str], ...]:
        """Build only the selected parent lineage; never expose audit/provider data."""
        if not job.parent_job_id:
            return ()
        jobs = await MindmapAiDao.list_jobs_for_session(db, job.session_id)
        by_id = {str(item.id): item for item in jobs}
        lineage: list[Any] = []
        cursor = str(job.parent_job_id)
        seen: set[str] = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            parent = by_id.get(cursor)
            if parent is None:
                raise MindmapArtifactError(
                    '讨论历史不完整，无法继续当前会话',
                    code='AI_SESSION_UNAVAILABLE',
                )
            if parent.intent == 'discuss' and parent.status == 'completed_message':
                lineage.append(parent)
            cursor = str(parent.parent_job_id or '')
        lineage.reverse()
        lineage = lineage[-(AI_DISCUSSION_HISTORY_MAX_MESSAGES // 2):]
        responses = await MindmapAiDao.get_responses_for_jobs(
            db,
            [str(item.id) for item in lineage],
            job.user_id,
        )
        messages: list[dict[str, str]] = []
        for item in lineage:
            request_payload = _json_loads(item.request_json, {})
            prompt = request_payload.get('prompt') if isinstance(request_payload, dict) else None
            response = responses.get(str(item.id))
            if not isinstance(prompt, str) or response is None:
                raise MindmapArtifactError(
                    '讨论历史已过期或不完整，无法继续当前会话',
                    code='AI_SESSION_UNAVAILABLE',
                )
            messages.extend((
                {'role': 'user', 'content': prompt[:AI_PROMPT_MAX_LENGTH]},
                {'role': 'assistant', 'content': str(response.content_text)},
            ))
        total = 0
        bounded: list[dict[str, str]] = []
        for message in reversed(messages):
            bounded_message = message
            length = len(bounded_message['content'])
            if bounded and total + length > AI_DISCUSSION_HISTORY_MAX_CHARS:
                break
            if length > AI_DISCUSSION_HISTORY_MAX_CHARS:
                bounded_message = {
                    **bounded_message,
                    'content': bounded_message['content'][-AI_DISCUSSION_HISTORY_MAX_CHARS:],
                }
                length = len(bounded_message['content'])
            bounded.append(bounded_message)
            total += length
        bounded.reverse()
        return tuple(bounded)

    @classmethod
    async def _purge_uncommitted_external_session(
        cls,
        adapter: Any,
        external_session_id: str,
        job_id: str,
    ) -> None:
        """Best-effort bounded cleanup for an owned result that was not committed."""
        purge_task = asyncio.create_task(
            adapter.purge_session(external_session_id),
            name=f'mindmap-ai-session-purge:{job_id}',
        )
        grace = float(MindmapAiConfig.mindmap_ai_adapter_cancel_grace_seconds)
        try:
            done, _pending = await asyncio.wait({purge_task}, timeout=grace)
        except asyncio.CancelledError:
            done = set()
        if purge_task in done:
            try:
                purge_task.result()
            except BaseException:
                logger.exception(
                    f'未提交的 AI SDK 会话清理失败: job_id={job_id}'
                )
            return

        # Do not cancel provider cleanup when the runner itself is cancelled.
        # Keep consuming its result so a late cleanup cannot surface as an
        # unhandled task exception.
        logger.warning(
            f'未提交的 AI SDK 会话仍在后台清理: job_id={job_id}'
        )
        cls._detached_adapter_tasks.add(purge_task)

        def forget_cleanup(done_task: asyncio.Task[Any]) -> None:
            cls._detached_adapter_tasks.discard(done_task)
            cls._consume_task_exception(done_task)

        purge_task.add_done_callback(forget_cleanup)

    @staticmethod
    async def _reconcile_external_session_commit(
        job_id: str,
        encrypted_session_ref: str,
    ) -> bool | None:
        """Resolve an ambiguous completion commit using a brand-new DB session.

        ``True`` means the exact encrypted reference is durable, ``False`` means
        the database definitively does not reference it, and ``None`` means the
        check itself failed. Unknown results deliberately retain the provider
        session because deleting a possibly committed session is irreversible.
        """
        try:
            async with AsyncSessionLocal() as reconciliation_db:
                persisted_job = await MindmapAiDao.get_job(
                    reconciliation_db,
                    job_id,
                )
        except (Exception, asyncio.CancelledError):
            logger.exception(
                f'AI SDK 会话提交状态无法对账，已保守保留: job_id={job_id}'
            )
            return None
        if persisted_job is None:
            return False
        return getattr(persisted_job, 'external_session_ref', None) == encrypted_session_ref

    @classmethod
    async def _lock_completion_target(
        cls,
        db: AsyncSession,
        job_id: str,
    ) -> tuple[Any, Any]:
        """Fence result writes behind the job and its still-active session."""
        current_job = await MindmapAiDao.get_job(db, job_id, for_update=True)
        expected_execution_epoch = _CURRENT_JOB_EXECUTION_EPOCH.get()
        if (
            current_job is None
            or current_job.status != 'validating'
            or (
                expected_execution_epoch is not None
                and int(getattr(current_job, 'execution_epoch', -1))
                != expected_execution_epoch
            )
        ):
            await db.rollback()
            raise asyncio.CancelledError

        # Every transaction that needs both rows takes job before session. In
        # particular, session deletion must never hold this session row while
        # waiting for jobs. The status check is performed before any artifact
        # or provider-session reference is persisted, so a deleting session
        # cannot be revived by a late adapter result.
        current_session = await MindmapAiDao.get_session(
            db,
            current_job.session_id,
            for_update=True,
        )
        if (
            not _session_accepts_work(current_session)
            or not await cls._owns_current_job_lease(job_id)
        ):
            await db.rollback()
            raise asyncio.CancelledError
        return current_job, current_session

    @classmethod
    async def _run_job(cls, job_id: str) -> None:  # noqa: PLR0912, PLR0915
        started_at = time.perf_counter()
        agent_key = 'unresolved'
        sdk_version = 'unknown'
        runtime_version = 'unknown'
        model_ref = 'unknown'
        adapter: Any | None = None
        parent_external_session_id: str | None = None
        pending_external_session_id: str | None = None
        external_session_committed = False
        completion_commit_uncertain = False
        attempted_encrypted_session_ref: str | None = None

        def record_run(outcome: str, usage: dict[str, Any] | None = None) -> None:
            record_mindmap_ai_run(
                agent_key,
                outcome,
                time.perf_counter() - started_at,
                usage,
                sdk_version=sdk_version,
                runtime_version=runtime_version,
                model_ref=model_ref,
            )

        try:
            if not await cls._set_status(job_id, 'preparing', 10):
                return
            recovered_preview: dict[str, Any] | None = None
            async with AsyncSessionLocal() as db:
                preliminary_job = await MindmapAiDao.get_job(db, job_id)
                discussion_job = bool(
                    preliminary_job is not None
                    and preliminary_job.intent == 'discuss'
                    and preliminary_job.target == 'message'
                )
                draft_event_payloads = (
                    []
                    if discussion_job
                    else await MindmapAiDao.list_draft_event_payloads(db, job_id)
                )
                if draft_event_payloads:
                    checkpoint = await MindmapAiDao.get_draft_checkpoint(db, job_id)
                    recovered_preview = cls._draft_checkpoint_preview(checkpoint)
            if not discussion_job:
                persisted_version, persisted_epoch = cls._draft_preview_history_checkpoint(
                    draft_event_payloads
                )
                if recovered_preview is not None:
                    persisted_version = max(
                        persisted_version if persisted_version is not None else -1,
                        int(recovered_preview['operationCursor']),
                    )
                    persisted_epoch = max(
                        persisted_epoch if persisted_epoch is not None else 0,
                        int(recovered_preview['previewEpoch']),
                    )
                await cls._begin_draft_preview_run(
                    job_id,
                    persisted_version=persisted_version,
                    persisted_epoch=persisted_epoch,
                    execution_epoch=_CURRENT_JOB_EXECUTION_EPOCH.get(),
                )
            async with AsyncSessionLocal() as db:
                job = await MindmapAiDao.get_job(db, job_id)
                if job is None or job.status == 'cancel_requested':
                    return
                agent_key = job.agent_key
                sdk_version = job.sdk_version or 'unknown'
                runtime_version = job.runtime_version or 'unknown'
                model_ref = job.model_ref or 'unknown'
                max_budget_usd = float(
                    getattr(job, 'max_budget_usd', MindmapAiConfig.mindmap_ai_max_budget_usd)
                )
                timeout_seconds = int(
                    getattr(job, 'timeout_seconds', MindmapAiConfig.mindmap_ai_job_timeout_seconds)
                )
                request_model = MindmapAiJobCreateModel.model_validate(_json_loads(job.request_json, {}))
                if request_model.execution_mode == 'direct':
                    # A worker restart loses the process-local fast path. Seed
                    # the next CAS revision from durable direct-commit event
                    # metadata before the recovered adapter emits another
                    # batch; mutation ids remain globally monotonic below.
                    durable_revision = int(job.base_revision or 1)
                    for payload_json in draft_event_payloads:
                        payload = _json_loads(payload_json, {})
                        commit = payload.get('directCommit') if isinstance(payload, dict) else None
                        revision = commit.get('contentRevision') if isinstance(commit, dict) else None
                        if isinstance(revision, int) and not isinstance(revision, bool):
                            durable_revision = max(durable_revision, revision)
                    cls._direct_commit_revisions[str(job_id)] = max(
                        durable_revision,
                        cls._direct_commit_revisions.get(str(job_id), durable_revision),
                    )
                adapter = get_mindmap_agent_registry().get(job.agent_key)
                manifest = adapter.get_manifest()
                max_nodes = int(getattr(job, 'max_nodes', manifest.max_nodes))
                max_depth = int(getattr(job, 'max_depth', manifest.max_depth))
                retention_days = int(
                    getattr(job, 'retention_days', MindmapAiConfig.mindmap_ai_artifact_retention_days)
                )
                if manifest.status != 'enabled':
                    raise MindmapArtifactError(
                        manifest.status_reason or 'Agent 当前不可用',
                        code='AI_AGENT_UNAVAILABLE',
                    )
                try:
                    connector = await MindmapAiService._ensure_connector_available(
                        db,
                        manifest,
                        job.user_id,
                    )
                except ServiceException as exc:
                    raise MindmapArtifactError(
                        exc.message or '选择的 AI Agent 当前不可用',
                        code='AI_AGENT_UNAVAILABLE',
                    ) from exc
                credential_env = resolve_connector_credential(job.agent_key, connector)
                original_source_document = request_model.source.document
                diff_base_document = (
                    request_model.source.baseline_document or original_source_document
                )
                source_document = await cls._resolve_run_source_document(
                    db, job, request_model, recovered_preview,
                    has_draft_history=bool(draft_event_payloads),
                )
                tag_catalog = (
                    [] if discussion_job else await load_ai_tag_catalog(
                        db, int(job.user_id), mindmap_id=cls._tag_catalog_target_mindmap_id(request_model),
                    )
                )
                external_session_id = None
                if job.parent_job_id:
                    parent_job = await MindmapAiDao.get_job(db, job.parent_job_id, job.user_id)
                    # Provider SDK sessions are scoped to one result contract.  A
                    # platform conversation may switch between editing and
                    # discussion, but an artifact-producing provider turn must
                    # never be resumed as a message turn (or vice versa).
                    if cls._same_provider_session_contract(parent_job, job):
                        external_session_id = cls._resolve_parent_external_session_id(
                            parent_job,
                            agent_key=job.agent_key,
                            supports_sessions=manifest.supports_sessions,
                        )
                parent_external_session_id = external_session_id
                visible_history = (
                    await cls._visible_discussion_history(db, job)
                    if discussion_job and external_session_id is None
                    else ()
                )
                model = None
                if job.agent_key == 'native_mindmap':
                    model = await cls._resolve_native_model(db, job.user_id, request_model.model_id)

            try:
                tool_options = {
                    'scope': request_model.source.scope.model_dump(by_alias=True, exclude_none=True)
                    if source_document else None,
                    'trusted_source': bool(source_document),
                    'intent': request_model.intent,
                    'ai_job_id': job_id,
                    'max_nodes': max_nodes,
                    'max_depth': max_depth,
                }
                tool_service = MindmapToolService(
                    base_document=source_document or None, tag_catalog=tag_catalog, **tool_options,
                )
                source_projection = tool_service.read_projection() if source_document else None
                source_scope_summary = (
                    tool_service.authorized_scope_summary() if source_document else None
                )
                budget_source_summary = source_scope_summary
                if (
                    recovered_preview is not None
                    and diff_base_document is not None
                ):
                    baseline_tool_service = MindmapToolService(
                        base_document=diff_base_document, **tool_options,
                    )
                    budget_source_summary = (
                        baseline_tool_service.authorized_scope_summary()
                    )
            except MindmapArtifactError as exc:
                if exc.code == 'AI_OUTPUT_INVALID':
                    raise MindmapArtifactError(
                        'AI 任务输入快照无法恢复',
                        code='AI_AGENT_UNAVAILABLE',
                    ) from exc
                raise
            if source_projection is not None and not discussion_job:
                preview_coordinates = cls._draft_preview_coordinates(job_id, 0)
                preview_version, preview_epoch = preview_coordinates or (0, 1)
                await cls._emit(job_id, 'draft_initialized', {
                    'previewVersion': preview_version,
                    'previewEpoch': preview_epoch,
                    'previewState': source_projection,
                    'summary': source_scope_summary or {},
                })
                if recovered_preview is not None:
                    await cls._emit(job_id, 'generation_restarted', {
                        'status': 'preparing',
                        'progress': 10,
                        'previewAvailable': True,
                        'previewVersion': preview_version,
                        'previewEpoch': preview_epoch,
                        'sessionMode': 'provider_turn_restarted',
                    })
            context = AgentRunContext(
                job_id=job_id,
                user_id=job.user_id,
                intent=job.intent,
                prompt=request_model.prompt,
                parameters=request_model.parameters.model_dump(by_alias=True),
                source_document=source_projection,
                tool_service=tool_service,
                execution_mode=request_model.execution_mode,
                model_id=request_model.model_id,
                external_session_id=external_session_id,
                metadata=cls._agent_context_metadata(
                    model=model,
                    model_ref=job.model_ref,
                    max_budget_usd=max_budget_usd,
                    timeout_seconds=timeout_seconds,
                    retention_days=retention_days,
                    credential_env=credential_env,
                ),
                visible_history=visible_history,
            )
            if not await cls._set_status(job_id, 'running', 25):
                raise asyncio.CancelledError
            try:
                runner = adapter.resume if external_session_id else adapter.start

                async def discard_adapter_result(discarded_result: Any) -> None:
                    owned_session_id = cls._owned_external_session_id(
                        discarded_result,
                        parent_external_session_id,
                    )
                    if owned_session_id is not None:
                        await cls._purge_uncommitted_external_session(
                            adapter,
                            owned_session_id,
                            job_id,
                        )

                result = await cls._await_adapter_result(
                    job_id,
                    run_adapter_with_transient_retries(
                        runner,
                        context,
                        lambda event, payload: cls._emit(job_id, event, payload),
                    ),
                    timeout_seconds,
                    discard_result=discard_adapter_result,
                )
            except (asyncio.CancelledError, TimeoutError, MindmapArtifactError):
                raise
            except Exception as exc:
                raise map_adapter_exception(exc) from exc
            pending_external_session_id = cls._owned_external_session_id(
                result,
                parent_external_session_id,
            )
            if isinstance(result, AgentNeedsInputResult):
                if discussion_job:
                    raise MindmapArtifactError(
                        '讨论模式必须返回文字答复',
                        code='AI_OUTPUT_INVALID',
                    )
                usage = adapter.collect_usage(result)
                encrypted_session_ref = (
                    CryptoUtil.encrypt(result.external_session_id)
                    if result.external_session_id
                    else None
                )
                attempted_encrypted_session_ref = encrypted_session_ref
                now = datetime.now()
                expires = now + timedelta(days=retention_days)
                async with AsyncSessionLocal() as db:
                    current_job = await MindmapAiDao.get_job(db, job_id, for_update=True)
                    expected_execution_epoch = _CURRENT_JOB_EXECUTION_EPOCH.get()
                    if (
                        current_job is None
                        or current_job.status != 'running'
                        or (
                            expected_execution_epoch is not None
                            and int(getattr(current_job, 'execution_epoch', -1))
                            != expected_execution_epoch
                        )
                        or not await cls._owns_current_job_lease(job_id)
                    ):
                        await db.rollback()
                        raise asyncio.CancelledError
                    current_session = await MindmapAiDao.get_session(
                        db,
                        current_job.session_id,
                        for_update=True,
                    )
                    if not _session_accepts_work(current_session):
                        await db.rollback()
                        raise asyncio.CancelledError
                    await MindmapAiDao.update_job(db, job_id, {
                        'status': 'needs_input',
                        'progress': 100,
                        'usage_json': _json_dumps(usage),
                        'external_session_ref': encrypted_session_ref,
                        'completed_time': now,
                    })
                    await MindmapAiDao.update_session(db, current_job.session_id, {
                        'current_agent_key': current_job.agent_key,
                        'expires_time': max(current_session.expires_time, expires),
                    })
                    await MindmapAiDao.add_event(
                        db,
                        job_id,
                        'needs_input',
                        _event_json({
                            'status': 'needs_input',
                            'progress': 100,
                            'questions': result.questions_payload(),
                        }),
                    )
                    await MindmapAiDao.delete_draft_checkpoint(db, job_id)
                    try:
                        await db.commit()
                    except BaseException:
                        completion_commit_uncertain = True
                        raise
                    external_session_committed = True
                await cls.mark_draft_terminal(job_id, int(expected_execution_epoch or 0))
                record_run('needs_input', usage)
                record_mindmap_ai_event('needs_input')
                return
            if request_model.execution_mode == 'direct':
                if not isinstance(result, AgentDirectResult):
                    raise MindmapArtifactError(
                        '直接写入 Agent 未返回 direct_completed 终态',
                        code='AI_OUTPUT_INVALID',
                    )
                # Direct mode has already committed every accepted draft delta
                # through _emit -> MindmapAiMutationGateway. The terminal turn
                # only closes the durable task and records the latest revision;
                # it must not create a second Artifact/Proposal apply path.
                # Keep the same validating fence used by the artifact path so
                # completion cannot race a cancellation or a lease takeover.
                if not await cls._set_status(job_id, 'validating', 85):
                    raise asyncio.CancelledError
                usage = adapter.collect_usage(result)
                self_summary = getattr(result, 'summary', {}) or {}
                self_title = str(getattr(result, 'title', '') or '')[:200] or 'AI 直写任务'
                self_revision = int(job.base_revision or 1)
                if job.source_mindmap_id:
                    async with AsyncSessionLocal() as db:
                        latest_detail = await MindmapAiMutationGateway.read_document(
                            db, int(job.source_mindmap_id), int(job.user_id),
                        )
                        self_revision = int(latest_detail.content_revision or self_revision)
                cls._enforce_usage_policy(usage, max_budget_usd=max_budget_usd)
                now = datetime.now()
                expires = now + timedelta(days=retention_days)
                encrypted_session_ref = (
                    CryptoUtil.encrypt(result.external_session_id)
                    if getattr(result, 'external_session_id', None)
                    else None
                )
                attempted_encrypted_session_ref = encrypted_session_ref
                async with AsyncSessionLocal() as db:
                    _current_job, current_session = await cls._lock_completion_target(db, job_id)
                    direct_undo_id = getattr(_current_job, 'proposal_id', None)
                    direct_change_result = await _direct_job_change_result(db, _current_job)
                    direct_change_summary = direct_change_result['changeSummary']
                    self_summary = {
                        **(self_summary if isinstance(self_summary, dict) else {}),
                        'changeSummary': direct_change_summary,
                    }
                    await MindmapAiDao.update_job(db, job_id, {
                        'status': 'completed_direct',
                        'progress': 100,
                        'title': self_title,
                        'artifact_id': None,
                        'proposal_id': direct_undo_id,
                        'usage_json': _json_dumps(usage),
                        'external_session_ref': encrypted_session_ref,
                        'completed_time': now,
                    })
                    await MindmapAiDao.update_session(db, job.session_id, {
                        'current_agent_key': job.agent_key,
                        'status': 'active',
                        'expires_time': max(current_session.expires_time, expires),
                    })
                    await MindmapAiDao.add_event(
                        db,
                        job_id,
                        'direct_completed',
                        _event_json({
                            'status': 'completed_direct',
                            'progress': 100,
                            'contentRevision': self_revision,
                            'summary': self_summary,
                            'changeSummary': direct_change_summary,
                            'changeSummaryVersion': direct_change_result['changeSummaryVersion'],
                            'proposalId': direct_undo_id,
                        }),
                    )
                    await MindmapAiDao.delete_draft_checkpoint(db, job_id)
                    try:
                        await db.commit()
                    except BaseException:
                        completion_commit_uncertain = True
                        raise
                    external_session_committed = True
                await cls.mark_draft_terminal(
                    job_id,
                    int(_CURRENT_JOB_EXECUTION_EPOCH.get() or 0),
                )
                record_run('success', usage)
                record_mindmap_ai_event('direct_completed')
                return
            if discussion_job:
                if not isinstance(result, AgentMessageResult):
                    raise MindmapArtifactError(
                        '讨论模式 Agent 返回了脑图结果',
                        code='AI_OUTPUT_INVALID',
                    )
                response_title, response_content, response_content_type = (
                    normalize_agent_message({
                        'completionState': 'message_completed',
                        'title': result.title,
                        'content': result.content,
                        'contentType': result.content_type,
                    })
                )
                usage = adapter.collect_usage(result)
                cls._enforce_usage_policy(usage, max_budget_usd=max_budget_usd)
                encrypted_session_ref = (
                    CryptoUtil.encrypt(result.external_session_id)
                    if result.external_session_id
                    else None
                )
                attempted_encrypted_session_ref = encrypted_session_ref
                now = datetime.now()
                expires = now + timedelta(days=retention_days)
                response_id = str(uuid.uuid4())
                content_bytes = response_content.encode('utf-8')
                async with AsyncSessionLocal() as db:
                    current_job = await MindmapAiDao.get_job(db, job_id, for_update=True)
                    expected_execution_epoch = _CURRENT_JOB_EXECUTION_EPOCH.get()
                    if (
                        current_job is None
                        or current_job.status != 'running'
                        or (
                            expected_execution_epoch is not None
                            and int(getattr(current_job, 'execution_epoch', -1))
                            != expected_execution_epoch
                        )
                        or not await cls._owns_current_job_lease(job_id)
                    ):
                        await db.rollback()
                        raise asyncio.CancelledError
                    current_session = await MindmapAiDao.get_session(
                        db,
                        current_job.session_id,
                        for_update=True,
                    )
                    if not _session_accepts_work(current_session):
                        await db.rollback()
                        raise asyncio.CancelledError
                    await MindmapAiDao.add_response(db, {
                        'id': response_id,
                        'job_id': job_id,
                        'user_id': current_job.user_id,
                        'content_type': response_content_type,
                        'content_text': response_content,
                        'content_hash': hashlib.sha256(content_bytes).hexdigest(),
                        'byte_size': len(content_bytes),
                        'created_time': now,
                        'expires_time': expires,
                    })
                    await MindmapAiDao.update_job(db, job_id, {
                        'status': 'completed_message',
                        'progress': 100,
                        'title': response_title,
                        'artifact_id': None,
                        'proposal_id': None,
                        'response_id': response_id,
                        'usage_json': _json_dumps(usage),
                        'external_session_ref': encrypted_session_ref,
                        'completed_time': now,
                    })
                    await MindmapAiDao.update_session(db, current_job.session_id, {
                        'current_agent_key': current_job.agent_key,
                        # Let the first structured answer refine the deterministic
                        # prompt title, then keep the conversation name stable.
                        'title': (
                            response_title
                            if response_title and int(current_job.turn_index or 1) == 1
                            else current_session.title
                        ),
                        'status': 'active',
                        'expires_time': max(current_session.expires_time, expires),
                    })
                    await MindmapAiDao.add_event(
                        db,
                        job_id,
                        'message_ready',
                        _event_json({'responseId': response_id}),
                    )
                    await MindmapAiDao.delete_draft_checkpoint(db, job_id)
                    try:
                        await db.commit()
                    except BaseException:
                        completion_commit_uncertain = True
                        raise
                    external_session_committed = True
                await cls.mark_draft_terminal(job_id, int(expected_execution_epoch or 0))
                record_run('success', usage)
                record_mindmap_ai_event('message_ready')
                return
            if isinstance(result, AgentMessageResult):
                raise MindmapArtifactError(
                    '脑图任务 Agent 返回了文字结果',
                    code='AI_OUTPUT_INVALID',
                )
            if not await cls._set_status(job_id, 'validating', 85):
                raise asyncio.CancelledError
            artifact, summary = _validate_job_result_artifact(
                result.artifact,
                max_node_count=AI_MAX_NODE_COUNT,
                expected_artifact_id=job_id,
                expected_agent_key=job.agent_key,
                expected_adapter_version=getattr(job, 'adapter_version', None),
            )
            usage = adapter.collect_usage(result)
            scoped_summary = context.tool_service.authorized_scope_summary()
            cumulative_budget_operations = (
                build_document_diff(diff_base_document, artifact['document'])[0]
                if diff_base_document is not None
                else result.operations
            )
            created_count = sum(
                1 for operation in cumulative_budget_operations
                if operation.get('type') == 'create_node'
            )
            cls._enforce_result_policy(
                summary,
                usage,
                max_nodes=max_nodes,
                max_depth=max_depth,
                max_budget_usd=max_budget_usd,
                source_summary=budget_source_summary,
                scoped_summary=scoped_summary,
                created_count=created_count,
            )
            validation_status = artifact['manifest']['validation']['status']
            if diff_base_document is not None:
                proposal_operations, impact = build_document_diff(
                    diff_base_document,
                    artifact['document'],
                )
            else:
                proposal_operations = result.operations
                impact = {
                    'beforeNodeCount': 0,
                    'afterNodeCount': summary['nodeCount'],
                    'createdCount': summary['nodeCount'],
                    'updatedCount': 0,
                    'movedCount': 0,
                    'deletedCount': 0,
                    'deletedSubtrees': [],
                    'metadataChanges': [],
                    'operationCount': len(result.operations),
                    'highImpact': False,
                    'highImpactReasons': [],
                    'changes': [],
                }
            # A structurally valid result may still have a broad or destructive
            # diff. Keep it visible in the live canvas, but require an explicit
            # review before it can be applied. Draft validation remains a
            # separate, stricter reason for the existing needs_review state.
            needs_review = (
                validation_status == 'draft'
                or bool(impact.get('highImpact'))
            )
            no_change = source_document is not None and not proposal_operations
            now = datetime.now()
            expires = now + timedelta(days=retention_days)
            artifact_id = str(artifact['manifest']['artifactId'])
            proposal_id = (
                str(uuid.uuid4())
                if request_model.target == 'proposal' and not no_change
                else None
            )
            document_hash = str(artifact['manifest']['documentHash'])
            async with AsyncSessionLocal() as db:
                _current_job, current_session = await cls._lock_completion_target(db, job_id)
                await MindmapAiDao.add_artifact(db, {
                    'id': artifact_id,
                    'job_id': job_id,
                    'user_id': job.user_id,
                    'title': result.title,
                    'content_json': _json_dumps(artifact),
                    'document_hash': document_hash,
                    'validation_status': validation_status,
                    'validator_version': 'mindmap-validator-2',
                    'node_count': summary['nodeCount'],
                    'tree_depth': summary['treeDepth'],
                    'byte_size': len(canonical_json_bytes(artifact)),
                    'created_time': now,
                    'expires_time': expires,
                })
                if proposal_id is not None:
                    local_proposal = (
                        job.source_type == 'local_snapshot'
                        and job.source_mindmap_id is None
                    )
                    cloud_proposal = (
                        job.source_type == 'cloud_document'
                        and job.source_mindmap_id is not None
                    )
                    if not local_proposal and not cloud_proposal:
                        raise MindmapArtifactError(
                            '提案来源通道无效',
                            code='AI_PROPOSAL_SOURCE_INVALID',
                        )
                    await MindmapAiDao.add_proposal(db, {
                        'id': proposal_id,
                        'job_id': job_id,
                        'user_id': job.user_id,
                        'proposal_type': 'patch' if proposal_operations else 'full_document',
                        'base_document_id': (
                            request_model.source.document_id
                            if local_proposal
                            else None
                        ),
                        'target_mindmap_id': (
                            job.source_mindmap_id
                            if cloud_proposal
                            else None
                        ),
                        'base_revision': job.base_revision,
                        'base_hash': job.base_hash,
                        'base_room_epoch': job.base_room_epoch,
                        'scope_json': _json_dumps(request_model.source.scope.model_dump(by_alias=True)),
                        'operations_json': _json_dumps(proposal_operations),
                        'result_artifact_id': artifact_id,
                        'result_hash': document_hash,
                        'impact_json': _json_dumps(impact),
                        'warnings_json': _json_dumps([]),
                        'status': 'needs_review' if needs_review else 'ready',
                        'created_time': now,
                        'expires_time': expires,
                    })
                encrypted_session_ref = (
                    CryptoUtil.encrypt(result.external_session_id)
                    if result.external_session_id
                    else None
                )
                attempted_encrypted_session_ref = encrypted_session_ref
                await MindmapAiDao.update_job(db, job_id, {
                    'status': (
                        'needs_review'
                        if needs_review
                        else 'completed_no_change' if no_change else 'ready'
                    ),
                    'progress': 100,
                    'title': result.title,
                    'artifact_id': artifact_id,
                    'proposal_id': proposal_id,
                    'usage_json': _json_dumps(usage),
                    'external_session_ref': encrypted_session_ref,
                    'completed_time': now,
                })
                session_expires = max(
                    current_session.expires_time,
                    expires,
                )
                await MindmapAiDao.update_session(db, job.session_id, {
                    'current_agent_key': job.agent_key,
                    'title': result.title,
                    'latest_artifact_id': artifact_id,
                    'status': 'active',
                    'expires_time': session_expires,
                })
                await MindmapAiDao.add_event(
                    db,
                    job_id,
                    (
                        'artifact_needs_review'
                        if needs_review
                        else 'artifact_no_change' if no_change else 'artifact_ready'
                    ),
                    _event_json({
                        'status': (
                            'needs_review'
                            if needs_review
                            else 'completed_no_change' if no_change else 'ready'
                        ),
                        'progress': 100,
                        'artifactId': artifact_id,
                        'proposalId': proposal_id,
                        'summary': summary,
                        'issueCount': 0,
                    }),
                )
                # The immutable artifact supersedes the transient draft. Keep
                # deletion in the exact same transaction as the final result.
                await MindmapAiDao.delete_draft_checkpoint(db, job_id)
                try:
                    await db.commit()
                except BaseException:
                    completion_commit_uncertain = True
                    raise
                external_session_committed = True
            await cls.mark_draft_terminal(
                job_id,
                int(_CURRENT_JOB_EXECUTION_EPOCH.get() or 0),
            )
            record_run('success', usage)
            record_mindmap_ai_event('artifact_ready')
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if (
                current_task in cls._lease_lost_tasks
                or not await cls._owns_current_job_lease(job_id)
            ):
                record_run('lease_lost')
                return
            if cls._shutting_down:
                await cls._set_status(job_id, 'queued', 0)
                return
            await cls._set_status(
                job_id,
                'cancelled',
                100,
                error_code='AI_TASK_CANCELLED',
                error_message='任务已取消',
                completed_time=datetime.now(),
            )
            record_run('cancelled')
        except TimeoutError:
            await cls._fail(job_id, 'AI_TIMEOUT', 'AI 脑图任务执行超时')
            record_run('timeout')
        except MindmapArtifactError as exc:
            # 单次运行失败不能修改全局 Connector 健康状态。Native 模型可以按
            # user_id 配置，Codex/Claude 也可能遇到模型级权限、短时网络或限流；
            # 将这些错误持久化为全局 unhealthy 会让一个用户阻断所有用户。
            # Connector 健康状态只由管理员显式 health-check 更新。
            if exc.code == 'AI_DOCUMENT_CONFLICT':
                await cls._set_status(
                    job_id,
                    'stale',
                    100,
                    error_code=exc.code,
                    error_message=str(exc),
                    completed_time=datetime.now(),
                )
                outcome = 'conflict'
                record_mindmap_ai_event('direct_conflict')
            else:
                await cls._fail(job_id, exc.code, str(exc))
                outcome = 'invalid' if exc.code == 'AI_OUTPUT_INVALID' else 'error'
            record_run(outcome)
        except Exception:
            logger.exception(f'AI 脑图任务执行失败: job_id={job_id}')
            await cls._fail(
                job_id,
                'AI_AGENT_UNAVAILABLE',
                'AI 脑图服务暂不可用，请稍后重试或切换 Agent',
            )
            record_run('error')
        finally:
            should_purge_external_session = (
                pending_external_session_id is not None
                and not external_session_committed
                and adapter is not None
            )
            if (
                should_purge_external_session
                and completion_commit_uncertain
                and attempted_encrypted_session_ref is not None
            ):
                reconciliation = await cls._reconcile_external_session_commit(
                    job_id,
                    attempted_encrypted_session_ref,
                )
                if reconciliation is True:
                    external_session_committed = True
                    should_purge_external_session = False
                elif reconciliation is None:
                    should_purge_external_session = False
            if should_purge_external_session:
                await cls._purge_uncommitted_external_session(
                    adapter,
                    pending_external_session_id,
                    job_id,
                )
            await cls._wake_waiting_followups(job_id)

    @classmethod
    async def _fail(cls, job_id: str, error_code: str, message: str) -> None:
        await cls._set_status(
            job_id,
            'failed',
            100,
            error_code=error_code,
            error_message=message[:500],
            completed_time=datetime.now(),
        )

    @classmethod
    async def cancel(cls, job_id: str, agent_key: str) -> bool:
        task = cls._tasks.get(job_id)
        task_cancelled = task is not None and not task.done()
        if task_cancelled:
            task.cancel()
        adapter_cancelled = False
        try:
            adapter = get_mindmap_agent_registry().get(agent_key)
            adapter_cancel_task = asyncio.create_task(
                adapter.cancel(job_id),
                name=f'mindmap-ai-adapter-cancel:{job_id}',
            )
            grace = float(MindmapAiConfig.mindmap_ai_adapter_cancel_grace_seconds)
            done, _pending = await asyncio.wait({adapter_cancel_task}, timeout=grace)
            if adapter_cancel_task in done:
                adapter_cancelled = bool(adapter_cancel_task.result())
            else:
                logger.warning(
                    f'取消 AI 脑图 Adapter 超时，开始有界终止: job_id={job_id}'
                )
                await cls._cancel_adapter_task(
                    adapter_cancel_task,
                    job_id,
                    grace_seconds=grace,
                )
        except Exception:
            logger.warning(
                f'取消 AI 脑图 Adapter 失败，任务结果仍将由持久化状态拒绝: job_id={job_id}'
            )
        return task_cancelled or adapter_cancelled


def _collect_adapter_session_references(
    records: list[Any],
    *,
    strict: bool,
) -> list[tuple[str, str]]:
    """Decrypt and deduplicate provider session references without exposing them in logs."""
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if isinstance(record, dict):
            agent_key = record.get('agentKey') or record.get('agent_key')
            encrypted_ref = (
                record.get('externalSessionRef') or record.get('external_session_ref')
            )
        else:
            agent_key = getattr(record, 'agent_key', None)
            encrypted_ref = getattr(record, 'external_session_ref', None)
        if not agent_key or not encrypted_ref:
            continue
        try:
            external_session_id = CryptoUtil.decrypt(str(encrypted_ref))
        except Exception as exc:
            if strict:
                raise ServiceException(message='AI SDK 会话引用无效，暂未删除会话') from exc
            logger.warning(
                f'跳过无法解密的 AI SDK 会话引用: agent_key={str(agent_key)[:64]}'
            )
            continue
        reference = (str(agent_key), external_session_id)
        if not external_session_id or reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
    return references


def _exclude_still_referenced_adapter_sessions(
    candidates: list[tuple[str, str]],
    surviving_records: list[Any],
) -> list[tuple[str, str]]:
    """Never purge a provider session still referenced by another job.

    Session-capable adapters may legally return the same external ID when a
    child reuses its parent context. A candidate becomes purgeable only after
    the final database reference for that agent/external-ID pair expires.
    """
    protected: set[tuple[str, str]] = set()
    uncertain_agents: set[str] = set()
    for record in surviving_records:
        if isinstance(record, dict):
            agent_key = record.get('agentKey') or record.get('agent_key')
            encrypted_refs = (
                record.get('externalSessionRef') or record.get('external_session_ref'),
                record.get('parentExternalSessionRef')
                or record.get('parent_external_session_ref'),
            )
        else:
            agent_key = getattr(record, 'agent_key', None)
            encrypted_refs = (
                getattr(record, 'external_session_ref', None),
                getattr(record, 'parent_external_session_ref', None),
            )
        if not agent_key:
            continue
        normalized_agent_key = str(agent_key)
        for encrypted_ref in encrypted_refs:
            if not encrypted_ref:
                continue
            try:
                external_session_id = CryptoUtil.decrypt(str(encrypted_ref))
            except Exception:
                # A corrupt/temporarily undecipherable surviving reference makes
                # ownership uncertain. Retain every candidate for that agent.
                uncertain_agents.add(normalized_agent_key)
                logger.warning(
                    '无法校验存活的 AI SDK 会话引用，已保守保留: '
                    f'agent_key={normalized_agent_key[:64]}'
                )
                continue
            if external_session_id:
                protected.add((normalized_agent_key, external_session_id))
    return [
        reference
        for reference in candidates
        if reference not in protected and reference[0] not in uncertain_agents
    ]


async def _purge_adapter_session_references(
    references: list[tuple[str, str]],
    *,
    strict: bool,
) -> tuple[int, int]:
    """Purge exact provider sessions; explicit user deletion is fail-closed."""
    registry = get_mindmap_agent_registry()
    purged = 0
    failures = 0
    for agent_key, external_session_id in references:
        try:
            adapter = registry.get(agent_key)
            removed = await adapter.purge_session(external_session_id)
            purged += int(bool(removed))
        except Exception as exc:  # noqa: PERF203
            failures += 1
            if strict:
                raise ServiceException(message='AI SDK 会话清理失败，请重试') from exc
            logger.warning(
                f'AI SDK 会话清理失败，将由到期清理重试: agent_key={agent_key[:64]}'
            )
    return purged, failures


async def _cleanup_expired_adapter_sessions() -> tuple[int, int]:
    """Run every session-capable adapter's orphan/expiry cleanup independently of new jobs."""
    registry = get_mindmap_agent_registry()
    removed = 0
    failures = 0
    for manifest in registry.manifests():
        if not manifest.supports_sessions:
            continue
        try:
            removed += max(0, int(await registry.get(manifest.agent_key).cleanup_expired_sessions()))
        except Exception:
            failures += 1
            logger.warning(
                'AI SDK 到期会话清理失败，将在下一周期重试: '
                f'agent_key={manifest.agent_key[:64]}'
            )
    return removed, failures


class MindmapAiRetentionManager:
    """按小批次清理到期正文；已应用结果只保留不可逆审计元数据。"""

    _task: asyncio.Task[None] | None = None
    _stop_event: asyncio.Event | None = None

    @classmethod
    async def cleanup_once(cls) -> dict[str, int]:
        now = datetime.now()
        batch_size = int(MindmapAiConfig.mindmap_ai_cleanup_batch_size)
        job_ids: list[str] = []
        async with AsyncSessionLocal() as db:
            try:
                rows = await MindmapAiDao.list_expired_job_metadata(
                    db,
                    now,
                    RETENTION_ELIGIBLE_JOB_STATUSES,
                    batch_size,
                )
                adapter_session_references = _collect_adapter_session_references(
                    rows,
                    strict=False,
                )
                retained_ids = [
                    row['id'] for row in rows if row['status'] in RETAINED_AUDIT_JOB_STATUSES
                ]
                deleted_ids = [
                    row['id'] for row in rows if row['status'] not in RETAINED_AUDIT_JOB_STATUSES
                ]
                job_ids = retained_ids + deleted_ids
                session_ids = list(dict.fromkeys(row['sessionId'] for row in rows))
                surviving_session_records = (
                    await MindmapAiDao.list_other_external_session_references(
                        db,
                        {agent_key for agent_key, _external_id in adapter_session_references},
                        job_ids,
                    )
                )
                adapter_session_references = _exclude_still_referenced_adapter_sessions(
                    adapter_session_references,
                    surviving_session_records,
                )

                retained_payloads = await MindmapAiDao.delete_events_and_undos_for_jobs(
                    db,
                    retained_ids,
                )
                scrubbed_jobs = await MindmapAiDao.scrub_expired_jobs(
                    db,
                    retained_ids,
                    now + timedelta(days=int(MindmapAiConfig.mindmap_ai_audit_retention_days)),
                )
                deleted_payloads = await MindmapAiDao.delete_job_payloads(db, deleted_ids)
                expired_undos = await MindmapAiDao.delete_expired_undos(db, now, batch_size)
                sessions = await MindmapAiDao.cleanup_sessions(db, session_ids, now)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        execution_epochs = {
            str(row['id']): int(row.get('executionEpoch') or 0)
            for row in rows
        }
        for job_id in job_ids:
            await MindmapAiTaskManager.mark_draft_terminal(
                job_id,
                execution_epochs[job_id],
            )
        purged_sdk_sessions, purge_failures = await _purge_adapter_session_references(
            adapter_session_references,
            strict=False,
        )
        expired_sdk_sessions, cleanup_failures = await _cleanup_expired_adapter_sessions()
        return {
            'scrubbedJobs': scrubbed_jobs,
            'deletedJobs': deleted_payloads['jobs'],
            'deletedArtifacts': deleted_payloads['artifacts'],
            'deletedProposals': deleted_payloads['proposals'],
            'deletedResponses': deleted_payloads.get('responses', 0),
            'deletedEvents': retained_payloads['events'] + deleted_payloads['events'],
            'deletedUndos': (
                retained_payloads['undos'] + deleted_payloads['undos'] + expired_undos
            ),
            'deletedSessions': sessions['deleted'],
            'scrubbedSessions': sessions['scrubbed'],
            'purgedSdkSessions': purged_sdk_sessions,
            'expiredSdkSessions': expired_sdk_sessions,
            'sdkSessionCleanupFailures': purge_failures + cleanup_failures,
        }

    @classmethod
    async def _run(cls) -> None:
        assert cls._stop_event is not None
        interval = int(MindmapAiConfig.mindmap_ai_cleanup_interval_seconds)
        while not cls._stop_event.is_set():
            try:
                result = await cls.cleanup_once()
                if any(result.values()):
                    logger.info(f'AI 脑图到期数据清理完成: {result}')
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('AI 脑图到期数据清理失败，将在下一周期重试')
            try:
                await asyncio.wait_for(cls._stop_event.wait(), timeout=interval)
            except (asyncio.TimeoutError, TimeoutError):
                continue

    @classmethod
    def start(cls) -> None:
        if cls._task is not None and not cls._task.done():
            return
        cls._stop_event = asyncio.Event()
        cls._task = asyncio.create_task(cls._run(), name='mindmap-ai-retention')

    @classmethod
    async def stop(cls) -> None:
        task = cls._task
        if task is None:
            return
        if cls._stop_event is not None:
            cls._stop_event.set()
        try:
            # 先让 _run 通过 stop event 正常退出。直接 cancel 一个正处于
            # asyncio.wait_for 超时边界的任务，可能把内部 TimeoutError 透出
            # 到 FastAPI lifespan，导致整个应用被标记为“关闭失败”。
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=RETENTION_SHUTDOWN_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, TimeoutError):
            if not task.done():
                logger.warning('AI 脑图到期清理任务未及时退出，已强制取消')
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, asyncio.TimeoutError, TimeoutError):
                pass
            except Exception:
                logger.exception('AI 脑图到期清理任务关闭异常')
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception('AI 脑图到期清理任务关闭异常')
        finally:
            cls._task = None
            cls._stop_event = None


class MindmapAiService:
    @staticmethod
    def _schedule_replayed_job(job: Any) -> None:
        """幂等重放也要唤醒已提交但尚未被本进程调度的 queued 任务。"""
        if getattr(job, 'status', None) == 'queued':
            MindmapAiTaskManager.schedule(str(job.id))

    @staticmethod
    def _applied_result_expiration(now: datetime) -> datetime:
        return now + timedelta(days=int(MindmapAiConfig.mindmap_ai_applied_retention_days))

    @classmethod
    async def _ensure_connector_available(
        cls,
        db: AsyncSession,
        manifest: Any,
        user_id: int,
        *,
        for_update: bool = False,
        preflight_unknown: bool = True,
    ) -> Any:
        if manifest.status != 'enabled':
            raise ServiceException(message=manifest.status_reason or '选择的 AI Agent 当前不可用')
        connector = await MindmapAiDao.get_connector(
            db,
            manifest.agent_key,
            for_update=for_update,
        )
        if connector is None:
            raise ServiceException(message='选择的 AI Agent 尚未由管理员配置 Connector')
        if not bool(connector.enabled):
            raise ServiceException(message='选择的 AI Agent 已被管理员停用')
        rollout_percentage = max(0, min(int(connector.rollout_percentage), 100))
        rollout_bucket = int(hashlib.sha256(
            f'{manifest.agent_key}:{user_id}'.encode(),
        ).hexdigest()[:8], 16) % 100
        if rollout_bucket >= rollout_percentage:
            raise ServiceException(message='选择的 AI Agent 尚未向当前用户开放')
        if connector.network_policy == 'deny' and manifest.network_allowed:
            raise ServiceException(message='选择的 AI Agent 被网络策略停用')
        try:
            credential_env = resolve_connector_credential(manifest.agent_key, connector)
        except MindmapArtifactError as exc:
            raise ServiceException(message=str(exc)) from exc
        health_status, health_reason = cls._connector_health_state(connector)
        if health_status == 'unhealthy':
            raise ServiceException(
                message=health_reason or '选择的 AI Agent 健康检查未通过'
            )
        if health_status == 'unknown' and preflight_unknown:
            adapter = get_mindmap_agent_registry().get(manifest.agent_key)
            healthy, reason = await cls._probe_connector_health(
                adapter,
                credential_env,
                model_ref=cls._resolve_model_ref(manifest, None),
            )
            if not healthy:
                raise ServiceException(message=reason or '选择的 AI Agent 健康检查未通过')
            checked_at = datetime.now()
            await MindmapAiDao.update_connector(db, manifest.agent_key, {
                'health_status': 'healthy',
                'health_reason': None,
                'last_health_time': checked_at,
            })
            connector.health_status = 'healthy'
            connector.health_reason = None
            connector.last_health_time = checked_at
            # 任务创建使用行锁，健康状态随任务原子提交；后台恢复路径没有后续
            # 写事务，必须在这里持久化，避免每次恢复都重复探测供应商。
            if for_update:
                await db.flush()
            else:
                await db.commit()
        return connector

    @staticmethod
    def _connector_health_state(connector: Any) -> tuple[str, str | None]:
        """Return a freshness-aware status without mutating the persisted row."""
        status = str(getattr(connector, 'health_status', '') or 'unknown')
        reason = getattr(connector, 'health_reason', None)
        if status != 'healthy':
            return status, reason
        checked_at = getattr(connector, 'last_health_time', None)
        if not isinstance(checked_at, datetime):
            return 'unknown', '尚未完成有效的连接检查'
        now = datetime.now(checked_at.tzinfo) if checked_at.tzinfo else datetime.now()
        age_seconds = (now - checked_at).total_seconds()
        ttl_seconds = MindmapAiConfig.mindmap_ai_connector_health_ttl_seconds
        if age_seconds < 0 or age_seconds > ttl_seconds:
            return 'unknown', '最近一次连接检查已过期，将在运行前重新检查'
        return status, reason

    @staticmethod
    async def _probe_connector_health(
        adapter: Any,
        credential_env: dict[str, str],
        *,
        model_ref: str | None,
    ) -> tuple[bool, str | None]:
        """执行有总时限的 Provider 探测，并只返回当前请求可见的安全错误。"""
        try:
            return await asyncio.wait_for(
                adapter.healthcheck(credential_env, model_ref=model_ref),
                timeout=CONNECTOR_HEALTHCHECK_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            mapped = map_adapter_exception(exc)
            return False, str(mapped)

    @staticmethod
    async def _has_native_model(
        db: AsyncSession,
        user_id: int,
        model_id: int | None = None,
    ) -> bool:
        query = select(AiModels.model_id).where(
            AiModels.status == '0',
            or_(AiModels.user_id.is_(None), AiModels.user_id == user_id),
        )
        if model_id is not None:
            query = query.where(AiModels.model_id == model_id)
        return (await db.execute(query.limit(1))).scalar_one_or_none() is not None

    @staticmethod
    def _runtime_policy(connector: Any | None, manifest: Any) -> AgentRuntimePolicy:
        allowlist = _json_loads(getattr(connector, 'model_allowlist_json', None), [])
        if not isinstance(allowlist, list):
            allowlist = []
        model_allowlist = tuple(
            dict.fromkeys(str(item).strip() for item in allowlist if str(item).strip())
        )
        retention_policy = str(getattr(connector, 'retention_policy', '') or '')
        retention_days = (
            int(retention_policy[:-1])
            if retention_policy.endswith('d') and retention_policy[:-1].isdigit()
            else MindmapAiConfig.mindmap_ai_artifact_retention_days
        )
        return AgentRuntimePolicy(
            model_allowlist=model_allowlist,
            max_budget_usd=max(
                0.0001,
                min(
                    float(
                        getattr(connector, 'max_budget_usd', None)
                        or MindmapAiConfig.mindmap_ai_max_budget_usd
                    ),
                    1_000.0,
                ),
            ),
            timeout_seconds=max(
                30,
                min(
                    int(
                        getattr(connector, 'timeout_seconds', None)
                        or MindmapAiConfig.mindmap_ai_job_timeout_seconds
                    ),
                    900,
                ),
            ),
            max_nodes=min(
                max(
                    5,
                    int(
                        getattr(connector, 'max_nodes', None)
                        or getattr(manifest, 'max_nodes', 2_000)
                    ),
                ),
                int(getattr(manifest, 'max_nodes', 2_000)),
            ),
            max_depth=min(
                max(
                    2,
                    int(
                        getattr(connector, 'max_depth', None)
                        or getattr(manifest, 'max_depth', 32)
                    ),
                ),
                int(getattr(manifest, 'max_depth', 32)),
            ),
            max_concurrent_jobs=max(
                1,
                min(
                    int(
                        getattr(connector, 'max_concurrent_jobs', None)
                        or MindmapAiConfig.mindmap_ai_max_concurrent_jobs_per_agent
                    ),
                    100,
                ),
            ),
            retention_days=max(1, min(retention_days, 365)),
        )

    @staticmethod
    def _resolve_model_ref(manifest: Any, model_id: int | None) -> str | None:
        if manifest.agent_key == 'native_mindmap':
            return str(model_id) if model_id is not None else None
        return getattr(manifest, 'default_model_ref', None)

    @classmethod
    def _validate_job_policy(
        cls,
        request_model: MindmapAiJobCreateModel,
        manifest: Any,
        policy: AgentRuntimePolicy,
    ) -> str | None:
        model_ref = cls._resolve_model_ref(manifest, request_model.model_id)
        if policy.model_allowlist:
            if model_ref is None:
                raise ServiceException(message='当前 Agent 已启用模型白名单，请明确选择模型')
            if model_ref not in policy.model_allowlist:
                raise ServiceException(message='所选模型不在当前 Agent 的管理员白名单中')
        if request_model.parameters.max_nodes > policy.max_nodes:
            raise ServiceException(message=f'请求节点上限不能超过当前 Agent 策略值 {policy.max_nodes}')
        if request_model.parameters.max_depth > policy.max_depth:
            raise ServiceException(message=f'请求层级上限不能超过当前 Agent 策略值 {policy.max_depth}')
        return model_ref

    @classmethod
    async def _ensure_concurrency_available(
        cls,
        db: AsyncSession,
        agent_key: str,
        policy: AgentRuntimePolicy,
    ) -> None:
        active_jobs = await MindmapAiDao.count_active_jobs(db, agent_key)
        if active_jobs >= policy.max_concurrent_jobs:
            raise ServiceException(
                message=f'当前 Agent 已达到并发上限 {policy.max_concurrent_jobs}，请稍后重试'
            )

    @classmethod
    async def _prepare_job_runtime(
        cls,
        db: AsyncSession,
        request_model: MindmapAiJobCreateModel,
        manifest: Any,
        user_id: int,
    ) -> tuple[AgentRuntimePolicy, dict[str, Any]]:
        """Lock and validate the runtime policy, then freeze its job columns.

        Callers retain concurrency admission: waiting turns validate their
        runtime here but do not compete for an active execution slot yet.
        """
        connector = await cls._ensure_connector_available(
            db, manifest, user_id, for_update=True, preflight_unknown=True,
        )
        policy = cls._runtime_policy(connector, manifest)
        model_ref = cls._validate_job_policy(request_model, manifest, policy)
        if (
            manifest.agent_key == 'native_mindmap'
            and not await cls._has_native_model(db, user_id, request_model.model_id)
        ):
            raise ServiceException(message='自研 MindMap Agent 没有可用的模型配置')
        return policy, {
            'agent_key': manifest.agent_key,
            'adapter_version': manifest.adapter_version,
            'sdk_version': manifest.sdk_version,
            'runtime_version': manifest.runtime_version,
            'model_ref': model_ref,
            'max_budget_usd': policy.max_budget_usd,
            'timeout_seconds': policy.timeout_seconds,
            'max_nodes': request_model.parameters.max_nodes,
            'max_depth': request_model.parameters.max_depth,
            'retention_days': policy.retention_days,
            'intent': request_model.intent,
            'target': request_model.target,
            'source_type': request_model.source.type,
        }

    @classmethod
    async def list_agents(
        cls,
        db: AsyncSession,
        user_id: int,
        intent: str | None = None,
        input_type: str | None = None,
    ) -> list[dict[str, Any]]:
        agents = []
        registry = get_mindmap_agent_registry()
        manifest_filters: dict[str, Any] = {
            'intent': intent,
            'input_type': input_type,
        }
        if intent == 'discuss':
            manifest_filters['result_type'] = 'message'
        for manifest in registry.manifests(**manifest_filters):
            unavailable_reason: str | None = None
            try:
                connector = await cls._ensure_connector_available(
                    db,
                    manifest,
                    user_id,
                    preflight_unknown=False,
                )
            except ServiceException as exc:
                unavailable_reason = exc.message or '当前 AI Agent 不可用'
                connector = await MindmapAiDao.get_connector(db, manifest.agent_key)
            if (
                unavailable_reason is None
                and manifest.agent_key == 'native_mindmap'
                and not await cls._has_native_model(db, user_id)
            ):
                unavailable_reason = '自研 MindMap Agent 没有可用的模型配置'
            item = manifest.to_dict()
            item['rolloutPercentage'] = int(connector.rollout_percentage) if connector else 100
            item['dataRegion'] = (
                connector.data_region if connector and connector.data_region else manifest.data_region
            )
            item['retentionPolicy'] = connector.retention_policy if connector else None
            item['credentialConfigured'] = bool(connector and connector.credential_ref)
            health_status, health_reason = (
                cls._connector_health_state(connector)
                if connector
                else ('unknown', None)
            )
            item['healthStatus'] = health_status
            item['healthReason'] = health_reason
            item['lastHealthTime'] = connector.last_health_time if connector else None
            policy = cls._runtime_policy(connector, manifest)
            fixed_model_ref = cls._resolve_model_ref(manifest, None)
            if (
                manifest.agent_key != 'native_mindmap'
                and policy.model_allowlist
                and fixed_model_ref not in policy.model_allowlist
            ):
                unavailable_reason = unavailable_reason or '默认模型不在当前 Agent 的管理员白名单中'
            if unavailable_reason:
                item['status'] = 'disabled'
                item['statusReason'] = unavailable_reason
            item.update({
                'modelAllowlist': list(policy.model_allowlist),
                'maxBudgetUsd': policy.max_budget_usd,
                'timeoutSeconds': policy.timeout_seconds,
                'maxNodes': policy.max_nodes,
                'maxDepth': policy.max_depth,
                'maxConcurrentJobs': policy.max_concurrent_jobs,
                'retentionDays': policy.retention_days,
            })
            agents.append(item)
        return agents

    @staticmethod
    def _connector_conformance_state(
        record: Any | None,
        manifest: Any,
    ) -> tuple[str, dict[str, Any] | None]:
        """Invalidate deterministic evidence when its adapter contract changed."""
        if record is None:
            return 'unknown', None

        status = getattr(record, 'conformance_status', None) or 'unknown'
        raw_report = _json_loads(getattr(record, 'conformance_report_json', None))
        report = raw_report if isinstance(raw_report, dict) else None
        if status == 'unknown':
            return status, report

        expected_versions = {
            'adapterVersion': manifest.adapter_version,
            'sdkVersion': manifest.sdk_version,
            'runtimeVersion': manifest.runtime_version,
            'contractVersion': manifest.tool_contract_version,
            'errorContractVersion': manifest.error_contract_version,
            'smmVersions': list(manifest.smm_versions),
        }
        if report is None:
            return 'stale', {
                'stale': True,
                'staleReason': 'MISSING_OR_INVALID_REPORT',
                'expectedVersions': expected_versions,
                'releaseEligible': False,
            }

        version_mismatches = [
            key
            for key, expected in expected_versions.items()
            if report.get(key) != expected
        ]
        if not version_mismatches:
            return status, report

        stale_report = dict(report)
        stale_report.update({
            'stale': True,
            'staleReason': 'MANIFEST_VERSION_CHANGED',
            'versionMismatches': version_mismatches,
            'expectedVersions': expected_versions,
            'releaseEligible': False,
        })
        return 'stale', stale_report

    @staticmethod
    def _connector_model(record: Any | None, manifest: Any) -> MindmapAiConnectorModel:
        policy = MindmapAiService._runtime_policy(record, manifest)
        conformance_status, conformance_report = (
            MindmapAiService._connector_conformance_state(record, manifest)
        )
        return MindmapAiConnectorModel(
            agentKey=manifest.agent_key,
            displayName=manifest.display_name,
            enabled=bool(record.enabled) if record is not None else manifest.status == 'enabled',
            rolloutPercentage=int(record.rollout_percentage) if record is not None else 100,
            credentialConfigured=bool(record and record.credential_ref),
            dataRegion=(record.data_region if record and record.data_region else manifest.data_region),
            retentionPolicy=record.retention_policy if record else None,
            networkPolicy=record.network_policy if record else 'adapter_default',
            modelAllowlist=list(policy.model_allowlist),
            maxBudgetUsd=policy.max_budget_usd,
            timeoutSeconds=policy.timeout_seconds,
            maxNodes=policy.max_nodes,
            maxDepth=policy.max_depth,
            maxConcurrentJobs=policy.max_concurrent_jobs,
            retentionDays=policy.retention_days,
            healthStatus=(
                record.health_status
                if record is not None
                else ('healthy' if manifest.status == 'enabled' else 'unhealthy')
            ),
            healthReason=(record.health_reason if record else manifest.status_reason),
            conformanceStatus=conformance_status,
            conformanceReport=conformance_report,
            lastHealthTime=record.last_health_time if record else None,
            lastConformanceTime=record.last_conformance_time if record else None,
            manifest=manifest.to_dict(),
        )

    @classmethod
    async def list_connectors(cls, db: AsyncSession) -> list[MindmapAiConnectorModel]:
        records = {item.agent_key: item for item in await MindmapAiDao.list_connectors(db)}
        return [
            cls._connector_model(records.get(manifest.agent_key), manifest)
            for manifest in get_mindmap_agent_registry().manifests()
        ]

    @classmethod
    async def update_connector(
        cls,
        db: AsyncSession,
        agent_key: str,
        model: MindmapAiConnectorUpdateModel,
        user_name: str,
    ) -> MindmapAiConnectorModel:
        try:
            adapter = get_mindmap_agent_registry().get(agent_key)
        except KeyError as exc:
            raise ServiceException(message='选择的 AI Agent 不存在') from exc
        manifest = adapter.get_manifest()
        changes = model.model_dump(exclude_unset=True)
        if 'enabled' in changes:
            changes['enabled'] = int(bool(changes['enabled']))
        if changes.get('credential_ref') == '':
            changes['credential_ref'] = None
        if changes.get('retention_policy') == '':
            changes['retention_policy'] = None
        if 'model_allowlist' in changes:
            changes['model_allowlist_json'] = _json_dumps(changes.pop('model_allowlist') or [])
        for field in (
            'max_budget_usd', 'timeout_seconds', 'max_nodes', 'max_depth', 'max_concurrent_jobs',
        ):
            if changes.get(field) is None:
                changes.pop(field, None)
        record = await MindmapAiDao.get_connector(db, agent_key, for_update=True)
        now = datetime.now()
        if record is None:
            record = await MindmapAiDao.add_connector(db, {
                'agent_key': agent_key,
                'enabled': changes.pop('enabled', int(manifest.status == 'enabled')),
                'rollout_percentage': changes.pop('rollout_percentage', 100),
                'network_policy': changes.pop('network_policy', 'adapter_default'),
                'health_status': 'unknown',
                'conformance_status': 'unknown',
                'create_by': user_name,
                'created_time': now,
                'update_by': user_name,
                'update_time': now,
                **changes,
            })
        else:
            await MindmapAiDao.update_connector(db, agent_key, {**changes, 'update_by': user_name})
        await db.commit()
        refreshed = await MindmapAiDao.get_connector(db, agent_key)
        return cls._connector_model(refreshed or record, manifest)

    @classmethod
    async def health_check_connector(
        cls,
        db: AsyncSession,
        agent_key: str,
        user_name: str,
    ) -> MindmapAiConnectorModel:
        try:
            adapter = get_mindmap_agent_registry().get(agent_key)
        except KeyError as exc:
            raise ServiceException(message='选择的 AI Agent 不存在') from exc
        manifest = adapter.get_manifest()
        record = await MindmapAiDao.get_connector(db, agent_key, for_update=True)
        try:
            credential_env = resolve_connector_credential(agent_key, record)
            healthy, reason = await cls._probe_connector_health(
                adapter,
                credential_env,
                model_ref=cls._resolve_model_ref(manifest, None),
            )
        except Exception as exc:
            mapped = map_adapter_exception(exc)
            healthy, reason = False, str(mapped)
        values = {
            'health_status': 'healthy' if healthy else 'unhealthy',
            'health_reason': None if healthy else (reason or '健康检查未通过')[:500],
            'last_health_time': datetime.now(),
            'update_by': user_name,
        }
        if record is None:
            record = await MindmapAiDao.add_connector(db, {
                'agent_key': agent_key,
                'enabled': int(manifest.status == 'enabled'),
                'rollout_percentage': 100,
                'network_policy': 'adapter_default',
                'conformance_status': 'unknown',
                'create_by': user_name,
                'created_time': datetime.now(),
                'update_time': datetime.now(),
                **values,
            })
        else:
            await MindmapAiDao.update_connector(db, agent_key, values)
        await db.commit()
        refreshed = await MindmapAiDao.get_connector(db, agent_key)
        return cls._connector_model(refreshed or record, manifest)

    @classmethod
    async def conformance_connector(
        cls,
        db: AsyncSession,
        agent_key: str,
        user_name: str,
    ) -> MindmapAiConnectorModel:
        try:
            adapter = get_mindmap_agent_registry().get(agent_key)
        except KeyError as exc:
            raise ServiceException(message='选择的 AI Agent 不存在') from exc
        manifest = adapter.get_manifest()
        try:
            report = build_agent_conformance_report(adapter)
            status = 'passed'
        except Exception:
            logger.exception(
                f'AI Agent 确定性合同检查失败: agent_key={agent_key}'
            )
            status = 'failed'
            report = {
                'assessmentScope': 'deterministic_contract_fixture',
                'providerExecution': 'not_run',
                'securityFaultInjection': 'not_run',
                'releaseEligible': False,
                'contractVersion': manifest.tool_contract_version,
                'errorContractVersion': manifest.error_contract_version,
                'smmVersions': list(manifest.smm_versions),
                'adapterVersion': manifest.adapter_version,
                'sdkVersion': manifest.sdk_version,
                'runtimeVersion': manifest.runtime_version,
                'errorCode': 'DETERMINISTIC_CONTRACT_FAILED',
                'checks': [{
                    'name': 'deterministicContractFixture',
                    'status': 'failed',
                }],
            }
        record = await MindmapAiDao.get_connector(db, agent_key, for_update=True)
        values = {
            'conformance_status': status,
            'conformance_report_json': _json_dumps(report),
            'last_conformance_time': datetime.now(),
            'update_by': user_name,
        }
        if record is None:
            record = await MindmapAiDao.add_connector(db, {
                'agent_key': agent_key,
                'enabled': int(manifest.status == 'enabled'),
                'rollout_percentage': 100,
                'network_policy': 'adapter_default',
                'health_status': 'unknown',
                'create_by': user_name,
                'created_time': datetime.now(),
                'update_time': datetime.now(),
                **values,
            })
        else:
            await MindmapAiDao.update_connector(db, agent_key, values)
        await db.commit()
        refreshed = await MindmapAiDao.get_connector(db, agent_key)
        return cls._connector_model(refreshed or record, manifest)

    @classmethod
    async def _prepare_source(
        cls,
        db: AsyncSession,
        request_model: MindmapAiJobCreateModel,
        user_id: int,
        *,
        capture_editor_document: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, int | None, str | None, int | None, str | None]:
        source = request_model.source
        if source.type == 'none':
            return None, None, None, None, None
        if source.type == 'uploaded_artifact':
            if source.artifact is not None:
                artifact, _summary = validate_smm_artifact(source.artifact)
                document = artifact['document']
            else:
                raw_document = source.document or {}
                if len(canonical_json_bytes(raw_document)) > AI_MAX_FILE_BYTES:
                    raise MindmapArtifactError(
                        f'AI 脑图文件不能超过{AI_MAX_FILE_BYTES}字节',
                        code='AI_INPUT_TOO_LARGE',
                    )
                document, _summary = normalize_ai_editable_source_document(raw_document)
            return document, source.revision, compute_document_hash(document), None, None
        if source.type == 'local_snapshot':
            document, _summary = normalize_ai_editable_source_document(
                source.document or {},
                max_node_count=AI_MAX_NODE_COUNT,
            )
            document_hash = compute_document_hash(document)
            if source.document_hash is not None and source.document_hash != document_hash:
                raise ServiceException(message='本地脑图内容哈希与请求不一致')
            return document, source.revision, document_hash, None, None
        mindmap = await MindmapService.check_mindmap_access(
            db,
            int(source.mindmap_id),
            user_id,
            # Direct jobs mutate the authoritative document regardless of the
            # legacy result target. Do the edit-permission check before a paid
            # provider run rather than allowing a read-only user to enqueue a
            # task that can only fail on its first mutation.
            require_edit=(
                request_model.target == 'proposal'
                or request_model.execution_mode == 'direct'
            ),
        )
        detail = await MindmapService.get_mindmap_detail_services(db, mindmap.id, user_id)
        editor_document = document_from_mindmap_detail(detail)
        document, _summary = normalize_ai_editable_source_document(
            editor_document, max_node_count=AI_MAX_NODE_COUNT,
        )
        from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

        revision = int(mindmap.content_revision)
        room_epoch = await room_manager.get_active_lineage_epoch(mindmap.id, revision)
        if capture_editor_document is not None and request_model.execution_mode == 'direct':
            if len(canonical_json_bytes(editor_document)) > AI_MAX_FILE_BYTES:
                raise MindmapArtifactError('脑图原始撤销快照超过大小上限', code='AI_INPUT_TOO_LARGE')
            capture_editor_document.update({
                'schemaVersion': 1, 'mindmapId': mindmap.id, 'revision': revision,
                'documentHash': compute_document_hash(document), 'document': deepcopy(editor_document),
            })
        return document, revision, compute_document_hash(document), mindmap.id, room_epoch

    @classmethod
    async def _prepare_source_for_job(
        cls,
        db: AsyncSession,
        request_model: MindmapAiJobCreateModel,
        user_id: int,
        *,
        capture_editor_document: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, int | None, str | None, int | None, str | None]:
        try:
            return await cls._prepare_source(
                db, request_model, user_id, capture_editor_document=capture_editor_document,
            )
        except MindmapArtifactError as exc:
            raise ServiceException(
                data={'errorCode': (
                    'AI_INPUT_INVALID'
                    if exc.code == 'AI_OUTPUT_INVALID'
                    else exc.code
                )},
                message=str(exc),
            ) from exc

    @classmethod
    async def create_job(
        cls,
        db: AsyncSession,
        request_model: MindmapAiJobCreateModel,
        user_id: int,
        idempotency_key: str,
    ) -> MindmapAiJobModel:
        fingerprint = _stable_create_fingerprint(request_model)
        existing = await MindmapAiDao.get_job_by_idempotency(
            db,
            user_id,
            idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ServiceException(message='幂等键已被用于不同的 AI 脑图任务')
            cls._schedule_replayed_job(existing)
            return _job_model(existing)
        registry = get_mindmap_agent_registry()
        try:
            adapter = registry.get(request_model.agent_key)
        except KeyError as exc:
            raise ServiceException(message='选择的 AI Agent 不存在') from exc
        manifest = adapter.get_manifest()
        await cls._ensure_connector_available(
            db,
            manifest,
            user_id,
            preflight_unknown=False,
        )
        expected_result_type = 'message' if request_model.intent == 'discuss' else 'artifact'
        if (
            request_model.intent not in manifest.intents
            or request_model.source.type not in manifest.input_types
            or not _manifest_supports_result(manifest, expected_result_type)
        ):
            raise ServiceException(message='选择的 AI Agent 不支持当前任务')

        undo_baseline: dict[str, Any] = {}
        (
            document,
            base_revision,
            base_hash,
            source_mindmap_id,
            base_room_epoch,
        ) = await cls._prepare_source_for_job(
            db, request_model, user_id, capture_editor_document=undo_baseline,
        )
        payload = request_model.model_dump(by_alias=True, exclude_none=True)
        payload['source']['document'] = document
        if request_model.intent == 'discuss':
            payload['source'].pop('baselineDocument', None)
        else:
            payload['source']['baselineDocument'] = document
        payload['source']['revision'] = base_revision
        payload['source']['documentHash'] = base_hash
        payload['source']['roomEpoch'] = base_room_epoch
        if source_mindmap_id is not None:
            payload['source']['mindmapId'] = source_mindmap_id
        payload['source'].pop('artifact', None)
        request_json = _json_dumps(_request_with_undo_baseline(payload, undo_baseline))

        policy, runtime_values = await cls._prepare_job_runtime(db, request_model, manifest, user_id)
        await cls._ensure_concurrency_available(db, manifest.agent_key, policy)

        now = datetime.now()
        job_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        try:
            await MindmapAiDao.add_session(db, {
                'id': session_id,
                'user_id': user_id,
                'current_agent_key': manifest.agent_key,
                'title': _initial_session_title(request_model.prompt),
                'status': 'active',
                'created_time': now,
                'update_time': now,
                'expires_time': now + timedelta(days=policy.retention_days),
            })
            job = await MindmapAiDao.add_job(db, {
                'id': job_id,
                'user_id': user_id,
                'session_id': session_id,
                'turn_index': 1,
                **runtime_values,
                'source_mindmap_id': source_mindmap_id,
                'base_revision': base_revision,
                'base_hash': base_hash,
                'base_room_epoch': base_room_epoch,
                'request_json': request_json,
                'request_fingerprint': fingerprint,
                'idempotency_key': idempotency_key,
                'status': 'queued',
                'progress': 0,
                'expires_time': now + timedelta(days=policy.retention_days),
                'created_time': now,
                'update_time': now,
            })
            await MindmapAiDao.add_event(
                db,
                job_id,
                'job_created',
                _event_json({
                    'status': 'queued',
                    'progress': 0,
                    'agentKey': manifest.agent_key,
                    'intent': request_model.intent,
                    'sourceType': request_model.source.type,
                }),
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            replay = await MindmapAiDao.get_job_by_idempotency(db, user_id, idempotency_key)
            if replay is None or replay.request_fingerprint != fingerprint:
                raise ServiceException(message='AI 脑图任务创建冲突，请重试') from None
            cls._schedule_replayed_job(replay)
            return _job_model(replay)
        record_mindmap_ai_event('job_created')
        MindmapAiTaskManager.schedule(job_id)
        return _job_model(job)

    @classmethod
    async def retry_job(  # noqa: PLR0912, PLR0915
        cls,
        db: AsyncSession,
        retry_of_job_id: str,
        model: MindmapAiJobRetryModel,
        user_id: int,
        idempotency_key: str,
    ) -> MindmapAiJobModel:
        """Create a new platform turn for a failed terminal job.

        A retry deliberately has no ``parent_job_id``. The runner therefore
        calls ``adapter.start`` with no external provider session, even though
        the new turn remains in the original platform session for audit.
        """
        fingerprint = _stable_retry_fingerprint(retry_of_job_id, model)
        existing = await MindmapAiDao.get_job_by_idempotency(
            db,
            user_id,
            idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ServiceException(message='幂等键已被用于不同的 AI 脑图任务')
            cls._schedule_replayed_job(existing)
            return _job_model(existing)

        retried_job = await MindmapAiDao.get_job(db, retry_of_job_id, user_id)
        if retried_job is None:
            raise ServiceException(
                data={'errorCode': 'AI_JOB_NOT_FOUND'},
                message='要重试的 AI 脑图任务不存在',
            )
        if retried_job.status not in RETRYABLE_JOB_STATUSES:
            raise ServiceException(
                data={'errorCode': 'AI_JOB_NOT_RETRYABLE'},
                message='只有失败、取消、过期或基线失效且无可用结果的终态任务才能重试',
            )
        session = await MindmapAiDao.get_session(db, retried_job.session_id, user_id)
        if not _session_accepts_work(session):
            raise ServiceException(
                data={'errorCode': 'AI_SESSION_UNAVAILABLE'},
                message='原 AI 脑图会话不存在或已结束，不能在该会话中重试',
            )
        try:
            original_request = MindmapAiJobCreateModel.model_validate(
                _json_loads(retried_job.request_json, {}),
            )
        except (TypeError, ValueError) as exc:
            raise ServiceException(
                data={'errorCode': 'AI_RETRY_SOURCE_EXPIRED'},
                message='原任务输入已过期或不完整，无法安全重试，请新建任务',
            ) from exc

        payload = original_request.model_dump(by_alias=True, exclude_none=True)
        requested_agent_key = model.agent_key or original_request.agent_key
        payload['agentKey'] = requested_agent_key
        if model.prompt is not None:
            payload['prompt'] = model.prompt
        if model.parameters is not None:
            payload['parameters'].update(
                model.parameters.model_dump(
                    by_alias=True,
                    exclude_unset=True,
                    exclude_none=True,
                ),
            )
        if requested_agent_key == 'native_mindmap':
            native_model_id = model.model_id
            if native_model_id is None and requested_agent_key == original_request.agent_key:
                native_model_id = original_request.model_id
            if native_model_id is None:
                raise ServiceException(message='请选择自研 MindMap Agent 使用的模型')
            payload['modelId'] = native_model_id
        else:
            # Provider adapters own their configured model; a stale native
            # model id must not leak when retrying with another Agent.
            payload.pop('modelId', None)
        try:
            request_model = MindmapAiJobCreateModel.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise ServiceException(
                data={'errorCode': 'AI_RETRY_REQUEST_INVALID'},
                message='重试参数与原任务不兼容，请调整后重试',
            ) from exc

        registry = get_mindmap_agent_registry()
        try:
            adapter = registry.get(request_model.agent_key)
        except KeyError as exc:
            raise ServiceException(message='选择的 AI Agent 不存在') from exc
        manifest = adapter.get_manifest()
        await cls._ensure_connector_available(
            db,
            manifest,
            user_id,
            preflight_unknown=False,
        )
        if (
            request_model.intent not in manifest.intents
            or request_model.source.type not in manifest.input_types
            or not _manifest_supports_result(
                manifest,
                'message' if request_model.intent == 'discuss' else 'artifact',
            )
        ):
            raise ServiceException(message='选择的 AI Agent 不支持重试当前任务')

        undo_baseline: dict[str, Any] = {}
        (
            document,
            base_revision,
            base_hash,
            source_mindmap_id,
            base_room_epoch,
        ) = await cls._prepare_source_for_job(
            db, request_model, user_id, capture_editor_document=undo_baseline,
        )
        source_payload = payload['source']
        source_payload['document'] = document
        source_payload['revision'] = base_revision
        source_payload['documentHash'] = base_hash
        source_payload['roomEpoch'] = base_room_epoch
        # A cloud retry always starts from the latest authoritative document.
        # Other sources keep their frozen original proposal baseline.
        if request_model.intent == 'discuss':
            source_payload.pop('baselineDocument', None)
        else:
            source_payload['baselineDocument'] = (
                document
                if request_model.source.type == 'cloud_document'
                else (request_model.source.baseline_document or document)
            )
        if source_mindmap_id is not None:
            source_payload['mindmapId'] = source_mindmap_id
        source_payload.pop('artifact', None)
        request_model = MindmapAiJobCreateModel.model_validate(payload)

        policy, runtime_values = await cls._prepare_job_runtime(db, request_model, manifest, user_id)
        await cls._ensure_concurrency_available(db, manifest.agent_key, policy)

        # Keep the same global lock order as completion/follow-up/delete:
        # every session job in stable ID order, then the session row.
        session_jobs = await MindmapAiDao.lock_jobs_for_session(db, retried_job.session_id)
        locked_session = await MindmapAiDao.get_session(
            db,
            retried_job.session_id,
            user_id,
            for_update=True,
        )
        locked_jobs = {str(session_job.id): session_job for session_job in session_jobs}
        locked_retried_job = locked_jobs.get(str(retry_of_job_id))
        if (
            not _session_accepts_work(locked_session)
            or locked_retried_job is None
            or locked_retried_job.status not in RETRYABLE_JOB_STATUSES
            or locked_retried_job.session_id != retried_job.session_id
        ):
            raise ServiceException(
                data={'errorCode': 'AI_RETRY_STATE_CHANGED'},
                message='原任务或会话状态已变化，请刷新后重试',
            )
        next_turn_index = max(
            (int(session_job.turn_index or 0) for session_job in session_jobs),
            default=0,
        ) + 1

        now = datetime.now()
        job_id = str(uuid.uuid4())
        try:
            job = await MindmapAiDao.add_job(db, {
                'id': job_id,
                'user_id': user_id,
                'session_id': retried_job.session_id,
                # Never set parent_job_id for retry: doing so would resume or
                # fork a provider SDK session from the failed turn.
                'parent_job_id': None,
                'retry_of_job_id': retry_of_job_id,
                'turn_index': next_turn_index,
                **runtime_values,
                'source_mindmap_id': source_mindmap_id,
                'base_revision': base_revision,
                'base_hash': base_hash,
                'base_room_epoch': base_room_epoch,
                'request_json': _json_dumps(
                    _request_with_undo_baseline(
                        request_model.model_dump(by_alias=True, exclude_none=True), undo_baseline,
                    ),
                ),
                'request_fingerprint': fingerprint,
                'idempotency_key': idempotency_key,
                'external_session_ref': None,
                'status': 'queued',
                'progress': 0,
                'expires_time': now + timedelta(days=policy.retention_days),
                'created_time': now,
                'update_time': now,
            })
            await MindmapAiDao.add_event(db, job_id, 'job_created', _event_json({
                'status': 'queued',
                'progress': 0,
                'agentKey': manifest.agent_key,
                'retryOfJobId': retry_of_job_id,
                'turnIndex': job.turn_index,
                'intent': request_model.intent,
                'sourceType': request_model.source.type,
            }))
            await MindmapAiDao.update_session(db, retried_job.session_id, {
                'current_agent_key': manifest.agent_key,
                'expires_time': max(
                    locked_session.expires_time,
                    now + timedelta(days=policy.retention_days),
                ),
            })
            await db.commit()
        except IntegrityError:
            await db.rollback()
            replay = await MindmapAiDao.get_job_by_idempotency(db, user_id, idempotency_key)
            if replay is None or replay.request_fingerprint != fingerprint:
                raise ServiceException(message='AI 脑图重试任务创建冲突，请重试') from None
            cls._schedule_replayed_job(replay)
            return _job_model(replay)
        record_mindmap_ai_event('job_created')
        MindmapAiTaskManager.schedule(job_id)
        return _job_model(job)

    @classmethod
    async def _create_waiting_followup_job(  # noqa: PLR0915
        cls,
        db: AsyncSession,
        parent: Any,
        model: MindmapAiMessageModel,
        user_id: int,
        fingerprint: str,
        idempotency_key: str,
    ) -> MindmapAiJobModel:
        """Persist a message submitted while the current turn is still running."""
        content_request = MindmapAiJobCreateModel.model_validate(
            _json_loads(parent.request_json, {}),
        )
        requested_intent = model.intent or parent.intent
        agent_key = model.agent_key or parent.agent_key
        payload = content_request.model_dump(by_alias=True, exclude_none=True)
        payload['agentKey'] = agent_key
        payload['intent'] = requested_intent
        payload['prompt'] = model.prompt
        if agent_key == 'native_mindmap':
            native_model_id = model.model_id or content_request.model_id
            if native_model_id is None:
                raise ServiceException(message='请选择自研 MindMap Agent 使用的模型')
            payload['modelId'] = native_model_id
        else:
            payload.pop('modelId', None)
        source_type = str((payload.get('source') or {}).get('type') or 'none')
        payload['target'] = (
            'message'
            if requested_intent == 'discuss'
            else 'file'
            if payload.get('executionMode') == 'direct'
            else 'proposal'
            if source_type in {'local_snapshot', 'cloud_document'}
            else 'file'
        )
        request_model = MindmapAiJobCreateModel.model_validate(payload)
        registry = get_mindmap_agent_registry()
        try:
            adapter = registry.get(agent_key)
        except KeyError as exc:
            raise ServiceException(message='选择的 AI Agent 不存在') from exc
        manifest = adapter.get_manifest()
        await cls._ensure_connector_available(
            db,
            manifest,
            user_id,
            preflight_unknown=False,
        )
        if (
            request_model.intent not in manifest.intents
            or request_model.source.type not in manifest.input_types
            or not _manifest_supports_result(
                manifest,
                'message' if request_model.intent == 'discuss' else 'artifact',
            )
        ):
            raise ServiceException(message='选择的 AI Agent 不支持继续当前任务')
        policy, runtime_values = await cls._prepare_job_runtime(db, request_model, manifest, user_id)

        session_jobs = await MindmapAiDao.lock_jobs_for_session(db, parent.session_id)
        session = await MindmapAiDao.get_session(
            db,
            parent.session_id,
            user_id,
            for_update=True,
        )
        locked_parent = next(
            (item for item in session_jobs if str(item.id) == str(parent.id)),
            None,
        )
        runnable_parent_statuses = {'queued', 'preparing', 'running', 'validating'}
        if (
            not _session_accepts_work(session)
            or locked_parent is None
            or locked_parent.status not in runnable_parent_statuses
        ):
            raise ServiceException(
                data={'errorCode': 'AI_FOLLOWUP_STATE_CHANGED'},
                message='当前 AI 轮次刚刚结束，请刷新后继续输入',
            )
        # Keep multiple messages submitted during one running turn as a
        # serial chain. The first child waits for the current parent; every
        # later child waits for the previous queued child so it can consume
        # that child's durable artifact instead of starting concurrently.
        queue_parent_id = str(locked_parent.id)
        queue_parent_candidates = {
            str(item.id): item
            for item in session_jobs
            if item.id != locked_parent.id
            and item.status in {
                WAITING_TURN_STATUS,
                'queued', 'preparing', 'running', 'validating',
            }
        }
        seen_queue_parent_ids: set[str] = set()
        while queue_parent_id not in seen_queue_parent_ids:
            seen_queue_parent_ids.add(queue_parent_id)
            children = [
                item for item in queue_parent_candidates.values()
                if str(item.parent_job_id or '') == queue_parent_id
            ]
            if not children:
                break
            tail = max(
                children,
                key=lambda item: (
                    int(getattr(item, 'turn_index', 0) or 0),
                    getattr(item, 'created_time', datetime.min),
                    str(getattr(item, 'id', '')),
                ),
            )
            queue_parent_id = str(tail.id)
        next_turn_index = max(
            (int(item.turn_index or 0) for item in session_jobs),
            default=0,
        ) + 1
        waiting_count = sum(
            1 for item in session_jobs if item.status == WAITING_TURN_STATUS
        )
        now = datetime.now()
        job_id = str(uuid.uuid4())
        source = request_model.source
        source_mindmap_id = source.mindmap_id if source.type == 'cloud_document' else None
        content_has_document_lineage = source.type in {'local_snapshot', 'cloud_document'}
        durable_request_payload = request_model.model_dump(
            by_alias=True,
            exclude_none=True,
        )
        # Route is orchestration metadata rather than Agent input. Persist it
        # beside the validated request so recovery workers make the same
        # release decision after a process restart.
        durable_request_payload['queueRoute'] = model.route
        job = await MindmapAiDao.add_job(db, {
            'id': job_id,
            'user_id': user_id,
            'session_id': parent.session_id,
            'parent_job_id': queue_parent_id,
            'turn_index': next_turn_index,
            **runtime_values,
            'source_mindmap_id': source_mindmap_id,
            'base_revision': source.revision if content_has_document_lineage else None,
            'base_hash': source.document_hash if content_has_document_lineage else None,
            'base_room_epoch': source.room_epoch if source.type == 'cloud_document' else None,
            'request_json': _json_dumps(durable_request_payload),
            'request_fingerprint': fingerprint,
            'idempotency_key': idempotency_key,
            'status': WAITING_TURN_STATUS,
            'progress': 0,
            'expires_time': now + timedelta(days=policy.retention_days),
            'created_time': now,
            'update_time': now,
        })
        await MindmapAiDao.add_event(db, job_id, 'job_created', _event_json({
            'status': WAITING_TURN_STATUS,
            'progress': 0,
            'agentKey': manifest.agent_key,
            'parentJobId': queue_parent_id,
            'turnIndex': job.turn_index,
            'intent': request_model.intent,
            'sourceType': request_model.source.type,
            'route': model.route,
            'queuePosition': waiting_count + 1,
            'continuationBase': model.continuation_base,
        }))
        await MindmapAiDao.update_session(db, parent.session_id, {
            'current_agent_key': manifest.agent_key,
            'expires_time': max(
                session.expires_time,
                now + timedelta(days=policy.retention_days),
            ),
        })
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            replay = await MindmapAiDao.get_job_by_idempotency(db, user_id, idempotency_key)
            if replay is None or replay.request_fingerprint != fingerprint:
                raise ServiceException(message='AI 脑图排队请求创建冲突，请重试') from None
            return _job_model(replay)
        record_mindmap_ai_event('job_queued')
        return _job_model(job)

    @classmethod
    async def create_followup_job(  # noqa: PLR0912, PLR0915
        cls,
        db: AsyncSession,
        parent_job_id: str,
        model: MindmapAiMessageModel,
        user_id: int,
        idempotency_key: str,
    ) -> MindmapAiJobModel:
        fingerprint = _stable_followup_fingerprint(parent_job_id, model)
        existing = await MindmapAiDao.get_job_by_idempotency(
            db,
            user_id,
            idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ServiceException(message='幂等键已被用于不同的 AI 脑图任务')
            cls._schedule_replayed_job(existing)
            return _job_model(existing)
        parent = await MindmapAiDao.get_job(db, parent_job_id, user_id)
        if parent is None:
            raise ServiceException(message='AI 脑图任务不存在')
        if parent.status == 'needs_review':
            raise ServiceException(
                data={'errorCode': 'AI_FOLLOWUP_REVIEW_REQUIRED'},
                message='请先确认或不采纳当前 AI 结果，再继续下一轮',
            )
        if parent.status in {'queued', 'preparing', 'running', 'validating'}:
            return await cls._create_waiting_followup_job(
                db,
                parent,
                model,
                user_id,
                fingerprint,
                idempotency_key,
            )
        observed_parent_status = parent.status
        requested_intent = model.intent or parent.intent
        current_document_followup = model.continuation_base == 'current_document'
        current_snapshot_followup = model.continuation_base == 'current_snapshot'
        current_source_followup = current_document_followup or current_snapshot_followup
        needs_input_followup = parent.status == 'needs_input' and not parent.artifact_id
        discussion_followup = (
            parent.status == 'completed_message'
            and parent.intent == 'discuss'
            and parent.target == 'message'
            and bool(getattr(parent, 'response_id', None))
            and not parent.artifact_id
            and not parent.proposal_id
        )
        artifact_followup = bool(
            not current_source_followup
            and parent.status in {
                'ready', 'completed_file', 'completed_no_change', 'completed_direct',
            }
            and parent.artifact_id
        )
        authoritative_document_followup = bool(
            current_document_followup
            and parent.status in {'applied', 'undone', 'completed_direct'}
            and parent.source_type == 'cloud_document'
            and parent.source_mindmap_id
        )
        authoritative_snapshot_followup = bool(
            current_snapshot_followup
            and parent.status in {'applied', 'undone'}
            and parent.status == model.expected_parent_status
            and parent.source_type == 'local_snapshot'
            and parent.proposal_id
            and model.source is not None
        )
        authoritative_followup = (
            authoritative_document_followup or authoritative_snapshot_followup
        )
        if not any((
            needs_input_followup,
            discussion_followup,
            artifact_followup,
            authoritative_followup,
        )):
            raise ServiceException(
                data={'errorCode': (
                    'AI_FOLLOWUP_BASE_INVALID'
                    if current_source_followup
                    else 'AI_FOLLOWUP_UNAVAILABLE'
                )},
                message='当前 AI 脑图结果不能继续调整',
            )
        session = await MindmapAiDao.get_session(
            db,
            parent.session_id,
            user_id,
        )
        if not _session_accepts_work(session):
            raise ServiceException(message='AI 脑图会话不存在或已结束')
        if needs_input_followup and requested_intent != parent.intent:
            raise ServiceException(message='补充澄清信息时不能切换 AI 任务模式')
        if (
            (needs_input_followup or discussion_followup)
            and current_source_followup
        ):
            raise ServiceException(
                data={'errorCode': 'AI_FOLLOWUP_BASE_INVALID'},
                message='当前文字交互轮次不能切换为当前脑图基线',
            )

        if authoritative_followup:
            allowed_artifact_ids = (
                {None, parent.artifact_id}
                if authoritative_document_followup
                else {None}
            )
            if model.artifact_id not in allowed_artifact_ids:
                raise ServiceException(
                    data={'errorCode': 'AI_FOLLOWUP_BASE_INVALID'},
                    message='从当前脑图继续时不能选择历史结果',
                )
            selected_artifact_id = None
            selected_artifact = None
            content_parent = parent
        elif needs_input_followup or discussion_followup:
            if model.artifact_id is not None:
                raise ServiceException(message='当前文字交互轮次不能选择 Artifact')
            selected_artifact_id = None
            selected_artifact = None
            content_parent = parent
        else:
            selected_artifact_id = model.artifact_id or parent.artifact_id
            artifact_record, selected_artifact = await cls.get_artifact(
                db,
                selected_artifact_id,
                user_id,
            )
            artifact_job = await MindmapAiDao.get_job(db, artifact_record.job_id, user_id)
            if artifact_job is None or artifact_job.session_id != parent.session_id:
                raise ServiceException(message='只能选择当前会话中的 AI 脑图结果')
            content_parent = artifact_job
        content_request = MindmapAiJobCreateModel.model_validate(
            _json_loads(content_parent.request_json, {}),
        )
        parent_request = (
            content_request
            if content_parent.id == parent.id
            else MindmapAiJobCreateModel.model_validate(_json_loads(parent.request_json, {}))
        )
        agent_key = model.agent_key or parent.agent_key

        payload = content_request.model_dump(by_alias=True, exclude_none=True)
        payload['agentKey'] = agent_key
        payload['intent'] = requested_intent
        if needs_input_followup:
            supplemented_prompt = (
                f'原始任务要求：\n{content_request.prompt}\n\n'
                f'用户补充信息：\n{model.prompt}'
            )
            if len(supplemented_prompt) > AI_PROMPT_MAX_LENGTH:
                raise ServiceException(message='原始要求与补充信息合计超过 20000 字符，请缩短补充内容')
            payload['prompt'] = supplemented_prompt
        else:
            payload['prompt'] = model.prompt
        if agent_key == 'native_mindmap':
            native_model_id = model.model_id or parent_request.model_id or content_request.model_id
            if native_model_id is None:
                raise ServiceException(message='请选择自研 MindMap Agent 使用的模型')
            payload['modelId'] = native_model_id
        else:
            payload.pop('modelId', None)

        source_payload = payload['source']
        if authoritative_snapshot_followup:
            submitted_source = model.source
            trusted_source = parent_request.source
            if (
                submitted_source is None
                or trusted_source.type != 'local_snapshot'
                or submitted_source.type != 'local_snapshot'
                or submitted_source.document_id != trusted_source.document_id
                or submitted_source.document is None
                or submitted_source.document_hash is None
                or submitted_source.baseline_document is not None
                or (
                    parent.base_revision is not None
                    and submitted_source.revision is not None
                    and submitted_source.revision <= parent.base_revision
                )
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_FOLLOWUP_BASE_INVALID'},
                    message='本地脑图当前快照与原任务血缘不一致',
                )
            if len(canonical_json_bytes(submitted_source.document)) > AI_MAX_FILE_BYTES:
                raise ServiceException(
                    data={'errorCode': 'AI_INPUT_TOO_LARGE'},
                    message=f'本地脑图快照不能超过{AI_MAX_FILE_BYTES}字节',
                )
            # Only the browser-owned document bytes, revision and claimed hash
            # are accepted from this turn.  Document identity and scope stay on
            # the already-authorized platform lineage; historical Artifacts are
            # deliberately not consulted for an applied/undone local turn.
            source_payload = submitted_source.model_dump(by_alias=True, exclude_none=True)
            source_payload['documentId'] = trusted_source.document_id
            source_payload['scope'] = trusted_source.scope.model_dump(
                by_alias=True,
                exclude_none=True,
            )
            source_payload.pop('baselineDocument', None)
            payload['source'] = source_payload
        elif selected_artifact is not None:
            if content_request.source.type in {'none', 'uploaded_artifact'}:
                # A generated standalone file becomes a concrete document input
                # for its next turn.  Keeping ``type=none`` while injecting a
                # document violates the public source contract and was the root
                # cause of create -> continue failures.
                source_payload = {
                    'type': 'uploaded_artifact',
                    'scope': content_request.source.scope.model_dump(
                        by_alias=True,
                        exclude_none=True,
                    ),
                    'document': selected_artifact['document'],
                }
                payload['source'] = source_payload
            else:
                source_payload['document'] = selected_artifact['document']
                source_payload['baselineDocument'] = (
                    content_request.source.baseline_document
                    or content_request.source.document
                )
                source_payload.pop('artifact', None)
        normalized_source_type = str(source_payload.get('type') or 'none')
        payload['target'] = (
            'message'
            if requested_intent == 'discuss'
            else 'file'
            if payload.get('executionMode') == 'direct'
            else (
                'proposal'
                if normalized_source_type in {'local_snapshot', 'cloud_document'}
                else 'file'
            )
        )
        request_model = MindmapAiJobCreateModel.model_validate(payload)
        registry = get_mindmap_agent_registry()
        try:
            adapter = registry.get(agent_key)
        except KeyError as exc:
            raise ServiceException(message='选择的 AI Agent 不存在') from exc
        manifest = adapter.get_manifest()
        await cls._ensure_connector_available(
            db,
            manifest,
            user_id,
            preflight_unknown=False,
        )
        if (
            request_model.intent not in manifest.intents
            or request_model.source.type not in manifest.input_types
            or not _manifest_supports_result(
                manifest,
                'message' if request_model.intent == 'discuss' else 'artifact',
            )
        ):
            raise ServiceException(message='选择的 AI Agent 不支持继续当前任务')
        undo_baseline: dict[str, Any] = {}
        refresh_cloud_source = authoritative_document_followup or request_model.execution_mode == 'direct'
        if authoritative_followup or refresh_cloud_source:
            try:
                (
                    authoritative_document,
                    authoritative_revision,
                    authoritative_hash,
                    authoritative_mindmap_id,
                    authoritative_room_epoch,
                ) = await cls._prepare_source_for_job(
                    db, request_model, user_id, capture_editor_document=undo_baseline,
                )
            except ServiceException as exc:
                if not authoritative_snapshot_followup:
                    raise
                source_error_code = (
                    exc.data.get('errorCode')
                    if isinstance(exc.data, dict)
                    else None
                )
                raise ServiceException(
                    data={'errorCode': (
                        source_error_code
                        if source_error_code in {'AI_INPUT_INVALID', 'AI_INPUT_TOO_LARGE'}
                        else 'AI_FOLLOWUP_BASE_INVALID'
                    )},
                    message='本地脑图当前快照未通过内容、大小与哈希校验',
                ) from exc
            if (
                authoritative_document is None
                or (
                    refresh_cloud_source
                    and authoritative_mindmap_id != parent.source_mindmap_id
                )
                or (
                    authoritative_snapshot_followup
                    and (
                        authoritative_mindmap_id is not None
                        or authoritative_room_epoch is not None
                    )
                )
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_FOLLOWUP_BASE_INVALID'},
                    message=(
                        '无法冻结当前本地脑图快照作为继续调整基线'
                        if authoritative_snapshot_followup
                        else '无法冻结当前云端脑图作为继续调整基线'
                    ),
                )
            source_payload = payload['source']
            source_payload['document'] = authoritative_document
            source_payload['revision'] = authoritative_revision
            source_payload['documentHash'] = authoritative_hash
            if refresh_cloud_source:
                source_payload['roomEpoch'] = authoritative_room_epoch
                source_payload['mindmapId'] = authoritative_mindmap_id
            else:
                source_payload.pop('roomEpoch', None)
                source_payload.pop('mindmapId', None)
            source_payload.pop('artifact', None)
            if requested_intent == 'discuss':
                source_payload.pop('baselineDocument', None)
            else:
                source_payload['baselineDocument'] = authoritative_document
            request_model = MindmapAiJobCreateModel.model_validate(payload)
        policy, runtime_values = await cls._prepare_job_runtime(db, request_model, manifest, user_id)
        await cls._ensure_concurrency_available(db, manifest.agent_key, policy)

        # Completion locks one job and then the session. Follow-up creation
        # therefore locks all session jobs in stable ID order before taking the
        # session row; it must never hold the session while waiting for a job.
        session_jobs = await MindmapAiDao.lock_jobs_for_session(
            db,
            parent.session_id,
        )
        locked_session = await MindmapAiDao.get_session(
            db,
            parent.session_id,
            user_id,
            for_update=True,
        )
        locked_jobs = {str(session_job.id): session_job for session_job in session_jobs}
        locked_parent = locked_jobs.get(str(parent_job_id))
        locked_content_parent = locked_jobs.get(str(content_parent.id))
        locked_parent_eligible = (
            locked_parent is not None
            and (
                (
                    needs_input_followup
                    and locked_parent.status == 'needs_input'
                    and not locked_parent.artifact_id
                )
                or (
                    discussion_followup
                    and locked_parent.status == 'completed_message'
                    and locked_parent.intent == 'discuss'
                    and locked_parent.target == 'message'
                    and bool(getattr(locked_parent, 'response_id', None))
                    and not locked_parent.artifact_id
                    and not locked_parent.proposal_id
                )
                or (
                    authoritative_document_followup
                    and locked_parent.status in {'applied', 'undone', 'completed_direct'}
                    and locked_parent.status == observed_parent_status
                    and locked_parent.source_type == 'cloud_document'
                    and locked_parent.source_mindmap_id == parent.source_mindmap_id
                )
                or (
                    authoritative_snapshot_followup
                    and locked_parent.status in {'applied', 'undone'}
                    and locked_parent.status == model.expected_parent_status
                    and locked_parent.status == observed_parent_status
                    and locked_parent.source_type == 'local_snapshot'
                    and locked_parent.source_mindmap_id is None
                    and locked_parent.proposal_id == parent.proposal_id
                    and locked_parent.request_json == parent.request_json
                )
                or (
                    not needs_input_followup
                    and not discussion_followup
                    and not authoritative_followup
                    and locked_parent.status in {
                        'ready', 'completed_file', 'completed_no_change', 'completed_direct',
                    }
                    and bool(locked_parent.artifact_id)
                )
            )
        )
        locked_content_eligible = (
            locked_parent is not None
            and
            locked_content_parent is not None
            and locked_content_parent.session_id == parent.session_id
            and (
                (
                    (needs_input_followup or discussion_followup)
                    and locked_content_parent.id == locked_parent.id
                    and not locked_content_parent.artifact_id
                )
                or (
                    authoritative_followup
                    and locked_content_parent.id == locked_parent.id
                )
                or (
                    not needs_input_followup
                    and not discussion_followup
                    and not authoritative_followup
                    and locked_content_parent.artifact_id == selected_artifact_id
                )
            )
        )
        if (
            not _session_accepts_work(locked_session)
            or not locked_parent_eligible
            or not locked_content_eligible
        ):
            raise ServiceException(
                data={'errorCode': 'AI_FOLLOWUP_STATE_CHANGED'},
                message='AI 脑图会话或结果已变化，请刷新后重试',
            )
        parent = locked_parent
        content_parent = locked_content_parent
        session = locked_session
        next_turn_index = max(
            (int(session_job.turn_index or 0) for session_job in session_jobs),
            default=0,
        ) + 1

        now = datetime.now()
        job_id = str(uuid.uuid4())
        content_has_document_lineage = request_model.source.type in {
            'local_snapshot', 'cloud_document',
        }
        source_mindmap_id = (
            request_model.source.mindmap_id
            if request_model.source.type == 'cloud_document'
            else None
        )
        base_revision = (
            request_model.source.revision
            if content_has_document_lineage and request_model.source.revision is not None
            else (content_parent.base_revision if content_has_document_lineage else None)
        )
        base_hash = (
            request_model.source.document_hash
            if content_has_document_lineage and request_model.source.document_hash
            else (content_parent.base_hash if content_has_document_lineage else None)
        )
        base_room_epoch = (
            request_model.source.room_epoch
            if request_model.source.type == 'cloud_document'
            else None
        )
        try:
            job = await MindmapAiDao.add_job(db, {
                'id': job_id,
                'user_id': user_id,
                'session_id': parent.session_id,
                'parent_job_id': parent.id,
                'turn_index': next_turn_index,
                **runtime_values,
                'source_mindmap_id': source_mindmap_id,
                'base_revision': base_revision,
                'base_hash': base_hash,
                'base_room_epoch': base_room_epoch,
                'request_json': _json_dumps(_request_with_undo_baseline(
                    request_model.model_dump(by_alias=True, exclude_none=True), undo_baseline,
                )),
                'request_fingerprint': fingerprint,
                'idempotency_key': idempotency_key,
                'status': 'queued',
                'progress': 0,
                'expires_time': now + timedelta(days=policy.retention_days),
                'created_time': now,
                'update_time': now,
            })
            await MindmapAiDao.add_event(db, job_id, 'job_created', _event_json({
                'status': 'queued',
                'progress': 0,
                'agentKey': manifest.agent_key,
                'parentJobId': parent.id,
                'turnIndex': job.turn_index,
                'intent': request_model.intent,
                'sourceType': request_model.source.type,
                'sessionMode': (
                    'new'
                    if needs_input_followup
                    else (
                        'mode_switch'
                        if (
                            request_model.intent != parent.intent
                            or request_model.target != parent.target
                        )
                        else 'lineage'
                    )
                ),
                'continuationBase': model.continuation_base,
                'route': model.route,
            }))
            await MindmapAiDao.update_session(db, parent.session_id, {
                'current_agent_key': manifest.agent_key,
                'expires_time': max(
                    session.expires_time,
                    now + timedelta(days=policy.retention_days),
                ),
            })
            await db.commit()
        except IntegrityError:
            await db.rollback()
            replay = await MindmapAiDao.get_job_by_idempotency(db, user_id, idempotency_key)
            if replay is None or replay.request_fingerprint != fingerprint:
                raise ServiceException(message='AI 脑图继续任务创建冲突，请重试') from None
            cls._schedule_replayed_job(replay)
            return _job_model(replay)
        record_mindmap_ai_event('job_created')
        MindmapAiTaskManager.schedule(job_id)
        return _job_model(job)

    @classmethod
    async def get_job(cls, db: AsyncSession, job_id: str, user_id: int) -> MindmapAiJobModel:
        job = await MindmapAiDao.get_job(db, job_id, user_id)
        if job is None:
            raise ServiceException(message='AI 脑图任务不存在')
        return _job_model(job)

    @classmethod
    async def get_response(
        cls,
        db: AsyncSession,
        response_id: str,
        user_id: int,
    ) -> MindmapAiResponseModel:
        response = await MindmapAiDao.get_response(db, response_id, user_id)
        if response is None or response.expires_time <= datetime.now():
            raise ServiceException(message='AI 讨论答复不存在或已过期')
        return MindmapAiResponseModel(
            id=response.id,
            jobId=response.job_id,
            content=response.content_text,
            contentType=response.content_type,
            createdTime=response.created_time,
            expiresTime=response.expires_time,
        )

    @classmethod
    async def list_sessions(
        cls,
        db: AsyncSession,
        user_id: int,
        *,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        sessions, total = await MindmapAiDao.list_sessions(
            db,
            user_id,
            page=page,
            limit=limit,
        )
        session_ids = [str(session.id) for session in sessions]
        current_jobs = await MindmapAiDao.list_latest_jobs_for_sessions(db, session_ids)
        turn_counts = await MindmapAiDao.count_turns_for_sessions(db, session_ids)
        mindmap_names: dict[int, str] = {}
        mindmap_access: dict[int, bool] = {}
        for current_job in current_jobs.values():
            source_mindmap_id = getattr(current_job, 'source_mindmap_id', None)
            if source_mindmap_id is None:
                continue
            try:
                mindmap = await MindmapService.check_mindmap_access(
                    db,
                    int(source_mindmap_id),
                    user_id,
                    require_edit=False,
                )
            except ServiceException:
                # A revoked document remains visible as a redacted task entry;
                # do not leak its old title or turn details through the task center.
                mindmap_access[int(source_mindmap_id)] = False
                continue
            normalized_mindmap_id = int(source_mindmap_id)
            mindmap_access[normalized_mindmap_id] = True
            mindmap_names[normalized_mindmap_id] = str(mindmap.name or '').strip()
        items: list[dict[str, Any]] = []
        for session in sessions:
            current_job = current_jobs.get(str(session.id))
            source_mindmap_id = getattr(current_job, 'source_mindmap_id', None)
            accessible = (
                mindmap_access.get(int(source_mindmap_id), False)
                if source_mindmap_id is not None
                else None
            )
            safe_session_title = session.title
            safe_job = (
                _job_model(current_job).model_dump(by_alias=True)
                if current_job is not None
                else None
            )
            if source_mindmap_id is not None and not accessible:
                # A task remains discoverable so the user can understand that
                # work exists, but a revoked document must not leak prompt,
                # generated title, provider error detail, or usage metadata.
                safe_session_title = '已隐藏的脑图任务'
                if safe_job is not None:
                    safe_job['title'] = None
                    safe_job['errorMessage'] = None
                    safe_job['usage'] = None
            items.append({
                'sessionId': session.id,
                'title': safe_session_title,
                'status': session.status,
                'currentAgentKey': session.current_agent_key,
                'mindmapName': (
                    mindmap_names.get(int(source_mindmap_id))
                    if source_mindmap_id is not None
                    else None
                ),
                'mindmapAccessible': accessible,
                'currentJob': safe_job,
                'turnCount': turn_counts.get(str(session.id), 0),
                'updateTime': session.update_time,
                'expiresTime': session.expires_time,
            })
        return {
            'items': items,
            'total': total,
            'page': page,
            'limit': limit,
        }

    @classmethod
    async def reconcile_job_attempt(
        cls,
        db: AsyncSession,
        user_id: int,
        idempotency_key: str,
    ) -> MindmapAiJobModel | None:
        """Resolve a response-loss window without replaying the original body.

        ``user_id`` is part of the database predicate, so possession of another
        user's key never grants access. A queued result is scheduled just like an
        ordinary idempotent POST replay, covering a process crash between commit
        and the original in-process scheduling call.
        """
        job = await MindmapAiDao.get_job_by_idempotency(
            db,
            user_id,
            idempotency_key,
        )
        if job is None:
            return None
        cls._schedule_replayed_job(job)
        return _job_model(job)

    @classmethod
    async def get_session_timeline(
        cls,
        db: AsyncSession,
        session_id: str,
        user_id: int,
    ) -> dict[str, Any]:
        """返回用户可见的交互与审计事件，不返回供应商隐藏推理或完整输入文档。"""
        session = await MindmapAiDao.get_session(db, session_id, user_id)
        if session is None:
            raise ServiceException(message='AI 脑图会话不存在')
        turns: list[dict[str, Any]] = []
        jobs = await MindmapAiDao.list_jobs_for_session(db, session_id)
        response_job_ids = [
            str(job.id) for job in jobs if getattr(job, 'response_id', None)
        ]
        responses = (
            await MindmapAiDao.get_responses_for_jobs(db, response_job_ids, user_id)
            if response_job_ids
            else {}
        )
        now = datetime.now()
        for job in jobs:
            request_payload = _json_loads(job.request_json, {})
            prompt = request_payload.get('prompt') if isinstance(request_payload, dict) else None
            visible_events: list[dict[str, Any]] = []
            seen_agent_envelopes: set[str] = set()
            event_cursor = 0
            while True:
                event_page = await MindmapAiDao.list_events(
                    db,
                    job.id,
                    event_cursor,
                    limit=AI_TIMELINE_EVENT_PAGE_SIZE,
                )
                if not event_page:
                    break
                for event in event_page:
                    safe_payload = sanitize_mindmap_ai_event_payload(
                        _json_loads(event.payload_json, {}),
                    )
                    # 旧版 Claude 兼容网关曾为同一个逻辑消息重复持久化上千个
                    # agent_event 信封。历史读取时只折叠完全相同的通用信封；
                    # 工具、草稿、状态、错误及结果事件全部按原顺序保留。
                    if event.event_type == 'agent_event':
                        envelope_key = _json_dumps(safe_payload)
                        if envelope_key in seen_agent_envelopes:
                            continue
                        seen_agent_envelopes.add(envelope_key)
                    visible_events.append({
                        'sequence': event.sequence,
                        'eventType': event.event_type,
                        'payload': safe_payload,
                        'createdTime': event.created_time,
                    })
                next_cursor = int(event_page[-1].sequence)
                if (
                    len(event_page) < AI_TIMELINE_EVENT_PAGE_SIZE
                    or next_cursor <= event_cursor
                ):
                    break
                event_cursor = next_cursor
            response = responses.get(str(job.id))
            assistant_message = (
                {
                    'content': response.content_text,
                    'contentType': response.content_type,
                    'createdTime': response.created_time,
                }
                if response is not None and response.expires_time > now
                else None
            )
            turns.append({
                'job': _job_model(job).model_dump(by_alias=True),
                'userMessage': ({
                    'content': str(prompt)[:20_000],
                    'createdTime': job.created_time,
                } if isinstance(prompt, str) and prompt else None),
                'assistantMessage': assistant_message,
                'events': visible_events,
            })
        return {
            'sessionId': session.id,
            'title': session.title,
            'status': session.status,
            'currentAgentKey': session.current_agent_key,
            'createdTime': session.created_time,
            'updateTime': session.update_time,
            'expiresTime': session.expires_time,
            'turns': turns,
        }

    @classmethod
    async def delete_session(
        cls,
        db: AsyncSession,
        session_id: str,
        user_id: int,
    ) -> dict[str, Any]:
        """删除用户自己的整段 AI 会话，并跨 worker 终止仍在执行的 Agent。"""
        session = await MindmapAiDao.get_session(
            db,
            session_id,
            user_id,
            for_update=True,
        )
        if session is None:
            raise ServiceException(message='AI 脑图会话不存在')

        # Tombstone the session in a session-only transaction. Completion and
        # follow-up paths that subsequently acquire this row must fail closed.
        # Do not acquire job rows before committing: result completion uses the
        # global job -> session lock order.
        if getattr(session, 'status', None) != 'deleting':
            await MindmapAiDao.update_session(db, session_id, {'status': 'deleting'})
        await db.commit()

        # Cancellation is durable before any process-local best effort. Other
        # workers observe this state from their polling/lease recovery paths.
        try:
            await MindmapAiDao.request_session_job_cancellations(
                db,
                session_id,
                datetime.now(),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        jobs = await MindmapAiDao.list_jobs_for_session(db, session_id)
        adapter_session_references = _collect_adapter_session_references(
            jobs,
            strict=True,
        )
        for job in jobs:
            if job.status not in ACTIVE_JOB_STATUSES:
                continue
            try:
                await MindmapAiTaskManager.cancel(job.id, job.agent_key)
            except Exception:
                logger.warning(f'删除 AI 会话时终止 Agent 失败，将继续移除持久化数据: job_id={job.id}')

        job_ids = [str(job.id) for job in jobs]
        execution_epochs = {
            str(job.id): int(getattr(job, 'execution_epoch', 0) or 0)
            for job in jobs
        }
        purged_sdk_sessions, _purge_failures = await _purge_adapter_session_references(
            adapter_session_references,
            strict=True,
        )
        try:
            # delete_session_cascade locks jobs in stable order before deleting
            # the session, matching the completion path's job -> session order.
            counts = await MindmapAiDao.delete_session_cascade(db, session_id, job_ids)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        for job_id in job_ids:
            await MindmapAiTaskManager.mark_draft_terminal(
                job_id,
                execution_epochs[job_id],
            )
        return {
            'sessionId': session_id,
            # A concurrent idempotent delete may have removed the tombstone
            # after ownership was verified; the requested end state still holds.
            'deleted': True,
            'jobCount': counts['jobs'],
            'sdkSessionCount': purged_sdk_sessions,
        }

    @classmethod
    async def get_job_draft_preview(  # noqa: PLR0912
        cls,
        db: AsyncSession,
        job_id: str,
        user_id: int,
        version: int | None = None,
    ) -> dict[str, Any]:
        # This endpoint must be linearizable with completion/cancellation.  A
        # plain read followed by a checkpoint/cache read has a TOCTOU window:
        # PostgreSQL can observe the committed checkpoint deletion and then
        # fall back to Redis, while MySQL REPEATABLE READ can retain the old
        # checkpoint snapshot.  Every terminal writer already locks the job
        # row first, so keep the current-read lock for the complete preview
        # decision (including Redis compatibility reads/refills).  Whichever
        # side acquires the row first is authoritative for this request.
        job = await MindmapAiDao.get_job(
            db,
            job_id,
            user_id,
            for_update=True,
        )
        if job is None:
            raise ServiceException(message='AI 脑图任务不存在')
        if job.status in TERMINAL_JOB_STATUSES:
            response = {
                'available': False,
                'jobId': job_id,
                'status': job.status,
                'progress': job.progress,
            }
            if version is not None:
                response['requestedVersion'] = version
            return response
        checkpoint = await MindmapAiDao.get_draft_checkpoint(db, job_id)
        preview: dict[str, Any] | None = None
        if checkpoint is None:
            # Compatibility for jobs created before durable checkpoints existed.
            preview = await MindmapAiTaskManager.get_draft_preview(job_id, version)
        else:
            try:
                checkpoint_version = int(checkpoint.preview_version)
            except (TypeError, ValueError):
                checkpoint_version = -1
            historical_redis_version = (
                version is not None
                and 0 <= int(version) < checkpoint_version
            )
            if historical_redis_version:
                # The durable row only stores the newest frame. Redis may still
                # carry an exact, older short-lived frame for SSE replay.
                preview = await MindmapAiTaskManager.get_draft_preview(job_id, version)
            else:
                durable_preview = MindmapAiTaskManager._draft_checkpoint_preview(
                    checkpoint,
                    expected_version=version,
                )
                if durable_preview is not None:
                    # A present durable row is authoritative. Authentication,
                    # expiry, JSON, hash, or requested-version failures never
                    # fall through to an unauthenticated Redis latest frame.
                    preview = durable_preview
                    cached_preview = await MindmapAiTaskManager.get_draft_preview(
                        job_id,
                        version,
                    )
                    durable_coordinates = (
                        int(durable_preview['previewEpoch']),
                        int(durable_preview['operationCursor']),
                    )
                    try:
                        cached_coordinates = (
                            int(cached_preview.get('previewEpoch') or 1),
                            int(cached_preview.get('operationCursor') or 0),
                        ) if cached_preview is not None else None
                    except (TypeError, ValueError):
                        cached_coordinates = None
                    cached_hash = (
                        str(cached_preview.get('documentHash') or '')
                        if cached_preview is not None
                        else ''
                    )
                    if (
                        cached_coordinates != durable_coordinates
                        or cached_hash != str(checkpoint.document_hash)
                    ):
                        execution_epoch = int(getattr(job, 'execution_epoch', 0) or 0)
                        if execution_epoch >= 1:
                            await MindmapAiTaskManager._publish_execution_epoch(
                                job_id,
                                execution_epoch,
                            )
                            await MindmapAiTaskManager._store_draft_preview(
                                job_id,
                                durable_preview['document'],
                                operation_cursor=int(durable_preview['operationCursor']),
                                expected_execution_epoch=execution_epoch,
                                preview_epoch=int(durable_preview['previewEpoch']),
                                summary=durable_preview.get('summary'),
                            )
        if preview is None:
            response = {
                'available': False,
                'jobId': job_id,
                'status': job.status,
                'progress': job.progress,
            }
            if version is not None:
                response['requestedVersion'] = version
            return response
        try:
            document, summary = normalize_ai_editable_source_document(
                preview['document'],
            )
        except MindmapArtifactError:
            return {
                'available': False,
                'jobId': job_id,
                'status': job.status,
                'progress': job.progress,
            }
        return {
            'available': True,
            'jobId': job_id,
            'status': job.status,
            'progress': job.progress,
            'operationCursor': int(preview.get('operationCursor') or 0),
            'previewEpoch': int(preview.get('previewEpoch') or 1),
            'document': document,
            'summary': summary,
            'updatedTime': preview.get('updatedTime'),
        }

    @classmethod
    async def _promote_draft_checkpoint_for_stop(
        cls,
        db: AsyncSession,
        job: Any,
    ) -> bool:
        """Promote a live checkpoint into a normal undoable AI result."""
        if (
            job is None
            or job.status not in ACTIVE_JOB_STATUSES
            or _json_loads(getattr(job, 'request_json', None), {}).get(
                'executionMode', 'preview',
            ) == 'direct'
            or job.target != 'proposal'
            or job.intent == 'discuss'
            or job.source_type not in {'local_snapshot', 'cloud_document'}
        ):
            return False
        checkpoint = await MindmapAiDao.get_draft_checkpoint(
            db,
            str(job.id),
            for_update=True,
        )
        preview = MindmapAiTaskManager._draft_checkpoint_preview(checkpoint)
        if preview is None or not isinstance(preview.get('document'), dict):
            return False
        request_model = MindmapAiJobCreateModel.model_validate(
            _json_loads(getattr(job, 'request_json', None), {}),
        )
        baseline_document = (
            request_model.source.baseline_document
            or request_model.source.document
        )
        if not isinstance(baseline_document, dict):
            return False
        # For an existing map max_nodes limits this turn's additions, not the
        # total size of the already authorized source document.
        max_node_count = AI_MAX_NODE_COUNT
        artifact_id = str(uuid.uuid4())
        artifact, summary = build_smm_artifact(
            _restore_preview_document(request_model, preview['document']),
            title=job.title or _initial_session_title(request_model.prompt),
            agent_key=job.agent_key,
            adapter_version=job.adapter_version,
            prompt_version='mindmap-ai-v2-stop-checkpoint',
            artifact_id=artifact_id,
            preserve_source_content=True,
            max_node_count=max_node_count,
        )
        artifact, summary = _validate_job_result_artifact(
            artifact,
            max_node_count=max_node_count,
            expected_artifact_id=artifact_id,
            expected_agent_key=job.agent_key,
            expected_adapter_version=getattr(job, 'adapter_version', None),
        )
        proposal_operations, impact = build_document_diff(
            baseline_document,
            artifact['document'],
        )
        if not proposal_operations:
            return False
        result_status = 'needs_review' if impact.get('highImpact') else 'ready'
        local_proposal = job.source_type == 'local_snapshot' and job.source_mindmap_id is None
        cloud_proposal = job.source_type == 'cloud_document' and job.source_mindmap_id is not None
        if not local_proposal and not cloud_proposal:
            return False
        now = datetime.now()
        expires = getattr(job, 'expires_time', None) or now + timedelta(
            days=int(getattr(
                job,
                'retention_days',
                MindmapAiConfig.mindmap_ai_artifact_retention_days,
            )),
        )
        proposal_id = str(uuid.uuid4())
        await MindmapAiDao.add_artifact(db, {
            'id': artifact_id,
            'job_id': job.id,
            'user_id': job.user_id,
            'title': artifact['manifest']['title'],
            'content_json': _json_dumps(artifact),
            'document_hash': artifact['manifest']['documentHash'],
            'validation_status': 'passed',
            'validator_version': 'mindmap-validator-2',
            'node_count': summary['nodeCount'],
            'tree_depth': summary['treeDepth'],
            'byte_size': len(canonical_json_bytes(artifact)),
            'created_time': now,
            'expires_time': expires,
        })
        await MindmapAiDao.add_proposal(db, {
            'id': proposal_id,
            'job_id': job.id,
            'user_id': job.user_id,
            'proposal_type': 'patch',
            'base_document_id': request_model.source.document_id if local_proposal else None,
            'target_mindmap_id': job.source_mindmap_id if cloud_proposal else None,
            'base_revision': job.base_revision,
            'base_hash': job.base_hash,
            'base_room_epoch': job.base_room_epoch,
            'scope_json': _json_dumps(
                request_model.source.scope.model_dump(by_alias=True),
            ),
            'operations_json': _json_dumps(proposal_operations),
            'result_artifact_id': artifact_id,
            'result_hash': artifact['manifest']['documentHash'],
            'impact_json': _json_dumps(impact),
            'warnings_json': _json_dumps([]),
            'status': result_status,
            'created_time': now,
            'expires_time': expires,
        })
        await MindmapAiDao.update_job(db, job.id, {
            'status': result_status,
            'progress': 100,
            'title': artifact['manifest']['title'],
            'artifact_id': artifact_id,
            'proposal_id': proposal_id,
            'completed_time': now,
            'error_code': None,
            'error_message': None,
        })
        session = await MindmapAiDao.get_session(db, job.session_id, for_update=True)
        if session is not None:
            await MindmapAiDao.update_session(db, job.session_id, {
                'current_agent_key': job.agent_key,
                'title': artifact['manifest']['title'],
                'latest_artifact_id': artifact_id,
                'status': 'active',
                'expires_time': max(session.expires_time or expires, expires),
            })
        await MindmapAiDao.add_event(
            db,
            job.id,
            'artifact_needs_review' if result_status == 'needs_review' else 'artifact_ready',
            _event_json({
                'status': result_status,
                'progress': 100,
                'artifactId': artifact_id,
                'proposalId': proposal_id,
                'summary': summary,
                'issueCount': 0,
                'completionReason': 'stopped',
            }),
        )
        await MindmapAiDao.delete_draft_checkpoint(db, str(job.id))
        return True

    @classmethod
    async def cancel_job(  # noqa: PLR0912
        cls,
        db: AsyncSession,
        job_id: str,
        user_id: int,
        *,
        preserve_draft: bool = False,
    ) -> MindmapAiJobModel:
        job = await MindmapAiDao.get_job(db, job_id, user_id, for_update=True)
        if job is None:
            raise ServiceException(message='AI 脑图任务不存在')
        if job.status in TERMINAL_JOB_STATUSES:
            # The read uses FOR UPDATE so that a concurrent cancellation
            # cannot change the status while this endpoint decides whether to
            # close or release queued children.  Materialize the response and
            # end that transaction before calling either helper: both helpers
            # open a second session and lock the same parent row.
            terminal_status = str(job.status)
            result = _job_model(job)
            await db.rollback()
            if terminal_status in {'cancelled', 'failed', 'expired', 'stale', 'rejected'}:
                await MindmapAiTaskManager._close_waiting_followups(
                    job_id,
                    parent_status=terminal_status,
                )
            else:
                await MindmapAiTaskManager._wake_waiting_followups(job_id)
            return result
        if preserve_draft:
            try:
                promoted = await cls._promote_draft_checkpoint_for_stop(db, job)
            except Exception:
                await db.rollback()
                logger.exception(
                    f'AI 停止时提升实时草稿失败，将回退为普通取消: job_id={job_id}'
                )
                job = await MindmapAiDao.get_job(db, job_id, user_id, for_update=True)
                if job is None:
                    raise ServiceException(message='AI 脑图任务不存在') from None
                promoted = False
            if promoted:
                await db.commit()
                execution_epoch = int(getattr(job, 'execution_epoch', 0) or 0)
                await MindmapAiTaskManager.mark_draft_terminal(
                    job_id,
                    execution_epoch,
                )
                await MindmapAiTaskManager.cancel(job_id, job.agent_key)
                await MindmapAiTaskManager._wake_waiting_followups(job_id)
                refreshed = await MindmapAiDao.get_job(db, job_id, user_id)
                return _job_model(refreshed or job)
        now = datetime.now()
        if job.status != 'cancel_requested':
            await MindmapAiDao.update_job(db, job_id, {
                'status': 'cancel_requested',
                'cancel_requested_time': now,
            })
            await MindmapAiDao.add_event(
                db, job_id, 'cancel_requested', _event_json({'status': 'cancel_requested'}),
            )
        changed = await MindmapAiDao.transition_job_status(
            db,
            job_id,
            frozenset({'cancel_requested'}),
            {
                'status': 'cancelled',
                'progress': 100,
                'error_code': 'AI_TASK_CANCELLED',
                'error_message': '任务已取消',
                'completed_time': now,
            },
        )
        if changed:
            # The terminal status and removal of its durable plaintext source
            # commit together. Redis is fenced only after this transaction is
            # durable, so a failed commit cannot hide a still-running draft.
            await MindmapAiDao.delete_draft_checkpoint(db, job_id)
            await MindmapAiDao.add_event(
                db,
                job_id,
                'status_changed',
                _event_json({'status': 'cancelled', 'progress': 100}),
            )
        await db.commit()
        execution_epoch = int(getattr(job, 'execution_epoch', 0) or 0)
        if changed:
            await MindmapAiTaskManager.mark_draft_terminal(
                job_id,
                execution_epoch,
            )
        await MindmapAiTaskManager.cancel(job_id, job.agent_key)
        refreshed = await MindmapAiDao.get_job(db, job_id, user_id)
        effective_job = refreshed or job
        if effective_job.status == 'cancelled':
            await MindmapAiTaskManager._close_waiting_followups(
                job_id,
                parent_status='cancelled',
            )
        elif effective_job.status in {
            'ready', 'completed_file', 'completed_no_change', 'completed_direct',
            'needs_review', 'completed_message',
        }:
            # A worker may have completed the parent between the cancel CAS
            # and the local task fence. Its queued child must use that durable
            # result rather than being closed as if cancellation had won.
            await MindmapAiTaskManager._wake_waiting_followups(job_id)
        return _job_model(effective_job)

    @classmethod
    async def get_artifact(
        cls,
        db: AsyncSession,
        artifact_id: str,
        user_id: int,
    ) -> tuple[Any, dict[str, Any]]:
        artifact = await MindmapAiDao.get_artifact(db, artifact_id, user_id)
        if artifact is None:
            raise ServiceException(message='AI 脑图文件不存在或已过期')
        if artifact.expires_time <= datetime.now():
            raise ServiceException(message='AI 脑图文件已过期')
        content = _json_loads(artifact.content_json)
        if not isinstance(content, dict):
            raise ServiceException(message='AI 脑图文件损坏')
        artifact_job = await MindmapAiDao.get_job(db, artifact.job_id, user_id)
        if artifact_job is None:
            raise ServiceException(message='AI 脑图文件损坏')
        try:
            validated, _summary = validate_smm_artifact(
                content,
                require_passed=False,
                max_node_count=AI_MAX_NODE_COUNT,
            )
        except MindmapArtifactError as exc:
            raise ServiceException(message='AI 脑图文件损坏') from exc
        return artifact, validated

    @classmethod
    async def reject_proposal(
        cls,
        db: AsyncSession,
        proposal_id: str,
        user_id: int,
    ) -> MindmapAiJobModel:
        """Record an explicit rejection before a review proposal is applied.

        The canvas preview is client-local, so rejecting it must still have a
        durable server result.  This endpoint is intentionally separate from
        task cancellation: a completed high-impact proposal is a user decision
        and its queued descendants must be closed against the rejected base.
        """
        proposal = await MindmapAiDao.get_proposal(
            db,
            proposal_id,
            user_id,
            for_update=True,
        )
        if proposal is None:
            raise ServiceException(
                data={'errorCode': 'AI_PROPOSAL_NOT_FOUND'},
                message='AI 脑图提案不存在或当前账号无权访问',
            )
        job = await MindmapAiDao.get_job(
            db,
            proposal.job_id,
            user_id,
            for_update=True,
        )
        if job is None or str(getattr(job, 'proposal_id', '')) != str(proposal_id):
            raise ServiceException(
                data={'errorCode': PROPOSAL_INTEGRITY_ERROR_CODE},
                message='AI 提案与任务关联不一致，已阻止拒绝操作',
            )
        job_id = str(proposal.job_id)
        if proposal.status == 'rejected' or job.status == 'rejected':
            return _job_model(job)
        if proposal.status in {'applied', 'undone'} or job.status in {'applied', 'undone'}:
            # A late reject click must never rewrite a committed result.  The
            # caller can reconcile the already authoritative terminal state.
            return _job_model(job)
        if proposal.status == 'prepared' or job.status not in {'ready', 'needs_review'}:
            raise ServiceException(
                data={'errorCode': 'AI_PROPOSAL_STATE_INVALID'},
                message='AI 提案已经进入应用流程，暂不能拒绝；请刷新查看最新状态',
            )
        now = datetime.now()
        await MindmapAiDao.update_proposal(db, proposal_id, {'status': 'rejected'})
        await MindmapAiDao.update_job(db, job_id, {
            'status': 'rejected',
            'progress': 100,
            'completed_time': now,
            'error_code': None,
            'error_message': None,
        })
        await MindmapAiDao.delete_draft_checkpoint(db, job_id)
        await MindmapAiDao.add_event(
            db,
            job_id,
            'proposal_rejected',
            _event_json({
                'status': 'rejected',
                'progress': 100,
                'proposalId': proposal.id,
                'completionReason': 'user_rejected',
            }),
        )
        await db.commit()
        await MindmapAiTaskManager._close_waiting_followups(
            job_id,
            parent_status='rejected',
        )
        record_mindmap_ai_event('proposal_rejected')
        refreshed = await MindmapAiDao.get_job(db, job_id, user_id)
        return _job_model(refreshed or job)

    @classmethod
    async def prepare_local_apply(
        cls,
        db: AsyncSession,
        proposal_id: str,
        user_id: int,
    ) -> dict[str, Any]:
        proposal = await MindmapAiDao.get_proposal(db, proposal_id, user_id)
        if proposal is None:
            raise ServiceException(message='AI 脑图提案不存在或不可应用')
        if (
            getattr(proposal, 'target_mindmap_id', None) is not None
            or not proposal.base_document_id
        ):
            raise ServiceException(message='AI 脑图提案不是本地应用提案')
        operations = _json_loads(getattr(proposal, 'operations_json', None), None)
        if proposal.status not in {'ready', 'prepared'} and not (
            proposal.status == 'needs_review' and _is_high_impact_proposal(proposal)
        ):
            raise ServiceException(message='AI 脑图提案不存在或不可应用')
        if proposal.expires_time <= datetime.now():
            raise ServiceException(message='AI 脑图提案已过期')
        try:
            job = await MindmapAiDao.get_job(db, proposal.job_id, user_id)
            if (
                job is None
                or str(getattr(job, 'id', '')) != str(proposal.job_id)
                or getattr(job, 'source_type', None) != 'local_snapshot'
                or getattr(job, 'target', None) != 'proposal'
            ):
                raise MindmapArtifactError(
                    'Proposal 与任务来源不一致',
                    code=PROPOSAL_INTEGRITY_ERROR_CODE,
                )
            request_model = MindmapAiJobCreateModel.model_validate(
                _json_loads(getattr(job, 'request_json', None), {}),
            )
            source = request_model.source
            if (
                source.type != 'local_snapshot'
                or source.document_id != proposal.base_document_id
                or source.revision != proposal.base_revision
                or getattr(job, 'base_revision', None) != proposal.base_revision
                or getattr(job, 'base_hash', None) != proposal.base_hash
            ):
                raise MindmapArtifactError(
                    'Proposal 基线身份不一致',
                    code=PROPOSAL_INTEGRITY_ERROR_CODE,
                )
            base_document = source.baseline_document or source.document
            if not isinstance(base_document, dict):
                raise MindmapArtifactError(
                    'Proposal 缺少冻结基线',
                    code=PROPOSAL_INTEGRITY_ERROR_CODE,
                )
            max_node_count = AI_MAX_NODE_COUNT
            base_document, _summary = normalize_ai_editable_source_document(
                base_document,
                max_node_count=max_node_count,
            )
            if (
                not isinstance(proposal.base_hash, str)
                or compute_document_hash(base_document) != proposal.base_hash
                or source.document_hash != proposal.base_hash
            ):
                raise MindmapArtifactError(
                    'Proposal 基线哈希不一致',
                    code=PROPOSAL_INTEGRITY_ERROR_CODE,
                )

            artifact_record, artifact = await cls.get_artifact(
                db,
                proposal.result_artifact_id,
                user_id,
            )
            manifest = artifact.get('manifest')
            artifact_document = artifact.get('document')
            if (
                str(getattr(artifact_record, 'job_id', '')) != str(proposal.job_id)
                or getattr(artifact_record, 'document_hash', None) != proposal.result_hash
                or getattr(job, 'artifact_id', None) != proposal.result_artifact_id
                or not isinstance(manifest, dict)
                or not isinstance(artifact_document, dict)
                or not isinstance(operations, list)
            ):
                raise MindmapArtifactError(
                    'Proposal 与 Artifact 关联不一致',
                    code=PROPOSAL_INTEGRITY_ERROR_CODE,
                )
            operations = normalize_proposal_operations_for_apply(
                base_document=base_document,
                operations=operations,
                artifact_document=artifact_document,
                max_node_count=max_node_count,
            )
            verify_proposal_document_integrity(
                base_document=base_document,
                operations=operations,
                artifact_document=artifact_document,
                proposal_result_hash=proposal.result_hash,
                manifest_document_hash=manifest.get('documentHash'),
                max_node_count=max_node_count,
            )
        except (
            KeyError,
            IndexError,
            MindmapArtifactError,
            ServiceException,
            TypeError,
            ValueError,
        ) as exc:
            logger.warning(
                'AI 本地 Proposal 完整性校验失败: '
                f'proposal_id={str(proposal_id)[:36]}, reason={str(exc)[:200]}'
            )
            raise _proposal_integrity_service_exception(exc) from exc
        await MindmapAiDao.update_proposal(db, proposal_id, {'status': 'prepared'})
        await db.commit()
        return {
            'proposalId': proposal.id,
            'proposalType': proposal.proposal_type,
            'baseDocumentId': proposal.base_document_id,
            'baseRevision': proposal.base_revision,
            'baseHash': proposal.base_hash,
            'baseRoomEpoch': proposal.base_room_epoch,
            'resultHash': proposal.result_hash,
            'scope': _json_loads(proposal.scope_json, {}),
            'operations': operations,
            'impact': _json_loads(proposal.impact_json, {}),
            'warnings': _json_loads(proposal.warnings_json, []),
            'artifact': artifact,
        }

    @classmethod
    async def get_proposal(
        cls,
        db: AsyncSession,
        proposal_id: str,
        user_id: int,
    ) -> MindmapAiProposalModel:
        proposal = await MindmapAiDao.get_proposal(db, proposal_id, user_id)
        if proposal is None:
            # Direct-write rounds use the task id as a durable undo receipt
            # rather than creating a preview Proposal.  Expose the same read
            # shape to task-center clients so they can render the undo action
            # without weakening the normal Proposal integrity checks.
            direct_job = await MindmapAiDao.get_job(db, proposal_id, user_id)
            direct_request = _json_loads(
                getattr(direct_job, 'request_json', None),
            ) if direct_job is not None else {}
            if not (
                direct_job is not None
                and direct_job.proposal_id == proposal_id
                and direct_request.get('executionMode') == 'direct'
                and direct_job.source_type == 'cloud_document'
            ):
                raise ServiceException(message='AI 脑图提案不存在')
            undo = await MindmapAiDao.get_undo(db, proposal_id, user_id)
            if undo is None:
                raise ServiceException(message='AI 脑图撤销记录不存在')
            source = direct_request.get('source') or {}
            change_result = await _direct_job_change_result(db, direct_job)
            change_summary = change_result['changeSummary']
            direct_impact = {
                'direct': True,
                'changeSummary': change_summary,
                'changeSummaryVersion': change_result['changeSummaryVersion'],
                # Keep Proposal's established impact names so existing UI
                # components render direct rounds exactly like file results.
                'createdCount': change_summary['added'],
                'updatedCount': change_summary['updated'],
                'movedCount': change_summary['moved'],
                'deletedCount': change_summary['deleted'],
                'operationCount': change_summary['total'],
            }
            return MindmapAiProposalModel(
                id=proposal_id,
                jobId=direct_job.id,
                proposalType='direct',
                baseDocumentId=None,
                targetMindmapId=direct_job.source_mindmap_id,
                baseRevision=direct_job.base_revision,
                baseHash=direct_job.base_hash,
                baseRoomEpoch=direct_job.base_room_epoch,
                scope=source.get('scope') if isinstance(source, dict) else {},
                operations=[],
                resultArtifactId='',
                resultHash=undo.applied_hash,
                impact=direct_impact,
                warnings=[],
                status=(
                    'blocked' if undo.status == 'available' and _raw_direct_undo_baseline(direct_job) is None
                    else 'applied' if undo.status == 'available' else undo.status
                ),
                appliedRevision=undo.applied_revision,
                createdTime=undo.created_time,
                expiresTime=undo.expires_time,
            )
        if (
            proposal.expires_time <= datetime.now()
            and proposal.status not in {'applied', 'undone', 'rejected', 'expired'}
        ):
            await MindmapAiDao.update_proposal(db, proposal_id, {'status': 'expired'})
            await db.commit()
            proposal.status = 'expired'
        return MindmapAiProposalModel(
            id=proposal.id,
            jobId=proposal.job_id,
            proposalType=proposal.proposal_type,
            baseDocumentId=proposal.base_document_id,
            targetMindmapId=proposal.target_mindmap_id,
            baseRevision=proposal.base_revision,
            baseHash=proposal.base_hash,
            baseRoomEpoch=proposal.base_room_epoch,
            scope=_json_loads(proposal.scope_json, {}),
            operations=_json_loads(proposal.operations_json, []),
            resultArtifactId=proposal.result_artifact_id,
            resultHash=proposal.result_hash,
            impact=_json_loads(proposal.impact_json, {}),
            warnings=_json_loads(proposal.warnings_json, []),
            status=proposal.status,
            appliedRevision=proposal.applied_revision,
            createdTime=proposal.created_time,
            expiresTime=proposal.expires_time,
        )

    @classmethod
    async def ack_local_apply(
        cls,
        db: AsyncSession,
        proposal_id: str,
        user_id: int,
        model: MindmapAiLocalApplyAckModel,
    ) -> dict[str, Any]:
        proposal = await MindmapAiDao.get_proposal(db, proposal_id, user_id, for_update=True)
        if proposal is None:
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_NOT_FOUND'},
                message='AI 脑图提案不存在',
            )
        if (
            getattr(proposal, 'target_mindmap_id', None) is not None
            or not proposal.base_document_id
        ):
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_TARGET_INVALID'},
                message='AI 脑图提案不是本地应用提案',
            )
        job_id = str(proposal.job_id)
        if proposal.status == 'applied':
            if (
                proposal.result_hash != model.result_hash
                or (
                    proposal.base_document_id
                    and proposal.base_document_id != model.document_id
                )
                or proposal.applied_revision != model.revision
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_LOCAL_ACK_CONFLICT'},
                    message='AI 脑图提案应用回执冲突',
                )
            return {'proposalId': proposal.id, 'status': 'applied', 'idempotentReplay': True}
        if proposal.status not in {'ready', 'prepared'}:
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_STATE_INVALID'},
                message='AI 脑图提案当前不可应用',
            )
        if proposal.base_document_id and proposal.base_document_id != model.document_id:
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_DOCUMENT_MISMATCH'},
                message='本地脑图文档与提案基线不一致',
            )
        if proposal.result_hash != model.result_hash:
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_RESULT_MISMATCH'},
                message='本地脑图应用结果哈希不一致',
            )
        now = datetime.now()
        applied_expires_time = max(
            proposal.expires_time,
            cls._applied_result_expiration(now),
        )
        await MindmapAiDao.update_proposal(db, proposal_id, {
            'status': 'applied',
            'applied_revision': model.revision,
            'applied_time': now,
        })
        await MindmapAiDao.update_job(db, job_id, {
            'status': 'applied',
            'progress': 100,
            'completed_time': now,
        })
        await MindmapAiDao.extend_result_expiration(
            db,
            job_id=proposal.job_id,
            artifact_id=proposal.result_artifact_id,
            proposal_id=proposal.id,
            expires_time=applied_expires_time,
        )
        await MindmapAiDao.add_event(
            db,
            job_id,
            'local_applied',
            _event_json({'proposalId': proposal.id, 'revision': model.revision}),
        )
        await db.commit()
        await MindmapAiTaskManager._wake_waiting_followups(job_id)
        record_mindmap_ai_event('local_applied')
        return {'proposalId': proposal.id, 'status': 'applied', 'idempotentReplay': False}

    @classmethod
    async def ack_local_undo(
        cls,
        db: AsyncSession,
        proposal_id: str,
        user_id: int,
        model: MindmapAiLocalUndoAckModel,
    ) -> dict[str, Any]:
        """Persist a browser-local atomic undo, including lost-apply-ACK recovery."""
        proposal = await MindmapAiDao.get_proposal(db, proposal_id, user_id, for_update=True)
        if proposal is None:
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_NOT_FOUND'},
                message='AI 脑图提案不存在',
            )
        if (
            getattr(proposal, 'target_mindmap_id', None) is not None
            or not proposal.base_document_id
        ):
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_TARGET_INVALID'},
                message='AI 脑图提案不是本地应用提案',
            )

        applied_revision = getattr(proposal, 'applied_revision', None)
        expected_applied_revision = (
            int(applied_revision)
            if applied_revision is not None
            else (
                int(proposal.base_revision) + 1
                if proposal.base_revision is not None
                else None
            )
        )
        receipt_matches = (
            proposal.base_document_id == model.document_id
            and proposal.result_hash == model.result_hash
            and proposal.base_hash == model.reverted_hash
            and expected_applied_revision is not None
            and model.revision == expected_applied_revision + 1
        )
        if not receipt_matches:
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_CONFLICT'},
                message='AI 脑图提案撤销回执冲突',
            )
        if proposal.status == 'undone':
            return {'proposalId': proposal.id, 'status': 'undone', 'idempotentReplay': True}
        # ``prepared`` covers the important response-loss ordering where the
        # local editor applied and undid the proposal before its apply ACK could
        # reach the server. Never replay either document mutation server-side.
        if proposal.status not in {'applied', 'prepared'}:
            raise ServiceException(
                data={'errorCode': 'AI_LOCAL_ACK_STATE_INVALID'},
                message='AI 脑图提案当前不可撤销',
            )

        now = datetime.now()
        proposal_values: dict[str, Any] = {'status': 'undone'}
        if applied_revision is None:
            proposal_values.update({
                'applied_revision': expected_applied_revision,
                'applied_time': now,
            })
        await MindmapAiDao.update_proposal(db, proposal_id, proposal_values)
        await MindmapAiDao.update_job(db, proposal.job_id, {
            'status': 'undone',
            'progress': 100,
            'completed_time': now,
        })
        await MindmapAiDao.add_event(
            db,
            proposal.job_id,
            'local_undone',
            _event_json({'proposalId': proposal.id, 'revision': model.revision}),
        )
        await db.commit()
        # A queued follow-up may depend on the post-undo document.  Wake it
        # only after the undo receipt is durable so it can freeze that exact
        # local revision instead of the pre-undo proposal base.
        await MindmapAiTaskManager._wake_waiting_followups(str(proposal.job_id))
        record_mindmap_ai_event('local_undone')
        return {'proposalId': proposal.id, 'status': 'undone', 'idempotentReplay': False}

    @classmethod
    async def save_artifact_cloud(
        cls,
        db: AsyncSession,
        artifact_id: str,
        user_id: int,
        user_name: str,
        model: MindmapAiCloudSaveModel,
        idempotency_key: str,
    ) -> dict[str, Any]:
        record, artifact = await cls.get_artifact(db, artifact_id, user_id)
        if record.validation_status != 'passed':
            raise ServiceException(message='未通过校验的草稿不能另存为正式云端脑图')
        document = artifact['document']
        now = datetime.now()
        resolved_name = model.name or record.title
        result = await MindmapService.add_mindmap_services(
            db,
            MindmapModel(
                name=resolved_name,
                ownerId=user_id,
                folderId=model.folder_id,
                layout=document['layout'],
                theme=document['theme'],
                nodeTree=document['root'],
                viewData=document['view'],
                documentData=document['documentData'],
                createBy=user_name,
                createTime=now,
                updateBy=user_name,
                updateTime=now,
            ),
            creation_request_id=idempotency_key,
            creation_operation='ai_import',
            creation_intent={
                'artifactId': artifact_id,
                'documentHash': record.document_hash,
                'name': resolved_name,
                'folderId': model.folder_id,
            },
        )
        await MindmapAiDao.update_job(db, record.job_id, {
            'status': 'completed_file',
            'progress': 100,
            'completed_time': now,
        })
        await MindmapAiDao.extend_result_expiration(
            db,
            job_id=record.job_id,
            artifact_id=artifact_id,
            expires_time=max(record.expires_time, cls._applied_result_expiration(now)),
        )
        await MindmapAiDao.add_event(
            db,
            record.job_id,
            'cloud_file_created',
            _event_json({'artifactId': artifact_id, 'mindmapId': result.result['id']}),
        )
        await db.commit()
        record_mindmap_ai_event('cloud_saved')
        return {**result.result, 'artifactId': artifact_id}

    @classmethod
    async def apply_cloud_proposal(  # noqa: PLR0912, PLR0915
        cls,
        db: AsyncSession,
        mindmap_id: int,
        proposal_id: str,
        user_id: int,
        user_name: str,
        model: MindmapAiCloudApplyModel,
        idempotency_key: str,
    ) -> dict[str, Any]:
        # 第一阶段只读解析身份和预期基线。等待浏览器排空可能持续数秒，绝不
        # 在这段时间持有 proposal 或 Mindmap 行锁，否则客户端自己的最终
        # HTTP 保存会和栅栏互相等待。
        force_overwrite = bool(model.force_overwrite)
        proposal = await MindmapAiDao.get_proposal(db, proposal_id, user_id)
        if (
            proposal is None
            or proposal.target_mindmap_id != mindmap_id
            or getattr(proposal, 'base_document_id', None) is not None
        ):
            raise ServiceException(
                data={'errorCode': 'AI_PROPOSAL_NOT_FOUND'},
                message='AI 脑图提案不存在',
            )
        proposal_job = await MindmapAiDao.get_job(db, proposal.job_id, user_id)
        if proposal_job is None:
            raise ServiceException(
                data={'errorCode': 'AI_PROPOSAL_NOT_FOUND'},
                message='AI 脑图提案不存在',
            )
        proposal_job_id = str(proposal.job_id)
        if proposal.status == 'applied':
            # Rollback expires ORM instances in a real AsyncSession.  Copy the
            # response scalars before releasing the transaction; otherwise
            # the idempotent replay path can trigger an implicit async query
            # (MissingGreenlet) while constructing its response.
            replay_proposal_id = str(proposal.id)
            replay_revision = proposal.applied_revision
            await db.rollback()
            await MindmapAiTaskManager._wake_waiting_followups(proposal_job_id)
            return {
                'proposalId': replay_proposal_id,
                'status': 'applied',
                'contentRevision': replay_revision,
                'idempotentReplay': True,
            }
        operations = _json_loads(getattr(proposal, 'operations_json', None), None)
        if (
            (
                proposal.status not in {'ready', 'prepared'}
                and not (
                    proposal.status == 'needs_review'
                    and _is_high_impact_proposal(proposal)
                )
            )
            or proposal.expires_time <= datetime.now()
        ):
            raise ServiceException(
                data={'errorCode': (
                    'AI_PROPOSAL_STALE'
                    if proposal.status in {'stale', 'expired'}
                    or proposal.expires_time <= datetime.now()
                    else 'AI_PROPOSAL_STATE_INVALID'
                )},
                message='AI 脑图提案已过期或不可应用',
            )
        proposal_record_id = str(proposal.id)
        if proposal.base_revision != model.content_revision or proposal.base_hash != model.base_hash:
            await cls._mark_proposal_stale(db, proposal_record_id, proposal_job_id)
            raise ServiceException(
                data={'errorCode': 'AI_PROPOSAL_STALE'},
                message='AI 脑图提案基线不一致，请基于最新内容重新生成',
            )
        if not force_overwrite and model.room_epoch != proposal.base_room_epoch:
            raise ServiceException(
                data={'errorCode': 'AI_APPLY_CONFLICT'},
                message='AI 脑图协作房间已切换，请基于最新内容重新生成',
            )
        expected_revision = int(proposal.base_revision)
        expected_room_epoch = proposal.base_room_epoch
        # AsyncSession.rollback() 会让当前事务中加载的 ORM 实例过期。协作栅栏
        # 等待阶段只能使用事务结束前复制出的不可变标量；否则在真实
        # SQLAlchemy 会话中再次读取 proposal / proposal_job 会触发
        # DetachedInstanceError，而基于 SimpleNamespace 的单测无法暴露它。
        proposal_base_hash = str(proposal.base_hash or '')
        proposal_base_revision = expected_revision
        proposal_base_room_epoch = expected_room_epoch
        await db.rollback()

        from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

        barrier = None
        if not force_overwrite:
            barrier = await room_manager.acquire_collaboration_mutation_barrier(
                mindmap_id,
                expected_revision,
                expected_room_epoch,
                operation='apply',
            )
        # 编辑器可能提交一个规范化后与当前正文完全一致的保存确认（例如富文本
        # 运行时字段被清洗）。这会推进 revision/room epoch，却没有改变 AI
        # Proposal 绑定的可编辑文档哈希。首个旧基线栅栏失败时，只允许在服务端
        # 重新读取并证明内容仍然等价后，把写栅栏安全迁移到当前协作世代。只有
        # 用户在客户端二次确认 forceOverwrite 时，才允许改绑最新协作版本并执行
        # 整图覆盖；提交瞬间仍由 barrier/CAS 阻止覆盖确认后的新修改。
        if force_overwrite or barrier is None:
            await MindmapService.check_mindmap_access(
                db,
                mindmap_id,
                user_id,
                require_edit=True,
            )
            latest_detail = await MindmapService.get_mindmap_detail_services(
                db,
                mindmap_id,
                user_id,
            )
            latest_document, _latest_summary = normalize_ai_editable_source_document(
                document_from_mindmap_detail(latest_detail), max_node_count=AI_MAX_NODE_COUNT,
            )
            latest_revision = int(latest_detail.content_revision)
            latest_hash = compute_document_hash(latest_document)
            latest_room_epoch = await room_manager.get_active_lineage_epoch(
                mindmap_id,
                latest_revision,
            )
            await db.rollback()
            equivalent_new_baseline = (
                latest_hash == proposal_base_hash
                and (
                    latest_revision != expected_revision
                    or latest_room_epoch != expected_room_epoch
                )
            )
            if force_overwrite or equivalent_new_baseline:
                expected_revision = latest_revision
                expected_room_epoch = latest_room_epoch
                barrier = await room_manager.acquire_collaboration_mutation_barrier(
                    mindmap_id,
                    expected_revision,
                    expected_room_epoch,
                    operation='apply',
                )
        if barrier is None:
            raise ServiceException(
                data={'errorCode': 'AI_APPLY_CONFLICT'},
                message='无法安全冻结协作房间，请稍后重试或重新生成提案',
            )
        prepared_barrier = None
        database_committed = False
        try:
            if not await room_manager.wait_for_collaboration_mutation_barrier(barrier):
                raise ServiceException(
                    data={'errorCode': 'AI_APPLY_CONFLICT'},
                    message='协作修改未能全部排空，已取消 AI 应用以保护当前内容',
                )

            # 第二阶段重新开启事务并按固定锁顺序复读全部权威状态。第一阶段
            # 的 ORM 对象只用于提示客户端冻结，不能参与任何写入决定。
            proposal = await MindmapAiDao.get_proposal(
                db,
                proposal_id,
                user_id,
                for_update=True,
            )
            if (
                proposal is None
                or proposal.target_mindmap_id != mindmap_id
                or getattr(proposal, 'base_document_id', None) is not None
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_PROPOSAL_NOT_FOUND'},
                    message='AI 脑图提案不存在',
                )
            if proposal.status == 'applied':
                return {
                    'proposalId': proposal.id,
                    'status': 'applied',
                    'contentRevision': proposal.applied_revision,
                    'idempotentReplay': True,
                }
            proposal_job = await MindmapAiDao.get_job(db, proposal.job_id, user_id)
            operations = _json_loads(getattr(proposal, 'operations_json', None), None)
            if (
                proposal_job is None
                or (
                    proposal.status not in {'ready', 'prepared'}
                    and not (
                        proposal.status == 'needs_review'
                        and _is_high_impact_proposal(proposal)
                    )
                )
                or proposal.expires_time <= datetime.now()
                or proposal.base_revision != model.content_revision
                or proposal.base_hash != model.base_hash
                or proposal.base_room_epoch != proposal_base_room_epoch
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_PROPOSAL_STALE'},
                    message='AI 脑图提案基线已变化，请重新生成',
                )
            await MindmapService.check_mindmap_access(
                db,
                mindmap_id,
                user_id,
                require_edit=True,
            )
            detail = await MindmapService.get_mindmap_detail_services(
                db,
                mindmap_id,
                user_id,
            )
            editor_document = document_from_mindmap_detail(detail)
            current_document, _summary = normalize_ai_editable_source_document(
                editor_document,
                max_node_count=AI_MAX_NODE_COUNT,
            )
            current_epoch = await room_manager.get_active_lineage_epoch(
                mindmap_id,
                expected_revision,
            )
            current_document_hash = compute_document_hash(current_document)
            if (
                int(detail.content_revision) != expected_revision
                or (
                    not force_overwrite
                    and current_document_hash != proposal.base_hash
                )
                or current_epoch != expected_room_epoch
                or not await room_manager.verify_collaboration_mutation_barrier(barrier)
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_APPLY_CONFLICT'},
                    message='云端脑图已被协作者更新，已取消 AI 应用',
                )
            try:
                if (
                    str(getattr(proposal_job, 'id', '')) != str(proposal.job_id)
                    or getattr(proposal_job, 'source_type', None) != 'cloud_document'
                    or getattr(proposal_job, 'target', None) != 'proposal'
                    or getattr(proposal_job, 'source_mindmap_id', None) != mindmap_id
                    or getattr(proposal_job, 'base_revision', None)
                    != proposal.base_revision
                    or getattr(proposal_job, 'base_hash', None) != proposal.base_hash
                    or getattr(proposal_job, 'base_room_epoch', None)
                    != proposal.base_room_epoch
                    or getattr(proposal_job, 'artifact_id', None)
                    != proposal.result_artifact_id
                ):
                    raise MindmapArtifactError(
                        '云端 Proposal 与任务来源不一致',
                        code=PROPOSAL_INTEGRITY_ERROR_CODE,
                    )
                artifact_record, artifact = await cls.get_artifact(
                    db,
                    proposal.result_artifact_id,
                    user_id,
                )
                manifest = artifact.get('manifest')
                artifact_document = artifact.get('document')
                if (
                    str(getattr(artifact_record, 'job_id', ''))
                    != str(proposal.job_id)
                    or getattr(artifact_record, 'document_hash', None)
                    != proposal.result_hash
                    or not isinstance(manifest, dict)
                    or not isinstance(artifact_document, dict)
                    or not isinstance(operations, list)
                ):
                    raise MindmapArtifactError(
                        '云端 Proposal 与 Artifact 关联不一致',
                        code=PROPOSAL_INTEGRITY_ERROR_CODE,
                    )
                max_node_count = AI_MAX_NODE_COUNT
                integrity_base_document = current_document
                if force_overwrite:
                    request_model = MindmapAiJobCreateModel.model_validate(
                        _json_loads(getattr(proposal_job, 'request_json', None), {}),
                    )
                    source = request_model.source
                    frozen_base_document = source.baseline_document or source.document
                    if (
                        source.type != 'cloud_document'
                        or source.mindmap_id != mindmap_id
                        or source.revision != proposal.base_revision
                        or source.document_hash != proposal.base_hash
                        or not isinstance(frozen_base_document, dict)
                    ):
                        raise MindmapArtifactError(
                            '强制覆盖 Proposal 缺少可信冻结基线',
                            code=PROPOSAL_INTEGRITY_ERROR_CODE,
                        )
                    integrity_base_document, _base_summary = (
                        normalize_ai_editable_source_document(
                            frozen_base_document,
                            max_node_count=max_node_count,
                        )
                    )
                    if compute_document_hash(integrity_base_document) != proposal.base_hash:
                        raise MindmapArtifactError(
                            '强制覆盖 Proposal 冻结基线哈希不一致',
                            code=PROPOSAL_INTEGRITY_ERROR_CODE,
                        )
                operations = normalize_proposal_operations_for_apply(
                    base_document=integrity_base_document,
                    operations=operations,
                    artifact_document=artifact_document,
                    max_node_count=max_node_count,
                )
                verify_proposal_document_integrity(
                    base_document=integrity_base_document,
                    operations=operations,
                    artifact_document=artifact_document,
                    proposal_result_hash=proposal.result_hash,
                    manifest_document_hash=manifest.get('documentHash'),
                    max_node_count=max_node_count,
                )
                document = (
                    json.loads(json.dumps(artifact_document, ensure_ascii=False))
                    if force_overwrite
                    else materialize_editor_document_from_proposal(
                        source_document=editor_document,
                        operations=operations,
                        artifact_document=artifact_document,
                        max_node_count=max_node_count,
                    )
                )
            except (
                KeyError,
                IndexError,
                MindmapArtifactError,
                ServiceException,
                TypeError,
                ValueError,
            ) as exc:
                logger.warning(
                    'AI 云端 Proposal 完整性校验失败: '
                    f'proposal_id={str(proposal_id)[:36]}, reason={str(exc)[:200]}'
                )
                raise _proposal_integrity_service_exception(exc) from exc
            try:
                result = await MindmapService.update_content_batch_services(
                    db,
                    mindmap_id,
                    MindmapContentBatchModel(
                        baseRevision=expected_revision,
                        clientMutationId=(
                            f'ai:{proposal_id}:'
                            f'{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}'
                        ),
                        yjsUpdateCount=0,
                        yjsDeliveryMode='reload',
                        operations=[{'type': 'document.content.update'}],
                        nodeTree=document['root'],
                        viewData=document['view'],
                        layout=document['layout'],
                        theme=document['theme'],
                        documentData=document['documentData'],
                    ),
                    user_id,
                    user_name,
                    commit=False,
                    broadcast=False,
                )
            except ServiceWarning as exc:
                raise ServiceException(
                    data={'errorCode': 'AI_APPLY_CONFLICT'},
                    message='云端脑图已被协作者更新，请刷新后重新生成',
                ) from exc
            now = datetime.now()
            applied_expires_time = max(
                proposal.expires_time,
                cls._applied_result_expiration(now),
            )
            await MindmapAiDao.add_undo(db, {
                'proposal_id': proposal_id,
                'user_id': user_id,
                'mindmap_id': mindmap_id,
                'before_document_json': _json_dumps(editor_document),
                'before_hash': current_document_hash,
                'applied_hash': proposal.result_hash,
                'applied_revision': result['contentRevision'],
                'status': 'available',
                'created_time': now,
                'expires_time': applied_expires_time,
            })
            await MindmapAiDao.update_proposal(db, proposal_id, {
                'status': 'applied',
                'applied_revision': result['contentRevision'],
                'applied_time': now,
            })
            await MindmapAiDao.update_job(db, proposal.job_id, {
                'status': 'applied',
                'progress': 100,
                'completed_time': now,
            })
            await MindmapAiDao.extend_result_expiration(
                db,
                job_id=proposal.job_id,
                artifact_id=proposal.result_artifact_id,
                proposal_id=proposal.id,
                expires_time=applied_expires_time,
            )
            await MindmapAiDao.add_event(
                db,
                proposal.job_id,
                'cloud_applied',
                _event_json({
                    'proposalId': proposal.id,
                    'mindmapId': mindmap_id,
                    'contentRevision': result['contentRevision'],
                    'rebasedFromRevision': (
                        proposal_base_revision
                        if expected_revision != proposal_base_revision
                        else None
                    ),
                    'forceOverwrite': force_overwrite,
                }),
            )
            prepared_barrier = (
                await room_manager.prepare_collaboration_mutation_barrier_commit(
                    barrier,
                    result['contentRevision'],
                )
            )
            if prepared_barrier is None:
                raise ServiceException(
                    data={'errorCode': 'AI_APPLY_CONFLICT'},
                    message='协作房间在提交前发生变化，已取消 AI 应用',
                )
            await db.commit()
            database_committed = True
        finally:
            if not database_committed:
                await db.rollback()
                await room_manager.abort_collaboration_mutation_barrier(
                    prepared_barrier or barrier,
                )

        record_mindmap_ai_event('cloud_applied')
        barrier_completed = await room_manager.complete_collaboration_mutation_barrier(
            prepared_barrier,
            new_revision=result['contentRevision'],
            client_mutation_id=result['clientMutationId'],
        )
        await MindmapAiTaskManager._wake_waiting_followups(proposal_job_id)
        return {
            'proposalId': proposal.id,
            'status': 'applied',
            'contentRevision': result['contentRevision'],
            'idempotentReplay': bool(result.get('idempotentReplay')),
            'collaborationSyncPending': not barrier_completed,
            'forceOverwrite': force_overwrite,
            'rebasedFromRevision': (
                proposal_base_revision
                if expected_revision != proposal_base_revision
                else None
            ),
        }

    @classmethod
    async def undo_cloud_proposal(  # noqa: PLR0912, PLR0915
        cls,
        db: AsyncSession,
        mindmap_id: int,
        proposal_id: str,
        user_id: int,
        user_name: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        # 与 apply 相同，排空阶段只做无锁身份解析；真正的 undo 决策必须在
        # ACK 完成后重新锁行读取，避免与客户端最终保存形成死锁。
        undo = await MindmapAiDao.get_undo(db, proposal_id, user_id)
        proposal = await MindmapAiDao.get_proposal(db, proposal_id, user_id)
        if undo is None or undo.mindmap_id != mindmap_id:
            raise ServiceException(
                data={'errorCode': 'AI_UNDO_NOT_FOUND'},
                message='AI 脑图撤销记录不存在',
            )
        proposal_job = None
        direct_receipt = False
        if proposal is None:
            proposal_job = await MindmapAiDao.get_job(db, proposal_id, user_id)
            direct_receipt = bool(
                proposal_job is not None
                and _json_loads(getattr(proposal_job, 'request_json', None), {}).get(
                    'executionMode',
                ) == 'direct'
                and getattr(proposal_job, 'proposal_id', None) == proposal_id
            )
            if not direct_receipt:
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_NOT_FOUND'},
                    message='AI 脑图撤销记录不存在',
                )
        else:
            if (
                getattr(proposal, 'target_mindmap_id', None) != mindmap_id
                or getattr(proposal, 'base_document_id', None) is not None
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_NOT_FOUND'},
                    message='AI 脑图撤销记录不存在',
                )
            proposal_job = await MindmapAiDao.get_job(db, proposal.job_id, user_id)
        if proposal_job is None:
            raise ServiceException(
                data={'errorCode': 'AI_UNDO_NOT_FOUND'},
                message='AI 脑图撤销记录不存在',
            )
        if direct_receipt and undo.status != 'undone' and _raw_direct_undo_baseline(proposal_job) is None:
            raise ServiceException(
                data={'errorCode': 'AI_UNDO_CONFLICT'},
                message='旧 AI 任务未保存精确原始快照，无法安全自动撤销',
            )
        if undo.status == 'undone':
            await MindmapAiTaskManager._wake_waiting_followups(str(proposal_job.id))
            return {
                'proposalId': proposal_id,
                'status': 'undone',
                'contentRevision': undo.undone_revision,
                'idempotentReplay': True,
            }
        if undo.status != 'available' or undo.expires_time <= datetime.now():
            raise ServiceException(
                data={'errorCode': (
                    'AI_UNDO_CONFLICT'
                    if undo.status == 'blocked'
                    else 'AI_UNDO_STATE_INVALID'
                )},
                message='AI 脑图撤销记录已过期或不可用',
            )
        expected_revision = int(undo.applied_revision)
        await db.rollback()

        from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

        expected_room_epoch = await room_manager.get_active_lineage_epoch(
            mindmap_id,
            expected_revision,
        )
        barrier = await room_manager.acquire_collaboration_mutation_barrier(
            mindmap_id,
            expected_revision,
            expected_room_epoch,
            operation='undo',
        )
        if barrier is None:
            raise ServiceException(
                data={'errorCode': 'AI_UNDO_CONFLICT'},
                message='无法安全冻结协作房间，已取消撤销以保护当前内容',
            )
        prepared_barrier = None
        database_committed = False
        try:
            if not await room_manager.wait_for_collaboration_mutation_barrier(barrier):
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_CONFLICT'},
                    message='协作修改未能全部排空，已取消撤销以保护当前内容',
                )
            undo = await MindmapAiDao.get_undo(
                db,
                proposal_id,
                user_id,
                for_update=True,
            )
            proposal = await MindmapAiDao.get_proposal(
                db,
                proposal_id,
                user_id,
                for_update=True,
            )
            proposal_job = (
                await MindmapAiDao.get_job(db, proposal.job_id, user_id)
                if proposal is not None
                else await MindmapAiDao.get_job(db, proposal_id, user_id)
            )
            direct_receipt = bool(
                proposal is None
                and proposal_job is not None
                and _json_loads(getattr(proposal_job, 'request_json', None), {}).get(
                    'executionMode',
                ) == 'direct'
                and getattr(proposal_job, 'proposal_id', None) == proposal_id
            )
            if (
                undo is None
                or undo.mindmap_id != mindmap_id
                or proposal_job is None
                or (
                    not direct_receipt
                    and (
                        proposal is None
                        or getattr(proposal, 'target_mindmap_id', None) != mindmap_id
                        or getattr(proposal, 'base_document_id', None) is not None
                    )
                )
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_NOT_FOUND'},
                    message='AI 脑图撤销记录不存在',
                )
            if undo.status == 'undone':
                # ``undo`` and ``proposal_job`` are both read with row locks
                # above.  Do not wake the successor while this transaction is
                # still open: _wake_waiting_followups acquires the same parent
                # job lock in a separate session and would deadlock on an
                # idempotent retry.  Release the lock and collaboration barrier
                # before scheduling the already-completed queue.
                replay_result = {
                    'proposalId': proposal_id,
                    'status': 'undone',
                    'contentRevision': undo.undone_revision,
                    'idempotentReplay': True,
                }
                replay_job_id = str(proposal_job.id)
                await db.rollback()
                await room_manager.abort_collaboration_mutation_barrier(barrier)
                # Mark cleanup as complete so the finally block does not abort
                # the same barrier a second time (which could publish a stale
                # release event after another operation acquired a new token).
                database_committed = True
                await MindmapAiTaskManager._wake_waiting_followups(replay_job_id)
                return replay_result
            if (
                proposal_job is None
                or undo.status != 'available'
                or undo.expires_time <= datetime.now()
                or int(undo.applied_revision) != expected_revision
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_CONFLICT'},
                    message='AI 脑图撤销记录已变化，不能继续自动撤销',
                )
            await MindmapService.check_mindmap_access(
                db,
                mindmap_id,
                user_id,
                require_edit=True,
            )
            detail = await MindmapService.get_mindmap_detail_services(
                db,
                mindmap_id,
                user_id,
            )
            current_document, _summary = normalize_ai_editable_source_document(
                document_from_mindmap_detail(detail), max_node_count=AI_MAX_NODE_COUNT,
            )
            current_epoch = await room_manager.get_active_lineage_epoch(
                mindmap_id,
                expected_revision,
            )
            if (
                int(detail.content_revision) != expected_revision
                or compute_document_hash(current_document) != undo.applied_hash
                or current_epoch != expected_room_epoch
                or not await room_manager.verify_collaboration_mutation_barrier(barrier)
            ):
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_CONFLICT'},
                    message='AI 应用后脑图已有新修改，不能自动撤销以免覆盖协作者内容',
                )
            before_document = _json_loads(undo.before_document_json)
            if not isinstance(before_document, dict):
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_SNAPSHOT_INVALID'},
                    message='AI 脑图撤销快照损坏',
                )
            try:
                result = await MindmapService.update_content_batch_services(
                    db,
                    mindmap_id,
                    MindmapContentBatchModel(
                        baseRevision=undo.applied_revision,
                        clientMutationId=(
                            f'ai-undo:{proposal_id}:'
                            f'{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}'
                        ),
                        yjsUpdateCount=0,
                        yjsDeliveryMode='reload',
                        operations=[{'type': 'document.content.update'}],
                        nodeTree=before_document['root'],
                        viewData=before_document['view'],
                        layout=before_document['layout'],
                        theme=before_document['theme'],
                        documentData=before_document['documentData'],
                    ),
                    user_id,
                    user_name,
                    commit=False,
                    broadcast=False,
                )
            except ServiceWarning as exc:
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_CONFLICT'},
                    message='AI 应用后脑图已有新修改，不能自动撤销以免覆盖协作者内容',
                ) from exc
            deleted_comment_nodes = (
                await MindmapCommentService.delete_ai_comments_for_job(
                    db,
                    mindmap_id,
                    user_id,
                    str(proposal_job.id),
                )
                if direct_receipt
                else []
            )
            await MindmapAiDao.update_undo(db, proposal_id, {
                'status': 'undone',
                'undone_revision': result['contentRevision'],
            })
            if proposal is not None:
                await MindmapAiDao.update_proposal(db, proposal_id, {'status': 'undone'})
            now = datetime.now()
            await MindmapAiDao.update_job(db, proposal_job.id, {
                'status': 'undone',
                'completed_time': now,
            })
            if proposal is not None:
                await MindmapAiDao.extend_result_expiration(
                    db,
                    job_id=proposal.job_id,
                    artifact_id=proposal.result_artifact_id,
                    proposal_id=proposal_id,
                    expires_time=max(
                        proposal.expires_time,
                        cls._applied_result_expiration(now),
                    ),
                )
            await MindmapAiDao.add_event(
                db,
                proposal_job.id,
                'cloud_undone',
                _event_json({
                    'proposalId': proposal_id,
                    'mindmapId': mindmap_id,
                    'contentRevision': result['contentRevision'],
                }),
            )
            prepared_barrier = (
                await room_manager.prepare_collaboration_mutation_barrier_commit(
                    barrier,
                    result['contentRevision'],
                )
            )
            if prepared_barrier is None:
                raise ServiceException(
                    data={'errorCode': 'AI_UNDO_CONFLICT'},
                    message='协作房间在提交前发生变化，已取消 AI 撤销',
                )
            await db.commit()
            database_committed = True
        finally:
            if not database_committed:
                await db.rollback()
                await room_manager.abort_collaboration_mutation_barrier(
                    prepared_barrier or barrier,
                )

        record_mindmap_ai_event('cloud_undone')
        for deleted_comment in deleted_comment_nodes:
            try:
                await MindmapCommentService._broadcast_change(
                    mindmap_id,
                    (
                        'thread_deleted'
                        if deleted_comment.get('threadDeleted')
                        else 'deleted'
                    ),
                    deleted_comment['threadId'],
                    deleted_comment['nodeUid'],
                )
            except Exception as exc:  # noqa: PERF203
                logger.warning(
                    '广播 AI 直写评论撤销失败: '
                    f"mindmap_id={mindmap_id}, thread_id={deleted_comment['threadId']}, error={exc}",
                )
        barrier_completed = await room_manager.complete_collaboration_mutation_barrier(
            prepared_barrier,
            new_revision=result['contentRevision'],
            client_mutation_id=result['clientMutationId'],
        )
        # The queued successor must be rebased against the post-undo revision;
        # otherwise it remains waiting forever until a worker recovery scan.
        await MindmapAiTaskManager._wake_waiting_followups(str(proposal_job.id))
        return {
            'proposalId': proposal_id,
            'status': 'undone',
            'contentRevision': result['contentRevision'],
            'idempotentReplay': bool(result.get('idempotentReplay')),
            'collaborationSyncPending': not barrier_completed,
        }

    @classmethod
    async def _mark_proposal_stale(
        cls,
        db: AsyncSession,
        proposal_id: str,
        job_id: str,
    ) -> None:
        now = datetime.now()
        await MindmapAiDao.update_proposal(db, proposal_id, {'status': 'stale'})
        await MindmapAiDao.update_job(db, job_id, {
            'status': 'stale',
            'completed_time': now,
        })
        await MindmapAiDao.add_event(
            db,
            job_id,
            'proposal_stale',
            _event_json({'status': 'stale', 'proposalId': proposal_id}),
        )
        await db.commit()
        record_mindmap_ai_event('proposal_stale')
