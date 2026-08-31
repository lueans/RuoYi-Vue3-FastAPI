<template>
  <el-dialog
    class="nodeExportDialog"
    :class="{ isDark: isDark }"
    v-model="dialogVisible"
    width="760px"
    modal-class="nodeExportOverlay"
    :show-close="false"
    :close-on-click-modal="!isExporting"
    :close-on-press-escape="!isExporting"
    append-to-body
  >
    <div class="xmindExportShell" :class="{ isDark: isDark }">
      <section class="exportPreviewPane" aria-label="当前脑图预览">
        <div ref="previewRef" class="previewCanvas"></div>
        <span v-if="!hasPreview" class="previewPlaceholder">正在生成预览…</span>
      </section>

      <section class="exportSettingsPane" aria-labelledby="mindmapExportTitle">
        <div class="settingsContent customScrollbar">
          <h2 id="mindmapExportTitle" class="dialogTitle">
            导出为{{ currentTypeData?.name || '' }}
          </h2>

          <div class="settingGroup">
            <label class="settingRow">
              <span class="settingLabel">文件名称</span>
              <span class="settingControl">
                <el-input
                  v-model="fileName"
                  maxlength="125"
                  :disabled="isExporting"
                  aria-label="导出文件名称"
                  @keydown.stop
                >
                  <template #append>.{{ currentTypeData?.type || '' }}</template>
                </el-input>
                <span v-if="fileNameError" class="fieldError" role="alert">{{ fileNameError }}</span>
              </span>
            </label>

            <label class="settingRow">
              <span class="settingLabel">格式</span>
              <span class="settingControl">
                <el-select
                  v-model="exportType"
                  :disabled="isExporting"
                  aria-label="导出格式"
                >
                  <el-option
                    v-for="item in filteredTypeList"
                    :key="item.type"
                    :label="item.name"
                    :value="item.type"
                  />
                </el-select>
              </span>
            </label>
          </div>

          <div v-if="!noOptions" class="settingsDivider"></div>

          <div v-if="['smm', 'json'].includes(exportType)" class="settingGroup">
            <div class="switchRow">
              <span>包含主题、结构等配置数据</span>
              <el-switch v-model="widthConfig" :disabled="isExporting" />
            </div>
          </div>

          <div v-if="['svg', 'png', 'pdf'].includes(exportType)" class="settingGroup">
            <label class="settingRow">
              <span class="settingLabel">水平内边距</span>
              <span class="settingControl compactControl">
                <el-input-number
                  v-model="paddingX"
                  :min="0"
                  :max="200"
                  :step="1"
                  :disabled="isExporting"
                  controls-position="right"
                  aria-label="水平内边距"
                  @change="onPaddingChange"
                  @keydown.stop
                />
              </span>
            </label>

            <label class="settingRow">
              <span class="settingLabel">垂直内边距</span>
              <span class="settingControl compactControl">
                <el-input-number
                  v-model="paddingY"
                  :min="0"
                  :max="200"
                  :step="1"
                  :disabled="isExporting"
                  controls-position="right"
                  aria-label="垂直内边距"
                  @change="onPaddingChange"
                  @keydown.stop
                />
              </span>
            </label>

            <label class="settingRow">
              <span class="settingLabel">底部文字</span>
              <span class="settingControl">
                <el-input
                  v-model="extraText"
                  :disabled="isExporting"
                  placeholder="选填"
                  aria-label="底部添加文字"
                  @keydown.stop
                />
              </span>
            </label>
          </div>

          <div v-if="['png', 'pdf'].includes(exportType)" class="settingsDivider"></div>

          <div v-if="['png', 'pdf'].includes(exportType)" class="settingGroup switchGroup">
            <div class="switchRow">
              <span>透明背景</span>
              <el-switch v-model="isTransparent" :disabled="isExporting" />
            </div>
            <div v-if="showFitBgOption" class="switchRow">
              <span>显示完整背景图片</span>
              <el-switch v-model="isFitBg" :disabled="isExporting" />
            </div>
          </div>
        </div>

        <footer class="dialogFooter">
          <span class="exportStatus" role="status" aria-live="polite">{{ exportStatusText }}</span>
          <el-button :disabled="isExporting" @click="cancel">取消</el-button>
          <el-button
            class="exportButton"
            :loading="isExporting"
            :disabled="Boolean(fileNameError)"
            @click="confirm"
          >{{ isExporting ? '生成中' : '导出' }}</el-button>
        </footer>
      </section>
    </div>
  </el-dialog>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import bus from './useEventBus'
import { store } from './useStore'
import { downTypeList } from './config'
import {
  normalizeMindmapExportPadding,
  validateMindmapExportName,
} from '@/utils/mindmap-export'

const isDark = computed(() => store.localConfig.isDark)

const dialogVisible = ref(false)
const exportType = ref('png')
const fileName = ref('思维导图')
const widthConfig = ref(true)
const isTransparent = ref(false)
const paddingX = ref(10)
const paddingY = ref(10)
const extraText = ref('')
const isFitBg = ref(true)
const isExporting = ref(false)
const exportStatusText = ref('')
const previewRef = ref(null)
const hasPreview = ref(false)
let exportRequestId = 0

const filteredTypeList = computed(() => {
  return downTypeList.filter(item => {
    return item.value !== 'mm' && item.value !== 'xlsx'
  }).map(item => ({
    name: item.name,
    type: item.value,
    desc: item.desc,
  }))
})

const currentTypeData = computed(() => {
  return filteredTypeList.value.find(item => item.type === exportType.value)
})

const showFitBgOption = computed(() => {
  return ['png', 'pdf'].includes(exportType.value) && !isTransparent.value
})

const noOptions = computed(() => {
  return ['md', 'xmind', 'txt', 'xlsx', 'mm'].includes(exportType.value)
})

const normalizedFileName = computed(() => (
  validateMindmapExportName(fileName.value, exportType.value)
))
const fileNameError = computed(() => normalizedFileName.value.error)

function refreshPreview() {
  hasPreview.value = false
  previewRef.value?.replaceChildren()
  if (!previewRef.value || !store.mindMap?.getSvgData) return
  try {
    const { svg, rect } = store.mindMap.getSvgData({
      paddingX: 16,
      paddingY: 16,
      ignoreWatermark: true,
    })
    if (!svg?.node || !rect?.width || !rect?.height) return
    svg.node.setAttribute('viewBox', `0 0 ${rect.width} ${rect.height}`)
    svg.node.setAttribute('preserveAspectRatio', 'xMidYMid meet')
    previewRef.value.replaceChildren(svg.node)
    hasPreview.value = true
  } catch (error) {
    console.warn('生成导出预览失败:', error)
  }
}

async function handleShowExport() {
  exportStatusText.value = ''
  dialogVisible.value = true
  await nextTick()
  refreshPreview()
}

function onPaddingChange() {
  paddingX.value = normalizeMindmapExportPadding(paddingX.value)
  paddingY.value = normalizeMindmapExportPadding(paddingY.value)
}

function cancel() {
  if (isExporting.value) return
  dialogVisible.value = false
}

function requestExport(payload) {
  return new Promise((resolve, reject) => {
    const handled = bus.emit('exportRequest', { ...payload, resolve, reject })
    if (!handled) reject(new Error('导出服务尚未就绪'))
  })
}

function createExportArgs(type, name, footerText = '') {
  const base = {
    type,
    name,
    config: {
      exportPaddingX: paddingX.value,
      exportPaddingY: paddingY.value,
      addContentToFooter: footerText ? () => footerText : null,
    },
  }
  if (type === 'xmind') return { ...base, args: [] }
  if (type === 'svg') {
    return { ...base, args: ['* { margin: 0; padding: 0; box-sizing: border-box; }'] }
  }
  if (['smm', 'json'].includes(type)) return { ...base, args: [widthConfig.value] }
  if (type === 'png') return { ...base, args: [isTransparent.value, null, isFitBg.value] }
  if (type === 'pdf') return { ...base, args: [isTransparent.value, isFitBg.value] }
  return { ...base, args: [] }
}

async function confirm() {
  if (isExporting.value || fileNameError.value) return
  const type = exportType.value
  const name = normalizedFileName.value.name
  const footerText = extraText.value
  const requestId = ++exportRequestId
  isExporting.value = true
  exportStatusText.value = type === 'pdf' || type === 'xmind'
    ? '正在加载导出组件并生成文件…'
    : '正在生成文件…'
  onPaddingChange()
  try {
    await requestExport(createExportArgs(type, name, footerText))
    if (requestId !== exportRequestId) return
    exportStatusText.value = '文件已生成并开始下载'
    ElMessage.success('导出成功')
    dialogVisible.value = false
  } catch (error) {
    if (requestId !== exportRequestId) return
    console.error('导出失败:', error)
    exportStatusText.value = error?.message || '导出失败，请重试'
    ElMessage.error(exportStatusText.value)
  } finally {
    if (requestId === exportRequestId) isExporting.value = false
  }
}

onMounted(() => {
  bus.on('showExport', handleShowExport)
})

onBeforeUnmount(() => {
  exportRequestId += 1
  bus.off('showExport', handleShowExport)
})
</script>

<style lang="less">
.el-overlay.nodeExportOverlay {
  pointer-events: auto;

  .el-overlay-dialog {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .el-dialog.nodeExportDialog {
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

@media (max-width: 800px) {
  .el-overlay.nodeExportOverlay {
    .el-overlay-dialog {
      padding: 16px;
    }

    .el-dialog.nodeExportDialog {
      width: calc(100vw - 32px) !important;
    }
  }
}
</style>

<style lang="less" scoped>
.xmindExportShell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 10px;
  width: 100%;
  height: 540px;
  color: #222326;

  .exportPreviewPane,
  .exportSettingsPane {
    overflow: hidden;
    border-radius: 10px;
    background: #fff;
  }

  .exportPreviewPane {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px 24px;
  }

  .previewCanvas {
    display: flex;
    width: 100%;
    height: 100%;
    align-items: center;
    justify-content: center;

    :deep(svg) {
      display: block;
      width: 100%;
      height: 100%;
      max-width: 100%;
      max-height: 100%;
    }
  }

  .previewPlaceholder {
    position: absolute;
    color: #9b9da2;
    font-size: 13px;
  }

  .exportSettingsPane {
    display: flex;
    min-width: 0;
    flex-direction: column;
  }

  .settingsContent {
    min-height: 0;
    flex: 1;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 28px 28px 20px;
  }

  .dialogTitle {
    margin: 0 0 28px;
    color: #202124;
    font-size: 21px;
    font-weight: 650;
    line-height: 1.25;
  }

  .settingGroup {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .settingRow {
    display: grid;
    grid-template-columns: 112px minmax(0, 1fr);
    align-items: start;
    min-height: 32px;
  }

  .settingLabel {
    padding-top: 7px;
    color: #5f6167;
    font-size: 14px;
    line-height: 18px;
  }

  .settingControl {
    min-width: 0;

    :deep(.el-select),
    :deep(.el-input-number) {
      width: 100%;
    }

    :deep(.el-input__wrapper),
    :deep(.el-select__wrapper),
    :deep(.el-input-number .el-input__wrapper) {
      min-height: 32px;
      border-radius: 6px;
      box-shadow: 0 0 0 1px #d8dadd inset;
    }

    :deep(.el-input-group__append) {
      padding: 0 10px;
      border-radius: 0 6px 6px 0;
      background: #f5f6f7;
      color: #777a80;
      box-shadow: 0 0 0 1px #d8dadd inset;
    }
  }

  .compactControl {
    max-width: 150px;
  }

  .fieldError {
    display: block;
    margin-top: 5px;
    color: var(--el-color-danger);
    font-size: 12px;
    line-height: 16px;
  }

  .settingsDivider {
    height: 1px;
    margin: 24px 0;
    background: #eceef0;
  }

  .switchGroup {
    gap: 18px;
  }

  .switchRow {
    display: flex;
    min-height: 28px;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    color: #3d3f44;
    font-size: 14px;

    :deep(.el-switch) {
      --el-switch-on-color: #2f3033;
      --el-switch-off-color: #d6d8dc;
      flex-shrink: 0;
    }
  }

  .dialogFooter {
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

    .exportButton {
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

  .exportStatus {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }

  &.isDark {
    color: rgba(255, 255, 255, 0.9);

    .exportPreviewPane,
    .exportSettingsPane {
      background: #282a2d;
    }

    .dialogTitle {
      color: rgba(255, 255, 255, 0.94);
    }

    .settingLabel,
    .switchRow {
      color: rgba(255, 255, 255, 0.68);
    }

    .settingsDivider,
    .dialogFooter {
      border-color: #3c3e42;
    }

    .settingsDivider {
      background: #3c3e42;
    }

    .settingControl :deep(.el-input-group__append) {
      background: #34363a;
      color: rgba(255, 255, 255, 0.58);
    }
  }
}

@media (max-width: 800px) {
  .xmindExportShell {
    grid-template-columns: 1fr;
    grid-template-rows: 170px minmax(0, 1fr);
    height: min(700px, calc(100vh - 68px));

    .exportPreviewPane {
      padding: 20px 32px;
    }

    .settingsContent {
      padding: 22px 22px 18px;
    }

    .dialogTitle {
      margin-bottom: 22px;
    }

    .dialogFooter {
      padding: 0 22px;
    }
  }
}
</style>
