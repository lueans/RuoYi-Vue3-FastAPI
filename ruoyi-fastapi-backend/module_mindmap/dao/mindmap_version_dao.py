"""脑图版本历史 DAO"""
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_mindmap.entity.do.mindmap_version_do import MindmapVersion
from utils.page_util import PageUtil


class MindmapVersionDao:
    """版本历史数据库操作层"""

    @classmethod
    async def get_version_list(
        cls, db: AsyncSession, mindmap_id: int, version_type: int | None = None,
        page_num: int = 1, page_size: int = 20,
    ) -> PageModel:
        """分页查询版本列表（不含 node_tree 大字段）"""
        query = (
            select(
                MindmapVersion.id,
                MindmapVersion.mindmap_id,
                MindmapVersion.version_number,
                MindmapVersion.version_type,
                MindmapVersion.name,
                MindmapVersion.layout,
                MindmapVersion.created_by,
                MindmapVersion.created_time,
            )
            .where(MindmapVersion.mindmap_id == mindmap_id)
        )

        if version_type is not None:
            query = query.where(MindmapVersion.version_type == version_type)

        query = query.order_by(MindmapVersion.created_time.desc())

        return await PageUtil.paginate(db, query, page_num, page_size, True)

    @classmethod
    async def get_version_by_id(cls, db: AsyncSession, version_id: int) -> MindmapVersion | None:
        """根据ID获取版本详情（含完整 node_tree）"""
        result = (await db.execute(
            select(MindmapVersion).where(MindmapVersion.id == version_id)
        )).scalars().first()
        return result

    @classmethod
    async def add_version(cls, db: AsyncSession, data: dict) -> MindmapVersion:
        """新增版本记录"""
        version = MindmapVersion(**data)
        db.add(version)
        await db.flush()
        return version

    @classmethod
    async def delete_version(cls, db: AsyncSession, version_id: int) -> None:
        """删除指定版本"""
        await db.execute(
            delete(MindmapVersion).where(MindmapVersion.id == version_id)
        )

    @classmethod
    async def get_draft_count(cls, db: AsyncSession, mindmap_id: int) -> int:
        """获取草稿版本数量"""
        result = (await db.execute(
            select(func.count())
            .select_from(MindmapVersion)
            .where(
                MindmapVersion.mindmap_id == mindmap_id,
                MindmapVersion.version_type == 0,
            )
        )).scalar_one()
        return result

    @classmethod
    async def delete_old_drafts(
        cls, db: AsyncSession, mindmap_id: int, keep_count: int = 10,
    ) -> None:
        """删除超出保留数量的旧草稿版本"""
        # 找到要保留的最旧的草稿版本 ID（按时间倒序，保留前 keep_count 个）
        keep_ids_subquery = (
            select(MindmapVersion.id)
            .where(
                MindmapVersion.mindmap_id == mindmap_id,
                MindmapVersion.version_type == 0,
            )
            .order_by(MindmapVersion.created_time.desc())
            .limit(keep_count)
            .subquery()
        )

        # 删除不在保留列表中的草稿版本
        await db.execute(
            delete(MindmapVersion).where(
                MindmapVersion.mindmap_id == mindmap_id,
                MindmapVersion.version_type == 0,
                MindmapVersion.id.not_in(select(keep_ids_subquery)),
            )
        )

    @classmethod
    async def get_next_version_number(cls, db: AsyncSession, mindmap_id: int) -> int:
        """获取下一个版本号"""
        max_num = (await db.execute(
            select(func.max(MindmapVersion.version_number))
            .where(MindmapVersion.mindmap_id == mindmap_id)
        )).scalar_one_or_none()
        return (max_num or 0) + 1
