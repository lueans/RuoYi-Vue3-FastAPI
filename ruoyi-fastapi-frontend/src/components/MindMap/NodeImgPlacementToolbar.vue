<template>
  <div
    class="imgPlacementToolbar"
    :class="{ isDark: isDark }"
    v-show="showToolbar"
    ref="toolbarRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    @click.stop
    @mousedown.stop
  >
    <el-tooltip v-for="item in placements" :key="item.value" :content="item.name" placement="top">
      <div
        class="btn iconfont icontupianweizhi"
        :class="{ active: currentPlacement === item.value }"
        :style="{ transform: item.rotate }"
        @click="setPlacement(item.value)"
      ></div>
    </el-tooltip>
  </div>
</template>

<script setup>
import { store } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const showToolbar = ref(false)
const toolbarRef = ref(null)
const left = ref(0)
const top = ref(0)
const currentPlacement = ref('right')
let currentNode = null
let imgNode = null

const placements = [
  { name: '上方', value: 'top', rotate: 'rotate(0deg)' },
  { name: '下方', value: 'bottom', rotate: 'rotate(180deg)' },
  { name: '左方', value: 'left', rotate: 'rotate(-90deg)' },
  { name: '右方', value: 'right', rotate: 'rotate(90deg)' }
]

function showAt(node, imgEl) {
  currentNode = node
  imgNode = imgEl
  currentPlacement.value = node.getStyle('imgPlacement') || 'right'
  positionToolbar()
  showToolbar.value = true
}

function positionToolbar() {
  if (!imgNode) return
  const rect = typeof imgNode.rbox === 'function' ? imgNode.rbox() : null
  if (!rect) return
  left.value = rect.x + rect.width / 2 - 60
  top.value = rect.y - 40
}

function close() {
  showToolbar.value = false
  currentNode = null
  imgNode = null
}

function setPlacement(val) {
  if (!currentNode) return
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
  if (oldMm) {
    oldMm.off('node_img_click', showAt)
    oldMm.off('draw_click', close)
    oldMm.off('svg_mousedown', close)
    oldMm.off('node_dblclick', close)
    oldMm.off('translate', close)
    oldMm.off('node_active', onNodeActive)
    oldMm.off('scale', onScale)
  }
  if (mm) {
    mm.on('node_img_click', showAt)
    mm.on('draw_click', close)
    mm.on('svg_mousedown', close)
    mm.on('node_dblclick', close)
    mm.on('translate', close)
    mm.on('node_active', onNodeActive)
    mm.on('scale', onScale)
  }
}, { immediate: true })

onMounted(() => {
  if (toolbarRef.value) document.body.appendChild(toolbarRef.value)
})

onBeforeUnmount(() => {
  props.mindMap?.off('node_img_click', showAt)
  props.mindMap?.off('draw_click', close)
  props.mindMap?.off('svg_mousedown', close)
  props.mindMap?.off('node_dblclick', close)
  props.mindMap?.off('translate', close)
  props.mindMap?.off('node_active', onNodeActive)
  props.mindMap?.off('scale', onScale)
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
    border-radius: 4px;
    font-size: 16px;

    &:hover { background: #f0f0f0; }
    &.active { color: #409eff; background: #ecf5ff; }
  }
}
</style>
