<template>
  <main class="templateAdminPage">
    <section class="adminHeader">
      <div>
        <span class="eyebrow">TEMPLATE OPERATIONS</span>
        <h1>模板运营</h1>
        <p>从已有脑图发布只读模板，维护模板分类和下架状态。</p>
      </div>
      <div class="headerActions">
        <el-button
          v-if="canPublish"
          type="success"
          plain
          icon="Folder"
          :disabled="isOperating"
          @click="showCategoryDialog = true"
        >
          管理分类
        </el-button>
        <el-button
          v-if="canPublish"
          type="primary"
          icon="Plus"
          :disabled="isOperating"
          @click="handlePublish"
        >
          发布模板
        </el-button>
      </div>
    </section>

    <el-alert
      v-if="!canPublish && !canRemove"
      class="permissionNotice"
      type="info"
      title="当前账号为模板只读权限"
      description="你可以查看和预览已发布模板；发布、分类管理与下架需要模板管理员权限。"
      show-icon
      :closable="false"
    />

    <el-alert
      v-if="listError"
      class="listError"
      type="error"
      :title="listError"
      show-icon
      :closable="false"
    >
      <template #default><el-button link type="primary" @click="loadTemplates">重新加载</el-button></template>
    </el-alert>

    <section class="tablePanel">
      <el-table v-loading="loading" :data="templateList" row-key="id" empty-text="暂无已发布模板">
        <el-table-column label="ID" prop="id" width="80" align="center" />
        <el-table-column label="模板" min-width="220">
          <template #default="{ row }">
            <div class="templateNameCell">
              <el-image
                v-if="getSafeTemplateCoverUrl(row.coverImage)"
                :src="getSafeTemplateCoverUrl(row.coverImage)"
                class="coverThumb"
                fit="cover"
              >
                <template #error><span class="coverFallback">图</span></template>
              </el-image>
              <span v-else class="coverFallback">图</span>
              <div>
                <strong :title="row.name">{{ row.name }}</strong>
                <span>{{ getTemplateCategoryName(categories, row.templateCategoryId) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="描述" prop="description" min-width="220" show-overflow-tooltip />
        <el-table-column label="布局" prop="layout" width="140" align="center" />
        <el-table-column label="创建时间" prop="createTime" width="180" align="center">
          <template #default="{ row }">{{ parseTime(row.createTime) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" icon="View" :disabled="isOperating" @click="handlePreview(row)">
              预览
            </el-button>
            <el-button
              v-if="canRemove"
              link
              type="danger"
              icon="Delete"
              :loading="operationType === `unpublish:${row.id}`"
              :disabled="isOperating && operationType !== `unpublish:${row.id}`"
              @click="handleUnpublish(row)"
            >
              下架
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <pagination
        v-show="total > 0 && !listError"
        :total="total"
        v-model:page="pageNum"
        v-model:limit="pageSize"
        @pagination="loadTemplates"
      />
    </section>

    <el-dialog
      v-model="publishDialogVisible"
      title="发布脑图模板"
      width="min(560px, 94vw)"
      :close-on-click-modal="!isPublishing"
      :close-on-press-escape="!isPublishing"
      :show-close="!isPublishing"
      @closed="publishFormRef?.clearValidate()"
    >
      <el-form ref="publishFormRef" :model="publishForm" :rules="publishRules" label-width="92px">
        <el-form-item label="源脑图" prop="mindmapId">
          <el-select
            v-model="publishForm.mindmapId"
            filterable
            allow-create
            default-first-option
            :loading="sourceLoading"
            placeholder="选择脑图，或输入有效脑图 ID"
            style="width: 100%"
          >
            <el-option
              v-for="mindmap in sourceMindmaps"
              :key="mindmap.id"
              :label="mindmap.name"
              :value="mindmap.id"
            />
          </el-select>
          <div class="fieldHint">发布时复制当前内容，后续修改源脑图不会影响模板。</div>
        </el-form-item>
        <el-form-item label="模板名称" prop="name">
          <el-input v-model="publishForm.name" maxlength="200" show-word-limit placeholder="请输入模板名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="publishForm.description"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="说明适用场景和模板内容（可选）"
          />
        </el-form-item>
        <el-form-item label="封面地址" prop="coverImage">
          <el-input v-model="publishForm.coverImage" maxlength="500" placeholder="HTTP、HTTPS 或同源相对地址（可选）" />
        </el-form-item>
        <el-form-item label="分类" prop="templateCategoryId">
          <el-select v-model="publishForm.templateCategoryId" placeholder="选择分类（可选）" clearable style="width: 100%">
            <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="isPublishing" @click="publishDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isPublishing" @click="submitPublish">发布模板</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showCategoryDialog"
      title="模板分类管理"
      width="min(520px, 94vw)"
      :close-on-click-modal="!isCategoryOperating"
      :close-on-press-escape="!isCategoryOperating"
      :show-close="!isCategoryOperating"
    >
      <div class="categoryList" aria-live="polite">
        <div v-for="category in categories" :key="category.id" class="categoryItem">
          <span>{{ category.name }}</span>
          <el-button
            link
            type="danger"
            size="small"
            :loading="operationType === `delete-category:${category.id}`"
            :disabled="isCategoryOperating && operationType !== `delete-category:${category.id}`"
            @click="handleDeleteCategory(category)"
          >
            删除
          </el-button>
        </div>
        <el-empty v-if="categories.length === 0" :image-size="72" description="暂无模板分类" />
      </div>
      <el-divider />
      <el-form class="categoryCreateForm" @submit.prevent="handleAddCategory">
        <el-form-item label="分类名称">
          <el-input
            v-model="newCategoryName"
            maxlength="100"
            placeholder="输入不重复的分类名称"
            :disabled="isCategoryOperating"
          />
        </el-form-item>
        <el-button native-type="submit" type="primary" :loading="operationType === 'add-category'">添加分类</el-button>
      </el-form>
      <p class="dialogHint">仍被模板使用的分类不能删除，请先下架或调整关联模板。</p>
    </el-dialog>

    <TemplatePreviewDialog
      v-model="previewVisible"
      :template-id="previewTemplateId"
      :allow-use="false"
    />
  </main>
</template>

<script setup name="TemplateAdmin">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import useUserStore from '@/store/modules/user'
import TemplatePreviewDialog from '@/components/MindMap/TemplatePreviewDialog.vue'
import { listMindmap } from '@/api/mindmap/mindmap'
import {
  addTemplateCategory,
  deleteTemplateCategory,
  getTemplateCategories,
  listTemplates,
  publishTemplate,
  unpublishTemplate,
} from '@/api/mindmap/template'
import { createLatestRequestTracker, isElementDialogDismissal } from '@/utils/mindmap-async'
import { validateMindmapName } from '@/utils/mindmap-file'
import {
  getMindmapTemplateErrorMessage,
  getSafeTemplateCoverUrl,
  getTemplateCategoryName,
} from '@/utils/mindmap-template'

const loading = ref(false)
const userStore = useUserStore()
const sourceLoading = ref(false)
const listError = ref('')
const templateList = ref([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const categories = ref([])
const sourceMindmaps = ref([])
const operationType = ref('')
const previewVisible = ref(false)
const previewTemplateId = ref(null)
const listRequestTracker = createLatestRequestTracker()
const categoryRequestTracker = createLatestRequestTracker()
const sourceRequestTracker = createLatestRequestTracker()

const isOperating = computed(() => Boolean(operationType.value))
const hasPermission = permission => userStore.permissions.includes('*:*:*')
  || userStore.permissions.includes(permission)
const canPublish = computed(() => hasPermission('mindmap:template:add'))
const canRemove = computed(() => hasPermission('mindmap:template:remove'))
const isPublishing = computed(() => operationType.value === 'publish')
const isCategoryOperating = computed(() => operationType.value.includes('category'))

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
  mindmapId: [{
    validator: (_rule, value, callback) => {
      const id = Number(value)
      if (!Number.isSafeInteger(id) || id <= 0) callback(new Error('请选择源脑图或输入有效脑图 ID'))
      else callback()
    },
    trigger: 'change',
  }],
  name: [{
    validator: (_rule, value, callback) => {
      const result = validateMindmapName(value)
      if (!result.valid) callback(new Error(result.message))
      else callback()
    },
    trigger: 'blur',
  }],
  coverImage: [{
    validator: (_rule, value, callback) => {
      if (!String(value || '').trim() || getSafeTemplateCoverUrl(value)) callback()
      else callback(new Error('封面地址仅支持 HTTP、HTTPS 或同源相对路径，且不能包含账号密码'))
    },
    trigger: 'blur',
  }],
}

const showCategoryDialog = ref(false)
const newCategoryName = ref('')

onMounted(() => {
  loadCategories()
  loadTemplates()
})

onBeforeUnmount(() => {
  listRequestTracker.invalidate()
  categoryRequestTracker.invalidate()
  sourceRequestTracker.invalidate()
})

async function loadCategories() {
  const requestId = categoryRequestTracker.begin()
  try {
    const response = await getTemplateCategories()
    if (!categoryRequestTracker.isCurrent(requestId)) return
    categories.value = Array.isArray(response?.data) ? response.data : []
  } catch (error) {
    if (!categoryRequestTracker.isCurrent(requestId)) return
    ElMessage.error(getMindmapTemplateErrorMessage(error, '模板分类加载失败'))
  }
}

async function loadTemplates() {
  const requestId = listRequestTracker.begin()
  const requestedPage = pageNum.value
  const requestedSize = pageSize.value
  loading.value = true
  listError.value = ''
  try {
    const response = await listTemplates({ pageNum: requestedPage, pageSize: requestedSize })
    if (!listRequestTracker.isCurrent(requestId)) return
    const responseTotal = Math.max(0, Number(response?.total) || 0)
    const maxPage = Math.max(1, Math.ceil(responseTotal / requestedSize))
    if (requestedPage > maxPage) {
      pageNum.value = maxPage
      loadTemplates()
      return
    }
    templateList.value = Array.isArray(response?.rows) ? response.rows : []
    total.value = responseTotal
  } catch (error) {
    if (!listRequestTracker.isCurrent(requestId)) return
    templateList.value = []
    total.value = 0
    listError.value = getMindmapTemplateErrorMessage(error, '模板列表加载失败，请稍后重试')
  } finally {
    if (listRequestTracker.isCurrent(requestId)) loading.value = false
  }
}

async function loadSourceMindmaps() {
  const requestId = sourceRequestTracker.begin()
  sourceLoading.value = true
  try {
    const response = await listMindmap({ pageNum: 1, pageSize: 100, isTemplate: 0 })
    if (!sourceRequestTracker.isCurrent(requestId)) return
    sourceMindmaps.value = Array.isArray(response?.rows) ? response.rows : []
  } catch (error) {
    if (!sourceRequestTracker.isCurrent(requestId)) return
    sourceMindmaps.value = []
    ElMessage.error(getMindmapTemplateErrorMessage(error, '源脑图列表加载失败，可直接输入脑图 ID'))
  } finally {
    if (sourceRequestTracker.isCurrent(requestId)) sourceLoading.value = false
  }
}

function handlePublish() {
  if (isOperating.value) return
  Object.assign(publishForm, {
    mindmapId: null,
    name: '',
    description: '',
    coverImage: '',
    templateCategoryId: null,
  })
  publishDialogVisible.value = true
  loadSourceMindmaps()
}

async function submitPublish() {
  if (isOperating.value || !publishFormRef.value) return
  operationType.value = 'publish'
  try {
    await publishFormRef.value.validate()
  } catch {
    operationType.value = ''
    return
  }

  const nameResult = validateMindmapName(publishForm.name)
  try {
    await publishTemplate({
      mindmapId: Number(publishForm.mindmapId),
      name: nameResult.value,
      description: publishForm.description.trim() || undefined,
      coverImage: publishForm.coverImage.trim() || undefined,
      templateCategoryId: publishForm.templateCategoryId || undefined,
    })
    ElMessage.success('模板发布成功')
    publishDialogVisible.value = false
    pageNum.value = 1
    await loadTemplates()
  } catch (error) {
    ElMessage.error(getMindmapTemplateErrorMessage(error, '模板发布失败'))
  } finally {
    operationType.value = ''
  }
}

async function handleUnpublish(row) {
  if (isOperating.value) return
  try {
    await ElMessageBox.confirm(
      `下架“${row.name}”后，模板市场将无法继续使用它，已创建的脑图不受影响。`,
      '下架模板',
      {
        type: 'warning',
        confirmButtonText: '确认下架',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
  } catch (reason) {
    if (isElementDialogDismissal(reason)) return
    ElMessage.error(getMindmapTemplateErrorMessage(reason, '无法打开下架确认，请稍后重试'))
    return
  }

  operationType.value = `unpublish:${row.id}`
  try {
    await unpublishTemplate(row.id)
    ElMessage.success('模板已下架')
    await loadTemplates()
  } catch (error) {
    ElMessage.error(getMindmapTemplateErrorMessage(error, '模板下架失败'))
  } finally {
    operationType.value = ''
  }
}

function handlePreview(row) {
  if (isOperating.value) return
  previewTemplateId.value = row.id
  previewVisible.value = true
}

async function handleAddCategory() {
  if (isOperating.value) return
  const name = newCategoryName.value.trim()
  if (!name) return ElMessage.warning('请输入分类名称')
  if (name.length > 100) return ElMessage.warning('分类名称不能超过 100 个字符')
  operationType.value = 'add-category'
  try {
    await addTemplateCategory(name, 0)
    ElMessage.success('分类添加成功')
    newCategoryName.value = ''
    await loadCategories()
  } catch (error) {
    ElMessage.error(getMindmapTemplateErrorMessage(error, '分类添加失败'))
  } finally {
    operationType.value = ''
  }
}

async function handleDeleteCategory(category) {
  if (isOperating.value) return
  try {
    await ElMessageBox.confirm(
      `确认删除分类“${category.name}”？仍被模板使用时系统会阻止删除。`,
      '删除模板分类',
      {
        type: 'warning',
        distinguishCancelAndClose: true,
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
  } catch (reason) {
    if (isElementDialogDismissal(reason)) return
    ElMessage.error(getMindmapTemplateErrorMessage(reason, '无法打开删除确认，请稍后重试'))
    return
  }

  operationType.value = `delete-category:${category.id}`
  try {
    await deleteTemplateCategory(category.id)
    ElMessage.success('分类已删除')
    await loadCategories()
  } catch (error) {
    ElMessage.error(getMindmapTemplateErrorMessage(error, '分类删除失败'))
  } finally {
    operationType.value = ''
  }
}
</script>

<style lang="scss" scoped>
.templateAdminPage {
  min-height: calc(100vh - 84px);
  padding: 24px;
  background: #f6f8fb;
}

.adminHeader,
.tablePanel {
  max-width: 1440px;
  margin-right: auto;
  margin-left: auto;
}

.adminHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;

  .eyebrow {
    color: #3975e9;
    font-size: 10px;
    font-weight: 750;
    letter-spacing: 0.14em;
  }

  h1 {
    margin: 4px 0;
    color: #182230;
    font-size: 26px;
  }

  p {
    margin: 0;
    color: #7a8496;
    font-size: 13px;
  }

  .headerActions {
    display: flex;
  }
}

.listError,
.permissionNotice {
  max-width: 1440px;
  margin: 0 auto 14px;
}

.tablePanel {
  padding: 16px;
  border: 1px solid #e1e7f0;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(31, 45, 70, 0.06);
}

.templateNameCell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;

  .coverThumb,
  .coverFallback {
    flex: none;
    width: 58px;
    height: 40px;
    border-radius: 7px;
  }

  .coverFallback {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(140deg, #edf4ff, #f5f0ff);
    color: #5681cf;
    font-size: 12px;
  }

  > div {
    display: flex;
    min-width: 0;
    flex-direction: column;

    strong {
      overflow: hidden;
      color: #263247;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    span {
      margin-top: 3px;
      color: #8a94a6;
      font-size: 11px;
    }
  }
}

.fieldHint,
.dialogHint {
  color: #8a94a6;
  font-size: 11px;
  line-height: 1.5;
}

.categoryList {
  max-height: 260px;
  overflow-y: auto;

  .categoryItem {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 42px;
    padding: 0 4px;
    border-bottom: 1px solid #edf0f5;
  }
}

.categoryCreateForm {
  display: flex;
  align-items: flex-start;
  gap: 10px;

  .el-form-item {
    flex: 1;
    margin-bottom: 0;
  }
}

.dialogHint {
  margin: 12px 0 0;
}

@media (max-width: 720px) {
  .templateAdminPage {
    padding: 14px 12px;
  }

  .adminHeader {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
