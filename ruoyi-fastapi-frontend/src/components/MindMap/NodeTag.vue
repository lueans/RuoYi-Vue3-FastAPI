<template>
  <el-dialog v-model="dialogVisible" title="标签" width="560px" :close-on-click-modal="false"
    @open="onOpen" @close="onClose" append-to-body>
    <!-- 字段选项面板 -->
    <div class="field-section">
      <div class="sectionTitle">字段标签</div>
      <div v-if="fields.length === 0" class="empty-field-tip">暂无字段，请在标签管理中创建</div>
      <div v-for="field in fields" :key="field.id" class="fieldGroup">
        <div class="fieldHeader" @click="toggleField(field.id)">
          <el-icon class="fieldArrow" :class="{ expanded: expandedFields.includes(field.id) }">
            <ArrowRight />
          </el-icon>
          <span class="fieldName">{{ field.name }}</span>
          <el-tag size="small" :type="field.selectMode === 'multi' ? 'warning' : 'info'" effect="plain">
            {{ field.selectMode === 'multi' ? '多选' : '单选' }}
          </el-tag>
        </div>
        <div v-show="expandedFields.includes(field.id)" class="fieldOptions">
          <span v-for="opt in field.options" :key="opt.id"
            class="optionBadge"
            :class="{ selected: isOptionSelected(field.id, opt.id) }"
            :style="getOptionBadgeStyle(opt, field, isOptionSelected(field.id, opt.id))"
            @click="toggleOption(field, opt)"
          >
            <el-icon v-if="isOptionSelected(field.id, opt.id)" class="checkIcon"><Check /></el-icon>
            {{ opt.name }}
          </span>
          <span v-if="!field.options || field.options.length === 0" class="empty-opt-tip">暂无选项</span>
        </div>
      </div>
    </div>

    <!-- 手动输入 -->
    <div class="sectionTitle" style="margin-top: 14px">自定义标签</div>
    <div class="tag-input-row">
      <el-input v-model="tagInput" placeholder="输入标签后按 Enter 添加" size="small"
        @keydown.enter="addTag" ref="inputRef" />
      <el-button size="small" type="primary" @click="addTag" :disabled="!tagInput.trim()">添加</el-button>
    </div>

    <!-- 当前标签列表 -->
    <div class="sectionTitle" style="margin-top: 14px">当前标签</div>
    <div class="tag-list" v-if="tagArr.length > 0">
      <el-tag v-for="(tag, index) in tagArr" :key="index" closable
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
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ArrowRight, Check } from '@element-plus/icons-vue'
import bus from './useEventBus'
import { listTagFields, getTagFieldDetail } from '@/api/mindmap/tag'
import { ElMessage } from 'element-plus'

const dialogVisible = ref(false)
const tagInput = ref('')
const tagArr = ref([])
const activeNodes = ref([])
const inputRef = ref(null)

// 字段数据
const fields = ref([])
const expandedFields = ref([])

const tagColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#00bcd4', '#9c27b0', '#ff5722']

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
  try {
    const res = await listTagFields()
    const fieldList = res.data || []
    // 加载每个字段的详情（含选项）
    const details = await Promise.all(
      fieldList.map(f => getTagFieldDetail(f.id).then(r => r.data))
    )
    fields.value = details
    // 默认展开所有字段
    expandedFields.value = details.map(f => f.id)
  } catch (e) {
    console.error('加载字段列表失败:', e)
    fields.value = []
  }
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
  if (field.selectMode === 'single') {
    // 单选：先移除同字段的其他选项
    tagArr.value = tagArr.value.filter(t =>
      !(typeof t === 'object' && t.fieldId === field.id)
    )
    // 如果点击的是已选中的，则只取消（不重新添加）
    if (isOptionSelected(field.id, opt.id)) return
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
  const node = activeNodes.value[0]
  if (!node) return
  const tags = node.getData('tag') || []
  tagArr.value = [...tags]
  loadFields()
  dialogVisible.value = true
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => inputRef.value?.focus())
}

function onClose() {
  bus.emit('endTextEdit')
}

// ── 手动标签 ──
function addTag() {
  const text = tagInput.value.trim()
  if (!text) return
  if (tagArr.value.length >= 20) {
    ElMessage.warning('最多添加 20 个标签')
    return
  }
  tagArr.value.push(text)
  tagInput.value = ''
}

function removeTag(index) {
  tagArr.value.splice(index, 1)
}

function confirm() {
  activeNodes.value.forEach(node => {
    node.setTag([...tagArr.value])
  })
  dialogVisible.value = false
}

function onNodeActive(_, list) {
  activeNodes.value = list ? [...list] : []
}

onMounted(() => {
  bus.on('node_active', onNodeActive)
  bus.on('showNodeTag', handleShow)
})
onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
  bus.off('showNodeTag', handleShow)
})
</script>

<style scoped lang="scss">
.sectionTitle {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
  margin-bottom: 8px;
}

.field-section {
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
  max-height: 320px;
  overflow-y: auto;
}

.empty-field-tip {
  color: #999;
  font-size: 13px;
  padding: 8px 0;
}

.fieldGroup {
  margin-bottom: 6px;
}

.fieldHeader {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.2s;

  &:hover {
    background: #f5f7fa;
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
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  line-height: 1.6;

  &:hover {
    opacity: 0.85;
    transform: scale(1.05);
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
