<template>
  <aside
    ref="inspectorRef"
    class="propertyInspector"
    :class="{ isDark }"
    role="complementary"
    aria-labelledby="mindmap-property-inspector-title"
    @click.stop
    @keydown.esc.stop="closeInspector"
  >
    <div class="inspectorHeader">
      <h2 id="mindmap-property-inspector-title" class="srOnly">脑图格式</h2>
      <div class="inspectorTabs" role="tablist" aria-label="脑图格式">
        <button
          v-for="(tab, index) in tabs"
          :key="tab.value"
          :ref="element => setTabRef(tab.value, element)"
          class="inspectorTab"
          :class="{ active: activeTab === tab.value }"
          type="button"
          role="tab"
          :id="`mindmap-inspector-tab-${tab.value}`"
          :aria-controls="`mindmap-inspector-panel-${tab.value}`"
          :aria-selected="activeTab === tab.value"
          :tabindex="activeTab === tab.value ? 0 : -1"
          @click="selectTab(tab.value)"
          @keydown="onTabKeydown($event, index)"
        >
          {{ tab.label }}
        </button>
      </div>
      <button
        ref="closeButtonRef"
        class="inspectorClose"
        type="button"
        aria-label="关闭脑图格式面板"
        @click="closeInspector"
      >
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <div class="inspectorContext">
      <div class="contextTarget">
        <span class="contextLabel" :title="contextLabel">{{ contextLabel }}</span>
      </div>
      <div v-show="feedbackActive" class="applicationState" role="status" aria-live="polite">
        <span class="stateDot" :class="{ applied: feedbackActive }" aria-hidden="true"></span>
        <span>{{ applicationText }}</span>
      </div>
    </div>

    <div ref="inspectorBodyRef" class="inspectorBody customScrollbar">
      <section
        v-if="activeTab === 'node'"
        id="mindmap-inspector-panel-node"
        class="inspectorPanel"
        role="tabpanel"
        aria-labelledby="mindmap-inspector-tab-node"
      >
        <MmStyle
          v-if="activeNodes.length > 0"
          :key="nodePanelKey"
          :mindMap="mindMap"
          embedded
        />
        <div v-else class="nodeEmptyState">
          <div class="emptyStateIcon iconfont icontianjiazijiedian" aria-hidden="true"></div>
          <h3>选择节点后编辑样式</h3>
          <p>在画布中点击一个或多个节点；也可以先设置整张脑图。</p>
          <div class="emptyStateActions">
            <button type="button" class="emptyStatePrimary" @click="selectTab('canvas', true)">
              设置画布
            </button>
            <button type="button" class="emptyStateSecondary" @click="selectTab('theme', true)">
              浏览主题
            </button>
          </div>
        </div>
      </section>

      <section
        v-else-if="activeTab === 'canvas'"
        id="mindmap-inspector-panel-canvas"
        class="inspectorPanel canvasPanel"
        role="tabpanel"
        aria-labelledby="mindmap-inspector-tab-canvas"
      >
        <details class="canvasSection" open>
          <summary class="canvasSectionSummary">
            <span class="canvasSectionHeading">
              <strong>布局结构</strong>
              <small>选择脑图的分支方向与排列方式</small>
            </span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="canvasSectionBody">
            <Structure
              :mindMap="mindMap"
              embedded
              @document-meta-change="handleDocumentMetaChange('canvas', $event)"
            />
          </div>
        </details>
        <details class="canvasSection" open>
          <summary class="canvasSectionSummary">
            <span class="canvasSectionHeading">
              <strong>画布样式</strong>
              <small>调整背景、连线与全局间距</small>
            </span>
            <el-icon class="sectionChevron"><ArrowUp /></el-icon>
          </summary>
          <div class="canvasSectionBody">
            <BaseStyle
              :mindMap="mindMap"
              embedded
              @document-meta-change="handleDocumentMetaChange('canvas', $event)"
            />
          </div>
        </details>
      </section>

      <section
        v-else
        id="mindmap-inspector-panel-theme"
        class="inspectorPanel"
        role="tabpanel"
        aria-labelledby="mindmap-inspector-tab-theme"
      >
        <Theme
          :mindMap="mindMap"
          embedded
          @document-meta-change="handleDocumentMetaChange('theme', $event)"
        />
      </section>
    </div>

    <div class="inspectorFooter">
      <button
        v-if="activeTab === 'node'"
        class="resetStyleButton"
        type="button"
        :disabled="activeNodes.length === 0 || isReadonly"
        @click="resetSelectedNodeStyles"
      >
        <el-icon><RefreshRight /></el-icon>
        <span>重置样式</span>
      </button>
      <div v-else class="footerHint">
        <span class="footerHintText">
          <strong>{{ activeTab === 'theme' ? '应用到整张脑图' : '全局设置立即应用' }}</strong>
          <small>需要恢复时可使用顶部撤销</small>
        </span>
        <kbd>{{ undoShortcut }}</kbd>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ArrowUp, Close, RefreshRight } from '@element-plus/icons-vue'
import MmStyle from './Style.vue'
import BaseStyle from './BaseStyle.vue'
import Theme from './Theme.vue'
import Structure from './Structure.vue'
import bus from './useEventBus'
import { actions, store } from './useStore'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'
import { layoutList } from './config'

const props = defineProps({
  mindMap: { type: Object, default: null },
})

const emit = defineEmits(['document-meta-change'])
const tabs = Object.freeze([
  { label: '节点', value: 'node', sidebar: 'nodeStyle' },
  { label: '画布', value: 'canvas', sidebar: 'baseStyle' },
  { label: '主题', value: 'theme', sidebar: 'theme' },
])
const propertySidebarNames = new Set(['nodeStyle', 'baseStyle', 'structure', 'theme'])
const inspectorRef = ref(null)
const inspectorBodyRef = ref(null)
const closeButtonRef = ref(null)
const tabRefs = new Map()
const nodePanelKey = ref(0)
const applicationText = ref('修改自动保存')
const feedbackActive = ref(false)
const currentLayout = ref('')
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const layoutNameMap = Object.fromEntries(layoutList.map(item => [item.value, item.name]))
const undoShortcut = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
  ? '⌘ Z'
  : 'Ctrl Z'
const { activeNodes, syncActiveNodes } = useMindMapActiveNodes({
  resolveMindMap: () => props.mindMap,
})
let focusReturnTarget = null
let feedbackTimer = null
let boundMindMap = null

const activeTab = computed(() => {
  if (store.activeSidebar === 'theme') return 'theme'
  if (['baseStyle', 'structure'].includes(store.activeSidebar)) return 'canvas'
  return 'node'
})

const contextLabel = computed(() => {
  if (activeTab.value === 'canvas') {
    return `当前布局：${layoutNameMap[currentLayout.value] || '默认布局'}`
  }
  if (activeTab.value === 'theme') return '主题将应用到整张脑图'
  if (activeNodes.value.length === 0) return '未选择节点'
  return `已选择 ${activeNodes.value.length} 个节点`
})

function setTabRef(name, element) {
  if (element) tabRefs.set(name, element)
  else tabRefs.delete(name)
}

function selectTab(name, focus = false) {
  const tab = tabs.find(item => item.value === name)
  if (!tab || isReadonly.value) return
  actions.setActiveSidebar(tab.sidebar)
  if (focus) nextTick(() => tabRefs.get(name)?.focus())
}

function announceApplied(message) {
  if (feedbackTimer) clearTimeout(feedbackTimer)
  applicationText.value = message
  feedbackActive.value = true
  feedbackTimer = setTimeout(() => {
    applicationText.value = '修改自动保存'
    feedbackActive.value = false
    feedbackTimer = null
  }, 1800)
}

function handleDocumentMetaChange(scope, payload) {
  if (payload?.layout) currentLayout.value = payload.layout
  emit('document-meta-change', payload)
  announceApplied(scope === 'theme' ? '主题已应用' : '画布设置已应用')
}

function handleMindMapDataChange() {
  if (activeTab.value === 'node' && activeNodes.value.length > 0) {
    announceApplied('节点样式已应用')
  }
}

function bindMindMap(nextMindMap) {
  if (boundMindMap === nextMindMap) return
  boundMindMap?.off?.('data_change', handleMindMapDataChange)
  boundMindMap = nextMindMap || null
  boundMindMap?.on?.('data_change', handleMindMapDataChange)
  currentLayout.value = boundMindMap?.getLayout?.() || ''
}

function onTabKeydown(event, index) {
  let nextIndex = index
  if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length
  else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length
  else if (event.key === 'Home') nextIndex = 0
  else if (event.key === 'End') nextIndex = tabs.length - 1
  else return
  event.preventDefault()
  selectTab(tabs[nextIndex].value, true)
}

function closeInspector() {
  const returnTarget = focusReturnTarget
  actions.setActiveSidebar(null)
  nextTick(() => {
    if (returnTarget?.isConnected && !returnTarget.closest?.('[inert]')) {
      returnTarget.focus?.()
    } else {
      bus.emit('focusSidebarTrigger', 'nodeStyle')
    }
  })
}

function handleCloseSidebar() {
  if (propertySidebarNames.has(store.activeSidebar)) actions.setActiveSidebar(null)
}

function focusWhenOpen() {
  closeButtonRef.value?.focus()
}

function resetSelectedNodeStyles() {
  if (!props.mindMap || isReadonly.value || activeNodes.value.length === 0) return
  props.mindMap.execCommand('REMOVE_ALL_NODE_CUSTOM_STYLES', [...activeNodes.value])
  nodePanelKey.value += 1
  announceApplied('节点样式已重置')
  nextTick(syncActiveNodes)
}

watch(() => props.mindMap, bindMindMap, { immediate: true })

watch(activeTab, () => {
  if (feedbackTimer) clearTimeout(feedbackTimer)
  applicationText.value = '修改自动保存'
  feedbackActive.value = false
  feedbackTimer = null
  if (activeTab.value === 'canvas') currentLayout.value = props.mindMap?.getLayout?.() || ''
  nextTick(() => {
    if (inspectorBodyRef.value) inspectorBodyRef.value.scrollTop = 0
  })
})

onMounted(() => {
  focusReturnTarget = document.activeElement
  bus.on('closeSideBar', handleCloseSidebar)
  bus.on('focusActiveSidebar', focusWhenOpen)
})

onBeforeUnmount(() => {
  if (feedbackTimer) clearTimeout(feedbackTimer)
  bindMindMap(null)
  bus.off('closeSideBar', handleCloseSidebar)
  bus.off('focusActiveSidebar', focusWhenOpen)
  tabRefs.clear()
})
</script>

<style lang="less" scoped>
.propertyInspector {
  --inspector-accent: #3370ff;
  position: absolute;
  top: 0;
  right: var(--mindmap-activity-width, 44px);
  bottom: var(--mindmap-workspace-bottom, 30px);
  z-index: 2001;
  width: var(--mindmap-inspector-width, 300px);
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  color: #1f2329;
  background: #fff;
  border-left: 1px solid #e8eaed;
  box-shadow: none;

  &.isDark {
    color: #e5e6eb;
    background: #25282d;
    border-left-color: #3d4046;
    box-shadow: -8px 0 24px rgba(0, 0, 0, 0.2);

    .inspectorHeader,
    .inspectorContext,
    .inspectorFooter,
    .nodeEmptyState {
      border-color: #3d4046;
    }

    .inspectorTab,
    .inspectorClose {
      color: #c9cdd4;
    }

    .inspectorTab:hover,
    .inspectorClose:hover {
      color: #fff;
      background: rgba(255, 255, 255, 0.06);
    }

    .inspectorContext {
      background: #292c31;
    }

    .contextLabel,
    .applicationState,
    .footerHintText small {
      color: #8f959e;
    }

    .footerHintText strong,
    .nodeEmptyState h3 {
      color: #e5e6eb;
    }

    .footerHint kbd,
    .emptyStateSecondary {
      color: #c9cdd4;
      background: #2f3338;
      border-color: #454950;
    }

    .nodeEmptyState p {
      color: #8f959e;
    }

    .canvasSection {
      border-color: #3d4046;
    }

    .canvasSectionSummary:hover {
      background: rgba(255, 255, 255, 0.04);
    }

    .canvasSectionHeading {
      strong {
        color: #e5e6eb;
      }

      small {
        color: #8f959e;
      }
    }

    .resetStyleButton {
      color: #e5e6eb;
      background: #2f3338;
      border-color: #454950;

      &:hover:not(:disabled) {
        color: #7aa2ff;
        border-color: #5b8def;
      }
    }
  }
}

.inspectorHeader {
  position: relative;
  flex: 0 0 40px;
  display: flex;
  align-items: stretch;
  padding: 0 42px 0 10px;
  border-bottom: 1px solid #eef0f3;
}

.inspectorTabs {
  display: flex;
  flex: 1;
  gap: 0;
}

.inspectorTab {
  position: relative;
  min-width: 0;
  flex: 1;
  padding: 0 6px;
  border: 0;
  background: transparent;
  color: #4e5969;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;

  &::after {
    position: absolute;
    right: 7px;
    bottom: -1px;
    left: 7px;
    height: 2px;
    border-radius: 2px 2px 0 0;
    background: var(--inspector-accent);
    content: '';
    opacity: 0;
    transform: scaleX(0.55);
    transition: 0.16s ease;
  }

  &:hover,
  &.active {
    color: var(--inspector-accent);
  }

  &.active {
    font-weight: 600;

    &::after {
      opacity: 1;
      transform: scaleX(1);
    }
  }

  &:focus-visible {
    outline: 2px solid var(--inspector-accent);
    outline-offset: -4px;
    border-radius: 6px;
  }
}

.inspectorClose {
  position: absolute;
  top: 6px;
  right: 9px;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 7px;
  color: #646a73;
  background: transparent;
  cursor: pointer;

  &:hover {
    color: #1f2329;
    background: #f5f6f7;
  }

  &:focus-visible {
    outline: 2px solid var(--inspector-accent);
    outline-offset: 2px;
  }
}

.inspectorContext {
  flex: 0 0 44px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 14px;
  border-bottom: 1px solid #eef0f3;
  background: #fff;
}

.contextTarget {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.contextLabel {
  overflow: hidden;
  color: #8f959e;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.applicationState {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #8f959e;
  font-size: 11px;

  .stateDot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #34c759;
    transition: 0.18s ease;

    &.applied {
      box-shadow: 0 0 0 4px rgba(52, 199, 89, 0.14);
    }
  }
}

.nodeEmptyState {
  min-height: 320px;
  display: flex;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  padding: 28px 24px;
  text-align: center;

  .emptyStateIcon {
    margin-bottom: 12px;
    color: #8fb0ff;
    font-size: 40px;
  }

  h3 {
    margin: 0 0 8px;
    color: #1f2329;
    font-size: 15px;
    font-weight: 600;
  }

  p {
    max-width: 240px;
    margin: 0;
    color: #8f959e;
    font-size: 12px;
    line-height: 1.65;
  }
}

.emptyStateActions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}

.emptyStatePrimary,
.emptyStateSecondary {
  height: 34px;
  padding: 0 15px;
  border: 1px solid transparent;
  border-radius: 7px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;

  &:focus-visible {
    outline: 2px solid var(--inspector-accent);
    outline-offset: 2px;
  }
}

.emptyStatePrimary {
  color: #fff;
  background: var(--inspector-accent);

  &:hover {
    background: #245bdb;
  }
}

.emptyStateSecondary {
  color: #4e5969;
  background: #fff;
  border-color: #dfe2e6;

  &:hover {
    color: var(--inspector-accent);
    border-color: #8fb0ff;
  }
}

.inspectorBody {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
}

.inspectorPanel {
  min-height: 100%;
}

.canvasPanel {
  padding: 0 14px 18px;
}

.canvasSection {
  margin: 0;
  border-bottom: 1px solid #eef0f3;

  &[open] .sectionChevron {
    transform: rotate(0deg);
  }

  &:not([open]) .sectionChevron {
    transform: rotate(180deg);
  }
}

.canvasSectionSummary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 -8px;
  padding: 14px 8px 12px;
  border-radius: 8px;
  list-style: none;
  cursor: pointer;
  user-select: none;

  &::-webkit-details-marker {
    display: none;
  }

  &:hover {
    background: #f7f9ff;
  }

  &:focus-visible {
    outline: 2px solid var(--inspector-accent);
    outline-offset: 2px;
  }

  .sectionChevron {
    flex: 0 0 auto;
    color: #646a73;
    font-size: 13px;
    transition: transform 0.16s ease;
  }
}

.canvasSectionHeading {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;

  strong {
    color: #1f2329;
    font-size: 13px;
    font-weight: 600;
  }

  small {
    color: #8f959e;
    font-size: 11px;
    line-height: 1.4;
  }
}

.canvasSectionBody {
  padding-bottom: 14px;
}

.inspectorFooter {
  flex: 0 0 56px;
  display: flex;
  align-items: center;
  padding: 8px 14px;
  border-top: 1px solid #eef0f3;
  background: inherit;
}

.footerHint {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  kbd {
    flex: 0 0 auto;
    padding: 4px 7px;
    border: 1px solid #dfe2e6;
    border-bottom-width: 2px;
    border-radius: 5px;
    color: #646a73;
    background: #f7f8fa;
    font-family: inherit;
    font-size: 11px;
  }
}

.footerHintText {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;

  strong {
    color: #1f2329;
    font-size: 12px;
    font-weight: 600;
  }

  small {
    color: #8f959e;
    font-size: 11px;
  }
}

.resetStyleButton {
  width: 100%;
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid #dfe2e6;
  border-radius: 8px;
  color: #1f2329;
  background: #fff;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: 0.16s ease;

  &:hover:not(:disabled) {
    color: var(--inspector-accent);
    border-color: #8fb0ff;
    background: #f7f9ff;
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  &:focus-visible {
    outline: 2px solid var(--inspector-accent);
    outline-offset: 2px;
  }
}

.srOnly {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 1439px) and (min-width: 761px) {
  .propertyInspector {
    width: var(--mindmap-inspector-compact-width, 300px);
    box-shadow: -8px 0 24px rgba(31, 35, 41, 0.1);
  }
}

@media (max-width: 760px) {
  .propertyInspector {
    right: 0;
    bottom: 52px;
    width: min(100%, 300px);
  }
}
</style>
