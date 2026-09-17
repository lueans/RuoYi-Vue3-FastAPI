"""AI 脑图到期清理与用户会话删除测试。"""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.service.mindmap_ai_service import (
    MindmapAiRetentionManager,
    MindmapAiService,
    MindmapAiTaskManager,
    _exclude_still_referenced_adapter_sessions,
)

EXPECTED_SESSION_DELETE_COMMITS = 3
EXPECTED_FAILED_PURGE_COMMITS = 2
TIMELINE_PAGE_SIZE = 1_000


@pytest.mark.asyncio
async def test_retention_reference_query_includes_surviving_child_parent_ref() -> None:
    row = SimpleNamespace(
        id='running-child',
        agent_key='codex',
        external_session_ref=None,
        parent_external_session_ref='encrypted-parent-reference',
    )
    result = SimpleNamespace(all=lambda: [row])
    database = SimpleNamespace(execute=AsyncMock(return_value=result))

    references = await MindmapAiDao.list_other_external_session_references(
        database,
        {'codex'},
        ['expired-parent'],
    )

    statement = database.execute.await_args.args[0]
    statement_text = str(statement)
    assert references == [{
        'id': 'running-child',
        'agentKey': 'codex',
        'externalSessionRef': None,
        'parentExternalSessionRef': 'encrypted-parent-reference',
    }]
    assert 'LEFT OUTER JOIN mindmap_ai_job AS parent_job' in statement_text
    assert 'surviving_job.parent_job_id = parent_job.id' in statement_text
    assert 'surviving_job.agent_key = parent_job.agent_key' in statement_text
    assert 'surviving_job.id NOT IN' in statement_text


def test_retention_keeps_provider_session_referenced_by_surviving_child() -> None:
    candidates = [
        ('codex', 'shared-session'),
        ('codex', 'expired-only-session'),
        ('claude', 'shared-session'),
    ]
    surviving = [{
        'agentKey': 'codex',
        'externalSessionRef': 'encrypted-child-reference',
    }]

    with patch(
        'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
        return_value='shared-session',
    ):
        purgeable = _exclude_still_referenced_adapter_sessions(candidates, surviving)

    assert purgeable == [
        ('codex', 'expired-only-session'),
        ('claude', 'shared-session'),
    ]


def test_retention_keeps_parent_session_inherited_by_running_child() -> None:
    candidates = [('codex', 'parent-session'), ('codex', 'expired-only-session')]
    surviving = [{
        'agentKey': 'codex',
        'externalSessionRef': None,
        'parentExternalSessionRef': 'encrypted-parent-reference',
    }]

    with patch(
        'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
        return_value='parent-session',
    ):
        purgeable = _exclude_still_referenced_adapter_sessions(candidates, surviving)

    assert purgeable == [('codex', 'expired-only-session')]


def test_retention_fails_closed_when_surviving_reference_cannot_be_decrypted() -> None:
    candidates = [('codex', 'candidate-session'), ('claude', 'other-session')]
    surviving = [{
        'agentKey': 'codex',
        'externalSessionRef': 'corrupt-reference',
    }]

    with patch(
        'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
        side_effect=ValueError('corrupt'),
    ):
        purgeable = _exclude_still_referenced_adapter_sessions(candidates, surviving)

    assert purgeable == [('claude', 'other-session')]


class _SessionFactory:
    def __init__(self, database: SimpleNamespace) -> None:
        self.database = database

    def __call__(self) -> '_SessionFactory':
        return self

    async def __aenter__(self) -> SimpleNamespace:
        return self.database

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_retention_stop_prefers_graceful_event_shutdown() -> None:
    stop_event = asyncio.Event()
    exited = asyncio.Event()

    async def worker() -> None:
        await stop_event.wait()
        exited.set()

    MindmapAiRetentionManager._stop_event = stop_event
    MindmapAiRetentionManager._task = asyncio.create_task(worker())

    await MindmapAiRetentionManager.stop()

    assert exited.is_set()
    assert MindmapAiRetentionManager._task is None
    assert MindmapAiRetentionManager._stop_event is None


@pytest.mark.asyncio
async def test_retention_stop_does_not_break_lifespan_on_worker_timeout() -> None:
    async def failed_worker() -> None:
        raise asyncio.TimeoutError

    MindmapAiRetentionManager._stop_event = asyncio.Event()
    MindmapAiRetentionManager._task = asyncio.create_task(failed_worker())
    await asyncio.sleep(0)

    await MindmapAiRetentionManager.stop()

    assert MindmapAiRetentionManager._task is None
    assert MindmapAiRetentionManager._stop_event is None


@pytest.mark.asyncio
async def test_cleanup_scrubs_applied_audit_but_deletes_unapplied_payloads() -> None:
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    rows = [
        {
            'id': 'applied-job',
            'sessionId': 'session-1',
            'status': 'applied',
            'agentKey': 'codex',
            'externalSessionRef': 'encrypted-shared-session',
            'executionEpoch': 3,
        },
        {
            'id': 'ready-job',
            'sessionId': 'session-2',
            'status': 'ready',
            'agentKey': 'codex',
            'externalSessionRef': 'encrypted-shared-session',
            'executionEpoch': 5,
        },
    ]

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_expired_job_metadata',
            new=AsyncMock(return_value=rows),
        ) as list_expired,
        patch(
            'module_mindmap.service.mindmap_ai_service.'
            'MindmapAiDao.list_other_external_session_references',
            new=AsyncMock(return_value=[]),
        ) as list_surviving_references,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.delete_events_and_undos_for_jobs',
            new=AsyncMock(return_value={'events': 2, 'undos': 1}),
        ) as delete_retained_payloads,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.scrub_expired_jobs',
            new=AsyncMock(return_value=1),
        ) as scrub,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.delete_job_payloads',
            new=AsyncMock(return_value={
                'events': 3,
                'undos': 1,
                'proposals': 1,
                'artifacts': 1,
                'responses': 1,
                'jobs': 1,
            }),
        ) as delete_payloads,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.delete_expired_undos',
            new=AsyncMock(return_value=4),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.cleanup_sessions',
            new=AsyncMock(return_value={'deleted': 1, 'scrubbed': 1}),
        ) as cleanup_sessions,
        patch.object(
            MindmapAiTaskManager,
            'mark_draft_terminal',
            new=AsyncMock(),
        ) as mark_terminal,
        patch(
            'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
            return_value='provider-session',
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service._purge_adapter_session_references',
            new=AsyncMock(return_value=(1, 0)),
        ) as purge_sdk_sessions,
        patch(
            'module_mindmap.service.mindmap_ai_service._cleanup_expired_adapter_sessions',
            new=AsyncMock(return_value=(2, 0)),
        ) as cleanup_sdk_sessions,
    ):
        result = await MindmapAiRetentionManager.cleanup_once()

    assert set(list_expired.await_args.args[2]) == {
        'ready', 'applied', 'undone', 'completed_file', 'completed_no_change',
        'completed_message', 'needs_review', 'needs_input', 'stale', 'cancelled',
        'failed', 'expired',
    }
    list_surviving_references.assert_awaited_once_with(
        database,
        {'codex'},
        ['applied-job', 'ready-job'],
    )
    delete_retained_payloads.assert_awaited_once_with(database, ['applied-job'])
    assert scrub.await_args.args[:2] == (database, ['applied-job'])
    assert scrub.await_args.args[2] > list_expired.await_args.args[1]
    delete_payloads.assert_awaited_once_with(database, ['ready-job'])
    cleanup_sessions.assert_awaited_once()
    assert [call.args for call in mark_terminal.await_args_list] == [
        ('applied-job', 3), ('ready-job', 5),
    ]
    purge_sdk_sessions.assert_awaited_once_with(
        [('codex', 'provider-session')],
        strict=False,
    )
    cleanup_sdk_sessions.assert_awaited_once_with()
    assert result == {
        'scrubbedJobs': 1,
        'deletedJobs': 1,
        'deletedArtifacts': 1,
        'deletedProposals': 1,
        'deletedResponses': 1,
        'deletedEvents': 5,
        'deletedUndos': 6,
        'deletedSessions': 1,
        'scrubbedSessions': 1,
        'purgedSdkSessions': 1,
        'expiredSdkSessions': 2,
        'sdkSessionCleanupFailures': 0,
    }
    database.commit.assert_awaited_once()
    database.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_session_cancels_active_jobs_and_removes_all_snapshots() -> None:
    operation_order: list[str] = []
    database = SimpleNamespace(
        commit=AsyncMock(side_effect=lambda: operation_order.append('commit')),
        rollback=AsyncMock(),
    )
    session = SimpleNamespace(id='session-owned', status='active')
    active = SimpleNamespace(
        id='job-active',
        status='running',
        agent_key='codex',
        external_session_ref='encrypted-codex-session',
        execution_epoch=2,
    )
    finished = SimpleNamespace(
        id='job-finished',
        status='ready',
        agent_key='claude',
        external_session_ref='encrypted-claude-session',
        execution_epoch=4,
    )

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_jobs_for_session',
            new=AsyncMock(return_value=[active, finished]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_session',
            new=AsyncMock(),
        ) as update_session,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.request_session_job_cancellations',
            new=AsyncMock(side_effect=lambda *_args: operation_order.append('persist') or 1),
        ) as request_cancellations,
        patch.object(
            MindmapAiTaskManager,
            'cancel',
            new=AsyncMock(side_effect=lambda *_args: operation_order.append('local') or True),
        ) as cancel,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.delete_session_cascade',
            new=AsyncMock(return_value={'sessions': 1, 'jobs': 2}),
        ) as cascade,
        patch.object(
            MindmapAiTaskManager,
            'mark_draft_terminal',
            new=AsyncMock(),
        ) as mark_terminal,
        patch(
            'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
            side_effect=lambda value: value.replace('encrypted-', ''),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service._purge_adapter_session_references',
            new=AsyncMock(return_value=(2, 0)),
        ) as purge_sdk_sessions,
    ):
        result = await MindmapAiService.delete_session(
            database,
            'session-owned',
            user_id=7,
        )

    update_session.assert_awaited_once_with(database, 'session-owned', {'status': 'deleting'})
    assert request_cancellations.await_args.args[:2] == (database, 'session-owned')
    assert isinstance(request_cancellations.await_args.args[2], datetime)
    assert operation_order[:4] == ['commit', 'persist', 'commit', 'local']
    cancel.assert_awaited_once_with('job-active', 'codex')
    cascade.assert_awaited_once_with(
        database,
        'session-owned',
        ['job-active', 'job-finished'],
    )
    assert [call.args for call in mark_terminal.await_args_list] == [
        ('job-active', 2), ('job-finished', 4),
    ]
    purge_sdk_sessions.assert_awaited_once_with(
        [
            ('codex', 'codex-session'),
            ('claude', 'claude-session'),
        ],
        strict=True,
    )
    assert result == {
        'sessionId': 'session-owned',
        'deleted': True,
        'jobCount': 2,
        'sdkSessionCount': 2,
    }
    assert database.commit.await_count == EXPECTED_SESSION_DELETE_COMMITS


@pytest.mark.asyncio
async def test_delete_session_rejects_foreign_or_missing_session() -> None:
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ServiceException) as missing,
    ):
        await MindmapAiService.delete_session(
            SimpleNamespace(),
            'session-not-owned',
            user_id=8,
        )

    assert missing.value.message == 'AI 脑图会话不存在'


@pytest.mark.asyncio
async def test_delete_session_retry_accepts_concurrent_cascade_completion() -> None:
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    session = SimpleNamespace(id='session-owned', status='deleting')

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_session',
            new=AsyncMock(),
        ) as update_session,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.request_session_job_cancellations',
            new=AsyncMock(return_value=0),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_jobs_for_session',
            new=AsyncMock(return_value=[]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.delete_session_cascade',
            new=AsyncMock(return_value={'sessions': 0, 'jobs': 0}),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service._purge_adapter_session_references',
            new=AsyncMock(return_value=(0, 0)),
        ),
    ):
        result = await MindmapAiService.delete_session(database, session.id, user_id=7)

    update_session.assert_not_awaited()
    assert result == {
        'sessionId': session.id,
        'deleted': True,
        'jobCount': 0,
        'sdkSessionCount': 0,
    }
    assert database.commit.await_count == EXPECTED_SESSION_DELETE_COMMITS


@pytest.mark.asyncio
async def test_delete_session_keeps_database_record_when_sdk_purge_fails() -> None:
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    session = SimpleNamespace(id='session-owned', status='deleting')
    finished = SimpleNamespace(
        id='job-finished',
        status='ready',
        agent_key='codex',
        external_session_ref='encrypted-session',
    )
    cascade = AsyncMock(return_value={'sessions': 1, 'jobs': 1})

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_jobs_for_session',
            new=AsyncMock(return_value=[finished]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_session',
            new=AsyncMock(),
        ) as update_session,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.request_session_job_cancellations',
            new=AsyncMock(return_value=0),
        ) as request_cancellations,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.delete_session_cascade',
            new=cascade,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
            return_value='provider-session',
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service._purge_adapter_session_references',
            new=AsyncMock(side_effect=ServiceException(message='AI SDK 会话清理失败，请重试')),
        ),
        pytest.raises(ServiceException) as purge_error,
    ):
        await MindmapAiService.delete_session(
            database,
            'session-owned',
            user_id=7,
        )

    assert purge_error.value.message == 'AI SDK 会话清理失败，请重试'
    update_session.assert_not_awaited()
    request_cancellations.assert_awaited_once()
    cascade.assert_not_awaited()
    assert database.commit.await_count == EXPECTED_FAILED_PURGE_COMMITS


@pytest.mark.asyncio
async def test_session_timeline_returns_visible_prompt_and_sanitized_events_only() -> None:
    now = datetime.now()
    session = SimpleNamespace(
        id='session-1',
        title='会话',
        status='active',
        current_agent_key='codex',
        created_time=now,
        update_time=now,
        expires_time=now + timedelta(days=1),
    )
    job = SimpleNamespace(
        id='job-1',
        request_json=json.dumps({
            'prompt': '生成登录测试用例',
            'source': {'document': {'root': {'data': {'text': '私密正文'}}}},
        }, ensure_ascii=False),
        created_time=now,
    )
    event = SimpleNamespace(
        sequence=1,
        event_type='tool_completed',
        payload_json=json.dumps({
            'toolName': 'add_nodes',
            'prompt': '不得从事件返回',
            'previewState': {'root': {'data': {'text': '不得返回'}}},
        }, ensure_ascii=False),
        created_time=now,
    )

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_jobs_for_session',
            new=AsyncMock(return_value=[job]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_events',
            new=AsyncMock(return_value=[event]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service._job_model',
            new=lambda _job: SimpleNamespace(model_dump=lambda **_kwargs: {'id': 'job-1'}),
        ),
    ):
        timeline = await MindmapAiService.get_session_timeline(
            SimpleNamespace(),
            'session-1',
            user_id=7,
        )

    turn = timeline['turns'][0]
    assert turn['userMessage']['content'] == '生成登录测试用例'
    assert turn['events'][0]['payload'] == {'toolName': 'add_nodes'}
    serialized = json.dumps(timeline, ensure_ascii=False, default=str)
    assert '私密正文' not in serialized
    assert '不得返回' not in serialized


@pytest.mark.asyncio
async def test_session_timeline_pages_past_message_flood_and_keeps_domain_events() -> None:
    now = datetime.now()
    session = SimpleNamespace(
        id='session-flood',
        title='会话',
        status='active',
        current_agent_key='claude',
        created_time=now,
        update_time=now,
        expires_time=now + timedelta(days=1),
    )
    job = SimpleNamespace(
        id='job-flood',
        request_json=json.dumps({'prompt': '生成支付失败分支'}, ensure_ascii=False),
        created_time=now,
    )
    repeated_envelopes = [SimpleNamespace(
        sequence=sequence,
        event_type='agent_event',
        payload_json=json.dumps({
            'stage': 'building',
            'messageType': 'SystemMessage',
        }),
        created_time=now,
    ) for sequence in range(1, TIMELINE_PAGE_SIZE + 1)]
    domain_tail = [
        SimpleNamespace(
            sequence=TIMELINE_PAGE_SIZE + 1,
            event_type='tool_completed',
            payload_json=json.dumps({'toolName': 'complete_artifact'}),
            created_time=now,
        ),
        SimpleNamespace(
            sequence=TIMELINE_PAGE_SIZE + 2,
            event_type='artifact_ready',
            payload_json=json.dumps({'status': 'ready', 'progress': 100}),
            created_time=now,
        ),
    ]
    list_events = AsyncMock(side_effect=[repeated_envelopes, domain_tail])

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_jobs_for_session',
            new=AsyncMock(return_value=[job]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_events',
            new=list_events,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service._job_model',
            new=lambda _job: SimpleNamespace(model_dump=lambda **_kwargs: {'id': 'job-flood'}),
        ),
    ):
        timeline = await MindmapAiService.get_session_timeline(
            SimpleNamespace(),
            'session-flood',
            user_id=7,
        )

    assert [event['eventType'] for event in timeline['turns'][0]['events']] == [
        'agent_event',
        'tool_completed',
        'artifact_ready',
    ]
    assert [call.args[2] for call in list_events.await_args_list] == [0, TIMELINE_PAGE_SIZE]
    assert all(
        call.kwargs['limit'] == TIMELINE_PAGE_SIZE
        for call in list_events.await_args_list
    )
