// Result presentation is independent of executor lifetime and connection state.
// This projection grants no edit/undo permission and never writes a document.
export function mindmapResultChangeCounts(impact) {
  const fields = ['createdCount', 'updatedCount', 'movedCount', 'deletedCount']
  if (!impact || !fields.every(key => Number.isSafeInteger(impact[key]) && impact[key] >= 0)) return null
  return Object.fromEntries(fields.map(key => [key, impact[key]]))
}

export function mindmapAgentResultState({ job = {}, historical = false, sourceIsCloud = false,
  direct = false, saving = false, saveFailed = false, undoing = false, reverting = false,
  livePreviewActive = false, catchingUp = false } = {}) {
  job ||= {}
  const state = (label, title, description, tone = 'neutral') => ({ label, title, description, tone,
    canvasNote: !historical && catchingUp ? '画布正在补齐最后的变更，显示完成不等于保存完成。' : '',
  })
  if (historical) return state('历史结果', '查看历史脑图结果', '仅查看或下载这轮结果，不改变当前脑图。')
  if (undoing || reverting) return state('处理中', '正在撤销本轮修改', '等待撤销确认，暂时不要重复操作。')
  // Durable outcomes win over stale UI activity flags after a receipt arrives.
  if (job.status === 'undone') return state('已撤销', '本轮 AI 修改已撤销', '撤销已确认，可以基于当前脑图继续。')
  if (job.status === 'rejected') return state('未采纳', '本轮变更未采纳', '当前脑图保持原内容，可以修改要求后重新生成。')
  if (job.status === 'completed_no_change') return state('无变更', '本轮没有新增修改', '已完成检查，当前脑图保持不变。')
  if (job.status === 'completed_file') return state('已保存', '已保存为云端脑图', '生成结果已另存为云端脑图，不表示覆盖了当前脑图。', 'success')
  if (job.status === 'completed_direct') return state('已提交', '本轮修改已写入云端', '云端写入已确认；画布同步和执行器退出状态单独确认。', 'success')
  if (job.status === 'applied') return sourceIsCloud
    ? state('已保存', '本轮修改已应用到云端', '云端应用已确认；可用的撤销操作显示在下方。', 'success')
    : state('已应用', '本轮修改已应用到本地脑图', '本地应用已确认；这不表示已另存为云端脑图。', 'success')
  if (saving) return state('保存中', '正在保存本轮结果', '正在等待保存确认，请勿重复提交。')
  if (saveFailed) return state('待恢复', '本轮结果保存未完成', '已接收的内容保留，可重试保存；未收到成功回执前不标记为已保存。', 'warning')
  if (job.status === 'needs_review') return state('待确认', '本轮变更需要你确认', '先查看差异并勾选确认，再采纳；也可以不采纳本轮。', 'warning')
  if (job.status === 'ready') return job.proposalId
    ? state('待保存', '本轮结果已生成', '结果已就绪，保存尚未确认。画布预览不代表已经应用。')
    : state('已生成', '独立脑图结果已生成', '可以下载、打开或另存为云端脑图，尚未应用到当前脑图。')
  if (['failed', 'stale', 'cancelled', 'expired'].includes(job.status)) {
    const title = ({ failed: '本轮任务失败', stale: '当前脑图版本已变化', cancelled: '本轮已停止更新', expired: '本轮结果已过期' })[job.status]
    return state('请核对结果', title, direct
      ? '已提交的修改不会因任务结束而自动回滚，请核对当前脑图。'
      : '已接收的结果保留；是否已应用以保存回执为准。', 'warning')
  }
  if (job.status === 'cancel_requested') return state('停止中', '正在停止本轮编辑', '等待 Agent 退出及最后修改的确认，停止不会自动撤销已提交内容。')
  if (job.status === 'needs_input') return state('待补充', '本轮需要补充信息', '请回答 Agent 的问题，再继续处理脑图。')
  if (['queued', 'waiting_turn', 'preparing'].includes(job.status)) return state('准备中', '正在准备本轮编辑', '尚未确认本轮结果，执行进度会在对话中显示。')
  if (!['running', 'validating'].includes(job.status)) return state('待确认', '本轮结果状态待确认', '请等待或刷新结果；未收到应用回执前不标记为已保存。')
  return direct
    ? state('编辑中', 'AI 正在编辑云端脑图', '已确认的修改会实时写入云端；关闭面板不会停止任务，停止也不会撤销已提交内容。')
    : state('生成中', livePreviewActive ? 'AI 正在更新脑图预览' : 'AI 正在准备脑图结果', '实时预览会继续更新，最终保存状态单独确认。')
}
