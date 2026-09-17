---
name: create-smm-v2
description: Create a validated RuoYi SMM v2 mind-map artifact with the isolated mindmap MCP tools.
---

# Create an SMM v2 artifact

1. Call `mindmap.start_document` for a new file, or `mindmap.read_projection` when an authorized draft already exists.
2. Build structure with `mindmap.add_nodes`; keep each batch at or below 200 nodes.
3. Use update, move, remove, or metadata tools only when the request requires them.
4. Call `mindmap.validate_draft` and repair any reported structural or safety issue.
5. Call `mindmap.complete_artifact` once and return its structured artifact.

Never edit hashes, access credentials, write to an unspecified directory, or claim platform verification for an external artifact.
