import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { applyAuthoritativeMindmapDocument } from '../mindmap-document-apply.js'

const editor = readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8')
const commandSource = readFileSync(new URL('../../libs/simple-mind-map/src/core/command/Command.js', import.meta.url), 'utf8')
function sourceBetween(source, start, end) {
  const from = source.indexOf(start)
  const to = source.indexOf(end, from)
  assert.ok(from >= 0 && to > from)
  return source.slice(from, to)
}
// Execute the actual command, editor commit and authoritative history helper.
// Only renderer/network IO is replaced; the undo/rebase algorithm is not mocked.
const back = new Function(`return ({
  ${sourceBetween(commandSource, '  back(step = 1)', '  //  前进')}
}).back`)()
const makeReload = new Function('io', `
  const { applyAuthoritativeMindmapDocument } = io;
  const mindMap = { value: io.mindMap };
  const aiEditingBlocked = { value: io.ai };
  let aiDraftPreviewState = io.session;
  const props = { mindmapId: 1 };
  const sessionController = null;
  const sessionCancelled = () => false;
  const hasActiveEditingTransition = () => false;
  const editingTransitionGeneration = 0;
  const viewChangeVersion = 0;
  const documentDataGeneration = 0;
  const draftProtection = { getChangeVersion: () => 0 };
  const viewSaveRequested = io.pendingView;
  const viewSaveInProgress = io.savingView;
  const hasUnsavedChanges = () => io.dirty;
  const getMindmap = async () => { io.onRead(); return { data: io.serverData }; };
  let contentRevision = 1;
  const pendingRemoteDocumentReset = null;
  const normalizeServerTheme = value => value;
  const normalizeMindmapDocumentData = value => value || {};
  const defaultData = null;
  const getAuthoritativeReloadMinimumRevision = () => 1;
  const ensureMindmapDocumentPlugins = async () => {};
  const markAuthoritativeReloadRequired = () => {};
  const protectActiveTextEditorBeforeRemoteDocumentApply = () => {};
  const commitActiveEditorsBeforeTermination = () => {};
  const nextTick = async () => {};
  const getCurrentDocument = () => io.mindMap.getData(true);
  const cloneRequestPayload = structuredClone;
  let applyingServerTree = false;
  const renderAiPreviewTree = async () => {};
  const documentData = { value: {} };
  const applyMindmapDocumentConfig = () => {};
  const enterAuthoritativeApplyFailureRecovery = async () => {};
  const nodeRevisionMap = new Map();
  let pendingContentOperations, activeSaveMutation, activeSaveDocumentDataGeneration;
  const clearFileMetaIntentState = () => {};
  const clearPendingClientMutation = () => {};
  const resolveAuthoritativeReload = () => true;
  let crossNodeOperationSnapshot;
  const extractCrossNodeState = () => ({});
  const markDocumentMetaSaved = () => {};
  let savedViewChangeVersion, conflictBlocked;
  const clearSaveRetryState = () => {};
  const setAuthoritativeRecoveryEditingBlocked = () => {};
  const clearLocalDraft = () => {};
  const clearRestoredDraft = () => {};
  const onYjsReinit = () => {};
  const acknowledgeRemoteDocumentReset = () => {};
  const setSaveStatus = () => {};
  ${sourceBetween(editor, 'function assertAiPresentationSession(', 'let terminatingSession')}
  ${sourceBetween(editor, 'async function reloadLatestServerDocument(', 'function downloadConflictBackup(')}
  return {
    commit: options => commitAiAuthoritativeDocument(io.session, options),
    ordinaryReload: () => reloadLatestServerDocument(),
  };
`)

const tree = (ai = '原 AI 节点', collaborator = '协作者原文', local = '本地原文') => ({
  data: { uid: 'root', text: '脑图' },
  children: [
    { data: { uid: 'ai', text: ai }, children: [] },
    { data: { uid: 'collaborator', text: collaborator }, children: [] },
    { data: { uid: 'local', text: local }, children: [] },
  ],
})
const texts = root => root.children.map(node => node.data.text)

function harness({ history, baseline, visible, cloud, ai = true, dirty = false, pendingView = false, savingView = false }) {
  let document = {
    root: structuredClone(visible),
    layout: 'logicalStructure',
    theme: { template: 'default', config: {} },
    documentData: {},
  }
  const updates = []
  const reads = []
  const applications = []
  const mindMap = {
    opt: { readonly: false },
    getData: () => structuredClone(document),
    updateData(root) { applications.push(root); document.root = structuredClone(root) },
    setFullData(next) { applications.push(next); document = structuredClone(next) },
    emit() {},
  }
  const addHistory = () => {}
  addHistory.cancel = () => {}
  mindMap.command = {
    mindMap,
    history: history.map(root => JSON.stringify(root)),
    activeHistoryIndex: history.length - 1,
    isPause: false,
    addHistory,
    getCopyData: () => structuredClone(document.root),
    pause() { this.isPause = true },
    recovery() { this.isPause = false },
    resetHistoryBaseline() {
      this.history = [JSON.stringify(document.root)]
      this.activeHistoryIndex = 0
    },
    back,
    emitDataUpdatesEvent(before, after) { updates.push({ before, after }) },
  }
  const serverData = {
    nodeTree: structuredClone(cloud),
    contentRevision: 8,
    nodeRevisions: { root: 8, ai: 8, collaborator: 8, local: 8 },
    layout: document.layout,
    theme: document.theme,
    documentData: {},
  }
  const session = {
    mindMap,
    directCommitted: true,
    baseline: { ...structuredClone(document), root: structuredClone(baseline) },
    commitServerData: serverData,
  }
  return {
    ...makeReload({ mindMap, session, serverData, ai, applyAuthoritativeMindmapDocument,
      dirty, pendingView, savingView, onRead: () => reads.push(true) }),
    command: mindMap.command,
    updates,
    reads,
    applications,
    document: () => structuredClone(document),
  }
}

test('AI 终态校准不能把已播放结果变成本地撤销记录', async () => {
  const baseline = tree()
  const cloud = tree('AI 完成文字', '协作者刚保存的新文')
  const runtime = harness({ history: [baseline], baseline, visible: cloud, cloud })

  assert.equal(await runtime.commit(), true)
  assert.equal(runtime.command.history.length, 1)
  assert.deepEqual(texts(JSON.parse(runtime.command.history[0])), texts(cloud))
  assert.equal(runtime.command.back(), undefined)
  assert.equal(runtime.updates.length, 0, 'Ctrl+Z 不得产生回写协作者旧值的本地变化')
})

test('AI 完成后仍可撤销无关人工修改，但不能撤销 AI 或协作者正文', async () => {
  const beforeLocalEdit = tree()
  const baseline = tree('原 AI 节点', '协作者原文', '已保存的人工修改')
  const cloud = tree('AI 完成文字', '协作者刚保存的新文', '已保存的人工修改')
  const runtime = harness({ history: [beforeLocalEdit, baseline], baseline, visible: cloud, cloud })

  await runtime.commit()
  assert.equal(runtime.command.history.length, 2, '合法人工历史仍然存在，播放没有新增历史')
  assert.deepEqual(texts(runtime.command.back()), ['AI 完成文字', '协作者刚保存的新文', '本地原文'])
  assert.equal(runtime.command.back(), undefined)
  assert.equal(runtime.updates.length, 1)
})

test('AI 终态与旧人工历史重叠时清理不安全历史，而不是恢复旧云端内容', async () => {
  const beforeLocalEdit = tree('原 AI 节点', '更早的协作者正文')
  const baseline = tree()
  const cloud = tree('AI 完成文字', '协作者刚保存的新文')
  const runtime = harness({ history: [beforeLocalEdit, baseline], baseline, visible: cloud, cloud })

  await runtime.commit()
  assert.equal(runtime.command.history.length, 1)
  assert.deepEqual(texts(JSON.parse(runtime.command.history[0])), texts(cloud))
  assert.equal(runtime.command.back(), undefined)
})

test('确认创建失败释放准备态时保留合法人工撤销并重基准备期间协作者更新', async () => {
  const beforeLocalEdit = tree()
  const baseline = tree('原 AI 节点', '协作者原文', '已保存的人工修改')
  const cloud = tree('原 AI 节点', '准备期间的协作者新文', '已保存的人工修改')
  const runtime = harness({ history: [beforeLocalEdit, baseline], baseline, visible: baseline, cloud })

  assert.equal(await runtime.commit({ abortPreparation: true }), true)
  assert.equal(runtime.command.history.length, 2)
  assert.deepEqual(texts(runtime.command.back()), ['原 AI 节点', '准备期间的协作者新文', '本地原文'])
})

test('AI 终态和准备撤销都不能用权威正文覆盖未排空的人工内容或视图保存', async () => {
  for (const abortPreparation of [false, true]) {
    for (const residue of ['dirty', 'pendingView', 'savingView']) {
      const baseline = tree()
      const visible = tree('原 AI 节点', '协作者原文', '尚未保存的人工文字')
      const cloud = tree('新 AI 文字')
      const runtime = harness({
        history: [baseline, visible], baseline, visible, cloud,
        [residue]: true,
      })
      const history = [...runtime.command.history]
      await assert.rejects(runtime.commit({ abortPreparation }), /人工修改尚未保存/)
      assert.equal(runtime.reads.length, 0, `${residue}: 不应发起覆盖用 GET`)
      assert.equal(runtime.applications.length, 0, `${residue}: 不得先覆盖再报错`)
      assert.deepEqual(runtime.document().root, visible)
      assert.deepEqual(runtime.command.history, history)
      assert.equal(runtime.updates.length, 0)
    }
  }
})

test('普通权威补拉继续使用当前人工树，不读取 AI 会话基线', async () => {
  const beforeLocalEdit = tree()
  const visible = tree('原 AI 节点', '协作者原文', '人工当前值')
  const cloud = tree('原 AI 节点', '协作者新文', '人工当前值')
  const runtime = harness({
    history: [beforeLocalEdit, visible],
    baseline: beforeLocalEdit,
    visible,
    cloud,
    ai: false,
  })

  assert.equal(await runtime.ordinaryReload(), true)
  assert.deepEqual(texts(runtime.command.back()), ['原 AI 节点', '协作者新文', '本地原文'])
})
