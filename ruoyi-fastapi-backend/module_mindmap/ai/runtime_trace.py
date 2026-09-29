"""Bounded, user-visible runtime events, following OpenDesign's stream adapters.

Protocol messages never mutate a mind map here. Only the existing tool gateway
can emit draft_changed. Hidden thinking is reduced to a state indicator.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from typing import Any

TRACE_TYPES = frozenset({'assistant_delta', 'thinking_state', 'thinking_summary', 'todo_updated'})
MAX_DETAIL_DEPTH = 4
MAX_TRACE_CHARS = 100_000
TRACE_BATCH_CHARS = 256
TRACE_BATCH_SECONDS = 0.12
MAX_ACP_TOOL_CALLS = 512
MAX_ACP_TOOL_ID_CHARS = 512
_SECRET_KEY = re.compile(r'password|secret|token|credential|authorization|api.?key|cookie', re.I)
# Credentials use ASCII word boundaries. Unicode \b treats adjacent Chinese
# prose as part of the token and would miss “密钥sk-...” in both batch and stream.
_SECRET_VALUE = re.compile(r'(?a:\b)(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+)', re.I)
_CONTROL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')
# An unfinished credential OR any unfinished prefix of its marker. Keep this
# suffix private across batching, time-based flushes and provider deltas.
_SECRET_TAIL = re.compile(r'(?a:\b)(?:sk-[A-Za-z0-9_-]*|Bearer(?:\s+\S*)?|s|sk|b|be|bea|bear|beare)\Z', re.I)
_JSON_CONTENT = re.compile(r'(?<!\\)"content"\s*:\s*"((?:\\.|[^"\\])*)', re.S)
_HIGH_SURROGATE_START = 0xD800
_HIGH_SURROGATE_END = 0xDBFF


def public_text(value: Any, limit: int = 4000) -> str:
    if not isinstance(value, str):
        return ''
    return _SECRET_VALUE.sub('[已隐藏]', _CONTROL.sub('', value))[:limit]


def display_value(value: Any, depth: int = 0) -> Any:
    """A bounded detail projection, not a dump of provider or process state."""
    if depth > MAX_DETAIL_DEPTH:
        return '…'
    if isinstance(value, dict):
        return {
            str(key)[:80]: '[已隐藏]' if _SECRET_KEY.search(str(key)) else display_value(item, depth + 1)
            for key, item in list(value.items())[:24]
            if str(key) not in {'artifact', 'document', 'sourceProjection', 'previewState', 'initialState'}
        }
    if isinstance(value, (list, tuple)):
        return [display_value(item, depth + 1) for item in value[:12]]
    if isinstance(value, str):
        return public_text(value, 500)
    if value is None or type(value) in (bool, int, float):
        return value
    return None


def detail_text(value: Any) -> str:
    return json.dumps(display_value(value), ensure_ascii=False, default=str)[:6000]


def normalize_todos(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result = []
    for index, item in enumerate(value[:40]):
        if not isinstance(item, dict):
            continue
        text = public_text(item.get('content', item.get('step', item.get('description'))), 500)
        if not text.strip():
            continue
        status = item.get('status', 'pending')
        if not isinstance(status, str) or status not in {'pending', 'in_progress', 'completed', 'cancelled'}:
            status = 'pending'
        result.append({'id': public_text(str(item.get('id') or index + 1), 80), 'content': text, 'status': status})
    return result


def as_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if callable(getattr(value, 'model_dump', None)):
        return value.model_dump(by_alias=True)
    return vars(value) if hasattr(value, '__dict__') else {}


def _closed_object_end(value: str) -> int | None:
    """Find a balanced example even when its values are not JSON (True/None)."""
    depth, quoted, escaped = 0, False, False
    for index, char in enumerate(value):
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _has_completion_key(value: str) -> bool:
    # Also recognize escaped keys in malformed control objects. Only JSON
    # strings followed by a colon qualify, not mentions inside prose values.
    return any(json.loads(match.group(1)) == 'completionState' for match in re.finditer(
        r'("(?:\\["\\/bfnrt]|\\u[0-9a-fA-F]{4}|[^"\\\x00-\x1f])*")\s*:', value,
    ))


@dataclasses.dataclass
class _CompletionTail:
    """Keep ACP's trailing completion contract out of the public transcript.

    Prose can precede the contract in the same message. Hold JSON candidates
    until their top-level keys are known, without removing ordinary examples.
    RuntimeTrace's raw-input budget also bounds this buffer.
    """

    buffer: str = ''
    hidden: bool = False

    def _object_offset(self) -> int | None:
        if self.buffer.startswith('{'):
            return 0
        prefix = self.buffer.lower()
        if prefix != '```json' and '```json'.startswith(prefix):
            return None  # The fence is still arriving.
        if not prefix.startswith('```json'):
            return -1
        candidate = self.buffer[7:].lstrip()
        if not candidate:
            return None
        return len(self.buffer) - len(candidate) if candidate.startswith('{') else -1

    def project(self, text: str, *, final: bool = False) -> str:
        if self.hidden:
            return ''
        self.buffer += text
        output = []
        while self.buffer:
            marker = re.search(r'[{`]', self.buffer)
            if marker is None:
                output.append(self.buffer)
                self.buffer = ''
                break
            output.append(self.buffer[:marker.start()])
            self.buffer = self.buffer[marker.start():]
            offset = self._object_offset()
            if offset is None:
                if final:
                    output.append(self.buffer)
                    self.buffer = ''
                break
            candidate = self.buffer[offset:] if offset >= 0 else ''
            body = candidate[1:].lstrip()
            if offset < 0 or (body and body[0] not in {'"', '}'}) or (final and not body):
                # Inline code, non-JSON fences and prose such as {name}.
                output.append(self.buffer[:1])
                self.buffer = self.buffer[1:]
                continue
            try:
                value, end = json.JSONDecoder().raw_decode(candidate)
            except (ValueError, RecursionError):
                end = _closed_object_end(candidate)
                if end is None:
                    if final:
                        self.buffer = ''  # Never flush a truncated control object.
                    break
                # A closed Python/JS example is not a truncated JSON contract.
                # Keep malformed control objects private, but release examples
                # and resume streaming the prose that follows them.
                value = {'completionState': None} if _has_completion_key(candidate[:end]) else None
            if isinstance(value, dict) and 'completionState' in value:
                self.hidden = True
                self.buffer = ''  # Also hide a closing fence in this/later deltas.
                break
            output.append(self.buffer[:offset + end])
            self.buffer = self.buffer[offset + end:]
        return ''.join(output)


@dataclasses.dataclass
class _TextState:
    """Message-local format detection and append-only, boundary-safe redaction."""

    structured: bool = False
    mode: str = 'prefix'
    buffer: str = ''
    shown: int = 0
    tail: str = ''
    previous_word: bool = False
    completion_tail: _CompletionTail | None = None

    def _json_text(self) -> str:
        if not self.structured:
            self.buffer = ''  # Editing contracts are never conversation text.
            return ''
        match = _JSON_CONTENT.search(self.buffer)
        if not match:
            return ''
        fragment = match.group(1)
        for trim in range(7):
            try:
                decoded = json.loads('"' + (fragment[:-trim] if trim else fragment) + '"')
            except ValueError:  # One incomplete JSON escape, at most six chars.
                continue
            # json.loads accepts a lone high surrogate. Wait for its low
            # surrogate instead of publishing invalid UTF-8.
            if decoded and _HIGH_SURROGATE_START <= ord(decoded[-1]) <= _HIGH_SURROGATE_END:
                decoded = decoded[:-1]
            text, self.shown = decoded[self.shown:], len(decoded)
            return text
        return ''

    def project(self, text: str, *, final: bool = False) -> str:
        if self.mode != 'plain':
            self.buffer += text
            if self.mode == 'prefix':
                prefix = self.buffer.lstrip().lower()
                if not prefix or (prefix != '```json' and '```json'.startswith(prefix)):
                    if not final:
                        return ''
                    self.mode = 'plain'
                else:
                    self.mode = 'json' if prefix.startswith(('{', '```json')) else 'plain'
                if self.mode == 'plain':
                    text, self.buffer = self.buffer, ''
            if self.mode == 'json':
                text = self._json_text()
        if self.mode == 'plain' and self.completion_tail is not None:
            text = self.completion_tail.project(text, final=final)
        # Decode JSON BEFORE redaction: Bearer tokens must not eat JSON quotes,
        # and escaped characters can form a credential only after decoding.
        # A neutral sentinel retains the original regex word boundary without
        # letting an already-published final 's'/'b' start a new secret match.
        value = ('x' if self.previous_word else ' ') + self.tail + _CONTROL.sub('', text)
        match = None if final else _SECRET_TAIL.search(value)
        boundary = match.start() if match else len(value)
        safe, self.tail = value[:boundary], value[boundary:]
        output = _SECRET_VALUE.sub('[已隐藏]', safe)[1:]
        self.previous_word = bool(re.match(r'(?a:\w)', safe[-1:]))
        return output


@dataclasses.dataclass
class _AcpToolState:
    call_id: str
    started: float
    name: str = 'CLI tool'
    raw_name: str = ''
    approval_name: str = ''
    tool_input: Any = None
    tool_output: str | None = None
    hidden: bool = False
    thinking: bool = False
    terminal: bool = False
    started_call: bool = False
    approved: bool = False
    shown: bool = False
    signature: str = ''
    published: float = 0.0


def _acp_name(update: dict) -> str:
    # Kimi's title can contain a key argument after ': '. Keep that argument
    # out of the label; the bounded details carry tool arguments separately.
    name = update.get('name') or update.get('title')
    if not isinstance(name, str):
        return ''
    name = name.split(': ', 1)[0]
    return name if len(name) <= MAX_ACP_TOOL_ID_CHARS else 'CLI tool'


class RuntimeTrace:
    """Normalize partial/final envelopes once, with bounded text batching."""

    def __init__(
        self, *, thinking_summary: bool = False, structured_message: bool = False,
        acp_gateway_tools: tuple[str, ...] = (),
    ) -> None:
        self.thinking_summary = thinking_summary
        self.structured_message = structured_message
        self._texts: dict[tuple[str, str], _TextState] = {}
        self.message_id = 'message-1'
        self._counter = 0
        self._streamed: set[str] = set()
        self._pending: dict[tuple[str, str], str] = {}
        self._last_flush = 0.0
        self._chars = 0
        self._thinking = False
        self._has_stream_message = False
        self._last_fallback_text = None
        self._native_streamed = False
        self._acp_tools: dict[str, _AcpToolState] = {}
        self._acp_gateway_names = frozenset(
            alias for name in acp_gateway_tools for alias in (f'mcp__mindmap__{name}', f'mindmap/{name}')
        )

    def text(
        self, text: Any, *, message_id: str | None = None, summary: bool = False, plain: bool = False,
        control_suffix: bool = False,
    ) -> list[tuple[str, dict]]:
        if not isinstance(text, str):
            return []
        text = _CONTROL.sub('', text)[:MAX_TRACE_CHARS - self._chars]
        if not text or self._chars >= MAX_TRACE_CHARS:
            return []
        key = message_id or self.message_id
        # Bound RAW input too, including held prefixes, JSON and credentials.
        self._chars += len(text)
        self._streamed.add(key)  # A final provider wrapper must not replay held input.
        event_type = 'thinking_summary' if summary else 'assistant_delta'
        state = self._texts.setdefault((event_type, key), _TextState(
            structured=self.structured_message,
            mode='plain' if plain or (control_suffix and not self.structured_message) else 'prefix',
            completion_tail=_CompletionTail() if control_suffix else None,
        ))
        self._queue_text(event_type, key, state, state.project(text))
        if (
            sum(map(len, self._pending.values())) >= TRACE_BATCH_CHARS
            or time.monotonic() - self._last_flush >= TRACE_BATCH_SECONDS
        ):
            return self.flush()
        return []

    def _queue_text(self, kind: str, key: str, state: _TextState, text: str) -> None:
        if text:
            pending_key = (kind, f'{key}:content' if state.mode == 'json' else key)
            self._pending[pending_key] = self._pending.get(pending_key, '') + text

    def finish(self, message_id: str | None = None) -> list[tuple[str, dict]]:
        """Finalize only at a real message/turn boundary, never on a timer."""
        for (kind, key), state in self._texts.items():
            if message_id is None or key in {message_id, f'{message_id}:summary'}:
                self._queue_text(kind, key, state, state.project('', final=True))
        return self.flush()

    def thinking(self) -> list[tuple[str, dict]]:
        if self._thinking:
            return []
        self._thinking = True
        return [
            ('thinking_state', {'stage': 'thinking', 'visibility': 'summary' if self.thinking_summary else 'status'})
        ]

    def flush(self) -> list[tuple[str, dict]]:
        """Drain safe output only; ambiguous prefixes/credentials remain private."""
        output = [
            (
                kind,
                {
                    'messageId': key,
                    'text': text[offset : offset + 4000],
                    'visibility': 'summary' if kind == 'thinking_summary' else 'visible',
                },
            )
            for (kind, key), text in self._pending.items()
            for offset in range(0, len(text), 4000)
        ]
        self._pending.clear()
        self._last_flush = time.monotonic()
        return output

    def next_message(self) -> list[tuple[str, dict]]:
        """Flush before a tool boundary so subsequent text keeps event order."""
        output = self.finish(self.message_id)
        self._counter += 1
        self.message_id = f'message-{self._counter + 1}'
        self._thinking = False
        return output

    def native(self, event: Any) -> list[tuple[str, dict]]:
        """Agno public content only; reasoning/provider metadata never leave here."""
        record = as_record(event)
        kind = record.get('event')
        output = []
        if record.get('reasoning_content') or kind in {'ReasoningStarted', 'ReasoningContentDelta'}:
            output += self.thinking()
        if kind == 'RunContent' and isinstance(record.get('content'), str) and record['content']:
            self._native_streamed = True
            output += self.text(record['content'])
        elif kind == 'RunCompleted' and not self._native_streamed:
            output += self.text(record.get('content'))
            self._native_streamed = True
        if kind in {'RunContentCompleted', 'RunCompleted'}:
            output += self.finish() if kind == 'RunCompleted' else self.flush()
        return output

    def claude(self, message: Any) -> list[tuple[str, dict]]:
        record = as_record(message)
        kind = record.get('type') or type(message).__name__
        if kind in {'stream_event', 'StreamEvent'}:
            event = as_record(record.get('event'))
            if event.get('type') == 'message_start':
                output = self.finish(self.message_id)
                self._has_stream_message = True
                self._counter += 1
                self.message_id = str(as_record(event.get('message')).get('id') or f'message-{self._counter}')
                self._thinking = False
                return output
            delta = as_record(event.get('delta'))
            if delta.get('type') == 'text_delta':
                return self.text(delta.get('text'))
            if delta.get('type') == 'thinking_delta':
                events = self.thinking()
                if self.thinking_summary:
                    events += self.text(delta.get('thinking'), message_id=f'{self.message_id}:summary', summary=True)
                return events
            if event.get('type') == 'message_stop':
                return self.finish(self.message_id)
            return self.flush() if event.get('type') == 'content_block_stop' else []
        if kind in {'assistant', 'AssistantMessage'}:
            body = as_record(record.get('message')) or record
            output = []
            blocks = [as_record(block) for block in body.get('content', [])]
            text = ''.join(block.get('text', '') for block in blocks if isinstance(block.get('text'), str))
            # The Python SDK names the provider's message.id `message_id`.
            # Match wrappers to their streamed message before using the
            # ID-less compatibility fallback; equal prose is not identity.
            provider_id = body.get('id') or body.get('message_id')
            key = str(provider_id or self.message_id)
            if not provider_id and not self._has_stream_message:
                if text != self._last_fallback_text:
                    self._counter += 1
                key = f'fallback-{self._counter}'
                self._last_fallback_text = text
            if key not in self._streamed:
                output += self.text(text, message_id=key)
            for block in blocks:
                if 'thinking' in block:
                    output += self.thinking()
            self._has_stream_message = False
            return output + self.finish(key)
        return []

    def codex(self, method: str, payload: Any) -> list[tuple[str, dict]]:
        data = as_record(payload)
        item_id = str(data.get('itemId', data.get('item_id', self.message_id)))
        if method == 'item/agentMessage/delta':
            return self.text(data.get('delta'), message_id=item_id)
        if method == 'item/reasoning/summaryTextDelta':
            return self.text(data.get('delta'), message_id=f'{item_id}:summary', summary=True)
        if method == 'item/reasoning/textDelta':
            return self.thinking()
        if method == 'turn/plan/updated':
            return [*self.flush(), ('todo_updated', {'todos': normalize_todos(data.get('plan')), 'origin': 'agent'})]
        if method == 'item/completed':
            item = as_record(data.get('item'))
            item_id = str(item.get('id', item_id))
            if item.get('type') == 'agentMessage' and item_id not in self._streamed:
                return self.text(item.get('text'), message_id=item_id) + self.finish(item_id)
            return self.finish(item_id)
        if method == 'turn/completed':
            return self.finish()
        return self.flush() if method == 'item/started' else []

    def acp(self, update: dict[str, Any]) -> list[tuple[str, dict]]:
        kind = update.get('sessionUpdate')
        content = as_record(update.get('content'))
        if kind == 'agent_message_chunk' and content.get('type') in (None, 'text'):
            return self.text(content.get('text'), control_suffix=True)
        if kind == 'agent_thought_chunk':
            return self.thinking()
        if kind == 'plan':
            return [
                *self.flush(),
                ('todo_updated', {'todos': normalize_todos(update.get('entries')), 'origin': 'agent'}),
            ]
        if kind in {'tool_call', 'tool_call_update'}:
            return self._acp_tool(update)
        return []

    def approve_acp_tool_once(self, tool_call: dict) -> bool:
        """Narrow CLI metadata check, NOT a sandbox or a substitute for MCP auth."""
        call_id = tool_call.get('toolCallId')
        state = self._acp_tools.get(call_id) if isinstance(call_id, str) else None
        # No title-only permission grants, bare names, suffix matches, or
        # session-wide approvals. The caller must also validate session/phase.
        if (state is None or not state.started_call or state.terminal or state.approved or state.thinking
                or not state.approval_name or state.raw_name != state.approval_name
                or _acp_name(tool_call) != state.raw_name):
            return False
        state.approved = True
        return True

    def _acp_tool(self, update: dict) -> list[tuple[str, dict]]:  # noqa: PLR0912
        raw_id = update.get('toolCallId')
        if not isinstance(raw_id, str) or not raw_id.strip() or len(raw_id) > MAX_ACP_TOOL_ID_CHARS:
            return []
        state = self._acp_tools.get(raw_id)
        if state is not None and state.terminal:
            return []  # Terminal state cannot be replayed or reopened by a late frame.
        output = self.flush()
        if state is None:
            if len(self._acp_tools) >= MAX_ACP_TOOL_CALLS:
                return output
            output += self.next_message()
            # Adapter IDs can embed paths/tokens. Only this opaque run-local ID
            # leaves memory, while the original remains the correlation key.
            state = _AcpToolState(f'acp:tool-{len(self._acp_tools) + 1}', time.monotonic())
            if update.get('sessionUpdate') == 'tool_call' and _acp_name(update) in self._acp_gateway_names:
                state.approval_name = _acp_name(update)
            self._acp_tools[raw_id] = state
        state.started_call |= update.get('sessionUpdate') == 'tool_call'
        name = _acp_name(update)
        if name:
            state.raw_name = name
            state.name = public_text(name, 80) if re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}', name) else 'CLI tool'
        state.thinking |= update.get('kind') == 'think' or name.lower() in {'think', 'thinking', 'reasoning'}
        state.hidden |= state.thinking or name in self._acp_gateway_names
        status = update.get('status')
        state.terminal = status in {'completed', 'failed', 'cancelled'}
        if state.hidden:
            # The authoritative MCP gateway reports draft calls itself. Sticky
            # classification also hides subsequent title-less result frames.
            if state.thinking:
                output += self.thinking()
            if not state.shown:
                return output
            state.name, state.tool_input, state.tool_output = 'CLI tool', '[内容不展示]', '[内容不展示]'
        else:
            if 'rawInput' in update:
                value = display_value(update['rawInput'])
                state.tool_input = display_value({**state.tool_input, **value}) if (
                    isinstance(state.tool_input, dict) and isinstance(value, dict)
                ) else value
            if 'rawOutput' in update or 'content' in update:
                state.tool_output = detail_text(update.get('rawOutput', update.get('content')))
        if not state.started_call and not state.terminal:
            # An orphan progress update is evidence of data, not of when the
            # tool began. Retain it for a later real start/terminal without
            # fabricating a start event and a potentially wrong Todo binding.
            return output
        payload = {'callId': state.call_id, 'toolName': state.name, 'origin': 'agent'}
        if state.tool_input is not None:
            payload['toolInput'] = detail_text(state.tool_input)
        if state.tool_output is not None:
            payload['toolOutput'] = state.tool_output
        signature = json.dumps(payload, ensure_ascii=False)
        now = time.monotonic()
        if not state.terminal and state.shown and (
            signature == state.signature or (not state.hidden and now - state.published < TRACE_BATCH_SECONDS)
        ):
            return output
        state.shown, state.signature, state.published = True, signature, now
        event_type = 'tool_started'
        if state.terminal:
            event_type = 'tool_completed' if status == 'completed' else 'tool_failed'
            if state.started_call:
                payload['durationMs'] = max(0, int((now - state.started) * 1000))
            if status == 'cancelled':
                payload['errorMessage'] = '工具调用已取消'
        return [*output, (event_type, payload)]
