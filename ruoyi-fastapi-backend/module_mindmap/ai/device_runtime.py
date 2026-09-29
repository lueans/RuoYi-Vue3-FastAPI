"""Closed device execution catalogue, distinct from scan-only discoveries."""

import json

from config.env import MindmapAiConfig

DEVICE_AGENT_KEYS = {'device_claude': 'claude', 'device_codex': 'codex', 'device_kimi': 'kimi'}
DEVICE_RUNTIME_KEYS = frozenset(DEVICE_AGENT_KEYS.values())
CODEX_BUDGET_POLICY = 'reported_usage_estimate'
MULTI_AGENT_HANDSHAKE_VERSION = 2
KIMI_HANDSHAKE_VERSION = 3
KIMI_BUDGET_POLICY = 'timeout_and_tool_limit'


def device_runtime_enabled(runtime: str) -> bool:
    return bool(MindmapAiConfig.mindmap_ai_device_bridge_enabled
                and MindmapAiConfig.mindmap_ai_device_execution_enabled
                and runtime in DEVICE_RUNTIME_KEYS
                and (runtime != 'codex' or MindmapAiConfig.mindmap_ai_device_codex_enabled)
                and (runtime != 'kimi' or MindmapAiConfig.mindmap_ai_device_kimi_enabled))


def execution_agents(state: dict) -> tuple[str, ...]:
    """Read the fenced Redis connection, never infer readiness from a scan."""
    try:
        raw = state.get('agents')
        values = json.loads(raw) if raw is not None else [state.get('agent')]
        if (not isinstance(values, list) or not 1 <= len(values) <= len(DEVICE_RUNTIME_KEYS)
                or any(not isinstance(value, str) or value not in DEVICE_RUNTIME_KEYS for value in values)
                or len(set(values)) != len(values)):
            return ()
        return tuple(values)
    except (ValueError, TypeError):
        return ()


def parse_execution_hello(value: object) -> tuple[tuple[str, ...], dict]:
    """v1 Claude; v2 Codex estimates; v3 additionally acknowledges unmetered Kimi."""
    if not isinstance(value, dict) or type(value.get('protocolVersion')) is not int:
        raise ValueError('Invalid execution handshake')
    if value == {'type': 'execute_ready', 'protocolVersion': 1, 'agentKey': 'claude'}:
        return ('claude',), {**value, 'type': 'execute_welcome'}
    version = value['protocolVersion']
    keys = {'type', 'protocolVersion', 'agentKeys', 'codexBudgetPolicy'}
    if version == KIMI_HANDSHAKE_VERSION:
        keys.add('kimiBudgetPolicy')
    if (set(value) != keys or value['type'] != 'execute_ready'
            or version not in {MULTI_AGENT_HANDSHAKE_VERSION, KIMI_HANDSHAKE_VERSION}):
        raise ValueError('Invalid execution handshake')
    agents = execution_agents({'agents': json.dumps(value['agentKeys'])})
    if not agents or value['codexBudgetPolicy'] != (CODEX_BUDGET_POLICY if 'codex' in agents else None):
        raise ValueError('Invalid execution capabilities')
    if (('kimi' in agents) != (version == KIMI_HANDSHAKE_VERSION)
            or ('kimi' in agents and value['kimiBudgetPolicy'] != KIMI_BUDGET_POLICY)):
        raise ValueError('Invalid Kimi execution consent')
    return agents, {**value, 'type': 'execute_welcome'}
