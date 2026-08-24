import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  isCompatibleTagReplacement,
  MAX_MINDMAP_TAG_BATCH_SIZE,
  MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
  MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
  validateMindmapTagCategorySortOrder,
  validateMindmapTagColor,
  validateMindmapTagDescription,
  validateMindmapTagDisplayName,
  validateMindmapTagIdentifier,
  validateMindmapTagSearchKeyword,
  validateMindmapTagStyle,
} from '../mindmap-tag-governance.js'

const sourceUrl = new URL('../../views/mindmap/tags.vue', import.meta.url)
const apiSourceUrl = new URL('../../api/mindmap/tag.js', import.meta.url)

test('统一标签输入使用一致的名称、Key、说明和搜索边界', () => {
  assert.equal(validateMindmapTagIdentifier(' risk_level ').value, 'risk_level')
  assert.equal(validateMindmapTagIdentifier('risk level').valid, false)
  assert.equal(validateMindmapTagDisplayName(' 风险等级 ').value, '风险等级')
  assert.equal(validateMindmapTagDisplayName('风险\n等级').valid, false)
  assert.equal(validateMindmapTagDescription(' 第一行\n第二行 ').value, '第一行\n第二行')
  assert.equal(validateMindmapTagDescription('说明\u0000内容').valid, false)
  assert.deepEqual(validateMindmapTagSearchKeyword('  风险等级  '), {
    valid: true,
    value: '风险等级',
    message: '',
  })
  assert.equal(validateMindmapTagSearchKeyword('风险\n等级').valid, false)
  assert.equal(
    validateMindmapTagSearchKeyword('标'.repeat(MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH + 1)).valid,
    false,
  )
})

test('统一标签样式只接受安全颜色和受控尺寸', () => {
  assert.deepEqual(validateMindmapTagColor(' rgba(255, 0, 16, 0.5) '), {
    valid: true,
    value: '#ff001080',
    message: '',
  })
  assert.equal(validateMindmapTagColor('url(https://example.test/pixel)').valid, false)
  const style = validateMindmapTagStyle({
    fill: '#ABC', color: 'rgb(255, 255, 255)', fontSize: 12, radius: 3.5, paddingX: 8,
    placement: 'top', align: 'right',
  })
  assert.equal(style.valid, true)
  assert.deepEqual(style.value, {
    fill: '#abc', color: '#ffffff', fontSize: 12, radius: 3.5, paddingX: 8,
    placement: 'top', align: 'right',
  })
  assert.equal(validateMindmapTagStyle({ width: 300 }).valid, false)
  assert.equal(validateMindmapTagStyle({ fontSize: 25 }).valid, false)
  assert.equal(validateMindmapTagStyle({ placement: 'top', align: 'bottom' }).valid, false)
})

test('标签替换保持所有者范围并只接受启用目标', () => {
  const globalSource = { id: 1, ownerId: 0 }
  const privateSource = { id: 2, ownerId: 42 }
  assert.equal(isCompatibleTagReplacement(globalSource, { id: 3, ownerId: 0, status: 0 }), true)
  assert.equal(isCompatibleTagReplacement(globalSource, { id: 4, ownerId: 42, status: 0 }), false)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 3, ownerId: 0, status: 0 }), true)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 5, ownerId: 42, status: 0 }), true)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 6, ownerId: 43, status: 0 }), false)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 7, ownerId: 42, status: 1 }), false)
})

test('标签分类排序只接受有界安全整数', () => {
  assert.equal(validateMindmapTagCategorySortOrder(0).valid, true)
  assert.equal(validateMindmapTagCategorySortOrder(-MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER).valid, true)
  assert.equal(validateMindmapTagCategorySortOrder(1.5).valid, false)
  assert.equal(validateMindmapTagCategorySortOrder(MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER + 1).valid, false)
})

test('标签管理页只保留统一标签治理并具备请求竞态和失败恢复', async () => {
  const [source, apiSource] = await Promise.all([
    readFile(sourceUrl, 'utf8'),
    readFile(apiSourceUrl, 'utf8'),
  ])

  assert.doesNotMatch(source, /<h2>标签管理<\/h2>/)
  assert.doesNotMatch(source, /集中维护标签定义。一个脑图节点可以同时使用多个标签。/)
  assert.match(source, /const tagRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /const categoryRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /const replacementRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /tagRequests\.isCurrent\(id\)/)
  assert.match(source, /replacementRequests\.invalidate\(\)/)
  assert.match(source, /replacementOptions\.value = \[\]/)
  assert.match(source, /目标标签加载失败，请重新搜索/)
  assert.match(source, /role="alert"/)
  assert.match(source, /重新加载/)
  assert.doesNotMatch(source, /标签字段|字段选项|fieldId|optionId|selectMode/)
  assert.doesNotMatch(apiSource, /tag-field/)
})

test('标签管理支持分组、影响评估、替换和有界批量归档', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.equal(MAX_MINDMAP_TAG_BATCH_SIZE, 100)
  assert.match(source, /class="tagWorkspace"/)
  assert.match(source, /class="tagGroupPanel"/)
  assert.match(source, /class="tagListPanel"/)
  assert.match(source, /<div class="managementCard">/)
  assert.doesNotMatch(source, /<el-card[^>]*class="managementCard"/)
  assert.match(source, /\.tagManagementPage[\s\S]*padding: 0;/)
  assert.match(source, /\.managementCard[\s\S]*border: 0;[\s\S]*border-radius: 0;/)
  assert.match(source, /grid-template-columns: clamp\(240px, 20%, 280px\)/)
  assert.match(source, /\.tagGroupPanel[\s\S]*margin: 0;[\s\S]*padding: 0;/)
  assert.match(source, /\.tagGroupPanelHeader[\s\S]*min-height: 52px/)
  assert.match(source, /\.tagGroupNavItem[\s\S]*height: 34px[\s\S]*border-radius: 5px/)
  assert.match(source, /&:hover[\s\S]*background: #e8f0fe/)
  assert.match(source, /&\.active[\s\S]*background: #d6e4ff/)
  assert.match(source, /@click="selectCategory\(category\.id\)"/)
  assert.match(source, /@click="selectCategory\(0\)"/)
  assert.match(source, /const currentCategoryTitle = computed/)
  assert.match(source, /title="标签分组管理"/)
  assert.match(source, /class="tagDefinitionDialog"/)
  assert.match(source, /max-height: calc\(100vh - 32px\)/)
  assert.match(source, /\.el-dialog__body[\s\S]*overflow-y: auto/)
  assert.match(source, /class="tagStyleSection"/)
  assert.match(source, /class="tagStyleNumber"[\s\S]*controls-position="right"/)
  assert.match(source, /v-model="editDialog\.placement"/)
  assert.match(source, /v-model="editDialog\.align"/)
  assert.match(source, /const tagAlignOptions = computed/)
  assert.match(source, /placement: editDialog\.placement/)
  assert.match(source, /align: editDialog\.align/)
  assert.match(source, /\.tagStyleNumberGrid[\s\S]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/)
  assert.match(source, /class="tagActionCell"/)
  assert.match(source, /\.tagActionCell[\s\S]*align-items: center[\s\S]*justify-content: flex-end[\s\S]*gap: 12px/)
  assert.match(source, /import Draggable from 'vuedraggable'/)
  assert.match(source, /handle="\.categoryDragHandle"/)
  assert.match(source, /finishCategoryReorder\('global'\)/)
  assert.match(source, /finishCategoryReorder\('mine'\)/)
  assert.match(source, /categoryTypeText\(row\.categoryType\)/)
  assert.match(source, /系统.*用户自定义/s)
  assert.match(source, /reorderTagCategories\(categoryIds\)/)
  assert.match(source, /Number\(row\.tagCount\) > 0/)
  assert.match(source, /getTagImpact\(row\.id\)/)
  assert.match(source, /isCompatibleTagReplacement/)
  assert.match(source, /ids\.length > MAX_MINDMAP_TAG_BATCH_SIZE/)
  assert.match(source, /deleteTags\(ids\.join\(','\), true\)/)
  assert.match(source, /type="selection"[\s\S]*:selectable="canSelectTag"/)
})
