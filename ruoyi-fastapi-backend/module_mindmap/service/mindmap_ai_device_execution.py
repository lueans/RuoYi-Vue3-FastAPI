"""Actual job admission/authorization for user-device execution.

No credentials, lease tokens or server filesystem paths cross this boundary.
The job manager injects its lease-check callback, never request JSON callbacks.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import AsyncSessionLocal
from exceptions.exception import ServiceException
from module_admin.entity.do.user_do import SysUser
from module_mindmap.ai.adapters._fs_utils import _finish_cleanup
from module_mindmap.ai.adapters.base import AgentEventHandler, AgentRunContext, AgentRunOutcome
from module_mindmap.ai.adapters.device import DEVICE_AGENT_KEY
from module_mindmap.ai.device_dispatch import DeviceDispatch, DispatchedRunConnection
from module_mindmap.ai.device_run_session import DeviceRunBinding, DeviceRunSession
from module_mindmap.ai.device_run_transport import _bounded, run_device_session
from module_mindmap.ai.device_runtime import DEVICE_AGENT_KEYS, device_runtime_enabled, execution_agents
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.entity.do.mindmap_ai_device_do import MindmapAiDevice
from module_mindmap.entity.vo.mindmap_ai_vo import (
    MindmapAiJobCreateModel,
    MindmapAiJobRetryModel,
    MindmapAiMessageModel,
)
from module_mindmap.service.mindmap_ai_mutation_gateway import MindmapAiMutationGateway


async def device_is_owned(db: AsyncSession, device_id: str, user_id: int) -> bool:
    return (await db.execute(select(MindmapAiDevice.id).join(
        SysUser, SysUser.user_id == MindmapAiDevice.user_id,
    ).where(
        MindmapAiDevice.id == device_id, MindmapAiDevice.user_id == user_id,
        MindmapAiDevice.status == 'active', MindmapAiDevice.credential_expires_time > datetime.now(),
        SysUser.status == '0', SysUser.del_flag == '0',
    ))).scalar_one_or_none() is not None


def merge_device_selection(
    payload: dict[str, Any], model: MindmapAiMessageModel | MindmapAiJobRetryModel, agent_key: str,
    *, previous: MindmapAiJobCreateModel | None = None,
) -> None:
    """Keep same-device continuation, but never silently cross runtime kinds."""
    if agent_key not in DEVICE_AGENT_KEYS:
        if model.device_id is not None:
            raise ServiceException(message='仅“我的电脑”Agent 支持选择本机设备')
        payload.pop('deviceId', None)
    elif model.device_id is not None:
        payload['deviceId'] = model.device_id
    elif previous is not None:
        # Artifact ancestry selects CONTENT, not a computer. Continue on the
        # parent turn's device, or require explicit selection when switching in.
        if previous.agent_key == agent_key and previous.device_id:
            payload['deviceId'] = previous.device_id
        else:
            payload.pop('deviceId', None)


async def validate_device_selection(
    db: AsyncSession, request_model: MindmapAiJobCreateModel, user_id: int, redis: Redis | None,
) -> None:
    device_id = request_model.device_id
    if request_model.agent_key not in DEVICE_AGENT_KEYS:
        if device_id is not None:
            raise ServiceException(message='当前 Agent 不支持本机设备参数')
        return
    runtime = DEVICE_AGENT_KEYS[request_model.agent_key]
    if not device_runtime_enabled(runtime):
        raise ServiceException(message='管理员尚未启用本机执行')
    if not device_id or not await device_is_owned(db, device_id, user_id):
        raise ServiceException(message='请选择本人有效的已配对设备')
    state = await DeviceDispatch(redis, device_id).state()
    if (state.get('user') != str(user_id) or runtime not in execution_agents(state)
            or state.get('phase') not in {'available', 'busy'}):
        raise ServiceException(message=f'请在所选电脑显式启用 {runtime.title()} 执行连接')


async def execute_device_job(
    context: AgentRunContext, emit: AgentEventHandler, *, redis: Redis | None,
    device_id: str, epoch: int, owns_lease: Callable[[], Awaitable[bool]],
    adapter_agent_key: str = DEVICE_AGENT_KEY,
) -> AgentRunOutcome:
    runtime = DEVICE_AGENT_KEYS.get(adapter_agent_key)
    if not runtime or not device_runtime_enabled(runtime):
        raise MindmapArtifactError('本机 Agent 未启用', code='AI_AGENT_UNAVAILABLE')
    if type(epoch) is not int or epoch < 1 or await owns_lease() is not True:
        raise MindmapArtifactError('设备任务缺少有效执行租约', code='AI_SANDBOX_VIOLATION')
    # Reclaiming a crashed worker does NOT authorize another paid model run.
    if epoch != 1:
        raise MindmapArtifactError('任务工作进程曾中断，请确认本机 CLI 已停止后手动重试', code='AI_AGENT_CLEANUP_FAILED')
    dispatch = DeviceDispatch(redis, device_id)

    async def authorized_job() -> bool:
        if not (device_runtime_enabled(runtime) and await owns_lease() is True):
            return False
        async with AsyncSessionLocal() as db:
            job = await MindmapAiDao.get_job(db, context.job_id, context.user_id)
            if (job is None or job.agent_key != adapter_agent_key or job.execution_epoch != epoch
                    or job.status != 'running' or json.loads(job.request_json).get('deviceId') != device_id):
                return False
            session = await MindmapAiDao.get_session(db, job.session_id, context.user_id)
            if (session is None or session.status != 'active'
                    or (session.expires_time is not None and session.expires_time <= datetime.now())
                    or not await device_is_owned(db, device_id, context.user_id)):
                return False
            # A permission removed after admission must also fence cached
            # source projections, public summaries and read-only tools.
            if job.source_mindmap_id:
                await MindmapAiMutationGateway.read_document(db, job.source_mindmap_id, context.user_id)
        return True

    deadline = asyncio.get_running_loop().time() + 10
    while True:
        if not await authorized_job():
            raise MindmapArtifactError('设备任务授权已失效', code='AI_SANDBOX_VIOLATION')
        try:
            binding = await dispatch.reserve(job_id=context.job_id, user_id=context.user_id, epoch=epoch, agent_key=runtime)
            break
        except MindmapArtifactError:
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(0.25)

    async def authorize(bound: DeviceRunBinding) -> bool:
        return bound == binding and await dispatch.owns(bound) and await authorized_job()

    connection = DispatchedRunConnection(dispatch, binding)
    session = DeviceRunSession(binding, context, emit, authorize, adapter_agent_key=adapter_agent_key)
    failure: BaseException | None = None
    try:
        return await run_device_session(session, connection, timeout=context.metadata['timeoutSeconds'])
    except BaseException as error:
        failure = error
        raise
    finally:
        # Best effort relay close; does not assert local-process termination.
        try:
            await _finish_cleanup(asyncio.create_task(_bounded(connection.finish(), 2)))
        except asyncio.CancelledError:
            if failure is None:
                raise
            # A repeated cancel cannot replace an uncertain process-stop
            # failure with an apparently successful cancellation.
        except Exception:
            pass
