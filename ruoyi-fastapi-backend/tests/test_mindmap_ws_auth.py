"""脑图 WebSocket 长连接认证复核测试。"""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt

from config.env import JwtConfig
from module_mindmap.websocket.room_manager import RoomManager
from module_mindmap.websocket.ws_auth import WsAuthenticationError, validate_ws_token


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeRedis:
    def __init__(self, stored_token: str | None = None, error: Exception | None = None) -> None:
        self.stored_token = stored_token
        self.error = error
        self.set_calls: list[tuple[tuple, dict]] = []

    async def get(self, _key: str) -> str | None:
        if self.error:
            raise self.error
        return self.stored_token

    async def set(self, *args: object, **kwargs: object) -> None:
        self.set_calls.append((args, kwargs))


def _create_token(*, expires_in: timedelta = timedelta(minutes=5)) -> str:
    return jwt.encode(
        {
            'user_id': '7',
            'session_id': 'session-7',
            'exp': datetime.now(timezone.utc) + expires_in,
        },
        JwtConfig.jwt_secret_key,
        algorithm=JwtConfig.jwt_algorithm,
    )


class MindmapWsAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(
            user_id=7,
            nick_name='协作者',
            user_name='editor',
            avatar='',
        )

    async def _validate(self, token: str, redis: _FakeRedis) -> dict:
        with (
            patch(
                'module_mindmap.websocket.ws_auth.AsyncSessionLocal',
                side_effect=_SessionContext,
            ),
            patch(
                'module_mindmap.websocket.ws_auth.UserDao.get_user_by_id',
                new=AsyncMock(return_value={'user_basic_info': self.user}),
            ),
        ):
            return await validate_ws_token(token, redis)

    async def test_active_session_is_revalidated_and_ttl_is_refreshed(self) -> None:
        token = _create_token()
        redis = _FakeRedis(token)

        result = await self._validate(token, redis)

        self.assertEqual(result['id'], 7)
        self.assertEqual(result['name'], '协作者')
        self.assertEqual(len(redis.set_calls), 1)

    async def test_revoked_session_has_stable_non_retryable_reason(self) -> None:
        token = _create_token()

        with self.assertRaises(WsAuthenticationError) as context:
            await self._validate(token, _FakeRedis('a-different-token'))

        self.assertEqual(context.exception.code, 'session_revoked')
        self.assertFalse(context.exception.retryable)

    async def test_redis_outage_is_retryable_without_accepting_session(self) -> None:
        token = _create_token()

        with self.assertRaises(WsAuthenticationError) as context:
            await self._validate(token, _FakeRedis(error=ConnectionError('redis down')))

        self.assertEqual(context.exception.code, 'auth_unavailable')
        self.assertTrue(context.exception.retryable)

    async def test_expired_and_malformed_bearer_tokens_are_rejected(self) -> None:
        with self.assertRaises(WsAuthenticationError) as expired_context:
            await self._validate(
                _create_token(expires_in=timedelta(seconds=-1)),
                _FakeRedis(),
            )
        self.assertEqual(expired_context.exception.code, 'token_expired')

        with self.assertRaises(WsAuthenticationError) as malformed_context:
            await self._validate('Bearer', _FakeRedis())
        self.assertEqual(malformed_context.exception.code, 'invalid_token')

    async def test_invalidated_connection_cannot_persist_on_disconnect(self) -> None:
        manager = RoomManager(instance_id='auth-test')
        websocket = object()

        manager.block_disconnect_persistence(websocket)

        self.assertFalse(manager.consume_disconnect_persistence_permission(websocket))
        self.assertTrue(manager.consume_disconnect_persistence_permission(websocket))


if __name__ == '__main__':
    unittest.main()
