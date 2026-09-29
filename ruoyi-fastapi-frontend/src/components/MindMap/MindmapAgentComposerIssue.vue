<!-- Open Design RunErrorCard's explanation/action separation, adapted to a
     compact preflight notice. Full diagnostics stay available on demand. -->
<template>
  <section class="composerIssue" aria-label="发送前需要处理的问题">
    <div class="issueHeading">
      <details :key="description" class="issueDetails">
        <summary><el-icon aria-hidden="true"><WarningFilled /></el-icon><span>{{ label }}</span><el-icon class="issueChevron" aria-hidden="true"><ArrowDown /></el-icon></summary>
        <p>{{ description }}</p>
      </details>
      <button type="button" @click="$emit('configure')">检查配置</button>
    </div>
  </section>
</template>
<script setup>
import { ArrowDown, WarningFilled } from '@element-plus/icons-vue'
defineProps({ description: { type: String, required: true }, label: { type: String, default: '所选 Agent 暂不可用' } })
defineEmits(['configure'])
</script>
<style scoped>
.composerIssue { margin: 4px 0 6px; padding: 2px 7px; border: 1px solid color-mix(in srgb, var(--agent-warning) 30%, transparent); border-radius: 7px; background: color-mix(in srgb, var(--agent-warning) 8%, var(--ai-panel-bg)); color: var(--agent-ink); font-size: 12px; line-height: 1.6; }
.issueHeading { display: flex; align-items: flex-start; gap: 8px; }
.issueDetails { min-width: 0; flex: 1; }
summary { display: flex; min-height: 32px; align-items: center; gap: 6px; cursor: pointer; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary > span { min-width: 0; }
summary > .el-icon { flex: none; color: var(--agent-warning); }
summary > .issueChevron { margin-left: auto; color: var(--agent-muted); font-size: 11px; }
[open] .issueChevron { transform: rotate(180deg); }
p { margin: 2px 0 7px; overflow-wrap: anywhere; }
button { min-height: 32px; flex: none; padding: 0 3px; border: 0; color: var(--agent-accent); background: transparent; font: inherit; font-weight: 500; cursor: pointer; }
button:focus-visible,summary:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; border-radius: 3px; }
</style>
