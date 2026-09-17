"""AI 适配器共享的私有文件系统与进程清理工具。"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Literal, overload

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


async def terminate_process(process: asyncio.subprocess.Process | None) -> None:
    """限时终止进程组，并在温和终止失败后强制清理。"""
    if process is None or process.returncode is not None:
        return
    try:
        if os.name == 'posix' and process.pid is not None:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    except (asyncio.TimeoutError, ProcessLookupError):
        pass
    try:
        if os.name == 'posix' and process.pid is not None:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass
    with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=2)


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
