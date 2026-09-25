import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const [source, editorSource] = await Promise.all([
  readFile(
    new URL('../../components/MindMap/VersionHistory.vue', import.meta.url),
    'utf8'
  ),
  readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8'
  ),
])

test('version list ignores stale tab and pagination responses and exposes retry state', () => {
  assert.match(source, /const requestId = \+\+loadRequestId/)
  assert.match(source, /requestId !== loadRequestId \|\| !componentActive/)
  assert.match(source, /loadError\.value = e\?\.message \|\| '版本列表加载失败'/)
  assert.match(source, /role="alert"/)
  assert.match(source, /@click="loadVersions">重新加载/)
})

test('version operations share one busy lock and destructive actions cannot overlap', () => {
  assert.match(source, /const operationType = ref\(''\)/)
  assert.match(source, /const isOperating = computed\(\(\) => Boolean\(operationType\.value\)\)/)
  assert.match(source, /let operationSequence = 0/)
  assert.match(source, /beginOperation\(`confirm-restore:\$\{versionId\}`\)/)
  assert.match(source, /updateOperation\(operationToken, `restore:\$\{versionId\}`\)/)
  assert.match(source, /beginOperation\(`confirm-delete:\$\{versionId\}`\)/)
  assert.match(source, /updateOperation\(operationToken, `delete:\$\{versionId\}`\)/)
  assert.match(source, /if \(token === operationSequence\) operationType\.value = ''/)
  assert.match(source, /:disabled="isOperating"/)
})

test('AI 实时预览期间禁止历史版本覆盖当前画布', () => {
  assert.match(source, /aiPreviewActive: \{ type: Boolean, default: false \}/)
  assert.match(source, /const aiPreviewBlocked = computed\(\(\) => props\.aiPreviewActive === true\)/)
  assert.match(source, /请先采纳或不采纳当前 AI 实时预览，再查看历史版本/)
  assert.match(source, /:disabled="isOperating \|\| aiPreviewBlocked"/)
  assert.match(editorSource, /:ai-preview-active="aiEditingBlocked"/)
})

test('formal version creation freezes editing across flush and snapshot creation', () => {
  const saveBlock = source.match(/async function handleSaveVersion[\s\S]*?\n\}/)?.[0] || ''
  const transitionIndex = saveBlock.indexOf('beginEditingTransition(session)')
  const settleIndex = saveBlock.indexOf('await settleSessionChanges(')
  const snapshotIndex = saveBlock.indexOf('await saveFormalVersion({')
  const releaseIndex = saveBlock.indexOf('endEditingTransition(session)')

  assert.ok(transitionIndex > 0)
  assert.ok(settleIndex > transitionIndex)
  assert.ok(snapshotIndex > settleIndex)
  assert.ok(releaseIndex > snapshotIndex)
  assert.match(saveBlock, /当前修改尚未成功保存，暂不能创建正式版本/)
})

test('restoring a version flushes current edits before the irreversible request', () => {
  const restoreBlock = source.match(/async function handleRestore[\s\S]*?\n\}/)?.[0] || ''
  const transitionIndex = restoreBlock.indexOf('beginEditingTransition(session)')
  const flushIndex = restoreBlock.indexOf('await settleSessionChanges(')
  const restoreIndex = restoreBlock.indexOf('await restoreVersion(versionId, {')

  assert.ok(transitionIndex > 0)
  assert.ok(flushIndex > transitionIndex)
  assert.ok(restoreIndex > flushIndex)
  assert.match(source, /当前修改尚未成功保存，暂不能恢复历史版本/)
})

test('preview flushes the live mutation before pausing collaboration or replacing the canvas', () => {
  const previewBlock = source.match(/async function handlePreview[\s\S]*?async function applyFullDataAndWait/)?.[0] || ''
  const settleBlock = source.match(/async function settleSessionChanges[\s\S]*?\n\}/)?.[0] || ''
  const transitionIndex = previewBlock.indexOf('beginEditingTransition(session)')
  const fetchIndex = previewBlock.indexOf('await getVersionDetail(versionId)')
  const settleIndex = previewBlock.indexOf('await settleSessionChanges(')
  const closeOutlineIndex = settleBlock.indexOf('closeSessionEditors(session)')
  const flushIndex = settleBlock.indexOf('await session.flushChanges()')
  const finalCloseIndex = settleBlock.indexOf('closeSessionEditors(session)', flushIndex)
  const finalTickIndex = settleBlock.indexOf('await nextTick()', finalCloseIndex)
  const snapshotIndex = previewBlock.indexOf('_prePreviewState = session.mindMap.getData(true)')
  const readonlyIndex = previewBlock.indexOf("session.mindMap.setMode?.('readonly')")
  const pauseIndex = previewBlock.indexOf('session.yjsSync.pause()')
  const applyIndex = previewBlock.indexOf('await applyFullDataAndWait({')

  assert.ok(transitionIndex > 0)
  assert.ok(fetchIndex > transitionIndex)
  assert.ok(settleIndex > fetchIndex)
  assert.ok(closeOutlineIndex >= 0)
  assert.ok(flushIndex > closeOutlineIndex)
  assert.ok(finalCloseIndex > flushIndex)
  assert.ok(finalTickIndex > finalCloseIndex)
  assert.ok(snapshotIndex > settleIndex)
  assert.ok(readonlyIndex > snapshotIndex)
  assert.ok(pauseIndex > readonlyIndex)
  assert.ok(applyIndex > pauseIndex)
  assert.match(previewBlock, /当前修改尚未成功保存，暂不能预览历史版本/)
  assert.match(previewBlock, /if \(!isCurrentSession\(session\)\) return[\s\S]*?_prePreviewState/)
  assert.match(settleBlock, /boundaryVersion !== settledVersion[\s\S]*?await session\.flushChanges\(\)/)
  assert.match(settleBlock, /等待期间检测到新的本地修改，请重试当前操作/)
})

test('version transitions gate every editor while allowing the frozen batch to flush', () => {
  assert.match(source, /defineEmits\(\['change-tracking', 'editing-transition'\]\)/)
  assert.match(source, /function beginEditingTransition[\s\S]*?emit\('editing-transition', true\)/)
  assert.match(source, /function endEditingTransition[\s\S]*?emit\('editing-transition', false\)/)
  assert.match(editorSource, /@editing-transition="onVersionEditingTransition"/)
  assert.match(editorSource, /:get-content-change-version="getCurrentContentChangeVersion"/)
  assert.match(
    editorSource,
    /function onVersionEditingTransition[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?setVersionTransitionEditingBlocked\(true\)/,
  )
  assert.match(
    editorSource,
    /const aiDialogReadonly = computed[\s\S]*?versionTransitionEditingBlocked\.value[\s\S]*?importTransitionEditingBlocked\.value/,
  )
  assert.match(
    editorSource,
    /function canFlushCloudChangesDuringEditingTransition[\s\S]*?!authoritativeRecoveryEditingBlocked\.value/,
  )
})

test('preview exit restores the full document before resuming Yjs and tracking', () => {
  const exitBlock = source.match(/function exitPreview[\s\S]*?\n\}/)?.[0] || ''
  assert.match(source, /function applyFullDataAndWait/)
  assert.match(source, /node_tree_render_end/)
  assert.match(source, /_previewAuthoritativeResetGeneration = props\.authoritativeResetGeneration/)
  assert.match(source, /function hasAuthoritativeResetSincePreview/)
  assert.match(exitBlock, /if \(state && !authoritativeResetPending\)/)
  assert.match(exitBlock, /\(\) => !hasAuthoritativeResetSincePreview\(\)/)
  assert.match(exitBlock, /if \(!authoritativeResetPending\) previewSession\?\.yjsSync\?\.resume\(\)/)
  assert.match(exitBlock, /emit\('change-tracking', false, \{ authoritativeResetPending \}\)/)
  assert.match(exitBlock, /endEditingTransition\(previewSession\)/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*exitPreview\(\{ notify: false \}\)/)
  const applyIndex = exitBlock.indexOf('await applyFullDataAndWait(')
  const resumeIndex = exitBlock.indexOf('previewSession?.yjsSync?.resume()', applyIndex)
  const trackingIndex = exitBlock.indexOf("emit('change-tracking', false", applyIndex)
  const releaseEditingIndex = exitBlock.indexOf('endEditingTransition(previewSession)', trackingIndex)
  assert.ok(applyIndex > 0)
  assert.ok(resumeIndex > applyIndex)
  assert.ok(trackingIndex > resumeIndex)
  assert.ok(releaseEditingIndex > trackingIndex)
})

test('preview renderer failures fence the old collaboration and never resume a half-applied tree', () => {
  const previewBlock = source.match(
    /async function handlePreview[\s\S]*?async function applyFullDataAndWait/,
  )?.[0] || ''
  const exitBlock = source.match(/function exitPreview[\s\S]*?^\}/m)?.[0] || ''
  const fenceBlock = source.match(
    /function fencePreviewApplyFailure[\s\S]*?^\}/m,
  )?.[0] || ''

  assert.match(
    previewBlock,
    /applyFullDataAndWait\([\s\S]*?isCurrentSession\(session\)[\s\S]*?_editingTransitionSession === session[\s\S]*?!hasAuthoritativeResetSincePreview\(\)/,
  )
  assert.match(
    previewBlock,
    /const previewApplied = await applyFullDataAndWait[\s\S]*?if \(previewApplied === false\) \{[\s\S]*?await exitPreview\(\{ notify: false \}\)/,
  )
  assert.match(
    previewBlock,
    /catch \(e\)[\s\S]*?fencePreviewApplyFailure\(session, e\)[\s\S]*?exitPreview/,
  )
  assert.match(fenceBlock, /session\?\.fenceAuthoritativeWrite\?\.\(revision\) === true/)
  assert.match(
    source,
    /function hasAuthoritativeResetSincePreview[\s\S]*?_previewAuthoritativeRecoveryFenced/,
  )
  assert.match(
    exitBlock,
    /catch \(error\)[\s\S]*?fencePreviewApplyFailure\(previewSession, error\)[\s\S]*?authoritativeResetPending = true/,
  )
  assert.match(exitBlock, /if \(!authoritativeResetPending\) previewSession\?\.yjsSync\?\.resume\(\)/)
  const emitIndex = exitBlock.indexOf("emit('change-tracking', false")
  const clearFenceIndex = exitBlock.indexOf(
    '_previewAuthoritativeRecoveryFenced = false',
    emitIndex,
  )
  assert.ok(emitIndex >= 0)
  assert.ok(clearFenceIndex > emitIndex)
})

test('closing the version sidebar keeps preview state mounted until it can resume collaboration', () => {
  assert.match(
    editorSource,
    /<template v-if="mindMap">[\s\S]*?<VersionHistory[\s\S]*?v-show="activeSidebar === 'versionHistory'"/,
  )
  assert.doesNotMatch(
    editorSource,
    /<VersionHistory\s+v-if="mindMap && activeSidebar === 'versionHistory'"/,
  )
})

test('历史文档在替换画布前加载实际需要的复杂渲染插件', () => {
  const ensureIndex = source.indexOf('await ensureMindmapDocumentPlugins(data, mindMap)')
  const applyIndex = source.indexOf('mindMap.setFullData(data)', ensureIndex)

  assert.ok(ensureIndex > 0)
  assert.ok(applyIndex > ensureIndex)
  assert.match(source, /await applyFullDataAndWait\(\{[\s\S]*root: versionData\.nodeTree/)
})

test('version operations capture the editor session and ignore late responses after navigation', () => {
  assert.match(source, /function captureSession\(\)/)
  assert.match(source, /function isCurrentSession\(session\)/)
  assert.match(source, /session\.mindmapId === props\.mindmapId/)
  assert.match(source, /session\.mindMap === props\.mindMap/)
  assert.match(source, /session\.yjsSync === props\.yjsSync/)
  assert.match(source, /getContentChangeVersion: props\.getContentChangeVersion/)
  assert.match(source, /fenceAuthoritativeWrite: props\.fenceAuthoritativeWrite/)
  assert.match(source, /applyAuthoritativeDocument: props\.applyAuthoritativeDocument/)
  assert.match(source, /const res = await getVersionDetail\(versionId\)[\s\S]*if \(!isCurrentSession\(session\)\) return/)
  assert.match(source, /await settleSessionChanges\([\s\S]*?await restoreVersion\(versionId, \{/)
  assert.match(source, /getMindmap\(session\.mindmapId\)/)
  assert.match(source, /await deleteVersion\(versionId\)[\s\S]*if \(!isCurrentSession\(session\)\) return/)
})

test('preview never restores or resumes a collaboration instance superseded while awaiting async work', () => {
  assert.match(
    source,
    /function hasAuthoritativeResetSincePreview\(\)[\s\S]*?authoritativeResetGeneration !== _previewAuthoritativeResetGeneration[\s\S]*?!isCurrentSession\(_previewSession\)/,
  )
  assert.match(
    source,
    /applyFullDataAndWait\([\s\S]*?\(\) => !hasAuthoritativeResetSincePreview\(\)/,
  )
})

test('stale collaboration recovery is deferred until historical preview has fully exited', () => {
  const markBlock = editorSource.match(
    /function markAuthoritativeReloadRequired[\s\S]*?\n\}/,
  )?.[0] || ''
  const reloadBlock = editorSource.match(
    /async function performAuthoritativeReload[\s\S]*?\n\}/,
  )?.[0] || ''
  const staleBlock = editorSource.match(
    /async function handleStaleCollaborationState[\s\S]*?\n\}/,
  )?.[0] || ''
  const trackingBlock = editorSource.match(
    /function onVersionChangeTracking[\s\S]*?\n\}/,
  )?.[0] || ''
  const startBlock = editorSource.match(
    /function startYjsSyncIfReady[\s\S]*?\n\}/,
  )?.[0] || ''

  assert.match(markBlock, /authoritativeResetGeneration\.value \+= 1/)
  assert.match(reloadBlock, /versionChangeTrackingPaused/)
  assert.match(staleBlock, /if \(versionChangeTrackingPaused \|\| resolvingStaleState/)
  assert.match(startBlock, /versionChangeTrackingPaused/)
  assert.match(trackingBlock, /setAuthoritativeRecoveryEditingBlocked\(true\)/)
  assert.match(trackingBlock, /scheduleAuthoritativeReload\(\)/)
  assert.match(trackingBlock, /startYjsSyncIfReady\(\)/)
  assert.match(trackingBlock, /setTimeout\(\(\) => \{ void saveToBackend\(\) \}, AUTO_SAVE_DELAY\)/)
})

test('version restore freezes a CAS revision and one idempotency key after flushing', async () => {
  const apiSource = await readFile(
    new URL('../../api/mindmap/version.js', import.meta.url),
    'utf8',
  )
  const restoreBlock = source.match(/async function handleRestore[\s\S]*?\n\}/)?.[0] || ''
  const flushIndex = restoreBlock.indexOf('await settleSessionChanges(')
  const revisionIndex = restoreBlock.indexOf('session.getContentRevision?.()')
  const mutationIndex = restoreBlock.indexOf('const clientMutationId = createMutationId()')
  const requestIndex = restoreBlock.indexOf('await restoreVersion(versionId, {')

  assert.match(source, /getContentRevision: \{ type: Function/)
  assert.match(source, /getContentRevision: props\.getContentRevision/)
  assert.match(source, /getContentChangeVersion: \{ type: Function/)
  assert.match(source, /fenceAuthoritativeWrite: \{ type: Function/)
  assert.ok(revisionIndex > flushIndex)
  assert.ok(mutationIndex > revisionIndex)
  assert.ok(requestIndex > mutationIndex)
  assert.match(
    restoreBlock,
    /await restoreVersion\(versionId, \{[\s\S]*?expectedRevision,[\s\S]*?clientMutationId,/,
  )
  assert.match(
    restoreBlock,
    /restoreResponse\.data\?\.contentRevision[\s\S]*?session\.fenceAuthoritativeWrite\?\.\(restoredRevision\)[\s\S]*?getMindmap\(session\.mindmapId\)/,
  )
  assert.match(
    apiSource,
    /export function restoreVersion\(versionId, data\)[\s\S]*?method: 'post',[\s\S]*?data/,
  )
  assert.match(editorSource, /:get-content-revision="getCurrentContentRevision"/)
  assert.match(editorSource, /:fence-authoritative-write="fenceAuthoritativeVersionWrite"/)
})

test('version confirmations lock before dialogs and only act on current listed targets', () => {
  const saveLockIndex = source.indexOf("beginOperation('confirm-save')")
  const saveDialogIndex = source.indexOf("ElMessageBox.prompt('请输入版本名称（可选）'")
  const restoreLockIndex = source.indexOf('beginOperation(`confirm-restore:${versionId}`)')
  const restoreDialogIndex = source.indexOf('ElMessageBox.confirm(', restoreLockIndex)
  const deleteLockIndex = source.indexOf('beginOperation(`confirm-delete:${versionId}`)')
  const deleteDialogIndex = source.indexOf('ElMessageBox.confirm(', deleteLockIndex)

  assert.ok(saveLockIndex > 0 && saveDialogIndex > saveLockIndex)
  assert.ok(restoreLockIndex > 0 && restoreDialogIndex > restoreLockIndex)
  assert.ok(deleteLockIndex > 0 && deleteDialogIndex > deleteLockIndex)
  assert.match(source, /function getListedVersionId\(item, \{ formalOnly = false \} = \{\}\)/)
  assert.match(source, /Number\.isSafeInteger\(id\)/)
  assert.match(source, /getListedVersionId\(item, \{ formalOnly: true \}\) !== versionId/)
  assert.match(source, /size="small"/)
  assert.match(source, /:disabled="isOperating \|\| isPreviewing \|\| aiPreviewBlocked"/)
  assert.doesNotMatch(source, /\n\s+small\n/)
})

test('failed preview restores the captured live tree instead of resuming over partial history data', () => {
  assert.match(source, /catch \(e\) \{[\s\S]*if \(isPreviewing\.value\) \{[\s\S]*await exitPreview\(\{ notify: false \}\)/)
  assert.match(source, /_previewSession = session/)
})

test('restore detail failure never reseeds collaboration with the stale local tree', () => {
  assert.doesNotMatch(source, /getData\(\)\?\.root/)
  assert.doesNotMatch(source, /emit\('yjs-reinit'/)
  assert.match(source, /后端已经广播 document_reset/)
  assert.match(source, /restoreResponse\.data\?\.contentRevision/)
  assert.match(
    editorSource,
    /function fenceAuthoritativeVersionWrite[\s\S]*?markAuthoritativeReloadRequired\(\)[\s\S]*?setAuthoritativeRecoveryEditingBlocked\(true\)[\s\S]*?stopCurrentCollaborationSource\(\)/,
  )
})

test('restore applies the complete authoritative response through the editor state ledger', () => {
  const restoreBlock = source.match(/async function handleRestore[\s\S]*?\n\}/)?.[0] || ''
  const applyBlock = editorSource.match(/function applyRestoredVersionData[\s\S]*?\n\}/)?.[0] || ''
  const reloadBlock = editorSource.match(/async function reloadLatestServerDocument[\s\S]*?\n\}/)?.[0] || ''

  assert.match(source, /applyAuthoritativeDocument: \{ type: Function/)
  assert.match(
    restoreBlock,
    /await session\.applyAuthoritativeDocument\(versionData, \{[\s\S]*?minimumContentRevision: restoredRevision/,
  )
  assert.doesNotMatch(restoreBlock, /contentRevision: versionData\.contentRevision \|\| restoredRevision/)
  assert.doesNotMatch(restoreBlock, /applyFullDataAndWait/)
  assert.match(editorSource, /:apply-authoritative-document="applyRestoredVersionData"/)
  assert.match(
    applyBlock,
    /const restoredRevision = Number\(options\.minimumContentRevision\)[\s\S]*?minimumContentRevision,/,
  )
  assert.match(applyBlock, /reloadLatestServerDocument\(\{[\s\S]*?serverData,/)
  assert.match(reloadBlock, /documentData\.value = nextDocumentData/)
  assert.match(reloadBlock, /nodeRevisionMap\.clear\(\)[\s\S]*?data\.nodeRevisions/)
  assert.match(reloadBlock, /crossNodeOperationSnapshot = extractCrossNodeState/)
  assert.match(reloadBlock, /markDocumentMetaSaved\(/)
  assert.match(reloadBlock, /onYjsReinit\(data\.nodeTree \|\| defaultData, contentRevision\)/)
})

test('closing a delete confirmation is treated as cancellation', () => {
  assert.match(source, /e !== 'cancel' && e !== 'close'/)
})
