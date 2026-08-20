import unittest

from module_mindmap.service.simple_mind_document_codec import (
    MAX_STABLE_UID_LENGTH,
    MAX_TREE_DEPTH,
    SimpleMindDocumentCodec,
)

EXPECTED_NODE_COUNT = 3
EXPECTED_GENERATED_UID_NODE_COUNT = 2
EXPECTED_ROOT_FONT_SIZE = 28
EXPECTED_TAG_ID = 7
ASSERTIONS = unittest.TestCase()


def _sample_tree() -> dict:
    return {
        'data': {
            'uid': 'root',
            'text': '<p>中心主题</p>',
            'richText': True,
            'expand': True,
            'imgMap': {'asset-1': 'data:image/png;base64,AAAA'},
            'fontSize': 28,
            '_business': {'caseId': 9},
            'futurePluginData': {'enabled': True},
            'isActive': True,
            'associativeLineTargets': ['child-b'],
            'associativeLineTargetControlOffsets': [[{'x': 1, 'y': 2}, {'x': 3, 'y': 4}]],
            'associativeLinePoint': [{'startPoint': {'dir': 'right'}, 'endPoint': {'dir': 'left'}}],
            'associativeLineText': {'child-b': '依赖'},
            'associativeLineStyle': {'child-b': {'associativeLineColor': '#f00'}},
            'generalization': {
                'uid': 'summary-1',
                'text': '概要',
                'range': [0, 1],
                'fontSize': 16,
            },
        },
        'children': [
            {
                'data': {
                    'uid': 'child-a',
                    'text': '节点A',
                    'image': 'asset-1',
                    'imageSize': {'width': 100, 'height': 80},
                    'tag': [{
                        'tagId': 7,
                        'text': '高优先级',
                        'style': {'fill': '#f00'},
                        'placement': 'bottom',
                    }],
                    'outerFrame': {
                        'groupId': 'frame-1',
                        'text': '阶段一',
                        'style': {'strokeColor': '#409eff'},
                    },
                },
                'children': [],
                'customEnvelope': {'source': 'import'},
            },
            {
                'data': {
                    'uid': 'child-b',
                    'text': '节点B',
                    'note': '备注',
                    'outerFrame': {
                        'groupId': 'frame-1',
                        'text': '阶段一',
                        'style': {'strokeColor': '#409eff'},
                    },
                },
                'children': [],
            },
        ],
    }


def _structured_node(uid: str, parent_uid: str | None, sort_order: int = 0) -> dict:
    return {
        'node_uid': uid,
        'parent_uid': parent_uid,
        'sort_order': sort_order,
        'text_content': uid,
    }


def test_codec_extracts_all_simple_mind_structures() -> None:
    encoded = SimpleMindDocumentCodec.encode(_sample_tree())

    assert encoded.root_uid == 'root'
    assert len(encoded.nodes) == EXPECTED_NODE_COUNT
    assert len(encoded.node_tags) == 1
    assert len(encoded.relations) == 1
    assert len(encoded.summaries) == 1
    assert len(encoded.groups) == 1
    assert len(encoded.assets) == 1

    root = next(node for node in encoded.nodes if node['node_uid'] == 'root')
    assert root['text_plain'] == '中心主题'
    assert root['style_data']['fontSize'] == EXPECTED_ROOT_FONT_SIZE
    assert root['extension_data']['futurePluginData'] == {'enabled': True}
    assert root['extension_data']['_business'] == {'caseId': 9}
    assert 'isActive' not in root['extension_data']

    child = next(node for node in encoded.nodes if node['node_uid'] == 'child-a')
    assert child['content_data']['image'] == 'asset-1'
    assert child['envelope_data']['customEnvelope'] == {'source': 'import'}
    assert encoded.summaries[0]['start_child_uid'] == 'child-a'
    assert encoded.summaries[0]['end_child_uid'] == 'child-b'
    assert encoded.groups[0]['member_uids'] == ['child-a', 'child-b']


def test_codec_round_trip_restores_component_shape() -> None:
    encoded = SimpleMindDocumentCodec.encode(_sample_tree())
    restored = SimpleMindDocumentCodec.decode(encoded)

    assert restored['data']['uid'] == 'root'
    assert restored['data']['text'] == '<p>中心主题</p>'
    assert restored['data']['richText'] is True
    assert restored['data']['futurePluginData'] == {'enabled': True}
    assert restored['data']['imgMap'] == {'asset-1': 'data:image/png;base64,AAAA'}
    assert 'isActive' not in restored['data']

    assert [node['data']['uid'] for node in restored['children']] == ['child-a', 'child-b']
    first = restored['children'][0]
    assert first['customEnvelope'] == {'source': 'import'}
    assert first['data']['tag'][0]['tagId'] == EXPECTED_TAG_ID
    assert first['data']['outerFrame']['groupId'] == 'frame-1'
    assert restored['children'][1]['data']['outerFrame']['groupId'] == 'frame-1'

    assert restored['data']['associativeLineTargets'] == ['child-b']
    assert restored['data']['associativeLineText']['child-b'] == '依赖'
    summary = restored['data']['generalization'][0]
    assert summary['uid'] == 'summary-1'
    assert summary['range'] == [0, 1]


def test_codec_generates_stable_node_uids_before_range_resolution() -> None:
    root = {
        'data': {'text': 'root', 'generalization': {'text': 'summary', 'range': [0, 0]}},
        'children': [{'data': {'text': 'child'}, 'children': []}],
    }
    encoded = SimpleMindDocumentCodec.encode(root)

    assert encoded.root_uid
    assert encoded.summaries[0]['start_child_uid']
    assert encoded.summaries[0]['end_child_uid'] == encoded.summaries[0]['start_child_uid']
    restored = SimpleMindDocumentCodec.decode(encoded)
    assert restored['data']['generalization'][0]['range'] == [0, 0]


def test_codec_hashes_long_associative_relation_identity_to_database_limit() -> None:
    root_uid = 'r' * 32
    child_uid = 'c' * 32
    tree = {
        'data': {'uid': root_uid, 'associativeLineTargets': [child_uid]},
        'children': [{'data': {'uid': child_uid}, 'children': []}],
    }

    first = SimpleMindDocumentCodec.encode(tree)
    second = SimpleMindDocumentCodec.encode(tree)

    assert len(first.relations[0]['relation_uid']) == MAX_STABLE_UID_LENGTH
    assert first.relations[0]['relation_uid'].startswith('assoc:')
    assert first.relations[0]['relation_uid'] == second.relations[0]['relation_uid']
    assert SimpleMindDocumentCodec.decode(first)['data']['associativeLineTargets'] == [child_uid]


def test_codec_rejects_duplicate_uids_instead_of_rewriting_references() -> None:
    root = {
        'data': {'uid': 'root', 'associativeLineTargets': ['duplicate']},
        'children': [
            {'data': {'uid': 'duplicate', 'text': 'first'}, 'children': []},
            {'data': {'uid': 'duplicate', 'text': 'second'}, 'children': []},
        ],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, 'UID 重复: duplicate'):
        SimpleMindDocumentCodec.encode(root)


def test_codec_rejects_cyclic_node_objects() -> None:
    root = {'data': {'uid': 'root'}, 'children': []}
    child = {'data': {'uid': 'child'}, 'children': [root]}
    root['children'].append(child)

    with ASSERTIONS.assertRaisesRegex(ValueError, '循环或重复引用'):
        SimpleMindDocumentCodec.encode(root)


def test_codec_rejects_node_object_shared_by_multiple_parents() -> None:
    shared = {'data': {'uid': 'shared'}, 'children': []}
    root = {
        'data': {'uid': 'root'},
        'children': [
            {'data': {'uid': 'left'}, 'children': [shared]},
            {'data': {'uid': 'right'}, 'children': [shared]},
        ],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, '循环或重复引用'):
        SimpleMindDocumentCodec.encode(root)


def test_codec_rejects_shared_uidless_node_data() -> None:
    shared_data = {'text': 'shared data'}
    root = {
        'data': {'uid': 'root'},
        'children': [
            {'data': shared_data, 'children': []},
            {'data': shared_data, 'children': []},
        ],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, '循环或重复引用'):
        SimpleMindDocumentCodec.encode(root)


def test_codec_keeps_existing_uids_and_only_fills_missing_values() -> None:
    root = {
        'data': {'uid': 7, 'text': 'root'},
        'children': [{'data': {'text': 'child'}, 'children': []}],
    }

    encoded = SimpleMindDocumentCodec.encode(root)

    assert encoded.root_uid == '7'
    assert len({row['node_uid'] for row in encoded.nodes}) == EXPECTED_GENERATED_UID_NODE_COUNT
    assert encoded.nodes[1]['node_uid']
    assert 'uid' not in root['children'][0]['data']


def test_codec_accepts_the_configured_maximum_tree_depth_without_recursion_error() -> None:
    root = {'data': {'uid': 'node-0'}, 'children': []}
    current = root
    for depth in range(1, MAX_TREE_DEPTH):
        child = {'data': {'uid': f'node-{depth}'}, 'children': []}
        current['children'].append(child)
        current = child

    encoded = SimpleMindDocumentCodec.encode(root)
    restored = SimpleMindDocumentCodec.decode(encoded)

    assert len(encoded.nodes) == MAX_TREE_DEPTH
    assert encoded.nodes[-1]['node_uid'] == f'node-{MAX_TREE_DEPTH - 1}'
    current = restored
    for _depth in range(1, MAX_TREE_DEPTH):
        current = current['children'][0]
    assert current['data']['uid'] == f'node-{MAX_TREE_DEPTH - 1}'


def test_codec_decode_rejects_duplicate_node_rows() -> None:
    document = {
        'root_uid': 'root',
        'nodes': [_structured_node('root', None), _structured_node('root', None)],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, 'UID 重复: root'):
        SimpleMindDocumentCodec.decode(document)


def test_codec_decode_rejects_missing_parent_rows() -> None:
    document = {
        'root_uid': 'root',
        'nodes': [_structured_node('root', None), _structured_node('orphan', 'missing')],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, '缺失父节点: orphan'):
        SimpleMindDocumentCodec.decode(document)


def test_codec_decode_rejects_multiple_roots() -> None:
    document = {
        'root_uid': 'root-a',
        'nodes': [_structured_node('root-a', None), _structured_node('root-b', None)],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, '必须且只能包含一个根节点'):
        SimpleMindDocumentCodec.decode(document)


def test_codec_decode_rejects_unreachable_cycle() -> None:
    document = {
        'root_uid': 'root',
        'nodes': [
            _structured_node('root', None),
            _structured_node('cycle-a', 'cycle-b'),
            _structured_node('cycle-b', 'cycle-a'),
        ],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, '循环或不可达节点'):
        SimpleMindDocumentCodec.decode(document)


def test_codec_decode_rejects_declared_root_that_is_not_the_topology_root() -> None:
    document = {
        'root_uid': 'child',
        'nodes': [_structured_node('root', None), _structured_node('child', 'root')],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, '根节点与父子拓扑不一致'):
        SimpleMindDocumentCodec.decode(document)


def test_codec_decode_infers_an_omitted_root_and_keeps_sibling_order() -> None:
    document = {
        'nodes': [
            _structured_node('child-b', 'root', 1),
            _structured_node('root', None),
            _structured_node('child-a', 'root', 0),
        ],
    }

    restored = SimpleMindDocumentCodec.decode(document)

    assert restored['data']['uid'] == 'root'
    assert [child['data']['uid'] for child in restored['children']] == ['child-a', 'child-b']


def test_codec_decode_rejects_malformed_node_row_fields() -> None:
    cases = [
        ('结构化节点必须是数组', {'nodes': 'not-a-list'}),
        ('结构化节点必须是数组', {'nodes': {}}),
        ('结构化节点必须是对象', {'nodes': ['not-an-object']}),
        ('缺少稳定 UID', {'nodes': [_structured_node('', None)]}),
        ('稳定 UID 不能超过 64 个字符', {
            'nodes': [_structured_node('n' * 65, None)],
        }),
        ('排序值非法', {'nodes': [{**_structured_node('root', None), 'sort_order': 'invalid'}]}),
        ('必须且只能包含一个根节点', {
            'nodes': [_structured_node('a', 'b'), _structured_node('b', 'a')],
        }),
        ('根节点 UID 不存在: missing', {
            'root_uid': 'missing',
            'nodes': [_structured_node('root', None)],
        }),
    ]

    for message, document in cases:
        with (
            ASSERTIONS.subTest(message=message),
            ASSERTIONS.assertRaisesRegex(ValueError, message),
        ):
            SimpleMindDocumentCodec.decode(document)


def test_codec_decode_rejects_malformed_or_dangling_component_rows() -> None:
    root = _structured_node('root', None)
    child = _structured_node('child', 'root')
    cases = [
        ('标签绑定必须是数组', {'node_tags': {}}),
        ('标签绑定记录必须是对象', {'node_tags': ['invalid']}),
        ('标签绑定引用不存在的节点', {'node_tags': [{'node_uid': 'missing'}]}),
        ('关联线记录必须是对象', {'relations': ['invalid']}),
        ('关联线引用不存在的节点', {
            'relations': [{
                'relation_uid': 'relation-1',
                'source_uid': 'root',
                'target_uid': 'missing',
            }],
        }),
        ('关联线 UID 重复', {
            'relations': [
                {'relation_uid': 'duplicate', 'source_uid': 'root', 'target_uid': 'child'},
                {'relation_uid': 'duplicate', 'source_uid': 'child', 'target_uid': 'root'},
            ],
        }),
        ('关联线不能指向自身', {
            'relations': [{
                'relation_uid': 'relation-1',
                'source_uid': 'root',
                'target_uid': 'root',
            }],
        }),
        ('概要范围必须同时包含起止节点', {
            'summaries': [{
                'summary_uid': 'summary-1',
                'owner_uid': 'root',
                'start_child_uid': 'child',
            }],
        }),
        ('概要范围必须引用所属节点的直接子节点', {
            'summaries': [{
                'summary_uid': 'summary-1',
                'owner_uid': 'child',
                'start_child_uid': 'child',
                'end_child_uid': 'child',
            }],
        }),
        ('概要范围起点不能晚于终点', {
            'nodes': [
                root,
                _structured_node('first', 'root', 0),
                _structured_node('second', 'root', 1),
            ],
            'summaries': [{
                'summary_uid': 'summary-1',
                'owner_uid': 'root',
                'start_child_uid': 'second',
                'end_child_uid': 'first',
            }],
        }),
        ('外框成员必须是非空数组', {
            'groups': [{'group_uid': 'group-1', 'parent_uid': 'root', 'member_uids': []}],
        }),
        ('外框成员必须是同一父节点下的直接子节点', {
            'groups': [{
                'group_uid': 'group-1',
                'parent_uid': 'child',
                'member_uids': ['child'],
            }],
        }),
        ('外框成员必须是连续的兄弟节点', {
            'nodes': [
                root,
                _structured_node('first', 'root', 0),
                _structured_node('middle', 'root', 1),
                _structured_node('last', 'root', 2),
            ],
            'groups': [{
                'group_uid': 'group-1',
                'parent_uid': 'root',
                'member_uids': ['first', 'last'],
            }],
        }),
        ('资源 UID 重复', {
            'assets': [{'asset_key': 'asset-1'}, {'asset_key': 'asset-1'}],
        }),
        ('资源稳定 UID 不能超过 128 个字符', {
            'assets': [{'asset_key': 'a' * 129}],
        }),
    ]

    for message, components in cases:
        document = {'root_uid': 'root', 'nodes': [root, child], **components}
        with (
            ASSERTIONS.subTest(message=message),
            ASSERTIONS.assertRaisesRegex(ValueError, message),
        ):
            SimpleMindDocumentCodec.decode(document)


def test_codec_encode_rejects_components_that_cannot_be_persisted_losslessly() -> None:
    tree = {
        'data': {'uid': 'root'},
        'children': [{
            'data': {
                'uid': 'child',
                'generalization': {'uid': 'summary-1', 'range': [0, 0]},
            },
            'children': [],
        }],
    }

    with ASSERTIONS.assertRaisesRegex(ValueError, '概要范围必须同时包含起止节点'):
        SimpleMindDocumentCodec.encode(tree)
