import request from '@/utils/request'

// 查询脑图列表
export function listMindmap(query) {
  return request({
    url: '/mindmap/list',
    method: 'get',
    params: query
  })
}

// 查询脑图详情
export function getMindmap(mindmapId) {
  return request({
    url: '/mindmap/' + mindmapId,
    method: 'get'
  })
}

// 新增脑图
export function addMindmap(data) {
  return request({
    url: '/mindmap',
    method: 'post',
    data: data
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

// 删除脑图
export function delMindmap(mindmapIds) {
  return request({
    url: '/mindmap/' + mindmapIds,
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

// 复制脑图
export function copyMindmap(mindmapId) {
  return request({
    url: '/mindmap/copy/' + mindmapId,
    method: 'post'
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

// 从本地存储导入脑图
export function importMindmap(data) {
  return request({
    url: '/mindmap/import',
    method: 'post',
    data: data
  })
}
