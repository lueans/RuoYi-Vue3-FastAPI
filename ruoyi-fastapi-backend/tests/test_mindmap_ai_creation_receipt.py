"""Definitive creation rejection receipts must never hide committed work."""

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from exceptions.exception import ServiceException
from exceptions.handle import handle_exception
from module_mindmap.controller.mindmap_ai_controller import (
    _run_job_creation,
    continue_mindmap_ai_job,
    create_mindmap_ai_job,
    retry_mindmap_ai_job,
)
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.service.mindmap_ai_service import MindmapAiService

KEY = 'mindmap-ai-create-receipt-1'
USER_ID = 23
BUSINESS_ERROR_CODE = 500


@pytest.mark.asyncio
async def test_business_rejection_rolls_back_before_owner_scoped_verification() -> None:
    calls = []
    db = SimpleNamespace(rollback=AsyncMock(side_effect=lambda: calls.append('rollback')))
    error = ServiceException(data={'errorCode': 'AI_INPUT_INVALID'}, message='输入无效')

    async def lookup(*args: object) -> None:
        assert args == (db, USER_ID, KEY)
        calls.append('lookup')

    with (
        patch.object(MindmapAiDao, 'get_job_by_idempotency', side_effect=lookup),
        pytest.raises(ServiceException) as raised,
    ):
        await _run_job_creation(db, USER_ID, KEY, AsyncMock(side_effect=error))
    assert raised.value is error
    assert calls == ['rollback', 'lookup']
    assert error.message == '输入无效'
    assert error.data == {'errorCode': 'AI_INPUT_INVALID', 'creationRejected': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('existing_status', ['queued', 'running', 'completed_direct', 'failed'])
async def test_existing_job_or_key_collision_never_certifies_rejection(existing_status: str) -> None:
    db = SimpleNamespace(rollback=AsyncMock())
    error = ServiceException(
        data={'errorCode': 'AI_CONFLICT', 'creationRejected': True},
        message='幂等键已被用于不同的任务',
    )
    existing = SimpleNamespace(status=existing_status, request_fingerprint='different-request')
    with (
        patch.object(MindmapAiDao, 'get_job_by_idempotency', AsyncMock(return_value=existing)),
        pytest.raises(ServiceException) as raised,
    ):
        await _run_job_creation(db, USER_ID, KEY, AsyncMock(side_effect=error))
    assert raised.value is error
    assert error.data == {'errorCode': 'AI_CONFLICT'}


@pytest.mark.asyncio
async def test_exception_after_commit_keeps_the_result_unknown() -> None:
    persisted = {}
    db = SimpleNamespace(rollback=AsyncMock())
    error = ServiceException(message='任务响应构造失败')

    async def create() -> None:
        # Simulate a scheduling/serialization exception after durable commit.
        persisted[(USER_ID, KEY)] = SimpleNamespace(id='committed-job')
        raise error

    async def lookup(_db: object, user_id: int, key: str) -> object:
        return persisted.get((user_id, key))

    with (
        patch.object(MindmapAiDao, 'get_job_by_idempotency', side_effect=lookup),
        pytest.raises(ServiceException) as raised,
    ):
        await _run_job_creation(db, USER_ID, KEY, create)
    assert raised.value is error
    assert error.data is None
    assert persisted[(USER_ID, KEY)].id == 'committed-job'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['rollback', 'lookup'])
async def test_failed_verification_preserves_the_original_unknown_error(failure: str) -> None:
    db = SimpleNamespace(rollback=AsyncMock(
        side_effect=RuntimeError('database unavailable') if failure == 'rollback' else None,
    ))
    error = ServiceException(data={'errorCode': 'AI_BUSY'}, message='资源不可用')
    lookup = AsyncMock(side_effect=RuntimeError('verification unavailable'))
    with (
        patch.object(MindmapAiDao, 'get_job_by_idempotency', lookup),
        pytest.raises(ServiceException) as raised,
    ):
        await _run_job_creation(db, USER_ID, KEY, AsyncMock(side_effect=error))
    assert raised.value is error
    assert error.data == {'errorCode': 'AI_BUSY'}
    if failure == 'rollback':
        lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_infrastructure_failure_is_not_a_creation_rejection() -> None:
    db = SimpleNamespace(rollback=AsyncMock())
    error = RuntimeError('commit connection lost')
    with (
        patch.object(MindmapAiDao, 'get_job_by_idempotency', AsyncMock()) as lookup,
        pytest.raises(RuntimeError) as raised,
    ):
        await _run_job_creation(db, USER_ID, KEY, AsyncMock(side_effect=error))
    assert raised.value is error
    db.rollback.assert_not_awaited()
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_does_not_rollback_or_requery_the_created_job() -> None:
    db = SimpleNamespace(rollback=AsyncMock())
    result = {'id': 'created-job'}
    with patch.object(MindmapAiDao, 'get_job_by_idempotency', AsyncMock()) as lookup:
        assert await _run_job_creation(db, USER_ID, KEY, AsyncMock(return_value=result)) is result
    db.rollback.assert_not_awaited()
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_non_object_business_payload_is_preserved_without_receipt() -> None:
    db = SimpleNamespace(rollback=AsyncMock())
    error = ServiceException(data='legacy-error-payload', message='旧服务错误')
    with (
        patch.object(MindmapAiDao, 'get_job_by_idempotency', AsyncMock()) as lookup,
        pytest.raises(ServiceException),
    ):
        await _run_job_creation(db, USER_ID, KEY, AsyncMock(side_effect=error))
    assert error.data == 'legacy-error-payload'
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_receipt_does_not_cancel_or_fence_an_older_inflight_request() -> None:
    db = SimpleNamespace(rollback=AsyncMock())
    started = asyncio.Event()
    finish = asyncio.Event()

    async def original_request() -> dict:
        started.set()
        await finish.wait()
        return {'id': 'original-committed-later'}

    original = asyncio.create_task(_run_job_creation(db, USER_ID, KEY, original_request))
    try:
        await started.wait()
        with (
            patch.object(MindmapAiDao, 'get_job_by_idempotency', AsyncMock(return_value=None)),
            pytest.raises(ServiceException) as raised,
        ):
            await _run_job_creation(
                db, USER_ID, KEY, AsyncMock(side_effect=ServiceException(message='本次请求被拒绝')),
            )
        assert raised.value.data['creationRejected'] is True
        # This is why a client already in UNKNOWN/replay must remain locked.
        assert not original.done()
        finish.set()
        assert (await original)['id'] == 'original-committed-later'
    finally:
        finish.set()
        await original


@pytest.mark.asyncio
@pytest.mark.parametrize(('endpoint', 'service', 'child'), [
    (create_mindmap_ai_job, 'create_job', False),
    (continue_mindmap_ai_job, 'create_followup_job', True),
    (retry_mindmap_ai_job, 'retry_job', True),
])
async def test_every_creation_endpoint_uses_the_receipt_boundary(
    endpoint: Callable[..., Awaitable[object]], service: str, child: bool,
) -> None:
    db = SimpleNamespace(rollback=AsyncMock())
    model = object()
    user = SimpleNamespace(user=SimpleNamespace(user_id=USER_ID))
    args = {
        'request': None, 'model': model, 'query_db': db,
        'current_user': user, 'idempotency_key': KEY,
    }
    if child:
        args['job_id'] = 'parent-job'
    error = ServiceException(message='没有可用模型')
    with (
        patch.object(MindmapAiService, service, AsyncMock(side_effect=error)) as creation,
        patch.object(MindmapAiDao, 'get_job_by_idempotency', AsyncMock(return_value=None)),
        pytest.raises(ServiceException) as raised,
    ):
        await inspect.unwrap(endpoint)(**args)
    assert raised.value.data == {'creationRejected': True}
    expected_args = (db, 'parent-job', model, USER_ID, KEY) if child else (db, model, USER_ID, KEY)
    creation.assert_awaited_once_with(*expected_args)


def test_receipt_is_preserved_in_the_existing_http_200_business_error_envelope() -> None:
    app = FastAPI()
    handle_exception(app)
    db = SimpleNamespace(rollback=AsyncMock())

    @app.post('/test-create')
    async def create() -> None:
        await _run_job_creation(
            db, USER_ID, KEY,
            AsyncMock(side_effect=ServiceException(data={'errorCode': 'AI_INPUT_INVALID'}, message='输入无效')),
        )

    with (
        patch.object(MindmapAiDao, 'get_job_by_idempotency', AsyncMock(return_value=None)),
        TestClient(app) as client,
    ):
        response = client.post('/test-create')
    assert response.status_code == HTTPStatus.OK
    payload = json.loads(response.content)
    assert payload['code'] == BUSINESS_ERROR_CODE
    assert payload['data'] == {'errorCode': 'AI_INPUT_INVALID', 'creationRejected': True}
    assert payload['msg'] == '输入无效'
