import request from '@/utils/request'

// 添加协作者
export function addCollaborator(data) {
  return request({
    url: '/mindmap/collaborator',
    method: 'post',
    data: data
  })
}

// 获取协作者列表
export function getCollaborators(mindmapId) {
  return request({
    url: '/mindmap/collaborator/list/' + mindmapId,
    method: 'get'
  })
}

// 修改协作者权限
export function updateCollaboratorPermission(data) {
  return request({
    url: '/mindmap/collaborator',
    method: 'put',
    data: data
  })
}

// 移除协作者
export function removeCollaborator(collabId) {
  return request({
    url: '/mindmap/collaborator/' + collabId,
    method: 'delete'
  })
}
