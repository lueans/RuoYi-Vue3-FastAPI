"""AI 脑图 Agent Adapter。"""

from module_mindmap.ai.adapters.base import (
    AgentAdapter,
    AgentManifest,
    AgentMessageResult,
    AgentRunResult,
)
from module_mindmap.ai.adapters.registry import MindmapAgentRegistry

__all__ = [
    'AgentAdapter',
    'AgentManifest',
    'AgentMessageResult',
    'AgentRunResult',
    'MindmapAgentRegistry',
]
