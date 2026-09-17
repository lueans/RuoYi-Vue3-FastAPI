"""AI 脑图 HTTP、SSE 与持久化边界回归测试。"""

import hashlib
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_mindmap.ai.adapters.base import AgentMessageResult
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.controller.mindmap_ai_controller import (
    _artifact_content_disposition,
    _event_stream,
    _parse_last_event_id,
    get_mindmap_ai_job_draft,
    reconcile_mindmap_ai_job_attempt,
    stream_mindmap_ai_job_events,
    validate_mindmap_ai_artifact,
)
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.entity.do.mindmap_ai_do import MINDMAP_AI_EVENT_SEQUENCE_MAX
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiArtifactValidateModel,
    MindmapAiCloudSaveModel,
    MindmapAiConnectorUpdateModel,
    MindmapAiJobCreateModel,
    MindmapAiScopeModel,
)
from module_mindmap.service.mindmap_ai_service import (
    AI_DRAFT_PREVIEW_MAX_VERSION,
    MindmapAiService,
    MindmapAiTaskManager,
    _compatible_persisted_error_code,
    _job_model,
    sanitize_mindmap_ai_event_payload,
)
from server import create_app


class _SessionFactory:
    def __init__(self, database: SimpleNamespace) -> None:
        self.database = database

    def __call__(self) -> '_SessionFactory':
        return self

    async def __aenter__(self) -> SimpleNamespace:
        return self.database

    async def __aexit__(self, *_args: object) -> None:
        return None


class _TrackingSessionFactory(_SessionFactory):
    def __init__(self, database: SimpleNamespace) -> None:
        super().__init__(database)
        self.active_sessions = 0

    async def __aenter__(self) -> SimpleNamespace:
        self.active_sessions += 1
        return await super().__aenter__()

    async def __aexit__(self, *_args: object) -> None:
        self.active_sessions -= 1


async def _empty_stream() -> AsyncGenerator[str, None]:
    if False:
        yield ''


@pytest.mark.parametrize(
    ('raw_value', 'expected'),
    [
        (None, 0),
        ('-8', 0),
        ('invalid', 0),
        (str(MINDMAP_AI_EVENT_SEQUENCE_MAX + 1), MINDMAP_AI_EVENT_SEQUENCE_MAX),
        ('9' * 5_000, 0),
    ],
)
def test_last_event_id_is_clamped_to_database_integer_range(
    raw_value: str | None,
    expected: int,
) -> None:
    assert _parse_last_event_id(raw_value) == expected


@pytest.mark.asyncio
async def test_sse_checks_job_ownership_before_starting_response() -> None:
    database = SimpleNamespace()
    current_user = SimpleNamespace(user=SimpleNamespace(user_id=7))
    with (
        patch(
            'module_mindmap.controller.mindmap_ai_controller.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch.object(MindmapAiDao, 'get_job', new=AsyncMock(return_value=None)) as get_job,
        pytest.raises(HTTPException) as missing,
    ):
        await stream_mindmap_ai_job_events(
            request=SimpleNamespace(),
            job_id='00000000-0000-4000-8000-000000000001',
            current_user=current_user,
            last_event_id=None,
        )

    get_job.assert_awaited_once_with(
        database,
        '00000000-0000-4000-8000-000000000001',
        7,
    )
    assert missing.value.status_code == 404  # noqa: PLR2004
    assert missing.value.detail == 'AI 脑图任务不存在'


@pytest.mark.asyncio
async def test_sse_passes_clamped_cursor_to_replay_stream() -> None:
    database = SimpleNamespace()
    current_user = SimpleNamespace(user=SimpleNamespace(user_id=9))
    stream_factory = Mock(return_value=_empty_stream())
    with (
        patch(
            'module_mindmap.controller.mindmap_ai_controller.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch.object(MindmapAiDao, 'get_job', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_mindmap.controller.mindmap_ai_controller._event_stream',
            new=stream_factory,
        ),
    ):
        response = await stream_mindmap_ai_job_events(
            request=SimpleNamespace(),
            job_id='00000000-0000-4000-8000-000000000002',
            current_user=current_user,
            last_event_id=str(1 << 80),
        )

    stream_factory.assert_called_once_with(
        ANY,
        '00000000-0000-4000-8000-000000000002',
        9,
        MINDMAP_AI_EVENT_SEQUENCE_MAX,
    )
    assert response.headers['cache-control'] == 'no-cache, no-transform'


@pytest.mark.asyncio
async def test_sse_normalizes_unsafe_event_names_and_non_finite_payloads() -> None:
    database = SimpleNamespace()
    job = SimpleNamespace(status='ready')
    event = SimpleNamespace(
        sequence=1,
        event_type='status_changed\nretry: 0',
        payload_json='{"progress": NaN}',
        created_time=datetime(2026, 9, 13, 12, 0, 0),
    )
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    with (
        patch(
            'module_mindmap.controller.mindmap_ai_controller.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch.object(MindmapAiDao, 'get_job', new=AsyncMock(side_effect=[job, job])),
        patch.object(MindmapAiDao, 'list_events', new=AsyncMock(side_effect=[[event], []])),
    ):
        chunks = [chunk async for chunk in _event_stream(request, 'job-id', 3, 0)]

    assert len(chunks) == 1
    assert '\nevent: agent_event\n' in chunks[0]
    assert 'retry: 0' not in chunks[0]
    payload = json.loads(chunks[0].split('\ndata: ', 1)[1].removesuffix('\n\n'))
    assert payload['eventType'] == 'agent_event'
    assert payload['payload'] == {}


@pytest.mark.asyncio
async def test_sse_releases_database_session_before_yielding_to_slow_client() -> None:
    database = SimpleNamespace()
    session_factory = _TrackingSessionFactory(database)
    job = SimpleNamespace(status='running')
    event = SimpleNamespace(
        sequence=1,
        event_type='status_changed',
        payload_json='{"progress":25}',
        created_time=datetime(2026, 9, 13, 12, 0, 0),
    )
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    with (
        patch(
            'module_mindmap.controller.mindmap_ai_controller.AsyncSessionLocal',
            new=session_factory,
        ),
        patch.object(MindmapAiDao, 'get_job', new=AsyncMock(return_value=job)),
        patch.object(MindmapAiDao, 'list_events', new=AsyncMock(return_value=[event])),
    ):
        stream = _event_stream(request, 'job-id', 3, 0)
        chunk = await anext(stream)
        try:
            assert 'id: 1\n' in chunk
            # The consumer is suspended here. Backpressure must not keep the
            # polling session (and its checked-out connection) alive.
            assert session_factory.active_sessions == 0
        finally:
            await stream.aclose()


@pytest.mark.asyncio
async def test_draft_version_is_forwarded_and_actual_version_is_returned_in_header() -> None:
    database = SimpleNamespace()
    current_user = SimpleNamespace(user=SimpleNamespace(user_id=11))
    preview = {'available': True, 'operationCursor': 8, 'document': {'root': {}}}
    with patch(
        'module_mindmap.controller.mindmap_ai_controller.MindmapAiService.get_job_draft_preview',
        new=AsyncMock(return_value=preview),
    ) as get_preview:
        response = await get_mindmap_ai_job_draft(
            request=SimpleNamespace(),
            job_id='00000000-0000-4000-8000-000000000003',
            query_db=database,
            current_user=current_user,
            version=5,
        )

    get_preview.assert_awaited_once_with(
        database,
        '00000000-0000-4000-8000-000000000003',
        11,
        version=5,
    )
    assert response.headers['x-mindmap-ai-preview-version'] == '8'


def test_draft_version_query_is_bounded_in_http_contract() -> None:
    operation = create_app().openapi()['paths']['/mindmap/ai/jobs/{job_id}/draft']['get']
    version = next(item for item in operation['parameters'] if item['name'] == 'version')
    integer_schema = next(
        item for item in version['schema']['anyOf']
        if item.get('type') == 'integer'
    )

    assert version['required'] is False
    assert integer_schema['minimum'] == 0
    assert integer_schema['maximum'] == AI_DRAFT_PREVIEW_MAX_VERSION


def test_job_attempt_reconcile_route_precedes_dynamic_job_route() -> None:
    paths = [route.path for route in create_app().routes]

    assert paths.index('/mindmap/ai/jobs/reconcile') < paths.index('/mindmap/ai/jobs/{job_id}')


@pytest.mark.asyncio
async def test_job_attempt_reconcile_is_owner_scoped_and_not_cached() -> None:
    database = SimpleNamespace()
    current_user = SimpleNamespace(user=SimpleNamespace(user_id=19))
    recovered = {'id': 'recovered-job'}
    with patch(
        'module_mindmap.controller.mindmap_ai_controller.MindmapAiService.reconcile_job_attempt',
        new=AsyncMock(return_value=recovered),
    ) as reconcile:
        response = await reconcile_mindmap_ai_job_attempt(
            request=SimpleNamespace(),
            query_db=database,
            current_user=current_user,
            idempotency_key='mindmap-ai:recovery-key',
        )

    reconcile.assert_awaited_once_with(database, 19, 'mindmap-ai:recovery-key')
    assert response.headers['cache-control'] == 'private, no-store'
    assert json.loads(response.body)['data'] == recovered


@pytest.mark.asyncio
async def test_job_attempt_reconcile_hides_missing_or_other_owner_job() -> None:
    with (
        patch(
            'module_mindmap.controller.mindmap_ai_controller.MindmapAiService.reconcile_job_attempt',
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(HTTPException) as missing,
    ):
        await reconcile_mindmap_ai_job_attempt(
            request=SimpleNamespace(),
            query_db=SimpleNamespace(),
            current_user=SimpleNamespace(user=SimpleNamespace(user_id=23)),
            idempotency_key='mindmap-ai:unknown-key',
        )

    assert missing.value.status_code == 404  # noqa: PLR2004
    assert missing.value.detail == 'AI 脑图任务不存在'


def test_artifact_validation_model_accepts_camel_case_require_passed() -> None:
    model = MindmapAiArtifactValidateModel.model_validate({
        'artifact': {},
        'requirePassed': False,
    })

    assert model.require_passed is False


def test_discussion_contract_requires_message_target() -> None:
    model = MindmapAiJobCreateModel(
        prompt='解释这张脑图的风险',
        intent='discuss',
        target='message',
    )

    assert model.intent == 'discuss'
    assert model.target == 'message'
    with pytest.raises(ValidationError, match='讨论模式只能生成文字消息'):
        MindmapAiJobCreateModel(prompt='讨论', intent='discuss', target='file')
    with pytest.raises(ValidationError, match='只有讨论模式才能生成文字消息'):
        MindmapAiJobCreateModel(prompt='生成', intent='create', target='message')


def test_message_ready_event_never_persists_response_body() -> None:
    assert sanitize_mindmap_ai_event_payload({
        'responseId': 'response-1',
        'content': '不得进入事件正文',
        'contentType': 'text/plain',
    }) == {'responseId': 'response-1'}


@pytest.mark.asyncio
@pytest.mark.parametrize('commit_fails', [False, True], ids=['committed', 'commit-failed'])
async def test_discussion_completion_persists_message_atomically_without_artifact(  # noqa: PLR0915
    commit_fails: bool,
) -> None:
    job_id = '12345678-1234-4234-8234-123456789012'
    session_id = '22345678-1234-4234-8234-123456789012'
    response_content = '当前脑图覆盖登录主流程，建议补充账号锁定场景。'
    request_json = json.dumps({
        'agentKey': 'codex',
        'intent': 'discuss',
        'prompt': '总结当前脑图的覆盖范围',
        'source': {'type': 'none'},
        'target': 'message',
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
        intent='discuss',
        target='message',
        parent_job_id=None,
        session_id=session_id,
        turn_index=1,
        base_revision=None,
        base_hash=None,
        base_room_epoch=None,
    )
    session = SimpleNamespace(
        id=session_id,
        title='总结当前脑图的覆盖范围',
        status='active',
        expires_time=datetime.now() + timedelta(days=1),
    )
    result = AgentMessageResult(
        title='覆盖范围总结',
        content=response_content,
        usage={'inputTokens': 5, 'outputTokens': 7},
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
            'inputTokens': 5,
            'outputTokens': 7,
            'totalTokens': 12,
        }),
        purge_session=AsyncMock(return_value=True),
    )

    class TransactionalDatabase:
        def __init__(self) -> None:
            self.pending: list[tuple[str, object]] = []
            self.durable: list[tuple[str, object]] = []
            self.commit = AsyncMock(side_effect=self.commit_transaction)
            self.rollback = AsyncMock(side_effect=self.rollback_transaction)
            self.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))

        async def commit_transaction(self) -> None:
            if commit_fails:
                raise RuntimeError('commit failed')
            self.durable.extend(self.pending)
            self.pending.clear()

        async def rollback_transaction(self) -> None:
            self.pending.clear()

    database = TransactionalDatabase()

    class TransactionalSessionFactory(_SessionFactory):
        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> None:
            if exc_type is not None:
                await self.database.rollback()

    async def stage_response(db: object, values: dict[str, object]) -> object:
        assert db is database
        database.pending.append(('response', dict(values)))
        return SimpleNamespace(**values)

    async def stage_job(
        db: object,
        persisted_job_id: str,
        values: dict[str, object],
    ) -> None:
        assert db is database
        assert persisted_job_id == job_id
        database.pending.append(('job', dict(values)))

    async def stage_session(
        db: object,
        persisted_session_id: str,
        values: dict[str, object],
    ) -> None:
        assert db is database
        assert persisted_session_id == session_id
        database.pending.append(('session', dict(values)))

    async def stage_event(
        db: object,
        persisted_job_id: str,
        event_type: str,
        payload_json: str,
    ) -> None:
        assert db is database
        assert persisted_job_id == job_id
        database.pending.append((
            'event',
            {'eventType': event_type, 'payload': json.loads(payload_json)},
        ))

    add_response = AsyncMock(side_effect=stage_response)
    update_job = AsyncMock(side_effect=stage_job)
    update_session = AsyncMock(side_effect=stage_session)
    add_event = AsyncMock(side_effect=stage_event)
    add_artifact = AsyncMock()
    add_proposal = AsyncMock()
    set_status = AsyncMock(return_value=True)
    record_event = MagicMock()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=TransactionalSessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=SimpleNamespace(get=lambda _agent_key: adapter),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.resolve_connector_credential',
            return_value={},
        ),
        patch.object(MindmapAiDao, 'get_job', new=AsyncMock(return_value=job)),
        patch.object(MindmapAiDao, 'get_session', new=AsyncMock(return_value=session)),
        patch.object(MindmapAiDao, 'add_response', new=add_response),
        patch.object(MindmapAiDao, 'update_job', new=update_job),
        patch.object(MindmapAiDao, 'update_session', new=update_session),
        patch.object(MindmapAiDao, 'add_event', new=add_event),
        patch.object(MindmapAiDao, 'add_artifact', new=add_artifact),
        patch.object(MindmapAiDao, 'add_proposal', new=add_proposal),
        patch.object(
            MindmapAiService,
            '_ensure_connector_available',
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_visible_discussion_history',
            new=AsyncMock(return_value=()),
        ),
        patch.object(MindmapAiTaskManager, '_set_status', new=set_status),
        patch.object(
            MindmapAiTaskManager,
            '_owns_current_job_lease',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_run',
            new=MagicMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event',
            new=record_event,
        ),
    ):
        await MindmapAiTaskManager._run_job(job_id)

    add_artifact.assert_not_awaited()
    add_proposal.assert_not_awaited()
    assert database.pending == []

    if commit_fails:
        assert database.durable == []
        database.rollback.assert_awaited_once()
        terminal_status = set_status.await_args_list[-1]
        assert terminal_status.args[:3] == (job_id, 'failed', 100)
        assert terminal_status.kwargs['error_code'] == 'AI_AGENT_UNAVAILABLE'
        record_event.assert_not_called()
        return

    database.commit.assert_awaited_once()
    database.rollback.assert_not_awaited()
    assert [record_type for record_type, _record in database.durable] == [
        'response',
        'job',
        'session',
        'event',
    ]
    durable = dict(database.durable)
    response_record = durable['response']
    job_record = durable['job']
    event_record = durable['event']
    assert isinstance(response_record, dict)
    assert isinstance(job_record, dict)
    assert isinstance(event_record, dict)
    assert response_record['content_text'] == response_content
    assert response_record['content_hash'] == hashlib.sha256(
        response_content.encode('utf-8'),
    ).hexdigest()
    assert job_record['status'] == 'completed_message'
    assert job_record['artifact_id'] is None
    assert job_record['proposal_id'] is None
    assert job_record['response_id'] == response_record['id']
    assert event_record == {
        'eventType': 'message_ready',
        'payload': {'responseId': response_record['id']},
    }
    record_event.assert_called_once_with('message_ready')


def test_scope_limits_each_selected_node_uid() -> None:
    with pytest.raises(ValidationError):
        MindmapAiScopeModel(type='selectedNodes', nodeUids=['x' * 65])
    scope = MindmapAiScopeModel(type='selectedNodes', nodeUids=['node-1', 'node-1'])
    assert scope.node_uids == ['node-1']


def test_connector_rejects_empty_or_malformed_credential_references() -> None:
    assert (
        MindmapAiConnectorUpdateModel(credentialRef='  env://OPENAI_API_KEY  ').credential_ref
        == 'env://OPENAI_API_KEY'
    )
    for credential_ref in ('env://', 'env://lowercase', 'secret://', 'secret://has space'):
        with pytest.raises(ValidationError):
            MindmapAiConnectorUpdateModel(credentialRef=credential_ref)
    with pytest.raises(ValidationError):
        MindmapAiConnectorUpdateModel(maxBudgetUsd=0.00001)


def test_cloud_save_name_is_trimmed_and_rejects_invisible_names() -> None:
    assert MindmapAiCloudSaveModel(name='  新脑图  ').name == '新脑图'
    with pytest.raises(ValidationError, match='名称不能为空'):
        MindmapAiCloudSaveModel(name='   ')
    with pytest.raises(ValidationError, match='控制字符'):
        MindmapAiCloudSaveModel(name='脑图\x00名称')


@pytest.mark.asyncio
async def test_artifact_validation_preserves_stable_error_code() -> None:
    model = MindmapAiArtifactValidateModel(artifact={})
    with (
        patch(
            'module_mindmap.controller.mindmap_ai_controller.validate_smm_artifact',
            side_effect=MindmapArtifactError(
                'AI 脑图文件已过期',
                code='AI_ARTIFACT_EXPIRED',
            ),
        ),
        pytest.raises(ServiceException) as invalid,
    ):
        await validate_mindmap_ai_artifact(SimpleNamespace(), model)

    assert invalid.value.message == 'AI 脑图文件已过期'
    assert invalid.value.data == {'errorCode': 'AI_ARTIFACT_EXPIRED'}


@pytest.mark.parametrize('message', [
    '生成结果包含 102 个节点，超过上限 100',
    'Agent 输出超过任务结构上限（最终节点 101/100，最终层级 5/8）',
    'Agent 输出超过任务结构上限（累计新增节点 102/100，最终层级 4/6）',
    'AI 脑图节点数量不能超过100',
    'AI 脑图层级不能超过64',
    'AI 脑图规范文档不能超过1800000字节',
    'AI 脑图文件不能超过2000000字节',
])
def test_legacy_persisted_result_limit_is_read_as_budget(message: str) -> None:
    assert _compatible_persisted_error_code(
        'AI_OUTPUT_INVALID', message,
    ) == 'AI_BUDGET_EXCEEDED'
    assert sanitize_mindmap_ai_event_payload({
        'status': 'failed',
        'errorCode': 'AI_OUTPUT_INVALID',
        'errorMessage': message,
    })['errorCode'] == 'AI_BUDGET_EXCEEDED'


@pytest.mark.parametrize('message', [
    'AI 脑图节点数量不能超过100',
    'AI 脑图层级不能超过32',
    'AI 脑图规范文档不能超过1800000字节',
    'AI 脑图文件不能超过2000000字节',
])
def test_legacy_persisted_generated_size_input_code_is_read_as_budget(
    message: str,
) -> None:
    assert _compatible_persisted_error_code(
        'AI_INPUT_TOO_LARGE', message,
    ) == 'AI_BUDGET_EXCEEDED'


def test_legacy_persisted_job_snapshot_exposes_corrected_budget_code() -> None:
    now = datetime.now()
    job = SimpleNamespace(
        id='job-legacy-limit',
        session_id='session-legacy-limit',
        parent_job_id=None,
        retry_of_job_id=None,
        turn_index=1,
        agent_key='codex',
        adapter_version='1.0.0',
        sdk_version='1.0.0',
        runtime_version='1.0.0',
        model_ref='gpt-5.6-terra',
        max_budget_usd=5,
        timeout_seconds=900,
        max_nodes=100,
        max_depth=8,
        retention_days=30,
        intent='create',
        target='proposal',
        source_type='none',
        source_mindmap_id=None,
        base_revision=None,
        base_hash=None,
        base_room_epoch=None,
        status='failed',
        progress=100,
        title=None,
        artifact_id=None,
        proposal_id=None,
        usage_json=None,
        error_code='AI_OUTPUT_INVALID',
        error_message='生成结果包含 102 个节点，超过上限 100',
        created_time=now,
        update_time=now,
        completed_time=now,
        expires_time=now + timedelta(days=30),
    )

    model = _job_model(job)

    assert model.error_code == 'AI_BUDGET_EXCEEDED'
    assert model.error_message == job.error_message


@pytest.mark.parametrize('message', [
    'AI Artifact 缺少 manifest',
    '生成结果包含 100 个节点，超过上限 100',
    '生成结果包含 102 个节点，超过上限 100；provider detail',
    'Agent 输出超过任务结构上限（最终节点 99/100，最终层级 5/8）',
])
def test_legacy_compatibility_does_not_reclassify_unverified_messages(message: str) -> None:
    assert _compatible_persisted_error_code(
        'AI_OUTPUT_INVALID', message,
    ) == 'AI_OUTPUT_INVALID'


@pytest.mark.asyncio
async def test_invalid_source_snapshot_is_classified_as_input_not_ai_output() -> None:
    request = MindmapAiJobCreateModel.model_validate({
        'prompt': '创建脑图',
        'intent': 'create',
        'source': {'type': 'none'},
    })
    with (
        patch.object(
            MindmapAiService,
            '_prepare_source',
            new=AsyncMock(side_effect=MindmapArtifactError('来源结构无效')),
        ),
        pytest.raises(ServiceException) as invalid,
    ):
        await MindmapAiService._prepare_source_for_job(
            SimpleNamespace(), request, user_id=7,
        )

    assert invalid.value.data == {'errorCode': 'AI_INPUT_INVALID'}
    assert invalid.value.message == '来源结构无效'


@pytest.mark.asyncio
async def test_uploaded_artifact_validation_uses_input_error_contract() -> None:
    model = MindmapAiArtifactValidateModel(artifact={})
    with pytest.raises(ServiceException) as invalid:
        await validate_mindmap_ai_artifact(SimpleNamespace(), model)

    assert invalid.value.data == {'errorCode': 'AI_INPUT_INVALID'}
    assert invalid.value.message == 'SMM 文件格式标识无效'


def test_download_filename_supports_unicode_without_invalid_http_header() -> None:
    value = _artifact_content_disposition('登录流程：冒烟测试', draft=True)

    value.encode('latin-1')
    assert 'filename="ai-mindmap.draft.smm"' in value
    assert "filename*=UTF-8''" in value
    assert '%E7%99%BB%E5%BD%95' in value


@pytest.mark.asyncio
async def test_add_event_drops_late_callback_after_job_deletion() -> None:
    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = None
    database = SimpleNamespace(
        execute=AsyncMock(return_value=lock_result),
        scalar=AsyncMock(),
        add=Mock(),
        flush=AsyncMock(),
    )

    event = await MindmapAiDao.add_event(database, 'deleted-job', 'agent_event', '{}')

    assert event is None
    database.scalar.assert_not_awaited()
    database.add.assert_not_called()
    database.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_event_rejects_sequence_overflow_before_database_insert() -> None:
    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = 'job-id'
    database = SimpleNamespace(
        execute=AsyncMock(return_value=lock_result),
        scalar=AsyncMock(return_value=MINDMAP_AI_EVENT_SEQUENCE_MAX),
        add=Mock(),
        flush=AsyncMock(),
    )

    with pytest.raises(OverflowError, match='事件序号'):
        await MindmapAiDao.add_event(database, 'job-id', 'agent_event', '{}')

    database.add.assert_not_called()
    database.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_event_normalizes_untrusted_event_type() -> None:
    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = 'job-id'
    database = SimpleNamespace(
        execute=AsyncMock(return_value=lock_result),
        scalar=AsyncMock(return_value=0),
        add=Mock(),
        flush=AsyncMock(),
    )

    event = await MindmapAiDao.add_event(
        database,
        'job-id',
        'status_changed\nretry: 0',
        '{}',
    )

    assert event is not None
    assert event.event_type == 'agent_event'


@pytest.mark.asyncio
async def test_add_event_drops_provider_callback_that_loses_terminal_status_race() -> None:
    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = 'cancelled'
    database = SimpleNamespace(
        execute=AsyncMock(return_value=lock_result),
        scalar=AsyncMock(),
        add=Mock(),
        flush=AsyncMock(),
    )

    event = await MindmapAiDao.add_event(database, 'job-id', 'tool_completed', '{}')

    assert event is None
    database.scalar.assert_not_awaited()
    database.add.assert_not_called()


@pytest.mark.asyncio
async def test_add_event_keeps_terminal_status_transition_event() -> None:
    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = 'cancelled'
    database = SimpleNamespace(
        execute=AsyncMock(return_value=lock_result),
        scalar=AsyncMock(return_value=2),
        add=Mock(),
        flush=AsyncMock(),
    )

    event = await MindmapAiDao.add_event(database, 'job-id', 'status_changed', '{}')

    assert event is not None
    assert event.sequence == 3  # noqa: PLR2004
    database.add.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_add_event_keeps_local_undo_event_after_undone_transition() -> None:
    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = 'undone'
    database = SimpleNamespace(
        execute=AsyncMock(return_value=lock_result),
        scalar=AsyncMock(return_value=4),
        add=Mock(),
        flush=AsyncMock(),
    )

    event = await MindmapAiDao.add_event(database, 'job-id', 'local_undone', '{}')

    assert event is not None
    assert event.event_type == 'local_undone'
    assert event.sequence == 5  # noqa: PLR2004
    database.add.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_event_replay_query_clamps_cursor_and_page_size() -> None:
    result = MagicMock()
    result.scalars.return_value = []
    database = SimpleNamespace(execute=AsyncMock(return_value=result))

    events = await MindmapAiDao.list_events(
        database,
        'job-id',
        1 << 80,
        limit=50_000,
    )

    statement = database.execute.await_args.args[0]
    assert events == []
    assert statement.compile().params == {
        'job_id_1': 'job-id',
        'sequence_1': MINDMAP_AI_EVENT_SEQUENCE_MAX,
        'param_1': 1_000,
    }


@pytest.mark.asyncio
async def test_session_cancellation_is_one_durable_conditional_update() -> None:
    requested_time = datetime.now()
    database = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=4)),
    )

    changed = await MindmapAiDao.request_session_job_cancellations(
        database,
        'session-delete',
        requested_time,
    )

    statement = database.execute.await_args.args[0]
    statement_text = str(statement)
    parameter_values = list(statement.compile().params.values())
    assert statement_text.startswith('UPDATE mindmap_ai_job SET')
    assert 'mindmap_ai_job.session_id =' in statement_text
    assert 'mindmap_ai_job.status IN' in statement_text
    assert 'coalesce(mindmap_ai_job.cancel_requested_time' in statement_text
    assert 'session-delete' in parameter_values
    assert requested_time in parameter_values
    assert any(
        set(value) == {'queued', 'preparing', 'running', 'validating', 'cancel_requested'}
        for value in parameter_values
        if isinstance(value, (list, tuple))
    )
    assert changed == 4  # noqa: PLR2004


@pytest.mark.asyncio
async def test_delete_job_payloads_locks_jobs_before_deleting_children() -> None:
    lock_result = MagicMock()
    lock_result.scalars.return_value = ['job-2', 'job-1']
    write_results = [SimpleNamespace(rowcount=1) for _ in range(7)]
    database = SimpleNamespace(
        execute=AsyncMock(side_effect=[lock_result, *write_results]),
    )

    counts = await MindmapAiDao.delete_job_payloads(database, ['job-1', 'job-2'])

    first_statement = str(database.execute.await_args_list[0].args[0])
    assert first_statement.startswith('SELECT mindmap_ai_job.id')
    assert 'ORDER BY mindmap_ai_job.id ASC' in first_statement
    assert first_statement.endswith('FOR UPDATE')
    assert counts == {
        'events': 1,
        'checkpoints': 1,
        'undos': 1,
        'proposals': 1,
        'artifacts': 1,
        'responses': 1,
        'jobs': 1,
    }
