"""Disposable ACP protocol peer, NOT a Kimi emulator or model integration."""

import json
import sys
from urllib.request import ProxyHandler, Request, build_opener


def send(message):
    print(json.dumps({'jsonrpc': '2.0', **message}, ensure_ascii=False), flush=True)


def receive():
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return json.loads(line)


def update(value):
    send({'method': 'session/update', 'params': {'sessionId': 'fixture-session', 'update': value}})


def run_prompt(url):
    opener = build_opener(ProxyHandler({}))
    call_number = 0

    def mcp(method, params):
        request = Request(url, data=json.dumps({
            'jsonrpc': '2.0', 'id': call_number, 'method': method, 'params': params,
        }).encode(), headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=5) as response:
            return json.loads(response.read(2 * 1024 * 1024))['result']

    def call(name, arguments):
        nonlocal call_number
        call_number += 1
        call_id = f'fixture-tool-{call_number}'
        title = f'mcp__mindmap__{name}'
        update({'sessionUpdate': 'tool_call', 'toolCallId': call_id, 'title': title,
                'status': 'in_progress', 'rawInput': arguments})
        send({'id': f'permission-{call_number}', 'method': 'session/request_permission', 'params': {
            'sessionId': 'fixture-session', 'toolCall': {'toolCallId': call_id, 'title': title},
            'options': [{'optionId': 'once', 'kind': 'allow_once'}],
        }})
        permission = receive()
        if permission.get('result') != {'outcome': {'outcome': 'selected', 'optionId': 'once'}}:
            raise RuntimeError('Fixture permission rejected')
        result = mcp('tools/call', {'name': name, 'arguments': arguments})
        if result.get('isError'):
            raise RuntimeError('Fixture tool failed')
        # ACP duplicates the gateway result without its original tool name.
        # It must not create a second "CLI tool" record in the transcript.
        for _ in range(2):
            update({'sessionUpdate': 'tool_call_update', 'toolCallId': call_id,
                    'status': 'completed', 'rawOutput': result})
        return json.loads(result['content'][0]['text'])

    mcp('initialize', {})
    update({'sessionUpdate': 'agent_thought_chunk', 'content': {'type': 'text', 'text': 'fixture-private-reasoning'}})
    update({'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': '开始生成订单脑图。'}})
    call('update_plan', {'todos': [{'content': '搭建订单脑图', 'status': 'in_progress'}]})
    root = call('start_document', {'title': '订单'})['rootUid']
    call('add_nodes', {'nodes': [{'parentUid': root, 'text': '支付'}, {'parentUid': root, 'text': '配送'}]})
    call('validate_draft', {})
    call('update_plan', {'todos': [{'content': '搭建订单脑图', 'status': 'completed'}]})
    call('complete_artifact', {})
    # The same post-tool message contains public prose and a split, fenced
    # terminal contract. Only the prose should reach the conversation.
    for text in ('订单脑图已完成。\n', '```J', 'SON\n{"title":"订单",',
                 '"completionState":"artifact_completed","questions":[]}', '\n```'):
        update({'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': text}})


def main():
    url = None
    while True:
        request = receive()
        method = request.get('method')
        if method == 'initialize':
            result = {'protocolVersion': 1, 'agentCapabilities': {'mcpCapabilities': {'http': True}}}
        elif method == 'session/new':
            url = request['params']['mcpServers'][0]['url']
            result = {'sessionId': 'fixture-session'}
        elif method == 'session/prompt':
            run_prompt(url)
            send({'id': request['id'], 'result': {'stopReason': 'end_turn'}})
            return
        else:
            raise RuntimeError('Unexpected fixture request')
        send({'id': request['id'], 'result': result})


if __name__ == '__main__':
    main()
