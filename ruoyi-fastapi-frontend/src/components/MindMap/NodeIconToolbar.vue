<template>
  <div
    class="nodeIconToolbar"
    ref="toolbarRef"
    :style="{ left: posLeft + 'px', top: posTop + 'px' }"
    v-show="visible"
    @click.stop
    @mousedown.stop
  >
    <div class="iconListBox">
      <div
        class="icon"
        v-for="icon in iconList"
        :key="icon.name"
        v-html="getHtml(icon.icon)"
        :class="{ selected: nodeIconList.includes(iconType + '_' + icon.name) }"
        @click="setIcon(icon.name)"
      ></div>
    </div>
    <div class="btnBox">
      <span class="btn" @click="deleteIcon">
        <el-icon><Delete /></el-icon>
      </span>
    </div>
  </div>
</template>

<script setup>
import { Delete } from '@element-plus/icons-vue'
import { nodeIconList as builtinIconList } from '@mind-map/src/svg/icons'
import { actions } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const toolbarRef = ref(null)
const visible = ref(false)
const posLeft = ref(0)
const posTop = ref(0)
const iconType = ref('')
const iconName = ref('')
const nodeIconList = ref([])
const iconList = ref([])
let currentNode = null

function show(node, iconKey) {
  currentNode = node
  iconType.value = iconKey.split('_')[0]
  iconName.value = iconKey.split('_').slice(1).join('_')
  nodeIconList.value = node.getData('icon') || []
  const group = builtinIconList.find(g => g.type === iconType.value)
  iconList.value = group ? [...group.list] : []
  updatePos()
  visible.value = true
}

function close() {
  visible.value = false
  currentNode = null
  iconType.value = ''
  iconName.value = ''
  nodeIconList.value = []
  iconList.value = []
}

function updatePos() {
  if (!currentNode) return
  const rect = currentNode.getRect()
  posLeft.value = rect.x
  posTop.value = rect.y + rect.height
}

function onScale() {
  if (visible.value) updatePos()
}

function onNodeActive(_, activeNodes) {
  if (!activeNodes || activeNodes.length === 0) {
    close()
  }
}

function deleteIcon() {
  setIcon(iconName.value)
  close()
}

function getHtml(icon) {
  return /^<svg/.test(icon) ? icon : `<img src="${icon}" />`
}

function setIcon(name) {
  const key = iconType.value + '_' + name
  const list = [...nodeIconList.value]
  const index = list.findIndex(i => i === key)
  if (index !== -1) {
    list.splice(index, 1)
  } else {
    const typeIndex = list.findIndex(i => i.split('_')[0] === iconType.value)
    if (typeIndex !== -1) {
      list.splice(typeIndex, 1, key)
      iconName.value = name
    } else {
      list.push(key)
    }
  }
  nodeIconList.value = list
  currentNode.setIcon([...list])
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) {
    oldMm.off('node_icon_click', show)
    oldMm.off('draw_click', close)
    oldMm.off('svg_mousedown', close)
    oldMm.off('node_dblclick', close)
    oldMm.off('node_active', onNodeActive)
    oldMm.off('scale', onScale)
  }
  if (mm) {
    mm.on('node_icon_click', show)
    mm.on('draw_click', close)
    mm.on('svg_mousedown', close)
    mm.on('node_dblclick', close)
    mm.on('node_active', onNodeActive)
    mm.on('scale', onScale)
  }
}, { immediate: true })

onMounted(() => {
  if (toolbarRef.value) {
    document.body.appendChild(toolbarRef.value)
  }
})

onBeforeUnmount(() => {
  props.mindMap?.off('node_icon_click', show)
  props.mindMap?.off('draw_click', close)
  props.mindMap?.off('svg_mousedown', close)
  props.mindMap?.off('node_dblclick', close)
  props.mindMap?.off('node_active', onNodeActive)
  props.mindMap?.off('scale', onScale)
  if (toolbarRef.value?.parentNode === document.body) {
    document.body.removeChild(toolbarRef.value)
  }
})
</script>

<style lang="less">
.nodeIconToolbar {
  position: fixed;
  z-index: 2000;
  width: 210px;
  max-height: 170px;
  background: #fff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 8px;
  box-shadow: 0 2px 16px 0 rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  overflow: hidden;

  .iconListBox {
    width: 100%;
    max-height: 140px;
    overflow-y: auto;
    padding: 10px;

    .icon {
      width: 24px;
      height: 24px;
      margin: 5px;
      cursor: pointer;
      position: relative;
      float: left;

      img {
        width: 100%;
        height: 100%;
      }

      svg {
        width: 100%;
        height: 100%;
      }

      &.selected {
        &::after {
          content: '';
          position: absolute;
          left: -4px;
          top: -4px;
          width: 28px;
          height: 28px;
          border-radius: 50%;
          border: 2px solid #409eff;
          box-sizing: content-box;
        }
      }
    }
  }

  .btnBox {
    width: 100%;
    height: 30px;
    display: flex;
    justify-content: center;
    align-items: center;
    border-top: 1px solid #eee;
    flex-shrink: 0;

    .btn {
      cursor: pointer;
      color: rgba(26, 26, 26, 0.8);
      font-size: 14px;

      &:hover {
        color: #f56c6c;
      }
    }
  }
}
</style>
