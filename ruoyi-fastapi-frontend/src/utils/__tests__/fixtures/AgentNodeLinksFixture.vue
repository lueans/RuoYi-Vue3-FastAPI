<template>
  <main class="fixture" :class="{ dark }">
    <header>
      <strong>节点定位验收 · 模拟回执与独立画布，不调用 API、不连接 Agent</strong>
      <div><button @click="dark = !dark">切换明暗</button><button @click="otherPreview = !otherPreview">{{ otherPreview ? '恢复本轮预览' : '模拟另一轮预览' }}</button><button @click="otherDocument = !otherDocument">{{ otherDocument ? '恢复当前脑图' : '模拟其他脑图' }}</button></div>
      <p role="status">{{ outcome || '展开工具，使用按钮或键盘定位节点。' }}</p>
    </header>
    <div class="workspace">
      <section class="agentChatSurface" :class="{ isDark: dark }" aria-label="工具定位聊天样例">
        <h2>完善登录异常分支</h2>
        <MindmapAgentTrace :events="events" running :node-navigation="navigation" />
      </section>
      <div ref="canvas" class="canvas" aria-label="独立验收脑图画布"></div>
    </div>
  </main>
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import MindMap from '@mind-map'
import MindmapAgentTrace from '../../../components/MindMap/MindmapAgentTrace.vue'
import { focusMindmapToolNode, resolveAgentToolDocumentScope } from '../../mindmap-agent-node-links.js'
import '../../../components/MindMap/styles/agent-chat.scss'
const canvas = ref(null)
const dark = ref(false)
const otherDocument = ref(false)
const otherPreview = ref(false)
const outcome = ref('')
let map
let resizeObserver
const job = { id: 'fixture-job', sourceType: 'cloud_document', sourceMindmapId: 900001, status: 'running' }
const document = { data: { uid: 'fixture-root', text: '登录验证' }, children: [
  { data: { uid: 'expired-code', text: '验证码过期' }, children: [] },
  { data: { uid: 'account-locked', text: '账号被锁定' }, children: [] },
  { data: { uid: 'collapsed-parent', text: '已折叠分支', expand: false }, children: [{ data: { uid: 'hidden-child', text: '隐藏节点不能被自动展开' }, children: [] }] },
] }
const events = [
  { key: 'plan', eventType: 'todo_updated', payload: { todos: [{ content: '补充异常场景', status: 'in_progress' }] } },
  { key: 'text', eventType: 'assistant_delta', payload: { text: '工具已返回节点，可在独立画布中核对。第三个节点在折叠分支中，第四个节点已不存在。' } },
  { key: 'tool', eventType: 'tool_started', payload: { callId: 'fixture-add', toolName: 'add_nodes', toolInput: '{"nodes":[]}' } },
  { key: 'done', eventType: 'tool_completed', payload: { callId: 'fixture-add', toolName: 'add_nodes', toolOutput: JSON.stringify({ createdCount: 4, created: ['expired-code', 'account-locked', 'hidden-child', 'deleted-child'].map(nodeUid => ({ nodeUid })) }), durationMs: 120 } },
]
const navigation = computed(() => {
  const scope = resolveAgentToolDocumentScope(job, { ownerUserId: '1', currentJob: job, editorContext: { mindmapId: otherDocument.value ? 900002 : 900001, documentId: otherDocument.value ? 'cloud:900002' : 'cloud:900001' } })
  return { identity: `${scope.documentId}:${otherPreview.value}`, reason: scope.reason, locate(_entry, nodeUid) {
    const before = JSON.stringify(map.getData())
    const viewBefore = JSON.stringify(map.view.getTransformData())
    const result = focusMindmapToolNode({ request: { ...scope, nodeUid }, ownerUserId: '1', documentId: 'cloud:900001', mindMap: map, previewJobId: otherPreview.value ? 'other-job' : job.id,
      navigate: node => map.renderer.moveNodeToCenter(node, false) })
    outcome.value = `${result.message} · 正文${before === JSON.stringify(map.getData()) ? '未改变' : '发生变化'} · 视角${viewBefore === JSON.stringify(map.view.getTransformData()) ? '未移动' : '已移动'}`
    return result
  } }
})
onMounted(() => {
  map = new MindMap({ el: canvas.value, data: document, readonly: true, layout: 'logicalStructure', theme: 'default' })
  resizeObserver = new ResizeObserver(() => {
    if (canvas.value?.clientWidth > 0 && canvas.value?.clientHeight > 0) map.resize()
  })
  resizeObserver.observe(canvas.value)
})
onBeforeUnmount(() => { resizeObserver?.disconnect(); map?.destroy() })
</script>
<style scoped>
:global(body) { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.fixture { padding: 16px; background: #f4f4f5; min-height: 100dvh; box-sizing: border-box; }
.fixture.dark { background: #17171b; color: #eee; }
header { font-size: 13px; margin-bottom: 16px; }
header div { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
header button { min-height: 32px; padding: 6px 10px; border: 1px solid #ddd; border-radius: 6px; background: white; color: #202020; }
.workspace { display: grid; grid-template-columns: minmax(0,460px) minmax(0,1fr); gap: 16px; }
.agentChatSurface { padding: 18px; border: 1px solid var(--agent-border); border-radius: 12px; background: var(--ai-panel-bg); min-width: 0; }
h2 { margin: 0 0 16px; color: var(--agent-ink); font-size: 16px; }
.canvas { height: 580px; min-width: 0; overflow: hidden; border: 1px solid #ddd; background: white; }
@media (max-width: 700px) { .workspace { grid-template-columns: minmax(0,1fr); } .canvas { height: 320px; } }
</style>
