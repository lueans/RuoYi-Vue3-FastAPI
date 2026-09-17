import asyncio
import contextlib
import json
import os
import time
import zipfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import claude_agent_sdk
import openai_codex
import pytest
from agno.models.metrics import Metrics
from agno.models.ollama import Ollama
from agno.run.agent import RunCompletedEvent, RunErrorEvent, RunEvent
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk._internal.session_resume import materialize_resume_session
from pydantic import BaseModel

from module_mindmap.ai.adapters import claude as claude_adapter_module
from module_mindmap.ai.adapters import codex as codex_adapter_module
from module_mindmap.ai.adapters import codex_mcp_bridge, codex_worker
from module_mindmap.ai.adapters.base import (
    AgentNeedsInputResult,
    AgentRunContext,
    agent_message_json_schema,
    build_agent_discussion_prompt,
    build_agent_output_contract,
    compact_agent_discussion_source,
    enforce_agent_target_layout,
    map_adapter_exception,
)
from module_mindmap.ai.adapters.claude import (
    CLAUDE_CREDENTIAL_ENV_ALLOWLIST,
    CLAUDE_FORCED_ISOLATION_ENV,
    CLAUDE_RUNTIME_ENV_ALLOWLIST,
    ClaudeMindmapAdapter,
    _claude_session_snapshot_path,
    _ClaudeSessionStore,
    _read_local_claude_profile_environment,
    _resolve_claude_environment,
)
from module_mindmap.ai.adapters.codex import (
    CodexMindmapAdapter,
    _build_worker_environment,
    _cleanup_expired_session_snapshots,
    _CodexToolExecutionBridge,
    _decode_worker_progress,
    _decode_worker_response,
    _restore_session_snapshot,
    _save_session_snapshot,
    _session_snapshot_paths,
    _stage_local_codex_auth,
    _validated_worker_usage,
    _WorkerStreamDecoder,
)
from module_mindmap.ai.adapters.codex_mcp_bridge import _consume_capability_token
from module_mindmap.ai.adapters.native import (
    NativeAgentMessageCompletion,
    NativeMindmapAdapter,
)
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.tool_contract import MindmapToolService

EXPECTED_NODE_COUNT = 2
EXPECTED_CODEX_INPUT_ITEMS = 2
EXPECTED_TOTAL_TOKENS = 15
EXPECTED_FALLBACK_TOTAL_TOKENS = 8
EXPECTED_POLICY_BUDGET = 1.25
EXPECTED_DEFAULT_BUDGET = 5.0
EXPECTED_LONG_CONTEXT_COST = 1.088184
EXPECTED_STREAM_MESSAGE_COUNT = 2
EXPECTED_MAX_NEEDS_INPUT_QUESTIONS = 3
EXPECTED_MAX_NEEDS_INPUT_QUESTION_LENGTH = 300
EXPECTED_MAX_IDENTICAL_TOOL_FAILURES = 3
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
CODEX_THREAD_ID = '01900000-0000-7000-8000-000000000001'
CODEX_SECOND_THREAD_ID = '01900000-0000-7000-8000-000000000002'
CLAUDE_SESSION_ID = '12345678-1234-4234-8234-123456789001'
CLAUDE_PARENT_SESSION_ID = '12345678-1234-4234-8234-123456789002'
CLAUDE_CHILD_SESSION_ID = '12345678-1234-4234-8234-123456789003'


def _codex_usage(*, cost: float = 0.0000769) -> dict[str, Any]:
    return {
        'inputTokens': 10,
        'cachedInputTokens': 2,
        'cacheWriteInputTokens': 1,
        'outputTokens': 5,
        'totalTokens': EXPECTED_TOTAL_TOKENS,
        'totalCostUsd': cost,
        'costEstimated': True,
        'costBasis': codex_worker.CODEX_COST_BASIS,
        'budgetEnforcement': codex_worker.CODEX_BUDGET_ENFORCEMENT,
    }


def _write_fake_codex_rollout(worker_kwargs: dict[str, Any], thread_id: str) -> Path:
    codex_home = Path(worker_kwargs['environment']['CODEX_HOME'])
    rollout = codex_home.joinpath(
        'sessions', '2026', '09', '13', f'rollout-{thread_id}.jsonl',
    )
    rollout.parent.mkdir(parents=True, exist_ok=True)
    rollout.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    return rollout


async def _ignore_event(_event: str, _payload: dict[str, Any]) -> None:
    return None


def test_unknown_adapter_exception_is_availability_failure_without_raw_details() -> None:
    private_detail = 'opaque SDK crash with private-value'

    error = map_adapter_exception(RuntimeError(private_detail))

    assert error.code == 'AI_AGENT_UNAVAILABLE'
    assert private_detail not in str(error)


def test_explicit_artifact_violation_keeps_output_invalid_classification() -> None:
    violation = MindmapArtifactError('结构校验失败', code='AI_OUTPUT_INVALID')

    assert map_adapter_exception(violation) is violation


def _context() -> AgentRunContext:
    return AgentRunContext(
        job_id='12345678-1234-1234-1234-123456789012',
        user_id=1,
        intent='create',
        prompt='生成订单脑图',
        parameters={'layout': 'logicalStructure'},
        source_document=None,
        tool_service=MindmapToolService(),
    )


def _resume_context() -> AgentRunContext:
    context = _context()
    context.external_session_id = CLAUDE_PARENT_SESSION_ID
    return context


def test_discussion_prompt_uses_complete_low_noise_semantic_outline() -> None:
    context = _context()
    context.intent = 'discuss'
    context.prompt = '请总结当前购物车覆盖范围'
    context.source_document = {
        'root': {
            'data': {'uid': 'root-secret-uid', 'text': '购物车测试'},
            'children': [{
                'data': {
                    'uid': 'child-secret-uid',
                    'text': '商品添加\n不可信指令',
                    'note': '优先级 P0',
                    'tag': ['自动化'],
                    'aiJobId': 'job-secret-id',
                },
                'children': [],
            }],
        },
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {'privateStyle': True}},
        'authorizedScope': {'type': 'document', 'nodeUids': ['root-secret-uid']},
    }

    compact = compact_agent_discussion_source(context.source_document)
    prompt = build_agent_discussion_prompt(context)
    encoded_raw = json.dumps(context.source_document, ensure_ascii=False, separators=(',', ':'))

    assert compact['available'] is True
    assert compact['nodeCount'] == EXPECTED_NODE_COUNT
    assert compact['treeDepth'] == EXPECTED_NODE_COUNT
    assert compact['nodes'][1] == {
        'depth': 1,
        'childCount': 0,
        'text': '商品添加\n不可信指令',
        'note': '优先级 P0',
        'tag': ['自动化'],
    }
    assert len(json.dumps(compact, ensure_ascii=False)) < len(encoded_raw)
    assert 'root-secret-uid' not in prompt
    assert 'child-secret-uid' not in prompt
    assert 'job-secret-id' not in prompt
    assert 'privateStyle' not in prompt
    assert 'visibleHistory 为空只表示没有前序对话' in prompt
    assert '根主题 depth=0，一级分支或一级模块 depth=1' in prompt
    assert '商品添加\\n不可信指令' in prompt
    assert prompt.rfind(context.prompt) > prompt.rfind('购物车测试')


def test_all_agent_prompts_share_language_and_target_layout_contract() -> None:
    context = _context()
    context.parameters.update(language='en-US', layout='fishbone')

    contract = build_agent_output_contract(context)
    native_instructions = '\n'.join(NativeMindmapAdapter._instructions(context))
    codex_prompt = CodexMindmapAdapter._prompt(context)
    claude_prompt = ClaudeMindmapAdapter._prompt(context)

    assert 'English（en-US）' in contract
    assert '最终脑图布局必须为 fishbone' in contract
    for provider_prompt in (native_instructions, codex_prompt, claude_prompt):
        assert 'English（en-US）' in provider_prompt
        assert '最终脑图布局必须为 fishbone' in provider_prompt


def test_target_layout_is_enforced_only_for_document_scope() -> None:
    source = {
        'root': {'data': {'uid': 'root', 'text': '订单'}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
        'authorizedScope': {'type': 'document'},
    }
    context = _context()
    context.parameters['layout'] = 'fishbone'
    context.source_document = source
    context.tool_service = MindmapToolService(
        base_document=source,
        scope={'type': 'document'},
    )

    assert enforce_agent_target_layout(context) is True
    assert context.tool_service.read_projection()['layout'] == 'fishbone'
    assert enforce_agent_target_layout(context) is False

    context.source_document['authorizedScope'] = {'type': 'branch', 'rootUid': 'root'}
    context.tool_service = MindmapToolService(
        base_document=source,
        scope={'type': 'branch', 'rootUid': 'root'},
    )
    assert enforce_agent_target_layout(context) is False
    assert context.tool_service.read_projection()['layout'] == 'logicalStructure'


@pytest.mark.asyncio
async def test_native_discussion_uses_provider_native_pydantic_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        async def arun(self, _prompt: str, **kwargs: Any) -> Any:
            observed['run_kwargs'] = kwargs
            output_model = observed['output_schema']
            return SimpleNamespace(
                content=output_model(
                    completionState='message_completed',
                    title='覆盖摘要',
                    content='当前已覆盖购物车的核心路径。',
                    contentType='text/plain',
                ),
                metrics=Metrics(total_tokens=8),
            )

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.intent = 'discuss'
    context.metadata['model'] = object()

    result = await NativeMindmapAdapter().run(context, collect_event)

    assert issubclass(observed['output_schema'], BaseModel)
    output_json_schema = observed['output_schema'].model_json_schema()
    assert set(output_json_schema['properties']) == {
        'completionState', 'title', 'content', 'contentType',
    }
    assert set(output_json_schema['required']) == {
        'completionState', 'title', 'content', 'contentType',
    }
    assert observed['run_kwargs'] == {'stream': False}
    assert observed['tools'] == []
    assert result.title == '覆盖摘要'
    assert result.content == '当前已覆盖购物车的核心路径。'
    assert result.content_type == 'text/plain'
    assert events == [
        ('agent_started', {'agentKey': 'native_mindmap', 'tools': []}),
        ('agent_completed', {'hasResponse': True}),
    ]


@pytest.mark.asyncio
async def test_native_discussion_normalizes_only_ollama_plain_text_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            return SimpleNamespace(
                content='当前脑图覆盖正常加购，建议补充库存并发扣减。',
                metrics=Metrics(total_tokens=8),
            )

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.intent = 'discuss'
    context.metadata['model'] = SimpleNamespace(
        provider='Ollama', request_params=None, options=None,
    )

    result = await NativeMindmapAdapter().run(context, _ignore_event)

    assert result.title is None
    assert result.content == '当前脑图覆盖正常加购，建议补充库存并发扣减。'
    assert result.content_type == 'text/plain'


@pytest.mark.asyncio
@pytest.mark.parametrize('raw_output', [
    '{"content":"缺少合同字段"}',
    '```json\n{"content":"代码围栏"}\n```',
    '包含不安全控制符\x00',
])
async def test_native_discussion_plain_text_fallback_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    raw_output: str,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            return SimpleNamespace(content=raw_output, metrics=None)

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.intent = 'discuss'
    context.metadata['model'] = SimpleNamespace(
        provider='Ollama', request_params=None, options=None,
    )

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, _ignore_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'


def test_native_discussion_schema_reaches_ollama_native_format() -> None:
    model = Ollama(id='contract-test')

    request_kwargs = model._prepare_request_kwargs_for_invoke(
        response_format=NativeAgentMessageCompletion,
        tools=[],
    )

    assert request_kwargs['format'] == NativeAgentMessageCompletion.model_json_schema()


@pytest.mark.asyncio
async def test_claude_discussion_accepts_only_sdk_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_query(*, prompt: str, options: Any, **_kwargs: Any) -> Any:
        captured.update(prompt=prompt, options=options)
        yield claude_agent_sdk.ResultMessage(
            subtype='success',
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=CLAUDE_SESSION_ID,
            usage={'input_tokens': 3},
            result='这段自由文本不得覆盖结构化结果',
            structured_output={
                'completionState': 'message_completed',
                'title': '覆盖摘要',
                'content': '当前脑图覆盖购物车核心添加流程。',
                'contentType': 'text/plain',
            },
            terminal_reason='completed',
        )

    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.intent = 'discuss'
    context.metadata.update({
        'modelRef': 'claude-policy-snapshot',
        'credentialEnv': {'ANTHROPIC_API_KEY': 'connector-secret'},
    })

    result = await ClaudeMindmapAdapter(
        session_storage_root=tmp_path.joinpath('claude-sessions'),
    ).run(context, _ignore_event)

    assert result.title == '覆盖摘要'
    assert result.content == '当前脑图覆盖购物车核心添加流程。'
    assert captured['options'].tools == []
    assert captured['options'].mcp_servers == {}
    assert captured['options'].allowed_tools == []
    assert captured['options'].output_format == {
        'type': 'json_schema',
        'schema': agent_message_json_schema(),
    }


@pytest.mark.asyncio
async def test_claude_discussion_does_not_fallback_from_empty_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id=CLAUDE_SESSION_ID,
            usage={}, structured_output={},
            result=json.dumps({
                'completionState': 'message_completed',
                'title': None,
                'content': '不得接受的自由文本回退',
                'contentType': 'text/plain',
            }),
            terminal_reason='completed',
        )

    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.intent = 'discuss'
    context.metadata.update({
        'modelRef': 'claude-policy-snapshot',
        'credentialEnv': {'ANTHROPIC_API_KEY': 'connector-secret'},
    })

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter(
            session_storage_root=tmp_path.joinpath('claude-sessions'),
        ).run(context, _ignore_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('terminal_reason', 'permission_denials', 'deferred_tool_use', 'error_type'),
    [
        ('aborted_streaming', None, None, asyncio.CancelledError),
        ('completed', [{'tool': 'Bash'}], None, MindmapArtifactError),
        ('completed', None, object(), MindmapArtifactError),
    ],
)
async def test_claude_discussion_rejects_cancelled_or_tool_tainted_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal_reason: str,
    permission_denials: list[Any] | None,
    deferred_tool_use: Any,
    error_type: type[BaseException],
) -> None:
    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id=CLAUDE_SESSION_ID,
            usage={},
            structured_output={
                'completionState': 'message_completed',
                'title': None,
                'content': '不得落库的结果',
                'contentType': 'text/plain',
            },
            terminal_reason=terminal_reason,
            permission_denials=permission_denials,
            deferred_tool_use=deferred_tool_use,
        )

    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.intent = 'discuss'
    context.metadata.update({
        'modelRef': 'claude-policy-snapshot',
        'credentialEnv': {'ANTHROPIC_API_KEY': 'connector-secret'},
    })

    with pytest.raises(error_type) as error:
        await ClaudeMindmapAdapter(
            session_storage_root=tmp_path.joinpath('claude-sessions'),
        ).run(context, _ignore_event)

    if isinstance(error.value, MindmapArtifactError):
        assert error.value.code == 'AI_SANDBOX_VIOLATION'


def test_codex_discussion_schema_matches_platform_message_contract() -> None:
    assert agent_message_json_schema() == codex_worker.CODEX_DISCUSSION_RESULT_SCHEMA


def test_codex_completed_agent_text_never_uses_commentary_as_final_output() -> None:
    commentary = SimpleNamespace(
        type='agentMessage',
        phase=SimpleNamespace(value='commentary'),
        text='{"completionState":"message_completed"}',
    )
    legacy = SimpleNamespace(type='agentMessage', phase=None, text='legacy')
    final = SimpleNamespace(
        type='agentMessage',
        phase=SimpleNamespace(value='final_answer'),
        text='final',
    )

    assert codex_worker._completed_agent_text(commentary) == (None, False)
    assert codex_worker._completed_agent_text(legacy) == ('legacy', False)
    assert codex_worker._completed_agent_text(final) == ('final', True)


@pytest.mark.asyncio
@pytest.mark.parametrize('budget', [0, -1, float('nan'), 'invalid', True])
async def test_claude_invalid_budget_policy_is_not_output_invalid(
    budget: Any,
) -> None:
    context = _context()
    context.metadata['maxBudgetUsd'] = budget

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter().run(context, _ignore_event)

    assert error.value.code == 'AI_BUDGET_EXCEEDED'


@pytest.mark.parametrize('adapter', [CodexMindmapAdapter, ClaudeMindmapAdapter])
def test_sdk_prompt_explains_new_document_structure_budget(adapter: type[Any]) -> None:
    context = _context()
    context.parameters.update({'maxNodes': 100, 'maxDepth': 6})

    prompt = adapter._prompt(context)

    assert 'maxNodes=100、maxDepth=6' in prompt
    assert '最终节点总数（包括根节点）最多为 100' in prompt


@pytest.mark.parametrize('adapter', [CodexMindmapAdapter, ClaudeMindmapAdapter])
def test_sdk_prompt_explains_source_document_cumulative_budget(adapter: type[Any]) -> None:
    context = _context()
    context.parameters.update({'maxNodes': 100, 'maxDepth': 6})
    context.source_document = {
        'root': {'data': {'uid': 'root', 'text': '来源'}, 'children': []},
    }

    prompt = adapter._prompt(context)

    assert '累计最多新增 100 个节点' in prompt
    assert '删除也不' in prompt and '返还预算' in prompt
    assert '不能继续加深' in prompt


def _codex_plan(title: str = '订单系统') -> dict[str, Any]:
    return {
        'completionState': 'artifact_completed',
        'title': title,
        'questions': [],
    }


def _needs_input_result() -> dict[str, Any]:
    return {
        'completionState': 'needs_input',
        'title': None,
        'questions': [{
            'questionId': 'scope',
            'prompt': '需要覆盖哪些业务范围？',
        }],
    }


def _dummy_codex_bridge(tmp_path: Path) -> tuple[Any, str]:
    return SimpleNamespace(close=lambda: None), str(tmp_path.joinpath('bridge.sock'))


def _install_inprocess_codex_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, _CodexToolExecutionBridge]:
    state: dict[str, _CodexToolExecutionBridge] = {}

    @contextlib.asynccontextmanager
    async def bridge_server(
        executor: _CodexToolExecutionBridge,
        _socket_directory: Path,
    ) -> Any:
        state['executor'] = executor
        yield (
            Path('/in-process-codex-bridge.sock'),
            Path('/in-process-codex-capability'),
        )

    monkeypatch.setattr(
        codex_adapter_module, '_codex_tool_bridge_server', bridge_server,
    )
    return state


async def _execute_codex_plan_inprocess(
    executor: _CodexToolExecutionBridge,
    *,
    title: str = '订单系统',
) -> None:
    started = await executor.call('start_document', {
        'title': title, 'layout': 'logicalStructure',
    })
    root_uid = started['result']['rootUid']
    assert (await executor.call('add_nodes', {'nodes': [{
        'clientRef': 'create-order',
        'parentUid': root_uid,
        'text': '创建订单',
    }]}))['ok'] is True
    assert (await executor.call('validate_draft', {}))['ok'] is True
    assert (await executor.call('complete_artifact', {}))['ok'] is True


@pytest.mark.asyncio
async def test_native_adapter_returns_common_needs_input_before_tool_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def events() -> Any:
                yield RunCompletedEvent(
                    content=_needs_input_result(),
                    metrics=Metrics(total_tokens=8),
                )

            return events()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    original_tools = context.tool_service
    context.metadata['model'] = object()

    result = await NativeMindmapAdapter().run(context, _ignore_event)

    assert isinstance(result, AgentNeedsInputResult)
    assert result.questions_payload() == _needs_input_result()['questions']
    assert context.tool_service is original_tools


@pytest.mark.asyncio
async def test_native_adapter_uses_terminal_clarification_tool_with_plain_text_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                accepted = json.loads(await tools['request_clarification'](
                    _needs_input_result()['questions'],
                ))
                assert accepted == {'accepted': True, 'questionCount': 1}
                yield RunCompletedEvent(
                    content='请先回答上面的问题。',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    original_tools = context.tool_service
    context.metadata['model'] = object()

    result = await NativeMindmapAdapter().run(context, collect_event)

    assert isinstance(result, AgentNeedsInputResult)
    assert result.questions_payload() == _needs_input_result()['questions']
    assert result.usage['total_tokens'] == EXPECTED_FALLBACK_TOTAL_TOKENS
    assert context.tool_service is original_tools
    assert [event_type for event_type, _payload in events] == [
        'agent_started', 'tool_started', 'tool_completed',
    ]
    assert events[1][1]['toolName'] == 'request_clarification'
    assert events[2][1]['toolName'] == 'request_clarification'


@pytest.mark.asyncio
async def test_native_adapter_accepts_bounded_ollama_plain_text_clarification_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                yield RunCompletedEvent(
                    content='为了生成合适的脑图，请告诉我希望覆盖什么业务主题？',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    original_tools = context.tool_service
    context.metadata['model'] = SimpleNamespace(provider='ollama')

    result = await NativeMindmapAdapter().run(context, _ignore_event)

    assert isinstance(result, AgentNeedsInputResult)
    assert result.questions_payload() == [{
        'questionId': 'clarification',
        'prompt': '为了生成合适的脑图，请告诉我希望覆盖什么业务主题？',
    }]
    assert context.tool_service is original_tools


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'terminal_text',
    [
        '请告诉我希望生成的主题。',
        '```json\n{"question":"主题是什么？"}\n```',
        '请提供你的 API key？',
        '我无法执行工具。\n是否继续？',
        '问题如下：\n1. 主题是什么？',
        '？',
        '1. ?',
        '🤔？',
        '参考 https://example.com 后告诉我主题？',
    ],
)
async def test_native_adapter_rejects_ambiguous_or_unsafe_plain_text_clarification(
    monkeypatch: pytest.MonkeyPatch,
    terminal_text: str,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                yield RunCompletedEvent(
                    content=terminal_text,
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = SimpleNamespace(provider='ollama')

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, _ignore_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_native_plain_text_clarification_is_rejected_after_draft_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('已创建草稿')
                yield RunCompletedEvent(
                    content='还需要我补充什么内容？',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.parameters['layout'] = 'fishbone'
    context.metadata['model'] = SimpleNamespace(provider='ollama')

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, _ignore_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_native_ollama_auto_finalizes_exactly_the_last_validated_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                root_uid = json.loads(
                    await tools['start_document']('用户登录')
                )['rootUid']
                await tools['add_nodes']([{
                    'parentUid': root_uid,
                    'text': '正常登录',
                }])
                await tools['validate_draft']()
                yield RunCompletedEvent(
                    content='脑图已生成。',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.parameters['layout'] = 'fishbone'
    context.metadata['model'] = SimpleNamespace(provider='ollama')

    result = await NativeMindmapAdapter().run(context, collect_event)

    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert result.artifact['document']['layout'] == 'fishbone'
    assert NativeMindmapAdapter().get_manifest().adapter_version == '1.12.0'
    assert [
        payload['toolName']
        for event_type, payload in events
        if event_type == 'tool_completed'
    ] == ['start_document', 'add_nodes', 'validate_draft', 'complete_artifact']
    assert events[-1][0] == 'agent_completed'


@pytest.mark.asyncio
async def test_native_ollama_validates_and_finalizes_a_mutated_unvalidated_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                root_uid = json.loads(
                    await tools['start_document']('用户登录')
                )['rootUid']
                await tools['add_nodes']([{
                    'parentUid': root_uid,
                    'text': '安全控制',
                }])
                yield RunCompletedEvent(
                    content='脑图已生成。',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.parameters['layout'] = 'fishbone'
    context.metadata['model'] = SimpleNamespace(provider='ollama')

    result = await NativeMindmapAdapter().run(context, collect_event)

    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert [
        payload['toolName']
        for event_type, payload in events
        if event_type == 'tool_completed'
    ] == ['start_document', 'add_nodes', 'validate_draft', 'complete_artifact']
    assert events[-1][0] == 'agent_completed'


@pytest.mark.asyncio
async def test_native_ollama_does_not_auto_finalize_after_post_validation_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                root_uid = json.loads(
                    await tools['start_document']('用户登录')
                )['rootUid']
                await tools['validate_draft']()
                await tools['add_nodes']([{
                    'parentUid': root_uid,
                    'text': '未重新校验的节点',
                }])
                yield RunCompletedEvent(
                    content='脑图已生成。',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = SimpleNamespace(provider='ollama')

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, _ignore_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_native_clarification_tool_rejects_after_start_document_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('订单系统')
                rejected = json.loads(await tools['request_clarification'](
                    _needs_input_result()['questions'],
                ))
                assert rejected == {
                    'ok': False,
                    'errorCode': 'TOOL_CONSTRAINT_VIOLATION',
                    'message': '工具参数或当前草稿状态不满足约束，请读取投影后重试',
                    'retryable': True,
                }
                await tools['validate_draft']()
                await tools['complete_artifact']()
                yield RunCompletedEvent(
                    content='脑图已完成。',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    result = await NativeMindmapAdapter().run(context, collect_event)

    assert result.summary['nodeCount'] == 1
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_failed'
    ] == ['request_clarification']


@pytest.mark.asyncio
async def test_native_adapter_rejects_tools_after_terminal_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['request_clarification'](_needs_input_result()['questions'])
                rejected = json.loads(await tools['read_projection']())
                assert rejected['ok'] is False
                yield RunCompletedEvent(
                    content='请先回答问题。',
                    metrics=Metrics(total_tokens=8),
                )

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    with pytest.raises(
        MindmapArtifactError,
        match='request_clarification 后继续调用工具',
    ) as error:
        await NativeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_failed'
    ] == ['read_projection']
    assert events[-1][0] != 'agent_completed'


@pytest.mark.asyncio
async def test_codex_adapter_returns_common_needs_input_before_tool_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_inprocess_codex_bridge(monkeypatch)

    async def fake_invoke(
        _request: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        _write_fake_codex_rollout(kwargs, CODEX_THREAD_ID)
        return {
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'ok': True,
            'result': _needs_input_result(),
            'externalSessionId': CODEX_THREAD_ID,
            'usage': _codex_usage(),
        }

    adapter = CodexMindmapAdapter(session_storage_root=tmp_path.joinpath('sessions'))
    monkeypatch.setattr(adapter, '_invoke_worker', fake_invoke)
    context = _context()
    original_tools = context.tool_service
    context.metadata['credentialEnv'] = {'OPENAI_API_KEY': 'connector-secret'}

    result = await adapter.run(context, _ignore_event)

    assert isinstance(result, AgentNeedsInputResult)
    assert result.questions_payload() == _needs_input_result()['questions']
    assert result.external_session_id == CODEX_THREAD_ID
    assert result.external_session_created is True
    assert context.tool_service is original_tools


@pytest.mark.asyncio
async def test_claude_adapter_returns_common_needs_input_before_tool_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.ResultMessage(
            subtype='success',
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=CLAUDE_SESSION_ID,
            usage={'input_tokens': 3},
            structured_output=_needs_input_result(),
        )

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    original_tools = context.tool_service
    context.metadata['modelRef'] = 'claude-policy-snapshot'
    adapter = ClaudeMindmapAdapter(session_storage_root=tmp_path.joinpath('sessions'))

    result = await adapter.run(context, _ignore_event)

    assert isinstance(result, AgentNeedsInputResult)
    assert result.questions_payload() == _needs_input_result()['questions']
    assert result.external_session_id == CLAUDE_SESSION_ID
    assert result.external_session_created is True
    assert context.tool_service is original_tools


@pytest.mark.asyncio
async def test_native_mindmap_agent_uses_only_domain_tools_and_collects_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, prompt: str, **kwargs: Any) -> Any:
            observed.update(prompt=prompt, run=kwargs)

            async def events() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('订单系统')
                await tools['add_nodes']([{'parentUid': '@root', 'text': '创建订单'}])
                await tools['validate_draft']()
                await tools['complete_artifact']()
                yield RunCompletedEvent(
                    content='脑图已生成。',
                    metrics=Metrics(
                        input_tokens=10,
                        output_tokens=5,
                        total_tokens=15,
                        cost=0.01,
                    ),
                )

            return events()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.external_session_id = CLAUDE_PARENT_SESSION_ID
    context.metadata['model'] = object()
    result = await NativeMindmapAdapter().run(context, _ignore_event)

    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert result.usage['total_tokens'] == EXPECTED_TOTAL_TOKENS
    assert result.external_session_id is None
    assert observed['session_id'] == context.job_id
    assert observed['telemetry'] is False
    assert 'output_schema' not in observed
    assert 'parse_response' not in observed
    assert 'structured_outputs' not in observed
    tool_by_name = {tool.__name__: tool for tool in observed['tools']}
    assert set(tool_by_name) == {
        'read_projection', 'start_document', 'add_nodes', 'update_nodes', 'move_nodes',
        'remove_nodes', 'set_document_meta', 'validate_draft', 'complete_artifact',
        'request_clarification',
    }
    start_document_schema = tool_by_name['start_document'].to_dict()
    assert set(start_document_schema['parameters']['properties']) == {'title'}
    assert start_document_schema['parameters']['required'] == ['title']
    expected_layouts = [
        'mindMap', 'logicalStructure', 'organizationStructure', 'catalogOrganization',
        'timeline', 'timeline2', 'verticalTimeline', 'verticalTimeline2',
        'verticalTimeline3', 'fishbone', 'fishbone2', 'rightFishbone',
        'rightFishbone2', 'logicalStructureLeft',
    ]
    set_meta_schema = tool_by_name['set_document_meta'].to_dict()
    assert set_meta_schema['parameters']['properties']['layout']['enum'] == expected_layouts
    add_item_schema = (
        tool_by_name['add_nodes']
        .to_dict()['parameters']['properties']['nodes']['items']
    )
    assert set(add_item_schema['required']) == {'parentUid', 'text'}
    assert '@root' in add_item_schema['properties']['parentUid']['description']
    assert '不要带 @' in add_item_schema['properties']['clientRef']['description']
    update_item_schema = (
        tool_by_name['update_nodes']
        .to_dict()['parameters']['properties']['updates']['items']
    )
    patch_properties = update_item_schema['properties']['patch']['properties']
    assert set(patch_properties) == {'text', 'note', 'hyperlink', 'tag'}
    clarification_schema = tool_by_name['request_clarification'].to_dict()['parameters']
    assert clarification_schema['required'] == ['questions']
    question_list_schema = clarification_schema['properties']['questions']
    assert question_list_schema['minItems'] == 1
    assert question_list_schema['maxItems'] == EXPECTED_MAX_NEEDS_INPUT_QUESTIONS
    question_schema = question_list_schema['items']
    assert set(question_schema['required']) == {'questionId', 'prompt'}
    assert question_schema['properties']['questionId']['pattern'] == (
        '^[A-Za-z][A-Za-z0-9_-]{0,31}$'
    )
    assert question_schema['properties']['prompt']['maxLength'] == (
        EXPECTED_MAX_NEEDS_INPUT_QUESTION_LENGTH
    )


@pytest.mark.asyncio
async def test_native_agent_resumes_checkpoint_without_restarting_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def events() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                assert 'start_document' not in tools
                await tools['read_projection']()
                await tools['add_nodes']([{
                    'parentUid': '@root',
                    'text': '恢复后继续生成',
                }])
                await tools['validate_draft']()
                await tools['complete_artifact']()
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return events()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.tool_service.start_document('已恢复草稿', 'logicalStructure')
    context.metadata['model'] = object()

    result = await NativeMindmapAdapter().run(context, _ignore_event)

    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    instructions = '\n'.join(observed['instructions'])
    assert '从检查点恢复' in instructions
    assert '不得调用 start_document' in instructions
    assert '不得重建已有内容' in instructions


@pytest.mark.asyncio
async def test_native_agent_stops_repeated_identical_tool_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []
    secret_reference = '@private-secret-node'

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('订单系统')
                for _index in range(3):
                    await tools['add_nodes']([{
                        'parentUid': secret_reference,
                        'text': '创建订单',
                    }])
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    original_tools = context.tool_service
    context.metadata['model'] = object()

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'
    failed_events = [
        payload for event_type, payload in events if event_type == 'tool_failed'
    ]
    assert len(failed_events) == EXPECTED_MAX_IDENTICAL_TOOL_FAILURES
    assert all(payload['toolName'] == 'add_nodes' for payload in failed_events)
    assert failed_events[-1]['retryable'] is False
    assert '自动纠错已达上限' in failed_events[-1]['errorMessage']
    assert secret_reference not in json.dumps(events, ensure_ascii=False)
    assert context.tool_service is original_tools


@pytest.mark.asyncio
async def test_native_agent_requires_explicit_complete_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                root_uid = json.loads(await tools['start_document']('订单系统'))['rootUid']
                await tools['add_nodes']([{
                    'parentUid': root_uid,
                    'text': '创建订单',
                }])
                # 模拟供应商正常结束，但模型忘记调用最后两个工具。
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    with pytest.raises(MindmapArtifactError, match='未显式调用 complete_artifact') as error:
        await NativeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_completed'
    ] == ['start_document', 'add_nodes']
    assert events[-1][0] != 'agent_completed'


@pytest.mark.asyncio
async def test_native_agent_rejects_any_tool_after_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('订单系统')
                await tools['complete_artifact']()
                rejected = json.loads(await tools['read_projection']())
                assert rejected['ok'] is False
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    with pytest.raises(MindmapArtifactError, match='complete_artifact 后继续调用工具'):
        await NativeMindmapAdapter().run(context, collect_event)

    assert events[-1][0] != 'agent_completed'
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_failed'
    ] == ['read_projection']


@pytest.mark.asyncio
async def test_native_agent_still_rejects_a_run_without_any_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    with pytest.raises(MindmapArtifactError, match='未显式调用 complete_artifact'):
        await NativeMindmapAdapter().run(context, _ignore_event)


@pytest.mark.asyncio
async def test_native_mindmap_agent_maps_stream_run_error_without_leaking_provider_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = 'private upstream response sk-secret-value'
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                yield RunErrorEvent(
                    content=f'{secret} (status code: 502)',
                    error_type='ModelProviderError',
                )

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert secret not in str(error.value)
    assert secret not in json.dumps(events, ensure_ascii=False)
    assert events == [
        ('agent_started', {'agentKey': 'native_mindmap'}),
        ('agent_error', {
            'errorCode': 'AI_AGENT_UNAVAILABLE',
            'errorMessage': 'Agent 供应商网络不可用',
        }),
    ]


@pytest.mark.asyncio
async def test_native_mindmap_tool_errors_emit_once_without_shifting_success_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                for invalid_title in (None, []):
                    rejected = json.loads(
                        await tools['start_document'](invalid_title)
                    )
                    assert rejected['errorCode'] == 'TOOL_ARGUMENT_INVALID'

                successful_tool = SimpleNamespace(tool_call_error=False)
                for tool_name, action in (
                    ('start_document', lambda: tools['start_document']('订单系统')),
                    ('add_nodes', lambda: tools['add_nodes']([{
                        'parentUid': next(iter(observed['root_uids'])),
                        'text': '创建订单',
                    }])),
                    ('validate_draft', tools['validate_draft']),
                    ('complete_artifact', tools['complete_artifact']),
                ):
                    successful_tool.tool_name = tool_name
                    yield SimpleNamespace(event=RunEvent.tool_call_started, tool=successful_tool)
                    result = await action()
                    if tool_name == 'start_document':
                        observed['root_uids'] = {json.loads(result)['rootUid']}
                    yield SimpleNamespace(event=RunEvent.tool_call_completed, tool=successful_tool)
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    result = await NativeMindmapAdapter().run(context, collect_event)

    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert [event_type for event_type, _payload in events] == [
        'agent_started',
        'tool_failed',
        'tool_failed',
        'tool_started', 'draft_changed', 'tool_completed',
        'tool_started', 'draft_changed', 'tool_completed',
        'tool_started', 'tool_completed',
        'tool_started', 'tool_completed',
        'agent_completed',
    ]
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_completed'
    ] == ['start_document', 'add_nodes', 'validate_draft', 'complete_artifact']
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_failed'
    ] == ['start_document', 'start_document']


@pytest.mark.asyncio
async def test_native_pre_wrapper_argument_error_emits_exactly_one_tool_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                # 模拟 Agno 在调用包装器前拒绝缺失 nodes 参数的 add_nodes。
                failed_tool = SimpleNamespace(
                    tool_name='add_nodes',
                    tool_call_error=True,
                )
                yield SimpleNamespace(event=RunEvent.tool_call_started, tool=failed_tool)
                yield SimpleNamespace(event=RunEvent.tool_call_completed, tool=failed_tool)
                yield SimpleNamespace(
                    event=RunEvent.tool_call_error,
                    tool=failed_tool,
                    error='Missing required argument: nodes input_value=token-SECRET',
                )

                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('订单系统')
                await tools['validate_draft']()
                await tools['complete_artifact']()
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    await NativeMindmapAdapter().run(context, collect_event)

    failed_events = [
        payload for event_type, payload in events if event_type == 'tool_failed'
    ]
    assert failed_events == [{
        'toolName': 'add_nodes',
        'errorCode': 'TOOL_EXECUTION_FAILED',
        'errorMessage': '工具调用失败，请按工具 Schema 重试',
        'retryable': True,
    }]
    assert 'token-SECRET' not in json.dumps(events, ensure_ascii=False)
    assert not [
        payload
        for event_type, payload in events
        if event_type == 'tool_started' and payload.get('toolName') == 'add_nodes'
    ]


@pytest.mark.asyncio
async def test_native_parallel_tool_calls_are_serialized_with_matching_draft_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                root_uid = json.loads(await tools['start_document']('订单系统'))['rootUid']
                await asyncio.gather(
                    tools['update_nodes']([{
                        'nodeUid': root_uid,
                        'patch': {'text': '第一版'},
                    }]),
                    tools['update_nodes']([{
                        'nodeUid': root_uid,
                        'patch': {'text': '第二版'},
                    }]),
                )
                await tools['validate_draft']()
                await tools['complete_artifact']()
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        if event_type == 'tool_started' and payload.get('toolName') == 'update_nodes':
            await asyncio.sleep(0.01)
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()

    result = await NativeMindmapAdapter().run(context, collect_event)

    assert result.title == '第二版'
    update_events = [
        (event_type, payload)
        for event_type, payload in events
        if payload.get('toolName') == 'update_nodes'
    ]
    assert [event_type for event_type, _payload in update_events] == [
        'tool_started', 'draft_changed', 'tool_completed',
        'tool_started', 'draft_changed', 'tool_completed',
    ]
    assert [
            payload['operations'][0]['payload']['set']['text']
        for event_type, payload in update_events
        if event_type == 'draft_changed'
    ] == ['第一版', '第二版']


@pytest.mark.asyncio
async def test_native_cancel_stops_running_and_queued_tools_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_started = asyncio.Event()
    stream_closed = asyncio.Event()
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                root_uid = json.loads(await tools['start_document']('订单系统'))['rootUid']
                try:
                    await asyncio.gather(
                        tools['update_nodes']([{
                            'nodeUid': root_uid,
                            'patch': {'text': '不应提交的更新'},
                        }]),
                        tools['set_document_meta'](title='不应提交的标题'),
                    )
                finally:
                    stream_closed.set()
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    async def block_first_update(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))
        if event_type == 'tool_started' and payload.get('toolName') == 'update_nodes':
            update_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    context.metadata['model'] = object()
    adapter = NativeMindmapAdapter()
    task = asyncio.create_task(adapter.run(context, block_first_update))
    await asyncio.wait_for(update_started.wait(), timeout=1)

    assert await adapter.cancel(context.job_id) is True
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(stream_closed.wait(), timeout=1)
    assert await adapter.cancel(context.job_id) is False
    assert context.tool_service.read_projection()['root']['data']['text'] == '订单系统'
    assert not [
        event_type
        for event_type, payload in events
        if payload.get('toolName') in {'update_nodes', 'set_document_meta'}
        and event_type in {'draft_changed', 'tool_completed'}
    ]


@pytest.mark.asyncio
async def test_codex_adapter_uses_isolated_worker_protocol(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, Any] = {}
    bridge_state = _install_inprocess_codex_bridge(monkeypatch)

    async def fake_invoke(
        request: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        observed.update(request=request, **kwargs)
        await _execute_codex_plan_inprocess(bridge_state['executor'])
        assert not kwargs['workspace'].joinpath('input.json').exists()
        assert not kwargs['workspace'].joinpath('mindmap-result.json').exists()
        _write_fake_codex_rollout(kwargs, CODEX_THREAD_ID)
        Path(kwargs['environment']['CODEX_HOME']).joinpath('auth.json').write_text(
            'must-not-persist', encoding='utf-8',
        )
        return {
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'ok': True,
            'result': _codex_plan(),
            'externalSessionId': CODEX_THREAD_ID,
            'usage': _codex_usage(),
        }

    adapter = CodexMindmapAdapter(session_storage_root=tmp_path.joinpath('sessions'))
    monkeypatch.setattr(adapter, '_invoke_worker', fake_invoke)
    monkeypatch.setenv('DB_PASSWORD', 'must-not-leak')
    monkeypatch.setenv('JWT_SECRET_KEY', 'must-not-leak')
    monkeypatch.setenv('REDIS_PASSWORD', 'must-not-leak')
    context = _context()
    context.metadata.update({
        'modelRef': 'gpt-5.6-terra',
        'credentialEnv': {'OPENAI_API_KEY': 'connector-secret'},
    })
    result = await adapter.run(context, _ignore_event)

    assert result.external_session_id == CODEX_THREAD_ID
    assert result.external_session_created is True
    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert observed['request']['model'] == 'gpt-5.6-terra'
    assert observed['request']['maxBudgetUsd'] == EXPECTED_DEFAULT_BUDGET
    assert 'externalSessionId' not in observed['request']
    assert observed['request']['sourceProjection'] is None
    assert 'bridgeToken' not in observed['request']
    assert bridge_state['executor'].capability_token not in json.dumps(observed['request'])
    assert observed['environment']['OPENAI_API_KEY'] == 'connector-secret'
    assert observed['environment']['HOME'] != str(Path.home())
    assert 'DB_PASSWORD' not in observed['environment']
    assert 'JWT_SECRET_KEY' not in observed['environment']
    assert 'REDIS_PASSWORD' not in observed['environment']
    archive_path, _metadata_path = _session_snapshot_paths(
        tmp_path.joinpath('sessions'), CODEX_THREAD_ID,
    )
    with zipfile.ZipFile(archive_path) as archive:
        assert 'auth.json' not in archive.namelist()
        assert any(name.startswith('sessions/') for name in archive.namelist())


@pytest.mark.asyncio
async def test_codex_adapter_does_not_trust_receipt_without_actual_mcp_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_inprocess_codex_bridge(monkeypatch)

    async def fake_invoke(
        _request: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        _write_fake_codex_rollout(kwargs, CODEX_THREAD_ID)
        return {
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'ok': True,
            'result': _codex_plan(),
            'externalSessionId': CODEX_THREAD_ID,
            'usage': _codex_usage(),
        }

    adapter = CodexMindmapAdapter(session_storage_root=tmp_path.joinpath('sessions'))
    monkeypatch.setattr(adapter, '_invoke_worker', fake_invoke)
    context = _context()
    context.metadata['credentialEnv'] = {'OPENAI_API_KEY': 'connector-secret'}

    with pytest.raises(MindmapArtifactError, match='未以唯一一次 complete_artifact') as error:
        await adapter.run(context, _ignore_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_codex_worker_disables_nondomain_tools_and_requires_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, Any] = {}
    progress_events: list[tuple[str, int, dict[str, int] | None]] = []

    class FakeThread:
        id = CODEX_THREAD_ID

        async def turn(self, run_input: Any, **kwargs: Any) -> Any:
            observed.update(run_input=run_input, run=kwargs)
            assert kwargs['output_schema'] == codex_worker.CODEX_RESULT_SCHEMA

            class FakeTurn:
                id = 'turn-1'

                async def stream(self) -> Any:
                    yield SimpleNamespace(
                        method='thread/tokenUsage/updated',
                        payload=SimpleNamespace(
                            turn_id=self.id,
                            token_usage=SimpleNamespace(last=SimpleNamespace(
                                input_tokens=10,
                                cached_input_tokens=2,
                                cache_write_input_tokens=1,
                                output_tokens=5,
                                reasoning_output_tokens=99,
                                total_tokens=15,
                            )),
                        ),
                    )
                    yield SimpleNamespace(
                        method='item/completed',
                        payload=SimpleNamespace(
                            turn_id=self.id,
                            item=SimpleNamespace(
                                type='agentMessage',
                                phase=SimpleNamespace(value='final_answer'),
                                text=json.dumps(
                                    _codex_plan('结构化订单脑图'), ensure_ascii=False,
                                ),
                            ),
                        ),
                    )
                    yield SimpleNamespace(
                        method='turn/completed',
                        payload=SimpleNamespace(turn=SimpleNamespace(
                            id=self.id,
                            status=SimpleNamespace(value='completed'),
                            error=None,
                        )),
                    )

            return FakeTurn()

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            observed['config'] = config

        async def __aenter__(self) -> 'FakeCodex':
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def login_api_key(self, api_key: str) -> None:
            observed['connector_api_key'] = api_key

        async def thread_start(self, **kwargs: Any) -> FakeThread:
            observed['start'] = kwargs
            return FakeThread()

    monkeypatch.setattr(openai_codex, 'AsyncCodex', FakeCodex)
    monkeypatch.setenv('OPENAI_API_KEY', 'connector-secret')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path.joinpath('codex-home')))
    monkeypatch.chdir(tmp_path)
    source_projection = {
        'root': {'data': {'uid': 'root', 'text': '来源'}, 'children': []},
    }
    bridge, bridge_path = _dummy_codex_bridge(tmp_path)
    response = await codex_worker.run_request(
        {
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'operation': 'generate',
            'model': 'gpt-5.6-terra',
            'prompt': '受控提示',
            'sourceProjection': source_projection,
            'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
            'bridgeSocket': bridge_path,
            'bridgeTokenFile': str(tmp_path.joinpath('capability')),
            'allowedTools': list(codex_worker.ALLOWED_TOOL_NAMES),
        },
        lambda stage, progress, usage: progress_events.append((stage, progress, usage)),
    )
    bridge.close()

    required_denials = {
        'sandbox_mode="read-only"',
        'approval_policy="never"',
        'web_search="disabled"',
        'tools.web_search=false',
        'tools.update_plan.enabled=false',
        'project_doc_max_bytes=0',
        'history.persistence="save-all"',
        'shell_environment_policy.inherit="none"',
        'features.shell_tool=false',
        'features.unified_exec=false',
        'features.apply_patch_freeform=false',
        'features.view_image=false',
        'features.apps=false',
        'features.plugins=false',
        'features.skill_search=false',
        'features.workspace_dependencies=false',
        'features.code_mode.enabled=true',
        'features.code_mode_host=true',
    }
    assert required_denials <= set(observed['config'].config_overrides)
    assert any(
        value.startswith('mcp_servers.mindmap.command=')
        for value in observed['config'].config_overrides
    )
    assert 'mcp_optional_startup_grace_ms=0' in observed['config'].config_overrides
    assert 'mcp_servers.mindmap.enabled=true' in observed['config'].config_overrides
    assert 'mcp_servers.mindmap.required=true' in observed['config'].config_overrides
    assert (
        'mcp_servers.mindmap.default_tools_approval_mode="approve"'
        in observed['config'].config_overrides
    )
    enabled_tools = next(
        value for value in observed['config'].config_overrides
        if value.startswith('mcp_servers.mindmap.enabled_tools=[')
    )
    assert all(name in enabled_tools for name in codex_worker.ALLOWED_TOOL_NAMES)
    skills_override = next(
        value for value in observed['config'].config_overrides
        if value.startswith('skills.config=[')
    )
    assert all(name in skills_override for name in codex_worker.DISABLED_CODEX_SKILL_NAMES)
    assert observed['config'].env == {}
    assert observed['connector_api_key'] == 'connector-secret'
    assert observed['start']['ephemeral'] is False
    assert observed['start']['sandbox'] is openai_codex.Sandbox.read_only
    assert observed['start']['approval_mode'] is openai_codex.ApprovalMode.deny_all
    assert observed['run']['sandbox'] is openai_codex.Sandbox.read_only
    assert observed['run']['approval_mode'] is openai_codex.ApprovalMode.deny_all
    assert len(observed['run_input']) == EXPECTED_CODEX_INPUT_ITEMS
    assert observed['run_input'][0].text == '受控提示'
    assert 'untrusted_source_projection_json' in observed['run_input'][1].text
    assert json.dumps(source_projection, ensure_ascii=False, separators=(',', ':')) in (
        observed['run_input'][1].text
    )
    assert response['result'] == _codex_plan('结构化订单脑图')
    assert response['externalSessionId'] == CODEX_THREAD_ID
    assert response['usage'] == _codex_usage()
    assert [item[0] for item in progress_events] == [
        'sdk_ready',
        'turn_started',
        'model_processing',
        'usage_updated',
        'structured_output_received',
        'turn_completed',
    ]
    assert all('reasoning' not in key for key in response['usage'])


def test_codex_bridge_consumes_capability_file_without_argv_secret(
    tmp_path: Path,
) -> None:
    capability = 'private-capability-' + ('a' * 48)
    token_file = tmp_path.joinpath('capability')
    token_file.write_text(capability, encoding='ascii')
    token_file.chmod(0o400)

    assert _consume_capability_token(token_file) == capability
    assert not token_file.exists()


@pytest.mark.asyncio
async def test_codex_worker_forks_exact_sdk_thread_into_an_independent_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, Any] = {}

    class FakeThread:
        id = CODEX_SECOND_THREAD_ID

        async def turn(self, _run_input: Any, **_kwargs: Any) -> Any:
            class FakeTurn:
                id = 'turn-resumed'

                async def stream(self) -> Any:
                    yield SimpleNamespace(
                        method='thread/tokenUsage/updated',
                        payload=SimpleNamespace(
                            turn_id=self.id,
                            token_usage=SimpleNamespace(last=SimpleNamespace(
                                input_tokens=10,
                                cached_input_tokens=2,
                                cache_write_input_tokens=1,
                                output_tokens=5,
                                total_tokens=15,
                            )),
                        ),
                    )
                    yield SimpleNamespace(
                        method='item/completed',
                        payload=SimpleNamespace(
                            turn_id=self.id,
                            item=SimpleNamespace(
                                type='agentMessage',
                                phase=SimpleNamespace(value='final_answer'),
                                text=json.dumps(_codex_plan(), ensure_ascii=False),
                            ),
                        ),
                    )
                    yield SimpleNamespace(
                        method='turn/completed',
                        payload=SimpleNamespace(turn=SimpleNamespace(
                            id=self.id,
                            status=SimpleNamespace(value='completed'),
                            error=None,
                        )),
                    )

            return FakeTurn()

    class FakeCodex:
        def __init__(self, _config: Any) -> None:
            return None

        async def __aenter__(self) -> 'FakeCodex':
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def thread_start(self, **_kwargs: Any) -> FakeThread:
            raise AssertionError('fork must not start an unrelated thread')

        async def thread_resume(self, *_args: Any, **_kwargs: Any) -> FakeThread:
            raise AssertionError('follow-up must fork instead of mutating the parent thread')

        async def thread_fork(self, thread_id: str, **kwargs: Any) -> FakeThread:
            observed.update(thread_id=thread_id, kwargs=kwargs)
            return FakeThread()

    monkeypatch.setattr(openai_codex, 'AsyncCodex', FakeCodex)
    monkeypatch.setenv('CODEX_HOME', str(tmp_path.joinpath('codex-home')))
    monkeypatch.chdir(tmp_path)
    bridge, bridge_path = _dummy_codex_bridge(tmp_path)
    response = await codex_worker.run_request({
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
        'operation': 'generate',
        'model': 'gpt-5.6-terra',
        'prompt': '继续生成',
        'sourceProjection': None,
        'externalSessionId': CODEX_THREAD_ID,
        'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
        'bridgeSocket': bridge_path,
        'bridgeTokenFile': str(tmp_path.joinpath('capability')),
        'allowedTools': list(codex_worker.ALLOWED_TOOL_NAMES),
    })
    bridge.close()

    assert observed['thread_id'] == CODEX_THREAD_ID
    assert observed['kwargs']['ephemeral'] is False
    assert observed['kwargs']['sandbox'] is openai_codex.Sandbox.read_only
    assert response['externalSessionId'] == CODEX_SECOND_THREAD_ID
    assert response['usage']['budgetEnforcement'] == 'post_run_estimate'


@pytest.mark.asyncio
async def test_codex_worker_rejects_a_fork_that_reuses_the_parent_thread_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeCodex:
        def __init__(self, _config: Any) -> None:
            return None

        async def __aenter__(self) -> 'FakeCodex':
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def thread_fork(self, _thread_id: str, **_kwargs: Any) -> Any:
            return SimpleNamespace(id=CODEX_THREAD_ID)

    monkeypatch.setattr(openai_codex, 'AsyncCodex', FakeCodex)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('CODEX_HOME', str(tmp_path.joinpath('codex-home')))
    monkeypatch.chdir(tmp_path)

    bridge, bridge_path = _dummy_codex_bridge(tmp_path)
    with pytest.raises(codex_worker.WorkerFailure) as error:
        await codex_worker.run_request({
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'operation': 'generate',
            'model': 'gpt-5.6-terra',
            'prompt': '继续生成',
            'sourceProjection': None,
            'externalSessionId': CODEX_THREAD_ID,
            'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
            'bridgeSocket': bridge_path,
            'bridgeTokenFile': str(tmp_path.joinpath('capability')),
            'allowedTools': list(codex_worker.ALLOWED_TOOL_NAMES),
        })
    bridge.close()
    assert error.value.code == 'AI_SESSION_UNAVAILABLE'


def test_codex_worker_environment_is_an_explicit_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv('DB_PASSWORD', 'database-secret')
    monkeypatch.setenv('JWT_SECRET_KEY', 'jwt-secret')
    monkeypatch.setenv('REDIS_PASSWORD', 'redis-secret')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'other-provider-secret')
    monkeypatch.setenv('OPENAI_API_KEY', 'ambient-openai-secret')
    isolation_root = tmp_path.joinpath('isolation')
    codex_home = isolation_root.joinpath('codex-home')
    codex_home.mkdir(parents=True)

    environment = _build_worker_environment(
        isolation_root,
        codex_home,
        {'OPENAI_API_KEY': 'connector-secret'},
    )

    assert environment['OPENAI_API_KEY'] == 'connector-secret'
    assert environment['CODEX_HOME'] == str(codex_home)
    assert environment['HOME'].startswith(str(isolation_root))
    assert not {
        'DB_PASSWORD', 'JWT_SECRET_KEY', 'REDIS_PASSWORD', 'ANTHROPIC_API_KEY',
    } & set(environment)
    assert 'ambient-openai-secret' not in environment.values()


def test_codex_worker_fails_closed_for_new_bundled_skill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    codex_home = tmp_path.joinpath('codex-home')
    codex_home.joinpath('skills', '.system', 'future-dangerous-skill').mkdir(parents=True)
    monkeypatch.setenv('CODEX_HOME', str(codex_home))

    with pytest.raises(codex_worker.WorkerFailure) as error:
        codex_worker._assert_no_unconfigured_bundled_skills()
    assert error.value.code == 'AI_AGENT_UNAVAILABLE'


def test_codex_local_auth_staging_copies_only_auth_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_home = tmp_path.joinpath('source-codex')
    source_home.mkdir()
    source_home.joinpath('auth.json').write_text('{"tokens":{"access_token":"secret"}}')
    source_home.joinpath('config.toml').write_text('[mcp_servers.unsafe]')
    source_home.joinpath('history.jsonl').write_text('private history')
    source_home.joinpath('skills').mkdir()
    monkeypatch.setenv('CODEX_HOME', str(source_home))
    isolated_home = tmp_path.joinpath('isolated-codex')

    assert _stage_local_codex_auth(isolated_home) is True
    assert {item.name for item in isolated_home.iterdir()} == {'auth.json'}
    assert isolated_home.joinpath('auth.json').read_text() == (
        '{"tokens":{"access_token":"secret"}}'
    )


def test_codex_worker_error_does_not_relay_private_provider_message() -> None:
    response = json.dumps({
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
        'ok': False,
        'error': {
            'code': 'AI_PROVIDER_AUTH_FAILED',
            'message': 'private prompt and sk-secret must never escape',
        },
    }).encode()

    with pytest.raises(MindmapArtifactError) as error:
        _decode_worker_response(response, 0)
    assert error.value.code == 'AI_PROVIDER_AUTH_FAILED'
    assert 'private prompt' not in str(error.value)
    assert 'sk-secret' not in str(error.value)


def test_codex_worker_unknown_internal_code_fails_as_availability_error() -> None:
    error = codex_worker.WorkerFailure('PRIVATE_INTERNAL_FAILURE')

    assert error.code == 'AI_AGENT_UNAVAILABLE'
    assert 'PRIVATE_INTERNAL_FAILURE' not in str(error)


def test_worker_error_message_keys_in_sync() -> None:
    assert (
        set(codex_adapter_module._WORKER_ERROR_MESSAGES)
        == set(codex_worker._PUBLIC_ERROR_MESSAGES)
    )


@pytest.mark.parametrize(('patch', 'expected_code'), [
    ({'protocolVersion': 0}, 'AI_AGENT_UNAVAILABLE'),
    ({'operation': 'unknown'}, 'AI_AGENT_UNAVAILABLE'),
    ({'prompt': ''}, 'AI_AGENT_UNAVAILABLE'),
    ({'sourceProjection': []}, 'AI_AGENT_UNAVAILABLE'),
    ({'externalSessionId': '../../foreign-thread'}, 'AI_SESSION_UNAVAILABLE'),
    ({'maxBudgetUsd': 0}, 'AI_BUDGET_EXCEEDED'),
    ({'maxBudgetUsd': float('nan')}, 'AI_BUDGET_EXCEEDED'),
    ({'bridgeSocket': 'relative.sock'}, 'AI_AGENT_UNAVAILABLE'),
    ({'bridgeTokenFile': 'relative-token'}, 'AI_AGENT_UNAVAILABLE'),
    ({'allowedTools': ['read_projection']}, 'AI_CAPABILITY_UNSUPPORTED'),
])
def test_codex_worker_parent_request_failures_are_not_model_output_errors(
    patch: dict[str, Any],
    expected_code: str,
) -> None:
    request = {
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
        'operation': 'generate',
        'model': 'gpt-5.6-terra',
        'prompt': '受控提示',
        'sourceProjection': None,
        'externalSessionId': None,
        'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
        'bridgeSocket': '/private/tmp/mindmap.sock',
        'bridgeTokenFile': '/private/tmp/mindmap-token',
        'allowedTools': list(codex_worker.ALLOWED_TOOL_NAMES),
    }

    with pytest.raises(codex_worker.WorkerFailure) as error:
        codex_worker._validated_request({**request, **patch})

    assert error.value.code == expected_code
    assert error.value.code != 'AI_OUTPUT_INVALID'


@pytest.mark.parametrize(('raw_request', 'expected_code'), [
    (b'{not-json', 'AI_AGENT_UNAVAILABLE'),
    (b'\xff', 'AI_AGENT_UNAVAILABLE'),
    (b'x' * (codex_worker.MAX_WORKER_REQUEST_BYTES + 1), 'AI_INPUT_TOO_LARGE'),
])
def test_codex_worker_wire_request_failures_are_not_model_output_errors(
    raw_request: bytes,
    expected_code: str,
) -> None:
    with pytest.raises(codex_worker.WorkerFailure) as error:
        codex_worker._decode_worker_request(raw_request)

    assert error.value.code == expected_code
    assert error.value.code != 'AI_OUTPUT_INVALID'


def test_codex_worker_internal_progress_contract_failure_is_unavailable() -> None:
    with pytest.raises(codex_worker.WorkerFailure) as error:
        codex_worker._emit_progress(lambda *_args: None, 'private-stage', 10)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'


def test_codex_worker_distinguishes_bridge_runtime_from_model_tool_failure() -> None:
    runtime_failure = SimpleNamespace(root=SimpleNamespace(
        type='mcpToolCall',
        status=SimpleNamespace(value='failed'),
        error=SimpleNamespace(
            message=(
                'MCP error -32603: '
                f'{codex_worker.MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER}'
            ),
        ),
    ))
    model_tool_failure = SimpleNamespace(root=SimpleNamespace(
        type='mcpToolCall',
        status=SimpleNamespace(value='failed'),
        error=SimpleNamespace(message='invalid tool arguments'),
    ))

    assert codex_worker._is_mindmap_bridge_runtime_failure(runtime_failure) is True
    assert codex_worker._is_mindmap_bridge_runtime_failure(model_tool_failure) is False


@pytest.mark.asyncio
async def test_codex_worker_maps_tagged_bridge_runtime_item_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = 'private bridge failure detail'

    class FakeThread:
        id = CODEX_THREAD_ID

        async def turn(self, _run_input: Any, **_kwargs: Any) -> Any:
            class FakeTurn:
                id = 'turn-bridge-failed'

                async def stream(self) -> Any:
                    yield SimpleNamespace(
                        method='item/completed',
                        payload=SimpleNamespace(
                            turn_id=self.id,
                            item=SimpleNamespace(root=SimpleNamespace(
                                type='mcpToolCall',
                                status=SimpleNamespace(value='failed'),
                                error=SimpleNamespace(message=(
                                    'MCP error -32603: '
                                    f'{codex_worker.MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER} '
                                    f'{secret}'
                                )),
                            )),
                        ),
                    )

            return FakeTurn()

    class FakeCodex:
        def __init__(self, _config: Any) -> None:
            return None

        async def __aenter__(self) -> 'FakeCodex':
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def thread_start(self, **_kwargs: Any) -> FakeThread:
            return FakeThread()

    monkeypatch.setattr(openai_codex, 'AsyncCodex', FakeCodex)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('CODEX_HOME', str(tmp_path.joinpath('codex-home')))
    monkeypatch.chdir(tmp_path)
    bridge, bridge_path = _dummy_codex_bridge(tmp_path)

    with pytest.raises(codex_worker.WorkerFailure) as error:
        await codex_worker.run_request({
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'operation': 'generate',
            'model': 'gpt-5.6-terra',
            'prompt': '受控提示',
            'sourceProjection': None,
            'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
            'bridgeSocket': bridge_path,
            'bridgeTokenFile': str(tmp_path.joinpath('capability')),
            'allowedTools': list(codex_worker.ALLOWED_TOOL_NAMES),
        })

    bridge.close()
    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert secret not in str(error.value)


def test_codex_bridge_internal_failure_is_sanitized_and_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = 'private socket path and credential fragment'

    def fail_internally(
        _proxy: Any,
        _request: dict[str, Any],
    ) -> dict[str, Any]:
        raise OSError(secret)

    monkeypatch.setattr(codex_mcp_bridge.CodexMindmapMcpProxy, 'handle', fail_internally)
    stdout = StringIO()

    result = codex_mcp_bridge.serve(
        Path('/private/tmp/mindmap.sock'),
        'a' * codex_mcp_bridge.MIN_CAPABILITY_TOKEN_LENGTH,
        ('read_projection',),
        stdin=StringIO('{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'),
        stdout=stdout,
    )

    response = json.loads(stdout.getvalue())
    assert result == 0
    assert response['id'] == 1
    assert response['error'] == {
        'code': -32603,
        'message': codex_mcp_bridge.MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER,
    }
    assert secret not in stdout.getvalue()
    assert (
        codex_mcp_bridge.MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER
        == codex_worker.MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER
    )


def test_codex_bridge_unknown_rpc_method_is_runtime_unavailable() -> None:
    proxy = codex_mcp_bridge.CodexMindmapMcpProxy(
        Path('/private/tmp/mindmap.sock'),
        'a' * codex_mcp_bridge.MIN_CAPABILITY_TOKEN_LENGTH,
        ('read_projection',),
    )

    response = proxy.handle({
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'unsupported/sdk-method',
    })

    assert response == {
        'jsonrpc': '2.0',
        'id': 1,
        'error': {
            'code': -32601,
            'message': codex_mcp_bridge.MINDMAP_BRIDGE_RUNTIME_ERROR_MARKER,
        },
    }


def test_codex_bridge_oversized_model_tool_request_is_output_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex_mcp_bridge, 'MAX_BRIDGE_MESSAGE_BYTES', 1)

    with pytest.raises(codex_mcp_bridge.ModelToolProtocolError) as error:
        codex_mcp_bridge._call_parent(
            Path('/private/tmp/not-opened.sock'),
            'a' * codex_mcp_bridge.MIN_CAPABILITY_TOKEN_LENGTH,
            'add_nodes',
            {'nodes': [{'parentUid': 'root', 'text': 'x'}]},
        )

    assert str(error.value) == codex_mcp_bridge.MODEL_TOOL_PROTOCOL_ERROR_MESSAGE
    assert 'AI_OUTPUT_INVALID' in str(error.value)


def test_codex_worker_stream_decoder_handles_fragmented_ndjson() -> None:
    event = json.dumps({
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
        'type': 'event',
        'event': {
            'stage': 'usage_updated',
            'progress': 65,
            'usage': {'inputTokens': 10, 'outputTokens': 5, 'totalTokens': 15},
        },
    }, separators=(',', ':')).encode()
    result = json.dumps({
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
        'type': 'result',
        'ok': True,
        'result': _codex_plan(),
    }, separators=(',', ':')).encode()
    wire = event + b'\n' + result + b'\n'
    decoder = _WorkerStreamDecoder()
    messages: list[bytes] = []
    for offset in range(0, len(wire), 7):
        messages.extend(decoder.feed(wire[offset:offset + 7]))
    messages.extend(decoder.finish())

    assert len(messages) == EXPECTED_STREAM_MESSAGE_COUNT
    assert _decode_worker_progress(messages[0]) == {
        'stage': 'usage_updated',
        'progress': 65,
        'usage': {'inputTokens': 10, 'outputTokens': 5, 'totalTokens': 15},
    }
    assert _decode_worker_response(messages[1], 0)['result'] == _codex_plan()


@pytest.mark.parametrize('event', [
    {'stage': 'reasoning_delta', 'progress': 30},
    {'stage': 'model_processing', 'progress': 30, 'reasoning': 'private chain'},
    {'stage': 'model_processing', 'progress': 101},
    {'stage': 'usage_updated', 'progress': 65, 'usage': {'reasoningTokens': 500}},
])
def test_codex_worker_rejects_non_allowlisted_progress(event: dict[str, Any]) -> None:
    raw = json.dumps({
        'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
        'type': 'event',
        'event': event,
    }).encode()

    with pytest.raises(MindmapArtifactError, match='事件无效'):
        _decode_worker_progress(raw)


def test_codex_worker_stream_decoder_enforces_total_response_limit() -> None:
    decoder = _WorkerStreamDecoder()
    with pytest.raises(MindmapArtifactError) as error:
        decoder.feed(b'x' * (codex_worker.MAX_WORKER_RESPONSE_BYTES + 1))
    assert error.value.code == 'AI_AGENT_UNAVAILABLE'


@pytest.mark.asyncio
async def test_codex_adapter_cancel_terminates_helper_and_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CodexMindmapAdapter()
    task = asyncio.create_task(asyncio.sleep(60))
    process = SimpleNamespace(returncode=None)
    terminated: list[Any] = []

    async def fake_terminate(candidate: Any) -> None:
        terminated.append(candidate)

    monkeypatch.setattr(adapter, '_terminate_worker', fake_terminate)
    adapter._tasks['job-cancel'] = task
    adapter._processes['job-cancel'] = process  # type: ignore[assignment]

    assert await adapter.cancel('job-cancel') is True
    assert terminated == [process]
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.parametrize(('provider_error', 'expected_code'), [
    ('401 unauthorized', 'AI_PROVIDER_AUTH_FAILED'),
    ('HTTP 429 rate limit', 'AI_RATE_LIMITED'),
    ('contextWindowExceeded', 'AI_INPUT_TOO_LARGE'),
    ('sessionBudgetExceeded', 'AI_BUDGET_EXCEEDED'),
    ('ThreadNotFoundError: rollout not found', 'AI_SESSION_UNAVAILABLE'),
    ('sandbox permission denied', 'AI_SANDBOX_VIOLATION'),
    ('response stream connection failed', 'AI_AGENT_UNAVAILABLE'),
])
def test_codex_worker_maps_provider_failures_to_public_error_codes(
    provider_error: str,
    expected_code: str,
) -> None:
    classified = codex_worker._classify_sdk_failure(RuntimeError(provider_error))
    assert classified.code == expected_code
    assert provider_error not in str(classified)


def test_codex_budget_estimate_is_fail_closed() -> None:
    usage = {
        'inputTokens': 10,
        'cachedInputTokens': 2,
        'cacheWriteInputTokens': 1,
        'outputTokens': 5,
        'totalTokens': 15,
    }

    estimated = codex_worker._usage_with_estimated_cost(
        usage,
        model='gpt-5.6-terra',
        max_budget_usd=EXPECTED_POLICY_BUDGET,
    )
    assert estimated == _codex_usage()

    with pytest.raises(codex_worker.WorkerFailure) as over_budget:
        codex_worker._usage_with_estimated_cost(
            usage,
            model='gpt-5.6-terra',
            max_budget_usd=0.00001,
        )
    assert over_budget.value.code == 'AI_BUDGET_EXCEEDED'

    with pytest.raises(codex_worker.WorkerFailure) as incomplete:
        codex_worker._usage_with_estimated_cost(
            {'inputTokens': 10},
            model='gpt-5.6-terra',
            max_budget_usd=EXPECTED_POLICY_BUDGET,
        )
    assert incomplete.value.code == 'AI_BUDGET_EXCEEDED'


def test_codex_budget_estimate_applies_terra_long_context_tier() -> None:
    estimated = codex_worker._usage_with_estimated_cost(
        {
            'inputTokens': 272_001,
            'cachedInputTokens': 0,
            'cacheWriteInputTokens': 0,
            'outputTokens': 10,
            'totalTokens': 272_011,
        },
        model='gpt-5.6-terra',
        max_budget_usd=EXPECTED_POLICY_BUDGET,
    )

    assert estimated['totalCostUsd'] == EXPECTED_LONG_CONTEXT_COST


def test_codex_unknown_pricing_model_is_rejected_before_sdk_call() -> None:
    with pytest.raises(codex_worker.WorkerFailure) as error:
        codex_worker._validated_request({
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'operation': 'generate',
            'model': 'unpriced-future-model',
            'prompt': '受控提示',
            'sourceProjection': None,
            'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
        })
    assert error.value.code == 'AI_CAPABILITY_UNSUPPORTED'


@pytest.mark.parametrize('usage_patch', [
    {'totalCostUsd': 0.0},
    {'totalTokens': EXPECTED_TOTAL_TOKENS - 1},
    {'cachedInputTokens': 11},
])
def test_codex_adapter_independently_rejects_unverifiable_worker_usage(
    usage_patch: dict[str, Any],
) -> None:
    usage = {**_codex_usage(), **usage_patch}

    with pytest.raises(MindmapArtifactError) as error:
        _validated_worker_usage(
            {'usage': usage},
            model_ref='gpt-5.6-terra',
            max_budget_usd=EXPECTED_POLICY_BUDGET,
        )

    assert error.value.code == 'AI_BUDGET_EXCEEDED'


@pytest.mark.asyncio
async def test_codex_adapter_rejects_forged_thread_id_before_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = CodexMindmapAdapter(session_storage_root=tmp_path.joinpath('sessions'))
    invoke_worker = AsyncMock()
    monkeypatch.setattr(adapter, '_invoke_worker', invoke_worker)
    context = _context()
    context.external_session_id = '../../foreign-thread'
    context.metadata['credentialEnv'] = {'OPENAI_API_KEY': 'connector-secret'}

    with pytest.raises(MindmapArtifactError) as error:
        await adapter.resume(context, _ignore_event)

    assert error.value.code == 'AI_SESSION_UNAVAILABLE'
    invoke_worker.assert_not_awaited()


def test_codex_session_snapshot_excludes_auth_restores_and_expires(tmp_path: Path) -> None:
    codex_home = tmp_path.joinpath('codex-home')
    rollout = codex_home.joinpath(
        'sessions', '2026', '09', '13', f'rollout-{CODEX_THREAD_ID}.jsonl',
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    codex_home.joinpath('auth.json').write_text('secret', encoding='utf-8')
    storage_root = tmp_path.joinpath('session-store')

    _save_session_snapshot(
        storage_root,
        codex_home,
        CODEX_THREAD_ID,
        retention_days=1,
    )
    archive_path, metadata_path = _session_snapshot_paths(storage_root, CODEX_THREAD_ID)
    assert storage_root.stat().st_mode & 0o777 == PRIVATE_DIRECTORY_MODE
    assert archive_path.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    assert metadata_path.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    with zipfile.ZipFile(archive_path) as archive:
        assert 'auth.json' not in archive.namelist()

    restored_home = tmp_path.joinpath('restored-home')
    _restore_session_snapshot(storage_root, restored_home, CODEX_THREAD_ID)
    assert list(restored_home.glob('sessions/**/*.jsonl'))
    assert not restored_home.joinpath('auth.json').exists()

    metadata_value = json.loads(metadata_path.read_text(encoding='utf-8'))
    metadata_value['expiresAt'] = time.time() - 1
    metadata_path.write_text(json.dumps(metadata_value), encoding='utf-8')
    assert _cleanup_expired_session_snapshots(storage_root) == 1
    assert not archive_path.exists()
    assert not metadata_path.exists()


def test_codex_session_snapshot_does_not_shorten_existing_retention(tmp_path: Path) -> None:
    codex_home = tmp_path.joinpath('codex-home')
    rollout = codex_home.joinpath(
        'sessions', '2026', '09', '13', f'rollout-{CODEX_THREAD_ID}.jsonl',
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    storage_root = tmp_path.joinpath('session-store')

    _save_session_snapshot(
        storage_root,
        codex_home,
        CODEX_THREAD_ID,
        retention_days=30,
    )
    _archive_path, metadata_path = _session_snapshot_paths(
        storage_root, CODEX_THREAD_ID,
    )
    original_expiry = json.loads(metadata_path.read_text(encoding='utf-8'))['expiresAt']
    _save_session_snapshot(
        storage_root,
        codex_home,
        CODEX_THREAD_ID,
        retention_days=1,
    )

    assert json.loads(metadata_path.read_text(encoding='utf-8'))['expiresAt'] == original_expiry


def test_codex_session_snapshot_cannot_be_relabelled_to_another_thread(tmp_path: Path) -> None:
    codex_home = tmp_path.joinpath('codex-home')
    rollout = codex_home.joinpath(
        'sessions', '2026', '09', '13', f'rollout-{CODEX_THREAD_ID}.jsonl',
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    storage_root = tmp_path.joinpath('session-store')
    _save_session_snapshot(
        storage_root,
        codex_home,
        CODEX_THREAD_ID,
        retention_days=1,
    )
    source_archive, source_metadata = _session_snapshot_paths(
        storage_root, CODEX_THREAD_ID,
    )
    forged_archive, forged_metadata = _session_snapshot_paths(
        storage_root, CODEX_SECOND_THREAD_ID,
    )
    forged_archive.write_bytes(source_archive.read_bytes())
    forged_metadata.write_bytes(source_metadata.read_bytes())

    with pytest.raises(MindmapArtifactError, match='快照无效'):
        _restore_session_snapshot(
            storage_root,
            tmp_path.joinpath('forged-home'),
            CODEX_SECOND_THREAD_ID,
        )


@pytest.mark.asyncio
async def test_codex_worker_rejects_non_json_sdk_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeThread:
        id = CODEX_THREAD_ID

        async def turn(self, _run_input: Any, **_kwargs: Any) -> Any:
            class FakeTurn:
                id = 'turn-invalid'

                async def stream(self) -> Any:
                    yield SimpleNamespace(
                        method='item/completed',
                        payload=SimpleNamespace(
                            turn_id=self.id,
                            item=SimpleNamespace(
                                type='agentMessage',
                                phase=SimpleNamespace(value='final_answer'),
                                text='not structured json',
                            ),
                        ),
                    )
                    yield SimpleNamespace(
                        method='turn/completed',
                        payload=SimpleNamespace(turn=SimpleNamespace(
                            id=self.id,
                            status=SimpleNamespace(value='completed'),
                            error=None,
                        )),
                    )

            return FakeTurn()

    class FakeCodex:
        def __init__(self, _config: Any) -> None:
            return None

        async def __aenter__(self) -> 'FakeCodex':
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def thread_start(self, **_kwargs: Any) -> FakeThread:
            return FakeThread()

    monkeypatch.setattr(openai_codex, 'AsyncCodex', FakeCodex)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('CODEX_HOME', str(tmp_path.joinpath('codex-home')))
    monkeypatch.chdir(tmp_path)
    bridge, bridge_path = _dummy_codex_bridge(tmp_path)
    with pytest.raises(codex_worker.WorkerFailure) as error:
        await codex_worker.run_request({
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'operation': 'generate',
            'model': 'gpt-5.6-terra',
            'prompt': '受控提示',
            'sourceProjection': None,
            'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
            'bridgeSocket': bridge_path,
            'bridgeTokenFile': str(tmp_path.joinpath('capability')),
            'allowedTools': list(codex_worker.ALLOWED_TOOL_NAMES),
        })
    bridge.close()
    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_codex_bridge_returns_tool_error_for_malformed_arguments() -> None:
    context = _context()
    context.parameters['layout'] = 'fishbone'
    events: list[tuple[str, dict[str, Any]]] = []

    async def collect(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    executor = _CodexToolExecutionBridge(
        context, collect, codex_worker.ALLOWED_TOOL_NAMES,
    )
    assert (await executor.call('start_document', {
        'title': '订单系统', 'layout': 'logicalStructure',
    }))['ok'] is True
    assert context.tool_service.read_projection()['layout'] == 'fishbone'
    response = await executor.call('add_nodes', {})

    assert response['ok'] is False
    assert events[-1][0] == 'tool_failed'
    assert events[-1][1]['toolName'] == 'add_nodes'


@pytest.mark.parametrize('arguments', [
    {'nodes': [{'nodeUid': 'root', 'text': '电商平台购物车功能测试用例'}]},
    {'updates': [{'uid': 'root', 'text': '电商平台购物车功能测试用例'}]},
    {'nodeId': 'root', 'patch': {'text': '电商平台购物车功能测试用例'}},
    {'updates': {
        'node_id': 'root',
        'data': {'text': '电商平台购物车功能测试用例'},
    }},
])
@pytest.mark.asyncio
async def test_codex_bridge_normalizes_legacy_update_nodes_shape(
    arguments: dict[str, Any],
) -> None:
    source = {
        'root': {'data': {'uid': 'root', 'text': '旧标题'}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }
    context = _context()
    context.source_document = source
    context.tool_service = MindmapToolService(base_document=source)

    events: list[tuple[str, dict[str, Any]]] = []

    async def collect(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    executor = _CodexToolExecutionBridge(
        context, collect, codex_worker.ALLOWED_TOOL_NAMES,
    )
    response = await executor.call('update_nodes', arguments)

    assert response['ok'] is True
    assert context.tool_service.read_projection()['root']['data']['text'] == (
        '电商平台购物车功能测试用例'
    )
    assert [event_type for event_type, _payload in events] == [
        'tool_started', 'draft_changed', 'tool_completed',
    ]
    assert events[1][1]['operations'][0]['payload']['set']['text'] == (
        '电商平台购物车功能测试用例'
    )


@pytest.mark.asyncio
async def test_codex_bridge_accepts_nested_uid_and_rejects_conflicting_batch_atomically() -> None:
    source = {
        'root': {'data': {'uid': 'root', 'text': '旧标题'}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }
    context = _context()
    context.source_document = source
    context.tool_service = MindmapToolService(base_document=source)
    executor = _CodexToolExecutionBridge(
        context, _ignore_event, codex_worker.ALLOWED_TOOL_NAMES,
    )

    accepted = await executor.call('update_nodes', {
        'data': {'nodeUid': 'root', 'text': '嵌套 UID 已兼容'},
    })
    before_conflict = context.tool_service.read_projection()
    before_cursor = context.tool_service.operation_cursor()
    rejected = await executor.call('update_nodes', {'updates': [
        {'data': {'uid': 'root', 'text': '不应写入'}},
        {
            'nodeUid': 'root',
            'data': {'nodeUid': 'different-node', 'text': '冲突'},
        },
    ]})

    assert accepted['ok'] is True
    assert before_conflict['root']['data']['text'] == '嵌套 UID 已兼容'
    assert rejected['ok'] is False
    assert 'UID 冲突' in rejected['error']['message']
    assert context.tool_service.read_projection() == before_conflict
    assert context.tool_service.operation_cursor() == before_cursor


@pytest.mark.asyncio
async def test_codex_bridge_commits_only_successful_incremental_calls() -> None:
    context = _context()
    executor = _CodexToolExecutionBridge(
        context, _ignore_event, codex_worker.ALLOWED_TOOL_NAMES,
    )

    started = await executor.call('start_document', {
        'title': '已实时提交', 'layout': 'logicalStructure',
    })
    failed = await executor.call('add_nodes', {})

    assert started['ok'] is True
    assert failed['ok'] is False
    assert context.tool_service.read_projection()['root']['data']['text'] == '已实时提交'


@pytest.mark.asyncio
async def test_codex_bridge_rejects_reused_client_ref_before_any_write() -> None:
    context = _context()
    events: list[tuple[str, dict[str, Any]]] = []

    async def collect(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    executor = _CodexToolExecutionBridge(
        context, collect, codex_worker.ALLOWED_TOOL_NAMES,
    )
    await executor.call('start_document', {
        'title': '订单系统', 'layout': 'logicalStructure',
    })
    await executor.call('add_nodes', {'nodes': [{
        'clientRef': 'stable-ref', 'parentUid': '@root', 'text': '第一个节点',
    }]})
    before_summary = context.tool_service.authorized_scope_summary()
    before_cursor = context.tool_service.operation_cursor()
    before_event_count = len(events)
    before_successful_tools = list(executor.successful_tools)

    rejected = await executor.call('add_nodes', {'nodes': [{
        'clientRef': 'stable-ref', 'parentUid': '@root', 'text': '隐藏脏节点',
    }]})

    assert rejected['ok'] is False
    assert context.tool_service.authorized_scope_summary() == before_summary
    assert context.tool_service.operation_cursor() == before_cursor
    assert executor.successful_tools == before_successful_tools
    assert [event_type for event_type, _payload in events[before_event_count:]] == [
        'tool_started', 'tool_failed',
    ]
    assert '隐藏脏节点' not in json.dumps(
        context.tool_service.read_projection(), ensure_ascii=False,
    )


@pytest.mark.parametrize('client_ref', ['', '   ', None, ['not-a-string']])
@pytest.mark.asyncio
async def test_codex_bridge_rejects_invalid_client_ref_before_any_write(
    client_ref: Any,
) -> None:
    context = _context()
    events: list[tuple[str, dict[str, Any]]] = []

    async def collect(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    executor = _CodexToolExecutionBridge(
        context, collect, codex_worker.ALLOWED_TOOL_NAMES,
    )
    await executor.call('start_document', {
        'title': '订单系统', 'layout': 'logicalStructure',
    })
    before_cursor = context.tool_service.operation_cursor()
    before_event_count = len(events)

    rejected = await executor.call('add_nodes', {'nodes': [{
        'clientRef': client_ref, 'parentUid': '@root', 'text': '不得写入',
    }]})

    assert rejected['ok'] is False
    assert context.tool_service.operation_cursor() == before_cursor
    assert context.tool_service.authorized_scope_summary()['nodeCount'] == 1
    assert [event_type for event_type, _payload in events[before_event_count:]] == [
        'tool_started', 'tool_failed',
    ]


@pytest.mark.asyncio
async def test_codex_bridge_resolves_only_uid_fields_and_same_batch_refs() -> None:
    context = _context()
    executor = _CodexToolExecutionBridge(
        context, _ignore_event, codex_worker.ALLOWED_TOOL_NAMES,
    )

    assert (await executor.call('start_document', {
        'title': '@订单系统', 'layout': 'logicalStructure',
    }))['ok'] is True
    assert (await executor.call('add_nodes', {'nodes': [
            {
                'clientRef': 'parent',
                'parentUid': '@root',
                'text': '@alice',
                'note': '@请保留',
                'tag': ['@smoke'],
            },
            {
                'clientRef': 'child',
                'parentUid': '@parent',
                'text': '@child 也是正文',
            },
        ]}))['ok'] is True
    assert (await executor.call('update_nodes', {
            'nodeUid': '@child',
            'patch': {'text': '@updated', 'note': '@mention'},
        }))['ok'] is True

    projection = context.tool_service.read_projection()
    parent = projection['root']['children'][0]
    child = parent['children'][0]
    assert projection['root']['data']['text'] == '@订单系统'
    assert parent['data']['text'] == '@alice'
    assert parent['data']['note'] == '@请保留'
    assert parent['data']['tag'] == ['@smoke']
    assert child['data']['text'] == '@updated'
    assert child['data']['note'] == '@mention'


@pytest.mark.asyncio
async def test_codex_adapter_restores_persisted_sdk_session_across_requests(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requests: list[dict[str, Any]] = []
    bridge_state = _install_inprocess_codex_bridge(monkeypatch)

    async def fake_invoke(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        requests.append(request)
        codex_home = Path(kwargs['environment']['CODEX_HOME'])
        restored_rollouts = list(codex_home.glob('sessions/**/*.jsonl'))  # noqa: ASYNC240
        if len(requests) == 1:
            assert not restored_rollouts
            await _execute_codex_plan_inprocess(bridge_state['executor'])
            result = _codex_plan()
        else:
            assert request['externalSessionId'] == CODEX_THREAD_ID
            assert restored_rollouts
            assert 'session_meta' in restored_rollouts[0].read_text(encoding='utf-8')
            executor = bridge_state['executor']
            assert (await executor.call('read_projection', {}))['ok'] is True
            assert (await executor.call('validate_draft', {}))['ok'] is True
            assert (await executor.call('complete_artifact', {}))['ok'] is True
            result = _codex_plan('续写订单')
        returned_thread_id = (
            CODEX_THREAD_ID if len(requests) == 1 else CODEX_SECOND_THREAD_ID
        )
        _write_fake_codex_rollout(kwargs, returned_thread_id)
        return {
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'ok': True,
            'result': result,
            'externalSessionId': returned_thread_id,
            'usage': _codex_usage(),
        }

    session_storage_root = tmp_path.joinpath('sessions')
    first_adapter = CodexMindmapAdapter(session_storage_root=session_storage_root)
    monkeypatch.setattr(first_adapter, '_invoke_worker', fake_invoke)
    first_context = _context()
    first_context.metadata['credentialEnv'] = {'OPENAI_API_KEY': 'connector-secret'}
    first_result = await first_adapter.start(first_context, _ignore_event)
    parent_archive, parent_metadata = _session_snapshot_paths(
        session_storage_root, CODEX_THREAD_ID,
    )
    parent_archive_before = parent_archive.read_bytes()
    parent_metadata_before = parent_metadata.read_bytes()

    context = _context()
    context.external_session_id = first_result.external_session_id
    context.source_document = first_result.artifact['document']
    context.tool_service = MindmapToolService(base_document=context.source_document)
    context.metadata['credentialEnv'] = {'OPENAI_API_KEY': 'connector-secret'}
    second_adapter = CodexMindmapAdapter(session_storage_root=session_storage_root)
    monkeypatch.setattr(second_adapter, '_invoke_worker', fake_invoke)
    result = await second_adapter.resume(context, _ignore_event)

    assert 'externalSessionId' not in requests[0]
    assert requests[1]['externalSessionId'] == CODEX_THREAD_ID
    assert requests[1]['sourceProjection'] == context.source_document
    assert result.external_session_id == CODEX_SECOND_THREAD_ID
    assert parent_archive.read_bytes() == parent_archive_before
    assert parent_metadata.read_bytes() == parent_metadata_before
    child_archive, _child_metadata = _session_snapshot_paths(
        session_storage_root, CODEX_SECOND_THREAD_ID,
    )
    with zipfile.ZipFile(child_archive) as archive:
        assert archive.namelist()
        assert all(CODEX_SECOND_THREAD_ID in name for name in archive.namelist())
        assert all(CODEX_THREAD_ID not in name for name in archive.namelist())
    restored_child_home = tmp_path.joinpath('restored-child')
    restored_child_home.mkdir()
    _restore_session_snapshot(
        session_storage_root, restored_child_home, CODEX_SECOND_THREAD_ID,
    )
    assert list(restored_child_home.glob(
        f'sessions/**/*{CODEX_SECOND_THREAD_ID}.jsonl',
    ))


def test_codex_worker_completion_schema_is_small_and_tool_history_free() -> None:
    schema = codex_worker._codex_result_schema()
    assert schema['type'] == 'object'
    assert schema['properties']['completionState']['enum'] == [
        'artifact_completed', 'needs_input',
    ]
    assert schema['required'] == ['completionState', 'title', 'questions']
    assert (
        schema['properties']['questions']['maxItems']
        == EXPECTED_MAX_NEEDS_INPUT_QUESTIONS
    )
    assert schema['additionalProperties'] is False
    assert 'actions' not in json.dumps(schema)
    assert 'argumentsJson' not in json.dumps(schema)


@pytest.mark.parametrize('result', [
    {'title': '缺少完成态'},
    {'completionState': 'incomplete', 'title': '错误完成态'},
    {'completionState': 'artifact_completed', 'title': '完成', 'actions': []},
])
def test_codex_worker_rejects_invalid_completion_summary(result: dict[str, Any]) -> None:
    with pytest.raises(codex_worker.WorkerFailure) as error:
        codex_worker._validated_generated_result(
            json.dumps(result),
            codex_worker.ALLOWED_TOOL_NAMES,
        )
    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_codex_bridge_rejects_any_call_after_completion() -> None:
    context = _context()
    events: list[tuple[str, dict[str, Any]]] = []

    async def collect(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    executor = _CodexToolExecutionBridge(
        context, collect, codex_worker.ALLOWED_TOOL_NAMES,
    )
    await _execute_codex_plan_inprocess(executor)

    response = await executor.call('read_projection', {})

    assert response['ok'] is False
    assert executor.post_completion_attempted is True
    assert executor.successful_tools[-1] == 'complete_artifact'
    assert events[-1][0] == 'tool_failed'


@pytest.mark.asyncio
async def test_claude_adapter_disables_builtins_and_uses_mcp_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv('DATABASE_PASSWORD', 'database-secret')
    monkeypatch.setenv('JWT_SECRET', 'jwt-secret')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'ambient-provider-secret')
    monkeypatch.setattr(
        claude_adapter_module,
        '_read_local_claude_profile_environment',
        dict,
    )

    def fake_server(*, name: str, version: str, tools: list[Any]) -> dict[str, Any]:
        captured.update(name=name, version=version, tools=tools)
        return {'type': 'sdk', 'name': name, 'instance': object()}

    async def fake_query(*, prompt: str, options: Any, **_kwargs: Any) -> Any:
        captured.update(prompt=prompt, options=options)
        tools = {item.name: item for item in captured['tools']}
        started = await tools['start_document'].handler({
            'title': '订单系统', 'layout': 'logicalStructure',
        })
        root_uid = json.loads(started['content'][0]['text'])['rootUid']
        await tools['add_nodes'].handler({'nodes': [{
            'parentUid': root_uid, 'text': '创建订单',
        }]})
        await tools['validate_draft'].handler({})
        await tools['complete_artifact'].handler({})
        yield claude_agent_sdk.ResultMessage(
            subtype='success',
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=3,
            session_id=CLAUDE_SESSION_ID,
            usage={'input_tokens': 10},
        )

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.parameters['layout'] = 'fishbone'
    context.metadata.update({
        'modelRef': 'claude-policy-snapshot',
        'maxBudgetUsd': EXPECTED_POLICY_BUDGET,
    })
    result = await ClaudeMindmapAdapter().run(context, _ignore_event)

    assert result.external_session_id == CLAUDE_SESSION_ID
    assert result.external_session_created is True
    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert result.artifact['document']['layout'] == 'fishbone'
    assert captured['options'].tools == []
    assert captured['options'].permission_mode == 'dontAsk'
    assert captured['options'].strict_mcp_config is True
    assert captured['options'].model == 'claude-policy-snapshot'
    assert captured['options'].max_budget_usd == EXPECTED_POLICY_BUDGET
    assert captured['options'].setting_sources == []
    assert captured['options'].skills == []
    assert captured['options'].plugins == []
    assert captured['options'].agents == {}
    assert captured['options'].sandbox == {
        'enabled': True,
        'autoAllowBashIfSandboxed': False,
        'allowUnsandboxedCommands': False,
    }
    assert captured['options'].env['DATABASE_PASSWORD'] == ''
    assert captured['options'].env['JWT_SECRET'] == ''
    assert captured['options'].env['ANTHROPIC_API_KEY'] == ''
    assert {
        name: captured['options'].env[name]
        for name in CLAUDE_FORCED_ISOLATION_ENV
    } == CLAUDE_FORCED_ISOLATION_ENV
    assert all(
        not value
        for key, value in captured['options'].env.items()
        if key not in (
            CLAUDE_RUNTIME_ENV_ALLOWLIST
            | CLAUDE_CREDENTIAL_ENV_ALLOWLIST
            | set(CLAUDE_FORCED_ISOLATION_ENV)
            | {'CLAUDE_CONFIG_DIR'}
        )
    )
    isolated_config = Path(captured['options'].env['CLAUDE_CONFIG_DIR'])
    assert isolated_config.name == 'config'
    assert not isolated_config.exists()  # noqa: ASYNC240
    assert 'Bash' in captured['options'].disallowed_tools
    assert all(name.startswith('mcp__mindmap__') for name in captured['options'].allowed_tools)


@pytest.mark.asyncio
async def test_claude_adapter_coalesces_repeated_sdk_message_envelopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        started = await tools['start_document'].handler({
            'title': '消息收敛测试', 'layout': 'logicalStructure',
        })
        root_uid = json.loads(started['content'][0]['text'])['rootUid']
        await tools['add_nodes'].handler({'nodes': [{
            'parentUid': root_uid, 'text': '可见节点',
        }]})
        await tools['complete_artifact'].handler({})
        hidden = '不得进入审计的模型正文和隐藏推理'
        for _index in range(300):
            yield claude_agent_sdk.SystemMessage(
                subtype='status',
                data={'private': hidden},
            )
        for _index in range(30):
            yield claude_agent_sdk.AssistantMessage(
                content=[claude_agent_sdk.TextBlock(text=hidden)],
                model='test-model',
            )
        for _index in range(20):
            yield claude_agent_sdk.UserMessage(content=hidden)
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)

    await ClaudeMindmapAdapter().run(_context(), collect_event)

    message_events = [payload for event_type, payload in events if event_type == 'agent_event']
    assert message_events == [
        {'stage': 'building', 'messageType': 'SystemMessage'},
        {'stage': 'building', 'messageType': 'AssistantMessage'},
        {'stage': 'building', 'messageType': 'UserMessage'},
    ]
    serialized = json.dumps(events, ensure_ascii=False)
    assert '不得进入审计的模型正文和隐藏推理' not in serialized


@pytest.mark.asyncio
async def test_claude_parallel_tools_are_serialized_without_duplicate_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        started = await tools['start_document'].handler({
            'title': '订单系统', 'layout': 'logicalStructure',
        })
        root_uid = json.loads(started['content'][0]['text'])['rootUid']
        await asyncio.gather(
            tools['update_nodes'].handler({'updates': [{
                'nodeUid': root_uid,
                'patch': {'text': '第一版'},
            }]}),
            tools['update_nodes'].handler({'updates': [{
                'nodeUid': root_uid,
                'patch': {'text': '第二版'},
            }]}),
        )
        await tools['complete_artifact'].handler({})
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        if event_type == 'tool_started' and payload.get('toolName') == 'update_nodes':
            await asyncio.sleep(0.01)
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.metadata['modelRef'] = 'claude-policy-snapshot'

    result = await ClaudeMindmapAdapter().run(context, collect_event)

    assert result.title == '第二版'
    update_events = [
        (event_type, payload)
        for event_type, payload in events
        if payload.get('toolName') == 'update_nodes'
    ]
    assert [event_type for event_type, _payload in update_events] == [
        'tool_started', 'draft_changed', 'tool_completed',
        'tool_started', 'draft_changed', 'tool_completed',
    ]
    update_deltas = [
        payload
        for event_type, payload in update_events
        if event_type == 'draft_changed'
    ]
    assert [payload['operationCursor'] for payload in update_deltas] == [1, 2]
    assert [len(payload['operations']) for payload in update_deltas] == [1, 1]
    assert [
            payload['operations'][0]['payload']['set']['text']
        for payload in update_deltas
    ] == ['第一版', '第二版']


@pytest.mark.asyncio
async def test_claude_complete_waits_for_inflight_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    add_started = asyncio.Event()
    release_add = asyncio.Event()

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        started = await tools['start_document'].handler({
            'title': '订单系统', 'layout': 'logicalStructure',
        })
        root_uid = json.loads(started['content'][0]['text'])['rootUid']
        add_task = asyncio.create_task(tools['add_nodes'].handler({'nodes': [{
            'parentUid': root_uid,
            'text': '必须在冻结前写入',
        }]}))
        await add_started.wait()
        complete_task = asyncio.create_task(tools['complete_artifact'].handler({}))
        await asyncio.sleep(0)
        release_add.set()
        await asyncio.gather(add_task, complete_task)
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    async def coordinate_event(event_type: str, payload: dict[str, Any]) -> None:
        if event_type == 'tool_started' and payload.get('toolName') == 'add_nodes':
            add_started.set()
            await release_add.wait()

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.metadata['modelRef'] = 'claude-policy-snapshot'

    result = await ClaudeMindmapAdapter().run(context, coordinate_event)

    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert result.artifact['document']['root']['children'][0]['data']['text'] == (
        '必须在冻结前写入'
    )


@pytest.mark.asyncio
async def test_claude_requires_explicit_complete_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        started = await tools['start_document'].handler({
            'title': '遗漏收尾的脑图', 'layout': 'logicalStructure',
        })
        root_uid = json.loads(started['content'][0]['text'])['rootUid']
        await tools['add_nodes'].handler({'nodes': [{
            'parentUid': root_uid,
            'text': '已经生成的节点',
        }]})
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.metadata['modelRef'] = 'claude-policy-snapshot'

    with pytest.raises(MindmapArtifactError, match='未显式调用 complete_artifact') as error:
        await ClaudeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_OUTPUT_INVALID'
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_completed'
    ] == ['start_document', 'add_nodes']


@pytest.mark.asyncio
async def test_claude_rejects_any_tool_after_completion_and_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        await tools['start_document'].handler({
            'title': '订单系统', 'layout': 'logicalStructure',
        })
        await tools['complete_artifact'].handler({})
        with pytest.raises(MindmapArtifactError, match='必须是最后一个工具调用'):
            await tools['read_projection'].handler({})
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)

    with pytest.raises(MindmapArtifactError, match='complete_artifact 后继续调用工具'):
        await ClaudeMindmapAdapter().run(_context(), collect_event)

    assert events[-1][0] != 'agent_completed'
    assert [
        payload.get('toolName')
        for event_type, payload in events
        if event_type == 'tool_failed'
    ] == ['read_projection']


@pytest.mark.asyncio
async def test_claude_fallback_without_a_draft_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object(), 'tools': tools}

    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.metadata['modelRef'] = 'claude-policy-snapshot'

    with pytest.raises(MindmapArtifactError, match='未显式调用 complete_artifact'):
        await ClaudeMindmapAdapter().run(context, _ignore_event)


@pytest.mark.asyncio
async def test_claude_adapter_uses_explicit_credential_without_user_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(*, options: Any, **_kwargs: Any) -> Any:
        captured['options'] = options
        tools = {item.name: item for item in captured['tools']}
        await tools['start_document'].handler({'title': '凭据测试', 'layout': 'logicalStructure'})
        await tools['complete_artifact'].handler({})
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    monkeypatch.setattr(
        claude_adapter_module,
        '_read_local_claude_profile_environment',
        lambda: pytest.fail('显式 Connector 凭据不得读取本机 Claude profile'),
    )
    context = _context()
    monkeypatch.setenv('DATABASE_PASSWORD', 'database-secret')
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'server-secret'}
    await ClaudeMindmapAdapter().run(context, _ignore_event)

    assert captured['options'].setting_sources == []
    assert captured['options'].env['ANTHROPIC_API_KEY'] == 'server-secret'
    assert captured['options'].env['DATABASE_PASSWORD'] == ''


def test_claude_local_profile_reads_only_valid_auth_routing_and_model_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'settings.json').write_text(json.dumps({
        'env': {
            'ANTHROPIC_AUTH_TOKEN': 'profile-secret',
            'ANTHROPIC_BASE_URL': 'https://gateway.example.test/anthropic',
            'ANTHROPIC_MODEL': 'gateway-sonnet',
            'ANTHROPIC_DEFAULT_SONNET_MODEL': 'gateway-sonnet',
            'DATABASE_PASSWORD': 'must-not-leak',
        },
        'hooks': {'PreToolUse': [{'command': 'must-not-run'}]},
        'enabledPlugins': {'unsafe-plugin': True},
    }), encoding='utf-8')

    selected = _read_local_claude_profile_environment()

    assert selected == {
        'ANTHROPIC_AUTH_TOKEN': 'profile-secret',
        'ANTHROPIC_BASE_URL': 'https://gateway.example.test/anthropic',
        'ANTHROPIC_MODEL': 'gateway-sonnet',
        'ANTHROPIC_DEFAULT_SONNET_MODEL': 'gateway-sonnet',
    }


def test_claude_local_profile_supports_a_valid_bedrock_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'settings.json').write_text(json.dumps({
        'env': {
            'CLAUDE_CODE_USE_BEDROCK': '1',
            'AWS_PROFILE': 'mindmap-runtime',
            'AWS_REGION': 'ap-southeast-1',
            'AWS_CONFIG_FILE': '/run/secrets/aws/config',
            'AWS_SHARED_CREDENTIALS_FILE': '/run/secrets/aws/credentials',
            'AWS_ENDPOINT_URL': 'https://must-not-pass.example.test',
        },
    }), encoding='utf-8')

    selected = _read_local_claude_profile_environment()

    assert selected == {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_PROFILE': 'mindmap-runtime',
        'AWS_REGION': 'ap-southeast-1',
        'AWS_CONFIG_FILE': '/run/secrets/aws/config',
        'AWS_SHARED_CREDENTIALS_FILE': '/run/secrets/aws/credentials',
    }
    assert 'AWS_ENDPOINT_URL' not in selected


def test_claude_local_profile_rejects_mixed_or_incomplete_bedrock_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(json.dumps({'env': {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_ACCESS_KEY_ID': 'access-id',
    }}), encoding='utf-8')
    assert _read_local_claude_profile_environment() == {}

    settings_path.write_text(json.dumps({'env': {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_PROFILE': 'mindmap-runtime',
        'ANTHROPIC_AUTH_TOKEN': 'must-not-mix',
    }}), encoding='utf-8')
    assert _read_local_claude_profile_environment() == {}


@pytest.mark.parametrize('invalid_env', [
    {'ANTHROPIC_AUTH_TOKEN': 123},
    {'ANTHROPIC_AUTH_TOKEN': 'secret\nsecond-line'},
    {
        'ANTHROPIC_AUTH_TOKEN': 'secret',
        'ANTHROPIC_BASE_URL': 'file:///private/collector',
    },
    {'ANTHROPIC_AUTH_TOKEN': 'x' * 65_537},
])
def test_claude_local_profile_rejects_invalid_allowed_values_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalid_env: dict[str, Any],
) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'settings.json').write_text(
        json.dumps({'env': invalid_env}),
        encoding='utf-8',
    )
    assert _read_local_claude_profile_environment() == {}


def test_claude_local_profile_rejects_symlink_and_oversized_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_directory = tmp_path / 'profile'
    profile_directory.mkdir()
    real_settings = tmp_path / 'real-settings.json'
    real_settings.write_text(
        json.dumps({'env': {'ANTHROPIC_API_KEY': 'secret'}}),
        encoding='utf-8',
    )
    (profile_directory / 'settings.json').symlink_to(real_settings)
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(profile_directory))
    assert _read_local_claude_profile_environment() == {}

    (profile_directory / 'settings.json').unlink()
    (profile_directory / 'settings.json').write_bytes(b'x' * 1_048_577)
    assert _read_local_claude_profile_environment() == {}


@pytest.mark.parametrize('raw_settings', [
    b'not-json',
    b'[]',
    b'{"env":[]}',
    b'{"env":{"ANTHROPIC_BASE_URL":"https://gateway.example.test"}}',
])
def test_claude_local_profile_rejects_malformed_or_incomplete_documents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_settings: bytes,
) -> None:
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'settings.json').write_bytes(raw_settings)
    assert _read_local_claude_profile_environment() == {}


def test_claude_runtime_resolves_local_profile_without_ambient_secret_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('DATABASE_PASSWORD', 'must-not-leak')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'ambient-provider-secret')
    monkeypatch.setattr(
        claude_adapter_module,
        '_read_local_claude_profile_environment',
        lambda: {
            'ANTHROPIC_AUTH_TOKEN': 'profile-secret',
            'ANTHROPIC_BASE_URL': 'https://gateway.example.test/anthropic',
            'ANTHROPIC_MODEL': 'gateway-sonnet',
        },
    )

    environment = _resolve_claude_environment({})

    assert environment['ANTHROPIC_AUTH_TOKEN'] == 'profile-secret'
    assert environment['ANTHROPIC_BASE_URL'] == 'https://gateway.example.test/anthropic'
    assert environment['ANTHROPIC_MODEL'] == 'gateway-sonnet'
    assert environment['ANTHROPIC_API_KEY'] == ''
    assert environment['DATABASE_PASSWORD'] == ''
    assert {
        name: environment[name]
        for name in CLAUDE_FORCED_ISOLATION_ENV
    } == CLAUDE_FORCED_ISOLATION_ENV


def test_claude_runtime_accepts_complete_bedrock_credentials_and_scrubs_ambient_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('DATABASE_PASSWORD', 'must-not-leak')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'ambient-provider-secret')

    environment = _resolve_claude_environment({
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_ACCESS_KEY_ID': 'access-id',
        'AWS_SECRET_ACCESS_KEY': 'secret-key',
        'AWS_SESSION_TOKEN': 'session-token',
        'AWS_REGION': 'us-east-1',
    })

    assert environment['CLAUDE_CODE_USE_BEDROCK'] == '1'
    assert environment['AWS_ACCESS_KEY_ID'] == 'access-id'
    assert environment['AWS_SECRET_ACCESS_KEY'] == 'secret-key'
    assert environment['AWS_SESSION_TOKEN'] == 'session-token'
    assert environment['AWS_REGION'] == 'us-east-1'
    assert environment['ANTHROPIC_API_KEY'] == ''
    assert environment['DATABASE_PASSWORD'] == ''


@pytest.mark.parametrize('credential_env', [
    {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_ACCESS_KEY_ID': 'access-id',
    },
    {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_WEB_IDENTITY_TOKEN_FILE': '/var/run/secrets/aws/token',
    },
    {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_PROFILE': '../unsafe-profile',
    },
    {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_PROFILE': 'mindmap-runtime',
        'ANTHROPIC_AUTH_TOKEN': 'mixed-provider-secret',
    },
    {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_CONTAINER_CREDENTIALS_FULL_URI': 'https://attacker.example.test/credentials',
    },
])
def test_claude_runtime_rejects_invalid_bedrock_credential_sets(
    credential_env: dict[str, str],
) -> None:
    secret_values = tuple(credential_env.values())

    with pytest.raises(MindmapArtifactError) as error:
        _resolve_claude_environment(credential_env)

    assert error.value.code == 'AI_PROVIDER_AUTH_FAILED'
    assert all(value not in str(error.value) for value in secret_values)


@pytest.mark.asyncio
async def test_claude_healthcheck_uses_the_same_isolated_connector_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeProcess:
        returncode = 0

        @staticmethod
        async def communicate() -> tuple[bytes, bytes]:
            return b'{"loggedIn":true}', b''

    async def fake_subprocess(*args: Any, **kwargs: Any) -> FakeProcess:
        captured.update(args=args, kwargs=kwargs)
        return FakeProcess()

    async def fake_query(*, options: Any, **_kwargs: Any) -> Any:
        captured['probe_options'] = options
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id='health-session', usage={}, result='OK',
        )

    monkeypatch.setattr(
        claude_adapter_module,
        '_read_local_claude_profile_environment',
        lambda: pytest.fail('显式 Connector 凭据不得读取本机 Claude profile'),
    )
    monkeypatch.setattr(
        claude_adapter_module.asyncio,
        'create_subprocess_exec',
        fake_subprocess,
    )
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)

    healthy, reason = await ClaudeMindmapAdapter().healthcheck({
        'ANTHROPIC_AUTH_TOKEN': 'connector-secret',
    }, model_ref='haiku')

    assert healthy is True
    assert reason is None
    assert '--setting-sources=' in captured['args']
    assert captured['kwargs']['env']['ANTHROPIC_AUTH_TOKEN'] == 'connector-secret'
    assert captured['kwargs']['env']['ENABLE_CLAUDEAI_MCP_SERVERS'] == 'false'
    assert captured['probe_options'].model == 'haiku'
    assert captured['probe_options'].max_turns == 1
    assert captured['probe_options'].setting_sources == []
    assert captured['probe_options'].tools == []
    assert captured['probe_options'].mcp_servers == {}
    auth_config = Path(captured['kwargs']['env']['CLAUDE_CONFIG_DIR'])
    probe_config = Path(captured['probe_options'].env['CLAUDE_CONFIG_DIR'])
    assert auth_config != probe_config
    assert not auth_config.exists()  # noqa: ASYNC240
    assert not probe_config.exists()  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_claude_healthcheck_timeout_terminates_the_cli_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {'terminated': False, 'killed': False, 'waited': False}

    class FakeProcess:
        pid = None
        returncode: int | None = None

        @staticmethod
        async def communicate() -> tuple[bytes, bytes]:
            raise asyncio.TimeoutError

        def terminate(self) -> None:
            state['terminated'] = True

        def kill(self) -> None:
            state['killed'] = True
            self.returncode = -9

        async def wait(self) -> int:
            state['waited'] = True
            self.returncode = -15
            return self.returncode

    async def fake_subprocess(*_args: Any, **kwargs: Any) -> FakeProcess:
        assert kwargs['start_new_session'] is (os.name == 'posix')
        return FakeProcess()

    monkeypatch.setattr(
        claude_adapter_module.asyncio,
        'create_subprocess_exec',
        fake_subprocess,
    )

    healthy, reason = await ClaudeMindmapAdapter().healthcheck({
        'ANTHROPIC_AUTH_TOKEN': 'connector-secret',
    }, model_ref='haiku')

    assert healthy is False
    assert reason == '无法确认 Claude Code 登录状态'
    assert state == {'terminated': True, 'killed': False, 'waited': True}


@pytest.mark.asyncio
async def test_claude_bedrock_healthcheck_probes_provider_without_claude_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail('Bedrock 健康检查不得依赖 Claude auth status')

    async def fake_query(*, options: Any, **_kwargs: Any) -> Any:
        captured['options'] = options
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id='bedrock-health-session', usage={}, result='OK',
        )

    monkeypatch.setattr(
        claude_adapter_module.asyncio,
        'create_subprocess_exec',
        fail_subprocess,
    )
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)

    healthy, reason = await ClaudeMindmapAdapter().healthcheck({
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_PROFILE': 'mindmap-runtime',
        'AWS_REGION': 'us-east-1',
    }, model_ref='us.anthropic.claude-sonnet-4-6')

    assert healthy is True
    assert reason is None
    assert captured['options'].env['CLAUDE_CODE_USE_BEDROCK'] == '1'
    assert not Path(captured['options'].env['CLAUDE_CONFIG_DIR']).exists()  # noqa: ASYNC240
    assert captured['options'].env['AWS_PROFILE'] == 'mindmap-runtime'
    assert captured['options'].env['AWS_REGION'] == 'us-east-1'


@pytest.mark.asyncio
async def test_claude_healthcheck_sanitizes_real_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_error = 'API key forbidden for private-provider-account'

    class FakeProcess:
        returncode = 0

        @staticmethod
        async def communicate() -> tuple[bytes, bytes]:
            return b'{"loggedIn":true}', b''

    async def fake_subprocess(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.ResultMessage(
            subtype='error', duration_ms=1, duration_api_ms=1, is_error=True,
            num_turns=1, session_id='failed-health-session', usage={},
            result=private_error, errors=[private_error],
            terminal_reason='api_error', api_error_status=403,
        )

    monkeypatch.setattr(
        claude_adapter_module,
        '_read_local_claude_profile_environment',
        lambda: {'ANTHROPIC_API_KEY': 'profile-secret'},
    )
    monkeypatch.setattr(
        claude_adapter_module.asyncio,
        'create_subprocess_exec',
        fake_subprocess,
    )
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)

    healthy, reason = await ClaudeMindmapAdapter().healthcheck(model_ref='sonnet')

    assert healthy is False
    assert reason == 'Claude Provider 拒绝了当前凭据或模型访问权限'
    assert private_error not in reason


@pytest.mark.asyncio
async def test_claude_healthcheck_rejects_unsafe_model_without_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        claude_adapter_module,
        '_read_local_claude_profile_environment',
        lambda: {'ANTHROPIC_API_KEY': 'profile-secret'},
    )
    provider_query = AsyncMock()
    monkeypatch.setattr(claude_agent_sdk, 'query', provider_query)

    healthy, reason = await ClaudeMindmapAdapter().healthcheck(model_ref='--dangerous')

    assert healthy is False
    assert reason == 'Claude 模型或认证配置无效'
    provider_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_claude_unknown_provider_error_never_exposes_raw_result_or_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = 'private prompt with sk-secret-value'
    events: list[tuple[str, dict[str, Any]]] = []

    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.ResultMessage(
            subtype='error', duration_ms=1, duration_api_ms=1, is_error=True,
            num_turns=1, session_id='failed-session', usage={},
            result=secret, errors=[secret], terminal_reason=secret,
        )

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter().run(_context(), collect_event)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert secret not in str(error.value)
    assert secret not in json.dumps(events, ensure_ascii=False)
    assert events[-1] == (
        'agent_error',
        {
            'errorCode': 'AI_AGENT_UNAVAILABLE',
            'message': 'Claude Agent 供应商暂不可用，请稍后重试',
        },
    )


@pytest.mark.asyncio
async def test_claude_bedrock_sdk_exception_maps_to_sanitized_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_error = 'UnrecognizedClientException for access-id private-value'
    events: list[tuple[str, dict[str, Any]]] = []

    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        raise RuntimeError(private_error)
        yield  # pragma: no cover

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.metadata.update({
        'modelRef': 'us.anthropic.claude-sonnet-4-6',
        'credentialEnv': {
            'CLAUDE_CODE_USE_BEDROCK': '1',
            'AWS_PROFILE': 'mindmap-runtime',
            'AWS_REGION': 'us-east-1',
        },
    })

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_PROVIDER_AUTH_FAILED'
    assert private_error not in str(error.value)
    assert private_error not in json.dumps(events, ensure_ascii=False)
    assert events[-1][0] == 'agent_error'


@pytest.mark.asyncio
async def test_claude_adapter_maps_not_logged_in_result_to_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.ResultMessage(
            subtype='error', duration_ms=1, duration_api_ms=1, is_error=True,
            num_turns=1, session_id='failed-session', usage={},
            result='Not logged in · Please run /login', terminal_reason='api_error',
        )

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter().run(_context(), _ignore_event)
    assert error.value.code == 'AI_PROVIDER_AUTH_FAILED'
    assert '登录' in str(error.value)


@pytest.mark.asyncio
async def test_claude_adapter_passes_only_the_explicit_resume_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    session_storage_root = tmp_path.joinpath('claude-sessions')
    seed_store = _ClaudeSessionStore(session_storage_root, retention_days=30)
    await seed_store.append(
        {'project_key': 'old-temporary-workspace', 'session_id': CLAUDE_PARENT_SESSION_ID},
        [{'type': 'user', 'uuid': 'parent-message'}],
    )

    def fake_server(*, name: str, version: str, tools: list[Any]) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': name, 'instance': object()}

    async def fake_query(*, options: Any, **_kwargs: Any) -> Any:
        captured['resume'] = options.resume
        captured['fork_session'] = options.fork_session
        captured['session_store'] = options.session_store
        parent_entries = await options.session_store.load({
            'project_key': 'new-temporary-workspace',
            'session_id': options.resume,
        })
        captured['parent_entries'] = parent_entries
        await options.session_store.append(
            {
                'project_key': 'new-temporary-workspace',
                'session_id': CLAUDE_CHILD_SESSION_ID,
            },
            [*(parent_entries or []), {'type': 'assistant', 'uuid': 'child-message'}],
        )
        tools = {item.name: item for item in captured['tools']}
        await tools['start_document'].handler({'title': '续写', 'layout': 'logicalStructure'})
        await tools['complete_artifact'].handler({})
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_CHILD_SESSION_ID, usage={},
        )

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _resume_context()
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}
    result = await ClaudeMindmapAdapter(
        session_storage_root=session_storage_root,
    ).resume(context, _ignore_event)
    assert captured['resume'] == CLAUDE_PARENT_SESSION_ID
    assert captured['fork_session'] is True
    assert captured['session_store'] is not None
    assert captured['parent_entries'] == [{'type': 'user', 'uuid': 'parent-message'}]
    assert result.external_session_id == CLAUDE_CHILD_SESSION_ID
    assert await _ClaudeSessionStore(
        session_storage_root, retention_days=30,
    ).load({
        'project_key': 'after-process-restart',
        'session_id': CLAUDE_CHILD_SESSION_ID,
    }) == [
        {'type': 'user', 'uuid': 'parent-message'},
        {'type': 'assistant', 'uuid': 'child-message'},
    ]


@pytest.mark.asyncio
async def test_claude_cancel_stops_a_tool_before_mutation_and_cleans_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    add_started = asyncio.Event()

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        started = await tools['start_document'].handler({
            'title': '取消测试', 'layout': 'logicalStructure',
        })
        root_uid = json.loads(started['content'][0]['text'])['rootUid']
        await tools['add_nodes'].handler({'nodes': [{
            'parentUid': root_uid,
            'text': '取消后不得写入',
        }]})
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id='cancel-session', usage={},
        )

    async def block_before_mutation(event_type: str, payload: dict[str, Any]) -> None:
        if event_type == 'tool_started' and payload.get('toolName') == 'add_nodes':
            add_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.metadata['modelRef'] = 'claude-policy-snapshot'
    adapter = ClaudeMindmapAdapter()
    run_task = asyncio.create_task(adapter.run(context, block_before_mutation))
    await asyncio.wait_for(add_started.wait(), timeout=1)

    assert await adapter.cancel(context.job_id) is True
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert context.tool_service.read_projection()['root']['children'] == []
    assert context.job_id not in adapter._tasks
    assert context.job_id not in adapter._cancel_events
    assert await adapter.cancel(context.job_id) is False


@pytest.mark.asyncio
async def test_sessionless_adapter_cleanup_defaults_fail_closed() -> None:
    adapter = NativeMindmapAdapter()

    with pytest.raises(MindmapArtifactError) as purge_error:
        await adapter.purge_session(external_session_id=CLAUDE_SESSION_ID)
    assert purge_error.value.code == 'AI_CAPABILITY_UNSUPPORTED'

    with pytest.raises(MindmapArtifactError) as cleanup_error:
        await adapter.cleanup_expired_sessions()
    assert cleanup_error.value.code == 'AI_CAPABILITY_UNSUPPORTED'


@pytest.mark.asyncio
async def test_codex_public_session_purge_is_exact_and_rejects_traversal(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('codex-sessions')
    codex_home = tmp_path.joinpath('codex-home')
    for thread_id in (CODEX_THREAD_ID, CODEX_SECOND_THREAD_ID):
        rollout = codex_home.joinpath(
            'sessions', thread_id, f'rollout-{thread_id}.jsonl',
        )
        rollout.parent.mkdir(parents=True, exist_ok=True)
        rollout.write_text('{"type":"session_meta"}\n', encoding='utf-8')
        _save_session_snapshot(
            storage_root, codex_home, thread_id, retention_days=30,
        )

    adapter = CodexMindmapAdapter(session_storage_root=storage_root)
    assert await adapter.purge_session(CODEX_THREAD_ID) is True
    assert await adapter.purge_session(CODEX_THREAD_ID) is False
    first_archive, first_metadata = _session_snapshot_paths(storage_root, CODEX_THREAD_ID)
    second_archive, second_metadata = _session_snapshot_paths(
        storage_root, CODEX_SECOND_THREAD_ID,
    )
    assert not first_archive.exists()
    assert not first_metadata.exists()
    assert second_archive.is_file()
    assert second_metadata.is_file()

    with pytest.raises(MindmapArtifactError) as error:
        await adapter.purge_session('../../foreign-session')
    assert error.value.code == 'AI_SESSION_UNAVAILABLE'


@pytest.mark.asyncio
async def test_codex_public_session_cleanup_is_independent_and_symlink_safe(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('codex-sessions')
    codex_home = tmp_path.joinpath('codex-home')
    rollout = codex_home.joinpath(
        'sessions', '2026', f'rollout-{CODEX_THREAD_ID}.jsonl',
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    _save_session_snapshot(storage_root, codex_home, CODEX_THREAD_ID, retention_days=30)
    archive_path, metadata_path = _session_snapshot_paths(storage_root, CODEX_THREAD_ID)
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    metadata['expiresAt'] = time.time() - 1
    metadata_path.write_text(json.dumps(metadata), encoding='utf-8')

    adapter = CodexMindmapAdapter(session_storage_root=storage_root)
    assert await adapter.cleanup_expired_sessions() == 1
    assert not archive_path.exists()
    assert not metadata_path.exists()

    outside = tmp_path.joinpath('outside-codex-snapshot')
    outside.write_text('must survive', encoding='utf-8')
    archive_path.symlink_to(outside)
    assert await adapter.purge_session(CODEX_THREAD_ID) is True
    assert outside.read_text(encoding='utf-8') == 'must survive'


@pytest.mark.asyncio
async def test_claude_session_store_round_trips_across_ephemeral_project_keys(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('claude-sessions')
    first_store = _ClaudeSessionStore(storage_root, retention_days=30)
    main_key = {'project_key': 'first-random-cwd', 'session_id': CLAUDE_SESSION_ID}
    first_entries = [
        {'type': 'user', 'uuid': 'message-1', 'message': {'role': 'user'}},
        {'type': 'assistant', 'uuid': 'message-2', 'message': {'role': 'assistant'}},
    ]
    await first_store.append(main_key, first_entries)
    # SDK retries can replay UUID-bearing records; the persistent adapter is idempotent.
    await first_store.append(main_key, [first_entries[0]])
    await first_store.append(
        {**main_key, 'subpath': 'subagents/agent-child'},
        [{'type': 'assistant', 'uuid': 'subagent-message'}],
    )

    restarted_store = _ClaudeSessionStore(storage_root, retention_days=30)
    assert await restarted_store.load({
        'project_key': 'different-random-cwd',
        'session_id': CLAUDE_SESSION_ID,
    }) == first_entries
    assert await restarted_store.list_subkeys({
        'project_key': 'third-random-cwd',
        'session_id': CLAUDE_SESSION_ID,
    }) == ['subagents/agent-child']
    snapshot_path = _claude_session_snapshot_path(storage_root, CLAUDE_SESSION_ID)
    assert snapshot_path.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    assert storage_root.stat().st_mode & 0o777 == PRIVATE_DIRECTORY_MODE


@pytest.mark.asyncio
async def test_claude_session_store_materializes_a_real_sdk_resume(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('claude-sessions')
    store = _ClaudeSessionStore(storage_root, retention_days=30)
    entries = [{
        'type': 'user',
        'uuid': 'persisted-user-message',
        'message': {'role': 'user', 'content': 'persisted'},
    }]
    await store.append(
        {'project_key': 'old-cwd', 'session_id': CLAUDE_PARENT_SESSION_ID},
        entries,
    )
    options = ClaudeAgentOptions(
        cwd=tmp_path.joinpath('brand-new-cwd'),
        env={'ANTHROPIC_API_KEY': 'test-only'},
        resume=CLAUDE_PARENT_SESSION_ID,
        session_store=_ClaudeSessionStore(storage_root, retention_days=30),
    )

    materialized = await materialize_resume_session(options)
    assert materialized is not None
    try:
        transcript_files = list(materialized.config_dir.glob('projects/**/*.jsonl'))
        assert len(transcript_files) == 1
        assert [
            json.loads(line)
            for line in transcript_files[0].read_text(encoding='utf-8').splitlines()
        ] == entries
    finally:
        await materialized.cleanup()
    assert not materialized.config_dir.exists()


@pytest.mark.asyncio
async def test_claude_session_retention_cleanup_and_exact_purge_are_safe(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('claude-sessions')
    long_store = _ClaudeSessionStore(storage_root, retention_days=30)
    await long_store.append(
        {'project_key': 'p', 'session_id': CLAUDE_PARENT_SESSION_ID},
        [{'type': 'user', 'uuid': 'parent'}],
    )
    parent_path = _claude_session_snapshot_path(storage_root, CLAUDE_PARENT_SESSION_ID)
    original_expiry = json.loads(parent_path.read_text(encoding='utf-8'))['expiresAt']
    await _ClaudeSessionStore(storage_root, retention_days=1).append(
        {'project_key': 'p2', 'session_id': CLAUDE_PARENT_SESSION_ID},
        [{'type': 'assistant', 'uuid': 'continued'}],
    )
    assert json.loads(parent_path.read_text(encoding='utf-8'))['expiresAt'] >= original_expiry

    await long_store.append(
        {'project_key': 'p', 'session_id': CLAUDE_CHILD_SESSION_ID},
        [{'type': 'user', 'uuid': 'child'}],
    )
    child_path = _claude_session_snapshot_path(storage_root, CLAUDE_CHILD_SESSION_ID)
    expired = json.loads(parent_path.read_text(encoding='utf-8'))
    expired['expiresAt'] = time.time() - 1
    parent_path.write_text(json.dumps(expired), encoding='utf-8')

    adapter = ClaudeMindmapAdapter(session_storage_root=storage_root)
    assert await adapter.cleanup_expired_sessions() == 1
    assert not parent_path.exists()
    assert child_path.is_file()
    assert await adapter.purge_session(CLAUDE_CHILD_SESSION_ID) is True
    assert await adapter.purge_session(CLAUDE_CHILD_SESSION_ID) is False

    with pytest.raises(MindmapArtifactError) as error:
        await adapter.purge_session('../../foreign-session')
    assert error.value.code == 'AI_SESSION_UNAVAILABLE'

    outside = tmp_path.joinpath('outside-claude-snapshot')
    outside.write_text('must survive', encoding='utf-8')
    child_path.symlink_to(outside)
    assert await adapter.purge_session(CLAUDE_CHILD_SESSION_ID) is True
    assert outside.read_text(encoding='utf-8') == 'must survive'


@pytest.mark.asyncio
async def test_claude_failed_branch_discards_child_but_preserves_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('claude-sessions')
    seed_store = _ClaudeSessionStore(storage_root, retention_days=30)
    parent_entries = [{'type': 'user', 'uuid': 'parent-message'}]
    await seed_store.append(
        {'project_key': 'old-cwd', 'session_id': CLAUDE_PARENT_SESSION_ID},
        parent_entries,
    )

    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(*, options: Any, **_kwargs: Any) -> Any:
        await options.session_store.append(
            {'project_key': 'new-cwd', 'session_id': CLAUDE_CHILD_SESSION_ID},
            [*parent_entries, {'type': 'assistant', 'uuid': 'failed-child'}],
        )
        raise RuntimeError('connection failed')
        yield  # pragma: no cover

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _resume_context()
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}
    adapter = ClaudeMindmapAdapter(session_storage_root=storage_root)

    with pytest.raises(MindmapArtifactError) as error:
        await adapter.resume(context, _ignore_event)
    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    restarted_store = _ClaudeSessionStore(storage_root, retention_days=30)
    assert await restarted_store.load({
        'project_key': 'after-restart',
        'session_id': CLAUDE_PARENT_SESSION_ID,
    }) == parent_entries
    assert await restarted_store.load({
        'project_key': 'after-restart',
        'session_id': CLAUDE_CHILD_SESSION_ID,
    }) is None


@pytest.mark.asyncio
async def test_codex_completed_event_failure_discards_new_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('codex-sessions')
    bridge_state = _install_inprocess_codex_bridge(monkeypatch)

    async def fake_invoke(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        await _execute_codex_plan_inprocess(bridge_state['executor'])
        _write_fake_codex_rollout(kwargs, CODEX_THREAD_ID)
        return {
            'protocolVersion': codex_worker.WORKER_PROTOCOL_VERSION,
            'ok': True,
            'result': _codex_plan(),
            'externalSessionId': CODEX_THREAD_ID,
            'usage': _codex_usage(),
        }

    async def fail_completed_event(event_type: str, _payload: dict[str, Any]) -> None:
        if event_type == 'agent_completed':
            raise RuntimeError('database event write failed')

    adapter = CodexMindmapAdapter(session_storage_root=storage_root)
    monkeypatch.setattr(adapter, '_invoke_worker', fake_invoke)
    context = _context()
    context.metadata['credentialEnv'] = {'OPENAI_API_KEY': 'connector-secret'}

    with pytest.raises(RuntimeError, match='event write failed'):
        await adapter.run(context, fail_completed_event)

    archive_path, metadata_path = _session_snapshot_paths(storage_root, CODEX_THREAD_ID)
    assert not archive_path.exists()
    assert not metadata_path.exists()


@pytest.mark.asyncio
async def test_claude_completed_event_failure_discards_child_but_preserves_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path.joinpath('claude-sessions')
    seed_store = _ClaudeSessionStore(storage_root, retention_days=30)
    parent_entries = [{'type': 'user', 'uuid': 'parent-message'}]
    await seed_store.append(
        {'project_key': 'old-cwd', 'session_id': CLAUDE_PARENT_SESSION_ID},
        parent_entries,
    )
    captured: dict[str, Any] = {}

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(*, options: Any, **_kwargs: Any) -> Any:
        loaded = await options.session_store.load({
            'project_key': 'new-cwd',
            'session_id': CLAUDE_PARENT_SESSION_ID,
        })
        await options.session_store.append(
            {'project_key': 'new-cwd', 'session_id': CLAUDE_CHILD_SESSION_ID},
            [*(loaded or []), {'type': 'assistant', 'uuid': 'child-message'}],
        )
        tools = {item.name: item for item in captured['tools']}
        await tools['start_document'].handler({
            'title': '续写', 'layout': 'logicalStructure',
        })
        await tools['complete_artifact'].handler({})
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_CHILD_SESSION_ID, usage={},
        )

    async def fail_completed_event(event_type: str, _payload: dict[str, Any]) -> None:
        if event_type == 'agent_completed':
            raise RuntimeError('database event write failed')

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _resume_context()
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}
    adapter = ClaudeMindmapAdapter(session_storage_root=storage_root)

    with pytest.raises(MindmapArtifactError):
        await adapter.resume(context, fail_completed_event)

    restarted_store = _ClaudeSessionStore(storage_root, retention_days=30)
    assert await restarted_store.load({
        'project_key': 'after-restart',
        'session_id': CLAUDE_PARENT_SESSION_ID,
    }) == parent_entries
    assert await restarted_store.load({
        'project_key': 'after-restart',
        'session_id': CLAUDE_CHILD_SESSION_ID,
    }) is None


@pytest.mark.asyncio
async def test_claude_mirror_failure_is_sanitized_and_fails_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = 'private mirror backend details'
    events: list[tuple[str, dict[str, Any]]] = []

    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        yield claude_agent_sdk.MirrorErrorMessage(
            subtype='mirror_error',
            data={'error': secret},
            key={'project_key': 'private', 'session_id': CLAUDE_SESSION_ID},
            error=secret,
        )

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter().run(context, collect_event)
    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert secret not in str(error.value)
    assert secret not in json.dumps(events, ensure_ascii=False)
    assert events[-1] == (
        'agent_error',
        {
            'errorCode': 'AI_AGENT_UNAVAILABLE',
            'message': 'Claude 会话快照保存失败',
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('adapter_class', [CodexMindmapAdapter, ClaudeMindmapAdapter])
async def test_session_storage_rejects_a_symlinked_ancestor(
    adapter_class: type[CodexMindmapAdapter] | type[ClaudeMindmapAdapter],
    tmp_path: Path,
) -> None:
    outside = tmp_path.joinpath('outside-storage')
    outside.mkdir()
    symlinked_parent = tmp_path.joinpath('storage-link')
    symlinked_parent.symlink_to(outside, target_is_directory=True)
    adapter = adapter_class(
        session_storage_root=symlinked_parent.joinpath('provider-sessions'),
    )

    with pytest.raises(MindmapArtifactError) as error:
        await adapter.cleanup_expired_sessions()
    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_event', ['draft_changed', 'tool_completed'])
async def test_codex_tool_event_failure_is_terminal_and_discards_the_run_draft(
    failed_event: str,
) -> None:
    context = _context()
    original_tools = context.tool_service
    failure_count = 0

    async def fail_required_event(
        event_type: str,
        _payload: dict[str, Any],
    ) -> None:
        nonlocal failure_count
        if event_type == failed_event:
            failure_count += 1
            raise RuntimeError('database event write failed with private details')

    executor = _CodexToolExecutionBridge(
        context, fail_required_event, codex_worker.ALLOWED_TOOL_NAMES,
    )

    with pytest.raises(MindmapArtifactError) as error:
        await executor.call('start_document', {
            'title': '不得保留的草稿', 'layout': 'logicalStructure',
        })

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert 'private details' not in str(error.value)
    assert context.tool_service is original_tools
    assert context.tool_service.operation_cursor() == 0
    assert executor.successful_tools == []
    assert executor.completed is None
    retry = await executor.call('start_document', {
        'title': '模型重试也不得写入', 'layout': 'logicalStructure',
    })
    assert retry['ok'] is False
    assert retry['error']['code'] == 'AI_AGENT_UNAVAILABLE'
    assert failure_count == 1


@pytest.mark.asyncio
async def test_codex_unexpected_tool_runtime_failure_is_not_output_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    original_tools = context.tool_service
    events: list[tuple[str, dict[str, Any]]] = []
    private_detail = 'database credential must-not-leak'

    def fail_tool(_self: MindmapToolService, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(private_detail)

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(MindmapToolService, 'start_document', fail_tool)
    executor = _CodexToolExecutionBridge(
        context, collect_event, codex_worker.ALLOWED_TOOL_NAMES,
    )

    response = await executor.call('start_document', {
        'title': 'discarded', 'layout': 'logicalStructure',
    })

    assert response == {
        'ok': False,
        'error': {
            'code': 'AI_AGENT_UNAVAILABLE',
            'message': 'Codex 脑图工具执行失败',
        },
    }
    assert private_detail not in json.dumps(events, ensure_ascii=False)
    assert events[-1] == ('tool_failed', {
        'toolName': 'start_document',
        'step': 1,
        'errorCode': 'AI_AGENT_UNAVAILABLE',
        'errorMessage': 'Codex 脑图工具执行失败',
        'retryable': False,
    })
    assert executor.terminal_error is not None
    assert context.tool_service is original_tools
    assert context.tool_service.operation_cursor() == 0


@pytest.mark.asyncio
async def test_codex_tool_limit_counts_failed_calls_and_becomes_terminal() -> None:
    context = _context()
    original_tools = context.tool_service
    executor = _CodexToolExecutionBridge(
        context,
        _ignore_event,
        codex_worker.ALLOWED_TOOL_NAMES,
        max_tool_calls=2,
    )

    assert (await executor.call('start_document', {
        'title': '临时草稿', 'layout': 'logicalStructure',
    }))['ok'] is True
    assert (await executor.call('add_nodes', {}))['ok'] is False
    exceeded = await executor.call('validate_draft', {})
    repeated = await executor.call('complete_artifact', {})

    assert exceeded['ok'] is False
    assert exceeded['error']['code'] == 'AI_BUDGET_EXCEEDED'
    assert repeated == exceeded
    assert executor.terminal_error is not None
    assert context.tool_service is original_tools
    assert context.tool_service.operation_cursor() == 0


@pytest.mark.asyncio
async def test_codex_adapter_aborts_worker_as_soon_as_tool_limit_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bridge_state = _install_inprocess_codex_bridge(monkeypatch)
    worker_cancelled = asyncio.Event()

    async def fake_invoke(_request: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        executor = bridge_state['executor']
        try:
            for _index in range(codex_adapter_module._MAX_CODEX_TOOL_CALLS + 1):
                await executor.call('read_projection', {})
            await asyncio.Event().wait()
        finally:
            worker_cancelled.set()
        raise AssertionError('unreachable')

    adapter = CodexMindmapAdapter(session_storage_root=tmp_path.joinpath('sessions'))
    monkeypatch.setattr(adapter, '_invoke_worker', fake_invoke)
    context = _context()
    original_tools = context.tool_service
    context.metadata['credentialEnv'] = {'OPENAI_API_KEY': 'connector-secret'}

    with pytest.raises(MindmapArtifactError) as error:
        await adapter.run(context, _ignore_event)

    assert error.value.code == 'AI_BUDGET_EXCEEDED'
    assert worker_cancelled.is_set()
    assert context.tool_service is original_tools


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_event', ['draft_changed', 'tool_completed'])
async def test_native_tool_event_failure_is_terminal_and_discards_the_run_draft(
    monkeypatch: pytest.MonkeyPatch,
    failed_event: str,
) -> None:
    observed: dict[str, Any] = {}
    retry_codes: list[str] = []

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                for _attempt in range(2):
                    with pytest.raises(MindmapArtifactError) as tool_error:
                        await tools['start_document']('不得保留的草稿')
                    retry_codes.append(tool_error.value.code)
                yield RunCompletedEvent(metrics=Metrics(total_tokens=8))

            return stream()

    failed_once = False

    async def fail_required_event(
        event_type: str,
        _payload: dict[str, Any],
    ) -> None:
        nonlocal failed_once
        if event_type == failed_event and not failed_once:
            failed_once = True
            raise RuntimeError('database event write failed')

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = _context()
    original_tools = context.tool_service
    context.metadata['model'] = object()

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, fail_required_event)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert retry_codes == ['AI_AGENT_UNAVAILABLE', 'AI_AGENT_UNAVAILABLE']
    assert context.tool_service is original_tools
    assert context.tool_service.operation_cursor() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_event', ['draft_changed', 'tool_completed'])
async def test_claude_tool_event_failure_is_terminal_and_discards_the_run_draft(
    monkeypatch: pytest.MonkeyPatch,
    failed_event: str,
) -> None:
    captured: dict[str, Any] = {}
    retry_codes: list[str] = []

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        for _attempt in range(2):
            with pytest.raises(MindmapArtifactError) as tool_error:
                await tools['start_document'].handler({
                    'title': '不得保留的草稿', 'layout': 'logicalStructure',
                })
            retry_codes.append(tool_error.value.code)
        yield claude_agent_sdk.ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id=CLAUDE_SESSION_ID, usage={},
        )

    failed_once = False

    async def fail_required_event(
        event_type: str,
        _payload: dict[str, Any],
    ) -> None:
        nonlocal failed_once
        if event_type == failed_event and not failed_once:
            failed_once = True
            raise RuntimeError('database event write failed')

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    context = _context()
    original_tools = context.tool_service
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter().run(context, fail_required_event)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert retry_codes == ['AI_AGENT_UNAVAILABLE', 'AI_AGENT_UNAVAILABLE']
    assert context.tool_service is original_tools
    assert context.tool_service.operation_cursor() == 0


@pytest.mark.asyncio
async def test_native_unexpected_tool_runtime_failure_is_not_output_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []
    private_detail = 'database password must-not-leak'

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: Any) -> Any:
            async def stream() -> Any:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('discarded')
                if False:  # pragma: no cover
                    yield RunCompletedEvent(metrics=Metrics(total_tokens=1))

            return stream()

    def fail_tool(_self: MindmapToolService, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(private_detail)

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    monkeypatch.setattr(MindmapToolService, 'start_document', fail_tool)
    context = _context()
    original_tools = context.tool_service
    context.metadata['model'] = object()

    with pytest.raises(MindmapArtifactError) as error:
        await NativeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert private_detail not in str(error.value)
    assert private_detail not in json.dumps(events, ensure_ascii=False)
    assert events[-1] == ('tool_failed', {
        'toolName': 'start_document',
        'errorCode': 'AI_AGENT_UNAVAILABLE',
        'errorMessage': 'MindMap Agent 脑图工具执行失败',
        'retryable': False,
    })
    assert context.tool_service is original_tools


@pytest.mark.asyncio
async def test_claude_unexpected_tool_runtime_failure_is_not_output_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []
    private_detail = 'storage token must-not-leak'

    def fake_server(*, tools: list[Any], **_kwargs: Any) -> dict[str, Any]:
        captured['tools'] = tools
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    async def fake_query(**_kwargs: Any) -> Any:
        tools = {item.name: item for item in captured['tools']}
        await tools['start_document'].handler({
            'title': 'discarded', 'layout': 'logicalStructure',
        })
        if False:  # pragma: no cover
            yield None

    def fail_tool(_self: MindmapToolService, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(private_detail)

    async def collect_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', fake_query)
    monkeypatch.setattr(MindmapToolService, 'start_document', fail_tool)
    context = _context()
    original_tools = context.tool_service
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}

    with pytest.raises(MindmapArtifactError) as error:
        await ClaudeMindmapAdapter().run(context, collect_event)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert private_detail not in str(error.value)
    assert private_detail not in json.dumps(events, ensure_ascii=False)
    assert events[-1] == ('tool_failed', {
        'toolName': 'start_document',
        'errorCode': 'AI_AGENT_UNAVAILABLE',
        'message': 'Claude 脑图工具执行失败',
        'retryable': False,
    })
    assert context.tool_service is original_tools


@pytest.mark.asyncio
async def test_claude_generation_explicitly_closes_stream_on_body_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = asyncio.Event()

    class TrackingStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> 'TrackingStream':
            return self

        async def __anext__(self) -> Any:
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            return claude_agent_sdk.MirrorErrorMessage(
                subtype='mirror_error',
                data={'error': 'private'},
                key={'project_key': 'private', 'session_id': CLAUDE_SESSION_ID},
                error='private',
            )

        async def aclose(self) -> None:
            closed.set()

    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', lambda **_kwargs: TrackingStream())
    context = _context()
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}

    with pytest.raises(MindmapArtifactError):
        await ClaudeMindmapAdapter().run(context, _ignore_event)

    assert closed.is_set()


@pytest.mark.asyncio
async def test_claude_generation_explicitly_closes_stream_on_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_started = asyncio.Event()
    closed = asyncio.Event()

    class BlockingStream:
        def __aiter__(self) -> 'BlockingStream':
            return self

        async def __anext__(self) -> Any:
            read_started.set()
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def aclose(self) -> None:
            closed.set()

    def fake_server(**_kwargs: Any) -> dict[str, Any]:
        return {'type': 'sdk', 'name': 'mindmap', 'instance': object()}

    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', fake_server)
    monkeypatch.setattr(claude_agent_sdk, 'query', lambda **_kwargs: BlockingStream())
    context = _context()
    context.metadata['credentialEnv'] = {'ANTHROPIC_API_KEY': 'connector-secret'}
    adapter = ClaudeMindmapAdapter()
    run_task = asyncio.create_task(adapter.run(context, _ignore_event))
    await asyncio.wait_for(read_started.wait(), timeout=1)

    assert await adapter.cancel(context.job_id) is True
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert closed.is_set()
