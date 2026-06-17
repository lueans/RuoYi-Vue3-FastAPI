<template>
  <el-dialog
    title="分享脑图"
    v-model="visible"
    width="560px"
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
            <el-select v-model="createForm.shareType" class="form-select">
              <el-option label="仅查看" :value="0" />
              <el-option label="可编辑" :value="1" />
            </el-select>
          </div>
          <div class="form-item">
            <label class="form-label">有效期</label>
            <el-select v-model="expireMode" class="form-select">
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
              placeholder="选择过期时间"
              :disabled-date="disablePastDate"
              style="width: 100%"
            />
          </div>
        </div>
        <div class="form-row">
          <el-button type="primary" @click="handleCreate" class="create-btn">
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
        <div v-if="shareLinks.length === 0 && !loading" class="empty-tip">
          <el-empty description="暂无分享链接" :image-size="80" />
        </div>
        <div v-for="link in shareLinks" :key="link.id" class="link-item">
          <div class="link-content">
            <div class="link-url-row">
              <el-input :model-value="getShareUrl(link.shareToken)" readonly size="small" class="link-input">
                <template #append>
                  <el-button @click="copyLink(link.shareToken)" :icon="CopyDocument" />
                </template>
              </el-input>
            </div>
            <div class="link-meta">
              <el-tag size="small" :type="link.shareType === 0 ? 'info' : 'success'" effect="plain">
                {{ link.shareType === 0 ? '仅查看' : '可编辑' }}
              </el-tag>
              <span class="expire-info" v-if="link.expireTime">
                <el-icon :size="12"><Clock /></el-icon>
                {{ parseTime(link.expireTime) }}
              </span>
              <span class="expire-info" v-else>
                <el-icon :size="12"><Clock /></el-icon>
                永久有效
              </span>
              <el-tag size="small" :type="link.isActive ? 'success' : 'danger'" effect="plain">
                {{ link.isActive ? '有效' : '已禁用' }}
              </el-tag>
            </div>
          </div>
          <div class="link-actions">
            <el-button
              link type="danger" size="small"
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
import { ref, reactive } from 'vue'
import { Plus, Clock, CopyDocument } from '@element-plus/icons-vue'
import { createShareLink, getShareLinks, deleteShareLink } from '@/api/mindmap/share'
import { parseTime } from '@/utils/ruoyi'
import { ElMessage } from 'element-plus'

const props = defineProps({
  mindmapId: { type: Number, default: null },
})

const emit = defineEmits(['close'])

const visible = ref(false)
const loading = ref(false)
const shareLinks = ref([])
const expireMode = ref('permanent')

const createForm = reactive({
  shareType: 0,
  expireTime: null,
})

function open() {
  visible.value = true
  loadLinks()
}

function onClose() {
  visible.value = false
  emit('close')
}

async function loadLinks() {
  if (!props.mindmapId) return
  loading.value = true
  try {
    const res = await getShareLinks(props.mindmapId)
    shareLinks.value = res.data || []
  } catch (e) {
    console.error('加载分享链接失败:', e)
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!props.mindmapId) return
  try {
    const data = {
      mindmapId: props.mindmapId,
      shareType: createForm.shareType,
    }
    if (expireMode.value === 'custom' && createForm.expireTime) {
      data.expireTime = createForm.expireTime
    }
    await createShareLink(data)
    ElMessage.success('分享链接创建成功')
    loadLinks()
    createForm.shareType = 0
    createForm.expireTime = null
    expireMode.value = 'permanent'
  } catch (e) {
    console.error('创建分享链接失败:', e)
    ElMessage.error('创建分享链接失败')
  }
}

async function handleDisable(link) {
  try {
    await deleteShareLink(link.id)
    ElMessage.success('分享链接已禁用')
    loadLinks()
  } catch (e) {
    console.error('禁用分享链接失败:', e)
    ElMessage.error('操作失败')
  }
}

function getShareUrl(token) {
  const base = window.location.origin
  return `${base}/mindmap/view/${token}`
}

async function copyLink(token) {
  const url = getShareUrl(token)
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('链接已复制到剪贴板')
  } catch {
    const input = document.createElement('input')
    input.value = url
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    document.body.removeChild(input)
    ElMessage.success('链接已复制到剪贴板')
  }
}

function disablePastDate(date) {
  return date.getTime() < Date.now() - 86400000
}

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
</style>
