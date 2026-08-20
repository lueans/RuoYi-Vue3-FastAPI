<template>
  <Sidebar ref="sidebarRef" title="设置" open-on-mount>
    <div class="sidebarContent" :class="{ isDark: isDark }">
      <div v-if="isReadonly" class="readonlyHint" role="status">
        当前文件为只读状态，水印和间距等文件展示设置不可修改；个人浏览偏好仍可调整。
      </div>
      <!-- 水印 -->
      <div class="title noTop">水印</div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="watermark.show" aria-label="显示水印" :disabled="isReadonly" @change="updateWatermark" />
          <span class="name" style="margin-left: 10px">显示水印</span>
        </div>
      </div>
      <template v-if="watermark.show">
        <div class="row">
          <div class="rowItem">
            <el-switch v-model="watermark.onlyExport" aria-label="仅导出时显示水印" :disabled="isReadonly" @change="updateWatermark" />
            <span class="name" style="margin-left: 10px">仅导出时显示</span>
          </div>
        </div>
        <div class="row">
          <div class="rowItem" style="width: 100%">
            <span class="name">水印文字</span>
            <el-input v-model="watermark.text" aria-label="水印文字" maxlength="200" :disabled="isReadonly" size="small" style="width: 160px" @change="updateWatermark" />
          </div>
        </div>
        <div class="row">
          <div class="rowItem">
            <span class="name">颜色</span>
            <el-color-picker v-model="watermark.textColor" aria-label="水印颜色" :disabled="isReadonly" size="small" show-alpha @change="updateWatermark" />
          </div>
          <div class="rowItem">
            <span class="name">字号</span>
            <el-input-number v-model="watermark.fontSize" aria-label="水印字号" :disabled="isReadonly" :min="10" :max="60" size="small" controls-position="right" style="width: 80px" @change="updateWatermark" />
          </div>
        </div>
        <div class="row">
          <div class="rowItem" style="width: 100%">
            <span class="name">角度</span>
            <div style="flex: 1">
              <el-slider v-model="watermark.angle" aria-label="水印角度" :disabled="isReadonly" :min="-90" :max="90" @change="updateWatermark" />
            </div>
          </div>
        </div>
      </template>

      <!-- 行为设置 -->
      <div class="title">行为设置</div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.openPerformance" aria-label="性能模式" @change="updateConfig('openPerformance')" />
          <span class="name" style="margin-left: 10px">性能模式</span>
          <span class="desc">1000 个以上节点默认开启，仅渲染可视区域</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.enableFreeDrag" aria-label="自由拖拽" @change="updateConfig('enableFreeDrag')" />
          <span class="name" style="margin-left: 10px">自由拖拽</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch :model-value="enableRichText" aria-label="开启富文本编辑" @change="toggleRichText" />
          <span class="name" style="margin-left: 10px">开启富文本编辑</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.enableAutoEnterTextEditWhenKeydown" aria-label="按键自动进入编辑" @change="updateConfig('enableAutoEnterTextEditWhenKeydown')" />
          <span class="name" style="margin-left: 10px">按键自动进入编辑</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.alwaysShowExpandBtn" aria-label="始终显示展开按钮" @change="onAlwaysShowExpandBtnChange" />
          <span class="name" style="margin-left: 10px">始终显示展开按钮</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch v-model="config.isLimitMindMapInCanvas" aria-label="限制脑图在画布内" @change="onLimitCanvasChange" />
          <span class="name" style="margin-left: 10px">限制脑图在画布内</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <el-switch :model-value="localConfig.useLeftKeySelectionRightKeyDrag" aria-label="左键框选节点" @change="onSelectionModeChange" />
          <span class="name" style="margin-left: 10px">左键框选节点</span>
          <span class="desc">开启后左键拖拽框选，右键拖拽画布</span>
        </div>
      </div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">鼠标滚轮行为</span>
          <el-select v-model="config.mousewheelAction" aria-label="鼠标滚轮行为" size="small" style="width: 130px" @change="updateConfig('mousewheelAction')">
            <el-option label="缩放" value="zoom" />
            <el-option label="上下移动" value="move" />
          </el-select>
        </div>
      </div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">创建新节点行为</span>
          <el-select v-model="config.createNewNodeBehavior" aria-label="创建新节点行为" size="small" style="width: 130px" @change="updateConfig('createNewNodeBehavior')">
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
            <el-slider v-model="config.imgTextMargin" aria-label="图文间距" :disabled="isReadonly" :min="0" :max="50" @change="onMarginChange('imgTextMargin')" />
          </div>
        </div>
      </div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">文字内容间距</span>
          <div style="flex: 1">
            <el-slider v-model="config.textContentMargin" aria-label="文字内容间距" :disabled="isReadonly" :min="0" :max="30" @change="onMarginChange('textContentMargin')" />
          </div>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store, actions } from './useStore'
import { getMindmapDocumentConfig } from '@/utils/mindmap-document-config'

const props = defineProps({
  mindMap: { type: Object, default: null },
  documentData: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['document-config-change'])

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
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
  const documentConfig = getMindmapDocumentConfig(props.documentData)
  config.openPerformance = !!get('openPerformance')
  config.enableFreeDrag = !!get('enableFreeDrag')
  config.enableAutoEnterTextEditWhenKeydown = get('enableAutoEnterTextEditWhenKeydown') !== false
  config.alwaysShowExpandBtn = !!get('alwaysShowExpandBtn')
  config.isLimitMindMapInCanvas = get('isLimitMindMapInCanvas') !== false
  config.mousewheelAction = get('mousewheelAction') || 'zoom'
  config.createNewNodeBehavior = get('createNewNodeBehavior') || 'default'
  config.imgTextMargin = documentConfig.imgTextMargin ?? get('imgTextMargin') ?? 5
  config.textContentMargin = documentConfig.textContentMargin ?? get('textContentMargin') ?? 2
}

function initWatermark() {
  if (!props.mindMap) return
  const wm = getMindmapDocumentConfig(props.documentData).watermarkConfig
    || props.mindMap.getConfig('watermarkConfig')
    || {}
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
  actions.storeConfig({ [prop]: config[prop] })
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
  if (isReadonly.value) return
  emit('document-config-change', { [prop]: config[prop] })
}

function updateWatermark() {
  if (!props.mindMap || isReadonly.value) return
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
  emit('document-config-change', { watermarkConfig: wmConfig })
}

watch(() => store.activeSidebar, (val) => {
  if (val === 'setting') {
    initConfig()
    initWatermark()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })

watch(() => props.documentData, () => {
  if (store.activeSidebar === 'setting') {
    initConfig()
    initWatermark()
  }
})
</script>

<style lang="less" scoped>
.sidebarContent {
  padding: 20px;
  padding-top: 10px;

  .readonlyHint {
    margin-bottom: 14px;
    padding: 9px 10px;
    border-radius: 6px;
    color: #606266;
    background: #f4f6f8;
    font-size: 12px;
    line-height: 1.5;
  }

  &.isDark {
    .readonlyHint {
      color: rgba(255, 255, 255, 0.72);
      background: rgba(255, 255, 255, 0.08);
    }

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

@media screen and (max-width: 520px) {
  .sidebarContent {
    padding: 10px 14px 18px;

    .row .rowItem {
      width: 100%;
      flex-wrap: wrap;
      row-gap: 6px;

      .desc {
        flex-basis: 100%;
        margin-left: 0;
      }
    }
  }
}
</style>
