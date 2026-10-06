<template>
  <section class="executionPicker" aria-label="下一轮执行设置">
    <div class="executionPickerBar">
      <el-select ref="agentSelect" :model-value="agentKey" size="small" popper-class="mindmapAiSelectPopper" aria-label="选择 AI Agent" :disabled="disabled" @change="$emit('select', $event)">
        <template #prefix><el-icon aria-hidden="true"><Cpu /></el-icon></template>
        <el-option-group v-for="group in groups" :key="group.label" :label="group.label">
          <el-option v-for="agent in group.agents" :key="agent.agentKey" :label="agent.displayName" :value="agent.agentKey" :disabled="agent.status !== 'enabled' || !canUseAgent(agent)" />
        </el-option-group>
      </el-select>
      <span class="executionHint">{{ running ? '切换会先停止当前轮' : '下一轮执行 Agent' }}</span>
      <el-button text size="small" @click="$emit('manage')">管理 Agents</el-button>
    </div>
    <p v-if="!isDeviceAgent(agentKey)" class="executionNotice" role="note">{{ budgetNotice }}</p>
    <template v-if="isDeviceAgent(agentKey)">
      <div class="executionDeviceBar">
        <el-icon aria-hidden="true"><Monitor /></el-icon>
        <el-select :model-value="deviceId || undefined" size="small" placeholder="选择我的电脑" aria-label="选择执行电脑" :disabled="disabled" :loading="catalog.loading" popper-class="mindmapAiSelectPopper" @change="$emit('select', { agentKey, deviceId: $event })">
          <el-option v-if="deviceId && !catalog.devices.some(item => item.deviceId === deviceId)" :value="deviceId" :label="`设备 ${deviceId.slice(0, 8)} · 不可用`" disabled />
          <el-option v-for="device in catalog.devices" :key="device.deviceId" :value="device.deviceId" :label="`${device.name} · ${deviceStateLabel(device)}`" :disabled="!!deviceExecutionIssue(device.deviceId, catalog, { agentKey, now: catalog.now || Date.now(), allowBusy: running && currentJob?.agentKey === agentKey && currentJob?.deviceId === device.deviceId })" />
        </el-select>
        <el-button text size="small" :loading="catalog.loading" aria-label="刷新执行电脑状态" @click="$emit('refresh')"><el-icon><Refresh /></el-icon></el-button>
      </div>
      <p class="executionNotice" :class="{ 'is-unavailable': !!issue }" role="status">{{ issue || `使用此电脑的 ${deviceAgentName(agentKey)} 登录；登录状态将在执行时校验。` }}</p>
      <p v-if="deviceBudgetNotice(agentKey)" class="executionNotice">{{ deviceBudgetNotice(agentKey) }}</p>
    </template>
    <p v-if="running && currentJob" class="executionCurrent"><span class="executionDot" />本轮运行于 {{ agentExecutionLocation(currentJob, catalog.devices) }}</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Cpu, Monitor, Refresh } from '@element-plus/icons-vue'
import { agentExecutionLocation, deviceExecutionLabel, deviceExecutionIssue, deviceAgentName, isDeviceAgent, isDeviceCatalogFresh, deviceBudgetNotice, agentBudgetNotice } from '@/utils/mindmap-agent-devices'
const props = defineProps({ agentKey: String, deviceId: String, agents: { type: Array, default: () => [] }, canUseAgent: { type: Function, default: () => true }, disabled: Boolean, running: Boolean, currentJob: Object, catalog: { type: Object, required: true }, issue: String })
defineEmits(['select', 'manage', 'refresh'])
const agentSelect = ref(null)
const budgetNotice = computed(() => agentBudgetNotice(props.agents.find(agent => agent.agentKey === props.agentKey)))
defineExpose({ focus: () => agentSelect.value?.focus() })
const deviceStateLabel = device => isDeviceCatalogFresh(props.catalog, props.catalog.now || Date.now())
  ? deviceExecutionLabel(device, props.agentKey) : '状态待确认'
const groups = computed(() => [
  { label: '平台运行主机', agents: props.agents.filter(agent => !isDeviceAgent(agent.agentKey)) },
  { label: '我的电脑', agents: props.agents.filter(agent => isDeviceAgent(agent.agentKey)) },
].filter(group => group.agents.length))
</script>

<style scoped>
.executionPicker { padding: 0 0 4px; color: var(--el-text-color-secondary); font-size: 11px; }
.executionPickerBar,.executionDeviceBar { display:flex; align-items:center; gap:8px; min-width:0; }
.executionPickerBar > .el-select { width:160px; flex:1; min-width:110px; }
.executionPickerBar > .el-button { margin-left:auto; flex-shrink:0; }
.executionPickerBar :deep(.el-select__wrapper) { box-shadow:none; background:transparent; padding-left:4px; font-size:12px; }
.executionPickerBar :deep(.el-select__wrapper:hover) { background:var(--el-fill-color-light); }
.executionDeviceBar :deep(.el-select__wrapper) { box-shadow:none; background:transparent; font-size:11px; }
.executionHint { font-size:11px; }
.executionDeviceBar { margin-top:6px; padding:4px 6px; background:var(--el-fill-color-light); border-radius:7px; }
.executionDeviceBar > .el-select { flex:1; min-width:0; }
.executionNotice { margin:5px 2px 0; font-size:11px; line-height:1.55; overflow-wrap:anywhere; }
.executionNotice.is-unavailable { color:var(--el-color-warning-dark-2); }
.executionCurrent { display:flex; align-items:center; gap:6px; margin:6px 2px 0; overflow-wrap:anywhere; }
.executionDot { width:5px; height:5px; flex-shrink:0; background:var(--el-color-primary); border-radius:50%; }
@container (max-width:380px) { .executionHint { display:none; } }
@media(max-width:480px) { .executionHint { display:none; } }
</style>
