<template>
  <div
    class="richTextToolbarContainer"
    :class="{ isDark: isDark }"
    v-show="showRichTextToolbar"
    ref="richTextToolbarRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    @click.stop
    @mousedown.stop
  >
    <el-tooltip content="加粗" placement="bottom">
      <div class="btn" :class="{ active: formatInfo.bold }" @click="formatText('bold')">B</div>
    </el-tooltip>
    <el-tooltip content="斜体" placement="bottom">
      <div class="btn italic" :class="{ active: formatInfo.italic }" @click="formatText('italic')">I</div>
    </el-tooltip>
    <el-tooltip content="下划线" placement="bottom">
      <div class="btn underline" :class="{ active: formatInfo.underline }" @click="formatText('underline')">U</div>
    </el-tooltip>
    <el-tooltip content="删除线" placement="bottom">
      <div class="btn strike" :class="{ active: formatInfo.strike }" @click="formatText('strike')">S</div>
    </el-tooltip>
    <span class="split"></span>
    <el-popover placement="bottom" trigger="click" :width="180">
      <template #reference>
        <el-tooltip content="字体" placement="bottom">
          <div class="btn fontBtn">{{ currentFontFamily }}</div>
        </el-tooltip>
      </template>
      <div class="fontList">
        <div
          class="fontItem"
          v-for="item in fontFamilyList"
          :key="item.value"
          :style="{ fontFamily: item.value }"
          :class="{ active: formatInfo.font === item.value }"
          @click="setFont(item.value)"
        >{{ item.name }}</div>
      </div>
    </el-popover>
    <el-popover placement="bottom" trigger="click" :width="120">
      <template #reference>
        <el-tooltip content="字号" placement="bottom">
          <div class="btn">{{ currentFontSize }}</div>
        </el-tooltip>
      </template>
      <div class="fontList">
        <div
          class="fontItem"
          v-for="item in fontSizeList"
          :key="item"
          :style="{ fontSize: item + 'px' }"
          :class="{ active: formatInfo.size === (item + 'px') }"
          @click="setFontSize(item)"
        >{{ item }}</div>
      </div>
    </el-popover>
    <span class="split"></span>
    <el-popover placement="bottom" trigger="click" :width="270">
      <template #reference>
        <el-tooltip content="字体颜色" placement="bottom">
          <div class="btn">
            A
            <span class="colorBar" :style="{ backgroundColor: formatInfo.color || '#333' }"></span>
          </div>
        </el-tooltip>
      </template>
      <Color :color="formatInfo.color" @change="setColor" />
    </el-popover>
    <el-popover placement="bottom" trigger="click" :width="270">
      <template #reference>
        <el-tooltip content="背景颜色" placement="bottom">
          <div class="btn bgBtn">
            <span class="bgIcon" :style="{ backgroundColor: formatInfo.background || 'transparent' }">A</span>
          </div>
        </el-tooltip>
      </template>
      <Color :color="formatInfo.background" @change="setBackground" />
    </el-popover>
    <span class="split"></span>
    <el-tooltip content="清除格式" placement="bottom">
      <div class="btn iconfont iconqingchu" @click="removeFormat"></div>
    </el-tooltip>
  </div>
</template>

<script setup>
import Color from './Color.vue'
import bus from './useEventBus'
import { store } from './useStore'
import { fontFamilyList, fontSizeList } from './config'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const showRichTextToolbar = ref(false)
const richTextToolbarRef = ref(null)
const left = ref(0)
const top = ref(0)
const formatInfo = reactive({
  bold: false,
  italic: false,
  underline: false,
  strike: false,
  font: '',
  size: '',
  color: '',
  background: ''
})

const currentFontFamily = computed(() => {
  const found = fontFamilyList.find(f => f.value === formatInfo.font)
  return found ? found.name : '字体'
})

const currentFontSize = computed(() => {
  return formatInfo.size ? parseInt(formatInfo.size) : '字号'
})

function onRichTextSelectionChange(hasRange, rect, info) {
  if (hasRange) {
    Object.assign(formatInfo, {
      bold: !!info?.bold,
      italic: !!info?.italic,
      underline: !!info?.underline,
      strike: !!info?.strike,
      font: info?.font || '',
      size: info?.size || '',
      color: info?.color || '',
      background: info?.background || ''
    })
    if (rect) {
      const elRect = richTextToolbarRef.value?.getBoundingClientRect()
      const toolbarWidth = elRect?.width || 300
      let x = rect.left + rect.width / 2 - toolbarWidth / 2
      let y = rect.top - 50
      if (x < 0) x = 10
      if (x + toolbarWidth > window.innerWidth) x = window.innerWidth - toolbarWidth - 10
      if (y < 0) y = rect.bottom + 10
      left.value = x
      top.value = y
    }
    showRichTextToolbar.value = true
  } else {
    showRichTextToolbar.value = false
  }
}

function formatText(type) {
  props.mindMap?.richText?.formatText({ [type]: !formatInfo[type] })
}

function setFont(font) {
  props.mindMap?.richText?.formatText({ font })
}

function setFontSize(size) {
  props.mindMap?.richText?.formatText({ size: size + 'px' })
}

function setColor(color) {
  props.mindMap?.richText?.formatText({ color })
}

function setBackground(color) {
  props.mindMap?.richText?.formatText({ background: color })
}

function removeFormat() {
  props.mindMap?.richText?.removeFormat()
}

onMounted(() => {
  bus.on('rich_text_selection_change', onRichTextSelectionChange)
  if (richTextToolbarRef.value) {
    document.body.appendChild(richTextToolbarRef.value)
  }
})

onBeforeUnmount(() => {
  bus.off('rich_text_selection_change', onRichTextSelectionChange)
  if (richTextToolbarRef.value?.parentNode === document.body) {
    document.body.removeChild(richTextToolbarRef.value)
  }
})
</script>

<style lang="less" scoped>
.richTextToolbarContainer {
  position: fixed;
  z-index: 10000;
  background: #fff;
  box-shadow: 0 2px 16px 0 rgba(0, 0, 0, 0.12);
  border-radius: 4px;
  padding: 4px 8px;
  display: flex;
  align-items: center;
  pointer-events: all;

  &.isDark {
    background: #363b3f;
    .btn { color: hsla(0, 0%, 100%, 0.8); }
  }

  .btn {
    width: 28px;
    height: 28px;
    display: flex;
    justify-content: center;
    align-items: center;
    cursor: pointer;
    border-radius: 4px;
    font-size: 14px;
    font-weight: 500;
    position: relative;

    &:hover { background: #f0f0f0; }
    &.active { background: #e8e8e8; color: #409eff; }
    &.italic { font-style: italic; }
    &.underline { text-decoration: underline; }
    &.strike { text-decoration: line-through; }
    &.fontBtn { width: auto; padding: 0 6px; font-size: 12px; max-width: 60px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .colorBar {
      position: absolute;
      bottom: 2px;
      left: 4px;
      right: 4px;
      height: 3px;
      border-radius: 1px;
    }

    .bgIcon {
      padding: 1px 4px;
      border-radius: 2px;
      font-size: 12px;
    }
  }

  .split {
    width: 1px;
    height: 20px;
    background: #e8e8e8;
    margin: 0 6px;
  }
}

.fontList {
  max-height: 200px;
  overflow-y: auto;

  .fontItem {
    padding: 4px 8px;
    cursor: pointer;
    border-radius: 4px;
    font-size: 13px;

    &:hover { background: #f5f5f5; }
    &.active { color: #409eff; background: #ecf5ff; }
  }
}
</style>
