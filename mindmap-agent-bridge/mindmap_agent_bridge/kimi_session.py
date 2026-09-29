"""Single-use ACP JSON-RPC conversation, following OpenDesign's lifecycle.

Only public assistant prose is projected. Thought chunks become state, never
hidden reasoning text; tool/plan details come from the authoritative gateway.
"""

import asyncio
import json
import re

from .completion import completion_schema, validate_completion
from .execution import MAX_OFFER_BYTES, MAX_REPLY_BYTES, RunFailure, RunProtocolError, RunStopped, _bounded, _load
from .kimi_policy import CLI_VERSION, MODEL_ALIAS
from .public_trace import PublicTextProjection


def completion_payload(text, offer):
    decoder = json.JSONDecoder()
    # Only a terminal JSON object (optionally fenced), never prose success.
    for match in reversed(list(re.finditer(r'(?:^|\n)\s*(?:```json\s*)?(?=\{)', text))):
        candidate = text[match.end():]
        try:
            value, end = decoder.raw_decode(candidate)
            if candidate[end:].strip() not in {'', '```'}:
                continue
            return validate_completion(_load(json.dumps(value), MAX_OFFER_BYTES), offer)
        except (ValueError, TypeError, KeyError, RunProtocolError):
            continue
    raise RunProtocolError


class KimiSession:
    def __init__(self, receive, send, *, cwd, gateway):
        self.receive, self.send, self.cwd, self.gateway = receive, send, cwd, gateway
        self.session_id = None
        self._used = self._interrupted = self._finished = False
        self._next_id = self._frames = self._bytes = 0
        self._write_lock = asyncio.Lock()
        self._deadline = None
        self._text = ''
        self._state = None
        self._thinking = False
        self._tool_ids = set()
        self._terminal_tools = set()
        self._granted_tools = set()
        self._reverse_ids = set()

    async def _send(self, value):
        raw = json.dumps({'jsonrpc': '2.0', **value}, ensure_ascii=False, allow_nan=False) + '\n'
        if len(raw.encode()) > MAX_REPLY_BYTES:
            raise RunProtocolError
        async with self._write_lock:
            await _bounded(self.send(raw), 15)

    async def _emit(self, channel, *, final=False):
        if self._state is None:
            return
        try:
            events = self.trace._publish(self._state, final=final)
        except (ValueError, TypeError):
            raise RunProtocolError from None
        for event in events:
            if self._interrupted:
                raise RunStopped
            await channel.public_text(event['text'], message_id=event['messageId'], channel=event['channel'])

    async def _update(self, params, channel):
        if params.get('sessionId') != self.session_id or self._interrupted or self._finished:
            return
        update = params.get('update')
        if not isinstance(update, dict):
            raise RunProtocolError
        kind = update.get('sessionUpdate')
        if kind == 'agent_thought_chunk':
            if not self._thinking:
                await channel.thinking()
                self._thinking = True
        elif kind == 'agent_message_chunk':
            content = update.get('content')
            if not isinstance(content, dict) or content.get('type') != 'text' or not isinstance(content.get('text'), str):
                raise RunProtocolError
            self._thinking = False
            delta = content['text']
            self._text += delta
            if len(self._text) > 100_000:
                raise RunProtocolError
            if self._state is None:
                self._state = self.trace._state()
            try:
                self.trace._append(self._state, delta)
                await self._emit(channel)
            except ValueError:
                raise RunProtocolError from None
        elif kind == 'tool_call':
            tool_id = update.get('toolCallId')
            if not isinstance(tool_id, str) or len(tool_id) > 512:
                raise RunProtocolError
            if update.get('status') in {'completed', 'failed'}:
                if len(self._terminal_tools) >= 200:
                    raise RunProtocolError
                self._terminal_tools.add(tool_id)
            if tool_id not in self._tool_ids and update.get('status') in {'pending', 'in_progress'}:
                if len(self._tool_ids) >= 200:
                    raise RunProtocolError
                self._tool_ids.add(tool_id)
                await self._emit(channel, final=True)
                self._state = None
                self._text += '\n'
            # Never interpret a human-readable ACP title as a tool identity.
        elif kind == 'tool_call_update':
            if update.get('status') in {'completed', 'failed'}:
                tool_id = update.get('toolCallId')
                if not isinstance(tool_id, str) or len(tool_id) > 512 or len(self._terminal_tools) >= 200:
                    raise RunProtocolError
                self._terminal_tools.add(tool_id)
        elif kind == 'config_option_update':
            self._validate_options(update.get('configOptions'))
        elif kind == 'current_mode_update' and update.get('currentModeId') != 'default':
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')

    @staticmethod
    def _validate_options(options):
        if not isinstance(options, list):
            raise RunProtocolError
        values = {item.get('id'): item.get('currentValue') for item in options if isinstance(item, dict)}
        if values.get('model') != MODEL_ALIAS or values.get('mode') != 'default':
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')

    def _approve_once(self, params):
        if (not self.gateway.accepting or self._interrupted or self._finished
                or params.get('sessionId') != self.session_id):
            return None
        call, options = params.get('toolCall'), params.get('options')
        if not isinstance(call, dict) or not isinstance(options, list):
            return None
        identity = call.get('toolCallId')
        # Pinned 2.1.1 approval.ts/buildPermissionToolCallUpdate explicitly
        # sets request_permission.toolCall.title = req.toolName. This is NOT
        # the human-readable session/update tool_call title. Re-audit on bump.
        if (not isinstance(identity, str) or identity not in self._tool_ids
                or identity in self._terminal_tools or identity in self._granted_tools
                or call.get('title') not in self._allowed):
            return None
        once = [row.get('optionId') for row in options if isinstance(row, dict) and row.get('kind') == 'allow_once']
        if once != ['approve_once']:
            return None
        self._granted_tools.add(identity)
        return {'outcome': {'outcome': 'selected', 'optionId': 'approve_once'}}

    async def _request(self, method, params, channel=None):
        if self._interrupted:
            raise RunStopped
        self._next_id += 1
        request_id = f'mindmap-{self._next_id}'
        await self._send({'id': request_id, 'method': method, 'params': params})
        while True:
            remaining = self._deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RunFailure('AI_TIMEOUT')
            raw = await _bounded(self.receive(), min(remaining, 30) if channel is None else remaining)
            if not raw or self._interrupted:
                raise RunStopped if self._interrupted else RunProtocolError
            self._frames += 1
            self._bytes += len(raw.encode() if isinstance(raw, str) else raw)
            if self._frames > 4096 or self._bytes > 16 * MAX_OFFER_BYTES:
                raise RunProtocolError
            frame = _load(raw, MAX_OFFER_BYTES)
            if frame.get('jsonrpc') != '2.0':
                raise RunProtocolError
            if 'method' in frame:
                if (not isinstance(frame['method'], str) or not isinstance(frame.get('params', {}), dict)
                        or set(frame) - {'jsonrpc', 'id', 'method', 'params'}):
                    raise RunProtocolError
                if 'id' in frame:
                    if type(frame['id']) not in {str, int} or len(str(frame['id'])) > 200:
                        raise RunProtocolError
                    identity = (type(frame['id']), frame['id'])
                    if identity in self._reverse_ids or len(self._reverse_ids) >= 200:
                        raise RunProtocolError
                    self._reverse_ids.add(identity)
                    approved = self._approve_once(frame.get('params', {})) if (
                        channel is not None and frame['method'] == 'session/request_permission') else None
                    if approved is not None:
                        await self._send({'id': frame['id'], 'result': approved})
                        continue
                    reply = {'result': {'outcome': {'outcome': 'cancelled'}}} if frame['method'] == 'session/request_permission' else {
                        'error': {'code': -32601, 'message': 'Capability not allowed'}}
                    await self._send({'id': frame['id'], **reply})
                    raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
                if channel is not None and frame['method'] == 'session/update':
                    await self._update(frame['params'], channel)
                continue
            if (frame.get('id') != request_id or ('result' in frame) == ('error' in frame)
                    or set(frame) - {'jsonrpc', 'id', 'result', 'error'}):
                raise RunProtocolError
            if channel is not None:
                # Gate closes at terminal-frame reception, before any await.
                self.gateway.disable()
                self._finished = True
            if 'error' in frame:
                error = frame['error']
                code = error.get('code') if isinstance(error, dict) else None
                raise RunFailure('AI_PROVIDER_AUTH_FAILED' if code == -32000 else 'AI_AGENT_UNAVAILABLE')
            if not isinstance(frame['result'], dict):
                raise RunProtocolError
            return frame['result']

    async def run(self, offer, channel):
        if self._used or self._interrupted:
            raise RunProtocolError
        self._used = True
        self._deadline = asyncio.get_running_loop().time() + offer.timeout_seconds
        self.trace = PublicTextProjection(discuss=offer.intent == 'discuss', control_suffix=offer.intent != 'discuss')
        self._allowed = {f'mcp__mindmap__{tool["name"]}' for tool in offer.tools}
        initialized = await self._request('initialize', {
            'protocolVersion': 1, 'clientCapabilities': {},
            'clientInfo': {'name': 'mindmap-agent-bridge', 'version': '0.1.0'},
        })
        agent = initialized.get('agentInfo', {})
        if (initialized.get('protocolVersion') != 1 or not isinstance(agent, dict)
                or agent.get('version') != CLI_VERSION
                or initialized.get('agentCapabilities', {}).get('mcpCapabilities', {}).get('http') is not True):
            raise RunFailure('AI_CAPABILITY_UNSUPPORTED')
        created = await self._request('session/new', {
            'cwd': self.cwd, 'mcpServers': [self.gateway.description] if offer.tools else [],
        })
        self.session_id = created.get('sessionId')
        if not isinstance(self.session_id, str) or not 1 <= len(self.session_id) <= 200:
            raise RunProtocolError
        self._validate_options(created.get('configOptions'))
        instruction = ('\n仅使用提供的脑图 MCP 工具。update_plan 记录真实计划，工具之间简要说明公开进度，'
                       '不要披露隐藏推理。最终结果必须在真实工具执行成功后返回，最后单独一行输出符合以下 schema '
                       '的 JSON 对象，不加任何后缀：\n' + json.dumps(completion_schema(offer), ensure_ascii=False))
        try:
            self.gateway.accepting = True
            result = await self._request('session/prompt', {'sessionId': self.session_id,
                'prompt': [{'type': 'text', 'text': offer.prompt + instruction}]}, channel)
            if self._interrupted or result.get('stopReason') == 'cancelled':
                raise RunStopped
            if self.gateway.failure is not None:
                raise self.gateway.failure
            if result.get('stopReason') != 'end_turn':
                raise RunFailure('AI_AGENT_UNAVAILABLE')
            final = completion_payload(self._text, offer)
            await self._emit(channel, final=True)
            return final  # server still verifies actual tool completion/draft
        finally:
            self.gateway.disable()

    async def interrupt(self):
        self.gateway.disable()
        if self._interrupted or self._finished:
            return False
        self._interrupted = True
        if self.session_id:
            await self._send({'method': 'session/cancel', 'params': {'sessionId': self.session_id}})
        return True  # a request, never proof of process exit
