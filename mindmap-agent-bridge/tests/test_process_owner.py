"""Real disposable subprocesses; never target existing user/Agent processes."""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip('psutil')

from mindmap_agent_bridge import process_owner
from mindmap_agent_bridge.execution import RunCleanupError


@pytest.mark.asyncio
async def test_cancel_during_spawn_still_waits_for_and_cleans_real_group(monkeypatch, tmp_path):
    owner = process_owner.OwnedProcess()
    spawned, release = asyncio.Event(), asyncio.Event()
    original = asyncio.create_subprocess_exec
    process = None
    async def delayed_spawn(*args, **kwargs):
        nonlocal process
        process = await original(*args, **kwargs)
        spawned.set()
        await release.wait()
        return process
    monkeypatch.setattr(process_owner.asyncio, 'create_subprocess_exec', delayed_spawn)
    task = asyncio.create_task(owner.start([sys.executable, '-c', 'import time; time.sleep(20)'], env={}, cwd=tmp_path))
    try:
        await asyncio.wait_for(spawned.wait(), 1)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert owner.process is process and process.returncode is not None and not owner._alive()
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await owner.stop()


@pytest.mark.asyncio
async def test_repeated_cancel_cannot_interrupt_owned_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(process_owner, 'TERM_GRACE', 0.08)
    owner = process_owner.OwnedProcess()
    process = await owner.start([
        sys.executable, '-c',
        'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready",flush=True); time.sleep(20)',
    ], env={}, cwd=tmp_path)
    assert await process.stdout.readline() == b'ready\n'
    entered = asyncio.Event()
    original_stop = owner._stop
    async def observed_stop():
        entered.set()
        await original_stop()
    monkeypatch.setattr(owner, '_stop', observed_stop)
    task = asyncio.create_task(owner.stop())
    await entered.wait()
    task.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    await owner.stop()
    assert not owner._alive()


def test_recycled_or_unproven_leader_never_authorizes_a_signal(monkeypatch):
    owner = process_owner.OwnedProcess()
    owner.process = SimpleNamespace(pid=12345)
    owner.created_at = 1.0
    monkeypatch.setattr(process_owner.psutil, 'Process', lambda _pid: SimpleNamespace(create_time=lambda: 2.0))
    signals = []
    monkeypatch.setattr(process_owner.os, 'killpg', lambda *args: signals.append(args))
    assert owner._alive() is False
    owner.created_at = None
    with pytest.raises(RunCleanupError):
        owner._alive()
    assert signals == []


@pytest.mark.asyncio
async def test_stop_refuses_own_bridge_process_group():
    owner = process_owner.OwnedProcess()
    owner.process = SimpleNamespace(pid=os.getpgrp(), wait=AsyncMock())
    with pytest.raises(RunCleanupError):
        await owner.stop()
    owner.process.wait.assert_not_awaited()
