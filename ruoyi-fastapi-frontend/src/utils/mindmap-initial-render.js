function isMindmapInitialRenderComplete(instance) {
  const renderer = instance?.renderer
  return Boolean(
    renderer
    && !renderer.destroyed
    && renderer.root
    && renderer.isRendering !== true
    && !renderer.renderTimer
  )
}
/**
 * 等待 simple-mind-map 首次画布渲染完成。
 *
 * 浏览器会暂停后台标签页的 requestAnimationFrame，不能让仍在后台等待的
 * 画布消耗失败超时；否则同时打开多个协作标签页时，后台页会稳定误报
 * “首次渲染超时”。重新可见后才重新开始完整的可见时间预算。
 */
export function waitForMindmapInitialRender(instance, {
  timeoutMs = 10000,
  documentRef = globalThis.document,
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
} = {}) {
  return new Promise((resolve, reject) => {
    let settled = false
    let timeoutId = null

    const clearWatchdog = () => {
      if (timeoutId === null) return
      clearTimer(timeoutId)
      timeoutId = null
    }
    const cleanup = () => {
      clearWatchdog()
      instance?.off?.('node_tree_render_end', onRenderEnd)
      instance?.off?.('beforeDestroy', onBeforeDestroy)
      documentRef?.removeEventListener?.('visibilitychange', onVisibilityChange)
    }
    const finish = (error) => {
      if (settled) return
      settled = true
      cleanup()
      if (error) reject(error)
      else resolve()
    }
    const onRenderEnd = () => finish()
    const onBeforeDestroy = () => finish(new Error('脑图实例已在首次渲染前销毁'))
    const armVisibleWatchdog = () => {
      clearWatchdog()
      if (settled || documentRef?.visibilityState === 'hidden') return
      // 初次渲染事件可能在调用方完成插件接线前已经触发。运行态也能证明
      // 首棵树已完整落到渲染器时，直接进入就绪态，避免等待一个不会重发的事件。
      if (isMindmapInitialRenderComplete(instance)) {
        finish()
        return
      }
      timeoutId = setTimer(() => {
        timeoutId = null
        if (documentRef?.visibilityState === 'hidden') return
        if (isMindmapInitialRenderComplete(instance)) {
          finish()
          return
        }
        finish(new Error('脑图首次渲染超时'))
      }, timeoutMs)
    }
    const onVisibilityChange = () => {
      if (documentRef?.visibilityState === 'hidden') {
        clearWatchdog()
        return
      }
      armVisibleWatchdog()
    }

    instance?.on?.('node_tree_render_end', onRenderEnd)
    instance?.on?.('beforeDestroy', onBeforeDestroy)
    documentRef?.addEventListener?.('visibilitychange', onVisibilityChange)
    armVisibleWatchdog()
  })
}
