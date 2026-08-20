"""simple-mind-map 文档与结构化持久化记录之间的无损编解码器。"""
from __future__ import annotations

import copy
import hashlib
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from html import unescape
from typing import Any

SCHEMA_VERSION = 2
ENGINE_NAME = 'simple-mind-map'
ENGINE_VERSION = 'fc4f93a38ee2a2eaa8e9e6c8d4c73f2bdac060b1'
MAX_NODE_COUNT = 20_000
MAX_TREE_DEPTH = 256
MAX_STABLE_UID_LENGTH = 64
MAX_ASSET_KEY_LENGTH = 128
ASSOCIATIVE_RELATION_PREFIX = 'assoc:'

# 不应跨会话保存的渲染/交互状态。
TRANSIENT_KEYS = {
    'isActive', 'inserting', 'needUpdate', 'resetRichText', 'activeStyle',
}

CORE_KEYS = {
    'uid', 'text', 'richText', 'expand', 'dir',
    'customLeft', 'customTop', 'customTextWidth',
}

CONTENT_KEYS = {
    'image', 'imageTitle', 'imageSize', 'icon',
    'hyperlink', 'hyperlinkTitle', 'note',
    'attachmentUrl', 'attachmentName', 'notation',
    'number', 'range', 'checkbox', 'nodeLink',
}

RELATION_KEYS = {
    'associativeLineTargets', 'associativeLineTargetControlOffsets',
    'associativeLinePoint', 'associativeLineText', 'associativeLineStyle',
}

SPECIAL_KEYS = {'tag', 'generalization', 'outerFrame', 'imgMap'}

# simple-mind-map 把不在 nodeDataNoStylePropList 中的字段视为节点样式。这里保留
# 常用/当前主题字段；新增样式字段可升级注册表，未知字段仍会进入 extension_data。
STYLE_KEYS = {
    'shape', 'fillColor', 'gradientStyle', 'startColor', 'endColor',
    'startDir', 'endDir', 'borderColor', 'borderWidth', 'borderDasharray',
    'borderRadius', 'color', 'fontFamily', 'fontSize', 'fontWeight',
    'fontStyle', 'textDecoration', 'textAlign', 'lineColor', 'lineWidth',
    'lineDasharray', 'showLineMarker', 'lineMarkerDir', 'lineStyle',
    'lineRadius', 'lineOffset', 'lineActiveColor', 'lineActiveWidth',
    'textAutoWrapWidth', 'textLineHeight', 'nodePaddingX', 'nodePaddingY',
    'imgPlacement', 'imgSize', 'iconSize', 'iconColor', 'tagPlacement',
    'hoverRectColor', 'hoverRectRadius', 'generalizationLineWidth',
    'generalizationLineColor', 'associativeLineColor',
    'associativeLineWidth', 'associativeLineActiveColor',
    'associativeLineActiveWidth', 'associativeLineTextColor',
    'associativeLineTextFontSize', 'associativeLineTextLineHeight',
    'associativeLineTextFontFamily',
}


def _plain_text(value: Any) -> str:
    if value is None:
        return ''
    text = str(value)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', unescape(text)).strip()


def _uid(value: Any | None = None) -> str:
    return str(value) if value else uuid.uuid4().hex


def _stable_identifier(
    value: Any,
    label: str,
    max_length: int = MAX_STABLE_UID_LENGTH,
) -> str:
    text = str(value) if value is not None else ''
    if not text or text != text.strip():
        raise ValueError(f'脑图{label}缺少稳定 UID')
    if len(text) > max_length:
        raise ValueError(f'脑图{label}稳定 UID 不能超过 {max_length} 个字符')
    return text


def _relation_uid(source_uid: str, target_uid: str) -> str:
    raw_uid = f'{ASSOCIATIVE_RELATION_PREFIX}{source_uid}:{target_uid}'
    if len(raw_uid) <= MAX_STABLE_UID_LENGTH:
        return raw_uid
    digest = hashlib.sha256(raw_uid.encode()).hexdigest()
    available_digest_length = MAX_STABLE_UID_LENGTH - len(ASSOCIATIVE_RELATION_PREFIX)
    return f'{ASSOCIATIVE_RELATION_PREFIX}{digest[:available_digest_length]}'


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def _clone_mindmap_tree(root: dict[str, Any]) -> dict[str, Any]:
    """逐节点复制树，避免合法深层 children 链耗尽 Python 调用栈。"""

    def clone_node(node: dict[str, Any]) -> dict[str, Any]:
        cloned = {
            key: _clone(value)
            for key, value in node.items()
            if key != 'children'
        }
        cloned['children'] = []
        return cloned

    cloned_root = clone_node(root)
    pending = [(root, cloned_root)]
    while pending:
        source, target = pending.pop()
        children = source.get('children') or []
        cloned_children = [clone_node(child) for child in children]
        target['children'] = cloned_children
        pending.extend(zip(children, cloned_children, strict=True))
    return cloned_root


def validate_mindmap_tree(root: dict[str, Any]) -> None:
    """限制树规模并拒绝无法无损持久化的图结构。"""
    node_count = 0
    seen_objects: set[int] = set()
    seen_data_objects: set[int] = set()
    seen_uids: set[str] = set()
    pending = [(root, 1)]
    while pending:
        node, depth = pending.pop()
        object_id = id(node)
        if object_id in seen_objects:
            raise ValueError('脑图节点包含循环或重复引用')
        seen_objects.add(object_id)

        node_count += 1
        if node_count > MAX_NODE_COUNT:
            raise ValueError(f'脑图节点数量不能超过 {MAX_NODE_COUNT}')
        if depth > MAX_TREE_DEPTH:
            raise ValueError(f'脑图层级不能超过 {MAX_TREE_DEPTH}')

        data = node.get('data')
        if isinstance(data, dict):
            data_object_id = id(data)
            if data_object_id in seen_data_objects:
                raise ValueError('脑图节点包含循环或重复引用')
            seen_data_objects.add(data_object_id)
        raw_uid = data.get('uid') if isinstance(data, dict) else None
        if raw_uid:
            node_uid = _stable_identifier(raw_uid, '节点')
            if node_uid in seen_uids:
                raise ValueError(f'脑图节点 UID 重复: {node_uid}')
            seen_uids.add(node_uid)

        children = node.get('children')
        if children is None:
            continue
        if not isinstance(children, list):
            raise ValueError('脑图节点 children 必须是数组')
        if any(not isinstance(child, dict) for child in children):
            raise ValueError('脑图子节点必须是对象')
        pending.extend((child, depth + 1) for child in children)


def _index_structured_node_rows(
    node_rows: Any,
) -> tuple[dict[str, str | None], dict[str, int]]:
    """规范结构化节点身份、父级和顺序字段。"""
    if not isinstance(node_rows, list):
        raise ValueError('脑图结构化节点必须是数组')
    if len(node_rows) > MAX_NODE_COUNT:
        raise ValueError(f'脑图节点数量不能超过 {MAX_NODE_COUNT}')

    parent_map: dict[str, str | None] = {}
    order_map: dict[str, int] = {}
    for row in node_rows:
        if not isinstance(row, dict):
            raise ValueError('脑图结构化节点必须是对象')
        raw_uid = row.get('node_uid')
        node_uid = _stable_identifier(raw_uid, '节点')
        if node_uid in parent_map:
            raise ValueError(f'脑图节点 UID 重复: {node_uid}')
        raw_parent_uid = row.get('parent_uid')
        parent_map[node_uid] = (
            _stable_identifier(raw_parent_uid, '父节点')
            if raw_parent_uid is not None
            else None
        )
        try:
            order_map[node_uid] = int(row.get('sort_order') or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'脑图节点排序值非法: {node_uid}') from exc
    return parent_map, order_map


def _resolve_structured_root_uid(
    parent_map: dict[str, str | None], declared_root_uid: Any,
) -> str:
    """解析唯一拓扑根，并校验显式根声明。"""
    roots = [node_uid for node_uid, parent_uid in parent_map.items() if parent_uid is None]
    if len(roots) != 1:
        raise ValueError('脑图必须且只能包含一个根节点')
    topology_root_uid = roots[0]
    root_uid = str(declared_root_uid) if declared_root_uid is not None else ''
    if root_uid:
        if root_uid not in parent_map:
            raise ValueError(f'脑图根节点 UID 不存在: {root_uid}')
        if root_uid != topology_root_uid:
            raise ValueError('脑图根节点与父子拓扑不一致')
        return root_uid
    return topology_root_uid


def _validate_structured_topology(
    parent_map: dict[str, str | None],
    order_map: dict[str, int],
    declared_root_uid: Any,
) -> tuple[dict[str, list[str]], str]:
    """校验结构化节点组成唯一、完整且深度受限的树。"""
    root_uid = _resolve_structured_root_uid(parent_map, declared_root_uid)

    children_by_parent: dict[str, list[str]] = defaultdict(list)
    for node_uid, parent_uid in parent_map.items():
        if parent_uid is None:
            continue
        if parent_uid not in parent_map:
            raise ValueError(f'脑图节点缺失父节点: {node_uid}')
        children_by_parent[parent_uid].append(node_uid)
    for child_uids in children_by_parent.values():
        child_uids.sort(key=lambda uid: (order_map[uid], uid))

    visited: set[str] = set()
    pending = [(root_uid, 1)]
    while pending:
        node_uid, depth = pending.pop()
        if node_uid in visited:
            raise ValueError('脑图节点包含循环或重复引用')
        if depth > MAX_TREE_DEPTH:
            raise ValueError(f'脑图层级不能超过 {MAX_TREE_DEPTH}')
        visited.add(node_uid)
        pending.extend(
            (child_uid, depth + 1)
            for child_uid in reversed(children_by_parent.get(node_uid, ()))
        )
    if len(visited) != len(parent_map):
        raise ValueError('脑图节点包含循环或不可达节点')
    return children_by_parent, root_uid


def _structured_rows(value: Any, label: str) -> list[dict[str, Any]]:
    """校验结构化附属记录容器，避免非数组值被 ``or []`` 静默吞掉。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f'脑图{label}必须是数组')
    if any(not isinstance(row, dict) for row in value):
        raise ValueError(f'脑图{label}记录必须是对象')
    return value


def _required_row_uid(
    row: dict[str, Any],
    key: str,
    label: str,
    max_length: int = MAX_STABLE_UID_LENGTH,
) -> str:
    return _stable_identifier(row.get(key), label, max_length)


def _validate_row_sort_order(row: dict[str, Any], label: str) -> None:
    try:
        int(row.get('sort_order') or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'脑图{label}排序值非法') from exc


def _validate_unique_uid(uid: str, seen: set[str], label: str) -> None:
    if uid in seen:
        raise ValueError(f'脑图{label} UID 重复: {uid}')
    seen.add(uid)


def _validate_tag_rows(node_tags: list[dict[str, Any]], node_uids: set[str]) -> None:
    for row in node_tags:
        node_uid = _required_row_uid(row, 'node_uid', '标签绑定')
        if node_uid not in node_uids:
            raise ValueError('脑图标签绑定引用不存在的节点')
        _validate_row_sort_order(row, '标签绑定')


def _validate_relation_rows(relations: list[dict[str, Any]], node_uids: set[str]) -> None:
    relation_uids: set[str] = set()
    for row in relations:
        relation_uid = _required_row_uid(row, 'relation_uid', '关联线')
        _validate_unique_uid(relation_uid, relation_uids, '关联线')
        source_uid = _required_row_uid(row, 'source_uid', '关联线源节点')
        target_uid = _required_row_uid(row, 'target_uid', '关联线目标节点')
        if source_uid not in node_uids or target_uid not in node_uids:
            raise ValueError('脑图关联线引用不存在的节点')
        if source_uid == target_uid:
            raise ValueError('脑图关联线不能指向自身')
        _validate_row_sort_order(row, '关联线')


def _validate_summary_rows(
    summaries: list[dict[str, Any]],
    parent_map: dict[str, str | None],
    order_map: dict[str, int],
) -> None:
    node_uids = set(parent_map)
    summary_uids: set[str] = set()
    for row in summaries:
        summary_uid = _required_row_uid(row, 'summary_uid', '概要')
        _validate_unique_uid(summary_uid, summary_uids, '概要')
        owner_uid = _required_row_uid(row, 'owner_uid', '概要所属节点')
        if owner_uid not in node_uids:
            raise ValueError('脑图概要引用不存在的所属节点')
        start_uid = row.get('start_child_uid')
        end_uid = row.get('end_child_uid')
        if (start_uid is None) != (end_uid is None):
            raise ValueError('脑图概要范围必须同时包含起止节点')
        if start_uid is not None:
            start_uid = _stable_identifier(start_uid, '概要起点')
            end_uid = _stable_identifier(end_uid, '概要终点')
            if (
                start_uid not in node_uids
                or end_uid not in node_uids
                or parent_map[start_uid] != owner_uid
                or parent_map[end_uid] != owner_uid
            ):
                raise ValueError('脑图概要范围必须引用所属节点的直接子节点')
            if order_map[start_uid] > order_map[end_uid]:
                raise ValueError('脑图概要范围起点不能晚于终点')
        _validate_row_sort_order(row, '概要')


def _validate_group_rows(
    groups: list[dict[str, Any]],
    parent_map: dict[str, str | None],
    order_map: dict[str, int],
) -> None:
    node_uids = set(parent_map)
    group_uids: set[str] = set()
    for row in groups:
        group_uid = _required_row_uid(row, 'group_uid', '外框')
        _validate_unique_uid(group_uid, group_uids, '外框')
        parent_uid = _required_row_uid(row, 'parent_uid', '外框父节点')
        if parent_uid not in node_uids:
            raise ValueError('脑图外框引用不存在的父节点')
        member_uids = row.get('member_uids')
        if not isinstance(member_uids, list) or not member_uids:
            raise ValueError('脑图外框成员必须是非空数组')
        normalized_members = [
            _stable_identifier(member_uid, '外框成员')
            for member_uid in member_uids
        ]
        if len(set(normalized_members)) != len(normalized_members):
            raise ValueError('脑图外框包含重复成员')
        if any(
            member_uid not in node_uids or parent_map[member_uid] != parent_uid
            for member_uid in normalized_members
        ):
            raise ValueError('脑图外框成员必须是同一父节点下的直接子节点')
        member_orders = sorted(order_map[member_uid] for member_uid in normalized_members)
        if member_orders != list(range(member_orders[0], member_orders[0] + len(member_orders))):
            raise ValueError('脑图外框成员必须是连续的兄弟节点')


def _validate_asset_rows(assets: list[dict[str, Any]]) -> None:
    asset_keys: set[str] = set()
    for row in assets:
        asset_key = _required_row_uid(
            row,
            'asset_key',
            '资源',
            max_length=MAX_ASSET_KEY_LENGTH,
        )
        _validate_unique_uid(asset_key, asset_keys, '资源')


def _validate_structured_components(
    *,
    parent_map: dict[str, str | None],
    order_map: dict[str, int],
    node_tags: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    assets: list[dict[str, Any]],
) -> None:
    """校验节点之外的结构化记录及其跨节点引用。"""
    node_uids = set(parent_map)
    _validate_tag_rows(node_tags, node_uids)
    _validate_relation_rows(relations, node_uids)
    _validate_summary_rows(summaries, parent_map, order_map)
    _validate_group_rows(groups, parent_map, order_map)
    _validate_asset_rows(assets)


@dataclass(slots=True)
class EncodedDocument:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    node_tags: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    root_uid: str = ''
    schema_version: int = SCHEMA_VERSION


class SimpleMindDocumentCodec:
    """集中维护 simple-mind-map 的持久化契约。"""

    @classmethod
    def encode(cls, root: dict[str, Any] | None) -> EncodedDocument:  # noqa: PLR0915
        result = EncodedDocument()
        if not isinstance(root, dict):
            return result

        validate_mindmap_tree(root)
        root = _clone_mindmap_tree(root)
        group_cache: dict[str, dict[str, Any]] = {}

        def ensure_uids(node: dict[str, Any]) -> None:
            reserved_uids: set[str] = set()
            pending = [node]
            while pending:
                current = pending.pop()
                data = current.get('data')
                if not isinstance(data, dict):
                    data = {}
                    current['data'] = data
                if data.get('uid'):
                    data['uid'] = str(data['uid'])
                    reserved_uids.add(data['uid'])
                pending.extend(reversed(current.get('children') or []))

            assigned_uids: set[str] = set()
            pending = [node]
            while pending:
                current = pending.pop()
                data = current['data']
                if not data.get('uid'):
                    node_uid = _uid()
                    while node_uid in reserved_uids:
                        node_uid = _uid()
                    data['uid'] = node_uid
                    reserved_uids.add(node_uid)
                node_uid = str(data['uid'])
                if node_uid in assigned_uids:
                    raise ValueError(f'脑图节点 UID 重复: {node_uid}')
                assigned_uids.add(node_uid)
                pending.extend(reversed(current.get('children') or []))

        ensure_uids(root)

        pending = [(root, None, 0)]
        while pending:
            node, parent_uid, order = pending.pop()
            data = _clone(node.get('data') or {})
            node_uid = str(data['uid'])
            if not result.root_uid:
                result.root_uid = node_uid

            children = node.get('children') if isinstance(node.get('children'), list) else []
            envelope = {
                key: _clone(value)
                for key, value in node.items()
                if key not in {'data', 'children'} and not str(key).startswith('_')
            }

            content_data: dict[str, Any] = {}
            style_data: dict[str, Any] = {}
            extension_data: dict[str, Any] = {}
            for key, value in data.items():
                if key in TRANSIENT_KEYS or key in CORE_KEYS or key in RELATION_KEYS or key in SPECIAL_KEYS:
                    continue
                if key in CONTENT_KEYS:
                    content_data[key] = value
                elif key in STYLE_KEYS:
                    style_data[key] = value
                else:
                    extension_data[key] = value

            result.nodes.append({
                'node_uid': node_uid,
                'parent_uid': parent_uid,
                'sort_order': order,
                'text_content': data.get('text'),
                'text_plain': _plain_text(data.get('text')),
                'text_format': 'rich' if data.get('richText') else 'plain',
                'is_expanded': data.get('expand') is not False,
                'direction': data.get('dir'),
                'custom_left': data.get('customLeft'),
                'custom_top': data.get('customTop'),
                'custom_text_width': data.get('customTextWidth'),
                'content_data': content_data or None,
                'style_data': style_data or None,
                'extension_data': extension_data or None,
                'envelope_data': envelope or None,
                'payload_schema_version': 1,
            })

            for tag_order, tag in enumerate(data.get('tag') or []):
                result.node_tags.append({
                    'node_uid': node_uid,
                    'sort_order': tag_order,
                    'placement': tag.get('placement') if isinstance(tag, dict) else None,
                    'align': tag.get('align') if isinstance(tag, dict) else None,
                    'raw': _clone(tag),
                })

            cls._encode_relations(result, node_uid, data)
            cls._encode_summaries(result, node_uid, children, data)

            outer_frame = data.get('outerFrame')
            if isinstance(outer_frame, dict):
                group_uid = _uid(outer_frame.get('groupId'))
                group = group_cache.setdefault(group_uid, {
                    'group_uid': group_uid,
                    'parent_uid': parent_uid,
                    'group_type': 'outer_frame',
                    'payload': {k: _clone(v) for k, v in outer_frame.items() if k != 'groupId'},
                    'member_uids': [],
                })
                group['member_uids'].append(node_uid)

            if parent_uid is None:
                cls._encode_assets(result, data.get('imgMap'))

            pending.extend(
                (children[child_order], node_uid, child_order)
                for child_order in range(len(children) - 1, -1, -1)
            )

        result.groups = list(group_cache.values())
        parent_map, order_map = _index_structured_node_rows(result.nodes)
        _validate_structured_components(
            parent_map=parent_map,
            order_map=order_map,
            node_tags=result.node_tags,
            relations=result.relations,
            summaries=result.summaries,
            groups=result.groups,
            assets=result.assets,
        )
        return result

    @staticmethod
    def _encode_relations(result: EncodedDocument, source_uid: str, data: dict[str, Any]) -> None:
        targets = data.get('associativeLineTargets') or []
        offsets = data.get('associativeLineTargetControlOffsets') or []
        points = data.get('associativeLinePoint') or []
        texts = data.get('associativeLineText') or {}
        styles = data.get('associativeLineStyle') or {}
        if not isinstance(targets, list):
            return
        for order, target_value in enumerate(targets):
            target_uid = str(target_value)
            result.relations.append({
                'relation_uid': _relation_uid(source_uid, target_uid),
                'relation_type': 'associative_line',
                'source_uid': source_uid,
                'target_uid': target_uid,
                'text': texts.get(target_uid) if isinstance(texts, dict) else None,
                'control_data': {
                    'offsets': _clone(offsets[order]) if order < len(offsets) else None,
                    'point': _clone(points[order]) if order < len(points) else None,
                },
                'style_data': _clone(styles.get(target_uid)) if isinstance(styles, dict) else None,
                'sort_order': order,
            })

    @staticmethod
    def _encode_summaries(
        result: EncodedDocument,
        owner_uid: str,
        children: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> None:
        summaries = data.get('generalization')
        if not summaries:
            return
        if not isinstance(summaries, list):
            summaries = [summaries]
        child_uids = [str((child.get('data') or {}).get('uid') or '') for child in children]
        for order, item in enumerate(summaries):
            if not isinstance(item, dict):
                continue
            payload = _clone(item)
            summary_uid = _uid(payload.pop('uid', None))
            range_value = payload.pop('range', None)
            start_uid = end_uid = None
            if range_value is not None and (
                not isinstance(range_value, list) or len(range_value) != 2  # noqa: PLR2004
            ):
                raise ValueError('脑图概要范围必须包含两个子节点位置')
            if range_value is not None:
                start, end = range_value
                if isinstance(start, int) and 0 <= start < len(child_uids):
                    start_uid = child_uids[start] or None
                if isinstance(end, int) and 0 <= end < len(child_uids):
                    end_uid = child_uids[end] or None
                if start_uid is None or end_uid is None:
                    raise ValueError('脑图概要范围必须同时包含起止节点')
            result.summaries.append({
                'summary_uid': summary_uid,
                'owner_uid': owner_uid,
                'start_child_uid': start_uid,
                'end_child_uid': end_uid,
                'payload': payload,
                'sort_order': order,
            })

    @staticmethod
    def _encode_assets(result: EncodedDocument, img_map: Any) -> None:
        if not isinstance(img_map, dict):
            return
        for key, uri in img_map.items():
            uri_text = str(uri)
            mime_match = re.match(r'^data:([^;,]+)', uri_text)
            result.assets.append({
                'asset_key': str(key),
                'asset_type': 'image',
                'storage_type': 'base64' if uri_text.startswith('data:') else 'url',
                'uri': uri_text,
                'mime_type': mime_match.group(1) if mime_match else None,
                'size': len(uri_text.encode('utf-8')),
                'sha256': hashlib.sha256(uri_text.encode('utf-8')).hexdigest(),
                'metadata': None,
            })

    @classmethod
    def decode(
        cls, document: EncodedDocument | dict[str, Any],
    ) -> dict[str, Any] | None:
        get = (lambda key: getattr(document, key)) if isinstance(document, EncodedDocument) else document.get
        node_rows = get('nodes')
        if node_rows is None or node_rows == []:
            return None

        parent_map, order_map = _index_structured_node_rows(node_rows)
        children_by_parent, root_uid = _validate_structured_topology(
            parent_map,
            order_map,
            get('root_uid'),
        )
        node_tags = _structured_rows(get('node_tags'), '标签绑定')
        relations = _structured_rows(get('relations'), '关联线')
        summaries = _structured_rows(get('summaries'), '概要')
        groups = _structured_rows(get('groups'), '外框')
        assets = _structured_rows(get('assets'), '资源')
        _validate_structured_components(
            parent_map=parent_map,
            order_map=order_map,
            node_tags=node_tags,
            relations=relations,
            summaries=summaries,
            groups=groups,
            assets=assets,
        )

        nodes: dict[str, dict[str, Any]] = {}
        for row in node_rows:
            uid = str(row['node_uid'])
            data: dict[str, Any] = {}
            for section in ('extension_data', 'style_data', 'content_data'):
                if isinstance(row.get(section), dict):
                    data.update(_clone(row[section]))
            data['uid'] = uid
            if row.get('text_content') is not None:
                data['text'] = row.get('text_content')
            if row.get('text_format') == 'rich':
                data['richText'] = True
            data['expand'] = bool(row.get('is_expanded', True))
            if row.get('direction') is not None:
                data['dir'] = row['direction']
            for source, target in (
                ('custom_left', 'customLeft'),
                ('custom_top', 'customTop'),
                ('custom_text_width', 'customTextWidth'),
            ):
                if row.get(source) is not None:
                    data[target] = row[source]
            node = {'data': data, 'children': []}
            if isinstance(row.get('envelope_data'), dict):
                node.update(_clone(row['envelope_data']))
            nodes[uid] = node
        for parent_uid, child_uids in children_by_parent.items():
            nodes[parent_uid]['children'] = [nodes[uid] for uid in child_uids]

        cls._decode_tags(nodes, node_tags)
        cls._decode_relations(nodes, relations)
        cls._decode_summaries(nodes, summaries)
        cls._decode_groups(nodes, groups)

        if assets:
            nodes[root_uid]['data']['imgMap'] = {
                str(asset['asset_key']): asset.get('uri')
                for asset in assets
                if asset.get('uri') is not None
            }
        return nodes[root_uid]

    @staticmethod
    def _decode_tags(nodes: dict[str, dict[str, Any]], bindings: list[dict[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for binding in bindings:
            grouped[str(binding['node_uid'])].append(binding)
        for node_uid, rows in grouped.items():
            if node_uid not in nodes:
                continue
            rows.sort(key=lambda row: int(row.get('sort_order') or 0))
            tags = []
            for row in rows:
                tag = _clone(row.get('resolved') if row.get('resolved') is not None else row.get('raw'))
                if tag is None:
                    continue
                if not isinstance(tag, dict):
                    tags.append(tag)
                    continue
                if row.get('placement') is not None:
                    tag['placement'] = row['placement']
                if row.get('align') is not None:
                    tag['align'] = row['align']
                tags.append(tag)
            if tags:
                nodes[node_uid]['data']['tag'] = tags

    @staticmethod
    def _decode_relations(nodes: dict[str, dict[str, Any]], relations: list[dict[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for relation in relations:
            if relation.get('relation_type', 'associative_line') == 'associative_line':
                grouped[str(relation['source_uid'])].append(relation)
        for source_uid, rows in grouped.items():
            if source_uid not in nodes:
                continue
            rows.sort(key=lambda row: int(row.get('sort_order') or 0))
            targets, offsets, points = [], [], []
            texts, styles = {}, {}
            for row in rows:
                target_uid = str(row['target_uid'])
                if target_uid not in nodes:
                    continue
                targets.append(target_uid)
                control = row.get('control_data') or {}
                offsets.append(_clone(control.get('offsets')))
                points.append(_clone(control.get('point')))
                if row.get('text') is not None:
                    texts[target_uid] = row['text']
                if row.get('style_data') is not None:
                    styles[target_uid] = _clone(row['style_data'])
            data = nodes[source_uid]['data']
            if targets:
                data['associativeLineTargets'] = targets
                data['associativeLineTargetControlOffsets'] = offsets
                data['associativeLinePoint'] = points
            if texts:
                data['associativeLineText'] = texts
            if styles:
                data['associativeLineStyle'] = styles

    @staticmethod
    def _decode_summaries(nodes: dict[str, dict[str, Any]], summaries: list[dict[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for summary in summaries:
            grouped[str(summary['owner_uid'])].append(summary)
        for owner_uid, rows in grouped.items():
            if owner_uid not in nodes:
                continue
            rows.sort(key=lambda row: int(row.get('sort_order') or 0))
            child_uids = [child['data']['uid'] for child in nodes[owner_uid]['children']]
            output = []
            for row in rows:
                payload = _clone(row.get('payload') or {})
                payload['uid'] = str(row['summary_uid'])
                start_uid = row.get('start_child_uid')
                end_uid = row.get('end_child_uid')
                if start_uid in child_uids and end_uid in child_uids:
                    payload['range'] = [child_uids.index(start_uid), child_uids.index(end_uid)]
                output.append(payload)
            if output:
                nodes[owner_uid]['data']['generalization'] = output

    @staticmethod
    def _decode_groups(nodes: dict[str, dict[str, Any]], groups: list[dict[str, Any]]) -> None:
        for group in groups:
            if group.get('group_type', 'outer_frame') != 'outer_frame':
                continue
            payload = _clone(group.get('payload') or {})
            payload['groupId'] = str(group['group_uid'])
            for node_uid in group.get('member_uids') or []:
                if str(node_uid) in nodes:
                    nodes[str(node_uid)]['data']['outerFrame'] = _clone(payload)
