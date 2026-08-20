<template>
  <Sidebar ref="sidebarRef" title="公式" open-on-mount>
    <div class="box" :class="{ isDark: isDark }">
      <div v-if="pluginLoading" class="formulaState" role="status" aria-live="polite">
        正在加载公式能力…
      </div>
      <div v-else-if="pluginError" class="formulaState error" role="alert">
        <span>{{ pluginError }}</span>
        <el-button link type="primary" size="small" :disabled="isReadonly" @click="loadFormulaPlugin">重新加载</el-button>
      </div>
      <template v-else>
        <div class="formulaInputBox">
          <el-input
            v-model="formulaText"
            :rows="4"
            resize="none"
            type="textarea"
            placeholder="请输入 LaTeX 公式"
            :disabled="isReadonly"
            @keydown.stop
          />
          <el-button
            size="small"
            style="width: 100%; margin-top: 20px"
            :disabled="!canInsertFormula"
            @click="confirm"
          >确认</el-button>
        </div>
        <div id="common-formula-title" class="title">常用公式</div>
        <div class="formulaList customScrollbar" role="list" aria-labelledby="common-formula-title">
          <div
            class="formulaItem"
            v-for="(item, index) in list"
            :key="index"
            role="listitem"
          >
            <div class="overview" aria-hidden="true" v-html="item.overview"></div>
            <button
              type="button"
              class="text"
              :aria-label="`使用公式 ${item.text}`"
              :title="item.text"
              :disabled="isReadonly"
              @click="formulaText = item.text"
            >
              {{ item.text }}
            </button>
          </div>
        </div>
      </template>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'
import { formulaList } from './config'
import { ensureFormulaPlugin } from './usePlugins'
import { resolveMindmapEventNodes } from '@/utils/mindmap-event'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const formulaText = ref('')
const activeNodes = ref([])
const list = ref([])
const pluginLoading = ref(false)
const pluginError = ref('')
const formulaReady = computed(() => Boolean(props.mindMap?.formula && window.katex))
const canInsertFormula = computed(() => {
  const activeMindMap = props.mindMap
  return !isReadonly.value
    && !pluginLoading.value
    && !pluginError.value
    && formulaReady.value
    && store.activeSidebar === 'formulaSidebar'
    && activeNodes.value.some(node => node?.mindMap === activeMindMap)
})
let pluginRequestId = 0
let componentAlive = true

function resetFormulaSession({ clearInput = true } = {}) {
  pluginRequestId += 1
  pluginLoading.value = false
  pluginError.value = ''
  list.value = []
  activeNodes.value = []
  if (clearInput) formulaText.value = ''
}

function isCurrentPluginRequest(requestId, mindMap) {
  return componentAlive
    && requestId === pluginRequestId
    && mindMap === props.mindMap
    && store.activeSidebar === 'formulaSidebar'
}

function renderFormulaList(mindMap) {
  if (!window.katex || !mindMap?.formula) {
    throw new Error('公式能力尚未就绪')
  }
  const katexConfig = mindMap.formula.getKatexConfig()
  return formulaList.map(item => ({
    overview: window.katex.renderToString(item, {
      ...katexConfig,
      throwOnError: false
    }),
    text: item
  }))
}

async function loadFormulaPlugin() {
  const activeMindMap = props.mindMap
  if (!activeMindMap || store.activeSidebar !== 'formulaSidebar') return
  const requestId = ++pluginRequestId
  pluginLoading.value = true
  pluginError.value = ''
  try {
    await ensureFormulaPlugin(activeMindMap)
    if (!isCurrentPluginRequest(requestId, activeMindMap)) return
    list.value = renderFormulaList(activeMindMap)
  } catch (error) {
    if (!isCurrentPluginRequest(requestId, activeMindMap)) return
    console.error('公式能力加载失败:', error)
    pluginError.value = '公式能力加载失败，请检查网络后重试'
  } finally {
    if (isCurrentPluginRequest(requestId, activeMindMap)) pluginLoading.value = false
  }
}

function confirm() {
  const activeMindMap = props.mindMap
  if (!canInsertFormula.value || !activeMindMap) return
  if (!store.localConfig.openNodeRichText) {
    ElMessage.warning('公式仅在富文本模式下支持，请先在设置中开启富文本编辑')
    return
  }
  if (!formulaReady.value) {
    ElMessage.warning('公式能力尚未加载完成，请稍后重试')
    return
  }
  const str = formulaText.value.trim()
  if (!str) return
  activeMindMap.execCommand('INSERT_FORMULA', str)
  formulaText.value = ''
}

function handleNodeActive(_, nodeList, sourceMindMap = null) {
  const nodes = resolveMindmapEventNodes(nodeList, sourceMindMap, props.mindMap)
  if (nodes === null) return
  activeNodes.value = nodes
  if (activeNodes.value.length <= 0 && store.activeSidebar === 'formulaSidebar') {
    actions.setActiveSidebar(null)
  }
}

onMounted(() => {
  bus.on('node_active', handleNodeActive)
})

onBeforeUnmount(() => {
  componentAlive = false
  resetFormulaSession()
  bus.off('node_active', handleNodeActive)
})

watch(() => props.mindMap, (mindMap, oldMindMap) => {
  if (mindMap === oldMindMap) return
  resetFormulaSession()
  if (oldMindMap && store.activeSidebar === 'formulaSidebar') {
    actions.setActiveSidebar(null)
    return
  }
  if (mindMap) void loadFormulaPlugin()
}, { immediate: true })

watch(() => store.activeSidebar, (val) => {
  if (val === 'formulaSidebar') {
    activeNodes.value = [...(props.mindMap?.renderer?.activeNodeList || [])]
    sidebarRef.value?.open()
    if (!pluginLoading.value && (!formulaReady.value || list.value.length === 0)) {
      void loadFormulaPlugin()
    }
  } else {
    sidebarRef.value?.close()
    resetFormulaSession()
  }
}, { immediate: true })
</script>

<style lang="less" scoped>
.box {
  padding: 10px;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;

  &.isDark {
    .title {
      color: #fff;
    }

    .formulaList {
      .formulaItem {
        .overview,
        .text {
          color: #fff;
        }

        .text {
          background-color: #363b3f;
        }
      }
    }

    :deep(.el-textarea__inner) {
      background-color: transparent;
      color: #fff;
    }
  }

  .title {
    font-size: 16px;
    font-weight: 500;
    color: #333;
    margin: 10px 0;
    flex-shrink: 0;
  }

  .formulaState {
    min-height: 96px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: #646a73;
    text-align: center;

    &.error {
      color: #d03050;
    }
  }

  .formulaInputBox {
    flex-shrink: 0;
  }

  .formulaList {
    height: 100%;
    overflow-y: auto;

    .formulaItem {
      position: relative;
      display: flex;
      overflow: hidden;
      align-items: center;
      border: 1px solid #dcdfe6;
      border-bottom: none;

      &:last-of-type {
        border-bottom: 1px solid #dcdfe6;
      }

      .overview,
      .text {
        width: 50%;
        overflow: hidden;
        display: flex;
        justify-content: center;
        align-items: center;
        flex-shrink: 0;
      }

      .overview {
        padding: 10px 0;
        border-right: none;
      }

      .text {
        cursor: pointer;
        border: 0;
        font-size: 14px;
        font-family: inherit;
        color: inherit;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        height: 100%;
        position: absolute;
        right: 0;
        top: 0;
        border-left: 1px solid #dcdfe6;
        background-color: #fafafa;
        padding: 0 5px;

        &:focus-visible {
          outline: 2px solid #409eff;
          outline-offset: -2px;
          z-index: 1;
        }
      }
    }
  }
}
</style>
