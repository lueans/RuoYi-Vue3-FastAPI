# AI 脑图左侧交互设计 QA

> 验收范围说明：早期记录仅覆盖空会话，不能证明发送区、已发送消息和附件
> 交互已完整还原。以下历史结论保留用于追踪；这些区域以文末
> “Composer / user message / attachment fidelity”复核结果为准。

- Source visual truth: `/Users/liushuisong/Downloads/mindmap-ai-assistant.html`
- Rendered implementation: `http://127.0.0.1/mindmap/edit?id=136`
- Browser evidence: Codex in-app browser capture, initial empty conversation state
- Viewport: 1280 × 720 CSS px, device scale factor 1
- Source pixels: 1280 × 720
- Implementation pixels: 1280 × 720
- Density normalization: none; both captures used the same browser viewport and density
- State: light theme, editable cloud mind map, AI panel open, no active AI job, no attachment

**Findings**

- No actionable P0/P1/P2 mismatch remains.
- Fonts and typography: system Chinese font stack, 23px/600 welcome heading, 13px supporting copy and card labels match the source hierarchy and wrapping closely.
- Spacing and layout rhythm: the production panel uses the source's 376px preferred width, 60px header, centered welcome block, 2 × 2 cards, 10px card gap, and 18px composer radius. The production editor's 44px tool rail and 52px/30px application chrome are intentional host-shell constraints.
- Colors and visual tokens: neutral white surface, #262626 primary text, muted gray secondary text, light neutral borders, soft purple AI identity and purple active action match the source palette.
- Image quality and asset fidelity: the source contains no raster imagery in the panel. All visible controls use the project's Element Plus icon library; no placeholder, emoji, CSS drawing, handcrafted SVG, or generated substitute is present.
- Copy and content: heading, selection guidance and all four starter prompts match the supplied prototype. Production-only labels reflect live context and the selected Agent.
- Accessibility and interaction: heading structure, named panel region, labelled context/Agent controls, mode switch state, keyboard focus styles and disabled send state remain available.

**Full-view comparison evidence**

- The source and implementation were emitted together in one browser comparison pass at 1280 × 720.
- The implementation matches the source panel composition: new-conversation header, centered identity/heading/help copy, four starter cards and bottom composer.
- Expected state differences: the source mock includes a PDF attachment and an enabled Claude send action; the tested production state has no attachment, uses MindMap Agent and therefore shows a disabled send action until text is entered.

**Focused region comparison evidence**

- Welcome region: icon block, heading baseline, two-line description, card dimensions, 2 × 2 grid, icon tiles and text wrapping checked directly.
- Composer region: context chip, textarea, attachment/settings/mode controls, compact Agent selector and circular send button checked directly.
- Header region: new-conversation menu and close control checked directly.

**Interaction checks**

- Starter card inserts the mapped prompt and selects discussion mode when appropriate.
- Edit/discussion icon switch updates `aria-checked` and returns to edit mode.
- Agent selector opens the available Agent list without console errors.
- Browser console: no error or warning entries during the verified interactions.
- Production build: passed.
- Targeted frontend tests: 119/119 passed after updating the expected welcome copy.

**Comparison history**

1. Initial implementation rendered starter cards in one column at the production panel's effective inline size, which pushed the welcome heading above the visible area (P1). Removed the over-eager narrow-container fallback; the revised browser capture shows the heading and 2 × 2 card grid together.
2. The save-policy label wrapped onto an extra row and made the composer materially taller than the source (P2). Kept the policy component and its logic but removed the redundant visible label from the compact composer; the mode switch and task settings retain the same information and controls.
3. Post-fix evidence shows the welcome region and compact composer fully visible in the production editor at 1280 × 720.

**Follow-up Polish**

- P3: the production editor's surrounding navigation rails make the available panel height shorter than the standalone prototype. The central content is vertically compressed by a few pixels, but all intended hierarchy and controls remain visible without overlap.

**Implementation Checklist**

- [x] Match panel width, header, welcome hierarchy and card grid.
- [x] Consolidate composer actions into the source ordering.
- [x] Preserve session, draft, context, Agent, streaming and stop behavior.
- [x] Verify starter, mode and Agent interactions in the browser.
- [x] Run targeted tests and a production build.

final result: passed

## 2026-09-30 — Composer context selection correction

The earlier composer check did not cover automatic canvas-selection updates. This
follow-up specifically corrects and verifies that behavior; it is not a new claim
that every editor screen or conversation lifecycle visually matches the prototype.

- New requests on the current map default to `整个脑图` (dashed pill).
- Selecting one node displays its plain-text label; long labels are truncated with
  the full label in the tooltip. Multiple selections display `用户已选择X节点`.
- The selected-state pill has the prototype's node icon, multi-selection tint,
  and clear button; the extra row divider/dropdown arrow were removed.
- Browser verification: no selection, single selection, Ctrl-multiselect,
  selection before opening the panel, and clearing the selection back to the
  whole map. Clearing also disables canvas node commands, confirming that the
  canvas selection itself was cleared.
- Scope is normalized from the final selection before a new request. Submitted
  node labels are frozen with that request snapshot. This initial correction
  kept existing conversations locked; the completed-turn regression below
  supersedes that limitation.
- Targeted existing frontend tests: 146 passed. Production build passed.
- No real AI request was submitted and no model-generated map edits were made
  during this verification.

## 2026-09-30 — Completed-turn selection regression

Root cause: the composer used the existence of any job as its scope lock and
rendered that job's stored nodes, even after generation completed. The follow-up
API also inherited the old scope, so updating the label alone was insufficient.

- Split the immutable submitted-turn configuration from the next-turn canvas
  selection. Running, restoring, historical-result and unsettled-review states
  remain locked; eligible completed current-document turns follow selection.
- Next-turn requests explicitly carry `scope` and persist the matching frozen
  node labels. Recovery retains that submitted scope, not a later canvas click.
- The server validates the new scope against the authorized current document.
  Scope changes keep the platform conversation but do not reuse provider state
  or history belonging to a different scope. Legacy requests without `scope`
  keep their original behavior.
- Verified with the existing completed-direct conversation “帮我完善这个模块的测试用例”
  in “AI脑图验收-用户登录”: single selection showed `验证码重发`, Ctrl-multiselect
  showed `用户已选择2节点`, clearing restored `整个脑图`, and selecting while the
  panel was hidden was reflected after reopening it.
- No new AI request was sent, and no generated content was changed during this
  browser check. Follow-up payload and scope isolation are covered by automated
  regression tests rather than a paid production generation.
- Final automated checks: frontend 1,681 passed (17 new selection regressions);
  targeted backend 475 passed, 3 skipped. Production build and whitespace checks
  passed.

## 2026-09-30 — Composer / user message / attachment fidelity

### Scope and visual truth

- Reference: the user-provided `mindmap-ai-assistant.html`, rendered locally.
  Open Design native inspection was unavailable because Computer Use permission
  was not granted; the supplied HTML was used directly, without generating a new design.
- Implementation: `http://127.0.0.1/mindmap/edit?id=130`, existing completed
  conversation “帮我完善这个模块的测试用例”.
- Both captures: 1280 × 720 CSS pixels, light theme, browser screenshot output
  1280 × 720. No density resampling or temporary viewport override.
- Matched composer comparison: whole-map context, no attachment, input text
  “继续完善”, focused input, idle send control. Matched message text:
  “帮我优化脑图用例”. Production task IDs and Agent identity remain real.

### Findings corrected

- P1: global `aside` rules added 24px horizontal padding, 16px text and 32px
  line height to the AI panel. Scoped resets restore the prototype layout.
- P2: composer spacing, input height and inline baseline differed. Both versions
  now measure 343 × 143.945 CSS pixels in the matched state, with internal
  padding 11px 12px 9px, footer spacing 6px 16px 16px, 18px radius,
  24px single-line input and 10px toolbar top spacing.
- P2: `composerSubmitGroup` now has one 34px circular purple control: the
  prototype's upward arrow when idle, or compact pause-shaped stop control
  while running. The real stop action and accessible label still explicitly
  mean stopping the task while retaining already generated results.
- P1: user messages now use the source's shallow-purple bubble, 10px 14px
  padding, 14px radius, 14px text and 21.7px line height. The same short prompt
  measures 142 × 43.695 CSS pixels in both versions. Task ID and copy action
  sit below the bubble; attachment metadata is separate from message text.
- P1: the plus control is now independent attachment selection, not source-map
  import. Multiple files can be selected, read locally, displayed as chips and
  removed independently without changing the selected nodes or source mode.
- P2: source-provided plus, settings, mode and send SVG paths replace the
  mismatched controls. This supersedes the earlier all-Element-Plus statement.

### Interaction and request checks

- Browser-verified real local TXT, PDF and DOCX parsing, multiple file selection,
  independent removal, ready state and enabled send after valid text input.
- Browser-verified whole-map → single node → two selected nodes after an
  existing completed AI turn, with attachments retained. Clearing selection
  leaves attachments; removing attachments leaves selection intact.
- Copy interaction verified. Temporary input and test attachment were cleared
  after capture. No new AI request, paid generation or map-content edit was
  performed during this acceptance pass.
- Supported attachments: TXT, Markdown, JSON, CSV, PDF and DOCX; maximum five
  files, 10 MiB each, 50,000 extracted characters per file and 100,000 total.
  Invalid, unreadable, oversized and duplicate inputs produce explicit feedback.
- Create, follow-up, queue and retry pass the captured attachment body through
  the actual backend/Agent request path. Browser-persisted recovery data stores
  metadata only, never attachment body. Recovery does not silently omit files.
- A reviewed race was fixed: removing and re-adding the same file during an
  in-flight request creates a new draft revision; the old response cannot
  consume that new draft. The local revision does not affect JSON request identity.

### Evidence

- Full reference: `artifacts/composer-fidelity/reference-full.jpg`.
- Full implementation with a local test attachment:
  `artifacts/composer-fidelity/implementation-full.jpg`.
- Matched composer: `reference-composer.jpg` / `implementation-composer.jpg`
  under `artifacts/composer-fidelity/`.
- Matched message: `reference-user-message.jpg` /
  `implementation-user-message.jpg` under the same directory. Message crops
  were extracted from the verified full screenshots without rescaling.
- Additional selection/attachment state: `implementation-multi-attachment.jpg`
  (intermediate capture before final icon polish).

### Verification and boundaries

- Frontend regression suite: 1,729 passed, zero failures or skips.
- Backend attachment/continuation/retry/recovery/SDK/security regression suites:
  591 passed, three optional local-Kimi integration cases skipped.
- Request-size middleware: 23 passed. Final frontend production build and
  `git diff --check` passed.
- No actionable P0/P1/P2 remains in the four requested regions. The completed
  production conversation has real audit/status content, task IDs, Agent icons,
  a 6px reserved scrollbar and editor chrome absent from the standalone mock;
  these are not claimed as whole-screen pixel identity.
- Running/stop, queued follow-up and retry are covered by code-level regression
  tests, not a new live generation in this browser acceptance pass.
- This is desktop verification at the supplied prototype size; no new mobile
  visual or ARTEMIS device-testing claim is made.

final result: passed (the four requested UI regions and their scoped interactions)

## 2026-09-30 — User-requested send-time metadata

- Supersedes the task-ID metadata below user bubbles: display the actual message
  or task creation time as `YYYY-MM-DD-HH:mm:ss`, with the copy button retained.
- Prefer message time, fall back to task creation time; pending follow-ups record
  their send time once. Newly inserted task messages use the server creation time
  instead of the response arrival time. UTC/offset inputs display in local time.
- Missing/invalid timestamps do not display fabricated time or a task ID.
- Browser verified both historical messages, including `2026-09-30-18:04:24`;
  the full timestamp fits without truncation and copying still copies only text.
- Evidence: `artifacts/composer-fidelity/implementation-send-time.jpg`.
- Regression suite: 1,732 passed. Whitespace checks passed.

final result: passed (send-time metadata)

## 2026-09-30 — Sent context and attachment receipts

- Added a read-only context chip and separate attachment group above each user
  message. No selected nodes displays `整个脑图`; one displays its saved name;
  multiple display `用户已经选择X个节点`. The composer uses the same multi-select
  wording. Long names have full titles and do not stretch the message lane.
- Sent context and attachment metadata come from the submitted turn, not the
  current composer. Pending follow-ups, accepted turns, queue reconciliation,
  retry and history restoration retain their own metadata. Historical controls
  have no remove/clear action; copy still copies only the message text.
- The server freezes a safe context receipt before source rebasing and derives
  legacy labels only from the stored source snapshot. Missing/corrupt historical
  scope displays `上下文不可用` instead of falsely claiming whole-map scope.
  Existing source authorization and request identity are unchanged.
- Browser verified actual conversation history: first turn `边界与异常处理`,
  second turn `整个脑图`; selecting `退出登录` and Ctrl-selecting
  `自动登录与免登` updates only the composer to `用户已经选择2个节点`.
  Clearing selection and refreshing/reopening preserve both historical chips.
- Browser-rendered real-component fixtures cover whole map, single selection,
  multiple selection with PDF/DOCX metadata, and long names in a narrow lane.
  No horizontal overflow or console errors. This fixture does not call an AI
  service or write conversation data.
- Evidence: `artifacts/composer-fidelity/implementation-message-context-history.jpg`
  and `implementation-message-context-cases.jpg` in the same directory.
- Repeatable visual fixture:
  `ruoyi-fastapi-frontend/src/utils/__tests__/fixtures/mindmap-user-message-context.html`.
- Frontend regression suite: 1,755 passed. Production build and whitespace
  checks passed. No new paid AI generation or map-content edit was performed.
- Backend context/follow-up/retry/retention/recovery/connector suites: 201 passed,
  including existing and legacy queued-task rebasing without label drift.

final result: passed (sent context and attachment receipts)

## 2026-09-30 — Message footer placement correction

- User-requested order is now message bubble → context/attachments → send time
  and copy button. This supersedes the earlier above-bubble placement.
- Removed the historical attachment group's vertical divider and its divider
  spacing; wrapped file chips align right. The live composer is unchanged.
- Browser verified actual message DOM order and whole-map/single/multi/long-name
  fixtures: context starts 6px below the bubble, attachment border-left is 0px,
  and narrow lanes have no horizontal overflow.
- Evidence: `artifacts/composer-fidelity/implementation-message-context-bottom.jpg`.
- Frontend regression suite: 1,755 passed, including 31 component tests.

final result: passed (message footer placement and separator removal)
