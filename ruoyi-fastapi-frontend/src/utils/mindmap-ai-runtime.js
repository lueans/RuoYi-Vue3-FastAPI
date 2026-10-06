// OpenDesign-style normalized runtime view. This module never changes the canvas.
function foldRuntimeEvents(events, { running = false, cancelled = false }, {
  entries = [], messages = new Map(), calls = new Map(), todos = [], steps = new Map(), currentStep = null,
} = {}) {
  const attachStep = entry => currentStep ? { ...entry, step: currentStep } : entry
  for (const event of events) {
    const payload = event?.payload || {}
    const type = event?.eventType
    const key = event?.key || `${event?.jobId}:${event?.sequence}`
    if (type === 'assistant_delta' || type === 'thinking_summary') {
      if (typeof payload.text !== 'string') continue
      const id = `${type}:${payload.messageId || key}`
      let entry = messages.get(id)
      // A tool may split a provider message; never move later prose ahead of it.
      if (!entry || entries.at(-1) !== entry) {
        entry = { key, kind: type === 'assistant_delta' ? 'message' : 'summary', text: '' }
        if (type === 'thinking_summary') entry = attachStep(entry)
        messages.set(id, entry)
        entries.push(entry)
      }
      entry.text = (entry.text + payload.text).slice(0, 100000)
    } else if (type === 'thinking_state') {
      if (entries.at(-1)?.kind !== 'thinking') entries.push(attachStep({ key, kind: 'thinking' }))
    } else if (type === 'todo_updated') {
      todos = (Array.isArray(payload.todos) ? payload.todos : []).slice(0, 40)
        .filter(item => typeof item?.content === 'string')
        .map(item => ({ ...item, content: item.content.slice(0, 500) }))
      entries.push({ key, kind: 'plan', todos: todos.map(item => ({ ...item })) })
      // Backend legacy IDs may be positional. Match unchanged, unique content,
      // never an index that may now name a different task after replanning.
      const counts = new Map()
      for (const todo of todos) counts.set(todo.content, (counts.get(todo.content) || 0) + 1)
      const nextSteps = new Map()
      for (const [index, todo] of todos.entries()) {
        if (counts.get(todo.content) !== 1) continue
        const step = steps.get(todo.content) || { key: `${key}:step:${index}`, content: todo.content }
        step.status = todo.status
        step.current = false
        nextSteps.set(todo.content, step)
      }
      for (const [content, step] of steps) {
        step.current = false
        if (!nextSteps.has(content)) step.removed = true
      }
      steps = nextSteps
      const active = todos.filter(todo => todo.status === 'in_progress')
      currentStep = active.length === 1 ? steps.get(active[0].content) || null : null
      if (currentStep) currentStep.current = running
    } else if (['tool_started', 'tool_completed', 'tool_failed'].includes(type)) {
      const id = payload.callId || (payload.step ? `step:${payload.step}` : `legacy:${payload.toolName}`)
      let entry = calls.get(id)
      if (!entry || (type === 'tool_started' && !payload.callId)) {
        entry = { key, kind: 'tool', name: payload.toolName || '工具', status: 'running' }
        // An orphan completion cannot prove when (or for which step) it began.
        // A late completion of a known call keeps its original step reference.
        if (type === 'tool_started') entry = attachStep(entry)
        entries.push(entry)
        calls.set(id, entry)
      }
      // ACP updates may refine an early placeholder without creating a new
      // call, moving it to a newer Todo, or reopening a terminal result.
      if (entry.status !== 'running' && type === 'tool_started') continue
      if (typeof payload.toolName === 'string' && payload.toolName) entry.name = payload.toolName
      if (typeof payload.toolInput === 'string') entry.input = payload.toolInput
      if (typeof payload.toolOutput === 'string') entry.output = payload.toolOutput
      if (Number.isFinite(payload.durationMs) && payload.durationMs >= 0) entry.duration = payload.durationMs
      if (Number.isSafeInteger(payload.summary?.nodeCount) && payload.summary.nodeCount >= 0) entry.scopeNodeCount = payload.summary.nodeCount
      if (type === 'tool_completed') entry.status = 'completed'
      if (type === 'tool_failed') {
        entry.status = 'failed'
        entry.error = payload.errorMessage || payload.errorCode || '工具执行失败'
      }
    }
  }
  return { entries, todos, messages, calls, steps, currentStep }
}

function runtimeView({ entries, todos }, { running = false, cancelled = false } = {}) {
  const stepSnapshots = new Map()
  return { entries: entries.map(entry => {
    // The reducer mutates aggregates in place. Publish fresh props so child
    // components invalidate computed tool details when a call is refined.
    const snapshot = { ...entry }
    if (entry.step) {
      if (!stepSnapshots.has(entry.step)) stepSnapshots.set(entry.step, { ...entry.step })
      snapshot.step = stepSnapshots.get(entry.step)
    }
    if (entry.kind === 'thinking') snapshot.active = running && entry === entries.at(-1)
    // Presentation status must not overwrite the reducer's pending call state:
    // later provider refinements/completions still belong to that same call.
    if (entry.kind === 'tool' && entry.status === 'running' && !running) {
      snapshot.status = cancelled ? 'cancelled' : 'unknown'
    }
    return snapshot
  }), todos }
}

export function projectRuntimeEvents(events = [], options = {}) {
  return runtimeView(foldRuntimeEvents(events, options), options)
}

/** One projector per mounted turn; historical prepends rebuild exactly once. */
export function createRuntimeEventProjector() {
  let state
  let count = 0
  let first
  let last
  let mode
  return (events = [], options = {}) => {
    const nextMode = `${Boolean(options.running)}:${Boolean(options.cancelled)}`
    if (mode !== nextMode || count > events.length
      || (count && (events[0] !== first || events[count - 1] !== last))) {
      state = undefined
      count = 0
    }
    state = foldRuntimeEvents(events.slice(count), options, state)
    count = events.length
    first = events[0]
    last = events.at(-1)
    mode = nextMode
    // Publish a new outer snapshot for Vue; only message/tool/plan aggregates
    // are copied here, never the accumulated raw event stream.
    return runtimeView(state, options)
  }
}

export function readAgentPreferences(ownerId, storage = globalThis.localStorage) {
  try {
    const value = JSON.parse(storage?.getItem(`mindmap:agent-preferences:${ownerId}`) || '{}')
    return {
      defaultAgent: typeof value.defaultAgent === 'string' ? value.defaultAgent : 'native_mindmap',
      hidden: Array.isArray(value.hidden) ? value.hidden.filter(item => typeof item === 'string') : [],
    }
  } catch { return { defaultAgent: 'native_mindmap', hidden: [] } }
}

export function saveAgentPreferences(ownerId, value, storage = globalThis.localStorage) {
  if (!ownerId) return false
  try {
    storage.setItem(`mindmap:agent-preferences:${ownerId}`, JSON.stringify(value))
    return true
  } catch { return false }
}
