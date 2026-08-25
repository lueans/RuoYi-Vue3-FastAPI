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
  if (item?.action) {
    actions.setActiveSidebar(null)
    bus.emit(item.action)
    return
  }
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
  if (item?.action) return false
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
  const workspaceBottom = Number.parseFloat(
    editorShell
      ? getComputedStyle(editorShell).getPropertyValue('--mindmap-workspace-bottom')
      : ''
  )
  const resolvedTop = Number.isFinite(shellTop) ? shellTop : 52
  const resolvedBottom = Number.isFinite(workspaceBottom) ? workspaceBottom : 30
  maxHeight.value = Math.max(0, window.innerHeight - resolvedTop - resolvedBottom)
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
  top: var(--mindmap-shell-top, 52px);
  bottom: var(--mindmap-workspace-bottom, 30px);
  right: calc(-1 * var(--mindmap-activity-width, 44px));
  z-index: 2000;
  width: var(--mindmap-activity-width, 44px);
  transition: right 0.2s ease;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  background: #f4f5f7;
  border-left: 1px solid #e3e6ea;
  box-sizing: border-box;

  &.isDark {
    .trigger {
      background-color: #25282d;
      border-color: #3d4046;
      box-shadow: none;

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
    right: 0;
  }

  &.hasActive {
    right: 0;
  }

  &.hasInspector {
    display: flex;
  }

  .toggleShowBtn {
    display: none;

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
    width: 100%;
    height: 100%;
    padding-top: 6px;
    border: 0;
    background-color: transparent;
    box-shadow: none;
    border-radius: 0;
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
      height: 40px;
      display: flex;
      flex-direction: row;
      justify-content: center;
      align-items: center;
      cursor: pointer;
      color: #646a73;
      user-select: none;
      white-space: nowrap;
      transition: all 0.15s ease;
      position: relative;

      &:hover {
        background-color: #fff;
        color: #1f2329;
      }

      &:focus-visible {
        outline: 2px solid #3370ff;
        outline-offset: -3px;
      }

      &.active {
        color: #3370ff;
        font-weight: 600;
        background: #fff;
        box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);

        &::before {
          content: '';
          position: absolute;
          right: 0;
          left: auto;
          top: 9px;
          bottom: 9px;
          width: 2px;
          border-radius: 3px 0 0 3px;
          background: #3370ff;
        }
      }

      .triggerIcon {
        font-size: 17px;
        margin-bottom: 0;
      }

      .triggerName {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
    }
  }
}

@media (max-width: 760px) {
  .sidebarTriggerContainer {
    display: none;
  }
}

</style>
