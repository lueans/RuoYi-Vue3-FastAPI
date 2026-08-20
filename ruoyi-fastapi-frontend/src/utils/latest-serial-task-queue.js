export function createLatestSerialTaskQueue({
  delayMs = 0,
  execute,
  onError = () => {},
}) {
  if (typeof execute !== 'function') {
    throw new TypeError('latest serial task queue requires an execute function')
  }

  let timer = null
  let pendingTask
  let hasPendingTask = false
  let generation = 0
  let chain = Promise.resolve()

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  function enqueuePending() {
    clearTimer()
    if (!hasPendingTask) return chain

    const task = pendingTask
    const taskGeneration = generation
    pendingTask = undefined
    hasPendingTask = false
    chain = chain
      .catch(() => {})
      .then(async () => {
        if (taskGeneration !== generation) return
        const context = {
          isCurrent: () => taskGeneration === generation,
        }
        try {
          await execute(task, context)
        } catch (error) {
          if (context.isCurrent()) onError(error)
        }
      })
    return chain
  }

  function schedule(task) {
    pendingTask = task
    hasPendingTask = true
    clearTimer()
    timer = setTimeout(enqueuePending, Math.max(0, delayMs))
  }

  function cancel() {
    generation += 1
    clearTimer()
    pendingTask = undefined
    hasPendingTask = false
  }

  async function flush() {
    const currentChain = enqueuePending()
    await currentChain
  }

  return {
    cancel,
    flush,
    schedule,
  }
}
