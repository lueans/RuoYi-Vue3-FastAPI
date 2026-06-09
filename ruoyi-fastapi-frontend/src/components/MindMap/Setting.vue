<template>
  <Sidebar ref="sidebarRef" title="设置">
    <div class="sidebarContent" :class="{ isDark: isDark }">
      <!-- 水印 -->
      <div class="title noTop">水印</div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="watermark.show" @change="updateWatermark" />
          <span class="name" style="margin-left: 10px">显示水印</span>
        </div>
      </div>
      <template v-if="watermark.show">
        <div class="row">
          <div class="rowItem">
            <el-switch v-model="watermark.onlyExport" @change="updateWatermark" />
            <span class="name" style="margin-left: 10px">仅导出时显示</span>
          </div>
        </div>
        <div class="row">
          <div class="rowItem" style="width: 100%">
            <span class="name">水印文字</span>
            <el-input v-model="watermark.text" size="small" style="width: 160px" @change="updateWatermark" />
          </div>
        </div>
        <div class="row">
          <div class="rowItem">
            <span class="name">颜色</span>
            <el-color-picker v-model="watermark.textColor" size="small" show-alpha @change="updateWatermark" />
          </div>
          <div class="rowItem">
            <span class="name">字号</span>
            <el-input-number v-model="watermark.fontSize" :min="10" :max="60" size="small" controls-position="right" style="width: 80px" @change="updateWatermark" />
          </div>
        </div>
        <div class="row">
          <div class="rowItem" style="width: 100%">
            <span class="name">角度</span>
            <div style="flex: 1">
              <el-slider v-model="watermark.angle" :min="-90" :max="90" @change="updateWatermark" />
            </div>
          </div>
        </div>
      </template>

      <!-- 行为设置 -->
      <div class="title">行为设置</div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.openPerformance" @change="updateConfig('openPerformance')" />
          <span class="name" style="margin-left: 10px">性能模式</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.enableFreeDrag" @change="updateConfig('enableFreeDrag')" />
          <span class="name" style="margin-left: 10px">自由拖拽</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch :model-value="enableRichText" @change="toggleRichText" />
          <span class="name" style="margin-left: 10px">开启富文本编辑</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.enableAutoEnterTextEditWhenKeydown" @change="updateConfig('enableAutoEnterTextEditWhenKeydown')" />
          <span class="name" style="margin-left: 10px">按键自动进入编辑</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.alwaysShowExpandBtn" @change="onAlwaysShowExpandBtnChange" />
          <span class="name" style="margin-left: 10px">始终显示展开按钮</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.isLimitMindMapInCanvas" @change="onLimitCanvasChange" />
          <span class="name" style="margin-left: 10px">限制脑图在画布内</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="localConfig.useLeftKeySelectionRightKeyDrag" @change="onSelectionModeChange" />
          <span class="name" style="margin-left: 10px">左键框选节点</span>
          <span class="desc">开启后左键拖拽框选，右键拖拽画布</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">鼠标滚轮行为</span>
          <el-select v-model="config.mousewheelAction" size="small" style="width: 130px" @change="updateConfig('mousewheelAction')">
            <el-option label="缩放" value="zoom" />
            <el-option label="上下移动" value="move" />
          </el-select>
        </div>
      </div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">创建新节点行为</span>
          <el-select v-model="config.createNewNodeBehavior" size="small" style="width: 130px" @change="updateConfig('createNewNodeBehavior')">
            <el-option label="默认" value="default" />
            <el-option label="不激活" value="notActive" />
            <el-option label="仅激活" value="activeOnly" />
          </el-select>
        </div>
      </div>

      <!-- 间距 -->
      <div class="title">间距</div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">图文间距</span>
          <div style="flex: 1">
            <el-slider v-model="config.imgTextMargin" :min="0" :max="50" @change="onMarginChange('imgTextMargin')" />
          </div>
        </div>
      </div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">文字内容间距</span>
          <div style="flex: 1">
            <el-slider v-model="config.textContentMargin" :min="0" :max="30" @change="onMarginChange('textContentMargin')" />
          </div>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store, actions } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const enableRichText = computed(() => store.localConfig.openNodeRichText)
const localConfig = computed(() => store.localConfig)

const config = reactive({
  openPerformance: false,
  enableFreeDrag: false,
  enableAutoEnterTextEditWhenKeydown: true,
  alwaysShowExpandBtn: false,
  isLimitMindMapInCanvas: true,
  mousewheelAction: 'zoom',
  createNewNodeBehavior: 'default',
  imgTextMargin: 5,
  textContentMargin: 2,
})

const watermark = reactive({
  show: false,
  onlyExport: false,
  text: '',
  textColor: 'rgba(0,0,0,0.1)',
  fontSize: 14,
  angle: -30,
})

function initConfig() {
  if (!props.mindMap) return
  const get = (key) => props.mindMap.getConfig(key)
  config.openPerformance = !!get('openPerformance')
  config.enableFreeDrag = !!get('enableFreeDrag')
  config.enableAutoEnterTextEditWhenKeydown = get('enableAutoEnterTextEditWhenKeydown') !== false
  config.alwaysShowExpandBtn = !!get('alwaysShowExpandBtn')
  config.isLimitMindMapInCanvas = get('isLimitMindMapInCanvas') !== false
  config.mousewheelAction = get('mousewheelAction') || 'zoom'
  config.createNewNodeBehavior = get('createNewNodeBehavior') || 'default'
  config.imgTextMargin = get('imgTextMargin') ?? 5
  config.textContentMargin = get('textContentMargin') ?? 2
}

function initWatermark() {
  if (!props.mindMap) return
  const wm = props.mindMap.getConfig('watermarkConfig') || {}
  watermark.show = !!wm.text
  watermark.onlyExport = !!wm.onlyExport
  watermark.text = wm.text || ''
  watermark.textColor = wm.textStyle?.color || 'rgba(0,0,0,0.1)'
  watermark.fontSize = wm.textStyle?.fontSize || 14
  watermark.angle = wm.angle ?? -30
}

function toggleRichText(val) {
  actions.setLocalConfig({ openNodeRichText: val })
}

function updateConfig(prop) {
  props.mindMap?.updateConfig({ [prop]: config[prop] })
}

function onAlwaysShowExpandBtnChange() {
  updateConfig('alwaysShowExpandBtn')
  props.mindMap?.reRender()
}

function onLimitCanvasChange() {
  updateConfig('isLimitMindMapInCanvas')
}

function onSelectionModeChange(val) {
  actions.setLocalConfig({ useLeftKeySelectionRightKeyDrag: val })
  props.mindMap?.updateConfig({ useLeftKeySelectionRightKeyDrag: val })
}

function onMarginChange(prop) {
  updateConfig(prop)
  props.mindMap?.reRender()
}

function updateWatermark() {
  if (!props.mindMap?.watermark) return
  const wmConfig = watermark.show ? {
    text: watermark.text || '水印',
    onlyExport: watermark.onlyExport,
    lineSpacing: 100,
    textSpacing: 100,
    angle: watermark.angle,
    textStyle: {
      color: watermark.textColor,
      fontSize: watermark.fontSize,
    }
  } : { text: '' }
  props.mindMap.watermark.updateWatermark(wmConfig)
}

watch(() => store.activeSidebar, (val) => {
  if (val === 'setting') {
    initConfig()
    initWatermark()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})
</script>

<style lang="less" scoped>
.sidebarContent {
  padding: 20px;
  padding-top: 10px;

  &.isDark {
    .title {
      color: #fff;
    }

    .row {
      .rowItem {
        .name {
          color: hsla(0, 0%, 100%, 0.6);
        }
      }
    }
  }

  .title {
    font-size: 16px;
    font-family: PingFangSC-Medium, PingFang SC;
    font-weight: 500;
    color: rgba(26, 26, 26, 0.9);
    margin-bottom: 10px;
    margin-top: 20px;

    &.noTop {
      margin-top: 0;
    }
  }

  .row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;

    .rowItem {
      display: flex;
      align-items: center;
      margin-bottom: 5px;

      .name {
        font-size: 12px;
        margin-right: 10px;
        white-space: nowrap;
      }

      .desc {
        font-size: 11px;
        color: #999;
        margin-left: 4px;
      }
    }
  }
}
</style>
