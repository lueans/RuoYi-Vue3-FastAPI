<template>
  <div class="themePanel" :class="{ embedded: props.embedded }">
    <div class="themeGroupList" :class="{ isDark: isDark }">
      <el-tabs v-model="activeName" class="tabBox">
        <el-tab-pane
          v-for="group in groupList"
          :key="group.name"
          :label="group.name"
          :name="group.name"
        >
          <template #label>
            <span class="themeTabLabel">
              {{ group.name }}
              <small>{{ group.list.length }}</small>
            </span>
          </template>
        </el-tab-pane>
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
            <span v-if="item.value === currentTheme" class="activeMark" aria-hidden="true">
              <el-icon><Check /></el-icon>
            </span>
          </div>
          <div class="name">
            <span>{{ item.name }}</span>
            <small v-if="item.value === currentTheme">当前</small>
          </div>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Check } from '@element-plus/icons-vue'
import { store, actions } from './useStore'
import { ElMessageBox } from 'element-plus'

import themeImgMapRaw from 'simple-mind-map-plugin-themes/themeImgMap'
import themeListRaw from 'simple-mind-map-plugin-themes/themeList'

const themeImgMap = themeImgMapRaw || {}
const themeList = themeListRaw || []

const props = defineProps({
  data: { type: [Object, null], default: null },
  mindMap: { type: Object, default: null },
  embedded: { type: Boolean, default: false }
})
const emit = defineEmits(['document-meta-change'])

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
  if (!group) return []
  const selectedTheme = group.list.find(item => item.value === currentTheme.value)
  if (!selectedTheme) return group.list
  return [
    selectedTheme,
    ...group.list.filter(item => item.value !== currentTheme.value)
  ]
})

// Initialize
if (groupList.value.length > 0) {
  activeName.value = groupList.value[0].name
}

function handleViewThemeChange() {
  if (!props.mindMap) return
  currentTheme.value = props.mindMap.getTheme()
  syncActiveThemeGroup()
  handleDark()
}

function syncActiveThemeGroup() {
  const selectedGroup = groupList.value.find(group => (
    group.list.some(theme => theme.value === currentTheme.value)
  ))
  if (selectedGroup) activeName.value = selectedGroup.name
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
    if (props.mindMap) {
      currentTheme.value = props.mindMap.getTheme()
      syncActiveThemeGroup()
    }
  }
}, { immediate: true })
</script>

<style lang="less" scoped>
.themePanel {
  width: 100%;
  min-height: 100%;
}

.themeGroupList {
  display: flex;
  flex-direction: column;
  min-height: 100%;

  &.isDark {
    .name {
      color: #fff;
    }

    .themeListTheme .themeItem {
      border-color: #454950;
      background: #2f3338;

      &:hover {
        border-color: #5b8def;
      }

      &.active {
        background: rgba(51, 112, 255, 0.12);
      }
    }
  }

  .tabBox {
    flex-shrink: 0;
    padding: 0 18px;

    :deep(.el-tabs__header) {
      margin-bottom: 14px;
    }

    :deep(.el-tabs__nav-wrap) {
      display: flex;
      justify-content: center;
    }

    :deep(.el-tabs__item) {
      height: 42px;
      padding: 0 15px;
      font-size: 13px;
    }

    .themeTabLabel {
      display: inline-flex;
      align-items: center;
      gap: 5px;

      small {
        min-width: 18px;
        height: 18px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0 4px;
        border-radius: 9px;
        color: #8f959e;
        background: #f2f3f5;
        font-size: 10px;
      }
    }
  }

  .themeListTheme {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    padding: 0 18px 24px;

    .themeItem {
      width: 100%;
      cursor: pointer;
      display: block;
      appearance: none;
      background: transparent;
      color: inherit;
      font: inherit;
      border: 1px solid #e2e5ea;
      margin: 0;
      padding: 6px;
      transition: all 0.2s;
      border-radius: 8px;
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
        border: 1px solid #e2e5ea;
      }

      &:hover {
        border-color: #8fb0ff;
        box-shadow: 0 4px 12px rgba(31, 35, 41, 0.08);
      }

      &.active {
        border: 2px solid #3370ff;
        padding: 5px;
        background: #f7f9ff;
      }

      .imgBox {
        position: relative;
        width: 100%;
        aspect-ratio: 16 / 9;
        overflow: hidden;
        border-radius: 5px;
        background: #f5f6f7;

        img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .activeMark {
          position: absolute;
          top: 6px;
          right: 6px;
          width: 20px;
          height: 20px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border: 2px solid #fff;
          border-radius: 50%;
          color: #fff;
          background: #3370ff;
          font-size: 12px;
          box-shadow: 0 2px 6px rgba(31, 35, 41, 0.22);
        }
      }
      .name {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
        padding: 7px 2px 1px;
        text-align: left;
        font-size: 12px;
        color: #4e5969;

        span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        small {
          flex: 0 0 auto;
          color: #3370ff;
          font-size: 10px;
        }
      }
    }
  }
}
</style>
