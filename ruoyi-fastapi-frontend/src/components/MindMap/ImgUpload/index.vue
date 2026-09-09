<template>
  <div
    class="imgUploadContainer"
    :class="{ disabled: props.disabled }"
    :aria-disabled="props.disabled"
  >
    <div class="imgUploadPanel">
      <div class="upBtn" v-if="!modelValue">
        <input
          type="file"
          accept="image/*"
          id="imgUploadInput"
          aria-label="选择背景图片"
          :disabled="props.disabled"
          @change="onImgUploadInputChange"
        />
        <label
          for="imgUploadInput"
          class="imgUploadInputArea"
          :aria-disabled="props.disabled"
          @dragenter.stop.prevent
          @dragover.stop.prevent
          @drop.stop.prevent="onDrop"
        >点击此处选择图片、或拖动图片到此</label>
      </div>
      <div v-if="modelValue" class="uploadInfoBox">
        <div
          class="previewBox"
          :style="{ backgroundImage: `url('${modelValue}')` }"
        ></div>
        <button
          class="delBtn"
          type="button"
          aria-label="删除背景图片"
          :disabled="props.disabled"
          @click="deleteImg"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { readMindmapImageFile } from '@/utils/mindmap-image'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'change'])
let imageReadToken = 0

function onImgUploadInputChange(e) {
  const input = e.target
  if (props.disabled) {
    input.value = ''
    return
  }
  const file = input.files?.[0]
  if (file) void selectImg(file)
  input.value = ''
}

function onDrop(e) {
  if (props.disabled) return
  const dt = e.dataTransfer
  const file = dt.files && dt.files[0]
  if (file) void selectImg(file)
}

async function selectImg(file) {
  if (props.disabled) return
  const token = ++imageReadToken
  try {
    const result = await readMindmapImageFile(file)
    if (token !== imageReadToken || props.disabled) return
    emit('update:modelValue', result)
    emit('change', result)
  } catch (error) {
    if (token !== imageReadToken) return
    ElMessage.error(error?.message || '读取图片失败')
  }
}

function deleteImg() {
  if (props.disabled) return
  imageReadToken++
  emit('update:modelValue', '')
  emit('change', '')
}

onBeforeUnmount(() => {
  imageReadToken++
})

watch(() => props.disabled, (disabled) => {
  if (disabled) imageReadToken++
})
</script>

<style lang="less" scoped>
@import './style.less';
</style>
