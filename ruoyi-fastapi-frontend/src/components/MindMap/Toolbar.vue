<template>
  <div
    ref="toolbarContainerRef"
    class="toolbarContainer"
    :class="{ isDark: isDark, embedded: props.embedded }"
  >
    <div class="toolbar" ref="toolbarRef" role="toolbar" aria-label="脑图编辑操作">
      <!-- Node operation buttons -->
      <div class="toolbarBlock" role="group" aria-label="节点操作">
        <div class="toolbarNodeBtnList">
          <template v-for="(item, index) in horizontalList" :key="item">
            <el-tooltip :content="btnLabels[item]" placement="bottom" :show-after="300">
              <button
                type="button"
                class="toolbarBtn"
                :class="{
                  disabled: isButtonDisabled(item),
                  active: isButtonActive(item),
                  dividerBefore: index > 0 && ['back', 'painter'].includes(item)
                }"
                :disabled="isButtonDisabled(item)"
                :aria-pressed="item === 'painter' ? isInPainter : undefined"
                @click="executeToolbarItem(item)"
              >
                <span :class="['icon', 'iconfont', toolbarItemDefinitions[item].icon]" />
                <span class="text">{{ btnLabels[item] }}</span>
              </button>
            </el-tooltip>
          </template>
        </div>
        <!-- More button (overflow items) -->
        <el-popover
          v-model:visible="popoverShow"
          placement="bottom-end"
          :width="120"
          trigger="click"
          v-if="showMoreBtn"
          :style="{ marginLeft: horizontalList.length > 0 ? (props.embedded ? '2px' : '20px') : 0 }"
        >
          <template #reference>
            <button
              class="toolbarBtn"
              type="button"
              aria-label="更多节点操作"
              aria-controls="mindmap-toolbar-overflow"
              :aria-expanded="popoverShow"
            >
              <span class="icon"><el-icon><MoreFilled /></el-icon></span>
              <span class="text">更多</span>
            </button>
          </template>
          <div
            id="mindmap-toolbar-overflow"
            class="toolbarNodeBtnList v"
            role="group"
            aria-label="更多节点操作"
            @click="popoverShow = false"
          >
            <template v-for="item in verticalList" :key="item">
              <button
                type="button"
                class="toolbarBtn"
                :class="{ disabled: isButtonDisabled(item), active: isButtonActive(item) }"
                :disabled="isButtonDisabled(item)"
                :aria-pressed="item === 'painter' ? isInPainter : undefined"
                @click="executeToolbarItem(item)"
              >
                <span :class="['icon', 'iconfont', toolbarItemDefinitions[item].icon]" />
                <span class="text">{{ btnLabels[item] }}</span>
              </button>
            </template>
            <div v-if="props.embedded" class="overflowFileOperations" role="group" aria-label="文件操作">
              <button
                type="button"
                class="toolbarBtn"
                :disabled="isReadonly"
                @click="bus.emit('showImport')"
              >
                <span class="icon iconfont icondaoru"></span>
                <span class="text">导入</span>
              </button>
              <button
                type="button"
                class="toolbarBtn"
                @click="bus.emit('showExport')"
              >
                <span class="icon iconfont iconexport"></span>
                <span class="text">导出</span>
              </button>
            </div>
          </div>
        </el-popover>
      </div>
      <!-- File operations block -->
      <div v-if="!props.embedded" class="toolbarBlock" role="group" aria-label="文件操作">
        <el-tooltip :content="btnLabels.import" placement="bottom" :show-after="300">
          <button type="button" class="toolbarBtn" :disabled="isReadonly" @click="bus.emit('showImport')">
            <span class="icon iconfont icondaoru"></span>
            <span class="text">导入</span>
          </button>
        </el-tooltip>
        <el-tooltip :content="btnLabels.export" placement="bottom" :show-after="300">
          <button type="button" class="toolbarBtn" @click="bus.emit('showExport')" style="margin-right: 0;">
            <span class="icon iconfont iconexport"></span>
            <span class="text">导出</span>
          </button>
        </el-tooltip>
      </div>
    </div>
    <NodeImage :readonly="isReadonly" />
    <NodeHyperlink :readonly="isReadonly" />
    <NodeNote :readonly="isReadonly" />
    <NodeTag :readonly="isReadonly" />
    <ExportDialog />
    <ImportDialog ref="importRef" :readonly="isReadonly" />
  </div>
</template>

<script setup>
import { MoreFilled } from '@element-plus/icons-vue'
import bus from './useEventBus'
import { store } from './useStore'
import NodeImage from './NodeImage.vue'
import NodeHyperlink from './NodeHyperlink.vue'
import NodeNote from './NodeNote.vue'
import NodeTag from './NodeTag.vue'
import ExportDialog from './Export.vue'
import ImportDialog from './Import.vue'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'
import { createLatestRequestTracker } from '@/utils/mindmap-async'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'
import { selectLargestFittingToolbarCount } from '@/utils/mindmap-toolbar-layout'

const props = defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})

const btnLabels = {
  back: '撤销',
  forward: '重做',
  painter: '格式刷',
  siblingNode: '主题',
  childNode: '子主题',
  deleteNode: '删除',
  image: '图片',
  link: '超链接',
  attachment: '附件',
  note: '备注',
  tag: '标签',
  summary: '概要',
  associativeLine: '联系',
  outerFrame: '外框',
  import: '导入',
  export: '导出',
}

const toolbarItemDefinitions = Object.freeze({
  back: { icon: 'iconhoutui-shi', command: 'BACK' },
  forward: { icon: 'iconqianjin1', command: 'FORWARD' },
  painter: { icon: 'iconjiedian', event: 'startPainter' },
  siblingNode: { icon: 'iconjiedian', command: 'INSERT_NODE' },
  childNode: { icon: 'icontianjiazijiedian', command: 'INSERT_CHILD_NODE' },
  deleteNode: { icon: 'iconshanchu', command: 'REMOVE_NODE' },
  image: { icon: 'iconimage', event: 'showNodeImage' },
  link: { icon: 'iconchaolianjie', event: 'showNodeLink' },
  attachment: { icon: 'iconfujian', event: 'showNodeAttachment' },
  note: { icon: 'iconflow-Mark', event: 'showNodeNote' },
  tag: { icon: 'iconbiaoqian', event: 'openSidebar', args: ['nodeTagSidebar'] },
  summary: { icon: 'icongaikuozonglan', command: 'ADD_GENERALIZATION' },
  associativeLine: { icon: 'iconlianjiexian', event: 'createAssociativeLine' },
  outerFrame: { icon: 'iconwaikuang', command: 'ADD_OUTER_FRAME' },
})

const defaultBtnList = [
  'siblingNode',
  'childNode',
  'associativeLine',
  'summary',
  'outerFrame',
  'image',
  'back',
  'forward',
  'painter',
  'deleteNode',
  'link',
  'attachment',
  'note',
  'tag',
]

const toolbarContainerRef = ref(null)
const toolbarRef = ref(null)
const importRef = ref(null)
const { activeNodes } = useMindMapActiveNodes({
  onMindMapChange: resetToolbarMindMapState,
})
const backEnd = ref(true)
const forwardEnd = ref(true)
const isInPainter = ref(false)
const horizontalList = ref([])
const verticalList = ref([])
const showMoreBtn = ref(true)
const popoverShow = ref(false)
const toolbarLayoutRequests = createLatestRequestTracker()

let componentAlive = true
let computeThrottleTimer = null
let toolbarResizeObserver = null

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)

const noActive = computed(() => activeNodes.value.length <= 0)
const hasRoot = computed(() => activeNodes.value.some(n => n.isRoot))
const hasGeneralization = computed(() => activeNodes.value.some(n => n.isGeneralization))

const btnList = computed(() => {
  return [...defaultBtnList]
})

function exec(...args) {
  bus.emit('execCommand', ...args)
}

function isButtonDisabled(item) {
  if (isReadonly.value) return true
  if (item === 'back') return backEnd.value
  if (item === 'forward') return forwardEnd.value
  if (['painter', 'childNode', 'associativeLine', 'outerFrame'].includes(item)) {
    return noActive.value || hasGeneralization.value
  }
  if (['siblingNode', 'summary'].includes(item)) {
    return noActive.value || hasRoot.value || hasGeneralization.value
  }
  return ['deleteNode', 'image', 'link', 'attachment', 'note', 'tag'].includes(item)
    ? noActive.value
    : false
}

function isButtonActive(item) {
  return item === 'painter' && isInPainter.value
}

function executeToolbarItem(item) {
  if (isButtonDisabled(item)) return
  const definition = toolbarItemDefinitions[item]
  if (!definition) return
  if (definition.command) {
    exec(definition.command)
  } else if (definition.event) {
    bus.emit(definition.event, ...(definition.args || []))
  }
}

function isToolbarLayoutCurrent(requestId, toolbar) {
  return componentAlive
    && toolbarLayoutRequests.isCurrent(requestId)
    && toolbarRef.value === toolbar
}

function readCssPixel(value) {
  const number = Number.parseFloat(value)
  return Number.isFinite(number) ? number : 0
}

function measureToolbarWidth(toolbar) {
  return Array.from(toolbar.children).reduce((total, child) => {
    const style = window.getComputedStyle(child)
    return total
      + child.getBoundingClientRect().width
      + readCssPixel(style.marginLeft)
      + readCssPixel(style.marginRight)
  }, 0)
}

function getToolbarContainerWidth() {
  const measuredWidth = toolbarContainerRef.value?.getBoundingClientRect?.().width
  if (Number.isFinite(measuredWidth)) return Math.max(0, measuredWidth)
  return Math.max(0, window.innerWidth - 40)
}

// Measure every real candidate, including the overflow button when it is needed.
async function computeToolbarShow() {
  const toolbar = toolbarRef.value
  if (!componentAlive || !toolbar) return false

  const requestId = toolbarLayoutRequests.begin()
  const containerWidth = getToolbarContainerWidth()
  const all = [...btnList.value]
  const maxVisibleCount = props.embedded ? Math.min(8, all.length) : all.length
  const candidateWidths = []

  popoverShow.value = false
  for (let candidateCount = 0; candidateCount <= maxVisibleCount; candidateCount += 1) {
    if (!isToolbarLayoutCurrent(requestId, toolbar)) return false

    horizontalList.value = all.slice(0, candidateCount)
    verticalList.value = all.slice(candidateCount)
    showMoreBtn.value = candidateCount < all.length
    await nextTick()

    if (!isToolbarLayoutCurrent(requestId, toolbar)) return false
    candidateWidths.push(measureToolbarWidth(toolbar))
  }

  if (!isToolbarLayoutCurrent(requestId, toolbar)) return false
  const fittingCount = selectLargestFittingToolbarCount(candidateWidths, containerWidth)
  horizontalList.value = all.slice(0, fittingCount)
  verticalList.value = all.slice(fittingCount)
  showMoreBtn.value = fittingCount < all.length
  return true
}

function scheduleToolbarLayout() {
  if (!componentAlive) return
  clearTimeout(computeThrottleTimer)
  computeThrottleTimer = setTimeout(() => {
    computeThrottleTimer = null
    void computeToolbarShow()
  }, 80)
}

function resetToolbarMindMapState() {
  backEnd.value = true
  forwardEnd.value = true
  isInPainter.value = false
  popoverShow.value = false
}

function onBackForward(index, len, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, store.mindMap)) return
  backEnd.value = index <= 0
  forwardEnd.value = index >= len - 1
}

function onPainterStart(sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, store.mindMap)) return
  isInPainter.value = true
}

function onPainterEnd(sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, store.mindMap)) return
  isInPainter.value = false
}

function onNodeNoteDblclick(node, e, _noteElement, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, store.mindMap)) return
  if (node?.mindMap && node.mindMap !== store.mindMap) return
  if (isReadonly.value) return
  e?.stopPropagation?.()
  bus.emit('showNodeNote', node)
}

watch(btnList, () => {
  scheduleToolbarLayout()
}, { deep: true })

onMounted(() => {
  void computeToolbarShow()
  if (typeof ResizeObserver !== 'undefined' && toolbarContainerRef.value) {
    toolbarResizeObserver = new ResizeObserver(scheduleToolbarLayout)
    toolbarResizeObserver.observe(toolbarContainerRef.value)
  } else {
    window.addEventListener('resize', scheduleToolbarLayout)
  }
  bus.on('back_forward', onBackForward)
  bus.on('painter_start', onPainterStart)
  bus.on('painter_end', onPainterEnd)
  bus.on('node_note_dblclick', onNodeNoteDblclick)
})

onBeforeUnmount(() => {
  componentAlive = false
  toolbarLayoutRequests.invalidate()
  toolbarResizeObserver?.disconnect()
  toolbarResizeObserver = null
  window.removeEventListener('resize', scheduleToolbarLayout)
  clearTimeout(computeThrottleTimer)
  bus.off('back_forward', onBackForward)
  bus.off('painter_start', onPainterStart)
  bus.off('painter_end', onPainterEnd)
  bus.off('node_note_dblclick', onNodeNoteDblclick)
})
</script>

<style lang="scss" scoped>
.toolbarContainer {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  pointer-events: none;

  &.embedded {
    position: static;
    inset: auto;
    z-index: auto;
    min-width: 0;
    flex: 1;
    overflow: hidden;

    .toolbar {
      min-width: 0;
      padding: 0;
      justify-content: center;

      .toolbarBlock {
        gap: 0;
        margin-right: 4px;
        padding: 0 5px 0 0;
        border: 0;
        border-radius: 0;
        background: transparent;
        box-shadow: none;

        &::after {
          content: '';
          position: absolute;
          top: 50%;
          right: 0;
          width: 1px;
          height: 20px;
          background: #e1e4e8;
          transform: translateY(-50%);
        }

        &:last-of-type {
          margin-right: 0;
          padding-right: 0;

          &::after {
            display: none;
          }
        }
      }

      .toolbarBtn {
        position: relative;
        min-width: 0;
        height: 32px;
        margin-right: 1px;
        padding: 0 6px;
        border-radius: 6px;
        color: #646a73;
        flex-direction: row;
        align-items: center;
        justify-content: center;
        gap: 4px;
        transition: background 0.15s ease, color 0.15s ease;

        &:hover:not(.disabled) {
          color: #1f2329;
          background: #f0f2f5;

          .icon {
            background: transparent;
          }
        }

        &.active {
          color: #3370ff;
          background: #edf4ff;

          .icon {
            background: transparent;
          }
        }

        &.disabled,
        &:disabled {
          color: #aeb4bd;
        }

        .icon {
          height: 18px;
          padding: 0;
          border: 0;
          background: transparent;
          color: inherit;
          font-size: 15px;
        }

        .text {
          margin-top: 0;
          color: inherit;
          font-size: 11px;
          line-height: 16px;
          white-space: nowrap;
        }

        &.dividerBefore {
          margin-left: 7px;

          &::before {
            content: '';
            position: absolute;
            top: 7px;
            bottom: 7px;
            left: -4px;
            width: 1px;
            background: #e1e4e8;
          }
        }
      }
    }

    &.isDark .toolbar {
      .toolbarBlock {
        background: transparent;
        border-color: transparent;

        &::after {
          background: #3d4046;
        }
      }

      .toolbarBtn:hover:not(.disabled) {
        background: rgba(255, 255, 255, 0.07);
      }
    }
  }

  &.isDark {
    .toolbar {
      color: hsla(0, 0%, 100%, 0.9);

      .toolbarBlock {
        background-color: hsla(210, 10%, 14%, 0.95);
        border-color: rgba(255, 255, 255, 0.08);
      }

      .toolbarBtn {
        .icon {
          background: transparent;
          border-color: transparent;
        }

        &:hover {
          &:not(.disabled) {
            .icon {
              background: hsla(0, 0%, 100%, 0.05);
            }
          }
        }

        &.disabled,
        &:disabled {
          color: #54595f;
        }
      }
    }
  }

  .toolbar {
    display: flex;
    justify-content: center;
    font-size: 12px;
    font-family: PingFangSC-Regular, PingFang SC;
    font-weight: 400;
    color: rgba(26, 26, 26, 0.8);
    padding: 10px 0;
    pointer-events: auto;

    .toolbarBlock {
      display: flex;
      background-color: hsla(0, 0%, 100%, 0.95);
      padding: 10px 20px;
      border-radius: 6px;
      box-shadow: 0 2px 16px 0 rgba(0, 0, 0, 0.06);
      border: 1px solid rgba(0, 0, 0, 0.06);
      margin-right: 20px;
      flex-shrink: 0;
      position: relative;

      &:last-of-type {
        margin-right: 0;
      }
    }

    .toolbarBtn {
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      display: flex;
      justify-content: center;
      flex-direction: column;
      cursor: pointer;
      margin-right: 20px;

      &:last-of-type {
        margin-right: 0;
      }

      &:hover {
        &:not(.disabled) {
          .icon {
            background: #f5f5f5;
          }
        }
      }

      &:focus-visible {
        outline: 2px solid #3370ff;
        outline-offset: 3px;
        border-radius: 5px;
      }

      &.active {
        .icon {
          background: #f5f5f5;
        }
      }

      &.disabled,
      &:disabled {
        color: #bcbcbc;
        cursor: not-allowed;
        pointer-events: none;
      }

      .icon {
        display: flex;
        height: 26px;
        background: #fff;
        border-radius: 4px;
        border: 1px solid #e9e9e9;
        justify-content: center;
        flex-direction: column;
        text-align: center;
        padding: 0 5px;
      }

      .text {
        margin-top: 3px;
        text-align: center;
      }
    }
  }
}

.toolbarNodeBtnList {
  display: flex;

  &.v {
    display: block;
    width: 120px;
    flex-wrap: wrap;

    .toolbarBtn {
      flex-direction: row;
      justify-content: flex-start;
      margin-bottom: 10px;
      width: 100%;
      margin-right: 0;

      &:last-of-type {
        margin-bottom: 0;
      }

      .icon {
        margin-right: 10px;
      }

      .text {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
    }

    .overflowFileOperations {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid #eef0f3;
    }
  }
}

@media (max-width: 1600px) {
  .toolbarContainer.embedded .toolbar .toolbarBtn {
    width: 32px;
    padding: 0;

    .text {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }
  }
}
</style>
