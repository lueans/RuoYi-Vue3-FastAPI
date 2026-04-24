<template>
  <Sidebar ref="sidebarRef" title="大纲">
    <div class="outline-actions">
      <el-tooltip content="进入大纲编辑模式" placement="bottom">
        <el-button size="small" @click="openOutlineEdit">
          <span class="iconfont iconbianji1"></span> 编辑模式
        </el-button>
      </el-tooltip>
    </div>
    <div class="outline-tree" v-if="outlineData">
      <div v-for="(item, i) in flatOutline" :key="i"
        class="outline-node"
        :style="{ paddingLeft: item.level * 20 + 'px' }"
        @click="goToNode(item.uid)">
        <span class="outline-expand" v-if="item.hasChildren"
          @click.stop="toggleExpand(item)">
          {{ item.expanded ? '▾' : '▸' }}
        </span>
        <span class="outline-text">{{ item.text || '空节点' }}</span>
      </div>
    </div>
    <div v-else class="empty-tip">暂无数据</div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const outlineData = ref(null)
const collapsedUids = ref(new Set())

function updateOutline() {
  if (!props.mindMap) return
  outlineData.value = props.mindMap.getData()
}

const flatOutline = computed(() => {
  if (!outlineData.value) return []
  const result = []
  function walk(node, level) {
    const uid = node.data?.uid || ''
    const hasChildren = node.children?.length > 0
    const expanded = !collapsedUids.value.has(uid)
    result.push({
      text: node.data?.text || '',
      uid,
      level,
      hasChildren,
      expanded,
    })
    if (hasChildren && expanded) {
      node.children.forEach(c => walk(c, level + 1))
    }
  }
  walk(outlineData.value, 0)
  return result
})

function toggleExpand(item) {
  if (collapsedUids.value.has(item.uid)) {
    collapsedUids.value.delete(item.uid)
  } else {
    collapsedUids.value.add(item.uid)
  }
}

function goToNode(uid) {
  if (!props.mindMap || !uid) return
  props.mindMap.execCommand('GO_TARGET_NODE', uid)
}

function openOutlineEdit() {
  actions.setActiveSidebar(null)
  bus.emit('openOutlineEdit')
}

onMounted(() => {
  bus.on('data_change', updateOutline)
  bus.on('node_tree_render_end', updateOutline)
})

onBeforeUnmount(() => {
  bus.off('data_change', updateOutline)
  bus.off('node_tree_render_end', updateOutline)
})

watch(() => store.activeSidebar, (val) => {
  if (val === 'outline') {
    updateOutline()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})
</script>

<style scoped lang="scss">
.outline-tree {
  .outline-node {
    display: flex;
    align-items: center;
    padding: 6px 8px;
    font-size: 13px;
    cursor: pointer;
    border-radius: 4px;
    &:hover { background: #f5f7fa; }
  }
  .outline-expand {
    width: 16px;
    flex-shrink: 0;
    cursor: pointer;
    color: #999;
    font-size: 12px;
  }
  .outline-text {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
.outline-actions {
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  justify-content: flex-end;
}
.empty-tip { text-align: center; color: #999; padding: 40px 0; }
</style>
