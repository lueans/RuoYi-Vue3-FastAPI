import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { babelParse, parse } from '@vue/compiler-sfc'
import { compareMindmapAiPreviewCoordinates, countMindmapAiDraftNodes } from '../mindmap-ai-live-preview.js'
import { directImpactForMindmapAiResult, resolveMindmapAiDirectChangeSummary } from '../mindmap-ai-result-summary.js'
import { mergeMindmapAiJobSnapshot } from '../mindmap-ai-stream.js'

// Execute the production lifecycle functions rather than matching source text.
// Editor IO is controlled so races can be delivered in either order.
const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const declarations = babelParse(script, { sourceType: 'module' }).program.body
const ref = value => ({ value })
const noop = () => {}
function functionSource(name) {
  const declaration = declarations.find(node => node.type === 'FunctionDeclaration' && node.id.name === name)
  assert.ok(declaration, name)
  return script.slice(declaration.start, declaration.end)
}
function compile(scope, names) {
  return new Function('scope', `with(scope) { ${names.map(functionSource).join('\n')} return { ${names.join(', ')} }; }`)(scope)
}
function harness() {
  const events = []
  const s = {
    componentAlive: true, job: ref({ id: 'job1', status: 'cancelled', executionMode: 'direct' }),
    visible: ref(false), running: ref(false), directCanvasOwnerId: ref('job1'),
    directCanvasRecoveryJobId: ref(''),
    uncertainCanvasCreation: ref(null), preparingCanvas: ref(false), livePreviewRecovering: ref(false),
    pendingHandoffCanvasJobId: '',
    livePreviewActive: ref(true), livePreviewReverting: ref(false), livePreviewPaused: ref(true),
    livePreviewError: ref(''), livePreviewJobId: 'job1', livePreviewSuppressedJobId: '',
    livePreviewGeneration: 1, livePreviewDirectSettlePromise: null, livePreviewDirectSettleJobId: '',
    directTerminalTargetJobId: '', livePreviewApplyingJobId: '', livePreviewRenderedDocument: null,
    livePreviewFlushInFlight: false, livePreviewPendingFrame: null, livePreviewFlushTimer: null,
    latestPreviewVersion: ref(4), livePreviewRenderedNodeCount: ref(2), livePreviewTargetNodeCount: ref(2),
    livePreviewChangeSummary: ref(null), LIVE_PREVIEW_FRAME_INTERVAL_MS: 1,
    restoreGeneration: 1, terminalFinalizationState: null,
    isTerminalStatus: status => ['cancelled', 'failed', 'completed_direct'].includes(status),
    isDirectExecutionJob: (job = s.job.value) => job?.executionMode === 'direct',
    formatMindmapAiError: (error, message) => error?.message || message,
    emitEditorRequest: async (_event, payload) => {
      events.push(payload)
      return { document: { root: { data: { uid: 'root', text: '终态' }, children: [] } }, targetToken: 7 }
    },
    queueLiveDraftPreview: document => { s.livePreviewPendingFrame = { document } },
    scheduleLivePreviewFlush: () => {
      assert.equal(s.livePreviewPaused.value, false, 'internal drain must resume even while cancelling')
      s.livePreviewRenderedDocument = s.livePreviewPendingFrame.document
      s.livePreviewPendingFrame = null
    },
    finishLiveDraftPreviewAfterApply: () => { s.livePreviewActive.value = false },
    reconcileQueuedCanvasRequest: async () => null,
    activateQueuedFollowupTurn: async () => false,
    livePreviewOldestPendingAt: null,
    emitAiEditingState: noop,
    bus: { emit: noop },
    store: { activeSidebar: null },
    actions: { setActiveSidebar: noop },
    window: { innerWidth: 1024 },
  }
  Object.defineProperty(s, 'directCanvasOwned', { get: () => ref(Boolean(s.directCanvasOwnerId.value)) })
  Object.defineProperty(s, 'livePreviewCanvasMutationBlocked', { get: () => ref(s.livePreviewActive.value || s.preparingCanvas.value || Boolean(s.directCanvasOwnerId.value)) })
  const api = compile(s, ['settleDirectLiveDraftPreview', 'completeDirectCanvasHandoff', 'releaseCanvasPreparation', 'reconcilePendingCanvasCreation', 'resetNewJob', 'showDialog', 'reconcileRestoredSourceBaseline'])
  return { s, events, ...api }
}

test('paused cancellation drains serially then commits the exact authoritative target', async () => {
  const h = harness()
  assert.equal(await h.settleDirectLiveDraftPreview(), true)
  assert.deepEqual(h.events.map(event => event.phase), ['start', 'authoritative-target', 'direct-committed'])
  assert.equal(h.events.at(-1).targetToken, 7)
  assert.equal(h.s.directCanvasOwnerId.value, '')
  assert.equal(h.s.livePreviewDirectSettlePromise, null)
})

test('running jobs cannot be settled or reset; reopening only reveals the existing panel', async () => {
  const h = harness()
  h.s.job.value.status = 'running'
  h.s.running.value = true
  assert.equal(await h.settleDirectLiveDraftPreview(), false)
  assert.equal(h.resetNewJob(), false)
  assert.equal(await h.showDialog(), true)
  assert.equal(h.s.visible.value, true)
  assert.equal(h.s.job.value.id, 'job1')
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  assert.deepEqual(h.events, [])
})

test('a stale terminal callback cannot commit or release its successor owner', async () => {
  const h = harness()
  let resolveTarget
  h.s.emitEditorRequest = async (_event, payload) => {
    h.events.push(payload)
    if (payload.phase === 'authoritative-target') return new Promise(resolve => { resolveTarget = resolve })
    return {}
  }
  const settlement = h.settleDirectLiveDraftPreview()
  await new Promise(resolve => setImmediate(resolve))
  h.s.job.value = { id: 'job2', status: 'running', executionMode: 'direct' }
  h.s.directCanvasOwnerId.value = 'job2'
  h.s.livePreviewGeneration += 1
  resolveTarget({ document: { root: {} }, targetToken: 8 })
  assert.equal(await settlement, false)
  assert.equal(h.s.directCanvasOwnerId.value, 'job2')
  assert.ok(!h.events.some(event => event.phase === 'direct-committed'))
})

test('unknown HTTP result retains preparation ownership; confirmed absence uses only preparation-aborted', async () => {
  const h = harness()
  h.s.job.value = null
  h.s.directCanvasOwnerId.value = 'preparing:key'
  h.s.preparingCanvas.value = true
  h.s.uncertainCanvasCreation.value = { preparationId: 'preparing:key', recover: async () => { throw new Error('offline') } }
  assert.equal(await h.reconcilePendingCanvasCreation(), false)
  assert.equal(await h.releaseCanvasPreparation('preparing:key'), false)
  assert.equal(h.s.directCanvasOwnerId.value, 'preparing:key')
  assert.equal(h.s.preparingCanvas.value, true)
  assert.deepEqual(h.events, [])
  h.s.uncertainCanvasCreation.value.recover = async () => null
  assert.equal(await h.reconcilePendingCanvasCreation(), true)
  assert.deepEqual(h.events.map(event => event.phase), ['preparation-aborted'])
  assert.equal(h.s.directCanvasOwnerId.value, '')
  assert.equal(h.s.preparingCanvas.value, false)
})

test('failed preparation release remains explicitly recoverable, without unlocking', async () => {
  const h = harness()
  h.s.directCanvasOwnerId.value = 'preparing:key'
  h.s.preparingCanvas.value = true
  h.s.emitEditorRequest = async () => { throw new Error('cloud unavailable') }
  assert.equal(await h.releaseCanvasPreparation('preparing:key'), false)
  assert.equal(h.s.directCanvasOwnerId.value, 'preparing:key')
  assert.equal(h.s.preparingCanvas.value, true)
  assert.equal(h.s.uncertainCanvasCreation.value.preparationId, 'preparing:key')
})

test('reconciled creation transfers ownership without aborting the adopted job', async () => {
  const h = harness()
  h.s.directCanvasOwnerId.value = 'preparing:key'
  h.s.preparingCanvas.value = true
  h.s.uncertainCanvasCreation.value = { preparationId: 'preparing:key', recover: async () => {
    h.s.directCanvasOwnerId.value = 'job1'
    return true
  } }
  assert.equal(await h.reconcilePendingCanvasCreation(), true)
  await h.releaseCanvasPreparation('preparing:key')
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  assert.deepEqual(h.events, [])
})

test('an incomplete reconciliation is not proof that the request was never sent', async () => {
  const h = harness()
  h.s.directCanvasOwnerId.value = 'preparing:key'
  h.s.preparingCanvas.value = true
  const pending = { preparationId: 'preparing:key', recover: async () => false }
  h.s.uncertainCanvasCreation.value = pending
  assert.equal(await h.reconcilePendingCanvasCreation(), false)
  assert.equal(h.s.uncertainCanvasCreation.value, pending)
  assert.equal(h.s.directCanvasOwnerId.value, 'preparing:key')
  assert.equal(h.s.preparingCanvas.value, true)
  assert.deepEqual(h.events, [])
})

test('a restored direct job may advance its own base revision without disabling streaming', async () => {
  const h = harness()
  h.s.sourceBaselineMismatch = ref(true)
  h.s.editorContext = ref({ revision: 12 })
  assert.equal(await h.reconcileRestoredSourceBaseline({ executionMode: 'direct', status: 'running', baseRevision: 3, sourceType: 'cloud_document' }), true)
  assert.equal(h.s.sourceBaselineMismatch.value, false)
})

test('terminal polling before the first draft cannot emit clear or commit outside settlement', async () => {
  const h = harness()
  h.s.livePreviewActive.value = false
  Object.assign(h.s, {
    navigator: { onLine: true }, monitoringSuspendedJobId: '', pollController: null,
    realtimeError: ref(''), realtimeConnectionState: ref('connected'), proposal: ref(null),
    getMindmapAiJob: async () => ({ data: h.s.job.value }),
    mergeMindmapAiJobSnapshot: (_old, next) => next, persistActiveJob: noop,
    hydrateTerminalResources: async () => true, refreshDraftPreview: async () => false,
    emitAiCanvasPreviewEvent: payload => h.events.push(payload),
    isMindmapAiMessageJob: () => false, stopRealtime: noop, stopPolling: noop, activateQueuedFollowupTurn: noop,
    isAbortError: () => false, terminalHydrationState: ref(''), terminalHydrationError: ref(''),
    scheduleTerminalHydrationRetry: noop,
  })
  const api = compile(h.s, ['pollJob', 'settleDirectLiveDraftPreview', 'completeDirectCanvasHandoff',
    'finalizeTerminalJob', 'terminalJobResourceKey'])
  await api.pollJob({ force: true })
  assert.deepEqual(h.events.map(event => event.phase), ['start', 'authoritative-target', 'direct-committed'])
  assert.equal(h.s.terminalHydrationError.value, '')
})

test('only a definitive original POST rejection is safe to release; network/server failures remain unknown', () => {
  const { isDefinitiveAiCreationRejection } = compile({
    resolveMindmapAiErrorCode: error => error?.data?.errorCode || '',
  }, ['isDefinitiveAiCreationRejection'])
  assert.equal(isDefinitiveAiCreationRejection({ response: { status: 422 } }), true)
  assert.equal(isDefinitiveAiCreationRejection({ response: { status: 403 } }), true)
  assert.equal(isDefinitiveAiCreationRejection({ code: 500, data: { errorCode: 'AI_MODEL_CONFIG_INVALID' } }), false)
  assert.equal(isDefinitiveAiCreationRejection({ code: 500, data: { creationRejected: true } }), true)
  assert.equal(isDefinitiveAiCreationRejection({ code: 'ECONNABORTED' }), false)
  assert.equal(isDefinitiveAiCreationRejection({ response: { status: 503 } }), false)
  assert.equal(isDefinitiveAiCreationRejection({ response: { status: 429 } }), true)
})

test('a rejected original create releases its preparation without retrying the rejected POST', async () => {
  const h = harness()
  h.s.job.value = null
  h.s.livePreviewActive.value = false
  h.s.directCanvasOwnerId.value = ''
  const clearedAttempts = []
  Object.assign(h.s, {
    form: { prompt: '添加测试节点', agentKey: 'codex', intent: 'expand', maxNodes: 20, maxDepth: 4 },
    agents: ref([{ agentKey: 'codex', status: 'enabled' }]), nativeModelConfigurationIssue: ref(''),
    effectiveFormIntent: ref('expand'), messageModeActive: ref(false), discussionMode: ref(false),
    restoringJob: ref(false), actionBusy: ref(false), submitting: ref(false), submissionStartedAt: ref(0),
    sourceContext: ref({ mindmapId: 1, readonly: false }), sourceFingerprint: ref('base'),
    submitAttempt: null, agentSupportsCurrentTask: () => true, beginActionIdentity: () => ({}),
    assertActionIdentity: noop, buildSource: async () => ({ type: 'cloud_document', mindmapId: 1 }),
    effectiveRequestLayout: () => 'logicalStructure', captureJobConfiguration: value => value,
    readPersistedAttempts: () => ({}),
    resolveDurableAttempt: async () => ({ key: 'key' }), createMindmapAiIdempotencyKey: () => 'key',
    createMindmapAiJob: async () => { throw Object.assign(new Error('forbidden'), { response: { status: 403 } }) },
    reconcileMindmapAiJob: async () => { throw new Error('must not reconcile a definitive rejection') },
    clearDurableAttempt: (...args) => clearedAttempts.push(args),
    resolveMindmapAiErrorCode: () => '', ElMessage: { warning: noop, error: noop },
  })
  const api = compile(h.s, ['submitJob', 'prepareDirectCanvasRequest', 'releaseCanvasPreparation', 'isDefinitiveAiCreationRejection'])
  await api.submitJob()
  assert.deepEqual(h.events.map(event => event.phase), ['prepare', 'preparation-aborted'])
  assert.equal(h.s.directCanvasOwnerId.value, '')
  assert.equal(h.s.preparingCanvas.value, false)
  assert.deepEqual(clearedAttempts, [['create', 'key']])

  // An old persisted key may belong to a POST whose response was lost. Even
  // a later 403 from the same key cannot establish that the old call failed.
  h.s.readPersistedAttempts = () => ({ create: { key: 'key' } })
  h.s.reconcileMindmapAiJob = async () => { throw new Error('offline') }
  const retryApi = compile(h.s, ['submitJob', 'prepareDirectCanvasRequest', 'releaseCanvasPreparation', 'reconcilePendingCanvasCreation', 'isDefinitiveAiCreationRejection'])
  await retryApi.submitJob()
  assert.deepEqual(h.events.map(event => event.phase), ['prepare', 'preparation-aborted', 'prepare'])
  assert.equal(h.s.directCanvasOwnerId.value, 'preparing:key')
  assert.equal(h.s.preparingCanvas.value, true)
  assert.deepEqual(clearedAttempts, [['create', 'key']])
})

test('retry preparation failure cannot start or replay a backend request', async () => {
  const h = harness()
  h.s.directCanvasOwnerId.value = ''
  h.s.livePreviewActive.value = false
  h.s.job.value = { id: 'job1', status: 'failed', executionMode: 'direct', intent: 'expand', sourceType: 'cloud_document' }
  const requests = []
  let attemptPersisted = false
  Object.assign(h.s, {
    actionBusy: ref(false), retryAvailable: ref(true), retrying: ref(false), retryPrompt: ref(''),
    form: { agentKey: 'codex' }, agents: ref([{ agentKey: 'codex', status: 'enabled', intents: ['expand'], inputTypes: ['cloud_document'] }]),
    nativeModelConfigurationIssue: ref(''), jobConfiguration: ref({}), sourceContext: ref({}), sourceFingerprint: ref(''), sessionTurns: ref([]),
    retryAttempt: null, beginActionIdentity: () => ({}), assertActionIdentity: noop,
    resolveDurableAttempt: async () => { attemptPersisted = true; return { key: 'retry-key' } }, createMindmapAiIdempotencyKey: () => 'retry-key',
    captureJobConfiguration: value => value, readPersistedAttempts: () => attemptPersisted ? ({ retry: { key: 'retry-key' } }) : {},
    prepareDirectCanvasRequest: async () => { throw new Error('editor busy') },
    retryMindmapAiJob: async () => requests.push('post'), replayRetryAttempt: async () => requests.push('replay'),
    clearDurableAttempt: noop, releaseCanvasPreparation: async () => true,
    resolveMindmapAiErrorCode: () => '', ElMessage: { info: noop, warning: noop, error: noop },
  })
  await compile(h.s, ['retryJob', 'isDefinitiveAiCreationRejection']).retryJob()
  assert.deepEqual(requests, [])
  assert.equal(h.s.retryAttempt, null)
})

test('an unknown queued child prevents terminal commit and keeps the parent read-only', async () => {
  const h = harness()
  h.s.reconcileQueuedCanvasRequest = async () => { throw new Error('queued request unknown') }
  assert.equal(await h.settleDirectLiveDraftPreview(), false)
  assert.deepEqual(h.events.map(event => event.phase), ['start'])
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  assert.match(h.s.livePreviewError.value, /queued request unknown/)
})

test('queued request reconciliation retains its durable key until an exact child is known', async () => {
  const h = harness()
  const attempt = { key: 'queued-key', sessionId: 'session1', requestPayload: { prompt: '下一轮' } }
  h.s.job.value.sessionId = 'session1'
  const cleared = []
  Object.assign(h.s, {
    queueAttempt: { key: attempt.key }, readPersistedAttempts: () => ({ queue: attempt }),
    replayFollowupAttempt: async () => null,
    clearDurableAttempt: (...args) => cleared.push(args), upsertSessionTurn: noop,
    appendClientPrompt: noop, restoreDurableAttemptNotice: noop,
  })
  const api = compile(h.s, ['reconcileQueuedCanvasRequest'])
  await assert.rejects(api.reconcileQueuedCanvasRequest('job1'), /尚未确认/)
  assert.deepEqual(cleared, [])
  h.s.replayFollowupAttempt = async () => ({ id: 'child1', turnIndex: 2 })
  assert.equal((await api.reconcileQueuedCanvasRequest('job1')).id, 'child1')
  assert.deepEqual(cleared, [['queue', 'queued-key']])
  assert.equal(h.s.queueAttempt, null)
})

test('a waiting queued child acquires the canvas before activation and before parent unlock', async () => {
  const h = harness()
  const child = { id: 'child1', parentJobId: 'job1', turnIndex: 2, status: 'waiting_turn', executionMode: 'direct' }
  Object.assign(h.s, {
    sessionTurns: ref([{ job: child, userMessage: { content: '继续' } }]), form: {}, queueAttempt: null,
    getMindmapAiJob: async () => ({ data: child }),
    beginActionIdentity: () => ({}),
    activateFollowupJob: async nextJob => {
      assert.equal(h.s.directCanvasOwnerId.value, 'child1')
      assert.equal(h.events.at(-1).phase, 'start')
      assert.equal(h.events.at(-1).jobId, 'child1')
      h.s.job.value = nextJob
      return true
    },
  })
  const api = compile(h.s, ['settleDirectLiveDraftPreview', 'completeDirectCanvasHandoff', 'activateQueuedFollowupTurn'])
  assert.equal(await api.settleDirectLiveDraftPreview(), true)
  assert.deepEqual(h.events.map(event => [event.phase, event.jobId]), [
    ['start', 'job1'], ['authoritative-target', 'job1'], ['direct-committed', 'job1'], ['start', 'child1'],
  ])
  assert.equal(h.s.directCanvasOwnerId.value, 'child1')
  assert.equal(h.s.job.value.id, 'child1')
})

function runningChildHandoff() {
  const h = harness()
  const child = { id: 'child1', parentJobId: 'job1', turnIndex: 2, status: 'running', executionMode: 'direct' }
  const activations = []
  Object.assign(h.s, {
    sessionTurns: ref([{ job: { ...child, status: 'waiting_turn' } }]), form: {}, queueAttempt: null,
    getMindmapAiJob: async () => ({ data: child }), beginActionIdentity: () => ({}),
    activateFollowupJob: async (nextJob, options) => {
      activations.push({ nextJob, options })
      h.s.job.value = nextJob
      return true
    },
  })
  const api = compile(h.s, ['completeDirectCanvasHandoff', 'activateQueuedFollowupTurn'])
  return { ...h, ...api, child, activations }
}

test('failed child checkpoint read retains the parent owner and retries the same fenced child', async () => {
  const h = runningChildHandoff()
  h.s.getMindmapAiJobDraft = async () => { throw new Error('offline') }
  assert.equal(await h.completeDirectCanvasHandoff('job1'), false)
  assert.equal(h.s.job.value.id, 'job1')
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  assert.equal(h.s.pendingHandoffCanvasJobId, 'child1')
  assert.equal(h.activations.length, 0)
  const preview = { available: true, previewEpoch: 2, operationCursor: 8, document: { root: { data: { uid: 'root', text: '当前子轮草稿' }, children: [] } } }
  h.s.getMindmapAiJobDraft = async () => ({ data: preview })
  assert.equal(await h.completeDirectCanvasHandoff('job1'), true)
  assert.equal(h.activations[0].options.initialPreview, preview)
  assert.equal(h.s.directCanvasOwnerId.value, 'child1')
  assert.equal(h.s.pendingHandoffCanvasJobId, '')
})

test('a child completing between job and draft reads activates its terminal path without a stale cursor', async () => {
  const h = runningChildHandoff()
  let reads = 0
  h.s.getMindmapAiJob = async () => ({ data: { ...h.child, status: ++reads === 1 ? 'running' : 'completed_direct' } })
  h.s.getMindmapAiJobDraft = async () => ({ data: { available: false, status: 'completed_direct' } })
  assert.equal(await h.completeDirectCanvasHandoff('job1'), true)
  assert.equal(h.activations[0].nextJob.status, 'completed_direct')
  assert.equal(h.activations[0].options.initialPreview, null)
})

test('a queued child without its first draft can begin monitoring under the acquired fence', async () => {
  const h = runningChildHandoff()
  h.s.getMindmapAiJob = async () => ({ data: { ...h.child, status: 'preparing' } })
  h.s.getMindmapAiJobDraft = async () => ({ data: { available: false } })
  assert.equal(await h.completeDirectCanvasHandoff('job1'), true)
  assert.equal(h.activations[0].nextJob.status, 'preparing')
  assert.equal(h.activations[0].options.initialPreview, null)
})

test('child activation establishes its latest epoch/cursor before monitoring and ignores older SSE snapshots', async () => {
  const h = harness()
  const queuedTargets = []
  const monitoring = []
  const child = { id: 'child1', status: 'running', executionMode: 'direct', sourceType: 'cloud_document', intent: 'expand', sessionId: 'session1' }
  Object.assign(h.s, {
    assertActionIdentity: noop, adoptDirectCanvasRequest: async () => {}, cloneRuntimeValue: structuredClone,
    draftDocument: ref(null), stopPolling: noop, stopRealtime: noop, monitoringSuspendedJobId: '',
    isMindmapAiMessageJob: () => false, intentOptions: [{ value: 'expand' }], form: { intent: 'expand' },
    jobConfiguration: ref({ intent: 'expand' }), discussionMode: ref(false), captureJobConfiguration: value => value,
    sourceContext: ref(null), sourceFingerprint: ref(''), selectedTurnJobId: ref(''),
    followupPrompt: ref(''), pendingFollowupPrompt: ref(''), proposal: ref(null), proposalError: ref(''), diffConfirmed: ref(false),
    followupAttempt: null, appendClientPrompt: noop, upsertSessionTurn: noop, persistActiveJob: () => true,
    clearDurableAttempt: noop, restoreDurableAttemptNotice: noop, resetCurrentJobCursor: noop,
    latestPreviewVersion: ref(99), latestPreviewEpoch: ref(1), livePreviewRenderedVersion: ref(-1),
    messageModeActive: ref(false), draftFreshness: ref(''), draftFreshnessMessage: ref(''),
    compareMindmapAiPreviewCoordinates, countMindmapAiDraftNodes,
    queueLiveDraftPreview: (_document, cursor) => queuedTargets.push(cursor),
    beginJobMonitoring: options => monitoring.push({ ...options, epoch: h.s.latestPreviewEpoch.value, cursor: h.s.latestPreviewVersion.value }),
    restoreSessionTimeline: async () => true, restoreGeneration: 1,
  })
  const preview = { available: true, previewEpoch: 2, operationCursor: 8, document: { root: { data: { uid: 'root', text: '最新' }, children: [] } } }
  const api = compile(h.s, ['activateFollowupJob', 'acceptDraftPreview'])
  assert.equal(await api.activateFollowupJob(child, { identity: {}, requestPayload: { prompt: '继续' }, attemptKey: '', initialPreview: preview }), true)
  assert.deepEqual(monitoring, [{ resetCursor: false, epoch: 2, cursor: 8 }])
  assert.equal(api.acceptDraftPreview({ ...preview, previewEpoch: 1, operationCursor: 100 }), false)
  assert.equal(api.acceptDraftPreview({ ...preview, operationCursor: 7 }), false)
  assert.equal(api.acceptDraftPreview({ ...preview, operationCursor: 9 }), true)
  assert.deepEqual(queuedTargets, [8, 9])
})

test('cancelling a parent preserves its terminal queued child polling and canvas ownership', async () => {
  const h = harness()
  const order = []
  const child = { id: 'child1', parentJobId: 'job1', sessionId: 'session1', turnIndex: 2,
    status: 'cancelled', executionMode: 'direct', sourceType: 'cloud_document', agentKey: 'codex' }
  h.s.job.value = { id: 'job1', sessionId: 'session1', status: 'running', executionMode: 'direct' }
  Object.assign(h.s, {
    actionBusy: ref(false), cancelling: ref(false), realtimeError: ref(''), pollTimer: null,
    beginActionIdentity: (_type, identity) => ({ ...identity }), assertActionIdentity: noop,
    cancelMindmapAiJob: async (jobId, { preserveDraft }) => {
      assert.equal(jobId, 'job1')
      assert.equal(preserveDraft, true)
      assert.equal(h.s.cancelling.value, true)
      return { data: { ...h.s.job.value, status: 'cancelled' } }
    },
    mergeMindmapAiJobSnapshot: (_old, next) => next, persistActiveJob: () => true,
    stopRealtime: () => order.push(`stopRealtime:${h.s.job.value.id}`),
    stopPolling: () => {
      order.push(`stopPolling:${h.s.job.value.id}`)
      clearTimeout(h.s.pollTimer)
      h.s.pollTimer = null
    },
    schedulePoll: (delay, force) => {
      const jobId = h.s.job.value.id
      order.push(`schedulePoll:${jobId}:${force}`)
      h.s.pollTimer = setTimeout(() => { order.push(`poll:${jobId}`); h.s.pollTimer = null }, delay)
    },
    hydrateTerminalResources: async () => true, refreshTimelineAfterSideEffect: async () => false,
    ElMessage: { error: message => assert.fail(message), warning: noop },
    sessionTurns: ref([{ job: child, userMessage: { content: '下一轮' } }]),
    getMindmapAiJob: async () => ({ data: child }),
    form: { agentKey: 'codex', intent: 'expand' }, queueAttempt: null,
    adoptDirectCanvasRequest: async () => {}, cloneRuntimeValue: structuredClone, draftDocument: ref(null),
    monitoringSuspendedJobId: '', isMindmapAiMessageJob: () => false, intentOptions: [{ value: 'expand' }],
    jobConfiguration: ref({ intent: 'expand' }), discussionMode: ref(false), captureJobConfiguration: value => value,
    sourceContext: ref({ revision: 1 }), sourceFingerprint: ref(''), appendClientPrompt: noop, upsertSessionTurn: noop,
    selectedTurnJobId: ref('job1'), followupPrompt: ref(''), pendingFollowupPrompt: ref(''),
    proposal: ref(null), proposalError: ref(''), diffConfirmed: ref(false),
    clearDurableAttempt: noop, followupAttempt: null, restoreDurableAttemptNotice: noop,
    restoreSessionTimeline: async () => true, restoreGeneration: 1,
  })
  const api = compile(h.s, ['cancelJob', 'settleDirectLiveDraftPreview', 'completeDirectCanvasHandoff',
    'activateQueuedFollowupTurn', 'activateFollowupJob', 'finalizeTerminalJob', 'terminalJobResourceKey'])
  assert.equal(await api.cancelJob(), true)
  assert.equal(h.s.job.value.id, 'child1')
  assert.equal(h.s.directCanvasOwnerId.value, 'child1')
  assert.notEqual(h.s.pollTimer, null, 'the child must retain its terminal drain timer')
  assert(h.events.every(event => event.phase !== 'status'), 'cancellation must only send actionable canvas events')
  assert.deepEqual(order, ['stopRealtime:job1', 'stopPolling:job1', 'stopPolling:job1', 'stopRealtime:job1', 'schedulePoll:child1:true'])
  await new Promise(resolve => setTimeout(resolve, 10))
  assert.equal(order.at(-1), 'poll:child1')
})

test('pending cancellation preserves its draft and polling without a canvas status round trip', async () => {
  const events = []
  const delays = []
  const s = {
    job: ref({ id: 'job1', status: 'running' }), actionBusy: ref(false),
    livePreviewActive: ref(true), cancelling: ref(false), realtimeError: ref(''),
    beginActionIdentity: (_type, identity) => identity, assertActionIdentity: noop,
    cancelMindmapAiJob: async (jobId, options) => {
      assert.equal(s.cancelling.value, true)
      assert.equal(jobId, 'job1')
      assert.deepEqual(options, { preserveDraft: true })
      return { data: { id: jobId, status: 'cancel_requested' } }
    },
    mergeMindmapAiJobSnapshot, persistActiveJob: noop,
    isTerminalStatus: () => false, schedulePoll: delay => delays.push(delay),
    emitAiCanvasPreviewEvent: payload => events.push(payload),
    ElMessage: { error: message => assert.fail(message) },
  }
  const { cancelJob } = compile(s, ['cancelJob'])
  assert.equal(await cancelJob(), true)
  assert.equal(s.job.value.status, 'cancel_requested')
  assert.equal(s.livePreviewActive.value, true)
  assert.equal(s.cancelling.value, false)
  assert.deepEqual(delays, [200])
  assert.deepEqual(events, [])
})

test('canvas editing locks remain active through preparation, playback and terminal ownership', () => {
  const events = []
  const s = {
    job: ref(null), form: { sourceMode: 'current' },
    messageModeActive: ref(false), viewingHistoricalArtifact: ref(false), sourceContext: ref({ readonly: false }),
    running: ref(false), livePreviewActive: ref(false), livePreviewRendering: ref(false),
    livePreviewReverting: ref(false), livePreviewAutoAccepting: ref(false), applying: ref(false),
    cancelling: ref(false), preparingCanvas: ref(true), directCanvasOwned: ref(true),
    bus: { emit: (event, payload) => events.push({ event, ...payload }) },
  }
  const { emitAiEditingState } = compile(s, ['emitAiEditingState'])
  emitAiEditingState()
  s.job.value = { id: 'job1', status: 'running' }
  s.preparingCanvas.value = false
  s.running.value = true
  s.livePreviewActive.value = true
  emitAiEditingState()
  s.job.value.status = 'completed_direct'
  s.running.value = false
  s.livePreviewActive.value = false
  emitAiEditingState()
  s.directCanvasOwned.value = false
  emitAiEditingState()
  assert.deepEqual(events, [
    { event: 'aiEditingState', jobId: '', locked: true },
    { event: 'aiEditingState', jobId: 'job1', locked: true },
    { event: 'aiEditingState', jobId: 'job1', locked: true },
    { event: 'aiEditingState', jobId: 'job1', locked: false },
  ])
})

for (const executionMode of ['direct', 'proposal']) {
  for (const resetCursor of [false, true]) {
    test(`${executionMode} monitoring ${resetCursor ? 'resets' : 'preserves'} cursors, sends only actionable canvas events and starts all monitoring channels`, () => {
      const calls = []
      const events = []
      const s = {
        job: ref({ id: 'job1', status: 'running', executionMode }),
        latestPreviewVersion: ref(9), latestPreviewEpoch: ref(2),
        livePreviewPreparing: ref(true), directCanvasOwnerId: ref(''),
        isTerminalStatus: () => false, isDirectExecutionJob: () => executionMode === 'direct',
        isMindmapAiMessageJob: () => false, hasUnresolvedGenerationRestart: () => false,
        stopPolling: () => calls.push('stop-poll'), stopRealtime: state => calls.push(`stop-stream:${state}`),
        resetCurrentJobCursor: jobId => calls.push(`reset-cursor:${jobId}`),
        syncCurrentJobCursor: jobId => calls.push(`sync-cursor:${jobId}`),
        emitAiCanvasPreviewEvent: payload => {
          assert.equal(s.directCanvasOwnerId.value, 'job1', 'direct ownership precedes its start handshake')
          events.push(payload)
          calls.push(`canvas:${payload.phase}`)
        },
        refreshDraftPreview: async jobId => { calls.push(`refresh:${jobId}`) },
        schedulePoll: delay => calls.push(`poll:${delay}`),
        connectRealtime: jobId => calls.push(`connect:${jobId}`),
      }
      const { beginJobMonitoring } = compile(s, ['beginJobMonitoring'])
      beginJobMonitoring({ resetCursor })
      assert.deepEqual(events, executionMode === 'direct'
        ? [{ phase: 'start', jobId: 'job1', directCommitted: true }]
        : [])
      assert.equal(s.directCanvasOwnerId.value, executionMode === 'direct' ? 'job1' : '')
      assert.equal(s.latestPreviewVersion.value, resetCursor ? -1 : 9)
      assert.equal(s.latestPreviewEpoch.value, resetCursor ? 1 : 2)
      assert.deepEqual(calls, [
        'stop-poll', 'stop-stream:idle', `${resetCursor ? 'reset' : 'sync'}-cursor:job1`,
        ...(executionMode === 'direct' ? ['canvas:start'] : []),
        'refresh:job1', 'poll:0', 'connect:job1',
      ])
    })
  }
}

function restoredDirectJobHarness() {
  const h = harness()
  const order = []
  const targets = []
  const snapshot = { id: 'job1', sessionId: 'session1', sourceType: 'cloud_document',
    sourceMindmapId: 7, executionMode: 'direct', status: 'running' }
  const preview = { available: true, previewEpoch: 2, operationCursor: 9,
    document: { root: { data: { uid: 'root', text: '最新云端' }, children: [] } } }
  const saved = { jobId: snapshot.id, ownerUserId: 'owner', savedAt: Date.now(), sourceMindmapId: 7 }
  h.s.job.value = null
  h.s.directCanvasOwnerId.value = ''
  h.s.livePreviewActive.value = false
  h.s.running.value = true
  Object.assign(h.s, {
    currentAiOwnerUserId: () => 'owner', ACTIVE_JOB_STORAGE_KEY: 'active', RECENT_JOB_STORAGE_KEY: 'recent',
    STORED_JOB_TTL_MS: 60_000, readMindmapAiOwnerSessionItem: key => key === 'active' ? JSON.stringify(saved) : null,
    editorContext: ref({ mindmapId: 7 }), restoreController: null, restoreGeneration: 1,
    restoringJob: ref(false), restoreError: ref(''), timelineError: ref(''), sourceBaselineMismatch: ref(false),
    flushLocalApplyAcks: async () => {}, getMindmapAiJob: async () => ({ data: snapshot }),
    flushPendingCloudMutationIntents: async () => {}, requestEditorContext: async () => ({}),
    terminalHydrationState: ref('idle'),
    readPersistedAttempts: () => ({}), latestSessionTurn: () => null,
    restoreSessionTimeline: async () => { h.s.timelineError.value = 'timeline unavailable'; return false },
    selectedTurnJobId: ref(''), restoreJobSourceState: noop, persistActiveJob: () => true,
    isMindmapAiMessageJob: () => false, isAbortError: error => error?.name === 'AbortError',
    realtimeError: ref(''), realtimeConnectionState: ref('idle'),
    messageModeActive: ref(false), draftDocument: ref(null), draftFreshness: ref(''), draftFreshnessMessage: ref(''),
    latestPreviewVersion: ref(-1), latestPreviewEpoch: ref(1), livePreviewRenderedVersion: ref(-1),
    compareMindmapAiPreviewCoordinates, countMindmapAiDraftNodes, cloneRuntimeValue: structuredClone,
    queueLiveDraftPreview: (_document, cursor) => targets.push(cursor),
    stopPolling: () => order.push('stop-poll'), stopRealtime: () => order.push('stop-stream'),
    livePreviewPreparing: ref(false), syncCurrentJobCursor: noop, hasUnresolvedGenerationRestart: () => false,
    getMindmapAiJobDraft: async () => { order.push('latest-draft'); return { data: preview } },
    emitEditorRequest: async (_event, payload) => { order.push(`editor:${payload.phase}`); return { document: preview.document } },
    refreshDraftPreview: async () => { order.push('refresh'); return false },
    schedulePoll: (_delay, force) => order.push(force ? 'terminal-poll' : 'poll'),
    connectRealtime: () => order.push(`stream:${h.s.latestPreviewEpoch.value}:${h.s.latestPreviewVersion.value}`),
    mergeMindmapAiJobSnapshot: (_old, next) => next,
    ElMessage: { info: message => assert.fail(message) },
  })
  const api = compile(h.s, ['restoreActiveJob', 'resumeRestoredDirectJob', 'beginJobMonitoring',
    'acceptDraftPreview', 'reconcileRestoredSourceBaseline', 'retryStoredJobRecovery', 'retryLivePreviewSync', 'onNetworkOnline'])
  return { ...h, ...api, order, targets, snapshot, preview }
}

test('timeline recovery failure still fences the baseline and establishes the latest draft floor before SSE', async () => {
  const h = restoredDirectJobHarness()
  let resolveDraft
  h.s.getMindmapAiJobDraft = async () => {
    h.order.push('latest-draft')
    return new Promise(resolve => { resolveDraft = resolve })
  }
  h.s.connectRealtime = () => {
    h.order.push(`stream:${h.s.latestPreviewEpoch.value}:${h.s.latestPreviewVersion.value}`)
    assert.equal(h.acceptDraftPreview({ ...h.preview, operationCursor: 1 }), false)
    assert.equal(h.acceptDraftPreview({ ...h.preview, previewEpoch: 1, operationCursor: 99 }), false)
  }
  const restoring = h.restoreActiveJob()
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(h.order, ['stop-poll', 'stop-stream', 'editor:start', 'latest-draft'])
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  assert.deepEqual(h.targets, [], 'no historical frame is allowed while latest checkpoint is pending')
  resolveDraft({ data: h.preview })
  assert.equal(await restoring, true)
  assert.equal(h.s.timelineError.value, 'timeline unavailable')
  assert.equal(h.order.at(-1), 'stream:2:9')
  assert.deepEqual(h.targets, [9])
  assert.equal(h.s.directCanvasRecoveryJobId.value, '')
})

test('failed latest draft recovery preserves the readonly owner and both retry controls resume it', async () => {
  const h = restoredDirectJobHarness()
  h.s.getMindmapAiJobDraft = async () => { throw new Error('draft offline') }
  assert.equal(await h.restoreActiveJob(), false)
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  assert.equal(h.s.directCanvasRecoveryJobId.value, 'job1')
  assert.equal(h.s.restoreError.value, 'draft offline')
  assert.equal(h.s.livePreviewError.value, 'draft offline')
  assert.ok(!h.order.some(item => item.startsWith('stream:') || item === 'poll'))
  // The same production handler backs the restore and stream retry buttons.
  assert.equal(await h.retryStoredJobRecovery(), false)
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  await h.onNetworkOnline()
  assert.ok(!h.order.some(item => item.startsWith('stream:') || item === 'poll'),
    'an online event must not bypass a failed checkpoint recovery')
  h.s.getMindmapAiJobDraft = async () => ({ data: h.preview })
  assert.equal(await h.retryLivePreviewSync(), true)
  assert.equal(h.order.at(-1), 'stream:2:9')
  assert.equal(h.s.directCanvasRecoveryJobId.value, '')
  assert.equal(h.s.restoreError.value, '')
  assert.deepEqual(h.targets, [9])
})

test('restored job completing during latest draft lookup schedules terminal settlement without SSE', async () => {
  const h = restoredDirectJobHarness()
  let reads = 0
  h.s.getMindmapAiJob = async () => ({ data: { ...h.snapshot, status: ++reads === 1 ? 'running' : 'completed_direct' } })
  h.s.getMindmapAiJobDraft = async () => ({ data: { available: false, status: 'completed_direct' } })
  assert.equal(await h.restoreActiveJob(), true)
  assert.equal(h.s.job.value.status, 'completed_direct')
  assert.equal(h.s.directCanvasOwnerId.value, 'job1')
  assert.equal(h.order.at(-1), 'terminal-poll')
  assert.ok(!h.order.some(item => item.startsWith('stream:')))
  assert.deepEqual(h.targets, [])
})

test('a late recovery draft cannot reopen playback after the same job has already settled', async () => {
  const h = restoredDirectJobHarness()
  let resolveDraft
  h.s.getMindmapAiJobDraft = () => new Promise(resolve => { resolveDraft = resolve })
  const restoring = h.restoreActiveJob()
  await new Promise(resolve => setImmediate(resolve))
  // A concurrent cancellation has completed its authoritative settlement.
  h.s.job.value = { ...h.snapshot, status: 'cancelled' }
  h.s.livePreviewGeneration += 1
  h.s.directCanvasRecoveryJobId.value = ''
  h.s.directCanvasOwnerId.value = ''
  resolveDraft({ data: h.preview })
  assert.equal(await restoring, false)
  assert.equal(h.s.directCanvasOwnerId.value, '')
  assert.deepEqual(h.targets, [])
  assert.ok(!h.order.some(item => item.startsWith('stream:') || item === 'terminal-poll'))
})

for (const activationName of ['activateCreatedJob', 'activateRetryJob', 'activateFollowupJob']) {
  for (const recoverExisting of [false, true]) {
    test(`${activationName} ${recoverExisting ? 'restores an existing direct job through the latest floor' : 'starts a new direct job without a recovery round trip'}`, async () => {
      const h = restoredDirectJobHarness()
      Object.assign(h.s, {
        assertActionIdentity: noop, adoptDirectCanvasRequest: async () => {},
        submitAttempt: null, retryAttempt: null, followupAttempt: null, monitoringSuspendedJobId: '',
        discussionMode: ref(false), currentSessionTitle: ref(''),
        deriveMindmapAiSessionTitle: () => '恢复任务', jobConfiguration: ref({ intent: 'expand' }),
        appendClientPrompt: noop, upsertSessionTurn: noop, clearDurableAttempt: noop,
        sourceContext: ref(null), sourceFingerprint: ref(''), proposal: ref(null),
        proposalError: ref(''), diffConfirmed: ref(false), restoreDurableAttemptNotice: noop,
        resetCurrentJobCursor: noop, captureJobConfiguration: value => value,
        form: { intent: 'expand' }, intentOptions: [{ value: 'expand' }], sessionTurns: ref([]),
        followupPrompt: ref(''), pendingFollowupPrompt: ref(''), retryPrompt: ref(''),
        clearAgentRuntimeState: () => { h.s.latestPreviewVersion.value = -1; h.s.latestPreviewEpoch.value = 1 },
        resumeRestoredDirectJob: h.resumeRestoredDirectJob, beginJobMonitoring: h.beginJobMonitoring,
      })
      h.s.latestPreviewVersion.value = 99
      const api = compile(h.s, [activationName])
      assert.equal(await api[activationName](h.snapshot, {
        identity: { jobId: 'previous' }, requestConfiguration: { intent: 'expand' },
        requestPayload: { prompt: '继续编辑', agentKey: 'codex', executionMode: 'direct' },
        attemptKey: 'same-durable-key', preparationId: 'preparing:same-durable-key',
        retryOfJob: { id: 'previous' }, recoverExisting,
      }), true)
      assert.equal(h.order.includes('latest-draft'), recoverExisting)
      assert.deepEqual(h.targets, recoverExisting ? [9] : [])
      assert.equal(h.order.at(-1), recoverExisting ? 'stream:2:9' : 'stream:1:-1')
    })
  }
}

function directReceiptHarness() {
  const id = '7eb610db-263c-46ce-8ecd-c6d40186c571'
  const server = { status: 'running', added: 8, revision: 652 }
  const events = []
  const proposalReads = []
  const retries = []
  const snapshot = () => ({ id, status: server.status, executionMode: 'direct', proposalId: id })
  const receipt = () => ({ id, jobId: id, appliedRevision: server.revision,
    resultHash: `hash:${server.revision}`, status: 'applied',
    impact: { direct: true, changeSummaryVersion: 2,
      changeSummary: { added: server.added, updated: 0, moved: 0, deleted: 0 } } })
  const s = {
    componentAlive: true, job: ref(snapshot()), monitoringSuspendedJobId: '', navigator: { onLine: true },
    pollController: null, realtimeError: ref(''), realtimeConnectionState: ref('connected'),
    proposal: ref(null), proposalError: ref(''), proposalLoading: ref(false), proposalLoadGeneration: 0,
    diffConfirmed: ref(false), restoreGeneration: 1, terminalHydrationGeneration: 0, terminalFinalizationState: null,
    terminalHydrationState: ref('idle'), terminalHydrationError: ref(''),
    terminalHydrationRetryCount: 0, terminalHydrationRetryTimer: null,
    sessionTurns: ref([]), needsInputQuestions: ref([]), form: { sourceMode: 'current' },
    isMindmapAiMessageJob: () => false, isDirectExecutionJob: () => s.job.value.executionMode === 'direct',
    isTerminalStatus: status => ['completed_direct', 'failed', 'cancelled', 'applied'].includes(status),
    isAbortError: error => error?.name === 'AbortError', formatMindmapAiError: error => error.message,
    getMindmapAiJob: async () => ({ data: snapshot() }),
    getMindmapAiProposal: async () => { proposalReads.push(server.revision); return { data: receipt() } },
    mergeMindmapAiJobSnapshot, persistActiveJob: noop, refreshDraftPreview: async () => false,
    settleDirectLiveDraftPreview: async () => true, stopRealtime: noop, stopPolling: noop,
    activateQueuedFollowupTurn: noop, schedulePoll: noop, livePreviewActive: ref(false),
    timelineError: ref(''), scheduleTerminalHydrationRetry: jobId => retries.push(jobId),
    actionBusy: ref(false), cancelling: ref(false), beginActionIdentity: (_type, identity) => identity,
    assertActionIdentity: noop, refreshTimelineAfterSideEffect: async () => true,
    cancelMindmapAiJob: async () => ({ data: { ...snapshot(), status: 'cancelled' } }),
    ElMessage: { error: message => assert.fail(message) },
  }
  const api = compile(s, ['pollJob', 'hydrateTerminalResources', 'loadProposal', 'cancelJob',
    'finalizeTerminalJob', 'terminalJobResourceKey'])
  const displayed = () => directImpactForMindmapAiResult(s.proposal.value,
    resolveMindmapAiDirectChangeSummary({ proposal: s.proposal.value, events, jobId: s.job.value.id }))
  return { s, id, server, events, proposalReads, retries, receipt, displayed, ...api }
}

test('running first-batch receipt 8 is refreshed to terminal 84 despite its stable proposal ID', async () => {
  const h = directReceiptHarness()
  await h.pollJob()
  assert.equal(h.displayed().createdCount, 8)
  assert.equal(h.s.proposal.value.appliedRevision, 652)
  Object.assign(h.server, { status: 'completed_direct', added: 84, revision: 658 })
  h.events.push({ jobId: h.id, eventType: 'direct_completed', payload: {
    changeSummaryVersion: 2, changeSummary: { added: 84, updated: 0, moved: 0, deleted: 0 },
  } })
  assert.equal(h.displayed().createdCount, 84, 'the terminal event wins before the receipt refresh resolves')
  await h.pollJob()
  assert.deepEqual(h.proposalReads, [652, 658])
  assert.equal(h.s.proposal.value.appliedRevision, 658)
  assert.equal(h.s.proposal.value.resultHash, 'hash:658')
  assert.equal(h.displayed().createdCount, 84)
  assert.equal(h.s.terminalHydrationState.value, 'ready')
})

test('failure and explicit cancellation refresh committed direct counters without a terminal summary event', async () => {
  for (const status of ['failed', 'cancelled']) {
    const h = directReceiptHarness()
    await h.pollJob()
    Object.assign(h.server, { status, added: 20, revision: 653 })
    if (status === 'cancelled') assert.equal(await h.cancelJob(), true)
    else await h.pollJob()
    assert.deepEqual(h.proposalReads, [652, 653])
    assert.equal(h.displayed().createdCount, 20)
    assert.equal(h.s.terminalHydrationState.value, 'ready')
  }
})

test('normal immutable proposal hydration keeps its same-ID cache', async () => {
  const h = directReceiptHarness()
  h.s.job.value = { ...h.s.job.value, executionMode: 'proposal', status: 'applied' }
  h.s.proposal.value = h.receipt()
  assert.equal(await h.hydrateTerminalResources(h.id), true)
  assert.deepEqual(h.proposalReads, [])
})

test('a late running receipt cannot overwrite the newer terminal receipt or its ready state', async () => {
  const h = directReceiptHarness()
  const runningReceipt = h.receipt()
  let resolveRunning
  h.s.getMindmapAiProposal = () => new Promise(resolve => { resolveRunning = resolve })
  const runningRead = h.loadProposal()
  Object.assign(h.server, { status: 'completed_direct', added: 84, revision: 658 })
  h.s.job.value.status = 'completed_direct'
  h.s.getMindmapAiProposal = async () => ({ data: h.receipt() })
  assert.equal(await h.hydrateTerminalResources(h.id), true)
  resolveRunning({ data: runningReceipt })
  assert.equal(await runningRead, false)
  assert.equal(h.displayed().createdCount, 84)
  assert.equal(h.s.terminalHydrationState.value, 'ready')
})

test('superseded terminal hydration and old-job responses cannot change a newer result', async () => {
  const h = directReceiptHarness()
  h.s.job.value.status = 'completed_direct'
  const staleReceipt = h.receipt()
  let resolveStale
  h.s.getMindmapAiProposal = () => new Promise(resolve => { resolveStale = resolve })
  const olderHydration = h.hydrateTerminalResources(h.id)
  Object.assign(h.server, { added: 84, revision: 658 })
  h.s.getMindmapAiProposal = async () => ({ data: h.receipt() })
  assert.equal(await h.hydrateTerminalResources(h.id), true)
  resolveStale({ data: staleReceipt })
  assert.equal(await olderHydration, false)
  assert.equal(h.s.terminalHydrationState.value, 'ready')
  assert.deepEqual(h.retries, [])
  assert.equal(h.displayed().createdCount, 84)

  h.s.getMindmapAiProposal = () => new Promise(resolve => { resolveStale = resolve })
  const oldJobHydration = h.hydrateTerminalResources(h.id)
  h.s.job.value = { id: 'next-job', proposalId: 'next-proposal', executionMode: 'direct', status: 'completed_direct' }
  const nextReceipt = { id: 'next-proposal', jobId: 'next-job', impact: { changeSummary: { added: 2 } } }
  h.s.proposal.value = nextReceipt
  h.s.terminalHydrationState.value = 'ready'
  resolveStale({ data: h.receipt() })
  assert.equal(await oldJobHydration, false)
  assert.equal(h.s.proposal.value, nextReceipt)
  assert.equal(h.s.terminalHydrationState.value, 'ready')
})
