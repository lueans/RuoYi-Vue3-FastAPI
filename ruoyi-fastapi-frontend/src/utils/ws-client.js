/**
 * WebSocket 客户端封装
 * 支持连接后认证（token 不在 URL 中）
 */
import { getToken } from './auth.js'

const WS_CAPABILITIES = [
  'structured-node-patch-v1',
  'yjs-checkpoint-v1',
]
const DEFAULT_CONNECT_TIMEOUT_MS = 10000
const DEFAULT_AUTH_TIMEOUT_MS = 15000
// 兼容旧服务端 sync_init 同时携带 states 和重复 legacy state 的最坏体积；
// 新服务端会对已协商检查点能力的客户端省略该重复字段。
const DEFAULT_MAX_SERVER_MESSAGE_BYTES = 48 * 1024 * 1024

function normalizePositiveInteger(value, fallback) {
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback
}

function exceedsUtf8ByteLimit(value, limit) {
  let bytes = 0
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index)
    if (codeUnit <= 0x7F) bytes += 1
    else if (codeUnit <= 0x7FF) bytes += 2
    else if (
      codeUnit >= 0xD800
      && codeUnit <= 0xDBFF
      && index + 1 < value.length
      && value.charCodeAt(index + 1) >= 0xDC00
      && value.charCodeAt(index + 1) <= 0xDFFF
    ) {
      bytes += 4
      index += 1
    } else bytes += 3
    if (bytes > limit) return true
  }
  return false
}

export function parseMindmapWsMessage(rawData, maxBytes = DEFAULT_MAX_SERVER_MESSAGE_BYTES) {
  if (typeof rawData !== 'string' || !Number.isInteger(maxBytes) || maxBytes <= 0) {
    throw new TypeError('Invalid collaboration message')
  }
  if (
    rawData.length > maxBytes
    || exceedsUtf8ByteLimit(rawData, maxBytes)
  ) {
    throw new RangeError('Collaboration message exceeds limit')
  }
  const data = JSON.parse(rawData)
  if (
    !data
    || typeof data !== 'object'
    || Array.isArray(data)
    || typeof data.type !== 'string'
    || !data.type
  ) {
    throw new TypeError('Invalid collaboration message')
  }
  return data
}

export function resolveMindmapWsUrl(location, baseApi, mindmapId) {
  if (!location?.protocol || !location?.host) {
    throw new Error('无法确定协作服务地址')
  }
  const origin = `${location.protocol}//${location.host}/`
  const url = new URL(baseApi || '/', origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = `${url.pathname.replace(/\/$/, '')}/ws/mindmap/${encodeURIComponent(String(mindmapId))}`
  url.search = ''
  url.hash = ''
  return url.toString()
}

export class MindmapWsClient {
  constructor(mindmapId, handlers, options = {}) {
    this.mindmapId = mindmapId
    this.handlers = handlers || {}
    this.eventTarget = options.eventTarget ?? (typeof window !== 'undefined' ? window : null)
    this.location = options.location ?? this.eventTarget?.location
    this.WebSocketImpl = options.WebSocketImpl ?? globalThis.WebSocket
    this.baseApi = options.baseApi ?? import.meta.env?.VITE_APP_BASE_API ?? ''
    // Window 定时器是 Web API 方法；保存后以客户端实例作为 this 调用时，
    // 部分 Chromium 环境会抛出 Illegal invocation。默认实现必须固定到
    // globalThis，测试注入的调度器则保持原样。
    this.setTimeoutFn = options.setTimeout ?? globalThis.setTimeout.bind(globalThis)
    this.clearTimeoutFn = options.clearTimeout ?? globalThis.clearTimeout.bind(globalThis)
    this.connectTimeoutMs = normalizePositiveInteger(
      options.connectTimeoutMs,
      DEFAULT_CONNECT_TIMEOUT_MS,
    )
    this.authTimeoutMs = normalizePositiveInteger(
      options.authTimeoutMs,
      DEFAULT_AUTH_TIMEOUT_MS,
    )
    this.maxServerMessageBytes = normalizePositiveInteger(
      options.maxServerMessageBytes,
      DEFAULT_MAX_SERVER_MESSAGE_BYTES,
    )
    this.ws = null
    this.reconnectTimer = null
    this.phaseTimer = null
    this.socketGeneration = 0
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = Number.isInteger(options.maxReconnectAttempts)
      && options.maxReconnectAttempts >= 0
      ? options.maxReconnectAttempts
      : 5
    this.isAuthenticated = false
    this.connectionState = 'idle'
    this.manualClose = false
    this.onlineListenerBound = false
    this._handleOnline = () => {
      if (this.manualClose || this.connectionState === 'auth-error') return
      if (this._isSocketOpenOrConnecting()) return
      this._clearReconnectTimer()
      this.reconnectAttempts = 0
      this.connect()
    }
  }

  _setConnectionState(state, detail) {
    this.connectionState = state
    this.handlers.onConnectionState?.(state, detail)
  }

  _isSocketOpenOrConnecting() {
    const readyState = this.ws?.readyState
    return readyState === 0 || readyState === 1
  }

  _isCurrentSocket(socket, generation) {
    return Boolean(
      !this.manualClose
      && socket
      && this.ws === socket
      && this.socketGeneration === generation
    )
  }

  _clearReconnectTimer() {
    if (this.reconnectTimer !== null) this.clearTimeoutFn(this.reconnectTimer)
    this.reconnectTimer = null
  }

  _clearPhaseTimer() {
    if (this.phaseTimer !== null) this.clearTimeoutFn(this.phaseTimer)
    this.phaseTimer = null
  }

  _armPhaseTimeout(socket, generation, delay, message) {
    this._clearPhaseTimer()
    this.phaseTimer = this.setTimeoutFn(() => {
      this.phaseTimer = null
      if (!this._isCurrentSocket(socket, generation)) return
      this._failCurrentSocket(socket, generation, new Error(message))
    }, delay)
  }

  _failCurrentSocket(socket, generation, error) {
    if (!this._isCurrentSocket(socket, generation)) return false
    this.handlers.onError?.(error)
    return this._retireSocket(socket, generation, {
      closeSocket: true,
      detail: error?.message || '协作连接异常',
    })
  }

  _retireSocket(socket, generation, { closeSocket = false, detail } = {}) {
    if (this.ws !== socket || this.socketGeneration !== generation) return false
    this._clearPhaseTimer()
    this.ws = null
    this.socketGeneration += 1
    this.isAuthenticated = false
    socket.onopen = null
    socket.onmessage = null
    socket.onclose = null
    socket.onerror = null
    if (closeSocket && socket.readyState !== 3) {
      try {
        socket.close()
      } catch {
        // 已从当前会话移除；底层关闭异常不能阻断后续重连。
      }
    }
    this.handlers.onClose?.()
    if (this.manualClose) return true
    if (this.connectionState !== 'auth-error') {
      this._setConnectionState(
        this.reconnectAttempts >= this.maxReconnectAttempts ? 'offline' : 'reconnecting',
        detail,
      )
    }
    this._scheduleReconnect()
    return true
  }

  _handleConnectionFailure(error) {
    this.isAuthenticated = false
    this.handlers.onError?.(error)
    if (this.manualClose || this.connectionState === 'auth-error') return
    this._setConnectionState(
      this.reconnectAttempts >= this.maxReconnectAttempts ? 'offline' : 'reconnecting',
      error?.message || '协作连接失败',
    )
    this._scheduleReconnect()
  }

  connect() {
    if (this.manualClose || this.connectionState === 'auth-error') return
    if (this._isSocketOpenOrConnecting()) return
    if (!this.onlineListenerBound) {
      this.eventTarget?.addEventListener?.('online', this._handleOnline)
      this.onlineListenerBound = Boolean(this.eventTarget?.addEventListener)
    }
    this._clearReconnectTimer()
    this._setConnectionState(this.reconnectAttempts > 0 ? 'reconnecting' : 'connecting')
    let socket
    let wsUrl
    try {
      wsUrl = resolveMindmapWsUrl(this.location, this.baseApi, this.mindmapId)
      socket = new this.WebSocketImpl(wsUrl)
    } catch (error) {
      this._handleConnectionFailure(error)
      return
    }
    const generation = this.socketGeneration + 1
    this.socketGeneration = generation
    this.ws = socket
    this._armPhaseTimeout(socket, generation, this.connectTimeoutMs, '协作连接超时')

    socket.onopen = () => {
      if (!this._isCurrentSocket(socket, generation)) return
      this._clearPhaseTimer()
      this._setConnectionState('authenticating')
      try {
        socket.send(JSON.stringify({
          type: 'auth',
          token: getToken(),
          capabilities: WS_CAPABILITIES,
        }))
      } catch (error) {
        this._failCurrentSocket(socket, generation, error)
        return
      }
      this._armPhaseTimeout(socket, generation, this.authTimeoutMs, '协作认证超时')
    }

    socket.onmessage = (event) => {
      if (!this._isCurrentSocket(socket, generation)) return
      let data
      try {
        data = parseMindmapWsMessage(event.data, this.maxServerMessageBytes)
      } catch {
        this.handlers.onError?.(new Error('协作服务返回了无效消息'))
        this._retireSocket(socket, generation, {
          closeSocket: true,
          detail: '协作消息异常，正在重新同步',
        })
        return
      }
      try {
        if (
          !this.isAuthenticated
          && data.type !== 'auth_ok'
          && data.type !== 'auth_error'
        ) {
          throw new TypeError('Message received before authentication')
        }
        if (data.type === 'auth_ok') {
          if (this.isAuthenticated) throw new TypeError('Duplicate auth response')
          this._clearPhaseTimer()
          this.isAuthenticated = true
          this.reconnectAttempts = 0
          this._setConnectionState('connected')
          this.handlers.onAuthenticated?.(data.user, data.capabilities)
        } else if (data.type === 'auth_error') {
          const retryable = data.retryable === true
          this.handlers.onAuthError?.(data.message, {
            code: data.code,
            retryable,
          })
          if (retryable) {
            this._retireSocket(socket, generation, {
              closeSocket: true,
              detail: data.message,
            })
          } else {
            this.reconnectAttempts = this.maxReconnectAttempts
            this._setConnectionState('auth-error', data.message)
            this._retireSocket(socket, generation, { closeSocket: true })
          }
        } else if (data.type === 'ping') {
          // 心跳响应
          this.send({ type: 'pong' })
        } else if (this.isAuthenticated) {
          // 未识别的对象消息保持向前兼容；只有当前客户端已注册的类型才分发。
          this.handlers[data.type]?.(data)
        }
      } catch {
        this.handlers.onError?.(new Error('协作消息处理失败'))
        this._retireSocket(socket, generation, {
          closeSocket: true,
          detail: '协作状态异常，正在重新同步',
        })
      }
    }

    socket.onclose = () => {
      this._retireSocket(socket, generation)
    }

    socket.onerror = () => {
      this._failCurrentSocket(socket, generation, new Error('协作连接异常'))
    }
  }

  send(data) {
    const socket = this.ws
    const generation = this.socketGeneration
    if (socket?.readyState === 1 && this.isAuthenticated) {
      let serialized
      try {
        serialized = JSON.stringify(data)
        if (typeof serialized !== 'string') throw new TypeError()
      } catch {
        // 本地负载错误不代表 socket 失效；退休连接只会造成无意义重连，
        // 且无法修复循环引用、BigInt 等确定性的序列化问题。
        this.handlers.onError?.(new Error('协作消息无法序列化'))
        return false
      }
      try {
        socket.send(serialized)
        return true
      } catch (error) {
        this._failCurrentSocket(socket, generation, error)
      }
    }
    return false
  }

  reconnect(detail = '正在重新同步协作状态') {
    if (this.manualClose || this.connectionState === 'auth-error') return false
    const socket = this.ws
    const generation = this.socketGeneration
    if (socket) {
      return this._retireSocket(socket, generation, {
        closeSocket: true,
        detail,
      })
    }
    this._clearPhaseTimer()
    this._setConnectionState(
      this.reconnectAttempts >= this.maxReconnectAttempts ? 'offline' : 'reconnecting',
      detail,
    )
    if (this.reconnectTimer === null) this._scheduleReconnect()
    return true
  }

  retryNow(detail = '正在手动重新连接协作服务') {
    if (this.manualClose || this.connectionState === 'auth-error') return false
    const socket = this.ws
    const generation = this.socketGeneration
    if (socket) {
      this._retireSocket(socket, generation, {
        closeSocket: true,
        detail,
      })
    }
    // 自动重连达到上限后会进入 30 秒慢速轮询；用户明确重试时取消旧计时，
    // 重置退避并立即创建新连接。旧 socket 已通过 generation 失效，不能回写新会话。
    this._clearReconnectTimer()
    this._clearPhaseTimer()
    this.reconnectAttempts = 0
    if (!socket) this._setConnectionState('reconnecting', detail)
    this.connect()
    return true
  }

  disconnect() {
    this.manualClose = true
    this._clearReconnectTimer()
    this._clearPhaseTimer()
    if (this.onlineListenerBound) {
      this.eventTarget?.removeEventListener?.('online', this._handleOnline)
      this.onlineListenerBound = false
    }
    const socket = this.ws
    const generation = this.socketGeneration
    if (socket) this._retireSocket(socket, generation, { closeSocket: true })
    this.isAuthenticated = false
    this._setConnectionState('closed')
  }

  _scheduleReconnect() {
    if (this.manualClose || this.connectionState === 'auth-error') return
    this._clearReconnectTimer()
    const delay = this.reconnectAttempts >= this.maxReconnectAttempts
      ? 30000
      : Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)
    this.reconnectTimer = this.setTimeoutFn(() => {
      this.reconnectTimer = null
      this.reconnectAttempts = Math.min(this.reconnectAttempts + 1, this.maxReconnectAttempts)
      this.connect()
    }, delay)
  }
}
