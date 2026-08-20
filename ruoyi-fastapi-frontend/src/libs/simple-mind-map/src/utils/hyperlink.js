export const MIND_MAP_HYPERLINK_MAX_LENGTH = 4096

const WEB_PROTOCOLS = new Set(['http:', 'https:'])
const SPECIAL_PROTOCOLS = new Set(['mailto:', 'tel:'])
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001F\u007F]/

function validateMailto(url) {
  const target = url.slice('mailto:'.length).split('?')[0]
  if (!target || !target.includes('@') || /%0d|%0a/i.test(url)) {
    throw new Error('邮箱链接格式不正确')
  }
}

function validateTelephone(url) {
  const target = url.slice('tel:'.length)
  if (!/^[+()\d\s.-]{3,64}$/.test(target)) {
    throw new Error('电话链接格式不正确')
  }
}

export function normalizeMindMapHyperlink(value, options = {}) {
  const link = String(value || '').trim()
  if (!link) return ''
  const maxLength = Number(options.maxLength) || MIND_MAP_HYPERLINK_MAX_LENGTH
  if (link.length > maxLength) throw new Error(`链接地址不能超过 ${maxLength} 个字符`)
  if (CONTROL_CHARACTER_PATTERN.test(link)) throw new Error('链接地址包含非法控制字符')

  const isRelative = /^(?:\/(?!\/)|\.{1,2}\/|#|\?)/.test(link)
  if (isRelative) {
    try {
      new URL(link, options.baseUrl || globalThis.location?.href || 'http://localhost/')
    } catch {
      throw new Error('相对链接格式不正确')
    }
    return link
  }

  let parsed
  try {
    parsed = new URL(link)
  } catch {
    throw new Error('链接地址必须包含协议，或使用 /、./、../、# 开头的相对路径')
  }

  if (WEB_PROTOCOLS.has(parsed.protocol)) {
    if (parsed.username || parsed.password) throw new Error('链接地址不能包含账号或密码')
    return parsed.href
  }
  if (!SPECIAL_PROTOCOLS.has(parsed.protocol)) {
    throw new Error('链接仅支持 HTTP、HTTPS、邮箱、电话或同源相对路径')
  }
  if (parsed.protocol === 'mailto:') validateMailto(link)
  if (parsed.protocol === 'tel:') validateTelephone(link)
  return link
}

export function getSafeMindMapHyperlink(value, options = {}) {
  try {
    return normalizeMindMapHyperlink(value, options)
  } catch {
    return ''
  }
}
