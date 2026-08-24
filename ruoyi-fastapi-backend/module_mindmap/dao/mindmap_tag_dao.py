"""脑图标签 DAO"""
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag, MindmapTagCategory
from utils.page_util import PageUtil


class MindmapTagDao:
    """标签数据库操作层"""

    # ── 分类 ──

    @classmethod
    async def get_categories(cls, db: AsyncSession, user_id: int) -> list[MindmapTagCategory]:
        """获取分类列表（全局 + 当前用户私有）"""
        result = (await db.execute(
            select(MindmapTagCategory)
            .where(
                or_(
                    MindmapTagCategory.owner_id == 0,
                    MindmapTagCategory.owner_id == user_id,
                )
            )
            .order_by(
                MindmapTagCategory.owner_id.asc(),
                MindmapTagCategory.sort_order.asc(),
                MindmapTagCategory.id.asc(),
            )
        )).scalars().all()
        return list(result)

    @classmethod
    async def get_category_by_id(
        cls,
        db: AsyncSession,
        category_id: int,
        *,
        for_update: bool = False,
    ) -> MindmapTagCategory | None:
        query = select(MindmapTagCategory).where(MindmapTagCategory.id == category_id)
        if for_update:
            query = query.with_for_update()
        result = (await db.execute(query)).scalars().first()
        return result

    @classmethod
    async def add_category(cls, db: AsyncSession, data: dict) -> MindmapTagCategory:
        cat = MindmapTagCategory(**data)
        db.add(cat)
        await db.flush()
        return cat

    @classmethod
    async def get_categories_by_owner(
        cls,
        db: AsyncSession,
        owner_id: int,
        *,
        for_update: bool = False,
    ) -> list[MindmapTagCategory]:
        query = (
            select(MindmapTagCategory)
            .where(MindmapTagCategory.owner_id == owner_id)
            .order_by(MindmapTagCategory.sort_order.asc(), MindmapTagCategory.id.asc())
        )
        if for_update:
            query = query.with_for_update()
        return list((await db.execute(query)).scalars().all())

    @classmethod
    async def check_category_name_unique(
        cls,
        db: AsyncSession,
        owner_id: int,
        name: str,
        exclude_id: int | None = None,
    ) -> bool:
        query = select(MindmapTagCategory.id).where(
            MindmapTagCategory.owner_id == owner_id,
            func.lower(MindmapTagCategory.name) == name.lower(),
        )
        if exclude_id is not None:
            query = query.where(MindmapTagCategory.id != exclude_id)
        return (await db.execute(query.limit(1))).scalar_one_or_none() is None

    @classmethod
    async def get_category_tag_counts(
        cls,
        db: AsyncSession,
        category_ids: list[int],
    ) -> dict[int, int]:
        if not category_ids:
            return {}
        rows = (await db.execute(
            select(MindmapTag.category_id, func.count(MindmapTag.id))
            .where(MindmapTag.category_id.in_(category_ids))
            .group_by(MindmapTag.category_id)
        )).all()
        return {int(category_id): int(count) for category_id, count in rows}

    @classmethod
    async def update_category(cls, db: AsyncSession, category_id: int, data: dict) -> None:
        await db.execute(
            update(MindmapTagCategory)
            .where(MindmapTagCategory.id == category_id)
            .values(**data)
        )

    @classmethod
    async def update_category_sort_orders(
        cls,
        db: AsyncSession,
        category_ids: list[int],
    ) -> None:
        sort_orders = {
            category_id: (index + 1) * 10
            for index, category_id in enumerate(category_ids)
        }
        await db.execute(
            update(MindmapTagCategory)
            .where(MindmapTagCategory.id.in_(category_ids))
            .values(sort_order=case(sort_orders, value=MindmapTagCategory.id))
        )

    @classmethod
    async def delete_category(cls, db: AsyncSession, category_id: int) -> None:
        await db.execute(
            delete(MindmapTagCategory).where(MindmapTagCategory.id == category_id)
        )

    @classmethod
    async def count_tags_in_category(cls, db: AsyncSession, category_id: int) -> int:
        """统计分类下的标签数量"""
        result = (await db.execute(
            select(func.count()).select_from(MindmapTag).where(MindmapTag.category_id == category_id)
        )).scalar()
        return result or 0

    # ── 标签 ──

    @classmethod
    async def get_tag_list(
        cls, db: AsyncSession, user_id: int,
        category_id: int | None = None,
        status: int | None = None,
        keyword: str | None = None,
        owner_scope: str = 'all',
        page_num: int = 1, page_size: int = 20,
    ) -> PageModel:
        """获取标签列表"""
        query = select(MindmapTag)

        # 范围筛选
        if owner_scope == 'mine':
            query = query.where(MindmapTag.owner_id == user_id)
        elif owner_scope == 'global':
            query = query.where(MindmapTag.owner_id == 0)
        else:  # all: 全局 + 私有
            query = query.where(
                or_(MindmapTag.owner_id == 0, MindmapTag.owner_id == user_id)
            )

        if category_id == 0:
            query = query.where(MindmapTag.category_id.is_(None))
        elif category_id is not None:
            query = query.where(MindmapTag.category_id == category_id)
        if status is not None:
            query = query.where(MindmapTag.status == status)

        if keyword:
            escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            query = query.where(
                or_(
                    MindmapTag.name.ilike(f'%{escaped}%', escape='\\'),
                    MindmapTag.tag_key.ilike(f'%{escaped}%', escape='\\'),
                    MindmapTag.description.ilike(f'%{escaped}%', escape='\\'),
                )
            )

        query = query.order_by(MindmapTag.updated_time.desc())
        return await PageUtil.paginate(db, query, page_num, page_size, True)

    @classmethod
    async def get_tag_by_id(cls, db: AsyncSession, tag_id: int) -> MindmapTag | None:
        result = (await db.execute(
            select(MindmapTag).where(MindmapTag.id == tag_id)
        )).scalars().first()
        return result

    @classmethod
    async def check_key_unique(
        cls, db: AsyncSession, owner_id: int, tag_key: str, exclude_id: int | None = None,
    ) -> bool:
        """检查 tag_key 是否唯一（同 scope 内），返回 True 表示唯一"""
        query = select(MindmapTag).where(
            MindmapTag.owner_id == owner_id,
            MindmapTag.tag_key == tag_key,
        )
        if exclude_id is not None:
            query = query.where(MindmapTag.id != exclude_id)
        result = (await db.execute(query)).scalars().first()
        return result is None

    @classmethod
    async def add_tag(cls, db: AsyncSession, data: dict) -> MindmapTag:
        tag = MindmapTag(**data)
        db.add(tag)
        await db.flush()
        return tag

    @classmethod
    async def update_tag(cls, db: AsyncSession, tag_id: int, data: dict) -> None:
        await db.execute(
            update(MindmapTag).where(MindmapTag.id == tag_id).values(**data)
        )

    @classmethod
    async def delete_tags(cls, db: AsyncSession, tag_ids: list[int]) -> None:
        await db.execute(delete(MindmapTag).where(MindmapTag.id.in_(tag_ids)))

    @classmethod
    async def get_suggestions(
        cls, db: AsyncSession, user_id: int, keyword: str | None = None, limit: int = 30,
    ) -> list[MindmapTag]:
        """获取标签建议（全局 + 私有，用于编辑器自动补全）"""
        query = (
            select(MindmapTag)
            .where(
                or_(MindmapTag.owner_id == 0, MindmapTag.owner_id == user_id),
                MindmapTag.status == 0,
            )
        )
        if keyword:
            escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            query = query.where(
                or_(
                    MindmapTag.name.ilike(f'%{escaped}%', escape='\\'),
                    MindmapTag.tag_key.ilike(f'%{escaped}%', escape='\\'),
                )
            )
        query = query.order_by(MindmapTag.name.asc()).limit(limit)
        result = (await db.execute(query)).scalars().all()
        return list(result)
