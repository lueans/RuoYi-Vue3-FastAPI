import request from '@/utils/request'

// 获取版本列表
export function listVersions(mindmapId, query) {
  return request({
    url: '/mindmap/version/list/' + mindmapId,
    method: 'get',
    params: query
  })
}

// 获取版本详情
export function getVersionDetail(versionId) {
  return request({
    url: '/mindmap/version/' + versionId,
    method: 'get'
  })
}

// 回滚到指定版本
export function restoreVersion(versionId) {
  return request({
    url: '/mindmap/version/restore/' + versionId,
    method: 'post'
  })
}

// 创建正式版本
export function saveFormalVersion(data) {
  return request({
    url: '/mindmap/version/save',
    method: 'post',
    data: data
  })
}

// 删除版本
export function deleteVersion(versionId) {
  return request({
    url: '/mindmap/version/' + versionId,
    method: 'delete'
  })
}
