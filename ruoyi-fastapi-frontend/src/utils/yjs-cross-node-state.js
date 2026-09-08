/**
 * Cross-node simple-mind-map state stored outside Yjs node payloads.
 *
 * Keeping these records in independent maps narrows the collaboration conflict
 * domain: editing a relation no longer replaces the source node, and repeated
 * outer-frame definitions are represented by one group with stable members.
 */

import { cloneJsonValueIterative } from '../libs/simple-mind-map/src/utils/jsonClone.js'
import { isSameObject } from '../libs/simple-mind-map/src/utils/deepEqual.js'

export const CROSS_NODE_DATA_KEYS = Object.freeze([
  'associativeLineTargets',
  'associativeLineTargetControlOffsets',
  'associativeLinePoint',
  'associativeLineText',
  'associativeLineStyle',
  'generalization',
  'outerFrame',
  'imgMap',
])

const CROSS_NODE_DATA_KEY_SET = new Set(CROSS_NODE_DATA_KEYS)

function cloneValue(value) {
  if (value === undefined) return undefined
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value)
    } catch {
      // Native structuredClone implementations commonly recurse internally
      // and overflow on otherwise valid deeply nested JSON. Fall through to
      // the stack-safe document clone. The equality check below prevents that
      // JSON-compatible fallback from silently coercing unsupported values.
    }
  }
  const cloned = cloneJsonValueIterative(value)
  if (
    (cloned === null && value !== null && typeof value === 'object')
    || !isSameObject(cloned, value)
  ) {
    throw new TypeError('跨节点协作数据无法安全复制')
  }
  return cloned
}

function entriesOf(collection) {
  if (!collection) return []
  if (collection instanceof Map || typeof collection.entries === 'function') {
    return Array.from(collection.entries())
  }
  return Object.entries(collection)
}

function compareStableStrings(left, right) {
  left = String(left)
  right = String(right)
  return left < right ? -1 : (left > right ? 1 : 0)
}

export function stripCrossNodeData(data = {}) {
  return Object.fromEntries(
    Object.entries(data).filter(([key]) => !CROSS_NODE_DATA_KEY_SET.has(key))
  )
}

export function nodeContainsCrossNodeData(node) {
  const data = node?.data
  return Boolean(data && CROSS_NODE_DATA_KEYS.some(key => (
    Object.prototype.hasOwnProperty.call(data, key)
  )))
}

function getDetailNodeData(node) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return null
  return (
    Array.isArray(node.children)
    && node.data
    && typeof node.data === 'object'
    && !Array.isArray(node.data)
  ) ? node.data : node
}

export function detailListTouchesCrossNodeState(detailList = []) {
  return detailList.some(detail => {
    if (detail?.action === 'delete') return true
    const nextData = getDetailNodeData(detail?.data)
    const previousData = getDetailNodeData(detail?.oldData)
    if (detail?.action === 'update' && !previousData) {
      // Legacy/plugin detail emitters may provide only an authoritative next
      // snapshot. Absence of every cross key can itself mean "remove all".
      return true
    }
    if (detail?.action !== 'update') {
      return nodeContainsCrossNodeData({ data: nextData })
        || nodeContainsCrossNodeData({ data: previousData })
    }
    const dataChanged = CROSS_NODE_DATA_KEYS.some(key => {
      const previousHasKey = Object.prototype.hasOwnProperty.call(previousData, key)
      const nextHasKey = Object.prototype.hasOwnProperty.call(nextData || {}, key)
      return previousHasKey !== nextHasKey
        || (previousHasKey && !isSameObject(previousData[key], nextData[key]))
    })
    if (dataChanged) return true

    // Generalization endpoints are stored as child UIDs, while the component
    // model stores numeric ranges. Reordering children changes that derived
    // record even when the generalization payload itself is unchanged.
    const ownsSummaries = Object.prototype.hasOwnProperty.call(previousData, 'generalization')
      || Object.prototype.hasOwnProperty.call(nextData || {}, 'generalization')
    if (!ownsSummaries) return false
    const previousChildren = Array.isArray(detail?.oldData?.children)
      ? detail.oldData.children.map(child => String(child?.data?.uid || ''))
      : null
    const nextChildren = Array.isArray(detail?.data?.children)
      ? detail.data.children.map(child => String(child?.data?.uid || ''))
      : null
    return previousChildren !== null
      && nextChildren !== null
      && !isSameObject(previousChildren, nextChildren)
  })
}

/** Convert the expanded component representation into stable top-level records. */
export function extractCrossNodeState(root, { validateReferences = true } = {}) {
  root = root?.root || root
  const relations = {}
  const summaries = {}
  const groups = {}
  const assets = {}
  const nodeUids = new Set()

  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    const data = node.data || {}
    const sourceUid = data.uid === undefined || data.uid === null ? '' : String(data.uid)
    if (sourceUid) nodeUids.add(sourceUid)
    const children = Array.isArray(node.children) ? node.children : []

    const targets = Array.isArray(data.associativeLineTargets)
      ? data.associativeLineTargets
      : []
    const offsets = Array.isArray(data.associativeLineTargetControlOffsets)
      ? data.associativeLineTargetControlOffsets
      : []
    const points = Array.isArray(data.associativeLinePoint) ? data.associativeLinePoint : []
    const texts = data.associativeLineText && typeof data.associativeLineText === 'object'
      ? data.associativeLineText
      : {}
    const styles = data.associativeLineStyle && typeof data.associativeLineStyle === 'object'
      ? data.associativeLineStyle
      : {}
    if (sourceUid) {
      targets.forEach((targetValue, sortOrder) => {
        if (targetValue === undefined || targetValue === null || targetValue === '') return
        const targetUid = String(targetValue)
        relations[`assoc:${sourceUid}:${targetUid}`] = {
          relationUid: `assoc:${sourceUid}:${targetUid}`,
          relationType: 'associative_line',
          sourceUid,
          targetUid,
          text: cloneValue(texts[targetUid]),
          controlData: {
            offsets: cloneValue(offsets[sortOrder]),
            point: cloneValue(points[sortOrder]),
          },
          styleData: cloneValue(styles[targetUid]),
          sortOrder,
        }
      })
    }

    const generalizations = Array.isArray(data.generalization)
      ? data.generalization
      : (data.generalization && typeof data.generalization === 'object'
          ? [data.generalization]
          : [])
    const childUids = children.map(child => String(child?.data?.uid || ''))
    generalizations.forEach((item, sortOrder) => {
      if (!sourceUid || !item || typeof item !== 'object') return
      const payload = cloneValue(item)
      const rawSummaryUid = payload.uid
      const summaryUid = rawSummaryUid === undefined || rawSummaryUid === null
        ? ''
        : String(rawSummaryUid)
      delete payload.uid
      const range = payload.range
      delete payload.range
      const startIndex = Array.isArray(range) ? range[0] : undefined
      const endIndex = Array.isArray(range) ? range[1] : undefined
      summaries[`${sourceUid}:${summaryUid || `index:${sortOrder}`}`] = {
        summaryUid,
        ownerUid: sourceUid,
        startChildUid: Number.isInteger(startIndex) ? childUids[startIndex] || null : null,
        endChildUid: Number.isInteger(endIndex) ? childUids[endIndex] || null : null,
        payload,
        sortOrder,
      }
    })

    const outerFrame = data.outerFrame
    if (sourceUid && outerFrame && typeof outerFrame === 'object' && outerFrame.groupId) {
      const groupUid = String(outerFrame.groupId)
      if (!groups[groupUid]) {
        const payload = cloneValue(outerFrame)
        delete payload.groupId
        groups[groupUid] = {
          groupUid,
          groupType: 'outer_frame',
          payload,
          memberUids: [],
        }
      }
      if (!groups[groupUid].memberUids.includes(sourceUid)) {
        groups[groupUid].memberUids.push(sourceUid)
      }
    }

    if (data.imgMap && typeof data.imgMap === 'object' && !Array.isArray(data.imgMap)) {
      for (const [assetKey, uri] of Object.entries(data.imgMap)) {
        assets[String(assetKey)] = { assetKey: String(assetKey), uri: cloneValue(uri) }
      }
    }

    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push(children[index])
    }
  }
  if (validateReferences) {
    for (const [key, relation] of Object.entries(relations)) {
      if (!nodeUids.has(relation.sourceUid) || !nodeUids.has(relation.targetUid)) {
        delete relations[key]
      }
    }
  }
  // Group membership is a set. Canonicalizing it prevents two equivalent
  // trees with different traversal order from producing different records.
  for (const group of Object.values(groups)) {
    group.memberUids.sort(compareStableStrings)
  }
  return { relations, summaries, groups, assets }
}

const CROSS_NODE_STATE_DOMAINS = Object.freeze([
  'relations',
  'summaries',
  'groups',
  'assets',
])

function asCrossNodeStateObject(state = {}) {
  return Object.fromEntries(CROSS_NODE_STATE_DOMAINS.map(domain => [
    domain,
    Object.fromEntries(entriesOf(state[domain])),
  ]))
}

function asDetailTree(node) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return null
  if (
    node.data
    && typeof node.data === 'object'
    && !Array.isArray(node.data)
    && Array.isArray(node.children)
  ) return node
  return { data: node, children: [] }
}

function collectDetailTreeNodeUids(root, target = new Set()) {
  if (!root || typeof root !== 'object') return target
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    const uid = node.data?.uid
    if (uid !== undefined && uid !== null && String(uid)) target.add(String(uid))
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      pending.push(child)
    }
  }
  return target
}

function rememberCrossNodeTransitions(transitions, previousState, nextState) {
  for (const domain of CROSS_NODE_STATE_DOMAINS) {
    const previous = previousState[domain] || {}
    const next = nextState[domain] || {}
    for (const key of new Set([...Object.keys(previous), ...Object.keys(next)])) {
      const previousHasKey = Object.prototype.hasOwnProperty.call(previous, key)
      const nextHasKey = Object.prototype.hasOwnProperty.call(next, key)
      if (
        previousHasKey === nextHasKey
        && (!previousHasKey || isSameObject(previous[key], next[key]))
      ) continue
      const current = transitions[domain].get(key)
      if (current) {
        current.nextHasKey = nextHasKey
        current.next = next[key]
      } else {
        transitions[domain].set(key, {
          previousHasKey,
          previous: previous[key],
          nextHasKey,
          next: next[key],
        })
      }
    }
  }
}

function recordReferencesAnyNode(domain, record, nodeUids) {
  if (!record || nodeUids.size === 0) return false
  if (domain === 'relations') {
    return nodeUids.has(String(record.sourceUid || ''))
      || nodeUids.has(String(record.targetUid || ''))
  }
  if (domain === 'summaries') {
    return nodeUids.has(String(record.ownerUid || ''))
      || nodeUids.has(String(record.startChildUid || ''))
      || nodeUids.has(String(record.endChildUid || ''))
  }
  if (domain === 'groups') {
    return (record.memberUids || []).some(uid => nodeUids.has(String(uid)))
  }
  return false
}

function isPlainRecord(value) {
  return Boolean(
    value
    && typeof value === 'object'
    && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype,
  )
}

function setOwnRecordValue(target, key, value) {
  Object.defineProperty(target, key, {
    configurable: true,
    enumerable: true,
    value,
    writable: true,
  })
}

function createJsonMergeFrame({
  output,
  previous,
  next,
  parent = null,
  restore = null,
}) {
  return {
    output,
    previous,
    next,
    parent,
    changed: false,
    restore,
    keys: [...new Set([...Object.keys(previous), ...Object.keys(next)])],
    index: 0,
  }
}

/** Apply only the JSON fields changed between the local before/after values. */
export function mergeJsonValueDelta(existingValue, previousValue, nextValue) {
  if (!isPlainRecord(previousValue) || !isPlainRecord(nextValue)) {
    return cloneValue(
      isSameObject(previousValue, nextValue) ? existingValue : nextValue,
    )
  }

  const existingIsRecord = isPlainRecord(existingValue)
  const result = existingIsRecord ? cloneValue(existingValue) : {}
  const rootFrame = createJsonMergeFrame({
    output: result,
    previous: previousValue,
    next: nextValue,
  })
  const pending = [rootFrame]
  while (pending.length) {
    const frame = pending.at(-1)
    if (frame.index >= frame.keys.length) {
      pending.pop()
      if (!frame.changed && frame.restore) {
        if (frame.restore.hadKey) {
          setOwnRecordValue(
            frame.restore.output,
            frame.restore.key,
            frame.restore.value,
          )
        } else {
          delete frame.restore.output[frame.restore.key]
        }
      }
      if (frame.changed && frame.parent) frame.parent.changed = true
      continue
    }

    const key = frame.keys[frame.index]
    frame.index += 1
    const previousHasKey = Object.prototype.hasOwnProperty.call(frame.previous, key)
    const nextHasKey = Object.prototype.hasOwnProperty.call(frame.next, key)
    const previousChildValue = previousHasKey ? frame.previous[key] : undefined
    const nextChildValue = nextHasKey ? frame.next[key] : undefined
    if (
      previousHasKey === nextHasKey
      && previousHasKey
      && previousChildValue === nextChildValue
    ) continue
    if (!nextHasKey) {
      delete frame.output[key]
      frame.changed = true
      continue
    }

    if (!previousHasKey) {
      setOwnRecordValue(frame.output, key, cloneValue(nextChildValue))
      frame.changed = true
      continue
    }

    if (isPlainRecord(previousChildValue) && isPlainRecord(nextChildValue)) {
      const outputHadKey = Object.prototype.hasOwnProperty.call(frame.output, key)
      const previousOutputValue = outputHadKey ? frame.output[key] : undefined
      const outputChildIsRecord = isPlainRecord(previousOutputValue)
      const outputChild = outputChildIsRecord ? previousOutputValue : {}
      if (!outputChildIsRecord) setOwnRecordValue(frame.output, key, outputChild)
      pending.push(createJsonMergeFrame({
        output: outputChild,
        previous: previousChildValue,
        next: nextChildValue,
        parent: frame,
        restore: outputChildIsRecord ? null : {
          output: frame.output,
          key,
          hadKey: outputHadKey,
          value: previousOutputValue,
        },
      }))
      continue
    }

    if (isSameObject(previousChildValue, nextChildValue)) continue
    setOwnRecordValue(frame.output, key, cloneValue(nextChildValue))
    frame.changed = true
  }
  return rootFrame.changed || existingIsRecord
    ? result
    : cloneValue(existingValue)
}

export function mergeGroupMemberDelta(existingMembers, previousMembers, nextMembers) {
  const previous = new Set((previousMembers || []).map(String))
  const next = new Set((nextMembers || []).map(String))
  const removed = new Set([...previous].filter(uid => !next.has(uid)))
  const merged = new Set(
    (existingMembers || []).map(String).filter(uid => !removed.has(uid)),
  )
  for (const uid of next) {
    if (!previous.has(uid)) merged.add(uid)
  }
  return [...merged].sort(compareStableStrings)
}

const DELETE_CROSS_NODE_RECORD = Symbol('delete-cross-node-record')

function mergeCrossNodeRecord(domain, existingRecord, transition) {
  if (domain !== 'groups' && !transition.nextHasKey) {
    return DELETE_CROSS_NODE_RECORD
  }
  if (domain === 'groups' && !transition.nextHasKey) {
    const remainingMembers = mergeGroupMemberDelta(
      existingRecord?.memberUids,
      transition.previous?.memberUids,
      [],
    )
    // A group disappearing from the component tree usually means its last
    // local member was removed, not that the logical group was hard-deleted.
    // Keep an empty record so a concurrent collaborator adding another member
    // is not hidden by a record-level tombstone. Empty groups are not rendered.
    return {
      ...cloneValue(existingRecord || transition.previous || {}),
      memberUids: remainingMembers,
    }
  }

  const merged = mergeJsonValueDelta(
    existingRecord,
    transition.previousHasKey ? transition.previous : {},
    transition.next,
  )
  if (domain === 'groups') {
    merged.memberUids = mergeGroupMemberDelta(
      existingRecord?.memberUids,
      transition.previousHasKey ? transition.previous?.memberUids : [],
      transition.next?.memberUids,
    )
  }
  return merged
}

/**
 * Build a record-level cross-node patch from simple-mind-map history details.
 * Untouched records are intentionally absent so an already-received remote
 * change cannot be rolled back by a stale runtime snapshot.
 */
export function buildCrossNodeStateDelta(
  detailList = [],
  currentRoot,
  existingState = {},
  runtimePreviousState = null,
) {
  currentRoot = currentRoot?.root || currentRoot
  const desiredState = extractCrossNodeState(currentRoot)
  const normalizedExistingState = asCrossNodeStateObject(existingState)
  const transitions = Object.fromEntries(
    CROSS_NODE_STATE_DOMAINS.map(domain => [domain, new Map()]),
  )
  const deletedNodeUids = new Set()

  // A detail without oldData cannot use the current Y.Map as its before state:
  // it may already contain remote records not rendered into the stale canvas.
  // The runtime shadow represents exactly what the user saw before this local
  // operation, so a full before/after diff remains safe for legacy emitters.
  if (runtimePreviousState) {
    rememberCrossNodeTransitions(
      transitions,
      asCrossNodeStateObject(runtimePreviousState),
      desiredState,
    )
  }

  for (const detail of (Array.isArray(detailList) ? detailList : [])) {
    const action = detail?.action
    const previousTree = asDetailTree(
      detail?.oldData || (action === 'delete' ? detail?.data : null),
    )
    const nextTree = action === 'delete' ? null : asDetailTree(detail?.data)
    if (!runtimePreviousState && !(action === 'update' && !detail?.oldData)) {
      const previousState = extractCrossNodeState(previousTree, {
        validateReferences: false,
      })
      const nextState = extractCrossNodeState(nextTree, {
        validateReferences: false,
      })
      rememberCrossNodeTransitions(transitions, previousState, nextState)
    }

    if (action === 'delete') {
      collectDetailTreeNodeUids(previousTree, deletedNodeUids)
    }
  }

  if (deletedNodeUids.size > 0) {
    for (const [key, relation] of Object.entries(normalizedExistingState.relations)) {
      if (
        !transitions.relations.has(key)
        && recordReferencesAnyNode('relations', relation, deletedNodeUids)
      ) {
        transitions.relations.set(key, {
          previousHasKey: true,
          previous: relation,
          nextHasKey: false,
          next: undefined,
        })
      }
    }
    for (const [key, summary] of Object.entries(normalizedExistingState.summaries)) {
      if (
        transitions.summaries.has(key)
        || !recordReferencesAnyNode('summaries', summary, deletedNodeUids)
      ) continue
      const desired = desiredState.summaries[key]
      transitions.summaries.set(key, {
        previousHasKey: true,
        previous: summary,
        nextHasKey: Boolean(desired),
        next: desired,
      })
    }
    for (const [key, group] of Object.entries(normalizedExistingState.groups)) {
      if (transitions.groups.has(key)) continue
      const removedMembers = (group.memberUids || []).filter(uid => (
        deletedNodeUids.has(String(uid))
      ))
      if (!removedMembers.length) continue
      transitions.groups.set(key, {
        previousHasKey: true,
        previous: group,
        nextHasKey: true,
        next: {
          ...group,
          memberUids: (group.memberUids || []).filter(uid => (
            !deletedNodeUids.has(String(uid))
          )),
        },
      })
    }
  }

  let hasChanges = false
  const delta = {}
  for (const domain of CROSS_NODE_STATE_DOMAINS) {
    const upserts = {}
    const deletedKeys = []
    const entries = [...transitions[domain].entries()]
      .sort(([left], [right]) => compareStableStrings(left, right))
    for (const [key, transition] of entries) {
      const existingHasKey = Object.prototype.hasOwnProperty.call(
        normalizedExistingState[domain],
        key,
      )
      // The record existed on the rendered canvas but has already been
      // deleted remotely. Match the node update-vs-delete policy: deletion
      // wins, rather than resurrecting a partial record from changed fields.
      if (
        transition.previousHasKey
        && transition.nextHasKey
        && !existingHasKey
      ) continue
      const existingRecord = normalizedExistingState[domain][key]
      const mergedRecord = mergeCrossNodeRecord(domain, existingRecord, transition)
      if (mergedRecord === DELETE_CROSS_NODE_RECORD) {
        if (existingHasKey) {
          deletedKeys.push(key)
        }
        continue
      }
      if (
        !existingHasKey
        || !isSameObject(existingRecord, mergedRecord)
      ) {
        upserts[key] = mergedRecord
      }
    }
    if (Object.keys(upserts).length || deletedKeys.length) hasChanges = true
    delta[domain] = { upserts, deletedKeys }
  }
  return hasChanges ? delta : null
}

/** Expand top-level records back into the exact shape simple-mind-map expects. */
export function applyCrossNodeState(root, state = {}) {
  root = root?.root || root
  if (!root) return root
  const nodes = new Map()
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    node.data = stripCrossNodeData(node.data || {})
    const uid = node.data.uid
    if (uid !== undefined && uid !== null) nodes.set(String(uid), node)
    const children = Array.isArray(node.children) ? node.children : []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push(children[index])
    }
  }

  const relationsBySource = new Map()
  for (const [recordKey, relation] of entriesOf(state.relations)) {
    if (!relation || relation.relationType && relation.relationType !== 'associative_line') continue
    const sourceUid = String(relation.sourceUid || '')
    const targetUid = String(relation.targetUid || '')
    if (!nodes.has(sourceUid) || !nodes.has(targetUid)) continue
    const rows = relationsBySource.get(sourceUid) || []
    rows.push({ recordKey: String(recordKey), record: relation })
    relationsBySource.set(sourceUid, rows)
  }
  for (const [sourceUid, rows] of relationsBySource) {
    rows.sort((left, right) => (
      Number(left.record.sortOrder || 0) - Number(right.record.sortOrder || 0)
      || compareStableStrings(
        left.record.relationUid || left.recordKey,
        right.record.relationUid || right.recordKey,
      )
    ))
    const targets = []
    const offsets = []
    const points = []
    const texts = {}
    const styles = {}
    for (const { record: row } of rows) {
      const targetUid = String(row.targetUid)
      targets.push(targetUid)
      offsets.push(cloneValue(row.controlData?.offsets))
      points.push(cloneValue(row.controlData?.point))
      if (row.text !== undefined && row.text !== null) texts[targetUid] = cloneValue(row.text)
      if (row.styleData !== undefined && row.styleData !== null) {
        styles[targetUid] = cloneValue(row.styleData)
      }
    }
    const data = nodes.get(sourceUid).data
    data.associativeLineTargets = targets
    data.associativeLineTargetControlOffsets = offsets
    data.associativeLinePoint = points
    if (Object.keys(texts).length) data.associativeLineText = texts
    if (Object.keys(styles).length) data.associativeLineStyle = styles
  }

  const summariesByOwner = new Map()
  for (const [recordKey, summary] of entriesOf(state.summaries)) {
    if (!summary) continue
    const ownerUid = String(summary.ownerUid || '')
    if (!nodes.has(ownerUid)) continue
    const rows = summariesByOwner.get(ownerUid) || []
    rows.push({ recordKey: String(recordKey), record: summary })
    summariesByOwner.set(ownerUid, rows)
  }
  for (const [ownerUid, rows] of summariesByOwner) {
    rows.sort((left, right) => (
      Number(left.record.sortOrder || 0) - Number(right.record.sortOrder || 0)
      || compareStableStrings(
        left.record.summaryUid || left.recordKey,
        right.record.summaryUid || right.recordKey,
      )
    ))
    const childUids = (nodes.get(ownerUid).children || []).map(child => String(child.data?.uid || ''))
    nodes.get(ownerUid).data.generalization = rows.map(({ record: row }) => {
      const payload = cloneValue(row.payload || {})
      if (row.summaryUid) payload.uid = String(row.summaryUid)
      const startIndex = childUids.indexOf(String(row.startChildUid || ''))
      const endIndex = childUids.indexOf(String(row.endChildUid || ''))
      if (startIndex >= 0 && endIndex >= 0) payload.range = [startIndex, endIndex]
      return payload
    })
  }

  const orderedGroups = entriesOf(state.groups)
    .sort(([left], [right]) => compareStableStrings(left, right))
  for (const [, group] of orderedGroups) {
    if (!group || group.groupType && group.groupType !== 'outer_frame') continue
    const outerFrame = { ...(cloneValue(group.payload || {})), groupId: String(group.groupUid) }
    for (const memberUid of (group.memberUids || [])) {
      const node = nodes.get(String(memberUid))
      if (node) node.data.outerFrame = cloneValue(outerFrame)
    }
  }

  const imgMap = {}
  const orderedAssets = entriesOf(state.assets)
    .sort(([left], [right]) => compareStableStrings(left, right))
  for (const [key, asset] of orderedAssets) {
    if (asset?.uri !== undefined && asset?.uri !== null) {
      imgMap[String(asset.assetKey ?? key)] = cloneValue(asset.uri)
    }
  }
  if (Object.keys(imgMap).length) root.data.imgMap = imgMap
  return root
}
