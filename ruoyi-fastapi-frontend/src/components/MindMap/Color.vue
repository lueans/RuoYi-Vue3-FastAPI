<template>
  <div class="colorContainer" :class="{ isDark: isDark }">
    <div class="colorList">
      <button
        type="button"
        class="colorItem iconfont"
        v-for="item in colorList"
        :key="item"
        :style="{ backgroundColor: item }"
        :class="{ icontouming: item === 'transparent' }"
        :aria-label="item === 'transparent' ? '选择透明色' : `选择颜色 ${item}`"
        :aria-pressed="isSelected(item)"
        :title="item === 'transparent' ? '透明色' : item"
        @click="clickColorItem(item)"
      ></button>
    </div>
    <div class="moreColor">
      <span>更多颜色</span>
      <el-color-picker
        size="small"
        show-alpha
        aria-label="选择自定义颜色"
        v-model="selectColor"
        @change="changeColor"
      />
    </div>
  </div>
</template>

<script setup>
import { colorList } from './config'
import { store } from './useStore'

const props = defineProps({
  color: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['change'])

const isDark = computed(() => store.localConfig.isDark)
const selectColor = ref(props.color || '')

watch(() => props.color, (val) => {
  selectColor.value = val
})

function clickColorItem(color) {
  emit('change', color)
}

function isSelected(color) {
  return String(props.color || '').toLowerCase() === String(color).toLowerCase()
}

function changeColor() {
  emit('change', selectColor.value)
}
</script>

<style lang="less" scoped>
.colorContainer {
  &.isDark {
    .moreColor {
      color: hsla(0, 0%, 100%, 0.6);
    }
  }
}

.colorList {
  width: 240px;
  display: flex;
  flex-wrap: wrap;

  .colorItem {
    display: flex;
    justify-content: center;
    align-items: center;
    width: 28px;
    height: 28px;
    padding: 0;
    margin-right: 6px;
    margin-bottom: 6px;
    cursor: pointer;
    border: 1px solid #e8e8e8;
    border-radius: 2px;

    &:focus-visible {
      outline: 2px solid #409eff;
      outline-offset: 2px;
    }

    &[aria-pressed='true'] {
      box-shadow: 0 0 0 2px #409eff;
    }

    &:hover {
      transform: scale(1.2);
    }
  }
}

.moreColor {
  display: flex;
  align-items: center;
  margin-top: 5px;

  span {
    margin-right: 5px;
    font-size: 12px;
    white-space: nowrap;
  }
}
</style>
