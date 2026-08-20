<template>
  <button
    v-bind="$attrs"
    type="button"
    class="mindmapColorTrigger"
    :disabled="disabled"
    :aria-label="accessibleLabel"
    :title="accessibleLabel"
    :style="triggerStyle"
  ></button>
</template>

<script setup>
defineOptions({ inheritAttrs: false })

const props = defineProps({
  color: { type: String, default: '' },
  label: { type: String, default: '选择颜色' },
  disabled: { type: Boolean, default: false },
  width: { type: Number, default: 32 },
  height: { type: Number, default: 32 },
})

const normalizedColor = computed(() => String(props.color || '').trim())
const isTransparent = computed(() => (
  !normalizedColor.value || normalizedColor.value.toLowerCase() === 'transparent'
))
const colorDescription = computed(() => isTransparent.value ? '透明色' : normalizedColor.value)
const accessibleLabel = computed(() => `${props.label}，当前${colorDescription.value}`)
const triggerStyle = computed(() => ({
  width: `${props.width}px`,
  height: `${props.height}px`,
  backgroundColor: isTransparent.value ? 'transparent' : normalizedColor.value,
  backgroundImage: isTransparent.value ? undefined : 'none',
}))
</script>

<style scoped>
.mindmapColorTrigger {
  flex: 0 0 auto;
  padding: 0;
  appearance: none;
  border: 1px solid #c8cdd5;
  border-radius: 6px;
  background-image:
    linear-gradient(45deg, #d8dce3 25%, transparent 25%),
    linear-gradient(-45deg, #d8dce3 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #d8dce3 75%),
    linear-gradient(-45deg, transparent 75%, #d8dce3 75%);
  background-position: 0 0, 0 5px, 5px -5px, -5px 0;
  background-size: 10px 10px;
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.72);
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}

.mindmapColorTrigger:hover:not(:disabled) {
  border-color: #409eff;
  transform: translateY(-1px);
}

.mindmapColorTrigger:focus-visible {
  outline: 2px solid #409eff;
  outline-offset: 2px;
}

.mindmapColorTrigger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}
</style>
