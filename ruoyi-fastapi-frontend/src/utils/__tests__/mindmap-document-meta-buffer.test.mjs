import assert from 'node:assert/strict'
import test from 'node:test'

import { createMindmapDocumentMetaBuffer } from '../mindmap-document-meta-buffer.js'

function createFakeTimers() {
  let nextId = 0
  const callbacks = new Map()
  return {
    setTimer(callback) {
      nextId += 1
      callbacks.set(nextId, callback)
      return nextId
    },
    clearTimer(id) {
      callbacks.delete(id)
    },
    runAll() {
      const queued = [...callbacks.values()]
      callbacks.clear()
      queued.forEach(callback => callback())
    },
    size: () => callbacks.size,
  }
}

test('文档元数据缓冲器合并连续变更并只提交最新字段', () => {
  const timers = createFakeTimers()
  const commits = []
  const buffer = createMindmapDocumentMetaBuffer(
    meta => commits.push(meta),
    timers,
  )

  assert.equal(buffer.enqueue({ theme: { template: 'classic', config: {} } }), true)
  assert.equal(buffer.enqueue({ layout: 'mindMap' }), true)
  assert.equal(buffer.hasPending(), true)
  assert.equal(timers.size(), 1)

  timers.runAll()
  assert.deepEqual(commits, [{
    theme: { template: 'classic', config: {} },
    layout: 'mindMap',
  }])
  assert.equal(buffer.hasPending(), false)
})

test('保存边界立即冲刷后不会被迟到定时器重复提交', () => {
  const timers = createFakeTimers()
  const commits = []
  const buffer = createMindmapDocumentMetaBuffer(
    meta => commits.push(meta),
    timers,
  )

  buffer.enqueue({ documentData: { simpleMindMap: { config: {} } } })
  assert.equal(buffer.flush(), true)
  assert.equal(buffer.flush(), false)
  assert.equal(timers.size(), 0)
  timers.runAll()
  assert.equal(commits.length, 1)

  buffer.enqueue({ view: null })
  buffer.clear()
  timers.runAll()
  assert.equal(commits.length, 1)
  assert.equal(buffer.hasPending(), false)
})

test('文档元数据缓冲器拒绝空补丁和无效提交器', () => {
  assert.throws(() => createMindmapDocumentMetaBuffer(null), /提交器/)
  const buffer = createMindmapDocumentMetaBuffer(() => undefined)
  assert.equal(buffer.enqueue(null), false)
  assert.equal(buffer.enqueue([]), false)
  assert.equal(buffer.enqueue({}), false)
  assert.equal(buffer.hasPending(), false)
})
