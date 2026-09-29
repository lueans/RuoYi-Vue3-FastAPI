import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { reactive, ref, watch, nextTick, effectScope } from 'vue'
import { projectRuntimeEvents } from '../mindmap-ai-runtime.js'
import { buildAgentChatBlocks, sliceAgentExecutionRows, agentStepState, agentExecutionState, agentPlanSummary, agentToolPresentation, agentToolLabel, formatAgentDuration, renderAgentMarkdown, isAgentChatNearBottom } from '../mindmap-agent-presentation.js'

const event = (sequence, eventType, payload) => ({ key: `job:${sequence}`, sequence, eventType, payload })

test('provider prose is not moved before intervening tools even with the same message ID', () => {
  const events = [
    event(1, 'assistant_delta', { messageId: 'a', text: '检查前' }),
    event(2, 'tool_started', { callId: 't', toolName: 'get_document' }),
    event(3, 'tool_completed', { callId: 't', toolName: 'get_document' }),
    event(4, 'assistant_delta', { messageId: 'a', text: '检查后' }),
    event(5, 'assistant_delta', { messageId: 'a', text: '，完成' }),
  ]
  const source = JSON.stringify(events)
  const view = projectRuntimeEvents(events)
  assert.deepEqual(view.entries.map(item => item.kind), ['message', 'tool', 'message'])
  assert.equal(view.entries[0].text, '检查前')
  assert.equal(view.entries[2].text, '检查后，完成')
  assert.equal(new Set(view.entries.map(item => item.key)).size, 3)
  const blocks = buildAgentChatBlocks(view.entries, '检查后，完成')
  assert.deepEqual(blocks.map(item => item.kind), ['message', 'execution', 'message'])
  assert.equal(JSON.stringify(events), source)
})

test('deduplicates finalized prose but preserves a distinct conclusion and missing-event fallback', () => {
  const entries = [{ key: 'm', kind: 'message', text: '已完成\n检查' }]
  assert.equal(buildAgentChatBlocks(entries, '已完成\r\n检查').length, 1)
  assert.equal(buildAgentChatBlocks(entries, '已完成 检查').length, 2)
  assert.equal(buildAgentChatBlocks(entries, '新增 8 个节点').length, 2)
  assert.equal(buildAgentChatBlocks([], '旧记录没有过程事件')[0].text, '旧记录没有过程事件')
  assert.deepEqual(buildAgentChatBlocks([], ''), [])
  assert.equal(buildAgentChatBlocks([{ key: '1', kind: 'message', text: 'A' }, { key: '2', kind: 'message', text: 'B' }], 'A\nB').length, 2)
})

test('legacy identical adjacent prose can fold without deleting records or crossing tool boundaries', () => {
  const entries = [
    { key: 'a', kind: 'message', text: '读取完成' },
    { key: 'b', kind: 'message', text: '读取完成' },
    { key: 'c', kind: 'tool', status: 'completed' },
    { key: 'd', kind: 'message', text: '读取完成' },
    { key: 'e', kind: 'message', text: '读取完成\n' },
  ]
  const original = structuredClone(entries)
  assert.equal(buildAgentChatBlocks(entries).length, 5, 'live prose is not folded by default')
  const blocks = buildAgentChatBlocks(entries, '读取完成', { foldRepeatedMessages: true })
  assert.deepEqual(blocks.map(block => block.key), ['a', 'execution:c', 'd', 'e'])
  assert.deepEqual(blocks[0].repeatedMessages, [entries[1]])
  assert.equal(blocks[2].repeatedMessages, undefined)
  assert.deepEqual(entries, original)
  const source = readFileSync(new URL('../../components/MindMap/MindmapAgentTrace.vue', import.meta.url), 'utf8')
  assert.match(source, /buildAgentTurnBlocks\(view.value.entries, props.finalContent, props\)/)
  assert.match(source, /v-for="repeat in block.repeatedMessages"[^>]*:key="repeat.key"/)
})

test('execution outcome never reports an interrupted or unresolved tool as completed', () => {
  assert.equal(agentExecutionState([], { running: true }).label, '进行中')
  assert.equal(agentExecutionState([], { cancelled: true }).label, '已中断')
  assert.equal(agentExecutionState([], { failed: true }).label, '执行失败')
  assert.equal(agentExecutionState([{ kind: 'tool', status: 'unknown' }]).label, '记录已结束')
  assert.equal(agentExecutionState([{ kind: 'tool', status: 'failed' }]).label, '执行失败')
})

test('missing durations and tool data are not invented', () => {
  assert.equal(formatAgentDuration(undefined), '')
  assert.equal(formatAgentDuration(-5), '')
  assert.equal(formatAgentDuration(0), '0 ms')
  assert.equal(formatAgentDuration(1520), '1.5 s')
  assert.equal(formatAgentDuration(62000), '1 m 2 s')
  assert.deepEqual(agentToolLabel('mcp__mindmap__add_nodes'), { verb: '新增', subject: '脑图节点' })
  assert.equal(agentToolLabel('custom_tool').subject, 'custom_tool')
  const view = projectRuntimeEvents([event(1, 'tool_completed', { callId: 't', toolName: 'custom_tool', durationMs: -1 })])
  assert.equal(view.entries[0].duration, undefined)
})

test('compact plan summary never promotes pending work or treats interruption as completion', () => {
  const todos = [{ content: '读取', status: 'completed' }, { content: '修改', status: 'pending' }]
  assert.equal(agentPlanSummary([]), null)
  assert.deepEqual(agentPlanSummary(todos, { running: true }), { label: '当前任务计划', meta: '已完成 1/2 项', tone: 'unknown' })
  todos[1].status = 'in_progress'
  assert.equal(agentPlanSummary(todos, { running: true }).label, '修改')
  assert.equal(agentPlanSummary(todos).tone, 'unknown')
  assert.equal(agentPlanSummary(todos, { cancelled: true }).label, '中断时的计划')
  assert.equal(agentPlanSummary(todos, { failed: true }).label, '失败时的计划')
  todos.push({ content: '并行检查', status: 'in_progress' })
  assert.equal(agentPlanSummary(todos, { running: true }).label, '2 项计划进行中')
  assert.equal(todos[1].status, 'in_progress')
  assert.equal(agentPlanSummary([{ content: '完成', status: 'completed' }]).label, '计划已完成')
})

test('tool summaries use explicit scalar receipts, never the truncated first 12 items or requested amounts', () => {
  const entry = { name: 'mcp__mindmap__add_nodes', status: 'completed',
    input: JSON.stringify({ nodes: Array.from({ length: 12 }, (_, i) => ({ text: `场景 ${i}` })) }),
    output: JSON.stringify({ createdCount: 50, created: Array.from({ length: 12 }, (_, i) => ({ nodeUid: String(i) })) }) }
  const result = agentToolPresentation(entry)
  assert.equal(result.summary, '工具返回：新增 50 个节点')
  assert.equal(result.request, '请求内容预览：「场景 0」、「场景 1」')
  assert.doesNotMatch(result.summary, /保存|12/)
  entry.output = JSON.stringify({ created: Array(12).fill({ nodeUid: 'id' }) })
  assert.equal(agentToolPresentation(entry).summary, '', 'legacy list is not an exact count')
  for (const status of ['running', 'failed', 'cancelled', 'unknown']) {
    assert.equal(agentToolPresentation({ ...entry, status, output: '{"createdCount":50}' }).summary, '')
  }
  assert.equal(agentToolPresentation({ ...entry, output: '{"createdCount":0}' }).summary, '工具返回：新增 0 个节点')
})

test('tool summaries retain operation and subtree semantics, handle provider prefixes and scoped counts', () => {
  assert.equal(agentToolPresentation({ name: 'mindmap_update_nodes', status: 'completed', output: '{"updated":2}' }).summary, '工具返回：完成 2 项节点更新')
  assert.equal(agentToolPresentation({ name: 'remove_nodes', status: 'completed', output: '{"removed":1}' }).summary, '工具返回：删除 1 个目标（含其子树）')
  const view = projectRuntimeEvents([event(1, 'tool_completed', { toolName: 'read_projection', callId: 'r', summary: { nodeCount: 18 } })])
  assert.equal(agentToolPresentation(view.entries[0]).summary, '返回的授权范围：18 个节点')
  assert.equal(agentToolPresentation({ name: 'read_document_detail', status: 'completed', output: '{"summary":{"nodeCount":0}}' }).summary, '返回的授权范围：0 个节点')
  assert.equal(agentToolPresentation({ name: 'custom_tool', status: 'completed', output: '{"createdCount":50}' }).summary, '')
})

test('malformed, oversized and nonnumeric tool metadata cannot invent a successful count', () => {
  for (const output of ['{"createdCount":50', '[]', 'null', '{"createdCount":true}', '{"createdCount":"50"}', '{"createdCount":-1}', '{"createdCount":1.5}', '{"createdCount":9007199254740992}', ' '.repeat(6001)]) {
    assert.equal(agentToolPresentation({ name: 'add_nodes', status: 'completed', output }).summary, '')
  }
  assert.deepEqual(agentToolLabel('toString'), { verb: '调用', subject: 'toString' })
  assert.deepEqual(agentToolLabel('constructor'), { verb: '调用', subject: 'constructor' })
  const result = agentToolPresentation({ name: 'edit_node_text', status: 'running', input: JSON.stringify({ text: 'abc\n' + '长'.repeat(1000) }) })
  assert.ok(result.request.length < 100)
  assert.doesNotMatch(result.request, /\n/)
})

test('chat markdown renders readable structure without HTML injection or automatic image requests', () => {
  const html = renderAgentMarkdown('## 结果\n\n- **完成**检查\n\n```js\nconst ok = true\n```\n\n<script>alert(1)</script>\n\n[危险](javascript:alert) ![截图](https://evil.test/track) [安全](https://example.com)')
  assert.match(html, /<h2>结果<\/h2>/)
  assert.match(html, /<strong>完成<\/strong>/)
  assert.match(html, /<pre><code>/)
  assert.doesNotMatch(html, /<script|<img|href="javascript:/)
  assert.match(html, /rel="noopener noreferrer"/)
})

test('deeply nested agent Markdown falls back to escaped text without breaking the transcript', () => {
  const source = '> '.repeat(4000) + '<img src=x onerror=alert(1)> [链接](javascript:alert)'
  const html = renderAgentMarkdown(source)
  assert.match(html, /^<p>&gt; /)
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/)
  assert.doesNotMatch(html, /<img|href="javascript:/)
  assert.equal(renderAgentMarkdown('后续 **消息**'), '<p>后续 <strong>消息</strong></p>')
})

test('chat tables have semantic headers, bounded columns and a keyboard-accessible scroll region', () => {
  const html = renderAgentMarkdown('| 分支 | 数量 | 说明 |\n| :--- | ---: | :---: |\n| **安全** | 4 | `a\\|b` |\n| 性能 | 3 |\n| 兼容 | 2 | 正常 | 多余单元格 |')
  assert.match(html, /class="mindmapMarkdownTable"[^>]*tabindex="0"[^>]*role="region"[^>]*aria-label=/)
  assert.match(html, /<table><thead><tr><th scope="col" align="left">分支<\/th>/)
  assert.match(html, /<th scope="col" align="right">数量<\/th>/)
  assert.match(html, /<tbody><tr><td align="left"><strong>安全<\/strong><\/td>/)
  assert.match(html, /<code>a\|b<\/code>/)
  assert.match(html, /<td align="center"><\/td>/, 'missing cells preserve the table grid')
  assert.doesNotMatch(html, /多余单元格/)
})

test('streaming table prefixes remain safe and never enable raw HTML, remote images or script links', () => {
  const source = '| 内容 |\n| --- |\n| <img src=x onerror=alert(1)> [链接](javascript:alert) ![图片](https://evil.test/pixel) |'
  for (let end = 1; end <= source.length; end++) {
    const html = renderAgentMarkdown(source.slice(0, end))
    assert.doesNotMatch(html, /<img|<script|href="javascript:/)
  }
  const html = renderAgentMarkdown(source)
  assert.match(html, /<table>/)
  assert.match(html, /&lt;img/)
  assert.match(renderAgentMarkdown('| 表头 |\n| --- |'), /<thead>.*表头.*<\/thead>/)
})

test('sparse wide tables cannot amplify a short reply into unbounded padded cells', () => {
  const header = `| ${Array(100).fill('列').join(' | ')} |\n| ${Array(100).fill('---').join(' | ')} |\n`
  const html = renderAgentMarkdown(header + '| 值 |\n'.repeat(1000) + '\n表格之后的回答')
  assert.ok((html.match(/<t[hd](?: |>|\b)/g) || []).length <= 5000)
  assert.equal((html.match(/<th /g) || []).length, 50)
  assert.match(html, /表格内容较多，仅显示前 50 列、99 行正文/)
  assert.match(html, /表格之后的回答/)
  assert.doesNotMatch(renderAgentMarkdown('| 列 |\n| --- |\n| 值 |'), /仅显示前/)
})

test('following the transcript respects a reader who scrolls away', () => {
  assert.equal(isAgentChatNearBottom(null), true)
  assert.equal(isAgentChatNearBottom({ scrollHeight: 1500, scrollTop: 950, clientHeight: 500 }), true)
  assert.equal(isAgentChatNearBottom({ scrollHeight: 1500, scrollTop: 400, clientHeight: 500 }), false)
})

function foldHarness(autoOpen) {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAgentFold.vue', import.meta.url), 'utf8')
  const script = parse(source).descriptor.scriptSetup.content
  const ast = babelParse(script, { sourceType: 'module' })
  const body = ast.program.body.filter(node => node.type !== 'ImportDeclaration').map(node => script.slice(node.start, node.end)).join('\n')
  const props = reactive({ autoOpen })
  const scope = effectScope()
  const state = scope.run(() => new Function('ref', 'watch', 'defineProps', `${body}; return { open, activated, toggle };`)(ref, watch, () => props))
  return { props, ...state, close: () => scope.stop() }
}

test('execution disclosure follows lifecycle until the user takes ownership', async () => {
  const auto = foldHarness(true)
  assert.equal(auto.open.value, true)
  auto.props.autoOpen = false
  await nextTick()
  assert.equal(auto.open.value, false)
  assert.equal(auto.activated.value, true)
  auto.close()
  const manual = foldHarness(true)
  manual.toggle()
  manual.toggle()
  manual.props.autoOpen = false
  await nextTick()
  assert.equal(manual.open.value, true, 'manual expansion survives a terminal event')
  manual.close()
})

test('initially collapsed historical records defer body activation, keyboard click toggles it', () => {
  const fold = foldHarness(false)
  assert.equal(fold.activated.value, false)
  fold.toggle()
  assert.equal(fold.open.value, true)
  assert.equal(fold.activated.value, true)
  fold.close()
})

const plan = (sequence, todos) => event(sequence, 'todo_updated', { todos: todos.map(([content, status], i) => ({ id: String(i + 1), content, status })) })
const started = (sequence, callId) => event(sequence, 'tool_started', { callId, toolName: 'add_nodes' })
const completed = (sequence, callId) => event(sequence, 'tool_completed', { callId, toolName: 'add_nodes', toolOutput: '{"ok":true}' })
const tools = view => view.entries.filter(item => item.kind === 'tool')
const rows = blocks => blocks.filter(block => block.kind === 'execution').flatMap(block => block.rows)
const flatten = list => list.flatMap(row => row.kind === 'step' ? row.entries : [row])

test('tools remain with the step that was active when they started, even after late completion', () => {
  const input = [plan(1, [['读取', 'in_progress'], ['补充', 'pending']]), started(2, 'a'),
    plan(3, [['读取', 'completed'], ['补充', 'in_progress']]), started(4, 'b'), completed(5, 'a')]
  const original = JSON.stringify(input)
  const view = projectRuntimeEvents(input, { running: true })
  const [a, b] = tools(view)
  assert.equal(a.step.content, '读取')
  assert.equal(a.step.status, 'completed')
  assert.equal(a.status, 'completed')
  assert.equal(b.step.content, '补充')
  assert.equal(b.status, 'running')
  assert.equal(view.entries[0].todos[0].status, 'in_progress', 'old snapshots stay immutable')
  assert.equal(JSON.stringify(input), original)
})

test('plan reordering does not reassign historical calls via positional IDs', () => {
  const prefix = [plan(1, [['读取', 'in_progress'], ['补充', 'pending']]), started(2, 'a')]
  const previous = projectRuntimeEvents(prefix, { running: true })
  const next = projectRuntimeEvents([...prefix, plan(3, [['补充', 'in_progress'], ['读取', 'completed']]), started(4, 'b')], { running: true })
  assert.equal(tools(next)[0].step.key, tools(previous)[0].step.key)
  assert.equal(tools(next)[0].step.content, '读取')
  assert.equal(tools(next)[1].step.content, '补充')
  assert.deepEqual(next.todos.map(todo => todo.content), ['补充', '读取'])
})

test('removed and reintroduced steps keep separate histories and are never silently completed', () => {
  const view = projectRuntimeEvents([plan(1, [['粗步骤', 'in_progress'], ['检查', 'pending']]), started(2, 'a'),
    plan(3, [['细步骤', 'in_progress'], ['检查', 'pending']]), started(4, 'b'),
    plan(5, [['粗步骤', 'in_progress']]), started(6, 'c')], { running: true })
  const [a, b, c] = tools(view)
  assert.equal(a.step.removed, true)
  assert.equal(a.step.status, 'in_progress')
  assert.equal(b.step.removed, true)
  assert.notEqual(a.step.key, c.step.key)
  assert.equal(c.step.removed, undefined)
  assert.equal(agentStepState(a.step, { running: true }).label, '已从计划移除')
})

for (const todos of [[], [['尚未开始', 'pending']], [['甲', 'in_progress'], ['乙', 'in_progress']], [['重复', 'in_progress'], ['重复', 'pending']]]) {
  test(`ambiguous plan ${JSON.stringify(todos)} does not invent a tool owner`, () => {
    const view = projectRuntimeEvents([plan(1, todos), started(2, 'a')], { running: true })
    assert.equal(tools(view)[0].step, undefined)
    assert.equal(rows(buildAgentChatBlocks(view.entries)).some(row => row.kind === 'step'), false)
    assert.deepEqual(view.todos.map(todo => todo.status), todos.map(todo => todo[1]))
  })
}

test('a completion with no start does not borrow the latest active step', () => {
  const view = projectRuntimeEvents([plan(1, [['正在做', 'in_progress']]), completed(2, 'missing')], { running: true })
  assert.equal(tools(view)[0].step, undefined)
})

test('empty replacement snapshots retire old steps but preserve their tool records', () => {
  const view = projectRuntimeEvents([plan(1, [['旧步骤', 'in_progress']]), started(2, 'a'), plan(3, []), started(4, 'b')])
  assert.deepEqual(view.todos, [])
  assert.equal(tools(view)[0].step.removed, true)
  assert.equal(tools(view)[1].step, undefined)
  assert.equal(flatten(rows(buildAgentChatBlocks(view.entries))).length, view.entries.length)
})

test('step drawers preserve record order, prose boundaries and a single active occurrence', () => {
  const view = projectRuntimeEvents([plan(1, [['补充', 'in_progress']]), started(2, 'a'),
    event(3, 'thinking_summary', { text: '公开摘要', messageId: 's' }),
    event(4, 'assistant_delta', { text: '中途说明', messageId: 'm' }),
    event(5, 'thinking_state', {}), started(6, 'b')], { running: true })
  const blocks = buildAgentChatBlocks(view.entries)
  assert.deepEqual(blocks.map(block => block.kind), ['execution', 'message', 'execution'])
  const stepRows = rows(blocks).filter(row => row.kind === 'step')
  assert.deepEqual(stepRows.map(row => row.active), [false, true])
  assert.deepEqual(stepRows.map(row => row.entries.map(entry => entry.kind)), [['tool', 'summary'], ['thinking', 'tool']])
  assert.deepEqual(flatten(rows(blocks)).map(item => item.key), view.entries.filter(item => item.kind !== 'message').map(item => item.key))
})

test('step status uses actual plan evidence and cancellation, not successful tool inference', () => {
  const step = { status: 'in_progress' }
  assert.equal(agentStepState(step).label, '未确认完成')
  assert.equal(agentStepState(step, { cancelled: true }).label, '已中断')
  assert.equal(agentStepState(step, { running: true, active: true }).label, '进行中')
  assert.equal(agentStepState(step, { running: true, active: false }).label, '过程记录')
  assert.equal(agentStepState({ status: 'completed' }, { cancelled: true }).label, '已完成')
})

test('pagination bounds leaf records even inside a single large step and retains stable disclosure keys', () => {
  const view = projectRuntimeEvents([plan(1, [['补充', 'in_progress']]),
    ...Array.from({ length: 130 }, (_, i) => started(i + 2, `tool-${i}`))], { running: true })
  const full = rows(buildAgentChatBlocks(view.entries))
  const page = sliceAgentExecutionRows(full, 50)
  assert.equal(flatten(page).length, 50)
  assert.equal(page[0].key, full[1].key)
  assert.equal(page[0].entries[0].key, 'job:82')
  assert.equal(flatten(sliceAgentExecutionRows(full, 100)).length, 100)
  assert.equal(flatten(sliceAgentExecutionRows(full, 150)).length, 131)
  for (const value of [0, -1, NaN, undefined]) assert.deepEqual(sliceAgentExecutionRows(full, value), [])
})

test('every growing stream prefix remains lossless and side-effect-free after grouping', () => {
  const stream = []
  let seq = 0
  for (let round = 0; round < 12; round++) {
    stream.push(plan(++seq, [[`步骤 ${round}`, 'in_progress']]), started(++seq, `c${round}`),
      event(++seq, 'assistant_delta', { text: `${round}`, messageId: `m${round}` }), completed(++seq, `c${round}`))
  }
  for (let size = 1; size <= stream.length; size++) {
    const input = stream.slice(0, size)
    const frozen = JSON.stringify(input)
    const view = projectRuntimeEvents(input, { running: true })
    const blocks = buildAgentChatBlocks(view.entries)
    const actual = blocks.flatMap(block => block.kind === 'message' ? [block] : flatten(block.rows))
    assert.deepEqual(actual.map(item => item.key), view.entries.map(item => item.key))
    assert.equal(JSON.stringify(input), frozen)
    const compact = buildAgentChatBlocks(view.entries, '', { includePlans: false })
    const visible = compact.flatMap(block => block.kind === 'message' ? [block] : flatten(block.rows))
    assert.deepEqual(visible.map(item => item.key), view.entries.filter(item => item.kind !== 'plan').map(item => item.key))
    assert.equal(JSON.stringify(input), frozen, 'plan snapshots remain available in the separate history')
  }
})

test('screen-reader live regions announce task state, not every streamed transcript character', () => {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
  const template = parse(source).descriptor.template.content
  assert.match(template, /<ol\s+v-if="conversationTurns.length"[^>]*aria-live="off"/)
  assert.match(template, /role="status" aria-live="polite" aria-atomic="true">\s*第 \{\{ job.turnIndex \|\| 1 \}\} 轮 · \{\{ statusLabel \}\}/)
  assert.match(template, /class="jobPanel" aria-live="off"/)
})

test('step drawers open for active or failed work and close after confirmed completion', () => {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAgentTraceRows.vue', import.meta.url), 'utf8')
  const script = parse(source).descriptor.scriptSetup.content
  const fn = babelParse(script, { sourceType: 'module' }).program.body.find(node => node.type === 'FunctionDeclaration' && node.id.name === 'stepOpen')
  const props = { running: true, cancelled: false }
  const open = new Function('props', `${script.slice(fn.start, fn.end)}; return stepOpen`)(props)
  const step = { active: true, step: { status: 'in_progress' }, entries: [] }
  assert.equal(open(step), true)
  props.running = false
  step.active = false
  step.step.status = 'completed'
  assert.equal(open(step), false)
  step.entries = [{ kind: 'tool', status: 'failed' }]
  assert.equal(open(step), true)
  step.entries = []
  step.step.status = 'in_progress'
  props.cancelled = true
  assert.equal(open(step), true)
  step.step.status = 'completed'
  assert.equal(open(step), false)
})
