"""脑图协作者 DAO"""
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator


class MindmapCollaboratorDao:
    """协作者数据库操作层"""

    @classmethod
    async def get_collaborators_by_mindmap(cls, db: AsyncSession, mindmap_id: int) -> list[MindmapCollaborator]:
        """获取脑图的所有协作者"""
        result = (await db.execute(
            select(MindmapCollaborator)
            .where(MindmapCollaborator.mindmap_id == mindmap_id)
            .order_by(MindmapCollaborator.created_time.desc())
        )).scalars().all()
        return list(result)

    @classmethod
    async def get_collaborator_by_id(cls, db: AsyncSession, collab_id: int) -> MindmapCollaborator | None:
        """根据 ID 获取协作者记录"""
        result = (await db.execute(
            select(MindmapCollaborator).where(MindmapCollaborator.id == collab_id)
        )).scalars().first()
        return result

    @classmethod
    async def get_collaborator_permission(
        cls, db: AsyncSession, mindmap_id: int, user_id: int,
    ) -> int | None:
        """获取用户对某脑图的协作者权限，返回 permission 值或 None（不是协作者）"""
        result = (await db.execute(
            select(MindmapCollaborator.permission)
            .where(
                MindmapCollaborator.mindmap_id == mindmap_id,
                MindmapCollaborator.user_id == user_id,
            )
        )).scalar_one_or_none()
        return result

    @classmethod
    async def check_exists(cls, db: AsyncSession, mindmap_id: int, user_id: int) -> bool:
        """检查协作者是否已存在"""
        result = (await db.execute(
            select(MindmapCollaborator.id)
            .where(
                MindmapCollaborator.mindmap_id == mindmap_id,
                MindmapCollaborator.user_id == user_id,
            )
        )).scalar_one_or_none()
        return result is not None

    @classmethod
    async def add_collaborator(cls, db: AsyncSession, data: dict) -> MindmapCollaborator:
        """新增协作者"""
        collab = MindmapCollaborator(**data)
        db.add(collab)
        await db.flush()
        return collab

    @classmethod
    async def update_permission(cls, db: AsyncSession, collab_id: int, permission: int) -> None:
        """修改协作者权限"""
        await db.execute(
            update(MindmapCollaborator)
            .where(MindmapCollaborator.id == collab_id)
            .values(permission=permission)
        )

    @classmethod
    async def remove_collaborator(cls, db: AsyncSession, collab_id: int) -> None:
        """移除协作者"""
        await db.execute(
            delete(MindmapCollaborator).where(MindmapCollaborator.id == collab_id)
        )
