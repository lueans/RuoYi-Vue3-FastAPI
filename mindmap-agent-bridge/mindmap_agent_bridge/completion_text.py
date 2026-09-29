"""Project ACP prose without hiding ordinary brace/JSON/code examples.

This is a text-only filter for the independently installed companion; it does
not validate a completion or own a draft. The backend verifies both separately.
The caller bounds the raw transcript before applying this projection.
"""

import json
import re


def _closed_object_end(value):
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


def _has_completion_key(value):
    return any(json.loads(match.group(1)) == 'completionState' for match in re.finditer(
        r'("(?:\\["\\/bfnrt]|\\u[0-9a-fA-F]{4}|[^"\\\x00-\x1f])*")\s*:', value,
    ))


def completion_prose(text, *, final=False):
    """Return an append-only public prefix, withholding undecided contracts."""
    cursor = 0
    decoder = json.JSONDecoder()
    while marker := re.search(r'[{`]', text[cursor:]):
        start = cursor + marker.start()
        candidate = text[start:]
        offset = start
        if candidate.startswith('`'):
            prefix = candidate.lower()
            if prefix != '```json' and '```json'.startswith(prefix):
                return text if final else text[:start]
            if not prefix.startswith('```json'):
                cursor = start + 1
                continue
            candidate = candidate[7:].lstrip()
            if not candidate:
                return text if final else text[:start]
            offset = len(text) - len(candidate)
            if not candidate.startswith('{'):
                cursor = start + 1
                continue
        body = candidate[1:].lstrip()
        if (body and body[0] not in {'"', '}'}) or (final and not body):
            cursor = start + 1
            continue
        try:
            value, end = decoder.raw_decode(candidate)
        except (ValueError, RecursionError):
            end = _closed_object_end(candidate)
            if end is None or _has_completion_key(candidate[:end]):
                return text[:start]
            value = None  # A closed Python/JS example, not control JSON.
        if isinstance(value, dict) and 'completionState' in value:
            return text[:start]
        cursor = offset + end
    return text
