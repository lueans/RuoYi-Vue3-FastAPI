"""Isolated Redis + actual ASGI/WebSocket + platform gateway; no provider calls."""

import asyncio
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis
from starlette.responses import StreamingResponse
from websockets.asyncio.client import connect

from config.env import MindmapAiConfig
from exceptions.exception import ServiceException
from module_mindmap.ai.adapters.base import AgentRunContext
from module_mindmap.ai.adapters.base import AgentDirectResult
from module_mindmap.ai.device_dispatch import MAX_QUEUE_MESSAGES, DeviceDispatch, DispatchedRunConnection
from module_mindmap.ai.device_run_session import DeviceRunBinding
from module_mindmap.ai.device_runtime import execution_agents
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.controller import mindmap_ai_device_controller as controller
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel, MindmapAiMessageModel
from module_mindmap.service import mindmap_ai_device_execution as execution
from module_mindmap.service.mindmap_ai_service import MindmapAiTaskManager

DEVICE = '11111111-1111-4111-8111-111111111111'
JOB = '22222222-2222-4222-8222-222222222222'
SECRET = 's' * 43


@pytest.fixture(scope='module')
def private_redis():
    binary = shutil.which('redis-server')
    if not binary:
        pytest.skip('redis-server is needed for isolated dispatch integration')
    # Short socket path also works on macOS. Never contacts configured Redis.
    with tempfile.TemporaryDirectory(prefix='mm-dispatch-', dir='/tmp') as directory:
        path = directory + '/redis.sock'
        process = subprocess.Popen([binary, '--port', '0', '--unixsocket', path,
                                    '--save', '', '--appendonly', 'no', '--dir', directory],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 3
            while not Path(path).exists():
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)
            yield path
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


@pytest_asyncio.fixture
async def redis(private_redis):
    client = Redis(unix_socket_path=private_redis, decode_responses=True)
    await client.flushdb()  # only this test-owned socket / server
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def device_client(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'mindmap-agent-bridge'))
    return importlib.import_module('mindmap_agent_bridge.execution_client')


@pytest.fixture(autouse=True)
def private_device_run_registry(monkeypatch, tmp_path):
    if importlib.util.find_spec('psutil') is None:
        return
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'mindmap-agent-bridge'))
    recovery = importlib.import_module('mindmap_agent_bridge.run_recovery')
    monkeypatch.setattr(recovery, 'run_root', lambda: tmp_path / 'private-device-runs')


@pytest.mark.asyncio
async def test_atomic_owner_reservation_cannot_take_over_replay_or_close_successor(redis):
    dispatch = DeviceDispatch(redis, DEVICE)
    connection = await dispatch.open(7, 'claude')
    assert await dispatch.available(7)
    assert not await dispatch.available(8)
    with pytest.raises(MindmapArtifactError):
        await dispatch.open(7, 'claude')
    with pytest.raises(MindmapArtifactError):
        await dispatch.reserve(job_id=JOB, user_id=8, epoch=1)
    outcomes = await asyncio.gather(*[
        dispatch.reserve(job_id=str(uuid4()), user_id=7, epoch=1) for _ in range(4)
    ], return_exceptions=True)
    assert sum(not isinstance(value, Exception) for value in outcomes) == 1
    binding = next(value for value in outcomes if not isinstance(value, Exception))
    assert await dispatch.owns(binding)
    await dispatch.close(connection)
    replacement = await dispatch.open(7, 'claude')
    await dispatch.close(connection)
    assert (await dispatch.state())['connection'] == replacement
    with pytest.raises(MindmapArtifactError):
        await DispatchedRunConnection(dispatch, binding).send('old task')
    assert not await dispatch.owns(binding)


@pytest.mark.asyncio
async def test_mailboxes_are_bounded_and_fenced_by_expiry(redis):
    dispatch = DeviceDispatch(redis, DEVICE)
    connection = await dispatch.open(7, 'claude')
    binding = await dispatch.reserve(job_id=JOB, user_id=7, epoch=1)
    for _ in range(MAX_QUEUE_MESSAGES):
        await dispatch.push(connection, 'in', 'test')
    assert await redis.llen(dispatch._keys(connection)[3]) == 1
    with pytest.raises(MindmapArtifactError):
        await dispatch.push(connection, 'in', 'overflow')
    for _ in range(MAX_QUEUE_MESSAGES):
        assert await dispatch.pop(connection, 'in', binding=binding) == 'test'
    assert (await dispatch.state())['inBytes'] == '0'
    # A worker cannot keep a disconnected device alive by pushing messages.
    await redis.pexpire(dispatch.key, 1)
    await asyncio.sleep(0.01)
    assert not await dispatch.owns(binding)
    with pytest.raises(MindmapArtifactError):
        await dispatch.push(connection, 'out', 'late', binding=binding)


@pytest.mark.asyncio
async def test_waiting_consumer_is_woken_without_polling_or_lost_payload(redis):
    dispatch = DeviceDispatch(redis, DEVICE)
    connection = await dispatch.open(7, 'claude')
    binding = await dispatch.reserve(job_id=JOB, user_id=7, epoch=1)
    reader = asyncio.create_task(dispatch.pop(connection, 'in', binding=binding))
    await asyncio.sleep(0.03)
    assert not reader.done()
    await dispatch.push(connection, 'in', 'stream chunk')
    assert await asyncio.wait_for(reader, 0.5) == 'stream chunk'


@asynccontextmanager
async def fake_db():
    yield object()


@pytest.fixture
def authorized(monkeypatch):
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_bridge_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_execution_enabled', True)
    monkeypatch.setattr(controller, 'AsyncSessionLocal', fake_db)
    monkeypatch.setattr(execution, 'AsyncSessionLocal', fake_db)
    authentication = AsyncMock(return_value=SimpleNamespace(user_id=7))
    monkeypatch.setattr(controller.MindmapAiDeviceService, 'authenticate', authentication)
    job = SimpleNamespace(agent_key='device_claude', execution_epoch=1, status='running',
                          request_json=json.dumps({'deviceId': DEVICE}), session_id='session', source_mindmap_id=130)
    monkeypatch.setattr(execution.MindmapAiDao, 'get_job', AsyncMock(return_value=job))
    monkeypatch.setattr(execution.MindmapAiDao, 'get_session', AsyncMock(return_value=SimpleNamespace(
        status='active', expires_time=datetime.now() + timedelta(hours=1),
    )))
    owned = AsyncMock(return_value=True)
    monkeypatch.setattr(execution, 'device_is_owned', owned)
    read = AsyncMock(return_value={})
    monkeypatch.setattr(execution.MindmapAiMutationGateway, 'read_document', read)
    return SimpleNamespace(auth=authentication, job=job, owned=owned, read=read)


@pytest_asyncio.fixture
async def endpoint(redis, authorized):
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
                await asyncio.sleep(0.01)
        await asyncio.wait_for(ready(), 3)
        yield f'ws://127.0.0.1:{listener.getsockname()[1]}/mindmap/ai/device-bridge/execute/{DEVICE}'
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


async def wait_available(redis, agent_key='claude'):
    async def ready():
        while not await DeviceDispatch(redis, DEVICE).available(7, agent_key):
            await asyncio.sleep(0.01)
    await asyncio.wait_for(ready(), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize('duplicate_executes', [False, True])
async def test_duplicate_bridge_cannot_interrupt_existing_run(
    endpoint, redis, authorized, device_client, monkeypatch, duplicate_executes,
):
    from mindmap_agent_bridge import client, run_recovery
    from module_mindmap.ai.device_run_session import DeviceRunSession
    from module_mindmap.ai.device_run_transport import run_device_session

    device = SimpleNamespace(user_id=7, scan_requested=1, scan_completed=0,
                             connection_id=None, last_seen_time=None)
    authorized.auth.return_value = device

    @asynccontextmanager
    async def memory_db():
        yield SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(controller, 'AsyncSessionLocal', memory_db)
    async def disconnect(_db, _device_id, connection_id):
        if device.connection_id == connection_id:
            device.connection_id = None
    monkeypatch.setattr(controller.MindmapAiDeviceService, 'disconnect', disconnect)
    original_session = client.connected_session
    scan = AsyncMock(return_value=[{
        'agentKey': key, 'installed': False, 'version': None,
        'status': 'not_installed', 'capabilities': [],
    } for key in ('claude', 'codex', 'kimi')])
    async def scanner(socket):
        await original_session(socket, scan=scan)
    monkeypatch.setattr(client, 'connected_session', scanner)
    monkeypatch.setattr(client, 'HEARTBEAT_SECONDS', 0.1)
    monkeypatch.setattr(client, 'CONNECTION_CONFLICT_RETRY_SECONDS', 0.2)
    # Accelerate the heartbeat without exercising the unrelated rate limiter.
    monkeypatch.setattr(controller, 'MAX_FRAMES_PER_WINDOW', 1_000)

    started, release = asyncio.Event(), asyncio.Event()
    class Driver:
        stopped = False
        async def run(self, offer, channel):
            self.workspace = run_recovery.OwnedRun.create('claude')
            started.set()
            await release.wait()
            await channel.public_text('重复启动后继续完成', message_id='still-running')
            return {'completionState': 'message_completed', 'content': '正常完成'}
        async def stop(self):
            self.workspace.cleanup()
            self.stopped = True
    driver = Driver()
    monkeypatch.setattr(device_client, 'local_drivers', lambda *a, **kw: {'claude': driver})
    config = {'server': endpoint.split('/mindmap/')[0].replace('ws:', 'http:'),
              'deviceId': DEVICE, 'deviceSecret': SECRET}
    first = asyncio.create_task(device_client.run_with_execution(config))
    second = platform = None
    try:
        await wait_available(redis)
        dispatch = DeviceDispatch(redis, DEVICE)
        binding = await dispatch.reserve(job_id=JOB, user_id=7, epoch=1)
        run_context = AgentRunContext(job_id=JOB, user_id=7, intent='discuss', prompt='离线测试',
                                      parameters={}, source_document=None, tool_service=MindmapToolService())
        session = DeviceRunSession(binding, run_context, AsyncMock(), AsyncMock(return_value=True))
        connection = DispatchedRunConnection(dispatch, binding)
        async def platform_run():
            try:
                return await run_device_session(session, connection, cancel_grace=.2)
            finally:
                await connection.finish()
        platform = asyncio.create_task(platform_run())
        await asyncio.wait_for(started.wait(), 3)
        previous_connection = device.connection_id
        assert (await run_recovery.recover_runs())['active'] == 1
        second = asyncio.create_task((device_client.run_with_execution if duplicate_executes else client.run)(config))
        with pytest.raises(client.BridgeError):
            await asyncio.wait_for(second, 3)
        assert device.connection_id == previous_connection
        assert await dispatch.owns(binding)
        assert not driver.stopped and not first.done()
        # Exercise the original scan socket's next heartbeat after rejection.
        previous_seen = device.last_seen_time
        async def heartbeat_received():
            while device.last_seen_time <= previous_seen:
                if first.done():
                    first.result()
                await asyncio.sleep(.01)
        await asyncio.wait_for(heartbeat_received(), 1)
        release.set()
        result = await asyncio.wait_for(platform, 3)
        assert result.content == '正常完成' and driver.stopped
        await wait_available(redis)
        assert not first.done() and device.connection_id == previous_connection
    finally:
        release.set()
        for task in (first, second, platform):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (first, second, platform) if task), return_exceptions=True)


@pytest.mark.asyncio
async def test_scanner_retries_orphaned_discovery_lease_without_losing_authorization(
    endpoint, authorized, device_client, monkeypatch,
):
    from mindmap_agent_bridge import client
    from websockets.exceptions import InvalidStatus

    stale_connection = str(uuid4())
    device = SimpleNamespace(user_id=7, scan_requested=1, scan_completed=0,
                             connection_id=stale_connection, last_seen_time=datetime.now())
    authorized.auth.return_value = device
    @asynccontextmanager
    async def memory_db():
        yield SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(controller, 'AsyncSessionLocal', memory_db)
    async def disconnect(_db, _device_id, connection_id):
        if device.connection_id == connection_id:
            device.connection_id = None
    monkeypatch.setattr(controller.MindmapAiDeviceService, 'disconnect', disconnect)

    rejected, connected = [], asyncio.Event()
    real_connect = client.NoRedirectConnect
    @asynccontextmanager
    async def observe_connect(*args, **kwargs):
        try:
            async with real_connect(*args, **kwargs) as socket:
                yield socket
        except InvalidStatus as error:
            rejected.append(error.response.status_code)
            assert error.response.status_code == 409
            assert error.response.headers['retry-after'] == '20'
            assert device.connection_id == stale_connection
            # Advance only the simulated orphan's timestamp, not the client's
            # retry implementation or the real WebSocket handshake.
            device.last_seen_time = datetime.now() - timedelta(seconds=21)
            raise
    monkeypatch.setattr(client, 'NoRedirectConnect', observe_connect)
    async def session(socket):
        assert client.decode_state(await socket.recv(), 'welcome')['type'] == 'welcome'
        await socket.send('{"type":"heartbeat","protocolVersion":1}')
        assert client.decode_state(await socket.recv(), 'state')['scanRevision'] == 1
        connected.set()
        await asyncio.Future()
    monkeypatch.setattr(client, 'connected_session', session)
    config = {'server': endpoint.split('/mindmap/')[0].replace('ws:', 'http:'),
              'deviceId': DEVICE, 'deviceSecret': SECRET}
    scanner = asyncio.create_task(client.run(config))
    ready = asyncio.create_task(connected.wait())
    try:
        done, _ = await asyncio.wait({scanner, ready}, timeout=3, return_when=asyncio.FIRST_COMPLETED)
        if scanner in done:
            scanner.result()
        assert ready in done and not scanner.done()
        assert rejected == [409] and device.connection_id != stale_connection
    finally:
        scanner.cancel()
        ready.cancel()
        await asyncio.gather(scanner, ready, return_exceptions=True)


def context():
    return AgentRunContext(
        job_id=JOB, user_id=7, intent='create', prompt='创建订单流程', parameters={},
        source_document=None, tool_service=MindmapToolService(),
        metadata={'timeoutSeconds': 30, 'maxBudgetUsd': 0.05, 'modelRef': 'sonnet',
                  'credentialEnv': {'API_KEY': 'never-forward-platform-secret'}},
    )


class PreviewDriver:
    stopped = False
    async def run(self, offer, channel):
        assert offer.max_budget_usd == 0.05 and offer.model_ref == 'sonnet' and offer.timeout_seconds == 30
        await channel.public_text('正在整理订单流程', message_id='m1')
        await channel.tool('update_plan', {'todos': [{'content': '建立结构', 'status': 'in_progress'}]})
        first = await channel.tool('start_document', {'title': '订单'})
        await channel.tool('add_nodes', {'nodes': [{'parentUid': first['result']['rootUid'], 'text': '支付'}]})
        await channel.tool('update_plan', {'todos': [{'content': '建立结构', 'status': 'completed'}]})
        await channel.tool('complete_artifact', {})
        return {'completionState': 'artifact_completed'}
    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_multi_agent_reservation_is_atomic_and_cannot_fall_back_to_other_runtime(redis):
    dispatch = DeviceDispatch(redis, DEVICE)
    first = await dispatch.open(7, 'claude')
    with pytest.raises(MindmapArtifactError):
        await dispatch.reserve(job_id=JOB, user_id=7, epoch=1, agent_key='codex')
    assert (await dispatch.state())['phase'] == 'available'
    await dispatch.close(first)
    connection = await dispatch.open(7, ('claude', 'codex'))
    assert execution_agents(await dispatch.state()) == ('claude', 'codex')
    outcomes = await asyncio.gather(*[
        dispatch.reserve(job_id=str(uuid4()), user_id=7, epoch=1, agent_key=key) for key in ('claude', 'codex')
    ], return_exceptions=True)
    assert sum(not isinstance(value, Exception) for value in outcomes) == 1
    await dispatch.close(connection)
    successor = await dispatch.open(7, 'codex')
    await dispatch.close(connection)
    assert not await dispatch.available(7, 'claude') and await dispatch.available(7, 'codex')
    binding = await dispatch.reserve(job_id=JOB, user_id=7, epoch=1, agent_key='codex')
    assert binding.agent_key == 'codex' and binding.connection_id == successor


@pytest.mark.asyncio
async def test_actual_route_codex_driver_dispatch_and_gateway_use_selected_agent(
    endpoint, redis, authorized, device_client, monkeypatch,
):
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_codex_enabled', True)
    authorized.job.agent_key = 'device_codex'
    module = importlib.import_module('mindmap_agent_bridge.codex_driver')
    monkeypatch.setattr(module, 'bundled_binary', lambda: sys.executable)
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-offline-test-credential')
    driver = module.CodexRunDriver()
    start = driver.owner.start
    source = Path(__file__).resolve().parents[2] / 'mindmap-agent-bridge/tests/fixtures/codex_driver_mock.py'
    async def launch(argv, **kwargs):
        return await start([argv[0], '-I', str(source), *argv[1:]], **kwargs)
    monkeypatch.setattr(driver.owner, 'start', launch)
    unused = SimpleNamespace(run=AsyncMock(side_effect=AssertionError('must not run Claude')), stop=AsyncMock())
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
    run_context = context()
    run_context.metadata['modelRef'] = 'gpt-5.6-terra'
    async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET},
                       proxy=None, max_size=8 * 1024 * 1024) as ws:
        client = asyncio.create_task(device_client.connected_execution(ws, {'claude': unused, 'codex': driver},
                                     agent_keys=('claude', 'codex'), accept_estimated_budget=True))
        try:
            await wait_available(redis, 'codex')
            request = MindmapAiJobCreateModel(agentKey='device_codex', deviceId=DEVICE, prompt='任务')
            await execution.validate_device_selection(object(), request, 7, redis)
            result = await asyncio.wait_for(execution.execute_device_job(
                run_context, emit, redis=redis, device_id=DEVICE, epoch=1, owns_lease=AsyncMock(return_value=True),
                adapter_agent_key='device_codex',
            ), 10)
            assert await asyncio.wait_for(client, 3) == 'completed'
        finally:
            client.cancel()
            await asyncio.gather(client, return_exceptions=True)
            await driver.stop()
    assert result.summary['nodeCount'] == 3
    assert result.artifact['manifest']['generator']['agentKey'] == 'device_codex'
    assert sum(kind == 'draft_changed' for kind, _ in events) == 2
    assert sum(kind == 'todo_updated' for kind, _ in events) == 2
    assert sum(kind == 'tool_completed' for kind, _ in events) == 6
    unused.run.assert_not_awaited()
    assert not driver.owner._alive() and not Path(driver._directory).exists()
    assert not await DeviceDispatch(redis, DEVICE).state()
    assert 'sk-offline' not in json.dumps(events) and 'never-forward-platform-secret' not in json.dumps(events)


def handoff_driver(key, monkeypatch, tmp_path):
    """Real driver/process ownership; protocol peers only, never user login."""
    fixtures = Path(__file__).resolve().parents[2] / 'mindmap-agent-bridge/tests/fixtures'
    module = importlib.import_module(f'mindmap_agent_bridge.{key}_driver')
    if key == 'claude':
        binary = tmp_path / 'claude'
        shutil.copyfile(fixtures / 'claude_mock.py', binary)
        shutil.copyfile(fixtures / 'handoff_scenario.py', tmp_path / 'handoff_scenario.py')
        binary.chmod(0o700)
        monkeypatch.setattr(module, 'resolve_binary', lambda _name: str(binary))
        monkeypatch.setattr(module, 'local_environment', lambda: {
            'PATH': os.environ['PATH'], 'LANG': 'en_US.UTF-8', 'ANTHROPIC_API_KEY': 'offline-only',
            'ANTHROPIC_BASE_URL': 'http://127.0.0.1:1', 'PYTHONNOUSERSITE': '1',
        })
        return module.ClaudeRunDriver()
    if key == 'codex':
        monkeypatch.setattr(module, 'bundled_binary', lambda: sys.executable)
        monkeypatch.setenv('OPENAI_API_KEY', 'sk-offline-test-credential')
        driver = module.CodexRunDriver()
        start = driver.owner.start
        async def launch(argv, **kwargs):
            return await start([argv[0], '-I', str(fixtures / 'codex_driver_mock.py'), *argv[1:]], **kwargs)
        monkeypatch.setattr(driver.owner, 'start', launch)
        return driver
    monkeypatch.setattr(module, 'local_command', lambda: ([sys.executable, '-I', str(fixtures / 'kimi_driver_mock.py')], None))
    monkeypatch.setattr(module, 'stage_local_auth', lambda _env: {
        'type': 'kimi', 'api_key': 'offline-only', 'base_url': 'http://127.0.0.1:1/v1'})
    return module.KimiRunDriver(accept_unmetered_budget=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('previous,next_agent', [
    ('claude', 'codex'), ('claude', 'kimi'), ('codex', 'claude'),
    ('codex', 'kimi'), ('kimi', 'claude'), ('kimi', 'codex'),
])
async def test_cross_protocol_partial_edit_stop_then_explicit_handoff(
    endpoint, redis, authorized, device_client, monkeypatch, tmp_path, previous, next_agent,
):
    """Route/Redis/real drivers/SDK/tools/history, with SQL and models simulated.

    The captured accepted projection stands for the platform-owned checkpoint;
    this does not claim to test SQL document commits or browser reconciliation.
    """
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_codex_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_kimi_enabled', True)
    document = {'root': {'data': {'uid': 'root', 'text': '接力验收'}, 'children': [
        {'data': {'uid': 'original', 'text': '人工已有内容'}, 'children': []},
    ]}, 'layout': 'logicalStructure', 'theme': {'template': 'default'}}
    records, histories, events, projections = {}, {}, {}, []
    first_id, second_id = str(uuid4()), str(uuid4())
    monkeypatch.setattr(execution.MindmapAiDao, 'get_job', AsyncMock(side_effect=lambda _db, identifier, _user: records.get(identifier)))
    monkeypatch.setattr(execution.MindmapAiDao, 'get_latest_plan_payload',
                        AsyncMock(side_effect=lambda _db, identifier, _user: histories.get(identifier)))
    monkeypatch.setattr(execution.MindmapAiDao, 'list_visible_reply_payloads', AsyncMock(
        side_effect=lambda _db, identifier, _user: [json.dumps(payload) for kind, payload in
                                                  reversed(events.get(identifier, [])) if kind == 'assistant_delta']))
    dispatch = DeviceDispatch(redis, DEVICE)
    old_binding = None
    for index, key in enumerate((previous, next_agent)):
        identifier = first_id if index == 0 else second_id
        request = MindmapAiJobCreateModel(agentKey=f'device_{key}', deviceId=DEVICE, intent='expand',
            prompt='handoff-stop' if index == 0 else 'handoff-continue', executionMode='direct', target='file',
            source={'type': 'cloud_document', 'mindmapId': 130, 'document': deepcopy(document),
                    'revision': index + 1, 'roomEpoch': 'same-document-lineage', 'scope': {'type': 'document'}})
        row = SimpleNamespace(id=identifier, user_id=7, session_id='session', agent_key=f'device_{key}',
            execution_epoch=1, status='running', request_json=request.model_dump_json(by_alias=True),
            source_mindmap_id=130, expires_time=datetime.now() + timedelta(hours=1),
            retry_of_job_id=first_id if index else None)
        records[identifier] = row
        history = await MindmapAiTaskManager._editing_continuation_history(object(), row, request)
        if index:
            assert history[-1]['agentKey'] == f'device_{previous}'
            assert history[-1]['status'] == 'cancelled'
            assert history[-1]['agentPlan'][0]['content'] == '未完成的接续事项'
        run_context = AgentRunContext(job_id=identifier, user_id=7, intent='expand', prompt=request.prompt,
            parameters={}, source_document=deepcopy(document),
            tool_service=MindmapToolService(base_document=document, trusted_source=True, intent='expand'),
            execution_mode='direct', continuation_history=history,
            metadata={'timeoutSeconds': 30, 'maxBudgetUsd': 0.05,
                      'modelRef': {'claude': 'sonnet', 'codex': 'gpt-5.6-terra', 'kimi': 'kimi-for-coding'}[key],
                      'credentialEnv': {'API_KEY': 'never-forward-platform-secret'},
                      'providerSessionId': 'private-provider-session', 'hiddenThinking': 'hidden-handoff-thinking'})
        events[identifier] = []
        edited = asyncio.Event()
        async def emit(kind, payload):
            events[identifier].append((kind, deepcopy(payload)))
            if kind == 'todo_updated':
                histories[identifier] = json.dumps(payload)
            if kind == 'draft_changed':
                projections.append(deepcopy(run_context.tool_service.read_projection()))
            if kind == 'tool_completed' and payload['toolName'] == 'add_nodes':
                edited.set()
        driver = handoff_driver(key, monkeypatch, tmp_path)
        unused = SimpleNamespace(run=AsyncMock(side_effect=AssertionError('unselected Agent ran')), stop=AsyncMock())
        async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET},
                           proxy=None, max_size=8 * 1024 * 1024) as ws:
            client = asyncio.create_task(device_client.connected_execution(ws,
                {agent: driver if agent == key else unused for agent in ('claude', 'codex', 'kimi')},
                agent_keys=('claude', 'codex', 'kimi'), accept_estimated_budget=True, accept_unmetered_budget=True))
            worker = None
            try:
                await wait_available(redis, key)
                if old_binding:
                    # A retired stream cannot poison the next idle connection.
                    with pytest.raises(MindmapArtifactError):
                        await DispatchedRunConnection(dispatch, old_binding).send('late old tool')
                    await dispatch.close(old_binding.connection_id)
                    assert await dispatch.available(7, key)
                worker = asyncio.create_task(execution.execute_device_job(run_context, emit, redis=redis,
                    device_id=DEVICE, epoch=1, owns_lease=AsyncMock(return_value=True), adapter_agent_key=f'device_{key}'))
                await asyncio.wait_for(edited.wait(), 12)
                if index == 0:
                    old_binding = DeviceRunBinding(**json.loads((await dispatch.state())['binding']))
                    with pytest.raises(MindmapArtifactError):
                        await dispatch.reserve(job_id=second_id, user_id=7, epoch=1, agent_key=next_agent)
                    worker.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(worker, 8)
                    assert await asyncio.wait_for(client, 3) == 'stopped'
                    row.status = 'cancelled'
                else:
                    outcome = await asyncio.wait_for(worker, 8)
                    assert isinstance(outcome, AgentDirectResult) and outcome.summary['nodeCount'] == 4
                    assert await asyncio.wait_for(client, 3) == 'completed'
                assert driver.owner.process.returncode is not None and not driver.owner._alive()
                assert not Path(driver._directory).exists()
                unused.run.assert_not_awaited()
                assert not await dispatch.state()
            finally:
                pending = [task for task in (worker, client) if task is not None]
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                await driver.stop()
        assert sum(kind == 'draft_changed' for kind, _ in events[identifier]) == 1
        document = projections[-1]
    assert [node['data']['text'] for node in document['root']['children']] == [
        '人工已有内容', '上一轮已确认部分', '下一位完成剩余部分',
    ]
    assert len(projections) == 2
    assert sum(kind == 'todo_updated' for kind, _ in events[first_id]) == 1
    assert sum(kind == 'todo_updated' for kind, _ in events[second_id]) == 2
    assert all('never-forward' not in json.dumps(turn) and 'private-provider-session' not in json.dumps(turn)
               and 'hidden-handoff-thinking' not in json.dumps(turn) for turn in events.values())


@asynccontextmanager
async def kimi_loopback_provider(*, pause=None):
    """Only loopback synthetic responses; no real model, auth or business data."""
    app = FastAPI()
    requests = []
    root = None
    @app.post('/v1/chat/completions')
    async def respond(request: controller.Request):
        nonlocal root
        body = await request.json()
        requests.append(body)
        for item in body['messages']:
            if item.get('role') == 'tool':
                raw = item.get('content', '')
                # Kimi prefixes tool text with execution metadata. Find only
                # our known JSON result; do not infer a root from the prompt.
                for index, character in enumerate(raw):
                    if character != '{':
                        continue
                    try:
                        value, _ = json.JSONDecoder().raw_decode(raw[index:])
                        if isinstance(value, dict) and isinstance(value.get('result'), dict):
                            root = value['result'].get('rootUid') or root
                    except ValueError:
                        continue
        calls = [('update_plan', {'todos': [{'content': '建立订单脑图', 'status': 'in_progress'}]}),
                 ('start_document', {'title': '订单'}),
                 ('add_nodes', {'nodes': [{'parentUid': root, 'text': '支付'}, {'parentUid': root, 'text': '配送'}]}),
                 ('validate_draft', {}),
                 ('update_plan', {'todos': [{'content': '建立订单脑图', 'status': 'completed'}]}),
                 ('complete_artifact', {})]
        index = len(requests) - 1
        if pause is not None and index == pause.at:
            pause.entered.set()
            await pause.release.wait()
        delta = {'role': 'assistant', 'content': '正在建立订单脑图。' if index == 0 else None}
        if index < len(calls):
            name, arguments = calls[index]
            delta['tool_calls'] = [{'index': 0, 'id': f'call-{index}', 'type': 'function',
                'function': {'name': f'mcp__mindmap__{name}', 'arguments': json.dumps(arguments)}}]
        else:
            delta['content'] = json.dumps({'completionState': 'artifact_completed', 'title': '订单', 'questions': []})
        async def stream():
            chunk = {'id': f'completion-{index}', 'object': 'chat.completion.chunk', 'model': 'kimi-for-coding',
                     'created': 1, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
            yield 'data: ' + json.dumps(chunk) + '\n\n'
            chunk['choices'] = [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if index < len(calls) else 'stop'}]
            yield 'data: ' + json.dumps(chunk) + '\n\n'
            yield 'data: [DONE]\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream')
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
        yield f'http://127.0.0.1:{listener.getsockname()[1]}/v1', requests
    finally:
        if pause is not None:
            pause.release.set()
        server.should_exit = True
        await asyncio.wait_for(task, 4)
        listener.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
async def test_kimi_full_device_route_streaming_preview_and_original_tool_gateway(
    endpoint, redis, authorized, device_client, monkeypatch, native,
):
    bundle, node = os.environ.get('MINDMAP_KIMI_TEST_BUNDLE'), os.environ.get('MINDMAP_KIMI_TEST_NODE')
    if native and (not bundle or not node):
        pytest.skip('Opt-in requires a local pinned Kimi 2.1.1 bundle and Node')
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_kimi_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_codex_enabled', True)
    authorized.job.agent_key = 'device_kimi'
    module = importlib.import_module('mindmap_agent_bridge.kimi_driver')
    mock = Path(__file__).resolve().parents[2] / 'mindmap-agent-bridge/tests/fixtures/kimi_driver_mock.py'
    argv = [node, bundle] if native else [sys.executable, '-I', str(mock)]
    monkeypatch.setattr(module, 'local_command', lambda: (argv, str(Path(node).parent) if native else None))
    unused = SimpleNamespace(run=AsyncMock(side_effect=AssertionError('must not select another Agent')), stop=AsyncMock())
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
    run_context = context()
    run_context.metadata['modelRef'] = 'kimi-for-coding'
    async with kimi_loopback_provider() as (provider_url, requests):
        monkeypatch.setattr(module, 'stage_local_auth', lambda _env: {
            'type': 'kimi', 'api_key': 'fake-loopback-test-only', 'base_url': provider_url})
        driver = module.KimiRunDriver(accept_unmetered_budget=True)
        async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET},
                           proxy=None, max_size=8 * 1024 * 1024) as ws:
            client = asyncio.create_task(device_client.connected_execution(ws,
                {'claude': unused, 'codex': unused, 'kimi': driver}, agent_keys=('claude', 'codex', 'kimi'),
                accept_estimated_budget=True, accept_unmetered_budget=True))
            try:
                await wait_available(redis, 'kimi')
                await execution.validate_device_selection(object(), MindmapAiJobCreateModel(
                    agentKey='device_kimi', deviceId=DEVICE, prompt='任务'), 7, redis)
                result = await asyncio.wait_for(execution.execute_device_job(run_context, emit, redis=redis,
                    device_id=DEVICE, epoch=1, owns_lease=AsyncMock(return_value=True), adapter_agent_key='device_kimi'), 25)
                assert await asyncio.wait_for(client, 3) == 'completed'
            finally:
                client.cancel()
                await asyncio.gather(client, return_exceptions=True)
                await driver.stop()
        if native:
            assert len(requests) == 7
            assert all(tool['function']['name'].startswith('mcp__mindmap__')
                       for request in requests for tool in request.get('tools', []))
        else:
            assert not requests
    assert result.summary['nodeCount'] == 3
    assert result.artifact['manifest']['generator']['agentKey'] == 'device_kimi'
    assert sum(kind == 'draft_changed' for kind, _ in events) == 2
    assert sum(kind == 'todo_updated' for kind, _ in events) == 2
    assert sum(kind == 'tool_started' for kind, _ in events) == 6
    assert sum(kind == 'tool_completed' for kind, _ in events) == 6
    unused.run.assert_not_awaited()
    assert not driver.owner._alive() and not Path(driver._directory).exists()
    assert not await DeviceDispatch(redis, DEVICE).state()
    assert 'fake-loopback-test-only' not in json.dumps(events)
    assert 'never-forward-hidden-reasoning' not in json.dumps(events)
    assert 'never-forward-platform-secret' not in json.dumps(events)


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['cancel', 'disconnect'])
async def test_real_kimi_partial_preview_stop_and_disconnect_do_not_complete_or_replay(
    endpoint, redis, authorized, device_client, monkeypatch, ending,
):
    from module_mindmap.ai.adapters._fs_utils import AgentProcessCleanupError
    bundle, node = os.environ.get('MINDMAP_KIMI_TEST_BUNDLE'), os.environ.get('MINDMAP_KIMI_TEST_NODE')
    if not bundle or not node:
        pytest.skip('Opt-in requires a local pinned Kimi 2.1.1 bundle and Node')
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_kimi_enabled', True)
    authorized.job.agent_key = 'device_kimi'
    module = importlib.import_module('mindmap_agent_bridge.kimi_driver')
    monkeypatch.setattr(module, 'local_command', lambda: ([node, bundle], str(Path(node).parent)))
    pause = SimpleNamespace(at=2, entered=asyncio.Event(), release=asyncio.Event())
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
    run_context = context()
    run_context.metadata['modelRef'] = 'kimi-for-coding'
    async with kimi_loopback_provider(pause=pause) as (provider_url, requests):
        monkeypatch.setattr(module, 'stage_local_auth', lambda _env: {
            'type': 'kimi', 'api_key': 'fake-loopback-test-only', 'base_url': provider_url})
        driver = module.KimiRunDriver(accept_unmetered_budget=True)
        async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET},
                           proxy=None, max_size=8 * 1024 * 1024) as ws:
            client = asyncio.create_task(device_client.connected_execution(
                ws, {'kimi': driver}, agent_keys=('kimi',), accept_unmetered_budget=True))
            worker = None
            try:
                await wait_available(redis, 'kimi')
                worker = asyncio.create_task(execution.execute_device_job(
                    run_context, emit, redis=redis, device_id=DEVICE, epoch=1,
                    owns_lease=AsyncMock(return_value=True), adapter_agent_key='device_kimi'))
                # Pause the next model response AFTER plan + root were actually
                # acknowledged through the platform gateway and preview stream.
                await asyncio.wait_for(pause.entered.wait(), 15)
                assert len(requests) == 3
                assert sum(kind == 'draft_changed' for kind, _ in events) == 1
                assert sum(kind == 'tool_completed' for kind, _ in events) == 2
                if ending == 'cancel':
                    worker.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(worker, 8)
                    assert await asyncio.wait_for(client, 3) == 'stopped'
                else:
                    await ws.close()
                    # Local process cleanup succeeds, but the server did NOT
                    # receive its stop receipt. It must preserve uncertainty.
                    with pytest.raises(AgentProcessCleanupError):
                        await asyncio.wait_for(worker, 8)
                    with pytest.raises(device_client.RunProtocolError):
                        await asyncio.wait_for(client, 3)
                assert not driver.owner._alive()
                assert driver.owner.process.returncode is not None
                assert not Path(driver._directory).exists()
                assert not driver.gateway.accepting
                pause.release.set()
                assert len(requests) == 3  # no new model turn or reconnect/replay
                assert sum(kind == 'draft_changed' for kind, _ in events) == 1
                assert sum(kind == 'tool_started' for kind, _ in events) == 2
                assert not await DeviceDispatch(redis, DEVICE).state()
            finally:
                pause.release.set()
                pending = [task for task in (worker, client) if task is not None]
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                await driver.stop()
    assert 'fake-loopback-test-only' not in json.dumps(events)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['disabled', 'missing_consent', 'wrong_policy', 'legacy_version'])
async def test_kimi_route_rejects_execution_without_both_admin_and_local_consent(endpoint, redis, monkeypatch, case):
    from websockets.exceptions import ConnectionClosed
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_kimi_enabled', case != 'disabled')
    hello = {'type': 'execute_ready', 'protocolVersion': 3, 'agentKeys': ['kimi'],
             'codexBudgetPolicy': None, 'kimiBudgetPolicy': 'timeout_and_tool_limit'}
    if case == 'missing_consent':
        hello.pop('kimiBudgetPolicy')
    elif case == 'wrong_policy':
        hello['kimiBudgetPolicy'] = 'hard_cap'
    elif case == 'legacy_version':
        hello.pop('kimiBudgetPolicy')
        hello['protocolVersion'] = 2
    async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET}, proxy=None) as ws:
        await ws.send(json.dumps(hello))
        with pytest.raises(ConnectionClosed):
            await ws.recv()
    assert not await DeviceDispatch(redis, DEVICE).state()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['codex_disabled', 'missing_budget_consent', 'unknown_agent'])
async def test_codex_execution_hello_rejects_missing_explicit_authority(endpoint, redis, monkeypatch, case):
    from websockets.exceptions import ConnectionClosed
    hello = {'type': 'execute_ready', 'protocolVersion': 2, 'agentKeys': ['codex'],
             'codexBudgetPolicy': 'reported_usage_estimate'}
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_codex_enabled', case != 'codex_disabled')
    if case == 'missing_budget_consent':
        hello['codexBudgetPolicy'] = None
    if case == 'unknown_agent':
        hello['agentKeys'] = ['codex', 'kimi']
    async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET}, proxy=None) as ws:
        await ws.send(json.dumps(hello))
        with pytest.raises(ConnectionClosed):
            await ws.recv()
    assert not await DeviceDispatch(redis, DEVICE).state()


@pytest.mark.asyncio
@pytest.mark.parametrize('real_sdk', [False, True])
async def test_actual_route_dispatch_job_gateway_preserves_stream_and_generator(
    endpoint, redis, authorized, device_client, real_sdk, monkeypatch, tmp_path,
):
    driver = PreviewDriver()
    if real_sdk:
        pytest.importorskip('claude_agent_sdk')
        driver_module = importlib.import_module('mindmap_agent_bridge.claude_driver')
        source = Path(__file__).resolve().parents[2] / 'mindmap-agent-bridge/tests/fixtures/claude_mock.py'
        binary = tmp_path / 'claude'
        shutil.copyfile(source, binary)
        binary.chmod(0o700)
        monkeypatch.setattr(driver_module, 'resolve_binary', lambda _name: str(binary))
        driver = driver_module.ClaudeRunDriver()
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
    async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET},
                       proxy=None, max_size=8 * 1024 * 1024) as ws:
        client = asyncio.create_task(device_client.connected_execution(ws, driver))
        try:
            await wait_available(redis)
            result = await asyncio.wait_for(execution.execute_device_job(
                context(), emit, redis=redis, device_id=DEVICE, epoch=1, owns_lease=AsyncMock(return_value=True),
            ), 15)
            assert await asyncio.wait_for(client, 3) == 'completed'
        finally:
            client.cancel()
            await asyncio.gather(client, return_exceptions=True)
    assert result.summary['nodeCount'] == 2
    assert result.artifact['manifest']['generator']['agentKey'] == 'device_claude'
    assert sum(kind == 'draft_changed' for kind, _ in events) == 2
    assert sum(kind == 'todo_updated' for kind, _ in events) == 2
    assert 'never-forward-platform-secret' not in json.dumps(events)
    assert not await DeviceDispatch(redis, DEVICE).state()
    assert authorized.read.await_count > 5 and authorized.auth.await_count > 5


@pytest.mark.asyncio
async def test_actual_route_cancel_waits_for_stop_receipt(endpoint, redis, authorized, device_client):
    entered, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class SlowDriver:
        async def run(self, _offer, channel):
            await channel.thinking()
            entered.set()
            await asyncio.Future()
        async def stop(self):
            stopping.set()
            await release.wait()
    async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET}, proxy=None) as ws:
        client = asyncio.create_task(device_client.connected_execution(ws, SlowDriver()))
        await wait_available(redis)
        worker = asyncio.create_task(execution.execute_device_job(
            context(), AsyncMock(), redis=redis, device_id=DEVICE, epoch=1, owns_lease=AsyncMock(return_value=True),
        ))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            worker.cancel()
            await asyncio.wait_for(stopping.wait(), 3)
            assert not worker.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(worker, 4)
            assert await asyncio.wait_for(client, 3) == 'stopped'
        finally:
            release.set()
            for task in (worker, client):
                task.cancel()
            await asyncio.gather(worker, client, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['lease', 'recovery', 'user', 'epoch', 'device', 'cancel', 'permission'])
async def test_job_authority_fails_before_sending_any_prompt(redis, authorized, case):
    dispatch = DeviceDispatch(redis, DEVICE)
    await dispatch.open(7, 'claude')
    lease = AsyncMock(return_value=case != 'lease')
    if case == 'user':
        authorized.owned.return_value = False
    elif case == 'epoch':
        authorized.job.execution_epoch = 2
    elif case == 'device':
        authorized.job.request_json = json.dumps({'deviceId': str(uuid4())})
    elif case == 'cancel':
        authorized.job.status = 'cancel_requested'
    elif case == 'permission':
        authorized.read.side_effect = ServiceException(message='已撤销读取权限')
    with pytest.raises((MindmapArtifactError, ServiceException)):
        await execution.execute_device_job(context(), AsyncMock(), redis=redis, device_id=DEVICE,
                                           epoch=2 if case == 'recovery' else 1, owns_lease=lease)
    assert (await dispatch.state())['phase'] == 'available'


@pytest.mark.asyncio
async def test_device_selection_admission_and_switch_do_not_leak_targets(redis, authorized):
    request = MindmapAiJobCreateModel(agentKey='device_claude', deviceId=DEVICE, prompt='任务')
    with pytest.raises(ServiceException):
        await execution.validate_device_selection(object(), request, 7, redis)
    await DeviceDispatch(redis, DEVICE).open(7, 'claude')
    await execution.validate_device_selection(object(), request, 7, redis)
    payload = request.model_dump(by_alias=True)
    execution.merge_device_selection(payload, MindmapAiMessageModel(prompt='继续', agentKey='codex'), 'codex')
    assert 'deviceId' not in payload
    replacement = str(uuid4())
    execution.merge_device_selection(payload, MindmapAiMessageModel(prompt='继续', deviceId=replacement), 'device_claude')
    assert payload['deviceId'] == replacement
    execution.merge_device_selection(payload, MindmapAiMessageModel(prompt='继续'), 'device_claude', previous=request)
    assert payload['deviceId'] == DEVICE  # parent target, not the selected artifact's older device
    execution.merge_device_selection(payload, MindmapAiMessageModel(prompt='继续'), 'device_claude',
                                     previous=MindmapAiJobCreateModel(prompt='平台任务'))
    assert 'deviceId' not in payload  # switching in requires an explicit device
    with pytest.raises(ServiceException):
        await execution.validate_device_selection(object(), request.model_copy(update={'agent_key': 'codex'}), 7, redis)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['disabled', 'origin', 'wrong_token', 'wrong_agent'])
async def test_execution_requires_separate_flag_header_auth_and_explicit_agent(
    endpoint, redis, authorized, monkeypatch, case,
):
    from websockets.exceptions import ConnectionClosed, InvalidStatus
    headers = {'Authorization': 'Bearer ' + SECRET}
    if case == 'disabled':
        monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_execution_enabled', False)
    if case == 'origin':
        headers['Origin'] = 'https://untrusted.example'
    if case == 'wrong_token':
        authorized.auth.side_effect = HTTPException(401, 'invalid')
    with pytest.raises((ConnectionClosed, InvalidStatus)):
        async with connect(endpoint, additional_headers=headers, proxy=None) as ws:
            await ws.send(json.dumps({'type': 'execute_ready', 'protocolVersion': 1,
                                      'agentKey': 'codex' if case == 'wrong_agent' else 'claude'}))
            await ws.recv()
    assert not await DeviceDispatch(redis, DEVICE).state()
    if case in {'disabled', 'origin'}:
        authorized.auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_during_run_closes_socket_and_never_claims_confirmed_stop(
    endpoint, redis, authorized, device_client,
):
    from module_mindmap.ai.adapters._fs_utils import AgentProcessCleanupError
    entered = asyncio.Event()
    class RevokedDriver:
        stopped = False
        async def run(self, _offer, channel):
            await channel.public_text('处理中', message_id='m1')
            entered.set()
            authorized.auth.side_effect = HTTPException(401, 'revoked')
            # Next frame must be refused, and cannot reach the domain tools.
            await channel.tool('start_document', {'title': '撤销后不允许创建'})
        async def stop(self):
            self.stopped = True
    events, driver = [], RevokedDriver()
    async def emit(kind, payload):
        events.append((kind, payload))
    async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET}, proxy=None) as ws:
        client = asyncio.create_task(device_client.connected_execution(ws, driver))
        await wait_available(redis)
        worker = asyncio.create_task(execution.execute_device_job(
            context(), emit, redis=redis, device_id=DEVICE, epoch=1, owns_lease=AsyncMock(return_value=True),
        ))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            with pytest.raises(AgentProcessCleanupError):
                await asyncio.wait_for(worker, 7)
            with pytest.raises(device_client.RunProtocolError):
                await asyncio.wait_for(client, 3)
        finally:
            for task in (worker, client):
                task.cancel()
            await asyncio.gather(worker, client, return_exceptions=True)
    assert driver.stopped  # local cleanup succeeded, but its ACK couldn't reach server
    assert not any(kind in {'draft_changed', 'tool_started'} for kind, _ in events)


@pytest.mark.asyncio
@pytest.mark.parametrize('runtime_key', ['claude', 'codex', 'kimi'])
async def test_actual_task_manager_injects_owned_target_and_never_retries_device_provider_error(
    authorized, monkeypatch, redis, runtime_key,
):
    from module_mindmap.ai.adapters.device import DeviceClaudeAdapter, DeviceCodexAdapter, DeviceKimiAdapter
    from module_mindmap.service import mindmap_ai_service as service
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_codex_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_kimi_enabled', True)
    agent_key = f'device_{runtime_key}'
    model_ref = {'codex': 'gpt-5.6-terra', 'claude': 'sonnet', 'kimi': 'kimi-for-coding'}[runtime_key]
    manager = service.MindmapAiTaskManager
    job = SimpleNamespace(
        id=JOB, user_id=7, status='running', agent_key=agent_key, sdk_version='sdk', runtime_version=None,
        model_ref=model_ref, max_budget_usd=0.05, timeout_seconds=30, max_nodes=100, max_depth=10,
        retention_days=30, intent='discuss', target='message', parent_job_id=None, session_id='s',
        request_json=json.dumps({'agentKey': agent_key, 'deviceId': DEVICE, 'intent': 'discuss',
                                 'target': 'message', 'prompt': '分析订单流程'}),
    )
    monkeypatch.setattr(service, 'AsyncSessionLocal', fake_db)
    monkeypatch.setattr(service.MindmapAiDao, 'get_job', AsyncMock(return_value=job))
    adapter = {'codex': DeviceCodexAdapter, 'claude': DeviceClaudeAdapter, 'kimi': DeviceKimiAdapter}[runtime_key]()
    monkeypatch.setattr(service, 'get_mindmap_agent_registry', lambda: SimpleNamespace(get=lambda key: adapter))
    monkeypatch.setattr(service.MindmapAiService, '_ensure_connector_available', AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(manager, '_visible_discussion_history', AsyncMock(return_value=()))
    monkeypatch.setattr(manager, '_set_status', AsyncMock(return_value=True))
    monkeypatch.setattr(manager, '_owns_current_job_lease', AsyncMock(return_value=True))
    monkeypatch.setattr(manager, '_wake_waiting_followups', AsyncMock())
    execution_receipts = AsyncMock(return_value=True)
    monkeypatch.setattr(manager, '_record_execution_state', execution_receipts)
    monkeypatch.setattr(manager, '_redis', redis)
    fail = AsyncMock()
    monkeypatch.setattr(manager, '_fail', fail)
    async def run(context, emit, **runtime):
        assert runtime['device_id'] == DEVICE and runtime['epoch'] == 1 and runtime['redis'] is redis
        assert runtime['adapter_agent_key'] == agent_key
        assert await runtime['owns_lease']() is True
        assert context.metadata['modelRef'] == model_ref and context.metadata['maxBudgetUsd'] == 0.05
        raise MindmapArtifactError('限流', code='AI_RATE_LIMITED')
    executed = AsyncMock(side_effect=run)
    monkeypatch.setattr(service, 'execute_device_job', executed)
    retried = AsyncMock(side_effect=AssertionError('device tasks cannot be transparently retried'))
    monkeypatch.setattr(service, 'run_adapter_with_transient_retries', retried)
    lease = service._CURRENT_JOB_LEASE_TOKEN.set('test-owned-lease')
    epoch = service._CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        await manager._run_job(JOB)
    finally:
        service._CURRENT_JOB_LEASE_TOKEN.reset(lease)
        service._CURRENT_JOB_EXECUTION_EPOCH.reset(epoch)
    executed.assert_awaited_once()
    retried.assert_not_awaited()
    fail.assert_awaited_once_with(JOB, 'AI_RATE_LIMITED', '限流')
    assert [call.args for call in execution_receipts.await_args_list] == [(JOB, 'running'), (JOB, 'stopped')]
    assert not adapter._tasks


@pytest.mark.asyncio
async def test_lost_job_lease_cancels_and_confirms_stop_without_accepting_late_tool(
    endpoint, redis, authorized, device_client,
):
    lease = AsyncMock(return_value=True)
    class FencedDriver:
        stopped = False
        async def run(self, _offer, channel):
            await channel.public_text('处理中', message_id='m1')
            lease.return_value = False
            await channel.tool('start_document', {'title': '租约失效后不允许创建'})
        async def stop(self):
            self.stopped = True
    events, driver = [], FencedDriver()
    async def emit(kind, payload):
        events.append((kind, payload))
    async with connect(endpoint, additional_headers={'Authorization': 'Bearer ' + SECRET}, proxy=None) as ws:
        client = asyncio.create_task(device_client.connected_execution(ws, driver))
        await wait_available(redis)
        try:
            with pytest.raises(MindmapArtifactError) as error:
                await asyncio.wait_for(execution.execute_device_job(
                    context(), emit, redis=redis, device_id=DEVICE, epoch=1, owns_lease=lease,
                ), 7)
            assert error.value.code == 'AI_SANDBOX_VIOLATION'
            assert await asyncio.wait_for(client, 3) == 'stopped'
        finally:
            client.cancel()
            await asyncio.gather(client, return_exceptions=True)
    assert driver.stopped
    assert not any(kind in {'draft_changed', 'tool_started'} for kind, _ in events)
