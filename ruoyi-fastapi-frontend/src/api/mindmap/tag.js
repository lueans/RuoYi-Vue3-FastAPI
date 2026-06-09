import request from '@/utils/request'

// ── 标签分类 ──

export function listTagCategories() {
  return request({
    url: '/mindmap/tag/categories',
    method: 'get'
  })
}

export function addTagCategory(name, sortOrder) {
  return request({
    url: '/mindmap/tag/category',
    method: 'post',
    params: { categoryName: name, sortOrder: sortOrder || 0 }
  })
}

export function updateTagCategory(categoryId, name, sortOrder) {
  return request({
    url: '/mindmap/tag/category',
    method: 'put',
    params: { categoryId, categoryName: name, sortOrder: sortOrder || 0 }
  })
}

export function deleteTagCategory(categoryId) {
  return request({
    url: '/mindmap/tag/category/' + categoryId,
    method: 'delete'
  })
}

// ── 标签 ──

export function listTags(query) {
  return request({
    url: '/mindmap/tag/list',
    method: 'get',
    params: query
  })
}

export function getTag(tagId) {
  return request({
    url: '/mindmap/tag/' + tagId,
    method: 'get'
  })
}

export function addTag(data) {
  return request({
    url: '/mindmap/tag',
    method: 'post',
    data: data
  })
}

export function updateTag(data) {
  return request({
    url: '/mindmap/tag',
    method: 'put',
    data: data
  })
}

export function deleteTags(tagIds) {
  return request({
    url: '/mindmap/tag/' + tagIds,
    method: 'delete'
  })
}

// 标签建议（编辑器自动补全）
export function getTagSuggestions(keyword) {
  return request({
    url: '/mindmap/tag/suggestions',
    method: 'get',
    params: { keyword }
  })
}
