<template>
  <div class="mind-map-page">
    <Toolbar v-if="!isZenMode" />
    <div class="mind-map-body">
      <Edit ref="editRef" />
    </div>
    <NavigatorToolbar v-if="!isZenMode" :mindMap="mindMapInstance" />
  </div>
</template>

<script setup name="MindMapEditor">
import Toolbar from '@/components/MindMap/Toolbar.vue'
import Edit from '@/components/MindMap/Edit.vue'
import NavigatorToolbar from '@/components/MindMap/NavigatorToolbar.vue'
import { store } from '@/components/MindMap/useStore'

const editRef = ref(null)
const isZenMode = computed(() => store.localConfig.isZenMode)
const mindMapInstance = computed(() => editRef.value?.mindMap || null)
</script>

<style scoped lang="scss">
.mind-map-page {
  position: relative;
  height: calc(100vh - 84px);
  background: #f5f5f5;
}
.mind-map-body {
  height: 100%;
  display: flex;
  overflow: hidden;
  position: relative;
}
</style>
