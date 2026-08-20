const isRecord = value => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
)

/**
 * Coalesce file-level metadata changes without tying the editor to a specific
 * transport. `flush()` is intentionally synchronous so save/leave boundaries
 * can commit the exact pending payload before destroying the collaboration
 * session.
 */
export function createMindmapDocumentMetaBuffer(
  commit,
  {
    setTimer = (callback, delay) => setTimeout(callback, delay),
    clearTimer = timer => clearTimeout(timer),
  } = {},
) {
  if (typeof commit !== 'function') {
    throw new TypeError('文档元数据提交器必须是函数')
  }

  let pending = null
  let timer = null

  const cancelTimer = () => {
    if (timer === null) return
    clearTimer(timer)
    timer = null
  }

  const flush = () => {
    cancelTimer()
    if (!pending) return false
    const next = pending
    pending = null
    commit(next)
    return true
  }

  const enqueue = (patch, delay = 120) => {
    if (!isRecord(patch) || Object.keys(patch).length === 0) return false
    pending = { ...(pending || {}), ...patch }
    cancelTimer()
    timer = setTimer(flush, Math.max(0, Number(delay) || 0))
    return true
  }

  const clear = () => {
    cancelTimer()
    pending = null
  }

  return {
    enqueue,
    flush,
    clear,
    hasPending: () => pending !== null,
  }
}
