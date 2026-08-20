const isRecord = value => Boolean(
  value && typeof value === 'object' && !Array.isArray(value)
)

const finiteNumberOr = (value, fallback) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export const normalizeViewScale = (value, fallback = null) => {
  const number = Number(value)
  if (Number.isFinite(number) && number > 0) return number
  const fallbackNumber = Number(fallback)
  return Number.isFinite(fallbackNumber) && fallbackNumber > 0
    ? fallbackNumber
    : null
}

export const normalizeViewCoordinate = (value, fallback = 0) => (
  finiteNumberOr(value, finiteNumberOr(fallback, 0))
)

export const calculateViewScaleAroundPoint = (
  currentState,
  nextScale,
  center
) => {
  const scale = normalizeViewScale(nextScale)
  if (scale === null) return null
  const previousScale = normalizeViewScale(currentState?.scale, 1)
  const x = normalizeViewCoordinate(currentState?.x)
  const y = normalizeViewCoordinate(currentState?.y)
  const centerX = normalizeViewCoordinate(center?.x)
  const centerY = normalizeViewCoordinate(center?.y)
  const ratio = 1 - scale / previousScale

  return {
    scale,
    x: x + (centerX - x) * ratio,
    y: y + (centerY - y) * ratio
  }
}

export const calculateViewFit = ({
  contentRect,
  viewportRect,
  transform,
  state,
  padding = 0,
  enlarge = false
} = {}) => {
  if (!isRecord(contentRect) || !isRecord(viewportRect)) return null

  const viewportWidth = finiteNumberOr(viewportRect.width, 0)
  const viewportHeight = finiteNumberOr(viewportRect.height, 0)
  const screenWidth = finiteNumberOr(contentRect.width, 0)
  const screenHeight = finiteNumberOr(contentRect.height, 0)
  const scaleX = normalizeViewScale(transform?.scaleX)
  const scaleY = normalizeViewScale(transform?.scaleY)
  if (
    viewportWidth <= 0
    || viewportHeight <= 0
    || screenWidth <= 0
    || screenHeight <= 0
    || scaleX === null
    || scaleY === null
  ) {
    return null
  }

  const requestedPadding = Math.max(finiteNumberOr(padding, 0), 0)
  const maxPadding = Math.max(
    0,
    (Math.min(viewportWidth, viewportHeight) - 1) / 2
  )
  const safePadding = Math.min(requestedPadding, maxPadding)
  const availableWidth = viewportWidth - safePadding * 2
  const availableHeight = viewportHeight - safePadding * 2
  const contentWidth = screenWidth / scaleX
  const contentHeight = screenHeight / scaleY
  if (
    !Number.isFinite(contentWidth)
    || !Number.isFinite(contentHeight)
    || contentWidth <= 0
    || contentHeight <= 0
  ) {
    return null
  }

  const scale = !enlarge
    && contentWidth <= availableWidth
    && contentHeight <= availableHeight
    ? 1
    : Math.min(
      availableWidth / contentWidth,
      availableHeight / contentHeight
    )
  const normalizedScale = normalizeViewScale(scale)
  if (normalizedScale === null) return null

  const viewportLeft = normalizeViewCoordinate(viewportRect.left)
  const viewportTop = normalizeViewCoordinate(viewportRect.top)
  const translateX = normalizeViewCoordinate(transform?.translateX, state?.x)
  const translateY = normalizeViewCoordinate(transform?.translateY, state?.y)
  const viewX = normalizeViewCoordinate(state?.x, translateX)
  const viewY = normalizeViewCoordinate(state?.y, translateY)
  const screenLeft = normalizeViewCoordinate(contentRect.x) - viewportLeft
  const screenTop = normalizeViewCoordinate(contentRect.y) - viewportTop
  const contentLeft = (screenLeft - translateX) / scaleX
  const contentTop = (screenTop - translateY) / scaleY
  const targetLeft = contentLeft * normalizedScale + viewX
  const targetTop = contentTop * normalizedScale + viewY
  const targetWidth = contentWidth * normalizedScale
  const targetHeight = contentHeight * normalizedScale
  const offsetX = -targetLeft
    + safePadding
    + (availableWidth - targetWidth) / 2
  const offsetY = -targetTop
    + safePadding
    + (availableHeight - targetHeight) / 2
  if (!Number.isFinite(offsetX) || !Number.isFinite(offsetY)) return null

  return {
    scale: normalizedScale,
    offsetX,
    offsetY,
    padding: safePadding,
    availableWidth,
    availableHeight
  }
}

export const normalizeViewTransformData = (viewData, fallback = {}) => {
  if (!isRecord(viewData)) return null

  const state = isRecord(viewData.state) ? viewData.state : {}
  const transform = isRecord(viewData.transform) ? viewData.transform : {}
  const translate = Array.isArray(transform.translate)
    ? transform.translate
    : []
  const scale = normalizeViewScale(
    state.scale,
    normalizeViewScale(
      transform.scaleX,
      normalizeViewScale(transform.scaleY, fallback.scale ?? 1)
    )
  )
  const x = normalizeViewCoordinate(
    state.x,
    normalizeViewCoordinate(
      transform.translateX,
      normalizeViewCoordinate(translate[0], fallback.x)
    )
  )
  const y = normalizeViewCoordinate(
    state.y,
    normalizeViewCoordinate(
      transform.translateY,
      normalizeViewCoordinate(translate[1], fallback.y)
    )
  )
  const sx = normalizeViewCoordinate(state.sx, x)
  const sy = normalizeViewCoordinate(state.sy, y)

  return {
    state: { scale, x, y, sx, sy },
    transform: {
      origin: [0, 0],
      scale,
      translate: [x, y]
    }
  }
}
