const INVALID_FILE_NAME = /[<>:"/\\|?*\u0000-\u001F]/
const RESERVED_WINDOWS_NAME = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/i
const MAX_EXPORT_NAME_LENGTH = 120

export function validateMindmapExportName(value, type = '') {
  let name = String(value ?? '').trim()
  const extension = String(type || '').trim().replace(/^\./, '')
  if (extension) {
    name = name.replace(new RegExp(`\\.${extension.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'i'), '').trim()
  }
  if (!name) return { name: '', error: '请输入导出文件名称' }
  if (
    name === '.'
    || name === '..'
    || INVALID_FILE_NAME.test(name)
    || RESERVED_WINDOWS_NAME.test(name)
  ) {
    return { name, error: '文件名不能包含路径符号或系统保留字符' }
  }
  if (/[. ]$/.test(name)) return { name, error: '文件名不能以空格或句点结尾' }
  if (name.length > MAX_EXPORT_NAME_LENGTH) {
    return { name, error: `文件名不能超过 ${MAX_EXPORT_NAME_LENGTH} 个字符` }
  }
  return { name, error: '' }
}

export function normalizeMindmapExportPadding(value, fallback = 10) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(200, Math.max(0, Math.round(parsed)))
}

export function normalizeMindmapExportRuntimeConfig(value = {}) {
  const config = value && typeof value === 'object' ? value : {}
  return {
    exportPaddingX: normalizeMindmapExportPadding(config.exportPaddingX),
    exportPaddingY: normalizeMindmapExportPadding(config.exportPaddingY),
    addContentToFooter: typeof config.addContentToFooter === 'function'
      ? config.addContentToFooter
      : null,
  }
}
