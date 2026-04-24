<template>
  <div>
    <el-dialog
      class="nodeImportDialog"
      title="导入"
      v-model="dialogVisible"
      width="350px"
    >
      <el-upload
        ref="uploadRef"
        action="x"
        :accept="supportFileStr"
        :file-list="fileList"
        :auto-upload="false"
        :multiple="false"
        :on-change="onChange"
        :on-remove="onRemove"
        :limit="1"
        :on-exceed="onExceed"
      >
        <template #trigger>
          <el-button size="small" type="primary">选取文件</el-button>
        </template>
        <template #tip>
          <div class="el-upload__tip">
            支持{{ supportFileStr }}文件
          </div>
        </template>
      </el-upload>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="cancel">取消</el-button>
          <el-button type="primary" @click="confirm">确定</el-button>
        </span>
      </template>
    </el-dialog>
    <el-dialog
      class="xmindCanvasSelectDialog"
      title="选择要导入的画布"
      v-model="xmindCanvasSelectDialogVisible"
      width="300px"
      :show-close="false"
    >
      <el-radio-group v-model="selectCanvas" class="canvasList">
        <el-radio
          v-for="(item, index) in canvasList"
          :key="index"
          :value="index"
        >{{ item.title }}</el-radio>
      </el-radio-group>
      <template #footer>
        <span class="dialog-footer">
          <el-button type="primary" @click="confirmSelect">确定</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { actions } from './useStore'

const dialogVisible = ref(false)
const fileList = ref([])
const uploadRef = ref(null)
const xmindCanvasSelectDialogVisible = ref(false)
const selectCanvas = ref(0)
const canvasList = ref([])

let selectPromiseResolve = null

const supportFileStr = '.smm,.json,.xmind,.md'

function handleShowImport() {
  dialogVisible.value = true
}

function getRegexp() {
  return new RegExp(`\\.(smm|json|xmind|md)$`)
}

// Handle file URL from route query — restricted to same origin for security
async function handleFileURL() {
  try {
    const params = new URLSearchParams(window.location.search)
    const fileURL = params.get('fileURL')
    if (!fileURL) return
    const match = getRegexp().exec(fileURL)
    if (!match) return
    try {
      const url = new URL(fileURL, window.location.origin)
      if (url.origin !== window.location.origin) {
        console.warn('[Import] Blocked cross-origin fileURL:', fileURL)
        return
      }
    } catch {
      return
    }
    const type = match[1]
    const res = await fetch(fileURL)
    const file = await res.blob()
    const data = { raw: file }
    if (type === 'smm' || type === 'json') {
      handleSmm(data)
    } else if (type === 'xmind') {
      handleXmind(data)
    } else if (type === 'md') {
      handleMd(data)
    }
  } catch (error) {
    console.error(error)
  }
}

function onChange(file) {
  if (!getRegexp().test(file.name)) {
    ElMessage.error('请选择' + supportFileStr + '文件')
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
  dialogVisible.value = false
}

function confirm() {
  if (fileList.value.length <= 0) {
    return ElMessage.error('请选择要导入的文件')
  }
  const file = fileList.value[0]
  if (/\.(smm|json)$/.test(file.name)) {
    handleSmm(file)
  } else if (/\.xmind$/.test(file.name)) {
    handleXmind(file)
  } else if (/\.md$/.test(file.name)) {
    handleMd(file)
  }
  cancel()
  actions.setActiveSidebar(null)
}

function handleSmm(file) {
  const fileReader = new FileReader()
  fileReader.readAsText(file.raw)
  fileReader.onload = evt => {
    try {
      const data = JSON.parse(evt.target.result)
      if (typeof data !== 'object') {
        throw new Error('文件内容有误')
      }
      bus.emit('setData', data)
      ElMessage.success('导入成功')
    } catch (error) {
      console.error(error)
      ElMessage.error('文件解析失败')
    }
  }
}

async function handleXmind(file) {
  try {
    const xmindModule = await import('@mind-map/src/parse/xmind.js')
    const xmind = xmindModule.default
    const data = await xmind.parseXmindFile(file.raw, content => {
      showSelectXmindCanvasDialog(content)
      return new Promise(resolve => {
        selectPromiseResolve = resolve
      })
    })
    bus.emit('setData', data)
    ElMessage.success('导入成功')
  } catch (error) {
    console.error(error)
    ElMessage.error('文件解析失败')
  }
}

function showSelectXmindCanvasDialog(content) {
  canvasList.value = content
  selectCanvas.value = 0
  xmindCanvasSelectDialogVisible.value = true
}

function confirmSelect() {
  if (selectPromiseResolve) {
    selectPromiseResolve(canvasList.value[selectCanvas.value])
  }
  xmindCanvasSelectDialogVisible.value = false
  canvasList.value = []
  selectCanvas.value = 0
}

async function handleMd(file) {
  const fileReader = new FileReader()
  fileReader.readAsText(file.raw)
  fileReader.onload = async evt => {
    try {
      const markdownModule = await import('@mind-map/src/parse/markdown.js')
      const markdown = markdownModule.default
      const data = markdown.transformMarkdownTo(evt.target.result)
      bus.emit('setData', data)
      ElMessage.success('导入成功')
    } catch (error) {
      console.error(error)
      ElMessage.error('文件解析失败')
    }
  }
}

function handleImportFile(file) {
  onChange({ raw: file, name: file.name })
  if (fileList.value.length <= 0) return
  confirm()
}

watch(dialogVisible, (val, oldVal) => {
  if (!val && oldVal) {
    fileList.value = []
  }
})

onMounted(() => {
  bus.on('showImport', handleShowImport)
  bus.on('handle_file_url', handleFileURL)
  bus.on('importFile', handleImportFile)
})

onBeforeUnmount(() => {
  bus.off('showImport', handleShowImport)
  bus.off('handle_file_url', handleFileURL)
  bus.off('importFile', handleImportFile)
})
</script>

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
</style>
