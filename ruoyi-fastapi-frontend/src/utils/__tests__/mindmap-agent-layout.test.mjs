import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileTemplate } from '@vue/compiler-sfc'
import {
  DEFAULT_AGENT_PANEL_WIDTH, normalizeAgentPanelWidth, agentPanelBounds,
  agentPanelKeyboardWidth, createAgentPanelLayout,
} from '../mindmap-agent-layout.js'

test('the single transcript scroller never caps an overflowing history section on small screens', () => {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
  const css = parse(source).descriptor.styles.map(style => style.content).join('\n')
  assert.doesNotMatch(css, /\.activitySidebar\s*\{[^}]*max-height:\s*\d/,
    'a capped overflow:visible history paints on top of the following result card')
  assert.match(css, /\.mindmapAiDrawer \.aiDialogBody\s*\{[^}]*overflow-y:\s*auto/)
  assert.match(css, /\.mindmapAiDrawer \.activitySidebar\s*\{[^}]*flex:\s*0 0 auto/)
})

test('latest-message control is an accessible icon overlay inside the activity sidebar, not the footer', () => {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
  const sidebar = source.match(/<aside\b[\s\S]*?class="activitySidebar"[\s\S]*?<\/aside>/)?.[0] || ''
  const control = sidebar.match(/<div class="chatJumpLatestOverlay">([\s\S]*?)<\/div>/)?.[1] || ''
  assert.match(control, /v-if="!chatFollowing && conversationTurns.length"/)
  assert.match(control, /aria-label="回到最新消息"/)
  assert.match(control, /title="回到最新消息"/)
  assert.match(control, /@click="jumpToLatest"/)
  assert.match(control, /<el-icon aria-hidden="true"><ArrowDown \/><\/el-icon>/)
  assert.doesNotMatch(control, />\s*回到最新消息\s*</)
  const footer = source.slice(source.indexOf('<template #footer>'))
  assert.doesNotMatch(footer.split('</template>')[0], /chatJumpLatest/)
  const descriptor = parse(source).descriptor
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, id: 'agent-chat' }).errors, [])
})

test('latest-message overlay has zero layout height and leaves non-button pointer events to the transcript', () => {
  const css = readFileSync(new URL('../../components/MindMap/styles/agent-chat.scss', import.meta.url), 'utf8')
  const overlay = css.match(/\.chatJumpLatestOverlay\s*\{([^}]+)\}/)?.[1] || ''
  const button = css.match(/\.chatJumpLatest\s*\{([^}]+)\}/)?.[1] || ''
  assert.match(overlay, /position:\s*sticky/)
  assert.match(overlay, /bottom:\s*12px/)
  assert.match(overlay, /height:\s*0/)
  assert.match(overlay, /pointer-events:\s*none/)
  assert.match(button, /pointer-events:\s*auto/)
  assert.match(button, /position:\s*absolute/)
  assert.match(button, /bottom:\s*0/)
  assert.match(button, /border-radius:\s*50%/)
  assert.match(button, /width:\s*40px/)
  assert.match(button, /height:\s*40px/)
})

test('latest-message action follows only the existing chat viewport', () => {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
  const body = source.match(/function jumpToLatest\(\) \{([\s\S]*?)\n\}/)?.[1]
  assert.ok(body)
  const following = { value: false }
  const viewport = { scrollTop: 125, scrollHeight: 2600 }
  new Function('chatFollowing', 'chatScrollRef', body)(following, { value: viewport })
  assert.equal(following.value, true)
  assert.equal(viewport.scrollTop, 2600)
  assert.doesNotThrow(() => new Function('chatFollowing', 'chatScrollRef', body)(following, { value: null }))
})

test('saved width accepts only finite numbers and cannot inject CSS', () => {
  for (const value of [null, undefined, '', ' ', '440px', '440;display:none', {}, true, Infinity, NaN]) {
    assert.equal(normalizeAgentPanelWidth(value), DEFAULT_AGENT_PANEL_WIDTH)
  }
  assert.equal(normalizeAgentPanelWidth('512'), 512)
  assert.equal(normalizeAgentPanelWidth(511.6), 512)
  assert.equal(normalizeAgentPanelWidth(-10), 360)
  assert.equal(normalizeAgentPanelWidth(9000), 720)
})

test('desktop bounds leave canvas room and small screens use the existing full-width drawer', () => {
  assert.deepEqual(agentPanelBounds(1280), { desktop: true, min: 360, max: 720 })
  assert.deepEqual(agentPanelBounds(1000), { desktop: true, min: 360, max: 496 })
  assert.deepEqual(agentPanelBounds(800), { desktop: true, min: 360, max: 360 })
  assert.deepEqual(agentPanelBounds(760), { desktop: false, min: 760, max: 760 })
  assert.deepEqual(agentPanelBounds(380), { desktop: false, min: 380, max: 380 })
})

test('responsive clamping does not overwrite the preferred desktop width', () => {
  const writes = []
  const layout = createAgentPanelLayout({ read: () => '640', write: width => writes.push(width), viewport: 1280 })
  assert.equal(layout.width.value, 640)
  layout.setViewport(1000)
  assert.equal(layout.width.value, 496)
  layout.setViewport(380)
  assert.equal(layout.width.value, 380)
  layout.setViewport(1280)
  assert.equal(layout.width.value, 640)
  assert.deepEqual(writes, [])
})

test('dragging previews transient width and only committed gestures persist', () => {
  const writes = []
  const layout = createAgentPanelLayout({ read: () => '600', write: width => writes.push(width), viewport: 1280 })
  layout.preview(500)
  assert.equal(layout.width.value, 500)
  assert.equal(layout.resizing.value, true)
  assert.deepEqual(writes, [])
  layout.cancel()
  assert.equal(layout.width.value, 600)
  assert.equal(layout.resizing.value, false)
  layout.preview(9999)
  layout.commit(9999)
  assert.equal(layout.width.value, 720)
  assert.deepEqual(writes, [720])
  assert.equal(layout.resizing.value, false)
})

test('viewport changes cancel an in-flight resize without losing saved preference', () => {
  const layout = createAgentPanelLayout({ read: () => '610', viewport: 1280 })
  layout.preview(500)
  layout.setViewport(380)
  assert.equal(layout.resizing.value, false)
  assert.equal(layout.width.value, 380)
  layout.commit(380) // A late gesture cannot persist mobile width.
  layout.setViewport(1280)
  assert.equal(layout.width.value, 610)
})

test('unavailable storage does not break resizing, and reset restores the default', () => {
  const layout = createAgentPanelLayout({ read: () => { throw Error('blocked') }, write: () => { throw Error('quota') }, viewport: 1280 })
  assert.equal(layout.width.value, DEFAULT_AGENT_PANEL_WIDTH)
  layout.commit(500)
  assert.equal(layout.width.value, 500)
  layout.reset()
  assert.equal(layout.width.value, DEFAULT_AGENT_PANEL_WIDTH)
})

test('separator keyboard supports bounds, steps, reset and ignores editing shortcuts', () => {
  const bounds = agentPanelBounds(1280)
  assert.equal(agentPanelKeyboardWidth({ key: 'ArrowLeft' }, 440, bounds), 430)
  assert.equal(agentPanelKeyboardWidth({ key: 'ArrowRight', shiftKey: true }, 440, bounds), 480)
  assert.equal(agentPanelKeyboardWidth({ key: 'Home' }, 440, bounds), 360)
  assert.equal(agentPanelKeyboardWidth({ key: 'End' }, 440, bounds), 720)
  for (const event of [{ key: 'a' }, { key: 'ArrowRight', ctrlKey: true }, { key: 'ArrowLeft', isComposing: true }]) {
    assert.equal(agentPanelKeyboardWidth(event, 440, bounds), null)
  }
})

test('real panel and canvas consume the same layout source', () => {
  const dialog = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8')
  assert.match(dialog, /useMindmapAgentLayout/)
  assert.match(page, /useMindmapAgentLayout/)
  assert.match(dialog, /:width="agentPanelWidth"/)
  assert.match(page, /--mindmap-ai-panel-width/)
  assert.doesNotMatch(page, /--mindmap-workspace-left: calc\(var\(--mindmap-activity-width\) \+ 500px\)/)
  for (const name of ['MindmapAgentResizeHandle', 'MindmapAgentModeSwitch', 'MindmapAgentPanel']) {
    const source = readFileSync(new URL(`../../components/MindMap/${name}.vue`, import.meta.url), 'utf8')
    const descriptor = parse(source).descriptor
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, id: name }).errors, [])
  }
})
