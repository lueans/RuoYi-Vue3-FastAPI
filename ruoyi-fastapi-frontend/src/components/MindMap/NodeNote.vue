<template>
  <el-dialog
    v-model="dialogVisible"
    :title="dialogTitle"
    width="min(760px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    append-to-body
    @open="onOpen"
    @close="onClose"
  >
    <div class="noteEditor" :class="{ isDark: isDark }">
      <div class="noteEditorMeta">
        <span>{{ targetSummary }}</span>
        <span>支持基础 CommonMark，原始 HTML 将作为文本显示</span>
      </div>
      <el-alert
        v-if="targetCount > 1"
        :title="batchImpactMessage"
        :type="hasMixedNotes ? 'warning' : 'info'"
        :closable="false"
        show-icon
        class="batchImpact"
      />
      <el-tabs v-model="activeTab" class="noteEditorTabs">
        <el-tab-pane label="编辑" name="edit">
          <el-input
            v-model="note"
            type="textarea"
            :rows="14"
            :maxlength="MINDMAP_NOTE_MAX_LENGTH"
            show-word-limit
            placeholder="请输入备注内容（支持 Markdown 格式）"
            ref="textareaRef"
            @keydown.ctrl.enter.prevent="confirm"
            @keydown.meta.enter.prevent="confirm"
          />
        </el-tab-pane>
        <el-tab-pane label="预览" name="preview">
          <div class="notePreview" aria-live="polite">
            <div v-if="isRendering" class="notePreviewState" role="status">正在生成预览…</div>
            <div v-else-if="previewError" class="notePreviewState isError" role="alert">
              {{ previewError }}
            </div>
            <div
              v-else-if="renderedPreview"
              class="mindmapMarkdownBody"
              :class="{ 'is-dark': isDark }"
              v-html="renderedPreview"
            ></div>
            <div v-else class="notePreviewState">输入内容后可在这里预览</div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
    <template #footer>
      <div class="noteEditorFooter">
        <span class="shortcutHint">Ctrl / ⌘ + Enter 保存</span>
        <div>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button v-if="hasExistingNote" type="danger" text :disabled="isReadonly" @click="removeNote">移除备注</el-button>
          <el-button type="primary" :disabled="isReadonly" @click="confirm">保存备注</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import bus from './useEventBus'
import { store } from './useStore'
import {
  MINDMAP_NOTE_MAX_LENGTH,
  renderMindmapMarkdown,
} from '@/utils/mindmap-markdown'
import { captureMindmapEditTargets } from '@/utils/mindmap-edit-targets'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const dialogVisible = ref(false)
const note = ref('')
const { activeNodes } = useMindMapActiveNodes({
  onMindMapChange: invalidateNoteDialogForMindMapChange,
})
const editTargets = shallowRef([])
const textareaRef = ref(null)
const activeTab = ref('edit')
const renderedPreview = ref('')
const previewError = ref('')
const isRendering = ref(false)
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => props.readonly || store.isReadonly)
const targetCount = computed(() => editTargets.value.length)
const dialogTitle = computed(() => targetCount.value > 1
  ? `批量编辑备注（${targetCount.value} 个节点）`
  : '编辑备注')
const targetSummary = computed(() => targetCount.value > 1
  ? `正在编辑打开弹窗时选中的 ${targetCount.value} 个节点`
  : '为当前节点添加说明、结论或参考资料')
const hasExistingNote = computed(() => editTargets.value.some(node => Boolean(node.getData('note'))))
const hasMixedNotes = computed(() => {
  const [firstNode, ...otherNodes] = editTargets.value
  if (!firstNode) return false
  const firstNote = String(firstNode.getData('note') || '')
  return otherNodes.some(node => String(node.getData('note') || '') !== firstNote)
})
const batchImpactMessage = computed(() => hasMixedNotes.value
  ? `这些节点的备注内容不同，保存后会用当前内容覆盖全部 ${targetCount.value} 个节点`
  : `保存后会把同一备注应用到全部 ${targetCount.value} 个节点`)
let previewTimer = null
let previewRequestId = 0

function handleShow(targetNode = null) {
  if (isReadonly.value) return
  editTargets.value = captureMindmapEditTargets(activeNodes.value, targetNode)
  const firstNode = editTargets.value[0]
  if (!firstNode) return
  note.value = String(firstNode.getData('note') || '').slice(0, MINDMAP_NOTE_MAX_LENGTH)
  activeTab.value = 'edit'
  renderedPreview.value = ''
  previewError.value = ''
  dialogVisible.value = true
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => textareaRef.value?.focus())
}

function onClose() {
  cancelPreview()
  editTargets.value = []
  bus.emit('endTextEdit')
}

function confirm() {
  if (isReadonly.value || editTargets.value.length === 0) return
  const nextNote = String(note.value ?? '').slice(0, MINDMAP_NOTE_MAX_LENGTH)
  editTargets.value.forEach(node => {
    node.setNote(nextNote)
  })
  dialogVisible.value = false
}

function removeNote() {
  if (isReadonly.value || editTargets.value.length === 0) return
  editTargets.value.forEach(node => {
    node.setNote('')
  })
  dialogVisible.value = false
}

function cancelPreview() {
  clearTimeout(previewTimer)
  previewTimer = null
  previewRequestId += 1
  isRendering.value = false
  previewError.value = ''
}

function schedulePreview() {
  clearTimeout(previewTimer)
  previewTimer = null
  const requestId = ++previewRequestId
  previewError.value = ''
  if (activeTab.value !== 'preview') {
    isRendering.value = false
    return
  }
  if (!note.value) {
    renderedPreview.value = ''
    isRendering.value = false
    return
  }
  isRendering.value = true
  const previewSource = String(note.value)
  previewTimer = setTimeout(async () => {
    previewTimer = null
    const isCurrentPreview = () => requestId === previewRequestId
      && dialogVisible.value
      && activeTab.value === 'preview'
    try {
      const html = await renderMindmapMarkdown(previewSource)
      if (!isCurrentPreview()) return
      renderedPreview.value = html
    } catch {
      if (!isCurrentPreview()) return
      renderedPreview.value = ''
      previewError.value = '备注预览生成失败，请稍后重试'
    } finally {
      if (isCurrentPreview()) isRendering.value = false
    }
  }, 120)
}

function invalidateNoteDialogForMindMapChange() {
  cancelPreview()
  editTargets.value = []
  if (dialogVisible.value) dialogVisible.value = false
}

watch([note, activeTab], schedulePreview)
watch(isReadonly, (readonly) => {
  if (readonly && dialogVisible.value) dialogVisible.value = false
})

onMounted(() => {
  bus.on('showNodeNote', handleShow)
})
onBeforeUnmount(() => {
  cancelPreview()
  if (dialogVisible.value) bus.emit('endTextEdit')
  bus.off('showNodeNote', handleShow)
})
</script>

<style lang="scss" scoped>
.noteEditor {
  .noteEditorMeta {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 4px;
    color: #909399;
    font-size: 12px;

    span:first-child {
      color: #606266;
      font-weight: 500;
    }
  }

  .noteEditorTabs {
    :deep(.el-tabs__header) {
      margin-bottom: 12px;
    }
  }

  .batchImpact {
    margin: 10px 0 4px;
  }

  .notePreview {
    min-height: 326px;
    max-height: min(52vh, 440px);
    overflow: auto;
    padding: 16px 18px;
    border: 1px solid #dcdfe6;
    border-radius: 8px;
    background: #fff;
  }

  .notePreviewState {
    display: grid;
    min-height: 290px;
    place-items: center;
    color: #a8abb2;
    font-size: 13px;

    &.isError {
      color: #f56c6c;
    }
  }

  &.isDark {
    .noteEditorMeta span:first-child {
      color: rgba(255, 255, 255, 0.72);
    }

    .notePreview {
      border-color: rgba(255, 255, 255, 0.12);
      background: #26282d;
    }
  }
}

.noteEditorFooter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;

  .shortcutHint {
    color: #a8abb2;
    font-size: 12px;
  }
}

@media (max-width: 600px) {
  .noteEditor {
    .noteEditorMeta {
      flex-direction: column;
      gap: 4px;
    }

    .notePreview {
      min-height: 280px;
    }
  }

  .noteEditorFooter {
    align-items: flex-end;

    .shortcutHint {
      display: none;
    }
  }
}
</style>
