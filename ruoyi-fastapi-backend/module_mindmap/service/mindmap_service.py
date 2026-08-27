import asyncio
import copy
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException, ServiceWarning
from module_admin.entity.do.user_do import SysUser
from module_mindmap.dao.mindmap_collaborator_dao import MindmapCollaboratorDao
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.dao.mindmap_creation_dao import MindmapCreationDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_folder_dao import MindmapFolderDao
from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator
from module_mindmap.entity.do.mindmap_content_do import (
    MindmapChangeLog,
    MindmapMigrationRecord,
    MindmapNode,
    MindmapNodeTag,
)
from module_mindmap.entity.do.mindmap_creation_do import MindmapCreationRequest
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_folder_do import MindmapFolder
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.vo.mindmap_vo import (
    CROSS_NODE_OPERATION_PREFIXES,
    CROSS_NODE_OPERATION_TYPES,
    FILE_OPERATION_FIELDS,
    NODE_OPERATION_TYPES,
    NODE_TAG_OPERATION_TYPES,
    TREE_OPERATION_TYPES,
    DeleteMindmapModel,
    MindmapBatchStatusUpdateModel,
    MindmapContentBatchModel,
    MindmapContentUpdateModel,
    MindmapListItemModel,
    MindmapMetadataUpdateModel,
    MindmapModel,
    MindmapPageQueryModel,
    MindmapRenameModel,
    MindmapStatusUpdateModel,
    MindmapViewUpdateModel,
)
from module_mindmap.service.mindmap_creation_service import (
    MindmapCreationContext,
    MindmapCreationService,
)
from module_mindmap.service.mindmap_document_service import (
    STRUCTURED_CONTENT_CORRUPT_MESSAGE,
    MindmapDocumentService,
)
from module_mindmap.service.mindmap_metrics import (
    observe_mindmap_operation,
    record_mindmap_event,
)
from module_mindmap.service.mindmap_tag_portability import MindmapTagPortabilityService
from module_mindmap.service.simple_mind_document_codec import (
    MAX_TREE_DEPTH,
    SCHEMA_VERSION,
    SimpleMindDocumentCodec,
    normalize_relation_uid,
    stable_relation_uid,
    validate_mindmap_tree,
)
from utils.common_util import CamelCaseUtil
from utils.log_util import logger

CHANGE_PAGE_SIZE = 500
MAX_BATCH_MINDMAP_DELETE = 100
MERGEABLE_OPERATION_TYPES = TREE_OPERATION_TYPES | frozenset(FILE_OPERATION_FIELDS)
WIDE_NODE_CONFLICT_PART_COUNT = 2
CROSS_NODE_DATA_KEYS = frozenset({
    'associativeLineTargets',
    'associativeLineTargetControlOffsets',
    'associativeLinePoint',
    'associativeLineText',
    'associativeLineStyle',
    'generalization',
    'outerFrame',
    'imgMap',
})
TAG_BINDING_DATA_KEY = 'tag'
MINDMAP_CREATION_ALLOWED_FIELDS = frozenset({
    'name', 'description', 'owner_id', 'folder_id', 'layout', 'theme',
    'node_tree', 'engine_name', 'engine_version', 'document_data',
    'view_data', 'cover_image', 'create_by', 'create_time', 'update_by',
    'update_time', 'remark',
})
MINDMAP_CREATION_AUDIT_FIELDS = frozenset({
    'owner_id', 'create_by', 'create_time', 'update_by', 'update_time',
})


def _detail_metric_outcome(result: MindmapModel) -> str:
    return 'success' if result.content_state == 'ready' else 'degraded'


def _detail_metric_units(
    args: tuple[Any, ...], kwargs: dict[str, Any], result: MindmapModel,
) -> int:
    del args, kwargs
    return max(0, int(result.node_count or 0))


def _detail_metric_hook(result: MindmapModel) -> None:
    event_by_state = {
        'integrity_failed': 'integrity_fallback',
        'load_failed': 'load_fallback',
        'migration_failed': 'migration_fallback',
    }
    if event := event_by_state.get(result.content_state):
        record_mindmap_event(event)


def _batch_save_metric_outcome(result: dict[str, Any]) -> str:
    return 'replay' if result.get('idempotentReplay') else 'success'


def _batch_save_metric_units(
    args: tuple[Any, ...], kwargs: dict[str, Any], result: dict[str, Any],
) -> int:
    del result
    page_object = kwargs.get('page_object')
    if page_object is None:
        page_object = next(
            (value for value in args if isinstance(value, MindmapContentBatchModel)),
            None,
        )
    return len(getattr(page_object, 'operations', ()) or ())


def _batch_save_metric_hook(result: dict[str, Any]) -> None:
    if result.get('idempotentReplay'):
        record_mindmap_event('idempotent_replay')
    if result.get('concurrentMerge'):
        record_mindmap_event('concurrent_merge')


def _operation_child_uids(payload: dict[str, Any], key: str, alias: str) -> list[str] | None:
    value = payload.get(key)
    if value is None:
        value = payload.get(alias)
    if not isinstance(value, list):
        return None
    return [str(uid) for uid in value]


def _cross_operation_conflict_keys(
    operation_type: str, payload: dict[str, Any],
) -> set[str] | None:
    prefix = operation_type.partition('.')[0]
    if not payload.get('key'):
        return None
    keys = {f'{prefix}:{payload["key"]}'}
    reference_fields = {
        'relation': (('sourceUid', 'source_uid'), ('targetUid', 'target_uid')),
        'summary': (
            ('ownerUid', 'owner_uid'),
            ('startChildUid', 'start_child_uid'),
            ('endChildUid', 'end_child_uid'),
        ),
        'group': (),
        'asset': (),
    }[prefix]
    for camel_name, snake_name in reference_fields:
        value = payload.get(camel_name, payload.get(snake_name))
        if value:
            keys.add(f'node-ref:{value}')
    if prefix == 'group':
        for node_uid in payload.get('memberUids', payload.get('member_uids')) or []:
            if node_uid:
                keys.add(f'group-member:{node_uid}')
                keys.add(f'node-ref:{node_uid}')
    return keys


def _node_tag_operation_conflict_keys(
    operation_type: str, operation: dict[str, Any], payload: dict[str, Any],
) -> set[str] | None:
    node_uid = str(operation.get('nodeUid') or operation.get('node_uid') or '')
    if not node_uid:
        return None
    if operation_type == 'node.tag.reorder':
        return {f'tag-order:{node_uid}', f'node-ref:{node_uid}'}
    tag_key = str(_payload_value(payload, 'tagKey', 'tag_key') or '')
    expected_key = f'{node_uid}:{tag_key}'
    if not tag_key or str(payload.get('key') or '') != expected_key:
        return None
    return {f'tag-binding:{node_uid}:{tag_key}', f'node-ref:{node_uid}'}


def get_operation_conflict_keys(operation: dict[str, Any]) -> set[str] | None:
    """返回操作涉及的冲突域；None 表示旧协议或未知操作，必须保守处理。"""
    operation_type = operation.get('type')
    if operation_type in NODE_OPERATION_TYPES:
        node_uid_value = operation.get('nodeUid') or operation.get('node_uid')
        if not node_uid_value:
            return None
        node_uid = str(node_uid_value)
        if operation_type != 'node.update':
            return {f'node:{node_uid}'}

        payload = operation.get('payload')
        if not isinstance(payload, dict):
            return None
        data_changed = payload.get('dataChanged', payload.get('data_changed'))
        children_changed = payload.get('childrenChanged', payload.get('children_changed'))
        if not isinstance(data_changed, bool) or not isinstance(children_changed, bool):
            return None

        keys = set()
        if data_changed:
            keys.add(f'node:{node_uid}:data')
        if children_changed:
            old_child_uids = _operation_child_uids(payload, 'oldChildUids', 'old_child_uids')
            child_uids = _operation_child_uids(payload, 'childUids', 'child_uids')
            if old_child_uids is None or child_uids is None:
                return None
            old_set = set(old_child_uids)
            current_set = set(child_uids)
            for child_uid in old_set ^ current_set:
                keys.add(f'edge:{node_uid}:{child_uid}')
            common_before = [uid for uid in old_child_uids if uid in current_set]
            common_after = [uid for uid in child_uids if uid in old_set]
            if common_before != common_after:
                keys.add(f'order:{node_uid}')
        return keys or None
    if operation_type in CROSS_NODE_OPERATION_TYPES:
        payload = operation.get('payload')
        return (
            _cross_operation_conflict_keys(operation_type, payload)
            if isinstance(payload, dict)
            else None
        )
    if operation_type in NODE_TAG_OPERATION_TYPES:
        payload = operation.get('payload')
        return (
            _node_tag_operation_conflict_keys(operation_type, operation, payload)
            if isinstance(payload, dict)
            else None
        )
    field = FILE_OPERATION_FIELDS.get(operation_type)
    return {f'file:{field}'} if field else None


def get_operation_conflict_key(operation: dict[str, Any]) -> str | None:
    """兼容旧调用：仅在操作有单一冲突域时返回该域。"""
    keys = get_operation_conflict_keys(operation)
    return next(iter(keys)) if keys and len(keys) == 1 else None


def _conflict_keys_overlap(local_key: str, remote_key: str) -> bool:
    local_parts = local_key.split(':')
    remote_parts = remote_key.split(':')
    # view_data 只是各客户端的平移/缩放视口，不承载节点内容。并发保存采用
    # 后写覆盖，避免两个协作者仅因调整画布就阻断同批次中的真实节点修改。
    if local_key == remote_key == 'file:view_data':
        return False
    if local_parts[0] == remote_parts[0] == 'node-ref':
        # Two independent cross-node entities may reference the same node.
        return False
    if local_key == remote_key:
        return True
    if local_parts[0] == remote_parts[0] == 'node':
        return local_parts[1] == remote_parts[1] and (
            len(local_parts) == WIDE_NODE_CONFLICT_PART_COUNT
            or len(remote_parts) == WIDE_NODE_CONFLICT_PART_COUNT
        )
    if local_parts[0] == 'node' and len(local_parts) == WIDE_NODE_CONFLICT_PART_COUNT:
        return remote_parts[0] in {'edge', 'order', 'node-ref'} and local_parts[1] == remote_parts[1]
    if remote_parts[0] == 'node' and len(remote_parts) == WIDE_NODE_CONFLICT_PART_COUNT:
        return local_parts[0] in {'edge', 'order', 'node-ref'} and remote_parts[1] == local_parts[1]
    if {local_parts[0], remote_parts[0]} == {'edge', 'order'}:
        return local_parts[1] == remote_parts[1]
    if {local_parts[0], remote_parts[0]} == {'tag-binding', 'tag-order'}:
        return local_parts[1] == remote_parts[1]
    return False


def _conflicting_key_pairs(local_keys: set[str], remote_keys: set[str]) -> list[tuple[str, str]]:
    return [
        (local_key, remote_key)
        for local_key in local_keys
        for remote_key in remote_keys
        if _conflict_keys_overlap(local_key, remote_key)
    ]


def analyze_concurrent_operations(
    local_operations: list[dict[str, Any]],
    remote_operations: list[dict[str, Any]],
    history_complete: bool,
) -> dict[str, Any]:
    local_key_groups = [get_operation_conflict_keys(operation) for operation in local_operations]
    remote_key_groups = [get_operation_conflict_keys(operation) for operation in remote_operations]
    mergeable = (
        history_complete
        and all(keys is not None for keys in local_key_groups)
        and all(keys is not None for keys in remote_key_groups)
        and all(operation.get('type') in MERGEABLE_OPERATION_TYPES for operation in local_operations)
        and all(operation.get('type') in MERGEABLE_OPERATION_TYPES for operation in remote_operations)
    )
    local_keys = set().union(*(keys or set() for keys in local_key_groups))
    remote_keys = set().union(*(keys or set() for keys in remote_key_groups))
    conflict_pairs = _conflicting_key_pairs(local_keys, remote_keys)
    conflicts = sorted({key for pair in conflict_pairs for key in pair})
    conflict_node_uids = sorted({
        parts[1]
        for key in conflicts
        if (parts := key.split(':'))[0] in {
            'node', 'node-ref', 'edge', 'order', 'tag-binding', 'tag-order',
        }
    })
    return {
        'mergeable': mergeable and not conflict_pairs,
        'conflictNodeUids': conflict_node_uids,
        'conflictFields': [key.removeprefix('file:') for key in conflicts if key.startswith('file:')],
        'conflictEntities': [
            key
            for key in conflicts
            if key.split(':', 1)[0] in CROSS_NODE_OPERATION_PREFIXES | {'tag-binding', 'tag-order'}
        ],
        'requiresSnapshot': not history_complete or not mergeable,
    }


def is_change_history_complete(changes: list[Any], base_revision: int, current_revision: int) -> bool:
    """确认变更日志从 baseRevision + 1 到当前版本连续且无缺口。"""
    expected_count = current_revision - base_revision
    if expected_count <= 0 or len(changes) != expected_count:
        return False
    return all(
        row.revision == base_revision + index
        for index, row in enumerate(changes, start=1)
    )


def _flatten_tree_for_merge(root: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], str]:
    """把 simple-mind-map 树转换为可安全合并的 UID 映射。"""
    validate_mindmap_tree(root)
    entries: dict[str, dict[str, Any]] = {}
    root_uid = ''

    def walk(node: dict[str, Any], parent_uid: str | None, sort_order: int) -> None:
        nonlocal root_uid
        data = node.get('data') if isinstance(node, dict) else None
        node_uid = str((data or {}).get('uid') or '')
        if not node_uid:
            raise ValueError('脑图节点缺少稳定 UID，无法安全合并')
        if node_uid in entries:
            raise ValueError(f'脑图节点 UID 重复: {node_uid}')
        if not root_uid:
            root_uid = node_uid
        entries[node_uid] = {
            'node': copy.deepcopy({key: value for key, value in node.items() if key != 'children'}),
            'parent_uid': parent_uid,
            'sort_order': sort_order,
        }
        for index, child in enumerate(node.get('children') or []):
            if isinstance(child, dict):
                walk(child, node_uid, index)

    walk(root, None, 0)
    return entries, root_uid


def _rebuild_tree_after_merge(entries: dict[str, dict[str, Any]], root_uid: str) -> dict[str, Any]:
    """从合并后的 UID 映射重建树，并拒绝孤儿或循环。"""
    if root_uid not in entries:
        raise ValueError('合并操作不能删除脑图根节点')
    children: dict[str, list[str]] = {}
    roots = []
    for node_uid, entry in entries.items():
        parent_uid = entry['parent_uid']
        if parent_uid is None:
            roots.append(node_uid)
        elif parent_uid not in entries:
            raise ValueError(f'节点 {node_uid} 的父节点不存在')
        else:
            children.setdefault(parent_uid, []).append(node_uid)
    if roots != [root_uid]:
        raise ValueError('合并后脑图必须且只能包含一个根节点')
    for child_uids in children.values():
        child_uids.sort(key=lambda uid: (entries[uid]['sort_order'], uid))

    def build(node_uid: str, path: set[str]) -> dict[str, Any]:
        if node_uid in path:
            raise ValueError('合并后脑图节点包含循环')
        node = copy.deepcopy(entries[node_uid]['node'])
        node['children'] = [build(uid, path | {node_uid}) for uid in children.get(node_uid, [])]
        return node

    return build(root_uid, set())


def _delete_server_subtree(
    entries: dict[str, dict[str, Any]], node_uid: str, root_uid: str,
) -> None:
    if node_uid == root_uid:
        raise ValueError('不能删除脑图根节点')
    children_by_parent: dict[str, list[str]] = {}
    for uid, entry in entries.items():
        parent_uid = entry['parent_uid']
        if parent_uid is not None:
            children_by_parent.setdefault(parent_uid, []).append(uid)
    pending = [node_uid]
    while pending:
        current_uid = pending.pop()
        pending.extend(children_by_parent.get(current_uid, ()))
        entries.pop(current_uid, None)


def _group_extras_by_anchor_gap(
    sequence: list[str], anchor_set: set[str], extras: set[str], gap_count: int,
) -> list[set[str]]:
    groups = [set() for _ in range(gap_count)]
    gap_index = 0
    for uid in sequence:
        if uid in anchor_set:
            gap_index += 1
        elif uid in extras:
            groups[min(gap_index, gap_count - 1)].add(uid)
    return groups


def _merge_child_order(
    entries: dict[str, dict[str, Any]],
    node_uid: str,
    server_child_uids: list[str],
    old_child_uids: list[str],
    child_uids: list[str],
) -> None:
    old_set = set(old_child_uids)
    anchors = [
        uid
        for uid in child_uids
        if uid in old_set and entries.get(uid, {}).get('parent_uid') == node_uid
    ]
    anchor_set = set(anchors)
    server_extras = {
        uid
        for uid in server_child_uids
        if uid not in anchor_set and entries.get(uid, {}).get('parent_uid') == node_uid
    }
    local_extras = {
        uid
        for uid in child_uids
        if uid not in anchor_set and entries.get(uid, {}).get('parent_uid') == node_uid
    }
    gap_count = len(anchors) + 1
    server_groups = _group_extras_by_anchor_gap(
        server_child_uids, anchor_set, server_extras, gap_count,
    )
    local_groups = _group_extras_by_anchor_gap(
        child_uids, anchor_set, local_extras, gap_count,
    )
    merged_order = []
    for gap_index in range(gap_count):
        merged_order.extend(sorted(server_groups[gap_index] | local_groups[gap_index]))
        if gap_index < len(anchors):
            merged_order.append(anchors[gap_index])
    for sort_order, child_uid in enumerate(merged_order):
        entries[child_uid]['sort_order'] = sort_order


def _apply_children_delta(
    server_entries: dict[str, dict[str, Any]],
    client_entries: dict[str, dict[str, Any]],
    node_uid: str,
    payload: dict[str, Any],
    deleted_in_batch_uids: set[str],
) -> None:
    old_child_uids = _operation_child_uids(payload, 'oldChildUids', 'old_child_uids')
    child_uids = _operation_child_uids(payload, 'childUids', 'child_uids')
    if old_child_uids is None or child_uids is None:
        raise ValueError(f'节点结构操作缺少新旧子节点顺序: {node_uid}')
    if len(child_uids) != len(set(child_uids)):
        raise ValueError(f'节点子列表包含重复 UID: {node_uid}')
    if node_uid in child_uids:
        raise ValueError(f'节点不能成为自己的子节点: {node_uid}')

    server_child_uids = sorted(
        (
            uid
            for uid, entry in server_entries.items()
            if entry['parent_uid'] == node_uid
        ),
        key=lambda uid: (server_entries[uid]['sort_order'], uid),
    )
    old_set = set(old_child_uids)
    current_set = set(child_uids)
    added_set = current_set - old_set
    # 删除由 node.delete 原子删除子树，移动由目标父节点新增边完成。仅凭源父节点
    # children 中少了一个 UID 就把节点 parent 置空，会制造第二个根节点；如果后续
    # 删除/移动事件因快捷键批次边界尚未到达，必须暂时保留现有服务端父子关系。
    for child_uid in child_uids:
        child_entry = server_entries.get(child_uid)
        if not child_entry:
            # 客户端旧快照中已经存在、但服务端没有的节点不是本批新增，可能来自尚未
            # 落库的 Yjs 远端状态；没有对应 edge/create 操作时不得隐式写入。
            if child_uid not in added_set:
                continue
            local_child_entry = client_entries.get(child_uid)
            if not local_child_entry:
                # 快速创建后撤销时，操作日志会保留早先的新增边，但最终物化快照中
                # 已没有该临时节点。后续 node.delete 会完成语义闭环，无需构造一个
                # 已经不存在的中间节点。
                if child_uid in deleted_in_batch_uids:
                    continue
                raise ValueError(f'节点结构操作引用不存在的子节点: {child_uid}')
            child_entry = copy.deepcopy(local_child_entry)
            if payload.get('crossNodeDataSeparated', payload.get('cross_node_data_separated')) is True:
                _strip_cross_node_data(child_entry['node'])
            if payload.get('tagBindingsSeparated', payload.get('tag_bindings_separated')) is True:
                _strip_tag_bindings(child_entry['node'])
            server_entries[child_uid] = child_entry
        if child_uid in added_set:
            child_entry['parent_uid'] = node_uid
    _merge_child_order(
        server_entries, node_uid, server_child_uids, old_child_uids, child_uids,
    )


def _apply_node_update(
    server_entries: dict[str, dict[str, Any]],
    client_entries: dict[str, dict[str, Any]],
    node_uid: str,
    payload: dict[str, Any],
    deleted_in_batch_uids: set[str],
) -> None:
    local_entry = client_entries[node_uid]
    data_changed = payload.get('dataChanged', payload.get('data_changed'))
    children_changed = payload.get('childrenChanged', payload.get('children_changed'))
    if not isinstance(data_changed, bool) or not isinstance(children_changed, bool):
        # 旧客户端没有字段级语义，只能沿用整节点替换；并发分析会阻止其自动合并。
        server_entries[node_uid] = copy.deepcopy(local_entry)
        return
    if data_changed:
        local_node = copy.deepcopy(local_entry['node'])
        if payload.get('crossNodeDataSeparated', payload.get('cross_node_data_separated')) is True:
            server_data = server_entries[node_uid]['node'].get('data') or {}
            local_data = local_node.setdefault('data', {})
            for key in CROSS_NODE_DATA_KEYS:
                if key in server_data:
                    local_data[key] = copy.deepcopy(server_data[key])
                else:
                    local_data.pop(key, None)
        if payload.get('tagBindingsSeparated', payload.get('tag_bindings_separated')) is True:
            server_data = server_entries[node_uid]['node'].get('data') or {}
            local_data = local_node.setdefault('data', {})
            if TAG_BINDING_DATA_KEY in server_data:
                local_data[TAG_BINDING_DATA_KEY] = copy.deepcopy(server_data[TAG_BINDING_DATA_KEY])
            else:
                local_data.pop(TAG_BINDING_DATA_KEY, None)
        server_entries[node_uid]['node'] = local_node
    if children_changed:
        _apply_children_delta(
            server_entries,
            client_entries,
            node_uid,
            payload,
            deleted_in_batch_uids,
        )


def _strip_cross_node_data(node: dict[str, Any]) -> None:
    data = node.get('data')
    if not isinstance(data, dict):
        return
    for key in CROSS_NODE_DATA_KEYS:
        data.pop(key, None)


def _strip_tag_bindings(node: dict[str, Any]) -> None:
    data = node.get('data')
    if isinstance(data, dict):
        data.pop(TAG_BINDING_DATA_KEY, None)


def _payload_value(payload: dict[str, Any], camel_key: str, snake_key: str) -> Any:
    return payload.get(camel_key, payload.get(snake_key))


def _cross_record_key(prefix: str, record: dict[str, Any]) -> str:
    if prefix == 'relation':
        return str(record.get('relation_uid') or '')
    if prefix == 'summary':
        return f'{record.get("owner_uid") or ""}:{record.get("summary_uid") or ""}'
    if prefix == 'group':
        return str(record.get('group_uid') or '')
    return str(record.get('asset_key') or '')


def _normalize_cross_record(prefix: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = str(payload.get('key') or '')
    if not key or len(key) > 256:  # noqa: PLR2004
        raise ValueError(f'{prefix} 操作缺少合法稳定标识')
    if prefix == 'relation':
        source_uid = str(_payload_value(payload, 'sourceUid', 'source_uid') or '')
        target_uid = str(_payload_value(payload, 'targetUid', 'target_uid') or '')
        canonical_relation_uid = stable_relation_uid(source_uid, target_uid)
        supplied_relation_uid = str(
            _payload_value(payload, 'relationUid', 'relation_uid') or key
        )
        if supplied_relation_uid != key:
            raise ValueError(f'{prefix} 操作标识与载荷不一致')
        record = {
            'relation_uid': canonical_relation_uid,
            'relation_type': _payload_value(payload, 'relationType', 'relation_type') or 'associative_line',
            'source_uid': source_uid,
            'target_uid': target_uid,
            'text': payload.get('text'),
            'control_data': copy.deepcopy(_payload_value(payload, 'controlData', 'control_data') or {}),
            'style_data': copy.deepcopy(_payload_value(payload, 'styleData', 'style_data')),
            'sort_order': int(_payload_value(payload, 'sortOrder', 'sort_order') or 0),
        }
    elif prefix == 'summary':
        owner_uid = str(_payload_value(payload, 'ownerUid', 'owner_uid') or '')
        summary_uid = str(_payload_value(payload, 'summaryUid', 'summary_uid') or '')
        if not summary_uid and key.startswith(f'{owner_uid}:'):
            summary_uid = key[len(owner_uid) + 1:]
        record = {
            'summary_uid': summary_uid,
            'owner_uid': owner_uid,
            'start_child_uid': _payload_value(payload, 'startChildUid', 'start_child_uid'),
            'end_child_uid': _payload_value(payload, 'endChildUid', 'end_child_uid'),
            'payload': copy.deepcopy(payload.get('payload') or {}),
            'sort_order': int(_payload_value(payload, 'sortOrder', 'sort_order') or 0),
        }
    elif prefix == 'group':
        record = {
            'group_uid': str(_payload_value(payload, 'groupUid', 'group_uid') or key),
            'group_type': _payload_value(payload, 'groupType', 'group_type') or 'outer_frame',
            'payload': copy.deepcopy(payload.get('payload') or {}),
            'member_uids': [
                str(uid)
                for uid in (_payload_value(payload, 'memberUids', 'member_uids') or [])
                if uid
            ],
        }
    else:
        record = {
            'asset_key': str(_payload_value(payload, 'assetKey', 'asset_key') or key),
            'uri': copy.deepcopy(payload.get('uri')),
        }
    if prefix != 'relation' and _cross_record_key(prefix, record) != key:
        raise ValueError(f'{prefix} 操作标识与载荷不一致')
    return record


def _validate_relation_record(record: dict[str, Any], node_uids: set[str]) -> None:
    if record['relation_type'] != 'associative_line':
        raise ValueError('暂不支持该关联类型')
    if record['source_uid'] not in node_uids or record['target_uid'] not in node_uids:
        raise ValueError('关联线起点或终点不存在')
    if record['source_uid'] == record['target_uid']:
        raise ValueError('关联线不能指向自身')


def _validate_summary_record(
    record: dict[str, Any], node_uids: set[str], parent_by_uid: dict[str, str | None],
) -> None:
    owner_uid = record['owner_uid']
    if not record['summary_uid'] or owner_uid not in node_uids:
        raise ValueError('概要缺少稳定 UID 或所属节点不存在')
    for child_uid in (record.get('start_child_uid'), record.get('end_child_uid')):
        if child_uid is not None and parent_by_uid.get(str(child_uid)) != owner_uid:
            raise ValueError('概要范围必须引用所属节点的直接子节点')


def _validate_group_record(
    record: dict[str, Any],
    node_uids: set[str],
    parent_by_uid: dict[str, str | None],
    order_by_uid: dict[str, int],
) -> None:
    members = record['member_uids']
    if not members or len(members) != len(set(members)):
        raise ValueError('外框成员不能为空或重复')
    if any(uid not in node_uids for uid in members):
        raise ValueError('外框包含不存在的节点')
    parents = {parent_by_uid.get(uid) for uid in members}
    if len(parents) != 1:
        raise ValueError('外框成员必须属于同一父节点')
    if None in parents:
        raise ValueError('脑图根节点不能作为外框成员')
    orders = sorted(order_by_uid[uid] for uid in members)
    if orders != list(range(orders[0], orders[0] + len(orders))):
        raise ValueError('外框成员必须是连续的兄弟节点')


def _validate_cross_record(
    prefix: str,
    record: dict[str, Any],
    node_uids: set[str],
    parent_by_uid: dict[str, str | None],
    order_by_uid: dict[str, int],
) -> None:
    if prefix == 'relation':
        _validate_relation_record(record, node_uids)
    elif prefix == 'summary':
        _validate_summary_record(record, node_uids, parent_by_uid)
    elif prefix == 'group':
        _validate_group_record(record, node_uids, parent_by_uid, order_by_uid)
    elif record.get('uri') is None:
        raise ValueError('资源 URI 不能为空')


def _apply_cross_node_operations(
    server_tree: dict[str, Any], operations: list[dict[str, Any]],
) -> dict[str, Any]:
    encoded = SimpleMindDocumentCodec.encode(server_tree)
    node_uids = {str(row['node_uid']) for row in encoded.nodes}
    parent_by_uid = {
        str(row['node_uid']): str(row['parent_uid']) if row.get('parent_uid') is not None else None
        for row in encoded.nodes
    }
    order_by_uid = {str(row['node_uid']): int(row.get('sort_order') or 0) for row in encoded.nodes}
    collection_by_prefix = {
        'relation': encoded.relations,
        'summary': encoded.summaries,
        'group': encoded.groups,
        'asset': encoded.assets,
    }
    for operation in operations:
        operation_type = str(operation.get('type') or '')
        prefix, _, action = operation_type.partition('.')
        if operation_type not in CROSS_NODE_OPERATION_TYPES:
            continue
        payload = operation.get('payload')
        if not isinstance(payload, dict) or not payload.get('key'):
            raise ValueError(f'{operation_type} 缺少操作载荷')
        key = str(payload['key'])
        if prefix == 'relation':
            source_uid = str(_payload_value(payload, 'sourceUid', 'source_uid') or '')
            target_uid = str(_payload_value(payload, 'targetUid', 'target_uid') or '')
            # 旧客户端的 relation.delete 只发送稳定 key。只有端点齐全时才由
            # 端点重新推导；否则直接规范化 key，避免退化为无效的 "assoc::"。
            key = (
                stable_relation_uid(source_uid, target_uid)
                if source_uid and target_uid
                else normalize_relation_uid(key)
            )
        collection = collection_by_prefix[prefix]
        collection[:] = [row for row in collection if _cross_record_key(prefix, row) != key]
        if action == 'upsert':
            record = _normalize_cross_record(prefix, payload)
            _validate_cross_record(prefix, record, node_uids, parent_by_uid, order_by_uid)
            if prefix == 'group':
                record['parent_uid'] = parent_by_uid[record['member_uids'][0]]
            collection.append(record)
    rebuilt = SimpleMindDocumentCodec.decode(encoded)
    if not rebuilt:
        raise ValueError('跨节点操作执行后无法重建脑图')
    return rebuilt


def _normalize_tag_binding(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tag = payload.get('tag')
    if not isinstance(tag, dict):
        raise ValueError('标签绑定操作缺少标签身份数据')
    try:
        tag_id = int(tag.get('tagId'))
    except (TypeError, ValueError) as exc:
        raise ValueError('标签绑定缺少合法 tagId') from exc
    if tag_id <= 0:
        raise ValueError('标签绑定缺少合法 tagId')
    tag_key = str(_payload_value(payload, 'tagKey', 'tag_key') or '')
    if tag_key != str(tag_id):
        raise ValueError('标签绑定标识与 tagId 不一致')
    normalized: dict[str, Any] = {'tagId': tag_id}
    for field in ('placement', 'align'):
        if field in tag:
            normalized[field] = copy.deepcopy(tag[field])
    return tag_key, normalized


def _managed_tag_key(tag: Any) -> str | None:
    if not isinstance(tag, dict) or tag.get('tagId') is None:
        return None
    try:
        tag_id = int(tag['tagId'])
    except (TypeError, ValueError):
        return None
    return str(tag_id) if tag_id > 0 else None


def _apply_node_tag_operations(
    tree: dict[str, Any], client_tree: dict[str, Any], operations: list[dict[str, Any]],
) -> dict[str, Any]:
    entries, root_uid = _flatten_tree_for_merge(tree)
    client_entries, _ = _flatten_tree_for_merge(client_tree)
    for operation in operations:
        operation_type = str(operation.get('type') or '')
        if operation_type not in NODE_TAG_OPERATION_TYPES:
            continue
        node_uid = str(operation.get('nodeUid') or operation.get('node_uid') or '')
        entry = entries.get(node_uid)
        if not entry:
            raise ValueError(f'标签操作引用不存在的节点: {node_uid}')
        payload = operation.get('payload')
        if not isinstance(payload, dict):
            raise ValueError(f'{operation_type} 缺少操作载荷')
        data = entry['node'].setdefault('data', {})
        tags = list(data.get(TAG_BINDING_DATA_KEY) or [])
        if operation_type == 'node.tag.reorder':
            if str(payload.get('key') or '') != node_uid:
                raise ValueError('标签排序操作标识与节点不一致')
            tag_keys = [str(key) for key in payload.get('tagKeys', payload.get('tag_keys')) or []]
            if len(tag_keys) != len(set(tag_keys)):
                raise ValueError('标签排序包含重复标识')
            managed = {_managed_tag_key(tag): tag for tag in tags if _managed_tag_key(tag)}
            if set(tag_keys) != set(managed):
                raise ValueError('标签排序必须覆盖节点的全部受管标签')
            unmanaged = [tag for tag in tags if _managed_tag_key(tag) is None]
            data[TAG_BINDING_DATA_KEY] = [managed[key] for key in tag_keys] + unmanaged
            continue

        tag_key = str(_payload_value(payload, 'tagKey', 'tag_key') or '')
        if str(payload.get('key') or '') != f'{node_uid}:{tag_key}':
            raise ValueError('标签绑定操作标识与节点不一致')
        tags = [tag for tag in tags if _managed_tag_key(tag) != tag_key]
        if operation_type == 'node.tag.bind':
            _, binding = _normalize_tag_binding(payload)
            client_tags = client_entries.get(node_uid, {}).get('node', {}).get('data', {}).get('tag') or []
            client_tag = next(
                (copy.deepcopy(tag) for tag in client_tags if _managed_tag_key(tag) == tag_key),
                {},
            )
            tags.append({**client_tag, **binding})
        if tags:
            data[TAG_BINDING_DATA_KEY] = tags
        else:
            data.pop(TAG_BINDING_DATA_KEY, None)
    return _rebuild_tree_after_merge(entries, root_uid)


def _apply_single_node_operation(
    server_entries: dict[str, dict[str, Any]],
    client_entries: dict[str, dict[str, Any]],
    initial_server_uids: set[str],
    server_root_uid: str,
    operation: dict[str, Any],
    deleted_in_batch_uids: set[str],
) -> None:
    operation_type = operation.get('type')
    node_uid_value = operation.get('nodeUid') or operation.get('node_uid')
    if operation_type not in NODE_OPERATION_TYPES or not node_uid_value:
        raise ValueError(f'操作 {operation_type or "unknown"} 不支持自动并发合并')
    node_uid = str(node_uid_value)
    if operation_type == 'node.delete':
        _delete_server_subtree(server_entries, node_uid, server_root_uid)
        return

    local_entry = client_entries.get(node_uid)
    if not local_entry:
        if operation_type == 'node.create' and node_uid in deleted_in_batch_uids:
            return
        raise ValueError(f'客户端操作缺少节点数据: {node_uid}')
    payload = operation.get('payload') if isinstance(operation.get('payload'), dict) else {}
    if operation_type == 'node.create':
        if node_uid in server_entries:
            # 父节点结构事件可能先于 create，把新节点从客户端快照带入。
            if node_uid in initial_server_uids:
                # 同一稳定 UID 的创建可能已经由 Yjs 或另一个标签页送达。
                # 把它视为幂等重放；父边和后续 update 仍独立物化。
                return
            return
        new_entry = copy.deepcopy(local_entry)
        if payload.get('crossNodeDataSeparated', payload.get('cross_node_data_separated')) is True:
            _strip_cross_node_data(new_entry['node'])
        if payload.get('tagBindingsSeparated', payload.get('tag_bindings_separated')) is True:
            _strip_tag_bindings(new_entry['node'])
        server_entries[node_uid] = new_entry
        return

    if node_uid not in server_entries:
        raise ValueError(f'待更新节点不存在: {node_uid}')
    _apply_node_update(
        server_entries,
        client_entries,
        node_uid,
        payload,
        deleted_in_batch_uids,
    )


def merge_node_operations(
    server_tree: dict[str, Any], client_tree: dict[str, Any], operations: list[dict[str, Any]],
) -> dict[str, Any]:
    """把客户端节点操作应用到最新服务端树，避免用过期整树覆盖并发修改。"""
    server_entries, server_root_uid = _flatten_tree_for_merge(server_tree)
    client_entries, client_root_uid = _flatten_tree_for_merge(client_tree)
    if client_root_uid != server_root_uid:
        # 草稿恢复或旧客户端可能只重新生成了根 UID。根节点是文档锚点，
        # 仅当本批不修改根节点本身时将别名收敛到已锁定的服务端根；
        # 根节点编辑仍必须回到权威快照，避免旧草稿覆盖文档级内容。
        operation_node_uids = {
            str(operation.get('nodeUid') or operation.get('node_uid') or '')
            for operation in operations
        }
        if server_root_uid in client_entries or client_root_uid in operation_node_uids:
            raise ValueError('客户端与服务端的脑图根节点不一致')
        client_root_entry = client_entries.pop(client_root_uid)
        client_root_entry['uid'] = server_root_uid
        client_root_entry['node'].setdefault('data', {})['uid'] = server_root_uid
        client_entries[server_root_uid] = client_root_entry
        for entry in client_entries.values():
            if entry.get('parent_uid') == client_root_uid:
                entry['parent_uid'] = server_root_uid
    initial_server_uids = set(server_entries)
    deleted_in_batch_uids = {
        str(operation.get('nodeUid') or operation.get('node_uid'))
        for operation in operations
        if operation.get('type') == 'node.delete'
        and (operation.get('nodeUid') or operation.get('node_uid'))
    }

    for operation in operations:
        operation_type = operation.get('type')
        if operation_type in CROSS_NODE_OPERATION_TYPES | NODE_TAG_OPERATION_TYPES:
            continue
        _apply_single_node_operation(
            server_entries,
            client_entries,
            initial_server_uids,
            server_root_uid,
            operation,
            deleted_in_batch_uids,
        )

    merged_tree = _rebuild_tree_after_merge(server_entries, server_root_uid)
    tag_operations = [
        operation for operation in operations
        if operation.get('type') in NODE_TAG_OPERATION_TYPES
    ]
    if tag_operations:
        merged_tree = _apply_node_tag_operations(merged_tree, client_tree, tag_operations)
    cross_operations = [
        operation for operation in operations
        if operation.get('type') in CROSS_NODE_OPERATION_TYPES
    ]
    return _apply_cross_node_operations(merged_tree, cross_operations) if cross_operations else merged_tree


class MindmapService:
    """思维导图模块服务层"""

    @staticmethod
    async def _create_draft_version_safely(
        query_db: AsyncSession,
        mindmap_id: int,
        *,
        node_tree: dict[str, Any] | None,
        view_data: dict[str, Any] | None,
        layout: str | None,
        theme: dict[str, Any] | None,
        created_by: str,
    ) -> None:
        """在保存点内创建可选草稿，失败时不污染主内容保存事务。"""
        try:
            from module_mindmap.service.mindmap_version_service import MindmapVersionService  # noqa: PLC0415

            async with query_db.begin_nested():
                await MindmapVersionService.create_draft_version(
                    query_db,
                    mindmap_id,
                    node_tree=node_tree,
                    view_data=view_data,
                    layout=layout,
                    theme=theme,
                    created_by=created_by,
                )
        except Exception as exc:
            logger.warning(f'创建脑图草稿版本失败，主内容保存继续: {exc}')

    @classmethod
    async def resolve_mindmap_access(
        cls, db: AsyncSession, mindmap_id: int, user_id: int, require_edit: bool = False,
    ) -> tuple[Mindmap, int, bool]:
        """返回脑图与当前用户的有效权限，权限判定只在此处进行。"""
        mindmap = (
            await MindmapDao.get_mindmap_for_update(db, mindmap_id)
            if require_edit
            else await MindmapDao.get_mindmap_by_id(db, mindmap_id)
        )
        if not mindmap:
            raise ServiceException(message='思维导图不存在')

        is_owner = mindmap.owner_id == user_id
        permission = 1 if is_owner else await MindmapCollaboratorDao.get_collaborator_permission(
            db, mindmap_id, user_id,
        )
        if permission is None or (require_edit and permission < 1):
            raise ServiceException(message='无编辑权限' if require_edit else '无访问权限')
        if require_edit and mindmap.status == 1:
            raise ServiceException(message='脑图已归档，请恢复后再编辑')
        if require_edit and await MindmapDao.get_migration_status(db, mindmap_id) == 'failed':
            raise ServiceException(message='脑图结构化迁移失败，当前仅可只读访问，请联系管理员重试迁移')
        return mindmap, permission, is_owner

    @classmethod
    async def check_mindmap_access(
        cls, db: AsyncSession, mindmap_id: int, user_id: int, require_edit: bool = False,
    ) -> Mindmap:
        """统一的脑图访问权限检查

        检查用户是否为脑图所有者，或是否有协作者权限。

        :param db: 数据库会话
        :param mindmap_id: 脑图ID
        :param user_id: 用户ID
        :param require_edit: True 则要求编辑权限，False 只需查看权限
        :return: 脑图记录
        :raises ServiceException: 无权限时抛出
        """
        mindmap, _, _ = await cls.resolve_mindmap_access(
            db, mindmap_id, user_id, require_edit=require_edit,
        )
        return mindmap

    @classmethod
    async def get_mindmap_list_services(
        cls, query_db: AsyncSession, query_object: MindmapPageQueryModel, is_page: bool = True
    ) -> PageModel | list[dict[str, Any]]:
        """获取思维导图列表"""
        result = await MindmapDao.get_mindmap_list(query_db, query_object, is_page)
        if isinstance(result, PageModel):
            result.rows = [
                MindmapListItemModel.model_validate(row).model_dump(by_alias=True)
                for row in result.rows
            ]
            return result
        return [
            MindmapListItemModel.model_validate(row).model_dump(by_alias=True)
            for row in result
        ]

    @classmethod
    @observe_mindmap_operation(
        'detail_load',
        outcome_getter=_detail_metric_outcome,
        work_units_getter=_detail_metric_units,
        result_hook=_detail_metric_hook,
    )
    async def get_mindmap_detail_services(cls, query_db: AsyncSession, mindmap_id: int, user_id: int) -> MindmapModel:
        """获取思维导图详细信息（含所有权校验）"""
        mindmap, permission, is_owner = await cls.resolve_mindmap_access(
            query_db, mindmap_id, user_id, require_edit=False,
        )

        result_dict = CamelCaseUtil.transform_result(mindmap)
        migration_failed = await MindmapDao.get_migration_status(query_db, mindmap_id) == 'failed'
        result_dict.update({
            'accessType': 'owned' if is_owner else 'shared',
            'effectivePermission': permission,
            'isOwner': is_owner,
            'canEdit': permission >= 1 and not migration_failed and mindmap.status == 0,
            'contentState': 'migration_failed' if migration_failed else 'ready',
            'contentStateMessage': (
                '结构化迁移未通过一致性校验，已回退到旧数据只读展示'
                if migration_failed else None
            ),
        })
        if not migration_failed and getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION:
            try:
                structured_tree = await MindmapDocumentService.load_tree(
                    query_db, mindmap_id, required=True,
                )
                result_dict['nodeTree'] = structured_tree
                result_dict['node_tree'] = structured_tree
                result_dict['nodeRevisions'] = await MindmapContentDao.get_node_revisions(
                    query_db, mindmap_id,
                )
            except ServiceException as exc:
                logger.warning(
                    f'读取结构化脑图失败，回退node_tree: mindmap_id={mindmap_id}, error={exc.message}',
                )
                result_dict.update({
                    'canEdit': False,
                    'contentState': 'integrity_failed',
                    'contentStateMessage': STRUCTURED_CONTENT_CORRUPT_MESSAGE,
                })
            except Exception as exc:
                logger.warning(
                    f'读取结构化脑图暂时失败，回退node_tree: mindmap_id={mindmap_id}, error={exc}',
                )
                result_dict.update({
                    'canEdit': False,
                    'contentState': 'load_failed',
                    'contentStateMessage': '脑图结构化内容暂时无法读取，请稍后重试',
                })
        if isinstance(result_dict.get('nodeTree'), str):
            result_dict['nodeTree'] = json.loads(result_dict['nodeTree'])
        if isinstance(result_dict.get('node_tree'), str):
            result_dict['node_tree'] = json.loads(result_dict['node_tree'])
        return MindmapModel(**result_dict)

    @classmethod
    async def search_nodes_services(
        cls, query_db: AsyncSession, mindmap_id: int, user_id: int,
        keyword: str | None = None, tag_id: int | None = None,
        page_num: int = 1, page_size: int = 20,
    ) -> PageModel:
        """在结构化节点表内搜索文本并按统一标签筛选。"""
        await cls.check_mindmap_access(query_db, mindmap_id, user_id, require_edit=False)
        parent = aliased(MindmapNode)
        query = (
            select(
                MindmapNode.id,
                MindmapNode.node_uid,
                MindmapNode.text_plain,
                MindmapNode.node_revision,
                parent.node_uid.label('parent_uid'),
            )
            .outerjoin(parent, parent.id == MindmapNode.parent_id)
            .where(MindmapNode.file_id == mindmap_id, MindmapNode.is_deleted == 0)
        )
        if keyword and keyword.strip():
            escaped = keyword.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            query = query.where(MindmapNode.text_plain.like(f'%{escaped}%'))
        if tag_id:
            query = query.join(
                MindmapNodeTag,
                (MindmapNodeTag.node_id == MindmapNode.id) & (MindmapNodeTag.tag_id == tag_id),
            )
        query = query.order_by(MindmapNode.update_time.desc(), MindmapNode.id)
        total = (await query_db.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar_one()
        rows = (await query_db.execute(
            query.offset((page_num - 1) * page_size).limit(page_size)
        )).all()
        node_ids = [row.id for row in rows]
        paths_by_node = await cls._load_node_paths(query_db, node_ids, file_id=mindmap_id)
        tag_rows = (await query_db.execute(
            select(MindmapNodeTag, MindmapTag)
            .join(MindmapTag, MindmapTag.id == MindmapNodeTag.tag_id)
            .where(MindmapNodeTag.node_id.in_(node_ids))
            .order_by(MindmapNodeTag.node_id, MindmapNodeTag.sort_order)
        )).all() if node_ids else []
        tags_by_node: dict[int, list[dict[str, Any]]] = {}
        for binding, tag in tag_rows:
            resolved_tag = {
                'tagId': tag.id,
                'text': tag.name,
                'style': dict(tag.style or {}),
                'status': tag.status,
                'definitionRevision': tag.definition_revision,
            }
            tags_by_node.setdefault(binding.node_id, []).append(resolved_tag)
        return PageModel(
            rows=[{
                'id': row.id,
                'nodeUid': row.node_uid,
                'parentUid': row.parent_uid,
                'text': row.text_plain,
                'nodeRevision': row.node_revision,
                'tags': tags_by_node.get(row.id, []),
                'path': paths_by_node.get(row.id, []),
                'pathText': ' / '.join(
                    item['text'] for item in paths_by_node.get(row.id, []) if item['text']
                ),
            } for row in rows],
            pageNum=page_num,
            pageSize=page_size,
            total=total,
            hasNext=page_num * page_size < total,
        )

    @classmethod
    async def search_global_nodes_services(
        cls,
        query_db: AsyncSession,
        user_id: int,
        keyword: str,
        page_num: int = 1,
        page_size: int = 20,
    ) -> PageModel:
        """跨当前用户可访问的有效文件搜索节点，并返回所属文件与完整路径。"""
        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            raise ServiceException(message='请输入节点搜索关键词')

        effective_permission = case(
            (Mindmap.owner_id == user_id, literal(1)),
            else_=MindmapCollaborator.permission,
        )
        access_type = case(
            (Mindmap.owner_id == user_id, literal('owned')),
            else_=literal('shared'),
        )
        query = (
            select(
                MindmapNode.id,
                MindmapNode.node_uid,
                MindmapNode.text_plain,
                MindmapNode.file_id,
                Mindmap.name.label('mindmap_name'),
                Mindmap.status,
                SysUser.nick_name.label('owner_name'),
                access_type.label('access_type'),
                effective_permission.label('effective_permission'),
            )
            .join(Mindmap, Mindmap.id == MindmapNode.file_id)
            .outerjoin(
                MindmapCollaborator,
                and_(
                    MindmapCollaborator.mindmap_id == Mindmap.id,
                    MindmapCollaborator.user_id == user_id,
                ),
            )
            .outerjoin(SysUser, SysUser.user_id == Mindmap.owner_id)
            .outerjoin(MindmapMigrationRecord, MindmapMigrationRecord.file_id == Mindmap.id)
            .where(
                or_(Mindmap.owner_id == user_id, MindmapCollaborator.user_id == user_id),
                Mindmap.del_flag == '0',
                Mindmap.status.in_([0, 1]),
                MindmapNode.is_deleted == 0,
                MindmapNode.text_plain.contains(normalized_keyword, autoescape=True),
                or_(
                    MindmapMigrationRecord.status.is_(None),
                    MindmapMigrationRecord.status != 'failed',
                ),
            )
            .order_by(
                Mindmap.update_time.desc(),
                Mindmap.id.desc(),
                MindmapNode.update_time.desc(),
                MindmapNode.id,
            )
        )
        total = (await query_db.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )).scalar_one()
        rows = (await query_db.execute(
            query.offset((page_num - 1) * page_size).limit(page_size)
        )).all()
        node_ids = [row.id for row in rows]
        paths_by_node = await cls._load_node_paths(query_db, node_ids)
        return PageModel(
            rows=[{
                'id': row.id,
                'nodeUid': row.node_uid,
                'text': row.text_plain or '',
                'mindmapId': row.file_id,
                'mindmapName': row.mindmap_name,
                'ownerName': row.owner_name,
                'accessType': row.access_type,
                'effectivePermission': row.effective_permission,
                'status': row.status,
                'canEdit': row.status == 0 and int(row.effective_permission or 0) >= 1,
                'path': paths_by_node.get(row.id, []),
                'pathText': ' / '.join(
                    item['text'] for item in paths_by_node.get(row.id, []) if item['text']
                ),
            } for row in rows],
            pageNum=page_num,
            pageSize=page_size,
            total=total,
            hasNext=page_num * page_size < total,
        )

    @staticmethod
    async def _load_node_paths(
        db: AsyncSession,
        node_ids: list[int],
        *,
        file_id: int | None = None,
    ) -> dict[int, list[dict[str, Any]]]:
        """用一个递归 CTE 批量读取单文件或跨文件搜索结果的祖先路径。"""
        if not node_ids:
            return {}
        seed = select(
            MindmapNode.id.label('origin_id'),
            MindmapNode.id.label('node_id'),
            MindmapNode.file_id.label('file_id'),
            MindmapNode.parent_id.label('parent_id'),
            MindmapNode.node_uid.label('node_uid'),
            MindmapNode.text_plain.label('text'),
            literal(0).label('depth'),
        ).where(
            MindmapNode.id.in_(node_ids),
            MindmapNode.is_deleted == 0,
        )
        if file_id is not None:
            seed = seed.where(MindmapNode.file_id == file_id)
        ancestor_chain = seed.cte('mindmap_node_ancestor_chain', recursive=True)
        parent = aliased(MindmapNode)
        ancestor_chain = ancestor_chain.union_all(select(
            ancestor_chain.c.origin_id,
            parent.id,
            parent.file_id,
            parent.parent_id,
            parent.node_uid,
            parent.text_plain,
            ancestor_chain.c.depth + 1,
        ).join(
            parent,
            and_(
                parent.id == ancestor_chain.c.parent_id,
                parent.file_id == ancestor_chain.c.file_id,
            ),
        ).where(
            parent.is_deleted == 0,
            ancestor_chain.c.depth < MAX_TREE_DEPTH,
        ))
        path_rows = (await db.execute(select(
            ancestor_chain.c.origin_id,
            ancestor_chain.c.node_uid,
            ancestor_chain.c.text,
            ancestor_chain.c.depth,
        ).order_by(
            ancestor_chain.c.origin_id,
            ancestor_chain.c.depth.desc(),
        ))).all()
        paths: dict[int, list[dict[str, Any]]] = {}
        for row in path_rows:
            paths.setdefault(row.origin_id, []).append({
                'nodeUid': row.node_uid,
                'text': row.text or '',
            })
        return paths

    @staticmethod
    def _prepare_mindmap_insert_data(page_object: MindmapModel) -> dict[str, Any]:
        page_data = page_object.model_dump(exclude_none=True)
        insert_data = {
            key: value
            for key, value in page_data.items()
            if key in MINDMAP_CREATION_ALLOWED_FIELDS
        }
        insert_data['status'] = 0
        if isinstance(insert_data.get('node_tree'), dict):
            insert_data['node_tree'] = json.dumps(insert_data['node_tree'], ensure_ascii=False)
        insert_data.pop('id', None)
        return insert_data

    @classmethod
    async def _find_mindmap_creation_replay(
        cls,
        query_db: AsyncSession,
        *,
        owner_id: int,
        creation_request_id: str,
        creation_operation: str,
        creation_intent: dict[str, Any],
    ) -> tuple[MindmapCreationContext, CrudResponseModel | None]:
        context = MindmapCreationService.build_context(
            creation_request_id,
            creation_operation,
            creation_intent,
        )
        existing_request = await MindmapCreationDao.get_by_owner_and_request(
            query_db,
            owner_id,
            context.request_id,
        )
        replay = (
            MindmapCreationService.resolve_replay(existing_request, context)
            if existing_request
            else None
        )
        return context, replay

    @classmethod
    async def _resolve_mindmap_creation_context(
        cls,
        query_db: AsyncSession,
        page_object: MindmapModel,
        insert_data: dict[str, Any],
        creation_request_id: str | None,
        creation_operation: str,
        creation_intent: dict[str, Any] | None,
    ) -> tuple[MindmapCreationContext | None, CrudResponseModel | None]:
        if creation_request_id is None:
            return None, None
        owner_id = insert_data.get('owner_id')
        if not isinstance(owner_id, int) or isinstance(owner_id, bool) or owner_id <= 0:
            raise ServiceException(message='脑图所有者无效')
        if creation_intent is None:
            creation_intent = {
                key: value
                for key, value in page_object.model_dump(mode='json', exclude_none=True).items()
                if key in MINDMAP_CREATION_ALLOWED_FIELDS
                and key not in MINDMAP_CREATION_AUDIT_FIELDS
            }
        return await cls._find_mindmap_creation_replay(
            query_db,
            owner_id=owner_id,
            creation_request_id=creation_request_id,
            creation_operation=creation_operation,
            creation_intent=creation_intent,
        )

    @classmethod
    async def add_mindmap_services(
        cls,
        query_db: AsyncSession,
        page_object: MindmapModel,
        *,
        creation_request_id: str | None = None,
        creation_operation: str = 'blank',
        creation_intent: dict[str, Any] | None = None,
    ) -> CrudResponseModel:
        """新增思维导图"""
        # Only creation-safe fields cross the service boundary. Derived
        # revision/root/count/ownership fields must not be assigned by
        # an untrusted create payload.
        insert_data = cls._prepare_mindmap_insert_data(page_object)
        context, replay = await cls._resolve_mindmap_creation_context(
            query_db,
            page_object,
            insert_data,
            creation_request_id,
            creation_operation,
            creation_intent,
        )
        if replay is not None:
            return replay

        # 校验文件夹归属
        if insert_data.get('folder_id'):
            folder = await MindmapFolderDao.get_folder_by_id(
                query_db,
                insert_data['folder_id'],
                insert_data['owner_id'],
                for_update=True,
            )
            if not folder:
                raise ServiceException(message='目标文件夹不存在或无权限')

        try:
            creation_record = None
            if context is not None:
                creation_record = await MindmapCreationDao.add_request(
                    query_db,
                    owner_id=insert_data['owner_id'],
                    request_id=context.request_id,
                    operation=context.operation,
                    request_fingerprint=context.request_fingerprint,
                    created_by=page_object.create_by,
                )
            new_mindmap = await MindmapDao.add_mindmap_dao(query_db, insert_data)
            # flush() 后主键 ID 立即可用，在 commit 前获取
            new_id = new_mindmap.id
            if page_object.node_tree:
                metadata = await MindmapDocumentService.persist_tree(
                    query_db,
                    new_id,
                    page_object.node_tree,
                    owner_id=page_object.owner_id,
                    operator=page_object.create_by or str(page_object.owner_id),
                )
                await MindmapDao.edit_mindmap_dao(query_db, {'id': new_id, **metadata})
            if creation_record is not None:
                await MindmapCreationDao.complete_request(
                    query_db,
                    creation_record.id,
                    new_id,
                )
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='新增成功', result={'id': new_id})
        except IntegrityError:
            await query_db.rollback()
            if context is not None:
                existing_request = await MindmapCreationDao.get_by_owner_and_request(
                    query_db,
                    insert_data['owner_id'],
                    context.request_id,
                )
                if existing_request:
                    return MindmapCreationService.resolve_replay(existing_request, context)
            raise
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def edit_mindmap_services(
        cls, query_db: AsyncSession, page_object: MindmapModel, user_id: int,
    ) -> CrudResponseModel:
        """编辑思维导图元数据（名称、描述、封面等）"""
        await cls.check_mindmap_access(query_db, page_object.id, user_id, require_edit=True)

        try:
            # 防御性排除：特权字段（owner_id、审计字段、版本计数等）禁止客户端修改，
            # 防止 Mass Assignment 攻击导致所有权劫持或数据篡改
            update_data = page_object.model_dump(
                exclude_unset=True,
                exclude={
                    'node_tree', 'view_data',       # 大内容字段，由 auto-save 端点单独处理
                    'root_node_id', 'content_revision', 'node_count',
                    'schema_version', 'engine_name', 'engine_version',
                    'document_data', 'node_revisions',
                    'owner_id',                      # 所有权：只能由 add_mindmap 设置
                    'status',                        # 状态只能通过归档接口修改
                    'version_count', 'last_version_id',  # 由版本服务维护
                    'create_by', 'create_time',      # 审计字段：创建时一次性写入
                    'folder_id',                     # 文件夹归属：仅通过 /mindmap/move 端点修改
                },
            )
            # id 保留在 update_data 中供 DAO 的 WHERE 子句使用，不会被 SET 覆盖
            await MindmapDao.edit_mindmap_dao(query_db, update_data)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='更新成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def update_content_services(
        cls,
        query_db: AsyncSession,
        page_object: MindmapContentUpdateModel,
        user_id: int,
        user_name: str | None = None,
    ) -> CrudResponseModel:
        """更新思维导图内容（自动保存端点）"""
        await cls.check_mindmap_access(query_db, page_object.id, user_id, require_edit=True)
        operator = user_name or str(user_id)

        # Serialize node_tree to JSON string
        update_data = {
            'update_by': operator,
            'update_time': datetime.now(),
        }
        if page_object.node_tree is not None:
            update_data['node_tree'] = json.dumps(page_object.node_tree, ensure_ascii=False)
        if page_object.view_data is not None:
            update_data['view_data'] = page_object.view_data
        if page_object.layout is not None:
            update_data['layout'] = page_object.layout
        if page_object.theme is not None:
            update_data['theme'] = page_object.theme
        if page_object.document_data is not None:
            update_data['document_data'] = page_object.document_data

        try:
            mindmap = await MindmapDao.get_mindmap_for_update(query_db, page_object.id)
            if not mindmap:
                raise ServiceException(message='思维导图不存在')
            mutation_id = page_object.client_mutation_id or f'compat-{uuid.uuid4()}'
            previous = await MindmapContentDao.get_change_by_mutation(
                query_db, page_object.id, mutation_id,
            )
            if previous:
                result = {**(previous.result_data or {}), 'idempotentReplay': True}
                await query_db.rollback()
                return CrudResponseModel(is_success=True, message='保存成功', result=result)
            if page_object.base_revision is not None and page_object.base_revision != mindmap.content_revision:
                raise ServiceWarning(
                    message='脑图内容版本冲突，请刷新后重试',
                    data={'currentRevision': mindmap.content_revision},
                )
            if page_object.node_tree is not None:
                if getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION:
                    await MindmapDocumentService.load_tree(
                        query_db, page_object.id, required=True,
                    )
                metadata = await MindmapDocumentService.persist_tree_incremental(
                    query_db,
                    page_object.id,
                    page_object.node_tree,
                    owner_id=mindmap.owner_id,
                    operator=operator,
                )
                changed_nodes = metadata.pop('changed_nodes', [])
                update_data.update(metadata)
                update_data['content_revision'] = mindmap.content_revision + 1
            await MindmapDao.update_content_dao(query_db, page_object.id, update_data)

            result_data = {
                'contentRevision': update_data.get('content_revision', mindmap.content_revision),
                'schemaVersion': update_data.get('schema_version', mindmap.schema_version),
                'nodeCount': update_data.get('node_count', mindmap.node_count),
                'clientMutationId': mutation_id,
                'changedNodes': changed_nodes if page_object.node_tree is not None else [],
                'idempotentReplay': False,
            }
            query_db.add(MindmapChangeLog(
                file_id=page_object.id,
                base_revision=mindmap.content_revision,
                revision=result_data['contentRevision'],
                client_mutation_id=mutation_id,
                operations=[{'type': 'document.replace_compat'}],
                result_data=result_data,
                created_by=operator,
                created_time=datetime.now(),
            ))

            # 草稿失败只回滚自身保存点，不能让已完成的主内容保存进入失败态。
            await cls._create_draft_version_safely(
                query_db,
                page_object.id,
                node_tree=page_object.node_tree,
                view_data=page_object.view_data,
                layout=page_object.layout,
                theme=page_object.theme,
                created_by=operator,
            )

            # 统一提交：内容更新 + 草稿版本创建
            await query_db.commit()

            return CrudResponseModel(is_success=True, message='保存成功', result=result_data)
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    @observe_mindmap_operation(
        'content_batch_save',
        outcome_getter=_batch_save_metric_outcome,
        work_units_getter=_batch_save_metric_units,
        result_hook=_batch_save_metric_hook,
    )
    async def update_content_batch_services(  # noqa: PLR0912, PLR0915
        cls,
        query_db: AsyncSession,
        mindmap_id: int,
        page_object: MindmapContentBatchModel,
        user_id: int,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """幂等、带乐观锁的结构化内容增量保存。"""
        await cls.check_mindmap_access(query_db, mindmap_id, user_id, require_edit=True)
        operator = user_name or str(user_id)
        try:
            mindmap = await MindmapDao.get_mindmap_for_update(query_db, mindmap_id)
            if not mindmap:
                raise ServiceException(message='思维导图不存在')

            previous = await MindmapContentDao.get_change_by_mutation(
                query_db, mindmap_id, page_object.client_mutation_id,
            )
            if previous:
                result = {**(previous.result_data or {}), 'idempotentReplay': True}
                await query_db.rollback()
                return result

            request_operations = [
                item.model_dump(by_alias=True, exclude_none=True)
                for item in page_object.operations
            ]
            tree_operations = [
                operation
                for operation in request_operations
                if operation.get('type') in TREE_OPERATION_TYPES
            ]
            file_fields = {
                field
                for operation in request_operations
                if (field := FILE_OPERATION_FIELDS.get(operation.get('type')))
            }
            legacy_document_update = any(
                operation.get('type') == 'document.update'
                for operation in request_operations
            )
            content_snapshot_update = any(
                operation.get('type') == 'document.content.update'
                for operation in request_operations
            )
            document_snapshot_update = legacy_document_update or content_snapshot_update
            should_persist_tree = bool(tree_operations or document_snapshot_update)
            materialized_tree = page_object.node_tree
            concurrent_merge = False
            if page_object.base_revision != mindmap.content_revision:
                changes = await MindmapContentDao.get_changes_after(
                    query_db, mindmap_id, page_object.base_revision,
                )
                remote_operations = [
                    operation
                    for change in changes
                    for operation in (change.operations or [])
                ]
                history_complete = is_change_history_complete(
                    changes,
                    page_object.base_revision,
                    mindmap.content_revision,
                )
                merge_analysis = analyze_concurrent_operations(
                    request_operations,
                    remote_operations,
                    history_complete,
                )
                if not merge_analysis['mergeable']:
                    raise ServiceWarning(
                        message='脑图内容版本冲突，需要重新加载或人工合并',
                        data={
                            'currentRevision': mindmap.content_revision,
                            'baseRevision': page_object.base_revision,
                            **merge_analysis,
                        },
                    )
                concurrent_merge = True

            server_tree = None
            if should_persist_tree and getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION:
                server_tree = await MindmapDocumentService.load_tree(
                    query_db, mindmap_id, required=True,
                )

            # nodeTree 只是客户端物化快照，真正的写入来源必须是 operations。即便文件
            # revision 尚未变化，也不能把 Yjs 收到但未进入本地操作日志的远端内容带入。
            if tree_operations and not document_snapshot_update:
                if not server_tree:
                    server_tree = mindmap.node_tree
                    if isinstance(server_tree, str):
                        server_tree = json.loads(server_tree)
                try:
                    materialized_tree = merge_node_operations(
                        server_tree, page_object.node_tree, tree_operations,
                    )
                except ValueError as exc:
                    raise ServiceWarning(
                        message=f'脑图内容无法自动合并: {exc}',
                        data={
                            'currentRevision': mindmap.content_revision,
                            'baseRevision': page_object.base_revision,
                            'requiresSnapshot': True,
                        },
                    ) from exc
            elif concurrent_merge:
                materialized_tree = server_tree or await MindmapDocumentService.load_tree(
                    query_db,
                    mindmap_id,
                    required=getattr(mindmap, 'schema_version', 1) >= SCHEMA_VERSION,
                )
                if not materialized_tree:
                    materialized_tree = mindmap.node_tree
                    if isinstance(materialized_tree, str):
                        materialized_tree = json.loads(materialized_tree)

            # 并发分支已经基于完整变更日志做过字段/边级冲突分析。此时整节点 revision
            # 可能仅因另一用户新增子节点而变化，不能再次否决本地的节点属性修改。
            target_revisions = {} if concurrent_merge else {
                operation.node_uid: operation.target_revision
                for operation in page_object.operations
                if operation.node_uid and operation.target_revision is not None
            }
            node_conflicts = []
            if target_revisions:
                nodes = list((await query_db.execute(
                    select(MindmapNode).where(
                        MindmapNode.file_id == mindmap_id,
                        MindmapNode.node_uid.in_(target_revisions),
                    )
                )).scalars())
                actual = {node.node_uid: node.node_revision for node in nodes}
                node_conflicts = [
                    {'nodeUid': uid, 'expectedRevision': expected, 'actualRevision': actual.get(uid)}
                    for uid, expected in target_revisions.items()
                    if actual.get(uid) != expected
                ]
            if node_conflicts:
                raise ServiceWarning(
                    message='节点版本冲突，请先合并服务端变更',
                    data={
                        'currentRevision': mindmap.content_revision,
                        'conflictNodes': node_conflicts,
                    },
                )

            if should_persist_tree:
                metadata = await MindmapDocumentService.persist_tree_incremental(
                    query_db,
                    mindmap_id,
                    materialized_tree,
                    owner_id=mindmap.owner_id,
                    operator=operator,
                )
                changed_nodes = metadata.pop('changed_nodes', [])
            else:
                metadata = {
                    'root_node_id': mindmap.root_node_id,
                    'node_count': mindmap.node_count,
                    'schema_version': mindmap.schema_version,
                    'engine_name': mindmap.engine_name,
                    'engine_version': mindmap.engine_version,
                }
                changed_nodes = []
            new_revision = mindmap.content_revision + 1
            update_data = {
                **metadata,
                'content_revision': new_revision,
                'update_by': operator,
                'update_time': datetime.now(),
            }
            if should_persist_tree:
                update_data['node_tree'] = json.dumps(materialized_tree, ensure_ascii=False)
            if 'view_data' in file_fields or legacy_document_update:
                update_data['view_data'] = page_object.view_data
            if ('layout' in file_fields or document_snapshot_update) and page_object.layout is not None:
                update_data['layout'] = page_object.layout
            if ('theme' in file_fields or document_snapshot_update) and page_object.theme is not None:
                update_data['theme'] = page_object.theme
            should_update_document_data = (
                'document_data' in file_fields
                or (document_snapshot_update and page_object.document_data is not None)
            )
            if should_update_document_data:
                update_data['document_data'] = page_object.document_data
            await MindmapDao.update_content_dao(query_db, mindmap_id, update_data)

            effective_layout = (
                page_object.layout
                if 'layout' in file_fields or document_snapshot_update
                else mindmap.layout
            )
            effective_theme = (
                page_object.theme
                if 'theme' in file_fields or document_snapshot_update
                else mindmap.theme
            )
            effective_view = (
                page_object.view_data
                if 'view_data' in file_fields or legacy_document_update
                else mindmap.view_data
            )
            effective_document_data = (
                page_object.document_data
                if should_update_document_data
                else mindmap.document_data
            )

            result = {
                'contentRevision': new_revision,
                'schemaVersion': metadata['schema_version'],
                'nodeCount': metadata['node_count'],
                'clientMutationId': page_object.client_mutation_id,
                'changedNodes': changed_nodes,
                'idempotentReplay': False,
                'concurrentMerge': concurrent_merge,
                'layout': effective_layout,
                'theme': effective_theme,
                'viewData': effective_view,
                'documentData': effective_document_data,
            }
            if concurrent_merge:
                result['nodeTree'] = materialized_tree
            result['nodeRevisions'] = await MindmapContentDao.get_node_revisions(query_db, mindmap_id)
            query_db.add(MindmapChangeLog(
                file_id=mindmap_id,
                base_revision=page_object.base_revision,
                revision=new_revision,
                client_mutation_id=page_object.client_mutation_id,
                operations=request_operations,
                result_data=result,
                created_by=operator,
                created_time=datetime.now(),
            ))
            await cls._create_draft_version_safely(
                query_db,
                mindmap_id,
                node_tree=materialized_tree,
                view_data=effective_view,
                layout=effective_layout,
                theme=effective_theme,
                created_by=operator,
            )
            await query_db.commit()
            try:
                from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

                room_manager.set_content_revision(mindmap_id, new_revision)
                await room_manager.broadcast(mindmap_id, {
                    'type': 'content_revision_changed',
                    'contentRevision': new_revision,
                    'clientMutationId': page_object.client_mutation_id,
                    'concurrentMerge': concurrent_merge,
                })
            except Exception as exc:
                # HTTP 保存已提交，实时通知失败不能反向回滚主数据。
                record_mindmap_event('broadcast_failure')
                logger.warning(f'广播脑图 revision 变更失败: {exc}')
            return result
        except (ServiceException, ServiceWarning):
            await query_db.rollback()
            raise
        except Exception:
            await query_db.rollback()
            raise

    @classmethod
    async def update_view_services(
        cls,
        query_db: AsyncSession,
        mindmap_id: int,
        page_object: MindmapViewUpdateModel,
        user_id: int,
    ) -> dict[str, Any]:
        """保存非语义视图状态；不占用正文 revision，也不触发协作重校准。"""
        await cls.check_mindmap_access(query_db, mindmap_id, user_id, require_edit=True)
        try:
            await MindmapDao.update_content_dao(
                query_db,
                mindmap_id,
                {'view_data': page_object.view_data},
            )
            await query_db.commit()
            return {'viewData': page_object.view_data}
        except Exception:
            await query_db.rollback()
            raise

    @classmethod
    async def get_content_changes_services(
        cls,
        query_db: AsyncSession,
        mindmap_id: int,
        after_revision: int,
        user_id: int,
    ) -> dict[str, Any]:
        """返回断线期间的有序增量操作。"""
        mindmap = await cls.check_mindmap_access(query_db, mindmap_id, user_id, require_edit=False)
        changes = await MindmapContentDao.get_changes_after(
            query_db, mindmap_id, after_revision, limit=CHANGE_PAGE_SIZE,
        )
        expected_revision = after_revision + 1
        requires_snapshot = False
        for row in changes:
            if row.revision != expected_revision:
                requires_snapshot = True
                break
            expected_revision += 1
        if (
            (after_revision < mindmap.content_revision and not changes)
            or (len(changes) < CHANGE_PAGE_SIZE and expected_revision <= mindmap.content_revision)
        ):
            requires_snapshot = True
        return {
            'fileId': mindmap_id,
            'afterRevision': after_revision,
            'currentRevision': mindmap.content_revision,
            'changes': [
                {
                    'baseRevision': row.base_revision,
                    'revision': row.revision,
                    'clientMutationId': row.client_mutation_id,
                    'operations': row.operations,
                    'createdTime': row.created_time,
                }
                for row in changes
            ],
            'hasMore': (
                len(changes) == CHANGE_PAGE_SIZE
                and changes[-1].revision < mindmap.content_revision
            ),
            'requiresSnapshot': requires_snapshot,
        }

    @classmethod
    async def rename_mindmap_services(
        cls, query_db: AsyncSession, page_object: MindmapRenameModel, user_id: int
    ) -> CrudResponseModel:
        """重命名思维导图"""
        await cls.check_mindmap_access(query_db, page_object.id, user_id, require_edit=True)

        try:
            await MindmapDao.edit_mindmap_dao(query_db, {
                'id': page_object.id,
                'name': page_object.name,
                'update_time': datetime.now(),
            })
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='重命名成功')
        except Exception:
            await query_db.rollback()
            raise

    @classmethod
    async def update_mindmap_metadata_services(
        cls,
        query_db: AsyncSession,
        page_object: MindmapMetadataUpdateModel,
        user_id: int,
        user_name: str,
    ) -> CrudResponseModel:
        """只更新用户可编辑的文件信息，不触碰正文和权限字段。"""
        await cls.check_mindmap_access(query_db, page_object.id, user_id, require_edit=True)
        result = {
            'id': page_object.id,
            'name': page_object.name,
            'description': page_object.description,
        }
        try:
            await MindmapDao.edit_mindmap_dao(query_db, {
                **result,
                'update_by': user_name,
                'update_time': datetime.now(),
            })
            await query_db.commit()
            return CrudResponseModel(
                is_success=True,
                message='脑图信息已更新',
                result=result,
            )
        except Exception:
            await query_db.rollback()
            raise

    @classmethod
    async def update_mindmap_status_services(
        cls,
        query_db: AsyncSession,
        page_object: MindmapStatusUpdateModel,
        user_id: int,
        user_name: str,
    ) -> CrudResponseModel:
        """归档或恢复所有者的脑图，并终止归档文件的在线写入会话。"""
        mindmap = await MindmapDao.get_mindmap_for_update(query_db, page_object.id)
        if not mindmap or mindmap.owner_id != user_id:
            await query_db.rollback()
            raise ServiceException(message='脑图不存在或无归档权限')
        if mindmap.status == page_object.status:
            await query_db.rollback()
            return CrudResponseModel(
                is_success=True,
                message='脑图状态未发生变化',
                result={'id': page_object.id, 'status': page_object.status, 'changed': False},
            )

        try:
            updated_count = await MindmapDao.update_mindmap_status(
                query_db,
                page_object.id,
                user_id,
                page_object.status,
                user_name,
            )
            if updated_count != 1:
                raise ServiceException(message='脑图状态已发生变化，请刷新后重试')
            await query_db.commit()
        except Exception:
            await query_db.rollback()
            raise

        if page_object.status == 1:
            try:
                from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

                await room_manager.broadcast_and_close_room(
                    page_object.id,
                    {
                        'type': 'document_archived',
                        'mindmapId': page_object.id,
                        'archivedBy': user_id,
                        'message': '该脑图已被所有者归档，当前编辑会话已结束',
                    },
                    close_code=4005,
                )
            except Exception as exc:
                logger.warning(f'关闭已归档脑图房间失败: mindmap_id={page_object.id}, error={exc}')
        return CrudResponseModel(
            is_success=True,
            message='脑图已归档' if page_object.status == 1 else '脑图已恢复',
            result={'id': page_object.id, 'status': page_object.status, 'changed': True},
        )

    @classmethod
    async def batch_update_mindmap_status_services(
        cls,
        query_db: AsyncSession,
        page_object: MindmapBatchStatusUpdateModel,
        user_id: int,
        user_name: str,
    ) -> CrudResponseModel:
        """原子批量归档或恢复所有者脑图，并关闭实际归档文件的在线房间。"""
        requested_ids = sorted(page_object.mindmap_ids)
        rows = list((await query_db.execute(
            select(Mindmap).where(
                Mindmap.id.in_(requested_ids),
                Mindmap.owner_id == user_id,
                Mindmap.del_flag == '0',
            ).order_by(Mindmap.id).with_for_update()
        )).scalars())
        if len(rows) != len(requested_ids):
            await query_db.rollback()
            raise ServiceException(message='部分脑图不存在、已在回收站或无归档权限')

        changed_ids = [row.id for row in rows if row.status != page_object.status]
        if not changed_ids:
            await query_db.rollback()
            return CrudResponseModel(
                is_success=True,
                message='所选脑图状态未发生变化',
                result={
                    'requestedIds': requested_ids,
                    'changedIds': [],
                    'status': page_object.status,
                },
            )

        try:
            updated_count = await MindmapDao.update_mindmaps_status(
                query_db,
                changed_ids,
                user_id,
                page_object.status,
                user_name,
            )
            if updated_count != len(changed_ids):
                raise ServiceException(message='部分脑图状态已发生变化，请刷新后重试')
            await query_db.commit()
        except Exception:
            await query_db.rollback()
            raise

        if page_object.status == 1:
            try:
                from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

                notification_results = await asyncio.gather(*(
                    room_manager.broadcast_and_close_room(
                        mindmap_id,
                        {
                            'type': 'document_archived',
                            'mindmapId': mindmap_id,
                            'archivedBy': user_id,
                            'message': '该脑图已被所有者归档，当前编辑会话已结束',
                        },
                        close_code=4005,
                    )
                    for mindmap_id in changed_ids
                ), return_exceptions=True)
                for mindmap_id, result in zip(changed_ids, notification_results, strict=True):
                    if isinstance(result, Exception):
                        logger.warning(
                            f'关闭批量归档脑图房间失败: mindmap_id={mindmap_id}, error={result}'
                        )
            except Exception as exc:
                logger.warning(f'关闭批量归档脑图房间失败: error={exc}')

        action = '归档' if page_object.status == 1 else '恢复'
        return CrudResponseModel(
            is_success=True,
            message=f'已{action} {len(changed_ids)} 张脑图',
            result={
                'requestedIds': requested_ids,
                'changedIds': changed_ids,
                'status': page_object.status,
            },
        )

    @classmethod
    async def delete_mindmap_services(
        cls,
        query_db: AsyncSession,
        page_object: DeleteMindmapModel,
        user_id: int,
        user_name: str | None = None,
    ) -> CrudResponseModel:
        """将脑图移入回收站，完整保留内容、版本和访问配置。"""
        id_list = cls._parse_delete_mindmap_ids(page_object.mindmap_ids)
        rows = list((await query_db.execute(
            select(Mindmap).where(
                Mindmap.id.in_(id_list),
                Mindmap.owner_id == user_id,
                Mindmap.del_flag == '0',
            ).with_for_update()
        )).scalars())
        if len(rows) != len(id_list) or any(row.owner_id != user_id for row in rows):
            await query_db.rollback()
            raise ServiceException(message='部分脑图不存在、已在回收站或无删除权限')

        try:
            updated_count = await MindmapDao.move_to_trash(
                query_db, id_list, user_id, user_name or str(user_id),
            )
            if updated_count != len(id_list):
                raise ServiceException(message='脑图状态已发生变化，请刷新后重试')
            await query_db.commit()
        except Exception:
            await query_db.rollback()
            raise

        try:
            from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

            notification_results = await asyncio.gather(*(
                room_manager.broadcast_and_close_room(mindmap_id, {
                    'type': 'document_deleted',
                    'mindmapId': mindmap_id,
                    'deletedBy': user_id,
                    'message': '该脑图已被所有者移入回收站',
                })
                for mindmap_id in id_list
            ), return_exceptions=True)
            for mindmap_id, result in zip(id_list, notification_results, strict=True):
                if isinstance(result, Exception):
                    logger.warning(f'关闭已删除脑图房间失败: mindmap_id={mindmap_id}, error={result}')
        except Exception as exc:
            logger.warning(f'关闭回收站脑图房间失败: error={exc}')
        return CrudResponseModel(is_success=True, message='已移入回收站')

    @classmethod
    async def restore_mindmap_services(
        cls,
        query_db: AsyncSession,
        page_object: DeleteMindmapModel,
        user_id: int,
        user_name: str,
    ) -> CrudResponseModel:
        """恢复回收站文件；兼容旧逻辑已清空结构化表的历史删除记录。"""
        id_list = cls._parse_delete_mindmap_ids(page_object.mindmap_ids)
        rows = list((await query_db.execute(
            select(Mindmap).where(
                Mindmap.id.in_(id_list),
                Mindmap.owner_id == user_id,
                Mindmap.del_flag == '2',
            ).with_for_update()
        )).scalars())
        if len(rows) != len(id_list) or any(row.owner_id != user_id for row in rows):
            await query_db.rollback()
            raise ServiceException(message='部分脑图不存在、不在回收站或无恢复权限')

        try:
            active_folder_ids = set((await query_db.execute(
                select(MindmapFolder.id).where(
                    MindmapFolder.owner_id == user_id,
                    MindmapFolder.del_flag == '0',
                )
            )).scalars())
            root_folder_file_ids = {
                row.id for row in rows
                if row.folder_id is not None and row.folder_id not in active_folder_ids
            }
            structured_file_ids = set((await query_db.execute(
                select(MindmapNode.file_id).where(
                    MindmapNode.file_id.in_(id_list),
                    MindmapNode.is_deleted == 0,
                ).distinct()
            )).scalars())
            legacy_recovered_ids: list[int] = []
            for row in rows:
                if row.id in structured_file_ids:
                    continue
                try:
                    root = json.loads(row.node_tree) if isinstance(row.node_tree, str) else row.node_tree
                    validate_mindmap_tree(root)
                    metadata = await MindmapDocumentService.persist_tree(
                        query_db,
                        row.id,
                        root,
                        owner_id=user_id,
                        operator=user_name,
                        allow_disabled_bindings=True,
                    )
                    await MindmapDao.edit_mindmap_dao(query_db, {
                        'id': row.id,
                        **metadata,
                        'last_version_id': None,
                        'version_count': 1,
                    })
                    legacy_recovered_ids.append(row.id)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ServiceException(
                        message=f'脑图“{row.name}”的历史内容已损坏，无法安全恢复',
                    ) from exc
            if legacy_recovered_ids:
                await query_db.execute(sa_delete(MindmapMigrationRecord).where(
                    MindmapMigrationRecord.file_id.in_(legacy_recovered_ids)
                ))
            restored_count = await MindmapDao.restore_from_trash(
                query_db,
                id_list,
                user_id,
                user_name,
                root_folder_file_ids,
            )
            if restored_count != len(id_list):
                raise ServiceException(message='脑图状态已发生变化，请刷新后重试')
            await query_db.commit()
            return CrudResponseModel(
                is_success=True,
                message='恢复成功',
                result={
                    'restoredIds': id_list,
                    'legacyRecoveredIds': legacy_recovered_ids,
                    'movedToRootIds': sorted(root_folder_file_ids),
                },
            )
        except Exception:
            await query_db.rollback()
            raise

    @classmethod
    async def permanently_delete_mindmap_services(
        cls,
        query_db: AsyncSession,
        page_object: DeleteMindmapModel,
        user_id: int,
    ) -> CrudResponseModel:
        """永久删除回收站文件及全部关联数据。"""
        id_list = cls._parse_delete_mindmap_ids(page_object.mindmap_ids)
        rows = list((await query_db.execute(
            select(Mindmap).where(
                Mindmap.id.in_(id_list),
                Mindmap.owner_id == user_id,
                Mindmap.del_flag == '2',
            ).with_for_update()
        )).scalars())
        if len(rows) != len(id_list) or any(row.owner_id != user_id for row in rows):
            await query_db.rollback()
            raise ServiceException(message='部分脑图不存在、不在回收站或无永久删除权限')

        try:
            from module_mindmap.entity.do.mindmap_collaborator_do import MindmapCollaborator  # noqa: PLC0415
            from module_mindmap.entity.do.mindmap_comment_do import (  # noqa: PLC0415
                MindmapComment,
                MindmapCommentThread,
            )
            from module_mindmap.entity.do.mindmap_share_do import MindmapShare  # noqa: PLC0415
            from module_mindmap.entity.do.mindmap_version_do import MindmapVersion  # noqa: PLC0415
            from module_mindmap.entity.do.mindmap_ws_state_do import MindmapWsState  # noqa: PLC0415

            await query_db.execute(sa_delete(MindmapComment).where(
                MindmapComment.mindmap_id.in_(id_list)
            ))
            await query_db.execute(sa_delete(MindmapCommentThread).where(
                MindmapCommentThread.mindmap_id.in_(id_list)
            ))
            for model in (MindmapVersion, MindmapShare, MindmapCollaborator, MindmapWsState):
                await query_db.execute(sa_delete(model).where(model.mindmap_id.in_(id_list)))
            await MindmapDocumentService.delete_files(query_db, id_list)
            await query_db.execute(sa_delete(MindmapMigrationRecord).where(
                MindmapMigrationRecord.file_id.in_(id_list)
            ))
            await query_db.execute(sa_delete(MindmapCreationRequest).where(
                MindmapCreationRequest.result_file_id.in_(id_list)
            ))
            deleted_count = await MindmapDao.permanently_delete(query_db, id_list, user_id)
            if deleted_count != len(id_list):
                raise ServiceException(message='脑图状态已发生变化，请刷新后重试')
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='已永久删除')
        except Exception:
            await query_db.rollback()
            raise

    @staticmethod
    def _parse_delete_mindmap_ids(ids_str: str) -> list[int]:
        try:
            mindmap_ids = list(dict.fromkeys(
                int(value.strip()) for value in ids_str.split(',') if value.strip()
            ))
        except ValueError as exc:
            raise ServiceException(message='脑图ID必须是逗号分隔的正整数') from exc
        if not mindmap_ids:
            raise ServiceException(message='传入思维导图ID为空')
        if any(mindmap_id <= 0 for mindmap_id in mindmap_ids):
            raise ServiceException(message='脑图ID必须是逗号分隔的正整数')
        if len(mindmap_ids) > MAX_BATCH_MINDMAP_DELETE:
            raise ServiceException(message=f'单次最多删除 {MAX_BATCH_MINDMAP_DELETE} 个脑图')
        return mindmap_ids

    @classmethod
    async def copy_mindmap_services(
        cls,
        query_db: AsyncSession,
        mindmap_id: int,
        user_id: int,
        *,
        creation_request_id: str | None = None,
    ) -> CrudResponseModel:
        """复制思维导图"""
        creation_intent = {'sourceMindmapId': mindmap_id}
        if creation_request_id is not None:
            _, replay = await cls._find_mindmap_creation_replay(
                query_db,
                owner_id=user_id,
                creation_request_id=creation_request_id,
                creation_operation='copy',
                creation_intent=creation_intent,
            )
            if replay is not None:
                return replay
        source = await cls.check_mindmap_access(query_db, mindmap_id, user_id, require_edit=False)

        # Parse node_tree from string (stored as LONGTEXT) to dict
        source_tree = None
        if getattr(source, 'schema_version', 1) >= SCHEMA_VERSION:
            source_tree = await MindmapDocumentService.load_tree(
                query_db, source.id, required=True,
            )
        if not source_tree:
            source_tree = source.node_tree
            if isinstance(source_tree, str):
                source_tree = json.loads(source_tree) if source_tree else {}
        source_tree = await MindmapTagPortabilityService.prepare_tree_for_owner(
            query_db,
            source_tree,
            target_owner_id=user_id,
        )

        # Create copy with new name
        copy_model = MindmapModel(
            name=f'{source.name} (副本)',
            description=source.description,
            owner_id=user_id,
            layout=source.layout,
            theme=source.theme,
            node_tree=source_tree,
            view_data=source.view_data,
            document_data=source.document_data,
            cover_image=source.cover_image,
        )

        return await cls.add_mindmap_services(
            query_db,
            copy_model,
            creation_request_id=creation_request_id,
            creation_operation='copy',
            creation_intent=creation_intent,
        )
