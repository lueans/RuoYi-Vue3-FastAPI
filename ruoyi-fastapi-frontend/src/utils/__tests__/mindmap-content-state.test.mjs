import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  getMindmapContentStatePresentation,
  isMindmapContentWritable,
  normalizeMindmapContentState,
} from '../mindmap-content-state.js'

test('缺省内容状态保持可编辑兼容', () => {
  assert.equal(normalizeMindmapContentState(undefined), 'ready')
  assert.equal(isMindmapContentWritable(undefined), true)
})

test('所有保护状态都禁止内容写入', () => {
  for (const state of ['migration_failed', 'integrity_failed', 'load_failed']) {
    assert.equal(isMindmapContentWritable(state), false)
  }
})

test('未知服务端状态按读取失败关闭编辑权限', () => {
  assert.equal(normalizeMindmapContentState('future_protection_state'), 'load_failed')
  assert.equal(isMindmapContentWritable('future_protection_state'), false)
})

test('不同故障状态提供准确的视觉层级和默认说明', () => {
  const migration = getMindmapContentStatePresentation('migration_failed')
  const integrity = getMindmapContentStatePresentation('integrity_failed')
  const unavailable = getMindmapContentStatePresentation('load_failed')

  assert.equal(migration.type, 'warning')
  assert.match(migration.title, /迁移保护/)
  assert.equal(integrity.type, 'error')
  assert.match(integrity.description, /不能继续编辑/)
  assert.match(unavailable.description, /稍后重新加载/)
})

test('服务端安全说明优先于前端默认说明', () => {
  const presentation = getMindmapContentStatePresentation(
    'integrity_failed',
    '管理员正在修复该文件',
  )
  assert.equal(presentation.description, '管理员正在修复该文件')
})

test('编辑页和列表统一使用内容状态写入门禁', async () => {
  const [editSource, editorSource, listSource] = await Promise.all([
    readFile(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../views/mindmap/index.vue', import.meta.url), 'utf8'),
  ])

  assert.match(editSource, /contentState !== 'ready'/)
  assert.match(editSource, /normalizeMindmapContentState\(access\?\.contentState\)/)
  assert.match(editSource, /isMindmapContentWritable\(nextContentState\)/)
  assert.match(editSource, /contentStatePresentation\.title/)
  assert.match(editorSource, /isMindmapContentWritable\(data\.contentState\)/)
  assert.match(listSource, /isMindmapContentWritable\(row\?\.contentState\)/)
})
