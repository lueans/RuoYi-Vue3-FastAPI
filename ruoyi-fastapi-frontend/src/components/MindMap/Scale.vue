<template>
  <div class="scaleContainer" :class="{ isDark: isDark }">
    <el-tooltip effect="dark" content="缩小" placement="top">
      <div class="btn el-icon-minus" @click="narrow">
        <span class="iconfont">-</span>
      </div>
    </el-tooltip>
    <div class="scaleInfo">
      <input
        ref="inputRef"
        type="text"
        v-model="scaleNum"
        @input="onScaleNumInput"
        @change="onScaleNumChange"
        @focus="onScaleNumInputFocus"
        @keydown.stop
        @keyup.stop
      />%
    </div>
    <el-tooltip effect="dark" content="放大" placement="top">
      <div class="btn el-icon-plus" @click="enlarge">
        <span class="iconfont">+</span>
      </div>
    </el-tooltip>
  </div>
</template>

<script setup>
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
  if (Number.isNaN(num) || num <= 0) {
    scaleNum.value = cacheScaleNum.value
  } else {
    const cx = props.mindMap.width / 2
    const cy = props.mindMap.height / 2
    props.mindMap.view.setScale(num / 100, cx, cy)
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
    cursor: pointer;
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
