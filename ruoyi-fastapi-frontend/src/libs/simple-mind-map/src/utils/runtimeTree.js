const isObjectNode = node => Boolean(node && typeof node === 'object')

const getExpandedChildren = node => {
  const isNodeExpandedForLayout = node?.mindMap?.renderer?.isNodeExpandedForLayout
  const expanded = typeof isNodeExpandedForLayout === 'function'
    ? isNodeExpandedForLayout.call(node.mindMap.renderer, node)
    : node?.getData?.('expand') !== false
  if (!expanded) return []
  return Array.isArray(node?.children) ? node.children : []
}

// Synchronous rendering used to recurse through MindMapNode.render. Keep the
// visible-node preorder and defer insertion finalizers until every node has
// rendered, so the renderer completion callback still runs before an inserted
// node enters text editing on the common append path.
export const renderRuntimeTreeSync = (
  root,
  renderNode,
  finishNode,
  onComplete = () => {}
) => {
  const visited = new WeakSet()
  const postOrder = []
  const stack = [{ type: 'enter', node: root }]

  while (stack.length > 0) {
    const frame = stack.pop()
    const node = frame.node

    if (frame.type === 'exit') {
      postOrder.push(node)
      continue
    }

    if (isObjectNode(node) && visited.has(node)) continue
    if (isObjectNode(node)) visited.add(node)

    renderNode(node)
    stack.push({ type: 'exit', node })
    const children = getExpandedChildren(node)
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push({ type: 'enter', node: children[index] })
    }
  }

  onComplete()
  postOrder.forEach(node => finishNode(node))
}

// Stable preorder traversal for runtime-node teardown. Returning false from
// the visitor prunes that node's subtree, matching MindMapNode.remove's old
// early return when its SVG group was already absent.
export const visitRuntimeSubtree = (root, visitNode) => {
  const visited = new WeakSet()
  const stack = [root]

  while (stack.length > 0) {
    const node = stack.pop()
    if (isObjectNode(node) && visited.has(node)) continue
    if (isObjectNode(node)) visited.add(node)

    if (visitNode(node) === false) continue
    const children = Array.isArray(node?.children) ? node.children : []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push(children[index])
    }
  }
}
