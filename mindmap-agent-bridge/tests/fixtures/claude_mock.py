#!/usr/bin/env python3
"""Disposable CLI speaking the REAL Claude SDK control/MCP protocol. No network."""

import json
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path


def send(value):
    print(json.dumps(value), flush=True)


def receive():
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    return json.loads(line)


def mcp(method, params, number):
    request = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if not method.startswith('notifications/'):
        request['id'] = number
    send({'type': 'control_request', 'request_id': str(number), 'request': {
        'subtype': 'mcp_message', 'server_name': 'mindmap', 'message': request,
    }})
    while True:
        value = receive()
        if value['type'] == 'control_response' and value['response']['request_id'] == str(number):
            assert value['response']['subtype'] == 'success'
            return value['response']['response']['mcp_response']


def tool(name, arguments, number):
    response = mcp('tools/call', {'name': name, 'arguments': arguments}, number)
    result = response['result']
    assert not result.get('isError'), result
    return json.loads(result['content'][0]['text'])['result']


def main():
    if '--version' in sys.argv or '-v' in sys.argv:
        print('2.1.275 (Test CLI)')
        return
    assert '--strict-mcp-config' in sys.argv
    assert sys.argv[sys.argv.index('--tools') + 1] == ''
    assert '--setting-sources=' in sys.argv
    assert sys.argv[sys.argv.index('--permission-mode') + 1] == 'dontAsk'
    assert '--no-session-persistence' in sys.argv
    assert '--include-partial-messages' in sys.argv
    assert '--max-budget-usd' in sys.argv
    assert 0.0001 <= float(sys.argv[sys.argv.index('--max-budget-usd') + 1]) <= 1000
    if '--model' in sys.argv:
        assert sys.argv[sys.argv.index('--model') + 1] == 'sonnet'
    assert '--dangerously-skip-permissions' not in sys.argv
    assert 'DATABASE_PASSWORD' not in os.environ
    request = receive()
    assert request['request']['subtype'] == 'initialize'
    send({'type': 'control_response', 'response': {'subtype': 'success', 'request_id': request['request_id'],
                                                  'response': {}}})
    request = receive()
    assert request['type'] == 'user'
    mode = request['message']['content']
    if '用户要求（JSON 字符串）："wait"' in mode:
        mode = 'wait'
    send({'type': 'system', 'subtype': 'init', 'session_id': 'private-session', 'apiKey': 'never-upload-init'})
    def event(value):
        send({'type': 'stream_event', 'uuid': 'event-1', 'session_id': 'private-session', 'event': value})
    event({'type': 'message_start', 'message': {'id': 'provider-message-1'}})
    event({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'never-upload-hidden'}})
    event({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '正在整理订单流程，'}})
    event({'type': 'content_block_stop'})
    send({'type': 'assistant', 'message': {'id': 'provider-message-1', 'role': 'assistant', 'model': 'mock',
                                          'content': [{'type': 'text', 'text': '正在整理订单流程，'}]}})
    if mode == 'wait':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(20)
        return
    if mode == 'orphan':
        child = subprocess.Popen([
            sys.executable, '-c',
            'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready", flush=True); time.sleep(20)',
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert child.stdout.readline().strip() == b'ready'
    if mode in {'auth_failed', 'rate_limited', 'invalid_completion'}:
        send({'type': 'result', 'subtype': 'success', 'duration_ms': 1, 'duration_api_ms': 1,
              'is_error': mode != 'invalid_completion', 'num_turns': 1, 'session_id': 'private-session', 'usage': {},
              'api_error_status': 401 if mode == 'auth_failed' else 429,
              'errors': ['never-upload-private-diagnostics'],
              'structured_output': {'completionState': 'artifact_completed', 'rawThinking': 'private'}})
        return
    mcp('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                       'clientInfo': {'name': 'mock-cli', 'version': '1'}}, 1)
    mcp('notifications/initialized', {}, 2)
    if 'handoff-' in mode:
        from handoff_scenario import HANDOFF_ADVICE, handoff_scenario
        send({'type': 'assistant', 'message': {'id': 'handoff-advice', 'role': 'assistant', 'model': 'mock',
                                              'content': [{'type': 'text', 'text': HANDOFF_ADVICE}]}})
        counter = iter(range(100, 120))
        completion = handoff_scenario(mode, lambda name, args: tool(name, args, next(counter)))
        if completion == 'wait':
            while True:
                receive()  # the real driver owns interrupt and group cleanup
        assert completion == 'direct_completed'
        send({'type': 'result', 'subtype': 'success', 'duration_ms': 1, 'duration_api_ms': 1, 'is_error': False,
              'num_turns': 1, 'session_id': 'private-session', 'usage': {},
              'structured_output': {'completionState': completion, 'title': '接力验收', 'questions': []}})
        return
    if mode == 'gateway_error':
        response = mcp('tools/call', {'name': 'start_document', 'arguments': {'title': '订单'}}, 3)
        assert response['result']['isError'] is True
        send({'type': 'result', 'subtype': 'success', 'duration_ms': 1, 'duration_api_ms': 1,
              'is_error': True, 'num_turns': 1, 'session_id': 'private-session', 'usage': {}})
        return
    tool('update_plan', {'todos': [{'content': '创建订单流程', 'status': 'in_progress'}]}, 3)
    root = tool('start_document', {'title': '订单'}, 4)['rootUid']
    tool('add_nodes', {'nodes': [{'parentUid': root, 'text': '支付'}]}, 5)
    tool('update_plan', {'todos': [{'content': '创建订单流程', 'status': 'completed'}]}, 6)
    tool('complete_artifact', {}, 7)
    send({'type': 'result', 'subtype': 'success', 'duration_ms': 1, 'duration_api_ms': 1, 'is_error': False,
          'num_turns': 1, 'session_id': 'private-session', 'usage': {},
          'structured_output': {'completionState': 'artifact_completed', 'title': '订单', 'questions': []}})


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Test-only diagnostics beside the disposable CLI. No production path
        # imports this fixture or records real CLI diagnostics this way.
        Path(__file__).with_suffix('.error').write_text(traceback.format_exc())
        raise
