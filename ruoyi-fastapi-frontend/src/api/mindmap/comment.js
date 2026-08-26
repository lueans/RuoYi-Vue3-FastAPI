import request from '@/utils/request'

export function listMindmapComments(mindmapId, query = {}) {
  return request({
    url: '/mindmap/comment/list/' + mindmapId,
    method: 'get',
    params: query,
    silentError: true,
  })
}

export function createMindmapComment(data, idempotencyKey) {
  return request({
    url: '/mindmap/comment',
    method: 'post',
    data,
    headers: { 'Idempotency-Key': idempotencyKey },
    silentError: true,
  })
}

export function replyMindmapComment(threadId, content, idempotencyKey) {
  return request({
    url: '/mindmap/comment/' + threadId + '/reply',
    method: 'post',
    data: { content },
    headers: { 'Idempotency-Key': idempotencyKey },
    silentError: true,
  })
}

export function updateMindmapCommentStatus(threadId, resolved) {
  return request({
    url: '/mindmap/comment/' + threadId + '/status',
    method: 'put',
    data: { resolved },
    silentError: true,
  })
}

export function deleteMindmapComment(commentId) {
  return request({
    url: '/mindmap/comment/message/' + commentId,
    method: 'delete',
    silentError: true,
  })
}
