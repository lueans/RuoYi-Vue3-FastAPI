import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MindmapWsClient,
  parseMindmapWsMessage,
  resolveMindmapWsUrl,
} from '../ws-client.js'

function createScheduler() {
  let nextId = 1
  const tasks = new Map()
  return {
    setTimeout(fn, delay) {
      const id = nextId++
      tasks.set(id, { fn, delay })
      return id
    },
    clearTimeout(id) {
      tasks.delete(id)
    },
    delays() {
      return [...tasks.values()].map(task => task.delay).sort((a, b) => a - b)
    },
    runDelay(delay) {
      const entry = [...tasks.entries()].find(([, task]) => task.delay === delay)
      assert.ok(entry, `expected timer with delay ${delay}`)
      tasks.delete(entry[0])
      entry[1].fn()
    },
  }
}

function createEventTarget(location = { protocol: 'https:', host: 'app.example.test' }) {
  const listeners = new Map()
  return {
    location,
    addEventListener(type, handler) {
      listeners.set(type, handler)
    },
    removeEventListener(type, handler) {
      if (listeners.get(type) === handler) listeners.delete(type)
    },
    emit(type) {
      listeners.get(type)?.()
    },
    has(type) {
      return listeners.has(type)
    },
  }
}

class FakeWebSocket {
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = 0
    this.sent = []
    FakeWebSocket.instances.push(this)
  }

  open() {
    this.readyState = 1
    this.onopen?.()
  }

  message(data) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  rawMessage(data) {
    this.onmessage?.({ data })
  }

  failSend() {
    this.sendError = new Error('socket send failed')
  }

  send(data) {
    if (this.sendError) throw this.sendError
    if (this.readyState !== 1) throw new Error('socket is not open')
    this.sent.push(JSON.parse(data))
  }

  close() {
    this.readyState = 3
    this.onclose?.()
  }
}

function createClient(handlers = {}, options = {}) {
  const scheduler = createScheduler()
  const eventTarget = createEventTarget()
  const client = new MindmapWsClient(42, handlers, {
    WebSocketImpl: FakeWebSocket,
    eventTarget,
    location: eventTarget.location,
    baseApi: '/api/',
    connectTimeoutMs: 50,
    authTimeoutMs: 60,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
    ...options,
  })
  return { client, eventTarget, scheduler }
}

test('默认浏览器定时器固定 window 调用上下文', () => {
  FakeWebSocket.instances.length = 0
  const originalSetTimeout = globalThis.setTimeout
  const originalClearTimeout = globalThis.clearTimeout
  const scheduled = new Map()
  let nextId = 1
  globalThis.setTimeout = function setBrowserTimeout(fn, delay) {
    assert.equal(this, globalThis)
    const id = nextId++
    scheduled.set(id, { fn, delay })
    return id
  }
  globalThis.clearTimeout = function clearBrowserTimeout(id) {
    assert.equal(this, globalThis)
    scheduled.delete(id)
  }

  try {
    const eventTarget = createEventTarget()
    const client = new MindmapWsClient(122, {}, {
      WebSocketImpl: FakeWebSocket,
      eventTarget,
      location: eventTarget.location,
      baseApi: '/api/',
    })
    assert.doesNotThrow(() => client.connect())
    assert.equal(FakeWebSocket.instances.length, 1)
    assert.deepEqual([...scheduled.values()].map(task => task.delay), [10000])
    assert.doesNotThrow(() => client.disconnect())
    assert.equal(scheduled.size, 0)
  } finally {
    globalThis.setTimeout = originalSetTimeout
    globalThis.clearTimeout = originalClearTimeout
  }
})

test('协作 WebSocket 地址兼容代理路径、独立域名并编码资源身份', () => {
  assert.equal(
    resolveMindmapWsUrl(
      { protocol: 'http:', host: 'localhost:80' },
      '/dev-api/',
      '7/8',
    ),
    'ws://localhost/dev-api/ws/mindmap/7%2F8',
  )
  assert.equal(
    resolveMindmapWsUrl(
      { protocol: 'https:', host: 'app.example.test' },
      'https://api.example.test/v1',
      9,
    ),
    'wss://api.example.test/v1/ws/mindmap/9',
  )
})

test('服务端消息解析限制 UTF-8 体积并只接受具名 JSON 对象', () => {
  assert.deepEqual(parseMindmapWsMessage('{"type":"ping"}', 32), { type: 'ping' })
  assert.throws(() => parseMindmapWsMessage('null', 32), /Invalid/)
  assert.throws(() => parseMindmapWsMessage('[]', 32), /Invalid/)
  assert.throws(() => parseMindmapWsMessage('{"value":1}', 32), /Invalid/)
  assert.throws(
    () => parseMindmapWsMessage('{"type":"消息"}', 16),
    /exceeds/,
  )
})

test('认证前畸形、越界或越序消息会安全退休并有界重连', () => {
  for (const rawMessage of [
    'not-json',
    'null',
    '{"type":"seed_pending"}',
    '{"type":"ping"}',
    JSON.stringify({ type: 'auth_ok', padding: 'x'.repeat(80) }),
  ]) {
    FakeWebSocket.instances.length = 0
    const errors = []
    const { client, scheduler } = createClient(
      { onError: error => errors.push(error.message) },
      { maxServerMessageBytes: 64 },
    )
    client.connect()
    const socket = FakeWebSocket.instances.at(-1)
    socket.open()
    socket.rawMessage(rawMessage)

    assert.equal(client.ws, null)
    assert.equal(socket.readyState, 3)
    assert.equal(client.connectionState, 'reconnecting')
    assert.equal(errors.length, 1)
    assert.deepEqual(scheduler.delays(), [1000])
    client.disconnect()
  }
})

test('认证后未知对象向前兼容，重复认证或处理器异常会重新安全握手', () => {
  FakeWebSocket.instances.length = 0
  const errors = []
  const { client, scheduler } = createClient({
    update: () => { throw new Error('sensitive handler detail') },
    onError: error => errors.push(error.message),
  })
  client.connect()
  const socket = FakeWebSocket.instances.at(-1)
  socket.open()
  socket.message({ type: 'auth_ok', user: { id: 1 }, capabilities: [] })
  socket.message({ type: 'future_protocol_event', value: 1 })
  assert.equal(client.ws, socket)
  assert.deepEqual(scheduler.delays(), [])

  socket.message({ type: 'update', update: 'ignored' })
  assert.equal(client.ws, null)
  assert.equal(socket.readyState, 3)
  assert.equal(client.connectionState, 'reconnecting')
  assert.deepEqual(errors, ['协作消息处理失败'])
  assert.deepEqual(scheduler.delays(), [1000])
  client.disconnect()

  const duplicate = createClient()
  duplicate.client.connect()
  const duplicateSocket = FakeWebSocket.instances.at(-1)
  duplicateSocket.open()
  duplicateSocket.message({ type: 'auth_ok', user: { id: 1 }, capabilities: [] })
  duplicateSocket.message({ type: 'auth_ok', user: { id: 1 }, capabilities: [] })
  assert.equal(duplicate.client.ws, null)
  assert.equal(duplicate.client.connectionState, 'reconnecting')
  assert.deepEqual(duplicate.scheduler.delays(), [1000])
  duplicate.client.disconnect()
})

test('建连和认证阶段超时会退休当前连接并进入有界重连', () => {
  FakeWebSocket.instances.length = 0
  const errors = []
  const states = []
  const { client, scheduler } = createClient({
    onError: error => errors.push(error.message),
    onConnectionState: (state, detail) => states.push({ state, detail }),
  })

  client.connect()
  const connectingSocket = FakeWebSocket.instances.at(-1)
  assert.deepEqual(scheduler.delays(), [50])
  scheduler.runDelay(50)
  assert.equal(connectingSocket.readyState, 3)
  assert.equal(client.ws, null)
  assert.equal(client.connectionState, 'reconnecting')
  assert.deepEqual(errors, ['协作连接超时'])
  assert.deepEqual(scheduler.delays(), [1000])

  scheduler.runDelay(1000)
  const authenticatingSocket = FakeWebSocket.instances.at(-1)
  authenticatingSocket.open()
  assert.equal(client.connectionState, 'authenticating')
  assert.deepEqual(scheduler.delays(), [60])
  scheduler.runDelay(60)
  assert.equal(authenticatingSocket.readyState, 3)
  assert.equal(client.connectionState, 'reconnecting')
  assert.deepEqual(errors, ['协作连接超时', '协作认证超时'])
  assert.equal(states.some(item => item.detail === '协作认证超时'), true)
  client.disconnect()
})

test('认证成功清除看门狗，旧连接迟到回调不能污染已关闭会话', () => {
  FakeWebSocket.instances.length = 0
  let authenticated = 0
  let closed = 0
  const { client, eventTarget, scheduler } = createClient({
    onAuthenticated: () => { authenticated += 1 },
    onClose: () => { closed += 1 },
  })

  client.connect()
  const socket = FakeWebSocket.instances.at(-1)
  socket.open()
  const staleMessage = socket.onmessage
  socket.message({ type: 'auth_ok', user: { id: 1 }, capabilities: [] })

  assert.equal(client.connectionState, 'connected')
  assert.equal(client.isAuthenticated, true)
  assert.deepEqual(scheduler.delays(), [])
  assert.equal(eventTarget.has('online'), true)
  assert.equal(authenticated, 1)

  client.disconnect()
  staleMessage({ data: JSON.stringify({ type: 'auth_ok', user: { id: 2 } }) })
  assert.equal(client.connectionState, 'closed')
  assert.equal(client.isAuthenticated, false)
  assert.equal(authenticated, 1)
  assert.equal(closed, 1)
  assert.equal(eventTarget.has('online'), false)
  assert.deepEqual(scheduler.delays(), [])
})

test('发送异常只退休一次并保留自动重连能力', () => {
  FakeWebSocket.instances.length = 0
  let closed = 0
  const errors = []
  const { client, scheduler } = createClient({
    onClose: () => { closed += 1 },
    onError: error => errors.push(error.message),
  })
  client.connect()
  const socket = FakeWebSocket.instances.at(-1)
  socket.open()
  socket.message({ type: 'auth_ok', user: { id: 1 }, capabilities: [] })
  socket.failSend()

  assert.equal(client.send({ type: 'awareness', nodeUids: ['root'] }), false)
  assert.equal(client.ws, null)
  assert.equal(closed, 1)
  assert.deepEqual(errors, ['socket send failed'])
  assert.deepEqual(scheduler.delays(), [1000])
  socket.onclose?.()
  assert.equal(closed, 1)
  client.disconnect()
})

test('本地消息序列化失败不会错误退休健康连接', () => {
  FakeWebSocket.instances.length = 0
  const errors = []
  let closed = 0
  const { client, scheduler } = createClient({
    onError: error => errors.push(error.message),
    onClose: () => { closed += 1 },
  })
  client.connect()
  const socket = FakeWebSocket.instances.at(-1)
  socket.open()
  socket.message({ type: 'auth_ok', user: { id: 1 }, capabilities: [] })
  const cyclicPayload = { type: 'update' }
  cyclicPayload.self = cyclicPayload

  assert.equal(client.send(cyclicPayload), false)
  assert.equal(client.ws, socket)
  assert.equal(client.isAuthenticated, true)
  assert.equal(client.connectionState, 'connected')
  assert.equal(closed, 0)
  assert.deepEqual(errors, ['协作消息无法序列化'])
  assert.deepEqual(scheduler.delays(), [])
  client.disconnect()
})

test('协议状态损坏时可主动退休连接并重新完成安全握手', () => {
  FakeWebSocket.instances.length = 0
  let closed = 0
  const states = []
  const { client, scheduler } = createClient({
    onClose: () => { closed += 1 },
    onConnectionState: (state, detail) => states.push({ state, detail }),
  })
  client.connect()
  const socket = FakeWebSocket.instances.at(-1)
  socket.open()
  socket.message({ type: 'auth_ok', user: { id: 1 }, capabilities: [] })

  assert.equal(client.reconnect('协作更新损坏，正在重新同步'), true)
  assert.equal(socket.readyState, 3)
  assert.equal(client.ws, null)
  assert.equal(client.isAuthenticated, false)
  assert.equal(client.connectionState, 'reconnecting')
  assert.equal(closed, 1)
  assert.deepEqual(scheduler.delays(), [1000])
  assert.equal(states.at(-1).detail, '协作更新损坏，正在重新同步')

  assert.equal(client.reconnect('重复恢复请求'), true)
  assert.deepEqual(scheduler.delays(), [1000])
  client.disconnect()
})

test('用户手动重连会取消慢速退避并立即建立新的连接代次', () => {
  FakeWebSocket.instances.length = 0
  const states = []
  const { client, scheduler } = createClient({
    onConnectionState: (state, detail) => states.push({ state, detail }),
  })

  client.reconnectAttempts = client.maxReconnectAttempts
  assert.equal(client.reconnect('后台慢速重试'), true)
  assert.equal(client.connectionState, 'offline')
  assert.deepEqual(scheduler.delays(), [30000])

  assert.equal(client.retryNow('用户立即重连'), true)
  const socket = FakeWebSocket.instances.at(-1)
  assert.ok(socket)
  assert.equal(client.ws, socket)
  assert.equal(client.reconnectAttempts, 0)
  assert.equal(client.connectionState, 'connecting')
  assert.deepEqual(scheduler.delays(), [50])
  assert.equal(states.some(item => item.detail === '用户立即重连'), true)

  client.disconnect()
})

test('永久认证失败或已销毁会话不能被手动重连绕过', () => {
  FakeWebSocket.instances.length = 0
  const revoked = createClient()
  revoked.client.connect()
  const socket = FakeWebSocket.instances.at(-1)
  socket.open()
  socket.message({
    type: 'auth_error',
    message: '登录会话已失效，请重新登录',
    code: 'session_revoked',
    retryable: false,
  })

  const instanceCount = FakeWebSocket.instances.length
  assert.equal(revoked.client.retryNow(), false)
  assert.equal(FakeWebSocket.instances.length, instanceCount)
  assert.deepEqual(revoked.scheduler.delays(), [])

  revoked.client.disconnect()
  assert.equal(revoked.client.retryNow(), false)
  assert.equal(FakeWebSocket.instances.length, instanceCount)
})

test('暂时认证故障自动重连，失效会话保持永久停止', () => {
  FakeWebSocket.instances.length = 0
  const authFailures = []
  const retryable = createClient({
    onAuthError: (message, detail) => authFailures.push({ message, ...detail }),
  })
  retryable.client.connect()
  const firstSocket = FakeWebSocket.instances.at(-1)
  firstSocket.open()
  firstSocket.message({
    type: 'auth_ok',
    user: { id: 1 },
    capabilities: ['yjs-checkpoint-v1'],
  })
  firstSocket.message({
    type: 'auth_error',
    message: '认证服务暂时不可用，请稍后重试',
    code: 'auth_unavailable',
    retryable: true,
  })

  assert.equal(retryable.client.connectionState, 'reconnecting')
  assert.equal(retryable.client.ws, null)
  assert.deepEqual(retryable.scheduler.delays(), [1000])
  assert.deepEqual(authFailures, [{
    message: '认证服务暂时不可用，请稍后重试',
    code: 'auth_unavailable',
    retryable: true,
  }])
  retryable.client.disconnect()

  const revoked = createClient()
  revoked.client.connect()
  const secondSocket = FakeWebSocket.instances.at(-1)
  secondSocket.open()
  secondSocket.message({
    type: 'auth_error',
    message: '登录会话已失效，请重新登录',
    code: 'session_revoked',
    retryable: false,
  })

  assert.equal(revoked.client.connectionState, 'auth-error')
  assert.equal(revoked.client.ws, null)
  assert.deepEqual(revoked.scheduler.delays(), [])
  revoked.client.disconnect()
})
