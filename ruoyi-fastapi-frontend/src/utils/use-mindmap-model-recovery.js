import { onScopeDispose, ref, watch } from 'vue'
import { enabledRecoveryModels } from './mindmap-model-recovery.js'

// Only refresh metadata. Never select a replacement model, test provider
// credentials, restart a task, or mutate its request/configuration snapshot.
export function useMindmapModelRecovery({ models, loadModels, ownerId, epoch, agentKey, canRefresh }) {
  const loading = ref(false)
  const error = ref('')
  const notice = ref('')
  let generation = 0
  let controller = null
  let disposed = false

  function invalidate() {
    generation++
    controller?.abort()
    controller = null
    loading.value = false
    error.value = ''
    notice.value = ''
  }

  async function refresh() {
    if (disposed || loading.value || !ownerId() || !canRefresh()) return false
    const requestGeneration = ++generation
    const owner = ownerId()
    const currentEpoch = epoch()
    const agent = agentKey()
    const request = new AbortController()
    const current = () => !disposed && generation === requestGeneration && ownerId() === owner
      && epoch() === currentEpoch && agentKey() === agent && canRefresh()
    controller = request
    loading.value = true
    error.value = ''
    notice.value = ''
    try {
      const response = await loadModels({ signal: request.signal, silentError: true })
      if (!current()) return false
      models.value = enabledRecoveryModels(response)
      notice.value = '已重新读取模型配置。实际连接和认证将在运行时校验，不会自动发送任务。'
      return true
    } catch {
      if (current() && !request.signal.aborted) {
        error.value = '无法重新读取模型配置，已保留上次清单；请检查连接后重试。'
      }
      return false
    } finally {
      if (generation === requestGeneration) {
        loading.value = false
        if (controller === request) controller = null
      }
    }
  }

  // Closing the panel or starting a task also invalidates the request. Even an
  // abort-ignoring transport must not update a later task/account's catalogue.
  watch([ownerId, epoch, agentKey, canRefresh], invalidate, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; invalidate() })
  return { loading, error, notice, refresh, invalidate }
}
