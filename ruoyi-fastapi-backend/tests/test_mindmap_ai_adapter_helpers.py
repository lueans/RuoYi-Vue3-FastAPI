"""Provider-neutral helper contracts shared by real adapter tool paths."""

from typing import Any
from unittest.mock import Mock

import pytest

from module_mindmap.ai.adapters.base import (
    AgentRunContext,
    build_agent_draft_changed_payload,
    build_agent_structure_budget_clause,
    build_agent_tool_completed_payload,
)
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.tool_contract import MindmapToolService


@pytest.mark.parametrize(('tool_name', 'mutates', 'before', 'after', 'changed'), [
    ('start_document', True, 0, 0, True),
    ('start_document', False, 0, 0, False),
    ('add_nodes', True, 0, 1, True),
    ('update_nodes', True, 1, 1, False),
    ('update_nodes', True, 1, 0, False),
    ('complete_artifact', True, 1, 1, False),
    ('read_projection', False, 0, 1, False),
    ('search_tags', False, 0, 1, False),
    ('suggest_tags', False, 0, 1, False),
])
def test_shared_draft_delta_preserves_mutation_and_cursor_boundaries(
    tool_name: str, mutates: bool, before: int, after: int, changed: bool,
) -> None:
    tools = Mock(spec=MindmapToolService)
    tools.operation_cursor.return_value = after
    delta = {'operationCursor': after, 'operations': []}
    tools.build_stream_delta.return_value = delta

    result = build_agent_draft_changed_payload(tools, tool_name, before, mutates_draft=mutates)

    if changed:
        assert result is delta
        tools.build_stream_delta.assert_called_once_with(after_cursor=before, tool_name=tool_name)
    else:
        assert result is None
        tools.build_stream_delta.assert_not_called()
    if not mutates or tool_name == 'start_document':
        tools.operation_cursor.assert_not_called()


@pytest.mark.parametrize(('tool_name', 'with_summary'), [
    ('read_projection', True), ('read_document_detail', True), ('get_node_tags', True),
    ('validate_draft', True), ('complete_artifact', True), ('start_document', False),
    ('add_nodes', False), ('update_nodes', False), ('search_tags', False), ('suggest_tags', False),
])
def test_shared_tool_receipt_only_computes_authorized_summary_when_needed(
    tool_name: str, with_summary: bool,
) -> None:
    tools = Mock(spec=MindmapToolService)
    summary = {'nodeCount': 2, 'treeDepth': 2}
    tools.authorized_scope_summary.return_value = summary

    receipt = build_agent_tool_completed_payload(tools, tool_name)

    assert receipt == {'toolName': tool_name, 'stage': 'building', **({'summary': summary} if with_summary else {})}
    if with_summary:
        tools.authorized_scope_summary.assert_called_once_with()
    else:
        tools.authorized_scope_summary.assert_not_called()


@pytest.mark.parametrize('operation', ['delta', 'summary'])
def test_shared_event_payload_helpers_propagate_errors_to_provider_boundary(operation: str) -> None:
    tools = Mock(spec=MindmapToolService)
    error = MindmapArtifactError('授权正文不可读', code='AI_AGENT_UNAVAILABLE')
    tools.build_stream_delta.side_effect = error
    tools.authorized_scope_summary.side_effect = error

    with pytest.raises(MindmapArtifactError) as raised:
        if operation == 'delta':
            build_agent_draft_changed_payload(tools, 'start_document', 0, mutates_draft=True)
        else:
            build_agent_tool_completed_payload(tools, 'read_projection')
    assert raised.value is error


@pytest.mark.parametrize('source', [None, {}])
@pytest.mark.parametrize('parameters', [{}, {'maxNodes': 100, 'maxDepth': 6}])
def test_shared_structure_budget_preserves_new_vs_existing_map_rules(
    source: dict[str, Any] | None, parameters: dict[str, Any],
) -> None:
    context = AgentRunContext(
        job_id='job', user_id=1, intent='create', prompt='', parameters=parameters,
        source_document=source, tool_service=MindmapToolService(),
    )
    clause = build_agent_structure_budget_clause(context)
    max_nodes, max_depth = parameters.get('maxNodes', 2_000), parameters.get('maxDepth', 32)
    assert f'maxNodes={max_nodes}、maxDepth={max_depth}' in clause
    if source is None:
        assert f'最终节点总数（包括根节点）最多为 {max_nodes}' in clause
        assert '累计最多新增' not in clause
    else:
        assert f'累计最多新增 {max_nodes}' in clause
        assert '删除也不返还预算' in clause
    assert f'最终深度不得超过 {max_depth}' in clause
    assert '只能保持或降低原深度' in clause
