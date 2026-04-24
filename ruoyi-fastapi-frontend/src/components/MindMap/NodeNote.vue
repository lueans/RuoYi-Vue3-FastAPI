<template>
  <el-dialog v-model="dialogVisible" title="备注" width="600px" :close-on-click-modal="false"
    @open="onOpen" @close="onClose">
    <el-input
      v-model="note"
      type="textarea"
      :rows="12"
      placeholder="请输入备注内容（支持 Markdown 格式）"
      ref="textareaRef"
    />
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button v-if="note" type="danger" text @click="removeNote">移除备注</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import bus from './useEventBus'

const dialogVisible = ref(false)
const note = ref('')
const activeNodes = ref([])
const appointNode = ref(null)
const textareaRef = ref(null)

function handleShow(targetNode) {
  if (targetNode) {
    appointNode.value = targetNode
    note.value = targetNode.getData('note') || ''
  } else {
    appointNode.value = null
    const node = activeNodes.value[0]
    if (!node) return
    note.value = node.getData('note') || ''
  }
  dialogVisible.value = true
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => textareaRef.value?.focus())
}

function onClose() {
  bus.emit('endTextEdit')
}

function confirm() {
  const targets = appointNode.value ? [appointNode.value] : activeNodes.value
  targets.forEach(node => {
    node.setNote(note.value)
  })
  dialogVisible.value = false
}

function removeNote() {
  const targets = appointNode.value ? [appointNode.value] : activeNodes.value
  targets.forEach(node => {
    node.setNote('')
  })
  dialogVisible.value = false
}

function onNodeActive(_, list) {
  activeNodes.value = list ? [...list] : []
}

onMounted(() => {
  bus.on('node_active', onNodeActive)
  bus.on('showNodeNote', handleShow)
})
onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
  bus.off('showNodeNote', handleShow)
})
</script>
