<template>
  <div class="app-container">
    <el-row :gutter="16">
      <!-- 左侧：字段列表 -->
      <el-col :span="6">
        <el-card shadow="never">
          <template #header>
            <div class="cardHeader">
              <span>标签字段</span>
              <el-button type="primary" size="small" @click="handleAddField">
                <el-icon><Plus /></el-icon>
              </el-button>
            </div>
          </template>
          <div class="fieldList">
            <div
              v-for="field in fields"
              :key="field.id"
              class="fieldItem"
              :class="{ active: selectedFieldId === field.id }"
              @click="selectField(field)"
            >
              <div class="fieldInfo">
                <span class="fieldName">{{ field.name }}</span>
                <el-tag size="small" :type="field.selectMode === 'multi' ? 'warning' : 'info'" effect="plain">
                  {{ field.selectMode === 'multi' ? '多选' : '单选' }}
                </el-tag>
              </div>
              <span class="fieldBadge" v-if="field.ownerId === 0">全局</span>
            </div>
            <div v-if="fields.length === 0" class="emptyTip">暂无字段，点击上方按钮创建</div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：字段编辑 -->
      <el-col :span="18">
        <el-card shadow="never" v-if="selectedField">
          <template #header>
            <div class="cardHeader">
              <span>编辑字段</span>
              <div>
                <el-button type="primary" @click="saveField">保存</el-button>
                <el-button type="danger" plain @click="handleDeleteField">删除</el-button>
              </div>
            </div>
          </template>

          <!-- 基本信息 -->
          <div class="sectionTitle">基本信息</div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="字段Key">
                <el-input v-model="fieldForm.fieldKey" placeholder="英文/数字/下划线" :disabled="!!fieldForm.id" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="名称">
                <el-input v-model="fieldForm.name" placeholder="字段显示名称" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="选择模式">
                <el-radio-group v-model="fieldForm.selectMode">
                  <el-radio value="single">单选</el-radio>
                  <el-radio value="multi">多选</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-col>
            <el-col :span="12" v-if="isAdmin">
              <el-form-item label="范围">
                <el-radio-group v-model="fieldForm.ownerScope">
                  <el-radio value="mine">私有</el-radio>
                  <el-radio value="global">全局</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="描述">
            <el-input v-model="fieldForm.description" type="textarea" :rows="1" placeholder="字段描述（可选）" />
          </el-form-item>

          <!-- 基础样式 -->
          <div class="sectionTitle">基础样式</div>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="字号">
                <el-input-number v-model="styleForm.fontSize" :min="10" :max="24" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="圆角">
                <el-input-number v-model="styleForm.radius" :min="0" :max="20" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="内边距">
                <el-input-number v-model="styleForm.paddingX" :min="0" :max="30" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="位置">
                <el-select v-model="styleForm.placement" style="width: 100%">
                  <el-option label="右侧" value="right" />
                  <el-option label="左侧" value="left" />
                  <el-option label="顶部" value="top" />
                  <el-option label="底部" value="bottom" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="对齐">
                <el-select v-model="styleForm.align" style="width: 100%">
                  <el-option v-for="opt in alignOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 选项管理 -->
          <div class="sectionTitle">
            选项管理
            <el-button type="primary" size="small" style="margin-left: 12px" @click="addOption">
              <el-icon><Plus /></el-icon> 添加选项
            </el-button>
          </div>
          <el-table :data="options" size="small" :header-cell-style="{ background: '#fafafa' }">
            <el-table-column label="Key" width="140">
              <template #default="{ row }">
                <el-input v-model="row.optionKey" size="small" placeholder="option_key"
                  @blur="onOptionChange(row)" />
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="140">
              <template #default="{ row }">
                <el-input v-model="row.name" size="small" placeholder="显示名称"
                  @blur="onOptionChange(row)" />
              </template>
            </el-table-column>
            <el-table-column label="背景色" width="100" align="center">
              <template #default="{ row }">
                <el-popover trigger="click" :width="230" placement="bottom-start">
                  <template #reference>
                    <span class="colorSwatch" :style="{ backgroundColor: row.fill || '#409eff' }" />
                  </template>
                  <div class="colorGroupPanel">
                    <div v-for="group in fillColorGroups" :key="group.label" class="colorGroup">
                      <div class="colorGroupLabel">{{ group.label }}</div>
                      <div class="colorGroupSwatches">
                        <span v-for="c in group.colors" :key="c" class="colorDot"
                          :class="{ active: row.fill === c }" :style="{ backgroundColor: c }"
                          @click="row.fill = c; onOptionChange(row)" />
                      </div>
                    </div>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="文字色" width="100" align="center">
              <template #default="{ row }">
                <el-popover trigger="click" :width="230" placement="bottom-start">
                  <template #reference>
                    <span class="colorSwatch" :style="{ backgroundColor: row.color || '#ffffff', border: '1px solid #dcdfe6' }" />
                  </template>
                  <div class="colorGroupPanel">
                    <div v-for="group in textColorGroups" :key="group.label" class="colorGroup">
                      <div class="colorGroupLabel">{{ group.label }}</div>
                      <div class="colorGroupSwatches">
                        <span v-for="c in group.colors" :key="c" class="colorDot"
                          :class="{ active: row.color === c }" :style="{ backgroundColor: c }"
                          @click="row.color = c; onOptionChange(row)" />
                      </div>
                    </div>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="60" align="center">
              <template #default="{ row, $index }">
                <el-button link type="danger" size="small" @click="removeOption($index, row)">
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
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { Plus, Delete, Document } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listTagFields, getTagFieldDetail, addTagField, updateTagField, deleteTagField,
  addTagFieldOption, updateTagFieldOption, deleteTagFieldOption,
} from '@/api/mindmap/tag'
import useUserStore from '@/store/modules/user'

const userStore = useUserStore()
const isAdmin = computed(() => userStore.id === 1)

// ── 字段列表 ──
const fields = ref([])
const selectedFieldId = ref(null)
const selectedField = ref(null)

async function loadFields() {
  try {
    const res = await listTagFields()
    fields.value = res.data || []
  } catch (e) {
    console.error('加载字段列表失败:', e)
  }
}

async function selectField(field) {
  selectedFieldId.value = field.id
  try {
    const res = await getTagFieldDetail(field.id)
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
    ElMessage.error('加载字段详情失败')
    console.error(e)
  }
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
  selectedFieldId.value = null
  selectedField.value = { id: 'new' }
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
async function saveFieldSilent() {
  const data = {
    fieldKey: fieldForm.fieldKey,
    name: fieldForm.name,
    selectMode: fieldForm.selectMode,
    ownerId: fieldForm.ownerScope === 'global' ? 0 : userStore.id,
    description: fieldForm.description || null,
    style: {
      fontSize: styleForm.fontSize,
      radius: styleForm.radius,
      paddingX: styleForm.paddingX,
      placement: styleForm.placement,
      align: styleForm.align,
    },
  }
  try {
    if (fieldForm.id) {
      data.id = fieldForm.id
      await updateTagField(data)
    } else {
      const res = await addTagField(data)
      // 新建后需要获取 ID
      await loadFields()
      const created = fields.value.find(f => f.fieldKey === fieldForm.fieldKey)
      if (created) {
        fieldForm.id = created.id
        selectedFieldId.value = created.id
        selectedField.value = created
      }
    }
    return true
  } catch (e) {
    ElMessage.error(e.message || '字段保存失败')
    return false
  }
}

async function saveField() {
  if (!fieldForm.fieldKey?.trim()) return ElMessage.warning('请输入字段Key')
  if (!fieldForm.name?.trim()) return ElMessage.warning('请输入字段名称')

  const data = {
    fieldKey: fieldForm.fieldKey,
    name: fieldForm.name,
    selectMode: fieldForm.selectMode,
    ownerId: fieldForm.ownerScope === 'global' ? 0 : userStore.id,
    description: fieldForm.description || null,
    style: {
      fontSize: styleForm.fontSize,
      radius: styleForm.radius,
      paddingX: styleForm.paddingX,
      placement: styleForm.placement,
      align: styleForm.align,
    },
  }

  try {
    if (fieldForm.id) {
      data.id = fieldForm.id
      await updateTagField(data)
      ElMessage.success('字段更新成功')
    } else {
      await addTagField(data)
      ElMessage.success('字段创建成功')
    }
    await loadFields()
    // 重新选中当前字段
    if (fieldForm.id) {
      const f = fields.value.find(f => f.id === fieldForm.id)
      if (f) selectField(f)
    } else {
      // 新建后选中最新的
      const latest = fields.value[fields.value.length - 1]
      if (latest) selectField(latest)
    }
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
}

async function handleDeleteField() {
  if (!fieldForm.id) {
    // 新建未保存，直接清空
    selectedField.value = null
    selectedFieldId.value = null
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除字段「${fieldForm.name}」及其所有选项？`, '提示', { type: 'warning' })
    await deleteTagField(fieldForm.id)
    ElMessage.success('字段删除成功')
    selectedField.value = null
    selectedFieldId.value = null
    loadFields()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

// ── 选项管理 ──
const options = ref([])
let tempIdCounter = 0

function addOption() {
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

function removeOption(index, row) {
  options.value.splice(index, 1)
  if (row.id) {
    // 已有选项，需要调用删除 API
    deleteTagFieldOption(row.id).catch(e => {
      ElMessage.error('删除选项失败')
    })
  }
}

async function onOptionChange(row) {
  if (!row.optionKey?.trim() || !row.name?.trim()) return

  // 字段未保存时，先自动保存字段
  if (!fieldForm.id) {
    if (!fieldForm.fieldKey?.trim() || !fieldForm.name?.trim()) {
      ElMessage.warning('请先填写字段Key和名称')
      return
    }
    const saved = await saveFieldSilent()
    if (!saved) return
  }

  try {
    if (row.id) {
      // 更新已有选项
      await updateTagFieldOption({
        id: row.id,
        fieldId: fieldForm.id,
        optionKey: row.optionKey,
        name: row.name,
        fill: row.fill,
        color: row.color,
        sortOrder: row.sortOrder,
      })
    } else {
      // 创建新选项
      await addTagFieldOption({
        fieldId: fieldForm.id,
        optionKey: row.optionKey,
        name: row.name,
        fill: row.fill,
        color: row.color,
        sortOrder: row.sortOrder,
      })
      // 回填 ID
      // 重新加载详情获取最新数据
      const detail = await getTagFieldDetail(fieldForm.id)
      options.value = (detail.data.options || []).map(o => ({ ...o, _dirty: false }))
    }
  } catch (e) {
    ElMessage.error(e.message || '保存选项失败')
  }
}

// ── 颜色预设 ──
const fillColorGroups = [
  { label: '灰色', colors: ['#F5F5F5', '#D9D9D9', '#B3B3B3', '#666666', '#333333'] },
  { label: '红色', colors: ['#FFCCC7', '#FFA39E', '#FF4D4F', '#CF1322', '#820014'] },
  { label: '橙黄', colors: ['#FFF1B8', '#FFD666', '#FAAD14', '#D48806', '#874D00'] },
  { label: '绿色', colors: ['#D9F7BE', '#95DE64', '#52C41A', '#237804', '#092B00'] },
  { label: '青色', colors: ['#B5F5EC', '#5CDBD3', '#13C2C2', '#006D75', '#002329'] },
  { label: '蓝色', colors: ['#D6E4FF', '#85A5FF', '#4D73FF', '#1D39C4', '#061178'] },
  { label: '紫色', colors: ['#EFDBFF', '#B37FEB', '#722ED1', '#391085', '#120338'] },
]
const textColorGroups = [
  { label: '灰色', colors: ['#FFFFFF', '#D9D9D9', '#666666', '#333333', '#000000'] },
  { label: '彩色', colors: ['#FF4D4F', '#FAAD14', '#52C41A', '#13C2C2', '#4D73FF', '#722ED1'] },
]

// ── 预览样式 ──
function getOptionStyle(opt) {
  return {
    backgroundColor: opt.fill || '#409eff',
    color: opt.color || '#fff',
    fontSize: (styleForm.fontSize || 12) + 'px',
    borderRadius: (styleForm.radius ?? 3) + 'px',
    padding: `2px ${styleForm.paddingX ?? 8}px`,
    display: 'inline-block',
    marginRight: '8px',
  }
}

onMounted(() => {
  loadFields()
})
</script>

<style lang="scss" scoped>
.cardHeader {
  display: flex;
  justify-content: space-between;
  align-items: center;
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

    &:hover {
      background: #f5f7fa;
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

// 颜色选择器
.colorSwatch {
  display: inline-block;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  cursor: pointer;
  vertical-align: middle;
  transition: box-shadow 0.2s;

  &:hover {
    box-shadow: 0 0 0 2px rgba(77, 115, 255, 0.3);
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

    &:hover {
      transform: scale(1.15);
    }

    &.active {
      border-color: #4D73FF;
      box-shadow: 0 0 0 1px #4D73FF;
    }
  }
}
</style>
