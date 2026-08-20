export const MINDMAP_PREVIEW_FEATURES = Object.freeze({
  associativeLine: 'associativeLine',
  outerFrame: 'outerFrame',
  formula: 'formula',
  mindMapLayoutPro: 'mindMapLayoutPro',
})

export function detectMindmapDocumentFeatures({ root, layout } = {}) {
  const features = new Set()
  if (layout === 'mindMap') {
    features.add(MINDMAP_PREVIEW_FEATURES.mindMapLayoutPro)
  }
  if (!root || typeof root !== 'object') return [...features]

  const pending = [root]
  const visited = new Set()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    if (Array.isArray(node.associativeLineTargets) && node.associativeLineTargets.length) {
      features.add(MINDMAP_PREVIEW_FEATURES.associativeLine)
    }
    if (node.outerFrame && typeof node.outerFrame === 'object') {
      features.add(MINDMAP_PREVIEW_FEATURES.outerFrame)
    }
    if (
      typeof node.text === 'string'
      && node.text.includes('ql-formula')
    ) {
      features.add(MINDMAP_PREVIEW_FEATURES.formula)
    }
    Object.values(node).forEach(value => {
      if (value && typeof value === 'object') pending.push(value)
    })
  }
  return [...features].sort()
}

// 保留既有公开名称，预览和编辑器共用同一份文档能力检测逻辑。
export const detectMindmapPreviewFeatures = detectMindmapDocumentFeatures
