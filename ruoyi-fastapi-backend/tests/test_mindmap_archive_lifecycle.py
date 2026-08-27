"""脑图归档、恢复、写入门禁和实时终止生命周期测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_share_vo import MindmapShareCreateModel
from module_mindmap.entity.vo.mindmap_vo import (
    MindmapBatchStatusUpdateModel,
    MindmapModel,
    MindmapPageQueryModel,
    MindmapStatusUpdateModel,
)
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.mindmap_share_service import MindmapShareService


def mindmap(*, status: int, owner_id: int = 7, mindmap_id: int = 9) -> SimpleNamespace:
    return SimpleNamespace(
        id=mindmap_id,
        owner_id=owner_id,
        status=status,
    )


class MindmapArchiveModelTest(unittest.TestCase):
    def test_status_contract_is_strict_and_list_filter_is_explicit(self) -> None:
        self.assertEqual(MindmapStatusUpdateModel(id=9, status=1).status, 1)
        self.assertIsNone(MindmapPageQueryModel().status)
        self.assertEqual(MindmapModel(name='规划').status, 0)

        for value in (
            {'id': 0, 'status': 1},
            {'id': 9, 'status': 2},
            {'id': 9, 'status': True},
            {'id': '9', 'status': 1},
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                MindmapStatusUpdateModel(**value)
        with self.assertRaises(ValidationError):
            MindmapModel(name='规划', status=2)

    def test_batch_status_contract_rejects_ambiguous_or_unbounded_ids(self) -> None:
        model = MindmapBatchStatusUpdateModel(mindmapIds=[9, 12], status=1)
        self.assertEqual(model.mindmap_ids, [9, 12])

        for value in (
            {'mindmapIds': [], 'status': 1},
            {'mindmapIds': [9, 9], 'status': 1},
            {'mindmapIds': [0], 'status': 1},
            {'mindmapIds': [True], 'status': 1},
            {'mindmapIds': ['9'], 'status': 1},
            {'mindmapIds': list(range(1, 102)), 'status': 1},
            {'mindmapIds': [9], 'status': 2},
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                MindmapBatchStatusUpdateModel(**value)


class MindmapArchiveServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_ignores_client_supplied_archive_status(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        add_mindmap = AsyncMock(return_value=SimpleNamespace(id=12))
        with patch.object(MindmapDao, 'add_mindmap_dao', new=add_mindmap):
            result = await MindmapService.add_mindmap_services(
                db,
                MindmapModel(name='新脑图', ownerId=7, status=1),
            )

        self.assertEqual(result.result, {'id': 12})
        self.assertEqual(add_mindmap.await_args.args[1]['status'], 0)
        db.commit.assert_awaited_once()

    async def test_archived_document_rejects_every_unified_edit_check(self) -> None:
        db = SimpleNamespace()
        migration_status = AsyncMock(return_value=None)
        with (
            patch.object(
                MindmapDao,
                'get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap(status=1)),
            ),
            patch.object(MindmapDao, 'get_migration_status', new=migration_status),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.resolve_mindmap_access(db, 9, 7, require_edit=True)

        self.assertIn('已归档', context.exception.message)
        migration_status.assert_not_awaited()

    async def test_archive_commits_then_broadcasts_and_closes_room(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        close_room = AsyncMock()
        with (
            patch.object(
                MindmapDao,
                'get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap(status=0)),
            ),
            patch.object(MindmapDao, 'update_mindmap_status', new=AsyncMock(return_value=1)),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast_and_close_room',
                new=close_room,
            ),
        ):
            result = await MindmapService.update_mindmap_status_services(
                db,
                MindmapStatusUpdateModel(id=9, status=1),
                user_id=7,
                user_name='tester',
            )

        self.assertEqual(result.result, {'id': 9, 'status': 1, 'changed': True})
        db.commit.assert_awaited_once()
        close_room.assert_awaited_once()
        self.assertEqual(close_room.await_args.kwargs['close_code'], 4005)
        self.assertEqual(close_room.await_args.args[1]['type'], 'document_archived')

    async def test_restore_reenables_document_without_opening_a_room(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        close_room = AsyncMock()
        update_status = AsyncMock(return_value=1)
        with (
            patch.object(
                MindmapDao,
                'get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap(status=1)),
            ),
            patch.object(MindmapDao, 'update_mindmap_status', new=update_status),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast_and_close_room',
                new=close_room,
            ),
        ):
            result = await MindmapService.update_mindmap_status_services(
                db,
                MindmapStatusUpdateModel(id=9, status=0),
                user_id=7,
                user_name='tester',
            )

        self.assertEqual(result.result['status'], 0)
        update_status.assert_awaited_once_with(db, 9, 7, 0, 'tester')
        close_room.assert_not_awaited()

    async def test_status_noop_rolls_back_without_writing(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_status = AsyncMock()
        with (
            patch.object(
                MindmapDao,
                'get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap(status=1)),
            ),
            patch.object(MindmapDao, 'update_mindmap_status', new=update_status),
        ):
            result = await MindmapService.update_mindmap_status_services(
                db,
                MindmapStatusUpdateModel(id=9, status=1),
                user_id=7,
                user_name='tester',
            )

        self.assertFalse(result.result['changed'])
        update_status.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_batch_archive_updates_only_changed_rows_then_closes_their_rooms(self) -> None:
        rows = [mindmap(status=0, mindmap_id=9), mindmap(status=1, mindmap_id=12)]
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: rows)),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_status = AsyncMock(return_value=1)
        close_room = AsyncMock()
        with (
            patch.object(MindmapDao, 'update_mindmaps_status', new=update_status),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast_and_close_room',
                new=close_room,
            ),
        ):
            result = await MindmapService.batch_update_mindmap_status_services(
                db,
                MindmapBatchStatusUpdateModel(mindmapIds=[12, 9], status=1),
                user_id=7,
                user_name='tester',
            )

        self.assertEqual(result.result, {
            'requestedIds': [9, 12],
            'changedIds': [9],
            'status': 1,
        })
        update_status.assert_awaited_once_with(db, [9], 7, 1, 'tester')
        db.commit.assert_awaited_once()
        close_room.assert_awaited_once()
        self.assertEqual(close_room.await_args.args[0], 9)
        self.assertEqual(close_room.await_args.kwargs['close_code'], 4005)

    async def test_batch_restore_does_not_open_or_close_rooms(self) -> None:
        rows = [mindmap(status=1, mindmap_id=9), mindmap(status=1, mindmap_id=12)]
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: rows)),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        close_room = AsyncMock()
        with (
            patch.object(MindmapDao, 'update_mindmaps_status', new=AsyncMock(return_value=2)),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast_and_close_room',
                new=close_room,
            ),
        ):
            result = await MindmapService.batch_update_mindmap_status_services(
                db,
                MindmapBatchStatusUpdateModel(mindmapIds=[9, 12], status=0),
                user_id=7,
                user_name='tester',
            )

        self.assertEqual(result.result['changedIds'], [9, 12])
        close_room.assert_not_awaited()

    async def test_batch_status_rejects_partial_or_unauthorized_set_atomically(self) -> None:
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(
                scalars=lambda: [mindmap(status=0, mindmap_id=9)],
            )),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_status = AsyncMock()
        with (
            patch.object(MindmapDao, 'update_mindmaps_status', new=update_status),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.batch_update_mindmap_status_services(
                db,
                MindmapBatchStatusUpdateModel(mindmapIds=[9, 12], status=1),
                user_id=7,
                user_name='tester',
            )

        self.assertIn('部分脑图不存在', context.exception.message)
        update_status.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_batch_status_noop_rolls_back_without_writing(self) -> None:
        rows = [mindmap(status=1, mindmap_id=9), mindmap(status=1, mindmap_id=12)]
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: rows)),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_status = AsyncMock()
        with patch.object(MindmapDao, 'update_mindmaps_status', new=update_status):
            result = await MindmapService.batch_update_mindmap_status_services(
                db,
                MindmapBatchStatusUpdateModel(mindmapIds=[9, 12], status=1),
                user_id=7,
                user_name='tester',
            )

        self.assertEqual(result.result['changedIds'], [])
        update_status.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_batch_archive_notification_failure_does_not_revert_committed_result(self) -> None:
        rows = [mindmap(status=0, mindmap_id=9), mindmap(status=0, mindmap_id=12)]
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: rows)),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch.object(MindmapDao, 'update_mindmaps_status', new=AsyncMock(return_value=2)),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast_and_close_room',
                new=AsyncMock(side_effect=[None, RuntimeError('pubsub unavailable')]),
            ),
        ):
            result = await MindmapService.batch_update_mindmap_status_services(
                db,
                MindmapBatchStatusUpdateModel(mindmapIds=[9, 12], status=1),
                user_id=7,
                user_name='tester',
            )

        self.assertTrue(result.is_success)
        self.assertEqual(result.result['changedIds'], [9, 12])
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_archived_document_rejects_new_public_share(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapDao,
                'get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap(status=1)),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapShareService.create_share_link(
                db,
                MindmapShareCreateModel(mindmapId=9, shareType=0),
                user_id=7,
            )

        self.assertIn('已归档', context.exception.message)
        db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
