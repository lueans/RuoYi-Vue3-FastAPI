"""ACP transcript/security regressions; no CLI, credentials, DB or model calls."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from module_mindmap.ai import runtime_trace
from module_mindmap.ai.adapters.acp_transport import AcpSession
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.runtime_trace import RuntimeTrace


def tool(call_id='tool-1', *, initial=False, **fields):
    return {'sessionUpdate': 'tool_call' if initial else 'tool_call_update', 'toolCallId': call_id, **fields}


def test_partial_tools_keep_identity_name_inputs_and_result_until_a_single_terminal(monkeypatch):
    tick = [10.0]
    monkeypatch.setattr(runtime_trace.time, 'monotonic', lambda: tick[0])
    trace = RuntimeTrace()
    first = trace.acp(tool('private:/home/person/token', initial=True, title='ReadFile: private-path',
                           status='in_progress', rawInput={'limit': 10, 'apiKey': 'private-key'}))
    assert first[0][1]['callId'] == 'acp:tool-1'
    assert first[0][1]['toolName'] == 'ReadFile'
    assert 'private' not in json.dumps(first)
    # Identical frames do not flood the transcript, even after the rate floor.
    tick[0] += 1
    assert trace.acp(tool('private:/home/person/token', status='in_progress')) == []
    progress = trace.acp(tool('private:/home/person/token', rawInput={'offset': 2}, rawOutput={'found': 3}))
    assert len(progress) == 1
    assert json.loads(progress[0][1]['toolInput']) == {'limit': 10, 'apiKey': '[已隐藏]', 'offset': 2}
    tick[0] += 2
    terminal = trace.acp(tool('private:/home/person/token', status='completed'))
    assert terminal == [('tool_completed', {**progress[0][1], 'durationMs': 3000})]
    assert trace.acp(tool('private:/home/person/token', status='failed', rawOutput='late failure')) == []
    assert trace.acp(tool('private:/home/person/token', initial=True, status='in_progress')) == []


def test_throttled_progress_is_not_lost_at_status_only_completion(monkeypatch):
    monkeypatch.setattr(runtime_trace.time, 'monotonic', lambda: 1.0)
    trace = RuntimeTrace()
    trace.acp(tool(initial=True, title='Search', rawInput={'query': '订单'}))
    assert trace.acp(tool(rawInput={'page': 2}, content=[{'type': 'content', 'content': {'text': '支付'}}])) == []
    payload = trace.acp(tool(status='completed'))[0][1]
    assert '支付' in payload['toolOutput']
    assert json.loads(payload['toolInput']) == {'query': '订单', 'page': 2}


def test_gateway_calls_remain_hidden_across_nameless_updates_but_similar_names_do_not():
    trace = RuntimeTrace(acp_gateway_tools=('add_nodes',))
    assert trace.acp(tool(initial=True, title='mcp__mindmap__add_nodes', status='in_progress')) == []
    assert trace.acp(tool(status='completed', rawOutput={'private': 'gateway result'})) == []
    other = trace.acp(tool('other', initial=True, title='other__mindmap__add_nodes', status='in_progress'))
    assert other[0][1]['toolName'] == 'other__mindmap__add_nodes'
    disallowed = trace.acp(tool('not-in-this-mode', initial=True, title='mcp__mindmap__add_comment'))
    assert disallowed  # Not suppressed simply because a name contains "mindmap".


def test_thinking_tools_never_publish_arguments_results_or_adapter_ids():
    trace = RuntimeTrace()
    events = trace.acp(tool('private-id', initial=True, title='Think', kind='think',
                            rawInput={'text': 'private reasoning'}, content=['private content']))
    events += trace.acp(tool('private-id', status='completed', rawOutput='private output'))
    assert events == [('thinking_state', {'stage': 'thinking', 'visibility': 'status'})]


def test_late_thinking_classification_clears_the_live_row_once_without_publishing_new_content(monkeypatch):
    monkeypatch.setattr(runtime_trace.time, 'monotonic', lambda: 1.0)
    trace = RuntimeTrace()
    trace.acp(tool(initial=True, title='Tool'))
    events = trace.acp(tool(kind='think', rawInput='private reasoning', rawOutput='private output'))
    assert [kind for kind, _ in events] == ['thinking_state', 'tool_started']
    assert '[内容不展示]' in events[1][1]['toolInput']
    assert 'private' not in json.dumps(events)
    assert trace.acp(tool(status='in_progress')) == []
    ending = trace.acp(tool(status='completed', rawOutput='private output'))
    assert ending[0][0] == 'tool_completed'
    assert 'private' not in json.dumps(ending)


def test_acp_text_flushes_before_new_tools_and_partial_frames_do_not_reset_message_id(monkeypatch):
    monkeypatch.setattr(runtime_trace.time, 'monotonic', lambda: 0.0)
    trace = RuntimeTrace()
    assert trace.acp({'sessionUpdate': 'agent_message_chunk', 'content': {'text': '先检查'}}) == []
    events = trace.acp(tool(initial=True, title='Read'))
    assert [kind for kind, _ in events] == ['assistant_delta', 'tool_started']
    message_id = trace.message_id
    trace.acp(tool(rawInput={'path': 'test'}))
    trace.acp(tool(status='completed'))
    assert trace.message_id == message_id


@pytest.mark.parametrize('call_id', [None, '', ' ', True, [], 'x' * 513])
def test_invalid_tool_ids_do_not_fabricate_or_leak_tool_records(call_id):
    assert RuntimeTrace().acp(tool(call_id, initial=True, title='Read')) == []


def test_tool_state_is_bounded_without_evicting_terminal_tombstones(monkeypatch):
    monkeypatch.setattr(runtime_trace, 'MAX_ACP_TOOL_CALLS', 2)
    trace = RuntimeTrace()
    assert trace.acp(tool('one', initial=True, status='completed'))
    assert trace.acp(tool('two', initial=True))
    assert trace.acp(tool('three', initial=True)) == []
    assert trace.acp(tool('one', initial=True)) == []
    assert len(trace._acp_tools) == 2


class RpcPipe:
    def __init__(self, on_prompt=None, *, hello=None):
        self.reader = asyncio.StreamReader(limit=1024 * 1024 + 1)
        self.sent = []
        self.on_prompt = on_prompt
        self.prompt_request = None
        self.prompt_received = asyncio.Event()
        self.hello = hello or {'protocolVersion': 1, 'agentCapabilities': {'mcpCapabilities': {'http': True}}}

    def feed(self, message):
        self.reader.feed_data((json.dumps(message, ensure_ascii=False) + '\n').encode())

    def respond(self, request_id, result):
        self.feed({'jsonrpc': '2.0', 'id': request_id, 'result': result})

    def update(self, value, session_id='session-1'):
        self.feed({'jsonrpc': '2.0', 'method': 'session/update',
                   'params': {'sessionId': session_id, 'update': value}})

    def permission(self, request_id, *, title='mcp__mindmap__add_nodes', session_id='session-1',
                   call_id='tool-1', options=None):
        self.feed({'jsonrpc': '2.0', 'id': request_id, 'method': 'session/request_permission', 'params': {
            'sessionId': session_id, 'toolCall': {'toolCallId': call_id, 'title': title},
            'options': options if options is not None else [
                {'optionId': 'always', 'kind': 'allow_always'}, {'optionId': 'once', 'kind': 'allow_once'},
            ],
        }})

    def finish(self):
        self.respond(self.prompt_request['id'], {'stopReason': 'end_turn'})

    def write(self, data):
        request = json.loads(data)
        self.sent.append(request)
        if request.get('method') == 'initialize':
            self.respond(request['id'], self.hello)
        elif request.get('method') == 'session/new':
            self.respond(request['id'], {'sessionId': 'session-1'})
        elif request.get('method') == 'session/prompt':
            self.prompt_request = request
            self.prompt_received.set()
            if self.on_prompt:
                self.on_prompt(self)

    async def drain(self):
        pass


@asynccontextmanager
async def connected(on_prompt=None, *, allowed=('add_nodes',), hello=None):
    pipe = RpcPipe(on_prompt, hello=hello)
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    session = AcpSession(SimpleNamespace(stdin=pipe, stdout=pipe.reader), emit, allowed_tools=allowed)
    try:
        await session.start('/isolated-test', [{'type': 'http', 'name': 'mindmap', 'url': 'http://127.0.0.1/test'}])
        yield session, pipe, events
    finally:
        await session.close()


def outcomes(pipe):
    return [entry['result']['outcome'] for entry in pipe.sent if 'result' in entry]


@pytest.mark.asyncio
async def test_permission_is_scoped_to_registered_gateway_call_and_is_one_use_only():
    def stream(pipe):
        pipe.update(tool(initial=True, title='mcp__mindmap__add_nodes'))
        pipe.permission('wrong-session', session_id='other')
        pipe.permission('unknown-call', call_id='other')
        pipe.permission('accepted')
        pipe.permission('not-twice')
        pipe.finish()

    async with connected(stream) as (session, pipe, events):
        await session.prompt('test', 1)
        assert outcomes(pipe) == [
            {'outcome': 'cancelled'}, {'outcome': 'cancelled'},
            {'outcome': 'selected', 'optionId': 'once'}, {'outcome': 'cancelled'},
        ]
        assert events == []


@pytest.mark.asyncio
async def test_session_without_an_explicit_tool_allowlist_never_auto_approves():
    def stream(pipe):
        pipe.update(tool(initial=True, title='mcp__mindmap__add_nodes'))
        pipe.permission('permission')
        pipe.finish()

    async with connected(stream, allowed=()) as (session, pipe, _):
        await session.prompt('test', 1)
        assert outcomes(pipe) == [{'outcome': 'cancelled'}]


@pytest.mark.asyncio
@pytest.mark.parametrize('title', ['add_nodes', 'evil__mindmap__add_nodes', 'mcp__mindmap__add_comment', 'Bash'])
async def test_bare_suffix_unknown_and_shell_names_do_not_authorize_tools(title):
    def stream(pipe):
        pipe.update(tool(initial=True, title=title))
        pipe.permission('permission', title=title)
        pipe.finish()

    async with connected(stream) as (session, pipe, _):
        await session.prompt('test', 1)
        assert outcomes(pipe) == [{'outcome': 'cancelled'}]


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['no-start', 'terminal', 'renamed', 'orphan-update', 'think'])
async def test_tool_name_alone_or_relabeling_is_not_permission(scenario):
    def stream(pipe):
        if scenario != 'no-start':
            pipe.update(tool(initial=scenario != 'orphan-update', title=(
                'Read' if scenario == 'renamed' else 'mcp__mindmap__add_nodes'
            ), kind='think' if scenario == 'think' else 'other'))
        if scenario == 'terminal':
            pipe.update(tool(status='completed'))
        if scenario == 'renamed':
            pipe.update(tool(title='mcp__mindmap__add_nodes'))
        pipe.permission('permission')
        pipe.finish()

    async with connected(stream) as (session, pipe, _):
        await session.prompt('test', 1)
        assert outcomes(pipe) == [{'outcome': 'cancelled'}]


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [
    [], ['allow'], [{'optionId': True, 'kind': 'allow_once'}],
    [{'optionId': 'all', 'kind': 'allow_always'}],
    [{'optionId': 'same', 'kind': 'allow_once'}, {'optionId': 'same', 'kind': 'reject_once'}],
])
async def test_malformed_or_session_wide_permission_choices_fail_closed(options):
    def stream(pipe):
        pipe.update(tool(initial=True, title='mcp__mindmap__add_nodes'))
        pipe.permission('permission', options=options)
        pipe.finish()

    async with connected(stream) as (session, pipe, _):
        await session.prompt('test', 1)
        assert outcomes(pipe) == [{'outcome': 'cancelled'}]


@pytest.mark.asyncio
async def test_wrong_session_and_post_terminal_frames_cannot_publish_or_get_approved():
    def stream(pipe):
        pipe.update({'sessionUpdate': 'agent_message_chunk', 'content': {'text': 'other-data'}}, 'other')
        pipe.update(tool(initial=True, title='mcp__mindmap__add_nodes'))
        pipe.update({'sessionUpdate': 'agent_message_chunk', 'content': {'text': 'visible'}})
        pipe.finish()
        pipe.update({'sessionUpdate': 'agent_message_chunk', 'content': {'text': 'late-data'}})
        pipe.permission('late')

    async with connected(stream) as (session, pipe, events):
        await session.prompt('test', 1)
        assert session.text == 'visible'
        assert 'late-data' not in json.dumps(events) and 'other-data' not in json.dumps(events)
        assert outcomes(pipe) == [{'outcome': 'cancelled'}]


@pytest.mark.asyncio
async def test_cancel_closes_publication_and_permissions_before_cli_acknowledges():
    async with connected() as (session, pipe, events):
        task = asyncio.create_task(session.prompt('test', 1))
        await pipe.prompt_received.wait()
        await session.cancel()
        pipe.update(tool(initial=True, title='mcp__mindmap__add_nodes'))
        pipe.update({'sessionUpdate': 'agent_message_chunk', 'content': {'text': 'late-data'}})
        pipe.permission('after-cancel')
        pipe.finish()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == [] and session.text == ''
        assert outcomes(pipe) == [{'outcome': 'cancelled'}]
        with pytest.raises(MindmapArtifactError):
            await session.prompt('not a replay', 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [
    {'id': True, 'result': {}}, {'id': None, 'result': {}}, {'id': '3', 'result': {}},
    {'id': 999, 'result': {}}, {'id': 3, 'result': []}, {'id': 3},
    {'id': 3, 'error': []}, {'id': 3, 'error': {'code': True}},
    {'id': 3, 'result': {}, 'error': {'code': -1}}, {'id': 3, 'result': {'number': float('nan')}},
    {'method': 'session/update', 'params': []}, {'method': [], 'params': {}},
])
async def test_invalid_rpc_envelopes_fail_prompt_without_hanging(bad):
    def stream(pipe):
        pipe.feed({'jsonrpc': '2.0', **bad})

    async with connected(stream) as (session, pipe, _):
        with pytest.raises(MindmapArtifactError, match='实时协议无效'):
            await session.prompt('test', 1)
        with pytest.raises(MindmapArtifactError):
            await asyncio.wait_for(session.request('ping', {}), 0.1)
        assert len([item for item in pipe.sent if item.get('method') == 'session/prompt']) == 1


@pytest.mark.asyncio
async def test_repeated_reverse_rpc_ids_are_not_granted_twice():
    def stream(pipe):
        pipe.update(tool(initial=True, title='mcp__mindmap__add_nodes'))
        pipe.permission('duplicate')
        pipe.permission('duplicate')

    async with connected(stream) as (session, pipe, _):
        with pytest.raises(MindmapArtifactError):
            await session.prompt('test', 1)
        assert outcomes(pipe) == [{'outcome': 'selected', 'optionId': 'once'}]


@pytest.mark.asyncio
async def test_no_filesystem_terminal_or_arbitrary_reverse_rpc_capability_is_exposed():
    def stream(pipe):
        for index, method in enumerate(['fs/read_text_file', 'terminal/create', 'unknown']):
            pipe.feed({'jsonrpc': '2.0', 'id': f'reverse-{index}', 'method': method, 'params': {}})
        pipe.finish()

    async with connected(stream) as (session, pipe, _):
        await session.prompt('test', 1)
        assert pipe.sent[0]['params']['clientCapabilities'] == {}
        errors = [item['error']['code'] for item in pipe.sent if 'error' in item]
        assert errors == [-32601] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize('hello', [
    {'protocolVersion': True}, {'protocolVersion': 2},
    {'protocolVersion': 1, 'agentCapabilities': []},
    {'protocolVersion': 1, 'agentCapabilities': {'mcpCapabilities': {'http': 'true'}}},
])
async def test_protocol_and_http_mcp_capabilities_are_not_truthy_coercions(hello):
    with pytest.raises(MindmapArtifactError) as failure:
        async with connected(hello=hello):
            pass
    assert failure.value.code == 'AI_CAPABILITY_UNSUPPORTED'


@pytest.mark.asyncio
async def test_closed_reader_is_latched_and_cannot_send_a_new_request():
    async with connected() as (session, pipe, _):
        pipe.reader.feed_eof()
        await session._reader
        before = len(pipe.sent)
        with pytest.raises(MindmapArtifactError, match='连接已结束'):
            await asyncio.wait_for(session.request('ping', {}), 0.1)
        assert len(pipe.sent) == before


@pytest.mark.asyncio
async def test_prompt_success_does_not_invent_tool_completion():
    def stream(pipe):
        pipe.update(tool(initial=True, title='Search', status='in_progress'))
        pipe.finish()

    async with connected(stream) as (session, _, events):
        await session.prompt('test', 1)
        assert [kind for kind, _ in events] == ['tool_started']


@pytest.mark.asyncio
async def test_request_timeout_also_covers_blocked_stdin():
    async with connected() as (session, pipe, _):
        async def blocked_drain():
            await asyncio.Event().wait()

        pipe.drain = blocked_drain
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(session.prompt('test', 0.01), 0.5)
        assert not session._pending and not session._accept_updates
        assert not session._write_lock.locked()


@pytest.mark.asyncio
async def test_cancellation_during_event_delivery_stops_the_rest_of_the_frame(monkeypatch):
    monkeypatch.setattr(runtime_trace.time, 'monotonic', lambda: 0.0)

    def stream(pipe):
        pipe.update({'sessionUpdate': 'agent_message_chunk', 'content': {'text': 'before-cancel'}})
        pipe.update(tool(initial=True, title='Read'))  # flushes text then tries to publish tool
        pipe.finish()

    async with connected(stream) as (session, _, events):
        async def cancel_on_delivery(kind, payload):
            events.append((kind, payload))
            await session.cancel()

        session.emit = cancel_on_delivery
        with pytest.raises(asyncio.CancelledError):
            await session.prompt('test', 1)
        assert [kind for kind, _ in events] == ['assistant_delta']


def test_orphan_terminal_has_no_fabricated_duration():
    events = RuntimeTrace().acp(tool(status='completed', title='Read'))
    assert events[0][0] == 'tool_completed'
    assert 'durationMs' not in events[0][1]


def test_orphan_progress_is_retained_without_fabricating_a_tool_start():
    trace = RuntimeTrace()
    assert trace.acp(tool(title='Read', rawInput={'limit': 10}, rawOutput={'found': 2})) == []
    events = trace.acp(tool(status='completed'))
    assert events[0][0] == 'tool_completed'
    assert events[0][1]['toolName'] == 'Read'
    assert json.loads(events[0][1]['toolOutput']) == {'found': 2}
    assert 'durationMs' not in events[0][1]


def test_non_text_content_does_not_become_visible_prose_or_completion_contract():
    trace = RuntimeTrace()
    assert trace.acp({'sessionUpdate': 'agent_message_chunk', 'content': {
        'type': 'image', 'text': 'not a message', 'data': 'private-base64',
    }}) == []


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'posix', reason='Owned POSIX test process')
async def test_real_stdio_peer_and_real_mcp_gateway_keep_streaming_drafts_without_duplicate_tools(tmp_path):
    from module_mindmap.ai.adapters._fs_utils import spawn_owned_process, terminate_process
    from module_mindmap.ai.adapters.acp_transport import mindmap_http_mcp
    from module_mindmap.ai.adapters.base import AgentRunContext
    from module_mindmap.ai.adapters.codex import _CodexToolExecutionBridge
    from module_mindmap.ai.adapters.codex_worker import ALLOWED_TOOL_NAMES
    from module_mindmap.ai.adapters.kimi import completion_payload
    from module_mindmap.ai.tool_contract import MindmapToolService
    from module_mindmap.service.mindmap_ai_service import sanitize_mindmap_ai_event_payload

    events = []
    drafts = []

    async def emit(kind, payload):
        # Preview operations have their own validation/persistence path; they
        # deliberately do not pass through the chat detail field allowlist.
        if kind == 'draft_changed':
            drafts.append(payload)
        events.append((kind, sanitize_mindmap_ai_event_payload(payload)))

    context = AgentRunContext(job_id='fixture-job', user_id=1, intent='create', prompt='订单',
                              parameters={'layout': 'logicalStructure'}, source_document=None,
                              tool_service=MindmapToolService())
    bridge = _CodexToolExecutionBridge(context, emit, ALLOWED_TOOL_NAMES, agent_key='kimi',
                                      adapter_version='1.0.0', prompt_version='fixture')
    process = session = None
    try:
        async with mindmap_http_mcp(bridge, ALLOWED_TOOL_NAMES) as server:
            process = await spawn_owned_process(
                sys.executable, str(Path(__file__).parent / 'fixtures/mindmap_acp_worker.py'),
                cwd=str(tmp_path), env={'PATH': os.environ.get('PATH', '')},
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, limit=1024 * 1024 + 1,
            )
            session = AcpSession(process, emit, allowed_tools=ALLOWED_TOOL_NAMES)
            await session.start(str(tmp_path), [server])
            await session.prompt('fixture: create map', 5)
            await asyncio.wait_for(process.wait(), 3)
            assert process.returncode == 0, (await process.stderr.read()).decode()
            assert completion_payload(session.text)['completionState'] == 'artifact_completed'
            assert bridge.completed['artifact']['manifest']['generator']['agentKey'] == 'kimi'
        assert len(drafts) == 2 and drafts[-1]['operations']
        assert len([kind for kind, _ in events if kind == 'todo_updated']) == 2
        starts = [payload for kind, payload in events if kind == 'tool_started']
        ends = [payload for kind, payload in events if kind == 'tool_completed']
        assert len(starts) == len(ends) == 6
        assert {item['callId'] for item in starts} == {item['callId'] for item in ends}
        assert all(not item['callId'].startswith('acp:') for item in starts)
        rendered = json.dumps(events, ensure_ascii=False)
        assert 'fixture-private-reasoning' not in rendered
        public_text = ''.join(payload.get('text', '') for _, payload in events)
        assert '订单脑图已完成。' in public_text
        assert 'completionState' not in public_text and '```JSON' not in public_text
        assert 'fixture-tool-' not in rendered and server['url'] not in rendered
    finally:
        if process is not None:
            await terminate_process(process)
        if session is not None:
            await session.close()
