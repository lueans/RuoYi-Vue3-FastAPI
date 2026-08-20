<template>
  <div
    class="contextmenuContainer listBox"
    v-if="isShow"
    ref="contextmenuRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    :class="{ isDark: isDark }"
    role="menu"
    :aria-label="type === 'node' ? '节点操作菜单' : '画布操作菜单'"
    @keydown="onMenuKeydown"
  >
    <template v-for="(group, groupIndex) in activeMenuGroups" :key="`${type}-${groupIndex}`">
      <div v-if="groupIndex > 0" class="splitLine" role="separator"></div>
      <template v-for="item in group" :key="item.key">
        <div
          v-if="item.children"
          class="submenu"
          :class="{ open: expandedSubmenu === item.key }"
          @mouseenter="expandedSubmenu = item.key"
          @mouseleave="expandedSubmenu = ''"
        >
          <button
            class="item"
            type="button"
            role="menuitem"
            aria-haspopup="menu"
            :data-menu-key="item.key"
            :aria-expanded="expandedSubmenu === item.key"
            @click="toggleSubmenu(item.key)"
            @focus="expandedSubmenu = item.key"
          >
            <span class="name">{{ item.label }}</span>
            <span aria-hidden="true">›</span>
          </button>
          <div
            v-show="expandedSubmenu === item.key"
            class="subItems listBox"
            :class="{ isDark: isDark, showLeft: subItemsShowLeft }"
            role="menu"
            :aria-label="item.label"
          >
            <button
              class="item"
              v-for="child in item.children"
              :key="child.key"
              type="button"
              role="menuitem"
              @click="runMenuItem(child)"
            >
              <span class="name">{{ child.label }}</span>
            </button>
          </div>
        </div>
        <button
          v-else
          class="item"
          :class="{ danger: item.danger }"
          type="button"
          role="menuitem"
          :disabled="isMenuItemDisabled(item)"
          @click="runMenuItem(item)"
          @focus="expandedSubmenu = ''"
        >
          <span class="name">{{ item.label }}</span>
          <span class="desc" v-if="item.shortcut">{{ item.shortcut }}</span>
          <span class="desc" v-else-if="item.checked" aria-hidden="true">✓</span>
        </button>
      </template>
    </template>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { isCurrentMindmapEventSource } from '@/utils/mindmap-event'
import { store, actions } from './useStore'
import { copyMindmapPngBlob, copyMindmapText } from '@/utils/mindmap-clipboard'
import { stringifyJsonValueIterative } from '@mind-map/src/utils/jsonClone'

const props = defineProps({
  mindMap: {
    type: Object,
    default: null
  }
})

const isShow = ref(false)
const left = ref(-9999)
const top = ref(-9999)
const node = ref(null)
const type = ref('')
const isMousedown = ref(false)
const mousedownX = ref(0)
const mousedownY = ref(0)
const subItemsShowLeft = ref(false)
const isNodeMousedown = ref(false)
const contextmenuRef = ref(null)
const expandedSubmenu = ref('')

const enableCopyToClipboardApi = !!navigator.clipboard

const isDark = computed(() => store.localConfig.isDark)
const isZenMode = computed(() => store.localConfig.isZenMode)
const isReadonly = computed(() => store.isReadonly)

const insertNodeBtnDisabled = computed(() => {
  return !node.value || node.value.isRoot || node.value.isGeneralization
})

const upNodeBtnDisabled = computed(() => {
  if (!node.value || node.value.isRoot || node.value.isGeneralization) return true
  const siblings = node.value.parent?.children || []
  return siblings.findIndex(item => item === node.value) === 0
})

const downNodeBtnDisabled = computed(() => {
  if (!node.value || node.value.isRoot || node.value.isGeneralization) return true
  const siblings = node.value.parent?.children || []
  return siblings.findIndex(item => item === node.value) === siblings.length - 1
})

const isGeneralization = computed(() => {
  return node.value?.isGeneralization || false
})

const hasHyperlink = computed(() => {
  return !!node.value?.getData?.('hyperlink')
})

const hasNote = computed(() => {
  return !!node.value?.getData?.('note')
})

const nodeMenuGroups = computed(() => [
  [
    { key: 'insert-sibling', label: '插入同级节点', shortcut: 'Enter', command: 'INSERT_NODE', write: true, disabled: () => insertNodeBtnDisabled.value },
    { key: 'insert-child', label: '插入子级节点', shortcut: 'Tab', command: 'INSERT_CHILD_NODE', write: true, disabled: () => isGeneralization.value },
    { key: 'insert-parent', label: '插入父节点', shortcut: 'Shift + Tab', command: 'INSERT_PARENT_NODE', write: true, disabled: () => insertNodeBtnDisabled.value },
    { key: 'insert-summary', label: '插入概要', shortcut: 'Ctrl + G', command: 'ADD_GENERALIZATION', write: true, disabled: () => insertNodeBtnDisabled.value },
  ],
  [
    { key: 'move-up', label: '上移节点', shortcut: 'Ctrl + ↑', command: 'UP_NODE', write: true, disabled: () => upNodeBtnDisabled.value },
    { key: 'move-down', label: '下移节点', shortcut: 'Ctrl + ↓', command: 'DOWN_NODE', write: true, disabled: () => downNodeBtnDisabled.value },
    { key: 'collapse-children', label: '收起所有下级节点', command: 'UNEXPAND_ALL' },
    { key: 'expand-children', label: '展开所有下级节点', command: 'EXPAND_ALL' },
  ],
  [
    { key: 'remove-node', label: '删除节点', shortcut: 'Delete', command: 'REMOVE_NODE', danger: true, write: true },
    { key: 'remove-current-node', label: '仅删除当前节点', shortcut: 'Shift + Backspace', command: 'REMOVE_CURRENT_NODE', danger: true, write: true },
  ],
  [
    { key: 'copy-node', label: '复制节点', shortcut: 'Ctrl + C', command: 'COPY_NODE', disabled: () => isGeneralization.value },
    { key: 'cut-node', label: '剪切节点', shortcut: 'Ctrl + X', command: 'CUT_NODE', write: true, disabled: () => isGeneralization.value },
    { key: 'paste-node', label: '粘贴节点', shortcut: 'Ctrl + V', command: 'PASTE_NODE', write: true },
  ],
  [
    { key: 'remove-link', label: '移除超链接', command: 'REMOVE_HYPERLINK', write: true, visible: () => hasHyperlink.value },
    { key: 'remove-note', label: '移除备注', command: 'REMOVE_NOTE', write: true, visible: () => hasNote.value },
    { key: 'remove-style', label: '一键去除自定义样式', command: 'REMOVE_CUSTOM_STYLES', write: true },
    { key: 'export-node', label: '导出该节点为图片', command: 'EXPORT_CUR_NODE_TO_PNG' },
  ],
])

const canvasMenuGroups = computed(() => {
  const copyChildren = [
    { key: 'copy-smm', label: 'SMM', action: 'copy', value: 'smm' },
    { key: 'copy-json', label: 'JSON', action: 'copy', value: 'json' },
    { key: 'copy-markdown', label: 'Markdown', action: 'copy', value: 'md' },
    { key: 'copy-text', label: 'Txt', action: 'copy', value: 'txt' },
  ]
  if (enableCopyToClipboardApi) {
    copyChildren.push({ key: 'copy-image', label: '图片', action: 'copy', value: 'png' })
  }
  return [
    [
      { key: 'return-center', label: '回到根节点', shortcut: 'Ctrl + Enter', command: 'RETURN_CENTER' },
    ],
    [
      { key: 'expand-all', label: '展开所有', command: 'EXPAND_ALL' },
      { key: 'collapse-all', label: '收起所有', command: 'UNEXPAND_ALL' },
      {
        key: 'expand-level',
        label: '展开到',
        children: Array.from({ length: 6 }, (_, index) => ({
          key: `expand-level-${index + 1}`,
          label: `${['一', '二', '三', '四', '五', '六'][index]}级主题`,
          command: 'UNEXPAND_TO_LEVEL',
          args: [index + 1],
        })),
      },
    ],
    [
      { key: 'reset-layout', label: '一键整理布局', shortcut: 'Ctrl + L', command: 'RESET_LAYOUT', write: true },
      { key: 'fit-canvas', label: '适应画布', shortcut: 'Ctrl + I', command: 'FIT_CANVAS' },
      { key: 'zen-mode', label: '禅模式', command: 'TOGGLE_ZEN_MODE', checked: isZenMode.value },
    ],
    [
      { key: 'remove-all-styles', label: '一键去除所有节点自定义样式', command: 'REMOVE_ALL_NODE_CUSTOM_STYLES', write: true },
      { key: 'copy-to-clipboard', label: '复制到剪贴板', children: copyChildren },
    ],
  ]
})

const activeMenuGroups = computed(() => {
  const groups = type.value === 'node' ? nodeMenuGroups.value : canvasMenuGroups.value
  return groups
    .map(group => group.filter(isMenuItemVisible))
    .filter(group => group.length > 0)
})

function isMenuItemVisible(item) {
  if (isReadonly.value && item.write) return false
  return item.visible ? item.visible() : true
}

function isMenuItemDisabled(item) {
  return Boolean((item.write && isReadonly.value) || item.disabled?.())
}

function runMenuItem(item) {
  if (isMenuItemDisabled(item)) return
  if (item.action === 'copy') {
    copyToClipboard(item.value)
    return
  }
  exec(item.command, false, ...(item.args || []))
}

function toggleSubmenu(key) {
  expandedSubmenu.value = expandedSubmenu.value === key ? '' : key
}

// Calculate context menu position to stay within viewport
function getShowPosition(x, y) {
  if (!contextmenuRef.value) return { x, y }
  const rect = contextmenuRef.value.getBoundingClientRect()
  if (x + rect.width > window.innerWidth) {
    x = x - rect.width - 20
  }
  subItemsShowLeft.value = x + rect.width + 150 > window.innerWidth
  if (y + rect.height > window.innerHeight) {
    y = window.innerHeight - rect.height - 10
  }
  return { x: Math.max(8, x), y: Math.max(8, y) }
}

function getFocusableMenuItems() {
  if (!contextmenuRef.value) return []
  return [...contextmenuRef.value.querySelectorAll('button[role="menuitem"]:not(:disabled)')]
    .filter(item => item.getClientRects().length > 0)
}

function focusFirstMenuItem() {
  getFocusableMenuItems()[0]?.focus()
}

function moveMenuFocus(current, direction) {
  const items = getFocusableMenuItems()
  if (items.length === 0) return
  const currentIndex = items.indexOf(current)
  const nextIndex = currentIndex < 0
    ? 0
    : (currentIndex + direction + items.length) % items.length
  items[nextIndex]?.focus()
}

function onMenuKeydown(event) {
  const target = event.target.closest?.('button[role="menuitem"]')
  if (event.key === 'Escape') {
    event.preventDefault()
    hide()
    props.mindMap?.el?.focus?.()
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    moveMenuFocus(target, event.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    const items = getFocusableMenuItems()
    items[event.key === 'Home' ? 0 : items.length - 1]?.focus()
    return
  }
  if (event.key === 'ArrowRight' && target?.getAttribute('aria-haspopup') === 'menu') {
    event.preventDefault()
    const submenu = target.parentElement?.querySelector('.subItems')
    expandedSubmenu.value = target.dataset.menuKey || expandedSubmenu.value
    nextTick(() => submenu?.querySelector('button[role="menuitem"]:not(:disabled)')?.focus())
    return
  }
  if (event.key === 'ArrowLeft') {
    const submenu = target?.closest('.subItems')
    const trigger = submenu?.parentElement?.querySelector(':scope > button[aria-haspopup="menu"]')
    if (trigger) {
      event.preventDefault()
      trigger.focus()
    }
  }
}

// Show node context menu
function show(e, n, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  if (n?.mindMap && n.mindMap !== props.mindMap) return
  type.value = 'node'
  isShow.value = true
  node.value = n
  nextTick(() => {
    const { x, y } = getShowPosition(e.clientX + 10, e.clientY + 10)
    left.value = x
    top.value = y
    focusFirstMenuItem()
  })
}

function onNodeMousedown(_node, event, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  isNodeMousedown.value = event?.button === 2 || event?.which === 3
}

// SVG mousedown - track for right-click canvas menu
function onMousedown(e, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  if (e.button !== 2 && e.which !== 3) return
  mousedownX.value = e.clientX
  mousedownY.value = e.clientY
  isMousedown.value = true
}

// Mouseup - show canvas context menu if right-click without drag
function onMouseup(e, sourceMindMap = null) {
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  if (!isMousedown.value) {
    isNodeMousedown.value = false
    return
  }
  if (isNodeMousedown.value) {
    isNodeMousedown.value = false
    isMousedown.value = false
    return
  }
  isMousedown.value = false
  if (
    Math.abs(mousedownX.value - e.clientX) > 3 ||
    Math.abs(mousedownY.value - e.clientY) > 3
  ) {
    hide()
    return
  }
  showCanvasMenu(e)
}

// Show canvas (SVG) context menu
function showCanvasMenu(e) {
  type.value = 'svg'
  isShow.value = true
  node.value = null
  nextTick(() => {
    const { x, y } = getShowPosition(e.clientX + 10, e.clientY + 10)
    left.value = x
    top.value = y
    focusFirstMenuItem()
  })
}

// Hide context menu
function hide() {
  isShow.value = false
  left.value = -9999
  top.value = -9999
  type.value = ''
  node.value = null
  expandedSubmenu.value = ''
  isMousedown.value = false
  isNodeMousedown.value = false
}

function hideFromMindMapEvent(...args) {
  const sourceMindMap = args.at(-1)
  if (!isCurrentMindmapEventSource(sourceMindMap, props.mindMap)) return
  hide()
}

// Execute command
function exec(key, disabled, ...args) {
  if (disabled) return

  switch (key) {
    case 'COPY_NODE':
      props.mindMap?.renderer?.copy()
      break
    case 'CUT_NODE':
      props.mindMap?.renderer?.cut()
      break
    case 'PASTE_NODE':
      props.mindMap?.renderer?.paste()
      break
    case 'RETURN_CENTER':
      props.mindMap?.renderer?.setRootNodeCenter()
      break
    case 'TOGGLE_ZEN_MODE':
      actions.setLocalConfig({ isZenMode: !isZenMode.value })
      break
    case 'FIT_CANVAS':
      props.mindMap?.view?.fit()
      break
    case 'REMOVE_HYPERLINK':
      node.value?.setHyperlink('', '')
      break
    case 'REMOVE_NOTE':
      node.value?.setNote('')
      break
    case 'EXPORT_CUR_NODE_TO_PNG': {
      const rawText = node.value?.getData?.('text') || ''
      // Strip HTML tags to get plain text for filename
      const nodeText = rawText.replace(/<[^>]+>/g, '') || ''
      props.mindMap?.export('png', true, nodeText, false, node.value)
      break
    }
    case 'UNEXPAND_ALL': {
      const uid = node.value ? node.value.uid : ''
      bus.emit('execCommand', key, !uid, uid)
      break
    }
    case 'EXPAND_ALL':
      bus.emit('execCommand', key, node.value ? node.value.uid : '')
      break
    default:
      bus.emit('execCommand', key, ...args)
      break
  }
  hide()
}

// Copy to clipboard
async function copyToClipboard(copyType) {
  try {
    hide()
    let data = null
    let str = ''
    let copied = false
    switch (copyType) {
      case 'smm':
      case 'json':
        data = props.mindMap?.getData(true)
        str = stringifyJsonValueIterative(data)
        break
      case 'md': {
        data = props.mindMap?.getData()
        // Dynamic import for markdown transform
        let transformToMarkdown
        try {
          const mod = await import('@mind-map/src/parse/toMarkdown')
          transformToMarkdown = mod.transformToMarkdown
        } catch {
          throw new Error('Markdown 转换器加载失败')
        }
        str = transformToMarkdown(data)
        break
      }
      case 'txt': {
        data = props.mindMap?.getData()
        let transformToTxt
        try {
          const mod = await import('@mind-map/src/parse/toTxt')
          transformToTxt = mod.transformToTxt
        } catch {
          throw new Error('文本转换器加载失败')
        }
        str = transformToTxt(data)
        break
      }
      case 'png': {
        const png = await props.mindMap?.export('png', false)
        if (!png) throw new Error('脑图未生成 PNG 图片')
        let imgToDataUrl
        try {
          const mod = await import('@mind-map/src/utils')
          imgToDataUrl = mod.imgToDataUrl
        } catch {
          throw new Error('图片转换器加载失败')
        }
        const blob = await imgToDataUrl(png, true)
        await copyMindmapPngBlob(blob)
        copied = true
        break
      }
      default:
        throw new Error('不支持的复制格式')
    }
    if (!copied) copied = await copyMindmapText(str)
    if (!copied) throw new Error('复制操作没有完成')
    ElMessage.success('复制成功')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.message || '复制失败')
  }
}

onMounted(() => {
  bus.on('node_contextmenu', show)
  bus.on('node_click', hideFromMindMapEvent)
  bus.on('draw_click', hideFromMindMapEvent)
  bus.on('expand_btn_click', hideFromMindMapEvent)
  bus.on('svg_mousedown', onMousedown)
  bus.on('mouseup', onMouseup)
  bus.on('translate', hideFromMindMapEvent)
  bus.on('node_mousedown', onNodeMousedown)
})

onBeforeUnmount(() => {
  bus.off('node_contextmenu', show)
  bus.off('node_click', hideFromMindMapEvent)
  bus.off('draw_click', hideFromMindMapEvent)
  bus.off('expand_btn_click', hideFromMindMapEvent)
  bus.off('svg_mousedown', onMousedown)
  bus.off('mouseup', onMouseup)
  bus.off('translate', hideFromMindMapEvent)
  bus.off('node_mousedown', onNodeMousedown)
})

watch(() => props.mindMap, (mindMap, oldMindMap) => {
  if (mindMap !== oldMindMap) hide()
})
</script>

<style lang="scss" scoped>
.listBox {
  width: 240px;
  background: #fff;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1), 0 0 1px rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  padding: 6px;
  border: 1px solid #dee0e3;

  &.isDark {
    background: #2a2d32;
    border-color: #3d4046;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  }
}

.contextmenuContainer {
  position: fixed;
  font-size: 13px;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', sans-serif;
  font-weight: 400;
  color: #1f2329;
  z-index: 9999;

  &.isDark {
    color: #e5e6eb;

    .item {
      &:hover {
        background: hsla(0, 0%, 100%, 0.06);
      }
    }

    .splitLine {
      background-color: #3d4046;
    }

    .item .desc {
      color: #646a73;
    }
  }

  .splitLine {
    width: calc(100% - 8px);
    height: 1px;
    background-color: #f0f1f3;
    margin: 4px auto;
  }

  .item {
    position: relative;
    width: 100%;
    height: 32px;
    padding: 0 10px;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-radius: 6px;
    transition: background 0.1s;

    &.danger {
      color: #f54a45;
      &:hover {
        background: #fef0f0;
      }
    }

    &:hover {
      background: #f5f6f7;
    }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: -2px;
      background: #f5f6f7;
    }

    &:disabled {
      color: #bbbfc4;
      cursor: not-allowed;

      &:hover {
        background: transparent;
      }
    }

    .name {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      line-height: 1;
    }

    .desc {
      color: #8f959e;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 12px;
      margin-left: 16px;
      line-height: 1;
    }

  }

  .submenu {
    position: relative;

    .subItems {
      position: absolute;
      left: 100%;
      width: 150px;
      cursor: auto;
      top: -6px;

      &.showLeft {
        left: -150px;
      }

      .item {
        width: 100%;
      }
    }

    &:last-child .subItems {
      top: auto;
      bottom: -6px;
    }
  }
}
</style>
