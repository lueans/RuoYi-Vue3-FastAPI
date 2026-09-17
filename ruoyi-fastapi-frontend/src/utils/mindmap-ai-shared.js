export function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function isPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

export function isBoundedText(value, maxLength) {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= maxLength
    && value.trim() === value
    && !/[\u0000-\u001f\u007f]/.test(value)
}

export function normalizeOwnerUserId(value) {
  if (Number.isSafeInteger(value) && value > 0) return String(value)
  if (isBoundedText(value, 128)) return value
  return null
}

export function stableJsonValue(value) {
  if (Array.isArray(value)) return value.map(stableJsonValue)
  if (value === null || typeof value !== 'object') return value
  return Object.keys(value).sort().reduce((output, key) => {
    output[key] = stableJsonValue(value[key])
    return output
  }, {})
}
