<template>
  <div
    class="mindmap-edit-page"
    :class="{
      'has-command-bar': documentLoaded && !isZenMode && !isReadonly,
      'has-search-panel': searchPanelOpen,
      'has-left-panel': activeSidebar === 'outline',
      'has-right-panel': Boolean(activeSidebar && activeSidebar !== 'outline'),
      'is-dark': isDark,
    }"
  >
    <div class="mindmap-edit-header">
      <div class="header-left">
        <div class="brand-mark" aria-hidden="true">
          <span class="iconfont iconfuhao-dagangshu" />
        </div>
        <button class="back-btn" @click="goBack" title="返回列表" type="button" aria-label="返回脑图列表">
          <el-icon :size="20"><ArrowLeft /></el-icon>
        </button>
        <div class="title-area">
          <div class="title-copy">
            <button
              class="mindmap-title"
              type="button"
              :disabled="isReadonly"
              :aria-label="isReadonly ? `脑图标题：${mindmapName}` : `编辑脑图信息：${mindmapName}`"
              @click="showMetadataDialog"
            >
              {{ mindmapName || '加载中...' }}
              <el-icon v-if="!isReadonly" class="edit-icon"><EditIcon /></el-icon>
            </button>
            <span class="document-meta">
              <template v-if="documentStatus === 1">已归档 · 只读预览</template>
              <template v-else-if="isReadonly">
                <span>只读预览</span>
                <span class="meta-separator" aria-hidden="true">·</span>
                <span>{{ documentNodeCount }} 个节点</span>
                <span class="meta-separator" aria-hidden="true">·</span>
                <span>{{ documentVersionCount }} 个版本</span>
              </template>
              <template v-else>
                <span>我的脑图</span>
                <span class="meta-separator" aria-hidden="true">·</span>
                <span class="meta-save-status" :class="saveStatus" role="status" aria-live="polite" aria-atomic="true">
                  {{ saveStatusText }}
                </span>
                <el-tooltip :content="realtimeStatusDetail" placement="bottom" :show-after="300">
                  <span
                    class="meta-realtime-status"
                    :class="realtimeStatusClass"
                    :aria-label="realtimeStatusText"
                    role="status"
                  >
                    <span class="status-dot" aria-hidden="true" />
                  </span>
                </el-tooltip>
              </template>
            </span>
          </div>
          <el-tag v-if="isReadonly" type="info" size="small" effect="plain" class="readonly-tag">只读</el-tag>
          <Collaborators
            v-if="collaborators.length > 0"
            :collaborators="collaborators"
            :dark="isDark"
            class="collaborators"
          />
        </div>
      </div>
      <div
        v-if="documentLoaded && !isZenMode && !isReadonly"
        ref="headerCommandCenterRef"
        id="mindmap-mobile-command-sheet"
        class="header-command-center"
        :class="{ 'is-mobile-open': mobileCommandOpen }"
        aria-label="脑图编辑命令"
        :role="mobileCommandOpen ? 'dialog' : undefined"
        :aria-modal="mobileCommandOpen ? 'true' : undefined"
      >
        <div class="mobile-command-sheet-header">
          <div>
            <strong>编辑命令</strong>
            <span>添加节点、插入内容或撤销操作</span>
          </div>
          <button
            ref="mobileCommandCloseRef"
            class="mobile-command-close"
            type="button"
            aria-label="关闭编辑命令"
            @click="closeMobileCommands"
          >
            <el-icon><Close /></el-icon>
          </button>
        </div>
        <Toolbar embedded class="header-command-toolbar" />
      </div>
      <div class="header-right">
        <div v-if="documentLoaded" class="header-actions">
          <div v-if="!isReadonly && (canRetryRealtime || saveRecoveryAction)" class="header-recovery-actions">
            <el-tooltip v-if="canRetryRealtime" content="立即重新连接实时协作" placement="bottom" :show-after="300">
              <button
                class="realtime-retry-btn"
                type="button"
                aria-label="立即重连实时协作"
                @click="handleRealtimeRetry"
              >
                <el-icon><Refresh /></el-icon>
                <span>重连</span>
              </button>
            </el-tooltip>
            <button
              v-if="saveRecoveryAction"
              class="save-recovery-btn"
              type="button"
              :aria-label="saveRecoveryAction.ariaLabel"
              :disabled="saveRecoveryBusy"
              @click="handleSaveRecovery"
            >
              <el-icon v-if="saveRecoveryBusy" class="is-loading"><Loading /></el-icon>
              <el-icon v-else><Refresh /></el-icon>
              <span class="recovery-label">{{ saveRecoveryAction.label }}</span>
            </button>
          </div>
          <template v-if="serverIsOwner && !isReadonly">
            <el-tooltip content="管理分享链接与访问权限" placement="bottom" :show-after="300">
              <button class="share-btn" @click="openShareDialog" type="button" aria-label="分享脑图">
                <svg-icon icon-class="share" />
                <span>分享</span>
              </button>
            </el-tooltip>
          </template>
          <div class="header-utility-group" aria-label="文档工具">
            <el-tooltip content="编辑命令" placement="bottom" :show-after="300" v-if="!isReadonly">
              <button
                ref="mobileCommandTriggerRef"
                class="header-icon-btn mobile-command-trigger"
                :class="{ 'is-active': mobileCommandOpen }"
                type="button"
                aria-label="打开编辑命令"
                aria-controls="mindmap-mobile-command-sheet"
                :aria-expanded="mobileCommandOpen"
                @click="toggleMobileCommands"
              >
                <el-icon><Operation /></el-icon>
                <span class="header-action-label">编辑</span>
              </button>
            </el-tooltip>
            <el-tooltip content="立即保存（Ctrl / ⌘ + S）" placement="bottom" :show-after="300" v-if="!isReadonly">
              <button
                class="header-icon-btn save-action-btn"
                type="button"
                aria-label="立即保存脑图"
                :disabled="manualSaveBusy || ['saving', 'syncing'].includes(saveStatus)"
                @click="handleManualSave"
              >
                <el-icon v-if="manualSaveBusy" class="is-loading"><Loading /></el-icon>
                <el-icon v-else><DocumentChecked /></el-icon>
                <span class="header-action-label">保存</span>
              </button>
            </el-tooltip>
            <el-tooltip
              v-if="isReadonly"
              :content="activeSidebar === 'outline' ? '关闭节点大纲' : '查看节点大纲'"
              placement="bottom"
              :show-after="300"
            >
              <button
                class="header-icon-btn outline-action-btn"
                :class="{ 'is-active': activeSidebar === 'outline' }"
                type="button"
                :aria-label="activeSidebar === 'outline' ? '关闭脑图大纲' : '打开脑图大纲'"
                :aria-pressed="activeSidebar === 'outline'"
                @click="openOutline"
              >
                <el-icon><List /></el-icon>
                <span class="header-action-label">大纲</span>
              </button>
            </el-tooltip>
            <el-tooltip content="搜索节点（Ctrl / ⌘ + F）" placement="bottom" :show-after="300">
              <button class="header-icon-btn search-action-btn" type="button" aria-label="搜索节点" @click="openSearch">
                <el-icon><Search /></el-icon>
                <span class="header-action-label">搜索</span>
              </button>
            </el-tooltip>
            <el-tooltip content="仅显示符合条件的节点" placement="bottom" :show-after="300">
              <button class="header-icon-btn filter-action-btn" type="button" aria-label="筛选画布节点" @click="openFilter">
                <el-icon><Filter /></el-icon>
                <span class="header-action-label">筛选</span>
              </button>
            </el-tooltip>
            <el-tooltip
              :content="activeSidebar === 'versionHistory' ? '关闭版本历史' : '查看版本历史'"
              placement="bottom"
              :show-after="300"
            >
              <button
                class="header-icon-btn history-action-btn"
                :class="{ 'is-active': activeSidebar === 'versionHistory' }"
                type="button"
                :aria-label="activeSidebar === 'versionHistory' ? '关闭版本历史' : '打开版本历史'"
                :aria-pressed="activeSidebar === 'versionHistory'"
                @click="openVersionHistory"
              >
                <el-icon><Clock /></el-icon>
                <span class="header-action-label">历史</span>
              </button>
            </el-tooltip>
            <el-tooltip content="协作者管理" placement="bottom" :show-after="300" v-if="serverIsOwner && !isReadonly">
              <button
                class="header-icon-btn collaborator-action-btn"
                :class="{ 'is-active': activeSidebar === 'collaboratorManager' }"
                type="button"
                :aria-label="activeSidebar === 'collaboratorManager' ? '关闭协作者管理' : '打开协作者管理'"
                :aria-pressed="activeSidebar === 'collaboratorManager'"
                @click="openCollaboratorManager"
              >
                <el-icon><User /></el-icon>
                <span class="header-action-label">协作</span>
              </button>
            </el-tooltip>
          </div>
        </div>
      </div>
    </div>
    <button
      v-if="mobileCommandOpen"
      class="mobile-command-backdrop"
      type="button"
      aria-label="关闭编辑命令"
      tabindex="-1"
      @click="closeMobileCommands"
    />
    <el-alert
      v-if="documentStatus === 1"
      class="content-state-alert"
      type="info"
      :closable="false"
      show-icon
      title="该脑图已归档"
      description="归档文件保留全部内容、版本和分享，但恢复前不能继续编辑。"
    />
    <el-alert
      v-if="contentState !== 'ready'"
      class="content-state-alert"
      :type="contentStatePresentation.type"
      :closable="false"
      show-icon
      :title="contentStatePresentation.title"
      :description="contentStatePresentation.description"
    />
    <div class="mindmap-edit-body">
      <div v-if="hasValidMindmapId && !loadError" class="mindmap-editor-container">
        <MindMapEditor
          :key="editorInstanceKey"
          ref="editRef"
          :mindmap-id="mindmapId"
          :readonly="requestedReadonly"
          :draft-key="requestedDraftKey"
          @name-change="onNameChange"
          @access-change="onAccessChange"
          @ready="onEditorReady"
          @load-error="onLoadError"
          @document-deleted="onDocumentDeleted"
          @document-archived="onDocumentArchived"
          @access-revoked="onAccessRevoked"
          @session-ended="onSessionEnded"
        />
        <div v-if="documentLoaded && isReadonly" class="readonly-canvas-context" aria-label="脑图文档摘要">
          <strong>{{ mindmapName || '未命名脑图' }}</strong>
          <span>
            {{ documentNodeCount }} 个节点 · {{ documentVersionCount }} 个版本
            <template v-if="documentUpdateTime"> · 更新于 {{ documentUpdateTime }}</template>
          </span>
        </div>
        <div v-if="documentLoaded && isReadonly" class="readonly-mode-banner" role="group" aria-label="阅读模式">
          <span>当前为只读预览</span>
          <button v-if="canEnterEditMode" type="button" @click="enterEditMode">进入编辑</button>
        </div>
        <div
          v-if="!editorReady"
          class="editor-loading"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <div class="editor-loading-card">
            <span class="editor-loading-icon" aria-hidden="true">
              <el-icon class="is-loading"><Loading /></el-icon>
            </span>
            <div class="editor-loading-copy">
              <strong>正在打开脑图</strong>
              <span>{{ serverCanEdit === null ? '正在获取文件与访问权限…' : '正在初始化画布与协作能力…' }}</span>
            </div>
          </div>
        </div>
      </div>
      <el-result
        v-else-if="!hasValidMindmapId"
        icon="warning"
        title="无法打开脑图"
        sub-title="脑图链接缺少有效的文件 ID"
        class="invalid-document"
      >
        <template #extra>
          <el-button type="primary" @click="goBack">返回脑图列表</el-button>
        </template>
      </el-result>
      <el-result
        v-else
        icon="error"
        title="脑图加载失败"
        :sub-title="loadError"
        class="invalid-document"
      >
        <template #extra>
          <div class="load-error-actions">
            <el-button type="primary" :icon="Refresh" @click="retryEditorLoad">重新加载</el-button>
            <el-button @click="goBack">返回脑图列表</el-button>
          </div>
        </template>
      </el-result>
      <NavigatorToolbar v-if="documentLoaded && !isZenMode" :mindMap="mindMapInstance" :locked-readonly="isReadonly" />
    </div>

    <MindmapMetadataDialog
      ref="metadataDialogRef"
      :session-key="editorSessionKey"
      @updated="handleMetadataUpdated"
    />

    <ShareDialog v-if="hasValidMindmapId" ref="shareDialogRef" :mindmap-id="mindmapId" />
  </div>
</template>

<script setup name="MindmapEditorPage">
import { ArrowLeft, Edit as EditIcon, Filter, Loading, Search, Clock, User, Refresh, DocumentChecked, List, Operation, Close } from '@element-plus/icons-vue'
import Toolbar from '@/components/MindMap/Toolbar.vue'
import MindMapEditor from '@/components/MindMap/Edit.vue'
import NavigatorToolbar from '@/components/MindMap/NavigatorToolbar.vue'
import Collaborators from '@/components/MindMap/Collaborators.vue'
import ShareDialog from '@/components/MindMap/ShareDialog.vue'
import MindmapMetadataDialog from '@/components/MindMap/MindmapMetadataDialog.vue'
import { store, actions } from '@/components/MindMap/useStore'
import bus from '@/components/MindMap/useEventBus'
import {
  buildMindmapListRoute,
  createMindmapEditorSessionKey,
  parseMindmapFocusNodeUid,
  parseMindmapRouteId,
} from '@/utils/mindmap-route'
import { getMindmapSaveRecoveryAction } from '@/utils/mindmap-save-lifecycle'
import {
  getMindmapContentStatePresentation,
  isMindmapContentWritable,
  normalizeMindmapContentState,
} from '@/utils/mindmap-content-state'
import { useRoute, useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { parseTime } from '@/utils/ruoyi'

const route = useRoute()
const router = useRouter()
const editRef = ref(null)
const headerCommandCenterRef = ref(null)
const mobileCommandTriggerRef = ref(null)
const mobileCommandCloseRef = ref(null)
const mobileCommandOpen = ref(false)
const searchPanelOpen = ref(false)
const mindmapId = computed(() => parseMindmapRouteId(route.query.id))
const hasValidMindmapId = computed(() => mindmapId.value !== null)
const requestedReadonly = computed(() => route.query.readonly === '1')
const requestedDraftKey = computed(() => (
  typeof route.query.draftKey === 'string'
    ? route.query.draftKey.slice(0, 512)
    : ''
))
const requestedFocusNodeUid = computed(() => parseMindmapFocusNodeUid(route.query.focusNode))
const editorSessionKey = computed(() => (
  `${createMindmapEditorSessionKey(mindmapId.value, requestedReadonly.value)}:${requestedDraftKey.value || 'latest-draft'}`
))
const editorRetryNonce = ref(0)
const editorInstanceKey = computed(() => `${editorSessionKey.value}:${editorRetryNonce.value}`)
const serverCanEdit = ref(null)
const editorReady = ref(false)
const serverIsOwner = ref(false)
const serverAccessType = ref(route.query.from === 'shared' ? 'shared' : null)
const loadError = ref('')
const contentState = ref('ready')
const contentStateMessage = ref('')
const contentStatePresentation = computed(() => (
  getMindmapContentStatePresentation(contentState.value, contentStateMessage.value)
))
const documentStatus = ref(0)
const isReadonly = computed(() => requestedReadonly.value || serverCanEdit.value !== true)
const documentLoaded = computed(() => (
  hasValidMindmapId.value
  && !loadError.value
  && serverCanEdit.value !== null
  && editorReady.value
))
const canEnterEditMode = computed(() => (
  requestedReadonly.value
  && serverCanEdit.value === true
  && documentStatus.value !== 1
  && contentState.value === 'ready'
))
const mindmapName = ref('')
const mindmapDescription = ref('')
const documentNodeCount = ref(0)
const documentVersionCount = ref(0)
const documentUpdateTime = ref('')
const metadataDialogRef = ref(null)
const isZenMode = computed(() => store.localConfig.isZenMode)
const isDark = computed(() => store.localConfig.isDark)
const activeSidebar = computed(() => store.activeSidebar)
const mindMapInstance = computed(() => editRef.value?.mindMap || null)
const collaborators = computed(() => editRef.value?.getCollaborators?.() || [])
const saveStatus = computed(() => {
  const exposedStatus = editRef.value?.saveStatus
  return typeof exposedStatus === 'string' ? exposedStatus : exposedStatus?.value || 'idle'
})
const saveRecoveryKind = computed(() => {
  const exposedKind = editRef.value?.saveRecoveryKind
  return typeof exposedKind === 'string' ? exposedKind : exposedKind?.value || ''
})
const saveRecoveryAction = computed(() => (
  getMindmapSaveRecoveryAction(saveStatus.value, saveRecoveryKind.value)
))
const saveRecoveryBusy = ref(false)
const manualSaveBusy = ref(false)
let manualSaveRequestId = 0
const isRealtimeConnected = computed(() => editRef.value?.isCollaborationSynced?.() === true)
const realtimeState = computed(() => editRef.value?.getCollaborationState?.() || 'connecting')
const realtimeError = computed(() => editRef.value?.getCollaborationError?.() || '')
const realtimeStatusText = computed(() => ({
  connected: '协作在线',
  degraded: '协作已恢复',
  syncing: '正在同步',
  stale: '正在合并',
  reconnecting: '正在重连',
  authenticating: '正在认证',
  'auth-error': '协作不可用',
  offline: '协作离线',
  closed: '协作已关闭',
}[realtimeState.value] || '正在连接'))
const realtimeStatusClass = computed(() => ({
  online: isRealtimeConnected.value && realtimeState.value === 'connected',
  error: ['auth-error', 'offline'].includes(realtimeState.value),
  warning: ['syncing', 'stale', 'reconnecting', 'authenticating', 'degraded'].includes(realtimeState.value),
}))
const realtimeStatusDetail = computed(() => realtimeError.value || ({
  connected: '实时协作连接正常',
  degraded: '检测到异常协作缓存，已隔离并使用可恢复内容继续同步',
  syncing: '连接已建立，正在校准协作状态',
  stale: '检测到较新的服务器内容，正在安全合并本地修改',
  reconnecting: '连接中断，正在自动重连',
  authenticating: '正在验证协作身份',
  offline: '实时协作暂时不可用，本地自动保存仍然有效',
}[realtimeState.value] || '正在建立实时协作连接'))
const canRetryRealtime = computed(() => (
  documentLoaded.value
  && !isReadonly.value
  && realtimeState.value === 'offline'
))
const saveStatusText = computed(() => ({
  pending: '待保存',
  saving: '正在保存',
  retrying: '正在重试',
  syncing: '正在同步画布',
  offline: '离线草稿',
  saved: '已自动保存',
  error: '保存异常',
  idle: '已自动保存',
}[saveStatus.value] || '已自动保存'))

const shareDialogRef = ref(null)
let terminalDialogShown = false
const returnListRoute = computed(() => buildMindmapListRoute(
  serverAccessType.value,
  route.query.returnList,
))

function handleRealtimeRetry() {
  if (!canRetryRealtime.value) return
  editRef.value?.retryCollaboration?.()
}

function closeMobileCommands({ restoreFocus = true } = {}) {
  if (!mobileCommandOpen.value) return
  mobileCommandOpen.value = false
  if (restoreFocus) nextTick(() => mobileCommandTriggerRef.value?.focus?.())
}

function toggleMobileCommands() {
  if (mobileCommandOpen.value) {
    closeMobileCommands()
    return
  }
  mobileCommandOpen.value = true
  nextTick(() => mobileCommandCloseRef.value?.focus?.())
}

function handleMobileCommandKeydown(event) {
  if (event.key === 'Escape' && mobileCommandOpen.value) {
    event.preventDefault()
    closeMobileCommands()
    return
  }
  if (event.key !== 'Tab' || !mobileCommandOpen.value) return
  const focusable = Array.from(headerCommandCenterRef.value?.querySelectorAll?.(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  ) || []).filter((element) => element.offsetParent !== null)
  if (focusable.length === 0) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function handleMobileCommandResize() {
  if (window.innerWidth > 760) closeMobileCommands({ restoreFocus: false })
}

async function handleSaveRecovery() {
  if (saveRecoveryBusy.value) return
  saveRecoveryBusy.value = true
  try {
    await editRef.value?.recoverSave?.()
  } finally {
    saveRecoveryBusy.value = false
  }
}

async function handleManualSave() {
  if (manualSaveBusy.value || isReadonly.value || !documentLoaded.value) return
  const requestId = ++manualSaveRequestId
  const sessionKey = editorSessionKey.value
  manualSaveBusy.value = true
  try {
    await editRef.value?.manualSave?.()
  } finally {
    if (requestId === manualSaveRequestId && sessionKey === editorSessionKey.value) {
      manualSaveBusy.value = false
    }
  }
}

function openShareDialog() {
  shareDialogRef.value?.open()
}

function openSearch() {
  bus.emit('show_search')
}

function openFilter() {
  bus.emit('show_filter')
}

function handleSearchPanelVisibilityChange(visible) {
  searchPanelOpen.value = visible === true
}

function toggleSidebar(sidebarName) {
  const nextSidebar = activeSidebar.value === sidebarName ? null : sidebarName
  if (!actions.setActiveSidebar(nextSidebar) || !nextSidebar) return
  nextTick(() => bus.emit('focusActiveSidebar'))
}

function openOutline() {
  toggleSidebar('outline')
}

function openVersionHistory() {
  toggleSidebar('versionHistory')
}

function openCollaboratorManager() {
  toggleSidebar('collaboratorManager')
}

function goBack() {
  router.push(returnListRoute.value)
}

function enterEditMode() {
  if (!canEnterEditMode.value) return
  const query = { ...route.query }
  delete query.readonly
  router.push({ path: route.path, query })
}

function onNameChange(name) {
  mindmapName.value = name
}

function onAccessChange(access) {
  const nextContentState = normalizeMindmapContentState(access?.contentState)
  serverCanEdit.value = access?.canEdit === true && isMindmapContentWritable(nextContentState)
  serverIsOwner.value = access?.isOwner === true
  serverAccessType.value = access?.accessType === 'shared' ? 'shared' : 'owned'
  contentState.value = nextContentState
  documentStatus.value = Number(access?.status) === 1 ? 1 : 0
  contentStateMessage.value = access?.contentStateMessage || ''
  mindmapDescription.value = access?.description || ''
  documentNodeCount.value = Math.max(0, Number(access?.nodeCount) || 0)
  documentVersionCount.value = Math.max(0, Number(access?.versionCount) || 0)
  documentUpdateTime.value = parseTime(access?.updateTime, '{y}-{m}-{d} {h}:{i}') || ''
}

function onEditorReady() {
  editorReady.value = true
  focusRequestedNode()
}

function focusRequestedNode() {
  const nodeUid = requestedFocusNodeUid.value
  if (!nodeUid) return
  nextTick(() => editRef.value?.focusNodeByUid?.(nodeUid))
}

watch(requestedFocusNodeUid, () => {
  if (editorReady.value) focusRequestedNode()
})

function onLoadError(error) {
  editorReady.value = false
  loadError.value = error?.message || '请检查文件是否存在、你是否仍有访问权限或网络是否正常。'
}

function retryEditorLoad() {
  if (!hasValidMindmapId.value || !loadError.value) return
  editRef.value = null
  editorReady.value = false
  serverCanEdit.value = null
  serverIsOwner.value = false
  mindmapName.value = ''
  mindmapDescription.value = ''
  documentNodeCount.value = 0
  documentVersionCount.value = 0
  documentUpdateTime.value = ''
  contentState.value = 'ready'
  contentStateMessage.value = ''
  documentStatus.value = 0
  loadError.value = ''
  editorRetryNonce.value += 1
}

async function onDocumentDeleted(data) {
  await showTerminalDialog(
    '脑图已删除',
    data?.message || '该脑图已被所有者删除，当前页面将返回脑图列表。',
    data,
  )
}

async function onDocumentArchived(data) {
  await showTerminalDialog(
    '脑图已归档',
    data?.message || '该脑图已被所有者归档，当前页面将返回脑图列表。',
    data,
  )
}

async function onAccessRevoked(data) {
  await showTerminalDialog(
    '编辑权限已失效',
    data?.message || '你已无法继续编辑该脑图，当前页面将返回脑图列表。',
    data,
  )
}

async function onSessionEnded(data) {
  const authenticationUnavailable = data?.reason === 'auth_unavailable'
  await showTerminalDialog(
    authenticationUnavailable ? '协作认证暂时不可用' : '登录会话已失效',
    data?.message || (
      authenticationUnavailable
        ? '暂时无法确认当前登录状态，为保护脑图数据，本次编辑会话已安全结束。'
        : '当前登录会话已过期或被注销，本次编辑会话已安全结束。'
    ),
    data,
  )
}

async function showTerminalDialog(title, message, data) {
  if (terminalDialogShown) return
  terminalDialogShown = true
  const backupMessage = data?.localBackupCreated && data?.localDraftPreserved
    ? ' 未同步修改已下载为 JSON，并保留在本地草稿中心。'
    : data?.localBackupCreated
      ? ' 未同步修改已自动下载为 JSON 备份。'
      : data?.localDraftPreserved
        ? ' 未同步修改已保留在本地草稿中心，可返回列表后下载。'
        : ''
  try {
    await ElMessageBox.alert(
      `${message}${backupMessage}`,
      title,
      {
        type: 'warning',
        confirmButtonText: '返回列表',
        showClose: false,
        closeOnClickModal: false,
        closeOnPressEscape: false,
      },
    )
  } finally {
    router.replace(returnListRoute.value)
  }
}

function showMetadataDialog() {
  if (isReadonly.value) return
  metadataDialogRef.value?.open?.({
    id: mindmapId.value,
    name: mindmapName.value,
    description: mindmapDescription.value,
  })
}

function handleMetadataUpdated(metadata) {
  if (Number(metadata?.id) !== mindmapId.value) return
  mindmapName.value = metadata.name
  mindmapDescription.value = metadata.description
}

async function confirmEditorNavigation() {
  if (isReadonly.value) return true
  const saved = await editRef.value?.prepareForCloudExit?.()
  if (saved !== false) return true
  const protectedByLocalDraft = editRef.value?.isLocalDraftProtected?.() === true
  try {
    await ElMessageBox.confirm(
      protectedByLocalDraft
        ? '修改已保存在本机草稿，但尚未同步到云端。仍要离开吗？'
        : '云端保存失败，且未能确认当前修改已写入本机草稿。离开后可能丢失内容，是否仍要离开？',
      '未保存的修改',
      {
        type: 'warning',
        confirmButtonText: '仍要离开',
        cancelButtonText: '留在此页',
        distinguishCancelAndClose: true,
      }
    )
    return true
  } catch {
    return false
  }
}

onBeforeRouteLeave(confirmEditorNavigation)

onBeforeRouteUpdate((to) => {
  const nextId = parseMindmapRouteId(to.query.id)
  const nextReadonly = to.query.readonly === '1'
  const nextDraftKey = typeof to.query.draftKey === 'string'
    ? to.query.draftKey.slice(0, 512)
    : ''
  if (
    nextId === mindmapId.value
    && nextReadonly === requestedReadonly.value
    && nextDraftKey === requestedDraftKey.value
  ) return true
  return confirmEditorNavigation()
})

watch(editorSessionKey, () => {
  closeMobileCommands({ restoreFocus: false })
  manualSaveRequestId += 1
  manualSaveBusy.value = false
  editRef.value = null
  editorReady.value = false
  mindmapName.value = ''
  mindmapDescription.value = ''
  documentNodeCount.value = 0
  documentVersionCount.value = 0
  documentUpdateTime.value = ''
  serverCanEdit.value = null
  serverIsOwner.value = false
  serverAccessType.value = route.query.from === 'shared' ? 'shared' : null
  loadError.value = ''
  contentState.value = 'ready'
  contentStateMessage.value = ''
  documentStatus.value = 0
  terminalDialogShown = false
})

watch([documentLoaded, isReadonly, isZenMode], ([loaded, readonly, zen]) => {
  if (!loaded || readonly || zen) closeMobileCommands({ restoreFocus: false })
})

onMounted(() => {
  window.addEventListener('keydown', handleMobileCommandKeydown)
  window.addEventListener('resize', handleMobileCommandResize)
  bus.on('searchPanelVisibilityChange', handleSearchPanelVisibilityChange)
})

onBeforeUnmount(() => {
  manualSaveRequestId += 1
  window.removeEventListener('keydown', handleMobileCommandKeydown)
  window.removeEventListener('resize', handleMobileCommandResize)
  bus.off('searchPanelVisibilityChange', handleSearchPanelVisibilityChange)
})
</script>

<style scoped lang="scss">
.mindmap-edit-page {
  --mindmap-shell-top: 52px;
  --mindmap-activity-width: 44px;
  --mindmap-side-panel-width: 300px;
  --mindmap-workspace-bottom: 30px;
  --mindmap-canvas-gap: 8px;
  --mindmap-workspace-left: var(--mindmap-activity-width);
  --mindmap-workspace-right: var(--mindmap-activity-width);
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f4f5f7;
  overflow: hidden;
  color: #1f2329;

  &.has-command-bar {
    --mindmap-shell-top: 52px;
  }

  &.has-search-panel {
    --mindmap-workspace-left: calc(var(--mindmap-activity-width) + 280px);
  }

  &.has-left-panel {
    --mindmap-workspace-left: calc(var(--mindmap-activity-width) + var(--mindmap-side-panel-width));
  }

  &.has-right-panel {
    --mindmap-workspace-right: calc(var(--mindmap-activity-width) + var(--mindmap-side-panel-width));
  }
}

.invalid-document {
  width: 100%;
  margin: auto;
}

.content-state-alert {
  flex-shrink: 0;
}

.mindmap-edit-header {
  height: 52px;
  padding: 0 8px 0 0;
  gap: 8px;
  background: #f4f5f7;
  border-bottom: 1px solid #e3e6ea;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  user-select: none;
  z-index: 2100;

  .header-left {
    display: flex;
    align-items: center;
    min-width: 0;
    flex: 0 1 264px;
    max-width: 30%;
    gap: 4px;
  }

  .header-right {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    gap: 4px;
  }

  .back-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: 6px;
    cursor: pointer;
    color: #646a73;
    transition: all 0.2s;
    flex-shrink: 0;
    border: none;
    background: transparent;
    padding: 0;
    outline: none;
    &:hover {
      background: #fff;
      color: #1f2329;
      box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px #3370ff40;
    }
  }

  .title-area {
    display: flex;
    align-items: center;
    min-width: 0;
    gap: 8px;
  }

  .brand-mark {
    width: 44px;
    height: 52px;
    flex: 0 0 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #3370ff;
    background: #f4f5f7;
    border-right: 1px solid #e3e6ea;

    .iconfont {
      font-size: 19px;
    }
  }

  .title-copy {
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-width: 0;
    gap: 1px;
  }

  .mindmap-title {
    appearance: none;
    border: none;
    background: transparent;
    font-family: inherit;
    text-align: left;
    font-size: 14px;
    line-height: 19px;
    font-weight: 600;
    color: #1f2329;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 5px;
    margin-left: -5px;
    border-radius: 6px;
    transition: background 0.15s;
    max-width: 184px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    &:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px rgba(51, 112, 255, 0.16);
    }

    &.is-active {
      color: #245bdb;
      background: #edf3ff;
    }
    &:disabled {
      cursor: default;
    }
    &:disabled:hover {
      background: transparent;
    }
    &:hover {
      background: #f0f3f8;
      .edit-icon { opacity: 1; }
    }
    .edit-icon {
      font-size: 14px;
      color: #8f959e;
      opacity: 0;
      transition: opacity 0.15s;
    }
  }

  .document-meta {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: #8f959e;
    font-size: 11px;
    line-height: 14px;
    white-space: nowrap;
  }

  .meta-separator {
    color: #c2c6cc;
  }

  .meta-save-status {
    &.error,
    &.offline {
      color: #b42318;
    }

    &.pending,
    &.retrying,
    &.saving,
    &.syncing {
      color: #8f6b20;
    }
  }

  .meta-realtime-status {
    width: 14px;
    height: 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;

    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #f5a623;
    }

    &.online .status-dot {
      background: #2fb66d;
    }

    &.error .status-dot {
      background: #e5484d;
    }
  }

  .readonly-tag {
    flex-shrink: 0;
  }

  .collaborators {
    flex-shrink: 0;
    margin-left: 4px;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .header-utility-group {
    display: flex;
    align-items: center;
    gap: 0;
    margin-left: 4px;
    padding-left: 6px;
    border-left: 1px solid #e1e4e8;
  }

  .header-icon-btn {
    width: 32px;
    height: 32px;
    border: none;
    border-radius: 7px;
    color: #646a73;
    background: transparent;
    display: inline-flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    gap: 0;
    cursor: pointer;
    font-size: 18px;
    transition: background 0.16s ease, color 0.16s ease, transform 0.16s ease;

    &:hover {
      background: #fff;
      color: #3370ff;
      box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);
    }

    &.is-active {
      color: #245bdb;
      background: #fff;
      box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);
    }

    &:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px rgba(51, 112, 255, 0.16);
    }

    .header-action-label {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }
  }

  .header-recovery-actions {
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }

  .realtime-retry-btn {
    display: inline-flex;
    height: 30px;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 0 9px;
    border: 1px solid #ffc9c5;
    border-radius: 999px;
    background: #fff;
    color: #b42318;
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    font-weight: 600;

    &:hover,
    &:focus-visible {
      border-color: #e5484d;
      background: #fff1f0;
      outline: none;
    }

    &:focus-visible {
      box-shadow: 0 0 0 3px rgba(229, 72, 77, 0.14);
    }
  }

  .save-action-btn:disabled {
    cursor: wait;
    opacity: 0.52;
  }

  .save-recovery-btn {
    display: inline-flex;
    height: 30px;
    align-items: center;
    gap: 4px;
    padding: 0 9px;
    border: 1px solid #ffc9c5;
    border-radius: 999px;
    background: #fff;
    color: #b42318;
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    font-weight: 600;

    &:hover:not(:disabled),
    &:focus-visible {
      border-color: #e5484d;
      background: #fff1f0;
      outline: none;
    }

    &:focus-visible {
      box-shadow: 0 0 0 3px rgba(229, 72, 77, 0.14);
    }

    &:disabled {
      cursor: wait;
      opacity: 0.65;
    }
  }

  .share-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 64px;
    height: 32px;
    border-radius: 6px;
    cursor: pointer;
    color: #1f2329;
    transition: all 0.2s;
    font-size: 13px;
    font-weight: 500;
    gap: 6px;
    border: 1px solid #dfe3e8;
    background: #fff;
    padding: 0 12px;
    box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);
    outline: none;
    &:hover {
      border-color: #b9c9eb;
      background: #f8faff;
      color: #245bdb;
      box-shadow: 0 2px 6px rgba(31, 35, 41, 0.1);
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px #3370ff40;
    }
    .svg-icon {
      width: 15px;
      height: 15px;
      color: #3370ff;
    }
  }
}

.header-command-center {
  min-width: 160px;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1 1 auto;
  overflow: hidden;
}

.header-command-toolbar {
  min-width: 0;
  flex: 1;
  pointer-events: auto;
  overflow: hidden;
}

.mobile-command-sheet-header,
.mobile-command-trigger,
.mobile-command-backdrop {
  display: none;
}

.mindmap-edit-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.mindmap-editor-container {
  flex: 1;
  display: flex;
  overflow: hidden;
  background: #fff;
  position: relative;
}

.readonly-canvas-context {
  position: absolute;
  top: 22px;
  left: 24px;
  z-index: 18;
  display: flex;
  max-width: min(420px, calc(100% - 120px));
  flex-direction: column;
  gap: 5px;
  pointer-events: none;

  strong,
  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: #1f2329;
    font-size: 16px;
    font-weight: 650;
    line-height: 22px;
  }

  span {
    color: #8f959e;
    font-size: 12px;
    line-height: 18px;
  }
}

.readonly-mode-banner {
  position: absolute;
  top: 14px;
  left: 50%;
  z-index: 19;
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  gap: 10px;
  padding: 4px 6px 4px 12px;
  color: #646a73;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #e2e6ed;
  border-radius: 8px;
  box-shadow: 0 6px 18px rgba(31, 35, 41, 0.08);
  transform: translateX(-50%);
  backdrop-filter: blur(10px);
  white-space: nowrap;
  font-size: 12px;

  button {
    height: 28px;
    padding: 0 10px;
    border: 0;
    border-radius: 6px;
    color: #245bdb;
    background: #edf3ff;
    cursor: pointer;
    font: inherit;
    font-weight: 600;

    &:hover { background: #dfeaff; }
    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 2px;
    }
  }
}

.load-error-actions {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;

  :deep(.el-button + .el-button) {
    margin-left: 0;
  }
}

.editor-loading {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at 50% 42%, rgba(51, 112, 255, 0.08), transparent 30%),
    #f8faff;
}

.editor-loading-card {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: min(320px, 100%);
  padding: 18px 20px;
  color: #1f2329;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(51, 112, 255, 0.12);
  border-radius: 14px;
  box-shadow: 0 14px 40px rgba(31, 35, 41, 0.08);
  backdrop-filter: blur(12px);
}

.editor-loading-icon {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  display: grid;
  place-items: center;
  color: #3370ff;
  background: #edf3ff;
  border-radius: 12px;
  font-size: 20px;
}

.editor-loading-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 4px;

  strong {
    font-size: 15px;
    line-height: 21px;
  }

  span {
    color: #8f959e;
    font-size: 12px;
    line-height: 18px;
  }
}

.mindmap-edit-page.is-dark {
  background: #17191d;

  .mindmap-edit-header {
    background: #23262b;
    border-color: #363a41;
    color: #e5e6eb;
  }

  .mindmap-edit-header {
    .mindmap-title { color: #f0f1f2; }
    .document-meta { color: #92979f; }
    .brand-mark {
      background: #23262b;
      border-right-color: #363a41;
    }
    .header-icon-btn {
      color: #afb4bc;
      &:hover { color: #fff; background: #30343a; }
      &.is-active { color: #8daaff; background: rgba(51, 112, 255, 0.16); }
    }
    .save-recovery-btn {
      color: #ff8f87;
      background: #302629;
      border-color: #6b3738;

      &:hover:not(:disabled),
      &:focus-visible {
        background: #3d292c;
        border-color: #e5484d;
      }
    }
    .realtime-retry-btn {
      color: #ff8f87;
      background: #302629;
      border-color: #6b3738;

      &:hover,
      &:focus-visible {
        background: #3d292c;
        border-color: #e5484d;
      }
    }
  }

  .header-command-toolbar {
    :deep(.toolbarBlock::after) { background: #3b3f46; }
    :deep(.toolbarBtn) {
      color: #b9bec6;
      &:hover:not(.disabled) { color: #fff; background: #30343a; }
      &.active { color: #7da2ff; background: rgba(51, 112, 255, 0.16); }
    }
  }

  .mindmap-editor-container {
    background: #1e2024;
  }

  .readonly-canvas-context {
    strong { color: #f0f1f2; }
    span { color: #92979f; }
  }

  .readonly-mode-banner {
    color: #b9bec6;
    background: rgba(42, 45, 51, 0.96);
    border-color: #3d4148;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.24);

    button {
      color: #a8bfff;
      background: rgba(51, 112, 255, 0.18);
      &:hover { background: rgba(51, 112, 255, 0.26); }
    }
  }

  .editor-loading {
    background:
      radial-gradient(circle at 50% 42%, rgba(91, 133, 255, 0.12), transparent 30%),
      #1e2024;
  }

  .editor-loading-card {
    color: #f0f1f2;
    background: rgba(42, 45, 51, 0.94);
    border-color: rgba(125, 162, 255, 0.18);
    box-shadow: 0 16px 46px rgba(0, 0, 0, 0.22);
  }

  .editor-loading-icon {
    color: #8daaff;
    background: rgba(51, 112, 255, 0.16);
  }

  .editor-loading-copy span {
    color: #92979f;
  }
}

@media (max-width: 1439px) and (min-width: 761px) {
  .mindmap-edit-page.has-right-panel {
    --mindmap-workspace-right: var(--mindmap-activity-width);
  }

  .mindmap-edit-page.has-left-panel {
    --mindmap-workspace-left: var(--mindmap-activity-width);
  }
}

@media (max-width: 1180px) {
  .mindmap-edit-header {
    .header-left {
      flex-basis: 252px;
    }

    .meta-realtime-status {
      display: none;
    }
  }
}

@media (max-width: 980px) {
  .mindmap-edit-header {
    gap: 10px;

    .header-left {
      flex-basis: 216px;
    }

    .header-icon-btn {
      width: 32px;
      height: 34px;

      .header-action-label {
        display: none;
      }
    }
  }
}

@media (max-width: 760px) {
  .mindmap-edit-page {
    --mindmap-shell-top: 60px;
    --mindmap-workspace-left: 0px;
    --mindmap-workspace-right: 0px;
    --mindmap-workspace-bottom: 52px;
    --mindmap-canvas-gap: 6px;

    &.has-command-bar {
      --mindmap-shell-top: 60px;
    }

    &.has-search-panel,
    &.has-left-panel,
    &.has-right-panel {
      --mindmap-workspace-left: 0px;
      --mindmap-workspace-right: 0px;
    }
  }

  .mindmap-edit-header {
    height: 60px;
    padding: 0 10px;
    gap: 8px;

    .header-left {
      max-width: none;
      flex: 1;
    }

    .document-meta,
    .collaborators,
    .history-action-btn,
    .collaborator-action-btn {
      display: none;
    }

    .brand-mark {
      width: 44px;
      height: 60px;
      flex-basis: 44px;
    }

    .header-utility-group {
      margin-left: 2px;
      padding-left: 4px;
    }

    .mindmap-title {
      max-width: 140px;
    }

    .share-btn {
      min-width: 34px;
      width: 34px;
      padding: 0;

      span {
        display: none;
      }
    }

    .save-recovery-btn {
      width: 30px;
      justify-content: center;
      padding: 0;

      .recovery-label {
        display: none;
      }
    }

    .realtime-retry-btn {
      width: 30px;
      padding: 0;

      span {
        display: none;
      }
    }
  }

  .header-command-center {
    display: none;

    &.is-mobile-open {
      position: fixed;
      z-index: 2201;
      left: 12px;
      right: 12px;
      bottom: 12px;
      display: flex;
      height: auto;
      max-height: min(70vh, 420px);
      min-width: 0;
      padding: 0 12px 14px;
      flex-direction: column;
      align-items: stretch;
      overflow: visible;
      border: 1px solid #e3e7ee;
      border-radius: 14px;
      background: #fff;
      box-shadow: 0 18px 48px rgba(31, 35, 41, 0.2);
    }
  }

  .mobile-command-trigger {
    display: inline-flex;
  }

  .mobile-command-sheet-header {
    display: flex;
    min-height: 58px;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    border-bottom: 1px solid #eef0f3;

    > div {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 2px;
    }

    strong {
      color: #1f2329;
      font-size: 15px;
      font-weight: 600;
    }

    span {
      overflow: hidden;
      color: #8f959e;
      font-size: 12px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .mobile-command-close {
    display: inline-flex;
    width: 34px;
    height: 34px;
    flex: 0 0 34px;
    align-items: center;
    justify-content: center;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: #646a73;
    cursor: pointer;

    &:hover { background: #f2f3f5; }
    &:focus-visible { outline: 2px solid #3370ff; outline-offset: 1px; }
  }

  .mobile-command-backdrop {
    position: fixed;
    z-index: 2200;
    inset: 0;
    display: block;
    width: 100%;
    height: 100%;
    padding: 0;
    border: 0;
    background: rgba(15, 23, 42, 0.32);
    cursor: default;
  }

  .header-command-toolbar {
    width: 100%;
    padding-top: 10px;
  }

  .readonly-canvas-context {
    top: 16px;
    left: 16px;
    max-width: calc(100% - 88px);

    strong { font-size: 14px; }
  }

  .readonly-mode-banner {
    top: auto;
    bottom: 64px;
  }

  .load-error-actions {
    flex-direction: column;

    :deep(.el-button) {
      width: 100%;
    }
  }
}
</style>
