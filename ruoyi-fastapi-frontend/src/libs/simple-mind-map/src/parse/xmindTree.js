import {
  MAX_MINDMAP_NODE_COUNT,
  MAX_MINDMAP_TREE_DEPTH
} from '../utils/documentLimits.js'

export const MAX_XMIND_MINDMAP_NODE_COUNT = MAX_MINDMAP_NODE_COUNT
export const MAX_XMIND_MINDMAP_DEPTH = MAX_MINDMAP_TREE_DEPTH

const isObject = value => value !== null && typeof value === 'object'

// XMind 导入和导出共用的迭代树映射器。转换器只描述单节点字段映射，
// 节点顺序、规模边界和异常图结构由这里统一保证。
export const mapXmindTreeIterative = ({
  root,
  visit,
  getChildren,
  createChild,
  maxNodeCount = MAX_XMIND_MINDMAP_NODE_COUNT,
  maxDepth = MAX_XMIND_MINDMAP_DEPTH
}) => {
  if (!isObject(root)) throw new Error('XMind 根节点格式无效')
  if (
    typeof visit !== 'function' ||
    typeof getChildren !== 'function' ||
    typeof createChild !== 'function'
  ) {
    throw new TypeError('XMind 树映射器配置无效')
  }

  const targetRoot = {}
  const seen = new WeakSet([root])
  const stack = [
    {
      source: root,
      target: targetRoot,
      parent: null,
      index: 0,
      depth: 1,
      isRoot: true
    }
  ]
  let discoveredCount = 1

  while (stack.length > 0) {
    const frame = stack.pop()
    if (frame.depth > maxDepth) {
      throw new Error(`脑图层级不能超过 ${maxDepth}`)
    }

    const meta = visit(frame.source, frame.target, frame) || null
    const context = { ...frame, meta }
    const children = getChildren(frame.source, context)
    if (children === undefined || children === null) continue
    if (!Array.isArray(children)) throw new Error('XMind 子节点格式无效')

    const nextFrames = []
    for (let index = 0; index < children.length; index += 1) {
      const child = children[index]
      if (!isObject(child)) throw new Error('XMind 节点格式无效')
      if (seen.has(child)) throw new Error('XMind 节点包含循环或重复引用')
      discoveredCount += 1
      if (discoveredCount > maxNodeCount) {
        throw new Error(`脑图节点数量不能超过 ${maxNodeCount}`)
      }
      if (frame.depth >= maxDepth) {
        throw new Error(`脑图层级不能超过 ${maxDepth}`)
      }
      seen.add(child)
      const target = createChild(frame.target, child, index, context)
      if (!isObject(target)) throw new Error('XMind 子节点映射结果无效')
      nextFrames.push({
        source: child,
        target,
        parent: frame.source,
        index,
        depth: frame.depth + 1,
        isRoot: false
      })
    }
    for (let index = nextFrames.length - 1; index >= 0; index -= 1) {
      stack.push(nextFrames[index])
    }
  }

  return targetRoot
}

// 保持旧解析器“当前层优先、同层从左到右”的根 topic 查找顺序。
export const findFirstXmindElementByName = (list, name) => {
  if (!Array.isArray(list)) return null
  const visitedLists = new WeakSet()
  const stack = [list]
  while (stack.length > 0) {
    const items = stack.pop()
    if (visitedLists.has(items)) continue
    visitedLists.add(items)
    for (let index = 0; index < items.length; index += 1) {
      if (items[index]?.name === name) return items[index]
    }
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const children = items[index]?.elements
      if (Array.isArray(children)) stack.push(children)
    }
  }
  return null
}
