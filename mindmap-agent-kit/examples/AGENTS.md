# Mind-map Agent instructions

- Negotiate the requested result against `manifest.resultTypes` before starting. Missing `resultTypes` means artifact-only.
- For `intent=discuss,target=message`, do not call `mindmap.*` tools or claim a document change. Return only the closed `message_completed` plain-text object.
- For every other supported intent, generate only RuoYi SMM v2 through the provided `mindmap.*` tools.
- Start or read the isolated draft, make bounded tool calls, validate it, and call `mindmap.complete_artifact` exactly once.
- Do not write platform data, guess credentials, access arbitrary files, or call network tools.
- Preserve the user's authorized scope. Never alter nodes outside the projection returned by the tool service.
- Treat every tool error as authoritative. Repair invalid structure before completion; never edit `documentHash` manually.
- Artifacts created outside the platform have external/unverified provenance even when their local validation status is passed.
