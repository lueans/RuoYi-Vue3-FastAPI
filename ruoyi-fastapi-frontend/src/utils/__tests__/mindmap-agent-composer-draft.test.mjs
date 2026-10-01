import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { computed, reactive, ref } from 'vue'
import { installComposerAttachmentHarness } from './mindmap-composer-attachment-harness.mjs'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const nodes = babelParse(script, { sourceType: 'module' }).program.body
function compile(names, scope) {
  installComposerAttachmentHarness(scope)
  const selected = nodes.filter(node => names.includes(node.id?.name)
    || node.declarations?.some(declaration => names.includes(declaration.id?.name)))
  assert.equal(selected.length, names.length, `missing production declarations: ${names.join(', ')}`)
  return new Function('scope', `with (scope) { ${selected.map(node => script.slice(node.start, node.end)).join('\n')}; return { ${names.join(', ')} }; }`)(scope)
}

function composer() {
  const scope = {
    ref, computed, form: reactive({ prompt: '' }), job: ref({ id: 'parent', status: 'running' }),
    followupAvailable: ref(false), actionBusy: ref(false), livePreviewCanvasMutationBlocked: ref(false),
    executionStopBlocked: ref(false), agentSwitchPending: ref(false), agentSwitchPhase: ref(''), restoreError: ref(''), selectedAgentReady: ref(true),
    restoringJob: ref(false), sessionSwitching: ref(false), deletingSession: ref(false), submitting: ref(false), openingLocal: ref(false),
    composerDraftPersistence: { update() {} }, readPersistedAttempts: () => ({}),
  }
  const api = compile(['continuationPrompt', 'terminalStatuses', 'retryableStatuses', 'running', 'retryAvailable',
    'composerText', 'composerEnabled', 'composerCanSend'], scope)
  return { ...scope, ...api }
}

test('writing a draft is independent from sending, stopping and canvas ownership', () => {
  const h = composer()
  const { composerEditable } = compile(['composerEditable'], h)
  h.composerText.value = '下一条要求'
  for (const flag of ['actionBusy', 'executionStopBlocked', 'agentSwitchPending', 'livePreviewCanvasMutationBlocked']) {
    h[flag].value = true
    h.job.value = { id: 'parent', status: 'completed_direct' }
    assert.equal(composerEditable.value, true, flag)
    assert.equal(h.composerCanSend.value, false, flag)
    h.composerText.value += '，可以继续写'
    h[flag].value = false
  }
  for (const flag of ['restoringJob', 'sessionSwitching', 'deletingSession', 'submitting', 'openingLocal']) {
    h[flag].value = true
    assert.equal(composerEditable.value, false, `${flag} has an unsettled identity`)
    h[flag].value = false
  }
  const input = source.slice(source.indexOf('ref="composerInputRef"'), source.indexOf('<div v-if="running" class="composerRoutePicker"'))
  assert.match(input, /:disabled="!composerEditable"/)
  assert.doesNotMatch(input, /:disabled="!composerEnabled"|:disabled="actionBusy"/)
})

test('draft-only feedback explains the gate without promising an automatic send', () => {
  const h = composer()
  const editable = compile(['composerEditable'], h)
  const { composerDraftOnlyHint } = compile(['composerDraftOnlyHint'], { ...h, ...editable })
  assert.equal(composerDraftOnlyHint.value, '')
  h.executionStopBlocked.value = true
  assert.match(composerDraftOnlyHint.value, /尚未确认停止.*不会自动发送/)
  h.executionStopBlocked.value = false
  h.agentSwitchPending.value = true
  assert.match(composerDraftOnlyHint.value, /切换 Agent.*不会自动发送/)
  h.agentSwitchPhase.value = '同步脑图结果'
  assert.match(composerDraftOnlyHint.value, /同步脑图结果.*不会自动发送/)
  h.agentSwitchPending.value = false
  h.actionBusy.value = true
  assert.match(composerDraftOnlyHint.value, /暂不能发送.*继续编写/)
  h.sessionSwitching.value = true
  assert.equal(composerDraftOnlyHint.value, '', 'an unsettled identity must not invite drafting')
})

test('unsent running text survives terminal hydration, canvas reconciliation and follow-up', () => {
  const h = composer()
  h.composerText.value = '继续补充密码过期的边界条件\n不要删除原有节点'
  const draft = h.composerText.value
  h.job.value = { id: 'parent', status: 'completed_direct' }
  h.livePreviewCanvasMutationBlocked.value = true
  assert.equal(h.composerText.value, draft, 'terminal hydration must not hide the draft')
  assert.equal(h.composerCanSend.value, false)
  h.followupAvailable.value = true
  assert.equal(h.composerText.value, draft)
  assert.equal(h.composerCanSend.value, false, 'typing state cannot bypass the canvas fence')
  h.livePreviewCanvasMutationBlocked.value = false
  assert.equal(h.composerCanSend.value, true)
  assert.equal(h.composerText.value, draft)
})

for (const status of ['cancelled', 'failed', 'expired', 'stale']) {
  test(`unsent running text survives ${status} and remains the explicit retry requirement`, () => {
    const h = composer()
    h.composerText.value = '保留已完成部分，只补充缺失内容'
    h.actionBusy.value = true
    h.executionStopBlocked.value = true
    h.job.value = { id: 'parent', status: 'cancel_requested' }
    assert.equal(h.composerCanSend.value, false)
    h.job.value = { id: 'parent', status }
    assert.equal(h.composerText.value, '保留已完成部分，只补充缺失内容')
    h.actionBusy.value = false
    assert.equal(h.composerCanSend.value, false, 'unconfirmed exit still blocks sending')
    h.executionStopBlocked.value = false
    assert.equal(h.composerCanSend.value, true)
  })
}

test('a terminal state with no send action keeps draft visible without enabling send', () => {
  const h = composer()
  h.composerText.value = '尚未发送的草稿'
  for (const status of ['ready', 'needs_review', 'rejected', 'needs_input']) {
    h.job.value = { id: 'parent', status }
    assert.equal(h.composerText.value, '尚未发送的草稿', status)
    assert.equal(h.composerCanSend.value, false, status)
  }
})

test('changing next Agent or temporarily losing readiness does not switch draft storage', () => {
  const h = composer()
  h.composerText.value = '给下一位 Agent 的接续要求'
  h.job.value = { id: 'parent', status: 'completed_direct' }
  h.followupAvailable.value = true
  h.agentSwitchPending.value = true
  assert.equal(h.composerCanSend.value, false)
  assert.equal(h.composerText.value, '给下一位 Agent 的接续要求')
  h.agentSwitchPending.value = false
  h.selectedAgentReady.value = false
  assert.equal(h.composerCanSend.value, false)
  h.selectedAgentReady.value = true
  assert.equal(h.composerCanSend.value, true)
  assert.equal(h.composerText.value, '给下一位 Agent 的接续要求')
})

function activationComposer() {
  const h = composer()
  const noop = () => {}
  const scope = {
    ...h, assertActionIdentity: noop, adoptDirectCanvasRequest: async () => {},
    cloneRuntimeValue: structuredClone, draftDocument: ref(null), stopPolling: noop, stopRealtime: noop,
    monitoringSuspendedJobId: '', isMindmapAiMessageJob: () => false, intentOptions: [{ value: 'expand' }],
    jobConfiguration: ref({ intent: 'expand' }), discussionMode: ref(false), captureJobConfiguration: value => value,
    sourceContext: ref(null), sourceFingerprint: ref(''), selectedTurnJobId: ref(''),
    pendingFollowupPrompt: ref(''), proposal: ref(null), proposalError: ref(''), diffConfirmed: ref(false),
    followupAttempt: null, retryAttempt: null, appendClientPrompt: noop, upsertSessionTurn: noop,
    persistActiveJob: () => true, clearDurableAttempt: noop, restoreDurableAttemptNotice: noop,
    beginJobMonitoring: noop, schedulePoll: noop, restoreSessionTimeline: async () => true,
    restoreGeneration: 1, sessionTurns: ref([]),
  }
  return { ...scope, ...compile(['consumeSubmittedComposerDraft', 'isTerminalStatus',
    'activateFollowupJob', 'activateRetryJob'], scope) }
}

for (const text of ['已经排队的要求', '正在写的另一条要求']) {
  test(`automatic queued-child activation preserves an unsent draft: ${text}`, async () => {
    const h = activationComposer()
    h.composerText.value = text
    const child = { id: 'child', status: 'running', intent: 'expand', sourceType: 'none', sessionId: 'session' }
    assert.equal(await h.activateFollowupJob(child, {
      identity: { type: 'queue-activate' }, requestPayload: { prompt: '已经排队的要求', agentKey: 'claude' }, attemptKey: '',
    }), true)
    assert.equal(h.job.value.id, 'child')
    assert.equal(h.composerText.value, text, 'queue handoff has no authority to consume the composer')
  })
}

for (const method of ['activateFollowupJob', 'activateRetryJob']) {
  for (const changed of [false, true]) {
    test(`${method} cannot consume a legacy unversioned draft, newer draft changed=${changed}`, async () => {
      const h = activationComposer()
      h.composerText.value = changed ? '新的接续要求' : '  已提交的要求\n'
      assert.equal(await h[method]({ id: 'child', status: 'running', sourceType: 'none', sessionId: 'session' }, {
        identity: { type: 'followup' }, requestPayload: { prompt: '已提交的要求', agentKey: 'claude' }, attemptKey: '',
        retryOfJob: { id: 'parent' },
      }), true)
      assert.equal(h.composerText.value, changed ? '新的接续要求' : '  已提交的要求\n')
    })
  }
}

test('submission dispatch reads the surviving draft after the run has already completed', async () => {
  const h = composer()
  const sent = []
  const scope = { ...h, submitJob: () => assert.fail('not a new conversation'),
    queueRunningMessage: () => assert.fail('parent is terminal'),
    continueJob: async () => sent.push({ kind: 'followup', prompt: h.continuationPrompt.value }),
    retryJob: async () => sent.push({ kind: 'retry', prompt: h.continuationPrompt.value }) }
  const { sendComposerMessage } = compile(['sendComposerMessage'], scope)
  h.composerText.value = '只补充边界用例'
  h.job.value = { id: 'parent', status: 'completed_direct' }
  h.followupAvailable.value = true
  await sendComposerMessage()
  h.job.value = { id: 'parent', status: 'cancelled' }
  await sendComposerMessage()
  h.executionStopBlocked.value = true
  await sendComposerMessage()
  assert.deepEqual(sent, [
    { kind: 'followup', prompt: '只补充边界用例' }, { kind: 'retry', prompt: '只补充边界用例' },
  ])
})
