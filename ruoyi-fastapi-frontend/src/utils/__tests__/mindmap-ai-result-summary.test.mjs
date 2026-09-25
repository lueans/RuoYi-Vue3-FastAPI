import assert from 'node:assert/strict'
import test from 'node:test'
import {
  directImpactForMindmapAiResult,
  resolveMindmapAiDirectChangeSummary,
} from '../mindmap-ai-result-summary.js'

const resolveImpact = impact => resolveMindmapAiDirectChangeSummary({ proposal: { impact } })

test('direct proposal impact counters are normalized without losing zero values', () => {
  assert.deepEqual(resolveImpact({
    createdCount: 2,
    updatedCount: 1,
    movedCount: 0,
    deletedCount: 3,
  }), {
    added: 2,
    updated: 1,
    moved: 0,
    deleted: 3,
    total: 6,
  })
})

test('missing legacy direct impact falls back to terminal direct_completed summary', () => {
  const summary = resolveMindmapAiDirectChangeSummary({
    proposal: { impact: { direct: true } },
    jobId: 'job-1',
    events: [
      {
        jobId: 'job-1',
        eventType: 'draft_changed',
        payload: { directCommit: { changeSummary: { added: 99 } } },
      },
      {
        jobId: 'job-1',
        eventType: 'direct_completed',
        payload: {
          changeSummary: {
            createdCount: 4,
            updatedCount: 2,
            movedCount: 1,
            deletedCount: 0,
          },
        },
      },
    ],
  })
  assert.deepEqual(summary, {
    added: 4,
    updated: 2,
    moved: 1,
    deleted: 0,
    total: 7,
  })
})

test('old direct tasks aggregate commit batches once and do not double count draft frames', () => {
  const summary = resolveMindmapAiDirectChangeSummary({
    proposal: { impact: { direct: true } },
    jobId: 'job-2',
    events: [
      {
        jobId: 'job-2',
        eventType: 'draft_changed',
        payload: {
          changeSummary: { added: 3 },
          directCommit: { changeSummary: { added: 2, updated: 1 } },
        },
      },
      {
        jobId: 'job-2',
        eventType: 'draft_changed',
        payload: {
          changeSummary: { added: 4 },
          directCommit: { changeSummary: { moved: 1, deleted: 1 } },
        },
      },
    ],
  })
  assert.deepEqual(summary, {
    added: 2,
    updated: 1,
    moved: 1,
    deleted: 1,
    total: 5,
  })
})

test('proposal-shaped display impact receives direct counters while preserving review metadata', () => {
  const impact = directImpactForMindmapAiResult(
    { impact: { direct: true, highImpact: false } },
    { added: 1, updated: 0, moved: 2, deleted: 0, total: 3 },
  )
  assert.deepEqual(impact, {
    direct: true,
    highImpact: false,
    createdCount: 1,
    updatedCount: 0,
    movedCount: 2,
    deletedCount: 0,
    changeSummary: { added: 1, updated: 0, moved: 2, deleted: 0, total: 3 },
  })
})

test('terminal counters override a cached first-batch proposal with the same stable ID', () => {
  const summary = resolveMindmapAiDirectChangeSummary({
    proposal: { id: 'job-1', jobId: 'job-1', impact: { direct: true, changeSummary: { added: 8 } } },
    jobId: 'job-1',
    events: [{ jobId: 'job-1', eventType: 'direct_completed', payload: { changeSummary: { added: 84 } } }],
  })
  assert.deepEqual(summary, { added: 84, updated: 0, moved: 0, deleted: 0, total: 84 })
})

test('legacy flat proposal impact counters are supported without requiring changeSummary nesting', () => {
  assert.deepEqual(resolveMindmapAiDirectChangeSummary({
    proposal: { jobId: 'job-1', impact: { direct: true, createdCount: 8, updatedCount: 2, movedCount: 1, deletedCount: 0 } },
    jobId: 'job-1',
  }), { added: 8, updated: 2, moved: 1, deleted: 0, total: 11 })
})

test('a previous job proposal cannot override the current job counters', () => {
  assert.deepEqual(resolveMindmapAiDirectChangeSummary({
    proposal: { jobId: 'old-job', impact: { changeSummary: { added: 999 } } },
    jobId: 'current-job',
    events: [
      { jobId: 'old-job', eventType: 'direct_completed', payload: { changeSummary: { added: 999 } } },
      { jobId: 'current-job', eventType: 'draft_changed', payload: { directCommit: { changeSummary: { added: 8 } } } },
    ],
  }), { added: 8, updated: 0, moved: 0, deleted: 0, total: 8 })
})

test('batch fallback ignores idempotent replay and counts an operation group only once', () => {
  const event = (group, count, replay = false) => ({
    jobId: 'job-1', eventType: 'draft_changed', payload: {
      changeSummary: { added: count },
      directCommit: { operationGroupId: group, idempotentReplay: replay, changeSummary: { added: count } },
    },
  })
  assert.deepEqual(resolveMindmapAiDirectChangeSummary({
    jobId: 'job-1',
    events: [event('first', 8, true), event('first', 8), event('first', 8), event('second', 12), event('second', 12, true)],
  }), { added: 20, updated: 0, moved: 0, deleted: 0, total: 20 })
})

test('mixed old and new batches use each batch best counter source without dropping legacy batches', () => {
  assert.deepEqual(resolveMindmapAiDirectChangeSummary({
    jobId: 'job-1',
    events: [
      { jobId: 'job-1', sequence: 1, eventType: 'draft_changed', payload: { changeSummary: { added: 8 } } },
      { jobId: 'job-1', sequence: 1, eventType: 'draft_changed', payload: { changeSummary: { added: 8 } } },
      { jobId: 'job-1', sequence: 2, eventType: 'draft_changed', payload: { changeSummary: { added: 99 }, directCommit: { operationGroupId: 'second', changeSummary: { added: 12 } } } },
      { jobId: 'job-1', sequence: 3, eventType: 'draft_changed', payload: { changeSummary: { added: 8 }, directCommit: { idempotentReplay: true } } },
    ],
  }), { added: 20, updated: 0, moved: 0, deleted: 0, total: 20 })
})

test('empty and nonnumeric counters are unavailable rather than fabricated zero counts', () => {
  assert.equal(resolveImpact({ added: null, updated: false, moved: '', deleted: [] }), null)
  assert.deepEqual(resolveImpact({ added: '0' }),
    { added: 0, updated: 0, moved: 0, deleted: 0, total: 0 })
})

test('a v2 net-node receipt supersedes an old v1 terminal operation-count summary', () => {
  assert.deepEqual(resolveMindmapAiDirectChangeSummary({
    jobId: 'job-1',
    proposal: { jobId: 'job-1', impact: { changeSummaryVersion: 2, changeSummary: { updated: 1 } } },
    events: [{ jobId: 'job-1', eventType: 'direct_completed', payload: { changeSummary: { updated: 2 } } }],
  }), { added: 0, updated: 1, moved: 0, deleted: 0, total: 1 })
})

test('within v2 a completed summary still supersedes a stale first-batch v2 receipt', () => {
  assert.deepEqual(resolveMindmapAiDirectChangeSummary({
    jobId: 'job-1',
    proposal: { jobId: 'job-1', impact: { changeSummaryVersion: 2, changeSummary: { added: 8 } } },
    events: [{ jobId: 'job-1', eventType: 'direct_completed', payload: { changeSummaryVersion: 2, changeSummary: { added: 84 } } }],
  }), { added: 84, updated: 0, moved: 0, deleted: 0, total: 84 })
})

test('a higher-version proposal from another job, or with no job identity, is ignored', () => {
  for (const proposalJobId of ['other-job', undefined]) {
    assert.deepEqual(resolveMindmapAiDirectChangeSummary({
      jobId: 'job-1',
      proposal: { jobId: proposalJobId, impact: { changeSummaryVersion: 2, changeSummary: { added: 999 } } },
      events: [{ jobId: 'job-1', eventType: 'direct_completed', payload: { changeSummary: { added: 8 } } }],
    }), { added: 8, updated: 0, moved: 0, deleted: 0, total: 8 })
  }
})
