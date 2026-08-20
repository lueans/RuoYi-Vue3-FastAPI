"""只读检查脑图代码所需的数据库迁移产物。"""

import asyncio
import json

from config.database import create_async_db_engine
from module_mindmap.service.mindmap_schema_verifier import (
    find_mindmap_schema_issues,
    inspect_mindmap_schema,
)


async def verify() -> int:
    engine = create_async_db_engine(echo=False)
    try:
        async with engine.connect() as connection:
            snapshot = await connection.run_sync(inspect_mindmap_schema)
    finally:
        await engine.dispose()
    issues = find_mindmap_schema_issues(snapshot)
    for issue in issues:
        print(json.dumps({'status': 'MISSING', **issue.to_dict()}, ensure_ascii=False))
    print(json.dumps({
        'status': 'READY' if not issues else 'NOT_READY',
        'missingCount': len(issues),
        'readOnly': True,
    }, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(verify()))
