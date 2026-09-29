<template>
  <main>
    <header><strong>设备组件验收 · 模拟数据，不配对真实设备</strong><nav>
      <button @click="active = !active">{{ active ? '关闭' : '重新打开' }}</button>
      <button @click="ownerId += 1">切换账号</button>
      <button @click="enabled = !enabled">切换服务开关</button>
      <button @click="fail = !fail">模拟连接错误</button>
      <button @click="dark = !dark; documentTheme()">切换明暗</button>
    </nav></header>
    <section class="fixturePanel"><h2>我的 AI Agents</h2>
      <p>平台运行主机与我的电脑分别管理；此页面只测试组件，不会启动模型。</p>
      <MindmapAgentExecutionPicker :agent-key="selection.agentKey" :device-id="selection.deviceId" :agents="agents" :catalog="catalog" :issue="selectionIssue" @select="selectAgent" @refresh="updatedAt = Date.now()" />
      <p role="status">下一轮：{{ selection.agentKey }} · {{ selection.deviceId || '平台主机' }}</p>
      <MindmapAgentDevices :active="active" :owner-id="ownerId" :execution-agents="['device_claude', 'device_codex', 'device_kimi']" @select="selectAgent" />
    </section>
  </main>
</template>
<script setup>
import { computed, provide, ref } from 'vue'
import MindmapAgentDevices from '../../../components/MindMap/MindmapAgentDevices.vue'
import MindmapAgentExecutionPicker from '../../../components/MindMap/MindmapAgentExecutionPicker.vue'
import { AGENT_DEVICE_API_KEY, deviceExecutionIssue, isDeviceAgent } from '../../mindmap-agent-devices'
const ownerId = ref(7)
const active = ref(true)
const enabled = ref(true)
const fail = ref(false)
const dark = ref(false)
const updatedAt = ref(Date.now())
const devices = ref([
  { deviceId: 'fixture-online', name: '我的 MacBook Pro', status: 'online', executionAvailable: true, executionAgents: ['claude', 'codex', 'kimi'], lastScanAt: '2026-09-26T10:30:00', runtimes: [
    { agentKey: 'claude', displayName: 'Claude Code', version: '2.0.1', status: 'detected' },
    { agentKey: 'codex', displayName: 'Codex', version: '0.100.0', status: 'detected' },
    { agentKey: 'kimi', displayName: 'Kimi Code', version: '2.1.1', status: 'detected' },
  ] },
  { deviceId: 'fixture-offline', name: '开发工作站 · 较长的用户自定义设备名称用于测试换行', status: 'offline', runtimes: [] },
])
const selection = ref({ agentKey: 'device_kimi', deviceId: 'fixture-online' })
const agents = [
  { agentKey: 'native', displayName: '平台 Agent', status: 'enabled' },
  { agentKey: 'device_claude', displayName: 'Claude · 我的电脑', status: 'enabled' },
  { agentKey: 'device_codex', displayName: 'Codex · 我的电脑', status: 'enabled' },
  { agentKey: 'device_kimi', displayName: 'Kimi · 我的电脑', status: 'enabled' },
]
const catalog = computed(() => ({ devices: devices.value, loaded: true, enabled: enabled.value, updatedAt: updatedAt.value, error: fail.value ? '模拟错误' : '' }))
const selectionIssue = computed(() => isDeviceAgent(selection.value.agentKey)
  ? deviceExecutionIssue(selection.value.deviceId, catalog.value, { agentKey: selection.value.agentKey }) : '')
function selectAgent(value) {
  selection.value = typeof value === 'string' ? { agentKey: value, deviceId: isDeviceAgent(value) ? selection.value.deviceId : '' } : value
}
let count = 0
function documentTheme() { document.documentElement.classList.toggle('dark', dark.value) }
provide(AGENT_DEVICE_API_KEY, {
  async list() { if (fail.value) throw new Error('fixture'); updatedAt.value = Date.now(); return { data: { enabled: enabled.value, devices: JSON.parse(JSON.stringify(devices.value)) } } },
  async pair(name) {
    const deviceId = 'fixture-pending-' + (++count)
    devices.value.push({ deviceId, name, status: 'pending', runtimes: [] })
    return { data: { deviceId, expiresIn: 300, pairingCode: '演示配对码-不能用于真实设备' } }
  },
  async scan(deviceId) { const device = devices.value.find(item => item.deviceId === deviceId); device.lastScanAt = new Date().toISOString() },
  async revoke(deviceId) { devices.value.find(item => item.deviceId === deviceId).status = 'revoked' },
})
</script>
<style scoped>
:global(body) { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--el-bg-color-page); color:var(--el-text-color-primary); }
main { padding:20px; box-sizing:border-box; }header { font-size:12px; line-height:1.7; margin-bottom:20px; }nav { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }button { border:1px solid var(--el-border-color); border-radius:6px; padding:6px 10px; background:var(--el-bg-color); color:inherit; cursor:pointer; }
.fixturePanel { max-width:680px; margin:auto; border:1px solid var(--el-border-color); background:var(--el-bg-color); border-radius:12px; padding:20px; box-sizing:border-box; }h2 { font-size:16px; margin:0; }.fixturePanel > p { font-size:12px; line-height:1.7; color:var(--el-text-color-secondary); }
@media(max-width:500px) { main { padding:12px; }.fixturePanel { padding:16px; } }
</style>
