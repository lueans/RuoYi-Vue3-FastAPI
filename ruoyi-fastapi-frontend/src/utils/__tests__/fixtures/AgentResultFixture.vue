<template>
  <main class="fixture" :class="{ dark }">
    <header class="fixtureControls">
      <strong>组件验收 · 模拟回执，不连接 Agent、不修改脑图</strong>
      <div><button v-for="item in states" :key="item" @click="scenario = item">{{ item }}</button><button @click="dark = !dark">切换明暗</button></div>
    </header>
    <section class="agentChatSurface" :class="{ isDark: dark }">
      <header class="fixtureHeader"><strong>补充登录异常场景</strong><span>第 2 轮</span></header>
      <div class="fixtureBody">
        <p>已生成登录异常场景，应用与保存状态见下方。</p>
        <MindmapAgentResultCard :state="state" :counts="historical ? null : counts" :turn-index="historical ? 1 : 2" :historical="historical" has-more>
          <details v-if="scenario === 'review'" open class="review">
            <summary>查看本轮变更</summary>
            <p>本次将替换整个“登录验证”分支，请先核对差异。</p>
            <el-checkbox v-model="confirmed">我已查看差异，确认采纳本轮修改</el-checkbox>
          </details>
          <template #actions>
            <div class="actions">
              <template v-if="scenario === 'review'"><el-button @click="scenario = 'rejected'">不采纳本轮</el-button><el-button type="primary" :disabled="!confirmed" @click="scenario = 'saving'">采纳本轮</el-button></template>
              <el-button v-else-if="scenario === 'save_failed'" type="warning" @click="scenario = 'saving'">重试保存 AI 结果</el-button>
              <el-button v-else-if="['cloud_applied', 'local_applied', 'direct'].includes(scenario)" @click="scenario = 'undone'">撤销 AI 结果</el-button>
            </div>
          </template>
          <template #more><button type="button" @click="notice = '仅模拟下载入口，未生成或下载文件'">下载 .smm</button></template>
        </MindmapAgentResultCard>
        <p v-if="notice" role="status">{{ notice }}</p>
      </div>
      <footer><label>给 Agent 的要求<textarea placeholder="继续完善脑图…" /></label><small>此页面不发送请求，结果状态由顶部按钮切换。</small></footer>
    </section>
  </main>
</template>
<script setup>
import { computed, ref } from 'vue'
import MindmapAgentResultCard from '../../../components/MindMap/MindmapAgentResultCard.vue'
import { mindmapAgentResultState, mindmapResultChangeCounts } from '../../mindmap-agent-result.js'
import '../../../components/MindMap/styles/agent-chat.scss'
const states = ['ready', 'saving', 'save_failed', 'review', 'cloud_applied', 'local_applied', 'direct', 'file', 'failed', 'cancelled', 'undone', 'rejected', 'historical']
const scenario = ref('ready')
const dark = ref(false)
const confirmed = ref(false)
const notice = ref('')
const historical = computed(() => scenario.value === 'historical')
const counts = mindmapResultChangeCounts({ createdCount: 18, updatedCount: 3, movedCount: 1, deletedCount: 2 })
const state = computed(() => mindmapAgentResultState({
  job: { proposalId: 'fixture-proposal', status: ({ cloud_applied: 'applied', local_applied: 'applied', direct: 'completed_direct', file: 'completed_file', saving: 'ready', save_failed: 'ready', review: 'needs_review' })[scenario.value] || scenario.value },
  sourceIsCloud: scenario.value !== 'local_applied', historical: historical.value,
  saving: scenario.value === 'saving', saveFailed: scenario.value === 'save_failed',
  direct: ['direct', 'failed', 'cancelled'].includes(scenario.value), catchingUp: scenario.value === 'direct',
}))
</script>
<style scoped>
:global(body) { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.fixture { min-height: 100dvh; padding: 16px; box-sizing: border-box; background: #f4f4f5; }
.fixture.dark { background: #111114; }
.fixtureControls { display: grid; gap: 8px; color: #737373; font-size: 12px; margin-bottom: 16px; }
.fixtureControls button { margin: 3px; }
button:not(.el-button) { min-height: 32px; padding: 6px 10px; border: 1px solid #ddd; background: white; border-radius: 6px; cursor: pointer; }
.agentChatSurface { width: 460px; max-width: 100%; border: 1px solid var(--agent-border); border-radius: 12px; background: var(--ai-panel-bg); color: var(--agent-ink); }
.fixtureHeader { padding: 16px; border-bottom: 1px solid var(--agent-border); display: flex; justify-content: space-between; font-size: 13px; }
.fixtureHeader span { color: var(--agent-muted); font-size: 12px; }
.fixtureBody { padding: 16px; }
.fixtureBody > p,.review { font-size: 13px; line-height: 1.7; }
.review { margin-top: 12px; }
.review :deep(.el-checkbox) { height: auto; white-space: normal; align-items: flex-start; }
.review :deep(.el-checkbox__label) { white-space: normal; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.actions .el-button { margin: 0; }
footer { padding: 16px; border-top: 1px solid var(--agent-border); font-size: 13px; }
textarea { width: 100%; display: block; box-sizing: border-box; min-height: 76px; margin: 8px 0; padding: 10px; border: 1px solid var(--agent-border); border-radius: 8px; background: var(--agent-surface); color: var(--agent-ink); font: inherit; }
footer small { color: var(--agent-muted); }
</style>
