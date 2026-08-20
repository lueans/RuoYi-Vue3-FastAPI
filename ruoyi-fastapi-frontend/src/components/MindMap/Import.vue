<template>
  <div>
    <el-dialog
      class="nodeImportDialog"
      title="导入"
      v-model="dialogVisible"
      width="350px"
      :close-on-click-modal="!isImporting"
      :close-on-press-escape="!isImporting"
      append-to-body
    >
      <el-upload
        ref="uploadRef"
        action="x"
        :accept="supportFileStr"
        :file-list="fileList"
        :auto-upload="false"
        :multiple="false"
        :disabled="isImporting || readonly"
        :on-change="onChange"
        :on-remove="onRemove"
        :limit="1"
        :on-exceed="onExceed"
      >
        <template #trigger>
          <el-button size="small" type="primary" :disabled="isImporting || readonly">选取文件</el-button>
        </template>
        <template #tip>
          <div class="el-upload__tip">
            支持{{ supportFileStr }}文件
          </div>
          <div class="importStatus" role="status" aria-live="polite">
            {{ isImporting ? '正在解析并校验文件，请稍候…' : '文件只在本地解析，不会上传到服务器' }}
          </div>
        </template>
      </el-upload>
      <template #footer>
        <span class="dialog-footer">
          <el-button :disabled="isImporting" @click="cancel">取消</el-button>
          <el-button
            type="primary"
            :loading="isImporting"
            :disabled="fileList.length === 0 || readonly"
            @click="confirm"
          >{{ isImporting ? '导入中' : '确定' }}</el-button>
        </span>
      </template>
    </el-dialog>
    <el-dialog
      class="xmindCanvasSelectDialog"
      title="选择要导入的画布"
      v-model="xmindCanvasSelectDialogVisible"
      width="300px"
      :show-close="false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      append-to-body
    >
      <el-radio-group v-model="selectCanvas" class="canvasList" :disabled="readonly">
        <el-radio
          v-for="(item, index) in canvasList"
          :key="index"
          :value="index"
        >{{ item.title }}</el-radio>
      </el-radio-group>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="cancelSelect">取消导入</el-button>
          <el-button type="primary" :disabled="canvasList.length === 0 || readonly" @click="confirmSelect">导入所选画布</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { actions } from './useStore'
import { assertMindmapImportDocument } from '@/utils/mindmap-import-validation'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const dialogVisible = ref(false)
const fileList = ref([])
const uploadRef = ref(null)
const xmindCanvasSelectDialogVisible = ref(false)
const selectCanvas = ref(0)
const canvasList = ref([])
const isImporting = ref(false)

let selectPromiseResolve = null
let selectPromiseReject = null
let fileFetchController = null
let importRequestId = 0
let componentAlive = true

const supportFileStr = '.smm,.json,.xmind,.md'
const MAX_IMPORT_FILE_SIZE = 20 * 1024 * 1024

function handleShowImport() {
  if (props.readonly) return
  dialogVisible.value = true
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
  dialogVisible.value = false
  fileList.value = []
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

function onChange(file) {
  if (props.readonly) {
    fileList.value = []
    return
  }
  if (!getRegexp().test(file.name)) {
    ElMessage.error('请选择' + supportFileStr + '文件')
    fileList.value = []
  } else if (!validateFileSize(file.raw)) {
    fileList.value = []
  } else {
    fileList.value = [file]
  }
}

function onRemove(file, list) {
  fileList.value = list
}

function onExceed() {
  ElMessage.error('最多只能选择一个文件')
}

function cancel() {
  if (isImporting.value) return
  dialogVisible.value = false
}

async function confirm() {
  if (props.readonly) return
  if (fileList.value.length <= 0) {
    return ElMessage.error('请选择要导入的文件')
  }
  const file = fileList.value[0]
  const type = resolveImportType(file.name)
  if (!type) return ElMessage.error('不支持该文件格式')
  const imported = await executeImport(file, type)
  if (imported) {
    dialogVisible.value = false
    actions.setActiveSidebar(null)
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
    ElMessage.success('导入成功')
    return true
  } catch (error) {
    if (!isImportRequestCurrent(requestId)) return false
    if (error?.code === 'IMPORT_CANCELLED') {
      ElMessage.info('已取消导入')
    } else {
      console.error(error)
      ElMessage.error(error?.message || '文件解析失败')
    }
    return false
  } finally {
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
  onChange({ raw: file, name: file.name })
  if (fileList.value.length <= 0) return
  await confirm()
}

watch(dialogVisible, (val, oldVal) => {
  if (!val && oldVal) {
    fileList.value = []
  }
})

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
.el-overlay.nodeImportDialog {
  pointer-events: auto;
}
</style>

<style lang="less" scoped>
.nodeImportDialog {
}

.canvasList {
  display: flex;
  flex-direction: column;

  :deep(.el-radio) {
    margin-bottom: 12px;

    &:last-of-type {
      margin-bottom: 0;
    }
  }
}

.importStatus {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
</style>
