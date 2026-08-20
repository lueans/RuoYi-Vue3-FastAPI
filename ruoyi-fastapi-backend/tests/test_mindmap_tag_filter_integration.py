"""脑图列表按统一标签筛选的真实数据库集成测试。"""

import os
import unittest

from sqlalchemy import func, select, update

from config.database import AsyncSessionLocal, async_engine
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_tag_dao import MindmapTagDao
from module_mindmap.entity.do.mindmap_content_do import MindmapNode, MindmapNodeTag
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.do.mindmap_tag_field_do import MindmapTagFieldOption
from module_mindmap.entity.vo.mindmap_vo import MindmapPageQueryModel
from module_mindmap.service.mindmap_tag_service import MindmapTagService

REQUIRED_REPLACEMENT_TAG_COUNT = 2


@unittest.skipUnless(
    os.getenv('MINDMAP_DB_INTEGRATION') == '1',
    '需要显式启用真实数据库集成测试',
)
class MindmapTagFilterIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        # IsolatedAsyncioTestCase 每个用例使用独立事件循环，连接池不能跨循环复用。
        await async_engine.dispose()

    async def test_tag_governance_filters_status_keyword_and_field(self) -> None:
        async with AsyncSessionLocal() as db:
            sample = (await db.execute(
                select(MindmapTag, MindmapTagFieldOption.field_id)
                .outerjoin(MindmapTagFieldOption, MindmapTagFieldOption.tag_id == MindmapTag.id)
                .order_by(MindmapTag.updated_time.desc(), MindmapTag.id.desc())
                .limit(1)
            )).first()
            if not sample:
                self.skipTest('数据库中没有可用于治理筛选的标签')
            tag, field_id = sample
            user_id = tag.owner_id if tag.owner_id else 1
            result = await MindmapTagDao.get_tag_list(
                db,
                user_id,
                field_id=field_id,
                status=tag.status,
                keyword=tag.tag_key,
                owner_scope='mine' if tag.owner_id else 'global',
                page_num=1,
                page_size=100,
            )
            self.assertIn(tag.id, {row['id'] for row in result.rows})

    async def test_list_returns_exact_owner_files_using_tag(self) -> None:
        async with AsyncSessionLocal() as db:
            sample = (await db.execute(
                select(Mindmap.owner_id, MindmapNodeTag.tag_id)
                .join(MindmapNodeTag, MindmapNodeTag.file_id == Mindmap.id)
                .where(Mindmap.del_flag == '0')
                .limit(1)
            )).first()
            if not sample:
                self.skipTest('数据库中没有可用于标签筛选的节点绑定')
            owner_id, tag_id = sample
            expected = set((await db.execute(
                select(Mindmap.id)
                .join(MindmapNodeTag, MindmapNodeTag.file_id == Mindmap.id)
                .where(
                    Mindmap.owner_id == owner_id,
                    Mindmap.del_flag == '0',
                    MindmapNodeTag.tag_id == tag_id,
                )
                .distinct()
            )).scalars())

            result = await MindmapDao.get_mindmap_list(
                db,
                MindmapPageQueryModel(ownerId=owner_id, tagId=tag_id),
                is_page=False,
            )

            self.assertEqual({row['id'] for row in result}, expected)

    async def test_replace_context_queries_distinguish_null_and_field_bindings(self) -> None:
        async with AsyncSessionLocal() as db:
            node = (await db.execute(
                select(MindmapNode.id, MindmapNode.file_id).limit(1)
            )).first()
            if not node:
                self.skipTest('数据库中没有可用于替换上下文验证的节点')
            node_id, file_id = node
            existing_tag_ids = select(MindmapNodeTag.tag_id).where(
                MindmapNodeTag.node_id == node_id,
            )
            tag_ids = list((await db.execute(
                select(MindmapTag.id)
                .where(MindmapTag.id.not_in(existing_tag_ids))
                .limit(REQUIRED_REPLACEMENT_TAG_COUNT)
            )).scalars())
            if len(tag_ids) < REQUIRED_REPLACEMENT_TAG_COUNT:
                self.skipTest('数据库中没有两个可用于替换上下文验证的标签')
            source_tag_id, target_tag_id = tag_ids

            try:
                db.add_all([
                    MindmapNodeTag(
                        file_id=file_id, node_id=node_id, tag_id=source_tag_id,
                        sort_order=1000,
                    ),
                    MindmapNodeTag(
                        file_id=file_id, node_id=node_id, tag_id=target_tag_id,
                        sort_order=1001,
                    ),
                ])
                await db.flush()
                duplicate_query, conflict_query = MindmapTagService._replacement_binding_queries(
                    source_tag_id, target_tag_id,
                )
                duplicate_count = (await db.execute(
                    select(func.count()).select_from(duplicate_query.subquery())
                )).scalar_one()
                conflict_count = (await db.execute(
                    select(func.count()).select_from(conflict_query.subquery())
                )).scalar_one()
                self.assertEqual((duplicate_count, conflict_count), (1, 0))

                await db.execute(
                    update(MindmapNodeTag)
                    .where(
                        MindmapNodeTag.node_id == node_id,
                        MindmapNodeTag.tag_id == source_tag_id,
                    )
                    .values(field_id=987654321, option_id=987654322)
                )
                duplicate_count = (await db.execute(
                    select(func.count()).select_from(duplicate_query.subquery())
                )).scalar_one()
                conflict_count = (await db.execute(
                    select(func.count()).select_from(conflict_query.subquery())
                )).scalar_one()
                self.assertEqual((duplicate_count, conflict_count), (0, 1))
            finally:
                await db.rollback()


if __name__ == '__main__':
    unittest.main()
