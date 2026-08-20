import assert from 'node:assert/strict'
import test from 'node:test'

import { createScopedAsyncSession } from '../mindmap-async.js'

test('作用域会话只接受当前代次和资源身份', () => {
  const guard = createScopedAsyncSession()
  const first = guard.activate(41)

  assert.equal(guard.isCurrent(first), true)
  assert.equal(Object.isFrozen(first), true)
  assert.deepEqual(guard.capture(), first)

  const second = guard.activate(42)
  assert.equal(guard.isCurrent(first), false)
  assert.equal(guard.isCurrent(second), true)
  assert.equal(second.identity, 42)
})

test('作用域会话失效后拒绝已有快照且不再产生捕获值', () => {
  const guard = createScopedAsyncSession()
  const session = guard.activate('mindmap:7')

  guard.invalidate()

  assert.equal(guard.isCurrent(session), false)
  assert.equal(guard.isCurrent(null), false)
  assert.equal(guard.capture(), null)
})
