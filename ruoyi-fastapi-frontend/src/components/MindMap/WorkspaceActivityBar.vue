<template>
  <nav class="workspaceActivityBar" :class="{ isDark }" aria-label="脑图工作区导航">
    <div class="activityGroup">
      <button
        class="activityButton"
        :class="{ active: searchOpen }"
        type="button"
        :aria-label="searchOpen ? '关闭节点搜索' : '打开节点搜索'"
        :aria-pressed="searchOpen"
        title="搜索与替换"
        @click="toggleSearch"
      >
        <span class="iconfont iconsousuo" aria-hidden="true" />
      </button>
      <button
        class="activityButton"
        :class="{ active: activeSidebar === 'outline' }"
        type="button"
        aria-label="节点大纲"
        :aria-pressed="activeSidebar === 'outline'"
        title="节点大纲"
        @click="toggleSidebar('outline')"
      >
        <span class="iconfont iconfuhao-dagangshu" aria-hidden="true" />
      </button>
      <button
        class="activityButton"
        :class="{ active: activeSidebar === 'versionHistory' }"
        type="button"
        aria-label="版本历史"
        :aria-pressed="activeSidebar === 'versionHistory'"
        title="版本历史"
        @click="toggleSidebar('versionHistory')"
      >
        <span class="iconfont iconlishijilu" aria-hidden="true" />
      </button>
      <button
        v-if="canManageCollaborators && !isReadonly"
        class="activityButton"
        :class="{ active: activeSidebar === 'collaboratorManager' }"
        type="button"
        aria-label="协作者管理"
        :aria-pressed="activeSidebar === 'collaboratorManager'"
        title="协作者管理"
        @click="toggleSidebar('collaboratorManager')"
      >
        <span class="iconfont iconxiezuo" aria-hidden="true" />
      </button>
    </div>

    <div class="activityGroup activityGroupBottom">
      <button
        class="activityButton"
        :class="{ active: activeSidebar === 'shortcutKey' }"
        type="button"
        aria-label="快捷键"
        :aria-pressed="activeSidebar === 'shortcutKey'"
        title="快捷键"
        @click="toggleSidebar('shortcutKey')"
      >
        <span class="iconfont iconjianpan" aria-hidden="true" />
      </button>
    </div>
  </nav>
</template>

<script setup>
import bus from './useEventBus'
import { actions, store, isMindmapSidebarReadonlySafe } from './useStore'

const searchOpen = ref(false)
const activeSidebar = computed(() => store.activeSidebar)
const isReadonly = computed(() => store.isReadonly)
const canManageCollaborators = computed(() => store.canManageCollaborators)
const isDark = computed(() => store.localConfig.isDark)

function onSearchVisibilityChange(visible) {
  searchOpen.value = visible === true
}

function toggleSearch() {
  bus.emit(searchOpen.value ? 'hide_search' : 'show_search')
}

function toggleSidebar(sidebarName) {
  if (isReadonly.value && !isMindmapSidebarReadonlySafe(sidebarName)) return
  const nextSidebar = activeSidebar.value === sidebarName ? null : sidebarName
  if (!actions.setActiveSidebar(nextSidebar) || !nextSidebar) return
  nextTick(() => bus.emit('focusActiveSidebar'))
}

onMounted(() => {
  bus.on('searchPanelVisibilityChange', onSearchVisibilityChange)
})

onBeforeUnmount(() => {
  bus.off('searchPanelVisibilityChange', onSearchVisibilityChange)
})
</script>

<style lang="less" scoped>
.workspaceActivityBar {
  position: absolute;
  inset: 0 auto var(--mindmap-workspace-bottom, 30px) 0;
  z-index: 2002;
  width: var(--mindmap-activity-width, 44px);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 6px;
  color: #646a73;
  background: #f4f5f7;
  border-right: 1px solid #e3e6ea;
  box-sizing: border-box;

  &.isDark {
    color: #aeb3bb;
    background: rgba(37, 40, 45, 0.98);
    border-right-color: #3d4046;

    .activityButton:hover {
      color: #fff;
      background: rgba(255, 255, 255, 0.08);
    }

    .activityButton.active {
      color: #8daaff;
      background: rgba(51, 112, 255, 0.16);
    }
  }
}

.activityGroup {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.activityButton {
  position: relative;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 7px;
  color: inherit;
  background: transparent;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;

  .iconfont {
    font-size: 17px;
  }

  &:hover {
    color: #1f2329;
    background: #fff;
    box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);
  }

  &:focus-visible {
    outline: 2px solid #3370ff;
    outline-offset: 1px;
  }

  &.active {
    color: #3370ff;
    background: #fff;
    box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);

    &::before {
      position: absolute;
      top: 7px;
      bottom: 7px;
      left: -6px;
      width: 2px;
      border-radius: 0 3px 3px 0;
      background: #3370ff;
      content: '';
    }
  }
}

@media (max-width: 760px) {
  .workspaceActivityBar {
    display: none;
  }
}
</style>
