"""Actual session implementation over controlled stdio frames; no model calls."""

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mindmap_agent_bridge.codex_session import CodexSession
from mindmap_agent_bridge.codex_trace import CodexTrace
from mindmap_agent_bridge.execution import MAX_OFFER_BYTES, RunFailure, RunOffer, RunProtocolError, RunStopped
from mindmap_agent_bridge.process_owner import OwnedProcess

BOUND = {'threadId': 'thread-private', 'turnId': 'turn-private'}
COMPLETION = {'completionState': 'artifact_completed', 'title': '测试脑图', 'questions': []}
OFFER = RunOffer('11111111-1111-4111-8111-111111111111', 1, 'codex', 'create', 'preview', '测试要求', (
    {'name': 'update_plan', 'description': '更新真实计划', 'inputSchema': {'type': 'object'}},
    {'name': 'add_nodes', 'description': '增加脑图节点', 'inputSchema': {'type': 'object'}},
    {'name': 'complete_artifact', 'description': '完成脑图', 'inputSchema': {'type': 'object'}},
))


def event(method, **params):
    return {'method': method, 'params': {**BOUND, **params}}


def message(text, *, phase='commentary', item_id='item-private', method='item/completed'):
    return event(method, item={'id': item_id, 'type': 'agentMessage', 'phase': phase, 'text': text})


def tool(request_id=100, call_id='call-private', **overrides):
    return {'id': request_id, 'method': 'item/tool/call', 'params': {
        **BOUND, 'callId': call_id, 'tool': 'mindmap_add_nodes', 'arguments': {'parentUid': 'root'}, **overrides,
    }}


def terminal(status='completed', **extra):
    return event('turn/completed', turn={'id': BOUND['turnId'], 'status': status, **extra})


def completed(value=COMPLETION):
    return [message(json.dumps(value, ensure_ascii=False), phase='final_answer', item_id='final-private'), terminal()]


class Harness:
    def __init__(self, frames, *, early=False):
        self.queue = asyncio.Queue()
        self.sent = []
        self.frames, self.early = frames, early
        self.channel = type('Channel', (), {
            'tool': AsyncMock(return_value={'ok': True, 'result': {'added': 1}}),
            'public_text': AsyncMock(), 'thinking': AsyncMock(),
        })()
        self.session = CodexSession(self.queue.get, self.send, cwd='/private/mindmap-test')

    async def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        method = value.get('method')
        if method == 'initialize':
            self.put({'id': value['id'], 'result': {'userAgent': 'mindmap-agent-bridge/0.141.0'}})
        elif method == 'thread/start':
            self.put({'id': value['id'], 'result': {'thread': {'id': BOUND['threadId']}}})
        elif method == 'turn/start':
            reply = {'id': value['id'], 'result': {'turn': {'id': BOUND['turnId'], 'status': 'inProgress'}}}
            for frame in ([*self.frames, reply] if self.early else [reply, *self.frames]):
                self.put(frame)

    def put(self, value):
        self.queue.put_nowait(json.dumps(value))

    async def run(self, offer=OFFER):
        return await asyncio.wait_for(self.session.run(offer, self.channel), 2)


@pytest.mark.asyncio
@pytest.mark.parametrize('early', [False, True])
async def test_real_protocol_lifecycle_dynamic_tools_and_public_stream(early):
    h = Harness([
        message('', method='item/started'), event('item/agentMessage/delta', itemId='item-private', delta='正在创建，'),
        message('正在创建，'), tool(tool='mindmap_update_plan', arguments={'todos': [{'content': '创建节点', 'status': 'in_progress'}]}),
        tool(101, 'call-2'), tool(102, 'call-3', tool='mindmap_complete_artifact'), *completed(),
    ], early=early)
    assert await h.run() == COMPLETION
    methods = [frame.get('method') for frame in h.sent if 'method' in frame]
    assert methods == ['initialize', 'initialized', 'thread/start', 'turn/start']
    thread = next(frame['params'] for frame in h.sent if frame.get('method') == 'thread/start')
    assert thread['approvalPolicy'] == 'never' and thread['sandbox'] == 'read-only' and thread['ephemeral'] is True
    assert [item['name'] for item in thread['dynamicTools']] == ['mindmap_update_plan', 'mindmap_add_nodes', 'mindmap_complete_artifact']
    assert all(item['type'] == 'function' for item in thread['dynamicTools'])
    assert [call.args[0] for call in h.channel.tool.await_args_list] == ['update_plan', 'add_nodes', 'complete_artifact']
    assert h.channel.public_text.await_args_list[0].args == ('正在创建，',)
    assert h.channel.public_text.await_count == 1
    assert 'private' not in str(h.channel.public_text.await_args_list)
    replies = [frame['result'] for frame in h.sent if 'result' in frame]
    assert len(replies) == 3 and all(reply['success'] for reply in replies)


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [
    {'tool': 'shell'}, {'tool': 'mindmap_remove_nodes'}, {'namespace': 'foreign'},
    {'threadId': 'another'}, {'turnId': 'another'}, {'arguments': []}, {'callId': ''},
])
async def test_unoffered_or_foreign_tool_requests_never_reach_gateway(overrides):
    h = Harness([tool(**overrides)])
    with pytest.raises(RunProtocolError):
        await h.run()
    h.channel.tool.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('second', [tool(), tool(101), tool(call_id='other-call')])
async def test_replayed_call_or_request_ids_cannot_repeat_a_mutation(second):
    h = Harness([tool(), second])
    with pytest.raises(RunProtocolError):
        await h.run()
    assert h.channel.tool.await_count == 1


@pytest.mark.asyncio
async def test_false_tool_result_is_reported_as_failure_not_fabricated_success():
    h = Harness([tool(), *completed()])
    h.channel.tool.return_value = {'ok': False, 'error': {'code': 'AI_SCOPE_VIOLATION'}}
    await h.run()
    reply = next(frame['result'] for frame in h.sent if 'result' in frame)
    assert reply['success'] is False
    assert json.loads(reply['contentItems'][0]['text'])['ok'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('frame', [
    {'id': 22, 'method': 'item/commandExecution/requestApproval', 'params': BOUND},
    event('item/started', item={'type': 'commandExecution', 'id': 'cmd'}),
    event('item/completed', item={'type': 'fileChange', 'id': 'patch'}),
    event('item/started', item={'type': 'mcpToolCall', 'id': 'mcp'}),
    {'id': 'unmatched', 'result': {}}, {'method': 3, 'params': {}},
])
async def test_unexpected_capabilities_and_responses_fail_closed(frame):
    h = Harness([frame])
    with pytest.raises(RunProtocolError):
        await h.run()
    h.channel.tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_notifications_cannot_publish_text_or_finish_this_turn():
    foreign_message = message('private-other-user')
    foreign_message['params']['threadId'] = 'foreign'
    foreign_done = terminal()
    foreign_done['params']['turn']['id'] = 'foreign'
    h = Harness([foreign_message, foreign_done, *completed()])
    assert await h.run() == COMPLETION
    h.channel.public_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('frames', [
    [terminal()], [message('not json', phase='final_answer')],
    completed({**COMPLETION, 'secret': 'private'}),
    [*completed()[:1], *completed()],
])
async def test_missing_invalid_or_duplicate_completion_is_rejected(frames):
    h = Harness(frames)
    with pytest.raises(RunProtocolError):
        await h.run()
    h.channel.public_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('code,expected', [('unauthorized', 'AI_PROVIDER_AUTH_FAILED'),
                                          ('usageLimitExceeded', 'AI_RATE_LIMITED'),
                                          ({'httpConnectionFailed': {'httpStatusCode': 500}}, 'AI_AGENT_UNAVAILABLE')])
async def test_errors_expose_only_fixed_public_codes(code, expected):
    h = Harness([terminal('failed', error={'codexErrorInfo': code, 'message': 'private-token private-prompt'})])
    with pytest.raises(RunFailure) as result:
        await h.run()
    assert result.value.code == expected
    assert 'private' not in str(result.value)


@pytest.mark.asyncio
async def test_interrupt_during_tool_reply_does_not_claim_process_exit_or_accept_more_work():
    h = Harness([tool(), tool(101, 'second'), *completed()])
    started, release = asyncio.Event(), asyncio.Event()
    async def blocked_tool(*_args):
        started.set()
        await release.wait()
        return {'ok': True}
    h.channel.tool.side_effect = blocked_tool
    task = asyncio.create_task(h.run())
    await asyncio.wait_for(started.wait(), 1)
    assert await h.session.interrupt() is True
    assert await h.session.interrupt() is False
    release.set()
    with pytest.raises(RunStopped):
        await task
    assert h.channel.tool.await_count == 1
    assert h.sent[-1]['method'] == 'turn/interrupt'
    assert h.sent[-1]['params'] == BOUND
    assert not any('processStopped' in frame or 'result' in frame for frame in h.sent)


@pytest.mark.asyncio
async def test_interrupt_while_waiting_cannot_apply_a_late_tool_call():
    h = Harness([])
    task = asyncio.create_task(h.run())
    while h.session.turn_id is None:
        await asyncio.sleep(0)
    await h.session.interrupt()
    h.put(tool())
    with pytest.raises(RunStopped):
        await task
    h.channel.tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_protocol_buffers_and_frames_are_bounded_and_sessions_are_single_use():
    h = Harness([event('unknown', text='x' * MAX_OFFER_BYTES)])
    with pytest.raises(RunProtocolError):
        await h.run()
    h = Harness([event('unknown') for _ in range(129)], early=True)
    with pytest.raises(RunProtocolError):
        await h.run()
    h = Harness(completed())
    await h.run()
    with pytest.raises(RunProtocolError):
        await h.run()


@pytest.mark.asyncio
async def test_discussion_has_no_tools_and_streams_only_public_content():
    result = {'completionState': 'message_completed', 'title': 'private-title', 'content': '公开讨论。', 'contentType': 'text/plain'}
    h = Harness(completed(result))
    assert await h.run(replace(OFFER, intent='discuss', tools=())) == result
    public = ''.join(call.args[0] for call in h.channel.public_text.await_args_list)
    assert public == '公开讨论。' and 'private' not in public
    h.channel.tool.assert_not_awaited()


def projected(frames, trace=None):
    trace = trace or CodexTrace()
    return [result for frame in frames for result in trace.consume(frame['method'], frame['params'])]


def test_public_summary_is_distinct_from_hidden_reasoning_and_redacts_split_secrets():
    frames = [event('item/reasoning/textDelta', itemId='reason-private', delta='hidden-chain-secret'),
              event('item/reasoning/textDelta', itemId='reason-private', delta='hidden-chain-secret'),
              event('item/reasoning/summaryTextDelta', itemId='reason-private', summaryIndex=0, delta='我会梳理 sk-abc'),
              event('item/reasoning/summaryTextDelta', itemId='reason-private', summaryIndex=0, delta='defghijklmnop 结构。'),
              event('item/completed', item={'id': 'reason-private', 'type': 'reasoning',
                                           'summary': ['我会梳理 sk-abcdefghijklmnop 结构。'], 'content': ['private-chain']})]
    result = projected(frames)
    assert [item for item in result if item['kind'] == 'thinking'] == [{'kind': 'thinking'}]
    text = ''.join(item.get('text', '') for item in result)
    assert text == '我会梳理 [已隐藏] 结构。'
    assert all(item['channel'] == 'thinking_summary' for item in result if item['kind'] == 'public_text')
    assert 'private' not in json.dumps(result) and 'hidden-chain' not in json.dumps(result)


def test_commentary_completion_before_deltas_never_duplicates_visible_text():
    result = projected([message('公开内容。'), event('item/agentMessage/delta', itemId='item-private', delta='公开内容。')])
    assert ''.join(item.get('text', '') for item in result) == '公开内容。'
    assert projected([event('item/agentMessage/delta', itemId='unknown', delta='not-yet-public。')]) == []


@pytest.mark.asyncio
async def test_read_timeout_has_fixed_public_error_and_expired_run_cannot_read_more():
    h = Harness([])
    with pytest.raises(RunFailure) as failure:
        await h.session._read(timeout=0.001)
    assert failure.value.code == 'AI_TIMEOUT'
    h.session._deadline = asyncio.get_running_loop().time() - 1
    h.put(tool())
    with pytest.raises(RunFailure) as failure:
        await h.session._read(timeout=None)
    assert failure.value.code == 'AI_TIMEOUT'
    assert h.queue.qsize() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupt', [False, True])
async def test_real_stdio_peer_and_owned_process_exit(tmp_path, interrupt):
    owner = OwnedProcess()
    process = await owner.start(
        [sys.executable, '-I', str(Path(__file__).with_name('fixtures') / 'codex_app_server_mock.py')],
        cwd=str(tmp_path), env={'PYTHONIOENCODING': 'utf-8'},
    )
    async def send(raw):
        process.stdin.write(raw.encode())
        await process.stdin.drain()
    session = CodexSession(process.stdout.readline, send, cwd=str(tmp_path))
    channel = Harness([]).channel
    offer = replace(OFFER, prompt='interrupt-test') if interrupt else OFFER
    task = asyncio.create_task(session.run(offer, channel))
    try:
        if interrupt:
            async def ready():
                while session.turn_id is None and not task.done():
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(ready(), 2)
            assert session.turn_id == 'mock-turn'
            await session.interrupt()
            with pytest.raises(RunStopped):
                await asyncio.wait_for(task, 2)
            assert process.returncode is None  # stop RPC is not exit evidence
            channel.tool.assert_not_awaited()
        else:
            result = await asyncio.wait_for(task, 2)
            assert result['title'] == '真实 stdio 测试'
            assert [call.args[0] for call in channel.tool.await_args_list] == ['update_plan', 'add_nodes', 'complete_artifact']
            await asyncio.wait_for(process.wait(), 2)
            assert process.returncode == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await owner.stop()
    assert not owner._alive()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get('MINDMAP_CODEX_SCHEMA_DIR'), reason='requires explicitly exported local CLI schemas')
async def test_requests_match_actual_cli_exported_experimental_schema():
    from jsonschema import Draft7Validator
    schema_root = Path(os.environ['MINDMAP_CODEX_SCHEMA_DIR'])
    paths = {'initialize': 'v1/InitializeParams.json', 'thread/start': 'v2/ThreadStartParams.json',
             'turn/start': 'v2/TurnStartParams.json'}
    h = Harness([tool(), *completed()])
    await h.run()
    checked = []
    for frame in h.sent:
        method = frame.get('method')
        if method in paths:
            Draft7Validator(json.loads((schema_root / paths[method]).read_text())).validate(frame['params'])
            checked.append(method)
        elif 'result' in frame:
            Draft7Validator(json.loads((schema_root / 'DynamicToolCallResponse.json').read_text())).validate(frame['result'])
            checked.append('tool-response')
    assert checked == ['initialize', 'thread/start', 'turn/start', 'tool-response']
