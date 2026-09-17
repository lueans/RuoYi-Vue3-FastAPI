import { createLoginRedirectLocation } from './login-redirect.js'

export const AUTH_EXPIRED_CODE = 401

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
