"""Isolated Claude SDK worker. Stdout is a bounded local protocol, not a log.

Started only by ClaudeRunDriver, never from an incoming executable/path field.
The SDK owns CLI JSON-RPC; this worker forwards only public trace projections
and the explicit mindmap MCP callbacks to its owning bridge process.
"""

import asyncio
import contextlib
import json
import logging
import sys
from pathlib import Path

if __package__ in (None, ''):
    # An absolute, installed module path works with python -I during development
    # too, without trusting PYTHONPATH or the temporary working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mindmap_agent_bridge.claude_trace import ClaudeTrace, record
from mindmap_agent_bridge.completion import completion_schema, validate_completion
from mindmap_agent_bridge.execution import MAX_OFFER_BYTES, MAX_REPLY_BYTES, _load, decode_offer

BUILTIN_DENY = ['Bash', 'Read', 'Write', 'Edit', 'WebFetch', 'WebSearch', 'Glob', 'Grep', 'NotebookEdit',
                'Agent', 'Task', 'Skill', 'TodoWrite', 'TaskCreate', 'TaskUpdate', 'TaskList', 'TaskGet']
MAX_TOOLS = 200


class WorkerLink:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.lock = asyncio.Lock()
        self.sequence = 0

    def send(self, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(data) > MAX_OFFER_BYTES:
            raise ValueError('Worker frame exceeded limit')
        self.writer.write(data)
        self.writer.flush()

    async def tool(self, name, arguments):
        async with self.lock:
            self.sequence += 1
            if self.sequence > MAX_TOOLS:
                raise ValueError('Tool call limit')
            self.send({'type': 'tool_call', 'sequence': self.sequence, 'toolName': name, 'arguments': arguments})
            reply = _load(await self.reader.readline(), MAX_REPLY_BYTES)
            if (set(reply) != {'type', 'sequence', 'toolResult'} or reply['type'] != 'tool_result'
                    or type(reply['sequence']) is not int or reply['sequence'] != self.sequence
                    or not isinstance(reply['toolResult'], dict)):
                raise ValueError('Worker response invalid')
            result = reply['toolResult']
            return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}],
                    'is_error': result.get('ok') is not True}


def build_options(sdk, offer, cli_path, link):
    tools = []
    for descriptor in offer.tools:
        def make_handler(name):
            async def handler(arguments):
                return await link.tool(name, arguments)
            return handler
        tools.append(sdk.tool(descriptor['name'], descriptor['description'], descriptor['inputSchema'],
                              annotations=sdk.McpToolAnnotations(maxResultSizeChars=MAX_REPLY_BYTES))(
            make_handler(descriptor['name']),
        ))
    servers = {'mindmap': sdk.create_sdk_mcp_server(name='mindmap', version='1.0.0', tools=tools)} if tools else {}
    return sdk.ClaudeAgentOptions(
        cli_path=cli_path, cwd=Path.cwd(),
        system_prompt='你是受限的脑图 Agent。仅使用提供的脑图工具；工具之间可以说明公开进度，不披露隐藏推理。',
        tools=[], mcp_servers=servers, strict_mcp_config=True,
        allowed_tools=[f'mcp__mindmap__{item["name"]}' for item in offer.tools],
        disallowed_tools=BUILTIN_DENY, permission_mode='dontAsk',
        setting_sources=[], skills=[], plugins=[], agents={},
        settings=json.dumps({'disableAllHooks': True, 'enableAllProjectMcpServers': False}),
        extra_args={'no-session-persistence': None, 'disable-slash-commands': None},
        env={'CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS': '1', 'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1',
             'CLAUDE_CODE_SUBPROCESS_ENV_SCRUB': '1', 'ENABLE_CLAUDEAI_MCP_SERVERS': 'false',
             'ENABLE_TOOL_SEARCH': 'false'},
        include_partial_messages=True, max_turns=80, max_buffer_size=MAX_REPLY_BYTES,
        max_budget_usd=offer.max_budget_usd, model=offer.model_ref,
        stderr=lambda _line: None,
        output_format={'type': 'json_schema', 'schema': completion_schema(offer)},
    )


async def serve(reader, writer, *, sdk=None):
    if sdk is None:
        import claude_agent_sdk as sdk
    link = WorkerLink(reader, writer)
    initial = _load(await reader.readline(), MAX_OFFER_BYTES)
    if set(initial) != {'type', 'offer', 'cliPath'} or initial['type'] != 'start':
        raise ValueError('Worker start invalid')
    cli_path = initial['cliPath']
    if not isinstance(cli_path, str) or not Path(cli_path).is_absolute():
        raise ValueError('Local CLI path invalid')
    offer = decode_offer(json.dumps(initial['offer']), agent_key='claude')
    options = build_options(sdk, offer, cli_path, link)
    trace = ClaudeTrace(discuss=offer.intent == 'discuss')
    terminal = None
    async with contextlib.aclosing(sdk.query(prompt=offer.prompt, options=options)) as messages:
        async for message in messages:
            data = record(message)
            kind = data.get('type') or type(message).__name__
            if kind in {'result', 'ResultMessage'}:
                if terminal is not None:
                    raise ValueError('Duplicate terminal')
                if data.get('is_error') is not False or data.get('terminal_reason') in {
                    'aborted_streaming', 'aborted_tools', 'max_turns',
                }:
                    status = data.get('api_error_status')
                    budget_exceeded = (
                        data.get('subtype') in {'error_max_budget_usd', 'error_max_turns'}
                        or data.get('terminal_reason') == 'max_turns'
                    )
                    code = ('AI_PROVIDER_AUTH_FAILED' if status in {401, 403}
                            else 'AI_RATE_LIMITED' if status == 429
                            else 'AI_BUDGET_EXCEEDED' if budget_exceeded else 'AI_AGENT_UNAVAILABLE')
                    terminal = {'type': 'failed', 'errorCode': code}
                else:
                    terminal = {'type': 'completed', 'completion': validate_completion(data.get('structured_output'), offer)}
            elif terminal is not None:
                raise ValueError('Output after terminal')
            else:
                for event in trace.consume(message):
                    link.send({'type': 'event', **event})
    if terminal is None:
        raise ValueError('Missing terminal')
    # SDK generator closed before the parent sees completion. Parent still
    # verifies the entire worker/CLI process group exited before accepting it.
    link.send(terminal)


async def main():
    logging.disable(logging.CRITICAL)
    reader = asyncio.StreamReader(limit=MAX_REPLY_BYTES)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer,
    )
    try:
        await serve(reader, sys.stdout.buffer)
    except Exception:
        sys.stdout.write('{"type":"failed","errorCode":"AI_AGENT_UNAVAILABLE"}\n')
        sys.stdout.flush()
    finally:
        transport.close()


if __name__ == '__main__':
    asyncio.run(main())
