"""AI 适配器共享的私有文件系统与进程清理工具。"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, overload

import psutil

from config.env import MindmapAiConfig
from module_mindmap.ai.document import MindmapArtifactError

if TYPE_CHECKING:
    from module_mindmap.ai.adapters.base import AgentRunContext


def ensure_private_directory(label: str, path: Path) -> Path:
    """创建私有目录，并拒绝路径中的符号链接或非目录目标。"""
    absolute_path = path.absolute()
    current = Path(absolute_path.anchor)
    for part in absolute_path.parts[1:]:
        current = current.joinpath(part)
        try:
            current_status = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise MindmapArtifactError(
                f'{label} 会话存储不可用', code='AI_AGENT_UNAVAILABLE',
            ) from exc
        if stat.S_ISLNK(current_status.st_mode):
            raise MindmapArtifactError(
                f'{label} 会话存储不安全', code='AI_AGENT_UNAVAILABLE',
            )
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory_status = path.lstat()
    except OSError as exc:
        raise MindmapArtifactError(
            f'{label} 会话存储不可用', code='AI_AGENT_UNAVAILABLE',
        ) from exc
    if stat.S_ISLNK(directory_status.st_mode) or not stat.S_ISDIR(
        directory_status.st_mode,
    ):
        raise MindmapArtifactError(
            f'{label} 会话存储不安全', code='AI_AGENT_UNAVAILABLE',
        )
    try:
        path.chmod(0o700)
    except OSError as exc:
        raise MindmapArtifactError(
            f'{label} 会话存储权限设置失败', code='AI_AGENT_UNAVAILABLE',
        ) from exc
    return path


def session_retention_days(context: AgentRunContext) -> int:
    """解析并限制适配器会话快照的保留天数。"""
    raw_value = context.metadata.get(
        'retentionDays', MindmapAiConfig.mindmap_ai_artifact_retention_days,
    )
    if isinstance(raw_value, bool):
        return MindmapAiConfig.mindmap_ai_artifact_retention_days
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return MindmapAiConfig.mindmap_ai_artifact_retention_days
    return max(1, min(value, 365))


PROCESS_TERM_GRACE_SECONDS = 2.0
PROCESS_KILL_GRACE_SECONDS = 2.0
PROCESS_POLL_SECONDS = 0.05


class AgentProcessCleanupError(MindmapArtifactError):
    def __init__(self) -> None:
        super().__init__(
            'Agent 进程清理未确认完成，请先检查运行主机上的 CLI；本轮结果已拒绝',
            code='AI_AGENT_CLEANUP_FAILED',
        )


@dataclass
class _OwnedGroup:
    pid: int
    created_at: float | None
    cleanup: asyncio.Task | None = None


async def _finish_cleanup(task: asyncio.Task) -> None:
    """Repeated cancellation must not interrupt an already-started group kill."""
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:  # noqa: PERF203 - repeated cancellation must not abandon cleanup
            interrupted = True
    task.result()
    if interrupted:
        raise asyncio.CancelledError


async def spawn_owned_process(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
    """Record the group at spawn; cancellation during spawn cannot orphan it.

    This is an in-process ownership record, not crash recovery or an OS sandbox.
    Only callers providing explicit argv/env and a private cwd use this helper.
    """
    if os.name == 'posix' and kwargs.get('start_new_session') is not True:
        raise ValueError('Owned Agent processes must start a new session')

    async def spawn() -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(*args, **kwargs)
        if (os.name == 'posix' and isinstance(process, asyncio.subprocess.Process)
                and type(process.pid) is int and process.pid > 1):
            created_at = None
            try:
                created_at = psutil.Process(process.pid).create_time()
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                # The child was just returned by the OS; no unverified handle
                # escapes if recording its identity fails before ownership.
                try:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await asyncio.wait_for(process.wait(), PROCESS_KILL_GRACE_SECONDS)
                except (OSError, asyncio.TimeoutError) as cleanup_error:
                    raise AgentProcessCleanupError from cleanup_error
                raise AgentProcessCleanupError from exc
            # Keep ownership on the handle itself. A global weak map whose
            # cleanup exception refers back to its handle would leak frames.
            process._mindmap_owned_group = _OwnedGroup(process.pid, created_at)
        return process

    task = asyncio.create_task(spawn())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        async def stop_after_spawn() -> None:
            try:
                process = await task
            except AgentProcessCleanupError:
                raise
            except Exception:
                return
            await terminate_process(process)
        await _finish_cleanup(asyncio.create_task(stop_after_spawn()))
        raise


def _group_has_running_members(group: _OwnedGroup) -> bool:
    """Ignore reaped/zombie members; reject a recycled group-leader identity."""
    try:
        root = psutil.Process(group.pid)
        if group.created_at is not None and root.create_time() != group.created_at:
            return False
    except psutil.NoSuchProcess:
        pass  # Leader gone is not proof its children have exited.
    try:
        os.killpg(group.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Signal-0 denial is not proof a runnable member remains. Inspect the
        # group; an actual TERM/KILL permission failure still fails closed.
        pass
    for process in psutil.process_iter(['pid', 'status']):
        try:
            if os.getpgid(process.pid) == group.pid and process.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                return True
        except (ProcessLookupError, psutil.NoSuchProcess):  # noqa: PERF203 - process exits race each OS query
            continue
    return False


async def _wait_group_exit(group: _OwnedGroup, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while _group_has_running_members(group):
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(PROCESS_POLL_SECONDS)
    return True


async def _terminate_owned_group(process: asyncio.subprocess.Process, group: _OwnedGroup) -> None:
    deadline = asyncio.get_running_loop().time() + PROCESS_TERM_GRACE_SECONDS + PROCESS_KILL_GRACE_SECONDS
    try:
        if group.pid == os.getpgrp():
            raise ValueError('Refusing to signal the server process group')
        for sig, grace in ((signal.SIGTERM, PROCESS_TERM_GRACE_SECONDS), (signal.SIGKILL, PROCESS_KILL_GRACE_SECONDS)):
            if not _group_has_running_members(group):
                break
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group.pid, sig)
            if await _wait_group_exit(group, grace):
                break
        else:
            raise OSError('Agent process group did not stop')
        await asyncio.wait_for(process.wait(), max(PROCESS_POLL_SECONDS, deadline - asyncio.get_running_loop().time()))
    except (OSError, ValueError, psutil.Error, asyncio.TimeoutError) as exc:
        raise AgentProcessCleanupError from exc


async def _terminate_single_process(process: asyncio.subprocess.Process) -> None:
    # SDK/test processes not created by spawn_owned_process never authorize
    # signalling an arbitrary process group. Windows remains direct-child only.
    if process.returncode is not None:
        return
    for stop in (process.terminate, process.kill):
        with contextlib.suppress(ProcessLookupError):
            stop()
        try:
            await asyncio.wait_for(process.wait(), PROCESS_TERM_GRACE_SECONDS)
            return
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
    raise AgentProcessCleanupError


async def terminate_process(process: asyncio.subprocess.Process | None) -> None:
    """Wait for the *owned group*, not merely the exited CLI parent."""
    if process is None:
        return
    group = getattr(process, '_mindmap_owned_group', None) if isinstance(process, asyncio.subprocess.Process) else None
    if group is not None:
        if group.cleanup is None:
            group.cleanup = asyncio.create_task(_terminate_owned_group(process, group))
        await _finish_cleanup(group.cleanup)
    else:
        await _finish_cleanup(asyncio.create_task(_terminate_single_process(process)))


@overload
def read_bounded_regular_file(
    path: Path,
    *,
    max_bytes: int,
    suppress_errors: Literal[False] = False,
) -> bytes: ...


@overload
def read_bounded_regular_file(
    path: Path,
    *,
    max_bytes: int,
    suppress_errors: Literal[True],
) -> bytes | None: ...


def read_bounded_regular_file(
    path: Path,
    *,
    max_bytes: int,
    suppress_errors: bool = False,
) -> bytes | None:
    """不跟随末级符号链接地读取大小受限的普通文件。"""
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, 'O_CLOEXEC', 0)
            | getattr(os, 'O_NOFOLLOW', 0)
            | getattr(os, 'O_NONBLOCK', 0),
        )
    except (OSError, ValueError):
        if suppress_errors:
            return None
        raise

    try:
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode) or file_status.st_size > max_bytes:
            if suppress_errors:
                return None
            raise ValueError
        with os.fdopen(descriptor, 'rb', closefd=True) as stream:
            descriptor = -1
            value = stream.read(max_bytes + 1)
    except OSError:
        if suppress_errors:
            return None
        raise
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                if not suppress_errors:
                    raise

    if len(value) > max_bytes:
        if suppress_errors:
            return None
        raise ValueError
    return value


def unlink_snapshot_file(label: str, path: Path) -> bool:
    """仅删除普通文件或符号链接形式的快照目录项。"""
    try:
        file_status = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise MindmapArtifactError(
            f'{label} 会话快照清理失败', code='AI_AGENT_UNAVAILABLE',
        ) from exc
    if not (stat.S_ISREG(file_status.st_mode) or stat.S_ISLNK(file_status.st_mode)):
        raise MindmapArtifactError(
            f'{label} 会话快照不安全', code='AI_AGENT_UNAVAILABLE',
        )
    try:
        path.unlink()
    except OSError as exc:
        raise MindmapArtifactError(
            f'{label} 会话快照清理失败', code='AI_AGENT_UNAVAILABLE',
        ) from exc
    return True
