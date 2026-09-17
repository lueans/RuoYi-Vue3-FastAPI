"""AI 脑图指标必须低基数且不泄露业务内容。"""

import json

import pytest

from module_mindmap.service.mindmap_ai_metrics import MindmapAiMetricsRegistry


def test_ai_metrics_only_accept_bounded_dimensions_and_fixed_events() -> None:
    registry = MindmapAiMetricsRegistry()
    secret = '客户A-回归测试脑图-user-9981'

    with pytest.raises(ValueError):
        registry.observe_run(secret, 'success', 0.2)
    with pytest.raises(ValueError):
        registry.observe_run('codex', secret, 0.2)
    with pytest.raises(ValueError):
        registry.increment_event(secret)

    assert secret not in json.dumps(registry.snapshot(), ensure_ascii=False)


def test_ai_metrics_aggregate_usage_cost_duration_and_lifecycle_events() -> None:
    registry = MindmapAiMetricsRegistry()
    registry.observe_run('codex', 'success', 0.25, {
        'total_tokens': 120,
        'totalCostUsd': 0.02,
        'prompt': '不得进入指标',
    }, sdk_version='0.147.0', runtime_version='0.147.0', model_ref='gpt-5.6-terra')
    registry.observe_run('codex', 'success', 0.75, {
        'totalTokens': 30,
        'total_cost_usd': 0.01,
    }, sdk_version='0.147.0', runtime_version='0.147.0', model_ref='gpt-5.6-terra')
    registry.increment_event('artifact_ready')

    snapshot = registry.snapshot()

    assert snapshot['runs'] == [{
        'agentKey': 'codex',
        'outcome': 'success',
        'sdkVersion': '0.147.0',
        'runtimeVersion': '0.147.0',
        'modelRef': 'gpt-5.6-terra',
        'count': 2,
        'durationSecondsSum': 1.0,
        'tokensSum': 150,
        'costUsdSum': 0.03,
    }]
    assert {item['event']: item['count'] for item in snapshot['events']}['artifact_ready'] == 1
    assert '不得进入指标' not in json.dumps(snapshot, ensure_ascii=False)
