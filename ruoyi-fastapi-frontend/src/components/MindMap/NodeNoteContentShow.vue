<template>
  <div
    class="noteContentShowContainer"
    ref="containerRef"
    v-show="show"
    role="note"
    aria-label="节点备注"
    aria-live="polite"
    :aria-busy="isRendering ? 'true' : 'false'"
    :class="{ isDark: isDark }"
    :style="{ left: left + 'px', top: top + 'px' }"
    @click.stop
    @mousedown.stop
    @mousemove.stop
    @mouseup.stop
    @wheel.stop
    @mouseenter="cancelScheduledHide"
    @mouseleave="scheduleHideNote"
  >
    <div class="noteContentWrap mindmapMarkdownBody" :class="{ 'is-dark': isDark }">
      <div v-if="isRendering" class="noteState" role="status">正在解析备注…</div>
      <div v-else-if="renderError" class="noteState isError" role="alert">
        {{ renderError }}
      </div>
      <div v-else v-html="renderedContent"></div>
    </div>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { store } from './useStore'
import { renderMindmapMarkdown } from '@/utils/mindmap-markdown'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const containerRef = ref(null)
const show = ref(false)
const left = ref(0)
const top = ref(0)
const renderedContent = ref('')
const renderError = ref('')
const isRendering = ref(false)
const isDark = computed(() => store.localConfig.isDark)
let currentNode = null
let currentMindMap = null
let renderRequestId = 0
let hideTimer = null
let componentAlive = true

function isCurrentNoteSession(requestId, node, mindMap) {
  return componentAlive
    && requestId === renderRequestId
    && show.value
    && currentNode === node
    && currentMindMap === mindMap
    && props.mindMap === mindMap
}

async function onShowNote(content, l, t, node, sourceMindMap = null) {
  cancelScheduledHide()
  const activeMindMap = props.mindMap
  const note = String(content ?? '')
  if (
    !isCurrentMindmapEventSource(sourceMindMap, activeMindMap)
    || !note
    || !node
    || (node.mindMap && node.mindMap !== activeMindMap)
  ) {
    hideNote()
    return
  }
  const requestId = ++renderRequestId
  currentNode = node
  currentMindMap = activeMindMap
  renderedContent.value = ''
  renderError.value = ''
  isRendering.value = true
  positionAt(l, t, activeMindMap)
  show.value = true
  try {
    const html = await renderMindmapMarkdown(note)
    if (!isCurrentNoteSession(requestId, node, activeMindMap)) return
    renderedContent.value = html
    await nextTick()
    if (isCurrentNoteSession(requestId, node, activeMindMap)) {
      positionAt(l, t, activeMindMap)
    }
  } catch {
    if (!isCurrentNoteSession(requestId, node, activeMindMap)) return
    renderError.value = '备注暂时无法显示，请稍后重试'
  } finally {
    if (isCurrentNoteSession(requestId, node, activeMindMap)) {
      isRendering.value = false
    }
  }
}

function positionAt(l, t, mindMap = currentMindMap) {
  if (!componentAlive || !mindMap || props.mindMap !== mindMap) return
  const safeLeft = Number.isFinite(Number(l)) ? Number(l) : 12
  const safeTop = Number.isFinite(Number(t)) ? Number(t) : 12
  const elRect = mindMap.elRect
  if (!elRect) {
    left.value = Math.max(12, safeLeft)
    top.value = Math.max(12, safeTop)
    return
  }
  const targetLeft = safeLeft - elRect.left
  const targetTop = safeTop - elRect.top
  const containerWidth = containerRef.value?.offsetWidth || 300
  const containerHeight = containerRef.value?.offsetHeight || 200
  const maxLeft = Math.max(12, elRect.width - 12 - containerWidth)
  const maxTop = Math.max(12, elRect.height - 12 - containerHeight)
  left.value = Math.max(12, Math.min(targetLeft, maxLeft))
  top.value = Math.max(12, Math.min(targetTop, maxTop))
}

function cancelScheduledHide() {
  if (hideTimer) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
}

function scheduleHideNote(sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, currentMindMap || props.mindMap)) return
  cancelScheduledHide()
  hideTimer = setTimeout(hideNote, 180)
}

function hideNote() {
  cancelScheduledHide()
  renderRequestId += 1
  show.value = false
  isRendering.value = false
  renderError.value = ''
  renderedContent.value = ''
  currentNode = null
  currentMindMap = null
}

function reposition() {
  const activeMindMap = currentMindMap
  if (!show.value || !currentNode || !activeMindMap || props.mindMap !== activeMindMap) return
  const pos = currentNode.getNoteContentPosition?.()
  if (pos) positionAt(pos.left, pos.top, activeMindMap)
}

function hideNoteFromMindMapEvent(...args) {
  const sourceMindMap = args.at(-1)
  if (!isCurrentMindmapEventSource(sourceMindMap, currentMindMap || props.mindMap)) return
  hideNote()
}

function repositionFromMindMapEvent(...args) {
  const sourceMindMap = args.at(-1)
  if (!isCurrentMindmapEventSource(sourceMindMap, currentMindMap || props.mindMap)) return
  reposition()
}

function attachContainer(mindMap) {
  const container = containerRef.value
  if (!componentAlive || !container || !mindMap?.el || props.mindMap !== mindMap) return
  if (container.parentNode !== mindMap.el) mindMap.el.appendChild(container)
}

watch(() => props.mindMap, (mindMap, oldMindMap) => {
  if (mindMap === oldMindMap) return
  hideNote()
  nextTick(() => attachContainer(mindMap))
})

onMounted(() => {
  bus.on('showNoteContent', onShowNote)
  bus.on('scheduleHideNoteContent', scheduleHideNote)
  bus.on('hideNoteContent', hideNote)
  bus.on('node_active', hideNoteFromMindMapEvent)
  bus.on('scale', repositionFromMindMapEvent)
  bus.on('translate', repositionFromMindMapEvent)
  bus.on('svg_mousedown', hideNoteFromMindMapEvent)
  bus.on('expand_btn_click', hideNoteFromMindMapEvent)
  attachContainer(props.mindMap)
})

onBeforeUnmount(() => {
  componentAlive = false
  hideNote()
  bus.off('showNoteContent', onShowNote)
  bus.off('scheduleHideNoteContent', scheduleHideNote)
  bus.off('hideNoteContent', hideNote)
  bus.off('node_active', hideNoteFromMindMapEvent)
  bus.off('scale', repositionFromMindMapEvent)
  bus.off('translate', repositionFromMindMapEvent)
  bus.off('svg_mousedown', hideNoteFromMindMapEvent)
  bus.off('expand_btn_click', hideNoteFromMindMapEvent)
  if (containerRef.value?.parentNode) {
    containerRef.value.parentNode.removeChild(containerRef.value)
  }
})
</script>

<style lang="less" scoped>
.noteContentShowContainer {
  position: absolute;
  z-index: 9999;
  background: #fff;
  box-shadow: 0 2px 16px 0 rgba(0, 0, 0, 0.15);
  border-radius: 6px;
  padding: 12px 16px;
  box-sizing: border-box;
  max-width: min(400px, calc(100% - 24px));
  max-height: 300px;
  overflow-y: auto;
  pointer-events: all;

  &.isDark {
    background: #26282d;
    box-shadow: 0 2px 16px rgba(0, 0, 0, 0.45);
  }

  .noteContentWrap {
    font-size: 13px;
  }

  .noteState {
    min-width: 180px;
    padding: 8px 0;
    color: #909399;
    text-align: center;

    &.isError {
      color: #f56c6c;
    }
  }
}
</style>
