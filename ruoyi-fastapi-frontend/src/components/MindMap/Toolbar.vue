<template>
  <div class="toolbarContainer" :class="{ isDark: isDark }">
    <div class="toolbar" ref="toolbarRef">
      <!-- Node operation buttons -->
      <div class="toolbarBlock">
        <div class="toolbarNodeBtnList">
          <template v-for="item in horizontalList" :key="item">
            <!-- Back -->
            <div
              v-if="item === 'back'"
              class="toolbarBtn"
              :class="{ disabled: isReadonly || backEnd }"
              @click="exec('BACK')"
            >
              <span class="icon iconfont iconhoutui-shi"></span>
              <span class="text">回退</span>
            </div>
            <!-- Forward -->
            <div
              v-if="item === 'forward'"
              class="toolbarBtn"
              :class="{ disabled: isReadonly || forwardEnd }"
              @click="exec('FORWARD')"
            >
              <span class="icon iconfont iconqianjin1"></span>
              <span class="text">前进</span>
            </div>
            <!-- Painter -->
            <div
              v-if="item === 'painter'"
              class="toolbarBtn"
              :class="{
                disabled: noActive || hasGeneralization,
                active: isInPainter
              }"
              @click="bus.emit('startPainter')"
            >
              <span class="icon iconfont iconjiedian"></span>
              <span class="text">格式刷</span>
            </div>
            <!-- Sibling Node -->
            <div
              v-if="item === 'siblingNode'"
              class="toolbarBtn"
              :class="{ disabled: noActive || hasRoot || hasGeneralization }"
              @click="exec('INSERT_NODE')"
            >
              <span class="icon iconfont iconjiedian"></span>
              <span class="text">同级节点</span>
            </div>
            <!-- Child Node -->
            <div
              v-if="item === 'childNode'"
              class="toolbarBtn"
              :class="{ disabled: noActive || hasGeneralization }"
              @click="exec('INSERT_CHILD_NODE')"
            >
              <span class="icon iconfont icontianjiazijiedian"></span>
              <span class="text">子节点</span>
            </div>
            <!-- Delete Node -->
            <div
              v-if="item === 'deleteNode'"
              class="toolbarBtn"
              :class="{ disabled: noActive }"
              @click="exec('REMOVE_NODE')"
            >
              <span class="icon iconfont iconshanchu"></span>
              <span class="text">删除节点</span>
            </div>
            <!-- Image -->
            <div
              v-if="item === 'image'"
              class="toolbarBtn"
              :class="{ disabled: noActive }"
              @click="bus.emit('showNodeImage')"
            >
              <span class="icon iconfont iconimage"></span>
              <span class="text">图片</span>
            </div>
            <!-- Icon -->
            <div
              v-if="item === 'icon'"
              class="toolbarBtn"
              :class="{ disabled: noActive }"
              @click="showNodeIcon"
            >
              <span class="icon iconfont iconxiaolian"></span>
              <span class="text">图标</span>
            </div>
            <!-- Link -->
            <div
              v-if="item === 'link'"
              class="toolbarBtn"
              :class="{ disabled: noActive }"
              @click="bus.emit('showNodeLink')"
            >
              <span class="icon iconfont iconchaolianjie"></span>
              <span class="text">超链接</span>
            </div>
            <!-- Note -->
            <div
              v-if="item === 'note'"
              class="toolbarBtn"
              :class="{ disabled: noActive }"
              @click="bus.emit('showNodeNote')"
            >
              <span class="icon iconfont iconflow-Mark"></span>
              <span class="text">备注</span>
            </div>
            <!-- Tag -->
            <div
              v-if="item === 'tag'"
              class="toolbarBtn"
              :class="{ disabled: noActive }"
              @click="bus.emit('showNodeTag')"
            >
              <span class="icon iconfont iconbiaoqian"></span>
              <span class="text">标签</span>
            </div>
            <!-- Summary -->
            <div
              v-if="item === 'summary'"
              class="toolbarBtn"
              :class="{ disabled: noActive || hasRoot || hasGeneralization }"
              @click="exec('ADD_GENERALIZATION')"
            >
              <span class="icon iconfont icongaikuozonglan"></span>
              <span class="text">概要</span>
            </div>
            <!-- Associative Line -->
            <div
              v-if="item === 'associativeLine'"
              class="toolbarBtn"
              :class="{ disabled: noActive || hasGeneralization }"
              @click="bus.emit('createAssociativeLine')"
            >
              <span class="icon iconfont iconlianjiexian"></span>
              <span class="text">关联线</span>
            </div>
            <!-- Outer Frame -->
            <div
              v-if="item === 'outerFrame'"
              class="toolbarBtn"
              :class="{ disabled: noActive || hasGeneralization }"
              @click="exec('ADD_OUTER_FRAME')"
            >
              <span class="icon iconfont iconwaikuang"></span>
              <span class="text">外框</span>
            </div>
          </template>
        </div>
        <!-- More button (overflow items) -->
        <el-popover
          v-model:visible="popoverShow"
          placement="bottom-end"
          :width="120"
          trigger="hover"
          v-if="showMoreBtn"
          :style="{ marginLeft: horizontalList.length > 0 ? '20px' : 0 }"
        >
          <template #reference>
            <div class="toolbarBtn">
              <span class="icon iconfont icongongshi"></span>
              <span class="text">更多</span>
            </div>
          </template>
          <div class="toolbarNodeBtnList v" @click="popoverShow = false">
            <template v-for="item in verticalList" :key="item">
              <div
                v-if="item === 'back'"
                class="toolbarBtn"
                :class="{ disabled: isReadonly || backEnd }"
                @click="exec('BACK')"
              >
                <span class="icon iconfont iconhoutui-shi"></span>
                <span class="text">回退</span>
              </div>
              <div
                v-if="item === 'forward'"
                class="toolbarBtn"
                :class="{ disabled: isReadonly || forwardEnd }"
                @click="exec('FORWARD')"
              >
                <span class="icon iconfont iconqianjin1"></span>
                <span class="text">前进</span>
              </div>
              <div
                v-if="item === 'painter'"
                class="toolbarBtn"
                :class="{ disabled: noActive || hasGeneralization, active: isInPainter }"
                @click="bus.emit('startPainter')"
              >
                <span class="icon iconfont iconjiedian"></span>
                <span class="text">格式刷</span>
              </div>
              <div
                v-if="item === 'siblingNode'"
                class="toolbarBtn"
                :class="{ disabled: noActive || hasRoot || hasGeneralization }"
                @click="exec('INSERT_NODE')"
              >
                <span class="icon iconfont iconjiedian"></span>
                <span class="text">同级节点</span>
              </div>
              <div
                v-if="item === 'childNode'"
                class="toolbarBtn"
                :class="{ disabled: noActive || hasGeneralization }"
                @click="exec('INSERT_CHILD_NODE')"
              >
                <span class="icon iconfont icontianjiazijiedian"></span>
                <span class="text">子节点</span>
              </div>
              <div
                v-if="item === 'deleteNode'"
                class="toolbarBtn"
                :class="{ disabled: noActive }"
                @click="exec('REMOVE_NODE')"
              >
                <span class="icon iconfont iconshanchu"></span>
                <span class="text">删除节点</span>
              </div>
              <div
                v-if="item === 'image'"
                class="toolbarBtn"
                :class="{ disabled: noActive }"
                @click="bus.emit('showNodeImage')"
              >
                <span class="icon iconfont iconimage"></span>
                <span class="text">图片</span>
              </div>
              <div
                v-if="item === 'icon'"
                class="toolbarBtn"
                :class="{ disabled: noActive }"
                @click="showNodeIcon"
              >
                <span class="icon iconfont iconxiaolian"></span>
                <span class="text">图标</span>
              </div>
              <div
                v-if="item === 'link'"
                class="toolbarBtn"
                :class="{ disabled: noActive }"
                @click="bus.emit('showNodeLink')"
              >
                <span class="icon iconfont iconchaolianjie"></span>
                <span class="text">超链接</span>
              </div>
              <div
                v-if="item === 'note'"
                class="toolbarBtn"
                :class="{ disabled: noActive }"
                @click="bus.emit('showNodeNote')"
              >
                <span class="icon iconfont iconflow-Mark"></span>
                <span class="text">备注</span>
              </div>
              <div
                v-if="item === 'tag'"
                class="toolbarBtn"
                :class="{ disabled: noActive }"
                @click="bus.emit('showNodeTag')"
              >
                <span class="icon iconfont iconbiaoqian"></span>
                <span class="text">标签</span>
              </div>
              <div
                v-if="item === 'summary'"
                class="toolbarBtn"
                :class="{ disabled: noActive || hasRoot || hasGeneralization }"
                @click="exec('ADD_GENERALIZATION')"
              >
                <span class="icon iconfont icongaikuozonglan"></span>
                <span class="text">概要</span>
              </div>
              <div
                v-if="item === 'associativeLine'"
                class="toolbarBtn"
                :class="{ disabled: noActive || hasGeneralization }"
                @click="bus.emit('createAssociativeLine')"
              >
                <span class="icon iconfont iconlianjiexian"></span>
                <span class="text">关联线</span>
              </div>
              <div
                v-if="item === 'outerFrame'"
                class="toolbarBtn"
                :class="{ disabled: noActive || hasGeneralization }"
                @click="exec('ADD_OUTER_FRAME')"
              >
                <span class="icon iconfont iconwaikuang"></span>
                <span class="text">外框</span>
              </div>
            </template>
          </div>
        </el-popover>
      </div>
      <!-- File operations block -->
      <div class="toolbarBlock">
        <div class="toolbarBtn" @click="bus.emit('showImport')">
          <span class="icon iconfont icondaoru"></span>
          <span class="text">导入</span>
        </div>
        <div
          class="toolbarBtn"
          @click="bus.emit('showExport')"
          style="margin-right: 0;"
        >
          <span class="icon iconfont iconexport"></span>
          <span class="text">导出</span>
        </div>
      </div>
    </div>
    <NodeImage />
    <NodeHyperlink />
    <NodeIcon />
    <NodeNote />
    <NodeTag />
    <ExportDialog />
    <ImportDialog ref="importRef" />
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { store, actions } from './useStore'
import NodeImage from './NodeImage.vue'
import NodeHyperlink from './NodeHyperlink.vue'
import NodeIcon from './NodeIconSidebar.vue'
import NodeNote from './NodeNote.vue'
import NodeTag from './NodeTag.vue'
import ExportDialog from './Export.vue'
import ImportDialog from './Import.vue'

const defaultBtnList = [
  'back',
  'forward',
  'painter',
  'siblingNode',
  'childNode',
  'deleteNode',
  'image',
  'icon',
  'link',
  'note',
  'tag',
  'summary',
  'associativeLine',
  'outerFrame',
]

const toolbarRef = ref(null)
const importRef = ref(null)
const activeNodes = ref([])
const backEnd = ref(true)
const forwardEnd = ref(true)
const isReadonly = ref(false)
const isInPainter = ref(false)
const horizontalList = ref([])
const verticalList = ref([])
const showMoreBtn = ref(true)
const popoverShow = ref(false)

const isDark = computed(() => store.localConfig.isDark)

const noActive = computed(() => activeNodes.value.length <= 0)
const hasRoot = computed(() => activeNodes.value.some(n => n.isRoot))
const hasGeneralization = computed(() => activeNodes.value.some(n => n.isGeneralization))

const btnList = computed(() => {
  return [...defaultBtnList]
})

function exec(...args) {
  bus.emit('execCommand', ...args)
}

function showNodeIcon() {
  bus.emit('close_node_icon_toolbar')
  actions.setActiveSidebar('nodeIconSidebar')
}

// Compute how many buttons fit horizontally
function computeToolbarShow() {
  if (!toolbarRef.value) return
  const windowWidth = window.innerWidth - 40
  const all = [...btnList.value]
  let index = 1

  const loopCheck = () => {
    if (index > all.length) return done()
    horizontalList.value = all.slice(0, index)
    nextTick(() => {
      if (!toolbarRef.value) return done()
      const width = toolbarRef.value.getBoundingClientRect().width
      if (width < windowWidth) {
        index++
        loopCheck()
      } else if (index > 0 && width > windowWidth) {
        index--
        horizontalList.value = all.slice(0, index)
        done()
      }
    })
  }
  const done = () => {
    verticalList.value = all.slice(index)
    showMoreBtn.value = verticalList.value.length > 0
  }
  loopCheck()
}

let computeThrottleTimer = null
function computeToolbarShowThrottle() {
  clearTimeout(computeThrottleTimer)
  computeThrottleTimer = setTimeout(computeToolbarShow, 300)
}

// Bus event handlers
function onNodeActive(_node, list) {
  activeNodes.value = list ? [...list] : []
}

function onBackForward(index, len) {
  backEnd.value = index <= 0
  forwardEnd.value = index >= len - 1
}

function onModeChange(mode) {
  isReadonly.value = mode === 'readonly'
}

function onPainterStart() {
  isInPainter.value = true
}

function onPainterEnd() {
  isInPainter.value = false
}

function onNodeNoteDblclick(node, e) {
  e?.stopPropagation?.()
  bus.emit('showNodeNote', node)
}

watch(btnList, () => {
  computeToolbarShow()
}, { deep: true })

onMounted(() => {
  computeToolbarShow()
  window.addEventListener('resize', computeToolbarShowThrottle)
  bus.on('node_active', onNodeActive)
  bus.on('back_forward', onBackForward)
  bus.on('mode_change', onModeChange)
  bus.on('painter_start', onPainterStart)
  bus.on('painter_end', onPainterEnd)
  bus.on('node_note_dblclick', onNodeNoteDblclick)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', computeToolbarShowThrottle)
  clearTimeout(computeThrottleTimer)
  bus.off('node_active', onNodeActive)
  bus.off('back_forward', onBackForward)
  bus.off('mode_change', onModeChange)
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

  &.isDark {
    .toolbar {
      color: hsla(0, 0%, 100%, 0.9);

      .toolbarBlock {
        background-color: hsla(210, 10%, 14%, 0.95);
        /* 临时禁用 backdrop-filter 验证性能问题 */
        /* backdrop-filter: blur(10px); */
        /* -webkit-backdrop-filter: blur(10px); */
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

        &.disabled {
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
      /* 临时禁用 backdrop-filter 验证性能问题 */
      /* backdrop-filter: blur(10px); */
      /* -webkit-backdrop-filter: blur(10px); */
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

      &.active {
        .icon {
          background: #f5f5f5;
        }
      }

      &.disabled {
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
  }
}
</style>
