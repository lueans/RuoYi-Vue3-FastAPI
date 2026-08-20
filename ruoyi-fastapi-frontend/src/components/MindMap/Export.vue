<template>
  <el-dialog
    class="nodeExportDialog"
    :class="{ isDark: isDark }"
    v-model="dialogVisible"
    :width="'800px'"
    :show-close="false"
    :close-on-click-modal="!isExporting"
    :close-on-press-escape="!isExporting"
    append-to-body
  >
    <div class="exportContainer" :class="{ isDark: isDark }">
      <div class="downloadTypeSelectBox">
        <!-- type list -->
        <div class="downloadTypeList customScrollbar">
          <button
            class="downloadTypeItem"
            v-for="item in filteredTypeList"
            :key="item.type"
            :class="{ active: exportType === item.type }"
            type="button"
            :aria-pressed="exportType === item.type"
            :disabled="isExporting"
            @click="exportType = item.type"
          >
            <div class="typeIcon" :class="[item.type]"></div>
            <div class="name">{{ item.name }}</div>
            <div class="icon checked el-icon-check" v-if="exportType === item.type">
              <el-icon><Check /></el-icon>
            </div>
          </button>
        </div>
        <!-- type content -->
        <div class="downloadTypeContent">
          <!-- filename input -->
          <div class="nameInputBox">
            <div class="nameInput">
              <span class="name">导出文件名称</span>
              <el-input
                style="max-width: 250px"
                v-model="fileName"
                size="small"
                maxlength="125"
                aria-label="导出文件名称"
                :disabled="isExporting"
                @keydown.stop
              />
              <span v-if="fileNameError" class="fieldError" role="alert">{{ fileNameError }}</span>
            </div>
            <button class="closeBtn" type="button" aria-label="关闭导出对话框" :disabled="isExporting" @click="cancel">
              <el-icon><Close /></el-icon>
            </button>
          </div>
          <!-- config options -->
          <div class="contentBox customScrollbar">
            <div class="contentRow">
              <div class="contentName">格式</div>
              <div class="contentValue info">
                {{ currentTypeData ? '.' + currentTypeData.type : '' }}
              </div>
            </div>
            <div class="contentRow">
              <div class="contentName">说明</div>
              <div class="contentValue info">
                {{ currentTypeData ? currentTypeData.desc : '' }}
              </div>
            </div>
            <div class="contentRow">
              <div class="contentName">选项</div>
              <div class="contentValue info" v-if="noOptions">无</div>
              <div class="contentValue" v-else>
                <div
                  class="valueItem"
                  v-show="['smm', 'json'].includes(exportType)"
                >
                  <el-checkbox v-model="widthConfig" :disabled="isExporting">是否包含主题、结构等配置数据</el-checkbox>
                </div>
                <div
                  class="valueItem"
                  v-show="['svg', 'png', 'pdf'].includes(exportType)"
                >
                  <div class="valueSubItem">
                    <span class="name">水平内边距</span>
                    <el-input
                      style="width: 200px"
                      v-model="paddingX"
                      type="number"
                      min="0"
                      max="200"
                      step="1"
                      :disabled="isExporting"
                      size="small"
                      @change="onPaddingChange"
                      @keydown.stop
                    />
                  </div>
                  <div class="valueSubItem">
                    <span class="name">垂直内边距</span>
                    <el-input
                      style="width: 200px"
                      v-model="paddingY"
                      type="number"
                      min="0"
                      max="200"
                      step="1"
                      :disabled="isExporting"
                      size="small"
                      @change="onPaddingChange"
                      @keydown.stop
                    />
                  </div>
                  <div class="valueSubItem">
                    <span class="name">底部添加文字</span>
                    <el-input
                      style="width: 200px"
                      v-model="extraText"
                      size="small"
                      :disabled="isExporting"
                      placeholder="比如：来自simple-mind-map"
                      @keydown.stop
                    />
                  </div>
                  <div class="valueSubItem">
                    <el-checkbox
                      v-show="['png', 'pdf'].includes(exportType)"
                      v-model="isTransparent"
                      :disabled="isExporting"
                    >背景是否透明</el-checkbox>
                  </div>
                  <div class="valueSubItem">
                    <el-checkbox v-show="showFitBgOption" v-model="isFitBg" :disabled="isExporting">
                      是否显示完整背景图片（使用了背景图片时生效）
                    </el-checkbox>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- buttons -->
          <div class="btnList">
            <span class="exportStatus" role="status" aria-live="polite">{{ exportStatusText }}</span>
            <el-button :disabled="isExporting" @click="cancel" size="small">取消</el-button>
            <el-button
              type="primary"
              :loading="isExporting"
              :disabled="Boolean(fileNameError)"
              @click="confirm"
              size="small"
            >{{ isExporting ? '生成中' : '导出' }}</el-button>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { Close, Check } from '@element-plus/icons-vue'
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
const exportType = ref('smm')
const fileName = ref('思维导图')
const widthConfig = ref(true)
const isTransparent = ref(false)
const paddingX = ref(10)
const paddingY = ref(10)
const extraText = ref('')
const isFitBg = ref(true)
const isExporting = ref(false)
const exportStatusText = ref('')
let exportRequestId = 0

const filteredTypeList = computed(() => {
  // Use local downTypeList from config (already Chinese)
  return downTypeList.filter(item => {
    return item.value !== 'mm' && item.value !== 'xlsx'
  }).map(item => ({
    name: item.name,
    type: item.value,
    desc: item.desc
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

function handleShowExport() {
  exportStatusText.value = ''
  dialogVisible.value = true
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
.el-overlay.nodeExportDialog {
  pointer-events: auto;
}
</style>

<style lang="less" scoped>
.nodeExportDialog {
  .exportContainer {
    &.isDark {
      .downloadTypeSelectBox {
        .downloadTypeList {
          background-color: #363b3f;

          .downloadTypeItem {
            background-color: #363b3f;

            &.active {
              background-color: #262a2e;
            }

            .name {
              color: hsla(0, 0%, 100%, 0.9);
            }
          }
        }

        .downloadTypeContent {
          .nameInputBox {
            border-bottom: 1px solid hsla(0, 0%, 100%, 0.6);

            .nameInput {
              .name {
                color: hsla(0, 0%, 100%, 0.6);
              }
            }

            .closeBtn {
              color: hsla(0, 0%, 100%, 0.6);
            }
          }

          .contentBox {
            .contentRow {
              .contentName {
                color: hsla(0, 0%, 100%, 0.6);
              }

              .contentValue {
                color: hsla(0, 0%, 100%, 0.6);

                &.info {
                  background-color: transparent;
                }
              }
            }
          }

          .btnList {
            border-top: 1px solid hsla(0, 0%, 100%, 0.6);
          }
        }
      }
    }
  }
}

.nodeExportDialog {
  &.isDark {
    :deep(.el-dialog__body) {
      .el-checkbox {
        .el-checkbox__label {
          color: hsla(0, 0%, 100%, 0.6);
        }
      }
    }
  }

  :deep(.el-dialog) {
    border-radius: 10px;
    overflow: hidden;

    .el-dialog__header {
      display: none;
    }
  }

  :deep(.el-dialog__body) {
    padding: 0;

    .el-checkbox__input.is-checked + .el-checkbox__label {
      color: #409eff !important;
    }

    .el-checkbox {
      .el-checkbox__label {
        color: #1a1a1a;
      }
    }
  }

  .exportContainer {
    width: 100%;
    height: 552px;
    overflow: hidden;
    display: flex;
    flex-direction: column;

    .downloadTypeSelectBox {
      width: 100%;
      height: 100%;
      overflow: hidden;
      display: flex;

      .downloadTypeList {
        width: 208px;
        height: 100%;
        overflow-y: auto;
        overflow-x: hidden;
        background-color: #f2f4f7;
        flex-shrink: 0;
        padding: 16px 0;

        .downloadTypeItem {
          appearance: none;
          border: 0;
          background: transparent;
          text-align: left;
          font: inherit;
          width: 100%;
          height: 52px;
          padding: 0 30px;
          overflow: hidden;
          display: flex;
          align-items: center;
          cursor: pointer;

          &:disabled {
            cursor: progress;
            opacity: 0.65;
          }

          &:focus-visible {
            outline: 2px solid #3370ff;
            outline-offset: -3px;
          }

          &.active {
            background-color: #fff;

            .icon {
              &.checked {
                display: block;
              }
            }
          }

          .icon {
            font-size: 25px;
            font-weight: 700;

            &.checked {
              color: #409eff;
              font-size: 20px;
              margin-left: auto;
              display: none;
            }
          }

          .typeIcon {
            margin-right: 18px;
            flex-shrink: 0;
            width: 23px;
            height: 26px;
            background-size: cover;
          }

          .name {
            color: #333;
            font-size: 15px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            font-weight: bold;
          }
        }
      }

      .downloadTypeContent {
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        overflow: hidden;

        .nameInputBox {
          display: flex;
          align-items: center;
          justify-content: space-between;
          min-height: 67px;
          flex-shrink: 0;
          border-bottom: 1px solid #f2f4f7;
          padding-left: 40px;
          padding-right: 20px;
          padding-top: 16px;
          padding-bottom: 12px;

          .nameInput {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            width: 100%;
            font-weight: bold;

            .name {
              margin-right: 10px;
              font-size: 15px;
              color: #333;
              font-weight: bold;
            }
          }

          .closeBtn {
            font-size: 20px;
            cursor: pointer;
            display: inline-flex;
            padding: 4px;
            border: 0;
            border-radius: 4px;
            background: transparent;
            color: inherit;

            &:disabled {
              cursor: progress;
              opacity: 0.5;
            }

            &:focus-visible {
              outline: 2px solid #3370ff;
              outline-offset: 2px;
            }
          }

          .fieldError {
            flex-basis: 100%;
            margin-top: 4px;
            color: var(--el-color-danger);
            font-size: 12px;
            font-weight: 400;
          }
        }

        .contentBox {
          height: 100%;
          overflow-y: auto;
          overflow-x: hidden;
          padding: 15px 40px;

          .contentRow {
            display: flex;
            font-size: 14px;
            margin-bottom: 20px;

            &:last-of-type {
              margin-bottom: 0;
            }

            .contentName {
              min-width: 40px;
              color: #808080;
              flex-shrink: 0;
              font-size: 13px;
              font-weight: 500;
              line-height: 25px;
              margin-right: 12px;
            }

            .contentValue {
              color: #808080;
              line-height: 23px;
              font-weight: 500;
              border: 1px solid transparent;
              font-size: 14px;

              &.info {
                color: rgb(90, 158, 247);
                background-color: rgb(245, 248, 249);
                border: 1px solid rgb(90, 158, 247);
                border-radius: 5px;
                padding: 0 16px;
              }

              .valueItem {
                .valueSubItem {
                  margin-bottom: 12px;
                  display: flex;
                  align-items: center;

                  &:last-of-type {
                    margin-right: 0;
                  }

                  .name {
                    margin-right: 12px;
                    min-width: 85px;
                  }
                }
              }
            }
          }
        }

        .btnList {
          padding: 0 40px;
          display: flex;
          align-items: center;
          justify-content: flex-end;
          height: 69px;
          flex-shrink: 0;
          border-top: 1px solid #f2f4f7;

          .exportStatus {
            margin-right: auto;
            color: var(--el-text-color-secondary);
            font-size: 13px;
          }
        }
      }
    }
  }
}
</style>
