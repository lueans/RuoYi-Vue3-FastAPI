import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  buildMindmapNodeSearchRoute,
  parseMindmapFocusNodeUid,
} from '../mindmap-route.js'
import { encodeMindmapListReturnState } from '../mindmap-list-route.js'

const dialogSourceUrl = new URL('../../components/MindMap/GlobalSearchDialog.vue', import.meta.url)
const indexSourceUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
const editPageSourceUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
const editorSourceUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
const controllerSourceUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/controller/mindmap_controller.py',
  import.meta.url,
)

test('全局搜索跳转保留节点定位、共享来源和只读权限', () => {
  assert.deepEqual(buildMindmapNodeSearchRoute({
    mindmapId: 12,
    nodeUid: 'node-plan',
    accessType: 'shared',
    canEdit: false,
  }), {
    path: '/mindmap/edit',
    query: {
      id: 12,
      focusNode: 'node-plan',
      readonly: '1',
      from: 'shared',
    },
  })
  assert.deepEqual(buildMindmapNodeSearchRoute({
    mindmapId: 13,
    nodeUid: 'owned-node',
    accessType: 'owned',
    canEdit: true,
  }), {
    path: '/mindmap/edit',
    query: { id: 13, focusNode: 'owned-node' },
  })
  assert.equal(buildMindmapNodeSearchRoute({ mindmapId: 0, nodeUid: 'x' }), null)
  assert.equal(parseMindmapFocusNodeUid(`a${String.fromCharCode(1)}b`), '')
  assert.equal(parseMindmapFocusNodeUid('x'.repeat(65)), '')
})

test('全局搜索只携带经过校验的列表返回状态', () => {
  const returnList = encodeMindmapListReturnState({
    scope: 'trash',
    pageNum: 2,
    sortKey: 'created-desc',
  })
  assert.equal(buildMindmapNodeSearchRoute({
    mindmapId: 12,
    nodeUid: 'node-plan',
    canEdit: true,
  }, { returnList }).query.returnList, returnList)
  assert.equal(buildMindmapNodeSearchRoute({
    mindmapId: 12,
    nodeUid: 'node-plan',
    canEdit: true,
  }, { returnList: '{broken' }).query.returnList, undefined)
})

test('列表级搜索具备分页、竞态保护、错误恢复和移动端布局', async () => {
  const [dialogSource, indexSource] = await Promise.all([
    readFile(dialogSourceUrl, 'utf8'),
    readFile(indexSourceUrl, 'utf8'),
  ])

  assert.match(dialogSource, /searchGlobalMindmapNodes/)
  assert.match(dialogSource, /requestId !== searchRequestId/)
  assert.match(dialogSource, /加载更多（已显示/)
  assert.match(dialogSource, /role="listbox"/)
  assert.match(dialogSource, /所属文件和完整节点路径/)
  assert.match(dialogSource, /归档文件仅可只读打开/)
  assert.match(dialogSource, /@media \(max-width: 720px\)/)
  assert.match(indexSource, /搜索全部内容/)
  assert.match(indexSource, /v-if="canQueryMindmaps"/)
  assert.match(indexSource, /buildMindmapNodeSearchRoute/)
})

test('搜索结果跳转后由编辑器定位稳定节点 UID', async () => {
  const [editPageSource, editorSource, controllerSource] = await Promise.all([
    readFile(editPageSourceUrl, 'utf8'),
    readFile(editorSourceUrl, 'utf8'),
    readFile(controllerSourceUrl, 'utf8'),
  ])

  assert.match(editPageSource, /parseMindmapFocusNodeUid\(route\.query\.focusNode\)/)
  assert.match(editPageSource, /focusNodeByUid/)
  assert.match(editorSource, /findNodeByUid/)
  assert.match(editorSource, /'GO_TARGET_NODE'/)
  assert.match(controllerSource, /@mindmap_controller\.get\(\s*'\/nodes\/search'/)
  assert.match(controllerSource, /PageResponseModel\[MindmapGlobalNodeSearchItemModel\]/)
})
