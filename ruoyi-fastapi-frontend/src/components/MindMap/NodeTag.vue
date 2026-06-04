<template>
  <el-dialog v-model="dialogVisible" title="标签" width="460px" :close-on-click-modal="false"
    @open="onOpen" @close="onClose" append-to-body>
    <div class="tag-input-row">
      <el-input v-model="tagInput" placeholder="输入标签后按 Enter 添加" size="small"
        @keydown.enter="addTag" ref="inputRef" />
      <el-button size="small" type="primary" @click="addTag" :disabled="!tagInput.trim()">添加</el-button>
    </div>
    <div class="tag-list" v-if="tagArr.length > 0">
      <el-tag v-for="(tag, index) in tagArr" :key="index" closable
        :color="getTagColor(tag)" effect="dark" @close="removeTag(index)"
        style="margin: 4px">
        {{ typeof tag === 'object' ? tag.text : tag }}
      </el-tag>
    </div>
    <div v-else class="empty-tip">暂无标签</div>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import bus from './useEventBus'

const dialogVisible = ref(false)
const tagInput = ref('')
const tagArr = ref([])
const activeNodes = ref([])
const inputRef = ref(null)

const tagColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#00bcd4', '#9c27b0', '#ff5722']

function getTagColor(tag) {
  const text = typeof tag === 'object' ? tag.text : tag
  let hash = 0
  for (let i = 0; i < text.length; i++) {
    hash = text.charCodeAt(i) + ((hash << 5) - hash)
  }
  return tagColors[Math.abs(hash) % tagColors.length]
}

function handleShow() {
  const node = activeNodes.value[0]
  if (!node) return
  const tags = node.getData('tag') || []
  tagArr.value = [...tags]
  dialogVisible.value = true
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => inputRef.value?.focus())
}

function onClose() {
  bus.emit('endTextEdit')
}

function addTag() {
  const text = tagInput.value.trim()
  if (!text) return
  if (tagArr.value.length >= 10) {
    ElMessage.warning('最多添加 10 个标签')
    return
  }
  tagArr.value.push(text)
  tagInput.value = ''
}

function removeTag(index) {
  tagArr.value.splice(index, 1)
}

function confirm() {
  activeNodes.value.forEach(node => {
    node.setTag([...tagArr.value])
  })
  dialogVisible.value = false
}

function onNodeActive(_, list) {
  activeNodes.value = list ? [...list] : []
}

onMounted(() => {
  bus.on('node_active', onNodeActive)
  bus.on('showNodeTag', handleShow)
})
onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
  bus.off('showNodeTag', handleShow)
})
</script>

<style scoped lang="scss">
.tag-input-row { display: flex; gap: 8px; margin-bottom: 12px; }
.tag-list { display: flex; flex-wrap: wrap; min-height: 40px; }
.empty-tip { text-align: center; color: #999; padding: 20px 0; }
</style>
