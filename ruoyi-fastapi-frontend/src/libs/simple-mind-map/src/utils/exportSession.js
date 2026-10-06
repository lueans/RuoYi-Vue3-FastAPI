export const exportAbortError = (message = '导出已取消') => {
  const error = new Error(message)
  error.name = 'AbortError'
  return error
}

export const throwIfExportAborted = signal => {
  if (signal?.aborted) throw signal.reason || exportAbortError()
}

// A caller timing out must settle the inner wait too, not just abandon it.
export const abortableExport = (value, signal) => new Promise((resolve, reject) => {
  const abort = () => finish(reject, signal.reason || exportAbortError())
  const finish = (settle, result) => {
    signal?.removeEventListener('abort', abort)
    settle(result)
  }
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  Promise.resolve(value).then(result => finish(resolve, result), error => finish(reject, error))
})

export const loadExportImage = (src, signal) => new Promise((resolve, reject) => {
  let image
  let settled = false
  const finish = (error, cancel = false) => {
    if (settled) return
    settled = true
    signal?.removeEventListener('abort', abort)
    if (image) {
      image.onload = null
      image.onerror = null
      if (cancel) image.src = ''
    }
    if (error) reject(error)
    else resolve(image)
  }
  const abort = () => finish(signal.reason || exportAbortError(), true)
  if (signal?.aborted) return abort()
  try {
    image = new Image()
    image.setAttribute('crossOrigin', 'anonymous')
    image.onload = () => finish()
    image.onerror = () => finish(new Error('图片无法加载'), true)
    signal?.addEventListener('abort', abort, { once: true })
    image.src = src
  } catch (error) {
    finish(error, true)
  }
})

// Snapshot in the same call stack as the idle check. Waiting for a Promise
// and then cloning separately leaves another microtask-sized mutation window.
export const captureAfterMindmapRender = (mindMap, capture, {
  signal, timeoutMs = 15000,
} = {}) => new Promise((resolve, reject) => {
  const renderer = mindMap.renderer
  const root = renderer?.renderTree
  let timer
  let settled = false
  const deadline = setTimeout(() => finish(new Error('脑图渲染尚未完成，请稍后重试导出')), timeoutMs)
  const finish = (error, result) => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    clearTimeout(deadline)
    signal?.removeEventListener('abort', onAbort)
    mindMap.off?.('beforeDestroy', onDestroy)
    mindMap.off?.('node_tree_render_error', onError)
    if (error) reject(error)
    else resolve(result)
  }
  const onAbort = () => finish(signal.reason || exportAbortError())
  const onDestroy = () => finish(exportAbortError('脑图实例已关闭'))
  const onError = error => finish(error || new Error('脑图渲染失败'))
  const check = () => {
    if (settled) return
    try {
      throwIfExportAborted(signal)
      if (!renderer || renderer.destroyed || renderer !== mindMap.renderer || renderer.renderTree !== root) {
        throw exportAbortError('脑图会话已经变化，请重新导出')
      }
      if (renderer.isRendering || renderer.renderTimer != null || renderer.hasWaitRendering) {
        timer = setTimeout(check, 16)
        return
      }
      if (renderer.renderRecoveryRequired) {
        throw new Error('脑图上次渲染未完成，请重新渲染后再导出')
      }
      finish(null, capture())
    } catch (error) {
      finish(error)
    }
  }
  signal?.addEventListener('abort', onAbort, { once: true })
  mindMap.on?.('beforeDestroy', onDestroy)
  mindMap.on?.('node_tree_render_error', onError)
  check()
})

export const createExportSession = (mindMap, { signal, timeoutMs = 60000 } = {}) => {
  const controller = new AbortController()
  const root = mindMap.renderer?.renderTree
  const abort = reason => {
    if (!controller.signal.aborted) controller.abort(reason || exportAbortError())
  }
  const onAbort = () => abort(signal.reason)
  const onReplace = () => abort(exportAbortError('脑图会话已经变化，请重新导出'))
  const onRender = () => {
    if (mindMap.renderer?.renderTree !== root) onReplace()
  }
  const timeout = setTimeout(() => abort(new Error('导出超时，请检查图片连接后重试，或使用 JSON 备份。')), timeoutMs)
  signal?.addEventListener('abort', onAbort, { once: true })
  if (signal?.aborted) onAbort()
  mindMap.on?.('beforeDestroy', onReplace)
  mindMap.on?.('before_set_data', onReplace)
  mindMap.on?.('before_update_data', onReplace)
  mindMap.on?.('node_tree_render_start', onRender)
  return {
    signal: controller.signal,
    abort,
    check() {
      if (mindMap.renderer?.destroyed || mindMap.renderer?.renderTree !== root) onReplace()
      throwIfExportAborted(controller.signal)
    },
    dispose() {
      abort()
      clearTimeout(timeout)
      signal?.removeEventListener('abort', onAbort)
      mindMap.off?.('beforeDestroy', onReplace)
      mindMap.off?.('before_set_data', onReplace)
      mindMap.off?.('before_update_data', onReplace)
      mindMap.off?.('node_tree_render_start', onRender)
    },
  }
}
