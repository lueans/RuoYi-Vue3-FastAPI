from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_creation_do import MindmapCreationRequest


class MindmapCreationDao:
    """Persistence boundary for durable creation idempotency records."""

    @classmethod
    async def get_by_owner_and_request(
        cls,
        db: AsyncSession,
        owner_id: int,
        request_id: str,
    ) -> MindmapCreationRequest | None:
        return (await db.execute(
            select(MindmapCreationRequest).where(
                MindmapCreationRequest.owner_id == owner_id,
                MindmapCreationRequest.request_id == request_id,
            )
        )).scalars().first()

    @classmethod
    async def add_request(
        cls,
        db: AsyncSession,
        *,
        owner_id: int,
        request_id: str,
        operation: str,
        request_fingerprint: str,
        created_by: str | None,
    ) -> MindmapCreationRequest:
        record = MindmapCreationRequest(
            owner_id=owner_id,
            request_id=request_id,
            operation=operation,
            request_fingerprint=request_fingerprint,
            created_by=created_by,
            created_time=datetime.now(),
        )
        db.add(record)
        # The unique owner/request constraint is deliberately claimed before
        # any file or node writes, so concurrent duplicates have one winner.
        await db.flush()
        return record

    @classmethod
    async def complete_request(
        cls,
        db: AsyncSession,
        request_record_id: int,
        result_file_id: int,
    ) -> None:
        await db.execute(
            update(MindmapCreationRequest)
            .where(MindmapCreationRequest.id == request_record_id)
            .values(result_file_id=result_file_id, completed_time=datetime.now())
        )
