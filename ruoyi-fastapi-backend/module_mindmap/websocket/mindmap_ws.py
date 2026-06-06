"""脑图 WebSocket 端点"""
import asyncio
import base64
import time

from fastapi import WebSocket, WebSocketDisconnect

from config.database import AsyncSessionLocal
from module_mindmap.websocket.room_manager import room_manager
from module_mindmap.websocket.ws_auth import validate_ws_token
from module_mindmap.websocket.yjs_doc import YjsDocManager
from utils.log_util import logger

# 认证超时：连接后 10 秒内必须发送 auth 消息
AUTH_TIMEOUT_SECONDS = 10
# Yjs 状态持久化间隔：每 30 秒最多持久化一次
PERSIST_INTERVAL_SECONDS = 30


async def mindmap_websocket_endpoint(websocket: WebSocket, mindmap_id: int) -> None:  # noqa: PLR0912, PLR0915
    """脑图实时协作 WebSocket 端点"""
    await websocket.accept()

    # ── 连接后认证（不通过 URL 传递 token） ──
    try:
        auth_msg = await asyncio.wait_for(
            websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS
        )
        if auth_msg.get('type') != 'auth' or not auth_msg.get('token'):
            await websocket.send_json({'type': 'auth_error', 'message': '请发送认证消息'})
            await websocket.close(code=4001)
            return

        # 从 app.state 获取 redis
        redis = websocket.app.state.redis
        user_info = await validate_ws_token(auth_msg['token'], redis)
    except asyncio.TimeoutError:
        await websocket.send_json({'type': 'auth_error', 'message': '认证超时'})
        await websocket.close(code=4001)
        return
    except (ValueError, Exception) as e:
        await websocket.send_json({'type': 'auth_error', 'message': str(e)})
        await websocket.close(code=4001)
        return

    # 认证通过
    await websocket.send_json({'type': 'auth_ok', 'user': user_info})
    await room_manager.join(mindmap_id, websocket, user_info)

    # 通知其他人有新用户加入
    await room_manager.broadcast(
        mindmap_id,
        {'type': 'user_joined', 'user': user_info},
        exclude=websocket,
    )

    # 发送当前房间用户列表
    users = room_manager.get_room_users(mindmap_id)
    await websocket.send_json({'type': 'room_users', 'users': users})

    # 加载持久化的 Yjs 状态
    try:
        async with AsyncSessionLocal() as db:
            state = await YjsDocManager.load_state(db, mindmap_id)
            if state:
                await websocket.send_json({
                    'type': 'sync_init',
                    'state': base64.b64encode(state).decode(),
                })
    except Exception as e:
        logger.error(f'加载 Yjs 状态失败: {e}')

    # ── 消息循环 ──
    last_persist_time = 0.0
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type')

            if msg_type in ('sync_step1', 'sync_step2', 'update'):
                # 转发 Yjs 更新给房间内其他人
                await room_manager.broadcast(
                    mindmap_id,
                    {
                        'type': msg_type,
                        'update': data.get('update'),
                        'origin': str(user_info['id']),
                    },
                    exclude=websocket,
                )

                # 节流持久化：每 30 秒最多一次
                now = time.monotonic()
                if msg_type == 'update' and (now - last_persist_time) >= PERSIST_INTERVAL_SECONDS:
                    last_persist_time = now
                    try:
                        state_b64 = data.get('state', '')
                        if state_b64:
                            state_bytes = base64.b64decode(state_b64)
                            async with AsyncSessionLocal() as db:
                                await YjsDocManager.save_state(db, mindmap_id, state_bytes)
                    except Exception as e:
                        logger.error(f'持久化 Yjs 状态失败: {e}')

            elif msg_type == 'awareness':
                # 转发 awareness 更新（光标、选区等）
                await room_manager.broadcast(
                    mindmap_id,
                    {
                        'type': 'awareness',
                        'update': data.get('update'),
                        'userId': user_info['id'],
                    },
                    exclude=websocket,
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f'WebSocket 错误: {e}')
    finally:
        await room_manager.leave(mindmap_id, websocket)
        await room_manager.broadcast(
            mindmap_id,
            {'type': 'user_left', 'userId': user_info['id']},
        )
