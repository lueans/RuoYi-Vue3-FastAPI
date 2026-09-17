"""Stable, early idempotency replay for AI mindmap job creation."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from exceptions.exception import ServiceException
from module_mindmap.ai.adapters.base import AgentManifest
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiJobCreateModel,
    MindmapAiMessageModel,
)
from module_mindmap.service.mindmap_ai_service import (
    MindmapAiService,
    MindmapAiTaskManager,
    _stable_create_fingerprint,
    _stable_followup_fingerprint,
)

EXPECTED_CONCURRENT_REPLAY_LOOKUPS = 2


def _cloud_request(**source_overrides: object) -> MindmapAiJobCreateModel:
    source = {'type': 'cloud_document', 'mindmapId': 42, **source_overrides}
    return MindmapAiJobCreateModel.model_validate({
        'agentKey': 'codex',
        'intent': 'expand',
        'prompt': '扩写当前脑图',
        'source': source,
        'target': 'proposal',
    })


def _create_request() -> MindmapAiJobCreateModel:
    return MindmapAiJobCreateModel.model_validate({
        'agentKey': 'codex',
        'intent': 'create',
        'prompt': '生成新脑图',
        'source': {'type': 'none'},
        'target': 'file',
    })


def _persisted_job(fingerprint: str) -> SimpleNamespace:
    now = datetime.now()
    return SimpleNamespace(
        id='job-idempotent',
        session_id='session-idempotent',
        parent_job_id=None,
        retry_of_job_id=None,
        turn_index=1,
        agent_key='codex',
        adapter_version='1.0.0',
        sdk_version='1.0.0',
        runtime_version='1.0.0',
        model_ref='test-model',
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
        base_hash='old-cloud-hash',
        base_room_epoch='old-cloud-epoch',
        request_fingerprint=fingerprint,
        status='ready',
        progress=100,
        title='已完成脑图',
        artifact_id='artifact-idempotent',
        proposal_id='proposal-idempotent',
        usage_json='{}',
        error_code=None,
        error_message=None,
        created_time=now,
        update_time=now,
        completed_time=now,
        expires_time=now + timedelta(days=1),
    )


def _manifest() -> AgentManifest:
    return AgentManifest(
        agent_key='codex',
        display_name='Codex',
        adapter_version='1.0.0',
        sdk_name='codex-sdk',
        sdk_version='1.0.0',
        runtime_version='1.0.0',
        intents=('create',),
        input_types=('none',),
        supports_sessions=True,
        supports_streaming=True,
        supports_usage=True,
        status='enabled',
        default_model_ref='test-model',
    )


def test_cloud_create_fingerprint_excludes_server_refetched_state() -> None:
    original = _cloud_request()
    refetched = _cloud_request(
        revision=99,
        documentHash='new-hash',
        roomEpoch='new-epoch',
        document={
            'root': {'data': {'uid': 'root', 'text': '新内容'}, 'children': []},
        },
        baselineDocument={
            'root': {'data': {'uid': 'root', 'text': '旧内容'}, 'children': []},
        },
    )

    assert _stable_create_fingerprint(original) == _stable_create_fingerprint(refetched)


@pytest.mark.asyncio
async def test_create_replay_bypasses_changed_cloud_and_disabled_connector() -> None:
    request = _cloud_request()
    existing = _persisted_job(_stable_create_fingerprint(request))
    registry = Mock(side_effect=AssertionError('connector must not be inspected'))
    prepare_source = AsyncMock(side_effect=AssertionError('cloud must not be refetched'))

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=existing),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            new=registry,
        ),
        patch.object(
            MindmapAiService,
            '_prepare_source_for_job',
            new=prepare_source,
        ),
        patch.object(MindmapAiTaskManager, 'schedule', new=Mock()) as schedule,
    ):
        replay = await MindmapAiService.create_job(
            SimpleNamespace(),
            request,
            user_id=7,
            idempotency_key='lost-create-response',
        )

    assert replay.id == existing.id
    registry.assert_not_called()
    prepare_source.assert_not_awaited()
    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_followup_replay_bypasses_changed_parent_and_session() -> None:
    message = MindmapAiMessageModel.model_validate({'prompt': '继续调整'})
    fingerprint = _stable_followup_fingerprint('parent-original', message)
    existing = _persisted_job(fingerprint)
    get_parent = AsyncMock(side_effect=AssertionError('parent state must not be reread'))
    get_session = AsyncMock(side_effect=AssertionError('session state must not be reread'))

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=existing),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=get_parent,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=get_session,
        ),
    ):
        replay = await MindmapAiService.create_followup_job(
            SimpleNamespace(),
            'parent-original',
            message,
            user_id=7,
            idempotency_key='lost-followup-response',
        )

    assert replay.id == existing.id
    get_parent.assert_not_awaited()
    get_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_job_attempt_uses_owner_and_wakes_committed_queue() -> None:
    request = _create_request()
    existing = _persisted_job(_stable_create_fingerprint(request))
    existing.status = 'queued'
    lookup = AsyncMock(return_value=existing)

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=lookup,
        ),
        patch.object(MindmapAiTaskManager, 'schedule', new=Mock(return_value=True)) as schedule,
    ):
        recovered = await MindmapAiService.reconcile_job_attempt(
            SimpleNamespace(),
            user_id=31,
            idempotency_key='mindmap-ai:lost-response',
        )

    lookup.assert_awaited_once_with(
        SimpleNamespace(),
        31,
        'mindmap-ai:lost-response',
    )
    assert recovered is not None
    assert recovered.id == existing.id
    schedule.assert_called_once_with(existing.id)


@pytest.mark.asyncio
async def test_reconcile_job_attempt_returns_no_cross_owner_match() -> None:
    database = SimpleNamespace()
    lookup = AsyncMock(return_value=None)

    with patch(
        'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
        new=lookup,
    ):
        recovered = await MindmapAiService.reconcile_job_attempt(
            database,
            user_id=37,
            idempotency_key='mindmap-ai:not-owned',
        )

    lookup.assert_awaited_once_with(database, 37, 'mindmap-ai:not-owned')
    assert recovered is None


@pytest.mark.asyncio
async def test_same_key_with_different_client_intent_fails_before_side_effects() -> None:
    request = _cloud_request()
    other_request = _cloud_request()
    other_request.prompt = '另一个要求'
    existing = _persisted_job(_stable_create_fingerprint(other_request))

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=existing),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
        ) as registry,
        pytest.raises(ServiceException) as blocked,
    ):
        await MindmapAiService.create_job(
            SimpleNamespace(),
            request,
            user_id=7,
            idempotency_key='reused-for-other-intent',
        )

    assert '不同的 AI 脑图任务' in blocked.value.message
    registry.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_insert_replay_compares_stable_client_fingerprint() -> None:
    request = _create_request()
    fingerprint = _stable_create_fingerprint(request)
    replay_job = _persisted_job(fingerprint)
    replay_job.intent = 'create'
    replay_job.target = 'file'
    replay_job.source_type = 'none'
    replay_job.source_mindmap_id = None
    replay_job.base_revision = None
    replay_job.base_hash = None
    replay_job.base_room_epoch = None
    lookup = AsyncMock(side_effect=[None, replay_job])
    connector = SimpleNamespace()
    policy = SimpleNamespace(
        model_allowlist=(),
        max_budget_usd=1.0,
        timeout_seconds=300,
        max_nodes=2_000,
        max_depth=32,
        max_concurrent_jobs=5,
        retention_days=30,
    )
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=lookup,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=SimpleNamespace(get=Mock(return_value=SimpleNamespace(
                get_manifest=Mock(return_value=_manifest()),
            ))),
        ),
        patch.object(
            MindmapAiService,
            '_ensure_connector_available',
            new=AsyncMock(return_value=connector),
        ),
        patch.object(
            MindmapAiService,
            '_prepare_source_for_job',
            new=AsyncMock(return_value=(None, None, None, None, None)),
        ),
        patch.object(MindmapAiService, '_runtime_policy', return_value=policy),
        patch.object(MindmapAiService, '_validate_job_policy', return_value='test-model'),
        patch.object(
            MindmapAiService,
            '_ensure_concurrency_available',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_session',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_job',
            new=AsyncMock(side_effect=IntegrityError('insert', {}, RuntimeError('race'))),
        ),
    ):
        replay = await MindmapAiService.create_job(
            database,
            request,
            user_id=7,
            idempotency_key='concurrent-create',
        )

    assert replay.id == replay_job.id
    assert lookup.await_count == EXPECTED_CONCURRENT_REPLAY_LOOKUPS
    database.rollback.assert_awaited_once()
