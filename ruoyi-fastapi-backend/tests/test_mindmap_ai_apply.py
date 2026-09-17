"""AI Proposal 的条件应用与撤销安全测试。"""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from pydantic import ValidationError

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.ai.diff import build_document_diff, build_legacy_document_diff_v0
from module_mindmap.ai.document import (
    AI_MAX_FILE_BYTES,
    MindmapArtifactError,
    build_smm_artifact,
    compute_document_hash,
    normalize_ai_document,
    normalize_ai_editable_source_document,
)
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiCloudApplyModel,
    MindmapAiCloudSaveModel,
    MindmapAiJobCreateModel,
    MindmapAiLocalApplyAckModel,
    MindmapAiLocalUndoAckModel,
)
from module_mindmap.service.mindmap_ai_service import MindmapAiService, MindmapAiTaskManager
from module_mindmap.service.mindmap_creation_service import MindmapCreationService

EXPECTED_LOCAL_APPLIED_REVISION = 7
CLOUD_SAVED_MINDMAP_ID = 42
EXPECTED_BARRIER_ROLLBACK_COUNT = 2
EXPECTED_TRUSTED_AI_APPLIED_REVISION = 6


def _document(text: str = '根节点') -> dict:
    return {
        'root': {'data': {'uid': 'root', 'text': text}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }


def _detail(document: dict, revision: int) -> SimpleNamespace:
    normalized, _summary = normalize_ai_document(document, content_policy='source')
    return SimpleNamespace(
        node_tree=normalized['root'],
        layout=normalized['layout'],
        theme=normalized['theme'],
        view_data=normalized['view'],
        document_data=normalized['documentData'],
        content_revision=revision,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'changed_model',
    [
        MindmapAiCloudSaveModel(name='修改后的名称', folder_id=11),
        MindmapAiCloudSaveModel(name='原始名称', folder_id=12),
    ],
)
async def test_cloud_save_idempotency_binds_resolved_name_and_folder(
    changed_model: MindmapAiCloudSaveModel,
) -> None:
    """Exact retries replay, while the same key cannot silently change its destination."""
    artifact_id = 'artifact-cloud-save'
    idempotency_key = 'cloud-save-idempotency-key'
    record = SimpleNamespace(
        job_id='job-cloud-save',
        title='原始产物名称',
        validation_status='passed',
        document_hash='document-hash',
        expires_time=datetime.now() + timedelta(days=1),
    )
    artifact = {'document': _document('云端另存')}
    database = SimpleNamespace(commit=AsyncMock())
    first_model = MindmapAiCloudSaveModel(name='原始名称', folder_id=11)
    saved_context = None

    async def emulate_idempotent_creation(
        _db: object,
        _mindmap: object,
        *,
        creation_request_id: str,
        creation_operation: str,
        creation_intent: dict,
    ) -> CrudResponseModel:
        nonlocal saved_context
        context = MindmapCreationService.build_context(
            creation_request_id,
            creation_operation,
            creation_intent,
        )
        if saved_context is None:
            saved_context = context
        elif saved_context.request_fingerprint != context.request_fingerprint:
            raise ServiceException(message='Idempotency-Key 已用于不同的脑图创建请求')
        return CrudResponseModel(
            is_success=True,
            message='新增成功',
            result={
                'id': CLOUD_SAVED_MINDMAP_ID,
                'idempotentReplay': saved_context is not context,
            },
        )

    with (
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.add_mindmap_services',
            new=AsyncMock(side_effect=emulate_idempotent_creation),
        ) as add_mindmap,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.extend_result_expiration',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ),
        patch('module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event'),
    ):
        first = await MindmapAiService.save_artifact_cloud(
            database,
            artifact_id,
            user_id=7,
            user_name='tester',
            model=first_model,
            idempotency_key=idempotency_key,
        )
        replay = await MindmapAiService.save_artifact_cloud(
            database,
            artifact_id,
            user_id=7,
            user_name='tester',
            model=first_model,
            idempotency_key=idempotency_key,
        )
        with pytest.raises(ServiceException) as conflict:
            await MindmapAiService.save_artifact_cloud(
                database,
                artifact_id,
                user_id=7,
                user_name='tester',
                model=changed_model,
                idempotency_key=idempotency_key,
            )

    assert first['id'] == replay['id'] == CLOUD_SAVED_MINDMAP_ID
    assert replay['idempotentReplay'] is True
    assert conflict.value.message == 'Idempotency-Key 已用于不同的脑图创建请求'
    assert add_mindmap.await_args_list[0].kwargs['creation_intent'] == {
        'artifactId': artifact_id,
        'documentHash': record.document_hash,
        'name': '原始名称',
        'folderId': 11,
    }


class _SessionFactory:
    def __call__(self) -> '_SessionFactory':
        return self

    async def __aenter__(self) -> SimpleNamespace:
        return SimpleNamespace()

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_idempotent_replay_reschedules_only_persisted_queued_jobs() -> None:
    with patch.object(MindmapAiTaskManager, 'schedule') as schedule:
        MindmapAiService._schedule_replayed_job(SimpleNamespace(id='queued-job', status='queued'))
        MindmapAiService._schedule_replayed_job(SimpleNamespace(id='running-job', status='running'))

    schedule.assert_called_once_with('queued-job')


@pytest.mark.asyncio
async def test_local_apply_replay_rejects_a_different_document_or_revision() -> None:
    proposal = SimpleNamespace(
        id='proposal-applied',
        job_id='job-applied',
        status='applied',
        base_document_id='document-a',
        result_hash='result-hash',
        applied_revision=8,
    )
    database = SimpleNamespace()

    with patch(
        'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
        new=AsyncMock(return_value=proposal),
    ):
        for document_id, revision in [('document-b', 8), ('document-a', 9)]:
            with pytest.raises(ServiceException) as conflict:
                await MindmapAiService.ack_local_apply(
                    database,
                    proposal.id,
                    user_id=7,
                    model=MindmapAiLocalApplyAckModel(
                        document_id=document_id,
                        revision=revision,
                        result_hash='result-hash',
                    ),
                )
            assert conflict.value.message == 'AI 脑图提案应用回执冲突'
            assert conflict.value.data == {'errorCode': 'AI_LOCAL_ACK_CONFLICT'}


@pytest.mark.asyncio
async def test_local_apply_endpoints_reject_a_persisted_cloud_proposal() -> None:
    proposal = SimpleNamespace(
        id='proposal-cloud-channel',
        job_id='job-cloud-channel',
        status='ready',
        base_document_id=None,
        target_mindmap_id=42,
    )
    get_artifact = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch.object(MindmapAiService, 'get_artifact', new=get_artifact),
    ):
        calls = (
            lambda: MindmapAiService.prepare_local_apply(
                SimpleNamespace(), proposal.id, user_id=7,
            ),
            lambda: MindmapAiService.ack_local_apply(
                SimpleNamespace(),
                proposal.id,
                user_id=7,
                model=MindmapAiLocalApplyAckModel(
                    document_id='local-document',
                    revision=2,
                    result_hash='result-hash',
                ),
            ),
            lambda: MindmapAiService.ack_local_undo(
                SimpleNamespace(),
                proposal.id,
                user_id=7,
                model=MindmapAiLocalUndoAckModel(
                    document_id='local-document',
                    revision=3,
                    result_hash='result-hash',
                    reverted_hash='base-hash',
                ),
            ),
        )
        for call in calls:
            with pytest.raises(ServiceException) as blocked:
                await call()
            assert blocked.value.message == 'AI 脑图提案不是本地应用提案'

    get_artifact.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(('initial_status', 'initial_applied_revision'), [
    ('applied', EXPECTED_LOCAL_APPLIED_REVISION),
    # The browser may undo before a temporarily failed apply ACK reaches the
    # server. A single undo receipt must settle that state without replaying the
    # document mutation.
    ('prepared', None),
])
async def test_local_undo_ack_is_atomic_and_can_supersede_a_lost_apply_ack(
    initial_status: str,
    initial_applied_revision: int | None,
) -> None:
    proposal = SimpleNamespace(
        id='proposal-local-undo',
        job_id='job-local-undo',
        status=initial_status,
        base_document_id='local:document-a',
        base_revision=6,
        base_hash='base-hash',
        result_hash='result-hash',
        applied_revision=initial_applied_revision,
        result_artifact_id='artifact-local-undo',
        expires_time=datetime.now() + timedelta(days=1),
    )
    locked_job = MagicMock()
    locked_job.scalar_one_or_none.return_value = 'undone'
    database = SimpleNamespace(
        commit=AsyncMock(),
        execute=AsyncMock(return_value=locked_job),
        scalar=AsyncMock(return_value=7),
        add=Mock(),
        flush=AsyncMock(),
    )
    update_proposal = AsyncMock()
    update_job = AsyncMock()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=update_proposal,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=update_job,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event',
        ) as metric,
    ):
        result = await MindmapAiService.ack_local_undo(
            database,
            proposal.id,
            user_id=7,
            model=MindmapAiLocalUndoAckModel(
                document_id='local:document-a',
                revision=8,
                result_hash='result-hash',
                reverted_hash='base-hash',
            ),
        )

    assert result == {
        'proposalId': proposal.id,
        'status': 'undone',
        'idempotentReplay': False,
    }
    update_proposal.assert_awaited_once()
    actual_values = update_proposal.await_args.args[2]
    assert actual_values['status'] == 'undone'
    if initial_applied_revision is None:
        assert actual_values['applied_revision'] == EXPECTED_LOCAL_APPLIED_REVISION
        assert isinstance(actual_values['applied_time'], datetime)
    update_job.assert_awaited_once()
    assert update_job.await_args.args[2]['status'] == 'undone'
    database.add.assert_called_once()
    persisted_event = database.add.call_args.args[0]
    assert persisted_event.event_type == 'local_undone'
    assert persisted_event.sequence == 8  # noqa: PLR2004
    database.flush.assert_awaited_once()
    database.commit.assert_awaited_once()
    metric.assert_called_once_with('local_undone')


@pytest.mark.asyncio
async def test_local_undo_ack_replay_and_conflicts_are_fail_closed() -> None:
    proposal = SimpleNamespace(
        id='proposal-local-undone',
        job_id='job-local-undone',
        status='undone',
        base_document_id='local:document-a',
        base_revision=6,
        base_hash='base-hash',
        result_hash='result-hash',
        applied_revision=7,
    )
    database = SimpleNamespace()
    get_proposal = AsyncMock(return_value=proposal)
    with patch(
        'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
        new=get_proposal,
    ):
        replay = await MindmapAiService.ack_local_undo(
            database,
            proposal.id,
            user_id=7,
            model=MindmapAiLocalUndoAckModel(
                document_id='local:document-a',
                revision=8,
                result_hash='result-hash',
                reverted_hash='base-hash',
            ),
        )
        assert replay['idempotentReplay'] is True

        for overrides in (
            {'document_id': 'local:other'},
            {'revision': 9},
            {'result_hash': 'other-result'},
            {'reverted_hash': 'other-base'},
        ):
            values = {
                'document_id': 'local:document-a',
                'revision': 8,
                'result_hash': 'result-hash',
                'reverted_hash': 'base-hash',
                **overrides,
            }
            with pytest.raises(ServiceException) as conflict:
                await MindmapAiService.ack_local_undo(
                    database,
                    proposal.id,
                    user_id=7,
                    model=MindmapAiLocalUndoAckModel(**values),
                )
            assert conflict.value.message == 'AI 脑图提案撤销回执冲突'
            assert conflict.value.data == {'errorCode': 'AI_LOCAL_ACK_CONFLICT'}


@pytest.mark.asyncio
async def test_cloud_proposal_creation_requires_edit_access_before_reading_content() -> None:
    request_model = MindmapAiJobCreateModel.model_validate({
        'agentKey': 'codex',
        'intent': 'expand',
        'prompt': '扩写当前脑图',
        'source': {'type': 'cloud_document', 'mindmapId': 42},
        'target': 'proposal',
    })
    access_error = ServiceException(message='无编辑权限')
    database = SimpleNamespace()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(side_effect=access_error),
        ) as check_access,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.get_mindmap_detail_services',
            new=AsyncMock(),
        ) as get_detail,
        pytest.raises(ServiceException) as blocked,
    ):
        await MindmapAiService._prepare_source(
            database,
            request_model,
            user_id=7,
        )

    check_access.assert_awaited_once_with(
        database,
        42,
        7,
        require_edit=True,
    )
    assert blocked.value.message == '无编辑权限'
    get_detail.assert_not_awaited()


def test_uploaded_source_requires_exactly_one_artifact_or_document() -> None:
    artifact, _summary = build_smm_artifact(
        _document(),
        title='上传脑图',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='test-1',
    )

    for source in (
        {'type': 'uploaded_artifact'},
        {'type': 'uploaded_artifact', 'artifact': artifact, 'document': _document()},
    ):
        with pytest.raises(ValidationError, match='必须且只能提供'):
            MindmapAiJobCreateModel.model_validate({
                'prompt': '扩写文件',
                'intent': 'expand',
                'source': source,
            })


@pytest.mark.parametrize(
    ('source', 'expected_message'),
    [
        (
            {
                'type': 'local_snapshot',
                'documentId': 'local-document',
                'mindmapId': 42,
                'revision': 1,
                'document': _document(),
            },
            '本地脑图来源不能携带云端脑图标识',
        ),
        (
            {
                'type': 'cloud_document',
                'mindmapId': 42,
                'documentId': 'local-document',
            },
            '云端脑图来源不能携带本地文档标识',
        ),
        (
            {
                'type': 'uploaded_artifact',
                'mindmapId': 42,
                'document': _document(),
            },
            '上传文件来源不能携带本地或云端脑图标识',
        ),
        (
            {'type': 'none', 'document': _document()},
            '新建脑图来源不能携带现有文档',
        ),
    ],
)
def test_source_types_reject_cross_channel_fields(
    source: dict,
    expected_message: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        MindmapAiJobCreateModel.model_validate({
            'prompt': '生成脑图',
            'intent': 'create',
            'source': source,
        })


def test_empty_and_uploaded_sources_keep_their_valid_field_matrix() -> None:
    empty_source = MindmapAiJobCreateModel.model_validate({
        'prompt': '生成脑图',
        'intent': 'create',
        'source': {'type': 'none'},
    })
    uploaded_source = MindmapAiJobCreateModel.model_validate({
        'prompt': '扩写脑图',
        'intent': 'expand',
        'source': {
            'type': 'uploaded_artifact',
            'document': _document(),
            'revision': 0,
            'documentHash': 'client-hash',
        },
    })

    assert empty_source.source.type == 'none'
    assert uploaded_source.source.type == 'uploaded_artifact'


@pytest.mark.asyncio
async def test_uploaded_source_accepts_valid_artifact_or_raw_document() -> None:
    document = _document('上传脑图')
    document['root']['data']['onClick'] = 'alert(1)'
    document['root']['data']['image'] = 'data:image/png;base64,AAAA'
    artifact, _summary = build_smm_artifact(
        document,
        title='上传脑图',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='test-1',
        preserve_source_content=True,
    )

    artifact_request = MindmapAiJobCreateModel.model_validate({
        'prompt': '扩写文件',
        'intent': 'expand',
        'source': {'type': 'uploaded_artifact', 'artifact': artifact},
    })
    raw_document_request = MindmapAiJobCreateModel.model_validate({
        'prompt': '扩写文件',
        'intent': 'expand',
        'source': {'type': 'uploaded_artifact', 'document': document},
    })

    artifact_source = await MindmapAiService._prepare_source(
        SimpleNamespace(), artifact_request, user_id=7,
    )
    raw_source = await MindmapAiService._prepare_source(
        SimpleNamespace(), raw_document_request, user_id=7,
    )

    for prepared in (artifact_source, raw_source):
        prepared_document, _revision, document_hash, mindmap_id, room_epoch = prepared
        assert prepared_document is not None
        assert prepared_document['root']['data']['text'] == '上传脑图'
        assert 'onClick' not in prepared_document['root']['data']
        assert prepared_document['root']['data']['image'].startswith('data:image/png')
        assert document_hash == compute_document_hash(prepared_document)
        assert mindmap_id is None
        assert room_epoch is None


@pytest.mark.asyncio
async def test_local_snapshot_accepts_a_new_blank_canvas_with_matching_hash() -> None:
    document = _document('')
    normalized, _summary = normalize_ai_editable_source_document(document)
    request = MindmapAiJobCreateModel.model_validate({
        'prompt': '从空白画布创建脑图',
        'intent': 'create',
        'source': {
            'type': 'local_snapshot',
            'documentId': 'local:blank',
            'revision': 1,
            'documentHash': compute_document_hash(normalized),
            'document': document,
        },
        'target': 'proposal',
    })

    prepared, revision, document_hash, mindmap_id, room_epoch = (
        await MindmapAiService._prepare_source(SimpleNamespace(), request, user_id=7)
    )

    assert prepared['root']['data']['text'] == '未命名节点'
    assert revision == 1
    assert document_hash == compute_document_hash(prepared)
    assert mindmap_id is None
    assert room_epoch is None


@pytest.mark.asyncio
async def test_create_job_maps_invalid_source_to_a_safe_service_error() -> None:
    request = MindmapAiJobCreateModel.model_validate({
        'agentKey': 'codex',
        'prompt': '扩写脑图',
        'intent': 'expand',
        'source': {
            'type': 'local_snapshot',
            'documentId': 'local:invalid',
            'revision': 1,
            'document': _document(),
        },
        'target': 'proposal',
    })
    manifest = SimpleNamespace(
        agent_key='codex',
        intents={'expand'},
        input_types={'local_snapshot'},
    )
    registry = SimpleNamespace(get=lambda _key: SimpleNamespace(
        get_manifest=lambda: manifest,
    ))

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=None),
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
            '_prepare_source',
            new=AsyncMock(side_effect=MindmapArtifactError(
                '脑图来源无效',
                code='AI_INPUT_TOO_LARGE',
            )),
        ),
        pytest.raises(ServiceException) as blocked,
    ):
        await MindmapAiService.create_job(
            SimpleNamespace(),
            request,
            user_id=7,
            idempotency_key='source-error-test',
        )

    assert blocked.value.message == '脑图来源无效'
    assert blocked.value.data == {'errorCode': 'AI_INPUT_TOO_LARGE'}


@pytest.mark.asyncio
async def test_uploaded_raw_document_enforces_file_size_and_link_policy() -> None:
    oversized = _document()
    oversized['ignoredTopLevelPadding'] = 'x' * AI_MAX_FILE_BYTES
    oversized_request = MindmapAiJobCreateModel.model_validate({
        'prompt': '扩写文件',
        'intent': 'expand',
        'source': {'type': 'uploaded_artifact', 'document': oversized},
    })

    with pytest.raises(MindmapArtifactError) as too_large:
        await MindmapAiService._prepare_source(
            SimpleNamespace(), oversized_request, user_id=7,
        )
    assert too_large.value.code == 'AI_INPUT_TOO_LARGE'

    unsafe_link = _document()
    unsafe_link['root']['data']['hyperlink'] = 'javascript:alert(1)'
    unsafe_request = MindmapAiJobCreateModel.model_validate({
        'prompt': '扩写文件',
        'intent': 'expand',
        'source': {'type': 'uploaded_artifact', 'document': unsafe_link},
    })
    with pytest.raises(MindmapArtifactError, match='链接仅支持'):
        await MindmapAiService._prepare_source(
            SimpleNamespace(), unsafe_request, user_id=7,
        )


@pytest.mark.asyncio
async def test_late_adapter_result_is_discarded_after_cross_worker_cancel() -> None:
    async def late_result() -> str:
        return 'must-not-be-committed'

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(status='cancelled')),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await MindmapAiTaskManager._await_adapter_result('job-cancelled', late_result())


@pytest.mark.asyncio
async def test_cancel_closes_local_task_even_when_adapter_cancel_fails() -> None:
    async def wait_forever() -> None:
        await asyncio.Event().wait()

    local_task = asyncio.create_task(wait_forever())
    MindmapAiTaskManager._tasks['job-adapter-error'] = local_task
    adapter = SimpleNamespace(cancel=AsyncMock(side_effect=RuntimeError('provider secret')))
    registry = SimpleNamespace(get=lambda _agent_key: adapter)
    try:
        with patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ):
            cancelled = await MindmapAiTaskManager.cancel('job-adapter-error', 'claude')
        await asyncio.gather(local_task, return_exceptions=True)
    finally:
        MindmapAiTaskManager._tasks.pop('job-adapter-error', None)

    assert cancelled is True
    assert local_task.cancelled()


@pytest.mark.asyncio
async def test_cancel_always_closes_job_even_when_local_task_accepts_immediate_cancel() -> None:
    operation_order: list[str] = []
    original = SimpleNamespace(status='queued', agent_key='codex', execution_epoch=6)
    cancelled = SimpleNamespace(status='cancelled', agent_key='codex')
    db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: operation_order.append('commit')))

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(side_effect=[original, cancelled]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ) as update_job,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.transition_job_status',
            new=AsyncMock(return_value=True),
        ) as transition,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ) as add_event,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.delete_draft_checkpoint',
            new=AsyncMock(side_effect=lambda *_args: operation_order.append('delete-checkpoint')),
        ) as delete_checkpoint,
        patch.object(
            MindmapAiTaskManager,
            'mark_draft_terminal',
            new=AsyncMock(side_effect=lambda *_args: operation_order.append('mark-terminal')),
        ) as mark_terminal,
        patch.object(
            MindmapAiTaskManager,
            'cancel',
            new=AsyncMock(side_effect=lambda *_args: operation_order.append('cancel-local') or True),
        ) as cancel,
        patch(
            'module_mindmap.service.mindmap_ai_service._job_model',
            new=lambda value: value,
        ),
    ):
        result = await MindmapAiService.cancel_job(db, 'job-immediate', 7)

    assert result is cancelled
    update_job.assert_awaited_once()
    cancel.assert_awaited_once_with('job-immediate', 'codex')
    delete_checkpoint.assert_awaited_once_with(db, 'job-immediate')
    mark_terminal.assert_awaited_once_with('job-immediate', 6)
    assert operation_order == [
        'delete-checkpoint',
        'commit',
        'mark-terminal',
        'cancel-local',
    ]
    db.commit.assert_awaited_once()
    assert transition.await_args.args[2] == frozenset({'cancel_requested'})
    assert transition.await_args.args[3]['status'] == 'cancelled'
    assert [call.args[2] for call in add_event.await_args_list] == [
        'cancel_requested', 'status_changed',
    ]


@pytest.mark.asyncio
async def test_status_cas_rejection_does_not_overwrite_terminal_job_or_emit_event() -> None:
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return db

        async def __aexit__(self, *_args: object) -> None:
            return None

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.transition_job_status',
            new=AsyncMock(return_value=False),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ) as add_event,
    ):
        changed = await MindmapAiTaskManager._set_status(
            'already-cancelled',
            'failed',
            100,
            error_code='AI_OUTPUT_INVALID',
        )

    assert changed is False
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    add_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_apply_rejects_request_baseline_before_reading_or_writing_document() -> None:
    proposal = SimpleNamespace(
        id='proposal-1',
        job_id='job-1',
        target_mindmap_id=7,
        status='ready',
        expires_time=datetime.now() + timedelta(hours=1),
        base_revision=4,
        base_hash='expected-hash',
    )
    db = SimpleNamespace()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(intent='expand')),
        ),
        patch.object(MindmapAiService, '_mark_proposal_stale', new=AsyncMock()) as mark_stale,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.get_mindmap_detail_services',
            new=AsyncMock(),
        ) as get_detail,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.update_content_batch_services',
            new=AsyncMock(),
        ) as update_content,
        pytest.raises(ServiceException) as stale,
    ):
        await MindmapAiService.apply_cloud_proposal(
            db,
            mindmap_id=7,
            proposal_id='proposal-1',
            user_id=9,
            user_name='tester',
            model=MindmapAiCloudApplyModel(
                contentRevision=5,
                baseHash='different-hash',
            ),
            idempotency_key='request-1',
        )

    assert stale.value.data == {'errorCode': 'AI_PROPOSAL_STALE'}
    mark_stale.assert_awaited_once_with(db, 'proposal-1', 'job-1')
    get_detail.assert_not_awaited()
    update_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_apply_and_undo_reject_a_persisted_hybrid_local_proposal() -> None:
    proposal = SimpleNamespace(
        id='proposal-hybrid-channel',
        job_id='job-hybrid-channel',
        target_mindmap_id=42,
        base_document_id='local-document',
        status='ready',
    )
    get_job = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_undo',
            new=AsyncMock(return_value=SimpleNamespace(mindmap_id=42)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=get_job,
        ),
    ):
        with pytest.raises(ServiceException) as apply_blocked:
            await MindmapAiService.apply_cloud_proposal(
                SimpleNamespace(),
                mindmap_id=42,
                proposal_id=proposal.id,
                user_id=7,
                user_name='tester',
                model=MindmapAiCloudApplyModel(
                    content_revision=1,
                    base_hash='base-hash',
                ),
                idempotency_key='apply-channel-test',
            )
        with pytest.raises(ServiceException) as undo_blocked:
            await MindmapAiService.undo_cloud_proposal(
                SimpleNamespace(),
                mindmap_id=42,
                proposal_id=proposal.id,
                user_id=7,
                user_name='tester',
                idempotency_key='undo-channel-test',
            )

    assert apply_blocked.value.message == 'AI 脑图提案不存在'
    assert apply_blocked.value.data == {'errorCode': 'AI_PROPOSAL_NOT_FOUND'}
    assert undo_blocked.value.message == 'AI 脑图撤销记录不存在'
    assert undo_blocked.value.data == {'errorCode': 'AI_UNDO_NOT_FOUND'}
    get_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_undo_replay_after_conflict_has_stable_permanent_error_code() -> None:
    proposal = SimpleNamespace(
        id='proposal-blocked-undo',
        job_id='job-blocked-undo',
        target_mindmap_id=42,
        base_document_id=None,
    )
    undo = SimpleNamespace(
        mindmap_id=42,
        status='blocked',
        expires_time=datetime.now() + timedelta(hours=1),
    )
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_undo',
            new=AsyncMock(return_value=undo),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(intent='expand')),
        ),
        pytest.raises(ServiceException) as blocked,
    ):
        await MindmapAiService.undo_cloud_proposal(
            SimpleNamespace(),
            mindmap_id=42,
            proposal_id=proposal.id,
            user_id=7,
            user_name='tester',
            idempotency_key='undo-blocked-replay',
        )

    assert blocked.value.data == {'errorCode': 'AI_UNDO_CONFLICT'}


@pytest.mark.asyncio
async def test_cloud_ai_apply_upgrades_legacy_operations() -> None:
    source_document = _document('AI 扩展前')
    source, _source_summary = normalize_ai_editable_source_document(
        source_document,
    )
    proposal = SimpleNamespace(
        id='proposal-trusted-ai-source',
        job_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        target_mindmap_id=76,
        base_document_id=None,
        status='ready',
        expires_time=datetime.now() + timedelta(hours=1),
        base_revision=5,
        base_hash=compute_document_hash(source),
        base_room_epoch=None,
        result_artifact_id='artifact-trusted-ai-source',
    )
    barrier = SimpleNamespace(token='trusted-ai-barrier')
    prepared_barrier = SimpleNamespace(token='trusted-ai-prepared-barrier')
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    update_content = AsyncMock(return_value={
        'contentRevision': 6,
        'clientMutationId': 'ai:trusted-source',
        'idempotentReplay': False,
    })
    artifact_document = _document('AI 扩展后')
    artifact_document['root']['children'] = [{
        'data': {'uid': 'generated-case', 'text': '新增分支'},
        'children': [{
            'data': {'uid': 'generated-step', 'text': '新增子节点'},
            'children': [],
        }],
    }]
    artifact_document, _artifact_summary = normalize_ai_editable_source_document(
        artifact_document,
    )
    proposal.result_hash = compute_document_hash(artifact_document)
    proposal.operations_json = json.dumps(
        build_legacy_document_diff_v0(source, artifact_document),
        ensure_ascii=False,
    )
    job = SimpleNamespace(
        id=proposal.job_id,
        intent='expand',
        source_type='cloud_document',
        target='proposal',
        source_mindmap_id=76,
        base_revision=proposal.base_revision,
        base_hash=proposal.base_hash,
        base_room_epoch=proposal.base_room_epoch,
        artifact_id=proposal.result_artifact_id,
    )
    artifact_record = SimpleNamespace(
        job_id=proposal.job_id,
        document_hash=proposal.result_hash,
    )
    artifact = {
        'manifest': {'documentHash': proposal.result_hash},
        'document': artifact_document,
    }

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(artifact_record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.get_mindmap_detail_services',
            new=AsyncMock(return_value=_detail(source, 5)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.update_content_batch_services',
            new=update_content,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_undo',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.extend_result_expiration',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.get_active_lineage_epoch',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.acquire_collaboration_mutation_barrier',
            new=AsyncMock(return_value=barrier),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.wait_for_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.verify_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.prepare_collaboration_mutation_barrier_commit',
            new=AsyncMock(return_value=prepared_barrier),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.complete_collaboration_mutation_barrier',
            new=AsyncMock(return_value=False),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.abort_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await MindmapAiService.apply_cloud_proposal(
            db,
            mindmap_id=76,
            proposal_id=proposal.id,
            user_id=7,
            user_name='tester',
            model=MindmapAiCloudApplyModel(
                contentRevision=5,
                baseHash=proposal.base_hash,
            ),
            idempotency_key='trusted-ai-apply',
        )

    assert update_content.await_args.kwargs == {
        'commit': False,
        'broadcast': False,
    }
    assert result['status'] == 'applied'
    assert result['contentRevision'] == EXPECTED_TRUSTED_AI_APPLIED_REVISION
    assert result['collaborationSyncPending'] is True
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cloud_apply_rebases_across_content_equivalent_revision() -> None:
    source, _source_summary = normalize_ai_editable_source_document(
        _document('内容未变化'),
    )
    artifact_document, _artifact_summary = normalize_ai_editable_source_document(
        _document('AI 扩展后的内容'),
    )
    base_room_epoch = 'a' * 32
    current_room_epoch = 'b' * 32
    proposal_base_revision = 5
    current_revision = 6
    applied_revision = 7
    expected_detail_reads = 2
    proposal = SimpleNamespace(
        id='proposal-equivalent-revision',
        job_id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        target_mindmap_id=77,
        base_document_id=None,
        status='ready',
        expires_time=datetime.now() + timedelta(hours=1),
        base_revision=proposal_base_revision,
        base_hash=compute_document_hash(source),
        base_room_epoch=base_room_epoch,
        result_artifact_id='artifact-equivalent-revision',
        result_hash=compute_document_hash(artifact_document),
        operations_json=json.dumps(
            build_document_diff(source, artifact_document)[0],
            ensure_ascii=False,
        ),
    )
    job = SimpleNamespace(
        id=proposal.job_id,
        intent='expand',
        source_type='cloud_document',
        target='proposal',
        source_mindmap_id=77,
        base_revision=proposal.base_revision,
        base_hash=proposal.base_hash,
        base_room_epoch=proposal.base_room_epoch,
        artifact_id=proposal.result_artifact_id,
    )
    artifact_record = SimpleNamespace(
        job_id=proposal.job_id,
        document_hash=proposal.result_hash,
    )
    artifact = {
        'manifest': {'documentHash': proposal.result_hash},
        'document': artifact_document,
    }
    barrier = SimpleNamespace(token='equivalent-revision-barrier')
    prepared_barrier = SimpleNamespace(token='equivalent-revision-prepared')

    class RollbackExpiringNamespace(SimpleNamespace):
        """模拟真实 AsyncSession.rollback() 后 ORM 标量属性已失效。"""

        _expired = False
        _expired_fields: frozenset[str] = frozenset()

        def expire(self) -> None:
            object.__setattr__(self, '_expired', True)

        def __getattribute__(self, name: str) -> object:
            if (
                name not in {'_expired', '_expired_fields', 'expire'}
                and object.__getattribute__(self, '_expired')
                and name in object.__getattribute__(self, '_expired_fields')
            ):
                raise RuntimeError(f'rollback-expired attribute accessed: {name}')
            return super().__getattribute__(name)

    initial_proposal = RollbackExpiringNamespace(**vars(proposal))
    initial_proposal._expired_fields = frozenset({'base_hash'})
    initial_job = RollbackExpiringNamespace(**vars(job))
    initial_job._expired_fields = frozenset({'intent'})

    def expire_initial_records() -> None:
        initial_proposal.expire()
        initial_job.expire()

    db = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(side_effect=expire_initial_records),
    )
    update_content = AsyncMock(return_value={
        'contentRevision': applied_revision,
        'clientMutationId': 'ai:equivalent-revision',
        'idempotentReplay': False,
    })

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(side_effect=[initial_proposal, proposal]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(side_effect=[initial_job, job]),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(artifact_record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.get_mindmap_detail_services',
            new=AsyncMock(return_value=_detail(source, current_revision)),
        ) as get_detail,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.update_content_batch_services',
            new=update_content,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_undo',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.extend_result_expiration',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.get_active_lineage_epoch',
            new=AsyncMock(return_value=current_room_epoch),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.acquire_collaboration_mutation_barrier',
            new=AsyncMock(side_effect=[None, barrier]),
        ) as acquire_barrier,
        patch(
            'module_mindmap.websocket.room_manager.room_manager.wait_for_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.verify_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.prepare_collaboration_mutation_barrier_commit',
            new=AsyncMock(return_value=prepared_barrier),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.complete_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.abort_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await MindmapAiService.apply_cloud_proposal(
            db,
            mindmap_id=77,
            proposal_id=proposal.id,
            user_id=7,
            user_name='tester',
            model=MindmapAiCloudApplyModel(
                contentRevision=proposal.base_revision,
                baseHash=proposal.base_hash,
                roomEpoch=proposal.base_room_epoch,
            ),
            idempotency_key='equivalent-revision-apply',
        )

    assert acquire_barrier.await_args_list[0].args == (
        77,
        proposal_base_revision,
        base_room_epoch,
    )
    assert acquire_barrier.await_args_list[1].args == (
        77,
        current_revision,
        current_room_epoch,
    )
    assert get_detail.await_count == expected_detail_reads
    assert update_content.await_args.args[2].base_revision == current_revision
    assert result['status'] == 'applied'
    assert result['contentRevision'] == applied_revision
    assert result['rebasedFromRevision'] == proposal_base_revision
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cloud_apply_rejects_noncanonical_operations_before_document_write() -> None:
    source, _source_summary = normalize_ai_editable_source_document(
        _document('应用前'),
    )
    artifact_document, _artifact_summary = normalize_ai_editable_source_document(
        _document('应用后'),
    )
    canonical_operations, _impact = build_document_diff(source, artifact_document)
    result_hash = compute_document_hash(artifact_document)
    proposal = SimpleNamespace(
        id='proposal-cloud-tampered-operations',
        job_id='job-cloud-tampered-operations',
        target_mindmap_id=78,
        base_document_id=None,
        status='ready',
        expires_time=datetime.now() + timedelta(hours=1),
        base_revision=5,
        base_hash=compute_document_hash(source),
        base_room_epoch=None,
        result_artifact_id='artifact-cloud-tampered-operations',
        result_hash=result_hash,
        operations_json=json.dumps([{
            'type': 'update_node',
            'nodeUid': 'root',
            'payload': {'set': {'text': '应用前'}, 'unset': []},
        }, *canonical_operations], ensure_ascii=False),
    )
    job = SimpleNamespace(
        id=proposal.job_id,
        intent='expand',
        source_type='cloud_document',
        target='proposal',
        source_mindmap_id=proposal.target_mindmap_id,
        base_revision=proposal.base_revision,
        base_hash=proposal.base_hash,
        base_room_epoch=proposal.base_room_epoch,
        artifact_id=proposal.result_artifact_id,
    )
    artifact_record = SimpleNamespace(
        job_id=proposal.job_id,
        document_hash=result_hash,
    )
    artifact = {
        'manifest': {'documentHash': result_hash},
        'document': artifact_document,
    }
    barrier = SimpleNamespace(token='tampered-operation-barrier')
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    update_content = AsyncMock()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(artifact_record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.'
            'get_mindmap_detail_services',
            new=AsyncMock(return_value=_detail(source, proposal.base_revision)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.'
            'update_content_batch_services',
            new=update_content,
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.'
            'get_active_lineage_epoch',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.'
            'acquire_collaboration_mutation_barrier',
            new=AsyncMock(return_value=barrier),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.'
            'wait_for_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.'
            'verify_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.'
            'abort_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ) as abort_barrier,
        pytest.raises(ServiceException) as invalid,
    ):
        await MindmapAiService.apply_cloud_proposal(
            db,
            mindmap_id=proposal.target_mindmap_id,
            proposal_id=proposal.id,
            user_id=7,
            user_name='tester',
            model=MindmapAiCloudApplyModel(
                contentRevision=proposal.base_revision,
                baseHash=proposal.base_hash,
            ),
            idempotency_key='tampered-cloud-apply',
        )

    assert invalid.value.data == {'errorCode': 'AI_PROPOSAL_INTEGRITY_INVALID'}
    update_content.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert db.rollback.await_count == EXPECTED_BARRIER_ROLLBACK_COUNT
    abort_barrier.assert_awaited_once_with(barrier)


@pytest.mark.asyncio
async def test_cloud_apply_rejects_document_drift_without_writing_document() -> None:
    original = _document('原始内容')
    proposal = SimpleNamespace(
        id='proposal-2',
        job_id='job-2',
        target_mindmap_id=8,
        status='ready',
        expires_time=datetime.now() + timedelta(hours=1),
        base_revision=3,
        base_hash=compute_document_hash(original),
        base_room_epoch=None,
    )

    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    barrier = SimpleNamespace(token='apply-drift-barrier')
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(intent='expand')),
        ),
        patch.object(MindmapAiService, '_mark_proposal_stale', new=AsyncMock()) as mark_stale,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.get_mindmap_detail_services',
            new=AsyncMock(return_value=_detail(_document('协作者的新内容'), 3)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.update_content_batch_services',
            new=AsyncMock(),
        ) as update_content,
        patch(
            'module_mindmap.websocket.room_manager.room_manager.acquire_collaboration_mutation_barrier',
            new=AsyncMock(return_value=barrier),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.wait_for_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.get_active_lineage_epoch',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.verify_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.abort_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ) as abort_barrier,
        pytest.raises(ServiceException) as stale,
    ):
        await MindmapAiService.apply_cloud_proposal(
            db,
            mindmap_id=8,
            proposal_id='proposal-2',
            user_id=9,
            user_name='tester',
            model=MindmapAiCloudApplyModel(
                contentRevision=3,
                baseHash=proposal.base_hash,
            ),
            idempotency_key='request-2',
        )

    assert stale.value.data == {'errorCode': 'AI_APPLY_CONFLICT'}
    mark_stale.assert_not_awaited()
    assert db.rollback.await_count == EXPECTED_BARRIER_ROLLBACK_COUNT
    db.commit.assert_not_awaited()
    abort_barrier.assert_awaited_once_with(barrier)
    update_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_apply_force_overwrite_replaces_drift_after_explicit_confirmation() -> None:
    source, _source_summary = normalize_ai_editable_source_document(
        _document('生成提案时的内容'),
    )
    current, _current_summary = normalize_ai_editable_source_document(
        _document('协作者后来修改的内容'),
    )
    artifact_document, _artifact_summary = normalize_ai_editable_source_document(
        _document('AI 最终提案内容'),
    )
    base_room_epoch = 'c' * 32
    current_room_epoch = 'd' * 32
    expected_current_revision = 9
    expected_next_revision = 10
    proposal = SimpleNamespace(
        id='proposal-force-overwrite',
        job_id='cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        target_mindmap_id=8,
        base_document_id=None,
        status='ready',
        expires_time=datetime.now() + timedelta(hours=1),
        base_revision=3,
        base_hash=compute_document_hash(source),
        base_room_epoch=base_room_epoch,
        result_artifact_id='artifact-force-overwrite',
        result_hash=compute_document_hash(artifact_document),
        operations_json=json.dumps(
            build_document_diff(source, artifact_document)[0],
            ensure_ascii=False,
        ),
    )
    request_model = MindmapAiJobCreateModel(
        intent='expand',
        prompt='覆盖为 AI 提案',
        source={
            'type': 'cloud_document',
            'mindmapId': 8,
            'revision': proposal.base_revision,
            'documentHash': proposal.base_hash,
            'roomEpoch': proposal.base_room_epoch,
            'document': source,
            'baselineDocument': source,
        },
        target='proposal',
    )
    job = SimpleNamespace(
        id=proposal.job_id,
        intent='expand',
        source_type='cloud_document',
        target='proposal',
        source_mindmap_id=8,
        base_revision=proposal.base_revision,
        base_hash=proposal.base_hash,
        base_room_epoch=proposal.base_room_epoch,
        artifact_id=proposal.result_artifact_id,
        request_json=json.dumps(request_model.model_dump(by_alias=True), ensure_ascii=False),
    )
    artifact_record = SimpleNamespace(
        job_id=proposal.job_id,
        document_hash=proposal.result_hash,
    )
    artifact = {
        'manifest': {'documentHash': proposal.result_hash},
        'document': artifact_document,
    }
    barrier = SimpleNamespace(token='force-overwrite-barrier')
    prepared_barrier = SimpleNamespace(token='force-overwrite-prepared')
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    update_content = AsyncMock(return_value={
        'contentRevision': expected_next_revision,
        'clientMutationId': 'ai:force-overwrite',
        'idempotentReplay': False,
    })
    add_undo = AsyncMock()
    add_event = AsyncMock()
    acquire_barrier = AsyncMock(return_value=barrier)

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(side_effect=[proposal, proposal]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(side_effect=[job, job]),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(artifact_record, artifact)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.get_mindmap_detail_services',
            new=AsyncMock(return_value=_detail(current, expected_current_revision)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.update_content_batch_services',
            new=update_content,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_undo',
            new=add_undo,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.extend_result_expiration',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=add_event,
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.get_active_lineage_epoch',
            new=AsyncMock(return_value=current_room_epoch),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.acquire_collaboration_mutation_barrier',
            new=acquire_barrier,
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.wait_for_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.verify_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.prepare_collaboration_mutation_barrier_commit',
            new=AsyncMock(return_value=prepared_barrier),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.complete_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.abort_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await MindmapAiService.apply_cloud_proposal(
            db,
            mindmap_id=8,
            proposal_id=proposal.id,
            user_id=9,
            user_name='tester',
            model=MindmapAiCloudApplyModel(
                contentRevision=proposal.base_revision,
                baseHash=proposal.base_hash,
                roomEpoch=proposal.base_room_epoch,
                forceOverwrite=True,
            ),
            idempotency_key='force-overwrite-apply',
        )

    acquire_barrier.assert_awaited_once_with(
        8,
        9,
        current_room_epoch,
        operation='apply',
    )
    content_model = update_content.await_args.args[2]
    assert content_model.base_revision == expected_current_revision
    assert content_model.node_tree == artifact_document['root']
    assert content_model.node_tree != current['root']
    assert add_undo.await_args.args[1]['before_hash'] == compute_document_hash(current)
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['forceOverwrite'] is True
    assert result['forceOverwrite'] is True
    assert result['contentRevision'] == expected_next_revision
    assert result['rebasedFromRevision'] == proposal.base_revision


@pytest.mark.asyncio
async def test_cloud_apply_waits_for_barrier_without_row_lock_and_drain_failure_writes_nothing(
) -> None:
    source = _document('等待排空')
    proposal = SimpleNamespace(
        id='proposal-drain-timeout',
        job_id='job-drain-timeout',
        target_mindmap_id=88,
        base_document_id=None,
        status='ready',
        expires_time=datetime.now() + timedelta(hours=1),
        base_revision=12,
        base_hash=compute_document_hash(source),
        base_room_epoch=None,
    )
    call_order = []
    barrier = SimpleNamespace(token='drain-timeout-barrier')
    db = SimpleNamespace(commit=AsyncMock())

    async def rollback() -> None:
        call_order.append('rollback')

    async def get_proposal(
        _db: object,
        _proposal_id: str,
        _user_id: int,
        *,
        for_update: bool = False,
    ) -> object:
        call_order.append(f'proposal-lock:{for_update}')
        return proposal

    async def acquire(*_args: object, **_kwargs: object) -> object:
        call_order.append('barrier-acquire')
        return barrier

    async def wait(_barrier: object) -> bool:
        call_order.append('barrier-wait')
        return False

    async def abort(_barrier: object) -> bool:
        call_order.append('barrier-abort')
        return True

    db.rollback = AsyncMock(side_effect=rollback)
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(side_effect=get_proposal),
        ) as get_proposal_mock,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(intent='expand')),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.acquire_collaboration_mutation_barrier',
            new=AsyncMock(side_effect=acquire),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.wait_for_collaboration_mutation_barrier',
            new=AsyncMock(side_effect=wait),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.abort_collaboration_mutation_barrier',
            new=AsyncMock(side_effect=abort),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(),
        ) as check_access,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.update_content_batch_services',
            new=AsyncMock(),
        ) as update_content,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_proposal',
            new=AsyncMock(),
        ) as update_proposal,
        pytest.raises(ServiceException) as conflict,
    ):
        await MindmapAiService.apply_cloud_proposal(
            db,
            mindmap_id=88,
            proposal_id=proposal.id,
            user_id=9,
            user_name='tester',
            model=MindmapAiCloudApplyModel(
                contentRevision=12,
                baseHash=proposal.base_hash,
            ),
            idempotency_key='drain-timeout-request',
        )

    assert conflict.value.data == {'errorCode': 'AI_APPLY_CONFLICT'}
    assert call_order == [
        'proposal-lock:False',
        'rollback',
        'barrier-acquire',
        'barrier-wait',
        'rollback',
        'barrier-abort',
    ]
    assert get_proposal_mock.await_count == 1
    check_access.assert_not_awaited()
    update_content.assert_not_awaited()
    update_proposal.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_undo_blocks_after_collaborator_edit_without_overwriting_document() -> None:
    applied = _document('AI 应用结果')
    undo = SimpleNamespace(
        mindmap_id=9,
        status='available',
        expires_time=datetime.now() + timedelta(hours=1),
        applied_revision=6,
        applied_hash=compute_document_hash(applied),
    )
    proposal = SimpleNamespace(
        job_id='job-3',
        target_mindmap_id=9,
        base_document_id=None,
    )
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    barrier = SimpleNamespace(token='undo-drift-barrier')

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_undo',
            new=AsyncMock(return_value=undo),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_proposal',
            new=AsyncMock(return_value=proposal),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(intent='expand')),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_undo',
            new=AsyncMock(),
        ) as update_undo,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.check_mindmap_access',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.get_mindmap_detail_services',
            new=AsyncMock(return_value=_detail(_document('协作者继续编辑'), 7)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapService.update_content_batch_services',
            new=AsyncMock(),
        ) as update_content,
        patch(
            'module_mindmap.websocket.room_manager.room_manager.get_active_lineage_epoch',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.acquire_collaboration_mutation_barrier',
            new=AsyncMock(return_value=barrier),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.wait_for_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.verify_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ),
        patch(
            'module_mindmap.websocket.room_manager.room_manager.abort_collaboration_mutation_barrier',
            new=AsyncMock(return_value=True),
        ) as abort_barrier,
        pytest.raises(ServiceException) as conflict,
    ):
        await MindmapAiService.undo_cloud_proposal(
            db,
            mindmap_id=9,
            proposal_id='proposal-3',
            user_id=9,
            user_name='tester',
            idempotency_key='undo-1',
        )

    assert conflict.value.data == {'errorCode': 'AI_UNDO_CONFLICT'}
    update_undo.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert db.rollback.await_count == EXPECTED_BARRIER_ROLLBACK_COUNT
    abort_barrier.assert_awaited_once_with(barrier)
    update_content.assert_not_awaited()
