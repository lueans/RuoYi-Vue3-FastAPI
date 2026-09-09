import { cloneJsonValueIterative } from '../../../utils/jsonClone.js'
import { isSameObject } from '../../../utils/deepEqual.js'
import { normalizePersistedNodeData } from '../../../utils/nodeData.js'

const MAX_PENDING_NODE_TEXT_INPUT_LENGTH = 1024

function capturePersistedNodeData(nodeData) {
  if (!nodeData || typeof nodeData !== 'object') return null
  // 布局器会给每个 nodeData 添加 enumerable `_node` 回指，直接 JSON
  // 序列化必然成环。回滚只比较与 Yjs 相同口径的持久化 data；isActive
  // 与托管标签展示定义不属于正文，且结构比较不能依赖对象键插入顺序。
  const data = cloneJsonValueIterative(
    normalizePersistedNodeData(nodeData.data)
  )
  return data && typeof data === 'object' && !Array.isArray(data)
    ? data
    : null
}

function getPersistentNodeUid(node) {
  return node?.getData?.('uid') || node?.nodeData?.data?.uid || node?.uid || ''
}

function getPrintableTextEditKey(event) {
  if (!event || event.ctrlKey || event.metaKey || event.altKey) return ''
  if (
    typeof event.key === 'string'
    && [...event.key].length === 1
  ) return event.key
  const keyCode = Number(event.keyCode)
  if (keyCode >= 48 && keyCode <= 57) {
    return String.fromCharCode(keyCode)
  }
  if (keyCode >= 65 && keyCode <= 90) {
    return String.fromCharCode(keyCode + (event.shiftKey ? 0 : 32))
  }
  return ''
}

function updatePendingInputValue(admission, value) {
  // window keydown 降级路径成为最新真源后，交接阶段不能再用未获焦点的
  // textarea 旧值覆盖它。
  admission.pendingInputNativeActivity = false
  admission.pendingInputText = value
  admission.pendingInputTouched = true
  const segments = admission.pendingInputSegments
  const index = Number(admission.pendingInputSegmentIndex)
  if (Array.isArray(segments) && segments[index]) {
    segments[index].text = value
    segments[index].touched = true
  }
}

// 插入命令会先激活新节点，再异步等待服务端文本租约。等待期间用户输入
// 会再次命中 TextEdit.show；同一持久 UID 必须复用原准入，不能把它当成
// “切换编辑目标”而补偿删除新节点。可打印按键一并暂存，获锁后恢复输入。
export function reusePendingNodeTextEditAdmission(admission, node, event) {
  if (!admission) return false
  const pendingUid = String(admission.nodeUid || '').trim()
  const targetUid = String(getPersistentNodeUid(node) || '').trim()
  if (!pendingUid || pendingUid !== targetUid) return false
  bufferPendingNodeTextEditInput(admission, node, event)
  return true
}

// 返回 true 表示当前按键已由待准入编辑器接管；即使缓冲已达到上限也要
// 阻止浏览器把按键作用到 body。临时 textarea 是主路径，这里仍负责焦点
// 被浏览器策略拒绝等降级场景，并完整保留普通输入及尾部删除语义。
export function bufferPendingNodeTextEditInput(admission, node, event) {
  if (!admission) return false
  const pendingUid = String(admission.nodeUid || '').trim()
  const targetUid = String(getPersistentNodeUid(node) || '').trim()
  if (!pendingUid || pendingUid !== targetUid) return false
  const key = event?.key
  const keyCode = Number(event?.keyCode)
  if (key === 'Backspace' || keyCode === 8) {
    const input = admission.pendingInputTouched
      ? [...String(admission.pendingInputText || '')]
      : []
    input.pop()
    updatePendingInputValue(admission, input.join(''))
    return true
  }
  if (key === 'Delete' || key === 'Del' || keyCode === 46) {
    // 兜底缓存没有光标模型；等待态输入始终位于末尾，因此 Delete 只需
    // 消费事件。即使当前为空也要标记 touched，使默认节点文字被清空。
    updatePendingInputValue(
      admission,
      admission.pendingInputTouched
        ? String(admission.pendingInputText || '')
        : ''
    )
    return true
  }
  const input = getPrintableTextEditKey(event)
  if (!input) return false
  const baseText = admission.pendingInputTouched
    ? admission.pendingInputText || ''
    : ''
  const combined = `${baseText}${input}`
  const value = [...combined]
    .slice(0, MAX_PENDING_NODE_TEXT_INPUT_LENGTH)
    .join('')
  updatePendingInputValue(admission, value)
  return true
}

function getChildNodeUids(nodeData) {
  if (!Array.isArray(nodeData?.children)) return null
  const uids = nodeData.children.map(child => child?.data?.uid || '')
  return uids.every(Boolean) ? uids : null
}

function getParentSiblingAnchors(parentChildren, nodeData) {
  if (!Array.isArray(parentChildren)) return null
  const index = parentChildren.indexOf(nodeData)
  if (index < 0) return null
  const siblingUids = parentChildren.map(child => child?.data?.uid || '')
  if (!siblingUids.every(Boolean)) return null
  return {
    before: siblingUids.slice(0, index),
    after: siblingUids.slice(index + 1),
  }
}

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
  // 概要节点的运行时 uid 每次渲染都会变化，getData('uid') 才是跨浏览器
  // 稳定身份；普通节点两者相同。所有协作判断都必须优先持久化 uid。
  const nodeUid = node?.getData?.('uid') || node?.uid
  const currentNode = nodeUid ? renderer?.findNodeByUid?.(nodeUid) : null
  if (readonly || !currentNode || currentNode.isUseCustomNodeContent?.()) return null
  return currentNode
}

// 异步租约返回前画布仍可收到远端更新。捕获持久化 UID、内容、父位置及
// 直接子节点顺序；运行时可以正常整树复用/换绑，但任一持久化语义变化都
// fail closed，避免删除已经被协作者实际修改的节点。
export function captureInsertedNodeRollbackState(
  node,
  { isInserting = false, insertionType = 'node' } = {},
) {
  if (!isInserting || !node?.nodeData) return null
  const children = node.nodeData.children
  // 自动编辑创建的普通节点应为空。若调用方同时附带子树，租约失败时
  // 宁可保留它也不冒险删除可能已被协作者修改的内容。
  if (
    insertionType !== 'parent'
    && !node.isGeneralization
    && Array.isArray(children)
    && children.length > 0
  ) return null
  let nodeDataSnapshot = null
  try {
    nodeDataSnapshot = capturePersistedNodeData(node.nodeData)
  } catch {
    return null
  }
  if (!nodeDataSnapshot) return null

  const parentNodeData = node.parent?.nodeData || null
  const parentChildren = Array.isArray(parentNodeData?.children)
    ? parentNodeData.children
    : null
  const generalizationOwner = node.isGeneralization
    ? node.generalizationBelongNode || null
    : null
  const childNodeUids = getChildNodeUids(node.nodeData)
  if (!childNodeUids) return null
  const nodeUid = getPersistentNodeUid(node)
  const parentUid = getPersistentNodeUid(node.parent)
  const generalizationOwnerUid = getPersistentNodeUid(generalizationOwner)
  const parentSiblingAnchors = generalizationOwner
    ? { before: [], after: [] }
    : getParentSiblingAnchors(parentChildren, node.nodeData)
  if (
    !nodeUid
    || (generalizationOwner ? !generalizationOwnerUid : !parentUid)
    || !parentSiblingAnchors
  ) return null
  return {
    nodeUid,
    nodeDataSnapshot,
    childNodeUids,
    parentUid,
    parentSiblingUidsBefore: parentSiblingAnchors.before,
    parentSiblingUidsAfter: parentSiblingAnchors.after,
    insertionType,
    generalizationOwnerUid,
  }
}

function remainsBetweenCapturedSiblings(state, parentChildren, currentIndex) {
  const currentSiblingIndexes = new Map()
  parentChildren.forEach((child, index) => {
    const uid = child?.data?.uid || ''
    if (uid) currentSiblingIndexes.set(uid, index)
  })
  return state.parentSiblingUidsBefore.every(uid => (
    !currentSiblingIndexes.has(uid)
    || currentSiblingIndexes.get(uid) < currentIndex
  )) && state.parentSiblingUidsAfter.every(uid => (
    !currentSiblingIndexes.has(uid)
    || currentSiblingIndexes.get(uid) > currentIndex
  ))
}

function isRollbackStateUnchanged(state, currentNode) {
  if (!state || !currentNode?.nodeData) return false
  if (getPersistentNodeUid(currentNode) !== state.nodeUid) return false
  const currentChildNodeUids = getChildNodeUids(currentNode.nodeData)
  if (
    !currentChildNodeUids
    || currentChildNodeUids.length !== state.childNodeUids.length
    || currentChildNodeUids.some((uid, index) => uid !== state.childNodeUids[index])
  ) return false
  try {
    const currentDataSnapshot = capturePersistedNodeData(currentNode.nodeData)
    if (!currentDataSnapshot || !isSameObject(
      currentDataSnapshot,
      state.nodeDataSnapshot
    )) return false
  } catch {
    return false
  }

  if (state.generalizationOwnerUid) {
    const owner = currentNode.generalizationBelongNode
    const ownerGeneralization = owner?.nodeData?.data?.generalization
    const currentGeneralizations = Array.isArray(ownerGeneralization)
      ? ownerGeneralization
      : ownerGeneralization && typeof ownerGeneralization === 'object'
        ? [ownerGeneralization]
        : []
    return (
      currentNode.isGeneralization === true
      && getPersistentNodeUid(owner) === state.generalizationOwnerUid
      // setData 会先把 owner runtime 换绑到新 renderTree，旧概要 runtime
      // 要到下一帧才销毁。只有当前 owner 仍实际包含该持久 UID 时，旧实例
      // 才能参与补偿，避免按旧下标误删新树中的另一个概要。
      && currentGeneralizations.some(item => (
        String(item?.uid || '') === state.nodeUid
      ))
    )
  }
  const currentParent = currentNode.parent
  const currentParentNodeData = currentParent?.nodeData || null
  const currentParentChildren = currentParentNodeData?.children
  const currentIndex = Array.isArray(currentParentChildren)
    ? currentParentChildren.indexOf(currentNode.nodeData)
    : -1
  return (
    getPersistentNodeUid(currentParent) === state.parentUid
    && Array.isArray(currentParentChildren)
    && currentIndex >= 0
    && remainsBetweenCapturedSiblings(state, currentParentChildren, currentIndex)
  )
}

// 布局计算期间 Render._render 会暂时把 renderer.root 置空，但持久
// renderTree 仍是当前命令真源。构造最小 runtime-like 视图复用同一套
// 快照校验，并携带一个只删除精确 UID 的补偿函数。
function findPersistedRollbackTarget(renderer, targetUid) {
  const root = renderer?.renderTree?.root || renderer?.renderTree
  if (!root || !targetUid) return null
  const pending = [{ nodeData: root, parentData: null }]
  const visited = new WeakSet()
  const createNodeView = (nodeData, parentData) => ({
    nodeData,
    parent: parentData ? {
      nodeData: parentData,
      getData: key => parentData.data?.[key]
    } : null,
    getData: key => nodeData.data?.[key]
  })
  while (pending.length) {
    const { nodeData, parentData } = pending.pop()
    if (!nodeData || typeof nodeData !== 'object' || visited.has(nodeData)) {
      continue
    }
    visited.add(nodeData)
    if (String(nodeData.data?.uid || '') === targetUid) {
      const node = createNodeView(nodeData, parentData)
      return {
        node,
        remove() {
          const siblings = parentData?.children
          const index = Array.isArray(siblings) ? siblings.indexOf(nodeData) : -1
          if (index < 0) return false
          const fallbackNodeData = siblings[index + 1]
            || siblings[index - 1]
            || parentData
          const fallbackUid = String(fallbackNodeData?.data?.uid || '').trim()
          siblings.splice(index, 1)
          if (fallbackNodeData?.data) fallbackNodeData.data.isActive = true
          return fallbackUid || false
        }
      }
    }
    const generalization = nodeData.data?.generalization
    const generalizationList = Array.isArray(generalization)
      ? generalization
      : generalization && typeof generalization === 'object'
        ? [generalization]
        : []
    for (let index = 0; index < generalizationList.length; index += 1) {
      const item = generalizationList[index]
      if (String(item?.uid || '') !== targetUid) continue
      const owner = createNodeView(nodeData, parentData)
      const summaryNodeData = { data: item, children: [] }
      const node = {
        ...createNodeView(summaryNodeData, null),
        isGeneralization: true,
        generalizationBelongNode: owner
      }
      return {
        node,
        ownerUid: getPersistentNodeUid(owner),
        remove() {
          const current = nodeData.data?.generalization
          if (Array.isArray(current)) {
            const currentIndex = current.findIndex(summary => (
              String(summary?.uid || '') === targetUid
            ))
            if (currentIndex < 0) return false
            current.splice(currentIndex, 1)
          } else if (String(current?.uid || '') === targetUid) {
            delete nodeData.data.generalization
          } else {
            return false
          }
          if (nodeData.data) nodeData.data.isActive = true
          return getPersistentNodeUid(owner) || false
        }
      }
    }
    for (const child of (Array.isArray(nodeData.children) ? nodeData.children : [])) {
      pending.push({ nodeData: child, parentData: nodeData })
    }
  }
  return null
}

// 新节点编辑租约被拒绝时撤销仍保持原样的临时插入。插入父节点需要解包
// 原有子树，普通节点/概要则由渲染器走各自的标准删除路径。
export function rollbackRejectedInsertedNode(state, renderer, mindMap) {
  if (!state?.nodeUid || !renderer || !mindMap) return false
  const runtimeNode = renderer.findNodeByUid?.(state.nodeUid)
  // updateData 会同步替换 renderTree、再于 RAF 重建 runtime。这个窗口里
  // findNodeByUid 仍可能返回旧树实例，因此始终解析当前持久树；只有两者
  // 确实指向同一 nodeData（或 renderTree 尚不可用）才走 runtime 删除路径。
  const persistedTreeRoot = renderer?.renderTree?.root || renderer?.renderTree
  const hasPersistedTree = Boolean(
    persistedTreeRoot && typeof persistedTreeRoot === 'object'
  )
  const persistedTarget = findPersistedRollbackTarget(renderer, state.nodeUid)
  const runtimeMatchesPersistedTree = Boolean(
    runtimeNode
    && persistedTarget
    && runtimeNode.nodeData === persistedTarget.node?.nodeData
  )
  const useRuntimeNode = Boolean(
    runtimeNode && (!hasPersistedTree || runtimeMatchesPersistedTree)
  )
  const currentNode = useRuntimeNode ? runtimeNode : persistedTarget?.node
  if (!isRollbackStateUnchanged(state, currentNode)) return false

  if (state.insertionType === 'parent') {
    const parentChildren = currentNode.parent?.nodeData?.children
    const currentIndex = Array.isArray(parentChildren)
      ? parentChildren.indexOf(currentNode.nodeData)
      : -1
    const promotedChildren = currentNode.nodeData?.children
    if (currentIndex < 0 || !Array.isArray(promotedChildren)) return false
    const promotedNodeUid = promotedChildren[0]?.data?.uid || ''
    if (useRuntimeNode) renderer.removeNodeFromActiveList?.(currentNode)
    parentChildren.splice(currentIndex, 1, ...promotedChildren)
    mindMap.render?.(() => {
      renderer.findNodeByUid?.(promotedNodeUid)?.active?.()
    })
  } else {
    if (useRuntimeNode) {
      renderer.removeNode?.([currentNode])
    } else {
      const fallbackActiveUid = persistedTarget?.remove()
      if (!fallbackActiveUid) return false
      mindMap.render?.(() => {
        renderer.findNodeByUid?.(fallbackActiveUid)?.active?.()
      })
    }
    // 概要没有兄弟节点，Render.removeNode 无法自动选择下一个节点；回到
    // 所属主题，避免一次租约失败让键盘焦点无故丢失。
    currentNode.generalizationBelongNode?.active?.()
  }

  // 若插入快照仍在节流窗口，这次 flush 会直接与旧基线去重；若插入已经
  // 保存，则立即产生对应删除批次，保证其他浏览器最终也不会保留幽灵节点。
  mindMap.command?.addHistory?.()
  mindMap.command?.flushPendingHistory?.()
  mindMap.emit?.('inserted_node_edit_rollback', currentNode, state.insertionType)
  return true
}
