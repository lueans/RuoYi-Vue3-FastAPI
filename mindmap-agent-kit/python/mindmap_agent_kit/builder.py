"""In-memory document builder used by SDKs and the local MCP server."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from mindmap_agent_kit.artifact import ALLOWED_LAYOUTS, ArtifactValidationError, build_artifact

ALLOWED_PATCH_FIELDS = frozenset(
    {
        'text',
        'note',
        'hyperlink',
        'tag',
    }
)


class MindmapBuilder:
    """Mutable isolated draft. It never reads or writes platform/user storage."""

    def __init__(self, title: str, layout: str = 'logicalStructure') -> None:
        if layout not in ALLOWED_LAYOUTS:
            raise ArtifactValidationError('unsupported layout')
        root_uid = uuid.uuid4().hex
        self.document: dict[str, Any] = {
            'root': {'data': {'uid': root_uid, 'text': self._text(title), 'expand': True}, 'children': []},
            'layout': layout,
            'theme': {'template': 'default', 'config': {}},
            'view': None,
            'documentData': {},
        }
        self.operations: list[dict[str, Any]] = []
        self.completed = False

    @property
    def root_uid(self) -> str:
        return str(self.document['root']['data']['uid'])

    @staticmethod
    def _text(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ArtifactValidationError('node text must be a non-empty string')
        return value.strip()

    def _require_open(self) -> None:
        if self.completed:
            raise ArtifactValidationError('draft is already completed')

    @staticmethod
    def _record_batch(value: Any, operation: str) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not 1 <= len(value) <= 200:
            raise ArtifactValidationError(f'{operation} accepts 1 to 200 items')
        if any(not isinstance(item, dict) for item in value):
            raise ArtifactValidationError(f'{operation} items must be objects')
        return value

    def _index(
        self,
        document: dict[str, Any] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str | None]]:
        nodes: dict[str, dict[str, Any]] = {}
        parents: dict[str, str | None] = {}
        source = self.document if document is None else document
        pending = [(source['root'], None)]
        while pending:
            node, parent_uid = pending.pop()
            uid = str(node['data']['uid'])
            nodes[uid] = node
            parents[uid] = parent_uid
            pending.extend((child, uid) for child in reversed(node.get('children') or []))
        return nodes, parents

    def read_projection(self) -> dict[str, Any]:
        return copy.deepcopy(self.document)

    def add_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        self._require_open()
        nodes = self._record_batch(nodes, 'add_nodes')
        candidate = copy.deepcopy(self.document)
        indexed, _parents = self._index(candidate)
        created: list[dict[str, str]] = []
        operations: list[dict[str, Any]] = []
        for item in nodes:
            parent_uid = str(item.get('parentUid') or '')
            if parent_uid not in indexed:
                raise ArtifactValidationError(f'parent node does not exist: {parent_uid}')
            unknown = set(item) - ({'parentUid', 'clientRef'} | ALLOWED_PATCH_FIELDS)
            if unknown:
                raise ArtifactValidationError(f'add_nodes contains unknown field: {sorted(unknown)[0]}')
            uid = uuid.uuid4().hex
            data: dict[str, Any] = {'uid': uid, 'text': self._text(item.get('text')), 'expand': True}
            for key in ALLOWED_PATCH_FIELDS - {'text'}:
                if key in item:
                    data[key] = copy.deepcopy(item[key])
            node = {'data': data, 'children': []}
            indexed[parent_uid].setdefault('children', []).append(node)
            indexed[uid] = node
            created.append({'clientRef': str(item.get('clientRef') or ''), 'nodeUid': uid})
            operations.append({'type': 'create_node', 'nodeUid': uid, 'payload': {'parentUid': parent_uid}})
        self.document = candidate
        self.operations.extend(operations)
        return {'created': created}

    def update_nodes(self, updates: list[dict[str, Any]]) -> dict[str, int]:
        self._require_open()
        updates = self._record_batch(updates, 'update_nodes')
        candidate = copy.deepcopy(self.document)
        indexed, _parents = self._index(candidate)
        operations: list[dict[str, Any]] = []
        for item in updates:
            if set(item) != {'nodeUid', 'patch'}:
                raise ArtifactValidationError('update_nodes accepts only nodeUid and patch')
            uid = str(item['nodeUid'])
            patch = item['patch']
            if uid not in indexed or not isinstance(patch, dict) or not patch or set(patch) - ALLOWED_PATCH_FIELDS:
                raise ArtifactValidationError(f'invalid update for node: {uid}')
            if 'text' in patch:
                patch = {**patch, 'text': self._text(patch['text'])}
            indexed[uid]['data'].update(copy.deepcopy(patch))
            operations.append({'type': 'update_node', 'nodeUid': uid, 'payload': {'patch': copy.deepcopy(patch)}})
        self.document = candidate
        self.operations.extend(operations)
        return {'updated': len(updates)}

    def move_nodes(self, moves: list[dict[str, Any]]) -> dict[str, int]:
        self._require_open()
        moves = self._record_batch(moves, 'move_nodes')
        candidate = copy.deepcopy(self.document)
        operations: list[dict[str, Any]] = []
        for item in moves:
            if set(item) - {'nodeUid', 'parentUid', 'index'}:
                raise ArtifactValidationError('move_nodes contains an unknown field')
            indexed, parents = self._index(candidate)
            uid = str(item.get('nodeUid') or '')
            parent_uid = str(item.get('parentUid') or '')
            if uid not in indexed or parent_uid not in indexed or parents[uid] is None:
                raise ArtifactValidationError('move source/target is invalid and root cannot be moved')
            ancestor: str | None = parent_uid
            while ancestor is not None:
                if ancestor == uid:
                    raise ArtifactValidationError('move would create a cycle')
                ancestor = parents[ancestor]
            old_parent = indexed[str(parents[uid])]
            node = indexed[uid]
            old_parent['children'].remove(node)
            children = indexed[parent_uid].setdefault('children', [])
            index = len(children) if item.get('index') is None else int(item['index'])
            if not 0 <= index <= len(children):
                raise ArtifactValidationError('move index is out of range')
            children.insert(index, node)
            operations.append(
                {'type': 'move_node', 'nodeUid': uid, 'payload': {'parentUid': parent_uid, 'index': index}}
            )
        self.document = candidate
        self.operations.extend(operations)
        return {'moved': len(moves)}

    def remove_nodes(self, node_uids: list[str]) -> dict[str, int]:
        self._require_open()
        if not isinstance(node_uids, list) or not 1 <= len(node_uids) <= 200:
            raise ArtifactValidationError('remove_nodes accepts 1 to 200 nodes')
        if any(not isinstance(uid, str) or not uid for uid in node_uids):
            raise ArtifactValidationError('remove_nodes requires non-empty string node UIDs')
        candidate = copy.deepcopy(self.document)
        indexed, parents = self._index(candidate)
        requested = {str(uid) for uid in node_uids}
        if self.root_uid in requested or requested - set(indexed):
            raise ArtifactValidationError('remove_nodes contains root or an unknown node')
        for uid in requested:
            parent_uid = parents[uid]
            if parent_uid in requested:
                continue
            parent = indexed[str(parent_uid)]
            parent['children'] = [child for child in parent['children'] if child['data']['uid'] != uid]
        operations = [{'type': 'delete_subtree', 'nodeUid': uid, 'payload': None} for uid in sorted(requested)]
        self.document = candidate
        self.operations.extend(operations)
        return {'removed': len(requested)}

    def set_document_meta(self, *, title: str | None = None, layout: str | None = None) -> dict[str, Any]:
        self._require_open()
        candidate = copy.deepcopy(self.document)
        patch: dict[str, Any] = {}
        if title is not None:
            patch['title'] = self._text(title)
            candidate['root']['data']['text'] = patch['title']
        if layout is not None:
            if layout not in ALLOWED_LAYOUTS:
                raise ArtifactValidationError('unsupported layout')
            patch['layout'] = layout
            candidate['layout'] = layout
        self.document = candidate
        self.operations.append({'type': 'set_document_meta', 'nodeUid': None, 'payload': copy.deepcopy(patch)})
        return patch

    def validate_draft(self) -> dict[str, int]:
        self._require_open()
        from mindmap_agent_kit.artifact import _walk_document, canonical_json_bytes  # noqa: PLC0415

        node_count, tree_depth = _walk_document(self.document)
        return {'nodeCount': node_count, 'treeDepth': tree_depth, 'bytes': len(canonical_json_bytes(self.document))}

    def complete_artifact(
        self,
        *,
        title: str,
        agent_key: str,
        adapter_version: str,
        prompt_version: str,
        artifact_id: str | None = None,
        validation_status: str = 'passed',
    ) -> dict[str, Any]:
        self._require_open()
        artifact = build_artifact(
            copy.deepcopy(self.document),
            title=title,
            agent_key=agent_key,
            adapter_version=adapter_version,
            prompt_version=prompt_version,
            artifact_id=artifact_id,
            validation_status=validation_status,
        )
        self.completed = True
        return {
            'artifact': artifact,
            'summary': self.validate_completed(artifact),
            'operations': copy.deepcopy(self.operations),
        }

    @staticmethod
    def validate_completed(artifact: dict[str, Any]) -> dict[str, Any]:
        from mindmap_agent_kit.artifact import validate_artifact  # noqa: PLC0415

        return validate_artifact(artifact, require_passed=False)
