"""Bound local-snapshot AI job bodies before FastAPI parses JSON."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from config.env import AppConfig

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

# One request may contain one local document of up to 2 MiB, plus a UTF-8 prompt
# and bounded JSON metadata.  The encrypted envelope is Base64URL encoded, hence
# the separate (still bounded) wire allowance.
MINDMAP_AI_REQUEST_METADATA_ALLOWANCE_BYTES = 256 * 1024
MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES = (2 * 1024 * 1024) + (
    MINDMAP_AI_REQUEST_METADATA_ALLOWANCE_BYTES
)
MINDMAP_AI_REQUEST_ENCRYPTED_WIRE_MAX_BYTES = (
    4 * ((MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES + 2) // 3)
) + (64 * 1024)
MINDMAP_AI_PLAINTEXT_BODY_LIMIT_STATE_KEY = 'mindmap_ai_plaintext_body_limit'
MINDMAP_AI_INPUT_TOO_LARGE_STATUS = 413
MINDMAP_AI_INPUT_TOO_LARGE_ERROR_CODE = 'AI_INPUT_TOO_LARGE'
MINDMAP_AI_INPUT_TOO_LARGE_MESSAGE = 'AI 输入内容超过任务上限，请缩小脑图后重试'
TRANSPORT_ENCRYPT_HEADER_DUPLICATE_STATUS = 400
TRANSPORT_ENCRYPT_HEADER_DUPLICATE_MESSAGE = 'x-transport-encrypt 请求头不能重复'
TRANSPORT_ENCRYPT_HEADER_DUPLICATE_RESPONSE_HEADERS = {
    'Cache-Control': 'no-store',
    'x-transport-request-mode': 'ambiguous',
    'x-transport-response-mode': 'plain',
    'x-transport-crypto-status': 'duplicate_request_header',
}

_CREATE_PATH_PATTERN = re.compile(r'^/mindmap/ai/jobs/?$')
_FOLLOWUP_PATH_PATTERN = re.compile(r'^/mindmap/ai/jobs/[^/]{36}/messages/?$')
_TOO_LARGE_CONTENT = {
    'code': MINDMAP_AI_INPUT_TOO_LARGE_STATUS,
    'msg': MINDMAP_AI_INPUT_TOO_LARGE_MESSAGE,
    'data': {'errorCode': MINDMAP_AI_INPUT_TOO_LARGE_ERROR_CODE},
    'success': False,
}


def is_ambiguous_transport_encrypt_header(values: list[bytes]) -> bool:
    """Reject raw duplicates and proxy-coalesced duplicate header values."""
    return len(values) > 1 or any(b',' in value for value in values)


class MindmapAiRequestSizeMiddleware:
    """Pre-read AI job input endpoints with a strict, bounded buffer."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_ai_job_input_request(scope):
            await self.app(scope, receive, send)
            return

        encrypt_header_values = self._header_values(scope, b'x-transport-encrypt')
        if is_ambiguous_transport_encrypt_header(encrypt_header_values):
            await self._send_duplicate_transport_header(scope, receive, send)
            return
        encrypted = bool(encrypt_header_values and encrypt_header_values[0] == b'1')
        wire_limit = (
            MINDMAP_AI_REQUEST_ENCRYPTED_WIRE_MAX_BYTES
            if encrypted
            else MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES
        )
        content_length = self._content_length(scope)
        if content_length is not None and content_length > wire_limit:
            await self._send_too_large(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            if message['type'] != 'http.request':
                continue
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > wire_limit:
                await self._send_too_large(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get('more_body', False):
                break

        limited_scope = dict(scope)
        limited_scope['state'] = dict(scope.get('state') or {})
        limited_scope['state'][MINDMAP_AI_PLAINTEXT_BODY_LIMIT_STATE_KEY] = (
            MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES
        )
        await self.app(limited_scope, self._build_receive(bytes(body)), send)

    @staticmethod
    def _header_values(scope: Scope, name: bytes) -> list[bytes]:
        normalized_name = name.lower()
        return [
            value.strip().lower()
            for key, value in scope.get('headers', [])
            if key.lower() == normalized_name
        ]

    @classmethod
    def _header(cls, scope: Scope, name: bytes) -> bytes | None:
        values = cls._header_values(scope, name)
        return values[-1] if values else None

    @classmethod
    def _content_length(cls, scope: Scope) -> int | None:
        raw_value = cls._header(scope, b'content-length')
        if raw_value is None:
            return None
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        return max(0, value)

    @staticmethod
    def _normalize_path(path: str) -> str:
        app_root_path = AppConfig.app_root_path
        if app_root_path and path.startswith(app_root_path):
            return path[len(app_root_path) :] or '/'
        return path or '/'

    @classmethod
    def _is_ai_job_input_request(cls, scope: Scope) -> bool:
        path = cls._normalize_path(str(scope.get('path', '')))
        return bool(
            scope.get('type') == 'http'
            and str(scope.get('method', '')).upper() == 'POST'
            and (
                _CREATE_PATH_PATTERN.fullmatch(path)
                or _FOLLOWUP_PATH_PATTERN.fullmatch(path)
            )
        )

    @staticmethod
    def _build_receive(body: bytes) -> Receive:
        sent = False

        async def _receive() -> Message:
            nonlocal sent
            if sent:
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}

        return _receive

    @staticmethod
    async def _send_too_large(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=MINDMAP_AI_INPUT_TOO_LARGE_STATUS,
            content=_TOO_LARGE_CONTENT,
            headers={'Cache-Control': 'no-store'},
        )
        await response(scope, receive, send)

    @staticmethod
    async def _send_duplicate_transport_header(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response = JSONResponse(
            status_code=TRANSPORT_ENCRYPT_HEADER_DUPLICATE_STATUS,
            content={
                'code': TRANSPORT_ENCRYPT_HEADER_DUPLICATE_STATUS,
                'msg': TRANSPORT_ENCRYPT_HEADER_DUPLICATE_MESSAGE,
                'success': False,
            },
            headers=TRANSPORT_ENCRYPT_HEADER_DUPLICATE_RESPONSE_HEADERS,
        )
        await response(scope, receive, send)


def add_mindmap_ai_request_size_middleware(app: FastAPI) -> None:
    """Register the route-scoped AI job request body guard."""

    app.add_middleware(MindmapAiRequestSizeMiddleware)
