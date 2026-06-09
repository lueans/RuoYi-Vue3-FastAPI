<template>
  <div class="app-container">
    <el-row :gutter="20">
      <!-- 左侧：分类管理 -->
      <el-col :span="6">
        <el-card shadow="never">
          <template #header>
            <div class="cardHeader">
              <span>标签分类</span>
              <el-button type="primary" size="small" @click="handleAddCategory">
                <el-icon><Plus /></el-icon>
              </el-button>
            </div>
          </template>
          <div class="categoryList">
            <div
              class="categoryItem"
              :class="{ active: selectedCategory === null }"
              @click="selectCategory(null)"
            >
              <span>全部标签</span>
            </div>
            <div
              v-for="cat in categories"
              :key="cat.id"
              class="categoryItem"
              :class="{ active: selectedCategory === cat.id }"
              @click="selectCategory(cat.id)"
            >
              <span class="categoryName">{{ cat.name }}</span>
              <span class="categoryBadge" v-if="cat.ownerId === 0">全局</span>
              <div class="categoryActions" @click.stop>
                <el-button link size="small" @click="handleEditCategory(cat)">
                  <el-icon><Edit /></el-icon>
                </el-button>
                <el-button link size="small" type="danger" @click="handleDeleteCategory(cat)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
            <div v-if="categories.length === 0" class="emptyTip">暂无分类</div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：标签列表 -->
      <el-col :span="18">
        <el-card shadow="never">
          <template #header>
            <div class="cardHeader">
              <div class="headerLeft">
                <el-input
                  v-model="queryParams.keyword"
                  placeholder="搜索标签名称/key..."
                  clearable
                  style="width: 240px"
                  @keyup.enter="handleSearch"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <el-select v-model="queryParams.ownerScope" style="width: 120px" @change="handleSearch">
                  <el-option label="全部" value="all" />
                  <el-option label="我的" value="mine" />
                  <el-option label="全局" value="global" />
                </el-select>
                <el-button type="primary" @click="handleSearch">搜索</el-button>
              </div>
              <el-button type="primary" @click="handleAddTag">
                <el-icon><Plus /></el-icon> 新增标签
              </el-button>
            </div>
          </template>

          <el-table :data="tagList" v-loading="loading" stripe>
            <el-table-column label="名称" prop="name" min-width="120">
              <template #default="{ row }">
                <div class="tagPreview">
                  <span
                    class="tagBadge"
                    :style="getTagStyle(row.style)"
                  >{{ row.name }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="Key" prop="tagKey" width="140" show-overflow-tooltip />
            <el-table-column label="分类" width="120">
              <template #default="{ row }">
                {{ getCategoryName(row.categoryId) || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="范围" width="80">
              <template #default="{ row }">
                <el-tag :type="row.ownerId === 0 ? 'success' : 'info'" size="small">
                  {{ row.ownerId === 0 ? '全局' : '私有' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="描述" prop="description" min-width="150" show-overflow-tooltip />
            <el-table-column label="创建人" prop="createdBy" width="100" />
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="handleEditTag(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="handleDeleteTag(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="paginationWrap" v-if="total > queryParams.pageSize">
            <el-pagination
              layout="total, prev, pager, next"
              :total="total"
              :page-size="queryParams.pageSize"
              v-model:current-page="queryParams.pageNum"
              @current-change="loadTags"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 分类弹窗 -->
    <el-dialog v-model="categoryDialogVisible" :title="categoryForm.id ? '编辑分类' : '新增分类'" width="420px">
      <el-form :model="categoryForm" label-width="80px">
        <el-form-item label="分类名称" required>
          <el-input v-model="categoryForm.name" placeholder="请输入分类名称" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="categoryForm.sortOrder" :min="0" :max="999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCategory">确定</el-button>
      </template>
    </el-dialog>

    <!-- 标签弹窗 -->
    <el-dialog v-model="tagDialogVisible" :title="tagForm.id ? '编辑标签' : '新增标签'" width="520px">
      <el-form :model="tagForm" label-width="80px" :rules="tagRules" ref="tagFormRef">
        <el-form-item label="标签Key" prop="tagKey">
          <el-input v-model="tagForm.tagKey" placeholder="唯一标识（英文/数字/下划线）" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="tagForm.name" placeholder="标签显示名称" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="tagForm.categoryId" clearable placeholder="选择分类" style="width: 100%">
            <el-option v-for="cat in categories" :key="cat.id" :label="cat.name" :value="cat.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="背景色">
          <el-color-picker v-model="tagStyleForm.fill" />
        </el-form-item>
        <el-form-item label="文字色">
          <el-color-picker v-model="tagStyleForm.color" />
        </el-form-item>
        <el-form-item label="字号">
          <el-input-number v-model="tagStyleForm.fontSize" :min="10" :max="24" />
        </el-form-item>
        <el-form-item label="预览">
          <span class="tagBadge" :style="getTagStyle(tagStyleForm)">
            {{ tagForm.name || '标签预览' }}
          </span>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="tagForm.description" type="textarea" :rows="2" placeholder="标签描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tagDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTag">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="TagManagement">
import { ref, reactive, onMounted } from 'vue'
import { Plus, Edit, Delete, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listTagCategories, addTagCategory, updateTagCategory, deleteTagCategory,
  listTags, addTag, updateTag, deleteTags
} from '@/api/mindmap/tag'

const loading = ref(false)
const categories = ref([])
const tagList = ref([])
const total = ref(0)
const selectedCategory = ref(null)

const queryParams = reactive({
  keyword: '',
  ownerScope: 'all',
  categoryId: null,
  pageNum: 1,
  pageSize: 20,
})

// ── 分类 ──
const categoryDialogVisible = ref(false)
const categoryForm = reactive({ id: null, name: '', sortOrder: 0 })

async function loadCategories() {
  try {
    const res = await listTagCategories()
    categories.value = res.data || []
  } catch (e) {
    console.error('加载分类失败:', e)
  }
}

function selectCategory(id) {
  selectedCategory.value = id
  queryParams.categoryId = id
  queryParams.pageNum = 1
  loadTags()
}

function handleAddCategory() {
  categoryForm.id = null
  categoryForm.name = ''
  categoryForm.sortOrder = 0
  categoryDialogVisible.value = true
}

function handleEditCategory(cat) {
  categoryForm.id = cat.id
  categoryForm.name = cat.name
  categoryForm.sortOrder = cat.sortOrder || 0
  categoryDialogVisible.value = true
}

async function handleDeleteCategory(cat) {
  try {
    await ElMessageBox.confirm(`确认删除分类「${cat.name}」？`, '提示', { type: 'warning' })
    await deleteTagCategory(cat.id)
    ElMessage.success('分类删除成功')
    if (selectedCategory.value === cat.id) {
      selectCategory(null)
    }
    loadCategories()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

async function submitCategory() {
  if (!categoryForm.name?.trim()) {
    ElMessage.warning('请输入分类名称')
    return
  }
  try {
    if (categoryForm.id) {
      await updateTagCategory(categoryForm.id, categoryForm.name, categoryForm.sortOrder)
    } else {
      await addTagCategory(categoryForm.name, categoryForm.sortOrder)
    }
    ElMessage.success(categoryForm.id ? '分类更新成功' : '分类创建成功')
    categoryDialogVisible.value = false
    loadCategories()
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  }
}

// ── 标签 ──
const tagDialogVisible = ref(false)
const tagFormRef = ref(null)
const tagForm = reactive({
  id: null, tagKey: '', name: '', categoryId: null, description: '',
})
const tagStyleForm = reactive({ fill: '#409eff', color: '#ffffff', fontSize: 12 })
const tagRules = {
  tagKey: [{ required: true, message: '请输入标签Key', trigger: 'blur' }],
  name: [{ required: true, message: '请输入标签名称', trigger: 'blur' }],
}

async function loadTags() {
  loading.value = true
  try {
    const res = await listTags(queryParams)
    tagList.value = res.rows || []
    total.value = res.total || 0
  } catch (e) {
    console.error('加载标签列表失败:', e)
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  queryParams.pageNum = 1
  loadTags()
}

function handleAddTag() {
  tagForm.id = null
  tagForm.tagKey = ''
  tagForm.name = ''
  tagForm.categoryId = selectedCategory.value
  tagForm.description = ''
  tagStyleForm.fill = '#409eff'
  tagStyleForm.color = '#ffffff'
  tagStyleForm.fontSize = 12
  tagDialogVisible.value = true
}

function handleEditTag(row) {
  tagForm.id = row.id
  tagForm.tagKey = row.tagKey
  tagForm.name = row.name
  tagForm.categoryId = row.categoryId
  tagForm.description = row.description || ''
  const style = row.style || {}
  tagStyleForm.fill = style.fill || '#409eff'
  tagStyleForm.color = style.color || '#ffffff'
  tagStyleForm.fontSize = style.fontSize || 12
  tagDialogVisible.value = true
}

async function handleDeleteTag(row) {
  try {
    await ElMessageBox.confirm(`确认删除标签「${row.name}」？`, '提示', { type: 'warning' })
    await deleteTags(row.id.toString())
    ElMessage.success('标签删除成功')
    loadTags()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

async function submitTag() {
  try {
    await tagFormRef.value?.validate()
  } catch { return }

  const data = {
    tagKey: tagForm.tagKey,
    name: tagForm.name,
    categoryId: tagForm.categoryId || null,
    description: tagForm.description || null,
    style: {
      fill: tagStyleForm.fill,
      color: tagStyleForm.color,
      fontSize: tagStyleForm.fontSize,
    },
  }

  try {
    if (tagForm.id) {
      data.id = tagForm.id
      await updateTag(data)
    } else {
      await addTag(data)
    }
    ElMessage.success(tagForm.id ? '标签更新成功' : '标签创建成功')
    tagDialogVisible.value = false
    loadTags()
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  }
}

// ── 工具函数 ──
function getCategoryName(categoryId) {
  if (!categoryId) return null
  return categories.value.find(c => c.id === categoryId)?.name
}

function getTagStyle(style) {
  if (!style) return { backgroundColor: '#409eff', color: '#fff', fontSize: '12px', borderRadius: '3px', padding: '2px 8px' }
  return {
    backgroundColor: style.fill || '#409eff',
    color: style.color || '#fff',
    fontSize: (style.fontSize || 12) + 'px',
    borderRadius: '3px',
    padding: '2px 8px',
    display: 'inline-block',
  }
}

onMounted(() => {
  loadCategories()
  loadTags()
})
</script>

<style lang="scss" scoped>
.cardHeader {
  display: flex;
  justify-content: space-between;
  align-items: center;

  .headerLeft {
    display: flex;
    gap: 10px;
    align-items: center;
  }
}

.categoryList {
  .categoryItem {
    display: flex;
    align-items: center;
    padding: 8px 12px;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.2s;
    margin-bottom: 2px;

    &:hover {
      background: #f5f7fa;
    }

    &.active {
      background: #ecf5ff;
      color: #409eff;
      font-weight: 500;
    }

    .categoryName {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .categoryBadge {
      font-size: 11px;
      color: #67c23a;
      margin: 0 6px;
    }

    .categoryActions {
      display: none;
      gap: 2px;
    }

    &:hover .categoryActions {
      display: flex;
    }
  }

  .emptyTip {
    text-align: center;
    color: #999;
    padding: 20px 0;
    font-size: 13px;
  }
}

.tagPreview {
  .tagBadge {
    display: inline-block;
    line-height: 1.4;
  }
}

.paginationWrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
