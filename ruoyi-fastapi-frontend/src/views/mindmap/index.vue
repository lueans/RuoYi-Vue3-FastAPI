<template>
  <div class="app-container mindmap-index">
    <splitpanes class="default-theme" style="height: calc(100vh - 84px);">
      <!-- 左侧：文件夹目录树 -->
      <pane size="20" min-size="16" max-size="30">
        <div class="dir-tree-container">
          <div class="dir-tree-header">
            <span class="dir-tree-title">脑图目录</span>
            <el-tooltip v-if="listScope === 'owned' && canCreateFolders" content="新建文件夹" placement="top">
              <el-button
                type="primary"
                icon="Plus"
                size="small"
                plain
                aria-label="新建文件夹"
                :loading="operationType === 'folder:add'"
                :disabled="isOperating || folderTreeLoading"
                @click="handleAddFolder(0)"
              />
            </el-tooltip>
          </div>
          <div v-if="listScope === 'owned' && canUseFolders" class="dir-tree-search">
            <el-input
              v-model="folderFilter"
              placeholder="搜索文件夹..."
              clearable
              prefix-icon="Search"
              size="default"
              :disabled="folderTreeLoading"
            />
          </div>
          <div class="dir-tree-body">
            <!-- 全部脑图 -->
            <button
              type="button"
              class="fixed-tree-node"
              :class="{ active: listScope === 'owned' && selectedFolderKey === 'all' }"
              :aria-current="listScope === 'owned' && selectedFolderKey === 'all' ? 'page' : undefined"
              @click="selectFolder('all')"
            >
              <el-icon class="folder-icon"><Files /></el-icon>
              <span class="node-text">我的脑图</span>
            </button>
            <button
              type="button"
              class="fixed-tree-node"
              :class="{ active: listScope === 'shared' }"
              :aria-current="listScope === 'shared' ? 'page' : undefined"
              @click="selectShared"
            >
              <el-icon class="folder-icon"><Share /></el-icon>
              <span class="node-text">与我共享</span>
            </button>
            <button
              type="button"
              class="fixed-tree-node"
              :class="{ active: listScope === 'trash' }"
              :aria-current="listScope === 'trash' ? 'page' : undefined"
              @click="selectTrash"
            >
              <el-icon class="folder-icon"><Delete /></el-icon>
              <span class="node-text">回收站</span>
            </button>
            <!-- 文件夹树 -->
            <div
              v-if="listScope === 'owned' && canUseFolders && folderTreeLoading"
              class="folder-tree-state"
              role="status"
            >
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>正在加载目录…</span>
            </div>
            <div
              v-else-if="listScope === 'owned' && canUseFolders && folderTreeError"
              class="folder-tree-state is-error"
              role="alert"
            >
              <span>{{ folderTreeError }}</span>
              <el-button link type="primary" :disabled="folderTreeLoading" @click="loadFolderTree">
                重新加载
              </el-button>
            </div>
            <el-tree
              v-else-if="listScope === 'owned' && canUseFolders"
              ref="folderTreeRef"
              :data="folderTree"
              :props="{ label: 'name', children: 'children' }"
              :expand-on-click-node="false"
              :filter-node-method="filterFolderNode"
              node-key="id"
              highlight-current
              :draggable="canEditFolders && !isOperating && !folderFilter"
              :allow-drag="allowFolderDrag"
              @node-drop="handleFolderDrop"
              @node-click="handleFolderClick"
            >
              <template #default="{ node, data }">
                <span class="custom-tree-node">
                  <span class="node-label">
                    <el-icon class="folder-icon">
                      <FolderOpened v-if="node.expanded && data.children && data.children.length" />
                      <Folder v-else />
                    </el-icon>
                    <span class="node-text">{{ data.name }}</span>
                  </span>
                  <el-dropdown
                    v-if="canCreateFolders || canEditFolders || canRemoveFolders"
                    class="node-more"
                    trigger="hover"
                    placement="bottom-end"
                    :disabled="isOperating"
                    @command="(cmd) => handleFolderCommand(cmd, data)"
                    @click.stop
                  >
                    <button
                      type="button" class="more-btn"
                      :aria-label="`管理文件夹 ${data.name}`"
                      @click.stop
                    >
                      <el-icon><MoreFilled /></el-icon>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item v-if="canCreateFolders" command="add">
                          <el-icon><Plus /></el-icon>新建子文件夹
                        </el-dropdown-item>
                        <el-dropdown-item v-if="canEditFolders" command="edit">
                          <el-icon><Edit /></el-icon>重命名
                        </el-dropdown-item>
                        <el-dropdown-item v-if="canRemoveFolders" command="delete" divided>
                          <el-icon class="delete-icon"><Delete /></el-icon>
                          <span class="delete-text">删除</span>
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </span>
              </template>
            </el-tree>
            <div
              v-if="listScope === 'owned' && canUseFolders && !folderTreeLoading && !folderTreeError && folderTree.length === 0"
              class="folder-tree-state is-empty"
              role="status"
            >
              暂无自定义文件夹
            </div>
            <div v-if="listScope === 'owned' && !canUseFolders" class="folder-permission-hint">
              当前角色未启用目录管理，脑图仍会保存在“我的脑图”中
            </div>
          </div>
        </div>
      </pane>

      <!-- 右侧：脑图列表 -->
      <pane>
        <div class="main-content">
          <header class="content-overview">
            <div class="content-overview-copy">
              <div class="content-title-row">
                <h1>{{ scopeTitle }}</h1>
                <span v-if="!loading && !listError" class="result-count">{{ total }}</span>
              </div>
              <p>{{ currentLocationText }} · {{ scopeDescription }}</p>
            </div>
            <el-button
              v-if="listScope === 'owned' && canCreateMindmaps"
              type="primary"
              icon="Plus"
              :disabled="isOperating"
              @click="handleAdd"
            >新建脑图</el-button>
          </header>

          <nav class="mobile-scope-bar" aria-label="脑图列表范围">
            <button
              type="button"
              :class="{ active: listScope === 'owned' }"
              :aria-current="listScope === 'owned' ? 'page' : undefined"
              @click="selectFolder('all')"
            >
              <el-icon><Files /></el-icon>
              我的脑图
            </button>
            <button
              type="button"
              :class="{ active: listScope === 'shared' }"
              :aria-current="listScope === 'shared' ? 'page' : undefined"
              @click="selectShared"
            >
              <el-icon><Share /></el-icon>
              与我共享
            </button>
            <button
              type="button"
              :class="{ active: listScope === 'trash' }"
              :aria-current="listScope === 'trash' ? 'page' : undefined"
              @click="selectTrash"
            >
              <el-icon><Delete /></el-icon>
              回收站
            </button>
          </nav>

          <el-form :model="queryParams" ref="queryRef" :inline="true" class="content-toolbar" v-show="showSearch">
            <el-form-item prop="keyword" class="keyword-filter-item">
              <el-input
                v-model="queryParams.keyword"
                placeholder="搜索名称或说明"
                aria-label="文件关键词"
                clearable
                prefix-icon="Search"
                :maxlength="MAX_MINDMAP_FILE_KEYWORD_LENGTH"
                style="width: 260px"
                @keyup.enter="handleQuery"
              />
            </el-form-item>
            <el-form-item prop="status">
              <el-select v-model="queryParams.status" aria-label="脑图状态" placeholder="全部状态" clearable style="width: 120px">
                <el-option label="正常" :value="0" />
                <el-option label="归档" :value="1" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="listScope === 'owned'" prop="tagId">
              <div class="tag-filter-control">
                <el-select
                v-model="queryParams.tagId"
                placeholder="按标签筛选"
                aria-label="脑图标签"
                clearable
                filterable
                remote
                reserve-keyword
                :remote-method="loadTagOptions"
                :loading="tagFilterLoading"
                style="width: 180px"
                >
                  <el-option
                  v-for="tag in tagOptions"
                  :key="tag.id"
                  :label="tag.name"
                  :value="tag.id"
                  >
                    <span
                    class="tag-filter-preview"
                    :style="{
                      backgroundColor: tag.style?.fill || '#eef2ff',
                      color: tag.style?.color || '#334155',
                    }"
                    >{{ tag.name }}</span>
                  </el-option>
                </el-select>
                <div v-if="tagOptionsError" class="tag-filter-error" role="alert">
                  <span>{{ tagOptionsError }}</span>
                  <el-button
                    link
                    type="primary"
                    :disabled="tagFilterLoading"
                    @click="retryTagOptions"
                  >重试</el-button>
                </div>
              </div>
            </el-form-item>
            <el-form-item class="filter-submit-item">
              <el-button type="primary" plain icon="Search" @click="handleQuery">筛选</el-button>
              <el-button v-if="hasActiveFilters" link icon="Refresh" @click="resetQuery">清除</el-button>
            </el-form-item>
            <span class="toolbar-divider" aria-hidden="true"></span>
            <el-form-item class="global-search-item">
              <el-button v-if="canQueryMindmaps" link icon="Search" :disabled="isOperating" @click="globalSearchOpen = true">搜索全部节点</el-button>
            </el-form-item>
          </el-form>

          <div class="content-actions">
            <el-button
              v-if="listScope === 'owned' && canEditMindmaps && selectedActiveMindmaps.length"
              plain
              icon="Box"
              :loading="operationType === 'status:batch:1'"
              :disabled="isOperating"
              @click="handleBatchStatusChange(1)"
            >归档 {{ selectedActiveMindmaps.length }} 张</el-button>
            <el-button
              v-if="listScope === 'owned' && canEditMindmaps && selectedArchivedMindmaps.length"
              type="primary"
              plain
              icon="RefreshLeft"
              :loading="operationType === 'status:batch:0'"
              :disabled="isOperating"
              @click="handleBatchStatusChange(0)"
            >恢复 {{ selectedArchivedMindmaps.length }} 张</el-button>
            <el-button v-if="listScope === 'owned' && canRemoveMindmaps && selectedMindmaps.length" type="danger" plain icon="Delete" :loading="operationType === 'delete:batch'" :disabled="isOperating" @click="handleDelete">删除 {{ selectedMindmaps.length }} 张</el-button>
            <el-button v-if="listScope === 'trash' && canEditMindmaps && selectedMindmaps.length" type="primary" plain icon="RefreshLeft" :loading="operationType === 'restore:batch'" :disabled="isOperating" @click="handleRestore">恢复 {{ selectedMindmaps.length }} 张</el-button>
            <el-button v-if="listScope === 'trash' && canRemoveMindmaps && selectedMindmaps.length" type="danger" plain icon="Delete" :loading="operationType === 'purge:batch'" :disabled="isOperating" @click="handlePermanentDelete">永久删除 {{ selectedMindmaps.length }} 张</el-button>
            <el-button v-if="listScope === 'owned' && canEditMindmaps && selectedFolderKey !== 'all'" plain icon="Rank" :disabled="multiple || isOperating" @click="handleMoveSelected">移动到</el-button>
            <el-badge
              :value="localDrafts.length"
              :hidden="localDrafts.length === 0"
              :max="99"
              class="local-draft-badge"
            >
              <el-button plain :disabled="localDraftsLoading" @click="openLocalDraftCenter">
                <el-icon><Document /></el-icon>
                本地草稿
              </el-button>
            </el-badge>
            <span v-if="listScope === 'shared'" class="shared-list-hint">显示他人授权给你的脑图</span>
            <div class="list-display-controls">
              <el-select
                v-model="sortKey"
                class="list-sort-select"
                aria-label="脑图排序方式"
                :disabled="loading || isOperating"
                @change="handleSortChange"
              >
                <el-option label="最近更新" value="updated-desc" />
                <el-option label="最早更新" value="updated-asc" />
                <el-option label="最近创建" value="created-desc" />
                <el-option label="名称 A–Z" value="name-asc" />
                <el-option label="名称 Z–A" value="name-desc" />
              </el-select>
              <div class="view-mode-switch" role="group" aria-label="脑图展示方式">
                <button
                  type="button"
                  :class="{ active: viewMode === 'grid' }"
                  :aria-pressed="viewMode === 'grid'"
                  aria-label="卡片视图"
                  :disabled="isOperating"
                  @click="setViewMode('grid')"
                >
                  <el-icon><Grid /></el-icon>
                </button>
                <button
                  type="button"
                  :class="{ active: viewMode === 'table' }"
                  :aria-pressed="viewMode === 'table'"
                  aria-label="表格视图"
                  :disabled="isOperating"
                  @click="setViewMode('table')"
                >
                  <el-icon><List /></el-icon>
                </button>
              </div>
            </div>
            <right-toolbar
              v-model:showSearch="showSearch"
              :loading="loading"
              @queryTable="getList"
            />
          </div>

          <div class="content-body">
            <el-table
              v-if="viewMode === 'table' && (loading || mindmapList.length)"
              v-loading="loading"
              class="mindmap-dense-table"
              size="small"
              :data="mindmapList"
              @selection-change="handleSelectionChange"
              style="width: 100%"
            >
              <el-table-column v-if="listScope !== 'shared'" type="selection" width="44" align="center" />
              <el-table-column type="index" label="序号" width="58" align="center" />
              <el-table-column label="名称" align="left" prop="name" min-width="220" :show-overflow-tooltip="true">
                <template #default="scope">
                  <button
                    v-if="listScope !== 'trash'"
                    type="button"
                    class="mindmap-name-button"
                    :disabled="isOperating"
                    :aria-label="`查看脑图详情：${scope.row.name || '未命名脑图'}`"
                    @click="openMindmapDetail(scope.row)"
                  >{{ scope.row.name }}</button>
                  <span v-else>{{ scope.row.name }}</span>
                  <el-tooltip
                    v-if="scope.row.contentState === 'migration_failed'"
                    content="迁移校验未通过，当前仅可只读查看"
                    placement="top"
                  >
                    <el-tag type="warning" size="small" effect="plain" class="migration-state-tag">迁移保护</el-tag>
                  </el-tooltip>
                </template>
              </el-table-column>
              <el-table-column v-if="listScope === 'shared'" label="所有者" align="center" prop="ownerName" min-width="120" :show-overflow-tooltip="true" />
              <el-table-column v-if="listScope === 'shared'" label="我的权限" align="center" width="100">
                <template #default="scope">
                  <el-tag :type="canEditMindmap(scope.row) ? 'success' : 'info'" effect="plain">
                    {{ canEditMindmap(scope.row) ? '可编辑' : '只读' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="节点数" align="center" prop="nodeCount" width="78">
                <template #default="scope">{{ Math.max(0, Number(scope.row.nodeCount) || 0) }}</template>
              </el-table-column>
              <el-table-column label="版本数" align="center" prop="versionCount" width="78" />
              <el-table-column label="状态" align="center" prop="status" width="82">
                <template #default="scope">
                  <el-tag size="small" effect="plain" :type="scope.row.status === 0 ? 'success' : 'info'">
                    {{ scope.row.status === 0 ? '正常' : '归档' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column v-if="listScope !== 'trash'" label="创建时间" align="center" prop="createTime" width="152" class-name="mindmap-optional-column">
                <template #default="scope">
                  <span>{{ parseTime(scope.row.createTime) }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="listScope === 'trash' ? '删除记录时间' : '更新时间'" align="center" prop="updateTime" width="152">
                <template #default="scope">
                  <span>{{ parseTime(scope.row.updateTime) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="190" align="center" fixed="right" class-name="small-padding fixed-width">
                <template #default="scope">
                  <div class="mindmap-table-actions">
                    <template v-if="listScope === 'trash'">
                      <el-button v-if="canEditMindmaps" link type="primary" icon="RefreshLeft" :loading="operationType === `restore:${scope.row.id}`" :disabled="isOperating" @click="handleRestore(scope.row)">恢复</el-button>
                      <el-button v-if="canRemoveMindmaps" link type="danger" icon="Delete" :loading="operationType === `purge:${scope.row.id}`" :disabled="isOperating" @click="handlePermanentDelete(scope.row)">永久删除</el-button>
                    </template>
                    <template v-else>
                      <el-button link type="primary" icon="View" :disabled="isOperating" @click="handleView(scope.row)">查看</el-button>
                      <el-button v-if="canEditMindmap(scope.row)" link type="primary" icon="Edit" :disabled="isOperating" @click="handleEdit(scope.row)">编辑</el-button>
                      <el-dropdown
                        trigger="click"
                        placement="bottom-end"
                        :disabled="isOperating"
                        @command="command => handleMindmapCommand(command, scope.row)"
                      >
                        <el-button link type="primary" :disabled="isOperating" :aria-label="`更多操作：${scope.row.name}`">
                          更多<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                        </el-button>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item v-if="canEditMindmap(scope.row)" command="metadata">
                              <el-icon><Edit /></el-icon>编辑信息
                            </el-dropdown-item>
                            <el-dropdown-item command="copy" :disabled="!canCreateMindmaps">
                              <el-icon><CopyDocument /></el-icon>复制
                            </el-dropdown-item>
                            <el-dropdown-item v-if="isOwnedMindmap(scope.row) && canEditMindmaps" command="move">
                              <el-icon><Rank /></el-icon>移动
                            </el-dropdown-item>
                            <el-dropdown-item v-if="isOwnedMindmap(scope.row) && canEditMindmaps" command="status">
                              <el-icon><RefreshLeft v-if="scope.row.status === 1" /><Box v-else /></el-icon>
                              {{ scope.row.status === 1 ? '恢复' : '归档' }}
                            </el-dropdown-item>
                            <el-dropdown-item v-if="isOwnedMindmap(scope.row) && canRemoveMindmaps" command="delete" divided>
                              <el-icon><Delete /></el-icon><span class="delete-text">删除</span>
                            </el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                    </template>
                  </div>
                </template>
              </el-table-column>
            </el-table>

            <div
              v-else-if="loading || mindmapList.length"
              v-loading="loading"
              class="mindmap-card-grid"
              aria-live="polite"
              :aria-busy="loading"
            >
              <MindmapFileCard
                v-for="item in mindmapList"
                :key="item.id"
                :item="item"
                :scope="listScope"
                :selected="ids.includes(item.id)"
                :selectable="listScope !== 'shared'"
                :busy="isOperating"
                :busy-operation="operationType"
                :can-edit="canEditMindmap(item)"
                :can-create="canCreateMindmaps"
                :can-edit-files="canEditMindmaps"
                :can-remove-files="canRemoveMindmaps"
                :time-text="parseTime(item.updateTime) || ''"
                @selection-change="selected => handleCardSelection(item, selected)"
                @open="openMindmapDetail"
                @view="handleView"
                @edit="handleEdit"
                @command="handleCardCommand"
              />
            </div>

            <div v-if="!loading && !mindmapList.length" class="mindmap-empty-state" :role="listError ? 'alert' : 'status'" aria-live="polite">
              <div class="empty-state-icon" aria-hidden="true">
                <el-icon v-if="listError"><WarningFilled /></el-icon>
                <el-icon v-else-if="hasActiveFilters"><Search /></el-icon>
                <el-icon v-else-if="listScope === 'shared'"><Share /></el-icon>
                <el-icon v-else-if="listScope === 'trash'"><Delete /></el-icon>
                <el-icon v-else><Files /></el-icon>
              </div>
              <h2>{{ listError ? '脑图列表加载失败' : emptyStateTitle }}</h2>
              <p>{{ listError || emptyStateDescription }}</p>
              <el-button v-if="listError" type="primary" icon="Refresh" @click="getList">重新加载</el-button>
              <el-button v-else-if="hasActiveFilters" icon="Refresh" @click="resetQuery">清除筛选</el-button>
              <el-button v-else-if="listScope === 'owned' && canCreateMindmaps" type="primary" icon="Plus" @click="handleAdd">创建第一张脑图</el-button>
            </div>

            <pagination
              v-show="total > 0"
              :total="total"
              v-model:page="queryParams.pageNum"
              v-model:limit="queryParams.pageSize"
              @pagination="handlePagination"
            />
          </div>
        </div>
      </pane>
    </splitpanes>

    <MindmapDetailDrawer
      v-model="detailDrawerOpen"
      :item="detailMindmap"
      :scope="listScope"
      :folder-name="detailFolderName"
      :can-edit="canEditMindmap(detailMindmap)"
      :busy="isOperating"
      :time-text="parseTime(detailMindmap?.updateTime) || ''"
      :create-time-text="parseTime(detailMindmap?.createTime) || ''"
      @view="handleDetailView"
      @edit="handleDetailEdit"
      @metadata="handleMetadata"
    />

    <!-- 新建脑图对话框 -->
    <el-dialog title="新建脑图" v-model="addDialogOpen" width="500px" append-to-body destroy-on-close :close-on-click-modal="!isOperating" :close-on-press-escape="!isOperating" :show-close="!isOperating">
      <el-form ref="addFormRef" :model="addForm" :rules="addRules" label-width="80px" @submit.prevent="submitAdd">
        <el-form-item label="所属目录" prop="folderId">
          <el-tree-select
            v-model="addForm.folderId"
            :data="folderSelectTree"
            :props="{ label: 'name', value: 'id', children: 'children' }"
            value-key="id"
            placeholder="根目录"
            check-strictly
            clearable
            style="width: 100%;"
            :disabled="isOperating"
          />
        </el-form-item>
        <el-form-item label="脑图名称" prop="name">
          <el-input v-model="addForm.name" placeholder="请输入脑图名称" :maxlength="MAX_MINDMAP_NAME_LENGTH" :disabled="isOperating" show-word-limit autofocus />
        </el-form-item>
        <el-form-item label="脑图说明" prop="description">
          <el-input v-model="addForm.description" type="textarea" placeholder="请输入脑图说明（选填）" :maxlength="MAX_MINDMAP_DESCRIPTION_LENGTH" :disabled="isOperating" show-word-limit :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button :disabled="isOperating" @click="addDialogOpen = false">取消</el-button>
          <el-button type="primary" :loading="operationType === 'add'" :disabled="isOperating" @click="submitAdd">创建并编辑</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 新建/重命名文件夹对话框 -->
    <el-dialog :title="folderDialogTitle" v-model="folderDialogOpen" width="500px" append-to-body destroy-on-close :close-on-click-modal="!isOperating" :close-on-press-escape="!isOperating" :show-close="!isOperating">
      <el-form ref="folderFormRef" :model="folderForm" :rules="folderRules" label-width="80px">
        <el-form-item label="上级目录" prop="parentId">
          <el-tree-select
            v-model="folderForm.parentId"
            :data="folderFormSelectTree"
            :props="{ label: 'name', value: 'id', children: 'children' }"
            value-key="id"
            placeholder="请选择上级目录"
            check-strictly
            clearable
            style="width: 100%;"
            :disabled="isOperating"
          />
        </el-form-item>
        <el-form-item label="文件夹名" prop="name">
          <el-input v-model="folderForm.name" placeholder="请输入文件夹名称" :maxlength="MAX_FOLDER_NAME_LENGTH" :disabled="isOperating" show-word-limit />
        </el-form-item>
        <el-form-item label="显示排序" prop="sortOrder">
          <el-input-number v-model="folderForm.sortOrder" controls-position="right" :min="0" :max="MAX_FOLDER_SORT_ORDER" :disabled="isOperating" style="width: 100%;" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button :disabled="isOperating" @click="folderDialogOpen = false">取消</el-button>
          <el-button type="primary" :loading="operationType === folderSubmitOperation" :disabled="isOperating" @click="submitFolder">保存</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 移动脑图对话框 -->
    <el-dialog title="移动脑图到文件夹" v-model="moveDialogOpen" width="420px" append-to-body destroy-on-close :close-on-click-modal="!isOperating" :close-on-press-escape="!isOperating" :show-close="!isOperating">
      <p class="move-dialog-hint">将 {{ moveMindmapIds.length }} 张脑图移动到：</p>
      <el-tree-select
        v-model="moveFolderId"
        :data="moveSelectTree"
        :props="{ label: 'name', value: 'id', children: 'children' }"
        check-strictly
        clearable
        placeholder="根目录"
        style="width: 100%"
        :disabled="isOperating"
      />
      <template #footer>
        <el-button type="primary" :loading="operationType === 'move'" :disabled="isOperating" @click="submitMove">确认移动</el-button>
        <el-button :disabled="isOperating" @click="moveDialogOpen = false">取消</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="localDraftDialogOpen"
      title="本地草稿中心"
      width="680px"
      append-to-body
      class="mindmap-local-draft-dialog"
      @open="loadLocalDrafts"
    >
      <p class="local-draft-intro">
        自动保存失败、离线或协作会话终止时，未同步内容会保存在当前浏览器。下载确认无误后，可手动删除不再需要的草稿。
      </p>
      <div v-if="localDraftsLoading" class="local-draft-state" role="status">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在读取本地草稿…
      </div>
      <div v-else-if="localDraftsError" class="local-draft-state is-error" role="alert">
        <span>{{ localDraftsError }}</span>
        <el-button link type="primary" @click="loadLocalDrafts">重新读取</el-button>
      </div>
      <div v-else-if="localDrafts.length === 0" class="local-draft-empty" role="status">
        <el-icon><Document /></el-icon>
        <strong>暂无本地草稿</strong>
        <span>云端保存成功后，对应草稿会自动清理。</span>
      </div>
      <ul v-else class="local-draft-list" aria-label="本地脑图草稿">
        <li v-for="draft in localDrafts" :key="draft.key" class="local-draft-item">
          <div class="local-draft-copy">
            <strong>{{ draft.name }}</strong>
            <div class="local-draft-meta">
              <span>文件 {{ draft.mindmapId }}</span>
              <span>基于云端版本 {{ draft.contentRevision }}</span>
              <span
                class="local-draft-source"
                :class="{ 'is-legacy': !draft.sessionId }"
              >{{ getMindmapDraftSourceLabel(draft) }}</span>
              <time :datetime="formatDraftDateTime(draft.updatedAt)">
                {{ formatDraftTime(draft.updatedAt) }}
              </time>
            </div>
          </div>
          <div class="local-draft-actions">
            <el-button
              size="small"
              :loading="localDraftBusyKey === `download:${draft.key}`"
              :disabled="Boolean(localDraftBusyKey)"
              :aria-label="`下载本地草稿：${draft.name}，${getMindmapDraftSourceLabel(draft)}`"
              @click="downloadLocalDraft(draft)"
            >
              <el-icon><Download /></el-icon>
              下载 JSON
            </el-button>
            <el-button
              size="small"
              type="primary"
              plain
              :disabled="Boolean(localDraftBusyKey) || !canOpenLocalDraft(draft)"
              :aria-label="`继续处理本地草稿：${draft.name}，${getMindmapDraftSourceLabel(draft)}`"
              @click="continueLocalDraft(draft)"
            >
              继续处理
            </el-button>
            <el-button
              size="small"
              type="danger"
              link
              :loading="localDraftBusyKey === `delete:${draft.key}`"
              :disabled="Boolean(localDraftBusyKey)"
              :aria-label="`删除本地草稿：${draft.name}，${getMindmapDraftSourceLabel(draft)}`"
              @click="deleteLocalDraft(draft)"
            >
              删除
            </el-button>
          </div>
        </li>
      </ul>
      <template #footer>
        <el-button :disabled="Boolean(localDraftBusyKey)" @click="localDraftDialogOpen = false">
          关闭
        </el-button>
      </template>
    </el-dialog>
    <MindmapMetadataDialog
      ref="metadataDialogRef"
      :session-key="listScope"
      @updated="handleMetadataUpdated"
    />
    <GlobalSearchDialog v-model="globalSearchOpen" @open-result="openGlobalSearchResult" />
  </div>
</template>

<script setup name="MindmapManagement">
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listMindmap,
  delMindmap,
  restoreMindmap,
  permanentlyDeleteMindmap,
  copyMindmap,
  addMindmap,
  updateMindmapStatus,
  batchUpdateMindmapStatus,
} from '@/api/mindmap/mindmap'
import { getTag, getTagSuggestions } from '@/api/mindmap/tag'
import { getFolderTree, addFolder, updateFolder, deleteFolder, getFolderDeleteImpact, moveMindmaps, sortFolders } from '@/api/mindmap/folder'
import { FolderOpened, Folder, Files, Share, Plus, Edit, Delete, Rank, MoreFilled, Search, WarningFilled, Loading, ArrowDown, Box, CopyDocument, RefreshLeft, Document, Download, Grid, List } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import GlobalSearchDialog from '@/components/MindMap/GlobalSearchDialog.vue'
import MindmapDetailDrawer from '@/components/MindMap/MindmapDetailDrawer.vue'
import MindmapFileCard from '@/components/MindMap/MindmapFileCard.vue'
import MindmapMetadataDialog from '@/components/MindMap/MindmapMetadataDialog.vue'
import { buildMindmapNodeSearchRoute } from '@/utils/mindmap-route'
import {
  readMindmapListPreferenceState,
  resolveInitialMindmapListViewMode,
  resolveMindmapListSort,
  writeMindmapListPreferences,
} from '@/utils/mindmap-list-preferences'
import {
  buildMindmapListRouteQuery,
  encodeMindmapListReturnState,
  isSameMindmapListRouteQuery,
  isSameMindmapListState,
  parseMindmapListRouteQuery,
} from '@/utils/mindmap-list-route'
import useUserStore from '@/store/modules/user'
import { canUseMindmapFolders, hasAnyPermission, MINDMAP_FILE_PERMISSIONS } from '@/utils/mindmap-permission'
import { validateMindmapTagSearchKeyword } from '@/utils/mindmap-tag-governance'
import { isMindmapContentWritable } from '@/utils/mindmap-content-state'
import { createLatestRequestTracker, isElementDialogDismissal } from '@/utils/mindmap-async'
import { downloadMindmapBackup } from '@/utils/mindmap-backup'
import {
  getMindmapDraftSourceLabel,
  listMindmapDrafts,
  removeMindmapDraft,
} from '@/utils/mindmap-draft'
import {
  formatMindmapDeletePrompt,
  formatMindmapPermanentDeletePrompt,
  formatMindmapArchivePrompt,
  formatMindmapBatchArchivePrompt,
  getMindmapFileErrorMessage,
  MAX_MINDMAP_FILE_KEYWORD_LENGTH,
  MAX_MINDMAP_DESCRIPTION_LENGTH,
  MAX_MINDMAP_NAME_LENGTH,
  validateMindmapDescription,
  validateMindmapName,
} from '@/utils/mindmap-file'
import {
  createMindmapCreationAttemptTracker,
  resolveCreatedMindmapNavigation,
} from '@/utils/mindmap-creation'
import {
  formatFolderDeletePrompt,
  getFolderSubtreeIds,
  getMindmapFolderErrorMessage,
  MAX_FOLDER_NAME_LENGTH,
  MAX_FOLDER_SORT_ORDER,
  normalizeFolderTarget,
  pruneFolderTree,
  validateFolderName,
} from '@/utils/mindmap-folder'

const { proxy } = getCurrentInstance()
const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const initialListPreferenceState = readMindmapListPreferenceState()
const initialListPreferences = initialListPreferenceState.preferences
const initialListRouteState = parseMindmapListRouteQuery(
  route.query,
  initialListPreferences.sortKey,
)

// ─── 文件夹树 ───
const folderTree = ref([])
const folderFilter = ref('')
const folderTreeRef = ref(null)
const folderTreeLoading = ref(false)
const folderTreeError = ref('')
const initialScope = initialListRouteState.scope
const listScope = ref(initialScope) // owned | shared | trash
const selectedFolderKey = ref(
  initialScope === 'owned' ? (initialListRouteState.folderId || 'all') : initialScope,
)

// ─── 脑图列表 ───
const mindmapList = ref([])
const loading = ref(true)
const listError = ref('')
const showSearch = ref(true)
const ids = ref([])
const multiple = ref(true)
const total = ref(0)
const tagSuggestionOptions = ref([])
const tagOptionsLoading = ref(false)
const tagSuggestionsError = ref('')
const selectedTagOption = ref(null)
const selectedTagLoading = ref(false)
const selectedTagError = ref('')
const tagOptions = computed(() => {
  const suggestions = Array.isArray(tagSuggestionOptions.value)
    ? tagSuggestionOptions.value
    : []
  const selected = selectedTagOption.value
  if (!selected?.id) return suggestions
  return [selected, ...suggestions.filter(item => Number(item?.id) !== Number(selected.id))]
})
const operationType = ref('')
const globalSearchOpen = ref(false)
const metadataDialogRef = ref(null)
const detailDrawerOpen = ref(false)
const detailMindmapId = ref(null)
const hasExplicitViewPreference = ref(initialListPreferenceState.hasExplicitViewPreference)
const viewMode = ref(resolveInitialMindmapListViewMode(
  initialListPreferenceState,
  globalThis.matchMedia?.('(max-width: 760px)')?.matches === true,
))
const sortKey = ref(initialListRouteState.sortKey)
const isOperating = computed(() => Boolean(operationType.value))
const selectedMindmaps = computed(() => {
  const selectedIds = new Set(ids.value)
  return mindmapList.value.filter(item => selectedIds.has(item.id))
})
const selectedActiveMindmaps = computed(() => (
  selectedMindmaps.value.filter(item => Number(item.status) === 0)
))
const selectedArchivedMindmaps = computed(() => (
  selectedMindmaps.value.filter(item => Number(item.status) === 1)
))
const detailMindmap = computed(() => {
  const targetId = Number(detailMindmapId.value)
  if (!Number.isSafeInteger(targetId) || targetId <= 0) return null
  return mindmapList.value.find(item => Number(item.id) === targetId) || null
})
const listRequests = createLatestRequestTracker()
const tagRequests = createLatestRequestTracker()
const selectedTagRequests = createLatestRequestTracker()
const folderRequests = createLatestRequestTracker()
const creationRequests = createMindmapCreationAttemptTracker({
  storageKey: 'mindmap:blank-creation-attempt:v1',
})

// ─── 本地草稿恢复中心 ───
const localDraftDialogOpen = ref(false)
const localDrafts = ref([])
const localDraftsLoading = ref(false)
const localDraftsError = ref('')
const localDraftBusyKey = ref('')
let localDraftRequestId = 0

// ─── 文件夹对话框 ───
const folderDialogOpen = ref(false)
const folderDialogTitle = ref('新建文件夹')
const folderFormRef = ref(null)
const folderForm = reactive({ id: null, name: '', parentId: 0, sortOrder: 0 })
const folderRules = {
  name: [{
    validator: (_rule, value, callback) => {
      const result = validateFolderName(value)
      callback(result.valid ? undefined : new Error(result.message))
    },
    trigger: ['blur', 'change'],
  }],
}

// ─── 移动对话框 ───
const moveDialogOpen = ref(false)
const moveFolderId = ref(null)
const moveMindmapIds = ref([])
const moveSourceFolderId = ref(null)

// ─── 新建脑图对话框 ───
const addDialogOpen = ref(false)
const addFormRef = ref(null)
const addForm = reactive({ name: '', description: '', folderId: null })
const addRules = {
  name: [{
    validator: (_rule, value, callback) => {
      const result = validateMindmapName(value)
      callback(result.valid ? undefined : new Error(result.message))
    },
    trigger: ['blur', 'change'],
  }],
  description: [{
    validator: (_rule, value, callback) => {
      const result = validateMindmapDescription(value)
      callback(result.valid ? undefined : new Error(result.message))
    },
    trigger: ['blur', 'change'],
  }],
}

const data = reactive({
  queryParams: {
    pageNum: initialListRouteState.pageNum,
    pageSize: initialListRouteState.pageSize,
    keyword: initialListRouteState.keyword || undefined,
    status: initialListRouteState.status ?? undefined,
    folderId: initialListRouteState.folderId || undefined,
    tagId: initialListRouteState.tagId || undefined,
    ...resolveMindmapListSort(initialListRouteState.sortKey),
  }
})
const { queryParams } = toRefs(data)

// ─── 计算属性 ───
const folderSelectTree = computed(() => [{ id: 0, name: '根目录', children: folderTree.value }])
const folderFormSelectTree = computed(() => [{
  id: 0,
  name: '根目录',
  children: pruneFolderTree(folderTree.value, folderForm.id),
}])
const moveSelectTree = computed(() => [{ id: 0, name: '根目录', children: folderTree.value }])
const canUseFolders = computed(() => canUseMindmapFolders(userStore.permissions))
const canCreateFolders = computed(() => hasAnyPermission(userStore.permissions, ['mindmap:folder:add']))
const canEditFolders = computed(() => hasAnyPermission(userStore.permissions, ['mindmap:folder:edit']))
const canRemoveFolders = computed(() => hasAnyPermission(userStore.permissions, ['mindmap:folder:remove']))
const canCreateMindmaps = computed(() => hasAnyPermission(userStore.permissions, MINDMAP_FILE_PERMISSIONS.add))
const canQueryMindmaps = computed(() => hasAnyPermission(userStore.permissions, MINDMAP_FILE_PERMISSIONS.query))
const canEditMindmaps = computed(() => hasAnyPermission(userStore.permissions, MINDMAP_FILE_PERMISSIONS.edit))
const canRemoveMindmaps = computed(() => hasAnyPermission(userStore.permissions, MINDMAP_FILE_PERMISSIONS.remove))
const folderSubmitOperation = computed(() => folderForm.id ? 'folder:update' : 'folder:add')
const scopeTitle = computed(() => ({
  owned: '我的脑图',
  shared: '与我共享',
  trash: '回收站',
})[listScope.value])
const scopeDescription = computed(() => ({
  owned: '创建、整理并持续完善你的知识地图',
  shared: '集中查看他人授权给你的脑图与当前访问权限',
  trash: '恢复误删的脑图，或永久清理不再需要的内容',
})[listScope.value])
const folderNameById = computed(() => {
  const names = new Map()
  const visit = items => {
    for (const item of items || []) {
      const id = Number(item?.id)
      if (Number.isSafeInteger(id) && id > 0) names.set(id, item.name || `目录 ${id}`)
      visit(item?.children)
    }
  }
  visit(folderTree.value)
  return names
})
const currentLocationText = computed(() => {
  if (listScope.value === 'shared') return '共享给我的文件'
  if (listScope.value === 'trash') return '已删除文件'
  const folderId = Number(queryParams.value.folderId)
  return Number.isSafeInteger(folderId) && folderId > 0
    ? (folderNameById.value.get(folderId) || '当前目录')
    : '全部脑图'
})
const detailFolderName = computed(() => {
  if (listScope.value === 'shared') return '与我共享'
  if (listScope.value === 'trash') return '回收站'
  const folderId = Number(detailMindmap.value?.folderId)
  return Number.isSafeInteger(folderId) && folderId > 0
    ? (folderNameById.value.get(folderId) || '未知目录')
    : '根目录'
})
const appliedListRouteState = computed(() => parseMindmapListRouteQuery(
  route.query,
  initialListPreferences.sortKey,
))
const tagOptionsError = computed(() => selectedTagError.value || tagSuggestionsError.value)
const tagFilterLoading = computed(() => tagOptionsLoading.value || selectedTagLoading.value)
const hasActiveFilters = computed(() => Boolean(
  appliedListRouteState.value.keyword
  || (appliedListRouteState.value.scope !== 'trash' && appliedListRouteState.value.status !== 0)
  || appliedListRouteState.value.tagId
))
const emptyStateTitle = computed(() => {
  if (hasActiveFilters.value) return '没有找到匹配的脑图'
  if (listScope.value === 'shared') return '暂时没有共享给你的脑图'
  if (listScope.value === 'trash') return '回收站是空的'
  if (typeof selectedFolderKey.value === 'number') return '当前文件夹还是空的'
  return '从第一张脑图开始整理想法'
})
const emptyStateDescription = computed(() => {
  if (hasActiveFilters.value) return '尝试调整名称、说明、状态或标签条件，或者清除筛选重新查看。'
  if (listScope.value === 'shared') return '当其他成员授予你查看或编辑权限后，脑图会出现在这里。'
  if (listScope.value === 'trash') return '删除的脑图会保留在这里，直到你永久删除。'
  if (typeof selectedFolderKey.value === 'number') return '可以在当前文件夹中新建脑图，后续也能随时移动到其他目录。'
  return '用脑图拆解问题、组织知识，并邀请成员一起实时协作。'
})

function getCurrentListRouteState() {
  return {
    scope: listScope.value,
    keyword: queryParams.value.keyword?.trim() || '',
    status: queryParams.value.status ?? null,
    folderId: queryParams.value.folderId ?? null,
    tagId: queryParams.value.tagId ?? null,
    pageNum: queryParams.value.pageNum,
    pageSize: queryParams.value.pageSize,
    sortKey: sortKey.value,
  }
}

function syncListRoute() {
  const nextQuery = buildMindmapListRouteQuery(getCurrentListRouteState())
  if (isSameMindmapListRouteQuery(route.query, nextQuery)) return false
  void router.replace({ query: nextQuery })
  return true
}

function applyListRouteState(state) {
  listScope.value = state.scope
  selectedFolderKey.value = state.scope === 'owned' ? (state.folderId || 'all') : state.scope
  queryParams.value.keyword = state.keyword || undefined
  queryParams.value.status = state.status ?? undefined
  queryParams.value.folderId = state.folderId || undefined
  queryParams.value.tagId = state.tagId || undefined
  queryParams.value.pageNum = state.pageNum
  queryParams.value.pageSize = state.pageSize
  sortKey.value = state.sortKey
  const sort = resolveMindmapListSort(state.sortKey)
  queryParams.value.sortField = sort.sortField
  queryParams.value.sortOrder = sort.sortOrder
  ids.value = []
  multiple.value = true
  writeMindmapListPreferences(
    { viewMode: viewMode.value, sortKey: state.sortKey },
    undefined,
    { viewModeExplicit: hasExplicitViewPreference.value },
  )
  nextTick(() => folderTreeRef.value?.setCurrentKey(state.folderId || null))
}

function getListReturnState() {
  return encodeMindmapListReturnState(appliedListRouteState.value)
}

// ─── 文件夹搜索过滤 ───
watch(folderFilter, (val) => {
  folderTreeRef.value?.filter(val)
})

watch(() => appliedListRouteState.value.tagId, (tagId) => {
  void loadSelectedTagOption(tagId)
}, { immediate: true })

function filterFolderNode(value, data) {
  if (!value) return true
  return data.name.indexOf(value) !== -1
}

// ─── 初始化 ───
syncListRoute()
void loadFolderTree()
void loadTagOptions('')
void getList()
void loadLocalDrafts()

onActivated(() => {
  void loadLocalDrafts()
})

watch(canUseFolders, (enabled, previous) => {
  if (enabled && !previous) {
    void loadFolderTree()
  } else if (!enabled) {
    folderRequests.invalidate()
    folderTree.value = []
    folderTreeError.value = ''
    folderTreeLoading.value = false
  }
})

watch(() => route.query, (nextQuery) => {
  const nextState = parseMindmapListRouteQuery(nextQuery, initialListPreferences.sortKey)
  if (isSameMindmapListState(nextState, getCurrentListRouteState())) return
  metadataDialogRef.value?.close?.({ force: true })
  detailDrawerOpen.value = false
  applyListRouteState(nextState)
  void getList()
}, { deep: true })

onBeforeUnmount(() => {
  listRequests.invalidate()
  tagRequests.invalidate()
  selectedTagRequests.invalidate()
  folderRequests.invalidate()
  creationRequests.invalidate()
  localDraftRequestId += 1
})

onDeactivated(() => {
  creationRequests.invalidate()
  metadataDialogRef.value?.close?.({ force: true })
  detailDrawerOpen.value = false
  if (operationType.value === 'add') operationType.value = ''
})

async function loadLocalDrafts() {
  const requestId = ++localDraftRequestId
  if (!userStore.id) {
    localDrafts.value = []
    localDraftsLoading.value = false
    localDraftsError.value = ''
    return false
  }
  localDraftsLoading.value = true
  localDraftsError.value = ''
  try {
    const drafts = await listMindmapDrafts(userStore.id)
    if (requestId !== localDraftRequestId) return false
    localDrafts.value = drafts
    return true
  } catch (error) {
    if (requestId !== localDraftRequestId) return false
    localDrafts.value = []
    localDraftsError.value = error?.message || '读取本地草稿失败'
    return false
  } finally {
    if (requestId === localDraftRequestId) localDraftsLoading.value = false
  }
}

function openLocalDraftCenter() {
  localDraftDialogOpen.value = true
}

function formatDraftDateTime(value) {
  const date = new Date(Number(value))
  return Number.isNaN(date.getTime()) ? '' : date.toISOString()
}

function formatDraftTime(value) {
  const date = new Date(Number(value))
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString()
}

function canOpenLocalDraft(draft) {
  const mindmapId = Number(draft?.mindmapId)
  return Number.isSafeInteger(mindmapId) && mindmapId > 0
}

function continueLocalDraft(draft) {
  if (!canOpenLocalDraft(draft)) return
  localDraftDialogOpen.value = false
  router.push({
    path: '/mindmap/edit',
    query: {
      id: Number(draft.mindmapId),
      draftKey: draft.key,
      returnList: getListReturnState(),
    },
  })
}

async function downloadLocalDraft(draft) {
  if (localDraftBusyKey.value) return
  localDraftBusyKey.value = `download:${draft.key}`
  try {
    const downloaded = downloadMindmapBackup(draft.document, {
      prefix: 'mindmap-local-draft',
      mindmapId: draft.mindmapId,
    })
    if (!downloaded) throw new Error('浏览器未能启动草稿下载')
    ElMessage.success('已发起本地草稿下载，确认文件可用后可删除草稿')
  } catch (error) {
    ElMessage.error(error?.message || '下载本地草稿失败')
  } finally {
    localDraftBusyKey.value = ''
  }
}

async function deleteLocalDraft(draft) {
  if (localDraftBusyKey.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除“${draft.name}”的本地草稿吗？删除后无法从当前浏览器恢复。`,
      '删除本地草稿',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '保留草稿',
        distinguishCancelAndClose: true,
      },
    )
  } catch (error) {
    if (!isElementDialogDismissal(error)) throw error
    return
  }
  localDraftBusyKey.value = `delete:${draft.key}`
  try {
    await removeMindmapDraft(userStore.id, draft.mindmapId, { key: draft.key })
    localDrafts.value = localDrafts.value.filter(item => item.key !== draft.key)
    ElMessage.success('本地草稿已删除')
  } catch (error) {
    ElMessage.error(error?.message || '删除本地草稿失败')
  } finally {
    localDraftBusyKey.value = ''
  }
}

// ==============================
// 文件夹相关
// ==============================

async function loadFolderTree() {
  if (!canUseFolders.value) {
    folderTree.value = []
    folderTreeError.value = ''
    folderTreeLoading.value = false
    return false
  }
  const requestId = folderRequests.begin()
  folderTreeLoading.value = true
  folderTreeError.value = ''
  try {
    const response = await getFolderTree()
    if (!folderRequests.isCurrent(requestId)) return false
    folderTree.value = Array.isArray(response.data) ? response.data : []
    await nextTick()
    folderTreeRef.value?.filter(folderFilter.value)
    return true
  } catch (error) {
    if (!folderRequests.isCurrent(requestId)) return false
    folderTree.value = []
    folderTreeError.value = getMindmapFolderErrorMessage(error, '目录加载失败，请重试')
    return false
  } finally {
    if (folderRequests.isCurrent(requestId)) folderTreeLoading.value = false
  }
}

function selectFolder(key) {
  if (isOperating.value) return
  const folderId = typeof key === 'number' && Number.isSafeInteger(key) && key > 0
    ? key
    : undefined
  listScope.value = 'owned'
  selectedFolderKey.value = folderId || 'all'
  if (queryParams.value.status === undefined) queryParams.value.status = 0
  queryParams.value.folderId = folderId
  queryParams.value.pageNum = 1
  folderTreeRef.value?.setCurrentKey(folderId || null)
  syncListRoute()
  void getList()
}

function selectShared() {
  if (isOperating.value) return
  listScope.value = 'shared'
  selectedFolderKey.value = 'shared'
  queryParams.value.folderId = undefined
  queryParams.value.tagId = undefined
  if (queryParams.value.status === undefined) queryParams.value.status = 0
  queryParams.value.pageNum = 1
  if (folderTreeRef.value) folderTreeRef.value.setCurrentKey(null)
  syncListRoute()
  void getList()
}

function selectTrash() {
  if (isOperating.value) return
  listScope.value = 'trash'
  selectedFolderKey.value = 'trash'
  queryParams.value.folderId = undefined
  queryParams.value.tagId = undefined
  queryParams.value.status = undefined
  queryParams.value.pageNum = 1
  if (folderTreeRef.value) folderTreeRef.value.setCurrentKey(null)
  syncListRoute()
  void getList()
}

function handleFolderClick(data) {
  if (isOperating.value) return
  selectedFolderKey.value = data.id
  queryParams.value.folderId = data.id
  queryParams.value.pageNum = 1
  syncListRoute()
  void getList()
}

function handleFolderCommand(command, data) {
  if (isOperating.value) return
  if (command === 'add' && !canCreateFolders.value) return
  if (command === 'edit' && !canEditFolders.value) return
  if (command === 'delete' && !canRemoveFolders.value) return
  switch (command) {
    case 'add':
      handleAddFolder(data.id)
      break
    case 'edit':
      handleRenameFolder(data)
      break
    case 'delete':
      handleDeleteFolder(data)
      break
  }
}

function handleAddFolder(parentId) {
  if (isOperating.value) return
  folderDialogTitle.value = '新建文件夹'
  folderForm.id = null
  folderForm.name = ''
  folderForm.parentId = parentId || 0
  folderForm.sortOrder = 0
  folderDialogOpen.value = true
  nextTick(() => folderFormRef.value?.clearValidate())
}

function handleRenameFolder(data) {
  if (isOperating.value) return
  folderDialogTitle.value = '编辑文件夹'
  folderForm.id = data.id
  folderForm.name = data.name
  folderForm.parentId = data.parentId
  folderForm.sortOrder = data.sortOrder || 0
  folderDialogOpen.value = true
  nextTick(() => folderFormRef.value?.clearValidate())
}

async function handleDeleteFolder(data) {
  if (isOperating.value) return
  const deletedIds = getFolderSubtreeIds(folderTree.value, data.id)
  operationType.value = `folder:delete:${data.id}`
  try {
    const response = await getFolderDeleteImpact(data.id)
    const impact = response.data || { folderName: data.name }
    await ElMessageBox.confirm(
      formatFolderDeletePrompt(impact),
      '删除文件夹',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
    const deleteResponse = await deleteFolder(data.id)
    if (deletedIds.has(Number(selectedFolderKey.value))) {
      selectedFolderKey.value = 'all'
      queryParams.value.folderId = undefined
      queryParams.value.pageNum = 1
      syncListRoute()
    }
    const movedCount = Number(deleteResponse.data?.movedMindmapCount) || 0
    ElMessage.success(movedCount ? `文件夹已删除，${movedCount} 张脑图已移至根目录` : '文件夹已删除')
    await Promise.all([loadFolderTree(), getList()])
  } catch (error) {
    if (!isElementDialogDismissal(error)) {
      ElMessage.error(getMindmapFolderErrorMessage(error, '删除文件夹失败'))
    }
  } finally {
    operationType.value = ''
  }
}

async function submitFolder() {
  if (isOperating.value) return
  operationType.value = folderSubmitOperation.value
  try {
    await folderFormRef.value?.validate()
  } catch {
    operationType.value = ''
    return
  }
  const nameResult = validateFolderName(folderForm.name)
  if (!nameResult.valid) {
    operationType.value = ''
    return
  }
  try {
    const payload = {
      name: nameResult.value,
      parentId: normalizeFolderTarget(folderForm.parentId) ?? 0,
      sortOrder: Number(folderForm.sortOrder) || 0,
    }
    if (folderForm.id) {
      await updateFolder({ id: folderForm.id, ...payload })
    } else {
      await addFolder(payload)
    }
    ElMessage.success(folderForm.id ? '文件夹已更新' : '文件夹已创建')
    folderDialogOpen.value = false
    await loadFolderTree()
  } catch (error) {
    ElMessage.error(getMindmapFolderErrorMessage(error, folderForm.id ? '更新文件夹失败' : '创建文件夹失败'))
  } finally {
    operationType.value = ''
  }
}

// ─── 拖拽排序 ───
function allowFolderDrag() {
  return canEditFolders.value && !isOperating.value && !folderFilter.value
}

async function handleFolderDrop(draggingNode, dropNode, dropType) {
  if (isOperating.value) return
  let newParentId
  if (dropType === 'inner') {
    newParentId = dropNode.data.id
  } else {
    newParentId = Number(dropNode.parent?.data?.id) || 0
  }

  const siblings = dropType === 'inner'
    ? dropNode.childNodes.map(node => node.data)
    : (dropNode.parent?.childNodes || []).map(node => node.data)

  const items = siblings.map((item, index) => ({
    id: item.id,
    sortOrder: index,
    ...(item.id === draggingNode.data.id ? { parentId: newParentId } : {})
  }))

  if (!items.length) {
    await loadFolderTree()
    return
  }
  operationType.value = 'folder:sort'
  try {
    await sortFolders({ items })
    ElMessage.success('目录排序已保存')
  } catch (error) {
    ElMessage.error(getMindmapFolderErrorMessage(error, '目录排序保存失败'))
  } finally {
    await loadFolderTree()
    operationType.value = ''
  }
}

// ==============================
// 脑图列表相关
// ==============================

function getList() {
  return loadMindmapList(true)
}

async function loadMindmapList(allowPageCorrection) {
  const requestId = listRequests.begin()
  const requestQuery = {
    ...queryParams.value,
    keyword: queryParams.value.keyword?.trim() || undefined,
    accessScope: listScope.value,
  }
  loading.value = true
  listError.value = ''
  try {
    const response = await listMindmap(requestQuery)
    if (!listRequests.isCurrent(requestId)) return false
    const rows = Array.isArray(response.rows) ? response.rows : []
    const responseTotal = Number(response.total) || 0
    const maxPage = Math.max(1, Math.ceil(responseTotal / queryParams.value.pageSize))
    if (allowPageCorrection && queryParams.value.pageNum > maxPage) {
      queryParams.value.pageNum = maxPage
      syncListRoute()
      return loadMindmapList(false)
    }
    mindmapList.value = rows
    total.value = responseTotal
    ids.value = []
    multiple.value = true
    return true
  } catch (error) {
    if (!listRequests.isCurrent(requestId)) return false
    mindmapList.value = []
    total.value = 0
    listError.value = getMindmapFileErrorMessage(error, '请检查网络连接后重新加载')
    return false
  } finally {
    if (listRequests.isCurrent(requestId)) loading.value = false
  }
}

async function loadSelectedTagOption(tagId) {
  const normalizedTagId = Number(tagId)
  if (!Number.isSafeInteger(normalizedTagId) || normalizedTagId <= 0) {
    selectedTagRequests.invalidate()
    selectedTagOption.value = null
    selectedTagLoading.value = false
    selectedTagError.value = ''
    return true
  }
  const requestId = selectedTagRequests.begin()
  selectedTagLoading.value = true
  selectedTagError.value = ''
  try {
    const response = await getTag(normalizedTagId)
    if (
      !selectedTagRequests.isCurrent(requestId)
      || appliedListRouteState.value.tagId !== normalizedTagId
    ) return false
    const tag = response?.data
    if (Number(tag?.id) !== normalizedTagId || !tag?.name) {
      throw new Error('当前标签信息不完整')
    }
    selectedTagOption.value = tag
    return true
  } catch (error) {
    if (!selectedTagRequests.isCurrent(requestId)) return false
    selectedTagOption.value = null
    selectedTagError.value = error?.response?.data?.msg || error?.message || '当前筛选标签加载失败'
    return false
  } finally {
    if (selectedTagRequests.isCurrent(requestId)) selectedTagLoading.value = false
  }
}

function retryTagOptions() {
  void loadTagOptions('')
  void loadSelectedTagOption(appliedListRouteState.value.tagId)
}

async function loadTagOptions(keyword = '') {
  const normalizedKeyword = validateMindmapTagSearchKeyword(String(keyword ?? ''))
  if (!normalizedKeyword.valid) {
    tagRequests.invalidate()
    tagSuggestionOptions.value = []
    tagOptionsLoading.value = false
    tagSuggestionsError.value = normalizedKeyword.message
    return false
  }
  const requestId = tagRequests.begin()
  tagOptionsLoading.value = true
  tagSuggestionsError.value = ''
  try {
    const response = await getTagSuggestions(normalizedKeyword.value || undefined)
    if (!tagRequests.isCurrent(requestId)) return
    tagSuggestionOptions.value = response.data || []
    return true
  } catch (error) {
    if (!tagRequests.isCurrent(requestId)) return
    tagSuggestionOptions.value = []
    tagSuggestionsError.value = error?.response?.data?.msg || error?.message || '标签选项加载失败，请重试'
    return false
  } finally {
    if (tagRequests.isCurrent(requestId)) tagOptionsLoading.value = false
  }
}

function handleQuery() {
  queryParams.value.pageNum = 1
  syncListRoute()
  void getList()
}

function handlePagination() {
  syncListRoute()
  void getList()
}

function persistListPreferences() {
  writeMindmapListPreferences(
    { viewMode: viewMode.value, sortKey: sortKey.value },
    undefined,
    { viewModeExplicit: hasExplicitViewPreference.value },
  )
}

function handleSortChange(nextSortKey) {
  const sort = resolveMindmapListSort(nextSortKey)
  sortKey.value = nextSortKey
  queryParams.value.sortField = sort.sortField
  queryParams.value.sortOrder = sort.sortOrder
  queryParams.value.pageNum = 1
  ids.value = []
  multiple.value = true
  persistListPreferences()
  syncListRoute()
  void getList()
}

function setViewMode(nextViewMode) {
  if (!['grid', 'table'].includes(nextViewMode)) return
  hasExplicitViewPreference.value = true
  if (nextViewMode === viewMode.value) {
    persistListPreferences()
    return
  }
  viewMode.value = nextViewMode
  ids.value = []
  multiple.value = true
  persistListPreferences()
}

function resetQuery() {
  proxy.resetForm('queryRef')
  queryParams.value.keyword = undefined
  queryParams.value.folderId = undefined
  queryParams.value.tagId = undefined
  queryParams.value.status = listScope.value === 'trash' ? undefined : 0
  handleQuery()
}

function handleSelectionChange(selection) {
  ids.value = selection.map(item => item.id)
  multiple.value = !selection.length
}

function handleCardSelection(item, selected) {
  if (listScope.value === 'shared' || isOperating.value) return
  const nextIds = new Set(ids.value)
  if (selected) nextIds.add(item.id)
  else nextIds.delete(item.id)
  ids.value = [...nextIds]
  multiple.value = !ids.value.length
}

function handleCardCommand(command, row) {
  if (command === 'restore') {
    void handleRestore(row)
    return
  }
  if (command === 'purge') {
    void handlePermanentDelete(row)
    return
  }
  handleMindmapCommand(command, row)
}

function handleAdd() {
  addForm.name = ''
  addForm.description = ''
  addForm.folderId = (typeof selectedFolderKey.value === 'number') ? selectedFolderKey.value : null
  addDialogOpen.value = true
}

async function submitAdd() {
  if (isOperating.value) return
  operationType.value = 'add'
  try {
    await addFormRef.value?.validate()
  } catch {
    operationType.value = ''
    return
  }
  const nameResult = validateMindmapName(addForm.name)
  const descriptionResult = validateMindmapDescription(addForm.description)
  if (!nameResult.valid || !descriptionResult.valid) {
    operationType.value = ''
    return
  }
  const mindmapData = {
    name: nameResult.value,
    description: descriptionResult.value || undefined,
    nodeTree: { data: { text: nameResult.value }, children: [] },
  }
  if (addForm.folderId) {
    mindmapData.folderId = addForm.folderId
  }
  let response
  const creationRequestId = creationRequests.begin(JSON.stringify(mindmapData))
  try {
    response = await addMindmap(mindmapData, creationRequestId.idempotencyKey)
  } catch (error) {
    if (!creationRequests.isCurrent(creationRequestId)) return
    ElMessage.error(getMindmapFileErrorMessage(error, '新建脑图失败'))
    operationType.value = ''
    return
  }
  creationRequests.complete(creationRequestId)

  addDialogOpen.value = false
  const navigation = await resolveCreatedMindmapNavigation({
    response,
    navigate: mindmapId => router.push({
      path: '/mindmap/edit',
      query: { id: mindmapId, returnList: getListReturnState() },
    }),
    isCurrent: () => creationRequests.isCurrent(creationRequestId),
  })
  if (navigation.reason === 'session-stale') return
  if (navigation.opened) {
    ElMessage.success('新建成功')
  } else {
    await getList()
    ElMessage.warning(navigation.reason === 'missing-id'
      ? (navigation.error?.message || '脑图已创建，请刷新列表后继续编辑')
      : '脑图已创建，但未能自动打开，请从当前列表继续编辑')
  }
  operationType.value = ''
}

function handleView(row) {
  if (isOperating.value) return
  router.push({
    path: '/mindmap/edit',
    query: {
      id: row.id,
      readonly: '1',
      ...(listScope.value === 'shared' ? { from: 'shared' } : {}),
      returnList: getListReturnState(),
    },
  })
}

function openMindmapDetail(row) {
  if (isOperating.value || listScope.value === 'trash') return
  const id = Number(row?.id)
  if (!Number.isSafeInteger(id) || id <= 0) return
  detailMindmapId.value = id
  detailDrawerOpen.value = true
}

function handleDetailView(row) {
  detailDrawerOpen.value = false
  handleView(row)
}

function handleDetailEdit(row) {
  detailDrawerOpen.value = false
  handleEdit(row)
}

function openGlobalSearchResult(item) {
  const targetRoute = buildMindmapNodeSearchRoute(item, {
    returnList: getListReturnState(),
  })
  if (!targetRoute) return
  globalSearchOpen.value = false
  router.push(targetRoute)
}

function canEditMindmap(row) {
  if (row?.canEdit !== undefined && row?.canEdit !== null) {
    return (row.canEdit === true || row.canEdit === 1)
      && isMindmapContentWritable(row?.contentState)
  }
  return Number(row?.effectivePermission) >= 1
    && Number(row?.status) !== 1
    && isMindmapContentWritable(row?.contentState)
}

function isOwnedMindmap(row) {
  return row?.isOwner === true || row?.accessType === 'owned'
}

function handleMindmapCommand(command, row) {
  if (isOperating.value) return
  if (command === 'copy' && !canCreateMindmaps.value) return
  if (command === 'metadata' && !canEditMindmap(row)) return
  if (
    ['move', 'status'].includes(command)
    && (!isOwnedMindmap(row) || !canEditMindmaps.value)
  ) return
  if (command === 'delete' && (!isOwnedMindmap(row) || !canRemoveMindmaps.value)) return
  const handlers = {
    metadata: handleMetadata,
    copy: handleCopy,
    move: handleMoveOne,
    status: handleStatusChange,
    delete: handleDelete,
  }
  handlers[command]?.(row)
}

function handleMetadata(row) {
  if (isOperating.value || !canEditMindmap(row)) return
  metadataDialogRef.value?.open?.(row)
}

function handleMetadataUpdated(metadata) {
  const current = mindmapList.value.find(item => Number(item.id) === Number(metadata?.id))
  if (!current) return
  current.name = metadata.name
  current.description = metadata.description
  void getList()
}

function handleEdit(row) {
  if (isOperating.value) return
  router.push({
    path: '/mindmap/edit',
    query: {
      id: row.id,
      ...(!canEditMindmap(row) ? { readonly: '1' } : {}),
      ...(listScope.value === 'shared' ? { from: 'shared' } : {}),
      returnList: getListReturnState(),
    }
  })
}

async function handleCopy(row) {
  if (isOperating.value) return
  operationType.value = `copy:${row.id}`
  const creationRequest = creationRequests.begin(`copy:${row.id}`)
  try {
    await copyMindmap(row.id, creationRequest.idempotencyKey)
    creationRequests.complete(creationRequest)
    ElMessage.success('复制成功')
    await getList()
  } catch (error) {
    ElMessage.error(getMindmapFileErrorMessage(error, '复制脑图失败'))
  } finally {
    operationType.value = ''
  }
}

async function handleDelete(row) {
  if (isOperating.value) return
  const selectedIds = row?.id ? [row.id] : [...ids.value]
  const selectedItems = row?.id
    ? [row]
    : mindmapList.value.filter(item => selectedIds.includes(item.id))
  if (!selectedIds.length) return
  operationType.value = row?.id ? `delete:${row.id}` : 'delete:batch'
  try {
    await ElMessageBox.confirm(
      formatMindmapDeletePrompt(selectedItems),
      selectedIds.length === 1 ? '移入回收站' : `移动 ${selectedIds.length} 张脑图`,
      {
        type: 'warning',
        confirmButtonText: '移入回收站',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
    await delMindmap(selectedIds.join(','))
    ElMessage.success('已移入回收站')
    await getList()
  } catch (error) {
    if (!isElementDialogDismissal(error)) {
      ElMessage.error(getMindmapFileErrorMessage(error, '移入回收站失败'))
    }
  } finally {
    operationType.value = ''
  }
}

async function handleRestore(row) {
  if (isOperating.value) return
  const selectedIds = row?.id ? [row.id] : [...ids.value]
  if (!selectedIds.length) return
  operationType.value = row?.id ? `restore:${row.id}` : 'restore:batch'
  try {
    const response = await restoreMindmap(selectedIds.join(','))
    const legacyCount = response.data?.legacyRecoveredIds?.length || 0
    const movedToRootCount = response.data?.movedToRootIds?.length || 0
    if (legacyCount) {
      ElMessage.warning(`已恢复 ${selectedIds.length} 张脑图，其中 ${legacyCount} 张历史记录仅恢复了正文内容`)
    } else if (movedToRootCount) {
      ElMessage.success(`恢复成功；${movedToRootCount} 张脑图因原目录不存在已移到根目录`)
    } else {
      ElMessage.success('恢复成功')
    }
    await getList()
  } catch (error) {
    ElMessage.error(getMindmapFileErrorMessage(error, '恢复脑图失败'))
  } finally {
    operationType.value = ''
  }
}

async function handlePermanentDelete(row) {
  if (isOperating.value) return
  const selectedIds = row?.id ? [row.id] : [...ids.value]
  const selectedItems = row?.id
    ? [row]
    : mindmapList.value.filter(item => selectedIds.includes(item.id))
  if (!selectedIds.length) return
  operationType.value = row?.id ? `purge:${row.id}` : 'purge:batch'
  try {
    await ElMessageBox.confirm(
      formatMindmapPermanentDeletePrompt(selectedItems),
      selectedIds.length === 1 ? '永久删除脑图' : `永久删除 ${selectedIds.length} 张脑图`,
      {
        type: 'error',
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
    await permanentlyDeleteMindmap(selectedIds.join(','))
    ElMessage.success('已永久删除')
    await getList()
  } catch (error) {
    if (!isElementDialogDismissal(error)) {
      ElMessage.error(getMindmapFileErrorMessage(error, '永久删除失败'))
    }
  } finally {
    operationType.value = ''
  }
}

async function handleStatusChange(row) {
  if (isOperating.value || !isOwnedMindmap(row)) return
  const targetStatus = row.status === 1 ? 0 : 1
  operationType.value = `status:${row.id}`
  try {
    if (targetStatus === 1) {
      await ElMessageBox.confirm(
        formatMindmapArchivePrompt(row),
        '归档脑图',
        {
          type: 'warning',
          confirmButtonText: '确认归档',
          cancelButtonText: '取消',
          distinguishCancelAndClose: true,
        },
      )
    }
    await updateMindmapStatus({ id: row.id, status: targetStatus })
    ElMessage.success(targetStatus === 1 ? '脑图已归档' : '脑图已恢复')
    await getList()
  } catch (error) {
    if (!isElementDialogDismissal(error)) {
      ElMessage.error(getMindmapFileErrorMessage(error, targetStatus === 1 ? '归档脑图失败' : '恢复脑图失败'))
    }
  } finally {
    operationType.value = ''
  }
}

async function handleBatchStatusChange(targetStatus) {
  if (isOperating.value || listScope.value !== 'owned') return
  const targetItems = targetStatus === 1
    ? [...selectedActiveMindmaps.value]
    : [...selectedArchivedMindmaps.value]
  if (!targetItems.length) return
  const targetIds = targetItems.map(item => item.id)
  operationType.value = `status:batch:${targetStatus}`
  try {
    if (targetStatus === 1) {
      await ElMessageBox.confirm(
        formatMindmapBatchArchivePrompt(targetItems),
        `归档 ${targetItems.length} 张脑图`,
        {
          type: 'warning',
          confirmButtonText: '确认归档',
          cancelButtonText: '取消',
          distinguishCancelAndClose: true,
        },
      )
    }
    const response = await batchUpdateMindmapStatus({
      mindmapIds: targetIds,
      status: targetStatus,
    })
    const changedCount = response.data?.changedIds?.length ?? targetIds.length
    ElMessage.success(targetStatus === 1
      ? `已归档 ${changedCount} 张脑图`
      : `已恢复 ${changedCount} 张脑图`)
    await getList()
  } catch (error) {
    if (!isElementDialogDismissal(error)) {
      ElMessage.error(getMindmapFileErrorMessage(
        error,
        targetStatus === 1 ? '批量归档脑图失败' : '批量恢复脑图失败',
      ))
    }
  } finally {
    operationType.value = ''
  }
}

// ─── 移动脑图 ───
function handleMoveOne(row) {
  if (isOperating.value) return
  moveMindmapIds.value = [row.id]
  moveSourceFolderId.value = normalizeFolderTarget(row.folderId)
  moveFolderId.value = moveSourceFolderId.value || 0
  moveDialogOpen.value = true
}

function handleMoveSelected() {
  if (isOperating.value || !ids.value.length) return
  moveMindmapIds.value = [...ids.value]
  moveSourceFolderId.value = typeof selectedFolderKey.value === 'number'
    ? selectedFolderKey.value
    : null
  moveFolderId.value = moveSourceFolderId.value || 0
  moveDialogOpen.value = true
}

async function submitMove() {
  if (isOperating.value || !moveMindmapIds.value.length) return
  const targetFolderId = normalizeFolderTarget(moveFolderId.value)
  if (targetFolderId === moveSourceFolderId.value) {
    ElMessage.info('脑图已经位于该文件夹')
    moveDialogOpen.value = false
    return
  }
  operationType.value = 'move'
  try {
    await moveMindmaps({
      mindmapIds: moveMindmapIds.value,
      folderId: targetFolderId,
    })
    ElMessage.success('移动成功')
    moveDialogOpen.value = false
    await getList()
  } catch (error) {
    ElMessage.error(getMindmapFileErrorMessage(error, '移动脑图失败'))
  } finally {
    operationType.value = ''
  }
}
</script>

<style lang="scss" scoped>
.mindmap-index {
  padding: 0;
  background: var(--el-bg-color);

  :deep(.splitpanes__splitter) {
    width: 1px;
    background: var(--el-border-color-lighter);
    &:hover {
      background: #409eff;
    }
  }
}

.tag-filter-preview {
  display: inline-flex;
  align-items: center;
  max-width: 150px;
  padding: 2px 8px;
  overflow: hidden;
  font-size: 12px;
  line-height: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 999px;
}

.tag-filter-control {
  display: flex;
  width: 180px;
  flex-direction: column;
}

.tag-filter-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.4;
}

/* ========== 左侧目录树 ========== */
.dir-tree-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fbfcfe;
  border-right: 0;
}

.dir-tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 52px;
  padding: 0 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-shrink: 0;

  .dir-tree-title {
    font-size: 14px;
    font-weight: 650;
    color: #303133;
    letter-spacing: 0.5px;
  }
}

.dir-tree-search {
  padding: 10px 12px 8px;
  flex-shrink: 0;

  :deep(.el-input__wrapper) {
    border-radius: 6px;
    background: #fff;
    box-shadow: 0 0 0 1px var(--el-border-color-lighter) inset;
  }
}

.dir-tree-body {
  flex: 1;
  overflow: auto;
  padding: 2px 8px 16px;

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: #d4d6d9;
    border-radius: 4px;
  }
  &::-webkit-scrollbar-thumb:hover {
    background: #b0b3b8;
  }

  :deep(.el-tree) {
    background: transparent;

    .el-tree-node__content {
      height: 34px;
      border-radius: 5px;
      margin-bottom: 1px;
      padding-right: 8px;
      transition: background-color 0.15s;

      &:hover {
        background: #e8f0fe;
      }
    }

    .el-tree-node.is-current > .el-tree-node__content {
      background: #d6e4ff;
      font-weight: 500;
    }

    .el-tree-node.is-drop-inner > .el-tree-node__content {
      background: #e8f0fe;
      outline: 1px dashed var(--el-color-primary);
      outline-offset: -1px;
    }

    .el-tree__drop-indicator {
      height: 2px;
      background: var(--el-color-primary);
    }
  }
}

.folder-permission-hint {
  margin: 10px 8px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.folder-tree-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 54px;
  margin: 8px;
  padding: 10px;
  border-radius: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
  text-align: center;

  &.is-error {
    flex-direction: column;
    background: var(--el-color-danger-light-9);
    color: var(--el-color-danger);
  }

  &.is-empty {
    min-height: 40px;
    border: 1px dashed var(--el-border-color);
  }
}

.move-dialog-hint {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.fixed-tree-node {
  display: flex;
  align-items: center;
  width: 100%;
  height: 34px;
  padding: 0 8px 0 16px;
  border: 0;
  border-radius: 5px;
  margin-bottom: 1px;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  text-align: left;
  color: #303133;
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
    font-weight: 500;
  }

  .folder-icon {
    font-size: 16px;
    color: var(--el-color-primary);
    margin-right: 6px;
    flex-shrink: 0;
    opacity: 0.75;
  }

  .node-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.custom-tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  font-size: 13px;
  line-height: 1;

  .node-label {
    display: flex;
    align-items: center;
    overflow: hidden;
    min-width: 0;
    flex: 1;

    .folder-icon {
      font-size: 16px;
      color: var(--el-color-primary);
      margin-right: 6px;
      flex-shrink: 0;
      opacity: 0.75;
    }

    .node-text {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: #303133;
    }
  }

  .node-more {
    flex-shrink: 0;
    margin-left: 4px;
    opacity: 0;
    transition: opacity 0.15s;

    .more-btn {
      display: inline-grid;
      width: 26px;
      height: 26px;
      place-items: center;
      margin: 0;
      border: 0;
      font-size: 16px;
      color: #909399;
      cursor: pointer;
      padding: 2px;
      border-radius: 4px;
      background: transparent;
      font-family: inherit;
      transition: all 0.15s;
      outline: none;

      &:hover {
        color: var(--el-color-primary);
        background: rgba(64, 158, 255, 0.08);
      }

      &:focus-visible {
        color: var(--el-color-primary);
        outline: 2px solid var(--el-color-primary);
        outline-offset: 1px;
      }
    }
  }

  &:hover .node-more,
  &:focus-within .node-more {
    opacity: 1;
  }
}

/* ========== 右侧内容区 ========== */
.main-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  overflow: hidden;
}

.content-overview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  min-height: 62px;
  padding: 0 18px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-shrink: 0;

  .content-overview-copy {
    min-width: 0;
  }

  .content-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  h1 {
    margin: 0;
    color: var(--el-text-color-primary);
    font-size: 17px;
    font-weight: 650;
    line-height: 1.35;
    letter-spacing: -0.3px;
  }

  p {
    margin: 3px 0 0;
    overflow: hidden;
    color: var(--el-text-color-secondary);
    font-size: 13px;
    line-height: 1.4;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.result-count {
  flex-shrink: 0;
  min-width: 22px;
  min-height: 20px;
  padding: 1px 7px;
  border: 0;
  border-radius: 999px;
  background: var(--el-fill-color-extra-light);
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}

.mobile-scope-bar {
  display: none;
}

.content-toolbar {
  display: flex;
  min-height: 52px;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-shrink: 0;

  :deep(.el-form-item) {
    margin-right: 0;
    margin-bottom: 0;
  }

  :deep(.el-input__wrapper),
  :deep(.el-select__wrapper) {
    min-height: 32px;
  }
}

.keyword-filter-item {
  flex: none;
}

.filter-submit-item,
.global-search-item {
  flex: none;
}

.toolbar-divider {
  width: 1px;
  height: 22px;
  margin: 0 2px;
  background: var(--el-border-color-lighter);
}

.content-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  min-height: 48px;
  gap: 6px;
  padding: 7px 18px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-shrink: 0;

  :deep(.el-button + .el-button) {
    margin-left: 0;
  }
}

.local-draft-badge {
  display: inline-flex;

  :deep(.el-badge__content) {
    border-color: var(--el-bg-color);
  }
}

.shared-list-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.list-display-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.list-sort-select {
  width: 128px;

  :deep(.el-select__wrapper) {
    min-height: 34px;
    border-radius: 9px;
  }
}

.view-mode-switch {
  display: inline-flex;
  padding: 3px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-extra-light);

  button {
    display: grid;
    width: 30px;
    height: 28px;
    place-items: center;
    padding: 0;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--el-text-color-secondary);
    cursor: pointer;
    transition: background-color 0.15s, color 0.15s, box-shadow 0.15s;

    &:hover,
    &:focus-visible {
      color: var(--el-color-primary);
    }

    &:focus-visible {
      outline: 2px solid var(--el-color-primary);
      outline-offset: 1px;
    }

    &.active {
      background: var(--el-bg-color);
      color: var(--el-color-primary);
      box-shadow: 0 2px 7px rgba(15, 23, 42, 0.09);
    }

    &:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
  }
}

.migration-state-tag {
  margin-left: 8px;
  vertical-align: middle;
}

.mindmap-name-button {
  max-width: calc(100% - 8px);
  padding: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  cursor: pointer;
  font: inherit;
  font-weight: 500;
  line-height: 26px;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover {
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  &:focus-visible {
    border-radius: 3px;
    outline: 2px solid var(--el-color-primary-light-5);
    outline-offset: 2px;
  }

  &:disabled {
    cursor: wait;
    opacity: 0.55;
  }
}

.mindmap-dense-table {
  :deep(.el-table__header th.el-table__cell) {
    height: 38px;
    padding: 5px 0;
    background: #f7f8fa;
    color: var(--el-text-color-secondary);
    font-size: 12px;
    font-weight: 600;
  }

  :deep(.el-table__body td.el-table__cell) {
    height: 42px;
    padding: 5px 0;
    color: var(--el-text-color-regular);
    font-size: 12px;
  }

  :deep(.el-table__row:hover > td.el-table__cell) {
    background: #f8faff;
  }

  :deep(.el-button.is-link) {
    padding-right: 3px;
    padding-left: 3px;
    font-size: 12px;
  }
}

.mindmap-table-actions {
  display: flex;
  min-height: 24px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  white-space: nowrap;

  :deep(.el-button) {
    min-height: 24px;
    margin: 0;
  }

  :deep(.el-dropdown) {
    display: inline-flex;
    min-height: 24px;
    align-items: center;
    vertical-align: middle;
  }
}

.content-body {
  flex: 1;
  overflow: auto;
  padding: 0 18px 14px;

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: #d4d6d9;
    border-radius: 4px;
  }
}

.mindmap-card-grid {
  display: grid;
  min-height: 220px;
  grid-template-columns: repeat(3, minmax(230px, 1fr));
  gap: 16px;
  padding: 4px 0 18px;
}

.mindmap-empty-state {
  display: flex;
  min-height: 330px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;

  .empty-state-icon {
    display: grid;
    width: 64px;
    height: 64px;
    place-items: center;
    margin-bottom: 18px;
    border: 1px solid color-mix(in srgb, var(--el-color-primary) 16%, transparent);
    border-radius: 20px;
    background: linear-gradient(145deg, var(--el-color-primary-light-9), #fff);
    color: var(--el-color-primary);
    box-shadow: 0 12px 30px rgba(64, 158, 255, 0.1);

    .el-icon {
      font-size: 30px;
    }
  }

  h2 {
    margin: 0;
    color: var(--el-text-color-primary);
    font-size: 17px;
    font-weight: 600;
    line-height: 1.5;
  }

  p {
    max-width: 420px;
    margin: 8px 0 20px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
    line-height: 1.7;
  }
}

@media (max-width: 1280px) {
  .mindmap-dense-table :deep(.mindmap-optional-column) {
    display: none;
  }
}

@media (max-width: 900px) {
  .mindmap-index {
    padding: 8px;

    :deep(.splitpanes__pane:first-child),
    :deep(.splitpanes__splitter) {
      display: none;
    }

    :deep(.splitpanes__pane:last-child) {
      width: 100% !important;
    }
  }

  .content-overview {
    min-height: 60px;
    padding: 0 16px;

    h1 {
      font-size: 17px;
    }

    p {
      max-width: 260px;
    }
  }

  .mobile-scope-bar {
    display: flex;
    gap: 6px;
    padding: 12px 16px 0;

    button {
      display: inline-flex;
      min-height: 36px;
      align-items: center;
      gap: 6px;
      padding: 0 12px;
      border: 1px solid var(--el-border-color);
      border-radius: 9px;
      background: var(--el-bg-color);
      color: var(--el-text-color-regular);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      transition: border-color 0.15s, background-color 0.15s, color 0.15s;

      &:hover,
      &:focus-visible {
        border-color: var(--el-color-primary-light-5);
        color: var(--el-color-primary);
        outline: none;
      }

      &.active {
        border-color: var(--el-color-primary-light-7);
        background: var(--el-color-primary-light-9);
        color: var(--el-color-primary);
        font-weight: 600;
      }
    }
  }

  .content-toolbar {
    min-height: auto;
    flex-wrap: wrap;
    padding: 10px 16px;

    :deep(.el-form-item) {
      width: auto;
    }

    :deep(.el-form-item__content) {
      min-width: 0;
    }

    .keyword-filter-item {
      width: min(100%, 320px);

      :deep(.el-input) {
        width: 100% !important;
      }
    }
  }

  .toolbar-divider {
    display: none;
  }

  .content-actions,
  .content-body {
    padding-right: 16px;
    padding-left: 16px;
  }

  .content-actions {
    flex-wrap: wrap;
  }

  .list-display-controls {
    margin-left: 0;
  }

  .mindmap-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mindmap-empty-state {
    min-height: 280px;
    padding: 36px 16px;
  }
}

@media (max-width: 520px) {
  .content-overview {
    align-items: flex-start;
  }

  .result-count {
    display: none;
  }

  .content-actions :deep(.el-button) {
    margin-left: 0;
  }

  .list-display-controls {
    width: 100%;
    justify-content: space-between;
  }

  .list-sort-select {
    width: min(180px, calc(100% - 82px));
  }

  .mindmap-card-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

<!-- dropdown 弹出层挂载到 body，scoped 无法覆盖，需全局样式 -->
<style lang="scss">
.mindmap-index .el-dropdown-menu__item {
  font-size: 13px;
  padding: 6px 16px;
  line-height: 22px;

  .el-icon {
    margin-right: 8px;
    font-size: 14px;
  }

  .delete-icon {
    color: #f56c6c;
  }

  .delete-text {
    color: #f56c6c;
  }

  &:hover .delete-icon,
  &:hover .delete-text {
    color: #f56c6c;
  }
}

.mindmap-local-draft-dialog {
  .local-draft-intro {
    margin: 0 0 16px;
    padding: 12px 14px;
    border: 1px solid var(--el-color-primary-light-8);
    border-radius: 10px;
    background: var(--el-color-primary-light-9);
    color: var(--el-text-color-regular);
    font-size: 13px;
    line-height: 1.65;
  }

  .local-draft-state,
  .local-draft-empty {
    display: flex;
    min-height: 180px;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--el-text-color-secondary);
  }

  .local-draft-state.is-error {
    flex-direction: column;
    color: var(--el-color-danger);
  }

  .local-draft-empty {
    flex-direction: column;

    > .el-icon {
      margin-bottom: 4px;
      color: var(--el-color-primary-light-5);
      font-size: 38px;
    }

    strong {
      color: var(--el-text-color-primary);
      font-size: 15px;
    }

    span {
      font-size: 13px;
    }
  }

  .local-draft-list {
    display: flex;
    max-height: min(52vh, 520px);
    flex-direction: column;
    gap: 10px;
    margin: 0;
    padding: 0 4px 0 0;
    overflow-y: auto;
    list-style: none;
  }

  .local-draft-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 14px 16px;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 12px;
    background: var(--el-bg-color);
    transition: border-color 0.15s, box-shadow 0.15s;

    &:hover {
      border-color: var(--el-color-primary-light-7);
      box-shadow: 0 8px 22px rgba(31, 35, 41, 0.06);
    }
  }

  .local-draft-copy {
    min-width: 0;

    > strong {
      display: block;
      overflow: hidden;
      color: var(--el-text-color-primary);
      font-size: 14px;
      line-height: 1.5;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .local-draft-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 10px;
    margin-top: 5px;
    color: var(--el-text-color-secondary);
    font-size: 12px;

    span:not(:last-child)::after {
      margin-left: 10px;
      color: var(--el-border-color);
      content: '·';
    }

    .local-draft-source {
      padding: 1px 7px;
      border: 1px solid var(--el-color-primary-light-7);
      border-radius: 999px;
      background: var(--el-color-primary-light-9);
      color: var(--el-color-primary);
      line-height: 18px;

      &.is-legacy {
        border-color: var(--el-border-color-lighter);
        background: var(--el-fill-color-light);
        color: var(--el-text-color-secondary);
      }

      &::after {
        content: none !important;
      }
    }
  }

  .local-draft-actions {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 4px;

    .el-button + .el-button {
      margin-left: 0;
    }
  }
}

@media (max-width: 720px) {
  .mindmap-local-draft-dialog {
    width: calc(100vw - 24px) !important;

    .local-draft-item {
      align-items: stretch;
      flex-direction: column;
      gap: 12px;
    }

    .local-draft-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;

      .el-button {
        width: 100%;
      }

      .el-button:last-child {
        grid-column: 1 / -1;
      }
    }
  }
}
</style>
