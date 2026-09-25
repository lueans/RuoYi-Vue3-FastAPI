from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from exceptions.exception import ServiceException
from module_ai.controller.ai_model_controller import ai_model_controller
from module_ai.dao.ai_model_dao import AiModelDao
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.service.mindmap_ai_service import MindmapAiTaskManager
from utils.ai_util import AiUtil
from utils.crypto_util import CryptoUtil


def _response_data_schema(app: FastAPI, path: str) -> dict:
    schema = app.openapi()
    response_schema = schema['paths'][path]['get']['responses']['200']['content'][
        'application/json'
    ]['schema']
    response_model = schema['components']['schemas'][response_schema['$ref'].rsplit('/', 1)[-1]]
    return response_model['properties']['data']


def test_ai_model_all_contract_returns_a_model_array() -> None:
    app = FastAPI()
    app.include_router(ai_model_controller)

    data_schema = _response_data_schema(app, '/ai/model/all')

    assert data_schema['type'] == 'array'
    item_ref = data_schema['items']['$ref']
    assert item_ref.endswith('/AiModelModel')


def test_ai_model_non_paginated_list_route_is_all_not_list_all() -> None:
    get_paths = {
        route.path
        for route in ai_model_controller.routes
        if 'GET' in getattr(route, 'methods', set())
    }

    assert '/ai/model/all' in get_paths
    assert '/ai/model/listAll' not in get_paths


@pytest.mark.asyncio
async def test_native_mindmap_model_id_resolves_persisted_provider_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        model_id=17,
        user_id=7,
        status='0',
        provider='Ollama',
        model_code='qwen3.5:latest',
        model_name='Qwen 3.5',
        api_key='encrypted-key',
        base_url='http://127.0.0.1:11434',
        temperature=0.2,
        max_tokens=4096,
    )
    load_model = AsyncMock(return_value=record)
    decrypt = Mock(return_value='plain-key')
    resolved_model = object()
    model_factory = Mock(return_value=resolved_model)
    monkeypatch.setattr(AiModelDao, 'get_ai_model_detail_by_id', load_model)
    monkeypatch.setattr(CryptoUtil, 'decrypt', decrypt)
    monkeypatch.setattr(AiUtil, 'get_model_from_factory', model_factory)
    database = SimpleNamespace()

    result = await MindmapAiTaskManager._resolve_native_model(
        database,
        user_id=7,
        model_id=17,
    )

    assert result is resolved_model
    load_model.assert_awaited_once_with(database, 17)
    decrypt.assert_called_once_with('encrypted-key')
    model_factory.assert_called_once_with(
        provider='Ollama',
        model_code='qwen3.5:latest',
        model_name='Qwen 3.5',
        api_key='plain-key',
        base_url='http://127.0.0.1:11434',
        temperature=0.2,
        max_tokens=4096,
    )


@pytest.mark.asyncio
async def test_native_mindmap_rejects_anthropic_with_openai_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        user_id=7,
        status='0',
        provider='Anthropic',
        model_code='阿里百炼',
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        api_key='encrypted-secret',
    )
    monkeypatch.setattr(
        AiModelDao, 'get_ai_model_detail_by_id', AsyncMock(return_value=record),
    )
    decrypt = Mock()
    model_factory = Mock()
    monkeypatch.setattr(CryptoUtil, 'decrypt', decrypt)
    monkeypatch.setattr(AiUtil, 'get_model_from_factory', model_factory)

    with pytest.raises(MindmapArtifactError) as error:
        await MindmapAiTaskManager._resolve_native_model(
            SimpleNamespace(), user_id=7, model_id=2,
        )

    assert error.value.code == 'AI_MODEL_CONFIG_INVALID'
    assert 'DashScope 或 OpenAI' in str(error.value)
    assert 'encrypted-secret' not in str(error.value)
    decrypt.assert_not_called()
    model_factory.assert_not_called()


@pytest.mark.asyncio
async def test_native_mindmap_model_constructor_error_is_actionable_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        user_id=7,
        status='0',
        provider='Anthropic',
        model_code='test-model',
        model_name='Test Model',
        base_url='https://gateway.example.test/anthropic',
        api_key=None,
        temperature=0.2,
        max_tokens=4096,
    )
    monkeypatch.setattr(
        AiModelDao, 'get_ai_model_detail_by_id', AsyncMock(return_value=record),
    )
    monkeypatch.setattr(
        AiUtil, 'get_model_from_factory',
        Mock(side_effect=TypeError('secret-raw-provider-detail')),
    )

    with pytest.raises(MindmapArtifactError) as error:
        await MindmapAiTaskManager._resolve_native_model(
            SimpleNamespace(), user_id=7, model_id=2,
        )

    assert error.value.code == 'AI_MODEL_CONFIG_INVALID'
    assert 'secret-raw-provider-detail' not in str(error.value)


@pytest.mark.asyncio
async def test_native_mindmap_model_key_decryption_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        user_id=7,
        status='0',
        provider='OpenAI',
        model_code='test-model',
        base_url=None,
        api_key='encrypted-secret',
    )
    monkeypatch.setattr(
        AiModelDao, 'get_ai_model_detail_by_id', AsyncMock(return_value=record),
    )
    monkeypatch.setattr(
        CryptoUtil, 'decrypt', Mock(side_effect=ServiceException('private-detail')),
    )

    with pytest.raises(MindmapArtifactError) as error:
        await MindmapAiTaskManager._resolve_native_model(
            SimpleNamespace(), user_id=7, model_id=2,
        )

    assert error.value.code == 'AI_MODEL_CONFIG_INVALID'
    assert '重新保存密钥' in str(error.value)
    assert 'private-detail' not in str(error.value)


def test_anthropic_custom_base_url_reaches_sdk_client_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor = Mock(return_value=object())
    monkeypatch.setattr(
        AiUtil, '_resolve_provider_class', Mock(return_value=constructor),
    )

    AiUtil.get_model_from_factory(
        provider='Anthropic',
        model_code='claude-test',
        api_key='test-key',
        base_url='https://anthropic-gateway.example.test/v1',
    )

    assert constructor.call_args.kwargs['client_params'] == {
        'base_url': 'https://anthropic-gateway.example.test/v1',
    }
    assert 'base_url' not in constructor.call_args.kwargs
