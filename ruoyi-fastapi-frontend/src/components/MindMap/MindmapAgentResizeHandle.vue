<!-- Open Design ProjectView's pointer/keyboard split resizing, adapted to Vue.
     See docs/third-party/open-design-chat.md. -->
<template>
  <div class="agentResizeHandle" :class="{ 'is-dragging': dragging }" role="separator" tabindex="0"
    aria-label="调整 AI 聊天栏宽度" aria-orientation="vertical" aria-controls="mindmap-agent-panel"
    :aria-valuemin="bounds.min" :aria-valuemax="bounds.max" :aria-valuenow="width"
    :aria-valuetext="`${width} 像素；方向键调整，Home 最窄，End 最宽，双击恢复默认`"
    title="拖动调整宽度 · 方向键调整 · 双击恢复默认"
    @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="cancel"
    @lostpointercapture="cancel" @keydown="keydown" @blur="cancel" @dblclick="$emit('reset')" />
</template>
<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { agentPanelKeyboardWidth } from '@/utils/mindmap-agent-layout'
const props = defineProps({ width: { type: Number, required: true }, bounds: { type: Object, required: true }, active: Boolean })
const emit = defineEmits(['preview', 'commit', 'cancel', 'reset'])
const dragging = ref(false)
let gesture = null
let frame = null
let pendingX = null
function clearFrame() {
  if (frame !== null) cancelAnimationFrame(frame)
  frame = null
  pendingX = null
}
function release() {
  const current = gesture
  gesture = null
  dragging.value = false
  clearFrame()
  if (current?.target.hasPointerCapture?.(current.id)) current.target.releasePointerCapture(current.id)
  window.removeEventListener('blur', cancel)
  window.removeEventListener('resize', cancel)
}
function cancel(event) {
  if (!gesture) return
  if (event?.pointerId != null && event.pointerId !== gesture.id) return
  release()
  emit('cancel')
}
function start(event) {
  if (!props.active || !props.bounds.desktop || event.button !== 0 || gesture) return
  event.preventDefault()
  event.currentTarget.focus({ preventScroll: true })
  gesture = { id: event.pointerId, x: event.clientX, width: props.width, target: event.currentTarget, moved: false }
  event.currentTarget.setPointerCapture(event.pointerId)
  dragging.value = true
  window.addEventListener('blur', cancel)
  window.addEventListener('resize', cancel)
}
function move(event) {
  if (!gesture || event.pointerId !== gesture.id) return
  pendingX = event.clientX
  if (frame !== null) return
  frame = requestAnimationFrame(() => {
    frame = null
    if (!gesture || pendingX === null || (pendingX === gesture.x && !gesture.moved)) return
    gesture.moved = true
    emit('preview', gesture.width + pendingX - gesture.x)
  })
}
function finish(event) {
  if (!gesture || event.pointerId !== gesture.id) return
  const value = gesture.width + event.clientX - gesture.x
  const moved = gesture.moved || event.clientX !== gesture.x
  release()
  if (moved) emit('commit', value)
}
function keydown(event) {
  if (event.key === 'Escape' && gesture) { event.preventDefault(); cancel(); return }
  if (gesture || !props.active) return
  const next = agentPanelKeyboardWidth(event, props.width, props.bounds)
  if (next === null) return
  event.preventDefault()
  emit('commit', next)
}
watch(() => [props.active, props.bounds.min, props.bounds.max], cancel)
onBeforeUnmount(cancel)
</script>
<style scoped>
.agentResizeHandle { position: absolute; z-index: 3; top: 0; right: 0; bottom: 0; width: 7px; cursor: col-resize; touch-action: none; user-select: none; }
.agentResizeHandle::after { content: ''; position: absolute; width: 2px; top: 0; bottom: 0; right: 0; background: transparent; }
.agentResizeHandle:hover::after,.agentResizeHandle:focus-visible::after,.agentResizeHandle.is-dragging::after { background: var(--agent-accent); }
.agentResizeHandle:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: -2px; }
.agentResizeHandle.is-dragging { width: 12px; }
</style>
