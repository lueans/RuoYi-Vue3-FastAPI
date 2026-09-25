import {
  normalizeMindmapLocalWorkspacePatch,
  normalizeMindmapLocalWorkspaceRecord,
  serializeMindmapLocalWorkspaceRecord,
} from './mindmap-local-workspace.js'
import {
  stringifyJsonValueIterative,
} from '../libs/simple-mind-map/src/utils/jsonClone.js'
import { isBoundedText, isNumericOwnerUserId, isPlainObject } from './mindmap-ai-shared.js'

export const MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY = 'MINDMAP_AI_LOCAL_JOURNAL_V1'
const MINDMAP_AI_LOCAL_JOURNAL_SCHEMA_VERSION = 1
export const MINDMAP_AI_LOCAL_JOURNAL_DEFAULT_TTL_MS = 7 * 24 * 60 * 60 * 1000
const HASH_PATTERN = /^mmf2:sha256:[a-f0-9]{64}$/
const MAX_ENTRY_COUNT = 20
const MAX_JOURNAL_BYTES = 3 * 1024 * 1024
const MAX_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
const MAX_CLOCK_SKEW_MS = 5 * 60 * 1000
const NEXT_PHASES = Object.freeze({
  prepared: new Set(['applied_ack_pending', 'done']),
  applied_ack_pending: new Set(['applied_ack_confirmed', 'done']),
  applied_ack_confirmed: new Set(['undone_ack_pending', 'done']),
  undone_ack_pending: new Set(['done']),
  done: new Set(),
})
export const MINDMAP_AI_LOCAL_JOURNAL_PHASES = Object.freeze(Object.keys(NEXT_PHASES))
const PHASES = new Set(MINDMAP_AI_LOCAL_JOURNAL_PHASES)

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key)

function normalizeOwnerUserId(value) {
  if (Number.isSafeInteger(value) && value > 0) return String(value)
  return isNumericOwnerUserId(value) ? value : null
}

function createJournalError(message, code, ErrorType = Error, cause) {
  const error = cause === undefined
    ? new ErrorType(message)
    : new ErrorType(message, { cause })
  error.code = code
  return error
}

function requireStorage(storage) {
  if (
    !storage
    || typeof storage.getItem !== 'function'
    || typeof storage.setItem !== 'function'
  ) {
    throw createJournalError(
      'AI 本地事务日志存储不可用',
      'AI_LOCAL_JOURNAL_STORAGE_UNAVAILABLE',
    )
  }
  return storage
}

function resolveNow(options) {
  const now = options?.now === undefined ? Date.now() : Number(options.now)
  if (!Number.isSafeInteger(now) || now < 1) {
    throw createJournalError(
      'AI 本地事务日志时间无效',
      'AI_LOCAL_JOURNAL_TIME_INVALID',
      TypeError,
    )
  }
  return now
}

function getUtf8ByteLength(value) {
  if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(value).byteLength
  return encodeURIComponent(value).replace(/%[0-9A-F]{2}|./g, 'x').length
}

function cloneJsonValue(value) {
  return JSON.parse(stringifyJsonValueIterative(value))
}

function normalizeIdentity(value) {
  if (!isPlainObject(value)) return null
  const ownerUserId = normalizeOwnerUserId(value.ownerUserId)
  if (
    !ownerUserId
    || !isBoundedText(value.documentId, 128)
    || !isBoundedText(value.proposalId, 64)
  ) return null
  return {
    ownerUserId,
    documentId: value.documentId,
    proposalId: value.proposalId,
  }
}

function requireIdentity(value) {
  const identity = normalizeIdentity(value)
  if (!identity) {
    throw createJournalError(
      'AI 本地事务日志标识无效',
      'AI_LOCAL_JOURNAL_IDENTITY_INVALID',
      TypeError,
    )
  }
  return identity
}

function sameIdentity(left, right) {
  return left.ownerUserId === right.ownerUserId
    && left.documentId === right.documentId
    && left.proposalId === right.proposalId
}

function sameDocumentPartition(left, right) {
  return left.ownerUserId === right.ownerUserId
    && left.documentId === right.documentId
}

function normalizeWorkspace(value, { strict = false } = {}) {
  let normalized
  if (isPlainObject(value) && hasOwn(value, 'schemaVersion')) {
    normalized = normalizeMindmapLocalWorkspaceRecord(value)
    if (!normalized && strict) throw new TypeError('本地工作区记录无效')
  } else {
    normalized = strict
      ? normalizeMindmapLocalWorkspacePatch(value)
      : normalizeMindmapLocalWorkspaceRecord(value)
  }
  if (!normalized?.root) {
    if (strict) throw new TypeError('本地工作区缺少脑图正文')
    return null
  }
  return normalized
}

function normalizeBeforeWorkspace(value, identity, baseRevision, baseHash) {
  let workspace
  try {
    workspace = normalizeWorkspace(value, { strict: true })
  } catch (error) {
    throw createJournalError(
      'AI 本地事务日志的应用前工作区无效',
      'AI_LOCAL_JOURNAL_BASE_INVALID',
      TypeError,
      error,
    )
  }
  if (
    workspace.documentId !== identity.documentId
    || Number(workspace.revision) !== baseRevision
    || workspace.documentHash !== baseHash
  ) {
    throw createJournalError(
      'AI 本地事务日志的应用前工作区身份不一致',
      'AI_LOCAL_JOURNAL_BASE_MISMATCH',
      TypeError,
    )
  }
  // Reuse the canonical workspace serializer so the durable undo baseline is
  // subject to the same schema, JSON safety and 2 MB boundary as MIND_MAP_DATA.
  return JSON.parse(serializeMindmapLocalWorkspaceRecord(workspace))
}

function normalizePersistedEntry(value, now) {
  if (!isPlainObject(value) || value.schemaVersion !== MINDMAP_AI_LOCAL_JOURNAL_SCHEMA_VERSION) {
    return null
  }
  const identity = normalizeIdentity(value)
  const baseRevision = Number(value.baseRevision)
  const appliedRevision = Number(value.appliedRevision)
  const createdAt = Number(value.createdAt)
  const updatedAt = Number(value.updatedAt)
  const expiresAt = Number(value.expiresAt)
  if (
    !identity
    || !PHASES.has(value.phase)
    || !Number.isSafeInteger(baseRevision)
    || baseRevision < 1
    || appliedRevision !== baseRevision + 1
    || !HASH_PATTERN.test(value.baseHash || '')
    || !HASH_PATTERN.test(value.resultHash || '')
    || value.baseHash === value.resultHash
    || !Number.isSafeInteger(createdAt)
    || createdAt < 1
    || createdAt > now + MAX_CLOCK_SKEW_MS
    || !Number.isSafeInteger(updatedAt)
    || updatedAt < createdAt
    || updatedAt > now + MAX_CLOCK_SKEW_MS
    || !Number.isSafeInteger(expiresAt)
    || expiresAt <= createdAt
    || expiresAt - createdAt > MAX_RETENTION_MS
    || updatedAt >= expiresAt
  ) return null

  let beforeWorkspace
  try {
    beforeWorkspace = normalizeBeforeWorkspace(
      value.beforeWorkspace,
      identity,
      baseRevision,
      value.baseHash,
    )
  } catch {
    return null
  }
  return {
    schemaVersion: MINDMAP_AI_LOCAL_JOURNAL_SCHEMA_VERSION,
    ...identity,
    phase: value.phase,
    beforeWorkspace,
    baseRevision,
    appliedRevision,
    baseHash: value.baseHash,
    resultHash: value.resultHash,
    createdAt,
    updatedAt,
    expiresAt,
  }
}

function readEntries(storage = globalThis.localStorage, options = {}) {
  const targetStorage = requireStorage(storage)
  const now = resolveNow(options)
  let raw
  try {
    raw = targetStorage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY)
  } catch (error) {
    throw createJournalError(
      'AI 本地事务日志无法读取',
      'AI_LOCAL_JOURNAL_STORAGE_UNAVAILABLE',
      Error,
      error,
    )
  }
  if (raw === null || raw === '') return []

  let envelope
  try {
    envelope = JSON.parse(raw)
  } catch (error) {
    throw createJournalError(
      'AI 本地事务日志已损坏',
      'AI_LOCAL_JOURNAL_CORRUPT',
      Error,
      error,
    )
  }
  if (
    !isPlainObject(envelope)
    || envelope.schemaVersion !== MINDMAP_AI_LOCAL_JOURNAL_SCHEMA_VERSION
    || !Array.isArray(envelope.entries)
    || envelope.entries.length > MAX_ENTRY_COUNT
  ) {
    throw createJournalError(
      'AI 本地事务日志格式无效',
      'AI_LOCAL_JOURNAL_CORRUPT',
    )
  }

  const entries = envelope.entries.map(entry => normalizePersistedEntry(entry, now))
  if (entries.some(entry => entry === null)) {
    throw createJournalError(
      'AI 本地事务日志包含无效记录',
      'AI_LOCAL_JOURNAL_CORRUPT',
    )
  }
  const identities = new Set()
  for (const entry of entries) {
    const key = `${entry.ownerUserId}\u0000${entry.documentId}\u0000${entry.proposalId}`
    if (identities.has(key)) {
      throw createJournalError(
        'AI 本地事务日志包含重复记录',
        'AI_LOCAL_JOURNAL_CORRUPT',
      )
    }
    identities.add(key)
  }
  return entries
}

function writeEntries(entries, storage = globalThis.localStorage) {
  const targetStorage = requireStorage(storage)
  if (!Array.isArray(entries) || entries.length > MAX_ENTRY_COUNT) {
    throw createJournalError(
      'AI 本地事务日志数量已达上限，未修改脑图',
      'AI_LOCAL_JOURNAL_CAPACITY_EXCEEDED',
    )
  }
  const envelope = {
    schemaVersion: MINDMAP_AI_LOCAL_JOURNAL_SCHEMA_VERSION,
    entries,
  }
  let serialized
  try {
    serialized = stringifyJsonValueIterative(envelope)
  } catch (error) {
    throw createJournalError(
      'AI 本地事务日志无法序列化',
      'AI_LOCAL_JOURNAL_SERIALIZE_FAILED',
      Error,
      error,
    )
  }
  if (getUtf8ByteLength(serialized) > MAX_JOURNAL_BYTES) {
    throw createJournalError(
      'AI 本地事务日志空间不足，未修改脑图',
      'AI_LOCAL_JOURNAL_TOO_LARGE',
    )
  }
  try {
    targetStorage.setItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY, serialized)
  } catch (error) {
    throw createJournalError(
      'AI 本地事务日志无法持久化，未修改脑图',
      'AI_LOCAL_JOURNAL_PERSIST_FAILED',
      Error,
      error,
    )
  }
}

function sameEntry(left, right) {
  return stringifyJsonValueIterative(left) === stringifyJsonValueIterative(right)
}

function sameTransactionContract(left, right) {
  return sameIdentity(left, right)
    && left.baseRevision === right.baseRevision
    && left.appliedRevision === right.appliedRevision
    && left.baseHash === right.baseHash
    && left.resultHash === right.resultHash
    && sameEntry(left.beforeWorkspace, right.beforeWorkspace)
}

function persistAndVerify(entries, expectedEntry, storage, options) {
  writeEntries(entries, storage)
  const persisted = readEntries(storage, options).find(entry => sameIdentity(entry, expectedEntry))
  if (!persisted || !sameEntry(persisted, expectedEntry)) {
    throw createJournalError(
      'AI 本地事务日志写入后校验失败，未修改脑图',
      'AI_LOCAL_JOURNAL_VERIFY_FAILED',
    )
  }
  return cloneJsonValue(persisted)
}

function persistRemovalAndVerify(entries, identity, storage, options) {
  writeEntries(entries, storage)
  if (readEntries(storage, options).some(entry => sameIdentity(entry, identity))) {
    throw createJournalError(
      'AI 本地事务日志删除后校验失败',
      'AI_LOCAL_JOURNAL_VERIFY_FAILED',
    )
  }
  return true
}

function isExpired(entry, now) {
  return now >= entry.expiresAt
}

/**
 * Persist the exact pre-apply workspace before the editor is allowed to change.
 * AI operations are deliberately not accepted or stored: crash recovery only
 * classifies the durable workspace and must never replay a proposal.
 */
export function prepareMindmapAiLocalJournal(
  input,
  storage = globalThis.localStorage,
  options = {},
) {
  const identity = requireIdentity(input)
  const now = resolveNow(options)
  const ttlMs = options.ttlMs === undefined
    ? MINDMAP_AI_LOCAL_JOURNAL_DEFAULT_TTL_MS
    : Number(options.ttlMs)
  const baseRevision = Number(input?.baseRevision)
  const appliedRevision = Number(input?.appliedRevision)
  if (
    !Number.isSafeInteger(baseRevision)
    || baseRevision < 1
    || appliedRevision !== baseRevision + 1
    || !HASH_PATTERN.test(input?.baseHash || '')
    || !HASH_PATTERN.test(input?.resultHash || '')
    || input.baseHash === input.resultHash
    || !Number.isSafeInteger(ttlMs)
    || ttlMs < 1
    || ttlMs > MAX_RETENTION_MS
  ) {
    throw createJournalError(
      'AI 本地事务日志参数无效',
      'AI_LOCAL_JOURNAL_INPUT_INVALID',
      TypeError,
    )
  }
  const beforeWorkspace = normalizeBeforeWorkspace(
    input.beforeWorkspace,
    identity,
    baseRevision,
    input.baseHash,
  )
  const entries = readEntries(storage, { now })
  const existing = entries.find(entry => sameIdentity(entry, identity))
  const normalizedBeforeWorkspace = normalizeMindmapLocalWorkspaceRecord(beforeWorkspace)
  const activeDocumentEntry = entries.find(entry => (
    sameDocumentPartition(entry, identity)
    && !sameIdentity(entry, identity)
    && entry.phase !== 'done'
    && !isExpired(entry, now)
    && !(
      entry.phase === 'applied_ack_confirmed'
      && baseRevision === entry.appliedRevision
      && input.baseHash === entry.resultHash
      && normalizedBeforeWorkspace?.lastAppliedProposal === entry.proposalId
    )
  ))
  if (activeDocumentEntry) {
    throw createJournalError(
      '当前本地脑图已有另一条未完成的 AI 事务日志',
      'AI_LOCAL_JOURNAL_CONFLICT',
    )
  }

  const freshEntry = {
    schemaVersion: MINDMAP_AI_LOCAL_JOURNAL_SCHEMA_VERSION,
    ...identity,
    phase: 'prepared',
    beforeWorkspace,
    baseRevision,
    appliedRevision,
    baseHash: input.baseHash,
    resultHash: input.resultHash,
    createdAt: now,
    updatedAt: now,
    expiresAt: now + ttlMs,
  }
  if (existing && !isExpired(existing, now)) {
    if (!sameTransactionContract(existing, freshEntry)) {
      throw createJournalError(
        'AI 本地事务日志与已保存事务不一致',
        'AI_LOCAL_JOURNAL_CONFLICT',
      )
    }
    return cloneJsonValue(existing)
  }

  const nextEntries = entries.filter(entry => (
    entry.ownerUserId !== identity.ownerUserId
    || (
      !isExpired(entry, now)
      && entry.phase !== 'done'
      && !sameIdentity(entry, identity)
    )
  ))
  nextEntries.push(freshEntry)
  return persistAndVerify(nextEntries, freshEntry, storage, { now })
}

export function getMindmapAiLocalJournal(
  identity,
  storage = globalThis.localStorage,
  options = {},
) {
  const normalized = requireIdentity(identity)
  const now = resolveNow(options)
  const entry = readEntries(storage, { now }).find(candidate => sameIdentity(candidate, normalized))
  return entry && !isExpired(entry, now) ? cloneJsonValue(entry) : null
}

export function listMindmapAiLocalJournals(
  ownerUserId,
  storage = globalThis.localStorage,
  options = {},
) {
  const owner = normalizeOwnerUserId(ownerUserId)
  if (!owner) return []
  const now = resolveNow(options)
  return readEntries(storage, { now })
    .filter(entry => entry.ownerUserId === owner && !isExpired(entry, now))
    .map(cloneJsonValue)
}

export function transitionMindmapAiLocalJournal(
  identity,
  nextPhase,
  storage = globalThis.localStorage,
  options = {},
) {
  const normalized = requireIdentity(identity)
  if (!PHASES.has(nextPhase)) {
    throw createJournalError(
      'AI 本地事务日志目标阶段无效',
      'AI_LOCAL_JOURNAL_PHASE_INVALID',
      TypeError,
    )
  }
  const now = resolveNow(options)
  const entries = readEntries(storage, { now })
  const index = entries.findIndex(entry => sameIdentity(entry, normalized))
  if (index < 0) return null
  const current = entries[index]
  if (isExpired(current, now)) {
    throw createJournalError(
      'AI 本地事务日志已经过期',
      'AI_LOCAL_JOURNAL_EXPIRED',
    )
  }
  if (current.phase === nextPhase) return cloneJsonValue(current)
  if (!NEXT_PHASES[current.phase]?.has(nextPhase)) {
    throw createJournalError(
      `AI 本地事务日志不能从 ${current.phase} 进入 ${nextPhase}`,
      'AI_LOCAL_JOURNAL_PHASE_CONFLICT',
    )
  }
  const expectedPhase = options.expectedPhase
  if (expectedPhase !== undefined && current.phase !== expectedPhase) {
    throw createJournalError(
      'AI 本地事务日志阶段已经变化',
      'AI_LOCAL_JOURNAL_PHASE_CONFLICT',
    )
  }
  const updated = {
    ...current,
    phase: nextPhase,
    updatedAt: Math.max(now, current.updatedAt),
  }
  entries[index] = updated
  return persistAndVerify(entries, updated, storage, { now: updated.updatedAt })
}

export function removeMindmapAiLocalJournal(
  identity,
  storage = globalThis.localStorage,
  options = {},
) {
  const normalized = requireIdentity(identity)
  const now = resolveNow(options)
  const entries = readEntries(storage, { now })
  if (!entries.some(entry => sameIdentity(entry, normalized))) return false
  return persistRemovalAndVerify(
    entries.filter(entry => !sameIdentity(entry, normalized)),
    normalized,
    storage,
    { now },
  )
}

function recoveryResult(classification, reason, entry, extra = {}) {
  return {
    classification,
    reason,
    actionable: classification === 'applied' || classification === 'undone',
    requiredAcks: [],
    ackPlan: [],
    undoAvailable: false,
    entry: entry ? cloneJsonValue(entry) : null,
    ...extra,
  }
}

function createAckPlan(entry, actions) {
  return actions.map(action => ({
    ownerUserId: entry.ownerUserId,
    action,
    proposalId: entry.proposalId,
    documentId: entry.documentId,
    revision: action === 'apply' ? entry.appliedRevision : entry.appliedRevision + 1,
    resultHash: entry.resultHash,
    ...(action === 'undo' ? { revertedHash: entry.baseHash } : {}),
  }))
}

/**
 * Classify durable state only. This function never mutates storage/workspace and
 * never receives or evaluates proposal operations, so callers cannot
 * accidentally replay an AI change during crash recovery.
 */
export function classifyMindmapAiLocalRecovery(entry, workspace, options = {}) {
  const now = resolveNow(options)
  const normalizedEntry = normalizePersistedEntry(entry, now)
  if (!normalizedEntry) {
    return recoveryResult('superseded', 'journal_invalid', null)
  }
  if (isExpired(normalizedEntry, now)) {
    return recoveryResult('superseded', 'journal_expired', null)
  }
  if (options.identity) {
    const identity = normalizeIdentity(options.identity)
    if (!identity || !sameIdentity(normalizedEntry, identity)) {
      return recoveryResult('superseded', 'identity_mismatch', null)
    }
  }

  let current
  try {
    current = normalizeWorkspace(workspace, { strict: true })
  } catch {
    return recoveryResult('superseded', 'workspace_invalid', normalizedEntry)
  }
  if (current.documentId !== normalizedEntry.documentId) {
    return recoveryResult('superseded', 'document_mismatch', normalizedEntry)
  }
  const revision = Number(current.revision)
  const lastAppliedProposal = current.lastAppliedProposal ?? null

  const atBase = revision === normalizedEntry.baseRevision
    && current.documentHash === normalizedEntry.baseHash
    && lastAppliedProposal === (
      normalizeMindmapLocalWorkspaceRecord(normalizedEntry.beforeWorkspace)
        ?.lastAppliedProposal ?? null
    )
  if (atBase) {
    return recoveryResult('not_applied', 'workspace_at_base', normalizedEntry, {
      recommendedPhase: normalizedEntry.phase === 'prepared' ? 'done' : null,
    })
  }

  const atResult = revision === normalizedEntry.appliedRevision
    && current.documentHash === normalizedEntry.resultHash
    && lastAppliedProposal === normalizedEntry.proposalId
  if (atResult) {
    if (['undone_ack_pending', 'done'].includes(normalizedEntry.phase)) {
      return recoveryResult('superseded', 'phase_workspace_conflict', normalizedEntry)
    }
    const needsApplyAck = ['prepared', 'applied_ack_pending'].includes(normalizedEntry.phase)
    const requiredAcks = needsApplyAck ? ['apply'] : []
    return recoveryResult('applied', 'workspace_at_result', normalizedEntry, {
      requiredAcks,
      ackPlan: createAckPlan(normalizedEntry, requiredAcks),
      undoAvailable: normalizedEntry.phase === 'applied_ack_confirmed',
      recommendedPhase: needsApplyAck ? 'applied_ack_pending' : null,
    })
  }

  const atUndoneBase = revision === normalizedEntry.appliedRevision + 1
    && current.documentHash === normalizedEntry.baseHash
    && lastAppliedProposal === null
  if (atUndoneBase) {
    if (normalizedEntry.phase === 'done') {
      return recoveryResult('undone', 'workspace_at_undone_base', normalizedEntry, {
        actionable: false,
      })
    }
    const needsApplyAck = ['prepared', 'applied_ack_pending'].includes(normalizedEntry.phase)
    const requiredAcks = needsApplyAck ? ['apply', 'undo'] : ['undo']
    return recoveryResult('undone', 'workspace_at_undone_base', normalizedEntry, {
      requiredAcks,
      ackPlan: createAckPlan(normalizedEntry, requiredAcks),
      recommendedPhase: needsApplyAck ? 'applied_ack_pending' : 'undone_ack_pending',
    })
  }
  return recoveryResult('superseded', 'workspace_changed', normalizedEntry)
}

export function inspectMindmapAiLocalRecovery(
  identity,
  workspace,
  storage = globalThis.localStorage,
  options = {},
) {
  const normalized = requireIdentity(identity)
  const now = resolveNow(options)
  const entry = readEntries(storage, { now }).find(candidate => sameIdentity(candidate, normalized))
  if (!entry) return recoveryResult('superseded', 'journal_missing', null)
  return classifyMindmapAiLocalRecovery(entry, workspace, {
    now,
    identity: normalized,
  })
}
