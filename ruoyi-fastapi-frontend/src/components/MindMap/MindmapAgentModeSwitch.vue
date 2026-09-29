<template>
  <div class="agentModeSwitch" role="radiogroup" aria-label="AI 工作模式" :aria-disabled="disabled || undefined">
    <label v-for="mode in modes" :key="mode.label" :class="{ 'is-selected': modelValue === mode.value, 'is-disabled': disabled }" :title="mode.description">
      <input type="radio" :name="name" :value="String(mode.value)" :checked="modelValue === mode.value"
        :disabled="disabled" :aria-label="mode.description" @change="select(mode.value)" />
      <span>{{ mode.label }}</span>
    </label>
  </div>
</template>
<script setup>
import { useId } from 'vue'
const props = defineProps({ modelValue: Boolean, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const name = `agent-mode-${useId()}`
const modes = [{ label: '讨论', value: true, description: '讨论：只回答，不修改脑图' }, { label: '编辑', value: false, description: '编辑：允许修改授权范围内的脑图' }]
function select(value) { if (!props.disabled) emit('update:modelValue', value) }
</script>
<style scoped>
.agentModeSwitch { display: inline-flex; flex: none; padding: 2px; gap: 2px; border: 1px solid var(--agent-border); border-radius: 7px; background: var(--ai-panel-bg); }
label { position: relative; cursor: pointer; }
input { position: absolute; inset: 0; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: inherit; }
span { display: flex; align-items: center; justify-content: center; min-width: 38px; min-height: 26px; padding: 0 5px; border-radius: 4px; font-size: 12px; line-height: 1.5; color: var(--agent-muted); }
.is-selected span { background: var(--agent-user-bg); color: var(--agent-user-ink); }
input:focus-visible + span { outline: 2px solid var(--agent-accent); outline-offset: 1px; }
.is-disabled { cursor: not-allowed; opacity: .6; }
</style>
