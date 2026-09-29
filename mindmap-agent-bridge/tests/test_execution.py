"""Internal protocol tests: fake local driver, no CLI/model/document/credential."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from mindmap_agent_bridge import execution as run

IDENTITY = {'protocolVersion': 1, 'runId': '11111111-1111-4111-8111-111111111111', 'executionEpoch': 2}
OFFER = {**IDENTITY, 'type': 'run', 'agentKey': 'claude', 'intent': 'discuss', 'executionMode': 'preview',
         'prompt': '讨论测试', 'tools': []}
COMPLETION = {'completionState': 'message_completed', 'content': '测试内容'}


class Connection:
    def __init__(self, offer=OFFER):
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait(json.dumps(offer))
        self.sent = asyncio.Queue()
        self.frames = []
        self.auto_ack = True

    async def recv(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send(self, raw):
        value = json.loads(raw)
        self.frames.append(value)
        await self.sent.put(value)
        if self.auto_ack:
            await self.incoming.put(json.dumps({**IDENTITY, 'type': 'ack', 'sequence': value['sequence']}))


def driver():
    return type('Driver', (), {'run': AsyncMock(return_value=COMPLETION), 'stop': AsyncMock()})()


async def execute(connection, local_driver, **options):
    return await run.execute_run(connection, agent_key='claude', driver=local_driver,
                                 consent=AsyncMock(return_value=True), ack_timeout=0.1, **options)


@pytest.mark.parametrize('change', [
    {'agentKey': 'codex'}, {'protocolVersion': True}, {'executionEpoch': True}, {'runId': 'other'},
    {'executable': '/bin/sh'}, {'env': {'API_KEY': 'secret'}}, {'cwd': '/tmp'}, {'args': ['-c', 'anything']},
    {'prompt': []}, {'tools': [{'name': 'shell', 'description': 'shell', 'inputSchema': {}}]},
    {'tools': [{'name': 'read_projection', 'description': 'no tools in discussion', 'inputSchema': {}}]},
])
def test_offer_cannot_choose_another_local_agent_or_arbitrary_process(change):
    with pytest.raises(run.RunProtocolError) as error:
        run.decode_offer(json.dumps({**OFFER, **change}), agent_key='claude')
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('policy', [
    {'maxBudgetUsd': True, 'timeoutSeconds': 30, 'modelRef': 'sonnet'},
    {'maxBudgetUsd': 0, 'timeoutSeconds': 30, 'modelRef': 'sonnet'},
    {'maxBudgetUsd': 1001, 'timeoutSeconds': 30, 'modelRef': 'sonnet'},
    {'maxBudgetUsd': float('nan'), 'timeoutSeconds': 30, 'modelRef': 'sonnet'},
    {'maxBudgetUsd': 1, 'timeoutSeconds': True, 'modelRef': 'sonnet'},
    {'maxBudgetUsd': 1, 'timeoutSeconds': 901, 'modelRef': 'sonnet'},
    {'maxBudgetUsd': 1, 'timeoutSeconds': 30, 'modelRef': '--arbitrary-flag'},
    {'maxBudgetUsd': 1, 'timeoutSeconds': 30, 'modelRef': 'https://untrusted.example'},
    {'maxBudgetUsd': 1, 'timeoutSeconds': 30, 'modelRef': 'sonnet', 'apiKey': 'secret'},
])
def test_runtime_policy_is_closed_bounded_and_never_a_process_option_bag(policy):
    with pytest.raises(run.RunProtocolError):
        run.decode_offer(json.dumps({**OFFER, 'runtimePolicy': policy}), agent_key='claude')


def test_runtime_policy_preserves_exact_budget_timeout_and_model():
    decoded = run.decode_offer(json.dumps({**OFFER, 'runtimePolicy': {
        'maxBudgetUsd': 0.05, 'timeoutSeconds': 30, 'modelRef': 'sonnet',
    }}), agent_key='claude')
    assert (decoded.max_budget_usd, decoded.timeout_seconds, decoded.model_ref) == (0.05, 30, 'sonnet')


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', [False, 1, None])
async def test_local_consent_must_be_explicit_before_any_driver_work(answer):
    local_driver, connection = driver(), Connection()
    with pytest.raises(run.BridgeError, match='未同意'):
        await run.execute_run(connection, agent_key='claude', driver=local_driver,
                              consent=AsyncMock(return_value=answer))
    local_driver.run.assert_not_awaited()
    local_driver.stop.assert_not_awaited()
    assert connection.frames == []


@pytest.mark.asyncio
async def test_public_text_is_chunked_and_driver_stops_before_completion():
    local_driver, connection = driver(), Connection()
    async def work(_offer, channel):
        await channel.thinking()
        await channel.public_text('内容' * 2500, message_id='message-1')
        await channel.public_text('公开简述', message_id='summary-1', channel='thinking_summary')
        return COMPLETION
    async def stop():
        assert not any(frame['type'] == 'completed' for frame in connection.frames)
    local_driver.run.side_effect, local_driver.stop.side_effect = work, stop
    assert await execute(connection, local_driver) == 'completed'
    texts = [frame for frame in connection.frames if frame['type'] == 'public_text']
    assert [len(frame['text']) for frame in texts] == [4000, 1000, 4]
    assert connection.frames[-1]['processStopped'] is True
    local_driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_driver_diagnostics_are_not_uploaded_on_failure():
    local_driver, connection = driver(), Connection()
    local_driver.run.side_effect = RuntimeError('private provider secret')
    with pytest.raises(run.RunProtocolError):
        await execute(connection, local_driver)
    assert connection.frames[-1]['type'] == 'failed'
    assert connection.frames[-1]['processStopped'] is True
    assert 'private' not in json.dumps(connection.frames)
    local_driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_execution_timeout_reports_timeout_after_confirmed_cleanup():
    local_driver, connection = driver(), Connection()

    async def stalled(*_args):
        await asyncio.Event().wait()

    local_driver.run.side_effect = stalled
    with pytest.raises(run.RunFailure) as error:
        await execute(connection, local_driver, timeout=0.01)
    assert error.value.code == 'AI_TIMEOUT'
    assert connection.frames[-1] == {
        **IDENTITY, 'type': 'failed', 'sequence': 1,
        'processStopped': True, 'errorCode': 'AI_TIMEOUT',
    }
    local_driver.stop.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['AI_PROVIDER_AUTH_FAILED', 'AI_RATE_LIMITED',
                                 'AI_CAPABILITY_UNSUPPORTED', 'AI_BUDGET_EXCEEDED'])
async def test_safe_driver_error_code_reaches_platform_after_cleanup(code):
    local_driver, connection = driver(), Connection()
    local_driver.run.side_effect = run.RunFailure(code)
    with pytest.raises(run.RunFailure):
        await execute(connection, local_driver)
    assert connection.frames[-1]['errorCode'] == code
    assert connection.frames[-1]['processStopped'] is True
    local_driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_uncertain_cleanup_never_reports_normal_completion():
    local_driver, connection = driver(), Connection()
    local_driver.stop.side_effect = RuntimeError('private cleanup secret')
    with pytest.raises(run.RunCleanupError):
        await execute(connection, local_driver)
    assert connection.frames[-1]['type'] == 'failed'
    assert connection.frames[-1]['processStopped'] is False
    assert connection.frames[-1]['errorCode'] == 'AI_AGENT_CLEANUP_FAILED'
    assert 'private' not in json.dumps(connection.frames)


@pytest.mark.asyncio
async def test_stop_timeout_is_bounded_and_not_a_success():
    local_driver, connection = driver(), Connection()
    async def stuck_stop():
        await asyncio.Event().wait()
    local_driver.stop.side_effect = stuck_stop
    with pytest.raises(run.RunCleanupError):
        await asyncio.wait_for(execute(connection, local_driver, stop_timeout=0.01), 1)
    assert connection.frames[-1]['processStopped'] is False


@pytest.mark.asyncio
async def test_wrong_run_ack_stops_driver_without_retrying_work():
    local_driver, connection = driver(), Connection()
    connection.auto_ack = False
    async def work(_offer, channel):
        await channel.thinking()
        pytest.fail('A mismatched acknowledgement must never release the driver')
    local_driver.run.side_effect = work
    task = asyncio.create_task(execute(connection, local_driver))
    await asyncio.wait_for(connection.sent.get(), 1)
    await connection.incoming.put(json.dumps({**IDENTITY, 'runId': '22222222-2222-4222-8222-222222222222',
                                              'type': 'ack', 'sequence': 1}))
    with pytest.raises(run.RunProtocolError):
        await asyncio.wait_for(task, 1)
    local_driver.stop.assert_awaited_once()
    assert len(connection.frames) == 1


@pytest.mark.asyncio
async def test_remote_cancel_unblocks_pending_tool_and_ignores_its_late_ack():
    tool = {'name': 'read_projection', 'description': 'Read', 'inputSchema': {}}
    local_driver = driver()
    connection = Connection({**OFFER, 'intent': 'create', 'tools': [tool]})
    connection.auto_ack = False
    async def work(_offer, channel):
        await channel.tool('read_projection', {})
        pytest.fail('Cancelled tool must not release the driver')
    local_driver.run.side_effect = work
    task = asyncio.create_task(execute(connection, local_driver))
    assert (await asyncio.wait_for(connection.sent.get(), 1))['type'] == 'tool_call'
    await connection.incoming.put(json.dumps({**IDENTITY, 'type': 'cancel'}))
    stopped = await asyncio.wait_for(connection.sent.get(), 1)
    assert stopped['type'] == 'stopped' and stopped['processStopped'] is True
    await connection.incoming.put(json.dumps({**IDENTITY, 'type': 'ack', 'sequence': 1, 'toolResult': {}}))
    await connection.incoming.put(json.dumps({**IDENTITY, 'type': 'ack', 'sequence': stopped['sequence']}))
    assert await asyncio.wait_for(task, 1) == 'stopped'
    local_driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_parent_cancel_waits_for_cleanup_and_reports_failed_not_completed():
    local_driver, connection = driver(), Connection()
    started, stop_entered, release_stop = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def work(_offer, _channel):
        started.set()
        await asyncio.Event().wait()
    async def stop():
        stop_entered.set()
        await release_stop.wait()
    local_driver.run.side_effect, local_driver.stop.side_effect = work, stop
    task = asyncio.create_task(execute(connection, local_driver))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    await asyncio.wait_for(stop_entered.wait(), 1)
    task.cancel()
    assert not task.done()
    release_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert connection.frames[-1]['type'] == 'failed'
    assert connection.frames[-1]['processStopped'] is True
    local_driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_bounded_wait_preserves_cancel_when_operation_just_finished():
    entered = asyncio.Event()
    async def just_finished():
        entered.set()
        return 1
    task = asyncio.create_task(run._bounded(just_finished(), 1))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
