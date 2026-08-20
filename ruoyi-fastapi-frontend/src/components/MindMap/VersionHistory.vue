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

      <!-- 操作栏 -->
      <div class="actionBar" v-if="!isReadonly">
        <el-button type="primary" size="small" :loading="['confirm-save', 'save'].includes(operationType)" :disabled="isPreviewing || isOperating" @click="handleSaveVersion">
          保存正式版本
        </el-button>
      </div>

      <!-- 版本类型切换 -->
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="正式版本" name="formal" :disabled="isPreviewing || isOperating" />
        <el-tab-pane label="草稿版本" name="draft" :disabled="isPreviewing || isOperating" />
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
            <el-button link type="primary" size="small" :disabled="isOperating" @click="handlePreview(item)">
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
          :disabled="isOperating || isPreviewing"
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
  readonly: { type: Boolean, default: false },
})

const emit = defineEmits(['yjs-reinit', 'change-tracking'])

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
const isPreviewing = ref(false)
const operationType = ref('')
const isOperating = computed(() => Boolean(operationType.value))
let loadRequestId = 0
let componentActive = true
let operationSequence = 0

// 预览前保存的状态，用于退出预览时恢复
let _prePreviewState = null
let _previewSession = null
let exitPreviewPromise = null

function captureSession() {
  return {
    mindmapId: props.mindmapId,
    mindMap: props.mindMap,
    yjsSync: props.yjsSync,
    flushChanges: props.flushChanges,
    readonly: isReadonly.value,
  }
}

function isCurrentSession(session) {
  return Boolean(
    session &&
    componentActive &&
    session.mindmapId === props.mindmapId &&
    session.mindMap === props.mindMap
  )
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
  if (!props.mindmapId || isOperating.value || isPreviewing.value) return
  const session = captureSession()
  const operationToken = beginOperation('confirm-save')
  let versionName
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
    if (session.flushChanges && await session.flushChanges() === false) {
      ElMessage.warning('当前修改尚未成功保存，暂不能创建正式版本')
      return
    }
    if (!isCurrentSession(session)) return
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
    finishOperation(operationToken)
  }
}

async function handlePreview(item) {
  if (!props.mindMap || isOperating.value) return
  const versionId = getListedVersionId(item)
  if (!versionId) return
  const session = captureSession()
  const operationToken = beginOperation(`preview:${versionId}`)
  try {
    // 如果已经在预览中，先退出上一次预览
    if (isPreviewing.value) {
      await exitPreview()
    }

    const res = await getVersionDetail(versionId)
    if (!isCurrentSession(session)) return
    const versionData = res.data
    if (versionData?.nodeTree && session.mindMap) {
      // 保存当前实时状态，用于退出预览时恢复
      _prePreviewState = session.mindMap.getData(true)
      _previewSession = session
      isPreviewing.value = true
      emit('change-tracking', true)

      // 暂停 Yjs 同步，防止预览数据广播给协作者
      if (session.yjsSync) {
        session.yjsSync.pause()
      }
      session.mindMap.setMode?.('readonly')

      // 以版本数据替换当前显示
      await applyFullDataAndWait({
        root: versionData.nodeTree,
        layout: versionData.layout,
        theme: versionData.theme,
        view: versionData.viewData,
      }, 1500, session.mindMap)
      if (!isCurrentSession(session)) return
      ElMessage.info('正在预览版本，点击"退出预览"或关闭侧边栏可恢复')
    }
  } catch (e) {
    if (isPreviewing.value) {
      await exitPreview({ notify: false })
    }
    if (isCurrentSession(session)) {
      console.error('预览版本失败:', e)
      ElMessage.error('预览版本失败')
    }
  } finally {
    finishOperation(operationToken)
  }
}

async function applyFullDataAndWait(data, timeout = 1500, mindMap = props.mindMap) {
  if (!mindMap) return Promise.resolve()
  await ensureMindmapDocumentPlugins(data, mindMap)
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

function exitPreview({ notify = true } = {}) {
  if (exitPreviewPromise) return exitPreviewPromise
  if (!isPreviewing.value) return Promise.resolve()
  const state = _prePreviewState
  const previewSession = _previewSession
  exitPreviewPromise = (async () => {
    try {
      if (state) await applyFullDataAndWait(state, 1500, previewSession?.mindMap)
      if (notify && isCurrentSession(previewSession)) ElMessage.success('已恢复到编辑状态')
    } finally {
      previewSession?.yjsSync?.resume()
      const readonly = isCurrentSession(previewSession) ? isReadonly.value : previewSession?.readonly
      previewSession?.mindMap?.setMode?.(readonly ? 'readonly' : 'edit')
      _prePreviewState = null
      _previewSession = null
      isPreviewing.value = false
      emit('change-tracking', false)
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
})

async function handleRestore(item) {
  if (isOperating.value) return
  const versionId = getListedVersionId(item)
  if (!versionId) return
  const session = captureSession()
  const operationToken = beginOperation(`confirm-restore:${versionId}`)
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

    if (session.flushChanges && await session.flushChanges() === false) {
      ElMessage.warning('当前修改尚未成功保存，暂不能恢复历史版本')
      return
    }
    if (!isCurrentSession(session)) return

    // 第一步：后端恢复（不可逆操作）
    const restoreResponse = await restoreVersion(versionId)
    const restoredRevision = restoreResponse.data?.contentRevision
    if (!isCurrentSession(session)) return
    ElMessage.success('版本恢复成功')

    // 第二步：获取恢复后的数据并更新本地显示
    // 即使此步骤失败，后端恢复已成功，不算整体失败
    if (session.mindMap) {
      try {
        const res = await getMindmap(session.mindmapId)
        if (!isCurrentSession(session)) return
        const versionData = res.data
        if (versionData?.nodeTree) {
          emit('change-tracking', true)
          try {
            await applyFullDataAndWait({
              root: versionData.nodeTree,
              layout: versionData.layout,
              theme: versionData.theme,
              view: versionData.viewData,
            }, 1500, session.mindMap)
            if (!isCurrentSession(session)) return
            // 通知父组件重新初始化 Yjs，使协作者也看到恢复后的内容
            emit('yjs-reinit', versionData.nodeTree, versionData.contentRevision || restoredRevision)
          } finally {
            emit('change-tracking', false)
          }
        }
      } catch (fetchErr) {
        if (!isCurrentSession(session)) return
        console.warn('恢复成功但获取版本详情失败，请刷新页面:', fetchErr)
        ElMessage.warning('版本已恢复，但获取详情失败，建议刷新页面')
        // 后端已经广播 document_reset。这里不能用恢复前的本地树重建
        // Yjs，否则会把刚完成的服务端恢复再次覆盖。
      }
    }
    await loadVersions()
  } catch (e) {
    if (!isCurrentSession(session)) return
    console.error('恢复版本失败:', e)
    ElMessage.error('恢复版本失败')
  } finally {
    finishOperation(operationToken)
  }
}

async function handleDelete(item) {
  if (isOperating.value) return
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
