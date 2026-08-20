<template>
  <div
    class="imgPlacementToolbar"
    :class="{ isDark: isDark }"
    v-show="showToolbar"
    ref="toolbarRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    role="toolbar"
    aria-label="节点图片位置"
    @click.stop
    @mousedown.stop
  >
    <el-tooltip v-for="item in placements" :key="item.value" :content="item.name" placement="top">
      <button
        type="button"
        class="btn"
        :class="{ active: currentPlacement === item.value }"
        :aria-label="`将图片放在节点${item.name}`"
        :aria-pressed="currentPlacement === item.value"
        :disabled="isReadonly"
        @click="setPlacement(item.value)"
      >
        <span
          class="placementIcon iconfont icontupianweizhi"
          :style="{ transform: item.rotate }"
          aria-hidden="true"
        ></span>
      </button>
    </el-tooltip>
  </div>
</template>

<script setup>
import { store } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const showToolbar = ref(false)
const toolbarRef = ref(null)
const left = ref(0)
const top = ref(0)
const currentPlacement = ref('right')
let currentNode = null
let imgNode = null
let currentMindMap = null

const placements = [
  { name: '上方', value: 'top', rotate: 'rotate(0deg)' },
  { name: '下方', value: 'bottom', rotate: 'rotate(180deg)' },
  { name: '左方', value: 'left', rotate: 'rotate(-90deg)' },
  { name: '右方', value: 'right', rotate: 'rotate(90deg)' }
]

function showAt(node, imgEl) {
  const activeMindMap = props.mindMap
  if (
    isReadonly.value
    || !activeMindMap
    || !node
    || (node.mindMap && node.mindMap !== activeMindMap)
  ) return
  currentNode = node
  imgNode = imgEl
  currentMindMap = activeMindMap
  currentPlacement.value = node.getStyle('imgPlacement') || 'right'
  positionToolbar()
  showToolbar.value = true
}

function positionToolbar() {
  if (!imgNode || !currentMindMap || currentMindMap !== props.mindMap) return
  const rect = typeof imgNode.rbox === 'function' ? imgNode.rbox() : null
  if (!rect) return
  left.value = rect.x + rect.width / 2 - 60
  top.value = rect.y - 40
}

function close() {
  showToolbar.value = false
  currentNode = null
  imgNode = null
  currentMindMap = null
}

function setPlacement(val) {
  if (
    isReadonly.value
    || !currentNode
    || !currentMindMap
    || currentMindMap !== props.mindMap
    || currentNode.mindMap !== currentMindMap
  ) return
  currentNode.setStyle('imgPlacement', val)
  currentPlacement.value = val
}

function onNodeActive(node, list) {
  if (!currentNode) return
  if (!list || list.length === 0 || list[0] !== currentNode) {
    close()
  }
}

function onScale() {
  if (showToolbar.value) positionToolbar()
}

watch(() => props.mindMap, (mm, oldMm) => {
  oldMm?.off?.('node_img_click', showAt)
  oldMm?.off?.('draw_click', close)
  oldMm?.off?.('svg_mousedown', close)
  oldMm?.off?.('node_dblclick', close)
  oldMm?.off?.('translate', close)
  oldMm?.off?.('node_active', onNodeActive)
  oldMm?.off?.('scale', onScale)
  if (mm !== oldMm) close()
  mm?.on?.('node_img_click', showAt)
  mm?.on?.('draw_click', close)
  mm?.on?.('svg_mousedown', close)
  mm?.on?.('node_dblclick', close)
  mm?.on?.('translate', close)
  mm?.on?.('node_active', onNodeActive)
  mm?.on?.('scale', onScale)
}, { immediate: true })

watch(isReadonly, (readonly) => {
  if (readonly) close()
})

onMounted(() => {
  if (toolbarRef.value) document.body.appendChild(toolbarRef.value)
})

onBeforeUnmount(() => {
  close()
  props.mindMap?.off?.('node_img_click', showAt)
  props.mindMap?.off?.('draw_click', close)
  props.mindMap?.off?.('svg_mousedown', close)
  props.mindMap?.off?.('node_dblclick', close)
  props.mindMap?.off?.('translate', close)
  props.mindMap?.off?.('node_active', onNodeActive)
  props.mindMap?.off?.('scale', onScale)
  if (toolbarRef.value?.parentNode === document.body) {
    document.body.removeChild(toolbarRef.value)
  }
})
</script>

<style lang="less" scoped>
.imgPlacementToolbar {
  position: fixed;
  z-index: 10000;
  background: #fff;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.12);
  border-radius: 4px;
  padding: 4px;
  display: flex;
  align-items: center;

  &.isDark {
    background: #363b3f;
    .btn { color: hsla(0, 0%, 100%, 0.8); }
  }

  .btn {
    width: 28px;
    height: 28px;
    display: flex;
    justify-content: center;
    align-items: center;
    cursor: pointer;
    border: 0;
    border-radius: 4px;
    background: transparent;
    font-size: 16px;

    &:hover { background: #f0f0f0; }
    &:focus-visible { outline: 2px solid #409eff; outline-offset: -2px; }
    &.active { color: #409eff; background: #ecf5ff; }
  }

  .placementIcon {
    display: inline-flex;
  }
}
</style>
