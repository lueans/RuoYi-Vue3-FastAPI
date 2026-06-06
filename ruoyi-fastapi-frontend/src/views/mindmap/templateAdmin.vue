<template>
  <div class="app-container">
    <!-- 工具栏 -->
    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button type="primary" plain icon="Plus" @click="handlePublish" v-hasPermi="['mindmap:template:add']">
          发布模板
        </el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button type="success" plain icon="Folder" @click="showCategoryDialog = true" v-hasPermi="['mindmap:template:add']">
          管理分类
        </el-button>
      </el-col>
    </el-row>

    <!-- 模板列表 -->
    <el-table v-loading="loading" :data="templateList">
      <el-table-column label="ID" prop="id" width="80" align="center" />
      <el-table-column label="名称" prop="name" min-width="160" show-overflow-tooltip />
      <el-table-column label="描述" prop="description" min-width="200" show-overflow-tooltip />
      <el-table-column label="布局" prop="layout" width="140" align="center" />
      <el-table-column label="封面" prop="coverImage" width="100" align="center">
        <template #default="{ row }">
          <el-image v-if="row.coverImage" :src="row.coverImage" :preview-src-list="[row.coverImage]" style="width: 60px; height: 40px; border-radius: 4px;" fit="cover" />
          <span v-else class="noCover">无</span>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" prop="createTime" width="180" align="center">
        <template #default="{ row }">
          {{ parseTime(row.createTime) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button link type="primary" icon="View" @click="handlePreview(row)">预览</el-button>
          <el-button link type="danger" icon="Delete" @click="handleUnpublish(row)" v-hasPermi="['mindmap:template:remove']">下架</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <pagination
      v-show="total > 0"
      :total="total"
      v-model:page="pageNum"
      v-model:limit="pageSize"
      @pagination="loadTemplates"
    />

    <!-- 发布模板对话框 -->
    <el-dialog title="发布模板" v-model="publishDialogVisible" width="500px">
      <el-form ref="publishFormRef" :model="publishForm" :rules="publishRules" label-width="80px">
        <el-form-item label="源脑图ID" prop="mindmapId">
          <el-input-number v-model="publishForm.mindmapId" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="模板名称" prop="name">
          <el-input v-model="publishForm.name" placeholder="请输入模板名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="publishForm.description" type="textarea" :rows="3" placeholder="请输入描述" />
        </el-form-item>
        <el-form-item label="封面URL" prop="coverImage">
          <el-input v-model="publishForm.coverImage" placeholder="封面图片URL（可选）" />
        </el-form-item>
        <el-form-item label="分类" prop="templateCategoryId">
          <el-select v-model="publishForm.templateCategoryId" placeholder="选择分类" clearable style="width: 100%">
            <el-option v-for="cat in categories" :key="cat.id" :label="cat.name" :value="cat.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="publishDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPublish">发布</el-button>
      </template>
    </el-dialog>

    <!-- 分类管理对话框 -->
    <el-dialog title="模板分类管理" v-model="showCategoryDialog" width="500px">
      <div class="categoryList">
        <div v-for="cat in categories" :key="cat.id" class="categoryItem">
          <span>{{ cat.name }}</span>
          <el-button link type="danger" size="small" @click="handleDeleteCategory(cat)">删除</el-button>
        </div>
        <div v-if="categories.length === 0" class="emptyTip">暂无分类</div>
      </div>
      <el-divider />
      <el-form :inline="true" size="small">
        <el-form-item label="分类名称">
          <el-input v-model="newCategoryName" placeholder="新分类名称" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleAddCategory">添加</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup name="TemplateAdmin">
import { ref, reactive, onMounted, getCurrentInstance } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listTemplates, getTemplateCategories, publishTemplate, unpublishTemplate, addTemplateCategory, deleteTemplateCategory } from '@/api/mindmap/template'

const router = useRouter()
const { proxy } = getCurrentInstance()

const loading = ref(false)
const templateList = ref([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const categories = ref([])

const publishDialogVisible = ref(false)
const publishFormRef = ref(null)
const publishForm = reactive({
  mindmapId: null,
  name: '',
  description: '',
  coverImage: '',
  templateCategoryId: null,
})
const publishRules = {
  mindmapId: [{ required: true, message: '请输入源脑图ID', trigger: 'blur' }],
  name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
}

const showCategoryDialog = ref(false)
const newCategoryName = ref('')

onMounted(() => {
  loadCategories()
  loadTemplates()
})

async function loadCategories() {
  try {
    const res = await getTemplateCategories()
    categories.value = res.data || []
  } catch (e) {
    console.error(e)
  }
}

async function loadTemplates() {
  loading.value = true
  try {
    const res = await listTemplates({ pageNum: pageNum.value, pageSize: pageSize.value })
    templateList.value = res.rows || []
    total.value = res.total || 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function handlePublish() {
  publishForm.mindmapId = null
  publishForm.name = ''
  publishForm.description = ''
  publishForm.coverImage = ''
  publishForm.templateCategoryId = null
  publishDialogVisible.value = true
}

async function submitPublish() {
  const form = publishFormRef.value
  if (!form) return
  await form.validate(async (valid) => {
    if (!valid) return
    try {
      await publishTemplate({
        mindmapId: publishForm.mindmapId,
        name: publishForm.name,
        description: publishForm.description || undefined,
        coverImage: publishForm.coverImage || undefined,
        templateCategoryId: publishForm.templateCategoryId || undefined,
      })
      ElMessage.success('模板发布成功')
      publishDialogVisible.value = false
      loadTemplates()
    } catch (e) {
      console.error(e)
    }
  })
}

async function handleUnpublish(row) {
  try {
    await ElMessageBox.confirm(`确认下架模板「${row.name}」？`, '确认', { type: 'warning' })
    await unpublishTemplate(row.id)
    ElMessage.success('模板已下架')
    loadTemplates()
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

function handlePreview(row) {
  router.push({ path: '/mindmap/edit', query: { id: row.id, readonly: '1' } })
}

async function handleAddCategory() {
  if (!newCategoryName.value.trim()) {
    ElMessage.warning('请输入分类名称')
    return
  }
  try {
    await addTemplateCategory(newCategoryName.value.trim(), 0)
    ElMessage.success('分类添加成功')
    newCategoryName.value = ''
    loadCategories()
  } catch (e) {
    console.error(e)
  }
}

async function handleDeleteCategory(cat) {
  try {
    await ElMessageBox.confirm(`确认删除分类「${cat.name}」？`, '确认', { type: 'warning' })
    await deleteTemplateCategory(cat.id)
    ElMessage.success('分类已删除')
    loadCategories()
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}
</script>

<style lang="scss" scoped>
.categoryList {
  max-height: 200px;
  overflow-y: auto;

  .categoryItem {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid #f0f0f0;
  }

  .emptyTip {
    text-align: center;
    color: #999;
    padding: 20px;
  }
}

.noCover {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
