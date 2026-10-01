import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { parse, babelParse } from '@vue/compiler-sfc'
import { effectScope, ref } from 'vue'
import { installComposerAttachmentHarness } from './mindmap-composer-attachment-harness.mjs'
import { useMindmapComposerDraft } from '../use-mindmap-composer-draft.js'
import { createMindmapComposerDraftStorage } from '../mindmap-agent-composer-storage.js'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const nodes = babelParse(script, { sourceType: 'module' }).program.body
const attachment = (id, draftRevision = `${id}-first`) => ({ id, name: `${id}.txt`, size: 64, mediaType: 'text/plain', text: `PRIVATE_${id}`, draftRevision, status: 'ready' })
function compile(names, scope) {
  installComposerAttachmentHarness(scope)
  const selected = nodes.filter(node => names.includes(node.id?.name))
  assert.equal(selected.length, names.length)
  return new Function('scope', `with (scope) { ${selected.map(node => script.slice(node.start, node.end)).join('\n')}; return { ${names.join(', ')} }; }`)(scope)
}

for (const newerText of ['下一条尚未发送的要求', '', '点击时的要求']) {
  test(`follow-up snapshots prompt and receipt before asynchronous canvas reads; newer draft=${JSON.stringify(newerText)}`, async () => {
    const noop = () => {}
    const rows = new Map()
    let draftId = 0, attempts = {}, resume
    const gate = new Promise(resolve => { resume = resolve })
    const draftScope = { ownerId: '1', documentKey: 'cloud:130', sessionId: 'session' }
    const repository = createMindmapComposerDraftStorage({ createId: () => `draft-${++draftId}`,
      storage: () => ({ getItem: key => rows.get(key) ?? null, setItem: (key, value) => rows.set(key, value), removeItem: key => rows.delete(key) }) })
    const text = ref('')
    const lifetime = effectScope()
    const draft = lifetime.run(() => useMindmapComposerDraft({ repository, scope: () => draftScope,
      ready: () => true, readText: () => text.value, writeText: value => { text.value = value } }))
    draft.update('点击时的要求')
    const originalId = repository.read(draftScope).id
    const parent = { id: 'parent', status: 'completed_direct', executionMode: 'direct', intent: 'expand',
      sourceType: 'cloud_document', sourceMindmapId: 130, sessionId: 'session', turnIndex: 1 }
    const context = { mindmapId: 130, document: { root: { data: { uid: 'root', text: '已有脑图' } } } }
    const sent = [], consumed = []
    const s = {
      job: ref(parent), followupParentJob: ref(parent), form: { agentKey: 'codex' },
      agents: ref([{ agentKey: 'codex', status: 'enabled', intents: ['expand'], inputTypes: ['cloud_document'] }]),
      nativeModelConfigurationIssue: ref(''), agentSwitchPending: ref(false), actionBusy: ref(false),
      livePreviewCanvasMutationBlocked: ref(false), continuing: ref(false), discussionMode: ref(false),
      composerContextLocked: ref(false), composerContextNodes: ref([]), jobConfiguration: ref({}),
      GENERATION_MODE_VALUES: new Set(['balanced']),
      continuationPrompt: text, pendingFollowupPrompt: ref(''), composerDraftPersistence: draft,
      sourceContext: ref(context), editorContext: ref(context), sourceFingerprint: ref(''),
      sessionTurns: ref([]), followupAttempt: null, monitoringSuspendedJobId: '', terminalHydrationRetryTimer: null,
      isMindmapExecutionBlocked: () => false, isDeviceAgent: () => false, isMindmapAiMessageJob: () => false,
      followupIntent: () => 'expand', followupSourceType: () => 'cloud_document', followupContinuationBase: () => 'current_document',
      beginActionIdentity: () => ({}), assertActionIdentity: noop, invalidateRestoreOperations: noop,
      stopPolling: noop, stopRealtime: noop, schedulePoll: noop,
      flushPendingCloudMutationIntents: () => gate, currentAiOwnerUserId: () => '1',
      listMindmapAiCloudMutationIntents: () => [], requestEditorContext: async () => context,
      reconcileCloudMutationBeforeSource: async value => value, computeMindmapSnapshotFingerprint: async () => 'hash',
      readPersistedAttempts: () => structuredClone(attempts),
      writePersistedAttempts: value => { attempts = structuredClone(value); return true },
      fingerprintMindmapAiRequest: JSON.stringify, hashAttemptFingerprint: async value => createHash('sha256').update(value).digest('hex'),
      resolveMindmapAiRequestAttempt: (_old, _payload, { createKey }) => ({ key: createKey() }),
      createMindmapAiIdempotencyKey: () => 'request-1', cloneRuntimeValue: structuredClone,
      isDirectExecutionJob: () => true, prepareDirectCanvasRequest: async () => 'preparing:request-1',
      releaseCanvasPreparation: async () => true,
      continueMindmapAiJob: async (_id, payload) => { sent.push(payload); return { data: { id: 'child' } } },
      assertFollowupAttemptResult: value => value,
      activateFollowupJob: async (_child, options) => {
        consumed.push(attempts.followup.composerDraft)
        api.consumeSubmittedComposerDraft(options.requestPayload.prompt, 'followup', options.attemptKey)
        s.consumeComposerAttachments(options.requestPayload.attachments)
      },
      clearDurableAttempt: noop,
      formatMindmapAiError: error => error.message,
      ElMessage: { info: assert.fail, warning: assert.fail, error: assert.fail },
    }
    const api = compile(['continueJob', 'resolveDurableAttempt', 'consumeSubmittedComposerDraft',
      'captureCanvasSelection', 'contextNodeLabel', 'captureJobConfiguration'], s)
    s.composerAttachments.value = [attachment('clicked')]
    try {
      const sending = api.continueJob()
      assert.equal(s.continuing.value, true)
      draft.update('')
      draft.update(newerText)
      s.composerAttachments.value = [attachment('clicked', 'clicked-reselected'), attachment('later')]
      resume()
      await sending
      assert.equal(sent.length, 1)
      assert.equal(sent[0].prompt, '点击时的要求', 'later typing must not rewrite the clicked request')
      assert.deepEqual(sent[0].attachments.map(item => item.id), ['clicked'])
      assert.equal(sent[0].attachments[0].draftRevision, 'clicked-first')
      assert.doesNotMatch(JSON.stringify(sent[0]), /draftRevision|clicked-first/)
      assert.deepEqual(s.composerAttachments.value.map(item => item.id), ['clicked', 'later'])
      assert.equal(s.composerAttachments.value[0].draftRevision, 'clicked-reselected')
      assert.doesNotMatch(JSON.stringify(attempts), /PRIVATE_/)
      assert.equal(consumed[0]?.id, originalId, 'same-text retyping must not become the old send receipt')
      assert.equal(text.value, newerText, 'the accepted send must not erase subsequent edits')
      assert.equal(repository.read(draftScope)?.text ?? '', newerText)
      assert.equal(s.continuing.value, false)
    } finally { lifetime.stop() }
  })
}

for (const newerText of ['下一条排队草稿', '', '点击时的要求']) {
  test(`queued send captures its draft before reconciling an earlier request; newer draft=${JSON.stringify(newerText)}`, async () => {
    const rows = new Map()
    let draftId = 0, attempts = {}, resume
    const gate = new Promise(resolve => { resume = resolve })
    const draftScope = { ownerId: '1', documentKey: 'cloud:130', sessionId: 'session' }
    const repository = createMindmapComposerDraftStorage({ createId: () => `draft-${++draftId}`,
      storage: () => ({ getItem: key => rows.get(key) ?? null, setItem: (key, value) => rows.set(key, value), removeItem: key => rows.delete(key) }) })
    const text = ref('')
    const lifetime = effectScope()
    const draft = lifetime.run(() => useMindmapComposerDraft({ repository, scope: () => draftScope,
      ready: () => true, readText: () => text.value, writeText: value => { text.value = value } }))
    draft.update('点击时的要求')
    const originalId = repository.read(draftScope).id
    const sent = [], receipts = []
    const s = {
      job: ref({ id: 'parent', sessionId: 'session', turnIndex: 1 }),
      form: { agentKey: 'codex' }, agents: ref([{ agentKey: 'codex', status: 'enabled' }]),
      continuationPrompt: text, composerDraftPersistence: draft, continuing: ref(false),
      agentSwitchPending: ref(false), runningMessageRoute: ref('next'), effectiveFormIntent: ref('expand'),
      jobConfiguration: ref({ sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'clicked-node', label: '点击排队时的节点' }] }),
      sessionTurns: ref([]), queueAttempt: null,
      isDeviceAgent: () => false, currentAiOwnerUserId: () => '1',
      beginActionIdentity: () => ({}), assertActionIdentity: () => {},
      reconcileQueuedCanvasRequest: () => gate,
      readPersistedAttempts: () => structuredClone(attempts),
      writePersistedAttempts: value => { attempts = structuredClone(value); return true },
      fingerprintMindmapAiRequest: JSON.stringify, hashAttemptFingerprint: async value => createHash('sha256').update(value).digest('hex'),
      resolveMindmapAiRequestAttempt: (_old, _payload, { createKey }) => ({ key: createKey() }),
      createMindmapAiIdempotencyKey: () => 'queue-1', cloneRuntimeValue: value => value == null ? value : JSON.parse(JSON.stringify(value)),
      continueMindmapAiJob: async (_id, payload) => {
        sent.push(payload)
        receipts.push(attempts.queue.composerDraft)
        return { data: { id: 'child' } }
      },
      assertFollowupAttemptResult: value => value, upsertSessionTurn: () => {}, appendClientPrompt: () => {},
      clearDurableAttempt: () => {}, restoreDurableAttemptNotice: () => {},
      formatMindmapAiError: error => error.message,
      ElMessage: { success: () => {}, info: assert.fail, warning: assert.fail, error: assert.fail },
    }
    const api = compile(['queueRunningMessage', 'resolveDurableAttempt', 'consumeSubmittedComposerDraft', 'upsertSessionTurn'], s)
    s.composerAttachments.value = [attachment('clicked')]
    try {
      const sending = api.queueRunningMessage()
      assert.equal(s.continuing.value, true)
      draft.update('')
      draft.update(newerText)
      s.jobConfiguration.value.contextNodes[0].label = '点击之后修改的节点'
      s.jobConfiguration.value.contextNodes.push({ uid: 'newer-node', label: '点击之后新选择的节点' })
      s.composerAttachments.value = [attachment('clicked', 'clicked-reselected'), attachment('later')]
      resume()
      assert.equal(await sending, true)
      assert.equal(sent.length, 1)
      assert.equal(sent[0].prompt, '点击时的要求')
      assert.deepEqual(sent[0].attachments.map(item => item.id), ['clicked'])
      assert.equal(sent[0].attachments[0].draftRevision, 'clicked-first')
      assert.doesNotMatch(JSON.stringify(sent[0]), /draftRevision|clicked-first/)
      assert.deepEqual(s.composerAttachments.value.map(item => item.id), ['clicked', 'later'])
      assert.equal(s.composerAttachments.value[0].draftRevision, 'clicked-reselected')
      assert.doesNotMatch(JSON.stringify(attempts), /PRIVATE_/)
      assert.deepEqual(attempts.queue.configuration.contextNodes, [{ uid: 'clicked-node', label: '点击排队时的节点' }])
      assert.deepEqual(s.sessionTurns.value[0].userMessage.context.contextNodes, [{ uid: 'clicked-node', label: '点击排队时的节点' }])
      assert.equal(text.value, newerText, 'acknowledging the queued send must preserve later typing, even identical text')
      assert.equal(receipts[0]?.id, originalId, 'the earlier send cannot acquire a later draft revision')
      assert.equal(repository.read(draftScope)?.text ?? '', newerText)
      assert.equal(s.continuing.value, false)
    } finally { lifetime.stop() }
  })
}
