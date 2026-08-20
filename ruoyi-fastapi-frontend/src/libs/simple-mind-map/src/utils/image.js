export const MIND_MAP_IMAGE_MAX_BYTES = 5 * 1024 * 1024
export const MIND_MAP_IMAGE_URL_MAX_LENGTH = 4096

const MAX_DATA_URL_LENGTH =
  Math.ceil((MIND_MAP_IMAGE_MAX_BYTES * 4) / 3) + 1024
const ALLOWED_REMOTE_PROTOCOLS = new Set(['http:', 'https:'])
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001F\u007F]/
const IMAGE_DATA_URL_PATTERN =
  /^data:image\/[a-z0-9.+-]+(?:;charset=[^;,]+)?(?:;base64)?,/i

function formatMegabytes(bytes) {
  return Math.max(1, Math.round(bytes / 1024 / 1024))
}

export function normalizeMindMapImageUrl(value, options = {}) {
  const url = String(value || '').trim()
  if (!url) throw new Error('请输入图片地址')
  if (CONTROL_CHARACTER_PATTERN.test(url)) {
    throw new Error('图片地址包含非法控制字符')
  }

  if (/^data:/i.test(url)) {
    if (!IMAGE_DATA_URL_PATTERN.test(url)) {
      throw new Error('仅支持图片 Data URL')
    }
    const maxLength =
      Number(options.maxDataUrlLength) || MAX_DATA_URL_LENGTH
    if (url.length > maxLength) {
      throw new Error(
        `图片大小不能超过 ${formatMegabytes(MIND_MAP_IMAGE_MAX_BYTES)} MB`
      )
    }
    return url
  }

  const maxLength =
    Number(options.maxLength) || MIND_MAP_IMAGE_URL_MAX_LENGTH
  if (url.length > maxLength) {
    throw new Error(`图片地址不能超过 ${maxLength} 个字符`)
  }

  let parsed
  try {
    parsed = new URL(
      url,
      options.baseUrl || globalThis.location?.href || 'http://localhost/'
    )
  } catch {
    throw new Error('图片地址格式不正确')
  }
  if (!ALLOWED_REMOTE_PROTOCOLS.has(parsed.protocol)) {
    throw new Error('图片地址仅支持 HTTP、HTTPS 或同源相对路径')
  }
  if (parsed.username || parsed.password) {
    throw new Error('图片地址不能包含账号或密码')
  }
  return url
}

export function getSafeMindMapImageUrl(value, options = {}) {
  try {
    return normalizeMindMapImageUrl(value, options)
  } catch {
    return ''
  }
}
