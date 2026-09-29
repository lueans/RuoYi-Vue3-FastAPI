"""Real, disposable Python process trees; no CLI/model/application database."""

import asyncio
import os
import signal
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import psutil
import pytest

from module_mindmap.ai.adapters import _fs_utils as processes
from module_mindmap.ai.document import MindmapArtifactError

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX process-group contract')
CHILD = (
    'import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
    'print(os.getpid(), flush=True); time.sleep(20)'
)


@pytest.fixture(autouse=True)
def short_grace(monkeypatch):
    monkeypatch.setattr(processes, 'PROCESS_TERM_GRACE_SECONDS', 0.15)
    monkeypatch.setattr(processes, 'PROCESS_KILL_GRACE_SECONDS', 1.0)
    monkeypatch.setattr(processes, 'PROCESS_POLL_SECONDS', 0.01)


def running(pid):
    try:
        return psutil.Process(pid).status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
    except psutil.NoSuchProcess:
        return False


async def launch(script, cwd):
    return await processes.spawn_owned_process(
        sys.executable, '-c', script, cwd=cwd, env={'PATH': os.environ.get('PATH', '')},
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )


async def emergency_stop(process, child_pid=None):
    # Only targets processes just created by this test. Prevents failed tests
    # from leaving even a 20-second helper behind.
    if child_pid and running(child_pid):
        os.kill(child_pid, signal.SIGKILL)
    if process.returncode is None:
        process.kill()
    await asyncio.wait_for(process.wait(), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize('parent_exits', [False, True])
async def test_cleanup_kills_stubborn_child_even_if_cli_parent_exits_first(tmp_path, parent_exits):
    script = (
        'import subprocess,sys,time; '
        f'subprocess.Popen([sys.executable,"-c",{CHILD!r}]); '
        + ('sys.exit(0)' if parent_exits else 'time.sleep(20)')
    )
    process = await launch(script, tmp_path)
    child_pid = None
    try:
        child_pid = int(await asyncio.wait_for(process.stdout.readline(), 3))
        if parent_exits:
            for _ in range(100):
                if process.returncode is not None:
                    break
                await asyncio.sleep(0.01)
            assert process.returncode == 0
        assert running(child_pid)
        await asyncio.wait_for(processes.terminate_process(process), 4)
        assert not running(child_pid)
        assert process.returncode is not None
        # Completed cleanup is a tombstone, never a second PID-based kill.
        await processes.terminate_process(process)
    finally:
        await emergency_stop(process, child_pid)


@pytest.mark.asyncio
async def test_concurrent_cleanup_is_one_operation_and_survives_repeated_cancel(tmp_path, monkeypatch):
    process = await launch(CHILD, tmp_path)
    original_killpg = os.killpg
    signals = []
    def track(pid, sig):
        if sig:
            signals.append(sig)
        return original_killpg(pid, sig)
    monkeypatch.setattr(processes.os, 'killpg', track)
    try:
        await asyncio.wait_for(process.stdout.readline(), 3)
        first = asyncio.create_task(processes.terminate_process(process))
        second = asyncio.create_task(processes.terminate_process(process))
        await asyncio.sleep(0.02)
        first.cancel()
        await asyncio.sleep(0.02)
        first.cancel()
        results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 4)
        assert isinstance(results[0], asyncio.CancelledError)
        assert results[1] is None
        assert signals == [signal.SIGTERM, signal.SIGKILL]
        assert not running(process.pid)
    finally:
        await emergency_stop(process)


@pytest.mark.asyncio
async def test_cancellation_during_spawn_waits_for_and_cleans_the_actual_child(tmp_path, monkeypatch):
    original_spawn = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    release = asyncio.Event()
    observed = []
    async def delayed_spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        observed.append(process)
        spawned.set()
        await release.wait()
        return process
    monkeypatch.setattr(processes.asyncio, 'create_subprocess_exec', delayed_spawn)
    task = asyncio.create_task(launch(CHILD, tmp_path))
    await asyncio.wait_for(spawned.wait(), 3)
    process = observed[0]
    try:
        await asyncio.wait_for(process.stdout.readline(), 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()  # no abandoned subprocess creation coroutine
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 4)
        assert not running(process.pid)
    finally:
        release.set()
        await emergency_stop(process)


@pytest.mark.asyncio
async def test_spawn_requires_an_explicit_private_process_group(monkeypatch):
    spawn = AsyncMock()
    monkeypatch.setattr(processes.asyncio, 'create_subprocess_exec', spawn)
    with pytest.raises(ValueError):
        await processes.spawn_owned_process('unused')
    spawn.assert_not_awaited()


def test_recycled_leader_pid_is_not_signalled(monkeypatch):
    class DifferentProcess:
        def create_time(self):
            return 200.0
    monkeypatch.setattr(processes.psutil, 'Process', lambda _pid: DifferentProcess())
    monkeypatch.setattr(processes.os, 'killpg', lambda *_args: pytest.fail('must not signal recycled PID'))
    assert processes._group_has_running_members(processes._OwnedGroup(12345, 100.0)) is False


@pytest.mark.asyncio
async def test_process_like_object_does_not_authorize_group_signalling(monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = None
        def terminate(self):
            self.returncode = -15
        def kill(self):
            pytest.fail('not needed')
        async def wait(self):
            return self.returncode
    monkeypatch.setattr(processes.os, 'killpg', lambda *_args: pytest.fail('not an owned group'))
    await processes.terminate_process(FakeProcess())


@pytest.mark.asyncio
async def test_unconfirmed_cleanup_is_an_error_not_a_success(monkeypatch):
    def denied(_group):
        raise PermissionError
    monkeypatch.setattr(processes, '_group_has_running_members', denied)
    with pytest.raises(MindmapArtifactError, match='清理未确认完成'):
        await processes._terminate_owned_group(None, processes._OwnedGroup(12345, 100.0))


@pytest.mark.asyncio
async def test_real_codex_worker_success_waits_for_leftover_children(tmp_path, monkeypatch):
    from module_mindmap.ai.adapters import codex
    monkeypatch.setattr(codex, '_CODEX_WORKER_PATH',
                        Path(__file__).with_name('fixtures') / 'mindmap_orphan_worker.py')
    adapter = codex.CodexMindmapAdapter()
    result = await adapter._invoke_worker(
        {'protocolVersion': codex.WORKER_PROTOCOL_VERSION}, workspace=tmp_path,
        environment={'PATH': os.environ.get('PATH', '')}, job_id='owned-cleanup-test', timeout=5,
    )
    assert result['ok'] is True
    assert not running(result['childPid'])
    assert 'owned-cleanup-test' not in adapter._processes


@pytest.mark.asyncio
async def test_cleanup_failure_never_retries_a_provider(monkeypatch):
    from module_mindmap.ai.adapters.base import AgentRunContext, run_adapter_with_transient_retries
    from module_mindmap.ai.tool_contract import MindmapToolService
    runner = AsyncMock(side_effect=processes.AgentProcessCleanupError)
    context = AgentRunContext(
        job_id='cleanup-failed', user_id=1, intent='create', prompt='测试',
        parameters={}, source_document=None, tool_service=MindmapToolService(),
    )
    with pytest.raises(processes.AgentProcessCleanupError):
        await run_adapter_with_transient_retries(runner, context, AsyncMock())
    assert runner.await_count == 1


@pytest.mark.asyncio
async def test_job_cancel_propagates_cleanup_failure_instead_of_confirming_stop():
    from module_mindmap.service.mindmap_ai_service import MindmapAiTaskManager
    ready = asyncio.Event()
    async def runner():
        ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise processes.AgentProcessCleanupError
    task = asyncio.create_task(runner())
    await ready.wait()
    with pytest.raises(processes.AgentProcessCleanupError):
        await MindmapAiTaskManager._cancel_adapter_task(task, 'test', grace_seconds=1)
    assert task.done()


@pytest.mark.asyncio
async def test_kimi_releases_session_and_draft_even_when_process_stop_fails(monkeypatch):
    from types import SimpleNamespace
    from module_mindmap.ai.adapters import kimi
    from module_mindmap.ai.adapters.base import AgentRunContext
    from module_mindmap.ai.tool_contract import MindmapToolService
    original = MindmapToolService()
    context = AgentRunContext(
        job_id='kimi-cleanup-failure', user_id=1, intent='create', prompt='测试',
        parameters={}, source_document=None, tool_service=original,
    )
    session = SimpleNamespace(start=AsyncMock(), prompt=AsyncMock(side_effect=asyncio.CancelledError),
                              cancel=AsyncMock(), close=AsyncMock())
    @asynccontextmanager
    async def server(*_args):
        yield {}
    adapter = kimi.KimiMindmapAdapter()
    monkeypatch.setattr(adapter, 'get_manifest', lambda: SimpleNamespace(status='enabled'))
    monkeypatch.setattr(kimi, 'resolve_cli', lambda _key: '/test/kimi')
    monkeypatch.setattr(kimi, 'spawn_owned_process', AsyncMock(return_value=object()))
    monkeypatch.setattr(kimi, 'terminate_process', AsyncMock(side_effect=processes.AgentProcessCleanupError))
    monkeypatch.setattr(kimi, 'mindmap_http_mcp', server)
    def make_session(_process, _emit, *, allowed_tools):
        assert allowed_tools == kimi.tools_for_execution_mode(context.execution_mode)
        return session
    monkeypatch.setattr(kimi, 'AcpSession', make_session)
    with pytest.raises(processes.AgentProcessCleanupError):
        await adapter.run(context, AsyncMock())
    session.close.assert_awaited_once()
    assert context.tool_service is original
    assert not adapter._tasks
