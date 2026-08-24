"""将 mindmap.node_tree 迁移为结构化脑图内容。

使用前先执行 migrations/20260817_mindmap_structured_content.sql。
默认逐文件提交，一个文件失败不会回滚已经成功的文件。
"""
import argparse
import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import AsyncSessionLocal
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.do.mindmap_content_do import MindmapMigrationRecord
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_shadow_verifier import (
    canonicalize_mindmap_tree,
    compare_mindmap_trees,
    hash_canonical_document,
)
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION, SimpleMindDocumentCodec


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='迁移脑图结构化内容')
    parser.add_argument('--file-id', type=int, help='只迁移指定脑图文件')
    parser.add_argument('--limit', type=int, default=0, help='最多迁移数量，0表示不限')
    parser.add_argument('--dry-run', action='store_true', help='只解析校验，不写数据库')
    parser.add_argument('--batch-id', help='迁移批次标识，默认自动生成')
    return parser.parse_args()


async def record_migration_result(
    db: AsyncSession,
    *,
    file_id: int,
    batch_id: str,
    status: str,
    started_time: datetime,
    legacy_hash: str | None = None,
    structured_hash: str | None = None,
    error_message: str | None = None,
) -> MindmapMigrationRecord:
    """按文件 upsert 迁移结果，重跑时保留最新的权威状态。"""
    record = (await db.execute(
        select(MindmapMigrationRecord).where(MindmapMigrationRecord.file_id == file_id)
    )).scalars().first()
    values = {
        'batch_id': batch_id,
        'status': status,
        'legacy_hash': legacy_hash,
        'structured_hash': structured_hash,
        'error_message': error_message[:2000] if error_message else None,
        'started_time': started_time,
        'finished_time': datetime.now(),
    }
    if record is None:
        record = MindmapMigrationRecord(file_id=file_id, **values)
        db.add(record)
    else:
        for field, value in values.items():
            setattr(record, field, value)
    return record


def prepare_legacy_tree(mindmap: Mindmap) -> tuple[dict, int, str]:
    tree = mindmap.node_tree
    if isinstance(tree, str):
        tree = json.loads(tree)
    encoded = SimpleMindDocumentCodec.encode(tree)
    if not encoded.root_uid or not encoded.nodes:
        raise ValueError('节点树为空或没有有效根节点')
    legacy_hash = hash_canonical_document(canonicalize_mindmap_tree(tree))
    return tree, len(encoded.nodes), legacy_hash


async def persist_verified_tree(
    db: AsyncSession,
    *,
    mindmap: Mindmap,
    tree: dict,
    batch_id: str,
    started_time: datetime,
) -> str:
    """在同一事务中持久化、回读和校验，差异时由调用方整体回滚。"""
    metadata = await MindmapDocumentService.persist_tree(
        db,
        mindmap.id,
        tree,
        owner_id=mindmap.owner_id,
        operator='migration',
        allow_disabled_bindings=True,
    )
    await MindmapDao.edit_mindmap_dao(db, {'id': mindmap.id, **metadata})
    structured_tree = await MindmapDocumentService.load_tree(db, mindmap.id)
    if not structured_tree:
        raise ValueError('结构化树回读为空')
    comparison = compare_mindmap_trees(tree, structured_tree)
    if not comparison.is_equal:
        raise ValueError(f'新旧树影子校验失败: path={comparison.difference_path}')
    await record_migration_result(
        db,
        file_id=mindmap.id,
        batch_id=batch_id,
        status='migrated',
        started_time=started_time,
        legacy_hash=comparison.legacy_hash,
        structured_hash=comparison.structured_hash,
    )
    return comparison.structured_hash


async def migrate_file(file_id: int, batch_id: str, *, dry_run: bool) -> bool:
    started_time = datetime.now()
    legacy_hash = structured_hash = None
    async with AsyncSessionLocal() as db:
        try:
            mindmap = await MindmapDao.get_mindmap_by_id(db, file_id)
            if not mindmap:
                raise ValueError('脑图不存在或已删除')
            tree, node_count, legacy_hash = prepare_legacy_tree(mindmap)
            if not dry_run:
                structured_hash = await persist_verified_tree(
                    db,
                    mindmap=mindmap,
                    tree=tree,
                    batch_id=batch_id,
                    started_time=started_time,
                )
                await db.commit()
            print(
                f'OK file_id={file_id} nodes={node_count} '
                f'hash={legacy_hash} batch_id={batch_id}'
            )
            return True
        except Exception as exc:
            await db.rollback()
            if not dry_run:
                try:
                    await record_migration_result(
                        db,
                        file_id=file_id,
                        batch_id=batch_id,
                        status='failed',
                        started_time=started_time,
                        legacy_hash=legacy_hash,
                        structured_hash=structured_hash,
                        error_message=str(exc),
                    )
                    await db.commit()
                except Exception as tracking_error:
                    await db.rollback()
                    print(f'TRACKING_FAILED file_id={file_id} error={tracking_error}')
            print(f'FAILED file_id={file_id} batch_id={batch_id} error={exc}')
            return False


async def migrate(args: argparse.Namespace) -> int:
    migrated = failed = 0
    batch_id = args.batch_id or f'{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}'
    async with AsyncSessionLocal() as db:
        query = select(Mindmap).where(
            Mindmap.del_flag == '0',
            or_(Mindmap.schema_version < SCHEMA_VERSION, Mindmap.root_node_id.is_(None)),
        ).order_by(Mindmap.id)
        if args.file_id:
            query = query.where(Mindmap.id == args.file_id)
        if args.limit > 0:
            query = query.limit(args.limit)
        file_ids = [item.id for item in (await db.execute(query)).scalars()]

    for file_id in file_ids:
        if await migrate_file(file_id, batch_id, dry_run=args.dry_run):
            migrated += 1
        else:
            failed += 1

    print(
        f'completed batch_id={batch_id} migrated={migrated} '
        f'failed={failed} dry_run={args.dry_run}'
    )
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(migrate(parse_args())))
