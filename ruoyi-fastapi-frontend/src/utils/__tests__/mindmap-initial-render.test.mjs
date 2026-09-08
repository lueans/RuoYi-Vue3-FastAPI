import assert from 'node:assert/strict'
import test from 'node:test'

import { waitForMindmapInitialRender } from '../mindmap-initial-render.js'

class FakeEventTarget {
  constructor(visibilityState = 'visible') {
    this.visibilityState = visibilityState
    this.listeners = new Map()
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener)
  }

  dispatch(type) {
    for (const listener of this.listeners.get(type) || []) listener()
  }
}

class FakeMindMap {
  constructor(renderer = {}) {
    this.renderer = {
      destroyed: false,
      root: null,
      isRendering: false,
      renderTimer: null,
      ...renderer,
    }
    this.listeners = new Map()
  }

  on(type, listener) {
    const listeners = this.listeners.get(type) || new Set()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }

  off(type, listener) {
    this.listeners.get(type)?.delete(listener)
  }

  emit(type) {
    for (const listener of this.listeners.get(type) || []) listener()
  }
}

const wait = delay => new Promise(resolve => setTimeout(resolve, delay))

test('后台标签页暂停首次渲染超时并在回到前台后等待真实完成事件', async () => {
  const documentRef = new FakeEventTarget('hidden')
  const mindMap = new FakeMindMap({ renderTimer: 1 })
  let result = 'pending'
  const operation = waitForMindmapInitialRender(mindMap, {
    timeoutMs: 5,
    documentRef,
  }).then(() => { result = 'resolved' }, () => { result = 'rejected' })

  await wait(15)
  assert.equal(result, 'pending')

  documentRef.visibilityState = 'visible'
  documentRef.dispatch('visibilitychange')
  mindMap.renderer.renderTimer = null
  mindMap.renderer.root = { uid: 'root' }
  mindMap.emit('node_tree_render_end')
  await operation

  assert.equal(result, 'resolved')
  assert.equal(documentRef.listeners.get('visibilitychange')?.size || 0, 0)
})

test('首次完成事件先于等待器时由渲染器状态直接确认就绪', async () => {
  const documentRef = new FakeEventTarget('visible')
  const mindMap = new FakeMindMap({ root: { uid: 'root' } })

  await waitForMindmapInitialRender(mindMap, { timeoutMs: 5, documentRef })

  assert.equal(documentRef.listeners.get('visibilitychange')?.size || 0, 0)
})

test('前台标签页真实卡住时仍会有界失败', async () => {
  const documentRef = new FakeEventTarget('visible')
  const mindMap = new FakeMindMap({ renderTimer: 1 })

  await assert.rejects(
    waitForMindmapInitialRender(mindMap, { timeoutMs: 5, documentRef }),
    /脑图首次渲染超时/,
  )
  assert.equal(documentRef.listeners.get('visibilitychange')?.size || 0, 0)
})

