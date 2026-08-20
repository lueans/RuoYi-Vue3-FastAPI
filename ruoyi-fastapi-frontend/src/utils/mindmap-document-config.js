import { normalizeMindmapRuntimeConfigRecord } from './mindmap-local-config.js'

const UNSAFE_KEYS = new Set(['__proto__', 'prototype', 'constructor'])

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function normalizeJsonPrimitive(value, arrayItem = false) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  return arrayItem ? null : undefined
}

function isAncestor(path, value) {
  for (let current = path; current; current = current.parent) {
    if (current.value === value) return true
  }
  return false
}

function cloneJsonValue(value) {
  if (!Array.isArray(value) && !isRecord(value)) return normalizeJsonPrimitive(value)

  const output = Array.isArray(value) ? [] : {}
  const pending = [{
    source: value,
    target: output,
    path: { value, parent: null },
  }]
  while (pending.length) {
    const { source, target, path } = pending.pop()
    const entries = Array.isArray(source)
      ? Array.from(source, (item, index) => [index, item])
      : Object.entries(source)
    for (const [key, item] of entries) {
      if (!Array.isArray(source) && UNSAFE_KEYS.has(key)) continue
      if (Array.isArray(item) || isRecord(item)) {
        if (isAncestor(path, item)) {
          target[key] = null
          continue
        }
        const child = Array.isArray(item) ? [] : {}
        target[key] = child
        pending.push({
          source: item,
          target: child,
          path: { value: item, parent: path },
        })
        continue
      }
      const primitive = normalizeJsonPrimitive(item, Array.isArray(source))
      if (primitive !== undefined) target[key] = primitive
    }
  }
  return output
}

function clampNumber(value, minimum, maximum, fallback) {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.min(maximum, Math.max(minimum, number))
}

function optionalBoundedNumber(value, minimum, maximum) {
  if (value === undefined || value === null) return undefined
  const number = Number(value)
  if (!Number.isFinite(number)) return undefined
  return Math.min(maximum, Math.max(minimum, number))
}

function normalizeColor(value, fallback) {
  return typeof value === 'string' && value.length <= 64 ? value : fallback
}

export function normalizeWatermarkConfig(value) {
  if (!isRecord(value)) return undefined
  const text = typeof value.text === 'string' ? value.text.slice(0, 200) : ''
  if (!text) return { text: '' }
  const textStyle = isRecord(value.textStyle) ? value.textStyle : {}
  return {
    text,
    onlyExport: value.onlyExport === true,
    lineSpacing: clampNumber(value.lineSpacing, 20, 400, 100),
    textSpacing: clampNumber(value.textSpacing, 20, 400, 100),
    angle: clampNumber(value.angle, -90, 90, -30),
    textStyle: {
      color: normalizeColor(textStyle.color, 'rgba(0,0,0,0.1)'),
      fontSize: clampNumber(textStyle.fontSize, 10, 60, 14),
    },
  }
}

export function normalizeMindmapDocumentData(value) {
  return isRecord(value) ? cloneJsonValue(value) : {}
}

export function getMindmapDocumentConfig(documentData) {
  const source = isRecord(documentData?.simpleMindMap?.config)
    ? documentData.simpleMindMap.config
    : {}
  const config = {}
  const watermarkConfig = normalizeWatermarkConfig(source.watermarkConfig)
  const imgTextMargin = optionalBoundedNumber(source.imgTextMargin, 0, 50)
  const textContentMargin = optionalBoundedNumber(source.textContentMargin, 0, 30)
  if (watermarkConfig !== undefined) config.watermarkConfig = watermarkConfig
  if (imgTextMargin !== undefined) config.imgTextMargin = imgTextMargin
  if (textContentMargin !== undefined) config.textContentMargin = textContentMargin
  return config
}

export function updateMindmapDocumentConfig(documentData, patch = {}) {
  const output = normalizeMindmapDocumentData(documentData)
  const simpleMindMap = isRecord(output.simpleMindMap) ? output.simpleMindMap : {}
  const existingConfig = isRecord(simpleMindMap.config) ? simpleMindMap.config : {}
  const nextConfig = { ...existingConfig }

  if (Object.prototype.hasOwnProperty.call(patch, 'watermarkConfig')) {
    nextConfig.watermarkConfig = normalizeWatermarkConfig(patch.watermarkConfig) || { text: '' }
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'imgTextMargin')) {
    nextConfig.imgTextMargin = clampNumber(patch.imgTextMargin, 0, 50, 5)
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'textContentMargin')) {
    nextConfig.textContentMargin = clampNumber(patch.textContentMargin, 0, 30, 2)
  }

  output.simpleMindMap = { ...simpleMindMap, config: nextConfig }
  return output
}

export function getMindmapLocalRuntimeConfig(value) {
  return normalizeMindmapRuntimeConfigRecord(value)
}

export function applyMindmapDocumentConfig(mindMap, documentData) {
  if (!mindMap) return getMindmapDocumentConfig(documentData)
  const config = getMindmapDocumentConfig(documentData)
  const runtimeConfig = {
    imgTextMargin: config.imgTextMargin ?? 5,
    textContentMargin: config.textContentMargin ?? 2,
  }
  const shouldRerender = typeof mindMap.getConfig !== 'function'
    || Object.entries(runtimeConfig).some(
      ([key, value]) => mindMap.getConfig(key) !== value,
    )
  mindMap.updateConfig?.(runtimeConfig)
  mindMap.watermark?.updateWatermark?.(config.watermarkConfig || { text: '' })
  // 节点间距会影响尺寸，只有它确实变化时才重建节点。保存响应和
  // Yjs 元数据回放也会重复应用相同 documentData；无条件 reRender
  // 会清空正在连续录入的活动节点，导致第二次 Tab 后选中标记丢失。
  if (shouldRerender) mindMap.reRender?.()
  return config
}
