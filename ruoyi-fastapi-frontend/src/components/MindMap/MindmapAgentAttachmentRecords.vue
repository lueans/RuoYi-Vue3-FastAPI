<template>
  <section v-if="records.length" class="attachmentRecords" aria-label="文件解析记录">
    <p v-for="(warning, index) in warnings" :key="index" class="attachmentRecordWarning" role="status">{{ warning }}</p>
    <details>
      <summary>文件解析记录 <span>{{ parsedCount }}/{{ records.length }} 个已解析</span></summary>
      <ul>
        <li v-for="(file, index) in records" :key="`${file.id}:${index}`">
          <span class="attachmentRecordName" :title="file.name"><span v-if="file.purpose === 'template'" class="attachmentRecordTemplate">模版</span>{{ file.name }}</span>
          <span v-if="file.parsing.status === 'parsed'" class="attachmentRecordResult">
            {{ file.purpose === 'template' ? '脑图结构读取完成' : '文本提取完成' }} · {{ file.parsing.characterCount.toLocaleString('zh-CN') }} 字符
          </span>
          <span v-else class="attachmentRecordResult">解析记录不可用</span>
        </li>
      </ul>
      <p>记录客户端文本提取结果，不代表 AI 已阅读；不包含图片识别结果。</p>
    </details>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { buildMindmapAiAttachmentMetadata } from '@/utils/mindmap-ai-attachment-records'

const props = defineProps({ attachments: { type: Array, default: () => [] } })
const records = computed(() => buildMindmapAiAttachmentMetadata(props.attachments))
const parsedCount = computed(() => records.value.filter(file => file.parsing.status === 'parsed').length)
const warnings = computed(() => records.value.flatMap(file => (file.warnings || []).map(warning => `${file.name}：${warning}`)))
</script>

<style scoped>
.attachmentRecords { min-width: 0; margin: 0 0 12px; color: var(--agent-muted); font-size: 12px; line-height: 1.6; }
summary { cursor: pointer; overflow-wrap: anywhere; }
summary span { margin-left: 6px; font-size: 11px; }
summary:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 3px; border-radius: 3px; }
ul { display: grid; gap: 8px; padding: 0; margin: 10px 0; list-style: none; }
li { display: grid; gap: 2px; padding-left: 10px; }
.attachmentRecordName { color: var(--agent-ink); overflow-wrap: anywhere; }
.attachmentRecordTemplate { display: inline-block; margin-right: 5px; padding: 0 4px; border-radius: 4px; color: var(--agent-accent); background: color-mix(in oklch, var(--agent-accent) 10%, transparent); font-size: 10px; }
.attachmentRecordResult { font-size: 11px; }
.attachmentRecordWarning { margin: 0 0 8px; padding: 6px 8px; border-radius: 6px; color: var(--el-color-warning-dark-2, #9a6700); background: var(--el-color-warning-light-9, #fff8e6); overflow-wrap: anywhere; }
p { margin: 8px 0 0; font-size: 11px; }
</style>
