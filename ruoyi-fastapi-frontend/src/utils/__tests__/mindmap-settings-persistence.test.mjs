import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  createMindmapLocalConfigRecord,
  createMindmapRuntimeConfigRecord,
  normalizeMindmapLocalConfigPatch,
  normalizeMindmapLocalConfigRecord,
  normalizeMindmapRuntimeConfigRecord,
} from '../mindmap-local-config.js'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)
const viewRoot = new URL('../../views/mindmap/', import.meta.url)

test('设置页把交互偏好保存在本机，把展示设置提交给文档状态机', async () => {
  const source = await readFile(new URL('Setting.vue', componentRoot), 'utf8')

  assert.match(source, /actions\.storeConfig\(\{ \[prop\]: config\[prop\] \}\)/)
  assert.match(source, /emit\('document-config-change', \{ \[prop\]: config\[prop\] \}\)/)
  assert.match(source, /emit\('document-config-change', \{ watermarkConfig: wmConfig \}\)/)
  assert.doesNotMatch(source, /v-model="localConfig\.useLeftKeySelectionRightKeyDrag"/)
  assert.match(source, /aria-label="显示水印"/)
  assert.match(source, /当前文件为只读状态，水印和间距等文件展示设置不可修改/)
  assert.equal((source.match(/:disabled="isReadonly"/g) || []).length >= 8, true)
  assert.match(source, /@media screen and \(max-width: 520px\)/)
})

test('编辑器将 documentData 纳入草稿、自动保存、冲突快照和 Yjs 元数据', async () => {
  const [source, mutationSource] = await Promise.all([
    readFile(new URL('Edit.vue', componentRoot), 'utf8'),
    readFile(new URL('../mindmap-save-mutation.js', import.meta.url), 'utf8'),
  ])

  assert.match(source, /function getCurrentDocument\(\)/)
  assert.match(source, /documentData: normalizeMindmapDocumentData\(documentData\.value\)/)
  assert.match(source, /document: fullData/)
  assert.match(mutationSource, /documentData: frozenDocument\.documentData/)
  assert.match(source, /getDocumentData: \(\) => normalizeMindmapDocumentData\(documentData\.value\)/)
  assert.match(source, /onDocumentMetaChange\(\{ documentData: documentData\.value \}\)/)
  assert.match(source, /applyMindmapDocumentConfig\(mindMap\.value, documentData\.value\)/)
  assert.match(source, /shouldZoomMindmapWheel\(e, mm\.opt\)/)
})

test('公开分享应用与编辑器一致的文档展示设置', async () => {
  const shareView = await readFile(new URL('view.vue', viewRoot), 'utf8')

  assert.match(shareView, /getMindmapDocumentConfig/)
  assert.match(shareView, /applyMindmapDocumentConfig/)
})

test('布局和主题元数据由编辑器按文件类型统一持久化', async () => {
  const [editor, inspector, structure, theme, baseStyle] = await Promise.all([
    readFile(new URL('Edit.vue', componentRoot), 'utf8'),
    readFile(new URL('PropertyInspector.vue', componentRoot), 'utf8'),
    readFile(new URL('Structure.vue', componentRoot), 'utf8'),
    readFile(new URL('Theme.vue', componentRoot), 'utf8'),
    readFile(new URL('BaseStyle.vue', componentRoot), 'utf8'),
  ])

  for (const source of [structure, theme, baseStyle]) {
    assert.match(source, /defineEmits\(\['document-meta-change'\]\)/)
    assert.match(source, /emit\('document-meta-change', \{/)
    assert.doesNotMatch(source, /actions\.storeData\(/)
  }
  assert.equal(
    (editor.match(/@document-meta-change="onDocumentMetaChange"/g) || []).length,
    1,
  )
  assert.equal(
    (inspector.match(/@document-meta-change="handleDocumentMetaChange\('(canvas|theme)', \$event\)"/g) || []).length,
    3,
  )
  assert.match(inspector, /function handleDocumentMetaChange\(scope, payload\)[\s\S]*emit\('document-meta-change', payload\)/)
  assert.match(editor, /function onDocumentMetaChange\(patch\)/)
  assert.match(editor, /normalizedPatch = normalizeMindmapDocumentMetaPatch\(patch\)/)
  assert.match(editor, /if \(!props\.mindmapId\) \{\s*persistLocalWorkspace\(normalizedPatch\)\s*return/)
  assert.match(editor, /recordDocumentOperations\(current\)/)
  assert.match(editor, /scheduleYjsMetaSync\(normalizedPatch\)/)
  assert.match(editor, /scheduleLocalDraftPersist\(\)/)
  assert.match(editor, /autoSaveTimer = setTimeout\(\(\) => saveToBackend\(\), AUTO_SAVE_DELAY\)/)
  assert.match(baseStyle, /const currentConfig = \{ \.\.\.\(props\.mindMap\.getCustomThemeConfig\(\) \|\| \{\}\) \}/)
  assert.match(baseStyle, /currentConfig\[marginActiveTab\.value\] = \{\s*\.\.\.\(currentConfig\[marginActiveTab\.value\] \|\| \{\}\),\s*\[type\]: value/)
  assert.match(editor, /function flushPendingYjsMetaSync\(\)/)
  assert.match(editor, /async function saveToBackend\(\)[\s\S]*?flushPendingYjsMetaSync\(\)[\s\S]*?if \(conflictBlocked\)/)
  assert.match(editor, /\|\| documentMetaBuffer\.hasPending\(\)/)
})

test('鼠标操作模式的显式 false 使用版本记录持久化而不会被重复迁移', () => {
  const record = createMindmapLocalConfigRecord({
    useLeftKeySelectionRightKeyDrag: false,
  })

  assert.deepEqual(record, {
    schemaVersion: 1,
    values: { useLeftKeySelectionRightKeyDrag: false },
  })
  assert.equal(
    normalizeMindmapLocalConfigRecord(record).useLeftKeySelectionRightKeyDrag,
    false,
  )
  assert.equal(
    normalizeMindmapLocalConfigRecord({
      useLeftKeySelectionRightKeyDrag: false,
    }).useLeftKeySelectionRightKeyDrag,
    false,
  )
})

test('只有可识别的旧版完整默认快照迁移鼠标模式旧默认值', () => {
  const migrated = normalizeMindmapLocalConfigRecord({
    isDark: false,
    isZenMode: false,
    openNodeRichText: true,
    isShowScrollbar: false,
    useLeftKeySelectionRightKeyDrag: false,
    enableAi: false,
  })

  assert.equal(migrated.useLeftKeySelectionRightKeyDrag, true)
  assert.equal(migrated.openNodeRichText, true)
})

test('本地脑图偏好只接受已知布尔值并忽略损坏或危险字段', () => {
  const patch = normalizeMindmapLocalConfigPatch(JSON.parse(`{
    "isDark": true,
    "isZenMode": "true",
    "unknown": true,
    "__proto__": { "polluted": true }
  }`))

  assert.deepEqual(patch, { isDark: true })
  assert.equal({}.polluted, undefined)
  assert.deepEqual(normalizeMindmapLocalConfigRecord(null), {
    isDark: false,
    isZenMode: false,
    openNodeRichText: true,
    isShowScrollbar: false,
    useLeftKeySelectionRightKeyDrag: true,
    enableAi: false,
  })
})

test('状态层刷新恢复显式鼠标模式并清理不可解析的本地记录', async () => {
  const hadLocalStorage = Object.prototype.hasOwnProperty.call(globalThis, 'localStorage')
  const previousLocalStorage = globalThis.localStorage
  let stored = JSON.stringify({
    schemaVersion: 1,
    values: { useLeftKeySelectionRightKeyDrag: false },
  })
  globalThis.localStorage = {
    getItem: () => stored,
    setItem: (_key, value) => { stored = String(value) },
    removeItem: () => { stored = null },
  }

  try {
    const moduleUrl = new URL('../../components/MindMap/useStore.js', import.meta.url)
    moduleUrl.searchParams.set('local-config-test', String(Date.now()))
    const { actions, store } = await import(moduleUrl.href)

    actions.initLocalConfig()
    assert.equal(store.localConfig.useLeftKeySelectionRightKeyDrag, false)
    assert.deepEqual(JSON.parse(stored), {
      schemaVersion: 1,
      values: { useLeftKeySelectionRightKeyDrag: false },
    })

    stored = '{invalid-json'
    actions.initLocalConfig()
    assert.equal(store.localConfig.useLeftKeySelectionRightKeyDrag, true)
    assert.equal(stored, null)
  } finally {
    if (hadLocalStorage) globalThis.localStorage = previousLocalStorage
    else delete globalThis.localStorage
  }
})

test('运行时偏好记录只保留设置页支持的有界配置', () => {
  const record = createMindmapRuntimeConfigRecord({
    openPerformance: true,
    mousewheelAction: 'move',
    createNewNodeBehavior: 'activeOnly',
    outerFramePaddingX: 500,
    rainbowLinesConfig: {
      open: true,
      colorsList: ['rgb(255, 1, 2)', 'url(javascript:alert(1))'],
    },
    watermarkConfig: { text: '不能泄漏到其他文件' },
    readonly: false,
    data: { injected: true },
  })

  assert.deepEqual(record, {
    schemaVersion: 1,
    values: {
      openPerformance: true,
      mousewheelAction: 'move',
      createNewNodeBehavior: 'activeOnly',
      outerFramePaddingX: 100,
      rainbowLinesConfig: {
        open: true,
        colorsList: ['rgb(255, 1, 2)'],
      },
    },
  })
  assert.deepEqual(normalizeMindmapRuntimeConfigRecord(record), record.values)
})

test('状态层从损坏运行时记录恢复后仍能保存合法偏好', async () => {
  const hadLocalStorage = Object.prototype.hasOwnProperty.call(globalThis, 'localStorage')
  const previousLocalStorage = globalThis.localStorage
  const storage = new Map([['MIND_MAP_CONFIG', '["invalid-shape"]']])
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  }

  try {
    const moduleUrl = new URL('../../components/MindMap/useStore.js', import.meta.url)
    moduleUrl.searchParams.set('runtime-config-test', String(Date.now()))
    const { actions } = await import(moduleUrl.href)

    assert.deepEqual(actions.getConfig(), {})
    actions.storeConfig({ openPerformance: true, readonly: false })
    assert.deepEqual(actions.getConfig(), { openPerformance: true })
    assert.deepEqual(JSON.parse(storage.get('MIND_MAP_CONFIG')), {
      schemaVersion: 1,
      values: { openPerformance: true },
    })

    storage.set('MIND_MAP_CONFIG', '{invalid-json')
    assert.deepEqual(actions.getConfig(), {})
    assert.equal(storage.has('MIND_MAP_CONFIG'), false)
  } finally {
    if (hadLocalStorage) globalThis.localStorage = previousLocalStorage
    else delete globalThis.localStorage
  }
})
