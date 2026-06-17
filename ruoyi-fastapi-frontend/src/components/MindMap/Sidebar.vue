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
  top: 52px;
  bottom: 0;
  width: 300px;
  background-color: #fff;
  border-left: 1px solid #dee0e3;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  transition: right 0.25s ease;
  z-index: 2001;

  &.isDark {
    background-color: #2a2d32;
    border-left-color: #3d4046;
    box-shadow: -4px 0 16px rgba(0, 0, 0, 0.2);

    .sidebarHeader {
      border-bottom-color: #3d4046;
      color: #e5e6eb;
    }

    .closeBtn {
      color: #8f959e;
      &:hover {
        color: #e5e6eb;
        background: hsla(0, 0%, 100%, 0.08);
      }
    }

    .sidebarContent {
      &::-webkit-scrollbar-thumb {
        background: #4a4d52;
      }
    }
  }

  &.show {
    right: 0;
  }

  .closeBtn {
    position: absolute;
    right: 12px;
    top: 8px;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    cursor: pointer;
    z-index: 1;
    color: #8f959e;
    border-radius: 6px;
    transition: all 0.15s;
    &:hover {
      color: #1f2329;
      background: #f5f6f7;
    }
  }

  .sidebarHeader {
    width: 100%;
    height: 44px;
    border-bottom: 1px solid #f0f1f3;
    display: flex;
    justify-content: center;
    align-items: center;
    flex-grow: 0;
    flex-shrink: 0;
    font-size: 14px;
    font-weight: 500;
    color: #1f2329;
    letter-spacing: 0.2px;
  }

  .sidebarContent {
    width: 100%;
    height: 100%;
    overflow: auto;
    &::-webkit-scrollbar {
      width: 4px;
    }
    &::-webkit-scrollbar-track {
      background: transparent;
    }
    &::-webkit-scrollbar-thumb {
      background: #d4d6d9;
      border-radius: 4px;
      &:hover {
        background: #b0b3b8;
      }
    }
  }
}
</style>
