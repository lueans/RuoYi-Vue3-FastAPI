"""Non-streaming Agno failures are statuses, not successful discussion text."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from openai import AsyncOpenAI

from module_mindmap.ai.adapters import native
from module_mindmap.ai.adapters.base import AgentRunContext
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.tool_contract import MindmapToolService


def _context(model: Any) -> AgentRunContext:
    return AgentRunContext(
        job_id='native-discussion-status', user_id=1, intent='discuss', prompt='分析脑图',
        parameters={}, source_document=None, tool_service=MindmapToolService(), metadata={'model': model},
    )


def _completion() -> native.NativeAgentMessageCompletion:
    return native.NativeAgentMessageCompletion(
        completionState='message_completed', title=None, content='已覆盖主流程。', contentType='text/plain',
    )


def _install_output(monkeypatch: pytest.MonkeyPatch, output: Any) -> None:
    class FakeAgent:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def arun(self, _prompt: str, **kwargs: Any) -> Any:
            assert kwargs == {'stream': False}
            return output

    monkeypatch.setattr(native, 'Agent', FakeAgent)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [RunStatus.error, 'error'])
@pytest.mark.parametrize('provider', ['OpenAI', 'Ollama'])
@pytest.mark.parametrize(('detail', 'code'), [
    ('400 unsupported response_format', 'AI_AGENT_UNAVAILABLE'),
    ('401 invalid api key', 'AI_PROVIDER_AUTH_FAILED'),
    ('429 rate limit exceeded', 'AI_RATE_LIMITED'),
    ('request timed out', 'AI_TIMEOUT'),
])
async def test_error_status_uses_safe_provider_mapping_before_plain_text_fallback(
    monkeypatch: pytest.MonkeyPatch, status: Any, provider: str, detail: str, code: str,
) -> None:
    private = 'offline-sensitive-value'
    _install_output(monkeypatch, RunOutput(status=status, content=f'{detail}; credential={private}'))
    events = []

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    adapter = native.NativeMindmapAdapter()
    with pytest.raises(MindmapArtifactError) as error:
        await adapter.run(_context(SimpleNamespace(provider=provider)), emit)

    assert error.value.code == code
    assert private not in str(error.value)
    assert private not in json.dumps(events)
    assert error.value.__cause__ is None
    assert [kind for kind, _ in events] == ['agent_started']
    assert not adapter._tasks
    assert not adapter._cancel_events


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [RunStatus.cancelled, 'cancelled'])
async def test_cancelled_status_cannot_publish_a_valid_completion(
    monkeypatch: pytest.MonkeyPatch, status: Any,
) -> None:
    _install_output(monkeypatch, RunOutput(status=status, content=_completion()))
    events = []

    async def emit(kind: str, _payload: dict[str, Any]) -> None:
        events.append(kind)

    with pytest.raises(asyncio.CancelledError):
        await native.NativeMindmapAdapter().run(_context(SimpleNamespace(provider='Ollama')), emit)
    assert events == ['agent_started']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [RunStatus.pending, RunStatus.running, RunStatus.paused])
async def test_nonterminal_status_is_not_a_success_even_with_valid_content(
    monkeypatch: pytest.MonkeyPatch, status: Any,
) -> None:
    _install_output(monkeypatch, RunOutput(status=status, content=_completion()))

    async def emit(_kind: str, _payload: dict[str, Any]) -> None:
        pass

    with pytest.raises(MindmapArtifactError) as error:
        await native.NativeMindmapAdapter().run(_context(object()), emit)
    assert error.value.code == 'AI_AGENT_UNAVAILABLE'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [RunStatus.completed, 'completed', None])
async def test_completed_and_legacy_statusless_outputs_keep_structured_contract(
    monkeypatch: pytest.MonkeyPatch, status: Any,
) -> None:
    output = SimpleNamespace(content=_completion(), metrics=None)
    if status is not None:
        output.status = status
    _install_output(monkeypatch, output)
    events = []

    async def emit(kind: str, _payload: dict[str, Any]) -> None:
        events.append(kind)

    result = await native.NativeMindmapAdapter().run(_context(object()), emit)
    assert result.content == '已覆盖主流程。'
    assert events == ['agent_started', 'agent_completed']

    output.content = '{"content":"missing required fields"}'
    with pytest.raises(MindmapArtifactError) as error:
        await native.NativeMindmapAdapter().run(_context(object()), emit)
    assert error.value.code == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_real_agno_http_400_error_output_is_not_reported_as_invalid_content() -> None:
    """Real OpenAI SDK and Agno; all HTTP is handled by an in-memory transport."""
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={'error': {
            'message': 'offline fixture: unsupported response_format',
            'type': 'invalid_request_error', 'code': 'invalid_parameter',
        }}, request=request)

    events = []

    async def emit(kind: str, _payload: dict[str, Any]) -> None:
        events.append(kind)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client,
        AsyncOpenAI(
            api_key='offline-placeholder', base_url='https://fixture.invalid/v1',
            http_client=http_client, max_retries=0,
        ) as client,
    ):
        model = OpenAIChat(id='offline-fixture', api_key='offline-placeholder', async_client=client)
        with pytest.raises(MindmapArtifactError) as error:
            await native.NativeMindmapAdapter().run(_context(model), emit)

    assert error.value.code == 'AI_AGENT_UNAVAILABLE'
    assert 'unsupported response_format' not in str(error.value)
    assert len(requests) == 1
    assert requests[0]['response_format']['type'] == 'json_schema'
    assert events == ['agent_started']
