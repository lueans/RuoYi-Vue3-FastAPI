<template>
  <el-dialog :model-value="modelValue" title="我的 AI Agents" width="min(680px, calc(100vw - 24px))" :z-index="4400" append-to-body class="mindmapAgentManager" @update:model-value="$emit('update:modelValue', $event)" @closed="finishConfigure">
    <div class="managerIntro"><div><strong>平台运行主机</strong><p>扫描 FastAPI 运行主机上的 Claude、Codex、Kimi CLI；与浏览器不在同一台电脑时，扫描的是服务端主机。</p></div><el-button :loading="scanning" @click="scan(true)">扫描运行主机</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="agentCards">
      <article v-for="agent in catalog" :key="agent.agentKey" class="agentCard">
        <div class="agentCardTitle"><strong>{{ agent.displayName }}</strong><el-tag v-if="preferences.defaultAgent === agent.agentKey" size="small">默认</el-tag></div>
        <div class="agentFacts"><el-tag size="small" :type="agent.readiness.tone">{{ agent.readiness.label }}</el-tag><span>平台运行主机</span></div>
        <p class="agentReason" role="status">{{ agent.readiness.description }}</p>
        <p class="agentDiscovery">{{ agent.agentKey === 'native_mindmap' ? '平台模型 · 无需扫描 CLI' : agentRuntimeDiscovery(agent.runtime) }}</p>
        <p v-if="agentCatalogCheckTime(agent.runtime?.checkedAt)" class="agentCheckTime">扫描时间 {{ agentCatalogCheckTime(agent.runtime.checkedAt) }}</p>
        <details class="agentTechnicalInfo">
          <summary>技术信息</summary>
          <p>{{ agent.runtime?.protocol || (agent.agentKey === 'native_mindmap' ? '平台模型' : 'SDK Adapter') }}<span v-if="agent.runtime?.version"> · v{{ agent.runtime.version }}</span></p>
          <p v-if="agent.runtime?.executionSource === 'sdk_bundled'">执行时使用 SDK 内置 CLI，保留会话续接兼容性。</p>
          <p v-if="agent.runtime?.reason">{{ agent.runtime.reason }}</p>
          <p v-if="agentCatalogCheckTime(agent.lastHealthTime)">环境检查时间 {{ agentCatalogCheckTime(agent.lastHealthTime) }}</p>
          <div class="agentFacts"><span v-if="agent.supportsStreaming">流式预览</span><span v-if="agent.supportsSessions">会话续接</span></div>
        </details>
        <label class="agentVisibility"><span>在列表显示</span><el-switch :model-value="!preferences.hidden.includes(agent.agentKey)" :disabled="agent.status !== 'enabled' && preferences.hidden.includes(agent.agentKey)" :aria-label="`在我的列表中显示 ${agent.displayName}`" @change="toggle(agent.agentKey, $event)" /></label>
        <div class="agentActions"><el-button text size="small" :disabled="agent.status !== 'enabled' || preferences.hidden.includes(agent.agentKey)" @click="setDefault(agent.agentKey)">设为默认</el-button><el-button v-if="selectionIssue && selectedAgentKey === agent.agentKey" type="primary" text size="small" @click="requestConfigure">检查配置</el-button><el-button v-else type="primary" text size="small" :disabled="agent.status !== 'enabled' || preferences.hidden.includes(agent.agentKey)" @click="$emit('select', agent.agentKey)">使用此 Agent</el-button></div>
      </article>
    </div>
    <p class="managerFootnote">扫描只确认程序发现情况，不验证供应商登录或模型可用性。“在列表显示”和默认 Agent 仅保存在当前浏览器、当前账号下，不影响其他用户。平台主机新安装 CLI 后点“扫描运行主机”；平台未开放的 Agent 仍需管理员启用。不会自动安装或执行登录命令。</p>
    <div v-for="deviceAgent in deviceAgents" :key="deviceAgent.agentKey" class="agentCardTitle deviceAgentPreference"><strong>{{ deviceAgent.displayName }}</strong><el-tag v-if="preferences.defaultAgent === deviceAgent.agentKey" size="small">默认</el-tag><el-button text size="small" :disabled="deviceAgent.status !== 'enabled' || preferences.hidden.includes(deviceAgent.agentKey)" @click="setDefault(deviceAgent.agentKey)">设为默认</el-button><label class="agentVisibility"><span>在列表显示</span><el-switch :model-value="!preferences.hidden.includes(deviceAgent.agentKey)" :aria-label="`在我的列表中显示 ${deviceAgent.displayName}`" @change="toggle(deviceAgent.agentKey, $event)" /></label></div>
    <MindmapAgentDevices :active="modelValue" :owner-id="ownerId" :execution-agents="deviceAgents.filter(agent => agent.status === 'enabled' && !preferences.hidden.includes(agent.agentKey)).map(agent => agent.agentKey)" @select="$emit('select', $event)" />
    <template #footer><el-button @click="$emit('update:modelValue', false)">完成</el-button></template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { listMindmapAiRuntimes } from '@/api/mindmap/mindmap'
import { createAgentRequestScope, isDeviceAgent } from '@/utils/mindmap-agent-devices'
import { agentCatalogReadiness, agentRuntimeDiscovery, agentCatalogCheckTime } from '@/utils/mindmap-agent-catalog'
import MindmapAgentDevices from './MindmapAgentDevices.vue'
const props = defineProps({ modelValue: Boolean, ownerId: { type: [Number, String], default: '' }, agents: { type: Array, default: () => [] }, preferences: { type: Object, required: true }, selectedAgentKey: { type: String, default: '' }, selectionIssue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'preferences', 'select', 'scanned', 'configure'])
const runtimes = ref([])
const scanning = ref(false)
const error = ref('')
const configureOwner = ref(null)
function requestConfigure() {
  configureOwner.value = props.ownerId
  emit('update:modelValue', false)
}
function finishConfigure() {
  const owner = configureOwner.value
  configureOwner.value = null
  // Wait for the modal's focus trap to close before focusing task settings.
  if (owner !== null && owner === props.ownerId && !props.modelValue) emit('configure')
}
const scope = createAgentRequestScope()
const deviceAgents = computed(() => props.agents.filter(agent => isDeviceAgent(agent.agentKey)))
const catalog = computed(() => {
  const items = props.agents.filter(agent => !isDeviceAgent(agent.agentKey)).map(agent => ({ ...agent, runtime: runtimes.value.find(item => item.agentKey === agent.agentKey) }))
  for (const runtime of runtimes.value) if (!items.some(item => item.agentKey === runtime.agentKey)) items.push({ ...runtime, runtime, status: 'disabled', statusReason: '平台尚未配置此 Agent 的执行适配器或 Connector' })
  return items.map(agent => ({ ...agent, readiness: agentCatalogReadiness(agent, props.selectedAgentKey === agent.agentKey ? props.selectionIssue : '') }))
})
async function scan(refresh) {
  if (scanning.value || !props.modelValue || !props.ownerId) return
  const current = scope.capture()
  scanning.value = true; error.value = ''
  try { const response = await listMindmapAiRuntimes({ refresh }); if (!current()) return; runtimes.value = Array.isArray(response.data) ? response.data : []; emit('scanned') }
  catch { if (current()) error.value = '扫描失败，请检查服务连接后重试。' }
  finally { if (current()) scanning.value = false }
}
watch(() => [props.modelValue, props.ownerId], () => { scope.invalidate(); runtimes.value = []; scanning.value = false; error.value = ''; if (props.modelValue && props.ownerId) void scan(false) }, { immediate: true })
onBeforeUnmount(() => scope.invalidate())
function toggle(key, enabled) {
  const hidden = props.preferences.hidden.filter(item => item !== key)
  if (!enabled) hidden.push(key)
  const defaultAgent = !enabled && props.preferences.defaultAgent === key
    ? props.agents.find(agent => agent.status === 'enabled' && !hidden.includes(agent.agentKey))?.agentKey || ''
    : props.preferences.defaultAgent
  emit('preferences', { defaultAgent, hidden })
}
function setDefault(defaultAgent) { emit('preferences', { ...props.preferences, defaultAgent }) }
</script>

<style>
/* The dialog is teleported: scope these rules to its public root class. */
.el-dialog.mindmapAgentManager {
  --agent-manager-gap: max(12px, min(6vh, 48px));
  display: flex;
  flex-direction: column;
  max-height: calc(100dvh - var(--agent-manager-gap) - var(--agent-manager-gap));
  margin-top: var(--agent-manager-gap) !important;
  margin-bottom: var(--agent-manager-gap);
}
.mindmapAgentManager > .el-dialog__body {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.mindmapAgentManager > .el-dialog__header,
.mindmapAgentManager > .el-dialog__footer { flex-shrink: 0; }
</style>

<style scoped>
.deviceAgentPreference { margin-top:16px; padding-top:16px; border-top:1px solid var(--el-border-color-lighter); flex-wrap:wrap; }
.managerIntro { display:flex; align-items:flex-start; gap:24px; }.managerIntro p,.managerFootnote { color:var(--el-text-color-secondary); line-height:1.7; font-size:12px; }.managerIntro > div { flex:1; }
.agentCards { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:16px 0; }.agentCard { border:1px solid var(--el-border-color-lighter); padding:16px; border-radius:12px; }.agentCardTitle { display:flex; align-items:center; gap:8px; }.agentCardTitle strong { flex:1; }.agentCard p { font-size:12px; color:var(--el-text-color-secondary); overflow-wrap:anywhere; }.agentFacts { display:flex; gap:8px; flex-wrap:wrap; align-items:center; font-size:11px; color:var(--el-text-color-secondary); }.agentReason { min-height:32px; }.agentActions { display:flex; justify-content:space-between; margin-top:12px; }
@media(max-width:600px) { .agentCards { grid-template-columns:1fr; }.managerIntro { gap:10px; } }
.agentCardTitle strong { min-width:0; overflow-wrap:anywhere; }
.agentCard > .agentFacts { margin-top:10px; }
.agentCard .agentReason { font-size:13px; line-height:1.65; margin:10px 0; color:var(--el-text-color-regular); }
.agentCard .agentDiscovery { margin:8px 0 4px; font-size:12px; }
.agentCard .agentCheckTime { margin:4px 0; font-size:11px; }
.agentTechnicalInfo { margin-top:8px; font-size:12px; color:var(--el-text-color-secondary); }
.agentTechnicalInfo summary { padding:5px 0; cursor:pointer; }
.agentTechnicalInfo summary:focus-visible { outline:2px solid var(--el-color-primary); outline-offset:2px; }
.agentVisibility { display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:12px; color:var(--el-text-color-secondary); }
.agentCard > .agentVisibility { margin-top:12px; padding-top:8px; border-top:1px solid var(--el-border-color-lighter); }
.deviceAgentPreference > .agentVisibility { margin-left:auto; }
</style>
