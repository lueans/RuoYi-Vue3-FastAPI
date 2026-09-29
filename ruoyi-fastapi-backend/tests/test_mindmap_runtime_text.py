"""Streaming projection must be independent of provider chunk boundaries."""

import json
from typing import Any

import pytest

from module_mindmap.ai.runtime_trace import MAX_TRACE_CHARS, RuntimeTrace, public_text


def visible(events: list[tuple[str, dict[str, Any]]]) -> str:
    # Persistence sanitizes each event independently, too. It cannot repair
    # secrets whose prefix has already been published in another event.
    return ''.join(public_text(payload['text'], 4000) for kind, payload in events
                   if kind in {'assistant_delta', 'thinking_summary'})


@pytest.mark.parametrize('credential', ['sk-' + 'a' * 24, 'SK-' + 'Z' * 24,
                                       'Bearer private-value', 'bEaReR\tprivate-value', 'Bearer\u00a0private-value'])
@pytest.mark.parametrize('summary', [False, True])
@pytest.mark.parametrize('prefix', ['公开说明：', '密钥'])
def test_redaction_survives_every_split_and_intermediate_flush(credential: str, summary: bool, prefix: str) -> None:
    for split in range(1, len(credential)):
        trace = RuntimeTrace()
        events = trace.text(prefix + credential[:split], summary=summary)
        events += trace.flush()
        assert credential[:split] not in visible(events), (credential, split)
        events += trace.text(credential[split:] + ' 后续进度', summary=summary)
        events += trace.flush()
        assert visible(events) == prefix + '[已隐藏] 后续进度', (credential, split)


@pytest.mark.parametrize('credential', ['sk-' + 'x' * 24, 'Bearer private-value'])
def test_single_character_chunks_and_terminal_secret_are_redacted(credential: str) -> None:
    trace = RuntimeTrace()
    events = []
    for character in credential:
        events += trace.text(character)
        events += trace.flush()
        assert visible(events) == ''
    events += trace.finish()
    assert visible(events) == '[已隐藏]'
    assert trace.finish() == []


@pytest.mark.parametrize('credential', ['sk-' + 'a' * 24, 'Bearer private-value'])
@pytest.mark.parametrize('prefix', ['密钥', '说明é'])
def test_unicode_prefix_published_in_an_earlier_chunk_preserves_ascii_secret_boundary(
    credential: str, prefix: str,
) -> None:
    trace = RuntimeTrace()
    events = trace.text(prefix) + trace.flush()
    assert visible(events) == prefix
    for character in credential:
        events += trace.text(character) + trace.flush()
        assert visible(events) == prefix
    events += trace.finish()
    assert visible(events) == prefix + '[已隐藏]'


@pytest.mark.parametrize('prefix', ['', '\n\t ', '```json\n', '\n```JSON\n'])
@pytest.mark.parametrize('structured', [False, True])
def test_json_prefix_can_be_split_at_every_character(prefix: str, structured: bool) -> None:
    contract = json.dumps({'completionState': 'message_completed', 'content': '你好\n世界',
                           'contentType': 'text/plain', 'title': None}, ensure_ascii=False)
    source = prefix + contract + ('\n```' if '`' in prefix else '')
    for split in range(1, len(source)):
        trace = RuntimeTrace(structured_message=structured)
        events = trace.text(source[:split]) + trace.flush()
        events += trace.text(source[split:]) + trace.flush()
        events += trace.finish()
        assert visible(events) == ('你好\n世界' if structured else ''), (prefix, split)


def test_decoded_json_content_is_redacted_without_corrupting_the_envelope() -> None:
    source = json.dumps({'completionState': 'message_completed',
                         'content': 'Key: sk-' + 'a' * 24 + '\nBearer private-value\n结束😀',
                         'title': None})
    trace = RuntimeTrace(structured_message=True)
    events = []
    for character in source:
        events += trace.text(character)
        events += trace.flush()
        # Never publish an incomplete surrogate escape to the JSON/SSE encoder.
        visible(events).encode('utf-8')
    events += trace.finish()
    assert visible(events) == 'Key: [已隐藏]\n[已隐藏]\n结束😀'


@pytest.mark.parametrize('source', ['\n普通进度', '```python\nprint(1)\n```', '`value`', 's', 'bear',
                                   'foosk-' + 'a' * 24, 'barely', '开始处理，无需等待句号'])
def test_plain_text_is_preserved_and_not_misclassified(source: str) -> None:
    trace = RuntimeTrace()
    events = []
    for character in source:
        events += trace.text(character)
        events += trace.flush()
    events += trace.finish()
    assert visible(events) == source


def test_message_and_summary_buffers_do_not_share_secret_or_json_state() -> None:
    trace = RuntimeTrace(structured_message=True)
    events = trace.text('sk-', message_id='one')
    events += trace.text('正常说明', message_id='two')
    events += trace.text('Bearer ', message_id='summary', summary=True)
    events += trace.text('a' * 24, message_id='one')
    events += trace.finish('one')
    events += trace.text('private-value ', message_id='summary', summary=True)
    events += trace.finish()
    by_message = {}
    for _kind, payload in events:
        by_message[payload['messageId']] = by_message.get(payload['messageId'], '') + payload['text']
    assert by_message == {'one': '[已隐藏]', 'two': '正常说明', 'summary': '[已隐藏] '}


def test_new_tool_message_flushes_the_previous_safe_tail_before_changing_identity() -> None:
    trace = RuntimeTrace()
    events = trace.text('progress') + trace.next_message()
    events += trace.text('s') + trace.next_message()
    assert visible(events) == 'progresss'
    assert events[0][1]['messageId'] != events[-1][1]['messageId']


@pytest.mark.parametrize('source', [' ' * (MAX_TRACE_CHARS + 10), '{' + 'x' * (MAX_TRACE_CHARS + 10),
                                   'sk-' + 'x' * (MAX_TRACE_CHARS + 10)], ids=['prefix', 'json', 'credential'])
def test_undecided_json_and_sensitive_buffers_share_the_input_budget(source: str) -> None:
    trace = RuntimeTrace()
    trace.text(source)
    assert trace._chars == MAX_TRACE_CHARS
    assert trace.text('extra', message_id='another') == []


def test_partial_json_is_not_replayed_when_the_claude_wrapper_arrives() -> None:
    trace = RuntimeTrace(structured_message=True)
    source = '{"completionState":"message_completed","content":"你好"}'
    events = trace.claude({'type': 'stream_event', 'event': {
        'type': 'message_start', 'message': {'id': 'one'},
    }})
    for piece in ('\n', '`', '``json\n', source):
        events += trace.claude({'type': 'stream_event', 'event': {
            'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': piece},
        }})
    events += trace.claude({'type': 'stream_event', 'event': {'type': 'message_stop'}})
    events += trace.claude({'type': 'assistant', 'message': {
        'id': 'one', 'content': [{'text': source}],
    }})
    assert visible(events) == '你好'


def test_claude_sdk_message_identity_survives_stream_and_replayed_wrappers() -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock

    trace = RuntimeTrace()
    events = trace.claude({'type': 'stream_event', 'event': {
        'type': 'message_start', 'message': {'id': 'provider-one'},
    }})
    events += trace.claude({'type': 'stream_event', 'event': {
        'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '已读取脑图。'},
    }})
    events += trace.claude({'type': 'stream_event', 'event': {'type': 'message_stop'}})
    wrapper = AssistantMessage(content=[TextBlock(text='已读取脑图。')], model='test', message_id='provider-one')
    events += trace.claude(wrapper)
    events += trace.claude(wrapper)
    assert visible(events) == '已读取脑图。'
    assert {payload['messageId'] for kind, payload in events if kind == 'assistant_delta'} == {'provider-one'}


def test_claude_sdk_identical_text_in_distinct_messages_is_not_deduplicated() -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock

    trace = RuntimeTrace()
    events = []
    for message_id in ('first', 'second', 'first'):
        events += trace.claude(AssistantMessage(content=[TextBlock(text='检查完成。')], model='test', message_id=message_id))
    assert visible(events) == '检查完成。检查完成。'
    assert [payload['messageId'] for kind, payload in events if kind == 'assistant_delta'] == ['first', 'second']


def test_claude_thinking_wrapper_before_text_does_not_erase_the_provider_identity() -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock

    trace = RuntimeTrace()
    events = trace.claude({'type': 'stream_event', 'event': {
        'type': 'message_start', 'message': {'id': 'one'},
    }})
    events += trace.claude(AssistantMessage(content=[ThinkingBlock(thinking='private', signature='sig')],
                                          model='test', message_id='one'))
    events += trace.claude({'type': 'stream_event', 'event': {
        'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '公开说明'},
    }})
    events += trace.claude(AssistantMessage(content=[TextBlock(text='公开说明')], model='test', message_id='one'))
    events += trace.claude({'type': 'stream_event', 'event': {'type': 'message_stop'}})
    assert visible(events) == '公开说明'
    assert 'private' not in json.dumps(events)


@pytest.mark.parametrize('provider', ['native', 'claude', 'codex', 'acp'])
def test_provider_terminal_events_finish_redaction_without_raw_replay(provider: str) -> None:
    trace = RuntimeTrace()
    pieces = ['可见进度 ', 's', 'k-', 'a' * 24]
    events = []
    if provider == 'claude':
        events += trace.claude({'type': 'stream_event', 'event': {
            'type': 'message_start', 'message': {'id': 'one'},
        }})
    for piece in pieces:
        if provider == 'native':
            events += trace.native({'event': 'RunContent', 'content': piece})
            events += trace.native({'event': 'RunContentCompleted'})
        elif provider == 'claude':
            events += trace.claude({'type': 'stream_event', 'event': {
                'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': piece},
            }})
            events += trace.claude({'type': 'stream_event', 'event': {'type': 'content_block_stop'}})
        elif provider == 'codex':
            events += trace.codex('item/agentMessage/delta', {'itemId': 'one', 'delta': piece})
        else:
            events += trace.acp({'sessionUpdate': 'agent_message_chunk', 'content': {'text': piece}})
        events += trace.flush()
        assert visible(events) == '可见进度 '
    if provider == 'native':
        events += trace.native({'event': 'RunCompleted', 'content': ''.join(pieces)})
    elif provider == 'claude':
        events += trace.claude({'type': 'stream_event', 'event': {'type': 'message_stop'}})
        events += trace.claude({'type': 'assistant', 'message': {
            'id': 'one', 'content': [{'text': ''.join(pieces)}],
        }})
    elif provider == 'codex':
        events += trace.codex('item/completed', {'item': {
            'id': 'one', 'type': 'agentMessage', 'text': ''.join(pieces),
        }})
        events += trace.codex('turn/completed', {})
    else:
        # ACP prompt completion is the public terminal boundary, used by
        # AcpSession.prompt after the actual JSON-RPC response arrives.
        events += trace.finish()
    assert visible(events) == '可见进度 [已隐藏]'


def acp_text(trace: RuntimeTrace, text: str) -> list[tuple[str, dict[str, Any]]]:
    return trace.acp({'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': text}})


@pytest.mark.parametrize('fence', ['', '```json\n', '```JSON\n'])
@pytest.mark.parametrize('completion', ['artifact_completed', 'direct_completed', 'needs_input'])
def test_acp_completion_after_prose_never_enters_chat_at_any_split(fence: str, completion: str) -> None:
    prose = '脑图整理完成。\n'
    # The discriminator need not be the first key in a valid completion.
    contract = json.dumps({'title': '控制标题', 'completionState': completion}, ensure_ascii=False)
    source = prose + fence + contract + ('\n```' if fence else '')
    for parts in ([source[:split], source[split:]] for split in range(1, len(source))):
        trace = RuntimeTrace()
        events = []
        for part in parts:
            events += acp_text(trace, part) + trace.flush()
            assert prose.startswith(visible(events))
        assert visible(events) == prose  # Progress does not wait for the terminal event.
        events += trace.finish()
        assert visible(events) == prose
        assert trace.finish() == []


@pytest.mark.parametrize('source', [
    '使用 {name} 占位符，继续生成。',
    '配置示例 {"style":{"color":"blue"}}，继续生成。',
    '配置示例\n```json\n{"style":"blue"}\n```\n继续生成。',
    '示例\n```python\nprint({"color": "blue"})\n```',
    '示例\n```python\nconfig = {"enabled": True, "value": None}\n```\n继续生成。',
    '{"enabled": False} 是 Python 字典，后续说明仍应显示。',
    '{"style":"blue"} 是普通配置。',
    '```JSON\n{"style":"blue"}\n```\n继续生成。',
    '示例 {"enabled": True, "nested": {"text": "a}b"}}，继续生成。',
    '说明 `参数` 和未闭合的 {',
])
def test_acp_keeps_ordinary_braces_json_examples_and_markdown(source: str) -> None:
    trace = RuntimeTrace()
    events = []
    for character in source:
        events += acp_text(trace, character) + trace.flush()
    if source.endswith('。'):
        assert visible(events) == source  # Ordinary examples do not wait for turn completion.
    events += trace.finish()
    assert visible(events) == source


@pytest.mark.parametrize('tail', ['{"completionState":', '```JSON\n{"title":"控制标题",',
                                 '{"completionState": True}', '{"completionState": True, "title":"控制标题"}',
                                 r'{"completion\u0053tate": True}'])
def test_acp_incomplete_control_tail_is_not_released_by_finish(tail: str) -> None:
    trace = RuntimeTrace()
    events = acp_text(trace, '公开进度。\n')
    for character in tail:
        events += acp_text(trace, character) + trace.flush()
        assert 'completionState' not in visible(events) and '控制标题' not in visible(events)
    events += trace.finish()
    assert visible(events) == '公开进度。\n'


def test_acp_control_filter_preserves_redaction_budget_and_tool_boundaries() -> None:
    trace = RuntimeTrace()
    events = []
    for character in '公开 sk-' + 'a' * 24 + ' 进度。':
        events += acp_text(trace, character) + trace.flush()
    events += acp_text(trace, '{"completionState":"artifact_completed"}') + trace.next_message()
    events += acp_text(trace, '后续工具进度。') + trace.finish()
    assert visible(events) == '公开 [已隐藏] 进度。后续工具进度。'
    acp_text(trace, '说明 {"title":"' + 'x' * MAX_TRACE_CHARS)
    assert trace._chars == MAX_TRACE_CHARS
    assert acp_text(trace, '超出限额') == []
