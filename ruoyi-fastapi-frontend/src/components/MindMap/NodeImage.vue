<template>
  <el-dialog
    v-model="dialogVisible"
    :title="dialogTitle"
    width="min(500px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    append-to-body
    @open="onDialogOpen"
    @close="onDialogClose"
  >
    <el-alert
      v-if="targetCount > 1"
      :title="`保存后将把图片设置应用到打开弹窗时选中的 ${targetCount} 个节点`"
      type="info"
      :closable="false"
      show-icon
      class="batchImpact"
    />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="URL 地址" name="url">
        <el-input ref="imgUrlInputRef" v-model="imgUrl" :disabled="isReadonly" placeholder="请输入图片 URL 地址" />
      </el-tab-pane>
      <el-tab-pane label="本地上传" name="upload">
        <el-upload
          drag
          :auto-upload="false"
          :show-file-list="false"
          :disabled="isReadonly"
          accept="image/*"
          :on-change="onFileChange"
        >
          <div class="upload-area">
            <img v-if="imgBase64" :src="imgBase64" class="preview-img" />
            <template v-else>
              <el-icon style="font-size:40px;color:#c0c4cc"><Plus /></el-icon>
              <div style="margin-top:8px;color:#999;font-size:13px">点击或拖拽上传图片</div>
            </template>
          </div>
        </el-upload>
      </el-tab-pane>
    </el-tabs>
    <el-form-item label="图片标题" style="margin-top:12px">
      <el-input v-model="imgTitle" :disabled="isReadonly" placeholder="可选" />
    </el-form-item>
    <template #footer>
      <el-button @click="cancel">取消</el-button>
      <el-button v-if="hasImage" type="danger" text :disabled="isReadonly || isConfirming" @click="removeImage">移除图片</el-button>
      <el-button type="primary" :loading="isConfirming" :disabled="isReadonly" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import bus from './useEventBus'
import { store } from './useStore'
import {
  loadMindmapImageDimensions,
  normalizeMindmapImageUrl,
  readMindmapImageFile,
} from '@/utils/mindmap-image'
import { captureMindmapEditTargets } from '@/utils/mindmap-edit-targets'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const dialogVisible = ref(false)
const activeTab = ref('url')
const imgUrl = ref('')
const imgBase64 = ref('')
const imgTitle = ref('')
const { activeNodes } = useMindMapActiveNodes({
  onMindMapChange: invalidateImageDialogForMindMapChange,
})
const editTargets = shallowRef([])
const imgUrlInputRef = ref(null)
const isConfirming = ref(false)
const isReadonly = computed(() => props.readonly || store.isReadonly)
const targetCount = computed(() => editTargets.value.length)
const dialogTitle = computed(() => targetCount.value > 1
  ? `批量设置图片（${targetCount.value} 个节点）`
  : '图片')
const hasImage = computed(() => editTargets.value.some(node => Boolean(node.getData('image'))))
let imageReadToken = 0
let imageOperationToken = 0

function handleShow() {
  if (isReadonly.value) return
  imageReadToken++
  imageOperationToken++
  editTargets.value = captureMindmapEditTargets(activeNodes.value)
  const node = editTargets.value[0]
  if (!node) return
  const url = node.getData('image') || ''
  imgTitle.value = node.getData('imageTitle') || ''
  if (url.startsWith('data:')) {
    imgBase64.value = url
    imgUrl.value = ''
    activeTab.value = 'upload'
  } else {
    imgUrl.value = url
    imgBase64.value = ''
    activeTab.value = 'url'
  }
  dialogVisible.value = true
}

function onDialogClose() {
  imageReadToken++
  imageOperationToken++
  isConfirming.value = false
  editTargets.value = []
  bus.emit('endTextEdit')
}

function onDialogOpen() {
  bus.emit('startTextEdit')
  if (activeTab.value === 'url') nextTick(() => imgUrlInputRef.value?.focus())
}

function cancel() {
  imageReadToken++
  imageOperationToken++
  isConfirming.value = false
  dialogVisible.value = false
}

async function onFileChange(file) {
  if (isReadonly.value) return
  const token = ++imageReadToken
  try {
    const result = await readMindmapImageFile(file?.raw)
    if (token !== imageReadToken) return
    imgBase64.value = result
  } catch (error) {
    if (token !== imageReadToken) return
    imgBase64.value = ''
    ElMessage.error(error?.message || '读取图片失败')
  }
}

async function confirm() {
  if (isReadonly.value || isConfirming.value || editTargets.value.length === 0) return
  const input = activeTab.value === 'url' ? imgUrl.value : imgBase64.value
  if (!String(input || '').trim()) {
    ElMessage.warning(activeTab.value === 'url' ? '请输入图片地址' : '请选择本地图片')
    return
  }
  let url
  try {
    url = normalizeMindmapImageUrl(input)
  } catch (error) {
    ElMessage.error(error?.message || '图片地址无效')
    return
  }

  const operationToken = ++imageOperationToken
  isConfirming.value = true
  try {
    const { width, height } = await loadMindmapImageDimensions(url)
    if (operationToken !== imageOperationToken || isReadonly.value) return
    editTargets.value.forEach(node => {
      node.setImage({ url, title: imgTitle.value.trim(), width, height })
    })
    dialogVisible.value = false
  } catch (error) {
    if (operationToken !== imageOperationToken) return
    ElMessage.error(error?.message || '图片加载失败')
  } finally {
    if (operationToken === imageOperationToken) isConfirming.value = false
  }
}

function removeImage() {
  if (isReadonly.value || editTargets.value.length === 0) return
  editTargets.value.forEach(node => {
    node.setImage(null)
  })
  dialogVisible.value = false
}

function invalidateImageDialogForMindMapChange() {
  imageReadToken += 1
  imageOperationToken += 1
  isConfirming.value = false
  editTargets.value = []
  if (dialogVisible.value) dialogVisible.value = false
}

watch(isReadonly, (readonly) => {
  if (!readonly || !dialogVisible.value) return
  imageReadToken++
  imageOperationToken++
  isConfirming.value = false
  dialogVisible.value = false
})

onMounted(() => {
  bus.on('showNodeImage', handleShow)
})
onBeforeUnmount(() => {
  imageReadToken++
  imageOperationToken++
  if (dialogVisible.value) bus.emit('endTextEdit')
  bus.off('showNodeImage', handleShow)
})
</script>

<style scoped lang="scss">
.upload-area {
  padding: 20px;
  text-align: center;
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.batchImpact {
  margin-bottom: 12px;
}
.preview-img {
  max-width: 100%;
  max-height: 200px;
  object-fit: contain;
}
</style>
