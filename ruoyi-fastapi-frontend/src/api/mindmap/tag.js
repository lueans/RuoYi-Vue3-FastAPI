import request from '@/utils/request'

// ── 标签字段 ──

export function listTagFields() {
  return request({
    url: '/mindmap/tag-field/list',
    method: 'get'
  })
}

export function getTagFieldDetail(fieldId) {
  return request({
    url: '/mindmap/tag-field/' + fieldId,
    method: 'get'
  })
}

export function addTagField(data) {
  return request({
    url: '/mindmap/tag-field',
    method: 'post',
    data: data
  })
}

export function updateTagField(data) {
  return request({
    url: '/mindmap/tag-field',
    method: 'put',
    data: data
  })
}

export function deleteTagField(fieldId) {
  return request({
    url: '/mindmap/tag-field/' + fieldId,
    method: 'delete'
  })
}

// ── 字段选项 ──

export function addTagFieldOption(data) {
  return request({
    url: '/mindmap/tag-field/option',
    method: 'post',
    data: data
  })
}

export function updateTagFieldOption(data) {
  return request({
    url: '/mindmap/tag-field/option',
    method: 'put',
    data: data
  })
}

export function deleteTagFieldOption(optionId) {
  return request({
    url: '/mindmap/tag-field/option/' + optionId,
    method: 'delete'
  })
}

export function batchUpdateOptionSort(fieldId, sortList) {
  return request({
    url: '/mindmap/tag-field/option/sort/' + fieldId,
    method: 'put',
    data: sortList
  })
}

// ── 搜索建议（侧边栏用） ──

export function getTagFieldSuggestions(keyword) {
  return request({
    url: '/mindmap/tag-field/suggestions',
    method: 'get',
    params: { keyword }
  })
}

// ── 旧标签 API（过渡期保留） ──

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

export function getTagSuggestions(keyword) {
  return request({
    url: '/mindmap/tag/suggestions',
    method: 'get',
    params: { keyword }
  })
}
