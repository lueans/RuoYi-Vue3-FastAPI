"""脑图文件信息严格更新契约测试。"""

import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.vo.mindmap_vo import (
    MAX_MINDMAP_DESCRIPTION_LENGTH,
    MindmapMetadataUpdateModel,
    MindmapModel,
)
from module_mindmap.service.mindmap_service import MindmapService


class MindmapMetadataModelTest(unittest.TestCase):
    def test_metadata_normalizes_name_and_description(self) -> None:
        model = MindmapMetadataUpdateModel(
            id=8,
            name='  产品规划  ',
            description='  目标\n范围\t说明  ',
        )
        blank_description = MindmapMetadataUpdateModel(id=8, name='产品规划', description='  ')

        self.assertEqual(model.name, '产品规划')
        self.assertEqual(model.description, '目标\n范围\t说明')
        self.assertIsNone(blank_description.description)

    def test_metadata_rejects_invalid_ids_controls_and_oversized_description(self) -> None:
        invalid_values = (
            {'id': True, 'name': '产品规划'},
            {'id': 0, 'name': '产品规划'},
            {'id': 8, 'name': '产品规划', 'description': '说明\x00注入'},
            {
                'id': 8,
                'name': '产品规划',
                'description': '脑' * (MAX_MINDMAP_DESCRIPTION_LENGTH + 1),
            },
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                MindmapMetadataUpdateModel(**value)

    def test_create_model_uses_the_same_description_contract(self) -> None:
        self.assertEqual(MindmapModel(name='脑图', description='  说明  ').description, '说明')
        with self.assertRaises(ValidationError):
            MindmapModel(name='脑图', description='说明\x00注入')


class MindmapMetadataServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_update_writes_only_public_metadata_and_audit_fields(self) -> None:
        query_db = AsyncMock()
        model = MindmapMetadataUpdateModel(id=8, name='产品规划', description='目标说明')
        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()) as access_mock,
            patch.object(MindmapDao, 'edit_mindmap_dao', new=AsyncMock()) as edit_mock,
        ):
            result = await MindmapService.update_mindmap_metadata_services(
                query_db,
                model,
                user_id=42,
                user_name='tester',
            )

        access_mock.assert_awaited_once_with(query_db, 8, 42, require_edit=True)
        payload = edit_mock.await_args.args[1]
        self.assertEqual(
            set(payload),
            {'id', 'name', 'description', 'update_by', 'update_time'},
        )
        self.assertEqual(payload['description'], '目标说明')
        self.assertEqual(payload['update_by'], 'tester')
        query_db.commit.assert_awaited_once()
        query_db.rollback.assert_not_awaited()
        self.assertEqual(result.result, {'id': 8, 'name': '产品规划', 'description': '目标说明'})

    async def test_update_rolls_back_when_persistence_fails(self) -> None:
        query_db = AsyncMock()
        model = MindmapMetadataUpdateModel(id=8, name='产品规划')
        with (
            patch.object(MindmapService, 'check_mindmap_access', new=AsyncMock()),
            patch.object(
                MindmapDao,
                'edit_mindmap_dao',
                new=AsyncMock(side_effect=RuntimeError('write failed')),
            ),
            self.assertRaisesRegex(RuntimeError, 'write failed'),
        ):
            await MindmapService.update_mindmap_metadata_services(
                query_db,
                model,
                user_id=42,
                user_name='tester',
            )

        query_db.commit.assert_not_awaited()
        query_db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
