<template>
  <div
    v-if="showMiniMap"
    class="navigatorBox"
    :class="{ isDark: isDark }"
    ref="navigatorBoxRef"
    :style="{ width: width + 'px' }"
    @mousedown="onMousedown"
    @mousemove="onMousemove"
  >
    <div
      class="svgBox"
      ref="svgBoxRef"
      :style="{
        transform: `scale(${svgBoxScale})`,
        left: svgBoxLeft + 'px',
        top: svgBoxTop + 'px'
      }"
    >
      <img :src="mindMapImg" @mousedown.prevent />
    </div>
    <div
      class="windowBox"
      :style="viewBoxStyle"
      :class="{ withTransition: withTransition }"
      @mousedown.stop="onViewBoxMousedown"
      @mousemove="onViewBoxMousemove"
    ></div>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { store } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)

const showMiniMap = ref(false)
const navigatorBoxRef = ref(null)
const svgBoxRef = ref(null)
const mindMapImg = ref('')
const svgBoxScale = ref(1)
const svgBoxLeft = ref(0)
const svgBoxTop = ref(0)
const viewBoxStyle = ref({
  left: 0,
  top: 0,
  bottom: 0,
  right: 0
})
const width = ref(0)
const withTransition = ref(true)
const boxWidth = ref(0)
const boxHeight = ref(0)

let timer = null
let setSizeTimer = null

function toggleMiniMap(show) {
  showMiniMap.value = show
  nextTick(() => {
    if (navigatorBoxRef.value) {
      init()
    }
    if (svgBoxRef.value) {
      drawMiniMap()
    }
  })
}

function dataChange() {
  if (!showMiniMap.value) return
  clearTimeout(timer)
  timer = setTimeout(() => {
    drawMiniMap()
  }, 500)
}

function setSize() {
  clearTimeout(setSizeTimer)
  setSizeTimer = setTimeout(() => {
    width.value = Math.min(window.innerWidth - 80, 370)
    nextTick(() => {
      if (showMiniMap.value) {
        init()
        drawMiniMap()
      }
    })
  }, 300)
}

function init() {
  if (!navigatorBoxRef.value) return
  const rect = navigatorBoxRef.value.getBoundingClientRect()
  boxWidth.value = rect.width
  boxHeight.value = rect.height
}

function drawMiniMap() {
  if (!props.mindMap?.miniMap) return
  const result = props.mindMap.miniMap.calculationMiniMap(boxWidth.value, boxHeight.value)
  if (!result) return
  result.getImgUrl(img => {
    mindMapImg.value = img
  })
  viewBoxStyle.value = result.viewBoxStyle
  svgBoxScale.value = result.miniMapBoxScale
  svgBoxLeft.value = result.miniMapBoxLeft
  svgBoxTop.value = result.miniMapBoxTop
}

function onMousedown(e) {
  props.mindMap?.miniMap?.onMousedown?.(e)
}

function onMousemove(e) {
  props.mindMap?.miniMap?.onMousemove?.(e)
}

function onMouseup(e) {
  if (!withTransition.value) {
    withTransition.value = true
  }
  if (props.mindMap?.miniMap) {
    props.mindMap.miniMap.onMouseup(e)
  }
}

function onViewBoxMousedown(e) {
  props.mindMap?.miniMap?.onViewBoxMousedown?.(e)
}

function onViewBoxMousemove(e) {
  props.mindMap?.miniMap?.onViewBoxMousemove?.(e)
}

function onViewBoxPositionChange({ left, right, top, bottom }) {
  withTransition.value = false
  viewBoxStyle.value = { left, right, top, bottom }
}

onMounted(() => {
  setSize()
  window.addEventListener('resize', setSize)
  window.addEventListener('mouseup', onMouseup)
  bus.on('toggle_mini_map', toggleMiniMap)
  bus.on('data_change', dataChange)
  bus.on('view_data_change', dataChange)
  bus.on('node_tree_render_end', dataChange)
})

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) {
    oldMm.off('mini_map_view_box_position_change', onViewBoxPositionChange)
  }
  if (mm) {
    mm.on('mini_map_view_box_position_change', onViewBoxPositionChange)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', setSize)
  window.removeEventListener('mouseup', onMouseup)
  bus.off('toggle_mini_map', toggleMiniMap)
  bus.off('data_change', dataChange)
  bus.off('view_data_change', dataChange)
  bus.off('node_tree_render_end', dataChange)
  props.mindMap?.off?.('mini_map_view_box_position_change', onViewBoxPositionChange)
  clearTimeout(timer)
  clearTimeout(setSizeTimer)
})
</script>

<style lang="less" scoped>
.navigatorBox {
  position: absolute;
  height: 220px;
  background-color: #fff;
  bottom: 80px;
  right: 70px;
  box-shadow: 0 0 16px #989898;
  border-radius: 4px;
  border: 1px solid #eee;
  cursor: pointer;
  user-select: none;

  &.isDark {
    background-color: #262a2e;
  }

  .svgBox {
    position: absolute;
    left: 0;
    transform-origin: left top;
  }

  .windowBox {
    position: absolute;
    border: 2px solid rgb(238, 69, 69);
    background-color: rgba(238, 69, 69, 0.2);

    &.withTransition {
      transition: all 0.3s;
    }
  }
}
</style>
