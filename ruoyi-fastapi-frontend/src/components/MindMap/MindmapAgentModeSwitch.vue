<template>
  <button
    type="button"
    class="agentModeSwitch"
    :class="{ 'is-discussion': modelValue }"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="description"
    :title="description"
    :disabled="disabled"
    @click="select(!modelValue)"
  >
    <svg v-if="modelValue" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-3 1 1-3L16.5 3.5z"/></svg>
  </button>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ modelValue: Boolean, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const description = computed(() => props.modelValue ? '讨论：只回答，不修改脑图' : '编辑：允许修改授权范围内的脑图')
function select(value) { if (!props.disabled) emit('update:modelValue', value) }
</script>
<style scoped>
.agentModeSwitch { display:grid; width:32px; height:32px; flex:none; padding:0; place-items:center; border:1px solid var(--agent-border); border-radius:50%; background:var(--ai-panel-bg); color:var(--agent-ink); cursor:pointer; }
.agentModeSwitch:hover:not(:disabled) { background:var(--agent-hover); }
.agentModeSwitch.is-discussion { color:var(--agent-muted); }
.agentModeSwitch:focus-visible { outline:2px solid var(--agent-accent); outline-offset:2px; }
.agentModeSwitch:disabled { cursor:not-allowed; opacity:.55; }
svg { width:16px; height:16px; transform:translateY(1px); }
</style>
