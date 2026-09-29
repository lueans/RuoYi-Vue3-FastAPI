"""Deterministic app-server peer for real stdio/process tests, no network."""

import json
import sys


def send(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def receive():
    raw = sys.stdin.readline()
    if not raw:
        raise SystemExit(0)
    return json.loads(raw)


def response(request, value):
    send({'id': request['id'], 'result': value})


def main():
    initialize = receive()
    assert initialize['method'] == 'initialize'
    assert initialize['params']['capabilities']['experimentalApi'] is True
    response(initialize, {'userAgent': 'mock-codex/0.141.0'})
    assert receive()['method'] == 'initialized'
    thread = receive()
    assert thread['method'] == 'thread/start'
    assert thread['params']['approvalPolicy'] == 'never'
    assert thread['params']['sandbox'] == 'read-only'
    assert thread['params']['ephemeral'] is True
    assert all(item['type'] == 'function' and item['name'].startswith('mindmap_') for item in thread['params']['dynamicTools'])
    response(thread, {'thread': {'id': 'mock-thread'}})
    turn = receive()
    assert turn['method'] == 'turn/start'
    assert turn['params']['outputSchema']['additionalProperties'] is False
    response(turn, {'turn': {'id': 'mock-turn', 'status': 'inProgress'}})
    bound = {'threadId': 'mock-thread', 'turnId': 'mock-turn'}
    if turn['params']['input'][0]['text'] == 'interrupt-test':
        send({'method': 'item/started', 'params': {**bound, 'item': {
            'id': 'mock-thinking', 'type': 'reasoning', 'summary': [], 'content': [],
        }}})
        request = receive()
        assert request['method'] == 'turn/interrupt' and request['params'] == bound
        response(request, {})
        send({'method': 'turn/completed', 'params': {'threadId': 'mock-thread', 'turn': {
            'id': 'mock-turn', 'status': 'interrupted',
        }}})
        while True:
            receive()  # a stop response does not prove this process exited
    for index, name in enumerate(['update_plan', 'add_nodes', 'complete_artifact']):
        send({'id': 100 + index, 'method': 'item/tool/call', 'params': {
            **bound, 'callId': f'call-{index}', 'tool': f'mindmap_{name}', 'arguments': {},
        }})
        reply = receive()
        assert reply['id'] == 100 + index and reply['result']['success'] is True
        assert json.loads(reply['result']['contentItems'][0]['text'])['ok'] is True
    text = json.dumps({'completionState': 'artifact_completed', 'title': '真实 stdio 测试', 'questions': []})
    send({'method': 'item/completed', 'params': {**bound, 'item': {
        'type': 'agentMessage', 'id': 'mock-final', 'phase': 'final_answer', 'text': text,
    }}})
    send({'method': 'turn/completed', 'params': {'threadId': 'mock-thread', 'turn': {
        'id': 'mock-turn', 'status': 'completed',
    }}})


if __name__ == '__main__':
    main()
