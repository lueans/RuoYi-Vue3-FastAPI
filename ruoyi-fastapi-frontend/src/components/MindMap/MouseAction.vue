<template>
  <div class="mouseActionContainer" :class="{ isDark: isDark }">
    <el-tooltip
      effect="dark"
      :content="
        useLeftKeySelectionRightKeyDrag
          ? '当前：左键框选节点，右键拖动画布'
          : '当前：左键拖动画布，右键框选节点'
      "
      placement="top"
    >
      <div
        class="btn iconfont"
        :class="[useLeftKeySelectionRightKeyDrag ? 'iconmouseR' : 'iconmouseL']"
        @click="toggleAction"
      ></div>
    </el-tooltip>
  </div>
</template>

<script setup>
import { store, actions } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null },
  isDark: { type: Boolean, default: false }
})

const useLeftKeySelectionRightKeyDrag = computed(
  () => store.localConfig.useLeftKeySelectionRightKeyDrag
)

function toggleAction() {
  const val = !useLeftKeySelectionRightKeyDrag.value
  props.mindMap?.updateConfig({
    useLeftKeySelectionRightKeyDrag: val
  })
  actions.setLocalConfig({
    useLeftKeySelectionRightKeyDrag: val
  })
}
</script>

<style lang="less" scoped>
.mouseActionContainer {
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
    font-size: 18px;
  }
}
</style>
