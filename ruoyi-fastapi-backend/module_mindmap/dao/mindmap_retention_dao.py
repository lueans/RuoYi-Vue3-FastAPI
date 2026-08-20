from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from module_mindmap.entity.do.mindmap_content_do import MindmapChangeLog
from module_mindmap.entity.do.mindmap_creation_do import MindmapCreationRequest
from module_mindmap.entity.do.mindmap_do import Mindmap


class MindmapRetentionDao:
    """Bounded retention queries; callers never load retained payload columns."""

    @staticmethod
    def creation_eligible_condition(cutoff: datetime) -> tuple[ColumnElement[bool], ...]:
        return (
            MindmapCreationRequest.completed_time.is_not(None),
            MindmapCreationRequest.completed_time < cutoff,
        )

    @staticmethod
    def change_eligible_condition(
        cutoff: datetime,
        keep_revisions: int,
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            MindmapChangeLog.created_time < cutoff,
            MindmapChangeLog.revision <= Mindmap.content_revision - keep_revisions,
        )

    @classmethod
    async def count_creation_candidates(cls, db: AsyncSession, cutoff: datetime) -> int:
        return int((await db.execute(
            select(func.count(MindmapCreationRequest.id)).where(
                *cls.creation_eligible_condition(cutoff),
            )
        )).scalar_one())

    @classmethod
    async def count_change_candidates(
        cls,
        db: AsyncSession,
        cutoff: datetime,
        keep_revisions: int,
    ) -> int:
        return int((await db.execute(
            select(func.count(MindmapChangeLog.id))
            .join(Mindmap, Mindmap.id == MindmapChangeLog.file_id)
            .where(*cls.change_eligible_condition(cutoff, keep_revisions))
        )).scalar_one())

    @classmethod
    async def list_creation_candidate_ids(
        cls,
        db: AsyncSession,
        cutoff: datetime,
        limit: int,
    ) -> list[int]:
        return list((await db.execute(
            select(MindmapCreationRequest.id)
            .where(*cls.creation_eligible_condition(cutoff))
            .order_by(MindmapCreationRequest.completed_time, MindmapCreationRequest.id)
            .limit(limit)
        )).scalars())

    @classmethod
    async def list_change_candidate_ids(
        cls,
        db: AsyncSession,
        cutoff: datetime,
        keep_revisions: int,
        limit: int,
    ) -> list[int]:
        return list((await db.execute(
            select(MindmapChangeLog.id)
            .join(Mindmap, Mindmap.id == MindmapChangeLog.file_id)
            .where(*cls.change_eligible_condition(cutoff, keep_revisions))
            .order_by(MindmapChangeLog.created_time, MindmapChangeLog.id)
            .limit(limit)
        )).scalars())

    @staticmethod
    async def delete_creation_candidates(db: AsyncSession, record_ids: list[int]) -> int:
        if not record_ids:
            return 0
        result = await db.execute(
            delete(MindmapCreationRequest).where(MindmapCreationRequest.id.in_(record_ids))
        )
        return int(result.rowcount or 0)

    @staticmethod
    async def delete_change_candidates(db: AsyncSession, record_ids: list[int]) -> int:
        if not record_ids:
            return 0
        result = await db.execute(
            delete(MindmapChangeLog).where(MindmapChangeLog.id.in_(record_ids))
        )
        return int(result.rowcount or 0)
