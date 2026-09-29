"""Public Claude text projection, before anything crosses the device link.

Raw thinking/signatures, init data, tool envelopes, usage and diagnostics stay
local. Tool/Todo details come only from the platform's real tool gateway.
"""

import dataclasses

from .public_trace import PublicTextProjection


def record(value):
    if isinstance(value, dict):
        return value
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return {}


class ClaudeTrace(PublicTextProjection):
    def __init__(self, *, discuss=False):
        super().__init__(discuss=discuss)
        self.streaming = False
        self.last_wrapper = None

    @staticmethod
    def _thinking(state):
        if state['thinking']:
            return []
        state['thinking'] = True
        return [{'kind': 'thinking'}]

    def consume(self, message):
        value = record(message)
        if value.get('parent_tool_use_id'):
            return []
        kind = value.get('type') or type(message).__name__
        if kind in {'stream_event', 'StreamEvent'}:
            event = record(value.get('event'))
            if event.get('type') == 'message_start':
                self.streaming = True
                self._state(record(event.get('message')).get('id'))
            state = self.current or self._state()
            delta = record(event.get('delta'))
            if delta.get('type') == 'text_delta' and not state['complete']:
                self._append(state, delta.get('text'))
                return self._publish(state)
            if delta.get('type') == 'thinking_delta':
                return self._thinking(state)
            if event.get('type') in {'content_block_stop', 'message_stop'}:
                return self._publish(state, final=event['type'] == 'message_stop')
        if kind in {'assistant', 'AssistantMessage'}:
            body = record(value.get('message')) or value
            blocks = [record(block) for block in body.get('content', [])]
            text = ''.join(block['text'] for block in blocks if isinstance(block.get('text'), str))
            if body.get('id'):
                state = self._state(body['id'])
            elif self.streaming and self.current:
                state = self.current
            elif text == self.last_wrapper:
                return []
            else:
                state = self._state()
            self.last_wrapper = text
            self.streaming = False
            output = []
            if not state['complete']:
                if text.startswith(state['raw']):
                    self._append(state, text[len(state['raw']):])
                state['complete'] = True
                output += self._publish(state, final=True)
            if any('thinking' in block for block in blocks):
                output += self._thinking(state)
            return output
        return []
