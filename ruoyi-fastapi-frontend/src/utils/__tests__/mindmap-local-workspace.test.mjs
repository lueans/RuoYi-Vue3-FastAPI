import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createMindmapLocalWorkspaceRecord,
  normalizeMindmapDocumentMetaPatch,
  normalizeMindmapLocalWorkspacePatch,
  normalizeMindmapLocalWorkspaceRecord,
  serializeMindmapLocalWorkspaceRecord,
} from '../mindmap-local-workspace.js'

const createRoot = (text = '根节点') => ({
  data: { uid: 'root', text },
  children: [{ data: { uid: 'child', text: '子节点' }, children: [] }],
})

test('旧版本地工作区迁移到版本记录并保留 simple-mind 扩展数据', () => {
  const legacy = JSON.parse(JSON.stringify({
    root: createRoot(),
    layout: 'mindMap',
    theme: {
      template: 'classic',
      config: { lineColor: '#123456', futureThemeField: { enabled: true } },
    },
    view: { state: { scale: 1.25, x: 20, y: -5 } },
    documentData: { simpleMindMap: { config: { imgTextMargin: 8 } } },
  }))

  const normalized = normalizeMindmapLocalWorkspaceRecord(legacy)
  const record = createMindmapLocalWorkspaceRecord(normalized)

  assert.equal(record.schemaVersion, 1)
  assert.equal(record.values.root.children[0].data.text, '子节点')
  assert.equal(record.values.layout, 'mindMap')
  assert.equal(record.values.theme.config.futureThemeField.enabled, true)
  assert.deepEqual(record.values.view.state, {
    scale: 1.25,
    x: 20,
    y: -5,
    sx: 20,
    sy: -5,
  })
  assert.equal(record.values.documentData.simpleMindMap.config.imgTextMargin, 8)
})

test('工作区边界拒绝非法树并过滤布局、视图和危险 JSON 字段', () => {
  assert.throws(
    () => normalizeMindmapLocalWorkspacePatch({
      root: { data: {}, children: [{ data: 'invalid' }] },
    }),
    /data|根节点/,
  )
  assert.throws(
    () => normalizeMindmapLocalWorkspacePatch({ layout: 'unknown-layout' }),
    /布局/,
  )

  const normalized = normalizeMindmapLocalWorkspaceRecord(JSON.parse(`{
    "root": {"data": {"uid": "root", "text": "安全", "__proto__": {"polluted": true}}},
    "layout": "unknown-layout",
    "theme": {"template": "default", "config": {"constructor": {"bad": true}, "ok": 1}},
    "view": {"state": {"scale": 0, "x": "bad", "y": 4}, "transform": {"rotate": 45}},
    "unknown": {"keep": false}
  }`))

  assert.equal(normalized.layout, undefined)
  assert.equal(normalized.root.data.text, '安全')
  assert.equal(Object.hasOwn(normalized.root.data, '__proto__'), false)
  assert.deepEqual(normalized.theme.config, { ok: 1 })
  assert.deepEqual(normalized.view.state, { scale: 1, x: 0, y: 4, sx: 0, sy: 4 })
  assert.equal(Object.hasOwn(normalized, 'unknown'), false)
  assert.equal({}.polluted, undefined)
})

test('服务端与匿名文档共用文件元数据规范化边界', () => {
  const normalized = normalizeMindmapDocumentMetaPatch(JSON.parse(`{
    "layout": "mindMap",
    "theme": {
      "template": "classic",
      "config": {"lineColor": "#123456", "__proto__": {"polluted": true}}
    },
    "view": {"state": {"scale": 1.5, "x": 8, "y": -3}},
    "documentData": {"simpleMindMap": {"config": {"imgTextMargin": 12}}},
    "root": {"data": {"uid": "ignored"}, "children": []},
    "unknown": true
  }`))

  assert.deepEqual(Object.keys(normalized), ['layout', 'theme', 'view', 'documentData'])
  assert.equal(normalized.layout, 'mindMap')
  assert.deepEqual(normalized.theme.config, { lineColor: '#123456' })
  assert.deepEqual(normalized.view.state, {
    scale: 1.5,
    x: 8,
    y: -3,
    sx: 8,
    sy: -3,
  })
  assert.equal(normalized.documentData.simpleMindMap.config.imgTextMargin, 12)
  assert.equal({}.polluted, undefined)
  assert.throws(
    () => normalizeMindmapDocumentMetaPatch({ layout: 'unknown-layout' }),
    /布局/,
  )
  assert.throws(
    () => normalizeMindmapDocumentMetaPatch({ theme: [] }),
    /主题/,
  )
})

test('工作区序列化执行 UTF-8 容量限制且深树不依赖递归 stringify', () => {
  assert.throws(
    () => serializeMindmapLocalWorkspaceRecord({ root: createRoot('中文内容') }, 40),
    error => error?.code === 'MINDMAP_LOCAL_WORKSPACE_TOO_LARGE',
  )

  const root = { data: { uid: 'node-0', text: '0' }, children: [] }
  let current = root
  for (let index = 1; index < 220; index += 1) {
    const child = { data: { uid: `node-${index}`, text: String(index) }, children: [] }
    current.children.push(child)
    current = child
  }
  const serialized = serializeMindmapLocalWorkspaceRecord({ root })
  assert.equal(JSON.parse(serialized).values.root.data.uid, 'node-0')
})

test('状态层从损坏记录恢复、合并部分保存并保留失败前快照', async () => {
  const hadLocalStorage = Object.prototype.hasOwnProperty.call(globalThis, 'localStorage')
  const previousLocalStorage = globalThis.localStorage
  const storage = new Map([['MIND_MAP_DATA', '{invalid-json']])
  let rejectWrites = false
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => {
      if (rejectWrites) throw new Error('quota exceeded')
      storage.set(key, String(value))
    },
    removeItem: key => storage.delete(key),
  }

  try {
    const moduleUrl = new URL('../../components/MindMap/useStore.js', import.meta.url)
    moduleUrl.searchParams.set('local-workspace-test', String(Date.now()))
    const { actions } = await import(moduleUrl.href)

    assert.equal(actions.storeData({ root: createRoot() }), true)
    assert.equal(actions.storeData({ layout: 'mindMap' }), true)
    assert.equal(actions.getData().root.data.text, '根节点')
    assert.equal(actions.getData().layout, 'mindMap')
    assert.deepEqual(JSON.parse(storage.get('MIND_MAP_DATA')).schemaVersion, 1)

    const previous = storage.get('MIND_MAP_DATA')
    assert.equal(actions.storeData({ root: { children: [] } }), false)
    assert.equal(storage.get('MIND_MAP_DATA'), previous)

    const invalidLegacyRoot = JSON.stringify({
      root: { data: 'invalid' },
      layout: 'mindMap',
    })
    storage.set('MIND_MAP_DATA', invalidLegacyRoot)
    assert.equal(actions.getData(), null)
    assert.equal(storage.get('MIND_MAP_DATA'), invalidLegacyRoot)
    assert.equal(actions.storeData({ view: null }), false)
    assert.equal(storage.get('MIND_MAP_DATA'), invalidLegacyRoot)
    assert.equal(actions.storeData({ root: createRoot('安全恢复') }), true)
    assert.equal(actions.getData().root.data.text, '安全恢复')

    const legacy = JSON.stringify({ root: createRoot('只读迁移') })
    storage.set('MIND_MAP_DATA', legacy)
    rejectWrites = true
    assert.equal(actions.getData().root.data.text, '只读迁移')
    assert.equal(storage.get('MIND_MAP_DATA'), legacy)
    rejectWrites = false

    storage.set('MIND_MAP_DATA', JSON.stringify({
      schemaVersion: 99,
      values: { root: createRoot('未来版本') },
    }))
    const futureRecord = storage.get('MIND_MAP_DATA')
    assert.equal(actions.getData(), null)
    assert.equal(actions.storeData({ layout: 'timeline' }), false)
    assert.equal(storage.get('MIND_MAP_DATA'), futureRecord)
  } finally {
    if (hadLocalStorage) globalThis.localStorage = previousLocalStorage
    else delete globalThis.localStorage
  }
})
