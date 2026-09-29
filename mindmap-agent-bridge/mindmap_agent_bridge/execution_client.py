"""Explicitly enabled outbound execution; never replay a disconnected run."""

import asyncio
import json
from urllib.parse import urlsplit, urlunsplit

from websockets.exceptions import ConnectionClosed, InvalidHandshake

from .client import BridgeError, NoRedirectConnect, normalize_server, run
from .execution import MAX_REPLY_BYTES, RunFailure, RunProtocolError, _bounded, _load, execute_run

EXECUTION_AGENTS = frozenset({'claude', 'codex', 'kimi'})


def execution_handshake(agent_keys, accept_estimated_budget=False, accept_unmetered_budget=False):
    if (not isinstance(agent_keys, tuple) or not 1 <= len(agent_keys) <= len(EXECUTION_AGENTS)
            or any(not isinstance(key, str) or key not in EXECUTION_AGENTS for key in agent_keys)
            or len(set(agent_keys)) != len(agent_keys)):
        raise BridgeError('请选择已支持的本机执行 Agent')
    if 'codex' in agent_keys and accept_estimated_budget is not True:
        raise BridgeError('Codex 预算仅按已回报用量估算，可能超额；确认后需显式添加 --accept-estimated-budget')
    if 'kimi' in agent_keys and accept_unmetered_budget is not True:
        raise BridgeError('Kimi 无金额上限，仅限制时间与工具次数；确认后需显式添加 --accept-unmetered-budget')
    if agent_keys == ('claude',):
        return {'type': 'execute_ready', 'protocolVersion': 1, 'agentKey': 'claude'}
    hello = {'type': 'execute_ready', 'protocolVersion': 3 if 'kimi' in agent_keys else 2,
             'agentKeys': list(agent_keys),
             'codexBudgetPolicy': 'reported_usage_estimate' if 'codex' in agent_keys else None}
    if 'kimi' in agent_keys:
        hello['kimiBudgetPolicy'] = 'timeout_and_tool_limit'
    return hello


def local_drivers(agent_keys, *, accept_unmetered_budget=False):
    # Closed, lazy LOCAL factory; remote offers cannot import a module/path.
    drivers = {}
    for key in agent_keys:
        if key == 'claude':
            from .claude_driver import ClaudeRunDriver
            drivers[key] = ClaudeRunDriver()
        elif key == 'codex':
            from .codex_driver import CodexRunDriver
            drivers[key] = CodexRunDriver()
        elif key == 'kimi':
            from .kimi_driver import KimiRunDriver
            drivers[key] = KimiRunDriver(accept_unmetered_budget=accept_unmetered_budget)
        else:
            raise RunProtocolError
    return drivers


class OfferedConnection:
    """Keep the relay-finished control frame out of the per-run ACK reader."""
    def __init__(self, socket, offer):
        self.socket, self.offer = socket, offer
        self.terminal = None
        self.terminal_acked = False

    async def send(self, message):
        value = _load(message, MAX_REPLY_BYTES)
        if value.get('type') in {'completed', 'stopped', 'failed'}:
            self.terminal = value
            self.terminal_acked = False
        await self.socket.send(message)

    async def recv(self):
        if self.offer is not None:
            offer, self.offer = self.offer, None
            return offer
        if self.terminal_acked:
            await asyncio.Future()  # cancelled by execute_run's single-reader cleanup
        raw = await self.socket.recv()
        value = _load(raw, MAX_REPLY_BYTES)
        if self.terminal is not None:
            expected = {key: self.terminal[key] for key in ('protocolVersion', 'runId', 'executionEpoch', 'sequence')}
            expected['type'] = 'ack'
            if value == expected and all(type(value[key]) is type(item) for key, item in expected.items()):
                self.terminal_acked = True
        return raw


async def connected_execution(socket, driver, *, agent_keys=('claude',), accept_estimated_budget=False,
                              accept_unmetered_budget=False):
    hello = execution_handshake(agent_keys, accept_estimated_budget, accept_unmetered_budget)
    await socket.send(json.dumps(hello))
    welcome = _load(await _bounded(socket.recv(), 15), MAX_REPLY_BYTES)
    if welcome != {**hello, 'type': 'execute_welcome'} or type(welcome.get('protocolVersion')) is not int:
        raise RunProtocolError

    async def heartbeat():
        while True:
            await asyncio.sleep(5)
            await socket.send('{"type":"idle_heartbeat","protocolVersion":1}')

    keepalive = asyncio.create_task(heartbeat())
    waiting = asyncio.create_task(socket.recv())
    try:
        done, _ = await asyncio.wait({keepalive, waiting}, return_when=asyncio.FIRST_COMPLETED)
        if keepalive in done:
            keepalive.result()
            raise RunProtocolError
        offer = waiting.result()
    finally:
        for task in (keepalive, waiting):
            task.cancel()
        await asyncio.gather(keepalive, waiting, return_exceptions=True)

    async def consent(_offer):
        # Entered ONLY by explicitly enabled local --execute flags, never via an
        # enrollment response, server capability advertisement or config file.
        return True

    key = _load(offer, MAX_REPLY_BYTES).get('agentKey')
    if not isinstance(key, str) or key not in agent_keys:
        raise RunProtocolError
    selected = driver.get(key) if isinstance(driver, dict) else (driver if agent_keys == ('claude',) else None)
    if selected is None:
        raise RunProtocolError
    connection = OfferedConnection(socket, offer)
    try:
        result = await execute_run(connection, agent_key=key, driver=selected, consent=consent)
    except RunFailure as error:
        terminal = connection.terminal or {}
        if not (connection.terminal_acked and terminal.get('type') == 'failed'
                and terminal.get('processStopped') is True and terminal.get('errorCode') == error.code):
            raise
        # A confirmed single-run failure doesn't revoke local Agent consent.
        # Still require the relay fence before opening a NEW idle connection.
        result = 'failed'
    finished = _load(await _bounded(socket.recv(), 15), MAX_REPLY_BYTES)
    if finished != {'type': 'relay_finished', 'protocolVersion': 1} or type(finished['protocolVersion']) is not int:
        raise RunProtocolError
    return result


async def run_execution(config, *, agent_keys=('claude',), accept_estimated_budget=False, accept_unmetered_budget=False):
    execution_handshake(agent_keys, accept_estimated_budget, accept_unmetered_budget)
    parsed = urlsplit(normalize_server(config['server']))
    url = urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', parsed.netloc,
                     parsed.path + '/mindmap/ai/device-bridge/execute/' + config['deviceId'], '', ''))
    while True:
        drivers = local_drivers(agent_keys, accept_unmetered_budget=accept_unmetered_budget)
        try:
            async with NoRedirectConnect(
                url, additional_headers={'Authorization': 'Bearer ' + config['deviceSecret']},
                proxy=None, max_size=MAX_REPLY_BYTES, open_timeout=10, close_timeout=3,
            ) as socket:
                await connected_execution(socket, drivers, agent_keys=agent_keys,
                                          accept_estimated_budget=accept_estimated_budget,
                                          accept_unmetered_budget=accept_unmetered_budget)
        except (ConnectionClosed, InvalidHandshake, OSError, asyncio.TimeoutError):
            raise BridgeError('本机执行连接已中断；不会自动重跑任务，请检查网页状态后手动重新连接') from None
        # Only a stopped + acknowledged run reaches here. This is a new idle
        # socket, not a reconnect/resume of the previous model invocation.


async def run_with_execution(config, *, agent_keys=('claude',), accept_estimated_budget=False, accept_unmetered_budget=False):
    execution_handshake(agent_keys, accept_estimated_budget, accept_unmetered_budget)
    try:
        from .run_recovery import recover_runs, RecoveryError
        from .process_owner import shield_cleanup
    except ImportError:
        raise BridgeError('本机执行需要先安装所选 Agent 的可选依赖') from None
    print('正在核验上次本机任务的退出状态…', flush=True)
    try:
        recovery = await shield_cleanup(asyncio.create_task(recover_runs()))
    except RecoveryError:
        raise BridgeError('本机运行记录无法安全读取；未建立执行连接，请检查桥接私有运行目录') from None
    if recovery['unresolved']:
        raise BridgeError(f"发现 {recovery['unresolved']} 个无法确认清理的本机任务；已保留运行记录，未建立执行连接，请检查后重试")
    if recovery['recovered']:
        print(f"已确认清理 {recovery['recovered']} 个中断任务及其私有目录；不会恢复或重跑旧任务。", flush=True)
    print(f'已显式启用 {", ".join(agent_keys)}：接受本人平台任务，使用本机登录和模型额度；Ctrl+C 停止。', flush=True)
    if 'codex' in agent_keys:
        print('Codex 按已回报用量估算预算，非硬费用上限，可能超额；不代表订阅账单。', flush=True)
    if 'kimi' in agent_keys:
        print('Kimi 不执行金额预算上限，仅限制时间与工具次数；使用本机登录额度。每轮使用私有回环 MCP 端口。', flush=True)
    tasks = [asyncio.create_task(run(config)), asyncio.create_task(run_execution(
        config, agent_keys=agent_keys, accept_estimated_budget=accept_estimated_budget,
        accept_unmetered_budget=accept_unmetered_budget,
    ))]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        settled = asyncio.gather(*tasks, return_exceptions=True)
        # execute_run owns bounded process cleanup even on repeated Ctrl+C.
        while not settled.done():
            try:
                await asyncio.shield(settled)
            except asyncio.CancelledError:
                pass
        results = settled.result()
        from .execution import RunCleanupError
        if any(isinstance(result, RunCleanupError) for result in results):
            raise RunCleanupError
