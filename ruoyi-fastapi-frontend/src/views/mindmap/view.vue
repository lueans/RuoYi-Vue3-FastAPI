<template>
  <div ref="sharePage" class="share-view-page">
    <div class="share-view-header" v-if="mindmapData">
      <div class="headerContent">
        <div class="titleBlock">
          <span class="eyebrow">在线脑图</span>
          <h1 :title="mindmapData.name">{{ mindmapData.name }}</h1>
        </div>
        <el-tag type="info" effect="plain" round>只读分享</el-tag>
      </div>
      <span class="headerHint">拖动画布浏览，滚轮缩放</span>
    </div>
    <div class="share-view-body">
      <div v-if="loading" class="loadingState">
        <el-icon class="is-loading" :size="40"><Loading /></el-icon>
        <p>加载中...</p>
      </div>
      <div v-else-if="error" class="errorState">
        <el-result icon="error" :title="error">
          <template #extra>
            <el-button type="primary" :loading="loading" @click="loadShare">重新加载</el-button>
            <el-button @click="$router.push('/login')">登录工作台</el-button>
          </template>
        </el-result>
      </div>
      <template v-else-if="mindmapData">
        <div
          ref="mindMapContainer"
          class="mindMapContainer"
          role="region"
          :aria-label="`${mindmapData.name || '脑图'}只读画布`"
          tabindex="0"
        ></div>
        <nav class="viewerToolbar" aria-label="脑图视图控制">
          <button type="button" aria-label="缩小脑图" title="缩小（-）" @click="narrow">−</button>
          <output class="scaleValue" aria-live="polite" aria-label="当前缩放比例">
            {{ scalePercent }}%
          </output>
          <button type="button" aria-label="放大脑图" title="放大（+）" @click="enlarge">＋</button>
          <span class="toolbarDivider" aria-hidden="true"></span>
          <button type="button" class="textButton fitButton" title="适应画布（0）" @click="fitCanvas">
            适应画布
          </button>
          <button type="button" class="textButton" title="切换全屏" @click="toggleFullscreen">
            {{ isFullscreen ? '退出全屏' : '全屏' }}
          </button>
        </nav>
      </template>
    </div>
  </div>
</template>

<script setup name="MindmapShareView">
import { ref, onMounted, onBeforeUnmount, shallowRef, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { viewByShareToken } from '@/api/mindmap/share'
import MindMap from '@mind-map'
import { registerPreviewPlugins } from '@/components/MindMap/usePreviewPlugins'
import Themes from 'simple-mind-map-plugin-themes'
import { resolveMindmapPerformanceOptions } from '@/utils/mindmap-performance'
import { applyMindmapDocumentConfig, getMindmapDocumentConfig } from '@/utils/mindmap-document-config'
import { createScopedAsyncSession } from '@/utils/mindmap-async'

Themes.init(MindMap)

const route = useRoute()
const loading = ref(true)
const error = ref('')
const mindmapData = ref(null)
const sharePage = ref(null)
const mindMapContainer = ref(null)
const mindMap = shallowRef(null)
const scalePercent = ref(100)
const isFullscreen = ref(false)
const shareSession = createScopedAsyncSession()
let shareRequestController = null
let componentActive = false

function getRouteShareToken() {
  const token = route.params.token
  return typeof token === 'string' ? token.trim() : ''
}

function isShareSessionCurrent(session, signal) {
  return Boolean(
    componentActive
    && shareSession.isCurrent(session)
    && getRouteShareToken() === session?.identity
    && signal?.aborted !== true
  )
}

function cancelShareLoad() {
  shareSession.invalidate()
  shareRequestController?.abort()
  shareRequestController = null
}

async function loadShare() {
  cancelShareLoad()
  const token = getRouteShareToken()
  const session = shareSession.activate(token)
  destroyMindMap()
  mindmapData.value = null
  error.value = ''
  if (!token) {
    error.value = '无效的分享链接'
    loading.value = false
    return
  }

  const controller = new AbortController()
  const { signal } = controller
  shareRequestController = controller
  loading.value = true
  try {
    const res = await viewByShareToken(token, { signal })
    if (!isShareSessionCurrent(session, signal)) return false
    const data = res.data
    await registerPreviewPlugins({
      root: data.nodeTree,
      layout: data.layout,
      documentData: data.documentData,
    })
    if (!isShareSessionCurrent(session, signal)) return false

    // 先结束加载态，让 v-else 中的画布容器进入 DOM，再初始化渲染器。
    mindmapData.value = data
    loading.value = false
    await nextTick()
    if (!isShareSessionCurrent(session, signal)) return false
    return initMindMap(data, session, signal)
  } catch (e) {
    if (!isShareSessionCurrent(session, signal)) return false
    destroyMindMap()
    mindmapData.value = null
    error.value = e?.message || '加载失败'
    return false
  } finally {
    if (isShareSessionCurrent(session, signal)) loading.value = false
    if (shareRequestController === controller) shareRequestController = null
  }
}

onMounted(() => {
  componentActive = true
  void loadShare()
  window.addEventListener('keydown', handleShortcut)
  window.addEventListener('resize', handleResize)
  document.addEventListener('fullscreenchange', handleFullscreenChange)
})

watch(() => route.params.token, (token, previousToken) => {
  if (token !== previousToken) void loadShare()
})

function initMindMap(data, session, signal) {
  if (!mindMapContainer.value || !isShareSessionCurrent(session, signal)) return false

  const performanceOptions = resolveMindmapPerformanceOptions({ root: data.nodeTree })
  const documentConfig = getMindmapDocumentConfig(data.documentData)
  const instance = new MindMap({
    ...documentConfig,
    el: mindMapContainer.value,
    data: data.nodeTree || { data: { text: '空脑图' }, children: [] },
    layout: data.layout || 'logicalStructure',
    theme: data.theme?.template || 'default',
    themeConfig: data.theme?.config || {},
    viewData: data.viewData || null,
    readonly: true,
    openPerformance: performanceOptions.openPerformance,
    openRealtimeRenderOnNodeTextEdit: performanceOptions.openRealtimeRenderOnNodeTextEdit,
    fit: true,
    enableFreeDrag: false,
    isLimitMindMapInCanvas: true,
    customInnerElsAppendTo: null,
  })
  if (!isShareSessionCurrent(session, signal)) {
    instance.destroy()
    return false
  }
  mindMap.value = instance
  applyMindmapDocumentConfig(instance, data.documentData)
  instance.on('scale', handleScale)
  scalePercent.value = Math.round((instance.view?.scale || 1) * 100)
  return true
}

function handleScale(scale) {
  scalePercent.value = Math.round(Number(scale || 1) * 100)
}

function narrow() {
  mindMap.value?.view?.narrow()
}

function enlarge() {
  mindMap.value?.view?.enlarge()
}

function fitCanvas() {
  mindMap.value?.view?.fit()
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
    } else {
      await sharePage.value?.requestFullscreen?.()
    }
  } catch {
    // 浏览器或嵌入环境拒绝全屏时保持当前视图，不影响分享内容浏览。
  }
}

function handleFullscreenChange() {
  isFullscreen.value = Boolean(document.fullscreenElement)
  nextTick(handleResize)
}

function handleResize() {
  mindMap.value?.resize?.()
}

function handleShortcut(event) {
  if (!mindMap.value) return
  if (event.ctrlKey || event.metaKey || event.altKey) return
  const tagName = event.target?.tagName?.toLowerCase()
  if (tagName === 'input' || tagName === 'textarea' || event.target?.isContentEditable) return
  if (event.key === '+' || event.key === '=') {
    event.preventDefault()
    enlarge()
  } else if (event.key === '-') {
    event.preventDefault()
    narrow()
  } else if (event.key === '0') {
    event.preventDefault()
    fitCanvas()
  }
}

function destroyMindMap() {
  if (!mindMap.value) return
  mindMap.value.off?.('scale', handleScale)
  mindMap.value.destroy()
  mindMap.value = null
  scalePercent.value = 100
}

onBeforeUnmount(() => {
  componentActive = false
  cancelShareLoad()
  destroyMindMap()
  window.removeEventListener('keydown', handleShortcut)
  window.removeEventListener('resize', handleResize)
  document.removeEventListener('fullscreenchange', handleFullscreenChange)
})
</script>

<style lang="scss" scoped>
.share-view-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(circle at 15% 0%, rgba(64, 158, 255, 0.08), transparent 30%),
    #f6f8fb;
  color: #182230;
}

.share-view-header {
  min-height: 66px;
  padding: 10px clamp(16px, 3vw, 36px);
  background: rgba(255, 255, 255, 0.9);
  border-bottom: 1px solid rgba(216, 222, 232, 0.9);
  backdrop-filter: blur(16px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  z-index: 2;

  .headerContent {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;

    .titleBlock {
      min-width: 0;
    }

    .eyebrow {
      display: block;
      margin-bottom: 2px;
      color: #8a94a6;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      max-width: min(52vw, 720px);
      overflow: hidden;
      color: #172033;
      font-size: 17px;
      font-weight: 650;
      line-height: 1.25;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .headerHint {
    flex: none;
    color: #8a94a6;
    font-size: 12px;
  }
}

.share-view-body {
  flex: 1;
  overflow: hidden;
  position: relative;

  .loadingState, .errorState {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #7a8496;

    p {
      margin-top: 16px;
      font-size: 14px;
    }
  }

  .mindMapContainer {
    width: 100%;
    height: 100%;
    background: rgba(255, 255, 255, 0.54);
  }

  .viewerToolbar {
    position: absolute;
    bottom: 20px;
    left: 50%;
    z-index: 3;
    display: flex;
    align-items: center;
    gap: 4px;
    min-height: 44px;
    padding: 5px 7px;
    border: 1px solid rgba(213, 219, 229, 0.95);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.94);
    box-shadow: 0 12px 32px rgba(27, 39, 61, 0.14), 0 2px 8px rgba(27, 39, 61, 0.06);
    transform: translateX(-50%);
    backdrop-filter: blur(18px);

    button {
      min-width: 34px;
      height: 34px;
      padding: 0 9px;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: #445064;
      cursor: pointer;
      font: inherit;
      font-size: 18px;
      transition: color 0.16s ease, background 0.16s ease, transform 0.16s ease;

      &:hover {
        background: #eef4ff;
        color: #337ecc;
      }

      &:active {
        transform: scale(0.96);
      }

      &:focus-visible {
        outline: 2px solid #409eff;
        outline-offset: 1px;
      }
    }

    .textButton {
      font-size: 12px;
      white-space: nowrap;
    }

    .scaleValue {
      min-width: 48px;
      color: #657086;
      font-size: 12px;
      font-variant-numeric: tabular-nums;
      text-align: center;
    }

    .toolbarDivider {
      width: 1px;
      height: 20px;
      margin: 0 3px;
      background: #e3e7ee;
    }
  }
}

@media (max-width: 640px) {
  .share-view-header {
    min-height: 58px;

    .headerHint {
      display: none;
    }

    .headerContent h1 {
      max-width: 58vw;
      font-size: 15px;
    }
  }

  .share-view-body .viewerToolbar {
    bottom: max(12px, env(safe-area-inset-bottom));
    max-width: calc(100vw - 24px);

    .fitButton {
      display: none;
    }
  }
}

@media (prefers-reduced-motion: reduce) {
  .viewerToolbar button {
    transition: none !important;
  }
}
</style>
