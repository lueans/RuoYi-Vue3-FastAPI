<template>
  <main class="templateMarketPage">
    <section class="marketHero" aria-labelledby="template-market-title">
      <div>
        <span class="eyebrow">MIND MAP TEMPLATES</span>
        <h1 id="template-market-title">从一个好结构开始</h1>
        <p>选择经过整理的脑图模板，预览完整内容后创建属于你的独立副本。</p>
      </div>
      <div class="heroMetric" aria-label="当前模板数量">
        <strong>{{ total }}</strong>
        <span>个可用模板</span>
      </div>
    </section>

    <section class="marketControls" aria-label="模板筛选">
      <el-input
        v-model="keyword"
        class="searchInput"
        placeholder="搜索模板名称"
        clearable
        :prefix-icon="Search"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-button type="primary" :loading="loading" @click="handleSearch">搜索模板</el-button>
    </section>

    <section class="categorySection" aria-labelledby="template-category-title">
      <div class="sectionHeading">
        <h2 id="template-category-title">按场景浏览</h2>
        <span v-if="categoryError" role="status">分类加载失败，仍可浏览全部模板</span>
      </div>
      <div class="categoryScroller" role="group" aria-label="模板分类">
        <button
          type="button"
          class="categoryChip"
          :class="{ active: selectedCategory === null }"
          :aria-pressed="selectedCategory === null"
          @click="handleCategoryChange(null)"
        >
          全部模板
        </button>
        <button
          v-for="category in categories"
          :key="category.id"
          type="button"
          class="categoryChip"
          :class="{ active: selectedCategory === category.id }"
          :aria-pressed="selectedCategory === category.id"
          @click="handleCategoryChange(category.id)"
        >
          {{ category.name }}
        </button>
        <button v-if="categoryError" type="button" class="categoryRetry" @click="loadCategories">
          重新加载分类
        </button>
      </div>
    </section>

    <section class="resultSection" aria-labelledby="template-result-title">
      <div class="resultHeading">
        <div>
          <h2 id="template-result-title">{{ resultTitle }}</h2>
          <p v-if="!loading && !listError">{{ resultDescription }}</p>
        </div>
        <span v-if="!loading && !listError" class="resultCount">共 {{ total }} 个</span>
      </div>

      <div v-if="loading" class="templateGrid" aria-label="正在加载模板">
        <div v-for="index in 8" :key="index" class="templateSkeleton">
          <el-skeleton animated>
            <template #template>
              <el-skeleton-item variant="image" class="skeletonCover" />
              <div class="skeletonBody">
                <el-skeleton-item variant="h3" style="width: 55%" />
                <el-skeleton-item variant="text" />
                <el-skeleton-item variant="text" style="width: 72%" />
              </div>
            </template>
          </el-skeleton>
        </div>
      </div>

      <el-result
        v-else-if="listError"
        class="resultState"
        icon="error"
        title="模板加载失败"
        :sub-title="listError"
      >
        <template #extra>
          <el-button type="primary" @click="loadTemplates">重新加载</el-button>
        </template>
      </el-result>

      <el-empty
        v-else-if="templateList.length === 0"
        class="resultState"
        :description="emptyDescription"
      >
        <el-button v-if="hasActiveFilter" type="primary" @click="resetFilters">查看全部模板</el-button>
      </el-empty>

      <div v-else class="templateGrid">
        <article v-for="item in templateList" :key="item.id" class="templateCard">
          <button
            type="button"
            class="cardCover"
            :aria-label="`预览模板：${item.name}`"
            @click="openPreview(item)"
          >
            <img
              v-if="getCover(item)"
              :src="getCover(item)"
              :alt="`${item.name} 模板封面`"
              loading="lazy"
              @error="markCoverFailed(item.id)"
            />
            <span v-else class="defaultCover" aria-hidden="true">
              <span class="coverOrb coverOrbOne"></span>
              <span class="coverOrb coverOrbTwo"></span>
              <el-icon :size="42"><Share /></el-icon>
            </span>
            <span class="previewHint">预览完整脑图</span>
          </button>

          <div class="cardBody">
            <div class="cardMeta">
              <span>{{ getTemplateCategoryName(categories, item.templateCategoryId) }}</span>
              <span>{{ item.layout || '逻辑结构' }}</span>
            </div>
            <h3 :title="item.name">{{ item.name }}</h3>
            <p :title="item.description || ''">{{ item.description || '一个可以立即使用和继续编辑的脑图模板。' }}</p>
            <div class="cardActions">
              <el-button :disabled="Boolean(usingTemplateId)" @click="openPreview(item)">预览</el-button>
              <el-button
                type="primary"
                :loading="usingTemplateId === item.id"
                :disabled="Boolean(usingTemplateId) && usingTemplateId !== item.id"
                @click="handleUseTemplate(item)"
              >
                使用模板
              </el-button>
            </div>
          </div>
        </article>
      </div>

      <el-pagination
        v-if="total > pageSize && !listError"
        v-model:current-page="pageNum"
        class="paginationWrap"
        background
        layout="prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :disabled="loading || Boolean(usingTemplateId)"
        @current-change="loadTemplates"
      />
    </section>

    <TemplatePreviewDialog
      v-model="previewVisible"
      :template-id="previewTemplateId"
      :using="Boolean(usingTemplateId)"
      @use="handleUseTemplate"
    />
  </main>
</template>

<script setup name="TemplateMarket">
import { computed, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { Search, Share } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import TemplatePreviewDialog from '@/components/MindMap/TemplatePreviewDialog.vue'
import { getTemplateCategories, listTemplates, useTemplate } from '@/api/mindmap/template'
import { createLatestRequestTracker, isElementDialogDismissal } from '@/utils/mindmap-async'
import {
  getMindmapTemplateErrorMessage,
  getSafeTemplateCoverUrl,
  getTemplateCategoryName,
} from '@/utils/mindmap-template'
import {
  createMindmapCreationAttemptTracker,
  resolveCreatedMindmapNavigation,
} from '@/utils/mindmap-creation'

const router = useRouter()
const loading = ref(false)
const listError = ref('')
const categoryError = ref(false)
const templateList = ref([])
const categories = ref([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = 20
const keyword = ref('')
const selectedCategory = ref(null)
const previewVisible = ref(false)
const previewTemplateId = ref(null)
const usingTemplateId = ref(null)
const failedCoverIds = ref(new Set())
const listRequestTracker = createLatestRequestTracker()
const categoryRequestTracker = createLatestRequestTracker()
const creationRequestTracker = createMindmapCreationAttemptTracker({
  storageKey: 'mindmap:template-creation-attempt:v1',
})

const hasActiveFilter = computed(() => Boolean(keyword.value.trim()) || selectedCategory.value !== null)
const resultTitle = computed(() => {
  const categoryName = selectedCategory.value === null
    ? ''
    : getTemplateCategoryName(categories.value, selectedCategory.value)
  return categoryName && categoryName !== '未分类' ? categoryName : '全部模板'
})
const resultDescription = computed(() => {
  if (keyword.value.trim()) return `“${keyword.value.trim()}”的搜索结果`
  return selectedCategory.value === null ? '挑选适合当前任务的起点' : '当前分类下的可用模板'
})
const emptyDescription = computed(() => hasActiveFilter.value
  ? '没有找到符合当前条件的模板'
  : '模板库正在建设中，请稍后再来看看')

onMounted(() => {
  loadCategories()
  loadTemplates()
})

function invalidateTemplateSessions() {
  listRequestTracker.invalidate()
  categoryRequestTracker.invalidate()
  creationRequestTracker.invalidate()
  usingTemplateId.value = null
}

onBeforeUnmount(invalidateTemplateSessions)
onDeactivated(invalidateTemplateSessions)

async function loadCategories() {
  const requestId = categoryRequestTracker.begin()
  categoryError.value = false
  try {
    const response = await getTemplateCategories()
    if (!categoryRequestTracker.isCurrent(requestId)) return
    categories.value = Array.isArray(response?.data) ? response.data : []
  } catch {
    if (!categoryRequestTracker.isCurrent(requestId)) return
    categoryError.value = true
  }
}

async function loadTemplates() {
  const requestId = listRequestTracker.begin()
  const requestedPage = pageNum.value
  const requestedKeyword = keyword.value.trim()
  const requestedCategory = selectedCategory.value
  loading.value = true
  listError.value = ''
  try {
    const response = await listTemplates({
      categoryId: requestedCategory ?? undefined,
      keyword: requestedKeyword || undefined,
      pageNum: requestedPage,
      pageSize,
    })
    if (!listRequestTracker.isCurrent(requestId)) return
    const rows = Array.isArray(response?.rows) ? response.rows : []
    const responseTotal = Math.max(0, Number(response?.total) || 0)
    const maxPage = Math.max(1, Math.ceil(responseTotal / pageSize))
    if (requestedPage > maxPage) {
      pageNum.value = maxPage
      loadTemplates()
      return
    }
    templateList.value = rows
    total.value = responseTotal
    failedCoverIds.value = new Set()
  } catch (error) {
    if (!listRequestTracker.isCurrent(requestId)) return
    templateList.value = []
    total.value = 0
    listError.value = getMindmapTemplateErrorMessage(error, '无法加载模板列表，请检查网络后重试')
  } finally {
    if (listRequestTracker.isCurrent(requestId)) loading.value = false
  }
}

function handleSearch() {
  keyword.value = keyword.value.trim()
  pageNum.value = 1
  loadTemplates()
}

function handleCategoryChange(categoryId) {
  if (selectedCategory.value === categoryId) return
  selectedCategory.value = categoryId
  pageNum.value = 1
  loadTemplates()
}

function resetFilters() {
  keyword.value = ''
  selectedCategory.value = null
  pageNum.value = 1
  loadTemplates()
}

function openPreview(item) {
  if (usingTemplateId.value) return
  previewTemplateId.value = item.id
  previewVisible.value = true
}

async function handleUseTemplate(item) {
  if (!item?.id || usingTemplateId.value) return
  try {
    await ElMessageBox.confirm(
      `将以“${item.name}”创建一份独立脑图，模板本身不会被修改。`,
      '使用模板',
      {
        type: 'info',
        confirmButtonText: '创建并编辑',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
  } catch (reason) {
    if (isElementDialogDismissal(reason)) return
    ElMessage.error(getMindmapTemplateErrorMessage(reason, '无法打开模板确认，请稍后重试'))
    return
  }

  usingTemplateId.value = item.id
  const creationRequestId = creationRequestTracker.begin(`template:${item.id}`)
  let response
  try {
    response = await useTemplate(item.id, creationRequestId.idempotencyKey)
  } catch (error) {
    if (!creationRequestTracker.isCurrent(creationRequestId)) return
    ElMessage.error(getMindmapTemplateErrorMessage(error, '使用模板失败，请稍后重试'))
    usingTemplateId.value = null
    return
  }
  creationRequestTracker.complete(creationRequestId)

  const navigation = await resolveCreatedMindmapNavigation({
    response,
    navigate: mindmapId => router.push({ path: '/mindmap/edit', query: { id: mindmapId } }),
    isCurrent: () => creationRequestTracker.isCurrent(creationRequestId),
  })
  if (navigation.reason === 'session-stale') return
  previewVisible.value = false
  if (navigation.opened) {
    ElMessage.success('已从模板创建脑图')
  } else if (navigation.reason === 'missing-id') {
    ElMessage.warning(navigation.error?.message || '脑图已创建，请返回我的脑图刷新后继续编辑')
  } else {
    ElMessage.warning('脑图已创建，但未能自动打开，请前往“我的脑图”继续编辑')
  }
  usingTemplateId.value = null
}

function getCover(item) {
  if (failedCoverIds.value.has(item.id)) return ''
  return getSafeTemplateCoverUrl(item.coverImage)
}

function markCoverFailed(id) {
  const next = new Set(failedCoverIds.value)
  next.add(id)
  failedCoverIds.value = next
}
</script>

<style lang="scss" scoped>
.templateMarketPage {
  min-height: calc(100vh - 84px);
  padding: 24px clamp(18px, 3vw, 42px) 44px;
  background:
    radial-gradient(circle at 4% -8%, rgba(59, 130, 246, 0.11), transparent 28%),
    radial-gradient(circle at 96% 8%, rgba(99, 102, 241, 0.08), transparent 24%),
    #f7f9fc;
  color: #182230;
}

.marketHero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  max-width: 1440px;
  margin: 0 auto 22px;
  padding: 30px 34px;
  overflow: hidden;
  border: 1px solid rgba(208, 218, 232, 0.85);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 18px 48px rgba(31, 45, 70, 0.08);
  backdrop-filter: blur(18px);

  .eyebrow {
    color: #3975e9;
    font-size: 11px;
    font-weight: 750;
    letter-spacing: 0.14em;
  }

  h1 {
    margin: 8px 0 9px;
    font-size: clamp(27px, 3vw, 42px);
    font-weight: 720;
    letter-spacing: -0.035em;
  }

  p {
    margin: 0;
    color: #667085;
    font-size: 14px;
  }

  .heroMetric {
    flex: none;
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 13px 17px;
    border-radius: 13px;
    background: #edf4ff;
    color: #3975e9;

    strong {
      font-size: 24px;
    }

    span {
      font-size: 12px;
    }
  }
}

.marketControls,
.categorySection,
.resultSection {
  max-width: 1440px;
  margin-right: auto;
  margin-left: auto;
}

.marketControls {
  display: flex;
  gap: 10px;
  margin-bottom: 22px;

  .searchInput {
    width: min(420px, 70vw);
  }
}

.sectionHeading,
.resultHeading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;

  h2 {
    margin: 0;
    font-size: 16px;
  }
}

.sectionHeading span {
  color: #c2410c;
  font-size: 12px;
}

.categoryScroller {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-bottom: 5px;
  overflow-x: auto;
  scrollbar-width: thin;
}

.categoryChip,
.categoryRetry {
  flex: none;
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid #dce3ed;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: #526075;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  transition: 0.18s ease;

  &:hover,
  &:focus-visible {
    border-color: #8bb4ff;
    color: #2563eb;
    outline: none;
  }

  &.active {
    border-color: #3975e9;
    background: #3975e9;
    color: #fff;
    box-shadow: 0 6px 16px rgba(57, 117, 233, 0.24);
  }
}

.categoryRetry {
  border-style: dashed;
  color: #c2410c;
}

.resultSection {
  margin-top: 24px;
}

.resultHeading {
  margin-bottom: 14px;

  p {
    margin: 4px 0 0;
    color: #8a94a6;
    font-size: 12px;
  }

  .resultCount {
    color: #8a94a6;
    font-size: 12px;
  }
}

.templateGrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 18px;
}

.templateCard,
.templateSkeleton {
  overflow: hidden;
  border: 1px solid rgba(216, 224, 235, 0.95);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(31, 45, 70, 0.055);
}

.templateSkeleton {
  .skeletonCover {
    width: 100%;
    height: 168px;
    border-radius: 0;
  }

  .skeletonBody {
    display: grid;
    gap: 12px;
    padding: 17px;
  }
}

.templateCard {
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;

  &:hover {
    border-color: #c3d3ee;
    box-shadow: 0 16px 38px rgba(31, 45, 70, 0.11);
    transform: translateY(-3px);
  }

  .cardCover {
    position: relative;
    display: block;
    width: 100%;
    height: 168px;
    padding: 0;
    overflow: hidden;
    border: 0;
    background: #eef3fa;
    cursor: pointer;

    img,
    .defaultCover {
      width: 100%;
      height: 100%;
    }

    img {
      display: block;
      object-fit: cover;
      transition: transform 0.3s ease;
    }

    &:hover img,
    &:focus-visible img {
      transform: scale(1.035);
    }

    &:focus-visible {
      outline: 3px solid rgba(59, 130, 246, 0.45);
      outline-offset: -3px;
    }

    .defaultCover {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #4d7ed8;
      background: linear-gradient(140deg, #eef5ff, #f6f1ff);
    }

    .coverOrb {
      position: absolute;
      border-radius: 50%;
      filter: blur(1px);
    }

    .coverOrbOne {
      top: -28px;
      left: -18px;
      width: 110px;
      height: 110px;
      background: rgba(96, 165, 250, 0.2);
    }

    .coverOrbTwo {
      right: -22px;
      bottom: -40px;
      width: 140px;
      height: 140px;
      background: rgba(167, 139, 250, 0.18);
    }

    .previewHint {
      position: absolute;
      right: 10px;
      bottom: 10px;
      padding: 6px 9px;
      border-radius: 8px;
      background: rgba(20, 30, 48, 0.76);
      color: #fff;
      font-size: 11px;
      opacity: 0;
      transform: translateY(3px);
      transition: 0.18s ease;
    }

    &:hover .previewHint,
    &:focus-visible .previewHint {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .cardBody {
    padding: 16px;
  }

  .cardMeta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    color: #8a94a6;
    font-size: 11px;
  }

  h3 {
    margin: 9px 0 6px;
    overflow: hidden;
    color: #202a3b;
    font-size: 16px;
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  p {
    display: -webkit-box;
    min-height: 40px;
    margin: 0;
    overflow: hidden;
    color: #7a8496;
    font-size: 12px;
    line-height: 1.65;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .cardActions {
    display: flex;
    justify-content: flex-end;
    margin-top: 14px;
  }
}

.resultState {
  min-height: 320px;
  border: 1px dashed #d7e0ed;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
}

.paginationWrap {
  justify-content: center;
  margin-top: 28px;
}

@media (max-width: 720px) {
  .templateMarketPage {
    padding: 14px 12px 32px;
  }

  .marketHero {
    align-items: flex-start;
    flex-direction: column;
    margin-bottom: 14px;
    padding: 22px 20px;
  }

  .marketControls {
    .searchInput {
      flex: 1;
      width: auto;
    }
  }

  .templateGrid {
    grid-template-columns: 1fr;
  }
}
</style>
