<template>
  <div class="colorContainer" :class="{ isDark: isDark }">
    <div class="colorList">
      <span
        class="colorItem iconfont"
        v-for="item in colorList"
        :key="item"
        :style="{ backgroundColor: item }"
        :class="{ icontouming: item === 'transparent' }"
        @click="clickColorItem(item)"
      ></span>
    </div>
    <div class="moreColor">
      <span>更多颜色</span>
      <el-color-picker
        size="small"
        show-alpha
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
    width: 15px;
    height: 15px;
    margin-right: 5px;
    margin-bottom: 5px;
    cursor: pointer;
    border: 1px solid #e8e8e8;
    border-radius: 2px;

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
