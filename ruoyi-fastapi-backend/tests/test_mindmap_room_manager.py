"""脑图协作房间 revision 与广播行为测试。"""
import asyncio
import json
import time
import unittest
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from module_mindmap.service.mindmap_metrics import mindmap_metrics
from module_mindmap.websocket.room_manager import (
    CONDITIONAL_NODE_PATCH_CAPABILITY,
    CROSS_NODE_CRDT_V2_CAPABILITY,
    NODE_EDIT_LEASE_CAPABILITY,
    REDIS_EVENT_MAX_AGE_MS,
    REDIS_EVENT_MAX_FUTURE_SKEW_MS,
    STRUCTURED_NODE_PATCH_CAPABILITY,
    YJS_CHECKPOINT_CAPABILITY,
    YJS_LINEAGE_CAPABILITY,
    YJS_MUTATION_SEQUENCE_CAPABILITY,
    RoomManager,
)

OFFICIAL_WRITE_CAPABILITIES = {
    CROSS_NODE_CRDT_V2_CAPABILITY,
    NODE_EDIT_LEASE_CAPABILITY,
    YJS_LINEAGE_CAPABILITY,
}


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
        self.seed_lease_renewals: list[tuple[str, str, int]] = []
        self.lineage_gap_clock_ms = 0
        self.lineage_gap_observations: dict[str, tuple[str, int]] = {}


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

    async def get(self, key: str) -> str | None:
        return self.broker.strings.get(key)

    async def eval(  # noqa: PLR0911, PLR0912
        self,
        script: str,
        numkeys: int,
        *keys_and_args: Any,
    ) -> int:
        keys = keys_and_args[:numkeys]
        args = keys_and_args[numkeys:]
        key = keys[0]
        if "redis.call('set', KEYS[2]" in script:
            expected_epoch, owner, ttl_seconds = args
            raw_fence = self.broker.strings.get(key)
            fence = json.loads(raw_fence) if raw_fence is not None else None
            if (
                not isinstance(fence, dict)
                or fence.get('version') != 1
                or fence.get('status') != 'active'
                or fence.get('epoch') != expected_epoch
            ):
                return -1
            lease_key = keys[1]
            current = self.broker.strings.get(lease_key)
            if current is not None and current != owner:
                return 0
            self.broker.strings[lease_key] = owner
            if current == owner:
                self.broker.seed_lease_renewals.append((
                    lease_key,
                    owner,
                    ttl_seconds,
                ))
            return 1
        if "redis.call('get', KEYS[2]) ~= ARGV[2]" in script:
            expected_epoch, owner, *ttl_values = args
            raw_fence = self.broker.strings.get(key)
            fence = json.loads(raw_fence) if raw_fence is not None else None
            valid = (
                isinstance(fence, dict)
                and fence.get('version') == 1
                and fence.get('status') == 'active'
                and fence.get('epoch') == expected_epoch
                and self.broker.strings.get(keys[1]) == owner
            )
            if valid and ttl_values:
                self.broker.seed_lease_renewals.append((
                    keys[1],
                    owner,
                    ttl_values[0],
                ))
            return int(valid)
        if "redis.call('publish'" in script:
            expected, channel, payload = args
            if self.broker.strings.get(key) != expected:
                return -1
            return await self.publish(channel, payload)
        if "redis.call('pttl'" in script:
            expected_epoch, grace_ms, _marker_ttl_ms = args
            observed = self.broker.lineage_gap_observations.get(key)
            if observed is None or observed[0] != expected_epoch:
                self.broker.lineage_gap_observations[key] = (
                    expected_epoch,
                    self.broker.lineage_gap_clock_ms,
                )
                return 0
            return int(
                self.broker.lineage_gap_clock_ms - observed[1] >= grace_ms
            )
        if "ARGV[3]" in script:
            expected, expect_missing, replacement = args
            current = self.broker.strings.get(key)
            if (
                (expect_missing == '1' and current is not None)
                or (expect_missing != '1' and current != expected)
            ):
                return 0
            self.broker.strings[key] = replacement
            return 1
        owner = args[0]
        ttl_seconds = args[1] if len(args) > 1 else None
        if self.broker.strings.get(key) != owner:
            return 0
        if ttl_seconds is not None:
            self.broker.seed_lease_renewals.append((key, owner, ttl_seconds))
            return 1
        del self.broker.strings[key]
        return 1

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


class _FenceRaceRedis(_FakeRedis):
    def __init__(self, broker: _FakeRedisBroker) -> None:
        super().__init__(broker)
        self.next_node_fence: str | None = None

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> int:
        if self.next_node_fence is not None and "KEYS[2]" in script:
            fence_key = keys_and_args[0]
            self.broker.strings[fence_key] = self.next_node_fence
            self.next_node_fence = None
        return await super().eval(script, numkeys, *keys_and_args)


class _PostRenewFenceRaceRedis(_FakeRedis):
    def __init__(self, broker: _FakeRedisBroker) -> None:
        super().__init__(broker)
        self.renew_succeeded = asyncio.Event()
        self.release_renew_result = asyncio.Event()

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> int:
        result = await super().eval(script, numkeys, *keys_and_args)
        if "redis.call('get', KEYS[2]) ~= ARGV[2]" in script and result == 1:
            self.renew_succeeded.set()
            await self.release_renew_result.wait()
        return result


class _FakeControlEventResult:
    def __init__(self, row: object | None) -> None:
        self.row = row

    def one_or_none(self) -> object | None:
        return self.row


class _FakeControlEventSession:
    def __init__(self, row: object | None) -> None:
        self.row = row
        self.entered = False

    async def __aenter__(self) -> '_FakeControlEventSession':
        self.entered = True
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.entered = False

    async def execute(self, _statement: object) -> _FakeControlEventResult:
        return _FakeControlEventResult(self.row)


class _FakeControlEventSessionFactory:
    def __init__(self, row: object | None) -> None:
        self.session = _FakeControlEventSession(row)

    def __call__(self) -> _FakeControlEventSession:
        return self.session


def _remote_event(
    manager: RoomManager,
    mindmap_id: int,
    event_id: str,
    message: dict,
) -> bytes:
    return manager._encode_redis_envelope({
        'schemaVersion': 2,
        'eventId': event_id,
        'sourceInstanceId': 'remote',
        'issuedAtMs': manager._utc_now_ms(),
        'mindmapId': mindmap_id,
        'message': message,
    })


def _establish_lineage(
    manager: RoomManager,
    mindmap_id: int,
    revision: int,
    lineage_id: str,
    broker: _FakeRedisBroker | None = None,
) -> str:
    if not manager.set_content_lineage(mindmap_id, revision, lineage_id):
        raise AssertionError('failed to establish local test lineage')
    if broker is None:
        return manager._local_lineage_epochs[mindmap_id]
    raw = manager._encode_lineage_fence(
        revision,
        manager._lineage_digest(lineage_id),
    )
    broker.strings[manager._lineage_fence_key(mindmap_id)] = raw
    record = manager._decode_lineage_fence_record(raw)
    if record is None:
        raise AssertionError('failed to encode test lineage fence')
    return record[3]


class MindmapRoomManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_plain_room_restricts_legacy_writer_to_readonly(self) -> None:
        manager = RoomManager()
        legacy = _FakeWebSocket()

        can_edit = await manager.join(40, legacy, {'id': 1}, can_edit=True)

        self.assertFalse(can_edit)
        self.assertEqual(
            await manager.get_required_write_capabilities(40),
            OFFICIAL_WRITE_CAPABILITIES,
        )
        self.assertFalse(manager.is_connection_write_enabled(40, legacy))

    async def test_v2_activation_retires_old_writer_but_preserves_readonly_viewer(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='v2-local-gate')
        await manager.start(_FakeRedis(broker))
        legacy_writer = _FakeWebSocket()
        legacy_viewer = _FakeWebSocket()
        try:
            self.assertFalse(await manager.join(
                41, legacy_writer, {'id': 1}, can_edit=True,
            ))
            self.assertFalse(await manager.join(
                41, legacy_viewer, {'id': 2}, can_edit=False,
            ))

            self.assertTrue(manager.is_connection_active(legacy_writer))
            self.assertEqual(legacy_writer.close_codes, [])
            self.assertTrue(manager.is_connection_active(legacy_viewer))
            self.assertEqual(legacy_viewer.close_codes, [])

            v2_writer = _FakeWebSocket()
            self.assertTrue(await manager.join(
                41,
                v2_writer,
                {'id': 3},
                OFFICIAL_WRITE_CAPABILITIES,
                can_edit=True,
            ))
            late_legacy = _FakeWebSocket()
            self.assertFalse(await manager.join(
                41, late_legacy, {'id': 4}, can_edit=True,
            ))
            self.assertTrue(manager.is_connection_active(late_legacy))
            self.assertFalse(manager.is_connection_write_enabled(41, late_legacy))
        finally:
            await manager.stop()

    async def test_static_protocol_is_required_on_every_worker(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='v2-gate-publisher')
        receiver = RoomManager(instance_id='v2-gate-receiver')
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        legacy_writer = _FakeWebSocket()
        legacy_viewer = _FakeWebSocket()
        await receiver.join(42, legacy_writer, {'id': 1}, can_edit=True)
        await receiver.join(42, legacy_viewer, {'id': 2}, can_edit=False)
        try:
            self.assertTrue(receiver.is_connection_active(legacy_writer))
            self.assertFalse(receiver.is_connection_write_enabled(42, legacy_writer))
            self.assertTrue(receiver.is_connection_active(legacy_viewer))
            self.assertEqual(
                await receiver.get_required_write_capabilities(42),
                OFFICIAL_WRITE_CAPABILITIES,
            )
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_v2_write_gate_is_loaded_by_a_later_worker_before_join(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='v2-gate-existing-worker')
        later_worker = RoomManager(instance_id='v2-gate-later-worker')
        await publisher.start(_FakeRedis(broker))
        try:
            self.assertTrue(await publisher.require_write_capability(
                43, CROSS_NODE_CRDT_V2_CAPABILITY,
            ))
            await later_worker.start(_FakeRedis(broker))
            self.assertEqual(
                await later_worker.get_required_write_capabilities(43),
                OFFICIAL_WRITE_CAPABILITIES,
            )

            legacy_writer = _FakeWebSocket()
            self.assertFalse(await later_worker.join(
                43, legacy_writer, {'id': 1}, can_edit=True,
            ))
            self.assertTrue(later_worker.is_connection_active(legacy_writer))
            self.assertFalse(
                later_worker.is_connection_write_enabled(43, legacy_writer),
            )
        finally:
            await publisher.stop()
            await later_worker.stop()

    async def test_configured_redis_write_gate_lookup_fails_closed_without_sticking(self) -> None:
        class _UnavailableRedis(_FakeRedis):
            async def get(self, _key: str) -> str | None:
                raise ConnectionError('redis unavailable')

        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='v2-gate-unavailable')
        manager._redis = _UnavailableRedis(broker)

        with patch(
            'module_mindmap.websocket.room_manager.AppConfig.app_workers',
            1,
        ):
            self.assertEqual(
                await manager.get_required_write_capabilities(44),
                OFFICIAL_WRITE_CAPABILITIES,
            )
        self.assertNotIn(44, manager._required_write_capabilities)

        manager._redis = _FakeRedis(broker)
        self.assertEqual(
            await manager.get_required_write_capabilities(44),
            OFFICIAL_WRITE_CAPABILITIES,
        )

    async def test_configured_redis_failure_cannot_activate_a_local_only_write_gate(
        self,
    ) -> None:
        class _UnavailableRedis(_FakeRedis):
            async def set(self, *args: Any, **kwargs: Any) -> bool | None:
                raise ConnectionError('redis unavailable')

        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='write-gate-redis-failure')
        manager._redis = _UnavailableRedis(broker)

        with patch(
            'module_mindmap.websocket.room_manager.AppConfig.app_workers',
            1,
        ):
            self.assertFalse(await manager.require_write_capability(
                45,
                NODE_EDIT_LEASE_CAPABILITY,
            ))

        self.assertNotIn(45, manager._required_write_capabilities)

    async def test_stop_clears_all_runtime_room_state_before_restart(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='restart-cleanup')
        stale_socket = _FakeWebSocket()
        await manager.start(_FakeRedis(broker))
        await manager.join(
            5,
            stale_socket,
            {'id': 1, 'name': 'old-session'},
            {YJS_CHECKPOINT_CAPABILITY},
        )
        manager.set_content_revision(5, 7)
        self.assertTrue(manager.set_content_lineage(5, 7, 'old-lineage'))
        manager._remember_event('old-event')

        await manager.stop()

        self.assertEqual(await manager.get_runtime_snapshot(), {
            'activeRooms': 0,
            'activeConnections': 0,
            'retiringConnections': 0,
            'redisTransportState': 'stopped',
        })
        self.assertEqual(manager._rooms, {})
        self.assertEqual(manager._user_info, {})
        self.assertIsNone(manager.get_content_revision(5))
        self.assertEqual(manager._content_lineages, {})
        self.assertEqual(manager._seen_event_ids, set())

        fresh_socket = _FakeWebSocket()
        await manager.start(_FakeRedis(broker))
        try:
            await manager.join(5, fresh_socket, {'id': 2, 'name': 'new-session'})
            manager.set_content_revision(5, 1)
            self.assertEqual(manager.get_content_revision(5), 1)
            self.assertTrue(manager.set_content_lineage(5, 1, 'fresh-lineage'))
            await manager.broadcast(5, {'type': 'room_users', 'users': []})
            self.assertEqual(stale_socket.messages, [])
            self.assertEqual(fresh_socket.messages, [{'type': 'room_users', 'users': []}])
        finally:
            await manager.leave(5, fresh_socket)
            await manager.stop()

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
        self.assertTrue(await manager.owns_seed_lease(5, 3, first))
        self.assertFalse(await manager.owns_seed_lease(5, 3, second))
        self.assertTrue(await manager.consume_seed_lease(5, 3, first))
        self.assertFalse(await manager.consume_seed_lease(5, 3, first))

    async def test_only_one_local_connection_can_edit_same_node(self) -> None:
        manager = RoomManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        capabilities = OFFICIAL_WRITE_CAPABILITIES
        await manager.join(5, first, {'id': 1}, capabilities)
        await manager.join(5, second, {'id': 2}, capabilities)
        manager.set_content_revision(5, 3)
        _establish_lineage(manager, 5, 3, 'local-lineage')

        results = await asyncio.gather(
            manager.acquire_node_edit_lease(5, 3, 'same-node', first),
            manager.acquire_node_edit_lease(5, 3, 'same-node', second),
        )

        self.assertEqual(sum(results), 1)
        winner, loser = (first, second) if results[0] else (second, first)
        self.assertTrue(await manager.acquire_node_edit_lease(5, 3, 'same-node', winner))
        self.assertFalse(await manager.acquire_node_edit_lease(5, 3, 'same-node', loser))
        self.assertTrue(await manager.owns_node_edit_lease(5, 'same-node', winner))
        self.assertFalse(await manager.owns_node_edit_lease(5, 'same-node', loser))
        self.assertTrue(await manager.release_node_edit_lease(5, 'same-node', winner))
        self.assertTrue(await manager.acquire_node_edit_lease(5, 3, 'same-node', loser))

    async def test_node_edit_lease_expires_and_disconnect_releases_it(self) -> None:
        manager = RoomManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        capabilities = OFFICIAL_WRITE_CAPABILITIES
        await manager.join(5, first, {'id': 1}, capabilities)
        await manager.join(5, second, {'id': 2}, capabilities)
        manager.set_content_revision(5, 3)
        _establish_lineage(manager, 5, 3, 'expiring-lineage')
        clock = [100.0]
        with patch(
            'module_mindmap.websocket.room_manager.time.monotonic',
            side_effect=lambda: clock[0],
        ):
            self.assertTrue(
                await manager.acquire_node_edit_lease(5, 3, 'expiring-node', first),
            )
            clock[0] += manager._node_edit_lease_ttl_seconds + 1
            self.assertTrue(
                await manager.acquire_node_edit_lease(5, 3, 'expiring-node', second),
            )
        await manager.leave(5, second)
        self.assertTrue(
            await manager.acquire_node_edit_lease(5, 3, 'expiring-node', first),
        )

    async def test_node_edit_lease_is_unique_across_instances(self) -> None:
        broker = _FakeRedisBroker()
        first_manager = RoomManager(instance_id='node-edit-first')
        second_manager = RoomManager(instance_id='node-edit-second')
        await first_manager.start(_FakeRedis(broker))
        await second_manager.start(_FakeRedis(broker))
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        capabilities = OFFICIAL_WRITE_CAPABILITIES
        try:
            self.assertTrue(await first_manager.require_write_capability(
                6,
                NODE_EDIT_LEASE_CAPABILITY,
            ))
            await first_manager.join(6, first, {'id': 1}, capabilities)
            await second_manager.join(6, second, {'id': 2}, capabilities)
            first_manager.set_content_revision(6, 4)
            second_manager.set_content_revision(6, 4)
            lineage_epoch = _establish_lineage(
                first_manager,
                6,
                4,
                'shared-lineage',
                broker,
            )
            self.assertTrue(second_manager.set_content_lineage(
                6,
                4,
                'shared-lineage',
            ))
            results = await asyncio.gather(
                first_manager.acquire_node_edit_lease(6, 4, 'shared-node', first),
                second_manager.acquire_node_edit_lease(6, 4, 'shared-node', second),
            )
            self.assertEqual(sum(results), 1)
            winner_manager, winner = (
                (first_manager, first) if results[0] else (second_manager, second)
            )
            loser_manager, loser = (
                (second_manager, second) if results[0] else (first_manager, first)
            )
            self.assertTrue(await winner_manager.acquire_node_edit_lease(
                6,
                4,
                'shared-node',
                winner,
            ))
            lease_key = winner_manager._node_edit_lease_key(
                6,
                lineage_epoch,
                'shared-node',
            )
            self.assertEqual(
                broker.seed_lease_renewals[-1],
                (
                    lease_key,
                    broker.strings[lease_key],
                    winner_manager._node_edit_lease_ttl_seconds,
                ),
            )
            await winner_manager.leave(6, winner)
            self.assertTrue(await loser_manager.acquire_node_edit_lease(
                6,
                4,
                'shared-node',
                loser,
            ))
        finally:
            await first_manager.stop()
            await second_manager.stop()

    async def test_node_edit_lease_survives_contiguous_revision_advance(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='node-edit-revision')
        manager._redis = _FakeRedis(broker)
        old_editor = _FakeWebSocket()
        new_editor = _FakeWebSocket()
        await manager.join(
            50,
            old_editor,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        await manager.join(
            50,
            new_editor,
            {'id': 2},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(50, 4)
        lineage_epoch = _establish_lineage(
            manager,
            50,
            4,
            'stable-lineage',
            broker,
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            50,
            4,
            'same-node',
            old_editor,
        ))
        lease_key = manager._node_edit_lease_key(
            50,
            lineage_epoch,
            'same-node',
        )

        self.assertTrue(await manager.advance_content_revision_fence(
            50,
            5,
            'content_revision_changed',
        ))
        advanced_record = manager._decode_lineage_fence_record(
            broker.strings[manager._lineage_fence_key(50)],
        )

        self.assertIsNotNone(advanced_record)
        self.assertEqual(advanced_record[3], lineage_epoch)
        self.assertTrue(await manager.owns_node_edit_lease(
            50,
            'same-node',
            old_editor,
        ))
        self.assertFalse(await manager.acquire_node_edit_lease(
            50,
            5,
            'same-node',
            new_editor,
        ))
        self.assertTrue(await manager.acquire_node_edit_lease(
            50,
            5,
            'same-node',
            old_editor,
        ))
        self.assertTrue(await manager.renew_node_edit_lease(
            50,
            'same-node',
            old_editor,
        ))
        self.assertIn(lease_key, broker.strings)

    async def test_local_node_edit_renewal_survives_prebroadcast_revision_gap(
        self,
    ) -> None:
        manager = RoomManager(instance_id='local-node-edit-renewal-gap')
        editor = _FakeWebSocket()
        await manager.join(
            58,
            editor,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(58, 4)
        old_epoch = _establish_lineage(
            manager,
            58,
            4,
            'stable-local-lineage',
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            58,
            4,
            'same-node',
            editor,
        ))

        # DB 权限重检先观察到连续 r5，正式广播尚未恢复 active lineage。
        manager.set_content_revision(58, 5)
        self.assertNotIn(58, manager._content_lineages)
        self.assertEqual(manager._pending_content_lineages[58][2], old_epoch)
        self.assertTrue(await manager.renew_node_edit_lease(
            58,
            'same-node',
            editor,
        ))

        # reset 不会留下 pending 连续世代，旧 owner 不能跨新 epoch 续租。
        manager.set_content_revision(
            58,
            5,
            transition_type='document_reset',
        )
        self.assertFalse(await manager.renew_node_edit_lease(
            58,
            'same-node',
            editor,
        ))

    async def test_local_node_edit_renewal_does_not_cross_reset_while_waiting_for_lock(
        self,
    ) -> None:
        manager = RoomManager(instance_id='local-node-edit-renewal-reset-race')
        editor = _FakeWebSocket()
        await manager.join(
            59,
            editor,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(59, 4)
        _establish_lineage(manager, 59, 4, 'old-local-lineage')
        self.assertTrue(await manager.acquire_node_edit_lease(
            59,
            4,
            'same-node',
            editor,
        ))

        await manager._lock.acquire()
        renewal = asyncio.create_task(manager.renew_node_edit_lease(
            59,
            'same-node',
            editor,
        ))
        await asyncio.sleep(0)
        manager.set_content_revision(
            59,
            5,
            transition_type='document_reset',
        )
        manager._lock.release()

        self.assertIsNone(await renewal)

    async def test_local_node_edit_renewal_rejects_connection_retiring_while_waiting_for_lock(
        self,
    ) -> None:
        manager = RoomManager(instance_id='local-node-edit-renewal-leave-race')
        editor = _FakeWebSocket()
        await manager.join(
            60,
            editor,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(60, 4)
        _establish_lineage(manager, 60, 4, 'leave-race-lineage')
        self.assertTrue(await manager.acquire_node_edit_lease(
            60,
            4,
            'same-node',
            editor,
        ))

        await manager._lock.acquire()
        renewal = asyncio.create_task(manager.renew_node_edit_lease(
            60,
            'same-node',
            editor,
        ))
        await asyncio.sleep(0)
        leaving = asyncio.create_task(manager.leave(60, editor))
        await asyncio.sleep(0)
        self.assertIn(id(editor), manager._retiring_connections)
        manager._lock.release()

        self.assertIsNone(await renewal)
        await leaving
        self.assertEqual(manager._local_node_edit_leases, {})

    async def test_local_node_edit_renewal_reads_expiry_after_lock_wait(
        self,
    ) -> None:
        manager = RoomManager(instance_id='local-node-edit-renewal-clock-race')
        editor = _FakeWebSocket()
        await manager.join(
            61,
            editor,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(61, 4)
        _establish_lineage(manager, 61, 4, 'clock-race-lineage')
        self.assertTrue(await manager.acquire_node_edit_lease(
            61,
            4,
            'same-node',
            editor,
        ))
        lease_key = next(iter(manager._local_node_edit_leases))
        websocket_id, owner, _deadline = manager._local_node_edit_leases[lease_key]
        manager._local_node_edit_leases[lease_key] = (
            websocket_id,
            owner,
            100.0,
        )

        clock = [99.0]
        await manager._lock.acquire()
        with patch(
            'module_mindmap.websocket.room_manager.time.monotonic',
            side_effect=lambda: clock[0],
        ):
            try:
                renewal = asyncio.create_task(manager.renew_node_edit_lease(
                    61,
                    'same-node',
                    editor,
                ))
                await asyncio.sleep(0)
                clock[0] = 101.0
            finally:
                manager._lock.release()
            self.assertFalse(await renewal)

        self.assertNotIn(lease_key, manager._local_node_edit_leases)

    async def test_reset_lineage_generation_does_not_reuse_old_node_lease(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='node-edit-reset')
        manager._redis = _FakeRedis(broker)
        old_editor = _FakeWebSocket()
        new_editor = _FakeWebSocket()
        for websocket, user_id in ((old_editor, 1), (new_editor, 2)):
            await manager.join(
                51,
                websocket,
                {'id': user_id},
                OFFICIAL_WRITE_CAPABILITIES,
            )
        manager.set_content_revision(51, 4)
        old_epoch = _establish_lineage(
            manager,
            51,
            4,
            'reused-lineage-id',
            broker,
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            51,
            4,
            'same-node',
            old_editor,
        ))
        old_key = manager._node_edit_lease_key(51, old_epoch, 'same-node')

        self.assertTrue(await manager.advance_content_revision_fence(
            51,
            5,
            'document_reset',
        ))
        repaired, _digest = await manager.repair_content_lineage_fence_from_persisted(
            51,
            5,
            manager._lineage_digest('reused-lineage-id'),
        )
        self.assertTrue(repaired)
        manager.set_content_lineage(51, 5, 'reused-lineage-id', replace=True)
        new_record = manager._decode_lineage_fence_record(
            broker.strings[manager._lineage_fence_key(51)],
        )
        self.assertIsNotNone(new_record)
        new_epoch = new_record[3]
        self.assertNotEqual(new_epoch, old_epoch)

        self.assertFalse(await manager.owns_node_edit_lease(
            51,
            'same-node',
            old_editor,
        ))
        self.assertTrue(await manager.acquire_node_edit_lease(
            51,
            5,
            'same-node',
            new_editor,
        ))
        new_key = manager._node_edit_lease_key(51, new_epoch, 'same-node')
        self.assertIn(old_key, broker.strings)
        self.assertIn(new_key, broker.strings)
        self.assertTrue(await manager.release_node_edit_lease(
            51,
            'same-node',
            old_editor,
        ))
        self.assertNotIn(old_key, broker.strings)
        self.assertIn(new_key, broker.strings)

    async def test_node_lease_lua_fences_epoch_not_contiguous_revision(self) -> None:
        broker = _FakeRedisBroker()
        redis = _FenceRaceRedis(broker)
        manager = RoomManager(instance_id='node-edit-fence-race')
        manager._redis = redis
        editor = _FakeWebSocket()
        await manager.join(
            52,
            editor,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(52, 4)
        lineage_id = 'race-lineage'
        lineage_digest = manager._lineage_digest(lineage_id)
        lineage_epoch = _establish_lineage(
            manager,
            52,
            4,
            lineage_id,
            broker,
        )

        # acquire 前置 GET 仍读到 r4；Lua 执行前 fence 已推进到 r5，
        # 但 epoch 未变，因此连续正文更新不能使原编辑世代失效。
        redis.next_node_fence = manager._encode_lineage_fence(
            5,
            lineage_digest,
            epoch=lineage_epoch,
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            52,
            4,
            'same-node',
            editor,
        ))

        manager.set_content_revision(
            52,
            5,
            transition_type='content_revision_changed',
        )
        redis.next_node_fence = manager._encode_lineage_fence(
            6,
            lineage_digest,
            epoch=lineage_epoch,
        )
        self.assertTrue(await manager.owns_node_edit_lease(
            52,
            'same-node',
            editor,
        ))

        # 同样的 GET→Lua 窗口若发生 reset/新 seed，epoch 必须改变，
        # 原租约的最终所有权校验随即失败。
        redis.next_node_fence = manager._encode_lineage_fence(
            7,
            lineage_digest,
        )
        self.assertFalse(await manager.owns_node_edit_lease(
            52,
            'same-node',
            editor,
        ))

    async def test_redis_node_edit_renewal_rechecks_epoch_after_lua_success(
        self,
    ) -> None:
        mindmap_id = 62
        broker = _FakeRedisBroker()
        redis = _PostRenewFenceRaceRedis(broker)
        manager = RoomManager(instance_id='node-edit-renew-post-reset-race')
        manager._redis = redis
        editor = _FakeWebSocket()
        await manager.join(
            mindmap_id,
            editor,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(mindmap_id, 4)
        lineage_id = 'renew-old-lineage'
        old_epoch = _establish_lineage(
            manager,
            mindmap_id,
            4,
            lineage_id,
            broker,
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            mindmap_id,
            4,
            'same-node',
            editor,
        ))
        old_key = manager._node_edit_lease_key(
            mindmap_id,
            old_epoch,
            'same-node',
        )

        renewal = asyncio.create_task(manager.renew_node_edit_lease(
            mindmap_id,
            'same-node',
            editor,
        ))
        await redis.renew_succeeded.wait()
        # 模拟另一 worker 在续租 Lua 成功后完成 reset；本 worker 尚未收到
        # pub/sub，因此本地连接和旧租约记录表面上仍完全有效。
        broker.strings[manager._lineage_fence_key(mindmap_id)] = (
            manager._encode_lineage_fence(
                5,
                manager._lineage_digest('renew-new-lineage'),
            )
        )
        redis.release_renew_result.set()

        self.assertIsNone(await renewal)
        self.assertNotIn(old_key, broker.strings)
        self.assertFalse(any(
            key[0] == mindmap_id and key[2] == 'same-node'
            for key in manager._local_node_edit_leases
        ))

    async def test_configured_redis_failure_never_falls_back_to_local_edit_lock(self) -> None:
        class _UnavailableRedis(_FakeRedis):
            async def eval(self, *args: Any, **kwargs: Any) -> int:
                raise ConnectionError('redis unavailable')

        manager = RoomManager(instance_id='node-edit-redis-failure')
        websocket = _FakeWebSocket()
        await manager.join(
            6,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(6, 4)
        broker = _FakeRedisBroker()
        _establish_lineage(manager, 6, 4, 'unavailable-lineage', broker)
        manager._redis = _UnavailableRedis(broker)

        with patch(
            'module_mindmap.websocket.room_manager.AppConfig.app_workers',
            1,
        ):
            self.assertIsNone(await manager.acquire_node_edit_lease(
                6,
                4,
                'fail-closed-node',
                websocket,
            ))
        self.assertEqual(manager._local_node_edit_leases, {})

    async def test_inflight_node_edit_acquire_is_released_during_retirement(
        self,
    ) -> None:
        class _DelayedAcquireRedis(_FakeRedis):
            def __init__(self, broker: _FakeRedisBroker) -> None:
                super().__init__(broker)
                self.set_started = asyncio.Event()
                self.release_set = asyncio.Event()

            async def eval(self, script: str, *args: Any) -> int:
                if "redis.call('set', KEYS[2]" in script:
                    self.set_started.set()
                    await self.release_set.wait()
                return await super().eval(script, *args)

        for teardown in ('leave', 'stop'):
            with self.subTest(teardown=teardown):
                broker = _FakeRedisBroker()
                redis = _DelayedAcquireRedis(broker)
                manager = RoomManager(instance_id=f'node-edit-{teardown}-race')
                manager._redis = redis
                websocket = _FakeWebSocket()
                await manager.join(
                    6,
                    websocket,
                    {'id': 1},
                    OFFICIAL_WRITE_CAPABILITIES,
                )
                manager.set_content_revision(6, 4)
                lineage_epoch = _establish_lineage(
                    manager,
                    6,
                    4,
                    'retiring-lineage',
                    broker,
                )
                acquire = asyncio.create_task(manager.acquire_node_edit_lease(
                    6,
                    4,
                    'retiring-node',
                    websocket,
                ))
                await redis.set_started.wait()

                if teardown == 'leave':
                    await manager.leave(6, websocket)
                else:
                    await manager.stop()
                redis.release_set.set()

                self.assertIsNone(await acquire)
                self.assertNotIn(
                    manager._node_edit_lease_key(
                        6,
                        lineage_epoch,
                        'retiring-node',
                    ),
                    broker.strings,
                )
                self.assertEqual(manager._local_node_edit_leases, {})

    async def test_revision_advance_discards_all_stale_local_seed_leases(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()
        await manager.join(5, websocket, {'id': 1})
        manager.set_content_revision(5, 3)
        self.assertTrue(await manager.acquire_seed_lease(5, 3, websocket))
        self.assertIn((5, 3), manager._local_seed_leases)

        manager.set_content_revision(5, 4)

        self.assertNotIn((5, 3), manager._local_seed_leases)
        self.assertFalse(await manager.owns_seed_lease(5, 3, websocket))

        # 收到迟到的旧 revision 通知不能清除当前 revision 的租约。
        self.assertTrue(await manager.acquire_seed_lease(5, 4, websocket))
        manager.set_content_revision(5, 3)
        self.assertIn((5, 4), manager._local_seed_leases)

    async def test_join_clears_reused_disconnect_persistence_marker(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()
        manager.block_disconnect_persistence(websocket)

        await manager.join(5, websocket, {'id': 1})

        self.assertTrue(manager.consume_disconnect_persistence_permission(websocket))

    async def test_local_seed_lease_is_released_when_its_connection_leaves(self) -> None:
        manager = RoomManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        await manager.join(5, first, {'id': 1})
        await manager.join(5, second, {'id': 2})
        self.assertTrue(await manager.acquire_seed_lease(5, 3, first))

        await manager.leave(5, first)

        self.assertFalse(await manager.owns_seed_lease(5, 3, first))
        self.assertTrue(await manager.acquire_seed_lease(5, 3, second))

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
            self.assertEqual(
                await first_manager.owns_seed_lease(6, 4, first),
                results[0],
            )
            self.assertEqual(
                await second_manager.owns_seed_lease(6, 4, second),
                results[1],
            )
        finally:
            await first_manager.stop()
            await second_manager.stop()

    async def test_redis_seed_deadline_starts_before_set_round_trip(self) -> None:
        broker = _FakeRedisBroker()
        clock = [100.0]

        class _DelayedRedis(_FakeRedis):
            async def set(self, *args: Any, **kwargs: Any) -> bool | None:
                clock[0] += 3
                return await super().set(*args, **kwargs)

        manager = RoomManager(instance_id='seed-deadline')
        websocket = _FakeWebSocket()
        await manager.join(6, websocket, {'id': 1})
        manager._redis = _DelayedRedis(broker)

        with patch(
            'module_mindmap.websocket.room_manager.time.monotonic',
            side_effect=lambda: clock[0],
        ):
            self.assertTrue(await manager.acquire_seed_lease(6, 4, websocket))

        self.assertEqual(manager._local_seed_leases[(6, 4)][1], 110.0)

    async def test_consume_seed_lease_rejects_replaced_redis_owner(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='seed-owner-check')
        websocket = _FakeWebSocket()
        await manager.join(6, websocket, {'id': 1})
        manager._redis = _FakeRedis(broker)
        self.assertTrue(await manager.acquire_seed_lease(6, 4, websocket))
        key = f'{manager._seed_key_prefix}6:4'
        broker.strings[key] = 'replacement-owner'

        self.assertFalse(await manager.consume_seed_lease(6, 4, websocket))
        self.assertNotIn((6, 4), manager._local_seed_leases)

    async def test_consume_seed_lease_rejects_expired_redis_owner(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='seed-expired-check')
        websocket = _FakeWebSocket()
        await manager.join(6, websocket, {'id': 1})
        manager._redis = _FakeRedis(broker)
        self.assertTrue(await manager.acquire_seed_lease(6, 4, websocket))
        key = f'{manager._seed_key_prefix}6:4'
        broker.strings.pop(key)

        self.assertFalse(await manager.consume_seed_lease(6, 4, websocket))
        self.assertNotIn((6, 4), manager._local_seed_leases)

    async def test_consume_seed_lease_renews_matching_redis_owner(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='seed-owner-renew')
        websocket = _FakeWebSocket()
        await manager.join(6, websocket, {'id': 1})
        manager._redis = _FakeRedis(broker)
        self.assertTrue(await manager.acquire_seed_lease(6, 4, websocket))
        key = f'{manager._seed_key_prefix}6:4'
        owner = broker.strings[key]

        self.assertTrue(await manager.consume_seed_lease(6, 4, websocket))

        self.assertEqual(
            broker.seed_lease_renewals,
            [(key, owner, manager._seed_lease_ttl_seconds)],
        )
        self.assertEqual(broker.strings[key], owner)

    async def test_consume_seed_lease_fails_closed_when_configured_redis_check_fails(
        self,
    ) -> None:
        class _UnavailableRedis(_FakeRedis):
            async def eval(self, *_args: Any, **_kwargs: Any) -> int:
                raise ConnectionError('redis unavailable')

        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='seed-consume-unavailable')
        websocket = _FakeWebSocket()
        await manager.join(6, websocket, {'id': 1})
        manager._redis = _FakeRedis(broker)
        self.assertTrue(await manager.acquire_seed_lease(6, 4, websocket))
        manager._redis = _UnavailableRedis(broker)

        with patch(
            'module_mindmap.websocket.room_manager.AppConfig.app_workers',
            1,
        ):
            self.assertFalse(await manager.consume_seed_lease(6, 4, websocket))

    async def test_same_redis_seed_owner_can_retry_without_opening_second_seed_window(self) -> None:
        broker = _FakeRedisBroker()
        first_manager = RoomManager(instance_id='seed-retry-first')
        second_manager = RoomManager(instance_id='seed-retry-second')
        await first_manager.start(_FakeRedis(broker))
        await second_manager.start(_FakeRedis(broker))
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        await first_manager.join(6, first, {'id': 1})
        await second_manager.join(6, second, {'id': 2})
        try:
            self.assertTrue(await first_manager.acquire_seed_lease(6, 4, first))
            self.assertTrue(await first_manager.acquire_seed_lease(6, 4, first))
            self.assertTrue(await first_manager.consume_seed_lease(6, 4, first))
            self.assertFalse(await second_manager.acquire_seed_lease(6, 4, second))
        finally:
            await first_manager.stop()
            await second_manager.stop()

    async def test_redis_seed_lease_is_released_when_owner_leaves(self) -> None:
        broker = _FakeRedisBroker()
        first_manager = RoomManager(instance_id='seed-leave-first')
        second_manager = RoomManager(instance_id='seed-leave-second')
        await first_manager.start(_FakeRedis(broker))
        await second_manager.start(_FakeRedis(broker))
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        await first_manager.join(6, first, {'id': 1})
        await second_manager.join(6, second, {'id': 2})
        try:
            self.assertTrue(await first_manager.acquire_seed_lease(6, 4, first))
            await first_manager.leave(6, first)

            self.assertTrue(await second_manager.acquire_seed_lease(6, 4, second))
        finally:
            await second_manager.stop()

    async def test_configured_redis_failure_never_falls_back_to_local_seed_lease(self) -> None:
        class _UnavailableRedis:
            async def set(self, *_args: Any, **_kwargs: Any) -> None:
                raise ConnectionError('redis unavailable')

            async def eval(self, *_args: Any, **_kwargs: Any) -> int:
                raise ConnectionError('redis unavailable')

        manager = RoomManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        await manager.join(8, first, {'id': 1})
        await manager.join(8, second, {'id': 2})
        manager._redis = _UnavailableRedis()

        with patch(
            'module_mindmap.websocket.room_manager.AppConfig.app_workers',
            1,
        ):
            self.assertFalse(await manager.acquire_seed_lease(8, 5, first))
            self.assertFalse(await manager.acquire_seed_lease(8, 5, second))
            self.assertFalse(await manager.owns_seed_lease(8, 5, first))
            self.assertFalse(await manager.owns_seed_lease(8, 5, second))

    async def test_seed_lease_fails_closed_across_workers_when_redis_is_unavailable(self) -> None:
        class _UnavailableRedis:
            async def set(self, *_args: Any, **_kwargs: Any) -> None:
                raise ConnectionError('redis unavailable')

        manager = RoomManager()
        websocket = _FakeWebSocket()
        await manager.join(9, websocket, {'id': 1})
        manager._redis = _UnavailableRedis()

        with patch(
            'module_mindmap.websocket.room_manager.AppConfig.app_workers',
            2,
        ):
            self.assertFalse(await manager.acquire_seed_lease(9, 6, websocket))
            self.assertFalse(await manager.owns_seed_lease(9, 6, websocket))

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

    async def test_only_explicit_contiguous_revision_events_preserve_lineage(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()
        await manager.join(
            46,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(46, 4)
        self.assertTrue(manager.set_content_lineage(46, 4, 'lineage-a'))
        digest = manager._lineage_digest('lineage-a')

        manager.set_content_revision(
            46,
            5,
            transition_type='content_revision_changed',
        )
        self.assertEqual(manager._content_lineages[46], (5, digest))
        manager.set_content_revision(46, 6, transition_type='tag_replaced')
        self.assertEqual(manager._content_lineages[46], (6, digest))
        manager.set_content_revision(46, 7, transition_type='tag_unbound')
        self.assertEqual(manager._content_lineages[46], (7, digest))

        manager.set_content_revision(
            46,
            9,
            transition_type='content_revision_changed',
        )
        self.assertNotIn(46, manager._content_lineages)
        self.assertTrue(manager.set_content_lineage(46, 9, 'lineage-b'))
        manager.set_content_revision(46, 10, transition_type='document_reset')
        self.assertNotIn(46, manager._content_lineages)

    async def test_local_recheck_gap_restores_lineage_only_for_contiguous_event(
        self,
    ) -> None:
        manager = RoomManager(instance_id='local-recheck-lineage-gap')
        old_editor = _FakeWebSocket()
        new_editor = _FakeWebSocket()
        for websocket, user_id in ((old_editor, 1), (new_editor, 2)):
            await manager.join(
                56,
                websocket,
                {'id': user_id},
                OFFICIAL_WRITE_CAPABILITIES,
            )
        manager.set_content_revision(56, 4)
        digest = manager._lineage_digest('stable-local-lineage')
        old_epoch = _establish_lineage(
            manager,
            56,
            4,
            'stable-local-lineage',
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            56,
            4,
            'same-node',
            old_editor,
        ))

        # 心跳可能在 HTTP commit 与正式 revision 事件之间先看到 r5。旧
        # revision 写必须立即失败关闭，但随后到达的明确连续事件要恢复同一
        # lineage 世代，不能让另一连接在节点租约 TTL 内并行进入编辑。
        manager.set_content_revision(56, 5)
        self.assertNotIn(56, manager._content_lineages)
        self.assertFalse(await manager.owns_node_edit_lease(
            56,
            'same-node',
            old_editor,
        ))

        manager.set_content_revision(
            56,
            5,
            transition_type='content_revision_changed',
        )
        self.assertEqual(manager._content_lineages[56], (5, digest))
        self.assertEqual(manager._local_lineage_epochs[56], old_epoch)
        self.assertTrue(await manager.owns_node_edit_lease(
            56,
            'same-node',
            old_editor,
        ))
        self.assertFalse(await manager.acquire_node_edit_lease(
            56,
            5,
            'same-node',
            new_editor,
        ))
        self.assertTrue(await manager.acquire_node_edit_lease(
            56,
            5,
            'same-node',
            old_editor,
        ))

    async def test_local_recheck_gap_does_not_restore_lineage_after_reset(self) -> None:
        manager = RoomManager(instance_id='local-recheck-reset-gap')
        old_editor = _FakeWebSocket()
        new_editor = _FakeWebSocket()
        for websocket, user_id in ((old_editor, 1), (new_editor, 2)):
            await manager.join(
                57,
                websocket,
                {'id': user_id},
                OFFICIAL_WRITE_CAPABILITIES,
            )
        manager.set_content_revision(57, 4)
        old_epoch = _establish_lineage(
            manager,
            57,
            4,
            'reused-local-lineage-id',
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            57,
            4,
            'same-node',
            old_editor,
        ))

        manager.set_content_revision(57, 5)
        manager.set_content_revision(
            57,
            5,
            transition_type='document_reset',
        )
        self.assertNotIn(57, manager._content_lineages)
        self.assertNotIn(57, manager._pending_content_lineages)

        self.assertTrue(manager.set_content_lineage(
            57,
            5,
            'reused-local-lineage-id',
            replace=True,
        ))
        self.assertNotEqual(manager._local_lineage_epochs[57], old_epoch)
        self.assertFalse(await manager.owns_node_edit_lease(
            57,
            'same-node',
            old_editor,
        ))
        self.assertTrue(await manager.acquire_node_edit_lease(
            57,
            5,
            'same-node',
            new_editor,
        ))

    async def test_redis_revision_cas_carries_digest_and_reset_tombstones_it(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='lineage-revision-cas')
        await manager.start(_FakeRedis(broker))
        websocket = _FakeWebSocket()
        await manager.join(
            47,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(47, 4)
        digest = manager._lineage_digest('lineage-a')
        self.assertTrue(manager.set_content_lineage(47, 4, 'lineage-a'))
        repaired, _ = await manager.repair_content_lineage_fence_from_persisted(
            47,
            4,
            digest,
        )
        self.assertTrue(repaired)
        original_record = manager._decode_lineage_fence_record(
            broker.strings[manager._lineage_fence_key(47)],
        )
        try:
            await manager.broadcast(47, {
                'type': 'content_revision_changed',
                'contentRevision': 5,
            })
            raw = broker.strings[manager._lineage_fence_key(47)]
            self.assertEqual(
                manager._decode_lineage_fence(raw),
                (5, digest, 'active'),
            )
            self.assertEqual(manager._content_lineages[47], (5, digest))
            advanced_record = manager._decode_lineage_fence_record(raw)
            self.assertEqual(advanced_record[3], original_record[3])

            await manager.broadcast(47, {
                'type': 'document_reset',
                'contentRevision': 6,
            })
            self.assertEqual(
                manager._decode_lineage_fence(
                    broker.strings[manager._lineage_fence_key(47)],
                ),
                (6, None, 'tombstone'),
            )
        finally:
            await manager.stop()

    async def test_idempotent_reset_does_not_tombstone_new_same_revision_seed(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='idempotent-reset-lineage')
        await manager.start(_FakeRedis(broker))
        websocket = _FakeWebSocket()
        await manager.join(
            48,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(48, 6)
        digest = manager._lineage_digest('post-reset-lineage')
        repaired, _ = await manager.repair_content_lineage_fence_from_persisted(
            48,
            6,
            digest,
        )
        self.assertTrue(repaired)
        try:
            await manager.broadcast(48, {
                'type': 'document_reset',
                'contentRevision': 6,
            })
            self.assertEqual(
                manager._decode_lineage_fence(
                    broker.strings[manager._lineage_fence_key(48)],
                ),
                (6, digest, 'active'),
            )
        finally:
            await manager.stop()

    async def test_handshake_does_not_tombstone_inflight_contiguous_revision(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='lineage-handshake-commit-gap')
        manager._redis = _FakeRedis(broker)
        websocket = _FakeWebSocket()
        await manager.join(
            53,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(53, 4)
        digest = manager._lineage_digest('committed-lineage')
        lineage_epoch = _establish_lineage(
            manager,
            53,
            4,
            'committed-lineage',
            broker,
        )
        old_raw = broker.strings[manager._lineage_fence_key(53)]
        manager.set_content_revision(53, 5)

        # DB 已提交 r5，但 content_revision_changed 尚未来得及推进 sticky；
        # 新握手看到空的 r5 WsState 时只能重试，不能破坏仍 active 的 r4。
        repaired, authoritative_digest = (
            await manager.repair_content_lineage_fence_from_persisted(
                53,
                5,
                None,
                preserve_matching_active=True,
            )
        )
        self.assertFalse(repaired)
        self.assertIsNone(authoritative_digest)
        self.assertEqual(
            broker.strings[manager._lineage_fence_key(53)],
            old_raw,
        )

        self.assertTrue(await manager.advance_content_revision_fence(
            53,
            5,
            'content_revision_changed',
        ))
        record = manager._decode_lineage_fence_record(
            broker.strings[manager._lineage_fence_key(53)],
        )
        self.assertEqual(record, (5, digest, 'active', lineage_epoch))

    async def test_matured_revision_gap_tombstones_when_broadcast_was_lost(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='lineage-handshake-lost-broadcast')
        manager._redis = _FakeRedis(broker)
        websocket = _FakeWebSocket()
        await manager.join(
            54,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(54, 4)
        _establish_lineage(manager, 54, 4, 'lost-event-lineage', broker)
        manager.set_content_revision(54, 5)

        first_repair = await manager.repair_content_lineage_fence_from_persisted(
            54,
            5,
            None,
            preserve_matching_active=True,
        )
        self.assertEqual(first_repair, (False, None))

        broker.lineage_gap_clock_ms += manager._lineage_gap_grace_ms
        second_repair = await manager.repair_content_lineage_fence_from_persisted(
            54,
            5,
            None,
            preserve_matching_active=True,
        )
        self.assertEqual(second_repair, (True, None))
        self.assertEqual(
            manager._decode_lineage_fence(
                broker.strings[manager._lineage_fence_key(54)],
            ),
            (5, None, 'tombstone'),
        )

    async def test_local_handshake_retries_before_clearing_commit_gap_lineage(self) -> None:
        manager = RoomManager(instance_id='local-handshake-commit-gap')
        websocket = _FakeWebSocket()
        await manager.join(
            55,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(55, 4)
        digest = manager._lineage_digest('local-committed-lineage')
        _establish_lineage(manager, 55, 4, 'local-committed-lineage')

        # mindmap_ws 握手现在先调用 repair，再决定是否 set r5；单 worker
        # 的 commit→broadcast 间隙因此返回重试，旧本地栅栏保持完整。
        repaired = await manager.repair_content_lineage_fence_from_persisted(
            55,
            5,
            None,
            preserve_matching_active=True,
        )
        self.assertEqual(repaired, (False, None))
        self.assertEqual(manager.get_content_revision(55), 4)
        self.assertEqual(manager._content_lineages[55], (4, digest))

        manager.set_content_revision(
            55,
            5,
            transition_type='content_revision_changed',
        )
        self.assertEqual(manager._content_lineages[55], (5, digest))

    async def test_sticky_lineage_switch_blocks_old_worker_guarded_broadcast(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='missed-seed-worker')
        await manager.start(_FakeRedis(broker))
        sender = _FakeWebSocket()
        peer = _FakeWebSocket()
        await manager.join(
            49,
            sender,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        await manager.join(49, peer, {'id': 2}, can_edit=False)
        manager.set_content_revision(49, 4)
        self.assertTrue(manager.set_content_lineage(49, 4, 'old-lineage'))
        broker.strings[manager._lineage_fence_key(49)] = (
            manager._encode_lineage_fence(
                4,
                manager._lineage_digest('new-lineage'),
            )
        )
        try:
            broadcasted = await manager.broadcast_with_lineage_fence(
                49,
                {
                    'type': 'update',
                    'update': 'old-update',
                    'contentRevision': 4,
                    'lineageId': 'old-lineage',
                },
                content_revision=4,
                lineage_id='old-lineage',
                exclude=sender,
            )
            self.assertFalse(broadcasted)
            self.assertEqual(peer.messages, [])
        finally:
            await manager.stop()

    async def test_configured_redis_lineage_lookup_fails_closed(self) -> None:
        class _UnavailableRedis(_FakeRedis):
            async def get(self, _key: str) -> str | None:
                raise ConnectionError('redis unavailable')

        manager = RoomManager(instance_id='lineage-redis-unavailable')
        websocket = _FakeWebSocket()
        await manager.join(
            51,
            websocket,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(51, 4)
        self.assertTrue(manager.set_content_lineage(51, 4, 'local-lineage'))
        manager._redis = _UnavailableRedis(_FakeRedisBroker())

        with patch(
            'module_mindmap.websocket.room_manager.AppConfig.app_workers',
            1,
        ):
            self.assertFalse(await manager.verify_content_lineage_fence(
                51,
                4,
                'local-lineage',
            ))

    async def test_revision_upgrade_invalidates_snapshot_generation_without_lineage(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()
        await manager.join(32, websocket, {'id': 1})
        manager.set_content_revision(32, 4)
        query_generation = manager.get_content_lineage_generation(32)

        manager.set_content_revision(32, 5)

        self.assertFalse(
            manager.is_content_lineage_generation_current(32, query_generation),
        )
        self.assertTrue(manager.is_current_revision(32, 5))

    async def test_same_revision_lineage_requires_match_unless_authoritative_replace(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()
        await manager.join(33, websocket, {'id': 1})
        manager.set_content_revision(33, 7)

        self.assertTrue(manager.set_content_lineage(33, 7, 'lineage-a'))
        self.assertTrue(manager.set_content_lineage(33, 7, 'lineage-a'))
        self.assertFalse(manager.set_content_lineage(33, 7, 'lineage-b'))
        self.assertEqual(
            manager._content_lineages[33],
            (7, manager._lineage_digest('lineage-a')),
        )

        self.assertTrue(
            manager.set_content_lineage(33, 7, 'lineage-b', replace=True),
        )
        self.assertEqual(
            manager._content_lineages[33],
            (7, manager._lineage_digest('lineage-b')),
        )

    async def test_persisted_lineage_reconciles_a_missed_redis_seed_and_retires_old_peers(
        self,
    ) -> None:
        manager = RoomManager()
        stale_peer = _FakeWebSocket()
        joining_peer = _FakeWebSocket()
        await manager.join(37, stale_peer, {'id': 1})
        await manager.join(37, joining_peer, {'id': 2})
        manager.set_content_revision(37, 8)
        self.assertTrue(manager.set_content_lineage(37, 8, 'lineage-before-missed-seed'))
        expected_generation = manager.get_content_lineage_generation(37)
        persisted_digest = manager._lineage_digest('database-authoritative-lineage')

        reconciled, replaced = manager.reconcile_persisted_content_lineage_digest(
            37,
            8,
            persisted_digest,
            expected_generation=expected_generation,
        )
        await manager.disconnect_stale_lineage_peers(37, joining_peer, 8)

        self.assertTrue(reconciled)
        self.assertTrue(replaced)
        self.assertEqual(manager._content_lineages[37], (8, persisted_digest))
        self.assertFalse(manager.is_connection_active(stale_peer))
        self.assertTrue(manager.is_connection_active(joining_peer))
        self.assertEqual(stale_peer.messages[-1]['reason'], 'yjs_lineage_changed')
        self.assertEqual(stale_peer.close_codes, [manager._slow_consumer_close_code])
        self.assertFalse(manager.consume_disconnect_persistence_permission(stale_peer))

    async def test_persisted_lineage_snapshot_cannot_overwrite_a_concurrent_seed(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()
        await manager.join(38, websocket, {'id': 1})
        manager.set_content_revision(38, 9)
        self.assertTrue(manager.set_content_lineage(38, 9, 'lineage-at-query-start'))
        query_generation = manager.get_content_lineage_generation(38)

        self.assertTrue(manager.set_content_lineage(
            38,
            9,
            'newer-redis-seed',
            replace=True,
        ))
        reconciled, replaced = manager.reconcile_persisted_content_lineage_digest(
            38,
            9,
            manager._lineage_digest('stale-database-snapshot'),
            expected_generation=query_generation,
        )

        self.assertFalse(reconciled)
        self.assertFalse(replaced)
        self.assertEqual(
            manager._content_lineages[38],
            (9, manager._lineage_digest('newer-redis-seed')),
        )

    async def test_revision_upgrade_clears_previous_lineage(self) -> None:
        manager = RoomManager()
        websocket = _FakeWebSocket()
        await manager.join(34, websocket, {'id': 1})
        manager.set_content_revision(34, 7)
        self.assertTrue(manager.set_content_lineage(34, 7, 'lineage-a'))

        manager.set_content_revision(34, 8)

        self.assertNotIn(34, manager._content_lineages)
        self.assertTrue(manager.set_content_lineage(34, 8, 'lineage-b'))

    async def test_redis_update_rejects_mismatched_lineage_but_seed_can_replace_it(self) -> None:
        manager = RoomManager(instance_id='lineage-receiver')
        broker = _FakeRedisBroker()
        manager._redis = _FakeRedis(broker)
        peer = _FakeWebSocket()
        await manager.join(35, peer, {'id': 2})
        manager.set_content_revision(35, 9)
        self.assertTrue(manager.set_content_lineage(35, 9, 'lineage-a'))
        fence_key = manager._lineage_fence_key(35)
        broker.strings[fence_key] = manager._encode_lineage_fence(
            9,
            manager._lineage_digest('lineage-a'),
        )

        def redis_event(event_id: str, message: dict) -> bytes:
            return manager._encode_redis_envelope({
                'schemaVersion': 2,
                'eventId': event_id,
                'sourceInstanceId': 'lineage-publisher',
                'issuedAtMs': manager._utc_now_ms(),
                'mindmapId': 35,
                'message': message,
            })

        mismatched_update = {
            'type': 'update',
            'update': 'mismatched-update',
            'contentRevision': 9,
            'lineageId': 'lineage-b',
        }
        await manager._handle_redis_event(
            redis_event('lineage-mismatch', mismatched_update),
        )

        self.assertEqual(peer.messages, [])
        self.assertEqual(
            manager._content_lineages[35],
            (9, manager._lineage_digest('lineage-a')),
        )

        authoritative_seed = {
            'type': 'update',
            'update': 'authoritative-seed',
            'state': 'authoritative-seed',
            'seedState': True,
            'contentRevision': 9,
            'lineageId': 'lineage-b',
        }
        broker.strings[fence_key] = manager._encode_lineage_fence(
            9,
            manager._lineage_digest('lineage-b'),
        )
        await manager._handle_redis_event(
            redis_event('lineage-authoritative-seed', authoritative_seed),
        )

        self.assertEqual(peer.messages, [authoritative_seed])
        self.assertEqual(
            manager._content_lineages[35],
            (9, manager._lineage_digest('lineage-b')),
        )

    async def test_empty_room_clears_lineage_guard(self) -> None:
        manager = RoomManager()
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        await manager.join(36, first, {'id': 1})
        await manager.join(36, second, {'id': 2})
        manager.set_content_revision(36, 4)
        self.assertTrue(manager.set_content_lineage(36, 4, 'room-lineage'))

        await manager.leave(36, first)
        self.assertIn(36, manager._content_lineages)

        await manager.leave(36, second)
        self.assertNotIn(36, manager._content_lineages)

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

    async def test_slow_local_delivery_does_not_delay_cross_worker_publish(self) -> None:
        manager = RoomManager()
        manager._send_timeout_seconds = 1
        slow = _SlowWebSocket()
        await manager.join(32, slow, {'id': 1})
        published = asyncio.Event()

        async def publish(_mindmap_id: int, _message: dict) -> None:
            published.set()

        manager._publish_redis_event = publish
        broadcast = asyncio.create_task(manager.broadcast(32, {'type': 'update'}))
        await slow.send_started.wait()
        await asyncio.wait_for(published.wait(), timeout=0.05)

        slow.release_send.set()
        await broadcast

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

    async def test_failed_connection_releases_redis_node_edit_lease(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='node-edit-send-failure')
        manager._redis = _FakeRedis(broker)
        manager._send_timeout_seconds = 0.01
        stuck = _SlowWebSocket()
        await manager.join(
            31,
            stuck,
            {'id': 1},
            OFFICIAL_WRITE_CAPABILITIES,
        )
        manager.set_content_revision(31, 7)
        lineage_epoch = _establish_lineage(
            manager,
            31,
            7,
            'send-failure-lineage',
            broker,
        )
        self.assertTrue(await manager.acquire_node_edit_lease(
            31,
            7,
            'locked-node',
            stuck,
        ))
        redis_key = manager._node_edit_lease_key(
            31,
            lineage_epoch,
            'locked-node',
        )
        self.assertIn(redis_key, broker.strings)

        self.assertFalse(await manager.send_to(stuck, {'type': 'update'}))

        self.assertNotIn(redis_key, broker.strings)
        self.assertFalse(manager.is_connection_active(stuck))

    async def test_conditional_patch_is_only_sent_to_explicitly_safe_connections(self) -> None:
        manager = RoomManager()
        safe = _FakeWebSocket()
        old_patch_client = _FakeWebSocket()
        legacy = _FakeWebSocket()
        await manager.join(
            10,
            safe,
            {'id': 1},
            {
                STRUCTURED_NODE_PATCH_CAPABILITY,
                CONDITIONAL_NODE_PATCH_CAPABILITY,
            },
        )
        await manager.join(
            10,
            old_patch_client,
            {'id': 2},
            {STRUCTURED_NODE_PATCH_CAPABILITY},
        )
        await manager.join(10, legacy, {'id': 3})
        message = {
            'type': 'update',
            'update': 'incremental',
            'state': 'full-state',
            'patch': {'schemaVersion': 1, 'nodes': [], 'deletedNodeUids': []},
        }

        await manager.broadcast(10, message)

        self.assertIsNone(safe.messages[0]['state'])
        self.assertIsNotNone(safe.messages[0]['patch'])
        self.assertEqual(old_patch_client.messages[0]['state'], 'full-state')
        self.assertIsNone(old_patch_client.messages[0]['patch'])
        self.assertEqual(legacy.messages[0]['state'], 'full-state')
        self.assertIsNone(legacy.messages[0]['patch'])
        self.assertEqual(message['state'], 'full-state')

    async def test_sequenced_revision_confirmation_forces_legacy_clients_to_reload(self) -> None:
        manager = RoomManager()
        modern = _FakeWebSocket()
        legacy = _FakeWebSocket()
        await manager.join(
            14,
            modern,
            {'id': 1},
            {YJS_MUTATION_SEQUENCE_CAPABILITY},
        )
        await manager.join(14, legacy, {'id': 2})
        message = {
            'type': 'content_revision_changed',
            'contentRevision': 8,
            'clientMutationId': 'mutation-8',
            'yjsUpdateCount': 2,
            'yjsDeliveryMode': 'sequenced',
            'authoritativeReloadRequired': True,
        }

        await manager.broadcast(14, message)

        self.assertEqual(modern.messages, [message])
        self.assertEqual(legacy.messages, [{
            'type': 'stale_state',
            'currentRevision': 8,
            'reason': 'mutation_sequence_capability_required',
            'message': '协作协议已升级，正在加载云端完整内容',
        }])

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
            lineage_id = 'cross-worker-lineage'
            broker.strings[publisher._lineage_fence_key(13)] = (
                publisher._encode_lineage_fence(
                    5,
                    publisher._lineage_digest(lineage_id),
                )
            )
            await publisher.broadcast_checkpoint(
                13,
                'cross-worker-state',
                '8',
                5,
                lineage_id=lineage_id,
            )
            await self._wait_until(lambda: len(legacy.messages) == 1)

            self.assertEqual(modern.messages, [])
            self.assertEqual(legacy.messages, [{
                'type': 'update',
                'update': 'cross-worker-state',
                'state': 'cross-worker-state',
                'patch': None,
                'contentRevision': 5,
                'origin': '8',
                'lineageId': lineage_id,
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
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=0,
            del_flag='2',
        ))

        with patch('config.database.AsyncSessionLocal', new=db_factory):
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

    async def test_terminal_close_does_not_capture_connection_joined_after_dispatch(
        self,
    ) -> None:
        manager = RoomManager()
        old_peer = _SlowWebSocket()
        reconnected_peer = _FakeWebSocket()
        await manager.join(18, old_peer, {'id': 1})
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=1,
            del_flag='0',
        ))

        with patch('config.database.AsyncSessionLocal', new=db_factory):
            close_task = asyncio.create_task(manager.broadcast_and_close_room(18, {
                'type': 'document_archived',
                'mindmapId': 18,
            }, close_code=4005))
            await old_peer.send_started.wait()
            # 事件快照完成后恢复并重连；新连接不能被旧事件的慢发送捕获。
            db_factory.session.row.status = 0
            await manager.join(18, reconnected_peer, {'id': 1})
            old_peer.release_send.set()
            await close_task

        self.assertEqual(old_peer.close_codes, [4005])
        self.assertFalse(manager.is_connection_active(old_peer))
        self.assertEqual(reconnected_peer.messages, [])
        self.assertEqual(reconnected_peer.close_codes, [])
        self.assertTrue(manager.is_connection_active(reconnected_peer))

    async def test_remote_document_deleted_event_closes_receiver_room(self) -> None:
        broker = _FakeRedisBroker()
        publisher = RoomManager(instance_id='delete-publisher')
        receiver = RoomManager(instance_id='delete-receiver')
        await publisher.start(_FakeRedis(broker))
        await receiver.start(_FakeRedis(broker))
        peer = _FakeWebSocket()
        await receiver.join(19, peer, {'id': 2})
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=0,
            del_flag='2',
        ))
        try:
            with patch('config.database.AsyncSessionLocal', new=db_factory):
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
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=1,
            del_flag='0',
        ))
        try:
            with patch('config.database.AsyncSessionLocal', new=db_factory):
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
        self.assertTrue(await receiver.acquire_seed_lease(20, 6, target_first))
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=0,
            del_flag='0',
        ))
        try:
            with (
                patch('config.database.AsyncSessionLocal', new=db_factory),
                patch(
                    'module_mindmap.dao.mindmap_collaborator_dao.'
                    'MindmapCollaboratorDao.get_collaborator_permission',
                    new=AsyncMock(return_value=None),
                ),
            ):
                await publisher.notify_and_disconnect_user(20, 7, {
                    'type': 'access_revoked',
                    'mindmapId': 20,
                    'message': '权限已撤销',
                })
                await self._wait_until(lambda: target_first.close_codes == [4003])

            for target in (target_first, target_second):
                self.assertEqual(target.messages[0]['type'], 'access_revoked')
                self.assertEqual(target.messages[0]['targetUserId'], 7)
                self.assertEqual(target.messages[0]['revocationScope'], 'access')
                self.assertEqual(target.close_codes, [4003])
            self.assertEqual(other_user.messages, [])
            self.assertEqual(other_user.close_codes, [])
            self.assertFalse(receiver.consume_disconnect_persistence_permission(target_first))
            self.assertTrue(receiver.consume_disconnect_persistence_permission(other_user))
            self.assertFalse(await receiver.owns_seed_lease(20, 6, target_first))
            self.assertEqual(receiver.get_content_revision(20), 6)
            self.assertEqual(await receiver.get_room_users(20), [{'id': 8, 'name': 'Other'}])
        finally:
            await publisher.stop()
            await receiver.stop()

    async def test_delayed_lifecycle_events_are_ignored_after_restore(self) -> None:
        for event_type in ('document_deleted', 'document_archived'):
            with self.subTest(event_type=event_type):
                manager = RoomManager(instance_id=f'restored-{event_type}')
                peer = _FakeWebSocket()
                await manager.join(21, peer, {'id': 7})
                db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
                    owner_id=7,
                    status=0,
                    del_flag='0',
                ))
                payload = _remote_event(manager, 21, event_type, {
                    'type': event_type,
                    'mindmapId': 21,
                })

                with patch('config.database.AsyncSessionLocal', new=db_factory):
                    await manager._handle_redis_event(payload)

                self.assertEqual(peer.messages, [])
                self.assertEqual(peer.close_codes, [])
                self.assertTrue(manager.is_connection_active(peer))
                self.assertFalse(db_factory.session.entered)

    async def test_source_lifecycle_event_is_ignored_if_restore_won_row_lock(self) -> None:
        manager = RoomManager()
        peer = _FakeWebSocket()
        await manager.join(22, peer, {'id': 7})
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=7,
            status=0,
            del_flag='0',
        ))

        with patch('config.database.AsyncSessionLocal', new=db_factory):
            await manager.broadcast_and_close_room(22, {
                'type': 'document_archived',
                'mindmapId': 22,
            }, close_code=4005)

        self.assertEqual(peer.messages, [])
        self.assertEqual(peer.close_codes, [])
        self.assertTrue(manager.is_connection_active(peer))

    async def test_delayed_remove_event_is_ignored_after_collaborator_readded(
        self,
    ) -> None:
        manager = RoomManager(instance_id='readded-receiver')
        peer = _FakeWebSocket()
        await manager.join(23, peer, {'id': 7}, can_edit=True)
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=0,
            del_flag='0',
        ))
        payload = _remote_event(manager, 23, 'old-remove', {
            'type': 'access_revoked',
            'mindmapId': 23,
            'targetUserId': 7,
            # 即便旧事件声称完全撤权，也必须以当前数据库权限为准。
            'revocationScope': 'access',
        })

        with (
            patch('config.database.AsyncSessionLocal', new=db_factory),
            patch(
                'module_mindmap.dao.mindmap_collaborator_dao.'
                'MindmapCollaboratorDao.get_collaborator_permission',
                new=AsyncMock(return_value=1),
            ),
        ):
            await manager._handle_redis_event(payload)

        self.assertEqual(peer.messages, [])
        self.assertEqual(peer.close_codes, [])
        self.assertTrue(manager.is_connection_active(peer))

    async def test_source_remove_event_is_ignored_after_collaborator_readded(
        self,
    ) -> None:
        manager = RoomManager()
        peer = _FakeWebSocket()
        await manager.join(24, peer, {'id': 7}, can_edit=True)
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=0,
            del_flag='0',
        ))

        with (
            patch('config.database.AsyncSessionLocal', new=db_factory),
            patch(
                'module_mindmap.dao.mindmap_collaborator_dao.'
                'MindmapCollaboratorDao.get_collaborator_permission',
                new=AsyncMock(return_value=1),
            ),
        ):
            await manager.notify_and_disconnect_user(
                24,
                7,
                {'type': 'access_revoked', 'mindmapId': 24},
                revocation_scope='access',
            )

        self.assertEqual(peer.messages, [])
        self.assertEqual(peer.close_codes, [])
        self.assertTrue(manager.is_connection_active(peer))

    async def test_permission_downgrade_only_closes_editable_connections(self) -> None:
        manager = RoomManager(instance_id='downgrade-receiver')
        editable = _FakeWebSocket()
        readonly = _FakeWebSocket()
        other_user = _FakeWebSocket()
        await manager.join(
            25,
            editable,
            {'id': 7},
            OFFICIAL_WRITE_CAPABILITIES,
            can_edit=True,
        )
        await manager.join(25, readonly, {'id': 7}, can_edit=False)
        await manager.join(
            25,
            other_user,
            {'id': 8},
            OFFICIAL_WRITE_CAPABILITIES,
            can_edit=True,
        )
        db_factory = _FakeControlEventSessionFactory(SimpleNamespace(
            owner_id=1,
            status=0,
            del_flag='0',
        ))
        payload = _remote_event(manager, 25, 'permission-downgrade', {
            'type': 'access_revoked',
            'mindmapId': 25,
            'targetUserId': 7,
            # 数据库中的 permission=0 才是 CLOSE_EDITABLE_ONLY 的依据。
            'revocationScope': 'access',
        })

        with (
            patch('config.database.AsyncSessionLocal', new=db_factory),
            patch(
                'module_mindmap.dao.mindmap_collaborator_dao.'
                'MindmapCollaboratorDao.get_collaborator_permission',
                new=AsyncMock(return_value=0),
            ),
        ):
            await manager._handle_redis_event(payload)

        self.assertEqual(editable.close_codes, [4003])
        self.assertEqual(editable.messages[0]['type'], 'access_revoked')
        self.assertFalse(manager.is_connection_active(editable))
        self.assertEqual(readonly.messages, [])
        self.assertEqual(readonly.close_codes, [])
        self.assertTrue(manager.is_connection_active(readonly))
        self.assertEqual(other_user.close_codes, [])
        self.assertTrue(manager.is_connection_active(other_user))
        self.assertEqual(
            {user['id'] for user in await manager.get_room_users(25)},
            {7, 8},
        )

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

    async def test_partial_redis_presence_never_hides_live_local_connection(self) -> None:
        broker = _FakeRedisBroker()
        manager = RoomManager(instance_id='local-presence-priority')
        await manager.start(_FakeRedis(broker))
        websocket = _FakeWebSocket()
        await manager.join(18, websocket, {'id': 2, 'name': 'Local New'})
        key = manager._presence_key(18)
        broker.sorted_sets[key].clear()
        broker.sorted_sets[key][json.dumps({
            'connectionId': 'remote-1',
            'instanceId': 'remote',
            'user': {'id': 1, 'name': 'Remote'},
        })] = time.time() + 30
        # 模拟 Redis 只留有远端旧记录；本地 zadd 曾短暂失败或刚过 TTL。
        try:
            users = await manager.get_room_users(18)
            self.assertEqual(users, [
                {'id': 2, 'name': 'Local New'},
                {'id': 1, 'name': 'Remote'},
            ])
        finally:
            await manager.stop()

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
