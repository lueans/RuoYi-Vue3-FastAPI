# Third-party Agent contract

This contract lets the platform negotiate a result type before an Agent runs. It keeps existing artifact-only adapters compatible and makes discussion an explicit, non-mutating path.

## Capability manifest

Every Adapter declares an `intents` array. Kit 1.1 adds the optional `resultTypes` array:

```json
{
  "agentKey": "my_agent",
  "intents": ["create", "discuss"],
  "resultTypes": ["artifact", "message"]
}
```

The allowed result types are:

- `artifact`: a validated SMM v2 candidate that can enter the platform proposal/apply flow;
- `message`: a bounded plain-text answer that never enters the proposal/apply flow.

For backward compatibility, a missing `resultTypes` field resolves to `["artifact"]`. Therefore an older Adapter remains usable for its existing artifact intents, but the platform must not route `discuss` to it. Any manifest containing `discuss` must also contain `message` in `resultTypes`.

## Request routing

Discussion uses one unambiguous pair:

```json
{
  "intent": "discuss",
  "target": "message"
}
```

`discuss` cannot target `file` or `proposal`, and `message` cannot be used by another intent. Before dispatch, call `validate_agent_request()` in Python or `validateAgentRequest()` in TypeScript with the selected manifest. The returned `resultType` is the only terminal result kind that the caller should accept for that run.

Discussion can receive a platform-authorized safe projection and user-visible conversation history, but it must not call the mutating `mindmap.*` tools, return an artifact, or claim that the current map changed. Platform authorization, persistence, session ownership, audit, and retention remain outside the Kit.

## Message completion

A successful discussion returns a closed object with no extra properties:

```json
{
  "completionState": "message_completed",
  "title": "信息架构建议",
  "content": "先按用户目标组织一级主题，再拆分关键路径。",
  "contentType": "text/plain"
}
```

Rules:

- `completionState` is exactly `message_completed`;
- `title` is a string or `null`, normalized to one line, with at most 200 Unicode characters;
- `content` is non-empty after trimming, at most 20,000 Unicode characters and at most 65,536 UTF-8 bytes;
- `contentType` is exactly `text/plain`;
- NUL, DEL, and C0 controls other than tab, line feed, and carriage return are rejected;
- HTML or Markdown is not interpreted by this contract. Consumers must render the value as untrusted plain text.

Use `agent_message_json_schema()` / `agentMessageJsonSchema()` as the provider structured-output schema. Always pass the provider result through `normalize_agent_message_result()` / `normalizeAgentMessageResult()` before returning it to the platform. The normalizer accepts either an object or a JSON string and rejects missing, unknown, unsafe, or oversized values.

## Result state matrix

| Request | Negotiated result | Terminal success | Mutating tools | Apply allowed |
| --- | --- | --- | --- | --- |
| non-`discuss` + `file`/`proposal` | `artifact` | SMM v2 artifact completion | bounded in-memory tools | only after platform validation |
| `discuss` + `message` | `message` | `message_completed` object | none | never |

`needs_input` remains a separate terminal clarification signal and is not added to `resultTypes`.
