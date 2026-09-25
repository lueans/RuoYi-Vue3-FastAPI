import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  compareMindmapAiPreviewCoordinates,
  countMindmapAiDraftNodes,
  describeMindmapAiDraftChange,
  nextMindmapAiDraftFrame,
  summarizeMindmapAiDraftChanges,
} from '../mindmap-ai-live-preview.js'
import { getMindmapAiPendingCharacterCount, getMindmapAiPlaybackPacing } from '../mindmap-ai-playback-pacing.js'

// Execute the actual Dialog queue/scheduler/flush, with deterministic timers
// and an editor ACK boundary. The planner and pacing are production functions.
const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const node = (uid, text, children = []) => ({ data: { uid, text }, children })
const baseline = () => ({ root: node('root', '根') })
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
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
function harness(options = {}) {
  const events = []
  const timers = new Map()
  let timerId = 0
  let clock = 1000
  const s = {
    job: ref({ id: 'job1', status: 'running', executionMode: 'direct' }),
    livePreviewPendingFrame: null, livePreviewOldestPendingAt: null,
    livePreviewFlushTimer: null, livePreviewFlushInFlight: false,
    livePreviewFlushPromise: Promise.resolve(), livePreviewRevertPromise: Promise.resolve(true),
    livePreviewGeneration: 1, livePreviewJobId: '', livePreviewEditorStarted: false,
    livePreviewRenderedDocument: null, livePreviewBaselineDocument: null,
    livePreviewActive: ref(false), livePreviewPaused: ref(false), livePreviewRendering: ref(false),
    livePreviewEligible: ref(true), livePreviewError: ref(''), livePreviewFramesPending: ref(false),
    livePreviewRenderedVersion: ref(-1), latestPreviewEpoch: ref(1),
    livePreviewRenderedNodeCount: ref(0), livePreviewTargetNodeCount: ref(0), livePreviewChangeSummary: ref(null),
    livePreviewApplyingJobId: '', livePreviewSuppressedJobId: '', directTerminalTargetJobId: '',
    visible: ref(true), canApplyLiveCanvasDraft: ref(false),
    Date: { now: () => clock },
    setTimeout: (callback, delay) => {
      const id = ++timerId
      timers.set(id, { callback, delay })
      return id
    },
    isTerminalStatus: status => ['cancelled', 'failed', 'completed_direct'].includes(status),
    isDirectExecutionJob: () => true,
    readLivePreviewSuppression: () => false,
    cloneRuntimeValue: structuredClone,
    formatMindmapAiError: error => error.message,
    getMindmapAiPendingCharacterCount,
    getMindmapAiPlaybackPacing: input => getMindmapAiPlaybackPacing({ ...input, now: clock }),
    countMindmapAiDraftNodes, describeMindmapAiDraftChange,
    nextMindmapAiDraftFrame, summarizeMindmapAiDraftChanges,
    emitEditorRequest: async (_event, payload) => {
      events.push(payload)
      if (payload.phase === 'start') {
        await options.start?.(payload)
        return { document: options.baseline || baseline() }
      }
      await options.update?.(payload)
      return { rendered: true }
    },
  }
  const names = ['livePreviewFrameDelay', 'scheduleLivePreviewFlush', 'flushLiveDraftPreview', 'queueLiveDraftPreview',
    'resumeRestoredDirectJob', 'beginJobMonitoring', 'acceptDraftPreview']
  const api = new Function('scope', `with (scope) { ${names.map(functionSource).join('\n')} return { ${names.join(', ')} }; }`)(s)
  const nextTimer = () => timers.values().next().value
  async function fireNext() {
    const entry = timers.entries().next().value
    assert(entry, 'expected a scheduled playback frame')
    const [id, timer] = entry
    timers.delete(id)
    clock += timer.delay
    timer.callback()
    await tick()
  }
  async function drain(limit = 200) {
    for (let index = 0; timers.size && index < limit; index++) await fireNext()
    assert.equal(timers.size, 0, 'playback must drain within the test frame limit')
    assert.equal(s.livePreviewFlushInFlight, false)
  }
  return {
    s, events, timers, ...api, fireNext, drain, nextTimer,
    advance: milliseconds => { clock += milliseconds },
    now: () => clock,
    updates: () => events.filter(event => event.phase === 'update'),
  }
}

test('真实首帧从编辑器基线重估，然后只展示第一个节点的首字', async () => {
  const h = harness()
  const target = { root: node('root', '根', [node('first', '第一节点'), node('second', '第二节点')]) }
  h.queueLiveDraftPreview(target, 1)
  assert.equal(h.nextTimer().delay, 0, 'ownership/baseline handshake starts immediately')
  await h.fireNext()
  assert.deepEqual(h.events.map(event => event.phase), ['start'])
  assert.equal(h.s.livePreviewPendingFrame.pendingCharacters, 8, 'baseline root must not be counted as newly generated text')
  assert.equal(h.nextTimer().delay, 56)
  await h.fireNext()
  assert.equal(h.updates()[0].document.root.children[0].data.text, '第')
  assert.equal(h.updates()[0].document.root.children.length, 1)
  assert.equal(h.s.livePreviewPendingFrame.pendingCharacters, 7)
  assert.equal(Object.hasOwn(h.s.livePreviewPendingFrame, 'batchSize'), false)
  await h.drain()
  assert.deepEqual(h.s.livePreviewRenderedDocument, target)
  assert(h.events.every(event => ['start', 'update'].includes(event.phase)))
  for (const event of h.events) {
    assert.equal(Object.hasOwn(event, 'connectionState'), false)
    assert.equal(Object.hasOwn(event, 'revealUids'), false)
  }
})

test('大积压使用更快定时器，但必须播完当前节点才能开始下一个', async () => {
  const h = harness()
  const target = { root: node('root', '根', [node('first', '甲乙丙'), node('second', '字'.repeat(2000))]) }
  h.queueLiveDraftPreview(target, 1)
  await h.fireNext()
  assert.equal(h.s.livePreviewPendingFrame.pendingCharacters, 2003)
  assert.equal(h.nextTimer().delay, 0)
  for (let index = 0; index < 4; index++) await h.fireNext()
  assert.deepEqual(h.updates().map(event => [event.change.uid, event.change.text]), [
    ['first', '甲'], ['first', '甲乙'], ['first', '甲乙丙'], ['second', '字'],
  ])
  assert.equal(h.s.livePreviewPendingFrame.pendingCharacters, 1999)
  assert.equal(h.nextTimer().delay, 0)
})

test('单个长节点不会因为只有一个pending节点而恢复为56ms固定速度', async () => {
  const h = harness()
  h.queueLiveDraftPreview({ root: node('root', '根', [node('long', '长'.repeat(2000))]) }, 1)
  await h.fireNext()
  await h.fireNext()
  assert.equal(h.s.livePreviewPendingFrame.pendingNodes, 1)
  assert.equal(h.s.livePreviewPendingFrame.pendingCharacters, 1999)
  assert.equal(h.nextTimer().delay, 0)
  assert.equal(h.updates()[0].change.text, '长')
})

test('终态回源仍逐字补齐，减少延迟但不能直接安装最终全文', async () => {
  const h = harness()
  h.s.job.value.status = 'completed_direct'
  h.s.directTerminalTargetJobId = 'job1'
  h.s.livePreviewEligible.value = false
  const target = { root: node('root', '根', [node('first', '最终正文')]) }
  h.queueLiveDraftPreview(target, 1, null, { authoritativeTerminal: true })
  await h.fireNext()
  assert(h.nextTimer().delay <= 16)
  await h.fireNext()
  assert.equal(h.updates()[0].change.text, '最')
  await h.drain()
  assert.deepEqual(h.updates().map(event => event.change.text), ['最', '最终', '最终正', '最终正文'])
  assert.deepEqual(h.s.livePreviewRenderedDocument, target)
})

test('连续替换目标保留队列年龄，真正排空后下一批才重新计时', async () => {
  const h = harness()
  h.queueLiveDraftPreview({ root: node('root', '根', [node('first', '甲乙')]) }, 1)
  const startedAt = h.s.livePreviewOldestPendingAt
  await h.fireNext()
  h.advance(4000)
  const latest = { root: node('root', '根', [node('first', '甲乙丙')]) }
  h.queueLiveDraftPreview(latest, 2)
  assert.equal(h.s.livePreviewOldestPendingAt, startedAt)
  await h.drain()
  assert.equal(h.s.livePreviewOldestPendingAt, null)
  assert.deepEqual(h.s.livePreviewRenderedDocument, latest)
  h.advance(300)
  h.queueLiveDraftPreview({ root: node('root', '根', [node('first', '甲乙丙丁')]) }, 3)
  assert.equal(h.s.livePreviewOldestPendingAt, h.now())
  assert(h.s.livePreviewOldestPendingAt > startedAt)
})

test('编辑器握手在途到达新目标时，以新目标重估而不把旧帧重新入队', async () => {
  const start = deferred()
  const h = harness({ start: () => start.promise })
  h.queueLiveDraftPreview({ root: node('root', '根', [node('old', '旧目标')]) }, 1)
  await h.fireNext()
  assert.equal(h.s.livePreviewFlushInFlight, true)
  const latest = { root: node('root', '根', [node('new', '新目标')]) }
  h.queueLiveDraftPreview(latest, 2)
  start.resolve()
  await tick()
  assert.equal(h.s.livePreviewPendingFrame.document, latest)
  assert.equal(h.s.livePreviewPendingFrame.operationCursor, 2)
  assert.equal(h.s.livePreviewPendingFrame.pendingCharacters, 3)
  await h.drain()
  assert.deepEqual(h.s.livePreviewRenderedDocument, latest)
  assert(h.updates().every(event => event.change.uid === 'new'))
})

test('旧字符帧等待ACK时新目标入队，旧帧完成不得覆盖最新pending目标', async () => {
  const ack = deferred()
  let requests = 0
  const h = harness({ update: () => ++requests === 1 ? ack.promise : undefined })
  h.queueLiveDraftPreview({ root: node('root', '根', [node('first', '甲乙旧版本')]) }, 1)
  const startedAt = h.s.livePreviewOldestPendingAt
  await h.fireNext()
  await h.fireNext()
  assert.equal(h.s.livePreviewFlushInFlight, true)
  const latest = { root: node('root', '根', [node('first', '甲乙新目标'), node('second', '随后')]) }
  h.advance(1000)
  h.queueLiveDraftPreview(latest, 2)
  assert.equal(h.s.livePreviewOldestPendingAt, startedAt)
  ack.resolve()
  await tick()
  assert.equal(h.s.livePreviewPendingFrame.document, latest)
  assert.equal(h.s.livePreviewPendingFrame.operationCursor, 2)
  assert.equal(h.s.livePreviewRenderedDocument.root.children[0].data.text, '甲')
  await h.drain()
  assert.deepEqual(h.s.livePreviewRenderedDocument, latest)
  assert.deepEqual(h.updates().map(event => [event.operationCursor, event.change.text]), [
    [1, '甲'], [2, '甲乙'], [2, '甲乙新'], [2, '甲乙新目'], [2, '甲乙新目标'], [2, '随'], [2, '随后'],
  ])
  assert.equal(h.s.livePreviewOldestPendingAt, null)
})

test('旧目标最后一字ACK与同游标新目标交错，不能误报播放已追平', async () => {
  const ack = deferred()
  let requests = 0
  const h = harness({ update: () => ++requests === 1 ? ack.promise : undefined })
  h.queueLiveDraftPreview({ root: node('root', '根', [node('first', '甲')]) }, 7)
  await h.fireNext()
  await h.fireNext()
  assert.equal(h.s.livePreviewFlushInFlight, true)
  const target = { root: node('root', '根', [node('first', '甲乙')]) }
  h.queueLiveDraftPreview(target, 7)
  ack.resolve()
  await tick()
  assert.equal(h.s.livePreviewPendingFrame.document, target)
  assert.equal(h.s.livePreviewFramesPending.value, true, 'new target remains pending even though the old target finished')
  assert.equal(h.s.livePreviewRenderedVersion.value, 7)
  assert.notEqual(h.s.livePreviewOldestPendingAt, null)
  await h.drain()
  assert.equal(h.s.livePreviewFramesPending.value, false)
  assert.equal(h.s.livePreviewOldestPendingAt, null)
  assert.deepEqual(h.s.livePreviewRenderedDocument, target)
})

test('恢复先固定云端基线再建立最新游标，旧SSE不能删除已显示节点且新增部分仍逐字播放', async () => {
  const cloud = { root: node('root', '根', [node('a', '甲'), node('b', '乙'), node('c', '丙')]) }
  const target = { root: node('root', '根', [...cloud.root.children, node('d', '丁丁')]) }
  const h = harness({ baseline: cloud })
  const preview = { available: true, operationCursor: 9, previewEpoch: 2, document: target }
  const noop = () => {}
  Object.assign(h.s, {
    componentAlive: true, restoreGeneration: 1, directCanvasOwnerId: ref(''), directCanvasRecoveryJobId: ref(''),
    restoreError: ref(''), latestPreviewVersion: ref(-1), latestPreviewEpoch: ref(1),
    messageModeActive: ref(false), selectedTurnJobId: ref('job1'), draftDocument: ref(null),
    draftFreshness: ref(''), draftFreshnessMessage: ref(''), compareMindmapAiPreviewCoordinates,
    stopPolling: noop, stopRealtime: noop, persistActiveJob: () => true, schedulePoll: noop,
    syncCurrentJobCursor: noop, hasUnresolvedGenerationRestart: () => false, livePreviewPreparing: ref(false),
    refreshDraftPreview: async () => false, isMindmapAiMessageJob: () => false,
    getMindmapAiJobDraft: async () => {
      assert.equal(h.events[0].phase, 'start', 'the cloud baseline is fenced before reading a newer checkpoint')
      return { data: preview }
    },
    connectRealtime: () => {
      assert.equal(h.acceptDraftPreview({ ...preview, operationCursor: 1,
        document: { root: node('root', '根', [node('a', '甲')]) } }), false)
    },
  })
  assert.equal(await h.resumeRestoredDirectJob('job1'), true)
  assert.equal(h.s.latestPreviewVersion.value, 9)
  await h.drain()
  assert.deepEqual(h.updates().map(frame => [frame.change.kind, frame.change.uid, frame.change.text]), [
    ['add', 'd', '丁'], ['update', 'd', '丁丁'],
  ])
  assert(h.updates().every(frame => frame.document.root.children.slice(0, 3)
    .map(item => item.data.uid).join(',') === 'a,b,c'))
  assert.deepEqual(h.s.livePreviewRenderedDocument, target)
})
