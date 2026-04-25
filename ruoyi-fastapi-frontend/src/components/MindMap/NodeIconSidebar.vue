<template>
  <Sidebar ref="sidebarRef" title="图标">
    <div class="node-icon-sidebar">
      <div v-for="group in iconList" :key="group.type" class="icon-group">
        <div class="group-title">{{ group.name }}</div>
        <div class="icon-grid">
          <div v-for="item in group.list" :key="item.name"
            class="icon-item" :class="{ selected: isSelected(group.type, item.name) }"
            @click="setIcon(group.type, item.name)"
            v-html="item.icon"
            :title="item.name">
          </div>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store } from './useStore'
import { nodeIconList } from '@mind-map/src/svg/icons'

const sidebarRef = ref(null)
const activeNodes = ref([])
const currentIcons = ref([])

const iconList = nodeIconList

function isSelected(type, name) {
  return currentIcons.value.includes(type + '_' + name)
}

function setIcon(type, name) {
  const key = type + '_' + name
  activeNodes.value.forEach(node => {
    const icons = node.getData('icon') || []
    const newIcons = [...icons]
    const existingIndex = newIcons.findIndex(i => i === key)
    const sameTypeIndex = newIcons.findIndex(i => i.startsWith(type + '_'))

    if (existingIndex !== -1) {
      newIcons.splice(existingIndex, 1)
    } else if (sameTypeIndex !== -1) {
      newIcons[sameTypeIndex] = key
    } else {
      newIcons.push(key)
    }
    node.setIcon(newIcons)
  })
  readIcons()
}

function readIcons() {
  const node = activeNodes.value[0]
  currentIcons.value = node ? (node.getData('icon') || []) : []
}

function onNodeActive(_, list) {
  activeNodes.value = list ? [...list] : []
  if (list?.length > 0) readIcons()
}

onMounted(() => {
  bus.on('node_active', onNodeActive)
})
onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
})

watch(() => store.activeSidebar, (val) => {
  if (val === 'nodeIconSidebar') {
    readIcons()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})
</script>

<style lang="less" scoped>
.node-icon-sidebar {
  padding-top: 6px;

  .icon-group {
    margin-bottom: 20px;
    padding: 0 20px;
  }
  .group-title {
    font-size: 16px;
    font-weight: 500;
    color: #333;
    margin-bottom: 10px;
  }
  .icon-grid {
    display: flex;
    flex-wrap: wrap;
  }
  .icon-item {
    width: 24px;
    height: 24px;
    margin-right: 10px;
    margin-bottom: 10px;
    cursor: pointer;
    position: relative;

    img {
      width: 100%;
      height: 100%;
    }

    svg {
      width: 100%;
      height: 100%;
    }

    &:hover { opacity: 0.7; }

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
</style>
