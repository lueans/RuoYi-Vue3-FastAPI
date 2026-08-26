const isObjectNode = node => Boolean(node && typeof node === 'object')

const getChildren = node => Array.isArray(node?.children) ? node.children : []

const getFiniteNumber = (value, fallback = 0) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

// 相邻子树只使用各自需要的安全间距，不把最高子树所需的间距广播给
// 整组兄弟节点；这样普通连续分支保持紧凑，复杂分支仍不会互相覆盖。
export const calculateUniformSiblingCenterOffsets = (metrics, gap = 0) => {
  const list = Array.isArray(metrics) ? metrics : []
  if (list.length <= 0) return []
  if (list.length === 1) return [0]

  const safeGap = Math.max(0, getFiniteNumber(gap))
  const offsets = [0]
  for (let index = 1; index < list.length; index += 1) {
    const previousBottom = getFiniteNumber(list[index - 1]?.bottomOffset)
    const currentTop = getFiniteNumber(list[index]?.topOffset)
    const distance = Math.max(
      0,
      previousBottom - currentTop + safeGap
    )
    offsets.push(offsets[index - 1] + distance)
  }

  const centerIndex = (list.length - 1) / 2
  const lowerCenter = Math.floor(centerIndex)
  const upperCenter = Math.ceil(centerIndex)
  const centerOffset = (
    offsets[lowerCenter] + offsets[upperCenter]
  ) / 2
  return offsets.map(offset => offset - centerOffset)
}

// 先自底向上计算每棵子树相对根节点中心的边界，再自顶向下一次性落位。
// 每个节点只参与常数次计算，避免在每一层反复平移整棵后代树。
export const balanceTreeChildrenVertically = (root, options = {}) => {
  if (!isObjectNode(root)) {
    return { balancedParentCount: 0 }
  }

  const resolveChildren = typeof options.getChildren === 'function'
    ? options.getChildren
    : getChildren
  const getNodeTop = typeof options.getNodeTop === 'function'
    ? options.getNodeTop
    : node => node?.top
  const setNodeTop = typeof options.setNodeTop === 'function'
    ? options.setNodeTop
    : (node, top) => {
        node.top = top
      }
  const getNodeHeight = typeof options.getNodeHeight === 'function'
    ? options.getNodeHeight
    : node => node?.height
  const getNodeExtentHeight = typeof options.getNodeExtentHeight === 'function'
    ? options.getNodeExtentHeight
    : getNodeHeight
  const getGap = typeof options.getGap === 'function'
    ? options.getGap
    : () => 0
  const hasCustomPosition = typeof options.hasCustomPosition === 'function'
    ? options.hasCustomPosition
    : node => Boolean(node?.hasCustomPosition?.())
  const resolveNodeChildren = node => {
    const children = resolveChildren(node)
    return Array.isArray(children) ? children : []
  }

  const order = []
  const discovered = new WeakSet()
  const stack = [root]
  let hasAnyCustomPosition = false
  while (stack.length > 0) {
    const node = stack.pop()
    if (!isObjectNode(node) || discovered.has(node)) continue
    discovered.add(node)
    order.push(node)
    if (hasCustomPosition(node)) hasAnyCustomPosition = true
    const children = resolveNodeChildren(node)
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push(children[index])
    }
  }

  // 手动定位表达的是整棵图的用户排版意图。只重排其中一部分会让普通分支
  // 侵入固定分支，所以此时完整保留旧布局，而不是进行局部自动平衡。
  if (hasAnyCustomPosition) {
    return { balancedParentCount: 0 }
  }

  const metrics = new WeakMap()
  const placements = new WeakMap()
  let balancedParentCount = 0

  for (let orderIndex = order.length - 1; orderIndex >= 0; orderIndex -= 1) {
    const node = order[orderIndex]
    const children = resolveNodeChildren(node).filter(child => metrics.has(child))
    const height = Math.max(0, getFiniteNumber(getNodeHeight(node)))
    const center = getFiniteNumber(getNodeTop(node)) + height / 2
    const extentHeight = Math.max(
      height,
      getFiniteNumber(getNodeExtentHeight(node), height)
    )
    let topOffset = -extentHeight / 2
    let bottomOffset = extentHeight / 2
    const childMetrics = children.map(child => metrics.get(child))
    const canBalanceChildren = children.length > 0
    let childOffsets = children.map(child => {
      const childHeight = Math.max(0, getFiniteNumber(getNodeHeight(child)))
      return getFiniteNumber(getNodeTop(child)) + childHeight / 2 - center
    })

    if (canBalanceChildren) {
      childOffsets = calculateUniformSiblingCenterOffsets(
        childMetrics,
        getGap(node)
      )
      balancedParentCount += 1
    }

    childMetrics.forEach((item, index) => {
      topOffset = Math.min(topOffset, childOffsets[index] + item.topOffset)
      bottomOffset = Math.max(
        bottomOffset,
        childOffsets[index] + item.bottomOffset
      )
    })

    metrics.set(node, {
      topOffset,
      bottomOffset
    })
    placements.set(node, {
      children,
      childOffsets,
      balanced: canBalanceChildren
    })
  }

  const positioned = new WeakSet()
  const positionStack = [root]
  while (positionStack.length > 0) {
    const node = positionStack.pop()
    if (!isObjectNode(node) || positioned.has(node)) continue
    positioned.add(node)
    const placement = placements.get(node)
    if (!placement) continue
    const height = Math.max(0, getFiniteNumber(getNodeHeight(node)))
    const center = getFiniteNumber(getNodeTop(node)) + height / 2

    for (let index = placement.children.length - 1; index >= 0; index -= 1) {
      const child = placement.children[index]
      if (placement.balanced) {
        const childHeight = Math.max(0, getFiniteNumber(getNodeHeight(child)))
        setNodeTop(
          child,
          center + placement.childOffsets[index] - childHeight / 2
        )
      }
      positionStack.push(child)
    }
  }

  return { balancedParentCount }
}

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
