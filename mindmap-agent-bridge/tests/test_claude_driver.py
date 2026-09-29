"""Public projection and real SDK/CLI control, without a provider request."""

import asyncio
import io
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mindmap_agent_bridge import claude_driver, claude_worker
from mindmap_agent_bridge.claude_trace import ClaudeTrace
from mindmap_agent_bridge.execution import RunFailure, RunOffer, RunProtocolError


def event(kind, **values):
    return {'type': 'stream_event', 'event': {'type': kind, **values}}


def delta(text):
    return event('content_block_delta', delta={'type': 'text_delta', 'text': text})


def wrapper(text, id='provider-1'):
    return {'type': 'assistant', 'message': {'id': id, 'content': [{'type': 'text', 'text': text}]}}


def visible(events):
    return ''.join(item['text'] for item in events if item['kind'] == 'public_text')


@pytest.mark.parametrize('wrapper_first', [False, True])
def test_public_text_deduplicates_partial_and_full_in_either_order(wrapper_first):
    trace = ClaudeTrace()
    start = event('message_start', message={'id': 'provider-1'})
    parts = [start, delta('公开进度，'), delta('继续创建。'), event('message_stop')]
    messages = ([wrapper('公开进度，继续创建。'), *parts] if wrapper_first
                else [*parts, wrapper('公开进度，继续创建。')])
    emitted = [item for message in messages for item in trace.consume(message)]
    assert visible(emitted) == '公开进度，继续创建。'
    assert 'provider-1' not in json.dumps(emitted)


def test_old_nonstream_wrappers_are_not_dropped_or_repeated():
    trace = ClaudeTrace()
    messages = [wrapper('第一步', None), wrapper('第一步', None), wrapper('第二步', None)]
    assert visible([e for m in messages for e in trace.consume(m)]) == '第一步第二步'


def test_hidden_reasoning_and_raw_envelopes_never_leave_device():
    trace = ClaudeTrace()
    emitted = []
    for message in [
        {'type': 'system', 'secret': 'private'},
        event('message_start', message={'id': 'private-provider-id'}),
        event('content_block_delta', delta={'type': 'thinking_delta', 'thinking': 'private-chain'}),
        event('content_block_delta', delta={'type': 'signature_delta', 'signature': 'private-signature'}),
        {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'input': {'secret': 'private'}}]}},
    ]:
        emitted.extend(trace.consume(message))
    assert emitted == [{'kind': 'thinking'}]


def test_split_credentials_are_redacted_before_public_transport():
    trace = ClaudeTrace()
    messages = [event('message_start', message={'id': 'provider-1'}),
                delta('进度 sk-abc'), delta('defghijklmnopqrst '), delta('Bearer '), delta('private-token '),
                delta('结束。'), event('message_stop')]
    result = visible([e for m in messages for e in trace.consume(m)])
    assert 'sk-' not in result and 'private-token' not in result and 'Bearer' not in result
    assert result == '进度 [已隐藏] [已隐藏] 结束。'


def test_structured_discussion_streams_content_only_and_edit_json_is_hidden():
    text = '{"completionState":"message_completed","title":"private-title","content":"订单包含创建。支付。","contentType":"text/plain"}'
    messages = [event('message_start', message={'id': 'provider-1'}), delta(text[:80]), delta(text[80:]),
                event('message_stop'), wrapper(text)]
    discuss, edit = ClaudeTrace(discuss=True), ClaudeTrace()
    assert visible([e for m in messages for e in discuss.consume(m)]) == '订单包含创建。支付。'
    assert visible([e for m in messages for e in edit.consume(m)]) == ''


def test_local_environment_does_not_inherit_application_or_loader_secrets(monkeypatch):
    monkeypatch.setenv('DATABASE_PASSWORD', 'private-db')
    monkeypatch.setenv('PYTHONPATH', '/untrusted')
    monkeypatch.setenv('NODE_OPTIONS', '--require=/untrusted')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'local-only-key')
    environment = claude_driver.local_environment()
    assert environment['ANTHROPIC_API_KEY'] == 'local-only-key'
    assert not {'DATABASE_PASSWORD', 'PYTHONPATH', 'NODE_OPTIONS'} & environment.keys()


def offer(prompt='normal'):
    # Minimal schemas sufficient for an actual SDK MCP exchange.
    descriptors = []
    for name in ['update_plan', 'start_document', 'add_nodes', 'complete_artifact']:
        descriptors.append({'name': name, 'description': name, 'inputSchema': {'type': 'object', 'properties': {}}})
    return RunOffer('11111111-1111-4111-8111-111111111111', 2, 'claude', 'create', 'preview', prompt, tuple(descriptors))


def install_mock(monkeypatch, tmp_path):
    binary = tmp_path / 'claude'
    shutil.copyfile(Path(__file__).with_name('fixtures') / 'claude_mock.py', binary)
    binary.chmod(0o700)
    monkeypatch.setattr(claude_driver, 'resolve_binary', lambda name: str(binary))
    monkeypatch.setenv('DATABASE_PASSWORD', 'private-db-sentinel')
    return binary


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['normal', 'orphan'])
async def test_actual_sdk_mcp_handshake_and_process_cleanup(monkeypatch, tmp_path, mode):
    binary = install_mock(monkeypatch, tmp_path)
    calls, events = [], []
    async def tool(name, arguments):
        calls.append((name, arguments))
        return {'ok': True, 'result': {'rootUid': 'root-1'} if name == 'start_document' else {}}
    channel = type('Channel', (), {
        'tool': staticmethod(tool), 'thinking': AsyncMock(side_effect=lambda: events.append('thinking')),
        'public_text': AsyncMock(side_effect=lambda text, **_: events.append(text)),
    })()
    driver = claude_driver.ClaudeRunDriver()
    try:
        result = await asyncio.wait_for(driver.run(offer(mode), channel), 8)
    except BaseException:
        if binary.with_suffix('.error').exists():
            pytest.fail(binary.with_suffix('.error').read_text())
        raise
    finally:
        await driver.stop()
    assert result['completionState'] == 'artifact_completed'
    assert [name for name, _ in calls] == ['update_plan', 'start_document', 'add_nodes', 'update_plan', 'complete_artifact']
    assert events == ['thinking', '正在整理订单流程，']
    assert not driver.owner._alive()
    assert not Path(driver._directory).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,code', [
    ('auth_failed', 'AI_PROVIDER_AUTH_FAILED'), ('rate_limited', 'AI_RATE_LIMITED'),
    ('invalid_completion', 'AI_AGENT_UNAVAILABLE'), ('gateway_error', 'AI_AGENT_UNAVAILABLE'),
])
async def test_actual_sdk_failure_and_tool_errors_never_become_success(monkeypatch, tmp_path, mode, code):
    binary = install_mock(monkeypatch, tmp_path)
    channel = type('Channel', (), {
        'tool': AsyncMock(return_value={'ok': False, 'error': {'code': 'AI_OUTPUT_INVALID', 'message': '工具参数无效'}}),
        'thinking': AsyncMock(), 'public_text': AsyncMock(),
    })()
    driver = claude_driver.ClaudeRunDriver()
    try:
        with pytest.raises(RunFailure) as failure:
            await asyncio.wait_for(driver.run(offer(mode), channel), 8)
        assert failure.value.code == code
        assert 'private' not in str(failure.value)
        assert not binary.with_suffix('.error').exists()
    finally:
        await driver.stop()
    assert not driver.owner._alive()


@pytest.mark.asyncio
@pytest.mark.parametrize('subtype,reason,is_error,status,code', [
    ('error_max_budget_usd', None, True, None, 'AI_BUDGET_EXCEEDED'),
    ('error_max_turns', None, True, None, 'AI_BUDGET_EXCEEDED'),
    ('success', 'max_turns', False, None, 'AI_BUDGET_EXCEEDED'),
    ('error_max_budget_usd', None, True, 401, 'AI_PROVIDER_AUTH_FAILED'),
    ('error_max_turns', 'max_turns', True, 403, 'AI_PROVIDER_AUTH_FAILED'),
    ('error_max_budget_usd', None, True, 429, 'AI_RATE_LIMITED'),
    ('success', 'aborted_streaming', False, None, 'AI_AGENT_UNAVAILABLE'),
    ('success', None, True, None, 'AI_AGENT_UNAVAILABLE'),
])
async def test_worker_preserves_budget_failures_and_auth_rate_limit_priority(
    monkeypatch, subtype, reason, is_error, status, code,
):
    import claude_agent_sdk as sdk

    async def query(**_kwargs):
        yield sdk.ResultMessage(
            subtype=subtype, duration_ms=1, duration_api_ms=1, is_error=is_error,
            num_turns=1, session_id='private-session', terminal_reason=reason,
            api_error_status=status, errors=['private-provider-diagnostics'],
        )

    monkeypatch.setattr(sdk, 'query', query)
    selected = offer()
    payload = {**selected.identity, 'type': 'run', 'agentKey': selected.agent_key,
               'intent': selected.intent, 'executionMode': selected.execution_mode,
               'prompt': selected.prompt, 'tools': list(selected.tools)}
    reader, writer = asyncio.StreamReader(), io.BytesIO()
    reader.feed_data(json.dumps({'type': 'start', 'offer': payload, 'cliPath': '/not-launched/claude'}).encode() + b'\n')
    reader.feed_eof()

    await claude_worker.serve(reader, writer, sdk=sdk)

    assert json.loads(writer.getvalue()) == {'type': 'failed', 'errorCode': code}


@pytest.mark.asyncio
async def test_driver_cannot_start_after_stop_or_clean_an_uncreated_directory(monkeypatch, tmp_path):
    install_mock(monkeypatch, tmp_path)
    driver = claude_driver.ClaudeRunDriver()
    await driver.stop()
    with pytest.raises(RunProtocolError):
        await driver.run(offer(), None)
    assert driver.owner.process is None and driver._directory is None


@pytest.mark.asyncio
async def test_actual_cli_cancel_and_repeated_stop_reap_ignored_sigterm(monkeypatch, tmp_path):
    install_mock(monkeypatch, tmp_path)
    ready = asyncio.Event()
    channel = type('Channel', (), {'thinking': AsyncMock(), 'public_text': AsyncMock(side_effect=lambda *_a, **_k: ready.set())})()
    driver = claude_driver.ClaudeRunDriver()
    task = asyncio.create_task(driver.run(offer('wait'), channel))
    try:
        await asyncio.wait_for(ready.wait(), 8)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(driver.stop(), driver.stop())
        assert not driver.owner._alive()
        assert not Path(driver._directory).exists()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await driver.stop()


def test_sdk_options_disable_builtin_tools_and_global_customization():
    import claude_agent_sdk as sdk
    options = claude_worker.build_options(sdk, offer(), '/trusted/local/claude', None)
    assert options.tools == [] and options.strict_mcp_config is True
    assert options.permission_mode == 'dontAsk'
    assert options.setting_sources == [] and options.skills == [] and options.plugins == [] and options.agents == {}
    assert set(options.allowed_tools) == {f'mcp__mindmap__{tool["name"]}' for tool in offer().tools}
    assert json.loads(options.settings)['disableAllHooks'] is True
    assert options.extra_args['no-session-persistence'] is None
    assert options.include_partial_messages is True


def test_driver_rejects_reuse_and_wrong_agent_before_spawn(monkeypatch, tmp_path):
    from dataclasses import replace
    install_mock(monkeypatch, tmp_path)
    driver = claude_driver.ClaudeRunDriver()
    with pytest.raises(RunProtocolError):
        asyncio.run(driver.run(replace(offer(), agent_key='codex'), None))
    assert driver.owner.process is None and driver._directory is None
