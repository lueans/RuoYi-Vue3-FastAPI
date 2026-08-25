<template>
  <div
    v-show="show"
    ref="searchContainerRef"
    class="searchContainer"
    :class="{ isDark: isDark, filterDialog: panelMode === 'filter' }"
    :role="panelMode === 'filter' ? 'dialog' : 'search'"
    :aria-modal="panelMode === 'filter' ? 'false' : undefined"
    :aria-label="panelMode === 'filter' ? '设置筛选条件' : '搜索脑图节点'"
    @keydown.esc.stop="close()"
  >
    <template v-if="panelMode === 'filter'">
      <header class="filterDialogHeader">
        <h2>设置筛选条件</h2>
        <button type="button" aria-label="关闭筛选条件" @click="close()">
          <el-icon><Close /></el-icon>
        </button>
      </header>
      <div class="filterConditionList">
        <div v-for="(row, index) in filterRows" :key="row.id" class="filterConditionRow">
          <el-select v-model="row.field" aria-label="筛选字段" size="small">
            <el-option label="用例标题" value="title" />
            <el-option label="任意节点名称" value="any" />
          </el-select>
          <el-select v-model="row.operator" aria-label="筛选运算符" size="small" placeholder="请选择运算符">
            <el-option label="包含" value="contains" />
            <el-option label="等于" value="equals" />
            <el-option label="不包含" value="notContains" />
            <el-option label="不等于" value="notEquals" />
          </el-select>
          <el-input
            v-model="row.value"
            aria-label="筛选目标值"
            placeholder="请输入字段值"
            maxlength="200"
            size="small"
            @keyup.enter.stop="confirmFilterConditions"
          />
          <el-button
            class="removeConditionButton"
            text
            type="danger"
            circle
            :aria-label="`删除第 ${index + 1} 个筛选条件`"
            @click="removeFilterCondition(index)"
          >
            <el-icon><RemoveFilled /></el-icon>
          </el-button>
        </div>
      </div>
      <footer class="filterDialogFooter">
        <el-button class="addConditionButton" size="small" @click="addFilterCondition">
          <el-icon><CirclePlusFilled /></el-icon>
          添加条件
        </el-button>
        <div class="filterDialogActions">
          <el-button size="small" @click="clearFilterConditions">清空筛选条件</el-button>
          <el-button type="primary" size="small" @click="confirmFilterConditions">确认</el-button>
        </div>
      </footer>
    </template>
    <template v-else>
    <header class="searchPanelHeader">
      <div class="searchPanelHeading">
        <strong>搜索与替换</strong>
        <span>在当前脑图中定位节点</span>
      </div>
      <button class="closeBtnBox" type="button" aria-label="关闭搜索" @click="close()">
        <el-icon><Close /></el-icon>
      </button>
    </header>
    <div class="searchModeTabs" role="tablist" aria-label="搜索模式">
      <button
        type="button"
        role="tab"
        :aria-selected="!showReplaceInput"
        :class="{ active: !showReplaceInput }"
        @click="hideReplaceInput"
      >
        搜索
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="showReplaceInput"
        :class="{ active: showReplaceInput }"
        :disabled="isReadonly || serverSearchMode"
        @click="showReplaceInput = true"
      >
        替换
      </button>
    </div>
    <div class="searchInputBox">
      <el-input
        ref="searchInputRef"
        placeholder="搜索节点"
        aria-label="节点搜索关键词"
        role="combobox"
        aria-controls="mindmap-search-results"
        aria-haspopup="listbox"
        :aria-expanded="showSearchResultList"
        :aria-activedescendant="activeSearchResultId || undefined"
        maxlength="200"
        size="small"
        v-model="searchText"
        @keyup.enter.stop="onSearchNext"
        @keydown="onSearchFieldKeydown($event, true)"
        @focus="onFocus"
        @blur="onBlur"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <div
        class="searchInfo"
        v-if="showSearchInfo && (searchText || selectedTagId)"
        role="status"
        aria-live="polite"
      >
        {{ currentIndex }} / {{ total }}
      </div>
    </div>
    <el-select
      v-model="selectedTagId" clearable filterable size="small"
      aria-label="按统一标签筛选节点"
      placeholder="按标签缩小范围（可选）" class="tagFilterSelect"
      :loading="tagOptionsLoading"
      :disabled="tagOptionsLoading && normalizedTagOptions.length === 0"
      :no-data-text="tagOptionsError ? '标签加载失败' : '暂无可用标签'"
      @change="onFilterChange"
    >
      <el-option
        v-for="tag in normalizedTagOptions" :key="tag.id"
        :label="tag.optionLabel" :value="tag.id"
      />
    </el-select>
    <div v-if="tagOptionsError" class="tagFilterState" role="alert">
      <span>{{ tagOptionsError }}</span>
      <el-button link type="primary" size="small" :loading="tagOptionsLoading" @click="loadTagOptions">
        重新加载标签
      </el-button>
    </div>
    <div class="canvasFilterBar" role="group" aria-label="画布节点筛选">
      <el-button
        size="small"
        :type="searchCanvasFilterActive ? 'primary' : 'default'"
        :disabled="!hasFilterCriteria"
        :aria-pressed="searchCanvasFilterActive"
        @click="toggleCanvasFilter"
      >
        <el-icon><Filter /></el-icon>
        {{ searchCanvasFilterActive ? '退出筛选' : '筛选画布' }}
      </el-button>
      <span :class="{ active: searchCanvasFilterActive }">
        {{ searchCanvasFilterActive ? `已显示 ${filteredMatchCount} 个匹配节点及其路径` : '仅保留匹配节点及其路径' }}
      </span>
    </div>
    <el-input
      v-if="showReplaceInput && !serverSearchMode"
      ref="replaceInputRef"
      placeholder="请输入替换内容"
      aria-label="节点替换内容"
      maxlength="20000"
      size="small"
      v-model="replaceText"
      style="margin: 12px 0;"
      @keydown="onSearchFieldKeydown($event, false)"
      @focus="onFocus"
      @blur="onBlur"
    >
      <template #prefix>
        <el-icon><Edit /></el-icon>
      </template>
      <template #append>
        <el-button size="small" @click="hideReplaceInput">取消</el-button>
      </template>
    </el-input>
    <div class="btnList" v-if="showReplaceInput && !serverSearchMode">
      <el-button size="small" :disabled="isReadonly" @click="doReplace">替换</el-button>
      <el-button size="small" :disabled="isReadonly" @click="doReplaceAll">全部替换</el-button>
    </div>
    <div v-if="showSearchResultList" class="searchResultSummary">
      <strong>{{ total }} 个结果</strong>
      <span>回车切换，点击定位</span>
    </div>
    <div
      id="mindmap-search-results"
      ref="searchResultListRef"
      class="searchResultList"
      :style="{ '--search-result-fallback-height': searchResultListHeight + 'px' }"
      v-if="showSearchResultList"
      role="listbox"
      aria-label="节点搜索结果"
      :aria-busy="searching || loadingMore"
    >
      <div class="searchState" v-if="searching" role="status" aria-live="polite">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在搜索节点…</span>
      </div>
      <template v-else>
        <button
          class="searchResultItem"
          v-for="(item, index) in searchResultList"
          :key="item.id"
          :id="getSearchResultOptionId(index)"
          :data-search-result-index="index"
          type="button"
          role="option"
          :aria-selected="currentIndex === index + 1"
          :aria-posinset="index + 1"
          :aria-setsize="total"
          :tabindex="currentIndex === index + 1 ? 0 : -1"
          :title="item.name"
          @click.stop="onSearchResultItemClick(index)"
          @keydown="onSearchResultKeydown($event)"
        >
          <div class="resultText">
            <span
              v-for="(segment, segmentIndex) in item.segments"
              :key="segmentIndex"
              :class="{ match: segment.match }"
            >{{ segment.text }}</span>
          </div>
          <div v-if="item.pathText" class="resultPath" :title="item.pathText">{{ item.pathText }}</div>
        </button>
      </template>
      <div class="searchState error" v-if="!searching && searchError" role="alert">
        <span>{{ searchError }}</span>
        <el-button link type="primary" size="small" @click="retryServerSearch">重试</el-button>
      </div>
      <div class="searchState" v-else-if="hasMoreServerResults || loadingMore">
        <el-button
          link
          type="primary"
          size="small"
          :loading="loadingMore"
          @click="loadMoreServerResults"
        >
          {{ loadingMore ? '加载中…' : `加载更多（已显示 ${searchResultList.length}/${total}）` }}
        </el-button>
      </div>
      <div class="empty" v-if="!searching && !searchError && searchResultList.length <= 0">
        <span class="iconfont iconwushuju"></span>
        <span class="text">暂无结果</span>
      </div>
    </div>
    </template>
  </div>
</template>

<script setup>
import { CirclePlusFilled, Close, Edit, Filter, Loading, RemoveFilled, Search } from '@element-plus/icons-vue'
import bus from './useEventBus'
import { actions, store } from './useStore'
import { getTagSuggestions } from '@/api/mindmap/tag'
import { searchMindmapNodes } from '@/api/mindmap/mindmap'
import {
  buildMindmapSearchHighlightSegments,
  buildMindmapTagFilterOptions,
  isMindmapCaseTitleData,
  matchesMindmapFilterText,
  resolveMindmapSearchNavigationIndex,
  resolveMindmapSearchResultListHeight,
} from '@/utils/mindmap-search'

const props = defineProps({
  mindMap: { type: Object, default: null },
  mindmapId: { type: Number, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)

const show = ref(false)
const panelMode = ref('search')
let filterRowSequence = 2
const createFilterRow = (field = 'any') => ({
  id: ++filterRowSequence,
  field,
  operator: 'contains',
  value: '',
})
const filterRows = ref([
  { id: 1, field: 'title', operator: 'contains', value: '' },
  { id: 2, field: 'any', operator: 'contains', value: '' },
])
const confirmedFilterRows = ref([])
const searchText = ref('')
const replaceText = ref('')
const showReplaceInput = ref(false)
const currentIndex = ref(0)
const total = ref(0)
const showSearchInfo = ref(false)
const searchResultListHeight = ref(0)
const searchResultList = ref([])
const showSearchResultList = ref(false)
const searchContainerRef = ref(null)
const searchResultListRef = ref(null)
const searchInputRef = ref(null)
const replaceInputRef = ref(null)
const selectedTagId = ref(null)
const tagOptions = ref([])
const normalizedTagOptions = computed(() => buildMindmapTagFilterOptions(tagOptions.value))
const tagOptionsLoading = ref(false)
const tagOptionsError = ref('')
const serverSearchMode = ref(false)
const searching = ref(false)
const loadingMore = ref(false)
const searchError = ref('')
const serverPageNum = ref(0)
const filterActive = ref(false)
const activeCanvasFilterSource = ref(null)
const filteredMatchCount = ref(0)
let searchRequestId = 0
let tagOptionsRequestId = 0
let focusReturnTarget = null
let autoEnterConfigOwner = null
let previousAutoEnterTextEdit = null
let componentAlive = true
let activeServerCriteriaKey = ''
let activeLocalKeyword = ''
let searchPanelResizeObserver = null
let liveSearchTimer = null
const filteredCanvasElements = new Set()

const SERVER_SEARCH_PAGE_SIZE = 100
const LIVE_SEARCH_DELAY = 220
const hasMoreServerResults = computed(() => (
  serverSearchMode.value && searchResultList.value.length < total.value
))
const hasFilterCriteria = computed(() => Boolean(searchText.value.trim() || selectedTagId.value))
const searchCanvasFilterActive = computed(() => (
  filterActive.value && activeCanvasFilterSource.value === 'search'
))
const activeSearchResultId = computed(() => {
  const index = currentIndex.value - 1
  return index >= 0 && index < searchResultList.value.length
    ? getSearchResultOptionId(index)
    : ''
})

function isUndef(val) {
  return val === undefined || val === null || val === ''
}

function getSearchResultOptionId(index) {
  return `mindmap-search-result-${index}`
}

function revealSearchResult(index, focus = false) {
  nextTick(() => {
    if (!componentAlive || !show.value || index < 0) return
    const option = searchResultListRef.value?.querySelector?.(
      `[data-search-result-index="${index}"]`,
    )
    option?.scrollIntoView?.({ block: 'nearest' })
    if (focus) option?.focus?.()
  })
}

function activateSearchResult(index, { focus = false } = {}) {
  if (!Number.isSafeInteger(index) || index < 0) return false
  const item = searchResultList.value[index]
  if (!item) return false

  currentIndex.value = index + 1
  if (serverSearchMode.value) {
    props.mindMap?.execCommand?.('GO_TARGET_NODE', item.nodeUid)
  } else {
    props.mindMap?.search?.jump?.(index)
  }
  revealSearchResult(index, focus)
  return true
}

function setCanvasElementFiltered(element, hidden) {
  if (!element) return
  if (hidden) {
    element.addClass?.('smm-filter-hidden')
    filteredCanvasElements.add(element)
  } else {
    element.removeClass?.('smm-filter-hidden')
    filteredCanvasElements.delete(element)
  }
}

function clearFilteredCanvasElements() {
  filteredCanvasElements.forEach(element => element?.removeClass?.('smm-filter-hidden'))
  filteredCanvasElements.clear()
}

function restoreCanvasVisibility({
  deactivate = true,
  relayout = true,
  mindMap = props.mindMap,
} = {}) {
  filteredMatchCount.value = 0
  if (deactivate) {
    filterActive.value = false
    activeCanvasFilterSource.value = null
  }
  const clearElements = () => clearFilteredCanvasElements()
  const relayoutScheduled = relayout
    && mindMap?.renderer?.clearTransientVisibleNodeUids?.(clearElements)
  if (!relayoutScheduled) clearElements()
}

function walkRuntimeNodeTree(root, visit) {
  if (!root || typeof visit !== 'function') return
  const visited = new WeakSet()
  const stack = [root]
  while (stack.length > 0) {
    const node = stack.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    visit(node)
    const children = Array.isArray(node.children) ? node.children : []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push(children[index])
    }
  }
}

function walkDocumentNodeTree(root, visit) {
  if (!root || typeof visit !== 'function') return
  const visited = new WeakSet()
  const stack = [{ node: root, parentUid: null }]
  while (stack.length > 0) {
    const { node, parentUid } = stack.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    visit(node, parentUid)
    const nodeUid = getMindmapNodeUid(node)
    const children = Array.isArray(node?.nodeData?.children)
      ? node.nodeData.children
      : (Array.isArray(node.children) ? node.children : [])
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push({ node: children[index], parentUid: nodeUid })
    }
  }
}

function getMindmapNodeData(node) {
  return node?.nodeData?.data || node?.data || {}
}

function getMindmapNodeUid(node) {
  const uid = node?.uid ?? getMindmapNodeData(node).uid
  return uid === undefined || uid === null ? null : String(uid)
}

function getMindmapNodeText(node) {
  const data = getMindmapNodeData(node)
  if (data.text !== undefined && data.text !== null) {
    const rawText = String(data.text)
    if (!data.richText) return rawText
    const template = document.createElement('template')
    template.innerHTML = rawText
    return template.content.textContent || ''
  }
  // 仅在数据节点没有 text 字段时才回退到渲染文本。节点容器中还会包含
  // 标签、优先级等后缀，优先读取整组 textContent 会让路径和搜索条件误命中。
  return String(node?.group?.node?.textContent ?? '').trim()
}

function getMindmapNodePathText(node, treeIndex) {
  const path = []
  const visited = new WeakSet()
  let current = node?.parent || null
  while (current && typeof current === 'object' && !visited.has(current)) {
    visited.add(current)
    const text = getMindmapNodeText(current).trim()
    if (text) path.unshift(text)
    current = current.parent || null
  }
  if (path.length > 0) return path.join(' / ')

  const uid = getMindmapNodeUid(node)
  const visitedUids = new Set()
  let parentUid = uid === null ? null : treeIndex?.parentUidByUid?.get(uid)
  while (parentUid !== null && parentUid !== undefined && !visitedUids.has(parentUid)) {
    visitedUids.add(parentUid)
    const parentNode = treeIndex?.nodeByUid?.get(parentUid)
    const text = getMindmapNodeText(parentNode).trim()
    if (text) path.unshift(text)
    parentUid = treeIndex?.parentUidByUid?.get(parentUid)
  }
  return path.join(' / ')
}

function nodeHasSelectedTag(node) {
  const tagId = Number(selectedTagId.value)
  if (!Number.isSafeInteger(tagId) || tagId <= 0) return true
  const tags = Array.isArray(getMindmapNodeData(node).tag)
    ? getMindmapNodeData(node).tag
    : []
  return tags.some(tag => (
    typeof tag === 'object' && tag !== null && Number(tag.tagId) === tagId
  ))
}

function getDocumentFilterMatches(keyword = searchText.value.trim()) {
  const root = props.mindMap?.renderer?.renderTree
  if (!root) return []
  if (activeCanvasFilterSource.value === 'search' && selectedTagId.value) {
    const matches = []
    walkDocumentNodeTree(root, node => {
      if (
        nodeHasSelectedTag(node)
        && (!keyword || getMindmapNodeText(node).includes(keyword))
      ) {
        matches.push(node)
      }
    })
    return matches
  }
  if (activeCanvasFilterSource.value === 'search') {
    if (!keyword) return []
    const matches = []
    walkDocumentNodeTree(root, node => {
      if (getMindmapNodeText(node).includes(keyword)) matches.push(node)
    })
    return matches
  }
  if (activeCanvasFilterSource.value !== 'conditions') return []
  const activeRows = confirmedFilterRows.value
  if (activeRows.length > 0) {
    const titleRows = activeRows.filter(row => row.field === 'title')
    const anyNodeRows = activeRows.filter(row => row.field !== 'title')
    const matchesAnyNodeRows = node => {
      const nodeText = getMindmapNodeText(node)
      return anyNodeRows.every(row => (
        matchesMindmapFilterText(nodeText, row.operator, row.value)
      ))
    }
    if (titleRows.length === 0) {
      const matches = []
      walkDocumentNodeTree(root, node => {
        if (matchesAnyNodeRows(node)) matches.push(node)
      })
      return matches
    }

    // 飞书脑图的一份文档可包含多条用例；本地数据用“用例标题”标签标记
    // 用例根节点。标题条件只匹配这些节点，任意节点条件再限定到命中用例
    // 的子树，避免普通分支名称误命中“用例标题”。
    const matchedCaseTitleNodes = []
    walkDocumentNodeTree(root, node => {
      const data = getMindmapNodeData(node)
      const nodeText = getMindmapNodeText(node)
      if (
        isMindmapCaseTitleData(data)
        && titleRows.every(row => (
          matchesMindmapFilterText(nodeText, row.operator, row.value)
        ))
      ) {
        matchedCaseTitleNodes.push(node)
      }
    })
    if (anyNodeRows.length === 0) return matchedCaseTitleNodes

    const matches = new Set()
    matchedCaseTitleNodes.forEach(caseTitleNode => {
      walkDocumentNodeTree(caseTitleNode, node => {
        if (matchesAnyNodeRows(node)) matches.add(node)
      })
    })
    return Array.from(matches)
  }
  return []
}

function createDocumentTreeIndex(root) {
  const parentUidByUid = new Map()
  const nodeByUid = new Map()
  walkDocumentNodeTree(root, (node, parentUid) => {
    const uid = getMindmapNodeUid(node)
    if (uid === null) return
    parentUidByUid.set(uid, parentUid)
    nodeByUid.set(uid, node)
  })
  return { parentUidByUid, nodeByUid }
}

function applyCanvasFilter() {
  // 不要在筛选重排前清空旧节点的隐藏标记。重排后的 runtime tree 只包含
  // 当前可见节点，若先清空，已经被裁掉的旧 SVG 节点将无法再次遍历并隐藏。
  filteredMatchCount.value = 0
  if (!filterActive.value) return
  const renderer = props.mindMap?.renderer
  const runtimeRoot = renderer?.root
  const documentRoot = renderer?.renderTree
  if (!runtimeRoot || !documentRoot) return

  const { parentUidByUid } = createDocumentTreeIndex(documentRoot)
  const rootUid = getMindmapNodeUid(documentRoot) || String(runtimeRoot.uid)
  const visibleNodeUids = new Set([rootUid])
  const matchedNodes = getDocumentFilterMatches()
  const matchedNodeUids = new Set()
  matchedNodes.forEach(matchedNode => {
    let uid = getMindmapNodeUid(matchedNode)
    const pathGuard = new Set()
    if (uid !== null) matchedNodeUids.add(uid)
    while (uid !== null && !pathGuard.has(uid)) {
      pathGuard.add(uid)
      visibleNodeUids.add(uid)
      uid = parentUidByUid.get(uid) ?? null
    }
  })
  filteredMatchCount.value = matchedNodeUids.size

  props.mindMap?.execCommand?.('CLEAR_ACTIVE_NODE')
  walkRuntimeNodeTree(runtimeRoot, node => {
    const nodeUid = getMindmapNodeUid(node)
    const hidden = nodeUid === null || !visibleNodeUids.has(nodeUid)
    setCanvasElementFiltered(node.group, hidden)
    // 临时筛选布局后，node.children 只保留可见子节点，但 _lines 仍可能
    // 带有完整树上一次渲染的多余路径。优先使用渲染阶段记录的真实起止
    // 节点；这样也兼容组织结构、时间轴等会追加共享主干线的布局。
    ;(node._lines || []).forEach((line, index) => {
      const ownerUid = line?.__smmFilterOwnerUid
      const targetUid = line?.__smmFilterTargetUid
      const lineRenderVersion = line?.__smmFilterRenderVersion
      let lineVisible
      if (
        ownerUid !== undefined
        && targetUid !== undefined
        && lineRenderVersion !== undefined
      ) {
        const isSharedBranchLine = ownerUid === targetUid
        lineVisible = lineRenderVersion === node._lineRenderVersion
          && visibleNodeUids.has(ownerUid)
          && (isSharedBranchLine
            ? Boolean(node.children?.length)
            : visibleNodeUids.has(targetUid))
      } else {
        const child = node.children?.[index]
        const childUid = getMindmapNodeUid(child)
        lineVisible = Boolean(
          childUid !== null
          && nodeUid !== null
          && visibleNodeUids.has(nodeUid)
          && visibleNodeUids.has(childUid)
        )
      }
      setCanvasElementFiltered(line, !lineVisible)
    })
    ;(node._generalizationList || []).forEach(item => {
      setCanvasElementFiltered(item?.generalizationLine, hidden)
      setCanvasElementFiltered(item?.generalizationNode?.group || item?.generalizationNode, hidden)
    })
  })
  renderer.setTransientVisibleNodeUids?.(visibleNodeUids)
}

function toggleCanvasFilter() {
  if (!hasFilterCriteria.value) return
  if (searchCanvasFilterActive.value) {
    restoreCanvasVisibility()
    return
  }
  activeCanvasFilterSource.value = 'search'
  filterActive.value = true
  applyCanvasFilter()
}

function reapplyCanvasFilter() {
  if (filterActive.value) nextTick(applyCanvasFilter)
}

function navigateSearchResults(key, { focus = false } = {}) {
  const nextIndex = resolveMindmapSearchNavigationIndex(
    currentIndex.value - 1,
    searchResultList.value.length,
    key,
  )
  return nextIndex >= 0 && activateSearchResult(nextIndex, { focus })
}

function onSearchResultKeydown(event) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  event.stopPropagation()
  navigateSearchResults(event.key, { focus: true })
}

function handleSearchInfoChange(data) {
  if (serverSearchMode.value || !show.value || !activeLocalKeyword) return
  const nextTotal = Math.max(0, Number(data?.total) || 0)
  const nextIndex = Number(data?.currentIndex)
  total.value = nextTotal
  currentIndex.value = Number.isSafeInteger(nextIndex) && nextIndex >= 0
    ? Math.min(nextIndex + 1, nextTotal)
    : 0
  showSearchInfo.value = true
}

function showSearch() {
  if (!show.value) {
    focusReturnTarget = document.activeElement
  }
  if (store.activeSidebar === 'outline') {
    actions.setActiveSidebar(null)
  }
  if (window.innerWidth <= 760 && store.activeSidebar) {
    actions.setActiveSidebar(null)
  }
  panelMode.value = 'search'
  show.value = true
  nextTick(() => {
    searchInputRef.value?.focus()
    setSearchResultListHeight()
  })
  void loadTagOptions()
}

function showFilter() {
  if (!show.value) focusReturnTarget = document.activeElement
  bus.emit('closeSideBar')
  panelMode.value = 'filter'
  show.value = true
}

function addFilterCondition() {
  filterRows.value.push(createFilterRow())
}

function removeFilterCondition(index) {
  filterRows.value.splice(index, 1)
  if (filterRows.value.length === 0) filterRows.value.push(createFilterRow())
}

function clearFilterConditions() {
  filterRows.value = [createFilterRow('title'), createFilterRow('any')]
  confirmedFilterRows.value = []
  restoreCanvasVisibility()
}

function confirmFilterConditions() {
  confirmedFilterRows.value = filterRows.value
    .map(row => ({ ...row, value: String(row.value || '').trim() }))
    .filter(row => row.value)
  if (confirmedFilterRows.value.length === 0) {
    restoreCanvasVisibility()
  } else {
    activeCanvasFilterSource.value = 'conditions'
    filterActive.value = true
    applyCanvasFilter()
  }
  show.value = false
  nextTick(() => focusReturnTarget?.focus?.())
}

function handleGlobalSearchShortcut(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
  if (String(event.key || '').toLowerCase() !== 'f') return
  event.preventDefault()
  event.stopPropagation()
  showSearch()
}

async function loadTagOptions() {
  const requestId = ++tagOptionsRequestId
  tagOptionsLoading.value = true
  tagOptionsError.value = ''
  try {
    const res = await getTagSuggestions()
    if (requestId !== tagOptionsRequestId || !show.value) return
    tagOptions.value = res.data || []
  } catch (error) {
    if (requestId !== tagOptionsRequestId || !show.value) return
    tagOptionsError.value = error?.response?.data?.msg || error?.message || '统一标签加载失败'
  } finally {
    if (requestId === tagOptionsRequestId) tagOptionsLoading.value = false
  }
}

function hideReplaceInput() {
  showReplaceInput.value = false
  replaceText.value = ''
}

function onFocus() {
  const mindMap = props.mindMap
  if (!mindMap) return
  if (autoEnterConfigOwner !== mindMap) {
    restoreAutoEnterTextEdit()
    autoEnterConfigOwner = mindMap
    previousAutoEnterTextEdit = mindMap.getConfig?.('enableAutoEnterTextEditWhenKeydown') !== false
  }
  mindMap.updateConfig({ enableAutoEnterTextEditWhenKeydown: false })
}

function onBlur() {
  restoreAutoEnterTextEdit()
}

function restoreAutoEnterTextEdit() {
  if (autoEnterConfigOwner && previousAutoEnterTextEdit !== null) {
    autoEnterConfigOwner.updateConfig?.({
      enableAutoEnterTextEditWhenKeydown: previousAutoEnterTextEdit,
    })
  }
  autoEnterConfigOwner = null
  previousAutoEnterTextEdit = null
}

function onSearchFieldKeydown(event, allowResultNavigation) {
  event.stopPropagation()
  if (event.key === 'Escape') {
    close()
    return
  }
  if (
    allowResultNavigation
    && showSearchResultList.value
    && ['ArrowDown', 'ArrowUp'].includes(event.key)
  ) {
    event.preventDefault()
    navigateSearchResults(event.key, { focus: true })
  }
}

function blur() {
  searchInputRef.value?.blur?.()
  replaceInputRef.value?.blur?.()
}

async function onSearchNext(event) {
  clearTimeout(liveSearchTimer)
  liveSearchTimer = null
  const keyword = searchText.value.trim()
  const navigationKey = event?.shiftKey ? 'ArrowUp' : 'ArrowDown'
  if (keyword !== searchText.value) searchText.value = keyword
  if (!keyword && !selectedTagId.value) {
    resetSearchResults()
    return
  }
  showSearchResultList.value = true
  if (selectedTagId.value && props.mindmapId) {
    const criteriaKey = getServerCriteriaKey(keyword, selectedTagId.value)
    if (
      serverSearchMode.value
      && activeServerCriteriaKey === criteriaKey
      && !searching.value
      && !loadingMore.value
      && !searchError.value
      && searchResultList.value.length > 0
    ) {
      navigateSearchResults(navigationKey)
      return
    }
    serverSearchMode.value = true
    activeLocalKeyword = ''
    props.mindMap?.search?.endSearch()
    await runServerSearch(false)
    return
  }
  if (
    activeLocalKeyword === keyword
    && searchResultList.value.length > 0
  ) {
    navigateSearchResults(navigationKey)
    return
  }
  startLocalSearch(keyword)
}

function startLocalSearch(keyword) {
  if (!show.value || selectedTagId.value || !keyword || activeLocalKeyword === keyword) return
  searchRequestId += 1
  activeServerCriteriaKey = ''
  serverSearchMode.value = false
  searching.value = true
  loadingMore.value = false
  searchError.value = ''
  serverPageNum.value = 0
  showSearchResultList.value = true
  activeLocalKeyword = keyword
  props.mindMap?.search?.search(keyword)
}

function scheduleLiveSearch(keyword) {
  clearTimeout(liveSearchTimer)
  liveSearchTimer = null
  if (!show.value || selectedTagId.value || !keyword) return
  liveSearchTimer = setTimeout(() => {
    liveSearchTimer = null
    startLocalSearch(keyword)
  }, LIVE_SEARCH_DELAY)
}

async function runServerSearch(append) {
  const sessionMindMap = props.mindMap
  const sessionMindmapId = Number(props.mindmapId)
  const sessionKeyword = searchText.value
  const sessionTagId = selectedTagId.value
  const criteriaKey = getServerCriteriaKey(sessionKeyword, sessionTagId)
  if (!sessionMindMap || !Number.isSafeInteger(sessionMindmapId) || sessionMindmapId <= 0) {
    resetSearchResults(sessionMindMap)
    return
  }
  activeServerCriteriaKey = criteriaKey
  const requestId = ++searchRequestId
  const pageNum = append ? serverPageNum.value + 1 : 1
  searchError.value = ''
  if (append) {
    loadingMore.value = true
  } else {
    searching.value = true
    searchResultList.value = []
    total.value = 0
    currentIndex.value = 0
    showSearchInfo.value = false
  }

  try {
    const res = await searchMindmapNodes(sessionMindmapId, {
      keyword: sessionKeyword || undefined,
      tagId: sessionTagId,
      pageNum,
      pageSize: SERVER_SEARCH_PAGE_SIZE,
    })
    if (!isCurrentServerSearchSession(requestId, sessionMindMap, sessionMindmapId, criteriaKey)) return
    const rows = (res.rows || []).map(item => ({
      id: item.nodeUid,
      nodeUid: item.nodeUid,
      name: String(item.text ?? ''),
      segments: buildMindmapSearchHighlightSegments(item.text, sessionKeyword),
      pathText: String(item.pathText ?? ''),
    }))
    searchResultList.value = append ? [...searchResultList.value, ...rows] : rows
    total.value = Math.max(searchResultList.value.length, Number(res.total) || 0)
    serverPageNum.value = pageNum
    showSearchInfo.value = true
    if (!append && rows.length > 0) {
      activateSearchResult(0)
    }
    reapplyCanvasFilter()
  } catch (error) {
    if (!isCurrentServerSearchSession(requestId, sessionMindMap, sessionMindmapId, criteriaKey)) return
    searchError.value = error?.response?.data?.msg || '搜索失败，请检查网络后重试'
  } finally {
    if (isCurrentServerSearchSession(requestId, sessionMindMap, sessionMindmapId, criteriaKey)) {
      searching.value = false
      loadingMore.value = false
    }
  }
}

function getServerCriteriaKey(keyword = searchText.value, tagId = selectedTagId.value) {
  return JSON.stringify([String(keyword || ''), Number(tagId) || null])
}

function isCurrentServerSearchSession(requestId, mindMap, mindmapId, criteriaKey) {
  return componentAlive
    && show.value
    && serverSearchMode.value
    && requestId === searchRequestId
    && props.mindMap === mindMap
    && Number(props.mindmapId) === mindmapId
    && activeServerCriteriaKey === criteriaKey
    && getServerCriteriaKey() === criteriaKey
}

function loadMoreServerResults() {
  if (loadingMore.value || !hasMoreServerResults.value) return
  void runServerSearch(true)
}

function retryServerSearch() {
  void runServerSearch(searchResultList.value.length > 0)
}

function onFilterChange() {
  void onSearchNext()
}

function doReplace() {
  if (isReadonly.value || !show.value || serverSearchMode.value || !searchText.value.trim()) return
  props.mindMap?.search?.replace(replaceText.value, true)
}

function doReplaceAll() {
  if (isReadonly.value || !show.value || serverSearchMode.value || !searchText.value.trim()) return
  props.mindMap?.search?.replaceAll(replaceText.value)
}

function resetSearchResults(mindMap = props.mindMap, { preserveCanvasFilter = false } = {}) {
  clearTimeout(liveSearchTimer)
  liveSearchTimer = null
  searchRequestId += 1
  showSearchResultList.value = false
  showSearchInfo.value = false
  total.value = 0
  currentIndex.value = 0
  serverSearchMode.value = false
  searching.value = false
  loadingMore.value = false
  searchError.value = ''
  serverPageNum.value = 0
  searchResultList.value = []
  activeServerCriteriaKey = ''
  activeLocalKeyword = ''
  if (preserveCanvasFilter && filterActive.value) {
    reapplyCanvasFilter()
  } else {
    restoreCanvasVisibility({ mindMap })
  }
  mindMap?.search?.endSearch()
}

function close(options = {}) {
  const wasShown = show.value
  const returnTarget = focusReturnTarget
  const restoreFocus = options?.restoreFocus !== false
  const forceReset = options?.forceReset === true
  const searchMindMap = options?.mindMap || props.mindMap
  if (panelMode.value === 'filter' && !forceReset) {
    focusReturnTarget = null
    show.value = false
    if (wasShown && restoreFocus) nextTick(() => returnTarget?.focus?.())
    return
  }
  focusReturnTarget = null
  tagOptionsRequestId += 1
  tagOptionsLoading.value = false
  tagOptionsError.value = ''
  show.value = false
  searchText.value = ''
  selectedTagId.value = null
  hideReplaceInput()
  restoreAutoEnterTextEdit()
  resetSearchResults(searchMindMap, {
    preserveCanvasFilter: activeCanvasFilterSource.value === 'conditions',
  })
  if (wasShown && restoreFocus) {
    nextTick(() => {
      if (returnTarget?.isConnected && !returnTarget.closest?.('[inert]')) {
        returnTarget.focus?.()
      }
    })
  }
}

function onSearchMatchNodeListChange(list) {
  if (
    serverSearchMode.value
    || !show.value
    || !activeLocalKeyword
    || searchText.value.trim() !== activeLocalKeyword
  ) return
  searching.value = false
  searchError.value = ''
  const treeIndex = createDocumentTreeIndex(props.mindMap?.renderer?.renderTree)
  searchResultList.value = (Array.isArray(list) ? list : []).map((item, index) => {
    const data = item?.data || item?.nodeData?.data || {}
    let name = String(data.text ?? '')
    const id = data.uid || `local-search-result-${index}`
    if (data.richText) {
      const template = document.createElement('template')
      template.innerHTML = name
      name = template.content.textContent || ''
    }
    const segments = buildMindmapSearchHighlightSegments(name, searchText.value, {
      caseSensitive: true,
    })
    return {
      data: item,
      id,
      segments,
      name,
      pathText: getMindmapNodePathText(item, treeIndex),
    }
  })
  total.value = searchResultList.value.length
  showSearchInfo.value = true
  if (searchResultList.value.length <= 0) currentIndex.value = 0
  reapplyCanvasFilter()
}

function setSearchResultListHeight() {
  const panelBottom = searchContainerRef.value?.getBoundingClientRect?.().bottom || 0
  searchResultListHeight.value = resolveMindmapSearchResultListHeight(
    window.innerHeight,
    panelBottom,
  )
}

function handleSearchPanelResize() {
  setSearchResultListHeight()
  if (
    window.innerWidth <= 760
    && show.value
    && panelMode.value === 'search'
    && store.activeSidebar
  ) {
    actions.setActiveSidebar(null)
  }
}

function onSearchResultItemClick(index) {
  activateSearchResult(index)
}

watch(searchText, (val) => {
  if (isUndef(val) && !selectedTagId.value) {
    resetSearchResults(props.mindMap, {
      preserveCanvasFilter: activeCanvasFilterSource.value === 'conditions',
    })
    return
  }
  if (
    serverSearchMode.value
    && activeServerCriteriaKey
    && getServerCriteriaKey() !== activeServerCriteriaKey
  ) {
    searchRequestId += 1
    activeServerCriteriaKey = ''
    searching.value = false
    loadingMore.value = false
    showSearchResultList.value = false
    showSearchInfo.value = false
    searchResultList.value = []
    total.value = 0
  }
  if (
    !serverSearchMode.value
    && activeLocalKeyword
    && String(val || '').trim() !== activeLocalKeyword
  ) {
    resetSearchResults(props.mindMap, {
      preserveCanvasFilter: filterActive.value,
    })
  }
  scheduleLiveSearch(String(val || '').trim())
})

watch(isReadonly, (readonly) => {
  if (readonly) hideReplaceInput()
})

watch(() => store.activeSidebar, (sidebarName) => {
  if (
    sidebarName
    && (sidebarName === 'outline' || window.innerWidth <= 760)
    && show.value
    && panelMode.value === 'search'
  ) {
    close({ restoreFocus: false })
  }
})

watch([show, panelMode], ([visible, mode]) => {
  bus.emit('searchPanelVisibilityChange', visible && mode === 'search')
}, { immediate: true })

onMounted(() => {
  setSearchResultListHeight()
  if (typeof ResizeObserver !== 'undefined' && searchContainerRef.value) {
    searchPanelResizeObserver = new ResizeObserver(setSearchResultListHeight)
    searchPanelResizeObserver.observe(searchContainerRef.value)
  }
  bus.on('show_search', showSearch)
  bus.on('hide_search', close)
  bus.on('show_filter', showFilter)
  bus.on('setData', onDocumentReplace)
  window.addEventListener('resize', handleSearchPanelResize)
  window.addEventListener('keydown', handleGlobalSearchShortcut, true)
})

function onDocumentReplace() {
  close({ restoreFocus: false, forceReset: true })
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm && oldMm !== mm) {
    close({ mindMap: oldMm, restoreFocus: false, forceReset: true })
  }
  restoreAutoEnterTextEdit()
  if (oldMm) {
    oldMm.off('search_info_change', handleSearchInfoChange)
    oldMm.off('node_click', blur)
    oldMm.off('draw_click', blur)
    oldMm.off('expand_btn_click', blur)
    oldMm.off('search_match_node_list_change', onSearchMatchNodeListChange)
    oldMm.off('node_tree_render_end', reapplyCanvasFilter)
    oldMm.keyCommand?.removeShortcut?.('Control+f', showSearch)
  }
  if (mm) {
    mm.on('search_info_change', handleSearchInfoChange)
    mm.on('node_click', blur)
    mm.on('draw_click', blur)
    mm.on('expand_btn_click', blur)
    mm.on('search_match_node_list_change', onSearchMatchNodeListChange)
    mm.on('node_tree_render_end', reapplyCanvasFilter)
    mm.keyCommand.addShortcut('Control+f', showSearch)
  }
}, { immediate: true })

watch(() => props.mindmapId, (mindmapId, oldMindmapId) => {
  if (oldMindmapId != null && mindmapId !== oldMindmapId) {
    close({ restoreFocus: false, forceReset: true })
  }
})

onBeforeUnmount(() => {
  componentAlive = false
  searchRequestId += 1
  tagOptionsRequestId += 1
  searchPanelResizeObserver?.disconnect()
  searchPanelResizeObserver = null
  restoreAutoEnterTextEdit()
  bus.off('show_search', showSearch)
  bus.off('hide_search', close)
  bus.emit('searchPanelVisibilityChange', false)
  bus.off('show_filter', showFilter)
  bus.off('setData', onDocumentReplace)
  window.removeEventListener('resize', handleSearchPanelResize)
  window.removeEventListener('keydown', handleGlobalSearchShortcut, true)
  props.mindMap?.off?.('search_info_change', handleSearchInfoChange)
  props.mindMap?.off?.('node_click', blur)
  props.mindMap?.off?.('draw_click', blur)
  props.mindMap?.off?.('expand_btn_click', blur)
  props.mindMap?.off?.('search_match_node_list_change', onSearchMatchNodeListChange)
  props.mindMap?.off?.('node_tree_render_end', reapplyCanvasFilter)
  props.mindMap?.keyCommand?.removeShortcut?.('Control+f', showSearch)
  restoreCanvasVisibility()
})
</script>

<style lang="less" scoped>
.searchContainer {
  position: fixed;
  top: var(--mindmap-shell-top, 52px);
  bottom: var(--mindmap-workspace-bottom, 30px);
  left: var(--mindmap-activity-width, 44px);
  z-index: 2001;
  width: 280px;
  display: flex;
  flex-direction: column;
  padding: 0 12px 12px;
  box-sizing: border-box;
  overflow: hidden;
  border-right: 1px solid #e5e8ed;
  border-radius: 0;
  background-color: #fff;
  box-shadow: none;

  .searchPanelHeader {
    min-height: 40px;
    display: flex;
    flex: 0 0 40px;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin: 0 -12px;
    padding: 0 8px 0 12px;
    border-bottom: 1px solid #eef0f3;
  }

  .searchPanelHeading {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;

    strong {
      color: #1f2329;
      font-size: 14px;
      font-weight: 600;
      line-height: 18px;
    }

    span {
      overflow: hidden;
      color: #8f959e;
      font-size: 10px;
      line-height: 12px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .searchModeTabs {
    height: 36px;
    display: grid;
    flex: 0 0 36px;
    grid-template-columns: 1fr 1fr;
    border-bottom: 1px solid #eef0f3;

    button {
      position: relative;
      padding: 0;
      border: 0;
      color: #646a73;
      background: transparent;
      font: inherit;
      font-size: 12px;
      cursor: pointer;

      &::after {
        position: absolute;
        right: 16px;
        bottom: -1px;
        left: 16px;
        height: 2px;
        border-radius: 2px 2px 0 0;
        background: #3370ff;
        content: '';
        opacity: 0;
        transform: scaleX(0.6);
        transition: 0.15s ease;
      }

      &:hover:not(:disabled),
      &.active {
        color: #245bdb;
      }

      &.active {
        font-weight: 600;

        &::after {
          opacity: 1;
          transform: scaleX(1);
        }
      }

      &:disabled {
        color: #c5c8ce;
        cursor: not-allowed;
      }

      &:focus-visible {
        outline: 2px solid #3370ff;
        outline-offset: -3px;
      }
    }
  }

  &.filterDialog {
    top: 88px;
    right: auto;
    bottom: auto;
    left: 50%;
    z-index: 2200;
    width: min(625px, calc(100vw - 32px));
    display: block;
    padding: 18px 24px 16px;
    overflow: visible;
    border: 1px solid #dee0e3;
    border-radius: 6px;
    box-shadow: 0 6px 24px rgba(31, 35, 41, 0.14);
    transform: translateX(-50%);
    transition: none;
    z-index: 30;

    .filterDialogHeader {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;

      h2 {
        margin: 0;
        color: #1f2329;
        font-size: 16px;
        font-weight: 600;
        line-height: 24px;
      }

      button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        padding: 0;
        border: 0;
        border-radius: 6px;
        color: #8f959e;
        background: transparent;
        cursor: pointer;

        &:hover { color: #1f2329; background: #f2f3f5; }
        &:focus-visible { outline: 2px solid #3370ff; outline-offset: 1px; }
      }
    }

    .filterConditionList {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .filterConditionRow {
      display: grid;
      grid-template-columns: 200px 122px minmax(150px, 1fr) 28px;
      align-items: center;
      gap: 8px;

      :deep(.el-input__wrapper),
      :deep(.el-select__wrapper) {
        min-height: 32px;
        border-radius: 5px;
        background: #f5f6f7;
        box-shadow: none;
      }

      :deep(.el-input__wrapper:hover),
      :deep(.el-select__wrapper:hover) { background: #eff0f1; }
      :deep(.is-focused .el-input__wrapper),
      :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px #3370ff inset; }

      .removeConditionButton {
        width: 28px;
        height: 28px;
        margin: 0;
        color: #d83931;
        font-size: 16px;
      }
    }

    .filterDialogFooter {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 10px;

      .addConditionButton {
        margin: 0;
        color: #245bdb;
        border-color: #d0d3d6;
        background: #fff;

        .el-icon { color: #3370ff; }
      }

      .filterDialogActions {
        display: flex;
        gap: 8px;

        .el-button { margin: 0; }
      }
    }

    &.isDark {
      border-color: #4a4f55;
      background: #2f3438;

      .filterDialogHeader h2 { color: #f2f3f5; }
      .filterConditionRow :deep(.el-input__wrapper),
      .filterConditionRow :deep(.el-select__wrapper) { background: #3a4046; }
      .filterDialogFooter .addConditionButton { color: #7da2ff; border-color: #5b6066; background: #2f3438; }
    }
  }

  &.isDark {
    background-color: #363b3f;

    .searchPanelHeader,
    .searchModeTabs {
      border-color: #4a4f55;
    }

    .searchPanelHeading strong {
      color: #f2f3f5;
    }

    .closeBtnBox {
      color: #fff;
      background-color: #363b3f;
    }

    .searchResultList {
      color: #e5e7eb;
      background-color: #2f3438;

      .searchResultItem:hover {
        background-color: #41484e;
      }

      .searchResultItem[aria-selected='true'] {
        background-color: rgba(51, 112, 255, 0.2);

        &::before {
          background-color: #7da2ff;
        }
      }

      .resultPath {
        color: #9ca3af;
      }
    }

    .tagFilterState {
      color: #f7a7a3;
    }
  }

  .tagFilterState {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: 6px;
    color: var(--el-color-danger);
    font-size: 12px;
    line-height: 1.4;
  }

  .btnList {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 8px;

    :deep(.el-button + .el-button) {
      margin-left: 0;
    }
  }

  .closeBtnBox {
    width: 28px;
    height: 28px;
    flex: 0 0 28px;
    background-color: transparent;
    border-radius: 6px;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 0;
    border: 0;
    color: inherit;
    cursor: pointer;
    transition: color 0.15s ease, background 0.15s ease;

    &:hover {
      color: #1f2329;
      background: #f0f2f5;
    }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 2px;
    }
  }

  .searchInputBox {
    position: relative;
    flex: 0 0 auto;
    margin-top: 10px;

    :deep(.el-input__wrapper) {
      min-height: 32px;
      border-radius: 6px;
      box-shadow: 0 0 0 1px #dfe3e8 inset;
    }

    :deep(.el-input__wrapper.is-focus) {
      box-shadow: 0 0 0 1px #3370ff inset, 0 0 0 3px rgba(51, 112, 255, 0.1);
    }

    .searchInfo {
      position: absolute;
      right: 9px;
      top: 50%;
      transform: translateY(-50%);
      color: #909090;
      font-size: 14px;
    }
  }

  .tagFilterSelect {
    width: 100%;
    flex: 0 0 auto;
    margin-top: 6px;

    :deep(.el-select__wrapper) {
      min-height: 30px;
      border-radius: 6px;
      background: #f6f7f9;
      box-shadow: none;
    }
  }

  .canvasFilterBar {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 8px;
    flex: 0 0 auto;
    margin-top: 6px;

    :deep(.el-button) {
      min-height: 30px;
      margin: 0;
      border-radius: 7px;
    }

    > span {
      min-width: 0;
      color: #8f959e;
      font-size: 11px;
      line-height: 16px;

      &.active { color: #3370ff; }
    }
  }

  .searchResultSummary {
    min-height: 34px;
    display: flex;
    flex: 0 0 34px;
    align-items: end;
    justify-content: space-between;
    gap: 8px;
    padding: 0 2px 6px;

    strong {
      color: #1f2329;
      font-size: 12px;
      font-weight: 600;
    }

    span {
      color: #a2a7ae;
      font-size: 10px;
      white-space: nowrap;
    }
  }

  .searchResultList {
    position: relative;
    left: auto;
    top: auto;
    width: auto;
    height: auto !important;
    min-height: min(96px, var(--search-result-fallback-height));
    flex: 1 1 auto;
    background-color: #fff;
    box-shadow: none;
    border-top: 1px solid #eef0f3;
    border-radius: 0;
    margin: 0 -12px -12px;
    overflow-y: auto;
    padding: 4px 6px 8px;

    .searchResultItem {
      width: 100%;
      border: 0;
      color: inherit;
      background: transparent;
      text-align: left;
      font-family: inherit;
      min-height: 44px;
      overflow: hidden;
      padding: 6px 10px 6px 20px;
      border-radius: 6px;
      font-size: 13px;
      cursor: pointer;
      position: relative;

      &::before {
        content: '';
        position: absolute;
        left: 9px;
        top: 50%;
        transform: translateY(-50%);
        width: 5px;
        height: 5px;
        background-color: #606266;
        border-radius: 50%;
      }

      &:hover {
        background-color: #f2f4f7;
      }

      &[aria-selected='true'] {
        background-color: #edf4ff;

        &::after {
          position: absolute;
          top: 6px;
          bottom: 6px;
          left: 0;
          width: 2px;
          border-radius: 0 3px 3px 0;
          background: #3370ff;
          content: '';
        }

        &::before {
          background-color: #3370ff;
        }
      }

      &:focus-visible {
        outline: 2px solid #3370ff;
        outline-offset: -2px;
        background-color: #f2f4f7;
      }

      :deep(.match) {
        color: #409eff;
        font-weight: bold;
      }

      .resultText,
      .resultPath {
        overflow: hidden;
        line-height: 18px;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .resultPath {
        color: #909399;
        margin-top: 2px;
        font-size: 10px;
        line-height: 14px;
      }
    }

    .searchState {
      min-height: 40px;
      padding: 8px 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      color: #606266;
      text-align: center;

      &.error {
        flex-direction: column;
        color: #f56c6c;
      }
    }

    .empty {
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;

      .iconfont {
        font-size: 50px;
        margin-bottom: 20px;
      }

      .text {
        font-size: 14px;
        color: rgba(26, 26, 26, 0.8);
      }
    }
  }
}

:global(.smm-filter-hidden) {
  display: none !important;
}

@media (max-height: 520px) {
  .searchContainer.filterDialog {
    top: 12px;
  }
}

@media (max-width: 760px) {
  .searchContainer:not(.filterDialog) {
    top: var(--mindmap-shell-top, 60px);
    right: 0;
    bottom: 52px;
    left: 0;
    width: min(100%, 300px);
    box-shadow: 8px 0 24px rgba(31, 35, 41, 0.12);
  }

  .searchContainer.filterDialog {
    top: 12px;
    padding: 16px;

    .filterConditionRow {
      grid-template-columns: 1fr 1fr 28px;

      :deep(.el-input) { grid-column: 1 / 3; }
      .removeConditionButton { grid-column: 3; grid-row: 1 / 3; }
    }

    .filterDialogFooter {
      align-items: stretch;
      flex-direction: column;
      gap: 10px;

      .filterDialogActions { justify-content: flex-end; }
    }
  }
}
</style>
