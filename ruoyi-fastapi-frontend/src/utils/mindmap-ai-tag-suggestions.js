const MINDMAP_AI_TAG_SUGGESTION_LIMITS = Object.freeze({
  perEvent: 10,
  perTurn: 20,
  name: 100,
  reason: 500,
  nodeUids: 200,
  nodeUid: 64,
})

const UNSAFE_CONTROLS = /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/gu

function text(value, limit) {
  if (typeof value !== 'string') return { value: '', truncated: false }
  const characters = Array.from(value.replace(UNSAFE_CONTROLS, ' ').replace(/\s+/gu, ' ').trim())
  return { value: characters.slice(0, limit).join(''), truncated: characters.length > limit }
}

// This is a display-only event: never retain arbitrary fields such as
// affectedUids/directCommit which could otherwise enter the canvas path.
export function sanitizeMindmapAiTagSuggestionsPayload(payload) {
  const source = Array.isArray(payload?.suggestions) ? payload.suggestions : []
  let truncated = payload?.truncated === true || source.length > MINDMAP_AI_TAG_SUGGESTION_LIMITS.perEvent
  const suggestions = []
  for (const raw of source.slice(0, MINDMAP_AI_TAG_SUGGESTION_LIMITS.perEvent)) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue
    const name = text(raw.name, MINDMAP_AI_TAG_SUGGESTION_LIMITS.name)
    if (!name.value) continue
    const reason = text(raw.reason, MINDMAP_AI_TAG_SUGGESTION_LIMITS.reason)
    const rawUids = Array.isArray(raw.nodeUids) ? raw.nodeUids : []
    const nodeUids = [...new Set(rawUids.filter(uid => (
      typeof uid === 'string' && uid.trim() && uid === uid.trim()
      && uid.length <= MINDMAP_AI_TAG_SUGGESTION_LIMITS.nodeUid
      && uid.replace(UNSAFE_CONTROLS, '') === uid
    )))]
    const nodeUidsTruncated = raw.nodeUidsTruncated === true
      || nodeUids.length > MINDMAP_AI_TAG_SUGGESTION_LIMITS.nodeUids
    truncated ||= name.truncated || reason.truncated || nodeUidsTruncated
    suggestions.push({
      name: name.value,
      reason: reason.value,
      nodeUids: nodeUids.slice(0, MINDMAP_AI_TAG_SUGGESTION_LIMITS.nodeUids),
      nodeUidsTruncated,
    })
  }
  return { suggestions, truncated }
}

// SSE and restored timeline events share Dialog.appendAgentEvent's sanitizer.
// Aggregate those immutable display records without re-sanitizing every render.
export function collectMindmapAiTagSuggestions(events, jobId) {
  if (!jobId) return { items: [], truncated: false }
  const matching = (Array.isArray(events) ? events : [])
    .filter(event => event?.eventType === 'tag_suggestions' && String(event.jobId || '') === String(jobId))
    .sort((left, right) => (Number(left.sequence) || 0) - (Number(right.sequence) || 0))
  const items = new Map()
  let truncated = false
  for (const event of matching) {
    const safe = event.payload
    truncated ||= safe.truncated
    for (const suggestion of safe.suggestions) {
      const key = suggestion.name.normalize('NFKC').toLowerCase()
      const previous = items.get(key)
      if (!previous && items.size >= MINDMAP_AI_TAG_SUGGESTION_LIMITS.perTurn) {
        truncated = true
        continue
      }
      const nodeUids = [...new Set([...(previous?.nodeUids || []), ...suggestion.nodeUids])]
      const nodeUidsTruncated = Boolean(previous?.nodeUidsTruncated)
        || suggestion.nodeUidsTruncated || nodeUids.length > MINDMAP_AI_TAG_SUGGESTION_LIMITS.nodeUids
      truncated ||= nodeUidsTruncated
      items.set(key, {
        ...suggestion,
        key,
        reason: suggestion.reason || previous?.reason || '',
        nodeUids: nodeUids.slice(0, MINDMAP_AI_TAG_SUGGESTION_LIMITS.nodeUids),
        nodeUidsTruncated,
      })
    }
  }
  return { items: [...items.values()], truncated }
}
