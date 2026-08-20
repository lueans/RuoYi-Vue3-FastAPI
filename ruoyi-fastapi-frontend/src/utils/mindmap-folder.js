export const MAX_FOLDER_NAME_LENGTH = 100
export const MAX_FOLDER_SORT_ORDER = 1_000_000

export function normalizeFolderName(value) {
  return String(value ?? '').trim()
}

export function validateFolderName(value) {
  if (typeof value !== 'string') {
    return { valid: false, value: '', message: '文件夹名称必须为字符串' }
  }
  const normalized = normalizeFolderName(value)
  if (!normalized) {
    return { valid: false, value: normalized, message: '文件夹名称不能为空' }
  }
  if (/\p{Cc}/u.test(normalized)) {
    return { valid: false, value: normalized, message: '文件夹名称不能包含控制字符' }
  }
  if (/[\\/]/u.test(normalized)) {
    return { valid: false, value: normalized, message: '文件夹名称不能包含路径分隔符' }
  }
  if (Array.from(normalized).length > MAX_FOLDER_NAME_LENGTH) {
    return {
      valid: false,
      value: normalized,
      message: `文件夹名称不能超过 ${MAX_FOLDER_NAME_LENGTH} 个字符`,
    }
  }
  return { valid: true, value: normalized, message: '' }
}

export function getFolderSubtreeIds(tree, rootId) {
  const targetId = Number(rootId)
  const result = new Set()
  const visit = (nodes, insideTarget = false) => {
    for (const node of Array.isArray(nodes) ? nodes : []) {
      const isInside = insideTarget || Number(node?.id) === targetId
      if (isInside) result.add(Number(node.id))
      visit(node?.children, isInside)
    }
  }
  visit(tree)
  return result
}

export function pruneFolderTree(tree, excludedId) {
  if (!excludedId) return Array.isArray(tree) ? tree : []
  const excludedIds = getFolderSubtreeIds(tree, excludedId)
  const clone = nodes => (Array.isArray(nodes) ? nodes : [])
    .filter(node => !excludedIds.has(Number(node?.id)))
    .map(node => ({
      ...node,
      ...(Array.isArray(node.children) ? { children: clone(node.children) } : {}),
    }))
  return clone(tree)
}

export function formatFolderDeletePrompt(impact) {
  const folderName = impact?.folderName || '未命名文件夹'
  const subfolderCount = Math.max(0, Number(impact?.subfolderCount) || 0)
  const mindmapCount = Math.max(0, Number(impact?.mindmapCount) || 0)
  const subfolderText = subfolderCount
    ? `并同时删除 ${subfolderCount} 个子文件夹，`
    : ''
  const mindmapText = mindmapCount
    ? `其中 ${mindmapCount} 张脑图会移至根目录，脑图内容不会删除。`
    : '其中没有脑图会被删除。'
  return `删除“${folderName}”后，${subfolderText}${mindmapText}`
}

export function normalizeFolderTarget(value) {
  const target = Number(value)
  return Number.isInteger(target) && target > 0 ? target : null
}

export function getMindmapFolderErrorMessage(error, fallback = '目录操作失败') {
  return error?.response?.data?.msg || error?.message || fallback
}
