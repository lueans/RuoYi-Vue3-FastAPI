"""Provider-independent needs-input and safe transient retry contracts."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from module_mindmap.ai.adapters.base import (
    AgentNeedsInputResult,
    AgentRunContext,
    agent_needs_input_result,
    normalize_agent_input_questions,
    run_adapter_with_transient_retries,
)
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.service.mindmap_ai_service import (
    MindmapAiService,
    MindmapAiTaskManager,
)

EXPECTED_ATTEMPTS = 3
EXPECTED_TERMINAL_PROGRESS = 100


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


def test_needs_input_contract_normalizes_one_to_three_safe_questions() -> None:
    questions = normalize_agent_input_questions({
        'completionState': 'needs_input',
        'questions': [
            {'questionId': 'scope', 'prompt': '  需要覆盖哪些   业务范围？ '},
            {'questionId': 'audience_2', 'prompt': '主要读者是谁？'},
        ],
    })

    assert [question.to_dict() for question in questions] == [
        {'questionId': 'scope', 'prompt': '需要覆盖哪些 业务范围？'},
        {'questionId': 'audience_2', 'prompt': '主要读者是谁？'},
    ]


@pytest.mark.parametrize(
    'payload',
    [
        {'completionState': 'needs_input', 'questions': []},
        {
            'completionState': 'needs_input',
            'questions': [
                {'questionId': f'q{index}', 'prompt': '请补充范围'}
                for index in range(4)
            ],
        },
        {
            'completionState': 'needs_input',
            'questions': [
                {'questionId': 'scope', 'prompt': '问题一'},
                {'questionId': 'scope', 'prompt': '问题二'},
            ],
        },
        {
            'completionState': 'needs_input',
            'questions': [{'questionId': '../scope', 'prompt': '请补充范围'}],
        },
        {
            'completionState': 'needs_input',
            'questions': [{'questionId': 'secret', 'prompt': '请提供 API key'}],
        },
        {
            'completionState': 'needs_input',
            'questions': [{'questionId': 'secret', 'prompt': 'What is your password?'}],
        },
        {
            'completionState': 'needs_input',
            'questions': [{'questionId': 'scope', 'prompt': '问题\u0000'}],
        },
    ],
)
def test_needs_input_contract_rejects_unsafe_or_invalid_questions(payload: dict[str, Any]) -> None:
    with pytest.raises(MindmapArtifactError) as error:
        normalize_agent_input_questions(payload)

    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_transient_provider_failures_retry_twice_before_any_visible_effect() -> None:
    context = _context()
    original_tools = context.tool_service
    attempts = 0
    persisted_events: list[tuple[str, dict[str, Any]]] = []
    sleeps: list[float] = []

    async def emit(event_type: str, payload: dict[str, Any]) -> None:
        persisted_events.append((event_type, payload))

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async def runner(
        run_context: AgentRunContext,
        attempt_emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AgentNeedsInputResult:
        nonlocal attempts
        attempts += 1
        assert run_context.tool_service is original_tools
        await attempt_emit('agent_started', {'attempt': attempts})
        if attempts < EXPECTED_ATTEMPTS:
            # Adapters may replace the tool service with an isolated fork. The
            # retry boundary must discard it and restore the pristine service.
            run_context.tool_service = original_tools.fork()
            raise MindmapArtifactError('供应商暂不可用', code='AI_AGENT_UNAVAILABLE')
        return agent_needs_input_result({
            'completionState': 'needs_input',
            'questions': [{'questionId': 'scope', 'prompt': '需要覆盖哪些范围？'}],
        })

    result = await run_adapter_with_transient_retries(
        runner,
        context,
        emit,
        retry_delays=(0.2, 0.4),
        sleep=sleep,
    )

    assert isinstance(result, AgentNeedsInputResult)
    assert attempts == EXPECTED_ATTEMPTS
    assert sleeps == [0.2, 0.4]
    # Failed-attempt lifecycle noise was never visible or persisted.
    assert persisted_events == [('agent_started', {'attempt': EXPECTED_ATTEMPTS})]


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary_event', ['tool_started', 'draft_changed'])
async def test_transient_failure_is_never_replayed_after_visible_tool_boundary(
    boundary_event: str,
) -> None:
    context = _context()
    attempts = 0
    persisted_events: list[str] = []
    sleeps: list[float] = []

    async def runner(
        _context: AgentRunContext,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AgentNeedsInputResult:
        nonlocal attempts
        attempts += 1
        await emit('agent_started', {})
        await emit(boundary_event, {'toolName': 'start_document'})
        raise MindmapArtifactError('请求受限', code='AI_RATE_LIMITED')

    with pytest.raises(MindmapArtifactError) as error:
        await run_adapter_with_transient_retries(
            runner,
            context,
            lambda event, _payload: _append_event(persisted_events, event),
            retry_delays=(0.01, 0.02),
            sleep=lambda delay: _append_delay(sleeps, delay),
        )

    assert error.value.code == 'AI_RATE_LIMITED'
    assert attempts == 1
    assert persisted_events == ['agent_started', boundary_event]
    assert sleeps == []


async def _append_event(events: list[str], event: str) -> None:
    events.append(event)


async def _append_delay(delays: list[float], delay: float) -> None:
    delays.append(delay)


@pytest.mark.asyncio
async def test_transient_failure_is_never_replayed_after_unannounced_operation() -> None:
    context = _context()
    attempts = 0
    sleeps: list[float] = []

    async def runner(
        run_context: AgentRunContext,
        _emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AgentNeedsInputResult:
        nonlocal attempts
        attempts += 1
        tools = run_context.tool_service.fork()
        run_context.tool_service = tools
        root_uid = tools.start_document('订单')['rootUid']
        tools.add_nodes([{'parentUid': root_uid, 'text': '支付'}])
        raise MindmapArtifactError('供应商暂不可用', code='AI_AGENT_UNAVAILABLE')

    with pytest.raises(MindmapArtifactError):
        await run_adapter_with_transient_retries(
            runner,
            context,
            _discard_event,
            retry_delays=(0.01, 0.02),
            sleep=lambda delay: _append_delay(sleeps, delay),
        )

    assert attempts == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_transient_failure_is_never_replayed_after_unannounced_draft_creation() -> None:
    context = _context()
    attempts = 0
    sleeps: list[float] = []

    async def runner(
        run_context: AgentRunContext,
        _emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AgentNeedsInputResult:
        nonlocal attempts
        attempts += 1
        tools = run_context.tool_service.fork()
        run_context.tool_service = tools
        # start_document creates a draft but deliberately has no patch
        # operation, so operation_cursor() remains zero.
        tools.start_document('订单')
        assert tools.operation_cursor() == 0
        raise MindmapArtifactError('供应商暂不可用', code='AI_AGENT_UNAVAILABLE')

    with pytest.raises(MindmapArtifactError) as error:
        await run_adapter_with_transient_retries(
            runner,
            context,
            _discard_event,
            retry_delays=(0.01, 0.02),
            sleep=lambda delay: _append_delay(sleeps, delay),
        )

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert attempts == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_common_needs_input_boundary_rejects_unannounced_draft_effect() -> None:
    context = _context()
    original_tools = context.tool_service

    async def runner(
        run_context: AgentRunContext,
        _emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AgentNeedsInputResult:
        tools = run_context.tool_service.fork()
        run_context.tool_service = tools
        tools.start_document('不得保留的草稿')
        return agent_needs_input_result({
            'completionState': 'needs_input',
            'questions': [{'questionId': 'scope', 'prompt': '请补充范围？'}],
        })

    with pytest.raises(MindmapArtifactError) as error:
        await run_adapter_with_transient_retries(
            runner,
            context,
            _discard_event,
        )

    assert error.value.code == 'AI_OUTPUT_INVALID'
    assert context.tool_service is original_tools


async def _discard_event(_event: str, _payload: dict[str, Any]) -> None:
    return None


@pytest.mark.asyncio
async def test_retry_helper_rejects_more_than_two_automatic_retries() -> None:
    async def runner(
        _context: AgentRunContext,
        _emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AgentNeedsInputResult:
        raise AssertionError('invalid retry policy must be rejected before provider call')

    with pytest.raises(ValueError, match='退避时间无效'):
        await run_adapter_with_transient_retries(
            runner,
            _context(),
            _discard_event,
            retry_delays=(0.1, 0.2, 0.4),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'failure',
    [
        asyncio.CancelledError(),
        TimeoutError(),
        MindmapArtifactError('供应商请求超时', code='AI_TIMEOUT'),
    ],
)
async def test_cancellation_and_timeout_propagate_without_retry(failure: BaseException) -> None:
    context = _context()
    attempts = 0
    sleeps: list[float] = []

    async def runner(
        _context: AgentRunContext,
        _emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AgentNeedsInputResult:
        nonlocal attempts
        attempts += 1
        raise failure

    with pytest.raises(type(failure)):
        await run_adapter_with_transient_retries(
            runner,
            context,
            _discard_event,
            retry_delays=(0.01, 0.02),
            sleep=lambda delay: _append_delay(sleeps, delay),
        )

    assert attempts == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_task_persists_needs_input_status_and_safe_questions_atomically() -> None:
    job_id = '12345678-1234-1234-1234-123456789012'
    session_id = '22345678-1234-1234-1234-123456789012'
    request_json = json.dumps({
        'agentKey': 'codex',
        'intent': 'create',
        'prompt': '帮我做一个脑图',
        'source': {'type': 'none'},
        'target': 'file',
    })
    job = SimpleNamespace(
        id=job_id,
        status='running',
        agent_key='codex',
        sdk_version='test-sdk',
        runtime_version='test-runtime',
        model_ref='test-model',
        max_budget_usd=1.0,
        timeout_seconds=30,
        max_nodes=100,
        max_depth=10,
        retention_days=30,
        user_id=7,
        request_json=request_json,
        intent='create',
        parent_job_id=None,
        session_id=session_id,
        base_revision=None,
        base_hash=None,
        base_room_epoch=None,
    )
    session = SimpleNamespace(
        id=session_id,
        status='active',
        expires_time=datetime.now() + timedelta(days=1),
    )
    result = agent_needs_input_result(
        {
            'completionState': 'needs_input',
            'questions': [{
                'questionId': 'scope',
                'prompt': '需要覆盖哪些业务范围？',
            }],
        },
        usage={'inputTokens': 3, 'outputTokens': 5},
    )
    manifest = SimpleNamespace(
        status='enabled',
        status_reason=None,
        max_nodes=100,
        max_depth=10,
    )
    adapter = SimpleNamespace(
        get_manifest=lambda: manifest,
        start=AsyncMock(return_value=result),
        resume=AsyncMock(return_value=result),
        collect_usage=MagicMock(return_value={
            'inputTokens': 3,
            'outputTokens': 5,
            'totalTokens': 8,
        }),
        purge_session=AsyncMock(return_value=True),
    )
    database = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )

    class SessionFactory:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    update_job = AsyncMock()
    update_session = AsyncMock()
    add_event = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=SimpleNamespace(get=lambda _agent_key: adapter),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.resolve_connector_credential',
            return_value={},
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_draft_event_payloads',
            new=AsyncMock(return_value=[]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=update_job,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_session',
            new=update_session,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=add_event,
        ),
        patch.object(
            MindmapAiService,
            '_ensure_connector_available',
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_begin_draft_preview_run',
            new=AsyncMock(),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_set_status',
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_owns_current_job_lease',
            new=AsyncMock(return_value=True),
        ),
        patch.object(MindmapAiTaskManager, '_fail', new=AsyncMock()),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_run',
            new=MagicMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event',
            new=MagicMock(),
        ),
    ):
        await MindmapAiTaskManager._run_job(job_id)

    update_job.assert_awaited_once()
    assert update_job.await_args.args[2]['status'] == 'needs_input'
    assert update_job.await_args.args[2]['progress'] == EXPECTED_TERMINAL_PROGRESS
    assert update_job.await_args.args[2]['completed_time'] is not None
    update_session.assert_awaited_once()
    add_event.assert_awaited_once()
    assert add_event.await_args.args[2] == 'needs_input'
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload == {
        'status': 'needs_input',
        'progress': 100,
        'questions': [{
            'questionId': 'scope',
            'prompt': '需要覆盖哪些业务范围？',
        }],
    }
    database.commit.assert_awaited_once()
