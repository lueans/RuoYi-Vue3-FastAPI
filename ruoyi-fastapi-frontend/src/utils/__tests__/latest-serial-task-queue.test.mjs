import assert from 'node:assert/strict'
import test from 'node:test'

import { createLatestSerialTaskQueue } from '../latest-serial-task-queue.js'

const nextTurn = () => new Promise(resolve => setImmediate(resolve))

test('coalesces pending work to the latest task', async () => {
  const executed = []
  const queue = createLatestSerialTaskQueue({
    delayMs: 60_000,
    execute: async task => executed.push(task),
  })

  queue.schedule('old')
  queue.schedule('latest')
  await queue.flush()

  assert.deepEqual(executed, ['latest'])
})

test('serializes a newer task behind an in-flight task', async () => {
  const started = []
  const releases = []
  const queue = createLatestSerialTaskQueue({
    delayMs: 60_000,
    execute: task => new Promise(resolve => {
      started.push(task)
      releases.push(resolve)
    }),
  })

  queue.schedule('first')
  const firstFlush = queue.flush()
  await Promise.resolve()
  queue.schedule('second')
  const secondFlush = queue.flush()
  await Promise.resolve()

  assert.deepEqual(started, ['first'])
  releases.shift()()
  await firstFlush
  await Promise.resolve()
  assert.deepEqual(started, ['first', 'second'])
  releases.shift()()
  await secondFlush
})

test('cancel drops pending work and invalidates in-flight task context', async () => {
  let release
  let inFlightContext
  const executed = []
  const queue = createLatestSerialTaskQueue({
    delayMs: 60_000,
    execute: (task, context) => new Promise(resolve => {
      executed.push(task)
      inFlightContext = context
      release = resolve
    }),
  })

  queue.schedule('running')
  const runningFlush = queue.flush()
  await nextTurn()
  assert.equal(inFlightContext.isCurrent(), true)

  queue.schedule('pending')
  queue.cancel()
  assert.equal(inFlightContext.isCurrent(), false)
  release()
  await runningFlush
  await queue.flush()

  assert.deepEqual(executed, ['running'])
})
