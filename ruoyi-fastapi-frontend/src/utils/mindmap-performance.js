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

// Follow structural changes on the renderer itself, including imports, remote
// trees and AI frames which deliberately do not emit a local data_change.
// A render-start check stops at the threshold, so large diagrams never need a
// full-tree recount just to decide whether to keep performance mode enabled.
export function bindMindmapPerformanceOptions(mindMap, { savedConfig = {} } = {}) {
  const preference = { ...savedConfig }
  let applying = false
  let disposed = false

  const apply = () => {
    if (disposed || applying || mindMap.demonstrate?.isInDemonstrate
      || mindMap.demonstrate?.isEntering) return
    const hasPreference = Object.prototype.hasOwnProperty.call(preference, 'openPerformance')
    const nodeCount = hasPreference ? 0 : countMindmapNodes(
      mindMap.renderer?.renderTree,
      LARGE_MINDMAP_NODE_THRESHOLD,
    )
    const next = resolveMindmapPerformanceOptions({ nodeCount, savedConfig: preference })
    const patch = {}
    for (const key of ['openPerformance', 'openRealtimeRenderOnNodeTextEdit']) {
      if (mindMap.opt[key] !== next[key]) patch[key] = next[key]
    }
    if (!Object.keys(patch).length) return
    applying = true
    try {
      mindMap.updateConfig(patch)
    } finally {
      applying = false
    }
  }

  const onRenderStart = () => {
    // Panning, export and explicit forceLoadNode also emit this event. They do
    // not change the tree and may temporarily force all nodes to be visible.
    if (mindMap.renderer?.isRendering) apply()
  }
  const onConfigChange = (next, previous) => {
    if (applying || disposed) return
    if (next.openPerformance !== previous.openPerformance) {
      preference.openPerformance = Boolean(next.openPerformance)
    }
    apply()
  }
  const dispose = () => {
    if (disposed) return
    disposed = true
    mindMap.off('node_tree_render_start', onRenderStart)
    mindMap.off('after_update_config', onConfigChange)
    mindMap.off('beforeDestroy', dispose)
  }
  mindMap.on('node_tree_render_start', onRenderStart)
  mindMap.on('after_update_config', onConfigChange)
  mindMap.on('beforeDestroy', dispose)
  return dispose
}
