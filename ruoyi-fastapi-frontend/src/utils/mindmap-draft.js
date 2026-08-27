import {
  cloneJsonValueIterative,
  stringifyJsonValueIterative,
} from '../libs/simple-mind-map/src/utils/jsonClone.js'

const DB_NAME = 'vfadmin-mindmap-drafts'
const DB_VERSION = 1
const STORE_NAME = 'drafts'
const FALLBACK_PREFIX = 'vfadmin:mindmap-draft:'
const SESSION_LEASE_PREFIX = 'vfadmin:mindmap-draft-session:'
const FALLBACK_MAX_BYTES = 2 * 1024 * 1024
const DRAFT_SCHEMA_VERSION = 1
const DATABASE_OPEN_TIMEOUT_MS = 4000
const TRANSACTION_TIMEOUT_MS = 5000
export const MINDMAP_DRAFT_SESSION_LEASE_TTL_MS = 120_000

export function createMindmapDraftKey(userId, mindmapId, sessionId) {
  if (userId === undefined || userId === null || userId === '') {
    throw new Error('保存脑图草稿需要用户标识')
  }
  if (mindmapId === undefined || mindmapId === null || mindmapId === '') {
    throw new Error('保存脑图草稿需要文件标识')
  }
  const baseKey = `${String(userId)}:${String(mindmapId)}`
  return sessionId === undefined || sessionId === null || sessionId === ''
    ? baseKey
    : `${baseKey}:${String(sessionId)}`
}

export function normalizeMindmapDraftDocument(document = {}) {
  const source = document && typeof document === 'object' ? document : {}
  const normalized = {
    root: source.root || null,
    layout: source.layout || 'logicalStructure',
    theme: source.theme || {},
    view: source.view || source.viewData || null,
  }
  if (
    Object.prototype.hasOwnProperty.call(source, 'documentData')
    || Object.prototype.hasOwnProperty.call(source, 'document_data')
  ) {
    normalized.documentData = source.documentData || source.document_data || {}
  }
  return normalized
}

function cloneMindmapDraftDocument(document) {
  const normalized = normalizeMindmapDraftDocument(document)
  const cloned = cloneJsonValueIterative(normalized)
  if (!cloned || typeof cloned !== 'object' || Array.isArray(cloned)) {
    throw new TypeError('脑图草稿内容无法安全复制')
  }
  return cloned
}

export function getMindmapDraftDisplayName(draft = {}) {
  const source = draft && typeof draft === 'object' ? draft : {}
  const root = source.document?.root || source.root
  const rawName = source.name || root?.data?.text || root?.text
  const name = typeof rawName === 'string'
    ? rawName.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim()
    : ''
  return name.slice(0, 200) || `脑图 ${source.mindmapId || ''}`.trim()
}

export function getMindmapDraftSourceLabel(draft = {}) {
  if (!draft?.sessionId) return '兼容草稿'
  const suffix = String(draft.sessionId).replace(/[^a-zA-Z0-9]/g, '').slice(-6).toUpperCase()
  return suffix ? `编辑窗口 ${suffix}` : '独立编辑窗口'
}

export function stableSerialize(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  const chunks = []
  const activePath = new WeakSet()
  const stack = [{ type: 'value', value, context: 'root' }]
  while (stack.length) {
    const frame = stack.pop()
    if (frame.type === 'raw') {
      chunks.push(frame.value)
      continue
    }
    if (frame.type === 'exit') {
      activePath.delete(frame.value)
      continue
    }

    const current = frame.value
    if (current === null || typeof current !== 'object') {
      const serialized = JSON.stringify(current)
      if (serialized !== undefined) chunks.push(serialized)
      else if (frame.context === 'array') chunks.push('null')
      continue
    }
    if (activePath.has(current)) throw new TypeError('脑图数据包含循环引用')
    activePath.add(current)
    stack.push({ type: 'exit', value: current })

    if (Array.isArray(current)) {
      stack.push({ type: 'raw', value: ']' })
      for (let index = current.length - 1; index >= 0; index -= 1) {
        stack.push({ type: 'value', value: current[index], context: 'array' })
        if (index > 0) stack.push({ type: 'raw', value: ',' })
      }
      stack.push({ type: 'raw', value: '[' })
      continue
    }

    const keys = Object.keys(current)
      .filter((key) => {
        const itemType = typeof current[key]
        return itemType !== 'undefined' && itemType !== 'function' && itemType !== 'symbol'
      })
      .sort()
    stack.push({ type: 'raw', value: '}' })
    for (let index = keys.length - 1; index >= 0; index -= 1) {
      const key = keys[index]
      stack.push({ type: 'value', value: current[key], context: 'object' })
      stack.push({ type: 'raw', value: ':' })
      stack.push({ type: 'raw', value: JSON.stringify(key) })
      if (index > 0) stack.push({ type: 'raw', value: ',' })
    }
    stack.push({ type: 'raw', value: '{' })
  }
  return chunks.join('')
}

export function areMindmapDraftDocumentsEqual(left, right) {
  const comparable = (document) => {
    const normalized = normalizeMindmapDraftDocument(document)
    // 平移和缩放只是当前用户的工作区偏好，不是需要恢复或冲突保护的正文。
    // 草稿仍保留 view，恢复真实内容时可以还原当时视角，但纯视图差异不弹窗。
    const { view: _view, ...content } = normalized
    return content
  }
  return stableSerialize(comparable(left)) === stableSerialize(comparable(right))
}

function createMindmapDraftSessionLeaseKey(userId, mindmapId, sessionId) {
  return `${SESSION_LEASE_PREFIX}${createMindmapDraftKey(userId, mindmapId, sessionId)}`
}

function createMindmapDraftSessionLockName(userId, mindmapId, sessionId) {
  return `mindmap-draft-session:${createMindmapDraftKey(userId, mindmapId, sessionId)}`
}

export function renewMindmapDraftSessionLease(
  userId,
  mindmapId,
  sessionId,
  {
    now = Date.now(),
    ttlMs = MINDMAP_DRAFT_SESSION_LEASE_TTL_MS,
  } = {},
) {
  try {
    const storage = globalThis.localStorage
    if (!storage || !sessionId) return false
    storage.setItem(
      createMindmapDraftSessionLeaseKey(userId, mindmapId, sessionId),
      JSON.stringify({ sessionId: String(sessionId), expiresAt: Number(now) + Number(ttlMs) }),
    )
    return true
  } catch {
    return false
  }
}

export async function isMindmapDraftSessionActive(
  userId,
  mindmapId,
  sessionId,
  {
    now = Date.now(),
    lockManager = globalThis.navigator?.locks,
  } = {},
) {
  if (!sessionId) return false
  // Web Lock 由活动页面持有到卸载，不依赖后台标签页中会被暂停的计时器。
  // 租约继续作为不支持 Web Locks 浏览器和锁查询失败时的兼容回退。
  if (typeof lockManager?.query === 'function') {
    try {
      const state = await lockManager.query()
      const lockName = createMindmapDraftSessionLockName(userId, mindmapId, sessionId)
      if ([...(state?.held || []), ...(state?.pending || [])].some(lock => (
        lock?.name === lockName
      ))) return true
    } catch {
      // 锁查询失败时继续检查带宽松 TTL 的 localStorage 租约。
    }
  }
  const key = createMindmapDraftSessionLeaseKey(userId, mindmapId, sessionId)
  try {
    const storage = globalThis.localStorage
    const lease = JSON.parse(storage?.getItem(key) || 'null')
    if (
      lease?.sessionId === String(sessionId)
      && Number.isFinite(Number(lease.expiresAt))
      && Number(lease.expiresAt) > Number(now)
    ) return true
    storage?.removeItem(key)
  } catch {
    // 损坏或不可用的租约不能阻断崩溃草稿恢复。
  }
  return false
}

export function startMindmapDraftSessionLease(
  userId,
  mindmapId,
  sessionId,
  {
    ttlMs = MINDMAP_DRAFT_SESSION_LEASE_TTL_MS,
    setIntervalFn = (callback, delay) => setInterval(callback, delay),
    clearIntervalFn = timer => clearInterval(timer),
    lockManager = globalThis.navigator?.locks,
  } = {},
) {
  const renew = () => renewMindmapDraftSessionLease(
    userId,
    mindmapId,
    sessionId,
    { ttlMs },
  )
  renew()
  const timer = setIntervalFn(renew, Math.max(1000, Math.floor(Number(ttlMs) / 3)))
  let stopped = false
  let releaseLock = () => {}
  if (typeof lockManager?.request === 'function') {
    const lifetime = new Promise(resolve => { releaseLock = resolve })
    try {
      void Promise.resolve(lockManager.request(
        createMindmapDraftSessionLockName(userId, mindmapId, sessionId),
        async () => {
          if (!stopped) await lifetime
        },
      )).catch(() => undefined)
    } catch {
      // Web Locks 不可用时仍由 localStorage 租约提供兼容保护。
    }
  }
  return () => {
    stopped = true
    releaseLock()
    clearIntervalFn(timer)
    const key = createMindmapDraftSessionLeaseKey(userId, mindmapId, sessionId)
    try {
      const storage = globalThis.localStorage
      const lease = JSON.parse(storage?.getItem(key) || 'null')
      if (lease?.sessionId === String(sessionId)) storage.removeItem(key)
    } catch {
      // 页面卸载时尽力释放；超时租约仍会自动失效。
    }
  }
}

function openDraftDatabase() {
  if (typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('IndexedDB 不可用'))
  }
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    let settled = false
    const finish = (callback, value) => {
      if (settled) return false
      settled = true
      clearTimeout(timeoutId)
      callback(value)
      return true
    }
    const timeoutId = setTimeout(() => {
      finish(reject, new Error('打开草稿数据库超时'))
    }, DATABASE_OPEN_TIMEOUT_MS)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'key' })
        store.createIndex('updatedAt', 'updatedAt')
      }
    }
    request.onsuccess = () => {
      if (!finish(resolve, request.result)) request.result.close()
    }
    request.onerror = () => finish(reject, request.error || new Error('打开草稿数据库失败'))
    request.onblocked = () => finish(reject, new Error('草稿数据库升级被阻止'))
  })
}

async function runDraftTransaction(mode, operation) {
  const db = await openDraftDatabase()
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, mode)
      const store = transaction.objectStore(STORE_NAME)
      let settled = false
      let request
      let requestResult
      const finish = (callback, value) => {
        if (settled) return
        settled = true
        clearTimeout(timeoutId)
        callback(value)
      }
      const timeoutId = setTimeout(() => {
        try {
          transaction.abort()
        } catch {
          // 事务可能已结束，仅需让调用方回退到 localStorage。
        }
        finish(reject, new Error('草稿数据库操作超时'))
      }, TRANSACTION_TIMEOUT_MS)
      try {
        request = operation(store)
      } catch (error) {
        transaction.abort()
        finish(reject, error)
        return
      }
      request.onsuccess = () => {
        requestResult = request.result
        if (mode === 'readonly') finish(resolve, requestResult)
      }
      request.onerror = () => finish(reject, request.error || new Error('草稿数据库操作失败'))
      transaction.oncomplete = () => {
        if (mode !== 'readonly') finish(resolve, requestResult)
      }
      transaction.onabort = () => finish(reject, transaction.error || new Error('草稿数据库事务已中止'))
      transaction.onerror = () => finish(reject, transaction.error || new Error('草稿数据库事务失败'))
    })
  } finally {
    db.close()
  }
}

function getFallbackStorage() {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function readFallbackDraft(key) {
  const storage = getFallbackStorage()
  if (!storage) return null
  try {
    const value = storage.getItem(FALLBACK_PREFIX + key)
    return value ? JSON.parse(value) : null
  } catch {
    return null
  }
}

function createDraftWriteId() {
  return globalThis.crypto?.randomUUID?.()
    || `draft-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function compareDraftRecords(left, right) {
  const updatedDiff = Number(left?.updatedAt || 0) - Number(right?.updatedAt || 0)
  if (updatedDiff !== 0) return updatedDiff
  return String(left?.writeId || '').localeCompare(String(right?.writeId || ''))
}

function listFallbackDrafts(userId) {
  const storage = getFallbackStorage()
  if (!storage) return []
  const drafts = []
  try {
    for (let index = 0; index < storage.length; index += 1) {
      const storageKey = storage.key(index)
      if (!storageKey?.startsWith(FALLBACK_PREFIX)) continue
      const record = readFallbackDraft(storageKey.slice(FALLBACK_PREFIX.length))
      if (
        record?.schemaVersion === DRAFT_SCHEMA_VERSION
        && String(record.userId) === String(userId)
      ) {
        drafts.push(record)
      }
    }
  } catch {
    return []
  }
  return drafts
}

function writeFallbackDraft(record) {
  const storage = getFallbackStorage()
  if (!storage) return false
  try {
    const existing = readFallbackDraft(record.key)
    if (existing && compareDraftRecords(existing, record) > 0) return true
    const serialized = stringifyJsonValueIterative(record)
    if (new Blob([serialized]).size > FALLBACK_MAX_BYTES) return false
    storage.setItem(FALLBACK_PREFIX + record.key, serialized)
    return true
  } catch {
    return false
  }
}

function removeFallbackDraft(key, shouldRemove = () => true) {
  try {
    const storage = getFallbackStorage()
    if (!storage) return false
    const existing = readFallbackDraft(key)
    if (existing && !shouldRemove(existing)) return false
    storage.removeItem(FALLBACK_PREFIX + key)
    return true
  } catch {
    // 浏览器禁止存储时无需阻断云端保存。
    return false
  }
}

function createDraftRecord({
  userId,
  mindmapId,
  sessionId,
  contentRevision,
  document,
  name,
  updatedAt = Date.now(),
}) {
  const record = {
    key: createMindmapDraftKey(userId, mindmapId, sessionId),
    userId: String(userId),
    mindmapId: String(mindmapId),
    sessionId: sessionId === undefined || sessionId === null || sessionId === ''
      ? null
      : String(sessionId),
    contentRevision: Number(contentRevision) || 1,
    document: cloneMindmapDraftDocument(document),
    updatedAt,
    writeId: createDraftWriteId(),
    schemaVersion: DRAFT_SCHEMA_VERSION,
  }
  record.name = getMindmapDraftDisplayName({ ...record, name })
  return record
}

async function runConditionalDraftMutation(key, shouldMutate, mutate) {
  const db = await openDraftDatabase()
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, 'readwrite')
      const store = transaction.objectStore(STORE_NAME)
      let settled = false
      let changed = false
      const finish = (callback, value) => {
        if (settled) return
        settled = true
        clearTimeout(timeoutId)
        callback(value)
      }
      const timeoutId = setTimeout(() => {
        try {
          transaction.abort()
        } catch {
          // 事务可能已经结束。
        }
        finish(reject, new Error('草稿数据库条件操作超时'))
      }, TRANSACTION_TIMEOUT_MS)
      let request
      try {
        request = store.get(key)
      } catch (error) {
        transaction.abort()
        finish(reject, error)
        return
      }
      request.onsuccess = () => {
        const existing = request.result
        if (!shouldMutate(existing)) return
        try {
          mutate(store, existing)
          changed = true
        } catch (error) {
          transaction.abort()
          finish(reject, error)
        }
      }
      request.onerror = () => finish(reject, request.error || new Error('读取现有草稿失败'))
      transaction.oncomplete = () => finish(resolve, { changed })
      transaction.onabort = () => finish(reject, transaction.error || new Error('草稿数据库事务已中止'))
      transaction.onerror = () => finish(reject, transaction.error || new Error('草稿数据库事务失败'))
    })
  } finally {
    db.close()
  }
}

export function saveMindmapDraftFallbackSync(options) {
  return writeFallbackDraft(createDraftRecord(options))
}

export async function saveMindmapDraft({
  userId,
  mindmapId,
  sessionId,
  contentRevision,
  document,
  name,
  updatedAt = Date.now(),
}) {
  const record = createDraftRecord({
    userId,
    mindmapId,
    sessionId,
    contentRevision,
    document,
    name,
    updatedAt,
  })
  const { key } = record
  try {
    await runConditionalDraftMutation(
      key,
      existing => !existing || compareDraftRecords(record, existing) >= 0,
      store => store.put(record),
    )
    removeFallbackDraft(key, fallback => compareDraftRecords(fallback, record) <= 0)
    return { saved: true, storage: 'indexeddb' }
  } catch {
    const saved = writeFallbackDraft(record)
    return { saved, storage: saved ? 'localStorage' : null }
  }
}

export async function getMindmapDraft(userId, mindmapId, { key } = {}) {
  const baseKey = createMindmapDraftKey(userId, mindmapId)
  const requestedKey = typeof key === 'string' && (key === baseKey || key.startsWith(`${baseKey}:`))
    ? key
    : null
  const drafts = await listMindmapDrafts(userId)
  return drafts.find(record => (
    String(record.mindmapId) === String(mindmapId)
    && (!requestedKey || record.key === requestedKey)
  )) || null
}

export async function listMindmapDrafts(userId) {
  if (userId === undefined || userId === null || userId === '') {
    throw new Error('读取脑图草稿需要用户标识')
  }
  const fallbackRecords = listFallbackDrafts(userId)
  let indexedRecords = []
  try {
    const records = await runDraftTransaction('readonly', store => store.getAll())
    indexedRecords = Array.isArray(records) ? records : []
  } catch {
    // IndexedDB 不可用时继续使用同步回退记录。
  }

  const recordsByKey = new Map()
  for (const record of [...indexedRecords, ...fallbackRecords]) {
    if (
      record?.schemaVersion !== DRAFT_SCHEMA_VERSION
      || String(record.userId) !== String(userId)
      || !record.key
    ) continue
    const current = recordsByKey.get(record.key)
    if (!current || compareDraftRecords(record, current) > 0) {
      recordsByKey.set(record.key, {
        ...record,
        name: getMindmapDraftDisplayName(record),
      })
    }
  }
  return [...recordsByKey.values()]
    .sort((left, right) => compareDraftRecords(right, left))
}

async function removeMindmapDraftRecord(key, beforeUpdatedAt) {
  const hasCutoff = Number.isFinite(Number(beforeUpdatedAt))
  const shouldRemove = record => (
    !hasCutoff || Number(record?.updatedAt || 0) <= Number(beforeUpdatedAt)
  )
  try {
    await runConditionalDraftMutation(
      key,
      shouldRemove,
      store => store.delete(key),
    )
  } catch {
    // IndexedDB 不可用时仍继续清理回退存储。
  }
  removeFallbackDraft(key, shouldRemove)
}

export async function removeMindmapDraft(
  userId,
  mindmapId,
  { beforeUpdatedAt, sessionId, key } = {},
) {
  const baseKey = createMindmapDraftKey(userId, mindmapId)
  let keys
  if (typeof key === 'string') {
    if (key !== baseKey && !key.startsWith(`${baseKey}:`)) {
      throw new Error('草稿记录与当前用户或文件不匹配')
    }
    keys = [key]
  } else if (sessionId !== undefined && sessionId !== null && sessionId !== '') {
    keys = [createMindmapDraftKey(userId, mindmapId, sessionId)]
  } else {
    const drafts = await listMindmapDrafts(userId)
    keys = drafts
      .filter(record => String(record.mindmapId) === String(mindmapId))
      .map(record => record.key)
    if (!keys.includes(baseKey)) keys.push(baseKey)
  }
  for (const draftKey of new Set(keys)) {
    await removeMindmapDraftRecord(draftKey, beforeUpdatedAt)
  }
}

/**
 * 清理同一文件已经失活的恢复草稿，同时保护仍由其他标签页持有的会话。
 *
 * “使用云端版本”只能代表当前窗口放弃可恢复的崩溃草稿，不能替另一个仍在
 * 编辑的窗口撤销其本地保护副本。逐条按稳定 key 删除也保留 updatedAt 条件，
 * 避免检查会话状态期间的新写入被旧清理任务覆盖。
 */
export async function removeInactiveMindmapDrafts(
  userId,
  mindmapId,
  { beforeUpdatedAt } = {},
) {
  const hasCutoff = Number.isFinite(Number(beforeUpdatedAt))
  const drafts = (await listMindmapDrafts(userId)).filter(record => (
    String(record.mindmapId) === String(mindmapId)
    && (!hasCutoff || Number(record.updatedAt || 0) <= Number(beforeUpdatedAt))
  ))
  const removedKeys = []
  const preservedKeys = []
  for (const record of drafts) {
    const sessionActive = record.sessionId
      ? await isMindmapDraftSessionActive(userId, mindmapId, record.sessionId)
      : false
    if (sessionActive) {
      preservedKeys.push(record.key)
      continue
    }
    await removeMindmapDraft(userId, mindmapId, {
      key: record.key,
      beforeUpdatedAt,
    })
    removedKeys.push(record.key)
  }
  return { removedKeys, preservedKeys }
}
