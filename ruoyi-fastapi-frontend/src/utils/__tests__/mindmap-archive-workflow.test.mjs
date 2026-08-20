import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  formatMindmapArchivePrompt,
  formatMindmapBatchArchivePrompt,
} from '../mindmap-file.js'

const listSourceUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
const editPageSourceUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
const editorSourceUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
const yjsSourceUrl = new URL('../yjs-sync.js', import.meta.url)
const controllerSourceUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/controller/mindmap_controller.py',
  import.meta.url,
)
const migrationSourceUrl = new URL(
  '../../../../ruoyi-fastapi-backend/migrations/20260818_mindmap_archive_lifecycle.sql',
  import.meta.url,
)

test('归档确认明确保留内容并终止在线编辑', () => {
  const message = formatMindmapArchivePrompt({ name: '产品规划' })
  assert.match(message, /产品规划/)
  assert.match(message, /内容、版本、分享链接和协作者都会保留/)
  assert.match(message, /在线编辑会话将立即结束/)
  assert.match(message, /恢复前只能查看/)

  const batchMessage = formatMindmapBatchArchivePrompt([
    { id: 1, name: 'A' },
    { id: 2, name: 'B' },
  ])
  assert.match(batchMessage, /选中的 2 张脑图/)
  assert.match(batchMessage, /在线编辑会话将立即结束/)
})

test('列表提供正常、全部和归档查询以及归档恢复操作', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /status: initialListRouteState\.status \?\? undefined/)
  assert.match(source, /updateMindmapStatus/)
  assert.match(source, /handleStatusChange/)
  assert.match(source, /formatMindmapArchivePrompt/)
  assert.match(source, /scope\.row\.status === 1 \? '恢复' : '归档'/)
  assert.match(source, /operationType\.value = `status:\$\{row\.id\}`/)
  assert.match(source, /row\?\.canEdit !== undefined/)
  assert.match(source, /Number\(row\?\.status\) !== 1/)
  assert.match(source, /batchUpdateMindmapStatus/)
  assert.match(source, /handleBatchStatusChange\(1\)/)
  assert.match(source, /handleBatchStatusChange\(0\)/)
  assert.match(source, /selectedActiveMindmaps/)
  assert.match(source, /selectedArchivedMindmaps/)
})

test('归档事件贯穿 Yjs、编辑器和页面终止链路', async () => {
  const [yjsSource, editorSource, pageSource] = await Promise.all([
    readFile(yjsSourceUrl, 'utf8'),
    readFile(editorSourceUrl, 'utf8'),
    readFile(editPageSourceUrl, 'utf8'),
  ])

  assert.match(yjsSource, /document_archived: \(data\) => this\._handleDocumentArchived\(data\)/)
  assert.match(yjsSource, /_terminateCollaboration\(data, 'archived', 'onDocumentArchived'\)/)
  assert.match(editorSource, /terminateEditingSession\('document-archived', data\)/)
  assert.match(editorSource, /'document-archived'/)
  assert.match(pageSource, /@document-archived="onDocumentArchived"/)
  assert.match(pageSource, /归档文件保留全部内容、版本和分享/)
})

test('后端暴露所有者状态接口并提供归档查询索引', async () => {
  const [controllerSource, migrationSource] = await Promise.all([
    readFile(controllerSourceUrl, 'utf8'),
    readFile(migrationSourceUrl, 'utf8'),
  ])

  assert.match(controllerSource, /@mindmap_controller\.put\(\s*'\/status'/)
  assert.match(controllerSource, /MindmapStatusUpdateModel/)
  assert.match(controllerSource, /@mindmap_controller\.put\(\s*'\/status\/batch'/)
  assert.match(controllerSource, /MindmapBatchStatusUpdateModel/)
  assert.match(migrationSource, /idx_mindmap_owner_status/)
  assert.match(migrationSource, /status NOT IN \(0, 1\)/)
})
