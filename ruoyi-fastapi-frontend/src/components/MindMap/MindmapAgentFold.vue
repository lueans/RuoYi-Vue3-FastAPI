<!-- Adapted from Open Design Foldable / record.module.css (Apache-2.0).
     Vue port: only explicit summary clicks own manual state.
     See docs/third-party/open-design-chat.md. -->
<template>
  <details class="agentFold" :class="{ 'is-flat': flat }" :open="open">
    <summary :aria-label="label" @click.prevent="toggle">
      <span class="foldTitle"><slot name="title">{{ label }}</slot></span>
      <span v-if="meta" class="foldMeta">{{ meta }}</span>
      <el-icon class="foldChevron" aria-hidden="true"><ArrowDown /></el-icon>
    </summary>
    <div v-if="activated" class="foldBody"><slot /></div>
  </details>
</template>
<script setup>
import { ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
const props = defineProps({ label: String, meta: String, flat: Boolean, autoOpen: Boolean })
const open = ref(props.autoOpen)
const activated = ref(props.autoOpen)
const manuallyToggled = ref(false)
watch(() => props.autoOpen, value => {
  if (!manuallyToggled.value) open.value = value
  if (value) activated.value = true
})
function toggle() {
  manuallyToggled.value = true
  open.value = !open.value
  if (open.value) activated.value = true
}
</script>
<style scoped>
.agentFold { border: 0; border-radius: 8px; background: var(--agent-surface); }
summary { display: flex; align-items: center; gap: 7px; padding: 8px 11px; list-style: none; cursor: pointer; border-radius: 8px; color: var(--agent-ink); font-size: 12px; line-height: 1.5; }
summary::-webkit-details-marker { display: none; }
summary:hover { background: var(--agent-hover); }
summary:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
.foldTitle { display: flex; align-items: center; gap: 7px; min-width: 0; flex: 1; }
.foldMeta { flex: none; color: var(--agent-muted); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.foldChevron { flex: none; font-size: 12px; color: var(--agent-muted); transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1); }
[open] > summary .foldChevron { transform: rotate(180deg); }
.foldBody { padding: 2px 11px 10px; font-size: 12px; line-height: 1.7; }
.is-flat { background: transparent; border-radius: 0; }
.is-flat > summary { margin-inline: -7px; padding: 6px 7px; font-size: 13px; font-weight: 600; }
.is-flat > .foldBody { border-top: 1px solid var(--agent-border); padding: 6px 0 2px; }
@media (prefers-reduced-motion: reduce) { .foldChevron { transition: none; } }
</style>
