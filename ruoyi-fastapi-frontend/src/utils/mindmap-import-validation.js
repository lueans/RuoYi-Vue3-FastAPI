import {
  MAX_MINDMAP_NODE_COUNT,
  MAX_MINDMAP_STABLE_UID_LENGTH,
  MAX_MINDMAP_TREE_DEPTH,
} from '../libs/simple-mind-map/src/utils/documentLimits.js'

export {
  MAX_MINDMAP_NODE_COUNT,
  MAX_MINDMAP_STABLE_UID_LENGTH,
  MAX_MINDMAP_TREE_DEPTH,
}

const isRecord = value => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
)

function invalidImport(message) {
  const error = new Error(message)
  error.code = 'MINDMAP_IMPORT_INVALID'
  return error
}

function normalizeStableUid(value, maxLength) {
  if (!value) return ''
  if (typeof value !== 'string' && typeof value !== 'number') {
    throw invalidImport('脑图节点 UID 必须是字符串或数字')
  }
  if (typeof value === 'number' && !Number.isFinite(value)) {
    throw invalidImport('脑图节点 UID 必须是有限数字')
  }
  const uid = String(value)
  if (!uid || uid !== uid.trim()) {
    throw invalidImport('脑图节点 UID 不能包含首尾空白')
  }
  if (uid.length > maxLength) {
    throw invalidImport(`脑图节点 UID 不能超过 ${maxLength} 个字符`)
  }
  return uid
}

// 所有本地导入格式在进入编辑器前共用此边界。规则与服务端结构化
// 持久化保持一致，避免导入成功后才在渲染或保存阶段失败。
export function assertMindmapImportDocument(document, options = {}) {
  const maxNodeCount = Number.isSafeInteger(options.maxNodeCount)
    && options.maxNodeCount > 0
    ? options.maxNodeCount
    : MAX_MINDMAP_NODE_COUNT
  const maxDepth = Number.isSafeInteger(options.maxDepth) && options.maxDepth > 0
    ? options.maxDepth
    : MAX_MINDMAP_TREE_DEPTH
  const maxUidLength = Number.isSafeInteger(options.maxUidLength)
    && options.maxUidLength > 0
    ? options.maxUidLength
    : MAX_MINDMAP_STABLE_UID_LENGTH

  if (!isRecord(document)) throw invalidImport('导入文件不是有效的脑图文档')
  const hasDocumentRoot = Object.prototype.hasOwnProperty.call(document, 'root')
  const root = hasDocumentRoot ? document.root : document
  if (!isRecord(root) || !isRecord(root.data)) {
    throw invalidImport('文件中没有有效的脑图根节点')
  }

  const seenNodes = new WeakSet([root])
  const seenData = new WeakSet()
  const seenUids = new Set()
  const stack = [{ node: root, depth: 1 }]
  let nodeCount = 1
  let treeDepth = 1

  while (stack.length > 0) {
    const { node, depth } = stack.pop()
    if (depth > treeDepth) treeDepth = depth

    const data = node.data
    if (data !== undefined && data !== null) {
      if (!isRecord(data)) throw invalidImport('脑图节点 data 必须是对象')
      if (seenData.has(data)) {
        throw invalidImport('脑图节点包含循环或重复数据引用')
      }
      seenData.add(data)
      const uid = normalizeStableUid(data.uid, maxUidLength)
      if (uid) {
        if (seenUids.has(uid)) throw invalidImport(`脑图节点 UID 重复: ${uid}`)
        seenUids.add(uid)
      }
    }

    const children = node.children
    if (children === undefined || children === null) continue
    if (!Array.isArray(children)) {
      throw invalidImport('脑图节点 children 必须是数组')
    }

    const childDepth = depth + 1
    if (children.length > 0 && childDepth > maxDepth) {
      throw invalidImport(`脑图层级不能超过 ${maxDepth}`)
    }
    for (let index = 0; index < children.length; index += 1) {
      const child = children[index]
      if (!isRecord(child)) throw invalidImport('脑图子节点必须是对象')
      if (seenNodes.has(child)) {
        throw invalidImport('脑图节点包含循环或重复引用')
      }
      seenNodes.add(child)
      nodeCount += 1
      if (nodeCount > maxNodeCount) {
        throw invalidImport(`脑图节点数量不能超过 ${maxNodeCount}`)
      }
    }
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push({ node: children[index], depth: childDepth })
    }
  }

  return { root, nodeCount, treeDepth }
}
