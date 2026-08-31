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

from config.env import JwtConfig
from module_mindmap.service.mindmap_metrics import record_mindmap_event
from utils.log_util import logger

STRUCTURED_NODE_PATCH_CAPABILITY = 'structured-node-patch-v1'
YJS_CHECKPOINT_CAPABILITY = 'yjs-checkpoint-v1'
CROSS_INSTANCE_MESSAGE_TYPES = frozenset({
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
})
MAX_REDIS_EVENT_IDENTITY_LENGTH = 128
REDIS_EVENT_SCHEMA_VERSION = 2
REDIS_EVENT_SIGNATURE_BYTES = 64
REDIS_EVENT_SIGNATURE_PREFIX = b',"signature":"'
REDIS_EVENT_SIGNATURE_SUFFIX = b'"}'
REDIS_EVENT_SIGNING_CONTEXT = b'mindmap-redis-events-v2'
REDIS_EVENT_MAX_AGE_MS = 2 * 60 * 1000
REDIS_EVENT_MAX_FUTURE_SKEW_MS = 30 * 1000


class RoomManager:
    """管理本地 WebSocket 房间，并通过 Redis 同步不同应用实例。"""

    _channel = 'mindmap:collaboration:events:v2'
    _presence_key_prefix = 'mindmap:collaboration:presence:v1:'
    _seed_key_prefix = 'mindmap:collaboration:seed:v1:'
    _presence_ttl_seconds = 120
    _seed_lease_ttl_seconds = 10
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
        self._content_revisions: dict[int, int] = {}
        self._connection_presence: dict[int, tuple[int, str, str]] = {}
        self._send_locks: dict[int, asyncio.Lock] = {}
        self._retiring_connections: set[int] = set()
        self._blocked_disconnect_persistence: set[int] = set()
        self._local_seed_leases: dict[tuple[int, int], tuple[int, float]] = {}
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
        task = self._listener_task
        self._listener_task = None
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        redis = self._redis
        presence_records = list(self._connection_presence.values())
        if redis:
            for mindmap_id, _connection_id, member in presence_records:
                await self._safe_redis_call(
                    redis.zrem(self._presence_key(mindmap_id), member),
                    operation='清理在线成员',
                )
        self._connection_presence.clear()
        self._send_locks.clear()
        self._retiring_connections.clear()
        self._connection_capabilities.clear()
        self._blocked_disconnect_persistence.clear()
        self._local_seed_leases.clear()
        self._redis = None
        self._listener_ready.clear()

    async def join(
        self,
        mindmap_id: int,
        websocket: WebSocket,
        user_info: dict,
        capabilities: set[str] | None = None,
    ) -> None:
        connection_id = uuid.uuid4().hex
        member = self._serialize_presence(connection_id, user_info)
        async with self._lock:
            self._rooms.setdefault(mindmap_id, set()).add(websocket)
            self._user_info[id(websocket)] = user_info
            self._connection_capabilities[id(websocket)] = set(capabilities or ())
            self._connection_presence[id(websocket)] = (mindmap_id, connection_id, member)
            self._send_locks.setdefault(id(websocket), asyncio.Lock())
            self._retiring_connections.discard(id(websocket))
        await self._write_presence(mindmap_id, member)

    async def leave(self, mindmap_id: int, websocket: WebSocket) -> None:
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
            presence = self._connection_presence.pop(id(websocket), None)
            mindmap_id = presence[0] if presence else expected_mindmap_id
            if mindmap_id in self._rooms:
                self._rooms[mindmap_id].discard(websocket)
                if not self._rooms[mindmap_id]:
                    del self._rooms[mindmap_id]
                    self._content_revisions.pop(mindmap_id, None)
                    self._clear_local_seed_leases(mindmap_id)
            self._user_info.pop(id(websocket), None)
            self._connection_capabilities.pop(id(websocket), None)
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

    async def touch_presence(self, mindmap_id: int, websocket: WebSocket) -> None:
        """刷新连接的分布式在线状态，供心跳任务调用。"""
        presence = self._connection_presence.get(id(websocket))
        if presence and presence[0] == mindmap_id:
            await self._write_presence(mindmap_id, presence[2])

    def set_content_revision(self, mindmap_id: int, revision: int | None) -> None:
        """缓存在线房间的最新持久化 revision，旧值不能覆盖新值。"""
        if mindmap_id not in self._rooms or type(revision) is not int:
            return
        current = self._content_revisions.get(mindmap_id, 0)
        self._content_revisions[mindmap_id] = max(current, revision)

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
        if self._redis:
            result = await self._safe_redis_call(
                self._redis.set(
                    f'{self._seed_key_prefix}{mindmap_id}:{content_revision}',
                    owner,
                    nx=True,
                    ex=self._seed_lease_ttl_seconds,
                ),
                operation='竞争脑图协作初始化租约',
            )
            return result is True or result in {b'OK', 'OK'}

        key = (mindmap_id, content_revision)
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

    def _clear_local_seed_leases(self, mindmap_id: int) -> None:
        for key in [key for key in self._local_seed_leases if key[0] == mindmap_id]:
            self._local_seed_leases.pop(key, None)

    async def broadcast(self, mindmap_id: int, message: Any, exclude: WebSocket | None = None) -> None:
        """先广播给本实例连接，再发布到 Redis 供其他实例转发。"""
        await self._broadcast_local(mindmap_id, message, exclude=exclude)
        await self._publish_redis_event(mindmap_id, message)

    async def broadcast_checkpoint(
        self,
        mindmap_id: int,
        state: str,
        origin: str,
        content_revision: int,
        exclude: WebSocket | None = None,
    ) -> None:
        """以标准 update 发布检查点，新 worker 再按连接能力抑制冗余消息。"""
        await self.broadcast(
            mindmap_id,
            {
                'type': 'update',
                'update': state,
                'state': state,
                'patch': None,
                'checkpoint': True,
                'contentRevision': content_revision,
                'origin': origin,
            },
            exclude=exclude,
        )

    async def broadcast_and_close_room(
        self, mindmap_id: int, message: dict, close_code: int = 4004,
    ) -> None:
        """广播终止事件到所有实例，并关闭本实例该文件的全部连接。"""
        await self.broadcast(mindmap_id, message)
        await self._close_local_room(mindmap_id, close_code)

    async def notify_and_disconnect_user(
        self, mindmap_id: int, user_id: int, message: dict, close_code: int = 4003,
    ) -> None:
        """跨实例定向通知并断开指定用户，其他房间成员不接收该事件。"""
        event = {**message, 'targetUserId': user_id}
        await self._disconnect_local_user(mindmap_id, user_id, event, close_code)
        await self._publish_redis_event(mindmap_id, event)

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
        return self._deduplicate_users(users or local_users)

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

    async def _publish_redis_event(self, mindmap_id: int, message: Any) -> None:
        redis = self._redis
        if not redis or not self._running:
            return
        message = self._normalize_cross_instance_message(mindmap_id, message)
        if message is None:
            logger.warning('脑图协作事件不符合跨实例协议，已仅在本实例广播')
            return
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
            return
        if len(payload) > self._max_redis_event_bytes:
            logger.warning('脑图协作事件超过跨实例体积上限，已仅在本实例广播')
            return
        self._remember_event(event_id)
        await self._safe_redis_call(
            redis.publish(self._channel, payload),
            operation='发布协作事件',
        )

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

        if message.get('type') == 'access_revoked':
            target_user_id = message.get('targetUserId')
            if type(target_user_id) is int:
                await self._disconnect_local_user(mindmap_id, target_user_id, message, 4003)
            return

        revision = message.get('contentRevision')
        if type(revision) is int:
            self.set_content_revision(mindmap_id, revision)
        await self._broadcast_local(mindmap_id, message)
        if message.get('type') == 'document_deleted':
            await self._close_local_room(mindmap_id, 4004)
        elif message.get('type') == 'document_archived':
            await self._close_local_room(mindmap_id, 4005)

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
        if msg_type == 'update':
            update = message.get('update')
            if not isinstance(update, str) or not update:
                return None
        if (
            msg_type in {'document_deleted', 'document_archived', 'access_revoked'}
            and message.get('mindmapId') != mindmap_id
        ):
            return None
        if msg_type == 'access_revoked':
            target_user_id = message.get('targetUserId')
            if type(target_user_id) is not int or target_user_id <= 0:
                return None
        return message

    async def _close_local_room(self, mindmap_id: int, close_code: int) -> None:
        """清除本地房间、在线状态并尽力关闭连接。"""
        websockets, presence_records = await self._take_local_connections(mindmap_id)
        await self._close_connections(
            mindmap_id, websockets, presence_records, close_code=close_code,
        )

    async def _disconnect_local_user(
        self, mindmap_id: int, user_id: int, message: dict, close_code: int,
    ) -> None:
        websockets, presence_records = await self._take_local_connections(
            mindmap_id, user_id=user_id,
        )
        await self._close_connections(
            mindmap_id,
            websockets,
            presence_records,
            close_code=close_code,
            message=message,
        )

    async def _take_local_connections(
        self, mindmap_id: int, user_id: int | None = None,
    ) -> tuple[list[WebSocket], list[tuple[int, str, str]]]:
        async with self._lock:
            room = self._rooms.get(mindmap_id, set())
            websockets = [
                websocket
                for websocket in room
                if user_id is None or str(
                    (self._user_info.get(id(websocket)) or {}).get('id', '')
                ) == str(user_id)
            ]
            presence_records = []
            for websocket in websockets:
                room.discard(websocket)
                self._blocked_disconnect_persistence.add(id(websocket))
                self._user_info.pop(id(websocket), None)
                self._connection_capabilities.pop(id(websocket), None)
                if presence := self._connection_presence.pop(id(websocket), None):
                    presence_records.append(presence)
            if not room:
                self._rooms.pop(mindmap_id, None)
                self._content_revisions.pop(mindmap_id, None)
                self._clear_local_seed_leases(mindmap_id)
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

    async def _safe_redis_call(self, awaitable: Any, operation: str) -> Any | None:
        try:
            return await asyncio.wait_for(
                awaitable,
                timeout=self._redis_operation_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            record_mindmap_event('redis_transport_degraded')
            logger.warning(f'脑图协作 Redis {operation}失败，已降级为单实例模式: {error}')
            return None

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

    def _message_for_connection(self, websocket: WebSocket, message: Any) -> Any | None:
        """新客户端收紧凑补丁；旧客户端在滚动升级期间继续收到完整状态。"""
        capabilities = self._connection_capabilities.get(id(websocket), set())
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
            and STRUCTURED_NODE_PATCH_CAPABILITY
            in capabilities
        ):
            return {**message, 'state': None}
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
