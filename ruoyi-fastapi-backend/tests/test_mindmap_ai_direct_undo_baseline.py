"""Direct undo keeps raw editor bytes and rejects mixed-author revision chains."""
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from exceptions.exception import ServiceException
from module_mindmap.ai.document import (
    compute_document_hash,
    document_from_mindmap_detail,
    normalize_ai_editable_source_document,
)
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiJobCreateModel,
    MindmapAiJobRetryModel,
    MindmapAiMessageModel,
)
from module_mindmap.service import mindmap_ai_service as service
from module_mindmap.websocket.room_manager import room_manager


def _setup(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    detail = SimpleNamespace(
        node_tree={'data': {'uid': 'root', 'text': 'Map'}, 'children': [
            {'data': {'uid': 'blank', 'text': '  ', 'image': 'https://example.test/original.png'}, 'children': []},
            {'data': {'uid': 'edit', 'text': '<b>Before</b>', 'richText': True}, 'children': []},
        ]}, content_revision=3, layout='logicalStructure', theme={'template': 'default', 'config': {'lineWidth': 2}},
        view_data={'scale': 1.7}, document_data={'custom': 'keep'},
    )
    request = MindmapAiJobCreateModel.model_validate({
        'agentKey': 'codex', 'intent': 'expand', 'prompt': '只编辑分支', 'executionMode': 'direct', 'target': 'file',
        'parameters': {'maxNodes': 100, 'maxDepth': 6},
        'source': {'type': 'cloud_document', 'mindmapId': 9, 'scope': {'type': 'branch', 'rootUid': 'edit'}},
    })
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(service.MindmapService, 'check_mindmap_access',
                        AsyncMock(return_value=SimpleNamespace(id=9, content_revision=3)))
    monkeypatch.setattr(service.MindmapService, 'get_mindmap_detail_services', AsyncMock(return_value=detail))
    monkeypatch.setattr(room_manager, 'get_active_lineage_epoch', AsyncMock(return_value='epoch'))
    return SimpleNamespace(detail=detail, request=request, database=database)


async def _job_with_baseline(state: SimpleNamespace) -> SimpleNamespace:
    baseline: dict[str, Any] = {}
    document, revision, document_hash, _mindmap_id, _epoch = await service.MindmapAiService._prepare_source_for_job(
        state.database, state.request, 7, capture_editor_document=baseline,
    )
    payload = state.request.model_dump(by_alias=True)
    payload['source'].update(document=document, baselineDocument=document, revision=revision, documentHash=document_hash)
    return SimpleNamespace(
        id='10000000-0000-4000-8000-000000000001', user_id=7, proposal_id=None, source_type='cloud_document',
        source_mindmap_id=9, base_revision=revision, base_hash=document_hash,
        session_id='session', agent_key='codex', intent='expand', target='file', turn_index=1,
        status='completed_direct',
        artifact_id=None, base_room_epoch='epoch',
        expires_time=datetime.now() + timedelta(days=1),
        request_json=json.dumps(service._request_with_undo_baseline(payload, baseline)),
    )


@pytest.mark.asyncio
async def test_prepare_receipt_and_actual_undo_write_preserve_original_editor_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _setup(monkeypatch)
    original = deepcopy(document_from_mindmap_detail(state.detail))
    job = await _job_with_baseline(state)
    insert = AsyncMock()
    monkeypatch.setattr(service.MindmapAiDao, 'get_undo', AsyncMock(return_value=None))
    monkeypatch.setattr(service.MindmapAiDao, 'add_undo', insert)
    monkeypatch.setattr(service.MindmapAiDao, 'update_job', AsyncMock())
    await service.MindmapAiTaskManager._ensure_direct_undo_receipt(state.database, job)
    receipt = SimpleNamespace(**insert.await_args.args[1])
    assert receipt.status == 'available'
    assert json.loads(receipt.before_document_json) == original
    state.detail.node_tree['children'][1]['data']['text'] = 'After'
    state.detail.content_revision = 4
    current, _summary = normalize_ai_editable_source_document(document_from_mindmap_detail(state.detail))
    receipt.applied_revision = 4
    receipt.applied_hash = compute_document_hash(current)
    locks: list[str] = []

    async def read_undo(*_args: Any, for_update: bool = False) -> SimpleNamespace:
        if for_update:
            assert locks == ['job'], 'serialize with the AI writer before locking its receipt'
            locks.append('receipt')
        return receipt

    async def read_job(*_args: Any, for_update: bool = False) -> SimpleNamespace:
        if for_update:
            locks.append('job')
        return job

    monkeypatch.setattr(service.MindmapAiDao, 'get_undo', read_undo)
    monkeypatch.setattr(service.MindmapAiDao, 'get_proposal', AsyncMock(return_value=None))
    monkeypatch.setattr(service.MindmapAiDao, 'get_job', read_job)
    monkeypatch.setattr(service.MindmapAiDao, 'update_undo', AsyncMock())
    monkeypatch.setattr(service.MindmapAiDao, 'add_event', AsyncMock())
    for method in (
        'acquire_collaboration_mutation_barrier', 'wait_for_collaboration_mutation_barrier',
        'verify_collaboration_mutation_barrier', 'prepare_collaboration_mutation_barrier_commit',
        'complete_collaboration_mutation_barrier', 'abort_collaboration_mutation_barrier',
    ):
        monkeypatch.setattr(room_manager, method, AsyncMock(return_value=True))
    monkeypatch.setattr(service.MindmapCommentService, 'delete_ai_comments_for_job', AsyncMock(return_value=[]))
    wake = AsyncMock()
    monkeypatch.setattr(service.MindmapAiTaskManager, '_wake_waiting_followups', wake)
    saved = AsyncMock(return_value={'contentRevision': 5, 'clientMutationId': 'undo'})
    monkeypatch.setattr(service.MindmapService, 'update_content_batch_services', saved)

    result = await service.MindmapAiService.undo_cloud_proposal(state.database, 9, job.id, 7, 'tester', 'key')

    assert result['status'] == 'undone'
    assert locks == ['job', 'receipt']
    batch = saved.await_args.args[2]
    assert {'root': batch.node_tree, 'layout': batch.layout, 'theme': batch.theme,
            'view': batch.view_data, 'documentData': batch.document_data} == original
    wake.assert_awaited_once_with(job.id)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [*sorted(service.ACTIVE_JOB_STATUSES), 'waiting_turn', None])
@pytest.mark.parametrize('phase', ['preflight', 'after_barrier'])
async def test_direct_undo_rejects_unfinished_jobs_before_any_receipt_lock(
    monkeypatch: pytest.MonkeyPatch, status: str | None, phase: str,
) -> None:
    state = _setup(monkeypatch)
    job = await _job_with_baseline(state)
    job.proposal_id = job.id
    locked_job = SimpleNamespace(**{**vars(job), 'status': status})
    if phase == 'preflight':
        job.status = status
    receipt = SimpleNamespace(mindmap_id=9, status='available', applied_revision=3, expires_time=job.expires_time)
    reads: list[str] = []

    async def read_job(*_args: Any, for_update: bool = False) -> SimpleNamespace:
        reads.append('job-lock' if for_update else 'job-read')
        return locked_job if for_update else job

    async def read_undo(*_args: Any, for_update: bool = False) -> SimpleNamespace:
        assert not for_update, 'unfinished jobs must be refused before any receipt/file lock'
        reads.append('receipt-read')
        return receipt

    monkeypatch.setattr(service.MindmapAiDao, 'get_job', read_job)
    monkeypatch.setattr(service.MindmapAiDao, 'get_undo', read_undo)
    monkeypatch.setattr(service.MindmapAiDao, 'get_proposal', AsyncMock(return_value=None))
    acquire, abort, saved = AsyncMock(return_value=object()), AsyncMock(), AsyncMock()
    monkeypatch.setattr(room_manager, 'acquire_collaboration_mutation_barrier', acquire)
    monkeypatch.setattr(room_manager, 'wait_for_collaboration_mutation_barrier', AsyncMock(return_value=True))
    monkeypatch.setattr(room_manager, 'abort_collaboration_mutation_barrier', abort)
    monkeypatch.setattr(service.MindmapService, 'update_content_batch_services', saved)
    with pytest.raises(ServiceException) as error:
        await service.MindmapAiService.undo_cloud_proposal(state.database, 9, job.id, 7, 'tester', 'key')
    assert error.value.data == {'errorCode': 'AI_UNDO_STATE_INVALID'}
    assert reads == ['receipt-read', 'job-read'] + (['job-lock'] if phase == 'after_barrier' else [])
    assert acquire.await_count == abort.await_count == int(phase == 'after_barrier')
    saved.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['create', 'retry', 'followup', 'clarification', 'queued_release'])
async def test_all_authoritative_source_entries_persist_server_only_raw_baseline(
    monkeypatch: pytest.MonkeyPatch, entry: str,
) -> None:
    state = _setup(monkeypatch)
    parent = await _job_with_baseline(state)
    parent.status = 'failed' if entry == 'retry' else 'needs_input' if entry == 'clarification' else 'completed_direct'
    parent.proposal_id = parent.id
    if entry == 'clarification':
        # A direct parent can ask a follow-up question after committing work.
        # The child needs fresh raw bytes, never the parent's earlier marker.
        state.detail.content_revision = 5
        state.detail.node_tree['children'][1]['data']['text'] = '<b>Parent partial result</b>'
        monkeypatch.setattr(service.MindmapService, 'check_mindmap_access',
                            AsyncMock(return_value=SimpleNamespace(id=9, content_revision=5)))
    session = SimpleNamespace(status='active', expires_time=parent.expires_time)
    child = SimpleNamespace(**{**vars(parent), 'id': 'child', 'status': 'waiting_turn', 'parent_job_id': parent.id})
    manifest = SimpleNamespace(agent_key='codex', intents=('expand',), input_types=('cloud_document',),
                               adapter_version='1', sdk_version='sdk', runtime_version='runtime', default_model_ref='model')
    policy = service.AgentRuntimePolicy((), 2.0, 120, 200, 10, 3, 20)
    insert = AsyncMock(side_effect=lambda _db, values: SimpleNamespace(**values))
    updates = AsyncMock()
    monkeypatch.setattr(service.MindmapAiDao, 'get_job_by_idempotency', AsyncMock(return_value=None))
    monkeypatch.setattr(service.MindmapAiDao, 'get_job', AsyncMock(return_value=parent))
    monkeypatch.setattr(service.MindmapAiDao, 'get_session', AsyncMock(return_value=session))
    monkeypatch.setattr(service.MindmapAiDao, 'lock_jobs_for_session', AsyncMock(return_value=[parent]))
    monkeypatch.setattr(service.MindmapAiDao, 'list_waiting_followups', AsyncMock(return_value=[child]))
    monkeypatch.setattr(service.MindmapAiDao, 'add_job', insert)
    monkeypatch.setattr(service.MindmapAiDao, 'update_job', updates)
    for method in ('add_session', 'add_event', 'update_session'):
        monkeypatch.setattr(service.MindmapAiDao, method, AsyncMock())
    monkeypatch.setattr(service, 'get_mindmap_agent_registry', Mock(return_value=SimpleNamespace(
        get=lambda _agent: SimpleNamespace(get_manifest=lambda: manifest))))
    monkeypatch.setattr(service.MindmapAiService, '_ensure_connector_available', AsyncMock())
    monkeypatch.setattr(service.MindmapAiService, '_runtime_policy', Mock(return_value=policy))
    monkeypatch.setattr(service.MindmapAiService, '_ensure_concurrency_available', AsyncMock())
    monkeypatch.setattr(service.MindmapAiTaskManager, 'schedule', Mock())
    monkeypatch.setattr(service, '_job_model', lambda job: job)

    @asynccontextmanager
    async def database_session() -> Any:
        yield state.database

    monkeypatch.setattr(service, 'AsyncSessionLocal', database_session)
    if entry == 'create':
        await service.MindmapAiService.create_job(state.database, state.request, 7, 'key')
    elif entry == 'retry':
        await service.MindmapAiService.retry_job(state.database, parent.id, MindmapAiJobRetryModel(), 7, 'key')
    elif entry in {'followup', 'clarification'}:
        await service.MindmapAiService.create_followup_job(
            state.database, parent.id, MindmapAiMessageModel(
                prompt='continue', continuationBase='artifact' if entry == 'clarification' else 'current_document',
            ), 7, 'key',
        )
    else:
        await service.MindmapAiTaskManager._wake_waiting_followups(parent.id)
    values = updates.await_args.args[2] if entry == 'queued_release' else insert.await_args.args[1]
    payload = json.loads(values['request_json'])
    assert payload['_directUndoBaseline']['document'] == document_from_mindmap_detail(state.detail)
    assert payload['_directUndoBaseline']['documentHash'] == values['base_hash']
    assert payload['_directUndoBaseline']['revision'] == state.detail.content_revision
    assert '_directUndoBaseline' not in MindmapAiJobCreateModel.model_validate(payload).model_dump(by_alias=True)
    assert payload['source']['document']['root']['children'][0]['data']['text'] == '未命名节点'


@pytest.mark.asyncio
@pytest.mark.parametrize(('previous', 'revision', 'operations', 'concurrent', 'status', 'replay', 'expected'), [
    (3, 4, 2, False, 'available', False, 'available'),
    (3, 3, 0, False, 'available', False, 'available'),
    (4, 5, 2, False, 'available', False, 'available'),  # recovered worker uses durable receipt, not job base 3
    (3, 8, 2, False, 'available', False, 'blocked'),  # a no-op may have advanced only the process cursor
    (3, 4, 2, True, 'available', False, 'blocked'),
    (3, 4, 0, False, 'available', False, 'blocked'),  # comments after a foreign document commit
    (4, 5, 2, False, 'blocked', False, 'blocked'),
    (4, 4, 2, False, 'available', True, 'available'),
])
async def test_undo_revision_chain_is_fail_closed_without_aborting_direct_work(
    monkeypatch: pytest.MonkeyPatch, previous: int, revision: int, operations: int, concurrent: bool,
    status: str, replay: bool, expected: str,
) -> None:
    state = _setup(monkeypatch)
    job = await _job_with_baseline(state)
    receipt = SimpleNamespace(applied_revision=previous, status=status)
    monkeypatch.setattr(service.MindmapAiDao, 'get_undo', AsyncMock(return_value=receipt))
    update = AsyncMock()
    monkeypatch.setattr(service.MindmapAiDao, 'update_undo', update)
    await service.MindmapAiTaskManager._record_direct_undo_commit(state.database, job, job.id, {
        'contentRevision': revision, 'operationCount': operations, 'documentHash': 'committed',
        'concurrentMerge': concurrent, 'idempotentReplay': replay,
    })
    values = update.await_args.args[2]
    assert values.get('status', status) == expected
    assert values['applied_revision'] == revision


@pytest.mark.asyncio
async def test_legacy_available_receipt_cannot_restore_a_lossy_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _setup(monkeypatch)
    job = await _job_with_baseline(state)
    payload = json.loads(job.request_json)
    del payload['_directUndoBaseline']
    job.request_json = json.dumps(payload)
    job.proposal_id = job.id
    receipt = SimpleNamespace(mindmap_id=9, status='available')
    monkeypatch.setattr(service.MindmapAiDao, 'get_undo', AsyncMock(return_value=receipt))
    monkeypatch.setattr(service.MindmapAiDao, 'get_proposal', AsyncMock(return_value=None))
    monkeypatch.setattr(service.MindmapAiDao, 'get_job', AsyncMock(return_value=job))
    saved = AsyncMock()
    monkeypatch.setattr(service.MindmapService, 'update_content_batch_services', saved)
    with pytest.raises(ServiceException) as error:
        await service.MindmapAiService.undo_cloud_proposal(state.database, 9, job.id, 7, 'tester', 'key')
    assert error.value.data == {'errorCode': 'AI_UNDO_CONFLICT'}
    assert '原始快照' in error.value.message
    saved.assert_not_awaited()
