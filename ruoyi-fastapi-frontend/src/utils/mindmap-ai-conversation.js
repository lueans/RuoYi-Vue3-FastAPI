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
      currentJob,
    })
  }
  return {
    items,
    total: Math.max(items.length, safeNonNegativeInteger(source.total) ?? items.length),
  }
}

export function buildMindmapAiConversationTurns({
  sessionTurns = [],
  currentJob = null,
  events = [],
} = {}) {
  const turnsByJobId = new Map()
  for (const raw of Array.isArray(sessionTurns) ? sessionTurns : []) {
    const jobId = String(raw?.job?.id || '')
    if (!jobId) continue
    turnsByJobId.set(jobId, {
      ...raw,
      job: { ...raw.job },
      userMessage: raw.userMessage ? { ...raw.userMessage } : null,
      assistantMessage: raw.assistantMessage ? { ...raw.assistantMessage } : null,
    })
  }
  const currentJobId = String(currentJob?.id || '')
  if (currentJobId) {
    const existing = turnsByJobId.get(currentJobId)
    turnsByJobId.set(currentJobId, {
      ...(existing || {}),
      job: { ...(existing?.job || {}), ...currentJob },
      userMessage: existing?.userMessage || null,
      assistantMessage: existing?.assistantMessage || null,
    })
  }
  const eventsByJobId = new Map()
  for (const event of Array.isArray(events) ? events : []) {
    const jobId = String(event?.jobId || '')
    if (!jobId) continue
    const list = eventsByJobId.get(jobId) || []
    list.push(event)
    eventsByJobId.set(jobId, list)
  }
  for (const [jobId, turn] of turnsByJobId) {
    const turnEvents = eventsByJobId.get(jobId) || []
    const promptEvent = turnEvents.find(event => event?.eventType === 'user_prompt')
    if (!turn.userMessage && typeof promptEvent?.payload?.message === 'string') {
      turn.userMessage = {
        content: promptEvent.payload.message,
        createdTime: promptEvent.createdTime || '',
      }
    }
    turn.events = turnEvents.filter(event => event?.eventType !== 'user_prompt')
    const eventUsage = [...turn.events].reverse().find(event => event?.payload?.usage)?.payload?.usage
    turn.usage = summarizeMindmapAiUsage(turn.job?.usage)
      || summarizeMindmapAiUsage(eventUsage)
  }
  return [...turnsByJobId.values()].sort((left, right) => (
    Number(left?.job?.turnIndex || 0) - Number(right?.job?.turnIndex || 0)
  ))
}
