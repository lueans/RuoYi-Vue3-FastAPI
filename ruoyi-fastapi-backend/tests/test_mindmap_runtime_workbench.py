import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import openai_codex
import pytest

from module_mindmap.ai import runtime_catalog
from module_mindmap.ai.adapters import codex, codex_worker
from module_mindmap.ai.adapters.acp_transport import AcpSession, mindmap_http_mcp
from module_mindmap.ai.adapters.base import AgentRunContext
from module_mindmap.ai.adapters.codex import _CodexToolExecutionBridge
from module_mindmap.ai.adapters.codex_worker import ALLOWED_TOOL_NAMES
from module_mindmap.ai.adapters.kimi import completion_payload
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.runtime_trace import RuntimeTrace, detail_text, normalize_todos
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.service.mindmap_ai_service import sanitize_mindmap_ai_event_payload


def test_claude_partial_stream_deduplicates_final_and_never_exposes_hidden_thinking():
    trace = RuntimeTrace()
    events = []
    for event in [
        {'type': 'message_start', 'message': {'id': 'm1'}},
        {'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'private thoughts'}},
        {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '正在扩展'}},
        {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '订单分支'}},
        {'type': 'message_stop'},
    ]:
        events += trace.claude({'type': 'stream_event', 'event': event})
    events += trace.claude({'type': 'assistant', 'message': {'id': 'm1', 'content': [{'text': '正在扩展订单分支'}]}})
    assert ''.join(payload['text'] for kind, payload in events if kind == 'assistant_delta') == '正在扩展订单分支'
    assert 'private thoughts' not in json.dumps(events)
    assert any(kind == 'thinking_state' for kind, _ in events)


def test_codex_trace_handles_aliases_plans_and_completion_without_duplicates():
    trace = RuntimeTrace()
    events = trace.codex('item/agentMessage/delta', {'itemId': 'i1', 'delta': '分析结构'})
    events += trace.codex('item/completed', {'item': {'id': 'i1', 'type': 'agentMessage', 'text': '分析结构'}})
    events += trace.codex('turn/plan/updated', {'plan': [{'step': '检查脑图', 'status': 'completed'}]})
    assert ''.join(payload['text'] for kind, payload in events if kind == 'assistant_delta') == '分析结构'
    assert events[-1][1]['todos'][0]['content'] == '检查脑图'
    assert (
        trace.codex('item/agentMessage/delta', {'itemId': 'final', 'delta': '{"completionState":"artifact_completed"}'})
        == []
    )


def test_runtime_payload_survives_persistence_bounded_and_redacted():
    payload = sanitize_mindmap_ai_event_payload(
        {
            'text': 'x' * 5000,
            'messageId': 'm1',
            'rawEnvelope': 'drop',
            'toolInput': detail_text({'apiKey': 'private', 'nodes': [{'text': '订单'}], 'artifact': {'private': 1}}),
            'todos': [{'content': '任务', 'status': 'in_progress'}],
        }
    )
    assert len(payload['text']) == 4000
    assert 'rawEnvelope' not in payload
    assert 'private' not in payload['toolInput']
    assert payload['todos'][0]['status'] == 'in_progress'


@pytest.mark.parametrize('status', [[], {}, ['completed'], {'value': 'completed'}, None, True, 1])
def test_malformed_plan_status_does_not_break_trace_or_persisted_event_projection(status: Any) -> None:
    raw = {'todos': [{'content': '检查脑图', 'status': status}]}
    expected = [{'id': '1', 'content': '检查脑图', 'status': 'pending'}]
    assert normalize_todos(raw['todos']) == expected
    assert sanitize_mindmap_ai_event_payload(raw)['todos'] == expected
    trace = RuntimeTrace()
    assert trace.codex('turn/plan/updated', {'plan': raw['todos']}) == [
        ('todo_updated', {'todos': expected, 'origin': 'agent'}),
    ]


def test_created_count_survives_public_detail_truncation_without_changing_draft_deltas():
    tools = MindmapToolService()
    root = tools.start_document('登录场景')['rootUid']
    count = 50
    result = tools.add_nodes([{'parentUid': root, 'text': f'场景 {index}'} for index in range(count)])
    payload = sanitize_mindmap_ai_event_payload({'toolOutput': detail_text(result)})
    public_result = json.loads(payload['toolOutput'])
    assert result['createdCount'] == len(result['created']) == count
    assert public_result['createdCount'] == count
    assert len(public_result['created']) < count
    delta = tools.build_stream_delta(after_cursor=0, tool_name='add_nodes')
    assert len(delta['operations']) == count
    assert tools.operation_cursor() == count


def test_node_navigation_receipts_report_actual_unique_targets_without_changing_operation_counts():
    tools = MindmapToolService()
    root = tools.start_document('导航回执')['rootUid']
    children = tools.add_nodes([{'parentUid': root, 'text': f'节点 {index}'} for index in range(20)])['created']
    uids = [item['nodeUid'] for item in children]
    updated = tools.update_nodes([
        {'nodeUid': node_uid, 'patch': {'text': '已更新'}} for node_uid in [*uids, uids[0]]
    ])
    assert updated == {'updated': 21, 'nodeUids': uids}
    public = json.loads(sanitize_mindmap_ai_event_payload({'toolOutput': detail_text(updated)})['toolOutput'])
    assert public == {'updated': 21, 'nodeUids': uids[:12]}
    assert tools.edit_node_text(uids[0], '独立编辑')['nodeUids'] == [uids[0]]
    moved = tools.move_nodes([
        {'nodeUid': uids[1], 'parentUid': uids[0]},
        {'nodeUid': uids[1], 'parentUid': root},
    ])
    assert moved == {'moved': 2, 'nodeUids': [uids[1]]}
    assert tools.operation_cursor() == 44


def test_failed_node_update_has_no_success_receipt_or_partial_draft_write():
    tools = MindmapToolService()
    root = tools.start_document('导航回执')['rootUid']
    cursor = tools.operation_cursor()
    with pytest.raises(MindmapArtifactError):
        tools.update_nodes([
            {'nodeUid': root, 'patch': {'text': '不能部分提交'}},
            {'nodeUid': 'missing', 'patch': {'text': '不存在'}},
        ])
    assert tools.operation_cursor() == cursor
    assert tools.read_projection()['root']['data']['text'] == '导航回执'


def test_discussion_streams_content_from_partial_json_without_raw_envelope():
    trace = RuntimeTrace(structured_message=True)
    events = []
    for fragment in [
        '{"completionState":"message_completed","content":"你',
        '好\\n世界\\u4f',
        '60","title":null,"contentType":"text/plain"}',
    ]:
        events += trace.text(fragment)
    events += trace.flush()
    assert ''.join(payload['text'] for _, payload in events) == '你好\n世界你'
    assert 'completionState' not in json.dumps(events)


@pytest.mark.asyncio
async def test_scanner_refresh_detects_new_install_without_returning_paths(monkeypatch):
    installed = False
    monkeypatch.setattr(runtime_catalog, 'resolve_cli', lambda _: '/private/bin/agent' if installed else None)

    async def probe(_path, args):
        return 'agent 1.2.3' if args == ['--version'] else '--include-partial-messages --session-mirror acp'

    monkeypatch.setattr(runtime_catalog, '_probe', probe)
    first = await runtime_catalog.discover_runtimes(refresh=True)
    assert all(not item['installed'] for item in first)
    installed = True
    second = await runtime_catalog.discover_runtimes(refresh=True)
    assert all(item['status'] == 'detected' for item in second)
    assert '/private/bin' not in json.dumps(second)
    runtime_catalog._cache.clear()


@pytest.mark.asyncio
async def test_failed_scan_cancels_and_waits_for_the_other_probe(monkeypatch):
    sibling_started = asyncio.Event()
    sibling_closed = asyncio.Event()
    monkeypatch.setattr(runtime_catalog, 'resolve_cli', lambda _: '/test/claude')
    async def probe(_path, arguments):
        if arguments == ['--version']:
            await sibling_started.wait()
            raise ValueError('bad version')
        assert arguments == ['-p', '--help']  # print-mode capabilities aren't global flags
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            sibling_closed.set()
    monkeypatch.setattr(runtime_catalog, '_probe', probe)
    result = await runtime_catalog.detect_runtime(runtime_catalog.RUNTIME_DEFINITIONS[0])
    assert result['status'] == 'probe_failed'
    assert sibling_closed.is_set()


@pytest.mark.asyncio
async def test_non_version_cli_output_is_not_published_as_a_version(monkeypatch):
    monkeypatch.setattr(runtime_catalog, 'resolve_cli', lambda _: '/private/claude')
    async def probe(_path, _arguments):
        return 'unexpected private diagnostics without a version'
    monkeypatch.setattr(runtime_catalog, '_probe', probe)
    result = await runtime_catalog.detect_runtime(runtime_catalog.RUNTIME_DEFINITIONS[0])
    assert result['version'] is None
    assert 'private' not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('selected', ['/runtime-account/.local/bin/codex', '/runtime-account/npm/codex.js'])
async def test_codex_resolves_host_cli_before_entering_worker_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selected: str,
) -> None:
    monkeypatch.setattr(codex, 'resolve_cli', lambda name: selected if name == 'codex' else '/node-runtime/bin/node')
    written = []
    stdout = asyncio.StreamReader()
    stdout.feed_data(json.dumps({'protocolVersion': codex.WORKER_PROTOCOL_VERSION, 'ok': True}).encode() + b'\n')
    stdout.feed_eof()
    process = SimpleNamespace(
        stdin=SimpleNamespace(write=lambda data: written.append(json.loads(data)), drain=AsyncMock(),
                              close=lambda: None, wait_closed=AsyncMock()),
        stdout=stdout, stderr=None, returncode=0, wait=AsyncMock(return_value=0),
    )
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(codex, 'spawn_owned_process', spawn)
    adapter = codex.CodexMindmapAdapter()
    monkeypatch.setattr(adapter, '_terminate_worker', AsyncMock())
    await adapter._invoke_worker(
        {'protocolVersion': codex.WORKER_PROTOCOL_VERSION, 'codexBin': '/untrusted/path'},
        workspace=tmp_path, environment={'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin'},
    )
    assert written[0]['codexBin'] == selected
    environment = spawn.await_args.kwargs['env']
    assert environment['HOME'] == str(tmp_path)
    assert environment['PATH'] == (
        '/node-runtime/bin' + os.pathsep + '/usr/bin:/bin' if selected.endswith('.js') else '/usr/bin:/bin'
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('selected', ['/runtime-account/.local/bin/codex', None])
async def test_codex_worker_uses_host_selected_binary_or_sdk_fallback(
    monkeypatch: pytest.MonkeyPatch, selected: str | None,
) -> None:
    configs = []

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            configs.append(config)

        async def __aenter__(self) -> 'FakeCodex':
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def account(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(account=SimpleNamespace(type='chatgpt'))

    monkeypatch.setattr(openai_codex, 'AsyncCodex', FakeCodex)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    await codex_worker.run_request({
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION, 'operation': 'healthcheck', 'codexBin': selected,
    })
    assert configs[0].codex_bin == selected


@pytest.mark.asyncio
@pytest.mark.parametrize('agent_key', ['codex', 'kimi'])
async def test_http_mcp_uses_existing_draft_deltas_and_todo_is_non_mutating(agent_key):
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    context = AgentRunContext(
        job_id='job-1',
        user_id=1,
        intent='create',
        prompt='订单',
        parameters={'layout': 'logicalStructure'},
        source_document=None,
        tool_service=MindmapToolService(),
    )
    bridge = _CodexToolExecutionBridge(context, emit, ALLOWED_TOOL_NAMES, agent_key=agent_key,
                                      adapter_version='1.0.0', prompt_version='runtime-test')
    async with mindmap_http_mcp(bridge, ALLOWED_TOOL_NAMES) as server:
        async with httpx.AsyncClient(trust_env=False) as client:

            async def rpc(method, params):
                response = await client.post(
                    server['url'], json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
                )
                assert response.status_code == 200
                return response.json()['result']

            hello = await rpc('initialize', {})
            assert hello['capabilities'] == {'tools': {}}
            assert any(item['name'] == 'update_plan' for item in (await rpc('tools/list', {}))['tools'])
            await rpc(
                'tools/call',
                {'name': 'update_plan', 'arguments': {'todos': [{'content': '搭建', 'status': 'in_progress'}]}},
            )
            assert not any(kind == 'draft_changed' for kind, _ in events)
            result = await rpc('tools/call', {'name': 'start_document', 'arguments': {'title': '订单'}})
            root = json.loads(result['content'][0]['text'])['rootUid']
            await rpc(
                'tools/call', {'name': 'add_nodes', 'arguments': {'nodes': [{'parentUid': root, 'text': '支付'}]}}
            )
            drafts = [payload for kind, payload in events if kind == 'draft_changed']
            assert len(drafts) == 2
            assert drafts[-1]['operations']
            assert any(payload.get('toolInput') for kind, payload in events if kind == 'tool_started')
            await rpc('tools/call', {'name': 'complete_artifact', 'arguments': {}})
            assert bridge.completed['artifact']['manifest']['generator']['agentKey'] == agent_key
            assert bridge.completed['artifact']['manifest']['generator']['adapterVersion'] == '1.0.0'
            assert (
                await client.post(server['url'], headers={'Origin': 'http://untrusted'}, json={})
            ).status_code == 403
            assert (await client.post(server['url'] + 'invalid', json={})).status_code == 404


class FakeStdin:
    def __init__(self, reader):
        self.reader = reader
        self.sent = []

    def write(self, data):
        request = json.loads(data)
        self.sent.append(request)
        method = request.get('method')
        if 'id' not in request or not method:
            return
        result = {}
        if method == 'initialize':
            result = {'protocolVersion': 1, 'agentCapabilities': {'mcpCapabilities': {'http': True}}}
        elif method == 'session/new':
            result = {'sessionId': 'session-1'}
        elif method == 'session/prompt':
            for update in [
                {'sessionUpdate': 'agent_thought_chunk', 'content': {'text': 'hidden'}},
                {'sessionUpdate': 'agent_message_chunk', 'content': {'text': '可见进度'}},
                {'sessionUpdate': 'plan', 'entries': [{'content': '读取', 'status': 'completed'}]},
            ]:
                self.reader.feed_data(
                    (
                        json.dumps(
                            {
                                'jsonrpc': '2.0',
                                'method': 'session/update',
                                'params': {'sessionId': 'session-1', 'update': update},
                            }
                        )
                        + '\n'
                    ).encode()
                )
            result = {'stopReason': 'end_turn'}
        self.reader.feed_data((json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}) + '\n').encode())

    async def drain(self):
        pass


@pytest.mark.asyncio
async def test_acp_lifecycle_streams_visible_progress_and_cancels_by_session():
    reader = asyncio.StreamReader()
    stdin = FakeStdin(reader)
    events = []

    async def emit(kind, payload):
        events.append((kind, payload))

    session = AcpSession(SimpleNamespace(stdin=stdin, stdout=reader), emit)
    try:
        await session.start('/tmp', [{'type': 'http', 'name': 'mindmap', 'url': 'http://127.0.0.1/secret'}])
        await session.prompt('test', 1)
        await session.cancel()
        assert [message['method'] for message in stdin.sent] == [
            'initialize',
            'session/new',
            'session/prompt',
            'session/cancel',
        ]
        assert session.text == '可见进度'
        assert 'hidden' not in json.dumps(events)
        assert any(kind == 'todo_updated' for kind, _ in events)
    finally:
        await session.close()


def test_kimi_completion_accepts_only_explicit_terminal_contract():
    assert (
        completion_payload('完成\n{"completionState":"artifact_completed","title":"订单","questions":[]}')['title']
        == '订单'
    )
    with pytest.raises(MindmapArtifactError):
        completion_payload('我已完成所有任务')
