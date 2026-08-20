<template>
  <el-dialog
    v-model="dialogVisible"
    :title="dialogTitle"
    width="min(500px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    append-to-body
    @open="onOpen"
    @close="onClose"
  >
    <el-alert
      v-if="targetCount > 1"
      :title="`保存后将把同一超链接应用到打开弹窗时选中的 ${targetCount} 个节点`"
      type="info"
      :closable="false"
      show-icon
      class="batchImpact"
    />
    <el-form label-width="70px">
      <el-form-item label="链接地址">
        <el-input ref="linkInputRef" v-model="link" maxlength="4096" :disabled="isReadonly" placeholder="请输入链接地址">
          <template #prepend>
            <el-select v-model="protocol" :disabled="isReadonly" aria-label="链接协议" style="width:112px">
              <el-option label="https://" value="https://" />
              <el-option label="http://" value="http://" />
              <el-option label="mailto:" value="mailto:" />
              <el-option label="tel:" value="tel:" />
              <el-option label="相对路径" value="" />
            </el-select>
          </template>
        </el-input>
      </el-form-item>
      <el-form-item label="链接名称">
        <el-input v-model="linkTitle" maxlength="200" :disabled="isReadonly" placeholder="可选，链接显示名称" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button v-if="hasExistingLink" type="danger" text :disabled="isReadonly" @click="removeLink">移除链接</el-button>
      <el-button type="primary" :disabled="isReadonly" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import bus from './useEventBus'
import { store } from './useStore'
import { normalizeMindMapHyperlink } from '@mind-map/src/utils/hyperlink'
import { captureMindmapEditTargets } from '@/utils/mindmap-edit-targets'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const dialogVisible = ref(false)
const link = ref('')
const linkTitle = ref('')
const protocol = ref('https://')
const { activeNodes } = useMindMapActiveNodes({
  onMindMapChange: invalidateHyperlinkDialogForMindMapChange,
})
const editTargets = shallowRef([])
const linkInputRef = ref(null)
const isReadonly = computed(() => props.readonly || store.isReadonly)
const targetCount = computed(() => editTargets.value.length)
const dialogTitle = computed(() => targetCount.value > 1
  ? `批量设置超链接（${targetCount.value} 个节点）`
  : '超链接')
const hasExistingLink = computed(() => editTargets.value.some(node => Boolean(node.getData('hyperlink'))))

function handleShow() {
  if (isReadonly.value) return
  editTargets.value = captureMindmapEditTargets(activeNodes.value)
  const node = editTargets.value[0]
  if (!node) return
  const href = node.getData('hyperlink') || ''
  linkTitle.value = node.getData('hyperlinkTitle') || ''
  if (!href) {
    protocol.value = 'https://'
    link.value = ''
  } else if (href.startsWith('https://')) {
    protocol.value = 'https://'
    link.value = href.replace('https://', '')
  } else if (href.startsWith('http://')) {
    protocol.value = 'http://'
    link.value = href.replace('http://', '')
  } else if (href.startsWith('mailto:')) {
    protocol.value = 'mailto:'
    link.value = href.slice('mailto:'.length)
  } else if (href.startsWith('tel:')) {
    protocol.value = 'tel:'
    link.value = href.slice('tel:'.length)
  } else {
    protocol.value = ''
    link.value = href
  }
  dialogVisible.value = true
}

function onClose() {
  editTargets.value = []
  bus.emit('endTextEdit')
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => linkInputRef.value?.focus())
}

function confirm() {
  if (isReadonly.value || editTargets.value.length === 0) return
  const rawLink = link.value.trim()
  const input = /^(?:https?:\/\/|mailto:|tel:)/i.test(rawLink)
    ? rawLink
    : protocol.value + rawLink
  let url
  try {
    url = normalizeMindMapHyperlink(input)
  } catch (error) {
    ElMessage.error(error?.message || '链接地址无效')
    return
  }
  editTargets.value.forEach(node => {
    node.setHyperlink(url, linkTitle.value.trim())
  })
  dialogVisible.value = false
}

function removeLink() {
  if (isReadonly.value || editTargets.value.length === 0) return
  editTargets.value.forEach(node => {
    node.setHyperlink('', '')
  })
  dialogVisible.value = false
}

function invalidateHyperlinkDialogForMindMapChange() {
  editTargets.value = []
  if (dialogVisible.value) dialogVisible.value = false
}

watch(isReadonly, (readonly) => {
  if (readonly && dialogVisible.value) dialogVisible.value = false
})

onMounted(() => {
  bus.on('showNodeLink', handleShow)
})
onBeforeUnmount(() => {
  if (dialogVisible.value) bus.emit('endTextEdit')
  bus.off('showNodeLink', handleShow)
})
</script>

<style scoped>
.batchImpact {
  margin-bottom: 12px;
}
</style>
