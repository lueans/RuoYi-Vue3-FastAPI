export const MINDMAP_LOCAL_CONFIG_SCHEMA_VERSION = 1
export const MINDMAP_RUNTIME_CONFIG_SCHEMA_VERSION = 1

export const DEFAULT_MINDMAP_LOCAL_CONFIG = Object.freeze({
  isDark: false,
  isZenMode: false,
  openNodeRichText: true,
  isShowScrollbar: false,
  useLeftKeySelectionRightKeyDrag: true,
  enableAi: false,
})

const LOCAL_CONFIG_KEYS = Object.freeze(Object.keys(DEFAULT_MINDMAP_LOCAL_CONFIG))
const RUNTIME_BOOLEAN_KEYS = Object.freeze([
  'openPerformance',
  'enableFreeDrag',
  'enableAutoEnterTextEditWhenKeydown',
  'alwaysShowExpandBtn',
  'isLimitMindMapInCanvas',
])
const MOUSEWHEEL_ACTIONS = new Set(['zoom', 'move'])
const CREATE_NODE_BEHAVIORS = new Set(['default', 'notActive', 'activeOnly'])
const SAFE_RGB_COLOR_PATTERN = /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key)

function isRecord(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

export function normalizeMindmapLocalConfigPatch(value) {
  if (!isRecord(value)) return {}
  const result = {}
  for (const key of LOCAL_CONFIG_KEYS) {
    if (typeof value[key] === 'boolean') result[key] = value[key]
  }
  return result
}

function isVersionedRecord(value) {
  return (
    isRecord(value)
    && Number.isSafeInteger(value.schemaVersion)
    && value.schemaVersion >= 1
    && isRecord(value.values)
  )
}

function isLegacyFullSnapshot(value) {
  return isRecord(value) && LOCAL_CONFIG_KEYS.every(key => hasOwn(value, key))
}

export function normalizeMindmapLocalConfigRecord(value) {
  const versioned = isVersionedRecord(value)
  const source = versioned ? value.values : value
  const patch = normalizeMindmapLocalConfigPatch(source)

  // 旧实现会保存所有默认字段；仅对这种可辨认的完整快照迁移旧鼠标模式默认值。
  // 差异记录中的 false 代表用户主动选择，不能在每次启动时重复删除。
  if (
    !versioned
    && isLegacyFullSnapshot(source)
    && source.useLeftKeySelectionRightKeyDrag === false
  ) {
    delete patch.useLeftKeySelectionRightKeyDrag
  }

  return { ...DEFAULT_MINDMAP_LOCAL_CONFIG, ...patch }
}

export function createMindmapLocalConfigRecord(value) {
  const patch = normalizeMindmapLocalConfigPatch(value)
  const values = {}
  for (const key of LOCAL_CONFIG_KEYS) {
    if (
      hasOwn(patch, key)
      && patch[key] !== DEFAULT_MINDMAP_LOCAL_CONFIG[key]
    ) {
      values[key] = patch[key]
    }
  }
  return {
    schemaVersion: MINDMAP_LOCAL_CONFIG_SCHEMA_VERSION,
    values,
  }
}

function normalizeBoundedNumber(value, minimum, maximum) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return Math.min(maximum, Math.max(minimum, value))
}

function normalizeRainbowColor(value) {
  if (typeof value !== 'string' || value.length > 64) return undefined
  const match = value.match(SAFE_RGB_COLOR_PATTERN)
  if (!match) return undefined
  const channels = match.slice(1).map(Number)
  if (channels.some(channel => channel > 255)) return undefined
  return `rgb(${channels.join(', ')})`
}

function normalizeRainbowLinesConfig(value) {
  if (!isRecord(value) || typeof value.open !== 'boolean') return undefined
  if (!value.open) return { open: false }
  const colorsList = Array.isArray(value.colorsList)
    ? value.colorsList
      .slice(0, 16)
      .map(normalizeRainbowColor)
      .filter(Boolean)
    : []
  return colorsList.length ? { open: true, colorsList } : { open: true }
}

export function normalizeMindmapRuntimeConfigPatch(value) {
  if (!isRecord(value)) return {}
  const result = {}
  for (const key of RUNTIME_BOOLEAN_KEYS) {
    if (typeof value[key] === 'boolean') result[key] = value[key]
  }
  if (MOUSEWHEEL_ACTIONS.has(value.mousewheelAction)) {
    result.mousewheelAction = value.mousewheelAction
  }
  if (CREATE_NODE_BEHAVIORS.has(value.createNewNodeBehavior)) {
    result.createNewNodeBehavior = value.createNewNodeBehavior
  }
  for (const key of ['outerFramePaddingX', 'outerFramePaddingY']) {
    const number = normalizeBoundedNumber(value[key], 0, 100)
    if (number !== undefined) result[key] = number
  }
  const rainbowLinesConfig = normalizeRainbowLinesConfig(value.rainbowLinesConfig)
  if (rainbowLinesConfig !== undefined) {
    result.rainbowLinesConfig = rainbowLinesConfig
  }
  return result
}

export function normalizeMindmapRuntimeConfigRecord(value) {
  const source = isVersionedRecord(value) ? value.values : value
  return normalizeMindmapRuntimeConfigPatch(source)
}

export function createMindmapRuntimeConfigRecord(value) {
  return {
    schemaVersion: MINDMAP_RUNTIME_CONFIG_SCHEMA_VERSION,
    values: normalizeMindmapRuntimeConfigPatch(value),
  }
}
