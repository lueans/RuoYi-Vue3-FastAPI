import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyMindmapAiDraftDelta,
  buildMindmapAiTimelineEnvelopeKey,
  consumeMindmapAiRealtimeEvents,
  describeMindmapAiAgentProgress,
  fingerprintMindmapAiRequest,
  mergeMindmapAiJobEventSnapshot,
  mergeMindmapAiJobSnapshot,
  mindmapAiTerminalErrorUpdate,
  MINDMAP_AI_MAX_SSE_EVENT_CHARS,
  parseMindmapAiSseChunk,
  resolveMindmapAiRequestAttempt,
  sanitizeMindmapAiAgentProgressPayload,
  streamMindmapAiJobEvents,
} from '../mindmap-ai-stream.js'

test('tool failures stay in the timeline and only terminal status events update the job error', () => {
  assert.deepEqual(mindmapAiTerminalErrorUpdate('tool_failed', {
    status: 'running',
    errorCode: 'AI_OUTPUT_INVALID',
    errorMessage: '工具参数无效',
  }), {})
  assert.deepEqual(mindmapAiTerminalErrorUpdate('agent_error', {
    errorCode: 'AI_AGENT_UNAVAILABLE',
    errorMessage: '供应商暂不可用',
  }), {})
  assert.deepEqual(mindmapAiTerminalErrorUpdate('status_changed', {
    status: 'failed',
    errorCode: 'AI_BUDGET_EXCEEDED',
    errorMessage: '累计新增节点 102/100',
  }), {
    errorCode: 'AI_BUDGET_EXCEEDED',
    errorMessage: '累计新增节点 102/100',
  })
})

test('timeline and live SSE events advance the same monotonic job snapshot', () => {
  const queued = {
    id: 'job-replayed-timeline',
    status: 'queued',
    progress: 0,
    updateTime: '2026-09-15T09:00:00.000Z',
  }
  const preparing = mergeMindmapAiJobEventSnapshot(queued, {
    eventType: 'status_changed',
    data: {
      createdTime: '2026-09-15T09:00:01.000Z',
      payload: { status: 'preparing', progress: 10 },
    },
  })
  const running = mergeMindmapAiJobEventSnapshot(preparing, {
    eventType: 'status_changed',
    payload: { status: 'running', progress: 25 },
    createdTime: '2026-09-15T09:00:02.000Z',
  })
  const staleQueueReplay = mergeMindmapAiJobEventSnapshot(running, {
    eventType: 'status_changed',
    payload: { status: 'queued', progress: 0 },
    createdTime: '2026-09-15T09:00:01.500Z',
  })
  const ready = mergeMindmapAiJobEventSnapshot(staleQueueReplay, {
    eventType: 'artifact_ready',
    payload: {
      status: 'ready',
      progress: 100,
      artifactId: 'artifact-replayed',
      proposalId: 'proposal-replayed',
    },
    createdTime: '2026-09-15T09:00:03.000Z',
  })

  assert.equal(preparing.status, 'preparing')
  assert.equal(preparing.progress, 10)
  assert.equal(running.status, 'running')
  assert.equal(running.progress, 25)
  assert.equal(staleQueueReplay.status, 'running')
  assert.equal(staleQueueReplay.progress, 25)
  assert.equal(ready.status, 'ready')
  assert.equal(ready.progress, 100)
  assert.equal(ready.artifactId, 'artifact-replayed')
  assert.equal(ready.proposalId, 'proposal-replayed')
})

test('timeline coalesces only repeated generic SDK message envelopes', () => {
  assert.equal(
    buildMindmapAiTimelineEnvelopeKey('job-1', 'agent_event', {
      stage: 'building',
      messageType: 'SystemMessage',
    }),
    'job-1:agent_event:building:SystemMessage',
  )
  assert.notEqual(
    buildMindmapAiTimelineEnvelopeKey('job-1', 'agent_event', {
      stage: 'building',
      messageType: 'AssistantMessage',
    }),
    buildMindmapAiTimelineEnvelopeKey('job-1', 'agent_event', {
      stage: 'building',
      messageType: 'UserMessage',
    }),
  )
  assert.equal(
    buildMindmapAiTimelineEnvelopeKey('job-1', 'tool_completed', {
      stage: 'building',
      messageType: 'SystemMessage',
    }),
    null,
    'tool and draft events must never be coalesced by the envelope filter',
  )
  assert.equal(
    buildMindmapAiTimelineEnvelopeKey('job-1', 'agent_event', { stage: 'building' }),
    null,
    'future generic audit events without a message type must remain visible',
  )
})

test('SSE parser preserves partial chunks and decodes named events', () => {
  const first = parseMindmapAiSseChunk('', 'id: 1\nevent: draft_changed\ndata: {"sequence":1')
  assert.equal(first.events.length, 0)

  const second = parseMindmapAiSseChunk(first.remainder, ',"payload":{"operations":[]}}\n\n')
  assert.equal(second.remainder, '')
  assert.deepEqual(second.events, [{
    id: '1',
    eventType: 'draft_changed',
    data: { sequence: 1, payload: { operations: [] } },
  }])
})

test('SSE parser flushes an unterminated tail exactly once', () => {
  const parsed = parseMindmapAiSseChunk(
    '',
    'id: 9\nevent: status_changed\ndata: {"sequence":9,"payload":{"progress":100}}',
    { flush: true },
  )
  assert.equal(parsed.remainder, '')
  assert.deepEqual(parsed.events.map(event => event.data.sequence), [9])
})

test('SSE parser supports CR-only frames and CRLF split across chunks', () => {
  const crOnly = parseMindmapAiSseChunk(
    '',
    'id: 2\revent: tool_started\rdata: {"sequence":2,"payload":{}}\r\r',
  )
  assert.equal(crOnly.events[0].data.sequence, 2)

  const first = parseMindmapAiSseChunk(
    '',
    'id: 3\r\nevent: tool_completed\r\ndata: {"sequence":3,"payload":{}}\r',
  )
  assert.equal(first.events.length, 0)
  const second = parseMindmapAiSseChunk(first.remainder, '\n\r\n')
  assert.deepEqual(second.events.map(event => event.data.sequence), [3])
})

test('SSE parser reports malformed JSON once and rejects oversized frames', () => {
  const malformed = parseMindmapAiSseChunk(
    '',
    'id: 4\nevent: draft_changed\ndata: {not-json}',
    { flush: true },
  )
  assert.deepEqual(malformed.events, [{
    id: '4',
    eventType: 'stream_error',
    data: { code: 'AI_EVENT_INVALID', sequence: 4 },
  }])

  assert.throws(
    () => parseMindmapAiSseChunk('', `data: ${'x'.repeat(MINDMAP_AI_MAX_SSE_EVENT_CHARS)}`),
    error => error?.code === 'AI_EVENT_TOO_LARGE',
  )
})

test('draft delta replays create, update, move, delete and metadata operations', () => {
  const started = applyMindmapAiDraftDelta(null, {
    initialState: {
      root: { data: { uid: 'root', text: '旧标题' }, children: [] },
      layout: 'logicalStructure',
      theme: { template: 'default', config: {} },
      view: null,
      documentData: {},
    },
    operations: [],
  })
  const created = applyMindmapAiDraftDelta(started, {
    operations: [
      {
        type: 'create_node',
        nodeUid: 'a',
        payload: { parentUid: 'root', index: 0, data: { uid: 'a', text: 'A' } },
      },
      {
        type: 'create_node',
        nodeUid: 'b',
        payload: { parentUid: 'root', index: 1, data: { uid: 'b', text: 'B' } },
      },
      {
        type: 'update_node',
        nodeUid: 'a',
        payload: { patch: { text: 'A+' } },
      },
      {
        type: 'move_node',
        nodeUid: 'b',
        payload: { parentUid: 'a', index: 0 },
      },
      {
        type: 'set_document_meta',
        payload: { title: '新标题', layout: 'mindMap' },
      },
    ],
  })
  assert.equal(created.root.data.text, '新标题')
  assert.equal(created.layout, 'mindMap')
  assert.equal(created.root.children[0].data.text, 'A+')
  assert.equal(created.root.children[0].children[0].data.text, 'B')

  const removed = applyMindmapAiDraftDelta(created, {
    operations: [{ type: 'delete_subtree', nodeUid: 'b', payload: null }],
  })
  assert.equal(removed.root.children[0].children.length, 0)
  assert.equal(created.root.children[0].children.length, 1, 'replay must not mutate prior snapshots')
})

test('realtime consumer deduplicates replayed events and fetches authoritative draft snapshots', async () => {
  const observedEvents = []
  const observedDrafts = []
  const fetchedVersions = []
  const streamImpl = async (_jobId, options) => {
    for (const event of [
      { id: '2', eventType: 'tool_started', data: { sequence: 2, payload: {} } },
      { id: '3', eventType: 'draft_changed', data: { sequence: 3, payload: {
        previewAvailable: true,
        previewVersion: 4,
      } } },
      { id: '3', eventType: 'draft_changed', data: { sequence: 3, payload: {
        previewAvailable: true,
        previewVersion: 4,
      } } },
      { id: '4', eventType: 'draft_changed', data: { sequence: 4, payload: {
        previewAvailable: true,
        previewVersion: 7,
      } } },
    ]) await options.onEvent(event)
  }
  const fetchDraft = async () => {
    const version = fetchedVersions.length === 0 ? 4 : 7
    fetchedVersions.push(version)
    return { data: {
      available: true,
      operationCursor: version,
      document: {
        root: { data: { uid: 'root', text: `版本 ${version}` }, children: [] },
      },
    } }
  }

  const cursor = await consumeMindmapAiRealtimeEvents('job-1', {
    afterSequence: 1,
    previewVersion: -1,
    streamImpl,
    fetchDraft,
    onEvent: event => observedEvents.push(event.data.sequence),
    onDraft: preview => observedDrafts.push(preview.operationCursor),
  })

  assert.deepEqual(observedEvents, [2, 3, 4])
  assert.deepEqual(fetchedVersions, [4, 7])
  assert.deepEqual(observedDrafts, [4, 7])
  assert.deepEqual(cursor, { afterSequence: 4, previewVersion: 7 })
})

test('realtime consumer rejects stale or unavailable draft snapshots', async () => {
  const observedDrafts = []
  let call = 0
  await consumeMindmapAiRealtimeEvents('job-2', {
    previewVersion: 5,
    streamImpl: async (_jobId, options) => {
      await options.onEvent({
        id: '1',
        eventType: 'draft_changed',
        data: { sequence: 1, payload: { previewAvailable: true, previewVersion: 6 } },
      })
      await options.onEvent({
        id: '2',
        eventType: 'draft_changed',
        data: { sequence: 2, payload: { previewAvailable: true, previewVersion: 8 } },
      })
    },
    fetchDraft: async () => {
      call += 1
      return call === 1
        ? { data: { available: true, operationCursor: 5, document: { root: {} } } }
        : { data: { available: false, operationCursor: 8 } }
    },
    onDraft: preview => observedDrafts.push(preview),
  })
  assert.deepEqual(observedDrafts, [])
})

test('request attempt reuses a key only while the canonical payload is unchanged', () => {
  const generatedKeys = ['key-1', 'key-2']
  const createKey = () => generatedKeys.shift()
  const firstPayload = {
    prompt: '生成登录脑图',
    parameters: { maxNodes: 20, maxDepth: 6 },
  }
  const reorderedPayload = {
    parameters: { maxDepth: 6, maxNodes: 20 },
    prompt: '生成登录脑图',
  }
  const changedPayload = {
    ...reorderedPayload,
    prompt: '生成支付脑图',
  }

  const first = resolveMindmapAiRequestAttempt(null, firstPayload, { createKey })
  const retried = resolveMindmapAiRequestAttempt(first, reorderedPayload, { createKey })
  const changed = resolveMindmapAiRequestAttempt(retried, changedPayload, { createKey })

  assert.equal(first.key, 'key-1')
  assert.equal(retried, first, 'network retry must reuse the original attempt object and key')
  assert.equal(changed.key, 'key-2')
  assert.notEqual(changed.fingerprint, first.fingerprint)
  assert.equal(
    fingerprintMindmapAiRequest(firstPayload),
    fingerprintMindmapAiRequest(reorderedPayload),
  )
})

test('draft fetch failure is isolated and a later preview can still be accepted', async () => {
  const observedEvents = []
  const observedDrafts = []
  const draftErrors = []
  let fetchCount = 0

  const cursor = await consumeMindmapAiRealtimeEvents('job-retry', {
    streamImpl: async (_jobId, options) => {
      await options.onEvent({
        id: '1',
        eventType: 'draft_initialized',
        data: { sequence: 1, payload: { previewAvailable: true, previewVersion: 0 } },
      })
      await options.onEvent({
        id: '2',
        eventType: 'draft_changed',
        data: { sequence: 2, payload: { previewAvailable: true, previewVersion: 2 } },
      })
    },
    fetchDraft: async () => {
      fetchCount += 1
      if (fetchCount === 1) throw new Error('temporary preview failure')
      return { data: {
        available: true,
        operationCursor: 2,
        document: { root: { data: { uid: 'root', text: '恢复后的草稿' }, children: [] } },
      } }
    },
    onEvent: event => observedEvents.push(event.data.sequence),
    onDraft: preview => observedDrafts.push(preview.operationCursor),
    onDraftError: (error, context) => draftErrors.push([error.message, context.requestedVersion]),
  })

  assert.deepEqual(observedEvents, [1, 2])
  assert.deepEqual(draftErrors, [['temporary preview failure', 0]])
  assert.deepEqual(observedDrafts, [2])
  assert.deepEqual(cursor, { afterSequence: 2, previewVersion: 2 })
})

test('rapid draft events request their exact versions without jumping to latest', async () => {
  const requestedVersions = []
  const observedDrafts = []
  await consumeMindmapAiRealtimeEvents('job-versions', {
    streamImpl: async (_jobId, options) => {
      for (const version of [1, 2]) {
        await options.onEvent({
          id: String(version),
          eventType: 'draft_changed',
          data: {
            sequence: version,
            payload: { previewAvailable: true, previewVersion: version },
          },
        })
      }
    },
    fetchDraft: async (_jobId, options) => {
      requestedVersions.push(options.version)
      if (options.version === 1) {
        return { data: { available: false, requestedVersion: 1 } }
      }
      return { data: {
        available: true,
        operationCursor: options.version,
        document: {
          root: { data: { uid: 'root', text: `版本 ${options.version}` }, children: [] },
        },
      } }
    },
    onDraft: preview => observedDrafts.push(preview.operationCursor),
  })

  assert.deepEqual(requestedVersions, [1, 2])
  assert.deepEqual(observedDrafts, [2])
})

test('Codex progress payload keeps only approved stage, progress and total tokens', () => {
  const sanitized = sanitizeMindmapAiAgentProgressPayload({
    agentKey: 'codex',
    stage: 'usage_updated',
    progress: 65,
    usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15, reasoningTokens: 99 },
    text: '不得进入会话栏的模型原文',
    message: '不得展示',
  })

  assert.deepEqual(sanitized, {
    stage: 'usage_updated',
    progress: 65,
    usage: { totalTokens: 15 },
  })
  assert.equal(describeMindmapAiAgentProgress(sanitized), '用量更新 · 65% · Token 合计 15')
  assert.equal(JSON.stringify(sanitized).includes('不得'), false)
  assert.equal(describeMindmapAiAgentProgress({ stage: 'sdk_ready', progress: 10 }), 'SDK 就绪 · 10%')
  assert.equal(describeMindmapAiAgentProgress({ stage: 'turn_started', progress: 20 }), '请求开始 · 20%')
  assert.equal(describeMindmapAiAgentProgress({ stage: 'model_processing', progress: 35 }), '模型处理中 · 35%')
  assert.equal(
    describeMindmapAiAgentProgress({ stage: 'structured_output_received', progress: 85 }),
    '结构化结果 · 85%',
  )
  assert.equal(describeMindmapAiAgentProgress({ stage: 'turn_completed', progress: 90 }), '本轮完成 · 90%')
})

test('SSE progress cannot be regressed by an older polling snapshot', () => {
  const started = { id: 'job-progress', status: 'running', progress: 25 }
  const streamed = mergeMindmapAiJobSnapshot(started, { progress: 65 })
  const stalePoll = mergeMindmapAiJobSnapshot(streamed, {
    id: 'job-progress', status: 'running', progress: 25, title: '任务',
  })
  const cancelled = mergeMindmapAiJobSnapshot(stalePoll, {
    id: 'job-progress', status: 'cancelled', progress: 100,
  })

  assert.equal(streamed.progress, 65)
  assert.equal(stalePoll.progress, 65)
  assert.equal(stalePoll.title, '任务')
  assert.equal(cancelled.status, 'cancelled')
  assert.equal(cancelled.progress, 100)
})

test('stale polling cannot revive a terminal or cancel-requested job', () => {
  const ready = {
    id: 'job-terminal',
    status: 'ready',
    progress: 100,
    artifactId: 'artifact-1',
    proposalId: 'proposal-1',
  }
  const staleRunning = mergeMindmapAiJobSnapshot(ready, {
    id: 'job-terminal',
    status: 'running',
    progress: 70,
    artifactId: null,
    proposalId: null,
  })
  assert.deepEqual(staleRunning, ready)

  const cancellation = mergeMindmapAiJobSnapshot(
    { id: 'job-cancel', status: 'cancel_requested', progress: 65 },
    { id: 'job-cancel', status: 'running', progress: 60 },
  )
  assert.equal(cancellation.status, 'cancel_requested')
  assert.equal(cancellation.progress, 65)

  const cancelled = mergeMindmapAiJobSnapshot(cancellation, {
    id: 'job-cancel', status: 'cancelled', progress: 100,
  })
  assert.equal(cancelled.status, 'cancelled')
})

test('older terminal snapshots cannot roll back apply and undo side effects', () => {
  const applied = {
    id: 'job-apply',
    status: 'applied',
    progress: 100,
    artifactId: 'artifact-1',
    proposalId: 'proposal-1',
  }
  assert.deepEqual(mergeMindmapAiJobSnapshot(applied, {
    id: 'job-apply',
    status: 'ready',
    progress: 100,
    artifactId: 'artifact-1',
    proposalId: 'proposal-1',
  }), applied)

  const undone = { ...applied, status: 'undone' }
  assert.deepEqual(mergeMindmapAiJobSnapshot(undone, {
    ...applied,
    status: 'applied',
  }), undone)
})

test('job snapshots still accept valid forward terminal transitions', () => {
  const ready = { id: 'job-forward', status: 'ready', progress: 100 }
  const applied = mergeMindmapAiJobSnapshot(ready, {
    id: 'job-forward', status: 'applied', progress: 100,
  })
  const undone = mergeMindmapAiJobSnapshot(applied, {
    id: 'job-forward', status: 'undone', progress: 100,
  })
  assert.equal(applied.status, 'applied')
  assert.equal(undone.status, 'undone')
})

test('authoritative snapshots accept coalesced ready or review to undone transitions', () => {
  for (const status of ['ready', 'needs_review']) {
    const merged = mergeMindmapAiJobSnapshot(
      { id: `job-${status}`, status, progress: 100 },
      { id: `job-${status}`, status: 'undone', progress: 100 },
    )
    assert.equal(merged.status, 'undone')
  }
})

test('replayed active events cannot rewind status while a newer worker recovery can', () => {
  const validating = {
    id: 'job-recovery', status: 'validating', progress: 80,
    updateTime: '2026-09-13T10:00:10.000Z',
  }
  const replayed = mergeMindmapAiJobSnapshot(validating, {
    id: 'job-recovery', status: 'queued', progress: 0,
    updateTime: '2026-09-13T10:00:01.000Z',
  })
  assert.equal(replayed.status, 'validating')
  assert.equal(replayed.progress, 80)
  assert.equal(replayed.updateTime, validating.updateTime)

  const secondReplay = mergeMindmapAiJobSnapshot(replayed, {
    id: 'job-recovery', status: 'running', progress: 20,
    updateTime: '2026-09-13T10:00:05.000Z',
  })
  assert.equal(secondReplay.status, 'validating')
  assert.equal(secondReplay.progress, 80)
  assert.equal(secondReplay.updateTime, validating.updateTime)

  const recovered = mergeMindmapAiJobSnapshot(validating, {
    id: 'job-recovery', status: 'queued', progress: 0,
    updateTime: '2026-09-13T10:00:20.000Z',
  })
  assert.equal(recovered.status, 'queued')
  assert.equal(recovered.progress, 0)
})

test('SSE request resumes with Last-Event-ID and reports connection readiness', async () => {
  const chunks = [
    new TextEncoder().encode('id: 8\nevent: tool_completed\ndata: {"sequence":8,"payload":{}}\n\n'),
  ]
  let request
  let opened = 0
  let released = 0
  const events = []
  const reader = {
    async read() {
      return chunks.length
        ? { done: false, value: chunks.shift() }
        : { done: true, value: undefined }
    },
    releaseLock() { released += 1 },
  }

  await streamMindmapAiJobEvents('job/with spaces', {
    afterSequence: 7,
    baseUrl: '/dev-api/',
    token: 'token-value',
    fetchImpl: async (url, options) => {
      request = { url, options }
      return {
        ok: true,
        status: 200,
        headers: { get: name => name === 'content-type' ? 'text/event-stream; charset=utf-8' : '' },
        body: { getReader: () => reader },
      }
    },
    onOpen: () => { opened += 1 },
    onEvent: event => events.push(event),
  })

  assert.equal(request.url, '/dev-api/mindmap/ai/jobs/job%2Fwith%20spaces/events')
  assert.equal(request.options.headers['Last-Event-ID'], '7')
  assert.equal(request.options.headers.Authorization, 'Bearer token-value')
  assert.equal(request.options.cache, 'no-store')
  assert.equal(opened, 1)
  assert.equal(released, 1)
  assert.deepEqual(events.map(event => event.data.sequence), [8])
})

test('an interrupted SSE releases and cancels its reader for reconnect cleanup', async () => {
  let cancelled = 0
  let released = 0
  const interrupted = Object.assign(new Error('stream interrupted'), { name: 'AbortError' })
  const reader = {
    async read() { throw interrupted },
    async cancel() { cancelled += 1 },
    releaseLock() { released += 1 },
  }

  await assert.rejects(
    streamMindmapAiJobEvents('job-aborted', {
      token: '',
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        headers: { get: () => 'text/event-stream' },
        body: { getReader: () => reader },
      }),
    }),
    error => error === interrupted,
  )

  assert.equal(cancelled, 1)
  assert.equal(released, 1)
})

test('SSE request rejects a successful non-event-stream response', async () => {
  await assert.rejects(
    streamMindmapAiJobEvents('job-1', {
      token: '',
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
      }),
    }),
    /无效响应/,
  )
})
