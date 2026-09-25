import { cloneJsonValueIterative, stringifyJsonValueIterative } from '../libs/simple-mind-map/src/utils/jsonClone.js'

// The only writer to the AI presentation surface. Targets are never installed
// as node text: they are used by createTextNode for detached measurement only.
function singleTextDelta(before, after) {
  const pending = [{ before, after, ancestors: [] }]
  let delta = null
  while (pending.length) {
    const { before: old, after: node, ancestors } = pending.pop()
    // Planner frames retain untouched subtree references. A shared subtree
    // cannot contain another delta, so don't index or serialize it again.
    if (old === node) continue
    if (!old || !node || String(old.data.uid) !== String(node.data.uid)) return null
    const { text: oldText, ...oldData } = old.data
    const { text, ...data } = node.data
    if (old.data !== node.data && JSON.stringify(oldData) !== JSON.stringify(data)) return null
    const oldChildren = old.children || []
    const children = node.children || []
    if (oldChildren.length !== children.length) return null
    if (oldText !== text) {
      if (delta) return null
      delta = { uid: String(node.data.uid), text, ancestors }
    }
    for (let index = 0; index < children.length; index++) {
      if (oldChildren[index] !== children[index]) {
        pending.push({ before: oldChildren[index], after: children[index], ancestors: [...ancestors, node] })
      }
    }
  }
  return delta
}

export async function clearMindmapAiPresentation(mindMap, { render = true } = {}) {
  const renderer = mindMap?.renderer
  if (!renderer) return false
  const generation = (renderer.aiPresentationCleanupGeneration || 0) + 1
  renderer.aiPresentationCleanupGeneration = generation
  renderer.aiPresentationCleanupCancel?.(new Error('AI 展示清理已被新会话替代'))
  renderer.aiPresentationCleanupCancel = null
  renderer.textRevealTargets?.clear()
  if (renderer.aiPresentationExpandedNodeUids?.size) {
    renderer.aiPresentationExpandedNodeUids.clear()
    renderer.aiPresentationVisibilityRestorePending = true
  }
  if (!render || renderer.destroyed || !renderer.aiPresentationVisibilityRestorePending) return false
  // Keep the pending marker on failure so retry cannot silently skip restoring
  // the original cloud expansion state after the overlay was already cleared.
  try {
    await waitForPreviewRender(mindMap, 'ai_preview_visibility_cleanup', () => {}, operation => {
      renderer.aiPresentationCleanupCancel = error => operation?.cancel(error)
    })
  } finally {
    if (renderer.aiPresentationCleanupGeneration === generation) renderer.aiPresentationCleanupCancel = null
  }
  if (renderer.aiPresentationCleanupGeneration !== generation) return false
  renderer.aiPresentationVisibilityRestorePending = false
  return true
}

function waitForPreviewRender(mindMap, source, prepare = () => {}, onOperation = () => {}) {
  return new Promise((resolve, reject) => {
    let settled = false
    let operation
    const fail = error => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      reject(error)
    }
    const timeout = setTimeout(() => {
      const error = new Error('AI 画布渲染超时，请重试同步')
      // Cancellation belongs to this request; a late timer cannot abort a
      // newer renderer transaction after this one has already completed.
      operation?.cancel(error)
      fail(error)
    }, 15000)
    try {
      prepare()
      operation = mindMap.renderAsync(() => {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        resolve(true)
      }, source, fail)
      onOperation(operation)
    } catch (error) {
      fail(error)
    }
  })
}

export function renderMindmapAiPreviewTree(mindMap, root) {
  if (!mindMap?.renderer || !root) return Promise.reject(new Error('脑图渲染器尚未就绪'))
  return waitForPreviewRender(mindMap, 'ai_live_preview', () => {
    // Preserve runtime identity, lines, selection and camera. No setFullData,
    // clearDraw, history entry or editable command is used for playback.
    // Draft snapshots can be Vue reactive proxies. Native structuredClone
    // rejects those; the document clone also handles deep trees safely.
    const tree = cloneJsonValueIterative(root)
    if (!tree) throw new Error('AI 草稿数据无法序列化')
    mindMap.renderer.setData(tree)
  })
}

function revealAncestors(renderer, ancestors) {
  const expanded = renderer.aiPresentationExpandedNodeUids ||= new Set()
  let changed = false
  for (const ancestor of ancestors) {
    const ancestorUid = String(ancestor.data.uid)
    if (ancestor.data.expand === false && !expanded.has(ancestorUid)) {
      expanded.add(ancestorUid)
      changed = true
    }
  }
  return changed
}

function revealTargetAncestors(renderer, root, uid) {
  if (!uid || !root) return false
  const pending = [{ node: root, ancestors: [] }]
  while (pending.length) {
    const { node, ancestors } = pending.pop()
    if (String(node.data.uid) === String(uid)) {
      return revealAncestors(renderer, ancestors)
    }
    for (const child of node.children || []) pending.push({ node: child, ancestors: [...ancestors, node] })
  }
  return false
}

export async function applyMindmapAiPresentationFrame(mindMap, previousDocument, frame) {
  const target = frame.typewriterTarget
  const targetUid = target?.uid || frame.change?.uid
  const delta = singleTextDelta(previousDocument?.root, frame.document.root)
  const visibilityChanged = delta && delta.uid === String(targetUid)
    ? revealAncestors(mindMap.renderer, delta.ancestors)
    : revealTargetAncestors(mindMap.renderer, frame.document.root, targetUid)
  const targets = mindMap.renderer.textRevealTargets ||= new Map()
  targets.clear()
  if (target) targets.set(String(target.uid), { text: String(target.text ?? '') })
  const node = delta && mindMap.renderer.findNodeByUid(delta.uid)
  if (!visibilityChanged && !mindMap.renderer.renderRecoveryRequired
    && node && target && String(target.uid) === delta.uid) {
    try {
      node.nodeData.data.text = delta.text
      if (node._textData?.reveal?.targetText === target.text) {
        node._textData.reveal.setVisible(delta.text)
        node.nodeDataSnapshot = stringifyJsonValueIterative(node.getData())
        return
      }
      // First character of an edit: measure once, mask before layout mounts it.
      const sizeChanged = node.reRender()
      if (!sizeChanged) return
    } catch (error) {
      // getSize may have replaced _textData before layout/update failed. That
      // reveal object is not reusable: retry must rebuild through a transaction.
      mindMap.renderer.renderRecoveryRequired = true
      throw error
    }
  }
  // A structural frame introduces only its selected node and prefix. The
  // renderer's detached measurement hook applies the mask BEFORE insertion.
  await renderMindmapAiPreviewTree(mindMap, frame.document.root)
}
