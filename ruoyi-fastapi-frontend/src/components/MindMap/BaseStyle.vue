<template>
  <div class="baseStylePanel" :class="{ embedded: props.embedded }">
    <div
      class="sidebarContent customScrollbar"
      :class="{ isDark: isDark }"
      v-if="props.mindMap"
    >
      <!-- 背景 -->
      <details class="baseStyleSection" open>
        <summary class="title noTop">
          <span>背景</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row">
        <el-tabs class="tab" v-model="activeTab">
          <el-tab-pane label="颜色" name="color">
            <Color
              :color="style.backgroundColor"
              @change="color => update('backgroundColor', color)"
            />
          </el-tab-pane>
          <el-tab-pane label="图片" name="image">
            <ImgUpload
              class="imgUpload"
              v-model="style.backgroundImage"
              @change="img => update('backgroundImage', img)"
            />
            <!-- 图片重复方式 -->
            <div class="rowItem">
              <span class="name">图片重复</span>
              <el-select
                size="small"
                style="width: 120px"
                v-model="style.backgroundRepeat"
                placeholder=""
                @change="value => update('backgroundRepeat', value)"
              >
                <el-option
                  v-for="item in backgroundRepeatList"
                  :key="item.value"
                  :label="item.name"
                  :value="item.value"
                />
              </el-select>
            </div>
            <!-- 图片位置 -->
            <div class="rowItem">
              <span class="name">图片位置</span>
              <el-select
                size="small"
                style="width: 120px"
                v-model="style.backgroundPosition"
                placeholder=""
                @change="value => update('backgroundPosition', value)"
              >
                <el-option
                  v-for="item in backgroundPositionList"
                  :key="item.value"
                  :label="item.name"
                  :value="item.value"
                />
              </el-select>
            </div>
            <!-- 图片大小 -->
            <div class="rowItem">
              <span class="name">图片大小</span>
              <el-select
                size="small"
                style="width: 120px"
                v-model="style.backgroundSize"
                placeholder=""
                @change="value => update('backgroundSize', value)"
              >
                <el-option
                  v-for="item in backgroundSizeList"
                  :key="item.value"
                  :label="item.name"
                  :value="item.value"
                />
              </el-select>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
        </div>
      </details>
      <!-- 连线 -->
      <details class="baseStyleSection" open>
        <summary class="title">
          <span>连线</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row">
        <div class="rowItem">
          <span class="name">颜色</span>
          <el-popover placement="bottom" trigger="click" :width="260">
            <template #reference>
              <ColorTrigger :color="style.lineColor" label="选择连线颜色" />
            </template>
            <Color
              :color="style.lineColor"
              @change="color => update('lineColor', color)"
            />
          </el-popover>
        </div>
        <div class="rowItem">
          <span class="name">粗细</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.lineWidth"
            placeholder=""
            @change="value => update('lineWidth', value)"
          >
            <el-option
              v-for="item in lineWidthList"
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
      </div>
      <div class="row">
        <!-- 连线风格 -->
        <div class="rowItem" v-if="lineStyleListShow.length > 1">
          <span class="name">风格</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.lineStyle"
            placeholder=""
            @change="value => update('lineStyle', value)"
          >
            <el-option
              v-for="item in lineStyleListShow"
              :key="item.value"
              :label="item.name"
              :value="item.value"
              class="lineStyleOption"
              :class="{
                isDark: isDark,
                isSelected: style.lineStyle === item.value
              }"
              v-html="lineStyleMap[item.value]"
            />
          </el-select>
        </div>
        <!-- 根节点连线样式 -->
        <div
          class="rowItem"
          v-if="style.lineStyle === 'curve' && showRootLineKeepSameInCurveLayouts"
        >
          <span class="name">根节点</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.rootLineKeepSameInCurve"
            placeholder=""
            @change="value => update('rootLineKeepSameInCurve', value)"
          >
            <el-option
              v-for="item in rootLineKeepSameInCurveList"
              :key="item.value"
              :label="item.name"
              :value="item.value"
            />
          </el-select>
        </div>
        <div class="rowItem" v-if="showLineRadius">
          <!-- 连线圆角大小 -->
          <span class="name">圆角大小</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.lineRadius"
            placeholder=""
            @change="value => update('lineRadius', value)"
          >
            <el-option
              v-for="item in [0, 2, 5, 7, 10, 12, 15]"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </div>
      </div>
      <div class="row">
        <!-- 根节点连线起始位置 -->
        <div
          class="rowItem"
          v-if="style.lineStyle === 'curve' && showRootLineKeepSameInCurveLayouts"
        >
          <span class="name">根节点连线起始位置</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.rootLineStartPositionKeepSameInCurve"
            placeholder=""
            @change="value => update('rootLineStartPositionKeepSameInCurve', value)"
          >
            <el-option key="center" label="中心" :value="false" />
            <el-option key="right" label="边缘" :value="true" />
          </el-select>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-checkbox
            v-model="style.showLineMarker"
            @change="value => update('showLineMarker', value)"
          >是否显示箭头</el-checkbox>
        </div>
      </div>
        </div>
      </details>
      <!-- 彩虹线条 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>彩虹线条</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row">
        <div class="rowItem">
          <el-popover
            placement="right"
            trigger="click"
            v-model:visible="rainbowLinesPopoverVisible"
            :width="220"
          >
            <template #default>
              <div class="rainbowLinesOptionsBox" :class="{ isDark: isDark }">
                <button
                  type="button"
                  class="optionItem"
                  v-for="item in rainbowLinesOptions"
                  :key="item.value"
                  :aria-label="item.list ? `使用彩虹线方案 ${item.value}` : '不使用彩虹线条'"
                  :aria-pressed="isRainbowOptionSelected(item)"
                  @click="updateRainbowLinesConfig(item)"
                >
                  <div
                    class="colorsBar"
                    v-if="item.list"
                    aria-hidden="true"
                  >
                    <span
                      class="colorItem"
                      v-for="(color, ci) in item.list"
                      :key="ci"
                      :style="{ backgroundColor: color }"
                    ></span>
                  </div>
                  <span v-else>不使用彩虹线条</span>
                </button>
              </div>
            </template>
            <template #reference>
              <button
                type="button"
                class="curRainbowLine"
                aria-label="选择彩虹线方案"
                :aria-expanded="rainbowLinesPopoverVisible"
              >
                <div class="colorsBar" v-if="curRainbowLineColorList">
                  <span
                    class="colorItem"
                    v-for="(color, ci) in curRainbowLineColorList"
                    :key="ci"
                    :style="{ backgroundColor: color }"
                  ></span>
                </div>
                <span v-else>不使用彩虹线条</span>
              </button>
            </template>
          </el-popover>
        </div>
      </div>
        </div>
      </details>
      <!-- 概要连线 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>概要连线</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row">
        <div class="rowItem">
          <span class="name">颜色</span>
          <el-popover placement="bottom" trigger="click" :width="260">
            <template #reference>
              <ColorTrigger :color="style.generalizationLineColor" label="选择概要连线颜色" />
            </template>
            <Color
              :color="style.generalizationLineColor"
              @change="color => update('generalizationLineColor', color)"
            />
          </el-popover>
        </div>
        <div class="rowItem">
          <span class="name">粗细</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.generalizationLineWidth"
            placeholder=""
            @change="value => update('generalizationLineWidth', value)"
          >
            <el-option
              v-for="item in lineWidthList"
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
      </div>
        </div>
      </details>
      <!-- 关联线 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>关联线</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row">
        <div class="rowItem">
          <span class="name">颜色</span>
          <el-popover placement="bottom" trigger="click" :width="260">
            <template #reference>
              <ColorTrigger :color="style.associativeLineColor" label="选择关联线颜色" />
            </template>
            <Color
              :color="style.associativeLineColor"
              @change="color => update('associativeLineColor', color)"
            />
          </el-popover>
        </div>
        <div class="rowItem">
          <span class="name">粗细</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.associativeLineWidth"
            placeholder=""
            @change="value => update('associativeLineWidth', value)"
          >
            <el-option
              v-for="item in lineWidthList"
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
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">激活颜色</span>
          <el-popover placement="bottom" trigger="click" :width="260">
            <template #reference>
              <ColorTrigger :color="style.associativeLineActiveColor" label="选择关联线激活颜色" />
            </template>
            <Color
              :color="style.associativeLineActiveColor"
              @change="color => update('associativeLineActiveColor', color)"
            />
          </el-popover>
        </div>
        <div class="rowItem">
          <span class="name">激活粗细</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.associativeLineActiveWidth"
            placeholder=""
            @change="value => update('associativeLineActiveWidth', value)"
          >
            <el-option
              v-for="item in lineWidthList"
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
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">样式</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.associativeLineDasharray"
            placeholder=""
            @change="value => update('associativeLineDasharray', value)"
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
                  :stroke="style.associativeLineDasharray === item.value ? '#409eff' : isDark ? '#fff' : '#000'"
                  :stroke-dasharray="item.value"
                />
              </svg>
            </el-option>
          </el-select>
        </div>
      </div>
        </div>
      </details>
      <!-- 关联线文字 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>关联线文字</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row">
        <div class="rowItem">
          <span class="name">字体</span>
          <el-select
            size="small"
            v-model="style.associativeLineTextFontFamily"
            placeholder=""
            @change="val => update('associativeLineTextFontFamily', val)"
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
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">颜色</span>
          <el-popover placement="bottom" trigger="click" :width="260">
            <template #reference>
              <ColorTrigger :color="style.associativeLineTextColor" label="选择关联线文字颜色" />
            </template>
            <Color
              :color="style.associativeLineTextColor"
              @change="color => update('associativeLineTextColor', color)"
            />
          </el-popover>
        </div>
        <div class="rowItem">
          <span class="name">字号</span>
          <el-select
            size="small"
            style="width: 80px"
            v-model="style.associativeLineTextFontSize"
            placeholder=""
            @change="val => update('associativeLineTextFontSize', val)"
          >
            <el-option
              v-for="item in fontSizeList"
              :key="item"
              :label="item"
              :value="item"
              :style="{ fontSize: item + 'px' }"
            />
          </el-select>
        </div>
      </div>
        </div>
      </details>
      <!-- 节点边框风格 -->
      <details v-if="showNodeUseLineStyle" class="baseStyleSection" open>
        <summary class="title">
          <span>节点边框风格</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
        <div class="row">
          <div class="rowItem">
            <el-checkbox
              v-model="style.nodeUseLineStyle"
              @change="value => update('nodeUseLineStyle', value)"
            >是否使用只有底边框的风格</el-checkbox>
          </div>
        </div>
        </div>
      </details>
      <!-- 内边距 -->
      <details class="baseStyleSection">
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
            @change="value => update('paddingX', value)"
          />
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">垂直</span>
          <el-slider
            style="width: 200px"
            v-model="style.paddingY"
            @change="value => update('paddingY', value)"
          />
        </div>
      </div>
        </div>
      </details>
      <!-- 图片 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>图片</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row noBottom">
        <div class="rowItem">
          <span class="name">显示的最大宽度</span>
          <el-slider
            style="width: 140px"
            v-model="style.imgMaxWidth"
            :min="10"
            :max="500"
            @change="value => update('imgMaxWidth', value)"
          />
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">显示的最大高度</span>
          <el-slider
            style="width: 140px"
            v-model="style.imgMaxHeight"
            :min="10"
            :max="500"
            @change="value => update('imgMaxHeight', value)"
          />
        </div>
      </div>
        </div>
      </details>
      <!-- 图标 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>图标</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row">
        <div class="rowItem">
          <span class="name">大小</span>
          <el-slider
            style="width: 200px"
            v-model="style.iconSize"
            :min="12"
            :max="50"
            @change="value => update('iconSize', value)"
          />
        </div>
      </div>
        </div>
      </details>
      <!-- 二级节点外边距 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>节点外边距</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row column noBottom">
        <el-tabs
          class="tab"
          v-model="marginActiveTab"
          @tab-change="initMarginStyle"
        >
          <el-tab-pane label="二级节点" name="second" />
          <el-tab-pane label="三级及以下节点" name="node" />
        </el-tabs>
        <div class="rowItem">
          <span class="name">水平</span>
          <el-slider
            :max="200"
            style="width: 200px"
            v-model="style.marginX"
            @change="value => updateMargin('marginX', value)"
          />
        </div>
        <div class="rowItem">
          <span class="name">垂直</span>
          <el-slider
            :max="200"
            style="width: 200px"
            v-model="style.marginY"
            @change="value => updateMargin('marginY', value)"
          />
        </div>
      </div>
        </div>
      </details>
      <!-- 外框内边距 -->
      <details class="baseStyleSection">
        <summary class="title">
          <span>外框内边距</span>
          <el-icon class="sectionChevron"><ArrowUp /></el-icon>
        </summary>
        <div class="sectionBody">
      <div class="row noBottom">
        <div class="rowItem">
          <span class="name">水平</span>
          <el-slider
            style="width: 200px"
            v-model="outerFramePadding.outerFramePaddingX"
            @change="value => updateOuterFramePadding('outerFramePaddingX', value)"
          />
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">垂直</span>
          <el-slider
            style="width: 200px"
            v-model="outerFramePadding.outerFramePaddingY"
            @change="value => updateOuterFramePadding('outerFramePaddingY', value)"
          />
        </div>
      </div>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup>
import { ArrowUp } from '@element-plus/icons-vue'
import ImgUpload from './ImgUpload/index.vue'
import Color from './Color.vue'
import ColorTrigger from './ColorTrigger.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'
import {
  lineWidthList,
  lineStyleList,
  lineStyleMap,
  rootLineKeepSameInCurveList,
  backgroundRepeatList,
  backgroundPositionList,
  backgroundSizeList,
  fontFamilyList,
  fontSizeList,
  borderDasharrayList,
  rainbowLinesOptions,
  supportLineStyleLayoutsMap,
  supportLineRadiusLayouts,
  supportNodeUseLineStyleLayouts,
  supportRootLineKeepSameInCurveLayouts
} from './config'

const props = defineProps({
  data: { type: [Object, null], default: null },
  configData: { type: Object, default: () => ({}) },
  mindMap: { type: Object, default: null },
  embedded: { type: Boolean, default: false }
})
const emit = defineEmits(['document-meta-change'])

const isDark = computed(() => store.localConfig.isDark)

const activeTab = ref('color')
const marginActiveTab = ref('second')

const style = reactive({
  backgroundColor: '',
  lineColor: '',
  lineWidth: '',
  lineStyle: '',
  showLineMarker: '',
  rootLineKeepSameInCurve: '',
  rootLineStartPositionKeepSameInCurve: '',
  lineRadius: 0,
  generalizationLineWidth: '',
  generalizationLineColor: '',
  associativeLineColor: '',
  associativeLineWidth: 0,
  associativeLineActiveWidth: 0,
  associativeLineDasharray: '',
  associativeLineActiveColor: '',
  associativeLineTextFontSize: 0,
  associativeLineTextColor: '',
  associativeLineTextFontFamily: '',
  paddingX: 0,
  paddingY: 0,
  imgMaxWidth: 0,
  imgMaxHeight: 0,
  iconSize: 0,
  backgroundImage: '',
  backgroundRepeat: 'no-repeat',
  backgroundPosition: '',
  backgroundSize: '',
  marginX: 0,
  marginY: 0,
  nodeUseLineStyle: false
})

const rainbowLinesPopoverVisible = ref(false)
const curRainbowLineColorList = ref(null)
const currentLayout = ref('')
const outerFramePadding = reactive({
  outerFramePaddingX: 0,
  outerFramePaddingY: 0
})

const showNodeUseLineStyle = computed(() => {
  return supportNodeUseLineStyleLayouts.includes(currentLayout.value)
})

const showLineRadius = computed(() => {
  return (
    style.lineStyle === 'straight' &&
    supportLineRadiusLayouts.includes(currentLayout.value)
  )
})

const lineStyleListShow = computed(() => {
  const res = []
  lineStyleList.forEach(item => {
    const list = supportLineStyleLayoutsMap[item.value]
    if (list) {
      if (list.includes(currentLayout.value)) {
        res.push(item)
      }
    } else {
      res.push(item)
    }
  })
  return res
})

const showRootLineKeepSameInCurveLayouts = computed(() => {
  return supportRootLineKeepSameInCurveLayouts.includes(currentLayout.value)
})

// Watch lineStyleListShow to auto-fix invalid selection
watch(lineStyleListShow, () => {
  const has = lineStyleListShow.value.find(item => item.value === style.lineStyle)
  if (!has && lineStyleListShow.value.length > 0) {
    style.lineStyle = lineStyleListShow.value[0].value
  }
}, { deep: true })

function initStyle() {
  if (!props.mindMap) return
  Object.keys(style).forEach(key => {
    style[key] = props.mindMap.getThemeConfig(key)
    if (key === 'backgroundImage' && style[key] === 'none') {
      style[key] = ''
    }
  })
  initMarginStyle()
}

function initRainbowLines() {
  if (!props.mindMap) return
  const config = props.mindMap.getConfig('rainbowLinesConfig') || {}
  curRainbowLineColorList.value = config.open
    ? (props.mindMap.rainbowLines
      ? props.mindMap.rainbowLines.getColorsList()
      : null)
    : null
}

function initOuterFramePadding() {
  if (!props.mindMap) return
  outerFramePadding.outerFramePaddingX = props.mindMap.getConfig('outerFramePaddingX')
  outerFramePadding.outerFramePaddingY = props.mindMap.getConfig('outerFramePaddingY')
}

function initMarginStyle() {
  if (!props.mindMap) return
  const themeConfig = props.mindMap.getThemeConfig()
  const tab = marginActiveTab.value
  if (themeConfig[tab]) {
    ;['marginX', 'marginY'].forEach(key => {
      style[key] = themeConfig[tab][key]
    })
  }
}

function update(key, value) {
  if (!props.mindMap || store.isReadonly) return
  if (key === 'backgroundImage' && value === 'none') {
    style[key] = ''
  } else {
    style[key] = value
  }
  const currentConfig = { ...(props.mindMap.getCustomThemeConfig() || {}) }
  currentConfig[key] = value
  props.mindMap.setThemeConfig(currentConfig)
  emit('document-meta-change', {
    theme: {
      template: props.mindMap.getTheme(),
      config: currentConfig
    }
  })
}

function updateRainbowLinesConfig(item) {
  if (store.isReadonly) return
  rainbowLinesPopoverVisible.value = false
  curRainbowLineColorList.value = item.list || null
  let newConfig = null
  if (item.list) {
    newConfig = { open: true, colorsList: item.list }
  } else {
    newConfig = { open: false }
  }
  if (props.mindMap?.rainbowLines) {
    props.mindMap.rainbowLines.updateRainLinesConfig(newConfig)
  }
  actions.storeConfig({ rainbowLinesConfig: newConfig })
}

function isRainbowOptionSelected(item) {
  const current = curRainbowLineColorList.value
  if (!item.list) return !current
  return Array.isArray(current)
    && current.length === item.list.length
    && current.every((color, index) => color === item.list[index])
}

function updateOuterFramePadding(prop, value) {
  if (store.isReadonly) return
  outerFramePadding[prop] = value
  if (props.mindMap) {
    props.mindMap.updateConfig({ [prop]: value })
    actions.storeConfig({ [prop]: value })
    props.mindMap.render()
  }
}

function updateMargin(type, value) {
  if (!props.mindMap || store.isReadonly) return
  style[type] = value
  const currentConfig = { ...(props.mindMap.getCustomThemeConfig() || {}) }
  currentConfig[marginActiveTab.value] = {
    ...(currentConfig[marginActiveTab.value] || {}),
    [type]: value
  }
  props.mindMap.setThemeConfig(currentConfig)
  emit('document-meta-change', {
    theme: {
      template: props.mindMap.getTheme(),
      config: currentConfig
    }
  })
}

function onSetData() {
  if (!['baseStyle', 'structure'].includes(store.activeSidebar)) return
  setTimeout(() => { initStyle() }, 0)
}

bus.on('setData', onSetData)

onBeforeUnmount(() => {
  bus.off('setData', onSetData)
})

watch(() => store.activeSidebar, (val) => {
  if (['baseStyle', 'structure'].includes(val)) {
    initStyle()
    initRainbowLines()
    initOuterFramePadding()
    if (props.mindMap) {
      currentLayout.value = props.mindMap.getLayout()
    }
  }
}, { immediate: true })
</script>

<style lang="less" scoped>
.baseStylePanel {
  width: 100%;
}

.sidebarContent {
  padding: 0;

  &.isDark {
    .title {
      color: #e5e6eb;
      border-color: #3d4046;

      &:hover {
        color: #7aa2ff;
      }
    }

    .row {
      .rowItem {
        .name,
        .curRainbowLine {
          color: #a9aeb8;
        }

        .curRainbowLine {
          border-color: #454950;
          background: #2f3338;
        }
      }
    }
  }

  .baseStyleSection {
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
    padding-top: 18px;
    border-top: 1px solid #eef0f3;
    font-size: 14px;
    font-family: PingFangSC-Medium, PingFang SC, sans-serif;
    font-weight: 600;
    color: #1f2329;
    margin-bottom: 14px;
    margin-top: 20px;
    list-style: none;
    cursor: pointer;
    user-select: none;

    &::-webkit-details-marker {
      display: none;
    }

    &:hover {
      color: #3370ff;
    }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 4px;
      border-radius: 4px;
    }

    &.noTop {
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }

    .sectionChevron {
      flex: 0 0 auto;
      color: #646a73;
      font-size: 13px;
      transition: transform 0.16s ease;
    }
  }

  .row {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 12px;

    &.noBottom {
      margin-bottom: 0;
    }

    &.column {
      flex-direction: column;
    }

    .tab {
      width: 100%;

      :deep(.el-tabs__header) {
        margin-bottom: 12px;
      }

      :deep(.el-tabs__item) {
        height: 34px;
        font-size: 12px;
      }
    }

    .imgUpload {
      margin-bottom: 5px;
    }

    .btnGroup {
      width: 100%;
      display: flex;
      justify-content: space-between;
    }

    .rowItem {
      display: flex;
      align-items: center;
      min-width: 0;
      margin-bottom: 6px;

      &.spaceBetween {
        justify-content: space-between;
      }

      .name {
        font-size: 12px;
        margin-right: 8px;
        color: #646a73;
        white-space: nowrap;
      }

      .curRainbowLine {
        width: 100%;
        min-width: 0;
        height: 34px;
        border: 1px solid #dfe2e6;
        border-radius: 6px;
        font-size: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        padding: 0;
        background: #fff;
        color: inherit;

        &:hover {
          border-color: #8fb0ff;
        }

        &:focus-visible {
          outline: 2px solid #409eff;
          outline-offset: 2px;
        }
      }

      .iconBtn {
        cursor: pointer;
        transition: all 0.3s;

        &.top {
          transform: rotateZ(-180deg);
        }
      }
    }

    > .rowItem:only-child {
      width: 100%;
    }

    :deep(.el-slider) {
      max-width: 100%;
    }

    .styleBtn {
      position: relative;
      width: 50px;
      height: 30px;
      background: #fff;
      border: 1px solid #eee;
      display: flex;
      justify-content: center;
      align-items: center;
      font-weight: bold;
      cursor: pointer;
      border-radius: 4px;

      &.actived {
        background-color: #eee;
      }

      .colorShow {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 2px;
      }
    }
  }
}

@media (max-width: 1180px) {
  .sidebarContent .row {
    gap: 6px;

    .rowItem .name {
      margin-right: 6px;
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

.lineStyleOption {
  &.isDark {
    svg {
      path {
        stroke: #fff;
      }
    }
  }

  &.isSelected {
    svg {
      path {
        stroke: #409eff;
      }
    }
  }

  svg {
    margin-top: 4px;

    path {
      stroke: #000;
    }
  }
}

.rainbowLinesOptionsBox {
  width: 200px;

  &.isDark {
    .optionItem {
      color: hsla(0, 0%, 100%, 0.6);

      &:hover {
        background-color: hsla(0, 0%, 100%, 0.05);
      }
    }
  }

  .optionItem {
    width: 100%;
    height: 30px;
    cursor: pointer;
    border: 0;
    padding: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    display: flex;
    align-items: center;
    justify-content: center;

    &:hover {
      background-color: #f5f7fa;
    }

    &:focus-visible {
      outline: 2px solid #409eff;
      outline-offset: -2px;
    }

    &[aria-pressed='true'] {
      box-shadow: inset 0 0 0 2px #409eff;
    }
  }
}

.colorsBar {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;

  .colorItem {
    flex: 1;
    height: 15px;
  }
}
</style>
