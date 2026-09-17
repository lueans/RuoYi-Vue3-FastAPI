from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from module_ai.controller.ai_model_controller import ai_model_controller
from module_ai.dao.ai_model_dao import AiModelDao
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
