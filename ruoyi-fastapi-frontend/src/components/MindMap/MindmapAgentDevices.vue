<template>
  <section class="agentDevices" aria-labelledby="agentDevicesTitle">
    <div class="deviceSectionHeader">
      <div><h3 id="agentDevicesTitle">我的电脑</h3><p>通过本地桥接连接用户设备，与平台运行主机分开管理。</p></div>
      <el-button text :loading="loading" @click="loadDevices">刷新设备</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="!loaded && loading" role="status">正在读取设备状态…</p>
    <p v-else-if="loaded && !enabled" class="deviceHint">本地桥接尚未由管理员启用。启用前需要安装设备表迁移；当前仍可使用上方的平台 Agents。</p>
    <template v-else-if="enabled">
      <el-alert title="扫描可发现 Claude、Codex、Kimi；执行需管理员启用，并在电脑上主动授权。扫描到不等于可执行，CLI 登录凭据不会上传。" type="info" :closable="false" />
      <p v-if="!executionAgents.length" class="deviceHint">当前无法选择本机 Agent，请检查个人列表显示设置与平台 Agent 启用状态。配对与扫描仍可使用。</p>
      <div class="devicePairForm">
        <el-input v-model="deviceName" maxlength="80" placeholder="设备名称，例如：我的 MacBook" aria-label="设备名称" @keyup.enter="pairDevice" />
        <el-button type="primary" plain :loading="busy === 'pair'" :disabled="!!busy || !deviceName.trim()" @click="pairDevice">连接新设备</el-button>
      </div>
      <div v-if="pairing" class="pairingPanel">
        <strong>在这台电脑的终端完成配对</strong>
        <p>配对码剩余 {{ remaining }} 秒，仅本次显示。不要发送给他人或粘贴到 AI 对话。</p>
        <div class="pairingCode">
          <el-input :model-value="pairing.pairingCode" type="password" show-password readonly autocomplete="off" aria-label="临时设备配对码" />
          <el-button @click="copyPairingCode">复制配对码</el-button>
        </div>
        <p>运行下方 pair 命令，在终端提示时粘贴配对码；成功后运行 run。关闭本窗口会清除这里的配对码。</p>
      </div>
      <details class="bridgeInstructions">
        <summary>本地桥接安装与连接步骤（macOS / Linux）</summary>
        <p>获取本项目后，在项目根目录安装独立伴随程序：</p>
        <code>pip install ./mindmap-agent-bridge</code>
        <p>将下面的地址替换为你的平台 API 根地址（包含部署使用的 API 前缀），远程地址必须为 HTTPS：</p>
        <code>mindmap-agent-bridge pair --server https://你的平台/API前缀</code>
        <code>mindmap-agent-bridge run</code>
        <p>普通 run 只主动连接平台进行扫描，不开放本机端口，也不自动安装、登录或运行 AI 模型；停止终端后设备会离线。</p>
        <p>若要在此电脑执行脑图任务，先安装 Claude 执行依赖、完成本机 Claude 登录，再用以下命令替代普通 run：</p>
        <code>pip install './mindmap-agent-bridge[claude]'</code>
        <code>mindmap-agent-bridge run --execute claude</code>
        <p>开启后，此账号发送的任务可调用本机 Claude，可能产生模型费用；关闭桥接会中断执行。仅支持 macOS / Linux，平台管理员还需启用设备执行。</p>
        <p>要在网页切换 Claude / Codex，可同时明确授权两者：</p>
        <code>pip install './mindmap-agent-bridge[claude,codex]'</code>
        <code>mindmap-agent-bridge run --execute claude --execute codex --accept-estimated-budget</code>
        <p>只用 Codex 时去掉 <code class="inlineCommand">--execute claude</code>。执行固定随包 Codex 0.147.0，与扫描到的 PATH 版本可能不同；先在终端完成 Codex 文件登录或配置本机 OPENAI_API_KEY。管理员需单独启用本机 Codex。</p>
        <p>{{ CODEX_DEVICE_BUDGET_NOTICE }}<br />只有理解并接受这一限制后，才添加 <code class="inlineCommand">--accept-estimated-budget</code>。</p>
        <p>使用 Kimi 需先安装并登录 Kimi Code CLI 2.1.1（不兼容旧版 Python Kimi CLI），再安装执行依赖：</p>
        <code>pip install './mindmap-agent-bridge[kimi]'</code>
        <code>{{ deviceExecutionCommand('device_kimi') }}</code>
        <p>{{ KIMI_DEVICE_BUDGET_NOTICE }}理解并接受后才添加 <code class="inlineCommand">--accept-unmetered-budget</code>；管理员还需单独启用本机 Kimi。</p>
        <p>Kimi 每轮使用私有回环 MCP 端口，仅本机可访问，不向局域网开放；只启用脑图工具，不继承本机 Shell、文件工具或其他 MCP。登录状态与精确版本将在执行时校验。</p>
        <p>同时授权三种 Agent 可安装 <code class="inlineCommand">'./mindmap-agent-bridge[claude,codex,kimi]'</code>，然后运行：</p>
        <code>mindmap-agent-bridge run --execute claude --execute codex --execute kimi --accept-estimated-budget --accept-unmetered-budget</code>
        <p>每台电脑一次只执行一轮；运行中切换会先停止原任务，已有脑图变更不会自动撤销。</p>
        <p>安装依赖后、配对或执行前，可先检查所选 Agent 的基础安装；不调用模型、不读取登录或配对凭据：</p>
        <code>mindmap-agent-bridge doctor --agent claude --agent codex --agent kimi</code>
        <p>去掉不使用的 Agent 即可。诊断检查实际执行版本；Codex 检查随包版本，不是扫描到的 PATH 版本。通过不代表已登录、模型可用或平台已授权，也不会自动安装、配对或启用执行。</p>
      </details>
      <p v-if="!devices.length" class="deviceEmpty">尚未配对电脑。连接后，可以扫描该电脑新安装的 Claude、Codex、Kimi CLI。</p>
      <article v-for="device in devices" :key="device.deviceId" class="deviceCard">
        <div class="deviceCardHeader">
          <strong>{{ device.name }}</strong>
          <el-tag size="small" :type="stateVerified && device.status === 'online' ? 'success' : 'info'">{{ stateVerified ? '' : '上次状态 · ' }}{{ agentDeviceStatus(device.status) }}</el-tag>
        </div>
        <p class="deviceHint">{{ stateVerified ? deviceExecutionLabel(device) : '状态待确认，请刷新设备' }}<span v-if="stateVerified && device.executionAvailable"> · 登录将在执行时校验</span></p>
        <p v-if="device.executionAgents?.includes('codex')" class="deviceHint">{{ CODEX_DEVICE_BUDGET_NOTICE }}</p>
        <p v-if="device.executionAgents?.includes('kimi')" class="deviceHint">{{ KIMI_DEVICE_BUDGET_NOTICE }}</p>
        <p v-if="device.scanPending && device.status === 'online'" class="deviceHint" role="status">扫描已排队，等待本地桥接回传…</p>
        <ul v-if="device.runtimes?.length" class="deviceRuntimes">
          <li v-for="runtime in device.runtimes" :key="runtime.agentKey">
            <span>{{ runtime.displayName }}<small v-if="runtime.version"> · {{ runtime.version }}</small></span>
            <span>{{ agentInstallationStatus(runtime) }}</span>
          </li>
        </ul>
        <div class="deviceCardFooter">
          <span>{{ device.lastScanAt ? `最近扫描 ${formatTime(device.lastScanAt)}` : '尚无扫描结果' }}</span>
          <div>
            <el-button v-for="agentKey in executionAgents" :key="agentKey" type="primary" text size="small" :disabled="!!busy || !!error || !!deviceExecutionIssue(device.deviceId, { loaded, enabled, updatedAt, devices }, { agentKey, now: clockNow })" @click="$emit('select', { agentKey, deviceId: device.deviceId })">使用 {{ deviceAgentName(agentKey) }}</el-button>
            <el-button text size="small" :loading="busy === `scan:${device.deviceId}`" :disabled="!!busy || device.status !== 'online' || device.scanPending" @click="scanDevice(device)">扫描此电脑</el-button>
            <el-button text size="small" type="danger" :disabled="!!busy || device.status === 'revoked'" @click="revokeDevice(device)">撤销授权</el-button>
          </div>
        </div>
      </article>
    </template>
  </section>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createMindmapAiDevicePairing, listMindmapAiDevices, revokeMindmapAiDevice, scanMindmapAiDevice } from '@/api/mindmap/mindmap'
import { AGENT_DEVICE_API_KEY, agentDeviceStatus, agentInstallationStatus, createAgentRequestScope, pairingSecondsRemaining, deviceExecutionLabel, deviceExecutionIssue, deviceAgentName, deviceExecutionCommand, isDeviceCatalogFresh, CODEX_DEVICE_BUDGET_NOTICE, KIMI_DEVICE_BUDGET_NOTICE } from '@/utils/mindmap-agent-devices'

const props = defineProps({ active: Boolean, ownerId: { type: [Number, String], default: '' }, executionAgents: { type: Array, default: () => [] } })
defineEmits(['select'])
const api = inject(AGENT_DEVICE_API_KEY, { list: listMindmapAiDevices, pair: createMindmapAiDevicePairing, scan: scanMindmapAiDevice, revoke: revokeMindmapAiDevice })
const scope = createAgentRequestScope()
const devices = ref([])
const loaded = ref(false)
const loading = ref(false)
const enabled = ref(false)
const error = ref('')
const busy = ref('')
const deviceName = ref('')
const pairing = ref(null)
const clockNow = ref(Date.now())
const updatedAt = ref(0)
const stateVerified = computed(() => isDeviceCatalogFresh({ loaded: loaded.value, error: error.value, updatedAt: updatedAt.value }, clockNow.value))
const remaining = computed(() => pairingSecondsRemaining(pairing.value?.expiresAt, clockNow.value))
let pollTimer
let clockTimer

function clearTimers() { clearTimeout(pollTimer); clearInterval(clockTimer) }
function scheduleRefresh() {
  clearTimeout(pollTimer)
  if (props.active && props.ownerId && (!loaded.value || enabled.value)) pollTimer = setTimeout(loadDevices, 5000)
}
async function loadDevices() {
  if (!props.active || !props.ownerId || loading.value) return
  const current = scope.capture()
  loading.value = true
  try {
    const response = await api.list()
    if (!current()) return
    loaded.value = true
    updatedAt.value = Date.now()
    clockNow.value = Date.now()
    enabled.value = response.data?.enabled === true
    devices.value = Array.isArray(response.data?.devices) ? response.data.devices : []
    error.value = ''
    if (pairing.value && devices.value.some(device => device.deviceId === pairing.value.deviceId && !['pending', 'pairing_expired'].includes(device.status))) pairing.value = null
  } catch {
    if (current()) error.value = '设备状态读取失败，请检查服务连接后刷新。'
  } finally {
    if (current()) { loading.value = false; scheduleRefresh() }
  }
}
async function pairDevice() {
  if (busy.value || !props.active || !props.ownerId || !enabled.value || !deviceName.value.trim()) return
  const current = scope.capture()
  busy.value = 'pair'
  try {
    const response = await api.pair(deviceName.value.trim())
    if (!current()) return
    const result = response.data
    if (!result?.deviceId || typeof result.pairingCode !== 'string' || !Number.isFinite(result.expiresIn)) throw new Error('invalid pairing')
    clockNow.value = Date.now()
    pairing.value = { deviceId: result.deviceId, pairingCode: result.pairingCode, expiresAt: clockNow.value + Math.min(300, Math.max(0, result.expiresIn)) * 1000 }
    deviceName.value = ''
    await loadDevices()
  } catch {
    if (current()) error.value = '配对码未确认生成成功。请刷新设备列表；若出现待配对设备，可撤销后重新连接。'
  } finally { if (current()) busy.value = '' }
}
async function copyPairingCode() {
  if (!pairing.value || !remaining.value) return
  try { await navigator.clipboard.writeText(pairing.value.pairingCode); ElMessage.success('配对码已复制') }
  catch { ElMessage.warning('无法访问剪贴板，可显示配对码后手动复制') }
}
async function scanDevice(device) {
  if (busy.value || device.status !== 'online') return
  const current = scope.capture()
  busy.value = `scan:${device.deviceId}`
  try { await api.scan(device.deviceId); if (current()) await loadDevices() }
  catch { if (current()) error.value = '扫描未能启动，请检查桥接是否仍在线。' }
  finally { if (current()) busy.value = '' }
}
async function revokeDevice(device) {
  if (busy.value) return
  const current = scope.capture()
  busy.value = `revoke:${device.deviceId}`
  try {
    await ElMessageBox.confirm('撤销后，这台设备的桥接连接将失效，正在执行的任务会被中断。已产生的脑图变更不会自动撤销。重新使用需要再次配对；不会卸载本机 CLI。', `撤销 ${device.name} 的授权？`, { type: 'warning', confirmButtonText: '撤销授权', cancelButtonText: '取消' })
    if (!current()) return
    await api.revoke(device.deviceId)
    if (current()) { if (pairing.value?.deviceId === device.deviceId) pairing.value = null; await loadDevices() }
  } catch (reason) {
    if (current() && !['cancel', 'close'].includes(reason)) error.value = '设备撤销结果尚未确认，请刷新检查后重试。'
  } finally { if (current()) busy.value = '' }
}
function formatTime(value) { const time = new Date(value); return Number.isNaN(time.getTime()) ? '时间未知' : time.toLocaleString() }
watch(() => [props.active, props.ownerId], () => {
  scope.invalidate(); clearTimers()
  devices.value = []; loaded.value = false; loading.value = false; enabled.value = false
  updatedAt.value = 0
  error.value = ''; busy.value = ''; pairing.value = null; deviceName.value = ''
  if (props.active && props.ownerId) {
    void loadDevices()
    clockTimer = setInterval(() => { clockNow.value = Date.now(); if (pairing.value && !remaining.value) pairing.value = null }, 1000)
  }
}, { immediate: true })
onBeforeUnmount(() => { scope.invalidate(); clearTimers(); pairing.value = null })
</script>

<style scoped>
.agentDevices { border-top:1px solid var(--el-border-color-lighter); padding-top:20px; margin-top:20px; font-size:12px; }
.deviceSectionHeader,.deviceCardHeader,.deviceCardFooter,.devicePairForm,.pairingCode { display:flex; align-items:center; gap:12px; }
.deviceSectionHeader { justify-content:space-between; align-items:flex-start; }.deviceSectionHeader h3 { margin:0; font-size:14px; }.agentDevices p { line-height:1.7; color:var(--el-text-color-secondary); }
.deviceSectionHeader p { margin:6px 0 12px; }.devicePairForm { margin:16px 0; }.devicePairForm .el-input,.pairingCode .el-input { flex:1; min-width:0; }
.pairingPanel { padding:14px; margin-bottom:12px; background:var(--el-fill-color-light); border:1px solid var(--el-border-color); border-radius:8px; }.pairingPanel strong { font-size:13px; }
.bridgeInstructions { padding:12px; border:1px solid var(--el-border-color-lighter); border-radius:8px; margin-bottom:16px; }.bridgeInstructions summary { cursor:pointer; line-height:1.7; }.bridgeInstructions code { display:block; overflow-wrap:anywhere; padding:8px; background:var(--el-fill-color-light); margin:6px 0; border-radius:4px; }
.deviceCard { border:1px solid var(--el-border-color-lighter); border-radius:8px; padding:14px; margin:10px 0; }.deviceCardHeader strong { font-size:13px; flex:1; overflow-wrap:anywhere; }.deviceRuntimes { list-style:none; padding:0; margin:12px 0; }.deviceRuntimes li { display:flex; justify-content:space-between; gap:12px; padding:6px 0; }.deviceRuntimes li > span:last-child,.deviceRuntimes small { color:var(--el-text-color-secondary); }
.deviceCardFooter { justify-content:space-between; flex-wrap:wrap; color:var(--el-text-color-secondary); }.deviceEmpty { text-align:center; padding:12px; }
.deviceCardFooter > div { display:flex; flex-wrap:wrap; gap:4px; }.deviceCardFooter :deep(.el-button + .el-button) { margin-left:0; }.bridgeInstructions code.inlineCommand { display:inline; padding:1px 4px; }
@media(max-width:500px) { .devicePairForm,.pairingCode { flex-wrap:wrap; }.devicePairForm .el-input,.pairingCode .el-input { flex-basis:100%; }.deviceRuntimes li { flex-direction:column; gap:3px; } }
</style>
