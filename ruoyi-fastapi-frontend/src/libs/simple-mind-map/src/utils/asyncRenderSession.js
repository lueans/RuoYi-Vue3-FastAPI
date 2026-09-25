// 管理一次异步节点渲染产生的全部定时任务。新渲染或实例销毁时可一次取消，
// 防止旧任务继续修改已经失效的 SVG 节点。
export const createAsyncRenderSession = ({
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onError = null
} = {}) => {
  let active = true
  const timers = new Set()
  const visited = new WeakSet()

  const session = {
    run(task) {
      if (!active) return false
      try {
        task()
        return active
      } catch (error) {
        session.cancel()
        if (onError) onError(error)
        else throw error
        return false
      }
    },
    claim(target) {
      if (!active || !target || typeof target !== 'object') return false
      if (visited.has(target)) return false
      visited.add(target)
      return true
    },

    schedule(task) {
      if (!active) return false
      const timer = setTimer(() => {
        timers.delete(timer)
        session.run(task)
      }, 0)
      timers.add(timer)
      return true
    },

    cancel() {
      if (!active) return
      active = false
      timers.forEach(timer => clearTimer(timer))
      timers.clear()
    },

    isActive() {
      return active
    },

    pendingCount() {
      return timers.size
    }
  }
  return session
}
