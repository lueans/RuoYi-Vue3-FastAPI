"""使用真实数据库验证标签绑定权限与停用语义，测试数据最终回滚。"""

import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.dao.mindmap_tag_field_dao import MindmapTagFieldDao
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.do.mindmap_tag_field_do import MindmapTagField, MindmapTagFieldOption
from module_mindmap.service.mindmap_document_service import MindmapDocumentService


def _tree(*tags: dict, child_tags: list[dict] | None = None) -> dict:
    return {
        'data': {'uid': 'guard-root', 'text': '权限校验', 'tag': list(tags)},
        'children': [{
            'data': {'uid': 'guard-child', 'text': '子节点', 'tag': child_tags or []},
            'children': [],
        }],
    }


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            now = datetime.now()
            mindmap = Mindmap(
                name=f'tag-guard-{marker}',
                owner_id=1,
                layout='logicalStructure',
                node_tree=json.dumps(_tree(), ensure_ascii=False),
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
            owned = MindmapTag(
                uuid=str(uuid.uuid4()), tag_key=f'owned_{marker}', name='可用标签',
                owner_id=1, status=0, definition_revision=1,
                usage_node_count=0, usage_file_count=0,
                created_by='verify', update_by='verify', created_time=now, updated_time=now,
            )
            foreign = MindmapTag(
                uuid=str(uuid.uuid4()), tag_key=f'foreign_{marker}', name='他人标签',
                owner_id=2, status=0, definition_revision=1,
                usage_node_count=0, usage_file_count=0,
                created_by='verify', update_by='verify', created_time=now, updated_time=now,
            )
            available = MindmapTag(
                uuid=str(uuid.uuid4()), tag_key=f'available_{marker}', name='可选标签',
                owner_id=1, status=0, definition_revision=1,
                usage_node_count=0, usage_file_count=0,
                created_by='verify', update_by='verify', created_time=now, updated_time=now,
            )
            session.add_all([mindmap, owned, foreign, available])
            await session.flush()
            field = MindmapTagField(
                field_key=f'guard_{marker}', name=f'权限字段 {marker}',
                select_mode='multi', owner_id=1, sort_order=0,
                created_by='verify', created_time=now, updated_time=now,
            )
            session.add(field)
            await session.flush()
            session.add_all([
                MindmapTagFieldOption(
                    field_id=field.id, tag_id=owned.id, option_key='disabled',
                    name='已停用选项', sort_order=0, created_time=now,
                ),
                MindmapTagFieldOption(
                    field_id=field.id, tag_id=available.id, option_key='active',
                    name='可选选项', sort_order=1, created_time=now,
                ),
            ])
            await session.flush()

            initial = _tree({'tagId': owned.id, 'text': owned.name})
            await MindmapDocumentService.persist_tree(
                session, mindmap.id, initial, owner_id=1, operator='verify',
            )
            owned.status = 1
            await session.flush()

            suggestions = await MindmapTagFieldDao.get_suggestions(session, 1, marker)
            assert len(suggestions) == 1
            assert [option.tag_id for option in suggestions[0][1]] == [available.id]

            # 原节点可以继续保留已停用标签。
            await MindmapDocumentService.persist_tree_incremental(
                session, mindmap.id, initial, owner_id=1, operator='verify',
            )

            rejected = [
                (_tree(child_tags=[{'tagId': owned.id, 'text': owned.name}]), '停用标签新绑定'),
                (_tree({'tagId': foreign.id, 'text': foreign.name}), '他人私有标签'),
                (_tree({'tagId': 9_999_999_999, 'text': '不应创建'}), '失效标签 ID'),
            ]
            for candidate, scenario in rejected:
                try:
                    await MindmapDocumentService.persist_tree_incremental(
                        session, mindmap.id, candidate, owner_id=1, operator='verify',
                    )
                except ValueError:
                    continue
                raise AssertionError(f'{scenario}未被拒绝')

            version_tree = _tree(child_tags=[{'tagId': owned.id, 'text': owned.name}])
            await MindmapDocumentService.persist_tree_incremental(
                session,
                mindmap.id,
                version_tree,
                owner_id=1,
                operator='verify',
                allow_disabled_bindings=True,
            )
            restored = await MindmapDocumentService.load_tree(session, mindmap.id)
            assert restored['children'][0]['data']['tag'][0]['tagId'] == owned.id

            print('mindmap tag binding guard verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
