"""脑图历史版本标签快照测试。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.controller.mindmap_controller import restore_version
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_version_dao import MindmapVersionDao
from module_mindmap.service.mindmap_document_service import collect_tag_snapshots
from module_mindmap.service.mindmap_version_service import MindmapVersionService, _apply_tag_snapshots
from utils.page_util import PageUtil


class MindmapVersionTagSnapshotsTest(unittest.TestCase):
    def test_snapshot_freezes_unified_tag_style(self) -> None:
        tree = {
            'data': {
                'uid': 'root',
                'tag': [{
                    'tagId': 8,
                    'text': '高',
                    'style': {'fontSize': 14, 'fill': '#f00'},
                    'placement': 'right',
                }],
            },
            'children': [],
        }

        snapshots = collect_tag_snapshots(tree)

        self.assertEqual(snapshots['8']['style'], {'fontSize': 14, 'fill': '#f00'})
        self.assertEqual(snapshots['8']['text'], '高')

    def test_preview_uses_tag_snapshot_and_preserves_local_layout(self) -> None:
        tree = {
            'data': {
                'uid': 'root',
                'tag': [{
                    'tagId': 8,
                    'text': '当前名称',
                    'style': {'fill': '#000'},
                    'placement': 'left',
                }],
            },
            'children': [],
        }
        snapshots = {
            '8': {'tagId': 8, 'text': '历史名称', 'style': {'fill': '#f00'}},
        }

        preview = _apply_tag_snapshots(tree, snapshots)
        tag = preview['data']['tag'][0]

        self.assertEqual(tag['text'], '历史名称')
        self.assertEqual(tag['style'], {'fill': '#f00'})
        self.assertEqual(tag['placement'], 'left')


class MindmapVersionAuthorCompatibilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_version_list_resolves_legacy_numeric_author_to_user_name(self) -> None:
        paginate = AsyncMock(return_value=object())

        with patch.object(PageUtil, 'paginate', new=paginate):
            await MindmapVersionDao.get_version_list(object(), mindmap_id=8)

        query = paginate.await_args.args[1]
        sql = str(query.compile(compile_kwargs={'literal_binds': True})).lower()
        self.assertIn('left outer join sys_user', sql)
        self.assertIn('cast(sys_user.user_id as varchar(64)) = mindmap_version.created_by', sql)
        self.assertIn('coalesce(sys_user.nick_name, sys_user.user_name, mindmap_version.created_by)', sql)


class MindmapVersionConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_version_for_update_uses_a_locking_read(self) -> None:
        result = unittest.mock.MagicMock()
        result.scalars.return_value.first.return_value = object()
        db = AsyncMock()
        db.execute.return_value = result

        await MindmapVersionDao.get_version_for_update(db, 9)

        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)

    async def test_delete_rechecks_locked_version_before_decrementing_count(self) -> None:
        version = SimpleNamespace(id=9, mindmap_id=7, version_type=1)
        mindmap = SimpleNamespace(id=7)
        delete = AsyncMock()
        decrement = AsyncMock()

        with (
            patch.object(MindmapVersionDao, 'get_version_by_id', new=AsyncMock(return_value=version)),
            patch(
                'module_mindmap.service.mindmap_version_service._check_version_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapVersionDao, 'get_version_for_update', new=AsyncMock(return_value=None)),
            patch.object(MindmapVersionDao, 'delete_version', new=delete),
            patch.object(MindmapDao, 'decrement_version_count', new=decrement),
            self.assertRaises(ServiceException) as raised,
        ):
            await MindmapVersionService.delete_version_services(AsyncMock(), 9, 3)

        self.assertEqual(raised.exception.message, '版本不存在或已被删除')
        delete.assert_not_awaited()
        decrement.assert_not_awaited()

    async def test_delete_decrements_once_after_file_and_version_are_locked(self) -> None:
        version = SimpleNamespace(id=9, mindmap_id=7, version_type=1)
        mindmap = SimpleNamespace(id=7)
        db = AsyncMock()

        with (
            patch.object(MindmapVersionDao, 'get_version_by_id', new=AsyncMock(return_value=version)),
            patch(
                'module_mindmap.service.mindmap_version_service._check_version_access',
                new=AsyncMock(return_value=mindmap),
            ) as lock_file,
            patch.object(MindmapVersionDao, 'get_version_for_update', new=AsyncMock(return_value=version)) as lock_version,
            patch.object(MindmapVersionDao, 'delete_version', new=AsyncMock()) as delete,
            patch.object(MindmapDao, 'decrement_version_count', new=AsyncMock()) as decrement,
        ):
            result = await MindmapVersionService.delete_version_services(db, 9, 3)

        self.assertTrue(result.is_success)
        lock_file.assert_awaited_once_with(db, 7, 3, require_edit=True)
        lock_version.assert_awaited_once_with(db, 9)
        delete.assert_awaited_once_with(db, 9)
        decrement.assert_awaited_once_with(db, 7)
        db.commit.assert_awaited_once()


class MindmapVersionControllerContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_restore_response_exposes_the_new_content_revision(self) -> None:
        db = AsyncMock()
        current_user = SimpleNamespace(user=SimpleNamespace(user_id=3, user_name='tester'))
        service_result = CrudResponseModel(
            is_success=True,
            message='版本回滚成功',
            result={'contentRevision': 12},
        )
        response = object()

        with (
            patch.object(
                MindmapVersionService,
                'restore_version_services',
                new=AsyncMock(return_value=service_result),
            ) as restore,
            patch(
                'module_mindmap.controller.mindmap_controller.ResponseUtil.success',
                return_value=response,
            ) as success,
        ):
            result = await restore_version.__wrapped__(None, 9, db, current_user)

        self.assertIs(result, response)
        restore.assert_awaited_once_with(db, 9, 3, 'tester')
        success.assert_called_once_with(
            msg='版本回滚成功',
            data={'contentRevision': 12},
        )


if __name__ == '__main__':
    unittest.main()
