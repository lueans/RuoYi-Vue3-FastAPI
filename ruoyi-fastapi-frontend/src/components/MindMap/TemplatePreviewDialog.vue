<template>
  <el-dialog
    v-model="visible"
    class="templatePreviewDialog"
    width="min(1080px, 94vw)"
    top="5vh"
    destroy-on-close
    :close-on-click-modal="!using"
    :close-on-press-escape="!using"
    :show-close="!using"
    @opened="handleDialogOpened"
    @closed="handleDialogClosed"
  >
    <template #header>
      <div class="dialogHeader">
        <div>
          <span class="eyebrow">模板预览</span>
          <h2 :title="template?.name || '加载模板'">{{ template?.name || '加载模板' }}</h2>
        </div>
        <el-tag v-if="template?.layout" type="info" effect="plain" round>
          {{ template.layout }}
        </el-tag>
      </div>
    </template>

    <div class="previewBody" aria-live="polite">
      <div v-if="loading" class="statePanel">
        <el-icon class="is-loading" :size="36"><Loading /></el-icon>
        <p>正在加载模板预览…</p>
      </div>
      <el-result v-else-if="error" icon="error" title="模板预览加载失败" :sub-title="error">
        <template #extra>
          <el-button type="primary" @click="loadTemplate">重新加载</el-button>
        </template>
      </el-result>
      <template v-else-if="template">
        <div ref="canvasContainer" class="canvasContainer" aria-label="只读模板脑图预览"></div>
        <nav class="previewToolbar" aria-label="模板预览控制">
          <button type="button" aria-label="缩小模板" title="缩小" @click="narrow">−</button>
          <output aria-live="polite" aria-label="当前缩放比例">{{ scalePercent }}%</output>
          <button type="button" aria-label="放大模板" title="放大" @click="enlarge">＋</button>
          <span aria-hidden="true"></span>
          <button type="button" class="textButton" @click="fitCanvas">适应画布</button>
        </nav>
      </template>
    </div>

    <div v-if="template?.description && !loading && !error" class="templateDescription">
      {{ template.description }}
    </div>

    <template #footer>
      <el-button :disabled="using" @click="visible = false">关闭</el-button>
      <el-button
        v-if="allowUse"
        type="primary"
        :loading="using"
        :disabled="loading || Boolean(error) || !template"
        @click="$emit('use', template)"
      >
        使用此模板
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import MindMap from '@mind-map'
import Themes from 'simple-mind-map-plugin-themes'
import { getTemplateDetail } from '@/api/mindmap/template'
import { registerPreviewPlugins } from '@/components/MindMap/usePreviewPlugins'
import { createLatestRequestTracker } from '@/utils/mindmap-async'
import { resolveMindmapPerformanceOptions } from '@/utils/mindmap-performance'
import { getMindmapTemplateErrorMessage } from '@/utils/mindmap-template'
import { applyMindmapDocumentConfig, getMindmapDocumentConfig } from '@/utils/mindmap-document-config'

Themes.init(MindMap)

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  templateId: { type: [Number, String], default: null },
  allowUse: { type: Boolean, default: true },
  using: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'use'])

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})
const loading = ref(false)
const error = ref('')
const template = ref(null)
const canvasContainer = ref(null)
const mindMap = shallowRef(null)
const scalePercent = ref(100)
const requestTracker = createLatestRequestTracker()
let resizeObserver = null

watch(
  () => [props.modelValue, props.templateId],
  ([isVisible]) => {
    if (isVisible) loadTemplate()
    else requestTracker.invalidate()
  },
  { immediate: true },
)

async function loadTemplate() {
  const id = Number(props.templateId)
  destroyMindMap()
  template.value = null
  error.value = ''
  if (!Number.isSafeInteger(id) || id <= 0) {
    error.value = '模板编号无效'
    loading.value = false
    return
  }

  const requestId = requestTracker.begin()
  loading.value = true
  try {
    const response = await getTemplateDetail(id)
    if (!requestTracker.isCurrent(requestId)) return
    const document = response?.data
    if (!document?.nodeTree || typeof document.nodeTree !== 'object') {
      throw new Error('模板内容为空或格式不正确')
    }
    await registerPreviewPlugins({ root: document.nodeTree, layout: document.layout })
    if (!requestTracker.isCurrent(requestId)) return
    template.value = document
    loading.value = false
    await nextTick()
    initMindMap()
  } catch (loadError) {
    if (!requestTracker.isCurrent(requestId)) return
    error.value = getMindmapTemplateErrorMessage(loadError, '无法加载模板内容，请稍后重试')
  } finally {
    if (requestTracker.isCurrent(requestId)) loading.value = false
  }
}

function initMindMap() {
  if (!canvasContainer.value || !template.value || mindMap.value) return
  const document = template.value
  const performanceOptions = resolveMindmapPerformanceOptions({ root: document.nodeTree })
  const documentConfig = getMindmapDocumentConfig(document.documentData)
  mindMap.value = new MindMap({
    ...documentConfig,
    el: canvasContainer.value,
    data: document.nodeTree,
    layout: document.layout || 'logicalStructure',
    theme: document.theme?.template || 'default',
    themeConfig: document.theme?.config || {},
    viewData: document.viewData || null,
    readonly: true,
    fit: true,
    enableFreeDrag: false,
    isLimitMindMapInCanvas: true,
    openPerformance: performanceOptions.openPerformance,
    openRealtimeRenderOnNodeTextEdit: performanceOptions.openRealtimeRenderOnNodeTextEdit,
  })
  applyMindmapDocumentConfig(mindMap.value, document.documentData)
  mindMap.value.on('scale', handleScale)
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => mindMap.value?.resize?.())
    resizeObserver.observe(canvasContainer.value)
  }
  scalePercent.value = Math.round((mindMap.value.view?.scale || 1) * 100)
}

function handleDialogOpened() {
  initMindMap()
  nextTick(() => mindMap.value?.resize?.())
}

function handleDialogClosed() {
  requestTracker.invalidate()
  destroyMindMap()
  template.value = null
  error.value = ''
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

function destroyMindMap() {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (!mindMap.value) return
  mindMap.value.off?.('scale', handleScale)
  mindMap.value.destroy()
  mindMap.value = null
  scalePercent.value = 100
}

onBeforeUnmount(() => {
  requestTracker.invalidate()
  destroyMindMap()
})
</script>

<style lang="scss">
.templatePreviewDialog {
  border-radius: 16px;
  overflow: hidden;

  .el-dialog__body {
    padding: 0 20px 12px;
  }

  .dialogHeader {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding-right: 24px;

    .eyebrow {
      color: #8a94a6;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.12em;
    }

    h2 {
      margin: 3px 0 0;
      max-width: 70vw;
      overflow: hidden;
      color: #172033;
      font-size: 18px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .previewBody {
    position: relative;
    height: min(62vh, 650px);
    min-height: 360px;
    overflow: hidden;
    border: 1px solid #e3e8f0;
    border-radius: 12px;
    background: #f7f9fc;

    .statePanel,
    .el-result {
      display: flex;
      height: 100%;
      align-items: center;
      justify-content: center;
    }

    .statePanel {
      flex-direction: column;
      color: #7a8496;
    }

    .canvasContainer {
      width: 100%;
      height: 100%;
      background: #fff;
    }
  }

  .previewToolbar {
    position: absolute;
    bottom: 14px;
    left: 50%;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 5px 7px;
    border: 1px solid #d9e0ea;
    border-radius: 13px;
    background: rgba(255, 255, 255, 0.95);
    box-shadow: 0 10px 28px rgba(31, 45, 70, 0.14);
    transform: translateX(-50%);

    button {
      min-width: 34px;
      height: 34px;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: #445064;
      cursor: pointer;
      font: inherit;
      font-size: 18px;

      &:hover,
      &:focus-visible {
        background: #edf4ff;
        color: #2563eb;
        outline: none;
      }
    }

    output {
      min-width: 48px;
      color: #667085;
      font-size: 12px;
      text-align: center;
    }

    > span {
      width: 1px;
      height: 20px;
      margin: 0 3px;
      background: #e3e8f0;
    }

    .textButton {
      padding: 0 10px;
      font-size: 12px;
    }
  }

  .templateDescription {
    margin-top: 10px;
    color: #667085;
    font-size: 13px;
    line-height: 1.6;
  }
}

@media (max-width: 640px) {
  .templatePreviewDialog .previewBody {
    height: 56vh;
    min-height: 300px;
  }
}
</style>
