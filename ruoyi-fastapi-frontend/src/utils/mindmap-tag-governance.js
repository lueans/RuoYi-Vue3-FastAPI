export const MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH = 200
export const MAX_MINDMAP_TAG_KEY_LENGTH = 100
export const MAX_MINDMAP_TAG_NAME_LENGTH = 200
export const MAX_MINDMAP_TAG_FIELD_NAME_LENGTH = 100
export const MAX_MINDMAP_TAG_DESCRIPTION_LENGTH = 500
export const MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH = 100
export const MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER = 100000
export const MAX_MINDMAP_TAG_BATCH_SIZE = 100
export const MINDMAP_TAG_STYLE_BOUNDS = Object.freeze({
  fontSize: Object.freeze([10, 24]),
  radius: Object.freeze([0, 20]),
  paddingX: Object.freeze([0, 30]),
})
export const MINDMAP_TAG_STYLE_PLACEMENTS = Object.freeze(['left', 'right', 'top', 'bottom'])
export const MINDMAP_TAG_STYLE_ALIGNS = Object.freeze(['left', 'right', 'top', 'bottom', 'center'])

const TAG_STYLE_COLOR_KEYS = new Set(['fill', 'color'])
const TAG_STYLE_NUMBER_KEYS = new Set(Object.keys(MINDMAP_TAG_STYLE_BOUNDS))
const TAG_STYLE_KEYS = new Set([
  ...TAG_STYLE_COLOR_KEYS,
  ...TAG_STYLE_NUMBER_KEYS,
  'placement',
  'align',
])
const FIELD_STYLE_KEYS = new Set([...TAG_STYLE_NUMBER_KEYS, 'placement', 'align'])

export function validateMindmapTagIdentifier(value, { label = '标签 Key' } = {}) {
  const normalized = String(value ?? '').trim()
  if (!normalized) {
    return { valid: false, value: normalized, message: `${label}不能为空` }
  }
  if (Array.from(normalized).length > MAX_MINDMAP_TAG_KEY_LENGTH) {
    return {
      valid: false,
      value: normalized,
      message: `${label}不能超过 ${MAX_MINDMAP_TAG_KEY_LENGTH} 个字符`,
    }
  }
  if (!/^[A-Za-z0-9_-]+$/u.test(normalized)) {
    return { valid: false, value: normalized, message: `${label}只能包含英文、数字、下划线和连字符` }
  }
  return { valid: true, value: normalized, message: '' }
}

export function validateMindmapTagDisplayName(
  value,
  { label = '标签名称', maxLength = MAX_MINDMAP_TAG_NAME_LENGTH } = {},
) {
  const normalized = String(value ?? '').trim()
  if (!normalized) {
    return { valid: false, value: normalized, message: `${label}不能为空` }
  }
  if (/[\u0000-\u001f\u007f]/u.test(normalized)) {
    return { valid: false, value: normalized, message: `${label}不能包含控制字符` }
  }
  if (Array.from(normalized).length > maxLength) {
    return { valid: false, value: normalized, message: `${label}不能超过 ${maxLength} 个字符` }
  }
  return { valid: true, value: normalized, message: '' }
}

export function validateMindmapTagDescription(value, { label = '标签说明' } = {}) {
  const normalized = String(value ?? '').trim()
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(normalized)) {
    return { valid: false, value: normalized, message: `${label}不能包含不可见控制字符` }
  }
  if (Array.from(normalized).length > MAX_MINDMAP_TAG_DESCRIPTION_LENGTH) {
    return {
      valid: false,
      value: normalized,
      message: `${label}不能超过 ${MAX_MINDMAP_TAG_DESCRIPTION_LENGTH} 个字符`,
    }
  }
  return { valid: true, value: normalized, message: '' }
}

export function validateMindmapTagCategorySortOrder(value) {
  if (!Number.isSafeInteger(value)) {
    return { valid: false, value, message: '分类排序必须是整数' }
  }
  if (Math.abs(value) > MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER) {
    return {
      valid: false,
      value,
      message: `分类排序必须在 -${MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER} 到 ${MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER} 之间`,
    }
  }
  return { valid: true, value, message: '' }
}

export function validateMindmapTagColor(value, { label = '标签颜色', required = false } = {}) {
  const normalized = String(value ?? '').trim()
  if (!normalized) {
    return required
      ? { valid: false, value: '', message: `${label}不能为空` }
      : { valid: true, value: null, message: '' }
  }
  if (normalized.toLowerCase() === 'transparent') {
    return { valid: true, value: 'transparent', message: '' }
  }
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/iu.test(normalized)) {
    return { valid: true, value: normalized.toLowerCase(), message: '' }
  }
  const rgbaMatch = normalized.match(/^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/iu)
    || normalized.match(
      /^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?|\.\d+)\s*\)$/iu,
    )
  if (rgbaMatch) {
    const channels = rgbaMatch.slice(1, 4).map(Number)
    if (channels.some(channel => channel > 255)) {
      return { valid: false, value: normalized, message: `${label}RGB 通道必须在 0 到 255 之间` }
    }
    const alpha = rgbaMatch[4]
    if (alpha !== undefined && Number(alpha) > 1) {
      return { valid: false, value: normalized, message: `${label}透明度必须在 0 到 1 之间` }
    }
    const suffix = alpha === undefined
      ? ''
      : Math.round(Number(alpha) * 255).toString(16).padStart(2, '0')
    return {
      valid: true,
      value: `#${channels.map(channel => channel.toString(16).padStart(2, '0')).join('')}${suffix}`,
      message: '',
    }
  }
  return {
    valid: false,
    value: normalized,
    message: `${label}仅支持透明色、Hex、RGB 或 RGBA 颜色`,
  }
}

function validateMindmapTagStyleNumber(value, key) {
  const labels = { fontSize: '字号', radius: '圆角', paddingX: '水平内边距' }
  const [minimum, maximum] = MINDMAP_TAG_STYLE_BOUNDS[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return { valid: false, value, message: `标签${labels[key]}必须是有限数字` }
  }
  if (value < minimum || value > maximum) {
    return { valid: false, value, message: `标签${labels[key]}必须在 ${minimum} 到 ${maximum} 之间` }
  }
  return { valid: true, value, message: '' }
}

export function validateMindmapTagStyle(style, { fieldStyle = false } = {}) {
  if (style === null || style === undefined) {
    return { valid: true, value: null, message: '' }
  }
  if (!style || typeof style !== 'object' || Array.isArray(style)) {
    return { valid: false, value: null, message: '标签样式必须是对象' }
  }
  const allowedKeys = fieldStyle ? FIELD_STYLE_KEYS : TAG_STYLE_KEYS
  const unknownKeys = Object.keys(style).filter(key => !allowedKeys.has(key)).sort()
  if (unknownKeys.length) {
    return {
      valid: false,
      value: null,
      message: `标签样式包含不支持的字段：${unknownKeys.join('、')}`,
    }
  }

  const value = {}
  for (const [key, raw] of Object.entries(style)) {
    if (raw === null || raw === undefined || raw === '') continue
    if (TAG_STYLE_COLOR_KEYS.has(key)) {
      const color = validateMindmapTagColor(raw, {
        label: key === 'fill' ? '标签背景色' : '标签文字色',
      })
      if (!color.valid) return color
      if (color.value !== null) value[key] = color.value
    } else if (TAG_STYLE_NUMBER_KEYS.has(key)) {
      const number = validateMindmapTagStyleNumber(raw, key)
      if (!number.valid) return number
      value[key] = number.value
    } else if (key === 'placement') {
      if (!MINDMAP_TAG_STYLE_PLACEMENTS.includes(raw)) {
        return { valid: false, value: null, message: '标签位置必须是左、右、上或下' }
      }
      value[key] = raw
    } else if (key === 'align') {
      if (!MINDMAP_TAG_STYLE_ALIGNS.includes(raw)) {
        return { valid: false, value: null, message: '标签对齐方式不合法' }
      }
      value[key] = raw
    }
  }

  if (value.placement && value.align && value.align !== 'center') {
    const validAligns = value.placement === 'top' || value.placement === 'bottom'
      ? ['left', 'right']
      : ['top', 'bottom']
    if (!validAligns.includes(value.align)) {
      return { valid: false, value: null, message: '标签位置与对齐方式不兼容' }
    }
  }
  return { valid: true, value: Object.keys(value).length ? value : null, message: '' }
}

export function validateMindmapTagSearchKeyword(value, { required = false } = {}) {
  if (typeof value !== 'string') {
    return { valid: false, value: '', message: '标签关键词必须为字符串' }
  }
  const normalized = value.trim()
  if (!normalized) {
    return required
      ? { valid: false, value: '', message: '标签名称不能为空' }
      : { valid: true, value: '', message: '' }
  }
  if ([...normalized].some(char => {
    const code = char.codePointAt(0)
    return code < 32 || code === 127
  })) {
    return { valid: false, value: normalized, message: '标签关键词不能包含控制字符' }
  }
  if (Array.from(normalized).length > MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH) {
    return {
      valid: false,
      value: normalized,
      message: `标签关键词不能超过 ${MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH} 个字符`,
    }
  }
  return { valid: true, value: normalized, message: '' }
}

export function isCompatibleTagReplacement(sourceTag, targetTag) {
  if (!sourceTag || !targetTag) return false
  if (Number(sourceTag.id) === Number(targetTag.id)) return false
  if (Number(targetTag.status) !== 0) return false
  const sourceOwnerId = Number(sourceTag.ownerId)
  const targetOwnerId = Number(targetTag.ownerId)
  if (!Number.isSafeInteger(sourceOwnerId) || !Number.isSafeInteger(targetOwnerId)) return false
  if (sourceOwnerId === 0) return targetOwnerId === 0
  return targetOwnerId === 0 || targetOwnerId === sourceOwnerId
}

export function getCreatedResourceId(response, fieldName) {
  const value = Number(response?.data?.[fieldName])
  return Number.isSafeInteger(value) && value > 0 ? value : null
}
