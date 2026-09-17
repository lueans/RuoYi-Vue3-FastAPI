import {
  isBoundedText,
  isPlainObject,
  normalizeOwnerUserId,
} from './mindmap-ai-shared.js'

export const MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY = 'MINDMAP_AI_CLOUD_MUTATION_INTENTS_V1'

const SCHEMA_VERSION = 1
const MAX_ENTRY_COUNT = 100
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
const MAX_CLOCK_SKEW_MS = 5 * 60 * 1000
const ACTIONS = new Set(['apply', 'undo'])
const PHASES = new Set(['pending_server', 'server_confirmed', 'permanent_failed'])
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{16,100}$/
const ERROR_CODE_PATTERN = /^AI_[A-Z0-9_]{1,61}$/
const FORCE_OVERWRITE_RETRYABLE_CODES = new Set([
  'AI_APPLY_CONFLICT',
  'AI_PROPOSAL_STALE',
])

function normalizeIdentity(identity) {
  const ownerUserId = isPlainObject(identity)
    ? normalizeOwnerUserId(identity.ownerUserId)
    : null
  if (
    !isPlainObject(identity)
    || !ownerUserId
    || !ACTIONS.has(identity.action)
    || !isBoundedText(identity.proposalId, 64)
    || !IDEMPOTENCY_KEY_PATTERN.test(identity.idempotencyKey || '')
  ) return null
  return {
    ownerUserId,
    action: identity.action,
    proposalId: identity.proposalId,
    idempotencyKey: identity.idempotencyKey,
  }
}

function normalizeApplyPayload(payload) {
  if (!isPlainObject(payload)) return null
  const contentRevision = Number(payload.contentRevision)
  const baseHash = payload.baseHash
  const roomEpoch = payload.roomEpoch == null ? null : payload.roomEpoch
  const forceOverwrite = payload.forceOverwrite === true
  if (
    !Number.isSafeInteger(contentRevision)
    || contentRevision < 1
    || !isBoundedText(baseHash, 80)
    || (roomEpoch !== null && !isBoundedText(roomEpoch, 64))
  ) return null
  return { contentRevision, baseHash, roomEpoch, forceOverwrite }
}

function normalizeRequestPayload(action, payload) {
  if (action === 'undo') return payload == null ? null : undefined
  return normalizeApplyPayload(payload) || undefined
}

function normalizePersistedEntry(value, now = Date.now()) {
  if (!isPlainObject(value) || value.schemaVersion !== SCHEMA_VERSION) return null
  const identity = normalizeIdentity(value)
  const requestPayload = identity
    ? normalizeRequestPayload(identity.action, value.requestPayload)
    : undefined
  const mindmapId = Number(value.mindmapId)
  const createdAt = Number(value.createdAt)
  const updatedAt = Number(value.updatedAt)
  const expectedStatus = identity?.action === 'apply' ? 'applied' : 'undone'
  if (
    !identity
    || !isBoundedText(value.jobId, 64)
    || !Number.isSafeInteger(mindmapId)
    || mindmapId < 1
    || requestPayload === undefined
    || value.expectedStatus !== expectedStatus
    || !PHASES.has(value.phase)
    || !Number.isSafeInteger(createdAt)
    || createdAt < 1
    || createdAt > now + MAX_CLOCK_SKEW_MS
    || now - createdAt > MAX_AGE_MS
    || !Number.isSafeInteger(updatedAt)
    || updatedAt < createdAt
    || updatedAt > now + MAX_CLOCK_SKEW_MS
  ) return null

  let confirmedContentRevision = null
  let errorCode = null
  if (value.phase === 'server_confirmed') {
    confirmedContentRevision = Number(value.confirmedContentRevision)
    if (!Number.isSafeInteger(confirmedContentRevision) || confirmedContentRevision < 1) return null
  } else if (value.phase === 'permanent_failed') {
    if (!ERROR_CODE_PATTERN.test(value.errorCode || '')) return null
    errorCode = value.errorCode
  }

  return {
    schemaVersion: SCHEMA_VERSION,
    ...identity,
    jobId: value.jobId,
    mindmapId,
    requestPayload,
    expectedStatus,
    phase: value.phase,
    confirmedContentRevision,
    errorCode,
    createdAt,
    updatedAt,
  }
}

function cloneEntry(entry) {
  return entry ? JSON.parse(JSON.stringify(entry)) : null
}

function sameIdentity(entry, identity) {
  return entry.ownerUserId === identity.ownerUserId
    && entry.action === identity.action
    && entry.proposalId === identity.proposalId
    && entry.idempotencyKey === identity.idempotencyKey
}

function samePartition(entry, identity) {
  return entry.ownerUserId === identity.ownerUserId
    && entry.action === identity.action
    && entry.proposalId === identity.proposalId
}

function sameEntry(left, right) {
  return JSON.stringify(left) === JSON.stringify(right)
}

function canUpgradeFailedApplyToForceOverwrite(existing, candidate) {
  if (
    existing.action !== 'apply'
    || candidate.action !== 'apply'
    || existing.phase !== 'permanent_failed'
    || !FORCE_OVERWRITE_RETRYABLE_CODES.has(existing.errorCode)
    || existing.jobId !== candidate.jobId
    || existing.mindmapId !== candidate.mindmapId
    || existing.requestPayload?.forceOverwrite === true
    || candidate.requestPayload?.forceOverwrite !== true
  ) return false
  const existingPayload = { ...existing.requestPayload, forceOverwrite: true }
  return JSON.stringify(existingPayload) === JSON.stringify(candidate.requestPayload)
}

function canRetryForceOverwriteConflict(existing, candidate) {
  return existing.action === 'apply'
    && existing.phase === 'permanent_failed'
    && existing.errorCode === 'AI_APPLY_CONFLICT'
    && existing.requestPayload?.forceOverwrite === true
    && sameIdentity(existing, candidate)
    && existing.jobId === candidate.jobId
    && existing.mindmapId === candidate.mindmapId
    && JSON.stringify(existing.requestPayload) === JSON.stringify(candidate.requestPayload)
}

function readEntries(storage = globalThis.localStorage, now = Date.now()) {
  try {
    const envelope = JSON.parse(storage?.getItem(MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY) || 'null')
    if (
      !isPlainObject(envelope)
      || envelope.schemaVersion !== SCHEMA_VERSION
      || !Array.isArray(envelope.entries)
    ) return []
    return envelope.entries
      .map(entry => normalizePersistedEntry(entry, now))
      .filter(Boolean)
      .slice(-MAX_ENTRY_COUNT)
  } catch {
    return []
  }
}

function writeEntries(entries, storage = globalThis.localStorage) {
  if (!storage || typeof storage.setItem !== 'function') {
    throw new Error('AI 云端操作恢复记录无法持久化')
  }
  const envelope = {
    schemaVersion: SCHEMA_VERSION,
    entries: entries.slice(-MAX_ENTRY_COUNT),
  }
  try {
    storage.setItem(MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY, JSON.stringify(envelope))
  } catch (error) {
    throw new Error('AI 云端操作恢复记录无法持久化', { cause: error })
  }
}

function persistAndVerify(entries, expectedEntry, storage) {
  writeEntries(entries, storage)
  const persisted = readEntries(storage).find(entry => sameIdentity(entry, expectedEntry))
  if (!persisted || !sameEntry(persisted, expectedEntry)) {
    throw new Error('AI 云端操作恢复记录写入后校验失败')
  }
  return cloneEntry(persisted)
}

function persistRemovalAndVerify(entries, identity, storage) {
  writeEntries(entries, storage)
  if (readEntries(storage).some(entry => sameIdentity(entry, identity))) {
    throw new Error('AI 云端操作恢复记录删除后校验失败')
  }
  return true
}

function requireIdentity(identity) {
  const normalized = normalizeIdentity(identity)
  if (!normalized) throw new TypeError('AI 云端操作恢复标识无效')
  return normalized
}

export function enqueueMindmapAiCloudMutationIntent(input, storage = globalThis.localStorage) {
  const identity = requireIdentity(input)
  const requestPayload = normalizeRequestPayload(identity.action, input?.requestPayload)
  const mindmapId = Number(input?.mindmapId)
  if (
    !isBoundedText(input?.jobId, 64)
    || !Number.isSafeInteger(mindmapId)
    || mindmapId < 1
    || requestPayload === undefined
  ) throw new TypeError('AI 云端操作恢复记录无效')

  const now = Date.now()
  const entries = readEntries(storage, now)
  const partitionEntry = entries.find(entry => samePartition(entry, identity))

  const freshEntry = {
    schemaVersion: SCHEMA_VERSION,
    ...identity,
    jobId: input.jobId,
    mindmapId,
    requestPayload,
    expectedStatus: identity.action === 'apply' ? 'applied' : 'undone',
    phase: 'pending_server',
    confirmedContentRevision: null,
    errorCode: null,
    createdAt: now,
    updatedAt: now,
  }
  const upgradeFailedApply = partitionEntry
    && !sameIdentity(partitionEntry, identity)
    && canUpgradeFailedApplyToForceOverwrite(partitionEntry, freshEntry)
  if (partitionEntry && !sameIdentity(partitionEntry, identity) && !upgradeFailedApply) {
    throw new Error('同一 AI 云端操作已有不同的幂等请求待确认')
  }
  if (partitionEntry) {
    if (!upgradeFailedApply && !canRetryForceOverwriteConflict(partitionEntry, freshEntry) && (
      partitionEntry.jobId !== freshEntry.jobId
      || partitionEntry.mindmapId !== freshEntry.mindmapId
      || JSON.stringify(partitionEntry.requestPayload) !== JSON.stringify(freshEntry.requestPayload)
    )) throw new Error('AI 云端操作幂等请求与已保存参数不一致')
  }

  // 旧版客户端可能已把普通 apply 的版本冲突保存为永久失败。用户在新版
  // 界面再次勾选“完整覆盖”时，这是一次新的显式授权，可以用独立幂等键
  // 原子替换旧失败记录。结果未知或已经服务端确认的请求仍严格禁止替换。
  // 已明确选择覆盖但只因协作栅栏竞争失败时，同一次显式点击也允许把记录
  // 恢复为 pending_server；服务端幂等键继续保证不会重复提交。
  const retryForceOverwrite = partitionEntry
    && canRetryForceOverwriteConflict(partitionEntry, freshEntry)
  const entry = upgradeFailedApply || retryForceOverwrite
    ? freshEntry
    : partitionEntry || freshEntry
  const nextEntries = entries.filter(candidate => !samePartition(candidate, identity))
  nextEntries.push(entry)
  return persistAndVerify(nextEntries, entry, storage)
}

export function listMindmapAiCloudMutationIntents(
  ownerUserId,
  storage = globalThis.localStorage,
) {
  const owner = normalizeOwnerUserId(ownerUserId)
  if (!owner) return []
  return readEntries(storage)
    .filter(entry => entry.ownerUserId === owner)
    .map(cloneEntry)
}

export function getMindmapAiCloudMutationIntent(identity, storage = globalThis.localStorage) {
  const normalized = requireIdentity(identity)
  return cloneEntry(readEntries(storage).find(entry => sameIdentity(entry, normalized)))
}

export function markMindmapAiCloudMutationConfirmed(
  identity,
  contentRevision,
  storage = globalThis.localStorage,
) {
  const normalized = requireIdentity(identity)
  const revision = Number(contentRevision)
  if (!Number.isSafeInteger(revision) || revision < 1) {
    throw new TypeError('AI 云端操作确认版本无效')
  }
  const entries = readEntries(storage)
  const index = entries.findIndex(entry => sameIdentity(entry, normalized))
  if (index < 0) return null
  const updated = {
    ...entries[index],
    phase: 'server_confirmed',
    confirmedContentRevision: revision,
    errorCode: null,
    updatedAt: Math.max(Date.now(), entries[index].createdAt),
  }
  entries[index] = updated
  return persistAndVerify(entries, updated, storage)
}

export function markMindmapAiCloudMutationFailed(
  identity,
  errorCode,
  storage = globalThis.localStorage,
) {
  const normalized = requireIdentity(identity)
  if (!ERROR_CODE_PATTERN.test(errorCode || '')) {
    throw new TypeError('AI 云端操作失败码无效')
  }
  const entries = readEntries(storage)
  const index = entries.findIndex(entry => sameIdentity(entry, normalized))
  if (index < 0) return null
  const updated = {
    ...entries[index],
    phase: 'permanent_failed',
    confirmedContentRevision: null,
    errorCode,
    updatedAt: Math.max(Date.now(), entries[index].createdAt),
  }
  entries[index] = updated
  return persistAndVerify(entries, updated, storage)
}

export function removeMindmapAiCloudMutationIntent(
  identity,
  storage = globalThis.localStorage,
) {
  const normalized = requireIdentity(identity)
  const entries = readEntries(storage)
  if (!entries.some(entry => sameIdentity(entry, normalized))) return false
  return persistRemovalAndVerify(
    entries.filter(entry => !sameIdentity(entry, normalized)),
    normalized,
    storage,
  )
}
