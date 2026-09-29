"""Outbound authenticated transport; credentials never appear in URLs or logs."""

import asyncio
import ipaddress
import json
import os
import re
import stat
import tempfile
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidTag
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from .discovery import discover
from .transport import decrypt, encrypt, uses_envelope

MAX_CONFIG_BYTES = 8192
MAX_FRAME_BYTES = 16384
SECRET_PATTERN = re.compile(r'^[A-Za-z0-9_-]{43}$')
HEARTBEAT_SECONDS = 5
CONNECTION_CONFLICT_RETRY_SECONDS = 25
MAX_SCAN_REVISION = 2_147_483_647


class BridgeError(Exception):
    """Already-sanitized message, safe to show in a local terminal."""


class NoRedirectConnect(connect):
    def process_redirect(self, exc: Exception) -> Exception:
        # websockets normally forwards headers on some redirects. A configured
        # device credential is scoped to precisely this origin and API path.
        return exc


def normalize_server(value: str) -> str:
    if any(ord(character) < ord(' ') for character in value):
        raise BridgeError('服务地址包含非法字符')
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BridgeError('请提供不含账号、查询参数或片段的服务 API 地址')
    try:
        loopback = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = False
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback):
        raise BridgeError('远程服务必须使用 HTTPS；HTTP 仅允许本机回环地址')
    try:
        _ = parsed.port  # urllib validates port syntax lazily.
    except ValueError:
        raise BridgeError('服务端口无效') from None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', ''))


def read_config(path: Path) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'r', encoding='utf-8') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG_BYTES:
                raise BridgeError('设备配置不是有效的私有文件')
            if os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
                raise BridgeError('设备配置必须归当前用户所有，且权限为 0600')
            value = json.load(handle)
        if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
            raise ValueError
        if str(UUID(value['deviceId'])) != value['deviceId'] or not SECRET_PATTERN.fullmatch(value['deviceSecret']):
            raise ValueError
        value['server'] = normalize_server(value['server'])
        if 'pairingSecret' in value and not SECRET_PATTERN.fullmatch(value['pairingSecret']):
            raise ValueError
        return value
    except BridgeError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise BridgeError('无法读取设备配置，请先配对；不会输出配置中的秘密') from None


def save_config(path: Path, value: dict, *, initial: bool = False) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink():
        raise BridgeError('拒绝写入符号链接配置')
    data = json.dumps(value, ensure_ascii=False).encode('utf-8')
    if initial:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            raise BridgeError('设备配置已经存在，不会覆盖；请先在网页撤销旧设备') from None
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return
    fd, staged = tempfile.mkstemp(prefix='.device-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


async def enroll(config: dict) -> None:
    async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
        try:
            path = '/mindmap/ai/device-bridge/enroll'
            payload = {
                'deviceId': config['deviceId'], 'deviceSecret': config['deviceSecret'],
                'pairingSecret': config['pairingSecret'],
            }
            metadata = await client.get(config['server'] + '/transport/crypto/frontend-config')
            metadata.raise_for_status()
            encrypted = uses_envelope(metadata.json()['data'], path)
            key = None
            if encrypted:
                public_key = await client.get(config['server'] + '/transport/crypto/public-key')
                public_key.raise_for_status()
                payload, key = encrypt(payload, public_key.json()['data'], path)
            response = await client.post(config['server'] + path, json=payload,
                                         headers={'x-transport-encrypt': '1'} if encrypted else {})
            response.raise_for_status()
            body = response.json()
            if encrypted:
                if response.headers.get('x-body-encrypted') != '1':
                    raise BridgeError('加密配对请求未收到加密响应，已拒绝降级')
                body = decrypt(body, key, payload['kid'], path)
            if body.get('code') != HTTPStatus.OK or body.get('data', {}).get('deviceId') != config['deviceId']:
                raise BridgeError('服务未确认配对，请核对 API 地址')
        except httpx.HTTPStatusError as error:
            raise BridgeError(f'配对失败（HTTP {error.response.status_code}），请检查配对码或服务配置') from None
        except (httpx.HTTPError, ValueError, AttributeError, KeyError, TypeError, InvalidTag):
            raise BridgeError('配对响应未确认；本地密钥已保留，可重试同一次配对') from None


def decode_state(raw: str | bytes, expected: str) -> dict:
    try:
        if len(raw) > MAX_FRAME_BYTES:
            raise ValueError
        payload = json.loads(raw)
        allowed = {'type', 'protocolVersion', 'capabilities', 'executionAvailable'}
        if expected == 'state':
            allowed.add('scanRevision')
        if (set(payload) != allowed or payload['type'] != expected or type(payload['protocolVersion']) is not int
                or payload['protocolVersion'] != 1 or payload['capabilities'] != ['discover']
                or payload['executionAvailable'] is not False):
            raise ValueError
        if expected == 'state' and (type(payload['scanRevision']) is not int or not 1 <= payload['scanRevision'] <= MAX_SCAN_REVISION):
            raise ValueError
        return payload
    except (ValueError, TypeError, KeyError):
        raise BridgeError('服务协议不兼容；此桥接仅允许扫描，不接受执行命令') from None


async def connected_session(socket: ClientConnection, *, scan: Callable[[], Awaitable[list[dict]]] = discover) -> None:
    decode_state(await asyncio.wait_for(socket.recv(), 15), 'welcome')

    async def exchange(payload: dict) -> dict:
        await socket.send(json.dumps(payload))
        return decode_state(await asyncio.wait_for(socket.recv(), 15), 'state')

    completed = 0
    state = await exchange({'type': 'heartbeat', 'protocolVersion': 1})
    while True:
        requested = state['scanRevision']
        if requested < completed:
            raise BridgeError('服务扫描序号回退，请检查服务状态')
        if requested > completed:
            runtimes = await scan()
            state = await exchange({'type': 'scan_result', 'protocolVersion': 1,
                                    'scanRevision': requested, 'runtimes': runtimes})
            completed = requested
        await asyncio.sleep(HEARTBEAT_SECONDS)
        state = await exchange({'type': 'heartbeat', 'protocolVersion': 1})


async def run(config: dict) -> None:
    parsed = urlsplit(normalize_server(config['server']))
    url = urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', parsed.netloc,
                     parsed.path + '/mindmap/ai/device-bridge/connect/' + config['deviceId'], '', ''))
    delay = 1
    conflict_deadline = None
    while True:
        open_timeout = 10
        if conflict_deadline is not None:
            remaining = conflict_deadline - monotonic()
            if remaining <= 0:
                raise BridgeError('此设备已有在线桥接，等待连接释放超时；请检查原桥接进程后重试')
            open_timeout = min(open_timeout, remaining)
        try:
            async with NoRedirectConnect(
                url, additional_headers={'Authorization': 'Bearer ' + config['deviceSecret']},
                proxy=None, max_size=MAX_FRAME_BYTES, open_timeout=open_timeout, close_timeout=3,
            ) as socket:
                delay = 1
                conflict_deadline = None
                print('扫描通道已连接；此通道不接受模型执行命令。', flush=True)
                await connected_session(socket)
        except InvalidStatus as error:
            if error.response.status_code == HTTPStatus.CONFLICT:
                if conflict_deadline is None:
                    conflict_deadline = monotonic() + CONNECTION_CONFLICT_RETRY_SECONDS
            elif error.response.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
                raise BridgeError('设备连接被拒绝，请检查设备授权、服务地址和桥接开关') from None
        except ConnectionClosed as error:
            if error.rcvd and error.rcvd.code in {4400, 4401, 4403, 4409, 4429}:
                raise BridgeError('设备授权已失效、连接被替代或协议被拒绝；请在网页检查设备') from None
        except InvalidHandshake:
            raise BridgeError('服务没有完成有效的设备协议握手，请检查 API 地址和代理配置') from None
        except (OSError, asyncio.TimeoutError):
            pass
        retry_delay = delay
        if conflict_deadline is not None:
            # Try again after the 20-second orphan lease expires, while still
            # bounding duplicate-instance waits and every handshake attempt.
            retry_delay = min(delay, 5, max(0, conflict_deadline - monotonic()))
        print(f'连接暂时中断，{retry_delay:g} 秒后重试。', flush=True)
        await asyncio.sleep(retry_delay)
        delay = min(delay * 2, 30)
