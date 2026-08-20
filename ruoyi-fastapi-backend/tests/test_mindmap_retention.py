"""Bounded and retry-safe retention maintenance tests."""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.dialects import mysql

from module_mindmap.dao.mindmap_retention_dao import MindmapRetentionDao
from module_mindmap.entity.do.mindmap_content_do import MindmapChangeLog
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.service.mindmap_retention_service import (
    MindmapRetentionPolicy,
    MindmapRetentionService,
)


class MindmapRetentionPolicyTest(unittest.TestCase):
    def test_policy_rejects_unsafe_windows_and_unbounded_batches(self) -> None:
        invalid = (
            {'creation_days': 6},
            {'change_days': 29},
            {'keep_revisions': 99},
            {'batch_size': 0},
            {'batch_size': 10_001},
            {'creation_days': True},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                MindmapRetentionPolicy(**values)

    def test_change_candidate_query_keeps_recent_revisions_and_age_window(self) -> None:
        cutoff = datetime(2026, 1, 1)
        statement = (
            select(MindmapChangeLog.id)
            .join(Mindmap, Mindmap.id == MindmapChangeLog.file_id)
            .where(*MindmapRetentionDao.change_eligible_condition(cutoff, 1_000))
        )
        sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={'literal_binds': True}))

        self.assertIn("mindmap_change_log.created_time < '2026-01-01", sql)
        self.assertIn('mindmap_change_log.revision <= mindmap.content_revision - 1000', sql)


class MindmapRetentionServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_plan_is_read_only_and_reports_counts_without_ids(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        now = datetime(2026, 8, 19, 12, 0, 0)
        with (
            patch.object(
                MindmapRetentionDao,
                'count_creation_candidates',
                new=AsyncMock(return_value=12),
            ),
            patch.object(
                MindmapRetentionDao,
                'count_change_candidates',
                new=AsyncMock(return_value=34),
            ),
        ):
            result = await MindmapRetentionService.plan(
                db, MindmapRetentionPolicy(), now=now,
            )

        self.assertTrue(result['readOnly'])
        self.assertEqual(result['creation']['eligibleCount'], 12)
        self.assertEqual(result['changes']['eligibleCount'], 34)
        self.assertNotIn('ids', str(result).lower())
        db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()

    async def test_execute_deletes_only_selected_bounded_candidates(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        policy = MindmapRetentionPolicy(batch_size=2)
        delete_creation = AsyncMock(return_value=2)
        delete_changes = AsyncMock(return_value=1)
        with (
            patch.object(
                MindmapRetentionDao,
                'list_creation_candidate_ids',
                new=AsyncMock(return_value=[1, 2]),
            ),
            patch.object(
                MindmapRetentionDao,
                'list_change_candidate_ids',
                new=AsyncMock(return_value=[7]),
            ),
            patch.object(
                MindmapRetentionDao,
                'delete_creation_candidates',
                new=delete_creation,
            ),
            patch.object(
                MindmapRetentionDao,
                'delete_change_candidates',
                new=delete_changes,
            ),
        ):
            result = await MindmapRetentionService.execute_batch(db, policy)

        delete_creation.assert_awaited_once_with(db, [1, 2])
        delete_changes.assert_awaited_once_with(db, [7])
        self.assertEqual(result['deletedCreationRequests'], 2)
        self.assertEqual(result['deletedChanges'], 1)
        self.assertTrue(result['hasMoreCandidates'])
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_concurrent_row_count_change_rolls_back_entire_batch(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapRetentionDao,
                'list_creation_candidate_ids',
                new=AsyncMock(return_value=[1]),
            ),
            patch.object(
                MindmapRetentionDao,
                'list_change_candidate_ids',
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                MindmapRetentionDao,
                'delete_creation_candidates',
                new=AsyncMock(return_value=0),
            ),
            patch.object(
                MindmapRetentionDao,
                'delete_change_candidates',
                new=AsyncMock(return_value=0),
            ),
            self.assertRaisesRegex(RuntimeError, '并发变化'),
        ):
            await MindmapRetentionService.execute_batch(db, MindmapRetentionPolicy())

        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
