"""旧 node_tree 与结构化脑图之间的只读影子一致性校验。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from module_mindmap.service.mindmap_tag_identity import build_custom_tag_key
from module_mindmap.service.simple_mind_document_codec import EncodedDocument, SimpleMindDocumentCodec


@dataclass(slots=True)
class ShadowComparison:
    is_equal: bool
    legacy_hash: str
    structured_hash: str
    difference_path: str | None = None
    legacy_value: Any = None
    structured_value: Any = None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        number = float(value)
        return int(number) if number.is_integer() else number
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {
            str(key): _normalize_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value


def _tag_identity(raw: Any) -> str:
    if not isinstance(raw, dict):
        return f'custom:{build_custom_tag_key(raw)}'
    tag_key = raw.get('tagKey') or raw.get('tag_key')
    if tag_key and str(tag_key).startswith('custom_'):
        return f'custom:{tag_key}'
    tag_id = raw.get('tagId') or raw.get('tag_id') or raw.get('id')
    if tag_id:
        return f'tag:{tag_id}'
    if raw.get('uuid'):
        return f'uuid:{raw["uuid"]}'
    if tag_key:
        return f'key:{tag_key}'
    return f'custom:{build_custom_tag_key(raw.get("text") or raw.get("name"))}'


def _build_path_map(document: EncodedDocument) -> dict[str, str]:
    rows_by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for row in document.nodes:
        parent_uid = str(row['parent_uid']) if row.get('parent_uid') is not None else None
        rows_by_parent.setdefault(parent_uid, []).append(row)
    for rows in rows_by_parent.values():
        rows.sort(key=lambda row: (int(row.get('sort_order') or 0), str(row['node_uid'])))

    root_uid = str(document.root_uid)
    paths: dict[str, str] = {}
    pending = [(root_uid, 'root')]
    while pending:
        node_uid, path = pending.pop()
        if node_uid in paths:
            raise ValueError('脑图节点包含循环或重复引用')
        paths[node_uid] = path
        children = rows_by_parent.get(node_uid, [])
        for index in range(len(children) - 1, -1, -1):
            child_uid = str(children[index]['node_uid'])
            pending.append((child_uid, f'{path}/{index}'))
    if len(paths) != len(document.nodes):
        raise ValueError('脑图节点包含孤儿或不可达节点')
    return paths


def canonicalize_mindmap_tree(root: dict[str, Any]) -> dict[str, Any]:
    """生成忽略托管标签展示副本和随机 UID 的稳定语义投影。"""
    document = SimpleMindDocumentCodec.encode(root)
    if not document.nodes or not document.root_uid:
        raise ValueError('脑图没有有效根节点')
    paths = _build_path_map(document)

    nodes = []
    for row in document.nodes:
        node_uid = str(row['node_uid'])
        nodes.append({
            'path': paths[node_uid],
            'textContent': row.get('text_content'),
            'textFormat': row.get('text_format'),
            'expanded': bool(row.get('is_expanded', True)),
            'direction': row.get('direction'),
            'customLeft': row.get('custom_left'),
            'customTop': row.get('custom_top'),
            'customTextWidth': row.get('custom_text_width'),
            'content': row.get('content_data'),
            'style': row.get('style_data'),
            'extension': row.get('extension_data'),
            'envelope': row.get('envelope_data'),
        })
    nodes.sort(key=lambda item: item['path'])

    tags = [{
        'path': paths.get(str(row.get('node_uid')), 'missing'),
        'order': int(row.get('sort_order') or 0),
        'identity': _tag_identity(row.get('resolved') if row.get('resolved') is not None else row.get('raw')),
        'placement': row.get('placement'),
        'align': row.get('align'),
    } for row in document.node_tags]
    tags.sort(key=lambda item: (item['path'], item['order'], item['identity']))

    relations = [{
        'sourcePath': paths.get(str(row.get('source_uid')), 'missing'),
        'targetPath': paths.get(str(row.get('target_uid')), 'missing'),
        'type': row.get('relation_type', 'associative_line'),
        'order': int(row.get('sort_order') or 0),
        'text': row.get('text'),
        'control': row.get('control_data'),
        'style': row.get('style_data'),
    } for row in document.relations]
    relations.sort(key=lambda item: (item['sourcePath'], item['order'], item['targetPath']))

    summaries = [{
        'ownerPath': paths.get(str(row.get('owner_uid')), 'missing'),
        'startPath': paths.get(str(row.get('start_child_uid')), None),
        'endPath': paths.get(str(row.get('end_child_uid')), None),
        'order': int(row.get('sort_order') or 0),
        'payload': row.get('payload'),
    } for row in document.summaries]
    summaries.sort(key=lambda item: (item['ownerPath'], item['order']))

    groups = [{
        'parentPath': paths.get(str(row.get('parent_uid')), None),
        'type': row.get('group_type', 'outer_frame'),
        'members': [paths.get(str(uid), 'missing') for uid in row.get('member_uids') or []],
        'payload': row.get('payload'),
    } for row in document.groups]
    groups.sort(key=lambda item: (item['parentPath'] or '', item['members']))

    assets = [{
        'key': row.get('asset_key'),
        'type': row.get('asset_type'),
        'storage': row.get('storage_type'),
        'uri': row.get('uri'),
        'mimeType': row.get('mime_type'),
        'size': row.get('size'),
        'sha256': row.get('sha256'),
    } for row in document.assets]
    assets.sort(key=lambda item: str(item['key']))

    return _normalize_value({
        'nodes': nodes,
        'tags': tags,
        'relations': relations,
        'summaries': summaries,
        'groups': groups,
        'assets': assets,
    })


def hash_canonical_document(document: dict[str, Any]) -> str:
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _first_difference(left: Any, right: Any, path: str = '$') -> tuple[str, Any, Any] | None:
    if type(left) is not type(right):
        return path, left, right
    if isinstance(left, dict):
        keys = sorted(set(left) | set(right))
        for key in keys:
            if key not in left or key not in right:
                return f'{path}.{key}', left.get(key), right.get(key)
            difference = _first_difference(left[key], right[key], f'{path}.{key}')
            if difference:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f'{path}.length', len(left), len(right)
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _first_difference(left_item, right_item, f'{path}[{index}]')
            if difference:
                return difference
        return None
    return None if left == right else (path, left, right)


def compare_mindmap_trees(legacy_tree: dict[str, Any], structured_tree: dict[str, Any]) -> ShadowComparison:
    legacy = canonicalize_mindmap_tree(legacy_tree)
    structured = canonicalize_mindmap_tree(structured_tree)
    legacy_hash = hash_canonical_document(legacy)
    structured_hash = hash_canonical_document(structured)
    difference = _first_difference(legacy, structured)
    return ShadowComparison(
        is_equal=difference is None,
        legacy_hash=legacy_hash,
        structured_hash=structured_hash,
        difference_path=difference[0] if difference else None,
        legacy_value=difference[1] if difference else None,
        structured_value=difference[2] if difference else None,
    )
