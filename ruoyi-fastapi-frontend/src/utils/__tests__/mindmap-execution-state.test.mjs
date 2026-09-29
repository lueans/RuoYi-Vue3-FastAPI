import test from 'node:test'
import assert from 'node:assert/strict'
import { setTimeout as delay } from 'node:timers/promises'
import { effectScope, nextTick, ref } from 'vue'
import { isMindmapExecutionBlocked, mergeMindmapExecutionEvidence } from '../mindmap-execution-state.js'
import { mergeMindmapAiJobEventSnapshot, mergeMindmapAiJobSnapshot } from '../mindmap-ai-stream.js'
import { useMindmapExecutionStop } from '../use-mindmap-execution-stop.js'

const retained = (changes = {}) => ({ id: 'j1', status: 'ready', artifactId: 'retained-draft',
  executionEpoch: 3, executionState: 'running', cancelRequestedTime: '2026-09-26T10:00:00', ...changes })

test('a preserved/applied result is not evidence that its executor has stopped', () => {
  for (const status of ['ready', 'needs_review', 'applied', 'cancelled', 'failed', 'completed_direct']) {
    for (const executionState of ['running', 'unconfirmed', 'unknown']) {
      assert.equal(isMindmapExecutionBlocked(retained({ status, executionState })), true)
    }
    for (const executionState of ['stopped', 'not_started']) {
      assert.equal(isMindmapExecutionBlocked(retained({ status, executionState })), false)
    }
  }
  assert.equal(isMindmapExecutionBlocked({ status: 'cancelled' }), true)
  assert.equal(isMindmapExecutionBlocked({ status: 'running', executionState: 'running' }), false)
  assert.equal(isMindmapExecutionBlocked({ status: 'running', errorCode: 'AI_AGENT_CLEANUP_FAILED' }), true)
})

test('same-epoch stop evidence is monotonic, and old epochs cannot attest to a new executor', () => {
  const stopped = retained({ executionState: 'stopped' })
  for (const state of ['running', 'unconfirmed', 'unknown', 'not_started']) {
    assert.equal(mergeMindmapExecutionEvidence(stopped, { executionEpoch: 3, executionState: state }).executionState, 'stopped')
  }
  const running = retained({ executionEpoch: 4 })
  assert.equal(mergeMindmapExecutionEvidence(running, stopped).executionState, 'running')
  assert.equal(mergeMindmapExecutionEvidence(stopped, running).executionEpoch, 4)
})

test('an older execution snapshot cannot replace the result/status of the current run', () => {
  const current = retained({ executionEpoch: 4, status: 'running', artifactId: null, cancelRequestedTime: null })
  const late = retained({ executionEpoch: 3, executionState: 'stopped', status: 'failed' })
  assert.deepEqual(mergeMindmapAiJobSnapshot(current, late), current)
})

test('an execution receipt can finish independently of a stale result status without losing the draft', () => {
  const current = retained({ status: 'applied' })
  const merged = mergeMindmapAiJobSnapshot(current, retained({ status: 'ready', executionState: 'stopped' }))
  assert.equal(merged.status, 'applied')
  assert.equal(merged.artifactId, 'retained-draft')
  assert.equal(merged.executionState, 'stopped')
  const event = mergeMindmapAiJobEventSnapshot(current, { eventType: 'execution_state',
    payload: { executionState: 'stopped', executionEpoch: 3 } })
  assert.equal(event.executionState, 'stopped')
  assert.equal(event.status, 'applied')
})

test('malformed execution fields cannot manufacture a stopped state', () => {
  for (const executionEpoch of [-1, '3', null, true]) {
    const result = mergeMindmapAiJobSnapshot({ id: 'j1', status: 'cancelled' },
      { id: 'j1', executionEpoch, executionState: 'stopped' })
    assert.equal(isMindmapExecutionBlocked(result), true)
    assert.notEqual(result.executionState, 'stopped')
  }
})

function monitor(t, { initial = retained(), load = async () => ({ data: retained() }), maxPolls = 30 } = {}) {
  const scope = effectScope()
  const job = ref(initial)
  const owner = ref('7')
  const requests = []
  const updated = []
  let loader = load
  const api = scope.run(() => useMindmapExecutionStop({
    job, ownerId: () => owner.value,
    loadJob: (id, options) => { requests.push({ id, ...options }); return loader(id, options) },
    onUpdated: snapshot => updated.push(snapshot), intervalMs: 2, maxPolls,
  }))
  t.after(() => scope.stop())
  return { ...api, job, owner, requests, updated, scope, setLoad: value => { loader = value } }
}

async function until(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return
    await delay(2)
  }
  assert.ok(predicate(), 'expected condition did not settle')
}

test('restoring a terminal retained draft starts an independent stop monitor', async t => {
  let calls = 0
  const h = monitor(t, { load: async () => ({ data: retained({ executionState: ++calls === 2 ? 'stopped' : 'running' }) }) })
  await until(() => !h.blocked.value)
  assert.equal(h.requests.length, 2)
  assert.equal(h.job.value.artifactId, 'retained-draft')
  assert.equal(h.job.value.status, 'ready')
  assert.equal(h.updated.at(-1).executionState, 'stopped')
})

for (const changed of ['job', 'epoch', 'owner', 'disposed']) {
  test(`late stop replies are ignored after ${changed} changes`, async t => {
    let release
    const h = monitor(t, { load: () => new Promise(resolve => { release = resolve }) })
    const oldRequest = h.requests[0]
    const resolveOld = release
    h.setLoad(async () => ({ data: h.job.value }))
    if (changed === 'job') h.job.value = retained({ id: 'j2', executionState: 'unconfirmed' })
    if (changed === 'epoch') h.job.value = retained({ executionEpoch: 4, executionState: 'unconfirmed' })
    if (changed === 'owner') h.owner.value = '8'
    if (changed === 'disposed') h.scope.stop()
    await nextTick()
    const updates = h.updated.length
    resolveOld({ data: retained({ executionState: 'stopped' }) })
    await nextTick()
    await Promise.resolve()
    assert.equal(oldRequest.signal.aborted, true)
    assert.notEqual(h.job.value.executionState, 'stopped')
    assert.equal(h.updated.length, updates)
  })
}

test('a wrong-job response cannot unlock the editor or overwrite its retained result', async t => {
  const h = monitor(t, { initial: retained({ executionState: 'unconfirmed' }),
    load: async () => ({ data: retained({ id: 'other-job', executionState: 'stopped' }) }) })
  await nextTick()
  await until(() => !h.checking.value)
  assert.equal(h.job.value.id, 'j1')
  assert.equal(h.blocked.value, true)
  assert.equal(h.updated.length, 0)
  assert.ok(h.error.value)
})

test('bounded stop polling does not infer success at timeout, and manual refresh can recover', async t => {
  const h = monitor(t, { maxPolls: 3 })
  await until(() => !!h.error.value)
  assert.equal(h.requests.length, 3)
  assert.equal(h.blocked.value, true)
  assert.match(h.error.value, /超时/)
  h.setLoad(async () => ({ data: retained({ executionState: 'stopped' }) }))
  assert.equal(await h.refresh(), true)
  assert.equal(h.job.value.artifactId, 'retained-draft')
  assert.equal(h.error.value, '')
})

test('unconfirmed/unknown execution requires evidence rather than an endless retry loop', async t => {
  for (const executionState of ['unconfirmed', 'unknown']) {
    const initial = retained({ executionState })
    const h = monitor(t, { initial, load: async () => ({ data: initial }) })
    await until(() => !h.checking.value)
    await delay(12)
    assert.equal(h.requests.length, 1)
    assert.equal(h.blocked.value, true)
    h.scope.stop()
  }
})

test('a failed stop status request preserves content and remains blocked', async t => {
  const h = monitor(t, { initial: retained({ executionState: 'unconfirmed' }), load: async () => { throw Error('offline') } })
  await until(() => !h.checking.value)
  assert.equal(h.blocked.value, true)
  assert.equal(h.job.value.artifactId, 'retained-draft')
  assert.match(h.error.value, /暂时无法查询/)
})

test('handoff wait joins stop receipts without another request and requires both exit and terminal result', async t => {
  const h = monitor(t, { initial: retained({ status: 'running' }) })
  const isRunning = () => ['running', 'cancel_requested'].includes(h.job.value.status)
  let settled = false
  const result = h.waitForStopped({ stillCurrent: () => true, isRunning }).then(value => { settled = true; return value })
  h.job.value = { ...h.job.value, executionState: 'stopped' }
  await nextTick()
  assert.equal(settled, false, 'exit alone does not attest to the final result')
  assert.equal(h.requests.length, 0, 'waiting must not introduce another network loop')
  h.job.value.status = 'ready'
  assert.equal(await result, true)
  assert.equal(h.requests.length, 0)
  assert.equal(h.job.value.artifactId, 'retained-draft')
})

test('handoff cannot turn a legacy unknown receipt into stopped evidence', async t => {
  const initial = retained({ executionState: 'unknown' })
  const h = monitor(t, { initial, load: async () => ({ data: initial }) })
  assert.equal(await h.waitForStopped({ stillCurrent: () => true, isRunning: () => false, timeoutMs: 10 }), false)
  assert.equal(h.job.value.executionState, 'unknown')
  assert.equal(h.blocked.value, true)
})

test('a never-started cancelled run is safe to hand off without inventing a process exit', async t => {
  const h = monitor(t, { initial: retained({ status: 'cancelled', executionState: 'not_started', executionEpoch: 0 }) })
  assert.equal(await h.waitForStopped({ stillCurrent: () => true, isRunning: () => false }), true)
  assert.equal(h.requests.length, 0)
})
