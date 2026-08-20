"""脑图公开分享权限策略测试。"""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_share_dao import MindmapShareDao
from module_mindmap.entity.vo.mindmap_share_vo import MindmapShareCreateModel
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_share_service import MindmapShareService


class MindmapSharePolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_anonymous_edit_link_is_rejected_before_database_access(self) -> None:
        with self.assertRaises(ServiceException) as context:
            await MindmapShareService.create_share_link(
                None,
                MindmapShareCreateModel(mindmapId=1, shareType=1),
                user_id=1,
            )

        self.assertIn('仅支持只读', context.exception.message)

    async def test_past_expiry_is_rejected_before_database_access(self) -> None:
        with self.assertRaises(ServiceException) as context:
            await MindmapShareService.create_share_link(
                None,
                MindmapShareCreateModel(
                    mindmapId=1,
                    expireTime=datetime.now() - timedelta(minutes=1),
                ),
                user_id=1,
            )

        self.assertIn('晚于当前时间', context.exception.message)

    async def test_timezone_aware_future_expiry_is_accepted_and_normalized(self) -> None:
        mindmap = SimpleNamespace(owner_id=7, status=0)
        captured: dict = {}

        async def capture_share(_db: object, data: dict) -> None:
            captured.update(data)

        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(MindmapDao, 'get_mindmap_for_update', new=AsyncMock(return_value=mindmap)),
            patch.object(MindmapShareDao, 'add_share', new=capture_share),
        ):
            result = await MindmapShareService.create_share_link(
                db,
                MindmapShareCreateModel(
                    mindmapId=1,
                    expireTime=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                user_id=7,
            )

        self.assertTrue(result.is_success)
        self.assertIsNone(captured['expire_time'].tzinfo)
        db.commit.assert_awaited_once()

    async def test_invalid_public_token_is_rejected_without_database_query(self) -> None:
        lookup = AsyncMock()
        with (
            patch.object(MindmapShareDao, 'get_share_by_token', new=lookup),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapShareService.view_by_share_token(None, '../invalid-token')

        self.assertIn('不存在', context.exception.message)
        lookup.assert_not_awaited()

    async def test_failed_migration_public_view_uses_legacy_snapshot(self) -> None:
        legacy_tree = {'data': {'uid': 'root', 'text': '旧快照'}, 'children': []}
        share = SimpleNamespace(is_active=1, expire_time=None, mindmap_id=8)
        mindmap = SimpleNamespace(
            id=8,
            name='迁移保护文件',
            schema_version=2,
            node_tree=legacy_tree,
            layout='logicalStructure',
            theme=None,
            view_data=None,
            document_data={'simpleMindMap': {'config': {'imgTextMargin': 11}}},
        )
        structured_loader = AsyncMock(return_value={
            'data': {'uid': 'root', 'text': '不完整新表'}, 'children': [],
        })
        with (
            patch.object(MindmapShareDao, 'get_share_by_token', new=AsyncMock(return_value=share)),
            patch.object(MindmapDao, 'get_mindmap_by_id', new=AsyncMock(return_value=mindmap)),
            patch.object(MindmapDao, 'get_migration_status', new=AsyncMock(return_value='failed')),
            patch.object(MindmapDocumentService, 'load_tree', new=structured_loader),
            patch(
                'module_mindmap.service.mindmap_share_service.CamelCaseUtil.transform_result',
                return_value={'nodeTree': legacy_tree},
            ),
        ):
            result = await MindmapShareService.view_by_share_token(None, 'a' * 32)

        self.assertEqual(result['documentData']['simpleMindMap']['config']['imgTextMargin'], 11)

        self.assertEqual(result['nodeTree'], legacy_tree)
        structured_loader.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
