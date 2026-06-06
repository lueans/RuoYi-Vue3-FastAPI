import request from '@/utils/request'

// 获取模板列表（公开）
export function listTemplates(query) {
  return request({
    url: '/mindmap/template/list',
    method: 'get',
    params: query,
    headers: { isToken: false }
  })
}

// 获取模板分类（公开）
export function getTemplateCategories() {
  return request({
    url: '/mindmap/template/categories',
    method: 'get',
    headers: { isToken: false }
  })
}

// 获取模板详情（公开）
export function getTemplateDetail(templateId) {
  return request({
    url: '/mindmap/template/' + templateId,
    method: 'get',
    headers: { isToken: false }
  })
}

// 使用模板创建脑图
export function useTemplate(templateId) {
  return request({
    url: '/mindmap/template/use/' + templateId,
    method: 'post'
  })
}

// 发布模板（管理员）
export function publishTemplate(data) {
  return request({
    url: '/mindmap/template',
    method: 'post',
    data: data
  })
}

// 下架模板（管理员）
export function unpublishTemplate(templateId) {
  return request({
    url: '/mindmap/template/' + templateId,
    method: 'delete'
  })
}

// 新增模板分类（管理员）
export function addTemplateCategory(name, sortOrder) {
  return request({
    url: '/mindmap/template/category',
    method: 'post',
    params: { name, sortOrder: sortOrder || 0 }
  })
}

// 删除模板分类（管理员）
export function deleteTemplateCategory(categoryId) {
  return request({
    url: '/mindmap/template/category/' + categoryId,
    method: 'delete'
  })
}
