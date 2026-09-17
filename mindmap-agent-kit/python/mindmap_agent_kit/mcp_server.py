"""Dependency-free local stdio MCP server for isolated mind-map drafts."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, TextIO

from mindmap_agent_kit.artifact import ArtifactValidationError
from mindmap_agent_kit.builder import MindmapBuilder

PROTOCOL_VERSION = '2025-06-18'


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


STRING = {'type': 'string', 'minLength': 1}
NODE_PATCH_PROPERTIES = {
    'text': STRING,
    'note': {'type': 'string'},
    'hyperlink': {'type': 'string'},
    'tag': {'type': 'array'},
}
NODE_INPUT = {
    'type': 'object',
    'properties': {
        'parentUid': STRING,
        'clientRef': {'type': 'string'},
        **NODE_PATCH_PROPERTIES,
    },
    'required': ['parentUid', 'text'],
    'additionalProperties': False,
}
NODE_PATCH_INPUT = {
    'type': 'object',
    'properties': NODE_PATCH_PROPERTIES,
    'minProperties': 1,
    'additionalProperties': False,
}
UPDATE_INPUT = {
    'type': 'object',
    'properties': {'nodeUid': STRING, 'patch': NODE_PATCH_INPUT},
    'required': ['nodeUid', 'patch'],
    'additionalProperties': False,
}
MOVE_INPUT = {
    'type': 'object',
    'properties': {
        'nodeUid': STRING,
        'parentUid': STRING,
        'index': {'type': 'integer', 'minimum': 0},
    },
    'required': ['nodeUid', 'parentUid'],
    'additionalProperties': False,
}

TOOLS = [
    {
        'name': 'mindmap.start_document',
        'description': 'Create an isolated candidate document.',
        'inputSchema': _schema(
            {
                'title': STRING,
                'layout': {'type': 'string'},
            },
            ['title'],
        ),
    },
    {
        'name': 'mindmap.read_projection',
        'description': 'Read the current safe draft projection.',
        'inputSchema': _schema({'draftId': STRING}, ['draftId']),
    },
    {
        'name': 'mindmap.add_nodes',
        'description': 'Add up to 200 candidate nodes.',
        'inputSchema': _schema(
            {
                'draftId': STRING,
                'nodes': {'type': 'array', 'items': NODE_INPUT, 'minItems': 1, 'maxItems': 200},
            },
            ['draftId', 'nodes'],
        ),
    },
    {
        'name': 'mindmap.update_nodes',
        'description': 'Update allowed fields on up to 200 nodes.',
        'inputSchema': _schema(
            {
                'draftId': STRING,
                'updates': {
                    'type': 'array',
                    'items': UPDATE_INPUT,
                    'minItems': 1,
                    'maxItems': 200,
                },
            },
            ['draftId', 'updates'],
        ),
    },
    {
        'name': 'mindmap.move_nodes',
        'description': 'Move nodes inside the isolated draft.',
        'inputSchema': _schema(
            {
                'draftId': STRING,
                'moves': {
                    'type': 'array',
                    'items': MOVE_INPUT,
                    'minItems': 1,
                    'maxItems': 200,
                },
            },
            ['draftId', 'moves'],
        ),
    },
    {
        'name': 'mindmap.remove_nodes',
        'description': 'Remove candidate nodes or subtrees.',
        'inputSchema': _schema(
            {
                'draftId': STRING,
                'nodeUids': {'type': 'array', 'items': STRING, 'minItems': 1, 'maxItems': 200},
            },
            ['draftId', 'nodeUids'],
        ),
    },
    {
        'name': 'mindmap.set_document_meta',
        'description': 'Set the candidate title or layout.',
        'inputSchema': _schema(
            {
                'draftId': STRING,
                'title': STRING,
                'layout': {'type': 'string'},
            },
            ['draftId'],
        ),
    },
    {
        'name': 'mindmap.validate_draft',
        'description': 'Validate structure and limits without freezing.',
        'inputSchema': _schema({'draftId': STRING}, ['draftId']),
    },
    {
        'name': 'mindmap.complete_artifact',
        'description': 'Freeze the draft as an external/unverified SMM v2 artifact.',
        'inputSchema': _schema(
            {
                'draftId': STRING,
                'title': STRING,
                'agentKey': STRING,
                'adapterVersion': STRING,
                'promptVersion': STRING,
                'artifactId': {'type': 'string'},
                'validationStatus': {'enum': ['passed', 'draft']},
            },
            ['draftId', 'title', 'agentKey', 'adapterVersion', 'promptVersion'],
        ),
    },
]


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    """Validate the dependency-free JSON Schema subset used by this server."""
    if 'enum' in schema and value not in schema['enum']:
        raise ArtifactValidationError(f'{path} must be one of {schema["enum"]}')
    schema_type = schema.get('type')
    if schema_type == 'object':
        if not isinstance(value, dict):
            raise ArtifactValidationError(f'{path} must be an object')
        properties = schema.get('properties', {})
        missing = set(schema.get('required', ())) - set(value)
        unknown = set(value) - set(properties)
        if missing:
            raise ArtifactValidationError(f'{path} is missing required field: {sorted(missing)[0]}')
        if schema.get('additionalProperties') is False and unknown:
            raise ArtifactValidationError(f'{path} contains unknown field: {sorted(unknown)[0]}')
        if len(value) < schema.get('minProperties', 0):
            raise ArtifactValidationError(f'{path} must not be empty')
        for key, item in value.items():
            if key in properties:
                _validate_schema(item, properties[key], f'{path}.{key}')
        return
    if schema_type == 'array':
        if not isinstance(value, list):
            raise ArtifactValidationError(f'{path} must be an array')
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', len(value)):
            raise ArtifactValidationError(f'{path} has an invalid item count')
        item_schema = schema.get('items')
        if item_schema:
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, f'{path}[{index}]')
        return
    if schema_type == 'string':
        if not isinstance(value, str) or len(value) < schema.get('minLength', 0):
            raise ArtifactValidationError(f'{path} must be a valid string')
        return
    if schema_type == 'integer' and (
        type(value) is not int or value < schema.get('minimum', value)
    ):
        raise ArtifactValidationError(f'{path} must be a valid integer')


class MindmapMcpServer:
    def __init__(self) -> None:
        self._drafts: dict[str, MindmapBuilder] = {}

    def _draft(self, arguments: dict[str, Any]) -> MindmapBuilder:
        draft_id = str(arguments.pop('draftId', ''))
        if draft_id not in self._drafts:
            raise ArtifactValidationError('draft does not exist in this MCP process')
        return self._drafts[draft_id]

    def call_tool(self, name: str, raw_arguments: Any) -> dict[str, Any]:
        descriptor = next((item for item in TOOLS if item['name'] == name), None)
        if descriptor is None:
            raise ArtifactValidationError(f'unknown tool: {name}')
        _validate_schema(raw_arguments, descriptor['inputSchema'], name)
        arguments = dict(raw_arguments)
        if name == 'mindmap.start_document':
            builder = MindmapBuilder(
                arguments['title'],
                arguments.get('layout', 'logicalStructure'),
            )
            draft_id = str(uuid.uuid4())
            self._drafts[draft_id] = builder
            return {'draftId': draft_id, 'rootUid': builder.root_uid}
        draft = self._draft(arguments)
        if name == 'mindmap.read_projection':
            return {'document': draft.read_projection()}
        if name == 'mindmap.add_nodes':
            return draft.add_nodes(arguments['nodes'])
        if name == 'mindmap.update_nodes':
            return draft.update_nodes(arguments['updates'])
        if name == 'mindmap.move_nodes':
            return draft.move_nodes(arguments['moves'])
        if name == 'mindmap.remove_nodes':
            return draft.remove_nodes(arguments['nodeUids'])
        if name == 'mindmap.set_document_meta':
            return draft.set_document_meta(title=arguments.get('title'), layout=arguments.get('layout'))
        if name == 'mindmap.validate_draft':
            return draft.validate_draft()
        if name == 'mindmap.complete_artifact':
            result = draft.complete_artifact(
                title=arguments['title'],
                agent_key=arguments['agentKey'],
                adapter_version=arguments['adapterVersion'],
                prompt_version=arguments['promptVersion'],
                artifact_id=arguments.get('artifactId'),
                validation_status=arguments.get('validationStatus', 'passed'),
            )
            return result
        raise ArtifactValidationError(f'unsupported tool: {name}')

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get('id')
        method = request.get('method')
        if request_id is None and method and str(method).startswith('notifications/'):
            return None
        try:
            if method == 'initialize':
                requested = (request.get('params') or {}).get('protocolVersion')
                result = {
                    'protocolVersion': requested or PROTOCOL_VERSION,
                    'capabilities': {'tools': {'listChanged': False}},
                    'serverInfo': {'name': 'ruoyi-mindmap-agent-kit', 'version': '1.1.0'},
                    'instructions': 'All tools modify only an in-memory draft. No platform or user file is written.',
                }
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                params = request.get('params') or {}
                if not isinstance(params, dict):
                    raise ArtifactValidationError('tools/call params must be an object')
                structured = self.call_tool(
                    str(params.get('name') or ''),
                    params.get('arguments', {}),
                )
                result = {
                    'content': [{'type': 'text', 'text': json.dumps(structured, ensure_ascii=False)}],
                    'structuredContent': structured,
                    'isError': False,
                }
            else:
                return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'Method not found'}}
            return {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except (ArtifactValidationError, KeyError, TypeError, ValueError) as exc:
            if method == 'tools/call':
                result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
                return {'jsonrpc': '2.0', 'id': request_id, 'result': result}
            return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32602, 'message': str(exc)}}


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    server = MindmapMcpServer()
    for line in stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('JSON-RPC message must be an object')
            response = server.handle(request)
        except (json.JSONDecodeError, ValueError) as exc:
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(exc)}}
        if response is not None:
            stdout.write(f'{json.dumps(response, ensure_ascii=False, separators=(",", ":"))}\n')
            stdout.flush()
    return 0


def main() -> int:
    return serve()


if __name__ == '__main__':
    raise SystemExit(main())
