<template>
  <main>
    <h1>Agent 停止切换验收</h1>
    <p>隔离样例：生产切换处理器、退出监视器及选择器；接口回执由下方按钮模拟，不连接后端或 Agent。</p>
    <label>确认时模拟目标变化
      <select v-model="targetFailure" :disabled="agentSwitchPending">
        <option value="none">保持可用</option><option value="disabled">目标 Agent 被禁用</option><option value="offline">目标电脑掉线</option><option value="queue">新增排队请求</option>
      </select>
    </label>
    <button :disabled="agentSwitchPending" @click="requestSwitch({ agentKey: 'device_codex', deviceId: 'fixture-device' })">切换到测试电脑 Codex</button>
    <MindmapAgentExecutionPicker ref="agentExecutionPickerRef" :agent-key="form.agentKey" :device-id="form.deviceId" :agents="agents"
      :disabled="agentSwitchPending || executionStop.blocked.value" :running="running" :current-job="job"
      :catalog="deviceCatalog" @select="requestSwitch" />
    <p role="status">{{ agentSwitchPhase || status }}</p>
    <label>未发送的下一条要求<textarea v-model="draft" /></label>
    <button :disabled="agentSwitchPending || running || executionStop.blocked.value || !canvasReady">发送（样例不执行）</button>
    <nav aria-label="模拟后端回执">
      <button :disabled="!agentSwitchPending || job.executionState === 'stopped'" @click="confirmExit">模拟旧 Agent 退出</button>
      <button :disabled="!settling" @click="finishCanvas(true)">模拟脑图同步成功</button>
      <button :disabled="!settling" @click="finishCanvas(false)">模拟脑图同步失败</button>
    </nav>
    <pre aria-label="验收状态">{{ JSON.stringify({ selectedAgent: form.agentKey, boundAgent: job.agentKey,
      jobStatus: job.status, executionState: job.executionState, pending: agentSwitchPending,
      confirmationCount, cancellationCount, draft, changedCount, targetFailure,
      targetDeviceStatus: deviceCatalog.devices[0].status }, null, 2) }}</pre>
  </main>
</template>
<script setup>
import { computed, h, nextTick, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MindmapAgentExecutionPicker from '../../../components/MindMap/MindmapAgentExecutionPicker.vue'
import MindmapAgentHandoffSummary from '../../../components/MindMap/MindmapAgentHandoffSummary.vue'
import { projectAgentHandoff } from '../../mindmap-agent-handoff.js'
import { mindmapAgentResultState } from '../../mindmap-agent-result.js'
import dialogSource from '../../../components/MindMap/MindmapAiDialog.vue?raw'
import { useMindmapExecutionStop } from '../../use-mindmap-execution-stop.js'
import { isMindmapExecutionBlocked } from '../../mindmap-execution-state.js'
import { isDeviceAgent, agentExecutionLocation, deviceExecutionIssue } from '../../mindmap-agent-devices.js'

const form = reactive({ agentKey: 'claude', deviceId: '' })
const agents = ref(['claude', 'codex', 'kimi', 'device_codex'].map(agentKey => ({ agentKey, displayName: agentKey, status: 'enabled' })))
const job = ref({ id: 'fixture-job', sessionId: 'fixture-session', agentKey: 'claude', status: 'running', executionState: 'running', executionEpoch: 1 })
const running = computed(() => ['running', 'cancel_requested'].includes(job.value.status))
const agentSwitchPending = ref(false), draft = ref('保留已完成部分，继续补充边界场景')
const agentSwitchPhase = ref(''), agentExecutionPickerRef = ref(null)
const sessionTurns = ref([{ job: { id: 'fixture-next', sessionId: 'fixture-session', agentKey: 'claude', status: 'waiting_turn' }, userMessage: { content: '补充异常场景，不删除已有节点' } }])
const agentEvents = ref([{ jobId: 'fixture-job', sequence: 1, eventType: 'todo_updated', payload: { executionEpoch: 1, todos: [
  { content: '读取当前脑图', status: 'completed' }, { content: '补全边界场景与依赖关系', status: 'in_progress' },
  { content: '<img onerror=alert(1)> 必须按文本显示', status: 'pending' },
] } }])
const confirmationCount = ref(0), cancellationCount = ref(0), changedCount = ref(0)
const status = ref('请选择另一个 Agent，开始验收'), settling = ref(false), canvasReady = ref(false)
const targetFailure = ref('none')
const deviceCatalog = reactive({ loaded: true, enabled: true, error: '', updatedAt: Date.now(), now: Date.now(), loading: false,
  devices: [{ deviceId: 'fixture-device', name: '测试电脑', status: 'online', executionAvailable: true, executionAgents: ['codex'] }],
})
let settleCanvas, targetKey
const executionStop = useMindmapExecutionStop({ job, ownerId: () => 'fixture-owner', loadJob: async () => ({ data: { ...job.value } }) })
const scope = {
  h, nextTick, MindmapAgentHandoffSummary, projectAgentHandoff, agentSwitchPhase, agentExecutionPickerRef,
  sessionTurns, agentEvents, handoffTimelineReceipt: ref({ ownerId: 'fixture-owner', sessionId: 'fixture-session' }),
  timelineLoading: ref(false), timelineError: ref(''), proposal: ref(null),
  currentResultState: computed(() => mindmapAgentResultState({ job: job.value, livePreviewActive: true })),
  form, agents, job, running, agentSwitchPending, executionStop, deviceCatalog, isMindmapExecutionBlocked, isDeviceAgent, agentExecutionLocation, deviceExecutionIssue,
  agentSwitchGeneration: 0, componentAlive: true, actionBusy: ref(false), restoringJob: ref(false), agentManagerVisible: ref(false),
  agentPreferences: ref({ hidden: [] }), agentSupportsCurrentTask: () => true, currentAiOwnerUserId: () => 'fixture-owner',
  refreshDeviceCatalog: async () => { deviceCatalog.updatedAt = deviceCatalog.now = Date.now(); return true }, onAgentChange: () => { changedCount.value++ },
  ElMessage, ElMessageBox: { confirm: async (...args) => {
    confirmationCount.value++
    await ElMessageBox.confirm(...args)
    if (targetFailure.value === 'disabled') agents.value.find(agent => agent.agentKey === targetKey).status = 'disabled'
    if (targetFailure.value === 'offline') deviceCatalog.devices[0].status = 'offline'
    if (targetFailure.value === 'queue') sessionTurns.value.push({ job: { id: 'fixture-new', sessionId: 'fixture-session', status: 'waiting_turn', agentKey: 'claude' } })
  } },
  cancelJob: async () => {
    cancellationCount.value++
    job.value = { ...job.value, status: 'cancel_requested', cancelRequestedTime: '2026-09-26T10:00:00' }
    status.value = '停止请求已接受，等待退出回执；可以继续写草稿'
    return true
  },
  finalizeTerminalJob: () => {
    settling.value = true
    status.value = '旧 Agent 已退出，等待脑图同步；尚未切换'
    return new Promise(resolve => { settleCanvas = resolve })
  },
}
// Test-only loader: exercise the actual handler without starting the app's
// authenticated services or exposing mutation hooks on a business document.
const start = dialogSource.indexOf('function agentHandoffSummary(')
const end = dialogSource.indexOf('function assistantMessageText(', start)
if (start < 0 || end < 0) throw new Error('生产切换处理器未找到')
const requestAgentSwitch = new Function('scope', `with(scope) { ${dialogSource.slice(start, end)}; return requestAgentSwitch }`)(scope)
async function requestSwitch(selection) {
  targetKey = typeof selection === 'string' ? selection : selection.agentKey
  deviceCatalog.updatedAt = deviceCatalog.now = Date.now()
  const switched = await requestAgentSwitch(selection)
  status.value = switched ? '已切换下一轮 Agent；没有发送任务，未发送草稿保留' : '本次切换未生效，原执行设置和草稿保留'
}
function confirmExit() { job.value = { ...job.value, status: 'cancelled', executionState: 'stopped' } }
function finishCanvas(ok) { canvasReady.value = ok; settling.value = false; settleCanvas?.(ok); settleCanvas = null }
onBeforeUnmount(() => { scope.componentAlive = false; agentSwitchPending.value = false; finishCanvas(false) })
</script>
<style scoped>
main { max-width: 680px; margin: 20px auto; padding: 16px; font-family: system-ui, sans-serif; }
h1 { font-size: 20px; } p { line-height: 1.6; }
label { display: block; } textarea { display: block; box-sizing: border-box; width: 100%; min-height: 90px; margin: 8px 0; }
nav { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
button { min-height: 36px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
