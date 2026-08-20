import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  getCreatedResourceId,
  isCompatibleTagReplacement,
  MAX_MINDMAP_TAG_BATCH_SIZE,
  MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
  MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
  MAX_MINDMAP_TAG_FIELD_NAME_LENGTH,
  MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
  validateMindmapTagColor,
  validateMindmapTagCategorySortOrder,
  validateMindmapTagDescription,
  validateMindmapTagDisplayName,
  validateMindmapTagIdentifier,
  validateMindmapTagSearchKeyword,
  validateMindmapTagStyle,
} from '../mindmap-tag-governance.js'

const sourceUrl = new URL('../../views/mindmap/tags.vue', import.meta.url)
const listSourceUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
const nodeTagSourceUrl = new URL('../../components/MindMap/NodeTag.vue', import.meta.url)
const apiSourceUrl = new URL('../../api/mindmap/tag.js', import.meta.url)

test('标签检索统一清理空白并拒绝控制字符与超长输入', () => {
  assert.deepEqual(validateMindmapTagSearchKeyword('  风险等级  '), {
    valid: true,
    value: '风险等级',
    message: '',
  })
  assert.equal(validateMindmapTagSearchKeyword('   ').valid, true)
  assert.equal(validateMindmapTagSearchKeyword('   ', { required: true }).valid, false)
  assert.equal(validateMindmapTagSearchKeyword('风险\n等级').valid, false)
  assert.equal(
    validateMindmapTagSearchKeyword('标'.repeat(MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH + 1)).valid,
    false,
  )
})

test('标签、字段和选项定义共享规范名称、Key 与说明边界', () => {
  assert.equal(validateMindmapTagIdentifier(' risk_level ').value, 'risk_level')
  assert.equal(validateMindmapTagIdentifier('risk level').valid, false)
  assert.equal(validateMindmapTagIdentifier('风险').valid, false)

  assert.equal(validateMindmapTagDisplayName(' 风险等级 ').value, '风险等级')
  assert.equal(validateMindmapTagDisplayName('   ').valid, false)
  assert.equal(validateMindmapTagDisplayName('风险\n等级').valid, false)
  assert.equal(validateMindmapTagDisplayName(
    '字'.repeat(MAX_MINDMAP_TAG_FIELD_NAME_LENGTH + 1),
    { label: '字段名称', maxLength: MAX_MINDMAP_TAG_FIELD_NAME_LENGTH },
  ).valid, false)

  assert.equal(validateMindmapTagDescription(' 第一行\n第二行 ').value, '第一行\n第二行')
  assert.equal(validateMindmapTagDescription('说明\u0000内容').valid, false)
})

test('标签样式仅接受安全颜色、受控数值以及兼容的位置对齐', () => {
  assert.deepEqual(validateMindmapTagColor(' rgba(255, 0, 16, 0.5) '), {
    valid: true,
    value: '#ff001080',
    message: '',
  })
  assert.equal(validateMindmapTagColor('#AbCd').value, '#abcd')
  assert.equal(validateMindmapTagColor('transparent').value, 'transparent')
  assert.equal(validateMindmapTagColor('rgb(999, 0, 0)').valid, false)
  assert.equal(validateMindmapTagColor('url(https://example.test/pixel)').valid, false)

  const style = validateMindmapTagStyle({
    fill: '#ABC',
    color: 'rgb(255, 255, 255)',
    fontSize: 12,
    radius: 3.5,
    paddingX: 8,
    placement: 'top',
    align: 'left',
  })
  assert.equal(style.valid, true)
  assert.deepEqual(style.value, {
    fill: '#abc',
    color: '#ffffff',
    fontSize: 12,
    radius: 3.5,
    paddingX: 8,
    placement: 'top',
    align: 'left',
  })
  assert.equal(validateMindmapTagStyle({ width: 300 }).valid, false)
  assert.equal(validateMindmapTagStyle({ fontSize: 25 }).valid, false)
  assert.equal(validateMindmapTagStyle({ placement: 'top', align: 'top' }).valid, false)
  assert.equal(validateMindmapTagStyle({ fill: '#fff' }, { fieldStyle: true }).valid, false)
})

test('标签分类排序只接受有界安全整数', () => {
  assert.equal(validateMindmapTagDisplayName(
    '类'.repeat(MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH),
    { label: '分类名称', maxLength: MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH },
  ).valid, true)
  assert.equal(validateMindmapTagCategorySortOrder(0).valid, true)
  assert.equal(validateMindmapTagCategorySortOrder(-MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER).valid, true)
  assert.equal(validateMindmapTagCategorySortOrder(MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER).valid, true)
  assert.equal(validateMindmapTagCategorySortOrder(1.5).valid, false)
  assert.equal(validateMindmapTagCategorySortOrder('1').valid, false)
  assert.equal(validateMindmapTagCategorySortOrder(MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER + 1).valid, false)
})

test('标签替换不会把全局绑定迁入私有范围或跨私有所有者迁移', () => {
  const globalSource = { id: 1, ownerId: 0 }
  const privateSource = { id: 2, ownerId: 42 }

  assert.equal(isCompatibleTagReplacement(globalSource, { id: 3, ownerId: 0, status: 0 }), true)
  assert.equal(isCompatibleTagReplacement(globalSource, { id: 4, ownerId: 42, status: 0 }), false)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 3, ownerId: 0, status: 0 }), true)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 5, ownerId: 42, status: 0 }), true)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 6, ownerId: 43, status: 0 }), false)
  assert.equal(isCompatibleTagReplacement(privateSource, { id: 7, ownerId: 42, status: 1 }), false)
})

test('创建响应只接受正的安全整数主键', () => {
  assert.equal(getCreatedResourceId({ data: { fieldId: 73 } }, 'fieldId'), 73)
  assert.equal(getCreatedResourceId({ data: { optionId: '81' } }, 'optionId'), 81)
  assert.equal(getCreatedResourceId({ data: { fieldId: 0 } }, 'fieldId'), null)
  assert.equal(getCreatedResourceId({ data: { fieldId: Number.MAX_SAFE_INTEGER + 1 } }, 'fieldId'), null)
  assert.equal(getCreatedResourceId({}, 'fieldId'), null)
})

test('标签治理页具备最新请求、错误恢复和操作互斥状态', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /const managedTagRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /const tagCategoryRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /const replacementRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /const fieldListRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /const fieldDetailRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /managedTagRequests\.isCurrent\(requestId\)/)
  assert.match(source, /tagCategoryRequests\.isCurrent\(requestId\)/)
  assert.match(source, /fieldDetailRequests\.isCurrent\(requestId\)/)
  assert.match(source, /role="alert"/)
  assert.match(source, /重新加载/)
  assert.match(source, /tagCategoriesError/)
  assert.match(source, /const tagOperationKey = ref\(''\)/)
  assert.match(source, /tagOperationKey\.value = `impact:\$\{row\.id\}`/)
  assert.match(source, /tagOperationKey\.value = `edit:\$\{row\.id\}`/)
  assert.match(source, /const fieldSubmitting = ref\(false\)/)
  assert.match(source, /const optionOperationKeys = reactive\(new Set\(\)\)/)
})

test('标签治理、列表筛选和节点标签共享严格搜索边界与失败反馈', async () => {
  const [source, listSource, nodeTagSource] = await Promise.all([
    readFile(sourceUrl, 'utf8'),
    readFile(listSourceUrl, 'utf8'),
    readFile(nodeTagSourceUrl, 'utf8'),
  ])

  assert.match(source, /:maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH"/)
  assert.match(source, /validateMindmapTagSearchKeyword\(managedTagQuery\.keyword\)/)
  assert.match(source, /validateMindmapTagSearchKeyword\(String\(keyword \?\? ''\)\)/)
  assert.match(listSource, /validateMindmapTagSearchKeyword\(String\(keyword \?\? ''\)\)/)
  assert.match(listSource, /tagOptionsError[\s\S]*role="alert"/)
  assert.match(listSource, /queryParams\.value\.keyword = undefined/)
  assert.match(nodeTagSource, /:maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH" show-word-limit/)
  assert.match(nodeTagSource, /validateMindmapTagDisplayName\(tagInput\.value\)/)
  assert.match(source, /function buildFieldPayload\(\)/)
  assert.match(source, /validateMindmapTagIdentifier\(fieldForm\.fieldKey/)
  assert.match(source, /validateMindmapTagDisplayName\(fieldForm\.name/)
  assert.match(source, /validateMindmapTagDescription\(fieldForm\.description/)
  assert.match(source, /validateMindmapTagStyle\(\{[\s\S]*fill: tagEditDialog\.fill/)
  assert.match(source, /validateMindmapTagStyle\(\{[\s\S]*placement: styleForm\.placement/)
  assert.match(source, /validateMindmapTagColor\(row\.fill/)
})

test('字段和颜色交互使用原生按钮并支持窄屏堆叠', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /<button[\s\S]*v-for="field in fields"[\s\S]*:aria-pressed=/)
  assert.match(source, /<ColorTrigger[\s\S]*label="选择选项背景色"/)
  assert.match(source, /<button v-for="c in group.colors"[\s\S]*:aria-pressed=/)
  assert.match(source, /:xs="24" :sm="8" :lg="6"/)
  assert.match(source, /:xs="24" :sm="16" :lg="18"/)
  assert.match(source, /\.fieldItem[\s\S]*&:focus-visible/)
  assert.match(source, /\.colorDot[\s\S]*&:focus-visible/)
})

test('标签治理表在窄屏固定可访问操作并使用当前分页 API', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /label="操作" width="150" align="right" fixed="right"/)
  assert.match(source, /:aria-label="`查看标签 \$\{row\.name\} 的影响范围`"/)
  assert.match(source, /:aria-label="`管理标签 \$\{row\.name\}`"/)
  assert.match(source, /@command="command => handleManagedTagCommand\(command, row\)"/)
  assert.match(source, /function handleManagedTagCommand\(command, row\)/)
  assert.match(source, /<el-pagination\s+size="small"/)
  assert.doesNotMatch(source, /<el-pagination\s+small\b/)
})

test('新增字段与选项直接使用服务端返回 ID，不按 Key 猜测记录', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /getCreatedResourceId\(res, 'fieldId'\)/)
  assert.match(source, /getCreatedResourceId\(res, 'optionId'\)/)
  assert.doesNotMatch(source, /find\(f => f\.fieldKey === fieldForm\.fieldKey\)/)
  assert.match(source, /if \(fieldCreatePromise\) return fieldCreatePromise/)
})

test('标签分类治理提供受控生命周期、权限和引用数量反馈', async () => {
  const [source, apiSource] = await Promise.all([
    readFile(sourceUrl, 'utf8'),
    readFile(apiSourceUrl, 'utf8'),
  ])

  assert.match(source, /title="标签分类管理"/)
  assert.match(source, /:maxlength="MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH"/)
  assert.match(source, /validateMindmapTagCategorySortOrder\(categoryForm\.sortOrder\)/)
  assert.match(source, /getCreatedResourceId\(response, 'categoryId'\)/)
  assert.match(source, /Number\(row\.tagCount\) > 0/)
  assert.match(source, /canEditCategoryRow\(row\)/)
  assert.match(source, /canRemoveCategoryRow\(row\)/)
  assert.match(source, /if \(!componentActive \|\| !categoryDialog\.visible\) return/)
  assert.match(source, /width="min\(680px, calc\(100vw - 32px\)\)"/)
  assert.match(source, new RegExp(`MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH`))
  assert.match(apiSource, /ownerScope = 'mine'/)
  assert.match(apiSource, /sortOrder: sortOrder \?\? 0, ownerScope/)
})

test('标签治理批量归档限制选择范围并在执行边界复核权限', async () => {
  const [source, apiSource] = await Promise.all([
    readFile(sourceUrl, 'utf8'),
    readFile(apiSourceUrl, 'utf8'),
  ])

  assert.equal(MAX_MINDMAP_TAG_BATCH_SIZE, 100)
  assert.match(source, /type="selection"[\s\S]*:selectable="canSelectManagedTag"/)
  assert.match(source, /aria-label="批量解除绑定并归档所选标签"/)
  assert.match(source, /tagIds\.length > MAX_MINDMAP_TAG_BATCH_SIZE/)
  assert.match(source, /rows\.some\(row => !canArchiveManagedTag\(row\)\)/)
  assert.match(source, /deleteTags\(tagIds\.join\(','\), true\)/)
  assert.match(source, /v-if="canAddTag"[\s\S]*@click="handleCreateManagedTag"/)
  assert.match(source, /canEditManagedTag\(row\)/)
  assert.match(source, /canArchiveManagedTag\(row\)/)
  assert.match(source, /\.governanceBatchBar[\s\S]*flex-direction: column/)
  assert.match(apiSource, /url: '\/mindmap\/tag\/' \+ tagIds/)
})
