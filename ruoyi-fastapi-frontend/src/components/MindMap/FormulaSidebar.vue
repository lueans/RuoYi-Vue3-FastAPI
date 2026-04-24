<template>
  <Sidebar ref="sidebarRef" title="公式">
    <div class="box" :class="{ isDark: isDark }">
      <div class="formulaInputBox">
        <el-input
          v-model="formulaText"
          :rows="4"
          resize="none"
          type="textarea"
          placeholder="请输入 LaTeX 公式"
          @keydown.stop
        />
        <el-button
          size="small"
          style="width: 100%; margin-top: 20px"
          @click="confirm"
        >确认</el-button>
      </div>
      <div class="title">常用公式</div>
      <div class="formulaList customScrollbar">
        <div
          class="formulaItem"
          v-for="(item, index) in list"
          :key="index"
        >
          <div class="overview" v-html="item.overview"></div>
          <div class="text" @click="formulaText = item.text">
            {{ item.text }}
          </div>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store, actions } from './useStore'
import { formulaList } from './config'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const formulaText = ref('')
const activeNodes = ref([])
const list = ref([])

function init() {
  if (!window.katex || !props.mindMap?.formula) return
  try {
    const katexConfig = props.mindMap.formula.getKatexConfig()
    list.value = formulaList.map(item => {
      return {
        overview: window.katex.renderToString(item, {
          ...katexConfig,
          throwOnError: false
        }),
        text: item
      }
    })
  } catch (e) {
    console.error('KaTeX init failed:', e)
  }
}

function confirm() {
  if (!store.localConfig.openNodeRichText) {
    ElMessage.warning('公式仅在富文本模式下支持，请先在设置中开启富文本编辑')
    return
  }
  const str = formulaText.value.trim()
  if (!str) return
  props.mindMap?.execCommand('INSERT_FORMULA', str)
}

function handleNodeActive(_, nodeList) {
  activeNodes.value = nodeList ? [...nodeList] : []
  if (activeNodes.value.length <= 0 && store.activeSidebar === 'formulaSidebar') {
    actions.setActiveSidebar(null)
  }
}

onMounted(() => {
  bus.on('node_active', handleNodeActive)
  init()
})

onBeforeUnmount(() => {
  bus.off('node_active', handleNodeActive)
})

watch(() => props.mindMap, () => {
  init()
})

watch(() => store.activeSidebar, (val) => {
  if (val === 'formulaSidebar') {
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})
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
        font-size: 14px;
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
      }
    }
  }
}
</style>
