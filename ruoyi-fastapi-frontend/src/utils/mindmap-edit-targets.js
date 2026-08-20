function isMindmapEditTarget(node) {
  return Boolean(node && typeof node.getData === 'function')
}

export function captureMindmapEditTargets(activeNodes, appointedNode = null) {
  const candidates = isMindmapEditTarget(appointedNode)
    ? [appointedNode]
    : (Array.isArray(activeNodes) ? activeNodes : [])
  const seen = new Set()
  const targets = []

  for (const node of candidates) {
    if (!isMindmapEditTarget(node) || seen.has(node)) continue
    seen.add(node)
    targets.push(node)
  }

  return Object.freeze(targets)
}
