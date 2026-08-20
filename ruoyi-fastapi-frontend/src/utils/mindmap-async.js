export function createLatestRequestTracker() {
  let currentRequestId = 0
  return {
    begin() {
      currentRequestId += 1
      return currentRequestId
    },
    invalidate() {
      currentRequestId += 1
    },
    isCurrent(requestId) {
      return requestId === currentRequestId
    },
  }
}

export function createScopedAsyncSession() {
  let generation = 0
  let active = false
  let identity

  function snapshot() {
    if (!active) return null
    return Object.freeze({ generation, identity })
  }

  return {
    activate(nextIdentity) {
      generation += 1
      active = true
      identity = nextIdentity
      return snapshot()
    },
    capture() {
      return snapshot()
    },
    invalidate() {
      generation += 1
      active = false
      identity = undefined
    },
    isCurrent(session) {
      return Boolean(
        active
        && session
        && session.generation === generation
        && Object.is(session.identity, identity),
      )
    },
  }
}

export function isElementDialogDismissal(reason) {
  return reason === 'cancel' || reason === 'close'
}
