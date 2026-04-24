<template>
  <Sidebar ref="sidebarRef" title="外框样式">
    <div class="sidebarContent" :class="{ isDark: isDark }" v-if="hasActiveFrame">
      <div class="title noTop">外框设置</div>
      <div class="row">
        <div class="rowItem">
          <span class="name">边框宽度</span>
          <el-select size="small" style="width: 70px" v-model="frameStyle.strokeWidth" @change="val => updateFrame('strokeWidth', val)">
            <el-option v-for="w in lineWidthList" :key="w" :label="w" :value="w" />
          </el-select>
        </div>
        <div class="rowItem">
          <span class="name">颜色</span>
          <el-popover placement="bottom" trigger="click" :width="270">
            <template #reference>
              <span class="block" :style="{ backgroundColor: frameStyle.strokeColor }"></span>
            </template>
            <Color :color="frameStyle.strokeColor" @change="color => updateFrame('strokeColor', color)" />
          </el-popover>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">圆角</span>
          <el-select size="small" style="width: 70px" v-model="frameStyle.radius" @change="val => updateFrame('radius', val)">
            <el-option v-for="r in borderRadiusList" :key="r" :label="r" :value="r" />
          </el-select>
        </div>
        <div class="rowItem">
          <span class="name">填充</span>
          <el-popover placement="bottom" trigger="click" :width="270">
            <template #reference>
              <span class="block" :style="{ backgroundColor: frameStyle.fill }"></span>
            </template>
            <Color :color="frameStyle.fill" @change="color => updateFrame('fill', color)" />
          </el-popover>
        </div>
      </div>
      <div class="row">
        <el-button size="small" type="danger" @click="removeFrame">删除外框</el-button>
      </div>

      <div class="title">外框文字</div>
      <div class="row">
        <div class="rowItem" style="width: 100%">
          <span class="name">字号</span>
          <el-select size="small" style="width: 70px" v-model="frameStyle.textFontSize" @change="val => updateFrame('textFontSize', val)">
            <el-option v-for="s in fontSizeList" :key="s" :label="s" :value="s" />
          </el-select>
        </div>
      </div>
      <div class="row">
        <div class="rowItem">
          <span class="name">颜色</span>
          <el-popover placement="bottom" trigger="click" :width="270">
            <template #reference>
              <span class="block" :style="{ backgroundColor: frameStyle.textColor }"></span>
            </template>
            <Color :color="frameStyle.textColor" @change="color => updateFrame('textColor', color)" />
          </el-popover>
        </div>
      </div>
      <div class="row">
        <el-button size="small" @click="removeFrameText">删除文字</el-button>
      </div>
    </div>
    <div v-else class="emptyTip">请点击一个外框</div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import Color from './Color.vue'
import { store, actions } from './useStore'
import { lineWidthList, fontSizeList, borderRadiusList } from './config'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const hasActiveFrame = ref(false)

const frameStyle = reactive({
  strokeWidth: 2,
  strokeColor: '#549688',
  radius: 5,
  fill: 'transparent',
  textFontSize: 14,
  textColor: '#333',
})

function onFrameActive(el, parentNode, range) {
  hasActiveFrame.value = true
  if (parentNode && range) {
    const node = parentNode.children?.[range[0]]
    if (node) {
      const data = node.getData('outerFrame') || {}
      const style = data.style || {}
      frameStyle.strokeWidth = style.strokeWidth ?? 2
      frameStyle.strokeColor = style.strokeColor || '#549688'
      frameStyle.radius = style.radius ?? 5
      frameStyle.fill = style.fill || 'transparent'
      frameStyle.textFontSize = style.textFontSize ?? 14
      frameStyle.textColor = style.textColor || '#333'
    }
  }
  actions.setActiveSidebar('nodeOuterFrameStyle')
}

function onFrameDeactivate() {
  hasActiveFrame.value = false
  if (store.activeSidebar === 'nodeOuterFrameStyle') {
    actions.setActiveSidebar(null)
  }
}

function updateFrame(key, val) {
  frameStyle[key] = val
  props.mindMap?.outerFrame?.updateActiveOuterFrame?.({ [key]: val })
}

function removeFrame() {
  props.mindMap?.outerFrame?.removeActiveOuterFrame?.()
  hasActiveFrame.value = false
}

function removeFrameText() {
  props.mindMap?.outerFrame?.removeActiveOuterFrameText?.()
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) {
    oldMm.off('outer_frame_active', onFrameActive)
    oldMm.off('outer_frame_delete', onFrameDeactivate)
    oldMm.off('outer_frame_deactivate', onFrameDeactivate)
  }
  if (mm) {
    mm.on('outer_frame_active', onFrameActive)
    mm.on('outer_frame_delete', onFrameDeactivate)
    mm.on('outer_frame_deactivate', onFrameDeactivate)
  }
}, { immediate: true })

watch(() => store.activeSidebar, (val) => {
  if (val === 'nodeOuterFrameStyle') {
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})

onBeforeUnmount(() => {
  props.mindMap?.off('outer_frame_active', onFrameActive)
  props.mindMap?.off('outer_frame_delete', onFrameDeactivate)
  props.mindMap?.off('outer_frame_deactivate', onFrameDeactivate)
})
</script>

<style lang="less" scoped>
.sidebarContent {
  padding: 20px;

  &.isDark {
    .title { color: #fff; }
    .name { color: hsla(0, 0%, 100%, 0.6); }
  }

  .title {
    font-size: 16px;
    font-weight: 500;
    color: rgba(26, 26, 26, 0.9);
    margin-bottom: 10px;
    margin-top: 20px;
    &.noTop { margin-top: 0; }
  }

  .row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;

    .rowItem {
      display: flex;
      align-items: center;
      .name {
        font-size: 12px;
        margin-right: 8px;
        white-space: nowrap;
      }
      .block {
        display: inline-block;
        width: 30px;
        height: 22px;
        border: 1px solid #dcdfe6;
        border-radius: 4px;
        cursor: pointer;
      }
    }
  }
}
.emptyTip {
  text-align: center;
  color: #999;
  padding: 40px 0;
}
</style>
