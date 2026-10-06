const MESSAGE_TARGET = 'message'
const DISCUSSION_INTENT = 'discuss'
const INITIAL_SESSION_TITLE_MAX_LENGTH = 36
const UNSAFE_TITLE_CONTROL_PATTERN = /[\u0000-\u001f\u007f]/gu

function safeNonNegativeInteger(value) {
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null
}

function safeNonNegativeNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

export function deriveMindmapAiSessionTitle(value, fallback = '未命名对话') {
  if (typeof value !== 'string') return fallback
  const normalized = value
    .replace(UNSAFE_TITLE_CONTROL_PATTERN, ' ')
    .replace(/\s+/gu, ' ')
    .trim()
  return normalized
    ? Array.from(normalized).slice(0, INITIAL_SESSION_TITLE_MAX_LENGTH).join('')
    : fallback
}

export function resolveMindmapAiSessionTitle(title, turns = []) {
  if (typeof title === 'string' && title.trim()) {
    return Array.from(title.trim()).slice(0, 200).join('')
  }
  const firstPrompt = (Array.isArray(turns) ? turns : []).find(turn => (
    typeof turn?.userMessage?.content === 'string' && turn.userMessage.content.trim()
  ))?.userMessage?.content
  return deriveMindmapAiSessionTitle(firstPrompt)
}

export function isMindmapAiMessageJob(job) {
  return job?.target === MESSAGE_TARGET || job?.intent === DISCUSSION_INTENT
}

export function summarizeMindmapAiUsage(usage) {
  if (!usage || typeof usage !== 'object' || Array.isArray(usage)) return null
  const inputTokens = safeNonNegativeInteger(usage.inputTokens ?? usage.input_tokens)
  const outputTokens = safeNonNegativeInteger(usage.outputTokens ?? usage.output_tokens)
  const reportedTotal = safeNonNegativeInteger(usage.totalTokens ?? usage.total_tokens)
  const summedTotal = inputTokens !== null && outputTokens !== null
    ? safeNonNegativeInteger(inputTokens + outputTokens)
    : null
  const totalTokens = reportedTotal ?? summedTotal
  const totalCostUsd = safeNonNegativeNumber(usage.totalCostUsd ?? usage.cost)
  const costEstimated = typeof usage.costEstimated === 'boolean'
    ? usage.costEstimated
    : null
  if (
    inputTokens === null
    && outputTokens === null
    && totalTokens === null
    && totalCostUsd === null
  ) return null
  return {
    ...(inputTokens === null ? {} : { inputTokens }),
    ...(outputTokens === null ? {} : { outputTokens }),
    ...(totalTokens === null ? {} : { totalTokens }),
    ...(totalCostUsd === null ? {} : { totalCostUsd }),
    ...(costEstimated === null ? {} : { costEstimated }),
  }
}

export function resolveMindmapAiContextAvailability({
  selectedCount = 0,
  hasEditor = true,
  locked = false,
} = {}) {
  const count = Math.max(0, Number.isSafeInteger(Number(selectedCount)) ? Number(selectedCount) : 0)
  return {
    document: Boolean(hasEditor) && !locked,
    branch: Boolean(hasEditor) && !locked && count === 1,
    selectedNodes: Boolean(hasEditor) && !locked && count > 0,
    newDocument: !locked,
    file: !locked,
  }
}

export function normalizeMindmapAiSessionList(payload) {
  const source = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload
    : {}
  const seen = new Set()
  const items = []
  for (const raw of Array.isArray(source.items) ? source.items : []) {
    const sessionId = typeof raw?.sessionId === 'string' ? raw.sessionId.trim() : ''
    const currentJob = raw?.currentJob && typeof raw.currentJob === 'object'
      && !Array.isArray(raw.currentJob)
      ? { ...raw.currentJob }
      : null
    if (!sessionId || seen.has(sessionId) || !currentJob?.id) continue
    seen.add(sessionId)
    items.push({
      sessionId,
      title: typeof raw.title === 'string' && raw.title.trim()
        ? raw.title.trim().slice(0, 200)
        : '未命名对话',
      status: typeof raw.status === 'string' ? raw.status : '',
      currentAgentKey: typeof raw.currentAgentKey === 'string' ? raw.currentAgentKey : '',
      turnCount: Math.max(0, safeNonNegativeInteger(raw.turnCount) ?? 0),
      updateTime: typeof raw.updateTime === 'string' ? raw.updateTime : '',
      expiresTime: typeof raw.expiresTime === 'string' ? raw.expiresTime : '',
      ...(typeof raw.mindmapAccessible === 'boolean' ? { mindmapAccessible: raw.mindmapAccessible } : {}),
      currentJob,
    })
  }
  return {
    items,
    total: Math.max(items.length, safeNonNegativeInteger(source.total) ?? items.length),
  }
}

/** One-shot callers share the live conversation's projection logic. */
export function buildMindmapAiConversationTurns(options) {
  return createMindmapAiConversationProjector()(options)
}

/** Keep completed turns stable while only the current turn receives output. */
export function createMindmapAiConversationProjector() {
  let source = null
  let count = 0
  let lastEvent = null
  let buckets = new Map()
  let cached = new Map()
  return ({ sessionTurns = [], currentJob = null, events = [] } = {}) => {
    sessionTurns = Array.isArray(sessionTurns) ? sessionTurns : []
    events = Array.isArray(events) ? events : []
    // History pagination publishes a new array. Live events append in place.
    if (source !== events || count > events.length || (count && events[count - 1] !== lastEvent)) {
      source = events
      count = 0
      buckets = new Map()
      cached = new Map()
    }
    for (let index = count; index < events.length; index++) {
      const event = events[index]
      const id = String(event?.jobId || '')
      if (!id) continue
      let bucket = buckets.get(id)
      if (!bucket) {
        bucket = { events: [], tagEvents: [], auditEvents: [], prompt: null, usage: null, version: 0 }
        buckets.set(id, bucket)
      }
      bucket.version += 1
      if (event.eventType === 'user_prompt') {
        bucket.prompt ||= event
      } else {
        bucket.events.push(event)
        if (event.payload?.usage) bucket.usage = event.payload.usage
        if (event.eventType === 'tag_suggestions') bucket.tagEvents.push(event)
        if (!['assistant_delta', 'thinking_summary', 'thinking_state', 'todo_updated',
          'tool_started', 'tool_completed', 'tool_failed'].includes(event.eventType)) bucket.auditEvents.push(event)
      }
    }
    count = events.length
    lastEvent = events.at(-1)
    const rawTurns = new Map(sessionTurns.filter(turn => turn?.job?.id).map(turn => [String(turn.job.id), turn]))
    const currentId = String(currentJob?.id || '')
    if (currentId && !rawTurns.has(currentId)) rawTurns.set(currentId, null)
    const turns = []
    for (const [id, raw] of rawTurns) {
      const active = id === currentId ? currentJob : null
      const bucket = buckets.get(id)
      const previous = cached.get(id)
      if (previous && previous.raw === raw && previous.active === active && previous.version === bucket?.version) {
        turns.push(previous.turn)
        continue
      }
      const job = { ...raw?.job, ...active }
      const prompt = bucket?.prompt
      const turn = {
        ...raw, job,
        userMessage: raw?.userMessage ? { ...raw.userMessage }
          : typeof prompt?.payload?.message === 'string'
            ? { content: prompt.payload.message, createdTime: prompt.createdTime || '' } : null,
        assistantMessage: raw?.assistantMessage ? { ...raw.assistantMessage } : null,
        events: bucket?.events || [], tagEvents: bucket?.tagEvents || [], auditEvents: bucket?.auditEvents || [],
        // Arrays stay stable; consumers use this revision to process new tail
        // records without cloning/filtering all earlier deltas on every token.
        eventVersion: bucket?.version || 0,
        usage: summarizeMindmapAiUsage(job.usage) || summarizeMindmapAiUsage(bucket?.usage),
      }
      cached.set(id, { raw, active, version: bucket?.version, turn })
      turns.push(turn)
    }
    for (const id of cached.keys()) if (!rawTurns.has(id)) cached.delete(id)
    return turns.sort((left, right) => Number(left.job.turnIndex || 0) - Number(right.job.turnIndex || 0))
  }
}
