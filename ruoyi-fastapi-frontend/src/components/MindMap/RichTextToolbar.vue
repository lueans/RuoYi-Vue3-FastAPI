<template>
  <div
    class="richTextToolbarContainer"
    :class="{ isDark: isDark }"
    v-show="showRichTextToolbar"
    ref="richTextToolbarRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    role="toolbar"
    aria-label="富文本格式"
    aria-orientation="horizontal"
    @click.stop
    @mousedown.stop
    @keydown.esc.stop="closeToolbar"
  >
    <el-tooltip content="加粗" placement="bottom">
      <button class="btn" type="button" aria-label="加粗" :aria-pressed="formatInfo.bold" :class="{ active: formatInfo.bold }" :disabled="isReadonly" @click="formatText('bold')">B</button>
    </el-tooltip>
    <el-tooltip content="斜体" placement="bottom">
      <button class="btn italic" type="button" aria-label="斜体" :aria-pressed="formatInfo.italic" :class="{ active: formatInfo.italic }" :disabled="isReadonly" @click="formatText('italic')">I</button>
    </el-tooltip>
    <el-tooltip content="下划线" placement="bottom">
      <button class="btn underline" type="button" aria-label="下划线" :aria-pressed="formatInfo.underline" :class="{ active: formatInfo.underline }" :disabled="isReadonly" @click="formatText('underline')">U</button>
    </el-tooltip>
    <el-tooltip content="删除线" placement="bottom">
      <button class="btn strike" type="button" aria-label="删除线" :aria-pressed="formatInfo.strike" :class="{ active: formatInfo.strike }" :disabled="isReadonly" @click="formatText('strike')">S</button>
    </el-tooltip>
    <span class="split"></span>
    <el-popover placement="bottom" trigger="click" :width="180">
      <template #reference>
        <span class="popoverReference">
          <el-tooltip content="字体" placement="bottom">
            <button class="btn fontBtn" type="button" aria-label="选择字体" :disabled="isReadonly">{{ currentFontFamily }}</button>
          </el-tooltip>
        </span>
      </template>
      <div class="fontList">
        <button
          class="fontItem"
          v-for="item in fontFamilyList"
          :key="item.value"
          type="button"
          :style="{ fontFamily: item.value }"
          :class="{ active: formatInfo.font === item.value }"
          :disabled="isReadonly"
          @click="setFont(item.value)"
        >{{ item.name }}</button>
      </div>
    </el-popover>
    <el-popover placement="bottom" trigger="click" :width="120">
      <template #reference>
        <span class="popoverReference">
          <el-tooltip content="字号" placement="bottom">
            <button class="btn" type="button" aria-label="选择字号" :disabled="isReadonly">{{ currentFontSize }}</button>
          </el-tooltip>
        </span>
      </template>
      <div class="fontList">
        <button
          class="fontItem"
          v-for="item in fontSizeList"
          :key="item"
          type="button"
          :style="{ fontSize: item + 'px' }"
          :class="{ active: formatInfo.size === (item + 'px') }"
          :disabled="isReadonly"
          @click="setFontSize(item)"
        >{{ item }}</button>
      </div>
    </el-popover>
    <span class="split"></span>
    <el-popover placement="bottom" trigger="click" :width="270">
      <template #reference>
        <span class="popoverReference">
          <el-tooltip content="字体颜色" placement="bottom">
            <button class="btn" type="button" aria-label="选择字体颜色" :disabled="isReadonly">
              A
              <span class="colorBar" :style="{ backgroundColor: formatInfo.color || '#333' }"></span>
            </button>
          </el-tooltip>
        </span>
      </template>
      <Color :color="formatInfo.color" @change="setColor" />
    </el-popover>
    <el-popover placement="bottom" trigger="click" :width="270">
      <template #reference>
        <span class="popoverReference">
          <el-tooltip content="背景颜色" placement="bottom">
            <button class="btn bgBtn" type="button" aria-label="选择背景颜色" :disabled="isReadonly">
              <span class="bgIcon" :style="{ backgroundColor: formatInfo.background || 'transparent' }">A</span>
            </button>
          </el-tooltip>
        </span>
      </template>
      <Color :color="formatInfo.background" @change="setBackground" />
    </el-popover>
    <span class="split"></span>
    <el-tooltip content="清除格式" placement="bottom">
      <button class="btn iconfont iconqingchu" type="button" aria-label="清除格式" :disabled="isReadonly" @click="removeFormat"></button>
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
const isReadonly = computed(() => store.isReadonly)
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
let currentMindMap = null

const emptyFormatInfo = Object.freeze({
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

function closeToolbar() {
  showRichTextToolbar.value = false
  currentMindMap = null
  Object.assign(formatInfo, emptyFormatInfo)
}

function getCurrentRichTextPlugin() {
  if (
    isReadonly.value
    || !showRichTextToolbar.value
    || !currentMindMap
    || currentMindMap !== props.mindMap
  ) return null
  return currentMindMap.richText || null
}

function onRichTextSelectionChange(hasRange, rect, info, sourceMindMap = null) {
  const activeMindMap = sourceMindMap || props.mindMap
  if (!activeMindMap || activeMindMap !== props.mindMap) return
  if (isReadonly.value) {
    closeToolbar()
    return
  }
  if (hasRange) {
    currentMindMap = activeMindMap
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
      const toolbarWidth = Math.min(elRect?.width || 300, Math.max(0, window.innerWidth - 16))
      const toolbarHeight = elRect?.height || 36
      let x = rect.left + rect.width / 2 - toolbarWidth / 2
      const maxLeft = Math.max(8, window.innerWidth - toolbarWidth - 8)
      x = Math.max(8, Math.min(x, maxLeft))
      const above = rect.top - toolbarHeight - 8
      const below = rect.bottom + 8
      const maxTop = Math.max(8, window.innerHeight - toolbarHeight - 8)
      const y = above >= 8 ? above : Math.max(8, Math.min(below, maxTop))
      left.value = x
      top.value = y
    }
    showRichTextToolbar.value = true
  } else {
    closeToolbar()
  }
}

function formatText(type) {
  getCurrentRichTextPlugin()?.formatText({ [type]: !formatInfo[type] })
}

function setFont(font) {
  getCurrentRichTextPlugin()?.formatText({ font })
}

function setFontSize(size) {
  getCurrentRichTextPlugin()?.formatText({ size: size + 'px' })
}

function setColor(color) {
  getCurrentRichTextPlugin()?.formatText({ color })
}

function setBackground(color) {
  getCurrentRichTextPlugin()?.formatText({ background: color })
}

function removeFormat() {
  getCurrentRichTextPlugin()?.removeFormat()
}

watch(isReadonly, (readonly) => {
  if (readonly) closeToolbar()
})

watch(() => props.mindMap, (mindMap, oldMindMap) => {
  if (mindMap !== oldMindMap) closeToolbar()
})

onMounted(() => {
  bus.on('rich_text_selection_change', onRichTextSelectionChange)
  if (richTextToolbarRef.value) {
    document.body.appendChild(richTextToolbarRef.value)
  }
})

onBeforeUnmount(() => {
  closeToolbar()
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
  max-width: calc(100vw - 16px);
  overflow-x: auto;
  overscroll-behavior-x: contain;
  pointer-events: all;

  &.isDark {
    background: #363b3f;
    .btn { color: hsla(0, 0%, 100%, 0.8); }
  }

  .btn {
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font-family: inherit;
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
    &:focus-visible { outline: 2px solid #409eff; outline-offset: 1px; }
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

  .popoverReference {
    display: inline-flex;
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
    display: block;
    width: 100%;
    border: 0;
    background: transparent;
    text-align: left;
    padding: 4px 8px;
    cursor: pointer;
    border-radius: 4px;
    font-size: 13px;

    &:hover { background: #f5f5f5; }
    &.active { color: #409eff; background: #ecf5ff; }
  }
}
</style>
