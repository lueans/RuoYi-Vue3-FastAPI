"""脑图增量保存请求契约测试。"""
import unittest
from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pydantic import ValidationError

from exceptions.exception import ServiceException, ServiceWarning
from module_mindmap.controller.mindmap_controller import reset_mindmap_collaboration
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_vo import (
    MindmapCollaborationResetModel,
    MindmapContentBatchModel,
    MindmapContentOperationModel,
    MindmapContentUpdateModel,
    MindmapModel,
    MindmapViewUpdateModel,
)
from module_mindmap.service.mindmap_service import (
    MindmapService,
    _collaboration_reset_request_fingerprint,
    _content_replace_request_fingerprint,
)


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
    def test_compat_replace_requires_cas_and_stable_mutation_identity(self) -> None:
        tree = {'data': {'uid': 'root', 'text': 'root'}, 'children': []}
        for payload in (
            {'id': 8, 'nodeTree': tree, 'clientMutationId': 'replace-1'},
            {'id': 8, 'nodeTree': tree, 'baseRevision': 3},
            {
                'id': 8,
                'nodeTree': tree,
                'baseRevision': 3,
                'clientMutationId': '   ',
            },
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                MindmapContentUpdateModel(**payload)

        request = MindmapContentUpdateModel(
            id=8,
            nodeTree=tree,
            baseRevision=3,
            clientMutationId='  replace-1  ',
        )
        self.assertEqual(request.client_mutation_id, 'replace-1')

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

    def test_sync_confirmation_is_standalone_and_carries_realtime_count(self) -> None:
        request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='confirm-1',
            yjsUpdateCount=2,
            operations=[{'type': 'collaboration.sync.confirm'}],
            nodeTree={'data': {'uid': 'root', 'text': 'root'}, 'children': []},
            layout='logicalStructure',
            theme={},
            documentData={},
        )

        self.assertEqual(request.yjs_update_count, 2)
        self.assertEqual(request.yjs_delivery_mode, 'sequenced')
        reload_request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='  confirm-reload  ',
            yjsUpdateCount=2,
            yjsDeliveryMode='reload',
            operations=[{'type': 'collaboration.sync.confirm'}],
            nodeTree=request.node_tree,
        )
        self.assertEqual(reload_request.client_mutation_id, 'confirm-reload')
        self.assertEqual(reload_request.yjs_delivery_mode, 'reload')
        with self.assertRaises(ValidationError):
            MindmapContentBatchModel(
                baseRevision=1,
                clientMutationId='   ',
                operations=[{'type': 'file.view.update'}],
                nodeTree=request.node_tree,
            )
        with self.assertRaises(ValidationError):
            MindmapContentBatchModel(
                baseRevision=1,
                clientMutationId='confirm-missing-count',
                operations=[{'type': 'collaboration.sync.confirm'}],
                nodeTree=request.node_tree,
            )
        with self.assertRaises(ValidationError):
            MindmapContentBatchModel(
                baseRevision=1,
                clientMutationId='confirm-mixed',
                yjsUpdateCount=2,
                operations=[
                    {'type': 'collaboration.sync.confirm'},
                    {'type': 'file.view.update'},
                ],
                nodeTree=request.node_tree,
            )

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
    async def test_mutation_lookup_uses_locking_current_read_after_file_lock(self) -> None:
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        await MindmapContentDao.get_change_by_mutation(
            db,
            8,
            'mutation-current-read',
            for_update=True,
        )

        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query.get_execution_options()['populate_existing'])

    async def test_change_history_uses_locking_current_read_after_file_lock(self) -> None:
        result = MagicMock()
        result.scalars.return_value = []
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        changes = await MindmapContentDao.get_changes_after(
            db,
            8,
            3,
            for_update=True,
        )

        self.assertEqual(changes, [])
        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query.get_execution_options()['populate_existing'])

    async def test_document_delete_discovers_groups_with_a_locking_current_read(self) -> None:
        result = MagicMock()
        result.scalars.return_value = [91]
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        await MindmapContentDao.delete_document(db, [8], for_update=True)

        group_query = db.execute.await_args_list[0].args[0]
        self.assertIsNotNone(group_query._for_update_arg)
        self.assertTrue(group_query._for_update_arg.read)
        self.assertTrue(group_query.get_execution_options()['populate_existing'])

    async def test_compat_replace_rejects_stale_revision_before_materializing(self) -> None:
        request = MindmapContentUpdateModel(
            id=8,
            nodeTree={'data': {'uid': 'root', 'text': 'stale'}, 'children': []},
            baseRevision=4,
            clientMutationId='compat-stale',
        )
        mindmap = SimpleNamespace(content_revision=5)
        db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock(), add=Mock())
        load_tree = AsyncMock()

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
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
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.load_tree',
                new=load_tree,
            ),
            self.assertRaises(ServiceWarning) as raised,
        ):
            await MindmapService.update_content_services(db, request, user_id=3)

        self.assertEqual(raised.exception.data['currentRevision'], 5)
        self.assertFalse(raised.exception.data['requiresCollaborationReset'])
        load_tree.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_compat_replace_retry_replays_without_overwriting_newer_content(self) -> None:
        request = MindmapContentUpdateModel(
            id=8,
            nodeTree={'data': {'uid': 'root', 'text': 'saved'}, 'children': []},
            baseRevision=4,
            clientMutationId='compat-retry',
        )
        previous_result = {
            'contentRevision': 5,
            'clientMutationId': request.client_mutation_id,
            'requestFingerprint': _content_replace_request_fingerprint(request),
            'idempotentReplay': False,
        }
        mindmap = SimpleNamespace(content_revision=9)
        previous = SimpleNamespace(result_data=previous_result)
        db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock(), add=Mock())
        update_content = AsyncMock()
        room_manager = SimpleNamespace(
            set_content_revision=Mock(),
            broadcast=AsyncMock(),
        )

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
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
                'module_mindmap.websocket.room_manager.room_manager',
                new=room_manager,
            ),
        ):
            result = await MindmapService.update_content_services(db, request, user_id=3)

        self.assertTrue(result.result['idempotentReplay'])
        self.assertEqual(result.result['contentRevision'], 5)
        update_content.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()
        room_manager.set_content_revision.assert_not_called()
        room_manager.broadcast.assert_awaited_once()

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

    async def test_view_save_is_last_write_wins_within_one_content_revision(self) -> None:
        request = MindmapViewUpdateModel(
            viewData={'scale': 1.25, 'translateX': -80},
            expectedContentRevision=7,
        )
        mindmap = SimpleNamespace(content_revision=7)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_content = AsyncMock()

        with (
            patch.object(
                MindmapService,
                'check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
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
        self.assertEqual(result['contentRevision'], 7)
        self.assertEqual(result['viewData']['scale'], 1.25)

    async def test_view_save_rejects_a_request_from_before_an_authoritative_reset(self) -> None:
        request = MindmapViewUpdateModel(
            viewData={'scale': 0.75},
            expectedContentRevision=7,
        )
        mindmap = SimpleNamespace(content_revision=8)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_content = AsyncMock()

        with (
            patch.object(
                MindmapService,
                'check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=update_content,
            ),
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.update_view_services(db, 8, request, 3)

        self.assertEqual(context.exception.data['currentRevision'], 8)
        self.assertEqual(context.exception.data['expectedRevision'], 7)
        update_content.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_legacy_view_save_is_acknowledged_without_overwriting_cloud_view(self) -> None:
        request = MindmapViewUpdateModel(viewData={'scale': 0.75})
        mindmap = SimpleNamespace(
            content_revision=8,
            view_data={'scale': 1.5, 'translateX': 40},
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_content = AsyncMock()

        with (
            patch.object(
                MindmapService,
                'check_mindmap_access',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=update_content,
            ),
        ):
            result = await MindmapService.update_view_services(db, 8, request, 3)

        self.assertTrue(result['ignoredLegacyRequest'])
        self.assertEqual(result['contentRevision'], 8)
        self.assertEqual(result['viewData'], {'scale': 1.5, 'translateX': 40})
        update_content.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    def test_view_save_validates_a_supplied_strict_content_revision_fence(self) -> None:
        for payload in (
            {'viewData': {'scale': 1}, 'expectedContentRevision': True},
            {'viewData': {'scale': 1}, 'expectedContentRevision': '7'},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                MindmapViewUpdateModel(**payload)

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

    async def test_deferred_idempotent_replay_preserves_callers_transaction(self) -> None:
        request = MindmapContentBatchModel(
            baseRevision=1,
            clientMutationId='replayed-deferred-mutation',
            operations=[{'type': 'file.view.update'}],
            nodeTree={'data': {'uid': 'root', 'text': 'root'}, 'children': []},
            viewData={'scale': 1},
        )
        mindmap = SimpleNamespace(content_revision=99)
        previous = SimpleNamespace(result_data={
            'contentRevision': 2,
            'clientMutationId': 'replayed-deferred-mutation',
            'concurrentMerge': False,
        })
        db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock(), add=Mock())

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
        ):
            result = await MindmapService.update_content_batch_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
                user_name='ai-agent',
                commit=False,
                broadcast=False,
            )

        self.assertTrue(result['idempotentReplay'])
        db.rollback.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_sync_confirmation_advances_only_revision_and_skips_draft_snapshot(self) -> None:
        tree = {'data': {'uid': 'root', 'text': 'root'}, 'children': []}
        mindmap = SimpleNamespace(
            id=8,
            owner_id=3,
            content_revision=4,
            root_node_id=10,
            node_count=1,
            schema_version=2,
            engine_name='simple-mind-map',
            engine_version='test',
            layout='logicalStructure',
            theme={},
            view_data=None,
            document_data={},
        )
        request = MindmapContentBatchModel(
            baseRevision=4,
            clientMutationId='confirm-net-zero',
            yjsUpdateCount=2,
            operations=[{'type': 'collaboration.sync.confirm'}],
            nodeTree=tree,
            layout='logicalStructure',
            theme={},
            documentData={},
        )
        db = SimpleNamespace(add=Mock(), commit=AsyncMock(), rollback=AsyncMock())
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
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value=tree),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.update_content_dao',
                new=update_content,
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_node_revisions',
                new=AsyncMock(return_value={'root': 1}),
            ),
            patch.object(
                MindmapService,
                '_create_draft_version_safely',
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

        update_content.assert_awaited_once_with(db, 8, {'content_revision': 5})
        create_draft.assert_not_awaited()
        db.commit.assert_awaited_once()
        self.assertEqual(result['contentRevision'], 5)
        self.assertEqual(result['yjsUpdateCount'], 2)
        self.assertFalse(result['authoritativeReloadRequired'])
        change_log = db.add.call_args.args[0]
        self.assertEqual(change_log.operations, [{'type': 'collaboration.sync.confirm'}])
        self.assertEqual(change_log.result_data['requestFingerprint'], result['requestFingerprint'])
        self.assertEqual(broadcast.await_args.args[1]['yjsUpdateCount'], 2)
        self.assertTrue(broadcast.await_args.args[1]['authoritativeReloadRequired'])

    async def test_reused_mutation_id_with_a_different_request_is_rejected(self) -> None:
        request = MindmapContentBatchModel(
            baseRevision=4,
            clientMutationId='reused-with-different-content',
            operations=[{'type': 'file.view.update'}],
            nodeTree={'data': {'uid': 'root', 'text': 'root'}, 'children': []},
            viewData={'scale': 1},
        )
        mindmap = SimpleNamespace(content_revision=5)
        previous = SimpleNamespace(result_data={
            'contentRevision': 5,
            'clientMutationId': request.client_mutation_id,
            'requestFingerprint': 'different-fingerprint',
        })
        db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock(), add=Mock())

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
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
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.update_content_batch_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        self.assertIn('批次标识', context.exception.message)
        self.assertFalse(context.exception.data['requiresCollaborationReset'])
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    async def test_sync_confirmation_rejects_a_final_tree_that_is_not_cloud_state(self) -> None:
        cloud_tree = {'data': {'uid': 'root', 'text': 'cloud'}, 'children': []}
        request = MindmapContentBatchModel(
            baseRevision=4,
            clientMutationId='confirm-diverged',
            yjsUpdateCount=1,
            operations=[{'type': 'collaboration.sync.confirm'}],
            nodeTree={'data': {'uid': 'root', 'text': 'local'}, 'children': []},
            layout='logicalStructure',
            theme={},
            documentData={},
        )
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            layout='logicalStructure',
            theme={},
            document_data={},
        )
        db = SimpleNamespace(rollback=AsyncMock())

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDao.get_mindmap_for_update',
                new=AsyncMock(return_value=mindmap),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapContentDao.get_change_by_mutation',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value=cloud_tree),
            ),
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.update_content_batch_services(
                db,
                8,
                request,
                user_id=3,
            )

        self.assertTrue(context.exception.data['requiresCollaborationReset'])
        db.rollback.assert_awaited_once()

    async def test_stale_sync_confirmation_does_not_request_a_new_reset(self) -> None:
        cloud_tree = {'data': {'uid': 'root', 'text': 'cloud'}, 'children': []}
        request = MindmapContentBatchModel(
            baseRevision=3,
            clientMutationId='stale-confirm-diverged',
            yjsUpdateCount=4,
            operations=[{'type': 'collaboration.sync.confirm'}],
            nodeTree={'data': {'uid': 'root', 'text': 'local'}, 'children': []},
            layout='logicalStructure',
            theme={},
            documentData={},
        )
        mindmap = SimpleNamespace(
            content_revision=4,
            schema_version=2,
            layout='logicalStructure',
            theme={},
            document_data={},
        )
        db = SimpleNamespace(rollback=AsyncMock())

        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
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
            patch(
                'module_mindmap.service.mindmap_service.MindmapDocumentService.load_tree',
                new=AsyncMock(return_value=cloud_tree),
            ),
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.update_content_batch_services(
                db,
                8,
                request,
                user_id=3,
            )

        self.assertFalse(context.exception.data['requiresCollaborationReset'])
        db.rollback.assert_awaited_once()

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
            'authoritativeReloadRequired': True,
            'yjsUpdateCount': 0,
            'yjsDeliveryMode': 'sequenced',
            'changedNodes': [],
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
            observedRevision=6,
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
        get_change = AsyncMock(return_value=None)

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
                new=get_change,
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
        self.assertEqual(
            change_log.result_data['requestFingerprint'],
            _collaboration_reset_request_fingerprint(8, request),
        )
        self.assertTrue(get_change.await_args.kwargs['for_update'])
        db.commit.assert_awaited_once()
        broadcast.assert_awaited_once()
        self.assertEqual(result['contentRevision'], 7)
        self.assertEqual(result['resetMode'], 'authoritative')
        self.assertFalse(result['idempotentReplay'])

    async def test_late_cloud_selection_reuses_existing_reset_without_clearing_new_state(
        self,
    ) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=4,
            clientMutationId='late-cloud-reset',
        )
        mindmap = SimpleNamespace(content_revision=6)
        changes = [
            SimpleNamespace(
                revision=5,
                operations=[{'type': 'collaboration.authoritative_reset'}],
            ),
            SimpleNamespace(
                revision=6,
                operations=[{'type': 'node.update'}],
            ),
        ]
        db = SimpleNamespace(
            execute=AsyncMock(),
            add=Mock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_content = AsyncMock()
        broadcast = AsyncMock()
        set_content_revision = Mock()
        get_changes = AsyncMock(return_value=changes)

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
                MindmapContentDao,
                'get_changes_after',
                new=get_changes,
            ),
            patch.object(MindmapDao, 'update_content_dao', new=update_content),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.broadcast',
                new=broadcast,
            ),
            patch(
                'module_mindmap.websocket.room_manager.room_manager.set_content_revision',
                new=set_content_revision,
            ),
        ):
            result = await MindmapService.reset_collaboration_state_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        self.assertEqual(result['contentRevision'], 6)
        self.assertTrue(result['coalescedReset'])
        update_content.assert_not_awaited()
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()
        broadcast.assert_not_awaited()
        set_content_revision.assert_called_once_with(8, 6)
        self.assertTrue(get_changes.await_args.kwargs['for_update'])

    async def test_late_cloud_selection_cannot_delete_a_new_revision_checkpoint(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=4,
            clientMutationId='late-after-new-checkpoint',
        )
        mindmap = SimpleNamespace(content_revision=6)
        changes = [
            SimpleNamespace(revision=5, operations=[{'type': 'node.update'}]),
            SimpleNamespace(revision=6, operations=[{'type': 'node.create'}]),
        ]
        db = SimpleNamespace(
            execute=AsyncMock(),
            add=Mock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        update_content = AsyncMock()

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
                MindmapContentDao,
                'get_changes_after',
                new=AsyncMock(return_value=changes),
            ),
            patch.object(MindmapDao, 'update_content_dao', new=update_content),
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.reset_collaboration_state_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        self.assertEqual(context.exception.data['currentRevision'], 6)
        self.assertFalse(context.exception.data['requiresCollaborationReset'])
        update_content.assert_not_awaited()
        db.execute.assert_not_awaited()
        db.add.assert_not_called()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_cloud_selection_rejects_a_future_observed_revision(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=7,
            clientMutationId='future-cloud-reset',
        )
        mindmap = SimpleNamespace(content_revision=6)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

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
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.reset_collaboration_state_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        self.assertEqual(context.exception.message, '协作版本无效，请重新加载后重试')
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_cloud_selection_retry_reuses_committed_reset_revision(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=6,
            clientMutationId='cloud-reset-retry',
        )
        mindmap = SimpleNamespace(content_revision=7)
        previous = SimpleNamespace(
            operations=[{
                'type': 'collaboration.authoritative_reset',
                'payload': {'observedRevision': 6},
            }],
            result_data={
                'contentRevision': 7,
                'previousRevision': 6,
                'observedRevision': 6,
                'clientMutationId': 'cloud-reset-retry',
                'resetMode': 'authoritative',
                'idempotentReplay': False,
            },
        )
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

    async def test_cloud_selection_rejects_mutation_id_owned_by_another_operation(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=6,
            clientMutationId='reused-by-batch-save',
        )
        mindmap = SimpleNamespace(content_revision=7)
        previous = SimpleNamespace(
            operations=[{'type': 'node.update', 'payload': {'text': 'other write'}}],
            result_data={
                'contentRevision': 7,
                'clientMutationId': request.client_mutation_id,
            },
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

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
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.reset_collaboration_state_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        self.assertIn('已被用于其他操作', context.exception.message)
        self.assertFalse(context.exception.data['requiresCollaborationReset'])
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_cloud_selection_rejects_same_id_with_different_observed_revision(self) -> None:
        request = MindmapCollaborationResetModel(
            observedRevision=6,
            clientMutationId='reset-observation-changed',
        )
        mindmap = SimpleNamespace(content_revision=7)
        previous_request = MindmapCollaborationResetModel(
            observedRevision=5,
            clientMutationId=request.client_mutation_id,
        )
        previous = SimpleNamespace(
            operations=[{
                'type': 'collaboration.authoritative_reset',
                'payload': {'observedRevision': 5},
            }],
            result_data={
                'contentRevision': 6,
                'previousRevision': 5,
                'observedRevision': 5,
                'clientMutationId': request.client_mutation_id,
                'resetMode': 'authoritative',
                'requestFingerprint': _collaboration_reset_request_fingerprint(
                    8,
                    previous_request,
                ),
            },
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

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
            self.assertRaises(ServiceWarning) as context,
        ):
            await MindmapService.reset_collaboration_state_services(
                db,
                mindmap_id=8,
                page_object=request,
                user_id=3,
            )

        self.assertIn('已被用于其他操作', context.exception.message)
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
