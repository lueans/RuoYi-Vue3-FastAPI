<template>
  <div class="navigatorContainer customScrollbar" :class="{ isDark: isDark }">
    <div class="item">
      <el-tooltip effect="dark" content="回到根节点" placement="top">
        <button class="btn iconfont icondingwei" type="button" aria-label="回到根节点" @click="backToRoot"></button>
      </el-tooltip>
    </div>
    <div class="item">
      <el-tooltip effect="dark" content="搜索节点" placement="top">
        <button class="btn iconfont iconsousuo" type="button" aria-label="搜索节点" @click="showSearch"></button>
      </el-tooltip>
    </div>
    <div class="item">
      <MouseAction :isDark="isDark" :mindMap="mindMap" />
    </div>
    <div class="item">
      <el-tooltip
        effect="dark"
        :content="openMiniMap ? '关闭小地图' : '开启小地图'"
        placement="top"
      >
        <button
          class="btn iconfont icondaohang1"
          type="button"
          :aria-label="openMiniMap ? '关闭小地图' : '开启小地图'"
          :aria-pressed="openMiniMap"
          @click="toggleMiniMap"
        ></button>
      </el-tooltip>
    </div>
    <div v-if="!lockedReadonly" class="item">
      <el-tooltip
        effect="dark"
        :content="isReadonly ? '切换为编辑模式' : '切换为只读模式'"
        placement="top"
      >
        <button
          class="btn iconfont"
          type="button"
          :aria-label="isReadonly ? '切换为编辑模式' : '切换为只读模式'"
          :aria-pressed="isReadonly"
          :class="[isReadonly ? 'iconyanjing' : 'iconbianji1']"
          @click="readonlyChange"
        ></button>
      </el-tooltip>
    </div>
    <div class="item">
      <Fullscreen :isDark="isDark" :mindMap="mindMap" />
    </div>
    <div class="item groupBreak">
      <Scale :isDark="isDark" :mindMap="mindMap" />
    </div>
    <div class="item">
      <el-tooltip effect="dark" :content="isDark ? '切换浅色画布' : '切换深色画布'" placement="top">
        <button
          class="btn iconfont"
          type="button"
          :aria-label="isDark ? '切换浅色画布' : '切换深色画布'"
          :aria-pressed="isDark"
          :class="[isDark ? 'iconmoon_line' : 'iconlieri']"
          @click="toggleDark"
        ></button>
      </el-tooltip>
    </div>
    <div class="item">
      <Demonstrate :isDark="isDark" :mindMap="mindMap" />
    </div>
    <div class="item">
      <el-dropdown @command="handleCommand">
        <button class="btn el-icon-more" type="button" aria-label="更多编辑器操作">
          <el-icon><MoreFilled /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="shortcutKey">
              <span class="iconfont iconjianpan"></span>
              快捷键
            </el-dropdown-item>
            <el-dropdown-item command="setting">
              <span class="iconfont iconshezhi"></span>
              编辑器设置
            </el-dropdown-item>
            <el-dropdown-item command="fitCanvas" :disabled="lockedReadonly">
              <span class="iconfont iconzhengli"></span>
              一键整理布局
            </el-dropdown-item>
            <el-dropdown-item disabled>
              当前：v{{ version }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup>
import { MoreFilled } from '@element-plus/icons-vue'
import Scale from './Scale.vue'
import Fullscreen from './Fullscreen.vue'
import MouseAction from './MouseAction.vue'
import Demonstrate from './Demonstrate.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null },
  lockedReadonly: { type: Boolean, default: false }
})

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)

const openMiniMap = ref(false)
const version = ref('0.0.0')

// Try to get version from simple-mind-map package
onMounted(() => {
  import('@mind-map/package.json').then(pkg => {
    version.value = pkg.version || pkg.default?.version || '0.0.0'
  }).catch(() => {
    version.value = '0.0.0'
  })
})

function readonlyChange() {
  const newVal = !isReadonly.value
  actions.setIsReadonly(newVal)
  props.mindMap?.setMode(newVal ? 'readonly' : 'edit')
}

function toggleMiniMap() {
  openMiniMap.value = !openMiniMap.value
  bus.emit('toggle_mini_map', openMiniMap.value)
}

function showSearch() {
  bus.emit('show_search')
}

function toggleDark() {
  actions.setLocalConfig({
    isDark: !isDark.value
  })
}

function handleCommand(command) {
  if (command === 'shortcutKey') {
    actions.setActiveSidebar('shortcutKey')
    nextTick(() => bus.emit('focusActiveSidebar'))
    return
  }
  if (command === 'setting') {
    actions.setActiveSidebar('setting')
    nextTick(() => bus.emit('focusActiveSidebar'))
    return
  }
  if (command === 'fitCanvas') {
    if (props.lockedReadonly) return
    bus.emit('execCommand', 'RESET_LAYOUT')
  }
}

function backToRoot() {
  props.mindMap?.renderer?.setRootNodeCenter()
}
</script>

<style lang="less" scoped>
.navigatorContainer {
  padding: 0 7px;
  position: fixed;
  left: 16px;
  bottom: 16px;
  z-index: 2000;
  background: #fff;
  border-radius: 11px;
  box-shadow: 0 8px 24px rgba(31, 35, 41, 0.1), 0 1px 3px rgba(31, 35, 41, 0.06);
  border: 1px solid #e2e5ea;
  height: 42px;
  font-size: 12px;
  display: flex;
  align-items: center;

  &.isDark {
    background: #2a2d32;
    border-color: #3d4046;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);

    .item {
      a {
        color: hsla(0, 0%, 100%, 0.7);
        &:hover { color: hsla(0, 0%, 100%, 0.9); }
      }
      .btn {
        color: hsla(0, 0%, 100%, 0.7);
        &:hover { color: hsla(0, 0%, 100%, 0.9); background: hsla(0, 0%, 100%, 0.08); }
      }
    }
  }

  .item {
    margin-right: 2px;
    &:last-of-type {
      margin-right: 0;
    }

    &.groupBreak {
      position: relative;
      margin-left: 7px;

      &::before {
        content: '';
        position: absolute;
        left: -5px;
        top: 7px;
        width: 1px;
        height: 18px;
        background: #e4e7eb;
      }
    }

    a {
      color: #646a73;
      text-decoration: none;
      transition: color 0.15s;
      &:hover { color: #1f2329; }
    }

    .btn {
      border: 0;
      padding: 0;
      background: transparent;
      font-family: inherit;
      cursor: pointer;
      font-size: 18px;
      width: 28px;
      height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 7px;
      transition: all 0.15s;
      color: #646a73;
      &:hover {
        background: #f5f6f7;
        color: #1f2329;
      }
      &:focus-visible {
        outline: 2px solid #3370ff;
        outline-offset: 1px;
      }
      &:active {
        background: #edf4ff;
        color: #3370ff;
      }
    }
  }
}

@media screen and (max-width: 700px) {
  .navigatorContainer {
    left: 16px;
    overflow-x: auto;
    overflow-y: hidden;
    height: 52px;
  }
}
</style>
