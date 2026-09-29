<!-- A persistent, non-modal workspace column, like Open Design's chat pane.
     Hiding this shell never unmounts or stops the parent task. -->
<template>
  <Teleport to="body">
    <Transition name="agent-panel" @after-leave="afterLeave">
      <div v-if="rendered" v-show="modelValue" class="mindmapAiDrawerOverlay agentPanelLayer" :style="{ zIndex }">
        <aside ref="panelRef" v-bind="$attrs" class="agentPanelShell" :style="{ width: `${width}px` }"
          :aria-label="label" tabindex="-1" @keydown.esc="$emit('escape', $event)">
          <div class="el-drawer__body"><slot /></div>
          <div class="el-drawer__footer"><slot name="footer" /></div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>
<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: Boolean, width: Number, label: { type: String, default: 'AI 脑图助手' }, zIndex: { type: Number, default: 2001 } })
const emit = defineEmits(['closed', 'escape'])
const panelRef = ref(null)
const rendered = ref(false)
let opener = null
let focusGeneration = 0
watch(() => props.modelValue, async visible => {
  const generation = ++focusGeneration
  const focused = document.activeElement
  if (visible) {
    rendered.value = true
    opener = focused
    await nextTick()
    if (generation === focusGeneration && props.modelValue && document.activeElement === focused) {
      panelRef.value?.focus({ preventScroll: true })
    }
  } else if (panelRef.value?.contains(focused)) {
    await nextTick()
    // Never take focus back from a user who has already returned to the canvas.
    if (generation === focusGeneration && !props.modelValue && opener?.isConnected
      && (document.activeElement === focused || document.activeElement === document.body)) {
      opener.focus({ preventScroll: true })
    }
  }
}, { immediate: true })
function afterLeave() { if (!props.modelValue) emit('closed') }
onBeforeUnmount(() => { focusGeneration++ })
</script>
<style scoped>
.agentPanelLayer { position: fixed; pointer-events: none; }
.agentPanelShell { position: absolute; inset: 0 auto 0 0; display: flex; flex-direction: column; box-sizing: border-box; max-width: 100%; height: 100%; overflow: hidden; pointer-events: auto; }
.agentPanelShell:focus { outline: none; }
.el-drawer__body { flex: 1; min-height: 0; }
.el-drawer__footer { flex: none; }
.agent-panel-enter-active .agentPanelShell { transition: transform 200ms cubic-bezier(0.23, 1, 0.32, 1), opacity 200ms; }
.agent-panel-leave-active .agentPanelShell { transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1), opacity 140ms; pointer-events: none; }
.agent-panel-enter-from .agentPanelShell,.agent-panel-leave-to .agentPanelShell { transform: translateX(-20px); opacity: 0; }
@media (prefers-reduced-motion: reduce) { .agentPanelShell { transition: none !important; } }
</style>
