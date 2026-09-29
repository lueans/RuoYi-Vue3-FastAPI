"""Per-run, loopback-only MCP capability; no filesystem/shell tool exposure.

The platform's original tool gateway remains authoritative for mutations,
Todo, tool detail and streaming draft events. ACP copies are not replayed.
"""

import asyncio
import contextlib
import json
import secrets
import socket

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .execution import MAX_OFFER_BYTES, MAX_REPLY_BYTES, RunCleanupError, RunProtocolError, RunStopped, _bounded, _load


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):
        yield  # never change the companion's signal handlers


class KimiToolGateway:
    def __init__(self, offer, channel):
        self.offer, self.channel = offer, channel
        self.accepting = False
        self.failure = None
        self._lock = asyncio.Lock()
        self._ids = set()
        self._calls = 0
        self._closing = False
        self._server = self._task = self._socket = self.description = None

    def disable(self):
        self.accepting = False

    async def _handle(self, request: Request):
        # Exact Host defeats DNS rebinding. Any Origin (including null) is
        # rejected; browsers do not receive CORS grants or credential cookies.
        if (self._closing or 'origin' in request.headers or request.headers.get('host') != self._host
                or request.client is None or request.client.host != '127.0.0.1'):
            return Response(status_code=403)
        if request.method != 'POST':
            return Response(status_code=405)
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return Response(status_code=415)
        try:
            async def read():
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > MAX_OFFER_BYTES:
                        raise RunProtocolError
                return _load(bytes(raw), MAX_OFFER_BYTES)
            value = await _bounded(read(), 10)
            if (value.get('jsonrpc') != '2.0' or not isinstance(value.get('method'), str)
                    or not isinstance(value.get('params', {}), dict)
                    or set(value) - {'jsonrpc', 'method', 'params', 'id'}):
                raise RunProtocolError
            method, params = value['method'], value.get('params', {})
            if 'id' not in value:
                return Response(status_code=202 if method == 'notifications/initialized' else 400)
            identity = value['id']
            if type(identity) not in {str, int} or len(str(identity)) > 200:
                raise RunProtocolError
            # Type-tag IDs so string "1" and integer 1 are distinct. Record
            # before awaiting a tool; concurrent retries cannot repeat edits.
            key = (type(identity), identity)
            if key in self._ids or len(self._ids) >= 1024:
                raise RunProtocolError
            self._ids.add(key)
            if method == 'initialize':
                result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'mindmap', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': list(self.offer.tools)}
            elif method == 'tools/call':
                name, arguments = params.get('name'), params.get('arguments', {})
                if name not in {tool['name'] for tool in self.offer.tools} or not isinstance(arguments, dict):
                    raise RunProtocolError
                async with self._lock:
                    if not self.accepting or self._closing or self.failure is not None:
                        return Response(status_code=403)
                    self._calls += 1
                    if self._calls > 200:
                        raise RunProtocolError
                    try:
                        response = await self.channel.tool(name, arguments)
                        text = json.dumps(response, ensure_ascii=False, allow_nan=False)
                        if not isinstance(response, dict) or len(text.encode()) > MAX_REPLY_BYTES:
                            raise RunProtocolError
                    except Exception as error:
                        self.failure = error
                        self.disable()
                        return Response(status_code=503)
                result = {'content': [{'type': 'text', 'text': text}], 'isError': response.get('ok') is not True}
            else:
                return JSONResponse({'jsonrpc': '2.0', 'id': identity,
                                     'error': {'code': -32601, 'message': 'Capability not allowed'}})
            return JSONResponse({'jsonrpc': '2.0', 'id': identity, 'result': result})
        except (RunProtocolError, ValueError, TypeError, asyncio.TimeoutError):
            return Response(status_code=400)

    async def start(self):
        if self._socket is not None or self._closing:
            raise RunProtocolError
        token = secrets.token_urlsafe(32)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(('127.0.0.1', 0))
        self._host = f'127.0.0.1:{self._socket.getsockname()[1]}'
        app = Starlette(routes=[Route(f'/{token}', self._handle, methods=['POST', 'GET', 'DELETE'])])
        self._server = _Server(uvicorn.Config(
            app, lifespan='off', access_log=False, log_config=None, ws='none',
            timeout_graceful_shutdown=1, limit_concurrency=8, h11_max_incomplete_event_size=16384,
        ))
        self._task = asyncio.create_task(self._server.serve(sockets=[self._socket]))
        for _ in range(200):
            if self._server.started:
                self.description = {'name': 'mindmap', 'type': 'http', 'url': f'http://{self._host}/{token}', 'headers': []}
                return self.description
            if self._task.done():
                await self._task
                raise RunProtocolError
            await asyncio.sleep(0.01)
        raise RunProtocolError

    async def close(self):
        self._closing = True
        self.disable()
        if self._server is not None:
            self._server.should_exit = True
        try:
            if self._task is not None:
                await _bounded(self._task, 3)
        except (asyncio.TimeoutError, RunStopped):
            raise RunCleanupError from None
        finally:
            if self._socket is not None:
                self._socket.close()
