import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { babelParse, parse } from '@vue/compiler-sfc'
import { createMindmapCollaborationRecoveryGuard } from '../mindmap-collaboration-recovery.js'

const script = parse(readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'))
  .descriptor.scriptSetup.content
const functions = babelParse(script, { sourceType: 'module' }).program.body
function harness() {
  const events = []
  const state = {
    collaborationRecoveryGuard: createMindmapCollaborationRecoveryGuard({ now: () => 1 }),
    authoritativeReloadRequired: true, authoritativeReloadNoticeShown: false,
    authoritativeReloadAttempt: 0, authoritativeReloadTimer: null, autoSaveTimer: null,
    saveRecoveryKind: { value: '' }, versionChangeTrackingPaused: false, resolvingStaleState: false,
    mindMap: { value: {} }, isSaving: { value: false }, sessionController: null,
    viewSaveRequested: false, viewSaveInProgress: false, pendingAutomaticConflictRecovery: null,
    pendingRemoteDocumentReset: null,
    shouldDeferAiAuthoritativeDocument: () => false,
    raiseAuthoritativeReloadMinimumRevision: data => events.push(['floor', data.currentRevision]),
    commitActiveEditorsBeforeTermination: () => events.push(['commit']),
    setAuthoritativeRecoveryEditingBlocked: value => events.push(['readonly', value]),
    stopCurrentCollaborationSource: () => events.push(['stop']),
    clearTimeout() {}, setSaveStatus: value => events.push(['status', value]),
    ElNotification: { warning: value => events.push(['warning', value]) },
    ElMessage: { info: value => events.push(['toast', value]) },
    dirty: false, hasUnsavedChanges: () => state.dirty,
    persistLocalDraft: async () => { events.push(['draft']); return { saved: true } },
    setResolvingStaleState: value => { state.resolvingStaleState = value },
    nextTick: async () => {}, sessionCancelled: () => false,
    drainPendingRemoteDocumentReset() {},
    performAuthoritativeReload: async () => {
      events.push(['get'])
      // Existing successful-GET cleanup resets its own HTTP retry budget.
      state.authoritativeReloadAttempt = 0
      state.authoritativeReloadNoticeShown = false
      return true
    },
  }
  const names = ['handleStaleCollaborationState', 'recoverSave']
  const source = names.map(name => {
    const node = functions.find(item => item.type === 'FunctionDeclaration' && item.id.name === name)
    return script.slice(node.start, node.end)
  }).join('\n')
  const api = new Function('scope', `with (scope) { ${source}; return { ${names.join(', ')} } }`)(state)
  return { state, events, ...api }
}

test('successful HTTP reloads cannot cause an unbounded stale/reconnect loop or success toasts', async () => {
  const h = harness()
  for (let i = 0; i < 8; i++) await h.handleStaleCollaborationState({ currentRevision: 991 })
  assert.equal(h.events.filter(item => item[0] === 'get').length, 3)
  assert.equal(h.events.filter(item => item[0] === 'warning').length, 1)
  assert.equal(h.events.filter(item => item[0] === 'toast').length, 0)
  assert.equal(h.state.collaborationRecoveryGuard.blocked, true)
  assert.equal(h.state.saveRecoveryKind.value, 'sync')
  assert.ok(h.events.some(item => item[0] === 'readonly' && item[1]))
})

test('exhausted recovery retains new input and explicit sync allows another bounded attempt', async () => {
  const h = harness()
  for (let i = 0; i < 3; i++) await h.handleStaleCollaborationState({ currentRevision: 991 })
  h.state.dirty = true
  await h.handleStaleCollaborationState({ currentRevision: 992 })
  assert.ok(h.events.some(item => item[0] === 'draft'))
  assert.ok(h.events.some(item => item[0] === 'floor' && item[1] === 992))
  h.state.dirty = false
  assert.equal(await h.recoverSave(), true)
  assert.equal(h.state.collaborationRecoveryGuard.blocked, false)
  assert.equal(h.events.filter(item => item[0] === 'get').length, 4)
})

test('infrequent collaboration resets remain recoverable and deferred events do not use retry budget', async () => {
  let time = 0
  const guard = createMindmapCollaborationRecoveryGuard({ now: () => time })
  for (let i = 0; i < 10; i++) {
    assert.equal(guard.recordFailure(), true)
    time += 31_000
  }
  const h = harness()
  h.state.versionChangeTrackingPaused = true
  for (let i = 0; i < 10; i++) await h.handleStaleCollaborationState({ currentRevision: 992 })
  assert.equal(h.state.collaborationRecoveryGuard.blocked, false)
  assert.equal(h.events.filter(item => item[0] === 'get').length, 0)
})
