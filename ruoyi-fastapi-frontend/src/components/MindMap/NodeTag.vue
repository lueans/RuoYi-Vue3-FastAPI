<template>
  <el-dialog
    v-model="dialogVisible"
    class="mindmap-node-tag-dialog"
    :title="dialogTitle"
    width="min(560px, calc(100vw - 32px))"
    :z-index="4200"
    :close-on-click-modal="false"
    append-to-body
    @open="onOpen"
    @close="onClose"
  >
    <el-alert
      v-if="targetCount > 1"
      :title="`保存后将用当前标签集合覆盖打开弹窗时选中的 ${targetCount} 个节点；各节点原有差异标签会被替换`"
      type="warning"
      :closable="false"
      show-icon
      class="batchImpact"
    />

    <div class="sectionTitle">选择标签</div>
    <el-input
      ref="inputRef"
      v-model="searchKeyword"
      clearable
      aria-label="搜索标签"
      placeholder="搜索标签名称或 Key"
      :maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH"
      :disabled="isReadonly || creating"
      @input="scheduleSearch"
      @keydown.enter.prevent="handleEnter"
    >
      <template #prefix><el-icon><Search /></el-icon></template>
    </el-input>

    <div class="suggestionPanel">
      <div v-if="loading" class="panelState" role="status" aria-live="polite">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在加载标签…
      </div>
      <div v-else-if="loadError" class="panelState isError" role="alert">
        <span>{{ loadError }}</span>
        <el-button link type="primary" :disabled="isReadonly" @click="loadSuggestions">重新加载</el-button>
      </div>
      <template v-else>
        <div v-if="groupLoadError" class="groupLoadWarning" role="status">
          <span>{{ groupLoadError }}，暂按全部标签展示</span>
          <el-button link type="primary" :disabled="isReadonly" @click="loadTagGroups">重新加载分组</el-button>
        </div>
        <div v-if="groupedSuggestions.length" class="suggestionBrowser">
          <nav class="suggestionGroupSidebar" aria-label="标签分组">
            <button
              v-for="group in groupedSuggestions"
              :key="group.id"
              type="button"
              class="suggestionGroupNavItem"
              :class="{ active: activeGroupId === group.id }"
              :aria-current="activeGroupId === group.id ? 'true' : undefined"
              @click="activeGroupId = group.id"
            >
              <span class="suggestionGroupName">{{ group.name }}</span>
              <span class="suggestionGroupCount">{{ group.tags.length }}</span>
            </button>
          </nav>
          <section
            v-if="activeSuggestionGroup"
            class="suggestionGroupContent"
            role="group"
            :aria-label="`${activeSuggestionGroup.name}，${activeSuggestionGroup.tags.length} 个标签`"
          >
            <div class="suggestionGroupContentHeader">
              <span>{{ activeSuggestionGroup.name }}</span>
              <span>可多选</span>
            </div>
            <div class="suggestionGroupTags">
              <button
                v-for="tag in activeSuggestionGroup.tags"
                :key="tag.id"
                type="button"
                class="suggestionTag"
                :class="{ selected: isSelected(tag.id) }"
                :style="getSuggestionStyle(tag, isSelected(tag.id))"
                :aria-pressed="isSelected(tag.id)"
                :disabled="isReadonly"
                @click="toggleSuggestion(tag)"
              >
                <el-icon v-if="isSelected(tag.id)"><Check /></el-icon>
                <span>{{ tag.name }}</span>
              </button>
            </div>
          </section>
        </div>
        <button
          v-if="canCreate"
          type="button"
          class="createTagButton"
          :disabled="isReadonly || creating"
          @click="createAndSelectTag"
        >
          <el-icon><Plus /></el-icon>
          创建“{{ normalizedKeyword }}”
        </button>
        <div v-if="suggestions.length === 0 && !canCreate" class="panelState">
          {{ normalizedKeyword ? '没有匹配的标签' : '暂无可用标签' }}
        </div>
      </template>
    </div>

    <div class="sectionTitle currentTitle">
      <span>已选标签</span>
      <span class="selectionCount">{{ tagArr.length }}/20</span>
    </div>
    <div v-if="tagArr.length" class="selectedList">
      <el-tag
        v-for="(tag, index) in tagArr"
        :key="getTagIdentity(tag, index)"
        :closable="!isReadonly"
        :color="getTagColor(tag)"
        effect="dark"
        @close="removeTag(index)"
      >
        {{ typeof tag === 'object' ? tag.text : tag }}
      </el-tag>
    </div>
    <div v-else class="emptySelection">暂无标签</div>

    <template #footer>
      <el-button :disabled="creating" @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :disabled="isReadonly || creating" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowRef,
  watch,
} from 'vue'
import { Check, Loading, Plus, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  addTag as createManagedTag,
  getTagSuggestions,
  listTagCategories,
} from '@/api/mindmap/tag'
import useUserStore from '@/store/modules/user'
import { captureMindmapEditTargets } from '@/utils/mindmap-edit-targets'
import {
  MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
  validateMindmapTagDisplayName,
  validateMindmapTagSearchKeyword,
} from '@/utils/mindmap-tag-governance'
import bus from './useEventBus'
import { store } from './useStore'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'

const MAX_NODE_TAG_COUNT = 20
const SEARCH_DEBOUNCE_MS = 250
const tagColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#00bcd4', '#9c27b0', '#ff5722']

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const userStore = useUserStore()
const dialogVisible = ref(false)
const searchKeyword = ref('')
const suggestions = ref([])
const tagGroups = ref([])
const tagGroupsLoaded = ref(false)
const activeGroupId = ref('')
const tagArr = ref([])
const editTargets = shallowRef([])
const inputRef = ref(null)
const loading = ref(false)
const loadError = ref('')
const groupLoadError = ref('')
const groupLoading = ref(false)
const creating = ref(false)
const requestId = ref(0)
const groupRequestId = ref(0)
const dialogSessionId = ref(0)
let searchTimer = null

const { activeNodes } = useMindMapActiveNodes({
  onMindMapChange: invalidateTagDialogForMindMapChange,
})

const isReadonly = computed(() => props.readonly || store.isReadonly)
const targetCount = computed(() => editTargets.value.length)
const dialogTitle = computed(() => targetCount.value > 1
  ? `批量设置标签（${targetCount.value} 个节点）`
  : '标签')
const normalizedKeyword = computed(() => searchKeyword.value.trim())
const groupedSuggestions = computed(() => {
  if (suggestions.value.length === 0) return []
  if (!tagGroupsLoaded.value) {
    return [{ id: 'all', name: groupLoading.value ? '正在读取分组…' : '全部标签', tags: suggestions.value }]
  }

  const knownGroupIds = new Set(tagGroups.value.map(group => Number(group.id)))
  const groups = tagGroups.value
    .map(group => ({
      id: `group-${group.id}`,
      name: group.name,
      tags: suggestions.value.filter(tag => Number(tag.categoryId) === Number(group.id)),
    }))
    .filter(group => group.tags.length > 0)
  const unknownGroupTags = suggestions.value.filter(tag => (
    tag.categoryId != null && !knownGroupIds.has(Number(tag.categoryId))
  ))
  const ungroupedTags = suggestions.value.filter(tag => tag.categoryId == null)

  if (unknownGroupTags.length > 0) {
    groups.push({ id: 'unknown', name: '其他分组', tags: unknownGroupTags })
  }
  if (ungroupedTags.length > 0) {
    groups.push({ id: 'ungrouped', name: '未分组', tags: ungroupedTags })
  }
  return groups
})
const activeSuggestionGroup = computed(() => (
  groupedSuggestions.value.find(group => group.id === activeGroupId.value)
  || groupedSuggestions.value[0]
  || null
))
const canCreate = computed(() => {
  const validation = validateMindmapTagDisplayName(searchKeyword.value)
  if (!validation.valid || tagArr.value.length >= MAX_NODE_TAG_COUNT) return false
  return !suggestions.value.some(tag => tag.name === validation.value)
})

function getTagColor(tag) {
  if (typeof tag === 'object' && tag?.style?.fill) return tag.style.fill
  const text = typeof tag === 'object' ? String(tag?.text || '') : String(tag || '')
  let hash = 0
  for (let index = 0; index < text.length; index += 1) {
    hash = text.charCodeAt(index) + ((hash << 5) - hash)
  }
  return tagColors[Math.abs(hash) % tagColors.length]
}

function getSuggestionStyle(tag, selected) {
  const fill = tag.style?.fill || getTagColor(tag.name)
  const color = tag.style?.color || '#ffffff'
  return {
    backgroundColor: fill === 'transparent' ? '#ffffff' : fill,
    color: color === 'transparent' ? '#303133' : color,
    borderColor: selected ? '#4d73ff' : (fill === 'transparent' ? '#dcdfe6' : fill),
  }
}

function getTagIdentity(tag, index) {
  if (tag && typeof tag === 'object') return tag.tagId || tag.uuid || `${tag.text}-${index}`
  return `${tag}-${index}`
}

function clearSearchTimer() {
  if (searchTimer === null) return
  clearTimeout(searchTimer)
  searchTimer = null
}

async function loadSuggestions() {
  if (!dialogVisible.value) return
  const keyword = validateMindmapTagSearchKeyword(searchKeyword.value)
  if (!keyword.valid) {
    requestId.value += 1
    suggestions.value = []
    loading.value = false
    loadError.value = keyword.message
    return
  }
  const currentRequestId = ++requestId.value
  loading.value = true
  loadError.value = ''
  try {
    const response = await getTagSuggestions(keyword.value || undefined)
    if (currentRequestId !== requestId.value || !dialogVisible.value) return
    suggestions.value = (response.data || []).filter(tag => tag?.id && tag.status === 0)
  } catch (error) {
    if (currentRequestId !== requestId.value || !dialogVisible.value) return
    suggestions.value = []
    loadError.value = error?.message || '标签加载失败，请重试'
  } finally {
    if (currentRequestId === requestId.value) loading.value = false
  }
}

async function loadTagGroups() {
  if (!dialogVisible.value) return
  const currentRequestId = ++groupRequestId.value
  groupLoading.value = true
  groupLoadError.value = ''
  try {
    const response = await listTagCategories()
    if (currentRequestId !== groupRequestId.value || !dialogVisible.value) return
    tagGroups.value = (response.data || []).filter(group => group?.id && group.name)
    tagGroupsLoaded.value = true
  } catch (error) {
    if (currentRequestId !== groupRequestId.value || !dialogVisible.value) return
    tagGroups.value = []
    tagGroupsLoaded.value = false
    groupLoadError.value = error?.message || '标签分组加载失败'
  } finally {
    if (currentRequestId === groupRequestId.value) groupLoading.value = false
  }
}

function scheduleSearch() {
  clearSearchTimer()
  requestId.value += 1
  loadError.value = ''
  loading.value = true
  searchTimer = setTimeout(() => {
    searchTimer = null
    void loadSuggestions()
  }, SEARCH_DEBOUNCE_MS)
}

function isSelected(tagId) {
  return tagArr.value.some(tag => (
    tag && typeof tag === 'object' && Number(tag.tagId) === Number(tagId)
  ))
}

function toNodeTag(tag) {
  const style = { ...(tag.style || {}) }
  return {
    tagId: tag.id,
    uuid: tag.uuid,
    tagKey: tag.tagKey,
    text: tag.name,
    style,
    placement: style.placement,
    align: style.align,
    status: tag.status,
    definitionRevision: tag.definitionRevision,
  }
}

function toggleSuggestion(tag) {
  if (isReadonly.value) return
  const index = tagArr.value.findIndex(item => (
    item && typeof item === 'object' && Number(item.tagId) === Number(tag.id)
  ))
  if (index >= 0) {
    tagArr.value.splice(index, 1)
    return
  }
  if (tagArr.value.length >= MAX_NODE_TAG_COUNT) {
    ElMessage.warning(`最多添加 ${MAX_NODE_TAG_COUNT} 个标签`)
    return
  }
  tagArr.value.push(toNodeTag(tag))
}

async function createAndSelectTag() {
  if (isReadonly.value || creating.value) return
  const validation = validateMindmapTagDisplayName(searchKeyword.value)
  if (!validation.valid) {
    ElMessage.warning(validation.message)
    return
  }
  if (tagArr.value.length >= MAX_NODE_TAG_COUNT) {
    ElMessage.warning(`最多添加 ${MAX_NODE_TAG_COUNT} 个标签`)
    return
  }
  const exactMatch = suggestions.value.find(tag => tag.name === validation.value)
  if (exactMatch) {
    if (!isSelected(exactMatch.id)) toggleSuggestion(exactMatch)
    return
  }

  const sessionId = dialogSessionId.value
  creating.value = true
  try {
    const response = await createManagedTag({
      tagKey: `custom_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
      name: validation.value,
      ownerId: userStore.id,
      style: { fill: getTagColor(validation.value), color: '#ffffff' },
      status: 0,
    })
    if (!isCurrentDialogSession(sessionId)) return
    const tag = response.data
    if (!tag?.id) throw new Error('标签创建后未能读取')
    tagArr.value.push(toNodeTag(tag))
    searchKeyword.value = ''
    await loadSuggestions()
  } catch (error) {
    if (isCurrentDialogSession(sessionId)) {
      ElMessage.error(error?.message || '创建标签失败')
    }
  } finally {
    if (sessionId === dialogSessionId.value) creating.value = false
  }
}

function handleEnter() {
  if (canCreate.value) {
    void createAndSelectTag()
    return
  }
  if (suggestions.value.length === 1 && !isSelected(suggestions.value[0].id)) {
    toggleSuggestion(suggestions.value[0])
  }
}

function handleShow() {
  if (isReadonly.value) return
  editTargets.value = captureMindmapEditTargets(activeNodes.value)
  const node = editTargets.value[0]
  if (!node) return
  tagArr.value = [...(node.getData('tag') || [])]
  searchKeyword.value = ''
  activeGroupId.value = ''
  dialogSessionId.value += 1
  dialogVisible.value = true
  void loadSuggestions()
  void loadTagGroups()
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => inputRef.value?.focus())
}

function onClose() {
  clearSearchTimer()
  dialogSessionId.value += 1
  requestId.value += 1
  groupRequestId.value += 1
  loading.value = false
  groupLoading.value = false
  creating.value = false
  editTargets.value = []
  bus.emit('endTextEdit')
}

function removeTag(index) {
  if (!isReadonly.value) tagArr.value.splice(index, 1)
}

function confirm() {
  if (isReadonly.value || creating.value || editTargets.value.length === 0) return
  editTargets.value.forEach(node => node.setTag(tagArr.value.map(tag => (
    tag && typeof tag === 'object' ? { ...tag, style: { ...(tag.style || {}) } } : tag
  ))))
  dialogVisible.value = false
}

function isCurrentDialogSession(sessionId) {
  return sessionId === dialogSessionId.value && dialogVisible.value && !isReadonly.value
}

function invalidateTagDialogForMindMapChange() {
  clearSearchTimer()
  dialogSessionId.value += 1
  requestId.value += 1
  groupRequestId.value += 1
  loading.value = false
  loadError.value = ''
  groupLoading.value = false
  groupLoadError.value = ''
  suggestions.value = []
  creating.value = false
  editTargets.value = []
  if (dialogVisible.value) dialogVisible.value = false
}

function onManagedTagDefinitionChanged(data) {
  const definition = data?.definition
  if (!definition || !data?.tagId) return
  tagArr.value = tagArr.value.map(tag => (
    tag && typeof tag === 'object' && Number(tag.tagId) === Number(data.tagId)
      ? {
          ...tag,
          ...definition,
          definitionRevision: data.definitionRevision,
          style: { ...(definition.style || {}) },
        }
      : tag
  ))
  if (dialogVisible.value) void loadSuggestions()
}

watch(isReadonly, (readonly) => {
  if (readonly && dialogVisible.value) dialogVisible.value = false
})

watch(groupedSuggestions, (groups) => {
  if (!groups.some(group => group.id === activeGroupId.value)) {
    activeGroupId.value = groups[0]?.id || ''
  }
})

onMounted(() => {
  bus.on('showNodeTag', handleShow)
  bus.on('managed_tag_definition_changed', onManagedTagDefinitionChanged)
})

onBeforeUnmount(() => {
  clearSearchTimer()
  dialogSessionId.value += 1
  requestId.value += 1
  groupRequestId.value += 1
  if (dialogVisible.value) bus.emit('endTextEdit')
  bus.off('showNodeTag', handleShow)
  bus.off('managed_tag_definition_changed', onManagedTagDefinitionChanged)
})
</script>

<style scoped lang="scss">
.sectionTitle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  color: #606266;
  font-size: 13px;
  font-weight: 500;
}

.batchImpact {
  margin-bottom: 12px;
}

.suggestionPanel {
  min-height: 112px;
  max-height: 260px;
  margin-top: 10px;
  padding: 12px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafbfc;
}

.groupLoadWarning {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}

.suggestionBrowser {
  display: grid;
  grid-template-columns: 148px minmax(0, 1fr);
  min-height: 150px;
  max-height: 220px;
  margin: -12px;
}

.suggestionGroupSidebar {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  overflow-y: auto;
  border-right: 1px solid #ebeef5;
  background: #f5f6f8;
}

.suggestionGroupNavItem {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #606266;
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;

  &:hover {
    background: #e9ebef;
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: -2px;
  }

  &.active {
    background: #e8edff;
    color: #3155d9;
    font-weight: 600;
  }
}

.suggestionGroupName {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.suggestionGroupCount {
  min-width: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #ebeef5;
  color: #909399;
  font-size: 11px;
  font-weight: 400;
  line-height: 18px;
  text-align: center;
}

.suggestionGroupContent {
  min-width: 0;
  padding: 12px;
  overflow-y: auto;
  background: #fff;
}

.suggestionGroupContentHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: #303133;
  font-size: 12px;
  font-weight: 600;

  span:last-child {
    color: #909399;
    font-weight: 400;
  }
}

.suggestionGroupTags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.panelState {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  min-height: 78px;
  color: #909399;
  font-size: 13px;

  &.isError {
    flex-wrap: wrap;
    color: var(--el-color-danger);
  }
}

.suggestionTag,
.createTagButton {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  gap: 4px;
  min-height: 28px;
  padding: 3px 10px;
  border: 1px solid;
  border-radius: 6px;
  font: inherit;
  font-size: 12px;
  line-height: 20px;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;

  &:hover {
    transform: translateY(-1px);
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: 2px;
  }
}

.suggestionTag.selected {
  box-shadow: 0 0 0 2px rgb(77 115 255 / 24%);
}

.createTagButton {
  margin-top: 12px;
  border-style: dashed;
  border-color: #8da2fb;
  background: #f2f5ff;
  color: #3155d9;
}

@media (max-width: 520px) {
  .suggestionBrowser {
    grid-template-columns: 116px minmax(0, 1fr);
  }
}

.currentTitle {
  margin-top: 16px;
}

.selectionCount {
  color: #909399;
  font-weight: 400;
}

.selectedList {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 32px;
}

.emptySelection {
  padding: 12px 0;
  color: #909399;
  font-size: 13px;
  text-align: center;
}
</style>

<style>
.el-dialog.mindmap-node-tag-dialog {
  display: flex;
  flex-direction: column;
  max-height: calc(100dvh - 32px);
  margin-top: max(16px, 6vh) !important;
  margin-bottom: 16px;
}

.mindmap-node-tag-dialog .el-dialog__header,
.mindmap-node-tag-dialog .el-dialog__footer {
  flex: none;
}

.mindmap-node-tag-dialog .el-dialog__body {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
</style>
