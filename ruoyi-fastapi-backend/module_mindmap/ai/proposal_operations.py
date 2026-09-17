"""AI Proposal 操作的冻结协议与严格、无副作用重放。

Proposal 是跨进程、跨浏览器的安全边界，不能复用实时预览所使用的宽松
reducer。本模块只接受 ``diff.build_document_diff`` 生成的 v1 冻结结构；任何
未知字段、悬空引用或非法树变换都会在修改传入文档前失败。
"""
from __future__ import annotations

from typing import Any

from module_mindmap.ai.document import (
    AI_MAX_NODE_COUNT,
    AI_PROJECTION_DATA_KEYS,
    MindmapArtifactError,
    canonical_json_bytes,
    compute_document_hash,
    normalize_ai_document,
    normalize_ai_editable_source_document,
)
from module_mindmap.service.simple_mind_document_codec import clone_json_value

PROPOSAL_INTEGRITY_ERROR_CODE = 'AI_PROPOSAL_INTEGRITY_INVALID'
PROPOSAL_OPERATION_TYPES = frozenset({
    'create_node',
    'update_node',
    'move_node',
    'delete_subtree',
    'set_document_meta',
})
DOCUMENT_META_FIELDS = frozenset({'layout', 'theme', 'documentData'})
PROPOSAL_NODE_DATA_FIELDS = (AI_PROJECTION_DATA_KEYS | {'expand'}) - {'uid'}
_OPERATION_FIELDS = frozenset({'type', 'nodeUid', 'payload'})


def _invalid(message: str) -> MindmapArtifactError:
    return MindmapArtifactError(message, code=PROPOSAL_INTEGRITY_ERROR_CODE)


def _require_exact_fields(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise _invalid(f'{label}字段无效')


def _require_uid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid(f'{label} UID 无效')
    return value


def _require_index(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _invalid(f'{label}位置无效')
    return value


def _index_tree(
    root: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, str | None], str]:
    if not isinstance(root, dict):
        raise _invalid('Proposal 基线缺少有效根节点')
    nodes: dict[str, dict[str, Any]] = {}
    parents: dict[str, str | None] = {}
    root_uid = ''
    pending: list[tuple[dict[str, Any], str | None]] = [(root, None)]
    while pending:
        node, parent_uid = pending.pop()
        data = node.get('data')
        if not isinstance(data, dict):
            raise _invalid('Proposal 节点 data 无效')
        uid = _require_uid(data.get('uid'), 'Proposal 节点')
        if uid in nodes:
            raise _invalid(f'Proposal 节点 UID 重复: {uid}')
        if parent_uid is None:
            if root_uid:
                raise _invalid('Proposal 文档只能有一个根节点')
            root_uid = uid
        children = node.get('children')
        if not isinstance(children, list) or any(
            not isinstance(child, dict) for child in children
        ):
            raise _invalid(f'Proposal 节点 children 无效: {uid}')
        nodes[uid] = node
        parents[uid] = parent_uid
        pending.extend((child, uid) for child in reversed(children))
    if not root_uid:
        raise _invalid('Proposal 基线缺少有效根节点')
    return nodes, parents, root_uid


def _require_set_unset_payload(
    payload: Any,
    *,
    label: str,
    allowed_fields: frozenset[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        raise _invalid(f'{label} payload 无效')
    _require_exact_fields(payload, frozenset({'set', 'unset'}), f'{label} payload')
    set_values = payload.get('set')
    unset_values = payload.get('unset')
    if not isinstance(set_values, dict) or not isinstance(unset_values, list):
        raise _invalid(f'{label} set/unset 无效')
    if not set_values and not unset_values:
        raise _invalid(f'{label}不能是空操作')
    if any(
        not isinstance(field, str) or not field or field != field.strip()
        for field in set_values
    ):
        raise _invalid(f'{label} set 字段无效')
    if any(
        not isinstance(field, str) or not field or field != field.strip()
        for field in unset_values
    ):
        raise _invalid(f'{label} unset 字段无效')
    if len(set(unset_values)) != len(unset_values):
        raise _invalid(f'{label} unset 字段重复')
    touched = set(set_values) | set(unset_values)
    if set(set_values).intersection(unset_values):
        raise _invalid(f'{label} set/unset 字段冲突')
    if allowed_fields is not None and touched - allowed_fields:
        raise _invalid(f'{label}包含未知字段')
    return set_values, unset_values


def strict_replay_document_operations(  # noqa: PLR0912, PLR0915
    base_document: dict[str, Any],
    operations: list[dict[str, Any]],
    *,
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> dict[str, Any]:
    """在基线副本上原子重放冻结 Proposal 操作。

    返回值是可直接参与 SMM 哈希计算的规范文档。函数从不修改
    ``base_document`` 或 ``operations``；失败时不会泄漏部分重放结果。
    """
    if not isinstance(base_document, dict):
        raise _invalid('Proposal 基线文档无效')
    if not isinstance(operations, list):
        raise _invalid('Proposal operations 必须是数组')

    try:
        # 先在原始输入上检查 UID，避免普通规范化过程为缺失 UID 自动补值。
        _index_tree(base_document.get('root'))
        document, _summary = normalize_ai_document(
            base_document,
            content_policy='source',
            max_node_count=max_node_count,
        )
    except MindmapArtifactError as exc:
        if exc.code == PROPOSAL_INTEGRITY_ERROR_CODE:
            raise
        raise _invalid(f'Proposal 基线文档无效: {exc}') from exc
    nodes, parents, root_uid = _index_tree(document['root'])

    for operation_index, raw_operation in enumerate(operations):
        label = f'Proposal operation[{operation_index}]'
        if not isinstance(raw_operation, dict):
            raise _invalid(f'{label}必须是对象')
        _require_exact_fields(raw_operation, _OPERATION_FIELDS, label)
        operation_type = raw_operation.get('type')
        if operation_type not in PROPOSAL_OPERATION_TYPES:
            raise _invalid(f'{label}类型无效')
        node_uid = raw_operation.get('nodeUid')
        payload = raw_operation.get('payload')

        if operation_type == 'create_node':
            uid = _require_uid(node_uid, '新增节点')
            if uid in nodes:
                raise _invalid(f'新增节点 UID 已存在: {uid}')
            if not isinstance(payload, dict):
                raise _invalid('新增节点 payload 无效')
            _require_exact_fields(
                payload,
                frozenset({'parentUid', 'index', 'data'}),
                '新增节点 payload',
            )
            parent_uid = _require_uid(payload.get('parentUid'), '新增节点父节点')
            parent = nodes.get(parent_uid)
            if parent is None:
                raise _invalid(f'新增节点父节点不存在: {parent_uid}')
            index = _require_index(payload.get('index'), '新增节点')
            children = parent['children']
            if index > len(children):
                raise _invalid('新增节点位置超出父节点范围')
            data = payload.get('data')
            if not isinstance(data, dict):
                raise _invalid('新增节点 data 无效')
            if data.get('uid') != uid:
                raise _invalid('新增节点 nodeUid 与 data.uid 不一致')
            if set(data) - (PROPOSAL_NODE_DATA_FIELDS | {'uid'}):
                raise _invalid('新增节点 data 包含未知字段')
            new_node = {'data': clone_json_value(data), 'children': []}
            children.insert(index, new_node)
            nodes[uid] = new_node
            parents[uid] = parent_uid
            continue

        if operation_type == 'update_node':
            uid = _require_uid(node_uid, '更新节点')
            node = nodes.get(uid)
            if node is None:
                raise _invalid(f'更新节点不存在: {uid}')
            set_values, unset_values = _require_set_unset_payload(
                payload,
                label='更新节点',
            )
            if 'uid' in set_values or 'uid' in unset_values:
                raise _invalid('更新节点不能修改 UID')
            if (set(set_values) | set(unset_values)) - PROPOSAL_NODE_DATA_FIELDS:
                raise _invalid('更新节点包含未知字段')
            data = node['data']
            for field, value in set_values.items():
                data[field] = clone_json_value(value)
            for field in unset_values:
                data.pop(field, None)
            continue

        if operation_type == 'move_node':
            uid = _require_uid(node_uid, '移动节点')
            if uid not in nodes:
                raise _invalid(f'移动节点不存在: {uid}')
            if uid == root_uid:
                raise _invalid('不能移动 Proposal 根节点')
            if not isinstance(payload, dict):
                raise _invalid('移动节点 payload 无效')
            _require_exact_fields(
                payload,
                frozenset({'parentUid', 'index'}),
                '移动节点 payload',
            )
            parent_uid = _require_uid(payload.get('parentUid'), '移动节点父节点')
            new_parent = nodes.get(parent_uid)
            if new_parent is None:
                raise _invalid(f'移动节点父节点不存在: {parent_uid}')
            ancestor_uid: str | None = parent_uid
            while ancestor_uid is not None:
                if ancestor_uid == uid:
                    raise _invalid('移动节点不能形成循环')
                ancestor_uid = parents.get(ancestor_uid)
            old_parent_uid = parents.get(uid)
            if old_parent_uid is None or old_parent_uid not in nodes:
                raise _invalid('移动节点缺少原父节点')
            node = nodes[uid]
            old_children = nodes[old_parent_uid]['children']
            try:
                old_index = next(
                    index
                    for index, child in enumerate(old_children)
                    if child is node
                )
            except StopIteration as exc:
                raise _invalid('移动节点与原父节点关系无效') from exc
            old_children.pop(old_index)
            index = _require_index(payload.get('index'), '移动节点')
            new_children = new_parent['children']
            if index > len(new_children):
                raise _invalid('移动节点位置超出父节点范围')
            new_children.insert(index, node)
            parents[uid] = parent_uid
            continue

        if operation_type == 'delete_subtree':
            uid = _require_uid(node_uid, '删除节点')
            if payload is not None:
                raise _invalid('删除节点 payload 必须为 null')
            if uid not in nodes:
                raise _invalid(f'删除节点不存在: {uid}')
            if uid == root_uid:
                raise _invalid('不能删除 Proposal 根节点')
            parent_uid = parents.get(uid)
            if parent_uid is None or parent_uid not in nodes:
                raise _invalid('删除节点缺少父节点')
            subtree_root = nodes[uid]
            parent_children = nodes[parent_uid]['children']
            nodes[parent_uid]['children'] = [
                child for child in parent_children if child is not subtree_root
            ]
            pending = [subtree_root]
            while pending:
                removed = pending.pop()
                removed_uid = str(removed['data']['uid'])
                pending.extend(removed['children'])
                nodes.pop(removed_uid, None)
                parents.pop(removed_uid, None)
            continue

        if node_uid is not None:
            raise _invalid('文档元数据操作 nodeUid 必须为 null')
        set_values, unset_values = _require_set_unset_payload(
            payload,
            label='文档元数据',
            allowed_fields=DOCUMENT_META_FIELDS,
        )
        for field, value in set_values.items():
            document[field] = clone_json_value(value)
        for field in unset_values:
            document.pop(field, None)

    # 再次索引可捕获最终重复 UID/非法 children；规范化与精确比较阻止
    # 事件字段被静默删除、缺失元数据被静默补默认值等非规范结果。
    _index_tree(document.get('root'))
    try:
        normalized, _summary = normalize_ai_document(
            document,
            content_policy='source',
            max_node_count=max_node_count,
        )
        if canonical_json_bytes(normalized) != canonical_json_bytes(document):
            raise _invalid('Proposal 重放结果不是规范脑图文档')
    except MindmapArtifactError as exc:
        if exc.code == PROPOSAL_INTEGRITY_ERROR_CODE:
            raise
        raise _invalid(f'Proposal 重放结果无效: {exc}') from exc
    return normalized


def materialize_editor_document_from_proposal(  # noqa: PLR0912, PLR0915
    *,
    source_document: dict[str, Any],
    operations: list[dict[str, Any]],
    artifact_document: dict[str, Any],
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> dict[str, Any]:
    """把已验证的 Proposal 增量重放到编辑器原始文档上。

    AI 基线和 Artifact 使用去 HTML 的规范语义文档参与哈希；它们不能直接
    覆盖编辑器正文，否则没有被 Proposal 修改的富文本字节、节点运行时字段
    和 view 都会被清空。这里先再次证明 operations 在规范投影上的结果精确
    等于 Artifact，再在原始 JSON 克隆上执行同一组冻结操作。最终结果重新
    投影后仍必须等于 Artifact，因此只能保留语义等价的原始编辑器数据。
    """
    if not isinstance(source_document, dict):
        raise _invalid('Proposal 编辑器基线文档无效')
    normalized_source, _summary = normalize_ai_editable_source_document(
        source_document,
        max_node_count=max_node_count,
    )
    canonical_result = strict_replay_document_operations(
        normalized_source,
        operations,
        max_node_count=max_node_count,
    )
    if canonical_json_bytes(canonical_result) != canonical_json_bytes(
        artifact_document,
    ):
        raise _invalid('Proposal 编辑器重放基线与 Artifact 不一致')

    editor_document = clone_json_value(source_document)
    nodes, parents, root_uid = _index_tree(editor_document.get('root'))
    for operation_index, operation in enumerate(operations):
        label = f'Proposal editor operation[{operation_index}]'
        if not isinstance(operation, dict):
            raise _invalid(f'{label}必须是对象')
        operation_type = operation.get('type')
        node_uid = operation.get('nodeUid')
        payload = operation.get('payload')

        if operation_type == 'create_node':
            uid = str(node_uid)
            parent_uid = str(payload['parentUid'])
            parent = nodes.get(parent_uid)
            if parent is None or uid in nodes:
                raise _invalid('Proposal 编辑器新增节点引用无效')
            index = int(payload['index'])
            children = parent['children']
            if index < 0 or index > len(children):
                raise _invalid('Proposal 编辑器新增节点位置无效')
            new_node = {
                'data': clone_json_value(payload['data']),
                'children': [],
            }
            children.insert(index, new_node)
            nodes[uid] = new_node
            parents[uid] = parent_uid
            continue

        if operation_type == 'update_node':
            uid = str(node_uid)
            node = nodes.get(uid)
            if node is None:
                raise _invalid('Proposal 编辑器更新节点不存在')
            for field, value in payload['set'].items():
                node['data'][field] = clone_json_value(value)
            for field in payload['unset']:
                node['data'].pop(field, None)
            continue

        if operation_type == 'move_node':
            uid = str(node_uid)
            parent_uid = str(payload['parentUid'])
            if uid == root_uid or uid not in nodes or parent_uid not in nodes:
                raise _invalid('Proposal 编辑器移动节点引用无效')
            ancestor_uid: str | None = parent_uid
            while ancestor_uid is not None:
                if ancestor_uid == uid:
                    raise _invalid('Proposal 编辑器移动节点不能形成循环')
                ancestor_uid = parents.get(ancestor_uid)
            old_parent_uid = parents.get(uid)
            if old_parent_uid is None or old_parent_uid not in nodes:
                raise _invalid('Proposal 编辑器移动节点缺少原父节点')
            node = nodes[uid]
            old_children = nodes[old_parent_uid]['children']
            try:
                old_index = next(
                    index for index, child in enumerate(old_children) if child is node
                )
            except StopIteration as exc:
                raise _invalid('Proposal 编辑器移动节点父子关系无效') from exc
            old_children.pop(old_index)
            new_children = nodes[parent_uid]['children']
            index = int(payload['index'])
            if index < 0 or index > len(new_children):
                raise _invalid('Proposal 编辑器移动节点位置无效')
            new_children.insert(index, node)
            parents[uid] = parent_uid
            continue

        if operation_type == 'delete_subtree':
            uid = str(node_uid)
            if uid == root_uid or uid not in nodes:
                raise _invalid('Proposal 编辑器删除节点引用无效')
            parent_uid = parents.get(uid)
            if parent_uid is None or parent_uid not in nodes:
                raise _invalid('Proposal 编辑器删除节点缺少父节点')
            subtree_root = nodes[uid]
            nodes[parent_uid]['children'] = [
                child
                for child in nodes[parent_uid]['children']
                if child is not subtree_root
            ]
            pending = [subtree_root]
            while pending:
                removed = pending.pop()
                removed_uid = str(removed['data']['uid'])
                pending.extend(removed['children'])
                nodes.pop(removed_uid, None)
                parents.pop(removed_uid, None)
            continue

        if operation_type != 'set_document_meta':
            raise _invalid('Proposal 编辑器操作类型无效')
        for field, value in payload['set'].items():
            editor_document[field] = clone_json_value(value)
        for field in payload['unset']:
            editor_document.pop(field, None)

    normalized_editor_result, _summary = normalize_ai_editable_source_document(
        editor_document,
        max_node_count=max_node_count,
    )
    if canonical_json_bytes(normalized_editor_result) != canonical_json_bytes(
        artifact_document,
    ):
        raise _invalid('Proposal 编辑器重放结果与 Artifact 不一致')
    return editor_document


def normalize_proposal_operations_for_apply(  # noqa: PLR0912, PLR0915
    *,
    base_document: dict[str, Any],
    operations: list[dict[str, Any]],
    artifact_document: dict[str, Any],
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> list[dict[str, Any]]:
    """验证并把唯一可确定的 v0 Proposal 转为当前冻结协议。

    新协议先按规范 diff 精确匹配。只有当原数组精确等于旧版服务端 diff
    时才进入兼容路径；旧 ``patch`` 的删除歧义通过 Artifact 中字段是否
    存在消解，随后仍需完整顺序重放到 Artifact。任何混合或篡改都会失败。
    """
    if not isinstance(operations, list):
        raise _invalid('Proposal operations 必须是数组')
    try:
        _index_tree(base_document.get('root'))
        _index_tree(artifact_document.get('root'))
        normalized_base, _summary = normalize_ai_document(
            base_document,
            content_policy='source',
            max_node_count=max_node_count,
        )
        normalized_artifact, _summary = normalize_ai_document(
            artifact_document,
            content_policy='source',
            max_node_count=max_node_count,
        )
        if canonical_json_bytes(normalized_base) != canonical_json_bytes(base_document):
            raise _invalid('Proposal 基线文档不是规范文档')
        if canonical_json_bytes(normalized_artifact) != canonical_json_bytes(
            artifact_document,
        ):
            raise _invalid('Proposal Artifact 文档不是规范文档')

        from module_mindmap.ai.diff import (  # noqa: PLC0415
            build_document_diff,
            build_legacy_document_diff_v0,
        )

        current_operations, _impact = build_document_diff(
            normalized_base,
            normalized_artifact,
        )
        if canonical_json_bytes(operations) == canonical_json_bytes(current_operations):
            replayed = strict_replay_document_operations(
                normalized_base,
                current_operations,
                max_node_count=max_node_count,
            )
            if canonical_json_bytes(replayed) != canonical_json_bytes(normalized_artifact):
                raise _invalid('Proposal operations 重放结果与 Artifact 不一致')
            return current_operations

        expected_legacy = build_legacy_document_diff_v0(
            normalized_base,
            normalized_artifact,
        )
        if canonical_json_bytes(operations) != canonical_json_bytes(expected_legacy):
            raise _invalid('旧版 Proposal operations 无法确定性验证，请重新生成')

        artifact_nodes, _parents, _root_uid = _index_tree(normalized_artifact['root'])
        translated: list[dict[str, Any]] = []
        for operation in operations:
            operation_type = operation['type']
            if operation_type == 'update_node':
                uid = str(operation['nodeUid'])
                target_node = artifact_nodes.get(uid)
                patch = operation['payload']['patch']
                if target_node is None or not isinstance(patch, dict) or not patch:
                    raise _invalid('旧版节点更新无法确定性转换')
                target_data = target_node['data']
                set_values: dict[str, Any] = {}
                unset_values: list[str] = []
                for field, value in patch.items():
                    if field in target_data:
                        if target_data[field] != value:
                            raise _invalid('旧版节点更新与 Artifact 不一致')
                        set_values[field] = clone_json_value(target_data[field])
                    elif value is None:
                        unset_values.append(field)
                    else:
                        raise _invalid('旧版节点删除语义不明确')
                translated.append({
                    'type': 'update_node',
                    'nodeUid': uid,
                    'payload': {'set': set_values, 'unset': sorted(unset_values)},
                })
                continue
            if operation_type == 'set_document_meta':
                fields = operation['payload']['fields']
                if (
                    not isinstance(fields, list)
                    or not fields
                    or any(not isinstance(field, str) for field in fields)
                    or len(set(fields)) != len(fields)
                    or set(fields) - DOCUMENT_META_FIELDS
                ):
                    raise _invalid('旧版文档元数据更新无法确定性转换')
                set_values = {
                    field: clone_json_value(normalized_artifact[field])
                    for field in fields
                    if field in normalized_artifact
                }
                unset_values = [
                    field for field in fields if field not in normalized_artifact
                ]
                translated.append({
                    'type': 'set_document_meta',
                    'nodeUid': None,
                    'payload': {'set': set_values, 'unset': unset_values},
                })
                continue
            translated.append(clone_json_value(operation))

        replayed_legacy = strict_replay_document_operations(
            normalized_base,
            translated,
            max_node_count=max_node_count,
        )
        if canonical_json_bytes(replayed_legacy) != canonical_json_bytes(
            normalized_artifact,
        ):
            raise _invalid('旧版 Proposal 重放结果与 Artifact 不一致')
        # 返回当前算法生成的唯一规范序列；后续三方哈希门禁仍会再次重放。
        return current_operations
    except MindmapArtifactError as exc:
        if exc.code == PROPOSAL_INTEGRITY_ERROR_CODE:
            raise
        raise _invalid(f'Proposal operation 转换失败: {exc}') from exc
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise _invalid('Proposal operation 结构无效') from exc


def verify_proposal_document_integrity(
    *,
    base_document: dict[str, Any],
    operations: list[dict[str, Any]],
    artifact_document: dict[str, Any],
    proposal_result_hash: str,
    manifest_document_hash: str,
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> dict[str, Any]:
    """绑定基线、规范操作序列、Artifact 正文和两个持久化哈希。"""
    replayed = strict_replay_document_operations(
        base_document,
        operations,
        max_node_count=max_node_count,
    )
    try:
        normalized_base, _summary = normalize_ai_document(
            base_document,
            content_policy='source',
            max_node_count=max_node_count,
        )
        normalized_artifact, _summary = normalize_ai_document(
            artifact_document,
            content_policy='source',
            max_node_count=max_node_count,
        )
        replayed_bytes = canonical_json_bytes(replayed)
        artifact_bytes = canonical_json_bytes(artifact_document)
        if canonical_json_bytes(normalized_artifact) != artifact_bytes:
            raise _invalid('Proposal Artifact 文档不是规范文档')
        if replayed_bytes != artifact_bytes:
            raise _invalid('Proposal operations 重放结果与 Artifact 不一致')
        replayed_hash = compute_document_hash(replayed)
        if (
            not isinstance(proposal_result_hash, str)
            or not isinstance(manifest_document_hash, str)
            or replayed_hash != proposal_result_hash
            or replayed_hash != manifest_document_hash
        ):
            raise _invalid('Proposal 结果哈希不一致')

        # 只接受服务端差异算法产生的唯一规范序列。这样额外插入的无副作用
        # update/move/meta 操作也无法绕过“重放结果相同”的哈希门禁。
        from module_mindmap.ai.diff import build_document_diff  # noqa: PLC0415

        expected_operations, _impact = build_document_diff(
            normalized_base,
            normalized_artifact,
        )
        if canonical_json_bytes(expected_operations) != canonical_json_bytes(operations):
            raise _invalid('Proposal operations 不是规范差异序列')
    except MindmapArtifactError as exc:
        if exc.code == PROPOSAL_INTEGRITY_ERROR_CODE:
            raise
        raise _invalid(f'Proposal 完整性校验失败: {exc}') from exc
    return replayed
