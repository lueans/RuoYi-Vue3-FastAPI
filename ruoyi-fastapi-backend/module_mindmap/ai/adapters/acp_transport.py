"""OpenDesign's initialize → new → prompt stdio lifecycle, ported to asyncio.

ACP controls the external CLI. MCP calls alone control the mind-map draft.
No provider-specific filesystem or terminal client capabilities are exposed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import socket
from typing import TYPE_CHECKING

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from module_mindmap.ai.adapters.codex_mcp_bridge import TOOL_DESCRIPTORS
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.runtime_trace import RuntimeTrace

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from starlette.requests import Request

    from module_mindmap.ai.adapters.base import AgentEventHandler
    from module_mindmap.ai.adapters.codex import _CodexToolExecutionBridge

ACP_AUTH_REQUIRED = -32000
MAX_PERMISSION_OPTIONS = 16
MAX_OPTION_ID_CHARS = 128
MAX_RPC_ID_CHARS = 512
MAX_SERVER_REQUESTS = 1024


class AcpSession:
    def __init__(
        self, process: asyncio.subprocess.Process, emit: AgentEventHandler, *, allowed_tools: tuple[str, ...] = (),
    ) -> None:
        self.process = process
        self.emit = emit
        self.session_id: str | None = None
        self.trace = RuntimeTrace(acp_gateway_tools=allowed_tools)
        self.text = ''
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._reader: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._failure: MindmapArtifactError | None = None
        self._closed = False
        self._cancelled = False
        self._accept_updates = False
        self._prompt_started = False
        self._request_methods: dict[int, str] = {}
        self._server_requests: set[tuple[type, str | int]] = set()

    async def _send(self, message: dict) -> None:
        async with self._write_lock:
            self.process.stdin.write((json.dumps(message, ensure_ascii=False, allow_nan=False) + '\n').encode())
            await self.process.stdin.drain()

    async def request(self, method: str, params: dict, timeout: float = 30) -> dict:
        if self._failure is not None:
            raise self._failure
        if self._closed or (self._reader is not None and self._reader.done()):
            raise MindmapArtifactError('ACP 连接已结束', code='AI_AGENT_UNAVAILABLE')
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._request_methods[request_id] = method

        async def exchange() -> dict:
            await self._send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
            return await future

        try:
            # Include stdin backpressure in the deadline, not only the reply.
            return await asyncio.wait_for(exchange(), timeout)
        finally:
            self._pending.pop(request_id, None)
            self._request_methods.pop(request_id, None)
            # A send can fail while the reader settles the same future.
            if future.done() and not future.cancelled():
                future.exception()
            elif not future.done():
                future.cancel()

    async def _permission(self, params: dict) -> dict:
        outcome = {'outcome': 'cancelled'}
        if not self._accept_updates or not self.session_id or params.get('sessionId') != self.session_id:
            return {'outcome': outcome}
        tool_call, options = params.get('toolCall'), params.get('options')
        if (not isinstance(tool_call, dict) or not isinstance(options, list)
                or not 1 <= len(options) <= MAX_PERMISSION_OPTIONS):
            return {'outcome': outcome}
        ids = set()
        for option in options:
            if (not isinstance(option, dict) or not isinstance(option.get('optionId'), str)
                    or not 1 <= len(option['optionId']) <= MAX_OPTION_ID_CHARS or option['optionId'] in ids):
                return {'outcome': outcome}
            ids.add(option['optionId'])
        option = next((item for item in options if item.get('kind') == 'allow_once'), None)
        if option is not None and self.trace.approve_acp_tool_once(tool_call):
            outcome = {'outcome': 'selected', 'optionId': option['optionId']}
        return {'outcome': outcome}

    async def _notification(self, method: str, params: dict) -> None:
        if (method != 'session/update' or not self._accept_updates or not self.session_id
                or params.get('sessionId') != self.session_id):
            return
        update = params.get('update')
        if not isinstance(update, dict):
            raise ValueError('invalid ACP update')
        if update.get('sessionUpdate') == 'agent_message_chunk':
            content = update.get('content')
            if (isinstance(content, dict) and content.get('type') in (None, 'text')
                    and isinstance(content.get('text'), str)):
                self.text = (self.text + content['text'])[-100000:]
        for kind, payload in self.trace.acp(update):
            if not self._accept_updates:
                break
            await self.emit(kind, payload)

    def _response(self, message: dict) -> None:
        request_id = message.get('id')
        # JSON booleans compare equal to 0/1 in Python, but are not RPC IDs.
        if (type(request_id) is not int or request_id not in self._pending
                or ('result' in message) == ('error' in message)):
            raise ValueError('invalid ACP response')
        future = self._pending[request_id]
        if future.done():
            raise ValueError('duplicate ACP response')
        # Close the publication gate in the reader, before processing buffered
        # frames after the prompt response (not later in the awaiting task).
        if self._request_methods[request_id] == 'session/prompt':
            self._accept_updates = False
        if 'error' in message:
            error = message['error']
            if not isinstance(error, dict) or type(error.get('code')) is not int:
                raise ValueError('invalid ACP error')
            auth = error['code'] == ACP_AUTH_REQUIRED
            future.set_exception(MindmapArtifactError(
                'Agent 登录已失效，请在运行主机完成登录' if auth else 'ACP 请求失败，请检查 CLI 版本及登录状态',
                code='AI_PROVIDER_AUTH_FAILED' if auth else 'AI_AGENT_UNAVAILABLE',
            ))
        else:
            if not isinstance(message['result'], dict):
                raise ValueError('invalid ACP result')
            future.set_result(message['result'])

    async def _receive(self) -> None:  # noqa: PLR0912
        error = MindmapArtifactError('ACP 连接已结束', code='AI_AGENT_UNAVAILABLE')
        try:
            total = 0
            while line := await self.process.stdout.readline():
                total += len(line)
                if len(line) > 1024 * 1024 or total > 16 * 1024 * 1024:
                    raise ValueError('ACP stream limit')
                message = json.loads(line)
                json.dumps(message, allow_nan=False)
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                    raise ValueError('invalid ACP envelope')
                method = message.get('method')
                if 'method' not in message:
                    self._response(message)
                    continue
                params = message.get('params', {})
                if (not isinstance(method, str) or not method or not isinstance(params, dict)
                        or 'result' in message or 'error' in message):
                    raise ValueError('invalid ACP method')
                if 'id' not in message:
                    await self._notification(method, params)
                    continue
                request_id = message['id']
                if (type(request_id) not in (int, str) or len(str(request_id)) > MAX_RPC_ID_CHARS
                        or (type(request_id), request_id) in self._server_requests
                        or len(self._server_requests) >= MAX_SERVER_REQUESTS):
                    raise ValueError('invalid or repeated ACP request ID')
                self._server_requests.add((type(request_id), request_id))
                response = {'jsonrpc': '2.0', 'id': request_id}
                if method == 'session/request_permission':
                    response['result'] = await self._permission(params)
                else:
                    response['error'] = {'code': -32601, 'message': 'Client capability unavailable'}
                await self._send(response)
        except asyncio.CancelledError:
            raise
        except MindmapArtifactError as exc:
            error = exc
        except Exception:
            error = MindmapArtifactError('ACP 实时协议无效', code='AI_AGENT_UNAVAILABLE')
        finally:
            self._failure = error
            self._accept_updates = False
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(error)

    async def start(self, cwd: str, mcp_servers: list[dict]) -> dict:
        if self._reader is not None or self._closed:
            raise MindmapArtifactError('ACP 会话不能重复创建', code='AI_AGENT_UNAVAILABLE')
        self._reader = asyncio.create_task(self._receive())
        hello = await self.request(
            'initialize',
            {
                'protocolVersion': 1,
                'clientInfo': {'name': 'ruoyi-mindmap', 'version': '1.0.0'},
                'clientCapabilities': {},
            },
        )
        if type(hello.get('protocolVersion')) is not int or hello['protocolVersion'] != 1:
            raise MindmapArtifactError('ACP 协议版本不兼容', code='AI_CAPABILITY_UNSUPPORTED')
        capabilities = hello.get('agentCapabilities')
        mcp = capabilities.get('mcpCapabilities') if isinstance(capabilities, dict) else None
        if mcp_servers and (not isinstance(mcp, dict) or mcp.get('http') is not True):
            raise MindmapArtifactError('此 Agent 不支持脑图 HTTP MCP 工具', code='AI_CAPABILITY_UNSUPPORTED')
        session = await self.request('session/new', {'cwd': cwd, 'mcpServers': mcp_servers})
        self.session_id = session.get('sessionId')
        if not isinstance(self.session_id, str) or not self.session_id or len(self.session_id) > MAX_RPC_ID_CHARS:
            raise MindmapArtifactError('ACP 会话未创建', code='AI_AGENT_UNAVAILABLE')
        return session

    async def prompt(self, prompt: str, timeout: float) -> None:
        if not self.session_id or self._prompt_started or self._closed or self._cancelled:
            raise MindmapArtifactError('ACP 任务不能重复执行', code='AI_AGENT_UNAVAILABLE')
        self._prompt_started = self._accept_updates = True
        try:
            result = await self.request(
                'session/prompt',
                {'sessionId': self.session_id, 'prompt': [{'type': 'text', 'text': prompt}]},
                timeout,
            )
        finally:
            self._accept_updates = False
        if self._cancelled:
            raise asyncio.CancelledError
        for kind, payload in self.trace.finish():
            if self._cancelled or self._closed:
                raise asyncio.CancelledError
            await self.emit(kind, payload)
        if result.get('stopReason') != 'end_turn':
            raise MindmapArtifactError('Agent 未正常完成本轮任务', code='AI_OUTPUT_INVALID')

    async def cancel(self) -> None:
        self._cancelled = True
        self._accept_updates = False
        if self.session_id:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self._send(
                        {'jsonrpc': '2.0', 'method': 'session/cancel', 'params': {'sessionId': self.session_id}}
                    ),
                    0.5,
                )

    async def close(self) -> None:
        self._closed = True
        self._accept_updates = False
        if self._reader:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader


class _EmbeddedServer(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        # A job-owned server must not replace the FastAPI host's signal handlers.
        yield


@contextlib.asynccontextmanager
async def mindmap_http_mcp(bridge: _CodexToolExecutionBridge, allowed_tools: tuple[str, ...]) -> AsyncIterator[dict]:  # noqa: PLR0915
    """Stateless Streamable HTTP MCP, private loopback capability URL per turn."""
    token = secrets.token_urlsafe(32)
    closing = False

    async def handle(request: Request) -> Response:  # noqa: PLR0912
        if closing or request.headers.get('origin'):
            return Response(status_code=403)
        if request.method == 'GET':
            return Response(status_code=405)
        if request.method == 'DELETE':
            return Response(status_code=204)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2 * 1024 * 1024:
                return Response(status_code=413)
        try:
            message = json.loads(raw)
            if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                raise ValueError
            method = message.get('method')
            request_id = message.get('id')
            if request_id is None:
                return Response(status_code=202)
            params = message.get('params') or {}
            if method == 'initialize':
                result = {
                    'protocolVersion': '2025-06-18',
                    'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'mindmap', 'version': '1.0.0'},
                }
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': [{'name': name, **TOOL_DESCRIPTORS[name]} for name in allowed_tools]}
            elif method == 'tools/call' and params.get('name') in allowed_tools:
                response = await bridge.call(params['name'], params.get('arguments', {}))
                result = {
                    'content': [
                        {'type': 'text', 'text': json.dumps(response.get('result', response), ensure_ascii=False)}
                    ],
                    'isError': not response.get('ok', False),
                }
            else:
                return JSONResponse(
                    {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'Unknown method or tool'}}
                )
            return JSONResponse({'jsonrpc': '2.0', 'id': request_id, 'result': result})
        except (ValueError, TypeError, KeyError):
            return Response(status_code=400)

    app = Starlette(routes=[Route(f'/{token}', handle, methods=['POST', 'GET', 'DELETE'])])
    server = _EmbeddedServer(
        uvicorn.Config(
            app, lifespan='off', access_log=False, log_config=None, timeout_graceful_shutdown=2, limit_concurrency=8
        )
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    address = sock.getsockname()
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
                raise RuntimeError('MCP server failed to start')
            await asyncio.sleep(0.01)
        if not server.started:
            raise RuntimeError('MCP server startup timeout')
        yield {'type': 'http', 'name': 'mindmap', 'url': f'http://127.0.0.1:{address[1]}/{token}', 'headers': []}
    finally:
        closing = True
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 4)
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            sock.close()
