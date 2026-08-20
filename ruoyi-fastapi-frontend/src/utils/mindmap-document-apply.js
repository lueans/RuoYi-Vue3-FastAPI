import { isSameObject } from '../libs/simple-mind-map/src/utils/deepEqual.js'

function captureRuntimeSelectionUids(mindMap) {
  const uids = new Set()
  for (const node of (mindMap?.renderer?.activeNodeList || [])) {
    const uid = node?.uid || node?.getData?.('uid')
    if (uid) uids.add(String(uid))
  }
  const editingNode = mindMap?.renderer?.textEdit?.getCurrentEditNode?.()
  const editingUid = editingNode?.uid || editingNode?.getData?.('uid')
  if (editingUid) uids.add(String(editingUid))
  return uids
}

function applyRuntimeSelection(root, activeUids) {
  if (!root || activeUids.size === 0) return
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    if (node.data && typeof node.data === 'object') {
      node.data.isActive = activeUids.has(String(node.data.uid || ''))
    }
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      pending.push(child)
    }
  }
}

/**
 * 应用来自协作或保存合并的文档，同时尽量保留当前节点实例、选区和编辑器。
 * 只有布局或主题确实变化时才允许 simple-mind-map 执行完整数据替换。
 */
export function applyMindmapDocumentPreservingRuntimeState(mindMap, document) {
  if (!mindMap || !document?.root) return false
  const currentDocument = mindMap.getData?.(true) || {}
  const runtimeSelectionUids = captureRuntimeSelectionUids(mindMap)
  const layoutChanged = document.layout !== undefined
    && document.layout !== currentDocument.layout
  const themeChanged = document.theme !== undefined
    && !isSameObject(document.theme, currentDocument.theme)

  if (
    layoutChanged
    || themeChanged
    || typeof mindMap.updateData !== 'function'
  ) {
    mindMap.setFullData(document)
    return 'full'
  }

  // 节点的 isActive 不是服务端文档状态。尤其在文本编辑期间，协作回放
  // 可能早于防抖后的 node_active 事件到达，因此还要把编辑节点作为本地
  // 选区恢复，避免编辑框存在但节点选中标记丢失。
  applyRuntimeSelection(document.root, runtimeSelectionUids)
  mindMap.updateData(document.root)
  if (
    document.view !== undefined
    && !isSameObject(document.view, currentDocument.view)
  ) {
    mindMap.view?.setTransformData?.(document.view)
  }
  return 'incremental'
}
