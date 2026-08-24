<template>
  <div
    class="sidebarTriggerContainer"
    @click.stop
    :class="{
      hasActive: show && activeSidebar,
      hasInspector: show && isPropertyInspectorActive,
      show,
      isDark
    }"
    :style="{ maxHeight: maxHeight + 'px' }"
  >
    <button
      class="toggleShowBtn"
      :class="{ hide: !show }"
      type="button"
      :aria-label="show ? '收起侧边工具栏' : '展开侧边工具栏'"
      :aria-expanded="show"
      @click="show = !show"
    >
      <span class="iconfont iconjiantouyou"></span>
    </button>
    <div class="trigger customScrollbar">
      <button
        class="triggerItem"
        v-for="item in triggerList"
        :key="item.value"
        type="button"
        :class="{ active: isTriggerActive(item) }"
        :aria-label="item.name"
        :aria-pressed="isTriggerActive(item)"
        :ref="el => setTriggerRef(item.value, el)"
        @click="triggerClick(item)"
      >
        <div class="triggerIcon iconfont" :class="[item.icon]"></div>
        <div class="triggerName">{{ item.name }}</div>
      </button>
    </div>
  </div>
</template>

<script setup>
import {
  store,
  actions,
  isMindmapSidebarReadonlySafe,
} from './useStore'
import { sidebarTriggerList } from './config'
import bus from './useEventBus'

const show = ref(true)
const maxHeight = ref(0)
const isDark = computed(() => store.localConfig.isDark)
const activeSidebar = computed(() => store.activeSidebar)
const propertySidebarNames = new Set(['nodeStyle', 'baseStyle', 'structure', 'theme'])
const isPropertyInspectorActive = computed(() => propertySidebarNames.has(activeSidebar.value))
const isReadonly = computed(() => store.isReadonly)
const canManageCollaborators = computed(() => store.canManageCollaborators)
const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
const readonlyHeaderSidebarNames = new Set(['outline', 'versionHistory'])
const triggerRefs = new Map()

const triggerList = computed(() => {
  let list = [...sidebarTriggerList]
  if (!canManageCollaborators.value) {
    list = list.filter(item => item.value !== 'collaboratorManager')
  }
  if (isReadonly.value) {
    list = list.filter(item => isMindmapSidebarReadonlySafe(item.value))
    if (viewportWidth.value > 760) {
      list = list.filter(item => (
        !readonlyHeaderSidebarNames.has(item.value)
        || activeSidebar.value === item.value
      ))
    }
  }
  return list
})

function triggerClick(item) {
  if (isReadonly.value && !isMindmapSidebarReadonlySafe(item?.value)) return
  if (isTriggerActive(item)) {
    actions.setActiveSidebar(null)
  } else {
    const targetSidebar = item.value === 'nodeStyle'
      ? resolveFormatSidebar()
      : item.value
    actions.setActiveSidebar(targetSidebar)
    nextTick(() => bus.emit('focusActiveSidebar'))
  }
}

function resolveFormatSidebar() {
  const hasActiveNodes = (store.mindMap?.renderer?.activeNodeList || []).length > 0
  if (hasActiveNodes) return 'nodeStyle'
  return ['baseStyle', 'structure', 'theme'].includes(store.lastPropertySidebar)
    ? store.lastPropertySidebar
    : 'baseStyle'
}

function isTriggerActive(item) {
  if (item?.value === 'nodeStyle') return isPropertyInspectorActive.value
  return activeSidebar.value === item?.value
}

function setTriggerRef(name, element) {
  if (element) {
    triggerRefs.set(name, element)
  } else {
    triggerRefs.delete(name)
  }
}

function focusTrigger(name) {
  triggerRefs.get(name)?.focus()
}

function updateSize() {
  viewportWidth.value = window.innerWidth
  const editorShell = document.querySelector('.mindmap-edit-page')
  const shellTop = Number.parseFloat(
    editorShell
      ? getComputedStyle(editorShell).getPropertyValue('--mindmap-shell-top')
      : ''
  )
  const topMargin = (Number.isFinite(shellTop) ? shellTop : 80) + 24
  const bottomMargin = 36
  maxHeight.value = Math.max(0, window.innerHeight - topMargin - bottomMargin)
}

function onResize() {
  updateSize()
}

watch([isReadonly, canManageCollaborators], ([readonly, canManage]) => {
  if (
    (readonly && !isMindmapSidebarReadonlySafe(activeSidebar.value))
    || (!canManage && activeSidebar.value === 'collaboratorManager')
  ) {
    actions.setActiveSidebar(null)
  }
})

onMounted(() => {
  window.addEventListener('resize', onResize)
  bus.on('focusSidebarTrigger', focusTrigger)
  updateSize()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  bus.off('focusSidebarTrigger', focusTrigger)
  triggerRefs.clear()
})
</script>

<style lang="less" scoped>
.sidebarTriggerContainer {
  position: fixed;
  top: calc(var(--mindmap-shell-top, 80px) + 12px);
  bottom: 18px;
  right: -72px;
  z-index: 2000;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  justify-content: center;

  &.isDark {
    .trigger {
      background-color: #2a2d32;
      border-color: #3d4046;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);

      .triggerItem {
        color: hsla(0, 0%, 100%, 0.6);

        &:hover {
          background-color: hsla(0, 0%, 100%, 0.06);
        }

        &.active {
          color: #5b8def;
          background-color: hsla(220, 70%, 60%, 0.1);
        }
      }
    }

    .toggleShowBtn {
      background: #3370ff;
    }
  }

  &.show {
    right: 12px;
  }

  &.hasActive {
    right: 360px;
  }

  &.hasInspector {
    display: none;
  }

  .toggleShowBtn {
    position: absolute;
    left: -6px;
    width: 30px;
    height: 52px;
    background: #3370ff;
    top: 50%;
    transform: translateY(-50%);
    cursor: pointer;
    transition: left 0.15s ease;
    z-index: 0;
    border-top-left-radius: 10px;
    border-bottom-left-radius: 10px;
    display: flex;
    align-items: center;
    padding-left: 4px;
    box-shadow: -2px 0 8px rgba(51, 112, 255, 0.2);
    border: 0;

    &.hide {
      left: -8px;

      span {
        transform: rotateZ(180deg);
      }
    }

    &:hover {
      left: -16px;
    }

    &:focus-visible {
      outline: 2px solid #245bdb;
      outline-offset: 2px;
    }

    span {
      color: #fff;
      font-size: 14px;
      transition: transform 0.15s ease;
    }
  }

  .trigger {
    position: relative;
    width: 62px;
    border: 1px solid #e2e5ea;
    background-color: rgba(255, 255, 255, 0.97);
    box-shadow: 0 8px 24px rgba(31, 35, 41, 0.09), 0 1px 3px rgba(31, 35, 41, 0.06);
    border-radius: 12px;
    max-height: 100%;
    overflow-y: auto;
    overflow-x: hidden;

    &::-webkit-scrollbar {
      width: 3px;
    }
    &::-webkit-scrollbar-thumb {
      background: #d4d6d9;
      border-radius: 3px;
    }

    .triggerItem {
      width: 100%;
      padding: 0;
      border: 0;
      background: transparent;
      font: inherit;
      height: 52px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      cursor: pointer;
      color: #646a73;
      user-select: none;
      white-space: nowrap;
      transition: all 0.15s ease;
      position: relative;

      &:hover {
        background-color: #f5f6f7;
        color: #1f2329;
      }

      &:focus-visible {
        outline: 2px solid #3370ff;
        outline-offset: -3px;
      }

      &.active {
        color: #3370ff;
        font-weight: 600;
        background: linear-gradient(90deg, #edf4ff 0%, #f4f7ff 100%);

        &::before {
          content: '';
          position: absolute;
          left: 0;
          top: 12px;
          bottom: 12px;
          width: 3px;
          border-radius: 0 3px 3px 0;
          background: #3370ff;
        }
      }

      .triggerIcon {
        font-size: 17px;
        margin-bottom: 3px;
      }

      .triggerName {
        font-size: 10px;
        line-height: 1;
      }
    }
  }
}

</style>
