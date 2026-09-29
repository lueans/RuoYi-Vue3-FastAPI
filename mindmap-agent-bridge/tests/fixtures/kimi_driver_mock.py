"""Offline ACP peer for full device routing; NOT a model/runtime substitute."""

import json
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def send(value):
    print(json.dumps({'jsonrpc': '2.0', **value}), flush=True)


def receive():
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    return json.loads(line)


def update(kind, **payload):
    send({'method': 'session/update', 'params': {
        'sessionId': 'private-test-session', 'update': {'sessionUpdate': kind, **payload}}})


def main():
    if sys.argv[-1] == '--version':
        print('2.1.1')
        return
    assert sys.argv[-1] == 'acp'
    initialized = receive()
    assert initialized['method'] == 'initialize' and initialized['params']['clientCapabilities'] == {}
    send({'id': initialized['id'], 'result': {'protocolVersion': 1, 'agentInfo': {'version': '2.1.1'},
                                            'agentCapabilities': {'mcpCapabilities': {'http': True}}}})
    session = receive()
    assert session['method'] == 'session/new'
    url = session['params']['mcpServers'][0]['url']
    send({'id': session['id'], 'result': {'sessionId': 'private-test-session', 'configOptions': [
        {'id': 'model', 'currentValue': 'mindmap-kimi'}, {'id': 'mode', 'currentValue': 'default'}]}})
    prompt = receive()
    assert prompt['method'] == 'session/prompt'
    assert 'never-forward-platform-secret' not in json.dumps(prompt)
    opener = build_opener(ProxyHandler({}))
    prompt_text = prompt['params']['prompt'][0]['text']
    if 'handoff-' in prompt_text:
        sys.path.insert(0, str(Path(__file__).parent))
        from handoff_scenario import HANDOFF_ADVICE, handoff_scenario
        update('agent_message_chunk', content={'type': 'text', 'text': HANDOFF_ADVICE})
        counter = iter(range(100, 120))
        def handoff_tool(name, arguments):
            index = next(counter)
            identity = f'call-{index}'
            update('tool_call', toolCallId=identity, title='Human description', status='in_progress', rawInput=arguments)
            send({'id': identity, 'method': 'session/request_permission', 'params': {
                'sessionId': 'private-test-session', 'toolCall': {'toolCallId': identity, 'title': f'mcp__mindmap__{name}'},
                'options': [{'optionId': 'approve_once', 'kind': 'allow_once'}]}})
            assert receive()['result'] == {'outcome': {'outcome': 'selected', 'optionId': 'approve_once'}}
            request = Request(url, data=json.dumps({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                              'params': {'name': name, 'arguments': arguments}}).encode(),
                              headers={'Content-Type': 'application/json'})
            with opener.open(request, timeout=5) as response:
                result = json.loads(response.read(8 * 1024 * 1024))['result']
            assert result['isError'] is False
            update('tool_call_update', toolCallId=identity, status='completed', rawOutput=result)
            return json.loads(result['content'][0]['text'])['result']
        completion = handoff_scenario(prompt_text, handoff_tool)
        if completion == 'wait':
            assert receive()['method'] == 'session/cancel'
            while True:
                receive()
        assert completion == 'direct_completed'
        update('agent_message_chunk', content={'type': 'text', 'text': json.dumps({
            'completionState': completion, 'title': '接力验收', 'questions': []})})
        send({'id': prompt['id'], 'result': {'stopReason': 'end_turn'}})
        while True:
            receive()
    calls = [('update_plan', {'todos': [{'content': '建立订单脑图', 'status': 'in_progress'}]}),
             ('start_document', {'title': '订单'}), ('add_nodes', None), ('validate_draft', {}),
             ('update_plan', {'todos': [{'content': '建立订单脑图', 'status': 'completed'}]}),
             ('complete_artifact', {})]
    root = None
    update('agent_message_chunk', content={'type': 'text', 'text': '正在建立订单脑图。'})
    update('agent_thought_chunk', content={'type': 'text', 'text': 'never-forward-hidden-reasoning'})
    for index, (name, arguments) in enumerate(calls):
        if arguments is None:
            arguments = {'nodes': [{'parentUid': root, 'text': '支付'}, {'parentUid': root, 'text': '配送'}]}
        identity = f'call-{index}'
        update('tool_call', toolCallId=identity, title='Human description', status='in_progress', rawInput=arguments)
        send({'id': identity, 'method': 'session/request_permission', 'params': {
            'sessionId': 'private-test-session', 'toolCall': {'toolCallId': identity, 'title': f'mcp__mindmap__{name}'},
            'options': [{'optionId': 'approve_once', 'kind': 'allow_once'}]}})
        assert receive()['result'] == {'outcome': {'outcome': 'selected', 'optionId': 'approve_once'}}
        request = Request(url, data=json.dumps({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                          'params': {'name': name, 'arguments': arguments}}).encode(),
                          headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=5) as response:
            result = json.loads(response.read(8 * 1024 * 1024))['result']
        assert result['isError'] is False
        tool = json.loads(result['content'][0]['text'])
        if name == 'start_document':
            root = tool['result']['rootUid']
        for _ in range(2):
            update('tool_call_update', toolCallId=identity, status='completed', rawOutput=result)
    update('agent_message_chunk', content={'type': 'text', 'text': json.dumps({
        'completionState': 'artifact_completed', 'title': '订单', 'questions': []})})
    send({'id': prompt['id'], 'result': {'stopReason': 'end_turn'}})
    while True:
        receive()  # exercise owned-process stop, not only natural child exit


if __name__ == '__main__':
    main()
