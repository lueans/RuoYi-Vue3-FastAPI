<template>
  <Sidebar ref="sidebarRef" title="主题" open-on-mount>
    <div class="themeGroupList" :class="{ isDark: isDark }">
      <el-tabs v-model="activeName" class="tabBox">
        <el-tab-pane
          v-for="group in groupList"
          :key="group.name"
          :label="group.name"
          :name="group.name"
        ></el-tab-pane>
      </el-tabs>
      <div class="themeListTheme customScrollbar">
        <button
          class="themeItem"
          v-for="item in currentList"
          :key="item.value"
          type="button"
          :aria-label="`使用主题：${item.name}`"
          :aria-pressed="item.value === currentTheme"
          :disabled="themeChangePending || isReadonly"
          @click="useTheme(item)"
          :class="{ active: item.value === currentTheme }"
        >
          <div class="imgBox">
            <img :src="item.img || themeImgMap[item.value]" :alt="`${item.name}主题预览`" />
          </div>
          <div class="name">{{ item.name }}</div>
        </button>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store, actions } from './useStore'
import { ElMessageBox } from 'element-plus'

import themeImgMapRaw from 'simple-mind-map-plugin-themes/themeImgMap'
import themeListRaw from 'simple-mind-map-plugin-themes/themeList'

const themeImgMap = themeImgMapRaw || {}
const themeList = themeListRaw || []

const props = defineProps({
  data: { type: [Object, null], default: null },
  mindMap: { type: Object, default: null }
})
const emit = defineEmits(['document-meta-change'])

const sidebarRef = ref(null)
const currentTheme = ref('default')
const activeName = ref('')
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const themeChangePending = ref(false)
let boundMindMap = null
let themeOperationId = 0
let componentAlive = true

const allThemes = ref([
  { name: '默认主题', value: 'default', dark: false },
  ...themeList
].reverse())

const baiduThemes = [
  'default', 'skyGreen', 'classic2', 'classic3', 'classicGreen',
  'classicBlue', 'blueSky', 'brainImpairedPink', 'earthYellow',
  'freshGreen', 'freshRed', 'romanticPurple', 'pinkGrape', 'mint'
]

const groupList = computed(() => {
  const baiduList = []
  const classicsList = []
  allThemes.value.forEach(item => {
    if (baiduThemes.includes(item.value)) {
      baiduList.push(item)
    } else if (!item.dark) {
      classicsList.push(item)
    }
  })
  return [
    { name: '经典', list: classicsList },
    { name: '深色', list: allThemes.value.filter(item => item.dark) },
    { name: '朴素', list: baiduList }
  ]
})

const currentList = computed(() => {
  const group = groupList.value.find(item => item.name === activeName.value)
  return group ? group.list : []
})

// Initialize
if (groupList.value.length > 0) {
  activeName.value = groupList.value[0].name
}

function handleViewThemeChange() {
  if (!props.mindMap) return
  currentTheme.value = props.mindMap.getTheme()
  handleDark()
}

function handleDark() {
  const target = allThemes.value.find(item => item.value === currentTheme.value)
  if (target) {
    actions.setLocalConfig({ isDark: target.dark })
  }
}

async function useTheme(theme) {
  if (!props.mindMap || themeChangePending.value || isReadonly.value) return
  if (theme.value === currentTheme.value) return
  const activeMindMap = props.mindMap
  const operationId = ++themeOperationId
  const isCurrentOperation = () => (
    componentAlive
    && operationId === themeOperationId
    && activeMindMap === props.mindMap
    && store.activeSidebar === 'theme'
    && !isReadonly.value
  )
  const customThemeConfig = activeMindMap.getCustomThemeConfig() || {}
  const hasCustomThemeConfig = Object.keys(customThemeConfig).length > 0
  if (hasCustomThemeConfig) {
    themeChangePending.value = true
    try {
      let config = {}
      try {
        await ElMessageBox.confirm(
          '你当前自定义过基础样式，是否覆盖？',
          '提示',
          {
            confirmButtonText: '覆盖',
            cancelButtonText: '保留',
            type: 'warning',
            distinguishCancelAndClose: true,
          }
        )
      } catch (action) {
        if (action !== 'cancel') return
        config = customThemeConfig
      }
      if (!isCurrentOperation()) return
      changeTheme(theme, config, activeMindMap)
    } finally {
      if (operationId === themeOperationId) themeChangePending.value = false
    }
  } else {
    if (!isCurrentOperation()) return
    changeTheme(theme, customThemeConfig, activeMindMap)
  }
}

function changeTheme(theme, config, targetMindMap = props.mindMap) {
  if (!targetMindMap || targetMindMap !== props.mindMap || isReadonly.value) return
  targetMindMap.setThemeConfig(config, true)
  targetMindMap.setTheme(theme.value)
  emit('document-meta-change', {
    theme: {
      template: theme.value,
      config
    }
  })
  currentTheme.value = theme.value
  handleDark()
}

function bindMindMap(nextMindMap) {
  if (boundMindMap === nextMindMap) return
  boundMindMap?.off('view_theme_change', handleViewThemeChange)
  boundMindMap = nextMindMap || null
  if (boundMindMap) {
    boundMindMap.on('view_theme_change', handleViewThemeChange)
    handleViewThemeChange()
  }
}

onBeforeUnmount(() => {
  componentAlive = false
  themeOperationId += 1
  bindMindMap(null)
})

watch(() => props.mindMap, bindMindMap, { immediate: true })

watch(() => store.activeSidebar, (val) => {
  if (val === 'theme') {
    if (props.mindMap) currentTheme.value = props.mindMap.getTheme()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })
</script>

<style lang="less" scoped>
.themeGroupList {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100%;

  &.isDark {
    .name {
      color: #fff;
    }
  }

  .tabBox {
    flex-shrink: 0;

    :deep(.el-tabs__nav-wrap) {
      display: flex;
      justify-content: center;
    }
  }

  .themeListTheme {
    height: 100%;
    overflow-y: auto;
    padding: 0 20px;

    .themeItem {
      width: 100%;
      cursor: pointer;
      display: block;
      appearance: none;
      background: transparent;
      color: inherit;
      font: inherit;
      border-bottom: 1px solid #e9e9e9;
      margin-bottom: 20px;
      padding-bottom: 20px;
      transition: all 0.2s;
      border: 3px solid transparent;
      border-radius: 5px;
      overflow: hidden;

      &:disabled {
        cursor: wait;
        opacity: 0.65;
      }

      &:focus-visible {
        outline: 3px solid #409eff;
        outline-offset: 2px;
      }

      &:last-of-type {
        border: none;
      }

      &:hover {
        box-shadow: 0 1px 2px -2px rgba(0, 0, 0, 0.16),
          0 3px 6px 0 rgba(0, 0, 0, 0.12), 0 5px 12px 4px rgba(0, 0, 0, 0.09);
      }

      &.active {
        border: 3px solid rgb(154, 198, 250);
      }

      .imgBox {
        width: 100%;

        img {
          width: 100%;
        }
      }
      .name {
        text-align: center;
        font-size: 14px;
      }
    }
  }
}
</style>
