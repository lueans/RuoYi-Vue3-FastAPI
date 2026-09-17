const OWNER_USER_ID_PATTERN = /^[1-9]\d{0,63}$/

export function buildMindmapAiOwnerSessionKey(baseKey, ownerUserId) {
  const normalizedBaseKey = String(baseKey || '').trim()
  const normalizedOwnerUserId = String(ownerUserId ?? '').trim()
  if (!normalizedBaseKey || !OWNER_USER_ID_PATTERN.test(normalizedOwnerUserId)) return ''
  return `${normalizedBaseKey}:${normalizedOwnerUserId}`
}

export function readMindmapAiOwnerSessionItem(
  baseKey,
  ownerUserId,
  storage = globalThis.sessionStorage,
) {
  const scopedKey = buildMindmapAiOwnerSessionKey(baseKey, ownerUserId)
  if (!scopedKey || !storage || typeof storage.getItem !== 'function') return null
  try {
    const scopedValue = storage.getItem(scopedKey)
    if (scopedValue !== null) return scopedValue || null
    // Compatibility with the unpartitioned V1 key. Callers still validate the
    // embedded owner before accepting this value. A scoped tombstone written
    // by clear prevents the legacy value from being revived later.
    return storage.getItem(baseKey)
  } catch {
    return null
  }
}

export function writeMindmapAiOwnerSessionItem(
  baseKey,
  ownerUserId,
  serializedValue,
  storage = globalThis.sessionStorage,
) {
  const scopedKey = buildMindmapAiOwnerSessionKey(baseKey, ownerUserId)
  if (
    !scopedKey
    || typeof serializedValue !== 'string'
    || !storage
    || typeof storage.setItem !== 'function'
    || typeof storage.getItem !== 'function'
  ) return false
  try {
    storage.setItem(scopedKey, serializedValue)
    return storage.getItem(scopedKey) === serializedValue
  } catch {
    return false
  }
}

export function clearMindmapAiOwnerSessionItem(
  baseKey,
  ownerUserId,
  storage = globalThis.sessionStorage,
) {
  // Use an empty scoped tombstone instead of deleting the key. Otherwise an
  // old unpartitioned V1 value could become visible again after logout/login.
  return writeMindmapAiOwnerSessionItem(baseKey, ownerUserId, '', storage)
}
