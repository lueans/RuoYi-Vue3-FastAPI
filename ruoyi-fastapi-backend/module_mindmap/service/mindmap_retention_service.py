from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.dao.mindmap_retention_dao import MindmapRetentionDao

MIN_CREATION_RETENTION_DAYS = 7
MIN_CHANGE_RETENTION_DAYS = 30
MIN_RETAINED_REVISIONS = 100
MAX_RETENTION_BATCH_SIZE = 10_000


@dataclass(frozen=True)
class MindmapRetentionPolicy:
    creation_days: int = 30
    change_days: int = 90
    keep_revisions: int = 1_000
    batch_size: int = 1_000

    def __post_init__(self) -> None:
        values = (
            self.creation_days,
            self.change_days,
            self.keep_revisions,
            self.batch_size,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError('脑图保留策略参数必须为整数')
        if self.creation_days < MIN_CREATION_RETENTION_DAYS:
            raise ValueError(f'创建幂等记录至少保留 {MIN_CREATION_RETENTION_DAYS} 天')
        if self.change_days < MIN_CHANGE_RETENTION_DAYS:
            raise ValueError(f'增量变更至少保留 {MIN_CHANGE_RETENTION_DAYS} 天')
        if self.keep_revisions < MIN_RETAINED_REVISIONS:
            raise ValueError(f'每个脑图至少保留最近 {MIN_RETAINED_REVISIONS} 个变更 revision')
        if not 1 <= self.batch_size <= MAX_RETENTION_BATCH_SIZE:
            raise ValueError(f'单批清理数量必须在 1-{MAX_RETENTION_BATCH_SIZE} 之间')

    def cutoffs(self, now: datetime) -> tuple[datetime, datetime]:
        return (
            now - timedelta(days=self.creation_days),
            now - timedelta(days=self.change_days),
        )


class MindmapRetentionService:
    """Plans and executes one bounded maintenance batch without exposing payloads."""

    @classmethod
    async def plan(
        cls,
        db: AsyncSession,
        policy: MindmapRetentionPolicy,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        reference_time = now or datetime.now()
        creation_cutoff, change_cutoff = policy.cutoffs(reference_time)
        creation_count = await MindmapRetentionDao.count_creation_candidates(
            db, creation_cutoff,
        )
        change_count = await MindmapRetentionDao.count_change_candidates(
            db, change_cutoff, policy.keep_revisions,
        )
        return {
            'readOnly': True,
            'referenceTime': reference_time.isoformat(),
            'creation': {
                'retentionDays': policy.creation_days,
                'cutoff': creation_cutoff.isoformat(),
                'eligibleCount': creation_count,
            },
            'changes': {
                'retentionDays': policy.change_days,
                'cutoff': change_cutoff.isoformat(),
                'keepRecentRevisionsPerFile': policy.keep_revisions,
                'eligibleCount': change_count,
            },
            'batchSize': policy.batch_size,
        }

    @classmethod
    async def execute_batch(
        cls,
        db: AsyncSession,
        policy: MindmapRetentionPolicy,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        reference_time = now or datetime.now()
        creation_cutoff, change_cutoff = policy.cutoffs(reference_time)
        try:
            creation_ids = await MindmapRetentionDao.list_creation_candidate_ids(
                db, creation_cutoff, policy.batch_size,
            )
            change_ids = await MindmapRetentionDao.list_change_candidate_ids(
                db, change_cutoff, policy.keep_revisions, policy.batch_size,
            )
            deleted_creation = await MindmapRetentionDao.delete_creation_candidates(
                db, creation_ids,
            )
            deleted_changes = await MindmapRetentionDao.delete_change_candidates(db, change_ids)
            if deleted_creation != len(creation_ids) or deleted_changes != len(change_ids):
                raise RuntimeError('脑图保留清理行数发生并发变化，请重试')
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return {
            'readOnly': False,
            'referenceTime': reference_time.isoformat(),
            'deletedCreationRequests': deleted_creation,
            'deletedChanges': deleted_changes,
            'batchSize': policy.batch_size,
            'hasMoreCandidates': (
                len(creation_ids) == policy.batch_size
                or len(change_ids) == policy.batch_size
            ),
        }
