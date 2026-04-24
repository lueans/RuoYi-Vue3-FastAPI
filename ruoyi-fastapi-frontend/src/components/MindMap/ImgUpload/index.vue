<template>
  <div class="imgUploadContainer">
    <div class="imgUploadPanel">
      <div class="upBtn" v-if="!modelValue">
        <label
          for="imgUploadInput"
          class="imgUploadInputArea"
          @dragenter.stop.prevent
          @dragover.stop.prevent
          @drop.stop.prevent="onDrop"
        >点击此处选择图片、或拖动图片到此</label>
        <input
          type="file"
          accept="image/*"
          id="imgUploadInput"
          @change="onImgUploadInputChange"
        />
      </div>
      <div v-if="modelValue" class="uploadInfoBox">
        <div
          class="previewBox"
          :style="{ backgroundImage: `url('${modelValue}')` }"
        ></div>
        <span class="delBtn" @click="deleteImg">
          <el-icon><Close /></el-icon>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Close } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue', 'change'])

function onImgUploadInputChange(e) {
  const file = e.target.files[0]
  if (file) selectImg(file)
}

function onDrop(e) {
  const dt = e.dataTransfer
  const file = dt.files && dt.files[0]
  if (file) selectImg(file)
}

function selectImg(file) {
  const fr = new FileReader()
  fr.readAsDataURL(file)
  fr.onload = (e) => {
    const result = e.target.result
    emit('update:modelValue', result)
    emit('change', result)
  }
}

function deleteImg() {
  emit('update:modelValue', '')
  emit('change', '')
}
</script>

<style lang="less" scoped>
@import './style.less';
</style>
