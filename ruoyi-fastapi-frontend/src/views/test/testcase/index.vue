<template>
  <div class="app-container testcase-page">
    <splitpanes class="default-theme" style="height: calc(100vh - 84px);">
      <!-- 左侧：用例目录树 -->
      <pane size="20" min-size="15" max-size="40">
        <div class="dir-tree-container">
          <div class="dir-tree-header">
            <span class="dir-tree-title">用例目录</span>
            <el-tooltip content="新建目录" placement="top">
              <el-button
                type="primary"
                icon="Plus"
                size="small"
                plain
                @click="handleAddRoot"
                v-hasPermi="['test:caseDir:add']"
              />
            </el-tooltip>
          </div>
          <div class="dir-tree-search">
            <el-input
              v-model="dirName"
              placeholder="搜索目录..."
              clearable
              prefix-icon="Search"
              size="default"
            />
          </div>
          <div class="dir-tree-body">
            <el-tree
              :data="dirTreeData"
              :props="{ label: 'dirName', children: 'children' }"
              :expand-on-click-node="false"
              :filter-node-method="filterNode"
              ref="dirTreeRef"
              node-key="dirId"
              highlight-current
              default-expand-all
              draggable
              :allow-drag="allowDrag"
              @node-drop="handleDrop"
              @node-click="handleNodeClick"
            >
              <template #default="{ node, data }">
                <span class="custom-tree-node">
                  <span class="node-label">
                    <el-icon class="folder-icon">
                      <FolderOpened v-if="node.expanded && data.children && data.children.length" />
                      <Folder v-else />
                    </el-icon>
                    <span class="node-text">{{ node.label }}</span>
                  </span>
                  <el-dropdown
                    class="node-more"
                    trigger="hover"
                    placement="bottom-end"
                    @command="(cmd) => handleCommand(cmd, data)"
                    @click.stop
                  >
                    <el-icon class="more-btn" @click.stop><MoreFilled /></el-icon>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="add" v-hasPermi="['test:caseDir:add']">
                          <el-icon><Plus /></el-icon>新建子目录
                        </el-dropdown-item>
                        <el-dropdown-item command="edit" v-hasPermi="['test:caseDir:edit']">
                          <el-icon><Edit /></el-icon>编辑
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="data.parentId !== 0"
                          command="delete"
                          divided
                          v-hasPermi="['test:caseDir:remove']"
                        >
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
      <!-- 右侧：主内容区 -->
      <pane>
        <div class="main-content">
          <div v-if="!selectedDir" class="empty-placeholder">
            <div class="empty-inner">
              <el-icon class="empty-icon"><FolderOpened /></el-icon>
              <p class="empty-text">请在左侧选择一个目录</p>
              <p class="empty-sub">选择目录后可查看和管理用例</p>
            </div>
          </div>
          <div v-else class="selected-info">
            <div class="content-header">
              <div class="content-breadcrumb">
                <el-icon><FolderOpened /></el-icon>
                <span>{{ selectedDir.dirName }}</span>
              </div>
            </div>
            <div class="content-body">
              <el-empty description="暂无用例数据" :image-size="120" />
            </div>
          </div>
        </div>
      </pane>
    </splitpanes>

    <!-- 新增/编辑目录对话框 -->
    <el-dialog :title="dialogTitle" v-model="dialogOpen" width="500px" append-to-body destroy-on-close>
      <el-form ref="dirFormRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="上级目录" prop="parentId">
          <el-tree-select
            v-model="form.parentId"
            :data="dirOptions"
            :props="{ value: 'dirId', label: 'dirName', children: 'children' }"
            value-key="dirId"
            placeholder="请选择上级目录"
            check-strictly
            clearable
            style="width: 100%;"
          />
        </el-form-item>
        <el-form-item label="目录名称" prop="dirName">
          <el-input v-model="form.dirName" placeholder="请输入目录名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="显示排序" prop="orderNum">
          <el-input-number v-model="form.orderNum" controls-position="right" :min="0" style="width: 100%;" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="dialogOpen = false">取 消</el-button>
          <el-button type="primary" @click="submitForm">确 定</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="Testcase">
import { Splitpanes, Pane } from "splitpanes";
import "splitpanes/dist/splitpanes.css";
import { listCaseDir, getCaseDir, addCaseDir, updateCaseDir, delCaseDir, listCaseDirExcludeChild } from "@/api/test/caseDir";

const { proxy } = getCurrentInstance();

const dirTreeData = ref([]);
const dirName = ref("");
const dirTreeRef = ref(null);
const selectedDir = ref(null);
const currentNodeId = ref(null);
// hoverNodeId removed — actions now shown via CSS :hover

const dialogOpen = ref(false);
const dialogTitle = ref("");
const dirOptions = ref([]);

const form = ref({});
const rules = {
  parentId: [],
  dirName: [{ required: true, message: "目录名称不能为空", trigger: "blur" }],
  orderNum: [{ required: true, message: "显示排序不能为空", trigger: "blur" }],
};

watch(dirName, (val) => {
  dirTreeRef.value?.filter(val);
});

function filterNode(value, data) {
  if (!value) return true;
  return data.dirName.indexOf(value) !== -1;
}

function getList() {
  listCaseDir().then(res => {
    dirTreeData.value = proxy.handleTree(res.data, "dirId");
  });
}

function handleNodeClick(data) {
  currentNodeId.value = data.dirId;
  selectedDir.value = data;
}

/** 禁止拖拽搜索过滤中的树 */
function allowDrag() {
  return !dirName.value;
}

/** 拖拽落下后持久化排序 */
function handleDrop(draggingNode, dropNode, dropType) {
  // 计算拖拽后的新 parentId
  let newParentId;
  if (dropType === "inner") {
    newParentId = dropNode.data.dirId;
  } else {
    // before / after — 与目标节点同级
    newParentId = dropNode.data.parentId;
  }

  // 获取同级兄弟节点列表（拖拽后 el-tree 已更新 data）
  const siblings = dropType === "inner"
    ? dropNode.data.children || []
    : (dropNode.parent.data.children || dropNode.parent.data);

  // 逐个更新 orderNum 并持久化
  const updates = siblings.map((item, index) => {
    const data = {
      dirId: item.dirId,
      dirName: item.dirName,
      parentId: newParentId,
      orderNum: index,
    };
    // 只有被拖拽的节点需要更新 parentId，其余节点仅更新排序
    if (item.dirId !== draggingNode.data.dirId) {
      data.parentId = item.parentId;
    }
    return updateCaseDir(data);
  });

  Promise.all(updates).then(() => {
    proxy.$modal.msgSuccess("排序已保存");
    getList();
  }).catch(() => {
    proxy.$modal.msgError("排序保存失败");
    getList();
  });
}

function handleCommand(command, data) {
  switch (command) {
    case "add":
      handleAddChild(data);
      break;
    case "edit":
      handleUpdate(data);
      break;
    case "delete":
      handleDelete(data);
      break;
  }
}

function resetForm() {
  form.value = {
    dirId: undefined,
    parentId: undefined,
    dirName: undefined,
    orderNum: 0,
  };
  proxy.resetForm("dirFormRef");
}

/** 将接口返回的目录列表包装为带"根目录"虚拟节点的选项树 */
function buildDirOptions(list) {
  return [{ dirId: 0, dirName: "根目录", children: proxy.handleTree(list, "dirId") }];
}

function handleAddRoot() {
  resetForm();
  listCaseDir().then(res => {
    dirOptions.value = buildDirOptions(res.data);
  });
  dialogOpen.value = true;
  dialogTitle.value = "新增目录";
}

function handleAddChild(data) {
  resetForm();
  listCaseDir().then(res => {
    dirOptions.value = buildDirOptions(res.data);
  });
  form.value.parentId = data.dirId;
  dialogOpen.value = true;
  dialogTitle.value = "新增目录";
}

function handleUpdate(data) {
  resetForm();
  listCaseDirExcludeChild(data.dirId).then(res => {
    dirOptions.value = buildDirOptions(res.data);
  });
  getCaseDir(data.dirId).then(res => {
    form.value = res.data;
    dialogOpen.value = true;
    dialogTitle.value = "修改目录";
  });
}

function submitForm() {
  proxy.$refs["dirFormRef"].validate(valid => {
    if (valid) {
      const submitData = { ...form.value };
      if (submitData.parentId == null) {
        submitData.parentId = 0;
      }
      if (submitData.dirId != undefined) {
        updateCaseDir(submitData).then(() => {
          proxy.$modal.msgSuccess("修改成功");
          dialogOpen.value = false;
          getList();
        });
      } else {
        addCaseDir(submitData).then(() => {
          proxy.$modal.msgSuccess("新增成功");
          dialogOpen.value = false;
          getList();
        });
      }
    }
  });
}

function handleDelete(data) {
  proxy.$modal.confirm('是否确认删除目录"' + data.dirName + '"?').then(() => {
    return delCaseDir(data.dirId);
  }).then(() => {
    getList();
    if (selectedDir.value && selectedDir.value.dirId === data.dirId) {
      selectedDir.value = null;
      currentNodeId.value = null;
    }
    proxy.$modal.msgSuccess("删除成功");
  }).catch(() => {});
}

getList();
</script>

<style lang="scss" scoped>
.testcase-page {
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

    /* 拖拽视觉反馈 */
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
}

.empty-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;

  .empty-inner {
    text-align: center;

    .empty-icon {
      font-size: 64px;
      color: #c0c4cc;
      margin-bottom: 16px;
    }

    .empty-text {
      font-size: 15px;
      color: #606266;
      margin: 0 0 8px;
    }

    .empty-sub {
      font-size: 13px;
      color: #909399;
      margin: 0;
    }
  }
}

.selected-info {
  display: flex;
  flex-direction: column;
  height: 100%;

  .content-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid #ebeef5;
    background: #fafbfc;
    flex-shrink: 0;

    .content-breadcrumb {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 15px;
      font-weight: 600;
      color: #303133;

      .el-icon {
        font-size: 18px;
        color: var(--el-color-primary);
        opacity: 0.75;
      }
    }
  }

  .content-body {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
}
</style>

<!-- dropdown 弹出层挂载到 body，scoped 无法覆盖，需全局样式 -->
<style lang="scss">
.testcase-page .el-dropdown-menu__item {
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
