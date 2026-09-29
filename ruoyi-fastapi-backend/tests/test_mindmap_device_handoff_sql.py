"""Opt-in, isolated device handoff through actual scheduling and SQL commits.

Only the CLI/model protocol peers and collaboration broadcast are substituted.
Never connects to the application database, Redis, real CLI login or provider.
SQLite verifies persisted contents, not production-database concurrent locks.
"""
import asyncio
import json
import os
import socket
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from sqlalchemy import func, select
from websockets.asyncio.client import connect

from config.env import MindmapAiConfig
from module_admin.entity.do.user_do import SysUser
from module_mindmap.ai.adapters.device import DeviceClaudeAdapter, DeviceCodexAdapter, DeviceKimiAdapter
from module_mindmap.ai.adapters.registry import MindmapAgentRegistry
from module_mindmap.ai.device_dispatch import DeviceDispatch
from module_mindmap.ai.execution_state import job_execution_state
from module_mindmap.controller import mindmap_ai_device_controller as controller
from module_mindmap.entity.do.mindmap_ai_do import MindmapAiConnector, MindmapAiJob
from module_mindmap.entity.do.mindmap_content_do import MindmapChangeLog
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_ai_device_vo import DeviceEnrollment
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel, MindmapAiJobRetryModel
from module_mindmap.service import mindmap_ai_device_execution as execution
from module_mindmap.service.mindmap_ai_device_service import MindmapAiDeviceService
from tests.test_mindmap_device_dispatch import (
    device_client, handoff_driver, private_device_run_registry, private_redis, redis,
)
from tests.test_mindmap_handoff_persistence import (
    Dao, MAP, Manager, MindmapDao, MindmapDocumentService, ROOT, SqlSession, USER,
    room_manager, service, sql_database,
)

pytestmark = pytest.mark.skipif(os.getenv('MINDMAP_DB_INTEGRATION') != '1', reason='explicit isolated SQLite opt-in')
SECRET = 'd' * 43


@pytest_asyncio.fixture
async def system(sql_database, redis, device_client, monkeypatch, private_device_run_registry):
    for field in ('mindmap_ai_device_bridge_enabled', 'mindmap_ai_device_execution_enabled',
                  'mindmap_ai_device_codex_enabled', 'mindmap_ai_device_kimi_enabled'):
        monkeypatch.setattr(MindmapAiConfig, field, True)
    for key, model in [('claude', 'sonnet'), ('codex', 'gpt-5.6-terra'), ('kimi', 'kimi-for-coding')]:
        monkeypatch.setattr(MindmapAiConfig, f'mindmap_ai_{key}_model', model)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_checkpoint_key', 'isolated-sql-device-key-' * 3)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_checkpoint_key_id', 'sql-device-test')
    registry = MindmapAgentRegistry()
    for adapter in (DeviceClaudeAdapter(), DeviceCodexAdapter(), DeviceKimiAdapter()):
        registry.register(adapter)
    monkeypatch.setattr(service, 'get_mindmap_agent_registry', lambda: registry)
    for module in (controller, execution):
        monkeypatch.setattr(module, 'AsyncSessionLocal', lambda: SqlSession(sql_database))
    monkeypatch.setattr(Manager, '_redis', redis)
    for name in ('_tasks', '_draft_preview_runs', '_direct_commit_revisions', '_claimed_execution_epochs'):
        monkeypatch.setattr(Manager, name, {})
    for name in ('_lease_lost_tasks', '_detached_adapter_tasks'):
        monkeypatch.setattr(Manager, name, set())
    monkeypatch.setattr(Manager, '_shutting_down', False)
    monkeypatch.setattr(room_manager, 'get_active_lineage_epoch', AsyncMock(return_value='sql-device-lineage'))
    monkeypatch.setattr(service.MindmapAiMutationGateway, 'publish_direct_commit', AsyncMock())
    async with SqlSession(sql_database) as db:
        db.add(SysUser(user_id=USER, user_name='isolated-test', nick_name='测试', status='0', del_flag='0'))
        tree = deepcopy(ROOT)
        tree['data']['text'] = '接力验收'
        db.add(Mindmap(id=MAP, name='隔离接力验收', owner_id=USER, node_tree=json.dumps(tree),
                      theme={'template': 'default'}, view_data={'scale': 1.7}))
        for key in ('claude', 'codex', 'kimi'):
            db.add(MindmapAiConnector(agent_key=f'device_{key}', create_by='test', update_by='test',
                                     health_status='healthy', last_health_time=datetime.now()))
        await db.flush()
        metadata = await MindmapDocumentService.persist_tree(db, MAP, tree, USER, 'test')
        await MindmapDao.update_content_dao(db, MAP, metadata)
        await db.commit()
        pairing = await MindmapAiDeviceService.create_pairing(db, USER, '隔离验收设备')
        device_id, pairing_secret = pairing['pairingCode'].split('.')
        await MindmapAiDeviceService.enroll(db, DeviceEnrollment(
            deviceId=device_id, pairingSecret=pairing_secret, deviceSecret=SECRET))
    app = FastAPI()
    app.state.redis = redis
    app.include_router(controller.mindmap_ai_bridge_controller)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan='off'))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async def ready():
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(.01)
        await asyncio.wait_for(ready(), 3)
        yield SimpleNamespace(engine=sql_database, device_id=device_id,
            url=f'ws://127.0.0.1:{listener.getsockname()[1]}/mindmap/ai/device-bridge/execute/{device_id}')
    finally:
        pending = list(Manager._tasks.values())
        for worker in pending:
            worker.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('previous,next_agent', [
    ('claude', 'codex'), ('claude', 'kimi'), ('codex', 'claude'),
    ('codex', 'kimi'), ('kimi', 'claude'), ('kimi', 'codex'),
])
async def test_scheduled_device_handoff_persists_partial_edits_and_actual_exit_evidence(
    system, redis, device_client, monkeypatch, tmp_path, previous, next_agent,
):
    previous_id = None
    for key in (previous, next_agent):
        driver = handoff_driver(key, monkeypatch, tmp_path)
        unused = SimpleNamespace(run=AsyncMock(side_effect=AssertionError('unselected Agent ran')), stop=AsyncMock())
        async with connect(system.url, additional_headers={'Authorization': 'Bearer ' + SECRET},
                           proxy=None, max_size=8 * 1024 * 1024) as ws:
            client = asyncio.create_task(device_client.connected_execution(ws,
                {name: driver if name == key else unused for name in ('claude', 'codex', 'kimi')},
                agent_keys=('claude', 'codex', 'kimi'), accept_estimated_budget=True, accept_unmetered_budget=True))
            try:
                async def available():
                    while not await DeviceDispatch(redis, system.device_id).available(USER, key):
                        if client.done():
                            raise AssertionError(f'device connection ended: {client.result()}')
                        await asyncio.sleep(.01)
                await asyncio.wait_for(available(), 3)
                async with SqlSession(system.engine) as db:
                    if previous_id is None:
                        job = await service.MindmapAiService.create_job(db, MindmapAiJobCreateModel(
                            agentKey=f'device_{key}', deviceId=system.device_id, intent='expand', prompt='handoff-stop',
                            executionMode='direct', target='file', source={'type': 'cloud_document', 'mindmapId': MAP}),
                            USER, 'create')
                    else:
                        job = await service.MindmapAiService.retry_job(db, previous_id, MindmapAiJobRetryModel(
                            agentKey=f'device_{key}', deviceId=system.device_id, prompt='handoff-continue'), USER, 'handoff')
                        row = await Dao.get_job(db, job.id, USER)
                        assert row.base_revision == 2 and row.retry_of_job_id == previous_id
                        assert row.external_session_ref is None and row.parent_job_id is None
                worker = Manager._tasks[job.id]
                if previous_id is None:
                    async def edited():
                        while True:
                            async with SqlSession(system.engine) as db:
                                detail = await service.MindmapService.get_mindmap_detail_services(db, MAP, USER)
                                if detail.content_revision == 2:
                                    checkpoint = await Dao.get_draft_checkpoint(db, job.id)
                                    assert Manager._draft_checkpoint_preview(checkpoint)['document']['root'] == detail.node_tree
                                    return
                                if worker.done():
                                    row = await Dao.get_job(db, job.id, USER)
                                    raise AssertionError(f'worker ended before edit: {row.status} {row.error_code} {row.error_message}')
                            await asyncio.sleep(.02)
                    await asyncio.wait_for(edited(), 15)
                    async with SqlSession(system.engine) as db:
                        await service.MindmapAiService.cancel_job(db, job.id, USER)
                    await asyncio.wait_for(asyncio.gather(worker, return_exceptions=True), 10)
                    assert await asyncio.wait_for(client, 3) == 'stopped'
                else:
                    await asyncio.wait_for(asyncio.shield(worker), 15)
                    assert await asyncio.wait_for(client, 3) == 'completed'
                async with SqlSession(system.engine) as db:
                    row = await Dao.get_job(db, job.id, USER)
                    assert row.status == ('cancelled' if previous_id is None else 'completed_direct'), row.error_message
                    assert job_execution_state(row) == 'stopped' and row.execution_epoch == 1
                    events = await Dao.list_events(db, job.id, 0)
                    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
                    assert sum(event.event_type == 'draft_changed' for event in events) == 1
                    assert sum(event.event_type == 'todo_updated' for event in events) == (1 if previous_id is None else 2)
                    stop_event = json.loads(events[-1].payload_json)
                    assert events[-1].event_type == 'execution_state'
                    assert stop_event['executionState'] == 'stopped' and stop_event['executionEpoch'] == 1
                    receipt = await Dao.get_undo(db, job.id, USER)
                    assert receipt.status == 'available' and receipt.applied_revision == (2 if previous_id is None else 3)
                    assert await Dao.get_draft_checkpoint(db, job.id) is None
                assert driver.owner.process.returncode is not None and not driver.owner._alive()
                assert not Path(driver._directory).exists()
                unused.run.assert_not_awaited()
                assert not await DeviceDispatch(redis, system.device_id).state()
                previous_id = job.id
            finally:
                client.cancel()
                await asyncio.gather(client, return_exceptions=True)
                await driver.stop()
    async with SqlSession(system.engine) as db:
        detail = await service.MindmapService.get_mindmap_detail_services(db, MAP, USER)
        assert detail.content_revision == 3 and detail.view_data == {'scale': 1.7}
        assert [node['data']['text'] for node in detail.node_tree['children']] == [
            '人工已有内容', '上一轮已确认部分', '下一位完成剩余部分']
        assert await db.scalar(select(func.count(MindmapAiJob.id))) == 2
        assert await db.scalar(select(func.count(MindmapChangeLog.id))) == 2
