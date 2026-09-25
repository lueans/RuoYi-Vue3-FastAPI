from copy import deepcopy

import pytest

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


def test_even_one_deletion_in_large_map_requires_destructive_review() -> None:
    before = _document([_node(f'n{index}', f'N{index}') for index in range(100)])
    after = deepcopy(before)
    after['root']['children'].pop()
    _, impact = build_document_diff(before, after)
    assert impact['deletedCount'] == 1
    assert impact['riskLevel'] == 'R3'
    assert impact['requiresApproval'] is True
    assert impact['highImpact'] is True


@pytest.mark.parametrize('change', ['cross_branch', 'reorder', 'root', 'bulk', 'majority', 'metadata'])
def test_structural_and_destructive_changes_require_review(change: str) -> None:
    before = _document([_node(f'n{index}', f'N{index}') for index in range(30)])
    after = deepcopy(before)
    children = after['root']['children']
    expected = 'R2'
    if change == 'cross_branch':
        children[0]['children'].append(children.pop())
    elif change == 'reorder':
        children.reverse()
    elif change == 'root':
        after['root']['data']['text'] = '新主题'
        expected = 'R3'
    elif change in {'bulk', 'majority'}:
        for child in children[:7 if change == 'bulk' else 20]:
            child['data']['text'] += ' revised'
        expected = 'R3' if change == 'majority' else 'R2'
    else:
        after['layout'] = 'mindMap'
    _, impact = build_document_diff(before, after)
    assert impact['riskLevel'] == expected
    assert impact['requiresApproval'] is True
    assert impact['highImpactReasons']


def test_new_sibling_insertion_is_not_misclassified_as_existing_node_reorder() -> None:
    before = _document([_node('a', 'A'), _node('b', 'B')])
    after = deepcopy(before)
    after['root']['children'].insert(0, _node('new', 'New'))
    after['root']['children'][1]['data']['text'] = 'A revised'
    operations, impact = build_document_diff(before, after)
    assert any(op['type'] == 'move_node' for op in operations)
    assert impact['movedCount'] == 0
    assert impact['riskLevel'] == 'R1'
    assert impact['requiresApproval'] is False


def test_unchanged_document_has_read_only_risk() -> None:
    before = _document([_node('a', 'A')])
    operations, impact = build_document_diff(before, deepcopy(before))
    assert operations == []
    assert impact['riskLevel'] == 'R0'
    assert impact['requiresApproval'] is False
