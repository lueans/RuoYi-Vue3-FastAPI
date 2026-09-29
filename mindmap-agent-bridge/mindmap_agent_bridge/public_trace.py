"""Bounded public-text projection with incremental credential redaction."""

import json
import re

from .completion_text import completion_prose

LIMIT = 100_000
# Match token boundaries next to Chinese prose before anything leaves the device.
_SECRET = re.compile(r'(?a:\b)(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+)', re.I)


class PublicTextProjection:
    def __init__(self, *, discuss=False, control_suffix=False):
        self.discuss = discuss
        self.control_suffix = control_suffix
        self.current = None
        self.counter = 0
        self.states = {}
        self.chars = 0

    def _state(self, provider_id=None):
        if not provider_id:
            provider_id = f'local-{self.counter + 1}'
        if provider_id not in self.states:
            self.counter += 1
            if self.counter > 1000:
                raise ValueError('Message count exceeded limit')
            self.states[provider_id] = {'id': f'message-{self.counter}', 'raw': '', 'shown': '',
                                        'complete': False, 'thinking': False}
        self.current = self.states[provider_id]
        return self.current

    def _append(self, state, text):
        if not isinstance(text, str):
            return
        self.chars += len(text)
        if self.chars > LIMIT:
            raise ValueError('Public stream exceeded limit')
        state['raw'] += text

    def _publish(self, state, *, final=False):
        value = state['raw']
        if self.control_suffix:
            value = completion_prose(value, final=final)
        prefix = value.lstrip().lower()
        # A whitespace-only delta or split fence has not established the
        # message format yet. Publishing it would break append-only content
        # projection when the next delta reveals a structured response.
        if not final and (not prefix or (prefix != '```json' and '```json'.startswith(prefix))):
            return []
        if not self.control_suffix and prefix.startswith(('{', '```json')):
            if not self.discuss:
                return []
            match = re.search(r'(?<!\\)"content"\s*:\s*"((?:\\.|[^"\\])*)', value, re.S)
            if not match:
                return []
            fragment = match.group(1)
            for trim in range(7):
                try:
                    value = json.loads('"' + (fragment[:-trim] if trim else fragment) + '"')
                    break
                except ValueError:
                    value = ''
        value = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', value)
        if not final:
            # Keep the unfinished last token, including split sk-/Bearer
            # credentials, until a separator or actual message boundary arrives.
            boundary = max(value.rfind(' '), value.rfind('\n'), value.rfind('。'), value.rfind('，'))
            value = value[:boundary + 1] if boundary >= 0 else ''
            if value.rstrip().lower().endswith('bearer'):
                value = value[:value.lower().rfind('bearer')]
        value = _SECRET.sub('[已隐藏]', value)
        if not value.startswith(state['shown']):
            return []
        delta = value[len(state['shown']):]
        state['shown'] = value
        return [{'kind': 'public_text', 'text': delta[offset:offset + 4000], 'messageId': state['id'],
                 'channel': 'assistant'} for offset in range(0, len(delta), 4000)]
