"""Durable stop receipts, using production DAO SQL on an isolated test database."""

import asyncio
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import NoReturn
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Engine, Integer, MetaData, Text, create_engine, select
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from exceptions.exception import ServiceException
from module_mindmap.ai.adapters._fs_utils import AgentProcessCleanupError
from module_mindmap.ai.adapters.base import AgentEventHandler, AgentRunContext, build_agent_continuation_clause
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.execution_state import execution_blocks_continuation, job_execution_state
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.entity.do.mindmap_ai_do import (
    MindmapAiDraftCheckpoint, MindmapAiJob, MindmapAiJobEvent, MindmapAiSession,
)
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel, MindmapAiJobRetryModel, MindmapAiMessageModel
from module_mindmap.service import mindmap_ai_service as service

JOB = '22222222-2222-4222-8222-222222222222'
SESSION = '11111111-1111-4111-8111-111111111111'
Manager = service.MindmapAiTaskManager
Dao = service.MindmapAiDao


class TestSession:
    __test__ = False

    def __init__(self, engine):
        self.db = Session(engine, expire_on_commit=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.db.close()

    async def execute(self, statement):
        return self.db.execute(statement)

    async def scalar(self, statement):
        return self.db.scalar(statement)

    def add(self, value):
        self.db.add(value)

    async def flush(self):
        self.db.flush()

    async def commit(self):
        self.db.commit()

    async def rollback(self):
        self.db.rollback()


@pytest.mark.asyncio
async def test_latest_plan_sql_preserves_clear_and_rejects_other_owner_and_expired_job(database):
    async with TestSession(database) as db:
        for sequence, payload in [(1, {'todos': [{'content': 'old', 'status': 'pending'}], 'origin': 'agent'}),
                                  (2, {'todos': [], 'origin': 'agent'})]:
            db.add(MindmapAiJobEvent(job_id=JOB, sequence=sequence, event_type='todo_updated', payload_json=json.dumps(payload)))
        db.add(MindmapAiJobEvent(job_id=JOB, sequence=3, event_type='assistant_delta', payload_json='{"text":"not a plan"}'))
        await db.commit()
        payload = await Dao.get_latest_plan_payload(db, JOB, 7)
        assert json.loads(payload) == {'todos': [], 'origin': 'agent'}
        assert await Dao.get_latest_plan_payload(db, JOB, 8) is None
        assert await Dao.get_latest_plan_payload(db, 'missing-job', 7) is None
        current = await Dao.get_job(db, JOB, 7)
        current.status = 'completed_file'
        current.request_json = json.dumps({'prompt': '原始目标', 'source': {'type': 'none'}})
        new_plan = {'todos': [{'content': '继续补充恢复测试', 'status': 'in_progress'}], 'origin': 'agent'}
        db.add(MindmapAiJobEvent(job_id=JOB, sequence=4, event_type='todo_updated', payload_json=json.dumps(new_plan)))
        await db.commit()
        request = {'prompt': '继续未完成部分', 'source': {'type': 'none'}, 'contextParentJobId': JOB}
        child = SimpleNamespace(id='new-job', user_id=7, session_id=SESSION, request_json=json.dumps(request))
        history = await Manager._editing_continuation_history(db, child, MindmapAiJobCreateModel.model_validate(request))
        context = AgentRunContext(job_id=child.id, user_id=7, intent='create', prompt=request['prompt'],
            parameters={}, source_document=None, tool_service=MindmapToolService(), continuation_history=history)
        clause = build_agent_continuation_clause(context)
        assert '继续补充恢复测试' in clause
        assert '"reportedStatus":"in_progress"' in clause
        assert '旧计划仅是上一 Agent 报告的快照' in clause
        current.expires_time = datetime.now() - timedelta(seconds=1)
        await db.commit()
        assert await Dao.get_latest_plan_payload(db, JOB, 7) is None


@pytest.fixture
def database(monkeypatch):
    if os.getenv('MINDMAP_DB_INTEGRATION') != '1':
        pytest.skip('explicit SQLite integration opt-in')
    # Copy table definitions, not the application engine or global ORM types.
    engine = create_engine('sqlite://', poolclass=StaticPool)
    metadata = MetaData()
    for model in (MindmapAiSession, MindmapAiJob, MindmapAiJobEvent, MindmapAiDraftCheckpoint):
        table = model.__table__.to_metadata(metadata)
        for column in table.c:
            if isinstance(column.type, LONGTEXT):
                column.type = Text()
        if model is MindmapAiJobEvent:
            table.c.id.type = Integer()  # SQLite's generated integer row ID.
    metadata.create_all(engine)
    now = datetime.now()
    with Session(engine) as db:
        db.add(MindmapAiSession(id=SESSION, user_id=7, current_agent_key='claude',
                               status='active', expires_time=now + timedelta(days=1)))
        db.add(MindmapAiJob(
            id=JOB, user_id=7, session_id=SESSION, agent_key='claude', adapter_version='test',
            execution_epoch=3, intent='create', target='file', source_type='empty',
            request_json='{}', request_fingerprint='fingerprint', idempotency_key='initial',
            status='running', expires_time=now + timedelta(days=1),
        ))
        db.commit()
    monkeypatch.setattr(service, 'AsyncSessionLocal', lambda: TestSession(engine))
    monkeypatch.setattr(Manager, '_owns_current_job_lease', AsyncMock(return_value=True))
    monkeypatch.setattr(Manager, '_detached_adapter_tasks', set())
    token = service._CURRENT_JOB_EXECUTION_EPOCH.set(3)
    try:
        yield engine
    finally:
        service._CURRENT_JOB_EXECUTION_EPOCH.reset(token)
        engine.dispose()


@pytest.mark.asyncio
async def test_visible_reply_sql_is_bounded_ordered_and_never_reads_foreign_or_private_events(database):
    async with TestSession(database) as db:
        current = await Dao.get_job(db, JOB, 7)
        current.status = 'completed_file'
        current.request_json = json.dumps({'prompt': '原始目标', 'source': {'type': 'none'}})
        db.add(MindmapAiJob(id='foreign', user_id=8, session_id=SESSION, agent_key='claude', adapter_version='test',
            intent='create', target='file', source_type='empty', request_json='{}', request_fingerprint='foreign',
            idempotency_key='foreign', status='completed_file', expires_time=datetime.now() + timedelta(days=1)))
        for index in range(131):
            db.add(MindmapAiJobEvent(job_id=JOB, sequence=index + 1, event_type='assistant_delta',
                payload_json=json.dumps({'text': f'{index}|', 'visibility': 'visible'})))
        db.add(MindmapAiJobEvent(job_id='foreign', sequence=1, event_type='assistant_delta',
                                payload_json='{"text":"foreign-private"}'))
        for sequence, kind in enumerate(('thinking_state', 'thinking_summary', 'tool_completed', 'todo_updated'), 132):
            db.add(MindmapAiJobEvent(job_id=JOB, sequence=sequence, event_type=kind,
                                    payload_json='{"text":"private-non-reply"}'))
        await db.commit()
        payloads = await Dao.list_visible_reply_payloads(db, JOB, 7)
        assert [json.loads(value)['text'] for value in payloads] == [f'{i}|' for i in range(130, 1, -1)]
        assert await Dao.list_visible_reply_payloads(db, JOB, 8) == []
        assert await Dao.list_visible_reply_payloads(db, 'foreign', 7) == []
        assert await Dao.list_visible_reply_payloads(db, 'missing', 7) == []
        request = {'prompt': '按第二点继续', 'source': {'type': 'none'}, 'contextParentJobId': JOB}
        child = SimpleNamespace(id='new-job', user_id=7, session_id=SESSION, request_json=json.dumps(request))
        history = await Manager._editing_continuation_history(db, child, MindmapAiJobCreateModel.model_validate(request))
        assert history[-1]['assistantReply'] == ''.join(f'{i}|' for i in range(3, 131))
        assert history[-1]['assistantReplyState'] == 'truncated'
        assert 'private' not in json.dumps(history)
        current.expires_time = datetime.now() - timedelta(seconds=1)
        await db.commit()
        assert await Dao.list_visible_reply_payloads(db, JOB, 7) == []


@pytest.mark.parametrize('payload', [None, '', '{', '[]', '{"executionEpoch":true,"executionState":"stopped"}',
                                    '{"executionEpoch":3,"executionState":{}}',
                                    '{"executionEpoch":2,"executionState":"stopped"}'])
def test_no_exit_claim_from_missing_malformed_or_other_epoch_evidence(payload):
    job = SimpleNamespace(execution_epoch=3, execution_state_json=payload, status='cancelled')
    assert job_execution_state(job) == 'unknown'
    assert execution_blocks_continuation(job)


def test_never_claimed_is_distinct_from_unknown_and_cleanup_failure():
    job = SimpleNamespace(execution_epoch=0, status='cancelled')
    assert job_execution_state(job) == 'not_started'
    assert not execution_blocks_continuation(job)
    job.error_code = 'AI_AGENT_CLEANUP_FAILED'
    assert job_execution_state(job) == 'unconfirmed'
    assert execution_blocks_continuation(job)


@pytest.mark.asyncio
async def test_real_sql_projection_refreshes_terminal_result_without_overwriting_it(database):
    assert await Manager._record_execution_state(JOB, 'running')
    async with TestSession(database) as db:
        job = await Dao.get_job(db, JOB)
        assert job_execution_state(job) == 'running'
        await Dao.update_job(db, JOB, {'status': 'ready', 'artifact_id': 'retained-artifact',
                                       'cancel_requested_time': datetime.now()})
        await db.commit()
        assert await Manager._record_execution_state(JOB, 'unconfirmed')
        refreshed = await Dao.get_job(db, JOB)
        assert refreshed is job  # The same identity map must not hide a new receipt.
        assert job_execution_state(refreshed) == 'unconfirmed'
        assert execution_blocks_continuation(refreshed)
        assert await Manager._record_execution_state(JOB, 'stopped')
        refreshed = await Dao.get_job(db, JOB)
        assert refreshed.status == 'ready'
        assert refreshed.artifact_id == 'retained-artifact'
        assert job_execution_state(refreshed) == 'stopped'
        assert not execution_blocks_continuation(refreshed)
        view = service._job_model(refreshed).model_dump(by_alias=True)
        assert view['executionState'] == 'stopped'
        assert view['executionEpoch'] == 3
        assert view['cancelRequestedTime'] is not None
        assert [event.sequence for event in await Dao.list_events(db, JOB, 0)] == [1, 2, 3]


@pytest.mark.asyncio
async def test_receipts_are_monotonic_idempotent_and_bound_to_owned_epoch(database):
    assert await Manager._record_execution_state(JOB, 'running')
    assert await Manager._record_execution_state(JOB, 'stopped')
    assert await Manager._record_execution_state(JOB, 'stopped')
    assert not await Manager._record_execution_state(JOB, 'unconfirmed')
    with pytest.raises(asyncio.CancelledError):
        await Manager._record_execution_state(JOB, 'running')
    async with TestSession(database) as db:
        assert len(await Dao.list_events(db, JOB, 0)) == 2
        await Dao.update_job(db, JOB, {'execution_epoch': 4})
        await db.commit()
    assert not await Manager._record_execution_state(JOB, 'stopped')
    with pytest.raises(asyncio.CancelledError):
        await Manager._record_execution_state(JOB, 'running')
    async with TestSession(database) as db:
        assert job_execution_state(await Dao.get_job(db, JOB)) == 'unknown'


@pytest.mark.asyncio
async def test_lost_lease_cannot_start_and_provider_cannot_attest_to_exit(database, monkeypatch):
    monkeypatch.setattr(Manager, '_owns_current_job_lease', AsyncMock(return_value=False))
    with pytest.raises(asyncio.CancelledError):
        await Manager._record_execution_state(JOB, 'running')
    with pytest.raises(MindmapArtifactError) as error:
        await Manager._emit(JOB, 'execution_state', {'executionState': 'stopped', 'executionEpoch': 3})
    assert error.value.code == 'AI_OUTPUT_INVALID'
    async with TestSession(database) as db:
        assert await Dao.list_events(db, JOB, 0) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['running', 'unconfirmed'])
async def test_recovered_lease_does_not_restart_unconfirmed_executor_and_closes_preview(database, monkeypatch, state):
    await Manager._record_execution_state(JOB, state)
    async with TestSession(database) as db:
        db.add(MindmapAiDraftCheckpoint(
            job_id=JOB, preview_version=2, preview_epoch=3,
            document_ciphertext='test-only', operations_ciphertext='test-only',
            document_hash='hash', summary_json='{}', expires_time=datetime.now() + timedelta(days=1),
        ))
        await db.commit()
    mark_terminal = AsyncMock()
    monkeypatch.setattr(Manager, 'mark_draft_terminal', mark_terminal)
    publish = AsyncMock()
    monkeypatch.setattr(Manager, '_publish_execution_epoch', publish)
    assert await Manager._prepare_claimed_job(JOB) is None
    async with TestSession(database) as db:
        job = await Dao.get_job(db, JOB)
        assert job.status == 'failed'
        assert job.execution_epoch == 3
        assert job_execution_state(job) == 'unconfirmed'
        assert await db.scalar(select(MindmapAiDraftCheckpoint)) is None
        events = await Dao.list_events(db, JOB, 0)
        assert any(e.event_type == 'status_changed' and json.loads(e.payload_json)['status'] == 'failed' for e in events)
    mark_terminal.assert_awaited_once_with(JOB, 3)
    publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('action,status', [('retry', 'failed'), ('followup', 'ready'), ('queue', 'ready')])
async def test_no_successor_before_exit_receipt(database, monkeypatch, action, status):
    await Manager._record_execution_state(JOB, 'running')
    async with TestSession(database) as db:
        await Dao.update_job(db, JOB, {'status': status})
        await db.commit()
        if action == 'queue':
            children = AsyncMock()
            monkeypatch.setattr(Dao, 'list_waiting_followups', children)
            await Manager._wake_waiting_followups(JOB)
            children.assert_not_awaited()
        else:
            with pytest.raises(ServiceException) as error:
                if action == 'retry':
                    await service.MindmapAiService.retry_job(db, JOB, MindmapAiJobRetryModel(), 7, 'retry')
                else:
                    await service.MindmapAiService.create_followup_job(
                        db, JOB, MindmapAiMessageModel(prompt='继续完善'), 7, 'followup',
                    )
            assert error.value.data['errorCode'] == 'AI_EXECUTION_STOP_UNCONFIRMED'


@pytest.mark.asyncio
@pytest.mark.parametrize('late_outcome', ['clean', 'cleanup_failed', 'cleanup_failed_subclass', 'new_epoch'])
async def test_late_cleanup_receipt_wakes_only_its_own_confirmed_execution(database, monkeypatch, late_outcome):
    await Manager._record_execution_state(JOB, 'unconfirmed')
    release = asyncio.Event()
    async def finish_cleanup():
        await release.wait()
        if late_outcome == 'cleanup_failed':
            raise MindmapArtifactError('not stopped', code='AI_AGENT_CLEANUP_FAILED')
        if late_outcome == 'cleanup_failed_subclass':
            raise AgentProcessCleanupError
    task = asyncio.create_task(finish_cleanup())
    wake = AsyncMock()
    monkeypatch.setattr(Manager, '_wake_waiting_followups', wake)
    Manager._observe_late_adapter_exit(task, JOB)
    if late_outcome == 'new_epoch':
        async with TestSession(database) as db:
            await Dao.update_job(db, JOB, {'execution_epoch': 4})
            await db.commit()
    release.set()
    await asyncio.gather(task, return_exceptions=True)
    # The done callback owns a separately tracked receipt task.
    await asyncio.sleep(0)
    await asyncio.gather(*Manager._detached_adapter_tasks, return_exceptions=True)
    async with TestSession(database) as db:
        assert job_execution_state(await Dao.get_job(db, JOB)) == {
            'clean': 'stopped', 'cleanup_failed': 'unconfirmed',
            'cleanup_failed_subclass': 'unconfirmed', 'new_epoch': 'unknown',
        }[late_outcome]
    assert wake.await_count == (1 if late_outcome == 'clean' else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('intent', ['create', 'discuss'])
@pytest.mark.parametrize('delivery_failure', [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize('retain_result', [False, True])
async def test_runner_cleanup_failure_remains_unconfirmed_and_blocks_successors(
    database: Engine, monkeypatch: pytest.MonkeyPatch, intent: str,
    delivery_failure: type[BaseException], retain_result: bool,
) -> None:
    child_id = '33333333-3333-4333-8333-333333333333'
    target = 'message' if intent == 'discuss' else 'file'
    retained_status = 'completed_message' if intent == 'discuss' else 'ready'
    async with TestSession(database) as db:
        await Dao.update_job(db, JOB, {
            'status': 'queued', 'intent': intent, 'target': target,
            'request_json': json.dumps({'agentKey': 'claude', 'intent': intent,
                                       'target': target, 'prompt': '测试', 'source': {'type': 'none'}}),
        })
        db.add(MindmapAiJob(
            id=child_id, user_id=7, session_id=SESSION, parent_job_id=JOB,
            agent_key='claude', adapter_version='test', intent=intent, target=target,
            source_type='empty', request_json='{}', request_fingerprint='child',
            idempotency_key='child', status='waiting_turn', expires_time=datetime.now() + timedelta(days=1),
        ))
        await db.commit()

    async def run(_context: AgentRunContext, emit: AgentEventHandler) -> NoReturn:
        await emit('agent_started', {'stage': 'building'})
        if retain_result:
            # A durable result fence may win the race before cleanup fails.
            async with TestSession(database) as db:
                await Dao.update_job(db, JOB, {'status': retained_status})
                await db.commit()
        raise AgentProcessCleanupError

    runner = AsyncMock(side_effect=run)
    manifest = SimpleNamespace(status='enabled', max_nodes=2000, max_depth=32, supports_sessions=False)
    adapter = SimpleNamespace(get_manifest=lambda: manifest, start=runner, resume=runner)
    monkeypatch.setattr(service, 'get_mindmap_agent_registry', lambda: SimpleNamespace(get=lambda _: adapter))
    monkeypatch.setattr(service, 'resolve_connector_credential', lambda *_: {})
    monkeypatch.setattr(service, 'load_ai_tag_catalog', AsyncMock(return_value=[]))
    monkeypatch.setattr(service.MindmapAiService, '_ensure_connector_available', AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(Manager, '_begin_draft_preview_run', AsyncMock())
    monkeypatch.setattr(Manager, 'mark_draft_terminal', AsyncMock())
    emit = AsyncMock(side_effect=delivery_failure)
    monkeypatch.setattr(Manager, '_emit', emit)
    schedule = MagicMock()
    monkeypatch.setattr(Manager, 'schedule', schedule)

    await Manager._run_job(JOB)

    runner.assert_awaited_once()
    async with TestSession(database) as db:
        job = await Dao.get_job(db, JOB)
        assert job_execution_state(job) == 'unconfirmed'
        assert job.status == (retained_status if retain_result else 'failed')
        assert (await Dao.get_job(db, child_id)).status == ('waiting_turn' if retain_result else 'cancelled')
        if not retain_result:
            assert job.error_code == 'AI_AGENT_CLEANUP_FAILED'
        with pytest.raises(ServiceException) as error:
            if retain_result:
                await service.MindmapAiService.create_followup_job(
                    db, JOB, MindmapAiMessageModel(prompt='继续完善'), 7, 'followup',
                )
            else:
                await service.MindmapAiService.retry_job(db, JOB, MindmapAiJobRetryModel(), 7, 'retry')
        assert error.value.data['errorCode'] == 'AI_EXECUTION_STOP_UNCONFIRMED'
    emit.assert_not_awaited()
    schedule.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('preserve_draft', [False, True])
async def test_cancel_response_reports_result_and_executor_independently(database, monkeypatch, preserve_draft):
    await Manager._record_execution_state(JOB, 'running')
    dispatch = AsyncMock(return_value=True)  # Request delivery is not exit proof.
    monkeypatch.setattr(Manager, 'cancel', dispatch)
    monkeypatch.setattr(Manager, 'mark_draft_terminal', AsyncMock())
    monkeypatch.setattr(Manager, '_close_waiting_followups', AsyncMock())
    monkeypatch.setattr(Manager, '_wake_waiting_followups', AsyncMock())
    async def retain_checkpoint(db, job):
        await Dao.update_job(db, job.id, {'status': 'ready', 'artifact_id': 'retained-draft'})
        return True
    monkeypatch.setattr(service.MindmapAiService, '_promote_draft_checkpoint_for_stop', retain_checkpoint)
    async with TestSession(database) as db:
        for _ in range(2):
            response = await service.MindmapAiService.cancel_job(db, JOB, 7, preserve_draft=preserve_draft)
            assert response.status == ('ready' if preserve_draft else 'cancelled')
            assert response.execution_state == 'running'
            assert response.cancel_requested_time is not None
        dispatch.assert_awaited_once()
        if preserve_draft:
            assert response.artifact_id == 'retained-draft'
        assert await Manager._record_execution_state(JOB, 'stopped')
        response = await service.MindmapAiService.get_job(db, JOB, 7)
        assert response.execution_state == 'stopped'
        assert response.status == ('ready' if preserve_draft else 'cancelled')
