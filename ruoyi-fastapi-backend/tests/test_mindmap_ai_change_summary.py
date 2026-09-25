import json
import random
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from module_mindmap.ai.change_summary import summarize_committed_node_changes
from module_mindmap.ai.diff import build_document_diff
from module_mindmap.service.mindmap_ai_service import (
    MindmapAiDao,
    MindmapContentDao,
    _direct_job_change_result,
    _safe_event_payload,
)


def update(uid: str, before: dict[str, Any], after: dict[str, Any], kind: str = 'node.update') -> dict[str, Any]:
    return {'type': kind, 'nodeUid': uid, 'payload': {
        'dataChanged': True, 'previousData': before, 'data': after,
    }}


def order(parent: str, before: list[str], after: list[str]) -> dict[str, Any]:
    return {'type': 'node.update', 'nodeUid': parent, 'payload': {
        'childrenChanged': True, 'oldChildUids': before, 'childUids': after,
    }}


def summary(added: int = 0, updated: int = 0, moved: int = 0, deleted: int = 0) -> dict[str, int]:
    return {
        'added': added, 'updated': updated, 'moved': moved, 'deleted': deleted,
        'total': added + updated + moved + deleted,
    }


def test_updates_are_distinct_nodes_and_reverted_fields_cancel() -> None:
    first = [update('a', {'text': 'A'}, {'text': 'B'})]
    second = [update('a', {'text': 'B'}, {'text': 'C'})]
    assert summarize_committed_node_changes([first, second]) == summary(updated=1)
    assert summarize_committed_node_changes([
        first, second, [update('a', {'text': 'C'}, {'text': 'A'})],
    ]) == summary()


def test_only_ai_changed_fields_are_counted_not_concurrent_snapshot_content() -> None:
    assert summarize_committed_node_changes([
        [update('a', {'text': 'A', 'color': 'red'}, {'text': 'B', 'color': 'red'})],
        [update('a', {'text': 'B', 'color': 'blue'}, {'text': 'A', 'color': 'blue'})],
    ]) == summary()


def test_transient_fields_and_noops_are_not_node_changes() -> None:
    assert summarize_committed_node_changes([[
        update('a', {'text': 'A', 'isActive': False}, {'text': 'A'}),
        order('root', ['a'], ['a']),
        {'type': 'file.layout.update', 'payload': {'layout': 'logicalStructure'}},
    ]]) == summary()


def test_creation_and_deletion_cancel_across_batches_and_updates_do_not_double_count() -> None:
    create = {'type': 'node.create', 'nodeUid': 'a'}
    delete = {'type': 'node.delete', 'nodeUid': 'a', 'payload': {'deletedNodeUids': ['a']}}
    assert summarize_committed_node_changes([
        [create], [update('a', {'text': 'A'}, {'text': 'B'})],
    ]) == summary(added=1)
    assert summarize_committed_node_changes([[create], [delete]]) == summary()
    assert summarize_committed_node_changes([
        [update('a', {'text': 'A'}, {'text': 'B'})], [delete],
    ]) == summary(deleted=1)


def test_subtree_delete_counts_distinct_nodes() -> None:
    assert summarize_committed_node_changes([[
        {'type': 'node.delete', 'nodeUid': 'a', 'payload': {'deletedNodeUids': ['a', 'b', 'b']}},
        {'type': 'node.delete', 'nodeUid': 'b'},
    ]]) == summary(deleted=2)


def test_tag_snapshots_support_cross_batch_reversion() -> None:
    assert summarize_committed_node_changes([
        [update('a', {'tag': []}, {'tag': [{'tagId': 1}]}, 'node.tag.bind')],
        [update('a', {'tag': [{'tagId': 1}]}, {'tag': []}, 'node.tag.unbind')],
    ]) == summary()


def test_concurrent_tag_and_nested_fields_are_not_adopted_by_ai_projection() -> None:
    assert summarize_committed_node_changes([
        [update('a', {'tag': []}, {'tag': [{'tagId': 1}]}, 'node.tag.bind')],
        [update('a', {'tag': [{'tagId': 1}, {'tagId': 2}]}, {'tag': [{'tagId': 2}]}, 'node.tag.unbind')],
    ]) == summary()
    assert summarize_committed_node_changes([
        [update('a', {}, {'tag': [{'tagId': 1}]}, 'node.tag.bind')],
        [update('a', {'tag': [{'tagId': 1}, {'tagId': 2}]}, {'tag': [{'tagId': 2}]}, 'node.tag.unbind')],
    ]) == summary()
    assert summarize_committed_node_changes([
        [update('a', {'style': {'color': 'red', 'size': 10}}, {'style': {'color': 'blue', 'size': 10}})],
        [update('a', {'style': {'color': 'blue', 'size': 20}}, {'style': {'color': 'red', 'size': 20}})],
    ]) == summary()


def test_cross_parent_move_does_not_count_passive_sibling_shift_and_can_be_reverted() -> None:
    forward = [order('p', ['a', 'b'], ['b']), order('q', [], ['a'])]
    backward = [order('q', ['a'], []), order('p', ['b'], ['a', 'b'])]
    assert summarize_committed_node_changes([forward]) == summary(moved=1)
    assert summarize_committed_node_changes([forward, backward]) == summary()


def test_same_parent_relative_order_matches_document_diff_and_reverts() -> None:
    forward = [order('root', ['a', 'b', 'c'], ['c', 'b', 'a'])]
    backward = [order('root', ['c', 'b', 'a'], ['a', 'b', 'c'])]
    assert summarize_committed_node_changes([forward]) == summary(moved=2)
    assert summarize_committed_node_changes([forward, backward]) == summary()


def test_concurrent_sibling_reordering_is_not_replayed_into_ai_projection() -> None:
    assert summarize_committed_node_changes([
        [order('p', ['a', 'b', 'c'], ['b', 'c']), order('q', [], ['a'])],
        # Someone else reordered b/c. AI only returns a to its old position.
        [order('q', ['a'], []), order('p', ['c', 'b'], ['a', 'c', 'b'])],
    ]) == summary()


def test_create_delete_membership_does_not_move_remaining_siblings() -> None:
    assert summarize_committed_node_changes([[
        {'type': 'node.create', 'nodeUid': 'new'},
        {'type': 'node.delete', 'nodeUid': 'a'},
        order('p', ['a', 'b'], ['new', 'b']),
    ]]) == summary(added=1, deleted=1)


def test_concurrent_parent_change_does_not_redefine_original_parent() -> None:
    assert summarize_committed_node_changes([
        [order('p', ['a', 'b'], ['b']), order('q', [], ['a'])],
        # A collaborator moved a from q to r. AI returns it to p; this must
        # also remove a from its projected q, without counting r as original.
        [order('r', ['a'], []), order('p', ['b'], ['a', 'b'])],
    ]) == summary()


def test_random_multi_batch_moves_match_final_document_diff() -> None:
    rng = random.Random(8124)
    for _ in range(150):
        state = {'p': ['a', 'b', 'c'], 'q': ['d', 'e'], 'r': []}
        initial = deepcopy(state)
        groups = []
        for _ in range(12):
            before = deepcopy(state)
            source = rng.choice([key for key in state if state[key]])
            uid = rng.choice(state[source])
            state[source].remove(uid)
            target = rng.choice(list(state))
            state[target].insert(rng.randrange(len(state[target]) + 1), uid)
            groups.append([order(parent, before[parent], state[parent][:])
                           for parent in state if before[parent] != state[parent]])

        def document(children: dict[str, list[str]]) -> dict[str, Any]:
            return {'root': {'data': {'uid': 'root', 'text': 'Root'}, 'children': [
                {'data': {'uid': parent, 'text': parent}, 'children': [
                    {'data': {'uid': uid, 'text': uid}, 'children': []} for uid in uids
                ]} for parent, uids in children.items()
            ]}}

        _, impact = build_document_diff(document(initial), document(state))
        assert summarize_committed_node_changes(groups) == summary(moved=impact['movedCount'])


def event(sequence: int, payload: dict[str, Any], kind: str = 'draft_changed') -> SimpleNamespace:
    return SimpleNamespace(sequence=sequence, event_type=kind, payload_json=json.dumps(payload))


def test_random_mixed_commits_keep_net_counts_after_removing_redundant_candidate_pass() -> None:
    rng = random.Random(3952)

    def document(state: dict[str, list[str]], texts: dict[str, str]) -> dict[str, Any]:
        return {'root': {'data': {'uid': 'root', 'text': 'Root'}, 'children': [
            {'data': {'uid': parent, 'text': parent}, 'children': [
                {'data': {'uid': uid, 'text': texts[uid]}, 'children': []} for uid in children
            ]} for parent, children in state.items()
        ]}}

    for _ in range(300):
        state = {'p': ['a', 'b', 'c'], 'q': ['d', 'e'], 'r': []}
        texts = {uid: uid for children in state.values() for uid in children}
        initial = document(state, texts)
        groups = []
        for step in range(20):
            kind = rng.choice(['create', 'update', 'move', 'delete']) if texts else 'create'
            if kind == 'create':
                uid = f'new-{step}'
                parent = rng.choice(list(state))
                state[parent].insert(rng.randrange(len(state[parent]) + 1), uid)
                texts[uid] = uid
                groups.append([{'type': 'node.create', 'nodeUid': uid}])
                continue
            uid = rng.choice(list(texts))
            parent = next(key for key, children in state.items() if uid in children)
            if kind == 'update':
                value = rng.choice([uid, 'changed', 'changed again'])
                groups.append([update(uid, {'text': texts[uid]}, {'text': value})])
                texts[uid] = value
            elif kind == 'delete':
                state[parent].remove(uid)
                del texts[uid]
                groups.append([{'type': 'node.delete', 'nodeUid': uid, 'payload': {'deletedNodeUids': [uid]}}])
            else:
                before = deepcopy(state)
                state[parent].remove(uid)
                target = rng.choice(list(state))
                state[target].insert(rng.randrange(len(state[target]) + 1), uid)
                groups.append([order(key, before[key], state[key][:])
                               for key in state if before[key] != state[key]])
        _, impact = build_document_diff(initial, document(state, texts))
        assert summarize_committed_node_changes(groups) == summary(
            added=impact['createdCount'], updated=impact['updatedCount'],
            moved=impact['movedCount'], deleted=impact['deletedCount'],
        )


def install_events(
    monkeypatch: pytest.MonkeyPatch, events: list[SimpleNamespace], rows: list[SimpleNamespace],
) -> AsyncMock:
    monkeypatch.setattr(MindmapAiDao, 'list_events', AsyncMock(return_value=events))
    read = AsyncMock(return_value=rows)
    monkeypatch.setattr(MindmapContentDao, 'get_changes_by_mutations', read)
    return read


@pytest.mark.asyncio
async def test_job_recomputes_legacy_totals_from_owned_groups_and_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    def commit(group: str) -> dict[str, Any]:
        return {'directCommit': {'operationGroupId': group, 'changeSummary': summary(updated=1)}}

    read = install_events(monkeypatch, [
        event(1, commit('g1')), event(2, commit('g2')), event(3, commit('g2')),
        event(4, {'directCommit': {**commit('g2')['directCommit'], 'idempotentReplay': True}}),
        event(5, {'changeSummary': summary(updated=2)}, 'direct_completed'),
    ], [
        SimpleNamespace(client_mutation_id='g2', operations=[update('a', {'text': 'B'}, {'text': 'A'})]),
        SimpleNamespace(client_mutation_id='g1', operations=[update('a', {'text': 'A'}, {'text': 'B'})]),
    ])
    assert await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9)) == {
        'changeSummary': summary(), 'changeSummaryVersion': 2,
    }
    assert read.await_args.args[1:] == (9, ['g1', 'g2'])


@pytest.mark.asyncio
async def test_job_reconstructs_real_seven_batch_84_node_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    sizes = [8, 12, 12, 12, 12, 16, 12]
    install_events(monkeypatch, [event(index + 1, {'directCommit': {
        'operationGroupId': f'g{index}', 'changeSummary': summary(added=size),
    }}) for index, size in enumerate(sizes)], [
        SimpleNamespace(client_mutation_id=f'g{index}', operations=[
            {'type': 'node.create', 'nodeUid': f'{index}-{node}'} for node in range(size)
        ]) for index, size in enumerate(sizes)
    ])
    compute = Mock(wraps=summarize_committed_node_changes)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.summarize_committed_node_changes', compute)
    result = await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9))
    assert result == {'changeSummary': summary(added=84), 'changeSummaryVersion': 2}
    compute.assert_called_once()
    assert len(compute.call_args.args[0]) == len(sizes)


@pytest.mark.asyncio
async def test_partial_legacy_history_uses_terminal_without_computing_discarded_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_events(monkeypatch, [
        event(1, {'directCommit': {'operationGroupId': 'saved'}}),
        event(2, {'directCommit': {'operationGroupId': 'expired'}}),
        event(3, {'changeSummary': summary(added=84)}, 'direct_completed'),
    ], [SimpleNamespace(client_mutation_id='saved', operations=[{'type': 'node.create', 'nodeUid': 'a'}])])
    compute = Mock(wraps=summarize_committed_node_changes)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.summarize_committed_node_changes', compute)
    result = await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9))
    assert result == {'changeSummary': summary(added=84), 'changeSummaryVersion': 1}
    compute.assert_not_called()


@pytest.mark.asyncio
async def test_missing_terminal_still_combines_available_logs_and_legacy_event_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_events(monkeypatch, [
        event(1, {'directCommit': {'operationGroupId': 'saved'}}),
        event(2, {'directCommit': {'operationGroupId': 'expired', 'changeSummary': summary(added=3)}}),
        event(3, {'directCommit': {'operationGroupId': 'expired', 'changeSummary': summary(added=3)}}),
        event(4, {'directCommit': {'operationCount': 0, 'changeSummary': summary()}}),
    ], [SimpleNamespace(client_mutation_id='saved', operations=[
        {'type': 'node.create', 'nodeUid': 'a'}, {'type': 'node.create', 'nodeUid': 'b'},
    ])])
    compute = Mock(wraps=summarize_committed_node_changes)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.summarize_committed_node_changes', compute)
    result = await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9))
    assert result == {'changeSummary': summary(added=5), 'changeSummaryVersion': 1}
    compute.assert_called_once()


@pytest.mark.asyncio
async def test_missing_logs_fall_back_to_complete_receipt_not_partial_reconstruction(monkeypatch: pytest.MonkeyPatch) -> None:
    install_events(monkeypatch, [
        event(1, {'directCommit': {'operationGroupId': 'gone', 'changeSummary': summary(added=8)}}),
        event(2, {'changeSummary': summary(added=84)}, 'direct_completed'),
    ], [])
    assert await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9)) == {
        'changeSummary': summary(added=84), 'changeSummaryVersion': 1,
    }


@pytest.mark.asyncio
async def test_versioned_terminal_summary_does_not_require_expired_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    read = install_events(monkeypatch, [event(1, {
        'changeSummary': summary(updated=1), 'changeSummaryVersion': 2,
    }, 'direct_completed')], [])
    result = await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9))
    assert result == {'changeSummary': summary(updated=1), 'changeSummaryVersion': 2}
    read.assert_not_awaited()
    assert _safe_event_payload(result) == result


@pytest.mark.asyncio
async def test_present_but_incomplete_legacy_log_is_not_labeled_net_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    install_events(monkeypatch, [
        event(1, {'directCommit': {'operationGroupId': 'g1'}}),
        event(2, {'directCommit': {'operationGroupId': 'g2'}}),
    ], [
        SimpleNamespace(client_mutation_id='g1', operations=[
            {'type': 'node.tag.bind', 'nodeUid': 'a', 'payload': {'tag': {'tagId': 1}}},
        ]),
        SimpleNamespace(client_mutation_id='g2', operations=[
            {'type': 'node.tag.unbind', 'nodeUid': 'a', 'payload': {'tagId': 1}},
        ]),
    ])
    result = await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9))
    assert result['changeSummaryVersion'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['failed', 'cancelled', 'stale'])
async def test_interrupted_tasks_count_only_durable_commits(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    install_events(monkeypatch, [
        event(1, {'directCommit': {'operationGroupId': 'saved', 'changeSummary': summary(added=1)}}),
        event(2, {'changeSummary': summary(added=20)}),  # uncommitted draft
        event(3, {'directCommit': {'operationCount': 0, 'changeSummary': summary()}}),
    ], [SimpleNamespace(client_mutation_id='saved', operations=[{'type': 'node.create', 'nodeUid': 'a'}])])
    result = await _direct_job_change_result(object(), SimpleNamespace(id='job', source_mindmap_id=9, status=status))
    assert result == {'changeSummary': summary(added=1), 'changeSummaryVersion': 2}
