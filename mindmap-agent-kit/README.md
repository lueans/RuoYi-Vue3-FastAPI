# MindMap Agent Kit

Standalone contract tooling for agents that create RuoYi Simple Mind Map (`.smm`) v2 artifacts or return non-mutating discussion messages. It contains no platform credentials, database access, or write-back capability. Artifacts produced outside the platform are marked `external_unverified` and are revalidated on import.

## Python

```bash
python -m pip install ./mindmap-agent-kit/python
mindmap-agent validate output.smm
mindmap-agent render-summary output.smm
mindmap-agent-mcp
```

Builder example:

```python
from mindmap_agent_kit import MindmapBuilder

builder = MindmapBuilder('Payment tests')
builder.add_nodes([{'parentUid': builder.root_uid, 'text': 'Successful payment'}])
result = builder.complete_artifact(
    title='Payment tests',
    agent_key='my_agent',
    adapter_version='1.0.0',
    prompt_version='payment-tests-1',
)
artifact = result['artifact']
```

Discussion example:

```python
from mindmap_agent_kit import (
    build_agent_message_result,
    normalize_agent_manifest,
    validate_agent_request,
)

manifest = normalize_agent_manifest({
    'agentKey': 'my_agent',
    'intents': ['create', 'discuss'],
    'resultTypes': ['artifact', 'message'],
})
validate_agent_request('discuss', 'message', manifest=manifest)
result = build_agent_message_result(
    '这次只讨论信息架构，不修改当前脑图。',
    title='信息架构建议',
)
```

The CLI only reads the file path provided by the caller. The MCP server is stdio-only and keeps drafts in process memory; `mindmap.complete_artifact` returns JSON and never writes a file.

## TypeScript

```bash
cd mindmap-agent-kit/typescript
npm install
npm run build
```

```ts
import { MindmapBuilder } from '@ruoyi/mindmap-agent-kit'

const builder = new MindmapBuilder('Payment tests')
builder.addNodes([{ parentUid: builder.rootUid, text: 'Successful payment' }])
const artifact = await builder.complete({
  title: 'Payment tests',
  agentKey: 'my_agent',
  adapterVersion: '1.0.0',
  promptVersion: 'payment-tests-1',
})
```

```ts
import {
  buildAgentMessageResult,
  normalizeAgentManifest,
  validateAgentRequest,
} from '@ruoyi/mindmap-agent-kit'

const manifest = normalizeAgentManifest({
  agentKey: 'my_agent',
  intents: ['create', 'discuss'],
  resultTypes: ['artifact', 'message'],
})
validateAgentRequest('discuss', 'message', manifest)
const result = buildAgentMessageResult(
  '这次只讨论信息架构，不修改当前脑图。',
  '信息架构建议',
)
```

## Result negotiation

- A legacy manifest that omits `resultTypes` is interpreted as `['artifact']`.
- An adapter that declares the `discuss` intent must explicitly declare `resultTypes: ['artifact', 'message']` (or `['message']` for a discussion-only adapter).
- A discussion request is always `intent: 'discuss'` plus `target: 'message'`. Other intents cannot target `message`.
- A completed discussion returns exactly `completionState`, `title`, `content`, and `contentType`. Its `contentType` is currently fixed to `text/plain`; it is not an SMM artifact and cannot be applied to a document.

See [AGENT_CONTRACT.md](AGENT_CONTRACT.md) for the complete third-party Adapter contract and security limits.

## MCP tools

The stdio server exposes:

- `mindmap.start_document`
- `mindmap.read_projection`
- `mindmap.add_nodes`
- `mindmap.update_nodes`
- `mindmap.move_nodes`
- `mindmap.remove_nodes`
- `mindmap.set_document_meta`
- `mindmap.validate_draft`
- `mindmap.complete_artifact`

All input schemas reject unknown top-level fields. A draft ID is valid only inside the MCP process that created it. No tool can open arbitrary files, access the network, or mutate a real platform document.

See [COMPATIBILITY.md](COMPATIBILITY.md) before upgrading an adapter or SDK. Fixed positive and negative samples are under `conformance/`.

## Tests

```bash
PYTHONPATH=mindmap-agent-kit/python python -m unittest discover -s mindmap-agent-kit/python/tests
python mindmap-agent-kit/conformance/run.py
cd mindmap-agent-kit/typescript && npm test
```
