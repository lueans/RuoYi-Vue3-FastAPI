import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const nodeTagSourceUrl = new URL('../../components/MindMap/NodeTag.vue', import.meta.url)

test('字段标签使用可聚焦按钮并公开展开和选中状态', async () => {
  const source = await readFile(nodeTagSourceUrl, 'utf8')

  assert.match(source, /class="fieldHeader"[\s\S]*:aria-expanded=/)
  assert.match(source, /:aria-controls="`field-options-\$\{field\.id\}`"/)
  assert.match(source, /class="optionBadge"[\s\S]*:aria-pressed=/)
  assert.match(source, /\.fieldHeader[\s\S]*&:focus-visible/)
  assert.match(source, /\.optionBadge[\s\S]*&:focus-visible/)
  assert.doesNotMatch(source, /<div class="fieldHeader"/)
  assert.doesNotMatch(source, /<span v-for="opt in field\.options"/)
})

test('字段加载和自定义标签创建具备失败恢复、竞态与重复提交保护', async () => {
  const source = await readFile(nodeTagSourceUrl, 'utf8')

  assert.match(source, /v-if="fieldsLoading"[\s\S]*正在加载字段标签/)
  assert.match(source, /v-else-if="fieldsError"[\s\S]*重新加载/)
  assert.match(source, /const requestId = \+\+fieldRequestId\.value/)
  assert.match(source, /requestId !== fieldRequestId\.value \|\| !dialogVisible\.value/)
  assert.match(
    source,
    /if \(isReadonly\.value \|\| customTagSubmitting\.value\) return[\s\S]*validateMindmapTagDisplayName\(tagInput\.value\)[\s\S]*if \(!validation\.valid\)/,
  )
  assert.match(source, /:loading="customTagSubmitting"/)
  assert.match(source, /if \(!isCurrentDialogSession\(sessionId\)\) return/)
  assert.match(source, /sessionId === dialogSessionId\.value[\s\S]*dialogVisible\.value[\s\S]*!isReadonly\.value/)
  assert.match(source, /tagInput\.value = ''[\s\S]*dialogVisible\.value = true/)
})

test('字段和选项可通过有界防抖搜索访问前 30 项之外的结果', async () => {
  const source = await readFile(nodeTagSourceUrl, 'utf8')

  assert.match(source, /aria-label="搜索字段或选项"/)
  assert.match(source, /:maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH"/)
  assert.match(source, /@input="scheduleFieldSearch"/)
  assert.match(source, /validateMindmapTagSearchKeyword\(fieldSearchKeyword\.value\)/)
  assert.match(source, /getTagFieldSuggestions\(keyword\.value \|\| undefined\)/)
  assert.match(source, /fieldRequestId\.value \+= 1[\s\S]*setTimeout\([\s\S]*void loadFields\(\)/)
  assert.match(source, /当前展示前 30 个字段，输入关键词可以搜索更多字段或选项/)
  assert.match(source, /function clearFieldSearchTimer\(\)/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*clearFieldSearchTimer\(\)/)
})
