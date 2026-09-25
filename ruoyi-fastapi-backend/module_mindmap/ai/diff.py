"""基于稳定 UID 的确定性脑图差异与影响摘要。"""
from __future__ import annotations

from typing import Any

from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.service.simple_mind_document_codec import clone_json_value

IGNORED_DATA_FIELDS = frozenset({
    'isActive',
    'inserting',
    'needUpdate',
    'resetRichText',
    'activeStyle',
})
HIGH_IMPACT_DELETE_COUNT = 20
HIGH_IMPACT_DELETE_RATIO = 0.1
STRUCTURAL_UPDATE_COUNT = 20
STRUCTURAL_UPDATE_RATIO = 0.2
MIN_BULK_UPDATE_COUNT = 5
HALF_UPDATE_RATIO = 0.5


def _index_document(document: dict[str, Any]) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str | None],
    dict[str, int],
    dict[str, str],
]:
    nodes: dict[str, dict[str, Any]] = {}
    parents: dict[str, str | None] = {}
    indexes: dict[str, int] = {}
    paths: dict[str, str] = {}
    root = document['root']
    pending = [(root, None, 0, '')]
    while pending:
        node, parent_uid, index, parent_path = pending.pop()
        data = node.get('data') or {}
        uid = str(data['uid'])
        text = str(data.get('text') or '').strip() or uid
        path = f'{parent_path} / {text}' if parent_path else text
        nodes[uid] = node
        parents[uid] = parent_uid
        indexes[uid] = index
        paths[uid] = path
        children = node.get('children') or []
        pending.extend(
            (child, uid, child_index, path)
            for child_index, child in reversed(list(enumerate(children)))
        )
    return nodes, parents, indexes, paths


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    return {
        key: clone_json_value(value)
        for key, value in (node.get('data') or {}).items()
        if key not in IGNORED_DATA_FIELDS and key != 'uid'
    }


def _deleted_subtree_size(node: dict[str, Any], deleted_uids: set[str]) -> int:
    count = 0
    pending = [node]
    while pending:
        current = pending.pop()
        if str((current.get('data') or {}).get('uid')) in deleted_uids:
            count += 1
        pending.extend(current.get('children') or [])
    return count


def _shared_sibling_ranks(
    shared_uids: set[str],
    before_parents: dict[str, str | None],
    before_indexes: dict[str, int],
    after_parents: dict[str, str | None],
    after_indexes: dict[str, int],
) -> tuple[dict[str, int], dict[str, int]]:
    stable_by_parent: dict[str | None, list[str]] = {}
    for uid in shared_uids:
        parent_uid = before_parents[uid]
        if parent_uid != after_parents[uid]:
            continue
        stable_by_parent.setdefault(parent_uid, []).append(uid)
    before_ranks: dict[str, int] = {}
    after_ranks: dict[str, int] = {}
    for siblings in stable_by_parent.values():
        before_ranks.update({
            uid: rank
            for rank, uid in enumerate(sorted(siblings, key=before_indexes.__getitem__))
        })
        after_ranks.update({
            uid: rank
            for rank, uid in enumerate(sorted(siblings, key=after_indexes.__getitem__))
        })
    return before_ranks, after_ranks


def build_document_diff(  # noqa: PLR0912, PLR0915
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回可审计操作和用户可读影响摘要，不按文本猜测节点身份。"""
    before_nodes, before_parents, before_indexes, before_paths = _index_document(before)
    after_nodes, after_parents, after_indexes, after_paths = _index_document(after)
    before_uids = set(before_nodes)
    after_uids = set(after_nodes)

    before_root_uid = str(before['root']['data']['uid'])
    after_root_uid = str(after['root']['data']['uid'])
    if before_root_uid != after_root_uid:
        raise MindmapArtifactError('AI Proposal 不能替换脑图根节点')

    created_uids = after_uids - before_uids
    deleted_uids = before_uids - after_uids
    shared_uids = before_uids & after_uids
    before_ranks, after_ranks = _shared_sibling_ranks(
        shared_uids,
        before_parents,
        before_indexes,
        after_parents,
        after_indexes,
    )
    operations: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    updated_count = 0
    moved_count = 0
    for uid in after_paths:
        if uid not in shared_uids:
            continue
        before_data = _node_data(before_nodes[uid])
        after_data = _node_data(after_nodes[uid])
        changed_fields = sorted({
            key for key in set(before_data) | set(after_data)
            if (
                (key in before_data) != (key in after_data)
                or before_data.get(key) != after_data.get(key)
            )
        })
        if changed_fields:
            set_values = {
                key: clone_json_value(after_data[key])
                for key in changed_fields
                if key in after_data
            }
            unset_values = [key for key in changed_fields if key not in after_data]
            operations.append({
                'type': 'update_node',
                'nodeUid': uid,
                'payload': {'set': set_values, 'unset': unset_values},
            })
            changes.append({
                'type': 'update_node',
                'nodeUid': uid,
                'path': after_paths[uid],
                'fields': changed_fields,
            })
            updated_count += 1
        semantically_moved = (
            before_parents[uid] != after_parents[uid]
            or before_ranks.get(uid) != after_ranks.get(uid)
        )
        if semantically_moved:
            changes.append({
                'type': 'move_node',
                'nodeUid': uid,
                'fromPath': before_paths[uid],
                'path': after_paths[uid],
            })
            moved_count += 1

    # 结构操作必须能按数组顺序在浏览器中直接重放。先把新增节点以 append
    # 形式实体化，再按目标树前序移动现有/新增节点；第一次移动会把仍位于
    # 待删子树中的保留节点移出，删除后第二次收敛消除旧兄弟造成的索引偏移。
    simulated = clone_json_value(before)
    simulated_nodes, simulated_parents, _simulated_indexes, _simulated_paths = (
        _index_document(simulated)
    )

    for uid in after_paths:
        if uid not in created_uids:
            continue
        parent_uid = after_parents[uid]
        if parent_uid is None or parent_uid not in simulated_nodes:
            raise MindmapArtifactError(f'AI Proposal 新增节点父节点不存在: {uid}')
        parent = simulated_nodes[parent_uid]
        index = len(parent.get('children') or [])
        data = {'uid': uid, **_node_data(after_nodes[uid])}
        node = {'data': clone_json_value(data), 'children': []}
        parent.setdefault('children', []).append(node)
        simulated_nodes[uid] = node
        simulated_parents[uid] = parent_uid
        operations.append({
            'type': 'create_node',
            'nodeUid': uid,
            'payload': {
                'parentUid': parent_uid,
                'index': index,
                'data': data,
            },
        })
        changes.append({
            'type': 'create_node',
            'nodeUid': uid,
            'path': after_paths[uid],
        })

    def move_simulated(uid: str, parent_uid: str, index: int) -> None:
        node = simulated_nodes[uid]
        old_parent_uid = simulated_parents[uid]
        if old_parent_uid is None:
            raise MindmapArtifactError('AI Proposal 不能移动脑图根节点')
        old_children = simulated_nodes[old_parent_uid].get('children') or []
        old_children.remove(node)
        new_children = simulated_nodes[parent_uid].setdefault('children', [])
        new_children.insert(index, node)
        simulated_parents[uid] = parent_uid

    def converge_structure() -> None:
        for parent_uid in after_paths:
            desired_children = [
                str(child['data']['uid'])
                for child in after_nodes[parent_uid].get('children') or []
            ]
            for index, uid in enumerate(desired_children):
                current_parent_uid = simulated_parents.get(uid)
                if current_parent_uid is None:
                    raise MindmapArtifactError(f'AI Proposal 节点关系无效: {uid}')
                current_children = simulated_nodes[current_parent_uid].get('children') or []
                current_index = current_children.index(simulated_nodes[uid])
                if current_parent_uid == parent_uid and current_index == index:
                    continue
                move_simulated(uid, parent_uid, index)
                operations.append({
                    'type': 'move_node',
                    'nodeUid': uid,
                    'payload': {'parentUid': parent_uid, 'index': index},
                })

    converge_structure()

    # 只为被删除子树的最高层节点记录 delete_subtree，避免重复删除。
    deletion_roots = [
        uid for uid in before_paths
        if uid in deleted_uids and before_parents[uid] not in deleted_uids
    ]
    deleted_subtrees = []
    for uid in deletion_roots:
        size = _deleted_subtree_size(before_nodes[uid], deleted_uids)
        operations.append({'type': 'delete_subtree', 'nodeUid': uid, 'payload': None})
        deleted_node = simulated_nodes[uid]
        parent_uid = simulated_parents[uid]
        if parent_uid is None:
            raise MindmapArtifactError('AI Proposal 不能删除脑图根节点')
        simulated_nodes[parent_uid]['children'].remove(deleted_node)
        pending_deleted = [deleted_node]
        while pending_deleted:
            current = pending_deleted.pop()
            current_uid = str(current['data']['uid'])
            pending_deleted.extend(current.get('children') or [])
            simulated_nodes.pop(current_uid, None)
            simulated_parents.pop(current_uid, None)
        detail = {
            'type': 'delete_subtree',
            'nodeUid': uid,
            'path': before_paths[uid],
            'subtreeSize': size,
        }
        changes.append(detail)
        deleted_subtrees.append(detail)

    converge_structure()

    metadata_changes = []
    for field in ('layout', 'theme', 'documentData'):
        if before.get(field) == after.get(field):
            continue
        metadata_changes.append(field)
    if metadata_changes:
        set_values = {
            field: clone_json_value(after[field])
            for field in metadata_changes
            if field in after
        }
        unset_values = [field for field in metadata_changes if field not in after]
        operations.append({
            'type': 'set_document_meta',
            'nodeUid': None,
            'payload': {'set': set_values, 'unset': unset_values},
        })
        changes.append({'type': 'set_document_meta', 'fields': metadata_changes})

    deleted_count = len(deleted_uids)
    before_count = max(len(before_nodes), 1)
    deletion_ratio = deleted_count / before_count
    high_impact_reasons = []
    if deleted_count > HIGH_IMPACT_DELETE_COUNT:
        high_impact_reasons.append('删除节点超过 20 个')
    if deletion_ratio >= HIGH_IMPACT_DELETE_RATIO and deleted_count > 0:
        high_impact_reasons.append('删除节点达到当前文档的 10%')
    # Risk is derived from the semantic diff, never from model confidence or
    # the mechanically generated moves needed to insert a new sibling.
    risk_level = 'R0' if not operations else 'R1'
    if moved_count:
        high_impact_reasons.append('移动或重排已有节点，需要确认结构变化')
        risk_level = 'R2'
    if metadata_changes:
        high_impact_reasons.append('修改脑图布局、主题或文档属性')
        risk_level = 'R2'
    if updated_count >= STRUCTURAL_UPDATE_COUNT or (
        updated_count >= MIN_BULK_UPDATE_COUNT
        and updated_count / before_count >= STRUCTURAL_UPDATE_RATIO
    ):
        high_impact_reasons.append('批量改写已有节点')
        risk_level = 'R2'
    if deleted_count:
        high_impact_reasons.append('包含删除节点或子树，需确认保留内容')
        risk_level = 'R3'
    if _node_data(before_nodes[before_root_uid]) != _node_data(after_nodes[after_root_uid]):
        high_impact_reasons.append('修改脑图根节点')
        risk_level = 'R3'
    if updated_count >= MIN_BULK_UPDATE_COUNT and updated_count / before_count >= HALF_UPDATE_RATIO:
        high_impact_reasons.append('改写至少一半的已有节点')
        risk_level = 'R3'
    return operations, {
        'beforeNodeCount': len(before_nodes),
        'afterNodeCount': len(after_nodes),
        'createdCount': len(created_uids),
        'updatedCount': updated_count,
        'movedCount': moved_count,
        'deletedCount': deleted_count,
        'deletedSubtrees': deleted_subtrees,
        'metadataChanges': metadata_changes,
        'operationCount': len(operations),
        'riskLevel': risk_level,
        'requiresApproval': risk_level in {'R2', 'R3'},
        'highImpact': bool(high_impact_reasons),
        'highImpactReasons': high_impact_reasons,
        'changes': changes,
    }


def build_legacy_document_diff_v0(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[dict[str, Any]]:
    """精确重建冻结协议发布前的 diff，仅供既存 Proposal 兼容校验。

    不得用它生成新提案。旧格式的 ``patch: null`` 和元数据 ``fields``
    都缺少完整目标语义，调用方还必须结合 Artifact 做严格转换和重放。
    """
    before_nodes, before_parents, before_indexes, _before_paths = _index_document(before)
    after_nodes, after_parents, after_indexes, after_paths = _index_document(after)
    before_uids = set(before_nodes)
    after_uids = set(after_nodes)
    created_uids = after_uids - before_uids
    deleted_uids = before_uids - after_uids
    shared_uids = before_uids & after_uids
    before_ranks, after_ranks = _shared_sibling_ranks(
        shared_uids,
        before_parents,
        before_indexes,
        after_parents,
        after_indexes,
    )
    operations: list[dict[str, Any]] = []
    for uid in after_paths:
        if uid not in created_uids:
            continue
        operations.append({
            'type': 'create_node',
            'nodeUid': uid,
            'payload': {
                'parentUid': after_parents[uid],
                'index': after_indexes[uid],
                'data': {'uid': uid, **_node_data(after_nodes[uid])},
            },
        })
    for uid in after_paths:
        if uid not in shared_uids:
            continue
        before_data = _node_data(before_nodes[uid])
        after_data = _node_data(after_nodes[uid])
        changed_fields = sorted({
            key for key in set(before_data) | set(after_data)
            if before_data.get(key) != after_data.get(key)
        })
        if changed_fields:
            operations.append({
                'type': 'update_node',
                'nodeUid': uid,
                'payload': {
                    'patch': {
                        key: clone_json_value(after_data.get(key))
                        for key in changed_fields
                    },
                },
            })
        if (
            before_parents[uid] != after_parents[uid]
            or before_ranks.get(uid) != after_ranks.get(uid)
        ):
            operations.append({
                'type': 'move_node',
                'nodeUid': uid,
                'payload': {
                    'parentUid': after_parents[uid],
                    'index': after_indexes[uid],
                },
            })
    deletion_roots = [
        uid for uid in before_nodes
        if uid in deleted_uids and before_parents[uid] not in deleted_uids
    ]
    operations.extend(
        {'type': 'delete_subtree', 'nodeUid': uid, 'payload': None}
        for uid in deletion_roots
    )
    metadata_changes = [
        field for field in ('layout', 'theme', 'documentData')
        if before.get(field) != after.get(field)
    ]
    if metadata_changes:
        operations.append({
            'type': 'set_document_meta',
            'nodeUid': None,
            'payload': {'fields': metadata_changes},
        })
    return operations
