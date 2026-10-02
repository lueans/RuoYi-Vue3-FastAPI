import test from 'node:test'
import assert from 'node:assert/strict'
import { getEventListeners } from 'node:events'
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { consumeMindmapAiRealtimeEvents, streamMindmapAiJobEvents } from '../mindmap-ai-stream.js'

const tick = () => new Promise(resolve => setImmediate(resolve))
const encode = text => new TextEncoder().encode(text)
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const response = reader => ({ ok: true, headers: { get: () => 'text/event-stream' }, body: { getReader: () => reader } })
const frame = (sequence, eventType, payload) => `id: ${sequence}\nevent: ${eventType}\ndata: ${JSON.stringify({ sequence, eventType, payload })}\n\n`

test('a stalled SSE handshake times out without cancelling the underlying job or caller', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const caller = new AbortController()
  const pending = deferred()
  let request, opened = 0
  const stream = streamMindmapAiJobEvents('existing-job', {
    token: '', signal: caller.signal, onOpen: () => opened++,
    fetchImpl: (_url, options) => { request = options; return pending.promise },
  })
  const rejected = assert.rejects(stream, error => error.code === 'AI_STREAM_TIMEOUT')
  await tick()
  t.mock.timers.tick(45_000)
  await rejected
  assert.equal(request.signal.aborted, true)
  assert.equal(caller.signal.aborted, false)
  assert.equal(opened, 0)
  assert.equal(getEventListeners(caller.signal, 'abort').length, 0)
  pending.reject(new Error('late network failure'))
  await tick()
})

test('a silent body times out even when reader cancellation never acknowledges', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const read = deferred(), cancellation = deferred()
  let cancelled = 0, released = 0, transportSignal
  const events = []
  const stream = streamMindmapAiJobEvents('existing-job', {
    token: '', onEvent: event => events.push(event),
    fetchImpl: async (_url, options) => {
      transportSignal = options.signal
      return response({ read: () => read.promise, cancel: () => { cancelled++; return cancellation.promise }, releaseLock: () => released++ })
    },
  })
  const rejected = assert.rejects(stream, error => error.code === 'AI_STREAM_TIMEOUT')
  await tick()
  t.mock.timers.tick(45_000)
  await rejected
  assert.equal(transportSignal.aborted, true)
  assert.equal(cancelled, 1)
  assert.equal(released, 1)
  read.resolve({ done: false, value: encode(frame(1, 'assistant_delta', { text: 'late' })) })
  cancellation.reject(new Error('late cleanup rejection'))
  await tick()
  assert.deepEqual(events, [])
})

test('15-second server heartbeats keep a quiet model stream alive beyond the idle deadline', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let pending = deferred(), finished = false, cancelled = 0
  const caller = new AbortController()
  const stream = streamMindmapAiJobEvents('quiet-job', {
    token: '', signal: caller.signal,
    fetchImpl: async () => response({ read: () => pending.promise, cancel: () => cancelled++, releaseLock() {} }),
  }).finally(() => { finished = true })
  await tick()
  for (let i = 0; i < 5; i++) {
    t.mock.timers.tick(15_000)
    const previous = pending
    pending = deferred()
    previous.resolve({ done: false, value: encode(': keepalive\n\n') })
    await tick()
    assert.equal(finished, false)
  }
  pending.resolve({ done: true })
  await stream
  t.mock.timers.tick(90_000)
  assert.equal(cancelled, 0)
  assert.equal(getEventListeners(caller.signal, 'abort').length, 0)
})

test('transport AbortError cannot hide the watchdog timeout from reconnect handling', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const pending = deferred()
  const stream = streamMindmapAiJobEvents('job', {
    token: '',
    fetchImpl: async (_url, { signal }) => {
      // Native body readers may reject with AbortError before the watchdog's
      // race listener runs. The timeout must still remain retryable.
      signal.addEventListener('abort', () => pending.reject(new DOMException('aborted', 'AbortError')), { once: true })
      return response({ read: () => pending.promise, cancel() {}, releaseLock() {} })
    },
  })
  const rejected = assert.rejects(stream, error => error.code === 'AI_STREAM_TIMEOUT')
  await tick()
  t.mock.timers.tick(45_000)
  await rejected
})

for (const phase of ['headers', 'body']) {
  test(`caller cancellation promptly releases a stalled ${phase} wait`, async t => {
    t.mock.timers.enable({ apis: ['setTimeout'] })
    const caller = new AbortController(), pending = deferred()
    const interrupted = new DOMException('caller stopped monitoring', 'AbortError')
    let transportSignal, cancelled = 0
    const stream = streamMindmapAiJobEvents('old-job', {
      token: '', signal: caller.signal,
      fetchImpl: async (_url, options) => {
        transportSignal = options.signal
        return phase === 'headers' ? pending.promise
          : response({ read: () => pending.promise, cancel: () => cancelled++, releaseLock() {} })
      },
    })
    const rejected = assert.rejects(stream, error => error === interrupted)
    await tick()
    caller.abort(interrupted)
    await rejected
    assert.equal(transportSignal.aborted, true)
    assert.equal(cancelled, phase === 'body' ? 1 : 0)
    assert.equal(getEventListeners(caller.signal, 'abort').length, 0)
    t.mock.timers.tick(90_000)
  })
}

test('already aborted monitoring never opens an SSE request', async () => {
  const caller = new AbortController()
  caller.abort()
  let requests = 0
  await assert.rejects(streamMindmapAiJobEvents('old-job', {
    token: '', signal: caller.signal, fetchImpl: () => { requests++; return new Promise(() => {}) },
  }), error => error.name === 'AbortError')
  assert.equal(requests, 0)
})

test('slow local event processing is not a transport timeout and its error is preserved', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const handler = deferred(), localFailure = new Error('local projection failed')
  let cancelled = 0
  const stream = streamMindmapAiJobEvents('job', {
    token: '', onEvent: () => handler.promise,
    fetchImpl: async () => response({
      read: async () => ({ done: false, value: encode(frame(1, 'assistant_delta', { text: 'hello' })) }),
      cancel: () => cancelled++, releaseLock() {},
    }),
  })
  const rejected = assert.rejects(stream, error => error === localFailure)
  await tick()
  t.mock.timers.tick(90_000)
  handler.reject(localFailure)
  await rejected
  assert.equal(cancelled, 1)
})

test('native HTTP disconnect resumes one existing job, deduplicates replay and preserves versioned preview', async t => {
  const requests = [], events = [], drafts = []
  let firstResponse, latestSequence = 0, latestVersion = -1
  const node = version => ({ root: { data: { uid: 'root', text: `version ${version}` }, children: [] } })
  const server = createServer((req, res) => {
    requests.push({ method: req.method, path: req.url, cursor: req.headers['last-event-id'] })
    if (req.url.startsWith('/draft/')) {
      const version = Number(req.url.split('/').at(-1))
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ available: true, operationCursor: version, previewEpoch: 1, document: node(version) }))
      return
    }
    res.writeHead(200, { 'content-type': 'text/event-stream' })
    if (!req.headers['last-event-id']) {
      firstResponse = res
      res.write(frame(1, 'assistant_delta', { messageId: 'm', text: '开始' }))
      res.write(frame(2, 'draft_changed', { previewAvailable: true, previewVersion: 1 }))
      res.write(frame(3, 'tool_started', { callId: 't', toolName: 'add_nodes' }))
    } else {
      res.write(frame(3, 'tool_started', { callId: 't', toolName: 'add_nodes' }))
      res.write(frame(4, 'tool_completed', { callId: 't', toolName: 'add_nodes' }))
      res.write(frame(5, 'draft_changed', { previewAvailable: true, previewVersion: 2 }))
      res.end(frame(6, 'status_changed', { status: 'completed_direct' }))
    }
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(() => { server.closeAllConnections(); server.close() })
  const baseUrl = `http://127.0.0.1:${server.address().port}`
  const consume = () => consumeMindmapAiRealtimeEvents('existing-job', {
    afterSequence: latestSequence, previewVersion: latestVersion,
    streamImpl: (id, options) => streamMindmapAiJobEvents(id, { ...options, token: '', baseUrl }),
    fetchDraft: async (_id, { version }) => (await fetch(`${baseUrl}/draft/${version}`)).json(),
    onEvent: event => {
      latestSequence = event.data.sequence
      events.push(latestSequence)
      if (latestSequence === 3 && requests.filter(request => request.path.endsWith('/events')).length === 1) firstResponse.destroy()
    },
    onDraft: preview => { latestVersion = preview.operationCursor; drafts.push(latestVersion) },
  })
  await assert.rejects(consume())
  assert.equal(latestSequence, 3)
  const cursor = await consume()
  assert.deepEqual(events, [1, 2, 3, 4, 5, 6])
  assert.deepEqual(drafts, [1, 2])
  assert.equal(cursor.afterSequence, 6)
  assert.equal(cursor.previewVersion, 2)
  assert.deepEqual(requests.filter(request => request.path.endsWith('/events')).map(request => request.cursor), [undefined, '3'])
  assert.ok(requests.every(request => request.method === 'GET'), 'recovery must never recreate or rerun the agent')
})

test('native fetch body silence is a retryable timeout and actually closes the old socket', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const received = deferred(), disconnected = deferred()
  const server = createServer((req, res) => {
    res.on('close', disconnected.resolve)
    res.writeHead(200, { 'content-type': 'text/event-stream' })
    res.write(frame(1, 'assistant_delta', { messageId: 'm', text: 'one frame then silent' }))
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(() => { server.closeAllConnections(); server.close() })
  const caller = new AbortController()
  const stream = streamMindmapAiJobEvents('existing-job', {
    token: '', signal: caller.signal, baseUrl: `http://127.0.0.1:${server.address().port}`,
    onEvent: received.resolve,
  })
  const rejected = assert.rejects(stream, error => error.code === 'AI_STREAM_TIMEOUT')
  assert.equal((await received.promise).data.sequence, 1)
  await tick()
  t.mock.timers.tick(45_000)
  await rejected
  await disconnected.promise
  assert.equal(caller.signal.aborted, false)
  assert.equal(getEventListeners(caller.signal, 'abort').length, 0)
})

const script = parse(readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')).descriptor.scriptSetup.content
const declarations = babelParse(script, { sourceType: 'module' }).program.body
function dialogHarness() {
  const streams = [], delays = [], events = []
  const ref = value => ({ value })
  const s = {
    authExpired: ref(false), componentAlive: true, navigator: { onLine: true }, job: ref({ id: 'job', status: 'running' }),
    realtimeReconnectTimer: null, realtimeReconnectAttempt: 0, realtimeGeneration: 0, realtimeController: null,
    realtimeConnectionState: ref('idle'), realtimeError: ref(''), latestEventSequence: ref(7),
    latestPreviewVersion: ref(1), latestPreviewEpoch: ref(1), jobEventSequences: new Map(),
    REALTIME_RECONNECT_BASE_MS: 600, REALTIME_RECONNECT_MAX_MS: 10_000,
    setTimeout: (fn, delay) => { delays.push(delay); return fn }, clearTimeout() {},
    Math: { min: Math.min, max: Math.max, round: Math.round, random: () => 0.5 },
    getMindmapAiJobDraft() {}, schedulePoll() {}, finalizeTerminalJob() {},
    isTerminalStatus: status => status === 'completed_direct', isAbortError: error => error.name === 'AbortError',
    compareMindmapAiPreviewCoordinates: () => 0, formatMindmapAiError: error => error.message,
    appendAgentEvent: (_id, event) => { events.push(event); s.latestEventSequence.value = Math.max(s.latestEventSequence.value, Number(event.data.sequence) || 0) },
    applyRealtimeJobEvent() {},
    consumeMindmapAiRealtimeEvents: (id, options) => {
      const completion = deferred()
      streams.push({ id, options, completion })
      return completion.promise
    },
  }
  const names = ['connectRealtime', 'scheduleRealtimeReconnect', 'stopRealtime']
  const functions = names.map(name => {
    const node = declarations.find(node => node.type === 'FunctionDeclaration' && node.id.name === name)
    return script.slice(node.start, node.end)
  })
  const api = new Function('scope', `with(scope) { ${functions.join('\n')} return { ${names.join(',')} } }`)(s)
  return { s, streams, delays, events, ...api }
}

test('production reconnect backoff survives successful headers and duplicate replay', async () => {
  const h = dialogHarness()
  for (let i = 0; i < 4; i++) {
    h.connectRealtime('job')
    const stream = h.streams.at(-1)
    stream.options.onOpen()
    stream.options.onEvent({ id: '7', eventType: 'assistant_delta', data: { sequence: 7, payload: { text: 'replay' } } })
    stream.completion.resolve({ afterSequence: 7, previewVersion: 1, previewEpoch: 1 })
    await tick()
  }
  assert.deepEqual(h.delays, [600, 1200, 2400, 4800])
  assert.ok(h.streams.every(stream => stream.options.afterSequence === 7 && stream.id === 'job'))
  h.connectRealtime('job')
  h.streams.at(-1).options.onEvent({ id: '8', eventType: 'assistant_delta', data: { sequence: 8, payload: { text: 'new' } } })
  assert.equal(h.s.realtimeReconnectAttempt, 0)
  h.streams.at(-1).completion.reject(new Error('disconnected'))
  await tick()
  assert.equal(h.delays.at(-1), 600)
})

test('old stream callbacks and stopping monitoring cannot restart or reset a successor connection', async () => {
  const h = dialogHarness()
  h.connectRealtime('job')
  const old = h.streams[0]
  h.connectRealtime('job')
  h.s.realtimeReconnectAttempt = 4
  old.options.onOpen()
  old.options.onEvent({ eventType: 'assistant_delta', data: { sequence: 99 } })
  old.completion.reject(new Error('old failure'))
  await tick()
  assert.equal(h.s.realtimeReconnectAttempt, 4)
  assert.deepEqual(h.events, [])
  assert.deepEqual(h.delays, [])
  h.stopRealtime('idle')
  h.streams[1].completion.reject(new DOMException('stopped', 'AbortError'))
  await tick()
  assert.equal(h.s.realtimeConnectionState.value, 'idle')
  assert.deepEqual(h.delays, [])
})
