"""脑图 WebSocket 房间与跨实例协作总线。"""

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from collections import deque
from contextlib import suppress
from typing import Any

from fastapi import WebSocket

from config.env import AppConfig, JwtConfig
from module_mindmap.service.mindmap_metrics import record_mindmap_event
from utils.log_util import logger

STRUCTURED_NODE_PATCH_CAPABILITY = 'structured-node-patch-v1'
CONDITIONAL_NODE_PATCH_CAPABILITY = 'conditional-node-patch-v1'
YJS_CHECKPOINT_CAPABILITY = 'yjs-checkpoint-v1'
YJS_MUTATION_SEQUENCE_CAPABILITY = 'yjs-mutation-sequence-v1'
YJS_LINEAGE_CAPABILITY = 'yjs-lineage-v1'
YJS_SOURCE_CAS_CAPABILITY = 'yjs-source-cas-v1'
CROSS_NODE_CRDT_V2_CAPABILITY = 'cross-node-crdt-v2'
NODE_EDIT_LEASE_CAPABILITY = 'node-edit-lease-v1'
NODE_EDIT_LEASE_RENEWAL_CAPABILITY = 'node-edit-lease-renewal-v1'
ROOM_WRITE_CAPABILITIES = frozenset({
    YJS_LINEAGE_CAPABILITY,
    CROSS_NODE_CRDT_V2_CAPABILITY,
    NODE_EDIT_LEASE_CAPABILITY,
})
STATIC_REQUIRED_WRITE_CAPABILITIES = ROOM_WRITE_CAPABILITIES
LINEAGE_PRESERVING_REVISION_EVENTS = frozenset({
    'content_revision_changed',
    'tag_replaced',
    'tag_unbound',
})
LINEAGE_REVISION_EVENTS = LINEAGE_PRESERVING_REVISION_EVENTS | {'document_reset'}
CROSS_INSTANCE_MESSAGE_TYPES = frozenset({
    'sync_step1',
    'sync_step2',
    'update',
    'awareness',
    'room_users',
    'seed_request',
    'content_revision_changed',
    'document_reset',
    'document_deleted',
    'document_archived',
    'access_revoked',
    'tag_definition_changed',
    'tag_replaced',
    'tag_unbound',
    'room_write_capability_required',
})
ACCESS_REVOCATION_SCOPES = frozenset({'access', 'edit'})
MAX_REDIS_EVENT_IDENTITY_LENGTH = 128
MAX_YJS_LINEAGE_ID_BYTES = 128
LINEAGE_DIGEST_HEX_LENGTH = 64
LINEAGE_FENCE_EPOCH_HEX_LENGTH = 32
LINEAGE_FENCE_SCHEMA_VERSION = 1
LINEAGE_FENCE_ACTIVE = 'active'
LINEAGE_FENCE_TOMBSTONE = 'tombstone'
REDIS_EVENT_SCHEMA_VERSION = 2
REDIS_EVENT_SIGNATURE_BYTES = 64
REDIS_EVENT_SIGNATURE_PREFIX = b',"signature":"'
REDIS_EVENT_SIGNATURE_SUFFIX = b'"}'
REDIS_EVENT_SIGNING_CONTEXT = b'mindmap-redis-events-v2'
REDIS_EVENT_MAX_AGE_MS = 2 * 60 * 1000
REDIS_EVENT_MAX_FUTURE_SKEW_MS = 30 * 1000
_REDIS_CALL_FAILED = object()
_RELEASE_SEED_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
_VERIFY_AND_RENEW_SEED_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    redis.call('expire', KEYS[1], ARGV[2])
    return 1
end
return 0
"""
_COMPARE_AND_SET_LINEAGE_FENCE_SCRIPT = """
local current = redis.call('get', KEYS[1])
if ARGV[2] == '1' then
    if current then
        return 0
    end
elseif current ~= ARGV[1] then
    return 0
end
redis.call('set', KEYS[1], ARGV[3])
return 1
"""
_VERIFY_LINEAGE_FENCE_AND_PUBLISH_SCRIPT = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then
    return -1
end
return redis.call('publish', ARGV[2], ARGV[3])
"""
_ACQUIRE_OR_RENEW_NODE_EDIT_LEASE_SCRIPT = """
local raw_fence = redis.call('get', KEYS[1])
if not raw_fence then
    return -1
end
local decoded, fence = pcall(cjson.decode, raw_fence)
if not decoded
    or fence.version ~= 1
    or fence.status ~= 'active'
    or fence.epoch ~= ARGV[1] then
    return -1
end
local current = redis.call('get', KEYS[2])
if not current then
    redis.call('set', KEYS[2], ARGV[2], 'EX', ARGV[3])
    return 1
end
if current == ARGV[2] then
    redis.call('expire', KEYS[2], ARGV[3])
    return 1
end
return 0
"""
_RENEW_OWNED_NODE_EDIT_LEASE_SCRIPT = """
local raw_fence = redis.call('get', KEYS[1])
if not raw_fence then
    return -1
end
local decoded, fence = pcall(cjson.decode, raw_fence)
if not decoded
    or fence.version ~= 1
    or fence.status ~= 'active'
    or fence.epoch ~= ARGV[1] then
    return -1
end
if redis.call('get', KEYS[2]) ~= ARGV[2] then
    return 0
end
redis.call('expire', KEYS[2], ARGV[3])
return 1
"""
_VERIFY_NODE_EDIT_LEASE_SCRIPT = """
local raw_fence = redis.call('get', KEYS[1])
if not raw_fence then
    return 0
end
local decoded, fence = pcall(cjson.decode, raw_fence)
if not decoded
    or fence.version ~= 1
    or fence.status ~= 'active'
    or fence.epoch ~= ARGV[1] then
    return 0
end
if redis.call('get', KEYS[2]) ~= ARGV[2] then
    return 0
end
return 1
"""
_OBSERVE_LINEAGE_REVISION_GAP_SCRIPT = """
local current = redis.call('get', KEYS[1])
if current ~= ARGV[1] then
    redis.call('set', KEYS[1], ARGV[1], 'PX', ARGV[3])
    return 0
end
local remaining = redis.call('pttl', KEYS[1])
if remaining < 0 then
    redis.call('set', KEYS[1], ARGV[1], 'PX', ARGV[3])
    return 0
end
if remaining <= tonumber(ARGV[3]) - tonumber(ARGV[2]) then
    return 1
end
return 0
"""


class RoomManager:
    """管理本地 WebSocket 房间，并通过 Redis 同步不同应用实例。"""

    _channel = 'mindmap:collaboration:events:v2'
    _presence_key_prefix = 'mindmap:collaboration:presence:v1:'
    _seed_key_prefix = 'mindmap:collaboration:seed:v1:'
    _node_edit_lease_key_prefix = 'mindmap:collaboration:node-edit:v2:'
    _write_capability_key_prefix = 'mindmap:collaboration:write-capability:v1:'
    _lineage_fence_key_prefix = 'mindmap:collaboration:lineage-fence:v1:'
    _lineage_gap_key_prefix = 'mindmap:collaboration:lineage-gap:v1:'
    _presence_ttl_seconds = 120
    _seed_lease_ttl_seconds = 10
    _node_edit_lease_ttl_seconds = 30
    _lineage_gap_grace_ms = 2_000
    _lineage_gap_marker_ttl_ms = 60_000
    _redis_operation_timeout_seconds = 2
    _send_timeout_seconds = 2
    _slow_consumer_close_code = 1013
    _max_seen_events = 2048
    _max_redis_event_bytes = 48 * 1024 * 1024

    def __init__(
        self,
        instance_id: str | None = None,
        event_signing_secret: str | None = None,
    ) -> None:
        signing_secret = (
            event_signing_secret
            if event_signing_secret is not None
            else JwtConfig.jwt_secret_key
        )
        if not isinstance(signing_secret, str) or not signing_secret:
            raise ValueError('脑图跨实例事件签名密钥不能为空')
        self._redis_event_signing_key = hmac.new(
            signing_secret.encode('utf-8'),
            REDIS_EVENT_SIGNING_CONTEXT,
            hashlib.sha256,
        ).digest()
        self._rooms: dict[int, set[WebSocket]] = {}
        self._user_info: dict[int, dict] = {}
        self._connection_capabilities: dict[int, set[str]] = {}
        # 一旦 v2 写端进入房间，该能力成为粘性写协议栅栏。Redis 键跨
        # worker/进程重启保留，本地缓存负责 join 与消息热路径快速拒绝。
        self._required_write_capabilities: dict[int, set[str]] = {}
        # 编辑资格属于单条连接的认证快照，而不是用户 presence。权限降级时
        # 只退休可写连接，用户随后建立的只读连接应继续接收协作更新。
        self._connection_can_edit: dict[int, bool] = {}
        self._content_revisions: dict[int, int] = {}
        # 同一正文 revision 只能对应一条 Yjs 创建历史。值保存 lineage 的
        # SHA-256，而不是用户可见标识，既固定内存占用，也与持久化来源中的
        # 摘要栅栏使用同一种比较语义。
        self._content_lineages: dict[int, tuple[int, str]] = {}
        # 单 worker 无 Redis 时也需要一条跨 revision 稳定、在 reset/新
        # seed 后切换的租约世代。Redis 模式以 sticky fence 中的 epoch
        # 为权威；本表只承载安全的单进程降级语义。
        self._local_lineage_epochs: dict[int, str] = {}
        # DB 权威复核可能恰好运行在 commit 与明确 revision 事件之间。此时
        # active lineage 必须立即清除以拒绝旧 revision 写，但暂存上一代候选，
        # 允许随后到达的同 revision 明确连续事件恢复；reset/seed 会丢弃它。
        self._pending_content_lineages: dict[int, tuple[int, str, str]] = {}
        # 持久化快照在查询期间可能与本 worker 收到的 Redis seed
        # 事件竞态。用单调代次做 compare-and-set，避免较早的数据库
        # 快照反向覆盖查询期间已经切换的更新 lineage。
        self._content_lineage_generations: dict[int, int] = {}
        self._connection_presence: dict[int, tuple[int, str, str]] = {}
        self._send_locks: dict[int, asyncio.Lock] = {}
        self._retiring_connections: set[int] = set()
        self._blocked_disconnect_persistence: set[int] = set()
        self._local_seed_leases: dict[tuple[int, int], tuple[int, float]] = {}
        # (mindmap_id, lineage_epoch, node_uid) ->
        # (websocket_id, Redis owner, deadline)。
        # Redis 是跨 worker 的权威仲裁；本表只用于连接退出时精确释放和
        # 单 worker 无 Redis 时的安全降级。
        self._local_node_edit_leases: dict[
            tuple[int, str, str], tuple[int, str, float]
        ] = {}
        self._lock = asyncio.Lock()
        self._redis: Any | None = None
        self._listener_task: asyncio.Task | None = None
        self._listener_ready = asyncio.Event()
        self._running = False
        self._instance_id_is_explicit = instance_id is not None
        self._instance_id = instance_id or self._create_instance_id()
        self._seen_event_ids: set[str] = set()
        self._seen_event_order: deque[str] = deque()

    @property
    def instance_id(self) -> str:
        """当前应用实例的协作总线标识。"""
        return self._instance_id

    async def start(self, redis: Any) -> None:
        """启动 Redis 订阅；重复调用不会创建多个监听任务。"""
        if self._running:
            return
        if not self._instance_id_is_explicit:
            # 应用可能在 Gunicorn preload 后 fork；启动时生成可避免 worker 复用主进程标识。
            self._instance_id = self._create_instance_id()
        self._redis = redis
        self._running = True
        self._listener_ready.clear()
        self._listener_task = asyncio.create_task(
            self._listen_redis_events(),
            name=f'mindmap-room-listener-{self._instance_id[:8]}',
        )
        try:
            await asyncio.wait_for(self._listener_ready.wait(), timeout=2)
        except asyncio.TimeoutError:
            logger.warning('脑图协作 Redis 订阅尚未就绪，将在后台继续重连')

    async def stop(self) -> None:
        """停止订阅并尽力清理当前实例写入的在线成员。"""
        self._running = False
        # 先封住所有连接的新租约申请。已有申请即使正在等待 Redis，也会在
        # 回程校验中看到 retiring/已移除的 presence，并原子归还刚拿到的键。
        self._retiring_connections.update(self._connection_presence)
        task = self._listener_task
        self._listener_task = None
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        redis = self._redis
        await self._release_owned_node_edit_leases(set(self._connection_presence))
        await self._release_owned_seed_leases(set(self._connection_presence))
        presence_records = list(self._connection_presence.values())
        if redis:
            for mindmap_id, _connection_id, member in presence_records:
                await self._safe_redis_call(
                    redis.zrem(self._presence_key(mindmap_id), member),
                    operation='清理在线成员',
                )
        # Lifespan 可在同一 Python 进程内停止后再次启动（测试、热重载或
        # 托管容器优雅重启）。只清 presence 会留下幽灵房间、旧 revision
        # 和旧 socket；下一轮广播可能投递到已经退休的连接，甚至用上一轮
        # lineage 拒绝新客户端。停止边界必须释放全部进程内协作运行态。
        self._rooms.clear()
        self._user_info.clear()
        self._connection_presence.clear()
        self._send_locks.clear()
        self._retiring_connections.clear()
        self._connection_capabilities.clear()
        self._required_write_capabilities.clear()
        self._connection_can_edit.clear()
        self._blocked_disconnect_persistence.clear()
        self._local_seed_leases.clear()
        self._local_node_edit_leases.clear()
        self._content_revisions.clear()
        self._content_lineages.clear()
        self._local_lineage_epochs.clear()
        self._pending_content_lineages.clear()
        self._content_lineage_generations.clear()
        self._seen_event_ids.clear()
        self._seen_event_order.clear()
        self._redis = None
        self._listener_ready.clear()

    async def join(
        self,
        mindmap_id: int,
        websocket: WebSocket,
        user_info: dict,
        capabilities: set[str] | None = None,
        *,
        can_edit: bool = True,
    ) -> bool:
        connection_id = uuid.uuid4().hex
        member = self._serialize_presence(connection_id, user_info)
        negotiated_capabilities = set(capabilities or ())
        async with self._lock:
            required_capabilities = (
                STATIC_REQUIRED_WRITE_CAPABILITIES
                | self._required_write_capabilities.get(mindmap_id, set())
            )
            effective_can_edit = (
                can_edit is True
                and required_capabilities.issubset(negotiated_capabilities)
            )
            self._rooms.setdefault(mindmap_id, set()).add(websocket)
            self._user_info[id(websocket)] = user_info
            self._connection_capabilities[id(websocket)] = negotiated_capabilities
            self._connection_can_edit[id(websocket)] = effective_can_edit
            self._connection_presence[id(websocket)] = (mindmap_id, connection_id, member)
            self._send_locks[id(websocket)] = asyncio.Lock()
            self._retiring_connections.discard(id(websocket))
            # 强制断开标记以对象 id 为键。旧 endpoint 若在 finally 前被任务
            # 取消，标记可能来不及消费；Python 后续复用该 id 时，新连接不能
            # 继承旧会话的“禁止断开持久化”状态。
            self._blocked_disconnect_persistence.discard(id(websocket))
        await self._write_presence(mindmap_id, member)
        return effective_can_edit

    async def leave(self, mindmap_id: int, websocket: WebSocket) -> None:
        # 必须在首次 await 前标记退休。否则一个已经通过前置校验、尚在等待
        # Redis SET 的申请可能恰好落在“释放已有租约”和 detach 之间，随后
        # detach 只清本地记录而把 Redis 假锁留到 TTL。
        self._retiring_connections.add(id(websocket))
        await self._release_owned_node_edit_leases({id(websocket)})
        await self._release_owned_seed_leases({id(websocket)})
        presence = await self._detach_local_connection(websocket, mindmap_id)
        self._send_locks.pop(id(websocket), None)
        self._retiring_connections.discard(id(websocket))
        await self._remove_presence_record(presence, operation='移除在线成员')

    async def _detach_local_connection(
        self,
        websocket: WebSocket,
        expected_mindmap_id: int | None = None,
    ) -> tuple[int, str, str] | None:
        """立即从本机路由表脱离单条连接；外部 presence 清理由调用方完成。"""
        async with self._lock:
            websocket_id = id(websocket)
            presence = self._connection_presence.pop(websocket_id, None)
            mindmap_id = presence[0] if presence else expected_mindmap_id
            if mindmap_id in self._rooms:
                self._rooms[mindmap_id].discard(websocket)
                if not self._rooms[mindmap_id]:
                    del self._rooms[mindmap_id]
                    self._content_revisions.pop(mindmap_id, None)
                    self._content_lineages.pop(mindmap_id, None)
                    self._local_lineage_epochs.pop(mindmap_id, None)
                    self._pending_content_lineages.pop(mindmap_id, None)
                    self._content_lineage_generations.pop(mindmap_id, None)
                    self._clear_local_seed_leases(mindmap_id)
                    self._clear_local_node_edit_leases(mindmap_id)
            self._user_info.pop(websocket_id, None)
            self._connection_capabilities.pop(websocket_id, None)
            self._connection_can_edit.pop(websocket_id, None)
            # 租约只属于当前连接实例。连接退出后立刻移除本地所有权，既让
            # 单 worker 降级模式的下一位编辑者能接管，也避免对象 id 复用
            # 时把旧连接的权威种子资格授给无关的新连接。
            for key in [
                key
                for key, lease in self._local_seed_leases.items()
                if lease[0] == websocket_id
            ]:
                self._local_seed_leases.pop(key, None)
            for key in [
                key
                for key, lease in self._local_node_edit_leases.items()
                if lease[0] == websocket_id
            ]:
                self._local_node_edit_leases.pop(key, None)
            return presence

    async def _remove_presence_record(
        self,
        presence: tuple[int, str, str] | None,
        *,
        operation: str,
    ) -> None:
        if presence and self._redis:
            await self._safe_redis_call(
                self._redis.zrem(self._presence_key(presence[0]), presence[2]),
                operation=operation,
            )

    def is_connection_active(self, websocket: WebSocket) -> bool:
        """发送失败后即刻停止该连接继续参与房间收发。"""
        websocket_id = id(websocket)
        return (
            websocket_id in self._connection_presence
            and websocket_id not in self._retiring_connections
        )

    def is_connection_write_enabled(
        self,
        mindmap_id: int,
        websocket: WebSocket,
    ) -> bool:
        websocket_id = id(websocket)
        capabilities = self._connection_capabilities.get(websocket_id, set())
        required = (
            STATIC_REQUIRED_WRITE_CAPABILITIES
            | self._required_write_capabilities.get(mindmap_id, set())
        )
        return (
            self.is_connection_active(websocket)
            and self._connection_can_edit.get(websocket_id, False)
            and required.issubset(capabilities)
        )

    async def get_required_write_capabilities(self, mindmap_id: int) -> set[str]:
        """读取房间粘性写协议；Redis 不可用时保留已知本地栅栏。"""
        async with self._lock:
            required = set(STATIC_REQUIRED_WRITE_CAPABILITIES)
            required.update(self._required_write_capabilities.get(mindmap_id, ()))
        redis = self._redis
        if not redis:
            return required
        for capability in ROOM_WRITE_CAPABILITIES - required:
            result = await self._safe_redis_call(
                redis.get(self._write_capability_key(mindmap_id, capability)),
                operation='读取脑图房间写协议',
                failure_value=_REDIS_CALL_FAILED,
            )
            if result is _REDIS_CALL_FAILED:
                # 只要配置过 Redis，就可能存在另一个单-worker 实例。读取
                # 失败时无法区分“从未升级”和“已升级但暂时读不到标记”，
                # 因而本次判断必须 fail-closed；不要用 app_workers 推断
                # 水平部署规模，也不污染本地粘性缓存。
                required.add(capability)
                continue
            if result is None:
                continue
            await self._activate_local_write_capability(mindmap_id, capability)
            required.add(capability)
        return required

    async def get_missing_write_capabilities(
        self,
        mindmap_id: int,
        capabilities: set[str],
    ) -> set[str]:
        """返回当前连接缺失的房间写能力。"""
        required = await self.get_required_write_capabilities(mindmap_id)
        return required - capabilities

    async def require_write_capability(
        self,
        mindmap_id: int,
        capability: str,
    ) -> bool:
        """持久化并激活房间写协议，退休仍使用旧协议的本地写连接。"""
        if capability not in ROOM_WRITE_CAPABILITIES:
            raise ValueError('不支持的脑图房间写协议能力')
        redis = self._redis
        if redis:
            result = await self._safe_redis_call(
                redis.set(
                    self._write_capability_key(mindmap_id, capability),
                    '1',
                ),
                operation='建立脑图房间写协议',
                failure_value=_REDIS_CALL_FAILED,
            )
            if result is _REDIS_CALL_FAILED:
                return False
        elif AppConfig.app_workers > 1:
            return False

        await self._activate_local_write_capability(mindmap_id, capability)
        await self._publish_redis_event(mindmap_id, {
            'type': 'room_write_capability_required',
            'capability': capability,
        })
        return True

    async def _activate_local_write_capability(
        self,
        mindmap_id: int,
        capability: str,
    ) -> None:
        async with self._lock:
            required = self._required_write_capabilities.setdefault(mindmap_id, set())
            if capability in required:
                return
            required.add(capability)
        websockets, presence_records = await self._take_local_connections(
            mindmap_id,
            editable_only=True,
            missing_capability=capability,
        )
        await self._close_connections(
            mindmap_id,
            websockets,
            presence_records,
            close_code=self._slow_consumer_close_code,
            message=self._write_capability_error_payload(capability),
        )

    @staticmethod
    def _write_capability_error_payload(capability: str) -> dict[str, Any]:
        return {
            'type': 'protocol_error',
            'code': 'write_capability_required',
            'message': '协作写协议已升级，请更新页面后重试；当前仍可只读查看',
            'requiredCapabilities': [capability],
            'retryable': True,
        }

    async def touch_presence(self, mindmap_id: int, websocket: WebSocket) -> None:
        """刷新连接的分布式在线状态，供心跳任务调用。"""
        presence = self._connection_presence.get(id(websocket))
        if presence and presence[0] == mindmap_id:
            await self._write_presence(mindmap_id, presence[2])

    def set_content_revision(
        self,
        mindmap_id: int,
        revision: int | None,
        *,
        transition_type: str | None = None,
    ) -> None:
        """缓存最新 revision，并只为明确的连续增量迁移 lineage。"""
        if mindmap_id not in self._rooms or type(revision) is not int:
            return
        current = self._content_revisions.get(mindmap_id, 0)
        if revision > current:
            current_lineage = self._content_lineages.get(mindmap_id)
            current_epoch = self._local_lineage_epochs.get(mindmap_id)
            preserve_lineage = (
                transition_type in LINEAGE_PRESERVING_REVISION_EVENTS
                and revision == current + 1
                and current_lineage is not None
                and current_lineage[0] == current
            )
            if preserve_lineage:
                self._content_lineages[mindmap_id] = (
                    revision,
                    current_lineage[1],
                )
                self._pending_content_lineages.pop(mindmap_id, None)
            else:
                if (
                    transition_type is None
                    and revision == current + 1
                    and current_lineage is not None
                    and current_lineage[0] == current
                    and current_epoch is not None
                ):
                    self._pending_content_lineages[mindmap_id] = (
                        revision,
                        current_lineage[1],
                        current_epoch,
                    )
                else:
                    self._pending_content_lineages.pop(mindmap_id, None)
                self._content_lineages.pop(mindmap_id, None)
                self._local_lineage_epochs.pop(mindmap_id, None)
            # seed 租约只对申请时的正文 revision 有效。长连接可能拿到
            # seed_granted 后一直不回传种子；若 revision 持续推进而只依赖
            # Redis TTL，进程内字典会为每个历史 revision 永久保留一项，
            # 直到该连接退出。推进栅栏时立即丢弃全部旧本地资格；Redis
            # 所有权仍由短 TTL 自动回收，不能再被本进程消费。
            self._clear_local_seed_leases(mindmap_id)
            # revision 本身也是协作世代的一部分。即使当前尚未建立
            # lineage，正在读取的数据库握手快照也必须在 revision 推进后
            # 失效；否则旧查询会通过 generation CAS，并把旧 sync_init
            # 发送给已经进入新版本的房间。
            self._bump_content_lineage_generation(mindmap_id)
        elif revision == current:
            pending = self._pending_content_lineages.get(mindmap_id)
            if (
                transition_type in LINEAGE_PRESERVING_REVISION_EVENTS
                and pending is not None
                and pending[0] == revision
                and mindmap_id not in self._content_lineages
            ):
                self._content_lineages[mindmap_id] = (revision, pending[1])
                self._local_lineage_epochs[mindmap_id] = pending[2]
                self._pending_content_lineages.pop(mindmap_id, None)
                self._bump_content_lineage_generation(mindmap_id)
            elif transition_type in LINEAGE_REVISION_EVENTS:
                self._pending_content_lineages.pop(mindmap_id, None)
        self._content_revisions[mindmap_id] = max(current, revision)

    def clear_content_lineage(self, mindmap_id: int, revision: object) -> bool:
        """在已确认的当前 revision 上清除无法证明唯一性的本地 lineage。"""
        if not self.is_current_revision(mindmap_id, revision):
            return False
        removed_lineage = self._content_lineages.pop(mindmap_id, None)
        removed_epoch = self._local_lineage_epochs.pop(mindmap_id, None)
        removed_pending = self._pending_content_lineages.pop(mindmap_id, None)
        if (
            removed_lineage is not None
            or removed_epoch is not None
            or removed_pending is not None
        ):
            self._bump_content_lineage_generation(mindmap_id)
        return True

    def _bump_content_lineage_generation(self, mindmap_id: int) -> None:
        self._content_lineage_generations[mindmap_id] = (
            self._content_lineage_generations.get(mindmap_id, 0) + 1
        )

    def get_content_lineage_generation(self, mindmap_id: int) -> int:
        """返回本 worker 的 lineage 单调代次，供 DB 快照 CAS 使用。"""
        return self._content_lineage_generations.get(mindmap_id, 0)

    def is_content_lineage_generation_current(
        self,
        mindmap_id: int,
        generation: object,
    ) -> bool:
        return (
            type(generation) is int
            and generation == self.get_content_lineage_generation(mindmap_id)
        )

    def has_content_lineage(self, mindmap_id: int, revision: object) -> bool:
        current = self._content_lineages.get(mindmap_id)
        return type(revision) is int and current is not None and current[0] == revision

    @staticmethod
    def _lineage_digest(lineage_id: object) -> str | None:
        if not isinstance(lineage_id, str):
            return None
        normalized = lineage_id.strip()
        encoded = normalized.encode('utf-8')
        if not normalized or len(encoded) > MAX_YJS_LINEAGE_ID_BYTES:
            return None
        return hashlib.sha256(encoded).hexdigest()

    def set_content_lineage(
        self,
        mindmap_id: int,
        revision: object,
        lineage_id: object,
        *,
        replace: bool = False,
    ) -> bool:
        """建立/校验房间 lineage；仅已落库的权威种子可显式切换。"""
        digest = self._lineage_digest(lineage_id)
        if (
            digest is None
            or type(revision) is not int
            or not self.is_current_revision(mindmap_id, revision)
        ):
            return False
        current = self._content_lineages.get(mindmap_id)
        if current and current != (revision, digest) and not replace:
            return False
        candidate = (revision, digest)
        if current != candidate:
            self._content_lineages[mindmap_id] = candidate
            self._local_lineage_epochs[mindmap_id] = uuid.uuid4().hex
            self._bump_content_lineage_generation(mindmap_id)
        self._pending_content_lineages.pop(mindmap_id, None)
        return True

    def is_content_lineage_compatible(
        self,
        mindmap_id: int,
        revision: object,
        lineage_id: object,
    ) -> bool:
        """只校验而不建立 lineage；真正切换必须等 DB 保存成功。"""
        digest = self._lineage_digest(lineage_id)
        if (
            digest is None
            or type(revision) is not int
            or not self.is_current_revision(mindmap_id, revision)
        ):
            return False
        current = self._content_lineages.get(mindmap_id)
        return current is None or current == (revision, digest)

    def set_content_lineage_digest(
        self,
        mindmap_id: int,
        revision: object,
        lineage_digest: object,
    ) -> bool:
        """从同 revision 的持久化快照恢复房间 lineage 栅栏。"""
        if (
            type(revision) is not int
            or not isinstance(lineage_digest, str)
            or len(lineage_digest) != LINEAGE_DIGEST_HEX_LENGTH
            or any(character not in '0123456789abcdef' for character in lineage_digest)
            or not self.is_current_revision(mindmap_id, revision)
        ):
            return False
        current = self._content_lineages.get(mindmap_id)
        candidate = (revision, lineage_digest)
        if current and current != candidate:
            return False
        if current != candidate:
            self._content_lineages[mindmap_id] = candidate
            self._local_lineage_epochs[mindmap_id] = uuid.uuid4().hex
            self._bump_content_lineage_generation(mindmap_id)
        self._pending_content_lineages.pop(mindmap_id, None)
        return True

    def reconcile_persisted_content_lineage_digest(
        self,
        mindmap_id: int,
        revision: object,
        lineage_digest: object,
        *,
        expected_generation: object,
    ) -> tuple[bool, bool]:
        """用查询前代次 CAS 将 DB 权威 lineage 恢复到本地房间。

        返回 ``(是否可用, 是否替换了本地栅栏)``。查询期间已经
        收到其他 lineage 事件时失败关闭，让调用方用新事务重试。
        """
        if (
            type(expected_generation) is not int
            or type(revision) is not int
            or not isinstance(lineage_digest, str)
            or len(lineage_digest) != LINEAGE_DIGEST_HEX_LENGTH
            or any(character not in '0123456789abcdef' for character in lineage_digest)
            or not self.is_current_revision(mindmap_id, revision)
        ):
            return False, False
        candidate = (revision, lineage_digest)
        current = self._content_lineages.get(mindmap_id)
        if current == candidate:
            # 查询期间同 lineage 的 seed/checkpoint 更新仍可 CRDT 合并。
            return True, False
        if not self.is_content_lineage_generation_current(
            mindmap_id,
            expected_generation,
        ):
            return False, False
        self._content_lineages[mindmap_id] = candidate
        self._local_lineage_epochs[mindmap_id] = uuid.uuid4().hex
        self._pending_content_lineages.pop(mindmap_id, None)
        self._bump_content_lineage_generation(mindmap_id)
        return True, True

    @staticmethod
    def _encode_lineage_fence(
        revision: int,
        lineage_digest: str | None,
        *,
        epoch: str | None = None,
    ) -> str:
        if epoch is None:
            epoch = uuid.uuid4().hex
        elif (
            len(epoch) != LINEAGE_FENCE_EPOCH_HEX_LENGTH
            or any(character not in '0123456789abcdef' for character in epoch)
        ):
            raise ValueError('lineage fence epoch 格式无效')
        return json.dumps(
            {
                'digest': lineage_digest,
                'epoch': epoch,
                'revision': revision,
                'status': (
                    LINEAGE_FENCE_ACTIVE
                    if lineage_digest is not None
                    else LINEAGE_FENCE_TOMBSTONE
                ),
                'version': LINEAGE_FENCE_SCHEMA_VERSION,
            },
            sort_keys=True,
            separators=(',', ':'),
        )

    @staticmethod
    def _decode_lineage_fence_record(
        value: object,
    ) -> tuple[int, str | None, str, str] | None:
        try:
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            if not isinstance(value, str):
                return None
            payload = json.loads(value)
            revision = payload.get('revision')
            digest = payload.get('digest')
            status = payload.get('status')
            epoch = payload.get('epoch')
            if (
                not isinstance(payload, dict)
                or payload.get('version') != LINEAGE_FENCE_SCHEMA_VERSION
                or type(revision) is not int
                or revision <= 0
                or not isinstance(epoch, str)
                or len(epoch) != LINEAGE_FENCE_EPOCH_HEX_LENGTH
                or any(character not in '0123456789abcdef' for character in epoch)
                or status not in {LINEAGE_FENCE_ACTIVE, LINEAGE_FENCE_TOMBSTONE}
            ):
                return None
            if status == LINEAGE_FENCE_ACTIVE:
                if (
                    not isinstance(digest, str)
                    or len(digest) != LINEAGE_DIGEST_HEX_LENGTH
                    or any(character not in '0123456789abcdef' for character in digest)
                ):
                    return None
            elif digest is not None:
                return None
            return revision, digest, status, epoch
        except (AttributeError, TypeError, ValueError, UnicodeDecodeError):
            return None

    @classmethod
    def _decode_lineage_fence(
        cls,
        value: object,
    ) -> tuple[int, str | None, str] | None:
        record = cls._decode_lineage_fence_record(value)
        return record[:3] if record is not None else None

    async def repair_content_lineage_fence_from_persisted(  # noqa: PLR0911, PLR0912
        self,
        mindmap_id: int,
        revision: int,
        lineage_digest: str | None,
        *,
        preserve_matching_active: bool = False,
    ) -> tuple[bool, str | None]:
        """在调用方持有 Mindmap→WsState 锁时用 DB 权威状态修复 Redis。

        无持久化状态时，可保留同 revision 的 active 栅栏：这表示明确连续
        HTTP 增量刚推进 revision，而在线 Y.Doc 尚未来得及写检查点。
        """
        if type(revision) is not int or revision <= 0:
            return False, None
        if lineage_digest is not None and (
            len(lineage_digest) != LINEAGE_DIGEST_HEX_LENGTH
            or any(character not in '0123456789abcdef' for character in lineage_digest)
        ):
            return False, None
        redis = self._redis
        if not redis:
            if AppConfig.app_workers > 1:
                return False, None
            if lineage_digest is not None:
                return True, lineage_digest
            current = self._content_lineages.get(mindmap_id)
            if preserve_matching_active and current and current[0] == revision:
                return True, current[1]
            if (
                preserve_matching_active
                and current
                and current[0] + 1 == revision
            ):
                # 单 worker 也可能在 HTTP commit 的 await 与随后本地广播
                # 之间运行新握手。不能先清旧 lineage 再误判为空房间；让在途
                # 服务协程先完成 transition，若它已崩溃则现有连接的 DB 心跳
                # 会清理旧本地栅栏，后续握手再重建。
                return False, None
            return True, None

        key = self._lineage_fence_key(mindmap_id)
        for _attempt in range(3):
            current_raw = await self._safe_redis_call(
                redis.get(key),
                operation='读取脑图 lineage 栅栏',
                failure_value=_REDIS_CALL_FAILED,
            )
            if current_raw is _REDIS_CALL_FAILED:
                return False, None
            current_record = self._decode_lineage_fence_record(current_raw)
            current = current_record[:3] if current_record is not None else None
            if lineage_digest is not None and current == (
                revision,
                lineage_digest,
                LINEAGE_FENCE_ACTIVE,
            ):
                return True, lineage_digest
            if (
                lineage_digest is None
                and current == (revision, None, LINEAGE_FENCE_TOMBSTONE)
            ):
                return True, None
            if (
                preserve_matching_active
                and lineage_digest is None
                and current is not None
                and current[0] == revision
                and current[2] == LINEAGE_FENCE_ACTIVE
            ):
                return True, current[1]
            if (
                preserve_matching_active
                and lineage_digest is None
                and current is not None
                and current[0] + 1 == revision
                and current[2] == LINEAGE_FENCE_ACTIVE
            ):
                # 正常 HTTP 增量先提交 DB、随后才推进 Redis fence。握手恰好落在
                # 二者之间时，WsState 因 revision 不匹配呈空，但旧 active fence
                # 是一条可能仍在途的连续 lineage，不能抢先覆盖成 tombstone；
                # 否则随后到达的幂等 revision 事件也无法恢复原 digest。让本次
                # 握手先重试，由正式事件决定“连续迁移”还是“reset 清空”。
                # 若事件确实丢失，Redis 记录的跨 worker 宽限期到期后，后续
                # 握手才允许安全地 CAS 成 tombstone，避免永久卡死在 r-1。
                gap_matured = await self._safe_redis_call(
                    redis.eval(
                        _OBSERVE_LINEAGE_REVISION_GAP_SCRIPT,
                        1,
                        self._lineage_gap_key(mindmap_id, revision),
                        current_record[3],
                        self._lineage_gap_grace_ms,
                        self._lineage_gap_marker_ttl_ms,
                    ),
                    operation='观察脑图 lineage revision 提交广播间隙',
                    failure_value=_REDIS_CALL_FAILED,
                )
                if gap_matured is _REDIS_CALL_FAILED or gap_matured != 1:
                    return False, None

            desired = self._encode_lineage_fence(revision, lineage_digest)
            result = await self._safe_redis_call(
                redis.eval(
                    _COMPARE_AND_SET_LINEAGE_FENCE_SCRIPT,
                    1,
                    key,
                    '' if current_raw is None else current_raw,
                    '1' if current_raw is None else '0',
                    desired,
                ),
                operation='修复脑图 lineage 栅栏',
                failure_value=_REDIS_CALL_FAILED,
            )
            if result is _REDIS_CALL_FAILED:
                return False, None
            if result == 1:
                return True, lineage_digest
        return False, None

    async def advance_content_revision_fence(
        self,
        mindmap_id: int,
        revision: int,
        transition_type: str,
    ) -> bool:
        """以 Redis CAS 推进 revision；只有明确连续增量可沿用 digest。"""
        if type(revision) is not int or revision <= 0:
            return False
        redis = self._redis
        if not redis:
            if AppConfig.app_workers > 1:
                return False
            self.set_content_revision(
                mindmap_id,
                revision,
                transition_type=transition_type,
            )
            return True

        key = self._lineage_fence_key(mindmap_id)
        for _attempt in range(3):
            current_raw = await self._safe_redis_call(
                redis.get(key),
                operation='读取脑图 lineage revision 栅栏',
                failure_value=_REDIS_CALL_FAILED,
            )
            if current_raw is _REDIS_CALL_FAILED:
                return False
            current_record = self._decode_lineage_fence_record(current_raw)
            current = current_record[:3] if current_record is not None else None
            if current is not None and current[0] > revision:
                return False

            preserve = (
                transition_type in LINEAGE_PRESERVING_REVISION_EVENTS
                and current is not None
                and current[0] + 1 == revision
                and current[2] == LINEAGE_FENCE_ACTIVE
            )
            desired_digest = current[1] if preserve else None
            desired_epoch = current_record[3] if preserve else None
            if current is not None and current[0] == revision:
                # 同 revision 的迟到/幂等 reset 可能发生在新世代已经完成
                # seed 之后。revision 相等时不得把这个更新 active 基线再改回
                # tombstone；首次 reset 必然从更小 revision 单调推进。
                desired_digest = current[1]
                desired_epoch = current_record[3]
                break
            desired_raw = self._encode_lineage_fence(
                revision,
                desired_digest,
                epoch=desired_epoch,
            )
            result = await self._safe_redis_call(
                redis.eval(
                    _COMPARE_AND_SET_LINEAGE_FENCE_SCRIPT,
                    1,
                    key,
                    '' if current_raw is None else current_raw,
                    '1' if current_raw is None else '0',
                    desired_raw,
                ),
                operation='推进脑图 lineage revision 栅栏',
                failure_value=_REDIS_CALL_FAILED,
            )
            if result is _REDIS_CALL_FAILED:
                return False
            if result == 1:
                break
        else:
            return False

        self.set_content_revision(
            mindmap_id,
            revision,
            transition_type=transition_type,
        )
        if desired_digest is None:
            self.clear_content_lineage(mindmap_id, revision)
        else:
            self.set_content_lineage_digest(mindmap_id, revision, desired_digest)
        return True

    async def _get_matching_lineage_fence_raw(
        self,
        mindmap_id: int,
        revision: object,
        lineage_id: object,
    ) -> str | None:
        digest = self._lineage_digest(lineage_id)
        if digest is None or type(revision) is not int:
            return None
        redis = self._redis
        if not redis:
            if AppConfig.app_workers > 1:
                return None
            return 'local' if self._content_lineages.get(mindmap_id) == (
                revision,
                digest,
            ) else None
        raw = await self._safe_redis_call(
            redis.get(self._lineage_fence_key(mindmap_id)),
            operation='校验脑图 lineage 栅栏',
            failure_value=_REDIS_CALL_FAILED,
        )
        if raw is _REDIS_CALL_FAILED:
            return None
        parsed = self._decode_lineage_fence(raw)
        if parsed != (revision, digest, LINEAGE_FENCE_ACTIVE):
            return None
        return raw.decode('utf-8') if isinstance(raw, bytes) else raw

    async def verify_content_lineage_fence(
        self,
        mindmap_id: int,
        revision: object,
        lineage_id: object,
    ) -> bool:
        """每次共享写最终动作前从可靠 Redis 键校验 revision+lineage。"""
        return await self._get_matching_lineage_fence_raw(
            mindmap_id,
            revision,
            lineage_id,
        ) is not None

    def get_content_revision(self, mindmap_id: int) -> int | None:
        """返回在线房间已知的最新持久化 revision。"""
        return self._content_revisions.get(mindmap_id)

    def is_current_revision(self, mindmap_id: int, revision: object) -> bool:
        """判断客户端 revision 是否可安全参与当前房间广播。"""
        current = self.get_content_revision(mindmap_id)
        return type(revision) is int and current is not None and revision == current

    async def get_runtime_snapshot(self) -> dict[str, int | str]:
        """返回当前 worker 的低基数协作运行态，不暴露房间或用户身份。"""
        async with self._lock:
            active_rooms = len(self._rooms)
            active_connections = len(self._connection_presence)
            retiring_connections = len(self._retiring_connections)
        listener_task = self._listener_task
        if not self._running:
            redis_transport_state = 'stopped'
        elif (
            self._listener_ready.is_set()
            and listener_task is not None
            and not listener_task.done()
        ):
            redis_transport_state = 'ready'
        else:
            redis_transport_state = 'degraded'
        return {
            'activeRooms': active_rooms,
            'activeConnections': active_connections,
            'retiringConnections': retiring_connections,
            'redisTransportState': redis_transport_state,
        }

    def consume_disconnect_persistence_permission(self, websocket: WebSocket) -> bool:
        """强制终止的连接不得在 endpoint finally 中回写最后状态。"""
        websocket_id = id(websocket)
        blocked = websocket_id in self._blocked_disconnect_persistence
        self._blocked_disconnect_persistence.discard(websocket_id)
        return not blocked

    def block_disconnect_persistence(self, websocket: WebSocket) -> None:
        """标记单条不再可信的连接，禁止其在断开阶段回写 Yjs 状态。"""
        self._blocked_disconnect_persistence.add(id(websocket))

    async def acquire_seed_lease(
        self,
        mindmap_id: int,
        content_revision: int,
        websocket: WebSocket,
    ) -> bool:
        """为无缓存 revision 选出唯一 Yjs 初始化连接。"""
        if type(content_revision) is not int or content_revision <= 0:
            return False
        presence = self._connection_presence.get(id(websocket))
        owner = presence[1] if presence else f'{self._instance_id}:{id(websocket)}'
        key = (mindmap_id, content_revision)
        now = time.monotonic()
        async with self._lock:
            current = self._local_seed_leases.get(key)
            if current and current[1] > now and current[0] == id(websocket):
                # seed_granted 可能在网络抖动时丢失。同一连接重试必须仍被
                # 识别为租约持有者，不能被自己的 Redis NX 键阻塞到超时。
                return True
            if current and current[1] <= now:
                self._local_seed_leases.pop(key, None)
        if self._redis:
            # Redis TTL 从 SET 执行时开始；本地截止时间必须在发起 SET 前
            # 固定，确保网络等待不会让进程内租约比 Redis 所有权活得更久。
            lease_deadline = time.monotonic() + self._seed_lease_ttl_seconds
            result = await self._safe_redis_call(
                self._redis.set(
                    f'{self._seed_key_prefix}{mindmap_id}:{content_revision}',
                    owner,
                    nx=True,
                    ex=self._seed_lease_ttl_seconds,
                ),
                operation='竞争脑图协作初始化租约',
                failure_value=_REDIS_CALL_FAILED,
            )
            if result is not _REDIS_CALL_FAILED:
                granted = result is True or result in {b'OK', 'OK'}
                if granted:
                    async with self._lock:
                        self._local_seed_leases[(mindmap_id, content_revision)] = (
                            id(websocket),
                            lease_deadline,
                        )
                return granted

            # 只要配置过 Redis，就可能存在另一个单-worker 实例。仲裁失败
            # 时降级为进程内租约会让多个实例同时生成不同 Y.Doc 基线。
            record_mindmap_event('seed_lease_unavailable')
            logger.warning('Redis 协作初始化租约仲裁失败，已拒绝本次申请')
            return False

        if AppConfig.app_workers > 1:
            # 多 worker 无法用进程内锁证明全局唯一。宁可让客户端继续等待
            # Redis 恢复，也不能让每个 worker 各自产生一份同名 Yjs 种子。
            record_mindmap_event('seed_lease_unavailable')
            logger.warning('多进程模式下 Redis 不可用，已拒绝本地协作种子租约')
            return False

        now = time.monotonic()
        async with self._lock:
            current = self._local_seed_leases.get(key)
            if current and current[1] > now:
                return current[0] == id(websocket)
            self._local_seed_leases[key] = (
                id(websocket),
                now + self._seed_lease_ttl_seconds,
            )
            return True

    async def owns_seed_lease(
        self,
        mindmap_id: int,
        content_revision: int,
        websocket: WebSocket,
    ) -> bool:
        """确认权威种子标记来自刚获得当前 revision 租约的连接。"""
        key = (mindmap_id, content_revision)
        now = time.monotonic()
        async with self._lock:
            current = self._local_seed_leases.get(key)
            if not current or current[1] <= now:
                self._local_seed_leases.pop(key, None)
                return False
            return current[0] == id(websocket)

    async def consume_seed_lease(
        self,
        mindmap_id: int,
        content_revision: int,
        websocket: WebSocket,
    ) -> bool:
        """一次性消费本连接的权威种子资格，阻止同一租约重复标记状态。"""
        key = (mindmap_id, content_revision)
        now = time.monotonic()
        async with self._lock:
            current = self._local_seed_leases.get(key)
            if not current or current[1] <= now:
                self._local_seed_leases.pop(key, None)
                return False
            if current[0] != id(websocket):
                return False
            local_lease = current
            presence = self._connection_presence.get(id(websocket))
            owner = presence[1] if presence else f'{self._instance_id}:{id(websocket)}'

        redis = self._redis
        redis_verified = False
        if redis:
            result = await self._safe_redis_call(
                redis.eval(
                    _VERIFY_AND_RENEW_SEED_LEASE_SCRIPT,
                    1,
                    f'{self._seed_key_prefix}{mindmap_id}:{content_revision}',
                    owner,
                    self._seed_lease_ttl_seconds,
                ),
                operation='校验脑图协作初始化租约',
                failure_value=_REDIS_CALL_FAILED,
            )
            if result is not _REDIS_CALL_FAILED and result != 1:
                async with self._lock:
                    if self._local_seed_leases.get(key) == local_lease:
                        self._local_seed_leases.pop(key, None)
                return False
            if result is _REDIS_CALL_FAILED:
                return False
            redis_verified = result is not _REDIS_CALL_FAILED
        elif AppConfig.app_workers > 1:
            return False

        async with self._lock:
            # Redis 往返期间连接可能退出或租约已被本机清理；只有仍是同一条
            # 本地租约的调用方才能完成一次性消费。
            if self._local_seed_leases.get(key) != local_lease:
                return False
            if not redis_verified and local_lease[1] <= time.monotonic():
                self._local_seed_leases.pop(key, None)
                return False
            self._local_seed_leases.pop(key, None)
        # Redis 键继续保留到短 TTL：调用方此刻尚未把种子写入数据库，立即
        # 释放会让另一 worker 在落库窗口内获得第二份独立种子资格。
        return True

    async def _release_owned_seed_leases(self, websocket_ids: set[int]) -> None:
        """释放指定连接持有的本地与 Redis 种子租约。"""
        if not websocket_ids:
            return
        releases: list[tuple[tuple[int, int], str]] = []
        async with self._lock:
            owners = {
                websocket_id: presence[1]
                for websocket_id, presence in self._connection_presence.items()
                if websocket_id in websocket_ids
            }
            for key, lease in list(self._local_seed_leases.items()):
                if lease[0] not in websocket_ids:
                    continue
                self._local_seed_leases.pop(key, None)
                if owner := owners.get(lease[0]):
                    releases.append((key, owner))
        await asyncio.gather(*(
            self._release_redis_seed_lease(key, owner)
            for key, owner in releases
        ))

    async def _release_redis_seed_lease(
        self,
        key: tuple[int, int],
        owner: str,
    ) -> None:
        """仅当 Redis 租约仍属于当前连接时原子删除，避免 ABA 误删。"""
        redis = self._redis
        if not redis:
            return
        await self._safe_redis_call(
            redis.eval(
                _RELEASE_SEED_LEASE_SCRIPT,
                1,
                f'{self._seed_key_prefix}{key[0]}:{key[1]}',
                owner,
            ),
            operation='释放脑图协作初始化租约',
        )

    def _clear_local_seed_leases(self, mindmap_id: int) -> None:
        for key in [key for key in self._local_seed_leases if key[0] == mindmap_id]:
            self._local_seed_leases.pop(key, None)

    def _get_local_lineage_lease_generation(
        self,
        mindmap_id: int,
        revision: int | None = None,
    ) -> str | None:
        current = self._content_lineages.get(mindmap_id)
        generation = self._local_lineage_epochs.get(mindmap_id)
        if (
            current is None
            or generation is None
            or (revision is not None and current[0] != revision)
        ):
            return None
        return generation

    async def _get_active_lineage_lease_fence(
        self,
        mindmap_id: int,
        revision: int | None = None,
    ) -> tuple[str | None, str] | None:
        """读取节点租约所绑定的稳定 lineage 世代。

        Redis fence 的 epoch 在连续增量 revision 间保持不变，并在 reset/
        新 seed 后切换。无 Redis 的单 worker 使用同等语义的本地 epoch。
        """
        redis = self._redis
        if not redis:
            if AppConfig.app_workers > 1:
                return None
            generation = self._get_local_lineage_lease_generation(
                mindmap_id,
                revision,
            )
            return (None, generation) if generation is not None else None

        raw = await self._safe_redis_call(
            redis.get(self._lineage_fence_key(mindmap_id)),
            operation='读取节点编辑租约 lineage 世代',
            failure_value=_REDIS_CALL_FAILED,
        )
        if raw is _REDIS_CALL_FAILED:
            return None
        record = self._decode_lineage_fence_record(raw)
        if (
            record is None
            or record[2] != LINEAGE_FENCE_ACTIVE
            or (revision is not None and record[0] != revision)
        ):
            return None
        normalized_raw = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        return normalized_raw, record[3]

    async def acquire_node_edit_lease(
        self,
        mindmap_id: int,
        content_revision: int,
        node_uid: str,
        websocket: WebSocket,
    ) -> bool | None:
        """原子获取或续期单节点编辑租约。

        ``False`` 仅表示租约已被其他连接占用；``None`` 表示仲裁器或
        当前连接不可用。这个三态结果让官方客户端不会把 Redis 故障误报为
        “其他协作者正在编辑”。
        """
        websocket_id = id(websocket)
        presence = self._connection_presence.get(websocket_id)
        if (
            not node_uid
            or type(content_revision) is not int
            or not presence
            or presence[0] != mindmap_id
            or NODE_EDIT_LEASE_CAPABILITY
            not in self._connection_capabilities.get(websocket_id, set())
            or not self.is_connection_write_enabled(mindmap_id, websocket)
        ):
            return None
        owner = presence[1]
        fence = await self._get_active_lineage_lease_fence(
            mindmap_id,
            content_revision,
        )
        if fence is None:
            return None
        _fence_snapshot, lineage_epoch = fence
        key = (mindmap_id, lineage_epoch, node_uid)
        redis_key = self._node_edit_lease_key(
            mindmap_id,
            lineage_epoch,
            node_uid,
        )
        redis = self._redis
        if redis:
            result = await self._safe_redis_call(
                redis.eval(
                    _ACQUIRE_OR_RENEW_NODE_EDIT_LEASE_SCRIPT,
                    2,
                    self._lineage_fence_key(mindmap_id),
                    redis_key,
                    lineage_epoch,
                    owner,
                    self._node_edit_lease_ttl_seconds,
                ),
                operation='按 lineage 世代竞争或续期节点编辑租约',
                failure_value=_REDIS_CALL_FAILED,
            )
            if result is _REDIS_CALL_FAILED or result == -1:
                # Redis 调用/lineage CAS 失败不能降级，否则会绕过另一个实例
                # 已经持有的锁或把旧世代租约错误授予当前连接。
                record_mindmap_event('node_edit_lease_unavailable')
                logger.warning('Redis 节点编辑租约仲裁失败，已拒绝本次申请')
                return None
            if result != 1:
                return False

            # Lua 把“fence 仍匹配”和“获取/续租”放在同一原子操作中。
            # 再读一次只用于避免在 reset 紧随其后时把旧世代登记成本地
            # 当前租约；连续 revision 推进保留 epoch，因此不会踢掉编辑者。
            current_fence = await self._get_active_lineage_lease_fence(mindmap_id)
            still_same_generation = (
                current_fence is not None and current_fence[1] == lineage_epoch
            )
            async with self._lock:
                current_presence = self._connection_presence.get(websocket_id)
                still_valid = (
                    still_same_generation
                    and current_presence is not None
                    and current_presence[0] == mindmap_id
                    and current_presence[1] == owner
                    and websocket_id not in self._retiring_connections
                    and self._connection_can_edit.get(websocket_id, False)
                    and NODE_EDIT_LEASE_CAPABILITY
                    in self._connection_capabilities.get(websocket_id, set())
                )
                if still_valid:
                    self._local_node_edit_leases[key] = (
                        websocket_id,
                        owner,
                        time.monotonic() + self._node_edit_lease_ttl_seconds,
                    )
            if still_valid:
                return True
            await self._release_redis_node_edit_lease(
                key,
                owner,
                redis_client=redis,
            )
            return None

        if AppConfig.app_workers > 1:
            record_mindmap_event('node_edit_lease_unavailable')
            logger.warning('多进程模式下 Redis 不可用，已拒绝节点编辑租约')
            return None

        now = time.monotonic()
        async with self._lock:
            if (
                not self.is_connection_write_enabled(mindmap_id, websocket)
                or self._get_local_lineage_lease_generation(
                    mindmap_id,
                    content_revision,
                ) != lineage_epoch
            ):
                return None
            current = self._local_node_edit_leases.get(key)
            if current and current[2] > now and current[0] != websocket_id:
                return False
            self._local_node_edit_leases[key] = (
                websocket_id,
                owner,
                now + self._node_edit_lease_ttl_seconds,
            )
            return True

    async def owns_node_edit_lease(
        self,
        mindmap_id: int,
        node_uid: str,
        websocket: WebSocket,
    ) -> bool:
        """只信任当前 lineage 中本连接仍真实持有的编辑租约。"""
        fence = await self._get_active_lineage_lease_fence(mindmap_id)
        if fence is None:
            return False
        _fence_snapshot, lineage_epoch = fence
        key = (mindmap_id, lineage_epoch, node_uid)
        now = time.monotonic()
        async with self._lock:
            current = self._local_node_edit_leases.get(key)
            if not current or current[2] <= now:
                self._local_node_edit_leases.pop(key, None)
                return False
            locally_owned = (
                current[0] == id(websocket)
                and NODE_EDIT_LEASE_CAPABILITY
                in self._connection_capabilities.get(id(websocket), set())
                and self.is_connection_write_enabled(mindmap_id, websocket)
            )
        if not locally_owned:
            return False
        redis = self._redis
        if not redis:
            return True
        verified = await self._safe_redis_call(
            redis.eval(
                _VERIFY_NODE_EDIT_LEASE_SCRIPT,
                2,
                self._lineage_fence_key(mindmap_id),
                self._node_edit_lease_key(mindmap_id, lineage_epoch, node_uid),
                lineage_epoch,
                current[1],
            ),
            operation='校验节点编辑租约所有权',
            failure_value=_REDIS_CALL_FAILED,
        )
        return verified == 1

    async def renew_node_edit_lease(
        self,
        mindmap_id: int,
        node_uid: str,
        websocket: WebSocket,
    ) -> bool | None:
        """仅续期当前连接在当前 lineage 已持有的节点租约。

        正文 revision 可在长时间输入期间因其他节点保存而连续推进；续租
        绑定稳定 lineage epoch 和 owner，而不能重新执行“无锁则获取”。因此
        reset 后的新 epoch、过期锁和伪造 renewal 都无法借此获得租约。
        """
        websocket_id = id(websocket)
        presence = self._connection_presence.get(websocket_id)
        if (
            not node_uid
            or not presence
            or presence[0] != mindmap_id
            or NODE_EDIT_LEASE_CAPABILITY
            not in self._connection_capabilities.get(websocket_id, set())
            or not self.is_connection_write_enabled(mindmap_id, websocket)
        ):
            return None
        owner = presence[1]

        redis = self._redis
        if redis:
            return await self._renew_redis_node_edit_lease(
                mindmap_id,
                node_uid,
                websocket,
                websocket_id,
                owner,
                redis,
            )

        if AppConfig.app_workers > 1:
            record_mindmap_event('node_edit_lease_unavailable')
            return None
        return await self._renew_local_node_edit_lease(
            mindmap_id,
            node_uid,
            websocket,
            websocket_id,
            owner,
        )

    async def _renew_redis_node_edit_lease(
        self,
        mindmap_id: int,
        node_uid: str,
        websocket: WebSocket,
        websocket_id: int,
        owner: str,
        redis: Any,
    ) -> bool | None:
        fence = await self._get_active_lineage_lease_fence(mindmap_id)
        if fence is None:
            return None
        _fence_snapshot, lineage_epoch = fence
        key = (mindmap_id, lineage_epoch, node_uid)
        result = await self._safe_redis_call(
            redis.eval(
                _RENEW_OWNED_NODE_EDIT_LEASE_SCRIPT,
                2,
                self._lineage_fence_key(mindmap_id),
                self._node_edit_lease_key(
                    mindmap_id,
                    lineage_epoch,
                    node_uid,
                ),
                lineage_epoch,
                owner,
                self._node_edit_lease_ttl_seconds,
            ),
            operation='按 owner 和 lineage 续期节点编辑租约',
            failure_value=_REDIS_CALL_FAILED,
        )
        if result is _REDIS_CALL_FAILED or result == -1:
            record_mindmap_event('node_edit_lease_unavailable')
            return None
        if result != 1:
            return False
        # Lua 与 fence 校验原子，但另一个 worker 可在 Lua 返回后立刻执行
        # document_reset。续租结果对调用方可见前必须再次确认 epoch；否则
        # 会把已经失效的旧世代登记为本地有效并继续接受节点文本写入。
        current_fence = await self._get_active_lineage_lease_fence(mindmap_id)
        still_same_generation = bool(
            current_fence is not None and current_fence[1] == lineage_epoch
        )
        if not still_same_generation:
            async with self._lock:
                current = self._local_node_edit_leases.get(key)
                if (
                    current
                    and current[0] == websocket_id
                    and current[1] == owner
                ):
                    self._local_node_edit_leases.pop(key, None)
            await self._release_redis_node_edit_lease(
                key,
                owner,
                redis_client=redis,
            )
            return None
        locally_valid = False
        async with self._lock:
            current = self._local_node_edit_leases.get(key)
            locally_valid = bool(
                current
                and current[0] == websocket_id
                and current[1] == owner
                and websocket_id not in self._retiring_connections
                and self.is_connection_write_enabled(mindmap_id, websocket)
            )
            if locally_valid:
                self._local_node_edit_leases[key] = (
                    websocket_id,
                    owner,
                    time.monotonic() + self._node_edit_lease_ttl_seconds,
                )
        if locally_valid:
            return True
        # Redis 仍属于本 owner，但本连接已经失去本地资格（例如断线清理
        # 并发发生）。立即归还刚续期的锁，不能留到 TTL。
        await self._release_redis_node_edit_lease(
            key,
            owner,
            redis_client=redis,
        )
        return False

    async def _renew_local_node_edit_lease(
        self,
        mindmap_id: int,
        node_uid: str,
        websocket: WebSocket,
        websocket_id: int,
        owner: str,
    ) -> bool | None:
        async with self._lock:
            # 前置资格检查与进入临界区之间，leave()/stop() 可能已经把连接
            # 标为 retiring。续租必须在锁内重新确认同一 connection owner
            # 仍可写，否则会给已退出的浏览器延长本地独占时间。
            current_presence = self._connection_presence.get(websocket_id)
            if (
                current_presence is None
                or current_presence[0] != mindmap_id
                or current_presence[1] != owner
                or websocket_id in self._retiring_connections
                or not self.is_connection_write_enabled(mindmap_id, websocket)
            ):
                return None
            # epoch 与租约记录必须在同一无 await 临界区内解析。否则 renewal
            # 等锁期间发生 reset 时，会拿旧 key 续期并向客户端错误返回 grant。
            current_epoch = self._local_lineage_epochs.get(mindmap_id)
            if current_epoch is None:
                # 数据库重检可能先看到 r+1，正式 content_revision_changed 事件
                # 尚未到达。set_content_revision 会只为这种连续间隙保留旧 epoch。
                pending = self._pending_content_lineages.get(mindmap_id)
                current_revision = self._content_revisions.get(mindmap_id)
                if pending is not None and pending[0] == current_revision:
                    current_epoch = pending[2]
            if current_epoch is None:
                return None
            key = (mindmap_id, current_epoch, node_uid)
            # 锁外读时钟会把排队时间错误计入新租期；更严重的是等待期间
            # 已过期的锁会被旧时间复活。资格、世代、时钟和写入必须原子。
            now = time.monotonic()
            current = self._local_node_edit_leases.get(key)
            if (
                not current
                or current[2] <= now
                or current[0] != websocket_id
                or current[1] != owner
            ):
                if current and current[2] <= now:
                    self._local_node_edit_leases.pop(key, None)
                return False
            self._local_node_edit_leases[key] = (
                websocket_id,
                owner,
                now + self._node_edit_lease_ttl_seconds,
            )
            return True

    async def release_node_edit_lease(
        self,
        mindmap_id: int,
        node_uid: str,
        websocket: WebSocket,
    ) -> bool:
        """仅释放调用连接自己的节点租约，迟到释放不能误删新持有者。"""
        websocket_id = id(websocket)
        presence = self._connection_presence.get(websocket_id)
        fallback_owner = (
            presence[1] if presence and presence[0] == mindmap_id else None
        )
        releases: list[tuple[tuple[int, str, str], str]] = []
        async with self._lock:
            for key, current in list(self._local_node_edit_leases.items()):
                if (
                    key[0] != mindmap_id
                    or key[2] != node_uid
                    or current[0] != websocket_id
                ):
                    continue
                self._local_node_edit_leases.pop(key, None)
                releases.append((key, current[1]))
        if not releases:
            return False
        await asyncio.gather(*(
            self._release_redis_node_edit_lease(
                key,
                owner or fallback_owner or '',
            )
            for key, owner in releases
        ))
        return True

    async def _release_owned_node_edit_leases(
        self,
        websocket_ids: set[int],
    ) -> None:
        """连接退出/强退时释放其全部节点租约。"""
        if not websocket_ids:
            return
        releases: list[tuple[tuple[int, str, str], str]] = []
        async with self._lock:
            for key, lease in list(self._local_node_edit_leases.items()):
                if lease[0] not in websocket_ids:
                    continue
                self._local_node_edit_leases.pop(key, None)
                releases.append((key, lease[1]))
        await asyncio.gather(*(
            self._release_redis_node_edit_lease(key, owner)
            for key, owner in releases
        ))

    async def release_connection_node_edit_leases(
        self,
        websocket: WebSocket,
    ) -> None:
        """在较慢的断开持久化之前公开释放当前连接的短期编辑锁。"""
        await self._release_owned_node_edit_leases({id(websocket)})

    async def _release_redis_node_edit_lease(
        self,
        key: tuple[int, str, str],
        owner: str,
        *,
        redis_client: Any | None = None,
    ) -> None:
        # 获取请求可能与 stop() 并发：stop 会清空 self._redis，但该请求仍需
        # 用发起 SET 的同一客户端归还随后才获得的租约。
        redis = self._redis if redis_client is None else redis_client
        if not redis:
            return
        await self._safe_redis_call(
            redis.eval(
                _RELEASE_SEED_LEASE_SCRIPT,
                1,
                self._node_edit_lease_key(key[0], key[1], key[2]),
                owner,
            ),
            operation='释放节点编辑租约',
        )

    def _clear_local_node_edit_leases(self, mindmap_id: int) -> None:
        for key in [
            key for key in self._local_node_edit_leases if key[0] == mindmap_id
        ]:
            self._local_node_edit_leases.pop(key, None)

    async def broadcast(self, mindmap_id: int, message: Any, exclude: WebSocket | None = None) -> None:
        """本地与跨实例并行分发，慢连接不能阻塞其他 worker。"""
        message_type = message.get('type') if isinstance(message, dict) else None
        revision = message.get('contentRevision') if isinstance(message, dict) else None
        if (
            message_type in LINEAGE_REVISION_EVENTS
            and type(revision) is int
            and not await self.advance_content_revision_fence(
                mindmap_id,
                revision,
                message_type,
            )
        ):
            raise RuntimeError('无法安全推进脑图 lineage revision 栅栏')
        await asyncio.gather(
            self._broadcast_local(mindmap_id, message, exclude=exclude),
            self._publish_redis_event(mindmap_id, message),
        )

    async def broadcast_with_lineage_fence(
        self,
        mindmap_id: int,
        message: dict,
        *,
        content_revision: int,
        lineage_id: str,
        exclude: WebSocket | None = None,
    ) -> bool:
        """原子校验 Redis lineage 后发布，再复核并投递本 worker。"""
        expected_fence = await self._get_matching_lineage_fence_raw(
            mindmap_id,
            content_revision,
            lineage_id,
        )
        if expected_fence is None:
            return False
        if self._redis:
            if not await self._publish_redis_event(
                mindmap_id,
                message,
                expected_lineage_fence=expected_fence,
            ):
                return False
            # Redis 原子发布完成后可能已有更晚的 seed 切换。旧帧已在频道
            # 全序中排在 seed 之前；此时不再向本机连接迟到投递即可。
            if not await self.verify_content_lineage_fence(
                mindmap_id,
                content_revision,
                lineage_id,
            ):
                return False
        if not self.set_content_lineage(
            mindmap_id,
            content_revision,
            lineage_id,
        ):
            return False
        await self._broadcast_local(mindmap_id, message, exclude=exclude)
        return True

    async def broadcast_checkpoint(
        self,
        mindmap_id: int,
        state: str,
        origin: str,
        content_revision: int,
        exclude: WebSocket | None = None,
        lineage_id: str | None = None,
    ) -> bool:
        """以标准 update 发布检查点，新 worker 再按连接能力抑制冗余消息。"""
        message = {
            'type': 'update',
            'update': state,
            'state': state,
            'patch': None,
            'checkpoint': True,
            'contentRevision': content_revision,
            'origin': origin,
            **({'lineageId': lineage_id} if lineage_id else {}),
        }
        if lineage_id:
            return await self.broadcast_with_lineage_fence(
                mindmap_id,
                message,
                content_revision=content_revision,
                lineage_id=lineage_id,
                exclude=exclude,
            )
        await self.broadcast(mindmap_id, message, exclude=exclude)
        return True

    async def broadcast_and_close_room(
        self, mindmap_id: int, message: dict, close_code: int = 4004,
    ) -> None:
        """广播终止事件到所有实例，并关闭本实例该文件的全部连接。"""
        taken = await self._take_verified_control_connections(mindmap_id, message)
        if taken is None:
            return
        websockets, presence_records = taken
        await asyncio.gather(
            self._close_connections(
                mindmap_id,
                websockets,
                presence_records,
                close_code=close_code,
                message=message,
            ),
            self._publish_redis_event(mindmap_id, message),
        )

    async def notify_and_disconnect_user(
        self,
        mindmap_id: int,
        user_id: int,
        message: dict,
        close_code: int = 4003,
        *,
        revocation_scope: str = 'access',
    ) -> None:
        """跨实例定向通知并断开指定用户，其他房间成员不接收该事件。"""
        if revocation_scope not in ACCESS_REVOCATION_SCOPES:
            raise ValueError('脑图权限撤销范围无效')
        event = {
            **message,
            'targetUserId': user_id,
            'revocationScope': revocation_scope,
        }
        taken = await self._take_verified_control_connections(mindmap_id, event)
        if taken is None:
            return
        websockets, presence_records = taken
        await asyncio.gather(
            self._close_connections(
                mindmap_id,
                websockets,
                presence_records,
                close_code=close_code,
                message=event,
            ),
            self._publish_redis_event(mindmap_id, event),
        )

    async def disconnect_stale_lineage_peers(
        self,
        mindmap_id: int,
        keep_websocket: WebSocket,
        content_revision: int,
    ) -> None:
        """DB 快照纠正本地 lineage 后，终止仍持有旧基线的其他连接。"""
        websockets, presence_records = await self._take_local_connections(
            mindmap_id,
            exclude_websocket=keep_websocket,
        )
        await self._close_connections(
            mindmap_id,
            websockets,
            presence_records,
            close_code=self._slow_consumer_close_code,
            message={
                'type': 'stale_state',
                'currentRevision': content_revision,
                'reason': 'yjs_lineage_changed',
                'message': '协作基线已在其他服务器更新，正在重新同步',
            },
        )

    async def get_room_users(self, mindmap_id: int) -> list[dict]:
        """获取跨实例在线成员；Redis 不可用时退回本实例成员。"""
        local_users = await self._get_local_room_users(mindmap_id)
        redis = self._redis
        if not redis:
            return self._deduplicate_users(local_users)

        key = self._presence_key(mindmap_id)
        now = time.time()
        cleanup_result = await self._safe_redis_call(
            redis.zremrangebyscore(key, 0, now),
            operation='清理过期在线成员',
        )
        if cleanup_result is None:
            return self._deduplicate_users(local_users)
        members = await self._safe_redis_call(
            redis.zrangebyscore(key, now, '+inf'),
            operation='读取在线成员',
        )
        if members is None:
            return self._deduplicate_users(local_users)

        users = []
        for member in members:
            user = self._deserialize_presence_user(member)
            if user:
                users.append(user)
        # Redis presence 是跨实例视图，但 Pub/Sub/zadd 短暂失败或 TTL 临界
        # 时可能只包含部分 worker。只要 Redis 返回任意远端成员就完全丢弃
        # 本地集合，会让仍然连着当前 worker 的用户从在线列表瞬时消失。
        # 本地连接是当前进程的最新事实，放在前面还能让去重时保留其新头像/
        # 昵称，再补齐其他实例成员。
        return self._deduplicate_users([*local_users, *users])

    async def _broadcast_local(
        self,
        mindmap_id: int,
        message: Any,
        exclude: WebSocket | None = None,
    ) -> None:
        async with self._lock:
            websockets = list(self._rooms.get(mindmap_id, ()))
        deliveries = []
        for websocket in websockets:
            if websocket == exclude:
                continue
            prepared_message = self._message_for_connection(websocket, message)
            if prepared_message is not None:
                deliveries.append(self.send_to(websocket, prepared_message))
        if deliveries:
            await asyncio.gather(*deliveries)

    async def send_to(self, websocket: WebSocket, message: Any) -> bool:
        """同一连接串行发送，不同连接并发，并隔离慢消费者背压。"""
        websocket_id = id(websocket)
        if websocket_id in self._retiring_connections:
            return False
        lock = self._send_locks.get(websocket_id)

        async def send() -> bool:
            if lock is None:
                await websocket.send_json(message)
                return True
            async with lock:
                if (
                    websocket_id in self._retiring_connections
                    or self._send_locks.get(websocket_id) is not lock
                ):
                    return False
                await websocket.send_json(message)
                return True

        try:
            return await asyncio.wait_for(send(), timeout=self._send_timeout_seconds)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            logger.warning('脑图协作慢连接发送超时，正在触发安全重连')
            await self._retire_failed_connection(websocket)
            return False
        except Exception:
            await self._retire_failed_connection(websocket)
            return False

    async def _retire_failed_connection(self, websocket: WebSocket) -> None:
        """先脱离房间再尽力关闭，关闭握手失败也不能重复拖慢广播。"""
        websocket_id = id(websocket)
        if websocket_id in self._retiring_connections:
            return
        was_registered = (
            websocket_id in self._connection_presence
            or websocket_id in self._send_locks
        )
        self._retiring_connections.add(websocket_id)
        await self._release_owned_node_edit_leases({websocket_id})
        await self._release_owned_seed_leases({websocket_id})
        presence = await self._detach_local_connection(websocket)

        async def close() -> None:
            try:
                await asyncio.wait_for(
                    websocket.close(code=self._slow_consumer_close_code),
                    timeout=self._send_timeout_seconds,
                )
            except Exception:
                return

        await asyncio.gather(
            close(),
            self._remove_presence_record(
                presence,
                operation='清理发送失败在线成员',
            ),
        )
        self._send_locks.pop(websocket_id, None)
        if not was_registered:
            self._retiring_connections.discard(websocket_id)

    async def _get_local_room_users(self, mindmap_id: int) -> list[dict]:
        async with self._lock:
            return [
                info
                for websocket in self._rooms.get(mindmap_id, ())
                if (info := self._user_info.get(id(websocket)))
            ]

    async def _publish_redis_event(
        self,
        mindmap_id: int,
        message: Any,
        *,
        expected_lineage_fence: str | None = None,
    ) -> bool:
        redis = self._redis
        if not redis:
            return expected_lineage_fence is None
        if not self._running:
            return False
        message = self._normalize_cross_instance_message(mindmap_id, message)
        if message is None:
            logger.warning('脑图协作事件不符合跨实例协议，已仅在本实例广播')
            return False
        event_id = uuid.uuid4().hex
        envelope = {
            'schemaVersion': REDIS_EVENT_SCHEMA_VERSION,
            'eventId': event_id,
            'sourceInstanceId': self._instance_id,
            'issuedAtMs': self._utc_now_ms(),
            'mindmapId': mindmap_id,
            'message': message,
        }
        try:
            payload = self._encode_redis_envelope(envelope)
        except (TypeError, ValueError, RecursionError):
            logger.warning('脑图协作事件无法序列化，已仅在本实例广播')
            return False
        if len(payload) > self._max_redis_event_bytes:
            logger.warning('脑图协作事件超过跨实例体积上限，已仅在本实例广播')
            return False
        if expected_lineage_fence is None:
            result = await self._safe_redis_call(
                redis.publish(self._channel, payload),
                operation='发布协作事件',
                failure_value=_REDIS_CALL_FAILED,
            )
        else:
            result = await self._safe_redis_call(
                redis.eval(
                    _VERIFY_LINEAGE_FENCE_AND_PUBLISH_SCRIPT,
                    1,
                    self._lineage_fence_key(mindmap_id),
                    expected_lineage_fence,
                    self._channel,
                    payload,
                ),
                operation='校验 lineage 并发布协作事件',
                failure_value=_REDIS_CALL_FAILED,
            )
        if result is _REDIS_CALL_FAILED or result == -1:
            return False
        self._remember_event(event_id)
        return True

    async def _listen_redis_events(self) -> None:
        retry_delay = 1
        while self._running and self._redis:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(self._channel)
                self._listener_ready.set()
                retry_delay = 1
                async for item in pubsub.listen():
                    if not self._running:
                        break
                    if item.get('type') != 'message':
                        continue
                    await self._handle_redis_event(item.get('data'))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._listener_ready.clear()
                record_mindmap_event('redis_transport_degraded')
                logger.warning(f'脑图协作 Redis 订阅异常: {error}，{retry_delay} 秒后重试')
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
            finally:
                with suppress(Exception):
                    await pubsub.unsubscribe(self._channel)
                with suppress(Exception):
                    await pubsub.aclose()

    async def _handle_redis_event(self, raw_data: Any) -> None:
        envelope = self._decode_redis_envelope(raw_data)
        if envelope is None:
            return
        schema_version = envelope.get('schemaVersion')
        event_id = envelope.get('eventId')
        source_instance_id = envelope.get('sourceInstanceId')
        issued_at_ms = envelope.get('issuedAtMs')
        mindmap_id = envelope.get('mindmapId')
        message = envelope.get('message')
        now_ms = self._utc_now_ms()
        if (
            schema_version != REDIS_EVENT_SCHEMA_VERSION
            or not isinstance(event_id, str)
            or not event_id
            or len(event_id) > MAX_REDIS_EVENT_IDENTITY_LENGTH
            or not isinstance(source_instance_id, str)
            or not source_instance_id
            or len(source_instance_id) > MAX_REDIS_EVENT_IDENTITY_LENGTH
            or source_instance_id == self._instance_id
            or type(issued_at_ms) is not int
            or issued_at_ms < now_ms - REDIS_EVENT_MAX_AGE_MS
            or issued_at_ms > now_ms + REDIS_EVENT_MAX_FUTURE_SKEW_MS
            or type(mindmap_id) is not int
            or mindmap_id <= 0
        ):
            return
        message = self._normalize_cross_instance_message(mindmap_id, message)
        if message is None or not self._remember_event(event_id):
            return

        message_type = message.get('type')
        if message_type == 'room_write_capability_required':
            await self._activate_local_write_capability(
                mindmap_id,
                message['capability'],
            )
            return
        if message_type in {
            'access_revoked',
            'document_deleted',
            'document_archived',
        }:
            taken = await self._take_verified_control_connections(
                mindmap_id,
                message,
            )
            if taken is None:
                return
            websockets, presence_records = taken
            await self._close_connections(
                mindmap_id,
                websockets,
                presence_records,
                close_code={
                    'access_revoked': 4003,
                    'document_deleted': 4004,
                    'document_archived': 4005,
                }[message_type],
                message=message,
            )
            return

        revision = message.get('contentRevision')
        if type(revision) is int:
            self.set_content_revision(
                mindmap_id,
                revision,
                transition_type=message_type,
            )
        if (
            message_type in {'sync_step1', 'sync_step2', 'update'}
            and (
                message.get('lineageId') is None
                or not await self.verify_content_lineage_fence(
                    mindmap_id,
                    revision,
                    message.get('lineageId'),
                )
                or not self.set_content_lineage(
                    mindmap_id,
                    revision,
                    message.get('lineageId'),
                    replace=message.get('seedState') is True,
                )
            )
        ):
            # 跨 worker 的旧 lineage 不能进入本地健康房间。权威种子已经先在
            # 来源 worker 完成数据库 CAS，seedState 才允许原子切换栅栏。
            record_mindmap_event('yjs_lineage_mismatch')
            return
        await self._broadcast_local(mindmap_id, message)

    async def _take_verified_control_connections(
        self,
        mindmap_id: int,
        message: dict,
    ) -> tuple[list[WebSocket], list[tuple[int, str, str]]] | None:
        """在脑图行锁内复核控制事件，并冻结仍应断开的连接。

        本机提交后的通知与 Redis 消息都可能晚于恢复、重新添加协作者或重新
        授予编辑权。WebSocket 鉴权与这些写操作采用相同的脑图主记录锁顺序，
        因此在锁内完成本地连接摘除，可将状态检查与集合选择合并为一个顺序点。
        """
        try:
            # 延迟导入避免房间传输层初始化时引入数据库实体依赖。
            from sqlalchemy import select  # noqa: PLC0415

            from config.database import AsyncSessionLocal  # noqa: PLC0415
            from module_mindmap.dao.mindmap_collaborator_dao import (  # noqa: PLC0415
                MindmapCollaboratorDao,
            )
            from module_mindmap.entity.do.mindmap_do import Mindmap  # noqa: PLC0415

            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(
                        select(
                            Mindmap.owner_id,
                            Mindmap.status,
                            Mindmap.del_flag,
                        )
                        .where(Mindmap.id == mindmap_id)
                        .with_for_update()
                    )
                ).one_or_none()
                message_type = message.get('type')
                if message_type == 'document_deleted':
                    is_current = row is None or row.del_flag != '0'
                    user_id = None
                    editable_only = False
                elif message_type == 'document_archived':
                    is_current = (
                        row is not None
                        and row.del_flag == '0'
                        and row.status == 1
                    )
                    user_id = None
                    editable_only = False
                else:
                    user_id = message['targetUserId']
                    permission = None
                    if row is not None and row.del_flag == '0':
                        permission = (
                            1
                            if row.owner_id == user_id
                            else await MindmapCollaboratorDao.get_collaborator_permission(
                                db,
                                mindmap_id,
                                user_id,
                            )
                        )
                    # 事件中的 scope 只是发送原因，可能已经过期。真正的断开
                    # 动作由当前权限派生：已重新授予编辑则忽略，当前只读仅退
                    # 休旧可写连接，已移除访问则关闭该用户的全部连接。
                    is_current = permission is None or permission < 1
                    editable_only = permission is not None

                if not is_current:
                    return None
                # 保持数据库行锁直到连接集合已从本地路由表摘除。随后完成的
                # 恢复/授权以及其新连接不会被这条旧控制事件关闭。
                return await self._take_local_connections(
                    mindmap_id,
                    user_id=user_id,
                    editable_only=editable_only,
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # 无法确认事件仍有效时必须 fail-open。心跳权限复核会收敛真正的
            # 撤权状态；在数据库短暂故障时错误断开有效会话则无法恢复现场。
            logger.warning(
                '复核脑图 Redis 控制事件失败，已忽略本次断开: '
                f'mindmap_id={mindmap_id}, '
                f'event_type={message.get("type")}, '
                f'error_type={type(error).__name__}'
            )
            return None

    def _decode_redis_envelope(self, raw_data: Any) -> dict | None:
        try:
            if isinstance(raw_data, bytes):
                payload = raw_data
            elif isinstance(raw_data, str):
                if len(raw_data) > self._max_redis_event_bytes:
                    return None
                payload = raw_data.encode('utf-8')
            else:
                return None
            if (
                len(payload) > self._max_redis_event_bytes
                or not self._verify_redis_event_signature(payload)
            ):
                return None
            envelope = json.loads(payload)
            return envelope if isinstance(envelope, dict) else None
        except (
            TypeError,
            ValueError,
            UnicodeDecodeError,
            RecursionError,
        ):
            return None

    def _encode_redis_envelope(self, envelope: dict) -> bytes:
        unsigned_payload = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
        return self._append_redis_event_signature(unsigned_payload)

    def _append_redis_event_signature(self, unsigned_payload: bytes) -> bytes:
        if not unsigned_payload.endswith(b'}'):
            raise ValueError('脑图跨实例事件信封格式无效')
        signature = hmac.new(
            self._redis_event_signing_key,
            unsigned_payload,
            hashlib.sha256,
        ).hexdigest().encode('ascii')
        return b''.join((
            unsigned_payload[:-1],
            REDIS_EVENT_SIGNATURE_PREFIX,
            signature,
            REDIS_EVENT_SIGNATURE_SUFFIX,
        ))

    def _verify_redis_event_signature(self, payload: bytes) -> bool:
        trailer_size = (
            len(REDIS_EVENT_SIGNATURE_PREFIX)
            + REDIS_EVENT_SIGNATURE_BYTES
            + len(REDIS_EVENT_SIGNATURE_SUFFIX)
        )
        signature_start = len(payload) - trailer_size
        prefix_end = signature_start + len(REDIS_EVENT_SIGNATURE_PREFIX)
        if (
            signature_start <= 0
            or payload[signature_start:prefix_end]
            != REDIS_EVENT_SIGNATURE_PREFIX
            or not payload.endswith(REDIS_EVENT_SIGNATURE_SUFFIX)
        ):
            return False
        signature_offset = prefix_end
        signature = payload[
            signature_offset:signature_offset + REDIS_EVENT_SIGNATURE_BYTES
        ]
        signer = hmac.new(
            self._redis_event_signing_key,
            digestmod=hashlib.sha256,
        )
        signer.update(memoryview(payload)[:signature_start])
        signer.update(b'}')
        return hmac.compare_digest(signer.hexdigest().encode('ascii'), signature)

    @staticmethod
    def _normalize_cross_instance_message(
        mindmap_id: int,
        message: Any,
    ) -> dict | None:
        """只允许服务端实际发布的事件跨 worker，并锁定危险事件资源身份。"""
        if not isinstance(message, dict):
            return None
        msg_type = message.get('type')
        if msg_type not in CROSS_INSTANCE_MESSAGE_TYPES:
            return None
        if msg_type in {'sync_step1', 'sync_step2', 'update'}:
            update = message.get('update')
            if not isinstance(update, str) or not update:
                return None
        if msg_type == 'room_write_capability_required':
            capability = message.get('capability')
            if capability not in ROOM_WRITE_CAPABILITIES:
                return None
            return {'type': msg_type, 'capability': capability}
        if (
            msg_type in {'document_deleted', 'document_archived', 'access_revoked'}
            and message.get('mindmapId') != mindmap_id
        ):
            return None
        if msg_type == 'access_revoked':
            target_user_id = message.get('targetUserId')
            if type(target_user_id) is not int or target_user_id <= 0:
                return None
            revocation_scope = message.get('revocationScope', 'access')
            if revocation_scope not in ACCESS_REVOCATION_SCOPES:
                return None
            # 缺少范围的旧 worker 事件沿用历史的“完全撤销访问”语义。
            return {**message, 'revocationScope': revocation_scope}
        return message

    async def _close_local_room(self, mindmap_id: int, close_code: int) -> None:
        """清除本地房间、在线状态并尽力关闭连接。"""
        websockets, presence_records = await self._take_local_connections(mindmap_id)
        await self._close_connections(
            mindmap_id, websockets, presence_records, close_code=close_code,
        )

    async def _disconnect_local_user(
        self,
        mindmap_id: int,
        user_id: int,
        message: dict,
        close_code: int,
        *,
        editable_only: bool = False,
    ) -> None:
        websockets, presence_records = await self._take_local_connections(
            mindmap_id,
            user_id=user_id,
            editable_only=editable_only,
        )
        await self._close_connections(
            mindmap_id,
            websockets,
            presence_records,
            close_code=close_code,
            message=message,
        )

    async def _take_local_connections(
        self,
        mindmap_id: int,
        user_id: int | None = None,
        *,
        exclude_websocket: WebSocket | None = None,
        editable_only: bool = False,
        missing_capability: str | None = None,
    ) -> tuple[list[WebSocket], list[tuple[int, str, str]]]:
        seed_releases: list[tuple[tuple[int, int], str]] = []
        node_edit_releases: list[tuple[tuple[int, str, str], str]] = []
        async with self._lock:
            room = self._rooms.get(mindmap_id, set())
            websockets = [
                websocket
                for websocket in room
                if websocket is not exclude_websocket
                and (
                    not editable_only
                    or self._connection_can_edit.get(id(websocket), True)
                )
                and (
                    missing_capability is None
                    or missing_capability
                    not in self._connection_capabilities.get(id(websocket), set())
                )
                and (
                    user_id is None
                    or str(
                        (self._user_info.get(id(websocket)) or {}).get('id', '')
                    ) == str(user_id)
                )
            ]
            presence_records = []
            disconnected_ids = {id(websocket) for websocket in websockets}
            seed_owners = {
                websocket_id: presence[1]
                for websocket_id, presence in self._connection_presence.items()
                if websocket_id in disconnected_ids
            }
            for websocket in websockets:
                room.discard(websocket)
                self._blocked_disconnect_persistence.add(id(websocket))
                self._user_info.pop(id(websocket), None)
                self._connection_capabilities.pop(id(websocket), None)
                self._connection_can_edit.pop(id(websocket), None)
                if presence := self._connection_presence.pop(id(websocket), None):
                    presence_records.append(presence)
            for key in [
                key
                for key, lease in self._local_seed_leases.items()
                if lease[0] in disconnected_ids
            ]:
                lease = self._local_seed_leases.pop(key, None)
                if lease and (owner := seed_owners.get(lease[0])):
                    seed_releases.append((key, owner))
            for key in [
                key
                for key, lease in self._local_node_edit_leases.items()
                if lease[0] in disconnected_ids
            ]:
                lease = self._local_node_edit_leases.pop(key, None)
                if lease:
                    node_edit_releases.append((key, lease[1]))
            if not room:
                self._rooms.pop(mindmap_id, None)
                self._content_revisions.pop(mindmap_id, None)
                self._content_lineages.pop(mindmap_id, None)
                self._local_lineage_epochs.pop(mindmap_id, None)
                self._pending_content_lineages.pop(mindmap_id, None)
                self._content_lineage_generations.pop(mindmap_id, None)
                self._clear_local_seed_leases(mindmap_id)
                self._clear_local_node_edit_leases(mindmap_id)
        await asyncio.gather(*(
            self._release_redis_seed_lease(key, owner)
            for key, owner in seed_releases
        ))
        await asyncio.gather(*(
            self._release_redis_node_edit_lease(key, owner)
            for key, owner in node_edit_releases
        ))
        return websockets, presence_records

    async def _close_connections(
        self,
        mindmap_id: int,
        websockets: list[WebSocket],
        presence_records: list[tuple[int, str, str]],
        *,
        close_code: int,
        message: dict | None = None,
    ) -> None:
        await asyncio.gather(*(
            self._safe_notify_and_close_websocket(websocket, close_code, message)
            for websocket in websockets
        ))
        for websocket in websockets:
            self._send_locks.pop(id(websocket), None)
        if self._redis and presence_records:
            await self._safe_redis_call(
                self._redis.zrem(
                    self._presence_key(mindmap_id),
                    *(presence[2] for presence in presence_records),
                ),
                operation='关闭已删除脑图在线成员',
            )

    async def _safe_notify_and_close_websocket(
        self, websocket: WebSocket, close_code: int, message: dict | None,
    ) -> None:
        try:
            if message is not None:
                await self.send_to(websocket, message)
            await websocket.close(code=close_code)
        except Exception:
            return

    async def _write_presence(self, mindmap_id: int, member: str) -> None:
        redis = self._redis
        if not redis:
            return
        key = self._presence_key(mindmap_id)
        expires_at = time.time() + self._presence_ttl_seconds
        result = await self._safe_redis_call(
            redis.zadd(key, {member: expires_at}),
            operation='刷新在线成员',
        )
        if result is not None:
            await self._safe_redis_call(
                redis.expire(key, self._presence_ttl_seconds * 2),
                operation='设置在线成员过期时间',
            )

    async def _safe_redis_call(
        self,
        awaitable: Any,
        operation: str,
        *,
        failure_value: Any = None,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                awaitable,
                timeout=self._redis_operation_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            record_mindmap_event('redis_transport_degraded')
            logger.warning(f'脑图协作 Redis {operation}失败，已启用该操作的安全降级策略: {error}')
            return failure_value

    def _serialize_presence(self, connection_id: str, user_info: dict) -> str:
        return json.dumps(
            {
                'connectionId': connection_id,
                'instanceId': self._instance_id,
                'user': user_info,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        )

    @staticmethod
    def _deserialize_presence_user(member: Any) -> dict | None:
        try:
            payload = json.loads(member.decode() if isinstance(member, bytes) else member)
            user = payload.get('user')
            return user if isinstance(user, dict) else None
        except (TypeError, ValueError, AttributeError, UnicodeDecodeError):
            return None

    def _presence_key(self, mindmap_id: int) -> str:
        return f'{self._presence_key_prefix}{mindmap_id}'

    def _node_edit_lease_key(
        self,
        mindmap_id: int,
        lineage_epoch: str,
        node_uid: str,
    ) -> str:
        uid_digest = hashlib.sha256(node_uid.encode('utf-8')).hexdigest()
        return (
            f'{self._node_edit_lease_key_prefix}'
            f'{mindmap_id}:{lineage_epoch}:{uid_digest}'
        )

    def _write_capability_key(self, mindmap_id: int, capability: str) -> str:
        return f'{self._write_capability_key_prefix}{mindmap_id}:{capability}'

    def _lineage_fence_key(self, mindmap_id: int) -> str:
        return f'{self._lineage_fence_key_prefix}{mindmap_id}'

    def _lineage_gap_key(self, mindmap_id: int, revision: int) -> str:
        return f'{self._lineage_gap_key_prefix}{mindmap_id}:{revision}'

    def _message_for_connection(self, websocket: WebSocket, message: Any) -> Any | None:
        """新客户端收紧凑补丁；旧客户端在滚动升级期间继续收到完整状态。"""
        capabilities = self._connection_capabilities.get(id(websocket), set())
        if (
            isinstance(message, dict)
            and message.get('type') == 'content_revision_changed'
            and 'yjsUpdateCount' in message
            and YJS_MUTATION_SEQUENCE_CAPABILITY not in capabilities
        ):
            # 旧客户端只按“是否见过任意一帧”确认 mutation，无法证明序列
            # 已完整到达。不要把新协议确认降级成不安全的快进，统一要求其
            # 从数据库正文回源；这样后端可先于前端安全滚动发布。
            return {
                'type': 'stale_state',
                'currentRevision': message.get('contentRevision'),
                'reason': 'mutation_sequence_capability_required',
                'message': '协作协议已升级，正在加载云端完整内容',
            }
        if (
            isinstance(message, dict)
            and message.get('type') == 'update'
            and message.get('checkpoint') is True
        ):
            if (
                STRUCTURED_NODE_PATCH_CAPABILITY in capabilities
                and YJS_CHECKPOINT_CAPABILITY in capabilities
            ):
                return None
            return {key: value for key, value in message.items() if key != 'checkpoint'}
        if (
            isinstance(message, dict)
            and message.get('type') == 'update'
            and message.get('patch') is not None
        ):
            if CONDITIONAL_NODE_PATCH_CAPABILITY in capabilities:
                return {**message, 'state': None}
            # 旧 structured-node-patch-v1 客户端会把整节点快照无条件写回
            # Y.Doc，在同节点并发编辑时可能覆盖 CRDT 胜者。滚动升级期间
            # 只向明确声明条件补丁能力的新客户端发送 patch；其他连接继续
            # 使用标准 Yjs 增量（有完整 state 时一并保留）。
            return {**message, 'patch': None}
        return message

    @staticmethod
    def _create_instance_id() -> str:
        return f'{os.getpid()}-{uuid.uuid4().hex}'

    @staticmethod
    def _utc_now_ms() -> int:
        return time.time_ns() // 1_000_000

    def _remember_event(self, event_id: str) -> bool:
        if event_id in self._seen_event_ids:
            return False
        if len(self._seen_event_order) >= self._max_seen_events:
            expired = self._seen_event_order.popleft()
            self._seen_event_ids.discard(expired)
        self._seen_event_ids.add(event_id)
        self._seen_event_order.append(event_id)
        return True

    @staticmethod
    def _deduplicate_users(users: list[dict]) -> list[dict]:
        result: list[dict] = []
        seen: set[str] = set()
        for user in users:
            identity = str(user.get('id') or user.get('userId') or '')
            if not identity:
                identity = json.dumps(user, ensure_ascii=False, sort_keys=True, default=str)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(user)
        return result


room_manager = RoomManager()
