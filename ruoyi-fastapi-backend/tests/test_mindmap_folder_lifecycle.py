"""脑图目录树、排序、删除和文件移动生命周期测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_folder_dao import MindmapFolderDao
from module_mindmap.entity.do.mindmap_folder_do import MindmapFolder
from module_mindmap.entity.vo.mindmap_folder_vo import (
    MAX_FOLDER_NAME_LENGTH,
    MindmapFolderCreateModel,
    MindmapFolderSortModel,
    MindmapFolderUpdateModel,
    MindmapMoveModel,
)
from module_mindmap.entity.vo.mindmap_vo import MindmapModel
from module_mindmap.service.mindmap_folder_service import (
    MAX_FOLDER_DEPTH,
    MindmapFolderService,
)
from module_mindmap.service.mindmap_service import MindmapService


def folder(
    folder_id: int,
    name: str,
    parent_id: int = 0,
    sort_order: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=folder_id,
        name=name,
        parent_id=parent_id,
        sort_order=sort_order,
    )


class MindmapFolderModelTest(unittest.TestCase):
    def test_active_unique_name_is_not_selected_during_rolling_upgrade(self) -> None:
        owner_id = 7
        statement = select(MindmapFolder).where(MindmapFolder.owner_id == owner_id)
        sql = str(statement.compile(dialect=mysql.dialect()))

        self.assertNotIn('active_name', sql)

    def test_create_normalizes_name_and_accepts_length_boundary(self) -> None:
        model = MindmapFolderCreateModel(name='  产品规划  ')
        boundary = MindmapFolderCreateModel(name='脑' * MAX_FOLDER_NAME_LENGTH)

        self.assertEqual(model.name, '产品规划')
        self.assertEqual(len(boundary.name), MAX_FOLDER_NAME_LENGTH)

    def test_models_reject_invalid_names_ids_and_duplicate_batches(self) -> None:
        invalid_creates = (' ', '研发/前端', '研发\\前端', '标题\n注入', '标题\u0085注入', '脑' * 101, 123)
        for name in invalid_creates:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                MindmapFolderCreateModel(name=name)

        with self.assertRaises(ValidationError):
            MindmapFolderUpdateModel(id=1)
        with self.assertRaises(ValidationError):
            MindmapFolderSortModel(items=[
                {'id': 1, 'sortOrder': 0},
                {'id': 1, 'sortOrder': 1},
            ])
        with self.assertRaises(ValidationError):
            MindmapMoveModel(mindmapIds=[7, 7])
        with self.assertRaises(ValidationError):
            MindmapMoveModel(mindmapIds=[7], folderId=0)
        with self.assertRaises(ValidationError):
            MindmapMoveModel(mindmapIds=[True])


class MindmapFolderGraphTest(unittest.TestCase):
    def test_build_tree_preserves_stable_sorting(self) -> None:
        folders = MindmapFolderService._folder_map([
            folder(3, '子目录', parent_id=1, sort_order=0),
            folder(2, '第二项', sort_order=2),
            folder(1, '第一项', sort_order=1),
        ])

        MindmapFolderService._validate_folder_graph(folders)
        tree = MindmapFolderService._build_tree(folders)

        self.assertEqual([item['id'] for item in tree], [1, 2])
        self.assertEqual(tree[0]['children'][0]['id'], 3)

    def test_graph_rejects_cycle_orphan_and_excessive_depth(self) -> None:
        cases = (
            {
                1: {'id': 1, 'name': '一', 'parentId': 2, 'sortOrder': 0},
                2: {'id': 2, 'name': '二', 'parentId': 1, 'sortOrder': 0},
            },
            {1: {'id': 1, 'name': '一', 'parentId': 99, 'sortOrder': 0}},
            {
                index: {
                    'id': index,
                    'name': str(index),
                    'parentId': index - 1 if index > 1 else 0,
                    'sortOrder': 0,
                }
                for index in range(1, MAX_FOLDER_DEPTH + 2)
            },
        )
        for graph in cases:
            with self.subTest(graph_size=len(graph)), self.assertRaises(ServiceException):
                MindmapFolderService._validate_folder_graph(graph)

    def test_sibling_names_are_case_insensitive(self) -> None:
        graph = {
            1: {'id': 1, 'name': 'Design', 'parentId': 0, 'sortOrder': 0},
            2: {'id': 2, 'name': 'design', 'parentId': 0, 'sortOrder': 1},
        }
        with self.assertRaises(ServiceException):
            MindmapFolderService._validate_sibling_names(graph)


class MindmapFolderServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_mindmap_locks_target_folder_until_commit(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        get_folder = AsyncMock(return_value=folder(8, '产品'))
        with (
            patch.object(MindmapFolderDao, 'get_folder_by_id', new=get_folder),
            patch.object(
                MindmapDao,
                'add_mindmap_dao',
                new=AsyncMock(return_value=SimpleNamespace(id=81)),
            ),
        ):
            result = await MindmapService.add_mindmap_services(
                db,
                MindmapModel(name='规划', ownerId=7, folderId=8),
            )

        self.assertEqual(result.result, {'id': 81})
        get_folder.assert_awaited_once_with(db, 8, 7, for_update=True)
        db.commit.assert_awaited_once()

    async def test_sort_rejects_cycle_before_writing_and_rolls_back(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_sort = AsyncMock()
        model = MindmapFolderSortModel(items=[{'id': 1, 'sortOrder': 0, 'parentId': 2}])
        with (
            patch.object(
                MindmapFolderDao,
                'get_folder_tree',
                new=AsyncMock(return_value=[folder(1, '根'), folder(2, '子', 1)]),
            ),
            patch.object(MindmapFolderDao, 'update_sort_order', new=update_sort),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapFolderService.sort_folders(db, model, user_id=7)

        self.assertIn('循环', context.exception.message)
        update_sort.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_move_rejects_partial_owned_set(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        move = AsyncMock()
        with (
            patch.object(
                MindmapFolderDao,
                'get_owned_mindmap_ids',
                new=AsyncMock(return_value=[11]),
            ),
            patch.object(MindmapFolderDao, 'move_mindmaps_to_folder', new=move),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapFolderService.move_mindmaps(
                db,
                MindmapMoveModel(mindmapIds=[11, 12]),
                user_id=7,
            )

        self.assertIn('部分脑图', context.exception.message)
        move.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_delete_moves_complete_subtree_in_one_transaction(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        move = AsyncMock(return_value=2)
        soft_delete = AsyncMock()
        with (
            patch.object(
                MindmapFolderDao,
                'get_folder_tree',
                new=AsyncMock(return_value=[
                    folder(1, '项目'),
                    folder(2, '需求', 1),
                    folder(3, '归档'),
                ]),
            ),
            patch.object(
                MindmapFolderDao,
                'count_mindmaps_in_folders',
                new=AsyncMock(return_value=2),
            ),
            patch.object(MindmapFolderDao, 'move_mindmaps_out_of_folders', new=move),
            patch.object(MindmapFolderDao, 'batch_soft_delete_folders', new=soft_delete),
        ):
            result = await MindmapFolderService.delete_folder(db, 1, user_id=7)

        self.assertEqual(result.result['folderCount'], 2)
        self.assertEqual(result.result['movedMindmapCount'], 2)
        moved_ids = set(move.await_args.args[1])
        deleted_ids = set(soft_delete.await_args.args[1])
        self.assertEqual(moved_ids, {1, 2})
        self.assertEqual(deleted_ids, {1, 2})
        db.commit.assert_awaited_once()

    async def test_delete_rolls_back_if_contents_change_during_operation(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        soft_delete = AsyncMock()
        with (
            patch.object(
                MindmapFolderDao,
                'get_folder_tree',
                new=AsyncMock(return_value=[folder(1, '项目')]),
            ),
            patch.object(
                MindmapFolderDao,
                'count_mindmaps_in_folders',
                new=AsyncMock(return_value=2),
            ),
            patch.object(
                MindmapFolderDao,
                'move_mindmaps_out_of_folders',
                new=AsyncMock(return_value=1),
            ),
            patch.object(MindmapFolderDao, 'batch_soft_delete_folders', new=soft_delete),
            self.assertRaises(ServiceException),
        ):
            await MindmapFolderService.delete_folder(db, 1, user_id=7)

        soft_delete.assert_not_awaited()
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    async def test_add_translates_database_unique_conflict(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapFolderDao,
                'get_folder_tree',
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                MindmapFolderDao,
                'add_folder',
                new=AsyncMock(side_effect=IntegrityError('insert', {}, Exception('duplicate'))),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapFolderService.add_folder(
                db,
                MindmapFolderCreateModel(name='项目'),
                user_id=7,
                user_name='tester',
            )

        self.assertIn('同名', context.exception.message)
        db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
