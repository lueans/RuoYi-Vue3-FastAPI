<template>
  <Sidebar ref="sidebarRef" title="大纲" placement="left" open-on-mount>
    <div class="outline-shell">
      <div class="outline-actions">
        <span class="outline-count" aria-live="polite">{{ flatOutline.length }} 个可见节点</span>
        <el-tooltip :content="isReadonly ? '只读状态不能编辑大纲' : '进入大纲编辑模式'" placement="bottom">
          <el-button size="small" :disabled="isReadonly" @click="openOutlineEdit">
            <span class="iconfont iconbianji1" aria-hidden="true"></span> 编辑模式
          </el-button>
        </el-tooltip>
      </div>
      <div
        v-if="outlineData"
        ref="outlineViewportRef"
        class="outline-tree"
        role="tree"
        aria-label="脑图节点大纲"
        @scroll="onOutlineScroll"
      >
        <div class="outline-spacer" :style="{ height: `${outlineWindow.totalHeight}px` }">
          <div
            v-for="entry in outlineWindow.items"
            :key="entry.item.key"
            class="outline-node"
            :class="{ active: focusedKey === entry.item.key }"
            :style="{
              height: `${OUTLINE_ITEM_HEIGHT}px`,
              transform: `translateY(${entry.top}px)`,
              paddingLeft: `${resolveOutlineIndent(entry.item.level)}px`,
            }"
            role="treeitem"
            :aria-level="entry.item.level + 1"
            :aria-posinset="entry.item.positionInSet"
            :aria-setsize="entry.item.setSize"
            :aria-expanded="entry.item.hasChildren ? entry.item.expanded : undefined"
          >
            <button
              v-if="entry.item.hasChildren"
              type="button"
              class="outline-expand"
              tabindex="-1"
              :aria-label="`${entry.item.expanded ? '收起' : '展开'}节点：${entry.item.text || '空节点'}`"
              :aria-expanded="entry.item.expanded"
              @click="toggleExpandAndFocus(entry.item)"
            >{{ entry.item.expanded ? '▾' : '▸' }}</button>
            <span v-else class="outline-expand-spacer" aria-hidden="true"></span>
            <button
              :ref="el => setTargetRef(entry.item.key, el)"
              type="button"
              class="outline-target outline-text"
              :tabindex="tabbableKey === entry.item.key ? 0 : -1"
              :aria-label="`定位到节点：${entry.item.text || '空节点'}，第 ${entry.index + 1} 项，共 ${flatOutline.length} 项`"
              @focus="focusedKey = entry.item.key"
              @keydown="onOutlineKeydown($event, entry.item)"
              @click="goToNode(entry.item.uid)"
            >{{ entry.item.text || '空节点' }}</button>
          </div>
        </div>
      </div>
      <div v-else class="empty-tip">暂无数据</div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'
import {
  flattenMindmapOutline,
  MINDMAP_OUTLINE_ITEM_HEIGHT,
  resolveMindmapOutlineNavigation,
  resolveMindmapOutlineWindow,
} from '@/utils/mindmap-outline'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const outlineViewportRef = ref(null)
const isReadonly = computed(() => store.isReadonly)
const outlineData = ref(null)
const collapsedKeys = ref(new Set())
const focusedKey = ref('')
const outlineScrollTop = ref(0)
const outlineViewportHeight = ref(0)
const targetRefs = new Map()
const OUTLINE_ITEM_HEIGHT = MINDMAP_OUTLINE_ITEM_HEIGHT
let viewportResizeObserver = null
let usingWindowResizeFallback = false

function updateOutline(data = null) {
  if (!props.mindMap) {
    outlineData.value = null
    return
  }
  outlineData.value = data && typeof data === 'object'
    ? data
    : props.mindMap.getData()
}

function onDataChange(data, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  updateOutline(data)
}

function onNodeTreeRenderEnd(sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  updateOutline()
}

const flatOutline = computed(() => flattenMindmapOutline(outlineData.value, collapsedKeys.value))
const outlineWindow = computed(() => resolveMindmapOutlineWindow(
  flatOutline.value,
  outlineScrollTop.value,
  outlineViewportHeight.value,
  OUTLINE_ITEM_HEIGHT,
))
const tabbableKey = computed(() => {
  const visibleItems = outlineWindow.value.items
  if (visibleItems.some(entry => entry.item.key === focusedKey.value)) return focusedKey.value
  return visibleItems[0]?.item.key || ''
})

function toggleExpand(item) {
  const nextCollapsedKeys = new Set(collapsedKeys.value)
  if (nextCollapsedKeys.has(item.key)) {
    nextCollapsedKeys.delete(item.key)
  } else {
    nextCollapsedKeys.add(item.key)
  }
  collapsedKeys.value = nextCollapsedKeys
}

function toggleExpandAndFocus(item) {
  focusedKey.value = item.key
  toggleExpand(item)
  nextTick(() => {
    const nextIndex = flatOutline.value.findIndex(entry => entry.key === item.key)
    if (nextIndex >= 0) focusOutlineIndex(nextIndex)
  })
}

function resolveOutlineIndent(level) {
  return 8 + Math.min(Math.max(0, Number(level) || 0), 14) * 16
}

function setTargetRef(key, el) {
  if (el) targetRefs.set(key, el)
  else targetRefs.delete(key)
}

function onOutlineScroll(event) {
  outlineScrollTop.value = Math.max(0, Number(event.currentTarget?.scrollTop) || 0)
}

function measureOutlineViewport() {
  outlineViewportHeight.value = Math.max(
    0,
    Number(outlineViewportRef.value?.clientHeight) || 0,
  )
}

function focusOutlineIndex(index) {
  const item = flatOutline.value[index]
  const viewport = outlineViewportRef.value
  if (!item || !viewport) return
  const itemTop = index * OUTLINE_ITEM_HEIGHT
  const itemBottom = itemTop + OUTLINE_ITEM_HEIGHT
  const viewportBottom = viewport.scrollTop + viewport.clientHeight
  if (itemTop < viewport.scrollTop) viewport.scrollTop = itemTop
  else if (itemBottom > viewportBottom) viewport.scrollTop = itemBottom - viewport.clientHeight
  outlineScrollTop.value = viewport.scrollTop
  focusedKey.value = item.key
  nextTick(() => targetRefs.get(item.key)?.focus?.({ preventScroll: true }))
}

function onOutlineKeydown(event, item) {
  if (event.altKey || event.ctrlKey || event.metaKey) return
  const action = resolveMindmapOutlineNavigation(flatOutline.value, item.key, event.key)
  if (!action) return
  event.preventDefault()
  event.stopPropagation()
  if (action.type === 'collapse' || action.type === 'expand') {
    toggleExpand(item)
    nextTick(() => {
      const nextIndex = flatOutline.value.findIndex(entry => entry.key === item.key)
      if (nextIndex >= 0) focusOutlineIndex(nextIndex)
    })
    return
  }
  focusOutlineIndex(action.index)
}

function goToNode(uid) {
  if (!props.mindMap || !uid) return
  props.mindMap.execCommand('GO_TARGET_NODE', uid)
}

function openOutlineEdit() {
  if (isReadonly.value) return
  actions.setActiveSidebar(null)
  bus.emit('openOutlineEdit')
}

onMounted(() => {
  bus.on('data_change', onDataChange)
  bus.on('node_tree_render_end', onNodeTreeRenderEnd)
  nextTick(() => {
    measureOutlineViewport()
    if (typeof ResizeObserver !== 'undefined' && outlineViewportRef.value) {
      viewportResizeObserver = new ResizeObserver(measureOutlineViewport)
      viewportResizeObserver.observe(outlineViewportRef.value)
    } else {
      usingWindowResizeFallback = true
      window.addEventListener('resize', measureOutlineViewport)
    }
  })
})

onBeforeUnmount(() => {
  bus.off('data_change', onDataChange)
  bus.off('node_tree_render_end', onNodeTreeRenderEnd)
  viewportResizeObserver?.disconnect()
  viewportResizeObserver = null
  if (usingWindowResizeFallback) window.removeEventListener('resize', measureOutlineViewport)
  targetRefs.clear()
})

watch(flatOutline, (items) => {
  if (items.length === 0) {
    focusedKey.value = ''
    return
  }
  if (!items.some(item => item.key === focusedKey.value)) focusedKey.value = items[0].key
})

watch(() => props.mindMap, (mindMap, oldMindMap) => {
  if (mindMap === oldMindMap) return
  collapsedKeys.value = new Set()
  focusedKey.value = ''
  outlineScrollTop.value = 0
  if (outlineViewportRef.value) outlineViewportRef.value.scrollTop = 0
  updateOutline()
})

watch(() => store.activeSidebar, (val) => {
  if (val === 'outline') {
    updateOutline()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })
</script>

<style scoped lang="scss">
.outline-shell {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.outline-tree {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  contain: strict;

  .outline-spacer {
    position: relative;
    width: 100%;
  }
  .outline-node {
    position: absolute;
    inset: 0 0 auto 0;
    display: flex;
    align-items: center;
    padding-top: 6px;
    padding-right: 8px;
    padding-bottom: 6px;
    font-size: 13px;
    border-radius: 6px;
    box-sizing: border-box;
    &:focus-within, &:hover, &.active { background: #f3f6fb; }
  }
  .outline-expand,
  .outline-expand-spacer {
    width: 16px;
    height: 28px;
    flex-shrink: 0;
  }
  .outline-expand {
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
    color: #999;
    font-size: 12px;
  }
  .outline-target {
    flex: 1;
    min-width: 0;
    min-height: 28px;
    padding: 0 4px;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .outline-expand:focus-visible,
  .outline-target:focus-visible {
    outline: 2px solid #409eff;
    outline-offset: 1px;
    border-radius: 3px;
  }
  .outline-text {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
.outline-actions {
  min-height: 48px;
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
}
.outline-count {
  color: #8f959e;
  font-size: 12px;
}
.empty-tip { text-align: center; color: #999; padding: 40px 0; }

:global(.sidebarContainer.isDark) {
  .outline-actions { border-bottom-color: #3d4046; }
  .outline-node {
    color: #e5e6eb;
    &:focus-within, &:hover, &.active { background: rgba(255, 255, 255, 0.08); }
  }
  .outline-expand { color: #a6a9ad; }
  .outline-count, .empty-tip { color: #8f959e; }
}
</style>
