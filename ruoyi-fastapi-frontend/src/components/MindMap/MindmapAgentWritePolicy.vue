<template>
  <el-popover v-if="active && description" v-model:visible="open" trigger="click" role="dialog" title="编辑与保存说明" placement="top-end" :width="286" :z-index="4300" :persistent="false" :popper-class="dark ? 'mindmapWritePolicyPopover is-dark' : 'mindmapWritePolicyPopover'">
    <template #reference>
      <button ref="triggerRef" type="button" class="composerWriteMode" :class="{ 'is-discussion': discussion }" :aria-label="`编辑与保存说明：${label}`" :aria-expanded="open" @keydown.esc="dismiss">
        {{ label }}<el-icon aria-hidden="true"><InfoFilled /></el-icon>
      </button>
    </template>
    <p class="writePolicyText" role="note" @keydown.esc="dismiss">{{ description }}</p>
  </el-popover>
  <span v-else class="composerWriteMode" :class="{ 'is-discussion': discussion }">{{ label }}</span>
</template>
<script setup>
import { ref, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
const props = defineProps({ label: String, description: String, discussion: Boolean, dark: Boolean, active: { type: Boolean, default: true } })
const open = ref(false)
const triggerRef = ref(null)
function dismiss(event) {
  if (!open.value) return
  event.preventDefault()
  event.stopPropagation()
  open.value = false
  triggerRef.value?.focus({ preventScroll: true })
}
watch([() => props.active, () => props.label, () => props.description], () => { open.value = false })
</script>
<style scoped>
.composerWriteMode { display: inline-flex; align-items: center; justify-content: flex-end; gap: 4px; min-height: 28px; margin-left: auto; padding: 0 3px; border: 0; border-radius: 5px; background: transparent; color: var(--agent-ink); font: inherit; font-size: 12px; line-height: 1.5; text-align: right; }
button.composerWriteMode { cursor: pointer; }
button.composerWriteMode:hover { background: var(--agent-hover); }
button.composerWriteMode:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
.composerWriteMode.is-discussion { color: var(--agent-muted); }
.composerWriteMode .el-icon { flex: none; color: var(--agent-muted); font-size: 12px; }
.writePolicyText { margin: 0; font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
</style>
<style>
.mindmapWritePolicyPopover.is-dark { --el-bg-color-overlay: #29292e; --el-text-color-regular: #d2d2d5; --el-border-color-light: #39393e; }
</style>
