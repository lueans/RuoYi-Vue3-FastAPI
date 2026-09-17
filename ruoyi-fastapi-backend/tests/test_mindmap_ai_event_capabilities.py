from module_mindmap.service.mindmap_ai_service import (
    sanitize_mindmap_ai_event_payload,
)


def test_agent_capability_events_keep_safe_session_and_budget_modes() -> None:
    payload = sanitize_mindmap_ai_event_payload({
        'agentKey': 'codex',
        'sessionMode': 'resumed',
        'budgetEnforcement': 'post_run_estimate',
        'prompt': 'must never be exposed',
        'credentialEnv': {'OPENAI_API_KEY': 'must never be exposed'},
    })

    assert payload == {
        'agentKey': 'codex',
        'sessionMode': 'resumed',
        'budgetEnforcement': 'post_run_estimate',
    }
