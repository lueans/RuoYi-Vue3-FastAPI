import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { installComposerAttachmentHarness } from './mindmap-composer-attachment-harness.mjs'
import { isDeviceAgent } from '../mindmap-agent-devices.js'
import { isMindmapExecutionBlocked } from '../mindmap-execution-state.js'
import { isMindmapAiMessageJob, resolveMindmapAiContextAvailability } from '../mindmap-ai-conversation.js'
import { fingerprintMindmapAiRequest, resolveMindmapAiRequestAttempt } from '../mindmap-ai-stream.js'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const declarations = babelParse(script, { sourceType: 'module' }).program.body
const copy = value => value == null ? value : JSON.parse(JSON.stringify(value))
const noop = () => {}

// Execute the production selection watcher as well as its handlers. A terminal
// transition must refresh without requiring another node_active event.
function compile(names, scope) {
  installComposerAttachmentHarness(scope)
  const selected = declarations.filter(node => names.includes(node.id?.name)
    || node.declarations?.some(item => names.includes(item.id?.name)))
  assert.equal(selected.length, names.length, `missing SFC declarations: ${names.join(', ')}`)
  const selectionWatch = declarations.find(node => node.type === 'ExpressionStatement'
    && node.expression.callee?.name === 'watch'
    && node.expression.arguments[0]?.type === 'ArrayExpression'
    && node.expression.arguments[0].elements.some(item => item?.name === 'composerContextLocked'))
  assert.ok(selectionWatch, 'the actual selection watcher must include the context lock')
  return new Function('scope', `with (scope) {
    ${selected.map(node => script.slice(node.start, node.end)).join('\n')}
    ${script.slice(selectionWatch.start, selectionWatch.end)}
    return { ${names.join(', ')} };
  }`)(scope)
}

function node(uid, text) {
  const data = { uid, text }
  return { getData: key => key === undefined ? data : data[key] }
}
const alpha = node('alpha', '模块甲')
const beta = node('beta', '模块乙')
const tree = { root: { data: { uid: 'root', text: '测试脑图' }, children: [
  { data: alpha.getData(), children: [] }, { data: beta.getData(), children: [] },
] } }

function harness({ sourceType = 'cloud_document', status = 'completed_direct' } = {}) {
  const parent = { id: 'parent', sessionId: 'session', turnIndex: 1, intent: 'expand',
    sourceType, status, executionState: 'stopped', sourceMindmapId: sourceType === 'cloud_document' ? 136 : null,
    ...(sourceType === 'local_snapshot' ? { proposalId: 'proposal', artifactId: 'artifact' } : {}) }
  const context = { mindmapId: parent.sourceMindmapId, documentId: 'document', revision: 2,
    documentHash: 'hash', readonly: false, selectedNodeUids: [], document: copy(tree) }
  const calls = { commands: [], sent: [], persisted: [], attempts: [], errors: [] }
  let attempts = {}
  const s = {
    props: { taskOnly: false },
    computed, ref, watch, form: reactive({ agentKey: 'codex', deviceId: '', modelId: null,
      intent: 'expand', sourceMode: 'current', scopeType: 'document', language: 'zh-CN',
      layout: 'logicalStructure', density: 'standard', generationMode: 'balanced', maxNodes: 50, maxDepth: 5 }),
    visible: ref(true), job: ref(copy(parent)), selectedTurn: ref(null), selectedTurnJobId: ref('parent'),
    restoringJob: ref(false), continuing: ref(false), livePreviewCanvasMutationBlocked: ref(false),
    selectedNodeUids: ref([]), selectedNodeLabels: ref({}), jobConfiguration: ref({
      sourceMode: 'current', scopeType: 'document', contextNodes: [], intent: 'expand',
    }),
    uploadedFileName: ref(''), editorContext: ref(copy(context)), sourceContext: ref(copy(context)),
    contextPickerVisible: ref(false), agentEvents: ref([]), discussionMode: ref(false),
    agents: ref([{ agentKey: 'codex', status: 'enabled', intents: ['expand'], inputTypes: [sourceType] }]),
    nativeModelConfigurationIssue: ref(''), agentSwitchPending: ref(false), selectedDeviceIssue: ref(''),
    continuationPrompt: ref('仅补充所选内容'), pendingFollowupPrompt: ref(''), sourceFingerprint: ref(''),
    sessionTurns: ref([]), draftDocument: ref(null), proposal: ref(null), proposalError: ref(''),
    diffConfirmed: ref(false), followupAttempt: null, monitoringSuspendedJobId: '', terminalHydrationRetryTimer: null,
    restoreGeneration: 1, intentOptions: [{ value: 'expand' }],
    isDeviceAgent, isMindmapExecutionBlocked, isMindmapAiMessageJob, resolveMindmapAiContextAvailability,
    fingerprintMindmapAiRequest, resolveMindmapAiRequestAttempt, cloneRuntimeValue: copy,
    composerDraftPersistence: { capture: prompt => ({ id: 'draft', text: prompt }), consume: noop },
    currentAiOwnerUserId: () => '1', beginActionIdentity: type => ({ type }), assertActionIdentity: noop,
    invalidateRestoreOperations: noop, stopPolling: noop, stopRealtime: noop, schedulePoll: noop,
    flushPendingCloudMutationIntents: async () => {}, listMindmapAiCloudMutationIntents: () => [],
    flushLocalApplyAcks: async () => {}, listMindmapAiLocalAcks: () => [],
    getMindmapAiJob: async () => ({ data: copy(parent) }),
    reconcileCloudMutationBeforeSource: async value => value,
    computeMindmapSnapshotFingerprint: async () => 'hash',
    readPersistedAttempts: () => copy(attempts),
    writePersistedAttempts: value => { attempts = copy(value); calls.attempts.push(copy(value)); return true },
    hashAttemptFingerprint: async value => value,
    createMindmapAiIdempotencyKey: () => 'request-key',
    prepareDirectCanvasRequest: async () => 'preparing:request-key', releaseCanvasPreparation: async () => true,
    adoptDirectCanvasRequest: async () => {},
    continueMindmapAiJob: async (parentId, payload, key) => {
      calls.sent.push({ parentId, payload: copy(payload), key })
      return { data: { ...parent, id: 'child', status: 'running', executionState: 'running', turnIndex: 2 } }
    },
    assertFollowupAttemptResult: value => value, appendClientPrompt: noop, upsertSessionTurn: noop,
    consumeSubmittedComposerDraft: noop, restoreDurableAttemptNotice: noop, beginJobMonitoring: noop,
    restoreSessionTimeline: async () => [], reconcileAgentSelection: noop,
    selectSourceFile: () => assert.fail('a follow-up cannot replace the source document'),
    formatMindmapAiError: error => error.message,
    ElMessage: { info: assert.fail, warning: assert.fail, error: message => { calls.errors.push(message) } },
    bus: { emit: (event, ...args) => {
      if (event === 'requestAiMindmapContext') { args[0].resolve(copy(context)); return true }
      calls.commands.push([event, ...args])
      return true
    } },
  }
  s.actionBusy = computed(() => s.restoringJob.value || s.continuing.value)
  s.effectiveFormIntent = computed(() => s.discussionMode.value ? 'discuss' : s.form.intent)
  s.persistActiveJob = () => { calls.persisted.push(copy(s.jobConfiguration.value)); return true }
  const lifetime = effectScope()
  const names = ['generationModeOptions', 'GENERATION_MODE_VALUES', 'terminalStatuses', 'running',
    'selectedArtifactJob', 'viewingHistoricalArtifact', 'followupParentJob', 'needsInputQuestions', 'followupAvailable',
    'taskConfigurationLocked', 'composerContextLocked', 'contextAvailability', 'composerContextNodes',
    'composerContextScope', 'currentContextLabel', 'composerContextTitle', 'syncComposerSelection',
    'contextNodeLabel', 'nodeUid', 'onEditorNodeActive', 'clearComposerSelection', 'selectComposerContext',
    'requestEditorContext', 'captureCanvasSelection', 'captureJobConfiguration', 'currentSourceType',
    'followupIntent', 'followupSourceType', 'followupContinuationBase', 'continueJob', 'activateFollowupJob',
    'isTerminalStatus', 'resolveDurableAttempt', 'clearDurableAttempt', 'upsertSessionTurn']
  const api = lifetime.run(() => compile(names, s))
  return { ...s, ...api, context, calls, bindings: s, stop: () => lifetime.stop() }
}

test('a completed direct turn follows single, multiple and cleared canvas selections without mutating its submitted configuration', async t => {
  const h = harness()
  t.after(h.stop)
  const submittedConfiguration = copy(h.jobConfiguration.value)
  assert.equal(h.taskConfigurationLocked.value, true, 'historical task parameters stay immutable')
  assert.equal(h.composerContextLocked.value, false, 'the next turn may choose its own scope')
  assert.equal(h.currentContextLabel.value, '整个脑图')
  h.onEditorNodeActive(alpha, [alpha])
  await nextTick()
  assert.equal(h.currentContextLabel.value, '模块甲')
  assert.equal(h.form.scopeType, 'branch')
  assert.equal(h.composerContextScope.value, 'one')
  h.onEditorNodeActive(beta, [alpha, beta])
  await nextTick()
  assert.equal(h.currentContextLabel.value, '用户已经选择2个节点')
  assert.equal(h.form.scopeType, 'selectedNodes')
  assert.equal(h.composerContextScope.value, 'multi')
  assert.equal(h.clearComposerSelection(), true)
  await nextTick()
  assert.deepEqual(h.calls.commands, [['execCommand', 'CLEAR_ACTIVE_NODE']])
  assert.equal(h.currentContextLabel.value, '整个脑图')
  assert.equal(h.form.scopeType, 'document')
  assert.deepEqual(copy(h.jobConfiguration.value), submittedConfiguration)
})

for (const status of ['completed_no_change', 'completed_message']) {
  test(`cloud ${status} without an artifact unlocks the next turn's canvas selection`, async t => {
    const h = harness({ status })
    t.after(h.stop)
    if (status === 'completed_message') {
      h.job.value.intent = 'discuss'
      h.job.value.target = 'message'
    }
    assert.equal(h.job.value.artifactId, undefined)
    assert.equal(h.followupAvailable.value, true)
    assert.equal(h.followupContinuationBase(), 'current_document')
    assert.equal(h.composerContextLocked.value, false)
    h.onEditorNodeActive(alpha, [alpha])
    await nextTick()
    assert.equal(h.currentContextLabel.value, '模块甲')
    assert.equal(h.form.scopeType, 'branch')
    assert.equal(h.followupIntent(), 'expand', 'the completed discussion does not force the next interaction mode')
    assert.equal(h.jobConfiguration.value.scopeType, 'document', 'the completed request stays immutable')
  })
}

test('running scope is frozen; completing and settling the canvas refreshes already-selected nodes without another event', async t => {
  const h = harness({ status: 'running' })
  t.after(h.stop)
  h.form.scopeType = 'branch'
  h.jobConfiguration.value = { scopeType: 'branch', contextNodes: [{ uid: 'original', label: '原请求节点' }] }
  h.livePreviewCanvasMutationBlocked.value = true
  h.onEditorNodeActive(beta, [alpha, beta])
  await nextTick()
  assert.equal(h.composerContextLocked.value, true)
  assert.equal(h.currentContextLabel.value, '原请求节点')
  assert.equal(h.form.scopeType, 'branch')
  h.job.value = { ...h.job.value, status: 'completed_direct', executionState: 'stopped' }
  await nextTick()
  assert.equal(h.composerContextLocked.value, true, 'terminal status alone does not release the canvas fence')
  h.livePreviewCanvasMutationBlocked.value = false
  await nextTick()
  assert.equal(h.composerContextLocked.value, false)
  assert.equal(h.currentContextLabel.value, '用户已经选择2个节点')
  assert.equal(h.form.scopeType, 'selectedNodes')
  assert.deepEqual(copy(h.jobConfiguration.value.contextNodes), [{ uid: 'original', label: '原请求节点' }])
})

for (const scenario of ['restoring', 'historical', 'needs_review', 'needs_input', 'standalone_artifact']) {
  test(`${scenario} never turns canvas selection into a new authorization`, async t => {
    const h = harness()
    t.after(h.stop)
    if (scenario === 'restoring') h.restoringJob.value = true
    if (scenario === 'historical') {
      h.selectedTurnJobId.value = 'older'
      h.selectedTurn.value = { job: { ...h.job.value, id: 'older', status: 'ready', artifactId: 'older-artifact' } }
    }
    if (scenario === 'needs_review' || scenario === 'needs_input') h.job.value.status = scenario
    if (scenario === 'needs_review') h.job.value.artifactId = 'review-artifact'
    if (scenario === 'needs_input') h.agentEvents.value = [{ jobId: 'parent', eventType: 'needs_input',
      payload: { questions: [{ questionId: 'q1', prompt: '需要补充哪个方向？' }] } }]
    if (scenario === 'standalone_artifact') h.job.value = { ...h.job.value, status: 'completed_file', sourceType: 'none', artifactId: 'artifact' }
    h.onEditorNodeActive(alpha, [alpha])
    await nextTick()
    assert.equal(h.composerContextLocked.value, true)
    assert.equal(h.currentContextLabel.value, '整个脑图')
    assert.equal(h.form.scopeType, 'document')
    assert.equal(h.clearComposerSelection(), false)
    assert.equal(h.selectComposerContext('branch'), false)
    assert.deepEqual(h.calls.commands, [])
    if (['historical', 'needs_input', 'standalone_artifact'].includes(scenario)) {
      assert.equal(h.followupAvailable.value, true, 'a resumable artifact or question is not authority to change canvas scope')
    }
    if (scenario === 'restoring') {
      h.restoringJob.value = false
      await nextTick()
      assert.equal(h.currentContextLabel.value, '模块甲', 'restoring a completed turn must unlock automatically')
    }
  })
}

test('an unlocked follow-up may change nodes but cannot switch to a new document or upload', t => {
  const h = harness()
  t.after(h.stop)
  assert.equal(h.selectComposerContext('new'), false)
  assert.equal(h.selectComposerContext('file'), false)
  assert.equal(h.form.sourceMode, 'current')
})

test('continuing a historical artifact never submits the current canvas selection as its scope', async t => {
  const h = harness()
  t.after(h.stop)
  h.selectedTurnJobId.value = 'older'
  h.selectedTurn.value = { job: { ...h.job.value, id: 'older', status: 'ready', artifactId: 'older-artifact' } }
  h.context.selectedNodeUids = ['alpha', 'beta']
  h.onEditorNodeActive(alpha, [alpha, beta])
  await nextTick()
  assert.equal(h.followupAvailable.value, true)
  assert.equal(h.composerContextLocked.value, true)
  await h.continueJob()
  assert.deepEqual(h.calls.errors, [])
  assert.equal(h.calls.sent.length, 1)
  assert.equal(h.calls.sent[0].parentId, 'older')
  assert.equal(h.calls.sent[0].payload.continuationBase, 'artifact')
  assert.equal(h.calls.sent[0].payload.artifactId, 'older-artifact')
  assert.equal(h.calls.sent[0].payload.scope, undefined)
  assert.deepEqual(h.calls.persisted[0].contextNodes, [])
})

for (const sourceType of ['cloud_document', 'local_snapshot']) {
  for (const selected of [[], [alpha], [alpha, beta]]) {
    test(`${sourceType} follow-up sends and persists the captured ${selected.length}-node scope despite later selection changes`, async t => {
      const h = harness({ sourceType, status: sourceType === 'cloud_document' ? 'completed_direct' : 'applied' })
      t.after(h.stop)
      const uids = selected.map(item => item.getData('uid'))
      const expectedScope = uids.length === 0 ? { type: 'document' }
        : uids.length === 1 ? { type: 'branch', rootUid: 'alpha' }
          : { type: 'selectedNodes', nodeUids: ['alpha', 'beta'] }
      const expectedNodes = selected.map(item => ({ uid: item.getData('uid'), label: item.getData('text') }))
      h.context.selectedNodeUids = uids
      h.onEditorNodeActive(selected[0], selected)
      h.composerAttachments.value = [{ id: 'original', name: '需求.txt', size: 64, mediaType: 'text/plain', text: '最初的附件内容', status: 'ready' }]
      await nextTick()
      let reachedCapture, resumeRequest
      const captured = new Promise(resolve => { reachedCapture = resolve })
      const gate = new Promise(resolve => { resumeRequest = resolve })
      // The production durable-attempt builder awaits this IO only after the
      // scope and its labels have both been captured from the same snapshot.
      h.bindings.hashAttemptFingerprint = async value => { reachedCapture(); await gate; return value }
      const sending = h.continueJob()
      await Promise.race([captured, sending.then(() => assert.fail(`send ended before capture: ${h.calls.errors.join(', ')}`))])
      assert.equal(h.continuing.value, true)
      assert.equal(h.pendingFollowupPrompt.value, '仅补充所选内容')
      assert.equal(h.pendingFollowupContext.value.scopeType, expectedScope.type)
      assert.deepEqual(copy(h.pendingFollowupContext.value.contextNodes), expectedNodes)
      assert.deepEqual(copy(h.pendingFollowupAttachments.value), [{ id: 'original', name: '需求.txt', size: 64,
        mediaType: 'text/plain', parsing: { status: 'parsed', characterCount: 7 } }])
      h.context.selectedNodeUids = ['beta']
      h.onEditorNodeActive(beta, [beta])
      h.composerAttachments.value[0].name = '改名后的附件.txt'
      h.composerAttachments.value[0].text = '输入草稿中新改的内容'
      h.continuationPrompt.value = '下一轮尚未发送的要求'
      await nextTick()
      assert.deepEqual(copy(h.pendingFollowupContext.value.contextNodes), expectedNodes)
      assert.equal(h.pendingFollowupAttachments.value[0].name, '需求.txt')
      resumeRequest()
      await sending
      await nextTick()
      assert.deepEqual(h.calls.errors, [])
      assert.equal(h.calls.sent.length, 1)
      const { parentId, payload, key } = h.calls.sent[0]
      assert.equal(parentId, 'parent')
      assert.equal(key, 'request-key')
      assert.deepEqual(payload.scope, expectedScope)
      assert.equal(payload.attachments[0].name, '需求.txt')
      assert.equal(payload.attachments[0].text, '最初的附件内容')
      assert.equal(payload.continuationBase, sourceType === 'cloud_document' ? 'current_document' : 'current_snapshot')
      if (sourceType === 'local_snapshot') {
        assert.equal(payload.expectedParentStatus, 'applied')
        assert.deepEqual(payload.source.document, tree, 'the full baseline stays available for scoped validation')
        assert.deepEqual(payload.source.scope, { type: 'document' })
      }
      const persistedAttempt = h.calls.attempts.find(item => item.followup)?.followup
      assert.deepEqual(persistedAttempt.requestPayload.scope, expectedScope)
      assert.equal(persistedAttempt.configuration.scopeType, expectedScope.type)
      assert.deepEqual(persistedAttempt.configuration.contextNodes, expectedNodes)
      assert.equal(h.calls.persisted.length, 1)
      assert.equal(h.calls.persisted[0].scopeType, expectedScope.type)
      assert.deepEqual(h.calls.persisted[0].contextNodes, expectedNodes)
      assert.equal(h.job.value.id, 'child')
      assert.equal(h.composerContextLocked.value, true)
      assert.equal(h.form.scopeType, expectedScope.type)
      assert.deepEqual(copy(h.jobConfiguration.value.contextNodes), expectedNodes)
      assert.equal(h.currentContextLabel.value, uids.length === 0 ? '整个脑图' : uids.length === 1 ? '模块甲' : '用户已经选择2个节点')
      const message = h.sessionTurns.value.find(turn => turn.job.id === 'child').userMessage
      assert.equal(message.context.scopeType, expectedScope.type)
      assert.deepEqual(copy(message.context.contextNodes), expectedNodes)
      assert.equal(message.content, '仅补充所选内容')
      assert.equal(message.attachments[0].name, '需求.txt')
      assert.ok(!Object.hasOwn(message.attachments[0], 'text'))
    })
  }
}
