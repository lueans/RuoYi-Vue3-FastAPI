import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  buildMindmapAiTimelineEnvelopeKey,
  mergeMindmapAiJobEventSnapshot,
  mergeMindmapAiJobSnapshot,
} from '../mindmap-ai-stream.js'
import { compareMindmapAiPreviewCoordinates } from '../mindmap-ai-live-preview.js'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const noop = () => {}
const tick = () => new Promise(resolve => setImmediate(resolve))
function functionSource(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
  assert(start >= 0, name)
  const rest = source.slice(start)
  const end = rest.slice(1).search(/\n(?:async )?function \w+\(/)
  assert(end >= 0, name)
  return rest.slice(0, end + 1)
}
function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function harness({ executionMode = 'direct', status = 'completed_direct', proposalRead } = {}) {
  const calls = []
  const streams = []
  const finalJob = {
    id: 'job1', sessionId: 'session1', executionMode, status, proposalId: 'proposal1',
    progress: 100, updateTime: '2026-09-24T10:00:02Z',
  }
  const terminalEvent = {
    eventType: status === 'ready' ? 'artifact_ready' : 'status_changed', sequence: 9,
    payload: { status, progress: 100, proposalId: 'proposal1' }, createdTime: finalJob.updateTime,
  }
  const receipt = (jobId = 'job1', proposalId = 'proposal1') => ({
    id: proposalId, jobId, appliedRevision: 658, resultHash: 'final',
    impact: { changeSummaryVersion: 2, changeSummary: { added: 84 } },
  })
  const s = {
    componentAlive: true, job: ref({ ...finalJob, status: 'running', progress: 30, updateTime: '2026-09-24T10:00:01Z' }),
    proposal: ref(executionMode === 'direct' ? { ...receipt(), appliedRevision: 652, resultHash: 'first-batch' } : null),
    navigator: { onLine: true }, restoreGeneration: 1, restoringJob: ref(false), timelineLoadGeneration: 0,
    timelineController: null, timelineLoading: ref(false), timelineError: ref(''),
    currentSessionTitle: ref(''), sessionTurns: ref([]), selectedTurnJobId: ref('job1'),
    getMindmapAiSessionTimeline: async () => ({ data: { turns: [{ job: finalJob, events: [terminalEvent] }] } }),
    getMindmapAiJob: async jobId => { calls.push(`job:${jobId}`); return { data: finalJob } },
    getMindmapAiProposal: async proposalId => {
      calls.push(`proposal:${proposalId}`)
      return proposalRead ? proposalRead(proposalId) : { data: receipt(s.job.value.id, proposalId) }
    },
    resolveMindmapAiSessionTitle: () => '', cloneRuntimeValue: structuredClone,
    mergeMindmapAiJobSnapshot, mergeMindmapAiJobEventSnapshot,
    buildMindmapAiTimelineEnvelopeKey, compareMindmapAiPreviewCoordinates,
    agentEventKeys: new Set(), agentEventEnvelopeKeys: new Set(), agentEvents: ref([]), jobEventSequences: new Map(),
    latestEventSequence: ref(3), latestPreviewVersion: ref(4), latestPreviewEpoch: ref(1),
    livePreviewEligible: ref(true), livePreviewActive: ref(true), livePreviewError: ref(''),
    upsertSessionTurn: noop, persistActiveJob: noop,
    syncCurrentJobCursor: jobId => { s.latestEventSequence.value = s.jobEventSequences.get(jobId) || 0 },
    realtimeReconnectTimer: null, realtimeGeneration: 0, realtimeController: null,
    realtimeConnectionState: ref('connected'), realtimeReconnectAttempt: 0, realtimeError: ref(''),
    getMindmapAiJobDraft: noop,
    consumeMindmapAiRealtimeEvents: (_jobId, options) => {
      const end = deferred()
      streams.push({ options, end: () => end.resolve({ afterSequence: 9, previewVersion: 4, previewEpoch: 1 }) })
      return end.promise
    },
    isTerminalStatus: value => ['ready', 'completed_direct', 'failed', 'cancelled', 'applied'].includes(value),
    isDirectExecutionJob: (candidate = s.job.value) => candidate.executionMode === 'direct',
    isMindmapAiMessageJob: () => false, isAbortError: error => error?.name === 'AbortError',
    monitoringSuspendedJobId: '', pollController: null, pollTimer: null,
    schedulePoll: (...args) => calls.push(['schedulePoll', ...args]),
    scheduleRealtimeReconnect: () => calls.push('reconnect'),
    settleDirectLiveDraftPreview: async jobId => { calls.push(`settle:${jobId}`); s.livePreviewActive.value = false; return true },
    revertLiveDraftPreview: async () => { calls.push('revert'); s.livePreviewActive.value = false; return true },
    emitAiCanvasPreviewEvent: payload => calls.push(`canvas:${payload.phase}`),
    stopRealtime: state => { calls.push(`stop-stream:${state}`); s.realtimeGeneration += 1 },
    stopPolling: () => calls.push('stop-poll'), activateQueuedFollowupTurn: async () => false,
    refreshDraftPreview: async () => false, restoreTerminalPreview: async () => true,
    proposalLoadGeneration: 0, proposalLoading: ref(false), proposalError: ref(''), diffConfirmed: ref(false),
    terminalHydrationGeneration: 0, terminalFinalizationState: null, terminalHydrationState: ref('idle'), terminalHydrationError: ref(''),
    terminalHydrationRetryTimer: null, terminalHydrationRetryCount: 0,
    scheduleTerminalHydrationRetry: jobId => calls.push(`retry:${jobId}`),
    needsInputQuestions: ref([]), form: { sourceMode: 'current' }, canApplyCurrentProposal: ref(status === 'ready'),
    scheduleDefaultLivePreviewAcceptance: jobId => calls.push(`accept:${jobId}`),
    formatMindmapAiError: error => error.message,
  }
  const names = ['restoreSessionTimeline', 'appendAgentEvent', 'applyRealtimeJobEvent', 'connectRealtime',
    'pollJob', 'hydrateTerminalResources', 'loadProposal', 'terminalJobResourceKey', 'finalizeTerminalJob']
  const api = new Function('scope', `with(scope) { ${names.map(functionSource).join('\n')} return { ${names.join(', ')} }; }`)(s)
  const deliverTerminal = () => streams[0].options.onEvent({ eventType: terminalEvent.eventType, data: terminalEvent })
  return { s, calls, streams, finalJob, receipt, ...api, deliverTerminal }
}

for (const [executionMode, statuses] of [['direct', ['completed_direct', 'failed', 'cancelled']], ['proposal', ['ready', 'failed', 'cancelled']]]) {
  for (const status of statuses) {
    test(`timeline-first ${executionMode}/${status} still hydrates and completes after duplicate SSE and EOF`, async () => {
      const h = harness({ executionMode, status })
      h.connectRealtime('job1')
      await h.restoreSessionTimeline('session1')
      await h.deliverTerminal()
      await h.pollJob()
      h.streams[0].end()
      await tick()
      assert.equal(h.s.terminalHydrationState.value, 'ready')
      assert.equal(h.s.proposal.value.appliedRevision, 658)
      assert.equal(h.calls.filter(call => call === 'proposal:proposal1').length, 1)
      if (executionMode === 'direct') assert.equal(h.calls.filter(call => call === 'settle:job1').length, 1)
      else if (status === 'ready') assert.equal(h.calls.filter(call => call === 'accept:job1').length, 1)
      else assert.equal(h.s.livePreviewActive.value, false)
    })
  }
}

test('duplicate terminal sources share an in-flight hydration instead of aborting or repeating it', async () => {
  const read = deferred()
  const h = harness({ proposalRead: () => read.promise })
  h.connectRealtime('job1')
  await h.restoreSessionTimeline('session1')
  await tick()
  const poll = h.pollJob({ force: true })
  await h.deliverTerminal()
  h.streams[0].end()
  await tick()
  assert.equal(h.calls.filter(call => call === 'proposal:proposal1').length, 1)
  read.resolve({ data: h.receipt() })
  await poll
  await tick()
  assert.equal(h.s.terminalHydrationState.value, 'ready')
  assert.equal(h.calls.filter(call => call === 'settle:job1').length, 1)
})

for (const executionMode of ['direct', 'proposal']) {
  for (const terminalSource of ['sse', 'poll', 'eof']) {
    test(`${terminalSource} can independently finalize a ${executionMode} job exactly once`, async () => {
      const h = harness({ executionMode, status: executionMode === 'direct' ? 'completed_direct' : 'ready' })
      h.connectRealtime('job1')
      if (terminalSource === 'sse') {
        await h.deliverTerminal()
        await h.deliverTerminal()
      } else if (terminalSource === 'poll') await h.pollJob()
      else {
        h.s.job.value = h.finalJob
        h.streams[0].end()
      }
      await tick()
      await h.pollJob({ force: true })
      assert.equal(h.s.terminalHydrationState.value, 'ready')
      assert.equal(h.calls.filter(call => call === 'proposal:proposal1').length, 1)
      assert.equal(h.calls.filter(call => call === `${executionMode === 'direct' ? 'settle' : 'accept'}:job1`).length, 1)
      h.streams[0].end()
    })
  }
}

test('a failed terminal hydration stays retryable without looping on duplicate terminal deliveries', async () => {
  const h = harness()
  let reads = 0
  h.s.getMindmapAiProposal = async () => {
    h.calls.push('proposal:proposal1')
    if (++reads === 1) throw new Error('receipt offline')
    return { data: h.receipt() }
  }
  h.s.job.value = h.finalJob
  assert.equal(await h.pollJob(), false)
  assert.equal(h.s.terminalHydrationState.value, 'error')
  assert.equal(h.s.terminalHydrationError.value, 'receipt offline')
  assert.equal(await h.pollJob(), false)
  assert.equal(reads, 1, 'duplicate delivery must leave the bounded retry policy in control')
  assert.equal(await h.pollJob({ force: true }), true)
  assert.equal(reads, 2)
  assert.equal(h.s.terminalHydrationState.value, 'ready')
  assert.equal(h.s.proposal.value.appliedRevision, 658)
  assert.equal(await h.pollJob({ force: true }), true)
  assert.equal(reads, 2, 'completed work is idempotent even when an old forced timer fires')
})

test('late terminal resources and completion cannot mutate a successor task', async () => {
  const oldRead = deferred()
  const h = harness({ proposalRead: proposalId => proposalId === 'proposal1'
    ? oldRead.promise : { data: h.receipt('job2', proposalId) } })
  h.s.job.value = h.finalJob
  const oldCompletion = h.pollJob()
  await tick()
  const child = { ...h.finalJob, id: 'job2', proposalId: 'proposal2' }
  h.s.job.value = child
  h.s.getMindmapAiJob = async () => ({ data: child })
  assert.equal(await h.pollJob(), true)
  oldRead.resolve({ data: h.receipt() })
  assert.equal(await oldCompletion, false)
  assert.equal(h.s.job.value.id, 'job2')
  assert.equal(h.s.proposal.value.jobId, 'job2')
  assert.equal(h.s.terminalHydrationState.value, 'ready')
  assert.equal(h.calls.includes('settle:job1'), false)
  assert.equal(h.calls.filter(call => call === 'settle:job2').length, 1)
})

test('generation invalidation rejects an old job GET before it can start hydration', async () => {
  const read = deferred()
  const h = harness()
  h.s.job.value = h.finalJob
  h.s.getMindmapAiJob = () => read.promise
  const completing = h.pollJob()
  h.s.restoreGeneration += 1
  h.s.job.value = { id: 'job2', status: 'running' }
  h.s.terminalHydrationState.value = 'idle'
  read.resolve({ data: h.finalJob })
  assert.equal(await completing, false)
  assert.equal(h.s.job.value.id, 'job2')
  assert.equal(h.s.terminalHydrationState.value, 'idle')
  assert.equal(h.calls.some(call => String(call).startsWith('proposal:')), false)
})

test('an apply transition during hydration is finalized serially without auto-accepting the older ready state', async () => {
  const read = deferred()
  const h = harness({ executionMode: 'proposal', status: 'ready', proposalRead: () => read.promise })
  h.s.job.value = h.finalJob
  const completing = h.pollJob()
  await tick()
  const applied = { ...h.finalJob, status: 'applied', updateTime: '2026-09-24T10:00:03Z' }
  h.s.job.value = applied
  h.s.getMindmapAiJob = async () => ({ data: applied })
  h.s.livePreviewActive.value = false
  await h.applyRealtimeJobEvent('job1', { eventType: 'cloud_applied', data: { payload: { status: 'applied' } } })
  read.resolve({ data: h.receipt() })
  await completing
  await tick()
  assert.equal(h.s.job.value.status, 'applied')
  assert.equal(h.s.terminalHydrationState.value, 'ready')
  assert.equal(h.calls.some(call => call === 'accept:job1'), false)
  assert.equal(h.calls.filter(call => call === 'proposal:proposal1').length, 1)
  assert.equal(await h.pollJob(), true)
})
