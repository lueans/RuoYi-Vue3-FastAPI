<template>
  <Sidebar ref="sidebarRef" title="备注">
    <div class="noteViewerWrap" :class="{ isDark: isDark }">
      <div class="noteContent" v-html="renderedNote"></div>
      <div v-if="!renderedNote" class="emptyTip">暂无备注内容</div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const renderedNote = ref('')
let currentNode = null

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

function onNoteClick(node) {
  currentNode = node
  const note = node.getData('note') || ''
  renderedNote.value = note ? escapeHtml(note) : ''
  actions.setActiveSidebar('noteSidebar')
}

function onNodeActive() {
  if (store.activeSidebar === 'noteSidebar') {
    actions.setActiveSidebar(null)
  }
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) oldMm.off('node_note_click', onNoteClick)
  if (mm) mm.on('node_note_click', onNoteClick)
}, { immediate: true })

watch(() => store.activeSidebar, (val) => {
  if (val === 'noteSidebar') {
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})

onMounted(() => {
  bus.on('node_active', onNodeActive)
})

onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
  props.mindMap?.off('node_note_click', onNoteClick)
})
</script>

<style lang="less" scoped>
.noteViewerWrap {
  padding: 16px;

  &.isDark {
    .noteContent { color: hsla(0, 0%, 100%, 0.8); }
    .emptyTip { color: hsla(0, 0%, 100%, 0.4); }
  }

  .noteContent {
    font-size: 14px;
    line-height: 1.6;
    color: #333;
    word-break: break-word;
  }

  .emptyTip {
    text-align: center;
    color: #999;
    padding: 40px 0;
  }
}
</style>
