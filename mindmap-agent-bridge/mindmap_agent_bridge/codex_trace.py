"""Codex app-server public projection; never forward raw reasoning or IDs."""

from .public_trace import PublicTextProjection


class CodexTrace(PublicTextProjection):
    def _item(self, item_id, *, summary_index=None):
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 200:
            raise ValueError('Invalid item identity')
        if summary_index is not None and (type(summary_index) is not int or not 0 <= summary_index < 100):
            raise ValueError('Invalid summary index')
        return self._state((item_id, summary_index))

    def _output(self, state, *, final=False, summary=False):
        result = self._publish(state, final=final)
        if summary:
            for event in result:
                event['channel'] = 'thinking_summary'
        return result

    def consume(self, method, params):
        if not isinstance(params, dict):
            return []
        if method == 'item/agentMessage/delta':
            state = self._item(params.get('itemId'))
            if state['complete']:
                return []
            self._append(state, params.get('delta'))
            # A phase-less item may turn out to be a structured final answer.
            # Buffer it until a public commentary phase or completion is known.
            if state.get('phase') == 'commentary':
                return self._output(state)
            return []
        if method == 'item/reasoning/summaryTextDelta':
            state = self._item(params.get('itemId'), summary_index=params.get('summaryIndex', 0))
            if state['complete']:
                return []
            self._append(state, params.get('delta'))
            return self._output(state, summary=True)
        if method == 'item/reasoning/textDelta':
            state = self._item(params.get('itemId'))
            if not state['thinking']:
                state['thinking'] = True
                return [{'kind': 'thinking'}]
            return []
        if method not in {'item/started', 'item/completed'}:
            return []
        item = params.get('item')
        if not isinstance(item, dict):
            return []
        if item.get('type') == 'agentMessage':
            state = self._item(item.get('id'))
            state['phase'] = item.get('phase')
            if method != 'item/completed' or state['complete']:
                return self._output(state) if state['phase'] == 'commentary' else []
            text = item.get('text')
            if not isinstance(text, str) or not text.startswith(state['raw']):
                raise ValueError('Inconsistent completed message')
            self._append(state, text[len(state['raw']):])
            state['complete'] = True
            return self._output(state, final=True)
        if item.get('type') == 'reasoning' and method == 'item/completed':
            # Only the explicit public `summary` array; `content` stays local.
            result = []
            summaries = item.get('summary', [])
            if not isinstance(summaries, list) or len(summaries) > 100:
                raise ValueError('Invalid public summary')
            for index, text in enumerate(summaries):
                state = self._item(item.get('id'), summary_index=index)
                if state['complete']:
                    continue
                if not isinstance(text, str) or not text.startswith(state['raw']):
                    raise ValueError('Inconsistent public summary')
                self._append(state, text[len(state['raw']):])
                state['complete'] = True
                result += self._output(state, final=True, summary=True)
            return result
        return []
