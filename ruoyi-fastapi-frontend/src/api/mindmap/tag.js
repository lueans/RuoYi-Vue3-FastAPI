import request from '@/utils/request'

// ── 统一标签 API ──

export function listTagCategories() {
  return request({
    url: '/mindmap/tag/categories',
    method: 'get'
  })
}

export function addTagCategory(
  name,
  sortOrder,
  ownerScope = 'mine',
  showOnHome = false,
  selectionMode = 'multiple'
) {
  return request({
    url: '/mindmap/tag/category',
    method: 'post',
    params: {
      categoryName: name,
      sortOrder: sortOrder ?? 0,
      ownerScope,
      showOnHome,
      selectionMode
    }
  })
}

export function updateTagCategory(categoryId, name, sortOrder, showOnHome, selectionMode) {
  return request({
    url: '/mindmap/tag/category',
    method: 'put',
    params: {
      categoryId,
      categoryName: name,
      sortOrder: sortOrder ?? 0,
      showOnHome,
      selectionMode
    }
  })
}

export function reorderTagCategories(categoryIds) {
  return request({
    url: '/mindmap/tag/categories/order',
    method: 'put',
    data: { categoryIds }
  })
}

export function deleteTagCategory(categoryId) {
  return request({
    url: '/mindmap/tag/category/' + categoryId,
    method: 'delete'
  })
}

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

export function getTagImpact(tagId) {
  return request({
    url: '/mindmap/tag/' + tagId + '/impact',
    method: 'get'
  })
}

export function getTagUsages(tagId, query) {
  return request({
    url: '/mindmap/tag/' + tagId + '/usages',
    method: 'get',
    params: query
  })
}

export function disableTag(tagId) {
  return request({
    url: '/mindmap/tag/' + tagId + '/disable',
    method: 'post'
  })
}

export function replaceTag(tagId, targetTagId) {
  return request({
    url: '/mindmap/tag/' + tagId + '/replace',
    method: 'post',
    data: { targetTagId }
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

export function deleteTags(tagIds, unbind = false) {
  return request({
    url: '/mindmap/tag/' + tagIds,
    method: 'delete',
    params: { unbind }
  })
}

export function getTagSuggestions(keyword) {
  return request({
    url: '/mindmap/tag/suggestions',
    method: 'get',
    params: { keyword }
  })
}
