<template>
  <main class="app-container aiTaskPage" :style="{ '--task-panel-width': `${panelWidth}px` }">
    <h1>AI 脑图任务</h1>
    <p>查看独立生成、本地脑图或上传文件的 AI 对话与结果。</p>
    <p>生成结果可下载或另存为云端脑图。修改原本地脑图需要回到原编辑器。</p>
    <el-alert v-if="!jobId" title="任务链接缺少任务编号，请从 AI 任务中心重新打开。" type="warning" :closable="false" />
    <div class="aiTaskActions">
      <el-button v-if="jobId" type="primary" @click="openTask">查看任务</el-button>
      <el-button @click="router.push('/mindmap/index')">返回脑图列表</el-button>
    </div>
    <MindmapAiDialog v-if="jobId" :key="jobId" ref="dialogRef" task-only readonly />
  </main>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MindmapAiDialog from '@/components/MindMap/MindmapAiDialog.vue'
import { useMindmapAgentLayout } from '@/utils/use-mindmap-agent-layout'

const route = useRoute()
const router = useRouter()
const dialogRef = ref(null)
const { width: panelWidth } = useMindmapAgentLayout()
const jobId = computed(() => String(Array.isArray(route.query.aiJobId)
  ? route.query.aiJobId[0] || '' : route.query.aiJobId || '').trim())

async function openTask() {
  await nextTick()
  await dialogRef.value?.openRequestedTask()
}
watch(dialogRef, dialog => { if (dialog) void dialog.openRequestedTask() }, { flush: 'post' })
</script>

<style scoped>
.aiTaskPage { padding-left: calc(var(--task-panel-width) + 64px); }
h1 { font-size: 24px; color: var(--el-text-color-primary); }
p { color: var(--el-text-color-regular); line-height: 1.7; }
.aiTaskActions { display: flex; gap: 12px; margin-top: 24px; flex-wrap: wrap; }
@media (max-width: 760px) { .aiTaskPage { padding-left: 20px; } }
</style>
