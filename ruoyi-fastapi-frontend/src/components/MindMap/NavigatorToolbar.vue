<template>
  <div class="navigatorContainer customScrollbar" :class="{ isDark: isDark }">
    <div class="item">
      <el-tooltip effect="dark" content="回到根节点" placement="top">
        <div class="btn iconfont icondingwei" @click="backToRoot"></div>
      </el-tooltip>
    </div>
    <div class="item">
      <div class="btn iconfont iconsousuo" @click="showSearch"></div>
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
        <div class="btn iconfont icondaohang1" @click="toggleMiniMap"></div>
      </el-tooltip>
    </div>
    <div class="item">
      <el-tooltip
        effect="dark"
        :content="isReadonly ? '切换为编辑模式' : '切换为只读模式'"
        placement="top"
      >
        <div
          class="btn iconfont"
          :class="[isReadonly ? 'iconyanjing' : 'iconbianji1']"
          @click="readonlyChange"
        ></div>
      </el-tooltip>
    </div>
    <div class="item">
      <Fullscreen :isDark="isDark" :mindMap="mindMap" />
    </div>
    <div class="item">
      <Scale :isDark="isDark" :mindMap="mindMap" />
    </div>
    <div class="item">
      <div
        class="btn iconfont"
        :class="[isDark ? 'iconmoon_line' : 'iconlieri']"
        @click="toggleDark"
      ></div>
    </div>
    <div class="item">
      <Demonstrate :isDark="isDark" :mindMap="mindMap" />
    </div>
    <div class="item">
      <el-dropdown @command="handleCommand">
        <div class="btn el-icon-more">
          <el-icon><MoreFilled /></el-icon>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="shortcutKey">
              <span class="iconfont iconjianpan"></span>
              快捷键
            </el-dropdown-item>
            <el-dropdown-item command="github">
              <span class="iconfont icongithub"></span>
              Github
            </el-dropdown-item>
            <el-dropdown-item command="site">
              <span class="iconfont iconwangzhan"></span>
              官方网站
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
  mindMap: { type: Object, default: null }
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
    return
  }
  let url = ''
  switch (command) {
    case 'github':
      url = 'https://github.com/wanglin2/mind-map'
      break
    case 'site':
      url = 'https://wanglin2.github.io/mind-map-docs/'
      break
    default:
      break
  }
  if (url) {
    const a = document.createElement('a')
    a.href = url
    a.target = '_blank'
    a.click()
  }
}

function backToRoot() {
  props.mindMap?.renderer?.setRootNodeCenter()
}
</script>

<style lang="less" scoped>
.navigatorContainer {
  padding: 0 8px;
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 2000;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08), 0 0 1px rgba(0, 0, 0, 0.06);
  border: 1px solid #dee0e3;
  height: 40px;
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
    margin-right: 4px;
    &:last-of-type {
      margin-right: 0;
    }

    a {
      color: #646a73;
      text-decoration: none;
      transition: color 0.15s;
      &:hover { color: #1f2329; }
    }

    .btn {
      cursor: pointer;
      font-size: 18px;
      width: 28px;
      height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      transition: all 0.15s;
      color: #646a73;
      &:hover {
        background: #f5f6f7;
        color: #1f2329;
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
