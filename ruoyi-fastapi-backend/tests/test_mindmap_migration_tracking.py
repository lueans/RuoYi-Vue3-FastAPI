"""结构化迁移结果记录测试。"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from module_mindmap.entity.do.mindmap_content_do import MindmapMigrationRecord
from scripts.migrate_mindmap_structured_content import record_migration_result


def _database_result(existing: Any) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing
    return result


class MindmapMigrationTrackingTest(unittest.IsolatedAsyncioTestCase):
    async def test_creates_failed_record_with_bounded_error(self) -> None:
        db = SimpleNamespace(
            execute=AsyncMock(return_value=_database_result(None)),
            add=MagicMock(),
        )
        started_time = datetime(2026, 8, 18, 2, 0, 0)

        record = await record_migration_result(
            db,
            file_id=8,
            batch_id='batch-1',
            status='failed',
            started_time=started_time,
            error_message='x' * 2500,
        )

        self.assertIsInstance(record, MindmapMigrationRecord)
        self.assertEqual(record.file_id, 8)
        self.assertEqual(record.status, 'failed')
        self.assertEqual(record.started_time, started_time)
        self.assertEqual(len(record.error_message), 2000)
        db.add.assert_called_once_with(record)

    async def test_rerun_updates_existing_file_record(self) -> None:
        existing = SimpleNamespace(
            batch_id='old',
            status='failed',
            legacy_hash=None,
            structured_hash=None,
            error_message='old error',
            started_time=None,
            finished_time=None,
        )
        db = SimpleNamespace(
            execute=AsyncMock(return_value=_database_result(existing)),
            add=MagicMock(),
        )
        started_time = datetime(2026, 8, 18, 3, 0, 0)

        record = await record_migration_result(
            db,
            file_id=8,
            batch_id='batch-2',
            status='migrated',
            started_time=started_time,
            legacy_hash='a' * 64,
            structured_hash='a' * 64,
        )

        self.assertIs(record, existing)
        self.assertEqual(existing.batch_id, 'batch-2')
        self.assertEqual(existing.status, 'migrated')
        self.assertEqual(existing.legacy_hash, existing.structured_hash)
        self.assertIsNone(existing.error_message)
        db.add.assert_not_called()


if __name__ == '__main__':
    unittest.main()
