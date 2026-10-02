import { computed, onScopeDispose, ref, watch } from 'vue'
import { isMindmapExecutionBlocked } from './mindmap-execution-state.js'
import { mergeMindmapAiJobSnapshot } from './mindmap-ai-stream.js'

// Terminal result hydration must not own this poll: it can finish long before
// the executor closes. Identity/epoch/account changes invalidate every callback.
export function useMindmapExecutionStop({ job, ownerId, loadJob, onUpdated = () => {},
  enabled = () => true, intervalMs = 1000, maxPolls = 30 }) {
  const checking = ref(false)
  const error = ref('')
  const blocked = computed(() => isMindmapExecutionBlocked(job.value))
  let generation = 0
  let timer = null
  let controller = null
  let polls = 0
  let disposed = false
  const stopWaiters = new Set()

  // Join the existing SSE/poll evidence, never issue another cancellation or
  // start a second polling loop. A chosen handoff is bounded and page-local.
  function waitForStopped({ stillCurrent, isRunning, timeoutMs = 30000 }) {
    const id = job.value?.id
    const epoch = job.value?.executionEpoch
    const owner = ownerId()
    return new Promise(resolve => {
      let unwatch
      let timeout
      const finish = result => {
        unwatch?.()
        clearTimeout(timeout)
        stopWaiters.delete(finish)
        resolve(result)
      }
      const check = () => {
        const snapshot = job.value
        if (disposed || !enabled() || !id || !stillCurrent() || snapshot?.id !== id
          || snapshot.executionEpoch !== epoch || ownerId() !== owner) return finish(false)
        if (snapshot.executionState === 'unconfirmed'
          || (snapshot.errorCode === 'AI_AGENT_CLEANUP_FAILED' && snapshot.executionState !== 'stopped')) return finish(false)
        if (!isRunning() && Number.isSafeInteger(epoch) && epoch >= 0
          && ['stopped', 'not_started'].includes(snapshot.executionState)) finish(true)
      }
      stopWaiters.add(finish)
      unwatch = watch([job, ownerId, enabled, stillCurrent, isRunning, () => job.value?.executionEpoch,
        () => job.value?.executionState, () => job.value?.errorCode], check, { flush: 'sync' })
      timeout = setTimeout(() => finish(false), timeoutMs)
      check()
    })
  }

  function cancel() {
    generation++
    clearTimeout(timer)
    timer = null
    controller?.abort()
    controller = null
    checking.value = false
  }

  async function refresh({ automatic = false } = {}) {
    if (disposed || !enabled() || !blocked.value || checking.value || !job.value?.id) return false
    if (!automatic) polls = 0
    const identity = generation
    const id = job.value.id
    const epoch = job.value.executionEpoch
    const owner = ownerId()
    const request = new AbortController()
    controller = request
    const current = () => !disposed && enabled() && generation === identity && job.value?.id === id
      && job.value.executionEpoch === epoch && ownerId() === owner
    checking.value = true
    error.value = ''
    try {
      const response = await loadJob(id, { signal: request.signal })
      if (!current()) return false
      if (!response?.data || response.data.id !== id) {
        throw new Error('Execution receipt does not belong to the requested job')
      }
      job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
      onUpdated(job.value)
      return !blocked.value
    } catch (failure) {
      if (current() && !request.signal.aborted) error.value = '暂时无法查询退出状态，请检查连接后刷新。'
      return false
    } finally {
      if (generation === identity) {
        checking.value = false
        if (controller === request) controller = null
        if (current() && blocked.value && job.value.executionState === 'running') {
          if (++polls < maxPolls) {
            clearTimeout(timer)
            timer = setTimeout(() => { timer = null; void refresh({ automatic: true }) }, intervalMs)
          } else error.value = '等待退出确认超时；未启动新一轮。请检查运行主机后刷新。'
        }
      }
    }
  }

  // Compare each identity field, not a newly allocated array on every snapshot.
  // Otherwise a running receipt restarts this immediate watcher recursively,
  // bypassing the poll interval/budget and starving rendering and cancellation.
  watch([() => job.value?.id, () => job.value?.executionEpoch, ownerId, enabled, () => blocked.value], () => {
    cancel()
    polls = 0
    error.value = ''
    if (enabled() && blocked.value) void refresh({ automatic: true })
  }, { immediate: true })
  onScopeDispose(() => {
    disposed = true
    cancel()
    for (const finish of stopWaiters) finish(false)
  })
  return { blocked, checking, error, refresh, waitForStopped }
}
