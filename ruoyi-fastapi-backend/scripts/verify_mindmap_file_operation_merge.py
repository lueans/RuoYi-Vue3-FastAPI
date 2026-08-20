"""验证文件元数据操作可与并发节点更新自动合并，测试数据最终回滚。"""

import asyncio
import copy
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_vo import MindmapContentBatchModel
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_service import MindmapService

REMOTE_REVISION = 2
MERGED_REVISION = 3


def build_tree() -> dict:
    return {
        'data': {'uid': 'root', 'text': '根节点'},
        'children': [{'data': {'uid': 'child', 'text': '原始文本'}, 'children': []}],
    }


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    initial_tree = build_tree()
    remote_tree = copy.deepcopy(initial_tree)
    remote_tree['children'][0]['data']['text'] = '远端节点更新'
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            now = datetime.now()
            mindmap = Mindmap(
                name=f'file-operation-merge-{marker}',
                owner_id=1,
                layout='logicalStructure',
                theme={'template': 'default', 'config': {}},
                view_data={'transform': {'scaleX': 1, 'scaleY': 1}},
                node_tree=json.dumps(initial_tree, ensure_ascii=False),
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
            metadata = await MindmapDocumentService.persist_tree(
                session,
                mindmap.id,
                initial_tree,
                owner_id=1,
                operator='verify',
            )
            mindmap.root_node_id = metadata['root_node_id']
            mindmap.node_count = metadata['node_count']
            mindmap.schema_version = metadata['schema_version']
            await session.flush()

            remote_result = await MindmapService.update_content_batch_services(
                session,
                mindmap.id,
                MindmapContentBatchModel(
                    baseRevision=1,
                    clientMutationId=f'{marker}-node',
                    operations=[{'type': 'node.update', 'nodeUid': 'child'}],
                    nodeTree=remote_tree,
                    viewData=mindmap.view_data,
                    layout=mindmap.layout,
                    theme=mindmap.theme,
                ),
                user_id=1,
            )
            revisions_before_view = await MindmapContentDao.get_node_revisions(session, mindmap.id)

            new_view = {'transform': {'scaleX': 1.5, 'scaleY': 1.5, 'translateX': 80}}
            merged = await MindmapService.update_content_batch_services(
                session,
                mindmap.id,
                MindmapContentBatchModel(
                    baseRevision=1,
                    clientMutationId=f'{marker}-view',
                    operations=[{'type': 'file.view.update'}],
                    nodeTree=initial_tree,
                    viewData=new_view,
                    layout='logicalStructure',
                    theme={'template': 'default', 'config': {}},
                ),
                user_id=1,
            )
            revisions_after_view = await MindmapContentDao.get_node_revisions(session, mindmap.id)
            restored = await MindmapDocumentService.load_tree(session, mindmap.id)
            stored_view = (await session.execute(
                select(Mindmap.view_data).where(Mindmap.id == mindmap.id)
            )).scalar_one()

            assert remote_result['contentRevision'] == REMOTE_REVISION
            assert merged['contentRevision'] == MERGED_REVISION
            assert merged['concurrentMerge'] is True
            assert merged['nodeTree']['children'][0]['data']['text'] == '远端节点更新'
            assert restored['children'][0]['data']['text'] == '远端节点更新'
            assert revisions_before_view == revisions_after_view
            assert stored_view == new_view
            print('mindmap file operation concurrent merge verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
