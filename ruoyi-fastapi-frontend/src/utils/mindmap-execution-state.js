const ACTIVE = new Set(['queued', 'preparing', 'running', 'validating', 'waiting_turn'])
const STATES = new Set(['unknown', 'not_started', 'running', 'stopped', 'unconfirmed'])
const ORDER = { unknown: 0, not_started: 1, running: 2, unconfirmed: 3, stopped: 4 }

export function isMindmapExecutionBlocked(job) {
  if (!job) return false
  if (job.executionState === 'unconfirmed' || job.errorCode === 'AI_AGENT_CLEANUP_FAILED') {
    return job.executionState !== 'stopped'
  }
  if (ACTIVE.has(job.status)) return false
  if (['stopped', 'not_started'].includes(job.executionState)) return false
  return job.executionState === 'running' || Boolean(job.cancelRequestedTime)
    || ['cancel_requested', 'cancelled'].includes(job.status)
}

export function mergeMindmapExecutionEvidence(current, incoming) {
  const previousEpoch = current?.executionEpoch
  const epoch = incoming?.executionEpoch
  const state = incoming?.executionState
  const keep = {}
  if (current?.cancelRequestedTime) keep.cancelRequestedTime = current.cancelRequestedTime
  if (!STATES.has(state) || !Number.isSafeInteger(epoch) || epoch < 0) {
    if (STATES.has(current?.executionState)) keep.executionState = current.executionState
    if (Number.isSafeInteger(previousEpoch)) keep.executionEpoch = previousEpoch
    if (incoming && ('executionState' in incoming || 'executionEpoch' in incoming)) {
      // A malformed pair must not survive the enclosing {...incoming} merge.
      keep.executionState ??= 'unknown'
      keep.executionEpoch ??= 0
    }
    return keep
  }
  if (Number.isSafeInteger(previousEpoch) && (epoch < previousEpoch
    || (epoch === previousEpoch && (ORDER[current.executionState] ?? -1) > ORDER[state]))) {
    return { ...keep, executionState: current.executionState, executionEpoch: previousEpoch }
  }
  return { ...keep, executionState: state, executionEpoch: epoch }
}
