"""Formal retry creates an auditable fresh turn without provider session reuse."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from exceptions.exception import ServiceException
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobRetryModel
from module_mindmap.service.mindmap_ai_service import (
    MindmapAiService,
    MindmapAiTaskManager,
    _stable_retry_fingerprint,
)
from server import create_app

SESSION_ID = '10000000-0000-4000-8000-000000000001'
FAILED_JOB_ID = '20000000-0000-4000-8000-000000000001'
NEXT_TURN_INDEX = 5
LATEST_CLOUD_REVISION = 9
RETRY_MAX_NODES = 80
ORIGINAL_MAX_DEPTH = 6


def _document(title: str) -> dict:
    return {
        'root': {'data': {'uid': 'root', 'text': title}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default'},
    }


def _request_json(*, agent_key: str = 'codex') -> str:
    return json.dumps({
        'agentKey': agent_key,
        'intent': 'expand',
        'prompt': '原始要求',
        'parameters': {
            'language': 'zh-CN',
            'layout': 'logicalStructure',
            'maxDepth': 6,
            'maxNodes': 100,
            'density': 'standard',
        },
        'source': {
            'type': 'cloud_document',
            'mindmapId': 42,
            'revision': 3,
            'documentHash': 'old-hash',
            'roomEpoch': 'old-epoch',
            'scope': {'type': 'document'},
            'document': _document('旧文档'),
            'baselineDocument': _document('旧文档'),
        },
        'target': 'proposal',
    })


def _failed_job(*, status: str = 'failed') -> SimpleNamespace:
    now = datetime.now()
    return SimpleNamespace(
        id=FAILED_JOB_ID,
        user_id=7,
        session_id=SESSION_ID,
        parent_job_id='provider-parent-must-not-be-inherited',
        retry_of_job_id=None,
        turn_index=2,
        agent_key='codex',
        adapter_version='old-adapter',
        sdk_version='old-sdk',
        runtime_version='old-runtime',
        model_ref='old-model',
        max_budget_usd=1.0,
        timeout_seconds=300,
        max_nodes=100,
        max_depth=6,
        retention_days=30,
        intent='expand',
        target='proposal',
        source_type='cloud_document',
        source_mindmap_id=42,
        base_revision=3,
        base_hash='old-hash',
        base_room_epoch='old-epoch',
        request_json=_request_json(),
        request_fingerprint='old-fingerprint',
        idempotency_key='old-idempotency-key',
        status=status,
        progress=100,
        title=None,
        artifact_id=None,
        proposal_id=None,
        external_session_ref='encrypted-provider-session-must-not-be-inherited',
        usage_json=None,
        error_code='AI_OUTPUT_INVALID',
        error_message='旧错误详情',
        created_time=now,
        update_time=now,
        completed_time=now,
        expires_time=now + timedelta(days=2),
    )


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        id=SESSION_ID,
        status='active',
        expires_time=datetime.now() + timedelta(days=2),
    )


def _created_job(_db: object, values: dict) -> SimpleNamespace:
    return SimpleNamespace(
        **values,
        title=None,
        artifact_id=None,
        proposal_id=None,
        usage_json=None,
        error_code=None,
        error_message=None,
        completed_time=None,
    )


def test_retry_fingerprint_is_bound_to_source_job_and_exact_overrides() -> None:
    first = MindmapAiJobRetryModel.model_validate({'prompt': ' 再试一次 '})
    same = MindmapAiJobRetryModel.model_validate({'prompt': '再试一次'})
    changed = MindmapAiJobRetryModel.model_validate({'prompt': '换个要求'})

    assert _stable_retry_fingerprint(FAILED_JOB_ID, first) == _stable_retry_fingerprint(
        FAILED_JOB_ID,
        same,
    )
    assert _stable_retry_fingerprint(FAILED_JOB_ID, first) != _stable_retry_fingerprint(
        '20000000-0000-4000-8000-000000000002',
        first,
    )
    assert _stable_retry_fingerprint(FAILED_JOB_ID, first) != _stable_retry_fingerprint(
        FAILED_JOB_ID,
        changed,
    )


def test_retry_http_contract_exposes_partial_overrides() -> None:
    operation = create_app().openapi()['paths']['/mindmap/ai/jobs/{job_id}/retry']['post']
    schema_ref = operation['requestBody']['content']['application/json']['schema']['$ref']
    schema_name = schema_ref.rsplit('/', 1)[-1]
    schema = create_app().openapi()['components']['schemas'][schema_name]

    assert operation['summary'] == '重试失败的 AI 脑图任务并创建新轮次'
    assert schema.get('required', []) == []
    assert {'agentKey', 'modelId', 'prompt', 'parameters'} <= set(schema['properties'])


@pytest.mark.asyncio
async def test_retry_idempotent_replay_bypasses_changed_source_and_session() -> None:
    model = MindmapAiJobRetryModel.model_validate({'agentKey': 'claude'})
    existing = _failed_job(status='queued')
    existing.id = 'new-retried-job'
    existing.retry_of_job_id = FAILED_JOB_ID
    existing.parent_job_id = None
    existing.request_fingerprint = _stable_retry_fingerprint(FAILED_JOB_ID, model)

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=existing),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(side_effect=AssertionError('original job must not be reread')),
        ),
        patch.object(
            MindmapAiService,
            '_prepare_source_for_job',
            new=AsyncMock(side_effect=AssertionError('cloud source must not be refetched')),
        ),
        patch.object(MindmapAiTaskManager, 'schedule', new=Mock()) as schedule,
    ):
        replay = await MindmapAiService.retry_job(
            SimpleNamespace(),
            FAILED_JOB_ID,
            model,
            user_id=7,
            idempotency_key='lost-retry-response',
        )

    assert replay.id == 'new-retried-job'
    schedule.assert_called_once_with('new-retried-job')


@pytest.mark.asyncio
async def test_retry_idempotency_key_cannot_be_reused_for_other_overrides() -> None:
    model = MindmapAiJobRetryModel.model_validate({'prompt': '新的要求'})
    existing = _failed_job(status='queued')
    existing.request_fingerprint = _stable_retry_fingerprint(
        FAILED_JOB_ID,
        MindmapAiJobRetryModel.model_validate({'prompt': '旧的重试要求'}),
    )

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=existing),
        ),
        pytest.raises(ServiceException) as error,
    ):
        await MindmapAiService.retry_job(
            SimpleNamespace(),
            FAILED_JOB_ID,
            model,
            user_id=7,
            idempotency_key='conflicting-retry-key',
        )
    assert '幂等键已被用于不同' in error.value.message


@pytest.mark.asyncio
async def test_retry_creates_fresh_turn_and_refetches_cloud_without_provider_session() -> None:
    original = _failed_job()
    existing_later_turn = SimpleNamespace(id='later', turn_index=4)
    session = _session()
    latest_document = _document('最新权威文档')
    manifest = SimpleNamespace(
        agent_key='claude',
        adapter_version='new-adapter',
        sdk_version='new-sdk',
        runtime_version='new-runtime',
        intents={'expand'},
        input_types={'cloud_document'},
    )
    registry = SimpleNamespace(get=Mock(return_value=SimpleNamespace(
        get_manifest=Mock(return_value=manifest),
    )))
    policy = SimpleNamespace(
        max_budget_usd=2.0,
        timeout_seconds=240,
        max_nodes=200,
        max_depth=8,
        retention_days=20,
        max_concurrent_jobs=3,
    )
    add_job = AsyncMock(side_effect=_created_job)
    add_event = AsyncMock()
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    model = MindmapAiJobRetryModel.model_validate({
        'agentKey': 'claude',
        'prompt': '换一个 Agent，覆盖边界场景',
        'parameters': {'maxNodes': RETRY_MAX_NODES, 'density': 'detailed'},
    })

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=original),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(side_effect=[session, session]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch.object(
            MindmapAiService,
            '_ensure_connector_available',
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch.object(
            MindmapAiService,
            '_prepare_source_for_job',
            new=AsyncMock(return_value=(
                latest_document,
                LATEST_CLOUD_REVISION,
                'latest-hash',
                42,
                'latest-epoch',
            )),
        ) as prepare_source,
        patch.object(MindmapAiService, '_runtime_policy', return_value=policy),
        patch.object(MindmapAiService, '_validate_job_policy', return_value='claude-model'),
        patch.object(MindmapAiService, '_ensure_concurrency_available', new=AsyncMock()),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.lock_jobs_for_session',
            new=AsyncMock(return_value=[original, existing_later_turn]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_job',
            new=add_job,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=add_event,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_session',
            new=AsyncMock(),
        ),
        patch.object(MindmapAiTaskManager, 'schedule', new=Mock()) as schedule,
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event',
            new=Mock(),
        ),
    ):
        result = await MindmapAiService.retry_job(
            database,
            FAILED_JOB_ID,
            model,
            user_id=7,
            idempotency_key='retry-switch-agent',
        )

    prepare_source.assert_awaited_once()
    prepared_request = prepare_source.await_args.args[1]
    assert prepared_request.source.type == 'cloud_document'
    created = add_job.await_args.args[1]
    assert created['id'] != FAILED_JOB_ID
    assert created['session_id'] == SESSION_ID
    assert created['turn_index'] == NEXT_TURN_INDEX
    assert created['parent_job_id'] is None
    assert created['retry_of_job_id'] == FAILED_JOB_ID
    assert created['external_session_ref'] is None
    assert created['agent_key'] == 'claude'
    assert created['base_revision'] == LATEST_CLOUD_REVISION
    assert created['base_hash'] == 'latest-hash'
    assert created['base_room_epoch'] == 'latest-epoch'
    request = json.loads(created['request_json'])
    assert request['prompt'] == '换一个 Agent，覆盖边界场景'
    assert request['parameters']['maxNodes'] == RETRY_MAX_NODES
    assert request['parameters']['maxDepth'] == ORIGINAL_MAX_DEPTH
    assert request['parameters']['density'] == 'detailed'
    assert request['source']['document'] == latest_document
    assert request['source']['baselineDocument'] == latest_document
    assert request['source']['revision'] == LATEST_CLOUD_REVISION
    assert 'modelId' not in request
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['retryOfJobId'] == FAILED_JOB_ID
    assert result.retry_of_job_id == FAILED_JOB_ID
    assert result.parent_job_id is None
    schedule.assert_called_once_with(created['id'])


@pytest.mark.asyncio
async def test_retry_rejects_non_retryable_terminal_before_provider_checks() -> None:
    original = _failed_job(status='ready')
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=original),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            new=Mock(side_effect=AssertionError('provider must not be inspected')),
        ),
        pytest.raises(ServiceException) as error,
    ):
        await MindmapAiService.retry_job(
            SimpleNamespace(),
            FAILED_JOB_ID,
            MindmapAiJobRetryModel(),
            user_id=7,
            idempotency_key='not-retryable-key',
        )

    assert error.value.data == {'errorCode': 'AI_JOB_NOT_RETRYABLE'}


@pytest.mark.asyncio
async def test_retry_rejects_deleted_or_expired_platform_session() -> None:
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=_failed_job()),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ServiceException) as error,
    ):
        await MindmapAiService.retry_job(
            SimpleNamespace(),
            FAILED_JOB_ID,
            MindmapAiJobRetryModel(),
            user_id=7,
            idempotency_key='missing-session-key',
        )

    assert error.value.data == {'errorCode': 'AI_SESSION_UNAVAILABLE'}
