import {
  canonicalMindmapJson,
  computeMindmapDocumentHash,
  normalizeMindmapAiSourceSnapshot,
} from './mindmap-ai-artifact.js'
import { isRecord } from './mindmap-ai-shared.js'

const MAX_PROPOSAL_OPERATIONS = 10_000
const MAX_UID_LENGTH = 128
const OPERATION_TYPES = new Set([
  'create_node',
  'update_node',
  'move_node',
  'delete_subtree',
  'set_document_meta',
])
const MUTABLE_NODE_FIELDS = new Set([
  'text',
  'note',
  'hyperlink',
  'tag',
  'expand',
])
const DOCUMENT_META_FIELDS = new Set(['layout', 'theme', 'documentData'])
const FORBIDDEN_OBJECT_KEYS = new Set(['__proto__', 'prototype', 'constructor'])

function proposalError(message) {
  const error = new Error(message)
  error.code = 'AI_PROPOSAL_INVALID'
  return error
}

function cloneJson(value, label = '提案数据') {
  try {
    const encoded = JSON.stringify(value)
    if (encoded === undefined) throw new TypeError('undefined')
    return JSON.parse(encoded)
  } catch {
    throw proposalError(`${label}不是有效 JSON`)
  }
}

function assertExactKeys(value, allowed, label) {
  if (!isRecord(value)) throw proposalError(`${label}必须是对象`)
  const keys = Object.keys(value)
  if (keys.some(key => !allowed.has(key))) throw proposalError(`${label}包含未知字段`)
  if ([...allowed].some(key => !Object.prototype.hasOwnProperty.call(value, key))) {
    throw proposalError(`${label}缺少必填字段`)
  }
}

function assertUid(value, label) {
  if (
    typeof value !== 'string'
    || value.length < 1
    || value.length > MAX_UID_LENGTH
    || /[\u0000-\u001f\u007f]/.test(value)
  ) throw proposalError(`${label}无效`)
  return value
}

function assertJsonRecord(value, label) {
  if (!isRecord(value)) throw proposalError(`${label}必须是对象`)
  if (Object.keys(value).some(key => FORBIDDEN_OBJECT_KEYS.has(key))) {
    throw proposalError(`${label}包含危险字段`)
  }
}

function indexDocument(document) {
  if (!isRecord(document) || !isRecord(document.root)) {
    throw proposalError('提案基线不是有效脑图文档')
  }
  const nodes = new Map()
  const parents = new Map()
  const pending = [{ node: document.root, parentUid: null }]
  while (pending.length) {
    const { node, parentUid } = pending.pop()
    if (!isRecord(node) || !isRecord(node.data)) {
      throw proposalError('提案基线节点结构无效')
    }
    const uid = assertUid(node.data.uid, '节点 UID')
    if (nodes.has(uid)) throw proposalError(`脑图包含重复节点 UID: ${uid}`)
    if (!Array.isArray(node.children)) throw proposalError(`节点 children 必须是数组: ${uid}`)
    nodes.set(uid, node)
    parents.set(uid, parentUid)
    for (let index = node.children.length - 1; index >= 0; index -= 1) {
      pending.push({ node: node.children[index], parentUid: uid })
    }
  }
  return { nodes, parents, rootUid: String(document.root.data.uid) }
}

function assertFieldChanges(payload, allowedFields, label) {
  assertExactKeys(payload, new Set(['set', 'unset']), label)
  assertJsonRecord(payload.set, `${label}.set`)
  if (!Array.isArray(payload.unset)) throw proposalError(`${label}.unset 必须是数组`)
  const unset = new Set()
  for (const field of payload.unset) {
    if (typeof field !== 'string' || !allowedFields.has(field)) {
      throw proposalError(`${label}.unset 包含无效字段`)
    }
    if (unset.has(field)) throw proposalError(`${label}.unset 包含重复字段`)
    unset.add(field)
  }
  for (const field of Object.keys(payload.set)) {
    if (!allowedFields.has(field)) throw proposalError(`${label}.set 包含无效字段`)
    if (unset.has(field)) throw proposalError(`${label}不能同时设置并删除同一字段`)
  }
  if (Object.keys(payload.set).length === 0 && unset.size === 0) {
    throw proposalError(`${label}不能为空`)
  }
}

function applyCreate(document, operation) {
  assertUid(operation.nodeUid, '新增节点 UID')
  assertExactKeys(
    operation.payload,
    new Set(['parentUid', 'index', 'data']),
    'create_node.payload',
  )
  const { nodes } = indexDocument(document)
  const parentUid = assertUid(operation.payload.parentUid, '新增节点父 UID')
  const parent = nodes.get(parentUid)
  if (!parent) throw proposalError(`新增节点的父节点不存在: ${parentUid}`)
  if (nodes.has(operation.nodeUid)) throw proposalError(`新增节点 UID 已存在: ${operation.nodeUid}`)
  if (
    !Number.isSafeInteger(operation.payload.index)
    || operation.payload.index < 0
    || operation.payload.index > parent.children.length
  ) throw proposalError('新增节点位置越界')
  assertJsonRecord(operation.payload.data, 'create_node.payload.data')
  if (operation.payload.data.uid !== operation.nodeUid) {
    throw proposalError('新增节点 data.uid 与 nodeUid 不一致')
  }
  for (const field of Object.keys(operation.payload.data)) {
    if (field !== 'uid' && !MUTABLE_NODE_FIELDS.has(field)) {
      throw proposalError(`新增节点包含不允许的字段: ${field}`)
    }
  }
  parent.children.splice(operation.payload.index, 0, {
    data: cloneJson(operation.payload.data, '新增节点数据'),
    children: [],
  })
}

function applyUpdate(document, operation) {
  const uid = assertUid(operation.nodeUid, '更新节点 UID')
  const { nodes } = indexDocument(document)
  const node = nodes.get(uid)
  if (!node) throw proposalError(`更新节点不存在: ${uid}`)
  assertFieldChanges(operation.payload, MUTABLE_NODE_FIELDS, 'update_node.payload')
  for (const [field, value] of Object.entries(operation.payload.set)) {
    node.data[field] = cloneJson(value, `节点字段 ${field}`)
  }
  for (const field of operation.payload.unset) delete node.data[field]
}

function detachNode(indexed, uid) {
  const parentUid = indexed.parents.get(uid)
  if (parentUid === null || parentUid === undefined) {
    throw proposalError('不能移动或删除脑图根节点')
  }
  const parent = indexed.nodes.get(parentUid)
  const index = parent.children.findIndex(child => child?.data?.uid === uid)
  if (index < 0) throw proposalError(`节点父子关系损坏: ${uid}`)
  return parent.children.splice(index, 1)[0]
}

function applyMove(document, operation) {
  const uid = assertUid(operation.nodeUid, '移动节点 UID')
  assertExactKeys(operation.payload, new Set(['parentUid', 'index']), 'move_node.payload')
  const parentUid = assertUid(operation.payload.parentUid, '移动节点父 UID')
  const before = indexDocument(document)
  if (uid === before.rootUid) throw proposalError('不能移动脑图根节点')
  if (!before.nodes.has(uid)) throw proposalError(`移动节点不存在: ${uid}`)
  const targetParent = before.nodes.get(parentUid)
  if (!targetParent) throw proposalError(`移动目标父节点不存在: ${parentUid}`)
  let ancestorUid = parentUid
  while (ancestorUid !== null) {
    if (ancestorUid === uid) throw proposalError('移动节点不能形成循环')
    ancestorUid = before.parents.get(ancestorUid) ?? null
  }
  // 位置基于节点从原父节点移除后的目标 children 数组。
  const targetChildCount = targetParent.children.length - Number(before.parents.get(uid) === parentUid)
  if (
    !Number.isSafeInteger(operation.payload.index)
    || operation.payload.index < 0
    || operation.payload.index > targetChildCount
  ) throw proposalError('移动节点位置越界')
  targetParent.children.splice(operation.payload.index, 0, detachNode(before, uid))
}

function applyDelete(document, operation) {
  const uid = assertUid(operation.nodeUid, '删除节点 UID')
  if (operation.payload !== null) throw proposalError('delete_subtree.payload 必须为 null')
  const indexed = indexDocument(document)
  if (uid === indexed.rootUid) throw proposalError('不能删除脑图根节点')
  if (!indexed.nodes.has(uid)) throw proposalError(`删除节点不存在: ${uid}`)
  detachNode(indexed, uid)
}

function applyDocumentMeta(document, operation) {
  if (operation.nodeUid !== null) throw proposalError('set_document_meta.nodeUid 必须为 null')
  assertFieldChanges(operation.payload, DOCUMENT_META_FIELDS, 'set_document_meta.payload')
  for (const [field, value] of Object.entries(operation.payload.set)) {
    document[field] = cloneJson(value, `文档字段 ${field}`)
  }
  for (const field of operation.payload.unset) delete document[field]
}

function applyOperation(document, operation) {
  assertExactKeys(operation, new Set(['type', 'nodeUid', 'payload']), '提案操作')
  if (!OPERATION_TYPES.has(operation.type)) throw proposalError('提案包含未知操作类型')
  if (operation.type === 'create_node') return applyCreate(document, operation)
  if (operation.type === 'update_node') return applyUpdate(document, operation)
  if (operation.type === 'move_node') return applyMove(document, operation)
  if (operation.type === 'delete_subtree') return applyDelete(document, operation)
  return applyDocumentMeta(document, operation)
}

/**
 * 在独立 JSON 克隆上严格、按序重放服务端提案。任何一步失败都只抛错，
 * 调用方传入的画布基线保持不变。
 */
export function strictApplyMindmapAiProposal(baseDocument, operations) {
  if (!Array.isArray(operations) || operations.length > MAX_PROPOSAL_OPERATIONS) {
    throw proposalError('提案操作列表无效或过大')
  }
  const candidate = cloneJson(baseDocument, '提案基线')
  indexDocument(candidate)
  for (const operation of operations) applyOperation(candidate, operation)
  indexDocument(candidate)
  return candidate
}

export function mindmapAiDocumentsEqual(left, right) {
  try {
    return canonicalMindmapJson(left) === canonicalMindmapJson(right)
  } catch {
    return false
  }
}

/**
 * 浏览器本地应用的最终提交门禁。只有基线、严格 operations 重放结果、
 * proposal 结果哈希和 artifact 内容四者形成同一条可验证链时才返回文档。
 */
export async function verifyMindmapAiLocalProposal({
  baseDocument,
  operations,
  baseHash,
  resultHash,
  artifactDocument,
  artifactHash,
}) {
  const normalizedBase = normalizeMindmapAiSourceSnapshot(baseDocument)
  const actualBaseHash = await computeMindmapDocumentHash(normalizedBase)
  if (actualBaseHash !== baseHash) throw proposalError('提案基线哈希不匹配')

  const shadow = strictApplyMindmapAiProposal(normalizedBase, operations)
  const normalizedShadow = normalizeMindmapAiSourceSnapshot(shadow)
  if (!mindmapAiDocumentsEqual(shadow, normalizedShadow)) {
    throw proposalError('提案操作重放结果不是规范脑图文档')
  }
  const shadowHash = await computeMindmapDocumentHash(shadow)
  if (
    typeof resultHash !== 'string'
    || resultHash !== shadowHash
    || artifactHash !== shadowHash
  ) throw proposalError('提案、操作重放与 AI 文件哈希不一致')
  if (!mindmapAiDocumentsEqual(shadow, artifactDocument)) {
    throw proposalError('提案操作重放结果与 AI 文件内容不一致')
  }
  // 安全门禁继续使用去 HTML 的规范投影；真正写回编辑器时，把同一组已
  // 验证 operations 重放到原始基线上，保留未修改节点的富文本字节、运行
  // 时字段和 view。重放结果重新投影后必须仍等于签名 Artifact。
  const editorDocument = strictApplyMindmapAiProposal(baseDocument, operations)
  const normalizedEditorDocument = normalizeMindmapAiSourceSnapshot(editorDocument)
  if (!mindmapAiDocumentsEqual(normalizedEditorDocument, shadow)) {
    throw proposalError('提案编辑器重放结果与 AI 文件内容不一致')
  }
  return {
    baseDocument: normalizedBase,
    baseHash: actualBaseHash,
    document: editorDocument,
    resultHash: shadowHash,
  }
}
