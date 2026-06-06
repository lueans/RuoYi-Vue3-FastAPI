"""脑图模板 DAO"""
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_template_category_do import MindmapTemplateCategory
from utils.page_util import PageUtil


class MindmapTemplateDao:
    """模板数据库操作层"""

    # ── 分类 ──

    @classmethod
    async def get_categories(cls, db: AsyncSession) -> list[MindmapTemplateCategory]:
        """获取所有模板分类"""
        result = (await db.execute(
            select(MindmapTemplateCategory)
            .order_by(MindmapTemplateCategory.sort_order.asc())
        )).scalars().all()
        return list(result)

    @classmethod
    async def add_category(cls, db: AsyncSession, data: dict) -> MindmapTemplateCategory:
        """新增分类"""
        cat = MindmapTemplateCategory(**data)
        db.add(cat)
        await db.flush()
        return cat

    @classmethod
    async def delete_category(cls, db: AsyncSession, category_id: int) -> None:
        """删除分类"""
        await db.execute(
            delete(MindmapTemplateCategory).where(MindmapTemplateCategory.id == category_id)
        )

    # ── 模板 ──

    @classmethod
    async def get_template_list(
        cls, db: AsyncSession, category_id: int | None = None,
        keyword: str | None = None, page_num: int = 1, page_size: int = 20,
    ) -> PageModel:
        """获取模板列表（公开，不含 node_tree）"""
        query = (
            select(
                Mindmap.id,
                Mindmap.name,
                Mindmap.description,
                Mindmap.cover_image,
                Mindmap.layout,
                Mindmap.template_category_id,
                Mindmap.create_time,
            )
            .where(Mindmap.is_template == 1, Mindmap.del_flag == '0')
        )

        if category_id is not None:
            query = query.where(Mindmap.template_category_id == category_id)
        if keyword:
            query = query.where(Mindmap.name.like(f'%{keyword}%'))

        query = query.order_by(Mindmap.create_time.desc())
        return await PageUtil.paginate(db, query, page_num, page_size, True)

    @classmethod
    async def get_template_by_id(cls, db: AsyncSession, template_id: int) -> Mindmap | None:
        """获取模板详情（含 node_tree）"""
        result = (await db.execute(
            select(Mindmap).where(
                Mindmap.id == template_id,
                Mindmap.is_template == 1,
                Mindmap.del_flag == '0',
            )
        )).scalars().first()
        return result

    @classmethod
    async def publish_template(cls, db: AsyncSession, data: dict) -> Mindmap:
        """发布模板（创建 is_template=1 的脑图记录）"""
        template = Mindmap(**data)
        db.add(template)
        await db.flush()
        return template

    @classmethod
    async def update_template(cls, db: AsyncSession, template_id: int, data: dict) -> None:
        """更新模板信息"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == template_id, Mindmap.is_template == 1)
            .values(**data)
        )

    @classmethod
    async def unpublish_template(cls, db: AsyncSession, template_id: int) -> None:
        """取消发布模板（软删除）"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == template_id, Mindmap.is_template == 1)
            .values(del_flag='2')
        )
