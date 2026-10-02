<template>
  <el-dropdown
    ref="dropdownRef"
    trigger="click"
    placement="top-start"
    :offset="12"
    :show-arrow="false"
    :hide-on-click="false"
    :disabled="disabled"
    :popper-class="['mindmapAgentAddPopper', { 'is-dark': dark }]"
    @visible-change="onVisibleChange"
    @command="select"
  >
    <button
      ref="addButtonRef"
      type="button"
      class="agentAddButton"
      :class="{ 'is-expanded': expanded }"
      aria-label="添加附件或模版"
      title="添加附件或模版"
      aria-haspopup="menu"
      :aria-expanded="expanded"
      :disabled="disabled"
      @keydown.esc="closeFromTrigger"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
    </button>
    <template #dropdown>
      <div ref="menuRef" class="agentAddMenuShell" @keydown.capture="onMenuKeydown">
        <el-dropdown-menu class="agentAddMenu" aria-label="添加内容">
          <el-dropdown-item command="attachment" :disabled="attachmentDisabled">
            <span class="agentAddMenuIcon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M20 12.5 12.4 20a4.5 4.5 0 0 1-6.4-6.4l7.9-7.9a3 3 0 0 1 4.3 4.3l-7.9 7.9a1.5 1.5 0 0 1-2.2-2.2l7.2-7.2" /></svg></span>
            <span class="agentAddMenuCopy"><strong>添加附件</strong><small>上传文件，作为内容参考</small></span>
          </el-dropdown-item>
          <el-dropdown-item
            data-template-trigger
            command="template"
            :disabled="templateDisabled"
            :class="{ 'is-template-open': templateExpanded }"
            aria-haspopup="dialog"
            :aria-expanded="templateExpanded"
            @keydown.right.stop.prevent="openTemplates"
            @pointermove="keepTemplateFocus"
          >
            <span class="agentAddMenuIcon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M4 9h16M10 9v12M14 13h3M14 17h3" /></svg></span>
            <span class="agentAddMenuCopy"><strong>添加模版</strong><small>{{ hasTemplate ? '已添加模版，移除后可更换' : '从模版文件夹选择脑图' }}</small></span>
            <svg class="agentAddMenuArrow" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
          </el-dropdown-item>
          <li class="agentAddMenuHint" role="presentation">合计最多 5 个 · 附件每个 10 MB · 模版限 1 个</li>
        </el-dropdown-menu>
        <section
          v-if="templateExpanded"
          ref="templatePanelRef"
          class="agentTemplateMenu"
          :style="templatePanelStyle"
          role="dialog"
          aria-label="选择脑图模版"
          :aria-busy="templateLoading || templateSelecting"
        >
          <header class="agentTemplateHeader">
            <button type="button" class="agentTemplateBack" aria-label="返回添加菜单" @click="closeTemplates(true)">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m12 4-6 6 6 6" /></svg>
            </button>
            <div><strong>选择模版</strong><small>“模版”文件夹中的脑图</small></div>
          </header>
          <div class="agentTemplateSearch">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
            <input ref="searchInputRef" :value="query" type="search" maxlength="100" placeholder="搜索模版名称" aria-label="搜索模版名称" :disabled="templateSelecting" @input="searchTemplates" @keydown.down.prevent="focusTemplate(0)" />
            <button v-if="query" type="button" aria-label="清除搜索" :disabled="templateSelecting" @click="clearSearch">×</button>
          </div>
          <div ref="templateListRef" class="agentTemplateList" @keydown="onListKeydown">
            <button
              v-for="(row, index) in templates"
              :key="row.id ?? index"
              type="button"
              class="agentTemplateRow"
              :disabled="templateSelecting || templateLoading"
              :title="`${row.name || '未命名脑图'}\n${row.folderPath || row.folderName || '模版'}`"
              @click="selectTemplate(row)"
            >
              <span class="agentTemplateRowIcon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="3" y="9" width="6" height="6" rx="1.5" /><rect x="15" y="3" width="6" height="6" rx="1.5" /><rect x="15" y="15" width="6" height="6" rx="1.5" /><path d="M9 12h3V6h3M12 12v6h3" /></svg></span>
              <span class="agentTemplateRowCopy"><strong>{{ row.name || '未命名脑图' }}</strong><small>{{ row.folderPath || row.folderName || '模版' }}</small></span>
              <span v-if="Number.isFinite(row.nodeCount)" class="agentTemplateNodeCount">{{ row.nodeCount }} 节点</span>
            </button>
            <p v-if="templateLoading && !templates.length" class="agentTemplateStatus" role="status">正在加载模版…</p>
            <p v-else-if="!templates.length && !templateError" class="agentTemplateStatus" role="status">{{ query.trim() ? '没有找到匹配的模版' : '“模版”文件夹中暂无可用脑图' }}</p>
            <div v-if="templateError" class="agentTemplateStatus" role="alert">
              <p>{{ templateError }}</p>
              <button type="button" class="agentTemplateTextButton" :disabled="templateLoading || templateSelecting" @click="retrySearch">重新加载</button>
            </div>
            <button v-else-if="templateHasMore" type="button" class="agentTemplateMore" :disabled="templateLoading || templateSelecting" @click="emit('template-more')">{{ templateLoading ? '正在加载…' : '加载更多' }}</button>
          </div>
          <p class="agentTemplateFooter" role="status">{{ templateSelecting ? '正在添加模版…' : '仅约束样式、节点关系和标签用法，内容按你的需求生成' }}</p>
        </section>
      </div>
    </template>
  </el-dropdown>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  active: Boolean,
  disabled: Boolean,
  attachmentDisabled: Boolean,
  templateDisabled: Boolean,
  hasTemplate: Boolean,
  dark: Boolean,
  templates: { type: Array, default: () => [] },
  templateLoading: Boolean,
  templateError: { type: String, default: '' },
  templateHasMore: Boolean,
  templateSelecting: Boolean,
})
const emit = defineEmits(['attachment', 'template-open', 'template-search', 'template-more', 'template-select'])
const dropdownRef = ref(null)
const addButtonRef = ref(null)
const menuRef = ref(null)
const templatePanelRef = ref(null)
const searchInputRef = ref(null)
const templateListRef = ref(null)
const expanded = ref(false)
const templateExpanded = ref(false)
const templatePanelStyle = ref({ visibility: 'hidden' })
const query = ref('')
let searchTimer
let positionFrame
let focusFrame
let focusGeneration = 0
let restoreTriggerFocus = false

function cancelFocus() {
  focusGeneration += 1
  cancelAnimationFrame(focusFrame)
}

async function focusAfterRender(getTarget, isCurrent) {
  cancelFocus()
  const generation = focusGeneration
  await nextTick()
  if (generation !== focusGeneration) return
  // DropdownItem schedules its own roving focus as the click/keydown settles.
  // Focus the real DOM element after that work and the panel's Vue update.
  focusFrame = requestAnimationFrame(() => {
    if (generation !== focusGeneration || !isCurrent()) return
    const target = getTarget()
    if (target?.isConnected && !target.disabled) target.focus({ preventScroll: true })
  })
}

function positionTemplatePanel() {
  if (!templateExpanded.value || !menuRef.value || !templatePanelRef.value) return
  const anchor = menuRef.value.getBoundingClientRect()
  const panel = templatePanelRef.value.getBoundingClientRect()
  const margin = 12
  const gap = 8
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  // Keep the parent menu stationary. Prefer a separate card on its right,
  // then its left; small viewports show the card over the parent menu.
  let left = anchor.right + gap
  if (left + panel.width > viewportWidth - margin) left = anchor.left - gap - panel.width
  if (left < margin) left = Math.max(margin, Math.min(anchor.left, viewportWidth - panel.width - margin))
  templatePanelStyle.value = {
    left: `${left}px`,
    top: `${Math.max(margin, Math.min(anchor.top, viewportHeight - panel.height - margin))}px`,
  }
}

function schedulePosition() {
  cancelAnimationFrame(positionFrame)
  positionFrame = requestAnimationFrame(positionTemplatePanel)
}

function closeTemplates(restoreFocus = false) {
  clearTimeout(searchTimer)
  cancelAnimationFrame(positionFrame)
  cancelFocus()
  templateExpanded.value = false
  window.removeEventListener('resize', schedulePosition)
  window.removeEventListener('scroll', schedulePosition, true)
  if (restoreFocus) {
    focusAfterRender(() => menuRef.value?.querySelector('[data-template-trigger]'), () => expanded.value && !templateExpanded.value)
  }
}

function close(restoreFocus = true) {
  restoreTriggerFocus = restoreFocus && expanded.value
  closeTemplates()
  dropdownRef.value?.handleClose()
}

function onVisibleChange(visible) {
  expanded.value = visible
  if (!visible) {
    closeTemplates()
    query.value = ''
    if (restoreTriggerFocus) {
      restoreTriggerFocus = false
      focusAfterRender(() => addButtonRef.value, () => props.active && !expanded.value
        && (!document.activeElement || document.activeElement === document.body
          || document.activeElement === addButtonRef.value || menuRef.value?.contains(document.activeElement)))
    }
  } else {
    restoreTriggerFocus = false
  }
}

function keepTemplateFocus(event) {
  if (templateExpanded.value) event.preventDefault()
}

async function openTemplates() {
  if (props.disabled || props.templateDisabled) return
  if (!templateExpanded.value) {
    query.value = ''
    templatePanelStyle.value = { visibility: 'hidden' }
    templateExpanded.value = true
    window.addEventListener('resize', schedulePosition)
    window.addEventListener('scroll', schedulePosition, true)
    emit('template-open')
  }
  await nextTick()
  positionTemplatePanel()
  focusAfterRender(() => searchInputRef.value, () => expanded.value && templateExpanded.value)
}

function select(command) {
  if (props.disabled) return
  if (command === 'attachment' && !props.attachmentDisabled) {
    close(false)
    emit('attachment')
  }
  if (command === 'template') openTemplates()
}

function searchTemplates(event) {
  query.value = event.target.value
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => emit('template-search', query.value.trim()), 250)
}

function clearSearch() {
  clearTimeout(searchTimer)
  query.value = ''
  emit('template-search', '')
  searchInputRef.value?.focus()
}

function retrySearch() {
  clearTimeout(searchTimer)
  emit('template-search', query.value.trim())
}

function selectTemplate(row) {
  if (!props.disabled && !props.templateDisabled && !props.templateSelecting && !props.templateLoading) emit('template-select', row)
}

function focusTemplate(index) {
  const rows = templateListRef.value?.querySelectorAll('.agentTemplateRow:not(:disabled)') || []
  rows[Math.max(0, Math.min(index, rows.length - 1))]?.focus()
}

function onListKeydown(event) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  const rows = Array.from(templateListRef.value?.querySelectorAll('.agentTemplateRow:not(:disabled)') || [])
  const index = rows.indexOf(event.target)
  if (index < 0) return
  event.preventDefault()
  if (event.key === 'ArrowUp' && index === 0) return searchInputRef.value?.focus()
  focusTemplate(event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1 : index + (event.key === 'ArrowDown' ? 1 : -1))
}

function onMenuKeydown(event) {
  const inPanel = templatePanelRef.value?.contains(event.target)
  const atInputStart = event.target !== searchInputRef.value || (event.target.selectionStart === 0 && event.target.selectionEnd === 0)
  if (event.key === 'Escape' || (event.key === 'ArrowLeft' && inPanel && atInputStart)) {
    event.preventDefault()
    event.stopPropagation()
    if (templateExpanded.value) closeTemplates(true)
    else close()
  }
}

function closeFromTrigger(event) {
  if (!expanded.value) return
  event.preventDefault()
  event.stopPropagation()
  if (templateExpanded.value) closeTemplates(true)
  else close()
}

watch(() => [props.templates.length, props.templateLoading, props.templateError, props.templateHasMore], () => {
  if (templateExpanded.value) nextTick(schedulePosition)
})
watch(() => [props.active, props.disabled], ([active, disabled]) => {
  if (!active || disabled) close(false)
})
onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  closeTemplates()
})
defineExpose({ close })
</script>

<style scoped>
.agentAddButton { display: grid; width: 32px; height: 32px; flex: none; padding: 0; place-items: center; border: 1px solid var(--agent-border); border-radius: 50%; background: var(--ai-card-bg); color: var(--agent-muted); cursor: pointer; transition: background .16s, color .16s; }
.agentAddButton:hover:not(:disabled),.agentAddButton.is-expanded { background: var(--agent-hover); color: var(--agent-ink); }
.agentAddButton:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 2px; }
.agentAddButton:disabled { opacity: .55; cursor: not-allowed; }
.agentAddButton svg { width: 17px; height: 17px; }
@media (prefers-reduced-motion: reduce) { .agentAddButton { transition: none; } }
</style>

<style lang="scss">
.mindmapAgentAddPopper.el-popper {
  --add-surface: #fff;
  --add-ink: #303133;
  --add-muted: #7a7c82;
  --add-border: #e5e5e8;
  --add-hover: #f4f4f6;
  --add-accent: #7255ce;
  z-index: 4300 !important;
  max-width: calc(100vw - 24px);
  border: 1px solid var(--add-border);
  border-radius: 14px;
  background: var(--add-surface);
  box-shadow: 0 8px 24px -12px rgb(25 25 30 / 38%), 0 1px 4px -1px rgb(25 25 30 / 14%);
  overflow: visible;
  &.is-dark { --add-surface: #252527; --add-ink: #ededee; --add-muted: #a0a0a8; --add-border: #3b3b40; --add-hover: #333337; --add-accent: #b09ae9; }
  > .el-scrollbar, > .el-scrollbar > .el-scrollbar__wrap { overflow: visible; }
  .agentAddMenuShell { width: 268px; max-width: calc(100vw - 26px); }
  // Element Plus gives dropdown menus z-index: 10. Keep this menu below its
  // sibling panel when narrow viewports place the template card over it.
  .agentAddMenu { position: relative; z-index: 0; box-sizing: border-box; width: 100%; padding: 6px; border-radius: 14px; background: var(--add-surface); }
  .el-dropdown-menu__item { gap: 10px; padding: 9px 8px; border-radius: 10px; color: var(--add-ink); line-height: 1.5; white-space: normal; }
  .el-dropdown-menu__item + .el-dropdown-menu__item { margin-top: 4px; }
  .el-dropdown-menu__item:not(.is-disabled):hover,.el-dropdown-menu__item:not(.is-disabled):focus,.el-dropdown-menu__item.is-template-open { background: var(--add-hover); color: var(--add-ink); }
  .el-dropdown-menu__item.is-disabled { opacity: .48; }
  .agentAddMenuIcon { display: grid; flex: none; width: 28px; height: 28px; place-items: center; border-radius: 8px; background: var(--add-hover); color: var(--add-muted); }
  .agentAddMenuIcon svg { width: 16px; height: 16px; margin: 0; }
  .agentAddMenuCopy { min-width: 0; flex: 1; }
  .agentAddMenuCopy strong { display: block; font-size: 13px; font-weight: 550; }
  .agentAddMenuCopy small { display: block; margin-top: 2px; color: var(--add-muted); font-size: 11px; }
  .agentAddMenuArrow { flex: none; width: 14px; height: 14px; margin: 0; color: var(--add-muted); }
  .agentAddMenuHint { margin: 6px 8px 2px; padding-top: 8px; border-top: 1px solid var(--add-border); color: var(--add-muted); font-size: 10px; line-height: 1.5; list-style: none; }
  .agentTemplateMenu { position: fixed; z-index: 1; display: flex; flex-direction: column; box-sizing: border-box; width: 340px; max-width: calc(100vw - 24px); max-height: min(440px, calc(100dvh - 24px)); border: 1px solid var(--add-border); border-radius: 14px; background: var(--add-surface); color: var(--add-ink); box-shadow: 0 12px 36px -12px rgb(25 25 30 / 35%), 0 1px 4px rgb(25 25 30 / 10%); overflow: hidden; }
  .agentTemplateHeader { display: flex; flex: none; gap: 8px; align-items: center; padding: 13px 12px 10px; }
  .agentTemplateHeader strong { display: block; font-size: 13px; font-weight: 600; line-height: 1.5; }
  .agentTemplateHeader small { display: block; color: var(--add-muted); font-size: 11px; line-height: 1.5; }
  .agentTemplateMenu button { font-family: inherit; cursor: pointer; }
  .agentTemplateMenu button:disabled { cursor: default; opacity: .55; }
  .agentTemplateMenu button:focus-visible { outline: 2px solid var(--add-accent); outline-offset: -2px; }
  .agentTemplateBack { display: grid; flex: none; width: 25px; height: 28px; padding: 3px; place-items: center; border: 0; border-radius: 6px; color: var(--add-muted); background: transparent; }
  .agentTemplateBack:hover { background: var(--add-hover); color: var(--add-ink); }
  .agentTemplateBack svg { width: 16px; height: 16px; }
  .agentTemplateSearch { display: flex; flex: none; align-items: center; gap: 7px; min-width: 0; margin: 0 12px 8px; padding: 7px 9px; border: 1px solid var(--add-border); border-radius: 8px; background: var(--add-hover); }
  .agentTemplateSearch:focus-within { border-color: var(--add-accent); }
  .agentTemplateSearch > svg { flex: none; width: 15px; height: 15px; color: var(--add-muted); }
  .agentTemplateSearch input { width: 100%; min-width: 0; padding: 0; border: 0; outline: 0; color: var(--add-ink); background: transparent; font: inherit; font-size: 12px; line-height: 1.6; }
  .agentTemplateSearch input::-webkit-search-cancel-button { -webkit-appearance: none; }
  .agentTemplateSearch input::placeholder { color: var(--add-muted); }
  .agentTemplateSearch > button { display: grid; flex: none; width: 18px; height: 18px; padding: 0; place-items: center; border: 0; border-radius: 4px; background: transparent; color: var(--add-muted); font-size: 17px; line-height: 1; }
  .agentTemplateList { min-height: 72px; min-width: 0; padding: 0 6px 6px; overflow: auto; overscroll-behavior: contain; }
  .agentTemplateRow { display: flex; align-items: center; gap: 9px; box-sizing: border-box; width: 100%; padding: 9px 7px; border: 0; border-radius: 8px; background: transparent; color: var(--add-ink); text-align: left; }
  .agentTemplateRow:hover:not(:disabled),.agentTemplateRow:focus-visible { background: var(--add-hover); }
  .agentTemplateRowIcon { display: grid; flex: none; width: 30px; height: 32px; place-items: center; border: 1px solid var(--add-border); border-radius: 7px; background: var(--add-hover); color: var(--add-accent); }
  .agentTemplateRowIcon svg { width: 18px; height: 18px; }
  .agentTemplateRowCopy { flex: 1; min-width: 0; }
  .agentTemplateRowCopy strong,.agentTemplateRowCopy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .agentTemplateRowCopy strong { font-size: 12px; font-weight: 500; line-height: 1.7; }
  .agentTemplateRowCopy small { color: var(--add-muted); font-size: 10px; line-height: 1.6; }
  .agentTemplateNodeCount { flex: none; color: var(--add-muted); font-size: 10px; white-space: nowrap; }
  .agentTemplateStatus { margin: 0; padding: 20px 12px; color: var(--add-muted); text-align: center; font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
  .agentTemplateStatus p { margin: 0 0 8px; }
  .agentTemplateTextButton,.agentTemplateMore { border: 0; border-radius: 6px; background: transparent; color: var(--add-accent); font-size: 12px; line-height: 1.6; }
  .agentTemplateTextButton { padding: 3px 8px; }
  .agentTemplateMore { display: block; width: 100%; padding: 9px; }
  .agentTemplateTextButton:hover:not(:disabled),.agentTemplateMore:hover:not(:disabled) { background: var(--add-hover); }
  .agentTemplateFooter { flex: none; margin: 0; padding: 9px 12px; border-top: 1px solid var(--add-border); color: var(--add-muted); font-size: 10px; line-height: 1.6; }
}
</style>
