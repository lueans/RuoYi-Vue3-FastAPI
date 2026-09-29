import { agentExecutionLocation, isDeviceAgent } from './mindmap-agent-devices.js'

const text = (value, limit = 500) => typeof value === 'string'
  ? value.length > limit ? `${value.slice(0, limit)}…` : value : ''

// Read-only presentation. The caller supplies owner-scoped state; this does
// not grant permissions, move queued jobs, or interpret a Todo as a receipt.
export function projectAgentHandoff({ job = {}, target = {}, ownerId, agents = [], devices = [],
  events = [], turns = [], timelineReceipt, timelineLoading = false, timelineError = '',
  resultState, scopeType } = {}) {
  job ||= {}
  const execution = binding => ({
    name: text(agents.find(agent => agent.agentKey === binding.agentKey)?.displayName || binding.agentKey || '未记录', 100),
    location: text(agentExecutionLocation(binding, devices), 100),
  })
  const current = execution(job), next = execution(target)
  const latest = events.filter(event => event?.jobId === job.id && event.eventType === 'todo_updated'
    && (!event.sessionId || event.sessionId === job.sessionId)
    && (event.payload?.executionEpoch == null || event.payload.executionEpoch === job.executionEpoch))
    .sort((a, b) => Number(b.sequence || 0) - Number(a.sequence || 0))[0]
  const rawTodos = latest?.payload?.todos
  const validTodos = Array.isArray(rawTodos) ? rawTodos.filter(item => typeof item?.content === 'string' && item.content.trim()) : []
  const todo = {
    known: Array.isArray(rawTodos),
    complete: Array.isArray(rawTodos) && validTodos.length === rawTodos.length && rawTodos.length <= 40,
    current: text(validTodos.find(item => item.status === 'in_progress')?.content, 140),
    items: validTodos.slice(0, 40).filter(item => item.status !== 'completed').map(item => ({
      content: text(item.content),
      status: ['pending', 'in_progress'].includes(item.status) ? item.status : 'unknown',
    })),
  }
  const queueJobs = turns.filter(turn => turn?.job?.id && turn.job.id !== job.id
    && job.sessionId && turn.job.sessionId === job.sessionId
    && ['waiting_turn', 'queued'].includes(turn.job.status))
    .sort((a, b) => Number(a.job.turnIndex || 0) - Number(b.job.turnIndex || 0)
      || String(a.job.id).localeCompare(String(b.job.id)))
  const queue = {
    known: !!ownerId && String(timelineReceipt?.ownerId) === String(ownerId)
      && !!job.sessionId && timelineReceipt?.sessionId === job.sessionId && !timelineLoading && !timelineError,
    items: queueJobs.map(turn => ({ id: turn.job.id, prompt: text(turn.userMessage?.content || '请求内容未同步', 160),
      agent: execution(turn.job).name, location: execution(turn.job).location })),
  }
  return {
    current, next, todo, queue,
    scope: ({ document: '整张脑图', branch: '指定分支', selectedNodes: '指定节点' })[scopeType]
      || (job.sourceType === 'none' ? '新建脑图，不扩大当前文档授权' : '详细授权范围未确认；仍以本轮已确认范围为准'),
    dataNotice: isDeviceAgent(job.agentKey) || isDeviceAgent(target.agentKey)
      ? '电脑执行仍可能将授权的脑图上下文发送给模型服务，不代表离线运行。切换不扩大编辑权限。'
      : '授权的脑图上下文由平台运行主机提交给模型服务；切换不扩大编辑权限。',
    result: job.intent === 'discuss' || job.target === 'message'
      ? { title: '本轮为讨论', description: '不将对话或 Todo 完成状态视为脑图写入。' }
      : resultState || { title: '结果状态待确认', description: '未收到保存回执，不将实时预览标为已保存。' },
    // Streaming result/Todo updates are informational. Execution identity and
    // queued requests change the consequences and require another confirmation.
    consentKey: JSON.stringify([ownerId, job.sessionId, job.id, job.executionEpoch,
      job.agentKey, job.deviceId, target.agentKey, target.deviceId, current, next, scopeType,
      queue.known, queueJobs.map(turn => [turn.job.id, turn.job.status, turn.job.agentKey,
        turn.job.deviceId, turn.userMessage?.content])]),
  }
}
