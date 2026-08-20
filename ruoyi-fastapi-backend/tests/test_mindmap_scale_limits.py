"""脑图规模限制与大文档正确性测试。"""

import unittest

from module_mindmap.service.mindmap_service import merge_node_operations
from module_mindmap.service.simple_mind_document_codec import (
    MAX_NODE_COUNT,
    MAX_TREE_DEPTH,
    SimpleMindDocumentCodec,
    validate_mindmap_tree,
)
from scripts.benchmark_mindmap_core import build_tree, count_nodes

LARGE_DOCUMENT_NODE_COUNT = 1_500


class MindmapScaleLimitsTest(unittest.TestCase):
    def test_large_balanced_document_round_trip_and_merge(self) -> None:
        tree, nodes = build_tree(LARGE_DOCUMENT_NODE_COUNT, branch_factor=8)
        encoded = SimpleMindDocumentCodec.encode(tree)
        restored = SimpleMindDocumentCodec.decode(encoded)
        nodes[-1]['data']['text'] = '已更新'
        merged = merge_node_operations(
            restored,
            tree,
            [{'type': 'node.update', 'nodeUid': nodes[-1]['data']['uid']}],
        )

        self.assertEqual(len(encoded.nodes), LARGE_DOCUMENT_NODE_COUNT)
        self.assertEqual(count_nodes(restored), LARGE_DOCUMENT_NODE_COUNT)
        self.assertEqual(count_nodes(merged), LARGE_DOCUMENT_NODE_COUNT)

    def test_rejects_document_over_node_limit(self) -> None:
        root = {'data': {'uid': 'root'}, 'children': []}
        root['children'] = [
            {'data': {'uid': f'child-{index}'}, 'children': []}
            for index in range(MAX_NODE_COUNT)
        ]

        with self.assertRaisesRegex(ValueError, '节点数量不能超过'):
            validate_mindmap_tree(root)

    def test_rejects_document_over_depth_limit_before_recursive_codec(self) -> None:
        root = current = {'data': {'uid': 'node-0'}, 'children': []}
        for index in range(1, MAX_TREE_DEPTH + 1):
            child = {'data': {'uid': f'node-{index}'}, 'children': []}
            current['children'].append(child)
            current = child

        with self.assertRaisesRegex(ValueError, '层级不能超过'):
            SimpleMindDocumentCodec.encode(root)

    def test_decode_rejects_structured_document_over_depth_limit(self) -> None:
        nodes = [{
            'node_uid': f'node-{index}',
            'parent_uid': f'node-{index - 1}' if index else None,
            'sort_order': 0,
        } for index in range(MAX_TREE_DEPTH + 1)]

        with self.assertRaisesRegex(ValueError, '层级不能超过'):
            SimpleMindDocumentCodec.decode({'root_uid': 'node-0', 'nodes': nodes})

    def test_decode_rejects_structured_document_over_node_limit(self) -> None:
        nodes = [{
            'node_uid': f'node-{index}',
            'parent_uid': None if index == 0 else 'node-0',
            'sort_order': index,
        } for index in range(MAX_NODE_COUNT + 1)]

        with self.assertRaisesRegex(ValueError, '节点数量不能超过'):
            SimpleMindDocumentCodec.decode({'root_uid': 'node-0', 'nodes': nodes})


if __name__ == '__main__':
    unittest.main()
