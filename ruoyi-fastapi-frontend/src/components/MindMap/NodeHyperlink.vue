<template>
  <el-dialog v-model="dialogVisible" title="超链接" width="500px" :close-on-click-modal="false" append-to-body>
    <el-form label-width="70px">
      <el-form-item label="链接地址">
        <el-input v-model="link" placeholder="请输入链接地址">
          <template #prepend>
            <el-select v-model="protocol" style="width:100px">
              <el-option label="https://" value="https://" />
              <el-option label="http://" value="http://" />
              <el-option label="无" value="" />
            </el-select>
          </template>
        </el-input>
      </el-form-item>
      <el-form-item label="链接名称">
        <el-input v-model="linkTitle" placeholder="可选，链接显示名称" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button v-if="link" type="danger" text @click="removeLink">移除链接</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import bus from './useEventBus'

const dialogVisible = ref(false)
const link = ref('')
const linkTitle = ref('')
const protocol = ref('https://')
const activeNodes = ref([])

function handleShow() {
  const node = activeNodes.value[0]
  if (!node) return
  const href = node.getData('hyperlink') || ''
  linkTitle.value = node.getData('hyperlinkTitle') || ''
  if (href.startsWith('https://')) {
    protocol.value = 'https://'
    link.value = href.replace('https://', '')
  } else if (href.startsWith('http://')) {
    protocol.value = 'http://'
    link.value = href.replace('http://', '')
  } else {
    protocol.value = ''
    link.value = href
  }
  dialogVisible.value = true
}

function confirm() {
  const url = link.value ? protocol.value + link.value : ''
  activeNodes.value.forEach(node => {
    node.setHyperlink(url, linkTitle.value)
  })
  dialogVisible.value = false
}

function removeLink() {
  activeNodes.value.forEach(node => {
    node.setHyperlink('', '')
  })
  dialogVisible.value = false
}

function onNodeActive(_, list) {
  activeNodes.value = list ? [...list] : []
}

onMounted(() => {
  bus.on('node_active', onNodeActive)
  bus.on('showNodeLink', handleShow)
})
onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
  bus.off('showNodeLink', handleShow)
})
</script>
