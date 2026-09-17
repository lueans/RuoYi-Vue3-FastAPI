const MINDMAP_AI_ERROR_MESSAGES = Object.freeze({
  AI_AGENT_UNAVAILABLE: 'AI Agent 暂不可用，请切换 Agent 或稍后重试',
  AI_CAPABILITY_UNSUPPORTED: '所选 Agent 不支持当前任务或输入来源，请调整选择',
  AI_INPUT_INVALID: '输入内容或授权范围无效，请检查后重试',
  AI_INPUT_TOO_LARGE: '输入内容超过任务上限，请缩小范围或降低节点上限',
  AI_BUDGET_EXCEEDED: '任务已达到预算、用量或时长上限，请缩小范围后重试',
  AI_TIMEOUT: 'AI 任务运行超时，请缩小范围或稍后重试',
  AI_OUTPUT_INVALID: 'AI 输出未通过安全与结构校验；可保留错误详情后重试任务，或切换 Agent 再试',
  AI_JOB_NOT_FOUND: '要重试的 AI 任务不存在或当前账号无权访问',
  AI_JOB_NOT_RETRYABLE: '当前任务状态不能重试；请刷新任务状态后再操作',
  AI_SESSION_UNAVAILABLE: '原 AI 会话不存在或已结束，无法保留该会话记录继续重试',
  AI_RETRY_SOURCE_EXPIRED: '原任务输入已过期或不完整，请新建任务',
  AI_RETRY_REQUEST_INVALID: '重试设置与原任务不兼容，请调整 Agent、模型或要求',
  AI_RETRY_STATE_CHANGED: '原任务或会话状态已变化，请刷新后重试',
  AI_FOLLOWUP_UNAVAILABLE: '当前结果不能继续调整，请选择可继续的完成轮次或新建对话',
  AI_FOLLOWUP_BASE_INVALID: '继续调整的内容基线无效，请回到原脑图并刷新后重试',
  AI_FOLLOWUP_STATE_CHANGED: '继续调整前任务状态已变化，请刷新后重试',
  AI_PROPOSAL_STALE: '脑图内容已变化，请基于最新版本重新生成提案',
  AI_PROPOSAL_NOT_FOUND: 'AI 提案不存在或当前账号无权访问，请重新生成',
  AI_PROPOSAL_STATE_INVALID: 'AI 提案当前状态不可应用，请刷新后重新生成',
  AI_PROPOSAL_INTEGRITY_INVALID: 'AI 提案与生成结果不一致，已阻止应用；请保留错误详情并重新生成',
  AI_PROPOSAL_FORMAT_OBSOLETE: '该 AI 提案来自旧版操作协议，无法安全升级时请重新生成',
  AI_APPLY_CONFLICT: '确认期间仍有新的协作修改，覆盖未完成；请再次点击覆盖当前脑图',
  AI_UNDO_CONFLICT: '应用后已有其他修改，当前不能安全撤销',
  AI_UNDO_NOT_FOUND: 'AI 撤销记录不存在或当前账号无权访问，请人工核对脑图',
  AI_UNDO_STATE_INVALID: 'AI 撤销记录已过期或不可用，请人工核对脑图',
  AI_UNDO_SNAPSHOT_INVALID: 'AI 撤销快照不可用，请人工核对脑图',
  AI_SANDBOX_VIOLATION: 'Agent 尝试执行未授权操作，任务已被安全终止',
  AI_PROVIDER_AUTH_FAILED: 'AI 供应商认证失败，请联系管理员检查 Connector',
  AI_RATE_LIMITED: 'AI 服务当前请求过多，请稍后重试',
  AI_TASK_CANCELLED: 'AI 任务已取消，可新建任务重新生成',
  AI_ARTIFACT_EXPIRED: 'AI 结果已过期，请重新生成',
  AI_EVENT_INVALID: '收到无效的实时事件，正在通过状态同步恢复',
  AI_EVENT_TOO_LARGE: '实时事件超过安全大小限制，已中断本次连接',
  AI_STREAM_CONNECTION_FAILED: 'AI 实时连接暂时不可用，正在通过轮询同步',
  AI_AUTH_REQUIRED: '登录状态已失效，请重新登录后继续',
})

export function resolveMindmapAiErrorCode(error) {
  const candidates = [
    error?.errorCode,
    error?.data?.errorCode,
    error?.response?.data?.data?.errorCode,
    error?.code,
  ]
  return candidates.find(value => (
    typeof value === 'string' && /^(?:AI|TESTCASE)_[A-Z0-9_]+$/.test(value)
  )) || ''
}

export function formatMindmapAiError(error, fallback = 'AI 脑图操作失败') {
  const code = resolveMindmapAiErrorCode(error)
  if (code && MINDMAP_AI_ERROR_MESSAGES[code]) return MINDMAP_AI_ERROR_MESSAGES[code]
  const detail = typeof error === 'string'
    ? error
    : error?.message
  return typeof detail === 'string' && detail.trim() ? detail.trim() : fallback
}

// Only call this for a job/status snapshot returned by the mind-map AI API.
// Those messages are persisted after server-side sanitization and may contain
// essential limit details (for example, actual 102 nodes versus an allowed
// 100). Arbitrary request/provider exceptions must continue through
// formatMindmapAiError so an untrusted technical message cannot bypass the
// stable, user-safe code mapping.
export function formatMindmapAiJobError(job, fallback = 'AI 脑图任务失败') {
  const code = resolveMindmapAiErrorCode(job)
  const advice = (code && MINDMAP_AI_ERROR_MESSAGES[code]) || fallback
  const detail = typeof job?.errorMessage === 'string'
    ? job.errorMessage
      .replace(/[\u0000-\u001f\u007f]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 500)
    : ''
  const codeLabel = code ? `错误码：${code}` : ''
  if (!detail) return codeLabel ? `${advice}（${codeLabel}）` : advice
  if (detail === advice) return codeLabel ? `${detail}（${codeLabel}）` : detail
  return `${detail}${codeLabel ? `（${codeLabel}）` : ''}；${advice}`
}

export async function assertMindmapAiArtifactDownloadResponse(blob) {
  if (!blob || typeof blob.text !== 'function') return blob
  const contentType = String(blob.type || '').toLowerCase()
  if (contentType && !contentType.includes('json')) return blob
  let payload
  try {
    payload = JSON.parse(await blob.text())
  } catch {
    return blob
  }
  if (
    !payload
    || typeof payload !== 'object'
    || payload.format === 'ruoyi-mindmap'
    || (payload.success !== false && Number(payload.code || 200) === 200)
  ) return blob
  const error = new Error(payload.msg || 'AI 脑图文件下载失败')
  error.data = payload.data
  error.code = payload.data?.errorCode || payload.code
  throw error
}
