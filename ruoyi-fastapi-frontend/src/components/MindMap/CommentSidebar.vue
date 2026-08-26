<template>
  <Sidebar ref="sidebarRef" title="评论">
    <div class="comment-sidebar" :class="{ isDark }">
      <div class="comment-toolbar" aria-label="评论筛选与新建">
        <div class="scope-tabs" role="group" aria-label="评论范围">
          <button
            type="button"
            :class="{ active: scope === 'all' }"
            :aria-pressed="scope === 'all'"
            @click="setScope('all')"
          >
            全部
          </button>
          <button
            type="button"
            :class="{ active: scope === 'node' }"
            :aria-pressed="scope === 'node'"
            :disabled="!selectedNodeUid"
            @click="setScope('node')"
          >
            当前节点
          </button>
        </div>
        <el-select
          v-model="statusFilter"
          class="status-filter"
          size="small"
          aria-label="评论状态"
          @change="handleStatusFilterChange"
        >
          <el-option label="待处理" value="open" />
          <el-option label="已解决" value="resolved" />
          <el-option label="全部状态" value="all" />
        </el-select>
        <el-tooltip content="在当前节点新建评论" placement="bottom" :show-after="300">
          <button class="new-comment-button" type="button" aria-label="新建评论" @click="focusComposer">
            <el-icon><Plus /></el-icon>
          </button>
        </el-tooltip>
      </div>

      <section class="comment-composer" aria-label="新建节点评论">
        <button
          v-if="selectedNodeUid"
          type="button"
          class="composer-node"
          :title="selectedNodeText"
          @click="focusNode(selectedNodeUid)"
        >
          <el-icon><Location /></el-icon>
          <span>{{ selectedNodeText || '未命名节点' }}</span>
        </button>
        <div v-else class="composer-hint">
          <el-icon><ChatDotRound /></el-icon>
          <span>先在画布上选择一个节点，再发表评论</span>
        </div>
        <textarea
          v-if="selectedNodeUid && canComment === true"
          ref="newCommentInputRef"
          v-model="newComment"
          maxlength="2000"
          rows="3"
          :disabled="creating"
          placeholder="写下评论，和协作者一起讨论…"
          aria-label="评论内容"
          @keydown.meta.enter.prevent="submitNewComment"
          @keydown.ctrl.enter.prevent="submitNewComment"
        />
        <div v-else-if="selectedNodeUid && canComment === false" class="composer-readonly">
          当前文档暂不允许新增评论
        </div>
        <div v-else-if="selectedNodeUid" class="composer-readonly">
          正在确认评论权限…
        </div>
        <p v-if="newCommentError" class="mutation-error" role="alert">
          {{ newCommentError }}，草稿已保留
        </p>
        <div v-if="selectedNodeUid && canComment === true" class="composer-actions">
          <span>{{ newComment.length }}/2000 · {{ commandKey }} + Enter 发布</span>
          <button type="button" :disabled="creating || !newComment.trim()" @click="submitNewComment">
            <el-icon v-if="creating" class="is-loading"><Loading /></el-icon>
            <span>{{ creating ? '发布中' : (newCommentError ? '重试' : '发布') }}</span>
          </button>
        </div>
      </section>

      <div class="comment-list-heading">
        <strong>{{ listTitle }}</strong>
        <span>{{ total }} 条</span>
      </div>

      <div v-if="loading && threads.length === 0" class="comment-state" role="status">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在读取评论…</span>
      </div>
      <div v-else-if="loadError && threads.length === 0" class="comment-state is-error" role="alert">
        <span>{{ loadError }}</span>
        <button type="button" @click="loadThreads">重试</button>
      </div>
      <div v-else-if="threads.length === 0" class="comment-state is-empty">
        <el-icon><ChatDotRound /></el-icon>
        <strong>{{ statusFilter === 'resolved' ? '暂无已解决评论' : '暂无待处理评论' }}</strong>
        <span>{{ scope === 'node' ? '可以在当前节点发起第一条讨论' : '选择节点即可发起讨论' }}</span>
      </div>

      <div v-else class="comment-thread-list" :aria-busy="loading">
        <article
          v-for="thread in threads"
          :key="thread.id"
          class="comment-thread"
          :class="{ resolved: thread.status === 1, focused: focusedThreadId === thread.id }"
          :data-thread-id="thread.id"
          :aria-label="`定位到评论节点：${thread.nodeText || '原节点'}`"
          :title="`点击定位到：${thread.nodeText || '原节点'}`"
          tabindex="0"
          @click="onThreadCardClick(thread, $event)"
          @keydown.enter.self.prevent="focusThreadFromCard(thread)"
          @keydown.space.self.prevent="focusThreadFromCard(thread)"
        >
          <header class="thread-header">
            <el-avatar :size="28" :src="avatarUrl(thread.messages[0]?.avatar)">
              {{ authorInitial(thread.messages[0]?.authorName) }}
            </el-avatar>
            <div class="thread-author">
              <strong>{{ thread.messages[0]?.authorName || '未知用户' }}</strong>
              <span>{{ formatRelativeTime(thread.createdTime) }}</span>
            </div>
            <span v-if="thread.status === 1" class="resolved-label">已解决</span>
          </header>

          <div class="thread-messages">
            <div v-for="message in thread.messages" :key="message.id" class="thread-message">
              <div v-if="message.id !== thread.messages[0]?.id" class="reply-identity">
                <el-avatar :size="22" :src="avatarUrl(message.avatar)">
                  {{ authorInitial(message.authorName) }}
                </el-avatar>
                <strong>{{ message.authorName }}</strong>
                <span>{{ formatRelativeTime(message.createdTime) }}</span>
              </div>
              <p>{{ message.content }}</p>
              <button
                v-if="message.canDelete && canComment"
                class="delete-message"
                type="button"
                :disabled="deletingMessageIds.has(message.id)"
                :aria-label="deletingMessageIds.has(message.id) ? '正在删除评论' : '删除这条评论'"
                @click="confirmDelete(thread, message)"
              >
                <el-icon :class="{ 'is-loading': deletingMessageIds.has(message.id) }">
                  <Loading v-if="deletingMessageIds.has(message.id)" />
                  <Delete v-else />
                </el-icon>
              </button>
            </div>
          </div>

          <div v-if="replyingThreadId === thread.id" class="reply-composer">
            <textarea
              :ref="element => setReplyInputRef(thread.id, element)"
              v-model="replyDrafts[thread.id]"
              maxlength="2000"
              rows="2"
              :disabled="replyingThreadIds.has(thread.id)"
              placeholder="回复这条评论…"
              :aria-label="`回复 ${thread.messages[0]?.authorName || '评论'}`"
              @keydown.meta.enter.prevent="submitReply(thread)"
              @keydown.ctrl.enter.prevent="submitReply(thread)"
            />
            <p v-if="thread.status === 1" class="reply-hint">发送回复后，这条讨论会自动重新打开</p>
            <p v-if="replyErrors[thread.id]" class="mutation-error" role="alert">
              {{ replyErrors[thread.id] }}，回复草稿已保留
            </p>
            <div>
              <button
                type="button"
                class="text-action"
                :disabled="replyingThreadIds.has(thread.id)"
                @click="cancelReply(thread.id)"
              >
                取消
              </button>
              <button
                type="button"
                class="primary-action"
                :disabled="replyingThreadIds.has(thread.id) || !replyDrafts[thread.id]?.trim()"
                @click="submitReply(thread)"
              >
                {{ replyingThreadIds.has(thread.id) ? '发送中…' : (replyErrors[thread.id] ? '重试' : '回复') }}
              </button>
            </div>
          </div>

          <footer class="thread-actions">
            <button
              v-if="thread.canReply"
              type="button"
              :disabled="replyingThreadIds.has(thread.id)"
              @click="beginReply(thread.id)"
            >
              <el-icon><ChatDotRound /></el-icon>
              {{ thread.status === 1 ? '回复并重新打开' : '回复' }}
            </button>
            <button
              v-if="thread.canResolve"
              type="button"
              :disabled="statusUpdatingThreadIds.has(thread.id)"
              @click="toggleResolved(thread)"
            >
              <el-icon :class="{ 'is-loading': statusUpdatingThreadIds.has(thread.id) }">
                <Loading v-if="statusUpdatingThreadIds.has(thread.id)" />
                <component :is="thread.status === 1 ? RefreshLeft : CircleCheck" v-else />
              </el-icon>
              {{ statusUpdatingThreadIds.has(thread.id) ? '处理中…' : (thread.status === 1 ? '重新打开' : '解决') }}
            </button>
          </footer>
        </article>
      </div>

      <button v-if="threads.length < total" class="load-more" type="button" :disabled="loading" @click="loadMore">
        {{ loading ? '加载中…' : '加载更多' }}
      </button>
      <p class="sr-only" role="status" aria-live="polite">{{ announcement }}</p>
    </div>
  </Sidebar>
</template>

<script setup>
import {
  ChatDotRound,
  CircleCheck,
  Delete,
  Loading,
  Location,
  Plus,
  RefreshLeft,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { actions, store } from './useStore'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'
import {
  createMindmapComment,
  deleteMindmapComment,
  listMindmapComments,
  replyMindmapComment,
  updateMindmapCommentStatus,
} from '@/api/mindmap/comment'
import { createCommentMutationTracker } from '@/utils/mindmap-comment-mutation'
import { createLatestRequestTracker } from '@/utils/mindmap-async'

const props = defineProps({
  mindMap: { type: Object, default: null },
  mindmapId: { type: Number, required: true },
})

const sidebarRef = ref(null)
const newCommentInputRef = ref(null)
const { activeNodes, syncActiveNodes } = useMindMapActiveNodes({
  resolveMindMap: () => props.mindMap,
})
const lastSelectedNode = shallowRef(null)
const threads = ref([])
const total = ref(0)
const loading = ref(false)
const loadError = ref('')
const canComment = ref(null)
const newCommentDrafts = reactive({})
const newCommentErrors = reactive({})
const creatingNodeUids = reactive(new Set())
const scope = ref('all')
const statusFilter = ref('open')
const pageNum = ref(1)
const pageSize = 50
const focusedThreadId = ref(null)
const replyingThreadId = ref(null)
const replyDrafts = reactive({})
const replyErrors = reactive({})
const replyingThreadIds = reactive(new Set())
const statusUpdatingThreadIds = reactive(new Set())
const deletingMessageIds = reactive(new Set())
const announcement = ref('')
const replyInputRefs = new Map()
const requestTracker = createLatestRequestTracker()
const mutationTracker = createCommentMutationTracker()
const renderedCommentNodes = new Set()
let latestNodeCounts = {}
let pollTimer = null
let componentActive = true
let highlightedCommentNode = null

const isDark = computed(() => store.localConfig.isDark)
const selectedNode = computed(() => (
  (store.activeSidebar === 'comments' ? lastSelectedNode.value : null)
  || activeNodes.value[0]
))
const selectedNodeUid = computed(() => selectedNode.value?.uid || '')
const selectedNodeText = computed(() => getNodeLabel(selectedNode.value))
const creating = computed(() => creatingNodeUids.has(selectedNodeUid.value))
const newCommentError = computed({
  get: () => selectedNodeUid.value ? (newCommentErrors[selectedNodeUid.value] || '') : '',
  set: value => {
    if (!selectedNodeUid.value) return
    if (value) newCommentErrors[selectedNodeUid.value] = value
    else delete newCommentErrors[selectedNodeUid.value]
  },
})
const newComment = computed({
  get: () => selectedNodeUid.value ? (newCommentDrafts[selectedNodeUid.value] || '') : '',
  set: value => {
    if (!selectedNodeUid.value) return
    newCommentDrafts[selectedNodeUid.value] = value
    newCommentError.value = ''
  },
})
const listTitle = computed(() => {
  const statusName = statusFilter.value === 'resolved' ? '已解决' : (statusFilter.value === 'all' ? '全部' : '待处理')
  return scope.value === 'node' ? `当前节点 · ${statusName}` : `${statusName}评论`
})
const commandKey = /Mac|iPhone|iPad/i.test(navigator.platform) ? '⌘' : 'Ctrl'

function stripHtml(value) {
  if (!value) return ''
  const container = document.createElement('div')
  container.innerHTML = String(value)
  return (container.textContent || '').replace(/\s+/g, ' ').trim()
}

function getNodeLabel(node) {
  return stripHtml(node?.getData?.('text') || node?.getData?.('richText') || '').slice(0, 120)
}

function avatarUrl(value) {
  if (!value) return ''
  if (/^(https?:|data:|blob:)/i.test(value)) return value
  const base = import.meta.env.VITE_APP_BASE_API || ''
  return `${base.replace(/\/$/, '')}/${String(value).replace(/^\//, '')}`
}

function authorInitial(name) {
  return String(name || '?').trim().slice(0, 1).toUpperCase()
}

function formatRelativeTime(value) {
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return ''
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000))
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} 天前`
  const date = new Date(time)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function mergeThreads(currentRows, nextRows) {
  const merged = new Map(currentRows.map(thread => [thread.id, thread]))
  for (const thread of nextRows) merged.set(thread.id, thread)
  return [...merged.values()]
}

function mutationErrorMessage(error, fallback) {
  return error?.response?.data?.msg || error?.message || fallback
}

function announce(message) {
  announcement.value = ''
  nextTick(() => { announcement.value = message })
}

async function refreshAfterMutation(successMessage) {
  const refreshed = await loadThreads({ silent: true })
  if (!refreshed) ElMessage.warning(`${successMessage}，评论列表将在网络恢复后自动刷新`)
}

function setScope(value) {
  if (value === 'node' && !selectedNodeUid.value) return
  focusedThreadId.value = null
  scope.value = value
  void loadThreads()
}

function handleStatusFilterChange() {
  focusedThreadId.value = null
  void loadThreads()
}

async function loadThreads({ append = false, silent = false } = {}) {
  const requestId = requestTracker.begin()
  if (!append) pageNum.value = 1
  loading.value = true
  if (!silent) loadError.value = ''
  try {
    const response = await listMindmapComments(props.mindmapId, {
      status: statusFilter.value,
      nodeUid: scope.value === 'node' ? selectedNodeUid.value : undefined,
      pageNum: pageNum.value,
      pageSize,
    })
    if (!componentActive || !requestTracker.isCurrent(requestId)) return
    const payload = response.data || {}
    const nextRows = Array.isArray(payload.rows) ? payload.rows : []
    threads.value = append ? mergeThreads(threads.value, nextRows) : nextRows
    total.value = Number(payload.total) || 0
    canComment.value = payload.canComment === true
    applyNodeCounts(payload.summary?.nodeCounts || {})
    loadError.value = ''
    if (focusedThreadId.value) scrollFocusedThread()
    return true
  } catch (error) {
    if (!componentActive || !requestTracker.isCurrent(requestId)) return
    if (!silent) loadError.value = error?.message || '评论加载失败'
    return false
  } finally {
    if (componentActive && requestTracker.isCurrent(requestId)) loading.value = false
  }
}

function applyNodeCounts(nodeCounts) {
  latestNodeCounts = { ...(nodeCounts || {}) }
  for (const uid of renderedCommentNodes) {
    props.mindMap?.renderer?.findNodeByUid?.(uid)?.setCommentCount?.(0)
  }
  renderedCommentNodes.clear()
  for (const [uid, rawCount] of Object.entries(nodeCounts || {})) {
    const count = Math.max(0, Number(rawCount) || 0)
    if (!count) continue
    const node = props.mindMap?.renderer?.findNodeByUid?.(uid)
    node?.setCommentCount?.(count)
    renderedCommentNodes.add(uid)
  }
}

function renderKnownNodeCounts() {
  applyNodeCounts(latestNodeCounts)
}

async function loadMore() {
  if (loading.value || threads.value.length >= total.value) return false
  const previousPage = pageNum.value
  pageNum.value = previousPage + 1
  const loaded = await loadThreads({ append: true })
  if (!loaded && pageNum.value === previousPage + 1) pageNum.value = previousPage
  return loaded === true
}

function focusComposer() {
  syncActiveNodes()
  if (!selectedNodeUid.value) {
    ElMessage.info('请先选择需要评论的节点')
    return
  }
  nextTick(() => newCommentInputRef.value?.focus())
}

async function submitNewComment() {
  const content = newComment.value.trim()
  const nodeUid = selectedNodeUid.value
  if (!content || !nodeUid || creatingNodeUids.has(nodeUid) || canComment.value !== true) return
  const scopeKey = `thread:${props.mindmapId}:${nodeUid}`
  const signature = `${props.mindmapId}\u0000${nodeUid}\u0000${content}`
  const attempt = mutationTracker.begin(scopeKey, signature)
  creatingNodeUids.add(nodeUid)
  delete newCommentErrors[nodeUid]
  try {
    const response = await createMindmapComment({
      mindmapId: props.mindmapId,
      nodeUid,
      content,
    }, attempt.key)
    mutationTracker.succeed(scopeKey, attempt.key)
    delete newCommentDrafts[nodeUid]
    statusFilter.value = 'open'
    focusedThreadId.value = response.data?.threadId || null
    ElMessage.success('评论已发布')
    announce('评论已发布')
    await refreshAfterMutation('评论已发布')
  } catch (error) {
    newCommentErrors[nodeUid] = mutationErrorMessage(error, '评论发布失败')
    announce(`${newCommentErrors[nodeUid]}，草稿已保留`)
  } finally {
    creatingNodeUids.delete(nodeUid)
  }
}

function beginReply(threadId) {
  replyingThreadId.value = threadId
  delete replyErrors[threadId]
  nextTick(() => replyInputRefs.get(threadId)?.focus())
}

function cancelReply(threadId) {
  replyingThreadId.value = null
  replyDrafts[threadId] = ''
  delete replyErrors[threadId]
  mutationTracker.clear(`reply:${props.mindmapId}:${threadId}`)
}

function setReplyInputRef(threadId, element) {
  if (element) replyInputRefs.set(threadId, element)
  else replyInputRefs.delete(threadId)
}

async function submitReply(thread) {
  const content = replyDrafts[thread.id]?.trim()
  if (!content || replyingThreadIds.has(thread.id)) return
  const scopeKey = `reply:${props.mindmapId}:${thread.id}`
  const signature = `${thread.id}\u0000${content}`
  const attempt = mutationTracker.begin(scopeKey, signature)
  replyingThreadIds.add(thread.id)
  delete replyErrors[thread.id]
  try {
    await replyMindmapComment(thread.id, content, attempt.key)
    mutationTracker.succeed(scopeKey, attempt.key)
    replyingThreadId.value = null
    replyDrafts[thread.id] = ''
    statusFilter.value = 'open'
    focusedThreadId.value = thread.id
    ElMessage.success('回复已发布')
    announce(thread.status === 1 ? '回复已发布，讨论已重新打开' : '回复已发布')
    await refreshAfterMutation('回复已发布')
  } catch (error) {
    replyErrors[thread.id] = mutationErrorMessage(error, '回复发布失败')
    announce(`${replyErrors[thread.id]}，回复草稿已保留`)
  } finally {
    replyingThreadIds.delete(thread.id)
  }
}

async function toggleResolved(thread) {
  if (statusUpdatingThreadIds.has(thread.id)) return
  const resolved = thread.status !== 1
  statusUpdatingThreadIds.add(thread.id)
  try {
    await updateMindmapCommentStatus(thread.id, resolved)
    const successMessage = resolved ? '评论已解决' : '评论已重新打开'
    ElMessage.success(successMessage)
    announce(successMessage)
    await refreshAfterMutation(successMessage)
  } catch (error) {
    const message = mutationErrorMessage(error, resolved ? '解决评论失败' : '重新打开评论失败')
    ElMessage.error(message)
    announce(message)
  } finally {
    statusUpdatingThreadIds.delete(thread.id)
  }
}

async function confirmDelete(thread, message) {
  if (deletingMessageIds.has(message.id)) return
  const isThreadStarter = message.id === thread.messages[0]?.id
  try {
    await ElMessageBox.confirm(
      isThreadStarter
        ? '这是讨论的首条评论，删除后整条讨论及全部回复都会被删除，且无法恢复。'
        : '删除后无法恢复这条回复。',
      '删除评论',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }
  deletingMessageIds.add(message.id)
  try {
    const response = await deleteMindmapComment(message.id)
    const successMessage = response.data?.threadDeleted ? '整条讨论已删除' : '评论已删除'
    ElMessage.success(successMessage)
    announce(successMessage)
    await refreshAfterMutation(successMessage)
  } catch (error) {
    const messageText = mutationErrorMessage(error, '删除评论失败')
    ElMessage.error(messageText)
    announce(messageText)
  } finally {
    deletingMessageIds.delete(message.id)
  }
}

function focusNode(nodeUid) {
  const node = props.mindMap?.renderer?.findNodeByUid?.(nodeUid)
  if (!node) {
    ElMessage.warning('原节点已被删除，评论仍保留在讨论记录中')
    return false
  }
  props.mindMap?.execCommand?.('GO_TARGET_NODE', nodeUid)
  return setCommentTarget(node, { focus: true })
}

function clearCommentHighlight() {
  highlightedCommentNode?.group?.removeClass?.('smm-node-comment-target')
  highlightedCommentNode = null
}

function setCommentTarget(node, { focus = false } = {}) {
  if (!node?.uid) return false
  lastSelectedNode.value = node
  if (!focus) return true
  if (props.mindMap?.opt?.readonly) {
    if (highlightedCommentNode !== node) clearCommentHighlight()
    node.group?.addClass?.('smm-node-comment-target')
    highlightedCommentNode = node
  } else {
    node.active?.()
  }
  return true
}

const threadInteractiveSelector = [
  'button',
  'a',
  'input',
  'textarea',
  'select',
  '[contenteditable="true"]',
  '[role="button"]',
  '[role="link"]',
].join(',')

function focusThreadFromCard(thread) {
  if (!thread) return false
  focusedThreadId.value = thread.id
  return focusNode(thread.nodeUid)
}

function onThreadCardClick(thread, event) {
  const target = event?.target
  if (target instanceof Element && target.closest(threadInteractiveSelector)) return
  const selection = window.getSelection?.()
  if (selection && !selection.isCollapsed) return
  focusThreadFromCard(thread)
}

function scrollFocusedThread() {
  nextTick(() => {
    const container = sidebarRef.value?.getEl?.()
    const target = container?.querySelector?.(`[data-thread-id="${focusedThreadId.value}"]`)
    target?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  })
}

function onNodeCommentClick(node) {
  if (!setCommentTarget(node, { focus: true })) return
  scope.value = 'node'
  statusFilter.value = 'open'
  focusedThreadId.value = null
  actions.setActiveSidebar('comments')
  nextTick(() => {
    syncActiveNodes()
    void loadThreads()
  })
}

function onCanvasNodeClick(node) {
  setCommentTarget(node, {
    focus: store.activeSidebar === 'comments' && props.mindMap?.opt?.readonly === true,
  })
}

function onRemoteCommentChanged(data) {
  if (Number(data?.mindmapId) !== props.mindmapId) return
  void loadThreads({ silent: true })
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (store.activeSidebar === 'comments' && !document.hidden) {
      void loadThreads({ silent: true })
    }
  }, 15000)
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = null
}

watch(selectedNodeUid, () => {
  if (!selectedNodeUid.value && scope.value === 'node') {
    focusedThreadId.value = null
    scope.value = 'all'
  }
  if (store.activeSidebar === 'comments' && scope.value === 'node') {
    focusedThreadId.value = null
    void loadThreads()
  }
})

watch(activeNodes, nodes => {
  if (nodes[0]) lastSelectedNode.value = nodes[0]
}, { flush: 'sync' })

watch(() => store.activeSidebar, value => {
  if (value === 'comments') {
    syncActiveNodes()
    sidebarRef.value?.open()
    startPolling()
    void loadThreads()
  } else {
    focusedThreadId.value = null
    clearCommentHighlight()
    sidebarRef.value?.close()
    stopPolling()
  }
}, { immediate: true })

watch(() => props.mindMap, (mindMap, oldMindMap) => {
  oldMindMap?.off?.('node_click', onCanvasNodeClick)
  oldMindMap?.off?.('node_comment_click', onNodeCommentClick)
  oldMindMap?.off?.('node_tree_render_end', renderKnownNodeCounts)
  clearCommentHighlight()
  lastSelectedNode.value = null
  mindMap?.on?.('node_click', onCanvasNodeClick)
  mindMap?.on?.('node_comment_click', onNodeCommentClick)
  mindMap?.on?.('node_tree_render_end', renderKnownNodeCounts)
})

onMounted(() => {
  props.mindMap?.on?.('node_click', onCanvasNodeClick)
  props.mindMap?.on?.('node_comment_click', onNodeCommentClick)
  props.mindMap?.on?.('node_tree_render_end', renderKnownNodeCounts)
  bus.on('comment_changed', onRemoteCommentChanged)
  if (store.activeSidebar === 'comments') {
    sidebarRef.value?.open()
    startPolling()
  }
  void loadThreads({ silent: true })
})

onBeforeUnmount(() => {
  componentActive = false
  requestTracker.invalidate()
  stopPolling()
  clearCommentHighlight()
  props.mindMap?.off?.('node_click', onCanvasNodeClick)
  props.mindMap?.off?.('node_comment_click', onNodeCommentClick)
  props.mindMap?.off?.('node_tree_render_end', renderKnownNodeCounts)
  bus.off('comment_changed', onRemoteCommentChanged)
  for (const uid of renderedCommentNodes) {
    props.mindMap?.renderer?.findNodeByUid?.(uid)?.setCommentCount?.(0)
  }
  replyInputRefs.clear()
})
</script>

<style lang="less" scoped>
.comment-sidebar {
  min-height: 100%;
  padding-bottom: 18px;
  color: #1f2329;

  &.isDark {
    color: #e5e6eb;

    .comment-toolbar,
    .comment-composer,
    .comment-list-heading,
    .comment-thread,
    .thread-message + .thread-message {
      border-color: #3d4046;
    }

    .scope-tabs,
    .comment-composer textarea,
    .reply-composer textarea,
    .comment-thread {
      background: #25282d;
    }

    .scope-tabs button,
    .thread-author span,
    .reply-identity span,
    .reply-hint,
    .composer-actions > span,
    .comment-list-heading span,
    .comment-state,
    .composer-readonly {
      color: #9da3ad;
    }

    .scope-tabs button.active,
    .new-comment-button,
    .composer-actions button,
    .primary-action {
      color: #fff;
      background: #3370ff;
    }

    .thread-actions button,
    .composer-node {
      color: #8fb1ff;
    }
  }
}

.comment-toolbar {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 47px;
  padding: 7px 10px;
  border-bottom: 1px solid #eef0f3;
  background: inherit;
}

.scope-tabs {
  display: flex;
  padding: 2px;
  border-radius: 7px;
  background: #f2f3f5;

  button {
    height: 32px;
    padding: 0 10px;
    border: 0;
    border-radius: 5px;
    color: #646a73;
    background: transparent;
    font-size: 12px;
    cursor: pointer;

    &.active {
      color: #1f2329;
      background: #fff;
      box-shadow: 0 1px 2px rgba(31, 35, 41, 0.08);
      font-weight: 600;
    }

    &:disabled { cursor: not-allowed; opacity: 0.45; }
  }
}

.status-filter {
  flex: 1;
  min-width: 78px;
}

.new-comment-button {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 7px;
  color: #fff;
  background: #3370ff;
  cursor: pointer;
}

.comment-composer {
  margin: 10px;
  padding: 10px;
  border: 1px solid #e4e7eb;
  border-radius: 10px;
  background: #fff;
}

.composer-node {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  border: 0;
  color: #3370ff;
  background: transparent;
  font-size: 11px;
  cursor: pointer;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.composer-hint {
  min-height: 50px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #8f959e;
  font-size: 12px;

  .el-icon { font-size: 18px; }
}

.comment-composer textarea,
.reply-composer textarea {
  width: 100%;
  margin-top: 8px;
  padding: 8px 9px;
  border: 1px solid #dfe2e6;
  border-radius: 7px;
  outline: none;
  color: inherit;
  background: #fff;
  font: inherit;
  font-size: 12px;
  line-height: 1.55;
  resize: vertical;
  box-sizing: border-box;

  &:focus {
    border-color: #3370ff;
    box-shadow: 0 0 0 2px rgba(51, 112, 255, 0.12);
  }
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 7px;

  > span { color: #a2a7ae; font-size: 10px; }

  button {
    min-width: 54px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 0 11px;
    border: 0;
    border-radius: 6px;
    color: #fff;
    background: #3370ff;
    font-size: 12px;
    cursor: pointer;

    &:disabled { opacity: 0.45; cursor: not-allowed; }
  }
}

.composer-readonly {
  padding: 13px 0 3px;
  color: #8f959e;
  font-size: 11px;
}

.mutation-error {
  margin: 7px 0 0;
  color: #d14343;
  font-size: 11px;
  line-height: 1.5;
}

.comment-list-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 34px;
  padding: 0 12px;
  border-bottom: 1px solid #eef0f3;

  strong { font-size: 12px; }
  span { color: #8f959e; font-size: 10px; }
}

.comment-thread-list { padding: 0 10px; }

.comment-thread {
  position: relative;
  margin-top: 9px;
  padding: 11px;
  border: 1px solid #e4e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;

  &:hover {
    border-color: #b8c7e8;
  }

  &:focus-visible {
    outline: 2px solid #3370ff;
    outline-offset: 2px;
  }

  &.focused {
    border-color: #3370ff;
    box-shadow: 0 0 0 2px rgba(51, 112, 255, 0.1);
  }

  &.resolved { opacity: 0.82; }
}

.thread-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.thread-author {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;

  strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
  span { color: #8f959e; font-size: 10px; }
}

.resolved-label {
  margin-left: auto;
  padding: 2px 6px;
  border-radius: 4px;
  color: #16835d;
  background: #e9f8f1;
  font-size: 10px;
}

.thread-messages { margin-top: 8px; }

.thread-message {
  position: relative;
  padding: 1px 24px 1px 0;

  & + & {
    margin-top: 9px;
    padding-top: 9px;
    border-top: 1px solid #eef0f3;
  }

  p {
    margin: 0;
    color: inherit;
    font-size: 12px;
    line-height: 1.65;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
}

.reply-identity {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 5px;

  strong { font-size: 11px; }
  span { color: #8f959e; font-size: 10px; }
}

.delete-message {
  position: absolute;
  top: 0;
  right: -3px;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 5px;
  color: #a2a7ae;
  background: transparent;
  opacity: 0;
  cursor: pointer;
}

.thread-message:hover .delete-message,
.delete-message:focus-visible { opacity: 1; }

.thread-actions {
  display: flex;
  gap: 14px;
  margin-top: 9px;

  button {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    min-height: 32px;
    padding: 0 4px;
    border: 0;
    color: #646a73;
    background: transparent;
    font-size: 12px;
    cursor: pointer;

    &:hover { color: #3370ff; }
    &:disabled { cursor: wait; opacity: 0.6; }
  }
}

.reply-composer {
  margin-top: 8px;

  > div {
    display: flex;
    justify-content: flex-end;
    gap: 7px;
    margin-top: 6px;
  }
}

.reply-hint {
  margin: 5px 0 0;
  color: #8f959e;
  font-size: 11px;
}

.text-action,
.primary-action {
  min-width: 54px;
  height: 32px;
  padding: 0 10px;
  border: 0;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.text-action { color: #646a73; background: transparent; }
.primary-action { color: #fff; background: #3370ff; }

.comment-state {
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 20px;
  color: #8f959e;
  text-align: center;
  font-size: 11px;

  .el-icon { font-size: 24px; }
  strong { color: inherit; font-size: 12px; }

  button {
    border: 0;
    color: #3370ff;
    background: transparent;
    cursor: pointer;
  }

  &.is-error { color: #e45656; }
}

.load-more {
  width: calc(100% - 20px);
  height: 30px;
  margin: 10px;
  border: 1px solid #e4e7eb;
  border-radius: 7px;
  color: #646a73;
  background: transparent;
  font-size: 11px;
  cursor: pointer;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

textarea:disabled,
button:disabled {
  cursor: not-allowed;
}

button:focus-visible {
  outline: 2px solid #3370ff;
  outline-offset: 2px;
}
</style>
