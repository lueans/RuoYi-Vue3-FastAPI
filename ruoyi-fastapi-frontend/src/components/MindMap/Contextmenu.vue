<template>
  <div
    class="contextmenuContainer listBox"
    v-if="isShow"
    ref="contextmenuRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    :class="{ isDark: isDark }"
  >
    <!-- Node context menu -->
    <template v-if="type === 'node'">
      <div
        class="item"
        @click="exec('INSERT_NODE', insertNodeBtnDisabled)"
        :class="{ disabled: insertNodeBtnDisabled }"
      >
        <span class="name">插入同级节点</span>
        <span class="desc">Enter</span>
      </div>
      <div
        class="item"
        @click="exec('INSERT_CHILD_NODE', isGeneralization)"
        :class="{ disabled: isGeneralization }"
      >
        <span class="name">插入子级节点</span>
        <span class="desc">Tab</span>
      </div>
      <div
        class="item"
        @click="exec('INSERT_PARENT_NODE', insertNodeBtnDisabled)"
        :class="{ disabled: insertNodeBtnDisabled }"
      >
        <span class="name">插入父节点</span>
        <span class="desc">Shift + Tab</span>
      </div>
      <div
        class="item"
        @click="exec('ADD_GENERALIZATION', insertNodeBtnDisabled)"
        :class="{ disabled: insertNodeBtnDisabled }"
      >
        <span class="name">插入概要</span>
        <span class="desc">Ctrl + G</span>
      </div>
      <div class="splitLine"></div>
      <div
        class="item"
        @click="exec('UP_NODE', upNodeBtnDisabled)"
        :class="{ disabled: upNodeBtnDisabled }"
      >
        <span class="name">上移节点</span>
        <span class="desc">Ctrl + &uarr;</span>
      </div>
      <div
        class="item"
        @click="exec('DOWN_NODE', downNodeBtnDisabled)"
        :class="{ disabled: downNodeBtnDisabled }"
      >
        <span class="name">下移节点</span>
        <span class="desc">Ctrl + &darr;</span>
      </div>
      <div class="item" @click="exec('UNEXPAND_ALL')">
        <span class="name">收起所有下级节点</span>
      </div>
      <div class="item" @click="exec('EXPAND_ALL')">
        <span class="name">展开所有下级节点</span>
      </div>
      <div class="splitLine"></div>
      <div class="item danger" @click="exec('REMOVE_NODE')">
        <span class="name">删除节点</span>
        <span class="desc">Delete</span>
      </div>
      <div class="item danger" @click="exec('REMOVE_CURRENT_NODE')">
        <span class="name">仅删除当前节点</span>
        <span class="desc">Shift + Backspace</span>
      </div>
      <div class="splitLine"></div>
      <div
        class="item"
        @click="exec('COPY_NODE', isGeneralization)"
        :class="{ disabled: isGeneralization }"
      >
        <span class="name">复制节点</span>
        <span class="desc">Ctrl + C</span>
      </div>
      <div
        class="item"
        @click="exec('CUT_NODE', isGeneralization)"
        :class="{ disabled: isGeneralization }"
      >
        <span class="name">剪切节点</span>
        <span class="desc">Ctrl + X</span>
      </div>
      <div class="item" @click="exec('PASTE_NODE')">
        <span class="name">粘贴节点</span>
        <span class="desc">Ctrl + V</span>
      </div>
      <div class="splitLine"></div>
      <div class="item" @click="exec('REMOVE_HYPERLINK')" v-if="hasHyperlink">
        <span class="name">移除超链接</span>
      </div>
      <div class="item" @click="exec('REMOVE_NOTE')" v-if="hasNote">
        <span class="name">移除备注</span>
      </div>
      <div class="item" @click="exec('REMOVE_CUSTOM_STYLES')">
        <span class="name">一键去除自定义样式</span>
      </div>
      <div class="item" @click="exec('EXPORT_CUR_NODE_TO_PNG')">
        <span class="name">导出该节点为图片</span>
      </div>
    </template>

    <!-- Canvas context menu -->
    <template v-if="type === 'svg'">
      <div class="item" @click="exec('RETURN_CENTER')">
        <span class="name">回到根节点</span>
        <span class="desc">Ctrl + Enter</span>
      </div>
      <div class="splitLine"></div>
      <div class="item" @click="exec('EXPAND_ALL')">
        <span class="name">展开所有</span>
      </div>
      <div class="item" @click="exec('UNEXPAND_ALL')">
        <span class="name">收起所有</span>
      </div>
      <div class="item">
        <span class="name">展开到</span>
        <span class="el-icon-arrow-right"></span>
        <div
          class="subItems listBox"
          :class="{ isDark: isDark, showLeft: subItemsShowLeft }"
          style="top: -10px"
        >
          <div
            class="item"
            v-for="(item, index) in expandList"
            :key="item"
            @click="exec('UNEXPAND_TO_LEVEL', false, index + 1)"
          >
            {{ item }}
          </div>
        </div>
      </div>
      <div class="splitLine"></div>
      <div class="item" @click="exec('RESET_LAYOUT')">
        <span class="name">一键整理布局</span>
        <span class="desc">Ctrl + L</span>
      </div>
      <div class="item" @click="exec('FIT_CANVAS')">
        <span class="name">适应画布</span>
        <span class="desc">Ctrl + i</span>
      </div>
      <div class="item" @click="exec('TOGGLE_ZEN_MODE')">
        <span class="name">禅模式</span>
        {{ isZenMode ? '√' : '' }}
      </div>
      <div class="splitLine"></div>
      <div class="item" @click="exec('REMOVE_ALL_NODE_CUSTOM_STYLES')">
        <span class="name">一键去除所有节点自定义样式</span>
      </div>
      <div class="item">
        <span class="name">复制到剪贴板</span>
        <span class="el-icon-arrow-right"></span>
        <div
          class="subItems listBox"
          :class="{ isDark: isDark, showLeft: subItemsShowLeft }"
          style="top: -130px"
        >
          <div
            class="item"
            v-for="item in copyList"
            :key="item.value"
            @click="copyToClipboard(item.value)"
          >
            {{ item.name }}
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { store, actions } from './useStore'

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

const enableCopyToClipboardApi = !!navigator.clipboard

const isDark = computed(() => store.localConfig.isDark)
const isZenMode = computed(() => store.localConfig.isZenMode)

const expandList = computed(() => [
  '一级主题',
  '二级主题',
  '三级主题',
  '四级主题',
  '五级主题',
  '六级主题',
])

const copyList = computed(() => {
  const list = [
    { name: 'SMM', value: 'smm' },
    { name: 'JSON', value: 'json' },
    { name: 'Markdown', value: 'md' },
    { name: 'Txt', value: 'txt' },
  ]
  if (enableCopyToClipboardApi) {
    list.push({ name: '图片', value: 'png' })
  }
  return list
})

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
  return { x, y }
}

// Show node context menu
function show(e, n) {
  type.value = 'node'
  isShow.value = true
  node.value = n
  nextTick(() => {
    const { x, y } = getShowPosition(e.clientX + 10, e.clientY + 10)
    left.value = x
    top.value = y
  })
}

function onNodeMousedown() {
  isNodeMousedown.value = true
}

// SVG mousedown - track for right-click canvas menu
function onMousedown(e) {
  if (e.which !== 3) return
  mousedownX.value = e.clientX
  mousedownY.value = e.clientY
  isMousedown.value = true
}

// Mouseup - show canvas context menu if right-click without drag
function onMouseup(e) {
  if (!isMousedown.value) return
  if (isNodeMousedown.value) {
    isNodeMousedown.value = false
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
  nextTick(() => {
    const { x, y } = getShowPosition(e.clientX + 10, e.clientY + 10)
    left.value = x
    top.value = y
  })
}

// Hide context menu
function hide() {
  isShow.value = false
  left.value = -9999
  top.value = -9999
  type.value = ''
  node.value = null
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
    let data
    let str
    switch (copyType) {
      case 'smm':
      case 'json':
        data = props.mindMap?.getData(true)
        str = JSON.stringify(data)
        break
      case 'md': {
        data = props.mindMap?.getData()
        // Dynamic import for markdown transform
        let transformToMarkdown
        try {
          const mod = await import('@mind-map/src/parse/toMarkdown')
          transformToMarkdown = mod.transformToMarkdown
        } catch {
          transformToMarkdown = () => ''
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
          transformToTxt = () => ''
        }
        str = transformToTxt(data)
        break
      }
      case 'png': {
        const png = await props.mindMap?.export('png', false)
        if (png) {
          let imgToDataUrl
          try {
            const mod = await import('@mind-map/src/utils')
            imgToDataUrl = mod.imgToDataUrl
          } catch {
            imgToDataUrl = null
          }
          if (imgToDataUrl) {
            const blob = await imgToDataUrl(png, true)
            if (navigator.clipboard && navigator.clipboard.write) {
              await navigator.clipboard.write([
                new ClipboardItem({ 'image/png': blob })
              ])
            }
          }
        }
        break
      }
      default:
        break
    }
    if (str) {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(str)
      } else {
        // Fallback copy
        const textArea = document.createElement('textarea')
        textArea.value = str
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
    }
    ElMessage.success('复制成功')
  } catch (error) {
    console.error(error)
    ElMessage.error('复制失败')
  }
}

onMounted(() => {
  bus.on('node_contextmenu', show)
  bus.on('node_click', hide)
  bus.on('draw_click', hide)
  bus.on('expand_btn_click', hide)
  bus.on('svg_mousedown', onMousedown)
  bus.on('mouseup', onMouseup)
  bus.on('translate', hide)
  bus.on('node_mousedown', onNodeMousedown)
})

onBeforeUnmount(() => {
  bus.off('node_contextmenu', show)
  bus.off('node_click', hide)
  bus.off('draw_click', hide)
  bus.off('expand_btn_click', hide)
  bus.off('svg_mousedown', onMousedown)
  bus.off('mouseup', onMouseup)
  bus.off('translate', hide)
  bus.off('node_mousedown', onNodeMousedown)
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
    height: 32px;
    padding: 0 10px;
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

      .subItems {
        visibility: visible;
      }
    }

    &.disabled {
      color: #bbbfc4;
      cursor: not-allowed;
      pointer-events: none;

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

    .subItems {
      position: absolute;
      left: 100%;
      visibility: hidden;
      width: 150px;
      cursor: auto;
      top: -6px;

      &.showLeft {
        left: -150px;
      }
    }
  }
}
</style>
