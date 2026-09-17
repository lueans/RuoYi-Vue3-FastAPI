"""默认 Adapter 注册与服务端安装的第三方 Adapter 扩展点。"""
from functools import lru_cache
from importlib import metadata
from typing import Any

from module_mindmap.ai.adapters.claude import ClaudeMindmapAdapter
from module_mindmap.ai.adapters.codex import CodexMindmapAdapter
from module_mindmap.ai.adapters.native import NativeMindmapAdapter
from module_mindmap.ai.adapters.registry import MindmapAgentRegistry
from utils.log_util import logger

AGENT_ADAPTER_ENTRY_POINT = 'ruoyi.mindmap_agent_adapters'


def _entry_points() -> list[Any]:
    discovered = metadata.entry_points()
    if hasattr(discovered, 'select'):
        return list(discovered.select(group=AGENT_ADAPTER_ENTRY_POINT))
    return list(discovered.get(AGENT_ADAPTER_ENTRY_POINT, ()))


def build_mindmap_agent_registry() -> MindmapAgentRegistry:
    registry = MindmapAgentRegistry()
    registry.register(NativeMindmapAdapter())
    registry.register(CodexMindmapAdapter())
    registry.register(ClaudeMindmapAdapter())
    for entry_point in _entry_points():
        try:
            loaded = entry_point.load()
            adapter = (
                loaded()
                if isinstance(loaded, type) or not callable(getattr(loaded, 'get_manifest', None))
                else loaded
            )
            registry.register(adapter)
        except Exception as exc:  # noqa: PERF203
            # 扩展由平台管理员随服务部署，不允许一个失效扩展拖垮三个内置 Agent。
            logger.warning(f'跳过无效 AI 脑图 Agent Adapter {entry_point.name}: {exc}')
    return registry


@lru_cache(maxsize=1)
def get_mindmap_agent_registry() -> MindmapAgentRegistry:
    return build_mindmap_agent_registry()
