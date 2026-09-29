"""Deterministic tool script shared by the three OFFLINE protocol peers."""

HANDOFF_ADVICE = '1. 保留人工已有内容。\n2. 下一轮补充断线恢复。'


def handoff_scenario(prompt, call):
    stop = '用户要求（JSON 字符串）："handoff-stop"' in prompt
    resume = '用户要求（JSON 字符串）："handoff-continue"' in prompt
    if not (stop or resume):
        return None
    assert 'never-forward-platform-secret' not in prompt
    assert 'private-provider-session' not in prompt
    assert 'hidden-handoff-thinking' not in prompt
    if resume:
        assert '未完成的接续事项' in prompt
        assert '旧计划仅是上一 Agent 报告的快照' in prompt
        assert '2. 下一轮补充断线恢复。' in prompt
        assert 'editing_transcript' in prompt and 'recorded' in prompt
        assert '公开回复只是旧 Agent 的陈述' in prompt
        assert 'never-upload-hidden' not in prompt
    projection = call('read_projection', {})
    root = projection['root']
    assert root['data']['text'] == '接力验收'
    children = root['children']
    assert children[0]['data'] == {'uid': 'original', 'text': '人工已有内容'}
    assert [node['data']['text'] for node in children] == (
        ['人工已有内容'] if stop else ['人工已有内容', '上一轮已确认部分'])
    call('update_plan', {'todos': [{'content': '未完成的接续事项', 'status': 'in_progress'}]})
    call('add_nodes', {'nodes': [{'parentUid': root['data']['uid'],
                                 'text': '上一轮已确认部分' if stop else '下一位完成剩余部分'}]})
    if stop:
        return 'wait'
    call('update_plan', {'todos': [{'content': '未完成的接续事项', 'status': 'completed'}]})
    call('validate_draft', {})
    return 'direct_completed'
