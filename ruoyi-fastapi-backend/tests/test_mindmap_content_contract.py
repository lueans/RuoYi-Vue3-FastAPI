"""脑图增量保存请求契约测试。"""
import unittest
from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

from module_mindmap.controller.mindmap_controller import reset_mindmap_collaboration
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_vo import (
    MindmapCollaborationResetModel,
    MindmapContentBatchModel,
    MindmapContentOperationModel,
    MindmapModel,
    MindmapViewUpdateModel,
)
from module_mindmap.service.mindmap_service import MindmapService


class AsyncSavepoint:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> 'AsyncSavepoint':
        self.entered = True
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.exited = True
        self.exception_type = exception_type
        return False


class MindmapContentOperationContractTest(unittest.TestCase):
    def test_unknown_operation_is_rejected(self) -> None:
        with self.assertRaises(ValidationError) as context:
            MindmapContentOperationModel(type='plugin.future.write')

        self.assertIn('不支持的脑图内容操作', str(context.exception))

    def test_node_and_entity_operations_require_identity_payload(self) -> None:
        invalid_operations = (
            {'type': 'node.update', 'payload': {}},
            {'type': 'node.update', 'nodeUid': 'node-1'},
            {'type': 'node.tag.bind', 'nodeUid': 'node-1'},
            {'type': 'relation.upsert'},
        )
        for operation in invalid_operations:
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                MindmapContentOperationModel(**operation)

    def test_delete_operation_only_requires_node_identity(self) -> None:
        operation = MindmapContentOperationModel(type='node.delete', nodeUid='node-1')

        self.assertEqual(operation.node_uid, 'node-1')
        self.assertIsNone(operation.payload)

    def test_file_operations_require_corresponding_batch_values(self) -> None:
        base = {
            'baseRevision': 1,
            'clientMutationId': 'mutation-1',
            'nodeTree': {'data': {'uid': 'root', 'text': 'root'}, 'children': []},
        }
        for operation_type in (
            'file.layout.update', 'file.theme.update', 'file.document_data.update',
        ):
            with self.subTest(operation_type=operation_type), self.assertRaises(ValidationError):
                MindmapContentBatchModel(
                    **base,
                    operations=[{'type': operation_type}],
                )

    def test_view_reset_can_explicitly_use_null(self) -> None:
        request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='mutation-1',
            operations=[{'type': 'file.view.update'}],
            nodeTree={'data': {'uid': 'root', 'text': 'root'}, 'children': []},
            viewData=None,
        )

        self.assertIsNone(request.view_data)

    def test_document_data_update_has_an_independent_file_conflict_domain(self) -> None:
        request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='mutation-document-config',
            operations=[{'type': 'file.document_data.update'}],
            nodeTree={'data': {'uid': 'root', 'text': 'root'}, 'children': []},
            documentData={'simpleMindMap': {'config': {'imgTextMargin': 8}}},
        )

        self.assertEqual(request.document_data['simpleMindMap']['config']['imgTextMargin'], 8)

    def test_content_snapshot_operation_is_supported(self) -> None:
        operation = MindmapContentOperationModel(type='document.content.update')

        self.assertEqual(operation.type, 'document.content.update')

    def test_document_data_rejects_oversized_deep_and_excessive_json(self) -> None:
        invalid_values = [
            {'payload': 'x' * (128 * 1024)},
            {'value': []},
            {'items': list(range(5_001))},
            {'invalidNumber': float('nan')},
        ]
        nested = invalid_values[1]['value']
        for _ in range(21):
            child = []
            nested.append(child)
            nested = child

        for document_data in invalid_values:
            with self.subTest(kind=next(iter(document_data))), self.assertRaises(ValidationError):
                MindmapModel(name='配置边界', documentData=document_data)


class MindmapDocumentDataPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_selection_controller_forwards_only_authenticated_user_id(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=4,
            clientMutationId='cloud-reset-1',
        )
        db = SimpleNamespace()
        current_user = SimpleNamespace(user=SimpleNamespace(user_id=3, user_name='alice'))
        reset_state = AsyncMock(return_value={
            'contentRevision': 5,
            'resetMode': 'authoritative',
        })

        with patch.object(
            MindmapService,
            'reset_collaboration_state_services',
            new=reset_state,
        ):
            await reset_mindmap_collaboration(
                request=SimpleNamespace(),
                mindmap_id=8,
                model=request,
                query_db=db,
                current_user=current_user,
            )

        reset_state.assert_awaited_once_with(db, 8, request, 3)

    async def test_view_save_is_last_write_wins_without_content_revision(self) -> None:
        request = MindmapViewUpdateModel(viewData={'scale': 1.25, 'translateX': -80})
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_content = AsyncMock()

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=update_content,
            ),
        ):
            result = await MindmapService.update_view_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        update_content.assert_awaited_once_with(
            db,
            8,
            {'view_data': {'scale': 1.25, 'translateX': -80}},
        )
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()
        self.assertNotIn('contentRevision', result)
        self.assertEqual(result['viewData']['scale'], 1.25)

    async def test_idempotent_replay_returns_before_revision_checks_or_writes(self) -> None:
        request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='replayed-mutation',
            operations=[{'type': 'file.view.update'}],
            nodeTree={'data': {'uid': 'root', 'text': 'root'}, 'children': []},
            viewData={'scale': 1},
        )
        mindmap = SimpleNamespace(content_revision=99)
        previous = SimpleNamespace(result_data={
            'contentRevision': 2,
            'clientMutationId': 'replayed-mutation',
            'concurrentMerge': False,
        })
        db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock(), add=Mock())
        update_content = AsyncMock()

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_change_by_mutation',
                new=AsyncMock(return_value=previous),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=update_content,
            ),
        ):
            result = await MindmapService.update_content_batch_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
                user_name='alice',
            )

        self.assertEqual(result['contentRevision'], 2)
        self.assertEqual(result['clientMutationId'], 'replayed-mutation')
        self.assertTrue(result['idempotentReplay'])
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
        update_content.assert_not_awaited()

    async def test_document_data_operation_persists_without_rewriting_tree(self) -> None:
        current_document_data = {'plugin': {'version': 1}}
        next_document_data = {
            'plugin': {'version': 1},
            'simpleMindMap': {'config': {'imgTextMargin': 12}},
        }
        mindmap = SimpleNamespace(
            id=8,
            owner_id=3,
            content_revision=4,
            root_node_id=10,
            node_count=2,
            schema_version=2,
            engine_name='simple-mind-map',
            engine_version='test',
            layout='logicalStructure',
            theme={'template': 'default'},
            view_data=None,
            document_data=current_document_data,
        )
        request = MindmapContentBatchModel(
            baseRevision=4,
            clientMutationId='document-config-save',
            operations=[{'type': 'file.document_data.update'}],
            nodeTree={'data': {'uid': 'root', 'text': 'root'}, 'children': []},
            documentData=next_document_data,
        )
        savepoint = AsyncSavepoint()
        db = SimpleNamespace(
            add=Mock(),
            begin_nested=Mock(return_value=savepoint),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_content = AsyncMock()
        create_draft = AsyncMock()
        broadcast = AsyncMock()

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=update_content,
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_node_revisions',
                new=AsyncMock(return_value={}),
            ),
            patch(
                'module_mindmap.service.mindmap_version_service.MindmapVersionService.create_draft_version',
                new=create_draft,
            ),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast',
                new=broadcast,
            ),
        ):
            result = await MindmapService.update_content_batch_services(
                db,
                8,
                request,
                user_id=3,
                user_name='alice',
            )

        persisted = update_content.await_args.args[2]
        self.assertEqual(persisted['document_data'], next_document_data)
        self.assertEqual(persisted['update_by'], 'alice')
        self.assertNotIn('node_tree', persisted)
        self.assertEqual(result['documentData'], next_document_data)
        self.assertEqual(result['contentRevision'], 5)
        broadcast.assert_awaited_once_with(8, {
            'type': 'content_revision_changed',
            'contentRevision': 5,
            'clientMutationId': 'document-config-save',
            'concurrentMerge': False,
        })
        self.assertEqual(db.add.call_args.args[0].created_by, 'alice')
        self.assertEqual(create_draft.await_args.kwargs['created_by'], 'alice')
        self.assertTrue(savepoint.entered)
        self.assertTrue(savepoint.exited)
        db.commit.assert_awaited_once()

    async def test_content_snapshot_persists_document_fields_without_overwriting_view(self) -> None:
        server_view = {'scale': 1.75, 'translateX': -120}
        replacement_tree = {
            'data': {'uid': 'root', 'text': '恢复后的正文'},
            'children': [],
        }
        mindmap = SimpleNamespace(
            id=8,
            owner_id=3,
            content_revision=4,
            root_node_id=10,
            node_count=1,
            schema_version=1,
            engine_name='simple-mind-map',
            engine_version='test',
            layout='logicalStructure',
            theme={'template': 'default'},
            view_data=server_view,
            document_data={'plugin': {'version': 1}},
        )
        request = MindmapContentBatchModel(
            baseRevision=4,
            clientMutationId='content-snapshot-save',
            operations=[{'type': 'document.content.update'}],
            nodeTree=replacement_tree,
            viewData={'scale': 0.5, 'translateX': 400},
            layout='fishbone',
            theme={'template': 'dark'},
            documentData={'plugin': {'version': 2}},
        )
        savepoint = AsyncSavepoint()
        db = SimpleNamespace(
            add=Mock(),
            begin_nested=Mock(return_value=savepoint),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_content = AsyncMock()
        persist_tree = AsyncMock(return_value={
            'root_node_id': 10,
            'node_count': 1,
            'schema_version': 2,
            'engine_name': 'simple-mind-map',
            'engine_version': 'test',
            'changed_nodes': [],
        })

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=update_content,
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_node_revisions',
                new=AsyncMock(return_value={}),
            ),
            patch.object(
                MindmapService,
                '_create_draft_version_safely',
                new=AsyncMock(),
            ) as create_draft,
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.persist_tree_incremental',
                new=persist_tree,
            ),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast',
                new=AsyncMock(),
            ),
        ):
            result = await MindmapService.update_content_batch_services(
                db,
                8,
                request,
                user_id=3,
                user_name='alice',
            )

        persisted = update_content.await_args.args[2]
        self.assertEqual(persisted['layout'], 'fishbone')
        self.assertEqual(persisted['theme'], {'template': 'dark'})
        self.assertEqual(persisted['document_data'], {'plugin': {'version': 2}})
        self.assertNotIn('view_data', persisted)
        self.assertEqual(result['viewData'], server_view)
        self.assertEqual(create_draft.await_args.kwargs['view_data'], server_view)
        persist_tree.assert_awaited_once_with(
            db,
            8,
            replacement_tree,
            owner_id=3,
            operator='alice',
        )
        db.commit.assert_awaited_once()

    async def test_draft_failure_rolls_back_savepoint_without_blocking_outer_commit(self) -> None:
        savepoint = AsyncSavepoint()
        db = SimpleNamespace(
            begin_nested=Mock(return_value=savepoint),
            commit=AsyncMock(),
        )
        create_draft = AsyncMock(side_effect=RuntimeError('draft flush failed'))

        with patch(
            'module_mindmap.service.mindmap_version_service.MindmapVersionService.create_draft_version',
            new=create_draft,
        ):
            await MindmapService._create_draft_version_safely(
                db,
                8,
                node_tree={'data': {'uid': 'root'}, 'children': []},
                view_data=None,
                layout='logicalStructure',
                theme=None,
                created_by='alice',
            )
            await db.commit()

        self.assertTrue(savepoint.entered)
        self.assertTrue(savepoint.exited)
        self.assertIs(savepoint.exception_type, RuntimeError)
        db.commit.assert_awaited_once()

    async def test_cloud_selection_advances_revision_and_invalidates_all_yjs_state(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=4,
            clientMutationId='cloud-reset-1',
        )
        mindmap = SimpleNamespace(content_revision=6)
        db = SimpleNamespace(
            execute=AsyncMock(),
            add=Mock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_content = AsyncMock()
        broadcast = AsyncMock()

        with (
            patch.object(
                MindmapService,
                'check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapDao,
                'get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapContentDao,
                'get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                MindmapDao,
                'update_content_dao',
                new=update_content,
            ),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast',
                new=broadcast,
            ),
        ):
            result = await MindmapService.reset_collaboration_state_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        update_content.assert_awaited_once_with(
            db,
            8,
            {
                'content_revision': 7,
                'update_by': '3',
                'update_time': update_content.await_args.args[2]['update_time'],
            },
        )
        delete_statement = db.execute.await_args.args[0]
        self.assertIn('mindmap_ws_state', str(delete_statement))
        change_log = db.add.call_args.args[0]
        self.assertEqual(change_log.base_revision, 6)
        self.assertEqual(change_log.revision, 7)
        self.assertEqual(change_log.operations[0]['type'], 'collaboration.authoritative_reset')
        db.commit.assert_awaited_once()
        broadcast.assert_awaited_once()
        self.assertEqual(result['contentRevision'], 7)
        self.assertEqual(result['resetMode'], 'authoritative')
        self.assertFalse(result['idempotentReplay'])

    async def test_cloud_selection_retry_reuses_committed_reset_revision(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=6,
            clientMutationId='cloud-reset-retry',
        )
        mindmap = SimpleNamespace(content_revision=7)
        previous = SimpleNamespace(result_data={
            'contentRevision': 7,
            'previousRevision': 6,
            'observedRevision': 6,
            'clientMutationId': 'cloud-reset-retry',
            'resetMode': 'authoritative',
            'idempotentReplay': False,
        })
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_content = AsyncMock()
        broadcast = AsyncMock()

        with (
            patch.object(
                MindmapService,
                'check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapDao,
                'get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(
                MindmapContentDao,
                'get_change_by_mutation',
                new=AsyncMock(return_value=previous),
            ),
            patch.object(MindmapDao, 'update_content_dao', new=update_content),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast',
                new=broadcast,
            ),
        ):
            result = await MindmapService.reset_collaboration_state_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        update_content.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()
        broadcast.assert_awaited_once()
        self.assertEqual(result['contentRevision'], 7)
        self.assertTrue(result['idempotentReplay'])


if __name__ == '__main__':
    unittest.main()
