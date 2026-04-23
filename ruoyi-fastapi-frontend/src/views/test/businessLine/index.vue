<template>
   <div class="app-container">
      <el-form :model="queryParams" ref="queryRef" :inline="true" v-show="showSearch">
         <el-form-item label="业务线名称" prop="lineName">
            <el-input
               v-model="queryParams.lineName"
               placeholder="请输入业务线名称"
               clearable
               style="width: 200px"
               @keyup.enter="handleQuery"
            />
         </el-form-item>
         <el-form-item label="业务线编码" prop="lineCode">
            <el-input
               v-model="queryParams.lineCode"
               placeholder="请输入业务线编码"
               clearable
               style="width: 200px"
               @keyup.enter="handleQuery"
            />
         </el-form-item>
         <el-form-item label="状态" prop="status">
            <el-select v-model="queryParams.status" placeholder="业务线状态" clearable style="width: 200px">
               <el-option
                  v-for="dict in sys_normal_disable"
                  :key="dict.value"
                  :label="dict.label"
                  :value="dict.value"
               />
            </el-select>
         </el-form-item>
         <el-form-item>
            <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
            <el-button icon="Refresh" @click="resetQuery">重置</el-button>
         </el-form-item>
      </el-form>

      <el-row :gutter="10" class="mb8">
         <el-col :span="1.5">
            <el-button
               type="primary"
               plain
               icon="Plus"
               @click="handleAdd"
               v-hasPermi="['test:businessLine:add']"
            >新增</el-button>
         </el-col>
         <el-col :span="1.5">
            <el-button
               type="info"
               plain
               icon="Sort"
               @click="toggleExpandAll"
            >展开/折叠</el-button>
         </el-col>
         <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
      </el-row>

      <el-table
         v-if="refreshTable"
         v-loading="loading"
         :data="businessLineList"
         row-key="lineId"
         :default-expand-all="isExpandAll"
         :tree-props="{ children: 'children', hasChildren: 'hasChildren' }"
      >
         <el-table-column prop="lineName" label="业务线名称" width="220"></el-table-column>
         <el-table-column prop="lineCode" label="业务线编码" width="160"></el-table-column>
         <el-table-column prop="leader" label="负责人" width="120"></el-table-column>
         <el-table-column prop="orderNum" label="排序" width="80"></el-table-column>
         <el-table-column prop="status" label="状态" width="100">
            <template #default="scope">
               <dict-tag :options="sys_normal_disable" :value="scope.row.status" />
            </template>
         </el-table-column>
         <el-table-column label="创建时间" align="center" prop="createTime" width="200">
            <template #default="scope">
               <span>{{ parseTime(scope.row.createTime) }}</span>
            </template>
         </el-table-column>
         <el-table-column label="操作" align="center" class-name="small-padding fixed-width">
            <template #default="scope">
               <el-button link type="primary" icon="Edit" @click="handleUpdate(scope.row)" v-hasPermi="['test:businessLine:edit']">修改</el-button>
               <el-button link type="primary" icon="Plus" @click="handleAdd(scope.row)" v-hasPermi="['test:businessLine:add']">新增</el-button>
               <el-button v-if="scope.row.parentId != 0" link type="primary" icon="Delete" @click="handleDelete(scope.row)" v-hasPermi="['test:businessLine:remove']">删除</el-button>
            </template>
         </el-table-column>
      </el-table>

      <!-- 添加或修改业务线对话框 -->
      <el-dialog :title="title" v-model="open" width="600px" append-to-body>
         <el-form ref="businessLineRef" :model="form" :rules="rules" label-width="100px">
            <el-row>
               <el-col :span="24" v-if="form.parentId !== 0">
                  <el-form-item label="上级业务线" prop="parentId">
                     <el-tree-select
                        v-model="form.parentId"
                        :data="businessLineOptions"
                        :props="{ value: 'lineId', label: 'lineName', children: 'children' }"
                        value-key="lineId"
                        placeholder="选择上级业务线"
                        check-strictly
                     />
                  </el-form-item>
               </el-col>
               <el-col :span="12">
                  <el-form-item label="业务线编码" prop="lineCode">
                     <el-input v-model="form.lineCode" placeholder="请输入业务线编码" maxlength="50" />
                  </el-form-item>
               </el-col>
               <el-col :span="12">
                  <el-form-item label="业务线名称" prop="lineName">
                     <el-input v-model="form.lineName" placeholder="请输入业务线名称" maxlength="30" />
                  </el-form-item>
               </el-col>
               <el-col :span="12">
                  <el-form-item label="显示排序" prop="orderNum">
                     <el-input-number v-model="form.orderNum" controls-position="right" :min="0" />
                  </el-form-item>
               </el-col>
               <el-col :span="12">
                  <el-form-item label="负责人" prop="leader">
                     <user-select v-model="form.leader" placeholder="请选择负责人" />
                  </el-form-item>
               </el-col>
               <el-col :span="12">
                  <el-form-item label="状态">
                     <el-radio-group v-model="form.status">
                        <el-radio
                           v-for="dict in sys_normal_disable"
                           :key="dict.value"
                           :value="dict.value"
                        >{{ dict.label }}</el-radio>
                     </el-radio-group>
                  </el-form-item>
               </el-col>
               <el-col :span="24">
                  <el-form-item label="备注" prop="remark">
                     <el-input v-model="form.remark" placeholder="请输入备注" type="textarea" />
                  </el-form-item>
               </el-col>
            </el-row>
         </el-form>
         <template #footer>
            <div class="dialog-footer">
               <el-button type="primary" @click="submitForm">确 定</el-button>
               <el-button @click="cancel">取 消</el-button>
            </div>
         </template>
      </el-dialog>
   </div>
</template>

<script setup name="BusinessLine">
import { listBusinessLine, getBusinessLine, delBusinessLine, addBusinessLine, updateBusinessLine, listBusinessLineExcludeChild } from "@/api/test/businessLine";

const { proxy } = getCurrentInstance();
const { sys_normal_disable } = proxy.useDict("sys_normal_disable");

const businessLineList = ref([]);
const open = ref(false);
const loading = ref(true);
const showSearch = ref(true);
const title = ref("");
const businessLineOptions = ref([]);
const isExpandAll = ref(true);
const refreshTable = ref(true);

const data = reactive({
  form: {},
  queryParams: {
    lineName: undefined,
    lineCode: undefined,
    status: undefined
  },
  rules: {
    parentId: [{ required: true, message: "上级业务线不能为空", trigger: "blur" }],
    lineCode: [{ required: true, message: "业务线编码不能为空", trigger: "blur" }],
    lineName: [{ required: true, message: "业务线名称不能为空", trigger: "blur" }],
    orderNum: [{ required: true, message: "显示排序不能为空", trigger: "blur" }]
  },
});

const { queryParams, form, rules } = toRefs(data);

/** 查询业务线列表 */
function getList() {
  loading.value = true;
  listBusinessLine(queryParams.value).then(response => {
    businessLineList.value = proxy.handleTree(response.data, "lineId");
    loading.value = false;
  });
}
/** 取消按钮 */
function cancel() {
  open.value = false;
  reset();
}
/** 表单重置 */
function reset() {
  form.value = {
    lineId: undefined,
    parentId: undefined,
    lineCode: undefined,
    lineName: undefined,
    orderNum: 0,
    leader: undefined,
    status: "0",
    remark: undefined
  };
  proxy.resetForm("businessLineRef");
}
/** 搜索按钮操作 */
function handleQuery() {
  getList();
}
/** 重置按钮操作 */
function resetQuery() {
  proxy.resetForm("queryRef");
  handleQuery();
}
/** 新增按钮操作 */
function handleAdd(row) {
  reset();
  listBusinessLine().then(response => {
    businessLineOptions.value = proxy.handleTree(response.data, "lineId");
  });
  if (row != undefined) {
    form.value.parentId = row.lineId;
  }
  open.value = true;
  title.value = "添加业务线";
}
/** 展开/折叠操作 */
function toggleExpandAll() {
  refreshTable.value = false;
  isExpandAll.value = !isExpandAll.value;
  nextTick(() => {
    refreshTable.value = true;
  });
}
/** 修改按钮操作 */
function handleUpdate(row) {
  reset();
  listBusinessLineExcludeChild(row.lineId).then(response => {
    businessLineOptions.value = proxy.handleTree(response.data, "lineId");
  });
  getBusinessLine(row.lineId).then(response => {
    form.value = response.data;
    open.value = true;
    title.value = "修改业务线";
  });
}
/** 提交按钮 */
function submitForm() {
  proxy.$refs["businessLineRef"].validate(valid => {
    if (valid) {
      if (form.value.lineId != undefined) {
        updateBusinessLine(form.value).then(response => {
          proxy.$modal.msgSuccess("修改成功");
          open.value = false;
          getList();
        });
      } else {
        addBusinessLine(form.value).then(response => {
          proxy.$modal.msgSuccess("新增成功");
          open.value = false;
          getList();
        });
      }
    }
  });
}
/** 删除按钮操作 */
function handleDelete(row) {
  proxy.$modal.confirm('是否确认删除名称为"' + row.lineName + '"的数据项?').then(function() {
    return delBusinessLine(row.lineId);
  }).then(() => {
    getList();
    proxy.$modal.msgSuccess("删除成功");
  }).catch(() => {});
}

getList();
</script>
