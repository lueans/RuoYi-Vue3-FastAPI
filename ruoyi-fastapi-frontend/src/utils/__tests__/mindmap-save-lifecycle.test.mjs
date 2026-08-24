import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  flushPendingMindmapChanges,
  getMindmapSaveRecoveryAction,
} from '../mindmap-save-lifecycle.js'

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
  assert.match(source, /draftProtection\.recordPersistResult\(draftChangeVersion, saved\)/)
  assert.match(source, /isLocalDraftProtected: \(\) => draftProtection\.isProtected\(\)/)
  assert.match(pageSource, /editRef\.value\?\.isLocalDraftProtected\?\.\(\) === true/)
  assert.doesNotMatch(pageSource, /\['pending', 'retrying', 'offline'\]\.includes\(saveStatus\.value\)/)
  assert.match(source, /removeEventListener\('pagehide', handlePageHide\)/)
  assert.match(source, /removeEventListener\('visibilitychange', handleVisibilityChange\)/)
  assert.match(source, /flushPendingMindmapChanges\(\{/)
  assert.match(source, /async function prepareForCloudExit\(\)/)
  assert.match(source, /commitActiveEditorsBeforeTermination\(\)[\s\S]*?await flushBeforeLeave\(\)/)
  assert.match(source, /await draftWriteQueue[\s\S]*?removeMindmapDraft\(userStore\.id, props\.mindmapId, \{[\s\S]*?beforeUpdatedAt: clearBeforeUpdatedAt,[\s\S]*?sessionId: draftSessionId/)
  assert.match(source, /const restoredDraftToClear = restoredDraftRecord[\s\S]*?key: restoredDraftToClear\.key,[\s\S]*?beforeUpdatedAt: restoredDraftToClear\.updatedAt/)
  assert.match(pageSource, /editRef\.value\?\.prepareForCloudExit\?\.\(\)/)
  assert.match(source, /blockedConflictData = error\.data/)
  assert.match(source, /function persistLocalDraft\(\{ notifyFailure = true \} = \{\}\)/)
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
})
