/**
 * Normalize the change counters returned by the direct-write and proposal
 * APIs.  Direct rounds historically returned `{ direct: true }` while newer
 * workers may return either `changeSummary` or the proposal-style
 * `createdCount` fields, so the UI must not turn an incomplete payload into a
 * misleading all-zero result.
 */

const SUMMARY_ALIASES = Object.freeze({
  added: ['added', 'created', 'createdCount', 'additions', 'addedCount'],
  updated: ['updated', 'updatedCount', 'updates', 'modified', 'modifiedCount'],
  moved: ['moved', 'movedCount', 'moves', 'reordered', 'reorderedCount'],
  deleted: ['deleted', 'deletedCount', 'deletions', 'removed', 'removedCount'],
})

function safeCount(value) {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null
  const count = Number(value)
  return Number.isSafeInteger(count) && count >= 0 ? count : null
}

function sourceObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value
    : null
}

/**
 * Return a canonical `{ added, updated, moved, deleted, total }` summary or
 * null when the payload does not contain any authoritative counter.
 */
function normalizeMindmapAiChangeSummary(value) {
  const source = sourceObject(value)
  if (!source) return null
  const summary = {}
  let hasCounter = false
  for (const [name, aliases] of Object.entries(SUMMARY_ALIASES)) {
    let count = null
    for (const alias of aliases) {
      if (!Object.prototype.hasOwnProperty.call(source, alias)) continue
      const parsed = safeCount(source[alias])
      if (parsed !== null) {
        count = parsed
        hasCounter = true
        break
      }
    }
    summary[name] = count ?? 0
  }
  if (!hasCounter) return null
  summary.total = summary.added + summary.updated + summary.moved + summary.deleted
  return summary
}

function nestedSummary(payload) {
  const source = sourceObject(payload)
  if (!source) return null
  // Keep this order stable: a direct changeSummary is the authoritative
  // terminal result, while `impact` is the proposal-compatible fallback.
  return normalizeMindmapAiChangeSummary(source.changeSummary)
    || normalizeMindmapAiChangeSummary(source.impact)
    || normalizeMindmapAiChangeSummary(source.summary?.changeSummary)
    || normalizeMindmapAiChangeSummary(source.summary?.impact)
    || normalizeMindmapAiChangeSummary(source.summary)
    || normalizeMindmapAiChangeSummary(source)
}

function summaryVersion(payload) {
  const version = Number(payload?.changeSummaryVersion)
  return Number.isSafeInteger(version) && version >= 1 ? version : 1
}

/**
 * Resolve the counters shown by a direct-write result card.
 *
 * A newer counter schema wins first (v2 counts net changed nodes rather than
 * historical operation occurrences). Within one schema, a terminal
 * `direct_completed` summary wins over an earlier proposal read.
 * Direct proposal IDs are stable throughout a task, but their counters are
 * mutable until its last commit. If no complete task summary exists, choose
 * directCommit then legacy draft_changed counters for each distinct batch;
 * never count both envelopes or a retried operation group twice.
 */
export function resolveMindmapAiDirectChangeSummary({
  proposal = null,
  events = [],
  jobId = '',
} = {}) {
  const expectedJobId = String(jobId || '')
  const jobEvents = (Array.isArray(events) ? events : []).filter(event => (
    !expectedJobId || String(event?.jobId || '') === expectedJobId
  ))
  const terminalEvents = jobEvents
    .filter(event => event?.eventType === 'direct_completed')
    .reverse()
  let terminalSummary = null
  let terminalVersion = 0
  for (const event of terminalEvents) {
    const summary = nestedSummary(event?.payload)
    const version = summaryVersion(event?.payload)
    if (summary && version > terminalVersion) {
      terminalSummary = summary
      terminalVersion = version
    }
  }

  const proposalBelongsToJob = !jobId || String(proposal?.jobId || '') === String(jobId)
  const proposalSummary = proposalBelongsToJob ? nestedSummary(proposal?.impact) : null
  if (terminalSummary && (!proposalSummary || terminalVersion >= summaryVersion(proposal?.impact))) {
    return terminalSummary
  }
  if (proposalSummary) return proposalSummary

  let batchSummary = null
  const seenBatches = new Set()
  for (const event of jobEvents) {
    if (event?.eventType !== 'draft_changed') continue
    const commit = sourceObject(event?.payload?.directCommit)
    if (commit?.idempotentReplay === true) continue
    const summary = nestedSummary(commit) || nestedSummary(event?.payload)
    if (!summary) continue
    const groupId = String(commit?.operationGroupId || '').trim()
    const sequence = Number(event?.sequence)
    const batchKey = groupId ? `group:${groupId}`
      : Number.isSafeInteger(sequence) && sequence > 0 ? `event:${sequence}` : ''
    if (batchKey && seenBatches.has(batchKey)) continue
    if (batchKey) seenBatches.add(batchKey)
    if (!batchSummary) batchSummary = { added: 0, updated: 0, moved: 0, deleted: 0, total: 0 }
    for (const key of Object.keys(SUMMARY_ALIASES)) batchSummary[key] += summary[key]
    batchSummary.total = batchSummary.added + batchSummary.updated + batchSummary.moved + batchSummary.deleted
  }
  return batchSummary
}

/**
 * Merge resolved direct counters into the proposal-shaped object consumed by
 * the existing result card.  Non-direct proposal fields remain untouched.
 */
export function directImpactForMindmapAiResult(proposal, summary) {
  const impact = sourceObject(proposal?.impact)
  if (!summary) return impact
  return {
    ...(impact || {}),
    direct: impact?.direct === true,
    createdCount: summary.added,
    updatedCount: summary.updated,
    movedCount: summary.moved,
    deletedCount: summary.deleted,
    changeSummary: summary,
  }
}
