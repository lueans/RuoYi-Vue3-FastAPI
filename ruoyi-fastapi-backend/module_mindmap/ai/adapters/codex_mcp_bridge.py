"""Minimal stdio MCP proxy for Codex mind-map tools.

The process owns no draft state. Each tool call is forwarded over one private
Unix-domain socket to the parent adapter, where the real MindmapToolService is
executed. Stdout remains exclusively MCP JSON-RPC traffic.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import uuid
from pathlib import Path
from typing import Any, TextIO

PROTOCOL_VERSION = '2025-06-18'
BRIDGE_PROTOCOL_VERSION = 1
MAX_BRIDGE_MESSAGE_BYTES = 8 * 1024 * 1024
MIN_CAPABILITY_TOKEN_LENGTH = 32
MAX_CAPABILITY_TOKEN_LENGTH = 128
MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER = 'RUOYI_MINDMAP_BRIDGE_RUNTIME_UNAVAILABLE'
MODEL_TOOL_PROTOCOL_ERROR_MESSAGE = 'AI_OUTPUT_INVALID: mind-map tool request is invalid'


class ModelToolProtocolError(ValueError):
    """模型生成的工具请求超出 MCP 协议约束。"""


STRING = {'type': 'string', 'minLength': 1}
NODE_FIELDS = {
    'clientRef': {'type': 'string'},
    'parentUid': STRING,
    'text': STRING,
    'note': {'type': 'string'},
    'hyperlink': {'type': 'string'},
    'tag': {'type': 'array'},
}
PATCH_FIELDS = {
    key: value for key, value in NODE_FIELDS.items()
    if key not in {'clientRef', 'parentUid'}
}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        'type': 'object',
        'properties': properties,
        'required': required,
        'additionalProperties': False,
    }


TOOL_DESCRIPTORS = {
    'read_projection': {
        'description': 'Read the current authorized mind-map draft projection.',
        'inputSchema': _schema({}, []),
    },
    'start_document': {
        'description': 'Create the isolated candidate document exactly once.',
        'inputSchema': _schema({
            'title': STRING,
            'layout': {'type': 'string'},
        }, ['title']),
    },
    'add_nodes': {
        'description': 'Add one to 200 nodes to the isolated candidate.',
        'inputSchema': _schema({
            'nodes': {
                'type': 'array',
                'items': _schema(NODE_FIELDS, ['parentUid', 'text']),
                'minItems': 1,
                'maxItems': 200,
            },
        }, ['nodes']),
    },
    'update_nodes': {
        'description': 'Update allowed fields on one to 200 candidate nodes.',
        'inputSchema': _schema({
            'updates': {
                'type': 'array',
                'items': _schema({
                    'nodeUid': STRING,
                    'patch': {
                        **_schema(PATCH_FIELDS, []),
                        'minProperties': 1,
                    },
                }, ['nodeUid', 'patch']),
                'minItems': 1,
                'maxItems': 200,
            },
        }, ['updates']),
    },
    'move_nodes': {
        'description': 'Move one to 200 nodes inside the isolated candidate.',
        'inputSchema': _schema({
            'moves': {
                'type': 'array',
                'items': _schema({
                    'nodeUid': STRING,
                    'parentUid': STRING,
                    'index': {'type': 'integer', 'minimum': 0},
                }, ['nodeUid', 'parentUid']),
                'minItems': 1,
                'maxItems': 200,
            },
        }, ['moves']),
    },
    'remove_nodes': {
        'description': 'Remove one to 200 candidate nodes or subtrees.',
        'inputSchema': _schema({
            'nodeUids': {
                'type': 'array',
                'items': STRING,
                'minItems': 1,
                'maxItems': 200,
            },
        }, ['nodeUids']),
    },
    'set_document_meta': {
        'description': 'Set the candidate title or layout.',
        'inputSchema': {
            **_schema({
                'title': STRING,
                'layout': {'type': 'string'},
            }, []),
            'minProperties': 1,
        },
    },
    'validate_draft': {
        'description': 'Validate the current candidate without freezing it.',
        'inputSchema': _schema({}, []),
    },
    'complete_artifact': {
        'description': 'Validate and freeze the final artifact. This must be the last tool call.',
        'inputSchema': _schema({}, []),
    },
}


def _recv_line(connection: socket.socket) -> bytes:
    value = bytearray()
    while len(value) <= MAX_BRIDGE_MESSAGE_BYTES:
        chunk = connection.recv(min(64 * 1024, MAX_BRIDGE_MESSAGE_BYTES + 1 - len(value)))
        if not chunk:
            break
        newline = chunk.find(b'\n')
        if newline >= 0:
            value.extend(chunk[:newline])
            return bytes(value)
        value.extend(chunk)
    raise ValueError('mind-map bridge response is missing or too large')


def _call_parent(
    socket_path: Path,
    capability_token: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    request = {
        'protocolVersion': BRIDGE_PROTOCOL_VERSION,
        'requestId': str(uuid.uuid4()),
        'capabilityToken': capability_token,
        'toolName': tool_name,
        'arguments': arguments,
    }
    encoded = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) + 1 > MAX_BRIDGE_MESSAGE_BYTES:
        raise ModelToolProtocolError(MODEL_TOOL_PROTOCOL_ERROR_MESSAGE)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(120)
        connection.connect(str(socket_path))
        connection.sendall(encoded + b'\n')
        raw_response = _recv_line(connection)
    response = json.loads(raw_response.decode('utf-8'))
    if (
        not isinstance(response, dict)
        or response.get('protocolVersion') != BRIDGE_PROTOCOL_VERSION
        or response.get('requestId') != request['requestId']
        or type(response.get('ok')) is not bool
    ):
        raise ValueError('mind-map bridge returned an invalid response')
    return response


class CodexMindmapMcpProxy:
    def __init__(
        self,
        socket_path: Path,
        capability_token: str,
        allowed_tools: tuple[str, ...],
    ) -> None:
        self._socket_path = socket_path
        self._capability_token = capability_token
        self._allowed_tools = allowed_tools

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get('id')
        method = request.get('method')
        if request_id is None and method and str(method).startswith('notifications/'):
            return None
        if method == 'initialize':
            requested = (request.get('params') or {}).get('protocolVersion')
            result = {
                'protocolVersion': requested or PROTOCOL_VERSION,
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': 'ruoyi-codex-mindmap-bridge', 'version': '1.0.0'},
                'instructions': (
                    'Tools operate one isolated server-side draft. '
                    'Call complete_artifact explicitly and last.'
                ),
            }
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': [
                {'name': name, **TOOL_DESCRIPTORS[name]}
                for name in self._allowed_tools
            ]}
        elif method == 'tools/call':
            params = request.get('params') or {}
            tool_name = str(params.get('name') or '')
            arguments = params.get('arguments') or {}
            if tool_name not in self._allowed_tools or not isinstance(arguments, dict):
                bridge_response = {
                    'ok': False,
                    'error': {'message': MODEL_TOOL_PROTOCOL_ERROR_MESSAGE},
                }
            else:
                bridge_response = _call_parent(
                    self._socket_path,
                    self._capability_token,
                    tool_name,
                    arguments,
                )
            if bridge_response.get('ok') is True:
                structured = bridge_response.get('result')
                result = {
                    'content': [{
                        'type': 'text',
                        'text': json.dumps(structured, ensure_ascii=False, separators=(',', ':')),
                    }],
                    'structuredContent': structured,
                    'isError': False,
                }
            else:
                error = bridge_response.get('error')
                message = error.get('message') if isinstance(error, dict) else None
                result = {
                    'content': [{
                        'type': 'text',
                        'text': str(message or 'mind-map tool call failed'),
                    }],
                    'isError': True,
                }
        else:
            return {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {
                    'code': -32601,
                    'message': MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER,
                },
            }
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def serve(
    socket_path: Path,
    capability_token: str,
    allowed_tools: tuple[str, ...],
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
) -> int:
    proxy = CodexMindmapMcpProxy(socket_path, capability_token, allowed_tools)
    for line in stdin:
        if not line.strip():
            continue
        request_id: Any = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('JSON-RPC message must be an object')
            request_id = request.get('id')
            response = proxy.handle(request)
        except ModelToolProtocolError:
            response = {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {'code': -32602, 'message': MODEL_TOOL_PROTOCOL_ERROR_MESSAGE},
            }
        except (
            AttributeError,
            KeyError,
            OSError,
            OverflowError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            response = {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {
                    'code': -32603,
                    'message': MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER,
                },
            }
        if response is not None:
            stdout.write(f'{json.dumps(response, ensure_ascii=False, separators=(",", ":"))}\n')
            stdout.flush()
    return 0


def _consume_capability_token(token_file: Path) -> str:
    descriptor = -1
    try:
        descriptor = os.open(
            token_file,
            os.O_RDONLY
            | getattr(os, 'O_CLOEXEC', 0)
            | getattr(os, 'O_NOFOLLOW', 0),
        )
        file_status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_status.st_mode)
            or file_status.st_mode & 0o077
        ):
            raise ValueError('invalid mind-map capability file')
        raw_token = os.read(descriptor, MAX_CAPABILITY_TOKEN_LENGTH + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            token_file.unlink()
        except OSError:
            pass
    try:
        token = raw_token.decode('ascii')
    except (UnicodeDecodeError, UnboundLocalError) as exc:
        raise ValueError('invalid mind-map capability file') from exc
    if not MIN_CAPABILITY_TOKEN_LENGTH <= len(token) <= MAX_CAPABILITY_TOKEN_LENGTH:
        raise ValueError('invalid mind-map capability file')
    return token


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--tools', required=True)
    options = parser.parse_args()
    requested_tools = tuple(item for item in options.tools.split(',') if item)
    if not requested_tools or any(name not in TOOL_DESCRIPTORS for name in requested_tools):
        return 2
    try:
        capability_token = _consume_capability_token(Path(options.token_file))
    except (OSError, ValueError):
        return 2
    return serve(Path(options.socket), capability_token, requested_tools)


if __name__ == '__main__':
    raise SystemExit(main())
