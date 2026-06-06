<template>
  <div class="app-container">
    <!-- 搜索和筛选 -->
    <div class="filterBar">
      <el-input
        v-model="keyword"
        placeholder="搜索模板..."
        clearable
        style="width: 300px"
        @keyup.enter="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="primary" @click="handleSearch">搜索</el-button>
    </div>

    <!-- 分类标签 -->
    <div class="categoryTabs">
      <el-radio-group v-model="selectedCategory" @change="handleCategoryChange">
        <el-radio-button :value="null">全部</el-radio-button>
        <el-radio-button
          v-for="cat in categories"
          :key="cat.id"
          :value="cat.id"
        >
          {{ cat.name }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <!-- 模板卡片网格 -->
    <div class="templateGrid" v-loading="loading">
      <div v-if="templateList.length === 0 && !loading" class="emptyState">
        <el-empty description="暂无模板" />
      </div>
      <div v-for="item in templateList" :key="item.id" class="templateCard">
        <div class="cardCover">
          <img v-if="item.coverImage" :src="item.coverImage" :alt="item.name" />
          <div v-else class="defaultCover">
            <el-icon :size="48"><Document /></el-icon>
          </div>
        </div>
        <div class="cardBody">
          <div class="cardTitle">{{ item.name }}</div>
          <div class="cardDesc">{{ item.description || '暂无描述' }}</div>
          <div class="cardFooter">
            <el-tag size="small" type="info">{{ item.layout || 'logicalStructure' }}</el-tag>
            <el-button type="primary" size="small" @click="handleUseTemplate(item)">
              使用模板
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div class="paginationWrap" v-if="total > pageSize">
      <el-pagination
        layout="prev, pager, next"
        :total="total"
        :page-size="pageSize"
        v-model:current-page="pageNum"
        @current-change="loadTemplates"
      />
    </div>
  </div>
</template>

<script setup name="TemplateMarket">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Document } from '@element-plus/icons-vue'
import { listTemplates, getTemplateCategories, useTemplate } from '@/api/mindmap/template'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const loading = ref(false)
const templateList = ref([])
const categories = ref([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const selectedCategory = ref(null)

onMounted(() => {
  loadCategories()
  loadTemplates()
})

async function loadCategories() {
  try {
    const res = await getTemplateCategories()
    categories.value = res.data || []
  } catch (e) {
    console.error('加载分类失败:', e)
  }
}

async function loadTemplates() {
  loading.value = true
  try {
    const res = await listTemplates({
      categoryId: selectedCategory.value,
      keyword: keyword.value || undefined,
      pageNum: pageNum.value,
      pageSize: pageSize.value,
    })
    templateList.value = res.rows || []
    total.value = res.total || 0
  } catch (e) {
    console.error('加载模板列表失败:', e)
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  pageNum.value = 1
  loadTemplates()
}

function handleCategoryChange() {
  pageNum.value = 1
  loadTemplates()
}

async function handleUseTemplate(item) {
  try {
    await ElMessageBox.confirm(
      `使用模板「${item.name}」创建新脑图？`,
      '确认',
      { type: 'info' }
    )
    const res = await useTemplate(item.id)
    ElMessage.success('脑图创建成功')
    // 从返回信息中提取新脑图 ID 并跳转编辑
    // 由于 add_mindmap_services 返回的是 CrudResponseModel，不直接返回 ID
    // 跳转到列表页让用户找到新建的脑图
    router.push('/mindmap/index')
  } catch (e) {
    if (e !== 'cancel') {
      console.error('使用模板失败:', e)
      ElMessage.error('使用模板失败')
    }
  }
}
</script>

<style lang="scss" scoped>
.filterBar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.categoryTabs {
  margin-bottom: 20px;
}

.templateGrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 20px;
  min-height: 200px;
}

.emptyState {
  grid-column: 1 / -1;
  padding: 60px 0;
}

.templateCard {
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  transition: box-shadow 0.2s, transform 0.2s;
  cursor: pointer;

  &:hover {
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
    transform: translateY(-2px);
  }

  .cardCover {
    height: 160px;
    background: #f5f7fa;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;

    img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .defaultCover {
      color: #c0c4cc;
    }
  }

  .cardBody {
    padding: 14px;

    .cardTitle {
      font-size: 15px;
      font-weight: 600;
      color: #303133;
      margin-bottom: 6px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .cardDesc {
      font-size: 13px;
      color: #909399;
      margin-bottom: 12px;
      height: 36px;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }

    .cardFooter {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  }
}

.paginationWrap {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}
</style>
