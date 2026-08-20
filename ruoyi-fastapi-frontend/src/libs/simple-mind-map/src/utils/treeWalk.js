function callbackNeedsAncestors(callback) {
  return typeof callback === 'function' && callback.length >= 6
}

// Iterative depth-first traversal. The callback contract intentionally matches
// the original recursive walk helper, including pre/post order and subtree stop.
export const walk = (
  root,
  parent,
  beforeCallback,
  afterCallback,
  isRoot,
  layerIndex = 0,
  index = 0,
  ancestors = [],
) => {
  const needsAncestors = ancestors.length > 0
    || callbackNeedsAncestors(beforeCallback)
    || callbackNeedsAncestors(afterCallback)
  const activePath = new WeakSet()
  const stack = [{
    type: 'enter',
    node: root,
    parent,
    isRoot,
    layerIndex,
    index,
    ancestors,
  }]

  while (stack.length > 0) {
    const frame = stack.pop()
    const node = frame.node
    const isObjectNode = Boolean(node && typeof node === 'object')

    if (frame.type === 'exit') {
      afterCallback?.(
        node,
        frame.parent,
        frame.isRoot,
        frame.layerIndex,
        frame.index,
        frame.ancestors,
      )
      if (isObjectNode) activePath.delete(node)
      continue
    }

    // Invalid legacy graphs may point back to an active ancestor. A shared
    // object in another completed branch remains visitable, matching tree use.
    if (isObjectNode && activePath.has(node)) continue
    if (isObjectNode) activePath.add(node)

    const stop = beforeCallback?.(
      node,
      frame.parent,
      frame.isRoot,
      frame.layerIndex,
      frame.index,
      frame.ancestors,
    )

    stack.push({ ...frame, type: 'exit' })
    const children = !stop && Array.isArray(node?.children) ? node.children : []
    if (children.length === 0) continue

    for (let childIndex = children.length - 1; childIndex >= 0; childIndex -= 1) {
      stack.push({
        type: 'enter',
        node: children[childIndex],
        parent: node,
        isRoot: false,
        layerIndex: frame.layerIndex + 1,
        index: childIndex,
        ancestors: needsAncestors ? [...frame.ancestors, node] : ancestors,
      })
    }
  }
}
