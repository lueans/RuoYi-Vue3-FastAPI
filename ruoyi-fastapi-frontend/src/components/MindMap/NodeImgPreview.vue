<template>
  <el-image-viewer
    v-if="showViewer"
    :url-list="images"
    @close="showViewer = false"
    :z-index="10000"
  />
</template>

<script setup>
const props = defineProps({
  mindMap: { type: Object, default: null }
})

const showViewer = ref(false)
const images = ref([])

function onImgDblclick(node) {
  const url = node.getImageUrl?.()
  if (url) {
    images.value = [url]
    showViewer.value = true
  }
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) oldMm.off('node_img_dblclick', onImgDblclick)
  if (mm) mm.on('node_img_dblclick', onImgDblclick)
}, { immediate: true })

onBeforeUnmount(() => {
  props.mindMap?.off('node_img_dblclick', onImgDblclick)
})
</script>
