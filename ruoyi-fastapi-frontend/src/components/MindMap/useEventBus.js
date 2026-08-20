const listeners = {}

export const bus = {
  on(event, fn) {
    if (!listeners[event]) listeners[event] = []
    if (!listeners[event].includes(fn)) {
      listeners[event].push(fn)
    }
  },
  off(event, fn) {
    if (!listeners[event]) return
    if (fn) {
      listeners[event] = listeners[event].filter(f => f !== fn)
    } else {
      delete listeners[event]
    }
  },
  emit(event, ...args) {
    const eventListeners = listeners[event]
    if (!eventListeners?.length) return false
    // Dispatch a snapshot so a listener can safely remove itself or another
    // listener without skipping the next callback in the current emission.
    eventListeners.slice().forEach(fn => fn(...args))
    return true
  }
}

export default bus
