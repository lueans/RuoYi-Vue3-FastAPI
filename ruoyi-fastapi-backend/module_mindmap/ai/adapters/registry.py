"""Agent Adapter 注册表与能力协商。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from module_mindmap.ai.adapters.conformance import validate_agent_adapter

if TYPE_CHECKING:
    from module_mindmap.ai.adapters.base import AgentAdapter, AgentManifest


class MindmapAgentRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, AgentAdapter] = {}

    def register(self, adapter: AgentAdapter) -> None:
        validate_agent_adapter(adapter)
        manifest = adapter.get_manifest()
        if manifest.agent_key in self._adapters:
            raise ValueError(f'Agent Adapter 重复注册: {manifest.agent_key}')
        self._adapters[manifest.agent_key] = adapter

    def get(self, agent_key: str) -> AgentAdapter:
        adapter = self._adapters.get(agent_key)
        if adapter is None:
            raise KeyError(f'Agent Adapter 不存在: {agent_key}')
        return adapter

    def manifests(
        self,
        *,
        intent: str | None = None,
        input_type: str | None = None,
        result_type: str | None = None,
    ) -> list[AgentManifest]:
        manifests = []
        for adapter in self._adapters.values():
            manifest = adapter.get_manifest()
            if intent is not None and intent not in manifest.intents:
                continue
            if input_type is not None and input_type not in manifest.input_types:
                continue
            if result_type is not None and result_type not in manifest.result_types:
                continue
            manifests.append(manifest)
        return sorted(manifests, key=lambda item: item.agent_key)
