import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMindmapListRoute,
  createMindmapEditorSessionKey,
  isSharedMindmapContext,
  parseMindmapRouteId,
} from '../mindmap-route.js'
import { encodeMindmapListReturnState } from '../mindmap-list-route.js'
import { readFile } from 'node:fs/promises'

test('脑图路由只接受安全正整数 ID', () => {
  assert.equal(parseMindmapRouteId('42'), 42)
  assert.equal(parseMindmapRouteId(7), 7)
  for (const value of [undefined, null, '', '0', '-1', '1.5', '1abc', ['1']]) {
    assert.equal(parseMindmapRouteId(value), null)
  }
  assert.equal(parseMindmapRouteId(String(Number.MAX_SAFE_INTEGER + 1)), null)
})

test('共享脑图返回列表时保留访问上下文', () => {
  assert.equal(isSharedMindmapContext('shared'), true)
  assert.deepEqual(buildMindmapListRoute('shared'), {
    path: '/mindmap/index',
    query: { scope: 'shared' },
  })
  assert.deepEqual(buildMindmapListRoute('owned'), { path: '/mindmap/index' })
})

test('编辑器返回列表时恢复完整查询状态并安全回退', () => {
  const returnList = encodeMindmapListReturnState({
    scope: 'owned',
    keyword: '季度目标',
    status: null,
    folderId: 12,
    tagId: 8,
    pageNum: 3,
    pageSize: 20,
    sortKey: 'name-asc',
  })
  assert.deepEqual(buildMindmapListRoute('shared', returnList), {
    path: '/mindmap/index',
    query: {
      sort: 'name-asc',
      q: '季度目标',
      status: 'all',
      folder: '12',
      tag: '8',
      page: '3',
      size: '20',
    },
  })
  assert.deepEqual(buildMindmapListRoute('shared', '{broken'), {
    path: '/mindmap/index',
    query: { scope: 'shared' },
  })
})

test('编辑会话身份同时包含文件与只读模式', () => {
  assert.equal(createMindmapEditorSessionKey(42, false), '42:edit')
  assert.equal(createMindmapEditorSessionKey('42', true), '42:readonly')
  assert.equal(createMindmapEditorSessionKey('invalid', false), 'invalid')
})

test('同路由切换文件或访问模式也必须执行离开保存守卫', async () => {
  const source = await readFile(
    new URL('../../views/mindmap/edit.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /:key="editorInstanceKey"/)
  assert.match(source, /const editorInstanceKey = computed\(\(\) => `\$\{editorSessionKey\.value\}:\$\{editorRetryNonce\.value\}`\)/)
  assert.match(source, /editRef\.value\?\.prepareForCloudExit\?\.\(\)/)
  assert.match(source, /onBeforeRouteLeave\(confirmEditorNavigation\)/)
  assert.match(source, /onBeforeRouteUpdate\(\(to\) => \{[\s\S]*?return confirmEditorNavigation\(\)/)
  assert.match(source, /watch\(editorSessionKey, \(\) => \{/)
  assert.match(source, /buildMindmapListRoute\(\s*serverAccessType\.value,\s*route\.query\.returnList,/)
})
