"""Opt-in single-run protocol; only explicit local CLI --execute flags enable it.

The caller supplies a trusted local driver and consent decision. Network data
cannot select an executable, argv, cwd, environment, or provider credentials.
Drivers must expose only public text and stop ALL owned processes in stop().
There is no automatic retry/reconnect of a model run or document mutation.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar
from uuid import UUID

from .client import BridgeError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

MAX_OFFER_BYTES = 2 * 1024 * 1024
MAX_REPLY_BYTES = 8 * 1024 * 1024
MAX_SEQUENCE = 2048
MAX_PUBLIC_CHARS = 100_000
KNOWN_TOOLS = frozenset({
    'update_plan', 'read_projection', 'read_document_detail', 'get_node_tags', 'search_tags', 'suggest_tags',
    'start_document', 'add_nodes', 'update_nodes', 'edit_node_text', 'edit_node_tags', 'add_comment',
    'move_nodes', 'remove_nodes', 'set_document_meta', 'validate_draft', 'complete_artifact',
})
_T = TypeVar('_T')


async def _bounded(operation: Awaitable[_T], timeout: float) -> _T:
    """Timeout without Python 3.10 wait_for's completed/cancelled race."""
    task = asyncio.ensure_future(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            raise asyncio.TimeoutError
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        settled = asyncio.gather(task, return_exceptions=True)
        interrupted = False
        while not settled.done():
            try:
                await asyncio.shield(settled)
            except asyncio.CancelledError:
                interrupted = True
        settled.result()
        if interrupted:
            raise asyncio.CancelledError


class RunProtocolError(BridgeError):
    def __init__(self) -> None:
        super().__init__('任务协议不兼容或连接中断；本轮不会自动重试')


class RunCleanupError(BridgeError):
    def __init__(self) -> None:
        super().__init__('尚未确认本机 Agent 已停止，请检查设备上的 CLI')


class RunFailure(BridgeError):
    MESSAGES = {
        'AI_PROVIDER_AUTH_FAILED': '本机 Agent 登录失效，请在设备终端完成登录',
        'AI_RATE_LIMITED': '本机 Agent 供应商请求受限',
        'AI_TIMEOUT': '本机 Agent 任务超时',
        'AI_AGENT_UNAVAILABLE': '本机 Agent 执行中断',
        'AI_CAPABILITY_UNSUPPORTED': '本机 Agent 的模型或受限执行能力未经验证，请检查配置',
        'AI_BUDGET_EXCEEDED': '本机 Agent 已达到预算限制，或无法验证本轮用量',
    }

    def __init__(self, code):
        self.code = code if code in self.MESSAGES else 'AI_AGENT_UNAVAILABLE'
        super().__init__(self.MESSAGES[self.code])


class RunStopped(BridgeError):
    def __init__(self) -> None:
        super().__init__('本轮任务已停止接收新操作')


class RunConnection(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


def _load(raw: str | bytes, limit: int) -> dict:
    try:
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
        if len(raw) > limit:
            raise ValueError
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        # Reject NaN/Infinity before this data can reach a model driver.
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RunProtocolError from None


@dataclass(frozen=True)
class RunOffer:
    run_id: str
    execution_epoch: int
    agent_key: str
    intent: str
    execution_mode: str
    prompt: str
    tools: tuple[dict, ...]
    max_budget_usd: float = 1.0
    timeout_seconds: int = 900
    model_ref: str | None = None

    @property
    def identity(self) -> dict:
        return {'protocolVersion': 1, 'runId': self.run_id, 'executionEpoch': self.execution_epoch}


def decode_offer(raw: str | bytes, *, agent_key: str) -> RunOffer:
    """Check the selected LOCAL Agent, not only the server-provided Agent key."""
    value = _load(raw, MAX_OFFER_BYTES)
    try:
        keys = {'protocolVersion', 'runId', 'executionEpoch', 'type', 'agentKey',
                'intent', 'executionMode', 'prompt', 'tools'}
        if set(value) not in (keys, keys | {'runtimePolicy'}):
            raise ValueError
        if (type(value['protocolVersion']) is not int or value['protocolVersion'] != 1
                or type(value['executionEpoch']) is not int or value['executionEpoch'] < 1
                or value['type'] != 'run' or str(UUID(value['runId'])) != value['runId']
                or agent_key not in {'claude', 'codex', 'kimi'} or value['agentKey'] != agent_key
                or value['executionMode'] not in {'preview', 'direct'}
                or not isinstance(value['intent'], str) or not re.fullmatch(r'[a-z_]{1,32}', value['intent'])
                or not isinstance(value['prompt'], str) or not value['prompt'].strip()
                or not isinstance(value['tools'], list) or len(value['tools']) > len(KNOWN_TOOLS)):
            raise ValueError
        allowed = KNOWN_TOOLS - {'complete_artifact' if value['executionMode'] == 'direct' else 'add_comment'}
        if value['intent'] == 'discuss':
            allowed = frozenset()
        names = set()
        for tool in value['tools']:
            if (not isinstance(tool, dict) or set(tool) != {'name', 'description', 'inputSchema'}
                    or tool['name'] not in allowed or tool['name'] in names
                    or not isinstance(tool['description'], str) or not isinstance(tool['inputSchema'], dict)):
                raise ValueError
            names.add(tool['name'])
        policy = value.get('runtimePolicy', {'maxBudgetUsd': 1.0, 'timeoutSeconds': 900, 'modelRef': None})
        if not isinstance(policy, dict) or set(policy) != {'maxBudgetUsd', 'timeoutSeconds', 'modelRef'}:
            raise ValueError
        budget, seconds, model = policy['maxBudgetUsd'], policy['timeoutSeconds'], policy['modelRef']
        if (type(budget) not in {float, int} or not math.isfinite(budget) or not 0.0001 <= budget <= 1000
                or type(seconds) is not int or not 30 <= seconds <= 900
                or (model is not None and (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', model)))):
            raise ValueError
        return RunOffer(value['runId'], value['executionEpoch'], agent_key, value['intent'],
                        value['executionMode'], value['prompt'], tuple(value['tools']), float(budget), seconds, model)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RunProtocolError from None


class RunDriver(Protocol):
    async def run(self, offer: RunOffer, channel: RunChannel) -> dict: ...
    async def stop(self) -> None:
        """Return only after proving every owned CLI process exited; otherwise raise."""
        ...


class RunChannel:
    """One reader, sequential RPCs, and an independent cancel signal."""

    def __init__(self, connection: RunConnection, offer: RunOffer, *, ack_timeout: float) -> None:
        self.connection = connection
        self.offer = offer
        self.ack_timeout = ack_timeout
        self.cancelled = asyncio.Event()
        self.accepting = True
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._pending: tuple[int, bool, asyncio.Future] | None = None
        self._abandoned: dict[int, bool] = {}
        self._public_chars = 0

    async def receive(self) -> None:
        while True:
            value = _load(await self.connection.recv(), MAX_REPLY_BYTES)
            identity = self.offer.identity
            if (any(type(value.get(key)) is not type(expected) or value[key] != expected
                    for key, expected in identity.items())):
                raise RunProtocolError
            if value.get('type') == 'cancel' and set(value) == {*identity, 'type'}:
                self.accepting = False
                self.cancelled.set()
                continue
            sequence = value.get('sequence')
            if value.get('type') != 'ack' or type(sequence) is not int:
                raise RunProtocolError
            if sequence in self._abandoned:
                is_tool = self._abandoned.pop(sequence)
                pending = None
            elif self._pending and self._pending[0] == sequence:
                _, is_tool, pending = self._pending
            else:
                raise RunProtocolError
            keys = {*identity, 'type', 'sequence'} | ({'toolResult'} if is_tool else set())
            if set(value) != keys or (is_tool and not isinstance(value['toolResult'], dict)):
                raise RunProtocolError
            if pending is not None:
                if pending.cancelled():
                    continue  # late ACK during cancellation of the waiting RPC
                if pending.done():
                    raise RunProtocolError
                pending.set_result(value.get('toolResult'))

    async def _exchange(self, kind: str, *, terminal: bool = False, **fields: Any) -> Any:
        async with self._lock:
            if not self.accepting and not terminal:
                raise RunStopped
            # Reserve the final sequence for stopped/failed/completed.
            if self._sequence >= MAX_SEQUENCE - (0 if terminal else 1):
                raise RunProtocolError
            sequence = self._sequence + 1
            payload = {**self.offer.identity, 'type': kind, 'sequence': sequence, **fields}
            try:
                encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode('utf-8')) > MAX_OFFER_BYTES:
                    raise ValueError
            except (ValueError, TypeError, RecursionError):
                raise RunProtocolError from None
            self._sequence = sequence
            future = asyncio.get_running_loop().create_future()
            is_tool = kind == 'tool_call'
            self._pending = (sequence, is_tool, future)
            try:
                await _bounded(self.connection.send(encoded), self.ack_timeout)
                return await _bounded(future, self.ack_timeout)
            except BaseException:
                # Even when send fails, bytes might have reached the peer. Do
                # not allow a driver to catch the error and continue mutating.
                self.accepting = False
                if not future.done() or future.cancelled():
                    self._abandoned[sequence] = is_tool
                raise
            finally:
                future.cancel()
                self._pending = None

    async def tool(self, name: str, arguments: dict) -> dict:
        if name not in {tool['name'] for tool in self.offer.tools} or not isinstance(arguments, dict):
            raise RunProtocolError
        return await self._exchange('tool_call', toolName=name, arguments=arguments)

    async def public_text(self, text: str, *, message_id: str, channel: str = 'assistant') -> None:
        """Only normalized, provider-public content; never pass raw SDK events."""
        if (not isinstance(text, str) or not text or channel not in {'assistant', 'thinking_summary'}
                or not re.fullmatch(r'[a-zA-Z0-9_:.-]{1,120}', message_id)):
            raise RunProtocolError
        self._public_chars += len(text)
        if self._public_chars > MAX_PUBLIC_CHARS:
            raise RunProtocolError
        for offset in range(0, len(text), 4000):
            await self._exchange('public_text', text=text[offset:offset + 4000], channel=channel, messageId=message_id)

    async def thinking(self) -> None:
        await self._exchange('thinking')

    async def heartbeat(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self._exchange('heartbeat')


async def _settle_driver(driver: RunDriver, tasks: list[asyncio.Task], timeout: float) -> None:
    for task in tasks:
        task.cancel()
    stop = asyncio.create_task(driver.stop())
    done, pending = await asyncio.wait([*tasks, stop], timeout=timeout)
    # Consume every completed exception; never leak provider diagnostics.
    cleanup_failed = stop not in done or (not stop.cancelled() and stop.exception() is not None) or stop.cancelled()
    for task in done:
        if not task.cancelled():
            task.exception()
    for task in pending:
        task.cancel()
        task.add_done_callback(lambda finished: None if finished.cancelled() else finished.exception())
    if pending or cleanup_failed:
        raise RunCleanupError


async def execute_run(
    connection: RunConnection, *, agent_key: str, driver: RunDriver,
    consent: Callable[[RunOffer], Awaitable[bool]], timeout: float = 900,
    ack_timeout: float = 15, heartbeat_interval: float = 5, stop_timeout: float = 4,
) -> str:
    """Run one explicitly enabled task; ordinary CLI `run` remains scan-only.

    Consent is local and mandatory. The trusted driver must own process cleanup;
    stop failure is NEVER represented as processStopped=true or normal cancel.
    """
    offer = decode_offer(await _bounded(connection.recv(), ack_timeout), agent_key=agent_key)
    if await consent(offer) is not True:
        raise BridgeError('本机未同意执行此任务')
    channel = RunChannel(connection, offer, ack_timeout=ack_timeout)
    receiver = asyncio.create_task(channel.receive())
    worker = asyncio.create_task(driver.run(offer, channel))
    heartbeat = asyncio.create_task(channel.heartbeat(heartbeat_interval))
    cancelled = asyncio.create_task(channel.cancelled.wait())
    failure: BaseException | None = None
    completion: dict | None = None
    try:
        done, _ = await asyncio.wait({worker, receiver, heartbeat, cancelled}, timeout=min(timeout, offer.timeout_seconds),
                                     return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise RunFailure('AI_TIMEOUT')
        if receiver in done:
            receiver.result()
            raise RunProtocolError
        if heartbeat in done:
            heartbeat.result()
            raise RunProtocolError
        if worker in done:
            completion = worker.result()
    except BaseException as exc:
        failure = exc
    finally:
        channel.accepting = False  # fence before awaiting cleanup

    async def finalize() -> str:
        try:
            await _settle_driver(driver, [worker, heartbeat], stop_timeout)
        except RunCleanupError:
            if not receiver.done():
                try:
                    await channel._exchange('failed', terminal=True, processStopped=False,
                                            errorCode='AI_AGENT_CLEANUP_FAILED')
                except Exception:
                    pass
            raise
        if receiver.done():
            raise RunProtocolError
        if channel.cancelled.is_set():
            kind, fields = 'stopped', {'processStopped': True}
        elif failure is not None or completion is None:
            code = failure.code if isinstance(failure, RunFailure) else 'AI_AGENT_UNAVAILABLE'
            kind, fields = 'failed', {'processStopped': True, 'errorCode': code}
        else:
            kind, fields = 'completed', {'processStopped': True, 'completion': completion}
        await channel._exchange(kind, terminal=True, **fields)
        return kind

    async def finish_and_close() -> str:
        try:
            return await finalize()
        finally:
            for task in (receiver, cancelled):
                task.cancel()
            await asyncio.gather(receiver, cancelled, return_exceptions=True)

    cleanup = asyncio.create_task(finish_and_close())
    # Repeated parent cancellation cannot abandon an owned process. A bounded
    # stop attempt and terminal acknowledgement finish before returning.
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as exc:
            failure = exc
        except Exception:
            break
    try:
        result = cleanup.result()
    except RunCleanupError:
        raise
    except Exception:
        raise RunProtocolError from None
    if isinstance(failure, asyncio.CancelledError):
        raise failure
    if isinstance(failure, RunFailure):
        raise failure
    if failure is not None:
        raise RunProtocolError from None
    return result
