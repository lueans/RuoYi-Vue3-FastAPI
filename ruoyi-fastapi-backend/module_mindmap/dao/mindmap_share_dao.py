"""脑图分享链接 DAO"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_share_do import MindmapShare


@dataclass(frozen=True, slots=True)
class MindmapShareAccessSnapshot:
    """分享鉴权所需的纯标量快照，不依赖事务结束后的 ORM 状态。"""

    mindmap_id: int
    share_type: int
    expire_time: datetime | None
    created_by: int
    is_active: int


@dataclass(frozen=True, slots=True)
class MindmapShareListSnapshot:
    """分享列表响应所需的纯标量快照。"""

    id: int
    mindmap_id: int
    share_token: str
    share_type: int
    expire_time: datetime | None
    created_by: int
    created_time: datetime | None
    is_active: int


@dataclass(frozen=True, slots=True)
class MindmapOwnershipSnapshot:
    """分享管理权限校验所需的脑图标量。"""

    mindmap_id: int
    owner_id: int
    status: int


@dataclass(frozen=True, slots=True)
class SharedMindmapSnapshot:
    """公开分享响应所需的脑图元数据快照。"""

    mindmap_id: int
    name: str
    node_tree: Any
    layout: str
    theme: Any
    view_data: Any
    document_data: Any
    schema_version: int
    content_revision: int


class MindmapShareDao:
    """分享链接数据库操作层"""

    @classmethod
    async def get_shares_by_mindmap_id(
        cls,
        db: AsyncSession,
        mindmap_id: int,
    ) -> list[MindmapShareListSnapshot]:
        """获取脑图的所有分享链接标量，避免响应物化触发 ORM 隐式 IO。"""
        rows = (await db.execute(
            select(
                MindmapShare.id,
                MindmapShare.mindmap_id,
                MindmapShare.share_token,
                MindmapShare.share_type,
                MindmapShare.expire_time,
                MindmapShare.created_by,
                MindmapShare.created_time,
                MindmapShare.is_active,
            )
            .where(MindmapShare.mindmap_id == mindmap_id)
            .order_by(MindmapShare.created_time.desc())
        )).all()
        return [
            MindmapShareListSnapshot(
                id=int(row.id),
                mindmap_id=int(row.mindmap_id),
                share_token=str(row.share_token),
                share_type=int(row.share_type),
                expire_time=row.expire_time,
                created_by=int(row.created_by),
                created_time=row.created_time,
                is_active=int(row.is_active),
            )
            for row in rows
        ]

    @classmethod
    async def get_share_by_token(
        cls,
        db: AsyncSession,
        share_token: str,
        *,
        for_update: bool = False,
    ) -> MindmapShareAccessSnapshot | None:
        """兼容旧调用，返回不依赖 ORM 生命周期的分享鉴权快照。"""
        return await cls.get_share_access_snapshot(
            db,
            share_token,
            for_update=for_update,
        )

    @classmethod
    async def get_share_access_snapshot(
        cls,
        db: AsyncSession,
        share_token: str,
        *,
        for_update: bool = False,
        for_share: bool = False,
    ) -> MindmapShareAccessSnapshot | None:
        """读取分享鉴权标量；公开读取和领取邀请可选择对应行锁。"""
        if for_update and for_share:
            raise ValueError('分享记录不能同时申请共享锁和排他锁')
        statement = select(
            MindmapShare.mindmap_id,
            MindmapShare.share_type,
            MindmapShare.expire_time,
            MindmapShare.created_by,
            MindmapShare.is_active,
        ).where(MindmapShare.share_token == share_token)
        if for_update:
            statement = statement.with_for_update()
        elif for_share:
            statement = statement.with_for_update(read=True)
        row = (await db.execute(statement)).one_or_none()
        if row is None:
            return None
        return MindmapShareAccessSnapshot(
            mindmap_id=int(row.mindmap_id),
            share_type=int(row.share_type),
            expire_time=row.expire_time,
            created_by=int(row.created_by),
            is_active=int(row.is_active),
        )

    @classmethod
    async def get_shared_mindmap_snapshot(
        cls,
        db: AsyncSession,
        mindmap_id: int,
        *,
        for_share: bool = False,
    ) -> SharedMindmapSnapshot | None:
        """读取分享响应字段；共享锁用于阻止正文保存跨查询切换 revision。"""
        statement = select(
            Mindmap.id.label('mindmap_id'),
            Mindmap.name,
            Mindmap.node_tree,
            Mindmap.layout,
            Mindmap.theme,
            Mindmap.view_data,
            Mindmap.document_data,
            Mindmap.schema_version,
            Mindmap.content_revision,
        ).where(
            Mindmap.id == mindmap_id,
            Mindmap.del_flag == '0',
        )
        if for_share:
            statement = statement.with_for_update(read=True)
        row = (await db.execute(statement)).one_or_none()
        if row is None:
            return None
        return SharedMindmapSnapshot(
            mindmap_id=int(row.mindmap_id),
            name=str(row.name),
            node_tree=row.node_tree,
            layout=str(row.layout),
            theme=row.theme,
            view_data=row.view_data,
            document_data=row.document_data,
            schema_version=int(row.schema_version or 1),
            content_revision=int(row.content_revision),
        )

    @classmethod
    async def get_mindmap_ownership_snapshot(
        cls,
        db: AsyncSession,
        mindmap_id: int,
        *,
        for_update: bool = False,
    ) -> MindmapOwnershipSnapshot | None:
        """读取分享管理所需的脑图字段，可选择锁定主记录。"""
        statement = select(
            Mindmap.id.label('mindmap_id'),
            Mindmap.owner_id,
            Mindmap.status,
        ).where(
            Mindmap.id == mindmap_id,
            Mindmap.del_flag == '0',
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await db.execute(statement)).one_or_none()
        if row is None:
            return None
        return MindmapOwnershipSnapshot(
            mindmap_id=int(row.mindmap_id),
            owner_id=int(row.owner_id),
            status=int(row.status),
        )

    @classmethod
    async def get_share_by_id(
        cls,
        db: AsyncSession,
        share_id: int,
    ) -> MindmapShareAccessSnapshot | None:
        """根据 ID 获取分享链接鉴权标量。"""
        row = (await db.execute(select(
            MindmapShare.mindmap_id,
            MindmapShare.share_type,
            MindmapShare.expire_time,
            MindmapShare.created_by,
            MindmapShare.is_active,
        ).where(MindmapShare.id == share_id))).one_or_none()
        if row is None:
            return None
        return MindmapShareAccessSnapshot(
            mindmap_id=int(row.mindmap_id),
            share_type=int(row.share_type),
            expire_time=row.expire_time,
            created_by=int(row.created_by),
            is_active=int(row.is_active),
        )

    @classmethod
    async def add_share(cls, db: AsyncSession, data: dict) -> None:
        """新增分享链接，不向服务层暴露 ORM 实例。"""
        await db.execute(insert(MindmapShare).values(**data))

    @classmethod
    async def deactivate_share(cls, db: AsyncSession, share_id: int) -> None:
        """禁用分享链接"""
        await db.execute(
            update(MindmapShare)
            .where(MindmapShare.id == share_id)
            .values(is_active=0)
        )
