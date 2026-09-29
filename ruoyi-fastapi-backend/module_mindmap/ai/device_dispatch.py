"""Bounded, fenced Redis mailboxes between a job worker and ONE device run.

Redis is transport, never the authority for document writes. A fresh socket is
required for each run; losing a socket never reoffers that run to another one.
All keys share a device hash tag for Redis Cluster's script key constraints.
"""

import json
from dataclasses import asdict
from uuid import UUID, uuid4

from redis.asyncio import Redis

from module_mindmap.ai.device_run_session import (
    MAX_DEVICE_REPLY_BYTES,
    MAX_DEVICE_RUN_FRAME_BYTES,
    DeviceRunBinding,
)
from module_mindmap.ai.device_runtime import DEVICE_RUNTIME_KEYS, execution_agents
from module_mindmap.ai.document import MindmapArtifactError

CONNECTION_TTL = 20
QUEUE_TTL = 30
MAX_QUEUE_MESSAGES = 8
MAX_QUEUE_BYTES = 16 * 1024 * 1024
FINISHED = '{"type":"relay_finished","protocolVersion":1}'

_OPEN = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], 'connection', ARGV[1], 'user', ARGV[2],
           'agent', ARGV[3], 'agents', ARGV[5], 'phase', 'available', 'binding', '', 'inBytes', 0, 'outBytes', 0)
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""
_MATCH = """
if redis.call('HGET', KEYS[1], 'connection') ~= ARGV[1] then return -1 end
if ARGV[2] ~= '' and redis.call('HGET', KEYS[1], 'binding') ~= ARGV[2] then return -1 end
"""
_RESERVE = _MATCH + """
local agents = redis.call('HGET', KEYS[1], 'agents')
local permitted = false
if agents then
  for _, agent in ipairs(cjson.decode(agents)) do
    if agent == ARGV[4] then permitted = true end
  end
else
  permitted = redis.call('HGET', KEYS[1], 'agent') == ARGV[4]
end
if redis.call('HGET', KEYS[1], 'user') ~= ARGV[3]
   or not permitted
   or redis.call('HGET', KEYS[1], 'phase') ~= 'available' then return -1 end
redis.call('HSET', KEYS[1], 'binding', ARGV[5], 'phase', 'busy')
return 1
"""
_PUSH = _MATCH + """
if redis.call('HGET', KEYS[1], 'phase') ~= 'busy' then return -1 end
local size = tonumber(redis.call('HGET', KEYS[1], ARGV[3]) or '0') + string.len(ARGV[4])
if redis.call('LLEN', KEYS[2]) >= tonumber(ARGV[5]) or size > tonumber(ARGV[6]) then return -2 end
redis.call('RPUSH', KEYS[2], ARGV[4])
redis.call('HSET', KEYS[1], ARGV[3], size)
redis.call('EXPIRE', KEYS[2], ARGV[7])
redis.call('LPUSH', KEYS[3], '1')
redis.call('LTRIM', KEYS[3], 0, 0)
redis.call('EXPIRE', KEYS[3], ARGV[7])
return 1
"""
_POP = _MATCH + """
local value = redis.call('LPOP', KEYS[2])
if not value then return '' end
redis.call('HINCRBY', KEYS[1], ARGV[3], -string.len(value))
return value
"""
_TOUCH = _MATCH + """
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""
_CLOSE = _MATCH + """
redis.call('DEL', KEYS[1], KEYS[2], KEYS[3], KEYS[4], KEYS[5])
return 1
"""


def unavailable() -> MindmapArtifactError:
    return MindmapArtifactError('本机执行连接不可用或已被占用，请检查设备', code='AI_AGENT_UNAVAILABLE')


def _binding(binding: DeviceRunBinding) -> str:
    return json.dumps(asdict(binding), sort_keys=True, separators=(',', ':'))


class DeviceDispatch:
    def __init__(self, redis: Redis | None, device_id: str) -> None:
        if redis is None or str(UUID(device_id)) != device_id:
            raise unavailable()
        self.redis = redis
        self.device_id = device_id
        self.key = f'mindmap:ai:device-execution:{{{device_id}}}'

    def _keys(self, connection_id: str) -> list[str]:
        if str(UUID(connection_id)) != connection_id:
            raise unavailable()
        prefix = f'{self.key}:{connection_id}'
        return [self.key, f'{prefix}:in', f'{prefix}:out', f'{prefix}:in:wake', f'{prefix}:out:wake']

    async def open(self, user_id: int, agent_key: str | tuple[str, ...]) -> str:
        agents = (agent_key,) if isinstance(agent_key, str) else agent_key
        if (type(user_id) is not int or user_id < 1 or not isinstance(agents, tuple)
                or not 1 <= len(agents) <= len(DEVICE_RUNTIME_KEYS)
                or any(not isinstance(agent, str) or agent not in DEVICE_RUNTIME_KEYS for agent in agents)
                or len(set(agents)) != len(agents)):
            raise unavailable()
        connection_id = str(uuid4())
        if await self.redis.eval(_OPEN, 1, self.key, connection_id, user_id,
                                 agents[0] if len(agents) == 1 else '', CONNECTION_TTL, json.dumps(agents)) != 1:
            raise unavailable()
        return connection_id

    async def state(self) -> dict:
        return await self.redis.hgetall(self.key)

    async def available(self, user_id: int, agent_key: str = 'claude') -> bool:
        state = await self.state()
        return (state.get('user') == str(user_id) and agent_key in execution_agents(state)
                and state.get('phase') == 'available')

    async def touch(self, connection_id: str) -> None:
        if await self.redis.eval(_TOUCH, 1, self.key, connection_id, '', CONNECTION_TTL) != 1:
            raise unavailable()

    async def reserve(self, *, job_id: str, user_id: int, epoch: int, agent_key: str = 'claude') -> DeviceRunBinding:
        if agent_key not in DEVICE_RUNTIME_KEYS:
            raise unavailable()
        state = await self.state()
        try:
            binding = DeviceRunBinding(str(uuid4()), job_id, user_id, self.device_id,
                                       epoch, state.get('connection', ''), agent_key)
        except ValueError:
            raise unavailable() from None
        if await self.redis.eval(_RESERVE, 1, self.key, binding.connection_id, '', user_id,
                                 binding.agent_key, _binding(binding)) != 1:
            raise unavailable()
        return binding

    async def owns(self, binding: DeviceRunBinding) -> bool:
        state = await self.state()
        return state.get('binding') == _binding(binding) and state.get('connection') == binding.connection_id

    async def push(self, connection_id: str, direction: str, raw: str, *, binding: DeviceRunBinding | None = None) -> None:
        if direction not in {'in', 'out'} or not isinstance(raw, str):
            raise unavailable()
        limit = MAX_DEVICE_RUN_FRAME_BYTES if direction == 'in' else MAX_DEVICE_REPLY_BYTES
        if len(raw.encode()) > limit:
            raise unavailable()
        keys = self._keys(connection_id)
        result = await self.redis.eval(
            _PUSH, 3, keys[0], keys[1 if direction == 'in' else 2], keys[3 if direction == 'in' else 4], connection_id,
            _binding(binding) if binding else '', direction + 'Bytes', raw,
            MAX_QUEUE_MESSAGES, MAX_QUEUE_BYTES, QUEUE_TTL,
        )
        if result != 1:
            raise unavailable()

    async def pop(self, connection_id: str, direction: str, *, binding: DeviceRunBinding | None = None) -> str:
        if direction not in {'in', 'out'}:
            raise unavailable()
        keys = self._keys(connection_id)
        while True:
            value = await self.redis.eval(_POP, 2, keys[0], keys[1 if direction == 'in' else 2],
                                          connection_id, _binding(binding) if binding else '', direction + 'Bytes')
            if value == -1:
                raise unavailable()
            if value:
                return value
            # Wakeups contain no data and coalesce to one item. A bounded
            # blocking wait avoids fixed polling latency on every text chunk;
            # always POP through the identity fence after waking or timing out.
            await self.redis.blpop(keys[3 if direction == 'in' else 4], timeout=1)

    async def close(self, connection_id: str) -> None:
        # A stale finally block cannot close a replacement connection.
        await self.redis.eval(_CLOSE, 5, *self._keys(connection_id), connection_id, '')


class DispatchedRunConnection:
    def __init__(self, dispatch: DeviceDispatch, binding: DeviceRunBinding) -> None:
        self.dispatch, self.binding = dispatch, binding

    async def send(self, raw: str) -> None:
        await self.dispatch.push(self.binding.connection_id, 'out', raw, binding=self.binding)

    async def recv(self) -> str:
        return await self.dispatch.pop(self.binding.connection_id, 'in', binding=self.binding)

    async def finish(self) -> None:
        await self.send(FINISHED)
