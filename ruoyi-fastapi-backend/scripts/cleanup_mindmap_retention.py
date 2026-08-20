"""Plan or execute one bounded mindmap retention cleanup batch."""

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker

from config.database import create_async_db_engine
from module_mindmap.service.mindmap_retention_service import (
    MindmapRetentionPolicy,
    MindmapRetentionService,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='脑图增量与创建幂等记录保留清理')
    parser.add_argument('--execute', action='store_true', help='显式执行一批删除；默认只读计划')
    parser.add_argument('--creation-days', type=int, default=30)
    parser.add_argument('--change-days', type=int, default=90)
    parser.add_argument('--keep-revisions', type=int, default=1_000)
    parser.add_argument('--batch-size', type=int, default=1_000)
    args, _ = parser.parse_known_args()
    return args


async def run() -> int:
    args = parse_args()
    try:
        policy = MindmapRetentionPolicy(
            creation_days=args.creation_days,
            change_days=args.change_days,
            keep_revisions=args.keep_revisions,
            batch_size=args.batch_size,
        )
    except ValueError as exc:
        print(json.dumps({'status': 'INVALID_POLICY', 'message': str(exc)}, ensure_ascii=False))
        return 2

    engine = create_async_db_engine(echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            if args.execute:
                result = await MindmapRetentionService.execute_batch(session, policy)
                status = 'EXECUTED'
            else:
                result = await MindmapRetentionService.plan(session, policy)
                status = 'PLANNED'
            print(json.dumps({'status': status, **result}, ensure_ascii=False))
    finally:
        await engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run()))
