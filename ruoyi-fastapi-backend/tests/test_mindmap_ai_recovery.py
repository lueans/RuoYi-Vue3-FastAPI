"""AI 脑图任务多 worker 恢复与有界取消测试。"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from config.env import MindmapAiConfig
from module_mindmap.ai.adapters.base import AgentRunResult
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.service.mindmap_ai_service import (
    _CURRENT_JOB_EXECUTION_EPOCH,
    _CURRENT_JOB_LEASE_TOKEN,
    ACTIVE_JOB_STATUSES,
    MindmapAiTaskManager,
)

EXPECTED_RECOVERED_JOBS = 501
EXPECTED_RECOVERY_PAGES = 3
RECOVERY_TEST_PAGE_SIZE = 200
MAX_CANCEL_WAIT_SECONDS = 0.25
MAX_RECOVERY_PAGE_SIZE = 2_000
OWNED_SDK_SESSION_ID = 'provider-child-session'
EXPECTED_RELEASE_UPDATES = 2
EXPECTED_RELEASE_REVISION = 11


class _SessionFactory:
    def __init__(self, database: SimpleNamespace | None = None) -> None:
        self.database = database or SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )

    def __call__(self) -> _SessionFactory:
        return self

    async def __aenter__(self) -> SimpleNamespace:
        return self.database

    async def __aexit__(self, *_args: object) -> None:
        return None


class _LeaseRedis:
    """足以验证 SET NX 与 compare-and-release 的并发假 Redis。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool,
        ex: int,
    ) -> bool:
        del ex
        async with self._lock:
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

    async def eval(
        self,
        script: str,
        _numkeys: int,
        key: str,
        token: str,
        *_args: object,
    ) -> int:
        async with self._lock:
            if self.values.get(key) != token:
                return 0
            if "redis.call('del'" in script:
                del self.values[key]
            return 1

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


@pytest.fixture(autouse=True)
def _reset_task_manager_state() -> None:
    previous_redis = MindmapAiTaskManager._redis
    previous_shutting_down = MindmapAiTaskManager._shutting_down
    previous_recovery_task = MindmapAiTaskManager._recovery_task
    previous_recovery_stop_event = MindmapAiTaskManager._recovery_stop_event
    MindmapAiTaskManager._redis = None
    MindmapAiTaskManager._shutting_down = False
    MindmapAiTaskManager._recovery_task = None
    MindmapAiTaskManager._recovery_stop_event = None
    MindmapAiTaskManager._tasks.clear()
    MindmapAiTaskManager._lease_lost_tasks.clear()
    MindmapAiTaskManager._detached_adapter_tasks.clear()
    yield
    MindmapAiTaskManager._redis = previous_redis
    MindmapAiTaskManager._shutting_down = previous_shutting_down
    MindmapAiTaskManager._recovery_task = previous_recovery_task
    MindmapAiTaskManager._recovery_stop_event = previous_recovery_stop_event
    MindmapAiTaskManager._tasks.clear()
    MindmapAiTaskManager._lease_lost_tasks.clear()
    MindmapAiTaskManager._detached_adapter_tasks.clear()


@pytest.mark.asyncio
async def test_job_lease_allows_only_one_worker_to_claim_same_job() -> None:
    redis = _LeaseRedis()
    MindmapAiTaskManager.configure_redis(redis)

    first, second = await asyncio.gather(
        MindmapAiTaskManager._acquire_job_lease('same-job', 'worker-a'),
        MindmapAiTaskManager._acquire_job_lease('same-job', 'worker-b'),
    )

    assert sorted((first, second)) == [False, True]
    winner = 'worker-a' if first else 'worker-b'
    loser = 'worker-b' if first else 'worker-a'
    await MindmapAiTaskManager._release_job_lease('same-job', loser)
    assert redis.values
    await MindmapAiTaskManager._release_job_lease('same-job', winner)
    assert redis.values == {}


@pytest.mark.asyncio
async def test_recovery_uses_keyset_pages_without_legacy_500_job_cap() -> None:
    created = datetime.now() - timedelta(hours=1)
    jobs = [
        SimpleNamespace(
            id=f'job-{index:03d}',
            created_time=created + timedelta(microseconds=index),
        )
        for index in range(EXPECTED_RECOVERED_JOBS)
    ]
    pages = [
        jobs[index:index + RECOVERY_TEST_PAGE_SIZE]
        for index in range(0, len(jobs), RECOVERY_TEST_PAGE_SIZE)
    ]
    list_recoverable = AsyncMock(side_effect=pages)

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_recoverable_jobs',
            new=list_recoverable,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_waiting_jobs',
            new=AsyncMock(return_value=[]),
        ),
        patch.object(MindmapAiTaskManager, 'schedule', new=MagicMock(return_value=True)) as schedule,
        patch.object(
            MindmapAiConfig,
            'mindmap_ai_recovery_batch_size',
            RECOVERY_TEST_PAGE_SIZE,
        ),
    ):
        recovered = await MindmapAiTaskManager.recover_pending()

    assert recovered == EXPECTED_RECOVERED_JOBS
    assert schedule.call_count == EXPECTED_RECOVERED_JOBS
    assert schedule.call_args_list[0] == call('job-000')
    assert schedule.call_args_list[-1] == call('job-500')
    assert list_recoverable.await_count == EXPECTED_RECOVERY_PAGES
    assert list_recoverable.await_args_list[0].kwargs['after_created_time'] is None
    assert list_recoverable.await_args_list[1].kwargs['after_created_time'] == jobs[199].created_time
    assert list_recoverable.await_args_list[1].kwargs['after_id'] == 'job-199'


@pytest.mark.asyncio
async def test_wake_waiting_followups_releases_only_the_oldest_queued_turn() -> None:
    parent = SimpleNamespace(
        id='queue-parent',
        session_id='queue-session',
        user_id=7,
        status='ready',
        artifact_id=None,
    )
    first_child = SimpleNamespace(
        id='queue-child-1',
        parent_job_id=parent.id,
        status='waiting_turn',
        turn_index=2,
        created_time=datetime.now() - timedelta(seconds=2),
        request_json=json.dumps({'source': {'type': 'none'}}),
        base_hash=None,
    )
    second_child = SimpleNamespace(
        id='queue-child-2',
        parent_job_id=parent.id,
        status='waiting_turn',
        turn_index=3,
        created_time=datetime.now() - timedelta(seconds=1),
        request_json=json.dumps({'source': {'type': 'none'}}),
        base_hash=None,
    )
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=parent),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_waiting_followups',
            new=AsyncMock(return_value=[second_child, first_child]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ) as update_job,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ) as add_event,
        patch.object(MindmapAiTaskManager, 'schedule', new=MagicMock()) as schedule,
        patch('module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event') as metric,
    ):
        await MindmapAiTaskManager._wake_waiting_followups(parent.id)

    update_job.assert_any_await(
        database,
        first_child.id,
        {
            'status': 'queued',
            'progress': 0,
            'error_code': None,
            'error_message': None,
        },
    )
    update_job.assert_any_await(
        database,
        second_child.id,
        {'parent_job_id': first_child.id},
    )
    assert update_job.await_count == EXPECTED_RELEASE_UPDATES
    schedule.assert_called_once_with(first_child.id)
    assert add_event.await_count == EXPECTED_RELEASE_UPDATES
    metric.assert_called_once_with('job_released')


@pytest.mark.asyncio
async def test_next_route_waits_for_parent_proposal_to_be_applied() -> None:
    parent = SimpleNamespace(
        id='route-parent',
        session_id='route-session',
        user_id=7,
        status='ready',
        proposal_id='route-proposal',
        artifact_id='route-artifact',
    )
    child = SimpleNamespace(
        id='route-child',
        parent_job_id=parent.id,
        status='waiting_turn',
        turn_index=2,
        created_time=datetime.now(),
        request_json=json.dumps({
            'queueRoute': 'next',
            'source': {'type': 'local_snapshot'},
        }),
        base_hash='old-hash',
    )
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=parent),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_waiting_followups',
            new=AsyncMock(return_value=[child]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ) as update_job,
        patch.object(MindmapAiTaskManager, 'schedule', new=MagicMock()) as schedule,
        patch('module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event') as metric,
    ):
        await MindmapAiTaskManager._wake_waiting_followups(parent.id)

    database.rollback.assert_awaited_once()
    database.commit.assert_not_awaited()
    update_job.assert_not_awaited()
    schedule.assert_not_called()
    metric.assert_not_called()


@pytest.mark.asyncio
async def test_direct_undo_wakes_followup_against_authoritative_document() -> None:
    """A direct receipt has no artifact, so an undone parent must still rebase its child."""
    parent = SimpleNamespace(
        id='direct-undone-parent',
        session_id='direct-session',
        user_id=7,
        status='undone',
        artifact_id=None,
        source_type='cloud_document',
        source_mindmap_id=42,
        proposal_id='direct-undone-parent',
        request_json=json.dumps({'executionMode': 'direct'}),
    )
    old_document = {
        'root': {
            'data': {'uid': 'root', 'text': 'old'},
            'children': [],
        },
    }
    child = SimpleNamespace(
        id='direct-undone-child',
        parent_job_id=parent.id,
        status='waiting_turn',
        turn_index=2,
        created_time=datetime.now(),
        request_json=json.dumps({
            'agentKey': 'native_mindmap',
            'intent': 'expand',
            'prompt': '继续补充',
            'target': 'file',
            'executionMode': 'direct',
            'source': {
                'type': 'cloud_document',
                'mindmapId': 42,
                'revision': 3,
                'documentHash': 'old-hash',
                'document': old_document,
                'baselineDocument': old_document,
            },
        }),
        base_hash='old-hash',
    )
    authoritative_document = {
        'root': {
            'data': {'uid': 'root', 'text': 'after undo'},
            'children': [],
        },
    }
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=parent),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_waiting_followups',
            new=AsyncMock(return_value=[child]),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ) as update_job,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ),
        patch.object(MindmapAiTaskManager, 'schedule', new=MagicMock()) as schedule,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiService._prepare_source_for_job',
            new=AsyncMock(return_value=(authoritative_document, 11, 'new-hash', 42, 'epoch-11')),
        ) as prepare_source,
        patch('module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event'),
    ):
        await MindmapAiTaskManager._wake_waiting_followups(parent.id)

    prepare_source.assert_awaited_once()
    released_values = update_job.await_args.args[2]
    request_payload = json.loads(released_values['request_json'])
    assert released_values['status'] == 'queued'
    assert released_values['base_revision'] == EXPECTED_RELEASE_REVISION
    assert released_values['base_hash'] == 'new-hash'
    assert released_values['base_room_epoch'] == 'epoch-11'
    assert request_payload['source']['revision'] == EXPECTED_RELEASE_REVISION
    assert request_payload['source']['documentHash'] == 'new-hash'
    assert request_payload['source']['document'] == authoritative_document
    schedule.assert_called_once_with(child.id)


@pytest.mark.asyncio
async def test_review_parent_does_not_release_queued_followups_before_user_decision() -> None:
    parent = SimpleNamespace(
        id='review-parent',
        session_id='review-session',
        user_id=7,
        status='needs_review',
        artifact_id='review-artifact',
    )
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=parent),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_waiting_followups',
            new=AsyncMock(),
        ) as list_waiting,
        patch.object(MindmapAiTaskManager, 'schedule', new=MagicMock()) as schedule,
    ):
        await MindmapAiTaskManager._wake_waiting_followups(parent.id)

    list_waiting.assert_not_awaited()
    schedule.assert_not_called()
    database.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejected_parent_closes_waiting_followups_during_recovery() -> None:
    parent = SimpleNamespace(
        id='rejected-parent',
        session_id='rejected-session',
        user_id=7,
        status='rejected',
        artifact_id='rejected-artifact',
    )
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=parent),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_close_waiting_followups',
            new=AsyncMock(),
        ) as close_waiting_followups,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_waiting_followups',
            new=AsyncMock(),
        ) as list_waiting,
    ):
        await MindmapAiTaskManager._wake_waiting_followups(parent.id)

    close_waiting_followups.assert_awaited_once_with(
        parent.id,
        parent_status='rejected',
    )
    list_waiting.assert_not_awaited()
    database.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_recoverable_query_requires_staleness_for_inflight_statuses() -> None:
    result = MagicMock()
    result.scalars.return_value = []
    database = SimpleNamespace(execute=AsyncMock(return_value=result))
    stale_before = datetime.now() - timedelta(minutes=1)

    jobs = await MindmapAiDao.list_recoverable_jobs(
        database,
        stale_before=stale_before,
        after_created_time=stale_before - timedelta(minutes=1),
        after_id='cursor-job',
        limit=5_000,
    )

    statement = database.execute.await_args.args[0]
    statement_text = str(statement)
    assert jobs == []
    assert 'mindmap_ai_job.update_time <=' in statement_text
    assert 'mindmap_ai_job.created_time >' in statement_text
    assert 'mindmap_ai_job.id >' in statement_text
    assert statement.compile().params['param_1'] == MAX_RECOVERY_PAGE_SIZE


@pytest.mark.asyncio
async def test_recovery_loop_retries_periodically_on_every_started_worker() -> None:
    recovered = asyncio.Event()

    async def recover_once() -> int:
        recovered.set()
        return 0

    with (
        patch.object(MindmapAiTaskManager, 'recover_pending', side_effect=recover_once),
        patch.object(MindmapAiConfig, 'mindmap_ai_recovery_interval_seconds', 0.01),
    ):
        MindmapAiTaskManager.start()
        await asyncio.wait_for(recovered.wait(), timeout=0.5)
        await MindmapAiTaskManager.shutdown()


@pytest.mark.asyncio
async def test_adapter_cancel_has_second_deadline_when_cancel_is_swallowed() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def ignores_first_cancel() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return 'late-result'

    waiter = asyncio.create_task(MindmapAiTaskManager._await_adapter_result(
        'stubborn-adapter',
        ignores_first_cancel(),
        cancel_grace_seconds=0.01,
    ))
    await started.wait()
    started_at = time.monotonic()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert time.monotonic() - started_at < MAX_CANCEL_WAIT_SECONDS
    assert len(MindmapAiTaskManager._detached_adapter_tasks) == 1
    release.set()
    for _attempt in range(10):
        if not MindmapAiTaskManager._detached_adapter_tasks:
            break
        await asyncio.sleep(0)
    assert MindmapAiTaskManager._detached_adapter_tasks == set()


@pytest.mark.asyncio
async def test_completed_adapter_result_is_cleaned_when_job_was_deleted_concurrently() -> None:
    result = AgentRunResult(
        title='迟到结果',
        artifact={},
        summary={},
        operations=[],
        external_session_id=OWNED_SDK_SESSION_ID,
        external_session_created=True,
    )
    discard_result = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await MindmapAiTaskManager._await_adapter_result(
            'deleted-while-finishing',
            asyncio.sleep(0, result=result),
            discard_result=discard_result,
        )

    discard_result.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_active_takeover_resets_state_only_after_lease_was_claimed() -> None:
    running_job = SimpleNamespace(
        id='stale-job',
        session_id='active-session',
        status='running',
        execution_epoch=4,
    )
    database = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
    transition = AsyncMock(return_value=True)
    update_job = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=running_job),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=SimpleNamespace(status='active')),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.transition_job_status',
            new=transition,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=update_job,
        ),
    ):
        runnable = await MindmapAiTaskManager._prepare_claimed_job('stale-job')

    assert runnable == 5  # noqa: PLR2004
    transition.assert_awaited_once_with(
        database,
        'stale-job',
        {'preparing', 'running', 'validating'},
        {
            'status': 'queued',
            'progress': 0,
            'error_code': None,
            'error_message': None,
        },
    )
    update_job.assert_awaited_once_with(database, 'stale-job', {'execution_epoch': 5})
    database.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_lease_renewal_heartbeats_with_explicit_claimed_execution_epoch() -> None:
    lease_lost = asyncio.Event()
    redis = SimpleNamespace(eval=AsyncMock(return_value=1))
    heartbeat = AsyncMock(side_effect=lambda *_args: lease_lost.set())
    MindmapAiTaskManager.configure_redis(redis)
    inherited_epoch = _CURRENT_JOB_EXECUTION_EPOCH.set(2)
    try:
        with (
            patch('asyncio.sleep', new=AsyncMock()),
            patch.object(
                MindmapAiTaskManager,
                '_touch_job_heartbeat',
                new=heartbeat,
            ),
        ):
            await MindmapAiTaskManager._renew_job_lease(
                'job-explicit-heartbeat',
                'lease-token',
                lease_lost,
                9,
            )
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(inherited_epoch)

    heartbeat.assert_awaited_once_with('job-explicit-heartbeat', 9)


@pytest.mark.asyncio
@pytest.mark.parametrize('job_status', ['queued', 'running'])
@pytest.mark.parametrize('session_state', ['deleting', 'expired_deadline'])
async def test_recovery_cancels_jobs_from_tombstoned_sessions_before_adapter_start(
    job_status: str,
    session_state: str,
) -> None:
    job = SimpleNamespace(
        id=f'tombstoned-{job_status}',
        session_id='deleted-session',
        status=job_status,
    )
    database = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    transition = AsyncMock(return_value=True)
    add_event = AsyncMock()
    session = (
        SimpleNamespace(status='deleting')
        if session_state == 'deleting'
        else SimpleNamespace(
            status='active',
            expires_time=datetime.now() - timedelta(seconds=1),
        )
    )

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ) as get_job,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            new=AsyncMock(return_value=session),
        ) as get_session,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.transition_job_status',
            new=transition,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=add_event,
        ),
        patch.object(MindmapAiTaskManager, '_run_job', new=AsyncMock()) as run_job,
    ):
        await MindmapAiTaskManager._run_scheduled_job(job.id)

    get_job.assert_awaited_once_with(database, job.id, for_update=True)
    get_session.assert_awaited_once_with(
        database,
        job.session_id,
        for_update=True,
    )
    transition.assert_awaited_once()
    assert transition.await_args.args[2] == ACTIVE_JOB_STATUSES
    assert transition.await_args.args[3]['status'] == 'cancelled'
    add_event.assert_awaited_once()
    assert add_event.await_args.args[2] == 'status_changed'
    database.commit.assert_awaited_once()
    run_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_write_rechecks_lease_while_database_row_is_locked() -> None:
    database = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
    lease_context = _CURRENT_JOB_LEASE_TOKEN.set('old-worker')
    try:
        with (
            patch.object(
                MindmapAiTaskManager,
                '_owns_job_lease',
                new=AsyncMock(side_effect=[True, False]),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=SimpleNamespace(status='running')),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.transition_job_status',
                new=AsyncMock(),
            ) as transition,
            patch(
                'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
                new=_SessionFactory(database),
            ),
        ):
            changed = await MindmapAiTaskManager._set_status('job-fenced', 'validating', 85)
    finally:
        _CURRENT_JOB_LEASE_TOKEN.reset(lease_context)

    assert changed is False
    transition.assert_not_awaited()
    database.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_completion_gate_rejects_deleting_session_before_result_writes() -> None:
    database = SimpleNamespace(rollback=AsyncMock())
    job = SimpleNamespace(id='job-finishing', session_id='session-deleting', status='validating')
    session = SimpleNamespace(id='session-deleting', status='deleting')
    lock_order: list[str] = []

    async def get_job(*_args: object, **_kwargs: object) -> SimpleNamespace:
        lock_order.append('job')
        return job

    async def get_session(*_args: object, **_kwargs: object) -> SimpleNamespace:
        lock_order.append('session')
        return session

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            side_effect=get_job,
        ) as locked_job,
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_session',
            side_effect=get_session,
        ) as locked_session,
        patch.object(
            MindmapAiTaskManager,
            '_owns_current_job_lease',
            new=AsyncMock(return_value=True),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await MindmapAiTaskManager._lock_completion_target(database, job.id)

    locked_job.assert_awaited_once_with(database, job.id, for_update=True)
    locked_session.assert_awaited_once_with(database, session.id, for_update=True)
    assert lock_order == ['job', 'session']
    database.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('source_kind', ['none', 'branch', 'recovered_branch'])
@pytest.mark.parametrize(
    ('failure_stage', 'reconciliation', 'expects_purge'),
    [
        ('validation', None, True),
        ('session_deletion', None, True),
        ('commit_not_persisted', False, True),
        ('commit_persisted', True, False),
        ('commit_unknown', None, False),
        ('committed', None, False),
    ],
)
async def test_owned_sdk_session_is_purged_until_result_transaction_commits(
    failure_stage: str,
    reconciliation: bool | None,
    expects_purge: bool,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
) -> None:
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_service.load_ai_tag_catalog',
        AsyncMock(return_value=[{'tagId': 7, 'text': 'Known', 'status': 0}]),
    )
    source_document = {'root': {'data': {'uid': 'root', 'text': 'Source'}, 'children': [
        {'data': {'uid': 'allowed', 'text': 'Allowed'}, 'children': []},
        {'data': {'uid': 'private', 'text': 'Private'}, 'children': []},
    ]}}
    source = {'type': 'none'} if source_kind == 'none' else {
        'type': 'local_snapshot', 'documentId': 'source', 'revision': 1,
        'document': source_document, 'scope': {'type': 'branch', 'rootUid': 'allowed'},
    }
    monkeypatch.setattr(MindmapAiTaskManager, '_emit', AsyncMock())
    if source_kind == 'recovered_branch':
        monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint', AsyncMock())
        monkeypatch.setattr(MindmapAiTaskManager, '_draft_checkpoint_preview', MagicMock(return_value={
            'operationCursor': 1, 'previewEpoch': 1,
            'document': {'root': source_document['root']['children'][0]},
        }))
    request_json = json.dumps({
        'agentKey': 'codex',
        'intent': 'create',
        'prompt': '生成脑图',
        'source': source,
        'target': 'file',
    })
    job = SimpleNamespace(
        id='job-owned-session',
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
        intent='create',
        parent_job_id=None,
        session_id='session-owned',
        base_revision=None,
        base_hash=None,
        base_room_epoch=None,
    )
    document = {
        'root': {'data': {'uid': 'root', 'text': 'AI 脑图'}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }
    artifact = {
        'manifest': {
            'artifactId': 'artifact-owned-session',
            'documentHash': 'document-hash',
            'validation': {'status': 'passed'},
        },
        'document': document,
    }
    summary = {'nodeCount': 1, 'treeDepth': 1}
    result = AgentRunResult(
        title='AI 脑图',
        artifact=artifact,
        summary=summary,
        operations=[],
        external_session_id=OWNED_SDK_SESSION_ID,
        external_session_created=True,
    )
    manifest = SimpleNamespace(
        status='enabled',
        status_reason=None,
        max_nodes=100,
        max_depth=10,
    )

    async def run_adapter(context: object, _emit: object) -> AgentRunResult:
        if source_kind == 'none':
            context.tool_service.start_document('AI 脑图', 'logicalStructure')
        else:
            assert context.source_document['root']['data']['uid'] == 'allowed'
            assert 'private' not in json.dumps(context.source_document)
        assert [tag['tagId'] for tag in context.tool_service.search_tags('Known')] == [7]
        return result

    adapter = SimpleNamespace(
        get_manifest=lambda: manifest,
        start=AsyncMock(side_effect=run_adapter),
        resume=AsyncMock(side_effect=run_adapter),
        collect_usage=MagicMock(return_value={}),
        purge_session=AsyncMock(return_value=True),
    )
    database = SimpleNamespace(
        commit=AsyncMock(
            side_effect=(
                RuntimeError('commit failed')
                if failure_stage.startswith('commit_')
                else None
            ),
        ),
        rollback=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    current_session = SimpleNamespace(
        id='session-owned',
        status='active',
        expires_time=datetime.now() + timedelta(days=1),
    )
    validation = MagicMock(return_value=(artifact, summary))
    if failure_stage == 'validation':
        validation.side_effect = MindmapArtifactError(
            'post-return validation failed',
            code='AI_OUTPUT_INVALID',
        )
    completion_lock = AsyncMock(return_value=(job, current_session))
    if failure_stage == 'session_deletion':
        completion_lock.side_effect = asyncio.CancelledError
    fail_job = AsyncMock()
    reconcile_commit = AsyncMock(return_value=reconciliation)

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(database),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=SimpleNamespace(get=lambda _agent_key: adapter),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.resolve_connector_credential',
            return_value={},
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service._validate_job_result_artifact',
            new=validation,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_draft_event_payloads',
            new=AsyncMock(return_value=[json.dumps({'previewVersion': 1, 'previewEpoch': 1})]
                          if source_kind == 'recovered_branch' else []),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=job),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_artifact',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_job',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.update_session',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.'
            'MindmapAiService._ensure_connector_available',
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_begin_draft_preview_run',
            new=AsyncMock(),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_set_status',
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_enforce_result_policy',
            new=MagicMock(),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_lock_completion_target',
            new=completion_lock,
        ),
        patch.object(
            MindmapAiTaskManager,
            '_owns_current_job_lease',
            new=AsyncMock(return_value=True),
        ),
        patch.object(MindmapAiTaskManager, '_fail', new=fail_job),
        patch.object(
            MindmapAiTaskManager,
            '_reconcile_external_session_commit',
            new=reconcile_commit,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_run',
            new=MagicMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_event',
            new=MagicMock(),
        ),
    ):
        await MindmapAiTaskManager._run_job(job.id)

    if expects_purge:
        adapter.purge_session.assert_awaited_once_with(OWNED_SDK_SESSION_ID)
    else:
        adapter.purge_session.assert_not_awaited()
    if failure_stage == 'committed':
        assert fail_job.await_args is None, repr(fail_job.await_args)
    if failure_stage.startswith('commit_'):
        reconcile_commit.assert_awaited_once()
    else:
        reconcile_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_runner_failure_is_availability_error_without_internal_details() -> None:
    private_detail = 'database password private-value'
    fail_job = AsyncMock()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.list_draft_event_payloads',
            new=AsyncMock(side_effect=RuntimeError(private_detail)),
        ),
        patch.object(
            MindmapAiTaskManager,
            '_set_status',
            new=AsyncMock(return_value=True),
        ),
        patch.object(MindmapAiTaskManager, '_fail', new=fail_job),
        patch(
            'module_mindmap.service.mindmap_ai_service.record_mindmap_ai_run',
            new=MagicMock(),
        ),
    ):
        await MindmapAiTaskManager._run_job('job-internal-failure')

    fail_job.assert_awaited_once_with(
        'job-internal-failure',
        'AI_AGENT_UNAVAILABLE',
        'AI 脑图服务暂不可用，请稍后重试或切换 Agent',
    )
    assert private_detail not in fail_job.await_args.args[2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('persisted_ref', 'expected'),
    [
        ('encrypted-owned-session', True),
        (None, False),
        ('encrypted-other-session', False),
    ],
)
async def test_commit_reconciliation_uses_fresh_session_and_exact_reference(
    persisted_ref: str | None,
    expected: bool,
) -> None:
    reconciliation_db = SimpleNamespace()
    factory = _SessionFactory(reconciliation_db)
    get_job = AsyncMock(return_value=SimpleNamespace(
        external_session_ref=persisted_ref,
    ))

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=factory,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=get_job,
        ),
    ):
        result = await MindmapAiTaskManager._reconcile_external_session_commit(
            'job-commit-uncertain',
            'encrypted-owned-session',
        )

    assert result is expected
    get_job.assert_awaited_once_with(reconciliation_db, 'job-commit-uncertain')


@pytest.mark.asyncio
async def test_commit_reconciliation_preserves_session_when_database_is_unavailable() -> None:
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(side_effect=RuntimeError('database unavailable')),
        ),
    ):
        result = await MindmapAiTaskManager._reconcile_external_session_commit(
            'job-commit-unknown',
            'encrypted-owned-session',
        )

    assert result is None


@pytest.mark.asyncio
async def test_reused_parent_sdk_session_is_never_claimed_or_purged() -> None:
    adapter = SimpleNamespace(purge_session=AsyncMock(return_value=True))
    result = AgentRunResult(
        title='复用父会话',
        artifact={},
        summary={},
        operations=[],
        external_session_id='parent-session',
        external_session_created=False,
    )

    owned = MindmapAiTaskManager._owned_external_session_id(
        result,
        'parent-session',
    )

    assert owned is None
    adapter.purge_session.assert_not_awaited()


def test_adapter_cannot_return_a_different_unowned_session_id() -> None:
    result = AgentRunResult(
        title='未声明所有权的会话',
        artifact={},
        summary={},
        operations=[],
        external_session_id='different-session',
        external_session_created=False,
    )

    with pytest.raises(MindmapArtifactError, match='未声明新建 SDK 会话') as error:
        MindmapAiTaskManager._owned_external_session_id(
            result,
            'parent-session',
        )

    assert error.value.code == 'AI_SESSION_UNAVAILABLE'


def test_same_agent_followup_requires_a_restorable_sdk_session() -> None:
    parent = SimpleNamespace(agent_key='codex', external_session_ref=None)

    with pytest.raises(MindmapArtifactError, match='缺少可恢复') as missing:
        MindmapAiTaskManager._resolve_parent_external_session_id(
            parent,
            agent_key='codex',
            supports_sessions=True,
        )

    assert missing.value.code == 'AI_SESSION_UNAVAILABLE'

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
            side_effect=RuntimeError('private ciphertext detail'),
        ),
        pytest.raises(MindmapArtifactError) as corrupt,
    ):
        parent.external_session_ref = 'encrypted-session'
        MindmapAiTaskManager._resolve_parent_external_session_id(
            parent,
            agent_key='codex',
            supports_sessions=True,
        )

    assert corrupt.value.code == 'AI_SESSION_UNAVAILABLE'
    assert 'private ciphertext detail' not in str(corrupt.value)

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
            return_value='',
        ),
        pytest.raises(MindmapArtifactError) as empty,
    ):
        MindmapAiTaskManager._resolve_parent_external_session_id(
            parent,
            agent_key='codex',
            supports_sessions=True,
        )

    assert empty.value.code == 'AI_SESSION_UNAVAILABLE'


def test_cross_agent_or_sessionless_followup_rebuilds_without_decryption() -> None:
    parent = SimpleNamespace(
        agent_key='codex',
        external_session_ref='encrypted-parent-session',
    )

    with patch(
        'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
    ) as decrypt:
        assert MindmapAiTaskManager._resolve_parent_external_session_id(
            parent,
            agent_key='claude',
            supports_sessions=True,
        ) is None
        assert MindmapAiTaskManager._resolve_parent_external_session_id(
            parent,
            agent_key='codex',
            supports_sessions=False,
        ) is None

    decrypt.assert_not_called()


def test_needs_input_followup_never_resumes_the_parent_provider_session() -> None:
    parent = SimpleNamespace(
        status='needs_input',
        agent_key='codex',
        external_session_ref='encrypted-clarification-session',
    )

    with patch(
        'module_mindmap.service.mindmap_ai_service.CryptoUtil.decrypt',
    ) as decrypt:
        assert MindmapAiTaskManager._resolve_parent_external_session_id(
            parent,
            agent_key='codex',
            supports_sessions=True,
        ) is None

    decrypt.assert_not_called()


@pytest.mark.asyncio
async def test_adapter_cancel_hook_cannot_hang_cancel_api() -> None:
    release = asyncio.Event()

    async def ignores_cancel(_job_id: str) -> bool:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return False

    adapter = SimpleNamespace(cancel=ignores_cancel)
    registry = SimpleNamespace(get=lambda _agent_key: adapter)
    started_at = time.monotonic()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
            return_value=registry,
        ),
        patch.object(MindmapAiConfig, 'mindmap_ai_adapter_cancel_grace_seconds', 0.01),
    ):
        cancelled = await MindmapAiTaskManager.cancel('stubborn-cancel-hook', 'future-agent')

    assert cancelled is False
    assert time.monotonic() - started_at < MAX_CANCEL_WAIT_SECONDS
    assert len(MindmapAiTaskManager._detached_adapter_tasks) == 1
    release.set()
    for _attempt in range(10):
        if not MindmapAiTaskManager._detached_adapter_tasks:
            break
        await asyncio.sleep(0)
    assert MindmapAiTaskManager._detached_adapter_tasks == set()


def test_agent_context_metadata_passes_retention_policy_to_sdk_adapter() -> None:
    metadata = MindmapAiTaskManager._agent_context_metadata(
        model=None,
        model_ref='gpt-test',
        max_budget_usd=1.25,
        timeout_seconds=300,
        retention_days=17,
        credential_env={'OPENAI_API_KEY': 'redacted-test-value'},
    )

    assert metadata['retentionDays'] == 17  # noqa: PLR2004
    assert metadata['modelRef'] == 'gpt-test'
