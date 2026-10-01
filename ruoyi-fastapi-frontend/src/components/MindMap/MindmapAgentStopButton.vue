<!-- Stop glyph from Open Design ChatComposer.tsx / ComposerStopIcon (Apache-2.0).
     The visible label distinguishes stopping execution from pausing preview. -->
<template>
  <el-button class="composerStopButton" :class="{ 'is-compact': compact }" aria-label="停止任务并保留已生成结果" title="停止任务并保留已生成结果" :loading="stopping" :disabled="disabled" @click="$emit('stop')">
    <svg v-if="compact && !stopping" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7.4" y="6" width="3.4" height="12" rx="1.3"/><rect x="13.2" y="6" width="3.4" height="12" rx="1.3"/></svg>
    <svg v-else-if="!stopping" width="24" height="24" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true" focusable="false"><path d="M18 9.00004C20.7614 9.00005 23 11.2386 23 14V18C23 20.7614 20.7614 22.9999 18 23L14 23C11.2386 23 9 20.7614 9 18V14C9 11.2386 11.2386 9.00001 14 9.00002L18 9.00004Z" /></svg><span v-if="!compact">{{ stopping ? '停止中' : '停止' }}</span>
  </el-button>
</template>
<script setup>
defineProps({ stopping: Boolean, disabled: Boolean, compact: Boolean })
defineEmits(['stop'])
</script>
<style scoped>
.composerStopButton { height: 32px; padding: 3px 8px 3px 2px; margin-left: 4px; border-radius: 7px; border-color: var(--agent-border); color: var(--agent-ink); background: var(--ai-panel-bg); font-size: 12px; }
.composerStopButton.is-loading { padding-left: 8px; }
.composerStopButton:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
.composerStopButton.is-compact { position: relative; width: 34px; height: 34px; padding: 0; margin: 0; border: 0; border-radius: 50%; color: var(--ai-card-bg); background: color-mix(in oklch, var(--agent-accent) 88%, black); }
.composerStopButton.is-compact:hover { background: color-mix(in oklch, var(--agent-accent) 72%, black); }
.composerStopButton.is-compact svg { width: 17px; height: 17px; }
.composerStopButton.is-compact:not(.is-loading)::after { content: ''; position: absolute; inset: -3px; border: 2px solid color-mix(in oklch, var(--agent-accent) 50%, transparent); border-radius: 50%; animation: composer-stop-pulse 1.5s ease-out infinite; pointer-events: none; }
@keyframes composer-stop-pulse { from { transform: scale(.9); opacity: .85; } to { transform: scale(1.45); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .composerStopButton.is-compact::after { animation: none !important; opacity: .6; } }
</style>
