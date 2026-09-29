"""Real DAO/domain transactions on disposable SQLite; no application DB or CLI.

Run only this file with MINDMAP_DB_INTEGRATION=1. SQLite verifies transaction
contents, not MySQL/PostgreSQL row-lock or concurrent-worker semantics.
"""
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import BigInteger, Integer, JSON, LargeBinary, MetaData, Text, create_engine, event, func, select
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT, MEDIUMBLOB
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from config.database import Base
from config.env import MindmapAiConfig
from exceptions.exception import ServiceException
from module_mindmap.ai.adapters.base import AgentManifest
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.entity.do.mindmap_ai_do import (
    MindmapAiConnector, MindmapAiDraftCheckpoint, MindmapAiJob, MindmapAiJobEvent, MindmapAiUndo,
)
from module_mindmap.entity.do.mindmap_content_do import MindmapChangeLog
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_version_do import MindmapVersion
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel, MindmapAiJobRetryModel
from module_mindmap.service import mindmap_ai_service as service
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.websocket.room_manager import room_manager

pytestmark = pytest.mark.skipif(os.getenv('MINDMAP_DB_INTEGRATION') != '1', reason='explicit isolated SQLite opt-in')
Manager, Dao = service.MindmapAiTaskManager, service.MindmapAiDao
USER, MAP = 7, 130
ROOT = {'data': {'uid': 'root', 'text': '数据库接续验收'}, 'children': [
    {'data': {'uid': 'original', 'text': '人工已有内容'}, 'children': []},
]}


class SqlSession:
    """Async service facade over real synchronous SQLite SQLAlchemy calls."""
    def __init__(self, engine):
        self.db = Session(engine, expire_on_commit=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.db.close()

    async def execute(self, statement, *args, **kwargs):
        return self.db.execute(statement, *args, **kwargs)

    async def scalar(self, statement):
        return self.db.scalar(statement)

    def add(self, value):
        self.db.add(value)

    async def flush(self):
        self.db.flush()

    async def refresh(self, value):
        self.db.refresh(value)

    async def commit(self):
        self.db.commit()

    async def rollback(self):
        self.db.rollback()

    @asynccontextmanager
    async def begin_nested(self):
        with self.db.begin_nested():
            yield


@pytest.fixture
def sql_database(monkeypatch):
    # Keep a positive connection allowlist even when the suite-wide opt-in is
    # set: an accidentally missed production SessionLocal must never connect.
    unexpected_connection = False
    def only_memory_sqlite(dialect, _record, args, _kwargs):
        nonlocal unexpected_connection
        if dialect.name != 'sqlite' or args != [':memory:']:
            unexpected_connection = True
            raise AssertionError('Only disposable in-memory SQLite is allowed')
    event.listen(Engine, 'do_connect', only_memory_sqlite)
    engine = create_engine('sqlite://', poolclass=StaticPool)
    try:
        metadata = MetaData()
        for source in Base.metadata.sorted_tables:
            if not (source.name.startswith('mindmap') or source.name == 'sys_user'):
                continue
            table = source.to_metadata(metadata)
            for column in table.c:
                if isinstance(column.type, LONGTEXT):
                    column.type = Text()
                elif isinstance(column.type, JSONB):
                    column.type = JSON()
                elif isinstance(column.type, (MEDIUMBLOB, LONGBLOB)):
                    column.type = LargeBinary()
                elif column.primary_key and isinstance(column.type, BigInteger):
                    column.type = Integer()
        metadata.create_all(engine)
        monkeypatch.setattr(service, 'AsyncSessionLocal', lambda: SqlSession(engine))
        yield engine
    finally:
        engine.dispose()
        event.remove(Engine, 'do_connect', only_memory_sqlite)
        assert not unexpected_connection, 'A service swallowed an unexpected database connection attempt'


@pytest.fixture
def database(sql_database, monkeypatch):
    monkeypatch.setattr(Manager, '_redis', None)
    monkeypatch.setattr(Manager, '_direct_commit_revisions', {})
    monkeypatch.setattr(Manager, '_draft_preview_runs', {})
    monkeypatch.setattr(Manager, '_owns_current_job_lease', AsyncMock(return_value=True))
    monkeypatch.setattr(Manager, 'schedule', Mock())
    monkeypatch.setattr(Manager, 'cancel', AsyncMock(return_value=True))
    monkeypatch.setattr(room_manager, 'get_active_lineage_epoch', AsyncMock(return_value='test-lineage'))
    monkeypatch.setattr(service.MindmapAiMutationGateway, 'publish_direct_commit', AsyncMock())
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_checkpoint_key', 'isolated-test-key-not-a-user-secret-' * 2)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_checkpoint_key_id', 'handoff-test')
    monkeypatch.setattr(service, 'resolve_connector_credential', lambda *_: {})
    def adapter(key):
        manifest = AgentManifest(agent_key=key, display_name=key, adapter_version='test', sdk_name='offline',
            sdk_version=None, runtime_version=None, intents=('expand',), input_types=('cloud_document',),
            supports_sessions=True, supports_streaming=True, supports_usage=False, status='enabled')
        return SimpleNamespace(get_manifest=lambda: manifest)
    monkeypatch.setattr(service, 'get_mindmap_agent_registry', lambda: SimpleNamespace(get=adapter))
    token = service._CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        yield sql_database
    finally:
        service._CURRENT_JOB_EXECUTION_EPOCH.reset(token)


async def create_running_job(engine):
    async with SqlSession(engine) as db:
        db.add(Mindmap(id=MAP, name='隔离验收', owner_id=USER, node_tree=json.dumps(ROOT),
                      theme={'template': 'default'}, view_data={'scale': 1.7}))
        for key in ('claude', 'codex', 'kimi'):
            db.add(MindmapAiConnector(agent_key=key, create_by='test', update_by='test',
                                     health_status='healthy', last_health_time=datetime.now()))
        await db.flush()
        metadata = await MindmapDocumentService.persist_tree(db, MAP, ROOT, USER, 'test')
        await MindmapDao.update_content_dao(db, MAP, metadata)
        await db.commit()
        request = MindmapAiJobCreateModel(agentKey='claude', intent='expand', prompt='保留原内容并补充边界',
            executionMode='direct', target='file', source={'type': 'cloud_document', 'mindmapId': MAP})
        job = await service.MindmapAiService.create_job(db, request, USER, 'first-request')
        await Dao.update_job(db, job.id, {'status': 'running', 'execution_epoch': 1,
                                        'external_session_ref': 'opaque-test-provider-session'})
        await db.commit()
    await Manager._record_execution_state(job.id, 'running')
    return job.id


async def change(engine, job_id, text):
    async with SqlSession(engine) as db:
        row = await Dao.get_job(db, job_id, USER)
        request = json.loads(row.request_json)
        tool = MindmapToolService(base_document=request['source']['document'], trusted_source=True, intent='expand')
    tool.add_nodes([{'parentUid': 'root', 'text': text}])
    delta = tool.build_stream_delta(after_cursor=0, tool_name='add_nodes')
    await Manager._emit(job_id, 'draft_changed', delta)
    return delta


@pytest.mark.asyncio
async def test_committed_partial_edits_survive_stop_retry_and_scoped_undo(database, monkeypatch):
    job_id = await create_running_job(database)
    await Manager._emit(job_id, 'todo_updated', {'todos': [{'content': '补充剩余边界', 'status': 'in_progress'}], 'origin': 'agent'})
    await Manager._emit(job_id, 'assistant_delta', {'text': '第二点建议：补充断线恢复。', 'visibility': 'visible'})
    await change(database, job_id, '旧 Agent 已提交部分')
    async with SqlSession(database) as db:
        detail = await service.MindmapService.get_mindmap_detail_services(db, MAP, USER)
        assert detail.content_revision == 2
        assert [node['data']['text'] for node in detail.node_tree['children']] == ['人工已有内容', '旧 Agent 已提交部分']
        checkpoint = await Dao.get_draft_checkpoint(db, job_id)
        assert Manager._draft_checkpoint_preview(checkpoint)['document']['root'] == detail.node_tree
        receipt = await Dao.get_undo(db, job_id, USER)
        assert receipt.status == 'available' and receipt.applied_revision == 2
        assert json.loads(receipt.before_document_json)['view'] == {'scale': 1.7}
        assert await db.scalar(select(func.count(MindmapVersion.id))) == 1
        stopped = await service.MindmapAiService.cancel_job(db, job_id, USER)
        assert stopped.status == 'cancelled' and stopped.execution_state == 'running'
        with pytest.raises(ServiceException) as error:
            await service.MindmapAiService.retry_job(db, job_id, MindmapAiJobRetryModel(agentKey='codex'), USER, 'retry')
        assert error.value.data['errorCode'] == 'AI_EXECUTION_STOP_UNCONFIRMED'
    await Manager._record_execution_state(job_id, 'stopped')
    async with SqlSession(database) as db:
        next_job = await service.MindmapAiService.retry_job(db, job_id, MindmapAiJobRetryModel(agentKey='codex'), USER, 'retry')
        row = await Dao.get_job(db, next_job.id, USER)
        assert row.retry_of_job_id == job_id and row.parent_job_id is None and row.external_session_ref is None
        request = MindmapAiJobCreateModel.model_validate_json(row.request_json)
        assert row.base_revision == 2 and request.source.document['root'] == detail.node_tree
        history = await Manager._editing_continuation_history(db, row, request)
        assert history[-1]['agentKey'] == 'claude'
        assert history[-1]['agentPlan'][0]['content'] == '补充剩余边界'
        assert history[-1]['assistantReply'] == '第二点建议：补充断线恢复。'
        assert history[-1]['assistantReplyState'] == 'recorded'
        assert 'opaque-test-provider-session' not in json.dumps(history)
        replay = await service.MindmapAiService.retry_job(db, job_id, MindmapAiJobRetryModel(agentKey='codex'), USER, 'retry')
        assert replay.id == next_job.id
        assert await db.scalar(select(func.count(MindmapAiJob.id))) == 2
        await Dao.update_job(db, next_job.id, {'status': 'running', 'execution_epoch': 1})
        await db.commit()
    await Manager._record_execution_state(next_job.id, 'running')
    await change(database, next_job.id, '新 Agent 补充部分')
    await change(database, job_id, '旧 Agent 迟到写入不得落库')
    async with SqlSession(database) as db:
        result = await service.MindmapService.get_mindmap_detail_services(db, MAP, USER)
        assert result.content_revision == 3
        assert [node['data']['text'] for node in result.node_tree['children']] == ['人工已有内容', '旧 Agent 已提交部分', '新 Agent 补充部分']
        assert await db.scalar(select(func.count(MindmapChangeLog.id))) == 2
        await service.MindmapAiService.cancel_job(db, next_job.id, USER)
    await Manager._record_execution_state(next_job.id, 'stopped')
    # Collaboration clients are outside this SQL test. Keep the real undo
    # transaction and its revision/hash checks; substitute only room barriers.
    barrier = object()
    for name, value in {
        'acquire_collaboration_mutation_barrier': barrier, 'wait_for_collaboration_mutation_barrier': True,
        'verify_collaboration_mutation_barrier': True, 'prepare_collaboration_mutation_barrier_commit': barrier,
        'complete_collaboration_mutation_barrier': True, 'abort_collaboration_mutation_barrier': None,
    }.items():
        monkeypatch.setattr(room_manager, name, AsyncMock(return_value=value))
    async with SqlSession(database) as db:
        with pytest.raises(ServiceException) as error:
            await service.MindmapAiService.undo_cloud_proposal(db, MAP, job_id, USER, 'test', 'old-undo')
        assert error.value.data['errorCode'] == 'AI_UNDO_CONFLICT', 'old turn must not erase the successor'
        undone = await service.MindmapAiService.undo_cloud_proposal(db, MAP, next_job.id, USER, 'test', 'new-undo')
        assert undone['status'] == 'undone' and undone['contentRevision'] == 4
        detail = await service.MindmapService.get_mindmap_detail_services(db, MAP, USER)
        assert [node['data']['text'] for node in detail.node_tree['children']] == ['人工已有内容', '旧 Agent 已提交部分']
        assert detail.view_data == {'scale': 1.7}
        replay = await service.MindmapAiService.undo_cloud_proposal(db, MAP, next_job.id, USER, 'test', 'new-undo')
        assert replay['idempotentReplay'] is True and replay['contentRevision'] == 4
        assert await db.scalar(select(func.count(MindmapChangeLog.id))) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['event-constraint', 'missing-event', 'checkpoint-failure', 'commit-constraint'])
async def test_document_checkpoint_event_and_undo_roll_back_together(database, monkeypatch, failure):
    job_id = await create_running_job(database)
    async with SqlSession(database) as db:
        baseline = await service.MindmapService.get_mindmap_detail_services(db, MAP, USER)
    if failure == 'checkpoint-failure':
        monkeypatch.setattr(service.MindmapAiCheckpointCrypto, 'encrypt_envelope', Mock(side_effect=RuntimeError('injected checkpoint failure')))
    elif failure == 'commit-constraint':
        original_commit = SqlSession.commit
        async def fail_commit(db):
            db.add(MindmapAiJobEvent(job_id=job_id, sequence=1, event_type='draft_changed', payload_json='{}'))
            await original_commit(db)
        monkeypatch.setattr(SqlSession, 'commit', fail_commit)
    else:
        async def fail_event(db, *_args):
            if failure == 'missing-event':
                return None
            # Exercise the real unique constraint, not a synthetic SQL error.
            db.add(MindmapAiJobEvent(job_id=job_id, sequence=1, event_type='draft_changed', payload_json='{}'))
            await db.flush()
        monkeypatch.setattr(Dao, 'add_event', fail_event)
    if failure == 'missing-event':
        await change(database, job_id, '不能留下半次提交')
    else:
        with pytest.raises(RuntimeError if failure == 'checkpoint-failure' else MindmapArtifactError):
            await change(database, job_id, '不能留下半次提交')
    async with SqlSession(database) as db:
        detail = await service.MindmapService.get_mindmap_detail_services(db, MAP, USER)
        assert detail.content_revision == 1 and detail.node_tree == baseline.node_tree
        assert detail.view_data == baseline.view_data and detail.theme == baseline.theme
        for model in (MindmapAiDraftCheckpoint, MindmapAiUndo, MindmapChangeLog, MindmapVersion):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
        assert len(await Dao.list_events(db, job_id, 0)) == 2  # created + running
        assert (await Dao.get_job(db, job_id, USER)).proposal_id is None
    assert Manager._direct_commit_revisions == {}
    service.MindmapAiMutationGateway.publish_direct_commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('restriction', ['agent-disabled', 'map-archived', 'map-access-revoked'])
async def test_handoff_rechecks_real_connector_and_document_permissions(database, restriction):
    job_id = await create_running_job(database)
    await change(database, job_id, '停止前已提交内容')
    async with SqlSession(database) as db:
        await service.MindmapAiService.cancel_job(db, job_id, USER)
    await Manager._record_execution_state(job_id, 'stopped')
    async with SqlSession(database) as db:
        if restriction == 'agent-disabled':
            await Dao.update_connector(db, 'codex', {'enabled': 0})
        else:
            await MindmapDao.update_content_dao(db, MAP, {'status': 1} if restriction == 'map-archived' else {'owner_id': USER + 1})
        await db.commit()
        with pytest.raises(ServiceException):
            await service.MindmapAiService.retry_job(db, job_id, MindmapAiJobRetryModel(agentKey='codex'), USER, 'denied-retry')
        assert await db.scalar(select(func.count(MindmapAiJob.id))) == 1
        assert await db.scalar(select(func.count(MindmapChangeLog.id))) == 1
        detail = await MindmapDao.get_mindmap_by_id(db, MAP)
        assert detail.content_revision == 2
        assert json.loads(detail.node_tree)['children'][-1]['data']['text'] == '停止前已提交内容'
