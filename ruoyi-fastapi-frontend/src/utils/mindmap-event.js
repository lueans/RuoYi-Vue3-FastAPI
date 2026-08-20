export function isCurrentMindmapEventSource(sourceMindMap, currentMindMap) {
  return Boolean(currentMindMap) && (!sourceMindMap || sourceMindMap === currentMindMap)
}

export function resolveMindmapEventNodes(nodeList, sourceMindMap, currentMindMap) {
  if (!isCurrentMindmapEventSource(sourceMindMap, currentMindMap)) return null
  if (!Array.isArray(nodeList)) return []

  const seen = new Set()
  const nodes = []
  nodeList.forEach(node => {
    if (!node || (typeof node !== 'object' && typeof node !== 'function')) return
    if (node.mindMap && node.mindMap !== currentMindMap) return
    if (seen.has(node)) return
    seen.add(node)
    nodes.push(node)
  })
  return nodes
}
