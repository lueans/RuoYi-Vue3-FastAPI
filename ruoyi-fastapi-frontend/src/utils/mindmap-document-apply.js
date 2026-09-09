import { isSameObject } from '../libs/simple-mind-map/src/utils/deepEqual.js'
import { rebaseMindmapHistory } from './mindmap-history-rebase.js'
import {
  extractCrossNodeState,
  stripCrossNodeData,
} from './yjs-cross-node-state.js'
import { normalizeNodeDataForYjs } from './yjs-tree-state.js'

export function captureMindmapRuntimeSelectionUids(mindMap) {
  const uids = new Set()
  for (const node of (mindMap?.renderer?.activeNodeList || [])) {
    // 概要节点的 runtime uid 每次渲染都会变化；持久化 uid 才能在
    // updateData 生成的新树中恢复本地选区和正在编辑状态。
    const uid = node?.getData?.('uid') || node?.uid
    if (uid) uids.add(String(uid))
  }
  const editingNode = mindMap?.renderer?.textEdit?.getCurrentEditNode?.()
  const editingUid = editingNode?.getData?.('uid') || editingNode?.uid
  if (editingUid) uids.add(String(editingUid))
  return uids
}

function resolveRuntimeSelectionUids(mindMap, explicitUids) {
  if (explicitUids === undefined) {
    return captureMindmapRuntimeSelectionUids(mindMap)
  }
  return new Set(
    (Array.isArray(explicitUids) || explicitUids instanceof Set
      ? [...explicitUids]
      : []
    ).map(uid => String(uid || '').trim()).filter(Boolean),
  )
}

function getGeneralizationDataList(node) {
  const generalization = node?.data?.generalization
  if (Array.isArray(generalization)) return generalization
  return generalization && typeof generalization === 'object'
    ? [generalization]
    : []
}

/**
 * Expose a generalization entry through the same `node.data` contract used by
 * ordinary tree nodes. The setter deliberately writes through to the owning
 * node because simple-mind-map stores summaries in data.generalization rather
 * than in children.
 */
function createGeneralizationNodeReference(owner, index) {
  const getGeneralization = () => owner?.data?.generalization
  return {
    isGeneralization: true,
    generalizationOwner: owner,
    children: [],
    get uid() {
      return this.data?.uid
    },
    get data() {
      const generalization = getGeneralization()
      return Array.isArray(generalization)
        ? generalization[index]
        : index === 0
          ? generalization
          : undefined
    },
    set data(value) {
      const generalization = getGeneralization()
      if (Array.isArray(generalization)) {
        generalization[index] = value
      } else if (index === 0 && owner?.data) {
        owner.data.generalization = value
      }
    },
  }
}

function applyRuntimeSelection(root, activeUids) {
  if (!root) return
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    if (node.data && typeof node.data === 'object') {
      node.data.isActive = activeUids.has(String(node.data.uid || ''))
      for (const generalization of getGeneralizationDataList(node)) {
        if (!generalization || typeof generalization !== 'object') continue
        generalization.isActive = activeUids.has(
          String(generalization.uid || ''),
        )
      }
    }
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      pending.push(child)
    }
  }
}

/** Iteratively locate node identity so very deep or malformed trees cannot overflow the stack. */
export function findMindmapTreeNodeByUid(root, targetUid) {
  const normalizedTarget = typeof targetUid === 'string' ? targetUid.trim() : ''
  if (!root || !normalizedTarget) return null
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    if (String(node.data?.uid || node.uid || '') === normalizedTarget) return node
    const generalizationList = getGeneralizationDataList(node)
    for (let index = 0; index < generalizationList.length; index += 1) {
      const generalization = generalizationList[index]
      if (
        generalization
        && typeof generalization === 'object'
        && String(generalization.uid || '') === normalizedTarget
      ) {
        return createGeneralizationNodeReference(node, index)
      }
    }
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      pending.push(child)
    }
  }
  return null
}

/**
 * Whether simple-mind-map can keep a runtime node instance after applying the
 * supplied tree. A collapsed node remains visible itself but hides descendants;
 * a generalization additionally disappears when its owning node is collapsed.
 */
export function mindmapTreeNodeIsRuntimeVisible(root, targetUid) {
  root = root?.root || root
  const normalizedTarget = typeof targetUid === 'string' ? targetUid.trim() : ''
  if (!root || !normalizedTarget) return false
  const pending = [{ node: root, ancestorsExpanded: true }]
  const visited = new WeakSet()
  while (pending.length) {
    const { node, ancestorsExpanded } = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    const nodeUid = String(node.data?.uid || node.uid || '')
    if (nodeUid === normalizedTarget) return ancestorsExpanded

    const ownerExpanded = node.data?.expand !== false
    for (const generalization of getGeneralizationDataList(node)) {
      if (
        generalization
        && typeof generalization === 'object'
        && String(generalization.uid || '') === normalizedTarget
      ) return ancestorsExpanded && ownerExpanded
    }

    const descendantsVisible = ancestorsExpanded && ownerExpanded
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      pending.push({ node: child, ancestorsExpanded: descendantsVisible })
    }
  }
  return false
}

/**
 * Merge text that still lives only in an active DOM editor into an already
 * cloned recovery document. This never touches the live renderer/Y.Doc: it is
 * only used to make a pre-apply safety snapshot complete.
 */
export function applyMindmapActiveEditorTextSnapshots(document, snapshots = []) {
  const root = document?.root || document
  if (!root || !Array.isArray(snapshots)) return document
  for (const snapshot of snapshots) {
    const nodeUid = typeof snapshot?.nodeUid === 'string'
      ? snapshot.nodeUid.trim()
      : ''
    if (!nodeUid || typeof snapshot?.text !== 'string') continue
    const node = findMindmapTreeNodeByUid(root, nodeUid)
    if (!node) continue
    node.data = {
      ...(node.data && typeof node.data === 'object' ? node.data : {}),
      text: snapshot.text,
    }
    if (typeof snapshot.richText === 'boolean') {
      node.data.richText = snapshot.richText
    }
  }
  return document
}

/** Merge uncommitted relationship/outer-frame DOM labels into a cloned draft. */
export function applyMindmapActiveCrossNodeEditorSnapshots(document, snapshots = []) {
  const root = document?.root || document
  if (!root || !Array.isArray(snapshots)) return document
  for (const snapshot of snapshots) {
    if (typeof snapshot?.text !== 'string') continue
    if (snapshot.kind === 'associative-line') {
      const sourceUid = String(snapshot.sourceUid || '').trim()
      const targetUid = String(snapshot.targetUid || '').trim()
      if (!mindmapTreeContainsAssociativeLine(root, sourceUid, targetUid)) continue
      const source = findMindmapTreeNodeByUid(root, sourceUid)
      const currentText = source.data?.associativeLineText
      source.data = {
        ...(source.data && typeof source.data === 'object' ? source.data : {}),
        associativeLineText: {
          ...(currentText && typeof currentText === 'object' ? currentText : {}),
          [targetUid]: snapshot.text,
        },
      }
      continue
    }
    if (snapshot.kind !== 'outer-frame') continue
    const groupUid = String(snapshot.groupUid || '').trim()
    const memberUids = Array.isArray(snapshot.memberUids)
      ? [...new Set(snapshot.memberUids.map(uid => String(uid || '').trim()).filter(Boolean))]
      : []
    if (!mindmapTreeContainsExactOuterFrame(root, groupUid, memberUids)) continue
    for (const memberUid of memberUids) {
      const member = findMindmapTreeNodeByUid(root, memberUid)
      member.data = {
        ...member.data,
        outerFrame: {
          ...member.data.outerFrame,
          text: snapshot.text,
        },
      }
    }
  }
  return document
}

/** Iteratively check node identity so very deep or malformed trees cannot overflow the stack. */
export function mindmapTreeContainsNodeUid(root, targetUid) {
  return Boolean(findMindmapTreeNodeByUid(root, targetUid))
}

/**
 * Compare only the data owned by a node's inline editor. Structural changes,
 * local selection and independently synchronized cross-node records must not
 * interrupt typing on an otherwise unchanged node.
 */
export function mindmapTreeNodesHaveSameEditableData(
  currentRoot,
  remoteRoot,
  targetUid,
) {
  const currentNode = findMindmapTreeNodeByUid(currentRoot, targetUid)
  const remoteNode = findMindmapTreeNodeByUid(remoteRoot, targetUid)
  if (!currentNode || !remoteNode) return false
  return isSameObject(
    normalizeNodeDataForYjs(stripCrossNodeData(currentNode.data || {})),
    normalizeNodeDataForYjs(stripCrossNodeData(remoteNode.data || {})),
  )
}

/**
 * A relationship text editor may only be committed while the exact remote
 * relationship still exists. Checking both endpoint nodes is not enough: a
 * collaborator can delete the line without deleting either endpoint.
 */
export function mindmapTreeContainsAssociativeLine(root, sourceUid, targetUid) {
  const normalizedSourceUid = String(sourceUid || '').trim()
  const normalizedTargetUid = String(targetUid || '').trim()
  if (!normalizedSourceUid || !normalizedTargetUid) return false
  const source = findMindmapTreeNodeByUid(root, normalizedSourceUid)
  if (!source || !findMindmapTreeNodeByUid(root, normalizedTargetUid)) return false
  const targets = source.data?.associativeLineTargets
  return Array.isArray(targets) && targets.some(
    item => String(item || '').trim() === normalizedTargetUid,
  )
}

/**
 * Outer-frame text is duplicated over every member node by simple-mind-map.
 * Committing an editor against a remotely changed member set would therefore
 * restore removed members (or remove newly-added ones) when the cross-node Yjs
 * record is replaced. Only an unchanged group identity and member set is safe.
 */
export function mindmapTreeContainsExactOuterFrame(
  root,
  groupUid,
  memberUids = [],
) {
  const normalizedGroupUid = String(groupUid || '').trim()
  const expectedMembers = new Set(
    (Array.isArray(memberUids) ? memberUids : [])
      .map(uid => String(uid || '').trim())
      .filter(Boolean),
  )
  if (!root || !normalizedGroupUid || expectedMembers.size === 0) return false

  const actualMembers = new Set()
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    const uid = String(node.data?.uid || node.uid || '').trim()
    const outerFrame = node.data?.outerFrame
    if (
      uid
      && outerFrame
      && typeof outerFrame === 'object'
      && String(outerFrame.groupId || '').trim() === normalizedGroupUid
    ) actualMembers.add(uid)
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      pending.push(child)
    }
  }

  if (actualMembers.size !== expectedMembers.size) return false
  return [...expectedMembers].every(uid => actualMembers.has(uid))
}

/**
 * Cross-node Yjs records are currently synchronized as one collection after a
 * simple-mind-map detail event. A DOM-only relation/frame commit is therefore
 * safe only if no remote cross-node record changed while the editor was open;
 * otherwise the stale canvas would overwrite even an unrelated remote record.
 */
export function mindmapTreesHaveSameCrossNodeState(currentRoot, remoteRoot) {
  if (!currentRoot || !remoteRoot) return false
  return isSameObject(
    extractCrossNodeState(currentRoot),
    extractCrossNodeState(remoteRoot),
  )
}

/** Whether applying this document necessarily replaces renderer node instances. */
export function mindmapDocumentRequiresFullRuntimeReplacement(
  mindMap,
  document,
  currentDocument = null,
) {
  if (!mindMap || !document?.root) return false
  const current = currentDocument || mindMap.getData?.(true) || {}
  return (
    typeof mindMap.updateData !== 'function'
    || (
      document.layout !== undefined
      && document.layout !== current.layout
    )
    || (
      document.theme !== undefined
      && !isSameObject(document.theme, current.theme)
    )
  )
}

/**
 * 应用来自协作或保存合并的文档，同时尽量保留当前节点实例、选区和编辑器。
 * 只有布局或主题确实变化时才允许 simple-mind-map 执行完整数据替换。
 */
export function applyMindmapDocumentPreservingRuntimeState(
  mindMap,
  document,
  { runtimeSelectionUids: explicitRuntimeSelectionUids } = {},
) {
  if (!mindMap || !document?.root) return false
  const currentDocument = mindMap.getData?.(true) || {}
  const runtimeSelectionUids = resolveRuntimeSelectionUids(
    mindMap,
    explicitRuntimeSelectionUids,
  )

  // isActive 永远是当前客户端状态，包括会替换全部 runtime 的布局/主题
  // 分支。必须在分支判断前覆盖，避免 setFullData 采用协作者共享的旧选区。
  applyRuntimeSelection(document.root, runtimeSelectionUids)

  if (mindmapDocumentRequiresFullRuntimeReplacement(
    mindMap,
    document,
    currentDocument,
  )) {
    mindMap.setFullData(document)
    return 'full'
  }

  // 节点的 isActive 不是服务端文档状态。尤其在文本编辑期间，协作回放
  // 可能早于防抖后的 node_active 事件到达，因此还要把编辑节点作为本地
  // 选区恢复，避免编辑框存在但节点选中标记丢失。
  mindMap.updateData(document.root)
  if (
    document.view !== undefined
    && !isSameObject(document.view, currentDocument.view)
  ) {
    mindMap.view?.setTransformData?.(document.view)
  }
  return 'incremental'
}

/**
 * Apply a server/Yjs-authoritative document without letting simple-mind-map's
 * delayed history collector turn the applied snapshot back into a local edit.
 *
 * The command collector is throttled, so merely holding an outer "remote apply"
 * flag around updateData/setFullData is insufficient: its callback may run after
 * that flag has already been released.  Cancel it on both sides of the apply and
 * replace the undo baseline before command tracking is resumed.
 */
export function applyAuthoritativeMindmapDocument(
  mindMap,
  document,
  options = {},
) {
  if (!mindMap || !document?.root) return false
  const command = mindMap.command
  if (!command) {
    return applyMindmapDocumentPreservingRuntimeState(
      mindMap,
      document,
      options,
    )
  }

  command.addHistory?.cancel?.()
  const currentTree = command.getCopyData?.() || mindMap.getData?.()
  const rebasedHistory = (
    Array.isArray(command.history)
    && currentTree
  ) ? rebaseMindmapHistory({
      history: command.history,
      activeHistoryIndex: command.activeHistoryIndex,
      currentTree,
      remoteTree: document.root,
      maxHistoryCount: command.mindMap?.opt?.maxHistoryCount,
      maxHistoryMemoryBytes: command.mindMap?.opt?.maxHistoryMemoryBytes,
    }) : null
  const historyWasPaused = command.isPause === true
  command.pause?.()

  try {
    const result = applyMindmapDocumentPreservingRuntimeState(
      mindMap,
      document,
      options,
    )
    // updateData/setData schedule addHistory even while the command is paused;
    // cancelling before recovery is what closes the trailing-timer window.
    command.addHistory?.cancel?.()
    if (rebasedHistory) {
      command.history = rebasedHistory.history
      command.activeHistoryIndex = rebasedHistory.activeHistoryIndex
      mindMap.emit?.(
        'back_forward',
        command.activeHistoryIndex,
        command.history.length,
      )
    } else {
      // A conflicting undo stack must not survive the authoritative replace.
      // Keep one silent baseline so the very next local command can still emit
      // data_change_detail against a known previous tree.
      command.resetHistoryBaseline?.()
      if (!command.resetHistoryBaseline) command.clearHistory?.()
    }
    return result
  } catch (error) {
    command.addHistory?.cancel?.()
    // The renderer may already be partially updated.  Old undo snapshots are
    // unsafe in that state, so retain only the best current baseline available.
    command.resetHistoryBaseline?.()
    if (!command.resetHistoryBaseline) command.clearHistory?.()
    throw error
  } finally {
    if (!historyWasPaused) command.recovery?.()
  }
}
