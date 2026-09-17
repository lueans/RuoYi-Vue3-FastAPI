import request from '@/utils/request'
import { assertMindmapAiArtifactDownloadResponse } from '@/utils/mindmap-ai-errors'

const MINDMAP_SAVE_TIMEOUT_MS = 30_000

// 幂等写请求统一携带 Idempotency-Key 并关闭客户端防重；
// data/timeout/signal/silentError 等差异由调用方通过 extra 覆盖。
function idempotentPost(url, idempotencyKey, extra = {}) {
  return request({
    url,
    method: 'post',
    headers: {
      'Idempotency-Key': idempotencyKey,
      repeatSubmit: false,
    },
    ...extra,
  })
}

// 查询脑图列表
export function listMindmap(query) {
  return request({
    url: '/mindmap/list',
    method: 'get',
    params: query
  })
}

// 查询脑图详情
export function getMindmap(mindmapId, { signal, silentError = false } = {}) {
  return request({
    url: '/mindmap/' + mindmapId,
    method: 'get',
    signal,
    silentError,
  })
}

// 新增脑图
export function addMindmap(data, idempotencyKey) {
  return idempotentPost('/mindmap', idempotencyKey, { data })
}

// 编辑脑图元数据
export function updateMindmap(data) {
  return request({
    url: '/mindmap',
    method: 'put',
    data: data
  })
}

// 更新脑图名称与说明（严格文件信息契约）
export function updateMindmapMetadata(data) {
  return request({
    url: '/mindmap/metadata',
    method: 'put',
    data,
  })
}

// 将脑图移入回收站
export function delMindmap(mindmapIds) {
  return request({
    url: '/mindmap/' + mindmapIds,
    method: 'delete'
  })
}

// 从回收站恢复脑图
export function restoreMindmap(mindmapIds) {
  return request({
    url: '/mindmap/trash/restore/' + mindmapIds,
    method: 'put'
  })
}

// 永久删除回收站脑图
export function permanentlyDeleteMindmap(mindmapIds) {
  return request({
    url: '/mindmap/trash/' + mindmapIds,
    method: 'delete'
  })
}

// 重命名脑图
export function renameMindmap(data) {
  return request({
    url: '/mindmap/rename',
    method: 'put',
    data: data
  })
}

// 归档或恢复脑图（0=正常，1=归档）
export function updateMindmapStatus(data) {
  return request({
    url: '/mindmap/status',
    method: 'put',
    data: data
  })
}

// 批量归档或恢复脑图（完整集合原子校验，最多100张）
export function batchUpdateMindmapStatus(data) {
  return request({
    url: '/mindmap/status/batch',
    method: 'put',
    data: data
  })
}

// 复制脑图
export function copyMindmap(mindmapId, idempotencyKey) {
  return idempotentPost('/mindmap/copy/' + mindmapId, idempotencyKey)
}

// 更新脑图内容（自动保存）
export function updateMindmapContent(data) {
  return request({
    url: '/mindmap/content',
    method: 'put',
    data: data
  })
}

// 批量增量保存（带 revision 与 clientMutationId）
export function batchUpdateMindmapContent(mindmapId, data) {
  return request({
    url: '/mindmap/file/' + mindmapId + '/content/batch',
    method: 'patch',
    data: data,
    // clientMutationId 已提供服务端幂等；避免客户端再次哈希整棵树并阻断安全重试。
    headers: { repeatSubmit: false },
    timeout: MINDMAP_SAVE_TIMEOUT_MS
  })
}

// 用户明确选择云端版本时推进 revision，并废弃整个旧协作基线。
export function resetMindmapCollaboration(mindmapId, data) {
  return request({
    url: '/mindmap/file/' + mindmapId + '/collaboration/reset',
    method: 'post',
    data,
    headers: { repeatSubmit: false },
    timeout: MINDMAP_SAVE_TIMEOUT_MS,
  })
}

// 视图状态不推进正文 revision，但旧 revision 的迟到请求会被服务端拒绝。
export function updateMindmapView(mindmapId, viewData, expectedContentRevision) {
  return request({
    url: '/mindmap/file/' + mindmapId + '/view',
    method: 'patch',
    data: { viewData, expectedContentRevision },
    headers: { repeatSubmit: false },
    timeout: 5000,
    silentError: true,
  })
}

export function getMindmapContentChanges(mindmapId, afterRevision) {
  return request({
    url: '/mindmap/file/' + mindmapId + '/changes',
    method: 'get',
    params: { afterRevision }
  })
}

export function searchMindmapNodes(mindmapId, query) {
  return request({
    url: '/mindmap/file/' + mindmapId + '/nodes/search',
    method: 'get',
    params: query
  })
}

// 跨当前用户可访问的脑图搜索节点
export function searchGlobalMindmapNodes(query) {
  return request({
    url: '/mindmap/nodes/search',
    method: 'get',
    params: query
  })
}

// 从本地存储导入脑图
export function importMindmap(data, idempotencyKey) {
  return idempotentPost('/mindmap/import', idempotencyKey, { data })
}

export function listMindmapAiAgents(params = {}) {
  return request({
    url: '/mindmap/ai/agents',
    method: 'get',
    params,
  })
}

// 管理端：查询和维护 Agent Connector。密钥只允许传服务端引用，不返回引用内容。
export function listMindmapAiConnectors() {
  return request({
    url: '/mindmap/ai/admin/connectors',
    method: 'get',
  })
}

export function updateMindmapAiConnector(agentKey, data) {
  return request({
    url: `/mindmap/ai/admin/connectors/${agentKey}`,
    method: 'patch',
    data,
  })
}

export function healthCheckMindmapAiConnector(agentKey) {
  return request({
    url: `/mindmap/ai/admin/connectors/${agentKey}/health-check`,
    method: 'post',
    headers: { repeatSubmit: false },
  })
}

export function conformanceMindmapAiConnector(agentKey) {
  return request({
    url: `/mindmap/ai/admin/connectors/${agentKey}/conformance`,
    method: 'post',
    headers: { repeatSubmit: false },
  })
}

export function createMindmapAiJob(data, idempotencyKey) {
  return idempotentPost('/mindmap/ai/jobs', idempotencyKey, {
    data,
    timeout: MINDMAP_SAVE_TIMEOUT_MS,
    silentError: true,
  })
}

export function getMindmapAiJob(jobId, { signal } = {}) {
  return request({
    url: `/mindmap/ai/jobs/${jobId}`,
    method: 'get',
    signal,
    silentError: true,
  })
}

export function reconcileMindmapAiJob(idempotencyKey, { signal } = {}) {
  return request({
    url: '/mindmap/ai/jobs/reconcile',
    method: 'get',
    headers: { 'Idempotency-Key': idempotencyKey },
    signal,
    silentError: true,
  })
}

export function getMindmapAiJobDraft(jobId, { signal, version } = {}) {
  const requestedVersion = Number(version)
  return request({
    url: `/mindmap/ai/jobs/${jobId}/draft`,
    method: 'get',
    params: Number.isSafeInteger(requestedVersion) && requestedVersion >= 0
      ? { version: requestedVersion }
      : undefined,
    signal,
    silentError: true,
  })
}

export function getMindmapAiSessionTimeline(sessionId, { signal } = {}) {
  return request({
    url: `/mindmap/ai/sessions/${sessionId}`,
    method: 'get',
    signal,
    silentError: true,
  })
}

export function listMindmapAiSessions({ limit = 20, signal } = {}) {
  return request({
    url: '/mindmap/ai/sessions',
    method: 'get',
    params: { limit },
    signal,
    silentError: true,
  })
}

export function deleteMindmapAiSession(sessionId) {
  return request({
    url: `/mindmap/ai/sessions/${sessionId}`,
    method: 'delete',
    headers: { repeatSubmit: false },
    silentError: true,
  })
}

export function continueMindmapAiJob(jobId, data, idempotencyKey, { signal } = {}) {
  return idempotentPost(`/mindmap/ai/jobs/${jobId}/messages`, idempotencyKey, {
    data,
    timeout: MINDMAP_SAVE_TIMEOUT_MS,
    signal,
    silentError: true,
  })
}

export function retryMindmapAiJob(jobId, data, idempotencyKey, { signal } = {}) {
  return idempotentPost(`/mindmap/ai/jobs/${jobId}/retry`, idempotencyKey, {
    data,
    timeout: MINDMAP_SAVE_TIMEOUT_MS,
    signal,
    silentError: true,
  })
}

export function cancelMindmapAiJob(jobId) {
  return request({
    url: `/mindmap/ai/jobs/${jobId}/cancel`,
    method: 'post',
    headers: { repeatSubmit: false },
    silentError: true,
  })
}

export async function downloadMindmapAiArtifact(artifactId) {
  const blob = await request({
    url: `/mindmap/ai/artifacts/${artifactId}/download`,
    method: 'get',
    responseType: 'blob',
    timeout: MINDMAP_SAVE_TIMEOUT_MS,
  })
  return assertMindmapAiArtifactDownloadResponse(blob)
}

export function validateMindmapAiArtifact(artifact, requirePassed = true) {
  return request({
    url: '/mindmap/ai/artifacts/validate',
    method: 'post',
    // 显式使用服务端字段名，不依赖 Pydantic 的别名策略。
    data: { artifact, require_passed: requirePassed },
    // 该接口只做无副作用的安全复校验。终态水合会先校验预览，
    // 随后从同一 artifact 读取人工问题清单；两次请求可能在 1 秒内
    // 完成，不应被全局写请求防重误判为重复提交。
    headers: { repeatSubmit: false },
  })
}

export function prepareMindmapAiLocalApply(proposalId) {
  return request({
    url: `/mindmap/ai/proposals/${proposalId}/prepare-local-apply`,
    method: 'post',
    headers: { repeatSubmit: false },
  })
}

export function getMindmapAiProposal(proposalId, { signal } = {}) {
  return request({
    url: `/mindmap/ai/proposals/${proposalId}`,
    method: 'get',
    signal,
    silentError: true,
  })
}

export function ackMindmapAiLocalApply(proposalId, data) {
  return request({
    url: `/mindmap/ai/proposals/${proposalId}/ack-local-apply`,
    method: 'post',
    data,
    headers: { repeatSubmit: false },
    silentError: true,
  })
}

export function ackMindmapAiLocalUndo(proposalId, data) {
  return request({
    url: `/mindmap/ai/proposals/${proposalId}/ack-local-undo`,
    method: 'post',
    data,
    headers: { repeatSubmit: false },
    silentError: true,
  })
}

export function saveMindmapAiArtifactCloud(artifactId, data, idempotencyKey) {
  return idempotentPost(
    `/mindmap/ai/artifacts/${artifactId}/save-cloud`,
    idempotencyKey,
    { data, silentError: true },
  )
}

export function applyMindmapAiCloudProposal(
  mindmapId,
  proposalId,
  data,
  idempotencyKey,
  { signal } = {},
) {
  return idempotentPost(
    `/mindmap/file/${mindmapId}/ai/proposals/${proposalId}/apply`,
    idempotencyKey,
    { data, timeout: MINDMAP_SAVE_TIMEOUT_MS, signal, silentError: true },
  )
}

export function undoMindmapAiCloudProposal(
  mindmapId,
  proposalId,
  idempotencyKey,
  { signal } = {},
) {
  return idempotentPost(
    `/mindmap/file/${mindmapId}/ai/proposals/${proposalId}/undo`,
    idempotencyKey,
    { timeout: MINDMAP_SAVE_TIMEOUT_MS, signal, silentError: true },
  )
}
