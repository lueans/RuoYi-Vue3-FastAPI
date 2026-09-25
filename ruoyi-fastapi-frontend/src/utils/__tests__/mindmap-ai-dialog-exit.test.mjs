import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { babelParse, compileScript, parse } from '@vue/compiler-sfc'

const ref = value => ({ value })
const noop = () => {}
function component(path) {
  const descriptor = parse(readFileSync(new URL(path, import.meta.url), 'utf8')).descriptor
  const script = descriptor.scriptSetup.content
  const declarations = babelParse(script, { sourceType: 'module' }).program.body
  return { descriptor, declarations, compile(scope, names) {
    const bodies = names.map(name => {
      const node = declarations.find(item => item.type === 'FunctionDeclaration' && item.id.name === name)
      assert.ok(node, name)
      return script.slice(node.start, node.end)
    })
    return new Function('scope', `with(scope) { ${bodies.join('\n')} return { ${names.join(',')} }; }`)(scope)
  } }
}
const dialog = component('../../components/MindMap/MindmapAiDialog.vue')
const editor = component('../../components/MindMap/Edit.vue')
const page = component('../../views/mindmap/edit.vue')

test('离页保护接通页面、Edit 暴露方法和真实 Dialog 收尾，并等待保存结果', async () => {
  const pending = [editor.descriptor.template.ast]
  let mountedDialog
  while (pending.length) {
    const node = pending.pop()
    if (node.tag === 'MindmapAiDialog') mountedDialog = node
    pending.push(...(node.children || []))
  }
  assert.equal(mountedDialog.props.find(prop => prop.name === 'ref').value.content, 'mindmapAiDialogRef')
  const expose = editor.declarations.find(node => node.expression?.callee?.name === 'defineExpose')
  assert.ok(expose.expression.arguments[0].properties.some(prop => prop.key.name === 'finishCompletedAiGeneration'))
  assert.ok(compileScript(editor.descriptor, { id: 'navigation-test' }).bindings.finishCompletedAiGeneration)

  for (const saved of [false, true]) {
    let finishSave
    const warnings = []
    const child = dialog.compile({
      form: { sourceMode: 'current' }, messageModeActive: ref(false), running: ref(false),
      job: ref({ id: 'job', status: 'ready', proposalId: 'proposal' }), livePreviewSuppressedJobId: '',
      livePreviewAutoAcceptPromise: null, terminalHydrationState: ref('ready'),
      acceptCompletedLivePreviewByDefault: () => new Promise(resolve => { finishSave = resolve }),
    }, ['finishCompletedAiGeneration'])
    const parent = editor.compile({
      mindmapAiDialogRef: ref(child), terminalState: null, props: { mindmapId: null },
    }, ['finishCompletedAiGeneration', 'prepareForCloudExit'])
    const guard = page.compile({
      editRef: ref(parent), isReadonly: ref(false), ElMessage: { warning: value => warnings.push(value) },
    }, ['confirmEditorNavigation'])
    let settled = false
    const navigation = guard.confirmEditorNavigation().then(value => { settled = true; return value })
    await Promise.resolve()
    assert.equal(settled, false)
    finishSave(saved)
    assert.equal(await navigation, saved)
    assert.equal(warnings.length, saved ? 0 : 1)
  }
})

function deletionHarness(target) {
  const calls = []
  const s = {
    job: ref({ id: 'job', sessionId: 'session', status: 'running', target, executionMode: 'preview' }),
    recentSessions: ref([{ sessionId: 'session' }]), actionBusy: ref(false),
    livePreviewCanvasMutationBlocked: ref(false), directCanvasOwned: ref(false),
    preparingCanvas: ref(false), livePreviewActive: ref(false), livePreviewReverting: ref(false),
    uncertainCanvasCreation: ref(null), livePreviewGeneration: 1, proposalLoadGeneration: 0,
    realtimeGeneration: 0, realtimeReconnectAttempt: 0, realtimeController: { abort: () => calls.push('abort-sse') },
    pollController: { abort: () => calls.push('abort-poll') }, draftController: { abort: () => calls.push('abort-draft') },
    ElMessageBox: { confirm: async () => {} },
    ElMessage: { success: () => calls.push('success'), error: () => calls.push('error'), info: noop },
    beginActionIdentity: () => s.job.value.id,
    assertActionIdentity: id => { if (s.job.value?.id !== id) throw Object.assign(new Error(), { code: 'AI_ACTION_SUPERSEDED' }) },
    deleteMindmapAiSession: async () => {},
    invalidateActionIdentity: noop, invalidateRestoreOperations: noop, clearAgentRuntimeState: noop,
    clearStoredActiveJob: () => calls.push('clear-active'), clearStoredRecentJob: () => calls.push('clear-recent'),
    restoreDurableAttemptNotice: noop, formatMindmapAiError: error => error.message,
    emitAiCanvasPreviewEvent: () => assert.fail('a non-canvas deletion must not change the canvas'),
  }
  for (const key of ['deletingSession', 'directCanvasRecoveryJobId', 'directCanvasOwnerId', 'jobConfiguration',
    'proposal', 'proposalError', 'proposalLoading', 'diffConfirmed', 'runningPrompt', 'followupPrompt',
    'pendingFollowupPrompt', 'retryPrompt', 'currentSessionTitle', 'contextPickerVisible', 'sessionMenuVisible',
    'sourceContext', 'sourceFingerprint',
    'realtimeConnectionState']) s[key] = ref('')
  for (const key of ['pendingHandoffCanvasJobId', 'livePreviewPendingFrame', 'livePreviewOldestPendingAt',
    'livePreviewFlushTimer', 'livePreviewJobId', 'livePreviewEditorStarted', 'livePreviewRenderedDocument',
    'livePreviewBaselineDocument', 'livePreviewDirectSettlePromise', 'livePreviewDirectSettleJobId',
    'directTerminalTargetJobId', 'monitoringSuspendedJobId', 'livePreviewSuppressedJobId',
    'submitAttempt', 'saveCloudAttempt', 'followupAttempt', 'retryAttempt', 'queueAttempt',
    'realtimeReconnectTimer', 'pollTimer']) s[key] = null
  Object.defineProperty(s, 'running', { get: () => ref(s.job.value?.status === 'running') })
  return { s, calls, ...dialog.compile(s, ['deleteSessionRecord', 'resetNewJob', 'stopRealtime', 'stopPolling']) }
}

for (const target of ['message', 'file']) {
  test(`删除运行中的 ${target} 无需 SSE 终态也能清理，普通 reset 仍被禁止`, async () => {
    const h = deletionHarness(target)
    assert.equal(h.resetNewJob(), false)
    await h.deleteSessionRecord()
    assert.equal(h.s.job.value, null)
    assert.equal(h.s.running.value, false)
    assert.deepEqual(h.s.recentSessions.value, [])
    assert.deepEqual(h.calls, ['abort-sse', 'abort-poll', 'abort-draft', 'clear-active', 'clear-recent', 'success'])
  })
}

test('删除失败或迟到响应不能清除当前任务及其连接', async () => {
  for (const stale of [false, true]) {
    const h = deletionHarness('message')
    h.s.deleteMindmapAiSession = async () => {
      if (stale) h.s.job.value = { id: 'successor', sessionId: 'new-session', status: 'running' }
      else throw new Error('offline')
    }
    await h.deleteSessionRecord()
    assert.equal(h.s.job.value.id, stale ? 'successor' : 'job')
    assert.equal(h.s.running.value, true)
    assert.deepEqual(h.calls, stale ? [] : ['error'])
  }
})
