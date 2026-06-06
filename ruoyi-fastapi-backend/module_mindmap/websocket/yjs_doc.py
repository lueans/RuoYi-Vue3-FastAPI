"""Yjs 文档持久化管理"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_ws_state_do import MindmapWsState


class YjsDocManager:
    """Yjs 文档的数据库持久化"""

    @classmethod
    async def load_state(cls, db: AsyncSession, mindmap_id: int) -> bytes | None:
        """从数据库加载 Yjs 文档状态"""
        result = (await db.execute(
            select(MindmapWsState.yjs_state)
            .where(MindmapWsState.mindmap_id == mindmap_id)
        )).scalar_one_or_none()
        return result

    @classmethod
    async def save_state(cls, db: AsyncSession, mindmap_id: int, state: bytes) -> None:
        """保存 Yjs 文档状态到数据库（upsert）"""
        existing = (await db.execute(
            select(MindmapWsState).where(MindmapWsState.mindmap_id == mindmap_id)
        )).scalar_one_or_none()

        if existing:
            await db.execute(
                update(MindmapWsState)
                .where(MindmapWsState.mindmap_id == mindmap_id)
                .values(yjs_state=state)
            )
        else:
            db.add(MindmapWsState(mindmap_id=mindmap_id, yjs_state=state))
        await db.commit()
