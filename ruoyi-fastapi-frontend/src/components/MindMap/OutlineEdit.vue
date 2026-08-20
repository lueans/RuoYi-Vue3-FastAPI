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
        :draggable="!isReadonly"
        :allow-drag="allowDrag"
        :allow-drop="allowDrop"
        @node-drop="onNodeDrop"
      >
        <template #default="{ node, data }">
          <span
            class="nodeEdit"
            :contenteditable="!isReadonly"
            @blur="onNodeBlur($event, data)"
            @keydown="onNodeKeydown($event, node, data)"
            @paste.prevent="onNodePaste($event)"
            v-text="data.label"
          ></span>
        </template>
      </el-tree>
    </div>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { store } from './useStore'
import { createUid } from '@mind-map/src/utils'
import {
  createNewOutlineNode,
  createOutlineTreeNode,
} from '@/utils/mindmap-outline-edit'
import { insertMindmapPlainTextAtSelection } from '@/utils/mindmap-dom-edit'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const isOutlineEdit = ref(false)
const treeData = ref([])
const containerRef = ref(null)

function openOutlineEdit() {
  if (isOutlineEdit.value || isReadonly.value) return
  isOutlineEdit.value = true
  refresh()
  nextTick(() => {
    if (containerRef.value) {
      document.body.appendChild(containerRef.value)
    }
  })
}

function close() {
  blurActiveOutlineEditor()
  isOutlineEdit.value = false
  if (containerRef.value?.parentNode === document.body) {
    document.body.removeChild(containerRef.value)
  }
}

function blurActiveOutlineEditor() {
  const activeElement = document.activeElement
  if (activeElement && containerRef.value?.contains(activeElement)) {
    activeElement.blur()
  }
}

function refresh() {
  if (!props.mindMap) return
  const data = props.mindMap.getData()
  treeData.value = [createOutlineTreeNode(data, createUid)]
}

function onNodeBlur(e, data) {
  updateNodeLabel(e.currentTarget, data)
}

function updateNodeLabel(target, data) {
  if (isReadonly.value) return
  const nextLabel = target?.textContent || ''
  if (nextLabel === data.label) return
  const runtimeNode = findRuntimeNode(data.uid)
  if (!runtimeNode) {
    recoverFromStaleOutline('该节点已被其他协作者删除，大纲已重新加载')
    return
  }
  data.label = nextLabel
  data.originalLabel = nextLabel
  data.originalData = {
    ...data.originalData,
    text: nextLabel,
    richText: false,
  }
  props.mindMap.execCommand('SET_NODE_TEXT', runtimeNode, nextLabel, false, true)
}

function onNodeKeydown(e, node, data) {
  if (isReadonly.value) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    updateNodeLabel(e.currentTarget, data)
    if (node.level <= 1) {
      ElMessage.info('根节点不能创建同级节点，请使用 Tab 创建子节点')
      return
    }
    const parent = node.parent
    if (!parent) return
    const siblings = parent.data.children || parent.data
    const index = Array.isArray(siblings) ? siblings.indexOf(data) : -1
    if (index >= 0) {
      const newNode = createNewOutlineNode(createUid)
      const runtimeNode = findRuntimeNode(data.uid)
      if (!runtimeNode) {
        recoverFromStaleOutline('目标节点已变化，大纲已重新加载')
        return
      }
      siblings.splice(index + 1, 0, newNode)
      treeData.value = [...treeData.value]
      props.mindMap.execCommand('INSERT_NODE', false, [runtimeNode], {
        ...newNode.originalData,
        richText: false,
      })
    }
  } else if (e.key === 'Tab') {
    e.preventDefault()
    if (e.shiftKey) return
    updateNodeLabel(e.currentTarget, data)
    const runtimeNode = findRuntimeNode(data.uid)
    if (!runtimeNode) {
      recoverFromStaleOutline('目标节点已变化，大纲已重新加载')
      return
    }
    if (!data.children) data.children = []
    const newChild = createNewOutlineNode(createUid)
    data.children.push(newChild)
    treeData.value = [...treeData.value]
    props.mindMap.execCommand('INSERT_CHILD_NODE', false, [runtimeNode], {
      ...newChild.originalData,
      richText: false,
    })
  }
}

function onNodePaste(e) {
  if (isReadonly.value) return
  const text = e.clipboardData?.getData('text/plain') || ''
  if (!insertMindmapPlainTextAtSelection(text, e.currentTarget)) {
    ElMessage.warning('浏览器无法在当前位置粘贴纯文本')
  }
}

function findRuntimeNode(uid) {
  return uid ? props.mindMap?.renderer?.findNodeByUid?.(uid) : null
}

function recoverFromStaleOutline(message) {
  ElMessage.warning(message)
  refresh()
}

function allowDrag(node) {
  return !isReadonly.value && node.level > 1
}

function allowDrop(_, dropNode, type) {
  return !isReadonly.value && (dropNode.level > 1 || type === 'inner')
}

function onNodeDrop(draggingNode, dropNode, dropType) {
  if (isReadonly.value) return
  const runtimeNode = findRuntimeNode(draggingNode.data?.uid)
  const targetNode = findRuntimeNode(dropNode.data?.uid)
  if (!runtimeNode || !targetNode) {
    recoverFromStaleOutline('拖拽期间脑图结构已变化，大纲已重新加载')
    return
  }
  if (dropType === 'inner') {
    props.mindMap.execCommand('MOVE_NODE_TO', runtimeNode, targetNode)
  } else if (dropType === 'before') {
    props.mindMap.execCommand('INSERT_BEFORE', runtimeNode, targetNode)
  } else if (dropType === 'after') {
    props.mindMap.execCommand('INSERT_AFTER', runtimeNode, targetNode)
  }
}

watch(() => store.localConfig.isOutlineEdit, (val) => {
  if (val) openOutlineEdit()
})

watch(isReadonly, (readonly) => {
  if (readonly && isOutlineEdit.value) close()
})

onMounted(() => {
  bus.on('openOutlineEdit', openOutlineEdit)
  bus.on('closeOutlineEdit', close)
})

onBeforeUnmount(() => {
  blurActiveOutlineEditor()
  bus.off('openOutlineEdit', openOutlineEdit)
  bus.off('closeOutlineEdit', close)
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
