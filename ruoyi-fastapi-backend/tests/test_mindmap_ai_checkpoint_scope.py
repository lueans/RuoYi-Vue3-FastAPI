"""A recovery checkpoint is an authorized projection, never a replacement file."""
import json
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from module_mindmap.ai.diff import build_document_diff
from module_mindmap.ai.document import compute_document_hash, normalize_ai_editable_source_document
from module_mindmap.ai.proposal_operations import materialize_editor_document_from_proposal
from module_mindmap.ai.tool_contract import MindmapToolService, _restore_projected_node_content
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel
from module_mindmap.service.mindmap_ai_service import MindmapAiService, MindmapAiTaskManager

SCOPES = [{'type': 'document'}, {'type': 'branch', 'rootUid': 'a'},
          {'type': 'selectedNodes', 'nodeUids': ['a', 'b']}]


def _fixture(scope: dict[str, Any]) -> tuple[dict[str, Any], MindmapAiJobCreateModel, MindmapToolService]:
    def node(uid: str, **data: Any) -> dict[str, Any]:
        return {'data': {'uid': uid, 'text': uid, **data}, 'children': []}

    branch = node('a', image='https://example.test/preserved.png', richText=True, expand=False, note='original')
    branch['children'] = [node('old'), node('keep', text='<b>Keep</b>', richText=True, color='#ff0000')]
    document, _summary = normalize_ai_editable_source_document({
        'root': {**node('root'), 'children': [branch, node('b'), node('outside')]},
        'theme': {'template': 'default', 'config': {'lineWidth': 3}},
        'documentData': {'privateEditorMetadata': True},
    })
    request = MindmapAiJobCreateModel.model_validate({
        'agentKey': 'codex', 'intent': 'expand', 'prompt': '只修改授权节点', 'target': 'proposal',
        'source': {'type': 'local_snapshot', 'documentId': 'local:scope', 'revision': 3,
                   'documentHash': compute_document_hash(document), 'document': document,
                   'baselineDocument': document, 'scope': scope},
    })
    tools = MindmapToolService(base_document=document, scope=scope, trusted_source=True)
    tools.update_nodes([{'nodeUid': 'a', 'patch': {'text': 'Changed'}}])
    tools.remove_nodes(['old'])
    tools.add_nodes([{'parentUid': 'a', 'text': 'new node'}])
    if scope['type'] == 'selectedNodes':
        tools.move_nodes([{'nodeUid': 'b', 'parentUid': 'a'}])
    return document, request, tools


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', SCOPES)
async def test_recovery_rebuilds_whole_file_without_resurrecting_deleted_nodes_or_expanding_scope(
    scope: dict[str, Any],
) -> None:
    baseline, request, tools = _fixture(scope)
    original = deepcopy(baseline)
    preview = {'document': tools.build_stream_delta(after_cursor=0, tool_name='remove_nodes')['previewState']}
    restored = await MindmapAiTaskManager._resolve_run_source_document(
        SimpleNamespace(), SimpleNamespace(), request, preview, has_draft_history=True,
    )
    assert restored == tools._draft.document
    assert baseline == original
    build_document_diff(baseline, restored)
    resumed = MindmapToolService(base_document=restored, scope=scope, trusted_source=True)
    projected = resumed.read_projection()
    assert 'image' not in json.dumps(projected)
    assert 'privateEditorMetadata' not in json.dumps(projected)
    if scope['type'] != 'document':
        assert 'outside' not in json.dumps(projected)
    added = next(node['data']['uid'] for node in restored['root']['children'][0]['children']
                 if node['data']['text'] == 'new node')
    resumed.remove_nodes([added])
    second = await MindmapAiTaskManager._resolve_run_source_document(
        SimpleNamespace(), SimpleNamespace(), request, {'document': resumed.read_projection()}, has_draft_history=True,
    )
    assert second == resumed._draft.document
    assert added not in json.dumps(second)
    assert '"uid": "old"' not in json.dumps(second)


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', SCOPES)
async def test_stop_promotes_scoped_checkpoint_to_whole_artifact(
    monkeypatch: pytest.MonkeyPatch, scope: dict[str, Any],
) -> None:
    baseline, request, tools = _fixture(scope)
    job = SimpleNamespace(
        id='10000000-0000-4000-8000-000000000001', status='running', target='proposal', intent='expand',
        source_type='local_snapshot', source_mindmap_id=None, request_json=request.model_dump_json(by_alias=True),
        title='Scoped result', agent_key='codex', adapter_version='1', user_id=7, session_id='session',
        base_revision=3, base_hash=compute_document_hash(baseline), base_room_epoch=None,
        expires_time=datetime.now() + timedelta(days=1),
    )
    dao = 'module_mindmap.service.mindmap_ai_service.MindmapAiDao'
    monkeypatch.setattr(f'{dao}.get_draft_checkpoint', AsyncMock(return_value=object()))
    monkeypatch.setattr(MindmapAiTaskManager, '_draft_checkpoint_preview',
                        lambda _checkpoint: {'document': tools.read_projection()})
    saved = AsyncMock()
    proposal = AsyncMock()
    monkeypatch.setattr(f'{dao}.add_artifact', saved)
    monkeypatch.setattr(f'{dao}.add_proposal', proposal)
    for method in ('update_job', 'update_session', 'add_event', 'delete_draft_checkpoint'):
        monkeypatch.setattr(f'{dao}.{method}', AsyncMock())
    monkeypatch.setattr(f'{dao}.get_session', AsyncMock(return_value=SimpleNamespace(expires_time=job.expires_time)))

    assert await MindmapAiService._promote_draft_checkpoint_for_stop(SimpleNamespace(), job) is True
    result = json.loads(saved.await_args.args[1]['content_json'])['document']
    assert result == tools._draft.document
    assert result['root']['data']['uid'] == 'root'
    operations = json.loads(proposal.await_args.args[1]['operations_json'])
    assert not any(op['type'] == 'update_node' and op['nodeUid'] == 'keep' for op in operations)
    # The artifact remains the existing normalized semantic contract. Applying
    # its real operations to raw editor bytes must not flatten untouched HTML.
    editor = deepcopy(baseline)
    editor['root']['children'][0]['children'][1]['data']['text'] = '<b>Keep</b>'
    materialized = materialize_editor_document_from_proposal(
        source_document=editor, operations=operations, artifact_document=result,
    )
    retained = next(node for node in materialized['root']['children'][0]['children'] if node['data']['uid'] == 'keep')
    assert retained['data']['text'] == '<b>Keep</b>'
    assert retained['data']['richText'] is True


@pytest.mark.parametrize('text', ['Plain', '<b>Formatted</b>'])
def test_projection_merge_stage_keeps_hidden_fields_and_unchanged_original_bytes(text: str) -> None:
    prior = {'data': {'uid': 'a', 'text': text, 'richText': True, 'image': 'keep', 'note': 'remove'}, 'children': []}
    old_projection = {'uid': 'a', 'text': 'Formatted' if '<' in text else text, 'note': 'remove'}
    projected = {'data': {key: value for key, value in old_projection.items() if key != 'note'}, 'children': []}
    _restore_projected_node_content(projected, prior, old_projection)
    assert projected['data'] == {'uid': 'a', 'text': text, 'richText': True, 'image': 'keep'}
    projected['data']['text'] = 'Renamed'
    _restore_projected_node_content(projected, prior, old_projection)
    assert projected['data']['text'] == 'Renamed'


def test_scoped_checkpoint_cannot_import_an_outside_node() -> None:
    baseline, _request, tools = _fixture({'type': 'branch', 'rootUid': 'a'})
    projection = tools.read_projection()
    projection['root']['children'].append(deepcopy(baseline['root']['children'][-1]))
    restore = MindmapToolService(base_document=baseline, scope={'type': 'branch', 'rootUid': 'a'}, trusted_source=True)
    with pytest.raises(ValueError, match='授权范围'):
        restore.restore_checkpoint_projection(projection)
