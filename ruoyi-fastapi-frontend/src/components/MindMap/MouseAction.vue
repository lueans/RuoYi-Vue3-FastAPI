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
      <button
        type="button"
        class="btn iconfont"
        :class="[useLeftKeySelectionRightKeyDrag ? 'iconmouseR' : 'iconmouseL']"
        :aria-label="actionLabel"
        :aria-pressed="useLeftKeySelectionRightKeyDrag"
        @click="toggleAction"
      ></button>
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
const actionLabel = computed(() => useLeftKeySelectionRightKeyDrag.value
  ? '切换为左键拖动画布、右键框选节点'
  : '切换为左键框选节点、右键拖动画布')

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
    width: 28px;
    height: 28px;
    padding: 0;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font-size: 18px;

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 1px;
    }
  }
}
</style>
