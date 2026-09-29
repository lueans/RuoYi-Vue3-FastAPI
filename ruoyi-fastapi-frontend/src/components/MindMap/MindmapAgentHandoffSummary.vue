<template>
  <div class="handoffSummary">
    <div class="handoffDetails">
      <div class="handoffRoute">
        <div><small>当前 Agent</small><strong>{{ summary.current.name }}</strong><span>{{ summary.current.location }}</span></div>
        <span aria-hidden="true">→</span>
        <div><small>下一轮 Agent</small><strong>{{ summary.next.name }}</strong><span>{{ summary.next.location }}</span></div>
      </div>
      <p class="handoffScope">授权范围：{{ summary.scope }}</p>
      <p class="handoffMuted">{{ summary.dataNotice }}</p>
      <section aria-label="脑图结果">
        <h3>{{ summary.result.title }}</h3>
        <p>{{ summary.result.description }}</p>
        <p v-if="summary.result.canvasNote" class="handoffMuted">{{ summary.result.canvasNote }}</p>
        <p class="handoffMuted">停止不是撤销；保存状态以回执为准，不按 Todo 或工具成功次数计算。</p>
      </section>
      <section aria-label="剩余 Todo">
        <h3>剩余 Todo <small>Agent 自报计划</small></h3>
        <p v-if="!summary.todo.known">未提供可确认的计划。</p>
        <template v-else>
          <p v-if="summary.todo.current">当前事项：{{ summary.todo.current }}</p>
          <p v-if="!summary.todo.complete">记录不完整，不能确认全部剩余事项。</p>
          <details v-if="summary.todo.items.length">
            <summary>{{ summary.todo.complete ? '' : '已知 ' }}{{ summary.todo.items.length }} 项未完成 · 展开详情</summary>
            <ul><li v-for="(todo, index) in summary.todo.items" :key="index"><span class="handoffMuted">{{ todo.status === 'in_progress' ? '进行中' : todo.status === 'pending' ? '待处理' : '状态未知' }} · </span>{{ todo.content }}</li></ul>
          </details>
          <p v-else-if="summary.todo.complete">最新清单无未完成项；不代表脑图已验收或保存。</p>
        </template>
      </section>
      <section aria-label="已发送的排队请求">
        <h3>已发送的排队请求</h3>
        <p v-if="!summary.queue.known">完整队列状态未确认，以下仅列出已知请求。</p>
        <details v-if="summary.queue.items.length">
          <summary>{{ summary.queue.items.length }} 条已知请求 · 查看原绑定</summary>
          <ol><li v-for="item in summary.queue.items" :key="item.id">{{ item.prompt }}<small>{{ item.agent }} · {{ item.location }}</small></li></ol>
        </details>
        <p v-else-if="summary.queue.known">最近同步时没有排队请求。</p>
        <p class="handoffWarning">排队请求不会自动转交新 Agent：停止可能关闭队列；保留结果或当前轮已完成时，也可能按原绑定继续执行。</p>
      </section>
    </div>
    <p class="handoffDraft">排队请求不会自动迁移，可能关闭或按原 Agent 继续。输入框草稿保留，切换不会自动发送。</p>
  </div>
</template>

<script setup>
defineProps({ summary: { type: Object, required: true } })
</script>

<style scoped>
.handoffSummary { display:flex; flex-direction:column; max-height:calc(100dvh - 200px); color:var(--el-text-color-regular); font-size:13px; line-height:1.6; overflow-wrap:anywhere; }
.handoffDetails { min-height:0; overflow-y:auto; overscroll-behavior:contain; }
.handoffRoute { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:12px; background:var(--el-fill-color-light); border-radius:8px; padding:12px; }
.handoffRoute strong,.handoffRoute small,.handoffRoute div > span { display:block; }
.handoffRoute small,.handoffMuted { color:var(--el-text-color-secondary); }
.handoffRoute strong { font-size:15px; color:var(--el-text-color-primary); }
.handoffSummary p { margin:6px 0; }
.handoffSummary section { border-top:1px solid var(--el-border-color-lighter); margin-top:12px; padding-top:10px; }
.handoffSummary h3 { font-size:13px; margin:0 0 4px; color:var(--el-text-color-primary); }
.handoffSummary h3 small { margin-left:6px; font-weight:400; color:var(--el-text-color-secondary); }
.handoffSummary summary { cursor:pointer; color:var(--el-color-primary); }
.handoffSummary summary:focus-visible { outline:2px solid var(--el-color-primary); outline-offset:2px; }
.handoffSummary ul,.handoffSummary ol { padding-left:20px; margin:6px 0; }
.handoffSummary li { margin:6px 0; }
.handoffSummary li small { display:block; color:var(--el-text-color-secondary); }
.handoffScope { padding-top:6px; }
.handoffWarning { color:var(--el-color-warning-dark-2); }
.handoffDraft { flex-shrink:0; padding-top:10px; border-top:1px solid var(--el-border-color-lighter); }
</style>
<style>
.mindmapAgentHandoffBox.el-message-box { width:520px; max-width:calc(100vw - 24px); }
.mindmapAgentHandoffBox .el-message-box__message { width:100%; }
.mindmapAgentHandoffBox .el-message-box__btns { flex-wrap:wrap; gap:8px; }
.mindmapAgentHandoffBox .el-message-box__header { padding-right:30px; }
</style>
