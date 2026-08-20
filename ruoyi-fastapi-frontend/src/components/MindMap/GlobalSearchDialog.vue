<template>
  <el-dialog
    :model-value="modelValue"
    class="mindmap-global-search-dialog"
    title="搜索全部脑图内容"
    width="680px"
    append-to-body
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
    @opened="focusSearchInput"
    @closed="invalidateSearch"
  >
    <p class="global-search-intro">
      搜索“我的脑图”和“与我共享”中的节点文字，结果会显示所属文件和完整节点路径。
    </p>
    <div class="global-search-form" role="search">
      <el-input
        ref="searchInputRef"
        v-model="keyword"
        aria-label="跨文件节点搜索关键词"
        maxlength="100"
        clearable
        placeholder="输入节点内容，例如：季度目标"
        @keyup.enter="runSearch(false)"
        @clear="clearResults"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" :loading="searching" @click="runSearch(false)">
        搜索
      </el-button>
    </div>

    <div class="global-search-summary" aria-live="polite">
      <span v-if="searching">正在搜索可访问的脑图…</span>
      <span v-else-if="hasSearched && !searchError">找到 {{ total }} 个节点</span>
      <span v-else>最多显示 50 条/页，归档文件仅可只读打开</span>
    </div>

    <div v-if="searchError" class="global-search-state is-error" role="alert">
      <span>{{ searchError }}</span>
      <el-button v-if="hasSearched" link type="primary" @click="runSearch(false)">重试</el-button>
    </div>
    <div v-else-if="searching && results.length === 0" class="global-search-state" role="status">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在检索节点文字与路径…</span>
    </div>
    <div v-else-if="hasSearched && results.length === 0" class="global-search-state is-empty" role="status">
      <el-icon><Document /></el-icon>
      <strong>没有找到匹配节点</strong>
      <span>可以缩短关键词，或检查目标脑图是否仍有访问权限。</span>
    </div>

    <div
      v-else-if="results.length"
      class="global-search-results"
      role="listbox"
      aria-label="跨文件节点搜索结果"
      :aria-busy="searching || loadingMore"
    >
      <button
        v-for="item in results"
        :key="`${item.mindmapId}:${item.nodeUid}`"
        type="button"
        class="global-search-result"
        role="option"
        :aria-label="`打开${item.mindmapName}中的节点${item.text}`"
        @click="emit('openResult', item)"
      >
        <span class="result-file-line">
          <strong>{{ item.mindmapName }}</strong>
          <el-tag v-if="item.status === 1" size="small" type="info" effect="plain">已归档</el-tag>
          <el-tag v-else-if="item.accessType === 'shared'" size="small" type="success" effect="plain">
            {{ item.canEdit ? '共享可编辑' : '共享只读' }}
          </el-tag>
        </span>
        <span class="result-node-text">
          <template v-for="(segment, index) in item.segments" :key="index">
            <mark v-if="segment.match">{{ segment.text }}</mark>
            <span v-else>{{ segment.text }}</span>
          </template>
        </span>
        <span class="result-path">{{ item.pathText || '当前节点' }}</span>
        <span v-if="item.accessType === 'shared' && item.ownerName" class="result-owner">
          所有者：{{ item.ownerName }}
        </span>
      </button>
      <div v-if="hasMore || loadingMore" class="global-search-more">
        <el-button link type="primary" :loading="loadingMore" @click="runSearch(true)">
          {{ loadingMore ? '加载中…' : `加载更多（已显示 ${results.length}/${total}）` }}
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { Document, Loading, Search } from '@element-plus/icons-vue'
import { searchGlobalMindmapNodes } from '@/api/mindmap/mindmap'
import { buildMindmapSearchHighlightSegments } from '@/utils/mindmap-search'

const PAGE_SIZE = 20

defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'openResult'])

const searchInputRef = ref(null)
const keyword = ref('')
const results = ref([])
const total = ref(0)
const pageNum = ref(0)
const searching = ref(false)
const loadingMore = ref(false)
const searchError = ref('')
const hasSearched = ref(false)
let searchRequestId = 0
let activeKeyword = ''

const hasMore = computed(() => results.value.length < total.value)

function focusSearchInput() {
  nextTick(() => searchInputRef.value?.focus?.())
}

function invalidateSearch() {
  searchRequestId += 1
  searching.value = false
  loadingMore.value = false
}

function clearResults() {
  invalidateSearch()
  results.value = []
  total.value = 0
  pageNum.value = 0
  hasSearched.value = false
  searchError.value = ''
  activeKeyword = ''
}

async function runSearch(append) {
  const normalizedKeyword = keyword.value.trim()
  if (!normalizedKeyword) {
    clearResults()
    searchError.value = '请输入要搜索的节点内容'
    return
  }
  const shouldAppend = append === true && normalizedKeyword === activeKeyword
  if (shouldAppend && !hasMore.value) return
  const requestId = ++searchRequestId
  const nextPage = shouldAppend ? pageNum.value + 1 : 1
  searchError.value = ''
  if (shouldAppend) {
    loadingMore.value = true
  } else {
    searching.value = true
    results.value = []
    total.value = 0
    pageNum.value = 0
    hasSearched.value = true
  }
  try {
    const response = await searchGlobalMindmapNodes({
      keyword: normalizedKeyword,
      pageNum: nextPage,
      pageSize: PAGE_SIZE,
    })
    if (requestId !== searchRequestId) return
    const rows = (Array.isArray(response.rows) ? response.rows : []).map(item => ({
      ...item,
      text: String(item.text || ''),
      segments: buildMindmapSearchHighlightSegments(item.text, normalizedKeyword),
    }))
    results.value = shouldAppend ? [...results.value, ...rows] : rows
    total.value = Math.max(results.value.length, Number(response.total) || 0)
    pageNum.value = nextPage
    activeKeyword = normalizedKeyword
  } catch (error) {
    if (requestId !== searchRequestId) return
    searchError.value = error?.response?.data?.msg || '搜索失败，请检查网络后重试'
  } finally {
    if (requestId === searchRequestId) {
      searching.value = false
      loadingMore.value = false
    }
  }
}
</script>

<style lang="scss">
.mindmap-global-search-dialog {
  .global-search-intro {
    margin: -4px 0 16px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
    line-height: 1.65;
  }

  .global-search-form {
    display: flex;
    gap: 10px;
  }

  .global-search-summary {
    min-height: 20px;
    margin: 10px 0;
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }

  .global-search-state {
    display: flex;
    min-height: 220px;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--el-text-color-secondary);

    &.is-error,
    &.is-empty {
      flex-direction: column;
      padding: 32px;
      border: 1px dashed var(--el-border-color);
      border-radius: 12px;
      text-align: center;
    }

    &.is-error { color: var(--el-color-danger); }
    &.is-empty .el-icon { color: var(--el-color-primary-light-5); font-size: 34px; }
    &.is-empty strong { color: var(--el-text-color-primary); }
    &.is-empty span { font-size: 13px; }
  }

  .global-search-results {
    display: flex;
    max-height: min(58vh, 560px);
    flex-direction: column;
    gap: 8px;
    padding-right: 4px;
    overflow-y: auto;
  }

  .global-search-result {
    display: flex;
    width: 100%;
    flex-direction: column;
    gap: 5px;
    padding: 13px 15px;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 11px;
    background: var(--el-bg-color);
    color: inherit;
    cursor: pointer;
    font: inherit;
    text-align: left;
    transition: border-color 0.15s, background-color 0.15s, box-shadow 0.15s;

    &:hover,
    &:focus-visible {
      border-color: var(--el-color-primary-light-5);
      background: var(--el-color-primary-light-9);
      box-shadow: 0 8px 22px rgba(31, 35, 41, 0.06);
      outline: none;
    }
  }

  .result-file-line {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--el-text-color-primary);
  }

  .result-node-text {
    overflow: hidden;
    color: var(--el-text-color-regular);
    font-size: 14px;
    line-height: 1.55;
    text-overflow: ellipsis;
    white-space: nowrap;

    mark {
      border-radius: 3px;
      background: var(--el-color-warning-light-7);
      color: inherit;
    }
  }

  .result-path,
  .result-owner {
    overflow: hidden;
    color: var(--el-text-color-secondary);
    font-size: 12px;
    line-height: 1.5;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .global-search-more {
    display: flex;
    justify-content: center;
    padding: 8px 0 2px;
  }
}

@media (max-width: 720px) {
  .mindmap-global-search-dialog {
    width: calc(100vw - 24px) !important;

    .global-search-form {
      align-items: stretch;
      flex-direction: column;
    }

    .global-search-results {
      max-height: 52vh;
    }
  }
}
</style>
