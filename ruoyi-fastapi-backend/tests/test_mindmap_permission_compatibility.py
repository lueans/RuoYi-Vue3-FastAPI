import unittest

from module_mindmap.permissions import mindmap_permissions


class MindmapPermissionCompatibilityTestCase(unittest.TestCase):
    def test_resource_qualified_permission_is_preferred(self) -> None:
        self.assertEqual(mindmap_permissions('query')[0], 'mindmap:mindmap:query')

    def test_legacy_permission_remains_available_during_upgrade(self) -> None:
        self.assertEqual(
            mindmap_permissions('edit'),
            ['mindmap:mindmap:edit', 'mindmap:edit'],
        )


if __name__ == '__main__':
    unittest.main()
