import { copyMindmapText } from './mindmap-clipboard.js'

export function resolveMindmapShareStatus(link, now = Date.now()) {
  if (!link?.isActive) {
    return { key: 'disabled', label: '已禁用', tagType: 'info', usable: false }
  }
  if (!link.expireTime) {
    return { key: 'active', label: '有效', tagType: 'success', usable: true }
  }
  const expiresAt = Date.parse(link.expireTime)
  if (!Number.isFinite(expiresAt)) {
    return { key: 'invalid', label: '时间异常', tagType: 'danger', usable: false }
  }
  if (expiresAt <= now) {
    return { key: 'expired', label: '已过期', tagType: 'warning', usable: false }
  }
  return { key: 'active', label: '有效', tagType: 'success', usable: true }
}

export function isFutureMindmapShareExpiry(value, now = Date.now()) {
  if (!value) return false
  const expiresAt = value instanceof Date ? value.getTime() : Date.parse(value)
  return Number.isFinite(expiresAt) && expiresAt > now
}

export async function copyMindmapShareText(
  text,
  {
    clipboard = globalThis.navigator?.clipboard,
    documentRef = globalThis.document,
  } = {},
) {
  const value = String(text ?? '')
  if (!value) throw new Error('没有可复制的分享链接')
  return copyMindmapText(value, { clipboard, documentRef })
}
