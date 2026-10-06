export const AGENT_DEVICE_API_KEY = Symbol('mindmap-agent-device-api')
export const DEVICE_AGENT_RUNTIMES = Object.freeze({ device_claude: 'claude', device_codex: 'codex', device_kimi: 'kimi' })
export const isDeviceAgent = key => Object.hasOwn(DEVICE_AGENT_RUNTIMES, key)
export const deviceAgentName = key => ({ device_claude: 'Claude', device_codex: 'Codex', device_kimi: 'Kimi' })[key] || 'Agent'
export const CODEX_DEVICE_BUDGET_NOTICE = 'Codex 预算按已回报用量估算，可能超额，不是硬费用上限，也不代表订阅账单。'
export const KIMI_DEVICE_BUDGET_NOTICE = 'Kimi 不执行金额预算上限，仅限制时间与工具次数；使用此电脑的登录和模型额度。'
export const deviceBudgetNotice = key => ({ device_codex: CODEX_DEVICE_BUDGET_NOTICE, device_kimi: KIMI_DEVICE_BUDGET_NOTICE })[key] || ''
export function agentBudgetNotice(agent = {}) {
  const key = String(agent.agentKey || '').replace(/^device_/, '')
  const amount = Number(agent.maxBudgetUsd)
  const budget = Number.isFinite(amount) && amount > 0 ? `$${amount}` : '平台配置金额'
  if (key === 'kimi') return 'Kimi 仅限制时间与工具次数，不执行金额预算上限；费用以供应商账单为准。'
  if (key === 'codex') return `Codex 按回报用量估算预算 ${budget}，可能超额；不是硬费用上限，也不代表订阅账单。`
  if (key === 'native_mindmap') return `模型费用在回报用量后按 ${budget} 校验；未回报费用时无法核验，不是调用前的硬费用上限。`
  if (key === 'claude') return `Claude SDK 使用 ${budget} 任务预算；调用可能产生费用，实际费用以供应商账单为准。`
  return '费用与限额由所选执行器和供应商决定，请先检查任务设置。'
}
export const deviceExecutionCommand = key => `mindmap-agent-bridge run --execute ${DEVICE_AGENT_RUNTIMES[key] || 'claude'}${key === 'device_codex' ? ' --accept-estimated-budget' : key === 'device_kimi' ? ' --accept-unmetered-budget' : ''}`

export function createAgentRequestScope() {
  let generation = 0
  return {
    invalidate() { generation += 1 },
    capture() { const issued = generation; return () => issued === generation },
  }
}

export function agentDeviceStatus(status) {
  return ({ online: '在线', offline: '已配对 · 离线', pending: '等待配对', pairing_expired: '配对码已过期',
    credential_expired: '设备授权已过期', revoked: '已撤销' })[status] || '状态未知'
}

export function agentInstallationStatus(runtime = {}) {
  return ({ detected: '已发现 · 登录状态未检查', not_installed: '未安装', incompatible: '协议不兼容',
    probe_failed: '探测失败' })[runtime.status] || '尚未检查'
}

export function pairingSecondsRemaining(expiresAt, now = Date.now()) {
  return Number.isFinite(expiresAt) ? Math.max(0, Math.ceil((expiresAt - now) / 1000)) : 0
}

export function isDeviceCatalogFresh(catalog, now = Date.now()) {
  return !!(catalog.loaded && !catalog.error && Number.isFinite(catalog.updatedAt)
    && catalog.updatedAt > 0 && now - catalog.updatedAt <= 15000)
}

export function deviceExecutionIssue(deviceId, catalog, { agentKey = 'device_claude', allowBusy = false, now = Date.now() } = {}) {
  if (!isDeviceAgent(agentKey)) return '此 Agent 不支持本机执行。'
  if (catalog.error) return '设备状态读取失败，请刷新后再发送。'
  if (!catalog.loaded) return '正在确认设备连接…'
  if (!deviceId) return '请选择执行这轮任务的电脑；不会自动切换到其他设备。'
  if (!isDeviceCatalogFresh(catalog, now)) return '设备状态已过期，请刷新后再发送。'
  if (!catalog.enabled) return '管理员尚未启用本地设备桥接。'
  const device = catalog.devices.find(item => item.deviceId === deviceId)
  if (!device) return '此前选择的电脑已不可用，请手动选择设备。'
  if (device.status !== 'online') return `此电脑${agentDeviceStatus(device.status)}，请检查本地桥接。`
  if (!device.executionAgents?.includes(DEVICE_AGENT_RUNTIMES[agentKey])) return `执行通道未连接。请在此电脑运行 ${deviceExecutionCommand(agentKey)}，并确认管理员已启用此 Agent 的设备执行。`
  if (device.executionBusy) return allowBusy ? '' : '此电脑正在执行其他任务，请等待结束或选择另一台电脑。'
  if (!device.executionAvailable) return '此电脑的执行通道尚未就绪，请刷新后重试。'
  return ''
}

export function deviceExecutionLabel(device, agentKey) {
  if (device?.status !== 'online') return agentDeviceStatus(device?.status)
  if (agentKey && !device.executionAgents?.includes(DEVICE_AGENT_RUNTIMES[agentKey])) return `未开启 ${deviceAgentName(agentKey)}`
  if (device.executionBusy) return '正在执行'
  if (device.executionAvailable && device.executionAgents?.some(key => Object.values(DEVICE_AGENT_RUNTIMES).includes(key))) return '执行通道已连接'
  return '仅发现模式'
}

export function agentExecutionLocation(job, devices = []) {
  if (!isDeviceAgent(job?.agentKey)) return '平台运行主机'
  const device = devices.find(item => item.deviceId === job.deviceId)
  return device?.name || (job.deviceId ? `我的电脑 · ${job.deviceId.slice(0, 8)}` : '我的电脑 · 设备未记录')
}
