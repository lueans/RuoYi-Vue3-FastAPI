<template>
  <div
    class="nodeIconToolbar"
    :class="{ isDark }"
    ref="toolbarRef"
    :style="{ left: posLeft + 'px', top: posTop + 'px' }"
    v-show="visible"
    role="toolbar"
    :aria-label="iconGroupName || '节点图标'"
    @click.stop
    @mousedown.stop
  >
    <div class="iconListBox" role="group" :aria-label="`${iconGroupName || '节点图标'}选项`">
      <button
        type="button"
        class="icon"
        v-for="icon in iconList"
        :key="icon.name"
        :class="{ selected: nodeIconList.includes(iconType + '_' + icon.name) }"
        :aria-label="`${iconGroupName || '节点图标'}：${icon.name}`"
        :aria-pressed="nodeIconList.includes(iconType + '_' + icon.name)"
        :disabled="isReadonly"
        @click="setIcon(icon.name)"
      >
        <span v-html="getHtml(icon.icon)" aria-hidden="true"></span>
      </button>
    </div>
    <div class="btnBox">
      <button type="button" class="btn" aria-label="移除当前节点图标" :disabled="isReadonly" @click="deleteIcon">
        <el-icon><Delete /></el-icon>
        <span>移除图标</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { Delete } from '@element-plus/icons-vue'
import { nodeIconList as builtinIconList } from '@mind-map/src/svg/icons'
import { store } from './useStore'
import { removeNodeIconType, toggleNodeIcon } from '@/utils/mindmap-node-icon'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const toolbarRef = ref(null)
const visible = ref(false)
const posLeft = ref(0)
const posTop = ref(0)
const iconType = ref('')
const iconName = ref('')
const iconGroupName = ref('')
const nodeIconList = ref([])
const iconList = ref([])
let currentNode = null
let currentMindMap = null
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)

function show(node, iconKey) {
  const activeMindMap = props.mindMap
  if (
    isReadonly.value
    || !activeMindMap
    || !node
    || (node.mindMap && node.mindMap !== activeMindMap)
  ) return
  currentNode = node
  currentMindMap = activeMindMap
  iconType.value = iconKey.split('_')[0]
  iconName.value = iconKey.split('_').slice(1).join('_')
  nodeIconList.value = node.getData('icon') || []
  const group = builtinIconList.find(g => g.type === iconType.value)
  iconGroupName.value = group?.name || '节点图标'
  iconList.value = group ? [...group.list] : []
  updatePos()
  visible.value = true
}

function close() {
  visible.value = false
  currentNode = null
  currentMindMap = null
  iconType.value = ''
  iconName.value = ''
  iconGroupName.value = ''
  nodeIconList.value = []
  iconList.value = []
}

function updatePos() {
  if (!currentNode || !currentMindMap || currentMindMap !== props.mindMap) return
  const rect = currentNode.getRect()
  posLeft.value = rect.x
  posTop.value = rect.y + rect.height
}

function onScale() {
  if (visible.value) updatePos()
}

function onNodeActive(_, activeNodes) {
  if (!activeNodes || activeNodes.length === 0 || activeNodes[0] !== currentNode) {
    close()
  }
}

function deleteIcon() {
  if (
    isReadonly.value
    || !currentNode
    || !currentMindMap
    || currentMindMap !== props.mindMap
    || currentNode.mindMap !== currentMindMap
    || !iconType.value
  ) return
  const list = removeNodeIconType(nodeIconList.value, iconType.value)
  nodeIconList.value = list
  currentNode.setIcon([...list])
  close()
}

function getHtml(icon) {
  return /^<svg/.test(icon) ? icon : `<img src="${icon}" />`
}

function setIcon(name) {
  if (
    isReadonly.value
    || !currentNode
    || !currentMindMap
    || currentMindMap !== props.mindMap
    || currentNode.mindMap !== currentMindMap
    || !iconType.value
  ) return
  const result = toggleNodeIcon(nodeIconList.value, iconType.value, name)
  nodeIconList.value = result.list
  iconName.value = result.selected ? name : ''
  currentNode.setIcon([...result.list])
}

watch(() => props.mindMap, (mm, oldMm) => {
  oldMm?.off?.('node_icon_click', show)
  oldMm?.off?.('draw_click', close)
  oldMm?.off?.('svg_mousedown', close)
  oldMm?.off?.('node_dblclick', close)
  oldMm?.off?.('node_active', onNodeActive)
  oldMm?.off?.('scale', onScale)
  if (mm !== oldMm) close()
  mm?.on?.('node_icon_click', show)
  mm?.on?.('draw_click', close)
  mm?.on?.('svg_mousedown', close)
  mm?.on?.('node_dblclick', close)
  mm?.on?.('node_active', onNodeActive)
  mm?.on?.('scale', onScale)
}, { immediate: true })

watch(isReadonly, (readonly) => {
  if (readonly) close()
})

onMounted(() => {
  if (toolbarRef.value) {
    document.body.appendChild(toolbarRef.value)
  }
})

onBeforeUnmount(() => {
  close()
  props.mindMap?.off?.('node_icon_click', show)
  props.mindMap?.off?.('draw_click', close)
  props.mindMap?.off?.('svg_mousedown', close)
  props.mindMap?.off?.('node_dblclick', close)
  props.mindMap?.off?.('node_active', onNodeActive)
  props.mindMap?.off?.('scale', onScale)
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
      width: 32px;
      height: 32px;
      margin: 4px;
      padding: 4px;
      border: 2px solid transparent;
      border-radius: 6px;
      background: transparent;
      cursor: pointer;
      position: relative;
      float: left;

      &:hover {
        background: #f0f2f5;
      }

      &:focus-visible {
        outline: 2px solid #409eff;
        outline-offset: 1px;
      }

      span,
      img {
        width: 100%;
        height: 100%;
        display: block;
      }

      svg {
        width: 100%;
        height: 100%;
      }

      &.selected {
        border-color: #409eff;
        background: #ecf5ff;
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
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-height: 30px;
      padding: 0 8px;
      border: 0;
      background: transparent;
      cursor: pointer;
      color: rgba(26, 26, 26, 0.8);
      font-size: 14px;

      &:hover {
        color: #f56c6c;
      }

      &:focus-visible {
        outline: 2px solid #409eff;
        outline-offset: -2px;
      }
    }
  }

  &.isDark {
    background: #363b3f;
    border-color: rgba(255, 255, 255, 0.12);

    .iconListBox .icon {
      &:hover { background: rgba(255, 255, 255, 0.1); }
      &.selected { background: rgba(64, 158, 255, 0.16); }
    }

    .btnBox {
      border-top-color: rgba(255, 255, 255, 0.12);
      .btn { color: rgba(255, 255, 255, 0.82); }
    }
  }
}
</style>
