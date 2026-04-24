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
    if (!listeners[event]) return
    listeners[event].forEach(fn => fn(...args))
  }
}

export default bus
