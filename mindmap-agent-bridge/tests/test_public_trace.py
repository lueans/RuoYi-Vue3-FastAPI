"""Public conversation must survive provider-specific JSON chunk boundaries."""

import json

import pytest

from mindmap_agent_bridge.claude_trace import ClaudeTrace
from mindmap_agent_bridge.codex_trace import CodexTrace
from mindmap_agent_bridge.public_trace import PublicTextProjection


def claude_event(kind, **values):
    return {'type': 'stream_event', 'event': {'type': kind, **values}}


def text(events):
    return ''.join(event.get('text', '') for event in events)


@pytest.mark.parametrize('control_suffix', [False, True])
@pytest.mark.parametrize('credential', ['sk-' + 'a' * 24, 'Bearer private-value', 'Bearer\u00a0private-value'])
def test_adjacent_chinese_credentials_never_leave_device_during_streaming(control_suffix, credential):
    trace = PublicTextProjection(control_suffix=control_suffix)
    state = trace._state()
    events = []
    source = '密钥' + credential + ' 后续进度。'
    for character in source:
        trace._append(state, character)
        events += trace._publish(state)
        assert '密钥[已隐藏] 后续进度。'.startswith(text(events))
    events += trace._publish(state, final=True)
    assert text(events) == '密钥[已隐藏] 后续进度。'


@pytest.mark.parametrize('tail', [
    '{"completionState":', '```JSON\n{"title":"控制标题",',
    '{"completionState": True}', r'{"completion\u0053tate": True}',
    '```JSON\n{"title":"控制标题","completionState":"artifact_completed"}\n```',
])
def test_acp_prose_streams_before_terminal_and_never_releases_control_tails(tail):
    trace = PublicTextProjection(control_suffix=True)
    state = trace._state()
    source = '使用 {name} 和 {"enabled": True}。Bearer private-value\n继续生成。'
    expected = source.replace('Bearer private-value', '[已隐藏]')
    events = []
    for character in source:
        trace._append(state, character)
        events += trace._publish(state)
    assert text(events) == expected
    for character in tail:
        trace._append(state, character)
        events += trace._publish(state)
        assert text(events) == expected
    events += trace._publish(state, final=True)
    assert text(events) == expected


@pytest.mark.parametrize('provider', ['claude', 'codex'])
@pytest.mark.parametrize('discuss', [False, True])
@pytest.mark.parametrize('prefix', ['\n', '\n\t ', '```json\n', '\n```JSON\n'])
def test_split_json_prefix_streams_only_content_without_wrapper_replay(provider, discuss, prefix):
    content = '你好 世界。'
    contract = json.dumps({'completionState': 'message_completed', 'content': content,
                           'title': '控制标题'}, ensure_ascii=False)
    source = prefix + contract + ('\n```' if '`' in prefix else '')
    # Two-way splits cover every possible prefix/content transition, including
    # an entire whitespace-only first delta and partial Markdown fences.
    for split in range(1, len(source)):
        expected = content if discuss else ''
        if provider == 'claude':
            trace = ClaudeTrace(discuss=discuss)
            events = trace.consume(claude_event('message_start', message={'id': 'one'}))
            for part in (source[:split], source[split:]):
                events += trace.consume(claude_event('content_block_delta', delta={'type': 'text_delta', 'text': part}))
                assert expected.startswith(text(events)), (prefix, split)
            assert text(events) == expected  # Content is visible before message_stop.
            events += trace.consume(claude_event('message_stop'))
            events += trace.consume({'type': 'assistant', 'message': {'id': 'one', 'content': [{'text': source}]}})
        else:
            trace = CodexTrace(discuss=discuss)
            events = trace.consume('item/started', {'item': {'id': 'one', 'type': 'agentMessage', 'phase': 'commentary'}})
            for part in (source[:split], source[split:]):
                events += trace.consume('item/agentMessage/delta', {'itemId': 'one', 'delta': part})
                assert expected.startswith(text(events)), (prefix, split)
            assert text(events) == expected
            events += trace.consume('item/completed', {'item': {'id': 'one', 'type': 'agentMessage', 'text': source}})
        assert text(events) == expected, (prefix, split)


def test_claude_block_stop_does_not_publish_an_undecided_message_prefix():
    trace = ClaudeTrace(discuss=True)
    events = trace.consume(claude_event('message_start', message={'id': 'one'}))
    events += trace.consume(claude_event('content_block_delta', delta={'type': 'text_delta', 'text': '\n'}))
    events += trace.consume(claude_event('content_block_stop'))
    assert text(events) == ''
    source = '```JSON\n' + json.dumps({'completionState': 'message_completed', 'content': '继续显示正文。'}) + '\n```'
    for character in source:
        events += trace.consume(claude_event('content_block_delta', delta={'type': 'text_delta', 'text': character}))
    events += trace.consume(claude_event('message_stop'))
    assert text(events) == '继续显示正文。'


@pytest.mark.parametrize('source', ['\n普通进度。', '\n```python\nprint(1)\n```', '\n`参数`', ' \n\t'])
def test_non_json_whitespace_and_markdown_are_preserved(source):
    trace = ClaudeTrace()
    events = trace.consume(claude_event('message_start', message={'id': 'one'}))
    for character in source:
        events += trace.consume(claude_event('content_block_delta', delta={'type': 'text_delta', 'text': character}))
    events += trace.consume(claude_event('message_stop'))
    assert text(events) == source


def test_json_content_redaction_and_unicode_remain_valid_after_prefix_buffering():
    trace = ClaudeTrace(discuss=True)
    source = '\n```JSON\n' + json.dumps({'content': '你好😀。Bearer private-token\nsk-' + 'a' * 24 + ' 结束。'}) + '\n```'
    events = trace.consume(claude_event('message_start', message={'id': 'one'}))
    for character in source:
        events += trace.consume(claude_event('content_block_delta', delta={'type': 'text_delta', 'text': character}))
        text(events).encode('utf-8')
        assert 'private-token' not in text(events) and 'sk-' not in text(events)
    events += trace.consume(claude_event('message_stop'))
    assert text(events) == '你好😀。[已隐藏]\n[已隐藏] 结束。'
