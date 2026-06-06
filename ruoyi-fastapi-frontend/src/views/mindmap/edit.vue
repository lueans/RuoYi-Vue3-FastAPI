<template>
  <div class="mindmap-edit-page">
    <div class="mindmap-edit-header">
      <el-page-header @back="goBack" :title="'返回列表'">
        <template #content>
          <span class="mindmap-title" @click="showRenameDialog">
            {{ mindmapName || '加载中...' }}
            <el-icon v-if="!isReadonly"><Edit /></el-icon>
          </span>
          <el-tag v-if="isReadonly" type="info" size="small" style="margin-left: 8px;">只读</el-tag>
          <Collaborators v-if="collaborators.length > 0" :collaborators="collaborators" style="margin-left: 12px;" />
          <el-button v-if="!isReadonly" type="primary" size="small" @click="openShareDialog" style="margin-left: 12px;">
            分享
          </el-button>
        </template>
      </el-page-header>
    </div>
    <div class="mindmap-edit-body">
      <Toolbar v-if="!isZenMode && !isReadonly" />
      <div class="mindmap-editor-container">
        <Edit ref="editRef" :mindmap-id="mindmapId" :readonly="isReadonly" @name-change="onNameChange" />
      </div>
      <NavigatorToolbar v-if="!isZenMode" :mindMap="mindMapInstance" />
    </div>

    <el-dialog title="重命名" v-model="renameOpen" width="400px">
      <el-form ref="renameRef" :model="renameForm" :rules="renameRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="renameForm.name" placeholder="请输入新名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" @click="submitRename">确定</el-button>
        <el-button @click="renameOpen = false">取消</el-button>
      </template>
    </el-dialog>

    <ShareDialog ref="shareDialogRef" :mindmap-id="mindmapId" />
  </div>
</template>

<script setup name="MindmapEditorPage">
import { Edit as EditIcon } from '@element-plus/icons-vue'
import Toolbar from '@/components/MindMap/Toolbar.vue'
import Edit from '@/components/MindMap/Edit.vue'
import NavigatorToolbar from '@/components/MindMap/NavigatorToolbar.vue'
import Collaborators from '@/components/MindMap/Collaborators.vue'
import ShareDialog from '@/components/MindMap/ShareDialog.vue'
import { store } from '@/components/MindMap/useStore'
import { renameMindmap } from '@/api/mindmap/mindmap'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const { proxy } = getCurrentInstance()

const editRef = ref(null)
const mindmapId = computed(() => Number(route.query.id))
const isReadonly = computed(() => route.query.readonly === '1')
const mindmapName = ref('')
const renameOpen = ref(false)
const isZenMode = computed(() => store.localConfig.isZenMode)
const mindMapInstance = computed(() => editRef.value?.mindMap || null)
const collaborators = computed(() => {
  const sync = editRef.value?.getYjsSync?.()
  return sync?.collaborators?.value || []
})

const shareDialogRef = ref(null)

function openShareDialog() {
  shareDialogRef.value?.open()
}

const renameForm = reactive({ id: undefined, name: '' })
const renameRules = {
  name: [{ required: true, message: '名称不能为空', trigger: 'blur' }]
}

function goBack() {
  router.push('/mindmap/index')
}

function onNameChange(name) {
  mindmapName.value = name
}

function showRenameDialog() {
  if (isReadonly.value) return
  renameForm.id = mindmapId.value
  renameForm.name = mindmapName.value
  renameOpen.value = true
}

function submitRename() {
  proxy.$refs['renameRef'].validate(valid => {
    if (valid) {
      renameMindmap(renameForm).then(response => {
        proxy.$modal.msgSuccess('重命名成功')
        mindmapName.value = renameForm.name
        renameOpen.value = false
      })
    }
  })
}
</script>

<style scoped lang="scss">
.mindmap-edit-page {
  height: calc(100vh - 84px);
  display: flex;
  flex-direction: column;
  background: #f5f5f5;
}
.mindmap-edit-header {
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  .mindmap-title {
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    &:hover { color: var(--el-color-primary); }
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
}
</style>
