import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  formatMindmapDeletePrompt,
  formatMindmapPermanentDeletePrompt,
  MAX_MINDMAP_DESCRIPTION_LENGTH,
  normalizeMindmapName,
  validateMindmapDescription,
  validateMindmapName,
} from '../mindmap-file.js'

const listSourceUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
const mindmapApiSourceUrl = new URL('../../api/mindmap/mindmap.js', import.meta.url)
const rightToolbarSourceUrl = new URL('../../components/RightToolbar/index.vue', import.meta.url)

test('脑图空列表按筛选、共享和首次使用场景提供明确下一步', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /没有找到匹配的脑图/)
  assert.match(source, /暂时没有共享给你的脑图/)
  assert.match(source, /创建第一张脑图/)
  assert.match(source, /v-else-if="hasActiveFilters"[\s\S]*@click="resetQuery"/)
  assert.match(source, /canCreateMindmaps[\s\S]*@click="handleAdd"/)
})

test('脑图名称统一清理空白、控制字符和 200 字符边界', () => {
  assert.equal(normalizeMindmapName('  产品规划  '), '产品规划')
  assert.equal(validateMindmapName('  ').valid, false)
  assert.equal(validateMindmapName('标题\n注入').valid, false)
  assert.equal(validateMindmapName('脑'.repeat(200)).valid, true)
  assert.equal(validateMindmapName('脑'.repeat(201)).valid, false)
})

test('回收站确认明确区分可恢复删除与不可撤销永久删除', () => {
  const single = formatMindmapDeletePrompt([{ id: 114, name: '产品规划' }])
  const batch = formatMindmapDeletePrompt([{ id: 1, name: 'A' }, { id: 2, name: 'B' }])
  const permanent = formatMindmapPermanentDeletePrompt([{ id: 114, name: '产品规划' }])

  assert.match(single, /“产品规划”/)
  assert.doesNotMatch(single, /114/)
  assert.match(single, /内容、版本和权限都会保留/)
  assert.match(single, /恢复后重新生效/)
  assert.match(batch, /2 张脑图/)
  assert.match(permanent, /分享链接和协作者权限/)
  assert.match(permanent, /无法撤销/)
})

test('脑图列表具备最新请求、可重试错误和越界分页恢复', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /const listRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /listRequests\.isCurrent\(requestId\)/)
  assert.match(source, /const tagRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /listError = ref\(''\)/)
  assert.match(source, /脑图列表加载失败/)
  assert.match(source, /重新加载/)
  assert.match(source, /queryParams\.value\.pageNum > maxPage/)
  assert.match(source, /return loadMindmapList\(false\)/)
})

test('文件关键词同时覆盖名称与说明并使用严格长度契约', async () => {
  const [source, fileUtility, vo, dao] = await Promise.all([
    readFile(listSourceUrl, 'utf8'),
    readFile(new URL('../mindmap-file.js', import.meta.url), 'utf8'),
    readFile(new URL('../../../../ruoyi-fastapi-backend/module_mindmap/entity/vo/mindmap_vo.py', import.meta.url), 'utf8'),
    readFile(new URL('../../../../ruoyi-fastapi-backend/module_mindmap/dao/mindmap_dao.py', import.meta.url), 'utf8'),
  ])

  assert.match(source, /label="文件关键词" prop="keyword"/)
  assert.match(source, /placeholder="搜索名称或说明"/)
  assert.match(source, /:maxlength="MAX_MINDMAP_FILE_KEYWORD_LENGTH"/)
  assert.match(source, /keyword: queryParams\.value\.keyword\?\.trim\(\) \|\| undefined/)
  assert.match(fileUtility, /MAX_MINDMAP_FILE_KEYWORD_LENGTH = 100/)
  assert.match(vo, /keyword: str \| None = Field\([\s\S]*max_length=MAX_MINDMAP_FILE_KEYWORD_LENGTH/)
  assert.match(dao, /Mindmap\.name\.ilike\(keyword_pattern, escape='\\\\'\)/)
  assert.match(dao, /Mindmap\.description\.ilike\(keyword_pattern, escape='\\\\'\)/)
})

test('URL 标签筛选恢复标签详情并隔离迟到请求', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /const selectedTagRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /watch\(\(\) => appliedListRouteState\.value\.tagId,[\s\S]*loadSelectedTagOption\(tagId\)/)
  assert.match(source, /const response = await getTag\(normalizedTagId\)/)
  assert.match(source, /appliedListRouteState\.value\.tagId !== normalizedTagId/)
  assert.match(source, /selectedTagOption\.value = tag/)
  assert.match(source, /selectedTagRequests\.invalidate\(\)/)
})

test('文件创建、复制、移动和删除共享操作锁与显式失败反馈', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /const operationType = ref\(''\)/)
  assert.match(source, /operationType\.value = 'add'/)
  assert.match(source, /operationType\.value = `copy:\$\{row\.id\}`/)
  assert.match(source, /operationType\.value = 'move'/)
  assert.match(source, /formatMindmapDeletePrompt\(selectedItems\)/)
  assert.match(source, /distinguishCancelAndClose: true/)
  assert.match(source, /getMindmapFileErrorMessage/)
})

test('文件说明统一清理空白、保留换行并限制控制字符和 500 字边界', () => {
  assert.deepEqual(validateMindmapDescription('  目标\n范围  '), {
    valid: true,
    value: '目标\n范围',
    message: '',
  })
  assert.equal(validateMindmapDescription('目标\t范围').valid, true)
  assert.equal(validateMindmapDescription('说明\u0000注入').valid, false)
  assert.equal(validateMindmapDescription('脑'.repeat(MAX_MINDMAP_DESCRIPTION_LENGTH)).valid, true)
  assert.equal(validateMindmapDescription('脑'.repeat(MAX_MINDMAP_DESCRIPTION_LENGTH + 1)).valid, false)
})

test('共享文件信息对话框统一严格契约并隔离迟到响应', async () => {
  const [source, editorSource, dialogSource] = await Promise.all([
    readFile(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/MindmapMetadataDialog.vue', import.meta.url), 'utf8'),
  ])

  assert.match(source, /<MindmapMetadataDialog/)
  assert.match(source, /:session-key="editorSessionKey"/)
  assert.doesNotMatch(source, /updateMindmapMetadata/)
  assert.match(dialogSource, /title="编辑脑图信息"/)
  assert.match(dialogSource, /width="min\(500px, calc\(100vw - 32px\)\)"/)
  assert.match(dialogSource, /:maxlength="MAX_MINDMAP_DESCRIPTION_LENGTH"/)
  assert.match(dialogSource, /await updateMindmapMetadata\(\{/)
  assert.match(dialogSource, /description: descriptionResult\.value \|\| null/)
  assert.match(dialogSource, /generation !== requestGeneration \|\| !visible\.value \|\| form\.id !== targetId/)
  assert.match(dialogSource, /watch\(\(\) => props\.sessionKey,[\s\S]*close\(\{ force: true \}\)/)
  assert.match(dialogSource, /defineExpose\(\{[\s\S]*open,[\s\S]*close,/)
  assert.match(editorSource, /description: data\.description \|\| ''/)
})

test('卡片与表格复用文件信息对话框并在更新后刷新确定性排序', async () => {
  const [listSource, cardSource] = await Promise.all([
    readFile(listSourceUrl, 'utf8'),
    readFile(new URL('../../components/MindMap/MindmapFileCard.vue', import.meta.url), 'utf8'),
  ])

  assert.match(listSource, /<MindmapMetadataDialog/)
  assert.match(listSource, /<el-dropdown-item v-if="canEditMindmap\(scope\.row\)" command="metadata">/)
  assert.match(cardSource, /<el-dropdown-item v-if="canEdit" command="metadata">/)
  assert.match(listSource, /if \(command === 'metadata' && !canEditMindmap\(row\)\) return/)
  assert.match(listSource, /metadataDialogRef\.value\?\.open\?\.\(row\)/)
  assert.match(listSource, /current\.description = metadata\.description[\s\S]*void getList\(\)/)
  assert.doesNotMatch(listSource, /updateMindmapMetadata/)
})

test('编辑页显式保存复用核心保存链路并尊重只读与会话边界', async () => {
  const [source, editorSource] = await Promise.all([
    readFile(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
  ])

  assert.match(source, /aria-label="立即保存脑图"/)
  assert.match(source, /立即保存（Ctrl \/ ⌘ \+ S）/)
  assert.match(source, /if \(manualSaveBusy\.value \|\| isReadonly\.value \|\| !documentLoaded\.value\) return/)
  assert.match(source, /await editRef\.value\?\.manualSave\?\.\(\)/)
  assert.match(source, /sessionKey === editorSessionKey\.value/)
  assert.match(editorSource, /defineExpose\(\{[\s\S]*manualSave,/)
})

test('协作离线状态提供受会话边界保护的立即重连入口', async () => {
  const [source, editorSource] = await Promise.all([
    readFile(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
  ])

  assert.match(source, /realtimeState\.value === 'offline'/)
  assert.match(source, /aria-label="立即重连实时协作"/)
  assert.match(source, /if \(!canRetryRealtime\.value\) return/)
  assert.match(source, /editRef\.value\?\.retryCollaboration\?\.\(\)/)
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.realtime-retry-btn[\s\S]*span \{[\s\S]*display: none/)
  assert.match(editorSource, /retryCollaboration: \(\) => yjsSyncRef\.value\?\.retryConnection\?\.\(\) === true/)
})

test('窄屏列表隐藏目录分栏并保留我的脑图与共享范围切换', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /class="mobile-scope-bar"/)
  assert.match(source, /@media \(max-width: 900px\)/)
  assert.match(source, /splitpanes__pane:first-child[\s\S]*display: none/)
  assert.match(source, /selectFolder\('all'\)/)
  assert.match(source, /@click="selectShared"/)
  assert.match(source, /class="mobile-scope-bar"[\s\S]*:aria-current="listScope === 'owned' \? 'page' : undefined"/)
  assert.match(source, /class="mobile-scope-bar"[\s\S]*:aria-current="listScope === 'shared' \? 'page' : undefined"/)
  assert.match(source, /label="操作" width="220" align="center" fixed="right"/)
})

test('列表下拉权限使用响应式状态并在执行入口再次校验', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /const canEditMindmaps = computed/)
  assert.match(source, /const canRemoveMindmaps = computed/)
  assert.match(source, /command === 'copy' && !canCreateMindmaps\.value/)
  assert.match(source, /\['move', 'status'\]\.includes\(command\)/)
  assert.doesNotMatch(source, /<el-dropdown-item[^>]*v-hasPermi/)
})

test('脑图列表完整状态同步到路由以支持刷新、历史导航和返回恢复', async () => {
  const source = await readFile(listSourceUrl, 'utf8')

  assert.match(source, /parseMindmapListRouteQuery\(\s*route\.query,/)
  assert.match(source, /function syncListRoute\(\)/)
  assert.match(source, /buildMindmapListRouteQuery\(getCurrentListRouteState\(\)\)/)
  assert.match(source, /router\.replace\(\{ query: nextQuery \}\)/)
  assert.match(source, /watch\(\(\) => route\.query,[\s\S]*applyListRouteState\(nextState\)/)
  assert.match(source, /function handlePagination\(\) \{[\s\S]*syncListRoute\(\)[\s\S]*getList\(\)/)
  assert.match(source, /function handleSortChange\(nextSortKey\) \{[\s\S]*syncListRoute\(\)/)
  assert.match(source, /returnList: getListReturnState\(\)/)
  assert.match(source, /appliedListRouteState\.value\.scope !== 'trash'[\s\S]*appliedListRouteState\.value\.status !== 0/)
})

test('回收站提供独立恢复与永久删除协议且不暴露编辑入口', async () => {
  const [source, apiSource] = await Promise.all([
    readFile(listSourceUrl, 'utf8'),
    readFile(mindmapApiSourceUrl, 'utf8'),
  ])

  assert.match(source, /listScope === 'trash'/)
  assert.match(source, /@click="selectTrash"/)
  assert.match(source, /handleRestore\(scope\.row\)/)
  assert.match(source, /handlePermanentDelete\(scope\.row\)/)
  assert.match(source, /<template v-if="listScope === 'trash'">[\s\S]*<template v-else>[\s\S]*handleView/)
  assert.match(apiSource, /url: '\/mindmap\/trash\/restore\/' \+ mindmapIds[\s\S]*method: 'put'/)
  assert.match(apiSource, /url: '\/mindmap\/trash\/' \+ mindmapIds[\s\S]*method: 'delete'/)
})

test('列表工具栏图标按钮提供名称、状态和重复刷新保护', async () => {
  const [listSource, toolbarSource] = await Promise.all([
    readFile(listSourceUrl, 'utf8'),
    readFile(rightToolbarSourceUrl, 'utf8'),
  ])

  assert.match(toolbarSource, /:aria-label="searchButtonLabel"/)
  assert.match(toolbarSource, /:aria-pressed="showSearch"/)
  assert.match(toolbarSource, /aria-label="刷新列表"/)
  assert.match(toolbarSource, /:loading="loading"/)
  assert.match(toolbarSource, /aria-label="设置显示列"/)
  assert.match(toolbarSource, /:aria-expanded="columnMenuOpen"/)
  assert.match(listSource, /<right-toolbar[\s\S]*:loading="loading"/)
})
