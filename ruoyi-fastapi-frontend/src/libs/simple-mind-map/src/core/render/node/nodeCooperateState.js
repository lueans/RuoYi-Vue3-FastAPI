// Presence 的选区与文本编辑占用必须保持正交。这个无 UI 依赖的判断也让
// 协作语义可以在不启动 SVG/DOM 渲染器的情况下做行为回归测试。
export function isNodeTextEditOccupied(node) {
  return Array.isArray(node?.editingUserList) && node.editingUserList.length > 0
}

// Presence 只是在旧协作协议下的尽力提示。服务端租约已协商时，过期或
// 丢失的 awareness 不能在真正申请发生前充当第二套互斥裁判。
export function shouldBlockNodeTextEditByPresence(
  node,
  { enabled = false, authoritative = false } = {},
) {
  return Boolean(enabled && !authoritative && isNodeTextEditOccupied(node))
}

// 异步租约等待结束后，运行时节点实例可能已被整树渲染替换。权威租约按
// UID 保护语义节点，因此继续编辑前必须重新解析当前实例；删除、只读切换
// 和自定义内容节点都返回 null，由调用方归还租约。
export function resolveCurrentNodeTextEditTarget(
  node,
  renderer,
  { authoritative = false, readonly = false } = {},
) {
  if (!authoritative) return node || null
  const nodeUid = node?.uid || node?.getData?.('uid')
  const currentNode = nodeUid ? renderer?.findNodeByUid?.(nodeUid) : null
  if (readonly || !currentNode || currentNode.isUseCustomNodeContent?.()) return null
  return currentNode
}
