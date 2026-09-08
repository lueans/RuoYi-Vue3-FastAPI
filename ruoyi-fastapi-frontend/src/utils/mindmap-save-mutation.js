import { cloneRequestPayload } from './requestPayload.js'

/**
 * Freeze the exact document carried by a rejected HTTP mutation before any
 * asynchronous conflict recovery work can let a remote Yjs preview replace
 * the live canvas. A previously captured snapshot wins on retries because the
 * active mutation may already have been released after a reset attempt.
 */
export function captureRejectedMindmapMutationSnapshot({
  mutation,
  fallbackDocument,
  previousSnapshot = null,
  fallbackBaseRevision = null,
  fallbackContentChangeVersion = null,
} = {}) {
  const sourceSnapshot = previousSnapshot?.document
    ? previousSnapshot
    : null
  const sourceDocument = sourceSnapshot?.document
    || mutation?.document
    || fallbackDocument
  if (!sourceDocument) return null

  const baseRevision = Number(
    sourceSnapshot?.baseRevision
      ?? mutation?.baseRevision
      ?? fallbackBaseRevision,
  )
  const contentChangeVersion = Number(
    sourceSnapshot?.contentChangeVersion
      ?? mutation?.contentChangeVersion
      ?? fallbackContentChangeVersion,
  )
  const yjsUpdateCount = Number(
    sourceSnapshot?.yjsUpdateCount
      ?? mutation?.yjsUpdateCount
      ?? 0,
  )
  return Object.freeze({
    clientMutationId: String(
      sourceSnapshot?.clientMutationId
        || mutation?.clientMutationId
        || '',
    ),
    baseRevision: Number.isInteger(baseRevision) && baseRevision > 0
      ? baseRevision
      : null,
    contentChangeVersion: Number.isSafeInteger(contentChangeVersion)
      && contentChangeVersion >= 0
      ? contentChangeVersion
      : null,
    yjsUpdateCount: Number.isInteger(yjsUpdateCount) && yjsUpdateCount >= 0
      ? yjsUpdateCount
      : 0,
    document: cloneRequestPayload(sourceDocument),
  })
}

function isAutoRebaseSafeOperationSet(operations) {
  if (!Array.isArray(operations) || operations.length === 0) return false
  const createdNodeUids = new Set(
    operations
      .filter(operation => operation?.type === 'node.create')
      .map(operation => String(operation.nodeUid || ''))
      .filter(Boolean),
  )
  return operations.every((operation) => {
    const operationType = operation?.type
    // 画布视口只记录平移/缩放等展示状态，协作者同时调整时采用后写覆盖即可；
    // 它不能阻止同一批次中的节点操作在服务端推进到最新基线。
    if (operationType === 'file.view.update') return true
    const nodeUid = String(operation?.nodeUid || '')
    if (!nodeUid || !operationType?.startsWith('node.')) return false
    // 标签绑定虽然也以 node. 开头，但没有节点 revision 保护；变更日志缺失时
    // 无法证明同一绑定未被其他客户端修改，因此不能静默重放。
    if (operationType.startsWith('node.tag.')) return false
    if (operationType === 'node.create') return true
    if (operationType === 'node.delete') {
      return createdNodeUids.has(nodeUid) || Number.isInteger(operation.targetRevision)
    }
    if (operationType !== 'node.update') return false
    if (createdNodeUids.has(nodeUid)) return true
    if (operation.payload?.dataChanged !== true) return true
    return Number.isInteger(operation.targetRevision)
  })
}

/**
 * 冻结一次可幂等重试的脑图保存批次。
 *
 * @param {Object} options 保存上下文
 * @returns {Object|null} 不可变批次；没有操作时返回 null
 */
export function createMindmapSaveMutation({
  clientMutationId,
  baseRevision,
  operations,
  document,
  viewChangeVersion,
  contentChangeVersion = 0,
  yjsUpdateCount = 0,
  yjsDeliveryMode = 'sequenced',
  rebaseAttempts = 0,
}) {
  if (!Array.isArray(operations) || operations.length === 0) return null
  if (!clientMutationId) throw new TypeError('Mindmap save mutation requires a clientMutationId')
  if (!Number.isInteger(yjsUpdateCount) || yjsUpdateCount < 0) {
    throw new TypeError('Mindmap save mutation requires a valid Yjs update count')
  }
  if (!['sequenced', 'reload'].includes(yjsDeliveryMode)) {
    throw new TypeError('Mindmap save mutation requires a valid Yjs delivery mode')
  }

  const frozenOperations = cloneRequestPayload(operations)
  const frozenDocument = cloneRequestPayload(document)
  const payload = Object.freeze({
    baseRevision,
    clientMutationId,
    yjsUpdateCount,
    yjsDeliveryMode,
    operations: frozenOperations,
    nodeTree: frozenDocument.root,
    viewData: frozenDocument.view,
    layout: frozenDocument.layout,
    theme: frozenDocument.theme,
    documentData: frozenDocument.documentData,
  })

  return Object.freeze({
    clientMutationId,
    baseRevision,
    operations: frozenOperations,
    document: frozenDocument,
    viewChangeVersion,
    contentChangeVersion,
    yjsUpdateCount,
    yjsDeliveryMode,
    rebaseAttempts,
    payload,
  })
}

/**
 * 对缺少完整服务端变更历史的细粒度保存批次自动推进基线。
 *
 * 这里只允许重放有节点 revision 保护、只修改父子边的节点操作，以及采用
 * 后写覆盖语义的画布视口。其余文件字段、关系、标签和整树替换在缺少历史时
 * 无法证明没有同域修改，仍交给人工恢复流程。
 */
export function rebaseMindmapSaveMutation(mutation, conflictData, maxAttempts = 3) {
  const currentRevision = Number(conflictData?.currentRevision)
  const reportedConflicts = [
    conflictData?.conflictNodeUids,
    conflictData?.conflictNodes,
    conflictData?.conflictFields,
    conflictData?.conflictEntities,
  ].some(items => Array.isArray(items) && items.length > 0)
  const operations = mutation?.operations
  if (
    conflictData?.requiresSnapshot !== true
    || reportedConflicts
    // 已发送过 Yjs 帧的批次绑定原始 collaboration revision/lineage。
    // 即使 HTTP 操作本身可重放，也不能把同 mutation/frame 声明改基到
    // 新 revision；只有从未发过实时帧的纯 HTTP 批次允许自动 rebase。
    || mutation?.yjsUpdateCount !== 0
    || !Number.isInteger(currentRevision)
    || currentRevision <= Number(mutation?.baseRevision)
    || !isAutoRebaseSafeOperationSet(operations)
    || Number(mutation?.rebaseAttempts || 0) >= maxAttempts
  ) return null

  return createMindmapSaveMutation({
    clientMutationId: mutation.clientMutationId,
    baseRevision: currentRevision,
    operations,
    document: mutation.document,
    viewChangeVersion: mutation.viewChangeVersion,
    contentChangeVersion: mutation.contentChangeVersion,
    yjsUpdateCount: mutation.yjsUpdateCount,
    yjsDeliveryMode: mutation.yjsDeliveryMode,
    rebaseAttempts: Number(mutation.rebaseAttempts || 0) + 1,
  })
}

/**
 * 串行提交一个不可变批次，并在仅缺少历史基线时自动重放细粒度操作。
 * 返回最终实际提交的 mutation，调用方据此校验响应和推进本地 revision。
 */
export async function submitMindmapSaveMutation(mutation, submit, options = {}) {
  if (!mutation || typeof submit !== 'function') {
    throw new TypeError('Mindmap save submission requires a mutation and submit function')
  }
  let currentMutation = mutation
  while (true) {
    try {
      const response = await submit(currentMutation.payload, currentMutation)
      return { response, mutation: currentMutation }
    } catch (error) {
      const rebasedMutation = rebaseMindmapSaveMutation(
        currentMutation,
        error?.data,
        options.maxRebaseAttempts,
      )
      if (!rebasedMutation) throw error
      currentMutation = rebasedMutation
      options.onRebase?.(currentMutation, error)
    }
  }
}

/**
 * 验证服务端响应确实属于当前保存批次，避免迟到或串线响应推进本地 revision。
 *
 * @param {Object} mutation 当前批次
 * @param {Object} responseData 服务端响应数据
 * @returns {void}
 */
export function assertMindmapSaveMutationResponse(mutation, responseData) {
  if (!mutation?.clientMutationId) throw new TypeError('Mindmap save mutation is missing')
  if (responseData?.clientMutationId !== mutation.clientMutationId) {
    throw new Error('脑图保存响应与当前请求批次不匹配')
  }
}
