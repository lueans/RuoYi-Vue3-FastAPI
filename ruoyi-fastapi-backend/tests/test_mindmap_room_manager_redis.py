"""脑图 RoomManager 的真实 Redis 集成测试。

默认跳过；本地或 CI 可执行：
``MINDMAP_REDIS_INTEGRATION=1 python -m unittest tests.test_mindmap_room_manager_redis -v``
"""

import asyncio
import os
import time
import unittest
from collections.abc import Callable

from config.get_redis import RedisUtil
from module_mindmap.websocket.room_manager import RoomManager


class _IntegrationWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.close_codes: list[int] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)

    async def close(self, code: int) -> None:
        self.close_codes.append(code)


@unittest.skipUnless(os.getenv('MINDMAP_REDIS_INTEGRATION') == '1', '需要显式启用真实 Redis 集成测试')
class MindmapRoomManagerRedisIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_cross_instance_event_and_presence(self) -> None:
        redis = await RedisUtil.create_redis_pool(log_enabled=False)
        publisher = RoomManager(instance_id='integration-publisher')
        receiver = RoomManager(instance_id='integration-receiver')
        room_id = 900_000_000 + time.time_ns() % 10_000_000
        websocket = _IntegrationWebSocket()
        other_websocket = _IntegrationWebSocket()
        try:
            await publisher.start(redis)
            await receiver.start(redis)
            await receiver.join(room_id, websocket, {'id': 9, 'name': 'Redis User'})
            await receiver.join(room_id, other_websocket, {'id': 10, 'name': 'Other User'})

            await publisher.broadcast(room_id, {
                'type': 'content_revision_changed',
                'contentRevision': 8,
            })
            await self._wait_until(lambda: len(websocket.messages) == 1 and len(other_websocket.messages) == 1)

            self.assertEqual(websocket.messages[0]['contentRevision'], 8)
            self.assertEqual(
                {user['id'] for user in await publisher.get_room_users(room_id)},
                {9, 10},
            )

            await publisher.notify_and_disconnect_user(room_id, 9, {
                'type': 'access_revoked',
                'mindmapId': room_id,
                'message': '权限已撤销',
            })
            await self._wait_until(lambda: websocket.close_codes == [4003])
            self.assertEqual(websocket.messages[-1]['type'], 'access_revoked')
            self.assertEqual(other_websocket.close_codes, [])
            self.assertEqual(
                await publisher.get_room_users(room_id),
                [{'id': 10, 'name': 'Other User'}],
            )

            await publisher.broadcast_and_close_room(room_id, {
                'type': 'document_deleted',
                'mindmapId': room_id,
            })
            await self._wait_until(lambda: other_websocket.close_codes == [4004])
            self.assertEqual(other_websocket.messages[-1]['type'], 'document_deleted')
            self.assertEqual(await receiver.get_room_users(room_id), [])
        finally:
            await receiver.leave(room_id, websocket)
            await receiver.leave(room_id, other_websocket)
            await publisher.stop()
            await receiver.stop()
            await redis.aclose()

    async def _wait_until(self, predicate: Callable[[], bool], timeout: float = 2) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                self.fail('等待真实 Redis 跨实例事件超时')
            await asyncio.sleep(0.01)


if __name__ == '__main__':
    unittest.main()
