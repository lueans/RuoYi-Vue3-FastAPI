const wait = (delay) => new Promise(resolve => setTimeout(resolve, delay))

const MINDMAP_STRUCTURE_WRITE_COMMANDS = new Set([
  'BACK',
  'FORWARD',
  'INSERT_NODE',
  'INSERT_MULTI_NODE',
  'INSERT_CHILD_NODE',
  'INSERT_MULTI_CHILD_NODE',
  'INSERT_PARENT_NODE',
  'UP_NODE',
  'DOWN_NODE',
  'MOVE_UP_ONE_LEVEL',
  'INSERT_AFTER',
  'INSERT_BEFORE',
  'MOVE_NODE_TO',
  'REMOVE_NODE',
  'REMOVE_CURRENT_NODE',
  'PASTE_NODE',
  'CUT_NODE',
  'ADD_GENERALIZATION',
  'REMOVE_GENERALIZATION',
  'ADD_ASSOCIATIVE_LINE',
  'REMOVE_ASSOCIATIVE_LINE',
  'SET_ASSOCIATIVE_LINE_CONTROL_POINTS',
  'ADD_OUTER_FRAME',
  'REMOVE_OUTER_FRAME',
  'SET_NODE_CUSTOM_POSITION',
  'SET_NODE_EXPAND',
  'EXPAND_ALL',
  'UNEXPAND_ALL',
  'UNEXPAND_TO_LEVEL',
  'RESET_LAYOUT',
])

const MINDMAP_AUTO_EDIT_COMMAND_ARG_INDEX = new Map([
  ['INSERT_NODE', 0],
  ['INSERT_CHILD_NODE', 0],
  ['INSERT_PARENT_NODE', 0],
  ['ADD_GENERALIZATION', 1],
])

const MINDMAP_APPOINTED_NODES_ARG_INDEX = new Map([
  ['INSERT_NODE', 1],
  ['INSERT_CHILD_NODE', 1],
  ['INSERT_PARENT_NODE', 1],
])

export function shouldBlockMindmapStructureWrite(commandName, recoveryActive = false) {
  return recoveryActive === true && MINDMAP_STRUCTURE_WRITE_COMMANDS.has(commandName)
}

export function mindmapCommandStartsNodeTextEdit(
  commandName,
  commandArgs = [],
  { createNewNodeBehavior = 'default', activeNodeCount = 1 } = {},
) {
  const openEditArgIndex = MINDMAP_AUTO_EDIT_COMMAND_ARG_INDEX.get(commandName)
  if (openEditArgIndex === undefined) return false
  if (
    commandArgs[openEditArgIndex] === false
    || createNewNodeBehavior !== 'default'
  ) return false

  const appointedNodesArgIndex = MINDMAP_APPOINTED_NODES_ARG_INDEX.get(commandName)
  const appointedNodes = appointedNodesArgIndex === undefined
    ? null
    : commandArgs[appointedNodesArgIndex]
  const targetCount = Array.isArray(appointedNodes) && appointedNodes.length > 0
    ? appointedNodes.length
    : appointedNodes && typeof appointedNodes === 'object'
      ? 1
      : activeNodeCount
  // Render.getNewNodeBehavior 在多目标操作时明确关闭自动文本编辑；零目标
  // 也不会执行插入。只有单目标默认行为才需要提前检查文本租约能力。
  return targetCount === 1
}

export function getMindmapSaveRecoveryAction(saveStatus, recoveryKind) {
  if (saveStatus !== 'error') return null
  if (recoveryKind === 'conflict') {
    return {
      label: '处理冲突',
      ariaLabel: '处理保存冲突并安全加载云端版本',
    }
  }
  if (recoveryKind === 'draft') {
    return {
      label: '保护修改',
      ariaLabel: '重试保存本地草稿，失败时下载 JSON 备份',
    }
  }
  if (recoveryKind === 'sync') {
    return {
      label: '同步画布',
      ariaLabel: '重新加载云端已合并的最新脑图画布',
    }
  }
  if (recoveryKind !== 'retry') return null
  return {
    label: '重试保存',
    ariaLabel: '重新尝试保存脑图到云端',
  }
}

export function getMindmapResumeRecoveryReason({
  cloudRevision,
  localRevision,
  cloudNodeCount,
  localNodeCount,
  hasLocalChanges = false,
}) {
  if (
    !Number.isInteger(cloudRevision)
    || cloudRevision <= 0
    || !Number.isInteger(localRevision)
    || localRevision <= 0
  ) return null
  if (cloudRevision > localRevision) return 'newer-revision'
  if (cloudRevision < localRevision) return null
  // 同 revision 下节点数减少也可能是用户刚执行了删除、尚未自动保存。
  // 只有干净会话才可将其判定为运行时/Yjs 残缺并自动用云端修复。
  if (hasLocalChanges) return null
  return (
    Number.isInteger(cloudNodeCount)
    && cloudNodeCount > 0
    && Number.isInteger(localNodeCount)
    && localNodeCount >= 0
    && localNodeCount < cloudNodeCount
  )
    ? 'incomplete-runtime'
    : null
}

/**
 * Flush editor changes before route navigation without treating one successful
 * request as proof that the document is clean. A user can continue editing
 * while a save is in flight, so every pass re-checks the dirty state.
 */
export async function flushPendingMindmapChanges({
  hasUnsavedChanges,
  isSaveInProgress,
  requestSave,
  markPendingSave = () => {},
  persistLocalBackup = () => {},
  maxSavePasses = 3,
  activeSavePollAttempts = 100,
  activeSavePollDelay = 50,
  waitFor = wait,
}) {
  const preserveAndFail = () => {
    persistLocalBackup()
    return false
  }

  if (!hasUnsavedChanges()) return true

  for (let pass = 0; pass < maxSavePasses; pass += 1) {
    if (!hasUnsavedChanges()) return true

    if (isSaveInProgress()) {
      markPendingSave()
      for (
        let attempt = 0;
        attempt < activeSavePollAttempts && isSaveInProgress();
        attempt += 1
      ) {
        await waitFor(activeSavePollDelay)
      }
      if (isSaveInProgress()) return preserveAndFail()
      if (!hasUnsavedChanges()) return true
    }

    if (await requestSave() !== true) return preserveAndFail()
  }

  return hasUnsavedChanges() ? preserveAndFail() : true
}
