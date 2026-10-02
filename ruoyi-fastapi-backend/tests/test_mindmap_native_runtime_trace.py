"""Native provider obeys the same observable, non-mutating chat contract as CLI agents."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from agno.run.agent import RunCompletedEvent, RunContentEvent

from module_mindmap.ai.adapters.base import AgentEventDeliveryError, AgentRunContext
from module_mindmap.ai.adapters.native import NativeMindmapAdapter, NativeTodoItem
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.runtime_trace import RuntimeTrace
from module_mindmap.ai.template_profile import build_template_profile
from module_mindmap.ai.tool_contract import MindmapToolService

EXPECTED_NODE_COUNT = 2
EXPECTED_TOOL_CALLS = 6
MAX_DETAIL_CHARS = 6000


def context() -> AgentRunContext:
    return AgentRunContext(
        job_id='native-trace-test', user_id=1, intent='create', prompt='生成订单脑图',
        parameters={'layout': 'logicalStructure'}, source_document=None,
        tool_service=MindmapToolService(), metadata={'model': object()},
    )


def install_agent(monkeypatch: pytest.MonkeyPatch, scenario: Callable[..., AsyncIterator[Any]]) -> None:
    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            self.tools = {tool.__name__: tool for tool in kwargs['tools']}

        def arun(self, _prompt: str, **_kwargs: Any) -> AsyncIterator[Any]:
            return scenario(self.tools)

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)


async def complete_map(tools: dict[str, Any]) -> None:
    await tools['start_document']('订单')
    await tools['add_nodes']([{'parentUid': '@root', 'text': '支付'}])
    await tools['validate_draft']()
    await tools['complete_artifact']()


def test_native_trace_streams_only_public_content_and_deduplicates_final() -> None:
    trace = RuntimeTrace()
    events = trace.native(RunContentEvent(content='正在', reasoning_content='private reasoning'))
    events += trace.native(RunContentEvent(content='分析'))
    events += trace.next_message()
    events += trace.native(RunContentEvent(content='已完成'))
    events += trace.native(RunCompletedEvent(content='正在分析已完成'))
    visible = [payload for kind, payload in events if kind == 'assistant_delta']
    assert ''.join(item['text'] for item in visible) == '正在分析已完成'
    assert visible[0]['messageId'] != visible[-1]['messageId']
    assert any(kind == 'thinking_state' for kind, _ in events)
    assert 'private reasoning' not in json.dumps(events)


def test_native_trace_final_only_and_structured_completion() -> None:
    trace = RuntimeTrace()
    assert trace.native(RunContentEvent(content='')) == []
    assert trace.native(RunCompletedEvent(content='完成'))[0][1]['text'] == '完成'
    assert trace.native(RunCompletedEvent(content='完成')) == []
    assert RuntimeTrace().native(RunCompletedEvent(content='{"completionState":"artifact_completed"}')) == []


@pytest.mark.asyncio
async def test_native_plan_tool_details_and_preview_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []
    ctx = context()
    original = ctx.tool_service
    before = original.attempt_effect_marker()

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        yield RunContentEvent(content='先整理结构')
        plan = json.loads(await tools['update_plan']([
            NativeTodoItem(id=None, content='整理结构', status='in_progress'),
            {'content': '添加支付', 'status': 'pending'},
        ]))
        assert [todo['id'] for todo in plan['todos']] == ['1', '2']
        assert not any(kind == 'draft_changed' for kind, _ in events)
        assert original.attempt_effect_marker() == before
        await tools['start_document']('订单')
        await tools['add_nodes']([{'parentUid': '@root', 'text': '支付'}])
        await tools['update_plan']([{'id': '1', 'content': '整理结构', 'status': 'completed'}])
        await tools['validate_draft']()
        await tools['complete_artifact']()
        yield RunContentEvent(content='完成脑图')
        yield RunCompletedEvent(content='先整理结构完成脑图')

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    install_agent(monkeypatch, scenario)
    result = await NativeMindmapAdapter().run(ctx, emit)
    assert result.summary['nodeCount'] == EXPECTED_NODE_COUNT
    assert [payload['toolName'] for kind, payload in events if kind == 'draft_changed'] == [
        'start_document', 'add_nodes',
    ]
    assert [payload['todos'][0]['status'] for kind, payload in events if kind == 'todo_updated'] == [
        'in_progress', 'completed',
    ]
    starts = {payload['callId']: payload for kind, payload in events if kind == 'tool_started'}
    finishes = {payload['callId']: payload for kind, payload in events if kind == 'tool_completed'}
    assert len(starts) == len(finishes) == EXPECTED_TOOL_CALLS
    assert starts.keys() == finishes.keys()
    for key, finish in finishes.items():
        assert starts[key]['toolName'] == finish['toolName']
        assert finish['durationMs'] >= 0
        assert len(finish['toolInput']) <= MAX_DETAIL_CHARS
        assert len(finish['toolOutput']) <= MAX_DETAIL_CHARS
    plan_details = [payload for payload in finishes.values() if payload['toolName'] == 'update_plan']
    assert json.loads(plan_details[0]['toolInput'])['todos'][0]['content'] == '整理结构'
    first_tool = next(index for index, (kind, _) in enumerate(events) if kind == 'tool_started')
    assert any(kind == 'assistant_delta' for kind, _ in events[:first_tool])
    assert ''.join(payload['text'] for kind, payload in events if kind == 'assistant_delta') == '先整理结构完成脑图'


@pytest.mark.asyncio
async def test_native_invalid_plan_never_echoes_arguments_or_modifies_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        result = json.loads(await tools['update_plan']([{'content': 'private-invalid-plan', 'status': 'invented'}]))
        assert result['errorCode'] == 'TOOL_ARGUMENT_INVALID'
        assert not any(kind in {'draft_changed', 'todo_updated'} for kind, _ in events)
        await complete_map(tools)
        yield RunCompletedEvent(content='完成')

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    install_agent(monkeypatch, scenario)
    await NativeMindmapAdapter().run(context(), emit)
    failure = next(payload for kind, payload in events if kind == 'tool_failed')
    assert failure['callId']
    assert failure['durationMs'] >= 0
    assert 'toolInput' not in failure
    assert 'private-invalid-plan' not in json.dumps(events)


@pytest.mark.asyncio
async def test_native_plan_after_completion_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = context()
    original = ctx.tool_service
    events = []

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        await complete_map(tools)
        await tools['update_plan']([{'content': '不能在终态后继续', 'status': 'completed'}])
        yield RunCompletedEvent(content='完成')

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    install_agent(monkeypatch, scenario)
    with pytest.raises(MindmapArtifactError, match='继续调用工具'):
        await NativeMindmapAdapter().run(ctx, emit)
    assert ctx.tool_service is original
    assert not any(kind == 'todo_updated' for kind, _ in events)


@pytest.mark.asyncio
async def test_native_parallel_tool_calls_keep_distinct_correlated_details(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        await asyncio.gather(tools['search_tags'](query='甲'), tools['search_tags'](query='乙'))
        await complete_map(tools)
        yield RunCompletedEvent(content='完成')

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))
        await asyncio.sleep(0)

    install_agent(monkeypatch, scenario)
    await NativeMindmapAdapter().run(context(), emit)
    searches = [(kind, payload) for kind, payload in events if payload.get('toolName') == 'search_tags']
    assert [kind for kind, _ in searches] == ['tool_started', 'tool_completed', 'tool_started', 'tool_completed']
    assert searches[0][1]['callId'] == searches[1][1]['callId']
    assert searches[2][1]['callId'] == searches[3][1]['callId']
    assert searches[0][1]['callId'] != searches[2][1]['callId']
    assert {json.loads(payload['toolInput'])['query'] for kind, payload in searches if kind == 'tool_completed'} == {
        '甲', '乙',
    }


@pytest.mark.asyncio
async def test_native_trace_delivery_failure_discards_isolated_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = context()
    original = ctx.tool_service

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        await tools['start_document']('未提交')
        yield RunContentEvent(content='公开进度')
        await complete_map(tools)

    async def emit(kind: str, _payload: dict[str, Any]) -> None:
        if kind == 'assistant_delta':
            raise RuntimeError('private storage error')

    install_agent(monkeypatch, scenario)
    with pytest.raises(AgentEventDeliveryError):
        await NativeMindmapAdapter().run(ctx, emit)
    assert ctx.tool_service is original
    assert original.attempt_effect_marker()[0] is False


@pytest.mark.asyncio
async def test_native_cancel_stops_trace_and_tools_without_late_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []
    ready = asyncio.Event()
    never = asyncio.Event()
    ctx = context()
    adapter = NativeMindmapAdapter()

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        yield RunContentEvent(content='开始处理')
        ready.set()
        await never.wait()
        await complete_map(tools)
        yield RunContentEvent(content='不应显示')

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    install_agent(monkeypatch, scenario)
    task = asyncio.create_task(adapter.run(ctx, emit))
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
        assert await adapter.cancel(ctx.job_id)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not await adapter.cancel(ctx.job_id)
        assert not any(kind in {'tool_started', 'draft_changed'} for kind, _ in events)
        assert '不应显示' not in json.dumps(events, ensure_ascii=False)
        assert ''.join(payload['text'] for kind, payload in events if kind == 'assistant_delta') == '开始处理'
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_native_provider_cannot_continue_trace_after_swallowing_tool_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        with pytest.raises(AgentEventDeliveryError):
            await tools['start_document']('未提交')
        yield RunContentEvent(content='不能伪装继续执行')

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        if kind == 'draft_changed':
            raise RuntimeError('storage unavailable')
        events.append((kind, payload))

    install_agent(monkeypatch, scenario)
    with pytest.raises(AgentEventDeliveryError):
        await NativeMindmapAdapter().run(context(), emit)
    assert not any(kind == 'assistant_delta' for kind, _ in events)


@pytest.mark.asyncio
async def test_native_template_role_failure_guides_correction_without_misreporting_parent_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []
    ctx = context()
    profile = build_template_profile({
        'id': 9, 'contentRevision': 1, 'layout': 'mindMap', 'theme': {'template': 'default', 'config': {}},
        'nodeTree': {'data': {'uid': 'example-root', 'text': 'Example'}, 'children': [
            {'data': {'uid': 'example-child', 'text': 'Example child', 'fillColor': '#123456', 'tag': [{'tagId': 7}]}, 'children': []},
        ]},
    })
    ctx.template_profile = profile
    ctx.tool_service = MindmapToolService(template_profile=profile, tag_catalog=[
        {'tagId': 7, 'text': 'Allowed', 'style': {'color': '#123456'}, 'status': 0},
        {'tagId': 8, 'text': 'Another role', 'style': {}, 'status': 0},
    ])

    async def scenario(tools: dict[str, Any]) -> AsyncIterator[Any]:
        await tools['start_document']('Generated topic')
        failed = json.loads(await tools['add_nodes']([{'parentUid': '@root', 'text': 'Child', 'templateRole': 'r'}]))
        assert failed['ok'] is False
        assert 'templateRole' in failed['message']
        assert '省略 templateRole' in failed['message']
        assert 'parentUid 无效' not in failed['message']
        wrong_tag = json.loads(await tools['add_nodes']([{'parentUid': '@root', 'text': 'Child', 'tag': [{'tagId': 8}]}]))
        assert wrong_tag['ok'] is False
        assert '只引用该角色列出的 tagIds' in wrong_tag['message']
        assert '省略 tag' in wrong_tag['message']
        corrected = json.loads(await tools['add_nodes']([{'parentUid': '@root', 'text': 'Child'}]))
        assert corrected['createdCount'] == 1
        await tools['validate_draft']()
        await tools['complete_artifact']()
        yield RunCompletedEvent(content='完成')

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    install_agent(monkeypatch, scenario)
    result = await NativeMindmapAdapter().run(ctx, emit)
    assert result.artifact['document']['root']['children'][0]['data']['fillColor'] == '#123456'
    failures = [payload for kind, payload in events if kind == 'tool_failed']
    assert [item['toolName'] for item in failures] == ['add_nodes', 'add_nodes']
    assert all(item['retryable'] for item in failures)
