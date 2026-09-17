const STORAGE_KEY = 'MINDMAP_AI_ACK_QUEUE_V1'
const MAX_QUEUE_LENGTH = 100
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
const PERMANENT_ACK_BUSINESS_CODES = new Set([
  'AI_LOCAL_ACK_NOT_FOUND',
  'AI_LOCAL_ACK_TARGET_INVALID',
  'AI_LOCAL_ACK_CONFLICT',
  'AI_LOCAL_ACK_STATE_INVALID',
  'AI_LOCAL_ACK_DOCUMENT_MISMATCH',
  'AI_LOCAL_ACK_RESULT_MISMATCH',
])

function isValidEntry(value) {
  const action = value?.action || 'apply'
  return value
    && typeof value.ownerUserId === 'string'
    && /^[1-9]\d{0,63}$/.test(value.ownerUserId)
    && ['apply', 'undo'].includes(action)
    && typeof value.proposalId === 'string'
    && value.proposalId.length > 0
    && value.proposalId.length <= 64
    && typeof value.documentId === 'string'
    && value.documentId.length > 0
    && value.documentId.length <= 64
    && Number.isSafeInteger(value.revision)
    && value.revision >= 1
    && typeof value.resultHash === 'string'
    && /^mmf2:sha256:[a-f0-9]{64}$/.test(value.resultHash)
    && (
      action !== 'undo'
      || (
        typeof value.revertedHash === 'string'
        && /^mmf2:sha256:[a-f0-9]{64}$/.test(value.revertedHash)
      )
    )
    && Number.isSafeInteger(value.createdAt)
    && value.createdAt > 0
    && Number.isSafeInteger(value.attempts)
    && value.attempts >= 0
}

function readQueue(storage = globalThis.localStorage, now = Date.now()) {
  try {
    const parsed = JSON.parse(storage?.getItem(STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter(entry => (
      isValidEntry(entry)
      && now - entry.createdAt <= MAX_AGE_MS
    )).slice(-MAX_QUEUE_LENGTH).map(entry => ({
      ...entry,
      // Entries written by V1 before local-undo receipts existed are apply ACKs.
      action: entry.action || 'apply',
    }))
  } catch {
    return []
  }
}

function writeQueue(entries, storage = globalThis.localStorage) {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(entries.slice(-MAX_QUEUE_LENGTH)))
    return true
  } catch {
    return false
  }
}

export function enqueueMindmapAiLocalAck(payload, storage = globalThis.localStorage) {
  const entry = {
    ownerUserId: String(payload?.ownerUserId ?? '').trim(),
    action: payload?.action || 'apply',
    proposalId: payload?.proposalId,
    documentId: payload?.documentId,
    revision: Number(payload?.revision),
    resultHash: payload?.resultHash,
    ...(payload?.action === 'undo' ? { revertedHash: payload?.revertedHash } : {}),
    createdAt: Date.now(),
    attempts: 0,
  }
  if (!isValidEntry(entry)) throw new TypeError('AI 本地应用回执无效')
  const queue = readQueue(storage).filter(item => (
    item.ownerUserId !== entry.ownerUserId || item.proposalId !== entry.proposalId
  ))
  queue.push(entry)
  if (!writeQueue(queue, storage)) throw new Error('AI 本地应用回执无法持久化')
  return entry
}

export function listMindmapAiLocalAcks(
  ownerUserId,
  storage = globalThis.localStorage,
) {
  const owner = String(ownerUserId ?? '').trim()
  if (!/^[1-9]\d{0,63}$/.test(owner)) return []
  return readQueue(storage).filter(entry => entry.ownerUserId === owner)
}

const fallbackStorageKey = {}
const activeFlushes = new WeakMap()

function sameAck(left, right) {
  return left.ownerUserId === right.ownerUserId
    && (left.action || 'apply') === (right.action || 'apply')
    && left.proposalId === right.proposalId
    && left.documentId === right.documentId
    && left.revision === right.revision
    && left.resultHash === right.resultHash
    && left.revertedHash === right.revertedHash
    && left.createdAt === right.createdAt
}

function isPermanentAckFailure(error) {
  const businessCode = error?.data?.errorCode
    ?? error?.response?.data?.data?.errorCode
  if (PERMANENT_ACK_BUSINESS_CODES.has(String(businessCode || ''))) return true
  const status = Number(error?.response?.status ?? error?.status)
  if (!Number.isInteger(status)) return false
  return status >= 400
    && status < 500
    && ![401, 408, 425, 429].includes(status)
}

export function flushMindmapAiLocalAcks(
  send,
  ownerUserId,
  storage = globalThis.localStorage,
) {
  if (typeof send !== 'function') return Promise.reject(new TypeError('AI 本地应用回执发送器无效'))
  const owner = String(ownerUserId ?? '').trim()
  if (!/^[1-9]\d{0,63}$/.test(owner)) {
    return Promise.reject(new TypeError('AI 本地应用回执用户分区无效'))
  }
  const storageKey = storage && (typeof storage === 'object' || typeof storage === 'function')
    ? storage
    : fallbackStorageKey
  let storageFlushes = activeFlushes.get(storageKey)
  if (!storageFlushes) {
    storageFlushes = new Map()
    activeFlushes.set(storageKey, storageFlushes)
  }
  const activeFlush = storageFlushes.get(owner)
  if (activeFlush) return activeFlush
  const flush = (async () => {
    const queue = readQueue(storage).filter(entry => entry.ownerUserId === owner)
    const outcomes = new Map()
    let sent = 0
    let discarded = 0
    const discardedFailures = []
    for (const entry of queue) {
      try {
        await send(entry.proposalId, {
          documentId: entry.documentId,
          revision: entry.revision,
          resultHash: entry.resultHash,
          ...(entry.action === 'undo' ? { revertedHash: entry.revertedHash } : {}),
        }, entry.action)
        outcomes.set(entry.proposalId, { entry, sent: true })
        sent += 1
      } catch (error) {
        const permanent = isPermanentAckFailure(error)
        outcomes.set(entry.proposalId, { entry, sent: false, permanent })
        if (permanent) {
          discarded += 1
          discardedFailures.push({
            proposalId: entry.proposalId,
            action: entry.action,
            businessCode: String(
              error?.data?.errorCode
              ?? error?.response?.data?.data?.errorCode
              ?? '',
            ),
            message: String(error?.message || '服务端拒绝了本地 AI 回执').slice(0, 300),
          })
        }
      }
    }
    // 发送期间可能又有新的回执入队。基于最新队列只移除本轮确实发送成功的
    // 那一条，避免最后一次整体覆盖把并发入队的数据静默丢掉。
    const latestQueue = readQueue(storage)
    const nextQueue = latestQueue.flatMap(entry => {
      if (entry.ownerUserId !== owner) return [entry]
      const outcome = outcomes.get(entry.proposalId)
      if (!outcome || !sameAck(entry, outcome.entry)) return [entry]
      if (outcome.sent || outcome.permanent) return []
      return [{ ...entry, attempts: entry.attempts + 1 }]
    })
    writeQueue(nextQueue, storage)
    const pending = nextQueue.filter(entry => entry.ownerUserId === owner)
    return {
      sent,
      pending: pending.length,
      discarded,
      ...(discardedFailures.length ? { discardedFailures } : {}),
    }
  })()
  const trackedFlush = flush.finally(() => {
    const currentFlushes = activeFlushes.get(storageKey)
    if (currentFlushes?.get(owner) === trackedFlush) currentFlushes.delete(owner)
    if (currentFlushes?.size === 0) activeFlushes.delete(storageKey)
  })
  storageFlushes.set(owner, trackedFlush)
  return trackedFlush
}
