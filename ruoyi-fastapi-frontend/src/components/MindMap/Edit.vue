<template>
  <div
    class="editContainer"
    ref="editContainerRef"
    @dragenter.stop.prevent="onDragenter"
    @dragleave.stop.prevent
    @dragover.stop.prevent
    @drop.stop.prevent
  >
    <div
      class="mindMapContainer"
      id="mindMapContainer"
      ref="mindMapContainerRef"
    ></div>
    <Navigator v-if="mindMap" :mindMap="mindMap" />
    <OutlineSidebar :mindMap="mindMap" />
    <MmStyle v-if="mindMap && !isZenMode" :mindMap="mindMap" />
    <BaseStyle :mindMap="mindMap" />
    <AssociativeLineStyle v-if="mindMap" :mindMap="mindMap" />
    <Theme v-if="mindMap" :mindMap="mindMap" />
    <Structure :mindMap="mindMap" />
    <ShortcutKey />
    <Contextmenu v-if="mindMap" :mindMap="mindMap" />
    <NodeIconSidebar v-if="mindMap" :mindMap="mindMap" />
    <Search v-if="mindMap" :mindMap="mindMap" />
    <SidebarTrigger v-if="!isZenMode" />
    <Setting :mindMap="mindMap" />
    <RichTextToolbar v-if="mindMap" :mindMap="mindMap" />
    <NodeTagStyle v-if="mindMap" :mindMap="mindMap" />
    <NodeIconToolbar v-if="mindMap" :mindMap="mindMap" />
    <NodeImgPlacementToolbar v-if="mindMap" :mindMap="mindMap" />
    <NodeOuterFrame v-if="mindMap" :mindMap="mindMap" />
    <NodeNoteContentShow v-if="mindMap" :mindMap="mindMap" />
    <NodeNoteSidebar v-if="mindMap" :mindMap="mindMap" />
    <NodeImgPreview v-if="mindMap" :mindMap="mindMap" />
    <FormulaSidebar v-if="mindMap" :mindMap="mindMap" />
    <OutlineEdit v-if="mindMap" :mindMap="mindMap" />
    <VersionHistory v-if="mindMap" :mindMap="mindMap" :mindmapId="props.mindmapId" :yjsSync="yjsSync" @yjs-reinit="onYjsReinit" />
    <CollaboratorManager v-if="mindMap" :mindmapId="props.mindmapId" />
    <div
      class="dragMask"
      v-if="showDragMask"
      @dragleave.stop.prevent="onDragleave"
      @dragover.stop.prevent
      @drop.stop.prevent="onDrop"
    >
      <div class="dragTip">在此释放以导入该文件</div>
    </div>
  </div>
</template>

<script setup>
import MindMap from '@mind-map'
import { registerPlugins, RichText, ScrollbarPlugin } from './usePlugins'
import Themes from 'simple-mind-map-plugin-themes'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import bus from './useEventBus'
import { store, actions } from './useStore'
import { defaultData } from './config'
import { getMindmap, updateMindmapContent } from '@/api/mindmap/mindmap'
import { YjsMindmapSync } from '@/utils/yjs-sync'
import './assets/icon-font/iconfont.css'

import Contextmenu from './Contextmenu.vue'
import Navigator from './Navigator.vue'
import Search from './Search.vue'
import SidebarTrigger from './SidebarTrigger.vue'
import MmStyle from './Style.vue'
import BaseStyle from './BaseStyle.vue'
import Theme from './Theme.vue'
import Structure from './Structure.vue'
import ShortcutKey from './ShortcutKey.vue'
import OutlineSidebar from './OutlineSidebar.vue'
import NodeIconSidebar from './NodeIconSidebar.vue'
import AssociativeLineStyle from './AssociativeLineStyle.vue'
import Setting from './Setting.vue'
import RichTextToolbar from './RichTextToolbar.vue'
import NodeTagStyle from './NodeTagStyle.vue'
import NodeIconToolbar from './NodeIconToolbar.vue'
import NodeImgPlacementToolbar from './NodeImgPlacementToolbar.vue'
import NodeOuterFrame from './NodeOuterFrame.vue'
import NodeNoteContentShow from './NodeNoteContentShow.vue'
import NodeNoteSidebar from './NodeNoteSidebar.vue'
import NodeImgPreview from './NodeImgPreview.vue'
import FormulaSidebar from './FormulaSidebar.vue'
import OutlineEdit from './OutlineEdit.vue'
import VersionHistory from './VersionHistory.vue'
import CollaboratorManager from './CollaboratorManager.vue'

// Register all plugins and themes
registerPlugins('full')
Themes.init(MindMap)

const props = defineProps({
  mindmapId: { type: Number, default: null },
  readonly: { type: Boolean, default: false }
})

const emit = defineEmits(['name-change'])

const editContainerRef = ref(null)
const mindMapContainerRef = ref(null)
const mindMap = shallowRef(null)
const showDragMask = ref(false)
let storeConfigTimer = null
let enableShowLoading = true
let autoSaveTimer = null
let yjsSync = null
const isSaving = ref(false)
const pendingSave = ref(false)
const saveStatus = ref('idle') // 'idle' | 'saving' | 'saved' | 'error'
let saveStatusTimer = null
const AUTO_SAVE_DELAY = 2000
let dataChangeDetailHandler = null

// 文本编辑模式退出检测
// 设置文本编辑退出检测
function onHideTextEdit() {
  // 取消 data_change 启动的防抖计时器，立即保存
  clearTimeout(autoSaveTimer)
  if (props.mindmapId) {
    saveToBackend()
  }
}

function setupTextEditExitDetection() {
  // 直接监听 hide_text_edit 事件（simple-mind-map 在退出文本编辑时触发）
  // 覆盖所有退出方式：点击画布、按 Enter/Tab、切换节点、缩放等
  // 同时兼容普通文本模式和富文本模式
  //
  // 注意时序：hideEditTextBox() 内部先 execCommand('SET_NODE_TEXT') 触发 data_change，
  // 然后才 emit hide_text_edit。所以 data_change 到达时我们还不知道是文本编辑退出。
  // 解决方案：data_change 启动 2 秒防抖，hide_text_edit 紧随其后触发时取消防抖并立即保存。
  bus.on('hide_text_edit', onHideTextEdit)
}

const isZenMode = computed(() => store.localConfig.isZenMode)
const openNodeRichText = computed(() => store.localConfig.openNodeRichText)
const isShowScrollbar = computed(() => store.localConfig.isShowScrollbar)
const useLeftKeySelectionRightKeyDrag = computed(() => store.localConfig.useLeftKeySelectionRightKeyDrag)

// All events to forward from mindMap instance to bus
const forwardEvents = [
  'node_active',
  'data_change',
  'view_data_change',
  'back_forward',
  'node_contextmenu',
  'node_click',
  'draw_click',
  'expand_btn_click',
  'svg_mousedown',
  'mouseup',
  'mode_change',
  'node_tree_render_end',
  'rich_text_selection_change',
  'transforming-dom-to-images',
  'generalization_node_contextmenu',
  'painter_start',
  'painter_end',
  'scrollbar_change',
  'scale',
  'translate',
  'node_attachmentClick',
  'node_attachmentContextmenu',
  'demonstrate_jump',
  'exit_demonstrate',
  'node_note_dblclick',
  'node_mousedown',
  'hide_text_edit',
]

// Watch openNodeRichText to dynamically add/remove RichText plugin.
// A full reRender is required after the swap: the plugin's internal transform
// only issues a partial render() that reuses cached MindMapNode instances, so
// stale plain <text> / rich <foreignObject> SVG groups otherwise remain and
// node text displays abnormally.
watch(openNodeRichText, (val) => {
  if (!mindMap.value) return
  mindMap.value.renderer?.textEdit?.hideEditTextBox?.()
  if (val) {
    mindMap.value.addPlugin(RichText)
  } else {
    mindMap.value.removePlugin(RichText)
  }
  nextTick(() => {
    mindMap.value?.reRender()
  })
})

// Watch isShowScrollbar to dynamically add/remove Scrollbar plugin
watch(isShowScrollbar, (val) => {
  if (!mindMap.value) return
  if (val) {
    mindMap.value.addPlugin(ScrollbarPlugin)
  } else {
    mindMap.value.removePlugin(ScrollbarPlugin)
  }
})

onMounted(async () => {
  actions.initLocalConfig()
  await initMindMap()
  setupTextEditExitDetection()
  bindBusEvents()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  unbindBusEvents()
  window.removeEventListener('resize', handleResize)
  if (yjsSync) {
    yjsSync.destroy()
    yjsSync = null
  }
  clearTimeout(autoSaveTimer)
  clearTimeout(saveStatusTimer)
  if (mindMap.value) {
    mindMap.value.destroy()
    mindMap.value = null
  }
  clearTimeout(storeConfigTimer)
  actions.resetState()
})

async function initMindMap() {
  if (!mindMapContainerRef.value) return

  let root = defaultData
  let layout = 'logicalStructure'
  let themeTemplate = 'default'
  let themeConfig = {}
  let viewData = null
  let savedConfig = {}

  // 如果有 mindmapId，从后端加载
  if (props.mindmapId) {
    try {
      const response = await getMindmap(props.mindmapId)
      const data = response.data
      root = data.nodeTree || defaultData
      layout = data.layout || 'logicalStructure'
      themeTemplate = data.theme?.template || 'default'
      themeConfig = data.theme?.config || {}
      viewData = data.viewData || null
      emit('name-change', data.name)
    } catch (error) {
      ElMessage.error('加载脑图失败')
      return
    }
  } else {
    // 回退到 localStorage
    const savedData = actions.getData()
    savedConfig = actions.getConfig() || {}
    root = savedData?.root || defaultData
    layout = savedData?.layout || 'logicalStructure'
    themeTemplate = savedData?.theme?.template || 'default'
    themeConfig = savedData?.theme?.config || {}
    viewData = savedData?.view || null
  }

  // savedConfig 放在最前面，后续显式配置覆盖它，防止 localStorage 污染覆盖关键选项
  const mm = new MindMap({
    ...savedConfig,
    el: mindMapContainerRef.value,
    data: root,
    fit: false,
    layout: layout,
    theme: themeTemplate,
    themeConfig: themeConfig,
    viewData: viewData,
    readonly: props.readonly,
    nodeTextEditZIndex: 1000,
    nodeNoteTooltipZIndex: 1000,
    customNoteContentShow: {
      show: (content, left, top, node) => {
        bus.emit('showNoteContent', content, left, top, node)
      },
      hide: () => {}
    },
    openRealtimeRenderOnNodeTextEdit: true,
    enableAutoEnterTextEditWhenKeydown: true,
    demonstrateConfig: {
      openBlankMode: false
    },
    isLimitMindMapInCanvas: true,
    useLeftKeySelectionRightKeyDrag: useLeftKeySelectionRightKeyDrag.value,
    customInnerElsAppendTo: null,
    initRootNodePosition: ['center', 'center'],
    customHandleMousewheel: (e) => {
      if (!mm) return
      const {
        mouseScaleCenterUseMousePosition,
        disableMouseWheelZoom,
        translateRatio = 1,
        minZoomRatio = 20,
        maxZoomRatio = 400
      } = mm.opt || {}
      if (e.ctrlKey || e.metaKey) {
        if (disableMouseWheelZoom) return
        const { x: cx, y: cy } = mm.toPos(e.clientX, e.clientY)
        const centerX = mouseScaleCenterUseMousePosition ? cx : undefined
        const centerY = mouseScaleCenterUseMousePosition ? cy : undefined
        const factor = 1 - e.deltaY * 0.01
        const minScale = minZoomRatio / 100
        const maxScale = maxZoomRatio === -1 ? Infinity : maxZoomRatio / 100
        const newScale = Math.min(Math.max(mm.view.scale * factor, minScale), maxScale)
        mm.view.setScale(newScale, centerX, centerY)
        mm.emit('scale', mm.view.scale)
        return
      }
      mm.view.translateXY(
        -e.deltaX * translateRatio,
        -e.deltaY * translateRatio
      )
    },
    handleIsSplitByWrapOnPasteCreateNewNode: () => {
      return ElMessageBox.confirm(
        '是否按换行自动分割节点？',
        '提示',
        {
          confirmButtonText: '是',
          cancelButtonText: '否',
          type: 'warning'
        }
      )
    },
    errorHandler: (code, err) => {
      console.error('[MindMap Error]', code, err)
      if (code === 'export_error') {
        ElMessage.error('导出失败')
      }
    },
    expandBtnNumHandler: (num) => {
      return num >= 100 ? '...' : num
    },
    beforeDeleteNodeImg: (node) => {
      return new Promise((resolve) => {
        ElMessageBox.confirm(
          '是否确认删除该节点图片？',
          '提示',
          {
            confirmButtonText: '是',
            cancelButtonText: '否',
            type: 'warning'
          }
        ).then(() => {
          resolve(false)
        }).catch(() => {
          resolve(true)
        })
      })
    }
  })

  mindMap.value = mm
  actions.setMindMap(mm)

  // Yjs 实时协作（仅后端模式 + 非只读）
  if (props.mindmapId && !props.readonly) {
    yjsSync = new YjsMindmapSync(props.mindmapId, mm)
    yjsSync.start()
    // 事件驱动初始化：等待 sync_init 到达后再决定是否需要写入本地数据
    // 服务端在 auth_ok 后立即发送 sync_init，因此短暂等待即可
    const initDelay = setTimeout(() => {
      // 超时未收到 sync_init，且 doc 为空 → 首次创建，写入本地数据
      if (yjsSync && !yjsSync.hasData()) {
        yjsSync.initFromMindmap(root)
      }
    }, 800)
    // 如果提前收到 sync_init（doc 已有数据），取消延时 init
    const originalHandleSyncInit = yjsSync._handleSyncInit.bind(yjsSync)
    yjsSync._handleSyncInit = (data) => {
      clearTimeout(initDelay)
      originalHandleSyncInit(data)
    }
  }

  // Load dynamic plugins based on config
  if (openNodeRichText.value) {
    mm.addPlugin(RichText)
  }
  if (isShowScrollbar.value) {
    mm.addPlugin(ScrollbarPlugin)
  }

  // Forward all events from mindMap to bus
  forwardEvents.forEach(eventName => {
    mm.on(eventName, (...args) => {
      bus.emit(eventName, ...args)
    })
  })

  // Bind save events (use named functions for proper cleanup)
  if (!props.readonly) {
    bus.on('data_change', onBusDataChange)
    bus.on('view_data_change', onBusViewDataChange)
    // Yjs 增量同步（带反馈循环保护）
    if (yjsSync) {
      dataChangeDetailHandler = (detailList) => {
        // 跳过远程变更引发的本地事件，防止回写 Yjs 形成放大循环
        if (yjsSync.isApplyingRemote()) return
        yjsSync.onDataChangeDetail(detailList)
      }
      mm.on('data_change_detail', dataChangeDetailHandler)
    }

    // Ctrl+S manual save
    mm.keyCommand.addShortcut('Control+s', () => {
      manualSave()
    })
  }
}

// ── Save status tracking ──
function setSaveStatus(status) {
  saveStatus.value = status
  clearTimeout(saveStatusTimer)
  if (status === 'saved') {
    saveStatusTimer = setTimeout(() => { saveStatus.value = 'idle' }, 3000)
  }
}

function onBusDataChange(data) {
  if (props.mindmapId) {
    // 跳过远程变更或暂停状态（版本预览）引发的本地 data_change
    if (yjsSync && (yjsSync.isApplyingRemote() || yjsSync.isPaused())) return
    // 常规变更，使用防抖延迟
    // 如果是文本编辑退出，hide_text_edit 事件会紧随其后触发，
    // 取消此防抖计时器并立即保存（见 setupTextEditExitDetection）
    clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => {
      saveToBackend()
    }, AUTO_SAVE_DELAY)
  } else {
    actions.storeData({ root: data })
  }
}

function onBusViewDataChange(data) {
  if (props.readonly) return
  if (props.mindmapId) {
    // 跳过远程变更或暂停状态引发的本地视图变更
    if (yjsSync && (yjsSync.isApplyingRemote() || yjsSync.isPaused())) return
    // 后端模式：视图变更也触发保存（平移/缩放后 2 秒自动保存）
    clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => {
      saveToBackend()
    }, AUTO_SAVE_DELAY)
  } else {
    clearTimeout(storeConfigTimer)
    storeConfigTimer = setTimeout(() => {
      actions.storeData({ view: data })
    }, 300)
  }
}

async function saveToBackend() {
  if (!mindMap.value || !props.mindmapId || props.readonly) return

  if (isSaving.value) {
    pendingSave.value = true
    return
  }

  isSaving.value = true
  pendingSave.value = false
  setSaveStatus('saving')

  try {
    const fullData = mindMap.value.getData(true)
    await updateMindmapContent({
      id: props.mindmapId,
      nodeTree: fullData.root,
      viewData: fullData.view,
      layout: fullData.layout,
      theme: fullData.theme
    })
    setSaveStatus('saved')
    return true
  } catch (error) {
    console.error('自动保存失败:', error)
    setSaveStatus('error')
    return false
  } finally {
    isSaving.value = false
    if (pendingSave.value) {
      pendingSave.value = false
      clearTimeout(autoSaveTimer)
      autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
    }
  }
}

async function manualSave() {
  if (!mindMap.value) return
  if (props.mindmapId) {
    clearTimeout(autoSaveTimer)
    const ok = await saveToBackend()
    if (ok !== false) {
      ElMessage.success('已保存到服务器')
    } else {
      ElMessage.error('保存失败，请检查网络')
    }
  } else {
    const fullData = mindMap.value.getData(true)
    actions.storeData(fullData)
    ElMessage.success('已保存')
  }
}

function onExecCommand(...args) {
  mindMap.value?.execCommand(...args)
}

async function onExport(...args) {
  if (!mindMap.value) return
  try {
    await mindMap.value.export(...args)
  } catch (error) {
    console.error('导出失败:', error)
  }
}

async function onExportXmind(name = '思维导图') {
  if (!mindMap.value?.doExportXMind) return
  try {
    const data = mindMap.value.getData(true)
    const result = await mindMap.value.doExportXMind.xmind(data, name)
    if (result) {
      const url = URL.createObjectURL(result)
      const a = document.createElement('a')
      a.href = url
      a.download = name + '.xmind'
      a.click()
      URL.revokeObjectURL(url)
    }
  } catch (error) {
    console.error('XMind导出失败:', error)
    ElMessage.error('XMind 导出失败')
  }
}

function onSetData(data) {
  if (!mindMap.value) return
  let rootNodeData = null
  if (data.root) {
    mindMap.value.setFullData(data)
    rootNodeData = data.root
  } else {
    mindMap.value.setData(data)
    rootNodeData = data
  }
  mindMap.value.view.reset()
  manualSave()
  // If imported content is rich text, auto-enable rich text mode
  if (rootNodeData?.data?.richText && !openNodeRichText.value) {
    bus.emit('toggleOpenNodeRichText', true)
    ElNotification.info({
      title: '提示',
      message: '检测到导入了富文本内容，已自动开启富文本模式'
    })
  }
}

function onPaddingChange(data) {
  mindMap.value?.updateConfig(data)
}

function onStartTextEdit() {
  mindMap.value?.renderer?.startTextEdit?.()
}

function onEndTextEdit() {
  mindMap.value?.renderer?.endTextEdit?.()
}

function onCreateAssociativeLine() {
  mindMap.value?.associativeLine?.createLineFromActiveNode()
}

function onStartPainter() {
  mindMap.value?.painter?.startPainter()
}

function handleResize() {
  mindMap.value?.resize()
}

// --- Drag and drop import ---

function onDragenter() {
  showDragMask.value = true
}

function onDragleave() {
  showDragMask.value = false
}

function onDrop(e) {
  showDragMask.value = false
  const dt = e.dataTransfer
  const file = dt?.files?.[0]
  if (!file) return
  bus.emit('importFile', file)
}

// --- Bus event binding ---

function onToggleOpenNodeRichText(val) {
  actions.setLocalConfig({ openNodeRichText: !!val })
}

function bindBusEvents() {
  bus.on('execCommand', onExecCommand)
  bus.on('paddingChange', onPaddingChange)
  bus.on('export', onExport)
  bus.on('exportXmind', onExportXmind)
  bus.on('setData', onSetData)
  bus.on('startTextEdit', onStartTextEdit)
  bus.on('endTextEdit', onEndTextEdit)
  bus.on('createAssociativeLine', onCreateAssociativeLine)
  bus.on('startPainter', onStartPainter)
  bus.on('toggleOpenNodeRichText', onToggleOpenNodeRichText)
}

function unbindBusEvents() {
  bus.off('execCommand', onExecCommand)
  bus.off('paddingChange', onPaddingChange)
  bus.off('export', onExport)
  bus.off('exportXmind', onExportXmind)
  bus.off('setData', onSetData)
  bus.off('startTextEdit', onStartTextEdit)
  bus.off('endTextEdit', onEndTextEdit)
  bus.off('createAssociativeLine', onCreateAssociativeLine)
  bus.off('startPainter', onStartPainter)
  bus.off('data_change', onBusDataChange)
  bus.off('view_data_change', onBusViewDataChange)
  bus.off('toggleOpenNodeRichText', onToggleOpenNodeRichText)
  bus.off('hide_text_edit', onHideTextEdit)
}

/**
 * Yjs 重新初始化（版本恢复时由 VersionHistory 触发）
 * 销毁旧的 Yjs 连接，用恢复后的数据创建新的同步实例
 */
function onYjsReinit(restoredRoot) {
  if (!props.mindmapId || props.readonly) return
  // 销毁旧的 Yjs 同步
  if (yjsSync) {
    yjsSync.destroy()
    yjsSync = null
  }
  // 移除旧的 data_change_detail 监听器（使用具名引用）
  if (dataChangeDetailHandler) {
    mindMap.value?.off('data_change_detail', dataChangeDetailHandler)
    dataChangeDetailHandler = null
  }
  // 组件可能正在卸载，检查 mindMap 是否仍可用
  if (!mindMap.value) return
  // 创建新的 Yjs 同步，使用恢复后的数据
  yjsSync = new YjsMindmapSync(props.mindmapId, mindMap.value)

  // 拦截 sync_init：版本恢复后，本地已有正确数据，忽略服务端可能过期的旧状态
  const originalHandleSyncInit = yjsSync._handleSyncInit.bind(yjsSync)
  yjsSync._handleSyncInit = (data) => {
    if (yjsSync.hasData()) {
      // 本地已有恢复后的数据，跳过服务端的旧状态
      return
    }
    originalHandleSyncInit(data)
  }

  yjsSync.start()
  yjsSync.initFromMindmap(restoredRoot)
  // 重新绑定 data_change_detail 事件（具名引用）
  dataChangeDetailHandler = (detailList) => {
    if (yjsSync && yjsSync.isApplyingRemote()) return
    yjsSync.onDataChangeDetail(detailList)
  }
  mindMap.value.on('data_change_detail', dataChangeDetailHandler)
}

defineExpose({
  mindMap,
  getMindMap: () => mindMap.value,
  getYjsSync: () => yjsSync,
  saveStatus
})
</script>

<style lang="scss" scoped>
.editContainer {
  position: relative;
  flex: 1;
  overflow: hidden;

  .mindMapContainer {
    width: 100%;
    height: 100%;
  }

  .dragMask {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(255, 255, 255, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 3999;

    .dragTip {
      pointer-events: none;
      font-weight: bold;
      font-size: 16px;
      color: #333;
    }
  }
}
</style>
