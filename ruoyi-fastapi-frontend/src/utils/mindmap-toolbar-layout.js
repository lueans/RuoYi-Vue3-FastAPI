export function selectLargestFittingToolbarCount(candidateWidths, containerWidth) {
  const availableWidth = Number(containerWidth)
  if (!Array.isArray(candidateWidths) || !Number.isFinite(availableWidth) || availableWidth < 0) {
    return 0
  }

  let fittingCount = 0
  candidateWidths.forEach((candidateWidth, candidateCount) => {
    const width = Number(candidateWidth)
    if (Number.isFinite(width) && width >= 0 && width <= availableWidth) {
      fittingCount = candidateCount
    }
  })
  return fittingCount
}
