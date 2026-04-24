<template>
  <Sidebar ref="sidebarRef" title="节点样式">
    <div
      class="styleBox"
      :class="{ isDark: isDark }"
      v-if="activeNodes.length > 0"
    >
      <div class="sidebarContent customScrollbar">
        <!-- 文字 -->
        <div class="title noTop">文字</div>
        <div class="row">
          <div class="rowItem">
            <el-select
              size="small"
              style="width: 100px"
              v-model="style.fontFamily"
              placeholder=""
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
          <div class="rowItem">
            <el-select
              size="small"
              style="width: 60px"
              v-model="style.fontSize"
              placeholder=""
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
          </div>
          <div class="rowItem">
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.textAlign"
              placeholder=""
              @change="update('textAlign')"
            >
              <el-option
                v-for="item in alignList"
                :key="item.value"
                :label="item.name"
                :value="item.value"
              />
            </el-select>
          </div>
        </div>
        <div class="row">
          <div class="btnGroup">
            <el-tooltip content="颜色" placement="bottom">
              <el-popover placement="bottom" trigger="hover" :width="260">
                <template #reference>
                  <div class="styleBtn">
                    A
                    <span
                      class="colorShow"
                      :style="{ backgroundColor: style.color || '#eee' }"
                    ></span>
                  </div>
                </template>
                <Color
                  :color="style.color"
                  @change="changeFontColor"
                />
              </el-popover>
            </el-tooltip>
            <el-tooltip content="加粗" placement="bottom">
              <div
                class="styleBtn"
                :class="{ actived: style.fontWeight === 'bold' }"
                @click="toggleFontWeight"
              >
                B
              </div>
            </el-tooltip>
            <el-tooltip content="斜体" placement="bottom">
              <div
                class="styleBtn i"
                :class="{ actived: style.fontStyle === 'italic' }"
                @click="toggleFontStyle"
              >
                I
              </div>
            </el-tooltip>
            <el-tooltip content="划线" placement="bottom">
              <el-popover placement="bottom" trigger="hover" :width="300">
                <template #reference>
                  <div
                    class="styleBtn u"
                    :style="{ textDecoration: style.textDecoration || 'none' }"
                  >
                    U
                  </div>
                </template>
                <el-radio-group
                  size="small"
                  v-model="style.textDecoration"
                  @change="update('textDecoration')"
                >
                  <el-radio-button label="none">无</el-radio-button>
                  <el-radio-button label="underline">下划线</el-radio-button>
                  <el-radio-button label="line-through">中划线</el-radio-button>
                  <el-radio-button label="overline">上划线</el-radio-button>
                </el-radio-group>
              </el-popover>
            </el-tooltip>
          </div>
        </div>
        <!-- 边框 -->
        <div class="title">边框</div>
        <div class="row">
          <div class="rowItem">
            <span class="name">颜色</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <span
                  class="block"
                  :style="{ width: '80px', backgroundColor: style.borderColor }"
                ></span>
              </template>
              <Color
                :color="style.borderColor"
                @change="changeBorderColor"
              />
            </el-popover>
          </div>
          <div class="rowItem">
            <span class="name">样式</span>
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.borderDasharray"
              placeholder=""
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
        </div>
        <div class="row">
          <div class="rowItem">
            <span class="name">宽度</span>
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.borderWidth"
              placeholder=""
              @change="update('borderWidth')"
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
          <div class="rowItem" v-show="style.shape === 'rectangle'">
            <span class="name">圆角</span>
            <el-select
              size="small"
              style="width: 80px"
              v-model="style.borderRadius"
              placeholder=""
              @change="update('borderRadius')"
            >
              <el-option
                v-for="item in borderRadiusList"
                :key="item"
                :label="item"
                :value="item"
              />
            </el-select>
          </div>
        </div>
        <!-- 背景 -->
        <div class="title">背景</div>
        <div class="row">
          <div class="rowItem">
            <span class="name">颜色</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <span
                  class="block"
                  :style="{ backgroundColor: style.fillColor }"
                ></span>
              </template>
              <Color
                :color="style.fillColor"
                @change="changeFillColor"
              />
            </el-popover>
            <span class="name" style="margin-left: 20px;">渐变</span>
            <el-checkbox
              v-model="style.gradientStyle"
              @change="update('gradientStyle')"
            />
          </div>
        </div>
        <div class="row" v-if="style.gradientStyle">
          <div class="rowItem">
            <span class="name">起始</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <span
                  class="block"
                  :style="{ backgroundColor: style.startColor }"
                ></span>
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
                <span
                  class="block"
                  :style="{ backgroundColor: style.endColor }"
                ></span>
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
        <!-- 形状 -->
        <div class="title">形状</div>
        <div class="row">
          <div class="rowItem">
            <span class="name">形状</span>
            <el-select
              size="small"
              style="width: 120px"
              v-model="style.shape"
              placeholder=""
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
        <!-- 线条 -->
        <div class="title">线条</div>
        <div class="row">
          <div class="rowItem">
            <span class="name">颜色</span>
            <el-popover placement="bottom" trigger="click" :width="260">
              <template #reference>
                <span
                  class="block"
                  :style="{ width: '80px', backgroundColor: style.lineColor }"
                ></span>
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
        <!-- 节点内边距 -->
        <div class="title">节点内边距</div>
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
        <!-- 节点图片布局 -->
        <div class="title">图片</div>
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
        <!-- 节点标签布局 -->
        <div class="title">标签</div>
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
    </div>
    <div class="tipBox" v-else>
      <div class="tipIcon iconfont icontianjiazijiedian"></div>
      <div class="tipText">请选择一个节点</div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import Color from './Color.vue'
import bus from './useEventBus'
import { store } from './useStore'
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
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const activeNodes = ref([])
const isDark = computed(() => store.localConfig.isDark)

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

// Listen for node activation
function onNodeActive(...args) {
  nextTick(() => {
    activeNodes.value = [...args[1]]
    initNodeStyle()
  })
}

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
  style.fontWeight = style.fontWeight === 'bold' ? 'normal' : 'bold'
  update('fontWeight')
}

function toggleFontStyle() {
  style.fontStyle = style.fontStyle === 'italic' ? 'normal' : 'italic'
  update('fontStyle')
}

function changeFontColor(color) {
  style.color = color
  update('color')
}

function changeBorderColor(color) {
  style.borderColor = color
  update('borderColor')
}

function changeLineColor(color) {
  style.lineColor = color
  update('lineColor')
}

function changeFillColor(color) {
  style.fillColor = color
  update('fillColor')
}

function changeStartColor(color) {
  style.startColor = color
  update('startColor')
}

function changeEndColor(color) {
  style.endColor = color
  update('endColor')
}

bus.on('node_active', onNodeActive)

onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
})

watch(() => store.activeSidebar, (val) => {
  if (val === 'nodeStyle') {
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})
</script>

<style lang="less" scoped>
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
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: #666;

  .tipIcon {
    font-size: 100px;
  }
}

.sidebarContent {
  padding: 20px;
  padding-top: 10px;

  .title {
    font-size: 16px;
    font-family: PingFangSC-Medium, PingFang SC;
    font-weight: 500;
    color: rgba(26, 26, 26, 0.9);
    margin-bottom: 10px;
    margin-top: 35px;

    &.noTop {
      margin-top: 0;
    }
  }

  .row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;

    &.noBottom {
      margin-bottom: 0;
    }

    .btnGroup {
      width: 100%;
      display: flex;
      justify-content: space-between;
    }

    .rowItem {
      display: flex;
      align-items: center;

      .name {
        font-size: 12px;
        margin-right: 10px;
      }

      .block {
        display: inline-block;
        width: 30px;
        height: 30px;
        border: 1px solid #dcdfe6;
        border-radius: 4px;
        cursor: pointer;

        &.disabled {
          background-color: #f5f7fa !important;
          border-color: #e4e7ed !important;
          color: #c0c4cc !important;
          cursor: not-allowed !important;
        }
      }
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

      &.disabled {
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
