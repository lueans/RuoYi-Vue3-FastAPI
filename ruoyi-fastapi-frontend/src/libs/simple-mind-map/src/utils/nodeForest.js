const isObjectNode = node => Boolean(node && typeof node === 'object')

const defaultGetChildren = node => (
  Array.isArray(node?.children) ? node.children : []
)

// 稳定先序遍历一组节点。循环和共享对象只处理首次可达位置，回调
// 返回 false 时只截断当前子树，不影响后续兄弟节点。
export const walkNodeForest = (
  roots,
  visit,
  getChildren = defaultGetChildren,
  options = {}
) => {
  if (typeof visit !== 'function') return 0
  const rootList = Array.isArray(roots) ? roots : [roots]
  const stack = []
  const visited = new WeakSet()
  let visitedCount = 0

  for (let index = rootList.length - 1; index >= 0; index -= 1) {
    stack.push({
      node: rootList[index],
      parent: null,
      depth: 0,
      index
    })
  }

  while (stack.length > 0) {
    const frame = stack.pop()
    const node = frame.node
    if (!isObjectNode(node)) {
      options.onInvalidNode?.(node, frame)
      continue
    }
    if (visited.has(node)) {
      options.onDuplicateNode?.(node, frame)
      continue
    }
    visited.add(node)
    visitedCount += 1
    if (visit(node, frame) === false) continue

    const children = typeof getChildren === 'function'
      ? getChildren(node, frame)
      : []
    if (!Array.isArray(children)) continue
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push({
        node: children[index],
        parent: node,
        depth: frame.depth + 1,
        index
      })
    }
  }

  return visitedCount
}

export const calculateNodeForestRect = ({
  roots,
  measureNode,
  getChildren = defaultGetChildren,
  excludeRoots = false
}) => {
  if (typeof measureNode !== 'function') return null
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  let measuredCount = 0

  walkNodeForest(roots, (node, frame) => {
    if (excludeRoots && frame.depth === 0) return
    let rect
    try {
      rect = measureNode(node, frame)
    } catch {
      return
    }
    const x = Number(rect?.x)
    const y = Number(rect?.y)
    const width = Number(rect?.width)
    const height = Number(rect?.height)
    if (
      !Number.isFinite(x)
      || !Number.isFinite(y)
      || !Number.isFinite(width)
      || !Number.isFinite(height)
      || width < 0
      || height < 0
    ) return

    measuredCount += 1
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x + width)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y + height)
  }, getChildren)

  if (measuredCount === 0) return null
  return {
    left: minX,
    top: minY,
    width: maxX - minX,
    height: maxY - minY,
    measuredCount
  }
}
