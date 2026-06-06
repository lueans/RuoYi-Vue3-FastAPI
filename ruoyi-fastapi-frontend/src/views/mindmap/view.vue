<template>
  <div class="share-view-page">
    <div class="share-view-header" v-if="mindmapData">
      <div class="headerContent">
        <h2>{{ mindmapData.name }}</h2>
        <el-tag type="info" size="small">分享预览</el-tag>
        <el-tag v-if="mindmapData.shareType === 1" type="success" size="small" style="margin-left: 8px;">可编辑</el-tag>
      </div>
    </div>
    <div class="share-view-body">
      <div v-if="loading" class="loadingState">
        <el-icon class="is-loading" :size="40"><Loading /></el-icon>
        <p>加载中...</p>
      </div>
      <div v-else-if="error" class="errorState">
        <el-result icon="error" :title="error">
          <template #extra>
            <el-button type="primary" @click="$router.push('/login')">登录</el-button>
          </template>
        </el-result>
      </div>
      <div v-else-if="mindmapData" ref="mindMapContainer" class="mindMapContainer"></div>
    </div>
  </div>
</template>

<script setup name="MindmapShareView">
import { ref, onMounted, onBeforeUnmount, shallowRef, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { viewByShareToken } from '@/api/mindmap/share'
import MindMap from '@mind-map'
import { registerPlugins } from '@/components/MindMap/usePlugins'
import Themes from 'simple-mind-map-plugin-themes'

registerPlugins('full')
Themes.init(MindMap)

const route = useRoute()
const loading = ref(true)
const error = ref('')
const mindmapData = ref(null)
const mindMapContainer = ref(null)
const mindMap = shallowRef(null)

onMounted(async () => {
  const token = route.params.token
  if (!token) {
    error.value = '无效的分享链接'
    loading.value = false
    return
  }

  try {
    const res = await viewByShareToken(token)
    mindmapData.value = res.data

    // 等待 DOM 更新后初始化脑图
    await nextTick()
    initMindMap()
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})

function initMindMap() {
  if (!mindMapContainer.value || !mindmapData.value) return

  const data = mindmapData.value
  mindMap.value = new MindMap({
    el: mindMapContainer.value,
    data: data.nodeTree || { data: { text: '空脑图' }, children: [] },
    layout: data.layout || 'logicalStructure',
    theme: data.theme?.template || 'default',
    themeConfig: data.theme?.config || {},
    viewData: data.viewData || null,
    readonly: true,
    fit: true,
    enableFreeDrag: false,
    isLimitMindMapInCanvas: true,
    customInnerElsAppendTo: null,
  })
}

onBeforeUnmount(() => {
  if (mindMap.value) {
    mindMap.value.destroy()
    mindMap.value = null
  }
})
</script>

<style lang="scss" scoped>
.share-view-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f5f5;
}

.share-view-header {
  padding: 12px 24px;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;

  .headerContent {
    display: flex;
    align-items: center;
    gap: 12px;

    h2 {
      margin: 0;
      font-size: 18px;
      font-weight: 500;
    }
  }
}

.share-view-body {
  flex: 1;
  overflow: hidden;
  position: relative;

  .loadingState, .errorState {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #999;

    p {
      margin-top: 16px;
      font-size: 14px;
    }
  }

  .mindMapContainer {
    width: 100%;
    height: 100%;
  }
}
</style>
