import { onBeforeUnmount, reactive, watch } from 'vue'
import { createAgentRequestScope } from './mindmap-agent-devices.js'

// Account/dialog-scoped catalog. An old response must never enable execution
// for a new owner. Errors and stale timestamps fail closed in the picker.
export function useMindmapAgentDevices(active, ownerId, list) {
  const state = reactive({ devices: [], loaded: false, loading: false, enabled: false, error: '', updatedAt: 0, now: Date.now() })
  const scope = createAgentRequestScope()
  let timer
  let pendingRefresh = null
  async function refresh({ afterPending = false } = {}) {
    const current = scope.capture()
    // Handoff needs a read issued after confirmation/exit, not a poll that
    // may already have captured the old busy state. Ordinary polls still skip.
    if (afterPending && pendingRefresh) await pendingRefresh
    if (!current() || !active() || !ownerId() || state.loading) return false
    state.loading = true
    const request = (async () => {
      try {
        const response = await list()
        if (!current()) return false
        state.devices = Array.isArray(response.data?.devices) ? response.data.devices : []
        state.enabled = response.data?.enabled === true
        state.loaded = true
        state.error = ''
        state.updatedAt = Date.now()
        state.now = Date.now()
        return true
      } catch {
        if (current()) state.error = '设备状态读取失败'
        return false
      } finally { if (current()) state.loading = false }
    })()
    pendingRefresh = request
    try { return await request }
    finally { if (pendingRefresh === request) pendingRefresh = null }
  }
  function reset() {
    scope.invalidate()
    pendingRefresh = null
    clearInterval(timer)
    Object.assign(state, { devices: [], loaded: false, loading: false, enabled: false, error: '', updatedAt: 0 })
  }
  watch(() => [active(), ownerId()], () => {
    reset()
    if (!active() || !ownerId()) return
    void refresh()
    let ticks = 0
    timer = setInterval(() => {
      state.now = Date.now()
      if (++ticks % 5 === 0) void refresh()
    }, 1000)
  }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(reset)
  return { state, refresh }
}
