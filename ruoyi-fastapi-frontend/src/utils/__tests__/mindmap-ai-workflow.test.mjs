import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { babelParse, parse } from '@vue/compiler-sfc'
import { resolveMindmapAiAgentSelection } from '../mindmap-ai-agent-selection.js'

const dialog = await readFile(
  new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url),
  'utf8',
)
const editor = await readFile(
  new URL('../../components/MindMap/Edit.vue', import.meta.url),
  'utf8',
)
const toolbar = await readFile(
  new URL('../../components/MindMap/Toolbar.vue', import.meta.url),
  'utf8',
)
const activityBar = await readFile(
  new URL('../../components/MindMap/WorkspaceActivityBar.vue', import.meta.url),
  'utf8',
)
const api = await readFile(
  new URL('../../api/mindmap/mindmap.js', import.meta.url),
  'utf8',
)
const requestClient = await readFile(
  new URL('../request.js', import.meta.url),
  'utf8',
)
const connectorAdmin = await readFile(
  new URL('../../views/mindmap/ai-agents.vue', import.meta.url),
  'utf8',
)
const mindmapPreview = await readFile(
  new URL('../../components/MindMap/index.vue', import.meta.url),
  'utf8',
)
const contextmenu = await readFile(
  new URL('../../components/MindMap/Contextmenu.vue', import.meta.url),
  'utf8',
)

// Execute the actual SFC declarations for guards/computed contracts. Layout
// assertions below only describe the current single-canvas UI, not the retired
// second MindMapPreview surface.
function declaration(source, name, { initializer = false } = {}) {
  const script = parse(source).descriptor.scriptSetup.content
  const ast = babelParse(script, { sourceType: 'module' })
  for (const statement of ast.program.body) {
    if (statement.type === 'FunctionDeclaration' && statement.id.name === name) {
      return script.slice(statement.start, statement.end)
    }
    for (const item of statement.declarations || []) {
      if (item.id.name === name) {
        const node = initializer ? item.init : statement
        return script.slice(node.start, node.end)
      }
    }
  }
  throw new Error(`Missing SFC declaration: ${name}`)
}

function executeFunction(name, bindings, source = dialog) {
  return new Function(...Object.keys(bindings), `${declaration(source, name)}; return ${name}`)(...Object.values(bindings))
}

function computedValue(name, bindings, source = dialog) {
  return new Function('computed', ...Object.keys(bindings), `return ${declaration(source, name, { initializer: true })}`)(getter => getter(), ...Object.values(bindings))
}

const ref = value => ({ value })

test('AI Agent 能力来自服务端 manifest 且按当前意图和来源协商', () => {
  assert.match(dialog, /listMindmapAiAgents\(\)/)
  assert.match(dialog, /agentSupportsCurrentTask\(agent\)/)
  assert.match(dialog, /agent\.intents/)
  assert.match(dialog, /agent\.inputTypes/)
  assert.match(dialog, /selectedAgent\.sdkVersion/)
  assert.match(dialog, /selectedAgent\.runtimeVersion/)
  assert.match(dialog, /selectedAgent\.authType/)
  assert.match(dialog, /selectedAgent\.dataRegion/)
})

test('Agent 选择明确展示连接就绪度且首次检查期间持续反馈', () => {
  assert.match(dialog, /class="agentReadiness"[\s\S]*selectedAgentReadinessLabel[\s\S]*selectedAgentReadinessDescription/)
  assert.match(dialog, /class="agentDisclosureDetails"[\s\S]*连接与使用范围/)
  assert.match(dialog, /healthStatus === 'healthy'[\s\S]*连接正常/)
  assert.match(dialog, /healthStatus === 'unknown'[\s\S]*首次运行时检查/)
  assert.match(dialog, /v-if="submitting" class="submissionStatus"[\s\S]*aria-live="polite"/)
  assert.match(dialog, /submissionStageTitle[\s\S]*正在检查[\s\S]*submissionStageDescription/)
  assert.match(dialog, /submissionStartedAt\.value = Date\.now\(\)[\s\S]*submitting\.value = true/)
  assert.match(dialog, /watch\(\(\) => running\.value \|\| submitting\.value/)
})

test('输出语言与目标布局可配置、可恢复，局部编辑强制保持原布局', () => {
  assert.match(dialog, /v-model="form\.language"[\s\S]*v-for="item in outputLanguageOptions"/)
  assert.match(dialog, /v-model="form\.layout"[\s\S]*v-for="item in aiLayoutOptions"/)
  assert.match(dialog, /v-if="targetLayoutLocked"[^>]*>局部编辑只修改授权节点，保持当前脑图布局。<\/div>/)
  assert.match(dialog, /function captureJobConfiguration[\s\S]*language:[\s\S]*layout:/)
  assert.match(dialog, /restorableFields = \[[\s\S]*'language', 'layout'/)
  assert.match(dialog, /parameters: \{[\s\S]*language: form\.language,[\s\S]*layout: effectiveRequestLayout\(source\)/)
  assert.match(dialog, /function effectiveRequestLayout[\s\S]*source\.scope\.type !== 'document'/)
  assert.match(dialog, /async function retryJob[\s\S]*parameters: \{[\s\S]*language:[\s\S]*layout:/)
})

test('已选 Agent 在任务或来源不兼容时保持不变并由用户决定是否切换', () => {
  const agents = [
    { agentKey: 'native_mindmap', status: 'enabled' },
    { agentKey: 'codex', status: 'enabled' },
    { agentKey: 'claude', status: 'disabled' },
  ]
  const incompatibleSelection = resolveMindmapAiAgentSelection({
    agents,
    selectedAgentKey: 'codex',
    supportsAgent: agent => agent.agentKey === 'native_mindmap',
  })
  assert.equal(incompatibleSelection.agentKey, 'codex')
  assert.equal(incompatibleSelection.selectedAgent?.agentKey, 'codex')
  assert.equal(incompatibleSelection.autoSelected, false)

  const missingSelection = resolveMindmapAiAgentSelection({
    agents,
    selectedAgentKey: 'retired_agent',
    supportsAgent: () => true,
  })
  assert.equal(missingSelection.agentKey, 'retired_agent')
  assert.equal(missingSelection.selectedAgent, null)
  assert.equal(missingSelection.autoSelected, false)

  const initialDefault = resolveMindmapAiAgentSelection({
    agents,
    selectedAgentKey: '',
    supportsAgent: agent => agent.status === 'enabled',
  })
  assert.equal(initialDefault.agentKey, 'native_mindmap')
  assert.equal(initialDefault.autoSelected, true)

  assert.match(dialog, /function reconcileAgentSelection\(\)[\s\S]*resolveMindmapAiAgentSelection/)
  assert.doesNotMatch(dialog, /form\.agentKey = replacement\?\.agentKey/)
  assert.match(dialog, /agentSelectionIssue[\s\S]*系统不会自动替换/)
  assert.match(dialog, /composerCanSend[\s\S]*selectedAgentReady\.value/)
  assert.match(dialog, /class="composerAgentIssue"[\s\S]*选择 Agent/)
})

test('新建脑图结果的产品内打开与云端保存动作不会落入原生 template 而失效', () => {
  const quickActions = dialog.match(/<div v-if="!messageModeActive && selectedArtifactJob\?\.artifactId" class="resultQuickActions">([\s\S]*?)<\/div>/)?.[1] || ''
  assert.doesNotMatch(quickActions, /<template>/)
  assert.match(quickActions, /@click="openArtifactAsLocal"[\s\S]*打开为本地脑图/)
  assert.match(quickActions, /type="primary"[\s\S]*@click="saveCloud"[\s\S]*保存为云端脑图/)
  assert.match(dialog, /\.resultQuickActions \{[\s\S]*min-height: 30px;[\s\S]*\.el-button \{[\s\S]*min-height: 30px;/)
})

test('只读来源只能生成独立文件而不会形成可回写 proposal', () => {
  assert.doesNotMatch(dialog, /只读脑图不能生成可应用提案/)
  assert.match(dialog, /sourceContext\.value\?\.readonly[\s\S]*\? 'file' : 'proposal'/)
  const bindings = {
    livePreviewActive: ref(true), canApplyCurrentProposal: ref(true), diffConfirmed: ref(true),
    livePreviewCatchingUp: ref(false), livePreviewPreparing: ref(false),
    actionBusy: ref(false), editorReadonly: ref(true),
  }
  assert.equal(computedValue('canApplyLiveCanvasDraft', bindings), false)
  bindings.editorReadonly.value = false
  assert.equal(computedValue('canApplyLiveCanvasDraft', bindings), true)
})

test('AI 面板由编辑器壳单一挂载且只读工作区保留权限受控入口', () => {
  assert.equal(editor.match(/<MindmapAiDialog\b/g)?.length, 1)
  assert.match(editor, /<MindmapAiDialog\b[^>]*\s:readonly="aiDialogReadonly"[^>]*\/>/)
  const readonlyState = {
    props: { readonly: false, mindmapId: 1 }, serverCanEdit: ref(true),
    aiEditingBlocked: ref(true), authoritativeRecoveryEditingBlocked: ref(false),
    collaborationBarrierEditingBlocked: ref(false), versionTransitionEditingBlocked: ref(false),
    importTransitionEditingBlocked: ref(false),
  }
  assert.equal(computedValue('isReadonly', readonlyState, editor), true)
  assert.equal(computedValue('aiDialogReadonly', readonlyState, editor), false)
  readonlyState.serverCanEdit.value = false
  assert.equal(computedValue('aiDialogReadonly', readonlyState, editor), true)
  assert.doesNotMatch(toolbar, /<MindmapAiDialog\b|import MindmapAiDialog/)
  assert.match(toolbar, /v-hasPermi="\['mindmap:ai:use'\]"[\s\S]*bus\.emit\('showAiMindmap'\)/)
  assert.match(activityBar, /v-hasPermi="\['mindmap:ai:use'\]"[\s\S]*class="activityButton aiActivityButton"/)
  assert.match(activityBar, /@click="bus\.emit\('showAiMindmap'\)"/)
  const aiButtonClassOffset = activityBar.indexOf('class="activityButton aiActivityButton"')
  const aiButtonOpenTag = activityBar.slice(
    activityBar.lastIndexOf('<button', aiButtonClassOffset),
    activityBar.indexOf('>', aiButtonClassOffset) + 1,
  )
  assert.doesNotMatch(aiButtonOpenTag, /v-if=.*isReadonly/)
})

test('AI 抽屉内所有浮层高于抽屉，Agent 与会话选项可见且可点击', () => {
  const selectTags = dialog.match(/<el-select\b[\s\S]*?>/g) || []
  assert.ok(selectTags.length >= 4)
  for (const tag of selectTags) {
    assert.match(tag, /popper-class="mindmapAiSelectPopper"/)
  }
  assert.match(dialog, /popper-class="mindmapAiSessionPopper"/)
  assert.match(dialog, /popper-class="mindmapAiContextPopper"/)
  assert.match(dialog, /popper-class="mindmapAiTooltipPopper"/)
  assert.match(
    dialog,
    /\.mindmapAiSessionPopper,[\s\S]*\.mindmapAiSelectPopper,[\s\S]*\.mindmapAiTooltipPopper \{[\s\S]*z-index: 4300 !important;/,
  )
})

test('节点右键 AI 快捷操作锁定当前分支并区分编辑与解释模式', () => {
  assert.match(contextmenu, /import \{ ElMessage \} from 'element-plus'/)
  assert.match(contextmenu, /hasAnyPermission\(userStore\.permissions, \['mindmap:ai:use'\]\)/)
  assert.match(contextmenu, /key: 'ai-expand'[\s\S]*value: 'expand'[\s\S]*key: 'ai-explain'[\s\S]*value: 'explain'[\s\S]*key: 'ai-reorganize'[\s\S]*value: 'reorganize'/)
  assert.match(contextmenu, /expand: Object\.freeze\(\{[\s\S]*intent: 'expand'[\s\S]*scopeType: 'branch'[\s\S]*interactionMode: 'edit'/)
  assert.match(contextmenu, /explain: Object\.freeze\(\{[\s\S]*scopeType: 'branch'[\s\S]*interactionMode: 'discussion'[\s\S]*不修改当前脑图/)
  assert.match(contextmenu, /reorganize: Object\.freeze\(\{[\s\S]*intent: 'reorganize'[\s\S]*scopeType: 'branch'/)
  assert.match(contextmenu, /function isSameMindmapNode[\s\S]*leftUid === nodeIdentity\(rightNode\)[\s\S]*function ensureContextNodeActive[\s\S]*activeNodes\.length === 1[\s\S]*target\.active\?\.\(\)/)
  assert.match(contextmenu, /function openNodeAi[\s\S]*bus\.emit\('showAiMindmap', \{ \.\.\.preset \}\)/)
  assert.match(contextmenu, /group\.map\(normalizeVisibleMenuItem\)[\s\S]*item\.children\.filter\(isMenuItemVisible\)/)
  assert.doesNotMatch(contextmenu, /@focus="expandedSubmenu = item\.key"/)
  assert.match(contextmenu, /@click="openSubmenu\(item\.key\)"[\s\S]*function openSubmenu\(key\)[\s\S]*expandedSubmenu\.value = key/)
})

test('手动采纳未确认差异时不会写入，并聚焦差异确认框', async () => {
  assert.match(dialog, /ref="proposalConfirmationRef"[\s\S]*?v-model="diffConfirmed"/)
  const calls = []
  const apply = executeFunction('applyProposal', {
    actionBusy: ref(false), sourceBaselineMismatch: ref(false),
    livePreviewCatchingUp: ref(false), livePreviewPreparing: ref(false),
    job: ref({ id: 'j' }), proposal: ref({ id: 'p' }), diffConfirmed: ref(false),
    ElMessage: { warning: message => calls.push(message) }, nextTick: async () => {},
    proposalConfirmationRef: ref({ $el: {
      scrollIntoView: () => calls.push('scroll'),
      querySelector: selector => { assert.equal(selector, 'input[type="checkbox"]'); return { focus: () => calls.push('focus') } },
    } }),
  })
  assert.equal(await apply(), false)
  assert.deepEqual(calls, ['请先查看并勾选提案差异确认，再应用到当前脑图', 'scroll', 'focus'])
})

test('提案应用或撤销后默认收起历史差异且不再显示覆盖确认', () => {
  assert.match(
    dialog,
    /<details[\s\S]*class="proposalPreview"[\s\S]*:open="!proposalReviewFinalized"/,
  )
  assert.match(
    dialog,
    /v-if="proposalReviewFinalized" class="proposalReviewSummary"[\s\S]*已撤销提案差异[\s\S]*已应用提案差异/,
  )
  assert.match(
    dialog,
    /v-if="!proposalReviewFinalized"[\s\S]*ref="proposalConfirmationRef"/,
  )
  for (const status of ['applied', 'undone', 'rejected']) {
    assert.equal(computedValue('proposalReviewFinalized', { proposal: ref({}), job: ref({ status }) }), true)
  }
  assert.equal(computedValue('proposalReviewFinalized', { proposal: ref({}), job: ref({ status: 'needs_review' }) }), false)
  assert.match(dialog, /\.proposalReviewSummary[\s\S]*cursor: pointer[\s\S]*focus-visible/)
})

test('本地 AI 提案在校验基线后以单条历史应用并使用持久化回执队列', () => {
  assert.match(dialog, /prepareMindmapAiLocalApply/)
  assert.match(dialog, /prepared\.baseHash !== expectedSourceFingerprint/)
  assert.match(dialog, /verifyMindmapAiLocalProposal\(\{[\s\S]*operations: prepared\.operations[\s\S]*artifactHash: documentHash/)
  assert.match(dialog, /enqueueMindmapAiLocalAck/)
  assert.match(editor, /captureHistoryState/)
  assert.match(editor, /appendCurrentToHistoryState\?\.\([\s\S]*?\{ force: Boolean\(aiLocalApply \|\| aiArtifactApply\) \}/)
  assert.match(editor, /const aiLocalApply = request\.aiLocalApply[\s\S]*?try \{/)
  assert.match(editor, /protectedLocalRecordBeforeAiApply = cloneRequestPayload\(actions\.getData\(\)\)/)
  assert.match(editor, /function restoreLocalAiBaseline[\s\S]*actions\.restoreData\(localRecord\)/)
  assert.match(editor, /localRecord: shouldRollbackLocalWorkspace && localWorkspaceMutationStarted[\s\S]*\? protectedLocalRecordBeforeAiApply/)
  assert.match(editor, /function onBusDataChange\([\s\S]*importTransitionEditingBlocked\.value\) return/)
  assert.match(editor, /function isContentDetailTrackingSuspended\([\s\S]*importTransitionEditingBlocked\.value/)
  assert.match(editor, /lastAppliedProposal: aiLocalApply\.proposalId/)
  assert.match(editor, /actualResultFingerprint = await computeMindmapSnapshotFingerprint\(getCurrentDocument\(\)\)/)
  assert.match(editor, /expectedResultFingerprint = await computeMindmapSnapshotFingerprint\(document\)/)
  assert.match(editor, /aiLocalApply && actualResultFingerprint !== aiLocalApply\.resultHash/)
  assert.match(editor, /localAiUndoSnapshot = \{[\s\S]*document: cloneRequestPayload\(protectedDocumentBeforeImportApply\)[\s\S]*historyState: cloneRequestPayload\(aiHistoryState\)/)
  assert.match(editor, /function applyLocalAiCompleteDocument[\s\S]*setFullData\(cloneRequestPayload\(document\)\)[\s\S]*if \(!document\.view\) activeMindMap\.view\?\.reset/)
  assert.match(editor, /if \(!data\.root \|\| !data\.view\) activeMindMap\.view\.reset\(\)/)
  assert.match(editor, /localRecord\?\.documentHash !== payload\.resultHash/)
  assert.match(dialog, /resultHash: proposal\.value\?\.resultHash/)
  assert.match(dialog, /bus\.emit\(event, payload, \{ \.\.\.options, resolve, reject \}\)/)
  assert.match(dialog, /emitEditorRequest\('setData', verified\.document, \{[\s\S]*aiLocalApply:/)
})

test('本地 AI 撤销持久化基线哈希并通过可恢复回执同步服务端状态', () => {
  assert.match(api, /ackMindmapAiLocalUndo[\s\S]*ack-local-undo/)
  assert.match(
    editor,
    /async function onUndoLocalAiProposal[\s\S]*undoSnapshot\.baseHash !== payload\.revertedHash[\s\S]*applyLocalAiCompleteDocument\(activeMindMap, undoSnapshot\.document\)[\s\S]*assertMindmapAiLocalUndoBaseline[\s\S]*documentHash: actualRevertedHash[\s\S]*lastAppliedProposal: null[\s\S]*revertedHash: actualRevertedHash/,
  )
  assert.match(editor, /const nextRevision = Number\(localRecord\.revision\) \+ 1/)
  assert.match(
    editor,
    /restoreLocalAiBaseline\(\{[\s\S]*document: appliedDocument[\s\S]*localRecord: appliedLocalRecord[\s\S]*logLabel: '恢复 AI 撤销前画布失败'/,
  )
  assert.match(editor, /if \(localAiUndoInProgress\) return[\s\S]*localAiUndoSnapshot = null[\s\S]*persistLocalWorkspace\(\{ root: data \}\)/)
  assert.match(
    dialog,
    /async function queueLocalAck[\s\S]*action === 'undo' \? ackMindmapAiLocalUndo : ackMindmapAiLocalApply/,
  )
  assert.match(dialog, /function queueLocalUndoAck[\s\S]*queueLocalAck\('undo'/)
  assert.match(
    dialog,
    /emitEditorRequest\('undoLocalAiProposal',[\s\S]*revertedHash: proposal\.value\?\.baseHash[\s\S]*queueLocalUndoAck/,
  )
})

test('云端 AI 应用和撤销都携带幂等键并触发权威重载', () => {
  assert.match(api, /Idempotency-Key/)
  assert.match(dialog, /applyMindmapAiCloudProposal/)
  assert.match(dialog, /undoMindmapAiCloudProposal/)
  assert.match(editor, /onAiCloudProposalApplied/)
  assert.match(editor, /markAuthoritativeReloadRequired\(\)/)
})

test('云端 apply/undo 在请求前持久化 intent，按原请求精确对账后才删除', () => {
  const applyBlock = dialog.slice(
    dialog.indexOf('async function applyCloudProposal'),
    dialog.indexOf('async function applyProposal'),
  )
  const settleBlock = dialog.slice(
    dialog.indexOf('async function settleCloudMutationIntent'),
    dialog.indexOf('function executeCloudMutationIntent'),
  )
  assert.ok(
    applyBlock.indexOf('enqueueMindmapAiCloudMutationIntent')
      < applyBlock.indexOf('executeCloudMutationWithRecovery'),
  )
  assert.match(dialog, /action: 'undo'[\s\S]*requestPayload: null[\s\S]*executeCloudMutationWithRecovery\(intent\)/)
  assert.match(settleBlock, /getMindmapAiProposal\(intent\.proposalId\)/)
  assert.match(settleBlock, /intent\.idempotencyKey/)
  assert.match(settleBlock, /markMindmapAiCloudMutationConfirmed\(identity, confirmedRevision\)/)
  assert.ok(
    settleBlock.indexOf("emitEditorRequest('aiCloudProposalApplied'")
      < settleBlock.indexOf('removeMindmapAiCloudMutationIntent(identity)'),
  )
  assert.match(settleBlock, /receipt\.contentRevision\) < revision/)
  assert.match(declaration(dialog, 'reconcileJobAfterSideEffect'), /await flushPendingCloudMutationIntents\(\{ allowDuringLivePreview: true \}\)[\s\S]*actionIdentityMatches/)
  assert.match(dialog, /async function showDialog[\s\S]*await flushPendingCloudMutationIntents\(\)[\s\S]*requestEditorContext\(\)/)
  assert.match(dialog, /aiCloudMutationRecoveryReady/)
  assert.match(dialog, /async function reconcileCloudMutationBeforeSource[\s\S]*hasPendingForDocument[\s\S]*await flushPendingCloudMutationIntents\(\)[\s\S]*requestEditorContext\(\)/)
  assert.match(dialog, /let context = await requestEditorContext\(\)[\s\S]*context = await reconcileCloudMutationBeforeSource\(context\)/)
  assert.match(dialog, /@click="discardPermanentCloudMutationRecovery"/)
  assert.match(dialog, /async function discardPermanentCloudMutationRecovery[\s\S]*phase === 'permanent_failed'[\s\S]*removeMindmapAiCloudMutationIntent/)
  assert.match(
    dialog,
    /PERMANENT_CLOUD_MUTATION_CODES[\s\S]*'AI_PROPOSAL_INTEGRITY_INVALID'[\s\S]*'AI_PROPOSAL_FORMAT_OBSOLETE'/,
  )
  assert.match(editor, /contentRevision >= nextRevision[\s\S]*request\.resolve\?\.\(\{[\s\S]*contentRevision/)
  assert.match(editor, /performAuthoritativeReload\(\)[\s\S]*contentRevision < nextRevision[\s\S]*request\.resolve\?\.\(\{/)
  assert.match(
    editor,
    /function hasSupersededCollaborationBarrier[\s\S]*revision > collaborationBarrierRevision/,
  )
  const cloudApplyReloadBlock = editor.match(
    /async function onAiCloudProposalApplied[\s\S]*?function onNodeTagClick/,
  )?.[0] || ''
  assert.ok(
    cloudApplyReloadBlock.indexOf('setAuthoritativeRecoveryEditingBlocked(true)')
      < cloudApplyReloadBlock.indexOf('setCollaborationBarrierEditingBlocked(false)'),
    'the authoritative recovery fence must take over before releasing the superseded barrier',
  )
  assert.ok(
    cloudApplyReloadBlock.indexOf('setCollaborationBarrierEditingBlocked(false)')
      < cloudApplyReloadBlock.indexOf('stopCurrentCollaborationSource()'),
    'the committed barrier must be released before its WebSocket source is destroyed',
  )
  assert.match(api, /applyMindmapAiCloudProposal[\s\S]*silentError: true/)
  assert.match(api, /undoMindmapAiCloudProposal[\s\S]*silentError: true/)
})

test('首次创建对账接口通过请求头传递幂等键且静默处理未命中', () => {
  const reconcileApi = api.slice(
    api.indexOf('export function reconcileMindmapAiJob'),
    api.indexOf('export function getMindmapAiJobDraft'),
  )
  assert.match(reconcileApi, /url: '\/mindmap\/ai\/jobs\/reconcile'/)
  assert.match(reconcileApi, /method: 'get'/)
  assert.match(reconcileApi, /headers: \{ 'Idempotency-Key': idempotencyKey \}/)
  assert.match(reconcileApi, /signal,/)
  assert.match(reconcileApi, /silentError: true/)
  assert.match(requestClient, /responseError\.response = response/)
  assert.match(requestClient, /responseError\.status = responseStatus/)
})

test('Agent 管理页覆盖发布、密钥引用、健康和一致性闭环', () => {
  assert.match(api, /\/mindmap\/ai\/admin\/connectors/)
  assert.match(api, /health-check/)
  assert.match(api, /conformance/)
  assert.match(connectorAdmin, /rolloutPercentage/)
  assert.match(connectorAdmin, /credentialMode/)
  assert.match(connectorAdmin, /env:\/\/变量名 或 secret:\/\/密钥路径/)
  assert.match(connectorAdmin, /checkSelected/)
  assert.match(connectorAdmin, /modelAllowlist/)
  assert.match(connectorAdmin, /maxBudgetUsd/)
  assert.match(connectorAdmin, /timeoutSeconds/)
  assert.match(connectorAdmin, /maxConcurrentJobs/)
  assert.match(connectorAdmin, /仅验证本地确定性合同/)
  assert.match(connectorAdmin, /真实供应商执行/)
  assert.match(connectorAdmin, /providerExecutionText/)
  assert.match(connectorAdmin, /completed: '已执行'/)
  assert.match(connectorAdmin, /partial: '部分执行'/)
  assert.match(connectorAdmin, /not_run: '未执行'/)
  assert.match(connectorAdmin, /\|\| '未执行'/)
  assert.match(connectorAdmin, /不可作为发布证据/)
  assert.match(connectorAdmin, /不代表发布验收/)
  assert.doesNotMatch(connectorAdmin, /row\.credentialRef/)
})

test('用户任务参数受 Connector 模型与结构策略约束', () => {
  assert.match(dialog, /availableModels/)
  assert.match(dialog, /selectedAgent\.value\?\.modelAllowlist/)
  assert.match(dialog, /:max="maxNodesCap"/)
  assert.match(dialog, /:max="maxDepthCap"/)
  assert.match(dialog, /onAgentChange/)
})

test('AI 任务通过可续传 SSE 驱动交互记录并以权威草稿单调更新预览', () => {
  assert.match(api, /\/mindmap\/ai\/jobs\/\$\{jobId\}\/draft/)
  assert.match(api, /\{ signal, version \}/)
  assert.match(api, /\? \{ version: requestedVersion \}/)
  assert.match(dialog, /consumeMindmapAiRealtimeEvents\(jobId/)
  assert.match(dialog, /fetchDraft: getMindmapAiJobDraft/)
  assert.match(dialog, /afterSequence: latestEventSequence\.value/)
  assert.match(dialog, /previewVersion: latestPreviewVersion\.value/)
  assert.match(dialog, /appendAgentEvent\(jobId, event\)/)
  assert.match(declaration(dialog, 'acceptDraftPreview'), /compareMindmapAiPreviewCoordinates\([\s\S]*epoch: latestPreviewEpoch\.value, version: latestPreviewVersion\.value/)
  assert.match(dialog, /previewEpoch: latestPreviewEpoch\.value/)
  assert.match(dialog, /scheduleRealtimeReconnect\(jobId\)/)
  assert.match(dialog, /schedulePoll\(0\)/)
  assert.match(dialog, /defineExpose\(\{[\s\S]*agentEvents,[\s\S]*draftDocument,/)
})

test('恢复会话会把已展示的状态事件同步归并到任务卡片', () => {
  assert.match(dialog, /function applyRealtimeJobEvent\(jobId, event\)[\s\S]*mergeMindmapAiJobEventSnapshot\(job\.value, event\)/)
  assert.match(dialog, /async function restoreSessionTimeline[\s\S]*let restoredCurrentJob = job\.value[\s\S]*mergeMindmapAiJobEventSnapshot\(restoredCurrentJob, normalizedEvent\)[\s\S]*job\.value = restoredCurrentJob/)
  assert.match(dialog, /realtimeConnectionState\.value === 'connected'[\s\S]*\['queued', 'preparing'\]\.includes\(job\.value\?\.status\)[\s\S]*return statusLabel\.value/)
})

test('实时草稿缓存缺失时明确降级旧画面而不继续伪装为最新版本', () => {
  assert.match(dialog, /const draftFreshness = ref\('idle'\)/)
  assert.match(dialog, /preview\?\.available !== true[\s\S]*draftFreshness\.value = hasVisibleDraft \? 'stale' : 'unavailable'/)
  assert.match(dialog, /当前画面是最后一次成功恢复的版本，可能不是最新结果/)
  assert.match(dialog, /已连接 · 草稿非实时/)
  assert.match(dialog, /v-if="draftFreshnessMessage"[\s\S]*:title="draftFreshnessMessage"/)
  assert.match(dialog, /draftFreshness\.value = 'fresh'[\s\S]*draftFreshnessMessage\.value = ''/)
  assert.match(dialog, /draftFreshness\.value = 'final'/)
})

test('生成进程重启时保留持久检查点并等待新帧恢复实时状态', () => {
  assert.match(dialog, /generation_restarted: '生成进程重启'/)
  assert.match(dialog, /event\?\.eventType === 'generation_restarted'[\s\S]*生成进程已重启，已从持久草稿恢复/)
  assert.match(dialog, /function markGenerationRestarted\(\)[\s\S]*draftFreshness\.value = 'restarted'/)
  assert.match(dialog, /function hasUnresolvedGenerationRestart[\s\S]*lastRestartSequence > lastDraftSequence/)
  assert.match(dialog, /function beginJobMonitoring[\s\S]*hasUnresolvedGenerationRestart\(jobId\)[\s\S]*markGenerationRestarted\(\)/)
  assert.match(dialog, /当前保留从持久检查点恢复的草稿。收到新的草稿帧前，该画面不代表最新结果/)
  assert.match(dialog, /event\?\.eventType === 'generation_restarted'\) markGenerationRestarted\(\)/)
  assert.match(dialog, /preview\?\.available !== true[\s\S]*draftFreshness\.value === 'restarted'[\s\S]*return false/)
  assert.match(dialog, /\['stale', 'restarted'\]\.includes\(draftFreshness\)/)
  assert.match(dialog, /\['stale', 'unavailable', 'restarted'\]\.includes\(draftFreshness\.value\)/)
  assert.match(dialog, /acceptDraftPreview\(preview, \{ realtimeFrame: true \}\)/)
  assert.match(dialog, /draftFreshness\.value !== 'restarted' \|\| realtimeFrame/)
  assert.match(dialog, /draftFreshness\.value = 'fresh'[\s\S]*draftFreshnessMessage\.value = ''/)
  assert.match(dialog, /draftFreshness\.value = 'final'[\s\S]*draftFreshnessMessage\.value = ''/)
  assert.match(dialog, /仅展示用户输入和经过清洗的运行审计，不展示模型隐藏思维链/)
})

test('实时脑图逐帧应用外部 modelValue，只抑制组件自身发出的 v-model 回声', () => {
  assert.match(mindmapPreview, /let applyingExternalModelValue = false/)
  assert.match(mindmapPreview, /if \(applyingExternalModelValue\) return/)
  assert.match(mindmapPreview, /val === lastEmittedModelValue \|\| toRaw\(val\) === lastEmittedModelValue/)
  assert.match(mindmapPreview, /applyingExternalModelValue = true[\s\S]*mindMapInstance\.value\.setData\(val\)[\s\S]*flushPendingHistory[\s\S]*applyingExternalModelValue = false/)
  assert.doesNotMatch(mindmapPreview, /dataVersion !== lastAppliedVersion/)
})

test('实时脑图画布跟随三栏响应式布局变更并在卸载时释放观察器', () => {
  assert.match(mindmapPreview, /new ResizeObserver\(scheduleCanvasResize\)/)
  assert.match(mindmapPreview, /containerResizeObserver\.observe\(containerRef\.value\)/)
  assert.match(mindmapPreview, /const \{ width, height \} = container\.getBoundingClientRect\(\)/)
  assert.match(mindmapPreview, /if \(width <= 0 \|\| height <= 0\) return/)
  assert.match(mindmapPreview, /instance\.resize\(\)/)
  assert.match(mindmapPreview, /containerResizeObserver\?\.disconnect\(\)/)
  assert.match(mindmapPreview, /window\.cancelAnimationFrame\(resizeAnimationFrame\)/)
})

test('严格草稿复校验使用后端实际 snake_case 契约', () => {
  assert.match(api, /data: \{ artifact, require_passed: requirePassed \}/)
  assert.doesNotMatch(api, /data: \{ artifact, requirePassed \}/)
  const validationApi = api.slice(
    api.indexOf('export function validateMindmapAiArtifact'),
    api.indexOf('export function prepareMindmapAiLocalApply'),
  )
  assert.match(validationApi, /headers: \{ repeatSubmit: false \}/)
})

test('AI 错误码经过统一映射且下载错误信封不会伪装成 artifact', () => {
  assert.match(api, /assertMindmapAiArtifactDownloadResponse/)
  assert.match(dialog, /formatMindmapAiError/)
  assert.match(dialog, /formatMindmapAiJobError\(job\.value, 'AI 脑图任务失败'\)/)
  assert.match(dialog, /resolveMindmapAiErrorCode/)
  assert.match(dialog, /AI_PROPOSAL_STALE/)
  assert.match(dialog, /schedulePoll\(0, true\)/)
})

test('云端提案把内容等价与协作冲突裁决交给服务端权威基线', () => {
  const cloudApply = dialog.slice(
    dialog.indexOf('async function applyCloudProposal'),
    dialog.indexOf('async function applyProposal'),
  )
  assert.doesNotMatch(cloudApply, /Number\(context\.revision\) !== Number\(baseRevision\)/)
  assert.doesNotMatch(cloudApply, /computeMindmapSnapshotFingerprint\(context\.document\)/)
  assert.match(cloudApply, /contentRevision: baseRevision/)
  assert.match(cloudApply, /baseHash,[\s\S]*roomEpoch: baseRoomEpoch/)
  assert.match(cloudApply, /forceOverwrite/)
  assert.match(cloudApply, /mindmap-ai-force-apply/)
})

test('云端普通提案经差异确认后第一次请求即整图覆盖', () => {
  assert.match(dialog, /确认用 AI 完整结果覆盖当前脑图（可撤销）/)
  assert.match(dialog, /保存完成后可撤销本次 AI 全部操作/)
  assert.match(dialog, /const directCloudOverwrite = Boolean\(sourceMindmapId\)/)
  assert.match(dialog, /forceOverwrite: directCloudOverwrite/)
  assert.match(dialog, /AI 完整结果已覆盖当前脑图，可随时撤销/)
  assert.doesNotMatch(dialog, /async function confirmAndForceCloudProposal/)
  assert.match(
    dialog,
    /emitEditorRequest\('aiCloudProposalApplied',[\s\S]*forceOverwrite: intent\.requestPayload\?\.forceOverwrite === true/,
  )
  const cloudApplyReloadBlock = editor.match(
    /async function onAiCloudProposalApplied[\s\S]*?function onNodeTagClick/,
  )?.[0] || ''
  assert.match(cloudApplyReloadBlock, /const forceOverwrite = payload\.forceOverwrite === true/)
  assert.match(
    cloudApplyReloadBlock,
    /if \(forceOverwrite\) \{[\s\S]*retirePendingViewSaveForAuthoritativeReload\(\)[\s\S]*abandonPendingContentForAuthoritativeReload\(\)[\s\S]*remoteDocumentResetRetryBlocked = false/,
  )
})

test('Codex 进度只保留安全字段并映射为明确中文阶段', () => {
  assert.match(dialog, /eventType === 'agent_progress'/)
  assert.match(dialog, /sanitizeMindmapAiAgentProgressPayload/)
  assert.match(dialog, /describeMindmapAiAgentProgress/)
  assert.match(dialog, /mergeMindmapAiJobSnapshot\(job\.value, response\.data\)/)
})

test('AI 抽屉展示安全会话与连接状态，脑图只在主编辑器流式显示', () => {
  assert.match(dialog, /class="mindmapAiDrawer"/)
  assert.match(dialog, /direction="ltr"/)
  assert.match(dialog, /size="500px"/)
  assert.match(dialog, /:modal="false"/)
  assert.match(dialog, /modal-penetrable/)
  assert.match(dialog, /:z-index="4000"/)
  assert.match(dialog, /class="activitySidebar"/)
  assert.match(dialog, /v-for="turn in conversationTurns"/)
  assert.match(dialog, /connectionStateLabel/)
  assert.match(dialog, /正在重连/)
  assert.match(dialog, /离线/)
  assert.match(dialog, /不展示模型隐藏思维链/)
  assert.match(dialog, /class="activityTimeline conversationTimeline"[\s\S]*aria-live="polite"/)
  assert.doesNotMatch(dialog, /<MindMapPreview\b|class="previewPanel aiDraftStage"/)
  assert.match(dialog, /class="liveDraftNotice"/)
  assert.match(dialog, /livePreviewNodeProgress/)
  assert.match(dialog, /phase: 'update'/)
  assert.match(editor, /applyMindmapAiPresentationFrame\(/)
  assert.match(dialog, /const generationClockNow = ref\(Date\.now\(\)\)/)
  assert.match(dialog, /首个变化出现后会立即显示在当前画布/)
  assert.match(dialog, /正在冻结输入与生成约束，请勿重复提交/)
  assert.match(dialog, /role="status" aria-live="polite"/)
  assert.match(dialog, /clearInterval\(generationClockTimer\)/)
  assert.match(dialog, /今天想做点什么？/)
  assert.match(dialog, /class="aiComposer"/)
  assert.match(dialog, /问我任何问题/)
  assert.match(dialog, /@media \(max-width: 760px\)/)
  assert.match(dialog, /@media \(prefers-reduced-motion: reduce\)/)
})

test('窄屏可关闭 AI 抽屉查看同一画布，关闭不会停止或重置任务', async () => {
  assert.match(dialog, /@media \(max-width: 760px\)[\s\S]*\.mindmapAiDrawer \{ width: 100% !important; \}/)
  assert.match(dialog, /aria-label="关闭 AI 面板" @click="requestDialogClose"/)
  const visible = ref(true)
  const close = executeFunction('requestDialogClose', { visible })
  await close()
  assert.equal(visible.value, false)
  const sessionMenuVisible = ref(true)
  const contextPickerVisible = ref(true)
  executeFunction('onDialogClosed', { sessionMenuVisible, contextPickerVisible })()
  assert.equal(sessionMenuVisible.value, false)
  assert.equal(contextPickerVisible.value, false)
  assert.doesNotMatch(declaration(dialog, 'onDialogClosed'), /resetNewJob|revertLiveDraftPreview|cancelJob|stopRealtime/)
})

test('讨论模式使用服务端权威 message 契约且不会展示脑图产物动作', () => {
  assert.match(dialog, /const requestedIntent = effectiveFormIntent\.value/)
  assert.match(dialog, /intent: requestedIntent/)
  assert.match(dialog, /target: discussionMode\.value \? 'message'/)
  assert.match(dialog, /const messageModeActive = computed[\s\S]*isMindmapAiMessageJob\(job\.value\)/)
  assert.match(declaration(dialog, 'livePreviewEligible', { initializer: true }), /!messageModeActive\.value/)
  assert.match(dialog, /v-if="!messageModeActive && selectedArtifactJob\?\.artifactId"/)
  assert.match(dialog, /v-if="!messageModeActive && proposal"/)
  assert.match(dialog, /if \(isMindmapAiMessageJob\(job\.value\)\) return false/)
  assert.match(dialog, /completed_message: 'AI 已回复'/)
  assert.match(dialog, /turn\?\.assistantMessage\?\.content/)
  assert.match(dialog, /!messageModeActive && \(artifactTurns\.length/)
  assert.match(dialog, /job\.value\.status === 'completed_message'[\s\S]*restoreSessionTimeline/)
})

test('终态续写可选择下一轮讨论或编辑且不改变当前轮结果展示模式', () => {
  assert.match(dialog, /const messageModeActive = computed[\s\S]*isMindmapAiMessageJob\(job\.value\)/)
  assert.match(dialog, /const canSwitchInteractionMode = computed[\s\S]*followupParentJob\.value\?\.status !== 'needs_input'[\s\S]*!running\.value[\s\S]*!actionBusy\.value/)
  assert.match(dialog, /:disabled="Boolean\(job\) && !canSwitchInteractionMode"/)
  assert.match(dialog, /<span v-if="discussionMode" class="discussionChip">/)
  assert.match(dialog, /watch\(discussionMode, \(\) => \{[\s\S]*job\.value && !canSwitchInteractionMode\.value[\s\S]*reconcileAgentSelection\(\)/)
  assert.match(dialog, /function followupIntent[\s\S]*parentJob\?\.status === 'needs_input'[\s\S]*effectiveFormIntent\.value/)
  assert.match(dialog, /const requestedIntent = followupIntent\(parentJob\)[\s\S]*intent: requestedIntent/)
  assert.match(dialog, /interactionMode: nextDiscussionMode \? 'discussion' : 'edit'/)
})

test('独立脑图结果续写按 uploaded_artifact 协商并更新下一轮来源基线', () => {
  for (const status of ['ready', 'completed_file', 'completed_no_change', 'needs_review']) {
    const candidate = { id: 'j', artifactId: 'a', sourceType: 'none', status }
    const actual = computedValue('followupParentJob', {
      selectedArtifactJob: ref(candidate), viewingHistoricalArtifact: ref(false),
      isMindmapAiMessageJob: () => false,
    })
    assert.equal(actual, status === 'needs_review' ? null : candidate,
      'high-impact proposals must be resolved before continuing from their artifact')
  }
  assert.match(dialog, /function followupSourceType[\s\S]*parentJob\?\.artifactId[\s\S]*\['none', 'uploaded_artifact'\][\s\S]*return 'uploaded_artifact'/)
  assert.match(dialog, /const requestedSourceType = followupSourceType\(parentJob\)[\s\S]*selectedAgent\.inputTypes\?\.includes\(requestedSourceType\)/)
  assert.match(dialog, /job\.value\.sourceType === 'uploaded_artifact'[\s\S]*previousDraft\?\.root[\s\S]*document: previousDraft/)
  assert.match(dialog, /sourceFingerprint\.value = job\.value\.baseHash \|\| ''/)
  assert.match(dialog, /sourceFingerprint\.value = nextJob\.baseHash \|\| ''/)
})

test('应用或撤销后的云端续写先对账画布并使用权威当前正文基线', () => {
  assert.match(dialog, /\['cloud_document', 'local_snapshot'\]\.includes\(candidate\?\.sourceType\)[\s\S]*\['applied', 'undone'\]\.includes\(candidate\?\.status\)/)
  assert.match(dialog, /function followupContinuationBase[\s\S]*'current_document'[\s\S]*'artifact'/)
  assert.match(dialog, /continuationBase === 'current_document'[\s\S]*await flushPendingCloudMutationIntents\(\)[\s\S]*listMindmapAiCloudMutationIntents\(ownerUserId\)[\s\S]*await requestEditorContext\(\)[\s\S]*await reconcileCloudMutationBeforeSource\(currentContext\)/)
  assert.match(dialog, /Number\(currentContext\?\.mindmapId\) !== Number\(parentJob\.sourceMindmapId\)/)
  assert.match(dialog, /artifactId: continuationBase === 'artifact'[\s\S]*continuationBase,/)
  assert.match(dialog, /sourceContext\.value = currentContext[\s\S]*sourceFingerprint\.value = await computeMindmapSnapshotFingerprint/)
})

test('应用或撤销后的本地续写结算回执并提交完整当前快照', () => {
  assert.match(dialog, /\['cloud_document', 'local_snapshot'\]\.includes\(candidate\?\.sourceType\)[\s\S]*\['applied', 'undone'\]\.includes\(candidate\?\.status\)/)
  assert.match(dialog, /function followupContinuationBase[\s\S]*sourceType === 'local_snapshot'[\s\S]*return 'current_snapshot'/)
  const followupBlock = dialog.slice(
    dialog.indexOf('async function continueJob'),
    dialog.indexOf('async function loadArtifact'),
  )
  assert.match(followupBlock, /continuationBase === 'current_snapshot'[\s\S]*await flushLocalApplyAcks\(\)[\s\S]*listMindmapAiLocalAcks\(ownerUserId\)/)
  assert.match(followupBlock, /await getMindmapAiJob\(parentJobId\)[\s\S]*sourceType !== 'local_snapshot'[\s\S]*\['applied', 'undone'\]\.includes\(authoritativeParent\?\.status\)/)
  assert.match(followupBlock, /await requestEditorContext\(\)[\s\S]*currentContext\?\.mindmapId[\s\S]*currentContext\.documentId/)
  assert.match(followupBlock, /const currentHash = await computeMindmapSnapshotFingerprint\(currentContext\.document\)[\s\S]*const confirmedContext = await requestEditorContext\(\)[\s\S]*confirmedContext\.documentId !== currentContext\.documentId[\s\S]*Number\(confirmedContext\.revision\) !== Number\(currentContext\.revision\)/)
  assert.match(followupBlock, /const confirmedHash = await computeMindmapSnapshotFingerprint\(confirmedContext\.document\)[\s\S]*confirmedHash !== currentHash[\s\S]*confirmedContext\.documentHash !== confirmedHash/)
  assert.match(followupBlock, /const stableContext = await requestEditorContext\(\)[\s\S]*stableContext\?\.documentId !== confirmedContext\.documentId[\s\S]*Number\(stableContext\?\.revision\) !== Number\(confirmedContext\.revision\)[\s\S]*stableContext\.documentHash !== confirmedHash/)
  assert.match(followupBlock, /documentHash: confirmedHash[\s\S]*document: confirmedContext\.document/)
  assert.match(followupBlock, /expectedParentStatus: continuationBase === 'current_snapshot'[\s\S]*source: currentSnapshotSource/)
})

test('应用与撤销完成后同步刷新持久化来源上下文', () => {
  const applyBlock = dialog.slice(
    dialog.indexOf('async function applyProposal'),
    dialog.indexOf('async function undoProposal'),
  )
  const undoBlock = dialog.slice(
    dialog.indexOf('async function undoProposal'),
    dialog.indexOf('async function cancelJob'),
  )
  assert.match(dialog, /async function refreshSourceContextAfterMutation[\s\S]*sourceContext\.value = refreshedContext[\s\S]*sourceFingerprint\.value = await computeMindmapSnapshotFingerprint[\s\S]*persistActiveJob\(\)/)
  assert.match(applyBlock, /await refreshSourceContextAfterMutation\(sourceMindmapId, identity\)/)
  assert.match(undoBlock, /await refreshSourceContextAfterMutation\(sourceMindmapId, identity\)/)
})

test('上下文菜单实时跟踪选择并对单分支执行精确基数校验', () => {
  assert.match(dialog, /class="contextChip"[\s\S]*aria-haspopup="menu"/)
  assert.match(dialog, /role="menu" aria-label="选择 AI 上下文"/)
  assert.match(dialog, /bus\.on\('node_active', onEditorNodeActive\)/)
  assert.match(dialog, /bus\.off\('node_active', onEditorNodeActive\)/)
  assert.match(dialog, /selectedNodeUids\.value\.length !== 1[\s\S]*当前分支需要恰好选择一个节点/)
  assert.match(dialog, /const context = await requestEditorContext\(\)[\s\S]*const scope = buildScope\(\)/)
})

test('最近会话菜单由服务端列表驱动并用恢复代次隔离切换', () => {
  assert.match(api, /export function listMindmapAiSessions\(\{ limit = 20, signal \} = \{\}\)/)
  assert.match(api, /url: '\/mindmap\/ai\/sessions'[\s\S]*params: \{ limit \}/)
  assert.match(dialog, /@show="loadRecentSessions"/)
  assert.match(dialog, /normalizeMindmapAiSessionList\(response\.data\)/)
  assert.match(dialog, /async function switchToSession[\s\S]*resetNewJob\(\{ clearStoredJob: false[\s\S]*generation = restoreGeneration[\s\S]*restoreActiveJob\(\{ generation/)
  assert.match(dialog, /function invalidateSessionList[\s\S]*sessionListController\?\.abort\(\)/)
})

test('工具失败详情展示服务端脱敏错误码、消息和重试建议', () => {
  assert.match(dialog, /event\?\.eventType === 'tool_failed'[\s\S]*payload\.errorCode[\s\S]*payload\.errorMessage[\s\S]*payload\.retryable/)
})

test('AI 预览事件为完整任务生命周期提供明确中文记录', () => {
  for (const eventType of [
    'job_created', 'cancel_requested', 'local_applied', 'local_undone', 'cloud_file_created',
    'cloud_applied', 'cloud_undone', 'proposal_stale', 'generation_restarted',
  ]) {
    assert.match(dialog, new RegExp(`${eventType}: '[^']+'`))
    assert.match(dialog, new RegExp(`event\\?\\.eventType === '${eventType}'`))
  }
})

test('恢复会话按 job 隔离 SSE sequence 并合并跨轮 prompt 与审计事件', () => {
  assert.match(dialog, /getMindmapAiSessionTimeline/)
  assert.match(dialog, /await restoreSessionTimeline\(job\.value\.sessionId, \{/)
  assert.match(dialog, /const jobEventSequences = new Map\(\)/)
  assert.match(dialog, /jobEventSequences\.set\(jobId, Math\.max\(previousSequence, sequence\)\)/)
  assert.match(dialog, /syncCurrentJobCursor\(expectedJobId\)/)
  assert.match(dialog, /beginJobMonitoring\(\)/)
  assert.match(dialog, /appendClientPrompt\([\s\S]*turn\.userMessage\.content/)
  assert.doesNotMatch(dialog, /JSON\.stringify\(event\.payload/)
})

test('任务恢复可取消且按代次隔离，临时失败保留指针并提供重试或放弃', () => {
  const restoreBlock = dialog.slice(
    dialog.indexOf('async function restoreActiveJob'),
    dialog.indexOf('function retryStoredJobRecovery'),
  )
  assert.match(dialog, /let restoreGeneration = 0/)
  assert.match(dialog, /restoreController\?\.abort\(\)/)
  assert.match(restoreBlock, /getMindmapAiJob\(saved\.jobId, \{ signal: controller\.signal \}\)/)
  assert.match(restoreBlock, /generation !== restoreGeneration/)
  assert.match(restoreBlock, /restoreError\.value = formatMindmapAiError/)
  assert.doesNotMatch(restoreBlock, /catch \(error\) \{[\s\S]*clearStoredActiveJob\(\)/)
  assert.match(dialog, /@click="retryStoredJobRecovery"/)
  assert.match(dialog, /@click="discardStoredJobRecovery"/)
  assert.match(dialog, /const composerCanSend = computed/)
  assert.match(dialog, /composerText\.value\.trim\(\)[\s\S]*&& !restoreError\.value/)
  assert.match(dialog, /:disabled="!composerCanSend"/)
  assert.match(dialog, /function onDialogClosed\(\) \{[\s\S]*invalidateRestoreOperations\(\{ clearError: false \}\)/)
  assert.match(dialog, /loadCapabilities\(\{ recoveryGeneration = restoreGeneration \} = \{\}\)/)
  assert.match(dialog, /if \(recoveryGeneration !== restoreGeneration\) return false/)
  assert.match(dialog, /await loadCapabilities\(\{ recoveryGeneration: generation \}\)/)
})

test('会话记录恢复使用独立取消器、身份栅栏和内联重试', () => {
  assert.match(dialog, /const generation = \+\+timelineLoadGeneration/)
  assert.match(dialog, /getMindmapAiSessionTimeline\(sessionId, \{ signal: controller\.signal \}\)/)
  assert.match(dialog, /job\.value\?\.id !== expectedJobId/)
  assert.match(dialog, /job\.value\?\.sessionId !== sessionId/)
  assert.match(dialog, /@click="retrySessionTimeline"/)
  assert.match(dialog, />重新加载会话记录<\/el-button>/)
})

test('会话记录支持确认后删除并清理本地恢复状态', () => {
  assert.match(dialog, /deleteMindmapAiSession/)
  assert.match(dialog, /@click="deleteSessionRecord"/)
  assert.match(dialog, /删除整段会话记录会同时请求取消正在运行的任务/)
  assert.match(dialog, /await deleteMindmapAiSession\(sessionId\)/)
  assert.match(dialog, /resetNewJob\(\{ clearStoredJob: true, preserveForm: true \}\)/)
})

test('任务生命周期可重置恢复，终态转存为可查看的最近结果而不阻塞新任务', () => {
  assert.match(dialog, /function resetNewJob\(/)
  assert.match(declaration(dialog, 'persistActiveJob'), /return persistJobPointer\(storedJob, job\.value\.status\)/)
  assert.match(declaration(dialog, 'persistJobPointer'), /if \(!writeMindmapAiOwnerSessionItem[\s\S]*return false[\s\S]*clearMindmapAiOwnerSessionItem/)
  assert.match(dialog, /saved = activeUsable \? active : \(allowRecent && recentUsable \? recent : null\)/)
  assert.match(dialog, /if \(isTerminalStatus\(job\.value\.status\)\) \{[\s\S]*await finalizeTerminalJob\(job\.value\.id/)
  assert.match(dialog, /class="newConversationButton"/)
  assert.match(dialog, /class="sessionNewAction"[\s\S]*新建对话/)
  assert.match(dialog, /@click="startNewJob"/)
  assert.match(dialog, /beginJobMonitoring\(\{ resetCursor: true \}\)/)
  assert.match(dialog, /window\.addEventListener\('offline', onNetworkOffline\)/)
  assert.match(dialog, /window\.removeEventListener\('offline', onNetworkOffline\)/)
  assert.match(declaration(dialog, 'cancelJob'), /assertActionIdentity\(identity\)[\s\S]*await finalizeTerminalJob\(jobId/)
  assert.match(declaration(dialog, 'finalizeTerminalJob'), /stopRealtime\('completed'\)[\s\S]*stopPolling\(\)/)
})

test('恢复任务还原模型和生成参数并保留讨论切回编辑所需的意图', () => {
  assert.match(dialog, /configuration: cloneRuntimeValue\(jobConfiguration\.value \|\| captureJobConfiguration\(\)\)/)
  assert.match(dialog, /stored\.modelId \?\? snapshot\.modelRef/)
  assert.match(dialog, /stored\.maxNodes \?\? snapshot\.maxNodes/)
  assert.match(dialog, /stored\.maxDepth \?\? snapshot\.maxDepth/)
  assert.match(dialog, /DENSITY_VALUES\.has\(stored\.density\)/)
  assert.match(dialog, /const taskConfigurationLocked = computed/)
  assert.match(dialog, /snapshot\.intent === 'discuss'[\s\S]*storedEditIntent \|\| 'create'/)
  const bindings = {
    running: ref(false), job: ref({ status: 'completed_direct' }),
    retryAvailable: ref(false), followupAvailable: ref(true), discussionMode: ref(true),
  }
  assert.equal(computedValue('composerPlaceholder', bindings), '基于当前脑图继续讨论，不应用任何变更…')
  bindings.discussionMode.value = false
  assert.equal(computedValue('composerPlaceholder', bindings), '继续调整刚才的脑图…')
})

test('统一输入框覆盖新建、运行中排队、重试和继续，不再挂载隐藏的重复输入面板', async () => {
  const template = parse(dialog).descriptor.template.content
  assert.doesNotMatch(template, /class="(?:retryPanel|followupPanel)"|v-model="(?:retryPrompt|followupPrompt)"/)
  assert.equal((template.match(/v-model="composerText"/g) || []).length, 1)
  const bindings = {
    form: { prompt: 'new' }, job: ref(null), running: ref(false),
    retryAvailable: ref(false), followupAvailable: ref(false),
    runningPrompt: ref('queued'), retryPrompt: ref('retry'), followupPrompt: ref('followup'),
  }
  const composer = new Function('computed', ...Object.keys(bindings),
    `return ${declaration(dialog, 'composerText', { initializer: true })}`,
  )(value => value, ...Object.values(bindings))
  const calls = []
  const composerCanSend = ref(true)
  const send = executeFunction('sendComposerMessage', {
    ...bindings, composerCanSend,
    submitJob: async () => calls.push('new'), queueRunningMessage: async () => calls.push('queued'),
    retryJob: async () => calls.push('retry'), continueJob: async () => calls.push('followup'),
  })
  for (const mode of ['new', 'queued', 'retry', 'followup']) {
    bindings.job.value = mode === 'new' ? null : { id: 'job' }
    bindings.running.value = mode === 'queued'
    bindings.retryAvailable.value = mode === 'retry'
    bindings.followupAvailable.value = mode === 'followup'
    assert.equal(composer.get(), mode)
    composer.set(`edited-${mode}`)
    const stored = mode === 'new' ? bindings.form.prompt
      : bindings[`${{ queued: 'running', retry: 'retry', followup: 'followup' }[mode]}Prompt`].value
    assert.equal(stored, `edited-${mode}`)
    await send()
    composerCanSend.value = false
    await send()
    composerCanSend.value = true
  }
  assert.deepEqual(calls, ['new', 'queued', 'retry', 'followup'])
})

test('统一输入框仍执行人工编辑锁与操作互斥，运行中仅允许排队消息', () => {
  for (const mode of ['new', 'running', 'retry', 'followup', 'closed']) {
    for (const actionBusy of [false, true]) {
      for (const blocked of [false, true]) {
        const enabled = computedValue('composerEnabled', {
          actionBusy: ref(actionBusy), livePreviewCanvasMutationBlocked: ref(blocked),
          job: ref(mode === 'new' ? null : { id: 'job' }),
          running: ref(mode === 'running'), retryAvailable: ref(mode === 'retry'),
          followupAvailable: ref(mode === 'followup'),
        })
        assert.equal(enabled, !actionBusy && mode !== 'closed' && (!blocked || mode === 'running'), mode)
      }
    }
  }
})

test('提案重载与编辑锁状态请求直接绑定生产处理器，卸载解除同一个回调', () => {
  assert.match(dialog, /@click="loadProposal"/)
  assert.match(dialog, /bus\.on\('aiEditingStateRequest', emitAiEditingState\)/)
  assert.match(dialog, /bus\.off\('aiEditingStateRequest', emitAiEditingState\)/)
  assert.doesNotMatch(dialog, /(?:function|@click=")\s*(?:reloadProposal|onAiEditingStateRequest)/)
  const emitted = []
  const bindings = {
    job: ref({ id: 'job' }), form: { sourceMode: 'current' },
    messageModeActive: ref(false), viewingHistoricalArtifact: ref(false), sourceContext: ref({ readonly: false }),
    running: ref(false), livePreviewActive: ref(false), livePreviewRendering: ref(false),
    livePreviewReverting: ref(false), livePreviewAutoAccepting: ref(false), applying: ref(false),
    cancelling: ref(false), preparingCanvas: ref(true), directCanvasOwned: ref(false),
    bus: { emit: (event, payload) => emitted.push({ event, payload }) },
  }
  const emitState = executeFunction('emitAiEditingState', bindings)
  emitState({ ignored: 'event payload' })
  bindings.preparingCanvas.value = false
  bindings.directCanvasOwned.value = true
  emitState()
  bindings.directCanvasOwned.value = false
  emitState()
  assert.deepEqual(emitted, [true, true, false].map(locked => ({
    event: 'aiEditingState', payload: { jobId: 'job', locked },
  })))
})

test('退役面板专属样式已删除，表单使用同一组响应式网格声明', () => {
  const { descriptor } = parse(dialog)
  const styles = descriptor.styles.map(style => style.content).join('\n')
  assert.doesNotMatch(styles, /\.(?:retryPanel|followupPanel|retryActions|followupActions|compactGrid)\b/)
  assert.doesNotMatch(descriptor.template.content, /\bcompactGrid\b/)
  assert.match(styles, /\.formGrid \{[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(styles, /@media \(max-width: 760px\)[\s\S]*\.formGrid \{ grid-template-columns: 1fr; \}/)
})

test('终态任务始终以复校验后的 artifact 覆盖临时草稿预览', () => {
  const fallbackBlock = declaration(dialog, 'restoreTerminalPreview')
  assert.match(fallbackBlock, /await refreshDraftPreview\(jobId\)/)
  assert.doesNotMatch(fallbackBlock, /restoredDraft[\s\S]*?\|\| recoveryGeneration/)
  assert.match(fallbackBlock, /!job\.value\?\.artifactId/)
  assert.match(fallbackBlock, /await loadArtifact\(\{ requirePassed: false, artifactId \}\)/)
  assert.match(fallbackBlock, /job\.value\?\.artifactId !== artifactId/)
  assert.match(fallbackBlock, /draftDocument\.value = cloneRuntimeValue\(document\)/)
  assert.match(declaration(dialog, 'restoreActiveJob'), /await finalizeTerminalJob\(job\.value\.id, \{ recoveryGeneration: generation/)
  assert.match(declaration(dialog, 'finalizeTerminalJob'), /await hydrateTerminalResources\(jobId, \{ recoveryGeneration \}\)/)
})

test('权威轮询和终态响应会清除已经过时的实时连接告警', () => {
  const pollBlock = dialog.slice(dialog.indexOf('async function pollJob'), dialog.indexOf('function scheduleRealtimeReconnect'))
  assert.match(pollBlock, /mergeMindmapAiJobSnapshot\(job\.value, response\.data\)[\s\S]*realtimeError\.value = ''[\s\S]*refreshDraftPreview/)
  assert.match(dialog, /if \(isTerminalStatus\(job\.value\.status\)\) \{[\s\S]*realtimeConnectionState\.value = 'completed'[\s\S]*realtimeError\.value = ''/)
})

test('本地应用回执存储失败时直接发送，双重失败不会伪装成持久队列', () => {
  const ackBlock = dialog.slice(
    dialog.indexOf('async function queueLocalAck'),
    dialog.indexOf('async function recoverLocalApplyAckFromContext'),
  )
  assert.match(ackBlock, /ackMindmapAiLocalUndo : ackMindmapAiLocalApply[\s\S]*catch \(storageError\)[\s\S]*await send\(proposalId, payload\)/)
  assert.match(ackBlock, /receiptUnstored: true/)
  assert.doesNotMatch(ackBlock, /return \{ sent: 0, pending: 1 \}/)
  assert.match(dialog, /await recoverLocalApplyAckFromContext\(context\)/)
  assert.match(dialog, /context\?\.lastAppliedProposal[\s\S]*context\?\.documentHash/)
  assert.match(dialog, /提案已应用但回执未保存；请恢复网络后重新打开 AI 面板重试/)
})

test('暂时失败的本地应用回执会在线指数退避重试并在离线时暂停', () => {
  assert.match(dialog, /listMindmapAiLocalAcks/)
  assert.match(dialog, /LOCAL_ACK_RETRY_BASE_MS/)
  assert.match(dialog, /LOCAL_ACK_RETRY_MAX_MS/)
  assert.match(dialog, /function scheduleLocalAckRetry\(\)[\s\S]*navigator\.onLine[\s\S]*2 \*\* Math\.min\(attempts, 10\)/)
  assert.match(dialog, /if \(result\.pending > 0\) scheduleLocalAckRetry\(\)/)
  assert.match(dialog, /if \(result\.sent > 0 && job\.value\?\.id\) \{[\s\S]*schedulePoll\(0, true\)/)
  assert.match(dialog, /function onNetworkOffline\(\) \{[\s\S]*clearLocalAckRetryTimer\(\)/)
  assert.match(dialog, /onBeforeUnmount\(\(\) => \{[\s\S]*clearLocalAckRetryTimer\(\)/)
  const ackApis = api.slice(
    api.indexOf('export function ackMindmapAiLocalApply'),
    api.indexOf('export function saveMindmapAiArtifactCloud'),
  )
  assert.equal((ackApis.match(/silentError: true/g) || []).length, 2)
  assert.match(dialog, /本地 AI 回执已被服务端拒绝[\s\S]*请人工确认任务与当前脑图状态/)
})

test('本地 AI 整图历史禁止普通 BACK 生成旧 root 与新元数据的混合态', () => {
  assert.match(editor, /function guardLocalAiHistoryBack\(commandName, sourceMindMap\)/)
  assert.match(editor, /sourceMindMap\.command\?\.flushPendingHistory\?\.\(\)/)
  assert.match(editor, /本次 AI 整图变更包含文档设置[\s\S]*撤销本次 AI 应用/)
  assert.match(editor, /addExecutionGuard\?\.\(\(name\) => guardLocalAiHistoryBack\(name, mm\)\)/)
})

test('提案差异加载失败在终态可见并支持原位重试', () => {
  assert.match(dialog, /v-if="!messageModeActive && proposalError" class="proposalLoadFailure"/)
  assert.match(dialog, /:loading="proposalLoading"[\s\S]*@click="loadProposal"/)
  assert.match(dialog, /proposalError\.value = formatMindmapAiError\(error, '无法加载 AI 提案差异'\)/)
  assert.match(dialog, /finally \{[\s\S]*proposalLoading\.value = false/)
})

test('本地快照把浏览器计算的基线 hash 一并交给服务端复核', () => {
  assert.match(dialog, /type: 'local_snapshot',[\s\S]*documentHash: sourceFingerprint\.value/)
})

test('创建、继续和另存请求按 payload 指纹管理幂等尝试', () => {
  assert.match(dialog, /resolveDurableAttempt\('create', submitAttempt, requestPayload/)
  assert.match(dialog, /\{ parentJobId, requestPayload \}/)
  assert.match(dialog, /resolveDurableAttempt\('save', saveCloudAttempt, requestPayload/)
  assert.match(dialog, /function writePersistedAttempts[\s\S]*writeMindmapAiOwnerSessionItem\([\s\S]*ATTEMPTS_STORAGE_KEY,[\s\S]*ownerUserId,[\s\S]*JSON\.stringify\(attempts\)/)
  assert.match(dialog, /if \(!writePersistedAttempts\(persistedAttempts\)\)[\s\S]*已阻止发送以避免重复任务/)
  assert.match(declaration(dialog, 'activateCreatedJob'), /if \(persistActiveJob\(\)\) clearDurableAttempt\('create', attemptKey\)/)
  assert.match(dialog, /async function activateFollowupJob[\s\S]*const pointerPersisted = persistActiveJob\(\)[\s\S]*if \(pointerPersisted\) clearDurableAttempt\('followup', attemptKey\)[\s\S]*beginJobMonitoring/)
  assert.doesNotMatch(dialog, /submitIdempotencyKey|followupIdempotencyKey|saveCloudIdempotencyKey/)
})

test('提案加载自行处理异步错误而不会产生未处理拒绝', () => {
  assert.match(dialog, /async function loadProposal\(\) \{[\s\S]*try \{[\s\S]*await getMindmapAiProposal[\s\S]*catch \(error\)/)
  assert.match(dialog, /proposalError\.value = formatMindmapAiError\(error, '无法加载 AI 提案差异'\)/)
})

test('终态资源水合具有有界自动重试、联网恢复和显式重试入口', () => {
  assert.match(dialog, /const TERMINAL_HYDRATION_RETRY_DELAYS = \[800, 1800, 4000\]/)
  assert.match(dialog, /async function hydrateTerminalResources[\s\S]*artifactReady[\s\S]*proposalReady[\s\S]*needsInputReady/)
  assert.match(dialog, /function scheduleTerminalHydrationRetry[\s\S]*TERMINAL_HYDRATION_RETRY_DELAYS\.length/)
  assert.match(dialog, /@click="retryTerminalHydration"[\s\S]*重新同步完成结果/)
  assert.match(dialog, /async function onNetworkOnline[\s\S]*retryTerminalHydration\(\)/)
})

test('写操作共享互斥、固定请求身份并在未知结果后主动对账', () => {
  assert.match(dialog, /const actionBusy = computed/)
  assert.match(dialog, /function beginActionIdentity/)
  assert.match(dialog, /function assertActionIdentity/)
  assert.match(dialog, /async function reconcileJobAfterSideEffect[\s\S]*getMindmapAiJob[\s\S]*refreshTimelineAfterSideEffect/)
  assert.match(dialog, /`mindmap-ai-apply:\$\{proposalId\}`/)
  assert.match(dialog, /`mindmap-ai-undo:\$\{proposalId\}`/)
})

test('恢复先结算本地 ACK 后再拉取权威任务状态', () => {
  const restoreBlock = dialog.slice(
    dialog.indexOf('async function restoreActiveJob'),
    dialog.indexOf('function retryStoredJobRecovery'),
  )
  assert.match(restoreBlock, /await flushLocalApplyAcks\(\)[\s\S]*getMindmapAiJob/)
})

test('本地 ACK 与云端对账 outbox 都按当前登录账号隔离', () => {
  assert.match(dialog, /const userStore = useUserStore\(\)/)
  assert.match(dialog, /function currentAiOwnerUserId\(\)/)
  assert.match(dialog, /enqueueMindmapAiLocalAck\(\{[\s\S]*ownerUserId,/)
  assert.match(dialog, /flushMindmapAiLocalAcks\([\s\S]*\}, ownerUserId\)/)
  assert.match(dialog, /listMindmapAiCloudMutationIntents\(ownerUserId\)/)
  assert.match(dialog, /enqueueMindmapAiCloudMutationIntent\(\{[\s\S]*ownerUserId: currentAiOwnerUserId\(\),/)
  assert.match(dialog, /const cloudMutationFlushPromises = new Map\(\)/)
  assert.match(dialog, /cloudMutationFlushPromises\.get\(ownerUserId\)/)
  assert.match(dialog, /ownerUserId: intent\.ownerUserId,/)
  assert.match(dialog, /async function onCloudMutationRecoveryReady[\s\S]*await activeFlush[\s\S]*listMindmapAiCloudMutationIntents\(ownerUserId\)[\s\S]*await flushPendingCloudMutationIntents\(\)/)
  assert.match(dialog, /function beginActionIdentity[\s\S]*ownerUserId: currentAiOwnerUserId\(\)/)
  assert.match(dialog, /function actionIdentityMatches[\s\S]*identity\.ownerUserId !== currentAiOwnerUserId\(\)/)
  assert.match(dialog, /function readPersistedAttempts[\s\S]*item\?\.ownerUserId === ownerUserId/)
  assert.match(dialog, /readMindmapAiOwnerSessionItem\(ATTEMPTS_STORAGE_KEY, ownerUserId\)/)
  assert.match(dialog, /writeMindmapAiOwnerSessionItem\([\s\S]*ATTEMPTS_STORAGE_KEY,[\s\S]*ownerUserId/)
  assert.match(dialog, /readMindmapAiOwnerSessionItem\(ACTIVE_JOB_STORAGE_KEY, ownerUserId\)/)
  assert.match(dialog, /clearMindmapAiOwnerSessionItem\(ACTIVE_JOB_STORAGE_KEY, currentAiOwnerUserId\(\)\)/)
  assert.match(dialog, /async function resolveDurableAttempt[\s\S]*ownerUserId,/)
  assert.match(dialog, /function persistActiveJob[\s\S]*const storedJob = \{[\s\S]*ownerUserId,/)
  assert.match(dialog, /const isUsableStoredJob = candidate => Boolean\([\s\S]*candidate\.ownerUserId === ownerUserId/)
  assert.match(dialog, /watch\(\(\) => userStore\.id,[\s\S]*resetNewJob\(\{ clearStoredJob: false, preserveForm: true, detach: true \}\)/)
})

test('副作用后刷新时间线', () => {
  assert.match(dialog, /async function refreshTimelineAfterSideEffect/)
  assert.match(dialog, /async function applyProposal[\s\S]*await refreshTimelineAfterSideEffect\(identity\)/)
  assert.match(dialog, /async function saveCloud[\s\S]*await refreshTimelineAfterSideEffect\(identity\)/)
  assert.match(dialog, /async function undoProposal[\s\S]*await refreshTimelineAfterSideEffect\(identity\)/)
})

test('draft 状态来自 artifact manifest，终态与历史轮次均可只读预览', () => {
  assert.match(dialog, /artifact\?\.manifest\?\.validation\?\.status/)
  assert.match(dialog, /function isDraftArtifact/)
  assert.match(dialog, /const draftSuffix = isDraftArtifact\(artifactId\)/)
  assert.match(dialog, /const sessionTurns = ref\(\[\]\)/)
  assert.match(dialog, /v-for="turn in artifactTurns"/)
  assert.match(dialog, /async function selectSessionTurn[\s\S]*requirePassed: false/)
  assert.match(dialog, /const followupParentJob = computed/)
})

test('编辑器动态报告只读与本地 undo 能力，离线期间不启动轮询', () => {
  assert.match(editor, /canUndoAiProposal = Boolean\([\s\S]*undoSnapshot\?\.proposalId === lastAppliedProposal[\s\S]*undoSnapshot\?\.appliedRevision[\s\S]*undoSnapshot\?\.resultHash === documentHash/)
  assert.match(editor, /undoableAiProposalId = canUndoAiProposal \? lastAppliedProposal : null/)
  assert.match(dialog, /const canUndoCurrentProposal = computed/)
  assert.match(dialog, /watch\(\(\) => props\.readonly, async/)
  assert.match(dialog, /function schedulePoll[\s\S]*!navigator\.onLine[\s\S]*return/)
  assert.match(dialog, /function onNetworkOffline[\s\S]*stopPolling\(\)/)
})

test('显式入口 preset 优先，recent 只补非显式默认值且 active 仍优先恢复', () => {
  assert.match(dialog, /const explicitPreset = normalizeDialogPreset\(preset\)/)
  assert.match(dialog, /SCOPE_TYPE_VALUES\.has\(preset\.scopeType\)[\s\S]*normalized\.scopeType = preset\.scopeType/)
  assert.match(dialog, /applyRecentJobDefaults\(explicitPreset\)[\s\S]*applyDialogPreset\(explicitPreset\)/)
  assert.match(dialog, /if \(!preset \|\| readUsableStoredJob\(ACTIVE_JOB_STORAGE_KEY\)\) return false/)
  assert.match(dialog, /if \(!explicitFields\.has\(field\)[\s\S]*form\[field\] = configuration\[field\]/)
  assert.match(dialog, /allowRecent: !explicitPreset/)
  assert.match(dialog, /if \(explicitPreset\) pendingDialogPreset = explicitPreset/)
  assert.match(dialog, /function startNewJob\(\)[\s\S]*applyDialogPreset\(pendingDialogPreset\)/)
})

test('继续生成 attempt 通过原 key、parent、session、turn 与已知 job 精确恢复', () => {
  assert.match(dialog, /const ATTEMPTS_STORAGE_KEY = 'MINDMAP_AI_REQUEST_ATTEMPTS_V1'/)
  assert.match(dialog, /async function hashAttemptFingerprint[\s\S]*return sha256Hex\(bytes\)/)
  assert.match(dialog, /async function resolveDurableAttempt[\s\S]*fingerprintHash/)
  assert.match(dialog, /metadata: \{[\s\S]*parentJobId,[\s\S]*parentTurnIndex,[\s\S]*sessionId: parentJob\.sessionId,[\s\S]*knownMaxTurnIndex:[\s\S]*knownJobIds:[\s\S]*requestPayload/)
  assert.match(dialog, /async function replayFollowupAttempt[\s\S]*reconcileMindmapAiJob\(attempt\.key[\s\S]*isHttpNotFound\(error\)[\s\S]*attempt\.parentJobId,[\s\S]*attempt\.requestPayload,[\s\S]*attempt\.key/)
  assert.match(dialog, /persistedRequestPayload = continuationBase === 'current_snapshot'[\s\S]*source: undefined[\s\S]*requestPayload: persistedRequestPayload/)
  assert.match(dialog, /function assertFollowupAttemptResult[\s\S]*candidateParentId !== parentJobId[\s\S]*candidateSessionId !== String\(expectedSessionId\)[\s\S]*turnIndex \|\| 0\) <= knownMaxTurnIndex[\s\S]*knownJobIds\.has\(candidateId\)/)
  assert.doesNotMatch(dialog, /recoverLatestSessionChild/)
})

test('时间线恢复会提升权威最新 child，并对运行轮次重新启动监控', () => {
  assert.match(dialog, /function latestSessionTurn/)
  assert.match(dialog, /latestTurn\.job\.id !== initialJobId[\s\S]*getMindmapAiJob\(latestTurn\.job\.id/)
  assert.match(dialog, /job\.value = latestResponse\.data/)
  assert.match(dialog, /if \(isTerminalStatus\(job\.value\.status\)\)[\s\S]*else \{[\s\S]*beginJobMonitoring\(\)/)
  assert.match(dialog, /function retrySessionTimeline[\s\S]*restoreActiveJob\(\{ generation: restoreGeneration, allowRecent: true \}\)/)
})

test('无任务指针时按持久化 create attempt 对账并复用标准恢复链路', () => {
  const restoreBlock = dialog.slice(
    dialog.indexOf('async function restoreActiveJob'),
    dialog.indexOf('function retryStoredJobRecovery'),
  )
  assert.match(
    restoreBlock,
    /if \(!saved\) \{[\s\S]*const persistedAttempts = readPersistedAttempts\(\)[\s\S]*createAttempt = persistedAttempts\.create/,
  )
  assert.match(
    restoreBlock,
    /reconcileMindmapAiJob\(createAttempt\.key, \{ signal: controller\.signal \}\)/,
  )
  assert.match(
    restoreBlock,
    /isHttpNotFound\(error\)[\s\S]*restoreDurableAttemptNotice\(\)[\s\S]*return false/,
  )
  const persistPointerIndex = restoreBlock.indexOf('if (!persistActiveJob())')
  const clearCreateAttemptIndex = restoreBlock.indexOf("clearDurableAttempt('create', createAttempt.key)")
  const restoreTimelineIndex = restoreBlock.indexOf('await restoreSessionTimeline')
  assert.ok(persistPointerIndex >= 0)
  assert.ok(clearCreateAttemptIndex > persistPointerIndex)
  assert.ok(restoreTimelineIndex > clearCreateAttemptIndex)
  assert.equal(clearCreateAttemptIndex, restoreBlock.lastIndexOf("clearDurableAttempt('create', createAttempt.key)"))
  assert.match(restoreBlock, /!componentAlive[\s\S]*generation !== restoreGeneration[\s\S]*restoreController !== controller/)
  assert.match(
    dialog,
    /metadata: \{[\s\S]*sourceRevision:[\s\S]*sourceFingerprint:[\s\S]*configuration: requestConfiguration/,
  )
})

test('失败任务通过正式 retry 新建同会话轮次并可切换 Agent', () => {
  assert.match(api, /export function retryMindmapAiJob\(jobId, data, idempotencyKey/)
  assert.match(api, /`\/mindmap\/ai\/jobs\/\$\{jobId\}\/retry`/)
  assert.match(dialog, /const retryableStatuses = new Set\(\['failed', 'cancelled', 'expired', 'stale'\]\)/)
  assert.match(dialog, /if \(retryAvailable\.value\) return retryPrompt\.value/)
  assert.match(dialog, /@click="sendComposerMessage"/)
  assert.match(dialog, /if \(!job\.value\) await submitJob\(\)[\s\S]*else if \(retryAvailable\.value\) await retryJob\(\)[\s\S]*else if \(followupAvailable\.value\) await continueJob\(\)/)
  assert.match(dialog, /requestPayload = \{[\s\S]*agentKey: form\.agentKey,[\s\S]*modelId:[\s\S]*prompt: retryPrompt\.value\.trim\(\) \|\| undefined/)
})

test('重试 attempt 以 retryOf、session、turn 和新 job 精确对账并可恢复', () => {
  assert.match(dialog, /resolveDurableAttempt\([\s\S]*'retry',[\s\S]*retryOfJobId: retriedJob\.id/)
  assert.match(dialog, /function assertRetryAttemptResult[\s\S]*candidateRetryOfJobId !== retryOfJobId[\s\S]*candidateParentJobId[\s\S]*candidateSessionId !== String\(expectedSessionId\)[\s\S]*knownJobIds\.has\(candidateId\)/)
  assert.match(dialog, /async function replayRetryAttempt[\s\S]*attempt\.retryOfJobId,[\s\S]*attempt\.requestPayload,[\s\S]*attempt\.key/)
  assert.match(dialog, /persistedAttempts\.retry\?\.key[\s\S]*jobId: persistedAttempts\.retry\.retryOfJobId/)
  assert.match(dialog, /reconciledRetryAttemptKey[\s\S]*clearDurableAttempt\('retry', reconciledRetryAttemptKey\)/)
  assert.match(dialog, /if \(pointerPersisted\) clearDurableAttempt\('retry', attemptKey\)/)
})

test('needs_input 作为不可复活终态展示问题并通过继续接口创建新轮次', () => {
  assert.match(dialog, /const terminalStatuses = new Set\([\s\S]*'needs_input'/)
  assert.match(dialog, /const retryableStatuses = new Set\(\['failed', 'cancelled', 'expired', 'stale'\]\)/)
  assert.match(dialog, /const needsInputQuestions = computed\([\s\S]*event\.eventType === 'needs_input'/)
  assert.match(dialog, /v-for="question in needsInputQuestions"/)
  assert.match(dialog, /当前轮次保持终态，不会被重新启动/)
  assert.match(dialog, /candidate\?\.status === 'needs_input' && !candidate\.artifactId/)
  assert.match(dialog, /!parentJob\.artifactId[\s\S]*parentJob\.status !== 'needs_input'[\s\S]*isMindmapAiMessageJob\(parentJob\)/)
  assert.match(dialog, /artifactId: continuationBase === 'artifact'[\s\S]*parentJob\.artifactId \|\| undefined/)
  assert.match(dialog, /await continueMindmapAiJob\([\s\S]*parentJobId,[\s\S]*requestPayload/)
  assert.match(dialog, /payload\.sessionMode === 'new'[\s\S]*补充信息任务[·\s]*使用全新 Agent 会话/)
  assert.match(dialog, /followupParentJob\.value\.status !== 'needs_input'[\s\S]*needsInputQuestions\.value\.length > 0/)
  assert.match(dialog, /job\.value\.status !== 'needs_input' \|\| needsInputQuestions\.value\.length > 0/)
  assert.match(dialog, /await restoreSessionTimeline\(job\.value\.sessionId,[\s\S]*needsInputReady = needsInputQuestions\.value\.length > 0/)
})
