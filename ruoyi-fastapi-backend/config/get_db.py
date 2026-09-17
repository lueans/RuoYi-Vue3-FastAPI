from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import AsyncSessionLocal, Base, async_engine
from config.env import AppConfig, DataBaseConfig
from utils.log_util import logger

MINDMAP_AI_SCHEMA_MIGRATIONS = (
    '20260910_mindmap_ai_agent.sql',
)
MINDMAP_AI_SCHEMA_GATE_ENVIRONMENTS = frozenset({'prod', 'dockermy', 'dockerpg'})


def _mindmap_ai_required_schema() -> dict[str, frozenset[str]]:
    """Build the current AI-only table/column contract from its ORM models."""
    from module_mindmap.entity.do.mindmap_ai_do import (  # noqa: PLC0415
        MindmapAiArtifact,
        MindmapAiConnector,
        MindmapAiDraftCheckpoint,
        MindmapAiJob,
        MindmapAiJobEvent,
        MindmapAiProposal,
        MindmapAiResponse,
        MindmapAiSession,
        MindmapAiUndo,
    )

    models = (
        MindmapAiSession,
        MindmapAiConnector,
        MindmapAiJob,
        MindmapAiResponse,
        MindmapAiArtifact,
        MindmapAiProposal,
        MindmapAiJobEvent,
        MindmapAiDraftCheckpoint,
        MindmapAiUndo,
    )
    return {
        model.__tablename__: frozenset(model.__table__.columns.keys())
        for model in models
    }


def validate_mindmap_ai_runtime_schema(connection: Connection) -> None:
    """Fail production startup when this AI rollout's tables/columns are absent."""
    schema = _mindmap_ai_required_schema()
    inspector = inspect(connection)
    available_tables = set(inspector.get_table_names())
    missing = [
        f'table:{table}'
        for table in sorted(schema)
        if table not in available_tables
    ]
    for table, required_columns in sorted(schema.items()):
        if table not in available_tables:
            continue
        available_columns = {
            str(column['name']) for column in inspector.get_columns(table)
        }
        missing.extend(
            f'column:{table}.{column}'
            for column in sorted(required_columns - available_columns)
        )

    if missing:
        migration_chain = ' -> '.join(MINDMAP_AI_SCHEMA_MIGRATIONS)
        raise RuntimeError(
            'AI 脑图数据库 Schema 不完整，拒绝生产启动；缺少 '
            f'{", ".join(missing)}。请按顺序执行迁移：{migration_chain}',
        )


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
    if (
        AppConfig.app_env in MINDMAP_AI_SCHEMA_GATE_ENVIRONMENTS
        and DataBaseConfig.db_auto_create_tables
    ):
        raise RuntimeError(
            '生产环境禁止启用 DB_AUTO_CREATE_TABLES；请执行已审核的数据库迁移',
        )
    logger.info('🔎 初始化数据库连接...')
    async with async_engine.begin() as conn:
        if DataBaseConfig.db_auto_create_tables:
            await conn.run_sync(Base.metadata.create_all)
            logger.warning('开发模式已启用 ORM 自动建表；生产环境必须关闭')
            # create_all only creates missing objects; it does not upgrade an
            # existing development database. Apply the same focused contract
            # check so a stale AI schema cannot leave the app half-started.
            await conn.run_sync(validate_mindmap_ai_runtime_schema)
        else:
            await conn.execute(text('SELECT 1'))
            if AppConfig.app_env in MINDMAP_AI_SCHEMA_GATE_ENVIRONMENTS:
                await conn.run_sync(validate_mindmap_ai_runtime_schema)
    logger.info('✅️ 数据库连接成功')


async def close_async_engine() -> None:
    """
    应用关闭时释放数据库连接池

    :return:
    """
    await async_engine.dispose()
