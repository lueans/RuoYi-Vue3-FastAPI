import request from '@/utils/request'

// 创建分享链接
export function createShareLink(data) {
  return request({
    url: '/mindmap/share/link',
    method: 'post',
    data: data,
    silentError: true,
  })
}

// 获取分享链接列表
export function getShareLinks(mindmapId) {
  return request({
    url: '/mindmap/share/link/' + mindmapId,
    method: 'get',
    silentError: true,
  })
}

// 禁用分享链接
export function deleteShareLink(shareId) {
  return request({
    url: '/mindmap/share/link/' + shareId,
    method: 'delete',
    silentError: true,
  })
}

// 通过分享 token 查看脑图（公开接口，不需要 token）
export function viewByShareToken(shareToken, { signal } = {}) {
  return request({
    url: '/mindmap/share/view/' + encodeURIComponent(String(shareToken)),
    method: 'get',
    headers: { isToken: false },
    signal,
    silentError: true,
  })
}

// 已登录用户通过编辑邀请加入脑图
export function joinEditShare(shareToken, { signal } = {}) {
  return request({
    url: '/mindmap/share/join/' + encodeURIComponent(String(shareToken)),
    method: 'post',
    signal,
    silentError: true,
  })
}
