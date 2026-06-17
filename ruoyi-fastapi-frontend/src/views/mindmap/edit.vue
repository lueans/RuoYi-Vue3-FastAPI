<template>
  <div class="mindmap-edit-page">
    <div class="mindmap-edit-header">
      <div class="header-left">
        <button class="back-btn" @click="goBack" title="返回列表" type="button">
          <el-icon :size="18"><ArrowLeft /></el-icon>
        </button>
        <div class="header-divider" />
        <div class="title-area">
          <span class="mindmap-title" @click="showRenameDialog">
            {{ mindmapName || '加载中...' }}
            <el-icon v-if="!isReadonly" class="edit-icon"><Edit /></el-icon>
          </span>
          <el-tag v-if="isReadonly" type="info" size="small" effect="plain" class="readonly-tag">只读</el-tag>
          <Collaborators v-if="collaborators.length > 0" :collaborators="collaborators" class="collaborators" />
        </div>
      </div>
      <div class="header-right">
        <Toolbar v-if="!isZenMode && !isReadonly" class="header-toolbar" />
        <div class="header-divider" />
        <div class="header-actions">
          <span v-if="!isReadonly" class="save-status" :class="saveStatus">
            <el-icon v-if="saveStatus === 'saving'" class="is-loading" :size="14"><Loading /></el-icon>
            <el-icon v-else-if="saveStatus === 'saved'" :size="14"><Check /></el-icon>
            <el-icon v-else-if="saveStatus === 'error'" :size="14"><WarningFilled /></el-icon>
            <span class="save-text">
              {{ saveStatus === 'saving' ? '保存中' : saveStatus === 'saved' ? '已保存' : saveStatus === 'error' ? '保存失败' : '' }}
            </span>
          </span>
          <template v-if="!isReadonly">
            <el-tooltip content="分享" placement="bottom" :show-after="300">
              <button class="share-btn" @click="openShareDialog" type="button">
                <svg-icon icon-class="share" />
              </button>
            </el-tooltip>
          </template>
        </div>
      </div>
    </div>
    <div class="mindmap-edit-body">
      <div class="mindmap-editor-container">
        <Edit ref="editRef" :mindmap-id="mindmapId" :readonly="isReadonly" @name-change="onNameChange" />
      </div>
      <NavigatorToolbar v-if="!isZenMode" :mindMap="mindMapInstance" />
    </div>

    <el-dialog title="重命名" v-model="renameOpen" width="420px" append-to-body>
      <el-form ref="renameRef" :model="renameForm" :rules="renameRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="renameForm.name" placeholder="请输入新名称" maxlength="100" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameOpen = false">取消</el-button>
        <el-button type="primary" @click="submitRename">确定</el-button>
      </template>
    </el-dialog>

    <ShareDialog ref="shareDialogRef" :mindmap-id="mindmapId" />
  </div>
</template>

<script setup name="MindmapEditorPage">
import { ArrowLeft, Edit as EditIcon, Loading, Check, WarningFilled } from '@element-plus/icons-vue'
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
const saveStatus = computed(() => editRef.value?.saveStatus?.value || 'idle')

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
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #fff;
  overflow: hidden;
}

.mindmap-edit-header {
  height: 52px;
  padding: 0 12px;
  background: #fff;
  border-bottom: 1px solid #dee0e3;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  user-select: none;

  .header-left {
    display: flex;
    align-items: center;
    min-width: 0;
    flex: 1;
    gap: 0;
  }

  .header-right {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    gap: 0;
  }

  .back-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    cursor: pointer;
    color: #646a73;
    transition: all 0.2s;
    flex-shrink: 0;
    border: none;
    background: transparent;
    padding: 0;
    outline: none;
    &:hover {
      background: #f5f6f7;
      color: #1f2329;
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px #3370ff40;
    }
  }

  .header-divider {
    width: 1px;
    height: 16px;
    background: #dee0e3;
    margin: 0 8px;
    flex-shrink: 0;
  }

  .title-area {
    display: flex;
    align-items: center;
    min-width: 0;
    gap: 8px;
  }

  .mindmap-title {
    font-size: 15px;
    font-weight: 500;
    color: #1f2329;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background 0.15s;
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    &:hover {
      background: #f5f6f7;
      .edit-icon { opacity: 1; }
    }
    .edit-icon {
      font-size: 14px;
      color: #8f959e;
      opacity: 0;
      transition: opacity 0.15s;
    }
  }

  .readonly-tag {
    flex-shrink: 0;
  }

  .collaborators {
    flex-shrink: 0;
    margin-left: 4px;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-left: 4px;
  }

  .save-status {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: #8f959e;
    transition: color 0.2s;
    padding: 4px 8px;
    border-radius: 4px;
    &.saving {
      color: #ff7d00;
    }
    &.saved {
      color: #34c759;
    }
    &.error {
      color: #f54a45;
    }
    .save-text {
      white-space: nowrap;
    }
  }

  .share-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    cursor: pointer;
    color: #646a73;
    transition: all 0.2s;
    font-size: 18px;
    border: none;
    background: transparent;
    padding: 0;
    outline: none;
    &:hover {
      background: #f5f6f7;
      color: #3370ff;
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px #3370ff40;
    }
    .svg-icon {
      width: 18px;
      height: 18px;
    }
  }

  /* ── Toolbar in header ── */
  .header-toolbar {
    position: static;
    pointer-events: auto;

    :deep(.toolbar) {
      padding: 0;
      justify-content: flex-start;
    }

    :deep(.toolbarBlock) {
      background: transparent;
      box-shadow: none;
      border: none;
      padding: 0 4px;
      border-radius: 0;
      margin-right: 0;
      flex-shrink: 0;
      position: relative;
      &::after {
        content: '';
        display: block;
        width: 1px;
        height: 16px;
        background: #dee0e3;
        position: absolute;
        right: 0;
        top: 50%;
        transform: translateY(-50%);
      }
      &:last-of-type::after {
        display: none;
      }
    }

    :deep(.toolbarBtn) {
      flex-direction: row;
      align-items: center;
      margin-right: 2px;
      padding: 5px 6px;
      border-radius: 6px;
      transition: background 0.15s, color 0.15s;
      color: #646a73;
      &:last-of-type {
        margin-right: 0;
      }
      &:hover:not(.disabled) {
        background: #f5f6f7;
        color: #1f2329;
        .icon {
          background: transparent;
          color: #1f2329;
        }
      }
      &.active {
        background: #edf4ff;
        color: #3370ff;
        .icon {
          background: transparent;
          color: #3370ff;
        }
      }
      &.disabled {
        color: #bbbfc4;
        cursor: not-allowed;
        .icon {
          color: #bbbfc4;
        }
      }
      .icon {
        height: auto;
        background: transparent;
        border: none;
        padding: 0;
        font-size: 18px;
        line-height: 1;
        color: inherit;
        transition: color 0.15s;
      }
      .text {
        display: none;
      }
    }

    :deep(.toolbarNodeBtnList.v) {
      .toolbarBtn {
        flex-direction: row;
        .text {
          display: inline;
        }
      }
    }

    /* 更多按钮样式 */
    :deep(.el-popover) {
      .toolbarBtn {
        .text {
          display: inline;
        }
      }
    }
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
