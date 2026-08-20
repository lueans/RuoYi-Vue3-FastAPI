<template>
  <el-dialog
    v-model="visible"
    title="编辑脑图信息"
    width="min(500px, calc(100vw - 32px))"
    append-to-body
    destroy-on-close
    :close-on-click-modal="!submitting"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    @closed="handleClosed"
  >
    <p class="metadata-dialog-intro">
      名称用于列表、分享和搜索识别；说明会展示在文件卡片中，便于成员快速理解内容范围。
    </p>
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="80px"
      @submit.prevent="submit"
    >
      <el-form-item label="名称" prop="name">
        <el-input
          v-model="form.name"
          placeholder="请输入脑图名称"
          :maxlength="MAX_MINDMAP_NAME_LENGTH"
          :disabled="submitting"
          show-word-limit
          autofocus
        />
      </el-form-item>
      <el-form-item label="说明" prop="description">
        <el-input
          v-model="form.description"
          type="textarea"
          placeholder="补充目标、范围或使用说明（选填）"
          :maxlength="MAX_MINDMAP_DESCRIPTION_LENGTH"
          :disabled="submitting"
          :rows="4"
          resize="vertical"
          show-word-limit
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="submitting" @click="close()">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">保存信息</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { updateMindmapMetadata } from '@/api/mindmap/mindmap'
import {
  getMindmapFileErrorMessage,
  MAX_MINDMAP_DESCRIPTION_LENGTH,
  MAX_MINDMAP_NAME_LENGTH,
  validateMindmapDescription,
  validateMindmapName,
} from '@/utils/mindmap-file'

const props = defineProps({
  sessionKey: { type: [String, Number], default: '' },
})
const emit = defineEmits(['updated'])

const visible = ref(false)
const submitting = ref(false)
const formRef = ref(null)
const form = reactive({ id: null, name: '', description: '' })
const initialValue = reactive({ name: '', description: '' })
let requestGeneration = 0

const rules = {
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

function open(file) {
  if (submitting.value) return false
  const id = Number(file?.id)
  if (!Number.isSafeInteger(id) || id <= 0) return false
  requestGeneration += 1
  form.id = id
  form.name = String(file?.name ?? '')
  form.description = String(file?.description ?? '')
  initialValue.name = form.name.trim()
  initialValue.description = form.description.trim()
  visible.value = true
  nextTick(() => formRef.value?.clearValidate?.())
  return true
}

function close({ force = false } = {}) {
  if (submitting.value && !force) return false
  requestGeneration += 1
  submitting.value = false
  visible.value = false
  return true
}

function handleClosed() {
  requestGeneration += 1
  formRef.value?.clearValidate?.()
}

async function submit() {
  if (submitting.value || !visible.value) return false
  submitting.value = true
  try {
    await formRef.value?.validate()
  } catch {
    submitting.value = false
    return false
  }

  const nameResult = validateMindmapName(form.name)
  const descriptionResult = validateMindmapDescription(form.description)
  if (!nameResult.valid || !descriptionResult.valid) {
    submitting.value = false
    return false
  }
  if (
    nameResult.value === initialValue.name
    && descriptionResult.value === initialValue.description
  ) {
    visible.value = false
    submitting.value = false
    return true
  }

  const targetId = form.id
  const generation = ++requestGeneration
  try {
    await updateMindmapMetadata({
      id: targetId,
      name: nameResult.value,
      description: descriptionResult.value || null,
    })
    if (generation !== requestGeneration || !visible.value || form.id !== targetId) return false
    const result = {
      id: targetId,
      name: nameResult.value,
      description: descriptionResult.value,
    }
    initialValue.name = result.name
    initialValue.description = result.description
    emit('updated', result)
    visible.value = false
    ElMessage.success('脑图信息已更新')
    return true
  } catch (error) {
    if (generation === requestGeneration) {
      ElMessage.error(getMindmapFileErrorMessage(error, '更新脑图信息失败'))
    }
    return false
  } finally {
    if (generation === requestGeneration) submitting.value = false
  }
}

watch(() => props.sessionKey, () => {
  close({ force: true })
})

onBeforeUnmount(() => {
  requestGeneration += 1
})

defineExpose({
  open,
  close,
  isOpen: () => visible.value,
})
</script>

<style scoped>
.metadata-dialog-intro {
  margin: -4px 0 18px 80px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 560px) {
  .metadata-dialog-intro {
    margin-left: 0;
  }
}
</style>
