import { assertMindmapImportDocument } from './mindmap-import-validation.js'
import { isRecord, stableJsonValue } from './mindmap-ai-shared.js'

export const MINDMAP_AI_FORMAT = 'ruoyi-mindmap'
export const MINDMAP_AI_SCHEMA_VERSION = 2
const MINDMAP_AI_HASH_PREFIX = 'mmf2:sha256:'
export const MINDMAP_AI_MAX_NODES = 2000
export const MINDMAP_AI_MAX_DEPTH = 32
const MINDMAP_AI_MAX_FILE_BYTES = 2_000_000

const TRANSIENT_KEYS = new Set([
  'isActive',
  'inserting',
  'needUpdate',
  'resetRichText',
  'activeStyle',
])
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g
const HTML_PATTERN = /<[^>]*>/g
const BLANK_SOURCE_NODE_TEXT = '未命名节点'

function artifactError(message, code = 'AI_ARTIFACT_INVALID') {
  const error = new Error(message)
  error.code = code
  return error
}

function cleanSourceText(value, label, maxLength, { allowBlank = false } = {}) {
  if (typeof value !== 'string') {
    if (allowBlank && (value === null || value === undefined)) return BLANK_SOURCE_NODE_TEXT
    throw artifactError(`${label}必须是字符串`)
  }
  const controlledText = value.replace(CONTROL_CHARACTER_PATTERN, '').trim()
  if (!controlledText) {
    if (allowBlank) return BLANK_SOURCE_NODE_TEXT
    throw artifactError(`${label}不能为空`)
  }
  if (controlledText.length > maxLength) throw artifactError(`${label}长度超出限制`)
  const text = controlledText.replace(HTML_PATTERN, '').trim()
  if (!text) {
    if (allowBlank) return BLANK_SOURCE_NODE_TEXT
    throw artifactError(`${label}不能为空`)
  }
  return text
}

export function canonicalMindmapJson(value) {
  return JSON.stringify(stableJsonValue(value))
}

function bytesToHex(bytes) {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

export async function computeMindmapDocumentHash(document) {
  if (!globalThis.crypto?.subtle) {
    throw artifactError('当前浏览器不支持安全哈希校验', 'AI_HASH_UNAVAILABLE')
  }
  const bytes = new TextEncoder().encode(canonicalMindmapJson(document))
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  return `${MINDMAP_AI_HASH_PREFIX}${bytesToHex(new Uint8Array(digest))}`
}

export function normalizeMindmapAiSourceSnapshot(document) {
  if (!isRecord(document) || !isRecord(document.root)) {
    throw artifactError('当前脑图不是有效文档')
  }
  const normalized = JSON.parse(JSON.stringify({
    root: document.root,
    layout: document.layout || 'logicalStructure',
    theme: isRecord(document.theme) ? document.theme : { template: 'default', config: {} },
    view: null,
    documentData: isRecord(document.documentData) ? document.documentData : {},
  }))
  // Command.getCopyData injects the currently bundled renderer version every
  // time it exports a runtime tree. It is transport metadata, not editable
  // mind-map content; excluding it keeps a validated artifact hash stable when
  // that artifact is loaded by a newer/older renderer and exported again.
  delete normalized.root.smmVersion
  const pending = [normalized.root]
  while (pending.length > 0) {
    const node = pending.pop()
    if (!isRecord(node?.data)) throw artifactError('脑图节点 data 必须是对象')
    for (const key of Object.keys(node.data)) {
      if (TRANSIENT_KEYS.has(key) || key.toLowerCase().startsWith('on')) delete node.data[key]
    }
    node.data.text = cleanSourceText(node.data.text, '脑图节点文本', 10_000, {
      allowBlank: true,
    })
    if (node.data.note !== undefined && node.data.note !== null) {
      const note = typeof node.data.note === 'string'
        ? node.data.note.replace(CONTROL_CHARACTER_PATTERN, '').trim()
          .replace(HTML_PATTERN, '').trim()
        : null
      if (note === '') delete node.data.note
      else node.data.note = cleanSourceText(node.data.note, '脑图节点备注', 20_000)
    }
    if (typeof node.data.hyperlink === 'string') {
      node.data.hyperlink = node.data.hyperlink.trim()
      if (!node.data.hyperlink) delete node.data.hyperlink
    }
    const children = node.children || []
    if (!Array.isArray(children)) throw artifactError('脑图节点 children 必须是数组')
    node.children = children
    pending.push(...children)
  }
  assertMindmapImportDocument(normalized, {
    maxNodeCount: MINDMAP_AI_MAX_NODES,
    maxDepth: MINDMAP_AI_MAX_DEPTH,
  })
  return normalized
}

export async function computeMindmapSnapshotFingerprint(document) {
  return computeMindmapDocumentHash(normalizeMindmapAiSourceSnapshot(document))
}

/**
 * Recompute the complete editable-document fingerprint after a browser-local
 * AI undo. The source fingerprint intentionally normalizes view state to null,
 * but still covers root, layout, theme and documentData exactly like the
 * server-side proposal baseline.
 */
export async function assertMindmapAiLocalUndoBaseline(document, expectedHash) {
  if (
    typeof expectedHash !== 'string'
    || !/^mmf2:sha256:[a-f0-9]{64}$/.test(expectedHash)
  ) {
    throw artifactError('本地 AI 撤销基线哈希无效', 'AI_LOCAL_UNDO_BASELINE_INVALID')
  }
  const actualHash = await computeMindmapSnapshotFingerprint(document)
  if (actualHash !== expectedHash) {
    throw artifactError(
      '撤销后的完整脑图与 AI 提案基线不一致，已恢复 AI 应用结果',
      'AI_LOCAL_UNDO_BASELINE_MISMATCH',
    )
  }
  return actualHash
}

export async function buildMindmapAiArtifactFromDocument(document, {
  title = '导入的脑图',
  sourceType = 'local_import',
} = {}) {
  const normalized = normalizeMindmapAiSourceSnapshot(document)
  const documentHash = await computeMindmapDocumentHash(normalized)
  const artifactId = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  const artifact = {
    format: MINDMAP_AI_FORMAT,
    formatSchemaVersion: MINDMAP_AI_SCHEMA_VERSION,
    manifest: {
      artifactId,
      title: String(title || '导入的脑图').trim().slice(0, 200) || '导入的脑图',
      sourceType,
      createdAt: new Date().toISOString(),
      generator: {
        agentKey: 'browser_import',
        adapterVersion: '1.0.0',
        promptVersion: 'local-file-v1',
      },
      validation: {
        status: 'passed',
        validatorVersion: 'browser-import-1',
      },
      documentHash,
    },
    document: normalized,
  }
  await assertMindmapAiArtifact(artifact)
  return artifact
}

export async function assertMindmapAiArtifact(artifact, { requirePassed = true } = {}) {
  if (!isRecord(artifact)) throw artifactError('AI 脑图文件必须是对象')
  if (artifact.format !== MINDMAP_AI_FORMAT) throw artifactError('AI 脑图文件格式无效')
  if (artifact.formatSchemaVersion !== MINDMAP_AI_SCHEMA_VERSION) {
    throw artifactError('不支持的 AI 脑图文件版本')
  }
  if (!isRecord(artifact.manifest) || !isRecord(artifact.document)) {
    throw artifactError('AI 脑图文件缺少 manifest 或 document')
  }
  const status = artifact.manifest.validation?.status
  if (!['passed', 'draft'].includes(status)) throw artifactError('AI 脑图校验状态无效')
  if (requirePassed && status !== 'passed') throw artifactError('未通过校验的 AI 脑图不能应用')
  assertMindmapImportDocument(artifact.document, {
    maxNodeCount: MINDMAP_AI_MAX_NODES,
    maxDepth: MINDMAP_AI_MAX_DEPTH,
  })
  const byteLength = new TextEncoder().encode(JSON.stringify(artifact)).byteLength
  if (byteLength > MINDMAP_AI_MAX_FILE_BYTES) throw artifactError('AI 脑图文件不能超过 2MB')
  const documentHash = await computeMindmapDocumentHash(artifact.document)
  if (documentHash !== artifact.manifest.documentHash) {
    throw artifactError('AI 脑图文件内容哈希不匹配')
  }
  return {
    artifact,
    document: artifact.document,
    documentHash,
  }
}

export function createMindmapAiIdempotencyKey(prefix = 'mindmap-ai') {
  const id = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  return `${prefix}:${id}`
}

export function cloneMindmapBranchWithFreshUids(root) {
  if (!isRecord(root)) throw artifactError('待插入的脑图分支无效')
  const cloned = JSON.parse(JSON.stringify(root))
  const uidMap = new Map()
  const nodes = [cloned]
  while (nodes.length > 0) {
    const node = nodes.pop()
    if (!isRecord(node?.data)) throw artifactError('脑图节点 data 必须是对象')
    const oldUid = typeof node.data.uid === 'string' ? node.data.uid : ''
    const newUid = globalThis.crypto?.randomUUID?.()
      || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
    if (oldUid) uidMap.set(oldUid, newUid)
    node.data.uid = newUid
    nodes.push(...(Array.isArray(node.children) ? node.children : []))
  }
  const rewriteReferences = (value, parentKey = '') => {
    if (Array.isArray(value)) return value.map(item => rewriteReferences(item, parentKey))
    if (!isRecord(value)) {
      if (
        typeof value === 'string'
        && uidMap.has(value)
        && /(uid|id|node|source|target|relation|summary|group)/i.test(parentKey)
      ) return uidMap.get(value)
      return value
    }
    for (const [key, item] of Object.entries(value)) {
      if (key === 'uid') continue
      value[key] = rewriteReferences(item, key)
    }
    return value
  }
  return rewriteReferences(cloned)
}
