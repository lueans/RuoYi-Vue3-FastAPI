import { stringifyRequestJsonValue } from './requestPayload.js'

const WRITE_METHODS = new Set(['post', 'put', 'patch'])
export const MAX_REPEAT_SUBMIT_PAYLOAD_BYTES = 5 * 1024 * 1024
const UNSUPPORTED_BODY_TAGS = new Set([
  '[object ArrayBuffer]',
  '[object Blob]',
  '[object File]',
  '[object FormData]',
  '[object ReadableStream]',
])

const normalizeMethod = method => String(method || 'get').toLowerCase()

const isUnsupportedBody = value => {
  if (value === null || value === undefined || typeof value !== 'object') return false
  if (ArrayBuffer.isView(value)) return true
  return UNSUPPORTED_BODY_TAGS.has(Object.prototype.toString.call(value))
}

const bytesToHex = value => Array.from(new Uint8Array(value), byte => (
  byte.toString(16).padStart(2, '0')
)).join('')

/**
 * 判断请求方法是否需要参与重复提交保护。
 *
 * @param {string} method HTTP 方法
 * @returns {boolean} 是否为有正文的写请求
 */
export const isRepeatSubmitMethod = method => WRITE_METHODS.has(normalizeMethod(method))

/**
 * 为请求正文创建紧凑指纹。二进制和流式正文不适合 JSON 指纹，返回 null。
 *
 * @param {*} payload 请求正文
 * @returns {Promise<{fingerprint: string, byteLength: number}|null>} 指纹和 UTF-8 字节数
 */
export async function fingerprintRequestPayload(payload) {
  if (isUnsupportedBody(payload)) return null

  let serialized
  let payloadKind
  if (Object.prototype.toString.call(payload) === '[object URLSearchParams]') {
    serialized = payload.toString()
    payloadKind = 'url-search-params'
  } else if (payload === undefined) {
    serialized = ''
    payloadKind = 'undefined'
  } else {
    serialized = stringifyRequestJsonValue(payload)
    payloadKind = 'json'
  }
  if (serialized === undefined) return null

  const subtle = globalThis.crypto?.subtle
  if (!subtle || typeof globalThis.TextEncoder !== 'function') return null
  // 先用 UTF-16 长度快速拒绝明显超限的正文，再只分配一份 UTF-8 摘要输入。
  // 非 ASCII 正文需要编码后再按真实字节数复核。
  if (serialized.length > MAX_REPEAT_SUBMIT_PAYLOAD_BYTES) return null
  const encoder = new TextEncoder()
  const prefixBytes = encoder.encode(`${payloadKind}\0`)
  const digestInput = encoder.encode(`${payloadKind}\0${serialized}`)
  const byteLength = digestInput.byteLength - prefixBytes.byteLength
  if (byteLength > MAX_REPEAT_SUBMIT_PAYLOAD_BYTES) return null
  const digest = await subtle.digest('SHA-256', digestInput)
  return {
    fingerprint: `sha256:${bytesToHex(digest)}`,
    byteLength,
  }
}

/**
 * 创建可安全写入 sessionStorage 的重复提交记录。
 *
 * @param {Object} config Axios 请求配置
 * @param {number} now 当前时间戳
 * @returns {Promise<Object|null>} 紧凑记录；不支持的正文返回 null
 */
export async function createRepeatSubmitRecord(config, now = Date.now()) {
  const payloadFingerprint = await fingerprintRequestPayload(config?.data)
  if (!payloadFingerprint) return null
  return {
    url: String(config?.url || ''),
    method: normalizeMethod(config?.method),
    fingerprint: payloadFingerprint.fingerprint,
    byteLength: payloadFingerprint.byteLength,
    time: now,
  }
}

/**
 * 判断两个紧凑记录是否属于时间窗内的同一次提交。
 *
 * @param {Object} previous 上一次记录
 * @param {Object} current 当前记录
 * @param {number} interval 防重时间窗（毫秒）
 * @returns {boolean} 是否重复
 */
export function isDuplicateRepeatSubmit(previous, current, interval) {
  if (!previous || !current) return false
  const elapsed = Number(current.time) - Number(previous.time)
  const normalizedInterval = Number(interval)
  return (
    Number.isFinite(elapsed)
    && elapsed >= 0
    && Number.isFinite(normalizedInterval)
    && normalizedInterval > 0
    && elapsed < normalizedInterval
    && previous.url === current.url
    && previous.method === current.method
    && previous.byteLength === current.byteLength
    && previous.fingerprint === current.fingerprint
  )
}
