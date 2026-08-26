export function createCommentRequestKey() {
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.randomUUID === 'function') {
    return `comment:${cryptoApi.randomUUID()}`
  }
  const randomPart = Math.random().toString(36).slice(2)
  return `comment:${Date.now().toString(36)}:${randomPart}:${Math.random().toString(36).slice(2)}`
}

export function createCommentMutationTracker({ createKey = createCommentRequestKey } = {}) {
  const attempts = new Map()

  return {
    begin(scope, signature) {
      const current = attempts.get(scope)
      if (current?.signature === signature) return current
      const next = { key: createKey(), signature }
      attempts.set(scope, next)
      return next
    },
    succeed(scope, key) {
      if (attempts.get(scope)?.key === key) attempts.delete(scope)
    },
    clear(scope) {
      attempts.delete(scope)
    },
  }
}
