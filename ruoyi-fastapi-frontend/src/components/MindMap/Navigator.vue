<template>
  <div
    v-if="showMiniMap"
    class="navigatorBox"
    :class="{ isDark: isDark }"
    ref="navigatorBoxRef"
    :style="{ width: width + 'px' }"
    role="region"
    aria-label="脑图小地图"
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
      <img :src="mindMapImg" alt="" draggable="false" @mousedown.prevent />
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
import { createScopedAsyncSession } from '@/utils/mindmap-async'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'

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
let componentAlive = true
const miniMapSession = createScopedAsyncSession()

function releaseMiniMapDrag(mindMap = props.mindMap) {
  mindMap?.miniMap?.onMouseup?.()
}

function invalidateMiniMap({ clearImage = false } = {}) {
  miniMapSession.invalidate()
  clearTimeout(timer)
  timer = null
  if (clearImage) {
    mindMapImg.value = ''
  }
}

function toggleMiniMap(show) {
  const nextShow = Boolean(show)
  showMiniMap.value = nextShow
  if (!nextShow) {
    releaseMiniMapDrag()
    invalidateMiniMap({ clearImage: true })
    return
  }
  nextTick(() => {
    if (!componentAlive || !showMiniMap.value) return
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

function onDataChange(_data, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  dataChange()
}

function onViewDataChange(_viewData, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  dataChange()
}

function onNodeTreeRenderEnd(sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  dataChange()
}

function setSize() {
  clearTimeout(setSizeTimer)
  setSizeTimer = setTimeout(() => {
    if (!componentAlive) return
    width.value = Math.max(0, Math.min(window.innerWidth - 80, 370))
    nextTick(() => {
      if (componentAlive && showMiniMap.value) {
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

async function drawMiniMap() {
  const activeMindMap = props.mindMap
  if (
    !componentAlive
    || !showMiniMap.value
    || !activeMindMap?.miniMap
    || boxWidth.value <= 0
    || boxHeight.value <= 0
  ) return

  const session = miniMapSession.activate(activeMindMap)
  try {
    const result = activeMindMap.miniMap.calculationMiniMap(
      boxWidth.value,
      boxHeight.value,
    )
    if (!result || !miniMapSession.isCurrent(session)) return

    viewBoxStyle.value = result.viewBoxStyle
    svgBoxScale.value = result.miniMapBoxScale
    svgBoxLeft.value = result.miniMapBoxLeft
    svgBoxTop.value = result.miniMapBoxTop

    await result.getImgUrl(img => {
      if (
        !componentAlive
        || !showMiniMap.value
        || props.mindMap !== activeMindMap
        || !miniMapSession.isCurrent(session)
      ) return
      mindMapImg.value = typeof img === 'string' ? img : ''
    })
  } catch {
    if (miniMapSession.isCurrent(session)) {
      mindMapImg.value = ''
    }
  }
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
  bus.on('data_change', onDataChange)
  bus.on('view_data_change', onViewDataChange)
  bus.on('node_tree_render_end', onNodeTreeRenderEnd)
})

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) {
    releaseMiniMapDrag(oldMm)
    oldMm.off?.('mini_map_view_box_position_change', onViewBoxPositionChange)
  }
  invalidateMiniMap({ clearImage: true })
  if (mm) {
    mm.on?.('mini_map_view_box_position_change', onViewBoxPositionChange)
  }
  if (mm && showMiniMap.value) {
    nextTick(() => {
      if (!componentAlive || !showMiniMap.value || props.mindMap !== mm) return
      init()
      drawMiniMap()
    })
  }
}, { immediate: true })

onBeforeUnmount(() => {
  componentAlive = false
  releaseMiniMapDrag()
  invalidateMiniMap({ clearImage: true })
  window.removeEventListener('resize', setSize)
  window.removeEventListener('mouseup', onMouseup)
  bus.off('toggle_mini_map', toggleMiniMap)
  bus.off('data_change', onDataChange)
  bus.off('view_data_change', onViewDataChange)
  bus.off('node_tree_render_end', onNodeTreeRenderEnd)
  props.mindMap?.off?.('mini_map_view_box_position_change', onViewBoxPositionChange)
  clearTimeout(setSizeTimer)
})
</script>

<style lang="less" scoped>
.navigatorBox {
  position: absolute;
  height: 200px;
  background-color: #fff;
  bottom: 70px;
  left: 20px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08), 0 0 1px rgba(0, 0, 0, 0.06);
  border-radius: 8px;
  border: 1px solid #dee0e3;
  cursor: pointer;
  user-select: none;
  overflow: hidden;

  &.isDark {
    background-color: #2a2d32;
    border-color: #3d4046;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  }

  .svgBox {
    position: absolute;
    left: 0;
    transform-origin: left top;
  }

  .windowBox {
    position: absolute;
    border: 1.5px solid #3370ff;
    background-color: rgba(51, 112, 255, 0.08);
    border-radius: 2px;

    &.withTransition {
      transition: all 0.2s ease;
    }
  }
}
</style>
