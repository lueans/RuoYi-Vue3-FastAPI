<template>
  <el-dialog
    title="分享脑图"
    v-model="visible"
    width="520px"
    append-to-body
    @close="onClose"
  >
    <!-- 创建新链接 -->
    <div class="createSection">
      <el-form :model="createForm" :inline="true">
        <el-form-item label="权限">
          <el-select v-model="createForm.shareType" style="width: 120px">
            <el-option label="仅查看" :value="0" />
            <el-option label="可编辑" :value="1" />
          </el-select>
        </el-form-item>
        <el-form-item label="有效期">
          <el-select v-model="expireMode" style="width: 120px">
            <el-option label="永久" value="permanent" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="expireMode === 'custom'">
          <el-date-picker
            v-model="createForm.expireTime"
            type="datetime"
            placeholder="选择过期时间"
            :disabled-date="disablePastDate"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleCreate">创建链接</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 已有链接列表 -->
    <div class="linkList" v-loading="loading">
      <div v-if="shareLinks.length === 0 && !loading" class="emptyTip">
        暂无分享链接
      </div>
      <div v-for="link in shareLinks" :key="link.id" class="linkItem">
        <div class="linkInfo">
          <div class="linkUrl">
            <el-input :model-value="getShareUrl(link.shareToken)" readonly size="small">
              <template #append>
                <el-button @click="copyLink(link.shareToken)">复制</el-button>
              </template>
            </el-input>
          </div>
          <div class="linkMeta">
            <el-tag size="small" :type="link.shareType === 0 ? 'info' : 'success'">
              {{ link.shareType === 0 ? '仅查看' : '可编辑' }}
            </el-tag>
            <span class="expireInfo" v-if="link.expireTime">
              过期: {{ parseTime(link.expireTime) }}
            </span>
            <span class="expireInfo" v-else>永久有效</span>
            <el-tag size="small" :type="link.isActive ? 'success' : 'danger'">
              {{ link.isActive ? '有效' : '已禁用' }}
            </el-tag>
          </div>
        </div>
        <div class="linkActions">
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
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
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
    // 重置表单
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
    // Fallback
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
.createSection {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}

.linkList {
  max-height: 300px;
  overflow-y: auto;
}

.emptyTip {
  text-align: center;
  color: #999;
  padding: 20px 0;
}

.linkItem {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f5f5f5;

  .linkInfo {
    flex: 1;
    min-width: 0;
    margin-right: 12px;

    .linkUrl {
      margin-bottom: 6px;
    }

    .linkMeta {
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 12px;
      color: #999;
    }
  }

  .linkActions {
    flex-shrink: 0;
  }
}
</style>
