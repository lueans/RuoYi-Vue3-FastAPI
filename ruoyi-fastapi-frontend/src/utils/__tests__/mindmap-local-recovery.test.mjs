import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  areMindmapDraftDocumentsEqual,
  createMindmapDraftKey,
  getMindmapDraft,
  getMindmapDraftDisplayName,
  getMindmapDraftSourceLabel,
  isMindmapDraftSessionActive,
  listMindmapDrafts,
  removeInactiveMindmapDrafts,
  removeMindmapDraft,
  saveMindmapDraft,
  saveMindmapDraftFallbackSync,
  startMindmapDraftSessionLease,
  stableSerialize,
} from '../mindmap-draft.js'
import {
  createMindmapBackupFileName,
  downloadMindmapBackup,
  serializeMindmapBackup,
} from '../mindmap-backup.js'

class MemoryStorage {
  constructor() {
    this.values = new Map()
  }

  get length() {
    return this.values.size
  }

  key(index) {
    return [...this.values.keys()][index] ?? null
  }

  getItem(key) {
    return this.values.get(key) ?? null
  }

  setItem(key, value) {
    this.values.set(key, String(value))
  }

  removeItem(key) {
    this.values.delete(key)
  }
}

class MemoryLockManager {
  constructor() {
    this.held = []
  }

  async request(name, callback) {
    const lock = { name }
    this.held.push(lock)
    try {
      return await callback(lock)
    } finally {
      this.held = this.held.filter(item => item !== lock)
    }
  }

  async query() {
    return { held: [...this.held], pending: [] }
  }
}

test('纯平移缩放差异不形成正文恢复草稿', () => {
  const base = {
    root: { data: { uid: 'root', text: '正文' }, children: [] },
    layout: 'logicalStructure',
    theme: { template: 'default' },
    view: { transform: { scaleX: 1, translateX: 0 } },
    documentData: {},
  }
  assert.equal(areMindmapDraftDocumentsEqual(base, {
    ...base,
    view: { transform: { scaleX: 1.5, translateX: -300 } },
  }), true)
  assert.equal(areMindmapDraftDocumentsEqual(base, {
    ...base,
    root: { data: { uid: 'root', text: '正文已修改' }, children: [] },
  }), false)
})

test('活跃编辑窗口锁不受过期租约影响，停止后立即释放', async () => {
  const previousStorage = globalThis.localStorage
  globalThis.localStorage = new MemoryStorage()
  const lockManager = new MemoryLockManager()
  let heartbeat
  let clearedTimer
  try {
    const stop = startMindmapDraftSessionLease(7, 127, 'window-a', {
      ttlMs: 10,
      lockManager,
      setIntervalFn: callback => {
        heartbeat = callback
        return 91
      },
      clearIntervalFn: timer => { clearedTimer = timer },
    })
    assert.equal(await isMindmapDraftSessionActive(7, 127, 'window-a', {
      now: Date.now() + 60_000,
      lockManager,
    }), true)
    heartbeat()
    assert.equal(await isMindmapDraftSessionActive(7, 127, 'window-a', {
      lockManager,
    }), true)
    stop()
    await Promise.resolve()
    await Promise.resolve()
    assert.equal(clearedTimer, 91)
    assert.equal(await isMindmapDraftSessionActive(7, 127, 'window-a', {
      now: Date.now() + 60_000,
      lockManager,
    }), false)
  } finally {
    globalThis.localStorage = previousStorage
  }
})

test('本地草稿列表按用户隔离、去除富文本标题并按时间倒序', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  try {
    assert.equal(saveMindmapDraftFallbackSync({
      userId: 7,
      mindmapId: 101,
      contentRevision: 3,
      updatedAt: 100,
      document: { root: { data: { text: '<b>第一份 草稿</b>' }, children: [] } },
    }), true)
    assert.equal(saveMindmapDraftFallbackSync({
      userId: 7,
      mindmapId: 102,
      contentRevision: 4,
      updatedAt: 200,
      document: { root: { data: { text: '第二份草稿' }, children: [] } },
    }), true)
    saveMindmapDraftFallbackSync({
      userId: 8,
      mindmapId: 103,
      updatedAt: 300,
      document: { root: { data: { text: '其他用户' }, children: [] } },
    })

    const drafts = await listMindmapDrafts(7)
    assert.deepEqual(drafts.map(item => item.mindmapId), ['102', '101'])
    assert.equal(drafts[1].name, '第一份 草稿')
    assert.equal(getMindmapDraftDisplayName(drafts[0]), '第二份草稿')

    await removeMindmapDraft(7, 102)
    assert.deepEqual((await listMindmapDrafts(7)).map(item => item.mindmapId), ['101'])
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('同一脑图的多个编辑窗口使用独立草稿并可精确恢复删除', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  try {
    await saveMindmapDraft({
      userId: 7,
      mindmapId: 107,
      sessionId: 'window-a',
      contentRevision: 3,
      updatedAt: 400,
      document: { root: { data: { text: '窗口 A' }, children: [] } },
    })
    await saveMindmapDraft({
      userId: 7,
      mindmapId: 107,
      sessionId: 'window-b',
      contentRevision: 3,
      updatedAt: 500,
      document: { root: { data: { text: '窗口 B' }, children: [] } },
    })

    const drafts = await listMindmapDrafts(7)
    assert.deepEqual(drafts.map(item => item.name), ['窗口 B', '窗口 A'])
    assert.match(getMindmapDraftSourceLabel(drafts[0]), /^编辑窗口 [A-Z0-9]{6}$/)
    assert.notEqual(
      getMindmapDraftSourceLabel(drafts[0]),
      getMindmapDraftSourceLabel(drafts[1]),
    )
    assert.equal(getMindmapDraftSourceLabel({}), '兼容草稿')
    assert.equal((await getMindmapDraft(7, 107)).name, '窗口 B')
    const windowAKey = createMindmapDraftKey(7, 107, 'window-a')
    assert.equal((await getMindmapDraft(7, 107, { key: windowAKey })).name, '窗口 A')

    await removeMindmapDraft(7, 107, { key: windowAKey })
    assert.deepEqual((await listMindmapDrafts(7)).map(item => item.name), ['窗口 B'])
    await assert.rejects(
      removeMindmapDraft(7, 107, { key: createMindmapDraftKey(8, 107, 'window-c') }),
      /不匹配/,
    )
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('云端退出清理同一脑图的旧窗口草稿但保留清理期间的新草稿', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  try {
    await saveMindmapDraft({
      userId: 7,
      mindmapId: 108,
      sessionId: 'old-window-a',
      contentRevision: 3,
      updatedAt: 100,
      document: { root: { data: { text: '旧窗口 A' }, children: [] } },
    })
    await saveMindmapDraft({
      userId: 7,
      mindmapId: 108,
      sessionId: 'old-window-b',
      contentRevision: 3,
      updatedAt: 120,
      document: { root: { data: { text: '旧窗口 B' }, children: [] } },
    })
    await saveMindmapDraft({
      userId: 7,
      mindmapId: 108,
      sessionId: 'new-window',
      contentRevision: 4,
      updatedAt: 160,
      document: { root: { data: { text: '清理期间的新草稿' }, children: [] } },
    })

    await removeMindmapDraft(7, 108, { beforeUpdatedAt: 150 })

    const drafts = await listMindmapDrafts(7)
    assert.deepEqual(drafts.map(item => item.name), ['清理期间的新草稿'])
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('使用云端版本只删除失活草稿并保护仍在编辑的其他窗口', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  let stopActiveSession
  try {
    await saveMindmapDraft({
      userId: 7,
      mindmapId: 127,
      sessionId: 'active-window',
      contentRevision: 3,
      updatedAt: 100,
      document: { root: { data: { text: '仍在编辑' }, children: [] } },
    })
    await saveMindmapDraft({
      userId: 7,
      mindmapId: 127,
      sessionId: 'crashed-window',
      contentRevision: 3,
      updatedAt: 200,
      document: { root: { data: { text: '崩溃草稿' }, children: [] } },
    })
    stopActiveSession = startMindmapDraftSessionLease(7, 127, 'active-window', {
      lockManager: {},
      setIntervalFn: () => 92,
      clearIntervalFn: () => {},
    })

    const result = await removeInactiveMindmapDrafts(7, 127, { beforeUpdatedAt: 200 })
    const drafts = await listMindmapDrafts(7)

    assert.deepEqual(drafts.map(item => item.name), ['仍在编辑'])
    assert.deepEqual(result.preservedKeys, [createMindmapDraftKey(7, 127, 'active-window')])
    assert.deepEqual(result.removedKeys, [createMindmapDraftKey(7, 127, 'crashed-window')])
  } finally {
    stopActiveSession?.()
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('备份文件名拒绝路径字符且序列化只接受脑图对象', () => {
  assert.equal(
    createMindmapBackupFileName({ prefix: '../冲突:副本', mindmapId: '1/2', timestamp: 42 }),
    '冲突-副本-1-2-42.json',
  )
  const serialized = serializeMindmapBackup({ root: { data: { text: '安全备份' } } })
  assert.match(serialized, /\n  "root": \{/)
  assert.equal(JSON.parse(serialized).root.data.text, '安全备份')
  assert.throws(() => serializeMindmapBackup([]), /备份内容无效/)
})

test('深层草稿复制、localStorage 回退和发布上限内的可读备份不依赖原生递归序列化', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  try {
    const root = { data: { text: '深层草稿' } }
    let current = root
    for (let depth = 1; depth < 20_000; depth += 1) {
      current.child = { data: { text: String(depth) } }
      current = current.child
    }
    assert.equal(saveMindmapDraftFallbackSync({
      userId: 7,
      mindmapId: 120,
      document: { root },
    }), true)
    const [draft] = await listMindmapDrafts(7)
    assert.equal(draft.document.root.data.text, '深层草稿')

    const backupRoot = { data: { text: '根' } }
    current = backupRoot
    for (let depth = 1; depth < 256; depth += 1) {
      current.child = { data: { text: String(depth) } }
      current = current.child
    }
    const backup = serializeMindmapBackup({ root: backupRoot })
    assert.equal(JSON.parse(backup).root.data.text, '根')
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('备份下载延迟释放 Blob URL 并报告是否成功启动', () => {
  const previousDocument = globalThis.document
  const previousCreateObjectUrl = URL.createObjectURL
  const previousRevokeObjectUrl = URL.revokeObjectURL
  const previousSetTimeout = globalThis.setTimeout
  const actions = []
  URL.createObjectURL = () => 'blob:mindmap-backup'
  URL.revokeObjectURL = value => actions.push(`revoke:${value}`)
  globalThis.setTimeout = callback => {
    actions.push('scheduled')
    callback()
    return 1
  }
  globalThis.document = {
    body: { appendChild: () => actions.push('append') },
    createElement: () => ({
      click: () => actions.push('click'),
      remove: () => actions.push('remove'),
    }),
  }
  try {
    assert.equal(downloadMindmapBackup(
      { root: { data: { text: '草稿' } } },
      { prefix: 'local', mindmapId: 9, timestamp: 10 },
    ), true)
    assert.deepEqual(actions, [
      'append',
      'click',
      'remove',
      'scheduled',
      'revoke:blob:mindmap-backup',
    ])
  } finally {
    globalThis.document = previousDocument
    URL.createObjectURL = previousCreateObjectUrl
    URL.revokeObjectURL = previousRevokeObjectUrl
    globalThis.setTimeout = previousSetTimeout
  }
})

test('IndexedDB 打开悬挂时限时回退到 localStorage', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  const previousSetTimeout = globalThis.setTimeout
  const previousClearTimeout = globalThis.clearTimeout
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = { open: () => ({}) }
  globalThis.setTimeout = callback => {
    queueMicrotask(callback)
    return 1
  }
  globalThis.clearTimeout = () => {}
  try {
    const result = await saveMindmapDraft({
      userId: 7,
      mindmapId: 104,
      contentRevision: 5,
      document: { root: { data: { text: '超时回退' }, children: [] } },
    })
    assert.deepEqual(result, { saved: true, storage: 'localStorage' })
    assert.equal((await listMindmapDrafts(7))[0].name, '超时回退')
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
    globalThis.setTimeout = previousSetTimeout
    globalThis.clearTimeout = previousClearTimeout
  }
})

test('IndexedDB 不可用且草稿超过回退容量时明确报告保存失败', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  try {
    const result = await saveMindmapDraft({
      userId: 7,
      mindmapId: 108,
      contentRevision: 1,
      document: {
        root: {
          data: { text: 'x'.repeat(2 * 1024 * 1024) },
          children: [],
        },
      },
    })

    assert.deepEqual(result, { saved: false, storage: null })
    assert.deepEqual(await listMindmapDrafts(7), [])
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('迟到的旧草稿写入和条件清理不会覆盖更新的同步恢复副本', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  try {
    saveMindmapDraftFallbackSync({
      userId: 7,
      mindmapId: 105,
      contentRevision: 8,
      updatedAt: 200,
      document: { root: { data: { text: '卸载前的新草稿' }, children: [] } },
    })

    const staleResult = await saveMindmapDraft({
      userId: 7,
      mindmapId: 105,
      contentRevision: 7,
      updatedAt: 100,
      document: { root: { data: { text: '队列中迟到的旧草稿' }, children: [] } },
    })
    assert.equal(staleResult.saved, true)
    assert.equal((await listMindmapDrafts(7))[0].name, '卸载前的新草稿')

    await removeMindmapDraft(7, 105, { beforeUpdatedAt: 150 })
    assert.equal((await listMindmapDrafts(7))[0].name, '卸载前的新草稿')

    await removeMindmapDraft(7, 105, { beforeUpdatedAt: 200 })
    assert.deepEqual(await listMindmapDrafts(7), [])
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('异步草稿保存会冻结调用时文档而不是保留可变引用', async () => {
  const previousStorage = globalThis.localStorage
  const previousIndexedDb = globalThis.indexedDB
  globalThis.localStorage = new MemoryStorage()
  globalThis.indexedDB = undefined
  try {
    const document = {
      root: { data: { text: '调用时内容' }, children: [] },
      documentData: { plugin: { enabled: true } },
    }
    const saving = saveMindmapDraft({
      userId: 7,
      mindmapId: 106,
      contentRevision: 1,
      updatedAt: 300,
      document,
    })
    document.root.data.text = '调用后被修改'
    document.documentData.plugin.enabled = false
    await saving

    const [draft] = await listMindmapDrafts(7)
    assert.equal(draft.document.root.data.text, '调用时内容')
    assert.equal(draft.document.documentData.plugin.enabled, true)
  } finally {
    globalThis.localStorage = previousStorage
    globalThis.indexedDB = previousIndexedDb
  }
})

test('稳定序列化支持深层 JSON 且不受对象键顺序影响', () => {
  assert.equal(
    stableSerialize({ beta: 2, alpha: { delta: 4, gamma: 3 } }),
    stableSerialize({ alpha: { gamma: 3, delta: 4 }, beta: 2 }),
  )
  let deepDocument = { leaf: true }
  for (let depth = 0; depth < 5000; depth += 1) {
    deepDocument = { child: deepDocument }
  }
  assert.doesNotThrow(() => stableSerialize(deepDocument))
  assert.notEqual(stableSerialize({ items: [1, 2] }), stableSerialize({ items: [2, 1] }))
  const cyclicDocument = {}
  cyclicDocument.self = cyclicDocument
  assert.throws(() => stableSerialize(cyclicDocument), /循环引用/)
})

test('编辑器在入队时冻结草稿时间并仅清理保存开始前的版本', async () => {
  const editorSource = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const draftOptionsBlock = editorSource.match(/function createDraftOptions[\s\S]*?\n\}/)?.[0] || ''
  const clearBlock = editorSource.match(/function clearLocalDraft[\s\S]*?\n\}/)?.[0] || ''
  const saveBlock = editorSource.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''

  assert.match(draftOptionsBlock, /updatedAt: nextDraftUpdatedAt\(\)/)
  assert.match(draftOptionsBlock, /sessionId: draftSessionId/)
  assert.match(clearBlock, /removeMindmapDraft\(userId, mindmapId, \{[\s\S]*?beforeUpdatedAt,[\s\S]*?sessionId: draftSessionId/)
  assert.match(saveBlock, /const draftClearBeforeUpdatedAt = nextDraftUpdatedAt\(\)/)
  assert.match(saveBlock, /clearLocalDraft\(draftClearBeforeUpdatedAt\)/)
})

test('草稿中心把指定记录键传给编辑器并只删除该编辑窗口草稿', async () => {
  const [listSource, pageSource, editorSource] = await Promise.all([
    readFile(new URL('../../views/mindmap/index.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
  ])

  assert.match(listSource, /draftKey: draft\.key,[\s\S]*returnList: getListReturnState\(\)/)
  assert.match(listSource, /removeMindmapDraft\(userStore\.id, draft\.mindmapId, \{ key: draft\.key \}\)/)
  assert.match(listSource, /class="local-draft-source"/)
  assert.match(listSource, /下载本地草稿：\$\{draft\.name\}，\$\{getMindmapDraftSourceLabel\(draft\)\}/)
  assert.match(listSource, /继续处理本地草稿：\$\{draft\.name\}，\$\{getMindmapDraftSourceLabel\(draft\)\}/)
  assert.match(listSource, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(pageSource, /:draft-key="requestedDraftKey"/)
  assert.match(pageSource, /nextDraftKey === requestedDraftKey\.value/)
  assert.match(editorSource, /getMindmapDraft\(userStore\.id, props\.mindmapId, \{\s*key: props\.draftKey \|\| undefined/)
  assert.match(editorSource, /clearDraftRecord\(draft\)/)
})

test('明确使用云端版本会让新协作会话替换旧缓存而不是再次合入', async () => {
  const editorSource = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const draftBlock = editorSource.match(
    /async function resolveLocalDraft[\s\S]*?function recordContentOperations/,
  )?.[0] || ''
  const createSyncBlock = editorSource.match(
    /function createYjsSyncInstance[\s\S]*?const isZenMode/,
  )?.[0] || ''
  const conflictBlock = editorSource.match(
    /async function performContentConflictResolution[\s\S]*?async function manualSave/,
  )?.[0] || ''

  const discardBlock = editorSource.match(
    /async function discardLocalDraftsAndUseCloud[\s\S]*?function clearRestoredDraft/,
  )?.[0] || ''

  assert.match(draftBlock, /action === 'cancel'[\s\S]*?await discardLocalDraftsAndUseCloud\(draft\)/)
  assert.match(discardBlock, /removeInactiveMindmapDrafts\(userId, mindmapId, \{\s*beforeUpdatedAt: record\.updatedAt/)
  assert.doesNotMatch(discardBlock, /sessionId:|key:/)
  assert.ok(
    discardBlock.indexOf('await enqueueDraftOperation')
      < discardBlock.indexOf('requestAuthoritativeCollaborationReset()'),
  )
  assert.match(discardBlock, /draftProtection\.markClean\(\)/)
  assert.match(draftBlock, /cancelButtonText: '删除本地草稿并使用云端'/)
  assert.match(createSyncBlock, /preferAuthoritativeDocument/)
  assert.match(conflictBlock, /requestAuthoritativeCollaborationReset\(\)[\s\S]*?onYjsReinit/)
  assert.match(editorSource, /buildMindmapDocumentOperations\(/)
  assert.doesNotMatch(editorSource, /pendingContentOperations\.push\(\{ type: 'document\.update' \}\)/)
})

test('固定脑图导航具备原生键盘语义与清晰焦点样式', async () => {
  const listUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
  const listSource = await readFile(listUrl, 'utf8')
  assert.match(listSource, /<button\s+type="button"\s+class="fixed-tree-node"/)
  assert.match(listSource, /:aria-current=/)
  assert.match(listSource, /&:focus-visible/)
})

test('终止编辑采用同步草稿与 JSON 下载双保险，列表提供恢复中心', async () => {
  const editorUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
  const pageUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
  const listUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
  const [editorSource, pageSource, listSource] = await Promise.all([
    readFile(editorUrl, 'utf8'),
    readFile(pageUrl, 'utf8'),
    readFile(listUrl, 'utf8'),
  ])

  assert.match(editorSource, /localDraftPreserved = saveMindmapDraftFallbackSync/)
  assert.match(editorSource, /localBackupCreated = downloadConflictBackup/)
  assert.match(editorSource, /saveMindmapDraft\(terminalDraftOptions\)/)
  assert.doesNotMatch(
    editorSource.match(/function terminateEditingSession[\s\S]*?async function reloadLatestServerDocument/)?.[0] || '',
    /clearLocalDraft\(\)/,
  )
  assert.match(pageSource, /保留在本地草稿中心/)
  assert.match(listSource, /title="本地草稿中心"/)
  assert.match(listSource, /下载 JSON/)
  assert.match(listSource, /继续处理/)
  assert.match(listSource, /删除本地草稿/)
})

test('终止编辑先提交所有活动编辑器，再备份并立即锁定只读', async () => {
  const editorSource = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const terminateBlock = editorSource.match(
    /function terminateEditingSession[\s\S]*?function commitActiveEditorsBeforeTermination/,
  )?.[0] || ''
  const commitBlock = editorSource.match(
    /function commitActiveEditorsBeforeTermination[\s\S]*?async function reloadLatestServerDocument/,
  )?.[0] || ''

  assert.ok(
    terminateBlock.indexOf('commitActiveEditorsBeforeTermination()')
      < terminateBlock.indexOf('const needsLocalBackup = hasUnsavedChanges()'),
  )
  assert.ok(
    terminateBlock.indexOf('const needsLocalBackup = hasUnsavedChanges()')
      < terminateBlock.indexOf('terminalState = eventName'),
  )
  assert.match(terminateBlock, /actions\.setIsReadonly\(true\)/)
  assert.match(terminateBlock, /mindMap\.value\?\.setMode\?\.\('readonly'\)/)
  assert.match(commitBlock, /bus\.emit\('closeOutlineEdit'\)/)
  assert.match(commitBlock, /mindMap\.value\?\.renderer\?\.textEdit/)
  assert.match(commitBlock, /mindMap\.value\?\.associativeLine/)
  assert.match(commitBlock, /mindMap\.value\?\.outerFrame/)
  assert.match(editorSource, /if \(terminatingSession \|\| isChangeTrackingSuspended\(\)\) return/)
})
