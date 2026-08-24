<template>
  <div class="nodeStylePanel" :class="{ embedded: props.embedded }">
    <div
      class="styleBox"
      :class="{ isDark: isDark }"
      v-if="activeNodes.length > 0"
    >
      <div class="sidebarContent customScrollbar">
        <!-- 文字 -->
        <details class="styleSection" open>
          <summary class="title noTop">
            <span>文字</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody">
            <div class="fieldBlock">
              <span class="fieldLabel">字体</span>
              <el-select
                size="small"
                style="width: 100%"
                v-model="style.fontFamily"
                placeholder="选择字体"
                aria-label="字体"
                @change="update('fontFamily')"
              >
                <el-option
                  v-for="item in fontFamilyList"
                  :key="item.value"
                  :label="item.name"
                  :value="item.value"
                  :style="{ fontFamily: item.value }"
                />
              </el-select>
            </div>

            <div class="typographyToolbar" role="group" aria-label="文字样式">
              <el-select
                class="fontSizeSelect"
                size="small"
                v-model="style.fontSize"
                placeholder="字号"
                aria-label="字号"
                @change="update('fontSize')"
              >
                <el-option
                  v-for="item in fontSizeList"
                  :key="item"
                  :label="item"
                  :value="item"
                  :style="{ fontSize: item + 'px' }"
                />
              </el-select>
              <div class="btnGroup compactButtonGroup">
                <el-tooltip content="加粗" placement="bottom">
                  <button
                    class="styleBtn"
                    type="button"
                    aria-label="加粗"
                    :aria-pressed="style.fontWeight === 'bold'"
                    :disabled="store.isReadonly"
                    :class="{ actived: style.fontWeight === 'bold' }"
                    @click="toggleFontWeight"
                  >B</button>
                </el-tooltip>
                <el-tooltip content="斜体" placement="bottom">
                  <button
                    class="styleBtn i"
                    type="button"
                    aria-label="斜体"
                    :aria-pressed="style.fontStyle === 'italic'"
                    :disabled="store.isReadonly"
                    :class="{ actived: style.fontStyle === 'italic' }"
                    @click="toggleFontStyle"
                  >I</button>
                </el-tooltip>
                <el-tooltip content="下划线" placement="bottom">
                  <button
                    class="styleBtn u"
                    type="button"
                    aria-label="下划线"
                    :aria-pressed="style.textDecoration === 'underline'"
                    :disabled="store.isReadonly"
                    :class="{ actived: style.textDecoration === 'underline' }"
                    @click="toggleTextDecoration('underline')"
                  >U</button>
                </el-tooltip>
                <el-tooltip content="中划线" placement="bottom">
                  <button
                    class="styleBtn strike"
                    type="button"
                    aria-label="中划线"
                    :aria-pressed="style.textDecoration === 'line-through'"
                    :disabled="store.isReadonly"
                    :class="{ actived: style.textDecoration === 'line-through' }"
                    @click="toggleTextDecoration('line-through')"
                  >S</button>
                </el-tooltip>
                <el-tooltip content="减小字号" placement="bottom">
                  <button
                    class="styleBtn fontStepBtn"
                    type="button"
                    aria-label="减小字号"
                    :disabled="store.isReadonly"
                    @click="stepFontSize(-1)"
                  >A<sup>−</sup></button>
                </el-tooltip>
                <el-tooltip content="增大字号" placement="bottom">
                  <button
                    class="styleBtn fontStepBtn"
                    type="button"
                    aria-label="增大字号"
                    :disabled="store.isReadonly"
                    @click="stepFontSize(1)"
                  >A<sup>+</sup></button>
                </el-tooltip>
              </div>
            </div>

            <div class="fieldBlock colorPaletteBlock">
              <span class="fieldLabel">文字颜色</span>
              <div class="colorPaletteControls">
                <div class="quickColorList" role="group" aria-label="常用文字颜色">
                  <button
                    v-for="color in fontQuickColors"
                    :key="color"
                    class="quickColorButton"
                    :class="{ active: normalizeColor(style.color) === normalizeColor(color) }"
                    type="button"
                    :aria-label="`文字颜色 ${color}`"
                    :aria-pressed="normalizeColor(style.color) === normalizeColor(color)"
                    :disabled="store.isReadonly"
                    @click="changeFontColor(color)"
                  >
                    <span class="quickColorSwatch" :style="{ backgroundColor: color }"></span>
                  </button>
                </div>
                <el-popover placement="bottom-end" trigger="click" :width="260">
                  <template #reference>
                    <button
                      class="moreColorButton"
                      type="button"
                      aria-label="选择更多文字颜色"
                      :disabled="store.isReadonly"
                    >
                      <span>更多</span>
                      <el-icon><ArrowDown /></el-icon>
                    </button>
                  </template>
                  <Color :color="style.color" @change="changeFontColor" />
                </el-popover>
              </div>
            </div>

            <div class="fieldBlock">
              <span class="fieldLabel">对齐</span>
              <div class="segmentedControl" role="group" aria-label="文字对齐方式">
                <button
                  v-for="item in alignList"
                  :key="item.value"
                  class="segmentButton"
                  type="button"
                  :aria-label="item.name"
                  :aria-pressed="style.textAlign === item.value"
                  :disabled="store.isReadonly"
                  :class="{ active: style.textAlign === item.value }"
                  @click="setTextAlign(item.value)"
                >{{ alignShortName[item.value] }}</button>
              </div>
            </div>
          </div>
        </details>
        <!-- 边框 -->
        <details class="styleSection" open>
          <summary class="title">
            <span>边框</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody controlGrid">
          <div class="fieldBlock">
            <span class="fieldLabel">颜色</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <ColorTrigger :color="style.borderColor" label="选择节点边框颜色" :width="124" />
              </template>
              <Color
                :color="style.borderColor"
                @change="changeBorderColor"
              />
            </el-popover>
          </div>
          <div class="fieldBlock">
            <span class="fieldLabel">宽度</span>
            <el-select
              size="small"
              style="width: 100%"
              v-model="style.borderWidth"
              placeholder="边框宽度"
              aria-label="边框宽度"
              @change="update('borderWidth')"
            >
              <el-option
                v-for="item in borderWidthList"
                :key="item"
                :label="`${item}px`"
                :value="item"
              >
                <span
                  v-if="item > 0"
                  class="borderLine"
                  :class="{ isDark: isDark }"
                  :style="{ height: item + 'px' }"
                ></span>
              </el-option>
            </el-select>
          </div>
          <div class="fieldBlock fullSpanField">
            <span class="fieldLabel">样式</span>
            <el-select
              size="small"
              style="width: 100%"
              v-model="style.borderDasharray"
              placeholder="边框样式"
              aria-label="边框样式"
              @change="update('borderDasharray')"
            >
              <el-option
                v-for="item in borderDasharrayList"
                :key="item.value"
                :label="item.name"
                :value="item.value"
              >
                <svg width="120" height="34">
                  <line
                    x1="10" y1="17" x2="110" y2="17"
                    stroke-width="2"
                    :stroke="style.borderDasharray === item.value ? '#409eff' : isDark ? '#fff' : '#000'"
                    :stroke-dasharray="item.value"
                  />
                </svg>
              </el-option>
            </el-select>
          </div>
          <div class="fieldBlock fullSpanField" v-show="style.shape === 'rectangle'">
            <span class="fieldLabel">圆角</span>
            <el-select
              size="small"
              style="width: 100%"
              v-model="style.borderRadius"
              placeholder="圆角"
              aria-label="圆角"
              @change="update('borderRadius')"
            >
              <el-option
                v-for="item in borderRadiusList"
                :key="item"
                :label="`${item}px`"
                :value="item"
              />
            </el-select>
          </div>
          </div>
        </details>
        <!-- 填充 -->
        <details class="styleSection" open>
          <summary class="title">
            <span>填充</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody">
        <div class="fillControlRow">
          <div class="fieldBlock fillColorField">
            <span class="fieldLabel">颜色</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <ColorTrigger :color="style.fillColor" label="选择节点填充颜色" :width="124" />
              </template>
              <Color
                :color="style.fillColor"
                @change="changeFillColor"
              />
            </el-popover>
          </div>
          <label class="gradientToggle">
            <span>渐变</span>
            <el-checkbox
              v-model="style.gradientStyle"
              @change="update('gradientStyle')"
            />
          </label>
        </div>
        <div class="row" v-if="style.gradientStyle">
          <div class="rowItem">
            <span class="name">起始</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <ColorTrigger :color="style.startColor" label="选择渐变起始颜色" />
              </template>
              <Color
                :color="style.startColor"
                @change="changeStartColor"
              />
            </el-popover>
          </div>
          <div class="rowItem">
            <span class="name">结束</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <ColorTrigger :color="style.endColor" label="选择渐变结束颜色" />
              </template>
              <Color
                :color="style.endColor"
                @change="changeEndColor"
              />
            </el-popover>
          </div>
          <div class="rowItem">
            <span class="name">方向</span>
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.linearGradientDir"
              placeholder=""
              @change="update('linearGradientDir')"
            >
              <el-option
                v-for="item in linearGradientDirList"
                :key="item.value"
                :label="item.name"
                :value="item.value"
              />
            </el-select>
          </div>
        </div>
          </div>
        </details>
        <!-- 形状 -->
        <details class="styleSection" open>
          <summary class="title">
            <span>形状</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody">
        <div class="fieldBlock">
            <span class="fieldLabel">形状</span>
            <el-select
              size="small"
              style="width: 100%"
              v-model="style.shape"
              placeholder="选择形状"
              aria-label="节点形状"
              @change="update('shape')"
            >
              <el-option
                v-for="item in shapeListData"
                :key="item.value"
                :label="item.name"
                :value="item.value"
                style="display: flex; justify-content: center; align-items: center;"
              >
                <svg
                  :width="item.width || 60"
                  :height="item.height || 26"
                  style="margin-top: 5px"
                >
                  <path
                    :d="shapeListMapData[item.value]"
                    fill="none"
                    :stroke="style.shape === item.value ? '#409eff' : isDark ? '#fff' : '#000'"
                    stroke-width="2"
                  />
                </svg>
              </el-option>
            </el-select>
        </div>
          </div>
        </details>
        <!-- 线条 -->
        <details class="styleSection">
          <summary class="title">
            <span>线条</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody">
        <div class="row">
          <div class="rowItem">
            <span class="name">颜色</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <ColorTrigger :color="style.lineColor" label="选择节点线条颜色" :width="80" />
              </template>
              <Color
                :color="style.lineColor"
                @change="changeLineColor"
              />
            </el-popover>
          </div>
          <div class="rowItem">
            <span class="name">样式</span>
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.lineDasharray"
              placeholder=""
              @change="update('lineDasharray')"
            >
              <el-option
                v-for="item in borderDasharrayList"
                :key="item.value"
                :label="item.name"
                :value="item.value"
              >
                <svg width="120" height="34">
                  <line
                    x1="10" y1="17" x2="110" y2="17"
                    stroke-width="2"
                    :stroke="style.lineDasharray === item.value ? '#409eff' : isDark ? '#fff' : '#000'"
                    :stroke-dasharray="item.value"
                  />
                </svg>
              </el-option>
            </el-select>
          </div>
        </div>
        <div class="row">
          <div class="rowItem">
            <span class="name">宽度</span>
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.lineWidth"
              placeholder=""
              @change="update('lineWidth')"
            >
              <el-option
                v-for="item in borderWidthList"
                :key="item"
                :label="item"
                :value="item"
              >
                <span
                  v-if="item > 0"
                  class="borderLine"
                  :class="{ isDark: isDark }"
                  :style="{ height: item + 'px' }"
                ></span>
              </el-option>
            </el-select>
          </div>
          <div class="rowItem">
            <span class="name">箭头位置</span>
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.lineMarkerDir"
              placeholder=""
              @change="update('lineMarkerDir')"
            >
              <el-option key="start" label="头部" value="start" />
              <el-option key="end" label="尾部" value="end" />
            </el-select>
          </div>
        </div>
          </div>
        </details>
        <!-- 节点内边距 -->
        <details class="styleSection">
          <summary class="title">
            <span>节点内边距</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody">
        <div class="row noBottom">
          <div class="rowItem">
            <span class="name">水平</span>
            <el-slider
              style="width: 200px"
              v-model="style.paddingX"
              @change="update('paddingX')"
            />
          </div>
        </div>
        <div class="row">
          <div class="rowItem">
            <span class="name">垂直</span>
            <el-slider
              style="width: 200px"
              v-model="style.paddingY"
              @change="update('paddingY')"
            />
          </div>
        </div>
          </div>
        </details>
        <!-- 节点图片布局 -->
        <details class="styleSection">
          <summary class="title">
            <span>图片</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody">
        <div class="row">
          <div class="rowItem">
            <span class="name">布局</span>
            <el-radio-group
              v-model="style.imgPlacement"
              size="small"
              @change="update('imgPlacement')"
            >
              <el-radio-button label="top">上</el-radio-button>
              <el-radio-button label="bottom">下</el-radio-button>
              <el-radio-button label="left">左</el-radio-button>
              <el-radio-button label="right">右</el-radio-button>
            </el-radio-group>
          </div>
        </div>
          </div>
        </details>
        <!-- 节点标签布局 -->
        <details class="styleSection">
          <summary class="title">
            <span>标签</span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="sectionBody">
        <div class="row">
          <div class="rowItem">
            <span class="name">布局</span>
            <el-radio-group
              v-model="style.tagPlacement"
              size="small"
              @change="update('tagPlacement')"
            >
              <el-radio-button label="right">右</el-radio-button>
              <el-radio-button label="bottom">下</el-radio-button>
            </el-radio-group>
          </div>
        </div>
          </div>
        </details>
      </div>
    </div>
    <div class="tipBox" v-else>
      <div class="tipIcon iconfont icontianjiazijiedian"></div>
      <div class="tipText">请选择一个节点</div>
    </div>
  </div>
</template>

<script setup>
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import Color from './Color.vue'
import ColorTrigger from './ColorTrigger.vue'
import { store } from './useStore'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'
import {
  fontFamilyList,
  fontSizeList,
  borderWidthList,
  borderDasharrayList,
  borderRadiusList,
  shapeList,
  shapeListMap,
  linearGradientDirList,
  alignList
} from './config'

const props = defineProps({
  mindMap: { type: Object, default: null },
  embedded: { type: Boolean, default: false }
})

const { activeNodes, syncActiveNodes } = useMindMapActiveNodes({
  resolveMindMap: () => props.mindMap,
})
const isDark = computed(() => store.localConfig.isDark)
const fontQuickColors = Object.freeze([
  '#000000',
  '#3370FF',
  '#F53F3F',
  '#FFB400',
  '#34C759',
  '#7A5AF8',
])
const alignShortName = Object.freeze({
  left: '左',
  center: '中',
  right: '右',
})

const style = reactive({
  shape: '',
  paddingX: 0,
  paddingY: 0,
  color: '',
  fontFamily: '',
  fontSize: '',
  textDecoration: '',
  fontWeight: '',
  fontStyle: '',
  borderWidth: '',
  borderColor: '',
  fillColor: '',
  borderDasharray: '',
  borderRadius: '',
  lineColor: '',
  lineDasharray: '',
  lineWidth: '',
  lineMarkerDir: '',
  gradientStyle: false,
  startColor: '',
  endColor: '',
  linearGradientDir: '',
  textAlign: '',
  imgPlacement: '',
  tagPlacement: ''
})

const shapeListData = computed(() => {
  const base = [...shapeList]
  if (props.mindMap && props.mindMap.extendShapeList) {
    props.mindMap.extendShapeList
      .filter(item => !['fishHead'].includes(item.name))
      .forEach(item => {
        base.push({
          width: '40px',
          name: item.nameShow,
          value: item.name
        })
      })
  }
  return base
})

const shapeListMapData = computed(() => {
  const map2 = {}
  if (props.mindMap && props.mindMap.extendShapeList) {
    props.mindMap.extendShapeList.forEach(item => {
      map2[item.name] = item.path
    })
  }
  return { ...shapeListMap, ...map2 }
})

function initNodeStyle() {
  if (activeNodes.value.length <= 0) return
  Object.keys(style).forEach(item => {
    style[item] = activeNodes.value[0].getStyle(item, false)
  })
  initLinearGradientDir()
}

function initLinearGradientDir() {
  const startDir = activeNodes.value[0].getStyle('startDir', false)
  const endDir = activeNodes.value[0].getStyle('endDir', false)
  if (!startDir || !endDir) return
  const target = linearGradientDirList.find(item => {
    return (
      item.start[0] === startDir[0] &&
      item.start[1] === startDir[1] &&
      item.end[0] === endDir[0] &&
      item.end[1] === endDir[1]
    )
  })
  if (target) {
    style.linearGradientDir = target.value
  }
}

function update(prop) {
  if (store.isReadonly) return
  if (prop === 'linearGradientDir') {
    const target = linearGradientDirList.find(item => {
      return item.value === style.linearGradientDir
    })
    if (target) {
      activeNodes.value.forEach(node => {
        node.setStyles({
          startDir: [...target.start],
          endDir: [...target.end]
        })
      })
    }
  } else {
    activeNodes.value.forEach(node => {
      node.setStyle(prop, style[prop])
    })
  }
}

function toggleFontWeight() {
  if (store.isReadonly) return
  style.fontWeight = style.fontWeight === 'bold' ? 'normal' : 'bold'
  update('fontWeight')
}

function toggleFontStyle() {
  if (store.isReadonly) return
  style.fontStyle = style.fontStyle === 'italic' ? 'normal' : 'italic'
  update('fontStyle')
}

function toggleTextDecoration(decoration) {
  if (store.isReadonly) return
  style.textDecoration = style.textDecoration === decoration ? 'none' : decoration
  update('textDecoration')
}

function stepFontSize(step) {
  if (store.isReadonly) return
  const current = Number(style.fontSize)
  const currentIndex = fontSizeList.indexOf(current)
  const closestIndex = currentIndex >= 0
    ? currentIndex
    : fontSizeList.findIndex(item => item >= current)
  const baseIndex = closestIndex >= 0 ? closestIndex : fontSizeList.length - 1
  const nextIndex = Math.min(fontSizeList.length - 1, Math.max(0, baseIndex + step))
  style.fontSize = fontSizeList[nextIndex]
  update('fontSize')
}

function setTextAlign(value) {
  if (store.isReadonly) return
  style.textAlign = value
  update('textAlign')
}

function changeFontColor(color) {
  if (store.isReadonly) return
  style.color = color
  update('color')
}

function changeBorderColor(color) {
  if (store.isReadonly) return
  style.borderColor = color
  update('borderColor')
}

function changeLineColor(color) {
  if (store.isReadonly) return
  style.lineColor = color
  update('lineColor')
}

function changeFillColor(color) {
  if (store.isReadonly) return
  style.fillColor = color
  update('fillColor')
}

function changeStartColor(color) {
  if (store.isReadonly) return
  style.startColor = color
  update('startColor')
}

function changeEndColor(color) {
  if (store.isReadonly) return
  style.endColor = color
  update('endColor')
}

function normalizeColor(value) {
  return String(value || '').trim().toLowerCase()
}

watch(activeNodes, (nodes) => {
  if (nodes.length <= 0) return
  const activeMindMap = props.mindMap
  nextTick(() => {
    if (activeMindMap === props.mindMap && activeNodes.value === nodes) initNodeStyle()
  })
}, { flush: 'sync' })

watch(() => store.activeSidebar, (val) => {
  if (val === 'nodeStyle') syncActiveNodes()
}, { immediate: true })
</script>

<style lang="less" scoped>
.nodeStylePanel {
  width: 100%;
  min-height: 100%;
}

.styleBox {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;

  &.isDark {
    .sidebarContent {
      .title {
        color: #fff;
      }

      .row {
        .rowItem {
          .name {
            color: hsla(0, 0%, 100%, 0.6);
          }
        }

        .styleBtn {
          background-color: #363b3f;
          color: hsla(0, 0%, 100%, 0.6);
          border-color: hsla(0, 0%, 100%, 0.1);
        }

        .quickColorButton {
          background: #30343a;
          border-color: #454950;
        }
      }

      .fieldLabel,
      .gradientToggle {
        color: hsla(0, 0%, 100%, 0.6);
      }

      .styleBtn,
      .segmentButton,
      .moreColorButton,
      .quickColorButton {
        background-color: #363b3f;
        color: hsla(0, 0%, 100%, 0.72);
        border-color: hsla(0, 0%, 100%, 0.12);
      }

      .segmentButton.active,
      .styleBtn.actived {
        color: #82a7ff;
        border-color: #4d73ff;
        background: rgba(77, 115, 255, 0.16);
      }
    }
  }

  .tab {
    flex-grow: 0;
    flex-shrink: 0;
    padding: 0 20px;
  }
}

.tipBox {
  width: 100%;
  min-height: 360px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: #666;

  .tipIcon {
    font-size: 54px;
    color: #c9cdd4;
    margin-bottom: 12px;
  }

  .tipText {
    color: #8f959e;
    font-size: 13px;
  }
}

.sidebarContent {
  padding: 18px 20px 22px;

  .styleSection {
    margin: 0;

    &[open] .sectionChevron {
      transform: rotate(0deg);
    }

    &:not([open]) {
      .title {
        margin-bottom: 0;
      }

      .sectionChevron {
        transform: rotate(180deg);
      }
    }
  }

  .title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding-top: 16px;
    border-top: 1px solid #eef0f3;
    font-size: 14px;
    font-family: PingFangSC-Medium, PingFang SC, sans-serif;
    font-weight: 600;
    color: #1f2329;
    margin-bottom: 13px;
    margin-top: 16px;
    list-style: none;
    cursor: pointer;
    user-select: none;

    &::-webkit-details-marker {
      display: none;
    }

    &:hover {
      color: #3370ff;
    }

    &.noTop {
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }

    .sectionChevron {
      color: #646a73;
      font-size: 13px;
      transition: transform 0.16s ease;
    }
  }

  .sectionBody {
    min-width: 0;
  }

  .fieldBlock {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    margin-bottom: 12px;

    &:last-child {
      margin-bottom: 0;
    }
  }

  .fieldLabel {
    color: #8f959e;
    font-size: 12px;
    line-height: 18px;
  }

  .typographyToolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;

    .fontSizeSelect {
      width: 68px;
      flex: 0 0 68px;
    }
  }

  .btnGroup {
    display: flex;
    align-items: center;
  }

  .compactButtonGroup {
    min-width: 0;
    flex: 1;
    justify-content: space-between;
    gap: 2px;
  }

  .styleBtn {
    position: relative;
    width: 34px;
    height: 32px;
    flex: 0 0 34px;
    padding: 0;
    background: transparent;
    color: #1f2329;
    border: 1px solid transparent;
    display: inline-flex;
    justify-content: center;
    align-items: center;
    font-weight: 600;
    font-family: inherit;
    font-size: 14px;
    cursor: pointer;
    border-radius: 6px;
    transition: 0.15s ease;

    &:hover:not(:disabled) {
      border-color: #c6d5ff;
      color: #3370ff;
      background: #f5f8ff;
    }

    &.actived {
      color: #3370ff;
      border-color: #8fb0ff;
      background-color: #edf4ff;
    }

    &:disabled {
      color: #c0c4cc;
      cursor: not-allowed;
      opacity: 0.55;
    }

    &.i {
      font-style: italic;
    }

    &.u {
      text-decoration: underline;
      text-underline-offset: 2px;
    }

    &.strike {
      text-decoration: line-through;
    }

    &.fontStepBtn {
      font-size: 13px;

      sup {
        font-size: 9px;
        line-height: 1;
        margin-left: 1px;
      }
    }
  }

  .colorPaletteControls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .quickColorList {
    display: flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
  }

  .quickColorButton {
    width: 28px;
    height: 28px;
    flex: 0 0 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 6px;
    background: #fff;
    cursor: pointer;
    transition: 0.15s ease;

    &:hover:not(:disabled),
    &.active {
      border-color: #8fb0ff;
      box-shadow: 0 0 0 2px #edf4ff;
    }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 2px;
    }

    &:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }
  }

  .quickColorSwatch {
    width: 20px;
    height: 20px;
    border: 1px solid rgba(31, 35, 41, 0.08);
    border-radius: 4px;
  }

  .moreColorButton {
    height: 28px;
    flex: 0 0 56px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 0 10px;
    border: 1px solid #dfe2e6;
    border-radius: 6px;
    color: #646a73;
    background: #fff;
    font-size: 12px;
    cursor: pointer;

    .el-icon {
      font-size: 12px;
    }

    &:hover:not(:disabled) {
      color: #3370ff;
      border-color: #8fb0ff;
    }

    &:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }
  }

  .segmentedControl {
    display: flex;
    width: 100%;
    border: 1px solid #dfe2e6;
    border-radius: 6px;
    overflow: hidden;
  }

  .segmentButton {
    min-width: 0;
    height: 30px;
    flex: 1;
    border: 0;
    border-right: 1px solid #eef0f3;
    background: #fff;
    color: #646a73;
    font-size: 12px;
    cursor: pointer;
    transition: 0.15s ease;

    &:last-child {
      border-right: 0;
    }

    &:hover:not(:disabled) {
      color: #3370ff;
      background: #f5f8ff;
    }

    &.active {
      color: #3370ff;
      background: #edf4ff;
      box-shadow: inset 0 0 0 1px #3370ff;
    }

    &:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }
  }

  .controlGrid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: 12px;
    row-gap: 10px;

    .fieldBlock {
      margin-bottom: 0;
    }

    .fullSpanField {
      grid-column: 1 / -1;
    }
  }

  .fillControlRow {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px;

    .fillColorField {
      margin-bottom: 0;
    }
  }

  .gradientToggle {
    height: 32px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #646a73;
    font-size: 12px;
    cursor: pointer;
  }

  .row {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 12px;

    &.noBottom {
      margin-bottom: 0;
    }

    &.textSettingsRow {
      flex-wrap: wrap;

      .fontFamilyItem {
        flex: 1 0 100%;
        width: 100%;
      }

      .alignItem {
        margin-left: auto;
      }
    }

    &.colorPaletteRow {
      align-items: center;

      > .name {
        color: #646a73;
        font-size: 12px;
        white-space: nowrap;
      }
    }

    .btnGroup {
      width: 100%;
      display: flex;
      justify-content: flex-start;
      gap: 8px;
    }

    .rowItem {
      display: flex;
      align-items: center;
      min-width: 0;

      .name {
        font-size: 12px;
        margin-right: 8px;
        color: #646a73;
        white-space: nowrap;
      }

    }

    .styleBtn {
      position: relative;
      width: 38px;
      height: 32px;
      padding: 0;
      background: #fff;
      border: 1px solid #dfe2e6;
      display: flex;
      justify-content: center;
      align-items: center;
      font-weight: bold;
      font-family: inherit;
      font-size: 14px;
      cursor: pointer;
      border-radius: 6px;
      transition: 0.15s ease;

      &:hover {
        border-color: #8fb0ff;
        color: #3370ff;
      }

      &.actived {
        color: #3370ff;
        border-color: #8fb0ff;
        background-color: #edf4ff;
      }

      &.disabled,
      &:disabled {
        background-color: #f5f7fa !important;
        border-color: #e4e7ed !important;
        color: #c0c4cc !important;
        cursor: not-allowed !important;
      }

      &.i {
        font-style: italic;
      }

      .colorShow {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 2px;
      }
    }

    .quickColorList {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .quickColorButton {
      width: 28px;
      height: 28px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
      border: 1px solid transparent;
      border-radius: 6px;
      background: #fff;
      cursor: pointer;
      transition: 0.15s ease;

      &:hover:not(:disabled),
      &.active {
        border-color: #8fb0ff;
        box-shadow: 0 0 0 2px #edf4ff;
      }

      &:focus-visible {
        outline: 2px solid #3370ff;
        outline-offset: 2px;
      }

      &:disabled {
        cursor: not-allowed;
        opacity: 0.45;
      }
    }

    .quickColorSwatch {
      width: 20px;
      height: 20px;
      border: 1px solid rgba(31, 35, 41, 0.08);
      border-radius: 4px;
    }
  }
}

.borderLine {
  display: inline-block;
  width: 100%;
  background-color: #000;

  &.isDark {
    background-color: #fff;
  }
}
</style>
<style lang="less">
.el-select-dropdown__item.selected {
  .borderLine {
    background-color: #409eff;
  }
}
</style>
