"""Kimi policy/ACP/MCP tests; no real credentials, database or paid models."""

import asyncio
import json
import os
import socket
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from mindmap_agent_bridge import kimi_driver, kimi_policy
from mindmap_agent_bridge.execution import RunFailure, RunOffer, RunProtocolError
from mindmap_agent_bridge.kimi_mcp import KimiToolGateway, _Server
from mindmap_agent_bridge.kimi_session import KimiSession, completion_payload

FINAL = {'completionState': 'artifact_completed', 'title': '测试脑图', 'questions': []}
OFFER = RunOffer('11111111-1111-4111-8111-111111111111', 1, 'kimi', 'create', 'preview', '创建测试脑图', (
    {'name': 'update_plan', 'description': '更新计划', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'add_nodes', 'description': '增加节点', 'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'complete_artifact', 'description': '完成脑图', 'inputSchema': {'type': 'object', 'properties': {}}},
), model_ref='kimi-for-coding')


def channel():
    return type('Channel', (), {'tool': AsyncMock(return_value={'ok': True, 'result': {'added': 1}}),
                               'thinking': AsyncMock(), 'public_text': AsyncMock()})()


def update(kind, **fields):
    return {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
        'sessionId': 'private-session', 'update': {'sessionUpdate': kind, **fields}}}


def message(text):
    return update('agent_message_chunk', content={'type': 'text', 'text': text})


class Harness:
    def __init__(self, frames):
        self.frames, self.sent = frames, []
        self.queue = asyncio.Queue()
        self.channel = channel()
        self.gateway = KimiToolGateway(OFFER, self.channel)
        self.gateway.description = {'name': 'mindmap', 'type': 'http', 'url': 'http://127.0.0.1:1/private', 'headers': []}
        self.session = KimiSession(self.queue.get, self.send, cwd='/private/isolated', gateway=self.gateway)

    async def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        method = value.get('method')
        if method == 'initialize':
            result = {'protocolVersion': 1, 'agentInfo': {'version': '2.1.1'},
                      'agentCapabilities': {'mcpCapabilities': {'http': True}}}
        elif method == 'session/new':
            result = {'sessionId': 'private-session', 'configOptions': [
                {'id': 'model', 'currentValue': 'mindmap-kimi'}, {'id': 'mode', 'currentValue': 'default'}]}
        elif method == 'session/prompt':
            for frame in self.frames:
                self.queue.put_nowait(json.dumps(frame))
            result = {'stopReason': 'end_turn'}
        else:
            return
        self.queue.put_nowait(json.dumps({'jsonrpc': '2.0', 'id': value['id'], 'result': result}))

    async def run(self, offer=OFFER):
        return await asyncio.wait_for(self.session.run(offer, self.channel), 2)


def test_private_configuration_is_exact_nonempty_and_toml_valid(tmp_path, monkeypatch):
    monkeypatch.setenv('KIMI_CODE_TOOLS', 'Bash')
    monkeypatch.setenv('NODE_OPTIONS', '--require unsafe')
    env = kimi_policy.isolated_environment(tmp_path)
    assert 'NODE_OPTIONS' not in env and 'KIMI_CODE_TOOLS' not in env
    provider = {'type': 'kimi', 'api_key': 'fake-only', 'base_url': kimi_policy.BASE_URL}
    kimi_policy.write_configuration(env, OFFER, provider)
    path = Path(env['KIMI_CODE_HOME']) / 'config.toml'
    values = kimi_policy.tomllib.loads(path.read_text())
    assert values['tools']['enabled'] == [f'mcp__mindmap__{tool["name"]}' for tool in OFFER.tools]
    assert values['hooks'] == [] and values['builtin_product_skills'] is False
    assert values['permission']['rules'] == []
    assert path.stat().st_mode & 0o777 == 0o600
    zero = kimi_policy.configuration(replace(OFFER, intent='discuss', tools=()), provider)
    assert zero['tools']['enabled'] == [kimi_policy.NO_TOOLS]
    assert zero['permission']['rules'] == []


@pytest.mark.parametrize('change', [{'model_ref': 'default'}, {'agent_key': 'claude'}, {'intent': 'discuss'},
                                   {'tools': ({'name': 'Bash'},)}, {'execution_mode': 'direct'}])
def test_unverified_model_or_tool_policy_rejected(change):
    with pytest.raises(RunFailure):
        kimi_policy.validate_offer(replace(OFFER, **change))


@pytest.mark.parametrize('base', list(kimi_policy.REGIONS))
def test_local_oauth_copy_is_private_and_does_not_copy_configuration(tmp_path, monkeypatch, base):
    local = tmp_path / 'local'
    local.mkdir()
    (local / 'credentials').mkdir()
    monkeypatch.delenv('KIMI_API_KEY', raising=False)
    monkeypatch.setenv('KIMI_CODE_HOME', str(local))
    host = kimi_policy.REGIONS[base]
    storage = 'kimi-code'
    if base != kimi_policy.BASE_URL:
        identity = json.dumps({'oauthHost': host, 'baseUrl': base}, separators=(',', ':'))
        storage += '-env-' + kimi_policy.hashlib.sha256(identity.encode()).hexdigest()[:16]
    oauth = {'storage': 'file', 'key': f'oauth/{storage}', 'oauth_host': host}
    config = {'default_model': 'local', 'models': {'local': {'provider': 'selected'}},
              'providers': {'selected': {'type': 'kimi', 'base_url': base, 'oauth': oauth}},
              'hooks': [{'event': 'SessionStart', 'command': 'must-not-copy'}]}
    (local / 'config.toml').write_text('\n'.join(f'{key} = {kimi_policy._toml(value)}' for key, value in config.items()))
    auth = local / 'credentials' / f'{storage}.json'
    auth.write_text(json.dumps({'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'expires_at': 9999999999}))
    isolated = tmp_path / 'isolated'
    isolated.mkdir()
    env = kimi_policy.isolated_environment(isolated)
    provider = kimi_policy.stage_local_auth(env)
    assert provider['oauth'] == oauth
    target = Path(env['KIMI_CODE_HOME']) / 'credentials' / auth.name
    assert target.read_bytes() == auth.read_bytes() and target.stat().st_mode & 0o777 == 0o600
    target.write_text('private refresh')
    assert 'fake-access' in auth.read_text()
    assert not (Path(env['KIMI_CODE_HOME']) / 'config.toml').exists()


def test_explicit_key_not_inherited_and_consent_not_from_saved_config(tmp_path, monkeypatch):
    monkeypatch.setenv('KIMI_API_KEY', 'fake-local-only')
    env = kimi_policy.isolated_environment(tmp_path)
    assert kimi_policy.stage_local_auth(env)['api_key'] == 'fake-local-only'
    assert 'fake-local-only' not in json.dumps(env)
    with pytest.raises(kimi_driver.BridgeError, match='金额上限'):
        kimi_driver.KimiRunDriver()


@pytest.mark.asyncio
async def test_acp_stream_public_text_and_authoritative_gateway_only():
    frames = [update('agent_thought_chunk', content={'type': 'text', 'text': 'hidden-secret'}),
              message('开始创建。'), update('tool_call', toolCallId='private-call', title='Human title', status='in_progress', rawInput={'secret': 'private'}),
              update('tool_call_update', toolCallId='private-call', status='completed', rawOutput='private-result'),
              message('已完成。\n' + json.dumps(FINAL, ensure_ascii=False))]
    h = Harness(frames)
    assert await h.run() == FINAL
    assert not h.gateway.accepting
    shown = ''.join(call.args[0] for call in h.channel.public_text.await_args_list)
    assert shown.rstrip() == '开始创建。已完成。'
    assert 'hidden-secret' not in shown and 'completionState' not in shown
    h.channel.thinking.assert_awaited_once()
    h.channel.tool.assert_not_awaited()  # MCP, never ACP copies, owns execution
    assert h.sent[0]['params']['clientCapabilities'] == {}
    assert [item.get('method') for item in h.sent] == ['initialize', 'session/new', 'session/prompt']


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['session/request_permission', 'fs/read_text_file', 'terminal/create'])
async def test_reverse_capabilities_are_denied_never_auto_approved(method):
    h = Harness([{'jsonrpc': '2.0', 'id': 'private-request', 'method': method, 'params': {}}])
    with pytest.raises(RunFailure):
        await h.run()
    assert not h.gateway.accepting
    assert h.sent[-1].get('error') or h.sent[-1]['result']['outcome']['outcome'] == 'cancelled'
    h.channel.tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_and_late_updates_do_not_publish_or_reopen_gateway():
    foreign = message('foreign-secret')
    foreign['params']['sessionId'] = 'wrong'
    h = Harness([foreign, message(json.dumps(FINAL))])
    await h.run()
    await h.session._update(message('late-secret')['params'], h.channel)
    h.channel.public_text.assert_not_awaited()
    assert not h.gateway.accepting


def permission(identity=1, **overrides):
    return {'jsonrpc': '2.0', 'id': identity, 'method': 'session/request_permission', 'params': {
        'sessionId': 'private-session', 'toolCall': {'toolCallId': 'call-1', 'title': 'mcp__mindmap__add_nodes'},
        'options': [{'optionId': 'approve_once', 'kind': 'allow_once'},
                    {'optionId': 'approve_always', 'kind': 'allow_always'}], **overrides}}


@pytest.mark.asyncio
async def test_pinned_permission_grants_once_only_for_active_known_allowed_call():
    started = update('tool_call', toolCallId='call-1', title='Human description', status='in_progress')
    h = Harness([started, permission(), message(json.dumps(FINAL))])
    assert await h.run() == FINAL
    assert h.sent[-1]['result'] == {'outcome': {'outcome': 'selected', 'optionId': 'approve_once'}}
    assert h.session._approve_once(permission()['params']) is None  # finished turn


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['orphan', 'foreign', 'terminal', 'repeat', 'always_only', 'unknown', 'title_only'])
async def test_permission_cannot_expand_capabilities(scenario):
    started = update('tool_call', toolCallId='call-1', title='Human description', status='in_progress')
    request = permission()
    frames = [started]
    if scenario == 'orphan':
        frames = []
    elif scenario == 'foreign':
        request['params']['sessionId'] = 'foreign'
    elif scenario == 'terminal':
        frames.append(update('tool_call_update', toolCallId='call-1', status='completed'))
    elif scenario == 'repeat':
        frames.append(permission(2))
    elif scenario == 'always_only':
        request['params']['options'] = [{'optionId': 'approve_always', 'kind': 'allow_always'}]
    elif scenario == 'unknown':
        request['params']['toolCall']['title'] = 'Bash'
    elif scenario == 'title_only':
        started['params']['update']['status'] = 'completed'
    h = Harness([*frames, request])
    with pytest.raises(RunFailure):
        await h.run()
    assert h.sent[-1]['result']['outcome']['outcome'] == 'cancelled'


@pytest.mark.asyncio
async def test_split_public_secrets_hidden_reasoning_and_completion_control_fields():
    content = '公开进度。Bearer sk-fake-private-key-must-hide\n' + json.dumps(FINAL, ensure_ascii=False)
    for offset in range(len(content)):
        h = Harness([message(content[:offset]), message(content[offset:])])
        assert await h.run() == FINAL
        shown = ''.join(call.args[0] for call in h.channel.public_text.await_args_list)
        assert 'sk-fake' not in shown and 'completionState' not in shown
        assert shown.startswith('公开进度。')


@pytest.mark.asyncio
@pytest.mark.parametrize('prose', [
    '使用 {name} 占位符，继续生成。',
    '配置示例 {"style":{"color":"blue"}}，继续生成。',
    '配置示例\n```JSON\n{"style":"blue"}\n```\n继续生成。',
    '示例\n```python\nconfig = {"enabled": True, "value": None}\n```\n继续生成。',
    '{"enabled": False} 是 Python 字典，后续说明仍应显示。',
    '```json\n{"style":"blue"}\n```\n继续生成。',
])
async def test_ordinary_examples_survive_each_chunk_boundary_before_completion(prose):
    source = prose + '\n```JSON\n' + json.dumps(FINAL, ensure_ascii=False) + '\n```'
    chunks = [[source[:index], source[index:]] for index in range(1, len(source))]
    chunks.append(list(source))
    for parts in chunks:
        h = Harness([message(part) for part in parts])
        assert await h.run() == FINAL
        shown = ''.join(call.args[0] for call in h.channel.public_text.await_args_list)
        assert shown == prose + '\n'


@pytest.mark.asyncio
async def test_interrupt_closes_tools_before_cancel_send_and_is_not_stop_confirmation():
    h = Harness([])
    h.session.session_id = 'private-session'
    h.gateway.accepting = True
    assert await h.session.interrupt() is True
    assert not h.gateway.accepting
    assert h.sent[-1]['method'] == 'session/cancel' and 'id' not in h.sent[-1]
    with pytest.raises(RunProtocolError):
        await h.run()


@pytest.mark.parametrize('text', ['done', '{"completionState":"artifact_completed"}', json.dumps(FINAL) + ' extra',
                                  json.dumps({**FINAL, 'secret': 'private'}), json.dumps({**FINAL, 'title': float('nan')})])
def test_invalid_completions_not_treated_as_success(text):
    with pytest.raises(RunProtocolError):
        completion_payload(text, OFFER)


@pytest.mark.asyncio
async def test_http_gateway_auth_phase_allowlist_dedup_and_stop():
    c = channel()
    gateway = KimiToolGateway(OFFER, c)
    try:
        description = await gateway.start()
        async with httpx.AsyncClient(trust_env=False) as client:
            async def post(identity, method, params=None, **kwargs):
                return await client.post(description['url'], json={'jsonrpc': '2.0', 'id': identity,
                                         'method': method, 'params': params or {}}, **kwargs)
            assert (await post(1, 'initialize')).status_code == 200
            assert (await post(2, 'tools/list')).json()['result']['tools'] == list(OFFER.tools)
            assert (await post(3, 'tools/call', {'name': 'add_nodes'})).status_code == 403
            gateway.accepting = True
            assert (await post(4, 'tools/call', {'name': 'Bash'})).status_code == 400
            assert (await post(5, 'tools/call', {'name': 'add_nodes'}, headers={'Origin': 'null'})).status_code == 403
            assert (await post(6, 'tools/call', {'name': 'add_nodes'}, headers={'Host': 'evil.example'})).status_code == 403
            assert (await post(7, 'tools/call', {'name': 'add_nodes'})).json()['result']['isError'] is False
            assert (await post(7, 'tools/call', {'name': 'add_nodes'})).status_code == 400
            gateway.disable()
            assert (await post(8, 'tools/call', {'name': 'add_nodes'})).status_code == 403
            assert (await client.get(description['url'])).status_code == 405
            assert (await client.post(description['url'] + 'wrong', json={})).status_code == 404
            assert c.tool.await_count == 1
    finally:
        await gateway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['edit', 'bash', 'read', 'discuss', 'cancel'])
async def test_real_pinned_kimi_cli_against_loopback_provider_only(tmp_path, monkeypatch, scenario):
    """Opt-in real CLI test; test endpoint injection is NOT a production option."""
    bundle = os.environ.get('MINDMAP_KIMI_TEST_BUNDLE')
    node = os.environ.get('MINDMAP_KIMI_TEST_NODE')
    if not bundle or not node:
        pytest.skip('Set explicit local test Node and pinned Kimi 2.1.1 bundle paths')
    requests = []
    arrived = asyncio.Event()
    canary = tmp_path / 'must-not-exist'
    secret_file = tmp_path / 'private-canary'
    secret_file.write_text('private-canary-must-not-leak')
    unsafe = [('Bash', {'command': f'touch {canary}'})] if scenario == 'bash' else [
        ('Read', {'file_path': str(secret_file)})] if scenario == 'read' else []
    steps = unsafe + [
        ('mcp__mindmap__update_plan', {}), ('mcp__mindmap__add_nodes', {}), ('mcp__mindmap__complete_artifact', {}),
    ]
    final, offer = FINAL, OFFER
    if scenario == 'discuss':
        steps = []
        offer = replace(OFFER, intent='discuss', tools=())
        final = {'completionState': 'message_completed', 'title': None, 'content': '公开讨论结果。', 'contentType': 'text/plain'}

    async def respond(request):
        body = await request.json()
        requests.append(body)
        arrived.set()
        if scenario == 'cancel':
            await asyncio.sleep(2)
        index = len(requests) - 1
        delta = {'role': 'assistant', 'content': '开始创建。' if index == 0 else None}
        if index < len(steps):
            name, arguments = steps[index]
            delta['tool_calls'] = [{'index': 0, 'id': f'call-{index}', 'type': 'function',
                                   'function': {'name': name, 'arguments': json.dumps(arguments)}}]
        else:
            delta['content'] = json.dumps(final, ensure_ascii=False)
        async def stream():
            chunk = {'id': f'completion-{index}', 'object': 'chat.completion.chunk', 'model': 'kimi-for-coding',
                     'created': 1, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
            yield 'data: ' + json.dumps(chunk) + '\n\n'
            chunk['choices'] = [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if index < len(steps) else 'stop'}]
            chunk['usage'] = {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110}
            yield 'data: ' + json.dumps(chunk) + '\n\n'
            yield 'data: [DONE]\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream')

    server = _Server(uvicorn.Config(Starlette(routes=[Route('/v1/chat/completions', respond, methods=['POST'])]),
                                    lifespan='off', log_config=None, access_log=False, ws='none'))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(.01)
        assert server.started
        provider = {'type': 'kimi', 'api_key': 'fake-loopback-test-only',
                    'base_url': f'http://127.0.0.1:{sock.getsockname()[1]}/v1'}
        monkeypatch.setattr(kimi_driver, 'local_command', lambda: ([node, bundle], str(Path(node).parent)))
        monkeypatch.setattr(kimi_driver, 'stage_local_auth', lambda _env: provider)
        driver = kimi_driver.KimiRunDriver(accept_unmetered_budget=True)
        frames = []
        class RecordingSession(KimiSession):
            def __init__(self, receive, send, **kwargs):
                async def read():
                    raw = await receive()
                    if raw:
                        frame = json.loads(raw)
                        if 'id' in frame and 'method' in frame:
                            frames.append(frame)
                    return raw
                super().__init__(read, send, **kwargs)
        driver._session_type = RecordingSession
        c = channel()
        if scenario == 'cancel':
            running = asyncio.create_task(driver.run(offer, c))
            try:
                await asyncio.wait_for(arrived.wait(), 20)
            finally:
                running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            c.tool.assert_not_awaited()
        else:
            try:
                assert await asyncio.wait_for(driver.run(offer, c), 45) == final
            except RunFailure:
                pytest.fail(json.dumps({'reverse': frames, 'tools': [r.get('tools') for r in requests]}, ensure_ascii=False))
            assert [call.args[0] for call in c.tool.await_args_list] == ([] if scenario == 'discuss' else [
                'update_plan', 'add_nodes', 'complete_artifact'])
            assert len(requests) == len(steps) + 1
        if unsafe:
            tool_results = [m.get('content') for m in requests[1]['messages'] if m.get('role') == 'tool']
            assert 'disabled by the active tool policy' in json.dumps(tool_results)
        assert not canary.exists()
        assert 'private-canary-must-not-leak' not in json.dumps(requests)
        for request in requests:
            assert {tool['function']['name'] for tool in request.get('tools', [])} == {
                f'mcp__mindmap__{tool["name"]}' for tool in offer.tools}
        assert not Path(driver._directory).exists()
        assert driver.owner.process.returncode is not None and not driver.owner._alive()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 4)
        sock.close()
