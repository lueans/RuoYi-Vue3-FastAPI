<template>
  <div class="app-container">
    <splitpanes class="default-theme" style="height: calc(100vh - 84px);">
      <!-- 左侧：用例目录树 -->
      <pane size="20" min-size="15" max-size="40">
        <div class="dir-tree-container">
          <div class="dir-tree-header">
            <el-input
              v-model="dirName"
              placeholder="搜索目录"
              clearable
              prefix-icon="Search"
            />
            <el-button
              type="primary"
              icon="Plus"
              circle
              size="small"
              style="margin-left: 8px;"
              @click="handleAddRoot"
              v-hasPermi="['test:caseDir:add']"
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
              @node-click="handleNodeClick"
            >
              <template #default="{ node, data }">
                <span class="custom-tree-node">
                  <span class="node-label">
                    <el-icon style="margin-right: 4px;"><Folder /></el-icon>
                    {{ node.label }}
                  </span>
                  <span class="node-actions" v-show="currentNodeId === data.dirId || hoverNodeId === data.dirId">
                    <el-icon
                      @click.stop="handleAddChild(data)"
                      v-hasPermi="['test:caseDir:add']"
                    ><Plus /></el-icon>
                    <el-icon
                      @click.stop="handleUpdate(data)"
                      v-hasPermi="['test:caseDir:edit']"
                    ><Edit /></el-icon>
                    <el-icon
                      v-if="data.parentId !== 0"
                      @click.stop="handleDelete(data)"
                      v-hasPermi="['test:caseDir:remove']"
                    ><Delete /></el-icon>
                  </span>
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
            <el-empty description="请在左侧选择目录" />
          </div>
          <div v-else class="selected-info">
            <el-empty :description="'当前目录：' + selectedDir.dirName" />
          </div>
        </div>
      </pane>
    </splitpanes>

    <!-- 新增/编辑目录对话框 -->
    <el-dialog :title="dialogTitle" v-model="dialogOpen" width="500px" append-to-body>
      <el-form ref="dirFormRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="上级目录" prop="parentId">
          <el-tree-select
            v-model="form.parentId"
            :data="dirOptions"
            :props="{ value: 'dirId', label: 'dirName', children: 'children' }"
            value-key="dirId"
            placeholder="无（创建为根目录）"
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
          <el-button type="primary" @click="submitForm">确 定</el-button>
          <el-button @click="dialogOpen = false">取 消</el-button>
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
const hoverNodeId = ref(null);

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

function resetForm() {
  form.value = {
    dirId: undefined,
    parentId: undefined,
    dirName: undefined,
    orderNum: 0,
  };
  proxy.resetForm("dirFormRef");
}

function handleAddRoot() {
  resetForm();
  listCaseDir().then(res => {
    dirOptions.value = proxy.handleTree(res.data, "dirId");
  });
  dialogOpen.value = true;
  dialogTitle.value = "新增目录";
}

function handleAddChild(data) {
  resetForm();
  listCaseDir().then(res => {
    dirOptions.value = proxy.handleTree(res.data, "dirId");
  });
  form.value.parentId = data.dirId;
  dialogOpen.value = true;
  dialogTitle.value = "新增目录";
}

function handleUpdate(data) {
  resetForm();
  listCaseDirExcludeChild(data.dirId).then(res => {
    dirOptions.value = proxy.handleTree(res.data, "dirId");
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
.dir-tree-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 12px;
  box-sizing: border-box;
}

.dir-tree-header {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.dir-tree-body {
  flex: 1;
  overflow: auto;
}

.custom-tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  font-size: 14px;

  .node-label {
    display: flex;
    align-items: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .node-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-left: 8px;
    flex-shrink: 0;

    .el-icon {
      font-size: 14px;
      color: #409eff;
      cursor: pointer;

      &:hover {
        color: #66b1ff;
      }

      &:last-child {
        color: #f56c6c;

        &:hover {
          color: #f89898;
        }
      }
    }
  }
}

.main-content {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-placeholder, .selected-info {
  text-align: center;
}
</style>
