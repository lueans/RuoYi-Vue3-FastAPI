export const LARGE_MINDMAP_NODE_THRESHOLD = 1000

export function countMindmapNodes(root, stopAt = Number.POSITIVE_INFINITY) {
  if (!root || typeof root !== 'object') return 0
  const pending = [root]
  const visited = new WeakSet()
  let count = 0
  while (pending.length > 0 && count < stopAt) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    count += 1
    if (Array.isArray(node.children)) pending.push(...node.children)
  }
  return count
}

export function resolveMindmapPerformanceOptions({ root, nodeCount, savedConfig = {} }) {
  const reportedCount = Number(nodeCount)
  const treeNodeCount = countMindmapNodes(root)
  const resolvedNodeCount = Number.isInteger(reportedCount) && reportedCount > 0
    ? Math.max(reportedCount, treeNodeCount)
    : treeNodeCount
  const hasExplicitPreference = Object.prototype.hasOwnProperty.call(savedConfig, 'openPerformance')
  const openPerformance = hasExplicitPreference
    ? Boolean(savedConfig.openPerformance)
    : resolvedNodeCount >= LARGE_MINDMAP_NODE_THRESHOLD

  return {
    nodeCount: resolvedNodeCount,
    openPerformance,
    // 组件文档明确说明实时文字重排在大图下会卡顿；性能模式下强制关闭。
    openRealtimeRenderOnNodeTextEdit: openPerformance
      ? false
      : savedConfig.openRealtimeRenderOnNodeTextEdit !== false,
  }
}
