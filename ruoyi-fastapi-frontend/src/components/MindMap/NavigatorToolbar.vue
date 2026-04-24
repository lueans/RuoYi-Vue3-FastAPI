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
  padding: 0 12px;
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 2000;
  background: hsla(0, 0%, 100%, 0.8);
  border-radius: 5px;
  opacity: 0.8;
  height: 44px;
  font-size: 12px;
  display: flex;
  align-items: center;

  &.isDark {
    background: #262a2e;

    .item {
      a {
        color: hsla(0, 0%, 100%, 0.6);
      }

      .btn {
        color: hsla(0, 0%, 100%, 0.6);
      }
    }
  }

  .item {
    margin-right: 20px;

    &:last-of-type {
      margin-right: 0;
    }

    a {
      color: #303133;
      text-decoration: none;
    }

    .btn {
      cursor: pointer;
      font-size: 18px;
    }
  }
}

@media screen and (max-width: 700px) {
  .navigatorContainer {
    left: 20px;
    overflow-x: auto;
    overflow-y: hidden;
    height: 60px;
  }
}
</style>
