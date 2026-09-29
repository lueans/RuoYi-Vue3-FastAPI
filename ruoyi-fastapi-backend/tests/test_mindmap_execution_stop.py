"""The worker must stop on durable result fences, not just a cancel label."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.service import mindmap_ai_service as service


@pytest.fixture
def job_state(monkeypatch):
    job = SimpleNamespace(status='running', execution_epoch=3)

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(service, 'AsyncSessionLocal', session)
    monkeypatch.setattr(service.MindmapAiDao, 'get_job', AsyncMock(return_value=job))
    return job


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['ready', 'needs_review', 'applied', 'failed', 'expired'])
async def test_preserved_or_terminal_result_stops_other_workers_adapter(job_state, status):
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def run():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    waiter = asyncio.create_task(service.MindmapAiTaskManager._await_adapter_result(
        'remote-worker-stop', run(), timeout_seconds=10,
    ))
    try:
        await started.wait()
        job_state.status = status
        done, _ = await asyncio.wait({waiter}, timeout=1.5)
        assert waiter in done, 'A retained draft must not leave the remote Agent running'
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert stopped.is_set()
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_replaced_execution_epoch_stops_old_adapter(job_state):
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def run():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    token = service._CURRENT_JOB_EXECUTION_EPOCH.set(3)
    waiter = asyncio.create_task(service.MindmapAiTaskManager._await_adapter_result(
        'old-worker-epoch', run(), timeout_seconds=10,
    ))
    service._CURRENT_JOB_EXECUTION_EPOCH.reset(token)
    try:
        await started.wait()
        job_state.execution_epoch = 4
        done, _ = await asyncio.wait({waiter}, timeout=1.5)
        assert waiter in done, 'An obsolete execution must stop even if the job is running again'
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert stopped.is_set()
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['ready', 'needs_review', 'cancelled'])
async def test_late_result_after_stop_is_discarded(job_state, status):
    result = object()
    discard = AsyncMock()

    async def run():
        job_state.status = status
        return result

    with pytest.raises(asyncio.CancelledError):
        await service.MindmapAiTaskManager._await_adapter_result(
            'late-result', run(), discard_result=discard,
        )
    discard.assert_awaited_once_with(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('trigger', ['user_cancel', 'timeout', 'remote_cancel'])
async def test_unfinished_cleanup_is_failure_not_confirmed_cancel(job_state, trigger):
    started = asyncio.Event()
    release = asyncio.Event()
    cleanup_started = asyncio.Event()
    adapter_task = None

    async def run():
        nonlocal adapter_task
        adapter_task = asyncio.current_task()
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            await release.wait()

    waiter = asyncio.create_task(service.MindmapAiTaskManager._await_adapter_result(
        'unconfirmed-stop', run(),
        timeout_seconds=0.01 if trigger == 'timeout' else 10,
        cancel_grace_seconds=0.01,
    ))
    try:
        await started.wait()
        if trigger == 'user_cancel':
            waiter.cancel()
        elif trigger == 'remote_cancel':
            job_state.status = 'cancel_requested'
        done, _ = await asyncio.wait({waiter}, timeout=1.5)
        assert waiter in done
        with pytest.raises(MindmapArtifactError) as error:
            await waiter
        assert error.value.code == 'AI_AGENT_CLEANUP_FAILED'
        assert cleanup_started.is_set()
        assert adapter_task in service.MindmapAiTaskManager._detached_adapter_tasks
        assert not adapter_task.done(), 'Do not interrupt in-progress cleanup twice'
    finally:
        release.set()
        await asyncio.gather(waiter, return_exceptions=True)
        if adapter_task is not None:
            await asyncio.gather(adapter_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_second_cancellation_cannot_mask_a_completed_cleanup_failure(job_state, monkeypatch):
    started = asyncio.Event()

    async def run():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise MindmapArtifactError('child still alive', code='AI_AGENT_CLEANUP_FAILED')

    async def interrupted_stop(task, *_args, **_kwargs):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # Model a second cancellation arriving at the end of the cleanup wait.
        raise asyncio.CancelledError

    monkeypatch.setattr(service.MindmapAiTaskManager, '_cancel_adapter_task', interrupted_stop)
    waiter = asyncio.create_task(service.MindmapAiTaskManager._await_adapter_result('double-stop', run()))
    await started.wait()
    waiter.cancel()
    with pytest.raises(MindmapArtifactError) as error:
        await waiter
    assert error.value.code == 'AI_AGENT_CLEANUP_FAILED'
