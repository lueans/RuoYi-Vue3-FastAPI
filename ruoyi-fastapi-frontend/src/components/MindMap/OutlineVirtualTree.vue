<template>
  <div ref="viewport" class="outlineVirtualTree" role="tree" aria-label="可编辑脑图大纲" @scroll.passive="measure"
    @dragover="scrollWhileDragging" @dragleave="onDragLeave" @drop="finishDrag" @dragend="finishDrag">
    <div class="outlineRows" :style="{ height: `${rows.length * ROW_HEIGHT}px` }">
      <div v-for="entry in visibleRows" :key="entry.data.uid" :ref="el => setRowRef(entry.data.uid, el)"
        class="outlineRow" :class="dropUid === entry.data.uid ? `drop-${dropType}` : ''"
        :style="{ top: `${entry.index * ROW_HEIGHT}px`, paddingLeft: `${Math.min(entry.level - 1, 20) * 18 + 4}px` }"
        role="treeitem" :aria-level="entry.level" :aria-expanded="entry.data.children.length ? !collapsed.has(entry.data.uid) : undefined"
        :aria-posinset="entry.position" :aria-setsize="entry.setSize"
        @dragover.stop="onDragOver($event, entry)" @drop.stop.prevent="dropOn(entry)">
        <button v-if="entry.data.children.length" type="button" class="treeToggle"
          :aria-label="`${collapsed.has(entry.data.uid) ? '展开' : '收起'}：${entry.data.label}`"
          :aria-expanded="!collapsed.has(entry.data.uid)" @click="toggle(entry)">{{ collapsed.has(entry.data.uid) ? '▸' : '▾' }}</button>
        <span v-else class="treeToggle" aria-hidden="true"></span>
        <button v-if="draggable && allowDrag(entry)" type="button" class="treeDrag" tabindex="-1" draggable="true"
          aria-label="拖动调整节点位置" title="拖动到节点上方、内部或下方" @dragstart="startDrag($event, entry)">⠿</button>
        <slot :node="entry" :data="entry.data" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps({
  data: { type: Array, default: () => [] },
  draggable: Boolean,
  allowDrag: { type: Function, default: () => true },
  allowDrop: { type: Function, default: () => true },
  pinnedUid: { type: String, default: '' },
})
const emit = defineEmits(['node-drop'])
const ROW_HEIGHT = 44
const viewport = ref(null)
const scrollTop = ref(0)
const height = ref(600)
const collapsed = ref(new Set())
const dropUid = ref('')
const dropType = ref('')
const rowRefs = new Map()
let draggedNode = null
let resizeObserver = null
let scrollFrame = null
let scrollSpeed = 0

const treeIndex = computed(() => {
  const byUid = new Map()
  const visible = []
  const pending = props.data.map((data, index) => ({ data, level: 1, parent: null, position: index + 1, setSize: props.data.length, hidden: false })).reverse()
  while (pending.length) {
    const node = pending.pop()
    if (byUid.has(node.data.uid)) continue
    byUid.set(node.data.uid, node)
    if (!node.hidden) { node.index = visible.length; visible.push(node) }
    const children = node.data.children || []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push({ data: children[index], level: node.level + 1, parent: node, position: index + 1, setSize: children.length,
        hidden: node.hidden || collapsed.value.has(node.data.uid) })
    }
  }
  return { byUid, visible }
})
const rows = computed(() => treeIndex.value.visible)
const visibleRows = computed(() => {
  const start = Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - 6)
  const end = Math.min(rows.value.length, Math.ceil((scrollTop.value + height.value) / ROW_HEIGHT) + 6)
  const result = rows.value.slice(start, end)
  // Scrolling must never unmount a contenteditable with an active/pending
  // lease: its unsaved DOM is also used by collaboration conflict recovery.
  const pinned = treeIndex.value.byUid.get(props.pinnedUid)
  if (pinned && !pinned.hidden && (pinned.index < start || pinned.index >= end)) result.push(pinned)
  return result.sort((a, b) => a.index - b.index)
})
function setRowRef(uid, element) { if (element) rowRefs.set(uid, element); else rowRefs.delete(uid) }
function measure() {
  scrollTop.value = viewport.value?.scrollTop || 0
  height.value = viewport.value?.clientHeight || 600
}
function toggle(entry) {
  const next = new Set(collapsed.value)
  if (next.has(entry.data.uid)) next.delete(entry.data.uid)
  else next.add(entry.data.uid)
  collapsed.value = next
}
async function reveal(uid) {
  const node = treeIndex.value.byUid.get(uid)
  if (!node) return null
  const next = new Set(collapsed.value)
  for (let parent = node.parent; parent; parent = parent.parent) next.delete(parent.data.uid)
  collapsed.value = next
  await nextTick()
  const current = treeIndex.value.byUid.get(uid)
  const top = current.index * ROW_HEIGHT
  if (viewport.value) {
    if (top < viewport.value.scrollTop) viewport.value.scrollTop = top
    else if (top + ROW_HEIGHT > viewport.value.scrollTop + height.value) viewport.value.scrollTop = top + ROW_HEIGHT - height.value
  }
  measure()
  await nextTick()
  return rowRefs.get(uid)?.querySelector('.nodeEdit') || null
}
function adjacentUid(uid, direction) {
  const current = treeIndex.value.byUid.get(uid)
  if (!current || current.hidden) return null
  const index = Math.max(0, Math.min(rows.value.length - 1, current.index + direction))
  return rows.value[index]?.data.uid || null
}
function startDrag(event, node) {
  if (!props.draggable || !props.allowDrag(node)) { event.preventDefault(); return }
  draggedNode = node
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', node.data.uid)
}
function validDrop(target, type) {
  if (!draggedNode || !props.draggable || !props.allowDrag(draggedNode) || !props.allowDrop(draggedNode, target, type)) return false
  for (let ancestor = target; ancestor; ancestor = ancestor.parent) {
    if (ancestor.data.uid === draggedNode.data.uid) return false
  }
  return true
}
function onDragOver(event, node) {
  scrollWhileDragging(event)
  const rect = event.currentTarget.getBoundingClientRect()
  const fraction = (event.clientY - rect.top) / rect.height
  const type = fraction < .25 ? 'before' : fraction > .75 ? 'after' : 'inner'
  if (!validDrop(node, type)) { dropUid.value = ''; dropType.value = ''; return }
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  dropUid.value = node.data.uid
  dropType.value = type
}
function dropOn(node) {
  if (dropUid.value === node.data.uid && validDrop(node, dropType.value)) emit('node-drop', draggedNode, node, dropType.value)
  finishDrag()
}
function scrollWhileDragging(event) {
  if (!draggedNode || !viewport.value) return
  const rect = viewport.value.getBoundingClientRect()
  scrollSpeed = event.clientY < rect.top + 40 ? -10 : event.clientY > rect.bottom - 40 ? 10 : 0
  if (!scrollSpeed || scrollFrame !== null) return
  const tick = () => {
    scrollFrame = null
    if (!draggedNode || !scrollSpeed || !viewport.value) return
    viewport.value.scrollTop += scrollSpeed
    measure()
    scrollFrame = requestAnimationFrame(tick)
  }
  scrollFrame = requestAnimationFrame(tick)
}
function onDragLeave(event) {
  if (!viewport.value?.contains(event.relatedTarget)) scrollSpeed = 0
}
function finishDrag() {
  draggedNode = null
  dropUid.value = ''
  dropType.value = ''
  scrollSpeed = 0
  if (scrollFrame !== null) cancelAnimationFrame(scrollFrame)
  scrollFrame = null
}
watch(() => props.data, () => nextTick(measure))
onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(measure)
    resizeObserver.observe(viewport.value)
  }
})
onBeforeUnmount(() => { resizeObserver?.disconnect(); finishDrag(); rowRefs.clear() })
defineExpose({ reveal, adjacentUid })
</script>

<style scoped>
.outlineVirtualTree { flex: 1; min-height: 0; overflow: auto; position: relative; color: inherit; background: inherit; }
.outlineRows { position: relative; min-width: 0; }
.outlineRow { display: flex; align-items: center; position: absolute; left: 0; right: 0; height: 44px; box-sizing: border-box; gap: 2px; padding-right: 8px; border-block: 2px solid transparent; }
.treeToggle,.treeDrag { width: 24px; flex: 0 0 24px; height: 28px; padding: 0; background: transparent; color: inherit; border: 0; border-radius: 4px; }
button.treeToggle { cursor: pointer; }
.treeDrag { cursor: grab; opacity: .65; }
.treeToggle:focus-visible { outline: 2px solid #409eff; }
.drop-before { border-top-color: #409eff; }
.drop-after { border-bottom-color: #409eff; }
.drop-inner { background: rgb(64 158 255 / 16%); outline: 1px solid #409eff; outline-offset: -1px; }
</style>
