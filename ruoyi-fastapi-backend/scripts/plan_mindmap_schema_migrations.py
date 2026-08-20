"""只读生成脑图 Schema 迁移发布计划；不会执行 SQL 或修改数据库。"""

import asyncio
import json
from pathlib import Path

from config.database import create_async_db_engine
from config.env import DataBaseConfig
from module_mindmap.service.mindmap_schema_release import (
    MANUAL_REVIEW_MIGRATIONS,
    build_mindmap_migration_plan,
)
from module_mindmap.service.mindmap_schema_verifier import (
    find_mindmap_schema_issues,
    inspect_mindmap_schema,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / 'migrations'


async def plan() -> int:
    engine = create_async_db_engine(echo=False)
    try:
        async with engine.connect() as connection:
            snapshot = await connection.run_sync(inspect_mindmap_schema)
    finally:
        await engine.dispose()

    issues = find_mindmap_schema_issues(snapshot)
    migration_plan = build_mindmap_migration_plan(issues, MIGRATIONS_DIR)
    payload = {
        'status': 'READY' if not issues else 'NOT_READY',
        'database': DataBaseConfig.db_database,
        'readOnly': True,
        'missingCount': len(issues),
        'pendingMigrationCount': len(migration_plan),
        'migrations': [item.to_dict() for item in migration_plan],
        'manualReview': list(MANUAL_REVIEW_MIGRATIONS),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(plan()))
