# 脑图评论功能 Design QA

## Evidence

- durable interaction evidence: `artifacts/comment-chain-audit/`
- viewport: desktop light theme, `1512 x 705` CSS px, device pixel ratio `2`
- source pixels: `1512 x 761`; normalized to `1512 x 705` by cropping the lower 56 px outside the compared workspace
- implementation pixels: `1512 x 705`; browser screenshot output was already normalized to CSS-pixel dimensions
- state: XMind comment overview compared with the local editor's selected-node/open-comment state. Visual QA used deterministic discussion data; a later isolated E2E run exercised real writes and cleaned them through the normal soft-delete workflow.

## Findings

No actionable P0, P1, or P2 differences remain.

- Fonts and typography: both use a compact system sans-serif hierarchy. The implementation keeps the project's existing 10–13 px sidebar scale and maintains readable author, time, node context, body, and action levels without clipping.
- Spacing and layout rhythm: XMind's source panel is about 284 px wide; the implementation intentionally uses the existing `--mindmap-side-panel-width: 300px` token. Header, toolbar, composer, thread list, and 44 px activity rail align without overlap or horizontal overflow.
- Colors and visual tokens: the implementation maps the source's blue comment markers and active controls to the current product token `#3370ff`. Borders, neutral surfaces, and disabled states remain consistent with the existing editor.
- Image quality and asset fidelity: the feature does not require decorative imagery. User identities use the existing Element Plus avatar component with text fallback; no source logos or product imagery were approximated with CSS or handcrafted SVG.
- Copy and content: labels for all/current-node scope, open/resolved state, composer guidance, reply, resolve, reopen, delete, loading, error, and empty states are coherent in the current Chinese product context.
- Icons and affordances: existing Element Plus icons are used for comment, add, location, reply, resolve, reopen, delete, loading, and close. Buttons expose semantic labels and visible focus styles.
- Responsiveness and accessibility: the existing sidebar breakpoint behavior is preserved; the panel becomes a 300 px mobile drawer below 760 px. Comment count markers expose `role="button"`, keyboard activation, `tabindex`, and an accessible count label.

## Interaction Evidence

- Switching from “全部” to “当前节点” changed the visible result count from 2 to 1.
- Opening “回复” produced a focused, enabled reply textbox labelled for the thread author.
- Switching to “已解决” produced the correct zero-result empty state for the selected node.
- Final fresh-tab console check returned no warnings or errors.
- A later isolated E2E run verified publish, reply, resolve, reply-to-reopen, whole-thread delete confirmation, and post-delete absence.
- Database verification confirmed all three E2E messages carried idempotency keys and both messages and thread were soft-deleted.

## Full-view Comparison

The source and implementation both keep the mind map as the primary canvas, place blue numeric comment markers beside affected nodes, and reserve the right edge for a persistent comment overview. The implementation adds the current product's activity rail and a selected-node composer; these are intentional extensions rather than fidelity defects.

## Focused Region Comparison

The focused comparison verifies the entire right sidebar at readable size. XMind uses a flatter chronological feed, while the current product uses lightly bordered thread cards so replies and resolution actions stay grouped. This difference follows the existing sidebar/card language and does not change the source interaction model.

## Comparison History

- Pass 1: no P0/P1/P2 visual mismatch found. The first QA tab contained one non-descriptive console entry caused during hot reload, so a fresh tab was rendered instead of treating it as final evidence.
- Pass 2: the fresh-tab screenshot preserved the same visual result and returned an empty warning/error log. Current-node filtering, reply state, and resolved empty state were then verified.

## Follow-up Polish

- P3 optional: if future discussions become very long, a compact-density preference could reduce card padding while retaining thread grouping.

## Final Result

final result: passed
