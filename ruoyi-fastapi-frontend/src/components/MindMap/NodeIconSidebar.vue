<template>
  <Sidebar ref="sidebarRef" title="图标" open-on-mount>
    <div class="node-icon-sidebar" :class="{ isDark }">
      <div v-for="group in iconList" :key="group.type" class="icon-group">
        <div class="group-title">{{ group.name }}</div>
        <div class="icon-grid" role="group" :aria-label="group.name">
          <button v-for="item in group.list" :key="item.name"
            type="button"
            class="icon-item" :class="{ selected: isSelected(group.type, item.name) }"
            :disabled="isReadonly"
            @click="setIcon(group.type, item.name)"
            v-html="item.icon"
            :aria-label="`${group.name}：${item.name}`"
            :aria-pressed="isSelected(group.type, item.name)"
            :title="item.name">
          </button>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store, actions } from './useStore'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'
import { nodeIconList } from '@mind-map/src/svg/icons'
import {
  getCommonNodeIcons,
  toggleNodeIconAcrossLists,
} from '@/utils/mindmap-node-icon'

const props = defineProps({
  mindMap: { type: Object, default: null },
})

const sidebarRef = ref(null)
const { activeNodes, syncActiveNodes } = useMindMapActiveNodes({
  resolveMindMap: () => props.mindMap,
})
const currentIcons = ref([])

const iconList = nodeIconList
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)

function isSelected(type, name) {
  return currentIcons.value.includes(type + '_' + name)
}

function setIcon(type, name) {
  if (isReadonly.value) return
  const nodes = activeNodes.value
  const { lists } = toggleNodeIconAcrossLists(
    nodes.map(node => node.getData('icon')),
    type,
    name,
  )
  nodes.forEach((node, index) => {
    node.setIcon(lists[index])
  })
  readIcons()
}

function readIcons() {
  currentIcons.value = getCommonNodeIcons(
    activeNodes.value.map(node => node.getData('icon')),
  )
}

watch(activeNodes, () => {
  readIcons()
  if (activeNodes.value.length === 0 && store.activeSidebar === 'nodeIconSidebar') {
    actions.setActiveSidebar(null)
  }
}, { flush: 'sync' })

watch(() => store.activeSidebar, (val) => {
  if (val === 'nodeIconSidebar') {
    syncActiveNodes()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })
</script>

<style lang="less" scoped>
.node-icon-sidebar {
  padding-top: 6px;

  &.isDark {
    .group-title {
      color: #f5f7fa;
    }

    .icon-item {
      border-radius: 4px;

      &:hover {
        background: #34383f;
        opacity: 1;
      }
    }
  }

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
    width: 32px;
    height: 32px;
    padding: 4px;
    border: 0;
    background: transparent;
    margin-right: 10px;
    margin-bottom: 10px;
    cursor: pointer;
    position: relative;

    :deep(img) {
      width: 100%;
      height: 100%;
      display: block;
    }

    :deep(svg) {
      width: 100%;
      height: 100%;
      display: block;
    }

    &:hover { opacity: 0.7; }

    &:focus-visible {
      outline: 2px solid #409eff;
      outline-offset: 3px;
      border-radius: 3px;
    }

    &.selected {
      &::after {
        content: '';
        position: absolute;
        inset: 0;
        border-radius: 6px;
        border: 2px solid #409eff;
        box-sizing: border-box;
      }
    }
  }
}
</style>
