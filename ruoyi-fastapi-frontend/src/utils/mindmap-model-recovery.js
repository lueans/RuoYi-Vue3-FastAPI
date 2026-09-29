// A repair link carries only an internal model ID, never credentials, endpoint,
// prompt, document data, or an arbitrary return URL. Backend permissions and
// data scope remain authoritative after navigation.
export function normalizeModelRecoveryId(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return null
  const text = String(value)
  if (!/^[1-9]\d{0,15}$/.test(text)) return null
  const id = Number(text)
  return Number.isSafeInteger(id) ? id : null
}

export function modelRepairLocation({ permissions = [], routeAvailable = false, modelId } = {}) {
  const allowed = Array.isArray(permissions) && ['ai:model:list', 'ai:model:query', 'ai:model:edit']
    .every(permission => permissions.includes('*:*:*') || permissions.includes(permission))
  if (!allowed || !routeAvailable) return null
  const id = normalizeModelRecoveryId(modelId)
  return { path: '/ai/model', query: { from: 'mindmap-agent', ...(id ? { modelId: String(id) } : {}) } }
}

export function enabledRecoveryModels(response) {
  if (!Array.isArray(response?.data)) throw new Error('Invalid model catalogue')
  return response.data.filter(model => model && normalizeModelRecoveryId(model.modelId)
    && String(model.status ?? '0') === '0')
}
