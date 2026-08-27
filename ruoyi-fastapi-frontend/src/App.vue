<template>
  <el-config-provider :message="elementMessageConfig">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { useRoute } from 'vue-router'
import useSettingsStore from '@/store/modules/settings'
import { handleThemeStyle } from '@/utils/theme'

const route = useRoute()
const elementMessageConfig = computed(() => ({
  // The mindmap editor owns a fixed 52/60px command header. Keep global
  // feedback below it so save and conflict messages are never covered.
  offset: route.path === '/mindmap/edit' ? 72 : 16,
}))

onMounted(() => {
  nextTick(() => {
    // 初始化主题样式
    handleThemeStyle(useSettingsStore().theme)
  })
})
</script>
