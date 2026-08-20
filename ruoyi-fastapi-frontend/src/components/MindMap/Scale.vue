<template>
  <div class="scaleContainer" :class="{ isDark: isDark }">
    <el-tooltip effect="dark" content="缩小" placement="top">
      <button class="btn el-icon-minus" type="button" aria-label="缩小画布" @click="narrow">
        <span class="iconfont">-</span>
      </button>
    </el-tooltip>
    <div class="scaleInfo">
      <input
        ref="inputRef"
        type="text"
        inputmode="numeric"
        aria-label="画布缩放百分比"
        v-model="scaleNum"
        @input="onScaleNumInput"
        @change="onScaleNumChange"
        @focus="onScaleNumInputFocus"
        @keydown.stop
        @keyup.stop
      />%
    </div>
    <el-tooltip effect="dark" content="放大" placement="top">
      <button class="btn el-icon-plus" type="button" aria-label="放大画布" @click="enlarge">
        <span class="iconfont">+</span>
      </button>
    </el-tooltip>
  </div>
</template>

<script setup>
import { clampMindmapScale } from '@/utils/mindmap-zoom'

const props = defineProps({
  mindMap: { type: Object, default: null },
  isDark: { type: Boolean, default: false }
})

const scaleNum = ref(100)
const cacheScaleNum = ref(0)
const inputRef = ref(null)

function toPer(scale) {
  return (scale * 100).toFixed(0)
}

function narrow() {
  props.mindMap?.view?.narrow()
}

function enlarge() {
  props.mindMap?.view?.enlarge()
}

function onScaleNumInputFocus() {
  cacheScaleNum.value = scaleNum.value
}

function onScaleNumInput() {
  scaleNum.value = String(scaleNum.value).replace(/[^0-9]+/g, '')
}

function onScaleNumChange() {
  const num = Number(scaleNum.value)
  const mindMap = props.mindMap
  if (!mindMap || !Number.isFinite(num) || num <= 0) {
    scaleNum.value = cacheScaleNum.value
  } else {
    const boundedScale = clampMindmapScale(num / 100, mindMap.opt)
    if (boundedScale === null) {
      scaleNum.value = cacheScaleNum.value
      return
    }
    scaleNum.value = toPer(boundedScale)
    const cx = mindMap.width / 2
    const cy = mindMap.height / 2
    mindMap.view.setScale(boundedScale, cx, cy)
  }
}

function onScale(scale) {
  scaleNum.value = toPer(scale)
}

function onDrawClick() {
  if (inputRef.value) inputRef.value.blur()
}

watch(() => props.mindMap, (val, oldVal) => {
  if (oldVal) {
    oldVal.off('scale', onScale)
    oldVal.off('draw_click', onDrawClick)
  }
  if (val) {
    val.on('scale', onScale)
    val.on('draw_click', onDrawClick)
    scaleNum.value = toPer(val.view.scale)
  }
}, { immediate: true })

onBeforeUnmount(() => {
  props.mindMap?.off?.('scale', onScale)
  props.mindMap?.off?.('draw_click', onDrawClick)
})
</script>

<style lang="less" scoped>
.scaleContainer {
  display: flex;
  align-items: center;

  &.isDark {
    .btn {
      color: hsla(0, 0%, 100%, 0.6);
    }

    .scaleInfo {
      color: hsla(0, 0%, 100%, 0.6);

      input {
        color: hsla(0, 0%, 100%, 0.6);
      }
    }
  }

  .btn {
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 4px;
      border-radius: 3px;
    }
  }

  .scaleInfo {
    margin: 0 20px;
    display: flex;
    align-items: center;

    input {
      width: 35px;
      text-align: center;
      background-color: transparent;
      border: none;
      outline: none;
    }
  }
}
</style>
