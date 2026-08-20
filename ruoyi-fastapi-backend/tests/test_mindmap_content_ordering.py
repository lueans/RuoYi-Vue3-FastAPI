"""结构化脑图节点分层排序测试。"""

import unittest

from module_mindmap.dao.mindmap_content_dao import order_document_node_levels


class MindmapContentOrderingTest(unittest.TestCase):
    def test_orders_unsorted_rows_by_parent_level(self) -> None:
        rows = [
            {'node_uid': 'grandchild', 'parent_uid': 'child'},
            {'node_uid': 'root', 'parent_uid': None},
            {'node_uid': 'sibling', 'parent_uid': 'root'},
            {'node_uid': 'child', 'parent_uid': 'root'},
        ]

        levels = order_document_node_levels(rows)

        self.assertEqual(
            [[row['node_uid'] for row in level] for level in levels],
            [['root'], ['sibling', 'child'], ['grandchild']],
        )

    def test_rejects_missing_parent(self) -> None:
        with self.assertRaisesRegex(ValueError, '缺失父节点'):
            order_document_node_levels([
                {'node_uid': 'root', 'parent_uid': None},
                {'node_uid': 'child', 'parent_uid': 'missing'},
            ])

    def test_rejects_unreachable_cycle(self) -> None:
        with self.assertRaisesRegex(ValueError, '循环或不可达'):
            order_document_node_levels([
                {'node_uid': 'root', 'parent_uid': None},
                {'node_uid': 'a', 'parent_uid': 'b'},
                {'node_uid': 'b', 'parent_uid': 'a'},
            ])

    def test_rejects_multiple_roots(self) -> None:
        with self.assertRaisesRegex(ValueError, '只能包含一个根节点'):
            order_document_node_levels([
                {'node_uid': 'root-a', 'parent_uid': None},
                {'node_uid': 'root-b', 'parent_uid': None},
            ])


if __name__ == '__main__':
    unittest.main()
