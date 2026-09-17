<template>
  <div class="mind-map-wrapper" :style="wrapperStyle">
    <div ref="containerRef" class="mind-map-container"></div>
  </div>
</template>

<script setup>
import MindMap from '@mind-map'
import { registerPlugins } from './usePlugins'

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({
      data: { text: '根节点', uid: '', expand: true },
      children: []
    })
  },
  layout: {
    type: String,
    default: 'logicalStructure'
  },
  theme: {
    type: String,
    default: 'default'
  },
  themeConfig: {
    type: Object,
    default: () => ({})
  },
  readonly: {
    type: Boolean,
    default: false
  },
  width: {
    type: String,
    default: '100%'
  },
  height: {
    type: String,
    default: '500px'
  },
  preset: {
    type: String,
    default: 'standard'
  },
  extraPlugins: {
    type: Array,
    default: () => []
  },
  options: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits([
  'update:modelValue',
  'node-click',
  'node-dblclick',
  'node-contextmenu',
  'node-active',
  'data-change',
  'scale',
  'ready'
])

const containerRef = ref(null)
const mindMapInstance = shallowRef(null)
let applyingExternalModelValue = false
let lastEmittedModelValue = null
let containerResizeObserver = null
let resizeAnimationFrame = null

const wrapperStyle = computed(() => ({
  width: props.width,
  height: props.height
}))

registerPlugins(props.preset, props.extraPlugins)

function scheduleCanvasResize() {
  if (resizeAnimationFrame !== null) return
  resizeAnimationFrame = window.requestAnimationFrame(() => {
    resizeAnimationFrame = null
    const instance = mindMapInstance.value
    const container = containerRef.value
    if (!instance || !container) return
    const { width, height } = container.getBoundingClientRect()
    // The renderer rejects a zero-sized canvas. This can occur while a dialog is
    // entering/leaving or a responsive column is temporarily hidden.
    if (width <= 0 || height <= 0) return
    instance.resize()
  })
}

onMounted(() => {
  if (!containerRef.value) return

  const instance = new MindMap({
    el: containerRef.value,
    data: props.modelValue,
    layout: props.layout,
    theme: props.theme,
    themeConfig: props.themeConfig,
    readonly: props.readonly,
    ...props.options
  })

  mindMapInstance.value = instance

  instance.on('data_change', (data) => {
    // MindMap#setData initializes a fresh history baseline and emits data_change
    // before replacing the render tree. That event is an implementation detail of
    // applying a prop, not a user edit, so it must not be echoed to the parent or
    // used to suppress the next authoritative realtime frame.
    if (applyingExternalModelValue) return
    lastEmittedModelValue = data
    emit('update:modelValue', data)
    emit('data-change', data)
  })

  instance.on('node_click', (node, e) => {
    emit('node-click', node, e)
  })

  instance.on('node_dblclick', (node, e) => {
    emit('node-dblclick', node, e)
  })

  instance.on('node_contextmenu', (e, node) => {
    emit('node-contextmenu', e, node)
  })

  instance.on('node_active', (node, activeNodes) => {
    emit('node-active', node, activeNodes)
  })

  instance.on('scale', (scale) => {
    emit('scale', scale)
  })

  emit('ready', instance)

  if (typeof ResizeObserver === 'function') {
    containerResizeObserver = new ResizeObserver(scheduleCanvasResize)
    containerResizeObserver.observe(containerRef.value)
  } else {
    window.addEventListener('resize', scheduleCanvasResize)
  }
})

onBeforeUnmount(() => {
  containerResizeObserver?.disconnect()
  containerResizeObserver = null
  window.removeEventListener('resize', scheduleCanvasResize)
  if (resizeAnimationFrame !== null) {
    window.cancelAnimationFrame(resizeAnimationFrame)
    resizeAnimationFrame = null
  }
  if (mindMapInstance.value) {
    mindMapInstance.value.destroy()
    mindMapInstance.value = null
  }
})

watch(() => props.modelValue, (val) => {
  // A v-model parent normally sends the exact emitted object back on the next
  // tick. Ignore only that echo; every other object is an external authoritative
  // update and must reach the canvas (notably every AI draft version).
  if (val === lastEmittedModelValue || toRaw(val) === lastEmittedModelValue) {
    lastEmittedModelValue = null
    return
  }
  if (val && mindMapInstance.value) {
    lastEmittedModelValue = null
    applyingExternalModelValue = true
    try {
      mindMapInstance.value.setData(val)
      // setData schedules its history initialization through a 100 ms throttle.
      // Flush it while the external-update guard is active so that its delayed
      // data_change cannot be mistaken for a user edit after this watcher exits.
      mindMapInstance.value.command?.flushPendingHistory?.()
    } finally {
      applyingExternalModelValue = false
    }
  }
})

watch(() => props.layout, (val) => {
  if (mindMapInstance.value) {
    mindMapInstance.value.setLayout(val)
  }
})

watch(() => props.theme, (val) => {
  if (mindMapInstance.value) {
    mindMapInstance.value.setTheme(val)
  }
})

watch(() => props.themeConfig, (val) => {
  if (mindMapInstance.value) {
    mindMapInstance.value.setThemeConfig(val)
  }
})

watch(() => props.readonly, (val) => {
  if (mindMapInstance.value) {
    mindMapInstance.value.setMode(val ? 'readonly' : 'edit')
  }
})

defineExpose({
  getInstance: () => mindMapInstance.value
})
</script>

<style scoped lang="scss">
.mind-map-wrapper {
  position: relative;
  overflow: hidden;
}

.mind-map-container {
  width: 100%;
  height: 100%;
}
</style>
