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
let dataVersion = 0

const wrapperStyle = computed(() => ({
  width: props.width,
  height: props.height
}))

registerPlugins(props.preset, props.extraPlugins)

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
    dataVersion++
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
})

onBeforeUnmount(() => {
  if (mindMapInstance.value) {
    mindMapInstance.value.destroy()
    mindMapInstance.value = null
  }
})

let lastAppliedVersion = 0
watch(() => props.modelValue, (val) => {
  if (dataVersion !== lastAppliedVersion) {
    lastAppliedVersion = dataVersion
    return
  }
  if (val && mindMapInstance.value) {
    mindMapInstance.value.setData(val)
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
