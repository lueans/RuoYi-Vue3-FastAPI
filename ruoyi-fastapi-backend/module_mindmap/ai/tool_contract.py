"""所有 AI Agent 共用的隔离脑图工具合同。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from module_mindmap.ai.document import (
    AI_ALLOWED_LAYOUTS,
    AI_MAX_NODE_COUNT,
    MindmapArtifactError,
    build_smm_artifact,
    normalize_ai_document,
    project_ai_source_document,
)
from module_mindmap.service.simple_mind_document_codec import clone_json_value

MAX_TOOL_BATCH_SIZE = 200
AI_NODE_CONTENT_FIELDS = frozenset({'text', 'note', 'hyperlink', 'tag'})
AI_ADD_NODE_FIELDS = frozenset({'clientRef', 'parentUid'}) | AI_NODE_CONTENT_FIELDS


@dataclass(slots=True)
class DraftOperation:
    type: str
    node_uid: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'type': self.type,
            'nodeUid': self.node_uid,
            'payload': clone_json_value(self.payload),
        }


@dataclass(slots=True)
class MindmapDraft:
    document: dict[str, Any]
    operations: list[DraftOperation] = field(default_factory=list)
    completed: bool = False


class MindmapToolService:
    """只操作单任务内存草稿，不接触数据库、画布或用户文件系统。"""

    def __init__(
        self,
        *,
        base_document: dict[str, Any] | None = None,
        scope: dict[str, Any] | None = None,
        trusted_source: bool = False,
        ai_job_id: str | None = None,
        intent: str | None = None,
        max_nodes: int | None = None,
        max_depth: int | None = None,
    ) -> None:
        self._draft: MindmapDraft | None = None
        self._trusted_source = trusted_source
        self._ai_job_id = ai_job_id
        self._intent = str(intent or '')
        self._task_max_nodes = int(max_nodes) if max_nodes is not None else None
        self._task_max_depth = int(max_depth) if max_depth is not None else None
        if self._task_max_nodes is not None and self._task_max_nodes < 1:
            raise MindmapArtifactError(
                'AI 脑图任务节点上限无效',
                code='AI_BUDGET_EXCEEDED',
            )
        if self._task_max_depth is not None and self._task_max_depth < 1:
            raise MindmapArtifactError(
                'AI 脑图任务层级上限无效',
                code='AI_BUDGET_EXCEEDED',
            )
        self._max_node_count = AI_MAX_NODE_COUNT
        self._scope = clone_json_value(scope or {'type': 'document'})
        self._authorized_uids: set[str] = set()
        self._scope_root_uids: list[str] = []
        self._source_scope_summary: dict[str, int] | None = None
        if base_document is not None:
            document, _summary = normalize_ai_document(
                base_document,
                content_policy='source' if trusted_source else 'generated',
                max_node_count=self._max_node_count,
            )
            self._draft = MindmapDraft(document=document)
            self._initialize_scope()
            self._source_scope_summary = self.authorized_scope_summary()

    def fork(self) -> MindmapToolService:
        """复制当前草稿，供 Agent 工具计划进行事务化预执行。"""
        clone = object.__new__(MindmapToolService)
        clone._draft = (
            None
            if self._draft is None
            else MindmapDraft(
                document=clone_json_value(self._draft.document),
                operations=[
                    DraftOperation(item.type, item.node_uid, clone_json_value(item.payload))
                    for item in self._draft.operations
                ],
                completed=self._draft.completed,
            )
        )
        clone._trusted_source = self._trusted_source
        clone._ai_job_id = self._ai_job_id
        clone._intent = self._intent
        clone._task_max_nodes = self._task_max_nodes
        clone._task_max_depth = self._task_max_depth
        clone._max_node_count = self._max_node_count
        clone._scope = clone_json_value(self._scope)
        clone._authorized_uids = set(self._authorized_uids)
        clone._scope_root_uids = list(self._scope_root_uids)
        clone._source_scope_summary = (
            None
            if self._source_scope_summary is None
            else dict(self._source_scope_summary)
        )
        return clone

    def operation_cursor(self) -> int:
        """返回当前变更游标，供 Adapter 生成可重放的实时事件。"""
        if self._draft is None:
            return 0
        return len(self._draft.operations)

    def attempt_effect_marker(self) -> tuple[bool, int, bool]:
        """Return a content-free marker for provider retry safety checks.

        ``operation_cursor`` alone cannot observe ``start_document`` because
        creation of the root is intentionally not represented as a patch
        operation.  The retry boundary also needs to distinguish that draft
        creation (and artifact completion) from an untouched fork, without
        reading or logging any node content.
        """
        draft = self._draft
        if draft is None:
            return False, 0, False
        return True, len(draft.operations), bool(draft.completed)

    def build_stream_delta(
        self,
        *,
        after_cursor: int,
        tool_name: str,
    ) -> dict[str, Any]:
        """构造不依赖最终 Artifact 的小型、可重放草稿增量。

        事件只包含用户已授权范围内的节点变更。新建脑图的根节点没有对应
        DraftOperation，因此 start_document 会额外携带一次最小初始状态。
        """
        draft = self._require_draft(allow_completed=True)
        cursor = max(0, min(int(after_cursor), len(draft.operations)))
        payload: dict[str, Any] = {
            'toolName': tool_name,
            'operationCursor': len(draft.operations),
            'operations': [
                operation.to_dict()
                for operation in draft.operations[cursor:]
            ],
            # previewState 仅供 TaskManager 写入短 TTL Redis 草稿，不得进入
            # mindmap_ai_job_event 或 SSE 审计 payload。
            'previewState': self.read_projection(),
        }
        if tool_name == 'start_document' and cursor == 0:
            root = draft.document['root']
            payload['initialState'] = {
                'root': {
                    'data': clone_json_value(root.get('data') or {}),
                    'children': [],
                },
                'layout': draft.document.get('layout'),
                'theme': clone_json_value(draft.document.get('theme')),
                'view': None,
                'documentData': clone_json_value(draft.document.get('documentData') or {}),
            }
        summary = self.authorized_scope_summary()
        payload['summary'] = {
            'nodeCount': summary['nodeCount'],
            'treeDepth': summary['treeDepth'],
        }
        return payload

    def _require_draft(self, *, allow_completed: bool = False) -> MindmapDraft:
        if self._draft is None:
            raise MindmapArtifactError('请先创建脑图草稿')
        if self._draft.completed and not allow_completed:
            raise MindmapArtifactError('脑图草稿已经完成，不能继续修改')
        return self._draft

    def _initialize_scope(self) -> None:
        draft = self._require_draft()
        nodes, parents = self._index_tree(draft.document['root'])
        scope_type = str(self._scope.get('type') or 'document')
        if scope_type == 'document':
            self._authorized_uids = set(nodes)
            self._scope_root_uids = [str(draft.document['root']['data']['uid'])]
            return
        if scope_type == 'branch':
            roots = [str(self._scope.get('rootUid') or '')]
        elif scope_type == 'selectedNodes':
            roots = [str(uid) for uid in self._scope.get('nodeUids') or []]
        else:
            raise MindmapArtifactError('AI 脑图授权范围无效')
        if not roots or any(uid not in nodes for uid in roots):
            raise MindmapArtifactError('AI 脑图授权范围中的节点不存在')
        roots = self._minimal_scope_roots(roots, parents)
        if scope_type == 'branch':
            self._scope['rootUid'] = roots[0]
        elif scope_type == 'selectedNodes':
            # 选择父节点已经授权其整棵子树。保留同一子树中的后代选择会在
            # synthetic projection 中复制相同 UID，既扩大输入又令投影失效。
            self._scope['nodeUids'] = list(roots)
        authorized: set[str] = set()
        for root_uid in roots:
            pending = [nodes[root_uid]]
            while pending:
                node = pending.pop()
                authorized.add(str(node['data']['uid']))
                pending.extend(node.get('children') or [])
        self._authorized_uids = authorized
        self._scope_root_uids = roots

    @staticmethod
    def _minimal_scope_roots(
        roots: list[str],
        parents: dict[str, str | None],
    ) -> list[str]:
        """按输入顺序保留不被另一选择祖先覆盖的顶层范围根。"""
        unique_roots = list(dict.fromkeys(roots))
        selected = set(unique_roots)
        minimal: list[str] = []
        for uid in unique_roots:
            ancestor_uid = parents.get(uid)
            while ancestor_uid is not None and ancestor_uid not in selected:
                ancestor_uid = parents.get(ancestor_uid)
            if ancestor_uid is None:
                minimal.append(uid)
        return minimal

    def _require_authorized(self, uid: str, action: str) -> None:
        if uid not in self._authorized_uids:
            raise MindmapArtifactError(f'{action}超出本次 AI 授权范围: {uid}')

    @staticmethod
    def _apply_node_patch(data: dict[str, Any], patch: dict[str, Any]) -> None:
        """应用节点 patch。"""
        for key, value in patch.items():
            data[key] = clone_json_value(value)

    @staticmethod
    def _prepare_node_patch(raw_patch: Any, allowed: set[str]) -> dict[str, Any]:
        if not isinstance(raw_patch, dict) or not raw_patch:
            raise MindmapArtifactError('更新节点包含不允许的字段')
        if set(raw_patch) - allowed:
            raise MindmapArtifactError('更新节点包含不允许的字段')
        return clone_json_value(raw_patch)

    @staticmethod
    def _validate_add_node_batch(nodes: list[dict[str, Any]]) -> None:
        """预检整批参数及按输入顺序可见的 clientRef。"""
        declared_refs: set[str] = set()
        for item in nodes:
            if not isinstance(item, dict):
                raise MindmapArtifactError('新增节点参数必须是对象')
            if set(item) - AI_ADD_NODE_FIELDS:
                raise MindmapArtifactError('新增节点包含不允许的字段')
            client_ref = str(item.get('clientRef') or '')
            if client_ref and client_ref in declared_refs:
                raise MindmapArtifactError(f'新增节点 clientRef 重复: {client_ref}')
            parent_ref = str(item.get('parentUid') or '')
            if parent_ref.startswith('@'):
                referenced_ref = parent_ref[1:]
                if not referenced_ref or referenced_ref not in declared_refs:
                    raise MindmapArtifactError(
                        f'新增节点 parentUid 引用未知或尚未创建的 clientRef: '
                        f'{parent_ref}'
                    )
            if client_ref:
                declared_refs.add(client_ref)

    @staticmethod
    def _new_uid() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _index_tree(root: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str | None]]:
        nodes: dict[str, dict[str, Any]] = {}
        parents: dict[str, str | None] = {}
        pending = [(root, None)]
        while pending:
            node, parent_uid = pending.pop()
            data = node.get('data') or {}
            uid = str(data.get('uid') or '')
            if not uid:
                raise MindmapArtifactError('脑图节点缺少稳定 UID')
            nodes[uid] = node
            parents[uid] = parent_uid
            pending.extend((child, uid) for child in reversed(node.get('children') or []))
        return nodes, parents

    def _project_document(self, document: dict[str, Any]) -> dict[str, Any]:
        projection, _summary = project_ai_source_document(
            document,
            max_node_count=self._max_node_count,
        )
        if self._scope.get('type', 'document') == 'document':
            return projection
        nodes, parents = self._index_tree(projection['root'])
        # 两个原本并列的 selectedNodes 可能在本轮被移动成祖孙关系；每次
        # 读取都重新最小化，避免实时预览再次产生重复 UID。
        projection_root_uids = self._minimal_scope_roots(self._scope_root_uids, parents)
        roots = [clone_json_value(nodes[uid]) for uid in projection_root_uids]
        if len(roots) == 1:
            projection['root'] = roots[0]
        else:
            projection['root'] = {
                'data': {
                    'uid': 'authorized-scope-preview',
                    'text': '已授权节点（此根节点不可编辑）',
                    'expand': True,
                },
                'children': roots,
            }
        projection['authorizedScope'] = clone_json_value(self._scope)
        return projection

    def read_projection(self) -> dict[str, Any]:
        draft = self._require_draft(allow_completed=True)
        return self._project_document(draft.document)

    def _authorized_scope_summary_for_document(
        self,
        document: dict[str, Any],
    ) -> dict[str, int]:
        projection = self._project_document(document)
        _normalized, summary = normalize_ai_document(
            projection,
            content_policy='source' if self._trusted_source else 'generated',
            max_node_count=self._max_node_count,
        )
        if (
            self._scope.get('type') == 'selectedNodes'
            and len(self._scope_root_uids) > 1
            and projection['root']['data']['uid'] == 'authorized-scope-preview'
        ):
            summary = {
                **summary,
                'nodeCount': max(0, summary['nodeCount'] - 1),
                'treeDepth': max(1, summary['treeDepth'] - 1),
            }
        return summary

    def authorized_scope_summary(self) -> dict[str, int]:
        """统计当前授权范围，避免把范围外的历史节点计入本次生成配额。"""
        draft = self._require_draft(allow_completed=True)
        return self._authorized_scope_summary_for_document(draft.document)

    def _normalize_candidate_document(
        self,
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Normalize Agent-created state and classify size as output budget."""
        try:
            return normalize_ai_document(
                candidate,
                content_policy='source' if self._trusted_source else 'generated',
                max_node_count=self._max_node_count,
            )
        except MindmapArtifactError as exc:
            if exc.code == 'AI_INPUT_TOO_LARGE':
                raise MindmapArtifactError(
                    str(exc),
                    code='AI_BUDGET_EXCEEDED',
                ) from exc
            raise

    def _enforce_candidate_structure_budget(
        self,
        candidate: dict[str, Any],
        pending_operations: list[DraftOperation],
    ) -> None:
        """在提交工具调用前按任务策略校验，失败时保持整批原子回滚。"""
        if self._task_max_nodes is None and self._task_max_depth is None:
            return
        draft = self._require_draft()
        summary = self._authorized_scope_summary_for_document(candidate)
        if self._task_max_nodes is not None:
            if self._source_scope_summary is None:
                node_limit_exceeded = summary['nodeCount'] > self._task_max_nodes
                remaining_nodes = max(
                    0,
                    self._task_max_nodes - self.authorized_scope_summary()['nodeCount'],
                )
            else:
                created_count = sum(
                    1
                    for operation in (*draft.operations, *pending_operations)
                    if operation.type == 'create_node'
                )
                node_limit_exceeded = created_count > self._task_max_nodes
                committed_created_count = sum(
                    1 for operation in draft.operations
                    if operation.type == 'create_node'
                )
                remaining_nodes = max(
                    0,
                    self._task_max_nodes - committed_created_count,
                )
            if node_limit_exceeded:
                requested_nodes = sum(
                    1 for operation in pending_operations
                    if operation.type == 'create_node'
                )
                raise MindmapArtifactError(
                    '新增节点超过本任务上限'
                    f'（剩余节点预算 {remaining_nodes}，本批新增 {requested_nodes}，'
                    f'上限 {self._task_max_nodes}）',
                    code='AI_BUDGET_EXCEEDED',
                )
        if self._task_max_depth is not None:
            depth_limit = self._task_max_depth
            if self._source_scope_summary is not None:
                depth_limit = max(
                    depth_limit,
                    self._source_scope_summary['treeDepth'],
                )
            if summary['treeDepth'] > depth_limit:
                raise MindmapArtifactError(
                    '节点层级超过本任务上限'
                    f'（当前 {summary["treeDepth"]} 层，上限 {depth_limit} 层）',
                    code='AI_BUDGET_EXCEEDED',
                )

    def start_document(self, title: str, layout: str = 'logicalStructure') -> dict[str, Any]:
        if self._draft is not None:
            raise MindmapArtifactError('脑图草稿已经存在')
        if not isinstance(title, str) or not title.strip():
            raise MindmapArtifactError('脑图标题必须是非空字符串')
        if not isinstance(layout, str):
            raise MindmapArtifactError('AI 脑图布局类型无效')
        if layout not in AI_ALLOWED_LAYOUTS:
            raise MindmapArtifactError('AI 脑图布局类型无效')
        root_uid = self._new_uid()
        document = {
            'root': {'data': {'uid': root_uid, 'text': title, 'expand': True}, 'children': []},
            'layout': layout,
            'theme': {'template': 'default', 'config': {}},
            'view': None,
            'documentData': {},
        }
        normalized, _summary = normalize_ai_document(
            document,
            max_node_count=self._max_node_count,
        )
        self._draft = MindmapDraft(document=normalized)
        self._scope = {'type': 'document'}
        self._scope_root_uids = [root_uid]
        self._authorized_uids = {root_uid}
        return {'rootUid': root_uid}

    def add_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_TOOL_BATCH_SIZE:
            raise MindmapArtifactError('每次只能新增1到200个节点')
        self._validate_add_node_batch(nodes)
        draft = self._require_draft()
        candidate = clone_json_value(draft.document)
        indexed, _parents = self._index_tree(candidate['root'])
        created: list[dict[str, str]] = []
        operations: list[DraftOperation] = []
        created_refs: dict[str, str] = {}
        candidate_authorized = set(self._authorized_uids)
        for item in nodes:
            raw_parent_uid = str(item.get('parentUid') or '')
            parent_uid = (
                created_refs[raw_parent_uid[1:]]
                if raw_parent_uid.startswith('@')
                else raw_parent_uid
            )
            if parent_uid not in candidate_authorized:
                raise MindmapArtifactError(f'新增节点超出本次 AI 授权范围: {parent_uid}')
            parent = indexed.get(parent_uid)
            if parent is None:
                raise MindmapArtifactError(f'新增节点的父节点不存在: {parent_uid}')
            uid = self._new_uid()
            data = {'uid': uid, 'text': item.get('text'), 'expand': True}
            client_ref = str(item.get('clientRef') or '')
            for key in ('note', 'hyperlink', 'tag'):
                if item.get(key) is not None:
                    data[key] = clone_json_value(item[key])
            node = {'data': data, 'children': []}
            parent.setdefault('children', []).append(node)
            indexed[uid] = node
            candidate_authorized.add(uid)
            if client_ref:
                created_refs[client_ref] = uid
            created.append({'clientRef': client_ref, 'nodeUid': uid})
            operations.append(DraftOperation('create_node', uid, {
                'parentUid': parent_uid,
                'index': len(parent['children']) - 1,
                'data': clone_json_value(data),
            }))
        normalized, _summary = self._normalize_candidate_document(candidate)
        self._enforce_candidate_structure_budget(normalized, operations)
        draft.document = normalized
        self._authorized_uids.update(item['nodeUid'] for item in created)
        draft.operations.extend(operations)
        return {'created': created}

    def update_nodes(self, updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(updates, list) or not 1 <= len(updates) <= MAX_TOOL_BATCH_SIZE:
            raise MindmapArtifactError('每次只能更新1到200个节点')
        draft = self._require_draft()
        candidate = clone_json_value(draft.document)
        indexed, _parents = self._index_tree(candidate['root'])
        operations: list[DraftOperation] = []
        allowed = {'text', 'note', 'hyperlink', 'tag'}
        for item in updates:
            if not isinstance(item, dict):
                raise MindmapArtifactError('更新节点参数必须是对象')
            uid = str(item.get('nodeUid') or '')
            self._require_authorized(uid, '更新节点')
            node = indexed.get(uid)
            if node is None:
                raise MindmapArtifactError(f'更新节点不存在: {uid}')
            patch = self._prepare_node_patch(item.get('patch'), allowed)
            self._apply_node_patch(node['data'], patch)
            set_values = {key: clone_json_value(value) for key, value in patch.items()}
            operations.append(DraftOperation('update_node', uid, {
                'set': set_values,
                'unset': [],
            }))
        normalized, _summary = self._normalize_candidate_document(candidate)
        draft.document = normalized
        draft.operations.extend(operations)
        return {'updated': len(updates)}

    def move_nodes(self, moves: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(moves, list) or not 1 <= len(moves) <= MAX_TOOL_BATCH_SIZE:
            raise MindmapArtifactError('每次只能移动1到200个节点')
        draft = self._require_draft()
        candidate = clone_json_value(draft.document)
        operations: list[DraftOperation] = []
        for item in moves:
            if not isinstance(item, dict):
                raise MindmapArtifactError('移动节点参数必须是对象')
            indexed, parents = self._index_tree(candidate['root'])
            uid = str(item.get('nodeUid') or '')
            parent_uid = str(item.get('parentUid') or '')
            self._require_authorized(uid, '移动节点')
            self._require_authorized(parent_uid, '移动节点')
            node = indexed.get(uid)
            new_parent = indexed.get(parent_uid)
            old_parent_uid = parents.get(uid)
            if node is None or new_parent is None or old_parent_uid is None:
                raise MindmapArtifactError('移动节点或目标父节点不存在，且根节点不能移动')
            ancestor_uid: str | None = parent_uid
            while ancestor_uid is not None:
                if ancestor_uid == uid:
                    raise MindmapArtifactError('移动节点不能形成循环')
                ancestor_uid = parents.get(ancestor_uid)
            old_parent = indexed[old_parent_uid]
            old_parent['children'] = [child for child in old_parent.get('children') or [] if child is not node]
            raw_index = item.get('index')
            index = len(new_parent.get('children') or []) if raw_index is None else int(raw_index)
            if index < 0 or index > len(new_parent.get('children') or []):
                raise MindmapArtifactError('移动节点的位置无效')
            new_parent.setdefault('children', []).insert(index, node)
            operations.append(DraftOperation('move_node', uid, {'parentUid': parent_uid, 'index': index}))
        normalized, _summary = self._normalize_candidate_document(candidate)
        self._enforce_candidate_structure_budget(normalized, operations)
        draft.document = normalized
        draft.operations.extend(operations)
        return {'moved': len(moves)}

    def remove_nodes(self, node_uids: list[str]) -> dict[str, Any]:
        if not isinstance(node_uids, list) or not 1 <= len(node_uids) <= MAX_TOOL_BATCH_SIZE:
            raise MindmapArtifactError('每次只能删除1到200个节点')
        draft = self._require_draft()
        candidate = clone_json_value(draft.document)
        indexed, parents = self._index_tree(candidate['root'])
        root_uid = str(candidate['root']['data']['uid'])
        requested = {str(uid) for uid in node_uids}
        if '' in requested:
            raise MindmapArtifactError('删除节点 UID 不能为空')
        for uid in requested:
            self._require_authorized(uid, '删除节点')
        if root_uid in requested:
            raise MindmapArtifactError('不能删除脑图根节点')
        if self._scope.get('type') != 'document' and requested.intersection(self._scope_root_uids):
            raise MindmapArtifactError('不能删除本次授权范围的根节点')
        unknown = requested - set(indexed)
        if unknown:
            raise MindmapArtifactError(f'删除节点不存在: {sorted(unknown)[0]}')
        for uid in requested:
            parent_uid = parents[uid]
            if parent_uid in requested:
                continue
            parent = indexed[str(parent_uid)]
            parent['children'] = [
                child for child in parent.get('children') or []
                if str((child.get('data') or {}).get('uid')) != uid
            ]
        normalized, _summary = self._normalize_candidate_document(candidate)
        draft.document = normalized
        draft.operations.extend(DraftOperation('delete_subtree', uid) for uid in sorted(requested))
        return {'removed': len(requested)}

    def set_document_meta(
        self,
        *,
        layout: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        draft = self._require_draft()
        if self._scope.get('type', 'document') != 'document':
            raise MindmapArtifactError('局部授权范围不能修改整份脑图元数据')
        candidate = clone_json_value(draft.document)
        patch: dict[str, Any] = {}
        if layout is not None:
            if not isinstance(layout, str):
                raise MindmapArtifactError('AI 脑图布局类型无效')
            candidate['layout'] = layout
            patch['layout'] = layout
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise MindmapArtifactError('脑图标题必须是非空字符串')
            candidate['root']['data']['text'] = title
            patch['title'] = title
        if not patch:
            raise MindmapArtifactError('文档元数据更新不能为空')
        normalized, _summary = self._normalize_candidate_document(candidate)
        draft.document = normalized
        if title is not None:
            root_uid = str(normalized['root']['data']['uid'])
            draft.operations.append(DraftOperation('update_node', root_uid, {
                'set': {'text': normalized['root']['data']['text']},
                'unset': [],
            }))
        if layout is not None:
            draft.operations.append(DraftOperation('set_document_meta', payload={
                'set': {'layout': layout},
                'unset': [],
            }))
        return patch

    def validate_draft(self) -> dict[str, Any]:
        draft = self._require_draft()
        normalized, summary = self._normalize_candidate_document(draft.document)
        draft.document = normalized
        return summary

    def complete_artifact(
        self,
        *,
        title: str,
        agent_key: str,
        adapter_version: str,
        prompt_version: str,
        artifact_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, int], list[dict[str, Any]]]:
        draft = self._require_draft()
        try:
            artifact, summary = build_smm_artifact(
                draft.document,
                title=title,
                agent_key=agent_key,
                adapter_version=adapter_version,
                prompt_version=prompt_version,
                artifact_id=artifact_id,
                preserve_source_content=self._trusted_source,
                max_node_count=self._max_node_count,
            )
        except MindmapArtifactError as exc:
            if exc.code == 'AI_INPUT_TOO_LARGE':
                raise MindmapArtifactError(
                    str(exc),
                    code='AI_BUDGET_EXCEEDED',
                ) from exc
            raise
        draft.completed = True
        return artifact, summary, [operation.to_dict() for operation in draft.operations]
