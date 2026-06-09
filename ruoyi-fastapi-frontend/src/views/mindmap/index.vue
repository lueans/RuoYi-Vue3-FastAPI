<template>
   <div class="app-container">
      <el-form :model="queryParams" ref="queryRef" :inline="true" v-show="showSearch">
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
            <el-select v-model="queryParams.status" placeholder="脑图状态" clearable style="width: 200px">
               <el-option label="正常" :value="0" />
               <el-option label="归档" :value="1" />
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
               v-hasPermi="['mindmap:mindmap:add']"
            >新建脑图</el-button>
         </el-col>
         <el-col :span="1.5">
            <el-button
               type="danger"
               plain
               icon="Delete"
               :disabled="multiple"
               @click="handleDelete"
               v-hasPermi="['mindmap:mindmap:remove']"
            >删除</el-button>
         </el-col>
         <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
      </el-row>

      <el-table v-loading="loading" :data="mindmapList" @selection-change="handleSelectionChange">
         <el-table-column type="selection" width="55" align="center" />
         <el-table-column label="ID" align="center" prop="id" width="80" />
         <el-table-column label="名称" align="center" prop="name" :show-overflow-tooltip="true" />
         <el-table-column label="描述" align="center" prop="description" :show-overflow-tooltip="true" />
         <el-table-column label="布局" align="center" prop="layout" width="120" />
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
         <el-table-column label="操作" width="320" align="center" class-name="small-padding fixed-width">
            <template #default="scope">
               <el-button link type="primary" icon="View" @click="handleView(scope.row)" v-hasPermi="['mindmap:mindmap:query']">查看</el-button>
               <el-button link type="primary" icon="Edit" @click="handleEdit(scope.row)" v-hasPermi="['mindmap:mindmap:edit']">编辑</el-button>
               <el-button link type="primary" icon="CopyDocument" @click="handleCopy(scope.row)" v-hasPermi="['mindmap:mindmap:add']">复制</el-button>
               <el-button link type="primary" icon="Delete" @click="handleDelete(scope.row)" v-hasPermi="['mindmap:mindmap:remove']">删除</el-button>
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

      <!-- 重命名对话框 -->
      <el-dialog title="重命名脑图" v-model="renameOpen" width="500px" append-to-body>
         <el-form ref="renameRef" :model="renameForm" :rules="renameRules" label-width="80px">
            <el-form-item label="名称" prop="name">
               <el-input v-model="renameForm.name" placeholder="请输入脑图名称" />
            </el-form-item>
            <el-form-item label="描述" prop="description">
               <el-input v-model="renameForm.description" type="textarea" placeholder="请输入描述" />
            </el-form-item>
         </el-form>
         <template #footer>
            <div class="dialog-footer">
               <el-button type="primary" @click="submitRename">确 定</el-button>
               <el-button @click="renameOpen = false">取 消</el-button>
            </div>
         </template>
      </el-dialog>
   </div>
</template>

<script setup name="MindmapManagement">
import { listMindmap, delMindmap, renameMindmap, copyMindmap, addMindmap } from '@/api/mindmap/mindmap'
import { useRouter } from 'vue-router'

const { proxy } = getCurrentInstance()
const router = useRouter()

const mindmapList = ref([])
const loading = ref(true)
const showSearch = ref(true)
const ids = ref([])
const multiple = ref(true)
const total = ref(0)
const renameOpen = ref(false)

const data = reactive({
  queryParams: {
    pageNum: 1,
    pageSize: 10,
    name: undefined,
    status: undefined
  },
  renameForm: {},
  renameRules: {
    name: [{ required: true, message: "脑图名称不能为空", trigger: "blur" }]
  }
})

const { queryParams, renameForm, renameRules } = toRefs(data)

/** 查询脑图列表 */
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

/** 搜索按钮操作 */
function handleQuery() {
  queryParams.value.pageNum = 1
  getList()
}

/** 重置按钮操作 */
function resetQuery() {
  proxy.resetForm("queryRef")
  handleQuery()
}

/** 多选框选中数据 */
function handleSelectionChange(selection) {
  ids.value = selection.map(item => item.id)
  multiple.value = !selection.length
}

/** 新建脑图 */
function handleAdd() {
  addMindmap({
    name: '未命名脑图',
    nodeTree: { data: { text: '中心主题' }, children: [] }
  }).then((response) => {
    proxy.$modal.msgSuccess("新建成功")
    // 跳转到新脑图编辑页
    router.push({ path: '/mindmap/edit', query: { id: response.data.id } })
  })
}

/** 查看脑图 */
function handleView(row) {
  router.push({ path: '/mindmap/edit', query: { id: row.id, readonly: '1' } })
}

/** 编辑脑图 */
function handleEdit(row) {
  router.push({ path: '/mindmap/edit', query: { id: row.id } })
}

/** 复制脑图 */
function handleCopy(row) {
  copyMindmap(row.id).then(() => {
    proxy.$modal.msgSuccess("复制成功")
    getList()
  })
}

/** 删除脑图 */
function handleDelete(row) {
  const mindmapIds = row.id || ids.value.join(',')
  proxy.$modal.confirm('是否确认删除脑图编号为"' + mindmapIds + '"的数据项？').then(function() {
    return delMindmap(mindmapIds)
  }).then(() => {
    getList()
    proxy.$modal.msgSuccess("删除成功")
  }).catch(() => {})
}

/** 重命名脑图 */
function handleRename(row) {
  renameForm.value = {
    id: row.id,
    name: row.name,
    description: row.description
  }
  renameOpen.value = true
}

/** 提交重命名 */
function submitRename() {
  proxy.$refs["renameRef"].validate(valid => {
    if (valid) {
      renameMindmap(renameForm.value).then(() => {
        proxy.$modal.msgSuccess("重命名成功")
        renameOpen.value = false
        getList()
      })
    }
  })
}

getList()
</script>
