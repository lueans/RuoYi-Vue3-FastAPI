import test from 'node:test'
import assert from 'node:assert/strict'
import { createMindmapAiCamera, panMindmapAiNodeIntoView } from '../mindmap-ai-camera.js'

function harness() {
  const translations = [], changes = [], timers = new Map(), listeners = new Set()
  let timerId = 0
  const transform = { scaleX: 1, scaleY: 1, translateX: 0, translateY: 0 }
  const nodes = { a: { left: 100, top: 100, width: 120, height: 40 }, b: { left: 900, top: 600, width: 120, height: 40 } }
  const map = {
    width: 800, height: 500, draw: { transform: () => ({ ...transform }) },
    renderer: { findNodeByUid: uid => nodes[uid] },
    view: { translateXY(x, y) {
      translations.push([x, y]); transform.translateX += x; transform.translateY += y
      listeners.forEach(fn => fn())
    } },
    on: (_event, fn) => listeners.add(fn), off: (_event, fn) => listeners.delete(fn),
  }
  const state = { map, session: { jobId: 'job1' } }
  const camera = createMindmapAiCamera({ getMindmap: () => state.map, getSession: () => state.session,
    onFollowingChange: value => changes.push(value),
    setTimer: fn => { timers.set(++timerId, fn); return timerId }, clearTimer: id => timers.delete(id),
  })
  return { map, state, nodes, transform, camera, translations, changes, timers, listeners,
    focus: (uid, cursor = 1) => camera.focus({ jobId: state.session.jobId, nodeUids: [uid], focusKey: `job1:${cursor}:${uid}` }),
    tick() { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(fn => fn()) },
  }
}

test('默认固定视角：旧图再次编辑跨分支也不自动平移', () => {
  const h = harness()
  for (const uid of ['a', 'b', 'a']) h.focus(uid)
  h.tick()
  assert.deepEqual(h.translations, [])
  assert.equal(h.timers.size, 0)
})
test('显式跟随只平移屏外节点，合并连续帧且不重置缩放', () => {
  const h = harness()
  h.focus('a'); h.camera.setFollowing(true); h.tick()
  assert.deepEqual(h.translations, [])
  h.focus('b', 1); h.focus('b', 2); h.focus('b', 3)
  assert.equal(h.timers.size, 1)
  h.tick()
  assert.deepEqual(h.translations, [[-268, -188]])
  h.focus('b', 4); h.tick()
  assert.equal(h.translations.length, 1, 'new cursor must not recenter a visible node')
  assert.equal(h.transform.scaleX, 1)
  assert.equal(h.changes.at(-1), true, 'own camera translation must not pause itself')
})
test('手动平移/缩放立即暂停，取消已排队的镜头；恢复时定位最新节点', () => {
  const h = harness()
  h.focus('b'); h.camera.setFollowing(true)
  h.listeners.forEach(fn => fn())
  h.tick()
  assert.deepEqual(h.translations, [])
  assert.equal(h.changes.at(-1), false)
  h.focus('a'); h.focus('b'); h.camera.setFollowing(true); h.tick()
  assert.equal(h.translations.length, 1)
})
test('等待布局时保留最后目标但不读取旧坐标', () => {
  const h = harness()
  h.map.renderer.isRendering = true
  h.focus('a'); h.camera.setFollowing(true); h.tick()
  assert.deepEqual(h.translations, [])
  h.focus('b'); h.map.renderer.isRendering = false; h.tick()
  assert.deepEqual(h.translations, [[-268, -188]])
})
test('会话交接、画布替换和销毁使旧镜头请求失效，历史事件不能触发镜头', () => {
  for (const kind of ['session', 'map', 'dispose']) {
    const h = harness()
    h.focus('b'); h.camera.setFollowing(true)
    if (kind === 'session') h.state.session = { jobId: 'job2' }
    if (kind === 'map') h.state.map = { ...h.map }
    if (kind === 'dispose') h.camera.dispose()
    h.tick()
    assert.deepEqual(h.translations, [])
  }
  const h = harness()
  h.camera.focus({ jobId: 'old-job', nodeUids: ['b'] })
  h.camera.setFollowing(true); h.tick()
  assert.deepEqual(h.translations, [])
  h.state.session = null
  h.focus = () => h.camera.focus({ jobId: 'job1', nodeUids: ['b'] })
  h.focus(); h.tick()
  assert.deepEqual(h.translations, [])
})
test('缩放、超大节点及无效尺寸不会持续摆动或写入非法坐标', () => {
  const h = harness()
  h.transform.scaleX = h.transform.scaleY = 2
  h.nodes.b = { left: 900, top: 600, width: 600, height: 300 }
  assert.equal(panMindmapAiNodeIntoView(h.map, h.nodes.b), true)
  assert.equal(panMindmapAiNodeIntoView(h.map, h.nodes.b), true)
  assert.equal(h.translations.length, 1)
  assert.equal(h.transform.scaleX, 2)
  h.map.width = 0
  assert.equal(panMindmapAiNodeIntoView(h.map, h.nodes.b), false)
  assert.equal(h.translations.length, 1)
})
