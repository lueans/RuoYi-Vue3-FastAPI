<template>
  <div class="fullscreenContainer" :class="{ isDark: isDark }">
    <el-tooltip effect="dark" content="全屏查看" placement="top">
      <div class="btn iconfont iconquanping" @click="toFullscreenShow"></div>
    </el-tooltip>
    <el-tooltip effect="dark" content="全屏编辑" placement="top">
      <div class="btn iconfont iconquanping1" @click="toFullscreenEdit"></div>
    </el-tooltip>
  </div>
</template>

<script setup>
import { fullscrrenEvent, fullScreen } from './utils'

const props = defineProps({
  mindMap: { type: Object, default: null },
  isDark: { type: Boolean, default: false }
})

const eventName = fullscrrenEvent ? fullscrrenEvent.replace(/^on/, '') : null

function onFullscreenChange() {
  setTimeout(() => {
    props.mindMap?.resize()
  }, 1000)
}

onMounted(() => {
  if (eventName) {
    document.addEventListener(eventName, onFullscreenChange)
  }
})

onBeforeUnmount(() => {
  if (eventName) {
    document.removeEventListener(eventName, onFullscreenChange)
  }
})
function toFullscreenShow() {
  if (props.mindMap?.el) {
    fullScreen(props.mindMap.el)
  }
}

function toFullscreenEdit() {
  fullScreen(document.body)
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
    cursor: pointer;
    margin-right: 12px;

    &:last-of-type {
      margin-right: 0;
    }
  }
}
</style>
