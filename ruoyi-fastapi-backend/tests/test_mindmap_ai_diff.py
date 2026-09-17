from module_mindmap.ai.diff import build_document_diff

DELETED_NODE_COUNT = 2


def _document(children: list[dict], *, layout: str = 'logicalStructure') -> dict:
    return {
        'root': {'data': {'uid': 'root', 'text': '根'}, 'children': children},
        'layout': layout,
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }


def _node(uid: str, text: str, children: list[dict] | None = None) -> dict:
    return {'data': {'uid': uid, 'text': text}, 'children': children or []}


def test_diff_distinguishes_update_move_create_and_delete() -> None:
    before = _document([
        _node('a', 'A', [_node('a1', 'A1')]),
        _node('b', 'B', [_node('b1', 'B1')]),
    ])
    after = _document([
        _node('b', 'B renamed', [_node('a1', 'A1'), _node('c', 'C')]),
    ])

    operations, impact = build_document_diff(before, after)

    assert {item['type'] for item in operations} == {
        'create_node', 'update_node', 'move_node', 'delete_subtree',
    }
    assert impact['createdCount'] == 1
    assert impact['updatedCount'] == 1
    assert impact['movedCount'] == 1
    assert impact['deletedCount'] == DELETED_NODE_COUNT
    assert impact['deletedSubtrees'][0]['path'] == '根 / A'


def test_diff_marks_large_or_ten_percent_deletion_as_high_impact() -> None:
    before = _document([_node(f'n{index}', f'N{index}') for index in range(10)])
    after = _document([_node(f'n{index}', f'N{index}') for index in range(8)])

    _operations, impact = build_document_diff(before, after)

    assert impact['deletedCount'] == DELETED_NODE_COUNT
    assert impact['highImpact'] is True
    assert '10%' in impact['highImpactReasons'][0]
