"""Local opt-in and transport-control isolation (no CLI or provider)."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mindmap_agent_bridge import cli, execution_client
from mindmap_agent_bridge.execution import RunCleanupError, RunFailure, RunProtocolError

IDENTITY = {'protocolVersion': 1, 'runId': '11111111-1111-4111-8111-111111111111', 'executionEpoch': 2}
OFFER = {**IDENTITY, 'type': 'run', 'agentKey': 'claude', 'intent': 'discuss',
         'executionMode': 'preview', 'prompt': 'offline test', 'tools': []}
FINISHED = {'type': 'relay_finished', 'protocolVersion': 1}
COMPLETION = {'completionState': 'message_completed', 'content': 'done'}


class ExecutionSocket:
    def __init__(self, offer=OFFER, *, agent_keys=('claude',), ack=True, ack_change=None, finished=FINISHED):
        self.incoming, self.frames = asyncio.Queue(), []
        self.offer, self.ack, self.ack_change, self.finished = offer, ack, ack_change, finished
        self.terminal_received = asyncio.Event()
        hello = execution_client.execution_handshake(agent_keys, 'codex' in agent_keys, 'kimi' in agent_keys)
        self.incoming.put_nowait(json.dumps({**hello, 'type': 'execute_welcome'}))
        if offer is not None:
            self.incoming.put_nowait(json.dumps(offer))

    async def recv(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send(self, raw):
        value = json.loads(raw)
        self.frames.append(value)
        if value['type'] in {'completed', 'failed', 'stopped'}:
            self.terminal_received.set()
            if self.ack:
                ack = {key: value[key] for key in (*IDENTITY, 'sequence')}
                self.incoming.put_nowait(json.dumps({**ack, 'type': 'ack', **(self.ack_change or {})}))
            if self.finished is not None:
                self.incoming.put_nowait(self.finished if isinstance(self.finished, Exception) else json.dumps(self.finished))


@pytest.mark.parametrize('enabled', [False, True])
def test_only_explicit_command_line_flag_enables_execution(monkeypatch, enabled):
    # Merely adding execution settings to a config file grants no authority.
    config = {'deviceId': 'local', 'execute': 'claude'}
    monkeypatch.setattr(cli, 'read_config', lambda _path: config)
    monkeypatch.setattr(cli.os, 'name', 'posix')
    discover = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(cli, 'run', discover)
    monkeypatch.setattr(execution_client, 'run_with_execution', execute)
    monkeypatch.setattr('sys.argv', ['mindmap-agent-bridge', 'run'] + (['--execute', 'claude'] if enabled else []))
    cli.main()
    if enabled:
        execute.assert_awaited_once_with(config, agent_keys=('claude',), accept_estimated_budget=False, accept_unmetered_budget=False)
    else:
        discover.assert_awaited_once_with(config)
    (discover if enabled else execute).assert_not_awaited()


@pytest.mark.parametrize('agent_keys', [('codex',), ('claude', 'codex')])
def test_codex_requires_explicit_local_budget_consent(agent_keys):
    with pytest.raises(execution_client.BridgeError, match='accept-estimated-budget'):
        execution_client.execution_handshake(agent_keys)
    hello = execution_client.execution_handshake(agent_keys, True)
    assert hello == {'type': 'execute_ready', 'protocolVersion': 2, 'agentKeys': list(agent_keys),
                     'codexBudgetPolicy': 'reported_usage_estimate'}


def test_cli_multiple_agents_are_explicit_and_never_loaded_from_config(monkeypatch):
    config = {'deviceId': 'local', 'execute': ['kimi'], 'acceptEstimatedBudget': False}
    monkeypatch.setattr(cli, 'read_config', lambda _path: config)
    execute = AsyncMock()
    monkeypatch.setattr(execution_client, 'run_with_execution', execute)
    monkeypatch.setattr('sys.argv', ['mindmap-agent-bridge', 'run', '--execute', 'claude',
                                   '--execute', 'codex', '--accept-estimated-budget'])
    cli.main()
    execute.assert_awaited_once_with(config, agent_keys=('claude', 'codex'), accept_estimated_budget=True, accept_unmetered_budget=False)


@pytest.mark.parametrize('keys', [('kimi',), ('claude', 'kimi'), ('claude', 'codex', 'kimi')])
def test_kimi_requires_separate_local_consent_and_version_three(keys):
    with pytest.raises(execution_client.BridgeError, match='accept-unmetered-budget'):
        execution_client.execution_handshake(keys, True)
    hello = execution_client.execution_handshake(keys, True, True)
    assert hello == {'type': 'execute_ready', 'protocolVersion': 3, 'agentKeys': list(keys),
                     'codexBudgetPolicy': 'reported_usage_estimate' if 'codex' in keys else None,
                     'kimiBudgetPolicy': 'timeout_and_tool_limit'}
    if 'codex' in keys:
        with pytest.raises(execution_client.BridgeError, match='accept-estimated-budget'):
            execution_client.execution_handshake(keys, False, True)


def test_kimi_cli_consent_is_explicit_not_loaded_from_pairing_config(monkeypatch):
    config = {'execute': ['kimi'], 'acceptUnmeteredBudget': True}
    monkeypatch.setattr(cli, 'read_config', lambda _path: config)
    execute = AsyncMock()
    monkeypatch.setattr(execution_client, 'run_with_execution', execute)
    monkeypatch.setattr('sys.argv', ['mindmap-agent-bridge', 'run', '--execute', 'kimi', '--accept-unmetered-budget'])
    cli.main()
    execute.assert_awaited_once_with(config, agent_keys=('kimi',), accept_estimated_budget=False, accept_unmetered_budget=True)
    execute.reset_mock()
    monkeypatch.setattr('sys.argv', ['mindmap-agent-bridge', 'run', '--execute', 'kimi'])
    cli.main()
    assert execute.await_args.kwargs['accept_unmetered_budget'] is False


@pytest.mark.asyncio
async def test_version_three_selects_only_kimi_and_requires_exact_consent_echo(monkeypatch):
    hello = execution_client.execution_handshake(('claude', 'codex', 'kimi'), True, True)
    socket = type('Socket', (), {'send': AsyncMock(), 'recv': AsyncMock(side_effect=[
        json.dumps({**hello, 'type': 'execute_welcome'}), '{"agentKey":"kimi"}',
        '{"type":"relay_finished","protocolVersion":1}',
    ])})()
    drivers = {key: object() for key in ('claude', 'codex', 'kimi')}
    execute = AsyncMock(return_value='completed')
    monkeypatch.setattr(execution_client, 'execute_run', execute)
    assert await execution_client.connected_execution(socket, drivers, agent_keys=tuple(drivers),
        accept_estimated_budget=True, accept_unmetered_budget=True) == 'completed'
    assert execute.await_args.kwargs['driver'] is drivers['kimi']
    assert execute.await_args.kwargs['agent_key'] == 'kimi'
    socket.recv = AsyncMock(return_value=json.dumps({**hello, 'type': 'execute_welcome', 'kimiBudgetPolicy': None}))
    execute.reset_mock()
    with pytest.raises(execution_client.RunProtocolError):
        await execution_client.connected_execution(socket, drivers, agent_keys=tuple(drivers),
            accept_estimated_budget=True, accept_unmetered_budget=True)
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('key', ['claude', 'codex', 'kimi'])
async def test_one_offer_selects_only_the_explicitly_enabled_local_driver(monkeypatch, key):
    hello = execution_client.execution_handshake(('claude', 'codex'), True)
    socket = type('Socket', (), {'send': AsyncMock(), 'recv': AsyncMock(side_effect=[
        json.dumps({**hello, 'type': 'execute_welcome'}), json.dumps({'agentKey': key}),
        '{"type":"relay_finished","protocolVersion":1}',
    ])})()
    drivers = {'claude': object(), 'codex': object()}
    execute = AsyncMock(return_value='completed')
    monkeypatch.setattr(execution_client, 'execute_run', execute)
    if key == 'kimi':
        with pytest.raises(execution_client.RunProtocolError):
            await execution_client.connected_execution(socket, drivers, agent_keys=('claude', 'codex'), accept_estimated_budget=True)
        execute.assert_not_awaited()
    else:
        assert await execution_client.connected_execution(socket, drivers, agent_keys=('claude', 'codex'), accept_estimated_budget=True) == 'completed'
        assert execute.await_args.kwargs['driver'] is drivers[key]
        assert execute.await_args.kwargs['agent_key'] == key
    assert json.loads(socket.send.await_args_list[0].args[0]) == hello


@pytest.mark.asyncio
async def test_terminal_ack_reader_cannot_consume_the_relay_finished_control_frame():
    socket = type('Socket', (), {'send': AsyncMock(), 'recv': AsyncMock(side_effect=[
        json.dumps({**IDENTITY, 'type': 'ack', 'sequence': 3}), json.dumps(FINISHED),
    ])})()
    connection = execution_client.OfferedConnection(socket, 'prefetched offer')
    assert await connection.recv() == 'prefetched offer'
    await connection.send(json.dumps({**IDENTITY, 'type': 'completed', 'sequence': 3, 'processStopped': True}))
    assert json.loads(await connection.recv())['type'] == 'ack'
    blocked = asyncio.create_task(connection.recv())
    await asyncio.sleep(0)
    assert not blocked.done()
    blocked.cancel()
    await asyncio.gather(blocked, return_exceptions=True)
    assert json.loads(await socket.recv())['type'] == 'relay_finished'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['AI_BUDGET_EXCEEDED', 'AI_PROVIDER_AUTH_FAILED', 'AI_TIMEOUT'])
async def test_confirmed_failure_keeps_bridge_online_for_a_new_selected_agent(monkeypatch, tmp_path, code):
    from mindmap_agent_bridge import run_recovery
    monkeypatch.setattr(run_recovery, 'run_root', lambda: tmp_path / 'runs')
    agents = ('claude', 'codex')
    next_offer = {**OFFER, 'agentKey': 'codex', 'runId': '22222222-2222-4222-8222-222222222222'}
    sockets = [ExecutionSocket(agent_keys=agents), ExecutionSocket(next_offer, agent_keys=agents),
               ExecutionSocket(None, agent_keys=agents)]
    opened, drivers, new_idle = [], [], asyncio.Event()

    @asynccontextmanager
    async def connect(*_args, **_kwargs):
        socket = sockets[len(opened)]
        opened.append(socket)
        if len(opened) == 3:
            new_idle.set()
        yield socket

    def local_drivers(*_args, **_kwargs):
        pair = {key: SimpleNamespace(run=AsyncMock(return_value=COMPLETION), stop=AsyncMock()) for key in agents}
        if not drivers:
            pair['claude'].run.side_effect = RunFailure(code)
        drivers.append(pair)
        return pair

    scan_stopped = asyncio.Event()
    async def scan(_config):
        try:
            await asyncio.Future()
        finally:
            scan_stopped.set()

    monkeypatch.setattr(execution_client, 'NoRedirectConnect', connect)
    monkeypatch.setattr(execution_client, 'local_drivers', local_drivers)
    monkeypatch.setattr(execution_client, 'run', scan)
    config = {'server': 'https://example.test', 'deviceId': IDENTITY['runId'], 'deviceSecret': 's' * 43}
    bridge = asyncio.create_task(execution_client.run_with_execution(
        config, agent_keys=agents, accept_estimated_budget=True))
    ready = asyncio.create_task(new_idle.wait())
    try:
        done, _ = await asyncio.wait({bridge, ready}, timeout=2, return_when=asyncio.FIRST_COMPLETED)
        if bridge in done:
            bridge.result()
        assert ready in done and not bridge.done() and not scan_stopped.is_set()
        assert sockets[0].frames[-1]['type'] == 'failed' and sockets[0].frames[-1]['processStopped'] is True
        assert sockets[1].frames[-1]['type'] == 'completed'
        assert sockets[0].incoming.empty() and sockets[1].incoming.empty()
        drivers[0]['claude'].run.assert_awaited_once()
        drivers[0]['codex'].run.assert_not_awaited()
        drivers[1]['claude'].run.assert_not_awaited()
        drivers[1]['codex'].run.assert_awaited_once()
        assert drivers[0]['claude'].run.await_args.args[0].run_id != drivers[1]['codex'].run.await_args.args[0].run_id
    finally:
        bridge.cancel()
        ready.cancel()
        await asyncio.gather(bridge, ready, return_exceptions=True)
    assert scan_stopped.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', [
    'missing_ack', 'wrong_sequence', 'wrong_run', 'wrong_epoch', 'boolean_sequence', 'extra_ack_field',
    'disconnected', 'invalid_finished', 'boolean_finished', 'cleanup_failed', 'protocol_failed',
])
async def test_unconfirmed_or_invalid_failure_never_returns_ready(monkeypatch, case):
    execute = execution_client.execute_run
    async def bounded_run(*args, **kwargs):
        return await execute(*args, **kwargs, ack_timeout=.02)
    monkeypatch.setattr(execution_client, 'execute_run', bounded_run)
    changes = {'wrong_sequence': {'sequence': 2}, 'wrong_run': {'runId': 'wrong-run'},
               'wrong_epoch': {'executionEpoch': 3}, 'boolean_sequence': {'sequence': True},
               'extra_ack_field': {'unexpected': True}}
    finished = {'disconnected': OSError('closed'), 'invalid_finished': {**FINISHED, 'unexpected': True},
                'boolean_finished': {**FINISHED, 'protocolVersion': True}}.get(case, FINISHED)
    socket = ExecutionSocket(ack=case != 'missing_ack', ack_change=changes.get(case), finished=finished)
    driver = SimpleNamespace(run=AsyncMock(side_effect=RunFailure('AI_BUDGET_EXCEEDED')), stop=AsyncMock())
    expected = RunProtocolError
    if case == 'cleanup_failed':
        driver.stop.side_effect = RuntimeError('process still alive')
        expected = RunCleanupError
    elif case == 'protocol_failed':
        driver.run.side_effect = RunProtocolError()
    elif case == 'disconnected':
        expected = OSError
    with pytest.raises(expected):
        await asyncio.wait_for(execution_client.connected_execution(socket, driver), 1)
    driver.run.assert_awaited_once()
    driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_external_cancel_after_failed_terminal_is_not_converted_to_ready():
    socket = ExecutionSocket(ack=False, finished=None)
    driver = SimpleNamespace(run=AsyncMock(side_effect=RunFailure('AI_BUDGET_EXCEEDED')), stop=AsyncMock())
    task = asyncio.create_task(execution_client.connected_execution(socket, driver))
    try:
        await asyncio.wait_for(socket.terminal_received.wait(), 1)
        task.cancel()
        terminal = socket.frames[-1]
        socket.incoming.put_nowait(json.dumps({**IDENTITY, 'type': 'ack', 'sequence': terminal['sequence']}))
        socket.incoming.put_nowait(json.dumps(FINISHED))
        with pytest.raises(asyncio.CancelledError):
            await task
        assert json.loads(socket.incoming.get_nowait()) == FINISHED
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal', [None, {'processStopped': False}, {'processStopped': True, 'errorCode': 'AI_TIMEOUT'}])
async def test_runfailure_without_matching_stopped_failure_evidence_is_not_swallowed(monkeypatch, terminal):
    socket = ExecutionSocket()
    async def unconfirmed_failure(connection, **_kwargs):
        await connection.recv()
        if terminal is not None:
            await connection.send(json.dumps({**IDENTITY, 'type': 'failed', 'sequence': 1,
                                              'errorCode': 'AI_BUDGET_EXCEEDED', **terminal}))
            await connection.recv()
        raise RunFailure('AI_BUDGET_EXCEEDED')
    monkeypatch.setattr(execution_client, 'execute_run', unconfirmed_failure)
    with pytest.raises(RunFailure):
        await execution_client.connected_execution(socket, object())
