import request from '@/utils/request'

// 创建分享链接
export function createShareLink(data) {
  return request({
    url: '/mindmap/share/link',
    method: 'post',
    data: data
  })
}

// 获取分享链接列表
export function getShareLinks(mindmapId) {
  return request({
    url: '/mindmap/share/link/' + mindmapId,
    method: 'get'
  })
}

// 禁用分享链接
export function deleteShareLink(shareId) {
  return request({
    url: '/mindmap/share/link/' + shareId,
    method: 'delete'
  })
}

// 通过分享 token 查看脑图（公开接口，不需要 token）
export function viewByShareToken(shareToken) {
  return request({
    url: '/mindmap/share/view/' + shareToken,
    method: 'get',
    headers: { isToken: false }
  })
}
