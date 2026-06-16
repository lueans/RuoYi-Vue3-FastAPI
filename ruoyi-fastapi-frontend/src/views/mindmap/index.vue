<template>
  <div class="app-container mindmap-index">
    <splitpanes class="default-theme" style="height: calc(100vh - 84px);">
      <!-- 左侧：文件夹目录树 -->
      <pane size="20" min-size="15" max-size="40">
        <div class="dir-tree-container">
          <div class="dir-tree-header">
            <span class="dir-tree-title">脑图目录</span>
            <el-tooltip content="新建文件夹" placement="top">
              <el-button
                type="primary"
                icon="Plus"
                size="small"
                plain
                @click="handleAddFolder(0)"
                v-hasPermi="['mindmap:folder:add']"
              />
            </el-tooltip>
          </div>
          <div class="dir-tree-search">
            <el-input
              v-model="folderFilter"
              placeholder="搜索文件夹..."
              clearable
              prefix-icon="Search"
              size="default"
            />
          </div>
          <div class="dir-tree-body">
            <!-- 全部脑图 -->
            <div
              class="fixed-tree-node"
              :class="{ active: selectedFolderKey === 'all' }"
              @click="selectFolder('all')"
            >
              <el-icon class="folder-icon"><Files /></el-icon>
              <span class="node-text">全部脑图</span>
            </div>
            <!-- 文件夹树 -->
            <el-tree
              ref="folderTreeRef"
              :data="folderTree"
              :props="{ label: 'name', children: 'children' }"
              :expand-on-click-node="false"
              :filter-node-method="filterFolderNode"
              node-key="id"
              highlight-current
              draggable
              :allow-drag="allowFolderDrag"
              @node-drop="handleFolderDrop"
              @node-click="handleFolderClick"
            >
              <template #default="{ node, data }">
                <span class="custom-tree-node">
                  <span class="node-label">
                    <el-icon class="folder-icon">
                      <FolderOpened v-if="node.expanded && data.children && data.children.length" />
                      <Folder v-else />
                    </el-icon>
                    <span class="node-text">{{ data.name }}</span>
                  </span>
                  <el-dropdown
                    class="node-more"
                    trigger="hover"
                    placement="bottom-end"
                    @command="(cmd) => handleFolderCommand(cmd, data)"
                    @click.stop
                  >
                    <el-icon class="more-btn" @click.stop><MoreFilled /></el-icon>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="add" v-hasPermi="['mindmap:folder:add']">
                          <el-icon><Plus /></el-icon>新建子文件夹
                        </el-dropdown-item>
                        <el-dropdown-item command="edit" v-hasPermi="['mindmap:folder:edit']">
                          <el-icon><Edit /></el-icon>重命名
                        </el-dropdown-item>
                        <el-dropdown-item command="delete" divided v-hasPermi="['mindmap:folder:remove']">
                          <el-icon class="delete-icon"><Delete /></el-icon>
                          <span class="delete-text">删除</span>
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </span>
              </template>
            </el-tree>
          </div>
        </div>
      </pane>

      <!-- 右侧：脑图列表 -->
      <pane>
        <div class="main-content">
          <el-form :model="queryParams" ref="queryRef" :inline="true" class="content-toolbar" v-show="showSearch">
            <el-form-item label="名称" prop="name">
              <el-input
                v-model="queryParams.name"
                placeholder="请输入脑图名称"
                clearable
                style="width: 200px"
                @keyup.enter="handleQuery"
              />
            </el-form-item>
            <el-form-item label="状态" prop="status">
              <el-select v-model="queryParams.status" placeholder="脑图状态" clearable style="width: 140px">
                <el-option label="正常" :value="0" />
                <el-option label="归档" :value="1" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
              <el-button icon="Refresh" @click="resetQuery">重置</el-button>
            </el-form-item>
          </el-form>

          <div class="content-actions">
            <el-button type="primary" plain icon="Plus" @click="handleAdd" v-hasPermi="['mindmap:mindmap:add']">新建脑图</el-button>
            <el-button type="danger" plain icon="Delete" :disabled="multiple" @click="handleDelete" v-hasPermi="['mindmap:mindmap:remove']">删除</el-button>
            <el-button v-if="selectedFolderKey !== 'all'" plain icon="Rank" :disabled="multiple" @click="handleMoveSelected" v-hasPermi="['mindmap:mindmap:edit']">移动到</el-button>
            <right-toolbar v-model:showSearch="showSearch" @queryTable="getList" />
          </div>

          <div class="content-body">
            <el-table
              v-loading="loading"
              :data="mindmapList"
              @selection-change="handleSelectionChange"
              style="width: 100%"
            >
              <el-table-column type="selection" width="55" align="center" />
              <el-table-column label="名称" align="center" prop="name" :show-overflow-tooltip="true">
                <template #default="scope">
                  <el-link type="primary" @click="handleEdit(scope.row)">{{ scope.row.name }}</el-link>
                </template>
              </el-table-column>
              <el-table-column label="版本数" align="center" prop="versionCount" width="80" />
              <el-table-column label="状态" align="center" prop="status" width="80">
                <template #default="scope">
                  <el-tag :type="scope.row.status === 0 ? 'success' : 'info'">
                    {{ scope.row.status === 0 ? '正常' : '归档' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="更新时间" align="center" prop="updateTime" width="180">
                <template #default="scope">
                  <span>{{ parseTime(scope.row.updateTime) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="300" align="center" class-name="small-padding fixed-width">
                <template #default="scope">
                  <el-button link type="primary" icon="View" @click="handleView(scope.row)">查看</el-button>
                  <el-button link type="primary" icon="Edit" @click="handleEdit(scope.row)">编辑</el-button>
                  <el-button link type="primary" icon="CopyDocument" @click="handleCopy(scope.row)">复制</el-button>
                  <el-button link type="primary" icon="Rank" @click="handleMoveOne(scope.row)">移动</el-button>
                  <el-button link type="primary" icon="Delete" @click="handleDelete(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <pagination
              v-show="total > 0"
              :total="total"
              v-model:page="queryParams.pageNum"
              v-model:limit="queryParams.pageSize"
              @pagination="getList"
            />
          </div>
        </div>
      </pane>
    </splitpanes>

    <!-- 新建/重命名文件夹对话框 -->
    <el-dialog :title="folderDialogTitle" v-model="folderDialogOpen" width="500px" append-to-body destroy-on-close>
      <el-form ref="folderFormRef" :model="folderForm" :rules="folderRules" label-width="80px">
        <el-form-item label="上级目录" prop="parentId">
          <el-tree-select
            v-model="folderForm.parentId"
            :data="folderSelectTree"
            :props="{ label: 'name', value: 'id', children: 'children' }"
            value-key="id"
            placeholder="请选择上级目录"
            check-strictly
            clearable
            style="width: 100%;"
          />
        </el-form-item>
        <el-form-item label="文件夹名" prop="name">
          <el-input v-model="folderForm.name" placeholder="请输入文件夹名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="显示排序" prop="sortOrder">
          <el-input-number v-model="folderForm.sortOrder" controls-position="right" :min="0" style="width: 100%;" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="folderDialogOpen = false">取 消</el-button>
          <el-button type="primary" @click="submitFolder">确 定</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 移动脑图对话框 -->
    <el-dialog title="移动脑图到文件夹" v-model="moveDialogOpen" width="420px" append-to-body destroy-on-close>
      <el-tree-select
        v-model="moveFolderId"
        :data="moveSelectTree"
        :props="{ label: 'name', value: 'id', children: 'children' }"
        check-strictly
        clearable
        placeholder="根目录"
        style="width: 100%"
      />
      <template #footer>
        <el-button type="primary" @click="submitMove">确 定</el-button>
        <el-button @click="moveDialogOpen = false">取 消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="MindmapManagement">
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import { listMindmap, delMindmap, copyMindmap, addMindmap } from '@/api/mindmap/mindmap'
import { getFolderTree, addFolder, updateFolder, deleteFolder, moveMindmaps, sortFolders } from '@/api/mindmap/folder'
import { FolderOpened, Folder, Files, Plus, Edit, Delete, Rank, MoreFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

const { proxy } = getCurrentInstance()
const router = useRouter()

// ─── 文件夹树 ───
const folderTree = ref([])
const folderFilter = ref('')
const folderTreeRef = ref(null)
const selectedFolderKey = ref('all') // 'all' | number(folderId)

// ─── 脑图列表 ───
const mindmapList = ref([])
const loading = ref(true)
const showSearch = ref(true)
const ids = ref([])
const multiple = ref(true)
const total = ref(0)

// ─── 文件夹对话框 ───
const folderDialogOpen = ref(false)
const folderDialogTitle = ref('新建文件夹')
const folderForm = reactive({ id: null, name: '', parentId: 0, sortOrder: 0 })
const folderRules = {
  name: [{ required: true, message: '文件夹名称不能为空', trigger: 'blur' }]
}

// ─── 移动对话框 ───
const moveDialogOpen = ref(false)
const moveFolderId = ref(null)
const moveMindmapIds = ref([])

const data = reactive({
  queryParams: {
    pageNum: 1,
    pageSize: 10,
    name: undefined,
    status: undefined,
    folderId: undefined
  }
})
const { queryParams } = toRefs(data)

// ─── 计算属性 ───
const folderSelectTree = computed(() => [{ id: 0, name: '根目录', children: folderTree.value }])
const moveSelectTree = computed(() => folderTree.value)

// ─── 文件夹搜索过滤 ───
watch(folderFilter, (val) => {
  folderTreeRef.value?.filter(val)
})

function filterFolderNode(value, data) {
  if (!value) return true
  return data.name.indexOf(value) !== -1
}

// ─── 初始化 ───
loadFolderTree()
getList()

// ==============================
// 文件夹相关
// ==============================

function loadFolderTree() {
  getFolderTree().then(res => {
    folderTree.value = res.data || []
  })
}

function selectFolder(key) {
  selectedFolderKey.value = key
  if (folderTreeRef.value) folderTreeRef.value.setCurrentKey(null)
  if (key === 'all') {
    queryParams.value.folderId = undefined
  }
  queryParams.value.pageNum = 1
  getList()
}

function handleFolderClick(data) {
  selectedFolderKey.value = data.id
  queryParams.value.folderId = data.id
  queryParams.value.pageNum = 1
  getList()
}

function handleFolderCommand(command, data) {
  switch (command) {
    case 'add':
      handleAddFolder(data.id)
      break
    case 'edit':
      handleRenameFolder(data)
      break
    case 'delete':
      handleDeleteFolder(data)
      break
  }
}

function handleAddFolder(parentId) {
  folderDialogTitle.value = '新建文件夹'
  folderForm.id = null
  folderForm.name = ''
  folderForm.parentId = parentId || 0
  folderForm.sortOrder = 0
  folderDialogOpen.value = true
}

function handleRenameFolder(data) {
  folderDialogTitle.value = '重命名文件夹'
  folderForm.id = data.id
  folderForm.name = data.name
  folderForm.parentId = data.parentId
  folderForm.sortOrder = data.sortOrder || 0
  folderDialogOpen.value = true
}

function handleDeleteFolder(data) {
  proxy.$modal.confirm(`确定删除文件夹"${data.name}"吗？文件夹内的脑图将移至根目录。`).then(() => {
    return deleteFolder(data.id)
  }).then(() => {
    proxy.$modal.msgSuccess('删除成功')
    loadFolderTree()
    if (selectedFolderKey.value === data.id) {
      selectFolder('all')
    } else {
      getList()
    }
  }).catch(() => {})
}

function submitFolder() {
  proxy.$refs['folderFormRef'].validate(valid => {
    if (!valid) return
    const promise = folderForm.id
      ? updateFolder({ id: folderForm.id, name: folderForm.name, parentId: folderForm.parentId, sortOrder: folderForm.sortOrder })
      : addFolder({ name: folderForm.name, parentId: folderForm.parentId, sortOrder: folderForm.sortOrder })
    promise.then(() => {
      proxy.$modal.msgSuccess(folderForm.id ? '重命名成功' : '创建成功')
      folderDialogOpen.value = false
      loadFolderTree()
    })
  })
}

// ─── 拖拽排序 ───
function allowFolderDrag() {
  return !folderFilter.value
}

function handleFolderDrop(draggingNode, dropNode, dropType) {
  let newParentId
  if (dropType === 'inner') {
    newParentId = dropNode.data.id
  } else {
    newParentId = dropNode.data.parentId
  }

  const siblings = dropType === 'inner'
    ? dropNode.data.children || []
    : (dropNode.parent.data.children || dropNode.parent.data)

  const items = siblings.map((item, index) => ({
    id: item.id,
    sortOrder: index,
    ...(item.id === draggingNode.data.id ? { parentId: newParentId } : {})
  }))

  sortFolders({ items }).then(() => {
    proxy.$modal.msgSuccess('排序已保存')
    loadFolderTree()
  }).catch(() => {
    proxy.$modal.msgError('排序保存失败')
    loadFolderTree()
  })
}

// ==============================
// 脑图列表相关
// ==============================

function getList() {
  loading.value = true
  listMindmap(queryParams.value).then(response => {
    mindmapList.value = response.rows
    total.value = response.total
  }).catch(() => {
    ElMessage.error('加载脑图列表失败')
  }).finally(() => {
    loading.value = false
  })
}

function handleQuery() {
  queryParams.value.pageNum = 1
  getList()
}

function resetQuery() {
  proxy.resetForm('queryRef')
  handleQuery()
}

function handleSelectionChange(selection) {
  ids.value = selection.map(item => item.id)
  multiple.value = !selection.length
}

function handleAdd() {
  const mindmapData = {
    name: '未命名脑图',
    nodeTree: { data: { text: '中心主题' }, children: [] }
  }
  if (typeof selectedFolderKey.value === 'number') {
    mindmapData.folderId = selectedFolderKey.value
  }
  addMindmap(mindmapData).then((response) => {
    proxy.$modal.msgSuccess('新建成功')
    router.push({ path: '/mindmap/edit', query: { id: response.data.id } })
  })
}

function handleView(row) {
  router.push({ path: '/mindmap/edit', query: { id: row.id, readonly: '1' } })
}

function handleEdit(row) {
  router.push({ path: '/mindmap/edit', query: { id: row.id } })
}

function handleCopy(row) {
  copyMindmap(row.id).then(() => {
    proxy.$modal.msgSuccess('复制成功')
    getList()
  })
}

function handleDelete(row) {
  const mindmapIds = row.id || ids.value.join(',')
  proxy.$modal.confirm('是否确认删除脑图编号为"' + mindmapIds + '"的数据项？').then(() => {
    return delMindmap(mindmapIds)
  }).then(() => {
    getList()
    proxy.$modal.msgSuccess('删除成功')
  }).catch(() => {})
}

// ─── 移动脑图 ───
function handleMoveOne(row) {
  moveMindmapIds.value = [row.id]
  moveFolderId.value = row.folderId || null
  moveDialogOpen.value = true
}

function handleMoveSelected() {
  moveMindmapIds.value = [...ids.value]
  moveFolderId.value = null
  moveDialogOpen.value = true
}

function submitMove() {
  moveMindmaps({
    mindmapIds: moveMindmapIds.value,
    folderId: moveFolderId.value
  }).then(() => {
    proxy.$modal.msgSuccess('移动成功')
    moveDialogOpen.value = false
    getList()
  })
}
</script>

<style lang="scss" scoped>
.mindmap-index {
  :deep(.splitpanes__splitter) {
    background: #e8eaed;
    width: 3px;
    &:hover {
      background: #409eff;
    }
  }
}

/* ========== 左侧目录树 ========== */
.dir-tree-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fafbfc;
  border-right: 1px solid #ebeef5;
}

.dir-tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 0;
  flex-shrink: 0;

  .dir-tree-title {
    font-size: 15px;
    font-weight: 600;
    color: #303133;
    letter-spacing: 0.5px;
  }
}

.dir-tree-search {
  padding: 12px 16px;
  flex-shrink: 0;

  :deep(.el-input__wrapper) {
    border-radius: 8px;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  }
}

.dir-tree-body {
  flex: 1;
  overflow: auto;
  padding: 0 8px 16px;

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: #d4d6d9;
    border-radius: 4px;
  }
  &::-webkit-scrollbar-thumb:hover {
    background: #b0b3b8;
  }

  :deep(.el-tree) {
    background: transparent;

    .el-tree-node__content {
      height: 36px;
      border-radius: 6px;
      margin-bottom: 2px;
      padding-right: 8px;
      transition: background-color 0.15s;

      &:hover {
        background: #e8f0fe;
      }
    }

    .el-tree-node.is-current > .el-tree-node__content {
      background: #d6e4ff;
      font-weight: 500;
    }

    .el-tree-node.is-drop-inner > .el-tree-node__content {
      background: #e8f0fe;
      outline: 1px dashed var(--el-color-primary);
      outline-offset: -1px;
    }

    .el-tree__drop-indicator {
      height: 2px;
      background: var(--el-color-primary);
    }
  }
}

.fixed-tree-node {
  display: flex;
  align-items: center;
  height: 36px;
  padding: 0 8px 0 16px;
  border-radius: 6px;
  margin-bottom: 2px;
  cursor: pointer;
  font-size: 13px;
  color: #303133;
  transition: background-color 0.15s;

  &:hover {
    background: #e8f0fe;
  }

  &.active {
    background: #d6e4ff;
    font-weight: 500;
  }

  .folder-icon {
    font-size: 16px;
    color: var(--el-color-primary);
    margin-right: 6px;
    flex-shrink: 0;
    opacity: 0.75;
  }

  .node-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.custom-tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  font-size: 13px;
  line-height: 1;

  .node-label {
    display: flex;
    align-items: center;
    overflow: hidden;
    min-width: 0;
    flex: 1;

    .folder-icon {
      font-size: 16px;
      color: var(--el-color-primary);
      margin-right: 6px;
      flex-shrink: 0;
      opacity: 0.75;
    }

    .node-text {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: #303133;
    }
  }

  .node-more {
    flex-shrink: 0;
    margin-left: 4px;
    opacity: 0;
    transition: opacity 0.15s;

    .more-btn {
      font-size: 16px;
      color: #909399;
      cursor: pointer;
      padding: 2px;
      border-radius: 4px;
      transition: all 0.15s;
      outline: none;

      &:hover {
        color: var(--el-color-primary);
        background: rgba(64, 158, 255, 0.08);
      }
    }
  }

  &:hover .node-more {
    opacity: 1;
  }
}

/* ========== 右侧内容区 ========== */
.main-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  overflow: hidden;
}

.content-toolbar {
  padding: 16px 20px 0;
  flex-shrink: 0;
}

.content-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  flex-shrink: 0;
}

.content-body {
  flex: 1;
  overflow: auto;
  padding: 0 20px 16px;

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: #d4d6d9;
    border-radius: 4px;
  }
}
</style>

<!-- dropdown 弹出层挂载到 body，scoped 无法覆盖，需全局样式 -->
<style lang="scss">
.mindmap-index .el-dropdown-menu__item {
  font-size: 13px;
  padding: 6px 16px;
  line-height: 22px;

  .el-icon {
    margin-right: 8px;
    font-size: 14px;
  }

  .delete-icon {
    color: #f56c6c;
  }

  .delete-text {
    color: #f56c6c;
  }

  &:hover .delete-icon,
  &:hover .delete-text {
    color: #f56c6c;
  }
}
</style>
