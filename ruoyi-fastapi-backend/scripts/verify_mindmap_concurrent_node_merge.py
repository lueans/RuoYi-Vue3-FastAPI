"""使用真实数据库验证并发节点合并，测试数据最终回滚。"""

import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_vo import MindmapContentBatchModel
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_service import MindmapService


def _node(uid: str, text: str, children: list[dict] | None = None) -> dict:
    return {'data': {'uid': uid, 'text': text}, 'children': children or []}


def _children_update(old_children: list[str], children: list[str]) -> dict:
    return {
        'type': 'node.update',
        'nodeUid': 'merge-root',
        'payload': {
            'dataChanged': False,
            'childrenChanged': True,
            'oldChildUids': old_children,
            'childUids': children,
        },
    }


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    now = datetime.now()
    base_tree = _node('merge-root', 'root', [_node('a', 'a')])
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            mindmap = Mindmap(
                name=f'concurrent-merge-{marker}', owner_id=1, layout='logicalStructure',
                node_tree=json.dumps(base_tree, ensure_ascii=False), content_revision=1,
                node_count=0, schema_version=1, version_count=1, status=0, del_flag='0',
                create_by='verify', update_by='verify', create_time=now, update_time=now,
            )
            session.add(mindmap)
            await session.flush()
            metadata = await MindmapDocumentService.persist_tree(
                session, mindmap.id, base_tree, owner_id=1, operator='verify',
            )
            mindmap.root_node_id = metadata['root_node_id']
            mindmap.node_count = metadata['node_count']
            mindmap.schema_version = metadata['schema_version']
            await session.flush()
            root_revision = (await MindmapContentDao.get_node_revisions(session, mindmap.id))['merge-root']

            # ghost 模拟 Yjs 已显示在本地、但不属于本批操作的远端节点；服务端不得
            # 因为客户端上传了完整物化树就把它写入缺少操作日志的当前 revision。
            remote_tree = _node(
                'merge-root', 'root',
                [_node('a', 'a'), _node('ghost', 'untracked'), _node('d', 'remote')],
            )
            await MindmapService.update_content_batch_services(
                session,
                mindmap.id,
                MindmapContentBatchModel(
                    baseRevision=1,
                    clientMutationId=f'remote-{marker}',
                    operations=[
                        _children_update(['a', 'ghost'], ['a', 'ghost', 'd']),
                        {'type': 'node.create', 'nodeUid': 'd', 'payload': {'data': {'uid': 'd'}}},
                    ],
                    nodeTree=remote_tree,
                ),
                user_id=1,
            )

            local_tree = _node('merge-root', 'root', [_node('a', 'a'), _node('c', 'local')])
            addition_result = await MindmapService.update_content_batch_services(
                session,
                mindmap.id,
                MindmapContentBatchModel(
                    baseRevision=1,
                    clientMutationId=f'local-add-{marker}',
                    operations=[
                        _children_update(['a'], ['a', 'c']),
                        {'type': 'node.create', 'nodeUid': 'c', 'payload': {'data': {'uid': 'c'}}},
                    ],
                    nodeTree=local_tree,
                ),
                user_id=1,
            )
            assert addition_result['concurrentMerge'] is True
            assert [child['data']['uid'] for child in addition_result['nodeTree']['children']] == ['a', 'c', 'd']

            stale_data_tree = _node('merge-root', 'renamed', [_node('a', 'a')])
            data_result = await MindmapService.update_content_batch_services(
                session,
                mindmap.id,
                MindmapContentBatchModel(
                    baseRevision=1,
                    clientMutationId=f'local-data-{marker}',
                    operations=[{
                        'type': 'node.update',
                        'nodeUid': 'merge-root',
                        'targetRevision': root_revision,
                        'payload': {
                            'dataChanged': True,
                            'childrenChanged': False,
                            'oldChildUids': ['a'],
                            'childUids': ['a'],
                        },
                    }],
                    nodeTree=stale_data_tree,
                ),
                user_id=1,
            )
            assert data_result['concurrentMerge'] is True
            assert data_result['nodeTree']['data']['text'] == 'renamed'
            assert [child['data']['uid'] for child in data_result['nodeTree']['children']] == ['a', 'c', 'd']
            print('mindmap concurrent node merge verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
