import { fromMarkdown } from 'mdast-util-from-markdown'
import {
  MAX_MINDMAP_NODE_COUNT,
  MAX_MINDMAP_TREE_DEPTH
} from '../utils/documentLimits.js'

export const MARKDOWN_MULTI_ROOT_TEXT = 'Markdown 导入'

const getChildren = node => Array.isArray(node?.children) ? node.children : []

// mdast 文本可能由 emphasis/link 等多层容器组成。用稳定先序显式栈
// 收集文本，并继续保持“嵌套列表不属于当前节点标题”的旧语义。
export const getMarkdownNodeText = node => {
  if (node?.type === 'list') return ''
  const stack = [node]
  const visited = new WeakSet()
  let text = ''

  while (stack.length > 0) {
    const current = stack.pop()
    if (!current || typeof current !== 'object' || visited.has(current)) continue
    visited.add(current)
    if (current.type === 'list') continue
    if (
      current.type === 'code'
      || current.type === 'inlineCode'
      || current.type === 'text'
    ) {
      text += current.value || ''
      continue
    }
    const children = getChildren(current)
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push(children[index])
    }
  }

  return text
}

const createConversionState = options => ({
  maxNodeCount: Number.isSafeInteger(options.maxNodeCount)
    && options.maxNodeCount > 0
    ? options.maxNodeCount
    : MAX_MINDMAP_NODE_COUNT,
  maxDepth: Number.isSafeInteger(options.maxDepth) && options.maxDepth > 0
    ? options.maxDepth
    : MAX_MINDMAP_TREE_DEPTH,
  sourceMarkdown: typeof options.sourceMarkdown === 'string'
    ? options.sourceMarkdown
    : '',
  nodeCount: 0,
  treeDepth: 0
})

const getMarkdownBlockSource = (node, state) => {
  const start = Number(node?.position?.start?.offset)
  const end = Number(node?.position?.end?.offset)
  if (
    state.sourceMarkdown
    && Number.isSafeInteger(start)
    && Number.isSafeInteger(end)
    && start >= 0
    && end >= start
    && end <= state.sourceMarkdown.length
  ) {
    return state.sourceMarkdown.slice(start, end).trim()
  }
  return getMarkdownNodeText(node).trim()
}

const appendNodeNote = (node, markdown) => {
  if (!node || !markdown) return
  node.data.note = node.data.note
    ? `${node.data.note}\n\n${markdown}`
    : markdown
}

const createMindmapNode = (source, depth, state) => {
  if (depth > state.maxDepth) {
    throw new Error(`脑图层级不能超过 ${state.maxDepth}`)
  }
  state.nodeCount += 1
  if (state.nodeCount > state.maxNodeCount) {
    throw new Error(`脑图节点数量不能超过 ${state.maxNodeCount}`)
  }
  if (depth > state.treeDepth) state.treeDepth = depth
  return {
    data: { text: getMarkdownNodeText(source) },
    children: []
  }
}

// 把一个 mdast list 追加到指定父级。栈帧保留数组游标，使多个嵌套
// list 仍按原文从左到右完整处理，不依赖 JavaScript 调用栈。
const appendMarkdownList = (listNode, target, depth, state) => {
  const stack = [{
    items: getChildren(listNode),
    target,
    depth,
    index: 0
  }]
  let lastCreatedNode = null

  while (stack.length > 0) {
    const frame = stack[stack.length - 1]
    if (frame.index >= frame.items.length) {
      stack.pop()
      continue
    }

    const source = frame.items[frame.index]
    frame.index += 1
    if (!source || typeof source !== 'object') {
      throw new Error('Markdown 列表节点格式无效')
    }
    const sourceChildren = getChildren(source)
    const node = createMindmapNode(
      sourceChildren[0] || source,
      frame.depth,
      state
    )
    frame.target.push(node)
    lastCreatedNode = node
    sourceChildren.slice(1).forEach(child => {
      if (child?.type !== 'list') {
        appendNodeNote(node, getMarkdownBlockSource(child, state))
      }
    })
    const nestedLists = sourceChildren
      .slice(1)
      .filter(child => child?.type === 'list')
    for (let index = nestedLists.length - 1; index >= 0; index -= 1) {
      stack.push({
        items: getChildren(nestedLists[index]),
        target: node.children,
        depth: frame.depth + 1,
        index: 0
      })
    }
  }
  return lastCreatedNode
}

const normalizeMarkdownRoots = (roots, state) => {
  if (roots.length <= 1) return roots[0]
  if (state.nodeCount >= state.maxNodeCount) {
    throw new Error(`脑图节点数量不能超过 ${state.maxNodeCount}`)
  }
  if (state.treeDepth >= state.maxDepth) {
    throw new Error(`脑图层级不能超过 ${state.maxDepth}`)
  }
  return {
    data: { text: MARKDOWN_MULTI_ROOT_TEXT },
    children: roots
  }
}

export const transformMarkdownAstToMindmap = (tree, options = {}) => {
  if (!tree || typeof tree !== 'object' || !Array.isArray(tree.children)) {
    throw new Error('Markdown 文档格式无效')
  }

  const state = createConversionState(options)
  const roots = []
  const headingStack = []
  let lastCreatedNode = null

  for (let index = 0; index < tree.children.length; index += 1) {
    const source = tree.children[index]
    if (source?.type === 'heading') {
      if (getChildren(source).length === 0) continue
      const headingDepth = Number(source.depth)
      if (!Number.isInteger(headingDepth) || headingDepth <= 0) {
        throw new Error('Markdown 标题层级无效')
      }
      while (
        headingStack.length > 0
        && headingStack[headingStack.length - 1].headingDepth >= headingDepth
      ) {
        headingStack.pop()
      }
      const parent = headingStack[headingStack.length - 1]?.node
      const node = createMindmapNode(source, headingStack.length + 1, state)
      ;(parent ? parent.children : roots).push(node)
      headingStack.push({ headingDepth, node })
      lastCreatedNode = node
      continue
    }

    if (source?.type === 'list') {
      const parent = headingStack[headingStack.length - 1]?.node
      const listLastNode = appendMarkdownList(
        source,
        parent ? parent.children : roots,
        headingStack.length + 1,
        state
      )
      if (listLastNode) lastCreatedNode = listLastNode
      continue
    }

    const blockSource = getMarkdownBlockSource(source, state)
    if (!blockSource) continue
    if (lastCreatedNode) {
      appendNodeNote(lastCreatedNode, blockSource)
    } else {
      const node = createMindmapNode(source, 1, state)
      roots.push(node)
      lastCreatedNode = node
    }
  }

  return normalizeMarkdownRoots(roots, state)
}

// 将 markdown 转换成节点树
export const transformMarkdownTo = (markdown, options = {}) => (
  transformMarkdownAstToMindmap(fromMarkdown(markdown), {
    ...options,
    sourceMarkdown: markdown
  })
)
