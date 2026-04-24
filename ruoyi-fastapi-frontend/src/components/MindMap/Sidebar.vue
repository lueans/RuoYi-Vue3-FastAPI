<template>
  <div
    class="sidebarContainer"
    @click.stop
    :class="{ show: show, isDark: isDark }"
    :style="{ zIndex: zIndex }"
  >
    <span class="closeBtn el-icon-close" @click="onCloseClick">
      <el-icon><Close /></el-icon>
    </span>
    <div class="sidebarHeader" v-if="title">
      {{ title }}
    </div>
    <div class="sidebarContent customScrollbar" ref="bodyRef">
      <slot></slot>
    </div>
  </div>
</template>

<script setup>
import { Close } from '@element-plus/icons-vue'
import { actions } from './useStore'
import { store } from './useStore'
import bus from './useEventBus'

defineProps({
  title: { type: String, default: '' }
})

const show = ref(false)
const zIndex = ref(2001)
const bodyRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)

function open() {
  show.value = true
  zIndex.value = actions.nextSidebarZIndex()
}

function close() {
  show.value = false
}

function onCloseClick() {
  show.value = false
  actions.setActiveSidebar(null)
}

function handleCloseSidebar() {
  show.value = false
}

function getEl() {
  return bodyRef.value
}

onMounted(() => {
  bus.on('closeSideBar', handleCloseSidebar)
})

onBeforeUnmount(() => {
  bus.off('closeSideBar', handleCloseSidebar)
})

defineExpose({ show, open, close, bodyRef, getEl })
</script>

<style lang="less" scoped>
.sidebarContainer {
  position: fixed;
  right: -300px;
  top: 110px;
  bottom: 0;
  width: 300px;
  background-color: #fff;
  border-left: 1px solid #e8e8e8;
  display: flex;
  flex-direction: column;
  transition: all 0.3s;
  z-index: 2001;

  &.isDark {
    background-color: #262a2e;
    border-left-color: hsla(0, 0%, 100%, 0.1);

    .sidebarHeader {
      border-bottom-color: hsla(0, 0%, 100%, 0.1);
      color: #fff;
    }

    .closeBtn {
      color: #fff;
    }
  }

  &.show {
    right: 0;
  }

  .closeBtn {
    position: absolute;
    right: 20px;
    top: 12px;
    font-size: 20px;
    cursor: pointer;
    z-index: 1;
  }

  .sidebarHeader {
    width: 100%;
    height: 44px;
    border-bottom: 1px solid #e8e8e8;
    display: flex;
    justify-content: center;
    align-items: center;
    flex-grow: 0;
    flex-shrink: 0;
  }

  .sidebarContent {
    width: 100%;
    height: 100%;
    overflow: auto;
  }
}
</style>
