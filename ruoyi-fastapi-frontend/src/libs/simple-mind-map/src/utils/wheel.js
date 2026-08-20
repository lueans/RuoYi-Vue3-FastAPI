const DECREASE_DIRECTIONS = new Set(['up', 'left'])
const INCREASE_DIRECTIONS = new Set(['down', 'right'])
const DEFAULT_TOUCHPAD_DELTA_THRESHOLD = 10

const finiteAbsoluteDelta = value => {
  const number = Number(value)
  return Number.isFinite(number) ? Math.abs(number) : 0
}

export const isLikelyTouchpadWheel = (
  event = {},
  threshold = DEFAULT_TOUCHPAD_DELTA_THRESHOLD
) => {
  // Line/page deltas are discrete wheel units. Trackpads normally report
  // pixel deltas, so these modes should never enter the fine-grained branch.
  if (event.deltaMode === 1 || event.deltaMode === 2) return false

  const maxDelta = Math.max(
    finiteAbsoluteDelta(event.deltaX),
    finiteAbsoluteDelta(event.deltaY)
  )
  const normalizedThreshold = Number(threshold)
  const safeThreshold = Number.isFinite(normalizedThreshold)
    && normalizedThreshold > 0
    ? normalizedThreshold
    : DEFAULT_TOUCHPAD_DELTA_THRESHOLD
  return maxDelta > 0 && maxDelta <= safeThreshold
}

// Wheel events report vertical directions before horizontal directions. Keep
// that priority for diagonal gestures while also supporting horizontal-only
// mouse wheels, which the previous `UP || LEFT` expression could never do.
export const resolveWheelZoomDirection = dirs => {
  const directions = Array.isArray(dirs) ? dirs : []
  for (let index = 0; index < directions.length; index += 1) {
    const direction = directions[index]
    if (DECREASE_DIRECTIONS.has(direction)) return -1
    if (INCREASE_DIRECTIONS.has(direction)) return 1
  }
  return 0
}
