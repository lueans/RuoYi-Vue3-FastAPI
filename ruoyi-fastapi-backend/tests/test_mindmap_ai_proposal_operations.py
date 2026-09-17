"""冻结 AI Proposal operation 协议的行为测试。"""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from exceptions.exception import ServiceException
from module_mindmap.ai.diff import build_document_diff, build_legacy_document_diff_v0
from module_mindmap.ai.document import (
    MindmapArtifactError,
    compute_document_hash,
    normalize_ai_document,
    normalize_ai_editable_source_document,
)
from module_mindmap.ai.proposal_operations import (
    PROPOSAL_INTEGRITY_ERROR_CODE,
    materialize_editor_document_from_proposal,
    normalize_proposal_operations_for_apply,
    strict_replay_document_operations,
    verify_proposal_document_integrity,
)
from module_mindmap.service.mindmap_ai_service import MindmapAiService


def _node(uid: str, text: str, children: list[dict] | None = None, **data: object) -> dict:
    return {
        'data': {'uid': uid, 'text': text, **data},
        'children': children or [],
    }


def _document(children: list[dict] | None = None) -> dict:
    document = {
        'root': _node('root', '根节点', children),
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }
    return normalize_ai_document(document, content_policy='source')[0]


def _operation(operation_type: str, node_uid: str | None, payload: object) -> dict:
    return {'type': operation_type, 'nodeUid': node_uid, 'payload': payload}


def test_diff_round_trip_covers_every_operation_and_keeps_inputs_immutable() -> None:
    before = _document([
        _node('a', 'A', [_node('a1', 'A1')], note='待删除备注'),
        _node('b', 'B'),
        _node('deleted', '删除我'),
    ])
    after = _document([
        _node('b', 'B 已更新', [_node('a1', 'A1')]),
        _node('created', '新增节点'),
    ])
    after['root']['data']['text'] = '新根标题'
    after['layout'] = 'mindMap'
    after['theme'] = {'template': 'classic4', 'config': {'lineColor': '#123456'}}
    after['documentData'] = {'board': {'grid': True, 'mode': 'loose'}}
    after = normalize_ai_document(after, content_policy='source')[0]
    frozen_before = deepcopy(before)

    operations, impact = build_document_diff(before, after)
    frozen_operations = deepcopy(operations)
    replayed = strict_replay_document_operations(before, operations)

    assert replayed == after
    assert before == frozen_before
    assert operations == frozen_operations
    assert {operation['type'] for operation in operations} == {
        'create_node', 'update_node', 'move_node', 'delete_subtree',
        'set_document_meta',
    }
    assert impact['operationCount'] == len(operations)
    for operation in operations:
        assert set(operation) == {'type', 'nodeUid', 'payload'}
        if operation['type'] in {'update_node', 'set_document_meta'}:
            assert set(operation['payload']) == {'set', 'unset'}


def test_editor_materialization_preserves_untouched_rich_text_and_view() -> None:
    raw_source = {
        'root': _node(
            'root',
            '<p><span>富文本根节点</span></p>',
            [_node('a', '<p><strong>A</strong></p>', richText=True)],
            richText=True,
        ),
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': {'transform': {'scale': 1.25, 'x': 10, 'y': 20}},
        'documentData': {},
    }
    normalized_source = normalize_ai_editable_source_document(raw_source)[0]
    artifact = deepcopy(normalized_source)
    artifact['root']['children'].append(_node('created', 'AI 新增'))
    artifact = normalize_ai_document(artifact, content_policy='source')[0]
    operations, _impact = build_document_diff(normalized_source, artifact)

    materialized = materialize_editor_document_from_proposal(
        source_document=raw_source,
        operations=operations,
        artifact_document=artifact,
    )

    assert materialized['root']['data']['text'] == '<p><span>富文本根节点</span></p>'
    assert materialized['root']['children'][0]['data']['text'] == '<p><strong>A</strong></p>'
    assert materialized['view'] == raw_source['view']
    assert materialized['root']['children'][1]['data']['text'] == 'AI 新增'
    assert normalize_ai_editable_source_document(materialized)[0] == artifact


def test_diff_distinguishes_null_from_unset_and_replays_explicit_deletion() -> None:
    before = _document([_node('a', 'A', note='删除备注')])
    after = _document([_node('a', 'A', hyperlink=None)])

    operations, _impact = build_document_diff(before, after)

    assert operations == [{
        'type': 'update_node',
        'nodeUid': 'a',
        'payload': {'set': {'hyperlink': None}, 'unset': ['note']},
    }]
    assert strict_replay_document_operations(before, operations) == after


@pytest.mark.parametrize('bad_operation', [
    {'type': 'unknown', 'nodeUid': 'a', 'payload': None},
    {'type': 'delete_subtree', 'nodeUid': 'a', 'payload': None, 'extra': True},
    _operation('update_node', 'a', {'patch': {'text': 'x'}}),
    _operation('update_node', 'missing', {'set': {'text': 'x'}, 'unset': []}),
    _operation('update_node', 'a', {'set': {'uid': 'other'}, 'unset': []}),
    _operation('update_node', 'a', {'set': {'unknown': 'x'}, 'unset': []}),
    _operation('update_node', 'a', {'set': {'text': 'x'}, 'unset': ['text']}),
    _operation('update_node', 'a', {'set': {}, 'unset': ['note', 'note']}),
    _operation('create_node', 'a', {
        'parentUid': 'root', 'index': 0, 'data': {'uid': 'a', 'text': '重复'},
    }),
    _operation('create_node', 'new', {
        'parentUid': 'missing', 'index': 0, 'data': {'uid': 'new', 'text': '新增'},
    }),
    _operation('create_node', 'new', {
        'parentUid': 'root', 'index': True, 'data': {'uid': 'new', 'text': '新增'},
    }),
    _operation('create_node', 'new', {
        'parentUid': 'root', 'index': 99, 'data': {'uid': 'new', 'text': '新增'},
    }),
    _operation('create_node', 'new', {
        'parentUid': 'root', 'index': 0, 'data': {'uid': 'other', 'text': '新增'},
    }),
    _operation('create_node', 'new', {
        'parentUid': 'root', 'index': 0,
        'data': {'uid': 'new', 'text': '新增', 'unknown': True},
    }),
    _operation('move_node', 'missing', {'parentUid': 'root', 'index': 0}),
    _operation('move_node', 'a', {'parentUid': 'missing', 'index': 0}),
    _operation('move_node', 'root', {'parentUid': 'a', 'index': 0}),
    _operation('move_node', 'a', {'parentUid': 'a1', 'index': 0}),
    _operation('delete_subtree', 'root', None),
    _operation('delete_subtree', 'missing', None),
    _operation('delete_subtree', 'a', {}),
    _operation('set_document_meta', 'root', {
        'set': {'layout': 'mindMap'}, 'unset': [],
    }),
    _operation('set_document_meta', None, {
        'set': {'view': None}, 'unset': [],
    }),
])
def test_strict_replay_rejects_invalid_schema_and_tree_mutations_atomically(
    bad_operation: dict,
) -> None:
    before = _document([_node('a', 'A', [_node('a1', 'A1')])])
    frozen = deepcopy(before)
    operations = [
        _operation('update_node', 'a', {'set': {'text': '先修改'}, 'unset': []}),
        bad_operation,
    ]

    with pytest.raises(MindmapArtifactError) as invalid:
        strict_replay_document_operations(before, operations)

    assert invalid.value.code == PROPOSAL_INTEGRITY_ERROR_CODE
    assert before == frozen


def test_strict_replay_rejects_duplicate_uid_in_the_baseline() -> None:
    before = _document([_node('a', 'A')])
    before['root']['children'].append(_node('a', '重复'))

    with pytest.raises(MindmapArtifactError, match='UID 重复') as invalid:
        strict_replay_document_operations(before, [])

    assert invalid.value.code == PROPOSAL_INTEGRITY_ERROR_CODE


@pytest.mark.parametrize('tamper', [
    'proposal_hash',
    'manifest_hash',
    'artifact_document',
    'operations',
])
def test_integrity_verifier_binds_operations_document_and_both_hashes(tamper: str) -> None:
    before = _document([_node('a', 'A')])
    after = _document([_node('a', 'A2'), _node('b', 'B')])
    operations, _impact = build_document_diff(before, after)
    proposal_hash = compute_document_hash(after)
    manifest_hash = proposal_hash
    artifact_document = deepcopy(after)
    if tamper == 'proposal_hash':
        proposal_hash = 'mmf2:sha256:' + '0' * 64
    elif tamper == 'manifest_hash':
        manifest_hash = 'mmf2:sha256:' + '1' * 64
    elif tamper == 'artifact_document':
        artifact_document['root']['data']['text'] = '被篡改'
    else:
        operations = [
            _operation('update_node', 'a', {'set': {'text': 'A'}, 'unset': []}),
            *operations,
        ]

    with pytest.raises(MindmapArtifactError) as invalid:
        verify_proposal_document_integrity(
            base_document=before,
            operations=operations,
            artifact_document=artifact_document,
            proposal_result_hash=proposal_hash,
            manifest_document_hash=manifest_hash,
        )

    assert invalid.value.code == PROPOSAL_INTEGRITY_ERROR_CODE


def test_integrity_verifier_accepts_only_the_canonical_diff_sequence() -> None:
    before = _document([_node('a', 'A'), _node('b', 'B')])
    after = _document([_node('b', 'B'), _node('a', 'A2')])
    operations, _impact = build_document_diff(before, after)
    result_hash = compute_document_hash(after)

    assert verify_proposal_document_integrity(
        base_document=before,
        operations=operations,
        artifact_document=after,
        proposal_result_hash=result_hash,
        manifest_document_hash=result_hash,
    ) == after


def test_legacy_operations_are_strictly_verified_and_upgraded() -> None:
    before = _document([_node('existing', '旧标题')])
    after = _document([
        _node('new-parent', '新增父节点', [_node('new-child', '新增子节点')]),
        _node('existing', '新标题'),
    ])
    after['root']['data']['text'] = 'AI 生成的脑图'
    after['documentData'] = {'board': {'grid': True, 'mode': 'strict'}}
    after = normalize_ai_document(after, content_policy='source')[0]
    legacy_operations = build_legacy_document_diff_v0(before, after)
    canonical_operations, _impact = build_document_diff(before, after)

    assert [operation['type'] for operation in legacy_operations] == [
        'create_node', 'create_node', 'update_node', 'update_node',
        'set_document_meta',
    ]
    assert normalize_proposal_operations_for_apply(
        base_document=before,
        operations=legacy_operations,
        artifact_document=after,
    ) == canonical_operations
    assert strict_replay_document_operations(before, canonical_operations) == after


@pytest.mark.parametrize(('before_value', 'after_has_field', 'expected_payload'), [
    ('旧备注', False, {'set': {}, 'unset': ['note']}),
    ('旧备注', True, {'set': {'note': None}, 'unset': []}),
])
def test_legacy_null_patch_is_resolved_from_artifact_field_presence(
    before_value: str,
    after_has_field: bool,
    expected_payload: dict,
) -> None:
    before = _document([_node('a', 'A', note=before_value)])
    after_node = _node('a', 'A')
    if after_has_field:
        after_node['data']['note'] = None
    after = _document([after_node])
    legacy_operations = build_legacy_document_diff_v0(before, after)

    upgraded = normalize_proposal_operations_for_apply(
        base_document=before,
        operations=legacy_operations,
        artifact_document=after,
    )

    assert upgraded == [_operation('update_node', 'a', expected_payload)]
    assert strict_replay_document_operations(before, upgraded) == after


@pytest.mark.parametrize('tamper', ['patch_value', 'metadata_fields', 'extra_field'])
def test_legacy_compatibility_rejects_tampered_or_ambiguous_audit_data(
    tamper: str,
) -> None:
    before = _document([_node('a', 'A')])
    after = _document([_node('a', 'A2'), _node('b', 'B')])
    after['documentData'] = {'board': {'grid': True}}
    after = normalize_ai_document(after, content_policy='source')[0]
    operations = build_legacy_document_diff_v0(before, after)
    if tamper == 'patch_value':
        next(
            operation for operation in operations
            if operation['type'] == 'update_node'
        )['payload']['patch']['text'] = '被篡改'
    elif tamper == 'metadata_fields':
        next(
            operation for operation in operations
            if operation['type'] == 'set_document_meta'
        )['payload']['fields'].append('layout')
    else:
        operations[0]['payload']['unexpected'] = True

    with pytest.raises(MindmapArtifactError) as invalid:
        normalize_proposal_operations_for_apply(
            base_document=before,
            operations=operations,
            artifact_document=after,
        )

    assert invalid.value.code == PROPOSAL_INTEGRITY_ERROR_CODE


def _local_prepare_records() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, dict]:
    before = _document([_node('a', 'A')])
    after = _document([_node('a', 'A2')])
    operations, _impact = build_document_diff(before, after)
    base_hash = compute_document_hash(before)
    result_hash = compute_document_hash(after)
    proposal = SimpleNamespace(
        id='proposal-local-integrity',
        job_id='job-local-integrity',
        status='ready',
        target_mindmap_id=None,
        base_document_id='local-document',
        base_revision=4,
        base_hash=base_hash,
        base_room_epoch=None,
        result_artifact_id='artifact-local-integrity',
        result_hash=result_hash,
        proposal_type='patch',
        scope_json='{}',
        operations_json=json.dumps(operations, ensure_ascii=False),
        impact_json='{}',
        warnings_json='[]',
        expires_time=datetime.now() + timedelta(hours=1),
    )
    job = SimpleNamespace(
        id='job-local-integrity',
        intent='expand',
        source_type='local_snapshot',
        target='proposal',
        artifact_id='artifact-local-integrity',
        base_revision=4,
        base_hash=base_hash,
        request_json=json.dumps({
            'agentKey': 'codex',
            'intent': 'expand',
            'prompt': '更新节点',
            'source': {
                'type': 'local_snapshot',
                'documentId': 'local-document',
                'revision': 4,
                'documentHash': base_hash,
                'document': before,
                'baselineDocument': before,
            },
            'target': 'proposal',
        }, ensure_ascii=False),
    )
    artifact_record = SimpleNamespace(
        job_id=job.id,
        document_hash=result_hash,
    )
    artifact = {
        'manifest': {'documentHash': result_hash},
        'document': after,
    }
    return proposal, job, artifact_record, artifact


@pytest.mark.asyncio
async def test_prepare_local_apply_verifies_integrity_before_marking_prepared() -> None:
    proposal, job, artifact_record, artifact = _local_prepare_records()
    database = SimpleNamespace(commit=AsyncMock())
    update_proposal = AsyncMock()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(artifact_record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=update_proposal,
        ),
    ):
        prepared = await MindmapAiService.prepare_local_apply(
            database,
            proposal.id,
            user_id=7,
        )

    assert prepared['resultHash'] == artifact['manifest']['documentHash']
    assert prepared['operations'] == json.loads(proposal.operations_json)
    update_proposal.assert_awaited_once_with(
        database,
        proposal.id,
        {'status': 'prepared'},
    )
    database.commit.assert_awaited_once()


@pytest.mark.parametrize('tamper', ['proposal_hash', 'artifact', 'operations'])
@pytest.mark.asyncio
async def test_prepare_local_apply_rejects_tampering_without_status_write(tamper: str) -> None:
    proposal, job, artifact_record, artifact = _local_prepare_records()
    if tamper == 'proposal_hash':
        proposal.result_hash = 'mmf2:sha256:' + '0' * 64
        artifact_record.document_hash = proposal.result_hash
    elif tamper == 'artifact':
        artifact['document']['root']['data']['text'] = '篡改 Artifact'
    else:
        proposal.operations_json = json.dumps([
            _operation('update_node', 'a', {'set': {'text': 'A'}, 'unset': []}),
            *json.loads(proposal.operations_json),
        ], ensure_ascii=False)
    database = SimpleNamespace(commit=AsyncMock())
    update_proposal = AsyncMock()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(artifact_record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=update_proposal,
        ),
        pytest.raises(ServiceException) as invalid,
    ):
        await MindmapAiService.prepare_local_apply(database, proposal.id, user_id=7)

    assert invalid.value.data == {'errorCode': PROPOSAL_INTEGRITY_ERROR_CODE}
    update_proposal.assert_not_awaited()
    database.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_local_apply_upgrades_a_verified_legacy_proposal() -> None:
    proposal, job, artifact_record, artifact = _local_prepare_records()
    base_document = json.loads(job.request_json)['source']['baselineDocument']
    legacy_operations = build_legacy_document_diff_v0(
        base_document,
        artifact['document'],
    )
    proposal.operations_json = json.dumps(legacy_operations, ensure_ascii=False)
    update_proposal = AsyncMock()
    database = SimpleNamespace(commit=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(artifact_record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=update_proposal,
        ),
    ):
        prepared = await MindmapAiService.prepare_local_apply(
            database,
            proposal.id,
            user_id=7,
        )

    assert prepared['operations'] == build_document_diff(
        base_document,
        artifact['document'],
    )[0]
    assert prepared['operations'] != legacy_operations
    update_proposal.assert_awaited_once_with(
        database,
        proposal.id,
        {'status': 'prepared'},
    )
    database.commit.assert_awaited_once()
