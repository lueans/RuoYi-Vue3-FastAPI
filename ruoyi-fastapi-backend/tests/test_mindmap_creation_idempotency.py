"""Durable and intent-safe mindmap creation idempotency tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_creation_dao import MindmapCreationDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_vo import MindmapModel
from module_mindmap.service.mindmap_creation_service import MindmapCreationService
from module_mindmap.service.mindmap_service import MindmapService


class MindmapCreationRuleTest(unittest.TestCase):
    def test_fingerprint_is_canonical_and_operation_sensitive(self) -> None:
        first = MindmapCreationService.build_context(
            'request-key-1234567890',
            'blank',
            {'name': '规划', 'theme': {'b': 2, 'a': 1}},
        )
        reordered = MindmapCreationService.build_context(
            'request-key-1234567890',
            'blank',
            {'theme': {'a': 1, 'b': 2}, 'name': '规划'},
        )
        template = MindmapCreationService.build_context(
            'request-key-1234567890',
            'template',
            {'theme': {'a': 1, 'b': 2}, 'name': '规划'},
        )

        self.assertEqual(first.request_fingerprint, reordered.request_fingerprint)
        self.assertNotEqual(first.request_fingerprint, template.request_fingerprint)

    def test_replay_rejects_same_key_for_different_intent(self) -> None:
        context = MindmapCreationService.build_context(
            'request-key-1234567890', 'template', {'templateId': 8},
        )
        record = SimpleNamespace(
            operation='template',
            request_fingerprint='different',
            result_file_id=88,
        )

        with self.assertRaises(ServiceException) as context_error:
            MindmapCreationService.resolve_replay(record, context)
        self.assertIn('不同', context_error.exception.message)

    def test_replay_returns_original_file_id(self) -> None:
        context = MindmapCreationService.build_context(
            'request-key-1234567890', 'template', {'templateId': 8},
        )
        record = SimpleNamespace(
            operation=context.operation,
            request_fingerprint=context.request_fingerprint,
            result_file_id=88,
        )

        result = MindmapCreationService.resolve_replay(record, context)

        self.assertEqual(result.result, {'id': 88, 'idempotentReplay': True})


class MindmapCreationTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def test_creation_claim_file_and_result_commit_in_one_transaction(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        record = SimpleNamespace(id=41)
        complete_request = AsyncMock()
        with (
            patch.object(
                MindmapCreationDao,
                'get_by_owner_and_request',
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                MindmapCreationDao,
                'add_request',
                new=AsyncMock(return_value=record),
            ) as add_request,
            patch.object(
                MindmapCreationDao,
                'complete_request',
                new=complete_request,
            ),
            patch.object(
                MindmapDao,
                'add_mindmap_dao',
                new=AsyncMock(return_value=SimpleNamespace(id=81)),
            ),
        ):
            result = await MindmapService.add_mindmap_services(
                db,
                MindmapModel(name='规划', ownerId=7, createBy='tester'),
                creation_request_id='request-key-1234567890',
            )

        self.assertEqual(result.result, {'id': 81})
        add_request.assert_awaited_once()
        complete_request.assert_awaited_once_with(db, 41, 81)
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_concurrent_duplicate_returns_winner_after_unique_conflict(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        context = MindmapCreationService.build_context(
            'request-key-1234567890',
            'blank',
            {'name': '规划'},
        )
        winner = SimpleNamespace(
            operation=context.operation,
            request_fingerprint=context.request_fingerprint,
            result_file_id=91,
        )
        add_mindmap = AsyncMock()
        with (
            patch.object(
                MindmapCreationDao,
                'get_by_owner_and_request',
                new=AsyncMock(side_effect=[None, winner]),
            ),
            patch.object(
                MindmapCreationDao,
                'add_request',
                new=AsyncMock(side_effect=IntegrityError('insert', {}, Exception('duplicate'))),
            ),
            patch.object(MindmapDao, 'add_mindmap_dao', new=add_mindmap),
        ):
            result = await MindmapService.add_mindmap_services(
                db,
                MindmapModel(name='规划', ownerId=7),
                creation_request_id='request-key-1234567890',
                creation_intent={'name': '规划'},
            )

        self.assertEqual(result.result, {'id': 91, 'idempotentReplay': True})
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
        add_mindmap.assert_not_awaited()

    async def test_existing_request_short_circuits_before_file_insert(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        context = MindmapCreationService.build_context(
            'request-key-1234567890', 'template', {'templateId': 12},
        )
        existing = SimpleNamespace(
            operation=context.operation,
            request_fingerprint=context.request_fingerprint,
            result_file_id=73,
        )
        add_mindmap = AsyncMock()
        with (
            patch.object(
                MindmapCreationDao,
                'get_by_owner_and_request',
                new=AsyncMock(return_value=existing),
            ),
            patch.object(MindmapDao, 'add_mindmap_dao', new=add_mindmap),
        ):
            result = await MindmapService.add_mindmap_services(
                db,
                MindmapModel(name='模板', ownerId=7),
                creation_request_id='request-key-1234567890',
                creation_operation='template',
                creation_intent={'templateId': 12},
            )

        self.assertEqual(result.result['id'], 73)
        add_mindmap.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()

    async def test_copy_replay_does_not_require_source_file_to_still_exist(self) -> None:
        context = MindmapCreationService.build_context(
            'request-key-1234567890',
            'copy',
            {'sourceMindmapId': 12},
        )
        existing = SimpleNamespace(
            operation=context.operation,
            request_fingerprint=context.request_fingerprint,
            result_file_id=95,
        )
        source_lookup = AsyncMock()
        with (
            patch.object(
                MindmapCreationDao,
                'get_by_owner_and_request',
                new=AsyncMock(return_value=existing),
            ),
            patch.object(MindmapService, 'check_mindmap_access', new=source_lookup),
        ):
            result = await MindmapService.copy_mindmap_services(
                None,
                mindmap_id=12,
                user_id=7,
                creation_request_id='request-key-1234567890',
            )

        self.assertEqual(result.result, {'id': 95, 'idempotentReplay': True})
        source_lookup.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
