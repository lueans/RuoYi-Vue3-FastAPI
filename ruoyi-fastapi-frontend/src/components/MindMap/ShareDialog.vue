<template>
  <el-dialog
    title="分享脑图"
    v-model="visible"
    width="min(560px, calc(100vw - 32px))"
    append-to-body
    @close="onClose"
    class="share-dialog"
  >
    <!-- 创建新链接 -->
    <div class="create-section">
      <div class="section-title">创建分享链接</div>
      <div class="create-form">
        <div class="form-row">
          <div class="form-item">
            <label class="form-label">访问权限</label>
            <el-select
              v-model="createForm.shareType"
              class="form-select"
              aria-label="分享访问权限"
              :disabled="isOperating"
            >
              <el-option label="仅查看" :value="0" />
            </el-select>
            <div class="permission-tip">需要共同编辑时，请在编辑器中添加协作者</div>
          </div>
          <div class="form-item">
            <label class="form-label">有效期</label>
            <el-select
              v-model="expireMode"
              class="form-select"
              aria-label="分享链接有效期"
              :disabled="isOperating"
            >
              <el-option label="永久有效" value="permanent" />
              <el-option label="自定义" value="custom" />
            </el-select>
          </div>
        </div>
        <div v-if="expireMode === 'custom'" class="form-row">
          <div class="form-item full-width">
            <label class="form-label">过期时间</label>
            <el-date-picker
              v-model="createForm.expireTime"
              type="datetime"
              aria-label="分享链接过期时间"
              placeholder="选择过期时间"
              :disabled-date="disablePastDate"
              :disabled="isOperating"
              style="width: 100%"
            />
          </div>
        </div>
        <div class="form-row">
          <el-button type="primary" :loading="creating" :disabled="isOperating" @click="handleCreate" class="create-btn">
            <el-icon><Plus /></el-icon>
            创建链接
          </el-button>
        </div>
      </div>
    </div>

    <!-- 已有链接列表 -->
    <div class="links-section">
      <div class="section-title">已创建的链接</div>
      <div class="link-list" v-loading="loading">
        <div v-if="displayLinks.length === 0 && !loading" class="empty-tip">
          <div v-if="loadError" class="load-error" role="alert">
            <span>{{ loadError }}</span>
            <el-button link type="primary" @click="reloadLinks">重新加载</el-button>
          </div>
          <el-empty v-else description="暂无分享链接" :image-size="80" />
        </div>
        <div v-for="link in displayLinks" :key="link.id" class="link-item">
          <div class="link-content">
            <div class="link-url-row">
              <el-input :model-value="getShareUrl(link.shareToken)" aria-label="分享链接" readonly size="small" class="link-input">
                <template #append>
                  <el-button
                    @click="copyLink(link.shareToken, link.id)"
                    :icon="CopyDocument"
                    aria-label="复制分享链接"
                    :loading="operationType === `copy:${link.id}`"
                    :disabled="!link.status.usable || isOperating"
                  />
                </template>
              </el-input>
            </div>
            <div class="link-meta">
              <el-tag size="small" type="info" effect="plain">仅查看</el-tag>
              <span class="expire-info" v-if="link.expireTime">
                <el-icon :size="12"><Clock /></el-icon>
                {{ parseTime(link.expireTime) }}
              </span>
              <span class="expire-info" v-else>
                <el-icon :size="12"><Clock /></el-icon>
                永久有效
              </span>
              <el-tag size="small" :type="link.status.tagType" effect="plain">
                {{ link.status.label }}
              </el-tag>
            </div>
          </div>
          <div class="link-actions">
            <el-button
              link type="danger" size="small"
              :loading="operationType === `disable:${link.id}`"
              :disabled="isOperating"
              @click="handleDisable(link)"
              v-if="link.isActive"
            >
              禁用
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Plus, Clock, CopyDocument } from '@element-plus/icons-vue'
import { createShareLink, getShareLinks, deleteShareLink } from '@/api/mindmap/share'
import { parseTime } from '@/utils/ruoyi'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  copyMindmapShareText,
  isFutureMindmapShareExpiry,
  resolveMindmapShareStatus,
} from '@/utils/mindmap-share'
import { createLatestRequestTracker, createScopedAsyncSession, isElementDialogDismissal } from '@/utils/mindmap-async'

const props = defineProps({
  mindmapId: { type: Number, default: null },
})

const emit = defineEmits(['close'])

const visible = ref(false)
const loading = ref(false)
const loadError = ref('')
const creating = ref(false)
const shareLinks = ref([])
const expireMode = ref('permanent')
const operationType = ref('')
const isOperating = computed(() => creating.value || Boolean(operationType.value))
const displayLinks = computed(() => shareLinks.value.map(link => ({
  ...link,
  status: resolveMindmapShareStatus(link),
})))
const listRequests = createLatestRequestTracker()
const dialogSession = createScopedAsyncSession()

const createForm = reactive({
  shareType: 0,
  expireTime: null,
})

function getMindmapId() {
  const id = Number(props.mindmapId)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

function isShareSessionCurrent(session) {
  return Boolean(
    visible.value
    && dialogSession.isCurrent(session)
    && getMindmapId() === session.identity,
  )
}

function invalidateShareSession() {
  dialogSession.invalidate()
  listRequests.invalidate()
  loading.value = false
  creating.value = false
  operationType.value = ''
  shareLinks.value = []
}

function open() {
  const mindmapId = getMindmapId()
  if (!mindmapId) return
  const session = dialogSession.activate(mindmapId)
  visible.value = true
  loadError.value = ''
  shareLinks.value = []
  void loadLinks(session)
}

function onClose() {
  invalidateShareSession()
  visible.value = false
  emit('close')
}

async function loadLinks(session = dialogSession.capture()) {
  if (!isShareSessionCurrent(session)) return
  const requestId = listRequests.begin()
  loading.value = true
  loadError.value = ''
  try {
    const res = await getShareLinks(session.identity)
    if (!listRequests.isCurrent(requestId) || !isShareSessionCurrent(session)) return
    shareLinks.value = res.data || []
  } catch (e) {
    if (!listRequests.isCurrent(requestId) || !isShareSessionCurrent(session)) return
    console.error('加载分享链接失败:', e)
    shareLinks.value = []
    loadError.value = e?.message || '分享链接加载失败'
  } finally {
    if (listRequests.isCurrent(requestId) && isShareSessionCurrent(session)) {
      loading.value = false
    }
  }
}

function reloadLinks() {
  void loadLinks()
}

async function handleCreate() {
  const session = dialogSession.capture()
  if (!isShareSessionCurrent(session) || isOperating.value) return
  if (expireMode.value === 'custom' && !isFutureMindmapShareExpiry(createForm.expireTime)) {
    ElMessage.warning('请选择晚于当前时间的过期时间')
    return
  }
  creating.value = true
  try {
    const data = {
      mindmapId: session.identity,
      shareType: createForm.shareType,
    }
    if (expireMode.value === 'custom' && createForm.expireTime) {
      data.expireTime = createForm.expireTime
    }
    await createShareLink(data)
    if (!isShareSessionCurrent(session)) return
    ElMessage.success('分享链接创建成功')
    await loadLinks(session)
    if (!isShareSessionCurrent(session)) return
    createForm.shareType = 0
    createForm.expireTime = null
    expireMode.value = 'permanent'
  } catch (e) {
    if (!isShareSessionCurrent(session)) return
    console.error('创建分享链接失败:', e)
    ElMessage.error(e?.message || '创建分享链接失败')
  } finally {
    if (isShareSessionCurrent(session)) creating.value = false
  }
}

async function handleDisable(link) {
  const session = dialogSession.capture()
  const linkId = Number(link?.id)
  if (!isShareSessionCurrent(session) || isOperating.value || !Number.isSafeInteger(linkId) || linkId <= 0) return
  if (!shareLinks.value.some(item => Number(item.id) === linkId)) return
  operationType.value = `confirm-disable:${linkId}`
  try {
    await ElMessageBox.confirm(
      '禁用后该链接将立即无法访问，且不能重新启用。确认继续吗？',
      '禁用分享链接',
      { type: 'warning', confirmButtonText: '确认禁用', cancelButtonText: '取消' },
    )
    if (!isShareSessionCurrent(session)) return
    operationType.value = `disable:${linkId}`
    await deleteShareLink(linkId)
    if (!isShareSessionCurrent(session)) return
    ElMessage.success('分享链接已禁用')
    await loadLinks(session)
  } catch (e) {
    if (isShareSessionCurrent(session) && !isElementDialogDismissal(e)) {
      console.error('禁用分享链接失败:', e)
      ElMessage.error(e?.message || '操作失败')
    }
  } finally {
    if (isShareSessionCurrent(session)) operationType.value = ''
  }
}

function getShareUrl(token) {
  return new URL(`/mindmap/view/${encodeURIComponent(String(token || ''))}`, window.location.origin).href
}

async function copyLink(token, linkId) {
  const session = dialogSession.capture()
  if (!isShareSessionCurrent(session) || isOperating.value) return
  const url = getShareUrl(token)
  operationType.value = `copy:${linkId}`
  try {
    await copyMindmapShareText(url)
    if (!isShareSessionCurrent(session)) return
    ElMessage.success('链接已复制到剪贴板')
  } catch (error) {
    if (!isShareSessionCurrent(session)) return
    ElMessage.error(error?.message || '复制失败，请手动选择链接')
  } finally {
    if (isShareSessionCurrent(session)) operationType.value = ''
  }
}

function disablePastDate(date) {
  return date.getTime() < Date.now() - 86400000
}

watch(() => props.mindmapId, () => {
  invalidateShareSession()
  if (visible.value) visible.value = false
})

onBeforeUnmount(invalidateShareSession)

defineExpose({ open })
</script>

<style lang="scss" scoped>
.create-section {
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid #f0f1f3;
}

.section-title {
  font-size: 13px;
  font-weight: 500;
  color: #646a73;
  margin-bottom: 12px;
}

.create-form {
  .form-row {
    display: flex;
    gap: 12px;
    margin-bottom: 12px;
    &:last-child { margin-bottom: 0; }
  }

  .form-item {
    flex: 1;
    &.full-width { flex: 0 0 100%; }
  }

  .form-label {
    display: block;
    font-size: 12px;
    color: #8f959e;
    margin-bottom: 6px;
  }

  .form-select {
    width: 100%;
  }

  .permission-tip {
    margin-top: 6px;
    color: #8f959e;
    font-size: 11px;
    line-height: 1.5;
  }

  .create-btn {
    margin-top: 4px;
  }
}

.links-section {
  .link-list {
    max-height: 280px;
    overflow-y: auto;
    &::-webkit-scrollbar {
      width: 4px;
    }
    &::-webkit-scrollbar-thumb {
      background: #d4d6d9;
      border-radius: 4px;
    }
  }
}

.empty-tip {
  padding: 16px 0;
}

.load-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 12px;
  color: var(--el-color-danger);
  font-size: 13px;
}

.link-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 12px 0;
  border-bottom: 1px solid #f5f6f7;
  &:last-child { border-bottom: none; }

  .link-content {
    flex: 1;
    min-width: 0;
    margin-right: 12px;

    .link-url-row {
      margin-bottom: 8px;
      :deep(.el-input-group__append) {
        padding: 0;
        .el-button {
          margin: 0;
          padding: 8px 12px;
        }
      }
    }

    .link-meta {
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 12px;
      color: #8f959e;

      .expire-info {
        display: inline-flex;
        align-items: center;
        gap: 2px;
      }
    }
  }

  .link-actions {
    flex-shrink: 0;
    padding-top: 4px;
  }
}

@media (max-width: 600px) {
  .create-form .form-row {
    flex-direction: column;
    gap: 10px;
  }

  .link-item {
    flex-direction: column;
    gap: 8px;

    .link-content {
      width: 100%;
      margin-right: 0;

      .link-meta {
        flex-wrap: wrap;
      }
    }

    .link-actions {
      align-self: flex-end;
      padding-top: 0;
    }
  }
}
</style>
