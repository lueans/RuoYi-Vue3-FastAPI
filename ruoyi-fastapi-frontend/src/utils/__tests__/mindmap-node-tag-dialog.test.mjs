import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const nodeTagSourceUrl = new URL('../../components/MindMap/NodeTag.vue', import.meta.url)

test('节点标签弹窗按分组规则展示统一标签选择入口', async () => {
  const source = await readFile(nodeTagSourceUrl, 'utf8')

  assert.match(source, /class="mindmap-node-tag-dialog"/)
  assert.match(source, /aria-label="搜索标签"/)
  assert.match(source, /getTagSuggestions\(keyword\.value \|\| undefined\)/)
  assert.match(source, /class="suggestionTag"[\s\S]*:aria-pressed="isSelected\(tag\.id\)"/)
  assert.match(source, /function toggleSuggestion\(tag\)/)
  assert.match(source, /placement: style\.placement/)
  assert.match(source, /align: style\.align/)
  assert.match(source, /最多添加 \$\{MAX_NODE_TAG_COUNT\} 个标签/)
  assert.match(source, /normalizeMindmapSingleSelectionTags/)
  assert.match(source, /removeMindmapSingleSelectionPeers/)
  assert.doesNotMatch(source, /tag-field|fieldId|optionId|selectMode/)
})

test('统一标签选择器使用左侧分组、右侧标签的主从布局并保留未分组降级', async () => {
  const source = await readFile(nodeTagSourceUrl, 'utf8')

  assert.match(source, /listTagCategories/)
  assert.match(source, /const groupedSuggestions = computed/)
  assert.match(source, /class="suggestionBrowser"/)
  assert.match(source, /class="suggestionGroupSidebar"/)
  assert.match(source, /class="suggestionGroupContent"/)
  assert.match(source, /const activeSuggestionGroup = computed/)
  assert.match(source, /activeGroupId\.value = groups\[0\]\?\.id \|\| ''/)
  assert.match(source, /name: '未分组'/)
  assert.match(source, /tag\.categoryId == null/)
  assert.match(source, /选择规则暂不可用/)
  assert.match(source, /listTags\(\{ pageNum, pageSize: 100 \}\)/)
})

test('统一标签搜索和创建具备防抖、竞态与重复提交保护', async () => {
  const source = await readFile(nodeTagSourceUrl, 'utf8')

  assert.match(source, /@input="scheduleSearch"/)
  assert.match(source, /validateMindmapTagSearchKeyword\(searchKeyword\.value\)/)
  assert.match(source, /const currentRequestId = \+\+requestId\.value/)
  assert.match(source, /currentRequestId !== requestId\.value \|\| !dialogVisible\.value/)
  assert.match(source, /if \(isReadonly\.value \|\| creating\.value\) return/)
  assert.match(source, /validateMindmapTagDisplayName\(searchKeyword\.value\)/)
  assert.match(source, /if \(!isCurrentDialogSession\(sessionId\)\) return/)
  assert.match(source, /function clearSearchTimer\(\)/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*clearSearchTimer\(\)/)
})

test('标签弹窗保持受控高度和键盘焦点', async () => {
  const source = await readFile(nodeTagSourceUrl, 'utf8')

  assert.match(source, /:z-index="4200"/)
  assert.match(source, /max-height:\s*calc\(100dvh - 32px\)/)
  assert.match(source, /\.mindmap-node-tag-dialog \.el-dialog__body[\s\S]*overflow-y:\s*auto/)
  assert.match(source, /nextTick\(\(\) => inputRef\.value\?\.focus\(\)\)/)
  assert.match(source, /\.suggestionTag[\s\S]*&:focus-visible/)
})
