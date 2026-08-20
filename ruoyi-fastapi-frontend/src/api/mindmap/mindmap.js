import request from '@/utils/request'

const MINDMAP_SAVE_TIMEOUT_MS = 30_000

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
  return request({
    url: '/mindmap',
    method: 'post',
    data: data,
    headers: {
      'Idempotency-Key': idempotencyKey,
      repeatSubmit: false,
    },
  })
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
  return request({
    url: '/mindmap/copy/' + mindmapId,
    method: 'post',
    headers: {
      'Idempotency-Key': idempotencyKey,
      repeatSubmit: false,
    },
  })
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
  return request({
    url: '/mindmap/import',
    method: 'post',
    data: data,
    headers: {
      'Idempotency-Key': idempotencyKey,
      repeatSubmit: false,
    },
  })
}
