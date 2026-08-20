import { normalizeMindMapHyperlink } from './hyperlink'

export const MIND_MAP_ATTACHMENT_MAX_DATA_BYTES = 10 * 1024 * 1024

const MAX_DATA_URL_LENGTH = Math.ceil(MIND_MAP_ATTACHMENT_MAX_DATA_BYTES * 4 / 3) + 1024
const SAFE_DATA_MIME_PATTERNS = [
  /^image\/(?:png|jpe?g|gif|webp|bmp|avif)$/i,
  /^text\/(?:plain|csv|markdown)$/i,
  /^application\/(?:pdf|json|zip|gzip|x-7z-compressed|x-rar-compressed|octet-stream)$/i,
  /^application\/(?:msword|vnd\.ms-excel|vnd\.ms-powerpoint)$/i,
  /^application\/vnd\.openxmlformats-officedocument\.(?:wordprocessingml\.document|spreadsheetml\.sheet|presentationml\.presentation)$/i,
]

function normalizeSafeAttachmentDataUrl(url, maxLength) {
  const match = /^data:([^;,]+)(?:;charset=[^;,]+)?(?:;base64)?,/i.exec(url)
  if (!match || !SAFE_DATA_MIME_PATTERNS.some(pattern => pattern.test(match[1]))) {
    throw new Error('附件 Data URL 类型不受支持')
  }
  if (url.length > maxLength) throw new Error('附件 Data URL 不能超过 10 MB')
  return url
}

export function normalizeMindMapAttachmentUrl(value, options = {}) {
  const url = String(value || '').trim()
  if (!url) return ''
  if (/^data:/i.test(url)) {
    const maxLength = Number(options.maxDataUrlLength) || MAX_DATA_URL_LENGTH
    return normalizeSafeAttachmentDataUrl(url, maxLength)
  }
  const normalized = normalizeMindMapHyperlink(url, options)
  if (/^(?:mailto:|tel:)/i.test(normalized)) {
    throw new Error('附件仅支持 HTTP、HTTPS、同源相对路径或安全 Data URL')
  }
  return normalized
}

export function getSafeMindMapAttachmentUrl(value, options = {}) {
  try {
    return normalizeMindMapAttachmentUrl(value, options)
  } catch {
    return ''
  }
}

export function inferMindMapAttachmentName(value, fallback = '附件') {
  const url = String(value || '').trim()
  if (!url || /^data:/i.test(url)) return fallback
  try {
    const parsed = new URL(url, globalThis.location?.href || 'http://localhost/')
    const segment = parsed.pathname.split('/').filter(Boolean).at(-1)
    return segment ? decodeURIComponent(segment) : fallback
  } catch {
    return fallback
  }
}
