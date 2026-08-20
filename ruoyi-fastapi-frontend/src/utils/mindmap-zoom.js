const DEFAULT_MIN_ZOOM_PERCENT = 20
const DEFAULT_MAX_ZOOM_PERCENT = 400
const WHEEL_LINE_PIXELS = 16
const WHEEL_PAGE_PIXELS = 800
const MAX_WHEEL_DELTA_PIXELS = 100
const WHEEL_ZOOM_SENSITIVITY = 0.002

function positiveNumberOr(value, fallback) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : fallback
}

export function getMindmapScaleBounds(options = {}) {
  const minPercent = positiveNumberOr(options.minZoomRatio, DEFAULT_MIN_ZOOM_PERCENT)
  const configuredMax = Number(options.maxZoomRatio)
  const maxPercent = configuredMax === -1
    ? Infinity
    : Math.max(positiveNumberOr(configuredMax, DEFAULT_MAX_ZOOM_PERCENT), minPercent)

  return {
    minScale: minPercent / 100,
    maxScale: maxPercent / 100,
  }
}

export function clampMindmapScale(scale, options = {}) {
  const numericScale = Number(scale)
  if (!Number.isFinite(numericScale)) return null
  const { minScale, maxScale } = getMindmapScaleBounds(options)
  return Math.min(Math.max(numericScale, minScale), maxScale)
}

export function shouldZoomMindmapWheel(event = {}, options = {}) {
  if (event.ctrlKey || event.metaKey) return true
  return options.mousewheelAction !== 'move'
}

export function normalizeMindmapWheelDelta(event = {}) {
  const deltaY = Number(event.deltaY)
  const deltaX = Number(event.deltaX)
  let delta = Number.isFinite(deltaY) && deltaY !== 0
    ? deltaY
    : (Number.isFinite(deltaX) ? deltaX : 0)

  const deltaMode = Number(event.deltaMode)
  if (deltaMode === 1) delta *= WHEEL_LINE_PIXELS
  if (deltaMode === 2) delta *= WHEEL_PAGE_PIXELS

  return Math.min(
    Math.max(delta, -MAX_WHEEL_DELTA_PIXELS),
    MAX_WHEEL_DELTA_PIXELS
  )
}

export function calculateMindmapWheelScale(
  currentScale,
  event = {},
  options = {}
) {
  const numericScale = Number(currentScale)
  if (!Number.isFinite(numericScale) || numericScale <= 0) return null

  const delta = normalizeMindmapWheelDelta(event)
  if (delta === 0) return clampMindmapScale(numericScale, options)
  const direction = options.mousewheelZoomActionReverse === false ? -1 : 1
  const factor = Math.exp(-delta * WHEEL_ZOOM_SENSITIVITY * direction)
  return clampMindmapScale(numericScale * factor, options)
}
