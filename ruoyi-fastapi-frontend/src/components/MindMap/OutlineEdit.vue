<template>
  <Teleport to="body">
  <div
    class="outlineEditContainer"
    :class="{ isDark: isDark }"
    v-if="isOutlineEdit"
    ref="containerRef"
    role="dialog"
    aria-modal="true"
    aria-label="大纲编辑"
    @keydown.esc.stop.prevent="close"
  >
    <div class="header">
      <span class="keyboardHint">Enter 同级 · Tab 子节点 · Alt+↑↓ 切换节点 · Shift+Tab 返回关闭按钮 · Esc 关闭</span>
      <el-button ref="closeButtonRef" size="small" @click="close">关闭大纲编辑</el-button>
    </div>
    <div class="treeWrap customScrollbar">
      <OutlineVirtualTree
        ref="virtualTreeRef"
        :data="treeData"
        :pinned-uid="editingRowUid"
        :draggable="!isReadonly"
        :allow-drag="allowDrag"
        :allow-drop="allowDrop"
        @node-drop="onNodeDrop"
      >
        <template #default="{ node, data }">
          <span
            class="nodeEdit"
            :contenteditable="!isReadonly"
            :aria-label="`编辑节点：${data.label || '空节点'}`"
            role="textbox"
            aria-multiline="true"
            :title="data.label"
            @focus="onNodeFocus($event, data)"
            @blur="onNodeBlur($event, data)"
            @keydown="onNodeKeydown($event, node, data)"
            @paste.prevent="onNodePaste($event)"
            v-text="data.label"
          ></span>
        </template>
      </OutlineVirtualTree>
    </div>
  </div>
  </Teleport>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import bus from './useEventBus'
import { store } from './useStore'
import { createUid } from '@mind-map/src/utils'
import OutlineVirtualTree from './OutlineVirtualTree.vue'
import {
  createNewOutlineNode,
  createOutlineRefreshGate,
  createOutlineTreeNode,
  ensureOutlineRuntimeNodes,
  clearOutlineRuntimeExpansion,
} from '@/utils/mindmap-outline-edit'
import { insertMindmapPlainTextAtSelection } from '@/utils/mindmap-dom-edit'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const isOutlineEdit = ref(false)
const treeData = shallowRef([])
const containerRef = ref(null)
const virtualTreeRef = ref(null)
const closeButtonRef = ref(null)
const editingRowUid = ref('')
let focusReturnTarget = null
let pendingFocusUid = ''
let focusRequestGeneration = 0
let selectOnLeaseUid = ''
let pendingOutlineLeaseUid = ''
let activeOutlineLeaseUid = ''
let pendingOutlineLeaseMindMap = null
let activeOutlineLeaseMindMap = null
let activeOutlineEditTarget = null
let activeOutlineEditData = null
let outlineLeaseGeneration = 0
let renderEventMindMap = null
let outlineSessionMindMap = null
let outlineDropGeneration = 0

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
  nextTick(tryFocusPendingNode)
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
  focusReturnTarget = document.activeElement
  outlineSessionMindMap = props.mindMap
  isOutlineEdit.value = true
  outlineRefreshGate.clear()
  bindRenderEvents()
  refresh()
  nextTick(focusCloseButton)
}

function close() {
  outlineDropGeneration += 1
  pendingFocusUid = ''
  selectOnLeaseUid = ''
  focusRequestGeneration += 1
  cancelPendingOutlineLease()
  blurActiveOutlineEditor()
  releaseDetachedOutlineLease()
  isOutlineEdit.value = false
  clearOutlineRuntimeExpansion(outlineSessionMindMap)
  outlineSessionMindMap = null
  outlineRefreshGate.clear()
  unbindRenderEvents()
  const returnTarget = focusReturnTarget
  focusReturnTarget = null
  nextTick(() => {
    const visibleOpener = returnTarget?.isConnected
      && returnTarget !== document.body
      && returnTarget.getClientRects?.().length > 0
      && window.getComputedStyle(returnTarget).visibility !== 'hidden'
    if (visibleOpener) {
      returnTarget.focus?.({ preventScroll: true })
    }
    // A still-mounted opener can sit in a hidden sidebar. Even a visible
    // element may no longer accept focus, so verify the actual outcome.
    if (!visibleOpener || document.activeElement !== returnTarget) {
      const canvas = props.mindMap?.el
      if (canvas?.isConnected) {
        if (!canvas.hasAttribute('tabindex')) canvas.setAttribute('tabindex', '-1')
        canvas.focus?.({ preventScroll: true })
      }
    }
  })
}

function focusCloseButton() {
  const button = closeButtonRef.value?.$el || closeButtonRef.value
  button?.focus?.({ preventScroll: true })
}

function selectEditorText(target) {
  const selection = window.getSelection()
  if (!selection || !target?.isConnected) return
  const range = document.createRange()
  range.selectNodeContents(target)
  selection.removeAllRanges()
  selection.addRange(range)
}

function queueNodeFocus(uid) {
  pendingFocusUid = uid
  selectOnLeaseUid = uid
  // Commit/release the old row before acquiring the newly inserted node.
  blurActiveOutlineEditor()
  nextTick(tryFocusPendingNode)
}

async function tryFocusPendingNode() {
  const uid = pendingFocusUid
  const mindMap = props.mindMap
  if (!uid || !isOutlineEdit.value) return
  const generation = ++focusRequestGeneration
  const isCurrent = () => generation === focusRequestGeneration
    && uid === pendingFocusUid && isOutlineEdit.value && !isReadonly.value
    && mindMap === props.mindMap && mindMap === outlineSessionMindMap
  try {
    const nodes = await ensureOutlineRuntimeNodes(mindMap, [uid], isCurrent)
    if (!isCurrent()) return
    if (!nodes) {
      pendingFocusUid = ''
      selectOnLeaseUid = ''
      recoverFromStaleOutline('该节点已删除或不在当前筛选范围，请重新选择')
      return
    }
  } catch (error) {
    if (isCurrent()) {
      pendingFocusUid = ''
      selectOnLeaseUid = ''
      ElMessage.warning(error?.message || '大纲节点准备失败，请重试')
    }
    return
  }
  if (!isCurrent()) return
  await nextTick()
  const target = await virtualTreeRef.value?.reveal(uid)
  if (!isCurrent() || !target?.isConnected) return
  pendingFocusUid = ''
  target.focus({ preventScroll: true })
}

function blurActiveOutlineEditor() {
  const activeElement = document.activeElement
  if (activeElement && containerRef.value?.contains(activeElement)) {
    activeElement.blur()
  }
}

function refresh() {
  if (!props.mindMap) return
  // Only our shallow editor records are copied. Serializing a second full
  // document snapshot here is unnecessary for every remote render.
  const data = props.mindMap.renderer?.renderTree || props.mindMap.getData()
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
    const owner = activeOutlineLeaseMindMap || props.mindMap
    const runtimeNode = owner?.renderer?.findNodeByUid?.(data.uid)
    if (activeOutlineLeaseUid === data.uid) {
      activeOutlineLeaseUid = ''
      editingRowUid.value = ''
      activeOutlineEditTarget = null
      activeOutlineEditData = null
      activeOutlineLeaseMindMap = null
      releaseOutlineLease(data.uid, runtimeNode, owner)
    }
    outlineRefreshGate.flush()
  }
}

function cancelPendingOutlineLease() {
  if (!pendingOutlineLeaseUid) return false
  const nodeUid = pendingOutlineLeaseUid
  const owner = pendingOutlineLeaseMindMap || props.mindMap
  pendingOutlineLeaseUid = ''
  pendingOutlineLeaseMindMap = null
  editingRowUid.value = ''
  outlineLeaseGeneration += 1
  owner?.opt?.releaseNodeTextEditLease?.(nodeUid)
  outlineRefreshGate.flush()
  return true
}

async function onNodeFocus(e, data) {
  if (isReadonly.value) return
  const leaseMindMap = props.mindMap
  if (
    activeOutlineLeaseUid === data.uid
    || pendingOutlineLeaseUid === data.uid
  ) return
  if (pendingOutlineLeaseUid) cancelPendingOutlineLease()
  // 同一浏览器只声明一个节点文本占用；从画布切到大纲前先安全提交画布
  // 浮层，再重新获取可能因渲染而替换的运行时节点实例。
  props.mindMap?.renderer?.textEdit?.hideEditTextBox?.()
  const runtimeNode = findRuntimeNode(data.uid)
  if (!runtimeNode) {
    e.currentTarget?.blur?.()
    // 先让临时展开和大纲刷新完成，再从新的 DOM 进入原有的获锁流程。
    // 准备实例期间不持有租约，也不允许隐藏节点的旧 DOM 接收输入。
    queueNodeFocus(data.uid)
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
  pendingOutlineLeaseMindMap = leaseMindMap
  editingRowUid.value = data.uid
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
  const requestStillCurrent = Boolean(
    generation === outlineLeaseGeneration
    && isOutlineEdit.value
    && !isReadonly.value
    && leaseMindMap === props.mindMap
    && leaseMindMap === outlineSessionMindMap
  )
  if (!granted || !requestStillCurrent) {
    if (!granted && requestStillCurrent && usesAuthoritativeLease) {
      props.mindMap?.emit?.(
        'node_text_edit_blocked',
        runtimeNode,
        [...(runtimeNode.editingUserList || [])],
        props.mindMap?.opt?.getNodeTextEditLeaseFailureReason?.()
          || 'unavailable',
      )
    }
    if (pendingOutlineLeaseUid === data.uid && generation === outlineLeaseGeneration) {
      pendingOutlineLeaseUid = ''
      pendingOutlineLeaseMindMap = null
      editingRowUid.value = ''
    }
    if (granted) releaseOutlineLease(data.uid, runtimeNode)
    outlineRefreshGate.flush()
    return
  }
  const currentRuntimeNode = findRuntimeNode(data.uid)
  if (!currentRuntimeNode || !target?.isConnected) {
    pendingOutlineLeaseUid = ''
    pendingOutlineLeaseMindMap = null
    editingRowUid.value = ''
    releaseOutlineLease(data.uid, runtimeNode)
    recoverFromStaleOutline('该节点已发生变化，大纲已重新加载')
    return
  }
  // 等待租约时若已发生远端渲染，旧大纲 DOM 可能以过期标题开始
  // 编辑。此时归还刚获得的租约并刷新，由用户在新快照上重试。
  if (outlineRefreshGate.pending) {
    pendingOutlineLeaseUid = ''
    pendingOutlineLeaseMindMap = null
    editingRowUid.value = ''
    if (selectOnLeaseUid === data.uid) pendingFocusUid = data.uid
    releaseOutlineLease(data.uid, currentRuntimeNode)
    outlineRefreshGate.flush()
    nextTick(tryFocusPendingNode)
    return
  }
  pendingOutlineLeaseUid = ''
  pendingOutlineLeaseMindMap = null
  activeOutlineLeaseUid = data.uid
  activeOutlineLeaseMindMap = leaseMindMap
  activeOutlineEditTarget = target
  activeOutlineEditData = data
  props.mindMap?.emit?.('node_text_edit_start', currentRuntimeNode)
  await nextTick()
  if (generation !== outlineLeaseGeneration) return
  if (
    generation === outlineLeaseGeneration
    && activeOutlineLeaseUid === data.uid
    && isOutlineEdit.value
    && !isReadonly.value
    && leaseMindMap === props.mindMap
    && leaseMindMap === outlineSessionMindMap
    && target.isConnected
  ) {
    target.focus({ preventScroll: true })
    if (selectOnLeaseUid === data.uid) {
      selectOnLeaseUid = ''
      selectEditorText(target)
    }
  } else if (activeOutlineLeaseUid === data.uid) {
    activeOutlineLeaseUid = ''
    editingRowUid.value = ''
    activeOutlineEditTarget = null
    activeOutlineEditData = null
    activeOutlineLeaseMindMap = null
    releaseOutlineLease(data.uid, currentRuntimeNode)
    outlineRefreshGate.flush()
  }
}

function releaseDetachedOutlineLease() {
  if (!activeOutlineLeaseUid) return
  const nodeUid = activeOutlineLeaseUid
  const owner = activeOutlineLeaseMindMap || props.mindMap
  activeOutlineLeaseUid = ''
  activeOutlineLeaseMindMap = null
  editingRowUid.value = ''
  activeOutlineEditTarget = null
  activeOutlineEditData = null
  const runtimeNode = owner?.renderer?.findNodeByUid?.(nodeUid)
  releaseOutlineLease(nodeUid, runtimeNode, owner)
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
      if (activeOutlineLeaseUid !== nodeUid || activeOutlineEditTarget !== target) return false
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

function releaseOutlineLease(nodeUid, runtimeNode = findRuntimeNode(nodeUid), owner = null) {
  const mindMap = runtimeNode?.mindMap || owner || props.mindMap
  if (runtimeNode) {
    mindMap?.emit?.('node_text_edit_end', runtimeNode)
    return
  }
  mindMap?.opt?.releaseNodeTextEditLease?.(nodeUid)
}

function updateNodeLabel(target, data) {
  if (isReadonly.value) return
  if (props.mindMap !== outlineSessionMindMap) return
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
  // A contenteditable's Enter/Tab must not also reach the canvas shortcuts.
  e.stopPropagation()
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
    return
  }
  if (e.key === 'Tab' && e.shiftKey) {
    e.preventDefault()
    focusCloseButton()
    return
  }
  if (e.isComposing) return
  if (isReadonly.value) return
  if (e.altKey && ['ArrowUp', 'ArrowDown'].includes(e.key)) {
    e.preventDefault()
    const uid = virtualTreeRef.value?.adjacentUid(data.uid, e.key === 'ArrowUp' ? -1 : 1)
    if (uid && uid !== data.uid) queueNodeFocus(uid)
    return
  }
  if (e.key === 'Enter' && e.shiftKey) {
    e.preventDefault()
    insertMindmapPlainTextAtSelection('\n', e.currentTarget)
    return
  }
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
      const inserted = props.mindMap.execCommand('INSERT_NODE', false, [runtimeNode], {
        ...newNode.originalData,
        richText: false,
      })
      if (inserted === false) {
        refreshOutlineFromRuntime()
        return
      }
      siblings.splice(index + 1, 0, newNode)
      treeData.value = [...treeData.value]
      queueNodeFocus(newNode.uid)
    }
  } else if (e.key === 'Tab') {
    e.preventDefault()
    updateNodeLabel(e.currentTarget, data)
    const runtimeNode = findRuntimeNode(data.uid)
    if (!runtimeNode) {
      recoverFromStaleOutline('目标节点已变化，大纲已重新加载')
      return
    }
    const newChild = createNewOutlineNode(createUid)
    const inserted = props.mindMap.execCommand('INSERT_CHILD_NODE', false, [runtimeNode], {
      ...newChild.originalData,
      richText: false,
    })
    if (inserted === false) {
      refreshOutlineFromRuntime()
      return
    }
    if (!data.children) data.children = []
    data.children.push(newChild)
    treeData.value = [...treeData.value]
    queueNodeFocus(newChild.uid)
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
  refreshOutlineFromRuntime()
}

function refreshOutlineFromRuntime() {
  outlineRefreshGate.clear()
  refresh()
}

function allowDrag(node) {
  return !isReadonly.value
    && props.mindMap?.opt?.isStructureWriteBlocked?.() !== true
    && node.level > 1
}

function allowDrop(_, dropNode, type) {
  return !isReadonly.value
    && props.mindMap?.opt?.isStructureWriteBlocked?.() !== true
    && (dropNode.level > 1 || type === 'inner')
}

async function onNodeDrop(draggingNode, dropNode, dropType) {
  if (isReadonly.value) return
  const mindMap = props.mindMap
  const generation = ++outlineDropGeneration
  const isCurrent = () => generation === outlineDropGeneration && isOutlineEdit.value
    && !isReadonly.value && mindMap === props.mindMap && mindMap === outlineSessionMindMap
  cancelPendingOutlineLease()
  blurActiveOutlineEditor()
  try {
    const nodes = await ensureOutlineRuntimeNodes(mindMap, [draggingNode.data?.uid, dropNode.data?.uid], isCurrent)
    if (!isCurrent()) return
    if (!nodes) {
      recoverFromStaleOutline('拖拽期间脑图结构已变化，大纲已重新加载')
      return
    }
  } catch (error) {
    if (isCurrent()) ElMessage.warning(error?.message || '大纲节点准备失败，请重试')
    return
  }
  const runtimeNode = findRuntimeNode(draggingNode.data?.uid)
  const targetNode = findRuntimeNode(dropNode.data?.uid)
  if (!runtimeNode || !targetNode) {
    recoverFromStaleOutline('拖拽期间脑图结构已变化，大纲已重新加载')
    return
  }
  let moved
  if (dropType === 'inner') {
    moved = props.mindMap.execCommand('MOVE_NODE_TO', runtimeNode, targetNode)
  } else if (dropType === 'before') {
    moved = props.mindMap.execCommand('INSERT_BEFORE', runtimeNode, targetNode)
  } else if (dropType === 'after') {
    moved = props.mindMap.execCommand('INSERT_AFTER', runtimeNode, targetNode)
  }
  if (moved === false) {
    refreshOutlineFromRuntime()
  } else {
    refreshOutlineFromRuntime()
    queueNodeFocus(draggingNode.data.uid)
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
  if (mindMap !== outlineSessionMindMap) {
    close()
    return
  }
  bindRenderEvents(mindMap)
  outlineRefreshGate.request()
})

onMounted(() => {
  bus.on('openOutlineEdit', openOutlineEdit)
  bus.on('closeOutlineEdit', close)
})

onBeforeUnmount(() => {
  outlineDropGeneration += 1
  focusRequestGeneration += 1
  pendingFocusUid = ''
  cancelPendingOutlineLease()
  blurActiveOutlineEditor()
  releaseDetachedOutlineLease()
  clearOutlineRuntimeExpansion(outlineSessionMindMap)
  outlineSessionMindMap = null
  outlineRefreshGate.clear()
  unbindRenderEvents()
  bus.off('openOutlineEdit', openOutlineEdit)
  bus.off('closeOutlineEdit', close)
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
  color: #303133;
  display: flex;
  flex-direction: column;

  &.isDark {
    background: #1e1e1e;
    color: #e0e0e0;
    .header { border-bottom-color: #333; }
    .nodeEdit { color: #e0e0e0; }
    .nodeEdit:focus { background: #243a52; box-shadow: 0 0 0 1px #73b4ff; }
    .keyboardHint { color: #b8bdc5; }
  }

  .header {
    padding: 12px 20px;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
  }

  .keyboardHint { margin-right: auto; color: #606266; font-size: 12px; }

  .treeWrap {
    flex: 1;
    min-height: 0;
    display: flex;
    overflow: hidden;
    padding: 12px;

    .nodeEdit {
      outline: none;
      padding: 2px 4px;
      min-width: 20px;
      flex: 1;
      height: 36px;
      box-sizing: border-box;
      line-height: 28px;
      overflow: auto;
      white-space: pre;
      border-radius: 2px;

      &:focus {
        background: #f0f7ff;
        box-shadow: 0 0 0 1px #409eff;
      }
    }
  }
}
@media (max-width: 760px) {
  .outlineEditContainer .header { padding: 10px 12px; }
  .outlineEditContainer .keyboardHint { display: none; }
  .outlineEditContainer .treeWrap { padding: 4px; }
}
</style>
