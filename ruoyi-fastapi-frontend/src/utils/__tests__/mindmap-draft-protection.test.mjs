import assert from 'node:assert/strict'
import test from 'node:test'

import { createMindmapDraftProtectionTracker } from '../mindmap-draft-protection.js'

test('只有覆盖当前最新修改的草稿写入才形成保护证明', () => {
  const tracker = createMindmapDraftProtectionTracker()
  tracker.markDirty()
  const firstSnapshot = tracker.beginPersist()
  tracker.markDirty()

  assert.equal(tracker.recordPersistResult(firstSnapshot, true), 'pending')
  assert.equal(tracker.isProtected(), false)

  const latestSnapshot = tracker.beginPersist()
  assert.equal(tracker.recordPersistResult(latestSnapshot, true), 'saved')
  assert.equal(tracker.isProtected(), true)
})

test('当前草稿失败会显式进入失败态且旧结果不能伪装成功', () => {
  const tracker = createMindmapDraftProtectionTracker()
  tracker.markDirty()
  const failedSnapshot = tracker.beginPersist()

  assert.equal(tracker.recordPersistResult(failedSnapshot, false), 'failed')
  assert.equal(tracker.isProtected(), false)
  assert.equal(tracker.recordPersistResult(-1, true), 'failed')
  assert.equal(tracker.isProtected(), false)
})

test('云端干净状态与后续新修改保持明确隔离', () => {
  const tracker = createMindmapDraftProtectionTracker()
  tracker.markDirty()
  tracker.markClean()
  assert.equal(tracker.getState(), 'idle')
  assert.equal(tracker.isProtected(), true)

  tracker.markDirty()
  assert.equal(tracker.getState(), 'pending')
  assert.equal(tracker.isProtected(), false)
  assert.equal(tracker.getChangeVersion(), tracker.getSavedVersion() + 1)
})
