"""AI 脑图历史 Artifact 分支与 SDK 会话血缘测试。"""

import inspect
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from exceptions.exception import ServiceException
from module_mindmap.ai.document import AI_MAX_FILE_BYTES
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiJobCreateModel,
    MindmapAiMessageModel,
)
from module_mindmap.service.mindmap_ai_service import (
    MindmapAiService,
    MindmapAiTaskManager,
    _initial_session_title,
)

SESSION_ID = '10000000-0000-4000-8000-000000000001'
JOB_A_ID = '20000000-0000-4000-8000-000000000001'
JOB_B_ID = '20000000-0000-4000-8000-000000000002'
ARTIFACT_A_ID = '30000000-0000-4000-8000-000000000001'
ARTIFACT_B_ID = '30000000-0000-4000-8000-000000000002'
BRANCH_TURN_INDEX = 3
NEEDS_INPUT_NEXT_TURN_INDEX = 2
MINDMAP_ID = 127
AUTHORITATIVE_REVISION = 9
LOCAL_PROPOSAL_ID = '40000000-0000-4000-8000-000000000001'


def test_initial_session_title_is_stable_bounded_and_control_safe() -> None:
    assert _initial_session_title('  第一行\n\t第二行\x00  ') == '第一行 第二行'
    assert _initial_session_title('') == '新对话'
    assert _initial_session_title('一' * 80) == '一' * 36


def test_followup_message_accepts_optional_validated_intent() -> None:
    inherited = MindmapAiMessageModel.model_validate({'prompt': '继续'})
    switched = MindmapAiMessageModel.model_validate({'prompt': '讨论一下', 'intent': 'discuss'})

    assert inherited.intent is None
    assert inherited.continuation_base == 'artifact'
    assert switched.intent == 'discuss'
    with pytest.raises(ValueError, match='不支持的 AI 脑图意图'):
        MindmapAiMessageModel.model_validate({'prompt': '继续', 'intent': 'invalid'})


def test_local_current_snapshot_followup_requires_snapshot_hash_and_parent_status() -> None:
    snapshot = {
        'type': 'local_snapshot',
        'documentId': 'local:followup-test',
        'revision': 2,
        'documentHash': 'mmf2:sha256:' + ('a' * 64),
        'document': _document('current-local'),
    }
    model = MindmapAiMessageModel.model_validate({
        'prompt': '继续',
        'continuationBase': 'current_snapshot',
        'expectedParentStatus': 'applied',
        'source': snapshot,
    })

    assert model.continuation_base == 'current_snapshot'
    assert model.expected_parent_status == 'applied'
    assert model.source is not None and model.source.type == 'local_snapshot'
    with pytest.raises(ValueError, match='本地当前快照续写'):
        MindmapAiMessageModel.model_validate({
            'prompt': '继续',
            'continuationBase': 'current_snapshot',
            'source': snapshot,
        })
    with pytest.raises(ValueError, match='只有本地当前快照续写'):
        MindmapAiMessageModel.model_validate({
            'prompt': '继续',
            'source': snapshot,
        })


@pytest.mark.asyncio
async def test_local_snapshot_backend_normalizes_and_recomputes_claimed_hash() -> None:
    raw_document = _document('hash-check')
    raw_document['root']['data']['onClick'] = 'alert(1)'
    request = MindmapAiJobCreateModel.model_validate({
        'prompt': '继续',
        'intent': 'expand',
        'source': {
            'type': 'local_snapshot',
            'documentId': 'local:followup-test',
            'revision': 2,
            'documentHash': 'mmf2:sha256:' + ('0' * 64),
            'document': raw_document,
        },
        'target': 'proposal',
    })

    with pytest.raises(ServiceException) as error:
        await MindmapAiService._prepare_source(SimpleNamespace(), request, user_id=7)
    assert error.value.message == '本地脑图内容哈希与请求不一致'


def _document(title: str) -> dict:
    return {
        'root': {
            'data': {'uid': f'root-{title}', 'text': title},
            'children': [],
        },
        'layout': 'logicalStructure',
        'theme': {'template': 'default'},
    }


def _request_json(
    agent_key: str,
    marker: str,
    *,
    intent: str = 'expand',
    source_type: str = 'local_snapshot',
    target: str = 'proposal',
) -> str:
    if source_type == 'none':
        source = {'type': 'none'}
    elif source_type == 'cloud_document':
        source = {
            'type': 'cloud_document',
            'mindmapId': MINDMAP_ID,
            'revision': 1,
            'documentHash': f'hash-{marker}',
            'document': _document(f'{marker}-source'),
            'baselineDocument': _document(f'{marker}-baseline'),
        }
    else:
        source = {
            'type': 'local_snapshot',
            'documentId': 'local:followup-test',
            'revision': 1,
            'document': _document(f'{marker}-source'),
            'baselineDocument': _document(f'{marker}-baseline'),
        }
    request = MindmapAiJobCreateModel.model_validate({
        'agentKey': agent_key,
        'prompt': f'{marker} 请求',
        'intent': intent,
        'parameters': {
            'layout': 'logicalStructure',
            'maxNodes': 100,
            'maxDepth': 6,
        },
        'source': source,
        'target': target,
    })
    return json.dumps(request.model_dump(by_alias=True, exclude_none=True))


def _job(
    job_id: str,
    *,
    turn_index: int,
    agent_key: str,
    artifact_id: str | None,
    marker: str,
    status: str = 'ready',
    intent: str = 'expand',
    source_type: str = 'local_snapshot',
    target: str = 'proposal',
) -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id,
        user_id=7,
        session_id=SESSION_ID,
        parent_job_id=None,
        turn_index=turn_index,
        agent_key=agent_key,
        intent=intent,
        target=target,
        source_type=source_type,
        source_mindmap_id=MINDMAP_ID if source_type == 'cloud_document' else None,
        base_revision=1,
        base_hash=f'hash-{marker}',
        base_room_epoch=None,
        request_json=_request_json(
            agent_key,
            marker,
            intent=intent,
            source_type=source_type,
            target=target,
        ),
        status=status,
        artifact_id=artifact_id,
        proposal_id=(
            LOCAL_PROPOSAL_ID
            if source_type == 'local_snapshot' and status in {'applied', 'undone'}
            else None
        ),
        response_id=(f'response-{marker}' if status == 'completed_message' else None),
        external_session_ref=f'encrypted-{agent_key}-{marker}',
    )


def _created_job(_database: object, values: dict) -> SimpleNamespace:
    return SimpleNamespace(
        **values,
        retry_of_job_id=None,
        title=None,
        artifact_id=None,
        proposal_id=None,
        usage_json=None,
        error_code=None,
        error_message=None,
        completed_time=None,
    )


async def _run_followup(
    *,
    current_parent: SimpleNamespace,
    artifact_parent: SimpleNamespace,
    requested_agent: str | None,
    requested_intent: str | None = None,
    continuation_base: str = 'artifact',
    authoritative_source: tuple[dict, int, str, int | None, str | None] | None = None,
    locked_current_parent: SimpleNamespace | None = None,
    current_snapshot_source: dict | None = None,
    call_observer: dict | None = None,
) -> tuple[object, dict, AsyncMock]:
    selected_document = _document('artifact-a-result')
    manifest_agent = requested_agent or current_parent.agent_key
    manifest = SimpleNamespace(
        agent_key=manifest_agent,
        adapter_version='1.0.0',
        sdk_version='sdk-test',
        runtime_version='runtime-test',
        intents={'create', 'expand', 'discuss'},
        input_types={'none', 'local_snapshot', 'cloud_document', 'uploaded_artifact'},
        result_types=('artifact', 'message'),
    )
    registry = SimpleNamespace(get=Mock(return_value=SimpleNamespace(
        get_manifest=Mock(return_value=manifest),
    )))
    session = SimpleNamespace(
        id=SESSION_ID,
        status='active',
        expires_time=datetime.now() + timedelta(days=2),
    )
    connector = SimpleNamespace()
    policy = SimpleNamespace(
        max_budget_usd=5.0,
        timeout_seconds=300,
        retention_days=30,
    )
    add_job = AsyncMock(side_effect=_created_job)
    add_event = AsyncMock()
    lock_order: list[str] = []

    async def get_session(
        *_args: object,
        for_update: bool = False,
        **_kwargs: object,
    ) -> SimpleNamespace:
        lock_order.append('session-lock' if for_update else 'session-read')
        return session

    async def ensure_connector(
        *_args: object,
        preflight_unknown: bool = True,
        **_kwargs: object,
    ) -> SimpleNamespace:
        if preflight_unknown:
            lock_order.append('provider-preflight')
        return connector

    async def lock_session_jobs(*_args: object, **_kwargs: object) -> list[SimpleNamespace]:
        lock_order.append('jobs-lock')
        locked_parent = locked_current_parent or current_parent
        if artifact_parent.id == locked_parent.id:
            return [locked_parent]
        return [artifact_parent, locked_parent]

    locked_session_jobs = AsyncMock(side_effect=lock_session_jobs)
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    model_payload = {
        'prompt': '从历史结果继续扩写',
    }
    if (
        current_parent.status not in {'needs_input', 'completed_message'}
        and continuation_base != 'current_snapshot'
    ):
        model_payload['artifactId'] = ARTIFACT_A_ID
    if requested_agent is not None:
        model_payload['agentKey'] = requested_agent
    if requested_intent is not None:
        model_payload['intent'] = requested_intent
    model_payload['continuationBase'] = continuation_base
    if continuation_base == 'current_snapshot':
        model_payload['expectedParentStatus'] = current_parent.status
        model_payload['source'] = current_snapshot_source or {
            'type': 'local_snapshot',
            'documentId': 'local:followup-test',
            'revision': AUTHORITATIVE_REVISION,
            'documentHash': 'mmf2:sha256:' + ('a' * 64),
            'document': _document('browser-current'),
        }
    if call_observer is not None:
        call_observer.update({
            'add_job': add_job,
            'add_event': add_event,
            'database': database,
        })

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(side_effect=[current_parent, artifact_parent]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(side_effect=get_session),
        ),
        patch.object(
            MindmapAiService,
            'get_artifact',
            new=AsyncMock(return_value=(
                SimpleNamespace(job_id=artifact_parent.id),
                {'document': selected_document},
            )),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch.object(
            MindmapAiService,
            '_ensure_connector_available',
            new=AsyncMock(side_effect=ensure_connector),
        ),
        patch.object(MindmapAiService, '_runtime_policy', return_value=policy),
        patch.object(MindmapAiService, '_validate_job_policy', return_value='model-test'),
        patch.object(
            MindmapAiService,
            '_ensure_concurrency_available',
            new=AsyncMock(),
        ),
        patch.object(
            MindmapAiService,
            '_prepare_source_for_job',
            new=AsyncMock(return_value=authoritative_source),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.lock_jobs_for_session',
            new=locked_session_jobs,
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
        patch.object(MindmapAiTaskManager, 'schedule', new=Mock()),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event',
            new=Mock(),
        ),
    ):
        result = await MindmapAiService.create_followup_job(
            database,
            current_parent.id,
            MindmapAiMessageModel.model_validate(model_payload),
            user_id=7,
            idempotency_key=f'followup-{manifest_agent}',
        )

    locked_session_jobs.assert_awaited_once_with(
        database,
        SESSION_ID,
    )
    assert lock_order == [
        'session-read',
        'provider-preflight',
        'jobs-lock',
        'session-lock',
    ]
    created_values = add_job.await_args.args[1]
    return result, created_values, add_event


@pytest.mark.asyncio
async def test_historical_artifact_is_content_source_but_current_turn_remains_parent() -> None:
    artifact_parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='a',
    )
    current_parent = _job(
        JOB_B_ID,
        turn_index=2,
        agent_key='claude',
        artifact_id=ARTIFACT_B_ID,
        marker='b',
    )

    result, created, add_event = await _run_followup(
        current_parent=current_parent,
        artifact_parent=artifact_parent,
        requested_agent=None,
    )

    assert created['parent_job_id'] == JOB_B_ID
    assert created['turn_index'] == BRANCH_TURN_INDEX
    assert created['agent_key'] == 'claude'
    assert created['base_hash'] == 'hash-a'
    request = json.loads(created['request_json'])
    assert request['source']['document']['root']['data']['text'] == 'artifact-a-result'
    assert request['source']['baselineDocument']['root']['data']['text'] == 'a-baseline'
    assert result.parent_job_id == JOB_B_ID
    assert result.turn_index == BRANCH_TURN_INDEX
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['parentJobId'] == JOB_B_ID
    assert event_payload['turnIndex'] == BRANCH_TURN_INDEX


@pytest.mark.asyncio
async def test_cross_agent_historical_branch_keeps_source_lineage_without_reusing_sdk_session() -> None:
    artifact_parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='a',
    )
    current_parent = _job(
        JOB_B_ID,
        turn_index=2,
        agent_key='codex',
        artifact_id=ARTIFACT_B_ID,
        marker='b',
    )

    result, created, _add_event = await _run_followup(
        current_parent=current_parent,
        artifact_parent=artifact_parent,
        requested_agent='claude',
    )

    assert created['parent_job_id'] == JOB_B_ID
    assert created['agent_key'] == 'claude'
    assert result.parent_job_id == JOB_B_ID
    assert result.agent_key == 'claude'
    # 运行时仅在父任务与当前任务 Agent 相同时解密 SDK 会话引用；因此这里
    # 会保留 Artifact 血缘，但 Claude 不会恢复 Codex 的会话。
    resolver_source = inspect.getsource(
        MindmapAiTaskManager._resolve_parent_external_session_id,
    )
    assert 'parent_job.agent_key != agent_key' in resolver_source
    assert resolver_source.index('parent_job.agent_key != agent_key') < resolver_source.index(
        'CryptoUtil.decrypt(encrypted_ref)',
    )


@pytest.mark.asyncio
async def test_standalone_artifact_followup_becomes_uploaded_document_source() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='standalone',
        status='completed_file',
        intent='create',
        source_type='none',
        target='file',
    )

    result, created, _add_event = await _run_followup(
        current_parent=parent,
        artifact_parent=parent,
        requested_agent=None,
    )

    request = json.loads(created['request_json'])
    assert request['source']['type'] == 'uploaded_artifact'
    assert request['source']['document']['root']['data']['text'] == 'artifact-a-result'
    assert 'documentId' not in request['source']
    assert 'mindmapId' not in request['source']
    assert created['source_type'] == 'uploaded_artifact'
    assert created['target'] == 'file'
    assert created['parent_job_id'] == JOB_A_ID
    assert result.source_type == 'uploaded_artifact'


@pytest.mark.asyncio
async def test_edit_artifact_can_start_discussion_without_reusing_result_contract() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='edit',
    )

    result, created, add_event = await _run_followup(
        current_parent=parent,
        artifact_parent=parent,
        requested_agent=None,
        requested_intent='discuss',
    )

    request = json.loads(created['request_json'])
    assert request['intent'] == 'discuss'
    assert request['target'] == 'message'
    assert request['source']['type'] == 'local_snapshot'
    assert request['source']['document']['root']['data']['text'] == 'artifact-a-result'
    assert created['intent'] == 'discuss'
    assert created['target'] == 'message'
    assert result.intent == 'discuss'
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['sessionMode'] == 'mode_switch'


@pytest.mark.asyncio
async def test_discussion_can_switch_back_to_edit_using_frozen_source() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=None,
        marker='discussion',
        status='completed_message',
        intent='discuss',
        source_type='local_snapshot',
        target='message',
    )

    result, created, add_event = await _run_followup(
        current_parent=parent,
        artifact_parent=parent,
        requested_agent=None,
        requested_intent='expand',
    )

    request = json.loads(created['request_json'])
    assert request['intent'] == 'expand'
    assert request['target'] == 'proposal'
    assert request['source']['document']['root']['data']['text'] == 'discussion-source'
    assert created['intent'] == 'expand'
    assert created['target'] == 'proposal'
    assert created['parent_job_id'] == JOB_A_ID
    assert result.target == 'proposal'
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['sessionMode'] == 'mode_switch'


@pytest.mark.parametrize('parent_status', ['applied', 'undone'])
@pytest.mark.asyncio
async def test_applied_or_undone_cloud_followup_refreezes_authoritative_document(
    parent_status: str,
) -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker=parent_status,
        status=parent_status,
        source_type='cloud_document',
    )
    authoritative_document = _document(f'{parent_status}-authoritative')

    result, created, add_event = await _run_followup(
        current_parent=parent,
        artifact_parent=parent,
        requested_agent=None,
        continuation_base='current_document',
        authoritative_source=(
            authoritative_document,
            AUTHORITATIVE_REVISION,
            f'hash-{parent_status}-current',
            MINDMAP_ID,
            f'epoch-{parent_status}-current',
        ),
    )

    request = json.loads(created['request_json'])
    assert request['source']['type'] == 'cloud_document'
    assert request['source']['document'] == authoritative_document
    assert request['source']['baselineDocument'] == authoritative_document
    assert request['source']['revision'] == AUTHORITATIVE_REVISION
    assert request['source']['documentHash'] == f'hash-{parent_status}-current'
    assert request['source']['roomEpoch'] == f'epoch-{parent_status}-current'
    assert created['source_mindmap_id'] == MINDMAP_ID
    assert created['base_revision'] == AUTHORITATIVE_REVISION
    assert created['base_hash'] == f'hash-{parent_status}-current'
    assert created['base_room_epoch'] == f'epoch-{parent_status}-current'
    assert created['parent_job_id'] == JOB_A_ID
    assert result.base_revision == AUTHORITATIVE_REVISION
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['continuationBase'] == 'current_document'


@pytest.mark.asyncio
async def test_current_document_followup_rejects_parent_status_race() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='status-race',
        status='applied',
        source_type='cloud_document',
    )
    locked_parent = SimpleNamespace(**{
        **vars(parent),
        'status': 'undone',
    })

    with pytest.raises(ServiceException) as error:
        await _run_followup(
            current_parent=parent,
            artifact_parent=parent,
            requested_agent=None,
            continuation_base='current_document',
            authoritative_source=(
                _document('status-race-authoritative'),
                10,
                'hash-status-race-current',
                MINDMAP_ID,
                'epoch-status-race-current',
            ),
            locked_current_parent=locked_parent,
        )
    assert error.value.message == 'AI 脑图会话或结果已变化，请刷新后重试'


@pytest.mark.asyncio
async def test_applied_cloud_result_can_switch_to_discussion_on_current_document() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='applied-discussion',
        status='applied',
        source_type='cloud_document',
    )
    authoritative_document = _document('applied-discussion-authoritative')

    _result, created, add_event = await _run_followup(
        current_parent=parent,
        artifact_parent=parent,
        requested_agent=None,
        requested_intent='discuss',
        continuation_base='current_document',
        authoritative_source=(
            authoritative_document,
            AUTHORITATIVE_REVISION,
            'hash-applied-discussion-current',
            MINDMAP_ID,
            'epoch-applied-discussion-current',
        ),
    )

    request = json.loads(created['request_json'])
    assert request['intent'] == 'discuss'
    assert request['target'] == 'message'
    assert request['source']['document'] == authoritative_document
    assert 'baselineDocument' not in request['source']
    assert created['target'] == 'message'
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['sessionMode'] == 'mode_switch'
    assert event_payload['continuationBase'] == 'current_document'


@pytest.mark.parametrize('parent_status', ['applied', 'undone'])
@pytest.mark.asyncio
async def test_applied_or_undone_local_followup_freezes_browser_current_snapshot(
    parent_status: str,
) -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker=f'local-{parent_status}',
        status=parent_status,
        source_type='local_snapshot',
    )
    browser_document = _document(f'local-{parent_status}-browser-current')
    normalized_document = _document(f'local-{parent_status}-normalized-current')
    current_hash = f'mmf2:sha256:{"b" * 64}'

    result, created, add_event = await _run_followup(
        current_parent=parent,
        artifact_parent=parent,
        requested_agent=None,
        continuation_base='current_snapshot',
        current_snapshot_source={
            'type': 'local_snapshot',
            'documentId': 'local:followup-test',
            'revision': AUTHORITATIVE_REVISION,
            'documentHash': current_hash,
            'document': browser_document,
            # The server must retain the prior trusted scope instead of this
            # browser-supplied attempt to widen/change it.
            'scope': {'type': 'selectedNodes', 'nodeUids': ['untrusted-node']},
        },
        authoritative_source=(
            normalized_document,
            AUTHORITATIVE_REVISION,
            current_hash,
            None,
            None,
        ),
    )

    request = json.loads(created['request_json'])
    assert request['source']['type'] == 'local_snapshot'
    assert request['source']['documentId'] == 'local:followup-test'
    assert request['source']['document'] == normalized_document
    assert request['source']['baselineDocument'] == normalized_document
    assert request['source']['revision'] == AUTHORITATIVE_REVISION
    assert request['source']['documentHash'] == current_hash
    assert request['source']['scope'] == {'type': 'document'}
    assert 'mindmapId' not in request['source']
    assert 'roomEpoch' not in request['source']
    assert created['source_type'] == 'local_snapshot'
    assert created['source_mindmap_id'] is None
    assert created['base_revision'] == AUTHORITATIVE_REVISION
    assert created['base_hash'] == current_hash
    assert created['base_room_epoch'] is None
    assert created['parent_job_id'] == JOB_A_ID
    assert result.base_hash == current_hash
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['continuationBase'] == 'current_snapshot'


@pytest.mark.asyncio
async def test_local_current_snapshot_can_switch_to_discussion_without_baseline() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='local-applied-discussion',
        status='applied',
        source_type='local_snapshot',
    )
    current_document = _document('local-applied-discussion-current')
    current_hash = f'mmf2:sha256:{"c" * 64}'

    _result, created, add_event = await _run_followup(
        current_parent=parent,
        artifact_parent=parent,
        requested_agent=None,
        requested_intent='discuss',
        continuation_base='current_snapshot',
        current_snapshot_source={
            'type': 'local_snapshot',
            'documentId': 'local:followup-test',
            'revision': AUTHORITATIVE_REVISION,
            'documentHash': current_hash,
            'document': current_document,
        },
        authoritative_source=(
            current_document,
            AUTHORITATIVE_REVISION,
            current_hash,
            None,
            None,
        ),
    )

    request = json.loads(created['request_json'])
    assert request['intent'] == 'discuss'
    assert request['target'] == 'message'
    assert request['source']['document'] == current_document
    assert 'baselineDocument' not in request['source']
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['sessionMode'] == 'mode_switch'


@pytest.mark.asyncio
async def test_local_current_snapshot_rejects_document_identity_and_status_races_without_write() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='local-race',
        status='applied',
        source_type='local_snapshot',
    )
    changed_status_parent = SimpleNamespace(**{**vars(parent), 'status': 'undone'})
    observer: dict = {}

    with pytest.raises(ServiceException) as error:
        await _run_followup(
            current_parent=parent,
            artifact_parent=parent,
            requested_agent=None,
            continuation_base='current_snapshot',
            authoritative_source=(
                _document('local-race-current'),
                AUTHORITATIVE_REVISION,
                f'mmf2:sha256:{"d" * 64}',
                None,
                None,
            ),
            locked_current_parent=changed_status_parent,
            call_observer=observer,
        )

    assert error.value.data == {'errorCode': 'AI_FOLLOWUP_STATE_CHANGED'}
    observer['add_job'].assert_not_awaited()
    observer['add_event'].assert_not_awaited()
    observer['database'].commit.assert_not_awaited()

    bad_identity_observer: dict = {}
    with pytest.raises(ServiceException) as identity_error:
        await _run_followup(
            current_parent=parent,
            artifact_parent=parent,
            requested_agent=None,
            continuation_base='current_snapshot',
            current_snapshot_source={
                'type': 'local_snapshot',
                'documentId': 'local:other-document',
                'revision': AUTHORITATIVE_REVISION,
                'documentHash': f'mmf2:sha256:{"e" * 64}',
                'document': _document('wrong-local-document'),
            },
            authoritative_source=(
                _document('should-not-be-used'),
                AUTHORITATIVE_REVISION,
                f'mmf2:sha256:{"e" * 64}',
                None,
                None,
            ),
            call_observer=bad_identity_observer,
        )
    assert identity_error.value.data == {'errorCode': 'AI_FOLLOWUP_BASE_INVALID'}
    bad_identity_observer['add_job'].assert_not_awaited()
    bad_identity_observer['add_event'].assert_not_awaited()


@pytest.mark.asyncio
async def test_local_current_snapshot_has_bounded_body_and_rejects_before_job_write() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='local-too-large',
        status='applied',
        source_type='local_snapshot',
    )
    oversized_document = _document('local-too-large')
    oversized_document['padding'] = 'x' * AI_MAX_FILE_BYTES
    observer: dict = {}

    with pytest.raises(ServiceException) as error:
        await _run_followup(
            current_parent=parent,
            artifact_parent=parent,
            requested_agent=None,
            continuation_base='current_snapshot',
            current_snapshot_source={
                'type': 'local_snapshot',
                'documentId': 'local:followup-test',
                'revision': AUTHORITATIVE_REVISION,
                'documentHash': f'mmf2:sha256:{"f" * 64}',
                'document': oversized_document,
            },
            authoritative_source=(
                _document('should-not-be-used'),
                AUTHORITATIVE_REVISION,
                f'mmf2:sha256:{"f" * 64}',
                None,
                None,
            ),
            call_observer=observer,
        )

    assert error.value.data == {'errorCode': 'AI_INPUT_TOO_LARGE'}
    observer['add_job'].assert_not_awaited()
    observer['add_event'].assert_not_awaited()
    observer['database'].commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_current_snapshot_rejects_client_supplied_baseline_without_write() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=ARTIFACT_A_ID,
        marker='local-client-baseline',
        status='applied',
        source_type='local_snapshot',
    )
    observer: dict = {}

    with pytest.raises(ServiceException) as error:
        await _run_followup(
            current_parent=parent,
            artifact_parent=parent,
            requested_agent=None,
            continuation_base='current_snapshot',
            current_snapshot_source={
                'type': 'local_snapshot',
                'documentId': 'local:followup-test',
                'revision': AUTHORITATIVE_REVISION,
                'documentHash': f'mmf2:sha256:{"f" * 64}',
                'document': _document('browser-current'),
                'baselineDocument': _document('untrusted-client-baseline'),
            },
            authoritative_source=(
                _document('should-not-be-used'),
                AUTHORITATIVE_REVISION,
                f'mmf2:sha256:{"f" * 64}',
                None,
                None,
            ),
            call_observer=observer,
        )

    assert error.value.data == {'errorCode': 'AI_FOLLOWUP_BASE_INVALID'}
    observer['add_job'].assert_not_awaited()
    observer['add_event'].assert_not_awaited()
    observer['database'].commit.assert_not_awaited()


def test_provider_session_contract_rejects_edit_discussion_switches() -> None:
    edit = SimpleNamespace(intent='expand', target='proposal')
    discuss = SimpleNamespace(intent='discuss', target='message')
    same_edit = SimpleNamespace(intent='expand', target='proposal')

    assert MindmapAiTaskManager._same_provider_session_contract(edit, same_edit) is True
    assert MindmapAiTaskManager._same_provider_session_contract(edit, discuss) is False
    assert MindmapAiTaskManager._same_provider_session_contract(None, discuss) is False


@pytest.mark.asyncio
async def test_needs_input_answer_creates_new_turn_without_reviving_terminal_parent() -> None:
    needs_input_parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=None,
        marker='needs-input',
        status='needs_input',
    )

    result, created, add_event = await _run_followup(
        current_parent=needs_input_parent,
        artifact_parent=needs_input_parent,
        requested_agent=None,
    )

    assert needs_input_parent.status == 'needs_input'
    assert needs_input_parent.artifact_id is None
    assert created['status'] == 'queued'
    assert created['parent_job_id'] == JOB_A_ID
    assert created['turn_index'] == NEEDS_INPUT_NEXT_TURN_INDEX
    request = json.loads(created['request_json'])
    assert request['prompt'] == (
        '原始任务要求：\nneeds-input 请求\n\n'
        '用户补充信息：\n从历史结果继续扩写'
    )
    assert request['source']['document']['root']['data']['text'] == 'needs-input-source'
    assert result.id != needs_input_parent.id
    event_payload = json.loads(add_event.await_args.args[3])
    assert event_payload['parentJobId'] == JOB_A_ID
    assert event_payload['turnIndex'] == NEEDS_INPUT_NEXT_TURN_INDEX
    assert event_payload['sessionMode'] == 'new'

    # The platform lineage is retained for audit, but the worker must start a
    # fresh provider turn instead of resuming the SDK session that asked the
    # clarification question.
    with patch(
        'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
    ) as decrypt:
        assert MindmapAiTaskManager._resolve_parent_external_session_id(
            needs_input_parent,
            agent_key='codex',
            supports_sessions=True,
        ) is None
    decrypt.assert_not_called()


@pytest.mark.asyncio
async def test_needs_input_answer_cannot_switch_intent() -> None:
    parent = _job(
        JOB_A_ID,
        turn_index=1,
        agent_key='codex',
        artifact_id=None,
        marker='needs-input',
        status='needs_input',
    )
    session = SimpleNamespace(
        id=SESSION_ID,
        status='active',
        expires_time=datetime.now() + timedelta(days=2),
    )
    database = SimpleNamespace()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=parent),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ),
        pytest.raises(ServiceException) as error,
    ):
        await MindmapAiService.create_followup_job(
            database,
            JOB_A_ID,
            MindmapAiMessageModel.model_validate({
                'prompt': '先改为讨论',
                'intent': 'discuss',
            }),
            user_id=7,
            idempotency_key='needs-input-mode-switch',
        )
    assert error.value.message == '补充澄清信息时不能切换 AI 任务模式'
