"""脑图协作者 DAO"""
from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from module_admin.entity.do.user_do import SysUser
from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator


class MindmapCollaboratorDao:
    """协作者数据库操作层"""

    @classmethod
    async def get_collaborators_by_mindmap(cls, db: AsyncSession, mindmap_id: int) -> list[Row]:
        """获取脑图协作者及其可展示的用户身份字段。"""
        result = (
            await db.execute(
                select(
                    MindmapCollaborator.id,
                    MindmapCollaborator.mindmap_id,
                    MindmapCollaborator.user_id,
                    MindmapCollaborator.permission,
                    MindmapCollaborator.created_by,
                    MindmapCollaborator.created_time,
                    SysUser.user_name,
                    SysUser.nick_name,
                    SysUser.avatar,
                )
                .join(SysUser, SysUser.user_id == MindmapCollaborator.user_id)
                .where(
                    MindmapCollaborator.mindmap_id == mindmap_id,
                    SysUser.del_flag == '0',
                )
                .order_by(MindmapCollaborator.created_time.desc())
            )
        ).all()
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
    async def is_active_user(cls, db: AsyncSession, user_id: int) -> bool:
        """检查目标用户是否存在且仍可登录。"""
        result = (await db.execute(
            select(SysUser.user_id).where(
                SysUser.user_id == user_id,
                SysUser.status == '0',
                SysUser.del_flag == '0',
            )
        )).scalar_one_or_none()
        return result is not None

    @classmethod
    async def search_available_users(
        cls, db: AsyncSession, mindmap_id: int, owner_id: int, keyword: str,
    ) -> list[Row]:
        """搜索尚未加入当前脑图的活跃用户。"""
        escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        like_pattern = f'%{escaped}%'
        collaborator_user_ids = select(MindmapCollaborator.user_id).where(
            MindmapCollaborator.mindmap_id == mindmap_id,
        )
        result = (
            await db.execute(
                select(
                    SysUser.user_id,
                    SysUser.user_name,
                    SysUser.nick_name,
                    SysUser.avatar,
                ).where(
                    SysUser.status == '0',
                    SysUser.del_flag == '0',
                    SysUser.user_id != owner_id,
                    SysUser.user_id.not_in(collaborator_user_ids),
                    or_(
                        SysUser.user_name.ilike(like_pattern, escape='\\'),
                        SysUser.nick_name.ilike(like_pattern, escape='\\'),
                    ),
                ).order_by(SysUser.user_name.asc()).limit(20)
            )
        ).all()
        return list(result)

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
