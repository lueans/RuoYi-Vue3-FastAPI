"""真实数据库验证正式版本创建、停用标签恢复和计数回收，数据最终回滚。"""

import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.do.mindmap_version_do import MindmapVersion
from module_mindmap.entity.vo.mindmap_version_vo import MindmapVersionSaveModel
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_version_service import MindmapVersionService

AFTER_CREATE_VERSION_COUNT = 2
AFTER_RESTORE_VERSION_COUNT = 3
RESTORED_CONTENT_REVISION = 2


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    now = datetime.now()
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            tag = MindmapTag(
                uuid=str(uuid.uuid4()), tag_key=f'version_{marker}', name=f'版本标签 {marker}',
                owner_id=1, status=0, style={'fill': '#7c3aed'}, definition_revision=1,
                usage_node_count=0, usage_file_count=0,
                created_by='verify', update_by='verify', created_time=now, updated_time=now,
            )
            session.add(tag)
            await session.flush()
            tagged_tree = {
                'data': {
                    'uid': 'version-root', 'text': '版本恢复',
                    'tag': [{'tagId': tag.id, 'text': tag.name, 'style': tag.style}],
                },
                'children': [],
            }
            mindmap = Mindmap(
                name=f'version-{marker}', owner_id=1, layout='logicalStructure',
                node_tree=json.dumps(tagged_tree, ensure_ascii=False), content_revision=1,
                node_count=0, schema_version=1, version_count=1, status=0, del_flag='0',
                create_by='verify', update_by='verify', create_time=now, update_time=now,
            )
            session.add(mindmap)
            await session.flush()
            metadata = await MindmapDocumentService.persist_tree(
                session, mindmap.id, tagged_tree, owner_id=1, operator='verify',
            )
            mindmap.root_node_id = metadata['root_node_id']
            mindmap.node_count = metadata['node_count']
            mindmap.schema_version = metadata['schema_version']
            await session.flush()

            await MindmapVersionService.create_formal_version(
                session,
                MindmapVersionSaveModel(mindmapId=mindmap.id, name='带标签版本'),
                user_id=1,
                user_name='verify',
            )
            formal = (await session.execute(
                select(MindmapVersion).where(
                    MindmapVersion.mindmap_id == mindmap.id,
                    MindmapVersion.version_type == 1,
                )
            )).scalars().one()
            await session.refresh(mindmap)
            assert mindmap.version_count == AFTER_CREATE_VERSION_COUNT

            untagged_tree = {'data': {'uid': 'version-root', 'text': '版本恢复', 'tag': []}, 'children': []}
            await MindmapDocumentService.persist_tree_incremental(
                session, mindmap.id, untagged_tree, owner_id=1, operator='verify',
            )
            tag.status = 1
            await session.flush()

            await MindmapVersionService.restore_version_services(
                session, formal.id, user_id=1, user_name='verify',
            )
            restored = await MindmapDocumentService.load_tree(session, mindmap.id)
            assert restored['data']['tag'][0]['tagId'] == tag.id
            await session.refresh(mindmap)
            assert mindmap.version_count == AFTER_RESTORE_VERSION_COUNT
            assert mindmap.content_revision == RESTORED_CONTENT_REVISION

            await MindmapVersionService.delete_version_services(session, formal.id, user_id=1)
            await session.refresh(mindmap)
            assert mindmap.version_count == AFTER_CREATE_VERSION_COUNT
            print('mindmap version workflow verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
