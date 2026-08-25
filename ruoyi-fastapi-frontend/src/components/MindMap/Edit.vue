<template>
  <div
    class="editContainer"
    :class="{ hasPropertyInspector, isDark: store.localConfig.isDark }"
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
      role="region"
      :aria-label="isReadonly ? '脑图只读画布' : '脑图编辑画布'"
      tabindex="0"
    ></div>
    <WorkspaceActivityBar v-if="!isZenMode" />
    <Navigator v-if="mindMap" :mindMap="mindMap" />
    <OutlineSidebar v-if="mindMap && activeSidebar === 'outline'" :mindMap="mindMap" />
    <AssociativeLineStyle v-if="mindMap" :mindMap="mindMap" />
    <PropertyInspector
      v-if="mindMap && hasPropertyInspector"
      :mindMap="mindMap"
      @document-meta-change="onDocumentMetaChange"
    />
    <ShortcutKey v-if="mindMap && activeSidebar === 'shortcutKey'" />
    <Contextmenu v-if="mindMap" :mindMap="mindMap" />
    <NodeTagSidebar
      v-if="mindMap && activeSidebar === 'nodeTagSidebar'"
      :mindMap="mindMap"
    />
    <Search v-if="mindMap" :mindMap="mindMap" :mindmapId="props.mindmapId" />
    <SidebarTrigger v-if="!isZenMode" />
    <Setting
      v-if="mindMap && activeSidebar === 'setting'"
      :mindMap="mindMap"
      :document-data="documentData"
      @document-config-change="onDocumentConfigChange"
    />
    <RichTextToolbar v-if="mindMap" :mindMap="mindMap" />
    <NodeAttachment v-if="mindMap" :readonly="isReadonly" />
    <NodeImgPlacementToolbar v-if="mindMap" :mindMap="mindMap" />
    <NodeOuterFrame v-if="mindMap" :mindMap="mindMap" />
    <NodeNoteContentShow v-if="mindMap" :mindMap="mindMap" />
    <NodeNoteSidebar v-if="mindMap" :mindMap="mindMap" />
    <NodeImgPreview v-if="mindMap" :mindMap="mindMap" />
    <FormulaSidebar v-if="mindMap && activeSidebar === 'formulaSidebar'" :mindMap="mindMap" />
    <OutlineEdit v-if="mindMap" :mindMap="mindMap" />
    <VersionHistory
      v-if="mindMap && activeSidebar === 'versionHistory'"
      :mindMap="mindMap"
      :mindmapId="props.mindmapId"
      :yjsSync="yjsSyncRef"
      :readonly="isReadonly"
      :flush-changes="flushBeforeLeave"
      @yjs-reinit="onYjsReinit"
      @change-tracking="onVersionChangeTracking"
    />
    <CollaboratorManager
      v-if="mindMap && store.canManageCollaborators && activeSidebar === 'collaboratorManager'"
      :mindmapId="props.mindmapId"
    />
    <div
      class="dragMask"
      v-if="showDragMask"
      @dragleave.stop.prevent="onDragleave"
      @dragover.stop.prevent
      @drop.stop.prevent="onDrop"
    >
      <div class="dragTip" role="status" aria-live="polite">在此释放以导入该文件</div>
    </div>
  </div>
</template>

<script setup>
import MindMap from '@mind-map'
import {
  ensureExportPlugins,
  registerPlugins,
  RichText,
  ScrollbarPlugin,
} from './usePlugins'
import Themes from 'simple-mind-map-plugin-themes'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import bus from './useEventBus'
import {
  store,
  actions,
  isMindmapSidebarReadonlySafe,
} from './useStore'
import { defaultData } from './config'
import { batchUpdateMindmapContent, getMindmap } from '@/api/mindmap/mindmap'
import { YjsMindmapSync } from '@/utils/yjs-sync'
import { resolveMindmapPerformanceOptions } from '@/utils/mindmap-performance'
import { ensureMindmapDocumentPlugins } from '@/utils/mindmap-plugin-loader'
import {
  calculateMindmapWheelScale,
  clampMindmapScale,
  shouldZoomMindmapWheel
} from '@/utils/mindmap-zoom'
import {
  applyMindmapDocumentConfig,
  getMindmapDocumentConfig,
  getMindmapLocalRuntimeConfig,
  normalizeMindmapDocumentData,
  updateMindmapDocumentConfig,
} from '@/utils/mindmap-document-config'
import {
  appendUniqueMindmapOperation,
  buildCrossNodeContentOperations,
  buildMindmapContentOperations,
  buildNodeTagContentOperations,
  detectMindmapFileOperations,
  snapshotMindmapDocumentMeta,
} from '@/utils/mindmap-operations'
import { extractCrossNodeState } from '@/utils/yjs-cross-node-state'
import useUserStore from '@/store/modules/user'
import {
  areMindmapDraftDocumentsEqual,
  getMindmapDraft,
  removeMindmapDraft,
  saveMindmapDraft,
  saveMindmapDraftFallbackSync,
} from '@/utils/mindmap-draft'
import { downloadMindmapBackup } from '@/utils/mindmap-backup'
import { isMindmapContentWritable } from '@/utils/mindmap-content-state'
import { flushPendingMindmapChanges } from '@/utils/mindmap-save-lifecycle'
import {
  assertMindmapSaveMutationResponse,
  createMindmapSaveMutation,
  submitMindmapSaveMutation,
} from '@/utils/mindmap-save-mutation'
import { normalizeMindmapExportRuntimeConfig } from '@/utils/mindmap-export'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'
import { assertMindmapImportDocument } from '@/utils/mindmap-import-validation'
import { createMindmapDocumentMetaBuffer } from '@/utils/mindmap-document-meta-buffer'
import { applyMindmapDocumentPreservingRuntimeState } from '@/utils/mindmap-document-apply'
import { normalizeMindmapDocumentMetaPatch } from '@/utils/mindmap-local-workspace'
import { createMindmapDraftProtectionTracker } from '@/utils/mindmap-draft-protection'
import './assets/icon-font/iconfont.css'
import './styles/markdown.scss'

import Contextmenu from './Contextmenu.vue'
import Navigator from './Navigator.vue'
import Search from './Search.vue'
import WorkspaceActivityBar from './WorkspaceActivityBar.vue'
import SidebarTrigger from './SidebarTrigger.vue'
import PropertyInspector from './PropertyInspector.vue'
import ShortcutKey from './ShortcutKey.vue'
import OutlineSidebar from './OutlineSidebar.vue'
import NodeTagSidebar from './NodeIconSidebar.vue'
import AssociativeLineStyle from './AssociativeLineStyle.vue'
import Setting from './Setting.vue'
import RichTextToolbar from './RichTextToolbar.vue'
import NodeAttachment from './NodeAttachment.vue'
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
  readonly: { type: Boolean, default: false },
  draftKey: { type: String, default: '' },
})

const emit = defineEmits([
  'name-change',
  'access-change',
  'ready',
  'load-error',
  'document-deleted',
  'document-archived',
  'access-revoked',
  'session-ended',
])
const userStore = useUserStore()
const serverCanEdit = ref(props.mindmapId ? null : true)
const isReadonly = computed(() => (
  props.readonly || (Boolean(props.mindmapId) && serverCanEdit.value !== true)
))
let terminalState = ''

const editContainerRef = ref(null)
const mindMapContainerRef = ref(null)
const mindMap = shallowRef(null)
const documentData = ref({})
const showDragMask = ref(false)
let storeConfigTimer = null
let localWorkspaceSaveFailureNotified = false
let enableShowLoading = true
let autoSaveTimer = null
let yjsSync = null
const yjsSyncRef = shallowRef(null)
const isSaving = ref(false)
const pendingSave = ref(false)
const saveStatus = ref('idle') // idle | pending | saving | retrying | syncing | offline | saved | error
let saveStatusTimer = null
const AUTO_SAVE_DELAY = 2000
const DRAFT_SAVE_DELAY = 500
const CLOUD_EXIT_MAX_PASSES = 3
const SAVE_RETRY_DELAYS = [2000, 5000, 10000, 30000, 60000]
const AUTHORITATIVE_RELOAD_RETRY_DELAYS = [2000, 5000, 10000, 30000]
let dataChangeDetailHandler = null
let contentRevision = 1
let pendingContentOperations = []
let activeSaveMutation = null
let authoritativeReloadRequired = false
let authoritativeReloadTimer = null
let authoritativeReloadAttempt = 0
let authoritativeReloadInProgress = false
let authoritativeReloadNoticeShown = false
let viewChangeVersion = 0
let savedViewChangeVersion = 0
let savedDocumentMeta = null
const nodeRevisionMap = new Map()
let conflictBlocked = false
let blockedConflictData = null
const saveRecoveryKind = ref('')
let applyingServerTree = false
let versionChangeTrackingPaused = false
let terminatingSession = false
let componentMounted = false
let sessionController = null
let localDraftDialogOpen = false
let conflictDialogOpen = false
let conflictResolutionPromise = null
let resolvingStaleState = false
let restoredLocalDraft = false
let restoredDraftRecord = null
let draftSaveTimer = null
let draftWriteQueue = Promise.resolve()
let lastDraftUpdatedAt = 0
let saveRetryTimer = null
let saveRetryAttempt = 0
let retryNoticeShown = false
let localDraftFailureNoticeShown = false
let crossNodeOperationSnapshot = null
let authoritativeCollaborationResetRequired = false

const documentMetaBuffer = createMindmapDocumentMetaBuffer((meta) => {
  yjsSync?.syncDocumentMeta(meta)
})
const draftProtection = createMindmapDraftProtectionTracker()

function createMutationId() {
  return globalThis.crypto?.randomUUID?.()
    || `mindmap-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const draftSessionId = createMutationId()

function markDocumentMetaSaved(document) {
  savedDocumentMeta = snapshotMindmapDocumentMeta(document)
}

function queueFileOperation(type) {
  appendUniqueMindmapOperation(pendingContentOperations, type)
}

function recordDocumentOperations(document) {
  const comparisonBaseline = activeSaveMutation?.document
    ? snapshotMindmapDocumentMeta(activeSaveMutation.document)
    : savedDocumentMeta
  for (const type of detectMindmapFileOperations(document, comparisonBaseline)) {
    queueFileOperation(type)
  }
}

function getCurrentDocument() {
  const data = mindMap.value?.getData?.(true) || {}
  return {
    ...data,
    documentData: normalizeMindmapDocumentData(documentData.value),
  }
}

function persistLocalWorkspace(data) {
  const saved = actions.storeData(data)
  if (saved) {
    localWorkspaceSaveFailureNotified = false
    return true
  }
  if (!localWorkspaceSaveFailureNotified) {
    localWorkspaceSaveFailureNotified = true
    ElMessage.error('本地保存失败：数据异常或浏览器存储空间不足，请及时导出备份')
  }
  return false
}

function onDocumentMetaChange(patch) {
  if (
    isReadonly.value
    || isChangeTrackingSuspended()
    || !patch
    || typeof patch !== 'object'
    || Array.isArray(patch)
  ) return
  let normalizedPatch
  try {
    normalizedPatch = normalizeMindmapDocumentMetaPatch(patch)
  } catch (error) {
    console.warn('忽略无效的脑图文档元数据:', error)
    return
  }
  if (Object.keys(normalizedPatch).length === 0) return
  if (!props.mindmapId) {
    persistLocalWorkspace(normalizedPatch)
    return
  }
  const current = getCurrentDocument()
  recordDocumentOperations(current)
  scheduleYjsMetaSync(normalizedPatch)
  scheduleLocalDraftPersist()
  resetSaveRetryForNewChange()
  clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
}

function onDocumentConfigChange(patch) {
  if (isReadonly.value || isChangeTrackingSuspended()) return
  documentData.value = updateMindmapDocumentConfig(documentData.value, patch)
  applyMindmapDocumentConfig(mindMap.value, documentData.value)
  onDocumentMetaChange({ documentData: documentData.value })
}

function scheduleYjsMetaSync(document, delay = 120) {
  return documentMetaBuffer.enqueue(document, delay)
}

function flushPendingYjsMetaSync() {
  return documentMetaBuffer.flush()
}

function canUseLocalDraft() {
  return Boolean(props.mindmapId && userStore.id && !isReadonly.value)
}

function nextDraftUpdatedAt() {
  lastDraftUpdatedAt = Math.max(Date.now(), lastDraftUpdatedAt + 1)
  return lastDraftUpdatedAt
}

function createDraftOptions(document) {
  return {
    userId: userStore.id,
    mindmapId: props.mindmapId,
    sessionId: draftSessionId,
    contentRevision,
    document,
    updatedAt: nextDraftUpdatedAt(),
  }
}

function enqueueDraftOperation(operation) {
  draftWriteQueue = draftWriteQueue
    .catch(() => undefined)
    .then(operation)
    .catch((error) => {
      console.warn('本地脑图草稿操作失败:', error)
    })
  return draftWriteQueue
}

function scheduleLocalDraftPersist() {
  if (terminalState || !canUseLocalDraft() || !mindMap.value) return
  draftProtection.markDirty()
  clearTimeout(draftSaveTimer)
  draftSaveTimer = setTimeout(() => {
    persistLocalDraft()
  }, DRAFT_SAVE_DELAY)
}

function persistLocalDraft({ notifyFailure = true } = {}) {
  if (terminalState || !canUseLocalDraft() || !mindMap.value) {
    return Promise.resolve({ saved: false, skipped: true })
  }
  clearTimeout(draftSaveTimer)
  const draftChangeVersion = draftProtection.beginPersist()
  const options = createDraftOptions(getCurrentDocument())
  return enqueueDraftOperation(() => saveMindmapDraft(options)).then((result) => {
    if (result?.saved === true) {
      draftProtection.recordPersistResult(draftChangeVersion, true)
      localDraftFailureNoticeShown = false
      if (saveRecoveryKind.value === 'draft') {
        saveRecoveryKind.value = ''
        if (isBrowserOffline()) setSaveStatus('offline')
        else if (saveRetryTimer) setSaveStatus('retrying')
        else if (hasUnsavedChanges()) setSaveStatus('pending')
      }
      return result
    }
    draftProtection.recordPersistResult(draftChangeVersion, false)
    if (!terminalState && componentMounted && hasUnsavedChanges()) {
      saveRecoveryKind.value = 'draft'
      setSaveStatus('error')
      if (notifyFailure && !localDraftFailureNoticeShown) {
        localDraftFailureNoticeShown = true
        ElNotification.error({
          title: '本地草稿保存失败',
          message: '修改仍只存在当前页面，请点击“保护修改”重试或下载 JSON 备份',
        })
      }
    }
    return result || { saved: false, storage: null }
  })
}

function clearLocalDraft(beforeUpdatedAt) {
  if (!canUseLocalDraft()) return
  clearTimeout(draftSaveTimer)
  const userId = userStore.id
  const mindmapId = props.mindmapId
  enqueueDraftOperation(() => removeMindmapDraft(userId, mindmapId, {
    beforeUpdatedAt,
    sessionId: draftSessionId,
  }))
}

function clearDraftRecord(record) {
  if (!record?.key) return
  const userId = userStore.id
  const mindmapId = props.mindmapId
  enqueueDraftOperation(() => removeMindmapDraft(userId, mindmapId, {
    key: record.key,
    beforeUpdatedAt: record.updatedAt,
  }))
}

function clearRestoredDraft() {
  if (!restoredDraftRecord) return
  const record = restoredDraftRecord
  restoredDraftRecord = null
  clearDraftRecord(record)
}

function requestAuthoritativeCollaborationReset() {
  authoritativeCollaborationResetRequired = true
}

function persistLocalDraftBeforeUnload() {
  if (terminalState || !canUseLocalDraft() || !mindMap.value || !hasUnsavedChanges()) return false
  const draftChangeVersion = draftProtection.beginPersist()
  const saved = saveMindmapDraftFallbackSync(createDraftOptions(getCurrentDocument()))
  draftProtection.recordPersistResult(draftChangeVersion, saved)
  return saved
}

function handlePageHide() {
  persistLocalDraftBeforeUnload()
}

function handleVisibilityChange() {
  if (document.visibilityState !== 'hidden' || !hasUnsavedChanges()) return
  // localStorage provides the immediate freeze/navigation fallback; IndexedDB
  // remains the durable, larger-capacity primary draft store when time permits.
  persistLocalDraftBeforeUnload()
  persistLocalDraft()
}

function sessionCancelled(signal) {
  return !componentMounted || Boolean(terminalState) || signal?.aborted === true
}

function cancelSessionAsyncWork() {
  sessionController?.abort()
  sessionController = null
  clearTimeout(authoritativeReloadTimer)
  authoritativeReloadTimer = null
  authoritativeReloadInProgress = false
  if (localDraftDialogOpen || conflictDialogOpen) ElMessageBox.close()
  localDraftDialogOpen = false
  conflictDialogOpen = false
}

async function resolveLocalDraft(serverDocument, signal) {
  if (!canUseLocalDraft() || sessionCancelled(signal)) return null
  let draft
  try {
    draft = await getMindmapDraft(userStore.id, props.mindmapId, {
      key: props.draftKey || undefined,
    })
  } catch {
    return null
  }
  if (sessionCancelled(signal)) return null
  if (!draft) return null
  if (areMindmapDraftDocumentsEqual(draft.document, serverDocument)) {
    clearDraftRecord(draft)
    return null
  }

  if (Number(draft.contentRevision) === Number(contentRevision)) {
    try {
      localDraftDialogOpen = true
      await ElMessageBox.confirm(
        `检测到 ${new Date(draft.updatedAt).toLocaleString()} 保存的本地草稿，是否恢复？`,
        '发现未提交的本地草稿',
        {
          type: 'warning',
          confirmButtonText: '恢复本地草稿',
          cancelButtonText: '使用云端版本',
          distinguishCancelAndClose: true,
          closeOnClickModal: false,
        }
      )
      if (sessionCancelled(signal)) return null
      restoredDraftRecord = { key: draft.key, updatedAt: draft.updatedAt }
      return draft.document
    } catch (action) {
      if (sessionCancelled(signal)) return null
      if (action === 'cancel') {
        clearDraftRecord(draft)
        requestAuthoritativeCollaborationReset()
      }
      return null
    } finally {
      localDraftDialogOpen = false
    }
  }

  try {
    localDraftDialogOpen = true
    await ElMessageBox.confirm(
      `本地草稿基于版本 ${draft.contentRevision}，云端已更新到版本 ${contentRevision}。为避免覆盖协作者内容，只能下载草稿副本后使用云端版本。`,
      '发现冲突草稿',
      {
        type: 'warning',
        confirmButtonText: '下载草稿副本',
        cancelButtonText: '丢弃草稿并使用云端',
        distinguishCancelAndClose: true,
        closeOnClickModal: false,
      }
    )
    if (sessionCancelled(signal)) return null
    const downloaded = downloadConflictBackup(draft.document, 'mindmap-local-draft')
    if (downloaded) {
      clearDraftRecord(draft)
    } else {
      ElMessage.error('浏览器未能下载草稿，副本仍保留在本地草稿中心')
    }
  } catch (action) {
    if (sessionCancelled(signal)) return null
    if (action === 'cancel') {
      clearDraftRecord(draft)
      requestAuthoritativeCollaborationReset()
    }
  } finally {
    localDraftDialogOpen = false
  }
  return null
}

function recordContentOperations(detailList) {
  if (isContentDetailTrackingSuspended()) return
  const currentCrossNodeState = extractCrossNodeState(mindMap.value?.getData?.(true))
  const nextOperations = [
    ...buildMindmapContentOperations(detailList, nodeRevisionMap),
    ...buildNodeTagContentOperations(detailList),
    ...buildCrossNodeContentOperations(
      crossNodeOperationSnapshot || currentCrossNodeState,
      currentCrossNodeState,
    ),
  ]
  for (const operation of nextOperations) {
    const prefix = operation.type?.split('.')[0]
    const domain = operation.type?.startsWith('node.tag.')
      ? (operation.type === 'node.tag.reorder' ? 'node.tag.order' : 'node.tag.binding')
      : prefix
    const key = operation.payload?.key
    if (key && [
      'relation', 'summary', 'group', 'asset', 'node.tag.binding', 'node.tag.order',
    ].includes(domain)) {
      const existingIndex = pendingContentOperations.findIndex(item => (
        (
          item.type?.startsWith('node.tag.')
            ? (item.type === 'node.tag.reorder' ? 'node.tag.order' : 'node.tag.binding')
            : item.type?.split('.')[0]
        ) === domain && item.payload?.key === key
      ))
      if (existingIndex >= 0) {
        pendingContentOperations.splice(existingIndex, 1, operation)
        continue
      }
    }
    pendingContentOperations.push(operation)
  }
  crossNodeOperationSnapshot = currentCrossNodeState
}

function onMindmapDataChangeDetail(detailList) {
  if (isContentDetailTrackingSuspended()) return
  const operationCountBefore = pendingContentOperations.length
  recordContentOperations(detailList)
  yjsSync?.onDataChangeDetail(detailList)
  // data_change 在远端渲染保护窗口内会被过滤；如果用户恰好在该窗口输入，
  // data_change_detail 仍需独立把真实本地操作放入保存队列并启动稳定期保存。
  if (pendingContentOperations.length > operationCountBefore) {
    scheduleLocalDraftPersist()
    resetSaveRetryForNewChange()
    clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
  }
}

// 文本编辑模式退出检测
// 设置文本编辑退出检测
function onHideTextEdit(...args) {
  const sourceMindMap = args.at(-1)
  if (!isCurrentMindmapEventSource(sourceMindMap, mindMap.value)) return
  // 强制终止会话时只需要把编辑框内容提交到本地模型，不能再向已经撤权、
  // 归档或删除的服务端文档发起保存；随后 terminateEditingSession 会生成恢复副本。
  if (terminatingSession || isChangeTrackingSuspended()) return
  // Enter/Tab 会先结束文本编辑，再执行节点插入命令。如果在 hide_text_edit
  // 阶段立即抓取文档，会把“文本已提交、节点尚未插入”的中间树与随后产生的
  // 操作日志拆成两个请求，快速连续录入时容易造成结构化树和操作批次不一致。
  // 重新开始稳定期防抖，让整个快捷键命令在同一个保存批次内完成。
  clearTimeout(autoSaveTimer)
  if (props.mindmapId && hasUnsavedChanges()) {
    autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
  }
}

function setupTextEditExitDetection() {
  // 直接监听 hide_text_edit 事件（simple-mind-map 在退出文本编辑时触发）
  // 覆盖所有退出方式：点击画布、按 Enter/Tab、切换节点、缩放等
  // 同时兼容普通文本模式和富文本模式
  //
  // 注意时序：hideEditTextBox() 内部先 execCommand('SET_NODE_TEXT') 触发 data_change，
  // 然后 emit hide_text_edit，Enter/Tab 处理器随后还会插入节点。这里必须等待完整
  // 快捷键命令结束，不能在 hide_text_edit 的中间状态立即保存。
  bus.on('hide_text_edit', onHideTextEdit)
}

function createYjsSyncInstance() {
  let documentPrepareFailureNotified = false
  const preferAuthoritativeDocument = authoritativeCollaborationResetRequired
  authoritativeCollaborationResetRequired = false
  return new YjsMindmapSync(props.mindmapId, mindMap.value, contentRevision, {
    preferAuthoritativeDocument,
    user: {
      id: userStore.id,
      name: userStore.nickName || userStore.name,
      avatar: userStore.avatar,
    },
    getDocumentData: () => normalizeMindmapDocumentData(documentData.value),
    // 协作更新可能首次引入富文本、公式等渲染能力。统一加载实际缺失的
    // 插件，避免当前客户端是否曾打开编辑器侧栏影响远端内容显示。
    prepareDocument: (document, targetMindMap) => (
      ensureMindmapDocumentPlugins(document, targetMindMap)
    ),
    onDocumentPrepareError: (error) => {
      console.error('协作内容渲染能力加载失败:', error)
      if (documentPrepareFailureNotified) return
      documentPrepareFailureNotified = true
      ElNotification.warning({
        title: '协作内容显示暂缓',
        message: '正在重试加载所需的渲染能力，当前修改不会丢失',
      })
    },
    onDocumentPrepareRecovered: () => {
      if (!documentPrepareFailureNotified) return
      documentPrepareFailureNotified = false
      ElMessage.success('协作内容渲染能力已恢复')
    },
    onDocumentPrepareExhausted: () => {
      ElNotification.error({
        title: '协作内容显示失败',
        message: '请检查网络后刷新页面；远端内容仍保存在协作文档中',
      })
    },
    onContentRevision: (revision) => {
      if (revision > contentRevision) contentRevision = revision
      // 远端协作者推进版本且本地没有待保存操作时，当前云端/Yjs 状态
      // 已经比任何遗留草稿更新。及时清理，避免刷新时误报冲突草稿。
      if (!hasUnsavedChanges()) clearLocalDraft()
    },
    onStaleState: (data) => {
      markAuthoritativeReloadRequired()
      void handleStaleCollaborationState(data)
    },
    onDocumentReset: (data) => {
      void handleRemoteDocumentReset(data)
    },
    onDocumentDeleted: (data) => {
      terminateEditingSession('document-deleted', data)
    },
    onDocumentArchived: (data) => {
      terminateEditingSession('document-archived', data)
    },
    onAccessRevoked: (data) => {
      terminateEditingSession('access-revoked', data)
    },
    onSessionEnded: (data) => {
      terminateEditingSession('session-ended', data)
    },
    onTagDefinitionChanged: (data) => {
      bus.emit('managed_tag_definition_changed', data)
    },
    onDocumentApplied: (root, meta) => {
      crossNodeOperationSnapshot = extractCrossNodeState(root)
      if (meta && Object.prototype.hasOwnProperty.call(meta, 'documentData')) {
        documentData.value = normalizeMindmapDocumentData(meta.documentData)
        applyMindmapDocumentConfig(mindMap.value, documentData.value)
      }
    },
  })
}

const isZenMode = computed(() => store.localConfig.isZenMode)
const activeSidebar = computed(() => store.activeSidebar)
const propertySidebarNames = new Set(['nodeStyle', 'baseStyle', 'structure', 'theme'])
const hasPropertyInspector = computed(() => propertySidebarNames.has(activeSidebar.value))
const hasSearchPanel = ref(false)
const openNodeRichText = computed(() => store.localConfig.openNodeRichText)
const isShowScrollbar = computed(() => store.localConfig.isShowScrollbar)
const useLeftKeySelectionRightKeyDrag = computed(() => store.localConfig.useLeftKeySelectionRightKeyDrag)

watch([activeSidebar, hasSearchPanel], async () => {
  await nextTick()
  mindMap.value?.resize?.()
})

// All events to forward from mindMap instance to bus
const forwardEvents = [
  'node_active',
  'data_change',
  'view_data_change',
  'back_forward',
  'node_contextmenu',
  'node_click',
  'node_tag_click',
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
  'enter_demonstrate',
  'demonstrate_enter_failed',
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
  componentMounted = true
  sessionController = new AbortController()
  actions.initLocalConfig()
  try {
    await initMindMap(sessionController.signal)
  } catch (error) {
    console.error('脑图编辑器初始化失败:', error)
    if (componentMounted) {
      emit('load-error', { message: '脑图编辑器初始化失败，请刷新页面后重试。' })
    }
    return
  }
  if (!componentMounted || !mindMap.value) return
  setupTextEditExitDetection()
  bindBusEvents()
  window.addEventListener('resize', handleResize)
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('pagehide', handlePageHide)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('online', handleNetworkOnline)
  window.addEventListener('offline', handleNetworkOffline)
  emit('ready')
})

onBeforeUnmount(() => {
  persistLocalDraftBeforeUnload()
  componentMounted = false
  cancelSessionAsyncWork()
  unbindBusEvents()
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('pagehide', handlePageHide)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('online', handleNetworkOnline)
  window.removeEventListener('offline', handleNetworkOffline)
  if (yjsSync) {
    yjsSync.destroy()
    yjsSync = null
    yjsSyncRef.value = null
  }
  clearTimeout(autoSaveTimer)
  clearTimeout(saveStatusTimer)
  clearTimeout(draftSaveTimer)
  clearTimeout(saveRetryTimer)
  documentMetaBuffer.clear()
  if (mindMap.value) {
    mindMap.value.destroy()
    mindMap.value = null
  }
  clearTimeout(storeConfigTimer)
  actions.resetState()
})

async function initMindMap(signal) {
  let root = defaultData
  let layout = 'logicalStructure'
  let themeTemplate = 'default'
  let themeConfig = {}
  let viewData = null
  const savedConfig = getMindmapLocalRuntimeConfig(actions.getConfig())
  let nodeCount = 0

  // 如果有 mindmapId，从后端加载
  if (props.mindmapId) {
    try {
      const response = await getMindmap(props.mindmapId, { signal })
      if (sessionCancelled(signal)) return
      const data = response.data
      root = data.nodeTree || defaultData
      layout = data.layout || 'logicalStructure'
      themeTemplate = data.theme?.template || 'default'
      themeConfig = data.theme?.config || {}
      viewData = data.viewData || null
      documentData.value = normalizeMindmapDocumentData(data.documentData)
      contentRevision = data.contentRevision || 1
      nodeCount = Number(data.nodeCount) || 0
      markDocumentMetaSaved({
        layout,
        theme: { template: themeTemplate, config: themeConfig },
        view: viewData,
        documentData: documentData.value,
      })
      for (const [nodeUid, revision] of Object.entries(data.nodeRevisions || {})) {
        nodeRevisionMap.set(nodeUid, revision)
      }
      serverCanEdit.value = data.canEdit === true
        && isMindmapContentWritable(data.contentState)
      actions.setCanManageCollaborators(data.isOwner === true)
      emit('access-change', {
        canEdit: serverCanEdit.value,
        isOwner: data.isOwner === true,
        permission: data.effectivePermission,
        accessType: data.accessType,
        contentState: data.contentState,
        contentStateMessage: data.contentStateMessage,
        status: data.status,
        description: data.description || '',
        nodeCount: data.nodeCount,
        versionCount: data.versionCount,
        updateTime: data.updateTime,
      })
      emit('name-change', data.name)
    } catch (error) {
      if (sessionCancelled(signal)) return
      const message = error?.response?.data?.msg || error?.message || '加载脑图失败'
      emit('load-error', { message })
      return
    }
  } else {
    // 回退到 localStorage
    const savedData = actions.getData()
    root = savedData?.root || defaultData
    layout = savedData?.layout || 'logicalStructure'
    themeTemplate = savedData?.theme?.template || 'default'
    themeConfig = savedData?.theme?.config || {}
    viewData = savedData?.view || null
    documentData.value = normalizeMindmapDocumentData(savedData?.documentData)
  }

  if (props.mindmapId && !isReadonly.value) {
    const localDraft = await resolveLocalDraft({
      root,
      layout,
      theme: { template: themeTemplate, config: themeConfig },
      view: viewData,
      documentData: documentData.value,
    }, signal)
    if (sessionCancelled(signal)) return
    if (localDraft) {
      root = localDraft.root || root
      layout = localDraft.layout || layout
      themeTemplate = localDraft.theme?.template || themeTemplate
      themeConfig = localDraft.theme?.config || themeConfig
      viewData = localDraft.view || viewData
      if (Object.prototype.hasOwnProperty.call(localDraft, 'documentData')) {
        documentData.value = normalizeMindmapDocumentData(localDraft.documentData)
      }
      restoredLocalDraft = true
    }
  }

  await ensureMindmapDocumentPlugins({
    root,
    layout,
    documentData: documentData.value,
  })
  if (sessionCancelled(signal)) return

  const container = await waitForMindMapContainer()
  if (sessionCancelled(signal)) return
  if (!container) {
    if (componentMounted) {
      emit('load-error', { message: '脑图画布初始化失败，请刷新页面后重试。' })
    }
    return
  }

  const performanceOptions = resolveMindmapPerformanceOptions({
    root,
    nodeCount,
    savedConfig,
  })
  const persistedDocumentConfig = getMindmapDocumentConfig(documentData.value)

  // savedConfig 放在最前面，后续显式配置覆盖它，防止 localStorage 污染覆盖关键选项
  let noteContentMindMap = null
  const mm = new MindMap({
    ...savedConfig,
    ...persistedDocumentConfig,
    el: container,
    data: root,
    fit: false,
    layout: layout,
    theme: themeTemplate,
    themeConfig: themeConfig,
    viewData: viewData,
    readonly: isReadonly.value,
    enableNodeAwareness: Boolean(props.mindmapId && !isReadonly.value),
    nodeTextEditZIndex: 1000,
    nodeNoteTooltipZIndex: 1000,
    customNoteContentShow: {
      show: (content, left, top, node) => {
        bus.emit('showNoteContent', content, left, top, node, noteContentMindMap)
      },
      hide: () => {
        bus.emit('scheduleHideNoteContent', noteContentMindMap)
      }
    },
    openPerformance: performanceOptions.openPerformance,
    openRealtimeRenderOnNodeTextEdit: performanceOptions.openRealtimeRenderOnNodeTextEdit,
    enableAutoEnterTextEditWhenKeydown: savedConfig.enableAutoEnterTextEditWhenKeydown !== false,
    demonstrateConfig: {
      openBlankMode: false
    },
    isLimitMindMapInCanvas: savedConfig.isLimitMindMapInCanvas !== false,
    useLeftKeySelectionRightKeyDrag: useLeftKeySelectionRightKeyDrag.value,
    customInnerElsAppendTo: null,
    initRootNodePosition: ['center', 'center'],
    customHandleMousewheel: (e) => {
      if (!mm) return
      const {
        mouseScaleCenterUseMousePosition,
        disableMouseWheelZoom,
        translateRatio = 1
      } = mm.opt || {}
      if (shouldZoomMindmapWheel(e, mm.opt)) {
        if (disableMouseWheelZoom) return
        const { x: cx, y: cy } = mm.toPos(e.clientX, e.clientY)
        const centerX = mouseScaleCenterUseMousePosition ? cx : undefined
        const centerY = mouseScaleCenterUseMousePosition ? cy : undefined
        const newScale = calculateMindmapWheelScale(mm.view.scale, e, mm.opt)
        if (newScale === null || newScale === mm.view.scale) return
        mm.view.setScale(newScale, centerX, centerY)
        return
      }
      // 双指/触控板平移阻尼：整体降速 + 大位移非线性衰减，快速滑动时阻尼更强
      // PAN_SENSITIVITY 控制整体速度（<1 降速）；PAN_NONLINEAR 控制非线性（<1 时大位移衰减更多）
      const PAN_SENSITIVITY = 0.92
      const PAN_NONLINEAR = 0.95
      const dampen = delta =>
        Math.sign(delta) *
        Math.pow(Math.abs(delta), PAN_NONLINEAR) *
        PAN_SENSITIVITY
      mm.view.translateXY(
        dampen(-e.deltaX * translateRatio),
        dampen(-e.deltaY * translateRatio)
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
  noteContentMindMap = mm

  mindMap.value = mm
  actions.setMindMap(mm)
  actions.setIsReadonly(isReadonly.value)
  applyMindmapDocumentConfig(mm, documentData.value)
  crossNodeOperationSnapshot = extractCrossNodeState(root)

  if (restoredLocalDraft) {
    pendingContentOperations.push({ type: 'document.update' })
    viewChangeVersion += 1
    setSaveStatus('pending')
    persistLocalDraft()
    autoSaveTimer = setTimeout(() => saveToBackend(), 1000)
  }

  // Yjs 实时协作（仅后端模式 + 非只读）
  if (props.mindmapId && !isReadonly.value) {
    yjsSync = createYjsSyncInstance()
    yjsSyncRef.value = yjsSync
    yjsSync.start()
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
      bus.emit(eventName, ...args, mm)
    })
  })

  // Bind save events (use named functions for proper cleanup)
  if (!isReadonly.value) {
    bus.on('data_change', onBusDataChange)
    bus.on('view_data_change', onBusViewDataChange)
    // Yjs 增量同步（带反馈循环保护）
    if (yjsSync) {
      dataChangeDetailHandler = onMindmapDataChangeDetail
      mm.on('data_change_detail', dataChangeDetailHandler)
    }

    // Ctrl+S manual save
    mm.keyCommand.addShortcut('Control+s', () => {
      manualSave()
    })
  }

  await waitForInitialMindmapRender(mm)
}

async function waitForMindMapContainer(maxAttempts = 8) {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (!componentMounted) return null
    await nextTick()
    const container = mindMapContainerRef.value
    if (container?.isConnected) {
      const { width, height } = container.getBoundingClientRect()
      if (width > 0 && height > 0) return container
    }
    await new Promise(resolve => requestAnimationFrame(resolve))
  }
  return null
}

function waitForInitialMindmapRender(instance, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    let settled = false
    const cleanup = () => {
      clearTimeout(timeoutId)
      instance.off('node_tree_render_end', onRenderEnd)
      instance.off('beforeDestroy', onBeforeDestroy)
    }
    const finish = (error) => {
      if (settled) return
      settled = true
      cleanup()
      if (error) reject(error)
      else resolve()
    }
    const onRenderEnd = () => finish()
    const onBeforeDestroy = () => finish(new Error('脑图实例已在首次渲染前销毁'))
    const timeoutId = setTimeout(() => {
      finish(new Error('脑图首次渲染超时'))
    }, timeoutMs)
    instance.on('node_tree_render_end', onRenderEnd)
    instance.on('beforeDestroy', onBeforeDestroy)
  })
}

// ── Save status tracking ──
function setSaveStatus(status) {
  saveStatus.value = status
  clearTimeout(saveStatusTimer)
  if (status === 'saved') {
    saveStatusTimer = setTimeout(() => { saveStatus.value = 'idle' }, 3000)
  }
}

function onBusDataChange(data, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, mindMap.value)) return
  if (props.mindmapId) {
    // 跳过远程变更或暂停状态（版本预览）引发的本地 data_change
    if (isChangeTrackingSuspended()) return
    const fullData = getCurrentDocument()
    yjsSync?.syncDocumentMeta(fullData)
    recordDocumentOperations(fullData)
    scheduleLocalDraftPersist()
    resetSaveRetryForNewChange()
    // 常规变更，使用防抖延迟
    // 如果是文本编辑退出，hide_text_edit 事件会紧随其后触发，
    // 取消此防抖计时器并立即保存（见 setupTextEditExitDetection）
    clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => {
      saveToBackend()
    }, AUTO_SAVE_DELAY)
  } else {
    persistLocalWorkspace({ root: data })
  }
}

function onBusViewDataChange(data, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, mindMap.value)) return
  if (isReadonly.value) return
  if (props.mindmapId) {
    // 跳过远程变更或暂停状态引发的本地视图变更
    if (isChangeTrackingSuspended()) return
    scheduleYjsMetaSync({ view: data })
    queueFileOperation('file.view.update')
    viewChangeVersion += 1
    scheduleLocalDraftPersist()
    resetSaveRetryForNewChange()
    // 后端模式：视图变更也触发保存（平移/缩放后 2 秒自动保存）
    clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => {
      saveToBackend()
    }, AUTO_SAVE_DELAY)
  } else {
    clearTimeout(storeConfigTimer)
    storeConfigTimer = setTimeout(() => {
      persistLocalWorkspace({ view: data })
    }, 300)
  }
}

function isBrowserOffline() {
  return typeof navigator !== 'undefined' && navigator.onLine === false
}

function isRetryableSaveError(error) {
  if (isBrowserOffline()) return true
  const status = Number(error?.response?.status || error?.status || error?.code)
  if (!Number.isInteger(status)) return true
  return status === 408 || status === 429 || status >= 500
}

function resetSaveRetryForNewChange() {
  clearTimeout(saveRetryTimer)
  saveRetryTimer = null
  saveRetryAttempt = 0
  if (saveRecoveryKind.value === 'retry') saveRecoveryKind.value = ''
}

function clearSaveRetryState() {
  clearTimeout(saveRetryTimer)
  saveRetryTimer = null
  saveRetryAttempt = 0
  retryNoticeShown = false
  saveRecoveryKind.value = ''
  blockedConflictData = null
}

function scheduleSaveRetry(error) {
  if (terminalState) return
  const draftPersist = persistLocalDraft()
  const announceProtectedDraft = (title, message, nextStatus) => {
    void draftPersist.then((result) => {
      if (result?.saved !== true || terminalState) return
      if (nextStatus && saveRecoveryKind.value !== 'draft') setSaveStatus(nextStatus)
      if (retryNoticeShown) return
      retryNoticeShown = true
      ElNotification.warning({ title, message })
    })
  }
  clearTimeout(saveRetryTimer)
  saveRetryTimer = null
  if (isBrowserOffline()) {
    saveRecoveryKind.value = ''
    setSaveStatus('pending')
    announceProtectedDraft(
      '当前处于离线状态',
      '修改已保存到本地草稿，恢复联网后会自动同步',
      'offline',
    )
    return
  }
  if (!isRetryableSaveError(error) || saveRetryAttempt >= SAVE_RETRY_DELAYS.length) {
    saveRecoveryKind.value = 'retry'
    setSaveStatus('error')
    if (saveRetryAttempt >= SAVE_RETRY_DELAYS.length) {
      announceProtectedDraft(
        '自动保存暂时停止',
        '修改已保存在本地草稿，请检查网络后点击保存或继续编辑以重试',
      )
    }
    return
  }

  const delay = SAVE_RETRY_DELAYS[saveRetryAttempt]
  saveRetryAttempt += 1
  saveRecoveryKind.value = ''
  setSaveStatus('retrying')
  announceProtectedDraft(
    '云端保存暂不可用',
    '修改已保存到本地草稿，系统会自动重试',
  )
  saveRetryTimer = setTimeout(() => {
    saveRetryTimer = null
    void saveToBackend()
  }, delay)
}

function handleNetworkOffline() {
  if (!hasUnsavedChanges()) return
  setSaveStatus('pending')
  void persistLocalDraft().then((result) => {
    if (result?.saved === true && saveRecoveryKind.value !== 'draft') {
      setSaveStatus('offline')
    }
  })
}

function handleNetworkOnline() {
  if (authoritativeReloadRequired && !hasUnsavedChanges()) {
    scheduleAuthoritativeReload()
    return
  }
  if (!hasUnsavedChanges() || isSaving.value || conflictBlocked || isChangeTrackingSuspended()) return
  clearTimeout(saveRetryTimer)
  saveRetryTimer = null
  setSaveStatus('retrying')
  void saveToBackend()
}

function markAuthoritativeReloadRequired() {
  if (!authoritativeReloadRequired) {
    authoritativeReloadAttempt = 0
    authoritativeReloadNoticeShown = false
  }
  authoritativeReloadRequired = true
}

function resolveAuthoritativeReload() {
  clearTimeout(authoritativeReloadTimer)
  authoritativeReloadTimer = null
  authoritativeReloadAttempt = 0
  authoritativeReloadInProgress = false
  authoritativeReloadNoticeShown = false
  authoritativeReloadRequired = false
  if (saveRecoveryKind.value === 'sync') saveRecoveryKind.value = ''
}

function scheduleNextAuthoritativeReload() {
  if (terminalState || !componentMounted || !authoritativeReloadRequired) return
  if (authoritativeReloadAttempt >= AUTHORITATIVE_RELOAD_RETRY_DELAYS.length) {
    saveRecoveryKind.value = 'sync'
    setSaveStatus('error')
    if (!authoritativeReloadNoticeShown) {
      authoritativeReloadNoticeShown = true
      ElNotification.warning({
        title: '云端已保存，画布同步暂时中断',
        message: '当前修改没有丢失，请检查网络后点击“同步画布”加载协作后的最新内容',
      })
    }
    return
  }
  const delay = AUTHORITATIVE_RELOAD_RETRY_DELAYS[authoritativeReloadAttempt]
  authoritativeReloadAttempt += 1
  scheduleAuthoritativeReload(delay)
}

function scheduleAuthoritativeReload(delay = 0) {
  if (terminalState || !componentMounted || !authoritativeReloadRequired) return
  clearTimeout(authoritativeReloadTimer)
  authoritativeReloadTimer = setTimeout(() => {
    authoritativeReloadTimer = null
    void performAuthoritativeReload()
  }, delay)
  if (saveRecoveryKind.value !== 'draft') {
    saveRecoveryKind.value = ''
    setSaveStatus('syncing')
  }
}

async function performAuthoritativeReload() {
  if (!authoritativeReloadRequired) return true
  if (
    terminalState
    || !componentMounted
    || authoritativeReloadInProgress
    || hasUnsavedChanges()
  ) return false

  authoritativeReloadInProgress = true
  if (saveRecoveryKind.value !== 'draft') setSaveStatus('syncing')
  try {
    const reloaded = await reloadLatestServerDocument({ requireClean: true })
    if (reloaded) {
      resolveAuthoritativeReload()
      ElMessage.success('已同步协作后的最新画布')
      return true
    }
    if (!terminalState && !hasUnsavedChanges()) scheduleNextAuthoritativeReload()
    return false
  } catch (error) {
    if (!sessionCancelled(sessionController?.signal)) {
      console.warn('同步协作后的最新画布失败:', error)
      scheduleNextAuthoritativeReload()
    }
    return false
  } finally {
    authoritativeReloadInProgress = false
  }
}

async function saveToBackend() {
  if (terminalState || !mindMap.value || !props.mindmapId || isReadonly.value) return
  if (isChangeTrackingSuspended()) return false
  // Manual save, route leave and text-edit exit can run before the normal
  // 120ms metadata debounce. Commit the compact Yjs metadata first so online
  // collaborators observe the same document version that is sent to HTTP.
  flushPendingYjsMetaSync()
  if (conflictBlocked) {
    saveRecoveryKind.value = 'conflict'
    setSaveStatus('error')
    return false
  }
  if (isBrowserOffline()) {
    scheduleSaveRetry()
    return false
  }

  if (isSaving.value) {
    pendingSave.value = true
    return
  }

  isSaving.value = true
  pendingSave.value = false
  setSaveStatus('saving')
  let shouldScheduleAuthoritativeReload = false

  try {
    const fullData = getCurrentDocument()
    const draftClearBeforeUpdatedAt = nextDraftUpdatedAt()
    if (!activeSaveMutation) {
      recordDocumentOperations(fullData)
      activeSaveMutation = createMindmapSaveMutation({
        clientMutationId: createMutationId(),
        baseRevision: contentRevision,
        operations: pendingContentOperations,
        document: fullData,
        viewChangeVersion,
      })
      if (activeSaveMutation) pendingContentOperations = []
    }
    let mutation = activeSaveMutation
    if (!mutation) {
      setSaveStatus('saved')
      return true
    }
    if (pendingContentOperations.length > 0) pendingSave.value = true
    const submission = await submitMindmapSaveMutation(
      mutation,
      payload => batchUpdateMindmapContent(props.mindmapId, payload),
      {
        onRebase: (rebasedMutation) => {
          activeSaveMutation = rebasedMutation
          setSaveStatus('syncing')
        },
      },
    )
    mutation = submission.mutation
    const response = submission.response
    if (sessionCancelled(sessionController?.signal) || !mindMap.value) return false
    assertMindmapSaveMutationResponse(mutation, response.data)
    if (activeSaveMutation?.clientMutationId !== mutation.clientMutationId) return false
    contentRevision = response.data.contentRevision
    documentData.value = normalizeMindmapDocumentData(
      response.data.documentData === undefined
        ? mutation.document.documentData
        : response.data.documentData
    )
    applyMindmapDocumentConfig(mindMap.value, documentData.value)
    yjsSync?.setContentRevision(contentRevision)
    if (response.data.nodeRevisions) {
      nodeRevisionMap.clear()
      for (const [nodeUid, revision] of Object.entries(response.data.nodeRevisions)) {
        nodeRevisionMap.set(nodeUid, revision)
      }
    } else {
      for (const node of (response.data.changedNodes || [])) {
        if (node.action === 'delete') nodeRevisionMap.delete(node.nodeUid)
        else nodeRevisionMap.set(node.nodeUid, node.nodeRevision)
      }
    }
    if (response.data.concurrentMerge && response.data.nodeTree) {
      const hasNewerLocalChanges = (
        pendingContentOperations.length > 0
        || viewChangeVersion > mutation.viewChangeVersion
      )
      if (hasNewerLocalChanges) {
        markAuthoritativeReloadRequired()
        ElNotification.info({
          title: '协作内容已在云端合并',
          message: '正在先保存当前后续修改，完成后会安全同步最新画布',
        })
      } else {
        const activeMindMap = mindMap.value
        const mergedDocument = {
          root: response.data.nodeTree,
          layout: response.data.layout || mutation.document.layout,
          theme: response.data.theme || mutation.document.theme,
          view: response.data.viewData ?? mutation.document.view,
          documentData: documentData.value,
        }
        try {
          await ensureMindmapDocumentPlugins(mergedDocument, activeMindMap)
          if (sessionCancelled(sessionController?.signal) || mindMap.value !== activeMindMap) return false
          applyingServerTree = true
          try {
            applyMindmapDocumentPreservingRuntimeState(
              activeMindMap,
              mergedDocument,
            )
            await nextTick()
          } finally {
            applyingServerTree = false
          }
        } catch (renderError) {
          // 服务端已经提交本批操作，渲染插件失败不能把同一批操作当成网络失败重试。
          // 保留当前画布草稿并阻止继续编辑旧基线，让用户通过既有冲突恢复流程
          // 下载副本后重新加载权威合并结果。
          activeSaveMutation = null
          savedViewChangeVersion = Math.max(savedViewChangeVersion, mutation.viewChangeVersion)
          markDocumentMetaSaved({
            layout: response.data.layout,
            theme: response.data.theme,
            view: response.data.viewData,
            documentData: documentData.value,
          })
          clearTimeout(saveRetryTimer)
          saveRetryTimer = null
          saveRetryAttempt = 0
          retryNoticeShown = false
          conflictBlocked = true
          blockedConflictData = { currentRevision: contentRevision }
          saveRecoveryKind.value = 'conflict'
          setSaveStatus('error')
          void persistLocalDraft()
          console.error('协作合并结果渲染失败:', renderError)
          ElNotification.error({
            title: '云端已保存，但画布刷新失败',
            message: '请点击“处理冲突”，系统会先备份当前画布，再加载云端合并结果',
          })
          return false
        }
        onYjsReinit(response.data.nodeTree)
        crossNodeOperationSnapshot = extractCrossNodeState(response.data.nodeTree)
        resolveAuthoritativeReload()
        ElNotification.success({
          title: '协作内容已合并',
          message: '已自动合并其他协作者在不同节点上的修改'
        })
      }
    }
    if (yjsSync?.requiresAuthoritativeReconciliation?.()) {
      markAuthoritativeReloadRequired()
    }
    markDocumentMetaSaved(response.data.concurrentMerge ? {
      layout: response.data.layout,
      theme: response.data.theme,
      view: response.data.viewData,
      documentData: documentData.value,
    } : mutation.document)
    savedViewChangeVersion = Math.max(savedViewChangeVersion, mutation.viewChangeVersion)
    activeSaveMutation = null
    conflictBlocked = false
    const recoveredFromRetry = retryNoticeShown || saveRetryAttempt > 0
    clearSaveRetryState()
    if (
      pendingContentOperations.length === 0
      && viewChangeVersion === savedViewChangeVersion
    ) {
      clearLocalDraft(draftClearBeforeUpdatedAt)
      clearRestoredDraft()
      draftProtection.markClean()
    }
    if (
      authoritativeReloadRequired
      && pendingContentOperations.length === 0
      && viewChangeVersion === savedViewChangeVersion
    ) shouldScheduleAuthoritativeReload = true
    setSaveStatus('saved')
    if (recoveredFromRetry) ElMessage.success('网络已恢复，修改已保存到云端')
    return true
  } catch (error) {
    if (terminalState) return false
    console.error('自动保存失败:', error)
    if (error?.data?.currentRevision) {
      conflictBlocked = true
      blockedConflictData = error.data
      saveRecoveryKind.value = 'conflict'
      await resolveContentConflict(getCurrentDocument(), blockedConflictData)
      if (conflictBlocked) {
        setSaveStatus('error')
      }
      return null
    }
    scheduleSaveRetry(error)
    return false
  } finally {
    isSaving.value = false
    if (terminalState) {
      pendingSave.value = false
    } else if (pendingSave.value || pendingContentOperations.length > 0) {
      pendingSave.value = false
      clearTimeout(saveRetryTimer)
      saveRetryTimer = null
      clearTimeout(autoSaveTimer)
      autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
    } else if (shouldScheduleAuthoritativeReload) {
      scheduleAuthoritativeReload()
    }
  }
}

async function handleStaleCollaborationState() {
  if (resolvingStaleState || !mindMap.value || isReadonly.value) return
  resolvingStaleState = true
  try {
    if (isSaving.value) {
      pendingSave.value = true
      for (let attempt = 0; attempt < 100 && isSaving.value; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 50))
      }
      if (!componentMounted || yjsSyncRef.value?.connectionState.value !== 'stale') return
    }

    if (hasUnsavedChanges()) {
      clearTimeout(autoSaveTimer)
      const saved = await saveToBackend()
      if (!saved || hasUnsavedChanges()) return
    }
    const reloaded = authoritativeReloadRequired
      ? await performAuthoritativeReload()
      : await reloadLatestServerDocument()
    if (!reloaded) return
    ElMessage.info('已同步服务器最新内容')
  } catch (error) {
    if (sessionCancelled(sessionController?.signal)) return
    console.error('恢复协作状态失败:', error)
    setSaveStatus('error')
  } finally {
    resolvingStaleState = false
  }
}

async function handleRemoteDocumentReset() {
  if (resolvingStaleState || !mindMap.value || isReadonly.value) return
  resolvingStaleState = true
  try {
    let preserveLocalDraft = false
    if (hasUnsavedChanges()) {
      const fullData = getCurrentDocument()
      const fallbackSaved = saveMindmapDraftFallbackSync(createDraftOptions(fullData))
      const downloaded = downloadConflictBackup(
        fullData,
        'mindmap-before-remote-restore',
      )
      preserveLocalDraft = !downloaded && fallbackSaved
      if (!downloaded && !fallbackSaved) {
        throw new Error('未能创建本地安全副本，已暂停加载协作者恢复的版本')
      }
      ElNotification.warning({
        title: '协作者恢复了历史版本',
        message: downloaded
          ? '当前未保存内容已下载为本地副本，正在加载恢复后的版本'
          : '自动下载未能启动，本地草稿仍保留，可在脑图列表的草稿中心下载',
      })
    }
    const reloaded = await reloadLatestServerDocument({ preserveLocalDraft })
    if (!reloaded) return
    ElMessage.success('已切换到协作者恢复的版本')
  } catch (error) {
    if (sessionCancelled(sessionController?.signal)) return
    console.error('加载协作者恢复版本失败:', error)
    setSaveStatus('error')
  } finally {
    resolvingStaleState = false
  }
}

function terminateEditingSession(eventName, data) {
  if (terminalState || terminatingSession) return
  terminatingSession = true
  commitActiveEditorsBeforeTermination()
  const needsLocalBackup = hasUnsavedChanges() && Boolean(mindMap.value)
  let localBackupCreated = false
  let localDraftPreserved = false
  let terminalDraftOptions = null
  if (needsLocalBackup) {
    const fullData = getCurrentDocument()
    terminalDraftOptions = createDraftOptions(fullData)
    localDraftPreserved = saveMindmapDraftFallbackSync(terminalDraftOptions)
    localBackupCreated = downloadConflictBackup(fullData, `mindmap-${eventName}`)
  }
  terminalState = eventName
  cancelSessionAsyncWork()
  serverCanEdit.value = false
  actions.setIsReadonly(true)
  actions.setActiveSidebar(null)
  mindMap.value?.setMode?.('readonly')
  versionChangeTrackingPaused = true
  clearTimeout(autoSaveTimer)
  clearTimeout(draftSaveTimer)
  clearTimeout(saveRetryTimer)
  documentMetaBuffer.clear()
  saveRecoveryKind.value = ''
  blockedConflictData = null
  pendingContentOperations = []
  activeSaveMutation = null
  resolveAuthoritativeReload()
  savedViewChangeVersion = viewChangeVersion
  isSaving.value = false
  pendingSave.value = false
  setSaveStatus('error')
  yjsSync = null
  yjsSyncRef.value = null
  const emitTerminalEvent = (draftPreserved) => emit(eventName, {
    ...data,
    localBackupCreated,
    localDraftPreserved: draftPreserved,
  })
  if (!terminalDraftOptions) {
    emitTerminalEvent(false)
    return
  }
  // 同步 localStorage 只承载小文档；继续等待 IndexedDB，确保大草稿也有持久副本。
  void enqueueDraftOperation(() => saveMindmapDraft(terminalDraftOptions)).then((result) => {
    emitTerminalEvent(localDraftPreserved || result?.saved === true)
  })
}

function commitActiveEditorsBeforeTermination() {
  // 大纲编辑使用 DOM blur 提交标题，必须先于核心命令总线切换只读。
  bus.emit('closeOutlineEdit')
  const activeEditors = [
    mindMap.value?.renderer?.textEdit,
    mindMap.value?.associativeLine,
    mindMap.value?.outerFrame,
  ]
  for (const editor of activeEditors) {
    try {
      editor?.hideEditTextBox?.()
    } catch (error) {
      // 单个插件编辑器异常不应阻断终止流程和其余内容的本地备份。
      console.warn('提交脑图活动编辑器失败:', error)
    }
  }
}

async function reloadLatestServerDocument({ preserveLocalDraft = false, requireClean = false } = {}) {
  const signal = sessionController?.signal
  const cleanViewChangeVersion = viewChangeVersion
  if (requireClean && hasUnsavedChanges()) return false
  const response = await getMindmap(props.mindmapId, {
    signal,
    // 自动补拉由本组件聚合为一次可恢复状态，避免每轮后台重试都弹全局错误。
    silentError: requireClean,
  })
  if (sessionCancelled(signal) || !mindMap.value) return false
  const data = response.data
  const nextDocumentData = normalizeMindmapDocumentData(data.documentData)
  const activeMindMap = mindMap.value
  const serverDocument = {
    root: data.nodeTree || defaultData,
    layout: data.layout || 'logicalStructure',
    theme: data.theme || {},
    view: data.viewData || null,
    documentData: nextDocumentData,
  }
  await ensureMindmapDocumentPlugins(serverDocument, activeMindMap)
  if (sessionCancelled(signal) || mindMap.value !== activeMindMap) return false
  if (
    requireClean
    && (
      hasUnsavedChanges()
      || viewChangeVersion !== cleanViewChangeVersion
    )
  ) return false
  applyingServerTree = true
  try {
    applyMindmapDocumentPreservingRuntimeState(activeMindMap, serverDocument)
    await nextTick()
  } finally {
    applyingServerTree = false
  }
  if (sessionCancelled(signal) || !mindMap.value) return false
  documentData.value = nextDocumentData
  applyMindmapDocumentConfig(mindMap.value, documentData.value)
  contentRevision = data.contentRevision || contentRevision
  nodeRevisionMap.clear()
  for (const [nodeUid, revision] of Object.entries(data.nodeRevisions || {})) {
    nodeRevisionMap.set(nodeUid, revision)
  }
  pendingContentOperations = []
  activeSaveMutation = null
  resolveAuthoritativeReload()
  crossNodeOperationSnapshot = extractCrossNodeState(data.nodeTree || defaultData)
  markDocumentMetaSaved({
    layout: data.layout,
    theme: data.theme,
    view: data.viewData,
    documentData: documentData.value,
  })
  savedViewChangeVersion = viewChangeVersion
  conflictBlocked = false
  clearSaveRetryState()
  if (!preserveLocalDraft) {
    clearLocalDraft()
    clearRestoredDraft()
  }
  onYjsReinit(data.nodeTree || defaultData, contentRevision)
  setSaveStatus('saved')
  return true
}

function downloadConflictBackup(fullData, prefix = 'mindmap-conflict') {
  return downloadMindmapBackup(fullData, {
    prefix,
    mindmapId: props.mindmapId,
  })
}

async function resolveContentConflict(localFullData, conflictData) {
  if (conflictResolutionPromise) return conflictResolutionPromise
  const operation = performContentConflictResolution(localFullData, conflictData)
  conflictResolutionPromise = operation
  try {
    return await operation
  } finally {
    if (conflictResolutionPromise === operation) conflictResolutionPromise = null
  }
}

async function performContentConflictResolution(localFullData, conflictData) {
  const nodeConflictCount = (conflictData.conflictNodeUids || conflictData.conflictNodes || []).length
  const entityConflictCount = (conflictData.conflictEntities || []).length
  const conflictCount = nodeConflictCount + entityConflictCount
  const conflictSummary = [
    nodeConflictCount ? `${nodeConflictCount} 个节点` : '',
    entityConflictCount ? `${entityConflictCount} 个关联对象` : '',
  ].filter(Boolean).join('、')
  const signal = sessionController?.signal
  try {
    conflictDialogOpen = true
    await ElMessageBox.confirm(
      `检测到${conflictCount ? ` ${conflictSummary}` : ''}无法自动合并。重新加载前会下载本地 JSON 副本，避免修改丢失。`,
      '需要处理协作冲突',
      {
        type: 'warning',
        confirmButtonText: '备份并重新加载',
        cancelButtonText: '暂不处理',
        closeOnClickModal: false
      }
    )
  } catch (error) {
    if (sessionCancelled(signal)) return false
    if (error === 'cancel' || error === 'close') {
      ElNotification.warning({
        title: '自动保存已暂停',
        message: '本地修改仍受草稿保护，可稍后点击“处理冲突”继续，系统不会覆盖服务器内容'
      })
    } else {
      ElMessage.error(error?.message || '无法打开冲突处理窗口')
    }
    return false
  } finally {
    conflictDialogOpen = false
  }
  if (sessionCancelled(signal)) return false

  try {
    if (!downloadConflictBackup(localFullData)) {
      throw new Error('浏览器未能下载冲突副本，本地草稿仍已保留，请稍后从草稿中心下载')
    }
    const response = await getMindmap(props.mindmapId, { signal })
    if (sessionCancelled(signal) || !mindMap.value) return false
    const data = response.data
    const nextDocumentData = normalizeMindmapDocumentData(data.documentData)
    const activeMindMap = mindMap.value
    const serverDocument = {
      root: data.nodeTree || defaultData,
      layout: data.layout || 'logicalStructure',
      theme: data.theme || {},
      view: data.viewData || null,
      documentData: nextDocumentData,
    }
    await ensureMindmapDocumentPlugins(serverDocument, activeMindMap)
    if (sessionCancelled(signal) || mindMap.value !== activeMindMap) return false
    applyingServerTree = true
    try {
      activeMindMap.setFullData(serverDocument)
      await nextTick()
    } finally {
      applyingServerTree = false
    }
    if (sessionCancelled(signal) || !mindMap.value) return false
    documentData.value = nextDocumentData
    applyMindmapDocumentConfig(mindMap.value, documentData.value)
    contentRevision = data.contentRevision || conflictData.currentRevision
    nodeRevisionMap.clear()
    for (const [nodeUid, revision] of Object.entries(data.nodeRevisions || {})) {
      nodeRevisionMap.set(nodeUid, revision)
    }
    pendingContentOperations = []
    activeSaveMutation = null
    resolveAuthoritativeReload()
    crossNodeOperationSnapshot = extractCrossNodeState(data.nodeTree || defaultData)
    markDocumentMetaSaved({
      layout: data.layout,
      theme: data.theme,
      view: data.viewData,
      documentData: documentData.value,
    })
    savedViewChangeVersion = viewChangeVersion
    conflictBlocked = false
    clearSaveRetryState()
    clearLocalDraft()
    clearRestoredDraft()
    requestAuthoritativeCollaborationReset()
    onYjsReinit(data.nodeTree || defaultData)
    setSaveStatus('saved')
    ElMessage.success('已加载服务器最新内容，本地冲突副本已下载')
    return true
  } catch (error) {
    if (sessionCancelled(signal)) return false
    ElMessage.error(error?.message || '重新加载失败')
    return false
  }
}

async function manualSave() {
  if (isReadonly.value) return false
  if (!mindMap.value) return
  if (props.mindmapId) {
    if (conflictBlocked) {
      if (!blockedConflictData) {
        saveRecoveryKind.value = 'conflict'
        setSaveStatus('error')
        ElMessage.error('冲突上下文已失效，请先导出当前内容后刷新页面')
        return false
      }
      return resolveContentConflict(getCurrentDocument(), blockedConflictData)
    }
    clearTimeout(autoSaveTimer)
    resetSaveRetryForNewChange()
    const ok = await saveToBackend()
    if (ok === true) {
      ElMessage.success('已保存到服务器')
    } else if (ok === false) {
      if (['offline', 'retrying'].includes(saveStatus.value)) {
        ElMessage.warning('云端暂不可用，系统正在保护本地修改')
      } else {
        ElMessage.error('保存失败，请检查网络')
      }
    }
  } else {
    const fullData = getCurrentDocument()
    if (persistLocalWorkspace(fullData)) ElMessage.success('已保存')
  }
}

async function recoverSave() {
  if (saveRecoveryKind.value === 'sync') {
    if (hasUnsavedChanges()) return manualSave()
    authoritativeReloadAttempt = 0
    authoritativeReloadNoticeShown = false
    saveRecoveryKind.value = ''
    return performAuthoritativeReload()
  }
  if (saveRecoveryKind.value !== 'draft') return manualSave()
  const result = await persistLocalDraft({ notifyFailure: false })
  if (result?.saved === true) {
    if (isBrowserOffline()) {
      ElMessage.success('本地草稿已安全保存，恢复联网后会自动同步')
      return true
    }
    const cloudSaved = await saveToBackend()
    if (cloudSaved === true) {
      ElMessage.success('本地草稿与云端均已保存')
    } else {
      ElMessage.warning('本地草稿已安全保存，云端同步仍在重试')
    }
    return true
  }
  const downloaded = downloadConflictBackup(
    getCurrentDocument(),
    'mindmap-local-storage-failed',
  )
  if (downloaded) {
    ElNotification.warning({
      title: '已下载 JSON 备份',
      message: '浏览器本地存储仍不可用，请确认下载文件完整并暂时保持页面开启',
    })
    return true
  }
  ElMessage.error('本地草稿和自动下载均失败，请保持页面开启并手动复制重要内容')
  return false
}

function hasUnsavedChanges() {
  return !terminalState && (
    isSaving.value
    || Boolean(activeSaveMutation)
    || documentMetaBuffer.hasPending()
    || pendingContentOperations.length > 0
    || viewChangeVersion !== savedViewChangeVersion
  )
}

function handleBeforeUnload(event) {
  if (!isReadonly.value && hasUnsavedChanges()) {
    persistLocalDraftBeforeUnload()
    event.preventDefault()
    event.returnValue = ''
  }
}

async function flushBeforeLeave() {
  if (terminalState || isReadonly.value || !props.mindmapId || !hasUnsavedChanges()) return true
  clearTimeout(autoSaveTimer)
  clearTimeout(saveRetryTimer)
  saveRetryTimer = null
  return flushPendingMindmapChanges({
    hasUnsavedChanges,
    isSaveInProgress: () => isSaving.value,
    markPendingSave: () => { pendingSave.value = true },
    requestSave: async () => {
      clearTimeout(autoSaveTimer)
      return saveToBackend()
    },
    persistLocalBackup: persistLocalDraftBeforeUnload,
  })
}

async function prepareForCloudExit() {
  if (terminalState || isReadonly.value || !props.mindmapId) return true

  for (let pass = 0; pass < CLOUD_EXIT_MAX_PASSES; pass += 1) {
    // 文本、关联线等浮层编辑器只有在关闭时才会把最终值提交到脑图模型，
    // 必须先提交，再判断是否存在需要上传的修改。
    commitActiveEditorsBeforeTermination()
    await nextTick()

    if (await flushBeforeLeave() !== true) return false

    clearTimeout(draftSaveTimer)
    const clearBeforeUpdatedAt = nextDraftUpdatedAt()
    await draftWriteQueue

    // 用户可能在离开守卫等待网络或 IndexedDB 时继续编辑。新修改必须再次
    // 保存到云端，不能被本轮缓存清理当成已经提交的数据。
    if (hasUnsavedChanges()) continue

    const restoredDraftToClear = restoredDraftRecord
    await removeMindmapDraft(userStore.id, props.mindmapId, {
      beforeUpdatedAt: clearBeforeUpdatedAt,
      sessionId: draftSessionId,
    })
    if (restoredDraftToClear?.key) {
      await removeMindmapDraft(userStore.id, props.mindmapId, {
        key: restoredDraftToClear.key,
        beforeUpdatedAt: restoredDraftToClear.updatedAt,
      })
    }
    if (hasUnsavedChanges()) continue

    if (restoredDraftRecord === restoredDraftToClear) restoredDraftRecord = null
    draftProtection.markClean()
    return true
  }

  persistLocalDraftBeforeUnload()
  return false
}

function onExecCommand(...args) {
  mindMap.value?.execCommand(...args)
}

async function onExportRequest(request = {}) {
  const activeMindMap = mindMap.value
  const signal = sessionController?.signal
  let previousConfig = null
  let runtimeConfigApplied = false
  try {
    if (!activeMindMap || sessionCancelled(signal)) throw new Error('脑图实例尚未就绪')
    const { type, name, args = [], config, resolve } = request
    if (!type || typeof resolve !== 'function') throw new Error('导出请求无效')
    await ensureExportPlugins(activeMindMap, type)
    if (sessionCancelled(signal) || activeMindMap !== mindMap.value) {
      throw new Error('脑图会话已经变化，请重新导出')
    }
    const runtimeConfig = normalizeMindmapExportRuntimeConfig(config)
    previousConfig = {
      exportPaddingX: activeMindMap.getConfig('exportPaddingX'),
      exportPaddingY: activeMindMap.getConfig('exportPaddingY'),
      addContentToFooter: activeMindMap.getConfig('addContentToFooter'),
    }
    activeMindMap.updateConfig(runtimeConfig)
    runtimeConfigApplied = true
    const result = await activeMindMap.export(type, true, name, ...args)
    if (!result) throw new Error('导出组件未生成文件')
    if (sessionCancelled(signal) || activeMindMap !== mindMap.value) {
      throw new Error('脑图会话已经变化，导出结果已丢弃')
    }
    resolve(result)
  } catch (error) {
    console.error('导出失败:', error)
    request.reject?.(error)
  } finally {
    if (
      runtimeConfigApplied
      && previousConfig
      && !sessionCancelled(signal)
      && activeMindMap === mindMap.value
    ) {
      activeMindMap.updateConfig(previousConfig)
    }
  }
}

async function onSetData(data, request = {}) {
  const activeMindMap = mindMap.value
  try {
    if (!activeMindMap) throw new Error('脑图实例尚未就绪')
    if (isReadonly.value) throw new Error('只读脑图不能导入内容')
    assertMindmapImportDocument(data)
    const document = data.root
      ? data
      : { root: data, layout: activeMindMap.getLayout?.() }
    await ensureMindmapDocumentPlugins(document, activeMindMap)
    if (activeMindMap !== mindMap.value || isReadonly.value) {
      throw new Error('脑图会话已经变化，请重新导入')
    }

    let rootNodeData = null
    if (data.root) {
      const nextDocumentData = Object.prototype.hasOwnProperty.call(data, 'documentData')
        ? normalizeMindmapDocumentData(data.documentData)
        : documentData.value
      activeMindMap.setFullData(data)
      documentData.value = nextDocumentData
      applyMindmapDocumentConfig(activeMindMap, documentData.value)
      rootNodeData = data.root
    } else {
      activeMindMap.setData(data)
      rootNodeData = data
    }
    activeMindMap.view.reset()
    manualSave()
    // If imported content is rich text, auto-enable rich text mode
    if (rootNodeData?.data?.richText && !openNodeRichText.value) {
      bus.emit('toggleOpenNodeRichText', true)
      ElNotification.info({
        title: '提示',
        message: '检测到导入了富文本内容，已自动开启富文本模式'
      })
    }
    request.resolve?.(true)
  } catch (error) {
    request.reject?.(error)
    if (!request.reject) {
      console.error('应用导入的脑图数据失败:', error)
      ElMessage.error(error?.message || '导入内容应用失败')
    }
  }
}

function onStartTextEdit() {
  if (isReadonly.value) return
  mindMap.value?.renderer?.startTextEdit?.()
}

function onEndTextEdit() {
  mindMap.value?.renderer?.endTextEdit?.()
}

function onCreateAssociativeLine() {
  if (isReadonly.value) return
  mindMap.value?.associativeLine?.createLineFromActiveNode()
}

function onStartPainter() {
  if (isReadonly.value) return
  mindMap.value?.painter?.startPainter()
}

function handleResize() {
  mindMap.value?.resize()
}

// --- Drag and drop import ---

function onDragenter() {
  if (isReadonly.value) return
  showDragMask.value = true
}

function onDragleave() {
  showDragMask.value = false
}

function onDrop(e) {
  showDragMask.value = false
  if (isReadonly.value) return
  const dt = e.dataTransfer
  const file = dt?.files?.[0]
  if (!file) return
  bus.emit('importFile', file)
}

// --- Bus event binding ---

function onToggleOpenNodeRichText(val) {
  actions.setLocalConfig({ openNodeRichText: !!val })
}

function onSearchPanelVisibilityChange(visible) {
  hasSearchPanel.value = visible === true
}

function onOpenSidebar(sidebarName) {
  if (
    !sidebarName
    || (isReadonly.value && !isMindmapSidebarReadonlySafe(sidebarName))
  ) return
  actions.setActiveSidebar(sidebarName)
  nextTick(() => bus.emit('focusActiveSidebar'))
}

function onNodeTagClick(node, _tag, _index, _element, sourceMindMap) {
  const activeMindMap = mindMap.value
  if (
    isReadonly.value
    || !activeMindMap
    || !node
    || sourceMindMap !== activeMindMap
    || (node.mindMap && node.mindMap !== activeMindMap)
  ) return
  onOpenSidebar('nodeTagSidebar')
}

function bindBusEvents() {
  bus.on('execCommand', onExecCommand)
  bus.on('exportRequest', onExportRequest)
  bus.on('setData', onSetData)
  bus.on('startTextEdit', onStartTextEdit)
  bus.on('endTextEdit', onEndTextEdit)
  bus.on('createAssociativeLine', onCreateAssociativeLine)
  bus.on('startPainter', onStartPainter)
  bus.on('openSidebar', onOpenSidebar)
  bus.on('node_tag_click', onNodeTagClick)
  bus.on('searchPanelVisibilityChange', onSearchPanelVisibilityChange)
  bus.on('toggleOpenNodeRichText', onToggleOpenNodeRichText)
}

function unbindBusEvents() {
  bus.off('execCommand', onExecCommand)
  bus.off('exportRequest', onExportRequest)
  bus.off('setData', onSetData)
  bus.off('startTextEdit', onStartTextEdit)
  bus.off('endTextEdit', onEndTextEdit)
  bus.off('createAssociativeLine', onCreateAssociativeLine)
  bus.off('startPainter', onStartPainter)
  bus.off('openSidebar', onOpenSidebar)
  bus.off('node_tag_click', onNodeTagClick)
  bus.off('searchPanelVisibilityChange', onSearchPanelVisibilityChange)
  bus.off('data_change', onBusDataChange)
  bus.off('view_data_change', onBusViewDataChange)
  bus.off('toggleOpenNodeRichText', onToggleOpenNodeRichText)
  bus.off('hide_text_edit', onHideTextEdit)
}

/**
 * Yjs 重新初始化（版本恢复时由 VersionHistory 触发）
 * 销毁旧的 Yjs 连接，用恢复后的数据创建新的同步实例
 */
function onYjsReinit(_restoredRoot, revision) {
  if (!props.mindmapId || isReadonly.value) return
  if (Number.isInteger(revision) && revision > 0) contentRevision = revision
  // 销毁旧的 Yjs 同步
  if (yjsSync) {
    yjsSync.destroy()
    yjsSync = null
    yjsSyncRef.value = null
  }
  // 移除旧的 data_change_detail 监听器（使用具名引用）
  if (dataChangeDetailHandler) {
    mindMap.value?.off('data_change_detail', dataChangeDetailHandler)
    dataChangeDetailHandler = null
  }
  // 组件可能正在卸载，检查 mindMap 是否仍可用
  if (!mindMap.value) return
  // 创建新的 Yjs 同步，使用恢复后的数据
  yjsSync = createYjsSyncInstance()
  yjsSyncRef.value = yjsSync
  yjsSync.start()
  // 重新绑定 data_change_detail 事件（具名引用）
  dataChangeDetailHandler = onMindmapDataChangeDetail
  mindMap.value.on('data_change_detail', dataChangeDetailHandler)
}

function isContentDetailTrackingSuspended() {
  return Boolean(terminalState)
    || applyingServerTree
    || versionChangeTrackingPaused
    || Boolean(yjsSync && (
      yjsSync.isPaused()
      || yjsSync.isMutatingMindmapFromRemote?.()
    ))
}

function isChangeTrackingSuspended() {
  return Boolean(terminalState)
    || applyingServerTree
    || versionChangeTrackingPaused
    || Boolean(yjsSync && (yjsSync.isApplyingRemote() || yjsSync.isPaused()))
}

function focusNodeByUid(nodeUid) {
  const normalizedUid = typeof nodeUid === 'string' ? nodeUid.trim() : ''
  if (!normalizedUid || normalizedUid.length > 64 || !mindMap.value) return false
  const targetNode = mindMap.value.renderer?.findNodeByUid?.(normalizedUid)
  if (!targetNode) return false
  mindMap.value.execCommand?.('GO_TARGET_NODE', normalizedUid)
  return true
}

function onVersionChangeTracking(paused) {
  versionChangeTrackingPaused = Boolean(paused)
  if (versionChangeTrackingPaused) clearTimeout(autoSaveTimer)
}

defineExpose({
  mindMap,
  getMindMap: () => mindMap.value,
  getYjsSync: () => yjsSync,
  getCollaborators: () => yjsSyncRef.value?.collaborators.value || [],
  getCollaborationState: () => yjsSyncRef.value?.connectionState.value || 'connecting',
  getCollaborationError: () => yjsSyncRef.value?.syncError.value || '',
  isCollaborationSynced: () => yjsSyncRef.value?.isSynced.value === true,
  retryCollaboration: () => yjsSyncRef.value?.retryConnection?.() === true,
  isLocalDraftProtected: () => draftProtection.isProtected(),
  getLocalDraftProtectionState: () => draftProtection.getState(),
  hasUnsavedChanges,
  flushBeforeLeave,
  prepareForCloudExit,
  manualSave,
  saveStatus,
  saveRecoveryKind,
  recoverSave,
  focusNodeByUid,
})
</script>

<style lang="scss" scoped>
.editContainer {
  --mindmap-inspector-width: var(--mindmap-side-panel-width, 300px);
  --mindmap-inspector-compact-width: 300px;
  position: relative;
  flex: 1;
  overflow: hidden;

  .mindMapContainer {
    position: absolute;
    top: var(--mindmap-canvas-gap, 8px);
    right: calc(var(--mindmap-workspace-right, var(--mindmap-activity-width, 44px)) + var(--mindmap-canvas-gap, 8px));
    bottom: calc(var(--mindmap-workspace-bottom, 30px) + var(--mindmap-canvas-gap, 8px));
    left: calc(var(--mindmap-workspace-left, var(--mindmap-activity-width, 44px)) + var(--mindmap-canvas-gap, 8px));
    width: auto;
    height: auto;
    overflow: hidden;
    background: #fff;
    border-radius: 10px;
    box-shadow: 0 0 0 1px rgba(31, 35, 41, 0.06), 0 2px 8px rgba(31, 35, 41, 0.025);
    transition: left 0.2s ease, right 0.2s ease;
  }

  &.isDark .mindMapContainer {
    background: #25282d;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.08), 0 2px 10px rgba(0, 0, 0, 0.14);
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

@media (max-width: 760px) {
  .editContainer .mindMapContainer {
    border-radius: 8px;
  }
}
</style>
