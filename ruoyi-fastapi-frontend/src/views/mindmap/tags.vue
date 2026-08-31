<template>
  <div class="app-container tagManagementPage">
    <div class="managementCard">
      <div class="tagWorkspace">
        <aside class="tagGroupPanel" aria-label="标签分组管理">
          <div class="tagGroupPanelHeader">
            <span>标签分组</span>
            <el-tooltip v-if="canAddCategory" content="新建标签分组" placement="top">
              <el-button
                class="tagGroupAddButton"
                type="primary"
                :icon="Plus"
                size="small"
                plain
                aria-label="新建标签分组"
                :disabled="categoryLoading || Boolean(categoryReordering)"
                @click="openCreateCategory"
              />
            </el-tooltip>
          </div>
          <div v-if="categoryError" class="groupLoadError" role="alert">
            <span>分组加载失败</span>
            <el-button link type="primary" @click="loadCategories">重试</el-button>
          </div>
          <nav v-loading="categoryLoading" class="tagGroupNav" aria-label="标签分组">
            <button
              type="button"
              class="tagGroupNavItem"
              :class="{ active: query.categoryId === null }"
              :aria-current="query.categoryId === null ? 'page' : undefined"
              @click="selectCategory(null)"
            >
              <span>全部标签</span>
            </button>
            <div v-if="globalCategoryRows.length && personalCategoryRows.length" class="tagGroupScopeLabel">全局分组</div>
            <Draggable
              v-model="globalCategoryRows"
              item-key="id"
              tag="div"
              class="tagGroupSortableList"
              handle=".tagGroupDragHandle"
              :animation="180"
              :disabled="!canReorderCategoryScope('global') || Boolean(categoryReordering)"
              ghost-class="tagGroupDragGhost"
              chosen-class="tagGroupDragChosen"
              @start="captureCategoryOrder('global')"
              @end="finishCategoryReorder('global')"
            >
              <template #item="{ element: category }">
                <div
                  class="tagGroupSortableRow"
                  :class="{ active: Number(query.categoryId) === Number(category.id) }"
                >
                  <button
                    v-if="canEditCategoryRow(category)"
                    type="button"
                    class="tagGroupDragHandle"
                    :disabled="!canReorderCategoryScope('global') || Boolean(categoryReordering)"
                    :aria-label="`拖拽调整${category.name}的顺序`"
                    title="按住拖拽排序"
                  >
                    <el-icon><Rank /></el-icon>
                  </button>
                  <button
                    type="button"
                    class="tagGroupSelectButton"
                    :aria-current="Number(query.categoryId) === Number(category.id) ? 'page' : undefined"
                    @click="selectCategory(category.id)"
                  >
                    <span class="tagGroupNavName" :title="category.name">{{ category.name }}</span>
                    <span class="tagGroupNavCount">{{ category.tagCount || 0 }}</span>
                  </button>
                  <div v-if="canEditCategoryRow(category) || canRemoveCategoryRow(category)" class="tagGroupRowActions">
                    <el-tooltip v-if="canEditCategoryRow(category)" content="编辑分组" placement="top">
                      <button
                        type="button"
                        class="tagGroupActionButton"
                        :aria-label="`编辑分组 ${category.name}`"
                        :disabled="Boolean(categoryReordering)"
                        @click.stop="openEditCategory(category)"
                      >
                        <el-icon><EditPen /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip
                      v-if="canRemoveCategoryRow(category)"
                      :content="Number(category.tagCount) > 0 ? '请先移动或删除分组内的标签' : '删除分组'"
                      placement="top"
                    >
                      <span class="tagGroupActionTooltip">
                        <button
                          type="button"
                          class="tagGroupActionButton is-danger"
                          :aria-label="`删除分组 ${category.name}`"
                          :disabled="Number(category.tagCount) > 0 || Boolean(categoryReordering)"
                          @click.stop="removeCategory(category)"
                        >
                          <el-icon><Delete /></el-icon>
                        </button>
                      </span>
                    </el-tooltip>
                  </div>
                </div>
              </template>
            </Draggable>
            <div v-if="globalCategoryRows.length && personalCategoryRows.length" class="tagGroupScopeLabel">我的分组</div>
            <Draggable
              v-model="personalCategoryRows"
              item-key="id"
              tag="div"
              class="tagGroupSortableList"
              handle=".tagGroupDragHandle"
              :animation="180"
              :disabled="!canReorderCategoryScope('mine') || Boolean(categoryReordering)"
              ghost-class="tagGroupDragGhost"
              chosen-class="tagGroupDragChosen"
              @start="captureCategoryOrder('mine')"
              @end="finishCategoryReorder('mine')"
            >
              <template #item="{ element: category }">
                <div
                  class="tagGroupSortableRow"
                  :class="{ active: Number(query.categoryId) === Number(category.id) }"
                >
                  <button
                    v-if="canEditCategoryRow(category)"
                    type="button"
                    class="tagGroupDragHandle"
                    :disabled="!canReorderCategoryScope('mine') || Boolean(categoryReordering)"
                    :aria-label="`拖拽调整${category.name}的顺序`"
                    title="按住拖拽排序"
                  >
                    <el-icon><Rank /></el-icon>
                  </button>
                  <button
                    type="button"
                    class="tagGroupSelectButton"
                    :aria-current="Number(query.categoryId) === Number(category.id) ? 'page' : undefined"
                    @click="selectCategory(category.id)"
                  >
                    <span class="tagGroupNavName" :title="category.name">{{ category.name }}</span>
                    <span class="tagGroupNavCount">{{ category.tagCount || 0 }}</span>
                  </button>
                  <div v-if="canEditCategoryRow(category) || canRemoveCategoryRow(category)" class="tagGroupRowActions">
                    <el-tooltip v-if="canEditCategoryRow(category)" content="编辑分组" placement="top">
                      <button
                        type="button"
                        class="tagGroupActionButton"
                        :aria-label="`编辑分组 ${category.name}`"
                        :disabled="Boolean(categoryReordering)"
                        @click.stop="openEditCategory(category)"
                      >
                        <el-icon><EditPen /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip
                      v-if="canRemoveCategoryRow(category)"
                      :content="Number(category.tagCount) > 0 ? '请先移动或删除分组内的标签' : '删除分组'"
                      placement="top"
                    >
                      <span class="tagGroupActionTooltip">
                        <button
                          type="button"
                          class="tagGroupActionButton is-danger"
                          :aria-label="`删除分组 ${category.name}`"
                          :disabled="Number(category.tagCount) > 0 || Boolean(categoryReordering)"
                          @click.stop="removeCategory(category)"
                        >
                          <el-icon><Delete /></el-icon>
                        </button>
                      </span>
                    </el-tooltip>
                  </div>
                </div>
              </template>
            </Draggable>
            <button
              type="button"
              class="tagGroupNavItem"
              :class="{ active: query.categoryId === 0 }"
              :aria-current="query.categoryId === 0 ? 'page' : undefined"
              @click="selectCategory(0)"
            >
              <span>未分组</span>
            </button>
          </nav>
        </aside>

        <section class="tagListPanel" :aria-label="`${currentCategoryTitle}标签管理`">
          <div class="tagListHeader">
            <div>
              <h3>{{ currentCategoryTitle }}</h3>
              <p>当前视图共 {{ total }} 个符合条件的标签</p>
            </div>
            <div class="headerActions">
              <el-button v-if="canAddTag" type="primary" @click="openCreateTag">新建标签</el-button>
              <el-button :loading="loading" @click="loadTags">刷新</el-button>
            </div>
          </div>

          <div class="filterBar" role="search" aria-label="标签筛选">
            <el-input
              v-model="query.keyword"
              clearable
              class="keywordInput"
              placeholder="搜索名称、Key 或描述"
              :prefix-icon="Search"
              :maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH"
              @keyup.enter="search"
              @clear="search"
            />
            <el-select v-model="query.ownerScope" class="filterSelect" @change="search">
              <el-option label="全部范围" value="all" />
              <el-option label="我的标签" value="mine" />
              <el-option label="全局标签" value="global" />
            </el-select>
            <el-select v-model="query.status" clearable class="filterSelect" placeholder="全部状态" @change="search">
              <el-option label="启用" :value="0" />
              <el-option label="停用" :value="1" />
              <el-option label="归档" :value="2" />
            </el-select>
            <el-button type="primary" @click="search">查询</el-button>
            <el-button @click="resetSearch">重置</el-button>
          </div>

          <div v-if="loadError" class="loadError" role="alert">
            <span>{{ loadError }}</span>
            <el-button link type="primary" @click="loadTags">重新加载</el-button>
          </div>

          <div v-if="selection.length" class="batchBar" role="status" aria-live="polite">
            <span>已选择 {{ selection.length }} 个标签，预计影响 {{ selectedNodeCount }} 个节点</span>
            <div>
              <el-button
                size="small"
                type="danger"
                plain
                :loading="operationKey === 'archive:batch'"
                :disabled="Boolean(operationKey)"
                @click="archiveSelected"
              >批量解绑并归档</el-button>
              <el-button size="small" :disabled="Boolean(operationKey)" @click="clearSelection">取消选择</el-button>
            </div>
          </div>

          <el-table
            ref="tableRef"
            v-loading="loading"
            :data="tags"
            row-key="id"
            :empty-text="loadError ? '标签列表加载失败' : '当前分组暂无符合条件的标签'"
            @selection-change="handleSelectionChange"
          >
            <el-table-column type="selection" width="46" fixed="left" :selectable="canSelectTag" />
            <el-table-column label="标签" min-width="210" fixed="left">
              <template #default="{ row }">
                <div class="tagCell">
                  <span class="tagPreview" :style="tagStyle(row)">
                    <span
                      v-if="getMindmapMarkerTagIconKey(row)"
                      class="tagMarkerIcon"
                      aria-hidden="true"
                      v-html="getMindmapMarkerIconMarkup(getMindmapMarkerTagIconKey(row))"
                    />
                    <span>{{ row.name }}</span>
                  </span>
                  <span v-if="row.description" class="tagDescription" :title="row.description">{{ row.description }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="Key" prop="tagKey" min-width="150" show-overflow-tooltip />
            <el-table-column v-if="query.categoryId === null" label="分组" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ categoryName(row.categoryId) }}</template>
            </el-table-column>
            <el-table-column label="范围" width="80" align="center">
              <template #default="{ row }">{{ Number(row.ownerId) === 0 ? '全局' : '私有' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="使用节点" prop="usageNodeCount" width="90" align="center" />
            <el-table-column label="使用文件" prop="usageFileCount" width="90" align="center" />
            <el-table-column label="最近修改" min-width="160">
              <template #default="{ row }">{{ formatDateTime(row.updatedTime || row.createdTime) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="176" align="right" fixed="right">
              <template #default="{ row }">
                <div class="tagActionCell">
                  <el-button link type="primary" :disabled="Boolean(operationKey)" @click="showImpact(row)">影响</el-button>
                  <el-dropdown
                    v-if="row.status !== 2 && (canEditManagedTag(row) || canArchiveManagedTag(row))"
                    trigger="click"
                    :disabled="Boolean(operationKey)"
                    @command="command => handleCommand(command, row)"
                  >
                    <el-button link type="primary">管理</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item v-if="canEditManagedTag(row)" command="edit">编辑定义</el-dropdown-item>
                        <el-dropdown-item v-if="row.status === 0 && canEditManagedTag(row)" command="disable">停用标签</el-dropdown-item>
                        <el-dropdown-item v-if="canEditManagedTag(row)" command="replace">替换引用</el-dropdown-item>
                        <el-dropdown-item v-if="canArchiveManagedTag(row)" command="archive" divided>解绑并归档</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="total" class="pager">
            <el-pagination
              v-model:current-page="query.pageNum"
              v-model:page-size="query.pageSize"
              layout="total, sizes, prev, pager, next"
              :page-sizes="[10, 20, 50, 100]"
              :total="total"
              @current-change="loadTags"
              @size-change="changePageSize"
            />
          </div>
        </section>
      </div>
    </div>

    <el-dialog
      v-model="editDialog.visible"
      :title="editDialog.id ? '编辑标签' : '新建标签'"
      class="tagDefinitionDialog"
      width="min(560px, calc(100vw - 32px))"
      destroy-on-close
    >
      <el-form label-width="88px">
        <el-form-item label="名称"><el-input v-model="editDialog.name" :maxlength="MAX_MINDMAP_TAG_NAME_LENGTH" show-word-limit /></el-form-item>
        <el-form-item label="Key"><el-input v-model="editDialog.tagKey" :maxlength="MAX_MINDMAP_TAG_KEY_LENGTH" :disabled="isEditingBuiltinMarker || (Boolean(editDialog.id) && !isAdmin)" /></el-form-item>
        <el-form-item v-if="isAdmin" label="范围">
          <el-radio-group v-model="editDialog.ownerScope" :disabled="isEditingBuiltinMarker">
            <el-radio value="mine">私有</el-radio>
            <el-radio value="global">全局</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="分组">
          <el-select v-model="editDialog.categoryId" clearable filterable placeholder="未分组" style="width: 100%">
            <el-option v-for="category in editableCategories" :key="category.id" :label="category.name" :value="category.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editDialog.id" label="状态">
          <el-radio-group v-model="editDialog.status">
            <el-radio :value="0">启用</el-radio>
            <el-radio :value="1">停用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="editDialog.description" type="textarea" :rows="2" :maxlength="MAX_MINDMAP_TAG_DESCRIPTION_LENGTH" show-word-limit />
        </el-form-item>
        <section class="tagStyleSection" aria-labelledby="tagStyleSectionTitle">
          <div class="tagStyleSectionHeader">
            <span id="tagStyleSectionTitle">标签样式</span>
            <span>调整节点中标签的展示效果</span>
          </div>
          <el-form-item label="节点标记" label-width="68px">
            <el-select v-model="editDialog.iconKey" clearable filterable placeholder="普通文字标签" style="width: 100%" :disabled="isEditingBuiltinMarker">
              <el-option-group v-for="group in MINDMAP_MARKER_GROUPS" :key="group.type" :label="group.label">
                <el-option v-for="option in group.options" :key="option.iconKey" :label="option.label" :value="option.iconKey">
                  <span class="markerOption">
                    <span class="tagMarkerIcon" aria-hidden="true" v-html="option.markup" />
                    <span>{{ option.label }}</span>
                  </span>
                </el-option>
              </el-option-group>
            </el-select>
          </el-form-item>
          <div class="tagStyleColorGrid">
            <el-form-item label="背景色" label-width="56px">
              <el-color-picker v-model="editDialog.fill" show-alpha />
            </el-form-item>
            <el-form-item label="文字色" label-width="56px">
              <el-color-picker v-model="editDialog.color" show-alpha />
            </el-form-item>
          </div>
          <div class="tagStyleNumberGrid">
            <el-form-item label="字号" label-width="56px">
              <el-input-number class="tagStyleNumber" v-model="editDialog.fontSize" :min="10" :max="24" controls-position="right" />
            </el-form-item>
            <el-form-item label="圆角" label-width="56px">
              <el-input-number class="tagStyleNumber" v-model="editDialog.radius" :min="0" :max="20" controls-position="right" />
            </el-form-item>
            <el-form-item label="内边距" label-width="56px">
              <el-input-number class="tagStyleNumber" v-model="editDialog.paddingX" :min="0" :max="30" controls-position="right" />
            </el-form-item>
          </div>
          <div class="tagStyleLayoutGrid">
            <el-form-item label="位置" label-width="56px">
              <el-select v-model="editDialog.placement" style="width: 100%">
                <el-option label="右侧" value="right" />
                <el-option label="左侧" value="left" />
                <el-option label="顶部" value="top" />
                <el-option label="底部" value="bottom" />
              </el-select>
            </el-form-item>
            <el-form-item label="对齐" label-width="56px">
              <el-select v-model="editDialog.align" style="width: 100%">
                <el-option
                  v-for="option in tagAlignOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </el-form-item>
          </div>
        </section>
      </el-form>
      <template #footer>
        <el-button @click="editDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="saveTag">{{ editDialog.id ? '保存并全局生效' : '创建标签' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="replaceDialog.visible" title="替换标签" width="520px" destroy-on-close>
      <el-alert :title="`将替换 ${replaceDialog.nodeCount} 个节点中的「${replaceDialog.sourceName}」`" type="warning" :closable="false" show-icon />
      <el-form label-width="88px" class="replaceForm">
        <el-form-item label="目标标签">
          <el-select
            v-model="replaceDialog.targetTagId"
            filterable
            remote
            clearable
            :remote-method="searchReplacementTags"
            :loading="replacementLoading"
            placeholder="搜索启用标签"
            style="width: 100%"
          >
            <el-option v-for="item in replacementOptions" :key="item.id" :label="`${item.name}（${item.tagKey}）`" :value="item.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="replaceDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="replaceSubmitting" :disabled="!replaceDialog.targetTagId" @click="confirmReplacement">确认替换</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="categoryDialog.visible"
      :title="categoryForm.id ? '编辑标签分组' : '新建标签分组'"
      width="min(520px, calc(100vw - 32px))"
      destroy-on-close
    >
      <el-form class="categoryForm" label-position="top" @submit.prevent>
        <el-form-item label="分组名称" required>
          <el-input
            v-model="categoryForm.name"
            autofocus
            placeholder="请输入分组名称"
            :maxlength="MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH"
            show-word-limit
            @keyup.enter="saveCategory"
          />
        </el-form-item>
        <el-form-item v-if="!categoryForm.id && isAdmin" label="分组范围">
          <el-radio-group v-model="categoryForm.ownerScope" class="categoryChoiceGroup">
            <el-radio value="mine" border>我的分组</el-radio>
            <el-radio value="global" border>全局分组</el-radio>
          </el-radio-group>
          <p class="categoryFieldHint">全局分组对所有用户可见；我的分组仅自己可见。</p>
        </el-form-item>
        <el-form-item label="展示位置">
          <el-radio-group v-model="categoryForm.showOnHome" class="categoryChoiceGroup" aria-label="分组展示位置">
            <el-radio :value="true" border>标签首页</el-radio>
            <el-radio :value="false" border>仅更多标签</el-radio>
          </el-radio-group>
          <p class="categoryFieldHint">首页仅展示常用分组，其余分组可在“更多标签”中使用。</p>
        </el-form-item>
        <el-form-item label="选择方式">
          <el-radio-group v-model="categoryForm.selectionMode" class="categoryChoiceGroup" aria-label="分组选择方式">
            <el-radio value="single" border>单选</el-radio>
            <el-radio value="multiple" border>多选</el-radio>
          </el-radio-group>
          <p class="categoryFieldHint">单选时，同一节点在该分组中只能保留一个标签。</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeCategoryDialog">取消</el-button>
        <el-button type="primary" :loading="categorySubmitting" @click="saveCategory">
          {{ categoryForm.id ? '保存修改' : '创建分组' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="TagManagement">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Delete, EditPen, Plus, Rank, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Draggable from 'vuedraggable'
import {
  addTag,
  addTagCategory,
  deleteTagCategory,
  deleteTags,
  disableTag,
  getTagImpact,
  listTagCategories,
  listTags,
  replaceTag,
  reorderTagCategories,
  updateTag,
  updateTagCategory,
} from '@/api/mindmap/tag'
import useUserStore from '@/store/modules/user'
import { createLatestRequestTracker, isElementDialogDismissal } from '@/utils/mindmap-async'
import {
  getMindmapMarkerIconMarkup,
  getMindmapMarkerTagIconKey,
  MINDMAP_MARKER_GROUPS,
  MINDMAP_MARKER_TAG_KEY_PREFIX,
} from '@/utils/mindmap-marker-tags'
import {
  isCompatibleTagReplacement,
  MAX_MINDMAP_TAG_BATCH_SIZE,
  MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
  MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
  MAX_MINDMAP_TAG_DESCRIPTION_LENGTH,
  MAX_MINDMAP_TAG_KEY_LENGTH,
  MAX_MINDMAP_TAG_NAME_LENGTH,
  MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
  validateMindmapTagCategorySortOrder,
  validateMindmapTagDescription,
  validateMindmapTagDisplayName,
  validateMindmapTagIdentifier,
  validateMindmapTagSearchKeyword,
  validateMindmapTagStyle,
} from '@/utils/mindmap-tag-governance'

const userStore = useUserStore()
const isAdmin = computed(() => Number(userStore.id) === 1)
const hasPermission = permission => userStore.permissions.includes('*:*:*') || userStore.permissions.includes(permission)
const canAddTag = computed(() => hasPermission('mindmap:tag:add'))
const canEditTag = computed(() => hasPermission('mindmap:tag:edit'))
const canRemoveTag = computed(() => hasPermission('mindmap:tag:remove'))
const canAddCategory = computed(() => hasPermission('mindmap:tag:add'))
const canEditCategory = computed(() => hasPermission('mindmap:tag:edit'))
const canRemoveCategory = computed(() => hasPermission('mindmap:tag:remove'))
const canManage = ownerId => Number(ownerId) === Number(userStore.id) || (Number(ownerId) === 0 && isAdmin.value)

const tags = ref([])
const categories = ref([])
const total = ref(0)
const loading = ref(false)
const categoryLoading = ref(false)
const loadError = ref('')
const categoryError = ref('')
const tableRef = ref(null)
const selection = ref([])
const operationKey = ref('')
const tagRequests = createLatestRequestTracker()
const categoryRequests = createLatestRequestTracker()
const replacementRequests = createLatestRequestTracker()
let componentActive = true

const query = reactive({
  pageNum: 1,
  pageSize: 10,
  keyword: '',
  ownerScope: 'all',
  status: null,
  categoryId: null,
})
const editDialog = reactive({
  visible: false,
  id: null,
  name: '',
  tagKey: '',
  fill: '#409eff',
  color: '#ffffff',
  fontSize: 12,
  radius: 3,
  paddingX: 8,
  placement: 'right',
  align: 'center',
  iconKey: '',
  ownerScope: 'mine',
  categoryId: null,
  description: '',
  status: 0,
  source: null,
  impact: null,
})
const isEditingBuiltinMarker = computed(() => (
  Boolean(editDialog.id)
  && String(editDialog.source?.tagKey || '').startsWith(MINDMAP_MARKER_TAG_KEY_PREFIX)
))
const editSubmitting = ref(false)
const replaceDialog = reactive({
  visible: false,
  sourceTagId: null,
  sourceName: '',
  sourceOwnerId: null,
  targetTagId: null,
  nodeCount: 0,
})
const replacementOptions = ref([])
const replacementLoading = ref(false)
const replaceSubmitting = ref(false)
const categoryDialog = reactive({ visible: false })
const categorySubmitting = ref(false)
const categoryReordering = ref('')
const globalCategoryRows = ref([])
const personalCategoryRows = ref([])
const categoryOrderSnapshot = reactive({ global: [], mine: [] })
const categoryForm = reactive({
  id: null,
  name: '',
  sortOrder: 0,
  ownerScope: 'mine',
  categoryType: 'custom',
  showOnHome: false,
  selectionMode: 'multiple',
})

const selectedNodeCount = computed(() => selection.value.reduce((sum, row) => sum + Math.max(0, Number(row.usageNodeCount) || 0), 0))
const currentCategoryTitle = computed(() => {
  if (query.categoryId === null) return '全部标签'
  if (query.categoryId === 0) return '未分组'
  return categories.value.find(item => Number(item.id) === Number(query.categoryId))?.name || '未知分组'
})
const editableCategories = computed(() => categories.value.filter(category => (
  Number(category.ownerId) === 0
  || (editDialog.ownerScope === 'mine' && Number(category.ownerId) === Number(userStore.id))
)))
const tagAlignOptions = computed(() => (
  editDialog.placement === 'top' || editDialog.placement === 'bottom'
    ? [
        { label: '居中', value: 'center' },
        { label: '靠左', value: 'left' },
        { label: '靠右', value: 'right' },
      ]
    : [
        { label: '居中', value: 'center' },
        { label: '靠上', value: 'top' },
        { label: '靠下', value: 'bottom' },
      ]
))

function canEditManagedTag(row) {
  return canEditTag.value && canManage(row?.ownerId)
}

function canArchiveManagedTag(row) {
  return canRemoveTag.value && canManage(row?.ownerId)
}

function canSelectTag(row) {
  return row?.status !== 2 && canArchiveManagedTag(row)
}

function canEditCategoryRow(row) {
  return canEditCategory.value && canManage(row?.ownerId)
}

function canRemoveCategoryRow(row) {
  return canRemoveCategory.value && canManage(row?.ownerId)
}

function syncCategoryOrderRows(items = categories.value) {
  globalCategoryRows.value = items.filter(item => Number(item.ownerId) === 0)
  personalCategoryRows.value = items.filter(item => Number(item.ownerId) !== 0)
}

function syncCategoriesFromOrderRows() {
  categories.value = [...globalCategoryRows.value, ...personalCategoryRows.value]
}

function categoryRowsForScope(scope) {
  return scope === 'global' ? globalCategoryRows.value : personalCategoryRows.value
}

function canReorderCategoryScope(scope) {
  if (!canEditCategory.value || categoryRowsForScope(scope).length < 2) return false
  return scope === 'global' ? isAdmin.value : true
}

function captureCategoryOrder(scope) {
  categoryOrderSnapshot[scope] = categoryRowsForScope(scope).map(item => Number(item.id))
}

async function finishCategoryReorder(scope) {
  const rows = categoryRowsForScope(scope)
  const categoryIds = rows.map(item => Number(item.id))
  if (categoryIds.every((id, index) => id === categoryOrderSnapshot[scope][index])) return

  categoryReordering.value = scope
  syncCategoriesFromOrderRows()
  try {
    await reorderTagCategories(categoryIds)
    rows.forEach((row, index) => { row.sortOrder = (index + 1) * 10 })
    ElMessage.success('分组排序已更新')
  } catch (error) {
    ElMessage.error(error?.message || '分组排序失败')
    await loadCategories()
  } finally {
    categoryReordering.value = ''
  }
}

async function loadTags() {
  clearSelection()
  const keyword = validateMindmapTagSearchKeyword(query.keyword)
  if (!keyword.valid) {
    loadError.value = keyword.message
    return
  }
  const id = tagRequests.begin()
  loading.value = true
  loadError.value = ''
  try {
    const response = await listTags({ ...query, keyword: keyword.value || undefined })
    if (!componentActive || !tagRequests.isCurrent(id)) return
    tags.value = response.rows || []
    total.value = response.total || 0
  } catch (error) {
    if (componentActive && tagRequests.isCurrent(id)) loadError.value = error?.message || '标签列表加载失败'
  } finally {
    if (componentActive && tagRequests.isCurrent(id)) loading.value = false
  }
}

async function loadCategories() {
  const id = categoryRequests.begin()
  categoryLoading.value = true
  categoryError.value = ''
  try {
    const response = await listTagCategories()
    if (!componentActive || !categoryRequests.isCurrent(id)) return
    categories.value = response.data || []
    syncCategoryOrderRows(categories.value)
  } catch (error) {
    if (componentActive && categoryRequests.isCurrent(id)) categoryError.value = error?.message || '分组加载失败'
  } finally {
    if (componentActive && categoryRequests.isCurrent(id)) categoryLoading.value = false
  }
}

function search() {
  query.pageNum = 1
  void loadTags()
}

function selectCategory(categoryId) {
  if (query.categoryId === categoryId) return
  query.categoryId = categoryId
  query.pageNum = 1
  void loadTags()
}

function resetSearch() {
  const categoryId = query.categoryId
  Object.assign(query, { pageNum: 1, keyword: '', ownerScope: 'all', status: null, categoryId })
  void loadTags()
}

function changePageSize(size) {
  query.pageSize = size
  query.pageNum = 1
  void loadTags()
}

function handleSelectionChange(rows) {
  selection.value = (rows || []).filter(canSelectTag)
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selection.value = []
}

function categoryName(categoryId) {
  if (!categoryId) return '未分组'
  return categories.value.find(item => Number(item.id) === Number(categoryId))?.name || '未知分组'
}

function statusText(status) {
  return Number(status) === 0 ? '启用' : Number(status) === 1 ? '停用' : '归档'
}

function statusType(status) {
  return Number(status) === 0 ? 'success' : Number(status) === 1 ? 'warning' : 'info'
}

function tagStyle(row) {
  const style = row.style || {}
  return {
    backgroundColor: style.fill === 'transparent' ? '#f5f7fa' : (style.fill || '#eef4ff'),
    color: style.color === 'transparent' ? '#303133' : (style.color || '#3157a4'),
    fontSize: `${style.fontSize || 12}px`,
    borderRadius: `${style.radius ?? 5}px`,
    padding: `3px ${style.paddingX ?? 8}px`,
  }
}

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

async function fetchImpact(row) {
  const response = await getTagImpact(row.id)
  return response.data || { fileCount: 0, nodeCount: 0, files: [] }
}

async function showImpact(row) {
  if (operationKey.value) return
  operationKey.value = `impact:${row.id}`
  try {
    const impact = await fetchImpact(row)
    const examples = (impact.files || []).slice(0, 5).map(item => item.name).join('、')
    await ElMessageBox.alert(
      `当前影响 ${impact.fileCount || 0} 个脑图、${impact.nodeCount || 0} 个节点${examples ? `；示例：${examples}` : ''}。`,
      `标签「${row.name}」影响范围`,
    )
  } catch (error) {
    if (!isElementDialogDismissal(error)) ElMessage.error(error?.message || '影响范围加载失败')
  } finally {
    operationKey.value = ''
  }
}

function openCreateTag() {
  const categoryId = Number(query.categoryId) > 0 ? query.categoryId : null
  Object.assign(editDialog, {
    visible: true, id: null, name: '', tagKey: '', fill: '#409eff', color: '#ffffff',
    fontSize: 12, radius: 3, paddingX: 8, placement: 'right', align: 'center', iconKey: '',
    ownerScope: 'mine', categoryId,
    description: '', status: 0, source: null, impact: null,
  })
}

async function openEditTag(row) {
  operationKey.value = `edit:${row.id}`
  try {
    const impact = await fetchImpact(row)
    const style = row.style || {}
    Object.assign(editDialog, {
      visible: true, id: row.id, name: row.name, tagKey: row.tagKey,
      fill: style.fill || '#409eff', color: style.color || '#ffffff',
      fontSize: style.fontSize || 12, radius: style.radius ?? 3, paddingX: style.paddingX ?? 8,
      placement: style.placement || 'right', align: style.align || 'center', iconKey: style.iconKey || '',
      ownerScope: Number(row.ownerId) === 0 ? 'global' : 'mine', categoryId: row.categoryId || null,
      description: row.description || '', status: row.status ?? 0, source: row, impact,
    })
  } catch (error) {
    ElMessage.error(error?.message || '标签详情加载失败')
  } finally {
    operationKey.value = ''
  }
}

async function saveTag() {
  if (editSubmitting.value) return
  const name = validateMindmapTagDisplayName(editDialog.name)
  const tagKey = validateMindmapTagIdentifier(editDialog.tagKey)
  const description = validateMindmapTagDescription(editDialog.description)
  const style = validateMindmapTagStyle({
    fill: editDialog.fill,
    color: editDialog.color,
    fontSize: editDialog.fontSize,
    radius: editDialog.radius,
    paddingX: editDialog.paddingX,
    placement: editDialog.placement,
    align: editDialog.align,
    iconKey: editDialog.iconKey,
  })
  const invalid = [name, tagKey, description, style].find(item => !item.valid)
  if (invalid) return ElMessage.warning(invalid.message)

  editSubmitting.value = true
  try {
    if (editDialog.id) {
      const impact = editDialog.impact || {}
      await ElMessageBox.confirm(
        `保存后会影响 ${impact.fileCount || 0} 个脑图、${impact.nodeCount || 0} 个节点，是否继续？`,
        '确认全局修改',
        { type: 'warning', confirmButtonText: '保存并全局生效' },
      )
    }
    const payload = {
      tagKey: tagKey.value,
      name: name.value,
      categoryId: editDialog.categoryId,
      ownerId: editDialog.ownerScope === 'global' ? 0 : (editDialog.source?.ownerId || userStore.id),
      description: description.value || null,
      status: editDialog.status,
      style: style.value,
    }
    if (editDialog.id) await updateTag({ ...payload, id: editDialog.id })
    else await addTag(payload)
    editDialog.visible = false
    ElMessage.success(editDialog.id ? '标签定义已全局更新' : '标签创建成功')
    await Promise.all([loadTags(), loadCategories()])
  } catch (error) {
    if (!isElementDialogDismissal(error)) ElMessage.error(error?.message || '标签保存失败')
  } finally {
    editSubmitting.value = false
  }
}

async function disableManagedTag(row) {
  operationKey.value = `disable:${row.id}`
  try {
    const impact = await fetchImpact(row)
    await ElMessageBox.confirm(
      `停用后既有 ${impact.nodeCount || 0} 个节点仍会显示，但新增时不可选择。`,
      `停用「${row.name}」`,
      { type: 'warning' },
    )
    await disableTag(row.id)
    ElMessage.success('标签已停用')
    await loadTags()
  } catch (error) {
    if (!isElementDialogDismissal(error)) ElMessage.error(error?.message || '停用失败')
  } finally {
    operationKey.value = ''
  }
}

async function openReplacement(row) {
  operationKey.value = `replace:${row.id}`
  try {
    const impact = await fetchImpact(row)
    Object.assign(replaceDialog, {
      visible: true,
      sourceTagId: row.id,
      sourceName: row.name,
      sourceOwnerId: row.ownerId,
      targetTagId: null,
      nodeCount: impact.nodeCount || 0,
    })
    await searchReplacementTags('')
  } catch (error) {
    ElMessage.error(error?.message || '替换标签加载失败')
  } finally {
    operationKey.value = ''
  }
}

async function searchReplacementTags(keyword) {
  const normalized = validateMindmapTagSearchKeyword(String(keyword ?? ''))
  if (!normalized.valid) {
    replacementRequests.invalidate()
    replacementOptions.value = []
    replacementLoading.value = false
    ElMessage.warning(normalized.message)
    return
  }
  const id = replacementRequests.begin()
  replacementLoading.value = true
  try {
    const response = await listTags({ pageNum: 1, pageSize: 100, ownerScope: 'all', keyword: normalized.value || undefined })
    if (!componentActive || !replaceDialog.visible || !replacementRequests.isCurrent(id)) return
    replacementOptions.value = (response.rows || []).filter(item => isCompatibleTagReplacement({
      id: replaceDialog.sourceTagId,
      ownerId: replaceDialog.sourceOwnerId,
    }, item))
  } catch (error) {
    if (!componentActive || !replaceDialog.visible || !replacementRequests.isCurrent(id)) return
    replacementOptions.value = []
    ElMessage.error(error?.message || '目标标签加载失败，请重新搜索')
  } finally {
    if (componentActive && replacementRequests.isCurrent(id)) replacementLoading.value = false
  }
}

async function confirmReplacement() {
  if (!replaceDialog.targetTagId || replaceSubmitting.value) return
  replaceSubmitting.value = true
  try {
    await replaceTag(replaceDialog.sourceTagId, replaceDialog.targetTagId)
    replaceDialog.visible = false
    ElMessage.success('标签替换成功')
    await loadTags()
  } catch (error) {
    ElMessage.error(error?.message || '替换失败')
  } finally {
    replaceSubmitting.value = false
  }
}

async function archiveTag(row) {
  operationKey.value = `archive:${row.id}`
  try {
    const impact = await fetchImpact(row)
    await ElMessageBox.confirm(
      `将从 ${impact.nodeCount || 0} 个节点解除该标签并归档；历史版本快照不受影响。`,
      `解绑并归档「${row.name}」`,
      { type: 'error', confirmButtonText: '确认解绑并归档' },
    )
    await deleteTags(row.id, true)
    ElMessage.success('标签已解绑并归档')
    await Promise.all([loadTags(), loadCategories()])
  } catch (error) {
    if (!isElementDialogDismissal(error)) ElMessage.error(error?.message || '归档失败')
  } finally {
    operationKey.value = ''
  }
}

async function archiveSelected() {
  const rows = selection.value.filter(canSelectTag)
  const ids = [...new Set(rows.map(row => Number(row.id)).filter(Number.isSafeInteger))]
  if (!ids.length || ids.length !== selection.value.length) return ElMessage.warning('所选标签已变化，请重新选择')
  if (ids.length > MAX_MINDMAP_TAG_BATCH_SIZE) return ElMessage.warning(`单次最多处理 ${MAX_MINDMAP_TAG_BATCH_SIZE} 个标签`)
  operationKey.value = 'archive:batch'
  try {
    await ElMessageBox.confirm(
      `将从预计 ${selectedNodeCount.value} 个节点解除 ${ids.length} 个标签并归档。`,
      `批量解绑并归档 ${ids.length} 个标签`,
      { type: 'error', confirmButtonText: '确认批量归档' },
    )
    await deleteTags(ids.join(','), true)
    ElMessage.success(`已归档 ${ids.length} 个标签`)
    await Promise.all([loadTags(), loadCategories()])
  } catch (error) {
    if (!isElementDialogDismissal(error)) ElMessage.error(error?.message || '批量归档失败')
  } finally {
    operationKey.value = ''
  }
}

function handleCommand(command, row) {
  if (operationKey.value || row.status === 2) return
  if (command === 'edit' && canEditManagedTag(row)) void openEditTag(row)
  if (command === 'disable' && canEditManagedTag(row)) void disableManagedTag(row)
  if (command === 'replace' && canEditManagedTag(row)) void openReplacement(row)
  if (command === 'archive' && canArchiveManagedTag(row)) void archiveTag(row)
}

function openCreateCategory() {
  if (!canAddCategory.value || categoryReordering.value) return
  Object.assign(categoryForm, {
    id: null,
    name: '',
    sortOrder: 0,
    ownerScope: 'mine',
    categoryType: 'custom',
    showOnHome: false,
    selectionMode: 'multiple',
  })
  categoryDialog.visible = true
}

function openEditCategory(row) {
  if (!canEditCategoryRow(row) || categoryReordering.value) return
  Object.assign(categoryForm, {
    id: row.id,
    name: row.name,
    sortOrder: Number(row.sortOrder) || 0,
    ownerScope: Number(row.ownerId) === 0 ? 'global' : 'mine',
    categoryType: row.categoryType || 'custom',
    showOnHome: Boolean(row.showOnHome),
    selectionMode: row.selectionMode === 'single' ? 'single' : 'multiple',
  })
  categoryDialog.visible = true
}

function closeCategoryDialog() {
  if (categorySubmitting.value) return
  categoryDialog.visible = false
}

async function saveCategory() {
  if (categorySubmitting.value) return
  const name = validateMindmapTagDisplayName(categoryForm.name, {
    label: '分组名称',
    maxLength: MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
  })
  const targetRows = categoryRowsForScope(categoryForm.ownerScope)
  const nextSortOrder = targetRows.length
    ? Math.min(MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER, Math.max(...targetRows.map(item => Number(item.sortOrder) || 0)) + 10)
    : 10
  const sortOrder = validateMindmapTagCategorySortOrder(
    categoryForm.id ? categoryForm.sortOrder : nextSortOrder,
  )
  const invalid = [name, sortOrder].find(item => !item.valid)
  if (invalid) return ElMessage.warning(invalid.message)
  categorySubmitting.value = true
  try {
    if (categoryForm.id) {
      await updateTagCategory(
        categoryForm.id,
        name.value,
        sortOrder.value,
        categoryForm.showOnHome,
        categoryForm.selectionMode,
      )
    } else {
      await addTagCategory(
        name.value,
        sortOrder.value,
        categoryForm.ownerScope,
        categoryForm.showOnHome,
        categoryForm.selectionMode,
      )
    }
    categoryDialog.visible = false
    ElMessage.success(categoryForm.id ? '分组已更新' : '分组已创建')
    await loadCategories()
  } catch (error) {
    ElMessage.error(error?.message || '分组保存失败')
  } finally {
    categorySubmitting.value = false
  }
}

async function removeCategory(row) {
  if (!canRemoveCategoryRow(row) || Number(row?.tagCount) > 0 || categoryReordering.value) return
  try {
    await ElMessageBox.confirm(`确认删除空分组「${row.name}」？`, '删除标签分组', { type: 'warning' })
    await deleteTagCategory(row.id)
    if (Number(query.categoryId) === Number(row.id)) query.categoryId = null
    ElMessage.success('分组已删除')
    await Promise.all([loadCategories(), loadTags()])
  } catch (error) {
    if (!isElementDialogDismissal(error)) ElMessage.error(error?.message || '分组删除失败')
  }
}

watch(() => editDialog.ownerScope, () => {
  if (editDialog.categoryId && !editableCategories.value.some(item => Number(item.id) === Number(editDialog.categoryId))) {
    editDialog.categoryId = null
  }
})

watch(() => replaceDialog.visible, visible => {
  if (!visible) {
    replacementRequests.invalidate()
    replacementOptions.value = []
  }
})

watch(() => editDialog.placement, () => {
  if (!tagAlignOptions.value.some(option => option.value === editDialog.align)) {
    editDialog.align = 'center'
  }
})

onMounted(() => {
  void Promise.all([loadTags(), loadCategories()])
})

onBeforeUnmount(() => {
  componentActive = false
  tagRequests.invalidate()
  categoryRequests.invalidate()
  replacementRequests.invalidate()
})
</script>

<style scoped lang="scss">
.tagManagementPage {
  --tag-border: #e5e7eb;
  padding: 0;
  background: var(--el-bg-color);
}

.managementCard {
  min-height: calc(100vh - 84px);
  border: 0;
  border-radius: 0;
  background: var(--el-bg-color);
  overflow: hidden;
}

.filterBar,
.batchBar {
  display: flex;
  align-items: center;
}

.headerActions,
.filterBar,
.tagListHeader,
.tagGroupPanelHeader {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tagWorkspace {
  display: grid;
  grid-template-columns: clamp(240px, 20%, 280px) minmax(0, 1fr);
  min-height: calc(100vh - 84px);
}

.tagGroupPanel {
  display: flex;
  max-height: calc(100vh - 84px);
  min-width: 0;
  margin: 0;
  padding: 0;
  flex-direction: column;
  border-radius: 0;
  background: #fbfcfe;
  border-right: 1px solid var(--el-border-color-lighter);
  font-family: inherit;
  line-height: normal;
}

.tagGroupPanelHeader {
  justify-content: space-between;
  min-height: 52px;
  padding: 0 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  color: #303133;
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.5px;
}

.tagGroupAddButton {
  flex: 0 0 auto;
}

.tagGroupNav {
  display: flex;
  flex: 1;
  min-height: 120px;
  padding: 2px 8px 16px;
  flex-direction: column;
  gap: 1px;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;

  &::-webkit-scrollbar {
    width: 4px;
  }

  &::-webkit-scrollbar-thumb {
    border-radius: 4px;
    background: #d4d6d9;
  }
}

.tagGroupNavItem {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  height: 34px;
  min-height: 34px;
  padding: 0 8px 0 16px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #303133;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s;

  &:hover {
    background: #e8f0fe;
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: -2px;
  }

  &.active {
    background: #d6e4ff;
    color: #303133;
    font-weight: 500;
  }
}

.tagGroupSortableList {
  display: flex;
  min-height: 1px;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 1px;
}

.tagGroupScopeLabel {
  padding: 9px 8px 4px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1;
}

.tagGroupSortableRow {
  display: flex;
  align-items: center;
  width: 100%;
  height: 34px;
  min-height: 34px;
  padding: 0 4px;
  border-radius: 5px;
  background: transparent;
  transition: background-color 0.15s, box-shadow 0.15s;

  &:hover,
  &:focus-within {
    background: #e8f0fe;
  }

  &.active {
    background: #d6e4ff;
  }
}

.tagGroupDragHandle,
.tagGroupActionButton {
  display: inline-grid;
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  place-items: center;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #909399;
  font: inherit;
  cursor: pointer;
  transition: color 0.15s, background-color 0.15s;

  &:hover:not(:disabled) {
    background: rgb(64 158 255 / 9%);
    color: var(--el-color-primary);
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: -2px;
  }

  &:disabled {
    color: #c7c9cc;
    cursor: not-allowed;
  }
}

.tagGroupDragHandle {
  color: #a5a8ad;
  cursor: grab;

  &:active:not(:disabled) {
    cursor: grabbing;
  }
}

.tagGroupSelectButton {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  height: 100%;
  flex: 1;
  padding: 0 4px;
  border: 0;
  background: transparent;
  color: #303133;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;

  &:focus-visible {
    border-radius: 4px;
    outline: 2px solid var(--el-color-primary);
    outline-offset: -2px;
  }
}

.tagGroupSortableRow.active .tagGroupSelectButton {
  font-weight: 500;
}

.tagGroupRowActions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 1px;
  margin-left: 1px;
}

.tagGroupActionTooltip {
  display: inline-flex;
}

.tagGroupActionButton.is-danger:hover:not(:disabled) {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}

.tagGroupDragGhost {
  opacity: 0.45;
  background: #eef3ff;
}

.tagGroupDragChosen {
  z-index: 2;
  box-shadow: 0 6px 18px rgb(49 85 217 / 16%);
}

.tagGroupNavName {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tagGroupNavCount {
  min-width: 22px;
  padding: 0 6px;
  border-radius: 10px;
  background: rgb(0 0 0 / 5%);
  color: #86909c;
  font-size: 11px;
  font-weight: 400;
  line-height: 20px;
  text-align: center;
}

.groupLoadError {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 6px 8px;
  color: var(--el-color-danger);
  font-size: 12px;
}

.tagListPanel {
  min-width: 0;
  padding: 16px 20px 20px;
}

.tagListHeader {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;

  h3 {
    margin: 0;
    color: #1f2329;
    font-size: 16px;
  }

  p {
    margin: 4px 0 0;
    color: #8f959e;
    font-size: 12px;
  }
}

.filterBar {
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding: 12px;
  border-radius: 8px;
  background: #f7f8fa;
}

.keywordInput {
  width: 280px;
}

.filterSelect {
  width: 140px;
}

.loadError {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 12px;
  color: var(--el-color-danger);
  font-size: 13px;
}

.batchBar {
  justify-content: space-between;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #cdd8ff;
  border-radius: 8px;
  background: #f4f7ff;
  color: #3155d9;
}

.tagCell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
}

.tagActionCell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  width: 100%;
  min-height: 32px;
  line-height: 1;

  :deep(.el-button),
  :deep(.el-dropdown) {
    margin: 0;
    line-height: 1;
    vertical-align: middle;
  }

  :deep(.el-dropdown) {
    display: inline-flex;
    align-items: center;
  }
}

.tagPreview {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  line-height: 1.5;
}

.tagMarkerIcon {
  display: inline-flex;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  align-items: center;
  justify-content: center;

  :deep(svg),
  :deep(img) {
    display: block;
    width: 20px;
    height: 20px;
  }
}

.markerOption {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.tagDescription {
  max-width: 220px;
  overflow: hidden;
  color: #8f959e;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tagStyleSection {
  margin-top: 4px;
  padding: 12px 14px 2px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.tagStyleSectionHeader {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;

  span:first-child {
    color: var(--el-text-color-primary);
    font-size: 14px;
    font-weight: 600;
  }

  span:last-child {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

.tagStyleColorGrid,
.tagStyleNumberGrid,
.tagStyleLayoutGrid {
  display: grid;
  gap: 12px;

  :deep(.el-form-item) {
    min-width: 0;
    margin-bottom: 12px;
  }
}

.tagStyleColorGrid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.tagStyleNumberGrid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.tagStyleLayoutGrid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.tagStyleNumber {
  width: 100%;
  min-width: 0;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.replaceForm {
  margin-top: 18px;
}

.categoryForm {
  padding: 2px 2px 0;

  :deep(.el-form-item) {
    margin-bottom: 22px;
  }

  :deep(.el-form-item:last-child) {
    margin-bottom: 4px;
  }

  :deep(.el-form-item__label) {
    color: var(--el-text-color-primary);
    font-weight: 600;
  }
}

.categoryChoiceGroup {
  display: grid;
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;

  :deep(.el-radio.is-bordered) {
    width: 100%;
    height: 40px;
    margin: 0;
    justify-content: center;
  }
}

.categoryFieldHint {
  width: 100%;
  margin: 7px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .batchBar,
  .tagListHeader {
    align-items: stretch;
    flex-direction: column;
  }

  .tagWorkspace {
    display: block;
  }

  .tagGroupPanel {
    margin-bottom: 16px;
    max-height: 360px;
    padding: 0;
    border-right: 0;
    border-bottom: 1px solid var(--tag-border);
  }

  .tagGroupNav {
    min-height: auto;
    padding: 8px;
  }

  .tagGroupNavItem {
    width: 100%;
    max-width: none;
  }

  .tagListPanel {
    padding: 0 12px 16px;
  }

  .headerActions {
    flex-wrap: wrap;
  }

  .keywordInput,
  .filterSelect {
    width: 100%;
  }
}

@media (max-width: 520px) {
  .tagStyleSectionHeader {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }

  .tagStyleColorGrid,
  .tagStyleNumberGrid,
  .tagStyleLayoutGrid {
    grid-template-columns: minmax(0, 1fr);
  }

  .categoryChoiceGroup {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

<style lang="scss">
.el-dialog.tagDefinitionDialog {
  display: flex;
  max-height: calc(100vh - 32px);
  margin: 16px auto !important;
  flex-direction: column;
  overflow: hidden;

  .el-dialog__header,
  .el-dialog__footer {
    flex: 0 0 auto;
  }

  .el-dialog__body {
    min-height: 0;
    padding-bottom: 12px;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .el-dialog__footer {
    padding-top: 12px;
    border-top: 1px solid var(--el-border-color-lighter);
    background: var(--el-bg-color-overlay);
  }
}
</style>
