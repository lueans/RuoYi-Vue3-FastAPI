<template>
  <el-dialog v-model="dialogVisible" title="图片" width="500px" :close-on-click-modal="false">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="URL 地址" name="url">
        <el-input v-model="imgUrl" placeholder="请输入图片 URL 地址" />
      </el-tab-pane>
      <el-tab-pane label="本地上传" name="upload">
        <el-upload
          drag
          :auto-upload="false"
          :show-file-list="false"
          accept="image/*"
          :on-change="onFileChange"
        >
          <div class="upload-area">
            <img v-if="imgBase64" :src="imgBase64" class="preview-img" />
            <template v-else>
              <el-icon style="font-size:40px;color:#c0c4cc"><Plus /></el-icon>
              <div style="margin-top:8px;color:#999;font-size:13px">点击或拖拽上传图片</div>
            </template>
          </div>
        </el-upload>
      </el-tab-pane>
    </el-tabs>
    <el-form-item label="图片标题" style="margin-top:12px">
      <el-input v-model="imgTitle" placeholder="可选" />
    </el-form-item>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button v-if="hasImage" type="danger" text @click="removeImage">移除图片</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { Plus } from '@element-plus/icons-vue'
import bus from './useEventBus'

const dialogVisible = ref(false)
const activeTab = ref('url')
const imgUrl = ref('')
const imgBase64 = ref('')
const imgTitle = ref('')
const activeNodes = ref([])
const hasImage = ref(false)

function handleShow() {
  const node = activeNodes.value[0]
  if (!node) return
  const url = node.getData('image') || ''
  imgTitle.value = node.getData('imageTitle') || ''
  hasImage.value = !!url
  if (url.startsWith('data:')) {
    imgBase64.value = url
    imgUrl.value = ''
    activeTab.value = 'upload'
  } else {
    imgUrl.value = url
    imgBase64.value = ''
    activeTab.value = 'url'
  }
  dialogVisible.value = true
}

function onFileChange(file) {
  const reader = new FileReader()
  reader.onload = (e) => {
    imgBase64.value = e.target.result
  }
  reader.readAsDataURL(file.raw)
}

function confirm() {
  const url = activeTab.value === 'url' ? imgUrl.value : imgBase64.value
  if (!url) {
    dialogVisible.value = false
    return
  }
  const img = new Image()
  img.onload = () => {
    activeNodes.value.forEach(node => {
      node.setImage({ url, title: imgTitle.value, width: img.width, height: img.height })
    })
    dialogVisible.value = false
  }
  img.onerror = () => {
    activeNodes.value.forEach(node => {
      node.setImage({ url, title: imgTitle.value, width: 200, height: 200 })
    })
    dialogVisible.value = false
  }
  img.src = url
}

function removeImage() {
  activeNodes.value.forEach(node => {
    node.setImage(null)
  })
  dialogVisible.value = false
}

function onNodeActive(_, list) {
  activeNodes.value = list ? [...list] : []
}

onMounted(() => {
  bus.on('node_active', onNodeActive)
  bus.on('showNodeImage', handleShow)
})
onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
  bus.off('showNodeImage', handleShow)
})
</script>

<style scoped lang="scss">
.upload-area {
  padding: 20px;
  text-align: center;
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.preview-img {
  max-width: 100%;
  max-height: 200px;
  object-fit: contain;
}
</style>
