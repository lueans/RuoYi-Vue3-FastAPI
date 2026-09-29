<!-- Open Design TodoRow / ToolRow presentation adapted to authoritative mindmap
     events. See docs/third-party/open-design-chat.md. No canvas mutations. -->
<template>
  <ol class="traceEntries">
    <li v-for="entry in entries" :key="entry.key">
      <div v-if="entry.kind === 'message'" class="processProse">
        <MindmapAgentMarkdown :content="entry.text" />
        <MindmapAgentFold v-if="entry.repeatedMessages?.length" :label="`另有 ${entry.repeatedMessages.length} 条相同正文记录`" class="repeatedProse">
          <p class="planNote">仅折叠相邻相同正文，原始记录保留；不代表工具重复执行。</p>
          <MindmapAgentMarkdown v-for="repeat in entry.repeatedMessages" :key="repeat.key" :content="repeat.text" />
        </MindmapAgentFold>
      </div>
      <MindmapAgentFold v-else-if="entry.kind === 'step'" :label="`步骤：${entry.step.content}`" :meta="`${entry.entries.length} 项`" :auto-open="stepOpen(entry)" class="stepRow">
        <template #title>
          <el-icon :class="[stepState(entry).tone, { spinning: running && entry.active }]" aria-hidden="true"><component :is="stepIcon(entry)" /></el-icon>
          <span class="stepName" :class="{ removed: entry.step.removed }">{{ entry.step.content }}</span>
          <span class="stepState" :class="stepState(entry).tone">{{ stepState(entry).label }}</span>
        </template>
        <p v-if="entry.step.removed" class="planNote">此步骤已从后续计划移除，保留此前实际执行的记录。</p>
        <MindmapAgentTraceRows :entries="entry.entries" :live="running && entry.active" :running="running" :cancelled="cancelled" :node-navigation="nodeNavigation" />
      </MindmapAgentFold>
      <MindmapAgentToolRow v-else-if="entry.kind === 'tool'" :entry="entry" :node-navigation="nodeNavigation" />
      <MindmapAgentFold v-else-if="entry.kind === 'summary'" label="思考摘要" class="thinkingRow" :auto-open="live">
        <MindmapAgentMarkdown :content="entry.text" />
        <p class="planNote">Agent 对外提供的摘要，不是隐藏推理。</p>
      </MindmapAgentFold>
      <div v-else-if="entry.kind === 'thinking'" class="thinkingStatus">
        <el-icon :class="{ spinning: entry.active }" aria-hidden="true"><component :is="entry.active ? Loading : ChatDotRound" /></el-icon>
        <span>{{ entry.active ? '思考中' : '已进行思考' }}</span><small>内部推理不展示</small>
      </div>
      <MindmapAgentFold v-else-if="entry.kind === 'plan'" :label="entry.revision ? `第 ${entry.revision} 份计划快照` : '更新计划'" :meta="`${entry.todos.length} 步`" class="planRevision">
        <p v-if="!entry.todos.length" class="planNote">这份快照清空了任务计划。</p>
        <ol class="planSteps"><li v-for="(todo, index) in entry.todos" :key="index"><span>{{ todo.content }}</span><small>{{ todoStatus[todo.status] || '待执行' }}</small></li></ol>
      </MindmapAgentFold>
    </li>
  </ol>
</template>
<script setup>
import { ChatDotRound, CircleCheck, Clock, Loading, VideoPause } from '@element-plus/icons-vue'
import { agentStepState } from '@/utils/mindmap-agent-presentation'
import MindmapAgentFold from './MindmapAgentFold.vue'
import MindmapAgentMarkdown from './MindmapAgentMarkdown.vue'
import MindmapAgentToolRow from './MindmapAgentToolRow.vue'
const props = defineProps({ entries: { type: Array, default: () => [] }, live: Boolean, running: Boolean, cancelled: Boolean, nodeNavigation: Object })
const todoStatus = { pending: '待执行', in_progress: '进行中', completed: '已完成', cancelled: '已取消' }
function stepState(entry) { return agentStepState(entry.step, { running: props.running, cancelled: props.cancelled, active: entry.active }) }
function stepIcon(entry) {
  const tone = stepState(entry).tone
  return tone === 'running' ? Loading : tone === 'completed' ? CircleCheck : tone === 'cancelled' ? VideoPause : Clock
}
function stepOpen(entry) { return (props.running && entry.active) || entry.entries.some(item => item.kind === 'tool' && ['failed', 'running'].includes(item.status)) || (props.cancelled && entry.step.status === 'in_progress') }
</script>
<style scoped>
.traceEntries,.planSteps { list-style: none; padding: 0; margin: 0; }
.traceEntries > li + li { margin-top: 2px; }
.processProse { padding: 7px 0; }
.repeatedProse { margin-top: 6px; color: var(--agent-muted); }
.stepRow,.thinkingRow,.planRevision { background: transparent; }
.stepRow :deep(summary),.planRevision :deep(summary) { padding: 6px 7px; margin-inline: -7px; }
.stepRow > :deep(.foldBody) { border-left: 1px solid var(--agent-border); margin-left: 7px; padding: 2px 0 8px 14px; }
.stepName { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.stepName.removed { text-decoration: line-through; color: var(--agent-muted); }
.stepState { flex: none; font-size: 11px; color: var(--agent-muted); white-space: nowrap; }
.planNote { color: var(--agent-muted); }
.running { color: var(--agent-accent); }
.completed.stepState { color: var(--agent-success); }
.thinkingStatus { display: flex; align-items: center; gap: 7px; padding: 7px 0; font-size: 12px; color: var(--agent-muted); }
.thinkingStatus small { font-size: 11px; margin-left: auto; }
.planSteps li { display: flex; align-items: baseline; gap: 8px; padding: 5px 0; font-size: 12px; line-height: 1.6; }
.planSteps li > span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.planSteps small { white-space: nowrap; font-size: 10px; color: var(--agent-muted); font-weight: 400; }
.planNote { font-size: 11px; margin: 8px 0; }
.spinning { animation: agent-spin 1.2s linear infinite; }
@keyframes agent-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinning { animation: none; } }
</style>
