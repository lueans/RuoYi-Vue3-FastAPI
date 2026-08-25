<template>
  <Sidebar ref="sidebarRef" title="标签" open-on-mount>
    <div class="node-icon-sidebar" :class="{ isDark }">
      <div class="selection-context" role="status" aria-live="polite">
        <span class="selection-dot" :class="{ ready: activeNodes.length > 0 }" aria-hidden="true" />
        <span>{{ selectionHint }}</span>
        <button type="button" class="all-tags-button" :disabled="isReadonly" @click="openAllTags">
          更多标签
        </button>
      </div>
      <div v-if="loading" class="marker-state" role="status">正在读取标签标记…</div>
      <div v-else-if="loadError" class="marker-state is-error" role="alert">
        <span>{{ loadError }}</span>
        <button type="button" @click="loadMarkerTags">重试</button>
      </div>
      <template v-else>
        <details
          v-for="(group, groupIndex) in iconList"
          :key="group.type"
          class="icon-group"
          :open="groupIndex < 4"
        >
          <summary class="group-title">
            <span>{{ group.name }}</span>
            <small>{{ group.list.length }}</small>
            <span class="group-chevron iconfont iconjiantouyou" aria-hidden="true" />
          </summary>
          <div class="icon-grid" role="group" :aria-label="group.name">
            <button v-for="item in group.list" :key="item.name"
              type="button"
              class="icon-item" :class="{ selected: isSelected(group.type, item.name) }"
              :disabled="iconControlsDisabled || !item.tag"
              @click="setTag(group.type, item)"
              v-html="item.icon"
              :aria-label="item.tag?.name || `${group.name}：${item.name}`"
              :aria-pressed="isSelected(group.type, item.name)"
              :title="item.tag?.name || item.label">
            </button>
          </div>
        </details>
      </template>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import bus from './useEventBus'
import { store } from './useStore'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'
import { listTags } from '@/api/mindmap/tag'
import { createLatestRequestTracker } from '@/utils/mindmap-async'
import {
  getMindmapManagedMarkerTagIconKey,
  getMindmapMarkerGroupType,
  getMindmapMarkerTagIconKey,
  MINDMAP_MARKER_GROUPS,
  replaceMindmapMarkerInTagList,
} from '@/utils/mindmap-marker-tags'

const props = defineProps({
  mindMap: { type: Object, default: null },
})

const sidebarRef = ref(null)
const { activeNodes, syncActiveNodes } = useMindMapActiveNodes({
  resolveMindMap: () => props.mindMap,
})
const currentIcons = ref([])
const markerTags = ref([])
const loading = ref(false)
const loadError = ref('')
const markerRequests = createLatestRequestTracker()
let componentActive = true

const markerTagMap = computed(() => new Map(
  markerTags.value.map(tag => [getMindmapManagedMarkerTagIconKey(tag), tag]),
))
const iconList = computed(() => MINDMAP_MARKER_GROUPS.map(group => ({
  type: group.type,
  name: group.label,
  list: group.options.map(option => ({
    ...option,
    name: option.iconKey.split('_').at(-1),
    icon: option.markup,
    tag: markerTagMap.value.get(option.iconKey) || null,
  })),
})))
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const iconControlsDisabled = computed(() => isReadonly.value || activeNodes.value.length === 0)
const selectionHint = computed(() => {
  if (isReadonly.value) return '只读模式下不能修改节点标记'
  if (activeNodes.value.length === 0) return '选择节点后应用标记'
  return `将标记应用到已选择的 ${activeNodes.value.length} 个节点`
})
function isSelected(type, name) {
  return currentIcons.value.includes(type + '_' + name)
}

function toNodeTag(tag) {
  const style = { ...(tag.style || {}) }
  return {
    tagId: tag.id,
    uuid: tag.uuid,
    tagKey: tag.tagKey,
    text: tag.name,
    style,
    placement: style.placement,
    align: style.align,
    status: tag.status,
    definitionRevision: tag.definitionRevision,
  }
}

function setTag(type, item) {
  if (iconControlsDisabled.value) return
  const nodes = activeNodes.value
  const managedTag = item.tag
  if (!managedTag) return
  const shouldSelect = !nodes.every(node => (
    (node.getData('tag') || []).some(tag => getMindmapMarkerTagIconKey(tag) === item.iconKey)
  ))
  nodes.forEach(node => {
    const tags = [...(node.getData('tag') || [])]
    const nextTags = shouldSelect
      ? replaceMindmapMarkerInTagList(tags, toNodeTag(managedTag))
      : tags.filter(tag => (
          getMindmapMarkerGroupType(getMindmapMarkerTagIconKey(tag)) !== type
        ))
    node.setTag(nextTags.map(tag => (
      tag && typeof tag === 'object' ? { ...tag, style: { ...(tag.style || {}) } } : tag
    )))
  })
  readIcons()
}

function readIcons() {
  const markerLists = activeNodes.value.map(node => (
    (node.getData('tag') || []).map(getMindmapMarkerTagIconKey).filter(Boolean)
  ))
  currentIcons.value = markerLists.length
    ? markerLists[0].filter(iconKey => markerLists.every(list => list.includes(iconKey)))
    : []
}

async function loadMarkerTags() {
  const requestId = markerRequests.begin()
  loading.value = true
  loadError.value = ''
  try {
    const response = await listTags({
      pageNum: 1,
      pageSize: 100,
      keyword: 'builtin_marker_',
      ownerScope: 'global',
      status: 0,
    })
    if (!componentActive || !markerRequests.isCurrent(requestId)) return
    markerTags.value = (response.rows || []).filter(tag => getMindmapManagedMarkerTagIconKey(tag))
    if (markerTags.value.length === 0) {
      loadError.value = '标记标签尚未初始化，请先执行标记数据迁移'
    }
  } catch (error) {
    if (!componentActive || !markerRequests.isCurrent(requestId)) return
    markerTags.value = []
    loadError.value = error?.message || '标签标记加载失败'
  } finally {
    if (componentActive && markerRequests.isCurrent(requestId)) loading.value = false
  }
}

function openAllTags() {
  if (isReadonly.value) return
  bus.emit('showNodeTag')
}

watch(activeNodes, () => {
  readIcons()
}, { flush: 'sync' })

watch(() => store.activeSidebar, (val) => {
  if (val === 'nodeTagSidebar') {
    syncActiveNodes()
    sidebarRef.value?.open()
    void loadMarkerTags()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })

function onManagedTagDefinitionChanged() {
  if (store.activeSidebar === 'nodeTagSidebar') void loadMarkerTags()
}

onMounted(() => {
  bus.on('managed_tag_definition_changed', onManagedTagDefinitionChanged)
})

onBeforeUnmount(() => {
  componentActive = false
  markerRequests.invalidate()
  bus.off('managed_tag_definition_changed', onManagedTagDefinitionChanged)
})
</script>

<style lang="less" scoped>
.node-icon-sidebar {
  min-height: 100%;
  padding: 0 12px 20px;

  &.isDark {
    .group-title,
    .section-heading strong {
      color: #f5f7fa;
    }

    .selection-context,
    .icon-group {
      border-color: #3d4046;
    }

    .selection-context {
      background: transparent;
    }

    .all-tags-button,
    .marker-state button {
      color: #8fb1ff;
    }

    .icon-item {
      border-radius: 7px;

      &:hover {
        background: #34383f;
        opacity: 1;
      }
    }
  }

  .selection-context {
    min-height: 34px;
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 6px 0 2px;
    padding: 0 4px;
    border: 0;
    border-bottom: 1px solid #eef0f3;
    border-radius: 0;
    color: #8f959e;
    background: transparent;
    font-size: 11px;
    line-height: 16px;
  }

  .all-tags-button {
    flex: 0 0 auto;
    margin-left: auto;
    padding: 3px 0;
    border: 0;
    background: transparent;
    color: #3370ff;
    font: inherit;
    cursor: pointer;

    &:disabled {
      color: #a8abb2;
      cursor: not-allowed;
    }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 2px;
      border-radius: 3px;
    }
  }

  .marker-state {
    display: flex;
    min-height: 96px;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 16px;
    color: #8f959e;
    font-size: 12px;
    text-align: center;

    &.is-error {
      flex-direction: column;
      color: #f56c6c;
    }

    button {
      padding: 2px 6px;
      border: 0;
      background: transparent;
      color: #3370ff;
      font: inherit;
      cursor: pointer;
    }
  }

  .selection-dot {
    width: 7px;
    height: 7px;
    flex: 0 0 7px;
    border-radius: 50%;
    background: #c7cbd1;

    &.ready {
      background: #34c759;
      box-shadow: 0 0 0 4px rgba(52, 199, 89, 0.12);
    }
  }

  .icon-grid {
    display: grid;
    grid-template-columns: repeat(7, 36px);
    gap: 3px;
  }

  .icon-group {
    margin: 0;
    border-bottom: 1px solid #eef0f3;

    &[open] .group-chevron {
      transform: rotate(90deg);
    }
  }

  .group-title {
    display: flex;
    min-height: 38px;
    align-items: center;
    padding: 0 2px;
    color: #1f2329;
    list-style: none;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;

    &::-webkit-details-marker { display: none; }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: -2px;
      border-radius: 7px;
    }

    small {
      margin-left: auto;
      color: #a2a7ae;
      font-size: 10px;
      font-weight: 400;
    }

    .group-chevron {
      margin-left: 8px;
      color: #8f959e;
      font-size: 11px;
      transition: transform 0.15s ease;
    }
  }

  .icon-grid {
    padding: 2px 0 10px;
  }

  .icon-item {
    box-sizing: border-box;
    width: 36px;
    height: 36px;
    padding: 5px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    margin: 0;
    cursor: pointer;
    position: relative;

    :deep(img) {
      width: 100%;
      height: 100%;
      display: block;
    }

    :deep(svg) {
      width: 100%;
      height: 100%;
      display: block;
    }

    &:hover:not(:disabled) {
      border-color: #b8caff;
      background: #f4f7ff;
      opacity: 1;
    }

    &:disabled {
      cursor: not-allowed;
      opacity: 0.46;
    }

    &:focus-visible {
      outline: 2px solid #3370ff;
      outline-offset: 1px;
    }

    &.selected {
      border-color: #3370ff;
      background: #edf3ff;

      &::after {
        content: '';
        position: absolute;
        inset: 0;
        border-radius: 5px;
        border: 1px solid #3370ff;
        box-sizing: border-box;
      }
    }
  }
}
</style>
