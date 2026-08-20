import { stringifyJsonValueIterative } from '../libs/simple-mind-map/src/utils/jsonClone.js'

/**
 * 将空请求正文规范化为后端可接收的 JSON 对象。
 *
 * @param {*} payload 原始请求正文
 * @returns {*} 规范化正文
 */
export function normalizeRequestPayload(payload) {
  if (payload === undefined || payload === null) return {}
  return payload
}

/**
 * 使用栈安全的原始 JSON 语义序列化任意值，不执行请求空值规范化。
 *
 * @param {*} value 原始 JSON 值
 * @returns {string|undefined} JSON 文本
 */
export function stringifyRequestJsonValue(value) {
  return stringifyJsonValueIterative(value)
}

/**
 * 使用栈安全的 JSON 语义序列化请求正文。
 *
 * @param {*} payload 原始请求正文
 * @returns {string|undefined} JSON 文本
 */
export function stringifyRequestPayload(payload) {
  return stringifyRequestJsonValue(normalizeRequestPayload(payload))
}

/**
 * 克隆请求配置中的可变字段，供传输密钥刷新后恢复原始请求。
 *
 * @param {*} value 待克隆值
 * @returns {*} 克隆结果
 */
export function cloneRequestPayload(value) {
  if (value === undefined || value === null) return value
  if (typeof globalThis.structuredClone === 'function') {
    try {
      return globalThis.structuredClone(value)
    } catch {
      // 部分浏览器的原生结构化克隆仍会在合法深层 JSON 上耗尽调用栈。
      // 继续走文档序列化降级，保证密钥刷新重试保留原始正文。
    }
  }
  if (typeof value === 'object') {
    const serialized = stringifyJsonValueIterative(value)
    if (serialized === undefined) throw new TypeError('Request payload is not JSON serializable')
    return JSON.parse(serialized)
  }
  return value
}
