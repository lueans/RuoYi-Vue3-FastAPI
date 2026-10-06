<template>
  <el-popover
    v-model:visible="visible"
    placement="bottom-end"
    :width="360"
    trigger="click"
    popper-class="mindmapAiTaskCenterPopper"
    @show="refreshTasks()"
  >
    <template #reference>
      <button
        type="button"
        class="mindmapAiTaskCenterTrigger right-menu-item hover-effect"
        :aria-label="attentionCount ? `打开 AI 任务中心，${attentionCount} 个运行中、待处理或未读会话` : '打开 AI 任务中心'"
        :aria-expanded="visible"
      >
        <el-icon aria-hidden="true"><Bell /></el-icon>
        <span v-if="attentionCount" class="mindmapAiTaskBadge" aria-hidden="true">
          {{ attentionCount > 99 ? '99+' : attentionCount }}
        </span>
      </button>
    </template>

    <section class="mindmapAiTaskCenter" aria-label="AI 任务中心">
      <header class="mindmapAiTaskCenterHeader">
        <div>
          <strong>AI 任务中心</strong>
          <span>红点统计运行中、待处理和未读结果</span>
        </div>
        <button
          type="button"
          class="mindmapAiTaskCenterRefresh"
          :disabled="loading || authExpired"
          aria-label="刷新 AI 任务"
          @click="refreshTasks()"
        >
          <el-icon :class="{ 'is-loading': loading }"><Refresh /></el-icon>
        </button>
      </header>

      <div v-if="authExpired" class="mindmapAiTaskCenterState is-error" role="status">
        <span>登录已过期，任务同步已暂停。</span>
        <button type="button" @click="requestRelogin">重新登录</button>
      </div>
      <div v-else-if="error" class="mindmapAiTaskCenterState is-error" role="alert">
        <span>{{ error }}</span>
        <button type="button" @click="refreshTasks()">重试</button>
      </div>
      <div v-else-if="loading && !tasks.length" class="mindmapAiTaskCenterState" role="status">
        正在同步任务…
      </div>
      <div v-else-if="!tasks.length" class="mindmapAiTaskCenterState">
        <strong>暂时没有 AI 任务</strong>
        <span>在脑图中发起 AI 编辑后，任务会显示在这里。</span>
      </div>
      <ol v-else class="mindmapAiTaskList">
        <li v-for="item in tasks" :key="item.sessionId" class="mindmapAiTaskItem">
          <button
            type="button"
            class="mindmapAiTaskItemButton"
            :disabled="!item.canOpen"
            :title="item.canOpen ? `打开${item.documentLabel} · ${item.summary}` : item.unavailableReason"
            @click="openTask(item)"
          >
            <span class="mindmapAiTaskStatus" :class="`is-${item.statusTone}`" aria-hidden="true">
              <i></i>
            </span>
            <span class="mindmapAiTaskCopy">
              <strong>{{ item.documentLabel }}</strong>
              <span class="mindmapAiTaskTitle">{{ item.title }}</span>
              <small>{{ item.statusLabel }} · {{ item.summary }}</small>
            </span>
            <el-icon class="mindmapAiTaskArrow" aria-hidden="true"><ArrowRight /></el-icon>
          </button>
          <button v-if="item.canAcknowledge" type="button" class="mindmapAiTaskRead"
            :disabled="acknowledgingJobId === item.jobId" @click="acknowledgeTask(item)">标为已读</button>
        </li>
      </ol>
      <nav v-if="total > pageSize" class="mindmapAiTaskPagination" aria-label="AI 任务分页">
        <button type="button" :disabled="loading || page <= 1" @click="refreshTasks(page - 1)">上一页</button>
        <span role="status">第 {{ page }} / {{ pageCount }} 页 · 共 {{ total }} 个会话</span>
        <button type="button" :disabled="loading || page >= pageCount" @click="refreshTasks(page + 1)">下一页</button>
      </nav>
      <footer v-if="tasks.length" class="mindmapAiTaskCenterFooter">
        <span>后台任务会继续运行，关闭入口不会停止任务。</span>
      </footer>
    </section>
  </el-popover>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, Bell, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { listMindmapAiSessions, acknowledgeMindmapAiTask } from '@/api/mindmap/mindmap'
import { formatMindmapAiError } from '@/utils/mindmap-ai-errors'
import useUserStore from '@/store/modules/user'
import { requestRelogin } from '@/utils/request'
import { useMindmapAuthExpiry } from '@/utils/use-mindmap-auth-expiry'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const authExpired = useMindmapAuthExpiry(() => userStore.token, stopForAuthExpiry)
const visible = ref(false)
const loading = ref(false)
const error = ref('')
const rawSessions = ref([])
const pageSize = 20
const page = ref(1)
const total = ref(0)
const serverAttentionTotal = ref(null)
const acknowledgingJobId = ref('')
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
let refreshTimer = null
let requestController = null
let componentAlive = true

const ACTIVE_STATUSES = new Set([
  'queued', 'waiting_turn', 'preparing', 'running', 'validating', 'cancel_requested',
])
const ATTENTION_STATUSES = new Set([
  'ready', 'needs_review', 'needs_input', 'completed_message', 'failed',
  'cancelled', 'stale', 'expired',
  'rejected',
])
const ACTION_REQUIRED_STATUSES = new Set(['ready', 'needs_review', 'needs_input'])
const STATUS_LABELS = {
  queued: '已排队',
  waiting_turn: '等待上一轮结果确认保存',
  preparing: '正在准备',
  running: '正在编辑脑图',
  validating: '正在校验结果',
  cancel_requested: '正在停止',
  ready: '已完成并保留结果',
  needs_review: '等待你确认',
  needs_input: '需要补充信息',
  completed_message: 'AI 已回复',
  failed: '本轮未完成',
  cancelled: '任务已停止',
  stale: '需要重新确认版本',
  expired: '结果已过期',
  completed_file: '已保存为云端脑图',
  completed_direct: 'AI 已直接更新云端脑图',
  completed_no_change: '未发现需要应用的变化',
  applied: '结果已应用',
  undone: '结果已撤销',
  rejected: '本轮变更未采纳',
}

const tasks = computed(() => rawSessions.value
  .map(normalizeTask)
  .filter(Boolean)
  .sort((left, right) => {
    const toneRank = { attention: 0, active: 1, quiet: 2 }
    const toneDifference = toneRank[left.statusTone] - toneRank[right.statusTone]
    if (toneDifference) return toneDifference
    return String(right.updateTime || '').localeCompare(String(left.updateTime || ''))
  }))

const attentionCount = computed(() => serverAttentionTotal.value ?? tasks.value.filter(item => (
  item.statusTone === 'active' || item.statusTone === 'attention'
)).length)

function normalizeTask(session) {
  if (!session?.sessionId) return null
  const job = session.currentJob || {}
  const status = String(job.status || session.status || '').trim()
  const sourceMindmapId = Number(job.sourceMindmapId)
  const hasMindmapId = Number.isSafeInteger(sourceMindmapId) && sourceMindmapId > 0
  const resultMindmapId = Number(session.resultMindmapId ?? job.resultMindmapId)
  const hasResultMindmapId = Number.isSafeInteger(resultMindmapId) && resultMindmapId > 0
  const openResult = status === 'completed_file' && hasResultMindmapId
  const documentAccessible = session.mindmapAccessible !== false
  const standalone = !hasMindmapId && ['none', 'uploaded_artifact', 'local_snapshot'].includes(job.sourceType)
  const canOpen = openResult
    ? session.resultMindmapAccessible !== false
    : documentAccessible && (hasMindmapId || standalone)
  const destinationMindmapId = openResult ? resultMindmapId : sourceMindmapId
  const documentLabel = String(
    (openResult ? session.resultMindmapName : session.mindmapName)
      || (standalone && !openResult ? '独立 AI 脑图任务'
        : canOpen ? `脑图 #${destinationMindmapId}` : openResult ? '无法访问的结果脑图' : '无法访问的脑图'),
  ).trim()
  const title = String(session.title || job.title || 'AI 对话').trim() || 'AI 对话'
  const statusTone = ACTIVE_STATUSES.has(status)
    ? 'active'
    : ATTENTION_STATUSES.has(status) && (ACTION_REQUIRED_STATUSES.has(status) || !session.taskAcknowledged) ? 'attention' : 'quiet'
  return {
    sessionId: String(session.sessionId),
    jobId: String(job.id || ''),
    sourceMindmapId: canOpen ? sourceMindmapId : null,
    destinationMindmapId: canOpen ? destinationMindmapId : null,
    openResult,
    standalone,
    documentLabel,
    title,
    status,
    statusTone,
    canAcknowledge: ATTENTION_STATUSES.has(status) && !ACTION_REQUIRED_STATUSES.has(status) && !session.taskAcknowledged,
    statusLabel: STATUS_LABELS[status] || status || '等待开始',
    summary: summarizeJob(job, status),
    updateTime: session.updateTime || job.updateTime || '',
    canOpen: canOpen && Boolean(job.id),
    unavailableReason: canOpen ? '' : '当前账号已无法访问这张脑图或任务缺少有效来源',
  }
}

function summarizeJob(job, status) {
  const messageOnly = job.target === 'message' || job.intent === 'discuss'
  const direct = job.executionMode === 'direct' && job.sourceType === 'cloud_document'
  const fileResult = job.target === 'file' && !direct
  const localProposal = job.sourceType === 'local_snapshot' && job.target === 'proposal'
  if (status === 'running' || status === 'validating') {
    if (messageOnly) return status === 'validating' ? '正在整理回复' : '正在生成回复'
    return status === 'validating' ? '正在校验生成结果' : '正在持续运行'
  }
  if (status === 'waiting_turn') return '等待上一轮结果确认保存'
  if (status === 'needs_review') {
    return localProposal ? '请回到原本地脑图查看差异并确认' : '请查看差异后确认是否采纳'
  }
  if (status === 'needs_input') return 'AI 正在等待你的回答'
  if (status === 'failed') {
    return formatMindmapAiError({ errorCode: job.errorCode }, '可重试或切换 Agent')
  }
  if (status === 'cancelled') return '可查看本轮记录并重试'
  if (status === 'rejected') return '本轮变更未采纳，可查看执行记录'
  if (status === 'completed_direct') return '权威正文已保存，页面关闭后任务也不会中断'
  if (status === 'ready') {
    if (fileResult || ['none', 'uploaded_artifact'].includes(job.sourceType)) {
      return '结果已生成，可查看、下载或另存'
    }
    if (localProposal) return '可查看或下载结果；采纳修改请回到原本地脑图'
    return direct ? '可打开脑图确认保存结果' : '可查看结果与变更，确认是否采纳'
  }
  return '点击进入查看详情'
}

async function refreshTasks(requestedPage = page.value) {
  if (!componentAlive || authExpired.value || loading.value) return
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  error.value = ''
  try {
    let targetPage = Number.isSafeInteger(requestedPage) ? Math.max(1, requestedPage) : page.value
    let response = await listMindmapAiSessions({
      limit: pageSize, page: targetPage, taskCenter: true, signal: controller.signal,
    })
    if (!componentAlive || authExpired.value || controller.signal.aborted) return
    const lastPage = Math.max(1, Math.ceil((Number(response?.data?.total) || 0) / pageSize))
    // A session may have been deleted in another tab while viewing the last page.
    if (targetPage > lastPage) {
      targetPage = lastPage
      response = await listMindmapAiSessions({
        limit: pageSize, page: targetPage, taskCenter: true, signal: controller.signal,
      })
    }
    if (!componentAlive || authExpired.value || controller.signal.aborted) return
    rawSessions.value = Array.isArray(response?.data?.items) ? response.data.items : []
    page.value = targetPage
    total.value = Math.max(0, Number(response?.data?.total) || 0)
    const count = response?.data?.attentionTotal
    serverAttentionTotal.value = Number.isSafeInteger(count) && count >= 0 ? count : null
  } catch (requestError) {
    if (!componentAlive || authExpired.value || controller.signal.aborted) return
    error.value = formatMindmapAiError(requestError, 'AI 任务暂时无法同步')
  } finally {
    if (requestController === controller) requestController = null
    if (componentAlive) loading.value = false
  }
}

function scheduleRefresh() {
  clearTimeout(refreshTimer)
  refreshTimer = null
  if (!componentAlive || authExpired.value) return
  refreshTimer = setTimeout(async () => {
    refreshTimer = null
    await refreshTasks()
    if (componentAlive) scheduleRefresh()
  }, 15_000)
}

function onWindowFocus() {
  void refreshTasks()
}

async function acknowledgeTask(item) {
  if (authExpired.value || !item?.canAcknowledge || acknowledgingJobId.value) return
  const ownerId = String(userStore.id)
  acknowledgingJobId.value = item.jobId
  try {
    await acknowledgeMindmapAiTask(item.jobId, item.status)
    if (!componentAlive || ownerId !== String(userStore.id) || authExpired.value) return
    rawSessions.value = rawSessions.value.map(session => session.currentJob?.id === item.jobId
      && session.currentJob?.status === item.status ? { ...session, taskAcknowledged: true } : session)
    await refreshTasks()
  } catch (failure) {
    if (componentAlive && ownerId === String(userStore.id)) error.value = formatMindmapAiError(failure, '未能标记已读，请刷新后重试')
  } finally { if (ownerId === String(userStore.id)) acknowledgingJobId.value = '' }
}

function openTask(item) {
  if (authExpired.value || !item?.canOpen || !item.jobId) return
  if (item.canAcknowledge) void acknowledgeTask(item)
  visible.value = false
  const currentMindmapId = Number(route.query?.id)
  if (item.openResult) {
    if (route.path !== '/mindmap/edit' || currentMindmapId !== item.destinationMindmapId) {
      // The saved result is a different document from the task's source. Do not
      // attach aiJobId: restoring that source-bound job here would reject its scope.
      void router.push({ path: '/mindmap/edit', query: { id: String(item.destinationMindmapId) } })
    }
    return
  }
  if (item.standalone) {
    void router.push({ path: '/mindmap/ai-task', query: { aiJobId: item.jobId } })
    return
  }
  if (route.path === '/mindmap/edit' && currentMindmapId === item.sourceMindmapId) {
    window.dispatchEvent(new CustomEvent('mindmap-ai-open-task', {
      detail: { jobId: item.jobId },
    }))
    return
  }
  void router.push({
    path: '/mindmap/edit',
    query: {
      id: String(item.sourceMindmapId),
      aiJobId: item.jobId,
    },
  })
}

function stopForAuthExpiry() {
  clearTimeout(refreshTimer)
  refreshTimer = null
  requestController?.abort()
  requestController = null
  loading.value = false
}

watch(authExpired, expired => {
  if (!expired && componentAlive) {
    void refreshTasks()
    scheduleRefresh()
  }
})

onMounted(() => {
  void refreshTasks()
  scheduleRefresh()
  window.addEventListener('focus', onWindowFocus)
})

onBeforeUnmount(() => {
  componentAlive = false
  clearTimeout(refreshTimer)
  requestController?.abort()
  window.removeEventListener('focus', onWindowFocus)
})
</script>

<style lang="scss" scoped>
.mindmapAiTaskCenterTrigger {
  position: relative;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  min-width: 42px;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.mindmapAiTaskBadge {
  position: absolute;
  top: 7px;
  right: 3px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 10px;
  background: #f56c6c;
  color: #fff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
}

.mindmapAiTaskCenter {
  color: #303133;
}
.mindmapAiTaskRead { margin: 0 12px 8px; padding: 4px 8px; border: 0; background: transparent; color: var(--el-color-primary); font: inherit; cursor: pointer; }
.mindmapAiTaskRead:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }

.mindmapAiTaskCenterHeader {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
}

.mindmapAiTaskCenterHeader > div {
  display: grid;
  gap: 4px;
}

.mindmapAiTaskCenterHeader strong {
  font-size: 15px;
}

.mindmapAiTaskCenterHeader span,
.mindmapAiTaskCenterFooter,
.mindmapAiTaskCenterState span,
.mindmapAiTaskCopy small {
  color: #909399;
  font-size: 12px;
}

.mindmapAiTaskCenterRefresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  color: #606266;
  background: transparent;
  cursor: pointer;
}

.mindmapAiTaskCenterRefresh:hover {
  background: #f2f6fc;
  color: #409eff;
}

.mindmapAiTaskCenterState {
  display: grid;
  gap: 6px;
  padding: 28px 8px;
  text-align: center;
}

.mindmapAiTaskCenterState.is-error {
  color: #e6a23c;
  text-align: left;
}

.mindmapAiTaskCenterState button {
  justify-self: center;
  border: 0;
  background: transparent;
  color: #409eff;
  cursor: pointer;
}

.mindmapAiTaskList {
  display: grid;
  gap: 2px;
  max-height: 390px;
  margin: 8px -8px 0;
  padding: 0 4px;
  overflow: auto;
  list-style: none;
}

.mindmapAiTaskItemButton {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 10px;
  padding: 10px 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.mindmapAiTaskItemButton:hover:not(:disabled) {
  background: #f5f7fa;
}

.mindmapAiTaskItemButton:disabled {
  cursor: not-allowed;
  opacity: .68;
}

.mindmapAiTaskStatus {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border-radius: 50%;
  background: #f4f4f5;
}

.mindmapAiTaskStatus i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #909399;
}

.mindmapAiTaskStatus.is-active {
  background: #ecf5ff;
}

.mindmapAiTaskStatus.is-active i {
  background: #409eff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, .18);
}

.mindmapAiTaskStatus.is-attention {
  background: #fdf6ec;
}

.mindmapAiTaskStatus.is-attention i {
  background: #e6a23c;
}

.mindmapAiTaskCopy {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 3px;
}

.mindmapAiTaskCopy strong,
.mindmapAiTaskTitle,
.mindmapAiTaskCopy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mindmapAiTaskCopy strong {
  font-size: 13px;
}

.mindmapAiTaskTitle {
  color: #606266;
  font-size: 12px;
}

.mindmapAiTaskArrow {
  color: #c0c4cc;
}

.mindmapAiTaskCenterFooter {
  padding-top: 10px;
  border-top: 1px solid #ebeef5;
  line-height: 1.5;
}

.mindmapAiTaskPagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 0;
  font-size: 12px;
  color: #606266;

  button {
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    padding: 4px 6px;
    background: #fff;
    color: #409eff;
    cursor: pointer;

    &:disabled { color: #a8abb2; cursor: not-allowed; }
  }
}
</style>

<style>
.mindmapAiTaskCenterPopper { max-width: calc(100vw - 24px); }
</style>
