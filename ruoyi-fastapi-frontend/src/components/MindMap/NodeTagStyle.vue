<template>
  <div
    class="nodeTagStyleContainer"
    :class="{ isDark: isDark }"
    v-show="show"
    ref="containerRef"
    :style="{ left: left + 'px', top: top + 'px' }"
    role="dialog"
    aria-label="编辑节点标签"
    aria-modal="false"
    tabindex="-1"
    @click.stop
    @mousedown.stop
    @keydown.esc.stop.prevent="hide"
  >
    <el-alert
      v-if="isManagedTag && managedPermissionLoaded && !canManageDefinition"
      title="你没有该标签的定义编辑权限，可调整当前位置或从节点移除"
      type="info" :closable="false" show-icon class="permissionHint"
    />
    <div class="row">
      <el-input ref="tagTextInputRef" v-model="tagText" aria-label="标签名称" size="small" style="width: 140px" :disabled="isReadonly || (isManagedTag && !canManageDefinition)" @change="onTextChange" @keydown.stop />
      <el-button size="small" type="danger" text :disabled="isReadonly" @click="deleteTag">删除</el-button>
    </div>
    <div class="row">
      <span class="label">位置</span>
      <el-radio-group v-model="tagPlacement" aria-label="标签位置" size="small" :disabled="isReadonly" @change="onPlacementChange">
        <el-radio-button value="left">前</el-radio-button>
        <el-radio-button value="top">上</el-radio-button>
        <el-radio-button value="right">后</el-radio-button>
        <el-radio-button value="bottom">下</el-radio-button>
      </el-radio-group>
    </div>
    <div class="row">
      <span class="label">对齐</span>
      <el-radio-group v-model="tagAlign" aria-label="标签对齐" size="small" :disabled="isReadonly" @change="onAlignChange">
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
      <el-popover placement="bottom" trigger="click" :disabled="isReadonly || (isManagedTag && !canManageDefinition)" :width="270">
        <template #reference>
          <ColorTrigger
            :color="tagFillColor"
            label="选择标签背景颜色"
            :disabled="isReadonly || (isManagedTag && !canManageDefinition)"
            :height="24"
          />
        </template>
        <Color :color="tagFillColor" @change="onColorChange" />
      </el-popover>
    </div>
    <div class="row">
      <span class="label">字色</span>
      <el-popover placement="bottom" trigger="click" :disabled="isReadonly || (isManagedTag && !canManageDefinition)" :width="270">
        <template #reference>
          <ColorTrigger
            :color="tagFontColor"
            label="选择标签文字颜色"
            :disabled="isReadonly || (isManagedTag && !canManageDefinition)"
            :height="24"
          />
        </template>
        <Color :color="tagFontColor" @change="onFontColorChange" />
      </el-popover>
    </div>
    <div class="row">
      <span class="label">字号</span>
      <el-input-number v-model="tagFontSize" aria-label="标签字号" size="small" :disabled="isReadonly || (isManagedTag && !canManageDefinition)" :min="10" :max="24" :step="1" style="width: 120px" @change="onFontSizeChange" />
    </div>
  </div>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import Color from './Color.vue'
import ColorTrigger from './ColorTrigger.vue'
import { store } from './useStore'
import bus from './useEventBus'
import { getTag, getTagImpact, updateTag } from '@/api/mindmap/tag'
import useUserStore from '@/store/modules/user'
import { createLatestSerialTaskQueue } from '@/utils/latest-serial-task-queue'
import {
  validateMindmapTagColor,
  validateMindmapTagDisplayName,
  validateMindmapTagStyle,
} from '@/utils/mindmap-tag-governance'

const props = defineProps({
  mindMap: { type: Object, default: null }
})
const userStore = useUserStore()

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const show = ref(false)
const left = ref(0)
const top = ref(0)
const containerRef = ref(null)
const tagTextInputRef = ref(null)
const tagText = ref('')
const tagFillColor = ref('')
const tagFontColor = ref('#fff')
const tagFontSize = ref(12)
const tagPlacement = ref('right')
const tagAlign = ref('center')
let currentNode = null
let currentMindMap = null
let currentTagIndex = -1
let currentManagedTag = null
let managedUpdateSequence = 0
let confirmedManagedTagId = null
let focusReturnTarget = null
const isManagedTag = ref(false)
const managedPermissionLoaded = ref(false)
const canManageDefinition = ref(true)

function focusEditor() {
  nextTick(() => {
    const input = tagTextInputRef.value?.input
    if (input && !input.disabled) input.focus()
    else containerRef.value?.focus()
  })
}

const managedDefinitionSaveQueue = createLatestSerialTaskQueue({
  delayMs: 250,
  execute: persistManagedDefinition,
})

function canManageOwner(ownerId) {
  return Number(ownerId) === Number(userStore.id)
    || (Number(ownerId) === 0 && Number(userStore.id) === 1)
}

async function onTagClick(node, tag, index, el) {
  const activeMindMap = props.mindMap
  if (
    isReadonly.value
    || !activeMindMap
    || !node
    || (node.mindMap && node.mindMap !== activeMindMap)
  ) return
  managedDefinitionSaveQueue.cancel()
  const sequence = ++managedUpdateSequence
  const activeElement = document.activeElement
  if (activeElement instanceof HTMLElement
    && activeElement !== document.body
    && !containerRef.value?.contains(activeElement)) {
    focusReturnTarget = activeElement
  }
  currentNode = node
  currentMindMap = activeMindMap
  currentTagIndex = index
  currentManagedTag = tag && typeof tag === 'object' && tag.tagId
    ? { ...tag, id: tag.tagId, name: tag.text }
    : null
  isManagedTag.value = Boolean(currentManagedTag)
  managedPermissionLoaded.value = !currentManagedTag
  canManageDefinition.value = !currentManagedTag
  confirmedManagedTagId = null
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
  focusEditor()
  if (currentManagedTag?.tagId) {
    try {
      const response = await getTag(currentManagedTag.tagId)
      if (
        sequence === managedUpdateSequence
        && hasCurrentTagTarget()
        && currentNode === node
        && !isReadonly.value
        && response?.data
      ) {
        currentManagedTag = { ...response.data, tagId: response.data.id }
        canManageDefinition.value = canManageOwner(response.data.ownerId)
        managedPermissionLoaded.value = true
        if (canManageDefinition.value) focusEditor()
      }
    } catch {
      // 面板仍可展示服务端随文档返回的定义；真正更新时接口会再次校验权限。
      if (sequence === managedUpdateSequence && hasCurrentTagTarget() && currentNode === node) {
        managedPermissionLoaded.value = true
      }
    }
  }
}

function hide() {
  managedDefinitionSaveQueue.cancel()
  show.value = false
  currentNode = null
  currentMindMap = null
  currentTagIndex = -1
  currentManagedTag = null
  isManagedTag.value = false
  managedPermissionLoaded.value = false
  canManageDefinition.value = true
  confirmedManagedTagId = null
  managedUpdateSequence += 1
  const returnTarget = focusReturnTarget
  focusReturnTarget = null
  nextTick(() => returnTarget?.isConnected && returnTarget.focus?.())
}

function hideWithoutFocusRestore() {
  focusReturnTarget = null
  hide()
}

function hasCurrentTagTarget() {
  return show.value
    && Boolean(currentMindMap)
    && currentMindMap === props.mindMap
    && Boolean(currentNode)
    && (!currentNode.mindMap || currentNode.mindMap === currentMindMap)
    && currentTagIndex >= 0
}

function onManagedTagDefinitionChanged(data) {
  if (!currentManagedTag?.tagId || Number(currentManagedTag.tagId) !== Number(data?.tagId)) return
  const definition = data.definition || {}
  currentManagedTag = {
    ...currentManagedTag,
    ...definition,
    definitionRevision: data.definitionRevision,
    style: { ...(definition.style || {}) },
  }
  tagText.value = definition.text ?? tagText.value
  tagFillColor.value = definition.style?.fill ?? tagFillColor.value
  tagFontColor.value = definition.style?.color ?? tagFontColor.value
  tagFontSize.value = definition.style?.fontSize ?? tagFontSize.value
}

async function persistManagedDefinition(pendingModel, { isCurrent }) {
  try {
    if (isReadonly.value || !hasCurrentTagTarget() || !isCurrent() || Number(currentManagedTag?.tagId) !== Number(pendingModel.id)) return
    if (confirmedManagedTagId !== pendingModel.id) {
      const impactResponse = await getTagImpact(pendingModel.id)
      if (isReadonly.value || !hasCurrentTagTarget() || !isCurrent()) return
      const impact = impactResponse?.data || {}
      await ElMessageBox.confirm(
        `这是统一标签。保存后会影响 ${impact.fileCount || 0} 个脑图、${impact.nodeCount || 0} 个节点，是否继续？`,
        '确认全局修改',
        { type: 'warning', confirmButtonText: '全局更新', cancelButtonText: '取消' }
      )
      if (isReadonly.value || !hasCurrentTagTarget() || !isCurrent()) return
      confirmedManagedTagId = pendingModel.id
    }
    if (isReadonly.value || !hasCurrentTagTarget() || !isCurrent()) return
    await updateTag(pendingModel)
  } catch (error) {
    if (isCurrent() && error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.message || '标签定义更新失败')
    }
  }
}

function scheduleManagedDefinitionUpdate(patch) {
  if (isReadonly.value || !hasCurrentTagTarget()) return true
  if (!currentManagedTag?.tagId) return false
  if (!canManageDefinition.value) return true
  const normalizedPatch = { ...patch }
  if (Object.prototype.hasOwnProperty.call(normalizedPatch, 'name')) {
    const name = validateMindmapTagDisplayName(normalizedPatch.name)
    if (!name.valid) {
      ElMessage.warning(name.message)
      return true
    }
    normalizedPatch.name = name.value
    tagText.value = name.value
  }
  if (normalizedPatch.style) {
    const currentStyle = currentManagedTag.style || {}
    const style = validateMindmapTagStyle({
      fill: currentStyle.fill,
      color: currentStyle.color,
      fontSize: currentStyle.fontSize,
      radius: currentStyle.radius,
      paddingX: currentStyle.paddingX,
      ...normalizedPatch.style,
    })
    if (!style.valid) {
      ElMessage.warning(style.message)
      return true
    }
    normalizedPatch.style = style.value || {}
  }
  // 使点击标签时尚未完成的详情请求失效，避免旧定义覆盖用户刚输入的值。
  managedUpdateSequence += 1
  currentManagedTag = {
    ...currentManagedTag,
    ...normalizedPatch,
    style: normalizedPatch.style
      ? normalizedPatch.style
      : currentManagedTag.style
  }
  const pendingModel = { ...currentManagedTag, id: currentManagedTag.tagId }
  delete pendingModel.tagId
  delete pendingModel.text
  managedDefinitionSaveQueue.schedule(pendingModel)
  return true
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

function getEditableTagList() {
  const tags = currentNode?.getData?.('tag')
  if (!Array.isArray(tags)) return []
  return tags.map(tag => {
    if (!tag || typeof tag !== 'object') return tag
    return {
      ...tag,
      style: { ...(tag.style || {}) },
    }
  })
}

function onTextChange() {
  if (isReadonly.value || !hasCurrentTagTarget()) return
  if (scheduleManagedDefinitionUpdate({ name: tagText.value })) return
  const tags = getEditableTagList()
  if (currentTagIndex >= tags.length) return
  if (typeof tags[currentTagIndex] === 'object') {
    tags[currentTagIndex].text = tagText.value
  } else {
    tags[currentTagIndex] = tagText.value
  }
  currentMindMap.execCommand('SET_NODE_TAG', currentNode, tags)
}

function onColorChange(color) {
  if (isReadonly.value || !hasCurrentTagTarget()) return
  const normalized = validateMindmapTagColor(color, { label: '标签背景色' })
  if (!normalized.valid) return ElMessage.warning(normalized.message)
  tagFillColor.value = normalized.value || ''
  if (scheduleManagedDefinitionUpdate({ style: { fill: normalized.value } })) return
  const tags = getEditableTagList()
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].style.fill = normalized.value
  currentMindMap.execCommand('SET_NODE_TAG', currentNode, tags)
}

function onFontColorChange(color) {
  if (isReadonly.value || !hasCurrentTagTarget()) return
  const normalized = validateMindmapTagColor(color, { label: '标签文字色' })
  if (!normalized.valid) return ElMessage.warning(normalized.message)
  tagFontColor.value = normalized.value || ''
  if (scheduleManagedDefinitionUpdate({ style: { color: normalized.value } })) return
  const tags = getEditableTagList()
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].style.color = normalized.value
  currentMindMap.execCommand('SET_NODE_TAG', currentNode, tags)
}

function onFontSizeChange(val) {
  if (isReadonly.value || !hasCurrentTagTarget()) return
  const normalized = validateMindmapTagStyle({ fontSize: val })
  if (!normalized.valid) return ElMessage.warning(normalized.message)
  tagFontSize.value = normalized.value.fontSize
  if (scheduleManagedDefinitionUpdate({ style: { fontSize: normalized.value.fontSize } })) return
  const tags = getEditableTagList()
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].style.fontSize = normalized.value.fontSize
  currentMindMap.execCommand('SET_NODE_TAG', currentNode, tags)
}

function onPlacementChange(val) {
  if (isReadonly.value || !hasCurrentTagTarget()) return
  tagPlacement.value = val
  tagAlign.value = 'center'
  const tags = getEditableTagList()
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].placement = val
  tags[currentTagIndex].align = 'center'
  currentMindMap.execCommand('SET_NODE_TAG', currentNode, tags)
}

function onAlignChange(val) {
  if (isReadonly.value || !hasCurrentTagTarget()) return
  tagAlign.value = val
  const tags = getEditableTagList()
  if (currentTagIndex >= tags.length) return
  ensureTagObject(tags)
  tags[currentTagIndex].align = val
  currentMindMap.execCommand('SET_NODE_TAG', currentNode, tags)
}

function deleteTag() {
  if (isReadonly.value || !hasCurrentTagTarget()) return
  const tags = getEditableTagList()
  tags.splice(currentTagIndex, 1)
  currentMindMap.execCommand('SET_NODE_TAG', currentNode, tags)
  hide()
}

watch(() => props.mindMap, (mm, oldMm) => {
  oldMm?.off?.('node_tag_click', onTagClick)
  oldMm?.off?.('scale', hide)
  oldMm?.off?.('translate', hide)
  oldMm?.off?.('svg_mousedown', hide)
  oldMm?.off?.('expand_btn_click', hide)
  if (mm !== oldMm) hideWithoutFocusRestore()
  mm?.on?.('node_tag_click', onTagClick)
  mm?.on?.('scale', hide)
  mm?.on?.('translate', hide)
  mm?.on?.('svg_mousedown', hide)
  mm?.on?.('expand_btn_click', hide)
}, { immediate: true })

watch(isReadonly, (readonly) => {
  if (readonly && show.value) hide()
})

onMounted(() => {
  bus.on('managed_tag_definition_changed', onManagedTagDefinitionChanged)
  if (containerRef.value) {
    document.body.appendChild(containerRef.value)
  }
})

onBeforeUnmount(() => {
  hideWithoutFocusRestore()
  bus.off('managed_tag_definition_changed', onManagedTagDefinitionChanged)
  props.mindMap?.off?.('node_tag_click', onTagClick)
  props.mindMap?.off?.('scale', hide)
  props.mindMap?.off?.('translate', hide)
  props.mindMap?.off?.('svg_mousedown', hide)
  props.mindMap?.off?.('expand_btn_click', hide)
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

  .permissionHint {
    margin-bottom: 10px;
    max-width: 320px;
  }

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

}
</style>
