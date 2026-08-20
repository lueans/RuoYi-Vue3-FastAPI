"""脑图复制与删除生命周期服务测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from exceptions.exception import ServiceException
from module_mindmap.entity.vo.mindmap_vo import DeleteMindmapModel
from module_mindmap.service.mindmap_service import MAX_BATCH_MINDMAP_DELETE, MindmapService


class MindmapLifecycleServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_delete_id_parser_deduplicates_and_limits_batch(self) -> None:
        self.assertEqual(MindmapService._parse_delete_mindmap_ids('3, 2,3'), [3, 2])
        invalid_values = ('', '1,abc', '0', '-1')
        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value), self.assertRaises(ServiceException):
                MindmapService._parse_delete_mindmap_ids(invalid_value)
        too_many_ids = ','.join(str(value) for value in range(1, MAX_BATCH_MINDMAP_DELETE + 2))
        with self.assertRaises(ServiceException) as context:
            MindmapService._parse_delete_mindmap_ids(too_many_ids)
        self.assertIn('单次最多删除', context.exception.message)

    async def test_delete_moves_complete_owned_batch_to_trash_without_cleanup(self) -> None:
        ownership_result = MagicMock()
        ownership_result.scalars.return_value = [
            SimpleNamespace(id=8, owner_id=42),
            SimpleNamespace(id=9, owner_id=42),
        ]
        db = SimpleNamespace(
            execute=AsyncMock(return_value=ownership_result),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.delete_files',
                new=AsyncMock(),
            ) as delete_files_mock,
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.move_to_trash',
                new=AsyncMock(return_value=2),
            ) as move_to_trash_mock,
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast_and_close_room',
                new=AsyncMock(),
            ) as close_room_mock,
        ):
            result = await MindmapService.delete_mindmap_services(
                db, DeleteMindmapModel(mindmapIds='8,9,8'), user_id=42, user_name='owner',
            )

        self.assertTrue(result.is_success)
        self.assertEqual(result.message, '已移入回收站')
        self.assertEqual(db.execute.await_count, 1)
        delete_files_mock.assert_not_awaited()
        move_to_trash_mock.assert_awaited_once_with(db, [8, 9], 42, 'owner')
        self.assertEqual(close_room_mock.await_count, 2)
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_delete_rejects_incomplete_or_foreign_batch_before_mutation(self) -> None:
        ownership_result = MagicMock()
        ownership_result.scalars.return_value = [SimpleNamespace(id=8, owner_id=42)]
        db = SimpleNamespace(execute=AsyncMock(return_value=ownership_result), rollback=AsyncMock())

        with (
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.move_to_trash',
                new=AsyncMock(),
            ) as move_to_trash_mock,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.delete_mindmap_services(db, DeleteMindmapModel(mindmapIds='8,9'), 42)

        self.assertIn('部分脑图不存在', context.exception.message)
        db.execute.assert_awaited_once()
        db.rollback.assert_awaited_once()
        move_to_trash_mock.assert_not_awaited()

    async def test_restore_preserves_structured_content_and_moves_missing_folder_to_root(self) -> None:
        row = SimpleNamespace(id=8, owner_id=42, folder_id=99, node_tree='{}', name='规划')
        locked = MagicMock()
        locked.scalars.return_value = [row]
        folders = MagicMock()
        folders.scalars.return_value = []
        structured = MagicMock()
        structured.scalars.return_value = [8]
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[locked, folders, structured]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.persist_tree',
                new=AsyncMock(),
            ) as persist_tree_mock,
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.restore_from_trash',
                new=AsyncMock(return_value=1),
            ) as restore_mock,
        ):
            result = await MindmapService.restore_mindmap_services(
                db, DeleteMindmapModel(mindmapIds='8'), 42, 'owner',
            )

        persist_tree_mock.assert_not_awaited()
        restore_mock.assert_awaited_once_with(db, [8], 42, 'owner', {8})
        self.assertEqual(result.result['movedToRootIds'], [8])
        self.assertEqual(result.result['legacyRecoveredIds'], [])
        db.commit.assert_awaited_once()

    async def test_restore_rematerializes_legacy_content_only_record(self) -> None:
        root = {'data': {'text': '旧脑图'}, 'children': []}
        row = SimpleNamespace(id=8, owner_id=42, folder_id=None, node_tree=root, name='旧脑图')
        locked = MagicMock()
        locked.scalars.return_value = [row]
        folders = MagicMock()
        folders.scalars.return_value = []
        structured = MagicMock()
        structured.scalars.return_value = []
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[locked, folders, structured, MagicMock()]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.persist_tree',
                new=AsyncMock(return_value={'root_node_id': 11, 'node_count': 1}),
            ) as persist_tree_mock,
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.edit_mindmap_dao',
                new=AsyncMock(),
            ) as edit_mock,
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.restore_from_trash',
                new=AsyncMock(return_value=1),
            ),
        ):
            result = await MindmapService.restore_mindmap_services(
                db, DeleteMindmapModel(mindmapIds='8'), 42, 'owner',
            )

        persist_tree_mock.assert_awaited_once()
        edit_mock.assert_awaited_once_with(db, {
            'id': 8,
            'root_node_id': 11,
            'node_count': 1,
            'last_version_id': None,
            'version_count': 1,
        })
        self.assertEqual(result.result['legacyRecoveredIds'], [8])

    async def test_restore_rejects_damaged_legacy_snapshot_and_rolls_back_batch(self) -> None:
        row = SimpleNamespace(id=8, owner_id=42, folder_id=None, node_tree='{broken', name='损坏脑图')
        locked = MagicMock()
        locked.scalars.return_value = [row]
        folders = MagicMock()
        folders.scalars.return_value = []
        structured = MagicMock()
        structured.scalars.return_value = []
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[locked, folders, structured]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.restore_from_trash',
                new=AsyncMock(),
            ) as restore_mock,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.restore_mindmap_services(
                db, DeleteMindmapModel(mindmapIds='8'), 42, 'owner',
            )

        self.assertIn('历史内容已损坏', context.exception.message)
        restore_mock.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_permanent_delete_cleans_dependencies_only_for_trashed_files(self) -> None:
        locked = MagicMock()
        locked.scalars.return_value = [SimpleNamespace(id=8, owner_id=42)]
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[locked, *(MagicMock() for _ in range(6))]),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with (
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.delete_files',
                new=AsyncMock(),
            ) as delete_files_mock,
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.permanently_delete',
                new=AsyncMock(return_value=1),
            ) as permanent_delete_mock,
        ):
            result = await MindmapService.permanently_delete_mindmap_services(
                db, DeleteMindmapModel(mindmapIds='8'), 42,
            )

        self.assertEqual(result.message, '已永久删除')
        self.assertEqual(db.execute.await_count, 7)
        delete_files_mock.assert_awaited_once_with(db, [8])
        permanent_delete_mock.assert_awaited_once_with(db, [8], 42)
        db.commit.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
