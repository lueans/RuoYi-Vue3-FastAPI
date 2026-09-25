"""受控的 AI 脑图直写网关。

Agent 只能通过本模块请求脑图领域操作；本模块不直接操作 ORM，而是把操作
转换为现有的 CAS/幂等/协作广播保存服务。Proposal/Artifact 流程继续独立存在。
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from exceptions.exception import ServiceException
from module_mindmap.ai.change_summary import summarize_committed_node_changes
from module_mindmap.ai.document import (
    compute_document_hash,
    document_from_mindmap_detail,
    normalize_ai_editable_source_document,
)
from module_mindmap.entity.vo.mindmap_comment_vo import MindmapCommentCreateModel
from module_mindmap.entity.vo.mindmap_vo import (
    MindmapContentBatchModel,
    MindmapContentOperationModel,
)
from module_mindmap.service.mindmap_comment_service import MindmapCommentService
from module_mindmap.service.mindmap_document_service import validate_tag_binding_access
from module_mindmap.service.mindmap_service import MindmapService, _apply_node_tag_operations
from module_mindmap.service.mindmap_tag_service import MindmapTagService
from utils.log_util import logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_MUTATION_ID_LENGTH = 100
MAX_COMMENT_CONTENT_LENGTH = 5_000
MAX_NODE_TAGS = 50


async def _resolve_existing_tags(
    db: AsyncSession,
    tags: Any,
    *,
    user_id: int,
    owner_id: int,
    previous_tags: list[Any],
    cache: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """AI may reference existing identities, never create tag definitions.

    Resolve before comparing data so a minimal reference and the authoritative
    expanded snapshot describe the same change. Persistence still locks and
    revalidates the definitions to protect against concurrent tag governance.
    """
    if not isinstance(tags, list) or len(tags) > MAX_NODE_TAGS:
        raise ServiceException(message='AI 节点标签必须是最多 50 项的已有标签引用数组')
    existing_ids = {
        tag['tagId'] for tag in previous_tags
        if isinstance(tag, dict) and isinstance(tag.get('tagId'), int)
    }
    resolved: list[dict[str, Any]] = []
    seen: set[int] = set()
    for reference in tags:
        tag_id = reference.get('tagId') if isinstance(reference, dict) else None
        if not isinstance(tag_id, int) or isinstance(tag_id, bool) or tag_id <= 0:
            raise ServiceException(message='AI 只能引用已有标签的合法 tagId，不能创建标签')
        if tag_id in seen:
            continue
        seen.add(tag_id)
        if tag_id not in cache:
            # A collaborator may retain an identity already bound to this
            # node, without receiving access to the owner's private catalog.
            # The previous bindings came from the authoritative document.
            reader_id = owner_id if tag_id in existing_ids else user_id
            cache[tag_id] = await MindmapTagService.get_tag_detail(db, tag_id, reader_id)
        definition = cache[tag_id]
        # Check every reference, not only cache misses: a retained private tag
        # earlier in the same batch must never authorize a new binding later.
        if tag_id not in existing_ids and definition.get('ownerId') not in (0, user_id):
            raise ServiceException(message='AI 无权新增引用该标签，请从可用标签库选择')
        try:
            validate_tag_binding_access(SimpleNamespace(
                owner_id=definition.get('ownerId'),
                status=definition.get('status'),
                name=definition.get('name', definition.get('text', str(tag_id))),
            ), owner_id, tag_id in existing_ids)
        except ValueError as exc:
            raise ServiceException(message=str(exc)) from exc
        tag = {
            'tagId': tag_id,
            'categoryId': definition.get('categoryId'),
            'uuid': definition.get('uuid'),
            'tagKey': definition.get('tagKey'),
            'text': definition.get('name', definition.get('text')),
            'style': deepcopy(definition.get('style') or {}),
            'status': definition.get('status'),
            'definitionRevision': definition.get('definitionRevision'),
        }
        previous = next((tag for tag in previous_tags if isinstance(tag, dict) and tag.get('tagId') == tag_id), {})
        for field in ('placement', 'align'):
            value = reference.get(field, previous.get(field))
            if value is not None:
                tag[field] = deepcopy(value)
        resolved.append(tag)
    return resolved


def _data_without_tags(data: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in data.items() if key != 'tag'}


def _canonical_tag_delta(
    uid: str, old_tags: list[dict[str, Any]], next_tags: list[dict[str, Any]],
) -> list[MindmapContentOperationModel]:
    """Materialize the final binding delta independently from node creation."""
    if old_tags == next_tags:
        return []
    if any(not isinstance(tag, dict) or not tag.get('tagId') for tag in old_tags + next_tags):
        raise ServiceException(message='旧版节点标签缺少 tagId，请同步云端标签后重试')
    # Definition labels/styles belong to the tag library, not this AI task.
    # Only membership, ordering and per-node placement are binding changes.
    # A concurrent rename must not turn an identity-preserving reference into
    # an AI edit or prevent bind/unbind restorations from netting to zero.
    binding_fields = {'tagId', 'placement', 'align'}
    old_bindings = [{key: deepcopy(value) for key, value in tag.items() if key in binding_fields} for tag in old_tags]
    next_bindings = [{key: deepcopy(value) for key, value in tag.items() if key in binding_fields} for tag in next_tags]
    if old_bindings == next_bindings:
        return []
    after = {str(tag['tagId']): tag for tag in next_tags}
    old_by_id = {str(tag['tagId']): tag for tag in old_bindings}
    next_by_id = {str(tag['tagId']): tag for tag in next_bindings}
    evidence = {
        'previousData': {'uid': uid, **({'tag': old_bindings} if old_bindings else {})},
        'data': {'uid': uid, **({'tag': next_bindings} if next_bindings else {})},
    }
    result = []
    for key in old_by_id:
        if key in after:
            continue
        result.append(MindmapContentOperationModel(
            type='node.tag.unbind', node_uid=uid,
            payload={'key': f'{uid}:{key}', 'tagKey': key, **deepcopy(evidence)},
        ))
    for key, tag in after.items():
        if old_by_id.get(key) != next_by_id[key]:
            result.append(MindmapContentOperationModel(
                type='node.tag.bind', node_uid=uid,
                payload={
                    'key': f'{uid}:{key}', 'tagKey': key,
                    'tag': deepcopy(tag), **deepcopy(evidence),
                },
            ))
    projected_order = [key for key in old_by_id if key in after] + [key for key in after if key not in old_by_id]
    if projected_order != list(after):
        result.append(MindmapContentOperationModel(
            type='node.tag.reorder', node_uid=uid,
            payload={'key': uid, 'tagKeys': list(after), **deepcopy(evidence)},
        ))
    return result


def empty_change_summary() -> dict[str, int]:
    """Return the stable, UI-facing direct-write change counters.

    Direct jobs do not create a Proposal row, so the normal Proposal impact
    object is not available to the client.  Keep this shape deliberately
    small and content-free; it is safe to persist in the AI audit event.
    """
    return {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 0}


def _root_node(tree: dict[str, Any]) -> dict[str, Any] | None:
    """Return a root node from either an SMM document or an editor tree.

    ``MindmapService.get_mindmap_detail_services`` exposes the structured
    document as a bare root node, while AI artifacts use ``{'root': ...}``.
    Gateway helper methods are shared by both callers, so never assume one
    transport shape at this boundary.
    """
    if not isinstance(tree, dict):
        return None
    envelope_root = tree.get('root')
    if isinstance(envelope_root, dict):
        return envelope_root
    return tree if isinstance(tree.get('data'), dict) else None


def _find_node(tree: dict[str, Any], node_uid: str) -> dict[str, Any]:
    """在权威树中找节点；不信任 Agent 提供的任意对象。"""
    root = _root_node(tree)
    if root is None:
        raise ServiceException(message='脑图正文不可用')
    stack = [root]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        data = node.get('data')
        if isinstance(data, dict) and str(data.get('uid')) == node_uid:
            return node
        stack.extend(reversed(node.get('children') or []))
    raise ServiceException(message='目标节点不存在或已被删除')


def _document_from_detail(detail: Any) -> dict[str, Any]:
    """Convert the detail VO's bare root into the internal SMM-v2 envelope."""
    document = {key: deepcopy(value) for key, value in document_from_mindmap_detail(detail).items()}
    raw_tree = document['root']
    if not isinstance(raw_tree, dict):
        raise ServiceException(message='无法读取脑图权威正文')
    document['root'] = raw_tree.get('root') if isinstance(raw_tree.get('root'), dict) else raw_tree
    document['layout'] = document['layout'] or raw_tree.get('layout') or 'logicalStructure'
    # Only the gateway accepts legacy envelopes inside node_tree. A VO value
    # takes precedence (including explicit empty metadata) over that fallback.
    for key, default in (('theme', {'template': 'default', 'config': {}}), ('view', None), ('documentData', {})):
        value = document[key] if document[key] is not None else deepcopy(raw_tree.get(key))
        document[key] = value if key == 'view' else value or default
    return document


def _tree_index(tree: dict[str, Any]) -> tuple[
    dict[str, dict[str, Any]], dict[str, str | None]
]:
    nodes: dict[str, dict[str, Any]] = {}
    parents: dict[str, str | None] = {}
    root = _root_node(tree)
    pending: list[tuple[dict[str, Any], str | None]] = []
    if isinstance(root, dict):
        pending.append((root, None))
    while pending:
        node, parent_uid = pending.pop()
        data = node.get('data')
        if not isinstance(data, dict) or not data.get('uid'):
            raise ServiceException(message='脑图节点缺少稳定 UID')
        uid = str(data['uid'])
        if uid in nodes:
            raise ServiceException(message='脑图节点 UID 重复，无法安全直写')
        nodes[uid] = node
        parents[uid] = parent_uid
        children = node.get('children')
        if not isinstance(children, list):
            node['children'] = []
            children = node['children']
        pending.extend((child, uid) for child in reversed(children) if isinstance(child, dict))
    if not nodes:
        raise ServiceException(message='脑图正文为空，无法安全直写')
    return nodes, parents


def _subtree_uids(node: dict[str, Any]) -> list[str]:
    result: list[str] = []
    pending = [node]
    while pending:
        current = pending.pop()
        data = current.get('data') or {}
        uid = data.get('uid')
        if uid:
            result.append(str(uid))
        pending.extend(child for child in reversed(current.get('children') or []) if isinstance(child, dict))
    return result


def _scope_uids(tree: dict[str, Any], scope: dict[str, Any] | None) -> set[str]:
    nodes, _parents = _tree_index(tree)
    scope = scope or {'type': 'document'}
    scope_type = str(scope.get('type') or 'document')
    if scope_type == 'document':
        return set(nodes)
    roots: list[str]
    if scope_type == 'branch':
        roots = [str(scope.get('rootUid') or '')]
    elif scope_type == 'selectedNodes':
        roots = [str(uid) for uid in scope.get('nodeUids') or []]
    else:
        raise ServiceException(message='AI 直写授权范围无效')
    if not roots or any(uid not in nodes for uid in roots):
        raise ServiceException(message='AI 直写授权范围中的节点不存在')
    authorized: set[str] = set()
    for root_uid in roots:
        pending = [nodes[root_uid]]
        while pending:
            node = pending.pop()
            uid = str((node.get('data') or {}).get('uid'))
            authorized.add(uid)
            pending.extend(child for child in node.get('children') or [] if isinstance(child, dict))
    return authorized


def _effective_canonical_operations(
    before: dict[str, Any],
    after: dict[str, Any],
    touched_uids: dict[str, None],
    structural_parents: set[str],
) -> list[MindmapContentOperationModel]:
    """Build each committed delta once, after the validated intents are applied."""
    before_nodes, before_parents = _tree_index(before)
    after_nodes, _ = _tree_index(after)
    deleted = set(before_nodes) - set(after_nodes)
    effective: list[MindmapContentOperationModel] = []
    # Resolve final edges before creates: inserting a create at its final index
    # first would collide with old sibling indices and look like a remote extra
    # to the domain's concurrent-order merge. Preorder also materializes new
    # parents before their children; subsequent creates only fill node data.
    for uid in after_nodes:
        if uid not in structural_parents:
            continue
        old_children = [str(child['data']['uid']) for child in before_nodes.get(uid, {}).get('children') or []]
        next_children = [str(child['data']['uid']) for child in after_nodes[uid].get('children') or []]
        if old_children == next_children:
            continue
        data = after_nodes[uid].get('data') or {}
        effective.append(MindmapContentOperationModel(
            type='node.update', node_uid=uid,
            payload={
                'dataChanged': False, 'childrenChanged': True,
                'data': deepcopy(data), 'previousData': deepcopy(data),
                'oldChildUids': old_children, 'childUids': next_children,
                'crossNodeDataSeparated': True, 'tagBindingsSeparated': True,
            },
        ))
    for uid in touched_uids:
        if uid not in after_nodes:
            continue
        old_data = _data_without_tags(before_nodes.get(uid, {}).get('data') or {})
        next_data = _data_without_tags(after_nodes[uid].get('data') or {})
        if old_data == next_data:
            continue
        effective.append(MindmapContentOperationModel(
            type='node.update' if uid in before_nodes else 'node.create', node_uid=uid,
            payload={
                'dataChanged': True, 'childrenChanged': False,
                'previousData': old_data, 'data': next_data,
                'crossNodeDataSeparated': True, 'tagBindingsSeparated': True,
            },
        ))

    if before.get('layout') != after.get('layout'):
        effective.append(MindmapContentOperationModel(
            type='file.layout.update', payload={'layout': deepcopy(after.get('layout'))},
        ))
    for uid, node in after_nodes.items():
        old_tags = (before_nodes.get(uid, {}).get('data') or {}).get('tag') or []
        next_tags = (node.get('data') or {}).get('tag') or []
        effective.extend(_canonical_tag_delta(uid, old_tags, next_tags))

    for uid in before_nodes:
        if uid not in deleted or before_parents.get(uid) in deleted:
            continue
        effective.append(MindmapContentOperationModel(
            type='node.delete',
            node_uid=uid,
            payload={
                'deletedNodeUids': [
                    item for item in _subtree_uids(before_nodes[uid]) if item in deleted
                ],
            },
        ))
    return effective


def _build_deferred_broadcast(
    mindmap_id: int,
    result: dict[str, Any],
    *,
    canonical: bool,
    comment_requests: list[tuple[str, str]],
    comments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build post-commit notifications without sending them prematurely."""
    pending: dict[str, Any] = {}
    if canonical and not bool(result.get('idempotentReplay')):
        pending['content'] = {
            'type': 'content_revision_changed',
            'mindmapId': mindmap_id,
            'contentRevision': result.get('contentRevision'),
            'clientMutationId': result.get('clientMutationId'),
            'concurrentMerge': bool(result.get('concurrentMerge')),
            'authoritativeReloadRequired': True,
            'yjsUpdateCount': result.get('yjsUpdateCount', 0),
            'yjsDeliveryMode': result.get('yjsDeliveryMode'),
            'changedNodes': result.get('changedNodes', []),
        }
    new_comments: list[dict[str, Any]] = []
    for index, comment in enumerate(comments):
        if not isinstance(comment, dict) or comment.get('idempotentReplay'):
            continue
        if index >= len(comment_requests):
            continue
        thread_id = comment.get('threadId')
        if thread_id is not None:
            new_comments.append({
                'threadId': thread_id,
                'nodeUid': comment_requests[index][0],
            })
    if new_comments:
        pending['comments'] = new_comments
    return pending


class MindmapAiMutationGateway:
    """Agent 直写的最小领域 API，所有写入经过既有服务的权限和 CAS。"""

    @staticmethod
    async def read_document(db: AsyncSession, mindmap_id: int, user_id: int) -> Any:
        return await MindmapService.get_mindmap_detail_services(db, mindmap_id, user_id)

    @staticmethod
    async def apply_draft_operations(  # noqa: PLR0912, PLR0915
        db: AsyncSession,
        mindmap_id: int,
        operations: list[dict[str, Any]],
        user_id: int,
        *,
        mutation_id: str,
        scope: dict[str, Any] | None = None,
        user_name: str | None = None,
        expected_revision: int | None = None,
        commit: bool = True,
        broadcast: bool = True,
    ) -> dict[str, Any]:
        """将隔离 DraftOperation 增量转换成领域操作并提交。

        这里故意不接受 Agent 传来的整树作为权威正文：每次提交都会先
        读取当前云端树，在当前树上重放受控增量，再交给现有 batch save
        做 CAS、并发分析、结构化持久化和广播。这样页面关闭或协作者
        同时编辑时，任务仍然有一个独立且可审计的执行上下文。

        ``commit`` controls the enclosing transaction.  When false, both the
        document and comment writes remain staged for the caller to commit
        together with task events/checkpoints; broadcasts are likewise
        deferred until ``publish_direct_commit`` is called after commit.
        """
        if not commit and broadcast:
            raise ServiceException(message='延迟提交时必须同时关闭脑图广播')
        if not operations:
            return {
                'contentRevision': None,
                'changedNodes': [],
                'idempotentReplay': False,
                'operationCount': 0,
                'changeSummary': empty_change_summary(),
            }
        if not mutation_id or len(mutation_id) > MAX_MUTATION_ID_LENGTH:
            raise ServiceException(message='AI 直写幂等标识无效')
        if expected_revision is not None and (
            isinstance(expected_revision, bool) or int(expected_revision) < 1
        ):
            raise ServiceException(message='AI 直写基线版本无效')

        detail = await MindmapService.get_mindmap_detail_services(db, mindmap_id, user_id)
        if getattr(detail, 'content_state', 'ready') != 'ready':
            raise ServiceException(message='脑图权威正文不可用，不能执行 AI 直写')
        # MindmapService exposes ``node_tree`` as the root node, while the AI
        # document contract wraps it in an SMM-v2 envelope.  Keep the gateway
        # envelope internally (for scope checks and hashing), but pass only its
        # root to the content batch API, whose schema is root-tree based.
        tree = _document_from_detail(detail)
        before_document = deepcopy(tree)
        authorized_uids = _scope_uids(tree, scope)
        root_uid = str((tree.get('root', {}).get('data') or {}).get('uid') or '')
        touched_uids: dict[str, None] = {}  # Ordered identities, not intermediate snapshots.
        comment_requests: list[tuple[str, str]] = []
        structural_parents: set[str] = set()
        deleted_in_batch: set[str] = set()
        tag_definitions: dict[int, dict[str, Any]] = {}
        owner_id = getattr(detail, 'owner_id', None)

        for raw in operations:
            if not isinstance(raw, dict):
                raise ServiceException(message='AI 直写操作格式无效')
            op_type = str(raw.get('type') or '')
            node_uid = str(raw.get('nodeUid', raw.get('node_uid', '')) or '')
            payload = raw.get('payload') if isinstance(raw.get('payload'), dict) else {}
            nodes, parents = _tree_index(tree)

            if op_type == 'create_node':
                parent_uid = str(payload.get('parentUid') or '')
                data = deepcopy(payload.get('data'))
                if not node_uid or not parent_uid or not isinstance(data, dict):
                    raise ServiceException(message='AI 新增节点操作缺少必要数据')
                if parent_uid not in authorized_uids or parent_uid not in nodes:
                    raise ServiceException(message='AI 新增节点超出授权范围')
                if str(data.get('uid') or '') != node_uid or node_uid in nodes:
                    raise ServiceException(message='AI 新增节点 UID 无效')
                # A stable UID cannot describe both a deleted identity and a
                # replacement in one batch; the net projector would conflate
                # them. Require update/move, or a genuinely new UID instead.
                if node_uid in deleted_in_batch:
                    raise ServiceException(message='AI 新增节点不能复用本批已删除的 UID')
                if 'tag' in data:
                    tags = await _resolve_existing_tags(
                        db, data['tag'], user_id=user_id, owner_id=owner_id,
                        previous_tags=[], cache=tag_definitions,
                    )
                    if tags:
                        data['tag'] = tags
                    else:
                        data.pop('tag', None)
                parent = nodes[parent_uid]
                node = {'data': data, 'children': []}
                raw_index = payload.get('index')
                index = len(parent.get('children') or []) if raw_index is None else int(raw_index)
                if index < 0 or index > len(parent.get('children') or []):
                    raise ServiceException(message='AI 新增节点位置无效')
                parent.setdefault('children', []).insert(index, node)
                structural_parents.add(parent_uid)
                authorized_uids.add(node_uid)
                touched_uids[node_uid] = None
                continue

            if op_type == 'update_node':
                if node_uid not in authorized_uids or node_uid not in nodes:
                    raise ServiceException(message='AI 更新节点超出授权范围')
                node = nodes[node_uid]
                patch = deepcopy(payload.get('set')) if isinstance(payload.get('set'), dict) else {}
                unset = payload.get('unset') if isinstance(payload.get('unset'), list) else []
                allowed = {'text', 'note', 'hyperlink', 'tag', 'richText', 'expand'}
                if set(patch) - allowed or any(str(key) not in allowed for key in unset):
                    raise ServiceException(message='AI 更新节点包含不允许的字段')
                if 'tag' in patch:
                    patch['tag'] = await _resolve_existing_tags(
                        db, patch['tag'], user_id=user_id, owner_id=owner_id,
                        previous_tags=node.get('data', {}).get('tag') or [], cache=tag_definitions,
                    )
                for key, value in patch.items():
                    node.setdefault('data', {})[key] = deepcopy(value)
                for key in unset:
                    node.setdefault('data', {}).pop(str(key), None)
                if not node.get('data', {}).get('tag'):
                    node.get('data', {}).pop('tag', None)
                touched_uids[node_uid] = None
                continue

            if op_type == 'move_node':
                parent_uid = str(payload.get('parentUid') or '')
                if (
                    node_uid not in authorized_uids
                    or parent_uid not in authorized_uids
                    or node_uid not in nodes
                    or parent_uid not in nodes
                    or node_uid == root_uid
                ):
                    raise ServiceException(message='AI 移动节点超出授权范围')
                old_parent_uid = parents.get(node_uid)
                if not old_parent_uid or old_parent_uid not in nodes:
                    raise ServiceException(message='AI 移动节点原父节点不存在')
                ancestor = parent_uid
                while ancestor is not None:
                    if ancestor == node_uid:
                        raise ServiceException(message='AI 移动节点不能形成循环')
                    ancestor = parents.get(ancestor)
                old_parent = nodes[old_parent_uid]
                new_parent = nodes[parent_uid]
                moving = next(
                    (child for child in old_parent.get('children') or []
                     if str((child.get('data') or {}).get('uid')) == node_uid),
                    None,
                )
                if moving is None:
                    raise ServiceException(message='AI 移动节点不存在')
                old_parent['children'] = [child for child in old_parent.get('children') or [] if child is not moving]
                raw_index = payload.get('index')
                index = len(new_parent.get('children') or []) if raw_index is None else int(raw_index)
                if index < 0 or index > len(new_parent.get('children') or []):
                    raise ServiceException(message='AI 移动节点位置无效')
                new_parent.setdefault('children', []).insert(index, moving)
                structural_parents.update({old_parent_uid, parent_uid})
                continue

            if op_type == 'delete_subtree':
                # MindmapToolService can emit one delete operation for every
                # selected UID, including descendants of a selected parent.
                # Once the ancestor has been removed from this replay tree,
                # the descendant operation is already satisfied and must not
                # turn an otherwise valid batch into a false failure.
                if node_uid in deleted_in_batch:
                    continue
                scope_type = str((scope or {}).get('type') or 'document')
                scope_roots = {
                    str((scope or {}).get('rootUid') or '')
                } if scope_type == 'branch' else {
                    str(uid) for uid in (scope or {}).get('nodeUids') or []
                }
                if (
                    node_uid not in authorized_uids
                    or node_uid not in nodes
                    or node_uid == root_uid
                    or (scope_type != 'document' and node_uid in scope_roots)
                ):
                    raise ServiceException(message='AI 删除节点超出授权范围')
                parent_uid = parents.get(node_uid)
                if not parent_uid or parent_uid not in nodes:
                    raise ServiceException(message='AI 删除节点父节点不存在')
                node = nodes[node_uid]
                deleted_uids = _subtree_uids(node)
                parent = nodes[parent_uid]
                parent['children'] = [
                    child for child in parent.get('children') or [] if child is not node
                ]
                structural_parents.add(parent_uid)
                deleted_in_batch.update(deleted_uids)
                authorized_uids.difference_update(deleted_uids)
                continue

            if op_type == 'set_document_meta':
                if str((scope or {}).get('type') or 'document') != 'document':
                    raise ServiceException(message='局部授权范围不能修改脑图元数据')
                values = payload.get('set') if isinstance(payload.get('set'), dict) else {}
                if 'layout' in values:
                    tree['layout'] = deepcopy(values['layout'])
                continue

            if op_type == 'add_comment':
                if node_uid not in authorized_uids or node_uid not in nodes:
                    raise ServiceException(message='AI 评论节点超出授权范围')
                content = payload.get('content')
                if (
                    not isinstance(content, str)
                    or not content.strip()
                    or len(content) > MAX_COMMENT_CONTENT_LENGTH
                ):
                    raise ServiceException(message='AI 评论内容无效')
                comment_requests.append((node_uid, content.strip()))
                continue

            if op_type in {'node.tag.bind', 'node.tag.unbind', 'node.tag.reorder'}:
                # Tag operations are already canonical when produced by a future
                # direct tool. Keep this branch strict rather than accepting an
                # arbitrary tree patch from the model.
                if node_uid not in authorized_uids or node_uid not in nodes:
                    raise ServiceException(message='AI 标签操作超出授权范围')
                if op_type == 'node.tag.bind':
                    resolved_tag = (await _resolve_existing_tags(
                        db, [payload.get('tag')], user_id=user_id, owner_id=owner_id,
                        previous_tags=(nodes[node_uid].get('data') or {}).get('tag') or [],
                        cache=tag_definitions,
                    ))[0]
                    payload = {**payload, 'tag': resolved_tag}
                elif op_type == 'node.tag.reorder':
                    tag_keys = payload.get('tagKeys', payload.get('tag_keys'))
                    if not isinstance(tag_keys, list):
                        raise ServiceException(message='AI 标签排序参数无效')
                    current_tags = (nodes[node_uid].get('data') or {}).get('tag') or []
                    current_keys = {
                        str(tag.get('tagId')) for tag in current_tags
                        if isinstance(tag, dict) and tag.get('tagId') is not None
                    }
                    if {str(key) for key in tag_keys} != current_keys:
                        raise ServiceException(message='AI 标签排序范围与当前节点不一致')
                # Reuse the domain's pure tag projection so same-value tags
                # and later restorations are accounted for like node data.
                try:
                    tree['root'] = _apply_node_tag_operations(tree['root'], tree['root'], [{
                        'type': op_type, 'nodeUid': node_uid, 'payload': deepcopy(payload),
                    }])
                except ValueError as exc:
                    raise ServiceException(message=str(exc)) from exc
                if op_type == 'node.tag.bind':
                    tag_data = _find_node(tree, node_uid)['data']
                    tag_data['tag'] = [
                        deepcopy(resolved_tag) if tag.get('tagId') == resolved_tag['tagId'] else tag
                        for tag in tag_data.get('tag') or []
                    ]
                continue

            raise ServiceException(message=f'AI 直写不支持操作: {op_type or "unknown"}')

        canonical = _effective_canonical_operations(before_document, tree, touched_uids, structural_parents)
        change_summary = summarize_committed_node_changes([[
            operation.model_dump(by_alias=True, exclude_none=True)
            for operation in canonical
        ]])
        if not canonical and not comment_requests:
            normalized, _summary = normalize_ai_editable_source_document(before_document)
            return {
                'contentRevision': int(detail.content_revision or 1),
                'changedNodes': [],
                'idempotentReplay': False,
                'operationCount': 0,
                'changeSummary': change_summary,
                'documentHash': compute_document_hash(normalized),
                '_committedDocument': before_document,
            }
        if canonical:
            batch = MindmapContentBatchModel(
                base_revision=int(
                    expected_revision
                    if expected_revision is not None
                    else detail.content_revision or 1
                ),
                client_mutation_id=mutation_id,
                operations=canonical,
                node_tree=tree['root'],
                layout=tree.get('layout'),
                theme=tree.get('theme'),
                document_data=tree.get('documentData'),
            )
            # Keep the document mutation open until comments (if any) and
            # the caller's audit/checkpoint rows are staged. Committing in
            # the lower-level service first would leave a partially
            # durable direct-write operation if a later step failed.
            result = await MindmapService.update_content_batch_services(
                db,
                mindmap_id,
                batch,
                user_id,
                user_name,
                commit=False,
                broadcast=False,
            )
        else:
            result = {
                'contentRevision': int(detail.content_revision or 1),
                'changedNodes': [],
                'idempotentReplay': False,
            }
        comments: list[dict[str, Any]] = []
        for index, (node_uid, content) in enumerate(comment_requests):
            comments.append(await MindmapCommentService.create_thread(
                db,
                MindmapCommentCreateModel(
                    mindmap_id=mindmap_id,
                    node_uid=node_uid,
                    content=content,
                ),
                user_id,
                f'{mutation_id}:comment:{index}',
                commit=False,
                broadcast=False,
            ))
        # The content service also gives its result dict to the pending change
        # log ORM row. Internal streaming snapshots must not leak into that
        # durable response or an idempotent replay of the public batch API.
        result = dict(result)
        result['operationCount'] = len(canonical)
        result['operationGroupId'] = mutation_id
        result['changeSummary'] = (
            empty_change_summary() if result.get('idempotentReplay') else change_summary
        )
        # A replayed/materialized candidate is not the persisted document:
        # structured storage resolves tag definitions, defaults and dedupes.
        # Read within the same transaction (the batch still holds its document
        # lock) so receipts and streaming checkpoints share the real result.
        persisted_detail = await MindmapService.get_mindmap_detail_services(db, mindmap_id, user_id)
        if getattr(persisted_detail, 'content_state', 'ready') != 'ready':
            raise ServiceException(message='AI 直写后无法校验云端正文，请重试')
        persisted_document = _document_from_detail(persisted_detail)
        result['_committedDocument'] = deepcopy(persisted_document)
        if 'nodeTree' in result:
            result['nodeTree'] = deepcopy(persisted_document['root'])
        # Job baselines are frozen through the editable-source normalizer
        # (which removes view state and gives blank editor nodes a stable
        # placeholder).  Apply the same normalization here; hashing the raw
        # editor tree would make a direct undo fail whenever the map has a
        # viewport payload or an intentionally blank node.
        normalized_persisted_document, _summary = normalize_ai_editable_source_document(
            persisted_document,
        )
        result['documentHash'] = compute_document_hash(normalized_persisted_document)
        result['affectedUids'] = sorted({
            str(operation.node_uid)
            for operation in canonical
            if operation.node_uid
        })
        if comments:
            result['comments'] = comments
            result['commentCount'] = len(comments)
        result['_deferredBroadcast'] = _build_deferred_broadcast(
            mindmap_id,
            result,
            canonical=bool(canonical),
            comment_requests=comment_requests,
            comments=comments,
        )
        if commit:
            await db.commit()
            if broadcast:
                await MindmapAiMutationGateway.publish_direct_commit(
                    mindmap_id,
                    result,
                )
        return result

    @staticmethod
    async def publish_direct_commit(
        mindmap_id: int,
        result: dict[str, Any] | None,
    ) -> None:
        """Publish a mutation only after its enclosing transaction commits.

        Direct AI writes are normally called from ``MindmapAiTaskManager._emit``.
        That method stages the map mutation, draft checkpoint and task event in
        one transaction, then invokes this helper after ``db.commit()``.  The
        helper is also used by standalone gateway callers when ``commit=True``.
        Broadcast failures are intentionally non-fatal: durable state has
        already been committed and clients can recover through their normal
        document reload path.
        """
        pending = result.get('_deferredBroadcast') if isinstance(result, dict) else None
        if not isinstance(pending, dict):
            return
        content = pending.get('content')
        if isinstance(content, dict):
            try:
                from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

                await room_manager.broadcast(mindmap_id, content)
            except Exception as exc:
                logger.warning(
                    '广播 AI 直写脑图 revision 变更失败: '
                    f'mindmap_id={mindmap_id}, error={exc}',
                )
        comments = pending.get('comments')
        if isinstance(comments, list):
            for item in comments:
                if not isinstance(item, dict):
                    continue
                thread_id = item.get('threadId')
                node_uid = item.get('nodeUid')
                if thread_id is None or not node_uid:
                    continue
                try:
                    await MindmapCommentService._broadcast_change(
                        mindmap_id,
                        'created',
                        int(thread_id),
                        str(node_uid),
                    )
                except Exception as exc:
                    logger.warning(
                        '广播 AI 直写评论变更失败: '
                        f'mindmap_id={mindmap_id}, thread_id={thread_id}, error={exc}',
                    )


__all__ = [
    'MindmapAiMutationGateway',
    'empty_change_summary',
]
