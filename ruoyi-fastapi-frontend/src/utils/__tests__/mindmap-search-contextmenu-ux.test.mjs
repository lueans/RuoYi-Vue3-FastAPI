import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const searchSourceUrl = new URL('../../components/MindMap/Search.vue', import.meta.url)
const contextMenuSourceUrl = new URL('../../components/MindMap/Contextmenu.vue', import.meta.url)

test('节点搜索区分加载、失败、空结果并支持继续加载', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /v-show="show"/)
  assert.match(source, /role="search"/)
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
})

test('搜索结果高度跟随面板和短视口且卸载释放观察器', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /const panelBottom = searchContainerRef\.value\?\.getBoundingClientRect/)
  assert.match(source, /resolveMindmapSearchResultListHeight/)
  assert.match(source, /new ResizeObserver\(setSearchResultListHeight\)/)
  assert.match(source, /searchPanelResizeObserver\?\.disconnect\(\)/)
  assert.match(source, /@media \(max-height: 520px\)/)
  assert.match(source, /width: min\(296px, calc\(100vw - 24px\)\)/)
})

test('搜索请求绑定脑图实例、文件和查询条件并在切换时失效', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /const sessionMindMap = props\.mindMap/)
  assert.match(source, /const sessionMindmapId = Number\(props\.mindmapId\)/)
  assert.match(source, /const criteriaKey = getServerCriteriaKey\(sessionKeyword, sessionTagId\)/)
  assert.match(source, /props\.mindMap === mindMap/)
  assert.match(source, /Number\(props\.mindmapId\) === mindmapId/)
  assert.match(source, /getServerCriteriaKey\(\) === criteriaKey/)
  assert.match(source, /close\(\{ mindMap: oldMm, restoreFocus: false \}\)/)
  assert.match(source, /watch\(\(\) => props\.mindmapId,[\s\S]*close\(\{ restoreFocus: false \}\)/)
})

test('搜索替换在界面与核心插件边界都重新校验只读状态', async () => {
  const [source, plugin] = await Promise.all([
    readFile(searchSourceUrl, 'utf8'),
    readFile(
      new URL('../../libs/simple-mind-map/src/plugins/Search.js', import.meta.url),
      'utf8',
    ),
  ])

  assert.match(source, /:disabled="isReadonly" @click="showReplaceInput = true"/)
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
