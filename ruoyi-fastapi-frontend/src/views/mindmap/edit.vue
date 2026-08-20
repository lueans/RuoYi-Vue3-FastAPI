<template>
  <div class="mindmap-edit-page" :class="{ 'has-command-bar': documentLoaded && !isZenMode && !isReadonly, 'is-dark': isDark }">
    <div class="mindmap-edit-header">
      <div class="header-left">
        <button class="back-btn" @click="goBack" title="返回列表" type="button" aria-label="返回脑图列表">
          <el-icon :size="18"><ArrowLeft /></el-icon>
        </button>
        <div class="header-divider" />
        <div class="title-area">
          <div class="document-mark" aria-hidden="true">
            <span class="iconfont iconfuhao-dagangshu" />
          </div>
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
            <span class="document-meta">{{ documentStatus === 1 ? '已归档 · 只读预览' : isReadonly ? '只读预览' : '在线脑图 · 自动保存' }}</span>
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
      <div class="header-right">
        <div v-if="documentLoaded" class="header-actions">
          <el-tooltip content="搜索节点（Ctrl / ⌘ + F）" placement="bottom" :show-after="300">
            <button class="header-icon-btn" type="button" aria-label="搜索节点" @click="openSearch">
              <el-icon><Search /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="版本历史" placement="bottom" :show-after="300">
            <button class="header-icon-btn" type="button" aria-label="版本历史" @click="openVersionHistory">
              <el-icon><Clock /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="协作者管理" placement="bottom" :show-after="300" v-if="serverIsOwner && !isReadonly">
            <button class="header-icon-btn" type="button" aria-label="协作者管理" @click="openCollaboratorManager">
              <el-icon><User /></el-icon>
            </button>
          </el-tooltip>
          <div v-if="!isReadonly" class="realtime-status-group">
            <el-tooltip :content="realtimeStatusDetail" placement="bottom" :show-after="300">
              <span class="realtime-status" :class="realtimeStatusClass" role="status" aria-live="polite" aria-atomic="true">
                <span class="status-dot" />
                <span>{{ realtimeStatusText }}</span>
              </span>
            </el-tooltip>
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
          </div>
          <div v-if="!isReadonly" class="save-status-group">
            <el-tooltip content="立即保存（Ctrl / ⌘ + S）" placement="bottom" :show-after="300">
              <button
                class="manual-save-btn"
                type="button"
                aria-label="立即保存脑图"
                :disabled="manualSaveBusy || ['saving', 'syncing'].includes(saveStatus)"
                @click="handleManualSave"
              >
                <el-icon v-if="manualSaveBusy" class="is-loading"><Loading /></el-icon>
                <el-icon v-else><DocumentChecked /></el-icon>
                <span class="manual-save-label">保存</span>
              </button>
            </el-tooltip>
            <span class="save-status" :class="saveStatus" role="status" aria-live="polite" aria-atomic="true">
              <el-icon v-if="['saving', 'retrying', 'syncing'].includes(saveStatus)" class="is-loading" :size="14"><Loading /></el-icon>
              <el-icon v-else-if="['error', 'offline'].includes(saveStatus)" :size="14"><WarningFilled /></el-icon>
              <el-icon v-else-if="saveStatus === 'pending'" :size="14"><Clock /></el-icon>
              <el-icon v-else :size="14"><Check /></el-icon>
              <span class="save-text">{{ saveStatusText }}</span>
            </span>
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
        </div>
      </div>
    </div>
    <div v-if="documentLoaded && !isZenMode && !isReadonly" class="mindmap-command-bar">
      <Toolbar class="command-toolbar" />
      <div class="command-shortcuts" aria-label="常用快捷键提示">
        <span><kbd>Tab</kbd> 子主题</span>
        <span><kbd>Enter</kbd> 同级主题</span>
      </div>
    </div>
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
import { ArrowLeft, Edit as EditIcon, Loading, Check, WarningFilled, Search, Clock, User, Refresh, DocumentChecked } from '@element-plus/icons-vue'
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

const route = useRoute()
const router = useRouter()
const editRef = ref(null)
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
const mindmapName = ref('')
const mindmapDescription = ref('')
const metadataDialogRef = ref(null)
const isZenMode = computed(() => store.localConfig.isZenMode)
const isDark = computed(() => store.localConfig.isDark)
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

function openVersionHistory() {
  actions.setActiveSidebar('versionHistory')
  nextTick(() => bus.emit('focusActiveSidebar'))
}

function openCollaboratorManager() {
  actions.setActiveSidebar('collaboratorManager')
  nextTick(() => bus.emit('focusActiveSidebar'))
}

function goBack() {
  router.push(returnListRoute.value)
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
  const saved = await editRef.value?.flushBeforeLeave?.()
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
  manualSaveRequestId += 1
  manualSaveBusy.value = false
  editRef.value = null
  editorReady.value = false
  mindmapName.value = ''
  mindmapDescription.value = ''
  serverCanEdit.value = null
  serverIsOwner.value = false
  serverAccessType.value = route.query.from === 'shared' ? 'shared' : null
  loadError.value = ''
  contentState.value = 'ready'
  contentStateMessage.value = ''
  documentStatus.value = 0
  terminalDialogShown = false
})

onBeforeUnmount(() => {
  manualSaveRequestId += 1
})
</script>

<style scoped lang="scss">
.mindmap-edit-page {
  --mindmap-shell-top: 60px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f6f8fb;
  overflow: hidden;
  color: #1f2329;

  &.has-command-bar {
    --mindmap-shell-top: 114px;
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
  height: 60px;
  padding: 0 16px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid #e7eaf0;
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
    flex: 1;
    gap: 0;
  }

  .header-right {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    gap: 0;
  }

  .back-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 9px;
    cursor: pointer;
    color: #646a73;
    transition: all 0.2s;
    flex-shrink: 0;
    border: none;
    background: transparent;
    padding: 0;
    outline: none;
    &:hover {
      background: #f0f3f8;
      color: #1f2329;
      transform: translateX(-1px);
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px #3370ff40;
    }
  }

  .header-divider {
    width: 1px;
    height: 24px;
    background: #e5e8ed;
    margin: 0 12px;
    flex-shrink: 0;
  }

  .title-area {
    display: flex;
    align-items: center;
    min-width: 0;
    gap: 10px;
  }

  .document-mark {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: linear-gradient(145deg, #edf4ff 0%, #e7eeff 100%);
    color: #3370ff;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.08);
    flex-shrink: 0;

    .iconfont {
      font-size: 18px;
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
    font-size: 15px;
    line-height: 20px;
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
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    &:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px rgba(51, 112, 255, 0.16);
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
    color: #8f959e;
    font-size: 11px;
    line-height: 15px;
    white-space: nowrap;
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
    gap: 6px;
  }

  .header-icon-btn {
    width: 34px;
    height: 34px;
    border: none;
    border-radius: 9px;
    color: #646a73;
    background: transparent;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 17px;
    transition: background 0.16s ease, color 0.16s ease, transform 0.16s ease;

    &:hover {
      background: #f0f3f8;
      color: #3370ff;
      transform: translateY(-1px);
    }

    &:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px rgba(51, 112, 255, 0.16);
    }
  }

  .realtime-status-group {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .realtime-status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 9px;
    color: #8f6b20;
    background: #fff8e8;
    border: 1px solid #f6dfae;
    border-radius: 999px;
    font-size: 12px;
    white-space: nowrap;

    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #f5a623;
      box-shadow: 0 0 0 3px rgba(245, 166, 35, 0.14);
    }

    &.online {
      color: #257a4a;
      background: #edfbf3;
      border-color: #c9edd8;

      .status-dot {
        background: #2fb66d;
        box-shadow: 0 0 0 3px rgba(47, 182, 109, 0.14);
      }
    }

    &.error {
      color: #b42318;
      background: #fff1f0;
      border-color: #ffc9c5;

      .status-dot {
        background: #e5484d;
        box-shadow: 0 0 0 3px rgba(229, 72, 77, 0.12);
      }
    }
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

  .save-status-group {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .manual-save-btn {
    display: inline-flex;
    height: 30px;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 0 9px;
    border: 1px solid #cddcff;
    border-radius: 999px;
    background: #f5f8ff;
    color: #2f63dc;
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    transition: border-color 0.16s ease, background 0.16s ease, color 0.16s ease;

    &:hover:not(:disabled) {
      border-color: #8eafff;
      background: #edf3ff;
      color: #2454c4;
    }

    &:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px rgba(51, 112, 255, 0.16);
    }

    &:disabled {
      cursor: wait;
      opacity: 0.62;
    }
  }

  .save-status {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    height: 30px;
    color: #646a73;
    background: #f6f7f9;
    border: 1px solid #e7e9ed;
    transition: all 0.2s;
    padding: 0 9px;
    border-radius: 999px;
    &.saving {
      color: #b56500;
      background: #fff8e8;
      border-color: #f6dfae;
    }
    &.pending,
    &.retrying {
      color: #8f6b20;
      background: #fff8e8;
      border-color: #f6dfae;
    }
    &.offline {
      color: #9a3412;
      background: #fff7ed;
      border-color: #fed7aa;
    }
    &.saved {
      color: #257a4a;
      background: #edfbf3;
      border-color: #c9edd8;
    }
    &.error {
      color: #b42318;
      background: #fff1f0;
      border-color: #ffc9c5;
    }
    .save-text {
      white-space: nowrap;
    }
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
    min-width: 72px;
    height: 34px;
    border-radius: 9px;
    cursor: pointer;
    color: #fff;
    transition: all 0.2s;
    font-size: 13px;
    font-weight: 500;
    gap: 6px;
    border: none;
    background: #3370ff;
    padding: 0 13px;
    box-shadow: 0 4px 10px rgba(51, 112, 255, 0.2);
    outline: none;
    &:hover {
      background: #2864e6;
      color: #fff;
      transform: translateY(-1px);
      box-shadow: 0 6px 14px rgba(51, 112, 255, 0.24);
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px #3370ff40;
    }
    .svg-icon {
      width: 15px;
      height: 15px;
    }
  }
}

.mindmap-command-bar {
  height: 54px;
  padding: 0 16px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
  background: #fff;
  border-bottom: 1px solid #e9ebef;
  box-shadow: 0 2px 8px rgba(31, 35, 41, 0.025);
  z-index: 2050;

  .command-toolbar {
    min-width: 0;
    flex: 1;
    position: static;
    pointer-events: auto;
    overflow: hidden;

    :deep(.toolbar) {
      min-width: 0;
      padding: 0;
      justify-content: flex-start;
    }

    :deep(.toolbarBlock) {
      background: transparent;
      box-shadow: none;
      border: none;
      border-radius: 0;
      margin-right: 8px;
      padding: 0 8px 0 0;
      gap: 2px;

      &::after {
        content: '';
        position: absolute;
        width: 1px;
        height: 28px;
        right: 0;
        top: 50%;
        transform: translateY(-50%);
        background: #e7e9ed;
      }

      &:last-of-type::after {
        display: none;
      }
    }

    :deep(.toolbarBtn) {
      min-width: 44px;
      height: 44px;
      margin-right: 2px;
      padding: 4px 7px;
      border-radius: 8px;
      color: #646a73;
      align-items: center;
      justify-content: center;
      transition: background 0.15s ease, color 0.15s ease;

      &:hover:not(.disabled) {
        color: #1f2329;
        background: #f2f5f9;
      }

      &.active {
        color: #3370ff;
        background: #edf4ff;
      }

      &.disabled {
        color: #c5c8ce;
      }

      .icon {
        height: 19px;
        padding: 0;
        border: 0;
        background: transparent;
        color: inherit;
        font-size: 18px;
      }

      .text {
        margin-top: 3px;
        color: inherit;
        font-size: 10px;
        line-height: 12px;
        white-space: nowrap;
      }
    }

    :deep(.toolbarNodeBtnList.v .toolbarBtn) {
      height: 34px;
      min-width: 100%;
      flex-direction: row;
      justify-content: flex-start;
    }
  }

  .command-shortcuts {
    display: flex;
    align-items: center;
    gap: 12px;
    color: #8f959e;
    font-size: 11px;
    white-space: nowrap;

    span {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }

    kbd {
      min-width: 24px;
      height: 20px;
      padding: 0 5px;
      border: 1px solid #dfe2e7;
      border-bottom-width: 2px;
      border-radius: 5px;
      background: #f8f9fb;
      color: #646a73;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font: inherit;
    }
  }
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

  .mindmap-edit-header,
  .mindmap-command-bar {
    background: rgba(35, 38, 43, 0.98);
    border-color: #363a41;
    color: #e5e6eb;
  }

  .mindmap-edit-header {
    .mindmap-title { color: #f0f1f2; }
    .document-meta { color: #92979f; }
    .header-divider { background: #3b3f46; }
    .header-icon-btn {
      color: #afb4bc;
      &:hover { color: #fff; background: #30343a; }
    }
    .save-status {
      color: #b9bec6;
      background: #2c3036;
      border-color: #3b4047;
    }
    .manual-save-btn {
      color: #9bb6ff;
      background: #273248;
      border-color: #3f5684;

      &:hover:not(:disabled) {
        color: #c7d5ff;
        background: #303e59;
        border-color: #6687cc;
      }
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

  .mindmap-command-bar {
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.16);

    .command-toolbar {
      :deep(.toolbarBlock::after) { background: #3b3f46; }
      :deep(.toolbarBtn) {
        color: #b9bec6;
        &:hover:not(.disabled) { color: #fff; background: #30343a; }
        &.active { color: #7da2ff; background: rgba(51, 112, 255, 0.16); }
      }
    }

    .command-shortcuts kbd {
      color: #b9bec6;
      background: #2b2e33;
      border-color: #454950;
    }
  }

  .mindmap-editor-container {
    background: #1e2024;
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

@media (max-width: 1180px) {
  .mindmap-command-bar .command-shortcuts,
  .mindmap-edit-header .realtime-status,
  .mindmap-edit-header .save-status .save-text {
    display: none;
  }

  .mindmap-edit-header .save-status {
    width: 30px;
    justify-content: center;
    padding: 0;
  }
}

@media (max-width: 760px) {
  .mindmap-edit-page {
    --mindmap-shell-top: 54px;

    &.has-command-bar {
      --mindmap-shell-top: 104px;
    }
  }

  .mindmap-edit-header {
    height: 54px;
    padding: 0 10px;

    .document-mark,
    .document-meta,
    .collaborators,
    .header-divider,
    .header-icon-btn:nth-of-type(2),
    .header-icon-btn:nth-of-type(3) {
      display: none;
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

    .manual-save-btn {
      width: 30px;
      padding: 0;

      .manual-save-label {
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

  .mindmap-command-bar {
    height: 50px;
    padding: 0 8px;
  }

  .load-error-actions {
    flex-direction: column;

    :deep(.el-button) {
      width: 100%;
    }
  }
}
</style>
