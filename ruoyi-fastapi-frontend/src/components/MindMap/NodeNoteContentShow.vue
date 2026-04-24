<template>
  <div
    class="noteContentShowContainer"
    ref="containerRef"
    v-show="show"
    :style="{ left: left + 'px', top: top + 'px' }"
    @click.stop
    @mousedown.stop
    @mousemove.stop
    @mouseup.stop
    @wheel.stop
  >
    <div class="noteContentWrap" v-html="renderedContent"></div>
  </div>
</template>

<script setup>
import bus from './useEventBus'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const containerRef = ref(null)
const show = ref(false)
const left = ref(0)
const top = ref(0)
const renderedContent = ref('')
let currentNode = null

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

function onShowNote(content, l, t, node) {
  if (!content) return
  renderedContent.value = escapeHtml(content)
  currentNode = node
  positionAt(l, t)
  show.value = true
}

function positionAt(l, t) {
  const elRect = props.mindMap?.elRect
  if (!elRect) { left.value = l; top.value = t; return }
  const maxRight = elRect.right - 20
  const maxBottom = elRect.bottom - 20
  const containerWidth = containerRef.value?.offsetWidth || 300
  const containerHeight = containerRef.value?.offsetHeight || 200
  left.value = Math.min(l, maxRight - containerWidth)
  top.value = Math.min(t, maxBottom - containerHeight)
}

function hideNote() {
  show.value = false
  currentNode = null
}

function reposition() {
  if (!show.value || !currentNode) return
  const pos = currentNode.getNoteContentPosition?.()
  if (pos) positionAt(pos.left, pos.top)
}

onMounted(() => {
  bus.on('showNoteContent', onShowNote)
  bus.on('hideNoteContent', hideNote)
  bus.on('node_active', hideNote)
  bus.on('scale', reposition)
  bus.on('translate', reposition)
  bus.on('svg_mousedown', hideNote)
  bus.on('expand_btn_click', hideNote)
  if (containerRef.value && props.mindMap?.el) {
    props.mindMap.el.appendChild(containerRef.value)
  }
})

onBeforeUnmount(() => {
  bus.off('showNoteContent', onShowNote)
  bus.off('hideNoteContent', hideNote)
  bus.off('node_active', hideNote)
  bus.off('scale', reposition)
  bus.off('translate', reposition)
  bus.off('svg_mousedown', hideNote)
  bus.off('expand_btn_click', hideNote)
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
  max-width: 400px;
  max-height: 300px;
  overflow-y: auto;
  pointer-events: all;

  .noteContentWrap {
    font-size: 13px;
    line-height: 1.6;
    color: #333;
    word-break: break-word;
  }
}
</style>
