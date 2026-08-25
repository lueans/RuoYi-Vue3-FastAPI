<template>
  <div
    class="sidebarContainer"
    @click.stop
    :class="{ show: show, isDark: isDark, isLeft }"
    :style="{ zIndex: zIndex }"
    :inert="!show"
    :aria-hidden="show ? undefined : 'true'"
    :aria-labelledby="title ? titleId : undefined"
    :aria-label="title ? undefined : '脑图侧栏'"
    role="complementary"
    @keydown.esc.stop="onEscape"
  >
    <button
      ref="closeButtonRef"
      class="closeBtn el-icon-close"
      type="button"
      :aria-label="`关闭${title || '侧栏'}`"
      @click="onCloseClick"
    >
      <el-icon><Close /></el-icon>
    </button>
    <div class="sidebarHeader" :id="titleId" v-if="title" role="heading" aria-level="2">
      {{ title }}
    </div>
    <div class="sidebarContent customScrollbar" ref="bodyRef">
      <slot></slot>
    </div>
  </div>
</template>

<script setup>
import { Close } from '@element-plus/icons-vue'
import { actions, store } from './useStore'
import bus from './useEventBus'

const props = defineProps({
  title: { type: String, default: '' },
  openOnMount: { type: Boolean, default: false },
  placement: {
    type: String,
    default: 'right',
    validator: value => ['left', 'right'].includes(value),
  },
})

const show = ref(false)
const zIndex = ref(2001)
const bodyRef = ref(null)
const closeButtonRef = ref(null)
const titleId = `mindmap-sidebar-title-${Math.random().toString(36).slice(2, 10)}`
const isDark = computed(() => store.localConfig.isDark)
const isLeft = computed(() => props.placement === 'left')
let focusReturnTarget = null

function open() {
  if (!show.value) focusReturnTarget = document.activeElement
  show.value = true
  zIndex.value = actions.nextSidebarZIndex()
}

function close() {
  show.value = false
}

function onCloseClick() {
  const sidebarName = store.activeSidebar
  const returnTarget = focusReturnTarget
  show.value = false
  actions.setActiveSidebar(null)
  nextTick(() => {
    if (returnTarget?.isConnected && !returnTarget.closest?.('[inert]')) {
      returnTarget.focus?.()
    } else {
      bus.emit('focusSidebarTrigger', sidebarName)
    }
  })
}

function onEscape() {
  onCloseClick()
}

function handleCloseSidebar() {
  if (show.value && store.activeSidebar) {
    actions.setActiveSidebar(null)
  }
  show.value = false
}

function focusWhenOpen() {
  if (show.value) closeButtonRef.value?.focus()
}

function getEl() {
  return bodyRef.value
}

onMounted(() => {
  bus.on('closeSideBar', handleCloseSidebar)
  bus.on('focusActiveSidebar', focusWhenOpen)
  if (props.openOnMount) open()
})

onBeforeUnmount(() => {
  bus.off('closeSideBar', handleCloseSidebar)
  bus.off('focusActiveSidebar', focusWhenOpen)
})

defineExpose({ show, open, close, bodyRef, getEl })
</script>

<style lang="less" scoped>
.sidebarContainer {
  position: fixed;
  right: calc(-1 * var(--mindmap-side-panel-width, 300px));
  top: var(--mindmap-shell-top, 52px);
  bottom: var(--mindmap-workspace-bottom, 30px);
  width: var(--mindmap-side-panel-width, 300px);
  background-color: #fff;
  border-left: 1px solid #e2e5ea;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  transition: right 0.25s ease;
  z-index: 2001;

  &.isDark {
    background-color: #2a2d32;
    border-left-color: #3d4046;
    box-shadow: none;

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
    right: var(--mindmap-activity-width, 44px);
  }

  &.isLeft {
    right: auto;
    left: calc(-1 * var(--mindmap-side-panel-width, 300px));
    border-right: 1px solid #e2e5ea;
    border-left: 0;
    transition: left 0.25s ease;

    &.show {
      right: auto;
      left: var(--mindmap-activity-width, 44px);
    }

    &.isDark {
      border-right-color: #3d4046;
    }
  }

  .closeBtn {
    position: absolute;
    right: 10px;
    top: 6px;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    cursor: pointer;
    z-index: 1;
    padding: 0;
    border: 0;
    background: transparent;
    color: #8f959e;
    border-radius: 6px;
    transition: all 0.15s;
    &:hover {
      color: #1f2329;
      background: #f5f6f7;
    }
    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 2px;
    }
  }

  .sidebarHeader {
    width: 100%;
    height: 40px;
    border-bottom: 1px solid #eef0f3;
    display: flex;
    justify-content: flex-start;
    align-items: center;
    flex-grow: 0;
    flex-shrink: 0;
    padding: 0 46px 0 14px;
    font-size: 13px;
    font-weight: 600;
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

@media (max-width: 1439px) and (min-width: 761px) {
  .sidebarContainer.show {
    box-shadow: -8px 0 24px rgba(31, 35, 41, 0.1);
  }

  .sidebarContainer.isLeft.show {
    box-shadow: 8px 0 24px rgba(31, 35, 41, 0.1);
  }
}

@media (max-width: 760px) {
  .sidebarContainer {
    right: -100%;
    bottom: 52px;
    width: min(100%, 300px);

    &.show {
      right: 0;
    }

    &.isLeft {
      right: auto;
      left: -100%;

      &.show {
        right: auto;
        left: 0;
      }
    }
  }
}
</style>
