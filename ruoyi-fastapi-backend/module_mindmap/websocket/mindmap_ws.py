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

from fastapi import WebSocket, WebSocketDisconnect

from config.database import AsyncSessionLocal
from exceptions.exception import ServiceException
from module_mindmap.service.mindmap_document_service import (
    STRUCTURED_CONTENT_CORRUPT_MESSAGE,
    MindmapDocumentService,
)
from module_mindmap.service.mindmap_metrics import record_mindmap_event
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION
from module_mindmap.websocket.room_manager import (
    STRUCTURED_NODE_PATCH_CAPABILITY,
    YJS_CHECKPOINT_CAPABILITY,
    room_manager,
)
from module_mindmap.websocket.ws_auth import WsAuthenticationError, validate_ws_token
from module_mindmap.websocket.yjs_doc import (
    YjsDocManager,
    normalize_yjs_state_source_changes,
)
from utils.log_util import logger

# 认证超时：连接后 10 秒内必须发送 auth 消息
AUTH_TIMEOUT_SECONDS = 10
# Yjs 状态持久化间隔：每 30 秒最多持久化一次
PERSIST_INTERVAL_SECONDS = 30
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


def get_ws_rate_limit_payload() -> dict:
    return {
        'type': 'protocol_error',
        'code': 'rate_limited',
        'message': '协作消息发送过于频繁，请稍后重试',
    }


def normalize_client_mutation_id(value: object) -> str | None:
    """只转发可由 HTTP 保存契约接受的批次标识。"""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_CLIENT_MUTATION_ID_LENGTH:
        return None
    return normalized


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


def normalize_ws_capabilities(payload: object) -> set[str]:
    """只协商服务端已实现的协议能力，忽略客户端任意声明。"""
    if not isinstance(payload, list):
        return set()
    return {
        capability
        for capability in payload
        if capability in {
            STRUCTURED_NODE_PATCH_CAPABILITY,
            YJS_CHECKPOINT_CAPABILITY,
        }
    }


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
    }
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
        if not isinstance(raw_node, dict):
            return None
        uid = raw_node.get('uid')
        node_data = raw_node.get('data')
        children = raw_node.get('children')
        if (
            not isinstance(uid, str)
            or not uid.strip()
            or len(uid.strip()) > MAX_NODE_UID_LENGTH
            or not isinstance(node_data, dict)
            or not isinstance(children, list)
        ):
            return None
        normalized_children = []
        for child_uid in children:
            if (
                not isinstance(child_uid, str)
                or not child_uid.strip()
                or len(child_uid.strip()) > MAX_NODE_UID_LENGTH
            ):
                return None
            normalized_children.append(child_uid.strip())
        child_count += len(normalized_children)
        if child_count > MAX_YJS_PATCH_CHILD_COUNT:
            return None
        nodes.append({
            'uid': uid.strip(),
            'data': node_data,
            'children': normalized_children,
        })

    deleted_node_uids = []
    for uid in raw_deleted_uids:
        if (
            not isinstance(uid, str)
            or not uid.strip()
            or len(uid.strip()) > MAX_NODE_UID_LENGTH
        ):
            return None
        deleted_node_uids.append(uid.strip())

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


async def mindmap_websocket_endpoint(websocket: WebSocket, mindmap_id: int) -> None:  # noqa: PLR0912, PLR0915
    """脑图实时协作 WebSocket 端点"""
    await websocket.accept()
    state_source_id = uuid.uuid4().hex

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
    try:
        async with AsyncSessionLocal() as db:
            mindmap = await MindmapService.check_mindmap_access(
                db, mindmap_id, user_info['id'], require_edit=True,
            )
            if getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION:
                await MindmapDocumentService.load_tree(db, mindmap_id, required=True)
    except ServiceException as exc:
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

    # 认证通过
    capabilities = normalize_ws_capabilities(auth_msg.get('capabilities'))
    auth_ok_sent = await room_manager.send_to(websocket, {
        'type': 'auth_ok',
        'user': user_info,
        'capabilities': sorted(capabilities),
    })
    if not auth_ok_sent:
        return
    await room_manager.join(mindmap_id, websocket, user_info, capabilities)
    room_manager.set_content_revision(mindmap_id, mindmap.content_revision)

    # 广播跨实例权威成员快照，避免同一用户多标签页导致重复或误离线。
    users = await room_manager.get_room_users(mindmap_id)
    await room_manager.broadcast(mindmap_id, {'type': 'room_users', 'users': users})

    # 加载持久化的 Yjs 状态
    state_entries = {}
    try:
        async with AsyncSessionLocal() as db:
            state_entries = await YjsDocManager.load_state_entries(db, mindmap_id)
            sync_init_payload = build_yjs_sync_init_payload(
                state_entries,
                include_legacy_state=YJS_CHECKPOINT_CAPABILITY not in capabilities,
            )
            if sync_init_payload:
                await room_manager.send_to(websocket, sync_init_payload)
    except Exception as e:
        record_mindmap_event('yjs_state_load_failure')
        logger.error(f'加载 Yjs 状态失败: {e}')
    if not state_entries:
        await room_manager.send_to(websocket, {
            'type': 'seed_pending',
            'contentRevision': mindmap.content_revision,
        })
    # 数据库检查点最多落后一个周期；每次加入都请现有客户端补发当前完整状态。
    # 全新房间里没有数据的新连接会忽略该请求，随后仍由种子租约完成初始化。
    await room_manager.broadcast(
        mindmap_id,
        {
            'type': 'seed_request',
            'contentRevision': mindmap.content_revision,
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
                    async with AsyncSessionLocal() as db:
                        await MindmapService.check_mindmap_access(
                            db, mindmap_id, user_info['id'], require_edit=True,
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
                    if not await room_manager.send_to(websocket, {'type': 'ping'}):
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
    latest_replace_source_ids: list[str] = []
    traffic_budget = WebSocketTrafficBudget()

    async def persist_latest_state(*, force: bool = False, context: str = '') -> bool:
        """按连接来源保存最近完整状态；失败时保留重试机会。"""
        nonlocal last_persist_time, latest_replace_source_ids
        if not latest_state_bytes:
            return False
        now = time.monotonic()
        if not force and (now - last_persist_time) < PERSIST_INTERVAL_SECONDS:
            return False
        try:
            async with AsyncSessionLocal() as db:
                saved = await YjsDocManager.save_state(
                    db,
                    mindmap_id,
                    latest_state_bytes,
                    latest_state_revision,
                    source_id=state_source_id,
                    replace_source_ids=latest_replace_source_ids,
                )
            if saved:
                last_persist_time = now
                latest_replace_source_ids = []
            else:
                record_mindmap_event('yjs_state_persist_failure')
            return saved
        except Exception as error:
            record_mindmap_event('yjs_state_persist_failure')
            prefix = f'{context}时' if context else ''
            logger.error(f'{prefix}持久化 Yjs 状态失败: {error}')
            return False

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
                if decode_base64_payload(update_b64, MAX_YJS_UPDATE_BYTES) is None:
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
                if msg_type == 'update':
                    client_revision = data.get('contentRevision')
                    current_revision = room_manager.get_content_revision(mindmap_id)
                    if not room_manager.is_current_revision(mindmap_id, client_revision):
                        await room_manager.send_to(websocket, {
                            'type': 'stale_state',
                            'message': '协作状态已落后，正在合并服务器最新内容',
                            'currentRevision': current_revision,
                        })
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

                # 节流持久化：每 30 秒最多一次
                if state_bytes:
                    latest_state_bytes = state_bytes
                    latest_state_revision = data.get('contentRevision')
                if msg_type == 'update' and state_bytes:
                    await persist_latest_state()

                # 首个种子状态先持久化再转发，避免恰好在广播之后加入的连接
                # 查不到状态并独立创建同名嵌套 Yjs 类型。
                mutation_id = normalize_client_mutation_id(data.get('clientMutationId'))
                correlation = {'contentRevision': data.get('contentRevision')}
                if mutation_id:
                    correlation['clientMutationId'] = mutation_id
                await room_manager.broadcast(
                    mindmap_id,
                    {
                        'type': msg_type,
                        'update': update_b64,
                        **(correlation if msg_type == 'update' else {}),
                        # RoomManager 按接收端能力裁剪：新客户端省略完整状态，
                        # 旧客户端在滚动升级期仍收到 state。
                        'state': state_b64 or None,
                        'patch': patch,
                        'origin': str(user_info['id']),
                    },
                    exclude=websocket,
                )

            elif msg_type == 'checkpoint':
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
                client_revision = data.get('contentRevision')
                current_revision = room_manager.get_content_revision(mindmap_id)
                if not room_manager.is_current_revision(mindmap_id, client_revision):
                    await room_manager.send_to(websocket, {
                        'type': 'stale_state',
                        'message': '协作状态已落后，正在合并服务器最新内容',
                        'currentRevision': current_revision,
                    })
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
                if invalid_source_ids:
                    logger.warning(
                        '客户端隔离损坏的 Yjs 持久化来源: '
                        f'mindmap_id={mindmap_id}, user_id={user_info["id"]}, '
                        f'invalid_source_count={len(invalid_source_ids)}'
                    )

                latest_state_bytes = state_bytes
                latest_state_revision = client_revision
                if replacement_ids:
                    latest_replace_source_ids = replacement_ids
                await persist_latest_state(
                    force=bool(replacement_ids),
                    context='状态修复' if invalid_source_ids else (
                        '状态压缩' if replace_source_ids else '检查点'
                    ),
                )

                await room_manager.broadcast_checkpoint(
                    mindmap_id,
                    state_b64,
                    str(user_info['id']),
                    exclude=websocket,
                )

            elif msg_type == 'request_seed':
                client_revision = data.get('contentRevision')
                current_revision = room_manager.get_content_revision(mindmap_id)
                if not room_manager.is_current_revision(mindmap_id, client_revision):
                    await room_manager.send_to(websocket, {
                        'type': 'stale_state',
                        'message': '协作状态已落后，正在合并服务器最新内容',
                        'currentRevision': current_revision,
                    })
                    continue
                granted = await room_manager.acquire_seed_lease(
                    mindmap_id,
                    client_revision,
                    websocket,
                )
                await room_manager.send_to(websocket, {
                    'type': 'seed_granted' if granted else 'seed_pending',
                    'contentRevision': current_revision,
                })

            elif msg_type == 'pong':
                # 心跳响应，重置未响应计数
                missed_pongs = 0

            elif msg_type == 'awareness':
                # 转发节点选区；忽略客户端声明的用户信息，防止身份伪造。
                await room_manager.broadcast(
                    mindmap_id,
                    {
                        'type': 'awareness',
                        'user': user_info,
                        'nodeUids': normalize_awareness_node_uids(data),
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
        # 断开时最终保存 Yjs 状态；被删除/撤权而强制终止的连接禁止回写。
        allow_disconnect_persistence = room_manager.consume_disconnect_persistence_permission(websocket)
        if latest_state_bytes and allow_disconnect_persistence:
            await persist_latest_state(force=True, context='断开')
        await room_manager.broadcast(
            mindmap_id,
            {'type': 'awareness', 'user': user_info, 'nodeUids': []},
            exclude=websocket,
        )
        await room_manager.leave(mindmap_id, websocket)
        users = await room_manager.get_room_users(mindmap_id)
        await room_manager.broadcast(
            mindmap_id,
            {'type': 'room_users', 'users': users},
        )
