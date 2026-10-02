import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { babelParse, parse } from '@vue/compiler-sfc'

function functionsFrom(path, names, scope) {
  const script = parse(readFileSync(new URL(path, import.meta.url), 'utf8')).descriptor.scriptSetup.content
  const nodes = babelParse(script, { sourceType: 'module' }).program.body
  const functions = names.map(name => {
    const node = nodes.find(item => item.type === 'FunctionDeclaration' && item.id.name === name)
    assert.ok(node, name)
    return script.slice(node.start, node.end)
  })
  return new Function('scope', `with (scope) { ${functions.join('\n')} return { ${names.join(', ')} }; }`)(scope)
}

const ref = value => ({ value })
const noop = () => {}
function editorHarness() {
  const events = []
  const documents = []
  const source = { root: { data: { uid: 'root', text: '未保存内容' } } }
  const s = {
    componentMounted: true, terminalState: '', terminatingSession: false,
    isAuthSessionExpired: () => true, userStore: { token: 'test-session' },
    terminalCleanup: null, terminalCleanupPending: null,
    authenticationExpired: ref(false), authenticationRecoveryMessage: ref(''),
    activeSaveMutation: null, contentRevision: 4, frozen: null,
    draftProtection: { getChangeVersion: () => 2 },
    captureRejectedMindmapMutationSnapshot: () => s.frozen,
    commitActiveEditorsBeforeTermination: () => false,
    dirty: true, hasUnsavedChanges: () => s.dirty,
    mindMap: ref({ setMode: mode => events.push(['mode', mode]) }),
    getCurrentDocument: () => structuredClone(source),
    areMindmapDraftDocumentsEqual: (a, b) => JSON.stringify(a) === JSON.stringify(b),
    createAutomaticConflictDraftOptions: document => ({ document }),
    createDraftOptions: document => ({ document }),
    saveMindmapDraftFallbackSync: () => false,
    downloadConflictBackup: () => false,
    saveMindmapDraft: async options => { documents.push(options.document); return { saved: true } },
    enqueueDraftOperation: operation => Promise.resolve().then(operation),
    cancelSessionAsyncWork: () => events.push(['cancel-requests']),
    serverCanEdit: ref(true),
    actions: { setIsReadonly: readonly => events.push(['readonly', readonly]), setActiveSidebar: noop },
    versionChangeTrackingPaused: false,
    clearTimeout: noop, autoSaveTimer: 1, draftSaveTimer: 2, saveRetryTimer: 3,
    documentMetaBuffer: { clear: noop }, saveRecoveryKind: ref(''), blockedConflictData: null,
    pendingContentOperations: [], activeSaveDocumentDataGeneration: null,
    clearFileMetaIntentState: noop, clearPendingClientMutation: noop, resolveAuthoritativeReload: noop,
    savedViewChangeVersion: 0, viewChangeVersion: 1, isSaving: ref(true), pendingSave: ref(true),
    setSaveStatus: status => events.push(['save-status', status]),
    yjsSync: { destroy: options => events.push(['destroy-sync', options]) },
    yjsSyncRef: ref({}), refreshStructureWriteBlockedState: noop,
    emit: (name, payload) => events.push(['terminal-event', name, payload]),
  }
  const api = functionsFrom('../../components/MindMap/Edit.vue', ['terminateEditingSession', 'handleAuthenticationExpired'], s)
  return { s, events, documents, source, ...api }
}

test('HTTP 登录失效同步停止编辑和协作，重新登录清理等待草稿真正落盘', async () => {
  const h = editorHarness()
  let finish
  h.s.saveMindmapDraft = options => {
    h.documents.push(options.document)
    return new Promise(resolve => { finish = resolve })
  }
  let settled = false
  const pending = h.handleAuthenticationExpired().then(() => { settled = true })
  const duplicate = h.handleAuthenticationExpired()
  assert.equal(h.s.authenticationExpired.value, true)
  assert.equal(h.s.serverCanEdit.value, false)
  assert.deepEqual(h.events.slice(0, 3), [['cancel-requests'], ['readonly', true], ['mode', 'readonly']])
  assert.ok(h.events.some(item => item[0] === 'destroy-sync' && item[1].flushCheckpoint === false))
  await Promise.resolve()
  assert.equal(settled, false)
  assert.equal(h.documents.length, 1)
  finish({ saved: true })
  await Promise.all([pending, duplicate])
  assert.deepEqual(h.documents, [h.source])
  assert.match(h.s.authenticationRecoveryMessage.value, /本地草稿中心/u)
  const emitted = h.events.filter(item => item[0] === 'terminal-event')
  assert.equal(emitted.length, 1)
  assert.equal(emitted[0][2].authHandledGlobally, true)
  assert.equal(emitted[0][2].localRecoveryProtected, true)
})

test('草稿与下载均失败时拒绝导航清理，用户重试使用原冻结快照', async () => {
  const h = editorHarness()
  h.s.saveMindmapDraft = async () => ({ saved: false })
  await assert.rejects(h.handleAuthenticationExpired(), /尚未备份/u)
  assert.equal(h.s.terminalState, 'session-ended')
  assert.equal(h.s.serverCanEdit.value, false)
  h.s.getCurrentDocument = () => { throw new Error('不能用后续画布替换冻结快照') }
  h.s.saveMindmapDraft = async options => {
    h.documents.push(options.document)
    return { saved: true }
  }
  await h.handleAuthenticationExpired()
  assert.deepEqual(h.documents, [h.source])
  assert.match(h.s.authenticationRecoveryMessage.value, /本地草稿中心/u)
  assert.equal(h.events.filter(item => item[0] === 'terminal-event').length, 1)
})

test('冻结在途批次和后续输入分别保留，本地存储与下载混合成功也不会丢失内容', async () => {
  const h = editorHarness()
  h.s.frozen = { document: { root: { data: { uid: 'root', text: '在途批次' } } }, baseRevision: 3 }
  h.s.saveMindmapDraftFallbackSync = options => options.document.root.data.text === '在途批次'
  h.s.downloadConflictBackup = document => document.root.data.text === '未保存内容'
  h.s.saveMindmapDraft = async () => ({ saved: false })
  await h.handleAuthenticationExpired()
  const result = h.events.find(item => item[0] === 'terminal-event')[2]
  assert.equal(result.localDraftPreserved, false)
  assert.equal(result.localBackupCreated, false)
  assert.equal(result.localRecoveryProtected, true)
  assert.match(h.s.authenticationRecoveryMessage.value, /分别保存在/u)
})

test('没有未保存内容时不会伪称已备份，也不会写草稿', async () => {
  const h = editorHarness()
  h.s.dirty = false
  await h.handleAuthenticationExpired()
  assert.deepEqual(h.documents, [])
  assert.match(h.s.authenticationRecoveryMessage.value, /只读/u)
  assert.equal(h.events.find(item => item[0] === 'terminal-event')[2].needsLocalBackup, false)
})

test('HTTP 失效不再叠加页面会话弹窗，独立协作终止仍保留提示', async () => {
  const dialogs = []
  const api = functionsFrom('../../views/mindmap/edit.vue', ['onSessionEnded'], {
    showTerminalDialog: (...args) => dialogs.push(args),
  })
  await api.onSessionEnded({ authHandledGlobally: true })
  assert.deepEqual(dialogs, [])
  await api.onSessionEnded({ reason: 'auth_unavailable' })
  assert.equal(dialogs.length, 1)
  assert.equal(dialogs[0][0], '协作认证暂时不可用')
})
