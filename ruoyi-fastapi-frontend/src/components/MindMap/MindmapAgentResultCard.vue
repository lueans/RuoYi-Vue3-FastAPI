<!-- Open Design's separate process/result presentation, adapted to mindmap
     save receipts. All mutations remain with the parent workbench. -->
<template>
  <section class="agentResultCard" :class="`is-${state.tone}`" :aria-label="historical ? '历史脑图结果' : '本轮脑图变更'">
    <header class="resultCardHeader">
      <div><span class="resultCardRound">第 {{ turnIndex || 1 }} 轮{{ historical ? ' · 历史结果' : ' · 脑图结果' }}</span><strong>{{ state.title }}</strong></div>
      <span class="resultCardBadge">{{ state.label }}</span>
    </header>
    <p class="resultCardDescription">{{ state.description }}</p>
    <p v-if="state.canvasNote" class="resultCardNote">{{ state.canvasNote }}</p>
    <dl v-if="counts" class="resultCardCounts" aria-label="本轮变更数量">
      <div v-for="item in countFields" :key="item.key"><dt>{{ item.label }}</dt><dd>{{ counts[item.key] }}</dd></div>
    </dl>
    <slot />
    <div class="resultCardActions"><slot name="actions" /></div>
    <details v-if="hasMore" class="resultCardMore">
      <summary>下载与更多结果操作</summary>
      <div><slot name="more" /></div>
    </details>
  </section>
</template>
<script setup>
defineProps({ state: { type: Object, required: true }, counts: Object, turnIndex: Number, historical: Boolean, hasMore: Boolean })
const countFields = [{ key: 'createdCount', label: '新增' }, { key: 'updatedCount', label: '修改' }, { key: 'movedCount', label: '移动' }, { key: 'deletedCount', label: '删除' }]
</script>
<style scoped>
.agentResultCard { min-width: 0; border: 1px solid var(--agent-border); border-radius: 10px; padding: 14px; background: var(--agent-surface); color: var(--agent-ink); }
.resultCardHeader { display: flex; align-items: flex-start; gap: 12px; justify-content: space-between; }
.resultCardHeader > div { display: grid; gap: 5px; min-width: 0; }
.resultCardHeader strong { font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.resultCardRound { color: var(--agent-muted); font-size: 11px; }
.resultCardBadge { flex: none; padding: 3px 7px; border-radius: 6px; background: var(--agent-hover); font-size: 11px; }
.is-success .resultCardBadge { color: var(--agent-success); }
.is-warning .resultCardBadge { color: var(--agent-danger); }
.resultCardDescription,.resultCardNote { margin: 8px 0 0; font-size: 12px; line-height: 1.7; color: var(--agent-muted); overflow-wrap: anywhere; }
.resultCardCounts { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 8px; margin: 12px 0; }
.resultCardCounts > div { padding: 7px; border: 1px solid var(--agent-border); border-radius: 6px; }
.resultCardCounts dt { font-size: 11px; color: var(--agent-muted); }
.resultCardCounts dd { margin: 3px 0 0; font-size: 15px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.resultCardActions { display: grid; gap: 8px; }
.resultCardActions:not(:empty) { margin-top: 12px; }
.resultCardMore { margin-top: 12px; border-top: 1px solid var(--agent-border); padding-top: 8px; }
.resultCardMore summary { padding: 4px 0; color: var(--agent-muted); font-size: 12px; cursor: pointer; }
.resultCardMore summary:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
.resultCardMore > div { padding-top: 8px; }
</style>
