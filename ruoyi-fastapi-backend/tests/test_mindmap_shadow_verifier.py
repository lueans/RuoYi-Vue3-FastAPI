"""脑图新旧模型影子一致性测试。"""

import copy
import unittest

from module_mindmap.service.mindmap_shadow_verifier import compare_mindmap_trees
from module_mindmap.service.simple_mind_document_codec import SimpleMindDocumentCodec


def _tree() -> dict:
    return {
        'data': {
            'uid': 'root',
            'text': '根节点',
            'fontSize': 24,
            'generalization': {'uid': 'summary', 'text': '概要', 'range': [0, 1]},
            'associativeLineTargets': ['b'],
        },
        'children': [
            {
                'data': {
                    'uid': 'a',
                    'text': 'A',
                    'tag': [{'tagId': 7, 'text': '旧名称', 'style': {'fill': '#f00'}}],
                },
                'children': [],
            },
            {'data': {'uid': 'b', 'text': 'B'}, 'children': []},
        ],
    }


class MindmapShadowVerifierTest(unittest.TestCase):
    def test_round_trip_has_same_hash(self) -> None:
        legacy = _tree()
        structured = SimpleMindDocumentCodec.decode(SimpleMindDocumentCodec.encode(legacy))

        result = compare_mindmap_trees(legacy, structured)

        self.assertTrue(result.is_equal)
        self.assertEqual(result.legacy_hash, result.structured_hash)

    def test_ignores_managed_tag_name_and_style_changes(self) -> None:
        legacy = _tree()
        structured = copy.deepcopy(legacy)
        structured['children'][0]['data']['tag'][0].update({
            'text': '全局新名称',
            'style': {'fill': '#00f'},
            'definitionRevision': 9,
        })

        self.assertTrue(compare_mindmap_trees(legacy, structured).is_equal)

    def test_reports_first_semantic_difference(self) -> None:
        legacy = _tree()
        structured = copy.deepcopy(legacy)
        structured['children'][1]['data']['text'] = 'B changed'

        result = compare_mindmap_trees(legacy, structured)

        self.assertFalse(result.is_equal)
        self.assertIn('nodes', result.difference_path)
        self.assertEqual(result.legacy_value, 'B')
        self.assertEqual(result.structured_value, 'B changed')

    def test_compares_nodes_by_path_when_uids_change(self) -> None:
        legacy = _tree()
        structured = copy.deepcopy(legacy)
        structured['data']['uid'] = 'new-root'
        structured['children'][0]['data']['uid'] = 'new-a'
        structured['children'][1]['data']['uid'] = 'new-b'
        structured['data']['associativeLineTargets'] = ['new-b']

        self.assertTrue(compare_mindmap_trees(legacy, structured).is_equal)


if __name__ == '__main__':
    unittest.main()
