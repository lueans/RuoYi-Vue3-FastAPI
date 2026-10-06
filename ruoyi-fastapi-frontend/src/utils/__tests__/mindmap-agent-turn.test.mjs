import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript, babelParse } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import * as presentation from '../mindmap-agent-presentation.js'
import { agentToolNodeTargets } from '../mindmap-agent-node-links.js'
import { buildAgentTurnBlocks, agentTurnExecutionState, sliceAgentExecutionRows } from '../mindmap-agent-presentation.js'
import { createRuntimeEventProjector, projectRuntimeEvents } from '../mindmap-ai-runtime.js'

const flatten = rows => rows.flatMap(row => row.kind === 'step' ? row.entries : [row])
const records = blocks => blocks.flatMap(block => block.kind === 'execution' ? flatten(block.rows) : [block])
const message = (key, text) => ({ key, kind: 'message', text })
const tool = (key, status = 'completed') => ({ key, kind: 'tool', name: 'add_nodes', status })

test('editing uses one stable execution container across every growing stream prefix', () => {
  const entries = [message('a', '先读取'), tool('b'), message('c', '继续补充'), tool('d', 'running'), message('e', '正在检查')]
  for (let size = 0; size <= entries.length; size++) {
    const prefix = entries.slice(0, size)
    const before = JSON.stringify(prefix)
    const blocks = buildAgentTurnBlocks(prefix, '', { running: true })
    assert.equal(blocks.length, 1)
    assert.equal(blocks[0].kind, 'execution')
    assert.equal(blocks[0].key, 'execution:turn')
    assert.deepEqual(records(blocks).map(record => record.key), prefix.map(record => record.key))
    assert.equal(JSON.stringify(prefix), before)
  }
})

test('only terminal trailing prose is lifted, in order, without removing earlier records', () => {
  const entries = [message('a', '读取完成'), tool('b'), message('c', '已新增三项。'), message('d', '请查看画布。')]
  const before = structuredClone(entries)
  const blocks = buildAgentTurnBlocks(entries, '已新增三项。\n请查看画布。')
  assert.deepEqual(blocks.map(block => block.kind), ['execution', 'message', 'message'])
  assert.deepEqual(records(blocks).map(record => record.key), ['a', 'b', 'c', 'd'])
  assert.deepEqual(entries, before)
  assert.equal(buildAgentTurnBlocks(entries, '', { running: true })[0].entries.length, 4)
})

test('interruption and failure retain partial prose in the execution record', () => {
  for (const status of [{ cancelled: true }, { failed: true }]) {
    const entries = [tool('t', 'unknown'), message('m', '准备删除下一组')]
    const blocks = buildAgentTurnBlocks(entries, '本轮尚未完成。', status)
    assert.equal(blocks[0].entries.length, 2)
    assert.equal(blocks[1].text, '本轮尚未完成。')
    assert.equal(blocks[1].key, 'final')
    assert.deepEqual(records(blocks).map(record => record.key), ['t', 'm', 'final'])
  }
})

test('discussion keeps visible prose streaming outside tool records, independently per turn', () => {
  const entries = [message('a', '讨论前'), tool('b'), message('c', '讨论后')]
  assert.deepEqual(buildAgentTurnBlocks(entries, '', { running: true, discussion: true }).map(block => block.kind), ['message', 'execution', 'message'])
  assert.equal(buildAgentTurnBlocks(entries, '', { running: true }).length, 1)
  assert.equal(buildAgentTurnBlocks([message('r', '建议一')], '建议一', { discussion: true }).length, 1)
})

test('legacy adjacent duplicate prose stays accessible without obscuring the final answer', () => {
  const entries = [message('a', '读取完成'), message('b', '读取完成'), tool('c'), message('d', '结论'), message('e', '结论')]
  const blocks = buildAgentTurnBlocks(entries, '结论')
  assert.equal(blocks.length, 2)
  assert.deepEqual(blocks[0].entries[0].repeatedMessages, [entries[1]])
  assert.deepEqual(blocks[1].repeatedMessages, [entries[4]])
  assert.equal(blocks[1].text, '结论')
  assert.equal(buildAgentTurnBlocks(entries, '', { running: true })[0].entries.length, 5)
})

test('final prose preserves Markdown whitespace and distinct host fallback text', () => {
  assert.deepEqual(buildAgentTurnBlocks([], ''), [])
  assert.equal(buildAgentTurnBlocks([], '没有过程记录的回答')[0].text, '没有过程记录的回答')
  assert.equal(buildAgentTurnBlocks([message('m', '第一行\n第二行')], '第一行 第二行').length, 2)
  assert.equal(buildAgentTurnBlocks([message('m', '结论')], '系统已确认保存')[1].text, '系统已确认保存')
  assert.equal(buildAgentTurnBlocks([], '迟到的旧摘要', { running: true }).length, 1)
})

test('one execution container retains Todo ownership, ordering and bounded leaf pagination', () => {
  const event = (sequence, eventType, payload) => ({ key: `j:${sequence}`, sequence, eventType, payload })
  const events = [event(1, 'todo_updated', { todos: [{ content: '补充', status: 'in_progress' }] })]
  for (let i = 0; i < 60; i++) {
    events.push(event(i * 2 + 2, 'tool_started', { callId: `c${i}`, toolName: 'add_nodes' }))
    events.push(event(i * 2 + 3, 'assistant_delta', { messageId: `m${i}`, text: `第 ${i} 批` }))
  }
  const view = projectRuntimeEvents(events, { running: true })
  const blocks = buildAgentTurnBlocks(view.entries, '', { running: true })
  const expected = view.entries.filter(entry => entry.kind !== 'plan')
  assert.deepEqual(records(blocks).map(entry => entry.key), expected.map(entry => entry.key))
  assert.equal(blocks[0].rows.filter(row => row.kind === 'step' && row.active).length, 1)
  const page = sliceAgentExecutionRows(blocks[0].rows, 50)
  assert.equal(flatten(page).length, 50)
  assert.deepEqual(flatten(page).map(entry => entry.key), expected.slice(-50).map(entry => entry.key))
})

test('process summary does not confuse a failed call with a failed turn or a save receipt', () => {
  assert.equal(agentTurnExecutionState([], { running: true }).label, '进行中')
  assert.equal(agentTurnExecutionState([tool('t', 'failed')]).label, '记录已结束 · 含失败调用')
  assert.equal(agentTurnExecutionState([tool('t', 'failed')], { failed: true }).label, '执行失败')
  assert.equal(agentTurnExecutionState([tool('t', 'unknown')]).label, '记录已结束 · 有调用未确认')
  assert.equal(agentTurnExecutionState([tool('t', 'cancelled')], { cancelled: true }).label, '已中断')
  assert.equal(agentTurnExecutionState([tool('t')]).label, '记录已结束')
  for (const entries of [[], [tool('t')], [tool('t', 'failed')]]) {
    assert.doesNotMatch(agentTurnExecutionState(entries).label, /保存|成功/)
  }
})

// Mount the production Trace -> Rows -> Fold/Tool/Markdown tree, not a copied
// template. A tiny renderer is sufficient for lifecycle and disclosure state.
function component(name, dependencies = {}) {
  const descriptor = parse(readFileSync(new URL(`../../components/MindMap/${name}.vue`, import.meta.url), 'utf8')).descriptor
  const code = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  const bindings = {}, body = []
  for (const node of babelParse(code, { sourceType: 'module' }).program.body) {
    if (node.type === 'ImportDeclaration') {
      for (const specifier of node.specifiers) {
        bindings[specifier.local.name] = node.source.value === 'vue' ? Vue[specifier.imported.name]
          : node.source.value === '@element-plus/icons-vue' ? Vue.defineComponent({ render: () => null })
            : dependencies[specifier.local.name]
        assert.ok(bindings[specifier.local.name], `Missing production dependency: ${specifier.local.name}`)
      }
    } else if (node.type === 'ExportDefaultDeclaration') body.push(`return ${code.slice(node.declaration.start, node.declaration.end)}`)
    else body.push(code.slice(node.start, node.end))
  }
  return new Function(...Object.keys(bindings), body.join('\n'))(...Object.values(bindings))
}
const Fold = component('MindmapAgentFold')
const Markdown = component('MindmapAgentMarkdown', presentation)
const Tool = component('MindmapAgentToolRow', { ...presentation, MindmapAgentFold: Fold, agentToolNodeTargets })
const Rows = component('MindmapAgentTraceRows', { ...presentation, MindmapAgentFold: Fold, MindmapAgentMarkdown: Markdown, MindmapAgentToolRow: Tool })
const Trace = component('MindmapAgentTrace', { ...presentation, createRuntimeEventProjector, MindmapAgentFold: Fold, MindmapAgentMarkdown: Markdown, MindmapAgentTraceRows: Rows })

function mount(input = {}) {
  const node = (type, text = '') => ({ type, text, children: [], props: {} })
  const remove = child => { if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null }
  const renderer = Vue.createRenderer({
    createElement: type => node(type), createText: text => node('text', text), createComment: () => node('comment'),
    insert(child, parent, anchor) { if (child.parent) remove(child); child.parent = parent; const index = parent.children.indexOf(anchor); parent.children.splice(index < 0 ? parent.children.length : index, 0, child) },
    remove, parentNode: child => child.parent, nextSibling: child => child.parent?.children[child.parent.children.indexOf(child) + 1],
    setText: (el, text) => { el.text = text }, setElementText: (el, text) => { el.text = text; el.children = [] },
    patchProp: (el, key, old, value) => { el.props[key] = value },
  })
  const props = Vue.reactive({ events: [], running: false, ...input })
  const root = node('root')
  const app = renderer.createApp({ render: () => Vue.h(Trace, props) })
  app.component('el-icon', { setup: (_, { slots }) => () => Vue.h('span', {}, slots.default?.()) })
  app.mount(root)
  const all = (el = root) => [el, ...el.children.flatMap(child => all(child))]
  const visible = el => {
    for (let child = el; child.parent; child = child.parent) {
      if (child.parent.type === 'details' && !child.parent.props.open && child.type !== 'summary') return false
    }
    return true
  }
  const shells = () => all().filter(el => el.type === 'summary' && el.props['aria-label']?.endsWith(' · 执行记录'))
  return { props, all, shells, text: () => all().filter(visible).map(el => `${el.text} ${el.props.innerHTML || ''}`).join(' '), close: () => app.unmount() }
}
const event = (sequence, eventType, payload) => ({ key: `turn:${sequence}`, sequence, eventType, payload })
const liveEvents = [
  event(1, 'assistant_delta', { messageId: 'a', text: '先检查现有节点' }),
  event(2, 'tool_started', { callId: 't', toolName: 'add_nodes', toolInput: '{}' }),
  event(3, 'assistant_delta', { messageId: 'b', text: '正在补充异常场景' }),
]

test('production editing trace keeps one mounted shell from empty wait through terminal collapse', async () => {
  const h = mount({ running: true })
  try {
    const shell = h.shells()[0].parent
    assert.match(h.text(), /正在等待 Agent 输出/)
    h.props.events = liveEvents
    await Vue.nextTick()
    assert.equal(h.shells().length, 1)
    assert.equal(h.shells()[0].parent, shell)
    assert.match(h.text(), /先检查现有节点.*正在补充异常场景/)
    h.props.events = [...liveEvents,
      event(4, 'tool_completed', { callId: 't', toolName: 'add_nodes', toolOutput: '{"createdCount":3}' }),
      event(5, 'assistant_delta', { messageId: 'final', text: '新增了三个异常场景' })]
    h.props.running = false
    h.props.finalContent = '新增了三个异常场景'
    await Vue.nextTick()
    assert.equal(h.shells()[0].parent, shell)
    assert.equal(shell.props.open, false)
    assert.doesNotMatch(h.text(), /先检查现有节点/)
    assert.match(h.text(), /新增了三个异常场景/)
    h.shells()[0].props.onClick({ preventDefault() {} })
    await Vue.nextTick()
    assert.match(h.text(), /先检查现有节点/)
  } finally { h.close() }
})

test('manual collapse survives additional prose, tool boundaries and completion', async () => {
  const h = mount({ events: liveEvents, running: true })
  try {
    const shell = h.shells()[0].parent
    h.shells()[0].props.onClick({ preventDefault() {} })
    await Vue.nextTick()
    h.props.events = [...liveEvents, event(4, 'tool_started', { callId: 't2', toolName: 'validate_draft' })]
    await Vue.nextTick()
    assert.equal(h.shells()[0].parent, shell)
    assert.equal(shell.props.open, false)
    h.props.running = false
    h.props.finalContent = '本轮记录结束'
    await Vue.nextTick()
    assert.equal(shell.props.open, false)
    assert.match(h.text(), /本轮记录结束/)
  } finally { h.close() }
})

test('manual expansion, cancellation and failure retain accessible process content', async () => {
  const h = mount({ events: liveEvents, running: true })
  try {
    const click = () => h.shells()[0].props.onClick({ preventDefault() {} })
    click(); await Vue.nextTick(); click(); await Vue.nextTick()
    h.props.running = false
    h.props.cancelled = true
    await Vue.nextTick()
    assert.equal(h.shells()[0].parent.props.open, true)
    assert.match(h.text(), /正在补充异常场景/)
    assert.match(h.text(), /本轮已中断/)
  } finally { h.close() }
  const failed = mount({ events: [...liveEvents, event(4, 'tool_failed', { callId: 't', errorMessage: '授权范围发生变化' })], failed: true })
  try { assert.match(failed.text(), /授权范围发生变化/) } finally { failed.close() }
})

test('production discussion exposes streamed body and binds mode to each historical turn', () => {
  const h = mount({ events: liveEvents, running: true, discussion: true })
  try { assert.match(h.text(), /先检查现有节点.*正在补充异常场景/) } finally { h.close() }
  const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
  assert.match(source, /:discussion="isMindmapAiMessageJob\(turn.job\)"/)
  assert.match(source, /running \? '实时' : '当前轮'/)
})
