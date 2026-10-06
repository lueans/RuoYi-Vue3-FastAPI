import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createRenderer, effectScope, nextTick, ref } from 'vue'
import { babelParse, parse } from '@vue/compiler-sfc'
import { markAuthSessionExpired, resetAuthExpirySession } from '../auth-expiry.js'
import { useMindmapAuthExpiry } from '../use-mindmap-auth-expiry.js'
import { useMindmapExecutionStop } from '../use-mindmap-execution-stop.js'
import { useMindmapAgentDevices } from '../use-mindmap-agent-devices.js'

const tick = () => new Promise(resolve => setImmediate(resolve))
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function componentFunctions(file, names, scope) {
  const script = parse(readFileSync(new URL(`../../components/MindMap/${file}`, import.meta.url), 'utf8')).descriptor.scriptSetup.content
  const nodes = babelParse(script, { sourceType: 'module' }).program.body
  const selected = names.map(name => nodes.find(node => node.type === 'FunctionDeclaration' && node.id.name === name))
  assert.ok(selected.every(Boolean))
  return new Function('scope', `with (scope) { ${selected.map(node => script.slice(node.start, node.end)).join('\n')}; return { ${names.join(',')} }; }`)(scope)
}
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null,
})

test('expiry subscriptions fence mounted panels and panels mounted after expiration, then reset only for a fresh login', () => {
  resetAuthExpirySession()
  const token = ref('current')
  let expired, cleaned = 0
  const mount = () => {
    const app = renderer.createApp({ setup() {
      expired = useMindmapAuthExpiry(() => token.value, () => { cleaned++ })
      return () => null
    } })
    app.mount({})
    return app
  }
  const first = mount()
  markAuthSessionExpired('old-request')
  assert.equal(expired.value, false, 'a stale credential cannot pause the current panel')
  markAuthSessionExpired('current')
  assert.equal(expired.value, true)
  assert.equal(cleaned, 1)
  first.unmount()
  const late = mount()
  assert.equal(expired.value, true)
  assert.equal(cleaned, 2)
  resetAuthExpirySession()
  token.value = 'new-login'
  assert.equal(expired.value, false)
  late.unmount()
  resetAuthExpirySession()
})

test('task center aborts an expired in-flight request and neither focus nor its 15-second timer can restart requests', async () => {
  const request = deferred()
  const timers = new Map()
  let requestOptions, calls = 0
  const s = {
    authExpired: ref(false), loading: ref(false), error: ref(''), rawSessions: ref([{ sessionId: 'retained' }]),
    page: ref(1), pageSize: 20, total: ref(0), serverAttentionTotal: ref(null),
    componentAlive: true, requestController: null, refreshTimer: null,
    listMindmapAiSessions: options => { requestOptions = options; calls++; return request.promise },
    formatMindmapAiError: error => error.message,
    setTimeout: callback => { const id = Symbol(); timers.set(id, callback); return id },
    clearTimeout: id => timers.delete(id),
  }
  const api = componentFunctions('MindmapAiTaskCenter.vue', ['refreshTasks', 'scheduleRefresh', 'onWindowFocus', 'stopForAuthExpiry'], s)
  const pending = api.refreshTasks()
  api.scheduleRefresh()
  s.authExpired.value = true
  api.stopForAuthExpiry()
  assert.equal(requestOptions.signal.aborted, true)
  request.reject(Object.assign(new Error('401'), { status: 401 }))
  await pending
  api.onWindowFocus()
  api.scheduleRefresh()
  await api.refreshTasks()
  assert.equal(calls, 1)
  assert.equal(timers.size, 0)
  assert.equal(s.error.value, '')
  assert.deepEqual(s.rawSessions.value, [{ sessionId: 'retained' }])
})

test('AI expiration stops existing work and cannot restart polling, streaming, templates or online recovery while retaining composer state', async () => {
  const request = deferred()
  const timers = new Map()
  let nextTimer = 0, calls = 0
  const s = {
    authExpired: ref(false), componentAlive: true, job: ref({ id: 'job', status: 'running' }),
    navigator: { onLine: true }, monitoringSuspendedJobId: '',
    pollTimer: 1, pollController: null, draftController: new AbortController(),
    realtimeController: new AbortController(), realtimeGeneration: 0, realtimeReconnectTimer: 2,
    realtimeReconnectAttempt: 2, realtimeConnectionState: ref('connected'),
    terminalFinalizationState: { controller: new AbortController() }, terminalHydrationGeneration: 1,
    terminalHydrationRetryTimer: 3, livePreviewFlushTimer: 4, livePreviewAutoAcceptTimer: 5,
    generationClockTimer: 6, livePreviewGeneration: 1, livePreviewPaused: ref(false),
    templateSelecting: ref(true), attachmentReading: ref(true),
    composerText: ref('保留未发送内容'), composerAttachments: ref([{ id: 'file', text: '保留附件' }]),
    composerDraftPersistence: { update: value => { assert.equal(value, s.composerText.value) } },
    loadingAgents: ref(true), sessionMenuVisible: ref(true), showAdvancedSettings: ref(true),
    agentManagerVisible: ref(true), agentSwitchGeneration: 1, agentSwitchPending: ref(true),
    invalidateActionIdentity() {}, invalidateRestoreOperations() {}, invalidateSessionList() {},
    clearLocalAckRetryTimer() {}, cancelTemplateRequests() {}, clearLivePreviewAnnouncement() {},
    getMindmapAiJob: () => { calls++; return request.promise },
    isTerminalStatus: () => false,
    setTimeout: callback => { const id = ++nextTimer; timers.set(id, callback); return id },
    clearTimeout: id => timers.delete(id), clearInterval: id => timers.delete(id),
  }
  const names = ['pauseForAuthExpiry', 'stopPolling', 'stopRealtime', 'pollJob', 'schedulePoll',
    'scheduleRealtimeReconnect', 'connectRealtime', 'loadComposerTemplates', 'selectComposerTemplate',
    'onNetworkOnline', 'scheduleLocalAckRetry', 'beginJobMonitoring']
  const api = componentFunctions('MindmapAiDialog.vue', names, s)
  const pending = api.pollJob()
  const poll = s.pollController, stream = s.realtimeController, draft = s.draftController
  s.authExpired.value = true
  api.pauseForAuthExpiry()
  request.reject(Object.assign(new Error('401'), { status: 401 }))
  await pending
  for (const controller of [poll, stream, draft]) assert.equal(controller.signal.aborted, true)
  await api.pollJob()
  api.schedulePoll()
  api.scheduleRealtimeReconnect('job')
  api.connectRealtime('job')
  api.beginJobMonitoring()
  await api.loadComposerTemplates()
  await api.selectComposerTemplate({ id: 3 })
  await api.onNetworkOnline()
  api.scheduleLocalAckRetry()
  assert.equal(calls, 1)
  assert.equal(timers.size, 0)
  assert.equal(s.realtimeConnectionState.value, 'auth-expired')
  assert.equal(s.livePreviewPaused.value, true)
  assert.equal(s.attachmentReading.value, false)
  assert.equal(s.composerText.value, '保留未发送内容')
  assert.deepEqual(s.composerAttachments.value, [{ id: 'file', text: '保留附件' }])
  assert.equal(s.job.value.id, 'job')
})

test('independent execution-stop and device polling abort their requests when authentication becomes unavailable', async () => {
  const scope = effectScope()
  const enabled = ref(true), job = ref({ id: 'job', status: 'ready', executionEpoch: 1, executionState: 'running' })
  const requests = [], deferreds = []
  const list = (_id, options) => {
    requests.push(options)
    const pending = deferred(); deferreds.push(pending)
    return pending.promise
  }
  const monitor = scope.run(() => useMindmapExecutionStop({
    job, ownerId: () => 'owner', enabled: () => enabled.value, loadJob: list,
  }))
  const devices = scope.run(() => useMindmapAgentDevices(() => enabled.value, () => 'owner', options => list('', options)))
  assert.equal(requests.length, 2)
  enabled.value = false
  await nextTick()
  assert.ok(requests.every(item => item.signal.aborted))
  deferreds.forEach(item => item.reject(new Error('late401')))
  await tick()
  await monitor.refresh()
  await devices.refresh()
  assert.equal(requests.length, 2)
  assert.equal(job.value.executionState, 'running', 'expiration is not evidence the server executor stopped')
  scope.stop()
})


test('a successful response released after expiry cannot replace job or preview state', async () => {
  for (const method of ['pollJob', 'refreshDraftPreview']) {
    const pending = deferred()
    let applied = false
    const s = {
      authExpired: ref(false), componentAlive: true, job: ref({ id: 'job', status: 'running' }),
      navigator: { onLine: true }, monitoringSuspendedJobId: '', selectedTurnJobId: ref(''),
      isTerminalStatus: () => false, isMindmapAiMessageJob: () => false,
      pollController: null, draftController: null,
      getMindmapAiJob: () => pending.promise, getMindmapAiJobDraft: () => pending.promise,
      mergeMindmapAiJobSnapshot: () => { applied = true }, acceptDraftPreview: () => { applied = true },
    }
    const api = componentFunctions('MindmapAiDialog.vue', [method], s)
    const response = api[method]('job')
    s.authExpired.value = true
    ;(s.pollController || s.draftController).abort()
    pending.resolve({ data: { id: 'job', status: 'completed_direct' } })
    await response
    assert.equal(applied, false, method)
    assert.equal(s.job.value.status, 'running')
  }
})
