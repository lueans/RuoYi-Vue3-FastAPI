import { assertMindmapImportDocument } from './mindmap-import-validation.js'
import { validateMindmapTagStyle } from './mindmap-tag-governance.js'
import {
  MAX_MINDMAP_AI_ATTACHMENT_CHARS,
  MINDMAP_AI_TEMPLATE_MEDIA_TYPE,
  validateMindmapAiAttachments,
} from './mindmap-ai-attachments.js'

function readableText(value, richText = false) {
  if (typeof value !== 'string') return ''
  if (!richText) return value.trim()
  return value
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/giu, '')
    .replace(/<br\s*\/?\s*>|<\/(?:p|div|li|h[1-6])\s*>/giu, '\n')
    .replace(/<[^>]*>/gu, '')
    .replace(/&(#x[\da-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/giu, (entity, code) => {
      if (code.startsWith('#')) {
        const point = code[1].toLowerCase() === 'x' ? parseInt(code.slice(2), 16) : Number(code.slice(1))
        return point > 0 && point <= 0x10ffff ? String.fromCodePoint(point) : entity
      }
      return { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }[code.toLowerCase()]
    }).trim()
}

function templateTags(tags) {
  if (!Array.isArray(tags)) return []
  return tags.flatMap(tag => {
    if (typeof tag === 'string') return tag.trim() ? [{ text: tag.trim() }] : []
    if (!tag || typeof tag !== 'object' || Array.isArray(tag)) return []
    const snapshot = {}
    if (Number.isSafeInteger(tag.tagId) && tag.tagId > 0) snapshot.tagId = tag.tagId
    for (const key of ['tagKey', 'text']) {
      if (typeof tag[key] === 'string' && tag[key].trim()) snapshot[key] = tag[key].trim()
    }
    if (!snapshot.tagId && !snapshot.tagKey && !snapshot.text) return []
    const style = validateMindmapTagStyle(tag.style)
    if (!style.valid) throw new Error(`模版中的标签样式无效：${style.message}`)
    if (style.value) snapshot.style = style.value
    // These are visible node-local choices, separate from the definition's
    // defaults. They remain reference data, never tool-call authority.
    if (['left', 'right', 'top', 'bottom'].includes(tag.placement)) snapshot.placement = tag.placement
    if (['left', 'right', 'top', 'bottom', 'center'].includes(tag.align)) snapshot.align = tag.align
    return [snapshot]
  })
}

// The dedicated template detail endpoint checks both read access and folder
// membership. Text/notes describe example node roles, not a content checklist.
// Freeze this format reference for the turn; never open it on the canvas.
export async function createMindmapAiTemplateAttachment(mindmap) {
  const sourceId = String(mindmap?.id ?? '')
  const revision = String(mindmap?.contentRevision ?? '')
  if (!/^[1-9]\d{0,19}$/.test(sourceId) || !/^\d{1,20}$/.test(revision)
    || !Number.isSafeInteger(Number(sourceId)) || !Number.isSafeInteger(Number(revision))) {
    throw new Error('模版脑图信息不完整，请刷新后重新选择')
  }
  const { root } = assertMindmapImportDocument(mindmap.nodeTree)
  const lines = []
  const stack = [{ node: root, depth: 0 }]
  let characters = 0
  let templateDepth = 1
  while (stack.length) {
    const { node, depth } = stack.pop()
    templateDepth = Math.max(templateDepth, depth + 1)
    const indent = '  '.repeat(depth)
    const title = readableText(node.data?.text, node.data?.richText)
    const note = readableText(node.data?.note, /<\/?(?:p|div|br|ul|ol|li|h[1-6]|strong|em|span|b|i|a|img|blockquote|pre|code|table|tr|td)\b/iu.test(node.data?.note || ''))
    const tags = templateTags(node.data?.tag)
    const line = `${indent}- 示例节点：${title.replaceAll('\n', `\n${indent}  `) || '（未填写示例）'}`
      + (note ? `\n${indent}  示例备注：${note.replaceAll('\n', `\n${indent}  `)}` : '')
      + (tags.length ? `\n${indent}  标签：${JSON.stringify(tags)}` : '')
    characters += line.length + (lines.length ? 1 : 0)
    if (characters > MAX_MINDMAP_AI_ATTACHMENT_CHARS) throw new Error('模版内容超过 50,000 字符，请简化脑图后重新选择')
    lines.push(line)
    for (let index = (node.children?.length || 0) - 1; index >= 0; index -= 1) {
      stack.push({ node: node.children[index], depth: depth + 1 })
    }
  }
  const text = lines.join('\n')
  const content = new TextEncoder().encode(text)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', content)
  const hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('').slice(0, 32)
  const attachment = {
    id: `template-map-${sourceId}-${revision}-${hash}`,
    name: mindmap.name,
    size: content.byteLength,
    mediaType: MINDMAP_AI_TEMPLATE_MEDIA_TYPE,
    text,
    purpose: 'template',
    templateSource: { mindmapId: Number(sourceId), contentRevision: Number(revision) },
    // Composer-only guidance; request capture deliberately omits this field.
    templateDepth,
  }
  validateMindmapAiAttachments([attachment])
  return attachment
}
