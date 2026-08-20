"""脑图标签字段 DAO"""
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
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
        """批量返回可见字段及可新增绑定的选项。"""
        active_option_condition = or_(
            MindmapTagFieldOption.tag_id.is_(None),
            MindmapTag.status == 0,
        )
        field_query = select(MindmapTagField).where(
            or_(MindmapTagField.owner_id == 0, MindmapTagField.owner_id == user_id)
        )
        if keyword:
            escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            matching_option_exists = (
                select(MindmapTagFieldOption.id)
                .outerjoin(MindmapTag, MindmapTag.id == MindmapTagFieldOption.tag_id)
                .where(
                    MindmapTagFieldOption.field_id == MindmapTagField.id,
                    active_option_condition,
                    or_(
                        MindmapTagFieldOption.name.ilike(f'%{escaped}%', escape='\\'),
                        MindmapTagFieldOption.option_key.ilike(f'%{escaped}%', escape='\\'),
                    ),
                )
                .exists()
            )
            field_query = field_query.where(
                or_(
                    MindmapTagField.name.ilike(f'%{escaped}%', escape='\\'),
                    MindmapTagField.field_key.ilike(f'%{escaped}%', escape='\\'),
                    matching_option_exists,
                )
            )
        field_query = field_query.order_by(MindmapTagField.sort_order.asc(), MindmapTagField.id.asc()).limit(limit)
        fields = list((await db.execute(field_query)).scalars())
        if not fields:
            return []

        options = list((await db.execute(
            select(MindmapTagFieldOption)
            .outerjoin(MindmapTag, MindmapTag.id == MindmapTagFieldOption.tag_id)
            .where(
                MindmapTagFieldOption.field_id.in_([field.id for field in fields]),
                active_option_condition,
            )
            .order_by(
                MindmapTagFieldOption.field_id.asc(),
                MindmapTagFieldOption.sort_order.asc(),
                MindmapTagFieldOption.id.asc(),
            )
        )).scalars())
        options_by_field: dict[int, list[MindmapTagFieldOption]] = {}
        for option in options:
            options_by_field.setdefault(option.field_id, []).append(option)

        normalized_keyword = keyword.casefold() if keyword else None
        results = []
        for field in fields:
            field_options = options_by_field.get(field.id, [])
            if normalized_keyword and normalized_keyword not in field.name.casefold() \
                    and normalized_keyword not in field.field_key.casefold():
                field_options = [
                    option for option in field_options
                    if normalized_keyword in option.name.casefold()
                    or normalized_keyword in option.option_key.casefold()
                ]
            results.append((field, field_options))
        return results
