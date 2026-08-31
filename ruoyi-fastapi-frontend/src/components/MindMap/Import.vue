<template>
  <div>
    <input
      ref="fileInputRef"
      class="importFileInput"
      type="file"
      :accept="supportFileStr"
      :disabled="isImporting || readonly"
      @change="handleFileInputChange"
    />
    <span class="importStatus" role="status" aria-live="polite">{{ importStatusText }}</span>

    <el-dialog
      class="xmindCanvasSelectDialog"
      :class="{ isDark: isDark }"
      v-model="xmindCanvasSelectDialogVisible"
      width="480px"
      modal-class="xmindCanvasSelectOverlay"
      :show-close="false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      append-to-body
    >
      <div class="canvasSelectShell" :class="{ isDark: isDark }">
        <div class="canvasSelectContent">
          <h2 class="canvasSelectTitle">选择要导入的画布</h2>
          <p class="canvasSelectHint">此 XMind 文件包含多个画布，请选择一个继续导入。</p>
          <el-radio-group v-model="selectCanvas" class="canvasList" :disabled="readonly">
            <el-radio
              v-for="(item, index) in canvasList"
              :key="index"
              class="canvasOption"
              :value="index"
            >{{ item.title || `画布 ${index + 1}` }}</el-radio>
          </el-radio-group>
        </div>
        <footer class="canvasSelectFooter">
          <el-button @click="cancelSelect">取消导入</el-button>
          <el-button
            class="importButton"
            :disabled="canvasList.length === 0 || readonly"
            @click="confirmSelect"
          >导入</el-button>
        </footer>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { actions, store } from './useStore'
import { assertMindmapImportDocument } from '@/utils/mindmap-import-validation'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const isDark = computed(() => store.localConfig.isDark)
const fileInputRef = ref(null)
const xmindCanvasSelectDialogVisible = ref(false)
const selectCanvas = ref(0)
const canvasList = ref([])
const isImporting = ref(false)
const importStatusText = ref('')

let selectPromiseResolve = null
let selectPromiseReject = null
let fileFetchController = null
let importRequestId = 0
let componentAlive = true

const supportFileStr = '.xmind,.smm,.json,.md'
const MAX_IMPORT_FILE_SIZE = 20 * 1024 * 1024

function handleShowImport() {
  if (props.readonly) return
  if (isImporting.value) {
    ElMessage.warning('已有文件正在导入，请稍候')
    return
  }
  fileInputRef.value?.click()
}

async function handleFileInputChange(event) {
  const input = event.target
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  await handleImportFile(file)
}

function isImportRequestCurrent(requestId) {
  return componentAlive && !props.readonly && requestId === importRequestId
}

function invalidateImportSession(message = '导入会话已经失效') {
  importRequestId += 1
  fileFetchController?.abort()
  fileFetchController = null
  rejectCanvasSelection(message)
  isImporting.value = false
  importStatusText.value = ''
}

function getRegexp() {
  return /\.(smm|json|xmind|md)$/i
}

function resolveImportType(name = '') {
  return getRegexp().exec(name)?.[1]?.toLowerCase() || ''
}

// Handle file URL from route query — restricted to same origin for security
async function handleFileURL() {
  if (props.readonly || !componentAlive) return
  let requestController = null
  try {
    const params = new URLSearchParams(window.location.search)
    const fileURL = params.get('fileURL')
    if (!fileURL) return
    let url
    try {
      url = new URL(fileURL, window.location.origin)
      if (url.origin !== window.location.origin) {
        console.warn('[Import] Blocked cross-origin fileURL:', fileURL)
        return
      }
    } catch {
      return
    }
    const type = resolveImportType(url.pathname)
    if (!type || isImporting.value) return
    fileFetchController?.abort()
    requestController = new AbortController()
    fileFetchController = requestController
    const res = await fetch(url.href, { signal: requestController.signal })
    if (!res.ok) throw new Error(`文件下载失败（${res.status}）`)
    const declaredSize = Number(res.headers.get('content-length'))
    if (Number.isFinite(declaredSize) && declaredSize > MAX_IMPORT_FILE_SIZE) {
      throw new Error('导入文件不能超过 20MB')
    }
    const file = await res.blob()
    if (props.readonly || !componentAlive || requestController.signal.aborted) return
    if (!validateFileSize(file)) return
    await executeImport({ raw: file, name: url.pathname }, type)
  } catch (error) {
    if (error?.name === 'AbortError') return
    console.error(error)
    ElMessage.error(error?.message || '文件下载失败')
  } finally {
    if (fileFetchController === requestController) fileFetchController = null
  }
}

async function handleSmm(file) {
  return JSON.parse(await file.raw.text())
}

async function handleXmind(file) {
  const xmindModule = await import('@mind-map/src/parse/xmind.js')
  return xmindModule.default.parseXmindFile(file.raw, requestXmindCanvasSelection)
}

function requestXmindCanvasSelection(content) {
  if (props.readonly || !componentAlive || !isImporting.value) {
    const error = new Error('导入会话已经失效')
    error.code = 'IMPORT_SESSION_EXPIRED'
    return Promise.reject(error)
  }
  rejectCanvasSelection('新的画布选择已开始')
  canvasList.value = content
  selectCanvas.value = 0
  xmindCanvasSelectDialogVisible.value = true
  return new Promise((resolve, reject) => {
    selectPromiseResolve = resolve
    selectPromiseReject = reject
  })
}

function confirmSelect() {
  if (props.readonly) return
  const selected = canvasList.value[selectCanvas.value]
  if (!selected || !selectPromiseResolve) return
  const resolve = selectPromiseResolve
  resetCanvasSelection()
  resolve(selected)
}

function cancelSelect() {
  rejectCanvasSelection('用户取消了画布选择')
}

function rejectCanvasSelection(message) {
  const reject = selectPromiseReject
  resetCanvasSelection()
  if (reject) {
    const error = new Error(message)
    error.code = 'IMPORT_CANCELLED'
    reject(error)
  }
}

function resetCanvasSelection() {
  selectPromiseResolve = null
  selectPromiseReject = null
  xmindCanvasSelectDialogVisible.value = false
  canvasList.value = []
  selectCanvas.value = 0
}

async function handleMd(file) {
  const markdownModule = await import('@mind-map/src/parse/markdown.js')
  return markdownModule.default.transformMarkdownTo(await file.raw.text())
}

async function executeImport(file, type) {
  if (props.readonly || !componentAlive) return false
  if (isImporting.value) {
    ElMessage.warning('已有文件正在导入，请稍候')
    return false
  }
  const requestId = ++importRequestId
  isImporting.value = true
  importStatusText.value = '正在解析并校验文件…'
  const progressMessage = ElMessage.info({
    message: '正在解析并校验文件…',
    duration: 0,
  })
  try {
    let data
    if (type === 'smm' || type === 'json') data = await handleSmm(file)
    else if (type === 'xmind') data = await handleXmind(file)
    else if (type === 'md') data = await handleMd(file)
    if (!isImportRequestCurrent(requestId)) return false
    assertMindmapImportDocument(data)
    await new Promise((resolve, reject) => {
      const handled = bus.emit('setData', data, { resolve, reject })
      if (!handled) reject(new Error('脑图编辑器尚未就绪'))
    })
    if (!isImportRequestCurrent(requestId)) return false
    importStatusText.value = '导入成功'
    ElMessage.success('导入成功')
    return true
  } catch (error) {
    if (!isImportRequestCurrent(requestId)) return false
    if (error?.code === 'IMPORT_CANCELLED') {
      importStatusText.value = '已取消导入'
      ElMessage.info('已取消导入')
    } else {
      console.error(error)
      importStatusText.value = error?.message || '文件解析失败'
      ElMessage.error(error?.message || '文件解析失败')
    }
    return false
  } finally {
    progressMessage.close()
    if (requestId === importRequestId) isImporting.value = false
  }
}

function validateFileSize(file) {
  if (!file || file.size <= MAX_IMPORT_FILE_SIZE) return true
  ElMessage.error('导入文件不能超过 20MB')
  return false
}

async function handleImportFile(file) {
  if (props.readonly) return
  const name = file?.name || ''
  const type = resolveImportType(name)
  if (!type) return ElMessage.error('请选择 XMind、SMM、JSON 或 Markdown 文件')
  if (!validateFileSize(file)) return false
  const imported = await executeImport({ raw: file, name }, type)
  if (imported) actions.setActiveSidebar(null)
  return imported
}

watch(() => props.readonly, (readonly) => {
  if (readonly) invalidateImportSession('脑图已切换为只读，导入已取消')
})

onMounted(() => {
  bus.on('showImport', handleShowImport)
  bus.on('handle_file_url', handleFileURL)
  bus.on('importFile', handleImportFile)
})

onBeforeUnmount(() => {
  componentAlive = false
  invalidateImportSession('导入组件已卸载')
  bus.off('showImport', handleShowImport)
  bus.off('handle_file_url', handleFileURL)
  bus.off('importFile', handleImportFile)
})
</script>

<style lang="less">
.el-overlay.xmindCanvasSelectOverlay {
  pointer-events: auto;

  .el-overlay-dialog {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .el-dialog.xmindCanvasSelectDialog {
    margin: 0 !important;
    padding: 0;
    overflow: hidden;
    border-radius: 12px;
    background: #eef0f2;
    box-shadow: 0 18px 54px rgba(0, 0, 0, 0.22);

    &.isDark {
      background: #1f2023;
    }
  }

  .el-dialog__header {
    display: none;
  }

  .el-dialog__body {
    padding: 10px;
  }
}

@media (max-width: 520px) {
  .el-overlay.xmindCanvasSelectOverlay {
    .el-overlay-dialog {
      padding: 16px;
    }

    .el-dialog.xmindCanvasSelectDialog {
      width: calc(100vw - 32px) !important;
    }
  }
}
</style>

<style lang="less" scoped>
.importFileInput {
  display: none;
}

.canvasSelectShell {
  display: flex;
  min-height: 360px;
  max-height: min(520px, calc(100vh - 68px));
  flex-direction: column;
  overflow: hidden;
  border-radius: 10px;
  background: #fff;
  color: #202124;

  .canvasSelectContent {
    min-height: 0;
    flex: 1;
    padding: 28px 28px 20px;
  }

  .canvasSelectTitle {
    margin: 0 0 8px;
    font-size: 21px;
    font-weight: 650;
    line-height: 1.3;
  }

  .canvasSelectHint {
    margin: 0 0 22px;
    color: #777a80;
    font-size: 13px;
    line-height: 1.6;
  }

  .canvasList {
    display: flex;
    max-height: 280px;
    flex-direction: column;
    gap: 8px;
    overflow-x: hidden;
    overflow-y: auto;
  }

  .canvasOption {
    width: 100%;
    min-height: 44px;
    margin: 0;
    padding: 10px 14px;
    border: 1px solid #e2e4e7;
    border-radius: 6px;
    background: #fff;

    &:hover {
      border-color: #bfc2c7;
      background: #f8f9fa;
    }

    &.is-checked {
      border-color: #2f3033;
      background: #f6f6f7;
    }

    :deep(.el-radio__input.is-checked .el-radio__inner) {
      border-color: #2f3033;
      background: #2f3033;
    }

    :deep(.el-radio__label) {
      overflow: hidden;
      color: #35373b;
      font-size: 14px;
      line-height: 20px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    :deep(.el-radio__input.is-checked + .el-radio__label) {
      color: #202124;
    }
  }

  .canvasSelectFooter {
    display: flex;
    height: 64px;
    flex-shrink: 0;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
    padding: 0 28px;
    border-top: 1px solid #eceef0;

    :deep(.el-button) {
      min-width: 64px;
      height: 32px;
      margin-left: 0;
      border-radius: 6px;
    }

    .importButton {
      border-color: #2f3033;
      background: #2f3033;
      color: #fff;

      &:hover,
      &:focus {
        border-color: #45464a;
        background: #45464a;
      }

      &:disabled {
        border-color: #a8aaae;
        background: #a8aaae;
      }
    }
  }

  &.isDark {
    background: #282a2d;
    color: rgba(255, 255, 255, 0.94);

    .canvasSelectHint {
      color: rgba(255, 255, 255, 0.58);
    }

    .canvasOption {
      border-color: #45474c;
      background: #2f3135;

      &:hover,
      &.is-checked {
        border-color: #777a80;
        background: #37393d;
      }

      :deep(.el-radio__label),
      :deep(.el-radio__input.is-checked + .el-radio__label) {
        color: rgba(255, 255, 255, 0.86);
      }
    }

    .canvasSelectFooter {
      border-color: #3c3e42;
    }
  }
}

.importStatus {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
