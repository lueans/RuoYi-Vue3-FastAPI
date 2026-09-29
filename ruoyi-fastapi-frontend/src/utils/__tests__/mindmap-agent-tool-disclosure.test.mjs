import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript, babelParse } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { agentToolPresentation, formatAgentDuration } from '../mindmap-agent-presentation.js'
import { agentToolNodeTargets } from '../mindmap-agent-node-links.js'

// Compile the production templates and setup functions. No copied display logic.
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
const Tool = component('MindmapAgentToolRow', { MindmapAgentFold: Fold, agentToolPresentation, formatAgentDuration, agentToolNodeTargets })

function mount(entry) {
  const node = (type, text = '') => ({ type, text, children: [], props: {} })
  const remove = child => { if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null }
  const renderer = Vue.createRenderer({
    createElement: type => node(type), createText: text => node('text', text), createComment: () => node('comment'),
    insert(child, parent, anchor) { if (child.parent) remove(child); child.parent = parent; const index = parent.children.indexOf(anchor); parent.children.splice(index < 0 ? parent.children.length : index, 0, child) },
    remove,
    parentNode: child => child.parent, nextSibling: child => child.parent?.children[child.parent.children.indexOf(child) + 1],
    setText: (el, text) => { el.text = text }, setElementText: (el, text) => { el.text = text; el.children = [] },
    patchProp: (el, key, old, value) => { el.props[key] = value },
  })
  const props = Vue.reactive({ entry })
  const root = node('root')
  const app = renderer.createApp({ render: () => Vue.h(Tool, props) })
  app.component('el-icon', { setup: (_, { slots }) => () => slots.default?.() })
  app.mount(root)
  const all = (el = root) => [el, ...el.children.flatMap(child => all(child))]
  return { props, all, text: () => all().map(el => el.text).join(' '), close: () => app.unmount() }
}
const failed = { key: 't', name: 'add_nodes', status: 'failed', error: '目标分支已被修改', input: '{"nodes":[{"text":"测试节点"}]}' }

test('failed tools show the reason immediately but defer raw parameters until requested', async () => {
  const h = mount(failed)
  try {
    assert.match(h.text(), /目标分支已被修改/)
    assert.ok(!h.all().some(el => el.type === 'pre'), 'JSON is not mounted by the automatic failure expansion')
    const details = h.all().find(el => el.type === 'summary' && el.props['aria-label'] === '调用参数与返回详情')
    assert.ok(details)
    details.props.onClick({ preventDefault() {} })
    await Vue.nextTick()
    assert.ok(h.all().some(el => el.type === 'pre'))
    assert.match(h.text(), /测试节点/)
  } finally { h.close() }
})

test('failure without a provider reason is explicit and does not invent rollback', () => {
  const h = mount({ ...failed, error: '', input: '', output: '' })
  try {
    assert.match(h.text(), /未提供具体原因/)
    assert.match(h.text(), /保存状态以.*回执为准/)
    assert.ok(!h.all().some(el => el.props['aria-label'] === '调用参数与返回详情'))
  } finally { h.close() }
})

test('late failure opens its cause, and later stream updates preserve manual detail expansion', async () => {
  const h = mount({ ...failed, status: 'running', error: '' })
  try {
    h.props.entry = { ...failed }
    await Vue.nextTick()
    assert.match(h.text(), /目标分支已被修改/)
    assert.ok(!h.all().some(el => el.type === 'pre'))
    const detail = h.all().find(el => el.props['aria-label'] === '调用参数与返回详情')
    detail.props.onClick({ preventDefault() {} })
    await Vue.nextTick()
    h.props.entry = { ...failed, output: '{"error":"新的诊断"}' }
    await Vue.nextTick()
    assert.equal(h.all().find(el => el.props['aria-label'] === '调用参数与返回详情').parent.props.open, true)
    assert.match(h.text(), /新的诊断/)
  } finally { h.close() }
})
