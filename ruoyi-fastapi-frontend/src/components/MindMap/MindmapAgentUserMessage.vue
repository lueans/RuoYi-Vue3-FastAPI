<template>
  <div class="agentUserMessage">
    <div class="userMessageContent">
      <p v-if="content" class="userMessageBubble">{{ content }}</p>
      <div class="userMessageContextRow">
        <span class="userMessageChipGroup" data-group="context" aria-label="本条消息的上下文">
          <span class="userMessageContextChip" :data-scope="messageContext.scope" :title="messageContext.title">
            <svg v-if="messageContext.scope === 'file'" class="userMessageContextIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M20 12.5 12.4 20a4.5 4.5 0 0 1-6.4-6.4l7.9-7.9a3 3 0 0 1 4.3 4.3l-7.9 7.9a1.5 1.5 0 0 1-2.2-2.2l7.2-7.2" /></svg>
            <svg v-else-if="messageContext.scope === 'all'" class="userMessageContextIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
              <circle cx="6" cy="7" r="2.3" /><circle cx="17.5" cy="6" r="2.3" /><circle cx="12" cy="16.5" r="2.3" />
              <path d="M7.7 8.6 10.9 14.4M15.7 7.6 13.3 14.4M8.2 6.3 15.3 6.1" />
            </svg>
            <svg v-else class="userMessageContextIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <rect x="3.2" y="8" width="8.4" height="8" rx="2.4" /><path d="M11.6 12h4.4" /><circle cx="18.4" cy="12" r="2.5" />
            </svg>
            <span class="userMessageContextLabel">{{ messageContext.label }}</span>
          </span>
        </span>
        <span v-if="visibleAttachments.length" class="userMessageChipGroup userMessageFileGroup" data-group="files" aria-label="已发送的附件">
          <span
            v-for="(attachment, index) in visibleAttachments"
            :key="`${attachment.id || attachment.name}:${index}`"
            class="userMessageAttachment"
            :data-purpose="attachment.purpose"
            :title="`${attachment.purpose === 'template' ? '模版' : '附件'}：${attachment.name}${attachment.sizeLabel ? ` · ${attachment.sizeLabel}` : ''}`"
          >
            <svg v-if="attachment.purpose === 'template'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="3" /><path d="M4 9h16M10 9v12" /></svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M20 12.5 12.4 20a4.5 4.5 0 0 1-6.4-6.4l7.9-7.9a3 3 0 0 1 4.3 4.3l-7.9 7.9a1.5 1.5 0 0 1-2.2-2.2l7.2-7.2" /></svg>
            <span v-if="attachment.purpose === 'template'" class="userMessageTemplateLabel">模版</span>
            <span class="userMessageAttachmentName">{{ attachment.name }}</span>
            <span v-if="attachment.sizeLabel" class="userMessageAttachmentSize">{{ attachment.sizeLabel }}</span>
          </span>
        </span>
      </div>
      <div class="userMessageMeta">
        <time
          v-if="sentTime"
          class="userMessageTime"
          :datetime="createdTime"
          :aria-label="`发送时间：${sentTime}`"
        >{{ sentTime }}</time>
        <button
          type="button"
          class="userMessageCopy"
          :class="{ 'is-copied': copied }"
          :disabled="copying || !content"
          :aria-label="copied ? '已复制内容' : '复制内容'"
          :title="copied ? '已复制' : '复制'"
          @click="copyContent"
        >
          <svg v-if="copied" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" /></svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="6" y="6" width="10" height="13" rx="2" /><path d="M9 6V4a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-1" /></svg>
          <span aria-live="polite">{{ copied ? '已复制' : '复制' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { copyMindmapText } from '@/utils/mindmap-clipboard'
import { formatAttachmentSize } from '@/utils/mindmap-ai-attachment-records'

const props = defineProps({
  content: { type: String, default: '' },
  jobId: { type: [String, Number], default: '' },
  createdTime: { type: String, default: '' },
  context: { type: Object, default: undefined },
  attachments: { type: Array, default: () => [] },
})

// This is the message's saved send context, never the live composer selection.
const messageContext = computed(() => {
  if (props.context === null) return { scope: 'unknown', label: '上下文不可用', title: '本条消息的发送上下文不可用' }
  const context = props.context || {}
  if (context.sourceMode === 'new') return { scope: 'new', label: '新建脑图', title: '新建脑图（未读取当前画布）' }
  if (context.sourceMode === 'file') {
    const name = typeof context.fileName === 'string' ? context.fileName.trim() : ''
    return { scope: 'file', label: name || '本地文件', title: name ? `本地文件：${name}` : '本地文件' }
  }
  if (!context.scopeType || context.scopeType === 'document') return { scope: 'all', label: '整个脑图', title: '整个脑图' }
  const nodes = (Array.isArray(context.contextNodes) ? context.contextNodes : [])
    .filter(node => node && typeof node === 'object')
  const labels = nodes.map(node => typeof node.label === 'string' ? node.label.trim() : '')
  if (nodes.length > 1) {
    return { scope: 'multi', label: `用户已经选择${nodes.length}个节点`, title: labels.filter(Boolean).join('、') || '已选节点' }
  }
  const label = labels[0] || (context.scopeType === 'branch' ? '当前分支' : '已选节点')
  const characters = Array.from(label)
  return { scope: 'one', label: characters.length > 10 ? `${characters.slice(0, 7).join('')}...` : label, title: label }
})

// History stores attachment metadata only; never render or copy file bodies.
const visibleAttachments = computed(() => (Array.isArray(props.attachments) ? props.attachments : [])
  .filter(attachment => attachment && typeof attachment.name === 'string' && attachment.name.trim())
  .map(attachment => ({
    id: typeof attachment.id === 'string' ? attachment.id : '',
    name: attachment.name,
    purpose: attachment.purpose === 'template' ? 'template' : 'reference',
    sizeLabel: attachment.purpose === 'template' ? '' : formatAttachmentSize(attachment.size),
  })))
const sentTime = computed(() => {
  const value = String(props.createdTime || '').trim()
  if (!value) return ''
  // Server wall-clock timestamps have no zone; ISO client timestamps retain
  // their offset and are displayed in the browser's local time.
  const date = new Date(value.replace(' ', 'T'))
  if (!Number.isFinite(date.getTime())) return ''
  const pad = value => String(value).padStart(2, '0')
  return `${String(date.getFullYear()).padStart(4, '0')}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}-${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
})
const copied = ref(false)
const copying = ref(false)
let resetTimer = null
let copyGeneration = 0

function resetCopyState() {
  copyGeneration += 1
  clearTimeout(resetTimer)
  resetTimer = null
  copied.value = false
  copying.value = false
}

async function copyContent() {
  if (copying.value || !props.content) return
  const generation = ++copyGeneration
  copying.value = true
  try {
    await copyMindmapText(props.content)
    if (generation !== copyGeneration) return
    copied.value = true
    clearTimeout(resetTimer)
    resetTimer = setTimeout(() => {
      copied.value = false
      resetTimer = null
    }, 1800)
  } catch (error) {
    if (generation === copyGeneration) ElMessage.error(error?.message || '复制失败，请手动选择内容')
  } finally {
    if (generation === copyGeneration) copying.value = false
  }
}

watch(() => [props.content, props.jobId], resetCopyState)
onBeforeUnmount(resetCopyState)
</script>

<style scoped>
.agentUserMessage {
  display: flex;
  align-self: flex-end;
  justify-self: end;
  flex-direction: row-reverse;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
  animation: user-message-in .25s cubic-bezier(.2, .9, .3, 1);
}

.userMessageContent { min-width: 0; max-width: 100%; }

.userMessageContextRow {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  max-width: 280px;
  margin-top: 6px;
  margin-left: auto;
}

.userMessageChipGroup {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  min-width: 0;
  max-width: 100%;
}

.userMessageFileGroup {
  box-sizing: border-box;
  justify-content: flex-end;
}

.userMessageContextChip,
.userMessageAttachment {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: min(220px, 100%);
  padding: 5px 6px 5px 10px;
  border: 1px solid var(--agent-border, oklch(0.916 0.004 285));
  border-radius: 999px;
  color: var(--agent-ink, oklch(0.205 0.006 285));
  font-size: 12.5px;
  line-height: 1.3;
}

.userMessageContextChip { background: var(--ai-card-bg, oklch(0.999 0.001 95)); }
.userMessageContextChip[data-scope='all'] { border-style: dashed; background: transparent; color: var(--agent-muted, oklch(0.555 0.008 285)); }
.userMessageContextChip[data-scope='unknown'] { background: transparent; color: var(--agent-muted, oklch(0.555 0.008 285)); }
.userMessageContextChip[data-scope='multi'] {
  border-color: color-mix(in oklch, var(--agent-node, oklch(0.52 0.20 266)) 32%, transparent);
  background: color-mix(in oklch, var(--agent-node, oklch(0.52 0.20 266)) 11%, transparent);
  color: color-mix(in oklch, var(--agent-node, oklch(0.52 0.20 266)) 80%, var(--agent-ink, oklch(0.205 0.006 285)));
}
.userMessageContextIcon { flex: none; width: 14px; height: 14px; color: var(--agent-node, oklch(0.52 0.20 266)); }
.userMessageContextChip[data-scope='all'] .userMessageContextIcon { color: inherit; }
.userMessageContextChip[data-scope='unknown'] .userMessageContextIcon { color: inherit; }
.userMessageContextLabel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.userMessageAttachment { background: var(--agent-surface, color-mix(in oklch, var(--agent-ink, oklch(0.205 0.006 285)) 6%, transparent)); }
.userMessageAttachment svg { flex: none; width: 14px; height: 14px; color: var(--agent-muted, oklch(0.555 0.008 285)); }
.userMessageAttachment[data-purpose='template'] { border-color: color-mix(in oklch, var(--agent-accent, oklch(0.60 0.20 288)) 28%, transparent); background: color-mix(in oklch, var(--agent-accent, oklch(0.60 0.20 288)) 8%, transparent); }
.userMessageAttachment[data-purpose='template'] svg,
.userMessageTemplateLabel { flex: none; color: var(--agent-accent, oklch(0.60 0.20 288)); }
.userMessageTemplateLabel { font-size: 11px; }
.userMessageAttachmentName { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.userMessageAttachmentSize { flex: none; color: var(--agent-muted, oklch(0.555 0.008 285)); font-size: 11px; font-family: ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, monospace; }

.userMessageBubble {
  box-sizing: border-box;
  width: fit-content;
  margin: 0;
  padding: 10px 14px;
  border: 1px solid color-mix(in oklch, var(--agent-accent, oklch(0.60 0.20 288)) 20%, transparent);
  border-radius: 14px;
  background: color-mix(in oklch, var(--agent-accent, oklch(0.60 0.20 288)) 12%, transparent);
  color: var(--agent-ink, oklch(0.205 0.006 285));
  font-size: 14px;
  font-weight: 400;
  line-height: 1.55;
  max-width: 280px;
  margin-left: auto;
  word-wrap: break-word;
  white-space: pre-wrap;
  text-wrap: pretty;
}

.userMessageMeta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
  padding-right: 2px;
}

.userMessageTime {
  flex: none;
  white-space: nowrap;
  font-family: ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, monospace;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--agent-muted, oklch(0.555 0.008 285));
  letter-spacing: .02em;
}

.userMessageCopy {
  display: inline-flex;
  align-items: center;
  flex: none;
  gap: 4px;
  padding: 3px 7px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--agent-muted, oklch(0.555 0.008 285));
  background: transparent;
  font: inherit;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.55;
  cursor: pointer;
  transition: background .14s, color .14s, border-color .14s;
}

.userMessageCopy:hover:not(:disabled) {
  color: var(--agent-ink, oklch(0.205 0.006 285));
  background: color-mix(in oklch, var(--agent-ink, oklch(0.205 0.006 285)) 6%, transparent);
  border-color: var(--agent-border, oklch(0.916 0.004 285));
}

.userMessageCopy svg { display: block; width: 12px; height: 12px; }
.userMessageCopy.is-copied { color: var(--agent-accent, oklch(0.60 0.20 288)); }
.userMessageCopy:disabled { cursor: default; }
.userMessageCopy:focus-visible { outline: 2px solid oklch(0.66 0.17 250); outline-offset: 2px; }

@keyframes user-message-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

@media (prefers-reduced-motion: reduce) {
  .agentUserMessage { animation: none; }
  .userMessageCopy { transition: none; }
}
</style>
