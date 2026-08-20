"""脑图运行指标：固定低基数标签、进程内有界存储。"""

import os
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from threading import Lock
from typing import Any, ParamSpec, TypeVar, get_args

from exceptions.exception import ServiceWarning
from module_mindmap.entity.vo.mindmap_monitor_vo import (
    MindmapMetricEvent,
    MindmapMetricOperation,
    MindmapMetricOutcome,
)

P = ParamSpec('P')
R = TypeVar('R')

MINDMAP_METRIC_OPERATIONS = frozenset(get_args(MindmapMetricOperation))
MINDMAP_METRIC_OUTCOMES = frozenset(get_args(MindmapMetricOutcome))
MINDMAP_METRIC_EVENTS = frozenset(get_args(MindmapMetricEvent))
MINDMAP_DURATION_BUCKETS_SECONDS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class _MetricSeries:
    count: int = 0
    duration_sum: float = 0.0
    duration_buckets: list[int] = field(
        default_factory=lambda: [0] * len(MINDMAP_DURATION_BUCKETS_SECONDS)
    )
    work_units_sum: int = 0
    work_units_max: int = 0


class MindmapMetricsRegistry:
    """线程安全、维度封闭的单进程指标注册器。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = datetime.now(timezone.utc)
        self._started_monotonic = time.monotonic()
        self._series: dict[tuple[str, str], _MetricSeries] = {}
        self._events: Counter[str] = Counter()

    def observe(
        self,
        operation: str,
        outcome: str,
        duration_seconds: float,
        *,
        work_units: int | None = None,
    ) -> None:
        if operation not in MINDMAP_METRIC_OPERATIONS:
            raise ValueError(f'不支持的脑图指标操作: {operation}')
        if outcome not in MINDMAP_METRIC_OUTCOMES:
            raise ValueError(f'不支持的脑图指标结果: {outcome}')
        duration = max(0.0, float(duration_seconds))
        units = work_units if isinstance(work_units, int) and not isinstance(work_units, bool) else 0
        units = max(0, units)
        with self._lock:
            series = self._series.setdefault((operation, outcome), _MetricSeries())
            series.count += 1
            series.duration_sum += duration
            for index, upper_bound in enumerate(MINDMAP_DURATION_BUCKETS_SECONDS):
                if duration <= upper_bound:
                    series.duration_buckets[index] += 1
            series.work_units_sum += units
            series.work_units_max = max(series.work_units_max, units)

    def increment_event(self, event: str) -> None:
        if event not in MINDMAP_METRIC_EVENTS:
            raise ValueError(f'不支持的脑图指标事件: {event}')
        with self._lock:
            self._events[event] += 1

    def snapshot(self, collaboration: dict[str, Any] | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._lock:
            series_snapshot = [
                {
                    'operation': operation,
                    'outcome': outcome,
                    'count': series.count,
                    'durationSecondsSum': round(series.duration_sum, 6),
                    'durationBuckets': [
                        {'le': upper_bound, 'count': series.duration_buckets[index]}
                        for index, upper_bound in enumerate(MINDMAP_DURATION_BUCKETS_SECONDS)
                    ],
                    'workUnitsSum': series.work_units_sum,
                    'workUnitsMax': series.work_units_max,
                }
                for (operation, outcome), series in sorted(self._series.items())
            ]
            event_snapshot = [
                {'event': event, 'count': self._events.get(event, 0)}
                for event in sorted(MINDMAP_METRIC_EVENTS)
            ]
        runtime = collaboration if isinstance(collaboration, dict) else {}

        def normalize_count(key: str) -> int:
            value = runtime.get(key)
            return value if type(value) is int and value >= 0 else 0

        redis_transport_state = runtime.get('redisTransportState')
        if redis_transport_state not in {'stopped', 'ready', 'degraded'}:
            redis_transport_state = 'stopped'
        return {
            'scope': 'process',
            'processId': os.getpid(),
            'startedTime': self._started_at,
            'generatedTime': now,
            'uptimeSeconds': max(0.0, round(time.monotonic() - self._started_monotonic, 3)),
            'collaboration': {
                'activeRooms': normalize_count('activeRooms'),
                'activeConnections': normalize_count('activeConnections'),
                'retiringConnections': normalize_count('retiringConnections'),
                'redisTransportState': redis_transport_state,
            },
            'series': series_snapshot,
            'events': event_snapshot,
        }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._series.clear()
            self._events.clear()


mindmap_metrics = MindmapMetricsRegistry()


def record_mindmap_event(event: str) -> None:
    """记录固定事件；监控故障不得改变业务执行结果。"""
    try:
        mindmap_metrics.increment_event(event)
    except Exception:
        pass


def _record_mindmap_operation(
    operation: str,
    outcome: str,
    duration_seconds: float,
    *,
    work_units: int | None = None,
) -> None:
    try:
        mindmap_metrics.observe(
            operation,
            outcome,
            duration_seconds,
            work_units=work_units,
        )
    except Exception:
        pass


def observe_mindmap_operation(
    operation: str,
    *,
    outcome_getter: Callable[[Any], str] | None = None,
    work_units_getter: Callable[[tuple[Any, ...], dict[str, Any], Any], int | None] | None = None,
    result_hook: Callable[[Any], None] | None = None,
) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    """观测异步服务方法；指标辅助逻辑永远不能改变业务结果。"""
    if operation not in MINDMAP_METRIC_OPERATIONS:
        raise ValueError(f'不支持的脑图指标操作: {operation}')

    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            started = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
            except ServiceWarning:
                _record_mindmap_operation(
                    operation,
                    'conflict',
                    time.perf_counter() - started,
                )
                record_mindmap_event('conflict')
                raise
            except Exception:
                _record_mindmap_operation(
                    operation,
                    'error',
                    time.perf_counter() - started,
                )
                raise

            outcome = 'success'
            work_units = None
            if outcome_getter is not None:
                try:
                    candidate = outcome_getter(result)
                    if candidate in MINDMAP_METRIC_OUTCOMES:
                        outcome = candidate
                except Exception:
                    pass
            if work_units_getter is not None:
                try:
                    work_units = work_units_getter(args, kwargs, result)
                except Exception:
                    work_units = None
            if result_hook is not None:
                try:
                    result_hook(result)
                except Exception:
                    pass
            _record_mindmap_operation(
                operation,
                outcome,
                time.perf_counter() - started,
                work_units=work_units,
            )
            return result

        return wrapper

    return decorator
