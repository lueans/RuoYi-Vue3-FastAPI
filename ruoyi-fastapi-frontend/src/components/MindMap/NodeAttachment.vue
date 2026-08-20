<template>
  <el-dialog
    v-model="dialogVisible"
    :title="dialogTitle"
    width="min(520px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    append-to-body
    @open="onOpen"
    @close="onClose"
  >
    <el-alert
      v-if="targetCount > 1"
      :title="`保存后将把同一附件应用到打开弹窗时选中的 ${targetCount} 个节点`"
      type="info"
      :closable="false"
      show-icon
      class="batchImpact"
    />
    <el-form label-width="78px">
      <el-form-item label="附件地址" required>
        <el-input
          ref="urlInputRef"
          v-model="attachmentUrl"
          maxlength="4096"
          :disabled="isReadonly"
          placeholder="https://example.com/document.pdf"
          @keydown.stop
        />
      </el-form-item>
      <el-form-item label="附件名称">
        <el-input
          v-model="attachmentName"
          maxlength="200"
          :disabled="isReadonly"
          placeholder="留空时根据地址自动生成"
          @keydown.stop
        />
      </el-form-item>
    </el-form>
    <p class="attachment-help">
      支持 HTTP、HTTPS、同源相对路径，以及兼容旧数据的安全 Data URL。
    </p>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button v-if="hasAttachment" type="danger" text :disabled="isReadonly" @click="removeAttachment">移除附件</el-button>
      <el-button type="primary" :disabled="isReadonly" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import bus from './useEventBus'
import { store } from './useStore'
import {
  inferMindMapAttachmentName,
  normalizeMindMapAttachmentUrl,
} from '@mind-map/src/utils/attachment'
import { captureMindmapEditTargets } from '@/utils/mindmap-edit-targets'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const dialogVisible = ref(false)
const attachmentUrl = ref('')
const attachmentName = ref('')
const { activeNodes } = useMindMapActiveNodes({
  onMindMapChange: invalidateAttachmentDialogForMindMapChange,
})
const editTargets = shallowRef([])
const urlInputRef = ref(null)
const isReadonly = computed(() => props.readonly || store.isReadonly)
const targetCount = computed(() => editTargets.value.length)
const dialogTitle = computed(() => targetCount.value > 1
  ? `批量设置附件（${targetCount.value} 个节点）`
  : '附件')
const hasAttachment = computed(() => editTargets.value.some(node => Boolean(node.getData('attachmentUrl'))))

function handleShow(targetNode = null) {
  if (isReadonly.value) return
  editTargets.value = captureMindmapEditTargets(activeNodes.value, targetNode)
  const node = editTargets.value[0]
  if (!node) return
  attachmentUrl.value = node.getData('attachmentUrl') || ''
  attachmentName.value = node.getData('attachmentName') || ''
  dialogVisible.value = true
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => urlInputRef.value?.focus())
}

function onClose() {
  bus.emit('endTextEdit')
  editTargets.value = []
}

function confirm() {
  if (isReadonly.value || editTargets.value.length === 0) return
  let url
  try {
    url = normalizeMindMapAttachmentUrl(attachmentUrl.value)
  } catch (error) {
    ElMessage.error(error?.message || '附件地址无效')
    return
  }
  if (!url) {
    ElMessage.warning('请输入附件地址')
    return
  }
  const name = attachmentName.value.trim() || inferMindMapAttachmentName(url)
  editTargets.value.forEach(node => node.setAttachment(url, name))
  dialogVisible.value = false
}

function removeAttachment() {
  if (isReadonly.value || editTargets.value.length === 0) return
  editTargets.value.forEach(node => node.setAttachment('', ''))
  dialogVisible.value = false
}

function openAttachment(node, event, _attachmentElement, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, store.mindMap)) return
  if (node?.mindMap && node.mindMap !== store.mindMap) return
  event?.stopPropagation?.()
  let url
  try {
    url = normalizeMindMapAttachmentUrl(node?.getData?.('attachmentUrl'))
  } catch (error) {
    ElMessage.error(error?.message || '附件地址无效，无法打开')
    return
  }
  if (!url) return
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.target = '_blank'
  anchor.rel = 'noopener noreferrer'
  anchor.referrerPolicy = 'no-referrer'
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

function editAttachmentFromContextMenu(node, event, _attachmentElement, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, store.mindMap)) return
  if (node?.mindMap && node.mindMap !== store.mindMap) return
  if (isReadonly.value) return
  event?.preventDefault?.()
  event?.stopPropagation?.()
  handleShow(node)
}

function invalidateAttachmentDialogForMindMapChange() {
  editTargets.value = []
  if (dialogVisible.value) dialogVisible.value = false
}

watch(isReadonly, (readonly) => {
  if (readonly && dialogVisible.value) dialogVisible.value = false
})

onMounted(() => {
  bus.on('showNodeAttachment', handleShow)
  bus.on('node_attachmentClick', openAttachment)
  bus.on('node_attachmentContextmenu', editAttachmentFromContextMenu)
})

onBeforeUnmount(() => {
  if (dialogVisible.value) bus.emit('endTextEdit')
  bus.off('showNodeAttachment', handleShow)
  bus.off('node_attachmentClick', openAttachment)
  bus.off('node_attachmentContextmenu', editAttachmentFromContextMenu)
})
</script>

<style scoped>
.attachment-help {
  margin: 4px 0 0 78px;
  color: #8f959e;
  font-size: 12px;
  line-height: 1.6;
}
.batchImpact {
  margin-bottom: 12px;
}
</style>
