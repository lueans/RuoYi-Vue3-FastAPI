<template>
  <div
    class="outlineEditContainer"
    :class="{ isDark: isDark }"
    v-if="isOutlineEdit"
    ref="containerRef"
  >
    <div class="header">
      <el-button size="small" @click="close">关闭大纲编辑</el-button>
    </div>
    <div class="treeWrap customScrollbar">
      <el-tree
        :data="treeData"
        node-key="uid"
        :default-expand-all="true"
        :props="{ label: 'label', children: 'children' }"
        draggable
        @node-drop="onNodeDrop"
      >
        <template #default="{ node, data }">
          <span
            class="nodeEdit"
            contenteditable="true"
            @blur="onNodeBlur($event, data)"
            @keydown="onNodeKeydown($event, node, data)"
            @paste.prevent="onNodePaste($event, data)"
            v-text="data.label"
          ></span>
        </template>
      </el-tree>
    </div>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { store, actions } from './useStore'
import { simpleDeepClone, createUid } from '@mind-map/src/utils'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const isOutlineEdit = ref(false)
const treeData = ref([])
const containerRef = ref(null)

function openOutlineEdit() {
  isOutlineEdit.value = true
  refresh()
  nextTick(() => {
    if (containerRef.value) {
      document.body.appendChild(containerRef.value)
    }
  })
}

function close() {
  const data = convertTreeToMindMapData()
  if (data) {
    bus.emit('setData', { root: data })
  }
  isOutlineEdit.value = false
  if (containerRef.value?.parentNode === document.body) {
    document.body.removeChild(containerRef.value)
  }
}

function refresh() {
  if (!props.mindMap) return
  const data = props.mindMap.getData()
  treeData.value = [convertToTreeNode(data)]
}

function convertToTreeNode(node) {
  const text = node.data?.text || ''
  const label = text.replace(/<[^>]*>/g, '')
  return {
    label,
    uid: node.data?.uid || createUid(),
    originalData: node.data,
    children: (node.children || []).map(c => convertToTreeNode(c))
  }
}

function convertTreeToMindMapData() {
  if (!treeData.value[0]) return null
  function walk(treeNode) {
    const data = { ...treeNode.originalData, text: treeNode.label }
    return {
      data,
      children: (treeNode.children || []).map(c => walk(c))
    }
  }
  return walk(treeData.value[0])
}

function onNodeBlur(e, data) {
  data.label = e.target.textContent || ''
}

function onNodeKeydown(e, node, data) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    const parent = node.parent
    if (!parent) return
    const siblings = parent.data.children || parent.data
    const index = Array.isArray(siblings) ? siblings.indexOf(data) : -1
    if (index >= 0) {
      const newNode = { label: '新节点', uid: createUid(), originalData: { text: '新节点', uid: createUid() }, children: [] }
      siblings.splice(index + 1, 0, newNode)
      treeData.value = [...treeData.value]
    }
  } else if (e.key === 'Tab') {
    e.preventDefault()
    if (e.shiftKey) return
    if (!data.children) data.children = []
    const newChild = { label: '新节点', uid: createUid(), originalData: { text: '新节点', uid: createUid() }, children: [] }
    data.children.push(newChild)
    treeData.value = [...treeData.value]
  }
}

function onNodePaste(e, data) {
  const text = e.clipboardData?.getData('text/plain') || ''
  document.execCommand('insertText', false, text)
}

function onNodeDrop() {
  // el-tree handles drag internally, treeData is updated
}

function onKeydown(e) {
  if ((e.key === 'Delete' || e.key === 'Backspace') && !e.target.closest('.nodeEdit')) {
    // Could implement node deletion here
  }
}

watch(() => store.localConfig.isOutlineEdit, (val) => {
  if (val) openOutlineEdit()
})

onMounted(() => {
  bus.on('openOutlineEdit', openOutlineEdit)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  bus.off('openOutlineEdit', openOutlineEdit)
  document.removeEventListener('keydown', onKeydown)
  if (containerRef.value?.parentNode === document.body) {
    document.body.removeChild(containerRef.value)
  }
})
</script>

<style lang="less" scoped>
.outlineEditContainer {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 10000;
  background: #fff;
  display: flex;
  flex-direction: column;

  &.isDark {
    background: #1e1e1e;
    color: #e0e0e0;
    .header { border-bottom-color: #333; }
    .nodeEdit { color: #e0e0e0; }
  }

  .header {
    padding: 12px 20px;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: flex-end;
    flex-shrink: 0;
  }

  .treeWrap {
    flex: 1;
    overflow: auto;
    padding: 20px;

    :deep(.el-tree-node__content) {
      height: auto;
      min-height: 30px;
    }

    .nodeEdit {
      outline: none;
      padding: 2px 4px;
      min-width: 20px;
      border-radius: 2px;

      &:focus {
        background: #f0f7ff;
        box-shadow: 0 0 0 1px #409eff;
      }
    }
  }
}
</style>
