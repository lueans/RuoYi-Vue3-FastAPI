import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const noop = () => {}
function functionSource(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
  assert(start >= 0, name)
  const rest = source.slice(start)
  const end = rest.slice(1).search(/\n(?:async )?function \w+\(/)
  assert(end >= 0, name)
  return rest.slice(0, end + 1)
}
function compile(scope, names) {
  return new Function('scope', `with(scope) { ${names.map(functionSource).join('\n')} return { ${names.join(', ')} }; }`)(scope)
}

for (const [method, attemptType] of [['submitJob', 'create'], ['retryJob', 'retry'], ['continueJob', 'followup']]) {
  for (const reused of [false, true]) {
    test(`${method} ${reused ? 'never drains a persisted unknown request' : 'drains human writes before a new request'}`, async () => {
      const prepared = []
      const parent = { id: 'parent', status: 'completed_direct', executionMode: 'direct',
        intent: 'expand', sourceType: 'cloud_document', sourceMindmapId: 1, sessionId: 'session', turnIndex: 1 }
      const context = { mindmapId: 1, readonly: false, document: { root: { data: { uid: 'root', text: 'human' } } } }
      const superseded = Object.assign(new Error('stop after observing the preparation request'), { code: 'AI_ACTION_SUPERSEDED' })
      const s = {
        job: ref(method === 'submitJob' ? null : parent), followupParentJob: ref(parent),
        form: { prompt: '继续完善', agentKey: 'codex', intent: 'expand' },
        agents: ref([{ agentKey: 'codex', status: 'enabled', intents: ['expand'], inputTypes: ['cloud_document'] }]),
        nativeModelConfigurationIssue: ref(''), effectiveFormIntent: ref('expand'),
        messageModeActive: ref(false), discussionMode: ref(false), agentSupportsCurrentTask: () => true,
        restoringJob: ref(false), actionBusy: ref(false), livePreviewCanvasMutationBlocked: ref(false),
        submitting: ref(false), retrying: ref(false), continuing: ref(false), submissionStartedAt: ref(0),
        sourceContext: ref(context), editorContext: ref(context), sourceFingerprint: ref('hash'),
        submitAttempt: null, retryAttempt: null, followupAttempt: null, jobConfiguration: ref({}),
        retryAvailable: ref(true), retryPrompt: ref(''), followupPrompt: ref('继续完善'), pendingFollowupPrompt: ref(''),
        sessionTurns: ref([]), monitoringSuspendedJobId: '', terminalHydrationRetryTimer: null,
        beginActionIdentity: () => ({}), assertActionIdentity: noop, invalidateRestoreOperations: noop,
        stopPolling: noop, stopRealtime: noop, schedulePoll: noop,
        isDirectExecutionJob: () => true, isMindmapAiMessageJob: () => false,
        buildSource: async () => ({ type: 'cloud_document', mindmapId: 1 }),
        effectiveRequestLayout: () => 'logicalStructure', captureJobConfiguration: value => value,
        readPersistedAttempts: () => reused ? { [attemptType]: { key: 'key' } } : {},
        resolveDurableAttempt: async () => ({ key: 'key' }), createMindmapAiIdempotencyKey: () => 'key',
        followupIntent: () => 'expand', followupSourceType: () => 'cloud_document', followupContinuationBase: () => 'current_document',
        currentAiOwnerUserId: () => 'owner', listMindmapAiCloudMutationIntents: () => [],
        flushPendingCloudMutationIntents: async () => true, requestEditorContext: async () => context,
        reconcileCloudMutationBeforeSource: async value => value, computeMindmapSnapshotFingerprint: async () => 'hash',
        preparingCanvas: ref(false), directCanvasOwnerId: ref(''),
        emitEditorRequest: async (event, payload) => {
          prepared.push({ event, payload })
          throw superseded
        },
        releaseCanvasPreparation: async () => true,
        ElMessage: { info: assert.fail, warning: assert.fail, error: assert.fail },
      }
      const api = compile(s, [method, 'prepareDirectCanvasRequest'])
      await api[method]()
      assert.deepEqual(prepared, [{ event: 'aiDraftPreview', payload: {
        phase: 'prepare', jobId: 'preparing:key', directCommitted: true, drainLocalChanges: !reused,
      } }])
    })
  }
}

test('unknown-create recovery defaults to presentation fencing, not a local save', async () => {
  const events = []
  const s = {
    preparingCanvas: ref(false), directCanvasOwnerId: ref(''),
    emitEditorRequest: async (_event, payload) => events.push(payload),
    releaseCanvasPreparation: async () => assert.fail('successful preparation cannot be released'),
  }
  await compile(s, ['prepareDirectCanvasRequest']).prepareDirectCanvasRequest('persisted-key')
  assert.equal(events[0].drainLocalChanges, false)
})
