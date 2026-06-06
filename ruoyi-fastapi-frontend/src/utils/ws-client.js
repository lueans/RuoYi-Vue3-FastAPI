/**
 * WebSocket 客户端封装
 * 支持连接后认证（token 不在 URL 中）
 */
import { getToken } from '@/utils/auth'

export class MindmapWsClient {
  constructor(mindmapId, handlers) {
    this.mindmapId = mindmapId
    this.handlers = handlers || {}
    this.ws = null
    this.reconnectTimer = null
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 5
    this.isAuthenticated = false
  }

  connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // 通过 Vite 代理时需要加上 base path
    const base = import.meta.env.VITE_APP_BASE_API || ''
    const wsUrl = `${protocol}//${window.location.host}${base}/ws/mindmap/${this.mindmapId}`

    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = () => {
      const token = getToken()
      this.ws.send(JSON.stringify({ type: 'auth', token }))
    }

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'auth_ok') {
          this.isAuthenticated = true
          this.reconnectAttempts = 0
          this.handlers.onAuthenticated?.(data.user)
        } else if (data.type === 'auth_error') {
          this.handlers.onAuthError?.(data.message)
          this.ws.close()
        } else if (this.isAuthenticated) {
          this.handlers[data.type]?.(data)
        }
      } catch (e) {
        console.error('WS message parse error:', e)
      }
    }

    this.ws.onclose = () => {
      this.isAuthenticated = false
      this.handlers.onClose?.()
      this._scheduleReconnect()
    }

    this.ws.onerror = (error) => {
      console.error('WS error:', error)
    }
  }

  send(data) {
    if (this.ws?.readyState === WebSocket.OPEN && this.isAuthenticated) {
      this.ws.send(JSON.stringify(data))
    }
  }

  disconnect() {
    clearTimeout(this.reconnectTimer)
    this.reconnectAttempts = this.maxReconnectAttempts // 阻止重连
    this.ws?.close()
    this.ws = null
    this.isAuthenticated = false
  }

  _scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }
}
