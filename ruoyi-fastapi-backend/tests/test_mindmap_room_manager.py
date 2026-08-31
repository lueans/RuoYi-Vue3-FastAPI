"""脑图协作房间 revision 与广播行为测试。"""
import asyncio
import json
import time
import unittest
from collections.abc import AsyncIterator, Callable
from typing import Any

from module_mindmap.service.mindmap_metrics import mindmap_metrics
from module_mindmap.websocket.room_manager import (
    REDIS_EVENT_MAX_AGE_MS,
    REDIS_EVENT_MAX_FUTURE_SKEW_MS,
    STRUCTURED_NODE_PATCH_CAPABILITY,
    YJS_CHECKPOINT_CAPABILITY,
    RoomManager,
)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.close_codes: list[int] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)

    async def close(self, code: int) -> None:
        self.close_codes.append(code)


class _SlowWebSocket(_FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send_json(self, message: dict) -> None:
        self.send_started.set()
        await self.release_send.wait()
        self.messages.append(message)


class _StuckWebSocket(_SlowWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_attempts = 0
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()

    async def send_json(self, message: dict) -> None:
        self.send_attempts += 1
        await super().send_json(message)

    async def close(self, code: int) -> None:
        self.close_started.set()
        await self.release_close.wait()
        self.close_codes.append(code)


class _SerialWebSocket(_FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.first_send_started = asyncio.Event()
        self.release_first_send = asyncio.Event()
        self.active_sends = 0
        self.max_active_sends = 0

    async def send_json(self, message: dict) -> None:
        self.active_sends += 1
        self.max_active_sends = max(self.max_active_sends, self.active_sends)
        try:
            if message['sequence'] == 1:
                self.first_send_started.set()
                await self.release_first_send.wait()
            self.messages.append(message)
        finally:
            self.active_sends -= 1


class _FakeRedisBroker:
    def __init__(self) -> None:
        self.subscribers: set[_FakePubSub] = set()
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.strings: dict[str, str] = {}


class _FakePubSub:
    def __init__(self, broker: _FakeRedisBroker) -> None:
        self.broker = broker
        self.queue: asyncio.Queue = asyncio.Queue()
        self.channels: set[str] = set()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channels.add(channel)
        self.broker.subscribers.add(self)

    async def unsubscribe(self, channel: str) -> None:
        self.channels.discard(channel)
        if not self.channels:
            self.broker.subscribers.discard(self)

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        while not self.closed:
            yield await self.queue.get()

    async def close(self) -> None:
        self.closed = True
        self.broker.subscribers.discard(self)

    async def aclose(self) -> None:
        await self.close()


class _FakeRedis:
    def __init__(self, broker: _FakeRedisBroker, fail_publish: bool = False) -> None:
        self.broker = broker
        self.fail_publish = fail_publish

    def pubsub(self) -> _FakePubSub:
        return _FakePubSub(self.broker)

    async def publish(self, channel: str, payload: str) -> int:
        if self.fail_publish:
            raise ConnectionError('redis unavailable')
        subscribers = [item for item in self.broker.subscribers if channel in item.channels]
        for subscriber in subscribers:
            await subscriber.queue.put({'type': 'message', 'data': payload})
        return len(subscribers)

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        del ex
        if nx and key in self.broker.strings:
            return None
        self.broker.strings[key] = value
        return True

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        bucket = self.broker.sorted_sets.setdefault(key, {})
        created = sum(member not in bucket for member in mapping)
        bucket.update(mapping)
        return created

    async def expire(self, _key: str, _seconds: int) -> bool:
        return True

    async def zrem(self, key: str, *members: str) -> int:
        bucket = self.broker.sorted_sets.setdefault(key, {})
        return sum(bucket.pop(member, None) is not None for member in members)

    async def zremrangebyscore(self, key: str, minimum: float, maximum: float) -> int:
        bucket = self.broker.sorted_sets.setdefault(key, {})
        expired = [member for member, score in bucket.items() if minimum <= score <= maximum]
        for member in expired:
            bucket.pop(member, None)
        return len(expired)

    async def zrangebyscore(self, key: str, minimum: float, maximum: str) -> list[str]:
        upper = float('inf') if maximum == '+inf' else float(maximum)
        bucket = self.broker.sorted_sets.setdefault(key, {})
        return [member for member, score in bucket.items() if minimum <= score <= upper]


class MindmapRoomManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_snapshot_exposes_counts_and_transport_health_without_identities(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='runtime-snapshot')
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        third = _FakeWebSocket()

        self.assertEqual(await manager.get_runtime_snapshot(), {
            'activeRooms': 0,
            'activeConnections': 0,
            'retiringConnections': 0,
            'redisTransportState': 'stopped',
        })
        await manager.start(_FakeRedis(broker))
        try:
            await manager.join(5, first, {'id': 1, 'name': 'Alice'})
            await manager.join(5, second, {'id': 2, 'name': 'Bob'})
            await manager.join(6, third, {'id': 3, 'name': 'Carol'})

            snapshot = await manager.get_runtime_snapshot()
            self.assertEqual(snapshot, {
                'activeRooms': 2,
                'activeConnections': 3,
                'retiringConnections': 0,
                'redisTransportState': 'ready',
            })
            self.assertNotIn('Alice', str(snapshot))

            manager._listener_ready.clear()
            self.assertEqual(
                (await manager.get_runtime_snapshot())['redisTransportState'],
                'degraded',
            )
        finally:
            await manager.leave(5, first)
            await manager.leave(5, second)
            await manager.leave(6, third)
            await manager.stop()

    async def test_redis_failure_records_a_fixed_degradation_event(self) -> None:
        mindmap_metrics.reset_for_tests()
        manager = RoomManager()

        async def fail() -> None:
            raise ConnectionError('redis unavailable')

        try:
            self.assertIsNone(await manager._safe_redis_call(fail(), '测试调用'))
            event_counts = {
                item['event']: item['count']
                for item in mindmap_metrics.snapshot()['events']
            }
            self.assertEqual(event_counts['redis_transport_degraded'], 1)
        finally:
            mindmap_metrics.reset_for_tests()

    async def test_only_one_local_connection_can_seed_same_revision(self) -> None:
        manager = RoomManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        await manager.join(5, first, {'id': 1})
        await manager.join(5, second, {'id': 2})

        self.assertTrue(await manager.acquire_seed_lease(5, 3, first))
        self.assertTrue(await manager.acquire_seed_lease(5, 3, first))
        self.assertFalse(await manager.acquire_seed_lease(5, 3, second))

    async def test_seed_lease_is_unique_across_instances(self) -> None:
        broker = _FakeRedisBroker()
        first_manager = RoomManager(instance_id='seed-first')
        second_manager = RoomManager(instance_id='seed-second')
        await first_manager.start(_FakeRedis(broker))
        await second_manager.start(_FakeRedis(broker))
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        await first_manager.join(6, first, {'id': 1})
        await second_manager.join(6, second, {'id': 2})
        try:
            results = await asyncio.gather(
                first_manager.acquire_seed_lease(6, 4, first),
                second_manager.acquire_seed_lease(6, 4, second),
            )
            self.assertEqual(sum(results), 1)
        finally:
            await first_manager.stop()
            await second_manager.stop()

    async def test_revision_never_moves_backwards_and_is_removed_with_room(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()

        await manager.join(7, websocket, {'id': 1})
        manager.set_content_revision(7, 5)
        manager.set_content_revision(7, 3)

        self.assertEqual(manager.get_content_revision(7), 5)
        self.assertTrue(manager.is_current_revision(7, 5))
        self.assertFalse(manager.is_current_revision(7, 4))
        self.assertFalse(manager.is_current_revision(7, True))
        self.assertFalse(manager.is_current_revision(7, None))

        await manager.leave(7, websocket)
        self.assertIsNone(manager.get_content_revision(7))

    async def test_broadcast_can_exclude_origin_connection(self) -> None:
        manager = RoomManager()
        origin = _FakeWebSocket()
        peer = _FakeWebSocket()
        await manager.join(9, origin, {'id': 1})
        await manager.join(9, peer, {'id': 2})

        await manager.broadcast(9, {'type': 'content_revision_changed'}, exclude=origin)

        self.assertEqual(origin.messages, [])
        self.assertEqual(peer.messages, [{'type': 'content_revision_changed'}])

    async def test_slow_connection_does_not_block_other_local_collaborators(self) -> None:
        manager = RoomManager()
        manager._send_timeout_seconds = 0.02
        slow = _SlowWebSocket()
        fast = _FakeWebSocket()
        await manager.join(29, slow, {'id': 1})
        await manager.join(29, fast, {'id': 2})

        started_at = asyncio.get_running_loop().time()
        await manager.broadcast(29, {'type': 'update', 'sequence': 1})
        elapsed = asyncio.get_running_loop().time() - started_at

        self.assertEqual(fast.messages, [{'type': 'update', 'sequence': 1}])
        self.assertLess(elapsed, 0.2)
        self.assertEqual(slow.close_codes, [1013])

    async def test_same_connection_messages_are_serialized_in_submission_order(self) -> None:
        manager = RoomManager()
        websocket = _SerialWebSocket()
        await manager.join(30, websocket, {'id': 1})

        first = asyncio.create_task(manager.send_to(websocket, {'sequence': 1}))
        await websocket.first_send_started.wait()
        second = asyncio.create_task(manager.send_to(websocket, {'sequence': 2}))
        await asyncio.sleep(0)

        self.assertEqual(websocket.max_active_sends, 1)
        self.assertEqual(websocket.messages, [])
        websocket.release_first_send.set()
        self.assertEqual(await asyncio.gather(first, second), [True, True])
        self.assertEqual(websocket.messages, [{'sequence': 1}, {'sequence': 2}])
        self.assertEqual(websocket.max_active_sends, 1)

    async def test_stuck_close_is_detached_before_later_broadcasts(self) -> None:
        manager = RoomManager()
        manager._send_timeout_seconds = 0.01
        stuck = _StuckWebSocket()
        fast = _FakeWebSocket()
        await manager.join(31, stuck, {'id': 1})
        await manager.join(31, fast, {'id': 2})
        manager.set_content_revision(31, 7)

        await manager.broadcast(31, {'type': 'update', 'sequence': 1})

        self.assertTrue(stuck.close_started.is_set())
        self.assertFalse(manager.is_connection_active(stuck))
        self.assertTrue(manager.is_connection_active(fast))
        self.assertEqual(await manager.get_room_users(31), [{'id': 2}])
        self.assertEqual(manager.get_content_revision(31), 7)

        started_at = asyncio.get_running_loop().time()
        await manager.broadcast(31, {'type': 'update', 'sequence': 2})
        elapsed = asyncio.get_running_loop().time() - started_at

        self.assertEqual(stuck.send_attempts, 1)
        self.assertEqual(
            fast.messages,
            [
                {'type': 'update', 'sequence': 1},
                {'type': 'update', 'sequence': 2},
            ],
        )
        self.assertLess(elapsed, 0.05)

    async def test_update_state_is_only_removed_for_patch_capable_connections(self) -> None:
        manager = RoomManager()
        modern = _FakeWebSocket()
        legacy = _FakeWebSocket()
        await manager.join(
            10,
            modern,
            {'id': 1},
            {STRUCTURED_NODE_PATCH_CAPABILITY},
        )
        await manager.join(10, legacy, {'id': 2})
        message = {
            'type': 'update',
            'update': 'incremental',
            'state': 'full-state',
            'patch': {'schemaVersion': 1, 'nodes': [], 'deletedNodeUids': []},
        }

        await manager.broadcast(10, message)

        self.assertIsNone(modern.messages[0]['state'])
        self.assertEqual(legacy.messages[0]['state'], 'full-state')
        self.assertEqual(message['state'], 'full-state')

    async def test_checkpoint_is_only_forwarded_as_full_update_to_legacy_connections(self) -> None:
        manager = RoomManager()
        modern = _FakeWebSocket()
        patch_only = _FakeWebSocket()
        legacy = _FakeWebSocket()
        await manager.join(
            11,
            modern,
            {'id': 1},
            {STRUCTURED_NODE_PATCH_CAPABILITY, YJS_CHECKPOINT_CAPABILITY},
        )
        await manager.join(
            11,
            patch_only,
            {'id': 2},
            {STRUCTURED_NODE_PATCH_CAPABILITY},
        )
        await manager.join(11, legacy, {'id': 3})

        await manager.broadcast_checkpoint(11, 'full-state', '7', 4)

        self.assertEqual(modern.messages, [])
        expected = {
            'type': 'update',
            'update': 'full-state',
            'state': 'full-state',
            'patch': None,
            'contentRevision': 4,
            'origin': '7',
        }
        self.assertEqual(patch_only.messages, [expected])
        self.assertEqual(legacy.messages, [expected])

    async def test_cross_instance_broadcast_works_without_local_room_on_publisher(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='publisher')
        receiver = RoomManager(instance_id='receiver')
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        peer = _FakeWebSocket()
        await receiver.join(12, peer, {'id': 2, 'name': 'B'})
        receiver.set_content_revision(12, 4)
        try:
            await publisher.broadcast(12, {'type': 'content_revision_changed', 'contentRevision': 6})
            await self._wait_until(lambda: len(peer.messages) == 1)

            self.assertEqual(peer.messages[0]['contentRevision'], 6)
            self.assertEqual(receiver.get_content_revision(12), 6)
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_cross_instance_checkpoint_uses_standard_update_and_skips_modern_peer(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='checkpoint-publisher')
        receiver = RoomManager(instance_id='checkpoint-receiver')
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        modern = _FakeWebSocket()
        legacy = _FakeWebSocket()
        await receiver.join(
            13,
            modern,
            {'id': 1},
            {STRUCTURED_NODE_PATCH_CAPABILITY, YJS_CHECKPOINT_CAPABILITY},
        )
        await receiver.join(13, legacy, {'id': 2})
        try:
            await publisher.broadcast_checkpoint(13, 'cross-worker-state', '8', 5)
            await self._wait_until(lambda: len(legacy.messages) == 1)

            self.assertEqual(modern.messages, [])
            self.assertEqual(legacy.messages, [{
                'type': 'update',
                'update': 'cross-worker-state',
                'state': 'cross-worker-state',
                'patch': None,
                'contentRevision': 5,
                'origin': '8',
            }])
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_origin_instance_does_not_deliver_pubsub_event_twice(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='origin')
        await manager.start(_FakeRedis(broker))
        origin = _FakeWebSocket()
        peer = _FakeWebSocket()
        await manager.join(15, origin, {'id': 1})
        await manager.join(15, peer, {'id': 2})
        try:
            update_message = {'type': 'update', 'update': 'dXBkYXRl'}
            await manager.broadcast(15, update_message, exclude=origin)
            await asyncio.sleep(0)

            self.assertEqual(origin.messages, [])
            self.assertEqual(peer.messages, [update_message])
        finally:
            await manager.stop()

    async def test_document_deleted_broadcast_closes_local_room(self) -> None:
        manager = RoomManager()
        peer = _FakeWebSocket()
        await manager.join(17, peer, {'id': 2})
        manager.set_content_revision(17, 5)

        await manager.broadcast_and_close_room(17, {
            'type': 'document_deleted',
            'mindmapId': 17,
        })

        self.assertEqual(peer.messages, [{'type': 'document_deleted', 'mindmapId': 17}])
        self.assertEqual(peer.close_codes, [4004])
        self.assertIsNone(manager.get_content_revision(17))
        self.assertEqual(await manager.get_room_users(17), [])
        self.assertFalse(manager.consume_disconnect_persistence_permission(peer))
        self.assertTrue(manager.consume_disconnect_persistence_permission(peer))

    async def test_remote_document_deleted_event_closes_receiver_room(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='delete-publisher')
        receiver = RoomManager(instance_id='delete-receiver')
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        peer = _FakeWebSocket()
        await receiver.join(19, peer, {'id': 2})
        try:
            await publisher.broadcast_and_close_room(19, {
                'type': 'document_deleted',
                'mindmapId': 19,
            })
            await self._wait_until(lambda: peer.close_codes == [4004])

            self.assertEqual(peer.messages, [{'type': 'document_deleted', 'mindmapId': 19}])
            self.assertIsNone(receiver.get_content_revision(19))
            self.assertEqual(await receiver.get_room_users(19), [])
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_remote_document_archived_event_closes_receiver_room(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='archive-publisher')
        receiver = RoomManager(instance_id='archive-receiver')
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        peer = _FakeWebSocket()
        await receiver.join(25, peer, {'id': 2})
        receiver.set_content_revision(25, 7)
        try:
            await publisher.broadcast_and_close_room(25, {
                'type': 'document_archived',
                'mindmapId': 25,
            }, close_code=4005)
            await self._wait_until(lambda: peer.close_codes == [4005])

            self.assertEqual(peer.messages, [{'type': 'document_archived', 'mindmapId': 25}])
            self.assertIsNone(receiver.get_content_revision(25))
            self.assertEqual(await receiver.get_room_users(25), [])
            self.assertFalse(receiver.consume_disconnect_persistence_permission(peer))
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_access_revoked_disconnects_only_target_user_across_instances(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='permission-publisher')
        receiver = RoomManager(instance_id='permission-receiver')
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        target_first = _FakeWebSocket()
        target_second = _FakeWebSocket()
        other_user = _FakeWebSocket()
        await receiver.join(20, target_first, {'id': 7, 'name': 'Target'})
        await receiver.join(20, target_second, {'id': 7, 'name': 'Target'})
        await receiver.join(20, other_user, {'id': 8, 'name': 'Other'})
        receiver.set_content_revision(20, 6)
        try:
            await publisher.notify_and_disconnect_user(20, 7, {
                'type': 'access_revoked',
                'mindmapId': 20,
                'message': '权限已撤销',
            })
            await self._wait_until(lambda: target_first.close_codes == [4003])

            for target in (target_first, target_second):
                self.assertEqual(target.messages[0]['type'], 'access_revoked')
                self.assertEqual(target.messages[0]['targetUserId'], 7)
                self.assertEqual(target.close_codes, [4003])
            self.assertEqual(other_user.messages, [])
            self.assertEqual(other_user.close_codes, [])
            self.assertFalse(receiver.consume_disconnect_persistence_permission(target_first))
            self.assertTrue(receiver.consume_disconnect_persistence_permission(other_user))
            self.assertEqual(receiver.get_content_revision(20), 6)
            self.assertEqual(await receiver.get_room_users(20), [{'id': 8, 'name': 'Other'}])
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_duplicate_remote_event_is_delivered_once(self) -> None:
        manager = RoomManager(instance_id='receiver')
        peer = _FakeWebSocket()
        await manager.join(16, peer, {'id': 2})
        payload = manager._encode_redis_envelope({
            'schemaVersion': 2,
            'eventId': 'same-event',
            'sourceInstanceId': 'remote',
            'issuedAtMs': manager._utc_now_ms(),
            'mindmapId': 16,
            'message': {'type': 'content_revision_changed', 'contentRevision': 2},
        })

        await manager._handle_redis_event(payload)
        await manager._handle_redis_event(payload)

        self.assertEqual(peer.messages, [{
            'type': 'content_revision_changed',
            'contentRevision': 2,
        }])

    async def test_invalid_remote_events_cannot_broadcast_or_close_rooms(self) -> None:
        manager = RoomManager(instance_id='receiver')
        manager._max_redis_event_bytes = 5000
        wrong_key_manager = RoomManager(
            instance_id='wrong-key',
            event_signing_secret='different-test-secret',
        )
        peer = _FakeWebSocket()
        await manager.join(26, peer, {'id': 2})
        now_ms = manager._utc_now_ms()

        def envelope(event_id: str, message: dict, **overrides: Any) -> bytes:
            return manager._encode_redis_envelope({
                'schemaVersion': 2,
                'eventId': event_id,
                'sourceInstanceId': 'remote',
                'issuedAtMs': now_ms,
                'mindmapId': 26,
                'message': message,
                **overrides,
            })

        tampered = envelope(
            'tampered',
            {'type': 'document_deleted', 'mindmapId': 26},
        ).replace(b'"mindmapId":26', b'"mindmapId":27', 1)
        payloads = [
            envelope('unknown', {'type': 'future_internal_event'}),
            envelope(
                'wrong-resource',
                {'type': 'document_deleted', 'mindmapId': 999},
            ),
            envelope(
                'missing-target',
                {'type': 'access_revoked', 'mindmapId': 26},
            ),
            envelope(
                'wrong-schema',
                {'type': 'document_archived', 'mindmapId': 26},
                schemaVersion=1,
            ),
            envelope(
                'stale-event',
                {'type': 'document_deleted', 'mindmapId': 26},
                issuedAtMs=now_ms - REDIS_EVENT_MAX_AGE_MS - 1,
            ),
            envelope(
                'future-event',
                {'type': 'document_archived', 'mindmapId': 26},
                issuedAtMs=now_ms + REDIS_EVENT_MAX_FUTURE_SKEW_MS + 1000,
            ),
            manager._encode_redis_envelope({
                'schemaVersion': 2,
                'eventId': 'missing-issued-at',
                'sourceInstanceId': 'remote',
                'mindmapId': 26,
                'message': {'type': 'document_deleted', 'mindmapId': 26},
            }),
            wrong_key_manager._encode_redis_envelope({
                'schemaVersion': 2,
                'eventId': 'wrong-key',
                'sourceInstanceId': 'remote',
                'issuedAtMs': now_ms,
                'mindmapId': 26,
                'message': {'type': 'document_deleted', 'mindmapId': 26},
            }),
            tampered,
            json.dumps({
                'schemaVersion': 2,
                'eventId': 'unsigned',
                'sourceInstanceId': 'remote',
                'mindmapId': 26,
                'message': {'type': 'document_deleted', 'mindmapId': 26},
            }).encode(),
            manager._append_redis_event_signature((
                '{"eventId":"deep","message":{"nested":'
                + '[' * 1100
                + '0'
                + ']' * 1100
                + ',"type":"awareness"},"mindmapId":26,'
                '"schemaVersion":2,"sourceInstanceId":"remote"}'
            ).encode()),
            b'x' * 5001,
        ]
        for payload in payloads:
            await manager._handle_redis_event(payload)

        self.assertEqual(peer.messages, [])
        self.assertEqual(peer.close_codes, [])
        self.assertTrue(manager.is_connection_active(peer))

    async def test_invalid_or_oversized_local_event_is_not_published(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='bounded-publisher')
        receiver = RoomManager(instance_id='bounded-receiver')
        publisher._max_redis_event_bytes = 300
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        peer = _FakeWebSocket()
        await receiver.join(27, peer, {'id': 2})
        try:
            await publisher.broadcast(27, {'type': 'future_internal_event'})
            await publisher.broadcast(27, {
                'type': 'awareness',
                'nodeUids': [],
                'padding': 'x' * 300,
            })
            await asyncio.sleep(0)
            self.assertEqual(peer.messages, [])

            await publisher.broadcast(27, {
                'type': 'awareness',
                'user': {'id': 1},
                'nodeUids': [],
            })
            await self._wait_until(lambda: len(peer.messages) == 1)
            self.assertEqual(peer.messages[0]['type'], 'awareness')
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_distributed_presence_is_merged_deduplicated_and_removed(self) -> None:
        broker = _FakeRedisBroker()
        first = RoomManager(instance_id='first')
        second = RoomManager(instance_id='second')
        await first.start(_FakeRedis(broker))
        await second.start(_FakeRedis(broker))
        first_socket = _FakeWebSocket()
        duplicate_socket = _FakeWebSocket()
        second_socket = _FakeWebSocket()
        await first.join(18, first_socket, {'id': 1, 'name': 'A'})
        await first.join(18, duplicate_socket, {'id': 1, 'name': 'A'})
        await second.join(18, second_socket, {'id': 2, 'name': 'B'})
        try:
            users = await second.get_room_users(18)
            self.assertEqual({user['id'] for user in users}, {1, 2})

            await first.leave(18, first_socket)
            await first.leave(18, duplicate_socket)
            users = await second.get_room_users(18)
            self.assertEqual(users, [{'id': 2, 'name': 'B'}])
        finally:
            await first.stop()
            await second.stop()

    async def test_expired_presence_is_not_returned(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='presence')
        await manager.start(_FakeRedis(broker))
        websocket = _FakeWebSocket()
        await manager.join(21, websocket, {'id': 7, 'name': 'Expired'})
        key = manager._presence_key(21)
        for member in broker.sorted_sets[key]:
            broker.sorted_sets[key][member] = time.time() - 1
        try:
            # Redis 是分布式在线状态的权威来源；过期后退回本地连接仅用于降级。
            self.assertEqual(await manager.get_room_users(21), [{'id': 7, 'name': 'Expired'}])
            self.assertEqual(broker.sorted_sets[key], {})
        finally:
            await manager.stop()

    async def test_publish_failure_keeps_local_broadcast_available(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='fallback')
        await manager.start(_FakeRedis(broker, fail_publish=True))
        peer = _FakeWebSocket()
        await manager.join(24, peer, {'id': 1})
        try:
            await manager.broadcast(24, {'type': 'awareness'})
            self.assertEqual(peer.messages, [{'type': 'awareness'}])
        finally:
            await manager.stop()

    async def _wait_until(self, predicate: Callable[[], bool], timeout: float = 1) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                self.fail('等待跨实例事件超时')
            await asyncio.sleep(0.01)


if __name__ == '__main__':
    unittest.main()
