import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileTemplate } from '@vue/compiler-sfc'
import { parse as parseJs } from '@babel/parser'
import { effectScope, markRaw, nextTick, reactive, ref, watch } from 'vue'
import { agentPanelKeyboardWidth } from '../mindmap-agent-layout.js'

const sourceOf = name => readFileSync(new URL(`../../components/MindMap/${name}.vue`, import.meta.url), 'utf8')

function setupComponent(name, props, extras, names) {
  const source = parse(sourceOf(name)).descriptor.scriptSetup.content
  const body = parseJs(source, { sourceType: 'module' }).program.body
    .filter(node => node.type !== 'ImportDeclaration'
      && !(node.type === 'ExpressionStatement' && node.expression.callee?.name === 'defineOptions')
      && !node.declarations?.some(item => ['props', 'emit'].includes(item.id.name)))
    .map(node => source.slice(node.start, node.end)).join('\n')
  const effects = effectScope()
  let dispose
  const scope = { ref, watch, nextTick, props, onBeforeUnmount: fn => { dispose = fn }, ...extras }
  const result = effects.run(() => new Function(...Object.keys(scope), `${body}; return {${names.join(',')}}`)(...Object.values(scope)))
  return { ...result, dispose: () => { dispose?.(); effects.stop() } }
}

test('chat is a named non-modal region, not an Element Plus modal drawer', () => {
  const source = sourceOf('MindmapAiDialog')
  assert.match(source, /<MindmapAgentPanel\b/)
  assert.doesNotMatch(source, /<el-drawer\b/)
  const panel = sourceOf('MindmapAgentPanel')
  assert.match(panel, /<aside\b[^>]*[\s\S]*?:aria-label="label"/)
  assert.doesNotMatch(panel, /aria-modal|FocusTrap|el-drawer\b/)
  assert.match(panel, /v-show="modelValue"/)
  assert.match(panel, /@after-leave="afterLeave"/)
  assert.deepEqual(compileTemplate({ source: parse(panel).descriptor.template.content, id: 'agent-panel' }).errors, [])
})

function panelHarness() {
  const events = []
  const document = { activeElement: null, body: {} }
  const target = () => ({ isConnected: true, focus() { document.activeElement = this } })
  const opener = target(), canvas = target(), inside = target()
  const panel = markRaw({ ...target(), contains: item => item === inside || item === panel })
  document.activeElement = opener
  const props = reactive({ modelValue: false })
  const state = setupComponent('MindmapAgentPanel', props, { document, emit: (...args) => events.push(args) }, ['panelRef', 'rendered', 'afterLeave'])
  state.panelRef.value = panel
  return { props, document, opener, canvas, inside, panel, events, ...state }
}

test('panel opens accessibly, remains mounted when hidden, and restores its trigger focus', async () => {
  const h = panelHarness()
  assert.equal(h.rendered.value, false)
  h.props.modelValue = true
  await nextTick(); await nextTick()
  assert.equal(h.document.activeElement, h.panel)
  assert.equal(h.rendered.value, true)
  h.document.activeElement = h.inside
  h.props.modelValue = false
  await nextTick(); await nextTick()
  assert.equal(h.document.activeElement, h.opener)
  assert.equal(h.rendered.value, true)
  h.afterLeave()
  assert.deepEqual(h.events, [['closed']])
  h.dispose()
})

test('closing while using the canvas does not steal focus; obsolete close callbacks are ignored', async () => {
  const h = panelHarness()
  h.props.modelValue = true
  await nextTick(); await nextTick()
  h.document.activeElement = h.canvas
  h.props.modelValue = false
  await nextTick(); await nextTick()
  assert.equal(h.document.activeElement, h.canvas)
  h.props.modelValue = true
  h.afterLeave()
  assert.deepEqual(h.events, [])
  h.dispose()
})

test('unmount invalidates pending focus work', async () => {
  const h = panelHarness()
  h.props.modelValue = true
  await nextTick()
  h.dispose()
  h.document.activeElement = h.canvas
  await nextTick()
  assert.equal(h.document.activeElement, h.canvas)
})

function escapeHarness() {
  const script = parse(sourceOf('MindmapAiDialog')).descriptor.scriptSetup.content
  const functions = parseJs(script, { sourceType: 'module' }).program.body
    .filter(node => node.type === 'FunctionDeclaration' && ['closeContextPicker', 'closeSessionMenu', 'onPanelEscape', 'requestDialogClose'].includes(node.id.name))
    .map(node => script.slice(node.start, node.end)).join('\n')
  const focused = []
  const scope = { visible: ref(true), contextPickerVisible: ref(false), sessionMenuVisible: ref(false),
    contextTriggerRef: ref({ focus: () => focused.push('context') }), sessionTriggerRef: ref({ focus: () => focused.push('session') }) }
  return { ...scope, focused, ...new Function(...Object.keys(scope), `${functions};return {onPanelEscape,closeContextPicker,closeSessionMenu}`)(...Object.values(scope)) }
}
const escapeEvent = extra => ({ key: 'Escape', defaultPrevented: false, stopped: false,
  preventDefault() { this.defaultPrevented = true }, stopPropagation() { this.stopped = true }, ...extra })

test('Escape closes only the highest chat popover and returns focus to its trigger', () => {
  for (const [key, target] of [['contextPickerVisible', 'context'], ['sessionMenuVisible', 'session']]) {
    const h = escapeHarness(); h[key].value = true
    const event = escapeEvent()
    h.onPanelEscape(event)
    assert.equal(h[key].value, false)
    assert.equal(h.visible.value, true)
    assert.deepEqual(h.focused, [target])
    assert.equal(event.stopped, true)
    h.onPanelEscape(escapeEvent())
    assert.equal(h.visible.value, false)
  }
})

test('IME and Escape already owned by composer stop or split resize do not hide the panel', () => {
  const h = escapeHarness()
  h.onPanelEscape(escapeEvent({ isComposing: true }))
  h.onPanelEscape(escapeEvent({ defaultPrevented: true }))
  assert.equal(h.visible.value, true)
})

test('write-policy Escape hides its note, not the surrounding workbench', () => {
  const events = [], focused = []
  const h = setupComponent('MindmapAgentWritePolicy', reactive({ active: true, label: '编辑', description: '说明' }),
    { emit: (...args) => events.push(args) }, ['open', 'triggerRef', 'dismiss'])
  h.triggerRef.value = { focus: () => focused.push(true) }
  h.open.value = true
  const event = escapeEvent()
  h.dismiss(event)
  assert.equal(h.open.value, false)
  assert.equal(event.stopped, true)
  assert.deepEqual(focused, [true])
  const idle = escapeEvent()
  h.dismiss(idle)
  assert.equal(idle.defaultPrevented, false)
  h.dispose()
})

function separatorHarness() {
  let nextFrame = 0
  const frames = new Map(), listeners = new Map(), events = []
  let capture = null
  const target = { focus() {}, setPointerCapture(id) { capture = id }, hasPointerCapture: id => capture === id,
    releasePointerCapture() { capture = null } }
  const props = reactive({ active: true, width: 440, bounds: { desktop: true, min: 360, max: 720 } })
  const h = setupComponent('MindmapAgentResizeHandle', props, {
    emit: (...args) => events.push(args), agentPanelKeyboardWidth,
    requestAnimationFrame: fn => { frames.set(++nextFrame, fn); return nextFrame }, cancelAnimationFrame: id => frames.delete(id),
    window: { addEventListener: (type, fn) => listeners.set(type, fn), removeEventListener: type => listeners.delete(type) },
  }, ['start', 'move', 'finish', 'cancel', 'keydown'])
  return { ...h, props, events, listeners, frames,
    pointer: (clientX, pointerId = 1) => ({ clientX, pointerId, button: 0, currentTarget: target, preventDefault() {} }),
    flush() { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn()) } }
}

test('split pointer updates coalesce, can return to origin and flush final pointer-up position', () => {
  const h = separatorHarness()
  h.start(h.pointer(440))
  h.move(h.pointer(450)); h.move(h.pointer(510))
  assert.equal(h.frames.size, 1)
  h.flush()
  h.move(h.pointer(440)); h.flush()
  h.move(h.pointer(550)); h.finish(h.pointer(560)); h.flush()
  assert.deepEqual(h.events, [['preview', 510], ['preview', 440], ['commit', 560]])
  assert.equal(h.listeners.size, 0)
  h.dispose()
})

test('split clicks and other pointers do not save; blur and hidden panels cancel uncommitted gestures', async () => {
  const h = separatorHarness()
  h.start(h.pointer(440)); h.move(h.pointer(550, 2)); h.finish(h.pointer(440))
  assert.deepEqual(h.events, [])
  h.start(h.pointer(440)); h.move(h.pointer(540)); h.listeners.get('blur')(); h.flush()
  assert.deepEqual(h.events, [['cancel']])
  h.start(h.pointer(440)); h.props.active = false
  await nextTick()
  assert.deepEqual(h.events, [['cancel'], ['cancel']])
  assert.equal(h.listeners.size, 0)
  h.dispose()
})

test('split Escape cancels dragging and unmount removes pending animation work', () => {
  const h = separatorHarness()
  h.start(h.pointer(440)); h.move(h.pointer(500))
  const event = escapeEvent(); h.keydown(event)
  assert.equal(event.defaultPrevented, true)
  assert.deepEqual(h.events, [['cancel']])
  h.start(h.pointer(440)); h.move(h.pointer(550)); h.dispose(); h.flush()
  assert.deepEqual(h.events, [['cancel'], ['cancel']])
  assert.equal(h.listeners.size, 0)
})
