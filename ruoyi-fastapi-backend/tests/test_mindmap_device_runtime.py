"""The discovery catalogue cannot grant local model execution consent."""

import json

import pytest
from pydantic import ValidationError

from config.env import MindmapAiConfig
from module_mindmap.ai.adapters.device import DeviceClaudeAdapter, DeviceCodexAdapter, DeviceKimiAdapter
from module_mindmap.ai.device_runtime import execution_agents, parse_execution_hello
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel, MindmapAiMessageModel
from module_mindmap.service.mindmap_ai_device_execution import merge_device_selection

HELLO = {'type': 'execute_ready', 'protocolVersion': 2, 'agentKeys': ['claude', 'codex'],
         'codexBudgetPolicy': 'reported_usage_estimate'}
DEVICE = '11111111-1111-4111-8111-111111111111'


def test_multi_agent_handshake_is_closed_and_codex_budget_consent_is_required():
    agents, welcome = parse_execution_hello(HELLO)
    assert agents == ('claude', 'codex')
    assert welcome == {**HELLO, 'type': 'execute_welcome'}
    assert parse_execution_hello({'type': 'execute_ready', 'protocolVersion': 1, 'agentKey': 'claude'})[0] == ('claude',)
    for change in ({'codexBudgetPolicy': None}, {'protocolVersion': True}, {'agentKeys': ['kimi']},
                   {'agentKeys': ['codex', 'codex']}, {'agentKeys': []}, {'agentKeys': 'codex'},
                   {'command': 'arbitrary'}, {'agentKeys': [{}]}):
        with pytest.raises(ValueError):
            parse_execution_hello({**HELLO, **change})


def test_malformed_or_unknown_redis_agents_never_advertise_execution():
    assert execution_agents({'agent': 'claude'}) == ('claude',)
    assert execution_agents({'agents': json.dumps(['claude', 'codex'])}) == ('claude', 'codex')
    assert execution_agents({'agents': '["kimi"]'}) == ('kimi',)
    for raw in ('invalid', 'null', '{}', '["unknown"]', '["codex", "codex"]', '[{}]'):
        assert execution_agents({'agents': raw, 'agent': 'claude'}) == ()


def test_device_codex_has_separate_admin_opt_in(monkeypatch):
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_bridge_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_execution_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_codex_enabled', False)
    assert DeviceClaudeAdapter().get_manifest().status == 'enabled'
    assert DeviceCodexAdapter().get_manifest().status == 'disabled'
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_codex_enabled', True)
    manifest = DeviceCodexAdapter().get_manifest()
    assert manifest.status == 'enabled' and manifest.default_model_ref == 'gpt-5.6-terra'
    assert '非硬费用上限' in manifest.status_reason


def test_device_identity_survives_same_agent_continuation_but_never_crosses_implicitly():
    previous = MindmapAiJobCreateModel(agentKey='device_codex', deviceId=DEVICE, prompt='create')
    payload = previous.model_dump(by_alias=True)
    message = MindmapAiMessageModel(prompt='continue')
    merge_device_selection(payload, message, 'device_codex', previous=previous)
    assert payload['deviceId'] == DEVICE
    merge_device_selection(payload, message, 'device_claude', previous=previous)
    assert 'deviceId' not in payload
    merge_device_selection(payload, message.model_copy(update={'device_id': DEVICE}), 'device_claude', previous=previous)
    assert payload['deviceId'] == DEVICE
    with pytest.raises(ValidationError):
        MindmapAiJobCreateModel(agentKey='device_codex', prompt='create')
    with pytest.raises(ValidationError):
        MindmapAiJobCreateModel(agentKey='codex', deviceId=DEVICE, prompt='create')


@pytest.mark.parametrize('keys', [['kimi'], ['claude', 'kimi'], ['claude', 'codex', 'kimi']])
def test_kimi_hello_requires_distinct_version_and_budget_acknowledgement(keys):
    hello = {'type': 'execute_ready', 'protocolVersion': 3, 'agentKeys': keys,
             'codexBudgetPolicy': 'reported_usage_estimate' if 'codex' in keys else None,
             'kimiBudgetPolicy': 'timeout_and_tool_limit'}
    assert parse_execution_hello(hello) == (tuple(keys), {**hello, 'type': 'execute_welcome'})
    for changes in ({'kimiBudgetPolicy': None}, {'kimiBudgetPolicy': 'hard_cap'}, {'agentKeys': ['claude']},
                    {'codexBudgetPolicy': True}, {'protocolVersion': 2}, {'command': 'kimi'},
                    {'agentKeys': ['kimi', 'kimi']}):
        with pytest.raises(ValueError):
            parse_execution_hello({**hello, **changes})
    with pytest.raises(ValueError):
        parse_execution_hello({key: value for key, value in hello.items() if key != 'kimiBudgetPolicy'})
    with pytest.raises(ValueError):
        parse_execution_hello({**HELLO, 'agentKeys': keys})


def test_kimi_has_separate_admin_gate_tool_free_discussion_and_explicit_device(monkeypatch):
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_bridge_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_execution_enabled', True)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_kimi_enabled', False)
    assert DeviceKimiAdapter().get_manifest().status == 'disabled'
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_device_kimi_enabled', True)
    manifest = DeviceKimiAdapter().get_manifest()
    assert manifest.status == 'enabled' and manifest.default_model_ref == 'kimi-for-coding'
    assert '无金额上限' in manifest.status_reason and 'discuss' in manifest.intents
    with pytest.raises(ValidationError):
        MindmapAiJobCreateModel(agentKey='device_kimi', prompt='create')
    model = MindmapAiJobCreateModel(agentKey='device_kimi', deviceId=DEVICE, prompt='create')
    payload = model.model_dump(by_alias=True)
    merge_device_selection(payload, MindmapAiMessageModel(prompt='continue'), 'device_kimi', previous=model)
    assert payload['deviceId'] == DEVICE
    merge_device_selection(payload, MindmapAiMessageModel(prompt='continue'), 'device_claude', previous=model)
    assert 'deviceId' not in payload
