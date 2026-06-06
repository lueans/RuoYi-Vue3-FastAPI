"""脑图 WebSocket 路由注册"""
from fastapi import APIRouter, WebSocket

from module_mindmap.websocket.mindmap_ws import mindmap_websocket_endpoint

mindmap_ws_controller = APIRouter(prefix='/ws/mindmap', tags=['脑图WebSocket'])


@mindmap_ws_controller.websocket('/{mindmap_id}')
async def mindmap_ws(websocket: WebSocket, mindmap_id: int) -> None:
    await mindmap_websocket_endpoint(websocket, mindmap_id)
