"""脑图分享链接 DAO"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_share_do import MindmapShare


class MindmapShareDao:
    """分享链接数据库操作层"""

    @classmethod
    async def get_shares_by_mindmap_id(cls, db: AsyncSession, mindmap_id: int) -> list[MindmapShare]:
        """获取脑图的所有分享链接"""
        result = (await db.execute(
            select(MindmapShare)
            .where(MindmapShare.mindmap_id == mindmap_id)
            .order_by(MindmapShare.created_time.desc())
        )).scalars().all()
        return list(result)

    @classmethod
    async def get_share_by_token(cls, db: AsyncSession, share_token: str) -> MindmapShare | None:
        """根据 token 获取分享链接"""
        result = (await db.execute(
            select(MindmapShare).where(MindmapShare.share_token == share_token)
        )).scalars().first()
        return result

    @classmethod
    async def get_share_by_id(cls, db: AsyncSession, share_id: int) -> MindmapShare | None:
        """根据 ID 获取分享链接"""
        result = (await db.execute(
            select(MindmapShare).where(MindmapShare.id == share_id)
        )).scalars().first()
        return result

    @classmethod
    async def add_share(cls, db: AsyncSession, data: dict) -> MindmapShare:
        """新增分享链接"""
        share = MindmapShare(**data)
        db.add(share)
        await db.flush()
        return share

    @classmethod
    async def deactivate_share(cls, db: AsyncSession, share_id: int) -> None:
        """禁用分享链接"""
        await db.execute(
            update(MindmapShare)
            .where(MindmapShare.id == share_id)
            .values(is_active=0)
        )
