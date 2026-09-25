import { getToken } from './auth.js'
import { isMindmapAiAbortError as isAbortError } from './mindmap-ai-errors.js'
import { stableJsonValue } from './mindmap-ai-shared.js'
import { compareMindmapAiPreviewCoordinates } from './mindmap-ai-live-preview.js'

export const MINDMAP_AI_MAX_SSE_EVENT_CHARS = 256 * 1024

const MINDMAP_AI_AGENT_PROGRESS_STAGE_LABELS = Object.freeze({
  sdk_ready: 'SDK 就绪',
  turn_started: '请求开始',
  model_processing: '模型处理中',
  usage_updated: '用量更新',
  structured_output_received: '结构化结果',
  turn_completed: '本轮完成',
})

function normalizeBaseUrl(value) {
  return String(value || '').replace(/\/+$/, '')
}

function createStreamError(code, message, details = {}) {
  const error = new Error(message)
  error.code = code
  Object.assign(error, details)
  return error
}

function safeTokenCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null
}

// Codex 进度事件在服务端已经过白名单清洗；浏览器仍只保留展示所需的
// stage/progress/总 token，避免未来服务端字段扩展时把模型正文带入会话栏。
export function sanitizeMindmapAiAgentProgressPayload(payload) {
  const source = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload
    : {}
  const sanitized = {}
  if (Object.hasOwn(MINDMAP_AI_AGENT_PROGRESS_STAGE_LABELS, source.stage)) {
    sanitized.stage = source.stage
  }
  if (Number.isInteger(source.progress) && source.progress >= 0 && source.progress <= 100) {
    sanitized.progress = source.progress
  }
  const directTotal = safeTokenCount(source.usage?.totalTokens)
  const inputTokens = safeTokenCount(source.usage?.inputTokens)
  const outputTokens = safeTokenCount(source.usage?.outputTokens)
  const summedTotal = inputTokens !== null && outputTokens !== null
    && Number.isSafeInteger(inputTokens + outputTokens)
    ? inputTokens + outputTokens
    : null
  const totalTokens = directTotal ?? summedTotal
  if (totalTokens !== null) sanitized.usage = { totalTokens }
  return sanitized
}

export function describeMindmapAiAgentProgress(payload) {
  const safe = sanitizeMindmapAiAgentProgressPayload(payload)
  const parts = [MINDMAP_AI_AGENT_PROGRESS_STAGE_LABELS[safe.stage] || 'Agent 正在处理']
  if (Number.isInteger(safe.progress)) parts.push(`${safe.progress}%`)
  if (Number.isSafeInteger(safe.usage?.totalTokens)) {
    parts.push(`Token 合计 ${safe.usage.totalTokens}`)
  }
  return parts.join(' · ')
}

// 通用 agent_event 只代表 SDK 消息信封，工具调用、草稿变更和状态事件拥有
// 各自的 eventType，不能在这里合并。该键用于兼容旧任务中重复上千次的 Claude
// 消息信封，同时确保不同任务、阶段和消息类型仍分别展示。
export function buildMindmapAiTimelineEnvelopeKey(jobId, eventType, payload) {
  if (eventType !== 'agent_event') return null
  const source = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload
    : {}
  const messageType = typeof source.messageType === 'string'
    ? source.messageType.slice(0, 100)
    : ''
  if (!messageType) return null
  const stage = typeof source.stage === 'string' ? source.stage.slice(0, 100) : ''
  return `${String(jobId || '')}:agent_event:${stage}:${messageType}`
}

export function fingerprintMindmapAiRequest(payload) {
  return JSON.stringify(stableJsonValue(payload))
}

export function resolveMindmapAiRequestAttempt(
  currentAttempt,
  payload,
  { createKey } = {},
) {
  if (typeof createKey !== 'function') throw new TypeError('AI 幂等键生成器无效')
  const fingerprint = fingerprintMindmapAiRequest(payload)
  if (
    currentAttempt?.key
    && currentAttempt.fingerprint === fingerprint
  ) return currentAttempt
  return { key: createKey(), fingerprint }
}

const MINDMAP_AI_TERMINAL_JOB_STATUSES = new Set([
  'ready', 'applied', 'undone', 'completed_file', 'completed_direct', 'completed_no_change',
  'needs_review', 'stale', 'cancelled', 'failed', 'expired',
  'needs_input', 'rejected',
])

const MINDMAP_AI_TERMINAL_TRANSITIONS = Object.freeze({
  // Authoritative GET may coalesce multiple committed side effects. A stale
  // tab can therefore observe ready/needs_review -> undone without ever seeing
  // the intermediate applied snapshot; accepting this transitive transition
  // is required to avoid presenting an already-undone proposal as applied.
  ready: new Set(['applied', 'undone', 'rejected', 'completed_file', 'completed_direct', 'stale']),
  needs_review: new Set(['applied', 'undone', 'rejected', 'stale']),
  applied: new Set(['undone']),
  // Direct-write jobs create an undo receipt before the first batch. If a
  // later batch fails (or the task is cancelled), the server can still
  // complete the compensating undo and move the job to `undone`.
  completed_direct: new Set(['undone']),
  failed: new Set(['undone']),
  stale: new Set(['undone']),
  cancelled: new Set(['undone']),
})

const MINDMAP_AI_ACTIVE_STATUS_ORDER = Object.freeze({
  waiting_turn: -1,
  queued: 0,
  preparing: 1,
  running: 2,
  validating: 3,
  cancel_requested: 4,
})

export function mindmapAiTerminalErrorUpdate(eventType, payload) {
  if (
    eventType !== 'status_changed'
    || !payload
    || typeof payload !== 'object'
    || !MINDMAP_AI_TERMINAL_JOB_STATUSES.has(payload.status)
  ) return {}
  const update = {}
  if (typeof payload.errorCode === 'string') update.errorCode = payload.errorCode
  if (typeof payload.errorMessage === 'string') update.errorMessage = payload.errorMessage
  return update
}

export function mergeMindmapAiJobEventSnapshot(currentJob, event) {
  if (!currentJob || typeof currentJob !== 'object') return currentJob || null
  const eventType = String(event?.eventType || event?.data?.eventType || '')
  const payload = event?.payload ?? event?.data?.payload
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return currentJob
  const updates = {}
  if (typeof payload.status === 'string') {
    updates.status = payload.status
    const createdTime = event?.createdTime ?? event?.data?.createdTime
    if (typeof createdTime === 'string' && createdTime) updates.updateTime = createdTime
  }
  if (Number.isFinite(Number(payload.progress))) updates.progress = Number(payload.progress)
  Object.assign(updates, mindmapAiTerminalErrorUpdate(eventType, payload))
  if (typeof payload.artifactId === 'string') updates.artifactId = payload.artifactId
  if (typeof payload.proposalId === 'string') updates.proposalId = payload.proposalId
  return Object.keys(updates).length
    ? mergeMindmapAiJobSnapshot(currentJob, updates)
    : currentJob
}

function timestamp(value) {
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

function activeStatusTransition(currentJob, incomingJob) {
  const currentOrder = MINDMAP_AI_ACTIVE_STATUS_ORDER[currentJob?.status]
  const incomingOrder = MINDMAP_AI_ACTIVE_STATUS_ORDER[incomingJob?.status]
  if (!Number.isInteger(currentOrder) || !Number.isInteger(incomingOrder)) {
    return { regression: false, newer: false, stale: false }
  }
  const currentTime = timestamp(currentJob?.updateTime)
  const incomingTime = timestamp(incomingJob?.updateTime)
  return {
    regression: incomingOrder < currentOrder,
    // A worker recovery is allowed to move an active job back to queued, but
    // only when the server/event gives us a strictly newer semantic revision.
    newer: currentTime !== null && incomingTime !== null && incomingTime > currentTime,
    stale: currentTime !== null && incomingTime !== null && incomingTime < currentTime,
  }
}

export function mergeMindmapAiJobSnapshot(currentJob, incomingJob) {
  if (!incomingJob || typeof incomingJob !== 'object') return currentJob || null
  if (
    !currentJob
    || typeof currentJob !== 'object'
    || (incomingJob.id != null && currentJob.id !== incomingJob.id)
  ) {
    return { ...incomingJob }
  }
  const currentProgress = Number(currentJob.progress)
  const incomingProgress = Number(incomingJob.progress)
  let progress = Math.max(
    Number.isFinite(currentProgress) ? currentProgress : 0,
    Number.isFinite(incomingProgress) ? incomingProgress : 0,
  )
  const activeTransition = activeStatusTransition(currentJob, incomingJob)
  const rejectedActiveTransition = activeTransition.stale
    || (activeTransition.regression && !activeTransition.newer)
  let incomingStatusOverride = incomingJob.status
  if (rejectedActiveTransition) {
    // Replayed SSE events and slow polls must not visually rewind an active
    // job. A genuinely newer queued snapshot is retained for worker recovery.
    incomingStatusOverride = currentJob.status
    if (activeTransition.stale) {
      progress = Number.isFinite(currentProgress) ? currentProgress : 0
    }
  } else if (activeTransition.regression && activeTransition.newer) {
    progress = Number.isFinite(incomingProgress) ? incomingProgress : 0
  }
  // A status poll can start before a terminal SSE event but resolve after it.
  // Keep the already-observed terminal snapshot intact instead of reviving the
  // task and discarding its artifact/error fields with that stale response.
  if (
    MINDMAP_AI_TERMINAL_JOB_STATUSES.has(currentJob.status)
    && typeof incomingJob.status === 'string'
    && !MINDMAP_AI_TERMINAL_JOB_STATUSES.has(incomingJob.status)
  ) return { ...currentJob, progress }
  if (
    MINDMAP_AI_TERMINAL_JOB_STATUSES.has(currentJob.status)
    && MINDMAP_AI_TERMINAL_JOB_STATUSES.has(incomingJob.status)
    && currentJob.status !== incomingJob.status
  ) {
    // A request issued before apply/save/undo may resolve afterwards with an
    // older terminal snapshot. Only server-supported terminal side effects may
    // replace an already observed terminal state.
    const allowed = MINDMAP_AI_TERMINAL_TRANSITIONS[currentJob.status]
    if (!allowed?.has(incomingJob.status)) return { ...currentJob, progress }
  }
  // The same race exists between a cancel response and an older active poll.
  // A later terminal response is still authoritative and is accepted normally.
  const incomingStatus = typeof incomingStatusOverride === 'string'
    ? incomingStatusOverride
    : currentJob.status
  const status = currentJob.status === 'cancel_requested'
    && !MINDMAP_AI_TERMINAL_JOB_STATUSES.has(incomingStatus)
    ? currentJob.status
    : incomingStatus
  const merged = {
    ...currentJob,
    ...incomingJob,
    ...(typeof status === 'string' ? { status } : {}),
    progress,
  }
  // A rejected active snapshot must not advance or rewind the semantic clock
  // used to judge later worker-recovery transitions. Otherwise two replayed
  // responses can collaborate: the first rewinds updateTime and the second is
  // then incorrectly accepted as a newer status regression.
  if (rejectedActiveTransition) {
    if (Object.prototype.hasOwnProperty.call(currentJob, 'updateTime')) {
      merged.updateTime = currentJob.updateTime
    } else {
      delete merged.updateTime
    }
  }
  return merged
}

export function parseMindmapAiSseChunk(buffer, chunk, { flush = false } = {}) {
  let source = `${buffer || ''}${chunk || ''}`
  // CRLF 可能刚好跨网络 chunk，非 flush 时保留末尾 CR，等下一块后再判定。
  const trailingCr = !flush && source.endsWith('\r') && !source.endsWith('\r\r')
  if (trailingCr) source = source.slice(0, -1)
  let normalized = source.replace(/\r\n|\r/g, '\n')
  if (trailingCr) normalized += '\r'
  if (!buffer && normalized.charCodeAt(0) === 0xFEFF) normalized = normalized.slice(1)
  const blocks = normalized.split('\n\n')
  const remainder = flush ? '' : (blocks.pop() || '')
  if (remainder.length > MINDMAP_AI_MAX_SSE_EVENT_CHARS) {
    throw createStreamError('AI_EVENT_TOO_LARGE', 'AI 实时事件超过安全大小限制')
  }
  const events = []
  for (const block of blocks) {
    if (!block) continue
    if (block.length > MINDMAP_AI_MAX_SSE_EVENT_CHARS) {
      throw createStreamError('AI_EVENT_TOO_LARGE', 'AI 实时事件超过安全大小限制')
    }
    let id = ''
    let eventType = 'message'
    const data = []
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const separator = line.indexOf(':')
      const field = separator < 0 ? line : line.slice(0, separator)
      let value = separator < 0 ? '' : line.slice(separator + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'id' && !value.includes('\0')) id = value
      else if (field === 'event') eventType = value || 'message'
      else if (field === 'data') data.push(value)
    }
    if (!data.length) continue
    try {
      events.push({ id, eventType, data: JSON.parse(data.join('\n')) })
    } catch {
      const sequence = Number(id)
      events.push({
        id,
        eventType: 'stream_error',
        data: {
          code: 'AI_EVENT_INVALID',
          ...(Number.isSafeInteger(sequence) && sequence > 0 ? { sequence } : {}),
        },
      })
    }
  }
  return { events, remainder }
}

async function readStreamResponseError(response, fallbackMessage) {
  let payload = null
  const contentType = response?.headers?.get?.('content-type') || ''
  if (/\bapplication\/(?:[\w.+-]+\+)?json\b/i.test(contentType)) {
    try {
      const readable = typeof response.clone === 'function' ? response.clone() : response
      payload = await readable.json?.()
    } catch {}
  }
  const errorCode = payload?.data?.errorCode
    || (Number(payload?.code) === 401 ? 'AI_AUTH_REQUIRED' : 'AI_STREAM_CONNECTION_FAILED')
  return createStreamError(errorCode, payload?.msg || fallbackMessage, {
    status: response?.status,
    data: payload?.data,
  })
}

export async function streamMindmapAiJobEvents(jobId, {
  afterSequence = 0,
  signal,
  onEvent,
  onOpen,
  fetchImpl = globalThis.fetch,
  token = getToken(),
  baseUrl = import.meta.env?.VITE_APP_BASE_API || '',
} = {}) {
  if (!jobId || typeof fetchImpl !== 'function') throw new Error('AI 事件流参数无效')
  const headers = { Accept: 'text/event-stream' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (Number(afterSequence) > 0) headers['Last-Event-ID'] = String(afterSequence)
  const response = await fetchImpl(
    `${normalizeBaseUrl(baseUrl)}/mindmap/ai/jobs/${encodeURIComponent(jobId)}/events`,
    { headers, signal, cache: 'no-store' },
  )
  if (!response.ok) {
    throw await readStreamResponseError(
      response,
      `AI 事件流连接失败（HTTP ${response.status}）`,
    )
  }
  const contentType = response.headers?.get?.('content-type') || ''
  if (!/\btext\/event-stream\b/i.test(contentType)) {
    throw await readStreamResponseError(response, 'AI 事件流返回了无效响应')
  }
  if (!response.body?.getReader) throw new Error('当前浏览器不支持 AI 实时事件流')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false
  try {
    await onOpen?.()
    while (true) {
      const { done, value } = await reader.read()
      const parsed = parseMindmapAiSseChunk(
        buffer,
        decoder.decode(value || new Uint8Array(), { stream: !done }),
        { flush: done },
      )
      buffer = parsed.remainder
      for (const event of parsed.events) await onEvent?.(event)
      if (done) {
        completed = true
        return
      }
    }
  } finally {
    if (!completed) {
      try { await reader.cancel() } catch {}
    }
    reader.releaseLock?.()
  }
}

export async function consumeMindmapAiRealtimeEvents(jobId, {
  afterSequence = 0,
  previewVersion = -1,
  previewEpoch = 1,
  signal,
  onEvent,
  onDraft,
  onDraftError,
  onOpen,
  streamImpl = streamMindmapAiJobEvents,
  fetchDraft,
  fetchDraftEnabled = true,
} = {}) {
  let latestSequence = Math.max(0, Number(afterSequence) || 0)
  let latestPreviewVersion = Number.isFinite(Number(previewVersion))
    ? Number(previewVersion)
    : -1
  let latestPreviewEpoch = Math.max(1, Number(previewEpoch) || 1)
  let pendingPreviewCoordinates = null
  const latestCoordinates = () => ({ epoch: latestPreviewEpoch, version: latestPreviewVersion })
  let draftDrain = null
  let draftFailure = null

  // Draft snapshots are fetched independently of the SSE reader. Waiting for
  // each HTTP request in the event callback stalls every later model/tool
  // event and can leave all visible edits until after the job has finished.
  // Keep the first in-flight version, then fetch the newest queued version.
  const startDraftDrain = () => {
    if (!fetchDraftEnabled || draftDrain || pendingPreviewCoordinates === null || draftFailure) return
    draftDrain = (async () => {
      while (pendingPreviewCoordinates !== null) {
        const requested = pendingPreviewCoordinates
        const requestedVersion = requested.version
        pendingPreviewCoordinates = null
        if (compareMindmapAiPreviewCoordinates(requested, latestCoordinates()) <= 0) continue
        let response
        try {
          response = await fetchDraft(jobId, { signal, version: requestedVersion })
        } catch (error) {
          if (isAbortError(error)) throw error
          await onDraftError?.(error, {
            requestedVersion,
            afterSequence: latestSequence,
          })
          continue
        }

        const preview = response?.data ?? response
        const receivedVersion = Number(preview?.operationCursor)
        const receivedEpoch = Number(preview?.previewEpoch || 1)
        // Never substitute an unversioned latest snapshot for an earlier
        // request; recovery/polling will repair an evicted exact version.
        if (
          preview?.available !== true
          || !preview.document?.root
          || !Number.isSafeInteger(receivedVersion)
          || receivedVersion !== requestedVersion
          || receivedEpoch !== requested.epoch
          || (pendingPreviewCoordinates && pendingPreviewCoordinates.epoch > receivedEpoch)
          || compareMindmapAiPreviewCoordinates({ epoch: receivedEpoch, version: receivedVersion }, latestCoordinates()) <= 0
        ) continue
        latestPreviewVersion = receivedVersion
        latestPreviewEpoch = receivedEpoch
        await onDraft?.(preview)
      }
    })().catch(error => {
      draftFailure = error
    }).finally(() => {
      draftDrain = null
      // An event may arrive just as the drain finishes. Do not strand it.
      if (pendingPreviewCoordinates !== null && !draftFailure) startDraftDrain()
    })
  }

  try {
    await streamImpl(jobId, {
      afterSequence: latestSequence,
      signal,
      onOpen,
      onEvent: async event => {
        const sequence = Number(event?.data?.sequence ?? event?.id)
        if (!Number.isInteger(sequence) || sequence <= latestSequence) return
        latestSequence = sequence
        await onEvent?.(event)

        const payload = event?.data?.payload
        const requestedVersion = Number(payload?.previewVersion)
        const requestedEpoch = Number(payload?.previewEpoch || 1)
        const requested = { epoch: requestedEpoch, version: requestedVersion }
        if (
          event?.eventType !== 'draft_changed'
          && event?.eventType !== 'draft_initialized'
        ) return
        if (
          payload?.previewAvailable !== true
          || !Number.isInteger(requestedVersion)
          || !Number.isInteger(requestedEpoch)
          || requestedEpoch < 1
          || compareMindmapAiPreviewCoordinates(requested, latestCoordinates()) <= 0
          || typeof fetchDraft !== 'function'
          || !fetchDraftEnabled
        ) return

        if (!pendingPreviewCoordinates || compareMindmapAiPreviewCoordinates(requested, pendingPreviewCoordinates) > 0) {
          pendingPreviewCoordinates = requested
        }
        startDraftDrain()
      },
    })
  } finally {
    // A finite stream can end immediately after the last event. Deliver the
    // already committed preview before returning its resume cursor.
    while (draftDrain) await draftDrain
  }
  if (draftFailure) throw draftFailure

  return {
    afterSequence: latestSequence,
    previewVersion: latestPreviewVersion,
    previewEpoch: latestPreviewEpoch,
  }
}
