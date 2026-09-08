"""脑图历史版本标签快照测试。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException, ServiceWarning
from module_mindmap.controller.mindmap_controller import restore_version
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_version_dao import MindmapVersionDao
from module_mindmap.entity.vo.mindmap_version_vo import MindmapVersionRestoreModel
from module_mindmap.service.mindmap_document_service import collect_tag_snapshots
from module_mindmap.service.mindmap_version_service import (
    MindmapVersionService,
    _apply_tag_snapshots,
    _restore_request_fingerprint,
)
from utils.page_util import PageUtil


class MindmapVersionTagSnapshotsTest(unittest.TestCase):
    def test_snapshot_freezes_unified_tag_style(self) -> None:
        tree = {
            'data': {
                'uid': 'root',
                'tag': [{
                    'tagId': 8,
                    'categoryId': 3,
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
        self.assertEqual(snapshots['8']['categoryId'], 3)

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
        self.assertTrue(query.get_execution_options()['populate_existing'])

    async def test_next_version_number_uses_locking_current_read(self) -> None:
        result = unittest.mock.MagicMock()
        result.scalars.return_value.first.return_value = 12
        db = AsyncMock()
        db.execute.return_value = result

        version_number = await MindmapVersionDao.get_next_version_number(
            db,
            7,
            for_update=True,
        )

        self.assertEqual(version_number, 13)
        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertIn('ORDER BY mindmap_version.version_number DESC', str(query))

    async def test_latest_draft_refreshes_the_locked_orm_row(self) -> None:
        result = unittest.mock.MagicMock()
        result.scalars.return_value.first.return_value = object()
        db = AsyncMock()
        db.execute.return_value = result

        await MindmapVersionDao.get_latest_draft(db, 7, for_update=True)

        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query.get_execution_options()['populate_existing'])

    async def test_delete_rechecks_locked_version_before_decrementing_count(self) -> None:
        version = SimpleNamespace(id=9, mindmap_id=7, version_type=1)
        mindmap = SimpleNamespace(id=7, content_revision=5)
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

    async def test_restore_rechecks_locked_version_after_waiting_for_file_lock(self) -> None:
        observed_version = SimpleNamespace(id=9, mindmap_id=7)
        mindmap = SimpleNamespace(id=7, content_revision=5)
        db = AsyncMock()
        restore_request = MindmapVersionRestoreModel(
            expectedRevision=5,
            clientMutationId='restore-recheck-version',
        )

        with (
            patch.object(
                MindmapVersionDao,
                'get_version_by_id',
                new=AsyncMock(return_value=observed_version),
            ),
            patch(
                'module_mindmap.service.mindmap_version_service._check_version_access',
                new=AsyncMock(return_value=mindmap),
            ) as lock_file,
            patch.object(
                MindmapContentDao,
                'get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                MindmapVersionDao,
                'get_version_for_update',
                new=AsyncMock(return_value=None),
            ) as lock_version,
            self.assertRaises(ServiceException) as raised,
        ):
            await MindmapVersionService.restore_version_services(
                db,
                9,
                restore_request,
                3,
                'tester',
            )

        self.assertEqual(raised.exception.message, '版本不存在或已被删除')
        lock_file.assert_awaited_once_with(db, 7, 3, require_edit=True)
        lock_version.assert_awaited_once_with(db, 9)
        db.rollback.assert_awaited_once()

    async def test_restore_purges_old_yjs_baseline_in_the_same_transaction(self) -> None:
        tree = {'data': {'uid': 'root', 'text': '历史版本'}, 'children': []}
        version = SimpleNamespace(
            id=9,
            mindmap_id=7,
            version_number=2,
            node_tree=tree,
            view_data={'scale': 1},
            layout='logicalStructure',
            theme={'template': 'default'},
        )
        mindmap = SimpleNamespace(
            id=7,
            owner_id=3,
            content_revision=5,
        )
        db = AsyncMock()
        db.add = Mock()
        room_manager = SimpleNamespace(
            set_content_revision=Mock(),
            broadcast=AsyncMock(),
        )
        metadata = {
            'root_node_id': 11,
            'node_count': 1,
            'schema_version': 2,
            'engine_name': 'simple-mind-map',
            'engine_version': None,
            'changed_nodes': [],
        }
        restore_request = MindmapVersionRestoreModel(
            expectedRevision=5,
            clientMutationId='restore-purge-yjs',
        )

        with (
            patch.object(
                MindmapVersionDao,
                'get_version_by_id',
                new=AsyncMock(return_value=version),
            ),
            patch.object(
                MindmapVersionDao,
                'get_version_for_update',
                new=AsyncMock(return_value=version),
            ),
            patch(
                'module_mindmap.service.mindmap_version_service._check_version_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapContentDao,
                'get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_version_service.MindmapTagPortabilityService.prepare_tree_for_owner',
                new=AsyncMock(return_value=tree),
            ) as prepare_tree,
            patch.object(MindmapDao, 'edit_mindmap_dao', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_version_service.MindmapDocumentService.persist_tree_incremental',
                new=AsyncMock(return_value=metadata),
            ),
            patch.object(
                MindmapVersionDao,
                'get_next_version_number',
                new=AsyncMock(return_value=3),
            ),
            patch.object(MindmapVersionDao, 'add_version', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_version_service.MindmapDocumentService.get_tag_snapshots',
                new=AsyncMock(return_value={}),
            ),
            patch.object(MindmapDao, 'increment_version_count', new=AsyncMock()),
            patch(
                'module_mindmap.websocket.room_manager.room_manager',
                new=room_manager,
            ),
        ):
            result = await MindmapVersionService.restore_version_services(
                db,
                9,
                restore_request,
                3,
                'tester',
            )

        self.assertTrue(result.is_success)
        prepare_tree.assert_awaited_once_with(
            db,
            tree,
            target_owner_id=3,
            allow_disabled_references=True,
            for_update=True,
        )
        delete_statement = db.execute.await_args.args[0]
        self.assertIn('DELETE FROM mindmap_ws_state', str(delete_statement))
        self.assertIn('mindmap_ws_state.mindmap_id', str(delete_statement))
        db.commit.assert_awaited_once()
        room_manager.set_content_revision.assert_called_once_with(
            7,
            6,
            transition_type='document_reset',
        )
        room_manager.broadcast.assert_awaited_once()

    async def test_restore_rejects_stale_confirmation_before_reading_snapshot(self) -> None:
        version = SimpleNamespace(id=9, mindmap_id=7)
        mindmap = SimpleNamespace(id=7, content_revision=6)
        request = MindmapVersionRestoreModel(
            expectedRevision=5,
            clientMutationId='restore-stale-confirmation',
        )
        db = AsyncMock()
        lock_version = AsyncMock()

        with (
            patch.object(
                MindmapVersionDao,
                'get_version_by_id',
                new=AsyncMock(return_value=version),
            ),
            patch(
                'module_mindmap.service.mindmap_version_service._check_version_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapContentDao,
                'get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                MindmapVersionDao,
                'get_version_for_update',
                new=lock_version,
            ),
            self.assertRaises(ServiceWarning) as raised,
        ):
            await MindmapVersionService.restore_version_services(
                db,
                9,
                request,
                3,
                'tester',
            )

        self.assertEqual(raised.exception.data['currentRevision'], 6)
        self.assertFalse(raised.exception.data['requiresCollaborationReset'])
        lock_version.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_restore_retry_replays_committed_result_without_a_second_write(self) -> None:
        version = SimpleNamespace(id=9, mindmap_id=7)
        mindmap = SimpleNamespace(id=7, content_revision=6)
        request = MindmapVersionRestoreModel(
            expectedRevision=5,
            clientMutationId='restore-idempotent-retry',
        )
        previous_result = {
            'contentRevision': 6,
            'clientMutationId': request.client_mutation_id,
            'restoredVersionId': 9,
            'requestFingerprint': _restore_request_fingerprint(9, request),
            'idempotentReplay': False,
        }
        previous = SimpleNamespace(result_data=previous_result)
        db = AsyncMock()
        room_manager = SimpleNamespace(
            set_content_revision=Mock(),
            broadcast=AsyncMock(),
        )
        lock_version = AsyncMock()

        with (
            patch.object(
                MindmapVersionDao,
                'get_version_by_id',
                new=AsyncMock(return_value=version),
            ),
            patch(
                'module_mindmap.service.mindmap_version_service._check_version_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapContentDao,
                'get_change_by_mutation',
                new=AsyncMock(return_value=previous),
            ),
            patch.object(
                MindmapVersionDao,
                'get_version_for_update',
                new=lock_version,
            ),
            patch(
                'module_mindmap.websocket.room_manager.room_manager',
                new=room_manager,
            ),
        ):
            result = await MindmapVersionService.restore_version_services(
                db,
                9,
                request,
                3,
                'tester',
            )

        self.assertTrue(result.result['idempotentReplay'])
        self.assertEqual(result.result['contentRevision'], 6)
        lock_version.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()
        room_manager.set_content_revision.assert_called_once_with(
            7,
            6,
            transition_type='document_reset',
        )
        room_manager.broadcast.assert_awaited_once()

    async def test_restore_rejects_reused_mutation_id_for_another_intent(self) -> None:
        version = SimpleNamespace(id=9, mindmap_id=7)
        mindmap = SimpleNamespace(id=7, content_revision=6)
        request = MindmapVersionRestoreModel(
            expectedRevision=6,
            clientMutationId='restore-reused-id',
        )
        previous = SimpleNamespace(result_data={
            'contentRevision': 6,
            'requestFingerprint': 'different-request',
        })
        db = AsyncMock()

        with (
            patch.object(
                MindmapVersionDao,
                'get_version_by_id',
                new=AsyncMock(return_value=version),
            ),
            patch(
                'module_mindmap.service.mindmap_version_service._check_version_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapContentDao,
                'get_change_by_mutation',
                new=AsyncMock(return_value=previous),
            ),
            self.assertRaises(ServiceWarning) as raised,
        ):
            await MindmapVersionService.restore_version_services(
                db,
                9,
                request,
                3,
                'tester',
            )

        self.assertIn('恢复标识', raised.exception.message)
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

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
        restore_request = MindmapVersionRestoreModel(
            expectedRevision=11,
            clientMutationId='restore-controller-contract',
        )

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
            result = await restore_version.__wrapped__(
                None,
                9,
                restore_request,
                db,
                current_user,
            )

        self.assertIs(result, response)
        restore.assert_awaited_once_with(db, 9, restore_request, 3, 'tester')
        success.assert_called_once_with(
            msg='版本回滚成功',
            data={'contentRevision': 12},
        )


if __name__ == '__main__':
    unittest.main()
