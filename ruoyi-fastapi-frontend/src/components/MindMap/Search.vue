<template>
  <div
    v-show="show"
    ref="searchContainerRef"
    class="searchContainer"
    :class="{ isDark: isDark }"
    role="search"
    aria-label="搜索脑图节点"
    @keydown.esc.stop="close()"
  >
    <button class="closeBtnBox" type="button" aria-label="关闭搜索" @click="close()">
      <el-icon><Close /></el-icon>
    </button>
    <el-select
      v-model="selectedTagId" clearable filterable size="small"
      aria-label="按统一标签筛选节点"
      placeholder="按统一标签筛选（可选）" style="width: 100%; margin-top: 10px"
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
    <div class="searchInputBox">
      <el-input
        ref="searchInputRef"
        placeholder="回车下一个，Shift+回车上一个"
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
        <template #append v-if="searchText && !selectedTagId">
          <el-button size="small" :disabled="isReadonly" @click="showReplaceInput = true">替换</el-button>
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
    <div
      id="mindmap-search-results"
      ref="searchResultListRef"
      class="searchResultList"
      :style="{ height: searchResultListHeight + 'px' }"
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
          <div v-if="item.pathText" class="resultPath">{{ item.pathText }}</div>
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
  </div>
</template>

<script setup>
import { Close, Edit, Loading, Search } from '@element-plus/icons-vue'
import bus from './useEventBus'
import { store } from './useStore'
import { getTagSuggestions } from '@/api/mindmap/tag'
import { searchMindmapNodes } from '@/api/mindmap/mindmap'
import {
  buildMindmapSearchHighlightSegments,
  buildMindmapTagFilterOptions,
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
let searchRequestId = 0
let tagOptionsRequestId = 0
let focusReturnTarget = null
let autoEnterConfigOwner = null
let previousAutoEnterTextEdit = null
let componentAlive = true
let activeServerCriteriaKey = ''
let activeLocalKeyword = ''
let searchPanelResizeObserver = null

const SERVER_SEARCH_PAGE_SIZE = 100
const hasMoreServerResults = computed(() => (
  serverSearchMode.value && searchResultList.value.length < total.value
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
  bus.emit('closeSideBar')
  show.value = true
  nextTick(() => {
    searchInputRef.value?.focus()
    setSearchResultListHeight()
  })
  void loadTagOptions()
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
  searchRequestId += 1
  activeServerCriteriaKey = ''
  serverSearchMode.value = false
  searching.value = false
  loadingMore.value = false
  searchError.value = ''
  serverPageNum.value = 0
  if (
    activeLocalKeyword === keyword
    && searchResultList.value.length > 0
  ) {
    navigateSearchResults(navigationKey)
    return
  }
  activeLocalKeyword = keyword
  props.mindMap?.search?.search(keyword)
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

function resetSearchResults(mindMap = props.mindMap) {
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
  mindMap?.search?.endSearch()
}

function close(options = {}) {
  const wasShown = show.value
  const returnTarget = focusReturnTarget
  const restoreFocus = options?.restoreFocus !== false
  const searchMindMap = options?.mindMap || props.mindMap
  focusReturnTarget = null
  tagOptionsRequestId += 1
  tagOptionsLoading.value = false
  tagOptionsError.value = ''
  show.value = false
  searchText.value = ''
  selectedTagId.value = null
  hideReplaceInput()
  restoreAutoEnterTextEdit()
  resetSearchResults(searchMindMap)
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
    return { data: item, id, segments, name }
  })
  total.value = searchResultList.value.length
  showSearchInfo.value = true
  if (searchResultList.value.length <= 0) currentIndex.value = 0
}

function setSearchResultListHeight() {
  const panelBottom = searchContainerRef.value?.getBoundingClientRect?.().bottom || 0
  searchResultListHeight.value = resolveMindmapSearchResultListHeight(
    window.innerHeight,
    panelBottom,
  )
}

function onSearchResultItemClick(index) {
  activateSearchResult(index)
}

watch(searchText, (val) => {
  if (isUndef(val) && !selectedTagId.value) {
    resetSearchResults()
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
    resetSearchResults()
  }
})

watch(isReadonly, (readonly) => {
  if (readonly) hideReplaceInput()
})

onMounted(() => {
  setSearchResultListHeight()
  if (typeof ResizeObserver !== 'undefined' && searchContainerRef.value) {
    searchPanelResizeObserver = new ResizeObserver(setSearchResultListHeight)
    searchPanelResizeObserver.observe(searchContainerRef.value)
  }
  bus.on('show_search', showSearch)
  bus.on('setData', onDocumentReplace)
  window.addEventListener('resize', setSearchResultListHeight)
})

function onDocumentReplace() {
  close({ restoreFocus: false })
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm && oldMm !== mm) {
    close({ mindMap: oldMm, restoreFocus: false })
  }
  restoreAutoEnterTextEdit()
  if (oldMm) {
    oldMm.off('search_info_change', handleSearchInfoChange)
    oldMm.off('node_click', blur)
    oldMm.off('draw_click', blur)
    oldMm.off('expand_btn_click', blur)
    oldMm.off('search_match_node_list_change', onSearchMatchNodeListChange)
    oldMm.keyCommand?.removeShortcut?.('Control+f', showSearch)
  }
  if (mm) {
    mm.on('search_info_change', handleSearchInfoChange)
    mm.on('node_click', blur)
    mm.on('draw_click', blur)
    mm.on('expand_btn_click', blur)
    mm.on('search_match_node_list_change', onSearchMatchNodeListChange)
    mm.keyCommand.addShortcut('Control+f', showSearch)
  }
}, { immediate: true })

watch(() => props.mindmapId, (mindmapId, oldMindmapId) => {
  if (oldMindmapId != null && mindmapId !== oldMindmapId) {
    close({ restoreFocus: false })
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
  bus.off('setData', onDocumentReplace)
  window.removeEventListener('resize', setSearchResultListHeight)
  props.mindMap?.off?.('search_info_change', handleSearchInfoChange)
  props.mindMap?.off?.('node_click', blur)
  props.mindMap?.off?.('draw_click', blur)
  props.mindMap?.off?.('expand_btn_click', blur)
  props.mindMap?.off?.('search_match_node_list_change', onSearchMatchNodeListChange)
  props.mindMap?.keyCommand?.removeShortcut?.('Control+f', showSearch)
})
</script>

<style lang="less" scoped>
.searchContainer {
  position: relative;
  background-color: #fff;
  padding: 16px;
  width: min(296px, calc(100vw - 24px));
  box-sizing: border-box;
  border-radius: 12px;
  box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.1);
  position: fixed;
  top: 110px;
  left: clamp(12px, 2vw, 20px);
  transition: all 0.3s;

  &.isDark {
    background-color: #363b3f;

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
  }

  .closeBtnBox {
    position: absolute;
    right: -5px;
    top: -5px;
    width: 20px;
    height: 20px;
    background-color: #fff;
    border-radius: 50%;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 0;
    border: 0;
    color: inherit;
    cursor: pointer;
    box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.1);

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 2px;
    }
  }

  .searchInputBox {
    position: relative;

    .searchInfo {
      position: absolute;
      right: 70px;
      top: 50%;
      transform: translateY(-50%);
      color: #909090;
      font-size: 14px;
    }
  }

  .searchResultList {
    position: absolute;
    left: 0;
    top: 100%;
    width: 100%;
    background-color: #fff;
    box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.1);
    border-radius: 12px;
    margin-top: 5px;
    overflow-y: auto;
    padding: 12px 0;

    .searchResultItem {
      width: 100%;
      border: 0;
      color: inherit;
      background: transparent;
      text-align: left;
      font-family: inherit;
      min-height: 36px;
      overflow: hidden;
      padding: 7px 12px 7px 22px;
      font-size: 14px;
      cursor: pointer;
      position: relative;
      padding-left: 22px;

      &::before {
        content: '';
        position: absolute;
        left: 10px;
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
        line-height: 20px;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .resultPath {
        color: #909399;
        font-size: 11px;
        line-height: 16px;
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

@media (max-height: 520px) {
  .searchContainer {
    top: 12px;
  }
}
</style>
