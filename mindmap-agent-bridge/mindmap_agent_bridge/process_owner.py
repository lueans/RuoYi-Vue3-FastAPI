"""Live POSIX ownership; optional durable registration through run_recovery."""

import asyncio
import contextlib
import os
import signal
import sys

import psutil

from .execution import RunCleanupError, _bounded

TERM_GRACE = 1.5
KILL_GRACE = 1.5


async def shield_cleanup(task):
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    result = task.result()
    if interrupted:
        raise asyncio.CancelledError
    return result


class OwnedProcess:
    def __init__(self):
        self.process = None
        self.created_at = None
        self._cleanup = None
        self._started = False

    async def start(self, argv, *, env, cwd, limit=2 * 1024 * 1024, workspace=None):
        if self._started or os.name != 'posix':
            raise RunCleanupError
        self._started = True
        if workspace is not None:
            from .run_recovery import BOOTSTRAP
            record_name = workspace.prepare_launch()
            argv = [sys.executable, '-I', str(BOOTSTRAP), str(workspace.path), record_name, *argv]

        async def spawn():
            self.process = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, env=env, start_new_session=True, limit=limit,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                self.created_at = psutil.Process(self.process.pid).create_time()
            except psutil.NoSuchProcess:
                pass  # a short-lived leader may have left live children
            except psutil.Error:
                # Do not release a just-spawned group without ownership proof.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await _bounded(self.process.wait(), KILL_GRACE)
                raise RunCleanupError from None
            return self.process

        task = asyncio.create_task(spawn())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            async def cleanup_spawn():
                try:
                    await task
                finally:
                    if self.process is not None:
                        await self.stop()
            await shield_cleanup(asyncio.create_task(cleanup_spawn()))
            raise

    def _alive(self):
        pid = self.process.pid
        try:
            current = psutil.Process(pid).create_time()
            if self.created_at is None:
                raise RunCleanupError
            if current != self.created_at:
                return False  # never signal a recycled leader
        except psutil.NoSuchProcess:
            pass
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        for member in psutil.process_iter(['pid', 'status']):
            try:
                if os.getpgid(member.pid) == pid and member.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                    return True
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
        return False

    async def _stop(self):
        try:
            if self.process.pid == os.getpgrp():
                raise RunCleanupError
            for sig, grace in ((signal.SIGTERM, TERM_GRACE), (signal.SIGKILL, KILL_GRACE)):
                if not self._alive():
                    break
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, sig)
                deadline = asyncio.get_running_loop().time() + grace
                while self._alive() and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.03)
                if not self._alive():
                    break
            if self._alive():
                raise RunCleanupError
            await _bounded(self.process.wait(), 0.2)
        except (OSError, psutil.Error, asyncio.TimeoutError):
            raise RunCleanupError from None

    async def stop(self):
        if self.process is not None:
            if self._cleanup is None:
                self._cleanup = asyncio.create_task(self._stop())
            await shield_cleanup(self._cleanup)
