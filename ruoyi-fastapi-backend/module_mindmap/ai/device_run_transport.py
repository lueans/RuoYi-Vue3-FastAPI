"""Transport-independent execution of one authenticated, already-bound run.

The separate execution route and job dispatcher must validate device
ownership, local execution opt-in and the durable job lease before constructing
the session. This module then enforces its per-message authorizer as well.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, TypeVar

from module_mindmap.ai.adapters._fs_utils import AgentProcessCleanupError, _finish_cleanup
from module_mindmap.ai.device_run_session import DeviceRunFenced, DeviceRunSession, _encode
from module_mindmap.ai.document import MindmapArtifactError

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from module_mindmap.ai.adapters.base import AgentRunOutcome

_T = TypeVar('_T')


async def _bounded(operation: Awaitable[_T], timeout: float) -> _T:
    # Python 3.10 wait_for can swallow outer cancellation when the operation
    # completes in the same loop turn. wait() preserves it even if task.done().
    task = asyncio.ensure_future(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            raise asyncio.TimeoutError
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        async def settle() -> None:
            await asyncio.gather(task, return_exceptions=True)
        await _finish_cleanup(asyncio.create_task(settle()))


class DeviceRunConnection(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


async def _confirm_stop(session: DeviceRunSession, connection: DeviceRunConnection, grace: float) -> None:
    async def exchange() -> None:
        await connection.send(_encode(session.request_cancel()).decode())
        # Account for bounded messages already in flight when cancellation won.
        for _ in range(64):
            raw = await connection.recv()
            try:
                reply = await session.handle(raw)
            except DeviceRunFenced:
                continue
            await connection.send(reply.decode())
            if session.phase == 'stopped':
                return
            if session.phase == 'failed':
                if session.error and session.error.code != 'AI_AGENT_CLEANUP_FAILED':
                    return  # a failed run explicitly confirmed processStopped
                break
        raise AgentProcessCleanupError
    try:
        await _bounded(exchange(), grace)
    except Exception as exc:
        raise AgentProcessCleanupError from exc


async def run_device_session(
    session: DeviceRunSession, connection: DeviceRunConnection, *,
    timeout: float = 900, idle_timeout: float = 15, cancel_grace: float = 5,
) -> AgentRunOutcome:
    """A validated, stopped terminal result survives a lost final ACK."""
    offered = False
    try:
        offer = await session.offer()
        offered = True  # a failed send may still have reached the peer
        await _bounded(connection.send(_encode(offer).decode()), idle_timeout)
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise MindmapArtifactError('设备执行超时', code='AI_TIMEOUT')
            try:
                raw = await _bounded(connection.recv(), min(remaining, idle_timeout))
            except asyncio.TimeoutError as exc:
                raise MindmapArtifactError('设备心跳或执行超时', code='AI_TIMEOUT') from exc
            reply = await _bounded(session.handle(raw), max(0, deadline - asyncio.get_running_loop().time()))
            try:
                await _bounded(connection.send(reply.decode()), idle_timeout)
            except Exception:
                # The server already owns the validated result and the device
                # explicitly confirmed process exit. Losing this ACK must not
                # turn a completed edit into a retryable transport failure.
                if session.phase not in {'completed', 'failed'}:
                    raise
            if session.phase == 'completed' and session.result is not None:
                return session.result
            if session.phase == 'failed':
                raise session.error or MindmapArtifactError('设备执行失败', code='AI_AGENT_UNAVAILABLE')
    except BaseException:
        if offered and session.phase not in {'completed', 'stopped', 'failed'}:
            session.request_cancel()
            # Waiting for remote termination has the same cancellation shield
            # as local process groups; repeated UI clicks cannot abandon it.
            await _finish_cleanup(asyncio.create_task(_confirm_stop(session, connection, cancel_grace)))
        raise
    finally:
        await session.close()
