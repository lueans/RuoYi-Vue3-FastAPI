"""脑图 WebSocket 端点"""
import asyncio
import base64
import time

from fastapi import WebSocket, WebSocketDisconnect

from config.database import AsyncSessionLocal
from exceptions.exception import ServiceException
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.websocket.room_manager import room_manager
from module_mindmap.websocket.ws_auth import validate_ws_token
from module_mindmap.websocket.yjs_doc import YjsDocManager
from utils.log_util import logger

# 认证超时：连接后 10 秒内必须发送 auth 消息
AUTH_TIMEOUT_SECONDS = 10
# Yjs 状态持久化间隔：每 30 秒最多持久化一次
PERSIST_INTERVAL_SECONDS = 30
# 心跳间隔：每 30 秒发送一次 ping
HEARTBEAT_INTERVAL_SECONDS = 30
# 连续未响应 pong 次数上限，超过则判定连接死亡
HEARTBEAT_MISS_LIMIT = 3


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

    # ── 脑图访问权限校验（防止认证用户访问无权限的脑图） ──
    try:
        async with AsyncSessionLocal() as db:
            await MindmapService.check_mindmap_access(
                db, mindmap_id, user_info['id'], require_edit=True,
            )
    except ServiceException:
        await websocket.send_json({
            'type': 'auth_error',
            'message': '无访问权限',
        })
        await websocket.close(code=4003)
        return
    except Exception as e:
        logger.error(f'WebSocket 权限校验异常: {e}')
        await websocket.send_json({'type': 'auth_error', 'message': '权限校验失败'})
        await websocket.close(code=4003)
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

    # ── 心跳任务 ──
    missed_pongs = 0

    async def heartbeat():
        """定期发送 ping，检测死亡连接"""
        nonlocal missed_pongs
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                if missed_pongs >= HEARTBEAT_MISS_LIMIT:
                    logger.warning(f'心跳超时: 用户 {user_info["id"]} 连续 {missed_pongs} 次未响应 pong，关闭连接')
                    try:
                        await websocket.close(code=4002)
                    except Exception:
                        pass
                    return
                missed_pongs += 1
                try:
                    await websocket.send_json({'type': 'ping'})
                except Exception:
                    return
        except (WebSocketDisconnect, Exception):
            pass

    heartbeat_task = asyncio.create_task(heartbeat())

    # ── 消息循环 ──
    last_persist_time = 0.0
    latest_state_b64 = ''  # 跟踪最新的 Yjs 状态，用于断开时最终保存
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
                state_b64 = data.get('state', '')
                if state_b64:
                    latest_state_b64 = state_b64
                if msg_type == 'update' and state_b64 and (now - last_persist_time) >= PERSIST_INTERVAL_SECONDS:
                    last_persist_time = now
                    try:
                        state_bytes = base64.b64decode(state_b64)
                        async with AsyncSessionLocal() as db:
                            await YjsDocManager.save_state(db, mindmap_id, state_bytes)
                    except Exception as e:
                        logger.error(f'持久化 Yjs 状态失败: {e}')

            elif msg_type == 'pong':
                # 心跳响应，重置未响应计数
                missed_pongs = 0

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
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        # 断开时最终保存 Yjs 状态，防止丢失节流窗口内的数据
        if latest_state_b64:
            try:
                state_bytes = base64.b64decode(latest_state_b64)
                async with AsyncSessionLocal() as db:
                    await YjsDocManager.save_state(db, mindmap_id, state_bytes)
            except Exception as e:
                logger.error(f'断开时保存 Yjs 状态失败: {e}')
        await room_manager.leave(mindmap_id, websocket)
        await room_manager.broadcast(
            mindmap_id,
            {'type': 'user_left', 'userId': user_info['id']},
        )
