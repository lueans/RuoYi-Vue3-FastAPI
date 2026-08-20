<template>
  <Sidebar ref="sidebarRef" title="备注">
    <div
      class="noteViewerWrap"
      :class="{ isDark: isDark }"
      aria-live="polite"
      :aria-busy="isRendering ? 'true' : 'false'"
    >
      <div v-if="isRendering" class="statusTip" role="status">正在解析备注…</div>
      <div v-else-if="renderError" class="statusTip errorTip" role="alert">
        {{ renderError }}
      </div>
      <div
        v-else-if="renderedNote"
        class="noteContent mindmapMarkdownBody"
        :class="{ 'is-dark': isDark }"
        v-html="renderedNote"
      ></div>
      <div v-else class="emptyTip">暂无备注内容</div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'
import { renderMindmapMarkdown } from '@/utils/mindmap-markdown'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const renderedNote = ref('')
const renderError = ref('')
const isRendering = ref(false)
let currentNode = null
let currentMindMap = null
let renderRequestId = 0
let componentAlive = true

function invalidateNoteSession() {
  renderRequestId += 1
  currentNode = null
  currentMindMap = null
  renderedNote.value = ''
  renderError.value = ''
  isRendering.value = false
}

function isCurrentNoteSession(requestId, node, mindMap) {
  return componentAlive
    && requestId === renderRequestId
    && currentNode === node
    && currentMindMap === mindMap
    && props.mindMap === mindMap
    && store.activeSidebar === 'noteSidebar'
}

async function onNoteClick(node) {
  const activeMindMap = props.mindMap
  if (
    !componentAlive
    || !activeMindMap
    || !node
    || typeof node.getData !== 'function'
    || (node.mindMap && node.mindMap !== activeMindMap)
  ) return

  const requestId = ++renderRequestId
  currentNode = node
  currentMindMap = activeMindMap
  let note = ''
  try {
    note = String(node.getData('note') || '')
  } catch {
    invalidateNoteSession()
    return
  }
  renderedNote.value = ''
  renderError.value = ''
  isRendering.value = Boolean(note)
  if (!actions.setActiveSidebar('noteSidebar')) {
    invalidateNoteSession()
    return
  }
  if (!note) return
  try {
    const html = await renderMindmapMarkdown(note)
    if (!isCurrentNoteSession(requestId, node, activeMindMap)) return
    renderedNote.value = html
  } catch {
    if (!isCurrentNoteSession(requestId, node, activeMindMap)) return
    renderError.value = '备注暂时无法显示，请稍后重试'
  } finally {
    if (isCurrentNoteSession(requestId, node, activeMindMap)) {
      isRendering.value = false
    }
  }
}

function onNodeActive(_node, _nodeList, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  invalidateNoteSession()
  if (store.activeSidebar === 'noteSidebar') {
    actions.setActiveSidebar(null)
  }
}

watch(() => props.mindMap, (mm, oldMm) => {
  oldMm?.off?.('node_note_click', onNoteClick)
  if (mm !== oldMm) {
    invalidateNoteSession()
    if (store.activeSidebar === 'noteSidebar') actions.setActiveSidebar(null)
  }
  mm?.on?.('node_note_click', onNoteClick)
}, { immediate: true })

watch(() => store.activeSidebar, (val) => {
  if (val === 'noteSidebar') {
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
    invalidateNoteSession()
  }
}, { immediate: true })

onMounted(() => {
  bus.on('node_active', onNodeActive)
})

onBeforeUnmount(() => {
  componentAlive = false
  invalidateNoteSession()
  bus.off('node_active', onNodeActive)
  props.mindMap?.off?.('node_note_click', onNoteClick)
})
</script>

<style lang="less" scoped>
.noteViewerWrap {
  padding: 16px;

  &.isDark {
    .noteContent { color: hsla(0, 0%, 100%, 0.8); }
    .emptyTip,
    .statusTip { color: hsla(0, 0%, 100%, 0.4); }

    .errorTip { color: #ff7875; }
  }

  .noteContent {
    min-width: 0;
  }

  .emptyTip,
  .statusTip {
    text-align: center;
    color: #999;
    padding: 40px 0;
  }

  .errorTip {
    color: #f56c6c;
  }
}
</style>
