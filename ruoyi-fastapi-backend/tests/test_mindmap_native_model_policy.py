import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from module_mindmap.ai.adapters.base import AgentRunContext
from module_mindmap.ai.adapters.native import (
    OLLAMA_DEFAULT_KEEP_ALIVE,
    OLLAMA_MIN_CONTEXT_WINDOW_TOKENS,
    OLLAMA_TOOL_RESPONSE_MAX_TOKENS,
    NativeMindmapAdapter,
    _configure_native_model,
)
from module_mindmap.ai.tool_contract import MindmapToolService


def test_native_ollama_disables_reasoning_and_caps_each_tool_response() -> None:
    model = SimpleNamespace(
        provider='Ollama',
        request_params={'think': True, 'keep_alive': '5m'},
        options={'temperature': 0.2, 'num_predict': 4096},
    )

    assert _configure_native_model(model) is model
    assert model.request_params == {'think': False, 'keep_alive': '5m'}
    assert not hasattr(model, 'keep_alive')
    assert model.options == {
        'temperature': 0.2,
        'num_ctx': OLLAMA_MIN_CONTEXT_WINDOW_TOKENS,
        'num_predict': OLLAMA_TOOL_RESPONSE_MAX_TOKENS,
    }


def test_native_ollama_preserves_a_stricter_token_limit() -> None:
    model = SimpleNamespace(
        provider='ollama',
        request_params=None,
        options={'num_predict': 256},
    )

    _configure_native_model(model)

    assert model.request_params == {'think': False}
    assert model.keep_alive == OLLAMA_DEFAULT_KEEP_ALIVE
    assert model.options == {
        'num_ctx': OLLAMA_MIN_CONTEXT_WINDOW_TOKENS,
        'num_predict': 256,
    }


def test_native_ollama_preserves_a_larger_context_window() -> None:
    model = SimpleNamespace(
        provider='ollama',
        request_params=None,
        options={'num_ctx': 32_768, 'num_predict': 256},
    )

    _configure_native_model(model)

    assert model.options == {'num_ctx': 32_768, 'num_predict': 256}


def test_native_ollama_preserves_an_explicit_keep_alive_field() -> None:
    model = SimpleNamespace(
        provider='ollama',
        request_params=None,
        options=None,
        keep_alive='2h',
    )

    _configure_native_model(model)

    assert model.keep_alive == '2h'
    assert model.request_params == {'think': False}


def test_native_non_ollama_model_is_not_mutated() -> None:
    model = SimpleNamespace(provider='OpenAI')

    assert _configure_native_model(model) is model
    assert not hasattr(model, 'request_params')
    assert not hasattr(model, 'options')


@pytest.mark.asyncio
async def test_native_timeout_does_not_auto_complete_partial_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    stream_closed = asyncio.Event()
    events: list[tuple[str, dict[str, object]]] = []

    class FakeAgent:
        def __init__(self, **kwargs: object) -> None:
            observed.update(kwargs)

        def arun(self, _prompt: str, **_kwargs: object) -> object:
            async def stream() -> AsyncIterator[None]:
                tools = {item.__name__: item for item in observed['tools']}
                await tools['start_document']('普通脑图')
                try:
                    await asyncio.Event().wait()
                finally:
                    stream_closed.set()
                if False:
                    yield None

            return stream()

    async def collect_event(event_type: str, payload: dict[str, object]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr('module_mindmap.ai.adapters.native.Agent', FakeAgent)
    context = AgentRunContext(
        job_id='12345678-1234-1234-1234-123456789012',
        user_id=1,
        intent='create',
        prompt='生成普通脑图',
        parameters={'layout': 'logicalStructure'},
        source_document=None,
        tool_service=MindmapToolService(),
        metadata={'model': object(), 'timeoutSeconds': 1},
    )

    with pytest.raises(asyncio.TimeoutError):
        await NativeMindmapAdapter().run(context, collect_event)

    assert stream_closed.is_set()
    assert not [
        payload for event_type, payload in events
        if event_type == 'tool_completed'
        and payload.get('toolName') == 'complete_artifact'
    ]
