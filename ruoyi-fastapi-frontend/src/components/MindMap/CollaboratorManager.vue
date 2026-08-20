<template>
  <Sidebar ref="sidebarRef" title="协作者管理" open-on-mount>
    <div class="collaboratorContainer">
      <!-- 添加协作者 -->
      <div class="addSection">
        <el-form :model="addForm" label-position="top" size="small" class="addForm" @submit.prevent="handleAdd">
          <el-form-item label="用户">
            <el-select
              v-model="addForm.userId"
              filterable
              remote
              reserve-keyword
              clearable
              :remote-method="handleSearchUsers"
              :loading="searchLoading"
              :disabled="isOperating"
              aria-label="搜索并选择协作者"
              placeholder="搜索用户名或昵称"
              class="collaboratorControl"
            >
              <el-option
                v-for="user in userOptions"
                :key="user.userId"
                :label="`${user.nickName || user.userName} (${user.userName})`"
                :value="user.userId"
              >
                <div class="userOption">
                  <el-avatar :size="24" :src="user.avatar || undefined">
                    {{ user.nickName?.charAt(0) || user.userName?.charAt(0) || '?' }}
                  </el-avatar>
                  <div class="userOptionInfo">
                    <span class="userOptionName">{{ user.nickName || user.userName }}</span>
                    <span class="userOptionId">{{ user.userName }}</span>
                  </div>
                </div>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="权限">
            <el-select v-model="addForm.permission" class="collaboratorControl" :disabled="isOperating" aria-label="新协作者权限">
              <el-option label="查看" :value="0" />
              <el-option label="编辑" :value="1" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button
              native-type="submit"
              type="primary"
              class="addButton"
              :loading="operationType === 'add'"
              :disabled="isOperating || !addForm.userId"
            >
              添加
            </el-button>
          </el-form-item>
        </el-form>
        <p v-if="searchError" class="searchError" role="alert">{{ searchError }}</p>
        <p class="permissionHint">编辑权限允许对方实时修改脑图；查看权限仅允许浏览。</p>
      </div>

      <!-- 协作者列表 -->
      <div class="collabList" v-loading="loading">
        <div v-if="collaborators.length === 0 && !loading" class="emptyTip">
          <template v-if="loadError">
            <p role="alert">{{ loadError }}</p>
            <el-button link type="primary" :disabled="isOperating" @click="loadCollaborators">重新加载</el-button>
          </template>
          <template v-else>暂无协作者</template>
        </div>
        <div v-for="item in collaborators" :key="item.id" class="collabItem">
          <div class="collabInfo">
            <el-avatar :size="32" :src="item.avatar || undefined">
              {{ item.nickName?.charAt(0) || item.userName?.charAt(0) || '?' }}
            </el-avatar>
            <div class="collabDetail">
              <div class="collabName">{{ item.nickName || item.userName }}</div>
              <div class="collabMeta">
                <el-select
                  :model-value="item.permission"
                  size="small"
                  style="width: 80px"
                  :aria-label="`修改${item.nickName || item.userName || '协作者'}的权限`"
                  :loading="operationType === `permission:${item.id}`"
                  :disabled="isOperating"
                  @change="(val) => handlePermissionChange(item, val)"
                >
                  <el-option label="查看" :value="0" />
                  <el-option label="编辑" :value="1" />
                </el-select>
              </div>
            </div>
          </div>
          <el-button
            link
            type="danger"
            size="small"
            :loading="operationType === `remove:${item.id}`"
            :disabled="isOperating"
            :aria-label="`移除协作者${item.nickName || item.userName || ''}`"
            @click="handleRemove(item)"
          >
            移除
          </el-button>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import Sidebar from './Sidebar.vue'
import { store } from './useStore'
import { addCollaborator, getCollaborators, updateCollaboratorPermission, removeCollaborator, searchUsers } from '@/api/mindmap/collaborator'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createLatestRequestTracker, createScopedAsyncSession, isElementDialogDismissal } from '@/utils/mindmap-async'
import {
  getCollaboratorErrorMessage,
  isCollaboratorPermissionDowngrade,
  normalizeCollaboratorSearchKeyword,
} from '@/utils/mindmap-collaborator'

const props = defineProps({
  mindmapId: { type: Number, default: null },
})

const sidebarRef = ref(null)
const loading = ref(false)
const loadError = ref('')
const collaborators = ref([])
const userOptions = ref([])
const searchLoading = ref(false)
const searchError = ref('')
const operationType = ref('')
const isOperating = computed(() => Boolean(operationType.value))
const listRequests = createLatestRequestTracker()
const searchRequests = createLatestRequestTracker()
const managerSession = createScopedAsyncSession()
let searchTimer = null
let componentMounted = true

const addForm = reactive({
  userId: null,
  permission: 0,
})

// 监听侧边栏开关
watch(
  [() => store.activeSidebar, () => props.mindmapId, () => store.canManageCollaborators],
  ([sidebar, mindmapId, canManage]) => {
    if (sidebar === 'collaboratorManager' && mindmapId && canManage) {
      managerSession.activate(mindmapId)
      void loadCollaborators()
      sidebarRef.value?.open()
    } else {
      invalidateManagerSession()
      sidebarRef.value?.close()
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  componentMounted = false
  invalidateManagerSession()
})

function invalidatePendingReads() {
  listRequests.invalidate()
  searchRequests.invalidate()
  clearTimeout(searchTimer)
  loading.value = false
  searchLoading.value = false
}

function invalidateManagerSession() {
  managerSession.invalidate()
  invalidatePendingReads()
  operationType.value = ''
  collaborators.value = []
  userOptions.value = []
  searchError.value = ''
}

function isManagerActive(session = managerSession.capture()) {
  return Boolean(
    componentMounted
    && store.activeSidebar === 'collaboratorManager'
    && store.canManageCollaborators
    && managerSession.isCurrent(session)
    && Number(props.mindmapId) === session.identity,
  )
}

async function loadCollaborators() {
  const session = managerSession.capture()
  if (!isManagerActive(session)) return
  const requestId = listRequests.begin()
  loading.value = true
  loadError.value = ''
  try {
    const res = await getCollaborators(session.identity)
    if (!listRequests.isCurrent(requestId) || !isManagerActive(session)) return
    collaborators.value = res.data || []
  } catch (e) {
    if (!listRequests.isCurrent(requestId) || !isManagerActive(session)) return
    console.error('加载协作者列表失败:', e)
    collaborators.value = []
    loadError.value = getCollaboratorErrorMessage(e, '协作者列表加载失败')
  } finally {
    if (listRequests.isCurrent(requestId) && isManagerActive(session)) loading.value = false
  }
}

function handleSearchUsers(keyword) {
  clearTimeout(searchTimer)
  const normalizedKeyword = normalizeCollaboratorSearchKeyword(keyword)
  const session = managerSession.capture()
  const requestId = searchRequests.begin()
  searchError.value = ''
  if (!normalizedKeyword || !isManagerActive(session)) {
    userOptions.value = []
    searchLoading.value = false
    return
  }
  searchTimer = setTimeout(async () => {
    if (!searchRequests.isCurrent(requestId) || !isManagerActive(session)) return
    searchLoading.value = true
    try {
      const res = await searchUsers(session.identity, normalizedKeyword)
      if (!searchRequests.isCurrent(requestId) || !isManagerActive(session)) return
      userOptions.value = res.data || []
    } catch (e) {
      if (!searchRequests.isCurrent(requestId) || !isManagerActive(session)) return
      console.error('搜索用户失败:', e)
      userOptions.value = []
      searchError.value = getCollaboratorErrorMessage(e, '用户搜索失败，请重试')
    } finally {
      if (searchRequests.isCurrent(requestId) && isManagerActive(session)) searchLoading.value = false
    }
  }, 300)
}

async function handleAdd() {
  const session = managerSession.capture()
  if (isOperating.value || !isManagerActive(session)) return
  const userId = addForm.userId
  const permission = Number(addForm.permission)
  if (!userId) {
    ElMessage.warning('请选择要添加的用户')
    return
  }
  if (![0, 1].includes(permission)) {
    ElMessage.warning('请选择有效的协作者权限')
    return
  }
  operationType.value = 'add'
  try {
    await addCollaborator({
      mindmapId: session.identity,
      userId,
      permission,
    })
    if (!isManagerActive(session)) return
    ElMessage.success('协作者添加成功')
    addForm.userId = null
    addForm.permission = 0
    userOptions.value = []
    searchRequests.invalidate()
    clearTimeout(searchTimer)
    searchLoading.value = false
    searchError.value = ''
    await loadCollaborators()
  } catch (e) {
    if (!isManagerActive(session)) return
    console.error('添加协作者失败:', e)
    ElMessage.error(getCollaboratorErrorMessage(e, '添加协作者失败'))
  } finally {
    if (isManagerActive(session)) operationType.value = ''
  }
}

async function handlePermissionChange(item, newPermission) {
  const session = managerSession.capture()
  const collaboratorId = Number(item?.id)
  const permission = Number(newPermission)
  if (isOperating.value || !isManagerActive(session)) return
  if (!Number.isSafeInteger(collaboratorId) || collaboratorId <= 0 || ![0, 1].includes(permission)) return
  if (!collaborators.value.some(collaborator => Number(collaborator.id) === collaboratorId)) return
  if (Number(item.permission) === permission) return
  const collaboratorName = item.nickName || item.userName || '该协作者'
  operationType.value = `confirm-permission:${collaboratorId}`
  try {
    if (isCollaboratorPermissionDowngrade(item.permission, permission)) {
      await ElMessageBox.confirm(
        `将「${collaboratorName}」调整为仅查看后，对方当前编辑会话会立即结束。确认继续吗？`,
        '调整协作者权限',
        {
          type: 'warning',
          confirmButtonText: '调整为仅查看',
          cancelButtonText: '取消',
          distinguishCancelAndClose: true,
        },
      )
    }
    if (!isManagerActive(session)) return
    operationType.value = `permission:${collaboratorId}`
    listRequests.invalidate()
    await updateCollaboratorPermission({
      id: collaboratorId,
      permission,
    })
    if (!isManagerActive(session)) return
    collaborators.value = collaborators.value.map(collaborator => (
      Number(collaborator.id) === collaboratorId
        ? { ...collaborator, permission }
        : collaborator
    ))
    ElMessage.success('权限修改成功')
  } catch (e) {
    if (isManagerActive(session) && !isElementDialogDismissal(e)) {
      console.error('修改权限失败:', e)
      ElMessage.error(getCollaboratorErrorMessage(e, '修改权限失败'))
    }
  } finally {
    if (isManagerActive(session)) operationType.value = ''
  }
}

async function handleRemove(item) {
  const session = managerSession.capture()
  const collaboratorId = Number(item?.id)
  if (isOperating.value || !isManagerActive(session)) return
  if (!Number.isSafeInteger(collaboratorId) || collaboratorId <= 0) return
  if (!collaborators.value.some(collaborator => Number(collaborator.id) === collaboratorId)) return
  operationType.value = `confirm-remove:${collaboratorId}`
  try {
    await ElMessageBox.confirm(
      `移除「${item.nickName || item.userName}」后，对方将立即失去访问权限，当前会话也会结束。确认继续吗？`,
      '确认移除',
      {
        type: 'warning',
        confirmButtonText: '确认移除',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
    if (!isManagerActive(session)) return
    operationType.value = `remove:${collaboratorId}`
    listRequests.invalidate()
    await removeCollaborator(collaboratorId)
    if (!isManagerActive(session)) return
    collaborators.value = collaborators.value.filter(collaborator => Number(collaborator.id) !== collaboratorId)
    ElMessage.success('协作者已移除')
  } catch (e) {
    if (isManagerActive(session) && !isElementDialogDismissal(e)) {
      console.error('移除协作者失败:', e)
      ElMessage.error(getCollaboratorErrorMessage(e, '移除协作者失败'))
    }
  } finally {
    if (isManagerActive(session)) operationType.value = ''
  }
}
</script>

<style lang="scss" scoped>
.collaboratorContainer {
  padding: 10px;

  .addSection {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #f0f0f0;
  }

  .addForm {
    :deep(.el-form-item) {
      margin-right: 0;
      margin-bottom: 12px;
    }

    :deep(.el-form-item__label) {
      margin-bottom: 4px;
      line-height: 1.4;
    }

    .collaboratorControl,
    .addButton {
      width: 100%;
    }
  }

  .permissionHint,
  .searchError {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
  }

  .permissionHint {
    color: #8a94a6;
  }

  .searchError {
    margin-bottom: 6px;
    color: var(--el-color-danger);
  }

  .collabList {
    max-height: calc(100vh - 300px);
    overflow-y: auto;
  }

  .emptyTip {
    text-align: center;
    color: #999;
    padding: 30px 0;
    font-size: 14px;

    p {
      margin: 0 0 6px;
    }
  }

  .collabItem {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 4px;
    border-bottom: 1px solid #f5f5f5;

    .collabInfo {
      display: flex;
      align-items: center;
      gap: 10px;
      flex: 1;
      min-width: 0;

      .collabDetail {
        flex: 1;
        min-width: 0;

        .collabName {
          font-size: 13px;
          font-weight: 500;
          color: #333;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .collabMeta {
          margin-top: 4px;
        }
      }
    }
  }
}
</style>

<!-- el-option 的 slot 内容会被 teleport 到 body，scoped 样式不生效，需要单独的 non-scoped 样式 -->
<style lang="scss">
.userOption {
  display: flex;
  align-items: center;
  gap: 8px;

  .userOptionInfo {
    display: flex;
    flex-direction: column;

    .userOptionName {
      font-size: 13px;
      font-weight: 500;
      color: #333;
    }

    .userOptionId {
      font-size: 11px;
      color: #999;
    }
  }
}
</style>
