import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { babelParse, parse } from '@vue/compiler-sfc'
import { computed, ref } from 'vue'
import { isMindmapAiAbortError, formatMindmapAiError } from '../mindmap-ai-errors.js'
import { isMindmapAiMessageJob } from '../mindmap-ai-conversation.js'
import {
  clearMindmapAiOwnerSessionItem,
  readMindmapAiOwnerSessionItem,
  writeMindmapAiOwnerSessionItem,
} from '../mindmap-ai-owner-session.js'
import { memoryStorage } from './helpers/memory-storage.mjs'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const declarations = babelParse(script, { sourceType: 'module' }).program.body
const noop = () => {}
function compile(scope, names) {
  const functions = names.map(name => {
    const node = declarations.find(node => node.type === 'FunctionDeclaration' && node.id.name === name)
    assert.ok(node, name)
    return script.slice(node.start, node.end)
  }).join('\n')
  return new Function('scope', `with(scope) { ${functions}; return { ${names.join(',')} }; }`)(scope)
}
function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
function task(id = 'old-job', status = 'completed_direct') {
  return { id, sessionId: `session:${id}`, status, sourceType: 'cloud_document', sourceMindmapId: 7 }
}

function harness({ initialJob = task(), storage = memoryStorage() } = {}) {
  const effects = []
  const scope = {
    componentAlive: true, requestedTaskSequence: 0, restoreGeneration: 1, restoreController: null,
    userId: '42', job: ref(initialJob), visible: ref(false), restoringJob: ref(false),
    sessionSwitching: ref(false), livePreviewCanvasMutationBlocked: ref(false),
    sessionMenuVisible: ref(false), agents: ref([{}]), restoreError: ref(''),
    currentSessionTitle: ref('old session'), sourceContext: ref({ mindmapId: 7, revision: 1 }),
    editorContext: ref({ mindmapId: 7 }), sourceFingerprint: ref(''), jobConfiguration: ref({}),
    route: { path: '/mindmap/edit', query: { id: '7' } }, selectedTurnJobId: ref(''),
    realtimeConnectionState: ref('idle'), realtimeError: ref(''),
    ACTIVE_JOB_STORAGE_KEY: 'active', RECENT_JOB_STORAGE_KEY: 'recent', STORED_JOB_TTL_MS: 60_000,
    isTerminalStatus: status => ['completed_direct', 'undone'].includes(status),
    currentAiOwnerUserId: () => scope.userId,
    isMindmapAiMessageJob, isAbortError: isMindmapAiAbortError, formatMindmapAiError,
    captureJobConfiguration: () => ({}),
    ElMessage: { info: message => effects.push(['info', message]) },
    requestEditorContext: async () => scope.editorContext.value,
    getMindmapAiJob: async id => { effects.push(['get', id]); return { data: task(id) } },
    loadCapabilities: async () => { effects.push(['capabilities']); scope.agents.value = [{}]; return true },
    readMindmapAiOwnerSessionItem: (key, owner) => readMindmapAiOwnerSessionItem(key, owner, storage),
    writeMindmapAiOwnerSessionItem: (key, owner, value) => {
      effects.push(['write', key, JSON.parse(value).jobId])
      return writeMindmapAiOwnerSessionItem(key, owner, value, storage)
    },
    clearMindmapAiOwnerSessionItem: (key, owner) => {
      effects.push(['clear', key])
      return clearMindmapAiOwnerSessionItem(key, owner, storage)
    },
    // Renderer/controller teardown is outside this entry-point test. Keep its
    // synchronous ownership rejection and generation transition contract.
    resetNewJob: () => {
      if (scope.running.value || scope.livePreviewCanvasMutationBlocked.value) return false
      effects.push(['reset'])
      scope.restoreGeneration += 1
      scope.job.value = null
      return true
    },
    flushLocalApplyAcks: async () => {}, readPersistedAttempts: () => ({}),
    restoreSessionTimeline: async () => [], latestSessionTurn: () => null,
    restoreJobSourceState: (_job, saved) => { scope.sourceContext.value = { mindmapId: saved.sourceMindmapId } },
    reconcileRestoredSourceBaseline: async () => true,
    finalizeTerminalJob: async () => true, beginJobMonitoring: noop,
    router: { replace: async route => { effects.push(['replace', route]); scope.route.query = route.query } },
  }
  scope.running = computed(() => Boolean(scope.job.value && !scope.isTerminalStatus(scope.job.value.status)))
  scope.actionBusy = computed(() => scope.restoringJob.value || scope.sessionSwitching.value)
  const api = compile(scope, [
    'getRequestedAiJobId', 'taskOpenContextKey', 'restoreRequestedAiJob', 'switchToSession',
    'sessionPointer', 'sessionUnavailableReason', 'persistJobPointer', 'persistActiveJob', 'restoreActiveJob', 'cloneRuntimeValue',
  ])
  const oldPointer = { ownerUserId: '42', jobId: initialJob?.id || 'previous', sourceMindmapId: 7, savedAt: Date.now() }
  storage.setItem('recent:42', JSON.stringify(oldPointer))
  const previousStorage = [...storage.values]
  return { scope, effects, storage, previousStorage, ...api }
}

test('hidden terminal task opens the requested session and updates its pointer only after authoritative validation', async () => {
  const h = harness()
  const gate = deferred()
  h.scope.getMindmapAiJob = async id => {
    h.effects.push(['get', id])
    return h.effects.filter(effect => effect[0] === 'get').length === 1 ? gate.promise : { data: task(id) }
  }
  const opening = h.restoreRequestedAiJob('requested-job')
  await Promise.resolve()
  assert.equal(h.scope.job.value.id, 'old-job')
  assert.deepEqual([...h.storage.values], h.previousStorage)
  gate.resolve({ data: task('requested-job') })
  assert.equal(await opening, true)
  assert.equal(h.scope.visible.value, true)
  assert.equal(h.scope.job.value.id, 'requested-job')
  assert.equal(JSON.parse(h.storage.getItem('recent:42')).jobId, 'requested-job')
  assert.equal(h.effects.filter(effect => effect[0] === 'reset').length, 1)
  assert.ok(h.effects.findIndex(effect => effect[0] === 'write') > h.effects.findIndex(effect => effect[0] === 'get'))
})

test('a hidden running or canvas-owned task rejects a different task without touching its pointer', async () => {
  for (const running of [false, true]) {
    const h = harness({ initialJob: task('old-job', running ? 'running' : 'completed_direct') })
    h.scope.livePreviewCanvasMutationBlocked.value = !running
    assert.equal(await h.restoreRequestedAiJob('requested-job'), false)
    assert.equal(h.scope.job.value.id, 'old-job')
    assert.deepEqual([...h.storage.values], h.previousStorage)
    assert.deepEqual(h.effects, [])
  }
})

test('reopening the same hidden owned task does not fetch, reset or recapture its canvas baseline', async () => {
  const h = harness({ initialJob: task('old-job', 'running') })
  h.scope.livePreviewCanvasMutationBlocked.value = true
  const oldJob = h.scope.job.value
  assert.equal(await h.restoreRequestedAiJob('old-job'), true)
  assert.equal(h.scope.job.value, oldJob)
  assert.equal(h.scope.visible.value, true)
  assert.deepEqual(h.effects, [])
  assert.deepEqual([...h.storage.values], h.previousStorage)
})

test('first task-center opening initializes capabilities and clears only the consumed route request', async () => {
  const h = harness({ initialJob: null })
  h.scope.agents.value = []
  h.scope.route.query.aiJobId = 'requested-job'
  assert.equal(await h.restoreRequestedAiJob(), true)
  assert.equal(h.scope.job.value.id, 'requested-job')
  assert.ok(h.effects.some(effect => effect[0] === 'capabilities'))
  assert.deepEqual(h.scope.route.query, { id: '7' })
})

test('late task responses cannot switch after unmount, account change, document navigation or explicit reset', async () => {
  for (const invalidate of [
    s => { s.componentAlive = false }, s => { s.userId = '43' },
    s => { s.route.query.id = '8' }, s => { s.restoreGeneration += 1 },
  ]) {
    const h = harness()
    const gate = deferred()
    h.scope.getMindmapAiJob = async () => gate.promise
    const opening = h.restoreRequestedAiJob('requested-job')
    await Promise.resolve()
    invalidate(h.scope)
    gate.resolve({ data: task('requested-job') })
    assert.equal(await opening, false)
    assert.equal(h.scope.job.value.id, 'old-job')
    assert.deepEqual([...h.storage.values], h.previousStorage)
    assert.equal(h.scope.restoreError.value, '')
  }
})

test('out-of-order task-center lookups accept only the newest requested task', async () => {
  const h = harness()
  const first = deferred()
  h.scope.getMindmapAiJob = async id => id === 'first-job' ? first.promise : { data: task(id) }
  const openingFirst = h.restoreRequestedAiJob('first-job')
  await Promise.resolve()
  assert.equal(await h.restoreRequestedAiJob('second-job'), true)
  first.resolve({ data: task('first-job') })
  assert.equal(await openingFirst, false)
  assert.equal(h.scope.job.value.id, 'second-job')
  assert.equal(JSON.parse(h.storage.getItem('recent:42')).jobId, 'second-job')
})

test('wrong job/document/session responses and lookup failures preserve the previous task and recovery pointer', async () => {
  for (const invalid of [
    task('unexpected-job'), { ...task('requested-job'), sourceMindmapId: 8 },
    { ...task('requested-job'), sessionId: null }, new Error('network unavailable'),
  ]) {
    const h = harness()
    h.scope.getMindmapAiJob = async () => {
      if (invalid instanceof Error) throw invalid
      return { data: invalid }
    }
    assert.equal(await h.restoreRequestedAiJob('requested-job'), false)
    assert.equal(h.scope.job.value.id, 'old-job')
    assert.deepEqual([...h.storage.values], h.previousStorage)
    assert.ok(h.scope.restoreError.value)
  }
})

test('a storage failure does not reset the old task or erase its active recovery pointer', async () => {
  const storage = memoryStorage()
  const h = harness({ storage })
  storage.setItem('active:42', storage.getItem('recent:42'))
  const previous = [...storage.values]
  storage.setItem = () => { throw new Error('quota') }
  assert.equal(await h.restoreRequestedAiJob('requested-job'), false)
  assert.equal(h.scope.job.value.id, 'old-job')
  assert.deepEqual([...storage.values], previous)
  assert.equal(h.effects.some(effect => effect[0] === 'reset' || effect[0] === 'clear'), false)
  assert.match(h.scope.restoreError.value, /恢复指针/)
  assert.equal(h.persistActiveJob(), false)
  assert.deepEqual([...storage.values], previous)
})

test('ordinary session-menu selection also validates authoritative identity before committing its pointer', async () => {
  const h = harness()
  h.scope.getMindmapAiJob = async () => ({ data: { ...task('requested-job'), sessionId: 'wrong-session' } })
  assert.equal(await h.switchToSession({ sessionId: 'session:requested-job', currentJob: task('requested-job') }), false)
  assert.deepEqual([...h.storage.values], h.previousStorage)
  assert.equal(h.scope.job.value.id, 'old-job')
  assert.equal(h.scope.sessionSwitching.value, false)
})

test('route/account invalidation while capabilities load still preserves the old task and pointer', async () => {
  for (const invalidate of [s => { s.userId = '43' }, s => { s.route.query.id = '8' }]) {
    const h = harness()
    const gate = deferred()
    h.scope.agents.value = []
    h.scope.loadCapabilities = async () => gate.promise
    const opening = h.switchToSession({ sessionId: 'session:requested-job', currentJob: task('requested-job') })
    await Promise.resolve()
    invalidate(h.scope)
    gate.resolve(true)
    assert.equal(await opening, false)
    assert.equal(h.scope.job.value.id, 'old-job')
    assert.deepEqual([...h.storage.values], h.previousStorage)
    assert.equal(h.scope.sessionSwitching.value, false)
  }
})

test('a rejected click while a switch owns the mutex does not invalidate the accepted open operation', async () => {
  const h = harness()
  const gate = deferred()
  h.scope.agents.value = []
  h.scope.loadCapabilities = async () => gate.promise
  const opening = h.restoreRequestedAiJob('first-job')
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(h.scope.sessionSwitching.value, true)
  assert.equal(await h.restoreRequestedAiJob('second-job'), false)
  assert.equal(await h.restoreRequestedAiJob('old-job'), false)
  gate.resolve(true)
  assert.equal(await opening, true)
  assert.equal(h.scope.job.value.id, 'first-job')
})

test('updateData keeps the synchronous single-argument contract while the AI renderAsync entry remains available', () => {
  const source = readFileSync(new URL('../../libs/simple-mind-map/index.js', import.meta.url), 'utf8')
  const klass = babelParse(source, { sourceType: 'module' }).program.body.find(node => node.type === 'ClassDeclaration')
  const method = klass.body.body.find(node => node.key.name === 'updateData')
  assert.equal(method.params.length, 1)
  const events = []
  const update = new Function('data', source.slice(method.body.start + 1, method.body.end - 1))
  update.call({
    handleData: data => ({ ...data, normalized: true }),
    emit: event => events.push(event), renderer: { setData: data => events.push(data) },
    render: () => events.push('render'), command: { addHistory: () => events.push('history') },
  }, { root: 'tree' })
  assert.deepEqual(events, ['before_update_data', { root: 'tree', normalized: true }, 'render', 'history', 'update_data'])
  assert.ok(klass.body.body.some(node => node.key.name === 'renderAsync'))
})
