<template>
  <Sidebar ref="sidebarRef" title="版本历史" open-on-mount>
    <div class="versionHistoryContainer">
      <!-- 预览状态提示 -->
      <div v-if="isPreviewing" class="previewBanner">
        <el-icon><InfoFilled /></el-icon>
        <span>正在预览历史版本</span>
        <el-button type="primary" size="small" @click="exitPreview">
          退出预览
        </el-button>
      </div>
      <div v-if="aiPreviewBlocked" class="previewBanner aiPreviewBlockedBanner">
        <el-icon><InfoFilled /></el-icon>
        <span>AI 正在实时预览，请先采纳或不采纳当前变更后再查看历史版本</span>
      </div>

      <!-- 操作栏 -->
      <div class="actionBar" v-if="!isReadonly">
        <el-button type="primary" size="small" :loading="['confirm-save', 'save'].includes(operationType)" :disabled="isPreviewing || isOperating || aiPreviewBlocked" @click="handleSaveVersion">
          保存正式版本
        </el-button>
      </div>

      <!-- 版本类型切换 -->
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="正式版本" name="formal" :disabled="isPreviewing || isOperating || aiPreviewBlocked" />
        <el-tab-pane label="草稿版本" name="draft" :disabled="isPreviewing || isOperating || aiPreviewBlocked" />
      </el-tabs>

      <!-- 版本列表 -->
      <div class="versionList" v-loading="loading">
        <div v-if="versionList.length === 0 && !loading" class="emptyTip">
          <template v-if="loadError">
            <span role="alert">{{ loadError }}</span>
            <el-button link type="primary" @click="loadVersions">重新加载</el-button>
          </template>
          <template v-else>暂无版本记录</template>
        </div>
        <div
          v-for="item in versionList"
          :key="item.id"
          class="versionItem"
        >
          <div class="versionInfo">
            <div class="versionName">
              {{ item.name || `版本 ${item.versionNumber}` }}
            </div>
            <div class="versionMeta">
              <span>{{ parseTime(item.createdTime) }}</span>
              <span class="versionAuthor">{{ item.createdBy }}</span>
            </div>
          </div>
          <div class="versionActions">
            <el-button link type="primary" size="small" :disabled="isOperating || aiPreviewBlocked" @click="handlePreview(item)">
              查看
            </el-button>
            <el-button link type="primary" size="small" :loading="[`confirm-restore:${item.id}`, `restore:${item.id}`].includes(operationType)" :disabled="isOperating" @click="handleRestore(item)" v-if="!isReadonly">
              恢复
            </el-button>
            <el-button
              link type="danger" size="small"
              :loading="[`confirm-delete:${item.id}`, `delete:${item.id}`].includes(operationType)"
              :disabled="isOperating"
              @click="handleDelete(item)"
              v-if="!isReadonly && Number(item.versionType) === 1"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div class="paginationWrap" v-if="total > pageSize">
        <el-pagination
          size="small"
          layout="prev, pager, next"
          :disabled="isOperating || isPreviewing || aiPreviewBlocked"
          :total="total"
          :page-size="pageSize"
          v-model:current-page="pageNum"
          @current-change="loadVersions"
        />
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { ensureMindmapDocumentPlugins } from '@/utils/mindmap-plugin-loader'
import { store, actions } from './useStore'
import { listVersions, getVersionDetail, restoreVersion, saveFormalVersion, deleteVersion } from '@/api/mindmap/version'
import { getMindmap } from '@/api/mindmap/mindmap'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import bus from './useEventBus'

const props = defineProps({
  mindMap: { type: Object, default: null },
  mindmapId: { type: Number, default: null },
  yjsSync: { type: Object, default: null },
  flushChanges: { type: Function, default: null },
  getContentRevision: { type: Function, default: null },
  getContentChangeVersion: { type: Function, default: null },
  fenceAuthoritativeWrite: { type: Function, default: null },
  applyAuthoritativeDocument: { type: Function, default: null },
  authoritativeResetGeneration: { type: Number, default: 0 },
  readonly: { type: Boolean, default: false },
  aiPreviewActive: { type: Boolean, default: false },
})

const emit = defineEmits(['change-tracking', 'editing-transition'])

const { proxy } = getCurrentInstance()
const sidebarRef = ref(null)
const loading = ref(false)
const loadError = ref('')
const versionList = ref([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const activeTab = ref('formal')
const isReadonly = computed(() => props.readonly || store.isReadonly)
const aiPreviewBlocked = computed(() => props.aiPreviewActive === true)
const isPreviewing = ref(false)
const operationType = ref('')
const isOperating = computed(() => Boolean(operationType.value))
let loadRequestId = 0
let componentActive = true
let operationSequence = 0

// 预览前保存的状态，用于退出预览时恢复
let _prePreviewState = null
let _previewSession = null
let _previewAuthoritativeResetGeneration = 0
let _previewAuthoritativeRecoveryFenced = false
let exitPreviewPromise = null
let _editingTransitionSession = null

function captureSession() {
  return {
    mindmapId: props.mindmapId,
    mindMap: props.mindMap,
    yjsSync: props.yjsSync,
    flushChanges: props.flushChanges,
    getContentRevision: props.getContentRevision,
    getContentChangeVersion: props.getContentChangeVersion,
    fenceAuthoritativeWrite: props.fenceAuthoritativeWrite,
    applyAuthoritativeDocument: props.applyAuthoritativeDocument,
    readonly: isReadonly.value,
  }
}

function beginEditingTransition(session) {
  if (!isCurrentSession(session)) return false
  if (_editingTransitionSession === session) return true
  if (_editingTransitionSession) return false
  _editingTransitionSession = session
  // 父编辑器同步提交当前 Plain/Rich/Outline DOM，再切换只读。该事件
  // 返回后才允许进入任何 HTTP 等待窗口。
  emit('editing-transition', true)
  return true
}

function endEditingTransition(session = _editingTransitionSession) {
  if (!session || _editingTransitionSession !== session) return false
  _editingTransitionSession = null
  emit('editing-transition', false)
  return true
}

function closeSessionEditors(session) {
  bus.emit('closeOutlineEdit')
  session?.mindMap?.renderer?.textEdit?.hideEditTextBox?.()
}

function getSessionContentChangeVersion(session) {
  const version = Number(session?.getContentChangeVersion?.())
  return Number.isSafeInteger(version) && version >= 0 ? version : null
}

async function settleSessionChanges(session, failureMessage) {
  closeSessionEditors(session)
  await nextTick()
  if (!isCurrentSession(session)) return false
  if (session.flushChanges && await session.flushChanges() === false) {
    ElMessage.warning(failureMessage)
    return false
  }
  if (!isCurrentSession(session)) return false

  // flush 的网络等待期间理论上已由 editing-transition 门闩禁止新编辑。
  // 在最终暂停/替换边界仍再收一次所有编辑器；若这一收口推进了代际，
  // 必须重跑 flush，随后以一个无 await 的稳定代际作为线性化点。
  let settledVersion = getSessionContentChangeVersion(session)
  closeSessionEditors(session)
  await nextTick()
  if (!isCurrentSession(session)) return false
  let boundaryVersion = getSessionContentChangeVersion(session)
  if (settledVersion !== null && boundaryVersion !== settledVersion) {
    if (session.flushChanges && await session.flushChanges() === false) {
      ElMessage.warning(failureMessage)
      return false
    }
    if (!isCurrentSession(session)) return false
    settledVersion = getSessionContentChangeVersion(session)
    closeSessionEditors(session)
    await nextTick()
    if (!isCurrentSession(session)) return false
    boundaryVersion = getSessionContentChangeVersion(session)
    if (settledVersion !== null && boundaryVersion !== settledVersion) {
      ElMessage.warning('等待期间检测到新的本地修改，请重试当前操作')
      return false
    }
  }
  return true
}

function isCurrentSession(session) {
  return Boolean(
    session &&
    componentActive &&
    session.mindmapId === props.mindmapId &&
    session.mindMap === props.mindMap &&
    session.yjsSync === props.yjsSync
  )
}

function fencePreviewApplyFailure(session, error) {
  if (_previewAuthoritativeRecoveryFenced) return true
  _previewAuthoritativeRecoveryFenced = true
  const revision = Number(session?.getContentRevision?.())
  const fenced = Number.isSafeInteger(revision)
    && revision > 0
    && session?.fenceAuthoritativeWrite?.(revision) === true
  if (!fenced) {
    console.error('历史预览渲染失败后未能建立权威恢复门闩:', error)
  }
  return fenced
}

function createMutationId() {
  return globalThis.crypto?.randomUUID?.()
    || `mindmap-version-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function getListedVersionId(item, { formalOnly = false } = {}) {
  const id = Number(item?.id)
  if (!Number.isSafeInteger(id) || id <= 0) return null
  const listed = versionList.value.find(version => Number(version.id) === id)
  if (!listed || (formalOnly && Number(listed.versionType) !== 1)) return null
  return id
}

function beginOperation(type) {
  operationSequence += 1
  operationType.value = type
  return operationSequence
}

function updateOperation(token, type) {
  if (token === operationSequence) operationType.value = type
}

function finishOperation(token) {
  if (token === operationSequence) operationType.value = ''
}

const parseTime = (time) => {
  return proxy.parseTime(time)
}

// 监听侧边栏开关
watch(() => store.activeSidebar, (val) => {
  if (val === 'versionHistory') {
    loadVersions()
    sidebarRef.value?.open()
  } else {
    // 侧边栏关闭时，如果正在预览则退出预览恢复数据
    if (isPreviewing.value) {
      exitPreview()
    }
    sidebarRef.value?.close()
  }
}, { immediate: true })

function onTabChange() {
  pageNum.value = 1
  loadVersions()
}

async function loadVersions() {
  if (!props.mindmapId || !componentActive) return
  const requestId = ++loadRequestId
  loading.value = true
  loadError.value = ''
  try {
    const versionType = activeTab.value === 'formal' ? 1 : 0
    const res = await listVersions(props.mindmapId, {
      versionType,
      pageNum: pageNum.value,
      pageSize: pageSize.value,
    })
    if (requestId !== loadRequestId || !componentActive) return
    versionList.value = res.rows || []
    total.value = res.total || 0
  } catch (e) {
    if (requestId !== loadRequestId || !componentActive) return
    console.error('加载版本列表失败:', e)
    versionList.value = []
    total.value = 0
    loadError.value = e?.message || '版本列表加载失败'
  } finally {
    if (requestId === loadRequestId && componentActive) loading.value = false
  }
}

async function handleSaveVersion() {
  if (!props.mindmapId || isReadonly.value || aiPreviewBlocked.value || isOperating.value || isPreviewing.value) return
  const session = captureSession()
  const operationToken = beginOperation('confirm-save')
  let versionName
  let editingTransitionStarted = false
  try {
    const { value } = await ElMessageBox.prompt('请输入版本名称（可选）', '保存正式版本', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPlaceholder: '版本名称',
      inputValidator: value => !value || value.trim().length <= 200 || '版本名称不能超过 200 个字符',
      inputErrorMessage: '版本名称不能超过 200 个字符',
    })
    versionName = value
  } catch {
    finishOperation(operationToken)
    return
  }
  if (!isCurrentSession(session)) {
    finishOperation(operationToken)
    return
  }
  updateOperation(operationToken, 'save')
  try {
    editingTransitionStarted = beginEditingTransition(session)
    if (!editingTransitionStarted) return
    if (!await settleSessionChanges(
      session,
      '当前修改尚未成功保存，暂不能创建正式版本',
    )) return
    await saveFormalVersion({
      mindmapId: session.mindmapId,
      name: versionName?.trim() || undefined,
    })
    if (!isCurrentSession(session)) return
    ElMessage.success('正式版本保存成功')
    await loadVersions()
  } catch (error) {
    if (!isCurrentSession(session)) return
    console.error('保存版本失败:', error)
    ElMessage.error('保存版本失败')
  } finally {
    if (editingTransitionStarted) endEditingTransition(session)
    finishOperation(operationToken)
  }
}

async function handlePreview(item) {
  if (!props.mindMap || isOperating.value) return
  if (aiPreviewBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再查看历史版本')
    return
  }
  const versionId = getListedVersionId(item)
  if (!versionId) return
  const session = captureSession()
  const operationToken = beginOperation(`preview:${versionId}`)
  let editingTransitionStarted = false
  try {
    // 如果已经在预览中，先退出上一次预览
    if (isPreviewing.value) {
      await exitPreview()
    }
    if (!isCurrentSession(session)) return
    editingTransitionStarted = beginEditingTransition(session)
    if (!editingTransitionStarted) return

    const res = await getVersionDetail(versionId)
    if (!isCurrentSession(session)) return
    const versionData = res.data
    if (versionData?.nodeTree && session.mindMap) {
      // 历史预览会暂停 Yjs 和自动保存。只有当前编辑批次已经完整落云后，
      // 才能把实时树换成历史树；否则预览期间到达的 reset/stale 事件可能
      // 把历史树误当成待保护草稿，或正常退出后让原修改永久失去自动保存。
      if (!await settleSessionChanges(
        session,
        '当前修改尚未成功保存，暂不能预览历史版本',
      )) return
      // 保存当前实时状态，用于退出预览时恢复
      _prePreviewState = session.mindMap.getData(true)
      _previewSession = session
      _previewAuthoritativeResetGeneration = props.authoritativeResetGeneration
      _previewAuthoritativeRecoveryFenced = false
      isPreviewing.value = true
      emit('change-tracking', true)

      // 编辑器已提交并释放租约，再切只读和暂停实时同步。
      session.mindMap.setMode?.('readonly')
      // 暂停 Yjs 同步，防止预览数据广播给协作者
      if (session.yjsSync) {
        session.yjsSync.pause()
      }

      // 以版本数据替换当前显示
      const previewApplied = await applyFullDataAndWait({
        root: versionData.nodeTree,
        layout: versionData.layout,
        theme: versionData.theme,
        view: versionData.viewData,
      }, 1500, session.mindMap, () => (
        isCurrentSession(session)
        && _editingTransitionSession === session
        && !hasAuthoritativeResetSincePreview()
      ))
      if (previewApplied === false) {
        await exitPreview({ notify: false })
        return
      }
      if (!isCurrentSession(session)) return
      ElMessage.info('正在预览版本，点击"退出预览"或关闭侧边栏可恢复')
    }
  } catch (e) {
    if (isPreviewing.value && isCurrentSession(session)) {
      fencePreviewApplyFailure(session, e)
    }
    if (isPreviewing.value) {
      await exitPreview({ notify: false })
    }
    if (isCurrentSession(session)) {
      console.error('预览版本失败:', e)
      ElMessage.error('预览版本失败')
    }
  } finally {
    if (editingTransitionStarted && !isPreviewing.value) {
      endEditingTransition(session)
    }
    finishOperation(operationToken)
  }
}

async function applyFullDataAndWait(
  data,
  timeout = 1500,
  mindMap = props.mindMap,
  shouldApply = () => true,
) {
  if (!mindMap) return Promise.resolve()
  await ensureMindmapDocumentPlugins(data, mindMap)
  if (!shouldApply()) return false
  return new Promise((resolve, reject) => {
    let settled = false
    let timer = null
    const finish = (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      mindMap.off?.('node_tree_render_end', onRenderEnd)
      if (error) reject(error)
      else resolve()
    }
    const onRenderEnd = () => finish()
    mindMap.on?.('node_tree_render_end', onRenderEnd)
    timer = setTimeout(() => finish(), timeout)
    try {
      mindMap.setFullData(data)
    } catch (error) {
      finish(error)
    }
  })
}

function hasAuthoritativeResetSincePreview() {
  return (
    _previewAuthoritativeRecoveryFenced
    ||
    props.authoritativeResetGeneration !== _previewAuthoritativeResetGeneration
    || !isCurrentSession(_previewSession)
  )
}

function exitPreview({ notify = true } = {}) {
  if (exitPreviewPromise) return exitPreviewPromise
  if (!isPreviewing.value) return Promise.resolve()
  const state = _prePreviewState
  const previewSession = _previewSession
  exitPreviewPromise = (async () => {
    let authoritativeResetPending = hasAuthoritativeResetSincePreview()
    try {
      if (state && !authoritativeResetPending) {
        try {
          await applyFullDataAndWait(
            state,
            1500,
            previewSession?.mindMap,
            () => !hasAuthoritativeResetSincePreview(),
          )
        } catch (error) {
          // 恢复预览前快照也可能在 renderer 半应用后失败。此时不能 resume
          // 旧 Y.Doc 或解除为它建立的交互门闩；切换到父级权威 GET 恢复。
          fencePreviewApplyFailure(previewSession, error)
          authoritativeResetPending = true
          console.error('退出历史预览时恢复实时画布失败:', error)
          if (notify && isCurrentSession(previewSession)) {
            ElMessage.warning('实时画布恢复失败，正在从服务器重新加载')
          }
        }
      }
      authoritativeResetPending = hasAuthoritativeResetSincePreview()
      if (notify && isCurrentSession(previewSession)) {
        if (authoritativeResetPending) {
          ElMessage.info('云端版本已更新，正在退出预览并同步最新画布')
        } else {
          ElMessage.success('已恢复到编辑状态')
        }
      }
    } finally {
      authoritativeResetPending = hasAuthoritativeResetSincePreview()
      // reset 已让旧 Yjs 建立 authoritative fence。此时既不能恢复预览前
      // 快照，也不能 resume 旧实例；父编辑器会在 tracking 恢复后以完整
      // HTTP 文档重建画布和协作实例。
      if (!authoritativeResetPending) previewSession?.yjsSync?.resume()
      _prePreviewState = null
      _previewSession = null
      _previewAuthoritativeResetGeneration = 0
      isPreviewing.value = false
      emit('change-tracking', false, { authoritativeResetPending })
      endEditingTransition(previewSession)
      _previewAuthoritativeRecoveryFenced = false
      exitPreviewPromise = null
    }
  })()
  return exitPreviewPromise
}

onBeforeUnmount(() => {
  componentActive = false
  loadRequestId += 1
  operationSequence += 1
  operationType.value = ''
  if (isPreviewing.value) void exitPreview({ notify: false })
  else endEditingTransition()
})

async function handleRestore(item) {
  if (isReadonly.value || aiPreviewBlocked.value || isOperating.value) return
  const versionId = getListedVersionId(item)
  if (!versionId) return
  const session = captureSession()
  const operationToken = beginOperation(`confirm-restore:${versionId}`)
  let editingTransitionStarted = false
  let changeTrackingStarted = false
  try {
    await ElMessageBox.confirm(
      `确认恢复到「${item.name || '版本 ' + item.versionNumber}」？当前修改会先保存，随后以该版本替换当前内容。历史预览使用当时标签样式；恢复后将按当前标签定义显示。`,
      '确认恢复',
      { type: 'warning' }
    )
  } catch {
    finishOperation(operationToken)
    return // 用户取消
  }
  if (!isCurrentSession(session) || getListedVersionId(item) !== versionId) {
    finishOperation(operationToken)
    return
  }

  updateOperation(operationToken, `restore:${versionId}`)
  try {
    // 如果正在预览，先退出预览
    if (isPreviewing.value) {
      await exitPreview()
    }

    if (!isCurrentSession(session)) return
    editingTransitionStarted = beginEditingTransition(session)
    if (!editingTransitionStarted) return
    if (!await settleSessionChanges(
      session,
      '当前修改尚未成功保存，暂不能恢复历史版本',
    )) return

    // flush 可能刚提交了一批本地编辑，因此在它完成后冻结当前权威 revision。
    // 恢复请求通过 CAS 拒绝随后到达的协作者保存，不能用额外 GET 把基线
    // 静默抬高；同一个 mutationId 则让传输层重试保持幂等。
    const expectedRevision = Number(session.getContentRevision?.())
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision <= 0) {
      ElMessage.warning('当前云端版本尚未确认，暂不能恢复历史版本')
      return
    }
    const clientMutationId = createMutationId()
    emit('change-tracking', true)
    changeTrackingStarted = true

    // 第一步：后端恢复（不可逆操作）
    const restoreResponse = await restoreVersion(versionId, {
      expectedRevision,
      clientMutationId,
    })
    const restoredRevision = restoreResponse.data?.contentRevision
    if (!isCurrentSession(session)) return
    if (session.fenceAuthoritativeWrite?.(restoredRevision) !== true) {
      throw new Error('版本已恢复，但当前画布未能进入安全重载状态')
    }
    ElMessage.success('版本恢复成功')

    // 第二步：获取恢复后的数据并更新本地显示
    // 即使此步骤失败，后端恢复已成功，不算整体失败
    if (session.mindMap) {
      try {
        const res = await getMindmap(session.mindmapId)
        if (!isCurrentSession(session)) return
        const versionData = res.data
        if (versionData?.nodeTree) {
          if (typeof session.applyAuthoritativeDocument !== 'function') {
            throw new Error('编辑器未提供权威文档应用入口')
          }
          // 恢复写请求已经返回了新的 revision，但紧随其后的详情读取仍可能
          // 命中滞后副本。不要把旧树改标成 restoredRevision；由编辑器把写
          // 响应 revision 作为独立下限校验，等真正的新快照到达后再应用。
          const applied = await session.applyAuthoritativeDocument(versionData, {
            minimumContentRevision: restoredRevision,
          })
          if (!isCurrentSession(session)) return
          if (applied !== true) throw new Error('服务器恢复结果尚未应用到当前画布')
        }
      } catch (fetchErr) {
        if (!isCurrentSession(session)) return
        console.warn('恢复成功但获取版本详情失败，请刷新页面:', fetchErr)
        ElMessage.warning('版本已恢复，但获取详情失败，建议刷新页面')
        // 后端已经广播 document_reset。这里不能用恢复前的本地树重建
        // Yjs；父编辑器会通过 reset 队列继续加载完整权威文档。
      }
    }
    await loadVersions()
  } catch (e) {
    if (!isCurrentSession(session)) return
    console.error('恢复版本失败:', e)
    ElMessage.error('恢复版本失败')
  } finally {
    if (changeTrackingStarted) emit('change-tracking', false)
    if (editingTransitionStarted) endEditingTransition(session)
    finishOperation(operationToken)
  }
}

async function handleDelete(item) {
  if (isReadonly.value || aiPreviewBlocked.value || isOperating.value) return
  const versionId = getListedVersionId(item, { formalOnly: true })
  if (!versionId) return
  const session = captureSession()
  const operationToken = beginOperation(`confirm-delete:${versionId}`)
  try {
    await ElMessageBox.confirm(
      `确认删除「${item.name || '版本 ' + item.versionNumber}」？此操作不可撤销。`,
      '确认删除',
      { type: 'warning' }
    )
    if (!isCurrentSession(session) || getListedVersionId(item, { formalOnly: true }) !== versionId) return
    updateOperation(operationToken, `delete:${versionId}`)
    await deleteVersion(versionId)
    if (!isCurrentSession(session)) return
    ElMessage.success('版本删除成功')
    await loadVersions()
    if (versionList.value.length === 0 && pageNum.value > 1) {
      pageNum.value -= 1
      await loadVersions()
    }
  } catch (e) {
    if (isCurrentSession(session) && e !== 'cancel' && e !== 'close') {
      console.error('删除版本失败:', e)
      ElMessage.error('删除版本失败')
    }
  } finally {
    finishOperation(operationToken)
  }
}
</script>

<style lang="scss" scoped>
.versionHistoryContainer {
  padding: 12px;

  .previewBanner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #edf4ff;
    border: 1px solid #b3ccff;
    border-radius: 6px;
    margin-bottom: 12px;
    font-size: 12px;
    color: #3370ff;

    .el-button {
      margin-left: auto;
    }
  }

  .actionBar {
    margin-bottom: 12px;
    text-align: center;
  }

  :deep(.el-tabs) {
    .el-tabs__header {
      margin-bottom: 8px;
    }
    .el-tabs__nav-wrap::after {
      height: 1px;
      background: #f0f1f3;
    }
    .el-tabs__item {
      font-size: 13px;
      color: #646a73;
      &.is-active {
        color: #3370ff;
        font-weight: 500;
      }
    }
    .el-tabs__active-bar {
      background-color: #3370ff;
      height: 2px;
    }
  }

  .versionList {
    min-height: 100px;
    max-height: calc(100vh - 320px);
    overflow-y: auto;
    &::-webkit-scrollbar {
      width: 4px;
    }
    &::-webkit-scrollbar-thumb {
      background: #d4d6d9;
      border-radius: 4px;
    }
  }

  .emptyTip {
    text-align: center;
    color: #8f959e;
    padding: 40px 0;
    font-size: 13px;
  }

  .versionItem {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 8px;
    border-radius: 6px;
    transition: background 0.15s;
    margin-bottom: 2px;

    &:hover {
      background: #f5f6f7;
    }

    .versionInfo {
      flex: 1;
      min-width: 0;

      .versionName {
        font-size: 13px;
        font-weight: 500;
        color: #1f2329;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .versionMeta {
        font-size: 12px;
        color: #8f959e;
        margin-top: 4px;
        display: flex;
        gap: 8px;
      }
    }

    .versionActions {
      flex-shrink: 0;
      margin-left: 8px;
      opacity: 0;
      transition: opacity 0.15s;
    }

    &:hover .versionActions {
      opacity: 1;
    }
  }

  .paginationWrap {
    display: flex;
    justify-content: center;
    margin-top: 12px;
  }
}
</style>
