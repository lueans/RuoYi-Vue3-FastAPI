"""只读比对旧 node_tree 与结构化脑图，输出规范化哈希和差异路径。"""

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import select

from config.database import AsyncSessionLocal
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_shadow_verifier import compare_mindmap_trees
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='只读校验脑图新旧持久化模型的一致性')
    parser.add_argument('--file-id', type=int, help='只校验指定脑图文件')
    parser.add_argument('--limit', type=int, default=0, help='最多校验数量，0 表示不限')
    parser.add_argument('--fail-fast', action='store_true', help='发现首个差异后停止')
    return parser.parse_args()


def _preview(value: Any, max_length: int = 240) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= max_length else f'{text[:max_length]}…'


async def verify(args: argparse.Namespace) -> int:
    checked = matched = mismatched = failed = 0
    async with AsyncSessionLocal() as db:
        query = (
            select(Mindmap)
            .where(
                Mindmap.del_flag == '0',
                Mindmap.schema_version >= SCHEMA_VERSION,
                Mindmap.root_node_id.is_not(None),
            )
            .order_by(Mindmap.id)
        )
        if args.file_id:
            query = query.where(Mindmap.id == args.file_id)
        if args.limit > 0:
            query = query.limit(args.limit)
        mindmaps = list((await db.execute(query)).scalars())

        for mindmap in mindmaps:
            checked += 1
            try:
                legacy_tree = mindmap.node_tree
                if isinstance(legacy_tree, str):
                    legacy_tree = json.loads(legacy_tree)
                structured_tree = await MindmapDocumentService.load_tree(db, mindmap.id)
                if not isinstance(legacy_tree, dict) or not structured_tree:
                    raise ValueError('旧树或结构化树为空')
                result = compare_mindmap_trees(legacy_tree, structured_tree)
                if result.is_equal:
                    matched += 1
                    print(json.dumps({
                        'status': 'MATCH',
                        'fileId': mindmap.id,
                        'hash': result.legacy_hash,
                    }, ensure_ascii=False))
                    continue
                mismatched += 1
                print(json.dumps({
                    'status': 'MISMATCH',
                    'fileId': mindmap.id,
                    'legacyHash': result.legacy_hash,
                    'structuredHash': result.structured_hash,
                    'differencePath': result.difference_path,
                    'legacyValue': _preview(result.legacy_value),
                    'structuredValue': _preview(result.structured_value),
                }, ensure_ascii=False))
                if args.fail_fast:
                    break
            except Exception as error:
                failed += 1
                print(json.dumps({
                    'status': 'ERROR',
                    'fileId': mindmap.id,
                    'error': str(error),
                }, ensure_ascii=False))
                if args.fail_fast:
                    break

    print(json.dumps({
        'status': 'SUMMARY',
        'checked': checked,
        'matched': matched,
        'mismatched': mismatched,
        'failed': failed,
    }, ensure_ascii=False))
    return 1 if mismatched or failed else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(verify(parse_args())))
