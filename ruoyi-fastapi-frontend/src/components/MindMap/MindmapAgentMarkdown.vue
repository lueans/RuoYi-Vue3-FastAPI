<template><div class="agentMarkdown" v-html="html"></div></template>
<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { renderAgentMarkdown } from '@/utils/mindmap-agent-presentation'
const props = defineProps({ content: { type: String, default: '' } })
const html = ref(renderAgentMarkdown(props.content))
let timer
watch(() => props.content, () => {
  if (timer) return
  timer = setTimeout(() => { html.value = renderAgentMarkdown(props.content); timer = null }, 80)
})
onBeforeUnmount(() => clearTimeout(timer))
</script>
<style scoped>
.agentMarkdown { min-width: 0; color: var(--agent-ink); font-size: 13px; font-weight: 400; line-height: 1.75; overflow-wrap: anywhere; }
.agentMarkdown :deep(> :first-child) { margin-top: 0; }
.agentMarkdown :deep(> :last-child) { margin-bottom: 0; }
.agentMarkdown :deep(p) { margin: 8px 0; }
.agentMarkdown :deep(h1), .agentMarkdown :deep(h2), .agentMarkdown :deep(h3), .agentMarkdown :deep(h4) { font-size: 14px; font-weight: 600; margin: 16px 0 8px; line-height: 1.5; }
.agentMarkdown :deep(ul), .agentMarkdown :deep(ol) { margin: 8px 0; padding-left: 22px; }
.agentMarkdown :deep(li) { margin: 4px 0; }
.agentMarkdown :deep(li p) { margin: 2px 0; }
.agentMarkdown :deep(code) { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; padding: 2px 4px; border-radius: 4px; background: var(--agent-surface); }
.agentMarkdown :deep(pre) { overflow-x: auto; max-width: 100%; padding: 12px; border-radius: 8px; background: var(--agent-surface); white-space: pre; }
.agentMarkdown :deep(pre code) { padding: 0; background: none; }
.agentMarkdown :deep(blockquote) { margin: 10px 0; padding-left: 12px; border-left: 2px solid var(--agent-border); color: var(--agent-muted); }
.agentMarkdown :deep(a) { color: var(--agent-accent); text-decoration: underline; text-underline-offset: 3px; }
.agentMarkdown :deep(hr) { border: 0; border-top: 1px solid var(--agent-border); margin: 14px 0; }
.agentMarkdown :deep(.mindmapMarkdownTable) { max-width: 100%; overflow-x: auto; margin: 12px 0; border: 1px solid var(--agent-border); border-radius: 6px; }
.agentMarkdown :deep(.mindmapMarkdownTable:focus-visible) { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
.agentMarkdown :deep(table) { border-collapse: collapse; width: max-content; min-width: 100%; font-size: inherit; }
.agentMarkdown :deep(th), .agentMarkdown :deep(td) { padding: 7px 10px; min-width: 72px; max-width: 280px; border: 1px solid var(--agent-border); vertical-align: top; text-align: left; }
.agentMarkdown :deep(th) { font-weight: 600; background: var(--agent-surface); }
.agentMarkdown :deep([align="center"]) { text-align: center; }
.agentMarkdown :deep([align="right"]) { text-align: right; }
</style>
