"""Phase 3/4 脑图标签治理与版本快照事务级验收脚本。

脚本在外层事务中构造临时数据；服务层即使调用 commit，也不会提交外层事务，
最终统一回滚，不污染开发数据库。
"""
import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.entity.do.mindmap_content_do import MindmapChangeLog, MindmapNode, MindmapNodeTag
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.do.mindmap_version_do import MindmapVersion
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.mindmap_tag_service import MindmapTagService
from module_mindmap.service.mindmap_version_service import MindmapVersionService

ARCHIVED_STATUS = 2
REVISION_AFTER_REPLACE = 2
REVISION_AFTER_UNBIND = 3


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            now = datetime.now()
            source = MindmapTag(
                uuid=str(uuid.uuid4()), tag_key=f'verify_source_{marker}', name='快照旧名称',
                owner_id=1, style={'fill': '#ff0000'}, status=0, definition_revision=1,
                usage_node_count=1, usage_file_count=1, created_by='verify', created_time=now,
                updated_time=now, update_by='verify',
            )
            target = MindmapTag(
                uuid=str(uuid.uuid4()), tag_key=f'verify_target_{marker}', name='替换目标',
                owner_id=1, style={'fill': '#00ff00'}, status=0, definition_revision=1,
                usage_node_count=0, usage_file_count=0, created_by='verify', created_time=now,
                updated_time=now, update_by='verify',
            )
            session.add_all([source, target])
            await session.flush()

            tree = {
                'data': {
                    'uid': f'root-{marker}', 'text': '可搜索节点',
                    'tag': [{'tagId': source.id, 'text': source.name, 'style': source.style}],
                },
                'children': [],
            }
            mindmap = Mindmap(
                name=f'phase34-{marker}', owner_id=1, node_tree=json.dumps(tree, ensure_ascii=False),
                layout='logicalStructure', content_revision=1, node_count=1, schema_version=2,
                version_count=1, status=0, del_flag='0', create_by='verify', update_by='verify',
                create_time=now, update_time=now,
            )
            session.add(mindmap)
            await session.flush()
            node = MindmapNode(
                file_id=mindmap.id, node_uid=f'root-{marker}', text_content='可搜索节点',
                text_plain='可搜索节点', text_format='plain', is_expanded=1, sort_order=0,
                node_revision=1, is_deleted=0, create_by='verify', update_by='verify',
                create_time=now, update_time=now,
            )
            session.add(node)
            await session.flush()
            mindmap.root_node_id = node.id
            session.add_all([
                MindmapNodeTag(
                    file_id=mindmap.id, node_id=node.id, tag_id=source.id,
                    sort_order=0, created_by='verify', created_time=now,
                ),
                MindmapNodeTag(
                    file_id=mindmap.id, node_id=node.id, tag_id=target.id,
                    sort_order=1, created_by='verify', created_time=now,
                ),
            ])
            await session.flush()

            await MindmapVersionService.create_draft_version(
                session, mindmap.id, tree, None, mindmap.layout, None, 'verify',
            )
            replace_result = await MindmapTagService.replace_tag(
                session, source.id, target.id, user_id=1,
            )
            assert replace_result.result['replacedNodeCount'] == 1
            assert replace_result.result['duplicateBindingCount'] == 1
            assert source.status == ARCHIVED_STATUS
            binding_tag_ids = list((await session.execute(
                select(MindmapNodeTag.tag_id).where(MindmapNodeTag.node_id == node.id)
            )).scalars())
            assert binding_tag_ids == [target.id]
            await session.refresh(mindmap)
            assert mindmap.content_revision == REVISION_AFTER_REPLACE
            assert (await session.execute(
                select(MindmapChangeLog).where(MindmapChangeLog.file_id == mindmap.id)
            )).scalars().one().operations[0]['type'] == 'tag.replace'

            search_result = await MindmapService.search_nodes_services(
                session, mindmap.id, 1, keyword='搜索', tag_id=target.id,
            )
            assert search_result.total == 1
            assert search_result.rows[0]['nodeUid'] == node.node_uid

            # 草稿版本应冻结创建时源标签定义，后续主表改名不影响预览。
            draft = (await session.execute(
                select(MindmapVersion).where(MindmapVersion.mindmap_id == mindmap.id)
            )).scalars().one()
            await session.execute(update(MindmapTag).where(MindmapTag.id == source.id).values(name='主表新名称'))
            detail = await MindmapVersionService.get_version_detail_services(session, draft.id, 1)
            assert detail.node_tree['data']['tag'][0]['text'] == '快照旧名称'

            unbind_result = await MindmapTagService.delete_tags(
                session, str(target.id), user_id=1, unbind=True,
            )
            assert unbind_result.result['unbind'] is True
            assert (await session.execute(
                select(MindmapNodeTag).where(MindmapNodeTag.node_id == node.id)
            )).scalars().first() is None
            await session.refresh(mindmap)
            assert mindmap.content_revision == REVISION_AFTER_UNBIND

            print('phase34 integration verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
