<template>
  <el-dialog
    class="nodeExportDialog"
    :class="{ isDark: isDark }"
    v-model="dialogVisible"
    :width="'800px'"
    :show-close="false"
  >
    <div class="exportContainer" :class="{ isDark: isDark }">
      <div class="downloadTypeSelectBox">
        <!-- type list -->
        <div class="downloadTypeList customScrollbar">
          <div
            class="downloadTypeItem"
            v-for="item in filteredTypeList"
            :key="item.type"
            :class="{ active: exportType === item.type }"
            @click="exportType = item.type"
          >
            <div class="typeIcon" :class="[item.type]"></div>
            <div class="name">{{ item.name }}</div>
            <div class="icon checked el-icon-check" v-if="exportType === item.type">
              <el-icon><Check /></el-icon>
            </div>
          </div>
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
                @keydown.stop
              />
            </div>
            <span class="closeBtn" @click="cancel">
              <el-icon><Close /></el-icon>
            </span>
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
                  <el-checkbox v-model="widthConfig">是否包含主题、结构等配置数据</el-checkbox>
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
                      placeholder="比如：来自simple-mind-map"
                      @keydown.stop
                    />
                  </div>
                  <div class="valueSubItem">
                    <el-checkbox
                      v-show="['png', 'pdf'].includes(exportType)"
                      v-model="isTransparent"
                    >背景是否透明</el-checkbox>
                  </div>
                  <div class="valueSubItem">
                    <el-checkbox v-show="showFitBgOption" v-model="isFitBg">
                      是否显示完整背景图片（使用了背景图片时生效）
                    </el-checkbox>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- buttons -->
          <div class="btnList">
            <el-button @click="cancel" size="small">取消</el-button>
            <el-button type="primary" @click="confirm" size="small">导出</el-button>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { Close, Check } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import bus from './useEventBus'
import { store } from './useStore'
import { downTypeList } from './config'

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
const imageFormat = ref('png')

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

function handleShowExport() {
  dialogVisible.value = true
}

function onPaddingChange() {
  bus.emit('paddingChange', {
    exportPaddingX: Number(paddingX.value),
    exportPaddingY: Number(paddingY.value)
  })
}

function cancel() {
  dialogVisible.value = false
}

function confirm() {
  const type = exportType.value
  if (extraText.value) {
    bus.emit('paddingChange', {
      addContentToFooter: () => extraText.value
    })
  }
  if (type === 'xmind') {
    bus.emit('exportXmind', fileName.value)
  } else if (type === 'svg') {
    bus.emit('export', type, true, fileName.value, '* { margin: 0; padding: 0; box-sizing: border-box; }')
  } else if (['smm', 'json'].includes(type)) {
    bus.emit('export', type, true, fileName.value, widthConfig.value)
  } else if (type === 'png') {
    bus.emit('export', 'png', true, fileName.value, isTransparent.value, null, isFitBg.value)
  } else if (type === 'pdf') {
    bus.emit('export', type, true, fileName.value, isTransparent.value, isFitBg.value)
  } else {
    bus.emit('export', type, true, fileName.value)
  }
  ElNotification.info({
    title: '消息',
    message: '如果没有触发下载，请检查是否被浏览器拦截了'
  })
  cancel()
}

onMounted(() => {
  bus.on('showExport', handleShowExport)
})

onBeforeUnmount(() => {
  bus.off('showExport', handleShowExport)
})
</script>

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
          width: 100%;
          height: 52px;
          padding: 0 30px;
          overflow: hidden;
          display: flex;
          align-items: center;
          cursor: pointer;

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
          height: 67px;
          flex-shrink: 0;
          border-bottom: 1px solid #f2f4f7;
          padding-left: 40px;
          padding-right: 20px;
          padding-top: 16px;

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
        }
      }
    }
  }
}
</style>
