"""脑图结构化文档读取完整性测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_vo import MindmapContentBatchModel, MindmapContentUpdateModel
from module_mindmap.service.mindmap_document_service import (
    STRUCTURED_CONTENT_CORRUPT_MESSAGE,
    MindmapDocumentService,
)
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.simple_mind_document_codec import EncodedDocument


class MindmapDocumentIntegrityTest(unittest.IsolatedAsyncioTestCase):
    async def test_detail_normalizes_legacy_null_theme_to_default(self) -> None:
        mindmap = Mindmap(
            id=42,
            name='旧版空主题脑图',
            owner_id=7,
            status=0,
            schema_version=1,
            node_tree={'data': {'uid': 'root', 'text': '根节点'}, 'children': []},
            theme=None,
        )
        with (
            patch.object(
                MindmapService,
                'resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, True)),
            ),
            patch.object(MindmapDao, 'get_migration_status', new=AsyncMock(return_value='done')),
        ):
            result = await MindmapService.get_mindmap_detail_services(AsyncMock(), 42, 7)

        self.assertEqual(result.theme, {'template': 'default', 'config': {}})
        self.assertEqual(result.content_state, 'ready')

    async def test_locking_load_uses_current_read_and_refreshes_identity_map(self) -> None:
        result = MagicMock()
        result.scalars.return_value = []
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        document = await MindmapContentDao.load_document(db, 42, for_update=True)

        self.assertIsNone(document)
        query = db.execute.await_args.args[0]
        self.assertIsNotNone(query._for_update_arg)
        self.assertTrue(query._for_update_arg.read)
        self.assertTrue(query.get_execution_options()['populate_existing'])

    async def test_load_tree_forwards_locking_current_read_to_dao(self) -> None:
        load_document = AsyncMock(return_value=None)
        db = AsyncMock()

        with patch.object(MindmapContentDao, 'load_document', new=load_document):
            result = await MindmapDocumentService.load_tree(db, 42, for_update=True)

        self.assertIsNone(result)
        load_document.assert_awaited_once_with(db, 42, for_update=True)

    async def test_load_tree_converts_corrupt_topology_to_stable_service_error(self) -> None:
        document = EncodedDocument(
            root_uid='root',
            nodes=[
                {'node_uid': 'root', 'parent_uid': None},
                {'node_uid': 'orphan', 'parent_uid': 'missing'},
            ],
        )
        with (
            patch.object(MindmapContentDao, 'load_document', new=AsyncMock(return_value=document)),
            patch('module_mindmap.service.mindmap_document_service.logger.error') as log_error,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapDocumentService.load_tree(AsyncMock(), 42)

        self.assertEqual(context.exception.message, STRUCTURED_CONTENT_CORRUPT_MESSAGE)
        self.assertIsInstance(context.exception.__cause__, ValueError)
        self.assertIn('缺失父节点', str(context.exception.__cause__))
        log_error.assert_called_once_with(
            '脑图结构化内容完整性校验失败: file_id=42, reason=脑图节点缺失父节点: orphan',
        )

    async def test_required_load_rejects_missing_structured_document(self) -> None:
        with (
            patch.object(MindmapContentDao, 'load_document', new=AsyncMock(return_value=None)),
            patch('module_mindmap.service.mindmap_document_service.logger.error') as log_error,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapDocumentService.load_tree(AsyncMock(), 42, required=True)

        self.assertEqual(context.exception.message, STRUCTURED_CONTENT_CORRUPT_MESSAGE)
        log_error.assert_called_once_with(
            '脑图结构化内容完整性校验失败: file_id=42, reason=节点记录不存在',
        )

    async def test_load_tree_converts_dao_reference_corruption_to_integrity_error(self) -> None:
        with (
            patch.object(
                MindmapContentDao,
                'load_document',
                new=AsyncMock(side_effect=ValueError('脑图节点引用不存在或已删除的父节点')),
            ),
            patch('module_mindmap.service.mindmap_document_service.logger.error') as log_error,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapDocumentService.load_tree(AsyncMock(), 42, required=True)

        self.assertEqual(context.exception.message, STRUCTURED_CONTENT_CORRUPT_MESSAGE)
        self.assertIsInstance(context.exception.__cause__, ValueError)
        log_error.assert_called_once_with(
            '脑图结构化内容完整性校验失败: '
            'file_id=42, reason=脑图节点引用不存在或已删除的父节点',
        )

    async def test_detail_fallback_marks_corrupt_structured_content_readonly(self) -> None:
        legacy_tree = {'data': {'uid': 'legacy-root', 'text': '兼容快照'}, 'children': []}
        mindmap = Mindmap(
            id=42,
            name='损坏脑图',
            owner_id=7,
            status=0,
            schema_version=2,
            node_tree=legacy_tree,
        )
        with (
            patch.object(
                MindmapService,
                'resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, True)),
            ),
            patch.object(MindmapDao, 'get_migration_status', new=AsyncMock(return_value='done')),
            patch.object(
                MindmapDocumentService,
                'load_tree',
                new=AsyncMock(side_effect=ServiceException(message=STRUCTURED_CONTENT_CORRUPT_MESSAGE)),
            ),
            patch('module_mindmap.service.mindmap_service.logger.warning'),
        ):
            result = await MindmapService.get_mindmap_detail_services(AsyncMock(), 42, 7)

        self.assertFalse(result.can_edit)
        self.assertEqual(result.content_state, 'integrity_failed')
        self.assertEqual(result.content_state_message, STRUCTURED_CONTENT_CORRUPT_MESSAGE)
        self.assertEqual(result.node_tree, legacy_tree)

    async def test_detail_fallback_marks_transient_structured_load_failure_readonly(self) -> None:
        mindmap = Mindmap(
            id=42,
            name='暂时不可用脑图',
            owner_id=7,
            status=0,
            schema_version=2,
            node_tree={'data': {'uid': 'legacy-root'}, 'children': []},
        )
        with (
            patch.object(
                MindmapService,
                'resolve_mindmap_access',
                new=AsyncMock(return_value=(mindmap, 1, True)),
            ),
            patch.object(MindmapDao, 'get_migration_status', new=AsyncMock(return_value='done')),
            patch.object(
                MindmapDocumentService,
                'load_tree',
                new=AsyncMock(side_effect=RuntimeError('temporary database error')),
            ),
            patch('module_mindmap.service.mindmap_service.logger.warning'),
        ):
            result = await MindmapService.get_mindmap_detail_services(AsyncMock(), 42, 7)

        self.assertFalse(result.can_edit)
        self.assertEqual(result.content_state, 'load_failed')
        self.assertIn('稍后重试', result.content_state_message)

    async def test_compat_document_replace_rejects_corrupt_structured_baseline(self) -> None:
        db = AsyncMock()
        mindmap = SimpleNamespace(
            id=42,
            owner_id=7,
            schema_version=2,
            content_revision=3,
        )
        request = MindmapContentUpdateModel(
            id=42,
            nodeTree={'data': {'uid': 'replacement'}, 'children': []},
            baseRevision=3,
            clientMutationId='replace-corrupt-baseline',
        )
        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch.object(MindmapDao, 'get_mindmap_for_update', new=AsyncMock(return_value=mindmap)),
            patch.object(MindmapContentDao, 'get_change_by_mutation', new=AsyncMock(return_value=None)),
            patch.object(
                MindmapDocumentService,
                'load_tree',
                new=AsyncMock(side_effect=ServiceException(message=STRUCTURED_CONTENT_CORRUPT_MESSAGE)),
            ) as load_tree,
            patch.object(MindmapDocumentService, 'persist_tree_incremental', new=AsyncMock()) as persist,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.update_content_services(db, request, user_id=7)

        self.assertEqual(context.exception.message, STRUCTURED_CONTENT_CORRUPT_MESSAGE)
        load_tree.assert_awaited_once_with(db, 42, required=True, for_update=True)
        persist.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_batch_tree_save_rejects_corrupt_structured_baseline(self) -> None:
        db = AsyncMock()
        mindmap = SimpleNamespace(
            id=42,
            owner_id=7,
            schema_version=2,
            content_revision=3,
        )
        request = MindmapContentBatchModel(
            baseRevision=3,
            clientMutationId='batch-corrupt-baseline',
            operations=[{'type': 'document.update'}],
            nodeTree={'data': {'uid': 'replacement'}, 'children': []},
        )
        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch.object(MindmapDao, 'get_mindmap_for_update', new=AsyncMock(return_value=mindmap)),
            patch.object(MindmapContentDao, 'get_change_by_mutation', new=AsyncMock(return_value=None)),
            patch.object(
                MindmapDocumentService,
                'load_tree',
                new=AsyncMock(side_effect=ServiceException(message=STRUCTURED_CONTENT_CORRUPT_MESSAGE)),
            ) as load_tree,
            patch.object(MindmapDocumentService, 'persist_tree_incremental', new=AsyncMock()) as persist,
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapService.update_content_batch_services(db, 42, request, user_id=7)

        self.assertEqual(context.exception.message, STRUCTURED_CONTENT_CORRUPT_MESSAGE)
        load_tree.assert_awaited_once_with(db, 42, required=True, for_update=True)
        persist.assert_not_awaited()
        db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
