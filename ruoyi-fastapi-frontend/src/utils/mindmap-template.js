const ALLOWED_TEMPLATE_COVER_PROTOCOLS = new Set(['http:', 'https:'])

export function getMindmapTemplateErrorMessage(error, fallback = '操作失败，请稍后重试') {
  const message = typeof error === 'string' ? error : error?.message
  return String(message || fallback).trim() || fallback
}

export function getSafeTemplateCoverUrl(value, baseUrl) {
  const raw = String(value || '').trim()
  if (!raw || raw.length > 500) return ''
  if (raw.startsWith('//')) return ''
  if (raw.startsWith('/') && !raw.startsWith('//')) return raw
  try {
    const parsed = new URL(raw, baseUrl || globalThis.location?.href || 'http://localhost/')
    if (!ALLOWED_TEMPLATE_COVER_PROTOCOLS.has(parsed.protocol)) return ''
    if (parsed.username || parsed.password) return ''
    return raw
  } catch {
    return ''
  }
}

export { extractCreatedMindmapId } from './mindmap-creation.js'

export function getTemplateCategoryName(categories, categoryId) {
  if (categoryId == null) return '未分类'
  const category = (Array.isArray(categories) ? categories : [])
    .find(item => Number(item?.id) === Number(categoryId))
  return category?.name || '未分类'
}
