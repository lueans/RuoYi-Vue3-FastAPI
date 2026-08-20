const isObjectNode = node => Boolean(node && typeof node === 'object')

const getChildren = node => Array.isArray(node?.children) ? node.children : []

// 沿 parent 链稳定向上访问。默认只处理存在父节点的项，和各布局原有
// updateBrothers 递归边界一致；异常 parent 环只处理首次可达位置。
export const walkLayoutAncestorChain = (
  start,
  visit,
  canVisit = node => Boolean(node?.parent)
) => {
  if (typeof visit !== 'function') return
  const visited = new WeakSet()
  let current = start
  while (isObjectNode(current) && !visited.has(current)) {
    if (!canVisit(current)) break
    visited.add(current)
    if (visit(current) === false) break
    current = current.parent
  }
}

export const updateDescendantNodes = (
  children,
  updateNode,
  shouldDescend = () => true
) => {
  const roots = Array.isArray(children) ? children : []
  const visited = new WeakSet()
  const stack = []
  for (let index = roots.length - 1; index >= 0; index -= 1) {
    stack.push(roots[index])
  }

  while (stack.length > 0) {
    const node = stack.pop()
    if (isObjectNode(node) && visited.has(node)) continue
    if (isObjectNode(node)) visited.add(node)

    updateNode(node)
    if (!shouldDescend(node)) continue
    const nodeChildren = getChildren(node)
    for (let index = nodeChildren.length - 1; index >= 0; index -= 1) {
      stack.push(nodeChildren[index])
    }
  }
}

export const calculateNodeAreaWidth = (root, withGeneralization = false) => {
  const visited = new WeakSet()
  const stack = [{ node: root, width: 0 }]
  let maxWidth = -Infinity
  let totalGeneralizationNodeWidth = 0

  while (stack.length > 0) {
    const { node, width } = stack.pop()
    if (isObjectNode(node) && visited.has(node)) continue
    if (isObjectNode(node)) visited.add(node)

    if (withGeneralization && node.checkHasGeneralization()) {
      totalGeneralizationNodeWidth += node._generalizationNodeWidth
    }

    const children = getChildren(node).filter(child => (
      !isObjectNode(child) || !visited.has(child)
    ))
    if (children.length === 0) {
      maxWidth = Math.max(maxWidth, width + node.width)
      continue
    }

    const childWidth = width + node.width / 2
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push({ node: children[index], width: childWidth })
    }
  }

  const fallbackWidth = Number(root?.width)
  return (
    Number.isFinite(maxWidth)
      ? maxWidth
      : (Number.isFinite(fallbackWidth) ? fallbackWidth : 0)
  ) + totalGeneralizationNodeWidth
}

export const calculateNodeBoundaries = (
  root,
  dir,
  generalizationNodeMargin
) => {
  const activePath = new WeakSet()
  const boundaries = new WeakMap()
  const stack = [{ type: 'enter', node: root }]

  while (stack.length > 0) {
    const frame = stack.pop()
    const node = frame.node

    if (frame.type === 'enter') {
      if (isObjectNode(node) && activePath.has(node)) continue
      if (isObjectNode(node)) activePath.add(node)
      stack.push({ type: 'exit', node })
      const children = getChildren(node)
      for (let index = children.length - 1; index >= 0; index -= 1) {
        stack.push({ type: 'enter', node: children[index] })
      }
      continue
    }

    let left = node.left
    let right = node.left + node.width
    let top = node.top
    let bottom = node.top + node.height
    const children = getChildren(node)

    for (let index = 0; index < children.length; index += 1) {
      const child = children[index]
      const childBoundaries = boundaries.get(child)
      if (!childBoundaries) continue
      const hasGeneralization =
        child.checkHasGeneralization() && child.getData('expand')
      const generalizationWidth = hasGeneralization
        ? child._generalizationNodeWidth + generalizationNodeMargin
        : 0
      const generalizationHeight = hasGeneralization
        ? child._generalizationNodeHeight + generalizationNodeMargin
        : 0

      left = Math.min(
        left,
        childBoundaries.left - (dir === 'h' ? generalizationWidth : 0)
      )
      right = Math.max(
        right,
        childBoundaries.right + (dir === 'h' ? generalizationWidth : 0)
      )
      top = Math.min(top, childBoundaries.top)
      bottom = Math.max(
        bottom,
        childBoundaries.bottom + (dir === 'v' ? generalizationHeight : 0)
      )
    }

    boundaries.set(node, { left, right, top, bottom })
    if (isObjectNode(node)) activePath.delete(node)
  }

  return boundaries.get(root) || {
    left: root.left,
    right: root.left + root.width,
    top: root.top,
    bottom: root.top + root.height
  }
}

export const calculateNodeAreaHeight = (
  root,
  getActiveChildrenLength,
  getMarginY
) => {
  const visited = new WeakSet()
  const stack = [root]
  let totalHeight = 0

  while (stack.length > 0) {
    const node = stack.pop()
    if (isObjectNode(node) && visited.has(node)) continue
    if (isObjectNode(node)) visited.add(node)

    totalHeight +=
      node.height +
      (getActiveChildrenLength(node) > 0 ? node.expandBtnSize : 0) +
      getMarginY(node.layerIndex)

    const children = getChildren(node)
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push(children[index])
    }
  }

  return totalHeight
}
