import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript, babelParse } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'
import * as Vue from 'vue'
import { formatAttachmentSize } from '../mindmap-ai-attachment-records.js'

const source = readFileSync(new URL('../../components/MindMap/MindmapAgentUserMessage.vue', import.meta.url), 'utf8')
const descriptor = parse(source).descriptor
const code = compileScript(descriptor, { id: 'user-message-test', inlineTemplate: true }).content

function productionComponent(dependencies) {
  const bindings = { ...dependencies }, body = []
  for (const node of babelParse(code, { sourceType: 'module' }).program.body) {
    if (node.type === 'ImportDeclaration') {
      for (const specifier of node.specifiers) {
        bindings[specifier.local.name] = node.source.value === 'vue'
          ? Vue[specifier.imported.name] : dependencies[specifier.local.name]
        assert.ok(bindings[specifier.local.name], `Missing production dependency: ${specifier.local.name}`)
      }
    } else if (node.type === 'ExportDefaultDeclaration') body.push(`return ${code.slice(node.declaration.start, node.declaration.end)}`)
    else body.push(code.slice(node.start, node.end))
  }
  return new Function(...Object.keys(bindings), body.join('\n'))(...Object.values(bindings))
}

function mount(input = {}, copy = async () => true) {
  const copies = [], errors = [], timers = new Map()
  let timerId = 0
  const Component = productionComponent({
    formatAttachmentSize,
    copyMindmapText: async text => { copies.push(text); return copy(text) },
    ElMessage: { error: message => errors.push(message) },
    setTimeout: callback => {
      const id = ++timerId
      timers.set(id, () => { timers.delete(id); callback() })
      return id
    },
    clearTimeout: id => timers.delete(id),
  })
  const node = (type, text = '') => ({ type, text, children: [], props: {} })
  const remove = child => {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
    child.parent = null
  }
  const renderer = Vue.createRenderer({
    createElement: type => node(type), createText: text => node('text', text), createComment: () => node('comment'),
    insert(child, parent, anchor) {
      if (child.parent) remove(child)
      child.parent = parent
      const index = parent.children.indexOf(anchor)
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
    },
    remove, parentNode: child => child.parent,
    nextSibling: child => child.parent?.children[child.parent.children.indexOf(child) + 1],
    setText: (el, text) => { el.text = text },
    setElementText: (el, text) => { el.text = text; el.children = [] },
    patchProp: (el, key, _old, value) => { el.props[key] = value },
  })
  const props = Vue.reactive({ content: '请补充登录失败的测试用例', ...input })
  const root = node('root')
  const app = renderer.createApp({ render: () => Vue.h(Component, props) })
  app.mount(root)
  const all = (el = root) => [el, ...el.children.flatMap(child => all(child))]
  const button = () => all().find(el => el.type === 'button')
  return {
    Component, props, all, button, copies, errors, timers,
    text: () => all().map(el => el.text).join(' '),
    copy: () => button().props.onClick(),
    close: () => app.unmount(),
  }
}

test('user message shows full send time instead of task ID below the bubble', () => {
  const h = mount({ jobId: 'd6a1d65d-810b-4a75-8e74-2e38c33f4cb2', createdTime: '2026-09-30T17:31:06' })
  try {
    assert.equal(h.all().find(el => el.props.class === 'userMessageBubble').text, h.props.content)
    assert.ok(!h.all().some(el => el.props.class === 'userMessageTaskId'))
    assert.doesNotMatch(h.text(), /d6a1d65d|任务 ID/)
    const time = h.all().find(el => el.type === 'time')
    assert.equal(time.props.class, 'userMessageTime')
    assert.equal(time.props.datetime, h.props.createdTime)
    assert.equal(time.text, '2026-09-30-17:31:06')
    assert.equal(time.props['aria-label'], '发送时间：2026-09-30-17:31:06')
    assert.equal(h.button().props['aria-label'], '复制内容')
    assert.ok(!h.all().some(el => el.text === '你'))
    assert.match(source, /padding: 10px 14px/)
    assert.match(source, /border-radius: 14px/)
    assert.match(source, /max-width: 280px/)
    assert.match(source, /font-size: 14px/)
    assert.match(source, /line-height: 1\.55/)
    assert.match(source, /20%, transparent/)
    assert.match(source, /12%, transparent/)
  } finally { h.close() }
})

const contextChip = h => h.all().find(el => el.props.class === 'userMessageContextChip')
const contextLabel = h => h.all().find(el => el.props.class === 'userMessageContextLabel')?.text

for (const [description, context, label, scope] of [
  ['omitted legacy context', undefined, '整个脑图', 'all'],
  ['empty legacy context', {}, '整个脑图', 'all'],
  ['whole-document authorization', { sourceMode: 'current', scopeType: 'document', contextNodes: [] }, '整个脑图', 'all'],
  ['document scope despite stale node labels', { sourceMode: 'current', scopeType: 'document', contextNodes: [{ uid: 'a', label: '不能误报的节点' }] }, '整个脑图', 'all'],
  ['single branch', { sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'a', label: '登录验证' }] }, '登录验证', 'one'],
  ['single selected node', { sourceMode: 'current', scopeType: 'selectedNodes', contextNodes: [{ uid: 'a', label: '验证码' }] }, '验证码', 'one'],
  ['multiple selected nodes', { sourceMode: 'current', scopeType: 'selectedNodes', contextNodes: [{ uid: 'a', label: '用户名' }, { uid: 'b', label: '密码' }] }, '用户已经选择2个节点', 'multi'],
  ['new map source', { sourceMode: 'new', scopeType: 'document', contextNodes: [] }, '新建脑图', 'new'],
  ['named local file source', { sourceMode: 'file', scopeType: 'document', fileName: '上传脑图.xmind' }, '上传脑图.xmind', 'file'],
  ['unnamed local file source', { sourceMode: 'file', scopeType: 'document' }, '本地文件', 'file'],
  ['missing branch label', { sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'a' }] }, '当前分支', 'one'],
  ['missing branch nodes', { sourceMode: 'current', scopeType: 'branch', contextNodes: [] }, '当前分支', 'one'],
  ['missing selected-node label', { sourceMode: 'current', scopeType: 'selectedNodes', contextNodes: [{ uid: 'a' }] }, '已选节点', 'one'],
  ['missing selected nodes', { sourceMode: 'current', scopeType: 'selectedNodes' }, '已选节点', 'one'],
  ['multiple unavailable labels', { sourceMode: 'current', scopeType: 'selectedNodes', contextNodes: [{ uid: 'a' }, { uid: 'b' }] }, '用户已经选择2个节点', 'multi'],
  ['explicitly unavailable context', null, '上下文不可用', 'unknown'],
]) {
  test(`saved message context: ${description}`, () => {
    const h = mount({ context })
    try {
      assert.equal(contextLabel(h), label)
      assert.equal(contextChip(h).props['data-scope'], scope)
      assert.equal(h.all().filter(el => el.type === 'button').length, 1, 'context is read-only, leaving only copy interactive')
      assert.ok(!h.all().some(el => el.props['aria-haspopup'] || el.props['aria-label']?.includes('取消选择')))
    } finally { h.close() }
  })
}

test('single-node labels truncate after ten characters while preserving full names in the tooltip', () => {
  for (const [label, display] of [
    ['一二三四五六七八九十', '一二三四五六七八九十'],
    ['一二三四五六七八九十一二', '一二三四五六七...'],
    ['😀一二三四五六七八九十', '😀一二三四五六...'],
  ]) {
    const h = mount({ context: { sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'a', label }] } })
    try {
      assert.equal(contextLabel(h), display)
      assert.equal(contextChip(h).props.title, label)
    } finally { h.close() }
  }
})

test('context and attachments share a read-only row below the prompt and above send time without a divider', async () => {
  const h = mount({
    context: { sourceMode: 'current', scopeType: 'selectedNodes', contextNodes: [{ uid: 'a', label: '用户名' }, { uid: 'b', label: '密码' }] },
    attachments: [{ id: 'file', name: '需求清单.pdf', size: 2048, text: 'PRIVATE_BODY' }],
    createdTime: '2026-10-01 08:09:10',
  })
  try {
    const group = h.all().find(el => el.props['data-group'] === 'context')
    const files = h.all().find(el => el.props['data-group'] === 'files')
    const bubble = h.all().find(el => el.props.class === 'userMessageBubble')
    const meta = h.all().find(el => el.props.class === 'userMessageMeta')
    assert.equal(group.parent, files.parent)
    assert.equal(group.parent.props.class, 'userMessageContextRow')
    assert.equal(bubble.parent, meta.parent)
    assert.ok(bubble.parent.children.indexOf(bubble) < bubble.parent.children.indexOf(group.parent), 'saved context follows the message bubble')
    assert.ok(bubble.parent.children.indexOf(group.parent) < bubble.parent.children.indexOf(meta), 'saved context precedes send time and copy actions')
    assert.equal(contextChip(h).props.title, '用户名、密码')
    assert.match(h.text(), /需求清单\.pdf.*2 KB/)
    assert.equal(h.all().find(el => el.type === 'time').text, '2026-10-01-08:09:10')
    assert.doesNotMatch(h.text(), /PRIVATE_BODY/)
    assert.equal(h.all().filter(el => el.type === 'button').length, 1)
    await h.copy()
    assert.deepEqual(h.copies, [h.props.content])
    assert.match(descriptor.styles[0].content, /\.userMessageContextRow\s*\{[^}]*flex-wrap: wrap/s)
    const fileGroupStyle = descriptor.styles[0].content.match(/\.userMessageFileGroup\s*\{([^}]*)\}/s)?.[1] || ''
    for (const [, value] of fileGroupStyle.matchAll(/border-(?:left|inline-start)\s*:\s*([^;]+)/g)) {
      assert.match(value.trim(), /^(?:0(?:px)?|none)$/, 'message context and attachments have no vertical separator')
    }
    assert.ok(!h.all().some(el => /(?:^|\s)composer(?:ChipGroup|FileGroup|ContextChip)(?:\s|$)/.test(el.props.class || '')), 'message styles cannot inherit composer-specific selectors')
  } finally { h.close() }
})

test('saved message scope does not follow later canvas or composer drafts and can hydrate from its own history', async () => {
  const draft = Vue.reactive({ sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'a', label: '发送时节点' }] })
  const h = mount({ context: JSON.parse(JSON.stringify(draft)) })
  try {
    draft.contextNodes[0].label = '后来改名的节点'
    draft.contextNodes.push({ uid: 'b', label: '后来选中的节点' })
    draft.scopeType = 'selectedNodes'
    await Vue.nextTick()
    assert.equal(contextLabel(h), '发送时节点')
    assert.equal(contextChip(h).props['data-scope'], 'one')
    h.props.context = null
    await Vue.nextTick()
    assert.equal(contextLabel(h), '上下文不可用')
    h.props.context = { sourceMode: 'current', scopeType: 'selectedNodes', contextNodes: [{ uid: 'c', label: '历史节点甲' }, { uid: 'd', label: '历史节点乙' }] }
    await Vue.nextTick()
    assert.equal(contextLabel(h), '用户已经选择2个节点')
    assert.equal(contextChip(h).props.title, '历史节点甲、历史节点乙')
  } finally { h.close() }
})

test('context node labels and source file names are escaped in visible text and full tooltips', async () => {
  for (const context of [
    { sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'a', label: '<img src=x onerror=alert(1)>' }] },
    { sourceMode: 'file', fileName: '<script>bad()</script>' },
  ]) {
    const h = mount({ context })
    try {
      const html = await renderToString(Vue.createSSRApp(h.Component, h.props))
      assert.doesNotMatch(html, /<img|<script>/)
      assert.match(html, /&lt;(?:img|script)/)
      assert.ok(!h.all().some(el => 'innerHTML' in el.props))
    } finally { h.close() }
  }
})

test('send time pads all fields and updates when the message timestamp changes', async () => {
  const h = mount({ createdTime: '2026-01-02 03:04:05' })
  try {
    assert.equal(h.all().find(el => el.type === 'time').text, '2026-01-02-03:04:05')
    h.props.createdTime = '2026-10-01T00:00:00'
    await Vue.nextTick()
    assert.equal(h.all().find(el => el.type === 'time').text, '2026-10-01-00:00:00')
    await h.copy()
    assert.deepEqual(h.copies, [h.props.content], 'copy still excludes metadata')
  } finally { h.close() }
})

test('ISO UTC and offset timestamps display in local time including date rollover', () => {
  const previousTimezone = process.env.TZ
  process.env.TZ = 'Asia/Shanghai'
  try {
    for (const createdTime of ['2026-09-30T16:04:05.678Z', '2026-09-30T18:04:05+02:00']) {
      const h = mount({ createdTime })
      try {
        assert.equal(h.all().find(el => el.type === 'time').text, '2026-10-01-00:04:05')
      } finally { h.close() }
    }
  } finally {
    if (previousTimezone === undefined) delete process.env.TZ
    else process.env.TZ = previousTimezone
  }
})

test('missing or invalid timestamps never invent a send time or expose a task ID', () => {
  for (const createdTime of ['', '  ', 'not-a-date']) {
    const h = mount({ createdTime, jobId: 'private-task-id' })
    try {
      assert.ok(!h.all().some(el => el.type === 'time'))
      assert.doesNotMatch(h.text(), /private-task-id|Invalid Date|NaN/)
      assert.equal(h.button().props['aria-label'], '复制内容')
    } finally { h.close() }
  }
})

test('sent attachments show metadata only and copy excludes attachment bodies and names', async () => {
  const h = mount({ attachments: [
    { id: 'a', name: '改版需求清单.pdf', size: 1258291, content: 'PRIVATE ATTACHMENT BODY' },
    { id: 'b', name: '竞品分析.docx', size: 884736 },
    { id: 'c', name: '空白.txt', size: 0 },
    { name: '', size: 4 }, null,
  ] })
  try {
    assert.equal(h.all().filter(el => el.props.class === 'userMessageAttachment').length, 3)
    assert.match(h.text(), /改版需求清单\.pdf.*1\.2 MB/)
    assert.match(h.text(), /竞品分析\.docx.*864 KB/)
    assert.match(h.text(), /空白\.txt.*0 B/)
    assert.doesNotMatch(h.text(), /PRIVATE ATTACHMENT BODY/)
    assert.equal(h.all().filter(el => el.type === 'button').length, 1, 'sent files cannot be removed from the historical message')
    await h.copy()
    assert.deepEqual(h.copies, [h.props.content])
  } finally { h.close() }
})

test('attachment names and prompts are escaped by the production Vue template', async () => {
  const h = mount({ content: '<img src=x onerror=alert(1)>', attachments: [{ name: '<script>bad()</script>', size: 10 }] })
  try {
    const html = await renderToString(Vue.createSSRApp(h.Component, h.props))
    assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/)
    assert.match(html, /&lt;script&gt;bad\(\)&lt;\/script&gt;/)
    assert.doesNotMatch(html, /<img|<script>/)
    assert.ok(!h.all().some(el => 'innerHTML' in el.props))
  } finally { h.close() }
})

test('copy completion is announced only after clipboard succeeds and resets predictably', async () => {
  let resolve
  const h = mount({}, () => new Promise(done => { resolve = done }))
  try {
    const sending = h.copy()
    await Vue.nextTick()
    assert.equal(h.button().props.disabled, true)
    assert.equal(h.button().props['aria-label'], '复制内容')
    await h.copy()
    assert.equal(h.copies.length, 1, 'duplicate clicks do not start another clipboard request')
    resolve(true)
    await sending
    await Vue.nextTick()
    assert.equal(h.button().props.disabled, false)
    assert.equal(h.button().props['aria-label'], '已复制内容')
    assert.equal(h.timers.size, 1)
    for (const callback of [...h.timers.values()]) callback()
    await Vue.nextTick()
    assert.equal(h.button().props['aria-label'], '复制内容')
    assert.equal(h.timers.size, 0)
  } finally { h.close() }
})

test('unmounting a copied message cancels its pending feedback timer', async () => {
  const h = mount()
  await h.copy()
  assert.equal(h.timers.size, 1)
  h.close()
  assert.equal(h.timers.size, 0)
})

test('failed copying reports a real error and permits retry without false success', async () => {
  let attempt = 0
  const h = mount({}, async () => { if (++attempt === 1) throw new Error('复制失败，请手动选择内容'); return true })
  try {
    await h.copy()
    await Vue.nextTick()
    assert.deepEqual(h.errors, ['复制失败，请手动选择内容'])
    assert.equal(h.button().props['aria-label'], '复制内容')
    assert.equal(h.button().props.disabled, false)
    assert.equal(h.timers.size, 0)
    await h.copy()
    await Vue.nextTick()
    assert.equal(h.button().props['aria-label'], '已复制内容')
  } finally { h.close() }
})

test('changing messages or unmounting invalidates stale clipboard results and clears feedback timers', async () => {
  let resolve
  const h = mount({}, () => new Promise(done => { resolve = done }))
  try {
    const sending = h.copy()
    h.props.content = '下一条用户消息'
    h.props.jobId = 'new-job'
    await Vue.nextTick()
    resolve(true)
    await sending
    await Vue.nextTick()
    assert.equal(h.button().props['aria-label'], '复制内容')
    assert.equal(h.timers.size, 0)
    const nextSending = h.copy()
    h.close()
    resolve(true)
    await nextSending
    assert.equal(h.timers.size, 0)
    assert.deepEqual(h.errors, [])
  } finally { h.close() }
})

test('empty prompts disable copying, and invalid historical metadata does not crash rendering', async () => {
  const h = mount({ content: '', jobId: '', attachments: [{ name: 'unknown.txt', size: -1 }, { name: 'large.txt', size: Infinity }] })
  try {
    assert.equal(h.button().props.disabled, true)
    await h.copy()
    assert.equal(h.copies.length, 0)
    assert.ok(!h.all().some(el => el.props.class === 'userMessageBubble'))
    assert.ok(!h.all().some(el => el.props.class === 'userMessageAttachmentSize'))
    h.props.attachments = null
    await Vue.nextTick()
    assert.ok(!h.all().some(el => el.props['data-group'] === 'files'))
  } finally { h.close() }
})
