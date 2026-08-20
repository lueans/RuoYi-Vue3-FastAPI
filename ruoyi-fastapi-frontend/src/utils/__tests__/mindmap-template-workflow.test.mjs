import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  getMindmapTemplateErrorMessage,
  getSafeTemplateCoverUrl,
  getTemplateCategoryName,
} from '../mindmap-template.js'
import { extractCreatedMindmapId } from '../mindmap-creation.js'

const marketSourceUrl = new URL('../../views/mindmap/templates.vue', import.meta.url)
const adminSourceUrl = new URL('../../views/mindmap/templateAdmin.vue', import.meta.url)
const previewSourceUrl = new URL('../../components/MindMap/TemplatePreviewDialog.vue', import.meta.url)
const controllerSourceUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/controller/mindmap_template_controller.py',
  import.meta.url,
)

test('模板封面只接受安全且可持久化的地址', () => {
  assert.equal(getSafeTemplateCoverUrl('/uploads/a.png'), '/uploads/a.png')
  assert.equal(getSafeTemplateCoverUrl('assets/a.png'), 'assets/a.png')
  assert.equal(getSafeTemplateCoverUrl('https://example.com/a.png'), 'https://example.com/a.png')
  assert.equal(getSafeTemplateCoverUrl('//example.com/a.png'), '')
  assert.equal(getSafeTemplateCoverUrl('javascript:alert(1)'), '')
  assert.equal(getSafeTemplateCoverUrl('data:image/svg+xml,<svg/>'), '')
  assert.equal(getSafeTemplateCoverUrl('https://user:secret@example.com/a.png'), '')
})

test('使用模板必须取得有效的新脑图 ID', () => {
  assert.equal(extractCreatedMindmapId({ data: { id: 88 } }), 88)
  assert.throws(() => extractCreatedMindmapId({ data: {} }), /未返回有效文件 ID/)
  assert.throws(() => extractCreatedMindmapId({ data: { id: 0 } }), /未返回有效文件 ID/)
})

test('模板分类和错误信息有稳定回退', () => {
  const categories = [{ id: 3, name: '项目管理' }]
  assert.equal(getTemplateCategoryName(categories, 3), '项目管理')
  assert.equal(getTemplateCategoryName(categories, 9), '未分类')
  assert.equal(getMindmapTemplateErrorMessage(new Error('网络错误')), '网络错误')
})

test('模板市场具备竞态保护、错误恢复、预览和创建锁', async () => {
  const source = await readFile(marketSourceUrl, 'utf8')
  assert.match(source, /createLatestRequestTracker/)
  assert.match(source, /v-else-if="listError"/)
  assert.match(source, /TemplatePreviewDialog/)
  assert.match(source, /usingTemplateId\.value/)
  assert.match(source, /resolveCreatedMindmapNavigation/)
  assert.match(source, /creationRequestTracker\.isCurrent\(creationRequestId\)/)
  assert.match(source, /onDeactivated\(invalidateTemplateSessions\)/)
  assert.match(source, /navigate: mindmapId => router\.push\(\{ path: '\/mindmap\/edit', query: \{ id: mindmapId \} \}\)/)
  assert.match(source, /脑图已创建，但未能自动打开/)
  assert.doesNotMatch(source, /\/mindmap\/edit\/\$\{newId\}/)
})

test('模板管理预览真实模板内容且所有写操作可恢复', async () => {
  const [adminSource, previewSource] = await Promise.all([
    readFile(adminSourceUrl, 'utf8'),
    readFile(previewSourceUrl, 'utf8'),
  ])
  assert.match(adminSource, /TemplatePreviewDialog/)
  assert.match(adminSource, /operationType/)
  assert.match(adminSource, /listError/)
  assert.match(adminSource, /listMindmap/)
  assert.doesNotMatch(adminSource, /router\.push\(\{ path: '\/mindmap\/edit'/)
  assert.match(previewSource, /getTemplateDetail/)
  assert.match(previewSource, /registerPreviewPlugins/)
  assert.match(previewSource, /readonly: true/)
  assert.match(previewSource, /requestTracker\.invalidate\(\)/)
})

test('模板接口响应新脑图 ID 并声明驼峰查询参数', async () => {
  const source = await readFile(controllerSourceUrl, 'utf8')
  assert.match(source, /Query\(alias='categoryId'/)
  assert.match(source, /Query\(alias='pageNum'/)
  assert.match(source, /Query\(alias='pageSize'/)
  assert.match(source, /Query\(alias='name'/)
  assert.match(source, /ResponseUtil\.success\(msg=result\.message, data=result\.result\)/)
})
