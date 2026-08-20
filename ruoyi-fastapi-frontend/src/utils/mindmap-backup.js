import { stringifyJsonValueIterative } from '../libs/simple-mind-map/src/utils/jsonClone.js'

const DEFAULT_BACKUP_PREFIX = 'mindmap-backup'

function sanitizeFileSegment(value, fallback) {
  const normalized = String(value ?? '')
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[.-]+|[. -]+$/g, '')
    .slice(0, 80)
  return normalized || fallback
}

export function createMindmapBackupFileName({
  prefix = DEFAULT_BACKUP_PREFIX,
  mindmapId,
  timestamp = Date.now(),
} = {}) {
  const safePrefix = sanitizeFileSegment(prefix, DEFAULT_BACKUP_PREFIX)
  const safeId = sanitizeFileSegment(mindmapId, 'local')
  const safeTimestamp = Number.isFinite(Number(timestamp))
    ? Math.max(0, Math.trunc(Number(timestamp)))
    : Date.now()
  return `${safePrefix}-${safeId}-${safeTimestamp}.json`
}

export function serializeMindmapBackup(document) {
  if (!document || typeof document !== 'object' || Array.isArray(document)) {
    throw new Error('脑图备份内容无效')
  }
  const serialized = stringifyJsonValueIterative(document, 2)
  if (typeof serialized !== 'string') throw new Error('脑图备份内容无法序列化')
  return serialized
}

export function downloadMindmapBackup(document, options = {}) {
  let objectUrl = ''
  try {
    if (
      typeof Blob === 'undefined'
      || typeof URL === 'undefined'
      || typeof URL.createObjectURL !== 'function'
      || typeof globalThis.document === 'undefined'
    ) return false
    const serialized = serializeMindmapBackup(document)
    const blob = new Blob([serialized], { type: 'application/json;charset=utf-8' })
    objectUrl = URL.createObjectURL(blob)
    const link = globalThis.document.createElement('a')
    link.href = objectUrl
    link.download = createMindmapBackupFileName(options)
    link.hidden = true
    globalThis.document.body.appendChild(link)
    link.click()
    link.remove()
    // Safari/Firefox 可能在 click 返回后才读取 Blob，不能立即撤销。
    setTimeout(() => URL.revokeObjectURL?.(objectUrl), 1000)
    return true
  } catch {
    if (objectUrl) URL.revokeObjectURL?.(objectUrl)
    return false
  }
}
