"""脑图标签绑定边界测试。"""
import unittest
from types import SimpleNamespace

from module_mindmap.service.mindmap_document_service import validate_tag_binding_access


class MindmapTagBindingAccessTest(unittest.TestCase):
    def test_global_active_tag_can_be_bound(self) -> None:
        validate_tag_binding_access(
            SimpleNamespace(owner_id=0, status=0, name='全局标签'),
            owner_id=42,
            is_existing=False,
        )

    def test_owner_active_tag_can_be_bound(self) -> None:
        validate_tag_binding_access(
            SimpleNamespace(owner_id=42, status=0, name='私有标签'),
            owner_id=42,
            is_existing=False,
        )

    def test_foreign_private_tag_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, '不属于当前文件所有者'):
            validate_tag_binding_access(
                SimpleNamespace(owner_id=99, status=0, name='他人标签'),
                owner_id=42,
                is_existing=False,
            )

    def test_disabled_tag_can_only_remain_on_existing_node(self) -> None:
        tag = SimpleNamespace(owner_id=42, status=1, name='已停用')
        validate_tag_binding_access(tag, owner_id=42, is_existing=True)
        with self.assertRaisesRegex(ValueError, '不能新增绑定'):
            validate_tag_binding_access(tag, owner_id=42, is_existing=False)

    def test_version_restore_can_rebind_disabled_but_not_archived_tag(self) -> None:
        validate_tag_binding_access(
            SimpleNamespace(owner_id=42, status=1, name='已停用'),
            owner_id=42,
            is_existing=False,
            allow_disabled=True,
        )
        with self.assertRaisesRegex(ValueError, '不能新增绑定'):
            validate_tag_binding_access(
                SimpleNamespace(owner_id=42, status=2, name='已归档'),
                owner_id=42,
                is_existing=False,
                allow_disabled=True,
            )


if __name__ == '__main__':
    unittest.main()
