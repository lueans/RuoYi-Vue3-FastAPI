import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { nextMindmapAiDraftFrame, summarizeMindmapAiDraftChanges } from '../mindmap-ai-live-preview.js'

// Execute the editor's actual event handler with isolated IO. The browser
// fixture separately exercises the real SVG renderer, not a rendering mock.
const editor = readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8')
function sourceBetween(start, end) {
  return editor.slice(editor.indexOf(start), editor.indexOf(end, editor.indexOf(start)))
}
const node = text => ({ data: { uid: 'root', text }, children: [] })
function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function harness(hooks = {}) {
  let document = { root: node('基线') }
  let failCommit = false
  const frames = []
  const commits = []
  const warnings = []
  const preparationEvents = []
  const create = new Function('io', `
    const mindMap = { value: io.ready() ? { renderer: {}, setMode(mode) { io.preparationEvent('rendererMode', mode); } } : null };
    const aiEditingBlocked = { value: false };
    const aiPreparationEditingBlocked = { value: false };
    let aiCanvasPreparation = null;
    let aiDraftPreviewState = null;
    let aiPresentationSessionSequence = 0;
    let aiPresentationDetached = false;
    let applyingServerTree = false;
    let versionChangeTrackingPaused = false;
    let terminalState = false;
    let terminatingSession = false;
    const versionTransitionEditingBlocked = { value: false };
    const importTransitionEditingBlocked = { value: false };
    const authoritativeRecoveryEditingBlocked = { value: false };
    const protectingActiveEditorFromRemoteDelete = false;
    const yjsSync = null;
    const serverCanEdit = { value: true };
    let componentMounted = true;
    let authoritativeReloadRequired = false;
    let authoritativeReloadInProgress = false;
    let viewSaveRequested = false;
    let viewSaveInProgress = false;
    const pendingSave = { value: false };
    const pendingRemoteDocumentReset = null;
    const collaborationBarrierEditingBlocked = { value: false };
    const hasActiveEditingTransition = () => io.transition();
    const props = { mindmapId: 1 };
    const sessionController = { signal: { aborted: false } };
    const autoSaveTimer = null;
    const documentData = { value: {} };
    const defaultData = { data: { uid: 'root', text: '' } };
    const cloneRequestPayload = structuredClone;
    const getCurrentDocument = () => io.document();
    const setMode = () => {};
    const syncEditingBlockedMode = () => io.preparationEvent('mode', aiEditingBlocked.value || aiPreparationEditingBlocked.value);
    const bindYjsDetailTracking = setMode;
    const resumePendingSaveAfterNodeEditLeaseSettles = () => io.preparationEvent('resume', pendingSave.value);
    const commitActiveEditorsBeforeTermination = () => io.commitEditors();
    const hasRealWritePermission = () => !props.readonly && serverCanEdit.value === true;
    const hasUnsavedChanges = () => io.dirty();
    const nextTick = async () => io.nextTick();
    const flushBeforeLeave = () => io.flush({
      readonly: aiEditingBlocked.value || aiPreparationEditingBlocked.value,
      suspended: isChangeTrackingSuspended(),
      owned: aiDraftPreviewState !== null,
    });
    const performAuthoritativeReload = async () => {
      const reloaded = await io.reload();
      if (reloaded) authoritativeReloadRequired = false;
      return reloaded;
    };
    const clearMindmapAiPresentation = (_map, options) => io.clear(options);
    const ElMessage = { warning: message => io.warning(message) };
    const bus = { emit() {} };
    const actions = { setIsReadonly: value => io.preparationEvent('readonly', value) };
    const normalizeServerTheme = value => value || {};
    const normalizeMindmapDocumentData = value => value || {};
    const ensureMindmapDocumentPlugins = async document => io.prepare(document);
    const applyMindmapDocumentConfig = setMode;
    const previewDocumentDataChanged = () => false;
    const renderAiPreviewTree = async () => true;
    const onAiNodeFocus = setMode;
    const getMindmap = () => io.target();
    const summarizeMindmapAiDraftChanges = io.summarize;
    const applyMindmapAiPresentationFrame = async (_map, before, frame) => io.frame(before, frame);
    const reloadLatestServerDocument = options => io.commit(options);
    ${sourceBetween('function assertAiPresentationSession(', 'let terminatingSession')}
    ${sourceBetween('function sessionCancelled(', 'function cancelSessionAsyncWork(')}
    ${sourceBetween('function setAiEditingBlocked(', 'function setVersionTransitionEditingBlocked(')}
    ${sourceBetween('function rejectEditModeDuringEditingTransition(', 'async function enterAuthoritativeApplyFailureRecovery(')}
    ${sourceBetween('function isChangeTrackingSuspended(', 'function focusNodeByUid(')}
    ${sourceBetween('function assertAiCanvasPreparation(', 'function onNodeTagClick(')}
    return {
      request: payload => new Promise((resolve, reject) => onAiDraftPreview(payload, { resolve, reject })),
      state: () => aiDraftPreviewState,
      blocked: () => aiEditingBlocked.value,
      deferred: shouldDeferAiAuthoritativeDocument,
      unlock: (jobId = aiDraftPreviewState?.jobId || '') => onAiEditingState({ jobId, locked: false }),
      lock: (jobId = aiDraftPreviewState?.jobId || '') => onAiEditingState({ jobId, locked: true }),
      readonly: () => aiEditingBlocked.value || aiPreparationEditingBlocked.value,
      suspended: isChangeTrackingSuspended,
      preparing: () => aiCanvasPreparation,
      rejectEditMode: mode => rejectEditModeDuringEditingTransition(mode, mindMap.value),
      expire: kind => {
        if (kind === 'map') mindMap.value = { renderer: {}, setMode() {} };
        if (kind === 'permission') serverCanEdit.value = false;
        if (kind === 'unmount') componentMounted = false;
        if (kind === 'aborted') sessionController.signal.aborted = true;
        if (kind === 'terminal') terminalState = 'ended';
      },
      requireReload: value => { authoritativeReloadRequired = value; },
      reloadInProgress: value => { authoritativeReloadInProgress = value; },
      pendingView: value => { viewSaveRequested = value; },
      savingView: value => { viewSaveInProgress = value; },
    };
  `)
  const session = create({
    document: () => document,
    ready: () => hooks.ready !== false,
    transition: hooks.transition || (() => false),
    frame: async (before, frame) => {
      frames.push({ before, frame })
      await hooks.frame?.(before, frame)
    },
    target: hooks.target || (async () => ({ data: { nodeTree: node('最终云端文字'), contentRevision: 8 } })),
    prepare: hooks.prepare || (() => {}),
    clear: hooks.clear || (() => {}),
    warning: message => warnings.push(message),
    preparationEvent: (...event) => preparationEvents.push(event),
    commitEditors: hooks.commitEditors || (() => {}),
    dirty: hooks.dirty || (() => false),
    nextTick: hooks.nextTick || (() => {}),
    flush: hooks.flush || (async () => true),
    reload: hooks.reload || (async () => true),
    summarize: summarizeMindmapAiDraftChanges,
    commit: async options => {
      commits.push(options)
      return hooks.commit ? hooks.commit(options) : !failCommit
    },
  })
  return { ...session, frames, commits, warnings, preparationEvents, changeDocument: value => { document = value }, failCommit: value => { failCommit = value } }
}

test('请求前获取画布所有权，采用任务 ID 和重复 start 都不能重新捕获基线', async () => {
  const session = harness()
  await session.request({ phase: 'prepare', jobId: 'preparing:1', directCommitted: true })
  assert.equal(session.blocked(), true)
  assert.equal(session.deferred(), true)
  session.changeDocument({ root: node('不应作为新基线的全文') })
  const adopted = await session.request({ phase: 'start', jobId: 'job1', preparationId: 'preparing:1', directCommitted: true })
  assert.equal(adopted.document.root.data.text, '基线')
  await session.request({ phase: 'update', jobId: 'job1', document: { root: node('第') }, typewriterTarget: { uid: 'root', text: '第一个节点' } })
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  assert.equal(session.state().rendered.root.data.text, '第')
  assert.equal(session.frames[0].before.root.data.text, '基线')
  assert.equal(session.frames[0].frame.document.root.data.text, '第')
  session.unlock()
  assert.equal(session.blocked(), true, 'terminal watcher must not unlock before commit')
})

const prepareNew = jobId => ({ phase: 'prepare', jobId, directCommitted: true, drainLocalChanges: true })
const tick = () => new Promise(resolve => setImmediate(resolve))

test('新请求准备先冻结人工输入并允许真实保存 gate 排空，成功后才捕获基线', async () => {
  const saving = deferred()
  let dirty = true
  let flushCalls = 0
  let editorCommits = 0
  const session = harness({
    dirty: () => dirty,
    commitEditors: () => { if (editorCommits++ === 0) dirty = true },
    flush: async state => {
      flushCalls += 1
      assert.equal(state.readonly, true, '网络等待前必须同步冻结输入')
      assert.equal(state.suspended, false, '使用实际 isChangeTrackingSuspended，不能把保存和输入一起锁住')
      assert.equal(state.owned, false, '排空中的画布还不能被当成 AI 播放树')
      await saving.promise
      dirty = false
      session.changeDocument({ root: node('活动编辑器和在途第二批均已保存') })
      return true
    },
  })
  // Dialog watcher may acquire the ordinary AI lock before the request arrives.
  session.lock('preparing:drain')
  const pending = session.request(prepareNew('preparing:drain'))
  assert.equal(session.readonly(), true, '直到首个 await 前都不留下可输入窗口')
  await tick()
  assert.equal(flushCalls, 1)
  assert.equal(session.state(), null)
  assert.equal(session.suspended(), false)
  session.lock('preparing:drain')
  session.unlock('preparing:drain')
  assert.equal(session.readonly(), true, 'watcher 解锁不能覆盖排空门闩')
  assert.equal(session.suspended(), false, 'watcher 上锁也不能重新阻断现存保存')
  saving.resolve()
  const started = await pending
  assert.equal(started.document.root.data.text, '活动编辑器和在途第二批均已保存')
  assert.equal(session.blocked(), true)
  assert.equal(session.suspended(), true, '真正接管后重新禁止普通保存')
  assert.equal(session.preparing(), null)
})

test('排空期间同准备重复与不同任务均拒绝，不重复排空或捕获基线', async () => {
  const saving = deferred()
  let flushCalls = 0
  const session = harness({ flush: () => { flushCalls += 1; return saving.promise } })
  const pending = session.request(prepareNew('preparing:one'))
  await tick()
  assert.equal(flushCalls, 1)
  await assert.rejects(session.request(prepareNew('preparing:one')))
  await assert.rejects(session.request(prepareNew('preparing:other')))
  await assert.rejects(session.request({ phase: 'start', jobId: 'other', directCommitted: true }))
  assert.equal(session.state(), null)
  assert.equal(flushCalls, 1)
  saving.resolve(true)
  await pending
  assert.equal(session.state().jobId, 'preparing:one')
})

test('准备排空失败保留 dirty；未取得 AI owner 的撤销只 ACK，不回源或覆盖正文', async () => {
  let dirty = true
  const session = harness({ dirty: () => dirty, flush: async () => false })
  session.changeDocument({ root: node('尚未保存的人工修改') })
  await assert.rejects(session.request(prepareNew('preparing:failed')))
  assert.equal(session.state(), null)
  assert.equal(session.preparing(), null)
  assert.equal(session.readonly(), false)
  const result = await session.request({ phase: 'preparation-aborted', jobId: 'preparing:failed', notCreated: true })
  assert.equal(result.cleared, true)
  assert.equal(session.commits.length, 0)
  assert.equal(session.frames.length, 0)
  assert.equal(dirty, true)
  assert.ok(session.preparationEvents.some(([kind, pending]) => kind === 'resume' && pending === true), '失败后保留并恢复既有保存意图')
  dirty = false
  const restored = await session.request({ phase: 'start', jobId: 'later', directCommitted: true })
  assert.equal(restored.document.root.data.text, '尚未保存的人工修改')
})

test('准备失败恢复提前到达的 AI 锁，Dialog 明确解除后才恢复人工保存', async () => {
  const session = harness({ dirty: () => true, flush: async () => false })
  session.lock('preparing:early-lock')
  await assert.rejects(session.request(prepareNew('preparing:early-lock')))
  assert.equal(session.state(), null)
  assert.equal(session.blocked(), true, '不能越权撤销 Dialog 持有的前置锁')
  await session.request({ phase: 'preparation-aborted', jobId: 'preparing:early-lock', notCreated: true })
  session.unlock('preparing:early-lock')
  assert.equal(session.readonly(), false)
  assert.equal(session.suspended(), false)
  assert.equal(session.commits.length, 0)
  assert.deepEqual(session.preparationEvents.at(-1), ['resume', true])
})

test('直接切换编辑模式不能穿透准备排空锁或 AI 正文所有权', async () => {
  const saving = deferred()
  const session = harness({ flush: () => saving.promise })
  assert.equal(session.rejectEditMode('edit'), false)
  const pending = session.request(prepareNew('preparing:mode'))
  await tick()
  assert.equal(session.rejectEditMode('edit'), true)
  assert.equal(session.rejectEditMode('readonly'), false, '只拒绝放开输入的模式切换')
  assert.deepEqual(session.preparationEvents.at(-1), ['rendererMode', 'readonly'])
  saving.resolve(true)
  await pending
  assert.equal(session.rejectEditMode('edit'), true)
  assert.deepEqual(session.preparationEvents.at(-1), ['rendererMode', 'readonly'])
})

test('准备排空被 detach 取代后，迟到保存不能重建旧 owner 或解锁新会话', async () => {
  const saving = deferred()
  const session = harness({ flush: () => saving.promise })
  const old = session.request(prepareNew('preparing:old'))
  const outcome = old.then(value => ({ value }), error => ({ error }))
  await tick()
  await session.request({ phase: 'detach', jobId: 'preparing:old', reason: 'session-ended' })
  assert.equal(session.preparing(), null)
  assert.equal(session.readonly(), true)
  await session.request({ phase: 'start', jobId: 'new', directCommitted: true })
  saving.resolve(true)
  assert.ok((await outcome).error)
  assert.equal(session.state().jobId, 'new')
  assert.equal(session.blocked(), true)
})

test('drain 已完成但 handler 尚未续跑的微任务窗口也不能恢复被 detach 的准备', async () => {
  let armDetach = false
  let detached
  const session = harness({
    flush: async () => { armDetach = true; return true },
    dirty: () => {
      if (armDetach) {
        armDetach = false
        queueMicrotask(() => {
          detached = session.request({ phase: 'detach', jobId: 'preparing:microtask', reason: 'session-ended' })
        })
      }
      return false
    },
  })
  await assert.rejects(session.request(prepareNew('preparing:microtask')))
  assert.equal((await detached).detached, true)
  assert.equal(session.state(), null)
  assert.equal(session.preparing(), null)
  assert.equal(session.readonly(), true)
})

test('接管前最后一次关闭编辑器若产生新 dirty，不能捕获未保存基线', async () => {
  let dirty = false
  let editorCommits = 0
  const session = harness({
    dirty: () => dirty,
    commitEditors: () => { if (++editorCommits === 2) dirty = true },
  })
  await assert.rejects(session.request(prepareNew('preparing:last-blur')))
  assert.equal(editorCommits, 2)
  assert.equal(dirty, true)
  assert.equal(session.state(), null)
  assert.equal(session.commits.length, 0)
  await session.request({ phase: 'preparation-aborted', jobId: 'preparing:last-blur', notCreated: true })
  assert.equal(dirty, true)
})

test('准备排空每次异步等待后校验画布、权限和终止状态，迟到成功不能取得所有权', async () => {
  for (const waitAt of ['nextTick', 'flush', 'reload']) {
    for (const reason of ['map', 'permission', 'unmount', 'aborted', 'terminal']) {
      const waiting = deferred()
      let entered = false
      const session = harness({ [waitAt]: () => { entered = true; return waiting.promise } })
      if (waitAt === 'reload') session.requireReload(true)
      const pending = session.request(prepareNew(`preparing:${waitAt}:${reason}`))
      const outcome = pending.then(value => ({ value }), error => ({ error }))
      await tick()
      assert.equal(entered, true, `${waitAt}/${reason}: 必须进入实际异步边界`)
      session.expire(reason)
      waiting.resolve(true)
      assert.ok((await outcome).error, `${waitAt}/${reason}: 迟到准备必须拒绝`)
      assert.equal(session.state(), null, `${waitAt}/${reason}: 不得创建迟到 owner`)
      assert.equal(session.preparing(), null)
    }
  }
})

test('保存成功但需权威校准时，先完成 reload 再捕获最终 baseline', async () => {
  const reloading = deferred()
  let reloadCalls = 0
  const session = harness({
    flush: async () => { session.requireReload(true); return true },
    reload: async () => {
      reloadCalls += 1
      assert.equal(session.state(), null)
      assert.equal(session.deferred(), false, '排空不能拦截自身的权威校准')
      await reloading.promise
      session.changeDocument({ root: node('云端并发合并后的权威基线') })
      return true
    },
  })
  const pending = session.request(prepareNew('preparing:reload'))
  await tick()
  assert.equal(reloadCalls, 1)
  assert.equal(session.readonly(), true)
  reloading.resolve()
  const result = await pending
  assert.equal(result.document.root.data.text, '云端并发合并后的权威基线')
  assert.equal(session.blocked(), true)
})

test('排空回调不能以 true 掩盖剩余 dirty、视图保存或未完成校准', async () => {
  for (const residue of ['dirty', 'pendingView', 'savingView', 'reloadInProgress', 'reloadFailure']) {
    const session = harness({
      dirty: () => residue === 'dirty',
      reload: async () => false,
    })
    if (residue === 'reloadFailure') session.requireReload(true)
    else if (residue !== 'dirty') session[residue](true)
    await assert.rejects(session.request(prepareNew(`preparing:${residue}`)))
    assert.equal(session.state(), null, `${residue} 尚未清理就不能接管画布`)
    assert.equal(session.commits.length, 0)
  }
})

test('未知创建恢复与 start 永不普通 flush，已接管后的重复握手不保存播放前缀', async () => {
  for (const phase of ['prepare', 'start']) {
    let flushCalls = 0
    const session = harness({ flush: async () => { flushCalls += 1; throw new Error('不能普通保存') } })
    const jobId = `${phase}:restore`
    await session.request({ phase, jobId, directCommitted: true })
    if (phase === 'prepare') {
      await session.request({ phase: 'start', jobId: 'restored', preparationId: jobId, directCommitted: true })
    }
    const adoptedId = session.state().jobId
    await session.request({ phase: 'update', jobId: adoptedId, document: { root: node('播') } })
    await session.request({ phase: 'start', jobId: adoptedId, directCommitted: true })
    await session.request(prepareNew(adoptedId))
    assert.equal(flushCalls, 0)
    assert.equal(session.state().rendered.root.data.text, '播')
  }
})

test('旧任务的清理和提交消息不能清除当前任务', async () => {
  const session = harness()
  await session.request({ phase: 'start', jobId: 'current', directCommitted: true })
  await session.request({ phase: 'clear', jobId: 'old' })
  await session.request({ phase: 'revert', jobId: 'old' })
  await assert.rejects(session.request({ phase: 'direct-committed', jobId: 'old' }), /过期/)
  assert.equal(session.state().jobId, 'current')
  assert.equal(session.commits.length, 0)
})

test('纯移动帧把实际操作节点传给展示层，折叠祖先也能临时展开', async () => {
  const child = { data: { uid: 'child', text: '已有节点' }, children: [] }
  const parent = { data: { uid: 'parent', text: '折叠分支', expand: false }, children: [] }
  const before = { root: { ...node('根'), children: [child, parent] } }
  const after = { root: { ...node('根'), children: [{ ...parent, children: [child] }] } }
  const session = harness()
  session.changeDocument(before)
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  const frame = nextMindmapAiDraftFrame(before, after, { typewriter: true })
  assert.equal(frame.typewriterTarget, undefined, '纯移动不应虚构文字播放')
  await session.request({ phase: 'update', jobId: 'job1', ...frame })
  assert.equal(session.frames[0].frame.change.uid, 'child')
  assert.equal(session.frames[0].frame.change.kind, 'move')
  assert.equal(session.frames[0].frame.document.root.children[0].data.expand, false)
})

test('最终云端文档只作为目标返回，提交失败保持所有权，重试成功后才能解锁', async () => {
  const session = harness()
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  const target = await session.request({ phase: 'authoritative-target', jobId: 'job1' })
  assert.equal(target.document.root.data.text, '最终云端文字')
  assert.equal(session.frames.length, 0)
  assert.equal(session.commits.length, 0)
  await session.request({ phase: 'update', jobId: 'job1', document: target.document })
  session.failCommit(true)
  await assert.rejects(session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken }), /同步尚未完成/)
  session.unlock()
  assert.equal(session.blocked(), true)
  assert.equal(session.state().jobId, 'job1')
  session.failCommit(false)
  await session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken })
  assert.equal(session.commits.at(-1).serverData.contentRevision, 8)
  assert.equal(session.commits.at(-1).allowAiPresentationCommit, true)
  session.unlock()
  assert.equal(session.blocked(), false)
  assert.equal(session.state(), null)
})

test('direct 的 clear/accepted/revert 不能抢先提交全文或回退画布', async () => {
  const session = harness()
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  await session.request({ phase: 'update', jobId: 'job1', document: { root: node('第') } })
  for (const phase of ['clear', 'accepted', 'revert']) {
    await assert.rejects(session.request({ phase, jobId: 'job1' }), /AI 云端编辑/)
  }
  assert.equal(session.state().rendered.root.data.text, '第')
  assert.equal(session.commits.length, 0)
  assert.equal(session.blocked(), true)
})

test('终态必须使用当前目标回执且目标已播完，不能凭终态消息跳过队列', async () => {
  const session = harness()
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  await assert.rejects(session.request({ phase: 'direct-committed', jobId: 'job1' }), /尚未完整显示/)
  const oldTarget = await session.request({ phase: 'authoritative-target', jobId: 'job1' })
  const target = await session.request({ phase: 'authoritative-target', jobId: 'job1' })
  await assert.rejects(session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken }), /尚未完整显示/)
  await session.request({ phase: 'update', jobId: 'job1', document: target.document })
  await assert.rejects(session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: oldTarget.targetToken }), /尚未完整显示/)
  assert.equal(session.commits.length, 0)
  await session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken })
  assert.equal(session.commits.length, 1)
})

test('最终正文无变化时无需虚构新帧即可校准', async () => {
  const session = harness({ target: async () => ({ data: { nodeTree: node('基线'), contentRevision: 8 } }) })
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  const target = await session.request({ phase: 'authoritative-target', jobId: 'job1' })
  await session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken })
  assert.equal(session.frames.length, 0)
  assert.equal(session.commits.length, 1)
})

test('终态等待临时展开恢复完成后才释放画布', async () => {
  const cleanup = deferred()
  const session = harness({
    clear: options => options?.render === false ? undefined : cleanup.promise,
  })
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  const target = await session.request({ phase: 'authoritative-target', jobId: 'job1' })
  await session.request({ phase: 'update', jobId: 'job1', document: target.document })
  const committed = session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(session.state().committing, true)
  session.unlock()
  assert.equal(session.blocked(), true)
  cleanup.resolve()
  await committed
  session.unlock()
  assert.equal(session.state(), null)
  assert.equal(session.blocked(), false)
})

test('恢复折叠状态失败保留会话，可重试完成校准', async () => {
  let failClear = true
  const session = harness({ clear: options => {
    if (options?.render !== false && failClear) throw new Error('恢复折叠失败')
  } })
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  const target = await session.request({ phase: 'authoritative-target', jobId: 'job1' })
  await session.request({ phase: 'update', jobId: 'job1', document: target.document })
  await assert.rejects(session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken }), /恢复折叠失败/)
  session.unlock()
  assert.equal(session.state().jobId, 'job1')
  assert.equal(session.state().committing, false)
  assert.equal(session.blocked(), true)
  failClear = false
  await session.request({ phase: 'direct-committed', jobId: 'job1', targetToken: target.targetToken })
  assert.equal(session.state(), null)
})

test('旧会话迟到的折叠恢复回调不能释放后继会话', async () => {
  const cleanup = deferred()
  const session = harness({ clear: options => options?.render === false ? undefined : cleanup.promise })
  await session.request({ phase: 'start', jobId: 'old', directCommitted: true })
  const target = await session.request({ phase: 'authoritative-target', jobId: 'old' })
  await session.request({ phase: 'update', jobId: 'old', document: target.document })
  const committed = session.request({ phase: 'direct-committed', jobId: 'old', targetToken: target.targetToken })
  const rejected = assert.rejects(committed, /已过期/)
  await new Promise(resolve => setImmediate(resolve))
  await session.request({ phase: 'detach', jobId: 'old', reason: 'session-ended' })
  await session.request({ phase: 'start', jobId: 'new', directCommitted: true })
  cleanup.resolve()
  await rejected
  assert.equal(session.state().jobId, 'new')
  assert.equal(session.blocked(), true)
})

test('准备态只有明确确认任务不存在才可释放，校准失败保持可重试所有权', async () => {
  const session = harness()
  await session.request({ phase: 'prepare', jobId: 'preparing:1', directCommitted: true })
  await assert.rejects(session.request({ phase: 'clear', jobId: 'preparing:1' }), /AI 云端编辑/)
  await assert.rejects(session.request({ phase: 'preparation-aborted', jobId: 'preparing:1' }), /必须确认/)
  session.failCommit(true)
  await assert.rejects(session.request({ phase: 'preparation-aborted', jobId: 'preparing:1', notCreated: true }), /同步尚未完成/)
  session.unlock()
  assert.equal(session.state().preparing, true)
  assert.equal(session.state().committing, false)
  assert.equal(session.blocked(), true)
  session.failCommit(false)
  await session.request({ phase: 'preparation-aborted', jobId: 'preparing:1', notCreated: true })
  session.unlock()
  assert.equal(session.state(), null)
  assert.equal(session.blocked(), false)
})

test('已采用的准备会话不能再按未创建任务释放', async () => {
  const session = harness()
  await session.request({ phase: 'prepare', jobId: 'preparing:1', directCommitted: true })
  await session.request({ phase: 'start', jobId: 'job1', preparationId: 'preparing:1', directCommitted: true })
  await assert.rejects(session.request({ phase: 'preparation-aborted', jobId: 'job1', notCreated: true }), /必须确认/)
  assert.equal(session.commits.length, 0)
})

test('历史预览或导入已占有画布时不能开始 AI 准备或恢复会话', async () => {
  const session = harness({ transition: () => true })
  for (const phase of ['prepare', 'start']) {
    await assert.rejects(session.request({ phase, jobId: 'job1', directCommitted: true }), /历史预览或文档切换/)
  }
  assert.equal(session.state(), null)
  assert.equal(session.commits.length, 0)
})

test('准备握手被历史预览或未挂载编辑器拒绝后，可无副作用地清理未创建请求', async () => {
  for (const hooks of [{ transition: () => true }, { ready: false }]) {
    let reads = 0
    const session = harness({ ...hooks, target: () => { reads += 1; throw new Error('不应回源') } })
    await assert.rejects(session.request({ phase: 'prepare', jobId: 'preparing:1', directCommitted: true }), /历史预览或文档切换|尚未就绪/)
    const result = await session.request({ phase: 'preparation-aborted', jobId: 'preparing:1', notCreated: true })
    assert.equal(result.cleared, true)
    assert.equal(session.state(), null)
    assert.equal(session.frames.length, 0)
    assert.equal(session.commits.length, 0)
    assert.equal(reads, 0)
  }
})

test('未持有准备会话的清理消息不能释放另一个已存在的会话', async () => {
  const session = harness()
  await session.request({ phase: 'start', jobId: 'current', directCommitted: true })
  await assert.rejects(session.request({ phase: 'preparation-aborted', jobId: 'preparing:old', notCreated: true }), /过期/)
  assert.equal(session.state().jobId, 'current')
  assert.equal(session.blocked(), true)
  assert.equal(session.commits.length, 0)
})

test('并发目标回源只能接受最新请求，迟到响应不能替换提交回执', async () => {
  const first = deferred()
  let reads = 0
  const session = harness({ target: () => ++reads === 1 ? first.promise : Promise.resolve({ data: { nodeTree: node('最新'), contentRevision: 9 } }) })
  await session.request({ phase: 'start', jobId: 'job1', directCommitted: true })
  const oldRequest = session.request({ phase: 'authoritative-target', jobId: 'job1' })
  const rejected = assert.rejects(oldRequest, /替代/)
  const latest = await session.request({ phase: 'authoritative-target', jobId: 'job1' })
  first.resolve({ data: { nodeTree: node('旧文'), contentRevision: 8 } })
  await rejected
  assert.equal(session.state().targetToken, latest.targetToken)
  assert.equal(session.state().commitServerData.contentRevision, 9)
})

test('插件准备阶段发生 detach 后，旧目标不能再返回成功回执', async () => {
  const preparation = deferred()
  const started = deferred()
  const session = harness({ prepare: () => { started.resolve(); return preparation.promise } })
  await session.request({ phase: 'start', jobId: 'old', directCommitted: true })
  const pending = session.request({ phase: 'authoritative-target', jobId: 'old' })
  const rejected = assert.rejects(pending, /过期/)
  await started.promise
  await session.request({ phase: 'detach', jobId: 'old', reason: 'session-ended' })
  await session.request({ phase: 'start', jobId: 'new', directCommitted: true })
  preparation.resolve()
  await rejected
  assert.equal(session.state().jobId, 'new')
  assert.equal(session.state().targetToken, null)
})

test('旧渲染和旧提交的异步完成不能覆盖或释放新会话', async () => {
  for (const operation of ['frame', 'commit']) {
    const waiting = deferred()
    const entered = deferred()
    const session = harness({ [operation]: () => { entered.resolve(); return waiting.promise } })
    await session.request({ phase: 'start', jobId: 'old', directCommitted: true })
    let payload = { phase: 'update', jobId: 'old', document: { root: node('旧') } }
    if (operation === 'commit') {
      const target = await session.request({ phase: 'authoritative-target', jobId: 'old' })
      await session.request({ phase: 'update', jobId: 'old', document: target.document })
      payload = { phase: 'direct-committed', jobId: 'old', targetToken: target.targetToken }
    }
    const pending = session.request(payload)
    const rejected = assert.rejects(pending, /过期/)
    await entered.promise
    await session.request({ phase: 'detach', jobId: 'old', reason: 'session-ended' })
    session.unlock('old')
    assert.equal(session.blocked(), true, 'account teardown must not expose an editable old canvas')
    await session.request({ phase: 'start', jobId: 'new', directCommitted: true })
    waiting.resolve(true)
    await rejected
    assert.equal(session.state().jobId, 'new')
    assert.equal(session.state().rendered.root.data.text, '基线')
    assert.equal(session.blocked(), true)
  }
})

test('非 direct 异步清理期间延后解锁，成功后兑现无需新的 watcher 通知', async () => {
  for (const phase of ['accepted', 'clear']) {
    const cleanup = deferred()
    const session = harness({ clear: options => options?.render === false ? undefined : cleanup.promise })
    await session.request({ phase: 'start', jobId: 'proposal', directCommitted: false })
    const pending = session.request({ phase, jobId: 'proposal' })
    session.unlock('proposal')
    assert.equal(session.blocked(), true)
    assert.equal(session.state().committing, true)
    await assert.rejects(session.request({ phase: 'update', jobId: 'proposal', document: { root: node('迟到帧') } }), /不能接收/)
    await assert.rejects(session.request({ phase, jobId: 'proposal' }), /仍在收尾/)
    cleanup.resolve()
    await pending
    assert.equal(session.state(), null)
    assert.equal(session.blocked(), false)
  }
})

test('非 direct 清理收到新的 locked true 会撤销先前延迟解锁', async () => {
  const cleanup = deferred()
  const session = harness({ clear: options => options?.render === false ? undefined : cleanup.promise })
  await session.request({ phase: 'start', jobId: 'proposal', directCommitted: false })
  const pending = session.request({ phase: 'accepted', jobId: 'proposal' })
  session.unlock('proposal')
  session.lock('proposal')
  cleanup.resolve()
  await pending
  assert.equal(session.state(), null)
  assert.equal(session.blocked(), true)
  session.unlock('proposal')
  assert.equal(session.blocked(), false)
})

test('非 direct 清理失败后保持只读，显式重试成功才兑现待处理解锁', async () => {
  const cleanup = deferred()
  let fail = true
  const session = harness({ clear: options => options?.render === false || !fail ? undefined : cleanup.promise })
  await session.request({ phase: 'start', jobId: 'proposal', directCommitted: false })
  const pending = session.request({ phase: 'clear', jobId: 'proposal' })
  const rejected = assert.rejects(pending, /恢复折叠失败/)
  session.unlock('proposal')
  cleanup.reject(new Error('恢复折叠失败'))
  await rejected
  session.unlock('proposal')
  assert.equal(session.blocked(), true)
  assert.equal(session.state().clearing, true)
  assert.equal(session.state().committing, false)
  assert.match(session.warnings[0].message, /已保持只读.*刷新页面/)
  fail = false
  await session.request({ phase: 'clear', jobId: 'proposal' })
  assert.equal(session.state(), null)
  assert.equal(session.blocked(), false)
})

test('旧非 direct 清理完成不能解锁或清除后继会话', async () => {
  const cleanup = deferred()
  const session = harness({ clear: options => options?.render === false ? undefined : cleanup.promise })
  await session.request({ phase: 'start', jobId: 'old', directCommitted: false })
  const pending = session.request({ phase: 'accepted', jobId: 'old' })
  const rejected = assert.rejects(pending, /已过期/)
  session.unlock('old')
  await session.request({ phase: 'detach', jobId: 'old', reason: 'session-ended' })
  await session.request({ phase: 'start', jobId: 'new', directCommitted: false })
  cleanup.resolve()
  await rejected
  assert.equal(session.state().jobId, 'new')
  assert.equal(session.state().committing, false)
  assert.equal(session.blocked(), true)
  assert.equal(session.warnings.length, 0, '旧清理异常不提示到后继会话')
})

test('已解锁的非 direct 会话清理只临时加锁，不依赖额外解锁消息', async () => {
  const cleanup = deferred()
  const session = harness({ clear: options => options?.render === false ? undefined : cleanup.promise })
  await session.request({ phase: 'start', jobId: 'proposal', directCommitted: false })
  session.unlock('proposal')
  assert.equal(session.blocked(), false)
  const pending = session.request({ phase: 'clear', jobId: 'proposal' })
  assert.equal(session.blocked(), true)
  cleanup.resolve()
  await pending
  assert.equal(session.blocked(), false)
})
