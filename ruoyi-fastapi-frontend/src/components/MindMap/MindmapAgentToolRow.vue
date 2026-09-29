<!-- Open Design ToolRow's action/object summary, adapted to mindmap receipts.
     Details remain available; this component never changes the canvas.
     See docs/third-party/open-design-chat.md. -->
<template>
    <MindmapAgentFold :label="`${presentation.verb} ${presentation.subject}，${toolStatus[entry.status] || '状态未知'}，${presentation.summary || presentation.request}`" :meta="formatAgentDuration(entry.duration)" :auto-open="entry.status === 'failed'" class="toolRow">
      <template #title>
        <span class="toolTitle">
          <span class="toolHeading">
            <el-icon :class="['toolMark', entry.status, { spinning: entry.status === 'running' }]" aria-hidden="true"><component :is="entry.status === 'running' ? Loading : entry.status === 'failed' ? Warning : Operation" /></el-icon>
            <span class="toolVerb">{{ presentation.verb }}</span><span class="toolName" :title="entry.name">{{ presentation.subject }}</span>
            <span class="toolState" :class="entry.status">{{ toolStatus[entry.status] }}</span>
          </span>
          <span v-if="presentation.summary" class="toolSummary">{{ presentation.summary }}</span>
          <span v-if="presentation.request" class="toolRequest">{{ presentation.request }}</span>
        </span>
      </template>
      <div class="toolDetails">
        <p v-if="entry.error || entry.status === 'failed'" class="toolError">{{ entry.error || '工具报告失败，未提供具体原因。' }}</p>
        <p v-if="entry.status === 'failed'" class="toolFailureNote">本次调用失败不代表已提交的修改已撤销，保存状态以本轮结果回执为准。</p>
        <section v-if="nodeTargets.length" class="toolNodes" aria-label="工具返回的相关节点">
          <strong>在当前脑图中查看 <small>工具返回的节点</small></strong>
          <div class="toolNodeLinks">
            <button v-for="(nodeUid, index) in nodeTargets" :key="nodeUid" type="button"
              :disabled="Boolean(navigationReason)"
              :title="navigationReason || nodeUid"
              :aria-label="`定位工具返回的第 ${index + 1} 个节点：${nodeUid}`"
              @click="locate(nodeUid)">节点 {{ index + 1 }} <code>{{ nodeUid.slice(0, 8) }}</code></button>
          </div>
          <p class="nodeLinkNote">{{ navigationReason || '仅定位当前节点，不代表本轮已保存。最多展示 12 个返回节点。' }}</p>
          <p v-if="navigationMessage" class="nodeLinkStatus" role="status" aria-live="polite">{{ navigationMessage }}</p>
        </section>
        <MindmapAgentFold v-if="entry.input || entry.output" label="调用参数与返回详情" class="toolTechnicalDetails">
          <code class="toolIdentity">{{ entry.name }}</code>
          <template v-if="entry.input"><strong>调用参数</strong><pre tabindex="0" aria-label="工具调用参数">{{ inputText }}</pre></template>
          <template v-if="entry.output"><strong>返回结果 <small>有界摘要</small></strong><pre tabindex="0" aria-label="工具返回结果">{{ outputText }}</pre></template>
        </MindmapAgentFold>
        <p v-if="!entry.input && !entry.output" class="missingDetail">{{ entry.status === 'running' ? '等待工具返回…' : '此 Agent 未提供参数或返回详情。' }}</p>
      </div>
    </MindmapAgentFold>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { Loading, Operation, Warning } from '@element-plus/icons-vue'
import { agentToolPresentation, formatAgentDuration } from '@/utils/mindmap-agent-presentation'
import { agentToolNodeTargets } from '@/utils/mindmap-agent-node-links'
import MindmapAgentFold from './MindmapAgentFold.vue'
const props = defineProps({ entry: { type: Object, required: true }, nodeNavigation: Object })
const presentation = computed(() => agentToolPresentation(props.entry))
const nodeTargets = computed(() => agentToolNodeTargets(props.entry))
const navigationReason = computed(() => props.nodeNavigation?.reason || (typeof props.nodeNavigation?.locate !== 'function' ? '当前视图未连接脑图，无法定位节点。' : ''))
const navigationMessage = ref('')
watch([() => props.entry.key, () => props.entry.output, () => props.nodeNavigation?.identity, () => props.nodeNavigation?.reason], () => { navigationMessage.value = '' })
function locate(nodeUid) {
  if (!nodeTargets.value.includes(nodeUid) || navigationReason.value) return
  try { navigationMessage.value = props.nodeNavigation.locate(props.entry, nodeUid)?.message || '画布尚未响应，请稍后重试。' }
  catch { navigationMessage.value = '暂时无法定位该节点，请稍后重试。' }
}
const toolStatus = { running: '执行中', completed: '完成', failed: '失败', cancelled: '中断', unknown: '未返回' }
function pretty(value) { try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value } }
const inputText = computed(() => pretty(props.entry.input))
const outputText = computed(() => pretty(props.entry.output))
</script>
<style scoped>
.toolRow { background: transparent; }
.toolRow :deep(summary) { padding: 6px 7px; margin-inline: -7px; }
.toolRow :deep(.foldBody) { padding-left: 22px; }
.toolTitle { min-width: 0; width: 100%; }
.toolHeading { display: flex; align-items: center; gap: 7px; }
.toolVerb,.toolRequest,.missingDetail { color: var(--agent-muted); }
.toolMark { flex: none; font-size: 15px; }
.toolName { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.toolState { flex: none; font-size: 11px; color: var(--agent-muted); white-space: nowrap; }
.failed,.toolError { color: var(--agent-danger); }
.running { color: var(--agent-accent); }
.toolSummary,.toolRequest { display: block; padding-left: 22px; margin-top: 3px; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.toolSummary { color: var(--agent-ink); }
.toolDetails { padding: 3px 0 6px; }
.toolFailureNote { margin: 6px 0 10px; color: var(--agent-muted); font-size: 12px; line-height: 1.6; }
.toolTechnicalDetails { margin-top: 8px; }
.toolTechnicalDetails :deep(.foldBody) { padding: 8px 10px 2px; }
.toolNodes { margin: 0 0 12px; }
.toolNodeLinks { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
.toolNodeLinks button { min-height: 32px; padding: 5px 8px; border: 1px solid var(--agent-border); border-radius: 6px; background: var(--agent-surface); color: var(--agent-ink); font: inherit; font-size: 12px; cursor: pointer; }
.toolNodeLinks button:disabled { cursor: not-allowed; color: var(--agent-muted); }
.toolNodeLinks button:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
.toolNodeLinks code { color: var(--agent-muted); font-size: 11px; }
.nodeLinkNote,.nodeLinkStatus { margin: 7px 0 0; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.nodeLinkNote { color: var(--agent-muted); }
.toolIdentity { display: block; color: var(--agent-muted); overflow-wrap: anywhere; margin: 0 0 10px; font-size: 11px; }
.toolDetails strong { display: block; font-size: 11px; font-weight: 600; }
.toolDetails strong small { color: var(--agent-muted); font-weight: 400; margin-left: 4px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; padding: 10px; border-radius: 6px; background: var(--agent-surface); font: 11px/1.65 ui-monospace, SFMono-Regular, Consolas, monospace; margin: 6px 0 12px; }
.spinning { animation: agent-spin 1.2s linear infinite; }
@keyframes agent-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinning { animation: none; } }
</style>
