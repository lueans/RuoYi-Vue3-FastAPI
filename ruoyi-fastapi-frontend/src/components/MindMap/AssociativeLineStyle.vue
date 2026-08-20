<template>
  <Sidebar ref="sidebarRef" title="关联线样式">
    <template v-if="hasActiveLine">
      <div class="section-title">线条样式</div>
      <div class="style-row">
        <div class="style-section flex1">
          <div class="style-label">颜色</div>
          <el-color-picker v-model="style.associativeLineColor" size="small" :disabled="isReadonly" @change="updateStyle('associativeLineColor')" />
        </div>
        <div class="style-section flex1">
          <div class="style-label">宽度</div>
          <el-select v-model="style.associativeLineWidth" size="small" :disabled="isReadonly" @change="updateStyle('associativeLineWidth')">
            <el-option v-for="w in lineWidthList" :key="w" :label="w + 'px'" :value="w" />
          </el-select>
        </div>
      </div>
      <div class="style-row">
        <div class="style-section flex1">
          <div class="style-label">激活颜色</div>
          <el-color-picker v-model="style.associativeLineActiveColor" size="small" :disabled="isReadonly" @change="updateStyle('associativeLineActiveColor')" />
        </div>
        <div class="style-section flex1">
          <div class="style-label">激活宽度</div>
          <el-select v-model="style.associativeLineActiveWidth" size="small" :disabled="isReadonly" @change="updateStyle('associativeLineActiveWidth')">
            <el-option v-for="w in lineWidthList" :key="w" :label="w + 'px'" :value="w" />
          </el-select>
        </div>
      </div>
      <div class="section-title">文字样式</div>
      <div class="style-section">
        <div class="style-label">字号</div>
        <el-select v-model="style.associativeLineTextFontSize" size="small" :disabled="isReadonly" @change="updateStyle('associativeLineTextFontSize')">
          <el-option v-for="s in fontSizeList" :key="s" :label="s + 'px'" :value="s" />
        </el-select>
      </div>
      <div class="style-section">
        <div class="style-label">颜色</div>
        <el-color-picker v-model="style.associativeLineTextColor" size="small" :disabled="isReadonly" @change="updateStyle('associativeLineTextColor')" />
      </div>
    </template>
    <div v-else class="empty-tip">请点击一条关联线</div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store, actions } from './useStore'
import { lineWidthList, fontSizeList } from './config'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const sidebarRef = ref(null)
const hasActiveLine = ref(false)
const isReadonly = computed(() => store.isReadonly)
let activeLineNode = null
let activeLineToNode = null

const style = reactive({
  associativeLineColor: '',
  associativeLineWidth: 2,
  associativeLineActiveColor: '',
  associativeLineActiveWidth: 3,
  associativeLineTextFontSize: 14,
  associativeLineTextColor: '#333',
})

function onLineClick(a, b, node, toNode) {
  const activeMindMap = props.mindMap
  if (
    isReadonly.value
    || !activeMindMap
    || !node
    || !toNode
    || (node.mindMap && node.mindMap !== activeMindMap)
    || (toNode.mindMap && toNode.mindMap !== activeMindMap)
  ) return
  activeLineNode = node
  activeLineToNode = toNode
  hasActiveLine.value = true
  const config = props.mindMap?.associativeLine?.getStyleConfig?.(node, toNode) || {}
  Object.keys(style).forEach(key => {
    if (config[key] !== undefined) style[key] = config[key]
  })
  actions.setActiveSidebar('associativeLineStyle')
}

function onLineDeactivate() {
  hasActiveLine.value = false
  activeLineNode = null
  activeLineToNode = null
  if (store.activeSidebar === 'associativeLineStyle') {
    actions.setActiveSidebar(null)
  }
}

function updateStyle(prop) {
  const activeMindMap = props.mindMap
  if (
    isReadonly.value
    || !activeMindMap
    || !activeLineNode
    || !activeLineToNode
    || activeLineNode.mindMap !== activeMindMap
    || activeLineToNode.mindMap !== activeMindMap
  ) return
  const uid = activeLineToNode.getData('uid')
  if (!uid) return
  const existingStyle = { ...(activeLineNode.getData('associativeLineStyle') || {}) }
  existingStyle[uid] = {
    ...(existingStyle[uid] || {}),
    [prop]: style[prop],
  }
  activeLineNode.setData({ associativeLineStyle: existingStyle })
  activeMindMap.associativeLine?.updateActiveLineStyle?.()
}

watch(() => props.mindMap, (mm, oldMm) => {
  oldMm?.off?.('associative_line_click', onLineClick)
  oldMm?.off?.('associative_line_deactivate', onLineDeactivate)
  if (mm !== oldMm) onLineDeactivate()
  mm?.on?.('associative_line_click', onLineClick)
  mm?.on?.('associative_line_deactivate', onLineDeactivate)
}, { immediate: true })

watch(() => store.activeSidebar, (val) => {
  if (val === 'associativeLineStyle') {
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})

watch(isReadonly, (readonly) => {
  if (readonly && hasActiveLine.value) onLineDeactivate()
})

onBeforeUnmount(() => {
  onLineDeactivate()
  props.mindMap?.off?.('associative_line_click', onLineClick)
  props.mindMap?.off?.('associative_line_deactivate', onLineDeactivate)
})
</script>

<style scoped lang="scss">
.section-title {
  font-size: 13px; font-weight: 600; margin: 16px 0 8px;
  padding-bottom: 4px; border-bottom: 1px solid #f0f0f0;
}
.style-section { margin-bottom: 12px; :deep(.el-select) { width: 100%; } }
.style-label { font-size: 12px; color: #666; margin-bottom: 4px; }
.style-row { display: flex; gap: 12px; }
.flex1 { flex: 1; }
.empty-tip { text-align: center; color: #999; padding: 40px 0; }
</style>
