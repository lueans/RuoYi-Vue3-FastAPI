"""验证结构化脑图按层批量写入与增量更新，最终回滚测试数据。"""

import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_service import MindmapService
from scripts.benchmark_mindmap_core import build_tree, count_nodes

VERIFY_NODE_COUNT = 257


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    tree, nodes = build_tree(VERIFY_NODE_COUNT, branch_factor=8)
    # 该脚本只验证节点批处理和路径查询，不应依赖环境中恰好存在的标签 ID。
    for node in nodes:
        node['data'].pop('tag', None)
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            now = datetime.now()
            mindmap = Mindmap(
                name=f'batch-verify-{marker}',
                owner_id=1,
                layout='logicalStructure',
                node_tree=json.dumps(tree, ensure_ascii=False),
                content_revision=1,
                node_count=0,
                schema_version=1,
                version_count=1,
                status=0,
                del_flag='0',
                create_by='verify',
                update_by='verify',
                create_time=now,
                update_time=now,
            )
            session.add(mindmap)
            await session.flush()

            created = await MindmapDocumentService.persist_tree(
                session,
                mindmap.id,
                tree,
                owner_id=1,
                operator='verify',
            )
            mindmap.root_node_id = created['root_node_id']
            mindmap.node_count = created['node_count']
            restored = await MindmapDocumentService.load_tree(session, mindmap.id)
            assert count_nodes(restored) == VERIFY_NODE_COUNT

            nodes[-1]['data']['text'] = '批量更新后的节点'
            tree['children'].append({
                'data': {'uid': f'added-{marker}', 'text': '新增节点'},
                'children': [],
            })
            updated = await MindmapDocumentService.persist_tree_incremental(
                session,
                mindmap.id,
                tree,
                owner_id=1,
                operator='verify',
            )
            actions = {item['action'] for item in updated['changed_nodes']}
            assert updated['node_count'] == VERIFY_NODE_COUNT + 1
            assert {'create', 'update'} <= actions
            restored = await MindmapDocumentService.load_tree(session, mindmap.id)
            assert count_nodes(restored) == VERIFY_NODE_COUNT + 1
            search_result = await MindmapService.search_nodes_services(
                session,
                mindmap.id,
                user_id=1,
                keyword='批量更新后的节点',
            )
            assert search_result.total == 1
            result_row = search_result.rows[0]
            assert result_row['path'][0]['nodeUid'] == 'node-0'
            assert result_row['path'][-1]['nodeUid'] == nodes[-1]['data']['uid']
            assert result_row['pathText'].endswith('批量更新后的节点')
            print('mindmap structured batching verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
