const LOGIN_REDIRECT_ORIGIN = 'http://router.local'
const DEFAULT_LOGIN_REDIRECT = '/'
const MAX_LOGIN_REDIRECT_LENGTH = 4096

function firstQueryValue(value) {
  return Array.isArray(value) ? value[0] : value
}
/**
 * 只接受站内绝对路由，避免登录跳转被外部地址或协议相对地址劫持。
 */
export function normalizeLoginRedirect(value, fallback = DEFAULT_LOGIN_REDIRECT) {
  const candidate = firstQueryValue(value)
  if (
    typeof candidate !== 'string'
    || !candidate.startsWith('/')
    || candidate.startsWith('//')
    || candidate.includes('\\')
    || candidate.length > MAX_LOGIN_REDIRECT_LENGTH
  ) {
    return fallback
  }

  try {
    const target = new URL(candidate, LOGIN_REDIRECT_ORIGIN)
    if (target.origin !== LOGIN_REDIRECT_ORIGIN) return fallback
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return fallback
  }
}

/**
 * 使用路由对象生成登录地址，让 Vue Router 负责对完整 fullPath 编码。
 * 直接拼接字符串会把目标地址中的 `&` 当成登录页自身的查询参数。
 */
export function createLoginRedirectLocation(fullPath) {
  return {
    path: '/login',
    query: { redirect: normalizeLoginRedirect(fullPath) },
  }
}

/**
 * 还原登录后的完整站内地址，并兼容旧版本已经拆散的登录链接：
 * `/login?redirect=/mindmap/edit&id=122`。
 */
export function resolvePostLoginLocation(query = {}) {
  const target = new URL(
    normalizeLoginRedirect(query?.redirect),
    LOGIN_REDIRECT_ORIGIN,
  )

  for (const [key, rawValue] of Object.entries(query || {})) {
    if (key === 'redirect' || target.searchParams.has(key)) continue
    const values = Array.isArray(rawValue) ? rawValue : [rawValue]
    for (const value of values) {
      if (value === undefined || value === null) continue
      target.searchParams.append(key, String(value))
    }
  }

  return `${target.pathname}${target.search}${target.hash}`
}
