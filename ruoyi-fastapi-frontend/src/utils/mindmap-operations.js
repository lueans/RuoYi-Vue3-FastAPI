import { stableSerialize } from './mindmap-draft.js'
import { stripCrossNodeData } from './yjs-cross-node-state.js'

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
  if (current.view !== savedMeta.view) operations.push('file.view.update')
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
  const fieldId = tag.fieldId == null ? undefined : Number(tag.fieldId)
  const optionId = tag.optionId == null ? undefined : Number(tag.optionId)
  if (!Number.isInteger(tagId) || tagId <= 0) return null
  if (fieldId !== undefined && (!Number.isInteger(fieldId) || fieldId <= 0)) return null
  if (optionId !== undefined && (!Number.isInteger(optionId) || optionId <= 0)) return null
  return Object.fromEntries(Object.entries({
    tagId,
    fieldId,
    optionId,
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
    for (const tagKey of [...allKeys].sort()) {
      const before = previousByKey.get(tagKey)
      const after = currentByKey.get(tagKey)
      const key = `${nodeUid}:${tagKey}`
      if (!after) {
        operations.push({
          type: 'node.tag.unbind',
          nodeUid,
          payload: { key, tagKey, tag: before },
        })
      } else if (!before || stableSerialize(before) !== stableSerialize(after)) {
        operations.push({
          type: 'node.tag.bind',
          nodeUid,
          payload: { key, tagKey, tag: after },
        })
      }
    }
    const sameBindingSet = previous.keys.length === current.keys.length
      && previous.keys.every(key => currentByKey.has(key))
    if (
      current.keys.length > 1
      && (action === 'create' || sameBindingSet)
      && stableSerialize(previous.keys) !== stableSerialize(current.keys)
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
      const after = current[key]
      if (after === undefined) {
        operations.push({ type: `${prefix}.delete`, payload: { key, ...(before || {}) } })
      } else if (before === undefined || stableSerialize(before) !== stableSerialize(after)) {
        operations.push({ type: `${prefix}.upsert`, payload: { key, ...after } })
      }
    }
  }
  return operations
}

function immediateChildUids(node) {
  return (node?.children || [])
    .map(child => child?.data?.uid)
    .filter(Boolean)
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
  for (const detail of (detailList || [])) {
    const nodeUid = detailNodeUid(detail)
    if (!nodeUid) continue
    const action = ['create', 'update', 'delete'].includes(detail.action)
      ? detail.action
      : 'update'
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
    if (action !== 'delete') {
      operation.payload = {
        data: currentData,
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
