"""Small, immutable display receipts for the context of a submitted message.

These fields never authorize Agent work. Authorization still comes exclusively
from the validated source/scope. No current document or provider state is read.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from module_mindmap.ai.document import AI_MAX_NODE_COUNT
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MAX_SELECTED_NODE_COUNT,
    MindmapAiAttachmentModel,
    MindmapAiScopeModel,
)

_RECEIPT_KEY = '_userMessageContext'
_LABEL_MAX_LENGTH = 512
_ATTACHMENT_TEXT_MAX_LENGTH = 50_000
_CONTROL_CHARACTERS = re.compile(r'[\x00-\x1f\x7f]')
_SOURCE_MODES = {
    'none': 'new', 'uploaded_artifact': 'file',
    'cloud_document': 'current', 'local_snapshot': 'current',
}


class _PlainLabelParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs: list) -> None:
        if tag in {'script', 'style'}:
            self.hidden += 1
        elif tag in {'br', 'p', 'div', 'li'}:
            self.parts.append(' ')

    def handle_endtag(self, tag: str) -> None:
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {'p', 'div', 'li'}:
            self.parts.append(' ')

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _bounded_label(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    return ' '.join(_CONTROL_CHARACTERS.sub(' ', value).split())[:_LABEL_MAX_LENGTH]


def _plain_label(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    parser = _PlainLabelParser()
    # Old persisted rows can contain rich text. Return text only, never HTML,
    # node notes, links, images, or arbitrary node fields.
    parser.feed(value[:20_000])
    parser.close()
    return _bounded_label(''.join(parser.parts))


def _selected_uids(scope: Any) -> tuple[str, list[str]] | None:
    try:
        parsed = MindmapAiScopeModel.model_validate(scope)
    except (TypeError, ValueError):
        return None
    return parsed.type, (
        [parsed.root_uid] if parsed.type == 'branch'
        else list(parsed.node_uids or []) if parsed.type == 'selectedNodes'
        else []
    )


def _snapshot_labels(source: dict, selected: list[str]) -> dict[str, str]:
    document = source.get('document')
    if not isinstance(document, dict):
        document = source.get('baselineDocument')
    if not isinstance(document, dict):
        artifact = source.get('artifact')
        document = artifact.get('document') if isinstance(artifact, dict) else None
    root = document.get('root') if isinstance(document, dict) else None
    if not isinstance(root, dict):
        return {}
    wanted = set(selected)
    labels: dict[str, str] = {}
    pending = [root]
    visited = 0
    while pending and visited < AI_MAX_NODE_COUNT and len(labels) < len(wanted):
        node = pending.pop()
        visited += 1
        data = node.get('data')
        if isinstance(data, dict):
            uid = data.get('uid')
            if isinstance(uid, str) and uid in wanted and uid not in labels:
                labels[uid] = _plain_label(data.get('text'))
        children = node.get('children')
        if isinstance(children, list):
            # Bound malformed legacy snapshots without walking unrelated data.
            pending.extend(child for child in reversed(children[:AI_MAX_NODE_COUNT]) if isinstance(child, dict))
    return labels


def _derive_context(payload: dict) -> dict | None:
    source = payload.get('source')
    if not isinstance(source, dict) or source.get('type') not in _SOURCE_MODES:
        return None
    # Validated requests persist even the default scope. If a legacy existing
    # source omitted that receipt entirely, we cannot prove it was the whole
    # map. A new empty source is the one unambiguous exception.
    if 'scope' not in source and source['type'] != 'none':
        return None
    selection = _selected_uids(source.get('scope', {}))
    if selection is None:
        return None
    scope_type, selected = selection
    labels = _snapshot_labels(source, selected) if selected else {}
    return {
        'sourceMode': _SOURCE_MODES[source['type']],
        'scopeType': scope_type,
        'contextNodes': [{'uid': uid, 'label': labels.get(uid, '')} for uid in selected],
    }


def _safe_receipt(value: Any) -> dict | None:
    if not isinstance(value, dict) or value.get('sourceMode') not in {'current', 'new', 'file'}:
        return None
    scope_type = value.get('scopeType')
    nodes = value.get('contextNodes')
    if not isinstance(nodes, list) or len(nodes) > MAX_SELECTED_NODE_COUNT:
        return None
    if any(not isinstance(node, dict) for node in nodes):
        return None
    scope = {'type': scope_type}
    if scope_type == 'branch':
        if len(nodes) != 1:
            return None
        scope['rootUid'] = nodes[0].get('uid')
    elif scope_type == 'selectedNodes':
        scope['nodeUids'] = [node.get('uid') for node in nodes]
    elif scope_type == 'document':
        if nodes:
            return None
    else:
        return None
    selection = _selected_uids(scope)
    if selection is None:
        return None
    # Frozen labels are already plain text. Do not parse them twice: a literal
    # node label such as "<button>" must survive repeated timeline reads.
    labels = {node.get('uid'): _bounded_label(node.get('label')) for node in nodes}
    return {
        'sourceMode': value['sourceMode'], 'scopeType': scope_type,
        'contextNodes': [{'uid': uid, 'label': labels.get(uid, '')} for uid in selection[1]],
    }


def freeze_user_message_context(payload: dict) -> dict:
    """Called after request validation, before a queued source can be rebased."""
    result = dict(payload)
    if _RECEIPT_KEY not in result:
        result[_RECEIPT_KEY] = _derive_context(payload)
    return result


def user_message_context(payload: Any) -> dict | None:
    if not isinstance(payload, dict):
        return None
    if _RECEIPT_KEY in payload:
        return _safe_receipt(payload[_RECEIPT_KEY])
    return _derive_context(payload)


def user_message_attachments(payload: Any) -> list[dict[str, Any]]:
    """Expose bounded file receipts, never extracted text or claimed parser logs.

    A parsed receipt only confirms that valid client-extracted text was saved
    with this turn. It does not claim that the server parsed the original file
    or that a provider read it. Older metadata without valid text stays unknown.
    """
    files = payload.get('attachments') if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return []
    receipts: list[dict[str, Any]] = []
    for item in files[:5]:
        if not isinstance(item, dict):
            continue
        metadata = {field: item.get(field) for field in ('id', 'name', 'size', 'mediaType')}
        if 'purpose' in item:
            metadata['purpose'] = item['purpose']
        try:
            # Validate metadata independently so a missing legacy text body
            # cannot break the entire timeline or erase its known file name.
            attachment = MindmapAiAttachmentModel.model_validate({**metadata, 'text': 'metadata only'})
        except (TypeError, ValueError):
            continue
        receipt = attachment.model_dump(by_alias=True, exclude={'text'})
        profile = payload.get('_templateProfile')
        if (attachment.purpose == 'template' and isinstance(profile, dict)
            and profile.get('source') == item.get('templateSource')
            and isinstance(profile.get('unavailableTags'), list) and profile['unavailableTags']):
            names = '、'.join(str(name)[:100] for name in profile['unavailableTags'][:10])
            receipt['warnings'] = [f'模版中的部分标签当前不可引用，已跳过这些标签：{names}']
        text = item.get('text')
        receipt['parsing'] = (
            {'status': 'parsed', 'characterCount': len(text)}
            if isinstance(text, str) and 0 < len(text) <= _ATTACHMENT_TEXT_MAX_LENGTH and text.strip()
            else {'status': 'unknown'}
        )
        receipts.append(receipt)
    return receipts
