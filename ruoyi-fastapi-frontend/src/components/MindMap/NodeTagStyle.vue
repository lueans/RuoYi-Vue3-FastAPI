<template>
  <div
    class="nodeTagStyleContainer"
    :class="{ isDark: isDark }"
    v-show="show"
    ref="containerRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    @click.stop
    @mousedown.stop
  >
    <div class="row">
      <el-input v-model="tagText" size="small" style="width: 140px" @change="onTextChange" @keydown.stop />
      <el-button size="small" type="danger" text @click="deleteTag">删除</el-button>
    </div>
    <div class="row">
      <span class="label">位置</span>
      <el-radio-group v-model="tagPlacement" size="small" @change="onPlacementChange">
        <el-radio-button value="left">前</el-radio-button>
        <el-radio-button value="top">上</el-radio-button>
        <el-radio-button value="right">后</el-radio-button>
        <el-radio-button value="bottom">下</el-radio-button>
      </el-radio-group>
    </div>
    <div class="row">
      <span class="label">对齐</span>
      <el-radio-group v-model="tagAlign" size="small" @change="onAlignChange">
        <template v-if="tagPlacement === 'top' || tagPlacement === 'bottom'">
          <el-radio-button value="left">左</el-radio-button>
          <el-radio-button value="center">中</el-radio-button>
          <el-radio-button value="right">右</el-radio-button>
        </template>
        <template v-else>
          <el-radio-button value="top">上</el-radio-button>
          <el-radio-button value="center">中</el-radio-button>
          <el-radio-button value="bottom">下</el-radio-button>
        </template>
      </el-radio-group>
    </div>
    <div class="row">
      <span class="label">背景</span>
      <el-popover placement="bottom" trigger="click" :width="270">
        <template #reference>
          <span class="block" :style="{ backgroundColor: tagFillColor }"></span>
        </template>
        <Color :color="tagFillColor" @change="onColorChange" />
      </el-popover>
    </div>
    <div class="row">
      <span class="label">字色</span>
      <el-popover placement="bottom" trigger="click" :width="270">
        <template #reference>
          <span class="block" :style="{ backgroundColor: tagFontColor }"></span>
        </template>
        <Color :color="tagFontColor" @change="onFontColorChange" />
      </el-popover>
    </div>
    <div class="row">
      <span class="label">字号</span>
      <el-input-number v-model="tagFontSize" size="small" :min="10" :max="24" :step="1" style="width: 120px" @change="onFontSizeChange" />
    </div>
  </div>
</template>

<script setup>
import Color from './Color.vue'
import { store } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const show = ref(false)
const left = ref(0)
const top = ref(0)
const containerRef = ref(null)
const tagText = ref('')
const tagFillColor = ref('')
const tagFontColor = ref('#fff')
const tagFontSize = ref(12)
const tagPlacement = ref('right')
const tagAlign = ref('center')
let currentNode = null
let currentTagIndex = -1

function onTagClick(node, tag, index, el) {
  currentNode = node
  currentTagIndex = index
  tagText.value = typeof tag === 'object' ? tag.text || '' : tag || ''
  tagFillColor.value = typeof tag === 'object' ? tag.style?.fill || '' : ''
  tagFontColor.value = typeof tag === 'object' ? tag.style?.color || '#fff' : '#fff'
  tagFontSize.value = typeof tag === 'object' ? tag.style?.fontSize || 12 : 12
  tagPlacement.value = typeof tag === 'object' ? tag.placement || 'right' : 'right'
  tagAlign.value = typeof tag === 'object' ? tag.align || 'center' : 'center'
  if (el) {
    const rect = typeof el.rbox === 'function' ? el.rbox() : el.getBoundingClientRect()
    left.value = rect.x || rect.left || 0
    top.value = (rect.y || rect.top || 0) + (rect.height || 20) + 5
  }
  show.value = true
}

function hide() {
  show.value = false
  currentNode = null
  currentTagIndex = -1
}

function ensureTagObject(tags) {
  if (typeof tags[currentTagIndex] === 'string') {
    tags[currentTagIndex] = { text: tags[currentTagIndex], style: {} }
  }
  if (!tags[currentTagIndex].style) {
    tags[currentTagIndex].style = {}
  }
  return tags
}

function onTextChange() {
  if (!currentNode || currentTagIndex < 0) return
  const tags = currentNode.getData('tag') || []
  if (currentTagIndex >= tags.length) return
  if (typeof tags[currentTagIndex] === 'object') {
    tags[currentTagIndex].text = tagText.value
  } else {
    tags[currentTagIndex] = tagText.value
  }
  props.mindMap?.execCommand('SET_NODE_TAG', currentNode, [...tags])
}

function onColorChange(color) {
  tagFillColor.value = color
  if (!currentNode || currentTagIndex < 0) return
  const tags = currentNode.getData('tag') || []
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].style.fill = color
  props.mindMap?.execCommand('SET_NODE_TAG', currentNode, [...tags])
}

function onFontColorChange(color) {
  tagFontColor.value = color
  if (!currentNode || currentTagIndex < 0) return
  const tags = currentNode.getData('tag') || []
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].style.color = color
  props.mindMap?.execCommand('SET_NODE_TAG', currentNode, [...tags])
}

function onFontSizeChange(val) {
  tagFontSize.value = val
  if (!currentNode || currentTagIndex < 0) return
  const tags = currentNode.getData('tag') || []
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].style.fontSize = val
  props.mindMap?.execCommand('SET_NODE_TAG', currentNode, [...tags])
}

function onPlacementChange(val) {
  tagPlacement.value = val
  tagAlign.value = 'center'
  if (!currentNode || currentTagIndex < 0) return
  const tags = currentNode.getData('tag') || []
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].placement = val
  tags[currentTagIndex].align = 'center'
  props.mindMap?.execCommand('SET_NODE_TAG', currentNode, [...tags])
}

function onAlignChange(val) {
  tagAlign.value = val
  if (!currentNode || currentTagIndex < 0) return
  const tags = currentNode.getData('tag') || []
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].align = val
  props.mindMap?.execCommand('SET_NODE_TAG', currentNode, [...tags])
}

function deleteTag() {
  if (!currentNode || currentTagIndex < 0) return
  const tags = currentNode.getData('tag') || []
  tags.splice(currentTagIndex, 1)
  props.mindMap?.execCommand('SET_NODE_TAG', currentNode, [...tags])
  hide()
}

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) {
    oldMm.off('node_tag_click', onTagClick)
    oldMm.off('scale', hide)
    oldMm.off('translate', hide)
    oldMm.off('svg_mousedown', hide)
    oldMm.off('expand_btn_click', hide)
  }
  if (mm) {
    mm.on('node_tag_click', onTagClick)
    mm.on('scale', hide)
    mm.on('translate', hide)
    mm.on('svg_mousedown', hide)
    mm.on('expand_btn_click', hide)
  }
}, { immediate: true })

onMounted(() => {
  if (containerRef.value) {
    document.body.appendChild(containerRef.value)
  }
})

onBeforeUnmount(() => {
  props.mindMap?.off('node_tag_click', onTagClick)
  props.mindMap?.off('scale', hide)
  props.mindMap?.off('translate', hide)
  props.mindMap?.off('svg_mousedown', hide)
  props.mindMap?.off('expand_btn_click', hide)
  if (containerRef.value?.parentNode === document.body) {
    document.body.removeChild(containerRef.value)
  }
})
</script>

<style lang="less" scoped>
.nodeTagStyleContainer {
  position: fixed;
  z-index: 10000;
  background: #fff;
  box-shadow: 0 2px 16px 0 rgba(0, 0, 0, 0.12);
  border-radius: 6px;
  padding: 12px;
  min-width: 240px;

  &.isDark {
    background: #363b3f;
    color: hsla(0, 0%, 100%, 0.8);
    .label { color: hsla(0, 0%, 100%, 0.6); }
  }

  .row {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
    &:last-child { margin-bottom: 0; }
  }

  .label {
    font-size: 12px;
    margin-right: 8px;
    white-space: nowrap;
    color: #666;
    min-width: 28px;
  }

  .block {
    display: inline-block;
    width: 30px;
    height: 20px;
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    cursor: pointer;
  }
}
</style>
