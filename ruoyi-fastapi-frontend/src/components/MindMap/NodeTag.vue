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
    <!-- 字段选项面板 -->
    <div class="field-section">
      <div class="sectionTitle">字段标签</div>
      <el-input
        v-model="fieldSearchKeyword"
        class="fieldSearchInput"
        size="small"
        clearable
        aria-label="搜索字段或选项"
        placeholder="搜索字段名称、Key 或选项"
        :maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH"
        :disabled="isReadonly"
        @input="scheduleFieldSearch"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <div v-if="fieldsLoading" class="field-state" role="status" aria-live="polite">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在加载字段标签…
      </div>
      <div v-else-if="fieldsError" class="field-state is-error" role="alert">
        <span>{{ fieldsError }}</span>
        <el-button link type="primary" :disabled="isReadonly || fieldsLoading" @click="loadFields">
          重新加载
        </el-button>
      </div>
      <div v-else-if="fields.length === 0" class="empty-field-tip">
        {{ fieldSearchKeyword.trim() ? '未找到匹配的字段或选项' : '暂无字段，请在标签管理中创建' }}
      </div>
      <div v-for="field in fields" :key="field.id" class="fieldGroup">
        <button
          type="button"
          class="fieldHeader"
          :aria-expanded="expandedFields.includes(field.id)"
          :aria-controls="`field-options-${field.id}`"
          :disabled="isReadonly"
          @click="toggleField(field.id)"
        >
          <el-icon class="fieldArrow" :class="{ expanded: expandedFields.includes(field.id) }">
            <ArrowRight />
          </el-icon>
          <span class="fieldName">{{ field.name }}</span>
          <el-tag size="small" :type="field.selectMode === 'multi' ? 'warning' : 'info'" effect="plain">
            {{ field.selectMode === 'multi' ? '多选' : '单选' }}
          </el-tag>
        </button>
        <div
          :id="`field-options-${field.id}`"
          v-show="expandedFields.includes(field.id)"
          class="fieldOptions"
          role="group"
          :aria-label="`${field.name}选项`"
        >
          <button v-for="opt in field.options" :key="opt.id"
            type="button"
            class="optionBadge"
            :class="{ selected: isOptionSelected(field.id, opt.id) }"
            :style="getOptionBadgeStyle(opt, field, isOptionSelected(field.id, opt.id))"
            :aria-pressed="isOptionSelected(field.id, opt.id)"
            :disabled="isReadonly"
            @click="toggleOption(field, opt)"
          >
            <el-icon v-if="isOptionSelected(field.id, opt.id)" class="checkIcon"><Check /></el-icon>
            {{ opt.name }}
          </button>
          <span v-if="!field.options || field.options.length === 0" class="empty-opt-tip">暂无选项</span>
        </div>
      </div>
      <div
        v-if="!fieldsLoading && !fieldsError && !fieldSearchKeyword.trim() && fields.length >= 30"
        class="fieldSearchHint"
      >
        当前展示前 30 个字段，输入关键词可以搜索更多字段或选项
      </div>
    </div>

    <!-- 手动输入 -->
    <div class="sectionTitle" style="margin-top: 14px">自定义标签</div>
    <div class="tag-input-row">
      <el-input v-model="tagInput" placeholder="输入标签后按 Enter 添加" size="small"
        :maxlength="MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH" show-word-limit
        :disabled="isReadonly || customTagSubmitting" @keydown.enter="addCustomTag" ref="inputRef" />
      <el-button size="small" type="primary" @click="addCustomTag"
        :loading="customTagSubmitting" :disabled="isReadonly || !tagInput.trim() || customTagSubmitting">添加</el-button>
    </div>

    <!-- 当前标签列表 -->
    <div class="sectionTitle" style="margin-top: 14px">当前标签</div>
    <div class="tag-list" v-if="tagArr.length > 0">
      <el-tag v-for="(tag, index) in tagArr" :key="index" :closable="!isReadonly"
        :color="getTagColor(tag)" effect="dark" @close="removeTag(index)"
        style="margin: 4px">
        <template v-if="typeof tag === 'object' && tag.fieldId">
          🏷️ {{ tag.text }}
        </template>
        <template v-else>
          {{ typeof tag === 'object' ? tag.text : tag }}
        </template>
      </el-tag>
    </div>
    <div v-else class="empty-tip">暂无标签</div>

    <template #footer>
      <el-button :disabled="customTagSubmitting" @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :disabled="isReadonly || customTagSubmitting" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ArrowRight, Check, Loading, Search } from '@element-plus/icons-vue'
import bus from './useEventBus'
import { store } from './useStore'
import { getTagFieldSuggestions, getTagSuggestions, addTag as createManagedTag } from '@/api/mindmap/tag'
import { ElMessage } from 'element-plus'
import useUserStore from '@/store/modules/user'
import { captureMindmapEditTargets } from '@/utils/mindmap-edit-targets'
import {
  MAX_MINDMAP_TAG_SEARCH_KEYWORD_LENGTH,
  validateMindmapTagDisplayName,
  validateMindmapTagSearchKeyword,
} from '@/utils/mindmap-tag-governance'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})

const userStore = useUserStore()

const dialogVisible = ref(false)
const tagInput = ref('')
const tagArr = ref([])
const { activeNodes } = useMindMapActiveNodes({
  onMindMapChange: invalidateTagDialogForMindMapChange,
})
const editTargets = shallowRef([])
const inputRef = ref(null)

// 字段数据
const fields = ref([])
const expandedFields = ref([])
const fieldsLoading = ref(false)
const fieldsError = ref('')
const fieldSearchKeyword = ref('')
const fieldRequestId = ref(0)
const dialogSessionId = ref(0)
const customTagSubmitting = ref(false)
const isReadonly = computed(() => props.readonly || store.isReadonly)
const targetCount = computed(() => editTargets.value.length)
const dialogTitle = computed(() => targetCount.value > 1
  ? `批量设置标签（${targetCount.value} 个节点）`
  : '标签')

const tagColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#00bcd4', '#9c27b0', '#ff5722']
const FIELD_SEARCH_DEBOUNCE_MS = 250
let fieldSearchTimer = null

function getTagColor(tag) {
  if (typeof tag === 'object' && tag.style?.fill) return tag.style.fill
  const text = typeof tag === 'object' ? tag.text : tag
  let hash = 0
  for (let i = 0; i < text.length; i++) {
    hash = text.charCodeAt(i) + ((hash << 5) - hash)
  }
  return tagColors[Math.abs(hash) % tagColors.length]
}

// ── 字段加载 ──
async function loadFields() {
  if (isReadonly.value || !dialogVisible.value) return
  const keyword = validateMindmapTagSearchKeyword(fieldSearchKeyword.value)
  if (!keyword.valid) {
    fieldRequestId.value += 1
    fields.value = []
    fieldsLoading.value = false
    fieldsError.value = keyword.message
    return false
  }
  const requestId = ++fieldRequestId.value
  fieldsLoading.value = true
  fieldsError.value = ''
  try {
    const res = await getTagFieldSuggestions(keyword.value || undefined)
    if (requestId !== fieldRequestId.value || !dialogVisible.value || isReadonly.value) return
    const details = (res.data || []).map(field => ({
      ...field,
      id: field.id ?? field.fieldId,
      name: field.name ?? field.fieldName,
    }))
    fields.value = details
    // 默认展开所有字段
    expandedFields.value = details.map(f => f.id)
  } catch (e) {
    if (requestId !== fieldRequestId.value || !dialogVisible.value || isReadonly.value) return
    fields.value = []
    fieldsError.value = e?.message || '字段标签加载失败，请重试'
  } finally {
    if (requestId === fieldRequestId.value) fieldsLoading.value = false
  }
}

function clearFieldSearchTimer() {
  if (fieldSearchTimer === null) return
  clearTimeout(fieldSearchTimer)
  fieldSearchTimer = null
}

function scheduleFieldSearch() {
  clearFieldSearchTimer()
  fieldRequestId.value += 1
  const keyword = validateMindmapTagSearchKeyword(fieldSearchKeyword.value)
  if (!keyword.valid) {
    fields.value = []
    fieldsLoading.value = false
    fieldsError.value = keyword.message
    return
  }
  fieldsLoading.value = true
  fieldsError.value = ''
  fieldSearchTimer = setTimeout(() => {
    fieldSearchTimer = null
    void loadFields()
  }, FIELD_SEARCH_DEBOUNCE_MS)
}

function toggleField(fieldId) {
  const idx = expandedFields.value.indexOf(fieldId)
  if (idx >= 0) {
    expandedFields.value.splice(idx, 1)
  } else {
    expandedFields.value.push(fieldId)
  }
}

// ── 选项选择逻辑 ──
function isOptionSelected(fieldId, optionId) {
  return tagArr.value.some(t =>
    typeof t === 'object' && t.fieldId === fieldId && t.optionId === optionId
  )
}

function toggleOption(field, opt) {
  if (isReadonly.value) return
  const wasSelected = isOptionSelected(field.id, opt.id)
  if (field.selectMode === 'single') {
    // 单选：先移除同字段的其他选项
    tagArr.value = tagArr.value.filter(t =>
      !(typeof t === 'object' && t.fieldId === field.id)
    )
    // 如果点击的是已选中的，则只取消（不重新添加）
    if (wasSelected) return
  } else {
    // 多选：切换
    if (isOptionSelected(field.id, opt.id)) {
      tagArr.value = tagArr.value.filter(t =>
        !(typeof t === 'object' && t.fieldId === field.id && t.optionId === opt.id)
      )
      return
    }
  }

  if (tagArr.value.length >= 20) {
    ElMessage.warning('最多添加 20 个标签')
    return
  }

  // 构建标签对象，注入字段的基础样式
  const fieldStyle = field.style || {}
  tagArr.value.push({
    tagId: opt.tagId || undefined,
    fieldId: field.id,
    optionId: opt.id,
    text: opt.name,
    style: {
      fill: opt.fill || '#409eff',
      color: opt.color || '#ffffff',
      fontSize: fieldStyle.fontSize || 12,
      radius: fieldStyle.radius ?? 3,
      paddingX: fieldStyle.paddingX ?? 8,
    },
    placement: fieldStyle.placement || undefined,
    align: fieldStyle.align || undefined,
  })
}

// ── 选项样式（始终按预览效果展示，选中态用边框+勾选标识） ──
function getOptionBadgeStyle(opt, field, selected) {
  const fieldStyle = field.style || {}
  const fill = opt.fill || '#409eff'
  const color = opt.color || '#fff'
  const isFillTransparent = fill === 'transparent'
  const isColorTransparent = color === 'transparent'
  return {
    backgroundColor: isFillTransparent ? '#f5f5f5' : fill,
    color: isColorTransparent ? '#333333' : color,
    borderColor: selected ? '#4D73FF' : (isFillTransparent ? '#d9d9d9' : fill),
    fontSize: (fieldStyle.fontSize || 12) + 'px',
    borderRadius: (fieldStyle.radius ?? 3) + 'px',
    padding: `2px ${fieldStyle.paddingX ?? 8}px`,
  }
}

// ── 弹窗生命周期 ──
function handleShow() {
  if (isReadonly.value) return
  editTargets.value = captureMindmapEditTargets(activeNodes.value)
  const node = editTargets.value[0]
  if (!node) return
  const tags = node.getData('tag') || []
  tagArr.value = [...tags]
  tagInput.value = ''
  clearFieldSearchTimer()
  fieldSearchKeyword.value = ''
  dialogVisible.value = true
  dialogSessionId.value += 1
  void loadFields()
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => inputRef.value?.focus())
}

function onClose() {
  clearFieldSearchTimer()
  dialogSessionId.value += 1
  fieldRequestId.value += 1
  fieldsLoading.value = false
  customTagSubmitting.value = false
  editTargets.value = []
  bus.emit('endTextEdit')
}

// ── 手动标签 ──
async function addCustomTag() {
  if (isReadonly.value || customTagSubmitting.value) return
  const validation = validateMindmapTagDisplayName(tagInput.value)
  if (!validation.valid) {
    ElMessage.warning(validation.message)
    return
  }
  const text = validation.value
  if (tagArr.value.length >= 20) {
    ElMessage.warning('最多添加 20 个标签')
    return
  }
  const sessionId = dialogSessionId.value
  customTagSubmitting.value = true
  try {
    const suggestionResponse = await getTagSuggestions(text)
    if (!isCurrentDialogSession(sessionId)) return
    let tag = (suggestionResponse.data || []).find(item => item.name === text && item.status !== 2)
    if (!tag) {
      const createResponse = await createManagedTag({
        tagKey: `custom_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
        name: text,
        ownerId: userStore.id,
        style: { fill: getTagColor(text), color: '#ffffff' },
        status: 0,
      })
      if (!isCurrentDialogSession(sessionId)) return
      tag = createResponse.data
    }
    if (!tag) throw new Error('标签创建后未能读取')
    if (!tagArr.value.some(item => typeof item === 'object' && item.tagId === tag.id)) {
      tagArr.value.push({
        tagId: tag.id,
        uuid: tag.uuid,
        tagKey: tag.tagKey,
        text: tag.name,
        style: tag.style || {},
        status: tag.status,
        definitionRevision: tag.definitionRevision,
      })
    }
    tagInput.value = ''
  } catch (error) {
    if (!isCurrentDialogSession(sessionId)) return
    ElMessage.error(error?.message || '创建统一标签失败')
  } finally {
    if (sessionId === dialogSessionId.value) customTagSubmitting.value = false
  }
}

function removeTag(index) {
  if (isReadonly.value) return
  tagArr.value.splice(index, 1)
}

function confirm() {
  if (isReadonly.value || customTagSubmitting.value || editTargets.value.length === 0) return
  editTargets.value.forEach(node => {
    node.setTag([...tagArr.value])
  })
  dialogVisible.value = false
}

function isCurrentDialogSession(sessionId) {
  return Boolean(
    sessionId === dialogSessionId.value &&
    dialogVisible.value &&
    !isReadonly.value
  )
}

function invalidateTagDialogForMindMapChange() {
  clearFieldSearchTimer()
  dialogSessionId.value += 1
  fieldRequestId.value += 1
  fieldsLoading.value = false
  fieldsError.value = ''
  fields.value = []
  expandedFields.value = []
  customTagSubmitting.value = false
  editTargets.value = []
  if (dialogVisible.value) dialogVisible.value = false
}

watch(isReadonly, (readonly) => {
  if (!readonly || !dialogVisible.value) return
  clearFieldSearchTimer()
  dialogSessionId.value += 1
  fieldRequestId.value += 1
  customTagSubmitting.value = false
  dialogVisible.value = false
})

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
  if (dialogVisible.value) void loadFields()
}

onMounted(() => {
  bus.on('showNodeTag', handleShow)
  bus.on('managed_tag_definition_changed', onManagedTagDefinitionChanged)
})
onBeforeUnmount(() => {
  clearFieldSearchTimer()
  dialogSessionId.value += 1
  fieldRequestId.value += 1
  if (dialogVisible.value) bus.emit('endTextEdit')
  bus.off('showNodeTag', handleShow)
  bus.off('managed_tag_definition_changed', onManagedTagDefinitionChanged)
})
</script>

<style scoped lang="scss">
.sectionTitle {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
  margin-bottom: 8px;
}

.batchImpact {
  margin-bottom: 12px;
}

.field-section {
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
  max-height: 320px;
  overflow-y: auto;
}

.fieldSearchInput {
  margin-bottom: 8px;
}

.fieldSearchHint {
  padding: 6px 8px 0;
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}

.empty-field-tip {
  color: #999;
  font-size: 13px;
  padding: 8px 0;
}

.field-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 42px;
  color: #909399;
  font-size: 13px;

  &.is-error {
    flex-wrap: wrap;
    color: var(--el-color-danger);
  }
}

.fieldGroup {
  margin-bottom: 6px;
}

.fieldHeader {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 6px;
  padding: 6px 8px;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  font-family: inherit;
  text-align: left;
  transition: background 0.2s;

  &:hover {
    background: #f5f7fa;
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: -2px;
  }

  .fieldArrow {
    font-size: 12px;
    color: #999;
    transition: transform 0.2s;

    &.expanded {
      transform: rotate(90deg);
    }
  }

  .fieldName {
    font-size: 13px;
    font-weight: 500;
    color: #303133;
    flex: 1;
  }
}

.fieldOptions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 8px 6px 26px;
}

.optionBadge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: 1.5px solid;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  line-height: 1.6;

  &:hover {
    opacity: 0.85;
    transform: scale(1.05);
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: 2px;
  }

  &.selected {
    font-weight: 500;
    border-color: #4D73FF;
    box-shadow: 0 0 0 1.5px #4D73FF;
  }

  .checkIcon {
    font-size: 11px;
  }
}

.empty-opt-tip {
  color: #bbb;
  font-size: 12px;
}

.tag-input-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  min-height: 32px;
}

.empty-tip {
  text-align: center;
  color: #999;
  padding: 12px 0;
  font-size: 13px;
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
