<template>
  <Sidebar ref="sidebarRef" title="协作者管理">
    <div class="collaboratorContainer">
      <!-- 添加协作者 -->
      <div class="addSection">
        <el-form :model="addForm" :inline="true" size="small">
          <el-form-item label="用户ID">
            <el-input-number v-model="addForm.userId" :min="1" :controls="false" placeholder="用户ID" style="width: 100px" />
          </el-form-item>
          <el-form-item label="权限">
            <el-select v-model="addForm.permission" style="width: 90px">
              <el-option label="查看" :value="0" />
              <el-option label="编辑" :value="1" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="handleAdd">添加</el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- 协作者列表 -->
      <div class="collabList" v-loading="loading">
        <div v-if="collaborators.length === 0 && !loading" class="emptyTip">
          暂无协作者
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
                  @change="(val) => handlePermissionChange(item, val)"
                >
                  <el-option label="查看" :value="0" />
                  <el-option label="编辑" :value="1" />
                </el-select>
              </div>
            </div>
          </div>
          <el-button link type="danger" size="small" @click="handleRemove(item)">
            移除
          </el-button>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import Sidebar from './Sidebar.vue'
import { store, actions } from './useStore'
import { addCollaborator, getCollaborators, updateCollaboratorPermission, removeCollaborator } from '@/api/mindmap/collaborator'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({
  mindmapId: { type: Number, default: null },
})

const sidebarRef = ref(null)
const loading = ref(false)
const collaborators = ref([])

const addForm = reactive({
  userId: null,
  permission: 0,
})

// 监听侧边栏开关
watch(() => store.activeSidebar, (val) => {
  if (val === 'collaboratorManager') {
    loadCollaborators()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
})

async function loadCollaborators() {
  if (!props.mindmapId) return
  loading.value = true
  try {
    const res = await getCollaborators(props.mindmapId)
    collaborators.value = res.data || []
  } catch (e) {
    console.error('加载协作者列表失败:', e)
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  if (!props.mindmapId || !addForm.userId) {
    ElMessage.warning('请输入用户ID')
    return
  }
  try {
    await addCollaborator({
      mindmapId: props.mindmapId,
      userId: addForm.userId,
      permission: addForm.permission,
    })
    ElMessage.success('协作者添加成功')
    addForm.userId = null
    addForm.permission = 0
    loadCollaborators()
  } catch (e) {
    console.error('添加协作者失败:', e)
  }
}

async function handlePermissionChange(item, newPermission) {
  try {
    await updateCollaboratorPermission({
      id: item.id,
      permission: newPermission,
    })
    ElMessage.success('权限修改成功')
    loadCollaborators()
  } catch (e) {
    console.error('修改权限失败:', e)
  }
}

async function handleRemove(item) {
  try {
    await ElMessageBox.confirm(
      `确认移除协作者「${item.nickName || item.userName}」？`,
      '确认移除',
      { type: 'warning' }
    )
    await removeCollaborator(item.id)
    ElMessage.success('协作者已移除')
    loadCollaborators()
  } catch (e) {
    if (e !== 'cancel') {
      console.error('移除协作者失败:', e)
    }
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

  .collabList {
    max-height: calc(100vh - 300px);
    overflow-y: auto;
  }

  .emptyTip {
    text-align: center;
    color: #999;
    padding: 30px 0;
    font-size: 14px;
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
