# Local Customizations Log

All modifications to the vendored `simple-mind-map` source code should be documented here.
This file is essential for future upstream merges.

## Format

```
### YYYY-MM-DD - Brief Description
- **File**: path/to/modified/file.js
- **Change**: What was changed
- **Reason**: Why it was changed
```

## Customizations

### 2026-08-20 - Continue sibling and child creation from text editing
- **File**: src/core/render/TextEdit.js
- **Change**: The temporary Enter and Tab shortcuts now share one commit-and-insert path, targeting the node being edited to create the next sibling or child respectively.
- **Reason**: A newly inserted node immediately enters text editing, where Enter and Tab previously only closed the editor and forced users to press the shortcut a second time before every subsequent node.

### 2026-08-20 - Accept shortcuts from a focusable canvas container
- **File**: src/core/command/KeyCommand.js
- **Change**: Treated the configured mind-map container as a valid default keyboard event target while retaining the existing body and text-editor checks.
- **Reason**: The accessible editor canvas uses `tabindex="0"`; clicking a node focuses that container, so rejecting it disabled Tab, Enter, zoom, undo, and the rest of the shared shortcut pipeline.

### 2026-08-19 - Make node snapshots and comparisons stack-safe
- **File**: src/layouts/Base.js, src/core/render/node/MindMapNode.js, src/utils/index.js
- **Change**: Routed render/layout/generalization snapshots through the iterative JSON serializer and reused the structural equality utility for nested object property comparison.
- **Reason**: Deep plugin data could overflow per-node render snapshots, while equivalent objects with different key insertion order caused unnecessary node resizing and collaboration updates.

### 2026-08-19 - Serialize deep JSON documents without recursion
- **File**: src/utils/jsonClone.js, src/utils/index.js, src/core/command/Command.js, src/plugins/Export.js, src/parse/xmind.js
- **Change**: Added frame-based compact or indented JSON serialization and routed undo history, JSON/SMM export, XMind package generation, and structured clipboard writes through it; removed the unused recursive `Command.removeDataUid` method.
- **Reason**: A deep tree could be copied or mapped iteratively but still overflow when history, export, XMind packaging, clipboard, draft, or recovery code serialized the full result with native recursive `JSON.stringify`.

### 2026-08-19 - Traverse mutable rich-text DOM iteratively
- **File**: src/utils/domTree.js, src/utils/index.js
- **Change**: Unified rich-text tag styling, literal text replacement, and formula removal on a child-snapshot iterative DOM traversal, preserving matched-tag subtree stops and text replacement behavior.
- **Reason**: Deep imported HTML could overflow three local recursive walkers, and deleting adjacent formula elements from a live `childNodes` collection could skip nodes after indexes shifted.

### 2026-08-19 - Clone JSON document values without recursion
- **File**: src/utils/jsonClone.js, src/utils/index.js
- **Change**: Replaced `JSON.parse(JSON.stringify(data))` in `simpleDeepClone` with an explicit enter/exit-frame JSON-value clone that preserves document isolation, JSON omission/null/number behavior, `toJSON`, shared-value duplication, and dangerous own keys.
- **Reason**: Deep appointed subtrees, collaboration payloads, and render-tree data could overflow inside JSON serialization before the newer iterative traversal and copy boundaries were reached.

### 2026-08-19 - Unify appointed-node edits and runtime bounds on an iterative forest
- **File**: src/utils/nodeForest.js, src/utils/index.js
- **Change**: Added stable first-reachable forest traversal and finite rectangle aggregation; migrated appointed data/UID mutation and runtime subtree bounds, with strict malformed-graph rejection for inserts and tolerant invalid SVG measurement handling.
- **Reason**: Deep paste/insert trees and export/presentation bounds still used duplicate recursion; cycles could hang insertion, shared nodes could receive multiple identities, and an unmeasurable subtree returned Infinity geometry.

### 2026-08-19 - Preserve and bound Markdown imports iteratively
- **File**: src/parse/markdownTo.js
- **Change**: Replaced recursive inline/list conversion with ordered stacks, enforce shared document limits during target construction, retain multiple top-level blocks under an explicit root, and restore paragraph/list continuation notes from source Markdown.
- **Reason**: Deep or oversized Markdown could fail before the application import gate, while multiple roots, ordinary paragraphs, and notes emitted by the matching exporter were previously discarded silently.

### 2026-08-19 - Share persistence limits with the application import boundary
- **File**: src/utils/documentLimits.js, src/parse/xmindTree.js
- **Change**: Extracted the 20,000-node and 256-level document limits into a stable vendored module while preserving the existing XMind exports, so every application import format can enforce the same persistence contract.
- **Reason**: XMind enforced the server limits internally, but JSON, SMM, and Markdown could otherwise enter the editor with a document that would only fail during rendering or save.

### 2026-08-19 - Make layout ancestor propagation iterative and cycle-safe
- **File**: src/layouts/layoutTree.js, src/layouts/LogicalStructure.js, src/layouts/CatalogOrganization.js, src/layouts/MindMap.js, src/layouts/OrganizationStructure.js, src/layouts/Timeline.js, src/layouts/Fishbone.js, src/layouts/VerticalTimeline.js
- **Change**: Replaced nine recursive sibling-offset propagation methods with one ordered iterative ancestor walker, preserving layout-specific root boundaries and Fishbone height transitions while stopping cycles and broken parent/children relationships.
- **Reason**: Deep or corrupted runtime parent chains could overflow the JavaScript stack, recurse forever, or shift unrelated siblings; the duplicated traversal rules also made layout maintenance inconsistent.

### 2026-08-19 - Make XMind tree conversion iterative and persistence-safe
- **File**: src/parse/xmind.js, src/parse/xmindTree.js, src/utils/xmind.js
- **Change**: Unified modern import, XMind 8 import, and export on a cycle-safe iterative mapper with the same 20,000-node and 256-level limits as server persistence; hardened malformed legacy helpers and write root images to `rootTopic`.
- **Reason**: Recursive conversion could overflow or stall on large input, oversized imports only failed later at save time, and root-node images were previously attached to the sheet instead of the exported root topic.

### 2026-08-19 - Cancel superseded performance render sessions
- **File**: src/core/render/Render.js, src/core/render/node/MindMapNode.js, src/utils/asyncRenderSession.js, src/utils/timing.js
- **Change**: Added cancellable render sessions, first-reachable runtime-node claiming, stable asynchronous child snapshots, lifecycle cleanup, and cancellable throttle/debounce wrappers.
- **Reason**: Superseded view renders and destroyed instances could leave scheduled node tasks writing stale SVG state or emitting late completion events.

### 2026-08-18 - Cancel stale presentation entry and render callbacks
- **File**: src/plugins/Demonstrate.js
- **Change**: Bound fullscreen entry to a monotonic request, cancel pending entry during exit/removal/destruction, and reject render/expand callbacks after presentation has ended.
- **Reason**: Fullscreen and render completion are asynchronous; a late result could otherwise enter presentation on a destroyed mind-map instance or mutate the canvas after the user had exited.

### 2026-08-18 - Harden search and replace for readonly and legacy documents
- **File**: src/plugins/Search.js
- **Change**: Normalize missing node text before search/replace and reject direct replace operations while the mind map is readonly.
- **Reason**: Imported or legacy nodes can omit text, and Search mutates nodes through plugin methods rather than the command bus; both cases need a core boundary independent of the application UI.

### 2026-08-18 - Validate document image URLs at the render boundary
- **File**: src/utils/image.js, src/core/render/node/nodeCreateContents.js
- **Change**: Added shared throwing/tolerant image URL normalization and validate the resolved `imgMap` value before creating an SVG image node.
- **Reason**: Imported, legacy, template, version, and collaborative documents can bypass the application image dialog; the renderer must not load script, local-file, Blob, credential-bearing, or oversized image addresses from document data.

### 2026-08-18 - Enforce readonly at the command boundary
- **File**: src/core/command/Command.js
- **Change**: Reject commands in readonly mode unless they belong to the explicit navigation, selection, or expansion allowlist; emit `readonly_command_rejected` for observability.
- **Reason**: UI-only disabling left indirect callers, shortcuts, and plugins able to mutate the local tree in readonly sessions, creating unsavable ghost changes and weakening the server permission boundary.

### 2026-04-24 - Fix rich text node text display
- **File**: src/plugins/RichText.js
- **Change**: Added CSS margin/padding reset for block elements (p, h1-h6, ol, ul, blockquote, pre) inside `.smm-richtext-node-wrap`; Added null safety for `htmlEscape` call in `handleDataToRichText`
- **Reason**: When enabling rich text mode, node text is wrapped in `<p>` tags rendered via SVG foreignObject. The browser default `<p>` margins caused text to shift/clip inside nodes. Also, nodes with undefined text could crash the conversion.
