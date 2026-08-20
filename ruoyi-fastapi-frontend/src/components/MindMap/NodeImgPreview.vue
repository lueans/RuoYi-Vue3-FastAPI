<template>
  <el-image-viewer
    v-if="showViewer"
    :url-list="images"
    @close="closeViewer"
    :z-index="10000"
  />
</template>

<script setup>
import { getSafeMindMapImageUrl } from '@mind-map/src/utils/image'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const showViewer = ref(false)
const images = ref([])

function closeViewer() {
  showViewer.value = false
  images.value = []
}

function onImgDblclick(node) {
  const url = getSafeMindMapImageUrl(node?.getImageUrl?.())
  if (url) {
    images.value = [url]
    showViewer.value = true
  }
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) oldMm.off('node_img_dblclick', onImgDblclick)
  closeViewer()
  if (mm) mm.on('node_img_dblclick', onImgDblclick)
}, { immediate: true })

onBeforeUnmount(() => {
  props.mindMap?.off('node_img_dblclick', onImgDblclick)
  closeViewer()
})
</script>
