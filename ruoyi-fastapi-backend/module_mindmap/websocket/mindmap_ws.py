"""脑图 WebSocket 端点"""
import asyncio
import base64
import binascii
import json
import math
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from config.database import AsyncSessionLocal
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.service.mindmap_document_service import (
    STRUCTURED_CONTENT_CORRUPT_MESSAGE,
    MindmapDocumentService,
)
from module_mindmap.service.mindmap_metrics import record_mindmap_event
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION
from module_mindmap.websocket.room_manager import (
    CONDITIONAL_NODE_PATCH_CAPABILITY,
    CROSS_NODE_CRDT_V2_CAPABILITY,
    NODE_EDIT_LEASE_CAPABILITY,
    NODE_EDIT_LEASE_RENEWAL_CAPABILITY,
    STRUCTURED_NODE_PATCH_CAPABILITY,
    YJS_CHECKPOINT_CAPABILITY,
    YJS_LINEAGE_CAPABILITY,
    YJS_MUTATION_SEQUENCE_CAPABILITY,
    YJS_SOURCE_CAS_CAPABILITY,
    room_manager,
)
from module_mindmap.websocket.ws_auth import WsAuthenticationError, validate_ws_token
from module_mindmap.websocket.yjs_doc import (
    YjsDocManager,
    get_yjs_lineage_digest,
    get_yjs_state_digest,
    normalize_yjs_state_source_changes,
    normalize_yjs_state_source_digests,
)
from utils.log_util import logger

# 认证超时：连接后 10 秒内必须发送 auth 消息
AUTH_TIMEOUT_SECONDS = 10
# Yjs 状态持久化间隔：每 30 秒最多持久化一次
PERSIST_INTERVAL_SECONDS = 30
YJS_PERSIST_SAVED = 'saved'
YJS_PERSIST_THROTTLED = 'throttled'
YJS_PERSIST_FAILED = 'failed'
# 心跳间隔：每 30 秒发送一次 ping
HEARTBEAT_INTERVAL_SECONDS = 30
# 连续未响应 pong 次数上限，超过则判定连接死亡
HEARTBEAT_MISS_LIMIT = 3
# 登录或权限基础设施连续失败达到上限后关闭并自动重连；明确失效立即终止。
RECHECK_TRANSIENT_FAILURE_LIMIT = 3
WS_RETRY_LATER_CLOSE_CODE = 1013
MAX_AWARENESS_NODE_COUNT = 100
MAX_NODE_UID_LENGTH = 64
MAX_YJS_UPDATE_BYTES = 5 * 1024 * 1024
MAX_YJS_STATE_BYTES = 15 * 1024 * 1024
MAX_YJS_PATCH_BYTES = 2 * 1024 * 1024
MAX_YJS_PATCH_NODE_COUNT = 20000
MAX_YJS_PATCH_CHILD_COUNT = 50000
MAX_YJS_PATCH_JSON_DEPTH = 64
MAX_CLIENT_MUTATION_ID_LENGTH = 100
MAX_YJS_LINEAGE_ID_LENGTH = 128
MAX_YJS_UPDATES_PER_MUTATION = 10_000
WS_TRAFFIC_WINDOW_SECONDS = 10
MAX_WS_MESSAGES_PER_WINDOW = 600
MAX_WS_AWARENESS_PER_WINDOW = 120
MAX_WS_ENCODED_PAYLOAD_BYTES_PER_WINDOW = 96 * 1024 * 1024
SUPPORTED_WS_CLIENT_MESSAGE_TYPES = frozenset({
    'sync_step1',
    'sync_step2',
    'update',
    'checkpoint',
    'request_seed',
    'pong',
    'awareness',
    'node_edit_lease_acquire',
    'node_edit_lease_release',
})


class _SlidingWindowBudget:
    """O(窗口内事件数) 空间的精确滑动窗口预算。"""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.events: deque[tuple[float, int]] = deque()
        self.total = 0

    def consume(self, cost: int, now: float) -> bool:
        cutoff = now - self.window_seconds
        while self.events and self.events[0][0] <= cutoff:
            _, expired_cost = self.events.popleft()
            self.total -= expired_cost
        if cost < 0 or self.total + cost > self.limit:
            return False
        self.events.append((now, cost))
        self.total += cost
        return True


class WebSocketTrafficBudget:
    """限制单连接持续消息、选区事件和编码载荷，正常突发仍可用。"""

    def __init__(
        self,
        *,
        message_limit: int = MAX_WS_MESSAGES_PER_WINDOW,
        awareness_limit: int = MAX_WS_AWARENESS_PER_WINDOW,
        payload_limit: int = MAX_WS_ENCODED_PAYLOAD_BYTES_PER_WINDOW,
        window_seconds: float = WS_TRAFFIC_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._messages = _SlidingWindowBudget(message_limit, window_seconds)
        self._awareness = _SlidingWindowBudget(awareness_limit, window_seconds)
        self._payload = _SlidingWindowBudget(payload_limit, window_seconds)

    def allow_message(self, msg_type: object) -> bool:
        now = self._clock()
        if not self._messages.consume(1, now):
            return False
        return msg_type != 'awareness' or self._awareness.consume(1, now)

    def allow_payload(self, encoded_size: int) -> bool:
        return self._payload.consume(encoded_size, self._clock())


def get_ws_encoded_payload_size(data: dict, msg_type: object) -> int:
    """在 Base64 解码前按实际 JSON 中的 ASCII 字符数计算网络载荷。"""
    fields = ('state',) if msg_type == 'checkpoint' else ('update', 'state')
    return sum(
        len(value)
        for field in fields
        if isinstance((value := data.get(field)), str)
    )


def get_yjs_update_payload_limit(data: dict, msg_type: object = 'update') -> int:
    """只给形状完整的权威种子候选放宽到完整状态上限。

    租约必须在解码后再由 ``can_forward_ws_authoritative_seed`` 一次性消费；
    这里先用无需分配大字节串的字段/编码等值校验，避免任意 ``seedState``
    标志把普通实时更新的 5 MiB 边界扩大三倍。
    """
    update_b64 = data.get('update')
    strict_seed_candidate = (
        msg_type == 'update'
        and data.get('seedState') is True
        and isinstance(update_b64, str)
        and bool(update_b64)
        and data.get('state') == update_b64
        and data.get('clientMutationId') is None
        and data.get('patch') is None
        and type(data.get('contentRevision')) is int
    )
    return MAX_YJS_STATE_BYTES if strict_seed_candidate else MAX_YJS_UPDATE_BYTES


def get_ws_rate_limit_payload() -> dict:
    return {
        'type': 'protocol_error',
        'code': 'rate_limited',
        'message': '协作消息发送过于频繁，请稍后重试',
    }


def get_ws_write_capability_error_payload(
    missing_capabilities: set[str],
) -> dict[str, Any]:
    return {
        'type': 'protocol_error',
        'code': 'write_capability_required',
        'message': '协作写协议已升级，请更新页面后重试；当前仍可只读查看',
        'requiredCapabilities': sorted(missing_capabilities),
        'retryable': True,
    }


def normalize_client_mutation_id(value: object) -> str | None:
    """只转发可由 HTTP 保存契约接受的批次标识。"""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_CLIENT_MUTATION_ID_LENGTH:
        return None
    return normalized


def normalize_mutation_update_sequence(value: object) -> int | None:
    if type(value) is not int or not 1 <= value <= MAX_YJS_UPDATES_PER_MUTATION:
        return None
    return value


def normalize_yjs_lineage_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized.encode('utf-8')) > MAX_YJS_LINEAGE_ID_LENGTH
    ):
        return None
    return normalized


def are_yjs_state_replacements_authorized(
    replaceable_source_digests: dict[str, str],
    replacement_ids: list[str],
    replacement_digests: dict[str, str],
) -> bool:
    """只允许 CAS 替换当前连接实际收到且内容未变化的持久化来源。"""
    return all(
        replaceable_source_digests.get(source_id)
        == replacement_digests.get(source_id)
        for source_id in replacement_ids
    )


def get_ws_client_message_type(payload: object) -> str | None:
    """只接受协议声明的 JSON 对象消息，避免原始值或未知类型进入处理分支。"""
    if not isinstance(payload, dict):
        return None
    msg_type = payload.get('type')
    return msg_type if msg_type in SUPPORTED_WS_CLIENT_MESSAGE_TYPES else None


def get_ws_invalid_message_payload() -> dict:
    return {
        'type': 'protocol_error',
        'code': 'invalid_message',
        'message': '协作消息格式或类型无效',
    }


def get_ws_revision_fence_payload(
    manager: Any,
    mindmap_id: int,
    client_revision: object,
) -> dict | None:
    """统一校验所有会改变共享文档的消息 revision。"""
    if manager.is_current_revision(mindmap_id, client_revision):
        return None
    return {
        'type': 'stale_state',
        'message': '协作状态已落后，正在合并服务器最新内容',
        'currentRevision': manager.get_content_revision(mindmap_id),
    }


def build_ws_heartbeat_payload(content_revision: int) -> dict[str, Any]:
    """心跳同时携带数据库权威 revision，修复跨进程广播丢失后的静默分叉。"""
    return {
        'type': 'ping',
        'contentRevision': content_revision,
    }


async def get_authorized_ws_heartbeat_revision(
    mindmap_id: int,
    user_id: int,
    *,
    require_edit: bool,
) -> int:
    """在会话关闭前冻结心跳使用的数据库 revision 标量。

    ``AsyncSession`` 退出会回滚只读事务，而 rollback 会使 ORM 实体过期。
    因此不能把 ``Mindmap`` 带出上下文后再读取属性，否则异步属性刷新会在
    greenlet 上下文之外触发 ``MissingGreenlet``，或在实体分离后失败。
    """
    async with AsyncSessionLocal() as db:
        mindmap, _, _ = await MindmapService.resolve_mindmap_access(
            db,
            mindmap_id,
            user_id,
            require_edit=require_edit,
            lock_for_session=False,
        )
        content_revision = mindmap.content_revision
    if type(content_revision) is not int:
        raise RuntimeError('脑图正文 revision 无效')
    return content_revision


async def get_authorized_ws_revision_fence_payload(
    db: Any,
    manager: Any,
    mindmap_id: int,
    user_id: int,
    client_revision: object,
    *,
    require_current_revision: bool = True,
) -> dict | None:
    """以数据库权限和正文 revision 作为每条共享写消息的线性化点。"""
    mindmap = await MindmapService.check_mindmap_access(
        db,
        mindmap_id,
        user_id,
        require_edit=True,
    )
    # require_edit 会锁定 Mindmap 行。若撤权/重置先提交，这里一定看到新
    # 状态并拒绝；若本次校验先获得锁，则该增量在线性化顺序上早于随后
    # 的管理操作，后者会通过重置/终止事件统一收敛所有客户端。
    manager.set_content_revision(mindmap_id, mindmap.content_revision)
    if not require_current_revision:
        return None
    return get_ws_revision_fence_payload(
        manager,
        mindmap_id,
        client_revision,
    )


def normalize_ws_capabilities(payload: object) -> set[str]:
    """只协商服务端已实现的协议能力，忽略客户端任意声明。"""
    if not isinstance(payload, list):
        return set()
    return {
        capability
        for capability in payload
        if capability in {
            CONDITIONAL_NODE_PATCH_CAPABILITY,
            STRUCTURED_NODE_PATCH_CAPABILITY,
            YJS_CHECKPOINT_CAPABILITY,
            YJS_LINEAGE_CAPABILITY,
            YJS_MUTATION_SEQUENCE_CAPABILITY,
            YJS_SOURCE_CAS_CAPABILITY,
            CROSS_NODE_CRDT_V2_CAPABILITY,
            NODE_EDIT_LEASE_CAPABILITY,
            NODE_EDIT_LEASE_RENEWAL_CAPABILITY,
        }
    }


def normalize_ws_readonly_flag(value: object) -> bool:
    """将客户端只读参数安全归一化。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


async def acquire_ws_seed_lease(
    manager: Any,
    mindmap_id: int,
    content_revision: int,
    websocket: WebSocket,
    *,
    can_edit_session: bool,
) -> bool:
    """只允许可写会话竞争房间初始化租约。"""
    if not can_edit_session:
        return False
    return await manager.acquire_seed_lease(
        mindmap_id,
        content_revision,
        websocket,
    )


async def can_forward_ws_authoritative_seed(
    manager: Any,
    mindmap_id: int,
    websocket: WebSocket,
    *,
    msg_type: str,
    data: dict,
    mutation_id: str | None,
    update_bytes: bytes | None,
    state_bytes: bytes | None,
    patch: dict | None,
) -> bool:
    """仅允许当前租约持有者标记无本地修改的完整权威种子。"""
    revision = data.get('contentRevision')
    if (
        msg_type != 'update'
        or data.get('seedState') is not True
        or mutation_id is not None
        or not update_bytes
        or not state_bytes
        or update_bytes != state_bytes
        or patch is not None
        or type(revision) is not int
    ):
        return False
    return await manager.consume_seed_lease(mindmap_id, revision, websocket)


async def persist_authorized_yjs_state(  # noqa: PLR0913
    db: Any,
    mindmap_id: int,
    user_id: int,
    state: bytes,
    content_revision: int | None,
    *,
    source_id: str,
    replace_source_ids: list[str],
    replace_source_digests: dict[str, str] | None = None,
    lineage_id: str | None = None,
    manager: Any | None = None,
    enforce_lineage_fence: bool = False,
) -> bool:
    """在与正文保存相同的脑图行锁内复核编辑权限并保存检查点。"""
    # 协作者降权/移除、归档以及正文保存都先锁 Mindmap。这里沿用同一
    # 顺序，确保权限接口一旦提交，旧会话就不能再把断开前状态写回缓存。
    await MindmapService.check_mindmap_access(
        db,
        mindmap_id,
        user_id,
        require_edit=True,
    )
    if enforce_lineage_fence and (
        manager is None
        or lineage_id is None
        or not await manager.verify_content_lineage_fence(
            mindmap_id,
            content_revision,
            lineage_id,
        )
    ):
        record_mindmap_event('yjs_lineage_mismatch')
        return False
    return await YjsDocManager.save_state(
        db,
        mindmap_id,
        state,
        content_revision,
        source_id=source_id,
        replace_source_ids=replace_source_ids,
        replace_source_digests=replace_source_digests,
        lineage_id=lineage_id,
    )


async def reconcile_persisted_lineage_fence(
    manager: Any,
    mindmap_id: int,
    content_revision: int,
    lineage_id: str,
) -> bool:
    """锁定 DB 权威快照后更新 Redis，防止迟到 seed/握手反向覆盖。"""
    expected_digest = get_yjs_lineage_digest(lineage_id)
    if expected_digest is None:
        return False
    async with AsyncSessionLocal() as db:
        revision, _states, lineages = (
            await YjsDocManager.load_state_snapshot_with_lineages(
                db,
                mindmap_id,
                lock_for_update=True,
            )
        )
        persisted_digests = set(lineages.values())
        if revision != content_revision or persisted_digests != {expected_digest}:
            return False
        repaired, authoritative_digest = (
            await manager.repair_content_lineage_fence_from_persisted(
                mindmap_id,
                content_revision,
                expected_digest,
            )
        )
        return repaired and authoritative_digest == expected_digest


def get_ws_access_error_message(error: ServiceException) -> str:
    """区分权限拒绝与结构化内容保护，避免向用户返回误导原因。"""
    if error.message == STRUCTURED_CONTENT_CORRUPT_MESSAGE:
        return '脑图内容完整性校验失败，当前不能进入协作编辑'
    return '无访问权限'


def get_ws_auth_error_payload(error: Exception) -> dict:
    """只向客户端暴露稳定认证原因；未知内部异常统一按暂时故障处理。"""
    if isinstance(error, WsAuthenticationError):
        return {
            'type': 'auth_error',
            'message': str(error),
            'code': error.code,
            'retryable': error.retryable,
        }
    return {
        'type': 'auth_error',
        'message': '认证服务暂时不可用，请稍后重试',
        'code': 'auth_unavailable',
        'retryable': True,
    }


def get_ws_auth_recheck_action(
    error: Exception,
    mindmap_id: int,
    failure_count: int,
) -> tuple[dict, int] | None:
    """把长期会话复核结果分为继续容忍、自动重连和永久终止。"""
    auth_payload = get_ws_auth_error_payload(error)
    if auth_payload['retryable']:
        if failure_count < RECHECK_TRANSIENT_FAILURE_LIMIT:
            return None
        return auth_payload, WS_RETRY_LATER_CLOSE_CODE
    return ({
        'type': 'session_ended',
        'mindmapId': mindmap_id,
        'reason': auth_payload['code'],
        'message': auth_payload['message'],
    }, 4001)


async def close_websocket_with_error(
    websocket: WebSocket,
    payload: dict,
    close_code: int,
) -> None:
    """尽力发送稳定错误并关闭；对端提前断开不能逃逸认证边界。"""
    await room_manager.send_to(websocket, payload)
    try:
        await websocket.close(code=close_code)
    except Exception:
        pass


def decode_base64_payload(payload: object, max_bytes: int) -> bytes | None:
    """严格解码有限大小的 WebSocket 二进制字段，拒绝畸形或空载荷。"""
    if not isinstance(payload, str) or not payload or max_bytes <= 0:
        return None
    max_encoded_length = ((max_bytes + 2) // 3) * 4
    if len(payload) > max_encoded_length:
        return None
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    return decoded if decoded and len(decoded) <= max_bytes else None


def build_yjs_sync_init_payload(
    state_entries: dict[str, bytes],
    *,
    content_revision: int | None = None,
    include_legacy_state: bool = True,
) -> dict | None:
    """构造来源与状态严格按索引对齐的持久化同步消息。"""
    if not state_entries:
        return None
    state_sources = list(state_entries)
    encoded_states = [
        base64.b64encode(state_entries[source_id]).decode()
        for source_id in state_sources
    ]
    payload = {
        'type': 'sync_init',
        'states': encoded_states,
        'stateSources': state_sources,
        'stateDigests': [
            get_yjs_state_digest(state_entries[source_id])
            for source_id in state_sources
        ],
    }
    if type(content_revision) is int:
        payload['contentRevision'] = content_revision
    if include_legacy_state:
        payload['state'] = encoded_states[-1]
    return payload


def normalize_awareness_node_uids(data: dict) -> list[str]:
    """只接收有限数量的节点 UID；用户身份始终由服务端认证结果提供。"""
    raw = data.get('nodeUids')
    if raw is None and isinstance(data.get('update'), dict):
        raw = data['update'].get('nodeUids')
    if not isinstance(raw, list):
        return []
    result = []
    seen = set()
    for value in raw:
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            continue
        uid = str(value).strip()
        if not uid or len(uid) > MAX_NODE_UID_LENGTH or uid in seen:
            continue
        seen.add(uid)
        result.append(uid)
        if len(result) >= MAX_AWARENESS_NODE_COUNT:
            break
    return result


def normalize_awareness_editing_node_uid(data: dict) -> str:
    """严格校验实际文本编辑占用；缺失或异常值一律视为已释放。"""
    raw = data.get('editingNodeUid')
    if raw is None and isinstance(data.get('update'), dict):
        raw = data['update'].get('editingNodeUid')
    if not isinstance(raw, str):
        return ''
    uid = raw.strip()
    return uid if uid and len(uid) <= MAX_NODE_UID_LENGTH else ''


def normalize_node_edit_lease_request_id(value: object) -> str | None:
    """关联一次租约申请，禁止无界客户端标识进入响应。"""
    if not isinstance(value, str):
        return None
    request_id = value.strip()
    if not request_id or len(request_id) > MAX_CLIENT_MUTATION_ID_LENGTH:
        return None
    return request_id


def normalize_node_edit_lease_uid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    node_uid = value.strip()
    if not node_uid or len(node_uid) > MAX_NODE_UID_LENGTH:
        return None
    return node_uid


def _is_bounded_json_value(value: object, max_depth: int) -> bool:
    """迭代校验 JSON 类型、循环引用和容器深度，避免编码器递归失控。"""
    stack: list[tuple[str, object, int]] = [('visit', value, 1)]
    active_containers: set[int] = set()
    while stack:
        action, current, depth = stack.pop()
        if action == 'exit':
            active_containers.discard(id(current))
            continue
        if current is None or isinstance(current, (str, bool, int)):
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                return False
            continue
        if not isinstance(current, (dict, list)) or depth > max_depth:
            return False
        container_id = id(current)
        if container_id in active_containers:
            return False
        active_containers.add(container_id)
        stack.append(('exit', current, depth))
        if isinstance(current, dict):
            if any(not isinstance(key, str) for key in current):
                return False
            values = current.values()
        else:
            values = current
        stack.extend(('visit', child, depth + 1) for child in values)
    return True


def _get_bounded_json_size(value: object, max_depth: int, max_bytes: int) -> int | None:
    if not _is_bounded_json_value(value, max_depth):
        return None
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
    except (TypeError, ValueError, RecursionError):
        return None
    return len(encoded) if len(encoded) <= max_bytes else None


def _normalize_yjs_patch_uid_list(payload: object) -> list[str] | None:
    if not isinstance(payload, list):
        return None
    result = []
    for value in payload:
        if not isinstance(value, str):
            return None
        uid = value.strip()
        if not uid or len(uid) > MAX_NODE_UID_LENGTH:
            return None
        result.append(uid)
    return result


def _normalize_yjs_patch_node(payload: object) -> tuple[dict, int] | None:
    if not isinstance(payload, dict):
        return None
    uid = payload.get('uid')
    node_data = payload.get('data')
    children = _normalize_yjs_patch_uid_list(payload.get('children'))
    if (
        not isinstance(uid, str)
        or not uid.strip()
        or len(uid.strip()) > MAX_NODE_UID_LENGTH
        or not isinstance(node_data, dict)
        or children is None
    ):
        return None
    normalized = {
        'uid': uid.strip(),
        'data': node_data,
        'children': children,
    }
    child_count = len(children)
    if 'previousData' in payload:
        previous_data = payload['previousData']
        if not isinstance(previous_data, dict):
            return None
        normalized['previousData'] = previous_data
    if 'previousChildren' in payload:
        previous_children = _normalize_yjs_patch_uid_list(payload['previousChildren'])
        if previous_children is None:
            return None
        normalized['previousChildren'] = previous_children
        child_count += len(previous_children)
    return normalized, child_count


def _normalize_yjs_patch_with_size(payload: object) -> tuple[dict, int] | None:
    """校验并裁剪节点修复补丁，防止借协作广播放大任意 JSON。"""
    if not isinstance(payload, dict) or payload.get('schemaVersion') != 1:
        return None
    raw_nodes = payload.get('nodes')
    raw_deleted_uids = payload.get('deletedNodeUids')
    if not isinstance(raw_nodes, list) or not isinstance(raw_deleted_uids, list):
        return None
    if (
        len(raw_nodes) > MAX_YJS_PATCH_NODE_COUNT
        or len(raw_deleted_uids) > MAX_YJS_PATCH_NODE_COUNT
    ):
        return None

    nodes = []
    child_count = 0
    for raw_node in raw_nodes:
        normalized_node = _normalize_yjs_patch_node(raw_node)
        if normalized_node is None:
            return None
        node, node_child_count = normalized_node
        child_count += node_child_count
        if child_count > MAX_YJS_PATCH_CHILD_COUNT:
            return None
        nodes.append(node)

    deleted_node_uids = _normalize_yjs_patch_uid_list(raw_deleted_uids)
    if deleted_node_uids is None:
        return None

    normalized = {
        'schemaVersion': 1,
        'nodes': nodes,
        'deletedNodeUids': deleted_node_uids,
        'applyMeta': payload.get('applyMeta') is True,
    }
    encoded_size = _get_bounded_json_size(
        normalized,
        MAX_YJS_PATCH_JSON_DEPTH,
        MAX_YJS_PATCH_BYTES,
    )
    return (normalized, encoded_size) if encoded_size is not None else None


def normalize_yjs_patch(payload: object) -> dict | None:
    """兼容公开校验接口；端点使用内部结果同时取得实际编码体积。"""
    normalized = _normalize_yjs_patch_with_size(payload)
    return normalized[0] if normalized else None


async def mindmap_websocket_endpoint(  # noqa: PLR0911, PLR0912, PLR0915
    websocket: WebSocket,
    mindmap_id: int,
) -> None:
    """脑图实时协作 WebSocket 端点"""
    await websocket.accept()
    state_source_id = uuid.uuid4().hex
    requested_readonly = False
    can_edit_session = False
    missing_write_capabilities: set[str] = set()

    # ── 连接后认证（不通过 URL 传递 token） ──
    try:
        auth_msg = await asyncio.wait_for(
            websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS
        )
        if (
            not isinstance(auth_msg, dict)
            or auth_msg.get('type') != 'auth'
            or not auth_msg.get('token')
        ):
            await close_websocket_with_error(
                websocket,
                get_ws_auth_error_payload(WsAuthenticationError(
                    '请发送有效认证消息',
                    code='invalid_auth_message',
                )),
                4001,
            )
            return

        # 从 app.state 获取 redis
        redis = websocket.app.state.redis
        auth_token = auth_msg['token']
        requested_readonly = normalize_ws_readonly_flag(auth_msg.get('readonly'))
        user_info = await validate_ws_token(auth_token, redis)
    except WebSocketDisconnect:
        return
    except asyncio.TimeoutError:
        await close_websocket_with_error(
            websocket,
            get_ws_auth_error_payload(WsAuthenticationError(
                '认证超时，请重试',
                code='auth_timeout',
                retryable=True,
            )),
            WS_RETRY_LATER_CLOSE_CODE,
        )
        return
    except json.JSONDecodeError:
        await close_websocket_with_error(
            websocket,
            get_ws_auth_error_payload(WsAuthenticationError(
                '认证消息格式无效',
                code='invalid_auth_message',
            )),
            4001,
        )
        return
    except WsAuthenticationError as error:
        await close_websocket_with_error(
            websocket,
            get_ws_auth_error_payload(error),
            WS_RETRY_LATER_CLOSE_CODE if error.retryable else 4001,
        )
        return
    except Exception as error:
        logger.error(
            f'WebSocket 认证服务异常: error_type={type(error).__name__}'
        )
        await close_websocket_with_error(
            websocket,
            get_ws_auth_error_payload(error),
            WS_RETRY_LATER_CLOSE_CODE,
        )
        return

    # ── 脑图访问权限校验（防止认证用户访问无权限的脑图） ──
    capabilities = normalize_ws_capabilities(auth_msg.get('capabilities'))
    joined_room = False
    collaboration_revision = 1
    try:
        async with AsyncSessionLocal() as db:
            mindmap, permission, _ = await MindmapService.resolve_mindmap_access(
                db,
                mindmap_id,
                user_info['id'],
                require_edit=False,
                lock_for_session=True,
            )
            migration_failed = await MindmapDao.get_migration_status(db, mindmap_id) == 'failed'
            requested_can_edit = (
                not requested_readonly
                and permission >= 1
                and mindmap.status == 0
                and not migration_failed
            )
            if getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION:
                await MindmapDocumentService.load_tree(db, mindmap_id, required=True)
            required_write_capabilities = (
                await room_manager.get_required_write_capabilities(mindmap_id)
            )
            missing_write_capabilities = (
                required_write_capabilities - capabilities
                if requested_can_edit
                else set()
            )
            can_edit_session = requested_can_edit and not missing_write_capabilities
            # 在脑图行锁释放前注册本地连接。这样权限变更若先提交，本次
            # 复核会看到新权限；若连接先注册，随后提交的撤权通知一定能
            # 找到并关闭它，不会留下 30 秒的旧权限窗口。
            can_edit_session = await room_manager.join(
                mindmap_id,
                websocket,
                user_info,
                capabilities,
                can_edit=can_edit_session,
            )
            joined_room = True
            if requested_can_edit and not can_edit_session:
                required_write_capabilities = (
                    await room_manager.get_required_write_capabilities(mindmap_id)
                )
                missing_write_capabilities = required_write_capabilities - capabilities
            auth_ok_sent = await room_manager.send_to(websocket, {
                'type': 'auth_ok',
                'user': user_info,
                # 同一账号可以同时打开多个浏览器。Presence 必须按连接会话
                # 区分，不能用 user id 把其他浏览器误认为当前客户端自己。
                'sessionId': state_source_id,
                'readonly': not can_edit_session,
                'capabilities': sorted(capabilities),
                **(
                    {
                        'requiredWriteCapabilities': sorted(
                            required_write_capabilities,
                        ),
                        'writeRestrictedReason': 'write_capability_required',
                    }
                    if missing_write_capabilities
                    else {}
                ),
            })
            if not auth_ok_sent:
                await room_manager.leave(mindmap_id, websocket)
                joined_room = False
                return
            collaboration_revision = mindmap.content_revision
            # 新房间可直接初始化 DB revision；已有房间暂不推进。后者可能
            # 正处于 HTTP commit→revision broadcast 间隙，若在读取 WsState
            # 前用未知 transition 清栅栏，会把合法的连续 lineage 误判为
            # 空房间并触发独立 seed。
            if room_manager.get_content_revision(mindmap_id) is None:
                room_manager.set_content_revision(
                    mindmap_id,
                    collaboration_revision,
                )
    except ServiceException as exc:
        if joined_room:
            await room_manager.leave(mindmap_id, websocket)
        await close_websocket_with_error(websocket, {
            'type': 'auth_error',
            'message': get_ws_access_error_message(exc),
            'code': (
                'content_corrupt'
                if exc.message == STRUCTURED_CONTENT_CORRUPT_MESSAGE
                else 'access_denied'
            ),
            'retryable': False,
        }, 4003)
        return
    except Exception as error:
        if joined_room:
            await room_manager.leave(mindmap_id, websocket)
        logger.error(
            f'WebSocket 权限校验异常: error_type={type(error).__name__}'
        )
        await close_websocket_with_error(
            websocket,
            get_ws_auth_error_payload(WsAuthenticationError(
                '权限校验服务暂时不可用，请稍后重试',
                code='access_check_unavailable',
                retryable=True,
            )),
            WS_RETRY_LATER_CLOSE_CODE,
        )
        return

    # 广播跨实例权威成员快照，避免同一用户多标签页导致重复或误离线。
    users = await room_manager.get_room_users(mindmap_id)
    await room_manager.broadcast(mindmap_id, {'type': 'room_users', 'users': users})

    # 加载持久化的 Yjs 状态
    state_entries = {}
    replaceable_state_source_digests: dict[str, str] = {}
    lineage_snapshot_generation = 0
    try:
        async with AsyncSessionLocal() as db:
            (
                loaded_revision,
                state_entries,
                state_lineages,
            ) = await YjsDocManager.load_state_snapshot_with_lineages(
                db,
                mindmap_id,
                lock_for_update=True,
            )
            if loaded_revision is None:
                await close_websocket_with_error(websocket, {
                    'type': 'document_deleted',
                    'mindmapId': mindmap_id,
                    'message': '该脑图已不存在或已被移入回收站',
                }, 4004)
                await room_manager.leave(mindmap_id, websocket)
                return
            collaboration_revision = loaded_revision
            replaceable_state_source_digests = {
                source_id: get_yjs_state_digest(state)
                for source_id, state in state_entries.items()
            }
            known_revision = room_manager.get_content_revision(mindmap_id)
            if (
                type(known_revision) is int
                and known_revision > collaboration_revision
            ):
                # 查询期间其他请求可能已经提交更高 revision。数据库返回的
                # 旧快照不能依赖后续 lineage 分支间接识别：空状态和 legacy
                # 多来源都可能没有唯一 lineage，必须在任何 sync_init 或
                # seed_pending 发出前再次复核 revision 栅栏。
                await close_websocket_with_error(websocket, {
                    'type': 'stale_state',
                    'currentRevision': room_manager.get_content_revision(mindmap_id),
                    'reason': 'handshake_revision_advanced',
                    'message': '协作版本在初始化期间已更新，正在重新同步',
                }, WS_RETRY_LATER_CLOSE_CODE)
                await room_manager.leave(mindmap_id, websocket)
                return
            persisted_lineages = set(state_lineages.values())
            persisted_lineage_digest = (
                next(iter(persisted_lineages))
                if len(persisted_lineages) == 1
                else None
            )
            fence_repaired, authoritative_lineage_digest = (
                await room_manager.repair_content_lineage_fence_from_persisted(
                    mindmap_id,
                    collaboration_revision,
                    persisted_lineage_digest,
                    # 连续 HTTP/tag 增量会先把 sticky digest 搬到 r+1，
                    # WsState 在首个新 revision checkpoint 前仍为空。
                    preserve_matching_active=not state_entries,
                )
            )
            if not fence_repaired:
                await close_websocket_with_error(websocket, {
                    'type': 'protocol_error',
                    'code': 'lineage_fence_unavailable',
                    'message': '协作基线服务暂时不可用，请稍后重试',
                    'retryable': True,
                }, WS_RETRY_LATER_CLOSE_CODE)
                await room_manager.leave(mindmap_id, websocket)
                return
            room_manager.set_content_revision(mindmap_id, collaboration_revision)
            if not room_manager.is_current_revision(
                mindmap_id,
                collaboration_revision,
            ):
                await close_websocket_with_error(websocket, {
                    'type': 'stale_state',
                    'currentRevision': room_manager.get_content_revision(mindmap_id),
                    'reason': 'handshake_revision_advanced',
                    'message': '协作版本在初始化期间已更新，正在重新同步',
                }, WS_RETRY_LATER_CLOSE_CODE)
                await room_manager.leave(mindmap_id, websocket)
                return
            # repair 在 DB 行锁内完成，之后到本地 reconcile 之间没有 await；
            # 以本次明确推进后的代次作为 CAS 基线，避免把我们自己的 revision
            # 更新误识别成并发 seed，同时仍能拒绝后续真实切换。
            lineage_snapshot_generation = (
                room_manager.get_content_lineage_generation(mindmap_id)
            )
            if authoritative_lineage_digest is not None:
                lineage_reconciled, lineage_replaced = (
                    room_manager.reconcile_persisted_content_lineage_digest(
                        mindmap_id,
                        collaboration_revision,
                        authoritative_lineage_digest,
                        expected_generation=lineage_snapshot_generation,
                    )
                )
                if not lineage_reconciled:
                    await close_websocket_with_error(websocket, {
                        'type': 'stale_state',
                        'currentRevision': room_manager.get_content_revision(mindmap_id),
                        'reason': 'yjs_lineage_changed',
                        'message': '协作基线在初始化期间已更新，正在重新同步',
                    }, WS_RETRY_LATER_CLOSE_CODE)
                    await room_manager.leave(mindmap_id, websocket)
                    return
                if lineage_replaced:
                    # 数据库已经是其他 worker 的新 lineage，说明本地房间
                    # 漏掉了对应 Redis seed。旧连接必须禁止断开回写并
                    # 重连，不能继续在旧基线上局部广播。
                    await room_manager.disconnect_stale_lineage_peers(
                        mindmap_id,
                        websocket,
                        collaboration_revision,
                    )
            elif not room_manager.is_content_lineage_generation_current(
                mindmap_id, lineage_snapshot_generation,
            ):
                # 无 lineage/多 lineage 快照无法证明与查询期间收到的
                # seed 属于同一创建历史，用新事务重连取最新快照。
                await close_websocket_with_error(websocket, {
                    'type': 'stale_state',
                    'currentRevision': room_manager.get_content_revision(mindmap_id),
                    'reason': 'yjs_lineage_changed',
                    'message': '协作基线在初始化期间已更新，正在重新同步',
                }, WS_RETRY_LATER_CLOSE_CODE)
                await room_manager.leave(mindmap_id, websocket)
                return
            else:
                room_manager.clear_content_lineage(
                    mindmap_id,
                    collaboration_revision,
                )
            sync_init_payload = build_yjs_sync_init_payload(
                state_entries,
                content_revision=collaboration_revision,
                include_legacy_state=YJS_CHECKPOINT_CAPABILITY not in capabilities,
            )
            if sync_init_payload and not await room_manager.send_to(websocket, sync_init_payload):
                await room_manager.leave(mindmap_id, websocket)
                return
    except Exception as e:
        record_mindmap_event('yjs_state_load_failure')
        logger.error(f'加载 Yjs 状态失败: {e}')
        await close_websocket_with_error(
            websocket,
            get_ws_auth_error_payload(WsAuthenticationError(
                '协作状态服务暂时不可用，请稍后重试',
                code='collaboration_state_unavailable',
                retryable=True,
            )),
            WS_RETRY_LATER_CLOSE_CODE,
        )
        await room_manager.leave(mindmap_id, websocket)
        return
    if not room_manager.is_connection_active(websocket):
        await room_manager.leave(mindmap_id, websocket)
        return
    if not state_entries:
        seed_pending_sent = await room_manager.send_to(websocket, {
            'type': 'seed_pending',
            'contentRevision': collaboration_revision,
        })
        if not seed_pending_sent:
            await room_manager.leave(mindmap_id, websocket)
            return
    # 数据库检查点最多落后一个周期；每次加入都请现有客户端补发当前完整状态。
    # 全新房间里没有数据的新连接会忽略该请求，随后仍由种子租约完成初始化。
    await room_manager.broadcast(
        mindmap_id,
        {
            'type': 'seed_request',
            'contentRevision': collaboration_revision,
        },
        exclude=websocket,
    )

    # ── 心跳任务 ──
    missed_pongs = 0
    auth_recheck_failures = 0
    access_recheck_failures = 0

    async def heartbeat() -> None:
        """定期复核登录会话、编辑权限并检测死亡连接。"""
        nonlocal access_recheck_failures, auth_recheck_failures, missed_pongs
        try:
            while room_manager.is_connection_active(websocket):
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                try:
                    await validate_ws_token(auth_token, redis)
                    auth_recheck_failures = 0
                except Exception as error:
                    auth_payload = get_ws_auth_error_payload(error)
                    if auth_payload['retryable']:
                        auth_recheck_failures += 1
                    action = get_ws_auth_recheck_action(
                        error,
                        mindmap_id,
                        auth_recheck_failures,
                    )
                    if action is None:
                        logger.warning(
                            '复核脑图协作会话暂时失败: '
                            f'mindmap_id={mindmap_id}, user_id={user_info["id"]}, '
                            f'attempt={auth_recheck_failures}, '
                            f'error_type={type(error).__name__}'
                        )
                        continue
                    payload, close_code = action
                    room_manager.block_disconnect_persistence(websocket)
                    await close_websocket_with_error(websocket, payload, close_code)
                    return
                try:
                    checked_revision = await get_authorized_ws_heartbeat_revision(
                        mindmap_id,
                        user_info['id'],
                        require_edit=can_edit_session,
                    )
                    # Redis 广播短暂不可用时，以数据库 revision 作为最终兜底。
                    # 更新房间栅栏后，旧客户端的下一条写消息会收到 stale_state，
                    # 从而不能无限期继续广播已经被放弃的 Yjs 状态。
                    room_manager.set_content_revision(
                        mindmap_id,
                        checked_revision,
                    )
                    access_recheck_failures = 0
                except ServiceException:
                    await room_manager.notify_and_disconnect_user(
                        mindmap_id,
                        user_info['id'],
                        {
                            'type': 'access_revoked',
                            'mindmapId': mindmap_id,
                            'message': '当前编辑权限已失效，会话已结束',
                        },
                        revocation_scope='edit' if can_edit_session else 'access',
                    )
                    return
                except Exception as error:
                    access_recheck_failures += 1
                    if access_recheck_failures < RECHECK_TRANSIENT_FAILURE_LIMIT:
                        logger.warning(
                            '复核脑图协作权限暂时失败: '
                            f'mindmap_id={mindmap_id}, user_id={user_info["id"]}, '
                            f'attempt={access_recheck_failures}, '
                            f'error_type={type(error).__name__}'
                        )
                        continue
                    room_manager.block_disconnect_persistence(websocket)
                    access_error = WsAuthenticationError(
                        '权限校验服务暂时不可用，请稍后重试',
                        code='access_check_unavailable',
                        retryable=True,
                    )
                    payload, close_code = get_ws_auth_recheck_action(
                        access_error,
                        mindmap_id,
                        access_recheck_failures,
                    )
                    await close_websocket_with_error(websocket, payload, close_code)
                    return
                await room_manager.touch_presence(mindmap_id, websocket)
                if missed_pongs >= HEARTBEAT_MISS_LIMIT:
                    logger.warning(f'心跳超时: 用户 {user_info["id"]} 连续 {missed_pongs} 次未响应 pong，关闭连接')
                    try:
                        await websocket.close(code=4002)
                    except Exception:
                        pass
                    return
                missed_pongs += 1
                try:
                    if not await room_manager.send_to(
                        websocket,
                        build_ws_heartbeat_payload(checked_revision),
                    ):
                        return
                except Exception:
                    return
        except (WebSocketDisconnect, Exception):
            pass

    heartbeat_task = asyncio.create_task(heartbeat())

    # ── 消息循环 ──
    last_persist_time = 0.0
    latest_state_bytes = b''  # 跟踪最新的 Yjs 状态，用于断开时最终保存
    latest_state_revision = None
    latest_state_lineage_id = None
    latest_replace_source_ids: list[str] = []
    latest_replace_source_digests: dict[str, str] = {}
    traffic_budget = WebSocketTrafficBudget()

    async def authorize_shared_document_mutation(
        client_revision: object,
        *,
        require_current_revision: bool = True,
    ) -> tuple[bool, bool]:
        """返回 (允许继续, 需要终止当前消息循环)。"""
        nonlocal missing_write_capabilities
        missing_write_capabilities = await room_manager.get_missing_write_capabilities(
            mindmap_id,
            capabilities,
        )
        if not room_manager.is_connection_active(websocket):
            return False, True
        if missing_write_capabilities:
            room_manager.block_disconnect_persistence(websocket)
            await close_websocket_with_error(
                websocket,
                get_ws_write_capability_error_payload(
                    missing_write_capabilities,
                ),
                WS_RETRY_LATER_CLOSE_CODE,
            )
            return False, True
        try:
            async with AsyncSessionLocal() as db:
                revision_error = await get_authorized_ws_revision_fence_payload(
                    db,
                    room_manager,
                    mindmap_id,
                    user_info['id'],
                    client_revision,
                    require_current_revision=require_current_revision,
                )
        except ServiceException:
            # 数据库已经确认权限/文件状态失效；立即移除该用户在所有本地及
            # 远端 worker 的连接，且禁止 finally 把旧检查点写回。
            room_manager.block_disconnect_persistence(websocket)
            await room_manager.notify_and_disconnect_user(
                mindmap_id,
                user_info['id'],
                {
                    'type': 'access_revoked',
                    'mindmapId': mindmap_id,
                    'message': '当前编辑权限已失效，会话已结束',
                },
                revocation_scope='edit' if can_edit_session else 'access',
            )
            return False, True
        except Exception as error:
            room_manager.block_disconnect_persistence(websocket)
            logger.warning(
                '校验脑图实时写权限失败: '
                f'mindmap_id={mindmap_id}, user_id={user_info["id"]}, '
                f'error_type={type(error).__name__}'
            )
            # 基础设施故障不等同于会话或权限失效。发送 retryable auth_error，
            # 让客户端保留本地 Y.Doc 和未保存修改并沿既有退避自动重连；
            # session_ended 会被前端解释为永久终止并销毁协作状态。
            await close_websocket_with_error(
                websocket,
                get_ws_auth_error_payload(WsAuthenticationError(
                    '权限校验服务暂时不可用，请稍后重试',
                    code='access_check_unavailable',
                    retryable=True,
                )),
                WS_RETRY_LATER_CLOSE_CODE,
            )
            return False, True
        if revision_error:
            await room_manager.send_to(websocket, revision_error)
            return False, False
        return True, False

    async def reconcile_message_lineage(
        client_revision: object,
        lineage_id: str,
    ) -> bool:
        """用 sticky authority 恢复漏掉 seed Pub/Sub 的本 worker 栅栏。"""
        if not await room_manager.verify_content_lineage_fence(
            mindmap_id,
            client_revision,
            lineage_id,
        ):
            return False
        local_compatible = room_manager.is_content_lineage_compatible(
            mindmap_id,
            client_revision,
            lineage_id,
        )
        if not room_manager.set_content_lineage(
            mindmap_id,
            client_revision,
            lineage_id,
            replace=not local_compatible,
        ):
            return False
        if not local_compatible:
            await room_manager.disconnect_stale_lineage_peers(
                mindmap_id,
                websocket,
                client_revision,
            )
        return True

    def connection_write_remains_enabled() -> bool:
        enabled = room_manager.is_connection_write_enabled(
            mindmap_id, websocket,
        )
        if not enabled:
            room_manager.block_disconnect_persistence(websocket)
        return enabled

    async def persist_latest_state(
        *,
        force: bool = False,
        context: str = '',
        establish_lineage: bool = False,
    ) -> str:
        """按连接来源保存最近完整状态，区分节流与真实失败。"""
        nonlocal last_persist_time, latest_replace_source_ids
        nonlocal latest_replace_source_digests
        if not latest_state_bytes:
            return YJS_PERSIST_FAILED
        now = time.monotonic()
        if not force and (now - last_persist_time) < PERSIST_INTERVAL_SECONDS:
            return YJS_PERSIST_THROTTLED
        try:
            async with AsyncSessionLocal() as db:
                saved = await persist_authorized_yjs_state(
                    db,
                    mindmap_id,
                    user_info['id'],
                    latest_state_bytes,
                    latest_state_revision,
                    source_id=state_source_id,
                    replace_source_ids=latest_replace_source_ids,
                    replace_source_digests=latest_replace_source_digests,
                    lineage_id=latest_state_lineage_id,
                    manager=room_manager,
                    enforce_lineage_fence=not establish_lineage,
                )
            if saved:
                if (
                    latest_state_lineage_id is None
                    or type(latest_state_revision) is not int
                    or not await reconcile_persisted_lineage_fence(
                        room_manager,
                        mindmap_id,
                        latest_state_revision,
                        latest_state_lineage_id,
                    )
                ):
                    record_mindmap_event('yjs_lineage_mismatch')
                    return YJS_PERSIST_FAILED
                last_persist_time = now
                latest_replace_source_ids = []
                latest_replace_source_digests = {}
                return YJS_PERSIST_SAVED
            record_mindmap_event('yjs_state_persist_failure')
            return YJS_PERSIST_FAILED
        except Exception as error:
            record_mindmap_event('yjs_state_persist_failure')
            prefix = f'{context}时' if context else ''
            logger.error(f'{prefix}持久化 Yjs 状态失败: {error}')
            return YJS_PERSIST_FAILED

    try:
        while True:
            data = await websocket.receive_json()
            if not room_manager.is_connection_active(websocket):
                break
            msg_type = get_ws_client_message_type(data)
            if not traffic_budget.allow_message(msg_type):
                await close_websocket_with_error(
                    websocket,
                    get_ws_rate_limit_payload(),
                    WS_RETRY_LATER_CLOSE_CODE,
                )
                break
            if msg_type is None:
                await room_manager.send_to(websocket, get_ws_invalid_message_payload())
                continue

            if msg_type in ('sync_step1', 'sync_step2', 'update'):
                if not can_edit_session:
                    await room_manager.send_to(
                        websocket,
                        get_ws_write_capability_error_payload(
                            missing_write_capabilities,
                        ) if missing_write_capabilities else {
                            'type': 'protocol_error',
                            'code': 'readonly_session',
                            'message': '当前为只读协作连接，拒绝写入协作消息',
                        },
                    )
                    continue
                if not traffic_budget.allow_payload(
                    get_ws_encoded_payload_size(data, msg_type)
                ):
                    await close_websocket_with_error(
                        websocket,
                        get_ws_rate_limit_payload(),
                        WS_RETRY_LATER_CLOSE_CODE,
                    )
                    break
                update_b64 = data.get('update')
                update_bytes = decode_base64_payload(
                    update_b64,
                    get_yjs_update_payload_limit(data, msg_type),
                )
                if update_bytes is None:
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'message': 'Yjs 更新格式无效或超过大小限制',
                    })
                    continue
                state_b64 = data.get('state', '')
                state_bytes = None
                if state_b64:
                    state_bytes = decode_base64_payload(state_b64, MAX_YJS_STATE_BYTES)
                    if state_bytes is None:
                        await room_manager.send_to(websocket, {
                            'type': 'protocol_error',
                            'message': 'Yjs 完整状态格式无效或超过大小限制',
                        })
                        continue
                # 旧版 sync_step 消息与 update 一样会改变共享 Yjs 文档，
                # 必须经过同一 revision 栅栏，不能绕过云端重置后继续广播。
                client_revision = data.get('contentRevision')
                mutation_allowed, terminate_loop = (
                    await authorize_shared_document_mutation(client_revision)
                )
                if not mutation_allowed:
                    if terminate_loop:
                        break
                    continue
                patch = None
                if data.get('patch') is not None:
                    normalized_patch = _normalize_yjs_patch_with_size(data.get('patch'))
                    if normalized_patch is None:
                        await room_manager.send_to(websocket, {
                            'type': 'protocol_error',
                            'message': 'Yjs 节点修复补丁格式无效或超过大小限制',
                        })
                        continue
                    patch, patch_size = normalized_patch
                    if not traffic_budget.allow_payload(patch_size):
                        await close_websocket_with_error(
                            websocket,
                            get_ws_rate_limit_payload(),
                            WS_RETRY_LATER_CLOSE_CODE,
                        )
                        break

                raw_mutation_id = data.get('clientMutationId')
                mutation_id = normalize_client_mutation_id(raw_mutation_id)
                mutation_update_seq = normalize_mutation_update_sequence(
                    data.get('mutationUpdateSeq'),
                )
                raw_lineage_id = data.get('lineageId')
                lineage_id = normalize_yjs_lineage_id(raw_lineage_id)
                if raw_mutation_id is not None and mutation_id is None:
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'invalid_client_mutation_id',
                        'message': 'Yjs 更新携带了非法的批次标识',
                    })
                    continue
                if (
                    YJS_MUTATION_SEQUENCE_CAPABILITY in capabilities
                    and (
                        (mutation_id and mutation_update_seq is None)
                        or (mutation_update_seq is not None and not mutation_id)
                    )
                ):
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'invalid_mutation_sequence',
                        'message': 'Yjs 更新的批次标识与合法序号必须同时提供',
                    })
                    continue
                if (
                    YJS_LINEAGE_CAPABILITY in capabilities
                    and lineage_id is None
                ):
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'invalid_yjs_lineage',
                        'message': 'Yjs 更新缺少合法的协作基线标识',
                    })
                    continue
                authoritative_seed = await can_forward_ws_authoritative_seed(
                    room_manager,
                    mindmap_id,
                    websocket,
                    msg_type=msg_type,
                    data=data,
                    mutation_id=mutation_id,
                    update_bytes=update_bytes,
                    state_bytes=state_bytes,
                    patch=patch,
                )
                if data.get('seedState') is True and not authoritative_seed:
                    # seedState 会让接收端把完整状态视为 HTTP 权威基线，必须
                    # 严格拒绝非租约持有者，不能只移除标志后仍持久化/广播一份
                    # 独立初始化的同名 Yjs 文档。
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'invalid_seed_lease',
                        'message': '协作初始化租约已失效，请重新同步',
                    })
                    continue

                if (
                    lineage_id
                    and not authoritative_seed
                    and not await reconcile_message_lineage(
                        client_revision,
                        lineage_id,
                    )
                ):
                    # 同 revision 的另一条 Y.Doc 创建历史不能继续广播。让败方
                    # 静默回源重建，并禁止 finally 把它的完整状态写回缓存。
                    room_manager.block_disconnect_persistence(websocket)
                    await close_websocket_with_error(websocket, {
                        'type': 'stale_state',
                        'currentRevision': room_manager.get_content_revision(mindmap_id),
                        'reason': 'yjs_lineage_changed',
                        'message': '协作基线已更新，正在使用云端内容重新同步',
                    }, WS_RETRY_LATER_CLOSE_CODE)
                    break

                if not connection_write_remains_enabled():
                    break
                # 普通 update.state 只是实时兼容载荷，可能包含断线期间尚未
                # 通过 HTTP 提交的删除或移动，不能写成当前 revision 的持久
                # 基线，也不能留给 disconnect finally 补写。只有租约持有者
                # 生成的 HTTP 权威种子可以在 update 分支持久化；后续安全
                # 状态统一由经过 revision/权限复核的 checkpoint 分支保存。
                if authoritative_seed and state_bytes:
                    latest_state_bytes = state_bytes
                    latest_state_revision = data.get('contentRevision')
                    latest_state_lineage_id = lineage_id
                    # 权威种子可能是在客户端隔离了同 revision 的损坏/分叉
                    # 检查点后产生。它只有携带本次握手所见全部来源的摘要，
                    # 才能在数据库行锁内完成无丢失的 lineage 切换。
                    latest_replace_source_ids = list(
                        replaceable_state_source_digests
                    )
                    latest_replace_source_digests = dict(
                        replaceable_state_source_digests
                    )
                persist_result = YJS_PERSIST_SAVED
                if authoritative_seed:
                    # 权威种子是空房间后续所有连接的唯一基线，不能受普通
                    # 30 秒检查点节流影响；否则进程启动后 monotonic 尚未
                    # 超过节流周期时，首个种子会被当作保存失败并反复重连。
                    persist_result = await persist_latest_state(
                        force=True,
                        establish_lineage=True,
                    )
                if (
                    authoritative_seed
                    and persist_result != YJS_PERSIST_SAVED
                ):
                    # 租约资格已经一次性消费。此次失败后 finally 不能
                    # 再次落库，否则可能在没有切换房间 lineage/广播 seed
                    # 的情况下偷渡一份新的 DB 基线。
                    room_manager.block_disconnect_persistence(websocket)
                    await close_websocket_with_error(websocket, {
                        'type': 'protocol_error',
                        'code': 'seed_persist_failed',
                        'message': '协作初始化状态暂未保存，正在重新连接',
                    }, WS_RETRY_LATER_CLOSE_CODE)
                    break
                if authoritative_seed and lineage_id:
                    # save_state 的 revision + source digest CAS 已经先完成；此时
                    # 才允许本 worker 以及 Redis 对端切换房间 lineage。
                    if not room_manager.set_content_lineage(
                        mindmap_id,
                        client_revision,
                        lineage_id,
                        replace=True,
                    ):
                        # DB 提交后正文 revision 可能已经再次推进。旧
                        # revision 的 seed 仍不能广播到已进入新世代的本地房间。
                        room_manager.block_disconnect_persistence(websocket)
                        await close_websocket_with_error(websocket, {
                            'type': 'stale_state',
                            'currentRevision': room_manager.get_content_revision(mindmap_id),
                            'reason': 'yjs_lineage_changed',
                            'message': '协作基线已更新，正在使用云端内容重新同步',
                        }, WS_RETRY_LATER_CLOSE_CODE)
                        break
                    replaceable_state_source_digests.clear()

                if not connection_write_remains_enabled():
                    break
                correlation = {'contentRevision': data.get('contentRevision')}
                if lineage_id:
                    correlation['lineageId'] = lineage_id
                if mutation_id:
                    correlation['clientMutationId'] = mutation_id
                if mutation_update_seq is not None:
                    correlation['mutationUpdateSeq'] = mutation_update_seq
                if authoritative_seed:
                    # 只有当前 revision 的租约持有者可声明“这是纯 HTTP
                    # 权威基线”。接收端据此避免把首次种子误当成尚未落库的
                    # 协作操作；普通重连快照和带 mutationId 的修改不能伪装。
                    correlation['seedState'] = True
                outbound_update = {
                    'type': msg_type,
                    'update': update_b64,
                    **correlation,
                    # RoomManager 按接收端能力裁剪：新客户端省略完整状态，
                    # 旧客户端在滚动升级期仍收到 state。
                    'state': state_b64 or None,
                    'patch': patch,
                    'origin': str(user_info['id']),
                }
                if (
                    lineage_id is None
                    or not await room_manager.broadcast_with_lineage_fence(
                        mindmap_id,
                        outbound_update,
                        content_revision=client_revision,
                        lineage_id=lineage_id,
                        exclude=websocket,
                    )
                ):
                    room_manager.block_disconnect_persistence(websocket)
                    await close_websocket_with_error(websocket, {
                        'type': 'stale_state',
                        'currentRevision': room_manager.get_content_revision(mindmap_id),
                        'reason': 'yjs_lineage_changed',
                        'message': '协作基线已更新，正在使用云端内容重新同步',
                    }, WS_RETRY_LATER_CLOSE_CODE)
                    break

            elif msg_type == 'checkpoint':
                if not can_edit_session:
                    await room_manager.send_to(
                        websocket,
                        get_ws_write_capability_error_payload(
                            missing_write_capabilities,
                        ) if missing_write_capabilities else {
                            'type': 'protocol_error',
                            'code': 'readonly_session',
                            'message': '当前为只读协作连接，拒绝写入检查点',
                        },
                    )
                    continue
                if not traffic_budget.allow_payload(
                    get_ws_encoded_payload_size(data, msg_type)
                ):
                    await close_websocket_with_error(
                        websocket,
                        get_ws_rate_limit_payload(),
                        WS_RETRY_LATER_CLOSE_CODE,
                    )
                    break
                if YJS_CHECKPOINT_CAPABILITY not in capabilities:
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'message': '当前连接未协商 Yjs 检查点协议',
                    })
                    continue
                checkpoint_lineage_id = normalize_yjs_lineage_id(
                    data.get('lineageId')
                )
                if (
                    YJS_LINEAGE_CAPABILITY in capabilities
                    and checkpoint_lineage_id is None
                ):
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'invalid_yjs_lineage',
                        'message': 'Yjs 检查点缺少合法的协作基线标识',
                    })
                    continue
                client_revision = data.get('contentRevision')
                mutation_allowed, terminate_loop = (
                    await authorize_shared_document_mutation(client_revision)
                )
                if not mutation_allowed:
                    if terminate_loop:
                        break
                    continue
                state_b64 = data.get('state')
                state_bytes = decode_base64_payload(state_b64, MAX_YJS_STATE_BYTES)
                if state_bytes is None:
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'message': 'Yjs 检查点格式无效或超过大小限制',
                    })
                    continue
                source_changes = normalize_yjs_state_source_changes(
                    data.get('replacesSources', []),
                    data.get('invalidSources', []),
                )
                if source_changes is None:
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'message': 'Yjs 状态源修复列表无效',
                    })
                    continue
                replace_source_ids, invalid_source_ids, replacement_ids = source_changes
                if (
                    replacement_ids
                    and YJS_SOURCE_CAS_CAPABILITY not in capabilities
                ):
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'state_source_cas_capability_required',
                        'message': '协作状态清理协议已升级，请重新同步',
                    })
                    continue
                replacement_digests = normalize_yjs_state_source_digests(
                    data.get('sourceDigests', {}),
                    replacement_ids,
                )
                if replacement_digests is None:
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'invalid_state_source_digests',
                        'message': 'Yjs 状态源摘要无效',
                    })
                    continue
                if not are_yjs_state_replacements_authorized(
                    replaceable_state_source_digests,
                    replacement_ids,
                    replacement_digests,
                ):
                    await room_manager.send_to(websocket, {
                        'type': 'protocol_error',
                        'code': 'unrecognized_state_sources',
                        'message': 'Yjs 状态源不属于当前同步快照',
                    })
                    continue
                if (
                    checkpoint_lineage_id
                    and not await reconcile_message_lineage(
                        client_revision,
                        checkpoint_lineage_id,
                    )
                ):
                    room_manager.block_disconnect_persistence(websocket)
                    await close_websocket_with_error(websocket, {
                        'type': 'stale_state',
                        'currentRevision': room_manager.get_content_revision(mindmap_id),
                        'reason': 'yjs_lineage_changed',
                        'message': '协作基线已更新，正在使用云端内容重新同步',
                    }, WS_RETRY_LATER_CLOSE_CODE)
                    break
                if invalid_source_ids:
                    logger.warning(
                        '客户端隔离损坏的 Yjs 持久化来源: '
                        f'mindmap_id={mindmap_id}, user_id={user_info["id"]}, '
                        f'invalid_source_count={len(invalid_source_ids)}'
                    )

                if not connection_write_remains_enabled():
                    break
                latest_state_bytes = state_bytes
                latest_state_revision = client_revision
                latest_state_lineage_id = checkpoint_lineage_id
                if replacement_ids:
                    latest_replace_source_ids = replacement_ids
                    latest_replace_source_digests = replacement_digests
                # 房间尚未建立 lineage 时，首个 checkpoint 必须经过
                # DB fence 成功后才能成为提交点，不能被进程启动初期的
                # 30 秒节流直接跳过。
                must_establish_lineage = bool(
                    checkpoint_lineage_id
                    and not room_manager.has_content_lineage(
                        mindmap_id,
                        client_revision,
                    )
                )
                persist_result = await persist_latest_state(
                    force=bool(replacement_ids) or must_establish_lineage,
                    context='状态修复' if invalid_source_ids else (
                        '状态压缩' if replace_source_ids else '检查点'
                    ),
                    establish_lineage=must_establish_lineage,
                )
                if persist_result == YJS_PERSIST_FAILED:
                    # DB 拒绝与纯节流必须区分。真实失败可能是
                    # revision/lineage/CAS fence 命中，不得继续切换本地房间或
                    # 将该检查点广播为已接受状态，finally 也不能重试偷渡。
                    room_manager.block_disconnect_persistence(websocket)
                    await close_websocket_with_error(websocket, {
                        'type': 'protocol_error',
                        'code': 'checkpoint_persist_failed',
                        'message': '协作检查点暂未保存，正在重新连接',
                    }, WS_RETRY_LATER_CLOSE_CODE)
                    break
                if persist_result == YJS_PERSIST_SAVED:
                    for source_id in replacement_ids:
                        replaceable_state_source_digests.pop(source_id, None)

                if not connection_write_remains_enabled():
                    break
                checkpoint_broadcasted = await room_manager.broadcast_checkpoint(
                    mindmap_id,
                    state_b64,
                    str(user_info['id']),
                    client_revision,
                    exclude=websocket,
                    lineage_id=checkpoint_lineage_id,
                )
                if not checkpoint_broadcasted:
                    room_manager.block_disconnect_persistence(websocket)
                    await close_websocket_with_error(websocket, {
                        'type': 'stale_state',
                        'currentRevision': room_manager.get_content_revision(mindmap_id),
                        'reason': 'yjs_lineage_changed',
                        'message': '协作基线已更新，正在使用云端内容重新同步',
                    }, WS_RETRY_LATER_CLOSE_CODE)
                    break

            elif msg_type == 'request_seed':
                client_revision = data.get('contentRevision')
                if not can_edit_session:
                    await room_manager.send_to(
                        websocket,
                        get_ws_write_capability_error_payload(
                            missing_write_capabilities,
                        ) if missing_write_capabilities else {
                            'type': 'protocol_error',
                            'code': 'readonly_session',
                            'message': '当前为只读协作连接，拒绝初始化共享文档',
                        },
                    )
                    continue
                # 初始化种子最终会成为整个房间的共享基线，不能只依赖本
                # worker 的缓存 revision。和 update/checkpoint 一样在数据库
                # 行锁内复核当前编辑权限及权威 revision，再竞争种子租约。
                mutation_allowed, terminate_loop = (
                    await authorize_shared_document_mutation(client_revision)
                )
                if not mutation_allowed:
                    if terminate_loop:
                        break
                    continue
                if not connection_write_remains_enabled():
                    break
                current_revision = room_manager.get_content_revision(mindmap_id)
                granted = await acquire_ws_seed_lease(
                    room_manager,
                    mindmap_id,
                    client_revision,
                    websocket,
                    can_edit_session=can_edit_session,
                )
                await room_manager.send_to(websocket, {
                    'type': 'seed_granted' if granted else 'seed_pending',
                    'contentRevision': current_revision,
                })

            elif msg_type == 'node_edit_lease_acquire':
                request_id = normalize_node_edit_lease_request_id(
                    data.get('requestId')
                )
                node_uid = normalize_node_edit_lease_uid(data.get('nodeUid'))
                client_revision = data.get('contentRevision')
                renewal = (
                    data.get('renewal') is True
                    and NODE_EDIT_LEASE_RENEWAL_CAPABILITY in capabilities
                )
                if (
                    request_id is None
                    or node_uid is None
                    or type(client_revision) is not int
                ):
                    await room_manager.send_to(
                        websocket,
                        get_ws_invalid_message_payload(),
                    )
                    continue
                lease_result: bool | None = None
                failure_reason = 'readonly' if not can_edit_session else 'unavailable'
                if (
                    can_edit_session
                    and NODE_EDIT_LEASE_CAPABILITY in capabilities
                ):
                    mutation_allowed, terminate_loop = (
                        await authorize_shared_document_mutation(
                            client_revision,
                            require_current_revision=not renewal,
                        )
                    )
                    if not mutation_allowed:
                        if terminate_loop:
                            break
                        continue
                    if not connection_write_remains_enabled():
                        break
                    if renewal:
                        lease_result = await room_manager.renew_node_edit_lease(
                            mindmap_id,
                            node_uid,
                            websocket,
                        )
                    else:
                        lease_result = await room_manager.acquire_node_edit_lease(
                            mindmap_id,
                            client_revision,
                            node_uid,
                            websocket,
                        )
                    if lease_result is False and not renewal:
                        failure_reason = 'occupied'
                granted = lease_result is True
                response = {
                    'type': 'node_edit_lease_result',
                    'requestId': request_id,
                    'nodeUid': node_uid,
                    'granted': granted,
                }
                if not granted:
                    response['reason'] = failure_reason
                await room_manager.send_to(websocket, response)

            elif msg_type == 'node_edit_lease_release':
                node_uid = normalize_node_edit_lease_uid(data.get('nodeUid'))
                if node_uid is None:
                    await room_manager.send_to(
                        websocket,
                        get_ws_invalid_message_payload(),
                    )
                    continue
                if NODE_EDIT_LEASE_CAPABILITY in capabilities:
                    await room_manager.release_node_edit_lease(
                        mindmap_id,
                        node_uid,
                        websocket,
                    )

            elif msg_type == 'pong':
                # 心跳响应，重置未响应计数
                missed_pongs = 0

            elif msg_type == 'awareness':
                # 转发节点选区和实际文本编辑占用；忽略客户端声明的用户
                # 信息，防止身份伪造。只读会话不能声明 editingNodeUid，
                # 因而不能阻塞真实编辑者。
                editing_node_uid = (
                    normalize_awareness_editing_node_uid(data)
                    if can_edit_session
                    else ''
                )
                if (
                    editing_node_uid
                    and NODE_EDIT_LEASE_CAPABILITY in capabilities
                    and not await room_manager.owns_node_edit_lease(
                        mindmap_id,
                        editing_node_uid,
                        websocket,
                    )
                ):
                    editing_node_uid = ''
                await room_manager.broadcast(
                    mindmap_id,
                    {
                        'type': 'awareness',
                        'user': user_info,
                        'sessionId': state_source_id,
                        'nodeUids': (
                            normalize_awareness_node_uids(data)
                            if can_edit_session
                            else []
                        ),
                        'editingNodeUid': editing_node_uid,
                    },
                    exclude=websocket,
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f'WebSocket 错误: {e}')
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        # 编辑占用是短期 Presence，必须先释放；不能让可能较慢的断开检查点
        # 持久化把其他浏览器阻塞到超时兜底。正文仍在离开房间前完成保存。
        allow_disconnect_persistence = room_manager.consume_disconnect_persistence_permission(websocket)
        await room_manager.release_connection_node_edit_leases(websocket)
        await room_manager.broadcast(
            mindmap_id,
            {
                'type': 'awareness',
                'user': user_info,
                'sessionId': state_source_id,
                'nodeUids': [],
                'editingNodeUid': '',
            },
            exclude=websocket,
        )
        # 断开时最终保存 Yjs 状态；被删除/撤权而强制终止的连接禁止回写。
        if latest_state_bytes and allow_disconnect_persistence:
            await persist_latest_state(force=True, context='断开')
        await room_manager.leave(mindmap_id, websocket)
        users = await room_manager.get_room_users(mindmap_id)
        await room_manager.broadcast(
            mindmap_id,
            {'type': 'room_users', 'users': users},
        )
