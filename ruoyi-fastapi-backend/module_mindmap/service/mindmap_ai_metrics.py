"""AI 脑图低基数运行指标，不记录提示词、文件名或用户标识。"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from threading import Lock
from typing import Any

from utils.log_util import logger

AGENT_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]{1,63}$')
VERSION_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$')
ALLOWED_OUTCOMES = frozenset({
    'success', 'cancelled', 'timeout', 'invalid', 'error', 'conflict',
})
ALLOWED_EVENTS = frozenset({
    'job_created',
    'artifact_ready',
    'artifact_downloaded',
    'local_applied',
    'cloud_saved',
    'cloud_applied',
    'proposal_stale',
    'proposal_rejected',
    'cloud_undone',
    'message_ready',
    'direct_completed',
    'direct_conflict',
})
MAX_AGENT_SERIES = 128


@dataclass
class _AgentSeries:
    count: int = 0
    duration_seconds_sum: float = 0.0
    tokens_sum: int = 0
    cost_usd_sum: float = 0.0


class MindmapAiMetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._series: dict[tuple[str, str, str, str, str], _AgentSeries] = {}
        self._events: Counter[str] = Counter()

    def observe_run(
        self,
        agent_key: str,
        outcome: str,
        duration_seconds: float,
        usage: dict[str, Any] | None = None,
        *,
        sdk_version: str = 'unknown',
        runtime_version: str = 'unknown',
        model_ref: str = 'unknown',
    ) -> None:
        dimensions = (sdk_version, runtime_version, model_ref)
        if (
            not AGENT_KEY_PATTERN.fullmatch(agent_key)
            or outcome not in ALLOWED_OUTCOMES
            or any(not VERSION_PATTERN.fullmatch(value) for value in dimensions)
        ):
            raise ValueError('AI 脑图指标维度无效')
        key = (agent_key, outcome, sdk_version, runtime_version, model_ref)
        with self._lock:
            if key not in self._series and len(self._series) >= MAX_AGENT_SERIES:
                key = ('other', outcome, 'other', 'other', 'other')
            series = self._series.setdefault(key, _AgentSeries())
            series.count += 1
            series.duration_seconds_sum += max(0.0, float(duration_seconds))
            values = usage if isinstance(usage, dict) else {}
            token_value = values.get('total_tokens', values.get('totalTokens', 0))
            cost_value = values.get('totalCostUsd', values.get('total_cost_usd', 0))
            if type(token_value) is int and token_value >= 0:
                series.tokens_sum += token_value
            if isinstance(cost_value, (int, float)) and not isinstance(cost_value, bool):
                series.cost_usd_sum += max(0.0, float(cost_value))

    def increment_event(self, event: str) -> None:
        if event not in ALLOWED_EVENTS:
            raise ValueError('AI 脑图指标事件无效')
        with self._lock:
            self._events[event] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                'runs': [
                    {
                        'agentKey': agent_key,
                        'outcome': outcome,
                        'sdkVersion': sdk_version,
                        'runtimeVersion': runtime_version,
                        'modelRef': model_ref,
                        'count': series.count,
                        'durationSecondsSum': round(series.duration_seconds_sum, 6),
                        'tokensSum': series.tokens_sum,
                        'costUsdSum': round(series.cost_usd_sum, 6),
                    }
                    for (
                        agent_key,
                        outcome,
                        sdk_version,
                        runtime_version,
                        model_ref,
                    ), series in sorted(self._series.items())
                ],
                'events': [
                    {'event': event, 'count': self._events.get(event, 0)}
                    for event in sorted(ALLOWED_EVENTS)
                ],
            }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._series.clear()
            self._events.clear()


mindmap_ai_metrics = MindmapAiMetricsRegistry()


def record_mindmap_ai_event(event: str) -> None:
    try:
        mindmap_ai_metrics.increment_event(event)
    except Exception as exc:
        logger.warning(
            'AI mindmap metrics event recording failed: event=%s, error=%s',
            event,
            type(exc).__name__,
        )


def record_mindmap_ai_run(
    agent_key: str,
    outcome: str,
    duration_seconds: float,
    usage: dict[str, Any] | None = None,
    *,
    sdk_version: str = 'unknown',
    runtime_version: str = 'unknown',
    model_ref: str = 'unknown',
) -> None:
    try:
        mindmap_ai_metrics.observe_run(
            agent_key,
            outcome,
            duration_seconds,
            usage,
            sdk_version=sdk_version,
            runtime_version=runtime_version,
            model_ref=model_ref,
        )
    except Exception as exc:
        logger.warning(
            'AI mindmap metrics run recording failed: error=%s',
            type(exc).__name__,
        )
