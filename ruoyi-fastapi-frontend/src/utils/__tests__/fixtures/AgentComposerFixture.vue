<template>
  <main class="fixture" :class="{ dark }">
    <header class="controls"><strong>输入区组件验收 · 模拟状态，不连接 Agent、不修改脑图</strong><div><button v-for="item in ['unavailable', 'ready', 'running', 'stopping']" :key="item" @click="scenario = item">{{ item }}</button><button @click="dark = !dark">切换明暗</button><button @click="active = !active">切换面板可见性</button></div></header>
    <section v-show="active" id="mindmap-agent-panel" class="agentChatSurface" :class="{ isDark: dark }" :style="{ width: `${panelWidth}px` }">
      <MindmapAgentResizeHandle :active="active" :width="panelWidth" :bounds="panelBounds" @preview="layout.preview" @commit="layout.commit" @cancel="layout.cancel" @reset="layout.reset" />
      <header class="fixtureHeader"><strong>输入区与恢复入口</strong><span>{{ scenario }}</span></header>
      <p class="transcript">这里模拟对话阅读区。以下错误说明、写入说明和停止按钮均使用实际组件；发送仅更新本页提示。</p>
      <div class="panelFooter">
        <MindmapAgentExecutionPicker :agent-key="agentKey" :agents="agents" :catalog="{ devices: [], loaded: true }" :running="running" :current-job="running ? { agentKey } : null" @select="agentKey = $event" @manage="notice = '模拟管理入口，未改变设置'" />
        <div class="aiComposer">
          <div class="contextRow"><span>整份当前脑图</span><MindmapAgentWritePolicy :active="active" :dark="dark" :discussion="discussion" :label="discussion ? '讨论 · 不改图' : '编辑 · 实时保存到云端'" :description="policy" /></div>
          <MindmapAgentComposerIssue v-if="scenario === 'unavailable'" description="当前模型使用兼容模式接口，但提供商选了 Anthropic。请检查提供商与模型编码；未发送的要求保持不变。" @configure="notice = '模拟配置入口，未打开或修改真实配置'" />
          <el-input v-model="draft" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" aria-label="给 Agent 的要求" placeholder="继续完善当前脑图…" />
          <div class="composerToolbar"><MindmapAgentModeSwitch v-model="discussion" :disabled="running" /><span class="composerShortcut" title="Ctrl / ⌘ + Enter 发送 · Enter 换行">⌘ / Ctrl + Enter</span><el-button circle :disabled="scenario === 'unavailable' || scenario === 'stopping' || !draft.trim()" aria-label="模拟发送" @click="notice = '仅模拟发送，未连接 Agent'"><el-icon><Promotion /></el-icon></el-button><MindmapAgentStopButton v-if="running" :stopping="scenario === 'stopping'" @stop="stopRequests++; scenario = 'stopping'" /></div>
        </div>
      </div>
    </section>
    <p class="receipt" role="status">停止请求：{{ stopRequests }} · 宽度 {{ panelWidth }} · 已提交宽度 {{ committedWidth }} · {{ notice }}</p>
  </main>
</template>
<script setup>
import { computed, ref } from 'vue'
import { Promotion } from '@element-plus/icons-vue'
import MindmapAgentExecutionPicker from '../../../components/MindMap/MindmapAgentExecutionPicker.vue'
import MindmapAgentComposerIssue from '../../../components/MindMap/MindmapAgentComposerIssue.vue'
import MindmapAgentWritePolicy from '../../../components/MindMap/MindmapAgentWritePolicy.vue'
import MindmapAgentStopButton from '../../../components/MindMap/MindmapAgentStopButton.vue'
import MindmapAgentModeSwitch from '../../../components/MindMap/MindmapAgentModeSwitch.vue'
import MindmapAgentResizeHandle from '../../../components/MindMap/MindmapAgentResizeHandle.vue'
import { createAgentPanelLayout } from '../../mindmap-agent-layout.js'
import '../../../components/MindMap/styles/agent-chat.scss'
const scenario = ref('unavailable')
const dark = ref(false)
const active = ref(true)
const discussion = ref(false)
const draft = ref('保留现有节点，只补充异常情况')
const agentKey = ref('claude')
const agents = [{ agentKey: 'claude', displayName: 'Claude', status: 'enabled' }, { agentKey: 'codex', displayName: 'Codex', status: 'enabled' }]
const notice = ref('没有真实任务')
const stopRequests = ref(0)
const committedWidth = ref('未保存（测试页不使用浏览器存储）')
const layout = createAgentPanelLayout({ viewport: 1280, write: width => { committedWidth.value = width } })
const { width: panelWidth, bounds: panelBounds } = layout
const running = computed(() => ['running', 'stopping'].includes(scenario.value))
const policy = computed(() => discussion.value ? '只讨论当前脑图，不会修改画布。' : '修改会实时保存并同步给协作者。关闭面板后任务仍会继续，停止后保留已完成的修改。')
</script>
<style scoped>
:global(body) { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.fixture { min-height: 100dvh; padding: 16px; background: #f4f4f5; box-sizing: border-box; }
.fixture.dark { background: #111114; }
.controls { display: grid; gap: 10px; font-size: 12px; color: #737373; margin-bottom: 16px; }
.controls button { min-height: 32px; margin: 3px; padding: 5px 10px; border: 1px solid #ddd; border-radius: 6px; background: white; cursor: pointer; }
.agentChatSurface { position: relative; max-width: 100%; border: 1px solid var(--agent-border); border-radius: 12px; background: var(--ai-panel-bg); color: var(--agent-ink); }
.fixtureHeader { display: flex; justify-content: space-between; padding: 16px; font-size: 13px; border-bottom: 1px solid var(--agent-border); }
.fixtureHeader span,.transcript { color: var(--agent-muted); }
.transcript { min-height: 160px; padding: 16px; font-size: 13px; line-height: 1.7; }
.panelFooter { padding: 12px; }
.aiComposer { border: 1px solid var(--agent-border); }
.contextRow { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; font-size: 12px; }
.composerToolbar { display: flex; align-items: center; }
.receipt { font-size: 12px; color: #737373; }
</style>
