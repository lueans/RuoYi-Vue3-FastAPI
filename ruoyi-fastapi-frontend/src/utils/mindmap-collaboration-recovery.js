// A successful HTTP reload does not prove that the following WebSocket
// handshake recovered. Keep this budget outside each Yjs instance so repeated
// stale → GET → reconnect cycles cannot reset it indefinitely.
export function createMindmapCollaborationRecoveryGuard({ now = Date.now } = {}) {
  let failures = []
  let blocked = false
  return {
    get blocked() { return blocked },
    recordFailure() {
      if (blocked) return false
      const time = now()
      failures = failures.filter(previous => time - previous < 30_000)
      failures.push(time)
      if (failures.length > 3) blocked = true
      return !blocked
    },
    reset() { failures = []; blocked = false },
  }
}
