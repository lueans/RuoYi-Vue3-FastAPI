<template>
  <main class="fixture" :class="{ dark }">
    <div class="fixtureControls"><strong>组件验收 · 模拟事件，不连接 Agent</strong><div><button v-for="item in ['running', 'completed', 'cancelled', 'failed', 'replanned', 'ambiguous', 'empty', 'long']" :key="item" @click="state = item">{{ item }}</button><button @click="dark = !dark">切换明暗</button><button @click="discussion = !discussion">{{ discussion ? '切换到编辑' : '切换到讨论' }}</button><button @click="reset += 1; state = 'running'">重开一轮</button></div></div>
    <section class="agentChatSurface" :class="{ isDark: dark }">
      <header class="fixtureHeader"><strong>完善登录测试用例</strong><span>Claude · {{ state }}</span></header>
      <div class="fixtureTranscript">
        <div class="conversationMessage is-user"><p>帮我补充登录异常场景，保留现有脑图结构，并告诉我具体改了哪些节点。</p></div>
        <div class="conversationMessage is-assistant">
          <div class="conversationMessageMeta"><strong>Claude</strong><span>{{ state }}</span></div>
          <MindmapAgentTrace :key="reset" :events="events" :discussion="discussion" :running="['running', 'replanned', 'ambiguous', 'long'].includes(state)" :cancelled="state === 'cancelled'" :failed="state === 'failed'" :final-content="state === 'completed' ? '已补充 **3 个异常场景**。\n\n- 验证码过期\n- 连续输错密码\n- 账号被锁定\n\n请在右侧脑图查看实时预览。' : state === 'failed' ? '本轮工具执行失败，已保留生成的草稿。' : ''" fallback-content="没有过程事件的历史回答。" />
        </div>
      </div>
    </section>
  </main>
</template>
<script setup>
import { computed, ref } from 'vue'
import MindmapAgentTrace from '../../../components/MindMap/MindmapAgentTrace.vue'
import '../../../components/MindMap/styles/agent-chat.scss'
const state = ref('running')
const reset = ref(0)
const dark = ref(false)
const discussion = ref(false)
const events = computed(() => {
  if (state.value === 'empty') return []
  let i = 0
  const e = (eventType, payload) => ({ key: `fixture:${++i}`, sequence: i, eventType, payload })
  const done = state.value === 'completed'
  const base = [
    e('assistant_delta', { messageId: 'a', text: '我会先检查当前分支，再补充缺失场景，最后核对脑图结构。' }),
    e('todo_updated', { todos: [{ content: '读取登录模块与已有用例', status: 'in_progress' }, { content: '补充异常场景，保留已有节点', status: 'pending' }, { content: '检查结构与节点关系', status: 'pending' }] }),
    e('tool_started', { callId: 'read', toolName: 'read_projection', toolInput: '{}' }),
    e('tool_completed', { callId: 'read', toolName: 'read_projection', toolOutput: '{"nodeCount":18,"title":"登录功能"}', durationMs: 84 }),
    e('assistant_delta', { messageId: 'progress', text: '已读取当前分支，继续补充缺失的异常场景。' }),
    e('todo_updated', { todos: [{ content: '读取登录模块与已有用例', status: 'completed' }, { content: '补充异常场景，保留已有节点', status: 'in_progress' }, { content: '检查结构与节点关系', status: state.value === 'ambiguous' ? 'in_progress' : 'pending' }] }),
    e('thinking_summary', { messageId: 'summary', text: '已有用例覆盖正常登录；接下来补充**验证码过期**与账号保护场景。' }),
    e('tool_started', { callId: 'add', toolName: 'add_nodes', toolInput: '{"nodes":[{"parentUid":"login-errors","text":"验证码过期"},{"parentUid":"login-errors","text":"连续输错密码"},{"parentUid":"login-errors","text":"账号被锁定"}]}' }),
  ]
  if (done) {
    base.push(e('tool_completed', { callId: 'add', toolName: 'add_nodes', toolOutput: '{"createdCount":3}', durationMs: 1520 }))
    base.push(e('todo_updated', { todos: [{ content: '读取登录模块与已有用例', status: 'completed' }, { content: '补充异常场景，保留已有节点', status: 'completed' }, { content: '检查结构与节点关系', status: 'in_progress' }] }))
    base.push(e('tool_started', { callId: 'validate', toolName: 'validate_draft', toolInput: '{}' }))
    base.push(e('tool_completed', { callId: 'validate', toolName: 'validate_draft', toolOutput: '{"valid":true}', durationMs: 36 }))
    base.push(e('todo_updated', { todos: [{ content: '读取登录模块与已有用例', status: 'completed' }, { content: '补充异常场景，保留已有节点', status: 'completed' }, { content: '检查结构与节点关系', status: 'completed' }] }))
    base.push(e('assistant_delta', { messageId: 'final', text: '已补充 **3 个异常场景**。\n\n- 验证码过期\n- 连续输错密码\n- 账号被锁定\n\n请在右侧脑图查看实时预览。' }))
  }
  if (state.value === 'failed') base.push(e('tool_failed', { callId: 'add', toolName: 'add_nodes', errorMessage: '目标分支已被其他窗口修改，请重新读取。' }))
  if (state.value === 'replanned') {
    base.push(e('todo_updated', { todos: [{ content: '读取登录模块与已有用例', status: 'completed' }, { content: '补充安全保护场景', status: 'in_progress' }, { content: '检查结构与节点关系', status: 'pending' }] }))
    base.push(e('tool_completed', { callId: 'add', toolName: 'add_nodes', toolOutput: '{"createdCount":3}', durationMs: 1520 }))
    base.push(e('tool_started', { callId: 'rewrite', toolName: 'update_nodes', toolInput: '{"updates":[{"nodeUid":"lock-policy","patch":{"text":"账号锁定与恢复"}}]}' }))
  }
  if (state.value === 'long') {
    for (let index = 0; index < 85; index++) {
      base.push(e('tool_started', { callId: `long:${index}`, toolName: 'read_document_detail', toolInput: '{}' }))
      base.push(e('tool_completed', { callId: `long:${index}`, toolName: 'read_document_detail', toolOutput: JSON.stringify({ title: '很长的节点标题/'.repeat(20), index }), durationMs: 35 }))
    }
  }
  return base
})
</script>
<style scoped>
:global(body) { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.fixture { min-height: 100vh; background: #f4f4f5; padding: 16px; box-sizing: border-box; }
.fixtureControls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 16px; color: #737373; font-size: 12px; }
.fixtureControls button { padding: 6px 10px; border: 1px solid #ddd; background: white; border-radius: 6px; margin: 3px; cursor: pointer; }
.agentChatSurface { width: 460px; max-width: 100%; background: var(--ai-panel-bg); border: 1px solid var(--agent-border); border-radius: 12px; }
.fixtureHeader { padding: 16px 20px; border-bottom: 1px solid var(--agent-border); display: flex; justify-content: space-between; color: var(--agent-ink); font-size: 12px; }
.fixtureHeader span { color: var(--agent-muted); }
.fixtureTranscript { padding: 20px; display: grid; gap: 24px; }
.conversationMessage { display: grid; gap: 10px; }
.conversationMessage p { margin: 0; font-size: 13px; }
.conversationMessageMeta { display: flex; justify-content: space-between; }
.dark { background: #111114; }
</style>
