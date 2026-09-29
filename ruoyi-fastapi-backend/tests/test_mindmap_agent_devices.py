"""Companion protocol and optional SQLite-only enrollment/lease integration."""

import asyncio
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from config.env import MindmapAiConfig
from module_admin.entity.do.user_do import SysUser
from module_mindmap.controller import mindmap_ai_device_controller as controller
from module_mindmap.entity.do.mindmap_ai_device_do import MindmapAiDevice
from module_mindmap.entity.vo.mindmap_ai_device_vo import DeviceEnrollment, DeviceFrame
from module_mindmap.service.mindmap_ai_device_service import (
    MAX_ACTIVE_DEVICES,
    ONLINE_TTL_SECONDS,
    MindmapAiDeviceService as Service,
    device_view,
    secret_digest,
)

DEVICE_ID = '11111111-1111-4111-8111-111111111111'
DEVICE_SECRET = 'd' * 43
PAIR_SECRET = 'p' * 43
CONNECTION_ID = 'owned-connection'
DB_TEST = pytest.mark.skipif(os.getenv('MINDMAP_DB_INTEGRATION') != '1', reason='explicit SQLite integration opt-in')


def scan_frame(revision=1):
    return DeviceFrame.model_validate({
        'type': 'scan_result', 'scanRevision': revision,
        'runtimes': [{'agentKey': key, 'installed': True, 'version': '1.2.3', 'status': 'detected'}
                     for key in ('claude', 'codex', 'kimi')],
    })


@pytest.mark.parametrize('payload', [
    {'type': 'execute', 'command': 'do not run'}, {'type': 'heartbeat', 'protocolVersion': True},
    {'type': 'scan_result', 'scanRevision': True}, {'type': 'heartbeat', 'filePath': '/private/path'},
    {'type': 'scan_result', 'runtimes': [{'agentKey': 'custom', 'installed': True, 'status': 'detected'}]},
    {'type': 'scan_result', 'runtimes': [{'agentKey': 'claude', 'installed': True, 'status': 'ready'}]},
    {'type': 'scan_result', 'runtimes': [{'agentKey': 'claude', 'installed': 'yes', 'status': 'detected'}]},
    {'type': 'scan_result', 'runtimes': [{'agentKey': 'claude', 'installed': True, 'status': 'detected', 'apiKey': 'secret'}]},
])
def test_closed_protocol_rejects_remote_commands_credentials_and_invented_readiness(payload):
    with pytest.raises(ValidationError):
        DeviceFrame.model_validate(payload)


def test_device_view_never_returns_credentials_and_distinguishes_offline():
    now = datetime.now()
    record = SimpleNamespace(
        id=DEVICE_ID, name='我的电脑', status='active', pairing_expires_time=now + timedelta(minutes=1),
        credential_expires_time=now + timedelta(days=1), connection_id=CONNECTION_ID,
        last_seen_time=now, last_scan_time=None, scan_requested=1, scan_completed=0,
        runtimes_json=None, credential_hash='private-digest', pairing_hash='private-pairing',
    )
    view = device_view(record, now=now)
    assert view['status'] == 'online' and view['executionAvailable'] is False
    assert 'private' not in json.dumps(view)
    record.last_seen_time = now - timedelta(seconds=21)
    assert device_view(record, now=now)['status'] == 'offline'
    record.credential_expires_time = now
    assert device_view(record, now=now)['status'] == 'credential_expired'
    record.status = 'revoked'
    assert device_view(record, now=now)['status'] == 'revoked'


@pytest.mark.asyncio
async def test_duplicate_connection_preserves_live_lease_and_scan_revision(monkeypatch):
    device = SimpleNamespace(connection_id=CONNECTION_ID, last_seen_time=datetime.now(),
                             scan_requested=3, scan_completed=3)
    monkeypatch.setattr(Service, 'authenticate', AsyncMock(return_value=device))
    db = SimpleNamespace(commit=AsyncMock())
    seen = device.last_seen_time
    with pytest.raises(HTTPException) as error:
        await Service.connect(db, DEVICE_ID, DEVICE_SECRET)
    assert error.value.status_code == 409
    assert error.value.headers == {'Retry-After': str(ONLINE_TTL_SECONDS)}
    assert device.connection_id == CONNECTION_ID and device.last_seen_time == seen
    assert device.scan_requested == device.scan_completed == 3
    db.commit.assert_not_awaited()
    # The existing socket remains authorized after the rejected connection.
    assert (await Service.receive(db, DEVICE_ID, DEVICE_SECRET, CONNECTION_ID,
                                  DeviceFrame(type='heartbeat')))['scanRevision'] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('connection_id,age', [(None, 0), (CONNECTION_ID, ONLINE_TTL_SECONDS + 1)])
async def test_disconnected_or_expired_lease_can_reconnect(monkeypatch, connection_id, age):
    device = SimpleNamespace(connection_id=connection_id, last_seen_time=datetime.now() - timedelta(seconds=age),
                             scan_requested=3, scan_completed=3)
    monkeypatch.setattr(Service, 'authenticate', AsyncMock(return_value=device))
    db = SimpleNamespace(commit=AsyncMock())
    replacement = await Service.connect(db, DEVICE_ID, DEVICE_SECRET)
    assert replacement != CONNECTION_ID and device.connection_id == replacement
    assert device.scan_requested == 4
    db.commit.assert_awaited_once()


class FakeSocket:
    def __init__(self, frames, headers=None):
        self.frames = list(frames)
        self.headers = headers or {'authorization': 'Bearer ' + DEVICE_SECRET}
        self.close = AsyncMock()
        self.accept = AsyncMock()
        self.send_json = AsyncMock()
        self.send_denial_response = AsyncMock()

    async def receive_text(self):
        from fastapi import WebSocketDisconnect
        if not self.frames:
            raise WebSocketDisconnect
        return self.frames.pop(0)


class FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        pass


@pytest.fixture
def socket_service(monkeypatch):
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_bridge_enabled', True)
    monkeypatch.setattr(controller, 'AsyncSessionLocal', FakeSessionContext)
    mocks = {name: AsyncMock(return_value=value) for name, value in {
        'connect': CONNECTION_ID, 'receive': {'type': 'state'}, 'disconnect': None,
    }.items()}
    for name, mock in mocks.items():
        monkeypatch.setattr(Service, name, mock)
    return mocks


@pytest.mark.asyncio
async def test_transport_bounds_frames_rejects_commands_and_fences_cleanup(socket_service):
    socket = FakeSocket([json.dumps({'type': 'heartbeat'}), json.dumps({'type': 'execute', 'command': 'bad'})])
    await controller.connect_device(socket, DEVICE_ID)
    assert socket_service['receive'].await_count == 1
    socket.close.assert_awaited_once_with(code=4400)
    assert socket_service['disconnect'].await_args.args[1:] == (DEVICE_ID, CONNECTION_ID)
    socket = FakeSocket(['x' * (controller.MAX_FRAME_BYTES + 1)])
    await controller.connect_device(socket, DEVICE_ID)
    socket.close.assert_awaited_once_with(code=1009)


@pytest.mark.asyncio
async def test_transport_rejects_browser_origin_before_authentication(socket_service):
    socket = FakeSocket([], headers={'authorization': 'Bearer ' + DEVICE_SECRET, 'origin': 'https://example.com'})
    await controller.connect_device(socket, DEVICE_ID)
    socket_service['connect'].assert_not_awaited()
    socket.accept.assert_not_awaited()
    socket.close.assert_awaited_once_with(code=4401)


@pytest.mark.asyncio
async def test_live_lease_conflict_has_retryable_handshake_status(socket_service):
    socket_service['connect'].side_effect = HTTPException(409, '在线桥接', headers={'Retry-After': '20'})
    socket = FakeSocket([])
    await controller.connect_device(socket, DEVICE_ID)
    denial = socket.send_denial_response.await_args.args[0]
    assert denial.status_code == 409 and denial.headers['retry-after'] == '20'
    assert denial.body == b''
    socket.accept.assert_not_awaited()
    socket.close.assert_not_awaited()
    socket_service['disconnect'].assert_not_awaited()


@pytest.mark.asyncio
async def test_transport_rate_limit_and_connection_takeover(socket_service):
    socket = FakeSocket([json.dumps({'type': 'heartbeat'})] * (controller.MAX_FRAMES_PER_WINDOW + 1))
    await controller.connect_device(socket, DEVICE_ID)
    socket.close.assert_awaited_once_with(code=4429)
    socket_service['receive'].side_effect = HTTPException(409, 'replacement')
    socket = FakeSocket([json.dumps({'type': 'heartbeat'})])
    await controller.connect_device(socket, DEVICE_ID)
    socket.close.assert_awaited_once_with(code=4409)


@pytest.mark.asyncio
async def test_python310_receive_timeout_closes_and_releases_connection(socket_service):
    socket = FakeSocket([])
    socket.receive_text = AsyncMock(side_effect=asyncio.TimeoutError)
    await controller.connect_device(socket, DEVICE_ID)
    socket.close.assert_awaited_once_with(code=4408)
    socket_service['disconnect'].assert_awaited_once()


@pytest.mark.asyncio
async def test_enrollment_validation_never_echoes_submitted_secret(monkeypatch):
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_bridge_enabled', True)
    class Request:
        async def stream(self):
            yield json.dumps({'deviceId': 'bad', 'pairingSecret': PAIR_SECRET, 'deviceSecret': DEVICE_SECRET}).encode()
    with pytest.raises(HTTPException) as error:
        await controller.enroll_device.__wrapped__(Request(), object())
    assert error.value.status_code == 400
    assert PAIR_SECRET not in str(error.value) and DEVICE_SECRET not in str(error.value)


class SqliteSession:
    """Async-shaped adapter around an explicitly in-memory synchronous test DB."""
    def __init__(self, engine):
        self.session = Session(engine, expire_on_commit=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.session.close()

    async def execute(self, statement):
        return self.session.execute(statement)

    def add(self, value):
        self.session.add(value)

    async def commit(self):
        self.session.commit()


@pytest.fixture
def database():
    # Never uses config.database's configured engine or application data.
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    SysUser.__table__.create(engine)
    MindmapAiDevice.__table__.create(engine)
    with Session(engine) as db:
        db.add(SysUser(user_id=7, user_name='test', nick_name='测试', status='0', del_flag='0'))
        db.commit()
    yield engine
    engine.dispose()


async def pair(database):
    async with SqliteSession(database) as db:
        issued = await Service.create_pairing(db, 7, '用户电脑')
        identifier, secret = issued['pairingCode'].split('.')
        enrollment = DeviceEnrollment.model_validate({'deviceId': identifier, 'pairingSecret': secret,
                                                     'deviceSecret': DEVICE_SECRET})
        await Service.enroll(db, enrollment)
    return identifier, enrollment


@DB_TEST
@pytest.mark.asyncio
async def test_real_sql_pairing_hashes_idempotency_owner_isolation_and_revoke(database):
    identifier, enrollment = await pair(database)
    async with SqliteSession(database) as db:
        row = db.session.get(MindmapAiDevice, identifier)
        assert row.credential_hash == secret_digest(DEVICE_SECRET)
        assert row.pairing_hash == secret_digest(enrollment.pairing_secret.get_secret_value())
        await Service.enroll(db, enrollment)  # lost-response retry retains exact key
        stolen = enrollment.model_dump(by_alias=True)
        stolen['deviceSecret'] = 'z' * 43
        with pytest.raises(HTTPException):
            await Service.enroll(db, DeviceEnrollment.model_validate(stolen))
        assert await Service.list_devices(db, 8) == []
        with pytest.raises(HTTPException) as error:
            await Service.revoke(db, 8, identifier)
        assert error.value.status_code == 404
        await Service.revoke(db, 7, identifier)
        with pytest.raises(HTTPException):
            await Service.authenticate(db, identifier, DEVICE_SECRET)
        with pytest.raises(HTTPException):
            await Service.enroll(db, enrollment)


@DB_TEST
@pytest.mark.asyncio
async def test_real_sql_connections_scan_revisions_and_stale_disconnect(database):
    identifier, _ = await pair(database)
    async with SqliteSession(database) as db:
        first = await Service.connect(db, identifier, DEVICE_SECRET)
        with pytest.raises(HTTPException) as error:
            await Service.connect(db, identifier, DEVICE_SECRET)
        assert error.value.status_code == 409
        row = db.session.get(MindmapAiDevice, identifier)
        assert row.connection_id == first and row.scan_requested == 1
        # A lost worker's expired lease can be replaced; its late cleanup must
        # still be fenced from the successor.
        row.last_seen_time = datetime.now() - timedelta(seconds=ONLINE_TTL_SECONDS + 1)
        await db.commit()
        second = await Service.connect(db, identifier, DEVICE_SECRET)
        with pytest.raises(HTTPException) as error:
            await Service.receive(db, identifier, DEVICE_SECRET, first, DeviceFrame(type='heartbeat'))
        assert error.value.status_code == 409
        await Service.disconnect(db, identifier, first)
        result = await Service.receive(db, identifier, DEVICE_SECRET, second, scan_frame())
        assert result['scanRevision'] == 1
        await Service.request_scan(db, 7, identifier)
        await Service.request_scan(db, 7, identifier)  # clicks coalesce
        result = await Service.receive(db, identifier, DEVICE_SECRET, second, scan_frame())
        assert result['scanRevision'] == 2
        with pytest.raises(HTTPException):
            await Service.receive(db, identifier, DEVICE_SECRET, second, scan_frame(3))
        await Service.receive(db, identifier, DEVICE_SECRET, second, scan_frame(2))
        view = (await Service.list_devices(db, 7))[0]
        assert view['status'] == 'online' and view['scanPending'] is False
        assert all(runtime['authenticationStatus'] == 'unknown' for runtime in view['runtimes'])
        await Service.disconnect(db, identifier, second)
        with pytest.raises(HTTPException):
            await Service.request_scan(db, 7, identifier)
        third = await Service.connect(db, identifier, DEVICE_SECRET)
        result = await Service.receive(db, identifier, DEVICE_SECRET, third, DeviceFrame(type='heartbeat'))
        assert result['scanRevision'] == 3  # reconnect refreshes installations
        await Service.receive(db, identifier, DEVICE_SECRET, third, scan_frame(3))
        assert (await Service.list_devices(db, 7))[0]['scanPending'] is False


@DB_TEST
@pytest.mark.asyncio
async def test_usable_device_cannot_be_hidden_by_expired_pairing_history(database):
    from uuid import uuid4
    identifier, _ = await pair(database)
    async with SqliteSession(database) as db:
        now = datetime.now()
        for index in range(55):
            db.add(MindmapAiDevice(
                id=str(uuid4()), user_id=7, name='过期配对', status='pending',
                pairing_expires_time=now - timedelta(seconds=1), credential_expires_time=now,
                created_time=now + timedelta(seconds=index), scan_requested=1, scan_completed=0,
            ))
        await db.commit()
        devices = await Service.list_devices(db, 7)
        assert len(devices) == 50
        assert devices[0]['deviceId'] == identifier


@DB_TEST
@pytest.mark.asyncio
async def test_real_sql_expiry_disabled_owner_and_device_limit(database):
    identifier, enrollment = await pair(database)
    async with SqliteSession(database) as db:
        row = db.session.get(MindmapAiDevice, identifier)
        row.pairing_expires_time = datetime.now() - timedelta(seconds=1)
        await db.commit()
        with pytest.raises(HTTPException):
            await Service.enroll(db, enrollment)
        for _ in range(MAX_ACTIVE_DEVICES - 1):
            await Service.create_pairing(db, 7, '另一个设备')
        with pytest.raises(HTTPException) as error:
            await Service.create_pairing(db, 7, '超过数量')
        assert error.value.status_code == 409
        row.credential_expires_time = datetime.now() - timedelta(seconds=1)
        await db.commit()
        with pytest.raises(HTTPException):
            await Service.authenticate(db, identifier, DEVICE_SECRET)
        db.session.get(SysUser, 7).status = '1'
        await db.commit()
        with pytest.raises(HTTPException):
            await Service.create_pairing(db, 7, '禁止')


@DB_TEST
@pytest.mark.asyncio
async def test_fastapi_websocket_uses_real_device_lease_and_reports_scan(database, monkeypatch):
    identifier, _ = await pair(database)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_bridge_enabled', True)
    monkeypatch.setattr(controller, 'AsyncSessionLocal', lambda: SqliteSession(database))
    app = FastAPI()
    app.include_router(controller.mindmap_ai_bridge_controller)
    with TestClient(app) as client:
        with client.websocket_connect('/mindmap/ai/device-bridge/connect/' + identifier,
                                      headers={'Authorization': 'Bearer ' + DEVICE_SECRET}) as socket:
            assert socket.receive_json()['type'] == 'welcome'
            socket.send_json(scan_frame().model_dump(by_alias=True))
            assert socket.receive_json()['scanRevision'] == 1
            with Session(database) as db:
                record = db.execute(select(MindmapAiDevice)).scalar_one()
                assert record.scan_completed == 1
                assert 'deviceSecret' not in record.runtimes_json
    async with SqliteSession(database) as db:
        assert (await Service.list_devices(db, 7))[0]['status'] == 'offline'
