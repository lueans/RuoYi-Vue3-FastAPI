"""Contract tests for the Codex MCP bridge tool registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from module_mindmap.ai.adapters import codex_mcp_bridge, codex_worker
from module_mindmap.ai.tool_contract import SEARCH_TAGS_SCHEMA, TAG_REFERENCE_SCHEMA, TAG_SUGGESTIONS_SCHEMA

EXPECTED_NODE_TAG_LIMIT = 50
EXPECTED_COMMENT_LENGTH_LIMIT = 5000


def test_standalone_bridge_tag_schemas_match_domain_contract() -> None:
    # The subprocess bridge intentionally cannot import application runtime modules.
    descriptors = codex_mcp_bridge.TOOL_DESCRIPTORS
    assert codex_mcp_bridge.TAG_REFERENCE_SCHEMA == TAG_REFERENCE_SCHEMA
    assert codex_mcp_bridge.TAG_SUGGESTIONS_SCHEMA == TAG_SUGGESTIONS_SCHEMA
    assert descriptors['edit_node_tags']['inputSchema']['properties']['tags'] == TAG_REFERENCE_SCHEMA
    search_schema = descriptors['search_tags']['inputSchema']
    assert {key: value for key, value in search_schema.items() if key != 'required'} == SEARCH_TAGS_SCHEMA
    assert descriptors['suggest_tags']['inputSchema']['properties']['suggestions'] == TAG_SUGGESTIONS_SCHEMA


def test_worker_allowlist_has_a_bridge_descriptor_for_every_tool() -> None:
    missing = set(codex_worker.ALLOWED_TOOL_NAMES) - set(
        codex_mcp_bridge.TOOL_DESCRIPTORS,
    )

    assert not missing


def test_tools_list_accepts_the_worker_allowlist() -> None:
    proxy = codex_mcp_bridge.CodexMindmapMcpProxy(
        socket_path=Path('/tmp/mindmap-test.sock'),
        capability_token='a' * codex_mcp_bridge.MIN_CAPABILITY_TOKEN_LENGTH,
        allowed_tools=codex_worker.ALLOWED_TOOL_NAMES,
    )

    response = proxy.handle({
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'tools/list',
        'params': {},
    })

    assert response is not None
    listed = response['result']['tools']
    assert tuple(item['name'] for item in listed) == codex_worker.ALLOWED_TOOL_NAMES


def test_new_direct_edit_tool_schemas_are_strict_and_bounded() -> None:
    descriptors: dict[str, dict[str, Any]] = codex_mcp_bridge.TOOL_DESCRIPTORS

    assert descriptors['read_document_detail']['inputSchema'] == {
        'type': 'object',
        'properties': {},
        'required': [],
        'additionalProperties': False,
    }
    assert descriptors['get_node_tags']['inputSchema']['required'] == []

    edit_text = descriptors['edit_node_text']['inputSchema']
    assert edit_text['required'] == ['nodeUid', 'text']
    assert edit_text['additionalProperties'] is False

    edit_tags = descriptors['edit_node_tags']['inputSchema']
    assert edit_tags['required'] == ['nodeUid', 'tags']
    assert edit_tags['properties']['tags']['maxItems'] == EXPECTED_NODE_TAG_LIMIT
    assert edit_tags['additionalProperties'] is False

    add_comment = descriptors['add_comment']['inputSchema']
    assert add_comment['required'] == ['nodeUid', 'content']
    assert add_comment['properties']['content']['maxLength'] == EXPECTED_COMMENT_LENGTH_LIMIT
    assert add_comment['additionalProperties'] is False


def test_direct_bridge_instructions_do_not_require_preview_completion_tool() -> None:
    direct_tools = tuple(
        name for name in codex_worker.ALLOWED_TOOL_NAMES
        if name != 'complete_artifact'
    )
    proxy = codex_mcp_bridge.CodexMindmapMcpProxy(
        socket_path=Path('/tmp/mindmap-direct-test.sock'),
        capability_token='a' * codex_mcp_bridge.MIN_CAPABILITY_TOKEN_LENGTH,
        allowed_tools=direct_tools,
    )

    response = proxy.handle({
        'jsonrpc': '2.0',
        'id': 2,
        'method': 'initialize',
        'params': {},
    })

    assert response is not None
    instructions = response['result']['instructions']
    assert 'validate_draft' in instructions
    assert 'do not call complete_artifact' in instructions


def test_direct_worker_request_requires_validate_draft_as_last_tool() -> None:
    request = {
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
        'operation': 'generate',
        'model': 'gpt-5.6-terra',
        'prompt': '受控提示',
        'sourceProjection': None,
        'externalSessionId': None,
        'maxBudgetUsd': 1.0,
        'bridgeSocket': '/private/tmp/mindmap.sock',
        'bridgeTokenFile': '/private/tmp/mindmap-token',
        'executionMode': 'direct',
        'allowedTools': [
            'read_projection',
            'validate_draft',
        ],
    }
    assert codex_worker._validated_request(request)['executionMode'] == 'direct'

    for invalid_tools in (
        ['read_projection', 'complete_artifact', 'validate_draft'],
        ['read_projection', 'validate_draft', 'read_document_detail'],
    ):
        with pytest.raises(codex_worker.WorkerFailure) as error:
            codex_worker._validated_request({
                **request,
                'allowedTools': invalid_tools,
            })
        assert error.value.code == 'AI_CAPABILITY_UNSUPPORTED'
