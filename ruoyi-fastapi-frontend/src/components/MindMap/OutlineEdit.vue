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
            @focus="onNodeFocus($event, data)"
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
  createOutlineRefreshGate,
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
let pendingOutlineLeaseUid = ''
let activeOutlineLeaseUid = ''
let activeOutlineEditTarget = null
let activeOutlineEditData = null
let outlineLeaseGeneration = 0
let renderEventMindMap = null

const outlineRefreshGate = createOutlineRefreshGate({
  isOpen: () => isOutlineEdit.value,
  hasLocalEdit: () => Boolean(
    pendingOutlineLeaseUid || activeOutlineLeaseUid
  ),
  schedule: callback => nextTick(callback),
  refresh,
})

function onMindMapRenderEnd() {
  outlineRefreshGate.request()
}

function bindRenderEvents(mindMap = props.mindMap) {
  if (!mindMap || renderEventMindMap === mindMap) return
  unbindRenderEvents()
  mindMap.on?.('node_tree_render_end', onMindMapRenderEnd)
  renderEventMindMap = mindMap
}

function unbindRenderEvents() {
  renderEventMindMap?.off?.('node_tree_render_end', onMindMapRenderEnd)
  renderEventMindMap = null
}

function openOutlineEdit() {
  if (isOutlineEdit.value || isReadonly.value) return
  isOutlineEdit.value = true
  outlineRefreshGate.clear()
  bindRenderEvents()
  refresh()
  nextTick(() => {
    if (containerRef.value) {
      document.body.appendChild(containerRef.value)
    }
  })
}

function close() {
  outlineLeaseGeneration += 1
  pendingOutlineLeaseUid = ''
  blurActiveOutlineEditor()
  releaseDetachedOutlineLease()
  isOutlineEdit.value = false
  outlineRefreshGate.clear()
  unbindRenderEvents()
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
  if (
    pendingOutlineLeaseUid === data.uid
    && activeOutlineLeaseUid !== data.uid
  ) return
  try {
    updateNodeLabel(e.currentTarget, data)
  } finally {
    const runtimeNode = findRuntimeNode(data.uid)
    if (activeOutlineLeaseUid === data.uid) {
      activeOutlineLeaseUid = ''
      activeOutlineEditTarget = null
      activeOutlineEditData = null
      releaseOutlineLease(data.uid, runtimeNode)
    }
    outlineRefreshGate.flush()
  }
}

async function onNodeFocus(e, data) {
  if (isReadonly.value) return
  if (
    activeOutlineLeaseUid === data.uid
    || pendingOutlineLeaseUid === data.uid
  ) return
  // 同一浏览器只声明一个节点文本占用；从画布切到大纲前先安全提交画布
  // 浮层，再重新获取可能因渲染而替换的运行时节点实例。
  props.mindMap?.renderer?.textEdit?.hideEditTextBox?.()
  const runtimeNode = findRuntimeNode(data.uid)
  if (!runtimeNode) {
    e.currentTarget?.blur?.()
    recoverFromStaleOutline('该节点已发生变化，大纲已重新加载')
    return
  }
  const usesAuthoritativeLease = (
    props.mindMap?.opt?.isNodeTextEditLeaseAuthoritative?.() === true
  )
  if (!usesAuthoritativeLease && runtimeNode.isTextEditOccupied?.()) {
    e.currentTarget?.blur?.()
    props.mindMap?.emit?.(
      'node_text_edit_blocked',
      runtimeNode,
      [...(runtimeNode.editingUserList || [])],
    )
    return
  }
  const target = e.currentTarget
  const generation = ++outlineLeaseGeneration
  pendingOutlineLeaseUid = data.uid
  // contenteditable 在 Promise 等待期间必须立即失焦，避免未拿锁的两个
  // 浏览器都继续接收键盘输入。
  target?.blur?.()
  const beforeTextEdit = props.mindMap?.opt?.beforeTextEdit
  let granted = true
  if (typeof beforeTextEdit === 'function') {
    try {
      granted = await beforeTextEdit(runtimeNode, false) === true
    } catch {
      granted = false
    }
  }
  if (
    !granted
    || generation !== outlineLeaseGeneration
    || !isOutlineEdit.value
    || isReadonly.value
  ) {
    if (pendingOutlineLeaseUid === data.uid) pendingOutlineLeaseUid = ''
    if (granted) releaseOutlineLease(data.uid, runtimeNode)
    outlineRefreshGate.flush()
    return
  }
  const currentRuntimeNode = findRuntimeNode(data.uid)
  if (!currentRuntimeNode || !target?.isConnected) {
    pendingOutlineLeaseUid = ''
    releaseOutlineLease(data.uid, runtimeNode)
    recoverFromStaleOutline('该节点已发生变化，大纲已重新加载')
    return
  }
  // 等待租约时若已发生远端渲染，旧大纲 DOM 可能以过期标题开始
  // 编辑。此时归还刚获得的租约并刷新，由用户在新快照上重试。
  if (outlineRefreshGate.pending) {
    pendingOutlineLeaseUid = ''
    releaseOutlineLease(data.uid, currentRuntimeNode)
    outlineRefreshGate.flush()
    return
  }
  pendingOutlineLeaseUid = ''
  activeOutlineLeaseUid = data.uid
  activeOutlineEditTarget = target
  activeOutlineEditData = data
  props.mindMap?.emit?.('node_text_edit_start', currentRuntimeNode)
  await nextTick()
  if (
    generation === outlineLeaseGeneration
    && activeOutlineLeaseUid === data.uid
    && isOutlineEdit.value
    && !isReadonly.value
    && target.isConnected
  ) {
    target.focus({ preventScroll: true })
  } else if (activeOutlineLeaseUid === data.uid) {
    activeOutlineLeaseUid = ''
    activeOutlineEditTarget = null
    activeOutlineEditData = null
    releaseOutlineLease(data.uid, currentRuntimeNode)
    outlineRefreshGate.flush()
  }
}

function releaseDetachedOutlineLease() {
  if (!activeOutlineLeaseUid) return
  const nodeUid = activeOutlineLeaseUid
  activeOutlineLeaseUid = ''
  activeOutlineEditTarget = null
  activeOutlineEditData = null
  const runtimeNode = findRuntimeNode(nodeUid)
  releaseOutlineLease(nodeUid, runtimeNode)
  outlineRefreshGate.flush()
}

// Edit.vue 在应用远端树前同步采集所有仍停留在 DOM 的输入。大纲文本不在
// simple-mind-map 的 TextEdit 实例中，必须显式暴露同形的关闭入口，才能在
// 协作者删除当前节点时先写入临时运行时树并生成独立冲突草稿。
function getActiveTextEditor() {
  const nodeUid = activeOutlineLeaseUid
  const target = activeOutlineEditTarget
  const data = activeOutlineEditData
  if (!nodeUid || !target || !data) return null
  return {
    nodeUid,
    getEditText: () => target.textContent || '',
    richText: false,
    hideEditTextBox() {
      if (activeOutlineLeaseUid !== nodeUid) return false
      target.blur?.()
      // 浏览器通常同步派发 blur；测试环境、已脱离 DOM 的元素或异常插件
      // 可能不会。直接走同一提交函数兜底，且 UID 门闩避免重复释放。
      if (activeOutlineLeaseUid === nodeUid) {
        onNodeBlur({ currentTarget: target }, data)
      }
      return activeOutlineLeaseUid !== nodeUid
    },
  }
}

function releaseOutlineLease(nodeUid, runtimeNode = findRuntimeNode(nodeUid)) {
  if (runtimeNode) {
    props.mindMap?.emit?.('node_text_edit_end', runtimeNode)
    return
  }
  props.mindMap?.opt?.releaseNodeTextEditLease?.(nodeUid)
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
  try {
    props.mindMap.execCommand('SET_NODE_TEXT', runtimeNode, nextLabel, false, true)
  } finally {
    // blur 的 finally 会紧接着释放节点租约；先同步提交 Command 的节流
    // 历史，保证最终标题已触发 data_change_detail/Yjs update。
    props.mindMap.command?.flushPendingHistory?.()
  }
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
  outlineRefreshGate.clear()
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

watch(() => props.mindMap, (mindMap) => {
  if (!isOutlineEdit.value) return
  bindRenderEvents(mindMap)
  outlineRefreshGate.request()
})

onMounted(() => {
  bus.on('openOutlineEdit', openOutlineEdit)
  bus.on('closeOutlineEdit', close)
})

onBeforeUnmount(() => {
  outlineLeaseGeneration += 1
  pendingOutlineLeaseUid = ''
  blurActiveOutlineEditor()
  releaseDetachedOutlineLease()
  outlineRefreshGate.clear()
  unbindRenderEvents()
  bus.off('openOutlineEdit', openOutlineEdit)
  bus.off('closeOutlineEdit', close)
  if (containerRef.value?.parentNode === document.body) {
    document.body.removeChild(containerRef.value)
  }
})

defineExpose({ getActiveTextEditor })
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
