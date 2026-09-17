"""AI job request body limits are enforced before JSON/decryption expansion."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI

from config.env import TransportCryptoConfig
from middlewares import mindmap_ai_request_size_middleware as size_guard
from middlewares.handle import handle_middleware
from middlewares.mindmap_ai_request_size_middleware import MindmapAiRequestSizeMiddleware
from middlewares.transport_crypto_middleware import TransportCryptoMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.types import Message, Receive, Scope, Send

FOLLOWUP_PATH = '/mindmap/ai/jobs/20000000-0000-4000-8000-000000000001/messages'
CREATE_PATH = '/mindmap/ai/jobs'
PAYLOAD_TOO_LARGE_STATUS = 413
DUPLICATE_HEADER_STATUS = 400
TEST_AES_KEY = b'x' * 32


def test_size_guard_is_registered_outside_transport_crypto() -> None:
    app = FastAPI()

    handle_middleware(app)

    middleware_names = [item.cls.__name__ for item in app.user_middleware]
    assert middleware_names.index('MindmapAiRequestSizeMiddleware') < middleware_names.index(
        'TransportCryptoMiddleware',
    )


def _scope(
    *,
    path: str = FOLLOWUP_PATH,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Scope:
    return {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'http',
        'path': path,
        'raw_path': path.encode(),
        'query_string': b'',
        'headers': headers or [],
        'client': ('127.0.0.1', 12345),
        'server': ('testserver', 80),
        'state': {},
    }


def _receive_messages(messages: list[Message]) -> Receive:
    pending = list(messages)

    async def receive() -> Message:
        if pending:
            return pending.pop(0)
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    return receive


async def _invoke(
    app: Callable[[Scope, Receive, Send], Awaitable[None]],
    scope: Scope,
    messages: list[Message],
) -> list[Message]:
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, _receive_messages(messages), send)
    return sent


def _response_payload(messages: list[Message]) -> tuple[int, dict]:
    start = next(message for message in messages if message['type'] == 'http.response.start')
    body = b''.join(
        message.get('body', b'')
        for message in messages
        if message['type'] == 'http.response.body'
    )
    return int(start['status']), (json.loads(body) if body else {})


def _decrypt_response_payload(messages: list[Message]) -> tuple[int, dict, dict[bytes, bytes]]:
    start = next(message for message in messages if message['type'] == 'http.response.start')
    headers = dict(start.get('headers', []))
    body = b''.join(
        message.get('body', b'')
        for message in messages
        if message['type'] == 'http.response.body'
    )
    envelope = json.loads(body)

    def decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(f'{value}{"=" * (-len(value) % 4)}')

    aad = json.dumps(envelope['aad'], ensure_ascii=False, separators=(',', ':')).encode()
    plaintext = AESGCM(TEST_AES_KEY).decrypt(
        decode(envelope['iv']),
        decode(envelope['ct']),
        aad,
    )
    return int(start['status']), json.loads(plaintext), headers


@pytest.mark.asyncio
async def test_declared_oversized_followup_is_rejected_before_downstream() -> None:
    downstream_called = False

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    guarded = MindmapAiRequestSizeMiddleware(downstream)
    messages = await _invoke(
        guarded,
        _scope(headers=[
            (b'content-length', str(size_guard.MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES + 1).encode()),
        ]),
        [{'type': 'http.request', 'body': b'', 'more_body': False}],
    )

    status, payload = _response_payload(messages)
    assert status == PAYLOAD_TOO_LARGE_STATUS
    assert payload['data'] == {'errorCode': 'AI_INPUT_TOO_LARGE'}
    response_start = next(
        message for message in messages if message['type'] == 'http.response.start'
    )
    response_headers = dict(response_start['headers'])
    assert response_headers[b'cache-control'] == b'no-store'
    assert b'x-transport-crypto-status' not in response_headers
    assert downstream_called is False


@pytest.mark.asyncio
async def test_declared_oversized_job_creation_is_rejected_before_downstream() -> None:
    downstream_called = False

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    messages = await _invoke(
        MindmapAiRequestSizeMiddleware(downstream),
        _scope(
            path=CREATE_PATH,
            headers=[
                (
                    b'content-length',
                    str(
                        size_guard.MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES + 1,
                    ).encode(),
                ),
            ],
        ),
        [{'type': 'http.request', 'body': b'', 'more_body': False}],
    )

    status, payload = _response_payload(messages)
    assert status == PAYLOAD_TOO_LARGE_STATUS
    assert payload['data'] == {'errorCode': 'AI_INPUT_TOO_LARGE'}
    assert downstream_called is False


@pytest.mark.asyncio
async def test_chunked_followup_cannot_bypass_limit_with_missing_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(size_guard, 'MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES', 5)
    downstream_called = False

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    messages = await _invoke(
        MindmapAiRequestSizeMiddleware(downstream),
        _scope(),
        [
            {'type': 'http.request', 'body': b'123', 'more_body': True},
            {'type': 'http.request', 'body': b'456', 'more_body': False},
        ],
    )

    status, payload = _response_payload(messages)
    assert status == PAYLOAD_TOO_LARGE_STATUS
    assert payload['data']['errorCode'] == 'AI_INPUT_TOO_LARGE'
    assert downstream_called is False


@pytest.mark.asyncio
async def test_small_followup_is_replayed_once_with_plaintext_limit_state() -> None:
    observed: dict[str, object] = {}

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        observed['state'] = scope['state']
        observed['body'] = (await receive()).get('body')
        await send({'type': 'http.response.start', 'status': 204, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'', 'more_body': False})

    messages = await _invoke(
        MindmapAiRequestSizeMiddleware(downstream),
        _scope(headers=[(b'content-length', b'2')]),
        [{'type': 'http.request', 'body': b'{}', 'more_body': False}],
    )

    assert _response_payload(messages) == (204, {})
    assert observed['body'] == b'{}'
    assert observed['state'] == {
        size_guard.MINDMAP_AI_PLAINTEXT_BODY_LIMIT_STATE_KEY: (
            size_guard.MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES
        ),
    }


@pytest.mark.asyncio
async def test_unrelated_route_is_not_buffered_or_limited() -> None:
    received_message: Message | None = None

    async def downstream(_scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal received_message
        received_message = await receive()
        await send({'type': 'http.response.start', 'status': 204, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'', 'more_body': False})

    messages = await _invoke(
        MindmapAiRequestSizeMiddleware(downstream),
        _scope(path='/mindmap/ai/jobs/20000000-0000-4000-8000-000000000001/retry'),
        [{'type': 'http.request', 'body': b'unchanged', 'more_body': False}],
    )

    assert _response_payload(messages) == (204, {})
    assert received_message == {'type': 'http.request', 'body': b'unchanged', 'more_body': False}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'path',
    [CREATE_PATH, FOLLOWUP_PATH],
    ids=['create', 'followup'],
)
async def test_decrypted_ai_job_plaintext_is_bounded_after_envelope_expansion(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setattr(size_guard, 'MINDMAP_AI_REQUEST_PLAINTEXT_MAX_BYTES', 5)
    monkeypatch.setattr(size_guard, 'MINDMAP_AI_REQUEST_ENCRYPTED_WIRE_MAX_BYTES', 100)
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_enabled', True)
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_mode', 'optional')
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_enabled_paths', '')
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_exclude_paths', '')
    downstream_called = False

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    class ExpandedTransportMiddleware(TransportCryptoMiddleware):
        async def _decrypt_request(self, scope, request, headers, body):  # noqa: ANN001, ANN202
            decrypted_scope = dict(scope)
            decrypted_scope['state'] = dict(scope.get('state') or {})
            return decrypted_scope, b'123456', {'kid': 'test', 'aes_key': TEST_AES_KEY}

    guarded = MindmapAiRequestSizeMiddleware(
        ExpandedTransportMiddleware(downstream),
    )
    messages = await _invoke(
        guarded,
        _scope(path=path, headers=[
            (b'x-transport-encrypt', b'1'),
            (b'content-type', b'application/json'),
            (b'content-length', b'2'),
        ]),
        [{'type': 'http.request', 'body': b'{}', 'more_body': False}],
    )

    status, payload, response_headers = _decrypt_response_payload(messages)
    assert status == PAYLOAD_TOO_LARGE_STATUS
    assert payload['data']['errorCode'] == 'AI_INPUT_TOO_LARGE'
    assert response_headers[b'x-body-encrypted'] == b'1'
    assert response_headers[b'x-transport-response-mode'] == b'encrypted'
    assert response_headers[b'x-transport-crypto-status'] == b'payload_too_large'
    assert downstream_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'path',
    [CREATE_PATH, FOLLOWUP_PATH],
    ids=['create', 'followup'],
)
async def test_encrypted_wire_body_is_bounded_before_decryption(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setattr(size_guard, 'MINDMAP_AI_REQUEST_ENCRYPTED_WIRE_MAX_BYTES', 5)
    downstream_called = False

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    messages = await _invoke(
        MindmapAiRequestSizeMiddleware(downstream),
        _scope(path=path, headers=[(b'x-transport-encrypt', b'1')]),
        [
            {'type': 'http.request', 'body': b'123', 'more_body': True},
            {'type': 'http.request', 'body': b'456', 'more_body': False},
        ],
    )

    status, payload = _response_payload(messages)
    assert status == PAYLOAD_TOO_LARGE_STATUS
    assert payload['data']['errorCode'] == 'AI_INPUT_TOO_LARGE'
    assert downstream_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'headers',
    [
        [(b'x-transport-encrypt', b'0'), (b'X-Transport-Encrypt', b'1')],
        [(b'x-transport-encrypt', b'1'), (b'X-Transport-Encrypt', b'1')],
        [(b'x-transport-encrypt', b'0, 1')],
    ],
    ids=['conflicting', 'identical', 'proxy-coalesced'],
)
async def test_size_guard_rejects_duplicate_transport_encrypt_header(
    headers: list[tuple[bytes, bytes]],
) -> None:
    downstream_called = False

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    messages = await _invoke(
        MindmapAiRequestSizeMiddleware(downstream),
        _scope(headers=headers),
        [{'type': 'http.request', 'body': b'{}', 'more_body': False}],
    )

    status, payload = _response_payload(messages)
    assert status == DUPLICATE_HEADER_STATUS
    assert payload == {
        'code': DUPLICATE_HEADER_STATUS,
        'msg': size_guard.TRANSPORT_ENCRYPT_HEADER_DUPLICATE_MESSAGE,
        'success': False,
    }
    response_start = next(
        message for message in messages if message['type'] == 'http.response.start'
    )
    assert (
        dict(response_start['headers'])[b'x-transport-crypto-status']
        == b'duplicate_request_header'
    )
    assert downstream_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'headers',
    [
        [(b'x-transport-encrypt', b'0'), (b'X-Transport-Encrypt', b'1')],
        [(b'x-transport-encrypt', b'1'), (b'X-Transport-Encrypt', b'1')],
        [(b'x-transport-encrypt', b'0, 1')],
    ],
    ids=['conflicting', 'identical', 'proxy-coalesced'],
)
async def test_transport_crypto_rejects_duplicate_transport_encrypt_header(
    monkeypatch: pytest.MonkeyPatch,
    headers: list[tuple[bytes, bytes]],
) -> None:
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_enabled', True)
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_mode', 'optional')
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_enabled_paths', '')
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_exclude_paths', '')
    downstream_called = False

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    messages = await _invoke(
        TransportCryptoMiddleware(downstream),
        _scope(headers=headers),
        [{'type': 'http.request', 'body': b'{}', 'more_body': False}],
    )

    status, payload = _response_payload(messages)
    assert status == DUPLICATE_HEADER_STATUS
    assert payload == {
        'code': DUPLICATE_HEADER_STATUS,
        'msg': size_guard.TRANSPORT_ENCRYPT_HEADER_DUPLICATE_MESSAGE,
        'success': False,
    }
    start = next(message for message in messages if message['type'] == 'http.response.start')
    assert dict(start['headers'])[b'x-transport-crypto-status'] == b'duplicate_request_header'
    assert downstream_called is False
