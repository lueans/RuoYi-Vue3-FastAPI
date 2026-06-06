"""脑图 WebSocket 房间管理器"""
import asyncio
from typing import Any

from fastapi import WebSocket


class RoomManager:
    """管理 WebSocket 房间：每个脑图一个房间"""

    def __init__(self) -> None:
        self._rooms: dict[int, set] = {}
        self._user_info: dict[int, dict] = {}
        self._lock = asyncio.Lock()

    async def join(self, mindmap_id: int, websocket: WebSocket, user_info: dict) -> None:
        async with self._lock:
            if mindmap_id not in self._rooms:
                self._rooms[mindmap_id] = set()
            self._rooms[mindmap_id].add(websocket)
            self._user_info[id(websocket)] = user_info

    async def leave(self, mindmap_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if mindmap_id in self._rooms:
                self._rooms[mindmap_id].discard(websocket)
                if not self._rooms[mindmap_id]:
                    del self._rooms[mindmap_id]
            self._user_info.pop(id(websocket), None)

    async def broadcast(self, mindmap_id: int, message: Any, exclude: WebSocket | None = None) -> None:
        if mindmap_id not in self._rooms:
            return
        for ws in list(self._rooms[mindmap_id]):
            if ws != exclude:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    def get_room_users(self, mindmap_id: int) -> list[dict]:
        result = []
        if mindmap_id in self._rooms:
            for ws in self._rooms[mindmap_id]:
                info = self._user_info.get(id(ws))
                if info:
                    result.append(info)
        return result


room_manager = RoomManager()
