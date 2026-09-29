<!-- Stop glyph from Open Design ChatComposer.tsx / ComposerStopIcon (Apache-2.0).
     The visible label distinguishes stopping execution from pausing preview. -->
<template>
  <el-button class="composerStopButton" aria-label="停止任务并保留已生成结果" title="停止任务并保留已生成结果" :loading="stopping" :disabled="disabled" @click="$emit('stop')">
    <svg v-if="!stopping" width="24" height="24" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true" focusable="false"><path d="M18 9.00004C20.7614 9.00005 23 11.2386 23 14V18C23 20.7614 20.7614 22.9999 18 23L14 23C11.2386 23 9 20.7614 9 18V14C9 11.2386 11.2386 9.00001 14 9.00002L18 9.00004Z" /></svg>{{ stopping ? '停止中' : '停止' }}
  </el-button>
</template>
<script setup>
defineProps({ stopping: Boolean, disabled: Boolean })
defineEmits(['stop'])
</script>
<style scoped>
.composerStopButton { height: 32px; padding: 3px 8px 3px 2px; margin-left: 4px; border-radius: 7px; border-color: var(--agent-border); color: var(--agent-ink); background: var(--ai-panel-bg); font-size: 12px; }
.composerStopButton.is-loading { padding-left: 8px; }
.composerStopButton:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
</style>
