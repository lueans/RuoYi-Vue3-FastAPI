"""脑图标签字段 DAO"""
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_tag_field_do import MindmapTagField, MindmapTagFieldOption


class MindmapTagFieldDao:
    """标签字段数据库操作层"""

    # ── 字段 ──

    @classmethod
    async def get_fields(cls, db: AsyncSession, user_id: int) -> list[MindmapTagField]:
        """获取字段列表（全局 + 当前用户私有）"""
        result = (await db.execute(
            select(MindmapTagField)
            .where(
                or_(
                    MindmapTagField.owner_id == 0,
                    MindmapTagField.owner_id == user_id,
                )
            )
            .order_by(MindmapTagField.sort_order.asc(), MindmapTagField.id.asc())
        )).scalars().all()
        return list(result)

    @classmethod
    async def get_field_by_id(cls, db: AsyncSession, field_id: int) -> MindmapTagField | None:
        result = (await db.execute(
            select(MindmapTagField).where(MindmapTagField.id == field_id)
        )).scalars().first()
        return result

    @classmethod
    async def check_field_key_unique(
        cls, db: AsyncSession, owner_id: int, field_key: str, exclude_id: int | None = None,
    ) -> bool:
        """检查 field_key 是否唯一（同 scope 内），返回 True 表示唯一"""
        query = select(MindmapTagField).where(
            MindmapTagField.owner_id == owner_id,
            MindmapTagField.field_key == field_key,
        )
        if exclude_id is not None:
            query = query.where(MindmapTagField.id != exclude_id)
        result = (await db.execute(query)).scalars().first()
        return result is None

    @classmethod
    async def add_field(cls, db: AsyncSession, data: dict) -> MindmapTagField:
        field = MindmapTagField(**data)
        db.add(field)
        await db.flush()
        return field

    @classmethod
    async def update_field(cls, db: AsyncSession, field_id: int, data: dict) -> None:
        await db.execute(
            update(MindmapTagField)
            .where(MindmapTagField.id == field_id)
            .values(**data)
        )

    @classmethod
    async def delete_field(cls, db: AsyncSession, field_id: int) -> None:
        await db.execute(
            delete(MindmapTagField).where(MindmapTagField.id == field_id)
        )

    # ── 选项 ──

    @classmethod
    async def get_options_by_field_id(cls, db: AsyncSession, field_id: int) -> list[MindmapTagFieldOption]:
        """获取字段下的所有选项"""
        result = (await db.execute(
            select(MindmapTagFieldOption)
            .where(MindmapTagFieldOption.field_id == field_id)
            .order_by(MindmapTagFieldOption.sort_order.asc(), MindmapTagFieldOption.id.asc())
        )).scalars().all()
        return list(result)

    @classmethod
    async def get_option_by_id(cls, db: AsyncSession, option_id: int) -> MindmapTagFieldOption | None:
        result = (await db.execute(
            select(MindmapTagFieldOption).where(MindmapTagFieldOption.id == option_id)
        )).scalars().first()
        return result

    @classmethod
    async def check_option_key_unique(
        cls, db: AsyncSession, field_id: int, option_key: str, exclude_id: int | None = None,
    ) -> bool:
        """检查 option_key 在字段内是否唯一，返回 True 表示唯一"""
        query = select(MindmapTagFieldOption).where(
            MindmapTagFieldOption.field_id == field_id,
            MindmapTagFieldOption.option_key == option_key,
        )
        if exclude_id is not None:
            query = query.where(MindmapTagFieldOption.id != exclude_id)
        result = (await db.execute(query)).scalars().first()
        return result is None

    @classmethod
    async def add_option(cls, db: AsyncSession, data: dict) -> MindmapTagFieldOption:
        option = MindmapTagFieldOption(**data)
        db.add(option)
        await db.flush()
        return option

    @classmethod
    async def update_option(cls, db: AsyncSession, option_id: int, data: dict) -> None:
        await db.execute(
            update(MindmapTagFieldOption)
            .where(MindmapTagFieldOption.id == option_id)
            .values(**data)
        )

    @classmethod
    async def delete_option(cls, db: AsyncSession, option_id: int) -> None:
        await db.execute(
            delete(MindmapTagFieldOption).where(MindmapTagFieldOption.id == option_id)
        )

    @classmethod
    async def delete_options_by_field_id(cls, db: AsyncSession, field_id: int) -> None:
        """删除字段下的所有选项"""
        await db.execute(
            delete(MindmapTagFieldOption).where(MindmapTagFieldOption.field_id == field_id)
        )

    @classmethod
    async def batch_update_option_sort(
        cls, db: AsyncSession, field_id: int, sort_list: list[dict],
    ) -> None:
        """批量更新选项排序，sort_list: [{'option_id': 1, 'sort_order': 0}, ...]
        通过 field_id 约束，防止跨字段操作选项(IDOR防护)"""
        for item in sort_list:
            await db.execute(
                update(MindmapTagFieldOption)
                .where(
                    MindmapTagFieldOption.id == item['option_id'],
                    MindmapTagFieldOption.field_id == field_id,
                )
                .values(sort_order=item['sort_order'])
            )

    # ── 搜索建议 ──

    @classmethod
    async def get_suggestions(
        cls, db: AsyncSession, user_id: int, keyword: str | None = None, limit: int = 30,
    ) -> list[tuple[MindmapTagField, list[MindmapTagFieldOption]]]:
        """获取字段搜索建议（全局 + 私有），返回 (field, matched_options) 列表"""
        # 先查字段
        field_query = select(MindmapTagField).where(
            or_(MindmapTagField.owner_id == 0, MindmapTagField.owner_id == user_id)
        )
        if keyword:
            escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            field_query = field_query.where(
                or_(
                    MindmapTagField.name.like(f'%{escaped}%'),
                    MindmapTagField.field_key.like(f'%{escaped}%'),
                )
            )
        field_query = field_query.order_by(MindmapTagField.sort_order.asc(), MindmapTagField.id.asc()).limit(limit)
        fields = (await db.execute(field_query)).scalars().all()

        results = []
        for field in fields:
            # 查该字段下匹配的选项
            opt_query = select(MindmapTagFieldOption).where(
                MindmapTagFieldOption.field_id == field.id
            )
            if keyword:
                escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                opt_query = opt_query.where(
                    or_(
                        MindmapTagFieldOption.name.like(f'%{escaped}%'),
                        MindmapTagFieldOption.option_key.like(f'%{escaped}%'),
                    )
                )
            opt_query = opt_query.order_by(
                MindmapTagFieldOption.sort_order.asc(), MindmapTagFieldOption.id.asc()
            )
            options = (await db.execute(opt_query)).scalars().all()

            # 如果字段名匹配但没有选项匹配，返回全部选项
            if not options:
                all_options = (await db.execute(
                    select(MindmapTagFieldOption)
                    .where(MindmapTagFieldOption.field_id == field.id)
                    .order_by(MindmapTagFieldOption.sort_order.asc(), MindmapTagFieldOption.id.asc())
                )).scalars().all()
                options = list(all_options)

            results.append((field, list(options)))

        return results
