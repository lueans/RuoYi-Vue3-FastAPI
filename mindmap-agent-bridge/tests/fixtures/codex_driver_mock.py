"""Offline app-server peer; launched inside the real driver-owned process group."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mindmap_agent_bridge.codex_policy import CONFIG_POLICY, startup_arguments  # noqa: E402


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def receive():
    raw = sys.stdin.readline()
    if not raw:
        raise SystemExit(0)
    return json.loads(raw)


def reply(request, result):
    emit({'id': request['id'], 'result': result})


def configuration():
    config = {}
    for dotted, value in CONFIG_POLICY.items():
        current = config
        *parts, last = dotted.split('.')
        for part in parts:
            current = current.setdefault(part, {})
        current[last] = value
    return {'config': config, 'layers': [{'name': {'type': 'sessionFlags'}, 'config': config}],
            'origins': {key: {'name': {'type': 'sessionFlags'}} for key in CONFIG_POLICY}}


def main():
    assert sys.argv[1:] == [*startup_arguments(), 'app-server']
    assert not {'DATABASE_PASSWORD', 'PYTHONPATH', 'NODE_OPTIONS', 'HTTP_PROXY', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY'} & os.environ.keys()
    assert Path(os.environ['HOME']).parent == Path.cwd().parent
    assert Path(os.environ['CODEX_HOME']).parent == Path.cwd().parent
    assert not (Path(os.environ['CODEX_HOME']) / 'config.toml').exists()
    initialize = receive()
    assert initialize['method'] == 'initialize'
    reply(initialize, {'userAgent': 'mindmap-agent-bridge/0.147.0'})
    assert receive()['method'] == 'initialized'
    while True:
        request = receive()
        method = request['method']
        if method == 'config/read':
            assert request['params']['includeLayers'] is True
            reply(request, configuration())
        elif method == 'account/login/start':
            assert request['params'] == {'type': 'apiKey', 'apiKey': 'sk-offline-test-credential'}
            reply(request, {'type': 'apiKey'})
        elif method == 'account/read':
            assert request['params'] == {'refreshToken': False}
            reply(request, {'account': {'type': 'apiKey'}, 'requiresOpenaiAuth': True})
        elif method == 'skills/list':
            reply(request, {'data': [{'cwd': str(Path.cwd()), 'errors': [], 'skills': []}]})
        elif method == 'thread/start':
            full_gateway = any(tool['name'] == 'mindmap_start_document' for tool in request['params']['dynamicTools'])
            reply(request, {'thread': {'id': 'mock-thread'}, 'model': request['params']['model'],
                            'modelProvider': 'openai', 'approvalPolicy': 'never',
                            'sandbox': {'type': 'readOnly'}, 'cwd': str(Path.cwd()), 'instructionSources': []})
        elif method == 'turn/start':
            reply(request, {'turn': {'id': 'mock-turn', 'status': 'inProgress'}})
            prompt = request['params']['input'][0]['text']
            break
        else:
            raise AssertionError('Unexpected preflight method')
    bound = {'threadId': 'mock-thread', 'turnId': 'mock-turn'}
    emit({'method': 'item/started', 'params': {**bound, 'item': {
        'type': 'agentMessage', 'id': 'progress', 'phase': 'commentary', 'text': '',
    }}})
    emit({'method': 'item/agentMessage/delta', 'params': {**bound, 'itemId': 'progress', 'delta': '正在整理脑图。'}})
    emit({'method': 'item/completed', 'params': {**bound, 'item': {
        'type': 'agentMessage', 'id': 'progress', 'phase': 'commentary', 'text': '正在整理脑图。',
    }}})
    if prompt == 'interrupt-test':
        request = receive()
        assert request['method'] == 'turn/interrupt' and request['params'] == bound
        reply(request, {})
        while True:
            receive()  # interrupt is not proof of child exit
    if prompt != 'missing-usage':
        usage = {'inputTokens': 100, 'cachedInputTokens': 20, 'cacheWriteInputTokens': 0,
                 'outputTokens': 20, 'reasoningOutputTokens': 10, 'totalTokens': 120}
        if prompt == 'over-budget':
            usage.update(outputTokens=100_000, totalTokens=100_100)
        emit({'method': 'thread/tokenUsage/updated', 'params': {**bound, 'tokenUsage': {'total': usage, 'last': usage}}})
    completion = 'artifact_completed'
    if 'handoff-' in prompt:
        sys.path.insert(0, str(Path(__file__).parent))
        from handoff_scenario import HANDOFF_ADVICE, handoff_scenario
        emit({'method': 'item/completed', 'params': {**bound, 'item': {
            'type': 'agentMessage', 'id': 'handoff-advice', 'phase': 'commentary', 'text': HANDOFF_ADVICE,
        }}})
        counter = iter(range(100, 120))
        def handoff_tool(name, arguments):
            index = next(counter)
            emit({'id': index, 'method': 'item/tool/call', 'params': {
                **bound, 'callId': f'call-{index}', 'tool': f'mindmap_{name}', 'arguments': arguments}})
            response = receive()
            assert response['id'] == index and response['result']['success'] is True
            return json.loads(response['result']['contentItems'][0]['text'])['result']
        completion = handoff_scenario(prompt, handoff_tool)
        if completion == 'wait':
            request = receive()
            assert request['method'] == 'turn/interrupt'
            reply(request, {})
            while True:
                receive()
        assert completion == 'direct_completed'
        calls = []
    else:
        calls = [('update_plan', {}), ('add_nodes', {}), ('complete_artifact', {})]
    if full_gateway and 'handoff-' not in prompt:
        calls = [
            ('update_plan', {'todos': [{'content': '构建订单', 'status': 'in_progress'}]}),
            ('start_document', {'title': '订单'}),
            ('read_projection', {}),
            ('add_nodes', None),
            ('update_plan', {'todos': [{'content': '构建订单', 'status': 'completed'}]}),
            ('complete_artifact', {}),
        ]
    root_uid = None
    for index, (name, arguments) in enumerate(calls):
        if arguments is None:
            arguments = {'nodes': [{'parentUid': root_uid, 'text': '创建'}, {'parentUid': root_uid, 'text': '支付'}]}
        emit({'id': index, 'method': 'item/tool/call', 'params': {
            **bound, 'callId': f'call-{index}', 'tool': f'mindmap_{name}', 'arguments': arguments,
        }})
        request = receive()
        if request.get('method') == 'turn/interrupt':
            reply(request, {})
            while True:
                receive()
        assert request['id'] == index and request['result']['success'] is True
        if name == 'start_document':
            root_uid = json.loads(request['result']['contentItems'][0]['text'])['result']['rootUid']
    text = json.dumps({'completionState': completion, 'title': '离线驱动测试', 'questions': []})
    emit({'method': 'item/completed', 'params': {**bound, 'item': {
        'type': 'agentMessage', 'id': 'final', 'phase': 'final_answer', 'text': text,
    }}})
    emit({'method': 'turn/completed', 'params': {'threadId': 'mock-thread', 'turn': {
        'id': 'mock-turn', 'status': 'completed',
    }}})
    while True:
        receive()  # exercise real process cleanup, not only short-lived peers


if __name__ == '__main__':
    main()
