from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import AsyncSessionLocal, Base, async_engine
from config.env import DataBaseConfig
from utils.log_util import logger


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    每一个请求处理完毕后会关闭当前连接，不同的请求使用不同的连接

    :return:
    """
    async with AsyncSessionLocal() as current_db:
        yield current_db


async def init_create_table() -> None:
    """
    应用启动时初始化数据库连接

    :return:
    """
    logger.info('🔎 初始化数据库连接...')
    async with async_engine.begin() as conn:
        if DataBaseConfig.db_auto_create_tables:
            await conn.run_sync(Base.metadata.create_all)
            logger.warning('开发模式已启用 ORM 自动建表；生产环境必须关闭')
        else:
            await conn.execute(text('SELECT 1'))
    logger.info('✅️ 数据库连接成功')


async def close_async_engine() -> None:
    """
    应用关闭时释放数据库连接池

    :return:
    """
    await async_engine.dispose()
