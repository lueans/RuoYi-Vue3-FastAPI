"""Claude cancellation crosses the task manager without interrupting SDK cleanup."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import anyio
import claude_agent_sdk
import pytest
from claude_agent_sdk._internal import session_resume
from claude_agent_sdk._internal.transport import subprocess_cli

from module_mindmap.ai.adapters import claude
from module_mindmap.ai.adapters._fs_utils import AgentProcessCleanupError
from module_mindmap.ai.adapters.base import AgentRunContext
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.service.mindmap_ai_service import MindmapAiTaskManager


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> claude.ClaudeMindmapAdapter:
    monkeypatch.setattr(claude, '_resolve_claude_environment', lambda _: {})
    monkeypatch.setattr(claude, '_isolated_claude_environment', lambda *_: {})
    monkeypatch.setattr(claude_agent_sdk, 'create_sdk_mcp_server', lambda **_: {
        'type': 'sdk', 'name': 'mindmap', 'instance': object(),
    })
    return claude.ClaudeMindmapAdapter(session_storage_root=tmp_path)


def context(intent: str) -> AgentRunContext:
    return AgentRunContext(
        job_id='claude-cleanup-test', user_id=1, intent=intent, prompt='测试',
        parameters={}, source_document=None, tool_service=MindmapToolService(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('intent', ['create', 'discuss'])
@pytest.mark.parametrize('cleanup_fails', [False, True])
async def test_repeated_cancel_waits_for_sdk_cleanup_in_its_original_task(
    runtime: claude.ClaudeMindmapAdapter, monkeypatch: pytest.MonkeyPatch, intent: str, cleanup_fails: bool,
) -> None:
    started, closing, release, closed = (asyncio.Event() for _ in range(4))

    async def query(**_kwargs: Any) -> AsyncIterator[Any]:
        owner = asyncio.current_task()
        with anyio.CancelScope():
            try:
                started.set()
                await asyncio.Event().wait()
                yield None
            finally:
                closing.set()
                await release.wait()
                assert asyncio.current_task() is owner
                if cleanup_fails:
                    raise AgentProcessCleanupError
                closed.set()

    monkeypatch.setattr(claude, '_claude_query', query)
    ctx = context(intent)
    task = asyncio.create_task(runtime.run(ctx, AsyncMock()))
    stop = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(closing.wait(), 1)
        assert await runtime.cancel(ctx.job_id)
        stop = asyncio.create_task(MindmapAiTaskManager._cancel_adapter_task(task, ctx.job_id, grace_seconds=1))
        await asyncio.sleep(0.01)
        assert not stop.done(), 'stop must not confirm an interrupted SDK cleanup'
        assert not task.done()
        release.set()
        if cleanup_fails:
            with pytest.raises(AgentProcessCleanupError):
                await stop
        else:
            await stop
            assert closed.is_set()
        assert ctx.job_id not in runtime._tasks
        assert ctx.job_id not in runtime._cancel_events
    finally:
        release.set()
        await asyncio.gather(task, *([stop] if stop else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('intent', ['create', 'discuss'])
async def test_explicit_stream_close_failure_does_not_confirm_execution_stopped(
    runtime: claude.ClaudeMindmapAdapter, monkeypatch: pytest.MonkeyPatch, intent: str,
) -> None:
    started = asyncio.Event()

    class Stream:
        def __aiter__(self) -> 'Stream':
            return self

        async def __anext__(self) -> Any:
            started.set()
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def aclose(self) -> None:
            raise OSError('private process cleanup failure')

    monkeypatch.setattr(claude, '_claude_query', lambda **_: Stream())
    ctx = context(intent)
    task = asyncio.create_task(runtime.run(ctx, AsyncMock()))
    await asyncio.wait_for(started.wait(), 1)
    with pytest.raises(MindmapArtifactError) as error:
        await MindmapAiTaskManager._cancel_adapter_task(task, ctx.job_id, grace_seconds=1)
    assert error.value.code == 'AI_AGENT_CLEANUP_FAILED'
    assert 'private' not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('cleanup_fails', [False, True])
@pytest.mark.parametrize('body_error', [False, True])
async def test_real_sdk_client_disconnects_after_consumer_body_exit(
    runtime: claude.ClaudeMindmapAdapter, monkeypatch: pytest.MonkeyPatch, cleanup_fails: bool, body_error: bool,
) -> None:
    """Actual SDK protocol/client, but an in-memory transport and no subprocess."""
    body_started, closing, release, closed = (asyncio.Event() for _ in range(4))
    received = asyncio.Queue()
    owner = []
    options_seen = []

    class Transport(claude_agent_sdk.Transport):
        def __init__(self, *, prompt: Any, options: Any) -> None:
            options_seen.append(options)
            self._process = _Process(1)

        async def connect(self) -> None:
            owner.append(asyncio.current_task())

        async def write(self, data: str) -> None:
            message = json.loads(data)
            if message['type'] == 'control_request':
                await received.put({'type': 'control_response', 'response': {
                    'subtype': 'success', 'request_id': message['request_id'], 'response': {},
                }})
            elif message['type'] == 'user':
                await received.put({'type': 'assistant', 'message': {
                    'id': 'fixture-message', 'model': 'fixture',
                    'content': [{'type': 'text', 'text': '公开进度'}],
                }})

        async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
            while True:
                yield await received.get()

        async def close(self) -> None:
            assert asyncio.current_task() is owner[0]
            closing.set()
            await release.wait()
            if cleanup_fails:
                raise OSError('private transport cleanup failure')
            self._process.returncode = 0
            closed.set()

        async def end_input(self) -> None:
            pass

        def is_ready(self) -> bool:
            return True

    async def emit(kind: str, _payload: dict[str, Any]) -> None:
        if kind == 'assistant_delta':
            body_started.set()
            if body_error:
                raise ValueError('event sink unavailable')
            await asyncio.Event().wait()

    monkeypatch.setattr(subprocess_cli, 'SubprocessCLITransport', Transport)
    ctx = context('discuss')
    task = asyncio.create_task(runtime.run(ctx, emit))
    try:
        await asyncio.wait_for(body_started.wait(), 1)
        if not body_error:
            task.cancel()
        await asyncio.wait_for(closing.wait(), 1)
        assert options_seen[0].session_store is not None
        assert options_seen[0].tools == []
        assert options_seen[0].mcp_servers == {}
        # A grace timeout must report unconfirmed while SDK close is pending.
        assert not await MindmapAiTaskManager._cancel_adapter_task(task, ctx.job_id, grace_seconds=0.01)
        assert not task.done()
        assert not closed.is_set()
        assert await runtime.cancel(ctx.job_id)
        release.set()
        if cleanup_fails:
            with pytest.raises(MindmapArtifactError) as error:
                await task
            assert error.value.code == 'AI_AGENT_CLEANUP_FAILED'
            assert 'private' not in str(error.value)
        else:
            with pytest.raises((asyncio.CancelledError, MindmapArtifactError)):
                await task
            assert closed.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


class _Process:
    """No OS process: exercise the installed SDK's actual close escalation."""

    def __init__(self, exit_after: int | None) -> None:
        self.returncode = None
        self.exit_after = exit_after
        self.waits = 0
        self.signals = []

    async def wait(self) -> int:
        self.waits += 1
        if self.exit_after is None or self.waits < self.exit_after:
            raise TimeoutError
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.signals.append('TERM')

    def kill(self) -> None:
        self.signals.append('KILL')


def _memory_subprocess(monkeypatch: pytest.MonkeyPatch, process: _Process, *, terminal: bool = False) -> list[Any]:
    transports = []
    received = asyncio.Queue()

    class MemorySubprocess(subprocess_cli.SubprocessCLITransport):
        async def connect(self) -> None:
            self._process = process
            self._ready = True
            transports.append(self)

        async def write(self, data: str) -> None:
            message = json.loads(data)
            if message['type'] == 'control_request':
                await received.put({'type': 'control_response', 'response': {
                    'subtype': 'success', 'request_id': message['request_id'], 'response': {},
                }})
            elif message['type'] == 'user':
                await received.put({'type': 'assistant', 'message': {
                    'id': 'fixture-message', 'model': 'fixture',
                    'content': [{'type': 'text', 'text': '公开进度'}],
                }})
                if terminal:
                    await received.put({
                        'type': 'result', 'subtype': 'success', 'duration_ms': 1,
                        'duration_api_ms': 1, 'is_error': False, 'num_turns': 1,
                        'session_id': 'fixture-session',
                    })

        async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
            while True:
                yield await received.get()

    monkeypatch.setattr(subprocess_cli, 'SubprocessCLITransport', MemorySubprocess)
    return transports


@pytest.mark.asyncio
@pytest.mark.parametrize('exit_after', [1, 2, 3, None])
async def test_real_sdk_silent_wait_failure_cannot_confirm_stopped(
    monkeypatch: pytest.MonkeyPatch, exit_after: int | None,
) -> None:
    process = _Process(exit_after)
    transports = _memory_subprocess(monkeypatch, process)
    started = asyncio.Event()

    async def run() -> None:
        stream = claude._claude_query(prompt='测试', options=claude_agent_sdk.ClaudeAgentOptions())
        async with claude.ClaudeMindmapAdapter._closing_stream(stream) as messages:
            async for _ in messages:
                started.set()
                await asyncio.Event().wait()

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(started.wait(), 1)
        if exit_after is None:
            with pytest.raises(AgentProcessCleanupError):
                await MindmapAiTaskManager._cancel_adapter_task(task, 'sdk-silent-cleanup', grace_seconds=1)
            assert process.returncode is None
            assert process.signals == ['TERM', 'KILL']
        else:
            assert await MindmapAiTaskManager._cancel_adapter_task(task, 'sdk-confirmed-cleanup', grace_seconds=1)
            assert process.returncode == 0
        assert transports[0]._process is None, 'SDK discards its handle even when wait fails'
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('exit_after', [1, None])
async def test_real_sdk_pre_query_connect_failure_closes_spawned_transport(
    monkeypatch: pytest.MonkeyPatch, exit_after: int | None,
) -> None:
    process = _Process(exit_after)
    transports = _memory_subprocess(monkeypatch, process)
    monkeypatch.setenv('CLAUDE_CODE_STREAM_CLOSE_TIMEOUT', 'invalid')
    expected = ValueError if exit_after is not None else AgentProcessCleanupError
    with pytest.raises(expected):
        async for _ in claude._claude_query(prompt='测试', options=claude_agent_sdk.ClaudeAgentOptions()):
            pass
    assert process.waits > 0, 'disconnect must close the transport even before Query exists'
    assert transports[0]._process is None
    assert process.returncode == (0 if exit_after is not None else None)


@pytest.mark.asyncio
async def test_real_sdk_result_does_not_hide_unconfirmed_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _Process(None)
    _memory_subprocess(monkeypatch, process, terminal=True)
    with pytest.raises(AgentProcessCleanupError):
        async for _ in claude._claude_query(prompt='测试', options=claude_agent_sdk.ClaudeAgentOptions()):
            pass
    assert process.returncode is None


@pytest.mark.asyncio
async def test_verified_client_preserves_real_sdk_session_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Never inspect or copy the developer's actual credentials in this test.
    monkeypatch.setattr(session_resume, '_copy_auth_files', lambda *_: None)
    process = _Process(1)
    transports = _memory_subprocess(monkeypatch, process)
    store = claude._ClaudeSessionStore(tmp_path / 'sessions', retention_days=30)
    session_id = '11111111-1111-4111-8111-111111111111'
    entries = [{'type': 'user', 'uuid': 'saved-message', 'message': {'role': 'user', 'content': '已保存'}}]
    await store.append({'project_key': 'old-project', 'session_id': session_id}, entries)
    options = claude_agent_sdk.ClaudeAgentOptions(
        cwd=tmp_path, resume=session_id, session_store=store,
    )
    stream = claude._claude_query(prompt='继续', options=options)
    try:
        await anext(stream)
        resumed_options = transports[0]._options
        assert resumed_options.resume == session_id
        config_dir = anyio.Path(resumed_options.env['CLAUDE_CONFIG_DIR'])
        transcripts = [path async for path in config_dir.glob('projects/**/*.jsonl')]
        assert len(transcripts) == 1
        assert [json.loads(line) for line in (await transcripts[0].read_text()).splitlines()] == entries
    finally:
        await stream.aclose()
    assert process.returncode == 0
    assert not await config_dir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('exit_after', [1, None])
async def test_cancel_during_sdk_internal_connect_cleanup_keeps_same_exit_barrier(
    runtime: claude.ClaudeMindmapAdapter, monkeypatch: pytest.MonkeyPatch, exit_after: int | None,
) -> None:
    process = _Process(exit_after)
    _memory_subprocess(monkeypatch, process)
    closing, release = asyncio.Event(), asyncio.Event()
    interrupted = False

    class BlockingClose(subprocess_cli.SubprocessCLITransport):
        async def close(self) -> None:
            nonlocal interrupted
            closing.set()
            try:
                await release.wait()
                await super().close()
            except asyncio.CancelledError:
                interrupted = True
                raise

    monkeypatch.setattr(subprocess_cli, 'SubprocessCLITransport', BlockingClose)
    monkeypatch.setenv('CLAUDE_CODE_STREAM_CLOSE_TIMEOUT', 'invalid')
    ctx = context('discuss')
    task = asyncio.create_task(runtime.run(ctx, AsyncMock()))
    try:
        await asyncio.wait_for(closing.wait(), 1)
        task.cancel()
        assert await runtime.cancel(ctx.job_id)
        assert not await MindmapAiTaskManager._cancel_adapter_task(task, ctx.job_id, grace_seconds=0.01)
        assert not task.done()
        assert not interrupted
        release.set()
        with pytest.raises(MindmapArtifactError) as error:
            await task
        assert (error.value.code == 'AI_AGENT_CLEANUP_FAILED') == (exit_after is None)
        assert not interrupted
        assert process.returncode == (0 if exit_after is not None else None)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
