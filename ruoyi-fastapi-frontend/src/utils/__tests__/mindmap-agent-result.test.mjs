import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { parse, babelParse, compileTemplate } from '@vue/compiler-sfc'
import { mindmapAgentResultState as result, mindmapResultChangeCounts as counts } from '../mindmap-agent-result.js'

test('生成、保存中、保存失败和成功回执是不同结果状态', () => {
  const job = { id: 'j1', status: 'ready', proposalId: 'p1' }
  assert.equal(result({ job }).label, '待保存')
  assert.match(result({ job }).description, /保存尚未确认/)
  assert.equal(result({ job, saving: true }).label, '保存中')
  assert.equal(result({ job, saveFailed: true }).label, '待恢复')
  assert.equal(result({ job, saving: true, saveFailed: true }).label, '保存中')
  assert.equal(result({ job: { ...job, status: 'applied' }, sourceIsCloud: true, saving: true, saveFailed: true }).label, '已保存')
  assert.equal(result({ job: { ...job, status: 'applied' } }).label, '已应用')
  assert.match(result({ job: { ...job, status: 'applied' } }).description, /本地/)
})

test('新建结果、另存和直写回执不冒充当前脑图的保存/同步', () => {
  assert.equal(result({ job: { status: 'ready' } }).label, '已生成')
  assert.match(result({ job: { status: 'completed_file' } }).description, /不表示覆盖了当前脑图/)
  const direct = result({ job: { status: 'completed_direct' }, catchingUp: true })
  assert.equal(direct.label, '已提交')
  assert.match(direct.description, /画布同步和执行器退出状态单独确认/)
  assert.match(direct.canvasNote, /正在补齐/)
})

test('生成结果和保存结果不从执行器状态推断', () => {
  for (const executionState of ['running', 'unknown', 'unconfirmed', 'stopped', 'not_started']) {
    assert.equal(result({ job: { status: 'ready', proposalId: 'p', executionState } }).label, '待保存')
    assert.equal(result({ job: { status: 'applied', executionState }, sourceIsCloud: true }).label, '已保存')
  }
})

test('部分失败、中断和停止请求不声明回滚或保存成功', () => {
  for (const status of ['failed', 'stale', 'cancelled', 'expired']) {
    assert.equal(result({ job: { status }, direct: true }).label, '请核对结果')
    assert.match(result({ job: { status }, direct: true }).description, /不会.*自动回滚/)
    assert.match(result({ job: { status } }).description, /以保存回执为准/)
  }
  assert.equal(result({ job: { status: 'cancel_requested' } }).label, '停止中')
  assert.equal(result({ job: { status: 'undone' } }).label, '已撤销')
  assert.equal(result({ job: { status: 'undone' }, undoing: true }).label, '处理中')
  assert.equal(result({ job: { status: 'rejected' } }).label, '未采纳')
  assert.equal(result({ job: { status: 'completed_no_change' } }).label, '无变更')
})

test('高风险待确认、补充信息和未知状态不伪造运行或成功', () => {
  assert.equal(result({ job: { status: 'needs_review' } }).label, '待确认')
  assert.equal(result({ job: { status: 'needs_input' } }).label, '待补充')
  for (const status of ['queued', 'waiting_turn', 'preparing']) assert.equal(result({ job: { status } }).label, '准备中')
  assert.equal(result({ job: null }).label, '待确认')
  assert.equal(result().label, '待确认')
  assert.equal(result({ job: { status: 'provider_specific_unknown' } }).label, '待确认')
  assert.equal(result({ job: { status: 'running' }, direct: true }).label, '编辑中')
  assert.match(result({ job: { status: 'running' }, direct: true }).description, /关闭面板不会停止任务，停止也不会撤销已提交内容/)
  assert.equal(result({ job: { status: 'validating' }, livePreviewActive: true }).label, '生成中')
})

test('历史结果不使用当前任务的保存、撤销或画布追赶状态', () => {
  const state = result({ historical: true, job: { status: 'applied' }, sourceIsCloud: true,
    saving: true, saveFailed: true, undoing: true, reverting: true, catchingUp: true })
  assert.equal(state.label, '历史结果')
  assert.match(state.description, /不改变当前脑图/)
  assert.equal(state.canvasNote, '')
})

test('只有四项完整、非负安全整数的实际计数才显示统计', () => {
  const input = { createdCount: 0, updatedCount: 1, movedCount: 2, deletedCount: 3 }
  assert.deepEqual(counts(input), input)
  assert.notEqual(counts(input), input)
  for (const invalid of [null, undefined, '0', '', false, true, -1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(counts({ ...input, deletedCount: invalid }), null)
  }
  assert.equal(counts(null), null)
  assert.equal(counts({ direct: true }), null)
})

const dialog = await readFile(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const { descriptor } = parse(dialog)
const ast = babelParse(descriptor.scriptSetup.content, { sourceType: 'module' })
function computedValue(name, bindings) {
  const item = ast.program.body.flatMap(node => node.declarations || []).find(node => node.id.name === name)
  assert.ok(item, name)
  return new Function('computed', ...Object.keys(bindings), `return ${descriptor.scriptSetup.content.slice(item.init.start, item.init.end)}`)(fn => fn(), ...Object.values(bindings))
}
const ref = value => ({ value })

test('实际工作台把结果及原有操作收敛到滚动主体，固定输入区不再含结果按钮', () => {
  const compiled = compileTemplate({ source: descriptor.template.content, filename: 'MindmapAiDialog.vue', id: 'result-test' })
  assert.deepEqual(compiled.errors, [])
  const cardStart = dialog.indexOf('<MindmapAgentResultCard')
  const cardEnd = dialog.indexOf('</MindmapAgentResultCard>')
  const footer = dialog.indexOf('<template #footer>')
  assert.ok(cardStart > 0 && cardEnd > cardStart && cardEnd < footer)
  const card = dialog.slice(cardStart, cardEnd)
  for (const action of ['downloadArtifact', 'openArtifactAsLocal', 'replaceLocalWithArtifact', 'insertArtifactBranch', 'saveCloud', 'rejectLiveDraft', 'applyProposal()', 'undoProposal', 'retry: true']) {
    assert.ok(card.includes(action), action)
  }
  assert.match(card, /:counts="viewingHistoricalArtifact \? null : resultChangeCounts"/)
  assert.match(card, /proposal && !viewingHistoricalArtifact/)
  assert.doesNotMatch(dialog.slice(footer, dialog.indexOf('</el-drawer>')), /@(click)="(?:undoProposal|downloadArtifact|saveCloud|rejectLiveDraft)/)
  assert.doesNotMatch(dialog, /当前结果已经保存|结果已完成并保存到当前脑图|结果已保存，可撤销本轮 AI 修改/)
})

test('实际结果投影使用任务来源回执，即使云端上下文尚未恢复也不误报本地', () => {
  const bindings = { mindmapAgentResultState: result, job: ref({ id: 'j', status: 'applied', sourceType: 'cloud_document' }),
    sourceContext: ref(null), isDirectExecutionJob: () => false, applying: ref(false), livePreviewAutoAccepting: ref(false),
    savingCloud: ref(false), livePreviewAutoAcceptFailedJobId: ref(''), undoing: ref(false), livePreviewReverting: ref(false),
    livePreviewActive: ref(false), livePreviewCatchingUp: ref(false) }
  assert.equal(computedValue('currentResultState', bindings).label, '已保存')
  bindings.job.value = { id: 'j', status: 'ready', proposalId: 'p' }
  bindings.livePreviewAutoAcceptFailedJobId.value = 'j'
  assert.equal(computedValue('currentResultState', bindings).label, '待恢复')
})

test('结果卡不在空态/纯讨论出现，历史选择不会借用当前 proposal 显示结果', () => {
  const bindings = { messageModeActive: ref(false), job: ref(null), viewingHistoricalArtifact: ref(false),
    selectedArtifactJob: ref(null), proposal: ref(null), livePreviewActive: ref(false), isDirectExecutionJob: () => false }
  const visible = () => computedValue('resultCardVisible', bindings)
  assert.equal(visible(), false)
  bindings.job.value = { status: 'running' }
  assert.equal(visible(), false)
  bindings.livePreviewActive.value = true
  assert.equal(visible(), true)
  bindings.messageModeActive.value = true
  assert.equal(visible(), false)
  bindings.messageModeActive.value = false
  bindings.viewingHistoricalArtifact.value = true
  bindings.proposal.value = { id: 'current' }
  assert.equal(visible(), false)
  bindings.selectedArtifactJob.value = { artifactId: 'old' }
  assert.equal(visible(), true)
})

test('直写任务的准备、运行、部分失败和停止都在唯一结果卡中展示，不依赖提案已加载', () => {
  const bindings = { messageModeActive: ref(false), job: ref(null), viewingHistoricalArtifact: ref(false),
    selectedArtifactJob: ref(null), proposal: ref(null), livePreviewActive: ref(false),
    isDirectExecutionJob: () => bindings.job.value?.executionMode === 'direct' }
  for (const status of ['queued', 'preparing', 'running', 'validating', 'cancel_requested', 'failed', 'cancelled', 'completed_direct', 'completed_no_change']) {
    bindings.job.value = { id: 'current', status, executionMode: 'direct' }
    assert.equal(computedValue('resultCardVisible', bindings), true, status)
  }
  bindings.messageModeActive.value = true
  assert.equal(computedValue('resultCardVisible', bindings), false, 'discussion never implies document edits')
  bindings.messageModeActive.value = false
  bindings.viewingHistoricalArtifact.value = true
  assert.equal(computedValue('resultCardVisible', bindings), false, 'current direct state cannot invent a historical artifact')
})

test('工作台只有一处结果结论，技术 ID 折叠而恢复操作和运行进度不被隐藏', () => {
  const template = descriptor.template.content
  assert.doesNotMatch(template, /directExecutionNotice|class="jobHeader"/)
  assert.match(template, /<p v-if="running" class="jobActivitySummary">/)
  const details = template.match(/<details class="jobDetails">([\s\S]*?)<\/details>/)?.[1]
  assert.ok(details, 'technical metadata has a native disclosure')
  assert.match(details, /当前轮任务详情/)
  assert.match(details, /job.id/)
  assert.match(details, /statusLabel/)
  assert.doesNotMatch(details, /jobErrorMessage|retryTerminalHydration|needsInputQuestions|livePreviewError/)
  assert.match(template, /v-if="job.errorMessage \|\| job.errorCode"/)
  assert.match(template, /v-if="executionStopBlocked"/)
  assert.match(template, /v-if="livePreviewError && !canvasSyncStatus"/)
  const footer = template.slice(template.indexOf('<template #footer>'))
  assert.match(footer, /v-if="canvasSyncStatus"[^>]*id="mindmap-ai-canvas-recovery"[^>]*role="status"/)
  assert.match(footer, /canvasSyncStatus.description/)
  assert.match(footer, /@click="retryLivePreviewSync"/)
  assert.match(template, /@click="toggleLivePreviewPlayback\(\)"/)
})

test('失败工具先显示原因，再显示原始参数', async () => {
  const source = await readFile(new URL('../../components/MindMap/MindmapAgentToolRow.vue', import.meta.url), 'utf8')
  assert.ok(source.indexOf('class="toolError"') < source.indexOf('aria-label="工具调用参数"'))
})

test('历史回答的系统兜底不再将撤销、另存或 ready 描述为当前画布已展示', () => {
  const declaration = ast.program.body.find(node => node.type === 'FunctionDeclaration' && node.id.name === 'assistantMessageText')
  const message = new Function(`${descriptor.scriptSetup.content.slice(declaration.start, declaration.end)}; return assistantMessageText`)()
  assert.match(message({ job: { status: 'undone' } }), /已撤销/)
  assert.match(message({ job: { status: 'completed_file' } }), /另存.*不表示覆盖/)
  assert.match(message({ job: { status: 'applied' } }), /应用结果已确认/)
  assert.match(message({ job: { status: 'ready' } }), /已生成.*应用与保存状态/)
  assert.doesNotMatch(message({ job: { status: 'ready' } }), /当前画布已展示|已保存/)
  const turn = { job: { status: 'ready' }, events: [{ eventType: 'agent_completed', payload: { summary: { nodeCount: null } } }] }
  assert.doesNotMatch(message(turn), /共 0 个节点/)
  turn.events[0].payload.summary.nodeCount = 8
  assert.match(message(turn), /共 8 个节点/)
  assert.equal(message({ job: { status: 'ready' }, assistantMessage: { content: 'Agent 实际提供的正文' } }), 'Agent 实际提供的正文')
})
