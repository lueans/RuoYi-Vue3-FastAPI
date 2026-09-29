"""Owner APIs and separately authenticated outbound companion transport."""

import asyncio
import json
import time
from collections import deque
from typing import Annotated

from fastapi import HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.rate_limit_annotation import ApiRateLimit, ApiRateLimitPreset
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.router import APIRouterPro
from config.database import AsyncSessionLocal
from config.env import MindmapAiConfig
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.ai.device_dispatch import FINISHED, DeviceDispatch
from module_mindmap.ai.device_run_session import MAX_DEVICE_RUN_FRAME_BYTES
from module_mindmap.ai.device_run_transport import _bounded
from module_mindmap.ai.device_runtime import device_runtime_enabled, execution_agents, parse_execution_hello
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.entity.vo.mindmap_ai_device_vo import DeviceEnrollment, DeviceFrame, DeviceId, DevicePairRequest
from module_mindmap.service.mindmap_ai_device_service import MindmapAiDeviceService
from utils.response_util import ResponseUtil

MAX_FRAME_BYTES = 16_384
FRAME_TIMEOUT_SECONDS = 15
TRAFFIC_WINDOW_SECONDS = 10
MAX_FRAMES_PER_WINDOW = 12
MAX_EXECUTION_FRAMES_PER_WINDOW = 1_000

mindmap_ai_device_controller = APIRouterPro(
    prefix='/mindmap/ai/devices', tags=['脑图 AI 用户设备'], order_num=21,
    dependencies=[PreAuthDependency(), UserInterfaceAuthDependency('mindmap:ai:use')],
)
mindmap_ai_bridge_controller = APIRouterPro(
    prefix='/mindmap/ai/device-bridge', tags=['脑图 AI 本地桥接'], order_num=21,
)


def require_bridge_enabled() -> None:
    if not MindmapAiConfig.mindmap_ai_device_bridge_enabled:
        raise HTTPException(503, '管理员尚未启用本地设备桥接')


@mindmap_ai_device_controller.get('')
async def list_devices(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    enabled = MindmapAiConfig.mindmap_ai_device_bridge_enabled
    devices = await MindmapAiDeviceService.list_devices(db, current_user.user.user_id) if enabled else []
    if enabled and MindmapAiConfig.mindmap_ai_device_execution_enabled:
        for device in devices:
            if device['status'] != 'online':
                continue
            try:
                state = await DeviceDispatch(request.app.state.redis, device['deviceId']).state()
                agents = [agent for agent in execution_agents(state) if device_runtime_enabled(agent)]
                if state.get('user') == str(current_user.user.user_id) and agents:
                    device['executionAvailable'] = state.get('phase') == 'available'
                    device['executionBusy'] = state.get('phase') == 'busy'
                    device['executionAgents'] = agents
            except Exception:
                pass  # Redis failure must never advertise execution readiness.
    return ResponseUtil.success(data={
        'enabled': enabled,
        'devices': devices,
    })


@mindmap_ai_device_controller.post('/pairing')
@ApiRateLimit(namespace='mindmap:device:pair', preset=ApiRateLimitPreset.USER_SECURITY_MUTATION)
async def create_pairing(
    request: Request,
    model: DevicePairRequest,
    db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    require_bridge_enabled()
    result = await MindmapAiDeviceService.create_pairing(db, current_user.user.user_id, model.name)
    response = ResponseUtil.success(data=result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@mindmap_ai_device_controller.post('/{device_id}/scan')
@ApiRateLimit(namespace='mindmap:device:scan', preset=ApiRateLimitPreset.USER_RESOURCE_EXECUTION)
async def scan_device(
    request: Request,
    device_id: DeviceId,
    db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    require_bridge_enabled()
    await MindmapAiDeviceService.request_scan(db, current_user.user.user_id, device_id)
    return ResponseUtil.success(msg='扫描请求已发送')


@mindmap_ai_device_controller.delete('/{device_id}')
@ApiRateLimit(namespace='mindmap:device:revoke', preset=ApiRateLimitPreset.USER_SECURITY_MUTATION)
async def revoke_device(
    request: Request,
    device_id: DeviceId,
    db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    require_bridge_enabled()
    await MindmapAiDeviceService.revoke(db, current_user.user.user_id, device_id)
    return ResponseUtil.success(msg='设备授权已撤销')


@mindmap_ai_bridge_controller.post('/enroll')
@ApiRateLimit(namespace='mindmap:device:enroll', preset=ApiRateLimitPreset.ANON_AUTH_REGISTER)
async def enroll_device(
    request: Request,
    db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    require_bridge_enabled()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FRAME_BYTES:
            raise HTTPException(413, '配对请求过大')
    try:
        model = DeviceEnrollment.model_validate_json(bytes(body))
    except ValidationError:
        # Never allow FastAPI's validation response to echo a submitted secret.
        raise HTTPException(400, '配对请求格式无效') from None
    result = await MindmapAiDeviceService.enroll(db, model)
    response = ResponseUtil.success(data=result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@mindmap_ai_bridge_controller.websocket('/connect/{device_id}')
async def connect_device(websocket: WebSocket, device_id: DeviceId) -> None:  # noqa: PLR0912
    if not MindmapAiConfig.mindmap_ai_device_bridge_enabled:
        await websocket.close(code=4403)
        return
    # Desktop clients use an Authorization header, never a query parameter or
    # user login cookie. Browser origins cannot use this machine-only channel.
    authorization = websocket.headers.get('authorization', '')
    if websocket.headers.get('origin') or not authorization.startswith('Bearer '):
        await websocket.close(code=4401)
        return
    credential = authorization[len('Bearer '):]
    connection_id = None
    try:
        async with AsyncSessionLocal() as db:
            connection_id = await MindmapAiDeviceService.connect(db, device_id, credential)
        await websocket.accept()
        await websocket.send_json({'type': 'welcome', 'protocolVersion': 1, 'capabilities': ['discover'],
                                   'executionAvailable': False})
        received: deque[float] = deque()
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=FRAME_TIMEOUT_SECONDS)
            if len(raw.encode('utf-8')) > MAX_FRAME_BYTES:
                await websocket.close(code=1009)
                return
            now = time.monotonic()
            while received and received[0] <= now - TRAFFIC_WINDOW_SECONDS:
                received.popleft()
            if len(received) >= MAX_FRAMES_PER_WINDOW:
                await websocket.close(code=4429)
                return
            received.append(now)
            frame = DeviceFrame.model_validate_json(raw)
            async with AsyncSessionLocal() as db:
                response = await MindmapAiDeviceService.receive(db, device_id, credential, connection_id, frame)
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
    except HTTPException as error:
        if (connection_id is None and error.status_code == status.HTTP_409_CONFLICT
                and error.headers and 'Retry-After' in error.headers):
            # Closing before accept always becomes HTTP 403. Keep a live lease
            # distinguishable from invalid credentials so reconnect can wait
            # briefly for an orphaned lease without taking over a live socket.
            await websocket.send_denial_response(Response(status_code=409, headers=error.headers))
        else:
            code = {status.HTTP_409_CONFLICT: 4409, status.HTTP_401_UNAUTHORIZED: 4401}.get(error.status_code, 4400)
            await websocket.close(code=code)
    except (ValidationError, ValueError, json.JSONDecodeError):
        await websocket.close(code=4400)
    except asyncio.TimeoutError:
        await websocket.close(code=4408)
    except Exception:
        # No raw WebSocket frame, token or provider state enters logs/responses.
        await websocket.close(code=1011)
    finally:
        if connection_id:
            try:
                async with AsyncSessionLocal() as db:
                    await MindmapAiDeviceService.disconnect(db, device_id, connection_id)
            except Exception:
                # last_seen TTL still makes this device offline if SQL is down.
                pass


@mindmap_ai_bridge_controller.websocket('/execute/{device_id}')
async def execute_device(websocket: WebSocket, device_id: DeviceId) -> None:  # noqa: PLR0912, PLR0915
    """One opt-in socket, one run. Discovery credentials alone do not enable it."""
    if not (MindmapAiConfig.mindmap_ai_device_bridge_enabled
            and MindmapAiConfig.mindmap_ai_device_execution_enabled):
        await websocket.close(code=4403)
        return
    authorization = websocket.headers.get('authorization', '')
    if websocket.headers.get('origin') or not authorization.startswith('Bearer '):
        await websocket.close(code=4401)
        return
    credential = authorization[len('Bearer '):]
    connection_id = None
    tasks = []
    dispatch = None
    agents = ()

    async def authenticate() -> int:
        if not (MindmapAiConfig.mindmap_ai_device_bridge_enabled
                and MindmapAiConfig.mindmap_ai_device_execution_enabled) or any(not device_runtime_enabled(agent) for agent in agents):
            raise HTTPException(403, '设备执行已停用')
        async with AsyncSessionLocal() as db:
            device = await MindmapAiDeviceService.authenticate(db, device_id, credential)
            return device.user_id

    try:
        user_id = await authenticate()
        await websocket.accept()
        raw = await _bounded(websocket.receive_text(), 10)
        if len(raw.encode()) > MAX_FRAME_BYTES:
            raise ValueError
        hello = json.loads(raw)
        agents, welcome = parse_execution_hello(hello)
        if any(not device_runtime_enabled(agent) for agent in agents):
            raise ValueError
        dispatch = DeviceDispatch(websocket.app.state.redis, device_id)
        connection_id = await dispatch.open(user_id, agents)
        await websocket.send_json(welcome)

        async def receive() -> None:
            received = deque()
            while True:
                raw = await _bounded(websocket.receive_text(), FRAME_TIMEOUT_SECONDS)
                if len(raw.encode()) > MAX_DEVICE_RUN_FRAME_BYTES:
                    raise ValueError
                now = time.monotonic()
                while received and received[0] <= now - TRAFFIC_WINDOW_SECONDS:
                    received.popleft()
                if len(received) >= MAX_EXECUTION_FRAMES_PER_WINDOW:
                    raise HTTPException(429, '设备消息过于频繁')
                received.append(now)
                if await authenticate() != user_id:
                    raise HTTPException(401, '设备账号已改变')
                await dispatch.touch(connection_id)
                value = json.loads(raw)
                if value == {'type': 'idle_heartbeat', 'protocolVersion': 1} and type(value['protocolVersion']) is int:
                    continue
                await dispatch.push(connection_id, 'in', raw)

        async def send() -> None:
            while True:
                raw = await dispatch.pop(connection_id, 'out')
                # Revoke/disable is also checked before releasing prompt/tool
                # result data, not just when a device next sends a heartbeat.
                if await authenticate() != user_id:
                    raise HTTPException(401, '设备账号已改变')
                if (await dispatch.state()).get('connection') != connection_id:
                    raise HTTPException(409, '设备连接已失效')
                if raw == FINISHED:
                    await dispatch.close(connection_id)
                    await websocket.send_text(raw)
                    return
                await _bounded(websocket.send_text(raw), FRAME_TIMEOUT_SECONDS)

        tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        await websocket.close(code=1000)
    except WebSocketDisconnect:
        pass
    except HTTPException as error:
        await websocket.close(code={401: 4401, 403: 4403, 409: 4409, 429: 4429}.get(error.status_code, 4400))
    except MindmapArtifactError:
        await websocket.close(code=4409)
    except (ValueError, TypeError, KeyError):
        await websocket.close(code=4400)
    except asyncio.TimeoutError:
        await websocket.close(code=4408)
    except Exception:
        await websocket.close(code=1011)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if dispatch is not None and connection_id:
            try:
                await dispatch.close(connection_id)
            except Exception:
                pass  # TTL fences the lost connection; never reoffer its run.
