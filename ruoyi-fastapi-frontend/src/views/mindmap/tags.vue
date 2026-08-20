<template>
  <div class="app-container">
    <el-card shadow="never" class="governanceCard">
      <template #header>
        <div class="cardHeader">
          <div>
            <span>统一标签治理</span>
            <span class="headerHint">名称和样式修改会同步到所有引用节点</span>
          </div>
          <div>
            <el-button size="small" @click="openCategoryManager">管理分类</el-button>
            <el-button v-if="canAddTag" size="small" type="primary" @click="handleCreateManagedTag">新建标签</el-button>
            <el-button size="small" :loading="managedTagsLoading" @click="loadManagedTags">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="governanceToolbar" role="search" aria-label="标签筛选">
        <el-input
          v-model="managedTagQuery.keyword" clearable class="keywordInput"
          placeholder="搜索名称、Key 或描述" :prefix-icon="Search"
          :maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH"
          @keyup.enter="handleManagedTagSearch" @clear="handleManagedTagSearch"
        />
        <el-select v-model="managedTagQuery.ownerScope" class="filterSelect" @change="handleManagedTagSearch">
          <el-option label="全部范围" value="all" />
          <el-option label="我的标签" value="mine" />
          <el-option label="全局标签" value="global" />
        </el-select>
        <el-select v-model="managedTagQuery.status" clearable class="filterSelect" placeholder="全部状态" @change="handleManagedTagSearch">
          <el-option label="启用" :value="0" />
          <el-option label="停用" :value="1" />
          <el-option label="归档" :value="2" />
        </el-select>
        <el-select v-model="managedTagQuery.categoryId" clearable filterable class="filterSelect" placeholder="全部分类" @change="handleManagedTagSearch">
          <el-option v-for="category in tagCategories" :key="category.id" :label="category.name" :value="category.id" />
        </el-select>
        <el-select v-model="managedTagQuery.fieldId" clearable filterable class="filterSelect" placeholder="全部字段" @change="handleManagedTagSearch">
          <el-option v-for="field in fields" :key="field.id" :label="field.name" :value="field.id" />
        </el-select>
        <el-button type="primary" @click="handleManagedTagSearch">查询</el-button>
        <el-button @click="resetManagedTagSearch">重置</el-button>
      </div>
      <div v-if="managedTagsError" class="loadError" role="alert">
        <span>{{ managedTagsError }}</span>
        <el-button link type="primary" @click="loadManagedTags">重新加载</el-button>
      </div>
      <div v-if="tagCategoriesError" class="loadError" role="alert">
        <span>{{ tagCategoriesError }}，分类名称和筛选可能不完整</span>
        <el-button link type="primary" :loading="tagCategoriesLoading" @click="loadTagCategories">重新加载分类</el-button>
      </div>
      <div v-if="managedTagSelection.length" class="governanceBatchBar" role="status" aria-live="polite">
        <span>
          已选择 {{ managedTagSelection.length }} 个可管理标签，预计影响
          {{ selectedManagedTagNodeCount }} 个节点
        </span>
        <div class="governanceBatchActions">
          <el-button
            size="small" type="danger" plain
            :loading="tagOperationKey === 'archive:batch'"
            :disabled="Boolean(tagOperationKey)"
            aria-label="批量解除绑定并归档所选标签"
            @click="handleBatchArchiveTags"
          >批量解绑并归档</el-button>
          <el-button size="small" :disabled="Boolean(tagOperationKey)" @click="clearManagedTagSelection">
            取消选择
          </el-button>
        </div>
      </div>
      <el-table
        ref="managedTagTableRef"
        :data="managedTags" size="small" v-loading="managedTagsLoading"
        row-key="id" @selection-change="handleManagedTagSelectionChange"
        :empty-text="managedTagsError ? '标签列表加载失败' : '暂无符合条件的标签'"
      >
        <el-table-column type="selection" width="46" fixed="left" :selectable="canSelectManagedTag" />
        <el-table-column label="标签" min-width="180" fixed="left">
          <template #default="{ row }">
            <div class="managedTagCell">
              <span class="managedTagPreview" :style="getManagedTagStyle(row)">{{ row.name }}</span>
              <span v-if="row.description" class="managedTagDescription" :title="row.description">{{ row.description }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Key" prop="tagKey" min-width="140" show-overflow-tooltip />
        <el-table-column label="分类" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ categoryName(row.categoryId) }}</template>
        </el-table-column>
        <el-table-column label="字段" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ fieldNames(row) }}</template>
        </el-table-column>
        <el-table-column label="范围" width="80" align="center">
          <template #default="{ row }">{{ row.ownerId === 0 ? '全局' : '私有' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 0 ? 'success' : row.status === 1 ? 'warning' : 'info'">
              {{ row.status === 0 ? '启用' : row.status === 1 ? '停用' : '归档' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="使用节点" prop="usageNodeCount" width="90" align="center" />
        <el-table-column label="使用文件" prop="usageFileCount" width="90" align="center" />
        <el-table-column label="最近修改" min-width="150">
          <template #default="{ row }">
            <el-popover placement="top" trigger="hover" :width="240">
              <template #reference><span class="auditTime">{{ formatDateTime(row.updatedTime || row.createdTime) }}</span></template>
              <div class="auditDetail">
                <div>修改人：{{ row.updateBy || row.createdBy || '—' }}</div>
                <div>定义版本：{{ row.definitionRevision || 1 }}</div>
                <div>创建时间：{{ formatDateTime(row.createdTime) }}</div>
              </div>
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="right" fixed="right">
          <template #default="{ row }">
            <div class="managedTagActions">
              <el-button
                link type="primary" :loading="tagOperationKey === `impact:${row.id}`"
                :disabled="Boolean(tagOperationKey)"
                :aria-label="`查看标签 ${row.name} 的影响范围`"
                @click="showTagImpact(row)"
              >影响</el-button>
              <el-dropdown
                v-if="row.status !== 2 && (canEditManagedTag(row) || canArchiveManagedTag(row))"
                trigger="click" :disabled="Boolean(tagOperationKey)"
                @command="command => handleManagedTagCommand(command, row)"
              >
                <el-button
                  link type="primary" :disabled="Boolean(tagOperationKey)"
                  :aria-label="`管理标签 ${row.name}`"
                >管理</el-button>
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
      <div class="governancePager" v-if="managedTagTotal > 0">
        <el-pagination
          size="small" layout="total, sizes, prev, pager, next" :total="managedTagTotal"
          :page-size="managedTagQuery.pageSize" v-model:current-page="managedTagQuery.pageNum"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="loadManagedTags" @size-change="handleManagedTagPageSize"
        />
      </div>
    </el-card>

    <el-dialog v-model="replaceDialog.visible" title="替换统一标签" width="520px" destroy-on-close>
      <el-alert
        :title="`将替换 ${replaceDialog.nodeCount} 个节点中的「${replaceDialog.sourceName}」`"
        type="warning" :closable="false" show-icon style="margin-bottom: 16px"
      />
      <el-form label-width="90px">
        <el-form-item label="目标标签">
          <el-select
            v-model="replaceDialog.targetTagId" filterable remote clearable
            :remote-method="searchReplacementTags" :loading="replacementLoading"
            placeholder="输入名称或 Key 搜索启用标签" style="width: 100%"
          >
            <el-option
              v-for="item in replacementOptions" :key="item.id"
              :label="`${item.name}（${item.tagKey}）`" :value="item.id"
            />
          </el-select>
          <div v-if="replacementError" class="fieldError" role="alert">
            {{ replacementError }}
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="replaceDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="replaceSubmitting" :disabled="!replaceDialog.targetTagId" @click="confirmReplaceTag">
          确认替换
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="tagEditDialog.visible" :title="tagEditDialog.id ? '编辑统一标签' : '新建统一标签'" width="560px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="tagEditDialog.name" :maxlength="MAX_MINDMAP_TAG_NAME_LENGTH" show-word-limit /></el-form-item>
        <el-form-item label="Key"><el-input v-model="tagEditDialog.tagKey" :maxlength="MAX_MINDMAP_TAG_KEY_LENGTH" :disabled="Boolean(tagEditDialog.id) && !isAdmin" /></el-form-item>
        <el-form-item v-if="isAdmin" label="范围">
          <el-radio-group v-model="tagEditDialog.ownerScope">
            <el-radio value="mine">私有</el-radio><el-radio value="global">全局</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="tagEditDialog.categoryId" clearable filterable placeholder="未分类" style="width: 100%">
            <el-option v-for="category in editableTagCategories" :key="category.id" :label="category.name" :value="category.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="tagEditDialog.id" label="状态">
          <el-radio-group v-model="tagEditDialog.status">
            <el-radio :value="0">启用</el-radio><el-radio :value="1">停用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="tagEditDialog.description" type="textarea" :rows="2" :maxlength="MAX_MINDMAP_TAG_DESCRIPTION_LENGTH" show-word-limit placeholder="说明标签的使用场景" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="背景色"><el-color-picker v-model="tagEditDialog.fill" show-alpha /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="文字色"><el-color-picker v-model="tagEditDialog.color" show-alpha /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="字号"><el-input-number v-model="tagEditDialog.fontSize" :min="10" :max="24" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="圆角"><el-input-number v-model="tagEditDialog.radius" :min="0" :max="20" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="内边距"><el-input-number v-model="tagEditDialog.paddingX" :min="0" :max="30" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="tagEditDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="tagEditSubmitting" @click="confirmEditManagedTag">
          {{ tagEditDialog.id ? '保存并全局生效' : '创建标签' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="categoryDialog.visible" title="标签分类管理" width="min(680px, calc(100vw - 32px))"
      :close-on-click-modal="!categoryBusy" :close-on-press-escape="!categoryBusy"
      :show-close="!categoryBusy"
    >
      <el-alert
        title="分类用于整理标签，不会改变节点内容；仍有标签的分类不能删除。"
        type="info" :closable="false" show-icon class="categoryHint"
      />
      <div v-if="categoryFormVisible" class="categoryEditor" role="group" :aria-label="categoryForm.id ? '编辑标签分类' : '新建标签分类'">
        <el-input
          v-model="categoryForm.name" aria-label="分类名称" placeholder="分类名称"
          :maxlength="MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH" show-word-limit
          @keyup.enter="saveCategory"
        />
        <el-input-number
          v-model="categoryForm.sortOrder" aria-label="分类排序" :min="-MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER"
          :max="MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER" :step="1" controls-position="right"
        />
        <el-select
          v-if="!categoryForm.id && isAdmin" v-model="categoryForm.ownerScope"
          aria-label="分类范围" class="categoryScope"
        >
          <el-option label="我的分类" value="mine" />
          <el-option label="全局分类" value="global" />
        </el-select>
        <div class="categoryEditorActions">
          <el-button :disabled="categorySubmitting" @click="cancelCategoryEdit">取消</el-button>
          <el-button type="primary" :loading="categorySubmitting" @click="saveCategory">
            {{ categoryForm.id ? '保存' : '创建' }}
          </el-button>
        </div>
      </div>
      <div v-else-if="canAddCategory" class="categoryCreateAction">
        <el-button type="primary" :disabled="Boolean(categoryOperationKey)" @click="startCreateCategory">
          新建分类
        </el-button>
      </div>
      <div v-if="tagCategoriesError" class="loadError" role="alert">
        <span>{{ tagCategoriesError }}</span>
        <el-button link type="primary" :loading="tagCategoriesLoading" @click="loadTagCategories">重新加载</el-button>
      </div>
      <el-table
        :data="tagCategories" size="small" v-loading="tagCategoriesLoading"
        :empty-text="tagCategoriesError ? '分类加载失败' : '暂无分类'"
      >
        <el-table-column label="分类" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="Number(row.ownerId) === 0" size="small" type="info" effect="plain" class="categoryScopeTag">全局</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标签数" prop="tagCount" width="90" align="center" />
        <el-table-column label="排序" prop="sortOrder" width="90" align="center" />
        <el-table-column label="操作" width="130" align="right">
          <template #default="{ row }">
            <el-button
              v-if="canEditCategoryRow(row)" link type="primary"
              :disabled="Boolean(categoryOperationKey) || categorySubmitting"
              :aria-label="`编辑分类 ${row.name}`" @click="startEditCategory(row)"
            >编辑</el-button>
            <el-button
              v-if="canRemoveCategoryRow(row)" link type="danger"
              :loading="categoryOperationKey === `delete:${row.id}`"
              :disabled="Boolean(categoryOperationKey) || categorySubmitting || Number(row.tagCount) > 0"
              :aria-label="Number(row.tagCount) > 0 ? `分类 ${row.name} 仍有 ${row.tagCount} 个标签，不能删除` : `删除分类 ${row.name}`"
              @click="removeCategory(row)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button :disabled="categoryBusy" @click="categoryDialog.visible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-row :gutter="16" class="fieldWorkspace">
      <!-- 左侧：字段列表 -->
      <el-col :xs="24" :sm="8" :lg="6">
        <el-card shadow="never" v-loading="fieldsLoading">
          <template #header>
            <div class="cardHeader">
              <span>标签字段</span>
              <el-button
                type="primary" size="small" aria-label="新建标签字段"
                :disabled="fieldSubmitting || fieldDeleting || optionOperationKeys.size > 0"
                @click="handleAddField"
              >
                <el-icon><Plus /></el-icon>
              </el-button>
            </div>
          </template>
          <div class="fieldList">
            <button
              v-for="field in fields"
              :key="field.id"
              type="button"
              class="fieldItem"
              :class="{ active: selectedFieldId === field.id }"
              :aria-pressed="selectedFieldId === field.id"
              :disabled="fieldSubmitting || fieldDeleting || optionOperationKeys.size > 0"
              @click="selectField(field)"
            >
              <div class="fieldInfo">
                <span class="fieldName">{{ field.name }}</span>
                <el-tag size="small" :type="field.selectMode === 'multi' ? 'warning' : 'info'" effect="plain">
                  {{ field.selectMode === 'multi' ? '多选' : '单选' }}
                </el-tag>
              </div>
              <span class="fieldBadge" v-if="field.ownerId === 0">全局</span>
            </button>
            <div v-if="fieldsError" class="loadError compact" role="alert">
              <span>{{ fieldsError }}</span>
              <el-button link type="primary" @click="loadFields">重试</el-button>
            </div>
            <div v-else-if="!fieldsLoading && fields.length === 0" class="emptyTip">暂无字段，点击上方按钮创建</div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：字段编辑 -->
      <el-col :xs="24" :sm="16" :lg="18">
        <el-card shadow="never" v-if="selectedField" v-loading="fieldDetailLoading">
          <template #header>
            <div class="cardHeader">
              <span>编辑字段</span>
              <div v-if="canManageSelectedField">
                <el-button type="primary" :loading="fieldSubmitting" :disabled="fieldDeleting" @click="saveField">保存</el-button>
                <el-button type="danger" plain :loading="fieldDeleting" :disabled="fieldSubmitting" @click="handleDeleteField">删除</el-button>
              </div>
            </div>
          </template>

          <el-alert
            v-if="!canManageSelectedField"
            title="该全局字段仅管理员可修改，当前为只读预览"
            type="info" :closable="false" show-icon style="margin-bottom: 16px"
          />
          <div v-if="fieldDetailError" class="loadError" role="alert">
            <span>{{ fieldDetailError }}</span>
            <el-button link type="primary" @click="retrySelectedField">重新加载</el-button>
          </div>

          <!-- 基本信息 -->
          <div class="sectionTitle">基本信息</div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="字段Key">
                <el-input v-model="fieldForm.fieldKey" placeholder="英文/数字/下划线" :maxlength="MAX_MINDMAP_TAG_KEY_LENGTH" :disabled="!!fieldForm.id || !canManageSelectedField" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="名称">
                <el-input v-model="fieldForm.name" placeholder="字段显示名称" :maxlength="MAX_MINDMAP_TAG_FIELD_NAME_LENGTH" show-word-limit :disabled="!canManageSelectedField" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="选择模式">
                <el-radio-group v-model="fieldForm.selectMode" :disabled="!canManageSelectedField">
                  <el-radio value="single">单选</el-radio>
                  <el-radio value="multi">多选</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-col>
            <el-col :span="12" v-if="isAdmin">
              <el-form-item label="范围">
                <el-radio-group v-model="fieldForm.ownerScope" :disabled="!canManageSelectedField">
                  <el-radio value="mine">私有</el-radio>
                  <el-radio value="global">全局</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="描述">
            <el-input v-model="fieldForm.description" type="textarea" :rows="1" placeholder="字段描述（可选）" :maxlength="MAX_MINDMAP_TAG_DESCRIPTION_LENGTH" show-word-limit :disabled="!canManageSelectedField" />
          </el-form-item>

          <!-- 基础样式 -->
          <div class="sectionTitle">基础样式</div>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="字号">
                <el-input-number v-model="styleForm.fontSize" :min="10" :max="24" :disabled="!canManageSelectedField" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="圆角">
                <el-input-number v-model="styleForm.radius" :min="0" :max="20" :disabled="!canManageSelectedField" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="内边距">
                <el-input-number v-model="styleForm.paddingX" :min="0" :max="30" :disabled="!canManageSelectedField" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="位置">
                <el-select v-model="styleForm.placement" :disabled="!canManageSelectedField" style="width: 100%">
                  <el-option label="右侧" value="right" />
                  <el-option label="左侧" value="left" />
                  <el-option label="顶部" value="top" />
                  <el-option label="底部" value="bottom" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="对齐">
                <el-select v-model="styleForm.align" :disabled="!canManageSelectedField" style="width: 100%">
                  <el-option v-for="opt in alignOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 选项管理 -->
          <div class="sectionTitle">
            选项管理
            <el-button v-if="canManageSelectedField" type="primary" size="small" style="margin-left: 12px" @click="addOption">
              <el-icon><Plus /></el-icon> 添加选项
            </el-button>
          </div>
          <el-table :data="options" size="small" :header-cell-style="{ background: '#fafafa' }">
            <el-table-column label="Key" width="140">
              <template #default="{ row }">
                <el-input v-model="row.optionKey" size="small" placeholder="option_key" :maxlength="MAX_MINDMAP_TAG_KEY_LENGTH" :disabled="!canManageSelectedField || isOptionBusy(row)"
                  @blur="onOptionChange(row)" />
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="140">
              <template #default="{ row }">
                <el-input v-model="row.name" size="small" placeholder="显示名称" :maxlength="MAX_MINDMAP_TAG_NAME_LENGTH" :disabled="!canManageSelectedField || isOptionBusy(row)"
                  @blur="onOptionChange(row)" />
              </template>
            </el-table-column>
            <el-table-column label="背景色" width="100" align="center">
              <template #default="{ row }">
                <el-popover trigger="click" :disabled="!canManageSelectedField || isOptionBusy(row)" :width="230" placement="bottom-start">
                  <template #reference>
                    <ColorTrigger
                      :color="row.fill || '#409eff'" label="选择选项背景色" :width="28" :height="28"
                      :disabled="!canManageSelectedField || isOptionBusy(row)"
                    />
                  </template>
                  <div class="colorGroupPanel">
                    <div v-for="group in colorGroups" :key="group.label" class="colorGroup">
                      <div class="colorGroupLabel">{{ group.label }}</div>
                      <div class="colorGroupSwatches">
                        <button v-for="c in group.colors" :key="c" type="button" class="colorDot"
                          :class="{ active: row.fill === c, transparentDot: c === 'transparent', lightDot: isLightColor(c) }"
                          :style="c === 'transparent' ? {} : { backgroundColor: c }"
                          :aria-label="`背景色 ${describeColor(c)}`" :aria-pressed="row.fill === c"
                          @click="row.fill = c; onOptionChange(row)" />
                      </div>
                    </div>
                    <div class="customColorRow">
                      <span class="colorGroupLabel">自定义</span>
                      <el-color-picker
                        :model-value="row.fill === 'transparent' ? '#ffffff' : row.fill"
                        show-alpha
                        size="small"
                        :teleported="false" :disabled="!canManageSelectedField || isOptionBusy(row)"
                        @change="(val) => applyFillColor(row, val)" />
                    </div>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="文字色" width="100" align="center">
              <template #default="{ row }">
                <el-popover trigger="click" :disabled="!canManageSelectedField || isOptionBusy(row)" :width="230" placement="bottom-start">
                  <template #reference>
                    <ColorTrigger
                      :color="row.color || '#ffffff'" label="选择选项文字色" :width="28" :height="28"
                      :disabled="!canManageSelectedField || isOptionBusy(row)"
                    />
                  </template>
                  <div class="colorGroupPanel">
                    <div v-for="group in colorGroups" :key="group.label" class="colorGroup">
                      <div class="colorGroupLabel">{{ group.label }}</div>
                      <div class="colorGroupSwatches">
                        <button v-for="c in group.colors" :key="c" type="button" class="colorDot"
                          :class="{ active: row.color === c, transparentDot: c === 'transparent', lightDot: isLightColor(c) }"
                          :style="c === 'transparent' ? {} : { backgroundColor: c }"
                          :aria-label="`文字色 ${describeColor(c)}`" :aria-pressed="row.color === c"
                          @click="row.color = c; onOptionChange(row)" />
                      </div>
                    </div>
                    <div class="customColorRow">
                      <span class="colorGroupLabel">自定义</span>
                      <el-color-picker
                        :model-value="row.color === 'transparent' ? '#ffffff' : row.color"
                        show-alpha
                        size="small"
                        :teleported="false" :disabled="!canManageSelectedField || isOptionBusy(row)"
                        @change="(val) => applyTextColor(row, val)" />
                    </div>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="60" align="center">
              <template #default="{ row, $index }">
                <el-button
                  v-if="canManageSelectedField" link type="danger" size="small"
                  :loading="isOptionBusy(row)" :disabled="isOptionBusy(row)"
                  :aria-label="`删除选项${row.name ? `「${row.name}」` : ''}`"
                  @click="removeOption($index, row)"
                >
                  <el-icon><Delete /></el-icon>
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 预览 -->
          <div class="sectionTitle" style="margin-top: 16px">预览</div>
          <div class="previewBox">
            <span v-for="opt in options" :key="opt.optionKey || opt._tempId"
              class="tagBadge" :style="getOptionStyle(opt)">
              {{ opt.name || '选项' }}
            </span>
            <span v-if="options.length === 0" class="emptyPreview">暂无选项</span>
          </div>
        </el-card>

        <el-card shadow="never" v-else>
          <div class="emptyState">
            <el-icon :size="48" color="#dcdfe6"><Document /></el-icon>
            <p>选择左侧字段进行编辑，或创建新字段</p>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup name="TagFieldManagement">
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { Plus, Delete, Document, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listTagFields, getTagFieldDetail, getTagFieldImpact, addTagField, updateTagField, deleteTagField,
  addTagFieldOption, updateTagFieldOption, deleteTagFieldOption,
  listTags, listTagCategories, addTagCategory, updateTagCategory, deleteTagCategory,
  getTagImpact, disableTag, replaceTag, deleteTags, addTag, updateTag,
} from '@/api/mindmap/tag'
import useUserStore from '@/store/modules/user'
import ColorTrigger from '@/components/MindMap/ColorTrigger.vue'
import { createLatestRequestTracker, isElementDialogDismissal } from '@/utils/mindmap-async'
import {
  getCreatedResourceId,
  isCompatibleTagReplacement,
  MAX_MINDMAP_TAG_BATCH_SIZE,
  MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
  MAX_MINDMAP_TAG_CATEGORY_SORT_ORDER,
  MAX_MINDMAP_TAG_DESCRIPTION_LENGTH,
  MAX_MINDMAP_TAG_FIELD_NAME_LENGTH,
  MAX_MINDMAP_TAG_KEY_LENGTH,
  MAX_MINDMAP_TAG_NAME_LENGTH,
  MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
  validateMindmapTagDescription,
  validateMindmapTagColor,
  validateMindmapTagCategorySortOrder,
  validateMindmapTagDisplayName,
  validateMindmapTagIdentifier,
  validateMindmapTagSearchKeyword,
  validateMindmapTagStyle,
} from '@/utils/mindmap-tag-governance'

const userStore = useUserStore()
const isAdmin = computed(() => Number(userStore.id) === 1)
const hasPermission = permission => userStore.permissions.includes('*:*:*')
  || userStore.permissions.includes(permission)
const canAddCategory = computed(() => hasPermission('mindmap:tag:add'))
const canEditCategory = computed(() => hasPermission('mindmap:tag:edit'))
const canRemoveCategory = computed(() => hasPermission('mindmap:tag:remove'))
const canAddTag = computed(() => hasPermission('mindmap:tag:add'))
const canEditTag = computed(() => hasPermission('mindmap:tag:edit'))
const canRemoveTag = computed(() => hasPermission('mindmap:tag:remove'))
const canManageResource = ownerId => Number(ownerId) === Number(userStore.id)
  || (Number(ownerId) === 0 && isAdmin.value)

// ── 统一标签治理 ──
const managedTags = ref([])
const managedTagsLoading = ref(false)
const managedTagsError = ref('')
const managedTagTotal = ref(0)
const tagCategories = ref([])
const tagCategoriesLoading = ref(false)
const tagCategoriesError = ref('')
const categoryDialog = reactive({ visible: false })
const categoryFormVisible = ref(false)
const categoryForm = reactive({ id: null, name: '', sortOrder: 0, ownerScope: 'mine' })
const categorySubmitting = ref(false)
const categoryOperationKey = ref('')
const categoryBusy = computed(() => categorySubmitting.value || Boolean(categoryOperationKey.value))
const managedTagRequests = createLatestRequestTracker()
const tagCategoryRequests = createLatestRequestTracker()
const replacementRequests = createLatestRequestTracker()
const fieldListRequests = createLatestRequestTracker()
const fieldDetailRequests = createLatestRequestTracker()
let componentActive = true
const managedTagQuery = reactive({
  pageNum: 1, pageSize: 10, keyword: '', ownerScope: 'all',
  status: null, categoryId: null, fieldId: null,
})
const replaceDialog = reactive({
  visible: false, sourceTagId: null, sourceName: '', sourceOwnerId: null,
  targetTagId: null, nodeCount: 0,
})
const replacementOptions = ref([])
const replacementLoading = ref(false)
const replacementError = ref('')
const replaceSubmitting = ref(false)
const tagOperationKey = ref('')
const managedTagTableRef = ref(null)
const managedTagSelection = ref([])
const selectedManagedTagNodeCount = computed(() => managedTagSelection.value.reduce(
  (total, row) => {
    const count = Number(row?.usageNodeCount)
    return total + (Number.isFinite(count) && count > 0 ? count : 0)
  },
  0,
))
const tagEditDialog = reactive({
  visible: false, id: null, name: '', tagKey: '', fill: '#409eff', color: '#ffffff',
  fontSize: 12, radius: 3, paddingX: 8, ownerScope: 'mine', categoryId: null,
  description: '', status: 0, source: null, impact: null,
})
const tagEditSubmitting = ref(false)
const editableTagCategories = computed(() => tagCategories.value.filter(category => (
  Number(category.ownerId) === 0
  || (tagEditDialog.ownerScope === 'mine' && Number(category.ownerId) === Number(userStore.id))
)))

function canEditCategoryRow(row) {
  return canEditCategory.value && canManageResource(row?.ownerId)
}

function canRemoveCategoryRow(row) {
  return canRemoveCategory.value && canManageResource(row?.ownerId)
}

function canEditManagedTag(row) {
  return canEditTag.value && canManageResource(row?.ownerId)
}

function canArchiveManagedTag(row) {
  return canRemoveTag.value && canManageResource(row?.ownerId)
}

function canSelectManagedTag(row) {
  return row?.status !== 2 && canArchiveManagedTag(row)
}

function handleManagedTagSelectionChange(rows) {
  managedTagSelection.value = (rows || []).filter(canSelectManagedTag)
}

function clearManagedTagSelection() {
  managedTagTableRef.value?.clearSelection()
  managedTagSelection.value = []
}

watch(() => tagEditDialog.ownerScope, () => {
  if (
    tagEditDialog.categoryId
    && !editableTagCategories.value.some(item => Number(item.id) === Number(tagEditDialog.categoryId))
  ) {
    tagEditDialog.categoryId = null
  }
})

watch(() => replaceDialog.visible, visible => {
  if (visible) return
  replacementRequests.invalidate()
  replacementLoading.value = false
  replacementError.value = ''
  replacementOptions.value = []
})

watch(() => categoryDialog.visible, visible => {
  if (visible) return
  categoryFormVisible.value = false
  categoryOperationKey.value = ''
  Object.assign(categoryForm, { id: null, name: '', sortOrder: 0, ownerScope: 'mine' })
})

async function loadManagedTags() {
  clearManagedTagSelection()
  const keyword = validateMindmapTagSearchKeyword(managedTagQuery.keyword)
  if (!keyword.valid) {
    managedTagRequests.invalidate()
    managedTagsLoading.value = false
    managedTagsError.value = keyword.message
    return false
  }
  managedTagQuery.keyword = keyword.value
  const requestId = managedTagRequests.begin()
  managedTagsLoading.value = true
  managedTagsError.value = ''
  try {
    const res = await listTags({
      ...managedTagQuery,
      keyword: keyword.value || undefined,
    })
    if (!componentActive || !managedTagRequests.isCurrent(requestId)) return
    managedTags.value = res.rows || []
    managedTagTotal.value = res.total || 0
  } catch (error) {
    if (!componentActive || !managedTagRequests.isCurrent(requestId)) return
    managedTagsError.value = error?.message || '标签列表加载失败，请重试'
  } finally {
    if (componentActive && managedTagRequests.isCurrent(requestId)) {
      managedTagsLoading.value = false
    }
  }
}

async function loadTagCategories() {
  const requestId = tagCategoryRequests.begin()
  tagCategoriesLoading.value = true
  tagCategoriesError.value = ''
  try {
    const res = await listTagCategories()
    if (!componentActive || !tagCategoryRequests.isCurrent(requestId)) return
    tagCategories.value = res.data || []
    return true
  } catch (e) {
    if (!componentActive || !tagCategoryRequests.isCurrent(requestId)) return
    tagCategoriesError.value = e?.message || '标签分类加载失败'
    return false
  } finally {
    if (componentActive && tagCategoryRequests.isCurrent(requestId)) {
      tagCategoriesLoading.value = false
    }
  }
}

async function openCategoryManager() {
  categoryDialog.visible = true
  categoryFormVisible.value = false
  await loadTagCategories()
}

function startCreateCategory() {
  if (!canAddCategory.value || categorySubmitting.value || categoryOperationKey.value) return
  Object.assign(categoryForm, { id: null, name: '', sortOrder: 0, ownerScope: 'mine' })
  categoryFormVisible.value = true
}

function startEditCategory(row) {
  if (!canEditCategoryRow(row) || categorySubmitting.value || categoryOperationKey.value) return
  Object.assign(categoryForm, {
    id: Number(row.id),
    name: row.name || '',
    sortOrder: Number(row.sortOrder) || 0,
    ownerScope: Number(row.ownerId) === 0 ? 'global' : 'mine',
  })
  categoryFormVisible.value = true
}

function cancelCategoryEdit() {
  if (categorySubmitting.value) return
  categoryFormVisible.value = false
  Object.assign(categoryForm, { id: null, name: '', sortOrder: 0, ownerScope: 'mine' })
}

async function saveCategory() {
  if (categorySubmitting.value || categoryOperationKey.value) return
  const name = validateMindmapTagDisplayName(categoryForm.name, {
    label: '分类名称',
    maxLength: MAX_MINDMAP_TAG_CATEGORY_NAME_LENGTH,
  })
  const sortOrder = validateMindmapTagCategorySortOrder(categoryForm.sortOrder)
  const invalid = [name, sortOrder].find(item => !item.valid)
  if (invalid) return ElMessage.warning(invalid.message)
  if (categoryForm.id) {
    const source = tagCategories.value.find(item => Number(item.id) === Number(categoryForm.id))
    if (!canEditCategoryRow(source)) return ElMessage.warning('你没有该分类的编辑权限')
  } else if (!canAddCategory.value) {
    return ElMessage.warning('你没有新建分类的权限')
  }

  categoryForm.name = name.value
  categoryForm.sortOrder = sortOrder.value
  const isEditing = Boolean(categoryForm.id)
  categorySubmitting.value = true
  try {
    if (categoryForm.id) {
      await updateTagCategory(categoryForm.id, name.value, sortOrder.value)
    } else {
      const response = await addTagCategory(name.value, sortOrder.value, categoryForm.ownerScope)
      if (!getCreatedResourceId(response, 'categoryId')) {
        throw new Error('分类已创建，但服务端未返回有效分类 ID，请刷新后重试')
      }
    }
    if (!componentActive || !categoryDialog.visible) return
    ElMessage.success(isEditing ? '分类已更新' : '分类已创建')
    categoryFormVisible.value = false
    Object.assign(categoryForm, { id: null, name: '', sortOrder: 0, ownerScope: 'mine' })
    await loadTagCategories()
  } catch (error) {
    if (!componentActive || !categoryDialog.visible) return
    ElMessage.error(error?.message || '分类保存失败')
  } finally {
    categorySubmitting.value = false
  }
}

async function removeCategory(row) {
  if (!canRemoveCategoryRow(row) || categorySubmitting.value || categoryOperationKey.value) return
  if (Number(row.tagCount) > 0) {
    return ElMessage.warning(`该分类仍有 ${row.tagCount} 个标签，请先转移或移除`)
  }
  categoryOperationKey.value = `delete:${row.id}`
  try {
    await ElMessageBox.confirm(
      `确认删除空分类「${row.name}」？该操作不会删除任何标签。`,
      '删除标签分类',
      { type: 'warning', confirmButtonText: '确认删除' },
    )
    await deleteTagCategory(row.id)
    if (!componentActive || !categoryDialog.visible) return
    const wasActiveFilter = Number(managedTagQuery.categoryId) === Number(row.id)
    if (wasActiveFilter) managedTagQuery.categoryId = null
    if (Number(tagEditDialog.categoryId) === Number(row.id)) tagEditDialog.categoryId = null
    ElMessage.success('分类已删除')
    await loadTagCategories()
    if (wasActiveFilter) await loadManagedTags()
  } catch (error) {
    if (
      componentActive
      && categoryDialog.visible
      && !isElementDialogDismissal(error)
    ) {
      ElMessage.error(error?.message || '分类删除失败')
    }
  } finally {
    categoryOperationKey.value = ''
  }
}

function handleManagedTagSearch() {
  managedTagQuery.pageNum = 1
  loadManagedTags()
}

function resetManagedTagSearch() {
  Object.assign(managedTagQuery, {
    pageNum: 1, keyword: '', ownerScope: 'all', status: null, categoryId: null, fieldId: null,
  })
  loadManagedTags()
}

function handleManagedTagPageSize(size) {
  managedTagQuery.pageSize = size
  managedTagQuery.pageNum = 1
  loadManagedTags()
}

function categoryName(categoryId) {
  if (!categoryId) return '未分类'
  return tagCategories.value.find(item => Number(item.id) === Number(categoryId))?.name || '未知分类'
}

function fieldNames(row) {
  const names = (row.fields || []).map(item => item.name).filter(Boolean)
  return names.length ? names.join('、') : '独立标签'
}

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

function getManagedTagStyle(row) {
  const style = row.style || {}
  const fill = normalizeColor(style.fill) || '#eef4ff'
  const color = normalizeColor(style.color) || '#3157a4'
  return {
    backgroundColor: fill === 'transparent' ? '#f5f7fa' : fill,
    color: color === 'transparent' ? '#303133' : color,
    fontSize: `${style.fontSize || 12}px`,
    borderRadius: `${style.radius ?? 5}px`,
    padding: `3px ${style.paddingX ?? 8}px`,
  }
}

async function fetchImpact(row) {
  const res = await getTagImpact(row.id)
  return res.data || { fileCount: 0, nodeCount: 0, files: [] }
}

async function showTagImpact(row) {
  if (tagOperationKey.value) return
  tagOperationKey.value = `impact:${row.id}`
  try {
    const impact = await fetchImpact(row)
    const examples = (impact.files || []).slice(0, 5).map(item => item.name).join('、')
    await ElMessageBox.alert(
      `当前影响 ${impact.fileCount || 0} 个脑图、${impact.nodeCount || 0} 个节点${examples ? `；示例：${examples}` : ''}。`,
      `标签「${row.name}」影响范围`,
      { confirmButtonText: '知道了' }
    )
  } catch (e) {
    if (!isElementDialogDismissal(e)) ElMessage.error(e.message || '加载标签影响范围失败')
  } finally {
    tagOperationKey.value = ''
  }
}

async function handleEditManagedTag(row) {
  if (tagOperationKey.value || !canEditManagedTag(row)) return
  tagOperationKey.value = `edit:${row.id}`
  try {
    const impact = await fetchImpact(row)
    const style = row.style || {}
    Object.assign(tagEditDialog, {
      visible: true,
      id: row.id,
      name: row.name,
      tagKey: row.tagKey,
      fill: style.fill || '#409eff',
      color: style.color || '#ffffff',
      fontSize: style.fontSize || 12,
      radius: style.radius ?? 3,
      paddingX: style.paddingX ?? 8,
      ownerScope: row.ownerId === 0 ? 'global' : 'mine',
      categoryId: row.categoryId || null,
      description: row.description || '',
      status: row.status ?? 0,
      source: row,
      impact,
    })
  } catch (e) {
    ElMessage.error(e.message || '加载标签详情失败')
  } finally {
    tagOperationKey.value = ''
  }
}

function handleCreateManagedTag() {
  if (!canAddTag.value || tagOperationKey.value) return
  Object.assign(tagEditDialog, {
    visible: true,
    id: null,
    name: '',
    tagKey: '',
    fill: '#409eff',
    color: '#ffffff',
    fontSize: 12,
    radius: 3,
    paddingX: 8,
    ownerScope: 'mine',
    categoryId: null,
    description: '',
    status: 0,
    source: null,
    impact: null,
  })
}

async function confirmEditManagedTag() {
  if (tagEditSubmitting.value) return
  if (tagEditDialog.id) {
    if (!canEditManagedTag(tagEditDialog.source)) {
      return ElMessage.warning('你没有该标签的编辑权限')
    }
  } else if (!canAddTag.value) {
    return ElMessage.warning('你没有新建标签的权限')
  }
  const name = validateMindmapTagDisplayName(tagEditDialog.name)
  const tagKey = validateMindmapTagIdentifier(tagEditDialog.tagKey)
  const description = validateMindmapTagDescription(tagEditDialog.description)
  const style = validateMindmapTagStyle({
    fill: tagEditDialog.fill,
    color: tagEditDialog.color,
    fontSize: tagEditDialog.fontSize,
    radius: tagEditDialog.radius,
    paddingX: tagEditDialog.paddingX,
  })
  const invalid = [name, tagKey, description, style].find(item => !item.valid)
  if (invalid) return ElMessage.warning(invalid.message)
  tagEditDialog.name = name.value
  tagEditDialog.tagKey = tagKey.value
  tagEditDialog.description = description.value
  tagEditSubmitting.value = true
  try {
    if (tagEditDialog.id) {
      const impact = tagEditDialog.impact || {}
      await ElMessageBox.confirm(
        `保存后会影响 ${impact.fileCount || 0} 个脑图、${impact.nodeCount || 0} 个节点，是否继续？`,
        '确认全局修改', { type: 'warning', confirmButtonText: '保存并全局生效' }
      )
    }
    const source = tagEditDialog.source || {}
    const payload = {
      tagKey: tagKey.value,
      name: name.value,
      categoryId: tagEditDialog.categoryId,
      ownerId: tagEditDialog.ownerScope === 'global'
        ? 0
        : (tagEditDialog.id ? source.ownerId : userStore.id),
      description: description.value || null,
      status: tagEditDialog.status,
      style: style.value,
    }
    if (tagEditDialog.id) await updateTag({ ...payload, id: tagEditDialog.id })
    else await addTag(payload)
    tagEditDialog.visible = false
    ElMessage.success(tagEditDialog.id ? '标签定义已全局更新' : '标签创建成功')
    await loadManagedTags()
  } catch (e) {
    if (!isElementDialogDismissal(e)) ElMessage.error(e.message || '标签更新失败')
  } finally {
    tagEditSubmitting.value = false
  }
}

async function handleDisableTag(row) {
  if (tagOperationKey.value || !canEditManagedTag(row)) return
  tagOperationKey.value = `disable:${row.id}`
  try {
    const impact = await fetchImpact(row)
    if (!componentActive || !canEditManagedTag(row)) return
    await ElMessageBox.confirm(
      `停用后既有 ${impact.nodeCount || 0} 个节点仍会显示，但新增时不可再选择。是否继续？`,
      `停用「${row.name}」`, { type: 'warning' }
    )
    if (!componentActive || !canEditManagedTag(row)) return
    await disableTag(row.id)
    if (!componentActive) return
    ElMessage.success('标签已停用')
    await loadManagedTags()
  } catch (e) {
    if (componentActive && !isElementDialogDismissal(e)) ElMessage.error(e.message || '停用失败')
  } finally {
    tagOperationKey.value = ''
  }
}

async function handleReplaceTag(row) {
  if (tagOperationKey.value || !canEditManagedTag(row)) return
  tagOperationKey.value = `replace:${row.id}`
  try {
    const impact = await fetchImpact(row)
    if (!componentActive || !canEditManagedTag(row)) return
    Object.assign(replaceDialog, {
      visible: true,
      sourceTagId: row.id,
      sourceName: row.name,
      sourceOwnerId: row.ownerId,
      targetTagId: null,
      nodeCount: impact.nodeCount || 0,
    })
    await searchReplacementTags('')
  } catch (e) {
    ElMessage.error(e.message || '加载可替换标签失败')
  } finally {
    tagOperationKey.value = ''
  }
}

function handleManagedTagCommand(command, row) {
  if (
    tagOperationKey.value
    || row?.status === 2
    || !canManageResource(row?.ownerId)
  ) return
  if (command === 'edit' && canEditManagedTag(row)) return handleEditManagedTag(row)
  if (command === 'disable' && row.status === 0 && canEditManagedTag(row)) {
    return handleDisableTag(row)
  }
  if (command === 'replace' && canEditManagedTag(row)) return handleReplaceTag(row)
  if (command === 'archive' && canArchiveManagedTag(row)) return handleArchiveTag(row)
}

async function searchReplacementTags(keyword) {
  const normalizedKeyword = validateMindmapTagSearchKeyword(String(keyword ?? ''))
  if (!normalizedKeyword.valid) {
    replacementRequests.invalidate()
    replacementOptions.value = []
    replacementLoading.value = false
    replacementError.value = normalizedKeyword.message
    return false
  }
  const requestId = replacementRequests.begin()
  replacementLoading.value = true
  replacementError.value = ''
  try {
    const res = await listTags({
      pageNum: 1,
      pageSize: 100,
      ownerScope: 'all',
      keyword: normalizedKeyword.value || undefined,
    })
    if (!componentActive || !replacementRequests.isCurrent(requestId) || !replaceDialog.visible) return
    replacementOptions.value = (res.rows || []).filter(
      item => isCompatibleTagReplacement(
        { id: replaceDialog.sourceTagId, ownerId: replaceDialog.sourceOwnerId },
        item,
      )
    )
  } catch (error) {
    if (!componentActive || !replacementRequests.isCurrent(requestId) || !replaceDialog.visible) return
    replacementOptions.value = []
    replacementError.value = error?.message || '目标标签加载失败，请重新搜索'
  } finally {
    if (componentActive && replacementRequests.isCurrent(requestId)) {
      replacementLoading.value = false
    }
  }
}

async function confirmReplaceTag() {
  if (
    !replaceDialog.targetTagId
    || !canEditTag.value
    || !canManageResource(replaceDialog.sourceOwnerId)
  ) return
  replaceSubmitting.value = true
  try {
    await replaceTag(replaceDialog.sourceTagId, replaceDialog.targetTagId)
    if (!componentActive || !replaceDialog.visible) return
    replaceDialog.visible = false
    ElMessage.success('标签替换成功')
    await loadManagedTags()
  } catch (e) {
    if (componentActive && replaceDialog.visible) ElMessage.error(e.message || '替换失败')
  } finally {
    replaceSubmitting.value = false
  }
}

async function handleArchiveTag(row) {
  if (tagOperationKey.value || !canArchiveManagedTag(row)) return
  tagOperationKey.value = `archive:${row.id}`
  try {
    const impact = await fetchImpact(row)
    if (!componentActive || !canArchiveManagedTag(row)) return
    await ElMessageBox.confirm(
      `将从 ${impact.nodeCount || 0} 个节点解除该标签并归档。此操作不会删除历史版本快照，是否继续？`,
      `解绑并归档「${row.name}」`,
      { type: 'error', confirmButtonText: '确认解绑并归档' }
    )
    if (!componentActive || !canArchiveManagedTag(row)) return
    await deleteTags(row.id, true)
    if (!componentActive) return
    ElMessage.success('标签已解绑并归档')
    await loadManagedTags()
  } catch (e) {
    if (componentActive && !isElementDialogDismissal(e)) ElMessage.error(e.message || '归档失败')
  } finally {
    tagOperationKey.value = ''
  }
}

async function handleBatchArchiveTags() {
  if (tagOperationKey.value) return
  const rows = managedTagSelection.value.filter(canSelectManagedTag)
  const tagIds = [...new Set(rows.map(row => Number(row.id)).filter(Number.isSafeInteger))]
  if (!tagIds.length || tagIds.length !== managedTagSelection.value.length) {
    return ElMessage.warning('所选标签已变化，请重新选择')
  }
  if (tagIds.length > MAX_MINDMAP_TAG_BATCH_SIZE) {
    return ElMessage.warning(`单次最多处理 ${MAX_MINDMAP_TAG_BATCH_SIZE} 个标签`)
  }

  const estimatedNodeCount = selectedManagedTagNodeCount.value
  tagOperationKey.value = 'archive:batch'
  try {
    await ElMessageBox.confirm(
      `将从预计 ${estimatedNodeCount} 个节点解除 ${tagIds.length} 个标签并归档。`
        + '服务端会重新校验全部标签、权限和真实引用；历史版本快照不会删除。是否继续？',
      `批量解绑并归档 ${tagIds.length} 个标签`,
      { type: 'error', confirmButtonText: '确认批量归档' },
    )
    if (!componentActive || rows.some(row => !canArchiveManagedTag(row))) return
    const response = await deleteTags(tagIds.join(','), true)
    if (!componentActive) return
    const affectedFiles = Number(response?.data?.affectedFileCount) || 0
    ElMessage.success(`已归档 ${tagIds.length} 个标签，影响 ${affectedFiles} 个脑图`)
    clearManagedTagSelection()
    await loadManagedTags()
  } catch (error) {
    if (componentActive && !isElementDialogDismissal(error)) {
      ElMessage.error(error?.message || '批量归档失败')
    }
  } finally {
    tagOperationKey.value = ''
  }
}

// ── 字段列表 ──
const fields = ref([])
const fieldsLoading = ref(false)
const fieldsError = ref('')
const selectedFieldId = ref(null)
const selectedField = ref(null)
const fieldDetailLoading = ref(false)
const fieldDetailError = ref('')
const fieldSubmitting = ref(false)
const fieldDeleting = ref(false)
const canManageSelectedField = computed(() => (
  !fieldForm.id || canManageResource(selectedField.value?.ownerId)
))

async function loadFields() {
  const requestId = fieldListRequests.begin()
  fieldsLoading.value = true
  fieldsError.value = ''
  try {
    const res = await listTagFields()
    if (!componentActive || !fieldListRequests.isCurrent(requestId)) return
    fields.value = res.data || []
  } catch (e) {
    if (!componentActive || !fieldListRequests.isCurrent(requestId)) return
    fieldsError.value = e?.message || '字段列表加载失败'
  } finally {
    if (componentActive && fieldListRequests.isCurrent(requestId)) {
      fieldsLoading.value = false
    }
  }
}

async function selectField(field) {
  if (!field?.id) return
  const requestId = fieldDetailRequests.begin()
  selectedFieldId.value = field.id
  selectedField.value = field
  fieldDetailLoading.value = true
  fieldDetailError.value = ''
  fieldForm.id = field.id
  fieldForm.fieldKey = field.fieldKey || ''
  fieldForm.name = field.name || ''
  fieldForm.selectMode = field.selectMode || 'single'
  fieldForm.ownerScope = Number(field.ownerId) === 0 ? 'global' : 'mine'
  fieldForm.description = field.description || ''
  styleForm.fontSize = 12
  styleForm.radius = 3
  styleForm.paddingX = 8
  styleForm.placement = 'right'
  styleForm.align = 'center'
  options.value = []
  try {
    const res = await getTagFieldDetail(field.id)
    if (
      !componentActive
      || !fieldDetailRequests.isCurrent(requestId)
      || Number(selectedFieldId.value) !== Number(field.id)
    ) return
    const detail = res.data
    selectedField.value = detail
    // 填充表单
    fieldForm.id = detail.id
    fieldForm.fieldKey = detail.fieldKey
    fieldForm.name = detail.name
    fieldForm.selectMode = detail.selectMode || 'single'
    fieldForm.ownerScope = detail.ownerId === 0 ? 'global' : 'mine'
    fieldForm.description = detail.description || ''
    // 样式
    const style = detail.style || {}
    styleForm.fontSize = style.fontSize || 12
    styleForm.radius = style.radius ?? 3
    styleForm.paddingX = style.paddingX ?? 8
    styleForm.placement = style.placement || 'right'
    styleForm.align = style.align || 'center'
    // 选项
    options.value = (detail.options || []).map(o => ({ ...o, _dirty: false }))
  } catch (e) {
    if (!componentActive || !fieldDetailRequests.isCurrent(requestId)) return
    fieldDetailError.value = e?.message || '字段详情加载失败'
  } finally {
    if (componentActive && fieldDetailRequests.isCurrent(requestId)) {
      fieldDetailLoading.value = false
    }
  }
}

function retrySelectedField() {
  const field = fields.value.find(item => Number(item.id) === Number(selectedFieldId.value))
  if (field) selectField(field)
}

// ── 字段表单 ──
const fieldForm = reactive({
  id: null, fieldKey: '', name: '', selectMode: 'single',
  ownerScope: 'mine', description: '',
})
const styleForm = reactive({
  fontSize: 12, radius: 3, paddingX: 8, placement: 'right', align: 'center',
})

// 对齐选项
const alignOptions = computed(() => {
  const p = styleForm.placement
  if (p === 'top' || p === 'bottom') {
    return [
      { label: '居中', value: 'center' },
      { label: '靠左', value: 'left' },
      { label: '靠右', value: 'right' },
    ]
  }
  return [
    { label: '居中', value: 'center' },
    { label: '靠上', value: 'top' },
    { label: '靠下', value: 'bottom' },
  ]
})

watch(() => styleForm.placement, () => {
  const valid = alignOptions.value.map(o => o.value)
  if (!valid.includes(styleForm.align)) styleForm.align = 'center'
})

function handleAddField() {
  fieldDetailRequests.invalidate()
  selectedFieldId.value = null
  selectedField.value = { id: 'new' }
  fieldDetailLoading.value = false
  fieldDetailError.value = ''
  fieldForm.id = null
  fieldForm.fieldKey = ''
  fieldForm.name = ''
  fieldForm.selectMode = 'single'
  fieldForm.ownerScope = 'mine'
  fieldForm.description = ''
  styleForm.fontSize = 12
  styleForm.radius = 3
  styleForm.paddingX = 8
  styleForm.placement = 'right'
  styleForm.align = 'center'
  options.value = []
}

// 静默保存字段（用于添加选项前自动创建字段），返回是否成功
let fieldCreatePromise = null

function buildFieldPayload() {
  const fieldKey = validateMindmapTagIdentifier(fieldForm.fieldKey, { label: '字段 Key' })
  const name = validateMindmapTagDisplayName(fieldForm.name, {
    label: '字段名称',
    maxLength: MAX_MINDMAP_TAG_FIELD_NAME_LENGTH,
  })
  const description = validateMindmapTagDescription(fieldForm.description, { label: '字段说明' })
  const style = validateMindmapTagStyle({
    fontSize: styleForm.fontSize,
    radius: styleForm.radius,
    paddingX: styleForm.paddingX,
    placement: styleForm.placement,
    align: styleForm.align,
  }, { fieldStyle: true })
  const invalid = [fieldKey, name, description, style].find(item => !item.valid)
  if (invalid) {
    ElMessage.warning(invalid.message)
    return null
  }
  fieldForm.fieldKey = fieldKey.value
  fieldForm.name = name.value
  fieldForm.description = description.value
  return {
    fieldKey: fieldKey.value,
    name: name.value,
    selectMode: fieldForm.selectMode,
    ownerId: fieldForm.ownerScope === 'global' ? 0 : userStore.id,
    description: description.value || null,
    style: style.value,
  }
}

async function saveFieldSilent() {
  if (fieldForm.id) return true
  if (fieldCreatePromise) return fieldCreatePromise
  const data = buildFieldPayload()
  if (!data) return false
  fieldCreatePromise = (async () => {
    try {
      const res = await addTagField(data)
      const fieldId = getCreatedResourceId(res, 'fieldId')
      if (!fieldId) {
        throw new Error('字段已创建，但服务端未返回有效字段 ID，请刷新后重试')
      }
      fieldForm.id = fieldId
      selectedFieldId.value = fieldId
      await loadFields()
      selectedField.value = fields.value.find(f => Number(f.id) === fieldId) || {
        id: fieldId,
        ...data,
      }
      return true
    } catch (e) {
      ElMessage.error(e.message || '字段保存失败')
      return false
    } finally {
      fieldCreatePromise = null
    }
  })()
  return fieldCreatePromise
}

async function saveField() {
  if (fieldSubmitting.value || fieldDeleting.value) return
  if (!canManageSelectedField.value) return ElMessage.warning('当前字段为只读')
  const data = buildFieldPayload()
  if (!data) return

  fieldSubmitting.value = true
  try {
    let savedFieldId = fieldForm.id
    if (fieldForm.id) {
      const impactRes = await getTagFieldImpact(fieldForm.id)
      const impact = impactRes.data || {}
      const switchingToSingle = selectedField.value?.selectMode !== 'single'
        && fieldForm.selectMode === 'single'
      if (switchingToSingle && impact.multiSelectionNodeCount > 0) {
        await ElMessageBox.alert(
          `当前有 ${impact.multiSelectionNodeCount} 个节点使用了该字段的多个选项，请先清理冲突后再切换为单选。`,
          '无法切换为单选',
          { type: 'warning', confirmButtonText: '知道了' }
        )
        return
      }
      const styleChanged = JSON.stringify(selectedField.value?.style || {})
        !== JSON.stringify(data.style || {})
      if (styleChanged && impact.nodeCount > 0) {
        const examples = (impact.files || []).slice(0, 5).map(item => item.name).join('、')
        await ElMessageBox.confirm(
          `字段默认样式会同步影响 ${impact.fileCount || 0} 个脑图、${impact.nodeCount || 0} 个节点${examples ? `；示例：${examples}` : ''}。是否继续？`,
          '确认全局样式修改',
          { type: 'warning', confirmButtonText: '保存并全局生效' }
        )
      }
      data.id = fieldForm.id
      await updateTagField(data)
      ElMessage.success('字段更新成功')
    } else {
      const res = await addTagField(data)
      savedFieldId = getCreatedResourceId(res, 'fieldId')
      if (!savedFieldId) {
        throw new Error('字段已创建，但服务端未返回有效字段 ID，请刷新后重试')
      }
      fieldForm.id = savedFieldId
      ElMessage.success('字段创建成功')
    }
    await loadFields()
    const savedField = fields.value.find(f => Number(f.id) === Number(savedFieldId))
    if (savedField) await selectField(savedField)
  } catch (e) {
    if (!isElementDialogDismissal(e)) ElMessage.error(e.message || '保存失败')
  } finally {
    fieldSubmitting.value = false
  }
}

async function handleDeleteField() {
  if (fieldSubmitting.value || fieldDeleting.value) return
  if (!canManageSelectedField.value) return ElMessage.warning('当前字段为只读')
  if (!fieldForm.id) {
    // 新建未保存，直接清空
    selectedField.value = null
    selectedFieldId.value = null
    return
  }
  fieldDeleting.value = true
  try {
    await ElMessageBox.confirm(`确认删除字段「${fieldForm.name}」及其所有选项？`, '提示', { type: 'warning' })
    await deleteTagField(fieldForm.id)
    ElMessage.success('字段删除成功')
    selectedField.value = null
    selectedFieldId.value = null
    await loadFields()
  } catch (e) {
    if (!isElementDialogDismissal(e)) ElMessage.error(e.message || '删除失败')
  } finally {
    fieldDeleting.value = false
  }
}

// ── 选项管理 ──
const options = ref([])
let tempIdCounter = 0

function addOption() {
  if (!canManageSelectedField.value) return
  options.value.push({
    _tempId: `temp_${++tempIdCounter}`,
    optionKey: '',
    name: '',
    fill: '#409eff',
    color: '#ffffff',
    sortOrder: options.value.length,
    _dirty: true,
  })
}

const optionOperationKeys = reactive(new Set())

function getOptionOperationKey(row) {
  return String(row.id ? `id:${row.id}` : `temp:${row._tempId}`)
}

function isOptionBusy(row) {
  return optionOperationKeys.has(getOptionOperationKey(row))
}

async function removeOption(index, row) {
  if (!canManageSelectedField.value) return
  if (!row.id) {
    options.value.splice(index, 1)
    return
  }
  const operationKey = getOptionOperationKey(row)
  if (optionOperationKeys.has(operationKey)) return
  optionOperationKeys.add(operationKey)
  try {
    await ElMessageBox.confirm(
      `确认删除选项「${row.name || row.optionKey}」？正在使用的选项会被服务端阻止删除。`,
      '删除字段选项',
      { type: 'warning', confirmButtonText: '确认删除' }
    )
    await deleteTagFieldOption(row.id)
    const currentIndex = options.value.findIndex(item => Number(item.id) === Number(row.id))
    if (currentIndex >= 0) options.value.splice(currentIndex, 1)
    ElMessage.success('选项删除成功')
  } catch (e) {
    if (!isElementDialogDismissal(e)) ElMessage.error(e.message || '删除选项失败')
  } finally {
    optionOperationKeys.delete(operationKey)
  }
}

async function onOptionChange(row) {
  if (!canManageSelectedField.value) return
  if (!row.optionKey?.trim() && !row.name?.trim()) return
  const optionKey = validateMindmapTagIdentifier(row.optionKey, { label: '选项 Key' })
  const name = validateMindmapTagDisplayName(row.name, { label: '选项名称' })
  const fill = validateMindmapTagColor(row.fill, { label: '选项背景色' })
  const color = validateMindmapTagColor(row.color, { label: '选项文字色' })
  const invalid = [optionKey, name, fill, color].find(item => !item.valid)
  if (invalid) return ElMessage.warning(invalid.message)
  row.optionKey = optionKey.value
  row.name = name.value
  row.fill = fill.value
  row.color = color.value
  const operationKey = getOptionOperationKey(row)
  if (optionOperationKeys.has(operationKey)) return
  optionOperationKeys.add(operationKey)

  try {
    // 字段未保存时，先通过单飞请求创建，避免多个新选项并发创建重复字段。
    if (!fieldForm.id) {
      const saved = await saveFieldSilent()
      if (!saved) return
    }

    if (row.id) {
      // 更新已有选项
      await updateTagFieldOption({
        id: row.id,
        fieldId: fieldForm.id,
        optionKey: optionKey.value,
        name: name.value,
        fill: fill.value,
        color: color.value,
        sortOrder: row.sortOrder,
      })
    } else {
      // 创建新选项
      const res = await addTagFieldOption({
        fieldId: fieldForm.id,
        optionKey: optionKey.value,
        name: name.value,
        fill: fill.value,
        color: color.value,
        sortOrder: row.sortOrder,
      })
      const optionId = getCreatedResourceId(res, 'optionId')
      if (!optionId) {
        throw new Error('选项已创建，但服务端未返回有效选项 ID，请重新加载字段详情')
      }
      row.id = optionId
      row.tagId = res.data?.tagId || null
    }
    row._dirty = false
  } catch (e) {
    ElMessage.error(e.message || '保存选项失败')
  } finally {
    optionOperationKeys.delete(operationKey)
  }
}

// ── 颜色预设（背景色与文字色共用） ──
const colorGroups = [
  { label: '特殊', colors: ['transparent', '#FFFFFF'] },
  { label: '灰色', colors: ['#F5F5F5', '#D9D9D9', '#B3B3B3', '#666666', '#333333'] },
  { label: '红色', colors: ['#FFCCC7', '#FFA39E', '#FF4D4F', '#CF1322', '#820014'] },
  { label: '橙黄', colors: ['#FFF1B8', '#FFD666', '#FAAD14', '#D48806', '#874D00'] },
  { label: '绿色', colors: ['#D9F7BE', '#95DE64', '#52C41A', '#237804', '#092B00'] },
  { label: '青色', colors: ['#B5F5EC', '#5CDBD3', '#13C2C2', '#006D75', '#002329'] },
  { label: '蓝色', colors: ['#D6E4FF', '#85A5FF', '#4D73FF', '#1D39C4', '#061178'] },
  { label: '紫色', colors: ['#EFDBFF', '#B37FEB', '#722ED1', '#391085', '#120338'] },
]
// 浅色圆点集合（在白底弹窗中需加边框才能看见）
const lightColors = new Set(['#FFFFFF', '#F5F5F5'])
function isLightColor(c) { return lightColors.has(c) }
function describeColor(color) { return color === 'transparent' ? '透明色' : color }

// ── 颜色工具 ──
function normalizeColor(val) {
  const result = validateMindmapTagColor(val)
  return result.valid ? result.value : null
}

function applyFillColor(row, val) {
  if (val === null) return
  row.fill = normalizeColor(val)
  onOptionChange(row)
}

function applyTextColor(row, val) {
  if (val === null) return
  row.color = normalizeColor(val)
  onOptionChange(row)
}

// ── 预览样式 ──
function getOptionStyle(opt) {
  const fill = normalizeColor(opt.fill) || '#409eff'
  const color = normalizeColor(opt.color) || '#fff'
  return {
    backgroundColor: fill === 'transparent' ? '#f5f5f5' : fill,
    color: color === 'transparent' ? '#333333' : color,
    fontSize: (styleForm.fontSize || 12) + 'px',
    borderRadius: (styleForm.radius ?? 3) + 'px',
    padding: `2px ${styleForm.paddingX ?? 8}px`,
    display: 'inline-block',
    marginRight: '8px',
  }
}

onMounted(() => {
  loadManagedTags()
  loadTagCategories()
  loadFields()
})

onBeforeUnmount(() => {
  componentActive = false
  managedTagRequests.invalidate()
  tagCategoryRequests.invalidate()
  replacementRequests.invalidate()
  fieldListRequests.invalidate()
  fieldDetailRequests.invalidate()
})
</script>

<style lang="scss" scoped>
.cardHeader {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.governanceCard {
  margin-bottom: 16px;
}

.headerHint {
  margin-left: 12px;
  color: #909399;
  font-size: 12px;
  font-weight: normal;
}

.governanceToolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: linear-gradient(135deg, #fafcff 0%, #f7f9fc 100%);

  .keywordInput {
    width: min(280px, 100%);
  }

  .filterSelect {
    width: 130px;
  }
}

.managedTagCell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
  min-width: 0;
}

.managedTagPreview {
  display: inline-flex;
  max-width: 100%;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.managedTagDescription {
  width: 100%;
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.managedTagActions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  white-space: nowrap;
}

.auditTime {
  color: #606266;
  cursor: help;
}

.auditDetail {
  display: grid;
  gap: 6px;
  color: #606266;
  font-size: 12px;
}

.governancePager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.governanceBatchBar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  color: #7a2e0e;
  background: #fff8eb;
  border: 1px solid #fedf89;
  border-radius: 8px;
  font-size: 13px;
}

.governanceBatchActions {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
}

.categoryHint {
  margin-bottom: 16px;
}

.categoryEditor {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 130px 130px auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid #d9e6ff;
  border-radius: 8px;
  background: #f7faff;
}

.categoryEditorActions {
  display: flex;
  gap: 8px;
}

.categoryCreateAction {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.categoryScopeTag {
  margin-left: 8px;
}

.loadError {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  color: #b42318;
  background: #fff4f2;
  border: 1px solid #fecdca;
  border-radius: 8px;
  font-size: 13px;

  &.compact {
    margin: 8px 0 0;
  }
}

.fieldError {
  width: 100%;
  margin-top: 6px;
  color: #b42318;
  font-size: 12px;
}

.fieldWorkspace {
  row-gap: 16px;
}

@media (max-width: 900px) {
  .cardHeader {
    align-items: flex-start;
    gap: 12px;
  }

  .headerHint {
    display: block;
    margin: 4px 0 0;
  }

  .governanceToolbar {
    .keywordInput,
    .filterSelect {
      width: calc(50% - 5px);
    }
  }
}

@media (max-width: 560px) {
  .cardHeader,
  .governanceToolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .governanceToolbar {
    .keywordInput,
    .filterSelect {
      width: 100%;
    }
  }

  .governancePager {
    justify-content: flex-start;
    overflow-x: auto;
  }

  .categoryEditor {
    grid-template-columns: 1fr;
  }

  .governanceBatchBar {
    flex-direction: column;
    align-items: stretch;
  }

  .governanceBatchActions {
    justify-content: flex-end;
  }

  .categoryScope,
  .categoryEditorActions {
    width: 100%;
  }

  .categoryEditorActions {
    justify-content: flex-end;
  }
}

.fieldList {
  .fieldItem {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.2s;
    margin-bottom: 2px;
    width: 100%;
    color: inherit;
    font: inherit;
    text-align: left;
    appearance: none;
    background: transparent;
    border: 0;

    &:hover {
      background: #f5f7fa;
    }

    &:focus-visible {
      outline: 2px solid #409eff;
      outline-offset: 1px;
    }

    &:disabled {
      cursor: wait;
      opacity: 0.65;
    }

    &.active {
      background: #ecf5ff;
    }

    .fieldInfo {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 1;
      overflow: hidden;
    }

    .fieldName {
      font-size: 14px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .fieldBadge {
      font-size: 11px;
      color: #67c23a;
      flex-shrink: 0;
    }
  }

  .emptyTip {
    text-align: center;
    color: #999;
    padding: 24px 0;
    font-size: 13px;
  }
}

.sectionTitle {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin: 4px 0 12px;
  padding-left: 8px;
  border-left: 3px solid #4D73FF;
  display: flex;
  align-items: center;

  &:first-child {
    margin-top: 0;
  }
}

.el-form-item {
  margin-bottom: 14px;
}

.previewBox {
  padding: 12px 16px;
  background: #fafafa;
  border-radius: 6px;
  border: 1px dashed #e4e7ed;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;

  .tagBadge {
    line-height: 1.4;
  }

  .emptyPreview {
    color: #999;
    font-size: 13px;
  }
}

.emptyState {
  text-align: center;
  padding: 80px 0;
  color: #999;

  p {
    margin-top: 12px;
    font-size: 14px;
  }
}

.colorGroupPanel {
  .colorGroup {
    margin-bottom: 6px;

    .colorGroupLabel {
      font-size: 11px;
      color: #999;
      margin-bottom: 3px;
    }

    .colorGroupSwatches {
      display: flex;
      gap: 5px;
    }
  }

  .colorDot {
    display: inline-block;
    width: 22px;
    height: 22px;
    border-radius: 4px;
    cursor: pointer;
    border: 2px solid transparent;
    transition: all 0.15s;
    padding: 0;
    appearance: none;
    background-clip: padding-box;

    &:hover {
      transform: scale(1.15);
    }

    &:focus-visible {
      outline: 2px solid #409eff;
      outline-offset: 2px;
    }

    &.active {
      border-color: #4D73FF;
      box-shadow: 0 0 0 1px #4D73FF;
    }

    &.lightDot {
      border-color: #e4e7ed;
    }

    &.transparentDot {
      background: repeating-conic-gradient(#d9d9d9 0% 25%, #fff 0% 50%) 50% / 8px 8px;
      border-color: #e4e7ed;
    }
  }

  .customColorRow {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-top: 8px;
    margin-top: 6px;
    border-top: 1px solid #f0f0f0;
  }
}
</style>
