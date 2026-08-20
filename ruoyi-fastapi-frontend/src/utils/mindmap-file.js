export const MAX_MINDMAP_NAME_LENGTH = 200
export const MAX_MINDMAP_DESCRIPTION_LENGTH = 500
export const MAX_MINDMAP_FILE_KEYWORD_LENGTH = 100

export function normalizeMindmapName(value) {
  return String(value ?? '').trim()
}

export function validateMindmapName(value) {
  const normalized = normalizeMindmapName(value)
  if (!normalized) {
    return { valid: false, value: normalized, message: '脑图名称不能为空' }
  }
  if (/[\u0000-\u001f\u007f]/u.test(normalized)) {
    return { valid: false, value: normalized, message: '脑图名称不能包含控制字符' }
  }
  if (Array.from(normalized).length > MAX_MINDMAP_NAME_LENGTH) {
    return {
      valid: false,
      value: normalized,
      message: `脑图名称不能超过 ${MAX_MINDMAP_NAME_LENGTH} 个字符`,
    }
  }
  return { valid: true, value: normalized, message: '' }
}

export function validateMindmapDescription(value) {
  const normalized = String(value ?? '').trim()
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(normalized)) {
    return { valid: false, value: normalized, message: '脑图说明不能包含不可见控制字符' }
  }
  if (Array.from(normalized).length > MAX_MINDMAP_DESCRIPTION_LENGTH) {
    return {
      valid: false,
      value: normalized,
      message: `脑图说明不能超过 ${MAX_MINDMAP_DESCRIPTION_LENGTH} 个字符`,
    }
  }
  return { valid: true, value: normalized, message: '' }
}

export function getMindmapFileErrorMessage(error, fallback) {
  return error?.response?.data?.msg || error?.message || fallback
}

export function formatMindmapDeletePrompt(items) {
  const list = Array.isArray(items) ? items.filter(Boolean) : []
  if (list.length === 1) {
    return `将“${list[0].name || '未命名脑图'}”移入回收站？内容、版本和权限都会保留；分享与协作访问会暂停，恢复后重新生效。`
  }
  return `将选中的 ${list.length} 张脑图移入回收站？内容、版本和权限都会保留；分享与协作访问会暂停，恢复后重新生效。`
}

export function formatMindmapPermanentDeletePrompt(items) {
  const list = Array.isArray(items) ? items.filter(Boolean) : []
  if (list.length === 1) {
    return `永久删除“${list[0].name || '未命名脑图'}”？内容、版本、分享链接和协作者权限都将被清除，此操作无法撤销。`
  }
  return `永久删除选中的 ${list.length} 张脑图？所有内容、版本和访问配置都将被清除，此操作无法撤销。`
}

export function formatMindmapArchivePrompt(item) {
  const name = item?.name || '未命名脑图'
  return `归档“${name}”后，内容、版本、分享链接和协作者都会保留，但所有在线编辑会话将立即结束，恢复前只能查看。`
}

export function formatMindmapBatchArchivePrompt(items) {
  const count = Array.isArray(items) ? items.filter(Boolean).length : 0
  return `归档选中的 ${count} 张脑图后，内容、版本、分享链接和协作者都会保留，但这些文件的在线编辑会话将立即结束，恢复前只能查看。`
}
