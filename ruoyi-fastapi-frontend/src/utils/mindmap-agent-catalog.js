// Presentation only: discovery, connector health and personal model readiness
// are separate evidence. This projection never changes selection permissions.
export function agentCatalogReadiness(agent = {}, selectionIssue = '') {
  const state = (label, description, tone = 'info') => ({ label, description, tone })
  if (selectionIssue) return state('当前配置需处理', selectionIssue, 'warning')
  if (agent.status !== 'enabled') return state('暂不可用', agent.statusReason || '平台尚未开放此 Agent，请联系管理员检查。', 'warning')
  if (agent.healthStatus === 'unhealthy') return state('环境检查未通过', agent.healthReason || '最近的运行环境检查未通过，请检查配置后重试。', 'warning')
  if (agent.agentKey === 'native_mindmap') return state('模型待校验', '平台已允许选择；个人模型的配置、登录和可用性在运行前校验。')
  if (agent.healthStatus === 'healthy') return state('环境已检查', '平台最近的环境检查已通过；本次任务仍按所选模型与权限校验。', 'success')
  return state('运行前检查', '平台已允许选择；登录与运行环境将在运行前检查。')
}

export function agentRuntimeDiscovery(runtime) {
  if (!runtime) return '尚无扫描结果'
  if (runtime.status === 'not_installed') return runtime.sdkInstalled ? '未发现独立 CLI · SDK 已安装' : '未发现 CLI'
  const labels = { detected: 'CLI 已发现', incompatible: 'CLI 协议不兼容', probe_failed: 'CLI 探测失败' }
  return Object.hasOwn(labels, runtime.status) ? labels[runtime.status] : '扫描状态未知'
}

export function agentCatalogCheckTime(value) {
  if (!['number', 'string'].includes(typeof value) || (typeof value === 'string' && !value.trim())) return ''
  const timestamp = typeof value === 'number' ? value : Date.parse(value)
  if (!Number.isFinite(timestamp) || timestamp <= 0) return ''
  const date = new Date(timestamp)
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : ''
}
