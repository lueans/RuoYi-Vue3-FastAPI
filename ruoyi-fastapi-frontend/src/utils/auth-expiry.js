import { createLoginRedirectLocation } from './login-redirect.js'

export const AUTH_EXPIRED_CODE = 401

// The rejected credential and this tab's mounted owner can differ after a
// cross-tab login. Fence both identities until the old owner's drafts are
// protected, without changing their ownership or disclosing tokens in events.
let expiredSession = null
const expirySubscribers = new Set()
const expiryEvent = Object.freeze({ kind: 'expired' })

export function isAuthSessionExpired(token) {
  return typeof token === 'string' && Boolean(token) && Boolean(expiredSession && (
    expiredSession.token === token || expiredSession.ownerToken === token
  ))
}

export function hasAuthExpiredSession() {
  return expiredSession !== null
}

function runExpiryCleanup(session, handler) {
  const cleanup = { handler, status: 'pending', error: null, promise: null }
  session.cleanups.set(handler, cleanup)
  let result
  try {
    // Invoke immediately so synchronous subscribers stop timers before another
    // request can start. Never disclose the rejected token in event payloads.
    result = handler(expiryEvent)
  } catch (error) {
    result = Promise.reject(error)
  }
  cleanup.promise = Promise.resolve(result).then(
    () => { cleanup.status = 'fulfilled' },
    error => {
      cleanup.status = 'rejected'
      cleanup.error = error instanceof Error ? error : new Error('未能安全保存当前编辑内容，请重试')
    },
  )
}

export function markAuthSessionExpired(token, { ownerToken = token } = {}) {
  if (typeof token !== 'string' || !token || isAuthSessionExpired(token)) return false
  const session = {
    token,
    ownerToken: typeof ownerToken === 'string' && ownerToken ? ownerToken : token,
    prompted: false,
    cleanups: new Map(),
  }
  expiredSession = session
  for (const handler of expirySubscribers) runExpiryCleanup(session, handler)
  return true
}

export function subscribeAuthExpiry(handler) {
  if (typeof handler !== 'function') throw new TypeError('认证失效处理器必须是函数')
  expirySubscribers.add(handler)
  if (expiredSession && !expiredSession.cleanups.has(handler)) runExpiryCleanup(expiredSession, handler)
  return () => expirySubscribers.delete(handler)
}

export function claimAuthExpiryPrompt(token) {
  if (!isAuthSessionExpired(token) || expiredSession.prompted) return false
  expiredSession.prompted = true
  return true
}

export function resetAuthExpirySession() {
  expiredSession = null
}

export async function waitForAuthExpiryCleanup({ retryFailed = false } = {}) {
  const session = expiredSession
  if (!session) return
  if (retryFailed) {
    for (const cleanup of session.cleanups.values()) {
      if (cleanup.status === 'rejected' && expirySubscribers.has(cleanup.handler)) {
        runExpiryCleanup(session, cleanup.handler)
      }
    }
  }
  // A subscriber mounted during cleanup belongs to the same protected exit.
  while ([...session.cleanups.values()].some(cleanup => cleanup.status === 'pending')) {
    await Promise.all([...session.cleanups.values()].map(cleanup => cleanup.promise))
  }
  const failed = [...session.cleanups.values()].find(cleanup => cleanup.status === 'rejected')
  if (failed) throw failed.error
}

export function createAuthExpiredError(message, { data, response } = {}) {
  const error = new Error(message || '无效的会话，或者会话已过期，请重新登录。')
  error.name = 'AuthExpiredError'
  error.code = AUTH_EXPIRED_CODE
  error.status = AUTH_EXPIRED_CODE
  error.data = data
  if (response) error.response = response
  return error
}

export function isAuthExpiredError(error) {
  return [
    error?.code,
    error?.status,
    error?.response?.data?.code,
    error?.response?.status,
  ].some(value => Number(value) === AUTH_EXPIRED_CODE)
}

export function claimReloginPrompt(reloginState) {
  if (!reloginState || reloginState.show) return false
  reloginState.show = true
  return true
}

export function releaseReloginPrompt(reloginState) {
  if (reloginState) reloginState.show = false
}

/**
 * Finish an expired bootstrap navigation without depending on remote logout.
 * The token is already rejected, so local revocation and routing are the
 * authoritative operations; server logout is deliberately fire-and-forget.
 */
export function recoverExpiredBootstrap({
  fullPath,
  clearLocalAuth,
  bestEffortLogout,
  setReloginVisible,
  navigate,
  notify,
}) {
  const loginLocation = createLoginRedirectLocation(fullPath)
  clearLocalAuth()
  setReloginVisible(false)
  navigate(loginLocation)
  notify?.()

  if (bestEffortLogout) {
    Promise.resolve()
      .then(() => bestEffortLogout())
      .catch(() => undefined)
  }
  return loginLocation
}
