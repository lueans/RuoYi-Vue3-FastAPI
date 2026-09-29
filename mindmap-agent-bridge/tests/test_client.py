"""Scan reconnect backoff uses a virtual clock, never real devices or waits."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.frames import Close

from mindmap_agent_bridge import client

CONFIG = {'server': 'https://example.test', 'deviceId': '11111111-1111-4111-8111-111111111111',
          'deviceSecret': 's' * 43}


class SessionDone(Exception):
    pass


@pytest.fixture
def reconnect(monkeypatch):
    state = SimpleNamespace(now=0, delays=[], attempts=[], outcomes=[], handshake_seconds=0, lease_expires_at=None,
                            session=AsyncMock(side_effect=SessionDone))

    async def sleep(seconds):
        state.delays.append(seconds)
        state.now += seconds

    @asynccontextmanager
    async def connect(*args, **kwargs):
        state.attempts.append((state.now, kwargs['open_timeout']))
        state.now += state.handshake_seconds
        status = state.outcomes.pop(0) if state.outcomes else 409
        if state.lease_expires_at is not None and state.now >= state.lease_expires_at:
            status = 200
        if status != 200:
            raise InvalidStatus(SimpleNamespace(status_code=status))
        yield object()

    monkeypatch.setattr(client, 'monotonic', lambda: state.now, raising=False)
    monkeypatch.setattr(client.asyncio, 'sleep', sleep)
    monkeypatch.setattr(client, 'NoRedirectConnect', connect)
    monkeypatch.setattr(client, 'connected_session', state.session)
    return state


@pytest.mark.asyncio
async def test_scan_retries_live_lease_conflict_then_connects(reconnect):
    reconnect.outcomes = [409, 200]
    with pytest.raises(SessionDone):
        await client.run(CONFIG)
    assert reconnect.delays == [1]
    assert len(reconnect.attempts) == 2
    reconnect.session.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_conflict_retry_budget_stops_without_stealing_or_retrying_forever(reconnect):
    with pytest.raises(client.BridgeError, match='已有在线桥接'):
        await client.run(CONFIG)
    assert reconnect.now == 25
    assert reconnect.delays == [1, 2, 4, 5, 5, 5, 3]
    assert [when for when, _ in reconnect.attempts] == [0, 1, 3, 7, 12, 17, 22]
    assert reconnect.attempts[-1][1] == 3
    reconnect.session.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_conflict_budget_includes_later_handshakes(reconnect):
    reconnect.handshake_seconds = 1
    with pytest.raises(client.BridgeError, match='已有在线桥接'):
        await client.run(CONFIG)
    # The first denial starts the 25-second window. Later attempts cannot
    # each add their full open timeout or sleep beyond that deadline.
    assert reconnect.now == 26
    assert reconnect.delays == [1, 2, 4, 5, 5, 3]
    assert reconnect.attempts[-1] == (22, 4)


@pytest.mark.asyncio
async def test_orphaned_lease_can_expire_naturally_before_retry_deadline(reconnect):
    reconnect.lease_expires_at = 20
    with pytest.raises(SessionDone):
        await client.run(CONFIG)
    assert reconnect.now == 22
    assert reconnect.delays == [1, 2, 4, 5, 5, 5]
    reconnect.session.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 429])
async def test_other_http_client_errors_remain_fatal(reconnect, status):
    reconnect.outcomes = [status]
    with pytest.raises(client.BridgeError, match='设备连接被拒绝'):
        await client.run(CONFIG)
    assert reconnect.delays == [] and len(reconnect.attempts) == 1
    reconnect.session.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_failures_without_conflict_keep_existing_backoff(reconnect):
    reconnect.outcomes = [503] * 6 + [200]
    with pytest.raises(SessionDone):
        await client.run(CONFIG)
    assert reconnect.delays == [1, 2, 4, 8, 16, 30]
    assert reconnect.now == 61


@pytest.mark.asyncio
async def test_successful_handshake_resets_conflict_budget_and_backoff(reconnect):
    reconnect.outcomes = [409, 200, 409, 200]
    sessions = 0
    async def session(_socket):
        nonlocal sessions
        sessions += 1
        if sessions == 1:
            reconnect.now += 40
            raise OSError('temporary disconnect')
        raise SessionDone
    reconnect.session.side_effect = session
    with pytest.raises(SessionDone):
        await client.run(CONFIG)
    assert reconnect.delays == [1, 1, 2]
    assert [when for when, _ in reconnect.attempts] == [0, 1, 42, 44]
    assert sessions == 2


@pytest.mark.asyncio
async def test_protocol_close_4409_still_fails_without_conflict_retry(reconnect):
    reconnect.outcomes = [200]
    reconnect.session.side_effect = ConnectionClosedError(Close(4409, 'conflict'), None)
    with pytest.raises(client.BridgeError, match='设备授权已失效'):
        await client.run(CONFIG)
    assert reconnect.delays == [] and len(reconnect.attempts) == 1
