"""AI 脑图持久化边界。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import aliased

from module_mindmap.entity.do.mindmap_ai_do import (
    MINDMAP_AI_EVENT_SEQUENCE_MAX,
    MindmapAiArtifact,
    MindmapAiConnector,
    MindmapAiDraftCheckpoint,
    MindmapAiJob,
    MindmapAiJobEvent,
    MindmapAiProposal,
    MindmapAiResponse,
    MindmapAiSession,
    MindmapAiUndo,
)

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

_Record = TypeVar('_Record')

MINDMAP_AI_EVENT_TYPE_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
MINDMAP_AI_INACTIVE_EVENT_STATUSES = frozenset({
    'cancel_requested', 'ready', 'applied', 'undone', 'completed_file',
    'completed_no_change', 'completed_direct', 'needs_review', 'stale', 'cancelled', 'failed', 'expired',
    'needs_input', 'completed_message', 'rejected',
})
MINDMAP_AI_POST_TRANSITION_EVENT_TYPES = frozenset({
    'status_changed', 'cancel_requested', 'artifact_ready', 'artifact_needs_review',
    'artifact_no_change', 'local_applied', 'local_undone', 'cloud_file_created',
    'cloud_applied', 'cloud_undone', 'proposal_stale', 'proposal_rejected',
    'needs_input',
    'message_ready',
    'direct_completed',
})


async def _select_first(
    db: AsyncSession, query: Select[tuple[_Record]], *, for_update: bool = False,
) -> _Record | None:
    """Execute an already-scoped single-record read, refreshing locked ORM rows."""
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(query)).scalars().first()


class MindmapAiDao:
    @classmethod
    async def list_connectors(cls, db: AsyncSession) -> list[MindmapAiConnector]:
        return list((await db.execute(
            select(MindmapAiConnector).order_by(MindmapAiConnector.agent_key.asc())
        )).scalars())

    @classmethod
    async def get_connector(
        cls,
        db: AsyncSession,
        agent_key: str,
        *,
        for_update: bool = False,
    ) -> MindmapAiConnector | None:
        query = select(MindmapAiConnector).where(MindmapAiConnector.agent_key == agent_key)
        return await _select_first(db, query, for_update=for_update)

    @classmethod
    async def add_connector(cls, db: AsyncSession, values: dict[str, Any]) -> MindmapAiConnector:
        connector = MindmapAiConnector(**values)
        db.add(connector)
        await db.flush()
        return connector

    @classmethod
    async def update_connector(
        cls,
        db: AsyncSession,
        agent_key: str,
        values: dict[str, Any],
    ) -> None:
        await db.execute(
            update(MindmapAiConnector)
            .where(MindmapAiConnector.agent_key == agent_key)
            .values(**values, update_time=datetime.now())
        )

    @classmethod
    async def add_session(cls, db: AsyncSession, values: dict[str, Any]) -> MindmapAiSession:
        session = MindmapAiSession(**values)
        db.add(session)
        await db.flush()
        return session

    @classmethod
    async def get_session(
        cls,
        db: AsyncSession,
        session_id: str,
        user_id: int | None = None,
        *,
        for_update: bool = False,
    ) -> MindmapAiSession | None:
        query = select(MindmapAiSession).where(MindmapAiSession.id == session_id)
        if user_id is not None:
            query = query.where(MindmapAiSession.user_id == user_id)
        return await _select_first(db, query, for_update=for_update)

    @classmethod
    async def list_sessions(
        cls,
        db: AsyncSession,
        user_id: int,
        *,
        page: int,
        limit: int,
    ) -> tuple[list[MindmapAiSession], int]:
        safe_page = max(int(page), 1)
        safe_limit = min(max(int(limit), 1), 100)
        total = int(await db.scalar(
            select(func.count(MindmapAiSession.id)).where(
                MindmapAiSession.user_id == user_id,
            )
        ) or 0)
        sessions = list((await db.execute(
            select(MindmapAiSession)
            .where(MindmapAiSession.user_id == user_id)
            .order_by(MindmapAiSession.update_time.desc(), MindmapAiSession.id.desc())
            .offset((safe_page - 1) * safe_limit)
            .limit(safe_limit)
        )).scalars())
        return sessions, total

    @classmethod
    async def list_latest_jobs_for_sessions(
        cls,
        db: AsyncSession,
        session_ids: list[str],
    ) -> dict[str, MindmapAiJob]:
        if not session_ids:
            return {}
        jobs = list((await db.execute(
            select(MindmapAiJob)
            .where(MindmapAiJob.session_id.in_(session_ids))
            .order_by(
                MindmapAiJob.session_id.asc(),
                MindmapAiJob.turn_index.desc(),
                MindmapAiJob.created_time.desc(),
            )
        )).scalars())
        latest: dict[str, MindmapAiJob] = {}
        active_statuses = {
            'queued', 'preparing', 'running', 'validating', 'cancel_requested',
        }
        waiting_status = 'waiting_turn'
        grouped: dict[str, list[MindmapAiJob]] = {}
        for job in jobs:
            grouped.setdefault(str(job.session_id), []).append(job)
        for session_id, session_jobs in grouped.items():
            # The latest turn is not always the turn currently executing: a
            # later message can wait in the durable queue while its parent is
            # still streaming. Surface the execution head so the task center
            # opens on the live progress instead of a silent waiting card.
            pending_jobs = [
                job for job in session_jobs
                if job.status in active_statuses or job.status == waiting_status
            ]
            latest[session_id] = min(
                pending_jobs,
                key=lambda job: (
                    job.status == waiting_status,
                    int(job.turn_index or 0),
                    job.created_time,
                    str(job.id),
                ),
            ) if pending_jobs else session_jobs[0]
        return latest

    @classmethod
    async def count_turns_for_sessions(
        cls,
        db: AsyncSession,
        session_ids: list[str],
    ) -> dict[str, int]:
        if not session_ids:
            return {}
        rows = (await db.execute(
            select(MindmapAiJob.session_id, func.count(MindmapAiJob.id))
            .where(MindmapAiJob.session_id.in_(session_ids))
            .group_by(MindmapAiJob.session_id)
        )).all()
        return {str(session_id): int(count) for session_id, count in rows}

    @classmethod
    async def list_jobs_for_session(
        cls,
        db: AsyncSession,
        session_id: str,
        *,
        for_update: bool = False,
    ) -> list[MindmapAiJob]:
        query = (
            select(MindmapAiJob)
            .where(MindmapAiJob.session_id == session_id)
            .order_by(MindmapAiJob.turn_index.asc(), MindmapAiJob.created_time.asc())
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return list((await db.execute(query)).scalars())

    @classmethod
    async def list_waiting_followups(
        cls,
        db: AsyncSession,
        parent_job_id: str,
        *,
        for_update: bool = False,
    ) -> list[MindmapAiJob]:
        query = select(MindmapAiJob).where(
            MindmapAiJob.parent_job_id == parent_job_id,
            MindmapAiJob.status == 'waiting_turn',
        ).order_by(MindmapAiJob.turn_index.asc(), MindmapAiJob.id.asc())
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return list((await db.execute(query)).scalars())

    @classmethod
    async def list_waiting_jobs(
        cls,
        db: AsyncSession,
        *,
        limit: int = 2_000,
    ) -> list[MindmapAiJob]:
        safe_limit = min(max(int(limit), 1), 10_000)
        return list((await db.execute(
            select(MindmapAiJob)
            .where(MindmapAiJob.status == 'waiting_turn')
            .order_by(MindmapAiJob.created_time.asc(), MindmapAiJob.id.asc())
            .limit(safe_limit)
        )).scalars())

    @classmethod
    async def lock_jobs_for_session(
        cls,
        db: AsyncSession,
        session_id: str,
    ) -> list[MindmapAiJob]:
        """Lock every session job in one globally stable row order."""
        query = (
            select(MindmapAiJob)
            .where(MindmapAiJob.session_id == session_id)
            .order_by(MindmapAiJob.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list((await db.execute(query)).scalars())

    @classmethod
    async def update_session(
        cls,
        db: AsyncSession,
        session_id: str,
        values: dict[str, Any],
    ) -> None:
        await db.execute(
            update(MindmapAiSession)
            .where(MindmapAiSession.id == session_id)
            .values(**values, update_time=datetime.now())
        )

    @classmethod
    async def add_job(cls, db: AsyncSession, values: dict[str, Any]) -> MindmapAiJob:
        job = MindmapAiJob(**values)
        db.add(job)
        await db.flush()
        return job

    @classmethod
    async def get_job(
        cls,
        db: AsyncSession,
        job_id: str,
        user_id: int | None = None,
        *,
        for_update: bool = False,
    ) -> MindmapAiJob | None:
        query = select(MindmapAiJob).where(MindmapAiJob.id == job_id)
        if user_id is not None:
            query = query.where(MindmapAiJob.user_id == user_id)
        return await _select_first(db, query, for_update=for_update)

    @classmethod
    async def get_job_by_idempotency(
        cls,
        db: AsyncSession,
        user_id: int,
        idempotency_key: str,
    ) -> MindmapAiJob | None:
        return (await db.execute(select(MindmapAiJob).where(
            MindmapAiJob.user_id == user_id,
            MindmapAiJob.idempotency_key == idempotency_key,
        ))).scalars().first()

    @classmethod
    async def list_recoverable_jobs(
        cls,
        db: AsyncSession,
        *,
        stale_before: datetime,
        after_created_time: datetime | None = None,
        after_id: str | None = None,
        limit: int = 200,
    ) -> list[MindmapAiJob]:
        """按稳定游标分页读取可接管任务，避免固定条数导致任务永久遗漏。"""
        safe_limit = min(max(int(limit), 1), 2_000)
        query = select(MindmapAiJob).where(or_(
            MindmapAiJob.status.in_(('queued', 'cancel_requested')),
            and_(
                MindmapAiJob.status.in_(('preparing', 'running', 'validating')),
                MindmapAiJob.update_time <= stale_before,
            ),
        ))
        if after_created_time is not None and after_id is not None:
            query = query.where(or_(
                MindmapAiJob.created_time > after_created_time,
                and_(
                    MindmapAiJob.created_time == after_created_time,
                    MindmapAiJob.id > after_id,
                ),
            ))
        return list((await db.execute(
            query
            .order_by(MindmapAiJob.created_time.asc(), MindmapAiJob.id.asc())
            .limit(safe_limit)
        )).scalars())

    @classmethod
    async def touch_active_job(
        cls,
        db: AsyncSession,
        job_id: str,
        expected_execution_epoch: int,
    ) -> bool:
        """刷新执行心跳；终态和取消态不会被迟到的 worker 触碰。"""
        conditions = [
            MindmapAiJob.id == job_id,
            MindmapAiJob.status.in_(('queued', 'preparing', 'running', 'validating')),
            MindmapAiJob.execution_epoch == expected_execution_epoch,
        ]
        result = await db.execute(
            update(MindmapAiJob)
            .where(*conditions)
            .values(update_time=datetime.now())
        )
        return int(result.rowcount or 0) == 1

    @classmethod
    async def count_active_jobs(cls, db: AsyncSession, agent_key: str) -> int:
        active_statuses = ('queued', 'preparing', 'running', 'validating', 'cancel_requested')
        value = await db.scalar(
            select(func.count(MindmapAiJob.id)).where(
                MindmapAiJob.agent_key == agent_key,
                MindmapAiJob.status.in_(active_statuses),
            )
        )
        return int(value or 0)

    @classmethod
    async def request_session_job_cancellations(
        cls,
        db: AsyncSession,
        session_id: str,
        requested_time: datetime,
    ) -> int:
        """Persist cancellation for every non-terminal job owned by one session."""
        result = await db.execute(
            update(MindmapAiJob)
            .where(
                MindmapAiJob.session_id == session_id,
                MindmapAiJob.status.in_((
                    'queued',
                    'preparing',
                    'running',
                    'validating',
                    'cancel_requested',
                    'waiting_turn',
                )),
            )
            .values(
                status='cancel_requested',
                cancel_requested_time=func.coalesce(
                    MindmapAiJob.cancel_requested_time,
                    requested_time,
                ),
                update_time=requested_time,
            )
        )
        return int(result.rowcount or 0)

    @classmethod
    async def update_job(cls, db: AsyncSession, job_id: str, values: dict[str, Any]) -> None:
        await db.execute(
            update(MindmapAiJob)
            .where(MindmapAiJob.id == job_id)
            .values(**values, update_time=datetime.now())
        )

    @classmethod
    async def transition_job_status(
        cls,
        db: AsyncSession,
        job_id: str,
        from_statuses: set[str] | frozenset[str],
        values: dict[str, Any],
    ) -> bool:
        """用数据库条件更新收口跨 worker 状态竞态，任何终态都不能被迟到任务覆盖。"""
        if not from_statuses or 'status' not in values:
            return False
        result = await db.execute(
            update(MindmapAiJob)
            .where(
                MindmapAiJob.id == job_id,
                MindmapAiJob.status.in_(tuple(from_statuses)),
            )
            .values(**values, update_time=datetime.now())
        )
        return int(result.rowcount or 0) == 1

    @classmethod
    async def extend_result_expiration(
        cls,
        db: AsyncSession,
        *,
        job_id: str,
        artifact_id: str,
        expires_time: datetime,
        proposal_id: str | None = None,
    ) -> None:
        session_id = await db.scalar(
            select(MindmapAiJob.session_id).where(MindmapAiJob.id == job_id)
        )
        await db.execute(
            update(MindmapAiJob)
            .where(MindmapAiJob.id == job_id)
            .values(expires_time=expires_time, update_time=datetime.now())
        )
        await db.execute(
            update(MindmapAiArtifact)
            .where(MindmapAiArtifact.id == artifact_id)
            .values(expires_time=expires_time)
        )
        if proposal_id:
            await db.execute(
                update(MindmapAiProposal)
                .where(MindmapAiProposal.id == proposal_id)
                .values(expires_time=expires_time)
            )
        if session_id:
            await db.execute(
                update(MindmapAiSession)
                .where(
                    MindmapAiSession.id == session_id,
                    MindmapAiSession.expires_time < expires_time,
                )
                .values(expires_time=expires_time, update_time=datetime.now())
            )

    @classmethod
    async def add_event(
        cls,
        db: AsyncSession,
        job_id: str,
        event_type: str,
        payload_json: str,
    ) -> MindmapAiJobEvent | None:
        # 同一任务可能同时收到 Adapter 进度与取消请求。先锁任务行，确保
        # MAX(sequence)+1 在 MySQL/PostgreSQL 中串行化且事件可稳定重放。
        locked_job_status = (await db.execute(
            select(MindmapAiJob.status)
            .where(MindmapAiJob.id == job_id)
            .with_for_update()
        )).scalar_one_or_none()
        # 会话删除可能与 Adapter 的迟到回调并发。任务行已经删除时不能再
        # 插入没有父任务的孤儿事件。
        if locked_job_status is None:
            return None
        if (
            locked_job_status in MINDMAP_AI_INACTIVE_EVENT_STATUSES
            and event_type not in MINDMAP_AI_POST_TRANSITION_EVENT_TYPES
        ):
            return None
        latest = await db.scalar(
            select(func.max(MindmapAiJobEvent.sequence)).where(MindmapAiJobEvent.job_id == job_id)
        )
        next_sequence = int(latest or 0) + 1
        if next_sequence > MINDMAP_AI_EVENT_SEQUENCE_MAX:
            raise OverflowError('AI 脑图任务事件序号已达到数据库上限')
        safe_event_type = (
            event_type
            if MINDMAP_AI_EVENT_TYPE_PATTERN.fullmatch(event_type or '')
            else 'agent_event'
        )
        event = MindmapAiJobEvent(
            job_id=job_id,
            sequence=next_sequence,
            event_type=safe_event_type,
            payload_json=payload_json,
            created_time=datetime.now(),
        )
        db.add(event)
        await db.flush()
        return event

    @classmethod
    async def list_events(
        cls,
        db: AsyncSession,
        job_id: str,
        after_sequence: int,
        limit: int = 100,
    ) -> list[MindmapAiJobEvent]:
        safe_after_sequence = min(
            max(int(after_sequence), 0),
            MINDMAP_AI_EVENT_SEQUENCE_MAX,
        )
        safe_limit = min(max(int(limit), 0), 1_000)
        if safe_limit == 0:
            return []
        return list((await db.execute(
            select(MindmapAiJobEvent)
            .where(
                MindmapAiJobEvent.job_id == job_id,
                MindmapAiJobEvent.sequence > safe_after_sequence,
            )
            .order_by(MindmapAiJobEvent.sequence.asc())
            .limit(safe_limit)
        )).scalars())

    @classmethod
    async def list_draft_event_payloads(
        cls,
        db: AsyncSession,
        job_id: str,
    ) -> list[str]:
        """读取草稿事件元数据，供恢复时计算历史最大版本。"""
        return list((await db.execute(
            select(MindmapAiJobEvent.payload_json)
            .where(
                MindmapAiJobEvent.job_id == job_id,
                MindmapAiJobEvent.event_type.in_(('draft_initialized', 'draft_changed')),
            )
            .order_by(MindmapAiJobEvent.sequence.asc())
        )).scalars())

    @classmethod
    async def get_draft_checkpoint(
        cls,
        db: AsyncSession,
        job_id: str,
        *,
        for_update: bool = False,
    ) -> MindmapAiDraftCheckpoint | None:
        query = select(MindmapAiDraftCheckpoint).where(
            MindmapAiDraftCheckpoint.job_id == job_id,
        )
        return await _select_first(db, query, for_update=for_update)

    @classmethod
    async def upsert_draft_checkpoint(
        cls,
        db: AsyncSession,
        values: dict[str, Any],
    ) -> tuple[MindmapAiDraftCheckpoint, bool]:
        """Write the latest checkpoint while the caller holds the job row lock.

        Avoid dialect-specific UPSERT syntax so MySQL and PostgreSQL use the
        same transaction semantics. A late frame cannot replace a newer one.
        """
        job_id = str(values['job_id'])
        checkpoint = await cls.get_draft_checkpoint(db, job_id, for_update=True)
        if checkpoint is None:
            checkpoint = MindmapAiDraftCheckpoint(**values)
            db.add(checkpoint)
            await db.flush()
            return checkpoint, True
        incoming = (int(values['preview_epoch']), int(values['preview_version']))
        current = (int(checkpoint.preview_epoch), int(checkpoint.preview_version))
        if incoming < current:
            return checkpoint, False
        if incoming == current:
            if str(checkpoint.document_hash) != str(values['document_hash']):
                raise ValueError('AI 草稿检查点坐标冲突')
            return checkpoint, False
        for key, value in values.items():
            if key not in {'job_id', 'created_time'}:
                setattr(checkpoint, key, value)
        checkpoint.update_time = datetime.now()
        await db.flush()
        return checkpoint, True

    @classmethod
    async def delete_draft_checkpoint(cls, db: AsyncSession, job_id: str) -> int:
        result = await db.execute(
            delete(MindmapAiDraftCheckpoint).where(
                MindmapAiDraftCheckpoint.job_id == job_id,
            )
        )
        return int(result.rowcount or 0)

    @classmethod
    async def list_expired_job_metadata(
        cls,
        db: AsyncSession,
        now: datetime,
        terminal_statuses: set[str] | frozenset[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = (await db.execute(
            select(
                MindmapAiJob.id,
                MindmapAiJob.session_id,
                MindmapAiJob.status,
                MindmapAiJob.agent_key,
                MindmapAiJob.external_session_ref,
                MindmapAiJob.execution_epoch,
            )
            .where(
                MindmapAiJob.expires_time <= now,
                MindmapAiJob.status.in_(tuple(terminal_statuses)),
            )
            .order_by(MindmapAiJob.expires_time.asc(), MindmapAiJob.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )).all()
        return [
            {
                'id': str(row.id),
                'sessionId': str(row.session_id),
                'status': str(row.status),
                'agentKey': str(row.agent_key),
                'externalSessionRef': row.external_session_ref,
                'executionEpoch': int(row.execution_epoch or 0),
            }
            for row in rows
        ]

    @classmethod
    async def list_other_external_session_references(
        cls,
        db: AsyncSession,
        agent_keys: set[str],
        excluded_job_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Return direct and inherited references surviving this retention batch.

        A running follow-up initially has no reference of its own: it resumes the
        session stored on its parent and only persists the returned reference at
        completion. Include that inherited reference so retention cannot purge
        the parent session during this window.
        """
        if not agent_keys:
            return []
        surviving_job = aliased(MindmapAiJob, name='surviving_job')
        parent_job = aliased(MindmapAiJob, name='parent_job')
        query = (
            select(
                surviving_job.id,
                surviving_job.agent_key,
                surviving_job.external_session_ref,
                parent_job.external_session_ref.label('parent_external_session_ref'),
            )
            .outerjoin(
                parent_job,
                and_(
                    surviving_job.parent_job_id == parent_job.id,
                    surviving_job.agent_key == parent_job.agent_key,
                ),
            )
            .where(
                surviving_job.agent_key.in_(tuple(sorted(agent_keys))),
                or_(
                    surviving_job.external_session_ref.is_not(None),
                    parent_job.external_session_ref.is_not(None),
                ),
            )
        )
        if excluded_job_ids:
            query = query.where(surviving_job.id.not_in(excluded_job_ids))
        rows = (await db.execute(query.order_by(surviving_job.id.asc()))).all()
        return [
            {
                'id': str(row.id),
                'agentKey': str(row.agent_key),
                'externalSessionRef': row.external_session_ref,
                'parentExternalSessionRef': row.parent_external_session_ref,
            }
            for row in rows
        ]

    @classmethod
    async def scrub_expired_jobs(
        cls,
        db: AsyncSession,
        job_ids: list[str],
        purge_time: datetime,
    ) -> int:
        if not job_ids:
            return 0
        await db.execute(
            update(MindmapAiArtifact)
            .where(MindmapAiArtifact.job_id.in_(job_ids))
            .values(content_json='{}', title='已过期 AI 脑图', expires_time=purge_time)
        )
        await db.execute(
            update(MindmapAiProposal)
            .where(MindmapAiProposal.job_id.in_(job_ids))
            .values(
                scope_json=None,
                operations_json='[]',
                impact_json='{}',
                warnings_json='[]',
                status='expired',
                expires_time=purge_time,
            )
        )
        result = await db.execute(
            update(MindmapAiJob)
            .where(MindmapAiJob.id.in_(job_ids))
            .values(
                request_json='{}',
                external_session_ref=None,
                title=None,
                error_message=None,
                status='expired',
                progress=100,
                expires_time=purge_time,
                update_time=datetime.now(),
            )
        )
        return int(result.rowcount or 0)

    @classmethod
    async def delete_job_payloads(cls, db: AsyncSession, job_ids: list[str]) -> dict[str, int]:
        if not job_ids:
            return {
                'events': 0, 'checkpoints': 0, 'undos': 0, 'proposals': 0,
                'artifacts': 0, 'responses': 0, 'jobs': 0,
            }
        # 与 add_event 使用同一任务行锁。无论迟到事件还是删除先拿到锁，
        # 最终都不会留下 job 已删除但 event 后插入的孤儿记录。
        list((await db.execute(
            select(MindmapAiJob.id)
            .where(MindmapAiJob.id.in_(job_ids))
            .order_by(MindmapAiJob.id.asc())
            .with_for_update()
        )).scalars())
        history_counts = await cls.delete_events_and_undos_for_jobs(db, job_ids)
        proposal_result = await db.execute(
            delete(MindmapAiProposal).where(MindmapAiProposal.job_id.in_(job_ids))
        )
        artifact_result = await db.execute(
            delete(MindmapAiArtifact).where(MindmapAiArtifact.job_id.in_(job_ids))
        )
        response_result = await db.execute(
            delete(MindmapAiResponse).where(MindmapAiResponse.job_id.in_(job_ids))
        )
        job_result = await db.execute(delete(MindmapAiJob).where(MindmapAiJob.id.in_(job_ids)))
        return {
            **history_counts,
            'proposals': int(proposal_result.rowcount or 0),
            'artifacts': int(artifact_result.rowcount or 0),
            'responses': int(response_result.rowcount or 0),
            'jobs': int(job_result.rowcount or 0),
        }

    @classmethod
    async def delete_events_and_undos_for_jobs(
        cls,
        db: AsyncSession,
        job_ids: list[str],
    ) -> dict[str, int]:
        if not job_ids:
            return {'events': 0, 'checkpoints': 0, 'undos': 0}
        proposal_ids = select(MindmapAiProposal.id).where(MindmapAiProposal.job_id.in_(job_ids))
        undo_result = await db.execute(
            delete(MindmapAiUndo).where(or_(
                MindmapAiUndo.proposal_id.in_(proposal_ids),
                # Direct tasks use job IDs as undo receipts without a Proposal.
                MindmapAiUndo.proposal_id.in_(job_ids),
            ))
        )
        event_result = await db.execute(
            delete(MindmapAiJobEvent).where(MindmapAiJobEvent.job_id.in_(job_ids))
        )
        checkpoint_result = await db.execute(
            delete(MindmapAiDraftCheckpoint).where(
                MindmapAiDraftCheckpoint.job_id.in_(job_ids)
            )
        )
        return {
            'events': int(event_result.rowcount or 0),
            'checkpoints': int(checkpoint_result.rowcount or 0),
            'undos': int(undo_result.rowcount or 0),
        }

    @classmethod
    async def delete_expired_undos(
        cls,
        db: AsyncSession,
        now: datetime,
        limit: int,
    ) -> int:
        candidate_ids = list((await db.execute(
            select(MindmapAiUndo.proposal_id)
            .where(MindmapAiUndo.expires_time <= now)
            .order_by(MindmapAiUndo.expires_time.asc())
            .limit(limit)
        )).scalars())
        if not candidate_ids:
            return 0
        result = await db.execute(
            delete(MindmapAiUndo).where(MindmapAiUndo.proposal_id.in_(candidate_ids))
        )
        return int(result.rowcount or 0)

    @classmethod
    async def cleanup_sessions(
        cls,
        db: AsyncSession,
        session_ids: list[str],
        now: datetime,
    ) -> dict[str, int]:
        if not session_ids:
            return {'deleted': 0, 'scrubbed': 0}
        has_jobs = exists(select(MindmapAiJob.id).where(
            MindmapAiJob.session_id == MindmapAiSession.id
        )).correlate(MindmapAiSession)
        deleted = await db.execute(delete(MindmapAiSession).where(
            MindmapAiSession.id.in_(session_ids),
            MindmapAiSession.expires_time <= now,
            ~has_jobs,
        ))
        scrubbed = await db.execute(update(MindmapAiSession).where(
            MindmapAiSession.id.in_(session_ids),
            MindmapAiSession.expires_time <= now,
        ).values(
            title=None,
            latest_artifact_id=None,
            status='expired',
            update_time=datetime.now(),
        ))
        return {
            'deleted': int(deleted.rowcount or 0),
            'scrubbed': int(scrubbed.rowcount or 0),
        }

    @classmethod
    async def delete_session_cascade(
        cls,
        db: AsyncSession,
        session_id: str,
        job_ids: list[str],
    ) -> dict[str, int]:
        counts = await cls.delete_job_payloads(db, job_ids)
        result = await db.execute(
            delete(MindmapAiSession).where(MindmapAiSession.id == session_id)
        )
        return {**counts, 'sessions': int(result.rowcount or 0)}

    @classmethod
    async def add_response(cls, db: AsyncSession, values: dict[str, Any]) -> MindmapAiResponse:
        response = MindmapAiResponse(**values)
        db.add(response)
        await db.flush()
        return response

    @classmethod
    async def get_response(
        cls,
        db: AsyncSession,
        response_id: str,
        user_id: int | None = None,
    ) -> MindmapAiResponse | None:
        query = select(MindmapAiResponse).where(MindmapAiResponse.id == response_id)
        if user_id is not None:
            query = query.where(MindmapAiResponse.user_id == user_id)
        return await _select_first(db, query)

    @classmethod
    async def get_responses_for_jobs(
        cls,
        db: AsyncSession,
        job_ids: list[str],
        user_id: int | None = None,
    ) -> dict[str, MindmapAiResponse]:
        if not job_ids:
            return {}
        query = select(MindmapAiResponse).where(MindmapAiResponse.job_id.in_(job_ids))
        if user_id is not None:
            query = query.where(MindmapAiResponse.user_id == user_id)
        records = list((await db.execute(query)).scalars())
        return {str(record.job_id): record for record in records}

    @classmethod
    async def add_artifact(cls, db: AsyncSession, values: dict[str, Any]) -> MindmapAiArtifact:
        artifact = MindmapAiArtifact(**values)
        db.add(artifact)
        await db.flush()
        return artifact

    @classmethod
    async def get_artifact(
        cls,
        db: AsyncSession,
        artifact_id: str,
        user_id: int | None = None,
    ) -> MindmapAiArtifact | None:
        query = select(MindmapAiArtifact).where(MindmapAiArtifact.id == artifact_id)
        if user_id is not None:
            query = query.where(MindmapAiArtifact.user_id == user_id)
        return await _select_first(db, query)

    @classmethod
    async def add_proposal(cls, db: AsyncSession, values: dict[str, Any]) -> MindmapAiProposal:
        proposal = MindmapAiProposal(**values)
        db.add(proposal)
        await db.flush()
        return proposal

    @classmethod
    async def get_proposal(
        cls,
        db: AsyncSession,
        proposal_id: str,
        user_id: int | None = None,
        *,
        for_update: bool = False,
    ) -> MindmapAiProposal | None:
        query = select(MindmapAiProposal).where(MindmapAiProposal.id == proposal_id)
        if user_id is not None:
            query = query.where(MindmapAiProposal.user_id == user_id)
        return await _select_first(db, query, for_update=for_update)

    @classmethod
    async def update_proposal(cls, db: AsyncSession, proposal_id: str, values: dict[str, Any]) -> None:
        await db.execute(update(MindmapAiProposal).where(MindmapAiProposal.id == proposal_id).values(**values))

    @classmethod
    async def add_undo(cls, db: AsyncSession, values: dict[str, Any]) -> MindmapAiUndo:
        undo = MindmapAiUndo(**values)
        db.add(undo)
        await db.flush()
        return undo

    @classmethod
    async def get_undo(
        cls,
        db: AsyncSession,
        proposal_id: str,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> MindmapAiUndo | None:
        query = select(MindmapAiUndo).where(
            MindmapAiUndo.proposal_id == proposal_id,
            MindmapAiUndo.user_id == user_id,
        )
        return await _select_first(db, query, for_update=for_update)

    @classmethod
    async def update_undo(cls, db: AsyncSession, proposal_id: str, values: dict[str, Any]) -> None:
        await db.execute(
            update(MindmapAiUndo)
            .where(MindmapAiUndo.proposal_id == proposal_id)
            .values(**values)
        )
