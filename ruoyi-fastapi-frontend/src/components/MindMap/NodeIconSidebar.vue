<template>
  <Sidebar ref="sidebarRef" title="图标">
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

<style scoped lang="scss">
.icon-group { margin-bottom: 16px; }
.group-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #f0f0f0;
}
.icon-grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 4px;
}
.icon-item {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.15s;
  :deep(svg) { width: 20px; height: 20px; }
  &:hover { background: #f5f7fa; }
  &.selected { border-color: #409eff; background: #ecf5ff; }
}
</style>
