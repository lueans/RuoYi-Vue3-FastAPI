<template>
  <section v-if="records.length" class="attachmentRecords" aria-label="文件解析记录">
    <details>
      <summary>文件解析记录 <span>{{ parsedCount }}/{{ records.length }} 个已解析</span></summary>
      <ul>
        <li v-for="(file, index) in records" :key="`${file.id}:${index}`">
          <span class="attachmentRecordName" :title="file.name">{{ file.name }}</span>
          <span v-if="file.parsing.status === 'parsed'" class="attachmentRecordResult">
            文本提取完成 · {{ file.parsing.characterCount.toLocaleString('zh-CN') }} 字符
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
</script>

<style scoped>
.attachmentRecords { min-width: 0; margin: 0 0 12px; color: var(--agent-muted); font-size: 12px; line-height: 1.6; }
summary { cursor: pointer; overflow-wrap: anywhere; }
summary span { margin-left: 6px; font-size: 11px; }
summary:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 3px; border-radius: 3px; }
ul { display: grid; gap: 8px; padding: 0; margin: 10px 0; list-style: none; }
li { display: grid; gap: 2px; padding-left: 10px; }
.attachmentRecordName { color: var(--agent-ink); overflow-wrap: anywhere; }
.attachmentRecordResult { font-size: 11px; }
p { margin: 8px 0 0; font-size: 11px; }
</style>
