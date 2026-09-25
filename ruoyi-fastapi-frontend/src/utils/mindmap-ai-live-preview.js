import { stableJsonValue } from './mindmap-ai-shared.js'
import { nextRevealedText } from '../libs/simple-mind-map/src/utils/textReveal.js'

// Match the backend document codec's TRANSIENT_KEYS and AI diff's
// IGNORED_DATA_FIELDS. Runtime exports retain these fields (for example,
// isActive:false), while authoritative cloud documents omit them.
const TRANSIENT_NODE_DATA_FIELDS = new Set([
  'isActive', 'inserting', 'needUpdate', 'resetRichText', 'activeStyle',
])

function uidOf(node) {
  const uid = node?.data?.uid
  return uid == null || uid === '' ? '' : String(uid)
}

function textOf(node) {
  return String(node?.data?.text || '')
}

function childrenOf(node) {
  return Array.isArray(node?.children) ? node.children : []
}

export function compareMindmapAiPreviewCoordinates(left = {}, right = {}) {
  const leftEpoch = Number.isInteger(Number(left.epoch)) && Number(left.epoch) >= 1
    ? Number(left.epoch)
    : 1
  const rightEpoch = Number.isInteger(Number(right.epoch)) && Number(right.epoch) >= 1
    ? Number(right.epoch)
    : 1
  if (leftEpoch !== rightEpoch) return leftEpoch > rightEpoch ? 1 : -1
  const leftVersion = Number.isInteger(Number(left.version)) ? Number(left.version) : -1
  const rightVersion = Number.isInteger(Number(right.version)) ? Number(right.version) : -1
  if (leftVersion === rightVersion) return 0
  return leftVersion > rightVersion ? 1 : -1
}

function walk(root, visitor, parentUid = null) {
  if (!uidOf(root)) return
  visitor(root, parentUid)
  for (const child of childrenOf(root)) {
    walk(child, visitor, uidOf(root))
  }
}

function collectNodes(root) {
  const nodes = new Map()
  walk(root, (node, parentUid) => {
    nodes.set(uidOf(node), { node, parentUid })
  })
  return nodes
}

function equal(valueA, valueB) {
  return JSON.stringify(stableJsonValue(valueA)) === JSON.stringify(stableJsonValue(valueB))
}

function comparableNodeData(node) {
  return Object.fromEntries(Object.entries(node?.data || {}).filter(([key]) => (
    key !== 'uid' && !TRANSIENT_NODE_DATA_FIELDS.has(key)
  )))
}

function nodeDataEqual(nodeA, nodeB) {
  // UID identity is already compared by collectNodes. Only exclude the exact
  // top-level transient keys: nested/custom business data must remain visible
  // to both semantic counters and the ordered playback planner.
  return nodeA?.data === nodeB?.data || equal(comparableNodeData(nodeA), comparableNodeData(nodeB))
}

function reorderedCommonSiblings(before, after) {
  const reordered = new Set()
  for (const [parentUid, beforeEntry] of before) {
    const afterEntry = after.get(parentUid)
    if (!afterEntry) continue
    if (beforeEntry.node.children === afterEntry.node.children) continue
    const beforeOrder = childrenOf(beforeEntry.node)
      .map(uidOf)
      .filter(uid => uid && after.get(uid)?.parentUid === parentUid)
    const afterOrder = childrenOf(afterEntry.node)
      .map(uidOf)
      .filter(uid => uid && before.get(uid)?.parentUid === parentUid)
    if (beforeOrder.length === afterOrder.length
      && beforeOrder.every((uid, index) => uid === afterOrder[index])) continue
    const afterIndex = new Map(afterOrder.map((uid, index) => [uid, index]))
    beforeOrder.forEach((uid, index) => {
      if (afterIndex.get(uid) !== index) reordered.add(uid)
    })
  }
  return reordered
}

function targetChanges(beforeRoot, afterRoot) {
  const before = collectNodes(beforeRoot)
  const after = collectNodes(afterRoot)
  const reordered = reorderedCommonSiblings(before, after)
  const additions = []
  const updates = []
  const moves = []
  const deletions = []
  const ordered = []
  for (const [uid, entry] of after) {
    const previous = before.get(uid)
    if (!previous) {
      const change = { uid, ...entry }
      additions.push(change)
      ordered.push({ kind: 'add', ...change })
    }
    else {
      if (!nodeDataEqual(previous.node, entry.node)) {
        const change = { uid, ...entry }
        updates.push(change)
        ordered.push({ kind: 'update', ...change })
      }
      if (previous.parentUid !== entry.parentUid || reordered.has(uid)) moves.push({ uid, ...entry })
    }
  }
  for (const [uid, entry] of before) {
    if (!after.has(uid)) deletions.push({ uid, ...entry })
  }
  return { before, after, additions, updates, moves, deletions, ordered }
}

export function countMindmapAiDraftNodes(root) {
  let count = 0
  walk(root, () => { count += 1 })
  return count
}

export function summarizeMindmapAiDraftChanges(beforeRoot, afterRoot) {
  const changes = targetChanges(beforeRoot, afterRoot)
  const summary = {
    added: changes.additions.length,
    updated: changes.updates.length,
    moved: changes.moves.length,
    deleted: changes.deletions.length,
  }
  return { ...summary, total: summary.added + summary.updated + summary.moved + summary.deleted }
}

export function describeMindmapAiDraftChange(beforeRoot, afterRoot) {
  return describeChange(targetChanges(beforeRoot, afterRoot), afterRoot)
}

function describeChange(changes, afterRoot) {
  const deleted = changes.deletions[0]
  if (deleted) {
    const parent = deleted.parentUid && changes.after.get(deleted.parentUid)
    return {
      kind: 'delete',
      uid: uidOf(parent?.node) || uidOf(afterRoot),
      text: textOf(deleted.node),
    }
  }
  const change = changes.ordered[0] || changes.moves[0]
  if (change) {
    return {
      kind: change.kind || 'move',
      uid: change.uid,
      text: textOf(change.node),
    }
  }
  return null
}

function materializeFrame(currentRoot, targetRoot, current, target, selectedUid, textPrefix) {
  const ready = new Set()
  const parents = new Map()
  const rootUid = current.has(uidOf(targetRoot)) || selectedUid === uidOf(targetRoot)
    ? uidOf(targetRoot)
    : uidOf(currentRoot)

  // A move depends on the ENTIRE target ancestor chain being present. Keeping
  // only the immediate parent would allow cycles during ancestor/child swaps.
  // Until the dependency is satisfied, retain the old location and any old
  // containers needed to keep the existing subtree continuously visible.
  for (const [uid, entry] of target) {
    if (!current.has(uid) && uid !== selectedUid) continue
    if (entry.parentUid === null || ready.has(entry.parentUid)) {
      ready.add(uid)
      parents.set(uid, entry.parentUid)
    } else if (current.has(uid)) {
      parents.set(uid, current.get(uid).parentUid)
    }
  }
  for (const [uid] of parents) {
    if (ready.has(uid)) continue
    let parentUid = current.get(uid)?.parentUid
    while (parentUid && parentUid !== rootUid && !parents.has(parentUid)) {
      const ancestor = current.get(parentUid)
      if (!ancestor) break
      parents.set(parentUid, ancestor.parentUid)
      parentUid = ancestor.parentUid
    }
  }
  // A replaced root cannot remain an invisible parent of deferred branches.
  const previousRootUid = uidOf(currentRoot)
  if (rootUid !== previousRootUid && !target.has(previousRootUid)) parents.delete(previousRootUid)
  parents.set(rootUid, null)
  for (const [uid, parentUid] of parents) {
    if (uid !== rootUid && !parents.has(parentUid)) parents.set(uid, rootUid)
  }

  const childUids = new Map([...parents.keys()].map(uid => [uid, []]))
  for (const [uid, parentUid] of parents) {
    if (parentUid !== null) childUids.get(parentUid)?.push(uid)
  }
  for (const [uid, attachedChildren] of childUids) {
    const attached = new Set(attachedChildren)
    const currentOrder = childrenOf(current.get(uid)?.node).map(uidOf)
    const preferredOrder = ready.has(uid)
      ? childrenOf(target.get(uid)?.node).map(uidOf)
      : currentOrder
    const ordered = preferredOrder.filter(childUid => attached.has(childUid))
    const orderedSet = new Set(ordered)
    currentOrder.forEach((childUid, index) => {
      if (attached.has(childUid) && !orderedSet.has(childUid)) {
        ordered.splice(Math.min(index, ordered.length), 0, childUid)
        orderedSet.add(childUid)
      }
    })
    for (const childUid of attachedChildren) {
      if (!orderedSet.has(childUid)) ordered.push(childUid)
    }
    childUids.set(uid, ordered)
  }

  function materialize(uid) {
    const currentNode = current.get(uid)?.node
    const targetNode = target.get(uid)?.node
    const source = uid === selectedUid && targetNode ? targetNode : currentNode
    const nextChildren = childUids.get(uid).map(materialize)
    const data = uid === selectedUid && textPrefix != null ? { ...source.data, text: textPrefix } : source.data
    if (source === currentNode && data === currentNode.data
      && nextChildren.length === childrenOf(currentNode).length
      && nextChildren.every((child, index) => child === childrenOf(currentNode)[index])) {
      return currentNode
    }
    return {
      ...source,
      data,
      ...(nextChildren.length || Array.isArray(source.children) ? { children: nextChildren } : {}),
    }
  }

  return { root: materialize(rootUid), nodeCount: parents.size }
}

export function nextMindmapAiDraftFrame(currentDocument, targetDocument) {
  if (!currentDocument || !targetDocument) return { document: targetDocument, remaining: 0 }
  // The presentation document and the authoritative target deliberately have
  // different lifetimes. Layout/theme/view metadata must never short-circuit
  // node playback: doing so exposes the complete cloud tree for one frame and
  // then makes the typewriter appear to restart. Keep presentation metadata
  // frozen until the authoritative commit that follows playback.
  const changes = targetChanges(currentDocument.root, targetDocument.root)
  const pending = changes.ordered
  if (!pending.length && !changes.moves.length && !changes.deletions.length) {
    return {
      document: currentDocument,
      remaining: 0,
      rootUnchanged: true,
      nodeCount: changes.before.size,
    }
  }
  // One node, one grapheme per acknowledged frame. There is no batch/full-tree
  // playback mode: terminal and retargeted snapshots follow the same contract.
  const selected = pending[0]
  const currentNode = changes.before.get(selected?.uid)?.node
  const selectedText = textOf(selected?.node)
  const currentText = textOf(currentNode)
  let renderedText = selectedText
  if (selectedText && currentText !== selectedText) {
    renderedText = nextRevealedText(currentText, selectedText,
      selected.node.data.richText === true,
      currentNode?.data?.richText === true,
    )
  }
  const materialized = materializeFrame(
    currentDocument.root, targetDocument.root, changes.before, changes.after,
    selected?.uid, renderedText !== selectedText ? renderedText : null,
  )
  const document = {
    // Retain the currently displayed layout/theme/view throughout playback.
    // Only the root advances toward the newest cloud target.
    ...currentDocument,
    root: materialized.root,
  }
  const textStillPending = selected && selectedText !== renderedText
  const frame = {
    document,
    remaining: pending.length - (selected ? 1 : 0) + (textStillPending ? 1 : 0),
    nodeCount: materialized.nodeCount,
    change: selected
      ? { kind: selected.kind, uid: selected.uid, text: renderedText }
      : describeChange(changes, document.root),
  }
  if (selected) {
    frame.typewriterTarget = { uid: selected.uid, text: selectedText }
  }
  return frame
}
