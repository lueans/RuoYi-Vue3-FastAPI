import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  flushPendingMindmapChanges,
  getMindmapSaveRecoveryAction,
  getMindmapResumeRecoveryReason,
  mindmapCommandStartsNodeTextEdit,
  shouldBlockMindmapStructureWrite,
} from '../mindmap-save-lifecycle.js'
import {
  mindmapDocumentRequiresFullRuntimeReplacement,
  mindmapTreeContainsAssociativeLine,
  mindmapTreeContainsExactOuterFrame,
  mindmapTreeContainsNodeUid,
  mindmapTreeNodeIsRuntimeVisible,
  mindmapTreeNodesHaveSameEditableData,
  mindmapTreesHaveSameCrossNodeState,
} from '../mindmap-document-apply.js'

test('save recovery action distinguishes retry failures from blocked conflicts', () => {
  assert.equal(getMindmapSaveRecoveryAction('saved', 'retry'), null)
  assert.equal(getMindmapSaveRecoveryAction('offline', 'retry'), null)
  assert.equal(getMindmapSaveRecoveryAction('error', ''), null)
  assert.deepEqual(getMindmapSaveRecoveryAction('error', 'retry'), {
    label: '重试保存',
    ariaLabel: '重新尝试保存脑图到云端',
  })
  assert.deepEqual(getMindmapSaveRecoveryAction('error', 'conflict'), {
    label: '处理冲突',
    ariaLabel: '处理保存冲突并安全加载云端版本',
  })
  assert.deepEqual(getMindmapSaveRecoveryAction('error', 'draft'), {
    label: '保护修改',
    ariaLabel: '重试保存本地草稿，失败时下载 JSON 备份',
  })
  assert.deepEqual(getMindmapSaveRecoveryAction('error', 'sync'), {
    label: '同步画布',
    ariaLabel: '重新加载云端已合并的最新脑图画布',
  })
})

test('resume recovery detects newer revisions and same-revision incomplete trees', () => {
  assert.equal(getMindmapResumeRecoveryReason({
    cloudRevision: 9,
    localRevision: 8,
    cloudNodeCount: 93,
    localNodeCount: 93,
  }), 'newer-revision')
  assert.equal(getMindmapResumeRecoveryReason({
    cloudRevision: 9,
    localRevision: 9,
    cloudNodeCount: 93,
    localNodeCount: 1,
  }), 'incomplete-runtime')
  assert.equal(getMindmapResumeRecoveryReason({
    cloudRevision: 9,
    localRevision: 9,
    cloudNodeCount: 93,
    localNodeCount: 92,
    hasLocalChanges: true,
  }), null)
  assert.equal(getMindmapResumeRecoveryReason({
    cloudRevision: 8,
    localRevision: 9,
    cloudNodeCount: 93,
    localNodeCount: 1,
  }), null)
  assert.equal(getMindmapResumeRecoveryReason({
    cloudRevision: 9,
    localRevision: 9,
    cloudNodeCount: 93,
    localNodeCount: 93,
  }), null)
})

test('recovery gate blocks structure writes without swallowing final editor commits', () => {
  for (const commandName of [
    'INSERT_NODE',
    'INSERT_CHILD_NODE',
    'MOVE_NODE_TO',
    'REMOVE_NODE',
    'PASTE_NODE',
    'BACK',
    'ADD_GENERALIZATION',
    'ADD_ASSOCIATIVE_LINE',
    'REMOVE_ASSOCIATIVE_LINE',
    'SET_ASSOCIATIVE_LINE_CONTROL_POINTS',
    'ADD_OUTER_FRAME',
    'REMOVE_OUTER_FRAME',
    'SET_NODE_EXPAND',
    'EXPAND_ALL',
    'UNEXPAND_ALL',
    'UNEXPAND_TO_LEVEL',
  ]) {
    assert.equal(shouldBlockMindmapStructureWrite(commandName, true), true)
    assert.equal(shouldBlockMindmapStructureWrite(commandName, false), false)
  }

  // Enter/Tab first closes the active editor through SET_NODE_TEXT, then asks
  // the mind-map runtime to insert a sibling/child. Recovery must preserve the
  // former while rejecting the latter, otherwise the last typed text is lost.
  assert.equal(shouldBlockMindmapStructureWrite('SET_NODE_TEXT', true), false)
  assert.equal(shouldBlockMindmapStructureWrite('SET_NODE_DATA', true), false)
  assert.equal(shouldBlockMindmapStructureWrite('GO_TARGET_NODE', true), false)

  assert.equal(mindmapCommandStartsNodeTextEdit('INSERT_NODE'), true)
  assert.equal(mindmapCommandStartsNodeTextEdit('INSERT_CHILD_NODE', [true]), true)
  assert.equal(mindmapCommandStartsNodeTextEdit('INSERT_PARENT_NODE', [false]), false)
  assert.equal(mindmapCommandStartsNodeTextEdit('ADD_GENERALIZATION', [null]), true)
  assert.equal(mindmapCommandStartsNodeTextEdit('ADD_GENERALIZATION', [null, false]), false)
  assert.equal(mindmapCommandStartsNodeTextEdit('INSERT_MULTI_NODE'), false)
  assert.equal(mindmapCommandStartsNodeTextEdit('INSERT_NODE', [], {
    createNewNodeBehavior: 'activeOnly',
  }), false)
  assert.equal(mindmapCommandStartsNodeTextEdit('INSERT_NODE', [], {
    activeNodeCount: 0,
  }), false)
  assert.equal(mindmapCommandStartsNodeTextEdit('INSERT_NODE', [], {
    activeNodeCount: 2,
  }), false)
  assert.equal(mindmapCommandStartsNodeTextEdit(
    'INSERT_CHILD_NODE',
    [true, [{ uid: 'one-appointed-node' }]],
    { activeNodeCount: 2 },
  ), true)
})

test('关联线控制点更新通过恢复门闩且拒绝时从未修改模型重建连线', async () => {
  const [pluginSource, controlsSource] = await Promise.all([
    readFile(
      new URL('../../libs/simple-mind-map/src/plugins/AssociativeLine.js', import.meta.url),
      'utf8',
    ),
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/plugins/associativeLine/associativeLineControls.js',
        import.meta.url,
      ),
      'utf8',
    ),
  ])
  const mouseupBlock = controlsSource.match(
    /function onControlPointMouseup[\s\S]*?\n\}/,
  )?.[0] || ''

  assert.match(
    pluginSource,
    /command\.add\([\s\S]*?'SET_ASSOCIATIVE_LINE_CONTROL_POINTS'[\s\S]*?this\.setLineControlPoints/,
  )
  assert.match(
    pluginSource,
    /command\.remove\([\s\S]*?'SET_ASSOCIATIVE_LINE_CONTROL_POINTS'[\s\S]*?this\.setLineControlPoints/,
  )
  assert.match(controlsSource, /import \{ simpleDeepClone \} from '\.\.\/\.\.\/utils\/index'/)
  assert.match(
    mouseupBlock,
    /simpleDeepClone\([\s\S]*?getData\('associativeLinePoint'\)[\s\S]*?simpleDeepClone\([\s\S]*?getData\('associativeLineTargetControlOffsets'\)/,
  )
  assert.match(
    mouseupBlock,
    /execCommand\([\s\S]*?'SET_ASSOCIATIVE_LINE_CONTROL_POINTS'[\s\S]*?if \(updated === false\) \{[\s\S]*?isNotRenderAllLines = false[\s\S]*?renderAllLines\(\)/,
  )
  assert.doesNotMatch(
    mouseupBlock,
    /let \{ associativeLinePoint, associativeLineTargetControlOffsets \}[\s\S]*?node\.getData\(\)/,
  )
})

test('conflict recovery keeps the rejected runtime fenced until authoritative apply succeeds', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const gateBlock = source.match(
    /function setAuthoritativeRecoveryEditingBlocked[\s\S]*?\n\}/,
  )?.[0] || ''
  const rejectEditModeBlock = source.match(
    /function rejectEditModeDuringAuthoritativeRecovery[\s\S]*?\n\}/,
  )?.[0] || ''
  const recoveryBlock = source.match(
    /async function recoverFromSaveRevisionConflict[\s\S]*?\n\}/,
  )?.[0] || ''
  const reloadBlock = source.match(
    /async function reloadLatestServerDocument[\s\S]*?\n\}/,
  )?.[0] || ''
  const detailGuardBlock = source.match(
    /function isContentDetailTrackingSuspended[\s\S]*?\n\}/,
  )?.[0] || ''
  const changeGuardBlock = source.match(
    /function isChangeTrackingSuspended[\s\S]*?\n\}/,
  )?.[0] || ''

  assert.match(
    source,
    /const authoritativeRecoveryEditingBlocked = ref\(false\)[\s\S]*?const aiDialogReadonly = computed\([\s\S]*?authoritativeRecoveryEditingBlocked\.value/,
  )
  assert.match(detailGuardBlock, /authoritativeRecoveryEditingBlocked\.value/)
  assert.match(changeGuardBlock, /authoritativeRecoveryEditingBlocked\.value/)
  assert.match(
    source,
    /eventName === 'mode_change'[\s\S]*?rejectEditModeDuringAuthoritativeRecovery\(args\[0\], mm\)/,
  )

  // The final DOM-editor commit and generation check must happen before the
  // rejected mutation/Y.Doc are cleared. This protects input typed while the
  // draft write or an in-flight view save was being retired.
  const retireView = recoveryBlock.indexOf('retirePendingViewSaveForAuthoritativeReload()')
  const finalEditorCommit = recoveryBlock.indexOf(
    'commitActiveEditorsBeforeTermination()',
    retireView,
  )
  const finalEditorTick = recoveryBlock.indexOf('await nextTick()', finalEditorCommit)
  const finalGenerationCheck = recoveryBlock.indexOf(
    'draftProtection.getChangeVersion() !== protectedDraftChangeVersion',
    finalEditorTick,
  )
  const enterFence = recoveryBlock.indexOf(
    'setAuthoritativeRecoveryEditingBlocked(true)',
    finalGenerationCheck,
  )
  const stopOldYjs = recoveryBlock.indexOf('stopCurrentCollaborationSource()', enterFence)
  const clearRejectedIntents = recoveryBlock.indexOf('clearFileMetaIntentState()', stopOldYjs)
  assert.ok([
    retireView,
    finalEditorCommit,
    finalEditorTick,
    finalGenerationCheck,
    enterFence,
    stopOldYjs,
    clearRejectedIntents,
  ].every(index => index >= 0))
  assert.ok(retireView < finalEditorCommit)
  assert.ok(finalEditorCommit < finalEditorTick)
  assert.ok(finalEditorTick < finalGenerationCheck)
  assert.ok(finalGenerationCheck < enterFence)
  assert.ok(enterFence < stopOldYjs)
  assert.ok(stopOldYjs < clearRejectedIntents)

  // No reset/GET/render failure branch releases the fence. Release lives in
  // the authoritative reload success tail, after tree + metadata + revision
  // have become the new save baseline and before drafts/Yjs are rebuilt.
  assert.equal(
    (recoveryBlock.match(/setAuthoritativeRecoveryEditingBlocked\(false\)/g) || []).length,
    0,
  )
  assert.equal(
    (reloadBlock.match(/setAuthoritativeRecoveryEditingBlocked\(false\)/g) || []).length,
    1,
  )
  const applyDocument = reloadBlock.indexOf('applyAuthoritativeMindmapDocument(')
  const updateRevision = reloadBlock.indexOf('contentRevision = serverContentRevision')
  const markMetadataBaseline = reloadBlock.indexOf('markDocumentMetaSaved({')
  const leaveFence = reloadBlock.indexOf('setAuthoritativeRecoveryEditingBlocked(false)')
  const clearSessionDraft = reloadBlock.indexOf('clearLocalDraft()', leaveFence)
  const rebuildYjs = reloadBlock.indexOf('onYjsReinit(', clearSessionDraft)
  assert.ok([
    applyDocument,
    updateRevision,
    markMetadataBaseline,
    leaveFence,
    clearSessionDraft,
    rebuildYjs,
  ].every(index => index >= 0))
  assert.ok(applyDocument < updateRevision)
  assert.ok(updateRevision < markMetadataBaseline)
  assert.ok(markMetadataBaseline < leaveFence)
  assert.ok(leaveFence < clearSessionDraft)
  assert.ok(clearSessionDraft < rebuildYjs)

  // Exercise the user-visible sequence: failed authoritative GET keeps both
  // save and direct toolbar mode toggles closed; a later successful apply
  // reopens editing, unless the server itself is readonly.
  const blocked = { value: false }
  let serverReadonly = false
  const readonly = {
    get value() { return serverReadonly || blocked.value },
  }
  const storeModes = []
  const runtimeModes = []
  const actionsStub = { setIsReadonly: value => storeModes.push(value) }
  const mindMapStub = {
    value: { setMode: mode => runtimeModes.push(mode) },
  }
  const setBlocked = Function(
    'authoritativeRecoveryEditingBlocked',
    'isReadonly',
    'actions',
    'mindMap',
    `'use strict'; ${gateBlock}; return setAuthoritativeRecoveryEditingBlocked`,
  )(blocked, readonly, actionsStub, mindMapStub)
  const rejectEditMode = Function(
    'authoritativeRecoveryEditingBlocked',
    'actions',
    `'use strict'; ${rejectEditModeBlock}; return rejectEditModeDuringAuthoritativeRecovery`,
  )(blocked, actionsStub)

  assert.equal(setBlocked(true), true)
  assert.equal(readonly.value, true)
  // Failed GET/render: no release call occurs, and a toolbar attempt to switch
  // the old runtime back to edit is synchronously forced to readonly.
  await assert.rejects(Promise.reject(new Error('authoritative GET failed')))
  assert.equal(readonly.value, true)
  assert.equal(rejectEditMode('edit', mindMapStub.value), true)
  let saveCount = 0
  if (!readonly.value) saveCount += 1
  assert.equal(saveCount, 0)
  assert.equal(runtimeModes.at(-1), 'readonly')

  // Successful authoritative apply releases the temporary fence.
  assert.equal(setBlocked(false), true)
  assert.equal(readonly.value, false)
  assert.equal(runtimeModes.at(-1), 'edit')
  if (!readonly.value) saveCount += 1
  assert.equal(saveCount, 1)

  // Releasing a temporary fence never overrides a real server-side readonly.
  assert.equal(setBlocked(true), true)
  serverReadonly = true
  assert.equal(setBlocked(false), true)
  assert.equal(readonly.value, true)
  assert.equal(storeModes.at(-1), true)
  assert.equal(runtimeModes.at(-1), 'readonly')
})

test('clean document leaves without issuing a save', async () => {
  let saveCount = 0
  const result = await flushPendingMindmapChanges({
    hasUnsavedChanges: () => false,
    isSaveInProgress: () => false,
    requestSave: async () => { saveCount += 1 },
  })

  assert.equal(result, true)
  assert.equal(saveCount, 0)
})

test('changes made during the first request are flushed by a second pass', async () => {
  let dirty = true
  let saveCount = 0
  const result = await flushPendingMindmapChanges({
    hasUnsavedChanges: () => dirty,
    isSaveInProgress: () => false,
    requestSave: async () => {
      saveCount += 1
      if (saveCount === 2) dirty = false
      return true
    },
  })

  assert.equal(result, true)
  assert.equal(saveCount, 2)
})

test('an existing save is marked pending and awaited before leaving', async () => {
  let saving = true
  let dirty = true
  let pendingCount = 0
  let saveCount = 0
  const result = await flushPendingMindmapChanges({
    hasUnsavedChanges: () => dirty,
    isSaveInProgress: () => saving,
    requestSave: async () => { saveCount += 1; return true },
    markPendingSave: () => { pendingCount += 1 },
    waitFor: async () => {
      saving = false
      dirty = false
    },
  })

  assert.equal(result, true)
  assert.equal(pendingCount, 1)
  assert.equal(saveCount, 0)
})

test('failed and continuously dirty saves preserve a local backup', async () => {
  let backupCount = 0
  const failed = await flushPendingMindmapChanges({
    hasUnsavedChanges: () => true,
    isSaveInProgress: () => false,
    requestSave: async () => false,
    persistLocalBackup: () => { backupCount += 1 },
  })
  const continuouslyDirty = await flushPendingMindmapChanges({
    hasUnsavedChanges: () => true,
    isSaveInProgress: () => false,
    requestSave: async () => true,
    persistLocalBackup: () => { backupCount += 1 },
    maxSavePasses: 2,
  })

  assert.equal(failed, false)
  assert.equal(continuouslyDirty, false)
  assert.equal(backupCount, 2)
})

test('editor persists drafts on page hide and background freeze boundaries', async () => {
  const [source, pageSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8'),
  ])

  assert.match(source, /addEventListener\('pagehide', handlePageHide\)/)
  assert.match(source, /addEventListener\('visibilitychange', handleVisibilityChange\)/)
  assert.match(source, /addEventListener\('focus', handleWindowFocus\)/)
  assert.match(
    source,
    /function handlePageHide\(\) \{[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?persistLocalDraftBeforeUnload\(\)/,
  )
  assert.match(
    source,
    /function handleVisibilityChange[\s\S]*?visibilityState !== 'hidden'[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?if \(!hasUnsavedChanges\(\)\) return/,
  )
  assert.match(
    source,
    /function handleBeforeUnload[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?hasUnsavedChanges\(\)/,
  )
  assert.match(
    source,
    /onBeforeUnmount\(\(\) => \{[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?persistLocalDraftBeforeUnload\(\)/,
  )
  assert.match(
    source,
    /async function performCloudRevisionResumeCheck[\s\S]*?isSaving\.value[\s\S]*?countMindmapNodes[\s\S]*?getMindmapResumeRecoveryReason[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?draftProtection\.getChangeVersion\(\) !== requestedDraftChangeVersion[\s\S]*?clearTimeout\(autoSaveTimer\)[\s\S]*?reloadLatestServerDocument\(\{[\s\S]*?serverData: data/,
  )
  assert.match(
    source,
    /function reconcileCloudRevisionOnResume[\s\S]*?resumeRevisionCheckPromise[\s\S]*?RESUME_REVISION_CHECK_INTERVAL/,
  )
  assert.match(source, /draftProtection\.recordPersistResult\(draftChangeVersion, saved\)/)
  assert.match(source, /isLocalDraftProtected: \(\) => draftProtection\.isProtected\(\)/)
  assert.match(pageSource, /editRef\.value\?\.isLocalDraftProtected\?\.\(\) === true/)
  assert.doesNotMatch(pageSource, /\['pending', 'retrying', 'offline'\]\.includes\(saveStatus\.value\)/)
  assert.match(source, /removeEventListener\('pagehide', handlePageHide\)/)
  assert.match(source, /removeEventListener\('visibilitychange', handleVisibilityChange\)/)
  assert.match(source, /removeEventListener\('focus', handleWindowFocus\)/)
  assert.match(source, /flushPendingMindmapChanges\(\{/)
  assert.match(source, /async function prepareForCloudExit\(\)/)
  assert.match(source, /commitActiveEditorsBeforeTermination\(\)[\s\S]*?await flushBeforeLeave\(\)/)
  assert.match(source, /await draftWriteQueue[\s\S]*?removeMindmapDraft\(userStore\.id, props\.mindmapId, \{[\s\S]*?beforeUpdatedAt: clearBeforeUpdatedAt,[\s\S]*?sessionId: draftSessionId/)
  assert.match(source, /const restoredDraftToClear = restoredDraftRecord[\s\S]*?key: restoredDraftToClear\.key,[\s\S]*?beforeUpdatedAt: restoredDraftToClear\.updatedAt/)
  assert.match(pageSource, /editRef\.value\?\.prepareForCloudExit\?\.\(\)/)
  assert.match(source, /recoverFromSaveRevisionConflict\(/)
  const automaticConflictRecovery = source.match(
    /async function recoverFromSaveRevisionConflict[\s\S]*?\n\}/,
  )?.[0] || ''
  const resumeRecovery = source.match(
    /async function performCloudRevisionResumeCheck[\s\S]*?\n\}/,
  )?.[0] || ''
  const remoteResetRecovery = source.match(
    /async function handleRemoteDocumentReset[\s\S]*?\n\}/,
  )?.[0] || ''
  assert.match(
    automaticConflictRecovery,
    /requiresCollaborationReset[\s\S]*?contentRevision = Math\.max\(contentRevision, currentRevision\)[\s\S]*?if \(requiresCollaborationReset\) \{[\s\S]*?resetCurrentCollaborationToCloud\(contentRevision\)[\s\S]*?reloadLatestServerDocument/,
  )
  assert.match(
    automaticConflictRecovery,
    /const requiresCollaborationReset = conflictData\?\.requiresCollaborationReset === true/,
  )
  assert.doesNotMatch(
    automaticConflictRecovery,
    /requiresCollaborationReset === undefined|rejectedMutationHadRealtimeFrames/,
  )
  assert.match(
    automaticConflictRecovery,
    /stopCurrentCollaborationSource\(\)[\s\S]*?activeSaveMutation = null/,
  )
  assert.match(
    automaticConflictRecovery,
    /resetResponse\?\.data\?\.contentRevision[\s\S]*?contentRevision = Math\.max\(contentRevision, resetRevision\)/,
  )
  assert.match(
    automaticConflictRecovery,
    /expectedDraftChangeVersion: recoveryDraftChangeVersion[\s\S]*?expectedViewChangeVersion: recoveryViewChangeVersion/,
  )
  assert.match(
    automaticConflictRecovery,
    /preserveAutomaticConflictDraft\([\s\S]*?draftResult\?\.saved !== true[\s\S]*?return false/,
  )
  assert.match(
    automaticConflictRecovery,
    /commitActiveEditorsBeforeTermination\(\)[\s\S]*?await nextTick\(\)[\s\S]*?localFullData = getCurrentDocument\(\)[\s\S]*?preserveAutomaticConflictDraft/,
  )
  assert.match(
    automaticConflictRecovery,
    /draftProtection\.getChangeVersion\(\) !== protectedDraftChangeVersion[\s\S]*?setPendingAutomaticConflictRecovery\(createDeferredRecoveryState\([\s\S]*?return false/,
  )
  assert.match(
    automaticConflictRecovery,
    /await retirePendingViewSaveForAuthoritativeReload\(\)/,
  )
  assert.doesNotMatch(automaticConflictRecovery, /viewSaveInProgress\s*=\s*false/)
  assert.doesNotMatch(automaticConflictRecovery, /viewSavePromise\s*=\s*null/)
  assert.doesNotMatch(automaticConflictRecovery, /downloadConflictBackup/)
  assert.match(
    resumeRecovery,
    /const requestedDraftChangeVersion = draftProtection\.getChangeVersion\(\)[\s\S]*?await getMindmap[\s\S]*?draftProtection\.getChangeVersion\(\) !== requestedDraftChangeVersion/,
  )
  assert.match(
    resumeRecovery,
    /commitActiveEditorsBeforeTermination\(\)[\s\S]*?await nextTick\(\)[\s\S]*?hasUnsavedChanges\(\)[\s\S]*?return false[\s\S]*?clearTimeout\(autoSaveTimer\)/,
  )
  assert.doesNotMatch(resumeRecovery, /preserveAutomaticConflictDraft/)
  assert.doesNotMatch(resumeRecovery, /downloadConflictBackup/)
  assert.match(remoteResetRecovery, /preserveAutomaticConflictDraft/)
  assert.match(
    remoteResetRecovery,
    /commitActiveEditorsBeforeTermination\(\)[\s\S]*?await nextTick\(\)[\s\S]*?preserveAutomaticConflictDraft/,
  )
  assert.match(remoteResetRecovery, /minimumContentRevision: Number\(data\?\.contentRevision\)/)
  assert.doesNotMatch(remoteResetRecovery, /downloadConflictBackup/)
  const reloadLatestDocument = source.match(
    /async function reloadLatestServerDocument[\s\S]*?\n\}/,
  )?.[0] || ''
  assert.match(
    reloadLatestDocument,
    /const serverContentRevision = Number\(data\?\.contentRevision\)[\s\S]*?serverContentRevision < contentRevision[\s\S]*?markAuthoritativeReloadRequired\(\)[\s\S]*?return false/,
  )
  assert.match(reloadLatestDocument, /contentRevision = serverContentRevision/)
  assert.match(
    reloadLatestDocument,
    /const guardedDocumentDataGeneration = documentDataGeneration[\s\S]*?documentDataGeneration !== guardedDocumentDataGeneration/,
  )
  assert.match(
    reloadLatestDocument,
    /await ensureMindmapDocumentPlugins\(serverDocument, activeMindMap\)[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?await nextTick\(\)[\s\S]*?hasLocalChangesSinceRequest\(\)[\s\S]*?markAuthoritativeReloadRequired\(\)[\s\S]*?return false/,
  )
  assert.match(
    source,
    /function createAutomaticConflictDraftOptions[\s\S]*?normalizedEventKey[\s\S]*?sessionId: `\$\{draftSessionId\}-conflict-r\$\{revisionKey\}\$\{/,
  )
  assert.match(
    automaticConflictRecovery,
    /if \(!collaborationResetCompleted\)[\s\S]*?setPendingAutomaticConflictRecovery\(createDeferredRecoveryState\([\s\S]*?protectedDraftChangeVersion/,
  )
  assert.match(
    automaticConflictRecovery,
    /createDeferredRecoveryState[\s\S]*?rejectedMutationSnapshot/,
  )
  assert.match(
    source,
    /async function recoverSave\(\)[\s\S]*?pendingAutomaticConflictRecovery[\s\S]*?recoverFromSaveRevisionConflict\([\s\S]*?getCurrentDocument\(\),[\s\S]*?recovery/,
  )
  assert.match(source, /function persistLocalDraft\(\{ notifyFailure = true \} = \{\}\)/)
  assert.match(
    source,
    /function hasUnsavedChanges\(\)[\s\S]*?Boolean\(pendingClientMutationId\)/,
  )
  assert.match(
    source,
    /else if \(hasPendingRealtimeMutation\)[\s\S]*?confirmLocalMutation\?\.\(clientMutationId\)/,
  )
  assert.match(source, /result\?\.saved === true/)
  assert.match(source, /saveRecoveryKind\.value = 'draft'/)
  assert.match(source, /title: '本地草稿保存失败'/)
  assert.match(source, /const announceProtectedDraft =/)
  assert.match(source, /async function recoverSave\(\)/)
  assert.match(source, /mindmap-local-storage-failed/)
  assert.match(source, /recoverSave,/)
  assert.match(pageSource, /class="save-recovery-btn"/)
  assert.match(pageSource, /handleSaveRecovery/)
  assert.match(pageSource, /pending: '待保存'/)

  const cloudExitBlock = source.match(
    /async function prepareForCloudExit[\s\S]*?function onExecCommand/,
  )?.[0] || ''
  const firstCommit = cloudExitBlock.indexOf('commitActiveEditorsBeforeTermination()')
  const flush = cloudExitBlock.indexOf('await flushBeforeLeave()', firstCommit)
  const draftQueueWait = cloudExitBlock.indexOf('await draftWriteQueue', flush)
  const secondCommit = cloudExitBlock.indexOf(
    'commitActiveEditorsBeforeTermination()',
    draftQueueWait,
  )
  const checkBeforeDraftRemoval = cloudExitBlock.indexOf(
    'if (hasUnsavedChanges()',
    secondCommit,
  )
  const draftRemoval = cloudExitBlock.indexOf('await removeMindmapDraft', checkBeforeDraftRemoval)
  const thirdCommit = cloudExitBlock.indexOf(
    'commitActiveEditorsBeforeTermination()',
    draftRemoval,
  )
  const finalGenerationCheck = cloudExitBlock.indexOf(
    'if (hasUnsavedChanges()',
    thirdCommit,
  )
  const markClean = cloudExitBlock.indexOf('draftProtection.markClean()', finalGenerationCheck)
  assert.ok([
    firstCommit,
    flush,
    draftQueueWait,
    secondCommit,
    checkBeforeDraftRemoval,
    draftRemoval,
    thirdCommit,
    finalGenerationCheck,
    markClean,
  ].every(index => index >= 0))
  assert.ok(firstCommit < flush)
  assert.ok(flush < draftQueueWait)
  assert.ok(draftQueueWait < secondCommit)
  assert.ok(secondCommit < checkBeforeDraftRemoval)
  assert.ok(checkBeforeDraftRemoval < draftRemoval)
  assert.ok(draftRemoval < thirdCommit)
  assert.ok(thirdCommit < finalGenerationCheck)
  assert.ok(finalGenerationCheck < markClean)
})

test('remote deletion protects every active DOM editor without rebroadcasting deleted entities', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const protectionBlock = source.match(
    /function protectActiveTextEditorBeforeRemoteDocumentApply[\s\S]*?\n\}/,
  )?.[0] || ''
  const targetCollectionBlock = source.match(
    /function collectActiveEditorProtectionTargets[\s\S]*?\n\}/,
  )?.[0] || ''
  const runtimeUidBlock = source.match(
    /function getRuntimeMindmapNodeUid[\s\S]*?\n\}/,
  )?.[0] || ''
  const createSyncBlock = source.match(
    /function createYjsSyncInstance[\s\S]*?\n\}/,
  )?.[0] || ''
  const detailGuardBlock = source.match(
    /function isContentDetailTrackingSuspended[\s\S]*?\n\}/,
  )?.[0] || ''
  const changeGuardBlock = source.match(
    /function isChangeTrackingSuspended[\s\S]*?\n\}/,
  )?.[0] || ''
  const identityBlock = source.match(
    /^function createRemoteDeletedEditorProtectionIdentity[\s\S]*?^\}/m,
  )?.[0] || ''
  const notifierBlock = source.match(
    /^function createRemoteDeletedEditorProtectionNotifier[\s\S]*?^\}/m,
  )?.[0] || ''

  assert.match(targetCollectionBlock, /getCurrentEditNode\?\.\(\)/)
  assert.match(targetCollectionBlock, /outlineEditRef\.value\?\.getActiveTextEditor\?\.\(\)/)
  assert.match(targetCollectionBlock, /kind: 'outline-node'/)
  assert.match(targetCollectionBlock, /mindmapTreeContainsNodeUid\(remoteRoot, editingNodeUid\)/)
  assert.match(targetCollectionBlock, /mindmapTreeNodeIsRuntimeVisible\(/)
  assert.match(targetCollectionBlock, /mindmapTreeNodesHaveSameEditableData\(/)
  assert.match(targetCollectionBlock, /associativeLine\?\.showTextEdit === true/)
  assert.match(targetCollectionBlock, /mindmapTreeContainsAssociativeLine\(/)
  assert.match(targetCollectionBlock, /outerFrame\?\.showTextEdit === true/)
  assert.match(targetCollectionBlock, /getRangeNodeList\?\.\(/)
  assert.match(targetCollectionBlock, /mindmapTreeContainsExactOuterFrame\(/)
  assert.match(targetCollectionBlock, /mindmapTreesHaveSameCrossNodeState\(currentRoot, remoteRoot\)/)
  const globalHistoryFlush = protectionBlock.indexOf('flushPendingHistory?.()')
  const activeEditorCollection = protectionBlock.indexOf(
    'collectActiveEditorProtectionTargets(',
  )
  assert.ok(globalHistoryFlush >= 0)
  assert.ok(activeEditorCollection >= 0)
  assert.ok(globalHistoryFlush < activeEditorCollection)
  assert.match(
    protectionBlock,
    /queuedHistoryCommitted[\s\S]*?draftProtection\.getChangeVersion\(\) !== queuedChangeVersion[\s\S]*?return 'local-edit-committed'/,
  )
  assert.doesNotMatch(protectionBlock, /active-editor-deferred/)
  assert.match(
    protectionBlock,
    /impactedTargets[\s\S]*?hideProtectedActiveEditors\(impactedTargets\)[\s\S]*?flushPendingHistory\?\.\(\)[\s\S]*?draftProtection\.getChangeVersion\(\)/,
  )
  assert.match(
    protectionBlock,
    /removedImpactedTargets\.length === 0[\s\S]*?protectingActiveEditorFromRemoteDelete = true[\s\S]*?hideProtectedActiveEditors\(impactedTargets\)[\s\S]*?getCurrentDocument\(\)[\s\S]*?saveMindmapDraftFallbackSync[\s\S]*?saveMindmapDraft/,
  )
  assert.match(
    protectionBlock,
    /enqueueRequiredDraftOperation\([\s\S]*?\(\) => saveMindmapDraft\(options\)/,
  )
  assert.doesNotMatch(protectionBlock, /if \(fallbackSaved\) notify/)
  assert.match(
    protectionBlock,
    /void durableSave\.then[\s\S]*?notifyRemoteDeletedEditorProtectionResult\([\s\S]*?result\?\.saved === true \|\| fallbackSaved/,
  )
  assert.match(source, /document: cloneRequestPayload\(document\)/)
  assert.match(createSyncBlock, /beforeRemoteDocumentApply: protectActiveTextEditorBeforeRemoteDocumentApply/)
  assert.match(detailGuardBlock, /protectingActiveEditorFromRemoteDelete/)
  assert.match(changeGuardBlock, /protectingActiveEditorFromRemoteDelete/)

  const collectProtectionTargets = Function(
    'outlineEditRef',
    'mindmapTreeContainsNodeUid',
    'mindmapTreeNodeIsRuntimeVisible',
    'mindmapTreeContainsAssociativeLine',
    'mindmapTreeContainsExactOuterFrame',
    'mindmapTreeNodesHaveSameEditableData',
    'mindmapTreesHaveSameCrossNodeState',
    `'use strict'; ${runtimeUidBlock}; ${targetCollectionBlock}; return collectActiveEditorProtectionTargets`,
  )(
    { value: null },
    mindmapTreeContainsNodeUid,
    mindmapTreeNodeIsRuntimeVisible,
    mindmapTreeContainsAssociativeLine,
    mindmapTreeContainsExactOuterFrame,
    mindmapTreeNodesHaveSameEditableData,
    mindmapTreesHaveSameCrossNodeState,
  )
  const runtimeNode = (uid, data = {}) => ({
    uid,
    getData(key) {
      const value = { uid, ...data }
      return key ? value[key] : value
    },
  })
  const sourceNode = runtimeNode('source')
  const targetNode = runtimeNode('target')
  const firstFrameNode = runtimeNode('frame-a', { outerFrame: { groupId: 'frame-1' } })
  const secondFrameNode = runtimeNode('frame-b', { outerFrame: { groupId: 'frame-1' } })
  const remoteRoot = {
    data: { uid: 'root' },
    children: [
      {
        data: { uid: 'source', associativeLineTargets: ['target'] },
        children: [],
      },
      { data: { uid: 'target' }, children: [] },
      { data: { uid: 'frame-a', outerFrame: { groupId: 'frame-1' } }, children: [] },
      { data: { uid: 'frame-b', outerFrame: { groupId: 'frame-1' } }, children: [] },
    ],
  }
  const currentRoot = structuredClone(remoteRoot)
  const editorMindMap = {
    getData: () => structuredClone(currentRoot),
    updateData() {},
    renderer: { textEdit: { getCurrentEditNode: () => sourceNode } },
    associativeLine: {
      showTextEdit: true,
      activeLine: [null, null, null, sourceNode, targetNode],
    },
    outerFrame: {
      showTextEdit: true,
      activeOuterFrame: { node: {}, range: [0, 1] },
      getRangeNodeList: () => [firstFrameNode, secondFrameNode],
    },
  }
  const retainedTargets = collectProtectionTargets(remoteRoot, editorMindMap)
  assert.deepEqual(
    retainedTargets.map(target => [
      target.kind,
      target.retained,
      target.requiresCommit === true,
    ]),
    [
      ['node', true, false],
      ['associative-line', true, false],
      ['outer-frame', true, false],
    ],
  )
  remoteRoot.children[1].data.text = '远端只修改其他节点'
  const unrelatedTargets = collectProtectionTargets(remoteRoot, editorMindMap)
  assert.deepEqual(
    unrelatedTargets.map(target => [
      target.kind,
      target.retained,
      target.requiresCommit === true,
    ]),
    [
      ['node', true, false],
      ['associative-line', true, false],
      ['outer-frame', true, false],
    ],
    '无关节点更新不得关闭当前浮层编辑器',
  )
  const collapsedRemoteRoot = structuredClone(remoteRoot)
  collapsedRemoteRoot.data.expand = false
  const collapsedNodeTarget = collectProtectionTargets(
    collapsedRemoteRoot,
    editorMindMap,
  ).find(target => target.kind === 'node')
  assert.equal(collapsedNodeTarget.retained, true)
  assert.equal(
    collapsedNodeTarget.requiresCommit,
    true,
    '远端折叠祖先会销毁编辑节点实例，应用前必须提交并关闭编辑器',
  )
  const protectRemoteApply = Function(
    'mindMap',
    'terminalState',
    'isReadonly',
    'protectingActiveEditorFromRemoteDelete',
    'draftProtection',
    'collectActiveEditorProtectionTargets',
    'mindmapDocumentRequiresFullRuntimeReplacement',
    `'use strict'; ${protectionBlock}; return protectActiveTextEditorBeforeRemoteDocumentApply`,
  )(
    { value: editorMindMap },
    false,
    { value: false },
    false,
    { getChangeVersion: () => 0 },
    collectProtectionTargets,
    mindmapDocumentRequiresFullRuntimeReplacement,
  )
  assert.equal(
    protectRemoteApply(remoteRoot, editorMindMap, { root: remoteRoot }),
    false,
    '编辑节点未受影响时必须立即应用其他节点的远端更新',
  )
  const fullReplacementTargets = collectProtectionTargets(
    remoteRoot,
    editorMindMap,
    true,
  )
  assert.deepEqual(
    fullReplacementTargets.map(target => [
      target.kind,
      target.retained,
      target.requiresCommit === true,
    ]),
    [
      ['node', true, true],
      ['associative-line', true, true],
      ['outer-frame', true, true],
    ],
    '布局或主题替换运行时节点前仍必须提交所有活动浮层',
  )
  remoteRoot.children[1].data.text = currentRoot.children[1].data.text
  remoteRoot.children[0].data.associativeLineTargets = []
  remoteRoot.children[3].data.outerFrame = null
  const deletedTargets = collectProtectionTargets(remoteRoot, editorMindMap)
  assert.deepEqual(
    deletedTargets.map(target => [target.kind, target.retained]),
    [['node', true], ['associative-line', false], ['outer-frame', false]],
  )

  const outlineEditor = { nodeUid: 'source', hideEditTextBox() {} }
  const collectOutlineProtectionTargets = Function(
    'outlineEditRef',
    'mindmapTreeContainsNodeUid',
    'mindmapTreeNodeIsRuntimeVisible',
    'mindmapTreeContainsAssociativeLine',
    'mindmapTreeContainsExactOuterFrame',
    'mindmapTreeNodesHaveSameEditableData',
    'mindmapTreesHaveSameCrossNodeState',
    `'use strict'; ${runtimeUidBlock}; ${targetCollectionBlock}; return collectActiveEditorProtectionTargets`,
  )(
    { value: { getActiveTextEditor: () => outlineEditor } },
    mindmapTreeContainsNodeUid,
    mindmapTreeNodeIsRuntimeVisible,
    mindmapTreeContainsAssociativeLine,
    mindmapTreeContainsExactOuterFrame,
    mindmapTreeNodesHaveSameEditableData,
    mindmapTreesHaveSameCrossNodeState,
  )
  const collapsedOutlineRoot = structuredClone(currentRoot)
  collapsedOutlineRoot.data.expand = false
  const collapsedOutlineTarget = collectOutlineProtectionTargets(
    collapsedOutlineRoot,
    editorMindMap,
  ).find(target => target.kind === 'outline-node')
  assert.equal(collapsedOutlineTarget.retained, true)
  assert.equal(collapsedOutlineTarget.requiresCommit, true)

  const remoteWithoutOutlineNode = structuredClone(remoteRoot)
  remoteWithoutOutlineNode.children = remoteWithoutOutlineNode.children.filter(
    node => node.data.uid !== 'source',
  )
  const outlineTarget = collectOutlineProtectionTargets(
    remoteWithoutOutlineNode,
    editorMindMap,
  ).find(target => target.kind === 'outline-node')
  assert.equal(outlineTarget.identity, 'node:source')
  assert.equal(outlineTarget.retained, false)
  assert.equal(outlineTarget.editor, outlineEditor)

  let eventSequence = 0
  const createIdentity = Function(
    'createMutationId',
    `'use strict'; ${identityBlock}; return createRemoteDeletedEditorProtectionIdentity`,
  )(() => `event-${eventSequence += 1}`)
  const firstIdentity = createIdentity('same-node', 17)
  const secondIdentity = createIdentity('same-node', 17)
  assert.notEqual(firstIdentity.eventKey, secondIdentity.eventKey)
  assert.notEqual(firstIdentity.notificationKey, secondIdentity.notificationKey)
  assert.match(firstIdentity.eventKey, /same-node/)

  const createNotifier = Function(
    `'use strict'; ${notifierBlock}; return createRemoteDeletedEditorProtectionNotifier`,
  )()
  const warnings = []
  const errors = []
  const notify = createNotifier({
    warning: payload => warnings.push(payload),
    error: payload => errors.push(payload),
  })
  // 两次相同 node/revision 的删除即使 IndexedDB 与 localStorage 都失败，
  // 也必须按独立事件各报一次失败；同一事件的迟到重复回调仍保持幂等。
  assert.equal(notify(firstIdentity.notificationKey, false), true)
  assert.equal(notify(secondIdentity.notificationKey, false), true)
  assert.equal(notify(firstIdentity.notificationKey, false), false)
  assert.equal(warnings.length, 0)
  assert.equal(errors.length, 2)
})

test('remote document resets remain queued until authoritative reload succeeds and can be retried', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const drainBlock = source.match(
    /function drainPendingRemoteDocumentReset[\s\S]*?\n\}/,
  )?.[0] || ''
  const resetBlock = source.match(
    /async function handleRemoteDocumentReset[\s\S]*?\n\}/,
  )?.[0] || ''
  const recoverBlock = source.match(/async function recoverSave[\s\S]*?\n\}/)?.[0] || ''

  assert.match(drainBlock, /remoteDocumentResetRetryBlocked/)
  assert.match(drainBlock, /versionChangeTrackingPaused/)
  assert.doesNotMatch(drainBlock, /pendingRemoteDocumentReset = null/)
  assert.match(resetBlock, /blockRemoteDocumentResetRetry\(actionTitle, '未能创建本地安全副本'\)/)
  assert.match(resetBlock, /blockRemoteDocumentResetRetry\(actionTitle, '尚未能加载服务器最新内容'\)/)
  assert.match(resetBlock, /acknowledgeRemoteDocumentReset\(data\)/)
  assert.match(resetBlock, /await retirePendingViewSaveForAuthoritativeReload\(\)/)
  const commitIndex = resetBlock.indexOf('commitActiveEditorsBeforeTermination()')
  const blockEditingIndex = resetBlock.indexOf('setAuthoritativeRecoveryEditingBlocked(true)')
  const firstAwaitIndex = resetBlock.indexOf('await nextTick()')
  assert.ok(commitIndex > 0)
  assert.ok(blockEditingIndex > commitIndex)
  assert.ok(firstAwaitIndex > blockEditingIndex)
  assert.match(
    source,
    /function canPersistProtectedDraft\(\)[\s\S]*?!props\.readonly[\s\S]*?serverCanEdit\.value === true[\s\S]*?!terminalState/,
  )
  assert.match(
    source,
    /async function preserveAutomaticConflictDraft[\s\S]*?!canPersistProtectedDraft\(\)/,
  )
  assert.doesNotMatch(
    source.match(/async function preserveAutomaticConflictDraft[\s\S]*?\n\}/)?.[0] || '',
    /canUseLocalDraft\(\)/,
  )
  const retireBlock = source.match(
    /async function retirePendingViewSaveForAuthoritativeReload[\s\S]*?\n\}/,
  )?.[0] || ''
  assert.match(retireBlock, /viewSaveGeneration \+= 1/)
  assert.match(retireBlock, /viewSaveRequested = false/)
  assert.match(retireBlock, /const retiredRequest = viewSavePromise/)
  assert.match(retireBlock, /if \(retiredRequest\) await retiredRequest/)
  assert.match(retireBlock, /savedViewChangeVersion = viewChangeVersion/)
  assert.doesNotMatch(
    drainBlock,
    /!allowUnsaved[\s\S]*?viewSaveRequested|!allowUnsaved[\s\S]*?viewSaveInProgress/,
  )
  assert.match(
    recoverBlock,
    /pendingRemoteDocumentReset[\s\S]*?remoteDocumentResetRetryBlocked = false[\s\S]*?handleRemoteDocumentReset\(resetData\)/,
  )
  assert.match(
    source,
    /function acknowledgeRemoteDocumentReset[\s\S]*?setPendingRemoteDocumentReset\(null\)/,
  )
  assert.match(
    source,
    /function onVersionChangeTracking[\s\S]*?authoritativeResetPending[\s\S]*?drainPendingRemoteDocumentReset\(\{[\s\S]*?allowUnsaved: true/,
  )
  assert.match(source, /:authoritative-reset-generation="authoritativeResetGeneration"/)
})

test('readonly observers recheck cloud revisions and rebuild Yjs after authoritative reloads', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const resumeBlock = source.match(
    /async function performCloudRevisionResumeCheck[\s\S]*?\n\}/,
  )?.[0] || ''
  const reinitBlock = source.match(/function onYjsReinit[\s\S]*?\n\}/)?.[0] || ''

  assert.doesNotMatch(resumeBlock, /isReadonly\.value/)
  assert.doesNotMatch(reinitBlock, /isReadonly\.value/)
  const staleBlock = source.match(
    /async function handleStaleCollaborationState[\s\S]*?\n\}/,
  )?.[0] || ''
  const remoteResetBlock = source.match(
    /async function handleRemoteDocumentReset[\s\S]*?\n\}/,
  )?.[0] || ''
  assert.doesNotMatch(staleBlock, /isReadonly\.value/)
  assert.doesNotMatch(remoteResetBlock, /if \([^\n]*isReadonly\.value/)
  assert.match(
    reinitBlock,
    /yjsSync\.destroy\(\{ flushCheckpoint: false \}\)[\s\S]*?startYjsSyncIfReady\(\)/,
  )
  assert.match(source, /function queueRemoteDocumentReset[\s\S]*?nextRevision >= queuedRevision/)
  assert.match(source, /function requestRemoteDocumentReset[\s\S]*?allowUnsaved: true/)
  assert.match(remoteResetBlock, /expectedDraftChangeVersion: recoveryDraftChangeVersion/)
  assert.match(remoteResetBlock, /expectedViewChangeVersion: recoveryViewChangeVersion/)
  assert.match(
    source,
    /onContentRevision: \(revision, data\)[\s\S]*?!hasRealWritePermission\(\) && revisionAdvanced[\s\S]*?markAuthoritativeReloadRequired\(\)[\s\S]*?scheduleAuthoritativeReload\(\)/,
  )
  assert.doesNotMatch(
    source.match(/onContentRevision: \(revision, data\)[\s\S]*?\n\s*\},\n\s*onStaleState/)?.[0] || '',
    /isReadonly\.value/,
  )
})

test('WebSocket 认证降级为只读会终止编辑会话并关闭当前协作实例', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )

  assert.match(
    source,
    /onReadonlyChanged: \(readonly\) => \{[\s\S]*?terminateEditingSession\('access-revoked'/,
  )
  const readonlyChangedBlock = source.match(
    /onReadonlyChanged: \(readonly\) => \{[\s\S]*?\n\s*\},\n\s*onContentRevision/,
  )?.[0] || ''
  assert.match(readonlyChangedBlock, /!hasRealWritePermission\(\)/)
  assert.doesNotMatch(readonlyChangedBlock, /isReadonly\.value/)
  assert.match(
    source,
    /const terminatedSync = yjsSync[\s\S]*?terminatedSync\?\.destroy\?\.\(\{ flushCheckpoint: false \}\)/,
  )
})

test('authoritative apply failures immediately fence the partial runtime and preserve the pre-apply document', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const helperBlock = source.match(
    /async function enterAuthoritativeApplyFailureRecovery[\s\S]*?\n\}/,
  )?.[0] || ''
  const reloadBlock = source.match(
    /async function reloadLatestServerDocument[\s\S]*?\n\}/,
  )?.[0] || ''
  const saveBlock = source.match(
    /async function saveToBackend[\s\S]*?function queueRemoteDocumentReset/,
  )?.[0] || ''

  const fenceIndex = helperBlock.indexOf('setAuthoritativeRecoveryEditingBlocked(true)')
  const markReloadIndex = helperBlock.indexOf('markAuthoritativeReloadRequired()')
  const draftIndex = helperBlock.indexOf('await preserveAutomaticConflictDraft(')
  assert.ok(fenceIndex >= 0)
  assert.ok(markReloadIndex > fenceIndex)
  assert.ok(draftIndex > markReloadIndex)

  assert.match(
    reloadBlock,
    /const protectedDocumentBeforeApply = getCurrentDocument\(\)/,
  )
  assert.match(
    reloadBlock,
    /catch \(error\) \{[\s\S]*?await enterAuthoritativeApplyFailureRecovery\([\s\S]*?protectedDocumentBeforeApply[\s\S]*?throw error/,
  )
  assert.match(saveBlock, /const protectedDocumentBeforeMergeApply = getCurrentDocument\(\)/)
  assert.match(
    saveBlock,
    /catch \(renderError\) \{[\s\S]*?await enterAuthoritativeApplyFailureRecovery\([\s\S]*?protectedDocumentBeforeMergeApply[\s\S]*?activeSaveMutation = null/,
  )
})

test('remote Yjs apply failures stop the failed lineage and recover from the pre-apply document', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const createSyncBlock = source.match(
    /function createYjsSyncInstance[\s\S]*?function startYjsSyncIfReady/,
  )?.[0] || ''
  const captureBlock = source.match(
    /function captureProtectedDocumentWithActiveEditorInput[\s\S]*?^\}/m,
  )?.[0] || ''
  const recoveryBlock = source.match(
    /function handleRemoteDocumentApplyFailure[\s\S]*?^\}/m,
  )?.[0] || ''
  const applyFailureBlock = source.match(
    /async function enterAuthoritativeApplyFailureRecovery[\s\S]*?^\}/m,
  )?.[0] || ''

  assert.match(
    createSyncBlock,
    /captureDocumentBeforeRemoteApply: captureProtectedDocumentWithActiveEditorInput/,
  )
  assert.match(
    createSyncBlock,
    /onDocumentApplyError:[\s\S]*?handleRemoteDocumentApplyFailure/,
  )
  const protectIndex = recoveryBlock.indexOf('enterAuthoritativeApplyFailureRecovery(')
  const stopIndex = recoveryBlock.indexOf('stopCurrentCollaborationSource()', protectIndex)
  const retireViewIndex = recoveryBlock.indexOf(
    'retirePendingViewSaveForAuthoritativeReload()',
    stopIndex,
  )
  const abandonIndex = recoveryBlock.indexOf(
    'abandonPendingContentForAuthoritativeReload()',
    retireViewIndex,
  )
  const reloadIndex = recoveryBlock.indexOf('scheduleAuthoritativeReload()', abandonIndex)
  assert.ok(protectIndex >= 0)
  assert.ok(stopIndex > protectIndex)
  assert.ok(retireViewIndex > stopIndex)
  assert.ok(abandonIndex > retireViewIndex)
  assert.ok(reloadIndex > abandonIndex)
  assert.match(captureBlock, /cloneRequestPayload\(getCurrentDocument\(\)\)/)
  assert.match(captureBlock, /richTextEditor\.getEditText\(\)/)
  assert.match(captureBlock, /outlineEditor\?\.getEditText/)
  assert.match(captureBlock, /applyMindmapActiveEditorTextSnapshots/)
  assert.match(captureBlock, /associativeLine\.getEditText\?\.\(\)/)
  assert.match(captureBlock, /outerFrame\.getEditText\?\.\(\)/)
  assert.match(captureBlock, /applyMindmapActiveCrossNodeEditorSnapshots/)
  assert.match(applyFailureBlock, /\{ syncFallback: true \}/)
})

test('temporary edit transitions still warn on unload and invalidate older authoritative reloads', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const unloadBlock = source.match(/function handleBeforeUnload[\s\S]*?^\}/m)?.[0] || ''
  const versionGateBlock = source.match(
    /function setVersionTransitionEditingBlocked[\s\S]*?^\}/m,
  )?.[0] || ''
  const importGateBlock = source.match(
    /function setImportTransitionEditingBlocked[\s\S]*?^\}/m,
  )?.[0] || ''
  const reloadBlock = source.match(
    /async function reloadLatestServerDocument[\s\S]*?function downloadConflictBackup/,
  )?.[0] || ''
  const resumeBlock = source.match(
    /function resumeAfterEditingTransition[\s\S]*?^\}/m,
  )?.[0] || ''

  assert.match(unloadBlock, /hasRealWritePermission\(\)/)
  assert.match(unloadBlock, /hasUnsavedChanges\(\) \|\| viewSaveRequested \|\| viewSaveInProgress/)
  assert.doesNotMatch(unloadBlock, /isReadonly\.value/)
  assert.match(versionGateBlock, /if \(nextBlocked\) editingTransitionGeneration \+= 1/)
  assert.match(importGateBlock, /if \(nextBlocked\) editingTransitionGeneration \+= 1/)
  assert.match(reloadBlock, /const transitionGenerationAtRequest = editingTransitionGeneration/)
  assert.match(
    reloadBlock,
    /editingTransitionGeneration !== transitionGenerationAtRequest[\s\S]*?markAuthoritativeReloadRequired\(\)/,
  )
  assert.match(resumeBlock, /authoritativeReloadRequired/)
  assert.match(resumeBlock, /scheduleAuthoritativeReload\(\)/)
  assert.match(resumeBlock, /hasUnsavedChanges\(\)[\s\S]*?saveToBackend\(\)/)
  assert.match(
    source,
    /performAuthoritativeReload\(\{[\s\S]*?allowDuringEditingTransition: true/,
  )
})

test('node leases span final editor publish and saves close editors before retiring a collaboration source', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const createSyncBlock = source.match(
    /function createYjsSyncInstance[\s\S]*?function startYjsSyncIfReady/,
  )?.[0] || ''
  const recoveryWriteGateBlock = source.match(
    /function isRecoveryStructureWriteBlocked[\s\S]*?\n\}/,
  )?.[0] || ''
  const structureWriteGateBlock = source.match(
    /function isMindmapStructureWriteBlocked[\s\S]*?\n\}/,
  )?.[0] || ''
  const commandGuardBlock = source.match(
    /function installRecoveryStructureCommandGuard[\s\S]*?\n\}/,
  )?.[0] || ''
  const saveBlock = source.match(
    /async function saveToBackend[\s\S]*?function queueRemoteDocumentReset/,
  )?.[0] || ''
  const leaseGate = saveBlock.indexOf('yjsSync?.hasActiveNodeEditLease?.()')
  const pendingLeaseGate = saveBlock.indexOf(
    'yjsSync?.hasPendingNodeEditLeaseAcquire?.()',
  )
  const freezeSave = saveBlock.indexOf('isSaving.value = true')

  assert.match(
    createSyncBlock,
    /canAcquireNodeEditLease: \(\) => \([\s\S]*?!isReadonly\.value[\s\S]*?!isSaving\.value[\s\S]*?!activeSaveMutation[\s\S]*?!isRecoveryStructureWriteBlocked\(\)/,
  )
  assert.match(
    recoveryWriteGateBlock,
    /resolvingStaleState[\s\S]*?authoritativeReloadInProgress[\s\S]*?authoritativeReloadRequired[\s\S]*?pendingAutomaticConflictRecovery[\s\S]*?pendingRemoteDocumentReset/,
  )
  assert.doesNotMatch(recoveryWriteGateBlock, /isSaving|activeSaveMutation/)
  assert.match(
    structureWriteGateBlock,
    /isRecoveryStructureWriteBlocked\(\)[\s\S]*?isStructureWriteBlocked/,
  )
  const pendingAdmissionStructureGate = Function(
    'isRecoveryStructureWriteBlocked',
    'yjsSync',
    `'use strict'; ${structureWriteGateBlock}; return isMindmapStructureWriteBlocked`,
  )(
    () => false,
    { isStructureWriteBlocked: () => true },
  )
  assert.equal(pendingAdmissionStructureGate(), true)
  assert.match(
    commandGuardBlock,
    /isMindmapStructureWriteBlocked\(\)[\s\S]*?shouldBlockMindmapStructureWrite\([\s\S]*?mindmapCommandStartsNodeTextEdit\(commandName, args,[\s\S]*?canAcquireNodeEditLease[\s\S]*?return false[\s\S]*?return execCommand\(commandName, \.\.\.args\)/,
  )
  assert.match(source, /installRecoveryStructureCommandGuard\(mm\)/)
  assert.match(source, /isStructureWriteBlocked: isMindmapStructureWriteBlocked/)
  assert.match(source, /const structureWriteBlocked = ref\(false\)/)
  assert.match(
    createSyncBlock,
    /onNodeEditLeaseSettled:[\s\S]*?refreshStructureWriteBlockedState\(\)[\s\S]*?resumePendingSaveAfterNodeEditLeaseSettles\(\)/,
  )
  assert.match(
    createSyncBlock,
    /onStructureWriteBlockedChange:[\s\S]*?wasBlocked[\s\S]*?refreshStructureWriteBlockedState\(\)[\s\S]*?wasBlocked && !isBlocked[\s\S]*?resumePendingSaveAfterNodeEditLeaseSettles\(\)/,
  )
  const resumePendingSaveBlock = source.match(
    /function resumePendingSaveAfterNodeEditLeaseSettles[\s\S]*?\n\}/,
  )?.[0] || ''
  assert.match(
    resumePendingSaveBlock,
    /isMindmapStructureWriteBlocked\(\)/,
  )
  assert.match(
    source,
    /function setAuthoritativeReloadRequiredState[\s\S]*?refreshStructureWriteBlockedState\(\)/,
  )
  assert.match(
    source,
    /function setPendingRemoteDocumentReset[\s\S]*?refreshStructureWriteBlockedState\(\)/,
  )
  assert.match(
    source,
    /function setResolvingStaleState[\s\S]*?refreshStructureWriteBlockedState\(\)/,
  )

  let recoveryActive = false
  let nodeEditLeaseAvailable = true
  const forwardedCommands = []
  const rejectedCommands = []
  const installCommandGuard = Function(
    'shouldBlockMindmapStructureWrite',
    'mindmapCommandStartsNodeTextEdit',
    'isMindmapStructureWriteBlocked',
    'props',
    'yjsSync',
    `'use strict'; ${commandGuardBlock}; return installRecoveryStructureCommandGuard`,
  )(
    shouldBlockMindmapStructureWrite,
    mindmapCommandStartsNodeTextEdit,
    () => recoveryActive,
    { mindmapId: 1 },
    {
      canAcquireNodeEditLease: () => nodeEditLeaseAvailable,
      getNodeEditLeaseFailureReason: () => 'unavailable',
    },
  )
  const guardedMindMap = {
    execCommand(commandName, ...args) {
      forwardedCommands.push([commandName, ...args])
      return 'executed'
    },
    emit(...args) {
      rejectedCommands.push(args)
    },
  }
  assert.equal(installCommandGuard(guardedMindMap), true)
  assert.equal(guardedMindMap.execCommand('INSERT_NODE', 'normal-save'), 'executed')
  recoveryActive = true
  assert.equal(guardedMindMap.execCommand('SET_NODE_TEXT', 'final-text'), 'executed')
  assert.equal(guardedMindMap.execCommand('INSERT_CHILD_NODE', 'ghost-node'), false)
  recoveryActive = false
  nodeEditLeaseAvailable = false
  assert.equal(guardedMindMap.execCommand('INSERT_NODE'), false)
  assert.equal(guardedMindMap.execCommand('INSERT_NODE', false), 'executed')
  assert.deepEqual(forwardedCommands, [
    ['INSERT_NODE', 'normal-save'],
    ['SET_NODE_TEXT', 'final-text'],
    ['INSERT_NODE', false],
  ])
  assert.deepEqual(rejectedCommands, [
    ['readonly_command_rejected', 'INSERT_CHILD_NODE'],
    ['node_text_edit_blocked', null, [], 'unavailable'],
  ])

  assert.ok(leaseGate >= 0)
  assert.ok(pendingLeaseGate > leaseGate)
  assert.ok(freezeSave > leaseGate)
  assert.ok(freezeSave > pendingLeaseGate)
  assert.match(
    saveBlock,
    /responseSuperseded[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?stopCurrentCollaborationSource\(\)/,
  )
  assert.match(
    saveBlock,
    /else if \(response\.data\.concurrentMerge\) \{[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?const hasNewerLocalChanges[\s\S]*?stopCurrentCollaborationSource\(\)/,
  )
  assert.match(
    source,
    /mm\.on\('node_text_edit_end'[\s\S]*?pendingSave\.value[\s\S]*?saveToBackend\(\)/,
  )
  assert.match(
    source,
    /function resumePendingSaveAfterNodeEditLeaseSettles[\s\S]*?hasActiveNodeEditLease[\s\S]*?hasPendingNodeEditLeaseAcquire[\s\S]*?saveToBackend\(\)/,
  )
  assert.match(
    source,
    /function commitActiveEditorsBeforeTermination[\s\S]*?cancelPendingTextEditAdmission\?\.\(\)[\s\S]*?hideEditTextBox\?\.\(\)/,
  )
})
