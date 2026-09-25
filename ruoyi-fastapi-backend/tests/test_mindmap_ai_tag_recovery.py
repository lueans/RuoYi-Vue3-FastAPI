"""Tag suggestions and committed draft truth across persistence/recovery."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from module_mindmap.ai.document import MindmapArtifactError, normalize_ai_editable_source_document
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel
from module_mindmap.service.mindmap_ai_service import (
    _CURRENT_JOB_EXECUTION_EPOCH,
    MindmapAiTaskManager,
    _direct_job_change_result,
    _safe_event_payload,
    sanitize_mindmap_ai_event_payload,
)
from module_mindmap.service.mindmap_ai_tag_catalog import load_ai_tag_catalog


def _document() -> dict:
    return {
        'root': {'data': {'uid': 'root', 'text': 'Map'}, 'children': [
            {'data': {'uid': 'allowed', 'text': 'Allowed'}, 'children': []},
            {'data': {'uid': 'private', 'text': 'Private'}, 'children': []},
        ]},
        'layout': 'logicalStructure', 'theme': {'template': 'default', 'config': {}},
        'view': None, 'documentData': {},
    }


def _job() -> SimpleNamespace:
    return SimpleNamespace(
        id='tag-recovery', user_id=7, status='running', execution_epoch=1,
        source_mindmap_id=42, expires_time=datetime.now() + timedelta(days=1),
        request_json=json.dumps({
            'executionMode': 'direct',
            'source': {'scope': {'type': 'branch', 'rootUid': 'allowed'}},
        }),
    )


def _session_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, AsyncMock]:
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    class Session:
        async def __aenter__(self) -> SimpleNamespace:
            return db

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.AsyncSessionLocal', Session)
    monkeypatch.setattr(MindmapAiTaskManager, '_owns_current_job_lease', AsyncMock(return_value=True))
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job', AsyncMock(return_value=_job()))
    events = AsyncMock(return_value=SimpleNamespace(sequence=1))
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event', events)
    return db, events


@pytest.mark.asyncio
async def test_direct_checkpoint_and_cache_use_committed_scope_not_tool_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _db, events = _session_fixture(monkeypatch)
    phantom = _document()
    phantom['root']['children'][0]['data']['tag'] = [{'tagId': 999, 'text': 'Not persisted'}]
    committed = _document()
    committed['root']['children'][0]['data']['tag'] = [{'tagId': 7, 'text': 'Resolved'}]
    monkeypatch.setattr(MindmapAiTaskManager, '_commit_direct_draft', AsyncMock(return_value={
        'contentRevision': 9, 'operationCount': 0, '_committedDocument': committed,
    }))
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiMutationGateway.publish_direct_commit', AsyncMock())
    values = []

    async def checkpoint(_db: object, data: dict) -> tuple[SimpleNamespace, bool]:
        values.append(data)
        return SimpleNamespace(**data), True

    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint', checkpoint)
    cache = AsyncMock()
    monkeypatch.setattr(MindmapAiTaskManager, '_store_draft_preview', cache)
    token = _CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        await MindmapAiTaskManager._emit('tag-recovery', 'draft_changed', {
            'operationCursor': 1, 'operations': [{'type': 'update_node'}], 'previewState': phantom,
        })
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(token)
    restored = MindmapAiTaskManager._draft_checkpoint_preview(
        SimpleNamespace(**values[0], update_time=datetime.now()),
    )
    assert restored['document']['root']['data'] == {**committed['root']['children'][0]['data'], 'expand': True}
    cached_document, _summary = normalize_ai_editable_source_document(cache.await_args.kwargs['document'])
    assert cached_document == restored['document']
    assert 'private' not in json.dumps(restored)
    assert 'Not persisted' not in json.dumps(restored)
    event_payload = json.loads(events.await_args.args[3])
    assert '_committedDocument' not in event_payload
    assert 'Resolved' not in json.dumps(event_payload)


@pytest.mark.asyncio
async def test_tag_suggestions_persist_and_recover_without_mutations_or_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, events = _session_fixture(monkeypatch)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiMutationGateway.read_document', AsyncMock(
        return_value=SimpleNamespace(node_tree=_document()['root']),
    ))
    commit = AsyncMock()
    checkpoint = AsyncMock()
    monkeypatch.setattr(MindmapAiTaskManager, '_commit_direct_draft', commit)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint', checkpoint)
    suggestions = [{'name': 'Needs review', 'reason': 'Reusable status', 'nodeUids': ['allowed']}]
    await MindmapAiTaskManager._emit('tag-recovery', 'tag_suggestions', {
        'suggestions': suggestions, 'operations': [{'type': 'create_node'}],
        'previewState': _document(), 'changeSummary': {'added': 99},
    })
    commit.assert_not_awaited()
    checkpoint.assert_not_awaited()
    db.commit.assert_awaited_once()
    payload = json.loads(events.await_args.args[3])
    assert payload == {'suggestions': suggestions}
    assert _safe_event_payload(payload) == payload
    assert sanitize_mindmap_ai_event_payload(payload) == payload
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_events', AsyncMock(return_value=[
        SimpleNamespace(sequence=1, event_type='tag_suggestions', payload_json=json.dumps(payload)),
    ]))
    result = await _direct_job_change_result(db, _job())
    assert result['changeSummary']['total'] == 0


@pytest.mark.asyncio
async def test_suggestion_rejects_node_outside_original_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    _db, events = _session_fixture(monkeypatch)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiMutationGateway.read_document', AsyncMock(
        return_value=SimpleNamespace(node_tree=_document()['root']),
    ))
    with pytest.raises(MindmapArtifactError, match='授权范围'):
        await MindmapAiTaskManager._emit('tag-recovery', 'tag_suggestions', {
            'suggestions': [{'name': 'Label', 'reason': 'Reason', 'nodeUids': ['private']}],
        })
    events.assert_not_awaited()


@pytest.mark.parametrize('invalid', [
    [], [{'name': 'x' * 101, 'reason': 'Reason', 'nodeUids': []}],
    [{'name': 'Label', 'reason': 'Reason', 'nodeUids': [], 'document': _document()}],
])
def test_suggestion_safe_payload_rejects_invalid_or_unknown_fields(invalid: object) -> None:
    assert _safe_event_payload({'suggestions': invalid}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('has_checkpoint', [False, True])
async def test_recovered_direct_worker_uses_latest_cloud_then_original_scope(
    monkeypatch: pytest.MonkeyPatch, has_checkpoint: bool,
) -> None:
    authoritative = _document()
    old = deepcopy(authoritative)
    old['root']['children'][0]['data']['tag'] = [{'tagId': 999}]
    request = MindmapAiJobCreateModel.model_validate({
        'intent': 'expand', 'prompt': 'Continue', 'executionMode': 'direct',
        'source': {'type': 'cloud_document', 'mindmapId': 42, 'document': old,
                   'scope': {'type': 'branch', 'rootUid': 'allowed'}},
    })
    read = AsyncMock(return_value=SimpleNamespace(node_tree=authoritative['root']))
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiMutationGateway.read_document', read)
    recovered = await MindmapAiTaskManager._resolve_run_source_document(
        None, _job(), request, {'document': old} if has_checkpoint else None, has_draft_history=True,
    )
    assert 'tag' not in recovered['root']['children'][0]['data']
    projection, _summary = MindmapAiTaskManager._project_committed_preview(_job(), recovered)
    assert projection['root']['data']['uid'] == 'allowed'
    assert 'private' not in json.dumps(projection)
    read.assert_awaited_once_with(None, 42, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize(('user_id', 'owner_id', 'expected_owners'), [(7, 7, [0, 7]), (7, 9, [0])])
async def test_catalog_intersects_visibility_and_file_ownership(
    monkeypatch: pytest.MonkeyPatch, user_id: int, owner_id: int, expected_owners: list[int],
) -> None:
    queries = []

    async def execute(query: object) -> SimpleNamespace:
        queries.append(query.compile().params)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=list))

    monkeypatch.setattr('module_mindmap.service.mindmap_ai_tag_catalog.MindmapService.resolve_mindmap_access', AsyncMock(
        return_value=(SimpleNamespace(owner_id=owner_id), 1, user_id == owner_id),
    ))
    assert await load_ai_tag_catalog(SimpleNamespace(execute=execute), user_id, mindmap_id=42) == []
    assert queries[0]['owner_id_1'] == expected_owners
    assert queries[0]['status_1'] == 0


@pytest.mark.asyncio
async def test_catalog_keyset_reads_every_page_and_refreshes_next_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_tag_catalog.TAG_CATALOG_PAGE_SIZE', 2)
    tags = [SimpleNamespace(
        id=index, category_id=None, uuid=f'uuid-{index}', tag_key=f'tag-{index}',
        name=f'Tag {index}', description='', style={}, status=0, definition_revision=1,
    ) for index in range(1, 4)]
    cursors = []

    async def execute(query: object) -> SimpleNamespace:
        cursor = query.compile().params['id_1']
        cursors.append(cursor)
        page = [tag for tag in tags if tag.id > cursor][:2]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: page))

    db = SimpleNamespace(execute=execute)
    first = await load_ai_tag_catalog(db, 7)
    assert [tag['tagId'] for tag in first] == [1, 2, 3]
    assert cursors == [0, 2]
    tags[0].name = 'Renamed'
    second = await load_ai_tag_catalog(db, 7)
    assert second[0]['text'] == 'Renamed'
    assert first[0]['text'] == 'Tag 1'


@pytest.mark.parametrize('scope', [
    {'type': 'document'},
    {'type': 'branch', 'rootUid': 'allowed'},
    {'type': 'selectedNodes', 'nodeUids': ['allowed', 'other']},
])
def test_committed_projection_accepts_blank_nodes_and_preserves_scope(scope: dict) -> None:
    document = _document()
    document['root']['data']['text'] = ''
    document['root']['children'][0]['data']['text'] = '  '
    document['root']['children'].append({'data': {'uid': 'other', 'text': 'Edited'}, 'children': []})
    job = _job()
    job.request_json = json.dumps({'source': {'scope': scope}})
    projection, _summary = MindmapAiTaskManager._project_committed_preview(job, document)
    assert document['root']['data']['text'] == ''
    if scope['type'] == 'branch':
        assert projection['root']['data']['uid'] == 'allowed'
        assert 'private' not in json.dumps(projection)
    elif scope['type'] == 'selectedNodes':
        assert [node['data']['uid'] for node in projection['root']['children']] == ['allowed', 'other']
        assert 'private' not in json.dumps(projection)
    else:
        assert projection['root']['data']['uid'] == 'root'


@pytest.mark.parametrize(('mode', 'target', 'expected_id'), [
    ('direct', 'file', 42), ('preview', 'proposal', 42), ('preview', 'file', None),
])
def test_catalog_uses_destination_ownership_not_shared_input_file(
    mode: str, target: str, expected_id: int | None,
) -> None:
    request = MindmapAiJobCreateModel.model_validate({
        'intent': 'expand', 'prompt': 'Continue', 'executionMode': mode, 'target': target,
        'source': {'type': 'cloud_document', 'mindmapId': 42, 'document': _document()},
    })
    assert MindmapAiTaskManager._tag_catalog_target_mindmap_id(request) == expected_id
