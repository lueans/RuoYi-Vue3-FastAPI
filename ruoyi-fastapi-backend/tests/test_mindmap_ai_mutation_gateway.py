from copy import deepcopy
from random import Random
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from exceptions.exception import ServiceException
from module_mindmap.ai.document import (
    compute_document_hash,
    normalize_ai_editable_source_document,
)
from module_mindmap.entity.vo.mindmap_comment_vo import MindmapCommentCreateModel
from module_mindmap.entity.vo.mindmap_vo import MindmapContentBatchModel
from module_mindmap.service.mindmap_ai_mutation_gateway import (
    MindmapAiMutationGateway,
    _canonical_tag_delta,
    _document_from_detail,
    _find_node,
    _resolve_existing_tags,
)
from module_mindmap.service.mindmap_service import merge_node_operations

BASE_CONTENT_REVISION = 8
SAVED_CONTENT_REVISION = BASE_CONTENT_REVISION + 1


def _tree() -> dict[str, Any]:
    return {'root': {'data': {'uid': 'root', 'text': 'Root'}, 'children': [
        {'data': {'uid': 'child', 'text': 'Old'}, 'children': []},
    ]}}


def _root_tree() -> dict[str, Any]:
    return _tree()['root']


def _tag_definition(tag_id: int=7) -> dict[str, Any]:
    return {
        'id': tag_id, 'ownerId': 3, 'categoryId': None, 'uuid': f'tag-{tag_id}',
        'tagKey': f'tag-{tag_id}', 'name': f'Tag {tag_id}', 'style': {},
        'status': 0, 'definitionRevision': 1,
    }


def _tag_snapshot(tag_id: int=7) -> dict[str, Any]:
    definition = _tag_definition(tag_id)
    return {
        'tagId': tag_id, 'categoryId': definition['categoryId'], 'uuid': definition['uuid'],
        'tagKey': definition['tagKey'], 'text': definition['name'], 'style': {},
        'status': 0, 'definitionRevision': 1,
    }


async def _run_effective_batch(monkeypatch: pytest.MonkeyPatch, operations: list[dict[str, Any]], *, root: dict[str, Any] | None=None, replay: bool=False) -> tuple[dict[str, Any], list[MindmapContentBatchModel]]:
    detail = SimpleNamespace(content_revision=BASE_CONTENT_REVISION, owner_id=3, node_tree=deepcopy(root or _root_tree()))
    batches = []
    db = SimpleNamespace(commit=AsyncMock())

    async def save(_db: SimpleNamespace, _mindmap_id: int, batch: MindmapContentBatchModel, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        batches.append(batch)
        # Exercise the actual canonical replay as well as the gateway counters.
        merged = merge_node_operations(detail.node_tree, batch.node_tree, [
            operation.model_dump(by_alias=True, exclude_none=True)
            for operation in batch.operations
            if not operation.type.startswith('file.')
        ])
        detail.node_tree = merged
        detail.content_revision = SAVED_CONTENT_REVISION
        if batch.layout:
            detail.layout = batch.layout
        # Normal saves deliberately omit nodeTree. The gateway must read back
        # the persisted document, not hash the submitted candidate.
        return {'contentRevision': SAVED_CONTENT_REVISION, 'changedNodes': [], 'idempotentReplay': replay}

    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        AsyncMock(return_value=detail),
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services',
        save,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapTagService.get_tag_detail',
        AsyncMock(side_effect=lambda _db, tag_id, _user: _tag_definition(tag_id)),
    )
    result = await MindmapAiMutationGateway.apply_draft_operations(
        db, 9, operations, 3, mutation_id='agent:effective:batch', commit=False, broadcast=False,
    )
    db.commit.assert_not_awaited()
    return result, batches


def _mixed_batch_trace(seed: int) -> tuple[dict, list[dict], dict, str]:
    """Independent small-tree oracle for folding interleaved intent batches."""
    random = Random(seed)
    root = _root_tree()
    root['children'].extend([
        {'data': {'uid': uid, 'text': uid}, 'children': []} for uid in ['a', 'b', 'c']
    ])
    expected = deepcopy(root)
    operations = []
    layout = 'logicalStructure'

    def descendants(node: dict) -> list[dict]:
        return [node] + [item for child in node['children'] for item in descendants(child)]

    for step in range(30):
        nodes = descendants(expected)
        node = random.choice(nodes)
        uid = node['data']['uid']
        action = random.choice(['create', 'update', 'move', 'delete', 'tags', 'layout'])
        payload = {}
        if action == 'create':
            data = {'uid': f'new-{step}', 'text': f'New {step}'}
            index = random.randrange(len(node['children']) + 1)
            payload = {'parentUid': uid, 'index': index, 'data': deepcopy(data)}
            node['children'].insert(index, {'data': data, 'children': []})
            uid = data['uid']
            kind = 'create_node'
        elif action in {'update', 'tags'}:
            patch = {'text': f'Edited {step}'} if action == 'update' else {
                'tag': [_tag_snapshot(tag_id) for tag_id in random.sample([7, 8, 9], random.randrange(4))],
            }
            node['data'].update(deepcopy(patch))
            if not node['data'].get('tag'):
                node['data'].pop('tag', None)
            payload = {'set': patch}
            kind = 'update_node'
        elif action in {'move', 'delete'}:
            if node is expected:
                continue
            parent = next(item for item in nodes if any(child is node for child in item['children']))
            parent['children'].remove(node)
            kind = 'delete_subtree'
            if action == 'move':
                destination = random.choice(descendants(expected))
                index = random.randrange(len(destination['children']) + 1)
                destination['children'].insert(index, node)
                payload = {'parentUid': destination['data']['uid'], 'index': index}
                kind = 'move_node'
        else:
            layout = random.choice(['logicalStructure', 'mindMap'])
            payload = {'set': {'layout': layout}}
            kind = 'set_document_meta'
        operations.append({'type': kind, 'nodeUid': uid, 'payload': payload})
    return root, operations, expected, layout


@pytest.mark.asyncio
@pytest.mark.parametrize('seed', range(40))
async def test_mixed_intent_batches_replay_to_final_candidate(monkeypatch: pytest.MonkeyPatch, seed: int) -> None:
    root, operations, expected, layout = _mixed_batch_trace(seed)
    result, batches = await _run_effective_batch(monkeypatch, operations, root=root)
    committed = result['_committedDocument']
    assert committed['root'] == expected
    assert committed['layout'] == layout
    normalized, _summary = normalize_ai_editable_source_document(committed)
    assert result['documentHash'] == compute_document_hash(normalized)
    if batches:
        assert batches[0].node_tree == expected


def test_gateway_tree_helpers_are_scoped_to_stable_uid() -> None:
    tree = _tree()
    assert _find_node(tree, 'child')['data']['text'] == 'Old'
    with pytest.raises(ServiceException) as error:
        _find_node(tree, 'missing')
    assert error.value.message == '目标节点不存在或已被删除'


@pytest.mark.asyncio
async def test_effective_batch_counts_actual_deleted_subtree_size(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root_tree()
    root['children'][0]['children'] = [{
        'data': {'uid': 'leaf', 'text': 'Leaf'},
        'children': [{'data': {'uid': 'grandchild', 'text': 'Grandchild'}, 'children': []}],
    }]
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'delete_subtree', 'nodeUid': 'child'},
    ], root=root)
    assert result['changeSummary'] == {
        'added': 0,
        'updated': 0,
        'moved': 0,
        'deleted': 3,
        'total': 3,
    }
    assert result['_committedDocument']['root']['children'] == []
    deletion = next(operation for operation in batches[0].operations if operation.type == 'node.delete')
    assert deletion.payload['deletedNodeUids'] == ['child', 'leaf', 'grandchild']


@pytest.mark.asyncio
async def test_apply_draft_operations_replays_create_update_move_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = SimpleNamespace(content_revision=BASE_CONTENT_REVISION, node_tree=_tree())
    captured = {}
    db = SimpleNamespace(commit=AsyncMock())

    async def read(_db: SimpleNamespace, _mindmap_id: int, _user_id: int) -> SimpleNamespace:
        return detail

    async def save(_db: SimpleNamespace, mindmap_id: int, batch: MindmapContentBatchModel, user_id: int, user_name: str, **kwargs: Any) -> dict[str, Any]:
        captured['batch'] = batch
        captured['kwargs'] = kwargs
        return {'contentRevision': SAVED_CONTENT_REVISION, 'changedNodes': ['child']}

    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        read,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services',
        save,
    )
    result = await MindmapAiMutationGateway.apply_draft_operations(
        db,
        9,
        [
            {
                'type': 'create_node',
                'nodeUid': 'new',
                'payload': {
                    'parentUid': 'root',
                    'index': 0,
                    'data': {'uid': 'new', 'text': 'New'},
                },
            },
            {
                'type': 'update_node',
                'nodeUid': 'child',
                'payload': {'set': {'text': 'Changed'}, 'unset': []},
            },
            {
                'type': 'move_node',
                'nodeUid': 'child',
                'payload': {'parentUid': 'new', 'index': 0},
            },
        ],
        3,
        mutation_id='agent:test:batch',
    )
    assert result['contentRevision'] == SAVED_CONTENT_REVISION
    batch = captured['batch']
    assert batch.base_revision == BASE_CONTENT_REVISION
    assert [operation.type for operation in batch.operations] == [
        'node.update', 'node.update', 'node.create', 'node.update',
    ]
    assert [operation.node_uid for operation in batch.operations[:2]] == ['root', 'new']
    assert all(operation.payload['childrenChanged'] for operation in batch.operations[:2])
    assert batch.node_tree['children'][0]['data']['uid'] == 'new'
    assert batch.node_tree['children'][0]['children'][0]['data']['text'] == 'Changed'
    assert captured['kwargs'] == {'commit': False, 'broadcast': False}
    assert result['changeSummary'] == {
        'added': 1,
        'updated': 1,
        'moved': 1,
        'deleted': 0,
        'total': 3,
    }
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_draft_operations_commits_comment_without_tree_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = SimpleNamespace(content_revision=2, node_tree=_tree())
    captured = {}
    db = SimpleNamespace(commit=AsyncMock())

    async def read(_db: SimpleNamespace, _mindmap_id: int, _user_id: int) -> SimpleNamespace:
        return detail

    async def create(_db: SimpleNamespace, model: MindmapCommentCreateModel, user_id: int, request_id: str, **kwargs: Any) -> dict[str, Any]:
        captured.update({
            'node_uid': model.node_uid,
            'content': model.content,
            'user_id': user_id,
            'request_id': request_id,
        })
        captured['kwargs'] = kwargs
        return {'id': 'thread-1'}

    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        read,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapCommentService.create_thread',
        create,
    )
    result = await MindmapAiMutationGateway.apply_draft_operations(
        db,
        9,
        [{
            'type': 'add_comment',
            'nodeUid': 'child',
            'payload': {'content': '请补充来源'},
        }],
        3,
        mutation_id='agent:test:comment',
    )
    assert result['commentCount'] == 1
    assert result['comments'] == [{'id': 'thread-1'}]
    assert captured == {
        'node_uid': 'child',
        'content': '请补充来源',
        'user_id': 3,
        'request_id': 'agent:test:comment:comment:0',
        'kwargs': {'commit': False, 'broadcast': False},
    }
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_draft_operations_commits_content_and_comment_before_broadcast(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = SimpleNamespace(content_revision=2, node_tree=_tree())
    committed_revision = detail.content_revision + 1
    trace = []
    db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: trace.append('commit')))

    async def read(_db: SimpleNamespace, _mindmap_id: int, _user_id: int) -> SimpleNamespace:
        return detail

    async def save(_db: SimpleNamespace, _mindmap_id: int, _batch: MindmapContentBatchModel, _user_id: int, _user_name: str, **kwargs: Any) -> dict[str, Any]:
        trace.append(('save', kwargs))
        return {
            'contentRevision': committed_revision,
            'clientMutationId': 'agent:test:atomic',
            'changedNodes': ['child'],
            'idempotentReplay': False,
        }

    async def create(_db: SimpleNamespace, _model: MindmapCommentCreateModel, _user_id: int, _request_id: str, **kwargs: Any) -> dict[str, Any]:
        trace.append(('comment', kwargs))
        return {'threadId': 41, 'commentId': 42, 'idempotentReplay': False}

    async def publish(_mindmap_id: int, _result: dict[str, Any]) -> None:
        trace.append('publish')

    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        read,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services',
        save,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapCommentService.create_thread',
        create,
    )
    monkeypatch.setattr(MindmapAiMutationGateway, 'publish_direct_commit', publish)

    result = await MindmapAiMutationGateway.apply_draft_operations(
        db,
        9,
        [
            {
                'type': 'update_node',
                'nodeUid': 'child',
                'payload': {'set': {'text': 'Changed'}, 'unset': []},
            },
            {
                'type': 'add_comment',
                'nodeUid': 'child',
                'payload': {'content': '请补充来源'},
            },
        ],
        3,
        mutation_id='agent:test:atomic',
    )

    assert trace == [
        ('save', {'commit': False, 'broadcast': False}),
        ('comment', {'commit': False, 'broadcast': False}),
        'commit',
        'publish',
    ]
    assert result['_deferredBroadcast']['content']['contentRevision'] == committed_revision
    assert result['_deferredBroadcast']['comments'] == [
        {'threadId': 41, 'nodeUid': 'child'},
    ]


@pytest.mark.asyncio
async def test_apply_draft_operations_wraps_service_root_and_hashes_full_document(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real detail service returns a bare root node, while the AI contract
    # and undo receipt use an SMM-v2 document envelope.
    detail = SimpleNamespace(
        content_revision=4,
        node_tree=_root_tree(),
        layout='logicalStructure',
        theme={'template': 'default', 'config': {}},
        view_data=None,
        document_data={},
    )
    db = SimpleNamespace(commit=AsyncMock())
    captured = {}

    async def read(_db: SimpleNamespace, _mindmap_id: int, _user_id: int) -> SimpleNamespace:
        return detail

    async def save(_db: SimpleNamespace, _mindmap_id: int, batch: MindmapContentBatchModel, _user_id: int, _user_name: str, **kwargs: Any) -> dict[str, Any]:
        captured['batch'] = batch
        captured['kwargs'] = kwargs
        root = batch.node_tree
        detail.node_tree = deepcopy(root)
        detail.content_revision = 5
        return {
            'contentRevision': 5,
            'changedNodes': ['child'],
            'layout': 'logicalStructure',
            'theme': {'template': 'default', 'config': {}},
            'viewData': None,
            'documentData': {},
            'nodeTree': root,
        }

    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        read,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services',
        save,
    )
    result = await MindmapAiMutationGateway.apply_draft_operations(
        db,
        9,
        [{
            'type': 'update_node',
            'nodeUid': 'child',
            'payload': {'set': {'text': 'Changed'}, 'unset': []},
        }],
        3,
        mutation_id='agent:test:root-only',
    )

    assert captured['batch'].node_tree['data']['uid'] == 'root'
    assert captured['kwargs'] == {'commit': False, 'broadcast': False}
    expected_document = {
        'root': captured['batch'].node_tree,
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }
    normalized, _summary = normalize_ai_editable_source_document(expected_document)
    assert result['documentHash'] == compute_document_hash(normalized)


@pytest.mark.asyncio
async def test_apply_draft_operations_hash_normalizes_view_and_blank_editor_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # The browser's source fingerprint strips viewport state and turns a blank
    # editor node into the deterministic source placeholder.  The direct
    # receipt must use that same canonical form or an immediate undo will
    # report a false document-hash conflict.
    detail = SimpleNamespace(
        content_revision=6,
        node_tree={
            'data': {'uid': 'root', 'text': ''},
            'children': [
                {'data': {'uid': 'child', 'text': 'Old'}, 'children': []},
            ],
        },
        layout='logicalStructure',
        theme={'template': 'default', 'config': {}},
        view_data={'scale': 1.25, 'x': 42, 'y': -9},
        document_data={},
    )
    db = SimpleNamespace(commit=AsyncMock())
    captured = {}

    async def read(_db: SimpleNamespace, _mindmap_id: int, _user_id: int) -> SimpleNamespace:
        return detail

    async def save(_db: SimpleNamespace, _mindmap_id: int, batch: MindmapContentBatchModel, _user_id: int, _user_name: str, **kwargs: Any) -> dict[str, Any]:
        captured['batch'] = batch
        captured['kwargs'] = kwargs
        detail.node_tree = deepcopy(batch.node_tree)
        detail.content_revision = 7
        detail.view_data = {'scale': 99, 'x': 1000, 'y': 1000}
        return {
            'contentRevision': 7,
            'changedNodes': ['child'],
            'layout': 'logicalStructure',
            'theme': {'template': 'default', 'config': {}},
            'viewData': {'scale': 99, 'x': 1000, 'y': 1000},
            'documentData': {},
            'nodeTree': batch.node_tree,
        }

    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        read,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services',
        save,
    )

    result = await MindmapAiMutationGateway.apply_draft_operations(
        db,
        9,
        [{
            'type': 'update_node',
            'nodeUid': 'child',
            'payload': {'set': {'text': 'Changed'}, 'unset': []},
        }],
        3,
        mutation_id='agent:test:normalized-hash',
    )

    persisted_document = {
        'root': captured['batch'].node_tree,
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        # Deliberately use the service's viewport payload to ensure the hash
        # implementation, rather than this fixture, performs the stripping.
        'view': {'scale': 99, 'x': 1000, 'y': 1000},
        'documentData': {},
    }
    normalized, _summary = normalize_ai_editable_source_document(persisted_document)
    assert normalized['view'] is None
    assert normalized['root']['data']['text'] == '未命名节点'
    assert result['documentHash'] == compute_document_hash(normalized)


@pytest.mark.asyncio
@pytest.mark.parametrize('operations', [
    [{'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'text': 'Old'}}}],
    [
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'text': 'Temporary'}}},
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'text': 'Old'}}},
    ],
    [{'type': 'move_node', 'nodeUid': 'child', 'payload': {'parentUid': 'root', 'index': 0}}],
    [
        {'type': 'create_node', 'nodeUid': 'temporary', 'payload': {
            'parentUid': 'root', 'data': {'uid': 'temporary', 'text': 'Temporary'},
        }},
        {'type': 'delete_subtree', 'nodeUid': 'temporary'},
    ],
    [{'type': 'set_document_meta', 'payload': {'set': {'layout': 'logicalStructure'}}}],
    [
        {'type': 'node.tag.bind', 'nodeUid': 'child', 'payload': {
            'key': 'child:7', 'tagKey': '7', 'tag': {'tagId': 7},
        }},
        {'type': 'node.tag.unbind', 'nodeUid': 'child', 'payload': {
            'key': 'child:7', 'tagKey': '7',
        }},
    ],
])
async def test_effective_batch_drops_noops_and_restorations(monkeypatch: pytest.MonkeyPatch, operations: list[dict[str, Any]]) -> None:
    result, batches = await _run_effective_batch(monkeypatch, operations)
    assert result['changeSummary'] == {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 0}
    assert result['operationCount'] == 0
    assert result['contentRevision'] == BASE_CONTENT_REVISION
    assert batches == []


@pytest.mark.asyncio
async def test_effective_batch_deduplicates_updates_and_new_node_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'text': 'First'}}},
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'text': 'Final'}}},
        {'type': 'create_node', 'nodeUid': 'new', 'payload': {
            'parentUid': 'root', 'data': {'uid': 'new', 'text': 'First new'},
        }},
        {'type': 'update_node', 'nodeUid': 'new', 'payload': {'set': {'text': 'Final new'}}},
    ])
    assert result['changeSummary'] == {'added': 1, 'updated': 1, 'moved': 0, 'deleted': 0, 'total': 2}
    expected_operation_count = 3  # One parent edge and two net node data changes.
    assert result['operationCount'] == expected_operation_count
    update = next(operation for operation in batches[0].operations if operation.node_uid == 'child')
    assert update.payload['previousData']['text'] == 'Old'
    assert update.payload['data']['text'] == 'Final'
    assert result['_committedDocument']['root']['children'][1]['data']['text'] == 'Final new'


@pytest.mark.asyncio
async def test_effective_batch_preserves_other_changes_when_temporary_node_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'create_node', 'nodeUid': 'temporary', 'payload': {
            'parentUid': 'root', 'data': {'uid': 'temporary', 'text': 'Temporary'},
        }},
        {'type': 'delete_subtree', 'nodeUid': 'temporary'},
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'text': 'Final'}}},
    ])
    assert result['changeSummary'] == {'added': 0, 'updated': 1, 'moved': 0, 'deleted': 0, 'total': 1}
    assert len(batches[0].operations) == 1
    assert [node['data']['uid'] for node in result['_committedDocument']['root']['children']] == ['child']


@pytest.mark.asyncio
@pytest.mark.parametrize('parent_uid', ['root', 'target'])
async def test_effective_batch_rejects_reusing_deleted_uid_before_persistence(monkeypatch: pytest.MonkeyPatch, parent_uid: str) -> None:
    root = _root_tree()
    root['children'].append({'data': {'uid': 'target', 'text': 'Target'}, 'children': []})
    save = AsyncMock()
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        AsyncMock(return_value=SimpleNamespace(content_revision=BASE_CONTENT_REVISION, node_tree=root)),
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services',
        save,
    )
    with pytest.raises(ServiceException) as error:
        await MindmapAiMutationGateway.apply_draft_operations(
            db, 9, [
                {'type': 'delete_subtree', 'nodeUid': 'child'},
                {'type': 'create_node', 'nodeUid': 'child', 'payload': {
                    'parentUid': parent_uid, 'data': {'uid': 'child', 'text': 'Replacement'},
                }},
            ], 3, mutation_id='agent:reuse-deleted-uid', commit=False, broadcast=False,
        )
    assert error.value.message == 'AI 新增节点不能复用本批已删除的 UID'
    save.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert root['children'][0]['data'] == {'uid': 'child', 'text': 'Old'}


@pytest.mark.asyncio
async def test_effective_batch_removes_existing_node_inside_deleted_temporary_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'create_node', 'nodeUid': 'temporary', 'payload': {
            'parentUid': 'root', 'data': {'uid': 'temporary', 'text': 'Temporary'},
        }},
        {'type': 'move_node', 'nodeUid': 'child', 'payload': {'parentUid': 'temporary', 'index': 0}},
        {'type': 'delete_subtree', 'nodeUid': 'temporary'},
    ])
    assert result['changeSummary'] == {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 1, 'total': 1}
    assert result['_committedDocument']['root']['children'] == []
    deletions = [operation for operation in batches[0].operations if operation.type == 'node.delete']
    assert [operation.node_uid for operation in deletions] == ['child']
    assert deletions[0].payload['deletedNodeUids'] == ['child']


@pytest.mark.asyncio
async def test_effective_batch_preserves_child_moved_out_before_parent_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root_tree()
    root['children'][0]['children'] = [
        {'data': {'uid': 'survivor', 'text': 'Survivor'}, 'children': []},
    ]
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'move_node', 'nodeUid': 'survivor', 'payload': {'parentUid': 'root', 'index': 1}},
        {'type': 'delete_subtree', 'nodeUid': 'child'},
    ], root=root)
    assert result['changeSummary'] == {'added': 0, 'updated': 0, 'moved': 1, 'deleted': 1, 'total': 2}
    assert [node['data']['uid'] for node in result['_committedDocument']['root']['children']] == ['survivor']
    deletion = next(operation for operation in batches[0].operations if operation.type == 'node.delete')
    assert deletion.payload['deletedNodeUids'] == ['child']


@pytest.mark.asyncio
async def test_effective_batch_cross_parent_move_does_not_count_shifted_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    def leaf(uid: str) -> dict[str, Any]:
        return {'data': {'uid': uid, 'text': uid}, 'children': []}
    root = _root_tree()
    root['children'] = [leaf('a'), leaf('b'), leaf('parent')]
    result, _ = await _run_effective_batch(monkeypatch, [
        {'type': 'move_node', 'nodeUid': 'a', 'payload': {'parentUid': 'parent', 'index': 0}},
    ], root=root)
    assert result['changeSummary'] == {'added': 0, 'updated': 0, 'moved': 1, 'deleted': 0, 'total': 1}


@pytest.mark.asyncio
async def test_effective_batch_reorder_uses_shared_sibling_ranks(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root_tree()
    root['children'] = [{'data': {'uid': uid, 'text': uid}, 'children': []} for uid in ['a', 'b', 'c']]
    result, _ = await _run_effective_batch(monkeypatch, [
        {'type': 'move_node', 'nodeUid': 'a', 'payload': {'parentUid': 'root', 'index': 2}},
    ], root=root)
    assert result['changeSummary']['moved'] == len(root['children'])


@pytest.mark.asyncio
async def test_effective_batch_metadata_and_replay_do_not_inflate_node_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'set_document_meta', 'payload': {'set': {'layout': 'mindMap'}}},
    ])
    assert result['changeSummary']['total'] == 0
    assert len(batches) == 1, 'real metadata change must still persist'
    replay, _ = await _run_effective_batch(monkeypatch, [
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'text': 'Final'}}},
    ], replay=True)
    assert replay['changeSummary']['total'] == 0


@pytest.mark.asyncio
async def test_effective_tag_batch_persists_before_after_evidence_for_task_net_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'node.tag.bind', 'nodeUid': 'child', 'payload': {
            'key': 'child:7', 'tagKey': '7', 'tag': {'tagId': 7},
        }},
    ])
    assert result['changeSummary']['updated'] == 1
    payload = batches[0].operations[0].payload
    assert payload['previousData'].get('tag', []) == []
    assert payload['data']['tag'] == [{'tagId': 7}]
    assert payload['tag'] == _tag_snapshot()


def test_tag_library_definition_changes_are_not_attributed_to_ai_bindings() -> None:
    before = [_tag_snapshot()]
    after = [{**_tag_snapshot(), 'text': 'Renamed by owner', 'definitionRevision': 2}]
    assert _canonical_tag_delta('child', before, after) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('same_batch_update', [False, True])
async def test_create_tags_are_replayed_by_explicit_binding_and_hash_actual_readback(monkeypatch: pytest.MonkeyPatch, same_batch_update: bool) -> None:
    data = {'uid': 'new', 'text': 'New'}
    operations = [{'type': 'create_node', 'nodeUid': 'new', 'payload': {'parentUid': 'root', 'data': data}}]
    if same_batch_update:
        operations.append({'type': 'update_node', 'nodeUid': 'new', 'payload': {'set': {'tag': [{'tagId': 7}]}}})
    else:
        data['tag'] = [{'tagId': 7, 'text': 'Untrusted name', 'style': {'fill': 'red'}}]
    result, batches = await _run_effective_batch(monkeypatch, operations)
    assert [op.type for op in batches[0].operations] == ['node.update', 'node.create', 'node.tag.bind']
    assert batches[0].operations[0].payload['childUids'] == ['child', 'new']
    assert 'tag' not in batches[0].operations[1].payload['data']
    document = result['_committedDocument']
    assert _find_node(document, 'new')['data']['tag'] == [_tag_snapshot()]
    normalized, _summary = normalize_ai_editable_source_document(document)
    assert result['documentHash'] == compute_document_hash(normalized)
    assert result['changeSummary'] == {'added': 1, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 1}


@pytest.mark.asyncio
@pytest.mark.parametrize('placement', [False, True])
async def test_setting_same_tag_identity_is_noop_even_with_resolved_metadata(monkeypatch: pytest.MonkeyPatch, placement: bool) -> None:
    root = _root_tree()
    tag = {**_tag_snapshot(), **({'placement': 'left', 'align': 'start'} if placement else {})}
    root['children'][0]['data']['tag'] = [tag]
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'tag': [{'tagId': 7}]}}},
    ], root=root)
    assert batches == []
    assert result['operationCount'] == 0
    assert result['contentRevision'] == BASE_CONTENT_REVISION
    assert result['changeSummary']['total'] == 0
    assert _find_node(result['_committedDocument'], 'child')['data']['tag'] == [tag]


@pytest.mark.asyncio
async def test_tag_replacement_and_order_use_binding_operations_without_replacing_other_data(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root_tree()
    root['children'][0]['data']['tag'] = [_tag_snapshot(7), _tag_snapshot(8)]
    result, batches = await _run_effective_batch(monkeypatch, [
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {
            'tag': [{'tagId': 9}, {'tagId': 8}, {'tagId': 9}],
        }}},
    ], root=root)
    assert [op.type for op in batches[0].operations] == ['node.tag.unbind', 'node.tag.bind', 'node.tag.reorder']
    data = _find_node(result['_committedDocument'], 'child')['data']
    assert data['text'] == 'Old'
    assert data['tag'] == [_tag_snapshot(9), _tag_snapshot(8)]
    assert result['changeSummary']['updated'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('tag', ['new tag', {'text': 'new tag'}, {'tagId': True}, {'tagId': '7'}, {'tagId': -1}])
@pytest.mark.parametrize('create', [True, False])
async def test_ai_never_creates_tag_definitions_from_text_or_invalid_id(monkeypatch: pytest.MonkeyPatch, tag: str | dict[str, Any], create: bool) -> None:
    operation = (
        {'type': 'create_node', 'nodeUid': 'new', 'payload': {
            'parentUid': 'root', 'data': {'uid': 'new', 'text': 'New', 'tag': [tag]},
        }} if create else
        {'type': 'update_node', 'nodeUid': 'child', 'payload': {'set': {'tag': [tag]}}}
    )
    with pytest.raises(ServiceException) as error:
        await _run_effective_batch(monkeypatch, [operation])
    assert '不能创建标签' in error.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize('definition', [
    {**_tag_definition(), 'ownerId': 99},
    {**_tag_definition(), 'status': 1},
    {**_tag_definition(), 'status': 2},
])
async def test_gateway_rejects_ineligible_existing_tag_before_save(monkeypatch: pytest.MonkeyPatch, definition: dict[str, Any]) -> None:
    save = AsyncMock()
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        AsyncMock(return_value=SimpleNamespace(content_revision=BASE_CONTENT_REVISION, owner_id=3, node_tree=_root_tree())),
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services', save,
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapTagService.get_tag_detail',
        AsyncMock(return_value=definition),
    )
    with pytest.raises(ServiceException):
        await MindmapAiMutationGateway.apply_draft_operations(
            SimpleNamespace(commit=AsyncMock()), 9, [
                {'type': 'create_node', 'nodeUid': 'new', 'payload': {
                    'parentUid': 'root', 'data': {'uid': 'new', 'text': 'New', 'tag': [{'tagId': 7}]},
                }},
            ], 3, mutation_id='ineligible-tag', commit=False, broadcast=False,
        )
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_shared_existing_private_binding_can_be_retained_but_cache_cannot_authorize_new_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_tag = AsyncMock(return_value=_tag_definition())
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapTagService.get_tag_detail', read_tag,
    )
    db = SimpleNamespace()
    cache = {}
    retained = await _resolve_existing_tags(
        db, [{'tagId': 7}], user_id=4, owner_id=3, previous_tags=[_tag_snapshot()], cache=cache,
    )
    assert retained == [_tag_snapshot()]
    read_tag.assert_awaited_once_with(db, 7, 3)
    with pytest.raises(ServiceException) as error:
        await _resolve_existing_tags(
            db, [{'tagId': 7}], user_id=4, owner_id=3, previous_tags=[], cache=cache,
        )
    assert '无权新增引用' in error.value.message
    assert read_tag.await_count == 1


@pytest.mark.asyncio
async def test_existing_disabled_tag_can_be_retained_not_copied(monkeypatch: pytest.MonkeyPatch) -> None:
    definition = {**_tag_definition(), 'status': 1}
    snapshot = {**_tag_snapshot(), 'status': 1}
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapTagService.get_tag_detail',
        AsyncMock(return_value=definition),
    )
    cache = {}
    assert await _resolve_existing_tags(
        SimpleNamespace(), [{'tagId': 7}], user_id=3, owner_id=3, previous_tags=[snapshot], cache=cache,
    ) == [snapshot]
    with pytest.raises(ServiceException):
        await _resolve_existing_tags(
            SimpleNamespace(), [{'tagId': 7}], user_id=3, owner_id=3, previous_tags=[], cache=cache,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize('remote_kind', ['independent_child', 'existing_text', 'both'])
async def test_structural_preorder_preserves_concurrent_nodes_and_existing_data(
    monkeypatch: pytest.MonkeyPatch, remote_kind: str,
) -> None:
    from module_mindmap.service.mindmap_service import analyze_concurrent_operations  # noqa: PLC0415

    baseline = {'data': {'uid': 'root', 'text': 'Root'}, 'children': [
        {'data': {'uid': 'a', 'text': 'A'}, 'children': []},
        {'data': {'uid': 'b', 'text': 'B'}, 'children': []},
    ]}
    detail = SimpleNamespace(content_revision=BASE_CONTENT_REVISION, owner_id=3, node_tree=deepcopy(baseline))
    remote = deepcopy(baseline)
    remote_operations = []
    if remote_kind in {'independent_child', 'both'}:
        remote_node = {'data': {'uid': 'remote', 'text': 'Other user'}, 'children': []}
        remote['children'].insert(1, remote_node)
        remote_operations.extend([
            {'type': 'node.update', 'nodeUid': 'root', 'payload': {
                'dataChanged': False, 'childrenChanged': True,
                'oldChildUids': ['a', 'b'], 'childUids': ['a', 'remote', 'b'],
            }},
            {'type': 'node.create', 'nodeUid': 'remote', 'payload': {'data': remote_node['data']}},
        ])
    if remote_kind in {'existing_text', 'both'}:
        remote['children'][0]['data']['text'] = 'Remote A'
        remote_operations.append({'type': 'node.update', 'nodeUid': 'a', 'payload': {
            'dataChanged': True, 'childrenChanged': False,
            'previousData': {'uid': 'a', 'text': 'A'}, 'data': {'uid': 'a', 'text': 'Remote A'},
        }})

    async def save(_db: object, _mindmap_id: int, batch: object, *_args: object, **_kwargs: object) -> dict:
        canonical = [operation.model_dump(by_alias=True, exclude_none=True) for operation in batch.operations]
        assert analyze_concurrent_operations(canonical, remote_operations, True)['mergeable'] is True
        detail.node_tree = merge_node_operations(
            remote, batch.node_tree, canonical, remote_operations=remote_operations,
        )
        detail.content_revision = 10
        return {'contentRevision': 10, 'nodeTree': detail.node_tree, 'concurrentMerge': True}

    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services',
        AsyncMock(return_value=detail),
    )
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services', save,
    )
    result = await MindmapAiMutationGateway.apply_draft_operations(
        SimpleNamespace(), 9, [
            {'type': 'create_node', 'nodeUid': 'parent', 'payload': {
                'parentUid': 'root', 'index': 0, 'data': {'uid': 'parent', 'text': 'Wrapper'},
            }},
            {'type': 'move_node', 'nodeUid': 'a', 'payload': {'parentUid': 'parent', 'index': 0}},
            {'type': 'create_node', 'nodeUid': 'leaf', 'payload': {
                'parentUid': 'a', 'index': 0, 'data': {'uid': 'leaf', 'text': 'Leaf'},
            }},
            {'type': 'update_node', 'nodeUid': 'b', 'payload': {'set': {'note': 'AI note'}}},
        ], 3, mutation_id='ai:concurrent-structure', expected_revision=8, commit=False, broadcast=False,
    )
    document = result['_committedDocument']
    moved = _find_node(document, 'parent')['children'][0]
    assert moved['data']['uid'] == 'a'
    assert moved['children'][0]['data']['uid'] == 'leaf'
    assert moved['data']['text'] == ('Remote A' if remote_kind in {'existing_text', 'both'} else 'A')
    assert _find_node(document, 'b')['data'] == {'uid': 'b', 'text': 'B', 'note': 'AI note'}
    if remote_kind in {'independent_child', 'both'}:
        assert _find_node(document, 'remote')['data']['text'] == 'Other user'
    assert result['changeSummary'] == {'added': 2, 'updated': 1, 'moved': 1, 'deleted': 0, 'total': 4}


@pytest.mark.parametrize('explicit_metadata', [False, True])
def test_gateway_detail_document_keeps_legacy_metadata_fallbacks(explicit_metadata: bool) -> None:
    root = {'data': {'uid': 'root', 'text': ''}, 'children': []}
    legacy_metadata = {
        'layout': 'mindMap', 'theme': {'template': 'legacy', 'config': {'color': 'blue'}},
        'view': {'scale': 2}, 'documentData': {'name': 'Legacy'},
    }
    detail = SimpleNamespace(node_tree={'root': root, **legacy_metadata})
    if explicit_metadata:
        detail.layout = 'fishbone'
        detail.theme = {'template': 'explicit', 'config': {}}
        detail.view_data = {'scale': 3}
        detail.document_data = {'name': 'Explicit'}

    result = _document_from_detail(detail)

    expected_metadata = {
        'layout': 'fishbone', 'theme': {'template': 'explicit', 'config': {}},
        'view': {'scale': 3}, 'documentData': {'name': 'Explicit'},
    } if explicit_metadata else legacy_metadata
    assert result == {'root': root, **expected_metadata}
    result['root']['data']['text'] = 'Mutation'
    result['theme']['config']['color'] = 'red'
    result['view']['scale'] = 4
    result['documentData']['name'] = 'Mutation'
    assert root['data']['text'] == ''
    assert legacy_metadata['theme']['config'] == {'color': 'blue'}
    assert legacy_metadata['view'] == {'scale': 2}
    assert legacy_metadata['documentData'] == {'name': 'Legacy'}
    if explicit_metadata:
        assert detail.theme['config'] == {}
        assert detail.view_data == {'scale': 3}
        assert detail.document_data == {'name': 'Explicit'}


def test_gateway_detail_document_explicit_empty_metadata_suppresses_legacy_fallback() -> None:
    root = {'data': {'uid': 'root', 'text': 'Root'}, 'children': []}
    detail = SimpleNamespace(
        node_tree={'root': root, 'layout': 'mindMap', 'theme': {'template': 'legacy'},
                   'view': {'scale': 2}, 'documentData': {'name': 'Legacy'}},
        layout='', theme={}, view_data={}, document_data={},
    )

    assert _document_from_detail(detail) == {
        'root': root, 'layout': 'mindMap', 'theme': {'template': 'default', 'config': {}},
        'view': {}, 'documentData': {},
    }


def test_gateway_detail_document_clones_fields_independently() -> None:
    shared_data = {'uid': 'root', 'text': 'Root'}
    detail = SimpleNamespace(node_tree={'data': shared_data, 'children': []}, document_data=shared_data)

    document = _document_from_detail(detail)
    document['root']['data']['text'] = 'Mutation'

    assert document['documentData']['text'] == 'Root'
    assert shared_data['text'] == 'Root'


@pytest.mark.parametrize('raw_tree', [None, 'invalid', []])
def test_gateway_detail_document_rejects_missing_or_invalid_root(raw_tree: object) -> None:
    with pytest.raises(ServiceException) as error:
        _document_from_detail(SimpleNamespace(node_tree=raw_tree))
    assert error.value.message == '无法读取脑图权威正文'
