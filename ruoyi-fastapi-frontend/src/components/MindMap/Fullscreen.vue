<template>
  <div class="fullscreenContainer" :class="{ isDark: isDark }">
    <el-tooltip effect="dark" :content="canvasTooltip" placement="top">
      <button
        class="btn iconfont iconquanping"
        type="button"
        :aria-label="canvasTooltip"
        :aria-pressed="isCanvasFullscreen"
        :disabled="!fullscreenSupported || isChanging"
        @click="toggleCanvasFullscreen"
      ></button>
    </el-tooltip>
    <el-tooltip effect="dark" :content="pageTooltip" placement="top">
      <button
        class="btn iconfont iconquanping1"
        type="button"
        :aria-label="pageTooltip"
        :aria-pressed="isPageFullscreen"
        :disabled="!fullscreenSupported || isChanging"
        @click="togglePageFullscreen"
      ></button>
    </el-tooltip>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import {
  exitFullscreenAndWait,
  fullscrrenEvent,
  getFullscreenElement,
  isFullscreenSupported,
  requestFullscreenAndWait,
} from './utils'

const props = defineProps({
  mindMap: { type: Object, default: null },
  isDark: { type: Boolean, default: false }
})

const eventName = fullscrrenEvent ? fullscrrenEvent.replace(/^on/, '') : null
const fullscreenElement = shallowRef(null)
const isChanging = ref(false)
let resizeTimer = null

const canvasElement = computed(() => props.mindMap?.el || null)
const pageElement = computed(() => (
  props.mindMap?.el?.closest?.('.mindmap-edit-page') || document.body
))
const fullscreenSupported = computed(() => isFullscreenSupported(canvasElement.value))
const isCanvasFullscreen = computed(() => fullscreenElement.value === canvasElement.value)
const isPageFullscreen = computed(() => fullscreenElement.value === pageElement.value)
const canvasTooltip = computed(() => {
  if (!fullscreenSupported.value) return '当前浏览器不支持全屏'
  return isCanvasFullscreen.value ? '退出全屏查看' : '全屏查看脑图'
})
const pageTooltip = computed(() => {
  if (!fullscreenSupported.value) return '当前浏览器不支持全屏'
  return isPageFullscreen.value ? '退出全屏编辑' : '全屏编辑脑图'
})

function onFullscreenChange() {
  fullscreenElement.value = getFullscreenElement()
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    props.mindMap?.resize()
  }, 120)
}

onMounted(() => {
  fullscreenElement.value = getFullscreenElement()
  if (eventName) {
    document.addEventListener(eventName, onFullscreenChange)
  }
})

onBeforeUnmount(() => {
  clearTimeout(resizeTimer)
  if (eventName) {
    document.removeEventListener(eventName, onFullscreenChange)
  }
})

async function toggleFullscreen(target, active) {
  if (!target || isChanging.value) return
  isChanging.value = true
  try {
    if (active) {
      if (!await exitFullscreenAndWait()) {
        throw new Error('浏览器未能退出全屏模式')
      }
    } else {
      if (!await requestFullscreenAndWait(target)) {
        throw new Error('浏览器未允许进入全屏模式')
      }
    }
  } catch (error) {
    ElMessage.warning(error?.message || '无法切换全屏模式')
  } finally {
    fullscreenElement.value = getFullscreenElement()
    isChanging.value = false
  }
}

function toggleCanvasFullscreen() {
  return toggleFullscreen(canvasElement.value, isCanvasFullscreen.value)
}

function togglePageFullscreen() {
  return toggleFullscreen(pageElement.value, isPageFullscreen.value)
}
</script>

<style lang="less" scoped>
.fullscreenContainer {
  display: flex;
  align-items: center;

  &.isDark {
    .btn {
      color: hsla(0, 0%, 100%, 0.6);
    }
  }

  .item {
    margin-right: 12px;

    &:last-of-type {
      margin-right: 0;
    }
  }

  .btn {
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
    margin-right: 12px;

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 4px;
      border-radius: 3px;
    }

    &:last-of-type {
      margin-right: 0;
    }

    &:disabled {
      cursor: not-allowed;
      opacity: 0.38;
    }

    &[aria-pressed='true'] {
      color: #3370ff;
    }
  }
}
</style>
