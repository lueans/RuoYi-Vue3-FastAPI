const CREATION_ATTEMPT_VERSION = 1
const DEFAULT_CREATION_ATTEMPT_MAX_AGE_MS = 24 * 60 * 60 * 1000
const CREATION_REQUEST_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{15,99}$/

function getSessionStorage() {
  try {
    return globalThis.sessionStorage
  } catch {
    return undefined
  }
}

function isCreationRequestKey(value) {
  return typeof value === 'string' && CREATION_REQUEST_KEY_PATTERN.test(value)
}

function generateCreationRequestKey() {
  const cryptoRef = globalThis.crypto
  if (typeof cryptoRef?.randomUUID === 'function') return cryptoRef.randomUUID()
  if (typeof cryptoRef?.getRandomValues === 'function') {
    const bytes = cryptoRef.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const value = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
    return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`
  }
  throw new Error('当前浏览器无法安全生成脑图创建请求标识')
}

function readStoredAttempt(storage, storageKey, now, maxAgeMs) {
  if (!storage || !storageKey) return null
  try {
    const parsed = JSON.parse(storage.getItem(storageKey) || 'null')
    if (
      parsed?.version !== CREATION_ATTEMPT_VERSION
      || typeof parsed.intent !== 'string'
      || !isCreationRequestKey(parsed.idempotencyKey)
      || !Number.isFinite(parsed.createdAt)
      || parsed.createdAt > now
      || now - parsed.createdAt > maxAgeMs
    ) {
      storage.removeItem(storageKey)
      return null
    }
    return parsed
  } catch {
    try { storage.removeItem(storageKey) } catch {}
    return null
  }
}

function persistAttempt(storage, storageKey, attempt) {
  if (!storage || !storageKey) return
  try {
    storage.setItem(storageKey, JSON.stringify(attempt))
  } catch {
    // Server idempotency remains authoritative even when sessionStorage is
    // unavailable. Only cross-refresh retry continuity is reduced.
  }
}

/**
 * Tracks the latest UI session and keeps one durable idempotency key for an
 * unresolved creation intent. An uncertain network failure can therefore be
 * retried, including after a same-tab refresh, without creating a second file.
 */
export function createMindmapCreationAttemptTracker({
  storage,
  storageKey = 'mindmap:creation-attempt:v1',
  createKey = generateCreationRequestKey,
  now = () => Date.now(),
  maxAgeMs = DEFAULT_CREATION_ATTEMPT_MAX_AGE_MS,
} = {}) {
  if (typeof createKey !== 'function' || typeof now !== 'function') {
    throw new TypeError('脑图创建请求跟踪器配置无效')
  }
  const resolvedStorage = storage === undefined ? getSessionStorage() : storage
  let sequence = 0
  let unresolved = readStoredAttempt(resolvedStorage, storageKey, now(), maxAgeMs)

  const clearStored = () => {
    unresolved = null
    if (!resolvedStorage || !storageKey) return
    try { resolvedStorage.removeItem(storageKey) } catch {}
  }

  return {
    begin(intent) {
      if (typeof intent !== 'string' || !intent) {
        throw new TypeError('脑图创建意图不能为空')
      }
      sequence += 1
      if (!unresolved || unresolved.intent !== intent) {
        unresolved = {
          version: CREATION_ATTEMPT_VERSION,
          intent,
          idempotencyKey: createKey(),
          createdAt: now(),
        }
        if (!isCreationRequestKey(unresolved.idempotencyKey)) {
          throw new Error('脑图创建请求标识格式无效')
        }
        persistAttempt(resolvedStorage, storageKey, unresolved)
      }
      return Object.freeze({
        sequence,
        idempotencyKey: unresolved.idempotencyKey,
      })
    },
    isCurrent(attempt) {
      return Boolean(attempt) && attempt.sequence === sequence
    },
    complete(attempt) {
      if (!attempt || attempt.idempotencyKey !== unresolved?.idempotencyKey) return false
      clearStored()
      return true
    },
    invalidate() {
      sequence += 1
    },
    discard() {
      sequence += 1
      clearStored()
    },
  }
}

export function extractCreatedMindmapId(response) {
  const id = Number(response?.data?.id)
  if (!Number.isSafeInteger(id) || id <= 0) {
    throw new Error('脑图已创建，但服务端未返回有效文件 ID，请返回列表刷新后重试')
  }
  return id
}

/**
 * Resolve and open a resource after its irreversible create request has
 * already committed. Navigation failures are returned as a distinct state so
 * callers never report the mutation itself as failed or encourage a duplicate
 * retry.
 */
export async function resolveCreatedMindmapNavigation({
  response,
  extractId = extractCreatedMindmapId,
  navigate,
  isCurrent = () => true,
} = {}) {
  if (
    typeof extractId !== 'function'
    || typeof navigate !== 'function'
    || typeof isCurrent !== 'function'
  ) {
    throw new TypeError('脑图创建结果处理器配置无效')
  }

  if (!isCurrent()) {
    return {
      created: true,
      opened: false,
      mindmapId: null,
      reason: 'session-stale',
      error: null,
    }
  }

  let mindmapId
  try {
    mindmapId = extractId(response)
  } catch (error) {
    return {
      created: true,
      opened: false,
      mindmapId: null,
      reason: 'missing-id',
      error,
    }
  }

  if (!isCurrent()) {
    return {
      created: true,
      opened: false,
      mindmapId,
      reason: 'session-stale',
      error: null,
    }
  }

  try {
    const navigationFailure = await navigate(mindmapId)
    if (navigationFailure) {
      return {
        created: true,
        opened: false,
        mindmapId,
        reason: 'navigation-failed',
        error: navigationFailure instanceof Error
          ? navigationFailure
          : new Error('脑图编辑页导航被取消'),
      }
    }
    return {
      created: true,
      opened: true,
      mindmapId,
      reason: null,
      error: null,
    }
  } catch (error) {
    return {
      created: true,
      opened: false,
      mindmapId,
      reason: 'navigation-failed',
      error,
    }
  }
}
