import { isBoundedText, normalizeNumericOwnerUserId } from './mindmap-ai-shared.js'

const PREFIX = 'MINDMAP_AI_COMPOSER_DRAFTS_V1:'
const TTL = 7 * 24 * 60 * 60 * 1000
const MAX_TEXT = 20_000
const MAX_RECORD = 150_000

export function composerDraftScopeKey(scope) {
  if (!scope || !normalizeNumericOwnerUserId(scope.ownerId)
    || !isBoundedText(scope.documentKey, 256)
    || !/^(cloud|local|task):.+/.test(scope.documentKey)
    || (scope.sessionId !== null && !isBoundedText(scope.sessionId, 128))) return ''
  return JSON.stringify([String(scope.ownerId), scope.documentKey, scope.sessionId])
}

export function resolveMindmapComposerDraftScope({ ownerId, context, sessionId = null, routeMindmapId, job, standalone = false } = {}) {
  const owner = normalizeNumericOwnerUserId(ownerId)
  if (!owner) return null
  if (job && (!isBoundedText(job.sessionId, 128) || sessionId !== job.sessionId)) return null
  if (standalone) {
    if (!job || job.sourceMindmapId || !['none', 'uploaded_artifact', 'local_snapshot'].includes(job.sourceType)) return null
    const scope = { ownerId: owner, documentKey: `task:${job.sessionId}`, sessionId }
    return composerDraftScopeKey(scope) ? scope : null
  }
  if (!context?.document?.root) return null
  if (job?.sourceType === 'cloud_document'
    && String(job.sourceMindmapId || '') !== String(context.mindmapId || '')) return null
  let documentKey
  if (context.mindmapId) {
    const cloudId = normalizeNumericOwnerUserId(context.mindmapId)
    if (!cloudId || (routeMindmapId != null && String(routeMindmapId) !== cloudId)) return null
    documentKey = `cloud:${cloudId}`
  } else {
    if (routeMindmapId != null || !isBoundedText(context.documentId, 200)) return null
    documentKey = `local:${context.documentId}`
  }
  const scope = { ownerId: owner, documentKey, sessionId }
  return composerDraftScopeKey(scope) ? scope : null
}

// A convenience draft, never a source document or an execution request. Only
// text and identity enter storage; no attachments, credentials or snapshots.
export function createMindmapComposerDraftStorage({
  storage = () => globalThis.localStorage,
  now = Date.now,
  createId = () => globalThis.crypto.randomUUID(),
} = {}) {
  function storageKey(scope) {
    const key = composerDraftScopeKey(scope)
    if (!key) throw new Error('Invalid draft scope')
    return `${PREFIX}${encodeURIComponent(key)}`
  }
  function read(scope) {
    const key = composerDraftScopeKey(scope)
    if (!key) return null
    const raw = storage().getItem(storageKey(scope))
    if (!raw || raw.length > MAX_RECORD) return null
    let parsed
    try { parsed = JSON.parse(raw) } catch { return null }
    if (parsed?.version !== 1 || composerDraftScopeKey(parsed.scope) !== key
      || !isBoundedText(parsed.id, 128) || typeof parsed.text !== 'string'
      || !parsed.text.trim() || parsed.text.length > MAX_TEXT
      || !Number.isSafeInteger(parsed.savedAt) || parsed.savedAt > now()
      || now() - parsed.savedAt > TTL) return null
    return { scope: { ownerId: String(scope.ownerId), documentKey: scope.documentKey, sessionId: scope.sessionId },
      id: parsed.id, text: parsed.text, savedAt: parsed.savedAt }
  }
  function write(scope, text) {
    const key = composerDraftScopeKey(scope)
    if (!key || typeof text !== 'string' || text.length > MAX_TEXT) throw new Error('Invalid draft')
    if (!text.trim()) { remove(scope); return null }
    const record = { scope: { ownerId: String(scope.ownerId), documentKey: scope.documentKey, sessionId: scope.sessionId },
      id: createId(), text, savedAt: now() }
    if (!isBoundedText(record.id, 128)) throw new Error('Missing draft revision')
    // One key per scope: typing in another document/tab never rewrites a
    // shared account-wide dictionary and cannot lose this record indirectly.
    const encoded = JSON.stringify({ version: 1, ...record })
    if (encoded.length > MAX_RECORD) throw new Error('Draft storage limit')
    const target = storage()
    target.setItem(storageKey(scope), encoded)
    if (target.getItem(storageKey(scope)) !== encoded) throw new Error('Draft write failed')
    return record
  }
  function remove(scope, expectedId = null) {
    const key = composerDraftScopeKey(scope)
    if (!key) return false
    const current = read(scope)
    if (expectedId !== null && current?.id !== expectedId) return false
    const target = storage()
    const targetKey = storageKey(scope)
    const existed = target.getItem(targetKey) !== null
    target.removeItem(targetKey)
    if (target.getItem(targetKey) !== null) throw new Error('Draft deletion failed')
    return existed
  }
  return { read, write, remove }
}
