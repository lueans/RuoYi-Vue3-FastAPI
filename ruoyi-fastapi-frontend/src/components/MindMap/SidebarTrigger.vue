<template>
  <div
    class="sidebarTriggerContainer"
    @click.stop
    :class="{ hasActive: show && activeSidebar, show: show, isDark: isDark }"
    :style="{ maxHeight: maxHeight + 'px' }"
  >
    <div class="toggleShowBtn" :class="{ hide: !show }" @click="show = !show">
      <span class="iconfont iconjiantouyou"></span>
    </div>
    <div class="trigger customScrollbar">
      <div
        class="triggerItem"
        v-for="item in triggerList"
        :key="item.value"
        :class="{ active: activeSidebar === item.value }"
        @click="triggerClick(item)"
      >
        <div class="triggerIcon iconfont" :class="[item.icon]"></div>
        <div class="triggerName">{{ item.name }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { store, actions } from './useStore'
import { sidebarTriggerList } from './config'

const show = ref(true)
const maxHeight = ref(0)
const isDark = computed(() => store.localConfig.isDark)
const activeSidebar = computed(() => store.activeSidebar)
const isReadonly = computed(() => store.isReadonly)

const triggerList = computed(() => {
  let list = [...sidebarTriggerList]
  if (isReadonly.value) {
    list = list.filter(item => {
      return ['outline', 'shortcutKey', 'ai', 'versionHistory', 'collaboratorManager'].includes(item.value)
    })
  }
  return list
})

function triggerClick(item) {
  if (activeSidebar.value === item.value) {
    actions.setActiveSidebar(null)
  } else {
    actions.setActiveSidebar(item.value)
  }
}

function updateSize() {
  const topMargin = 60
  const bottomMargin = 60
  maxHeight.value = window.innerHeight - topMargin - bottomMargin
}

function onResize() {
  updateSize()
}

watch(isReadonly, (val) => {
  if (val) {
    actions.setActiveSidebar(null)
  }
})

onMounted(() => {
  window.addEventListener('resize', onResize)
  updateSize()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})
</script>

<style lang="less" scoped>
.sidebarTriggerContainer {
  position: fixed;
  top: 60px;
  bottom: 60px;
  right: -60px;
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
    right: 0;
  }

  &.hasActive {
    right: 305px;
  }

  .toggleShowBtn {
    position: absolute;
    left: -6px;
    width: 32px;
    height: 56px;
    background: #3370ff;
    top: 50%;
    transform: translateY(-50%);
    cursor: pointer;
    transition: left 0.15s ease;
    z-index: 0;
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
    display: flex;
    align-items: center;
    padding-left: 4px;
    box-shadow: -2px 0 8px rgba(51, 112, 255, 0.2);

    &.hide {
      left: -8px;

      span {
        transform: rotateZ(180deg);
      }
    }

    &:hover {
      left: -16px;
    }

    span {
      color: #fff;
      font-size: 14px;
      transition: transform 0.15s ease;
    }
  }

  .trigger {
    position: relative;
    width: 56px;
    border: 1px solid #dee0e3;
    background-color: #fff;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    border-radius: 8px;
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
      height: 56px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      cursor: pointer;
      color: #646a73;
      user-select: none;
      white-space: nowrap;
      transition: all 0.15s ease;

      &:hover {
        background-color: #f5f6f7;
        color: #1f2329;
      }

      &.active {
        color: #3370ff;
        font-weight: 500;
        background-color: #edf4ff;
      }

      .triggerIcon {
        font-size: 18px;
        margin-bottom: 4px;
      }

      .triggerName {
        font-size: 11px;
        line-height: 1;
      }
    }
  }
}
</style>
