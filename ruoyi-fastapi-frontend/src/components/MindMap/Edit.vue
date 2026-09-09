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
      @transitionend="onMindMapContainerTransitionEnd"
    ></div>
    <WorkspaceActivityBar v-if="!isZenMode" />
    <Navigator v-if="mindMap" :mindMap="mindMap" />
    <OutlineSidebar v-if="mindMap && activeSidebar === 'outline'" :mindMap="mindMap" />
    <AssociativeLineStyle v-if="mindMap" :mindMap="mindMap" />
    <PropertyInspector
      v-if="mindMap && hasPropertyInspector"
      :mindMap="mindMap"
      :structure-write-blocked="structureWriteBlocked"
      @document-meta-change="onDocumentMetaChange"
    />
    <ShortcutKey v-if="mindMap && activeSidebar === 'shortcutKey'" />
    <Contextmenu v-if="mindMap" :mindMap="mindMap" />
    <NodeTagSidebar
      v-if="mindMap && activeSidebar === 'nodeTagSidebar'"
      :mindMap="mindMap"
    />
    <CommentSidebar v-if="mindMap && props.mindmapId" :mindMap="mindMap" :mindmapId="props.mindmapId" />
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
    <OutlineEdit ref="outlineEditRef" v-if="mindMap" :mindMap="mindMap" />
    <!-- 历史预览会暂停当前 Yjs 实例。画布存续期间保持组件挂载，关闭侧栏
         只隐藏 UI，使 exitPreview 能先恢复快照并 resume，避免产生“可编辑但
         不再保存/同步”的假编辑状态。 -->
    <template v-if="mindMap">
      <VersionHistory
        v-show="activeSidebar === 'versionHistory'"
        :mindMap="mindMap"
        :mindmapId="props.mindmapId"
        :yjsSync="yjsSyncRef"
        :readonly="isReadonly"
        :flush-changes="flushBeforeLeave"
        :get-content-revision="getCurrentContentRevision"
        :get-content-change-version="getCurrentContentChangeVersion"
        :fence-authoritative-write="fenceAuthoritativeVersionWrite"
        :apply-authoritative-document="applyRestoredVersionData"
        :authoritative-reset-generation="authoritativeResetGeneration"
        @editing-transition="onVersionEditingTransition"
        @change-tracking="onVersionChangeTracking"
      />
    </template>
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
import {
  batchUpdateMindmapContent,
  getMindmap,
  resetMindmapCollaboration,
  updateMindmapView,
} from '@/api/mindmap/mindmap'
import { YjsMindmapSync } from '@/utils/yjs-sync'
import {
  countMindmapNodes,
  resolveMindmapPerformanceOptions,
} from '@/utils/mindmap-performance'
import { waitForMindmapInitialRender } from '@/utils/mindmap-initial-render'
import {
  getMindmapResumeRecoveryReason,
  mindmapCommandStartsNodeTextEdit,
  shouldBlockMindmapStructureWrite,
} from '@/utils/mindmap-save-lifecycle'
import { ensureMindmapDocumentPlugins } from '@/utils/mindmap-plugin-loader'
import { getNodeEditLeaseBlockedMessage } from '@/utils/mindmap-node-edit-lease'
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
  applyMindmapFileMetaIntents,
  applyMindmapOperationIntents,
  applyMindmapNodeRevisionChanges,
  appendUniqueMindmapOperation,
  buildCrossNodeContentOperations,
  buildMindmapDocumentOperations,
  buildMindmapContentOperations,
  buildNodeTagContentOperations,
  compactMindmapContentOperations,
  captureMindmapFileMetaIntents,
  detectMindmapFileOperations,
  findConflictingMindmapFileMetaIntents,
  mergePendingCrossNodeOperation,
  omitMindmapFileMetaIntents,
  rebaseMindmapOperationTargetRevisions,
  snapshotMindmapDocumentMeta,
} from '@/utils/mindmap-operations'
import {
  detailListTouchesCrossNodeState,
  extractCrossNodeState,
} from '@/utils/yjs-cross-node-state'
import useUserStore from '@/store/modules/user'
import {
  areMindmapDraftDocumentsEqual,
  getMindmapDraft,
  isMindmapDraftSessionActive,
  removeMindmapDraft,
  resolveMindmapDraftOpenMode,
  saveMindmapDraft,
  saveMindmapDraftFallbackSync,
  startMindmapDraftSessionLease,
} from '@/utils/mindmap-draft'
import { downloadMindmapBackup } from '@/utils/mindmap-backup'
import { isMindmapContentWritable } from '@/utils/mindmap-content-state'
import { flushPendingMindmapChanges } from '@/utils/mindmap-save-lifecycle'
import {
  assertMindmapSaveMutationResponse,
  captureRejectedMindmapMutationSnapshot,
  createMindmapSaveMutation,
  submitMindmapSaveMutation,
} from '@/utils/mindmap-save-mutation'
import { cloneRequestPayload } from '@/utils/requestPayload'
import { normalizeMindmapExportRuntimeConfig } from '@/utils/mindmap-export'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'
import { assertMindmapImportDocument } from '@/utils/mindmap-import-validation'
import { createMindmapDocumentMetaBuffer } from '@/utils/mindmap-document-meta-buffer'
import {
  applyMindmapActiveCrossNodeEditorSnapshots,
  applyMindmapActiveEditorTextSnapshots,
  applyAuthoritativeMindmapDocument,
  mindmapDocumentRequiresFullRuntimeReplacement,
  mindmapTreeContainsAssociativeLine,
  mindmapTreeContainsExactOuterFrame,
  mindmapTreeContainsNodeUid,
  mindmapTreeNodeIsRuntimeVisible,
  mindmapTreeNodesHaveSameEditableData,
  mindmapTreesHaveSameCrossNodeState,
} from '@/utils/mindmap-document-apply'
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
import CommentSidebar from './CommentSidebar.vue'

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
// 冲突批次已经被服务器拒绝、但权威正文尚未成功回源时，当前 runtime
// 仍属于旧 revision。临时只读门闩阻止它产生新的保存意图；进入门闩前
// 会先提交并持久化所有活动输入，成功应用权威正文后才解除。
const authoritativeRecoveryEditingBlocked = ref(false)
// 历史预览和整图导入都包含不可避免的网络/插件等待窗口。它们只冻结用户
// 交互，不撤销当前会话的写权限；已经登记的修改仍须能够在门闩内 flush。
const versionTransitionEditingBlocked = ref(false)
const importTransitionEditingBlocked = ref(false)
const isReadonly = computed(() => (
  props.readonly
  || authoritativeRecoveryEditingBlocked.value
  || versionTransitionEditingBlocked.value
  || importTransitionEditingBlocked.value
  || (Boolean(props.mindmapId) && serverCanEdit.value !== true)
))
let terminalState = ''

const editContainerRef = ref(null)
const mindMapContainerRef = ref(null)
const outlineEditRef = ref(null)
const mindMap = shallowRef(null)
const documentData = ref({})
const showDragMask = ref(false)
let storeConfigTimer = null
let localWorkspaceSaveFailureNotified = false
let enableShowLoading = true
let autoSaveTimer = null
let yjsSync = null
const yjsSyncRef = shallowRef(null)
// Yjs/恢复门闩本身是普通类字段和闭包变量。单独桥接成 Vue ref，确保
// 属性面板中的结构控件会即时更新 disabled/无障碍状态，而不只是点击后拒绝。
const structureWriteBlocked = ref(false)
const isSaving = ref(false)
const pendingSave = ref(false)
const saveStatus = ref('idle') // idle | pending | saving | retrying | syncing | offline | saved | error
let saveStatusTimer = null
const AUTO_SAVE_DELAY = 2000
const VIEW_SAVE_DELAY = 1200
const DRAFT_SAVE_DELAY = 500
const CLOUD_EXIT_MAX_PASSES = 3
const SAVE_RETRY_DELAYS = [2000, 5000, 10000, 30000, 60000]
const AUTHORITATIVE_RELOAD_RETRY_DELAYS = [2000, 5000, 10000, 30000]
const RESUME_REVISION_CHECK_INTERVAL = 3000
const COLLABORATION_SYNC_CONFIRM_OPERATION = 'collaboration.sync.confirm'
const CONTENT_SNAPSHOT_OPERATION = 'document.content.update'
const DOCUMENT_META_OPERATION_TYPES = Object.freeze({
  layout: 'file.layout.update',
  theme: 'file.theme.update',
  documentData: 'file.document_data.update',
})
const DOCUMENT_META_FIELDS_BY_OPERATION = Object.freeze(Object.fromEntries(
  Object.entries(DOCUMENT_META_OPERATION_TYPES).map(([field, type]) => [type, field]),
))
let dataChangeDetailHandler = null
let contentRevision = 1
let pendingContentOperations = []
let activeSaveMutation = null
let pendingFileMetaIntents = {}
let reconcilingFileMetaIntents = {}
let fileMetaReconciliationRequired = false
let documentDataGeneration = 0
let activeSaveDocumentDataGeneration = null
let authoritativeReloadRequired = false
let authoritativeReloadTimer = null
let authoritativeReloadAttempt = 0
let authoritativeReloadInProgress = false
let authoritativeReloadNoticeShown = false
let authoritativeReloadMinimumRevision = 0
let viewChangeVersion = 0
let savedViewChangeVersion = 0
let savedDocumentMeta = null
const nodeRevisionMap = new Map()
let conflictBlocked = false
let blockedConflictData = null
let pendingAutomaticConflictRecovery = null
let pendingRemoteDocumentReset = null
let remoteDocumentResetRetryBlocked = false
const authoritativeResetGeneration = ref(0)
const saveRecoveryKind = ref('')
let applyingServerTree = false
let versionChangeTrackingPaused = false
let terminatingSession = false
let componentMounted = false
let initialRenderReady = false
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
let selectedAuthoritativeServerData = null
let pendingViewData = undefined
let viewSaveTimer = null
let viewSaveInProgress = false
let viewSaveRequested = false
let viewSavePromise = null
let viewSaveGeneration = 0
let stopDraftSessionLease = null
let pendingClientMutationId = null
let pendingClientMutationBaseRevision = null
let resumeRevisionCheckPromise = null
let lastResumeRevisionCheckAt = 0
let protectingActiveEditorFromRemoteDelete = false
// 整图导入已经销毁旧 Y.Doc、但替换快照尚未由 HTTP 确认时，任何通用的
// startYjsSyncIfReady 调用都必须保持断开。否则会用旧 revision/lineage 把
// 服务端旧缓存合入尚未保存的导入树。成功保存或完整权威回源后再解除。
let collaborationRestartDeferredUntilSave = false
let remoteDocumentApplyRecoveryPromise = null
let editingTransitionGeneration = 0

const documentMetaBuffer = createMindmapDocumentMetaBuffer((meta) => {
  yjsSync?.syncDocumentMeta(meta, pendingClientMutationId)
})
const draftProtection = createMindmapDraftProtectionTracker()

function createMutationId() {
  return globalThis.crypto?.randomUUID?.()
    || `mindmap-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function getCurrentContentRevision() {
  return contentRevision
}

function getCurrentContentChangeVersion() {
  return draftProtection.getChangeVersion()
}

function createRemoteDeletedEditorProtectionIdentity(entityIdentity, revision) {
  const eventId = createMutationId()
  return {
    // eventId 放在前部，经过草稿 sessionId 长度裁剪后仍保持唯一；实体身份
    // 同时保留在事件键和通知键中，便于区分同 revision 的连续冲突。
    eventKey: `deleted-${eventId}-${String(entityIdentity || '')}`,
    notificationKey: `${String(entityIdentity || '')}:${Number(revision) || 'unknown'}:${eventId}`,
  }
}

function createRemoteDeletedEditorProtectionNotifier(notifications) {
  const notifiedProtectionKeys = new Set()
  return (protectionKey, saved) => {
    if (!protectionKey || notifiedProtectionKeys.has(protectionKey)) return false
    notifiedProtectionKeys.add(protectionKey)
    if (saved) {
      notifications.warning({
        title: '协作者变更了正在编辑的内容',
        message: '云端变更已应用；覆盖前的最后输入已保留到冲突保护草稿',
      })
    } else {
      notifications.error({
        title: '冲突输入未能持久保护',
        message: '请保持页面开启，并从其他窗口撤销变更后复制当前输入',
      })
    }
    return true
  }
}

const notifyRemoteDeletedEditorProtectionResult =
  createRemoteDeletedEditorProtectionNotifier(ElNotification)

function ensurePendingClientMutationId() {
  if (!pendingClientMutationId) {
    pendingClientMutationId = createMutationId()
    pendingClientMutationBaseRevision = contentRevision
    yjsSync?.markLocalMutation?.(
      pendingClientMutationId,
      pendingClientMutationBaseRevision,
    )
  }
  return pendingClientMutationId
}

function clearPendingClientMutation() {
  pendingClientMutationId = null
  pendingClientMutationBaseRevision = null
}

function advancePendingUnsentMutationBaseRevision(nextRevision) {
  const normalizedRevision = Number(nextRevision)
  if (
    !pendingClientMutationId
    || !Number.isInteger(normalizedRevision)
    || normalizedRevision <= 0
  ) return false
  if (
    Number.isInteger(pendingClientMutationBaseRevision)
    && pendingClientMutationBaseRevision >= normalizedRevision
  ) return true
  // 没有协作源时，这一批天然只存在于 HTTP 队列；有协作源时则必须由
  // Yjs 证明尚未分配过任何实时序号，避免把可能已到达服务端的帧改基。
  if (
    yjsSync
    && yjsSync.rebaseUnsentLocalMutation?.(
      pendingClientMutationId,
      normalizedRevision,
    ) !== true
  ) return false
  pendingClientMutationBaseRevision = normalizedRevision
  return true
}

const draftSessionId = createMutationId()

function ensureDraftSessionLease() {
  if (stopDraftSessionLease || !canUseLocalDraft()) return
  stopDraftSessionLease = startMindmapDraftSessionLease(
    userStore.id,
    props.mindmapId,
    draftSessionId,
  )
}

function markDocumentMetaSaved(document) {
  savedDocumentMeta = snapshotMindmapDocumentMeta(document)
}

function normalizeServerTheme(theme) {
  const normalized = normalizeMindmapDocumentMetaPatch({ theme })
  return normalized.theme || { template: 'default', config: {} }
}

function queueFileOperation(type) {
  appendUniqueMindmapOperation(pendingContentOperations, type)
}

function recordDocumentOperations(document, changedFields = null) {
  const comparisonBaseline = activeSaveMutation?.document
    ? snapshotMindmapDocumentMeta(activeSaveMutation.document)
    : savedDocumentMeta
  const detectedOperationTypes = detectMindmapFileOperations(
    document,
    comparisonBaseline,
  )
  const scopedOperationTypes = Array.isArray(changedFields)
    ? changedFields
        .map(field => DOCUMENT_META_OPERATION_TYPES[field])
        .filter(Boolean)
    : null
  const operationTypes = scopedOperationTypes
    ? detectedOperationTypes.filter(type => scopedOperationTypes.includes(type))
    : detectedOperationTypes.filter(type => {
        const field = DOCUMENT_META_FIELDS_BY_OPERATION[type]
        // A value already accepted by HTTP but waiting for authoritative reload
        // is a display overlay, not a new local edit. Generic node data_change
        // events must not enqueue that file domain again; an explicit metadata
        // event creates a pending intent through the scoped branch above.
        return !field
          || !Object.prototype.hasOwnProperty.call(reconcilingFileMetaIntents, field)
          || Object.prototype.hasOwnProperty.call(pendingFileMetaIntents, field)
      })
  if (scopedOperationTypes) {
    const revertedOperationTypes = scopedOperationTypes.filter(
      type => !operationTypes.includes(type),
    )
    if (revertedOperationTypes.length > 0) {
      const revertedSet = new Set(revertedOperationTypes)
      pendingContentOperations = pendingContentOperations.filter(
        operation => !revertedSet.has(operation?.type),
      )
      pendingFileMetaIntents = omitMindmapFileMetaIntents(
        pendingFileMetaIntents,
        revertedOperationTypes,
      )
    }
  }
  pendingFileMetaIntents = captureMindmapFileMetaIntents(
    pendingFileMetaIntents,
    document,
    operationTypes,
  )
  for (const type of operationTypes) {
    queueFileOperation(type)
  }
}

function getProtectedFileMetaIntents() {
  const activeIntents = activeSaveMutation
    ? captureMindmapFileMetaIntents(
        reconcilingFileMetaIntents,
        activeSaveMutation.document,
        activeSaveMutation.operations,
      )
    : reconcilingFileMetaIntents
  return {
    ...activeIntents,
    ...pendingFileMetaIntents,
  }
}

function clearFileMetaIntentState() {
  pendingFileMetaIntents = {}
  reconcilingFileMetaIntents = {}
  fileMetaReconciliationRequired = false
}

function getRuntimeDocument() {
  const data = mindMap.value?.getData?.(true) || {}
  return {
    ...data,
    documentData: normalizeMindmapDocumentData(documentData.value),
  }
}

function getCurrentDocument() {
  return applyMindmapFileMetaIntents(
    getRuntimeDocument(),
    getProtectedFileMetaIntents(),
  )
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
  if (Object.prototype.hasOwnProperty.call(normalizedPatch, 'documentData')) {
    documentDataGeneration += 1
  }
  if (!props.mindmapId) {
    persistLocalWorkspace(normalizedPatch)
    return
  }
  const current = {
    ...getRuntimeDocument(),
    ...normalizedPatch,
  }
  recordDocumentOperations(current, Object.keys(normalizedPatch))
  ensurePendingClientMutationId()
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

function canPersistProtectedDraft() {
  // 权威恢复门闩只冻结旧画布交互，不撤销用户对该文件已有的草稿身份。
  // 冲突副本必须仍可写入；真正的只读访问、服务端撤权和终止会话继续拒绝。
  return Boolean(
    props.mindmapId
    && userStore.id
    && hasRealWritePermission()
    && !terminalState
  )
}

function hasRealWritePermission() {
  return !props.readonly && serverCanEdit.value === true
}

function canFlushCloudChangesDuringEditingTransition() {
  return Boolean(
    props.mindmapId
    && hasRealWritePermission()
    && !authoritativeRecoveryEditingBlocked.value
    && !terminalState
  )
}

function canUseLocalDraft() {
  return canPersistProtectedDraft() && !authoritativeRecoveryEditingBlocked.value
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

function createAutomaticConflictDraftOptions(document, baseContentRevision, eventKey = '') {
  const updatedAt = nextDraftUpdatedAt()
  const normalizedRevision = Number(baseContentRevision)
  const revisionKey = Number.isSafeInteger(normalizedRevision) && normalizedRevision > 0
    ? normalizedRevision
    : 'unknown'
  const normalizedEventKey = String(eventKey || '')
    .replace(/[^a-zA-Z0-9_-]/g, '-')
    .slice(0, 80)
  return {
    userId: userStore.id,
    mindmapId: props.mindmapId,
    // 冲突快照必须独立于当前编辑会话。加载云端版本时只清理当前会话草稿，
    // 这份快照会继续留在草稿中心，避免再次弹窗或被后续成功保存误删。
    // 普通冲突仍按 revision 覆盖最新完整快照；远端删除活动节点时额外
    // 带节点事件键，防止同 revision 的第二次删除覆盖第一份最后输入。
    sessionId: `${draftSessionId}-conflict-r${revisionKey}${
      normalizedEventKey ? `-${normalizedEventKey}` : ''
    }`,
    contentRevision: Number(baseContentRevision) || contentRevision,
    // 冲突写操作会等草稿队列中的前序任务结束后才启动，因此必须在入队前
    // 冻结当前树；否则随后应用的远端树可能改写这份保护快照的引用。
    document: cloneRequestPayload(document),
    updatedAt,
  }
}

async function preserveAutomaticConflictDraft(
  document,
  baseContentRevision,
  eventKey = '',
  { syncFallback = false } = {},
) {
  if (!document || !canPersistProtectedDraft()) return { saved: false, storage: null }
  const options = createAutomaticConflictDraftOptions(
    document,
    baseContentRevision,
    eventKey,
  )
  // IndexedDB writes are asynchronous and pagehide cannot wait for them. For
  // renderer apply failures, persist the exact same immutable conflict record
  // to localStorage before the first await; the durable write below replaces
  // that fallback only after its transaction completes.
  let fallbackSaved = false
  if (syncFallback) {
    try {
      fallbackSaved = saveMindmapDraftFallbackSync(options)
    } catch (error) {
      console.warn('同步保存自动冲突草稿失败:', error)
    }
  }
  try {
    const result = await enqueueRequiredDraftOperation(() => saveMindmapDraft(options))
    if (result?.saved === true || !fallbackSaved) return result
    return { saved: true, storage: 'localStorage' }
  } catch (error) {
    console.warn('保存自动冲突草稿失败:', error)
    return fallbackSaved
      ? { saved: true, storage: 'localStorage' }
      : { saved: false, storage: null }
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

function enqueueRequiredDraftOperation(operation) {
  const requiredOperation = draftWriteQueue
    .catch(() => undefined)
    .then(operation)
  draftWriteQueue = requiredOperation.catch((error) => {
    console.warn('本地脑图草稿操作失败:', error)
  })
  return requiredOperation
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
  if (!record?.key) return Promise.resolve()
  const userId = userStore.id
  const mindmapId = props.mindmapId
  return enqueueDraftOperation(() => removeMindmapDraft(userId, mindmapId, {
    key: record.key,
    beforeUpdatedAt: record.updatedAt,
  }))
}

async function removeDraftRecordRequired(record, message) {
  const userId = userStore.id
  const mindmapId = props.mindmapId
  await enqueueRequiredDraftOperation(() => removeMindmapDraft(userId, mindmapId, {
    key: record.key,
    beforeUpdatedAt: record.updatedAt,
  }))
  const remaining = await getMindmapDraft(userId, mindmapId, { key: record.key })
  if (remaining) throw new Error(message)
}

async function restoreDraftRecordPersistence(record) {
  if (!record?.document) return
  const result = await enqueueRequiredDraftOperation(() => saveMindmapDraft({
    userId: userStore.id,
    mindmapId: props.mindmapId,
    sessionId: record.sessionId,
    contentRevision: record.contentRevision,
    document: record.document,
    name: record.name,
    updatedAt: record.updatedAt,
  }))
  const restored = await getMindmapDraft(userStore.id, props.mindmapId, { key: record.key })
  if (result?.saved !== true || !restored) {
    throw new Error('本地草稿回滚失败，修改仍保留在当前页面')
  }
}

async function discardLocalDraftAndUseCloud(record, signal) {
  if (!record?.updatedAt) return
  clearTimeout(draftSaveTimer)
  const mindmapId = props.mindmapId
  const observedRevision = contentRevision
  let localDraftRemoved = false
  try {
    // “使用云端”只放弃这条本地草稿。不能重置整个协作房间：同一账号的
    // 另一浏览器或其他协作者可能正有尚未 HTTP 保存的 Yjs 修改。握手层会
    // 隔离与 HTTP 基线不一致的旧检查点，当前页面只需重新读取权威正文。
    await removeDraftRecordRequired(
      record,
      '本地草稿未能删除，已保留原内容并停止切换',
    )
    localDraftRemoved = true
    const latestResponse = await getMindmap(mindmapId, { signal })
    if (sessionCancelled(signal)) return null
    if (
      Number(latestResponse.data?.contentRevision)
      < Number(observedRevision)
    ) throw new Error('云端协作基线尚未完成更新，请稍后重试')
    restoredLocalDraft = false
    restoredDraftRecord = null
    draftProtection.markClean()
    return latestResponse.data
  } catch (error) {
    if (localDraftRemoved) {
      try {
        await restoreDraftRecordPersistence(record)
      } catch (restoreError) {
        error.message = `${error?.message || '云端状态校准失败'}；${restoreError.message}`
      }
    }
    throw error
  }
}

function clearRestoredDraft() {
  restoredLocalDraft = false
  if (!restoredDraftRecord) return
  const record = restoredDraftRecord
  restoredDraftRecord = null
  clearDraftRecord(record)
}

function stopCurrentCollaborationSource() {
  if (!yjsSync) return false
  yjsSync.destroy({ flushCheckpoint: false })
  yjsSync = null
  yjsSyncRef.value = null
  refreshStructureWriteBlockedState()
  return true
}

async function resetCurrentCollaborationToCloud(observedRevision) {
  // 先关闭当前 Yjs 连接且不冲刷旧检查点。服务端随后推进 revision 并清空
  // 整个旧缓存，其他协作者会通过 document_reset 重新加载数据库正文。
  stopCurrentCollaborationSource()
  return resetMindmapCollaboration(props.mindmapId, {
    observedRevision,
    clientMutationId: createMutationId(),
  })
}

function persistLocalDraftBeforeUnload() {
  if (terminalState || !canUseLocalDraft() || !mindMap.value || !hasUnsavedChanges()) return false
  const draftChangeVersion = draftProtection.beginPersist()
  const saved = saveMindmapDraftFallbackSync(createDraftOptions(getCurrentDocument()))
  draftProtection.recordPersistResult(draftChangeVersion, saved)
  return saved
}

function handlePageHide() {
  // 浮层输入只有在编辑器关闭时才进入模型。页面被冻结前必须先提交 DOM
  // 中的最后字符，再判断脏状态并写同步草稿。
  commitActiveEditorsBeforeTermination()
  persistLocalDraftBeforeUnload()
  if (viewSaveRequested) void flushPendingViewSave()
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    void reconcileCloudRevisionOnResume()
    return
  }
  if (document.visibilityState !== 'hidden') return
  commitActiveEditorsBeforeTermination()
  if (viewSaveRequested) void flushPendingViewSave()
  if (!hasUnsavedChanges()) return
  // localStorage provides the immediate freeze/navigation fallback; IndexedDB
  // remains the durable, larger-capacity primary draft store when time permits.
  persistLocalDraftBeforeUnload()
  persistLocalDraft()
}

function handleWindowFocus() {
  void reconcileCloudRevisionOnResume()
}

async function performCloudRevisionResumeCheck() {
  if (
    terminalState
    || !componentMounted
    || !props.mindmapId
    || !mindMap.value
    || isBrowserOffline()
    || isSaving.value
    || resolvingStaleState
    || authoritativeReloadInProgress
    || isChangeTrackingSuspended()
    || hasUnsavedChanges()
    || viewSaveRequested
    || viewSaveInProgress
  ) return false

  const requestedDraftChangeVersion = draftProtection.getChangeVersion()
  const requestedViewChangeVersion = viewChangeVersion
  const signal = sessionController?.signal
  const response = await getMindmap(props.mindmapId, {
    signal,
    silentError: true,
  })
  if (
    sessionCancelled(signal)
    || !mindMap.value
    || isSaving.value
    || resolvingStaleState
    || authoritativeReloadInProgress
    || isChangeTrackingSuspended()
    || hasUnsavedChanges()
    || viewSaveRequested
    || viewSaveInProgress
    || draftProtection.getChangeVersion() !== requestedDraftChangeVersion
    || viewChangeVersion !== requestedViewChangeVersion
  ) return false
  const data = response.data
  const cloudRevision = Number(data?.contentRevision)
  const cloudNodeCount = Number(data?.nodeCount)
  const localNodeCount = countMindmapNodes(
    getCurrentDocument().root,
    Number.isInteger(cloudNodeCount) && cloudNodeCount > 0
      ? cloudNodeCount
      : Number.POSITIVE_INFINITY,
  )
  const recoveryReason = getMindmapResumeRecoveryReason({
    cloudRevision,
    localRevision: contentRevision,
    cloudNodeCount,
    localNodeCount,
    hasLocalChanges: hasUnsavedChanges(),
  })
  if (!recoveryReason) return false

  // 后台标签页可能错过 document_reset/stale_state 广播。重新获得焦点时以
  // 数据库正文为权威基线重建 Yjs，避免旧连接保持 stale 后让画布看似可见、
  // 实际无法编辑。先提交活动文本框并复核代际，确保本轮 GET 不覆盖新输入。
  commitActiveEditorsBeforeTermination()
  await nextTick()
  if (
    sessionCancelled(signal)
    || !mindMap.value
    || hasUnsavedChanges()
    || viewSaveRequested
    || viewSaveInProgress
    || draftProtection.getChangeVersion() !== requestedDraftChangeVersion
    || viewChangeVersion !== requestedViewChangeVersion
  ) {
    // 焦点检查的 GET 与用户输入并行。任何在请求期间开始或由 blur 提交的
    // 本地 mutation 都继续走原自动保存/CAS 合并链路，绝不能被这份更早的
    // 云端快照替换；否则后台标签页恢复时会把最后输入仅留在草稿中。
    return false
  }
  clearTimeout(autoSaveTimer)
  const recoveryDraftChangeVersion = draftProtection.getChangeVersion()
  const recoveryViewChangeVersion = viewChangeVersion

  const reloaded = await reloadLatestServerDocument({
    preserveLocalDraft: false,
    serverData: data,
    expectedDraftChangeVersion: recoveryDraftChangeVersion,
    expectedViewChangeVersion: recoveryViewChangeVersion,
  })
  if (!reloaded) {
    markAuthoritativeReloadRequired()
    if (
      !hasUnsavedChanges()
      && !viewSaveRequested
      && !viewSaveInProgress
    ) scheduleNextAuthoritativeReload()
    return false
  }
  ElMessage.success('已同步云端最新内容，可以继续编辑')
  return true
}

function reconcileCloudRevisionOnResume() {
  if (resumeRevisionCheckPromise) return resumeRevisionCheckPromise
  const now = Date.now()
  if (now - lastResumeRevisionCheckAt < RESUME_REVISION_CHECK_INTERVAL) return false
  lastResumeRevisionCheckAt = now
  const operation = performCloudRevisionResumeCheck()
    .catch((error) => {
      if (!sessionCancelled(sessionController?.signal)) {
        console.warn('恢复前台脑图协作会话失败:', error)
      }
      return false
    })
    .finally(() => {
      if (resumeRevisionCheckPromise === operation) resumeRevisionCheckPromise = null
    })
  resumeRevisionCheckPromise = operation
  return operation
}

function sessionCancelled(signal) {
  return !componentMounted || Boolean(terminalState) || signal?.aborted === true
}

function cancelSessionAsyncWork() {
  sessionController?.abort()
  sessionController = null
  clearTimeout(authoritativeReloadTimer)
  authoritativeReloadTimer = null
  setAuthoritativeReloadInProgress(false)
  if (localDraftDialogOpen || conflictDialogOpen) ElMessageBox.close()
  localDraftDialogOpen = false
  conflictDialogOpen = false
  setPendingAutomaticConflictRecovery(null)
  setPendingRemoteDocumentReset(null)
  remoteDocumentResetRetryBlocked = false
}

function restoreLocalDraftRecord(draft) {
  restoredDraftRecord = { key: draft.key, updatedAt: draft.updatedAt }
  return draft.document
}

async function useAuthoritativeCloudVersion(draft, signal) {
  try {
    const latestServerData = await discardLocalDraftAndUseCloud(draft, signal)
    if (latestServerData) selectedAuthoritativeServerData = latestServerData
    return null
  } catch (error) {
    if (sessionCancelled(signal)) return null
    const preservedDraft = await getMindmapDraft(
      userStore.id,
      props.mindmapId,
      { key: draft.key },
    ).catch(() => null)
    ElNotification.error({
      title: '未能切换到云端版本',
      message: `${error?.message || '云端状态校准失败'}；本地修改仍保留，已继续打开本地版本`,
    })
    return restoreLocalDraftRecord(preservedDraft || draft)
  }
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
  let otherSessionActive = false
  if (draft.sessionId && draft.sessionId !== draftSessionId) {
    otherSessionActive = await isMindmapDraftSessionActive(
      userStore.id,
      props.mindmapId,
      draft.sessionId,
    )
    if (sessionCancelled(signal)) return null
  }
  const draftOpenMode = resolveMindmapDraftOpenMode({
    draftSessionId: draft.sessionId,
    currentSessionId: draftSessionId,
    requestedDraftKey: props.draftKey,
    otherSessionActive,
  })
  if (draftOpenMode === 'skip-active') {
    // 另一标签页仍在持续续租，这不是崩溃恢复草稿。它会自行完成云端保存，
    // 当前窗口不应弹窗或把对方的工作区当成自己的恢复来源。
    return null
  }
  // 只有确认记录不属于其他活跃编辑窗口后才能清理等价草稿；否则当前
  // 窗口可能删除对方仍依赖的断线/崩溃保护副本。
  if (areMindmapDraftDocumentsEqual(draft.document, serverDocument)) {
    clearDraftRecord(draft)
    return null
  }
  if (draftOpenMode === 'preserve-background') {
    // 普通文件入口始终快速打开云端权威内容。失活窗口留下的修改继续保留
    // 在草稿中心，只有用户从草稿中心明确选择该记录时才进入恢复决策。
    ElNotification.info({
      title: '已打开云端版本',
      message: `检测到 ${new Date(draft.updatedAt).toLocaleString()} 的其他窗口草稿，已保留在草稿中心，不影响当前编辑`,
    })
    return null
  }
  if (Number(draft.contentRevision) === Number(contentRevision)) {
    try {
      localDraftDialogOpen = true
      await ElMessageBox.confirm(
        `检测到 ${new Date(draft.updatedAt).toLocaleString()} 保存的本地修改（基于云端版本 ${draft.contentRevision}）。继续本地修改会自动同步；使用云端版本只放弃这份草稿，不会中断其他窗口的协作。`,
        '发现未同步的本地修改',
        {
          type: 'warning',
          confirmButtonText: '继续本地修改',
          cancelButtonText: '使用云端版本',
          distinguishCancelAndClose: true,
          closeOnClickModal: false,
          closeOnPressEscape: false,
          showClose: false,
        }
      )
      if (sessionCancelled(signal)) return null
      return restoreLocalDraftRecord(draft)
    } catch (action) {
      if (sessionCancelled(signal)) return null
      if (action === 'cancel') {
        return useAuthoritativeCloudVersion(draft, signal)
      }
      return restoreLocalDraftRecord(draft)
    } finally {
      localDraftDialogOpen = false
    }
  }

  try {
    localDraftDialogOpen = true
    await ElMessageBox.confirm(
      `本地修改基于版本 ${draft.contentRevision}，云端已更新到版本 ${contentRevision}。下载副本后使用云端，或直接放弃这份草稿；两种方式都不会中断其他窗口的协作。`,
      '本地修改与云端版本不同',
      {
        type: 'warning',
        confirmButtonText: '下载副本并使用云端',
        cancelButtonText: '使用云端版本',
        distinguishCancelAndClose: true,
        closeOnClickModal: false,
        closeOnPressEscape: false,
        showClose: false,
      }
    )
    if (sessionCancelled(signal)) return null
    const downloaded = downloadConflictBackup(draft.document, 'mindmap-local-draft')
    if (downloaded) {
      return useAuthoritativeCloudVersion(draft, signal)
    } else {
      ElMessage.error('浏览器未能下载草稿，副本仍保留在本地草稿中心')
      return restoreLocalDraftRecord(draft)
    }
  } catch (action) {
    if (sessionCancelled(signal)) return null
    if (action === 'cancel') {
      return useAuthoritativeCloudVersion(draft, signal)
    }
    return restoreLocalDraftRecord(draft)
  } finally {
    localDraftDialogOpen = false
  }
  return null
}

function recordContentOperations(detailList) {
  if (isContentDetailTrackingSuspended()) return false
  const crossNodeStateChanged = detailListTouchesCrossNodeState(detailList)
  // Text input and ordinary node styling are the dominant hot path. Their
  // command details prove that no relation/summary/group/asset changed, so do
  // not read and traverse the complete canvas merely to rediscover that fact.
  const currentCrossNodeState = crossNodeStateChanged
    ? extractCrossNodeState(mindMap.value?.getData?.(true))
    : crossNodeOperationSnapshot
  const nextOperations = [
    ...buildMindmapContentOperations(detailList, nodeRevisionMap),
    ...buildNodeTagContentOperations(detailList),
    ...(crossNodeStateChanged
      ? buildCrossNodeContentOperations(
          crossNodeOperationSnapshot || currentCrossNodeState,
          currentCrossNodeState,
        )
      : []),
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
      let existingIndex = -1
      for (let index = pendingContentOperations.length - 1; index >= 0; index -= 1) {
        const item = pendingContentOperations[index]
        const itemDomain = item.type?.startsWith('node.tag.')
          ? (item.type === 'node.tag.reorder' ? 'node.tag.order' : 'node.tag.binding')
          : item.type?.split('.')[0]
        if (itemDomain === domain && item.payload?.key === key) {
          existingIndex = index
          break
        }
      }
      if (existingIndex >= 0) {
        const mergedOperation = ['relation', 'summary', 'group', 'asset'].includes(domain)
          ? mergePendingCrossNodeOperation(
              pendingContentOperations[existingIndex],
              operation,
            )
          : operation
        if (Array.isArray(mergedOperation)) {
          pendingContentOperations.splice(existingIndex, 1, ...mergedOperation)
        } else if (mergedOperation) {
          pendingContentOperations.splice(existingIndex, 1, mergedOperation)
        } else {
          pendingContentOperations.splice(existingIndex, 1)
        }
        continue
      }
    }
    pendingContentOperations.push(operation)
  }
  // 同一防抖窗口内的连续修改先折叠为最终净效果。输入后撤销、移动后
  // 撤销以及新建后立即删除都不应占用一个 revision 或制造伪冲突。
  pendingContentOperations = compactMindmapContentOperations(
    pendingContentOperations,
  )
  if (crossNodeStateChanged) crossNodeOperationSnapshot = currentCrossNodeState
  return nextOperations.length > 0
}

function onMindmapDataChangeDetail(detailList) {
  if (isContentDetailTrackingSuspended()) return
  const operationRecorded = recordContentOperations(detailList)
  if (!operationRecorded) return
  const clientMutationId = ensurePendingClientMutationId()
  yjsSync?.onDataChangeDetail(detailList, clientMutationId)
  // data_change 在远端渲染保护窗口内会被过滤；如果用户恰好在该窗口输入，
  // data_change_detail 仍需独立把真实本地操作放入保存队列并启动稳定期保存。
  scheduleLocalDraftPersist()
  resetSaveRetryForNewChange()
  clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
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

function getRuntimeMindmapNodeUid(node) {
  return String(node?.getData?.('uid') || node?.uid || '').trim()
}

function collectActiveEditorProtectionTargets(
  remoteRoot,
  targetMindMap,
  forceCommit = false,
) {
  const targets = []
  const textEditor = targetMindMap?.renderer?.textEdit
  const editingNode = textEditor?.getCurrentEditNode?.()
  const editingNodeUid = getRuntimeMindmapNodeUid(editingNode)
  const outlineTextEditor = outlineEditRef.value?.getActiveTextEditor?.()
  const outlineEditingNodeUid = String(
    outlineTextEditor?.nodeUid || '',
  ).trim()
  const associativeLine = targetMindMap?.associativeLine
  const outerFrame = targetMindMap?.outerFrame
  const hasActiveAssociativeLineEditor = (
    associativeLine?.showTextEdit === true
    && Array.isArray(associativeLine.activeLine)
  )
  const activeOuterFrame = outerFrame?.showTextEdit === true
    ? outerFrame.activeOuterFrame
    : null
  const currentDocument = (
    editingNodeUid
    || outlineEditingNodeUid
    || hasActiveAssociativeLineEditor
    || activeOuterFrame
  ) ? targetMindMap?.getData?.(true) : null
  const currentRoot = currentDocument?.root || currentDocument

  if (editingNodeUid) {
    const retained = mindmapTreeContainsNodeUid(remoteRoot, editingNodeUid)
    const runtimeVisible = retained && mindmapTreeNodeIsRuntimeVisible(
      remoteRoot,
      editingNodeUid,
    )
    targets.push({
      kind: 'node',
      identity: `node:${editingNodeUid}`,
      editor: textEditor,
      retained,
      // simple-mind-map 的增量更新会保留未变化的节点实例和编辑框。
      // 只有远端也改了当前节点本身时才需要先提交 DOM-only 输入。
      requiresCommit: retained && (
        forceCommit
        || !runtimeVisible
        || !mindmapTreeNodesHaveSameEditableData(
          currentRoot,
          remoteRoot,
          editingNodeUid,
        )
      ),
    })
  }

  if (outlineEditingNodeUid) {
    const retained = mindmapTreeContainsNodeUid(
      remoteRoot,
      outlineEditingNodeUid,
    )
    const runtimeVisible = retained && mindmapTreeNodeIsRuntimeVisible(
      remoteRoot,
      outlineEditingNodeUid,
    )
    targets.push({
      kind: 'outline-node',
      identity: `node:${outlineEditingNodeUid}`,
      editor: outlineTextEditor,
      retained,
      requiresCommit: retained && (
        forceCommit
        || !runtimeVisible
        || !mindmapTreeNodesHaveSameEditableData(
          currentRoot,
          remoteRoot,
          outlineEditingNodeUid,
        )
      ),
    })
  }

  const crossNodeStateRetained = (
    !hasActiveAssociativeLineEditor
    && !activeOuterFrame
  ) || mindmapTreesHaveSameCrossNodeState(currentRoot, remoteRoot)
  if (hasActiveAssociativeLineEditor) {
    const sourceUid = getRuntimeMindmapNodeUid(associativeLine.activeLine[3])
    const targetUid = getRuntimeMindmapNodeUid(associativeLine.activeLine[4])
    if (sourceUid && targetUid) {
      targets.push({
        kind: 'associative-line',
        identity: `relation:${sourceUid}:${targetUid}`,
        editor: associativeLine,
        retained: crossNodeStateRetained
          && mindmapTreeContainsAssociativeLine(remoteRoot, sourceUid, targetUid),
        requiresCommit: forceCommit,
      })
    }
  }

  if (activeOuterFrame) {
    const memberNodes = outerFrame.getRangeNodeList?.(
      activeOuterFrame.node,
      activeOuterFrame.range,
    ) || []
    const memberUids = memberNodes.map(getRuntimeMindmapNodeUid).filter(Boolean)
    const groupUid = String(
      memberNodes[0]?.getData?.('outerFrame')?.groupId || '',
    ).trim()
    if (memberUids.length > 0) {
      targets.push({
        kind: 'outer-frame',
        identity: `outer-frame:${groupUid || memberUids.join(',')}`,
        editor: outerFrame,
        retained: crossNodeStateRetained
          && mindmapTreeContainsExactOuterFrame(remoteRoot, groupUid, memberUids),
        requiresCommit: forceCommit,
      })
    }
  }

  return targets
}

function hideProtectedActiveEditors(targets) {
  let succeeded = true
  for (const target of targets) {
    try {
      target.editor?.hideEditTextBox?.()
    } catch (error) {
      succeeded = false
      console.warn(`提交脑图${target.kind}活动编辑器失败:`, error)
    }
  }
  return succeeded
}

function captureProtectedDocumentWithActiveEditorInput(targetMindMap) {
  const protectedDocument = cloneRequestPayload(getCurrentDocument())
  if (targetMindMap !== mindMap.value) return protectedDocument

  const snapshots = []
  const crossNodeSnapshots = []
  const appendSnapshot = (nodeUid, readText, richText) => {
    const normalizedUid = String(nodeUid || '').trim()
    if (!normalizedUid || typeof readText !== 'function') return
    try {
      const text = readText()
      if (typeof text !== 'string') return
      snapshots.push({ nodeUid: normalizedUid, text, richText })
    } catch (error) {
      // A broken editor accessor must not turn an otherwise valid remote frame
      // into an apply failure. The model-backed text remains in the snapshot.
      console.warn('读取脑图活动编辑器内容失败:', error)
    }
  }

  const textEditor = targetMindMap?.renderer?.textEdit
  const editingNode = textEditor?.getCurrentEditNode?.()
  const editingNodeUid = getRuntimeMindmapNodeUid(editingNode)
  const richTextEditor = targetMindMap?.richText
  if (
    editingNodeUid
    && richTextEditor?.showTextEdit === true
    && richTextEditor.node === editingNode
  ) {
    appendSnapshot(editingNodeUid, () => richTextEditor.getEditText(), true)
  } else if (
    editingNodeUid
    && textEditor?.showTextEdit === true
    && textEditor.currentNode === editingNode
  ) {
    appendSnapshot(editingNodeUid, () => textEditor.getEditText(), undefined)
  }

  const outlineEditor = outlineEditRef.value?.getActiveTextEditor?.()
  appendSnapshot(
    outlineEditor?.nodeUid,
    outlineEditor?.getEditText,
    outlineEditor?.richText,
  )

  const associativeLine = targetMindMap?.associativeLine
  if (
    associativeLine?.showTextEdit === true
    && Array.isArray(associativeLine.activeLine)
  ) {
    const sourceNode = associativeLine.activeLine[3]
    const targetNode = associativeLine.activeLine[4]
    try {
      const text = associativeLine.getEditText?.()
      if (typeof text === 'string') {
        crossNodeSnapshots.push({
          kind: 'associative-line',
          sourceUid: getRuntimeMindmapNodeUid(sourceNode),
          targetUid: getRuntimeMindmapNodeUid(targetNode),
          text,
        })
      }
    } catch (error) {
      console.warn('读取关联线活动编辑器内容失败:', error)
    }
  }

  const outerFrame = targetMindMap?.outerFrame
  const activeOuterFrame = outerFrame?.showTextEdit === true
    ? outerFrame.activeOuterFrame
    : null
  if (activeOuterFrame) {
    const memberNodes = outerFrame.getRangeNodeList?.(
      activeOuterFrame.node,
      activeOuterFrame.range,
    ) || []
    try {
      const text = outerFrame.getEditText?.()
      if (typeof text === 'string') {
        crossNodeSnapshots.push({
          kind: 'outer-frame',
          groupUid: String(
            memberNodes[0]?.getData?.('outerFrame')?.groupId || '',
          ).trim(),
          memberUids: memberNodes.map(getRuntimeMindmapNodeUid).filter(Boolean),
          text,
        })
      }
    } catch (error) {
      console.warn('读取外框活动编辑器内容失败:', error)
    }
  }

  applyMindmapActiveEditorTextSnapshots(protectedDocument, snapshots)
  return applyMindmapActiveCrossNodeEditorSnapshots(
    protectedDocument,
    crossNodeSnapshots,
  )
}

function protectActiveTextEditorBeforeRemoteDocumentApply(
  remoteRoot,
  targetMindMap,
  remoteDocument = null,
) {
  if (
    targetMindMap !== mindMap.value
    || terminalState
    || isReadonly.value
    || protectingActiveEditorFromRemoteDelete
  ) return false
  // Command.addHistory 是节流任务。普通新增、移动、样式或删除命令可能已经
  // 改完运行时树，但 data_change_detail 尚未派发。远端权威应用会取消这个
  // 定时器，因此必须先同步冲刷；一旦产生本地操作，当前 prepared remote
  // tree 已经过期，应让 Yjs 基于刚合入的本地增量重新构建下一帧。
  const queuedChangeVersion = draftProtection.getChangeVersion()
  const queuedHistoryCommitted = (
    targetMindMap.command?.flushPendingHistory?.() === true
  )
  if (
    queuedHistoryCommitted
    || draftProtection.getChangeVersion() !== queuedChangeVersion
  ) return 'local-edit-committed'
  const protectionTargets = collectActiveEditorProtectionTargets(
    remoteRoot,
    targetMindMap,
    mindmapDocumentRequiresFullRuntimeReplacement(
      targetMindMap,
      remoteDocument,
    ),
  )
  if (protectionTargets.length === 0) return false
  // 远端只改了其他节点时，增量渲染不会替换当前节点实例；保持编辑框和
  // 光标不动并立即更新其他节点。异步准入已经在 TextEdit 内按持久 UID
  // 重新解析当前实例，因此不能再为了本地文本框把整份远端文档无限积压。
  const impactedTargets = protectionTargets.filter(
    target => !target.retained || target.requiresCommit === true,
  )
  if (impactedTargets.length === 0) return false
  const removedImpactedTargets = impactedTargets.filter(target => !target.retained)
  if (removedImpactedTargets.length === 0) {
    const previousChangeVersion = draftProtection.getChangeVersion()
    const editorsCommitted = hideProtectedActiveEditors(impactedTargets)
    // 所有浮层编辑器都只会把最终命令放入 Command 的节流历史队列。
    // 远端树会立即覆盖画布，因此必须在比较 changeVersion 前同步派发
    // 本地明细并更新 Yjs。若某个编辑器关闭失败，也让旧 prepared tree
    // 失效，保留当前 DOM 给用户再次触发提交。
    targetMindMap.command?.flushPendingHistory?.()
    return (
      !editorsCommitted
      || draftProtection.getChangeVersion() !== previousChangeVersion
    )
      ? 'local-edit-committed'
      : false
  }

  // 远端已经删除节点、关联线或外框，本地浮层最后的字符尚未进入模型。
  // 这里必须禁止 hideEditTextBox 生成普通 Yjs/HTTP 操作，否则会在远端
  // 应用调用栈内把已删除实体再次广播出去；只提交到临时树并保存独立草稿。
  protectingActiveEditorFromRemoteDelete = true
  let fallbackSaved = false
  const protectionIdentity = createRemoteDeletedEditorProtectionIdentity(
    removedImpactedTargets.map(target => target.identity).sort().join('|'),
    contentRevision,
  )
  try {
    hideProtectedActiveEditors(impactedTargets)
    // 在删除保护门闩内同步消耗节流任务：当前树会被保存为
    // 独立草稿，但不能在门闩释放后把已删实体当成普通编辑重播。
    targetMindMap.command?.flushPendingHistory?.()
    const options = createAutomaticConflictDraftOptions(
      getCurrentDocument(),
      contentRevision,
      protectionIdentity.eventKey,
    )
    try {
      fallbackSaved = saveMindmapDraftFallbackSync(options)
    } catch (error) {
      console.warn('同步保护与远端冲突的浮层输入失败:', error)
    }
    // 耐久写入只能在前序草稿任务完成后启动；options 已在入队前冻结，因此
    // 随后应用远端树既不会改写快照，也不会绕过离开页面所等待的写队列。
    const durableSave = enqueueRequiredDraftOperation(
      () => saveMindmapDraft(options),
    ).catch((error) => {
      console.warn('持久保护与远端冲突的浮层输入失败:', error)
      return { saved: false, storage: null }
    })
    // 即使同步 localStorage 已成功，也等排队的耐久写入实际结束后再报成功。
    // 这样“已保护”严格表示完整持久化流程已经落定；两层都失败则明确报错。
    void durableSave.then((result) => {
      notifyRemoteDeletedEditorProtectionResult(
        protectionIdentity.notificationKey,
        result?.saved === true || fallbackSaved,
      )
    })
  } catch (error) {
    console.warn('保护与远端冲突的活动输入失败:', error)
    notifyRemoteDeletedEditorProtectionResult(
      protectionIdentity.notificationKey,
      false,
    )
  } finally {
    protectingActiveEditorFromRemoteDelete = false
  }

  return 'protected-remote-delete'
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

function isRecoveryStructureWriteBlocked() {
  return Boolean(
    resolvingStaleState
    || authoritativeReloadInProgress
    || authoritativeReloadRequired
    || pendingAutomaticConflictRecovery
    || pendingRemoteDocumentReset
  )
}

function isMindmapStructureWriteBlocked() {
  return Boolean(
    isRecoveryStructureWriteBlocked()
    || yjsSync?.isStructureWriteBlocked?.()
  )
}

function refreshStructureWriteBlockedState() {
  const nextBlocked = isMindmapStructureWriteBlocked()
  if (structureWriteBlocked.value !== nextBlocked) {
    structureWriteBlocked.value = nextBlocked
  }
  return nextBlocked
}

function setAuthoritativeReloadRequiredState(required) {
  authoritativeReloadRequired = required === true
  refreshStructureWriteBlockedState()
}

function setAuthoritativeReloadInProgress(inProgress) {
  authoritativeReloadInProgress = inProgress === true
  refreshStructureWriteBlockedState()
}

function setPendingAutomaticConflictRecovery(recovery) {
  pendingAutomaticConflictRecovery = recovery || null
  refreshStructureWriteBlockedState()
  return pendingAutomaticConflictRecovery
}

function setPendingRemoteDocumentReset(reset) {
  pendingRemoteDocumentReset = reset || null
  refreshStructureWriteBlockedState()
  return pendingRemoteDocumentReset
}

function setResolvingStaleState(resolving) {
  resolvingStaleState = resolving === true
  refreshStructureWriteBlockedState()
}

function installRecoveryStructureCommandGuard(activeMindMap) {
  if (!activeMindMap || typeof activeMindMap.execCommand !== 'function') return false
  const execCommand = activeMindMap.execCommand.bind(activeMindMap)
  activeMindMap.execCommand = (commandName, ...args) => {
    const structureWriteBlocked = isMindmapStructureWriteBlocked()
    if (shouldBlockMindmapStructureWrite(commandName, structureWriteBlocked)) {
      activeMindMap.emit?.('readonly_command_rejected', commandName)
      return false
    }
    if (
      props.mindmapId
      && mindmapCommandStartsNodeTextEdit(commandName, args, {
        createNewNodeBehavior: activeMindMap.opt?.createNewNodeBehavior,
        activeNodeCount: Array.isArray(activeMindMap.renderer?.activeNodeList)
          ? activeMindMap.renderer.activeNodeList.length
          : 1,
      })
      && yjsSync?.canAcquireNodeEditLease?.() !== true
    ) {
      activeMindMap.emit?.(
        'node_text_edit_blocked',
        null,
        [],
        yjsSync?.getNodeEditLeaseFailureReason?.() || 'connecting',
      )
      return false
    }
    return execCommand(commandName, ...args)
  }
  return true
}

function resumePendingSaveAfterNodeEditLeaseSettles() {
  if (
    !pendingSave.value
    || isSaving.value
    || terminalState
    || isChangeTrackingSuspended()
    || isMindmapStructureWriteBlocked()
    || yjsSync?.hasActiveNodeEditLease?.()
    || yjsSync?.hasPendingNodeEditLeaseAcquire?.()
  ) return
  clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => { void saveToBackend() }, 0)
}

function createYjsSyncInstance() {
  let documentPrepareFailureNotified = false
  return new YjsMindmapSync(props.mindmapId, mindMap.value, contentRevision, {
    user: {
      id: userStore.id,
      name: userStore.nickName || userStore.name,
      avatar: userStore.avatar,
    },
    readonly: isReadonly.value,
    getDocumentData: () => normalizeMindmapDocumentData(documentData.value),
    getClientMutationId: () => pendingClientMutationId,
    getClientMutationBaseRevision: clientMutationId => (
      clientMutationId === pendingClientMutationId
        ? pendingClientMutationBaseRevision
        : null
    ),
    // HTTP 保存会推进全房间 revision。在请求冻结到响应落定之间开启新的
    // DOM 文本编辑，会让最终 Yjs 帧因旧基线被快速通道拒绝却先释放租约。
    // 该窗口 fail-closed；现有租约则让 saveToBackend 延后启动。
    canAcquireNodeEditLease: () => (
      !isReadonly.value
      && !isSaving.value
      && !activeSaveMutation
      && !isRecoveryStructureWriteBlocked()
    ),
    // 初次租约等待期间自动保存同样必须停住；结果落定后用下一轮任务恢复，
    // 让 TextEdit 先完成打开或幽灵节点补偿，再冻结 HTTP 保存快照。
    onNodeEditLeaseSettled: () => {
      refreshStructureWriteBlockedState()
      resumePendingSaveAfterNodeEditLeaseSettles()
    },
    onStructureWriteBlockedChange: () => {
      const wasBlocked = structureWriteBlocked.value
      const isBlocked = refreshStructureWriteBlockedState()
      // 租约 settled 可能恰好落在远端 prepare/apply 窗口，首次恢复会被
      // 门闩挡住。最后一个结构门闩解除时必须再次唤醒已登记的自动保存。
      if (wasBlocked && !isBlocked) {
        resumePendingSaveAfterNodeEditLeaseSettles()
      }
    },
    // 当前保存请求提交后会推进全房间 revision。它在途期间新建的下一批
    // Yjs 帧无法保证全部落在同一 revision，先仅保留本地并由紧随其后的
    // HTTP 批次权威提交，避免连续输入时被服务端误判成旧基线写入。
    canSendRealtimeMutation: () => !activeSaveMutation,
    beforeRemoteDocumentApply: protectActiveTextEditorBeforeRemoteDocumentApply,
    captureDocumentBeforeRemoteApply: captureProtectedDocumentWithActiveEditorInput,
    onDocumentApplyError: (error, context) => {
      handleRemoteDocumentApplyFailure(error, context)
    },
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
    onReadonlyChanged: (readonly) => {
      // HTTP 详情加载后、WebSocket 认证前权限可能被所有者降级。若服务端
      // 拒绝建立可写会话，必须立刻关闭编辑入口并保护本地输入，不能只让
      // Yjs 静默停止发送，否则用户会看到“能编辑但修改不会同步”。
      // 历史/导入 transition 只是交互门闩，不能掩盖服务端真正撤权。
      if (!readonly || !hasRealWritePermission() || terminalState) return
      terminateEditingSession('access-revoked', {
        message: '服务器已将当前协作会话切换为只读，编辑权限可能已变更',
      })
    },
    onContentRevision: (revision, data) => {
      const revisionAdvanced = revision > contentRevision
      if (revisionAdvanced) contentRevision = revision
      applyMindmapNodeRevisionChanges(nodeRevisionMap, data?.changedNodes)
      // 远端 revision 推进不能改写已经冻结在待保存操作里的 targetRevision。
      // 若双方修改同一节点，旧 fence 必须保留给服务端识别冲突；只有本地
      // active mutation 成功后的响应才有资格为它之后产生的操作重新定基。
      // 远端协作者推进版本且本地没有待保存操作时，当前云端/Yjs 状态
      // 已经比任何遗留草稿更新。及时清理，避免刷新时误报冲突草稿。
      if (!hasUnsavedChanges()) clearLocalDraft()
      // 只读观察者不产生可持久化 Yjs 检查点，因此每次数据库 revision
      // 推进后都用 HTTP 权威正文校准一次。实时增量仍会先展示，此补拉负责
      // 覆盖后台丢包、跨 worker 短暂降级和旧缓存隔离后的最终一致性。
      if (!hasRealWritePermission() && revisionAdvanced) {
        markAuthoritativeReloadRequired()
        scheduleAuthoritativeReload()
      }
    },
    onStaleState: (data) => {
      markAuthoritativeReloadRequired()
      void handleStaleCollaborationState(data)
    },
    onDocumentReset: (data) => {
      requestRemoteDocumentReset(data)
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
    onCommentChanged: (data) => {
      bus.emit('comment_changed', data)
    },
    onDocumentApplied: (root, meta) => {
      crossNodeOperationSnapshot = extractCrossNodeState(root)
      const protectedMetaIntents = getProtectedFileMetaIntents()
      if (
        meta
        && findConflictingMindmapFileMetaIntents(
          protectedMetaIntents,
          meta,
        ).length > 0
      ) {
        // Yjs 元数据只提供低延迟预览。同一字段发生并发写入时，不能让
        // Y.Map 的临时胜出值改写已经进入本地 HTTP 批次的用户意图；该
        // 批次保存后通过权威正文重建 Y.Doc，避免错误元数据进入检查点。
        fileMetaReconciliationRequired = true
      }
      if (meta && Object.prototype.hasOwnProperty.call(meta, 'documentData')) {
        const effectiveMeta = applyMindmapFileMetaIntents(
          meta,
          protectedMetaIntents,
        )
        documentData.value = normalizeMindmapDocumentData(effectiveMeta.documentData)
        applyMindmapDocumentConfig(mindMap.value, documentData.value)
      }
    },
  })
}

function bindYjsDetailTracking() {
  if (!yjsSync || !mindMap.value || isReadonly.value || dataChangeDetailHandler) return
  dataChangeDetailHandler = onMindmapDataChangeDetail
  mindMap.value.on('data_change_detail', dataChangeDetailHandler)
}

function startYjsSyncIfReady() {
  if (
    yjsSync
    || authoritativeReloadRequired
    || restoredLocalDraft
    || versionChangeTrackingPaused
    || versionTransitionEditingBlocked.value
    || importTransitionEditingBlocked.value
    || collaborationRestartDeferredUntilSave
    || !initialRenderReady
    || !props.mindmapId
    || !mindMap.value
    || terminalState
  ) return false
  yjsSync = createYjsSyncInstance()
  yjsSyncRef.value = yjsSync
  yjsSync.start()
  refreshStructureWriteBlockedState()
  bindYjsDetailTracking()
  return true
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

function onMindMapContainerTransitionEnd(event) {
  if (
    event.target !== mindMapContainerRef.value
    || !['left', 'right'].includes(event.propertyName)
  ) return
  // 侧栏和搜索面板通过 left/right 动画改变画布宽度。watch 中的 resize
  // 发生在动画开始时，此处在最终尺寸落定后再次同步内部 SVG，避免关闭
  // 侧栏后残留一个与侧栏等宽的空白（看起来像透明侧栏）。
  mindMap.value?.resize?.()
}

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
    // 路由切换、权限收回或开发期热更新会主动销毁尚在首帧等待中的
    // MindMap 实例。这属于正常取消，不能记录成初始化失败或让外层页面
    // 短暂闪出“重新加载”错误态。
    if (sessionCancelled(sessionController?.signal)) return
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
  window.addEventListener('focus', handleWindowFocus)
  emit('ready')
})

onBeforeUnmount(() => {
  commitActiveEditorsBeforeTermination()
  persistLocalDraftBeforeUnload()
  clearTimeout(viewSaveTimer)
  viewSaveTimer = null
  if (viewSaveRequested) void flushPendingViewSave()
  stopDraftSessionLease?.()
  stopDraftSessionLease = null
  componentMounted = false
  initialRenderReady = false
  cancelSessionAsyncWork()
  unbindBusEvents()
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('pagehide', handlePageHide)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('online', handleNetworkOnline)
  window.removeEventListener('offline', handleNetworkOffline)
  window.removeEventListener('focus', handleWindowFocus)
  if (yjsSync) {
    yjsSync.destroy()
    yjsSync = null
    yjsSyncRef.value = null
    refreshStructureWriteBlockedState()
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

function applyLoadedMindmapData(data) {
  const root = data.nodeTree || defaultData
  const layout = data.layout || 'logicalStructure'
  const normalizedTheme = normalizeServerTheme(data.theme)
  const themeTemplate = normalizedTheme.template
  const themeConfig = normalizedTheme.config
  const viewData = data.viewData || null
  const nextDocumentData = normalizeMindmapDocumentData(data.documentData)
  documentData.value = nextDocumentData
  contentRevision = data.contentRevision || 1
  markDocumentMetaSaved({
    layout,
    theme: normalizedTheme,
    view: viewData,
    documentData: nextDocumentData,
  })
  nodeRevisionMap.clear()
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
  return {
    root,
    layout,
    themeTemplate,
    themeConfig,
    viewData,
    nodeCount: Number(data.nodeCount) || 0,
    serverDocument: {
      root,
      layout,
      theme: normalizedTheme,
      view: viewData,
      documentData: nextDocumentData,
    },
  }
}

async function initMindMap(signal) {
  let root = defaultData
  let layout = 'logicalStructure'
  let themeTemplate = 'default'
  let themeConfig = {}
  let viewData = null
  let serverDocument = null
  let restoredDraftOperations = []
  const savedConfig = getMindmapLocalRuntimeConfig(actions.getConfig())
  let nodeCount = 0

  // 如果有 mindmapId，从后端加载
  if (props.mindmapId) {
    try {
      const response = await getMindmap(props.mindmapId, { signal })
      if (sessionCancelled(signal)) return
      const data = response.data
      const loaded = applyLoadedMindmapData(data)
      root = loaded.root
      layout = loaded.layout
      themeTemplate = loaded.themeTemplate
      themeConfig = loaded.themeConfig
      viewData = loaded.viewData
      nodeCount = loaded.nodeCount
      serverDocument = loaded.serverDocument
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
    ensureDraftSessionLease()
    const localDraft = await resolveLocalDraft(serverDocument, signal)
    if (sessionCancelled(signal)) return
    if (selectedAuthoritativeServerData) {
      const loaded = applyLoadedMindmapData(selectedAuthoritativeServerData)
      selectedAuthoritativeServerData = null
      root = loaded.root
      layout = loaded.layout
      themeTemplate = loaded.themeTemplate
      themeConfig = loaded.themeConfig
      viewData = loaded.viewData
      nodeCount = loaded.nodeCount
      serverDocument = loaded.serverDocument
    } else if (localDraft) {
      restoredDraftOperations = buildMindmapDocumentOperations(
        serverDocument,
        localDraft,
        nodeRevisionMap,
      )
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
    // 选中节点只展示协作者位置，不构成编辑锁。只有实际打开文本编辑器的
    // 会话才通过 editingNodeUid 提供短租约式占用。
    onlyOneEnableActiveNodeOnCooperate: false,
    onlyOneEnableTextEditOnCooperate: Boolean(props.mindmapId && !isReadonly.value),
    isStructureWriteBlocked: isMindmapStructureWriteBlocked,
    isNodeTextEditLeaseAuthoritative: () => (
      yjsSync?.usesAuthoritativeNodeEditLease?.() === true
    ),
    releaseNodeTextEditLease: nodeUid => yjsSync?.releaseNodeEditLease?.(nodeUid),
    getNodeTextEditLeaseFailureReason: () => (
      yjsSync?.getNodeEditLeaseFailureReason?.() || 'unavailable'
    ),
    beforeTextEdit: async (node) => {
      if (!props.mindmapId) return true
      return await yjsSync?.acquireNodeEditLease?.(node) === true
    },
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
  installRecoveryStructureCommandGuard(mm)
  noteContentMindMap = mm

  mm.on('readonly_command_rejected', () => {
    if (!isMindmapStructureWriteBlocked()) return
    ElMessage.info({
      message: yjsSync?.hasPendingNodeEditLeaseAcquire?.()
        ? '正在获取节点编辑权限，请稍后再修改脑图结构'
        : '正在同步云端最新版本，请稍后再修改脑图结构',
      grouping: true,
    })
  })

  mm.on('node_text_edit_blocked', (_node, users = [], reason = 'occupied') => {
    ElMessage.warning({
      message: getNodeEditLeaseBlockedMessage(reason, users),
      grouping: true,
    })
  })

  mm.on('node_text_edit_lease_lost', () => {
    // 续租失败或连接中断后立即结束所有节点文本入口；普通文本和富文本
    // 均由核心 TextEdit 收口，大纲通过 blur 提交并释放本地编辑态。
    bus.emit('closeOutlineEdit')
    mm.renderer?.textEdit?.hideEditTextBox?.()
    ElMessage.warning({
      message: '节点编辑锁已失效，已结束本次编辑，请重新尝试',
      grouping: true,
    })
  })

  mm.on('node_text_edit_end', () => {
    // 自动保存定时器若恰在 DOM 编辑期间触发，会被租约门闩延后。无论
    // 本次 blur 是否改变文本，都在释放后恢复那次已登记的保存请求。
    resumePendingSaveAfterNodeEditLeaseSettles()
  })

  mindMap.value = mm
  actions.setMindMap(mm)
  actions.setIsReadonly(isReadonly.value)
  applyMindmapDocumentConfig(mm, documentData.value)
  crossNodeOperationSnapshot = extractCrossNodeState(root)

  if (restoredLocalDraft) {
    pendingContentOperations.push(...restoredDraftOperations)
    pendingFileMetaIntents = captureMindmapFileMetaIntents(
      pendingFileMetaIntents,
      getCurrentDocument(),
      restoredDraftOperations,
    )
    if (restoredDraftOperations.length > 0) ensurePendingClientMutationId()
    setSaveStatus('pending')
    persistLocalDraft()
    // 在接入持久化 Yjs 状态前立即冻结恢复批次。网络失败时仍由保存重试链路
    // 保护草稿。首次画布完整渲染后才提交该批次，避免初始化渲染、服务器
    // 合并结果和 Yjs 首次握手同时改写同一棵运行时节点树。
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
      if (
        eventName === 'mode_change'
        && (
          rejectEditModeDuringAuthoritativeRecovery(args[0], mm)
          || rejectEditModeDuringEditingTransition(args[0], mm)
        )
      ) return
      bus.emit(eventName, ...args, mm)
    })
  })

  // Bind save events (use named functions for proper cleanup)
  if (!isReadonly.value) {
    bus.on('data_change', onBusDataChange)
    bus.on('view_data_change', onBusViewDataChange)
    // Yjs 增量同步（带反馈循环保护）
    bindYjsDetailTracking()

    // Ctrl+S manual save
    mm.keyCommand.addShortcut('Control+s', () => {
      manualSave()
    })
  }

  await waitForMindmapInitialRender(mm)
  if (sessionCancelled(signal) || mindMap.value !== mm) return
  initialRenderReady = true
  if (restoredLocalDraft) void saveToBackend()
  // 首帧之前不接入 Yjs，杜绝初始化渲染与远端状态同时替换节点树。
  startYjsSyncIfReady()
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
    // data_change 可能先于对应 data_change_detail 触发。先建立同一个保存
    // 批次，确保布局/主题/documentData 的 Yjs 更新也能和 HTTP revision
    // 精确关联，绝不以无 mutationId 的旧 revision 检查点落库。
    const clientMutationId = ensurePendingClientMutationId()
    yjsSync?.syncDocumentMeta(fullData, clientMutationId)
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

function scheduleViewSave(data) {
  if (
    !componentMounted
    || !props.mindmapId
    || isReadonly.value
    || terminalState
    || authoritativeReloadRequired
    || pendingRemoteDocumentReset
  ) return
  viewChangeVersion += 1
  // View.state / transform 都是可变嵌套对象；请求真正序列化前画布仍会继续
  // 平移缩放，因此必须在事件边界冻结完整快照，不能只复制第一层。
  pendingViewData = data && typeof data === 'object'
    ? cloneRequestPayload(data)
    : null
  viewSaveRequested = true
  clearTimeout(viewSaveTimer)
  viewSaveTimer = setTimeout(() => {
    viewSaveTimer = null
    void flushPendingViewSave()
  }, VIEW_SAVE_DELAY)
}

async function flushPendingViewSave() {
  if (viewSaveInProgress) return viewSavePromise || false
  if (!viewSaveRequested) return true
  if (!canFlushCloudChangesDuringEditingTransition()) return false
  clearTimeout(viewSaveTimer)
  viewSaveTimer = null
  viewSaveInProgress = true
  viewSaveRequested = false
  const snapshot = pendingViewData
  const snapshotViewChangeVersion = viewChangeVersion
  const snapshotContentRevision = contentRevision
  const requestGeneration = viewSaveGeneration
  const requestIsRetired = () => requestGeneration !== viewSaveGeneration
  let requestSucceeded = false
  let newerViewRequested = false
  let rejectedByNewerContentRevision = false
  const requestPromise = Promise.resolve()
    .then(() => updateMindmapView(
      props.mindmapId,
      snapshot,
      snapshotContentRevision,
    ))
    .then(() => {
      if (requestIsRetired()) return true
      requestSucceeded = true
      savedViewChangeVersion = Math.max(
        savedViewChangeVersion,
        snapshotViewChangeVersion,
      )
      return true
    })
    .catch((error) => {
      // document_reset 会推进代际并以云端视图替换本地视图。旧请求即使因
      // revision CAS 被拒绝，也不得重新排队或显示无意义的保存失败。
      if (requestIsRetired()) return true
      const serverContentRevision = Number(error?.data?.currentRevision)
      if (Number.isInteger(serverContentRevision) && serverContentRevision > 0) {
        // 视图不承载正文语义。它基于旧正文 revision 时继续排队只会与
        // 权威重载互相阻塞；采用服务器版本并丢弃当前/更新的本地视图，
        // 等完整文档回源后再接受新的平移缩放。
        rejectedByNewerContentRevision = true
        clearTimeout(viewSaveTimer)
        viewSaveTimer = null
        pendingViewData = undefined
        viewSaveRequested = false
        savedViewChangeVersion = viewChangeVersion
        raiseAuthoritativeReloadMinimumRevision(serverContentRevision)
        markAuthoritativeReloadRequired()
        return true
      }
      // 失败的最新视图继续保留为待保存状态，供手动保存、离开守卫或下一次
      // 视图变化重试；它仍不进入正文 revision、Yjs 或恢复草稿。
      newerViewRequested = viewSaveRequested
      if (!viewSaveRequested) {
        pendingViewData = snapshot
        viewSaveRequested = true
      }
      console.warn('保存脑图视图失败:', error)
      return false
    })
    .finally(() => {
      if (viewSavePromise === requestPromise) {
        viewSaveInProgress = false
        viewSavePromise = null
      }
      if (requestIsRetired()) return
      if (rejectedByNewerContentRevision) {
        if (componentMounted && !hasUnsavedChanges()) scheduleAuthoritativeReload()
        drainPendingRemoteDocumentReset()
        return
      }
      // 请求期间产生了更新视图时继续保存最新快照；单次网络失败则等待
      // 手动保存、离开页面或用户再次平移，避免固定频率重试冲击后端。
      if (
        componentMounted
        && viewSaveRequested
        && (requestSucceeded || newerViewRequested)
      ) {
        clearTimeout(viewSaveTimer)
        viewSaveTimer = setTimeout(() => {
          viewSaveTimer = null
          void flushPendingViewSave()
        }, VIEW_SAVE_DELAY)
      }
      if (
        requestSucceeded
        && authoritativeReloadRequired
        && !hasUnsavedChanges()
        && !viewSaveRequested
      ) scheduleAuthoritativeReload()
      drainPendingRemoteDocumentReset()
    })
  viewSavePromise = requestPromise
  return requestPromise
}

async function retirePendingViewSaveForAuthoritativeReload() {
  // 清除尚未发出的视图，并让在途请求的完成回调失效。后端 revision CAS
  // 决定它与已提交 reset 的线性顺序；等待结束后再 GET，保证画布采用最终值。
  viewSaveGeneration += 1
  clearTimeout(viewSaveTimer)
  viewSaveTimer = null
  viewSaveRequested = false
  pendingViewData = undefined
  const retiredRequest = viewSavePromise
  if (retiredRequest) await retiredRequest
  viewSaveRequested = false
  pendingViewData = undefined
  savedViewChangeVersion = viewChangeVersion
}

async function settlePendingViewSave(maxPasses = CLOUD_EXIT_MAX_PASSES) {
  for (let pass = 0; pass < maxPasses; pass += 1) {
    if (!viewSaveRequested && !viewSaveInProgress) return true
    clearTimeout(viewSaveTimer)
    viewSaveTimer = null
    const saved = await flushPendingViewSave()
    if (saved !== true) return false
  }
  return !viewSaveRequested && !viewSaveInProgress
}

function onBusViewDataChange(data, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, mindMap.value)) return
  if (isReadonly.value) return
  if (props.mindmapId) {
    // 跳过远程变更或暂停状态引发的本地视图变更
    if (isChangeTrackingSuspended()) return
    // 平移/缩放独立采用后写覆盖，不进入正文 revision、Yjs 或恢复草稿。
    scheduleViewSave(data)
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
  if (viewSaveRequested && !viewSaveInProgress) void flushPendingViewSave()
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

function raiseAuthoritativeReloadMinimumRevision(dataOrRevision) {
  const candidate = Number(
    dataOrRevision && typeof dataOrRevision === 'object'
      ? dataOrRevision.contentRevision ?? dataOrRevision.currentRevision
      : dataOrRevision,
  )
  if (Number.isInteger(candidate) && candidate > 0) {
    authoritativeReloadMinimumRevision = Math.max(
      authoritativeReloadMinimumRevision,
      candidate,
    )
  }
  return authoritativeReloadMinimumRevision
}

function getAuthoritativeReloadMinimumRevision(minimumContentRevision = null) {
  const requestedRevision = Number(minimumContentRevision)
  return Math.max(
    authoritativeReloadMinimumRevision,
    Number.isInteger(requestedRevision) && requestedRevision > 0
      ? requestedRevision
      : 0,
  )
}

function setAuthoritativeRecoveryEditingBlocked(blocked) {
  const nextBlocked = blocked === true
  if (authoritativeRecoveryEditingBlocked.value === nextBlocked) return false
  authoritativeRecoveryEditingBlocked.value = nextBlocked
  actions.setIsReadonly(isReadonly.value)
  mindMap.value?.setMode?.(isReadonly.value ? 'readonly' : 'edit')
  return true
}

function syncEditingBlockedMode() {
  actions.setIsReadonly(isReadonly.value)
  mindMap.value?.setMode?.(isReadonly.value ? 'readonly' : 'edit')
}

function setVersionTransitionEditingBlocked(blocked) {
  const nextBlocked = blocked === true
  if (versionTransitionEditingBlocked.value === nextBlocked) return false
  if (nextBlocked) editingTransitionGeneration += 1
  versionTransitionEditingBlocked.value = nextBlocked
  syncEditingBlockedMode()
  return true
}

function setImportTransitionEditingBlocked(blocked) {
  const nextBlocked = blocked === true
  if (importTransitionEditingBlocked.value === nextBlocked) return false
  if (nextBlocked) editingTransitionGeneration += 1
  importTransitionEditingBlocked.value = nextBlocked
  syncEditingBlockedMode()
  return true
}

function hasActiveEditingTransition() {
  return versionTransitionEditingBlocked.value || importTransitionEditingBlocked.value
}

function resumeAfterEditingTransition() {
  if (terminalState || !componentMounted) return false
  if (authoritativeReloadRequired) {
    if (hasUnsavedChanges() || viewSaveRequested || viewSaveInProgress) {
      if (!isSaving.value && !saveRetryTimer && !isBrowserOffline()) {
        clearTimeout(autoSaveTimer)
        autoSaveTimer = setTimeout(() => { void saveToBackend() }, 0)
      }
    } else {
      // 旧 reload 被本次 transition generation 取消时，Yjs 可能已经停止。
      // 保持权威 readonly 并显式重排 GET；formal save 不会发 change-tracking，
      // 因而不能只依赖预览退出回调恢复这条链路。
      setAuthoritativeRecoveryEditingBlocked(true)
      scheduleAuthoritativeReload()
    }
    return false
  }
  if (collaborationRestartDeferredUntilSave) {
    if (
      hasUnsavedChanges()
      && !isSaving.value
      && !saveRetryTimer
      && !isBrowserOffline()
    ) {
      clearTimeout(autoSaveTimer)
      autoSaveTimer = setTimeout(() => { void saveToBackend() }, 0)
    }
    return false
  }
  return startYjsSyncIfReady()
}

function rejectEditModeDuringAuthoritativeRecovery(mode, activeMindMap) {
  if (!authoritativeRecoveryEditingBlocked.value || mode !== 'edit') return false
  // 可编辑用户仍能看到导航栏的“编辑模式”开关。门闩期间若它尝试直接
  // 调用 MindMap#setMode，必须同步恢复只读，不能留下一个可修改旧树的窗口。
  actions.setIsReadonly(true)
  activeMindMap?.setMode?.('readonly')
  return true
}

function rejectEditModeDuringEditingTransition(mode, activeMindMap) {
  if (
    mode !== 'edit'
    || (
      !versionTransitionEditingBlocked.value
      && !importTransitionEditingBlocked.value
    )
  ) return false
  actions.setIsReadonly(true)
  activeMindMap?.setMode?.('readonly')
  return true
}

async function enterAuthoritativeApplyFailureRecovery(
  protectedDocument,
  { recoveryKind = 'sync', eventKey = 'authoritative-apply' } = {},
) {
  // applyAuthoritativeMindmapDocument/setFullData 可能在半棵树已经渲染后抛错。
  // 先同步冻结当前 runtime，任何草稿 IO 都只能发生在只读门闩之后。
  setAuthoritativeRecoveryEditingBlocked(true)
  markAuthoritativeReloadRequired()
  clearTimeout(autoSaveTimer)
  if (recoveryKind) {
    saveRecoveryKind.value = recoveryKind
    setSaveStatus('error')
  }
  const result = await preserveAutomaticConflictDraft(
    protectedDocument,
    contentRevision,
    `${eventKey}-${createMutationId()}`,
    { syncFallback: true },
  )
  if (result?.saved !== true) {
    ElNotification.error({
      title: '画布刷新失败且安全副本未完成',
      message: '请保持页面开启并点击保护修改，成功重新加载前画布将保持只读',
    })
  }
  return result?.saved === true
}

function abandonPendingContentForAuthoritativeReload() {
  clearTimeout(autoSaveTimer)
  clearTimeout(saveRetryTimer)
  saveRetryTimer = null
  saveRetryAttempt = 0
  retryNoticeShown = false
  activeSaveMutation = null
  activeSaveDocumentDataGeneration = null
  pendingContentOperations = []
  clearPendingClientMutation()
  clearFileMetaIntentState()
  documentMetaBuffer.clear()
  pendingSave.value = false
}

function handleRemoteDocumentApplyFailure(error, context = {}) {
  const failedSync = context?.sourceSync
  const targetMindMap = context?.targetMindMap
  if (
    terminalState
    || remoteDocumentApplyRecoveryPromise
    || (failedSync && failedSync !== yjsSync)
    || (targetMindMap && targetMindMap !== mindMap.value)
  ) return

  console.error('应用远端协作画布失败:', error)
  // Yjs 在调用 applyAuthoritativeMindmapDocument 前冻结这份完整文档；即使
  // renderer 已半应用后抛错，也不能退回读取当前 runtime 作为保护快照。
  const protectedDocument = context?.protectedDocument || getCurrentDocument()
  const draftRecovery = enterAuthoritativeApplyFailureRecovery(
    protectedDocument,
    {
      eventKey: `remote-yjs-apply-${createMutationId()}`,
    },
  )
  // enterAuthoritativeApplyFailureRecovery 在首次 await 前同步建立 readonly
  // 门闩。随后立即销毁失败 Y.Doc，禁止 0ms render-release 再开放半棵树。
  stopCurrentCollaborationSource()

  const operation = (async () => {
    await draftRecovery
    if (terminalState || !componentMounted || !mindMap.value) return false
    await retirePendingViewSaveForAuthoritativeReload()
    if (terminalState || !componentMounted || !mindMap.value) return false
    // 失败的 Yjs apply 可能与尚未提交的本地批次交错。前置完整快照已使用
    // 独立 conflict session 保存，丢弃旧 lineage 的 intents 后才能让权威
    // GET 穿过 requireClean 栅栏；草稿不会被成功回源清理当前 session 时误删。
    abandonPendingContentForAuthoritativeReload()
    saveRecoveryKind.value = 'sync'
    setSaveStatus('syncing')
    scheduleAuthoritativeReload()
    return true
  })().catch(recoveryError => {
    if (!terminalState && componentMounted) {
      console.error('远端协作画布恢复失败:', recoveryError)
      saveRecoveryKind.value = 'sync'
      setSaveStatus('error')
      scheduleNextAuthoritativeReload()
    }
    return false
  })
  remoteDocumentApplyRecoveryPromise = operation
  void operation.finally(() => {
    if (remoteDocumentApplyRecoveryPromise === operation) {
      remoteDocumentApplyRecoveryPromise = null
    }
  })
}

function markAuthoritativeReloadRequired() {
  if (!authoritativeReloadRequired) {
    authoritativeReloadAttempt = 0
    authoritativeReloadNoticeShown = false
    // 历史预览只允许恢复它进入时捕获的同一权威会话。预览期间首次出现
    // stale/reload 要求时推进代际，让退出流程跳过旧树和旧 Yjs 实例。
    authoritativeResetGeneration.value += 1
  }
  setAuthoritativeReloadRequiredState(true)
}

function resolveAuthoritativeReload() {
  // 保存响应、版本恢复和协作重载都可能尝试结束同一恢复状态。若处理期间
  // 又收到了更高 stale revision，较旧调用方无权清除门闩；它只需返回，
  // 当前保存/恢复链路随后会继续执行带新下界的权威 GET。
  if (
    !terminalState
    && contentRevision < authoritativeReloadMinimumRevision
  ) {
    setAuthoritativeReloadRequiredState(true)
    return false
  }
  clearTimeout(authoritativeReloadTimer)
  authoritativeReloadTimer = null
  authoritativeReloadAttempt = 0
  setAuthoritativeReloadInProgress(false)
  authoritativeReloadNoticeShown = false
  setAuthoritativeReloadRequiredState(false)
  authoritativeReloadMinimumRevision = 0
  if (saveRecoveryKind.value === 'sync') saveRecoveryKind.value = ''
  return true
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

async function performAuthoritativeReload({ allowDuringEditingTransition = false } = {}) {
  if (!authoritativeReloadRequired) return true
  if (hasActiveEditingTransition() && !allowDuringEditingTransition) return false
  if (isSaving.value) {
    // 远端 apply 失败可能在一个 HTTP 保存仍在途时销毁旧 Y.Doc。保护快照
    // 落盘后会废弃该旧批次；等请求 finally 退出再重试权威 GET，不能让
    // 一次过早的 0ms 尝试永久吃掉唯一重载定时器。
    scheduleAuthoritativeReload(250)
    return false
  }
  if (
    terminalState
    || !componentMounted
    || authoritativeReloadInProgress
    || versionChangeTrackingPaused
    || hasUnsavedChanges()
    || viewSaveRequested
    || viewSaveInProgress
  ) return false

  setAuthoritativeReloadInProgress(true)
  if (saveRecoveryKind.value !== 'draft') setSaveStatus('syncing')
  try {
    const reloaded = await reloadLatestServerDocument({
      requireClean: true,
      minimumContentRevision: authoritativeReloadMinimumRevision,
      allowDuringEditingTransition,
    })
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
    setAuthoritativeReloadInProgress(false)
    drainPendingRemoteDocumentReset()
  }
}

async function recoverFromSaveRevisionConflict(
  conflictData,
  localFullData,
  recoveryState = {},
) {
  setPendingAutomaticConflictRecovery(null)
  clearTimeout(autoSaveTimer)
  // HTTP 批次在发出前已经冻结了用户真正提交的文档。冲突响应到达之前，
  // 远端 Yjs 预览可能已在同字段竞争中覆盖运行时画布，因此必须在任何
  // await/blur 之前先抓住被拒绝批次；重试则沿用首次抓取的快照。
  const rejectedMutationSnapshot = captureRejectedMindmapMutationSnapshot({
    mutation: activeSaveMutation,
    fallbackDocument: localFullData,
    previousSnapshot: recoveryState.rejectedMutationSnapshot,
    fallbackBaseRevision: recoveryState.localContentRevision || contentRevision,
    fallbackContentChangeVersion: draftProtection.getChangeVersion(),
  })
  commitActiveEditorsBeforeTermination()
  await nextTick()
  if (sessionCancelled(sessionController?.signal) || !mindMap.value) return false
  // 运行时文档只用于额外保护批次冻结后产生的输入，绝不能反向替换上面的
  // rejectedMutationSnapshot；它可能已经包含协作者的临时 Yjs 胜出值。
  localFullData = getCurrentDocument()
  const localContentRevision = Number(recoveryState.localContentRevision)
    || rejectedMutationSnapshot?.baseRevision
    || contentRevision
  const currentDraftChangeVersion = draftProtection.getChangeVersion()
  let protectedDraftChangeVersion = Number.isSafeInteger(
    recoveryState.protectedDraftChangeVersion,
  ) ? recoveryState.protectedDraftChangeVersion : null
  const createDeferredRecoveryState = (protectedVersion) => ({
    conflictData,
    localContentRevision,
    protectedDraftChangeVersion: protectedVersion,
    rejectedMutationSnapshot,
  })
  if (rejectedMutationSnapshot && protectedDraftChangeVersion !== currentDraftChangeVersion) {
    const mutationKey = rejectedMutationSnapshot.clientMutationId || 'local'
    const draftsToProtect = [{
      document: rejectedMutationSnapshot.document,
      eventKey: `rejected-${mutationKey}`,
    }]
    const hasPostFreezeLocalChanges = (
      Number.isSafeInteger(rejectedMutationSnapshot.contentChangeVersion)
      && currentDraftChangeVersion !== rejectedMutationSnapshot.contentChangeVersion
    )
    if (
      hasPostFreezeLocalChanges
      && localFullData
      && !areMindmapDraftDocumentsEqual(
        rejectedMutationSnapshot.document,
        localFullData,
      )
    ) {
      // 冻结后的后续输入属于下一批，不能覆盖被拒绝批次的独立草稿；按
      // changeVersion 分键保存，等待期间再有输入时由下方代际栅栏重试。
      draftsToProtect.push({
        document: localFullData,
        eventKey: `pending-${mutationKey}-v${currentDraftChangeVersion}`,
      })
    }
    let allDraftsSaved = true
    for (const draft of draftsToProtect) {
      const draftResult = await preserveAutomaticConflictDraft(
        draft.document,
        localContentRevision,
        draft.eventKey,
      )
      if (draftResult?.saved !== true) {
        allDraftsSaved = false
        break
      }
    }
    if (!allDraftsSaved) {
      setPendingAutomaticConflictRecovery(createDeferredRecoveryState(null))
      saveRecoveryKind.value = 'retry'
      setSaveStatus('error')
      ElNotification.error({
        title: '未能安全切换到云端版本',
        message: '本地冲突内容仍保留在当前画布，请保持页面开启并点击“重试保存”',
      })
      return false
    }
    protectedDraftChangeVersion = currentDraftChangeVersion
  }
  // 视图不承载正文语义。冲突已证明该视图建立在过期 revision 上；让后端
  // CAS 决定在途请求的线性顺序并将本地视图代际作废，避免旧视图保存先于
  // currentRevision 更新而形成永久重试环。
  await retirePendingViewSaveForAuthoritativeReload()
  // 草稿与视图请求等待期间，用户可能又在尚未 blur 的 DOM 编辑器里输入。
  // 再提交一次后才检查代际，确保这段等待窗口里的最后字符要么进入下一轮
  // 独立草稿，要么已经包含在本轮受保护快照中。
  commitActiveEditorsBeforeTermination()
  await nextTick()
  if (sessionCancelled(sessionController?.signal) || !mindMap.value) return false
  if (draftProtection.getChangeVersion() !== protectedDraftChangeVersion) {
    // IndexedDB 写入期间用户仍可能继续编辑。此时刚保存的快照只覆盖旧版本，
    // 不能清空新产生的操作或加载云端正文；下一轮会先保护最新画布再恢复。
    setPendingAutomaticConflictRecovery(createDeferredRecoveryState(
      protectedDraftChangeVersion,
    ))
    saveRecoveryKind.value = 'retry'
    return false
  }
  // 从这里开始会丢弃被拒绝批次的 intent/Y.Doc。若随后的 reset、GET、插件
  // 准备或渲染失败，旧 runtime 只能用于查看，绝不能再登记为新 revision 的
  // 保存意图。reloadLatestServerDocument 完整应用权威正文后负责解除门闩。
  setAuthoritativeRecoveryEditingBlocked(true)
  // 只有服务端能判定被拒 mutation 的实时帧是否污染房间。旧响应缺少该
  // 标志时只重建当前客户端，不能根据客户端帧数推断并打断全房间。
  const requiresCollaborationReset = conflictData?.requiresCollaborationReset === true
  const currentRevision = Number(conflictData?.currentRevision)
  if (Number.isInteger(currentRevision) && currentRevision > 0) {
    contentRevision = Math.max(contentRevision, currentRevision)
  }
  // 被拒绝批次的 Y.Doc 不能继续作为新 revision 的检查点。即使服务端确认
  // 没有实时帧需要全房间 reset，本客户端也必须先丢弃旧 Doc 再读取权威树。
  stopCurrentCollaborationSource()
  clearSaveRetryState()
  activeSaveMutation = null
  activeSaveDocumentDataGeneration = null
  clearPendingClientMutation()
  pendingContentOperations = []
  clearFileMetaIntentState()
  documentMetaBuffer.clear()
  conflictBlocked = false
  blockedConflictData = null
  pendingSave.value = false
  setSaveStatus('syncing')
  const recoveryDraftChangeVersion = draftProtection.getChangeVersion()
  const recoveryViewChangeVersion = viewChangeVersion
  let collaborationResetCompleted = !requiresCollaborationReset
  try {
    // 只有服务器明确判定“被拒绝的 mutation 已经广播过实时帧”时才推进
    // 全房间协作 epoch。纯 HTTP stale/conflict 只重载当前客户端，不能打断
    // 其他浏览器正在进行的正常编辑。
    if (requiresCollaborationReset) {
      const resetResponse = await resetCurrentCollaborationToCloud(contentRevision)
      collaborationResetCompleted = true
      const resetRevision = Number(resetResponse?.data?.contentRevision)
      if (Number.isInteger(resetRevision) && resetRevision > 0) {
        contentRevision = Math.max(contentRevision, resetRevision)
      }
    }
    const reloaded = await reloadLatestServerDocument({
      preserveLocalDraft: false,
      requireClean: false,
      expectedDraftChangeVersion: recoveryDraftChangeVersion,
      expectedViewChangeVersion: recoveryViewChangeVersion,
    })
    if (reloaded) {
      resolveAuthoritativeReload()
      ElMessage.success('云端版本已有更新，已同步最新内容；原修改保留在草稿中心')
      return true
    }
    markAuthoritativeReloadRequired()
    scheduleNextAuthoritativeReload()
    return false
  } catch (error) {
    if (sessionCancelled(sessionController?.signal)) return false
    console.warn('自动同步云端最新协作版本失败:', error)
    if (!collaborationResetCompleted) {
      // 必需的重置请求失败时不能直接走普通重载，否则仍会重新接入旧检查点。
      // 保留明确的无弹窗重试入口，并继续让本地草稿承担兜底保护。
      setPendingAutomaticConflictRecovery(createDeferredRecoveryState(
        protectedDraftChangeVersion,
      ))
      saveRecoveryKind.value = 'retry'
      return false
    }
    markAuthoritativeReloadRequired()
    scheduleNextAuthoritativeReload()
    return false
  }
}

async function saveToBackend() {
  if (
    terminalState
    || !mindMap.value
    || !canFlushCloudChangesDuringEditingTransition()
  ) return
  if (isChangeTrackingSuspended()) return false
  // 节点租约必须覆盖“最终文本已进入可发送 Yjs”这一线性化点。保存请求
  // 在途会暂时关闭新实时批次，所以现有编辑结束前不能冻结 HTTP mutation。
  if (
    yjsSync?.hasActiveNodeEditLease?.()
    || yjsSync?.hasPendingNodeEditLeaseAcquire?.()
  ) {
    pendingSave.value = true
    return
  }
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
      const hasPendingRealtimeMutation = Boolean(pendingClientMutationId)
      const clientMutationId = pendingClientMutationId || createMutationId()
      const mutationBaseRevision = hasPendingRealtimeMutation
        ? (
            pendingClientMutationBaseRevision
            || yjsSync?.getLocalMutationBaseRevision?.(clientMutationId)
            || contentRevision
          )
        : contentRevision
      const yjsUpdateCount = hasPendingRealtimeMutation
        ? (yjsSync?.sealLocalMutation?.(clientMutationId) || 0)
        : 0
      const yjsDeliveryMode = hasPendingRealtimeMutation
        ? (yjsSync?.getLocalMutationDeliveryMode?.(clientMutationId) || 'reload')
        : 'sequenced'
      // 只有冻结批次时才能判断最终净操作是否为空。过早插入 confirm 会在
      // 防抖窗口后续又发生真实编辑时把哨兵和内容操作错误混入同一请求。
      const semanticOperations = pendingContentOperations.filter(
        operation => operation?.type !== COLLABORATION_SYNC_CONFIRM_OPERATION,
      )
      const shouldConfirmRealtimeOnly = (
        semanticOperations.length === 0
        && yjsUpdateCount > 0
      )
      const operations = shouldConfirmRealtimeOnly
        ? [{ type: COLLABORATION_SYNC_CONFIRM_OPERATION }]
        : semanticOperations
      const mutationDocument = applyMindmapOperationIntents(
        fullData,
        semanticOperations,
      )
      const frozenDocumentDataGeneration = documentDataGeneration
      activeSaveMutation = createMindmapSaveMutation({
        clientMutationId,
        baseRevision: mutationBaseRevision,
        operations,
        document: mutationDocument,
        viewChangeVersion,
        contentChangeVersion: draftProtection.getChangeVersion(),
        yjsUpdateCount,
        yjsDeliveryMode,
      })
      activeSaveDocumentDataGeneration = activeSaveMutation
        ? frozenDocumentDataGeneration
        : null
      if (activeSaveMutation) {
        pendingContentOperations = []
        // 文件域的最终值已经随不可变 mutation 冻结。此后发生的新编辑会
        // 重新写入 pendingFileMetaIntents，不能与在途批次共享可变引用。
        pendingFileMetaIntents = {}
        if (pendingClientMutationId === clientMutationId) clearPendingClientMutation()
      } else if (hasPendingRealtimeMutation) {
        // 某些核心事件会产生操作明细，但写入 Y.Doc 后最终是 no-op；此时
        // 既没有 HTTP 批次也不会收到 revision 广播。主动释放该 mutation，
        // 否则它会永久阻止后续安全检查点。
        yjsSync?.confirmLocalMutation?.(clientMutationId)
      }
    }
    let mutation = activeSaveMutation
    if (!mutation) {
      // 本轮修改可能已被净操作折叠为“回到原状态”。同步清理为最终树保存
      // 的临时草稿和 mutationId，避免刷新后把已撤销内容误报为未同步草稿。
      clearPendingClientMutation()
      clearLocalDraft(draftClearBeforeUpdatedAt)
      clearRestoredDraft()
      draftProtection.markClean()
      setSaveStatus('saved')
      return true
    }
    // WebSocket revision 广播可能先于 HTTP 响应返回。显式登记本地批次，
    // 避免“确认已保存但没有远端回环增量”的保护定时器把自己的保存误判
    // 为丢包；当前画布天然已经包含这个批次。
    yjsSync?.markLocalMutation?.(mutation.clientMutationId)
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
    const responseRevision = Number(response.data.contentRevision)
    if (!Number.isInteger(responseRevision) || responseRevision <= 0) {
      throw new Error('脑图保存响应缺少有效的内容版本')
    }
    const responseSuperseded = responseRevision < contentRevision
    const rebasedAcrossRemoteRevision = mutation.rebaseAttempts > 0
    const ordinaryAuthoritativeReloadRequired = (
      response.data.authoritativeReloadRequired === true
      && response.data.concurrentMerge !== true
    )
    const requiresFileMetaReconciliation = fileMetaReconciliationRequired
    const authoritativeResponseDocumentData = normalizeMindmapDocumentData(
      response.data.documentData === undefined
        ? mutation.document.documentData
        : response.data.documentData
    )
    if (!responseSuperseded) {
      contentRevision = Math.max(contentRevision, responseRevision)
      const hasNewerDocumentDataChange = (
        activeSaveDocumentDataGeneration === null
        || documentDataGeneration !== activeSaveDocumentDataGeneration
      )
      if (!hasNewerDocumentDataChange) {
        documentData.value = authoritativeResponseDocumentData
        applyMindmapDocumentConfig(mindMap.value, documentData.value)
      }
      if (response.data.nodeRevisions) {
        nodeRevisionMap.clear()
        for (const [nodeUid, revision] of Object.entries(response.data.nodeRevisions)) {
          nodeRevisionMap.set(nodeUid, revision)
        }
      } else {
        applyMindmapNodeRevisionChanges(nodeRevisionMap, response.data.changedNodes)
      }
      pendingContentOperations = rebaseMindmapOperationTargetRevisions(
        pendingContentOperations,
        nodeRevisionMap,
      )
    }
    if (
      !responseSuperseded
      && !rebasedAcrossRemoteRevision
      && response.data.concurrentMerge !== true
      && !requiresFileMetaReconciliation
    ) {
      // activeSaveMutation 冻结后产生的下一批操作没有走实时通道，仍记录着
      // 前一 revision。当前普通响应证明服务器已按顺序提交了上一批，可将
      // 这批完全未发送的操作推进到新基线，避免连续输入撞上自己的修改。
      advancePendingUnsentMutationBaseRevision(responseRevision)
    }
    if (
      responseSuperseded
      || rebasedAcrossRemoteRevision
      || ordinaryAuthoritativeReloadRequired
      || requiresFileMetaReconciliation
    ) {
      // HTTP 响应可能落后于已经消费的 WS revision；自动 rebase 也只证明
      // 本地操作可重放，不证明客户端已经应用中间云端树。两者都必须保留
      // 单调栅栏并重新拉取权威正文，禁止旧响应覆盖当前画布。
      // 响应等待期间可能已有下一轮 DOM 输入。先同步提交/flush，再销毁
      // Y.Doc；新增 pending 操作会让后续权威 GET 等它保存完成后再应用。
      commitActiveEditorsBeforeTermination()
      stopCurrentCollaborationSource()
      if (requiresFileMetaReconciliation) {
        // 保留服务端刚接受的本地文件值，直到权威 GET 真正落到画布。否则
        // 用户在重载前继续编辑节点时，会再次从旧 Yjs 预览读到远端值，
        // 并把它误记为一次新的本地 file 更新。
        reconcilingFileMetaIntents = captureMindmapFileMetaIntents(
          reconcilingFileMetaIntents,
          mutation.document,
          mutation.operations,
        )
        raiseAuthoritativeReloadMinimumRevision(responseRevision)
      }
      markAuthoritativeReloadRequired()
      ElNotification.info({
        title: '云端版本已继续更新',
        message: requiresFileMetaReconciliation
          ? '本地文档设置已保存，正在用云端正文校准并发预览状态'
          : ordinaryAuthoritativeReloadRequired
            ? '本次修改已保存；实时帧未能完整确认，正在加载云端完整画布'
            : '本次修改已保存，正在加载不低于当前版本的完整画布',
      })
    } else if (response.data.concurrentMerge) {
      // 合并响应里的 revision 与完整权威树是一个原子基线。旧 Y.Doc 不能
      // 先被标记为新 revision；否则树渲染失败或仍有后续本地编辑时，它会
      // 把旧/不完整状态作为新检查点继续传播。
      commitActiveEditorsBeforeTermination()
      const hasNewerLocalChanges = (
        pendingContentOperations.length > 0
        || Boolean(pendingClientMutationId)
        || draftProtection.getChangeVersion() !== mutation.contentChangeVersion
        || documentDataGeneration !== activeSaveDocumentDataGeneration
        || viewSaveRequested
        || viewSaveInProgress
        || viewChangeVersion > mutation.viewChangeVersion
      )
      stopCurrentCollaborationSource()
      if (hasNewerLocalChanges || !response.data.nodeTree) {
        markAuthoritativeReloadRequired()
        ElNotification.info({
          title: '协作内容已在云端合并',
          message: '正在先保存当前后续修改，完成后会安全同步最新画布',
        })
      } else {
        const activeMindMap = mindMap.value
      const prepareDraftChangeVersion = draftProtection.getChangeVersion()
      const prepareViewChangeVersion = viewChangeVersion
      const prepareDocumentDataGeneration = documentDataGeneration
      const preparePendingMutationId = pendingClientMutationId
      const mergedTheme = normalizeServerTheme(
        response.data.theme || mutation.document.theme,
      )
      const mergedDocument = {
        root: response.data.nodeTree,
        layout: response.data.layout || mutation.document.layout,
        theme: mergedTheme,
        view: response.data.viewData ?? mutation.document.view,
        documentData: documentData.value,
      }
        const protectedDocumentBeforeMergeApply = getCurrentDocument()
        let mergedDocumentApplied = false
        try {
          await ensureMindmapDocumentPlugins(mergedDocument, activeMindMap)
          if (sessionCancelled(sessionController?.signal) || mindMap.value !== activeMindMap) return false
          // 插件加载期间用户仍可能在浮层编辑器继续输入。应用权威树前再次
          // 提交 DOM-only 内容，让 generation 栅栏能够发现并延迟覆盖。文本
          // 节点必须先经过删除感知保护，避免把远端已删节点重新广播出去。
          const textProtectionResult = protectActiveTextEditorBeforeRemoteDocumentApply(
            mergedDocument.root,
            activeMindMap,
            mergedDocument,
          )
          commitActiveEditorsBeforeTermination()
          await nextTick()
          const changedDuringPluginPreparation = (
            textProtectionResult === 'local-edit-committed'
            || draftProtection.getChangeVersion() !== prepareDraftChangeVersion
            || viewChangeVersion !== prepareViewChangeVersion
            || documentDataGeneration !== prepareDocumentDataGeneration
            || pendingClientMutationId !== preparePendingMutationId
            || pendingContentOperations.length > 0
          )
          if (changedDuringPluginPreparation) {
            markAuthoritativeReloadRequired()
            ElNotification.info({
              title: '检测到新的本地修改',
              message: '已保留当前输入；保存完成后再应用云端合并结果',
            })
          } else {
            applyingServerTree = true
            try {
              applyAuthoritativeMindmapDocument(
                activeMindMap,
                mergedDocument,
              )
              await nextTick()
              mergedDocumentApplied = true
            } finally {
              applyingServerTree = false
            }
          }
        } catch (renderError) {
          // 服务端已经提交本批操作，渲染插件失败不能把同一批操作当成网络失败重试。
          // 保留当前画布草稿并阻止继续编辑旧基线，让用户通过既有冲突恢复流程
          // 从草稿中心找回当前画布，同时重新加载权威合并结果。
          await enterAuthoritativeApplyFailureRecovery(
            protectedDocumentBeforeMergeApply,
            {
              recoveryKind: null,
              eventKey: `concurrent-merge-${mutation.clientMutationId}`,
            },
          )
          activeSaveMutation = null
          activeSaveDocumentDataGeneration = null
          markDocumentMetaSaved({
            layout: response.data.layout,
            theme: normalizeServerTheme(response.data.theme),
            view: response.data.viewData,
            documentData: authoritativeResponseDocumentData,
          })
          clearTimeout(saveRetryTimer)
          saveRetryTimer = null
          saveRetryAttempt = 0
          retryNoticeShown = false
          conflictBlocked = true
          blockedConflictData = { currentRevision: contentRevision }
          saveRecoveryKind.value = 'conflict'
          setSaveStatus('error')
          console.error('协作合并结果渲染失败:', renderError)
          ElNotification.error({
            title: '云端已保存，但画布刷新失败',
            message: '请点击“处理冲突”，系统会先将当前画布保留到草稿中心，再加载云端合并结果',
          })
          return false
        }
        if (mergedDocumentApplied) {
          crossNodeOperationSnapshot = extractCrossNodeState(response.data.nodeTree)
          resolveAuthoritativeReload()
          onYjsReinit(response.data.nodeTree, contentRevision)
          ElNotification.success({
            title: '协作内容已合并',
            message: '已自动合并其他协作者在不同节点上的修改'
          })
        }
      }
    } else {
      // 普通保存的当前画布天然已经包含该批次，只有此时才可直接推进原
      // Y.Doc 的 revision；并发合并必须等权威树实际落到画布后重建。
      yjsSync?.setContentRevision(contentRevision, mutation.clientMutationId)
    }
    if (yjsSync?.requiresAuthoritativeReconciliation?.()) {
      markAuthoritativeReloadRequired()
    }
    if (
      !responseSuperseded
      && !rebasedAcrossRemoteRevision
      && !ordinaryAuthoritativeReloadRequired
    ) {
      markDocumentMetaSaved(response.data.concurrentMerge ? {
        layout: response.data.layout,
        theme: normalizeServerTheme(response.data.theme),
        view: response.data.viewData,
        documentData: authoritativeResponseDocumentData,
      } : mutation.document)
    }
    activeSaveMutation = null
    activeSaveDocumentDataGeneration = null
    setPendingAutomaticConflictRecovery(null)
    conflictBlocked = false
    const recoveredFromRetry = retryNoticeShown || saveRetryAttempt > 0
    clearSaveRetryState()
    if (
      pendingContentOperations.length === 0
      && !pendingClientMutationId
    ) {
      clearLocalDraft(draftClearBeforeUpdatedAt)
      clearRestoredDraft()
      draftProtection.markClean()
      collaborationRestartDeferredUntilSave = false
      startYjsSyncIfReady()
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
      const localData = getCurrentDocument()
      const recovered = await recoverFromSaveRevisionConflict(error.data, localData)
      if (!recovered) setSaveStatus('error')
      // 成功加载权威云端只表示冲突恢复完成；当前 HTTP mutation 仍然被
      // 服务器拒绝，调用方（手动保存/导入）绝不能把它报告为保存成功。
      return false
    }
    scheduleSaveRetry(error)
    return false
  } finally {
    isSaving.value = false
    if (terminalState) {
      pendingSave.value = false
    } else if (
      pendingSave.value
      || pendingContentOperations.length > 0
      || pendingClientMutationId
    ) {
      pendingSave.value = false
      clearTimeout(saveRetryTimer)
      saveRetryTimer = null
      clearTimeout(autoSaveTimer)
      autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
    } else if (shouldScheduleAuthoritativeReload) {
      scheduleAuthoritativeReload()
    }
    drainPendingRemoteDocumentReset()
  }
}

function queueRemoteDocumentReset(data = {}) {
  const nextRevision = Number(data?.contentRevision)
  const queuedRevision = Number(pendingRemoteDocumentReset?.contentRevision)
  if (
    !pendingRemoteDocumentReset
    || (
      Number.isInteger(nextRevision)
      && (!Number.isInteger(queuedRevision) || nextRevision >= queuedRevision)
    )
  ) {
    setPendingRemoteDocumentReset(data)
    return true
  }
  return false
}

function remoteDocumentResetAlreadyApplied(data) {
  const resetRevision = Number(data?.contentRevision)
  return Number.isInteger(resetRevision)
    && resetRevision <= contentRevision
    && yjsSync?.requiresAuthoritativeReconciliation?.() !== true
}

function acknowledgeRemoteDocumentReset(data) {
  if (!pendingRemoteDocumentReset) return
  const queuedRevision = Number(pendingRemoteDocumentReset?.contentRevision)
  const handledRevision = Number(data?.contentRevision)
  const handledRevisionApplied = !Number.isInteger(handledRevision)
    || handledRevision <= contentRevision
  if (
    (pendingRemoteDocumentReset === data && handledRevisionApplied)
    || (Number.isInteger(queuedRevision) && queuedRevision <= contentRevision)
  ) setPendingRemoteDocumentReset(null)
  if (!pendingRemoteDocumentReset) {
    remoteDocumentResetRetryBlocked = false
    if (saveRecoveryKind.value === 'sync') saveRecoveryKind.value = ''
  }
}

function blockRemoteDocumentResetRetry(actionTitle, message) {
  remoteDocumentResetRetryBlocked = true
  saveRecoveryKind.value = 'sync'
  setSaveStatus('error')
  ElNotification.error({
    title: `${actionTitle}暂未完成`,
    message: `${message}；当前画布仍保留，请点击“同步画布”重试`,
  })
}

function drainPendingRemoteDocumentReset({ allowUnsaved = false, forceRetry = false } = {}) {
  if (forceRetry) remoteDocumentResetRetryBlocked = false
  if (
    !pendingRemoteDocumentReset
    || remoteDocumentResetRetryBlocked
    || terminalState
    || !componentMounted
    || !mindMap.value
    || isSaving.value
    || resolvingStaleState
    || authoritativeReloadInProgress
    || versionChangeTrackingPaused
    || (
      !allowUnsaved
      && hasUnsavedChanges()
    )
  ) return false
  const resetData = pendingRemoteDocumentReset
  if (remoteDocumentResetAlreadyApplied(resetData)) {
    acknowledgeRemoteDocumentReset(resetData)
    mindMap.value?.setMode?.(isReadonly.value ? 'readonly' : 'edit')
    return false
  }
  // 在完整权威文档成功加载前始终保留 reset payload。WebSocket 已经建立
  // authoritative fence，同 revision 的事件不会再次派发，提前消费会让一次
  // IndexedDB/网络失败永久卡住当前协作会话。
  void handleRemoteDocumentReset(resetData)
  return true
}

function requestRemoteDocumentReset(data) {
  if (queueRemoteDocumentReset(data)) {
    authoritativeResetGeneration.value += 1
    remoteDocumentResetRetryBlocked = false
  }
  drainPendingRemoteDocumentReset({ allowUnsaved: true })
}

async function handleStaleCollaborationState(data) {
  // stale 回调可能在上一轮 GET/渲染仍进行时再次到达。即使本轮恢复函数
  // 随即因 resolvingStaleState 返回，也必须先提升单调版本下界，防止旧
  // HTTP 响应销毁持有更高 pending revision 的 Yjs 实例并宣告恢复成功。
  raiseAuthoritativeReloadMinimumRevision(data)
  // 历史版本画布不是可保存/可备份的当前文档。先只记录单调 revision
  // 下界，退出预览后再由 onVersionChangeTracking 锁定编辑并权威回源。
  if (versionChangeTrackingPaused || resolvingStaleState || !mindMap.value) return
  setResolvingStaleState(true)
  try {
    clearTimeout(autoSaveTimer)
    commitActiveEditorsBeforeTermination()
    await nextTick()
    if (sessionCancelled(sessionController?.signal) || !mindMap.value) return
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
    if (viewSaveRequested || viewSaveInProgress) {
      await retirePendingViewSaveForAuthoritativeReload()
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
    setResolvingStaleState(false)
    drainPendingRemoteDocumentReset()
  }
}

async function handleRemoteDocumentReset(data) {
  if (!mindMap.value) return false
  if (
    versionChangeTrackingPaused
    || resolvingStaleState
    || authoritativeReloadInProgress
    || isSaving.value
  ) {
    queueRemoteDocumentReset(data)
    return false
  }
  if (remoteDocumentResetAlreadyApplied(data)) {
    acknowledgeRemoteDocumentReset(data)
    return true
  }
  setResolvingStaleState(true)
  const isCloudReset = data?.reason === 'authoritative_cloud_reset'
  const actionTitle = isCloudReset ? '协作者选择了云端版本' : '协作者恢复了历史版本'
  try {
    clearTimeout(autoSaveTimer)
    commitActiveEditorsBeforeTermination()
    // document_reset 已使当前 Y.Doc 失效。活动编辑器先同步提交最后输入，随后
    // 立即锁住旧画布；IndexedDB 或权威 GET 等待期间不能继续接受新编辑，
    // 否则失败重试会留下无法合并、也无法安全丢弃的第三份本地状态。
    setAuthoritativeRecoveryEditingBlocked(true)
    await nextTick()
    if (sessionCancelled(sessionController?.signal) || !mindMap.value) return
    const recoveryDraftChangeVersion = draftProtection.getChangeVersion()
    const recoveryViewChangeVersion = viewChangeVersion
    if (hasUnsavedChanges()) {
      const fullData = getCurrentDocument()
      const draftResult = await preserveAutomaticConflictDraft(
        fullData,
        contentRevision,
      )
      if (draftResult?.saved !== true) {
        blockRemoteDocumentResetRetry(actionTitle, '未能创建本地安全副本')
        return false
      }
      if (draftProtection.getChangeVersion() !== recoveryDraftChangeVersion) {
        blockRemoteDocumentResetRetry(actionTitle, '保存安全副本期间画布又发生了修改')
        return false
      }
      ElNotification.warning({
        title: actionTitle,
        message: `当前未保存内容已保留在草稿中心，正在加载${isCloudReset ? '服务器' : '恢复后的'}版本`,
      })
    }
    await retirePendingViewSaveForAuthoritativeReload()
    if (sessionCancelled(sessionController?.signal) || !mindMap.value) return false
    const reloaded = await reloadLatestServerDocument({
      preserveLocalDraft: false,
      expectedDraftChangeVersion: recoveryDraftChangeVersion,
      expectedViewChangeVersion: recoveryViewChangeVersion,
      minimumContentRevision: Number(data?.contentRevision),
    })
    if (!reloaded) {
      blockRemoteDocumentResetRetry(actionTitle, '尚未能加载服务器最新内容')
      return false
    }
    acknowledgeRemoteDocumentReset(data)
    mindMap.value?.setMode?.(isReadonly.value ? 'readonly' : 'edit')
    ElMessage.success(isCloudReset ? '已重新加载服务器云端版本' : '已切换到协作者恢复的版本')
    return true
  } catch (error) {
    if (sessionCancelled(sessionController?.signal)) return false
    console.error('加载协作基线重置结果失败:', error)
    blockRemoteDocumentResetRetry(actionTitle, error?.message || '加载服务器最新内容失败')
    return false
  } finally {
    setResolvingStaleState(false)
    if (!remoteDocumentResetRetryBlocked) drainPendingRemoteDocumentReset()
  }
}

function terminateEditingSession(eventName, data) {
  if (terminalState || terminatingSession) return
  terminatingSession = true
  // HTTP 保存开始时已经冻结了用户实际提交的文档。终止事件可能在请求等待
  // 期间到达，而远端 Yjs 预览此时仍可能改写运行时画布；必须在提交浮层
  // 编辑器之前先复制在途批次，否则下面的 runtime 备份无法还原被覆盖的值。
  const frozenMutationSnapshot = captureRejectedMindmapMutationSnapshot({
    mutation: activeSaveMutation,
    fallbackBaseRevision: contentRevision,
    fallbackContentChangeVersion: draftProtection.getChangeVersion(),
  })
  const activeEditorChangesCommitted = commitActiveEditorsBeforeTermination()
  // terminatingSession 会阻止浮层关闭事件再进入普通保存队列，所以仅依赖
  // hasUnsavedChanges 会漏掉刚从 DOM 同步进模型的最后输入。
  const needsLocalBackup = Boolean(mindMap.value) && (
    hasUnsavedChanges() || activeEditorChangesCommitted
  )
  let localBackupCreated = false
  let localDraftPreserved = false
  const terminalDraftEntries = []
  if (needsLocalBackup) {
    const fullData = getCurrentDocument()
    const runtimeDiffersFromFrozenMutation = Boolean(
      frozenMutationSnapshot
      && !areMindmapDraftDocumentsEqual(frozenMutationSnapshot.document, fullData),
    )
    if (frozenMutationSnapshot) {
      terminalDraftEntries.push({
        options: createAutomaticConflictDraftOptions(
          frozenMutationSnapshot.document,
          frozenMutationSnapshot.baseRevision || contentRevision,
          `terminal-${eventName}-mutation-${frozenMutationSnapshot.clientMutationId || 'local'}`,
        ),
        document: frozenMutationSnapshot.document,
        downloadPrefix: `mindmap-${eventName}-mutation`,
        fallbackSaved: false,
      })
    }
    // 浮层提交可能产生冻结后的新输入；远端 Yjs 也可能已经改变 runtime。
    // 与在途批次不同时使用另一个草稿键，禁止两份快照互相覆盖。
    if (!frozenMutationSnapshot || runtimeDiffersFromFrozenMutation) {
      terminalDraftEntries.push({
        options: frozenMutationSnapshot
          ? createAutomaticConflictDraftOptions(
              fullData,
              contentRevision,
              `terminal-${eventName}-runtime-v${draftProtection.getChangeVersion()}`,
            )
          : createDraftOptions(fullData),
        document: fullData,
        downloadPrefix: `mindmap-${eventName}${frozenMutationSnapshot ? '-runtime' : ''}`,
        fallbackSaved: false,
      })
    }
    for (const entry of terminalDraftEntries) {
      entry.fallbackSaved = saveMindmapDraftFallbackSync(entry.options)
    }
    localDraftPreserved = terminalDraftEntries.length > 0
      && terminalDraftEntries.every(entry => entry.fallbackSaved)
    const downloadedBackups = terminalDraftEntries.map(entry => (
      downloadConflictBackup(entry.document, entry.downloadPrefix)
    ))
    localBackupCreated = terminalDraftEntries.length > 0
      && downloadedBackups.every(Boolean)
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
  activeSaveDocumentDataGeneration = null
  clearFileMetaIntentState()
  clearPendingClientMutation()
  resolveAuthoritativeReload()
  savedViewChangeVersion = viewChangeVersion
  isSaving.value = false
  pendingSave.value = false
  setSaveStatus('error')
  const terminatedSync = yjsSync
  yjsSync = null
  yjsSyncRef.value = null
  refreshStructureWriteBlockedState()
  terminatedSync?.destroy?.({ flushCheckpoint: false })
  const emitTerminalEvent = (draftPreserved) => emit(eventName, {
    ...data,
    localBackupCreated,
    localDraftPreserved: draftPreserved,
  })
  if (terminalDraftEntries.length === 0) {
    emitTerminalEvent(false)
    return
  }
  // 同步 localStorage 只承载小文档；每份快照继续分别等待 IndexedDB。只有
  // 冻结批次及不同的冻结后 runtime 都已落入至少一层存储，才宣告草稿安全。
  const durableDraftResults = terminalDraftEntries.map(entry => (
    enqueueDraftOperation(() => saveMindmapDraft(entry.options)).then(result => (
      entry.fallbackSaved || result?.saved === true
    ))
  ))
  void Promise.all(durableDraftResults).then((results) => {
    emitTerminalEvent(localDraftPreserved || results.every(Boolean))
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
      editor?.cancelPendingTextEditAdmission?.()
      editor?.hideEditTextBox?.()
    } catch (error) {
      // 单个插件编辑器异常不应阻断终止流程和其余内容的本地备份。
      console.warn('提交脑图活动编辑器失败:', error)
    }
  }
  // 上述各编辑器只会调用命令并排队 addHistory。nextTick 和
  // pagehide 都不会等待该定时器，所以在检查脏状态或备份前同步刷新。
  const historyCommitted = mindMap.value?.command?.flushPendingHistory?.() === true
  if (terminatingSession && historyCommitted) draftProtection.markDirty()
  return historyCommitted
}

async function reloadLatestServerDocument(options = {}) {
  const {
    preserveLocalDraft = false,
    requireClean = false,
    expectedDraftChangeVersion = null,
    expectedViewChangeVersion = null,
    minimumContentRevision = null,
    serverData = null,
    allowDuringEditingTransition = false,
  } = options
  const transitionGenerationAtRequest = editingTransitionGeneration
  if (hasActiveEditingTransition() && !allowDuringEditingTransition) {
    markAuthoritativeReloadRequired()
    return false
  }
  const signal = sessionController?.signal
  const cleanViewChangeVersion = viewChangeVersion
  const guardedDraftChangeVersion = expectedDraftChangeVersion
    ?? draftProtection.getChangeVersion()
  const guardedViewChangeVersion = expectedViewChangeVersion
    ?? viewChangeVersion
  const guardedDocumentDataGeneration = documentDataGeneration
  const hasLocalChangesSinceRequest = () => (
    draftProtection.getChangeVersion() !== guardedDraftChangeVersion
    || documentDataGeneration !== guardedDocumentDataGeneration
    || (
      viewChangeVersion !== guardedViewChangeVersion
      || viewSaveRequested
      || viewSaveInProgress
    )
  )
  if (
    requireClean
    && (hasUnsavedChanges() || viewSaveRequested || viewSaveInProgress)
  ) return false
  if (hasLocalChangesSinceRequest()) return false
  const response = serverData
    ? { data: serverData }
    : await getMindmap(props.mindmapId, {
      signal,
      // 自动补拉由本组件聚合为一次可恢复状态，避免每轮后台重试都弹全局错误。
      silentError: requireClean,
    })
  if (sessionCancelled(signal) || !mindMap.value) return false
  const data = response.data
  const serverContentRevision = Number(data?.contentRevision)
  const pendingResetRevision = Number(pendingRemoteDocumentReset?.contentRevision)
  const normalizedTheme = normalizeServerTheme(data.theme)
  const nextDocumentData = normalizeMindmapDocumentData(data.documentData)
  const activeMindMap = mindMap.value
  const serverDocument = {
    root: data.nodeTree || defaultData,
    layout: data.layout || 'logicalStructure',
    theme: normalizedTheme,
    view: data.viewData || null,
    documentData: nextDocumentData,
  }
  const isBelowRequiredRevision = () => (
    serverContentRevision < getAuthoritativeReloadMinimumRevision(
      minimumContentRevision,
    )
  )
  await ensureMindmapDocumentPlugins(serverDocument, activeMindMap)
  if (sessionCancelled(signal) || mindMap.value !== activeMindMap) return false
  if (
    editingTransitionGeneration !== transitionGenerationAtRequest
    || (hasActiveEditingTransition() && !allowDuringEditingTransition)
  ) {
    markAuthoritativeReloadRequired()
    return false
  }
  if (
    !Number.isInteger(serverContentRevision)
    || serverContentRevision <= 0
    || serverContentRevision < contentRevision
    || isBelowRequiredRevision()
    || (
      Number.isInteger(pendingResetRevision)
      && serverContentRevision < pendingResetRevision
    )
  ) {
    // HTTP 响应返回后，WebSocket 可能已经通知了更高 revision。此时再把
    // 旧快照落到画布会覆盖刚收到的协作结果，并把运行态重新带回旧基线。
    // 保持当前画布，改由下一轮权威补拉获取不低于本地栅栏的快照。
    markAuthoritativeReloadRequired()
    return false
  }
  if (
    (
      requireClean
      && (
        hasUnsavedChanges()
        || viewSaveRequested
        || viewSaveInProgress
        || viewChangeVersion !== cleanViewChangeVersion
      )
    )
    || hasLocalChangesSinceRequest()
  ) return false
  protectActiveTextEditorBeforeRemoteDocumentApply(
    serverDocument.root,
    activeMindMap,
    serverDocument,
  )
  // 节点仍存在时，浮层最后输入尚未进入 changeVersion。主动提交后再次
  // 检查请求代际；若产生了新修改，本轮权威快照必须让位给下一轮保存。
  commitActiveEditorsBeforeTermination()
  await nextTick()
  if (
    sessionCancelled(signal)
    || mindMap.value !== activeMindMap
    || editingTransitionGeneration !== transitionGenerationAtRequest
    || (hasActiveEditingTransition() && !allowDuringEditingTransition)
    || hasLocalChangesSinceRequest()
    || serverContentRevision < contentRevision
    || isBelowRequiredRevision()
    || (
      Number.isInteger(Number(pendingRemoteDocumentReset?.contentRevision))
      && serverContentRevision < Number(pendingRemoteDocumentReset.contentRevision)
    )
  ) {
    markAuthoritativeReloadRequired()
    return false
  }
  const protectedDocumentBeforeApply = getCurrentDocument()
  try {
    applyingServerTree = true
    try {
      applyAuthoritativeMindmapDocument(activeMindMap, serverDocument)
      await nextTick()
    } finally {
      applyingServerTree = false
    }
    documentData.value = nextDocumentData
    applyMindmapDocumentConfig(mindMap.value, documentData.value)
  } catch (error) {
    await enterAuthoritativeApplyFailureRecovery(
      protectedDocumentBeforeApply,
      { eventKey: 'authoritative-reload-apply' },
    )
    throw error
  }
  if (
    sessionCancelled(signal)
    || !mindMap.value
    || isBelowRequiredRevision()
  ) {
    if (!sessionCancelled(signal) && mindMap.value) {
      markAuthoritativeReloadRequired()
    }
    return false
  }
  contentRevision = serverContentRevision
  nodeRevisionMap.clear()
  for (const [nodeUid, revision] of Object.entries(data.nodeRevisions || {})) {
    nodeRevisionMap.set(nodeUid, revision)
  }
  pendingContentOperations = []
  activeSaveMutation = null
  activeSaveDocumentDataGeneration = null
  clearFileMetaIntentState()
  clearPendingClientMutation()
  if (!resolveAuthoritativeReload()) return false
  crossNodeOperationSnapshot = extractCrossNodeState(data.nodeTree || defaultData)
  markDocumentMetaSaved({
    layout: data.layout,
    theme: normalizedTheme,
    view: data.viewData,
    documentData: documentData.value,
  })
  savedViewChangeVersion = viewChangeVersion
  conflictBlocked = false
  clearSaveRetryState()
  // 到这里权威树、文件元数据、revision 与保存基线才全部一致。先解除临时
  // 门闩，让当前会话草稿可以正常清理，并让新的 Y.Doc 以可写权限重建。
  setAuthoritativeRecoveryEditingBlocked(false)
  if (!preserveLocalDraft) {
    clearLocalDraft()
    clearRestoredDraft()
  }
  onYjsReinit(data.nodeTree || defaultData, contentRevision)
  if (pendingRemoteDocumentReset) {
    acknowledgeRemoteDocumentReset(pendingRemoteDocumentReset)
  }
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
      `检测到${conflictCount ? ` ${conflictSummary}` : ''}无法自动合并。当前画布会保留在草稿中心，然后加载云端最新版本。`,
      '需要处理协作冲突',
      {
        type: 'warning',
        confirmButtonText: '保留草稿并加载云端',
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
  // 复用自动冲突恢复的安全状态机：独立草稿成功落盘且期间没有新编辑，
  // 才允许推进协作 revision、清空旧检查点并加载数据库权威正文。
  // 不触发浏览器下载，用户可按需从草稿中心导出或继续处理原修改。
  return recoverFromSaveRevisionConflict(conflictData, localFullData)
}

async function manualSave() {
  if (isReadonly.value) return false
  if (!mindMap.value) return
  if (props.mindmapId) {
    if (conflictBlocked) {
      if (!blockedConflictData) {
        saveRecoveryKind.value = 'conflict'
        setSaveStatus('error')
        ElMessage.error('冲突上下文已失效，当前内容仍保留在草稿中心，请刷新后重试')
        return false
      }
      return resolveContentConflict(getCurrentDocument(), blockedConflictData)
    }
    clearTimeout(autoSaveTimer)
    resetSaveRetryForNewChange()
    const ok = await saveToBackend()
    const viewSaved = await flushPendingViewSave()
    if (ok === true && viewSaved === true) {
      ElMessage.success('已保存到服务器')
    } else if (ok === true && viewSaved === false) {
      ElMessage.warning('正文已保存，但画布视图暂未保存，请稍后重试')
    } else if (ok === false) {
      if (['offline', 'retrying'].includes(saveStatus.value)) {
        ElMessage.warning('云端暂不可用，系统正在保护本地修改')
      } else if (saveStatus.value !== 'saved') {
        ElMessage.error('保存失败，请检查网络')
      }
    }
    return ok === true && viewSaved === true
  } else {
    const fullData = getCurrentDocument()
    const saved = persistLocalWorkspace(fullData)
    if (saved) ElMessage.success('已保存')
    return saved
  }
}

async function recoverSave() {
  if (pendingRemoteDocumentReset) {
    const resetData = pendingRemoteDocumentReset
    remoteDocumentResetRetryBlocked = false
    saveRecoveryKind.value = ''
    setSaveStatus('syncing')
    return handleRemoteDocumentReset(resetData)
  }
  if (pendingAutomaticConflictRecovery) {
    const recovery = pendingAutomaticConflictRecovery
    setPendingAutomaticConflictRecovery(null)
    return recoverFromSaveRevisionConflict(
      recovery.conflictData,
      getCurrentDocument(),
      recovery,
    )
  }
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
    // 一次编辑后又撤销到原状态时，语义操作会被压缩为空，但对应 Yjs
    // 帧已经被其他浏览器预览。仍须提交 collaboration.sync.confirm，
    // 否则离开页面会取消防抖保存，让观察端永久停在未确认状态。
    || Boolean(pendingClientMutationId)
    || documentMetaBuffer.hasPending()
    || pendingContentOperations.length > 0
  )
}

function handleBeforeUnload(event) {
  commitActiveEditorsBeforeTermination()
  if (viewSaveRequested) void flushPendingViewSave()
  if (
    hasRealWritePermission()
    && (hasUnsavedChanges() || viewSaveRequested || viewSaveInProgress)
  ) {
    // version/import transition 只临时冻结交互，不能把仍在途的保存伪装成
    // 真正只读会话。即使 pagehide 的草稿写入失败，浏览器也必须保留原生
    // 离页确认；服务端撤权/只读观察者则没有可提交写入，不弹误导提示。
    persistLocalDraftBeforeUnload()
    event.preventDefault()
    event.returnValue = ''
  }
}

async function flushBeforeLeave() {
  if (terminalState || !props.mindmapId) return true
  // 真正的只读观察者没有可提交批次，沿用原先的成功语义；恢复门闩则
  // 表示旧 runtime 不可再保存，必须明确阻止调用方继续破坏性流程。
  if (props.readonly || serverCanEdit.value !== true) return true
  if (!canFlushCloudChangesDuringEditingTransition()) return false
  clearTimeout(autoSaveTimer)
  clearTimeout(saveRetryTimer)
  saveRetryTimer = null
  for (let pass = 0; pass < CLOUD_EXIT_MAX_PASSES; pass += 1) {
    const contentSaved = await flushPendingMindmapChanges({
      hasUnsavedChanges,
      isSaveInProgress: () => isSaving.value,
      markPendingSave: () => { pendingSave.value = true },
      requestSave: async () => {
        clearTimeout(autoSaveTimer)
        return saveToBackend()
      },
      persistLocalBackup: persistLocalDraftBeforeUnload,
    })
    if (contentSaved !== true) return false

    clearTimeout(viewSaveTimer)
    viewSaveTimer = null
    const viewSaved = await flushPendingViewSave()
    if (viewSaved !== true) return false
    if (!hasUnsavedChanges() && !viewSaveRequested && !viewSaveInProgress) return true
  }
  persistLocalDraftBeforeUnload()
  return false
}

async function prepareForCloudExit() {
  if (
    terminalState
    || !props.mindmapId
    || props.readonly
    || serverCanEdit.value !== true
  ) return true
  if (!canFlushCloudChangesDuringEditingTransition()) return false

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
    commitActiveEditorsBeforeTermination()
    await nextTick()
    if (hasUnsavedChanges() || viewSaveRequested || viewSaveInProgress) continue

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
    // 删除草稿本身也是异步窗口；返回路由守卫前做最后一次同步提交。该
    // nextTick 后到 clean 判断之间不再 await，DOM-only 输入无法漏过栅栏。
    commitActiveEditorsBeforeTermination()
    await nextTick()
    if (hasUnsavedChanges() || viewSaveRequested || viewSaveInProgress) continue

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
  let importCollaborationStopped = false
  let importEditingBlocked = false
  let importBoundaryChangeVersion = null
  let protectedDocumentBeforeImportApply = null
  let importApplyFailureHandled = false
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

    if (props.mindmapId) {
      // 导入是“替换整份正文”，不能和一个仍在途的增量保存共享旧基线。
      // 先让导入前的编辑稳定落库；失败时画布尚未被替换，用户可直接重试。
      commitActiveEditorsBeforeTermination()
      await nextTick()
      if (
        activeMindMap !== mindMap.value
        || sessionCancelled(sessionController?.signal)
        || props.readonly
        || serverCanEdit.value !== true
        || authoritativeRecoveryEditingBlocked.value
      ) {
        throw new Error('脑图会话已经变化，请重新导入')
      }
      setImportTransitionEditingBlocked(true)
      importEditingBlocked = true
      await nextTick()
      importBoundaryChangeVersion = draftProtection.getChangeVersion()
      if (await flushBeforeLeave() !== true) {
        throw new Error('当前修改尚未保存，已取消导入以避免覆盖内容')
      }
      if (
        activeMindMap !== mindMap.value
        || sessionCancelled(sessionController?.signal)
        || props.readonly
        || serverCanEdit.value !== true
        || authoritativeRecoveryEditingBlocked.value
      ) {
        throw new Error('脑图会话已经变化，请重新导入')
      }
      if (conflictBlocked || pendingAutomaticConflictRecovery) {
        throw new Error('当前保存冲突尚未处理，请处理后再导入')
      }
      if (pendingRemoteDocumentReset) {
        const resetApplied = await handleRemoteDocumentReset(
          pendingRemoteDocumentReset,
        )
        if (resetApplied !== true || pendingRemoteDocumentReset) {
          throw new Error('协作者的画布变更仍在同步，请稍后再导入')
        }
      }
      if (authoritativeReloadRequired) {
        const reloaded = await performAuthoritativeReload({
          allowDuringEditingTransition: true,
        })
        if (reloaded !== true || authoritativeReloadRequired) {
          throw new Error('云端画布仍在同步，请稍后再导入')
        }
      }
      if (
        activeMindMap !== mindMap.value
        || sessionCancelled(sessionController?.signal)
        || props.readonly
        || serverCanEdit.value !== true
        || authoritativeRecoveryEditingBlocked.value
      ) {
        throw new Error('脑图会话已经变化，请重新导入')
      }
      // reset/reload/flush 都可能等待网络或插件。替换旧 Y.Doc 前再收一次
      // Plain/Rich/Outline，并确认门闩期间没有出现新的内容代际；一旦发现
      // pending 就取消本次整树覆盖，让用户在当前画布重试。
      commitActiveEditorsBeforeTermination()
      await nextTick()
      if (
        draftProtection.getChangeVersion() !== importBoundaryChangeVersion
        || hasUnsavedChanges()
        || viewSaveRequested
        || viewSaveInProgress
      ) {
        throw new Error('导入等待期间检测到新的修改，已取消覆盖，请重试')
      }
      // 已经打开的 Y.Doc 代表导入前的正文。整树替换若继续沿用它，旧节点
      // 会在下一次远端增量或检查点中重新出现；先无检查点地关闭，等 HTTP
      // 快照提交及权威回源后再由 onYjsReinit 建立新 lineage。
      protectedDocumentBeforeImportApply = getCurrentDocument()
      collaborationRestartDeferredUntilSave = true
      importCollaborationStopped = stopCurrentCollaborationSource()
      documentMetaBuffer.clear()
      clearFileMetaIntentState()
      nodeRevisionMap.clear()
    } else {
      commitActiveEditorsBeforeTermination()
      await nextTick()
      if (activeMindMap !== mindMap.value || isReadonly.value) {
        throw new Error('脑图会话已经变化，请重新导入')
      }
      setImportTransitionEditingBlocked(true)
      importEditingBlocked = true
    }

    let rootNodeData = null
    try {
      if (data.root) {
        const hasImportedDocumentData = Object.prototype.hasOwnProperty.call(data, 'documentData')
        const nextDocumentData = hasImportedDocumentData
          ? normalizeMindmapDocumentData(data.documentData)
          : documentData.value
        activeMindMap.setFullData(data)
        documentData.value = nextDocumentData
        if (hasImportedDocumentData) documentDataGeneration += 1
        applyMindmapDocumentConfig(activeMindMap, documentData.value)
        rootNodeData = data.root
      } else {
        activeMindMap.setData(data)
        rootNodeData = data
      }
      activeMindMap.view.reset()
      // setData 会清空历史并安排首个节流基线，它不会产生
      // data_change_detail。先同步消费该任务，再显式登记受 revision 保护的
      // 整图快照；否则导入可能只改变当前画布，刷新后仍回到旧云端正文。
      activeMindMap.command?.flushPendingHistory?.()
    } catch (applyError) {
      if (props.mindmapId && protectedDocumentBeforeImportApply) {
        importApplyFailureHandled = true
        await enterAuthoritativeApplyFailureRecovery(
          protectedDocumentBeforeImportApply,
          { eventKey: `import-apply-${createMutationId()}` },
        )
        // setFullData/config/view.reset 任一步都可能已改动部分 runtime，并触发
        // 不完整的本地事件。保护导入前完整文档后清空这些旧 lineage intents，
        // 让 requireClean 的权威 GET 能恢复一致基线；readonly 门闩只由成功
        // 的 reloadLatestServerDocument 解除。
        abandonPendingContentForAuthoritativeReload()
        scheduleAuthoritativeReload()
      }
      throw applyError
    }
    crossNodeOperationSnapshot = extractCrossNodeState(rootNodeData)
    if (props.mindmapId) {
      pendingContentOperations = [{ type: CONTENT_SNAPSHOT_OPERATION }]
      ensurePendingClientMutationId()
      scheduleLocalDraftPersist()
      resetSaveRetryForNewChange()
      clearTimeout(autoSaveTimer)
      const saved = await flushPendingMindmapChanges({
        hasUnsavedChanges,
        isSaveInProgress: () => isSaving.value,
        markPendingSave: () => { pendingSave.value = true },
        requestSave: async () => {
          clearTimeout(autoSaveTimer)
          return saveToBackend()
        },
        persistLocalBackup: persistLocalDraftBeforeUnload,
      })
      if (saved !== true) {
        throw new Error('导入内容已保留在本地草稿，但尚未保存到云端')
      }
    } else if (!persistLocalWorkspace(getCurrentDocument())) {
      throw new Error('导入内容未能保存到本地')
    }
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
    if (
      !importApplyFailureHandled
      && importCollaborationStopped
      && !yjsSync
      && !hasUnsavedChanges()
      && !sessionCancelled(sessionController?.signal)
    ) {
      // 替换过程在登记快照前异常时，旧 Y.Doc 已经安全销毁。不要用可能
      // 只应用了一半的运行时树重新播种，改从数据库恢复原来的权威正文。
      markAuthoritativeReloadRequired()
      scheduleAuthoritativeReload()
    }
    request.reject?.(error)
    if (!request.reject) {
      console.error('应用导入的脑图数据失败:', error)
      ElMessage.error(error?.message || '导入内容应用失败')
    }
  } finally {
    if (importEditingBlocked) {
      setImportTransitionEditingBlocked(false)
      resumeAfterEditingTransition()
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

/** 使用版本恢复后的完整 HTTP 响应走统一权威加载入口。 */
function fenceAuthoritativeVersionWrite(contentRevisionFloor) {
  if (terminalState || !mindMap.value) return false
  // restoreVersion 已经不可逆地推进了数据库正文。旧 Y.Doc 从这一刻起就
  // 不能再恢复编辑；即使紧随其后的 GET 失败，也由权威重载重试保持只读。
  commitActiveEditorsBeforeTermination()
  raiseAuthoritativeReloadMinimumRevision(contentRevisionFloor)
  markAuthoritativeReloadRequired()
  setAuthoritativeRecoveryEditingBlocked(true)
  stopCurrentCollaborationSource()
  return true
}

function applyRestoredVersionData(serverData, options = {}) {
  if (!serverData?.nodeTree) return Promise.resolve(false)
  const responseRevision = Number(serverData.contentRevision)
  const restoredRevision = Number(options.minimumContentRevision)
  const minimumContentRevision = Number.isInteger(restoredRevision)
    ? restoredRevision
    : responseRevision
  return reloadLatestServerDocument({
    preserveLocalDraft: false,
    // 恢复 API 与随后 GET 之间用户仍可能继续输入。服务端恢复已不可逆，
    // 但绝不能因此清空这段新输入；若会话不再干净，交给 document_reset
    // 的草稿保护流程处理。
    requireClean: true,
    minimumContentRevision,
    serverData,
    allowDuringEditingTransition: true,
  })
}

/** 销毁旧的 Yjs 连接，用已经应用到画布的权威数据创建新的同步实例。 */
function onYjsReinit(_restoredRoot, revision) {
  if (!props.mindmapId) return
  if (Number.isInteger(revision) && revision > 0) contentRevision = revision
  collaborationRestartDeferredUntilSave = false
  // 这里的调用方已经把画布切换为 HTTP/历史版本返回的权威基线。旧 Y.Doc
  // 可能仍是上一 revision 的残缺或未确认状态，且 contentRevision 已经推进；
  // 若按默认行为冲刷检查点，会把旧文档错误地写成新 revision 的协作缓存，
  // 后续打开页面就可能只显示旧状态中的根节点。
  if (yjsSync) {
    yjsSync.destroy({ flushCheckpoint: false })
    yjsSync = null
    yjsSyncRef.value = null
    refreshStructureWriteBlockedState()
  }
  // 移除旧的 data_change_detail 监听器（使用具名引用）
  if (dataChangeDetailHandler) {
    mindMap.value?.off('data_change_detail', dataChangeDetailHandler)
    dataChangeDetailHandler = null
  }
  // 恢复草稿尚未提交时保持协作门闩关闭，避免 sync_init 把本地恢复内容覆盖。
  startYjsSyncIfReady()
}

function isContentDetailTrackingSuspended() {
  return Boolean(terminalState)
    || terminatingSession
    || authoritativeRecoveryEditingBlocked.value
    || protectingActiveEditorFromRemoteDelete
    || applyingServerTree
    || versionChangeTrackingPaused
    || Boolean(yjsSync && (
      yjsSync.isPaused()
      || yjsSync.isMutatingMindmapFromRemote?.()
    ))
}

function isChangeTrackingSuspended() {
  return Boolean(terminalState)
    || terminatingSession
    || authoritativeRecoveryEditingBlocked.value
    || protectingActiveEditorFromRemoteDelete
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

function onVersionEditingTransition(blocked) {
  if (blocked === true) {
    // 子组件会在此同步回调返回后才开始 GET/flush。先提交所有 DOM-only
    // 编辑，再切只读，保证等待窗口里无法重新取得节点租约。
    commitActiveEditorsBeforeTermination()
    setVersionTransitionEditingBlocked(true)
    return
  }
  setVersionTransitionEditingBlocked(false)
  resumeAfterEditingTransition()
}

function onVersionChangeTracking(paused, context = {}) {
  versionChangeTrackingPaused = Boolean(paused)
  if (versionChangeTrackingPaused) {
    clearTimeout(autoSaveTimer)
    return
  }
  const authoritativeRecoveryPending = Boolean(
    context?.authoritativeResetPending
    || pendingRemoteDocumentReset
    || authoritativeReloadRequired
  )
  if (
    authoritativeRecoveryPending
    && !hasUnsavedChanges()
    && !viewSaveRequested
    && !viewSaveInProgress
  ) setAuthoritativeRecoveryEditingBlocked(true)
  if (context?.authoritativeResetPending) remoteDocumentResetRetryBlocked = false
  const resetStarted = drainPendingRemoteDocumentReset({
    allowUnsaved: true,
    forceRetry: context?.authoritativeResetPending === true,
  })
  if (!resetStarted && authoritativeReloadRequired) {
    if (hasUnsavedChanges()) {
      clearTimeout(autoSaveTimer)
      autoSaveTimer = setTimeout(() => { void saveToBackend() }, AUTO_SAVE_DELAY)
    } else if (!viewSaveRequested && !viewSaveInProgress) {
      scheduleAuthoritativeReload()
    }
    return
  }
  if (resetStarted) return
  // drain 可能因正在保存/恢复或显式重试门闩暂缓执行。只要 reset 仍在
  // 队列中就保持只读，不能恢复旧协作实例让用户继续编辑待淘汰的画布。
  if (pendingRemoteDocumentReset) return

  // applyRestoredVersionData 会在 tracking 暂停期间销毁旧 Y.Doc；恢复跟踪后
  // 才能以已经落到画布的权威树创建新实例。普通退出也重新接上可能因异常
  // 遗留的本地自动保存，避免最后一次编辑永久停在 pending 状态。
  if (authoritativeRecoveryPending) setAuthoritativeRecoveryEditingBlocked(false)
  startYjsSyncIfReady()
  if (hasUnsavedChanges() && !isSaving.value) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => { void saveToBackend() }, AUTO_SAVE_DELAY)
  }
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
