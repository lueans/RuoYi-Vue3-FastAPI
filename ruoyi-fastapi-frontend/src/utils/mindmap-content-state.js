const CONTENT_STATE_PRESENTATIONS = Object.freeze({
  ready: {
    type: 'success',
    title: '',
    description: '',
  },
  migration_failed: {
    type: 'warning',
    title: '该脑图已进入迁移保护模式',
    description: '结构化数据未通过迁移一致性校验，已使用兼容快照只读展示。请联系管理员重试迁移。',
  },
  integrity_failed: {
    type: 'error',
    title: '该脑图已进入数据保护模式',
    description: '结构化内容完整性校验失败，当前仅展示兼容快照，不能继续编辑。请联系管理员修复。',
  },
  load_failed: {
    type: 'warning',
    title: '结构化内容暂时不可用',
    description: '当前仅展示兼容快照，已暂停编辑以保护数据。请稍后重新加载。',
  },
})

export function normalizeMindmapContentState(value) {
  if (value === undefined || value === null || value === '') return 'ready'
  const state = String(value)
  return Object.hasOwn(CONTENT_STATE_PRESENTATIONS, state) ? state : 'load_failed'
}

export function isMindmapContentWritable(value) {
  return normalizeMindmapContentState(value) === 'ready'
}

export function getMindmapContentStatePresentation(value, message = '') {
  const state = normalizeMindmapContentState(value)
  const presentation = CONTENT_STATE_PRESENTATIONS[state]
  return {
    state,
    type: presentation.type,
    title: presentation.title,
    description: String(message || '').trim() || presentation.description,
  }
}
