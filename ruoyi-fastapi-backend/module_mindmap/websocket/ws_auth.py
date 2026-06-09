"""WebSocket 专用认证模块"""
from datetime import timedelta
from typing import Any

import jwt
from jwt import InvalidTokenError

from common.enums import RedisInitKeyConfig
from config.database import AsyncSessionLocal
from config.env import AppConfig, JwtConfig
from module_admin.dao.user_dao import UserDao


async def validate_ws_token(token: str, redis: Any) -> dict:
    """
    WebSocket 专用 token 验证

    :param token: JWT token 字符串（不含 Bearer 前缀）
    :param redis: Redis 连接实例（从 app.state.redis 获取）
    :return: {'user_id': int, 'nick_name': str, 'avatar': str, 'user_name': str}
    :raises: ValueError with error message
    """
    try:
        if token.startswith('Bearer'):
            token = token.split(' ')[1]
        payload = jwt.decode(token, JwtConfig.jwt_secret_key, algorithms=[JwtConfig.jwt_algorithm])
        user_id: str = payload.get('user_id')
        session_id: str = payload.get('session_id')
        if not user_id:
            raise ValueError('token缺少user_id')
    except InvalidTokenError:
        raise ValueError('token已失效') from None

    # DB 查询用户
    async with AsyncSessionLocal() as db:
        query_user = await UserDao.get_user_by_id(db, user_id=int(user_id))
        if not query_user.get('user_basic_info'):
            raise ValueError('用户不存在')

        user_info = query_user['user_basic_info']

        # Redis session 校验
        try:
            if AppConfig.app_same_time_login:
                redis_token = await redis.get(f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{session_id}')
            else:
                redis_token = await redis.get(f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{user_info.user_id}')

            if token != redis_token:
                raise ValueError('token已失效，请重新登录')

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
            # Redis 不可用时但 JWT 有效，允许连接（降级处理）
            pass

        return {
            'id': user_info.user_id,
            'name': user_info.nick_name or user_info.user_name,
            'avatar': user_info.avatar or '',
            'user_name': user_info.user_name,
        }
