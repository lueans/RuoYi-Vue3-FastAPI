/**
 * Cross-node simple-mind-map state stored outside Yjs node payloads.
 *
 * Keeping these records in independent maps narrows the collaboration conflict
 * domain: editing a relation no longer replaces the source node, and repeated
 * outer-frame definitions are represented by one group with stable members.
 */

import { cloneJsonValueIterative } from '../libs/simple-mind-map/src/utils/jsonClone.js'

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
  if (typeof structuredClone === 'function') return structuredClone(value)
  const cloned = cloneJsonValueIterative(value)
  if (cloned === null && value !== null && typeof value === 'object') {
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

export function detailListTouchesCrossNodeState(detailList = []) {
  return detailList.some(detail => {
    if (detail?.action === 'delete') return true
    return nodeContainsCrossNodeData(detail?.data)
      || nodeContainsCrossNodeData(detail?.oldData)
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
  return { relations, summaries, groups, assets }
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
  for (const [, relation] of entriesOf(state.relations)) {
    if (!relation || relation.relationType && relation.relationType !== 'associative_line') continue
    const sourceUid = String(relation.sourceUid || '')
    const targetUid = String(relation.targetUid || '')
    if (!nodes.has(sourceUid) || !nodes.has(targetUid)) continue
    const rows = relationsBySource.get(sourceUid) || []
    rows.push(relation)
    relationsBySource.set(sourceUid, rows)
  }
  for (const [sourceUid, rows] of relationsBySource) {
    rows.sort((left, right) => Number(left.sortOrder || 0) - Number(right.sortOrder || 0))
    const targets = []
    const offsets = []
    const points = []
    const texts = {}
    const styles = {}
    for (const row of rows) {
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
  for (const [, summary] of entriesOf(state.summaries)) {
    if (!summary) continue
    const ownerUid = String(summary.ownerUid || '')
    if (!nodes.has(ownerUid)) continue
    const rows = summariesByOwner.get(ownerUid) || []
    rows.push(summary)
    summariesByOwner.set(ownerUid, rows)
  }
  for (const [ownerUid, rows] of summariesByOwner) {
    rows.sort((left, right) => Number(left.sortOrder || 0) - Number(right.sortOrder || 0))
    const childUids = (nodes.get(ownerUid).children || []).map(child => String(child.data?.uid || ''))
    nodes.get(ownerUid).data.generalization = rows.map(row => {
      const payload = cloneValue(row.payload || {})
      if (row.summaryUid) payload.uid = String(row.summaryUid)
      const startIndex = childUids.indexOf(String(row.startChildUid || ''))
      const endIndex = childUids.indexOf(String(row.endChildUid || ''))
      if (startIndex >= 0 && endIndex >= 0) payload.range = [startIndex, endIndex]
      return payload
    })
  }

  for (const [, group] of entriesOf(state.groups)) {
    if (!group || group.groupType && group.groupType !== 'outer_frame') continue
    const outerFrame = { ...(cloneValue(group.payload || {})), groupId: String(group.groupUid) }
    for (const memberUid of (group.memberUids || [])) {
      const node = nodes.get(String(memberUid))
      if (node) node.data.outerFrame = cloneValue(outerFrame)
    }
  }

  const imgMap = {}
  for (const [key, asset] of entriesOf(state.assets)) {
    if (asset?.uri !== undefined && asset?.uri !== null) {
      imgMap[String(asset.assetKey ?? key)] = cloneValue(asset.uri)
    }
  }
  if (Object.keys(imgMap).length) root.data.imgMap = imgMap
  return root
}
