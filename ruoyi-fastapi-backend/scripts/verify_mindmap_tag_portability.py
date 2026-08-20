"""使用真实数据库验证脑图跨所有者复制的标签语义，数据最终回滚。"""

import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_tag_portability import MindmapTagPortabilityService

TARGET_OWNER_ID = 2


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    now = datetime.now()
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            tags = [
                MindmapTag(
                    uuid=str(uuid.uuid4()), tag_key=f'global_{marker}', name=f'全局 {marker}',
                    owner_id=0, status=0, style={'fill': '#2563eb'}, definition_revision=1,
                    usage_node_count=0, usage_file_count=0,
                    created_by='verify', update_by='verify', created_time=now, updated_time=now,
                ),
                MindmapTag(
                    uuid=str(uuid.uuid4()), tag_key=f'private_{marker}', name=f'私有 {marker}',
                    owner_id=1, status=0, style={'fill': '#16a34a'}, definition_revision=1,
                    usage_node_count=0, usage_file_count=0,
                    created_by='verify', update_by='verify', created_time=now, updated_time=now,
                ),
                MindmapTag(
                    uuid=str(uuid.uuid4()), tag_key=f'disabled_{marker}', name=f'停用 {marker}',
                    owner_id=0, status=1, style={'fill': '#64748b'}, definition_revision=1,
                    usage_node_count=0, usage_file_count=0,
                    created_by='verify', update_by='verify', created_time=now, updated_time=now,
                ),
            ]
            session.add_all(tags)
            await session.flush()
            global_tag, private_tag, disabled_tag = tags
            source_tree = {
                'data': {
                    'uid': 'portable-root',
                    'text': '可携带性',
                    'tag': [
                        {'tagId': global_tag.id, 'text': global_tag.name, 'style': global_tag.style},
                        {'tagId': private_tag.id, 'text': private_tag.name, 'style': private_tag.style},
                        {'tagId': disabled_tag.id, 'text': disabled_tag.name, 'style': disabled_tag.style},
                    ],
                },
                'children': [],
            }
            portable_tree = await MindmapTagPortabilityService.prepare_tree_for_owner(
                session, source_tree, target_owner_id=TARGET_OWNER_ID,
            )
            portable_tags = portable_tree['data']['tag']
            assert portable_tags[0]['tagId'] == global_tag.id
            assert 'tagId' not in portable_tags[1]
            assert 'tagId' not in portable_tags[2]
            assert portable_tags[1]['style']['fill'] == '#16a34a'
            assert portable_tags[2]['text'] == disabled_tag.name

            mindmap = Mindmap(
                name=f'portable-{marker}', owner_id=TARGET_OWNER_ID, layout='logicalStructure',
                node_tree=json.dumps(portable_tree, ensure_ascii=False), content_revision=1,
                node_count=0, schema_version=1, version_count=1, status=0, del_flag='0',
                create_by='verify', update_by='verify', create_time=now, update_time=now,
            )
            session.add(mindmap)
            await session.flush()
            await MindmapDocumentService.persist_tree(
                session, mindmap.id, portable_tree, owner_id=TARGET_OWNER_ID, operator='verify',
            )
            restored = await MindmapDocumentService.load_tree(session, mindmap.id)
            restored_ids = [tag['tagId'] for tag in restored['data']['tag']]
            assert global_tag.id in restored_ids
            created_tags = list((await session.execute(
                select(MindmapTag).where(
                    MindmapTag.owner_id == TARGET_OWNER_ID,
                    MindmapTag.id.in_(restored_ids),
                )
            )).scalars())
            assert {tag.name for tag in created_tags} == {private_tag.name, disabled_tag.name}
            assert all(tag.status == 0 for tag in created_tags)
            print('mindmap tag portability verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
