"""Single-turn Codex app-server stdio protocol, with device-owned tools only.

Follows OpenDesign's initialize → thread/start → turn/start lifecycle, but
uses explicit dynamic tool callbacks instead of exposing a shell or local
design files. The process launcher remains responsible for authentication,
CLI/config isolation, budget policy, and proving process exit. This module
does not advertise a runnable device or grant consent to execute a model.
"""

import asyncio
import json
import re
from collections import deque
from pathlib import Path

from .codex_trace import CodexTrace
from .completion import completion_schema, validate_completion
from .execution import MAX_OFFER_BYTES, MAX_REPLY_BYTES, RunFailure, RunProtocolError, RunStopped, _bounded, _load

MAX_FRAMES = 4096
MAX_EARLY_EVENTS = 128
MAX_TOOL_CALLS = 200
INSTRUCTIONS = (
    '你是受限的脑图 Agent。只能调用提供的 mindmap_ 工具。不要调用 shell、文件、浏览器、'
    'MCP、插件、子 Agent 或其他能力。用 mindmap_update_plan 记录真实计划；工具间可说明公开进度，'
    '不披露隐藏推理。按输出 schema 返回最终结果；脑图结果必须先通过真实工具完成。'
)
FORBIDDEN_ITEMS = frozenset({'commandExecution', 'fileChange', 'mcpToolCall', 'webSearch',
                            'imageGeneration', 'collabAgentToolCall', 'browserToolCall'})


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        raise RunProtocolError
    return value


def _failure(error):
    # Raw messages may contain prompts, credentials or provider diagnostics.
    detail = error.get('codexErrorInfo') if isinstance(error, dict) else None
    if detail == 'unauthorized':
        return RunFailure('AI_PROVIDER_AUTH_FAILED')
    if detail in ('usageLimitExceeded', 'rateLimitExceeded'):
        return RunFailure('AI_RATE_LIMITED')
    return RunFailure('AI_AGENT_UNAVAILABLE')


class CodexSession:
    """`receive` returns one JSON line; `send` writes one JSON line atomically."""

    def __init__(self, receive, send, *, cwd, policy=None):
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise RunProtocolError
        self.receive, self.send, self.cwd = receive, send, cwd
        # Only a trusted local driver supplies this policy, never a run offer.
        self.policy = policy
        self.thread_id = self.turn_id = None
        self._write_lock = asyncio.Lock()
        self._next_id = 0
        self._frames = self._bytes = 0
        self._early = deque()
        self._requests = set()
        self._calls = set()
        self._used = False
        self._interrupted = False
        self._finished = False
        self._deadline = None

    async def _send(self, frame):
        try:
            raw = json.dumps(frame, ensure_ascii=False, allow_nan=False) + '\n'
            if len(raw.encode()) > MAX_REPLY_BYTES:
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise RunProtocolError from None
        async with self._write_lock:
            await _bounded(self.send(raw), 15)

    def _remaining(self):
        remaining = self._deadline - asyncio.get_running_loop().time() if self._deadline is not None else 30
        if remaining <= 0:
            raise RunFailure('AI_TIMEOUT')
        return remaining

    async def _read(self, timeout=30):
        # Startup RPCs are short; a model may legitimately stay silent during
        # a longer reasoning phase. Active reads use the run deadline instead
        # of incorrectly treating 30 seconds of silence as a broken transport.
        remaining = self._remaining()
        try:
            raw = await _bounded(self.receive(), min(timeout, remaining) if timeout is not None else remaining)
        except asyncio.TimeoutError:
            raise RunFailure('AI_TIMEOUT') from None
        if not isinstance(raw, (str, bytes)) or not raw:
            raise RunProtocolError
        self._frames += 1
        self._bytes += len(raw.encode() if isinstance(raw, str) else raw)
        if self._frames > MAX_FRAMES or self._bytes > 8 * MAX_OFFER_BYTES:
            raise RunProtocolError
        return _load(raw, MAX_OFFER_BYTES)

    async def _reject(self, frame):
        request_id = frame.get('id')
        if type(request_id) not in {str, int} or (isinstance(request_id, str) and len(request_id) > 200):
            raise RunProtocolError
        await self._send({'id': request_id, 'error': {'code': -32601, 'message': 'Capability not allowed'}})
        raise RunProtocolError

    async def _request(self, method, params):
        if self._interrupted:
            raise RunStopped
        self._next_id += 1
        request_id = f'mindmap-{self._next_id}'
        await self._send({'id': request_id, 'method': method, 'params': params})
        while True:
            if self._interrupted:
                raise RunStopped
            frame = await self._read()
            if 'method' in frame and 'id' in frame and method != 'turn/start':
                # Tool calls are legal only after this turn is bound.
                await self._reject(frame)
            if 'method' in frame and 'id' in frame:
                if len(self._early) >= MAX_EARLY_EVENTS:
                    raise RunProtocolError
                self._early.append(frame)
                continue
            if 'id' in frame:
                if frame['id'] != request_id or ('result' in frame) == ('error' in frame):
                    raise RunProtocolError
                if 'error' in frame:
                    raise _failure(frame['error'])
                if not isinstance(frame['result'], dict):
                    raise RunProtocolError
                return frame['result']
            if not isinstance(frame.get('method'), str) or not isinstance(frame.get('params', {}), dict):
                raise RunProtocolError
            # A very fast turn can publish notifications before turn/start's
            # response. Preserve order in a bounded buffer, then fence by IDs.
            if len(self._early) >= MAX_EARLY_EVENTS:
                raise RunProtocolError
            self._early.append(frame)

    def _bound(self, params):
        return isinstance(params, dict) and params.get('threadId') == self.thread_id and params.get('turnId') == self.turn_id

    async def interrupt(self):
        """Request stop; this is NOT proof of exit and never sends a stopped ACK."""
        if self._interrupted or self._finished:
            return False
        self._interrupted = True
        if self.thread_id and self.turn_id:
            self._next_id += 1
            await self._send({'id': f'mindmap-{self._next_id}', 'method': 'turn/interrupt',
                              'params': {'threadId': self.thread_id, 'turnId': self.turn_id}})
        return True

    async def _tool(self, frame, channel, allowed):
        params = frame.get('params')
        request_id = frame.get('id')
        if (frame.get('method') != 'item/tool/call' or not self._bound(params)
                or type(request_id) not in {str, int} or len(str(request_id)) > 200
                or params.get('namespace') is not None or params.get('tool') not in allowed
                or not isinstance(params.get('arguments'), dict)):
            await self._reject(frame)
        call_id = _identity(params.get('callId'))
        if request_id in self._requests or call_id in self._calls or len(self._calls) >= MAX_TOOL_CALLS:
            await self._reject(frame)
        self._requests.add(request_id)
        self._calls.add(call_id)
        result = await channel.tool(allowed[params['tool']], params['arguments'])
        if self._interrupted:
            raise RunStopped
        if not isinstance(result, dict):
            raise RunProtocolError
        await self._send({'id': request_id, 'result': {
            'contentItems': [{'type': 'inputText', 'text': json.dumps(result, ensure_ascii=False, allow_nan=False)}],
            'success': result.get('ok') is True,
        }})

    async def run(self, offer, channel):
        if self._used or self._interrupted or offer.agent_key != 'codex':
            raise RunProtocolError
        self._used = True
        self._deadline = asyncio.get_running_loop().time() + offer.timeout_seconds
        allowed = {f'mindmap_{tool["name"]}': tool['name'] for tool in offer.tools}
        trace = CodexTrace(discuss=offer.intent == 'discuss')
        initialized = await self._request('initialize', {
            'clientInfo': {'name': 'mindmap-agent-bridge', 'version': '0.1.0'},
            'capabilities': {'experimentalApi': True},
        })
        await self._send({'method': 'initialized', 'params': {}})
        if self.policy is not None:
            await self.policy.prepare(self, offer, initialized)
        thread = await self._request('thread/start', {
            'cwd': self.cwd, 'model': offer.model_ref, 'approvalPolicy': 'never', 'sandbox': 'read-only',
            'ephemeral': True, 'baseInstructions': INSTRUCTIONS, 'developerInstructions': INSTRUCTIONS,
            'dynamicTools': [{'type': 'function', 'name': f'mindmap_{tool["name"]}',
                              'description': tool['description'], 'inputSchema': tool['inputSchema'],
                              'deferLoading': False} for tool in offer.tools],
        })
        self.thread_id = _identity(thread.get('thread', {}).get('id') if isinstance(thread.get('thread'), dict) else None)
        if self.policy is not None:
            await self.policy.before_turn(self, offer, thread)
        response = await self._request('turn/start', {
            'threadId': self.thread_id, 'input': [{'type': 'text', 'text': offer.prompt}],
            'cwd': self.cwd, 'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False},
            'summary': 'concise', 'outputSchema': completion_schema(offer),
        })
        self.turn_id = _identity(response.get('turn', {}).get('id') if isinstance(response.get('turn'), dict) else None)
        final = None
        while not self._interrupted:
            self._remaining()
            frame = self._early.popleft() if self._early else await self._read(timeout=None)
            if self._interrupted:
                raise RunStopped
            if 'id' in frame:
                if 'method' not in frame:
                    raise RunProtocolError
                await self._tool(frame, channel, allowed)
                continue
            method, params = frame.get('method'), frame.get('params', {})
            if not isinstance(method, str) or not isinstance(params, dict):
                raise RunProtocolError
            if method == 'turn/completed':
                turn = params.get('turn')
                if params.get('threadId') != self.thread_id or not isinstance(turn, dict) or turn.get('id') != self.turn_id:
                    continue
                self._finished = True
                if turn.get('status') != 'completed':
                    raise _failure(turn.get('error'))
                if final is None:
                    raise RunProtocolError
                if self.policy is not None:
                    self.policy.finish()
                return final
            if not self._bound(params):
                continue
            if self.policy is not None:
                self.policy.observe(method, params)
            item = params.get('item', {})
            if method in {'item/started', 'item/completed'}:
                if not isinstance(item, dict) or item.get('type') in FORBIDDEN_ITEMS:
                    raise RunProtocolError
                if item.get('type') == 'agentMessage' and method == 'item/completed' and item.get('phase') in {None, 'final_answer'}:
                    text = item.get('text', '')
                    if item.get('phase') == 'final_answer' or (isinstance(text, str) and text.lstrip().startswith('{')):
                        if final is not None:
                            raise RunProtocolError
                        try:
                            final = validate_completion(_load(text, MAX_OFFER_BYTES), offer)
                        except (ValueError, TypeError, KeyError):
                            raise RunProtocolError from None
            try:
                events = trace.consume(method, params)
            except (ValueError, TypeError, KeyError):
                raise RunProtocolError from None
            for event in events:
                if self._interrupted:
                    raise RunStopped
                if event['kind'] == 'thinking':
                    await channel.thinking()
                else:
                    await channel.public_text(event['text'], message_id=event['messageId'], channel=event['channel'])
        raise RunStopped
