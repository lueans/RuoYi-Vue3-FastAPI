import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createMindmapCanvasResize } from '../mindmap-canvas-resize.js'

function harness() {
  let id = 0, calls = 0
  const frames = new Map()
  const rect = { width: 736, height: 622, left: 492, top: 60 }
  const element = { isConnected: true, getBoundingClientRect: () => ({ ...rect }) }
  let mindmap = { el: element, resize() { calls++ } }
  const control = createMindmapCanvasResize({ getElement: () => element, getMindmap: () => mindmap,
    requestFrame: fn => { frames.set(++id, fn); return id }, cancelFrame: id => frames.delete(id) })
  return { ...control, element, rect, frames, calls: () => calls, replace: value => { mindmap = value },
    flush() { const batch = [...frames.values()]; frames.clear(); batch.forEach(fn => fn()) } }
}

test('canvas resize coalesces frames and reads current rather than queued dimensions', () => {
  const h = harness()
  h.schedule(); h.schedule(); h.rect.width = 600
  assert.equal(h.frames.size, 1)
  h.flush()
  assert.equal(h.calls(), 1)
  h.rect.width = 736
  h.schedule(); h.flush()
  assert.equal(h.calls(), 2)
})

test('hidden, detached and replaced canvases never call the renderer with zero dimensions', () => {
  for (const invalidate of [h => { h.rect.width = 0 }, h => { h.rect.height = 0 },
    h => { h.element.isConnected = false }, h => h.replace(null), h => h.replace({ el: {}, resize() { throw Error('wrong canvas') } })]) {
    const h = harness(); h.schedule(); invalidate(h); h.flush(); assert.equal(h.calls(), 0)
  }
})

test('disposal cancels queued work and future notifications', () => {
  const h = harness()
  h.schedule(); h.dispose(); h.schedule(); h.flush()
  assert.equal(h.frames.size, 0)
  assert.equal(h.calls(), 0)
})

test('real canvas observes geometry and cleans up observer independently of window resize', () => {
  const source = readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8')
  assert.match(source, /new ResizeObserver\(handleResize\)/)
  assert.match(source, /canvasResizeObserver\.observe\(mindMapContainerRef\.value\)/)
  assert.match(source, /canvasResizeObserver\?\.disconnect\(\)/)
  assert.match(source, /canvasResize\.dispose\(\)/)
  const page = readFileSync(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8')
  assert.match(page, /is-ai-resizing[\s\S]*?:deep\(\.mindMapContainer\)[\s\S]*?transition: none/)
})
