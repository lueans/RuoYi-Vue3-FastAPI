import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const searchSourceUrl = new URL('../../components/MindMap/Search.vue', import.meta.url)
const contextMenuSourceUrl = new URL('../../components/MindMap/Contextmenu.vue', import.meta.url)
const renderSourceUrl = new URL(
  '../../libs/simple-mind-map/src/core/render/Render.js',
  import.meta.url,
)
const layoutBaseSourceUrl = new URL(
  '../../libs/simple-mind-map/src/layouts/Base.js',
  import.meta.url,
)
const mindMapNodeSourceUrl = new URL(
  '../../libs/simple-mind-map/src/core/render/node/MindMapNode.js',
  import.meta.url,
)

test('节点搜索区分加载、失败、空结果并支持继续加载', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /v-show="show"/)
  assert.match(source, /:role="panelMode === 'filter' \? 'dialog' : 'search'"/)
  assert.match(source, /const SERVER_SEARCH_PAGE_SIZE = 100/)
  assert.match(source, /function loadMoreServerResults\(\)/)
  assert.match(source, /function retryServerSearch\(\)/)
  assert.match(source, /searchError\.value = error\?\.response\?\.data\?\.msg/)
  assert.match(source, /if \(!isCurrentServerSearchSession\(requestId, sessionMindMap, sessionMindmapId, criteriaKey\)\) return/)
})

test('标签筛选加载具备失败重试、竞态取消和清空条件收口', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /aria-label="按统一标签筛选节点"/)
  assert.match(source, /v-if="tagOptionsError"[^>]*role="alert"/)
  assert.match(source, /const requestId = \+\+tagOptionsRequestId/)
  assert.match(source, /requestId !== tagOptionsRequestId \|\| !show\.value/)
  assert.match(source, /function onFilterChange\(\) \{\s*void onSearchNext\(\)/)
  assert.match(source, /if \(!keyword && !selectedTagId\.value\) \{\s*resetSearchResults\(\)/)
  assert.match(source, /function close\(options = \{\}\)[\s\S]*tagOptionsRequestId \+= 1/)
})

test('节点搜索结果和关闭入口使用可聚焦控件与读屏状态', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /type="button" aria-label="关闭搜索"/)
  assert.match(source, /role="listbox"/)
  assert.match(source, /role="option"/)
  assert.match(source, /:aria-selected="currentIndex === index \+ 1"/)
  assert.match(source, /:aria-busy="searching \|\| loadingMore"/)
  assert.match(source, /\{\{ segment\.text \}\}/)
  assert.doesNotMatch(source, /v-html="item\.text"/)
})

test('节点搜索结果支持组合框关联、漫游焦点和完整方向键导航', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /role="combobox"/)
  assert.match(source, /aria-controls="mindmap-search-results"/)
  assert.match(source, /:aria-activedescendant="activeSearchResultId \|\| undefined"/)
  assert.match(source, /:tabindex="currentIndex === index \+ 1 \? 0 : -1"/)
  assert.match(source, /:aria-posinset="index \+ 1"/)
  assert.match(source, /:aria-setsize="total"/)
  assert.match(source, /resolveMindmapSearchNavigationIndex/)
  for (const key of ['ArrowDown', 'ArrowUp', 'Home', 'End']) {
    assert.equal(source.includes(`'${key}'`), true)
  }
  assert.match(source, /option\?\.scrollIntoView\?\.\(\{ block: 'nearest' \}\)/)
  assert.match(source, /if \(focus\) option\?\.focus\?\.\(\)/)
  assert.match(source, /pathText: getMindmapNodePathText\(item, treeIndex\)/)
  assert.match(source, /treeIndex\?\.parentUidByUid\?\.get\(uid\)/)
})

test('移动宽度下搜索与右侧面板互斥，避免完全遮挡画布', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /function showSearch\(\)[\s\S]*window\.innerWidth <= 760[\s\S]*actions\.setActiveSidebar\(null\)/)
  assert.match(source, /function handleSearchPanelResize\(\)[\s\S]*window\.innerWidth <= 760[\s\S]*actions\.setActiveSidebar\(null\)/)
  assert.match(source, /watch\(\(\) => store\.activeSidebar,[\s\S]*window\.innerWidth <= 760[\s\S]*close\(\{ restoreFocus: false \}\)/)
})

test('搜索结果占满停靠面板并在短视口下保持可滚动且卸载释放观察器', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /const panelBottom = searchContainerRef\.value\?\.getBoundingClientRect/)
  assert.match(source, /resolveMindmapSearchResultListHeight/)
  assert.match(source, /new ResizeObserver\(setSearchResultListHeight\)/)
  assert.match(source, /searchPanelResizeObserver\?\.disconnect\(\)/)
  assert.match(source, /@media \(max-height: 520px\)/)
  assert.match(source, /width: 280px/)
  assert.match(source, /bottom: var\(--mindmap-workspace-bottom, 30px\)/)
  assert.match(source, /height: auto !important/)
})

test('搜索请求绑定脑图实例、文件和查询条件并在切换时失效', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /const sessionMindMap = props\.mindMap/)
  assert.match(source, /const sessionMindmapId = Number\(props\.mindmapId\)/)
  assert.match(source, /const criteriaKey = getServerCriteriaKey\(sessionKeyword, sessionTagId\)/)
  assert.match(source, /props\.mindMap === mindMap/)
  assert.match(source, /Number\(props\.mindmapId\) === mindmapId/)
  assert.match(source, /getServerCriteriaKey\(\) === criteriaKey/)
  assert.match(source, /close\(\{ mindMap: oldMm, restoreFocus: false, forceReset: true \}\)/)
  assert.match(source, /watch\(\(\) => props\.mindmapId,[\s\S]*close\(\{ restoreFocus: false, forceReset: true \}\)/)
  assert.match(source, /onDocumentReplace\(\)[\s\S]*close\(\{ restoreFocus: false, forceReset: true \}\)/)
  assert.match(source, /function resetSearchResults\(mindMap = props\.mindMap, \{ preserveCanvasFilter = false \} = \{\}\)[\s\S]*restoreCanvasVisibility\(\{ mindMap \}\)/)
})

test('搜索替换在界面与核心插件边界都重新校验只读状态', async () => {
  const [source, plugin] = await Promise.all([
    readFile(searchSourceUrl, 'utf8'),
    readFile(
      new URL('../../libs/simple-mind-map/src/plugins/Search.js', import.meta.url),
      'utf8',
    ),
  ])

  assert.match(source, /:disabled="isReadonly \|\| serverSearchMode"[\s\S]*?@click="showReplaceInput = true"/)
  assert.equal((source.match(/if \(isReadonly\.value \|\| !show\.value/g) || []).length, 2)
  assert.match(source, /watch\(isReadonly,[\s\S]*hideReplaceInput\(\)/)
  assert.match(plugin, /rejectReadonlyReplace\('SEARCH_REPLACE'\)/)
  assert.match(plugin, /rejectReadonlyReplace\('SEARCH_REPLACE_ALL'\)/)
})

test('搜索输入临时暂停按键编辑并恢复用户原配置', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /previousAutoEnterTextEdit = mindMap\.getConfig\?\.\('enableAutoEnterTextEditWhenKeydown'\) !== false/)
  assert.match(source, /function restoreAutoEnterTextEdit\(\)/)
  assert.match(source, /enableAutoEnterTextEditWhenKeydown: previousAutoEnterTextEdit/)
  assert.doesNotMatch(source, /enableAutoEnterTextEditWhenKeydown: true/)
  assert.match(source, /function close\(options = \{\}\)[\s\S]*?restoreAutoEnterTextEdit\(\)/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*?restoreAutoEnterTextEdit\(\)/)
})

test('节点搜索支持实时反馈并在任意焦点位置接管跨平台查找快捷键', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /const LIVE_SEARCH_DELAY = 220/)
  assert.match(source, /function scheduleLiveSearch\(keyword\)/)
  assert.match(source, /liveSearchTimer = setTimeout\(\(\) => \{[\s\S]*startLocalSearch\(keyword\)/)
  assert.match(source, /event\.ctrlKey \|\| event\.metaKey/)
  assert.match(source, /window\.addEventListener\('keydown', handleGlobalSearchShortcut, true\)/)
  assert.match(source, /window\.removeEventListener\('keydown', handleGlobalSearchShortcut, true\)/)
})

test('画布筛选从完整文档树计算命中节点并保留祖先路径', async () => {
  const [source, mindMapNodeSource] = await Promise.all([
    readFile(searchSourceUrl, 'utf8'),
    readFile(mindMapNodeSourceUrl, 'utf8'),
  ])

  assert.match(source, /aria-label="画布节点筛选"/)
  assert.match(source, /function applyCanvasFilter\(\)/)
  assert.match(source, /function getDocumentFilterMatches\(keyword = searchText\.value\.trim\(\)\)/)
  assert.match(source, /const root = props\.mindMap\?\.renderer\?\.renderTree/)
  assert.match(source, /data\.text !== undefined && data\.text !== null/)
  assert.match(source, /return String\(node\?\.group\?\.node\?\.textContent \?\? ''\)\.trim\(\)/)
  assert.doesNotMatch(source, /syncRuntimeKeywordResults/)
  assert.match(source, /function createDocumentTreeIndex\(root\)/)
  assert.match(source, /parentUidByUid\.set\(uid, parentUid\)/)
  assert.match(source, /uid = parentUidByUid\.get\(uid\) \?\? null/)
  assert.match(source, /walkDocumentNodeTree\(root, visit\)/)
  assert.match(source, /addClass\?\.\('smm-filter-hidden'\)/)
  assert.match(source, /removeClass\?\.\('smm-filter-hidden'\)/)
  assert.match(mindMapNodeSource, /line\.__smmFilterOwnerUid = String\(this\.uid\)/)
  assert.match(mindMapNodeSource, /line\.__smmFilterTargetUid = String\(targetNode\.uid\)/)
  assert.match(mindMapNodeSource, /line\.__smmFilterRenderVersion = lineRenderVersion/)
  assert.match(source, /const ownerUid = line\?\.__smmFilterOwnerUid[\s\S]*?const targetUid = line\?\.__smmFilterTargetUid[\s\S]*?const lineRenderVersion = line\?\.__smmFilterRenderVersion/)
  assert.match(source, /lineRenderVersion === node\._lineRenderVersion/)
  assert.match(source, /isSharedBranchLine[\s\S]*?Boolean\(node\.children\?\.length\)[\s\S]*?visibleNodeUids\.has\(targetUid\)/)
  assert.doesNotMatch(source, /node\.parent\._lines\?\.\[childIndex\]/)
  assert.match(source, /setTransientVisibleNodeUids\?\.\(visibleNodeUids\)/)
  assert.match(source, /clearTransientVisibleNodeUids\?\.\(clearElements\)/)
  const applyFilterSource = source.slice(
    source.indexOf('function applyCanvasFilter()'),
    source.indexOf('function toggleCanvasFilter()'),
  )
  assert.match(applyFilterSource, /filteredMatchCount\.value = 0/)
  assert.doesNotMatch(applyFilterSource, /restoreCanvasVisibility/)
  assert.match(source, /mm\.on\('node_tree_render_end', reapplyCanvasFilter\)/)
  assert.doesNotMatch(source, /renderer\?\.setData|mindMap\?\.setData/)
  assert.match(source, /nodeHasSelectedTag\(node\)[\s\S]*Number\(tag\.tagId\) === tagId/)
  assert.doesNotMatch(source, /searchResultList\.value\.map\(resolveResultRuntimeNode\)/)
})

test('搜索筛选不会在重排后清空隐藏标记，修改关键词时保持筛选状态', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /const activeCanvasFilterSource = ref\(null\)/)
  assert.match(source, /const searchCanvasFilterActive = computed\(\(\) => \([\s\S]*activeCanvasFilterSource\.value === 'search'/)
  assert.match(source, /function resetSearchResults\(mindMap = props\.mindMap, \{ preserveCanvasFilter = false \} = \{\}\)/)
  assert.match(source, /preserveCanvasFilter && filterActive\.value[\s\S]*reapplyCanvasFilter\(\)/)
  assert.match(source, /String\(val \|\| ''\)\.trim\(\) !== activeLocalKeyword[\s\S]*preserveCanvasFilter: filterActive\.value/)
})

test('普通搜索与高级条件筛选使用独立来源，互不抢占匹配规则', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /activeCanvasFilterSource\.value === 'search' && selectedTagId\.value/)
  assert.match(source, /if \(activeCanvasFilterSource\.value === 'search'\) \{[\s\S]*getMindmapNodeText\(node\)\.includes\(keyword\)/)
  assert.match(source, /if \(activeCanvasFilterSource\.value !== 'conditions'\) return \[\]/)
  assert.match(source, /activeCanvasFilterSource\.value = 'conditions'[\s\S]*filterActive\.value = true/)
  assert.match(source, /activeCanvasFilterSource\.value = 'search'[\s\S]*filterActive\.value = true/)
})

test('画布筛选以临时可见集合局部刷新布局并对重复集合去重', async () => {
  const [renderSource, layoutSource] = await Promise.all([
    readFile(renderSourceUrl, 'utf8'),
    readFile(layoutBaseSourceUrl, 'utf8'),
  ])

  assert.match(renderSource, /this\.transientVisibleNodeUids = null/)
  assert.match(renderSource, /isSameTransientVisibleNodeUids\(nextNodeUids\)/)
  assert.match(renderSource, /setTransientVisibleNodeUids\(nodeUids, callback\)/)
  assert.match(renderSource, /this\.mindMap\.render\(callback, 'transient_node_filter'\)/)
  assert.match(renderSource, /clearTransientVisibleNodeUids\(callback\)/)
  assert.match(renderSource, /isNodeTransientlyVisible\(uid, isRoot = false\)/)
  assert.match(renderSource, /isNodeExpandedForLayout\(node\)/)
  assert.match(renderSource, /this\.transientVisibleNodeUids\.has\(String\(child\?\.data\?\.uid\)\)/)
  assert.match(layoutSource, /else if \(this\.renderer\.isNodeTransientlyVisible\(newNode\.uid\)\)/)
  assert.doesNotMatch(renderSource, /setTransientVisibleNodeUids[\s\S]{0,800}setData\(/)
})

test('筛选稀疏运行时树上的结构命令只按完整数据树 UID 修改节点', async () => {
  const renderSource = await readFile(renderSourceUrl, 'utf8')

  assert.match(renderSource, /upNode\(appointNode\)[\s\S]*?const nodeDataIndex = getNodeDataIndex\(node\)[\s\S]*?const previousNodeDataIndex = getNodeDataIndex\(previousNode\)/)
  assert.match(renderSource, /downNode\(appointNode\)[\s\S]*?const nodeDataIndex = getNodeDataIndex\(node\)[\s\S]*?const nextNodeDataIndex = getNodeDataIndex\(nextNode\)/)
  assert.match(renderSource, /moveUpOneLevel\(node\)[\s\S]*?const index = getNodeDataIndex\(node\)[\s\S]*?const parentIndex = getNodeDataIndex\(parent\)/)
  assert.match(renderSource, /insertTo\(node, exist, dir = 'before'\)[\s\S]*?const nodeIndex = getNodeDataIndex\(item\)[\s\S]*?let existIndex = getNodeDataIndex\(exist\)/)
  assert.doesNotMatch(renderSource, /nodeBorthers|existBorthers/)
})

test('筛选面板复刻飞书的条件行、增删清空与确认结构', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /设置筛选条件/)
  assert.match(source, /class="filterConditionRow"/)
  assert.match(source, /placeholder="请选择运算符"/)
  assert.match(source, /placeholder="请输入字段值"/)
  assert.match(source, /function addFilterCondition\(\)/)
  assert.match(source, /function removeFilterCondition\(index\)/)
  assert.match(source, /function clearFilterConditions\(\)/)
  assert.match(source, /function confirmFilterConditions\(\)/)
  assert.match(source, /class="filterDialogActions"/)
  assert.match(source, /const titleRows = activeRows\.filter\(row => row\.field === 'title'\)/)
  assert.match(source, /const anyNodeRows = activeRows\.filter\(row => row\.field !== 'title'\)/)
  assert.match(source, /isMindmapCaseTitleData\(data\)[\s\S]*?titleRows\.every/)
  assert.match(source, /matchedCaseTitleNodes\.forEach\(caseTitleNode => \{[\s\S]*?walkDocumentNodeTree\(caseTitleNode/)
})

test('上下文菜单使用数据驱动定义、原生禁用和标准键盘导航', async () => {
  const source = await readFile(contextMenuSourceUrl, 'utf8')

  assert.equal(/<div[^>]*class="item"[^>]*@click/.test(source), false)
  assert.match(source, /const nodeMenuGroups = computed/)
  assert.match(source, /const canvasMenuGroups = computed/)
  assert.match(source, /role="menuitem"/)
  assert.match(source, /:disabled="isMenuItemDisabled\(item\)"/)
  assert.match(source, /if \(isReadonly\.value && item\.write\) return false/)
  for (const key of ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End', 'Escape']) {
    assert.equal(source.includes(`'${key}'`), true)
  }
})
