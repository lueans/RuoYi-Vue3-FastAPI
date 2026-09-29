import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse, compileTemplate } from '@vue/compiler-sfc'
import { computed, reactive, ref, watch, effectScope, nextTick } from 'vue'
import { isDeviceAgent } from '../mindmap-agent-devices.js'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const nodes = babelParse(script, { sourceType: 'module' }).program.body

test('running composer placeholder follows the actual selected routing mode', () => {
  const scope = { computed, running: ref(true), messageModeActive: ref(false), runningMessageRoute: ref('current') }
  const { composerPlaceholder } = compile(['composerPlaceholder'], scope)
  assert.match(composerPlaceholder.value, /补充当前任务/)
  scope.runningMessageRoute.value = 'next'
  assert.match(composerPlaceholder.value, /排到下一轮/)
  scope.messageModeActive.value = true
  assert.match(composerPlaceholder.value, /排到下一轮/)
  scope.runningMessageRoute.value = 'current'
  assert.match(composerPlaceholder.value, /补充当前任务/)
})

function compile(names, scope) {
  const selected = nodes.filter(node => names.includes(node.id?.name)
    || node.declarations?.some(declaration => names.includes(declaration.id?.name)))
  assert.equal(selected.length, names.length)
  const body = selected.map(node => script.slice(node.start, node.end)).join('\n')
  return new Function('scope', `with (scope) { ${body}; return { ${names.join(', ')} }; }`)(scope)
}

function readiness(agent = { agentKey: 'codex', displayName: 'Codex', status: 'enabled', healthStatus: 'healthy' }) {
  const scope = {
    computed, isDeviceAgent,
    form: reactive({ agentKey: agent.agentKey }),
    selectedAgent: ref(agent), loadingAgents: ref(false), agentError: ref(''),
    modelRecovery: { loading: ref(false), error: ref('') },
    agentSelectionIssue: ref(''), selectedDeviceIssue: ref(''),
    formatEventTime: value => value, deviceAgentName: () => 'Claude', deviceBudgetNotice: () => '',
  }
  return { ...scope, ...compile([
    'selectedAgentReadinessTone', 'selectedAgentReadinessLabel', 'selectedAgentReadinessDescription',
  ], scope) }
}

test('selection errors override healthy connector state and remain reactive', () => {
  const state = readiness()
  assert.equal(state.selectedAgentReadinessTone.value, 'ready')
  state.agentSelectionIssue.value = '当前模型配置错误'
  assert.equal(state.selectedAgentReadinessTone.value, 'unavailable')
  assert.equal(state.selectedAgentReadinessDescription.value, '当前模型配置错误')
  assert.doesNotMatch(state.selectedAgentReadinessLabel.value, /已就绪|已检查/)
  state.agentSelectionIssue.value = ''
  assert.equal(state.selectedAgentReadinessTone.value, 'ready')
})

test('loading or failed capabilities cannot reuse a previous healthy badge', () => {
  const state = readiness()
  state.loadingAgents.value = true
  assert.equal(state.selectedAgentReadinessTone.value, 'pending')
  assert.equal(state.selectedAgentReadinessLabel.value, '正在检查 Agent 配置')
  state.loadingAgents.value = false
  state.agentError.value = '连接服务失败'
  assert.equal(state.selectedAgentReadinessTone.value, 'unavailable')
  assert.equal(state.selectedAgentReadinessDescription.value, '连接服务失败')
})

test('native connector health is not proof of the individual model being ready', () => {
  const state = readiness({ agentKey: 'native_mindmap', displayName: 'MindMap Agent', status: 'enabled', healthStatus: 'healthy' })
  assert.equal(state.selectedAgentReadinessTone.value, 'pending')
  assert.match(state.selectedAgentReadinessDescription.value, /当前模型.*运行前校验/)
  state.selectedAgent.value.healthStatus = 'unhealthy'
  state.selectedAgent.value.healthReason = '运行环境缺失'
  assert.equal(state.selectedAgentReadinessTone.value, 'unavailable')
  assert.equal(state.selectedAgentReadinessDescription.value, '运行环境缺失')
})

test('model refresh displays metadata loading without claiming authentication succeeded', () => {
  const state = readiness({ agentKey: 'native_mindmap', displayName: 'MindMap Agent', status: 'enabled', healthStatus: 'healthy' })
  state.modelRecovery.loading.value = true
  state.agentSelectionIssue.value = 'previous configuration issue'
  assert.equal(state.selectedAgentReadinessTone.value, 'pending')
  assert.equal(state.selectedAgentReadinessLabel.value, '正在重新读取模型配置')
  assert.match(state.selectedAgentReadinessDescription.value, /不会自动发送任务/)
  state.modelRecovery.loading.value = false
  assert.equal(state.selectedAgentReadinessTone.value, 'unavailable')
  state.agentSelectionIssue.value = ''
  assert.match(state.selectedAgentReadinessDescription.value, /运行前校验/)
})

test('a removed selected model remains unavailable until the user chooses another', () => {
  const scope = { computed, form: reactive({ agentKey: 'native_mindmap', modelId: 2 }), models: ref([{ modelId: 1 }]) }
  const state = compile(['nativeModelConfigurationIssue'], scope)
  assert.match(state.nativeModelConfigurationIssue.value, /已不可用.*不会自动替换/)
  assert.equal(scope.form.modelId, 2)
  scope.form.modelId = 1
  assert.equal(state.nativeModelConfigurationIssue.value, '')
})

test('native sends are disabled throughout refresh and after a failed refresh', () => {
  const scope = { computed, isDeviceAgent, form: reactive({ agentKey: 'native_mindmap', modelId: 2 }),
    loadingAgents: ref(false), agentError: ref(''), agentPreferences: ref({ hidden: [] }),
    selectedAgent: ref({ agentKey: 'native_mindmap', status: 'enabled' }), agents: ref([]),
    agentSupportsCurrentTask: () => true, nativeModelConfigurationIssue: ref(''),
    modelRecovery: { loading: ref(true), error: ref('') } }
  const state = compile(['agentSelectionIssue', 'selectedAgentReady'], scope)
  assert.equal(state.selectedAgentReady.value, false)
  scope.modelRecovery.loading.value = false
  assert.equal(state.selectedAgentReady.value, true)
  scope.modelRecovery.error.value = '无法读取最新配置'
  assert.equal(state.selectedAgentReady.value, false)
  assert.equal(state.agentSelectionIssue.value, '无法读取最新配置')
  scope.modelRecovery.error.value = ''
  assert.equal(state.selectedAgentReady.value, true)
})

function panel(overrides = {}) {
  const scope = { computed, restoringJob: ref(false), submitting: ref(false), submissionStageTitle: ref('正在创建任务'),
    job: ref(null), executionStopBlocked: ref(false), cancelling: ref(false),
    directCanvasOwnerId: ref(''), livePreviewError: ref(''), restoreError: ref(''),
    connectionStateLabel: ref('实时运行'), realtimeConnectionState: ref('connected'),
    loadingAgents: ref(false), form: reactive({ agentKey: 'native_mindmap', modelId: 1 }),
    modelRecovery: { loading: ref(false) }, agentError: ref(''), nativeModelConfigurationIssue: ref(''),
    selectedAgentReadinessTone: ref('pending'), selectedAgentReady: ref(true),
    selectedAgentReadinessDescription: ref('认证将在运行前检查'), ...overrides }
  return { ...scope, ...compile(['terminalStatuses', 'isTerminalStatus', 'canvasSyncStatus', 'panelStatus'], scope) }
}

test('completed job cannot show all-done while its owned canvas is still recovering', () => {
  const state = panel({ job: ref({ id: 'run', status: 'completed_direct' }), directCanvasOwnerId: ref('run'),
    connectionStateLabel: ref('已完成'), realtimeConnectionState: ref('completed'),
    livePreviewError: ref('人工修改尚未保存，不能同步 AI 云端结果') })
  assert.equal(state.panelStatus.value.label, '画布待恢复')
  assert.equal(state.panelStatus.value.tone, 'warning')
  assert.equal(state.canvasSyncStatus.value.description, state.livePreviewError.value)
  assert.equal(state.canvasSyncStatus.value.canRetry, true)
  state.livePreviewError.value = ''
  assert.equal(state.panelStatus.value.label, '同步画布中')
  assert.equal(state.canvasSyncStatus.value.canRetry, false)
  state.directCanvasOwnerId.value = ''
  assert.equal(state.canvasSyncStatus.value, null)
  assert.equal(state.panelStatus.value.label, '已完成')
})

test('canvas recovery respects owner identity and gives stop confirmation precedence', () => {
  const state = panel({ job: ref({ id: 'run', status: 'running' }), directCanvasOwnerId: ref('other'), restoreError: ref('恢复草稿失败') })
  assert.equal(state.canvasSyncStatus.value, null)
  state.directCanvasOwnerId.value = 'run'
  assert.equal(state.canvasSyncStatus.value.description, '恢复草稿失败')
  state.executionStopBlocked.value = true
  assert.equal(state.canvasSyncStatus.value, null)
  assert.equal(state.panelStatus.value.label, '退出待确认')
  state.executionStopBlocked.value = false
  state.cancelling.value = true
  assert.equal(state.canvasSyncStatus.value, null)
  assert.equal(state.panelStatus.value.label, '停止中')
  state.cancelling.value = false
  state.restoreError.value = ''
  assert.equal(state.canvasSyncStatus.value, null, '正常运行不显示收尾同步状态')
})

test('canvas recovery explanation and existing retry remain beside the composer', () => {
  const footer = source.slice(source.indexOf('<template #footer>'), source.indexOf('</MindmapAgentPanel>'))
  assert.match(footer, /id="mindmap-ai-canvas-recovery"/)
  assert.match(footer, /canvasSyncStatus\.description/)
  assert.match(footer, /canvasSyncStatus\.canRetry[\s\S]*?:disabled="actionBusy \|\| restoringJob"[\s\S]*?@click="retryLivePreviewSync"/)
  assert.match(footer, /:aria-describedby="composerInputDescription"/)
  const scope = { computed, canvasSyncStatus: ref({}), composerDraftOnlyHint: ref('可先写草稿') }
  const { composerInputDescription } = compile(['composerInputDescription'], scope)
  assert.equal(composerInputDescription.value, 'mindmap-ai-canvas-recovery mindmap-ai-composer-draft-hint')
  scope.composerDraftOnlyHint.value = ''
  assert.equal(composerInputDescription.value, 'mindmap-ai-canvas-recovery')
  scope.canvasSyncStatus.value = null
  assert.equal(composerInputDescription.value, undefined)
})

test('idle panel distinguishes metadata checks, configuration failures and unverified authentication', () => {
  const state = panel()
  assert.equal(state.panelStatus.value.label, '运行前检查')
  assert.match(state.panelStatus.value.description, /运行前检查/)
  state.selectedAgentReadinessTone.value = 'ready'
  assert.equal(state.panelStatus.value.label, '待命')
  state.nativeModelConfigurationIssue.value = '提供商与接口不匹配'
  state.selectedAgentReady.value = false
  state.selectedAgentReadinessTone.value = 'unavailable'
  state.selectedAgentReadinessDescription.value = state.nativeModelConfigurationIssue.value
  assert.equal(state.panelStatus.value.label, '需配置')
  assert.equal(state.panelStatus.value.description, '提供商与接口不匹配')
  state.modelRecovery.loading.value = true
  assert.equal(state.panelStatus.value.label, '检查中')
  state.modelRecovery.loading.value = false
  state.agentError.value = '读取失败'
  assert.equal(state.panelStatus.value.label, '读取失败')
})

test('current task header ignores next-agent errors and preserves connection, preview and completion facts', () => {
  const state = panel({ job: ref({ id: 'run', status: 'running' }),
    selectedAgentReady: ref(false), selectedAgentReadinessTone: ref('unavailable'), agentError: ref('下一轮配置读取失败') })
  for (const [tone, label] of [['connected', '实时运行'], ['offline', '离线'], ['reconnecting', '正在重连'], ['completed', '已完成'], ['connected', '已暂停显示']]) {
    state.realtimeConnectionState.value = tone
    state.connectionStateLabel.value = label
    assert.deepEqual(state.panelStatus.value, { label, tone, description: '' })
  }
  state.job.value.status = 'cancel_requested'
  assert.equal(state.panelStatus.value.label, '停止中')
  state.job.value.status = 'cancelled'
  state.executionStopBlocked.value = true
  assert.equal(state.panelStatus.value.label, '退出待确认')
  assert.match(state.panelStatus.value.description, /不能发送下一轮或切换/)
  state.restoringJob.value = true
  assert.equal(state.panelStatus.value.label, '恢复中')
})

test('pre-submission and unavailable devices never inherit an idle ready label', () => {
  const state = panel({ form: reactive({ agentKey: 'device_claude' }), selectedAgentReady: ref(false),
    selectedAgentReadinessTone: ref('unavailable'), selectedAgentReadinessDescription: ref('执行电脑已离线') })
  assert.equal(state.panelStatus.value.label, '暂不可用')
  assert.equal(state.panelStatus.value.description, '执行电脑已离线')
  state.submitting.value = true
  assert.equal(state.panelStatus.value.label, '准备中')
  state.submitting.value = false
  state.loadingAgents.value = true
  assert.equal(state.panelStatus.value.label, '检查中')
})

test('compact composer preserves full policy and diagnostics, one management entry and the authoritative stop action', () => {
  assert.equal((source.match(/aria-label="管理 Agents"/g) || []).length, 0, 'Management remains in ExecutionPicker, not duplicated in the header')
  assert.match(source, /<MindmapAgentExecutionPicker[^>]+@manage="agentManagerVisible = true"/)
  assert.match(source, /<MindmapAgentWritePolicy[^>]+:description="composerPreflightText"[^>]+:active="visible"/)
  assert.match(source, /<MindmapAgentComposerIssue[\s\S]*?:description="agentSelectionIssue"[\s\S]*?@configure="openTaskSettings"/)
  assert.match(source, /<MindmapAgentStopButton[\s\S]*?:stopping="cancelling"[\s\S]*?:disabled="actionBusy && !cancelling"[\s\S]*?@stop="cancelJob"/)
  assert.doesNotMatch(source, /<VideoPause/)
  for (const name of ['MindmapAgentComposerIssue', 'MindmapAgentWritePolicy', 'MindmapAgentStopButton']) {
    const content = readFileSync(new URL(`../../components/MindMap/${name}.vue`, import.meta.url), 'utf8')
    const { descriptor, errors } = parse(content)
    assert.deepEqual(errors, [])
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: `${name}.vue`, id: name }).errors, [])
    assert.doesNotMatch(content, /v-html|fetch\(|localStorage|sessionStorage|setInterval/)
  }
  const issue = readFileSync(new URL('../../components/MindMap/MindmapAgentComposerIssue.vue', import.meta.url), 'utf8')
  assert.match(issue, /<details :key="description"/)
  assert.match(issue, /<p>\{\{ description \}\}<\/p>/)
  const policy = readFileSync(new URL('../../components/MindMap/MindmapAgentWritePolicy.vue', import.meta.url), 'utf8')
  assert.match(policy, /v-if="active && description"/)
  assert.match(policy, /watch\(\[\(\) => props.active, \(\) => props.label, \(\) => props.description\], \(\) => \{ open.value = false \}\)/)
  const stop = readFileSync(new URL('../../components/MindMap/MindmapAgentStopButton.vue', import.meta.url), 'utf8')
  assert.match(stop, /aria-label="停止任务并保留已生成结果"/)
  assert.match(stop, /:loading="stopping" :disabled="disabled" @click="\$emit\('stop'\)"/)
  assert.match(stop, /stopping \? '停止中' : '停止'/)
})

test('write-policy popover closes when the panel hides or its actual policy changes', async () => {
  const content = readFileSync(new URL('../../components/MindMap/MindmapAgentWritePolicy.vue', import.meta.url), 'utf8')
  const script = parse(content).descriptor.scriptSetup.content
  const ast = babelParse(script, { sourceType: 'module' }).program.body
  const body = ast.filter(node => node.type === 'ExpressionStatement' || node.declarations?.some(item => item.id.name === 'open'))
    .map(node => script.slice(node.start, node.end)).join('\n')
  const props = reactive({ active: true, label: '编辑 · 实时保存到云端', description: '修改会实时保存' })
  const scope = effectScope()
  const open = scope.run(() => new Function('props', 'ref', 'watch', `${body};return open`)(props, ref, watch))
  try {
    for (const change of [{ active: false }, { active: true }, { label: '讨论 · 不改图' }, { description: '只讨论当前脑图，不会修改画布。' }]) {
      open.value = true
      Object.assign(props, change)
      await nextTick()
      assert.equal(open.value, false)
    }
  } finally { scope.stop() }
})

test('device connection does not claim that the local CLI is authenticated', () => {
  const state = readiness({ agentKey: 'device_claude', displayName: 'Claude', status: 'enabled', healthStatus: 'healthy' })
  assert.equal(state.selectedAgentReadinessTone.value, 'pending')
  assert.match(state.selectedAgentReadinessDescription.value, /登录将在执行时校验/)
  state.selectedDeviceIssue.value = '电脑已离线'
  assert.equal(state.selectedAgentReadinessTone.value, 'unavailable')
  assert.equal(state.selectedAgentReadinessDescription.value, '电脑已离线')
})

test('native model preflight accepts provider casing without skipping incompatible endpoint errors', () => {
  const scope = { computed, form: reactive({ agentKey: 'native_mindmap', modelId: 1 }),
    models: ref([{ modelId: 1, provider: ' anthropic ', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' }]) }
  const state = compile(['nativeModelConfigurationIssue'], scope)
  assert.match(state.nativeModelConfigurationIssue.value, /兼容模式/)
  scope.models.value[0].provider = 'OpenAI'
  assert.equal(state.nativeModelConfigurationIssue.value, '')
})

test('composer shortcut matches displayed shortcut and does not send Chinese IME confirmation', () => {
  let sends = 0
  const state = compile(['onComposerKeydown'], {
    running: ref(false), cancelling: ref(false), sendComposerMessage: () => sends++,
  })
  for (const modifiers of [{}, { ctrlKey: true, isComposing: true }, { metaKey: true, keyCode: 229 }, { ctrlKey: true, shiftKey: true }]) {
    state.onComposerKeydown({ key: 'Enter', preventDefault: () => assert.fail('Keep normal editing'), ...modifiers })
  }
  assert.equal(sends, 0)
  let prevented = 0
  for (const modifiers of [{ ctrlKey: true }, { metaKey: true }]) {
    state.onComposerKeydown({ key: 'Enter', preventDefault: () => prevented++, ...modifiers })
  }
  assert.equal(sends, 2)
  assert.equal(prevented, 2)
  assert.match(source, /Ctrl \/ ⌘ \+ Enter 发送 · Enter 换行/)
})

test('content-size presets say what they control and preserve generation parameters', () => {
  const scope = { taskConfigurationLocked: ref(false), form: {}, maxNodesCap: ref(1000), maxDepthCap: ref(20) }
  const state = compile(['reasoningModes', 'setReasoningMode'], scope)
  assert.deepEqual(state.reasoningModes.map(mode => mode.label), ['简洁', '标准', '详细'])
  for (const mode of state.reasoningModes) assert.match(mode.description, /内容规模.*不调整模型思考强度/)
  state.setReasoningMode('deep')
  assert.deepEqual(scope.form, { density: 'detailed', maxNodes: 240, maxDepth: 10 })
  state.setReasoningMode('quick')
  assert.deepEqual(scope.form, { density: 'concise', maxNodes: 60, maxDepth: 5 })
})

test('configuration dialog returns focus to the composer only for the same visible account', async () => {
  const actions = []
  let owner = 'owner'
  const scope = { showAdvancedSettings: ref(false), componentAlive: true, visible: ref(true),
    currentAiOwnerUserId: () => owner, nextTick: async () => actions.push('render'),
    composerInputRef: ref({ focus: () => actions.push('composer') }),
    advancedSettingsRef: ref({ focus: () => actions.push('focus') }) }
  const state = compile(['taskSettingsOwnerId', 'openTaskSettings', 'focusTaskSettings', 'finishTaskSettings'], scope)
  await state.openTaskSettings()
  assert.equal(scope.showAdvancedSettings.value, true)
  assert.deepEqual(actions, ['render', 'focus'])
  const finished = state.finishTaskSettings()
  scope.showAdvancedSettings.value = false // Escape updates v-model after `closed`.
  await finished
  assert.equal(actions.at(-1), 'composer')

  await state.openTaskSettings()
  actions.length = 0
  owner = 'another-owner'
  state.focusTaskSettings()
  scope.showAdvancedSettings.value = false
  await state.finishTaskSettings()
  assert.deepEqual(actions, ['render'], 'A late dialog callback must not refocus a different account')

  actions.length = 0
  scope.nextTick = async () => { scope.visible.value = false }
  await state.openTaskSettings()
  assert.deepEqual(actions, [], 'Closing the editor must not steal focus back')
})

test('manager configuration navigation waits for modal close and stays within the same account', () => {
  const manager = parse(readFileSync(new URL('../../components/MindMap/MindmapAgentManager.vue', import.meta.url), 'utf8')).descriptor.scriptSetup.content
  const definitions = babelParse(manager, { sourceType: 'module' }).program.body
    .filter(node => ['requestConfigure', 'finishConfigure'].includes(node.id?.name))
    .map(node => manager.slice(node.start, node.end)).join('\n')
  const events = []
  const props = reactive({ ownerId: 'owner', modelValue: true })
  const configureOwner = ref(null)
  const api = new Function('props', 'configureOwner', 'emit', `${definitions}; return { requestConfigure, finishConfigure };`)(props, configureOwner, (...args) => events.push(args))
  api.requestConfigure()
  assert.deepEqual(events, [['update:modelValue', false]])
  props.modelValue = false
  api.finishConfigure()
  assert.deepEqual(events.at(-1), ['configure'])
  const count = events.length
  api.finishConfigure()
  assert.equal(events.length, count, 'Navigation happens once')
  props.modelValue = true
  api.requestConfigure()
  props.ownerId = 'different-owner'
  props.modelValue = false
  api.finishConfigure()
  assert.equal(events.length, count + 1, 'Old account cannot navigate new account settings')
})
