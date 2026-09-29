<!-- Open Design execution-shell presentation, ported to Vue and mindmap events.
     See docs/third-party/open-design-chat.md for source/license and adaptations. -->
<template>
  <section class="agentTrace" aria-label="Agent 实时执行过程">
    <MindmapAgentFold v-if="planRevisions.length" :label="`任务计划：${planSummary?.label || '计划已清空'}`" :meta="planSummary?.meta" class="tracePlan">
      <template #title>
        <el-icon aria-hidden="true" :class="{ spinning: planSummary?.tone === 'running' }"><component :is="planSummary?.tone === 'running' ? Loading : List" /></el-icon>
        <span class="planCurrent" :title="planSummary?.label">{{ planSummary?.label || '计划已清空' }}</span>
      </template>
      <ol class="planSteps">
        <li v-for="(todo, index) in view.todos" :key="todo.id || index" :class="todo.status">
          <el-icon aria-hidden="true" :class="{ spinning: running && todo.status === 'in_progress' }"><component :is="todoIcon(todo.status)" /></el-icon>
          <span>{{ todo.content }}</span><small>{{ planStatus(todo.status) }}</small>
        </li>
      </ol>
      <p v-if="!view.todos.length" class="planNote">Agent 已清空最新计划，此前的记录仍可查看。</p>
      <p v-if="cancelled" class="planNote">已停止更新，以上保留中断时的计划。</p>
      <MindmapAgentFold v-if="planRevisions.length > 1 || !view.todos.length" label="计划变更记录" :meta="`${planRevisions.length} 份快照`" class="planHistory">
        <button v-if="planRevisions.length > planHistoryLimit" type="button" class="loadTrace" @click="planHistoryLimit += 10">查看更早的计划（{{ planRevisions.length - planHistoryLimit }}）</button>
        <MindmapAgentTraceRows :entries="planRevisions.slice(-planHistoryLimit)" />
      </MindmapAgentFold>
    </MindmapAgentFold>
    <button v-if="blocks.length > limit" type="button" class="loadTrace" @click="limit += 40">查看更早的过程（{{ blocks.length - limit }}）</button>
    <div v-for="block in blocks.slice(-limit)" :key="block.key" class="traceBlock">
      <template v-if="block.kind === 'message'">
        <MindmapAgentMarkdown :content="block.text" />
        <MindmapAgentFold v-if="block.repeatedMessages?.length" :label="`另有 ${block.repeatedMessages.length} 条相同正文记录`" class="repeatedProse">
          <p class="planNote">仅折叠相邻相同正文，原始记录保留；不代表工具重复执行。</p>
          <MindmapAgentMarkdown v-for="repeat in block.repeatedMessages" :key="repeat.key" :content="repeat.text" />
        </MindmapAgentFold>
      </template>
      <MindmapAgentFold v-else flat :label="shellState(block).label + ' · 执行记录'" :auto-open="isLiveBlock(block) || cancelled || shellState(block).tone === 'failed'" :meta="`${block.entries.length} 项记录`">
        <template #title>
          <el-icon class="shellStatus" :class="[shellState(block).tone, { spinning: isLiveBlock(block) }]" aria-hidden="true"><component :is="isLiveBlock(block) ? Loading : shellState(block).tone === 'failed' ? Warning : cancelled ? VideoPause : shellState(block).tone === 'unknown' ? Clock : CircleCheck" /></el-icon>
          <span>{{ shellState(block).label }}</span><span class="shellCaption">执行记录</span>
        </template>
        <button v-if="block.entries.length > recordLimit" type="button" class="loadTrace" @click="recordLimit += 50">展开更早的 {{ Math.min(50, block.entries.length - recordLimit) }} 项记录</button>
        <div v-if="running && !block.entries.length" class="thinkingStatus waitingStatus" role="status"><el-icon class="spinning" aria-hidden="true"><Loading /></el-icon><span>正在等待 Agent 输出…</span></div>
        <MindmapAgentTraceRows :entries="sliceAgentExecutionRows(block.rows, recordLimit)" :live="isLiveBlock(block)" :running="running" :cancelled="cancelled" :node-navigation="nodeNavigation" />
      </MindmapAgentFold>
    </div>
    <div v-if="running && !blocks.length" class="thinkingStatus waitingStatus" role="status"><el-icon class="spinning" aria-hidden="true"><Loading /></el-icon><span>正在等待 Agent 输出…</span></div>
    <MindmapAgentMarkdown v-else-if="!blocks.length && fallbackContent" :content="fallbackContent" />
    <p v-if="cancelled" class="traceEndNote"><el-icon aria-hidden="true"><VideoPause /></el-icon>本轮已中断 · 已接收的内容保留</p>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { CircleCheck, Clock, List, Loading, VideoPause, Warning } from '@element-plus/icons-vue'
import { projectRuntimeEvents } from '@/utils/mindmap-ai-runtime'
import { agentExecutionState, agentTurnExecutionState, agentPlanSummary, buildAgentTurnBlocks, sliceAgentExecutionRows } from '@/utils/mindmap-agent-presentation'
import MindmapAgentFold from './MindmapAgentFold.vue'
import MindmapAgentMarkdown from './MindmapAgentMarkdown.vue'
import MindmapAgentTraceRows from './MindmapAgentTraceRows.vue'
const props = defineProps({ events: { type: Array, default: () => [] }, running: Boolean, cancelled: Boolean, failed: Boolean, discussion: Boolean, finalContent: String, fallbackContent: String, nodeNavigation: Object })
const limit = ref(40)
const recordLimit = ref(50)
const planHistoryLimit = ref(10)
const view = computed(() => projectRuntimeEvents(props.events, props))
const planRevisions = computed(() => view.value.entries.filter(entry => entry.kind === 'plan').map((entry, index) => ({ ...entry, revision: index + 1 })))
const planSummary = computed(() => agentPlanSummary(view.value.todos, props))
const blocks = computed(() => buildAgentTurnBlocks(view.value.entries, props.finalContent, props))
const todoStatus = { pending: '待执行', in_progress: '进行中', completed: '已完成', cancelled: '已取消' }
function isLiveBlock(block) { return props.running && (block === blocks.value.at(-1) || block.entries.some(entry => entry.kind === 'tool' && entry.status === 'running')) }
function shellState(block) { return (props.discussion ? agentExecutionState : agentTurnExecutionState)(block.entries, { running: isLiveBlock(block), cancelled: props.cancelled, failed: props.failed && block === blocks.value.filter(item => item.kind === 'execution').at(-1) }) }
function todoIcon(status) { return status === 'completed' ? CircleCheck : status === 'in_progress' && props.running ? Loading : status === 'cancelled' ? VideoPause : Clock }
function planStatus(status) { return status === 'in_progress' && !props.running ? (props.cancelled ? '已中断' : '未确认完成') : todoStatus[status] || '待执行' }
</script>
<style scoped>
.agentTrace { min-width: 0; color: var(--agent-ink); }
.traceBlock + .traceBlock { margin-top: 14px; }
.tracePlan { margin-bottom: 16px; }
.planCurrent { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.planHistory { margin-top: 10px; }
.repeatedProse { margin-top: 6px; color: var(--agent-muted); }
.planSteps { list-style: none; padding: 0; margin: 0; }
.shellCaption,.planNote { color: var(--agent-muted); }
.shellCaption { font-weight: 400; font-size: 12px; }
.shellStatus.completed { color: var(--agent-success); }
.failed { color: var(--agent-danger); }
.running { color: var(--agent-accent); }
.thinkingStatus { display: flex; align-items: center; gap: 7px; padding: 7px 0; font-size: 12px; color: var(--agent-muted); }
.thinkingStatus small { font-size: 11px; margin-left: auto; }
.planSteps li { display: flex; align-items: baseline; gap: 8px; padding: 5px 0; font-size: 12px; line-height: 1.6; }
.planSteps li > span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.planSteps .completed { color: var(--agent-muted); }
.planSteps .completed > span { text-decoration: line-through; text-decoration-color: var(--agent-border); }
.planSteps .in_progress { font-weight: 600; }
.planSteps small { white-space: nowrap; font-size: 10px; color: var(--agent-muted); font-weight: 400; }
.planNote { font-size: 11px; margin: 8px 0 0; }
.loadTrace { width: 100%; padding: 8px; border: 0; background: none; color: var(--agent-muted); cursor: pointer; font-size: 12px; }
.traceEndNote { display: flex; align-items: center; gap: 6px; margin: 14px 0 0; color: var(--agent-muted); font-size: 11px; }
.spinning { animation: agent-spin 1.2s linear infinite; }
@keyframes agent-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinning { animation: none; } }
</style>
