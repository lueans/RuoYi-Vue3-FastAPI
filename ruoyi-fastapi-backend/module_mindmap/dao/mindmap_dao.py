from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_vo import MindmapPageQueryModel
from utils.page_util import PageUtil


class MindmapDao:
    """思维导图模块数据库操作层"""

    @classmethod
    async def get_mindmap_by_id(cls, db: AsyncSession, mindmap_id: int) -> Mindmap | None:
        """根据ID获取思维导图详细信息"""
        result = (
            await db.execute(
                select(Mindmap).where(
                    Mindmap.id == mindmap_id,
                    Mindmap.del_flag == '0',
                )
            )
        ).scalars().first()
        return result

    @classmethod
    async def get_mindmap_list(
        cls, db: AsyncSession, query_object: MindmapPageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """获取思维导图列表"""
        query = (
            select(
                Mindmap.id,
                Mindmap.name,
                Mindmap.description,
                Mindmap.layout,
                Mindmap.cover_image,
                Mindmap.folder_id,
                Mindmap.is_template,
                Mindmap.version_count,
                Mindmap.status,
                Mindmap.create_time,
                Mindmap.update_time,
            )
            .where(
                Mindmap.owner_id == query_object.owner_id,
                Mindmap.del_flag == '0',
                Mindmap.name.like(
                    f'%{query_object.name.replace(chr(92), chr(92)*2).replace("%", chr(92) + "%").replace("_", chr(92) + "_")}%'
                ) if query_object.name else True,
                Mindmap.status == query_object.status if query_object.status is not None else True,
                Mindmap.is_template == query_object.is_template if query_object.is_template is not None else True,
                Mindmap.folder_id == query_object.folder_id if query_object.folder_id is not None else True,
                Mindmap.create_time >= query_object.begin_time if query_object.begin_time else True,
                Mindmap.create_time <= query_object.end_time if query_object.end_time else True,
            )
            .distinct()
        )

        # Sorting — 白名单防止任意属性访问
        _allowed_sort_fields = {'name', 'create_time', 'update_time', 'version_count', 'status'}
        sort_column = getattr(
            Mindmap, query_object.sort_field, Mindmap.update_time
        ) if query_object.sort_field in _allowed_sort_fields else Mindmap.update_time
        if query_object.sort_order == 'desc':
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        if is_page:
            mindmap_list: PageModel = await PageUtil.paginate(
                db, query, query_object.page_num, query_object.page_size, True
            )
            return mindmap_list
        result = (await db.execute(query)).all()
        return [dict(row._mapping) for row in result]

    @classmethod
    async def add_mindmap_dao(cls, db: AsyncSession, data: dict) -> Mindmap:
        """新增思维导图"""
        db_mindmap = Mindmap(**data)
        db.add(db_mindmap)
        await db.flush()
        return db_mindmap

    @classmethod
    async def edit_mindmap_dao(cls, db: AsyncSession, mindmap: dict) -> None:
        """编辑思维导图"""
        mindmap_id = mindmap.pop('id', None)
        if mindmap_id is None:
            raise ValueError('edit_mindmap_dao requires id in data dict')
        await db.execute(update(Mindmap).where(Mindmap.id == mindmap_id).values(**mindmap))

    @classmethod
    async def update_content_dao(cls, db: AsyncSession, mindmap_id: int, data: dict) -> None:
        """更新思维导图内容（node_tree, view_data, layout, theme）"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == mindmap_id)
            .values(**data)
        )

    @classmethod
    async def delete_mindmap_dao(cls, db: AsyncSession, mindmap_id: int) -> None:
        """软删除思维导图"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == mindmap_id)
            .values(del_flag='2')
        )

    @classmethod
    async def batch_delete_mindmap_dao(cls, db: AsyncSession, mindmap_ids: list[int]) -> None:
        """批量软删除思维导图"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id.in_(mindmap_ids))
            .values(del_flag='2')
        )

    @classmethod
    async def check_name_unique(
        cls, db: AsyncSession, name: str, owner_id: int, exclude_id: int | None = None
    ) -> bool:
        """检查名称是否唯一（同一用户下）"""
        conditions = [
            Mindmap.name == name,
            Mindmap.owner_id == owner_id,
            Mindmap.del_flag == '0',
        ]
        if exclude_id:
            conditions.append(Mindmap.id != exclude_id)

        result = (await db.execute(select(Mindmap.id).where(*conditions))).first()
        return result is None

    @classmethod
    async def increment_version_count(cls, db: AsyncSession, mindmap_id: int) -> None:
        """增加版本计数"""
        await db.execute(
            update(Mindmap)
            .where(Mindmap.id == mindmap_id)
            .values(version_count=Mindmap.version_count + 1)
        )
