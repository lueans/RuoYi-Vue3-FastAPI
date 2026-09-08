import { stableSerialize } from './mindmap-draft.js'
import { cloneRequestPayload } from './requestPayload.js'
import {
  applyCrossNodeState,
  extractCrossNodeState,
  mergeGroupMemberDelta,
  mergeJsonValueDelta,
  stripCrossNodeData,
} from './yjs-cross-node-state.js'
import {
  transformTreeDataToObject,
} from '../libs/simple-mind-map/src/utils/treeData.js'

export const MAX_MINDMAP_CONTENT_OPERATIONS = 2000

const MINDMAP_FILE_OPERATION_FIELDS = Object.freeze({
  'file.layout.update': 'layout',
  'file.theme.update': 'theme',
  'file.document_data.update': 'documentData',
})

function mindmapFileOperationField(operation) {
  const type = typeof operation === 'string' ? operation : operation?.type
  return MINDMAP_FILE_OPERATION_FIELDS[type] || null
}

/**
 * Freeze the local values represented by file-level operations. Yjs metadata
 * is intentionally a live preview and can resolve a concurrent remote value
 * before the matching HTTP mutation is created; the HTTP payload must retain
 * the value that caused the local operation instead of reading that preview.
 */
export function captureMindmapFileMetaIntents(
  currentIntents = {},
  document = {},
  operations = [],
) {
  const next = { ...currentIntents }
  for (const operation of (Array.isArray(operations) ? operations : [])) {
    const field = mindmapFileOperationField(operation)
    if (!field || !Object.prototype.hasOwnProperty.call(document, field)) continue
    next[field] = cloneRequestPayload(document[field])
  }
  return next
}

/** Apply frozen local file values to a live document snapshot. */
export function applyMindmapFileMetaIntents(document = {}, intents = {}) {
  let result = document
  for (const field of Object.values(MINDMAP_FILE_OPERATION_FIELDS)) {
    if (!Object.prototype.hasOwnProperty.call(intents, field)) continue
    if (result === document) result = { ...document }
    result[field] = cloneRequestPayload(intents[field])
  }
  return result
}

/** Remove intent values for file operations that have returned to baseline. */
export function omitMindmapFileMetaIntents(intents = {}, operations = []) {
  const next = { ...intents }
  for (const operation of (Array.isArray(operations) ? operations : [])) {
    const field = mindmapFileOperationField(operation)
    if (field) delete next[field]
  }
  return next
}

/** Return file domains where a remote Yjs preview differs from local intent. */
export function findConflictingMindmapFileMetaIntents(intents = {}, remoteMeta = {}) {
  const conflicts = []
  for (const [type, field] of Object.entries(MINDMAP_FILE_OPERATION_FIELDS)) {
    if (
      !Object.prototype.hasOwnProperty.call(intents, field)
      || !Object.prototype.hasOwnProperty.call(remoteMeta, field)
      || remoteMeta[field] === undefined
    ) continue
    if (stableSerialize(intents[field]) !== stableSerialize(remoteMeta[field])) {
      conflicts.push(type)
    }
  }
  return conflicts
}

function readNodeRevision(nodeRevisions, nodeUid) {
  if (!nodeUid) return undefined
  return nodeRevisions instanceof Map
    ? nodeRevisions.get(nodeUid)
    : nodeRevisions?.[nodeUid]
}

/**
 * Apply the node-revision delta attached to a committed collaboration batch.
 * The delta is delivered only after the matching Yjs update reaches the canvas,
 * so callers can advance the content and per-node fences atomically.
 */
export function applyMindmapNodeRevisionChanges(nodeRevisions, changedNodes = []) {
  if (!(nodeRevisions instanceof Map)) return nodeRevisions
  for (const node of (Array.isArray(changedNodes) ? changedNodes : [])) {
    const nodeUid = typeof node?.nodeUid === 'string' ? node.nodeUid.trim() : ''
    if (!nodeUid) continue
    if (node.action === 'delete') {
      nodeRevisions.delete(nodeUid)
      continue
    }
    const revision = Number(node.nodeRevision)
    if (Number.isInteger(revision) && revision > 0) {
      nodeRevisions.set(nodeUid, revision)
    }
  }
  return nodeRevisions
}

/**
 * Rebase operations captured while an earlier save was in flight. Only an
 * existing node fence is replaced: pure edge/order operations deliberately do
 * not acquire a targetRevision, and provisional creates must stay unfenced.
 */
export function rebaseMindmapOperationTargetRevisions(operations, nodeRevisions) {
  return (Array.isArray(operations) ? operations : []).map(operation => {
    if (
      !['node.update', 'node.delete'].includes(operation?.type)
      || !Number.isInteger(operation.targetRevision)
    ) return operation
    const revision = Number(readNodeRevision(nodeRevisions, operation.nodeUid))
    if (!Number.isInteger(revision) || revision <= 0 || revision === operation.targetRevision) {
      return operation
    }
    return { ...operation, targetRevision: revision }
  })
}

function operationNodeUid(operation) {
  const value = operation?.nodeUid ?? operation?.node_uid
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function operationPayloadValue(payload, camelKey, snakeKey) {
  return payload?.[camelKey] ?? payload?.[snakeKey]
}

function separatedDomainsAreCompatible(previousPayload, currentPayload) {
  return [
    ['crossNodeDataSeparated', 'cross_node_data_separated'],
    ['tagBindingsSeparated', 'tag_bindings_separated'],
  ].every(([camelKey, snakeKey]) => (
    (operationPayloadValue(previousPayload, camelKey, snakeKey) === true)
    === (operationPayloadValue(currentPayload, camelKey, snakeKey) === true)
  ))
}

function compactNodeUpdates(previous, current) {
  const previousPayload = previous?.payload
  const currentPayload = current?.payload
  if (!previousPayload || !currentPayload) return null
  if (!separatedDomainsAreCompatible(previousPayload, currentPayload)) return null

  const previousData = previousPayload.dataChanged === true
    ? operationPayloadValue(previousPayload, 'previousData', 'previous_data')
    : previousPayload.data
  const currentData = currentPayload.data
  const oldChildUids = operationPayloadValue(
    previousPayload,
    'oldChildUids',
    'old_child_uids',
  )
  const childUids = operationPayloadValue(currentPayload, 'childUids', 'child_uids')
  if (
    !previousData
    || typeof previousData !== 'object'
    || Array.isArray(previousData)
    || !currentData
    || typeof currentData !== 'object'
    || Array.isArray(currentData)
    || !Array.isArray(oldChildUids)
    || !Array.isArray(childUids)
  ) return null

  const dataChanged = stableSerialize(previousData) !== stableSerialize(currentData)
  const childrenChanged = stableSerialize(oldChildUids) !== stableSerialize(childUids)
  if (!dataChanged && !childrenChanged) return false

  return {
    ...previous,
    payload: {
      ...currentPayload,
      data: currentData,
      ...(dataChanged ? { previousData } : {}),
      ...(!dataChanged ? { previousData: undefined } : {}),
      childUids,
      oldChildUids,
      dataChanged,
      childrenChanged,
      crossNodeDataSeparated: operationPayloadValue(
        currentPayload,
        'crossNodeDataSeparated',
        'cross_node_data_separated',
      ) === true,
      tagBindingsSeparated: operationPayloadValue(
        currentPayload,
        'tagBindingsSeparated',
        'tag_bindings_separated',
      ) === true,
    },
    ...(previous.targetRevision === undefined && current.targetRevision !== undefined
      ? { targetRevision: current.targetRevision }
      : {}),
  }
}

function compactCreateWithUpdate(created, updated) {
  const createdPayload = created?.payload
  const updatedPayload = updated?.payload
  const data = updatedPayload?.data
  const childUids = operationPayloadValue(updatedPayload, 'childUids', 'child_uids')
  if (
    !createdPayload
    || !updatedPayload
    || !separatedDomainsAreCompatible(createdPayload, updatedPayload)
    || !data
    || typeof data !== 'object'
    || Array.isArray(data)
    || !Array.isArray(childUids)
  ) return null
  return {
    ...created,
    payload: {
      ...createdPayload,
      ...updatedPayload,
      data,
      previousData: undefined,
      childUids,
      oldChildUids: [],
      dataChanged: true,
      childrenChanged: childUids.length > 0,
    },
  }
}

function normalizedNodeReference(value) {
  if (value === undefined || value === null) return null
  const normalized = String(value).trim()
  return normalized || null
}

function crossNodeOperationReferencesAnyNode(operation, nodeUids) {
  const payload = operation?.payload
  if (!payload || typeof payload !== 'object') return false
  const prefix = operation.type?.split('.')[0]
  let references = []
  if (prefix === 'relation') {
    references = [
      operationPayloadValue(payload, 'sourceUid', 'source_uid'),
      operationPayloadValue(payload, 'targetUid', 'target_uid'),
    ]
  } else if (prefix === 'summary') {
    references = [
      operationPayloadValue(payload, 'ownerUid', 'owner_uid'),
      operationPayloadValue(payload, 'startChildUid', 'start_child_uid'),
      operationPayloadValue(payload, 'endChildUid', 'end_child_uid'),
    ]
  } else if (prefix === 'group') {
    const memberUids = operationPayloadValue(payload, 'memberUids', 'member_uids')
    references = Array.isArray(memberUids) ? memberUids : []
  }
  return references.some(value => {
    const nodeUid = normalizedNodeReference(value)
    return nodeUid !== null && nodeUids.has(nodeUid)
  })
}

function removeCancelledNodeReferences(operation, nodeUids) {
  const nodeUid = operationNodeUid(operation)
  if (nodeUid && nodeUids.has(nodeUid)) return null
  if (
    ['node.create', 'node.update'].includes(operation?.type)
    && operation.payload
  ) {
    const oldChildUids = operationPayloadValue(
      operation.payload,
      'oldChildUids',
      'old_child_uids',
    )
    const childUids = operationPayloadValue(operation.payload, 'childUids', 'child_uids')
    if (Array.isArray(oldChildUids) && Array.isArray(childUids)) {
      const filteredOld = oldChildUids.filter(uid => {
        const normalized = normalizedNodeReference(uid)
        return normalized === null || !nodeUids.has(normalized)
      })
      const filteredNext = childUids.filter(uid => {
        const normalized = normalizedNodeReference(uid)
        return normalized === null || !nodeUids.has(normalized)
      })
      const childrenChanged = stableSerialize(filteredOld) !== stableSerialize(filteredNext)
      if (
        operation.type === 'node.update'
        && !childrenChanged
        && operation.payload.dataChanged !== true
      ) return null
      return {
        ...operation,
        payload: {
          ...operation.payload,
          oldChildUids: filteredOld,
          childUids: filteredNext,
          childrenChanged,
        },
      }
    }
  }
  if (operation?.type?.startsWith('node.tag.')) return operation
  if (crossNodeOperationReferencesAnyNode(operation, nodeUids)) return null
  return operation
}

function rebuildLatestNodeOperationIndexes(result, latestNodeOperationIndex) {
  latestNodeOperationIndex.clear()
  result.forEach((item, index) => {
    const uid = operationNodeUid(item)
    if (uid && ['node.create', 'node.update', 'node.delete'].includes(item?.type)) {
      latestNodeOperationIndex.set(uid, index)
    }
  })
}

function combinePendingNodeOperations(previous, current) {
  if (previous.type === 'node.create' && current.type === 'node.delete') return false
  if (previous.type === 'node.create' && current.type === 'node.update') {
    return compactCreateWithUpdate(previous, current)
  }
  if (previous.type === 'node.update' && current.type === 'node.update') {
    return compactNodeUpdates(previous, current)
  }
  if (previous.type === 'node.update' && current.type === 'node.delete') {
    return {
      ...current,
      ...(current.targetRevision === undefined && previous.targetRevision !== undefined
        ? { targetRevision: previous.targetRevision }
        : {}),
    }
  }
  // delete -> create 是撤销删除而不是新建后撤销；必须保留顺序让服务端
  // 重建原稳定 UID。其他无法证明等价的旧协议组合也保持原样。
  return null
}

/**
 * Collapse transient node operations within one unsaved mutation without
 * reordering different nodes. This removes edits that ended at their original
 * state, reducing false conflicts while retaining semantically meaningful
 * delete/restore sequences.
 */
export function compactMindmapContentOperations(operations) {
  const result = []
  const latestNodeOperationIndex = new Map()
  const provisionalNodeUids = new Set()
  for (const operation of (Array.isArray(operations) ? operations : [])) {
    const nodeUid = operationNodeUid(operation)
    let preserveProvisionalRootDeleteSequence = false
    if (operation?.type === 'node.delete') {
      const deletedNodeUids = operationPayloadValue(
        operation.payload,
        'deletedNodeUids',
        'deleted_node_uids',
      )
      const deletedScope = new Set(
        (Array.isArray(deletedNodeUids) ? deletedNodeUids : [nodeUid])
          .map(uid => String(uid || '').trim())
          .filter(Boolean),
      )
      const cancelledProvisionalUids = new Set(
        [...deletedScope].filter(uid => provisionalNodeUids.has(uid)),
      )
      const hasPersistedNodeInScope = [...deletedScope].some(
        uid => !provisionalNodeUids.has(uid),
      )
      // A provisional parent can temporarily adopt an existing node. In that
      // mixed case the original create -> delete ordering carries information
      // that cannot be represented by merely cancelling the parent create.
      preserveProvisionalRootDeleteSequence = Boolean(
        nodeUid
        && provisionalNodeUids.has(nodeUid)
        && hasPersistedNodeInScope
      )
      if (cancelledProvisionalUids.size > 0 && !preserveProvisionalRootDeleteSequence) {
        for (let index = 0; index < result.length; index += 1) {
          result[index] = removeCancelledNodeReferences(
            result[index],
            cancelledProvisionalUids,
          )
        }
        for (const uid of cancelledProvisionalUids) provisionalNodeUids.delete(uid)
        rebuildLatestNodeOperationIndexes(result, latestNodeOperationIndex)
        if (!hasPersistedNodeInScope) continue
      }
    }
    if (!nodeUid || !['node.create', 'node.update', 'node.delete'].includes(operation?.type)) {
      result.push(operation)
      continue
    }
    const previousIndex = latestNodeOperationIndex.get(nodeUid)
    if (preserveProvisionalRootDeleteSequence) {
      latestNodeOperationIndex.set(nodeUid, result.push(operation) - 1)
      provisionalNodeUids.delete(nodeUid)
      continue
    }
    if (previousIndex === undefined || !result[previousIndex]) {
      latestNodeOperationIndex.set(nodeUid, result.push(operation) - 1)
      if (operation.type === 'node.create') provisionalNodeUids.add(nodeUid)
      continue
    }
    const combined = combinePendingNodeOperations(result[previousIndex], operation)
    if (combined === null) {
      latestNodeOperationIndex.set(nodeUid, result.push(operation) - 1)
    } else if (combined === false) {
      result[previousIndex] = null
      latestNodeOperationIndex.delete(nodeUid)
      provisionalNodeUids.delete(nodeUid)
    } else {
      result[previousIndex] = combined
    }
  }
  return result.filter(Boolean).map(operation => {
    if (operation?.payload?.previousData !== undefined) return operation
    if (!operation?.payload || !Object.hasOwn(operation.payload, 'previousData')) return operation
    const payload = { ...operation.payload }
    delete payload.previousData
    return { ...operation, payload }
  })
}

export function snapshotMindmapDocumentMeta(document = {}) {
  return {
    layout: document.layout || 'logicalStructure',
    theme: stableSerialize(document.theme || {}),
    view: stableSerialize(document.view ?? document.viewData ?? null),
    documentData: stableSerialize(document.documentData ?? document.document_data ?? {}),
  }
}

export function detectMindmapFileOperations(document, savedMeta) {
  if (!savedMeta) return []
  const current = snapshotMindmapDocumentMeta(document)
  const operations = []
  if (current.layout !== savedMeta.layout) operations.push('file.layout.update')
  if (current.theme !== savedMeta.theme) operations.push('file.theme.update')
  if (current.documentData !== savedMeta.documentData) operations.push('file.document_data.update')
  return operations
}

export function appendUniqueMindmapOperation(operations, type) {
  if (operations.some(operation => operation.type === type)) return false
  operations.push({ type })
  return true
}

const CROSS_NODE_OPERATION_DOMAINS = Object.freeze({
  relations: { prefix: 'relation' },
  summaries: { prefix: 'summary' },
  groups: { prefix: 'group' },
  assets: { prefix: 'asset' },
})

function normalizeManagedTagBinding(tag) {
  if (!tag || typeof tag !== 'object' || tag.tagId === undefined || tag.tagId === null) return null
  const tagId = Number(tag.tagId)
  if (!Number.isInteger(tagId) || tagId <= 0) return null
  return Object.fromEntries(Object.entries({
    tagId,
    placement: tag.placement,
    align: tag.align,
  }).filter(([, value]) => value !== undefined))
}

function managedTagBindings(data = {}) {
  const tags = Array.isArray(data.tag) ? data.tag : []
  const normalized = tags.map(normalizeManagedTagBinding)
  if (normalized.some(tag => tag === null)) return null
  const keys = normalized.map(tag => String(tag.tagId))
  if (new Set(keys).size !== keys.length) return null
  return { tags: normalized, keys }
}

function stripSeparatedTagBindings(data = {}, canSeparate = true) {
  if (!canSeparate) return { ...data }
  const output = { ...data }
  delete output.tag
  return output
}

/** Build managed node-tag binding operations without copying tag definitions into node data. */
export function buildNodeTagContentOperations(detailList) {
  const operations = []
  for (const detail of (detailList || [])) {
    const action = ['create', 'update', 'delete'].includes(detail.action) ? detail.action : 'update'
    if (action === 'delete') continue
    const nodeUid = detailNodeUid(detail)
    if (!nodeUid) continue
    const previous = managedTagBindings(action === 'create' ? {} : (detail.oldData?.data || {}))
    const current = managedTagBindings(detail.data?.data || {})
    if (!previous || !current) continue

    const previousByKey = new Map(previous.tags.map(tag => [String(tag.tagId), tag]))
    const currentByKey = new Map(current.tags.map(tag => [String(tag.tagId), tag]))
    const allKeys = new Set([...previous.keys, ...current.keys])
    const replayedKeys = [...previous.keys]
    for (const tagKey of [...allKeys].sort()) {
      const before = previousByKey.get(tagKey)
      const after = currentByKey.get(tagKey)
      const key = `${nodeUid}:${tagKey}`
      if (!after) {
        const index = replayedKeys.indexOf(tagKey)
        if (index >= 0) replayedKeys.splice(index, 1)
        operations.push({
          type: 'node.tag.unbind',
          nodeUid,
          payload: { key, tagKey, tag: before },
        })
      } else if (!before || stableSerialize(before) !== stableSerialize(after)) {
        if (!replayedKeys.includes(tagKey)) replayedKeys.push(tagKey)
        operations.push({
          type: 'node.tag.bind',
          nodeUid,
          payload: { key, tagKey, tag: after },
        })
      }
    }
    if (
      current.keys.length > 0
      && stableSerialize(replayedKeys) !== stableSerialize(current.keys)
    ) {
      operations.push({
        type: 'node.tag.reorder',
        nodeUid,
        payload: { key: nodeUid, tagKeys: current.keys },
      })
    }
  }
  return operations
}

/** Build entity-level operations between two already extracted cross-node states. */
export function buildCrossNodeContentOperations(previousState = {}, currentState = {}) {
  const operations = []
  for (const [domain, { prefix }] of Object.entries(CROSS_NODE_OPERATION_DOMAINS)) {
    const previous = previousState[domain] || {}
    const current = currentState[domain] || {}
    const keys = new Set([...Object.keys(previous), ...Object.keys(current)])
    for (const key of [...keys].sort()) {
      const before = previous[key]
      // An outer-frame group disappears from the component tree when its last
      // rendered member is removed. That is a member-set delta, not a hard
      // entity deletion: a collaborator may have added another member in the
      // meantime. Keep the empty semantic shell in the operation so both the
      // HTTP merger and Yjs CRDT can retain that concurrent addition.
      const after = current[key] ?? (
        domain === 'groups' && before
          ? { ...before, memberUids: [] }
          : undefined
      )
      if (after === undefined) {
        operations.push({
          type: `${prefix}.delete`,
          payload: {
            key,
            ...(before || {}),
            before: before ?? null,
            after: null,
          },
        })
      } else if (before === undefined || stableSerialize(before) !== stableSerialize(after)) {
        operations.push({
          type: `${prefix}.upsert`,
          payload: {
            key,
            ...after,
            before: before ?? null,
            after,
          },
        })
      }
    }
  }
  return operations
}

/** Preserve the first before-state while one autosave window coalesces edits. */
export function mergePendingCrossNodeOperation(previous, current) {
  const previousPrefix = previous?.type?.split('.')[0]
  const currentPrefix = current?.type?.split('.')[0]
  if (
    !Object.values(CROSS_NODE_OPERATION_DOMAINS).some(({ prefix }) => (
      prefix === previousPrefix
    ))
    || previousPrefix !== currentPrefix
    || previous?.payload?.key !== current?.payload?.key
    || !Object.prototype.hasOwnProperty.call(previous?.payload || {}, 'before')
    || !Object.prototype.hasOwnProperty.call(current?.payload || {}, 'after')
  ) return current
  // A different before-state proves that a remote render occurred between the
  // two local actions. Likewise, changing upsert↔delete crosses a record
  // generation boundary. A single before/after snapshot cannot encode those
  // temporal intents without either claiming remote-only fields or erasing an
  // explicit local "back to baseline" action, so preserve both operations.
  if (
    previous.type !== current.type
    || stableSerialize(previous.payload.after) !== stableSerialize(current.payload.before)
  ) return [previous, current]
  const before = previous.payload.before
  const after = current.payload.after
  if (stableSerialize(before) === stableSerialize(after)) return null
  return {
    ...current,
    payload: {
      ...current.payload,
      before,
    },
  }
}

function setOwnCrossNodeRecord(records, key, value) {
  Object.defineProperty(records, key, {
    configurable: true,
    enumerable: true,
    writable: true,
    value: cloneRequestPayload(value),
  })
}

function mergeCrossNodeRecordIntent(domain, existing, before, after) {
  if (domain === 'groups') {
    const memberUids = mergeGroupMemberDelta(
      existing?.memberUids,
      before?.memberUids,
      after?.memberUids,
    )
    if (after === null) {
      const retained = existing || before
      return retained && typeof retained === 'object'
        ? { ...cloneRequestPayload(retained), memberUids }
        : null
    }
    const merged = existing === undefined || existing === null
      ? cloneRequestPayload(after)
      : mergeJsonValueDelta(existing, before || {}, after)
    merged.memberUids = memberUids
    return merged
  }
  if (after === null) return null
  return existing === undefined || existing === null
    ? cloneRequestPayload(after)
    : mergeJsonValueDelta(existing, before || {}, after)
}

/**
 * Reapply the exact local cross-node deltas to a live Yjs canvas snapshot.
 *
 * A remote preview can win the same CRDT field after the editor recorded the
 * local before/after operation but before HTTP freezes its document. Applying
 * only that recorded delta preserves the user's submitted value (and therefore
 * the rejected-conflict draft) without replacing unrelated remote fields.
 */
export function applyCrossNodeOperationIntents(document = {}, operations = []) {
  const applicableOperations = (Array.isArray(operations) ? operations : [])
    .map(operation => {
      const prefix = operation?.type?.split('.')[0]
      const domain = Object.entries(CROSS_NODE_OPERATION_DOMAINS)
        .find(([, value]) => value.prefix === prefix)?.[0]
      const payload = operation?.payload
      if (
        !domain
        || !payload
        || typeof payload !== 'object'
        || !Object.prototype.hasOwnProperty.call(payload, 'before')
        || !Object.prototype.hasOwnProperty.call(payload, 'after')
        || payload.key === undefined
        || payload.key === null
      ) return null
      return { domain, key: String(payload.key), payload }
    })
    .filter(Boolean)
  if (applicableOperations.length === 0 || !document?.root) return document

  const result = cloneRequestPayload(document)
  const state = extractCrossNodeState(result.root)
  for (const { domain, key, payload } of applicableOperations) {
    const records = state[domain]
    const existing = Object.prototype.hasOwnProperty.call(records, key)
      ? records[key]
      : undefined
    const before = payload.before
    const after = payload.after

    const merged = mergeCrossNodeRecordIntent(domain, existing, before, after)
    if (merged === null) {
      delete records[key]
      continue
    }
    // If a remote preview already removed the entity, the helper starts from
    // the full local after-state so the conflict draft retains identity fields.
    setOwnCrossNodeRecord(records, key, merged)
  }
  applyCrossNodeState(result.root, state)
  return result
}

/**
 * Reapply local node-data deltas to a live canvas snapshot before freezing an
 * HTTP mutation. Realtime Yjs rendering can resolve a concurrent value between
 * data_change_detail and autosave; the operation's before/after pair is the
 * durable record of what this browser actually changed.
 *
 * Only the fields changed by the local operation are overlaid. Unrelated
 * fields won by a remote preview stay intact, and separated tag/cross-node
 * domains continue to be handled by their own operation replayers.
 */
export function applyMindmapNodeDataOperationIntents(document = {}, operations = []) {
  const applicableOperations = (Array.isArray(operations) ? operations : [])
    .map(operation => {
      if (operation?.type !== 'node.update' || operation?.payload?.dataChanged !== true) {
        return null
      }
      const nodeUid = operationNodeUid(operation)
      const data = operation.payload.data
      const previousData = operationPayloadValue(
        operation.payload,
        'previousData',
        'previous_data',
      )
      if (
        !nodeUid
        || !data
        || typeof data !== 'object'
        || Array.isArray(data)
        || !previousData
        || typeof previousData !== 'object'
        || Array.isArray(previousData)
        || String(data.uid || '') !== nodeUid
        || String(previousData.uid || '') !== nodeUid
      ) return null
      return { nodeUid, data, previousData }
    })
    .filter(Boolean)
  if (applicableOperations.length === 0 || !document?.root) return document

  const result = cloneRequestPayload(document)
  const nodesByUid = new Map()
  const pending = [result.root]
  const visited = new WeakSet()
  while (pending.length > 0) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    const nodeUidValue = node?.data?.uid ?? node?.uid
    const nodeUid = typeof nodeUidValue === 'string' && nodeUidValue.trim()
      ? nodeUidValue.trim()
      : null
    if (nodeUid && !nodesByUid.has(nodeUid)) nodesByUid.set(nodeUid, node)
    const children = Array.isArray(node.children) ? node.children : []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push(children[index])
    }
  }

  for (const { nodeUid, data, previousData } of applicableOperations) {
    const node = nodesByUid.get(nodeUid)
    if (!node || !node.data || typeof node.data !== 'object' || Array.isArray(node.data)) {
      continue
    }
    const mergedData = mergeJsonValueDelta(node.data, previousData, data)
    // Stable UID is protocol identity, never a user-editable field. Keeping the
    // indexed value also prevents malformed local plugin data from relocating
    // the intent to another node in the frozen conflict draft.
    if (mergedData && typeof mergedData === 'object' && !Array.isArray(mergedData)) {
      mergedData.uid = nodeUid
      node.data = mergedData
    }
  }
  return result
}

/** Freeze every operation domain whose live Yjs preview may have moved ahead. */
export function applyMindmapOperationIntents(document = {}, operations = []) {
  return applyCrossNodeOperationIntents(
    applyMindmapNodeDataOperationIntents(document, operations),
    operations,
  )
}

function immediateChildUids(node) {
  return (node?.children || [])
    .map(child => child?.data?.uid)
    .filter(Boolean)
}

function subtreeNodeUids(node) {
  const result = []
  const pending = [node]
  const visited = new WeakSet()
  while (pending.length) {
    const current = pending.pop()
    if (!current || typeof current !== 'object' || visited.has(current)) continue
    visited.add(current)
    const uid = current.data?.uid || current.uid
    if (uid) result.push(String(uid))
    const children = Array.isArray(current.children) ? current.children : []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push(children[index])
    }
  }
  return result
}

function detailNodeUid(detail) {
  return detail?.data?.data?.uid
    || detail?.oldData?.data?.uid
    || detail?.oldData?.uid
}

/**
 * 把 simple-mind-map 的树差异转换为可合并的领域操作。
 * update 显式区分节点属性和子列表变化，避免同父节点并发新增被误判为整节点冲突。
 */
export function buildMindmapContentOperations(detailList, nodeRevisions = new Map()) {
  const operations = []
  const details = detailList || []
  const deleteSubtreeUids = new Map()
  const deletedDescendantUids = new Set()
  for (const detail of details) {
    if (detail?.action !== 'delete') continue
    const nodeUid = detailNodeUid(detail)
    const deletedUids = subtreeNodeUids(detail.oldData || detail.data)
    deleteSubtreeUids.set(detail, deletedUids)
    for (const uid of deletedUids) {
      if (uid !== String(nodeUid || '')) deletedDescendantUids.add(uid)
    }
  }
  for (const detail of details) {
    const nodeUid = detailNodeUid(detail)
    if (!nodeUid) continue
    const action = ['create', 'update', 'delete'].includes(detail.action)
      ? detail.action
      : 'update'
    // Command 会为子树内每个消失节点各发一条 delete 明细。祖先操作已经
    // 原子覆盖整个子树，省略后代重复删除可避免大分支产生平方级请求载荷。
    if (action === 'delete' && deletedDescendantUids.has(String(nodeUid))) continue
    const rawCurrentData = stripCrossNodeData(detail.data?.data || {})
    const rawPreviousData = stripCrossNodeData(detail.oldData?.data || {})
    const canSeparateTags = managedTagBindings(rawCurrentData) !== null
      && managedTagBindings(action === 'create' ? {} : rawPreviousData) !== null
    const currentData = stripSeparatedTagBindings(rawCurrentData, canSeparateTags)
    const previousData = stripSeparatedTagBindings(rawPreviousData, canSeparateTags)
    const childUids = immediateChildUids(detail.data)
    const oldChildUids = immediateChildUids(detail.oldData)
    const dataChanged = action === 'update'
      ? stableSerialize(currentData) !== stableSerialize(previousData)
      : action === 'create'
    const childrenChanged = action === 'update'
      ? stableSerialize(childUids) !== stableSerialize(oldChildUids)
      : action === 'create' && childUids.length > 0
    if (action === 'update' && !dataChanged && !childrenChanged) continue

    const operation = {
      type: `node.${action}`,
      nodeUid,
    }
    if (action === 'delete') {
      // 删除父节点会同时删除整个后代子树。把基线子树身份写入操作日志，
      // 服务端才能识别“另一浏览器编辑后代 vs 当前浏览器删除祖先”的冲突，
      // 避免保存顺序不同导致后代修改被静默吞掉。
      operation.payload = {
        deletedNodeUids: deleteSubtreeUids.get(detail) || [],
      }
    } else {
      operation.payload = {
        data: currentData,
        // 服务端以新旧快照计算本次真正修改的字段。这样两个浏览器分别修改
        // 同一节点的文字和样式时，只合并各自字段，不再用整节点快照互相覆盖。
        ...(action === 'update' && dataChanged ? { previousData } : {}),
        childUids,
        oldChildUids,
        dataChanged,
        childrenChanged,
        crossNodeDataSeparated: true,
        tagBindingsSeparated: canSeparateTags,
      }
    }
    // 纯子列表增量由 edge/order 冲突域保护，不使用整节点 revision 阻断可合并的并发插入。
    if ((action === 'delete' || dataChanged) && nodeRevisions.has(nodeUid)) {
      operation.targetRevision = nodeRevisions.get(nodeUid)
    }
    operations.push(operation)
  }
  return operations
}

/**
 * Build the same fine-grained detail list emitted by simple-mind-map history,
 * but from two persisted documents. Draft recovery uses this instead of the
 * legacy whole-document replacement operation so concurrent edits can still be
 * checked and merged at node/edge/entity granularity.
 */
export function buildMindmapTreeDetailList(previousRoot, currentRoot) {
  const previous = transformTreeDataToObject(previousRoot)
  const current = transformTreeDataToObject(currentRoot)
  const details = []

  // 操作构建只读取节点数据和直接子节点 UID。不要为每个变更节点展开完整
  // 后代子树，否则深层草稿的全量恢复会产生平方级复制和内存占用。
  const materializeDetailNode = (entries, uid) => {
    const entry = entries[uid]
    if (!entry) return null
    return {
      ...entry,
      data: entry.data && typeof entry.data === 'object'
        ? { ...entry.data }
        : entry.data,
      children: (Array.isArray(entry.children) ? entry.children : []).map(childUid => ({
        data: { uid: childUid },
        children: [],
      })),
    }
  }

  for (const uid of Object.keys(current)) {
    if (!previous[uid]) {
      details.push({
        action: 'create',
        data: materializeDetailNode(current, uid),
      })
      continue
    }
    if (stableSerialize(previous[uid]) !== stableSerialize(current[uid])) {
      details.push({
        action: 'update',
        oldData: materializeDetailNode(previous, uid),
        data: materializeDetailNode(current, uid),
      })
    }
  }
  for (const uid of Object.keys(previous)) {
    if (current[uid]) continue
    details.push({
      action: 'delete',
      oldData: materializeDetailNode(previous, uid),
      data: materializeDetailNode(previous, uid),
    })
  }
  return details
}

export function buildMindmapDocumentOperations(
  previousDocument,
  currentDocument,
  nodeRevisions = new Map(),
) {
  const previousRoot = previousDocument?.root || previousDocument
  const currentRoot = currentDocument?.root || currentDocument
  if (!previousRoot?.data?.uid || !currentRoot?.data?.uid) return []
  const details = buildMindmapTreeDetailList(previousRoot, currentRoot)
  const operations = [
    ...buildMindmapContentOperations(details, nodeRevisions),
    ...buildNodeTagContentOperations(details),
    ...buildCrossNodeContentOperations(
      extractCrossNodeState(previousRoot),
      extractCrossNodeState(currentRoot),
    ),
    ...detectMindmapFileOperations(
      currentDocument,
      snapshotMindmapDocumentMeta(previousDocument),
    ).map(type => ({ type })),
  ]
  // 服务端单批最多接受 2000 项。大规模离线草稿无法安全拆成多个独立
  // revision（父边、标签和跨节点实体需要原子提交），因此退回受乐观锁保护的
  // 正文快照操作。它覆盖树和正文配置但明确排除 view，避免绕过独立的视图
  // LWW 通道；若云端已推进 revision，服务端仍会拒绝覆盖并进入冲突流程。
  return operations.length > MAX_MINDMAP_CONTENT_OPERATIONS
    ? [{ type: 'document.content.update' }]
    : operations
}
