"""WebSocket 专用认证模块"""
from datetime import timedelta
from typing import Any

import jwt
from jwt import InvalidTokenError

from common.enums import RedisInitKeyConfig
from config.database import AsyncSessionLocal
from config.env import AppConfig, JwtConfig
from module_admin.dao.user_dao import UserDao


class WsAuthenticationError(ValueError):
    """可供长连接区分失效会话与暂时认证故障的稳定错误。"""

    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _decode_ws_token(token: str) -> tuple[str, int, str | None]:
    """规范化并解码 JWT，不把底层解析异常暴露给 WebSocket 客户端。"""
    try:
        if not isinstance(token, str) or not token.strip():
            raise WsAuthenticationError('请重新登录', code='invalid_token')
        token = token.strip()
        if token.startswith('Bearer'):
            scheme, separator, credentials = token.partition(' ')
            if scheme != 'Bearer' or not separator or not credentials.strip():
                raise WsAuthenticationError('token格式无效，请重新登录', code='invalid_token')
            token = credentials.strip()
        payload = jwt.decode(token, JwtConfig.jwt_secret_key, algorithms=[JwtConfig.jwt_algorithm])
        raw_user_id = payload.get('user_id')
        session_id = payload.get('session_id')
        user_id = int(raw_user_id)
        if user_id <= 0:
            raise ValueError
        if AppConfig.app_same_time_login and not session_id:
            raise WsAuthenticationError('token缺少session_id', code='invalid_token')
        return token, user_id, session_id
    except WsAuthenticationError:
        raise
    except InvalidTokenError:
        raise WsAuthenticationError('token已失效，请重新登录', code='token_expired') from None
    except (TypeError, ValueError):
        raise WsAuthenticationError('token缺少有效user_id', code='invalid_token') from None


async def validate_ws_token(token: str, redis: Any) -> dict:
    """
    WebSocket 专用 token 验证

    :param token: JWT token 字符串（不含 Bearer 前缀）
    :param redis: Redis 连接实例（从 app.state.redis 获取）
    :return: {'user_id': int, 'nick_name': str, 'avatar': str, 'user_name': str}
    :raises: ValueError with error message
    """
    token, user_id, session_id = _decode_ws_token(token)

    # DB 查询用户
    async with AsyncSessionLocal() as db:
        query_user = await UserDao.get_user_by_id(db, user_id=user_id)
        if not query_user.get('user_basic_info'):
            raise WsAuthenticationError('用户不存在或已停用', code='account_unavailable')

        user_info = query_user['user_basic_info']

        # Redis session 校验
        try:
            if AppConfig.app_same_time_login:
                redis_token = await redis.get(f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{session_id}')
            else:
                redis_token = await redis.get(f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{user_info.user_id}')

            if token != redis_token:
                raise WsAuthenticationError('登录会话已失效，请重新登录', code='session_revoked')

            # 刷新 Redis TTL
            if AppConfig.app_same_time_login:
                await redis.set(
                    f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{session_id}',
                    redis_token,
                    ex=timedelta(minutes=JwtConfig.jwt_redis_expire_minutes),
                )
            else:
                await redis.set(
                    f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{user_info.user_id}',
                    redis_token,
                    ex=timedelta(minutes=JwtConfig.jwt_redis_expire_minutes),
                )
        except (ConnectionError, TimeoutError, OSError):
            # Redis 不可用时拒绝连接（fail-closed），防止已撤销 token 被接受
            raise WsAuthenticationError(
                '认证服务暂时不可用，请稍后重试',
                code='auth_unavailable',
                retryable=True,
            ) from None

        return {
            'id': user_info.user_id,
            'name': user_info.nick_name or user_info.user_name,
            'avatar': user_info.avatar or '',
            'user_name': user_info.user_name,
        }
