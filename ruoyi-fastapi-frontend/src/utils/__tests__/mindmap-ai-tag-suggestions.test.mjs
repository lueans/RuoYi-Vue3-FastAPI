import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compile } from '@vue/compiler-dom'
import * as Vue from 'vue'
import { renderToString } from '@vue/server-renderer'
import { buildMindmapAiConversationTurns } from '../mindmap-ai-conversation.js'
import {
  collectMindmapAiTagSuggestions,
  sanitizeMindmapAiTagSuggestionsPayload,
} from '../mindmap-ai-tag-suggestions.js'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const event = (suggestions, sequence = 1, jobId = 'job-1') => ({
  eventType: 'tag_suggestions', jobId, sequence, payload: sanitizeMindmapAiTagSuggestionsPayload({ suggestions }),
})
const suggestion = (name = '重要', nodeUids = ['node-1'], reason = '需要重点检查') => ({ name, reason, nodeUids })

test('suggestion payload whitelists display fields and rejects malformed values', () => {
  const safe = sanitizeMindmapAiTagSuggestionsPayload({
    suggestions: [null, [], { name: 4 }, { name: ' ' }, {
      ...suggestion('  重要\n标签\u0000  ', ['node-1', 'node-1', 7, ' ', '\u0000bad', 'x'.repeat(65)]),
      autoCreate: true,
    }],
    directCommit: { affectedUids: ['private'] }, affectedUids: ['private'], secret: 'drop',
  })
  assert.deepEqual(safe, {
    suggestions: [{ name: '重要 标签', reason: '需要重点检查', nodeUids: ['node-1'], nodeUidsTruncated: false }],
    truncated: false,
  })
  assert.deepEqual(sanitizeMindmapAiTagSuggestionsPayload(null), { suggestions: [], truncated: false })
})

test('suggestions are isolated to their job and never inferred from other event payloads', () => {
  const events = [event([suggestion()]), event([suggestion('另一轮')], 2, 'job-2'), {
    ...event([suggestion('非建议')]), eventType: 'draft_changed',
  }]
  assert.deepEqual(collectMindmapAiTagSuggestions(events, 'job-1').items.map(item => item.name), ['重要'])
  assert.deepEqual(collectMindmapAiTagSuggestions(events, 'job-2').items.map(item => item.name), ['另一轮'])
  assert.deepEqual(collectMindmapAiTagSuggestions(events, 'job-3'), { items: [], truncated: false })
  assert.deepEqual(collectMindmapAiTagSuggestions(events, null), { items: [], truncated: false })
})

test('replayed and late historical events deduplicate names and targets in server sequence order', () => {
  const early = event([suggestion(' Priority ', ['one'], '旧说明')], 1)
  const latest = event([suggestion('ＰＲＩＯＲＩＴＹ', ['two', 'one'], '最新说明')], 4)
  const result = collectMindmapAiTagSuggestions([latest, early, early, latest], 'job-1')
  assert.equal(result.items.length, 1)
  assert.equal(result.items[0].reason, '最新说明')
  assert.deepEqual(result.items[0].nodeUids, ['one', 'two'])
  assert.equal(result.truncated, false)
})

test('event and turn limits are bounded and disclose truncation', () => {
  const oversized = sanitizeMindmapAiTagSuggestionsPayload({ suggestions: Array.from({ length: 11 }, (_, index) => (
    suggestion(`name-${index}`, Array.from({ length: 201 }, (_, id) => `node-${id}`), '🧠'.repeat(501))
  )) })
  assert.equal(oversized.suggestions.length, 10)
  assert.equal(Array.from(oversized.suggestions[0].reason).length, 500)
  assert.equal(oversized.suggestions[0].nodeUids.length, 200)
  assert.equal(oversized.suggestions[0].nodeUidsTruncated, true)
  assert.equal(oversized.truncated, true)
  const longName = sanitizeMindmapAiTagSuggestionsPayload({ suggestions: [suggestion('🧠'.repeat(101))] })
  assert.equal(Array.from(longName.suggestions[0].name).length, 100)
  assert.equal(longName.truncated, true)
  const events = [0, 1, 2].map(group => event(
    Array.from({ length: 10 }, (_, index) => suggestion(`name-${group * 10 + index}`)), group + 1,
  ))
  const result = collectMindmapAiTagSuggestions(events, 'job-1')
  assert.equal(result.items.length, 20)
  assert.equal(result.truncated, true)
  assert.equal(collectMindmapAiTagSuggestions([event(oversized.suggestions)], 'job-1').truncated, true)
})

test('merging repeated suggestions cannot grow target IDs beyond the display bound', () => {
  const result = collectMindmapAiTagSuggestions([
    event([suggestion('重要', Array.from({ length: 150 }, (_, index) => `a-${index}`))]),
    event([suggestion('重要', Array.from({ length: 150 }, (_, index) => `b-${index}`))], 2),
  ], 'job-1')
  assert.equal(result.items[0].nodeUids.length, 200)
  assert.equal(result.items[0].nodeUidsTruncated, true)
  assert.equal(result.truncated, true)
})

test('actual Dialog event ingestion restores suggestions without focusing or mutating the canvas', () => {
  const start = source.indexOf('function appendAgentEvent(')
  const end = source.indexOf('\nfunction appendClientPrompt(', start)
  const s = {
    agentEventKeys: new Set(), agentEventEnvelopeKeys: new Set(), jobEventSequences: new Map(),
    job: { value: { id: 'job-1' } }, latestEventSequence: { value: 0 }, agentEvents: { value: [] },
    buildMindmapAiTimelineEnvelopeKey: () => null, cloneRuntimeValue: structuredClone,
    sanitizeMindmapAiTagSuggestionsPayload, livePreviewEligible: { value: false },
    bus: { emit: () => assert.fail('suggestions must not enter the canvas focus path') },
  }
  const append = new Function('scope', `with (scope) { ${source.slice(start, end)}; return appendAgentEvent; }`)(s)
  const ingest = (jobId, sequence, name) => append(jobId, {
    eventType: 'tag_suggestions', data: { sequence, payload: {
      suggestions: [suggestion(name)], affectedUids: ['not-a-real-change'], directCommit: { affectedUids: ['also-not-real'] },
    } },
  })
  assert.equal(ingest('job-1', 3, '当前建议'), true)
  assert.equal(ingest('job-1', 3, '当前建议'), false)
  assert.equal(ingest('job-0', 1, '历史建议'), true)
  const turns = buildMindmapAiConversationTurns({
    sessionTurns: [{ job: { id: 'job-0', turnIndex: 1 } }],
    currentJob: { id: 'job-1', turnIndex: 2 }, events: s.agentEvents.value,
  }).map(turn => ({ ...turn, tagSuggestions: collectMindmapAiTagSuggestions(turn.events, turn.job.id) }))
  assert.deepEqual(turns.map(turn => turn.tagSuggestions.items[0].name), ['历史建议', '当前建议'])
  assert.equal(s.latestEventSequence.value, 3)
  assert.deepEqual(collectMindmapAiTagSuggestions([], 'new-job'), { items: [], truncated: false })
  assert.match(source, /tagSuggestions: collectMindmapAiTagSuggestions\(turn\.events, turn\.job\.id\)/)
})

test('actual historical restoration shares the one sanitizer boundary with SSE before aggregation', async () => {
  const appendStart = source.indexOf('function appendAgentEvent(')
  const appendEnd = source.indexOf('\nfunction appendClientPrompt(', appendStart)
  const restoreStart = source.indexOf('async function restoreSessionTimeline(')
  const restoreEnd = source.indexOf('\nfunction latestSessionTurn(', restoreStart)
  let sanitizedCount = 0
  const rawEvent = {
    eventType: 'tag_suggestions', sequence: 1,
    payload: { suggestions: [null, suggestion('  历史\u0000建议  ', ['node', 'node'])], affectedUids: ['unsafe'] },
  }
  const s = {
    agentEventKeys: new Set(), agentEventEnvelopeKeys: new Set(), jobEventSequences: new Map(),
    job: { value: { id: 'current', sessionId: 'session' } }, latestEventSequence: { value: 0 },
    agentEvents: { value: [] }, timelineLoadGeneration: 0, restoreGeneration: 1, timelineController: null,
    timelineLoading: { value: false }, timelineError: { value: '' }, currentSessionTitle: { value: '' },
    sessionTurns: { value: [] }, selectedTurnJobId: { value: '' }, restoringJob: { value: true },
    getMindmapAiSessionTimeline: async () => ({ data: { turns: [
      { job: { id: 'old', turnIndex: 1 }, events: [rawEvent, rawEvent] },
    ] } }),
    resolveMindmapAiSessionTitle: () => '恢复的会话', syncCurrentJobCursor: () => {},
    isAbortError: () => false, formatMindmapAiError: error => error.message,
    buildMindmapAiTimelineEnvelopeKey: () => null, cloneRuntimeValue: structuredClone,
    sanitizeMindmapAiTagSuggestionsPayload: payload => {
      sanitizedCount += 1
      return sanitizeMindmapAiTagSuggestionsPayload(payload)
    },
    livePreviewEligible: { value: false },
    bus: { emit: () => assert.fail('historical suggestions must not enter canvas focus') },
  }
  const { restoreSessionTimeline, appendAgentEvent } = new Function('scope', `with (scope) {
    ${source.slice(appendStart, appendEnd)}
    ${source.slice(restoreStart, restoreEnd)}
    return { restoreSessionTimeline, appendAgentEvent };
  }`)(s)
  await restoreSessionTimeline('session')
  assert.equal(s.timelineError.value, '')
  assert.equal(sanitizedCount, 1)
  assert.equal(appendAgentEvent('old', { eventType: 'tag_suggestions', data: rawEvent }), false)
  assert.equal(sanitizedCount, 1)
  const snapshot = structuredClone(s.agentEvents.value)
  const restored = collectMindmapAiTagSuggestions(s.agentEvents.value, 'old')
  assert.equal(restored.items[0].name, '历史 建议')
  assert.deepEqual(restored.items[0].nodeUids, ['node'])
  assert.deepEqual(collectMindmapAiTagSuggestions(s.agentEvents.value, 'current').items, [])
  assert.deepEqual(s.agentEvents.value, snapshot)
})

test('shared busy computation still blocks playback for every in-flight action', () => {
  const busyStart = source.indexOf('const mutationActionBusy = computed(')
  const busyEnd = source.indexOf('\nconst reasoningMode =', busyStart)
  const playbackStart = source.indexOf('const livePreviewPlaybackAvailable = computed(')
  const playbackEnd = source.indexOf('\nconst livePreviewCanvasMutationBlocked =', playbackStart)
  const flags = [
    'restoringJob', 'submitting', 'cancelling', 'savingCloud', 'applying', 'rejectingReview',
    'continuing', 'retrying', 'openingLocal', 'replacingLocal', 'insertingLocal', 'undoing',
    'deletingSession', 'sessionSwitching',
  ]
  const s = {
    ...Object.fromEntries(flags.map(flag => [flag, Vue.ref(false)])), computed: Vue.computed,
    livePreviewActive: Vue.ref(true), livePreviewJobId: 'job', job: Vue.ref({ id: 'job' }),
    running: Vue.ref(true), livePreviewCatchingUp: Vue.ref(false), livePreviewReverting: Vue.ref(false),
  }
  const { actionBusy, livePreviewPlaybackAvailable } = new Function('scope', `with (scope) {
    ${source.slice(busyStart, busyEnd)}
    ${source.slice(playbackStart, playbackEnd)}
    return { actionBusy, livePreviewPlaybackAvailable };
  }`)(s)
  assert.equal(livePreviewPlaybackAvailable.value, true)
  for (const flag of flags) {
    s[flag].value = true
    assert.equal(actionBusy.value, true, flag)
    assert.equal(livePreviewPlaybackAvailable.value, false, flag)
    s[flag].value = false
  }
  assert.equal(livePreviewPlaybackAvailable.value, true)
})

test('actual suggestion template is plain text with no automatic action and labels bounded results', async () => {
  const start = source.indexOf('<section v-if="turn.tagSuggestions.items.length"')
  const end = source.indexOf('</section>', start) + '</section>'.length
  const template = source.slice(start, end)
  assert(start >= 0)
  assert.doesNotMatch(template, /v-html|@click|<button|<el-button/)
  const { code } = compile(template, { mode: 'function', prefixIdentifiers: true })
  const render = new Function('Vue', code)(Vue)
  const turn = { tagSuggestions: { ...collectMindmapAiTagSuggestions([
    event([suggestion('<img src=x onerror=alert(1)>', ['one'], '<script>bad()</script>')]),
  ], 'job-1'), truncated: true } }
  const html = await renderToString(Vue.createSSRApp({ render, data: () => ({ turn }) }))
  assert(html.includes('&lt;img'))
  assert(html.includes('&lt;script&gt;'))
  assert.doesNotMatch(html, /<img|<script/)
  assert(html.includes('未创建、未绑定'))
  assert(html.includes('不会自动创建或继续执行'))
  assert(html.includes('部分建议、说明或目标节点已省略'))
})
