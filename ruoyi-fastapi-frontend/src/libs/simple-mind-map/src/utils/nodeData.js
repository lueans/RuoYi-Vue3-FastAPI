// 节点选中态与托管标签的展示定义都只属于当前客户端。所有需要比较
// “持久化节点内容”的路径必须复用同一归一化规则，避免把远端重绘带来的
// UI 差异误判为正文修改。
export function stripManagedTagDefinitions(data = {}) {
  const output = { ...data }
  if (Array.isArray(output.tag)) {
    output.tag = output.tag.map(tag => {
      if (!tag || typeof tag !== 'object' || !tag.tagId) return tag
      return Object.fromEntries(Object.entries({
        tagId: tag.tagId,
        categoryId: tag.categoryId,
        placement: tag.placement,
        align: tag.align
      }).filter(([, value]) => value !== undefined))
    })
  }
  return output
}

export function normalizePersistedNodeData(data = {}) {
  const output = stripManagedTagDefinitions(data)
  delete output.isActive
  return output
}

function getRuntimePersistentUid(node) {
  return String(node?.getData?.('uid') || node?.uid || '').trim()
}

// updateData 会同步替换 renderTree，但布局/runtime 重建在下一帧。将仍存活
// runtime 的 nodeData 立即换绑到新树，可保证这段窗口内的文本 blur、关联线
// 提交、大纲提交等仍写入当前命令真源，而不是已经脱树的旧对象。
export function rebindRuntimeNodesToRenderTree(runtimeRoot, renderTree) {
  if (!runtimeRoot || !renderTree) return 0
  const runtimeByUid = new Map()
  const runtimePending = Array.isArray(runtimeRoot)
    // 调用方按 current root/nodeCache → lastNodeCache 排列。栈反转后让当前
    // 实例先登记，同 UID 的已销毁旧 cache 不能抢走换绑目标。
    ? [...runtimeRoot].reverse()
    : [runtimeRoot]
  const runtimeVisited = new WeakSet()
  while (runtimePending.length) {
    const node = runtimePending.pop()
    if (!node || typeof node !== 'object' || runtimeVisited.has(node)) continue
    runtimeVisited.add(node)
    const uid = getRuntimePersistentUid(node)
    if (uid && !runtimeByUid.has(uid)) runtimeByUid.set(uid, node)
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      runtimePending.push(child)
    }
    for (const item of (
      Array.isArray(node._generalizationList) ? node._generalizationList : []
    )) {
      if (item?.generalizationNode) runtimePending.push(item.generalizationNode)
    }
  }

  let reboundCount = 0
  const dataPending = [renderTree]
  const dataVisited = new WeakSet()
  while (dataPending.length) {
    const nodeData = dataPending.pop()
    if (!nodeData || typeof nodeData !== 'object' || dataVisited.has(nodeData)) {
      continue
    }
    dataVisited.add(nodeData)
    const uid = String(nodeData.data?.uid || '').trim()
    const runtimeNode = runtimeByUid.get(uid)
    if (runtimeNode && runtimeNode.isGeneralization !== true) {
      runtimeNode.nodeData = typeof runtimeNode.handleData === 'function'
        ? runtimeNode.handleData(nodeData)
        : nodeData
      nodeData._node = runtimeNode
      reboundCount += 1
    }

    const generalization = nodeData.data?.generalization
    const summaries = Array.isArray(generalization)
      ? generalization
      : generalization && typeof generalization === 'object'
        ? [generalization]
        : []
    for (const summary of summaries) {
      const summaryUid = String(summary?.uid || '').trim()
      const summaryRuntime = runtimeByUid.get(summaryUid)
      if (!summaryRuntime?.isGeneralization) continue
      const summaryNodeData = { data: summary, children: [] }
      summaryRuntime.nodeData = typeof summaryRuntime.handleData === 'function'
        ? summaryRuntime.handleData(summaryNodeData)
        : summaryNodeData
      if (runtimeNode) summaryRuntime.generalizationBelongNode = runtimeNode
      reboundCount += 1
    }
    for (const child of (
      Array.isArray(nodeData.children) ? nodeData.children : []
    )) dataPending.push(child)
  }
  return reboundCount
}
