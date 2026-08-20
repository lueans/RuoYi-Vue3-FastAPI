"""脑图文件名称与生命周期请求契约测试。"""

import unittest

from pydantic import ValidationError

from module_mindmap.entity.vo.mindmap_vo import (
    MAX_MINDMAP_NAME_LENGTH,
    MindmapImportModel,
    MindmapModel,
    MindmapRenameModel,
)


class MindmapFileLifecycleModelTest(unittest.TestCase):
    def test_rename_trims_name_and_accepts_shared_length_boundary(self) -> None:
        model = MindmapRenameModel(id=5, name='  产品规划  ')
        boundary = MindmapRenameModel(id=5, name='脑' * MAX_MINDMAP_NAME_LENGTH)

        self.assertEqual(model.name, '产品规划')
        self.assertEqual(len(boundary.name), MAX_MINDMAP_NAME_LENGTH)

    def test_rename_rejects_blank_oversized_control_names_and_invalid_id(self) -> None:
        invalid_values = (
            {'id': 5, 'name': '   '},
            {'id': 5, 'name': '脑' * (MAX_MINDMAP_NAME_LENGTH + 1)},
            {'id': 5, 'name': '标题\n注入'},
            {'id': 0, 'name': '产品规划'},
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                MindmapRenameModel(**value)

    def test_create_and_query_model_share_name_normalization(self) -> None:
        model = MindmapModel(name='  产品规划  ')
        self.assertEqual(model.name, '产品规划')
        with self.assertRaises(ValidationError):
            MindmapModel(name='标题\x00注入')

    def test_import_name_uses_same_server_boundary(self) -> None:
        model = MindmapImportModel(name='  导入脑图  ', root={'data': {'text': '根节点'}})
        self.assertEqual(model.name, '导入脑图')
        with self.assertRaises(ValidationError):
            MindmapImportModel(name=' ', root={'data': {'text': '根节点'}})


if __name__ == '__main__':
    unittest.main()
