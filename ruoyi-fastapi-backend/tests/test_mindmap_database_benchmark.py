"""脑图数据库性能基准的纯函数测试。"""

import unittest

from scripts.benchmark_mindmap_core import build_tree
from scripts.benchmark_mindmap_database import attach_tags, percentile95, summarize


class MindmapDatabaseBenchmarkTest(unittest.TestCase):
    def test_attaches_requested_number_of_rotating_tags(self) -> None:
        _tree, nodes = build_tree(4, 2)

        attach_tags(nodes, [11, 12, 13], 2)

        self.assertEqual([tag['tagId'] for tag in nodes[0]['data']['tag']], [11, 12])
        self.assertEqual([tag['tagId'] for tag in nodes[1]['data']['tag']], [12, 13])
        self.assertEqual([tag['tagId'] for tag in nodes[2]['data']['tag']], [13, 11])

    def test_rejects_more_tags_per_node_than_available(self) -> None:
        _tree, nodes = build_tree(1, 1)

        with self.assertRaisesRegex(ValueError, '每节点标签数'):
            attach_tags(nodes, [1], 2)

    def test_uses_nearest_rank_p95(self) -> None:
        self.assertEqual(percentile95([0.1, 0.2, 0.3, 0.4, 0.5]), 0.5)
        result = summarize([0.1, 0.2, 0.3], [2, 4, 3])
        self.assertEqual(result['medianSeconds'], 0.2)
        self.assertEqual(result['p95Seconds'], 0.3)
        self.assertEqual(result['sqlStatementsMedian'], 3)


if __name__ == '__main__':
    unittest.main()
