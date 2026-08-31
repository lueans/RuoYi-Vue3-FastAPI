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
      <div v-if="loading" class="marker-state" role="status">正在读取首页标签…</div>
      <div v-else-if="loadError" class="marker-state is-error" role="alert">
        <span>{{ loadError }}</span>
        <button type="button" @click="loadHomeTags">重试</button>
      </div>
      <div v-else-if="iconList.length === 0" class="marker-state" role="status">
        暂无首页标签分组，可在标签管理中设置
      </div>
      <template v-else>
        <details
          v-for="(group, groupIndex) in iconList"
          :key="group.id"
          class="icon-group"
          :open="groupIndex < 4"
        >
          <summary class="group-title">
            <span>{{ group.name }}</span>
            <small>{{ group.selectionMode === 'single' ? '单选' : '多选' }} · {{ group.list.length }}</small>
            <span class="group-chevron iconfont iconjiantouyou" aria-hidden="true" />
          </summary>
          <div class="icon-grid" :class="{ 'tag-grid': group.kind === 'tag' }" role="group" :aria-label="group.name">
            <button v-for="item in group.list" :key="item.tag?.id || item.iconKey"
              type="button"
              class="icon-item" :class="{ selected: isSelected(item), 'tag-item': group.kind === 'tag' }"
              :style="group.kind === 'tag' ? getTagButtonStyle(item.tag) : undefined"
              :disabled="iconControlsDisabled || !item.tag"
              @click="setTag(item)"
              :aria-label="item.tag?.name || `${group.name}：${item.name}`"
              :aria-pressed="isSelected(item)"
              :title="item.tag?.name || item.label">
              <span v-if="group.kind === 'marker'" v-html="item.icon" />
              <template v-else>
                <span v-if="item.icon" class="home-tag-marker" aria-hidden="true" v-html="item.icon" />
                <span class="home-tag-name">{{ item.tag?.name }}</span>
              </template>
            </button>
          </div>
        </details>
      </template>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { ElMessage } from 'element-plus'
import bus from './useEventBus'
import { store } from './useStore'
import { useMindMapActiveNodes } from './useMindMapActiveNodes'
import { listTagCategories, listTags } from '@/api/mindmap/tag'
import { createLatestRequestTracker } from '@/utils/mindmap-async'
import {
  buildMindmapTagSelectionIndex,
  getMindmapTagSelectionMode,
  hasMindmapManagedTag,
  MINDMAP_TAG_SELECTION_MODE_SINGLE,
  removeMindmapSingleSelectionPeers,
} from '@/utils/mindmap-tag-selection'
import {
  getMindmapMarkerIconMarkup,
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
const currentTagIds = ref([])
const homeCategoryGroups = ref([])
const loading = ref(false)
const loadError = ref('')
const markerRequests = createLatestRequestTracker()
let componentActive = true

const tagSelectionIndex = computed(() => buildMindmapTagSelectionIndex(
  homeCategoryGroups.value.map(group => group.category),
  homeCategoryGroups.value.flatMap(group => group.catalogTags),
))

const iconList = computed(() => homeCategoryGroups.value.map(({ category, tags }) => {
  const markerTypes = new Set(
    tags
      .map(tag => getMindmapMarkerGroupType(getMindmapManagedMarkerTagIconKey(tag)))
      .filter(Boolean),
  )
  const markerGroup = markerTypes.size === 1 && tags.every(getMindmapManagedMarkerTagIconKey)
    ? MINDMAP_MARKER_GROUPS.find(group => group.type === [...markerTypes][0])
    : null
  if (markerGroup) {
    const tagMap = new Map(
      tags.map(tag => [getMindmapManagedMarkerTagIconKey(tag), tag]),
    )
    return {
      id: `category-${category.id}`,
      kind: 'marker',
      name: category.name,
      selectionMode: category.selectionMode === 'single' ? 'single' : 'multiple',
      list: markerGroup.options
        .filter(option => tagMap.has(option.iconKey))
        .map(option => ({
          ...option,
          name: option.iconKey.split('_').at(-1),
          icon: option.markup,
          tag: tagMap.get(option.iconKey),
        })),
    }
  }
  return {
    id: `category-${category.id}`,
    kind: 'tag',
    name: category.name,
    selectionMode: category.selectionMode === 'single' ? 'single' : 'multiple',
    list: tags.map(tag => {
      const iconKey = getMindmapManagedMarkerTagIconKey(tag)
      return {
        name: String(tag.id),
        iconKey,
        icon: iconKey ? getMindmapMarkerIconMarkup(iconKey) : '',
        tag,
      }
    }),
  }
}).filter(group => group.list.length > 0))
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const iconControlsDisabled = computed(() => isReadonly.value || activeNodes.value.length === 0)
const selectionHint = computed(() => {
  if (isReadonly.value) return '只读模式下不能修改节点标记'
  if (activeNodes.value.length === 0) return '选择节点后应用标记'
  return `将标记应用到已选择的 ${activeNodes.value.length} 个节点`
})
function isSelected(item) {
  if (item.iconKey) return currentIcons.value.includes(item.iconKey)
  return currentTagIds.value.includes(Number(item.tag?.id))
}

function getTagButtonStyle(tag) {
  const fill = tag?.style?.fill || '#f0f4ff'
  const color = tag?.style?.color || '#3155d9'
  return {
    backgroundColor: fill === 'transparent' ? 'transparent' : fill,
    color: color === 'transparent' ? 'inherit' : color,
  }
}

function toNodeTag(tag) {
  const style = { ...(tag.style || {}) }
  return {
    tagId: tag.id,
    categoryId: tag.categoryId,
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

function setTag(item) {
  if (iconControlsDisabled.value) return
  const nodes = activeNodes.value
  const managedTag = item.tag
  if (!managedTag) return
  const selectionMode = getMindmapTagSelectionMode(managedTag, tagSelectionIndex.value)
  const shouldSelect = !nodes.every(node => (
    (node.getData('tag') || []).some(tag => (
      item.iconKey
        ? getMindmapMarkerTagIconKey(tag) === item.iconKey
      : Number(tag?.tagId) === Number(managedTag.id)
    ))
  ))
  const nodeTag = toNodeTag(managedTag)
  const buildSelectedTags = tags => {
    const categoryAdjustedTags = removeMindmapSingleSelectionPeers(
      tags,
      managedTag,
      tagSelectionIndex.value,
    )
    if (
      hasMindmapManagedTag(categoryAdjustedTags, managedTag)
      || (item.iconKey && categoryAdjustedTags.some(tag => (
        getMindmapMarkerTagIconKey(tag) === item.iconKey
      )))
    ) {
      return categoryAdjustedTags
    }
    return item.iconKey && selectionMode === MINDMAP_TAG_SELECTION_MODE_SINGLE
      ? replaceMindmapMarkerInTagList(categoryAdjustedTags, nodeTag)
      : [...categoryAdjustedTags, nodeTag]
  }
  if (shouldSelect && nodes.some(node => buildSelectedTags(node.getData('tag') || []).length > 20)) {
    ElMessage.warning('单个节点最多设置 20 个标签')
    return
  }
  nodes.forEach(node => {
    const tags = [...(node.getData('tag') || [])]
    const nextTags = shouldSelect
      ? buildSelectedTags(tags)
      : tags.filter(tag => (
          Number(tag?.tagId) !== Number(managedTag.id)
          && (!item.iconKey || getMindmapMarkerTagIconKey(tag) !== item.iconKey)
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
  const tagIdLists = activeNodes.value.map(node => (
    (node.getData('tag') || [])
      .map(tag => Number(tag?.tagId))
      .filter(Number.isSafeInteger)
  ))
  currentTagIds.value = tagIdLists.length
    ? tagIdLists[0].filter(tagId => tagIdLists.every(list => list.includes(tagId)))
    : []
}

function isHomeTagRequestCurrent(requestId) {
  return componentActive && markerRequests.isCurrent(requestId)
}

async function loadTagCatalog(requestId) {
  const rows = []
  let pageNum = 1
  let total = 0
  do {
    const response = await listTags({
      pageNum,
      pageSize: 100,
    })
    if (!isHomeTagRequestCurrent(requestId)) return null
    const pageRows = response.rows || []
    rows.push(...pageRows)
    total = Number(response.total) || rows.length
    pageNum += 1
    if (pageRows.length === 0) break
  } while (rows.length < total)
  return rows
}

async function loadHomeTags() {
  const requestId = markerRequests.begin()
  loading.value = true
  loadError.value = ''
  try {
    const categoryResponse = await listTagCategories()
    const homeCategories = (categoryResponse.data || []).filter(category => (
      category?.id && category.showOnHome
    ))
    if (!isHomeTagRequestCurrent(requestId)) return
    const tagRows = await loadTagCatalog(requestId)
    if (!tagRows || !isHomeTagRequestCurrent(requestId)) return
    const tagsByCategoryId = new Map()
    tagRows.forEach(tag => {
      const categoryId = String(tag?.categoryId || '')
      if (!categoryId) return
      const categoryTags = tagsByCategoryId.get(categoryId) || []
      categoryTags.push(tag)
      tagsByCategoryId.set(categoryId, categoryTags)
    })
    homeCategoryGroups.value = homeCategories.map(category => ({
      category,
      catalogTags: tagsByCategoryId.get(String(category.id)) || [],
      tags: (tagsByCategoryId.get(String(category.id)) || []).filter(tag => tag.status === 0),
    }))
  } catch (error) {
    if (!componentActive || !markerRequests.isCurrent(requestId)) return
    homeCategoryGroups.value = []
    loadError.value = error?.message || '首页标签加载失败'
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
    void loadHomeTags()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })

function onManagedTagDefinitionChanged() {
  if (store.activeSidebar === 'nodeTagSidebar') void loadHomeTags()
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

    &.tag-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
    }
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

    &.tag-item {
      display: flex;
      width: 100%;
      height: 34px;
      min-width: 0;
      align-items: center;
      justify-content: flex-start;
      gap: 5px;
      padding: 5px 8px;
      border-color: rgb(0 0 0 / 8%);
      font-size: 11px;
      line-height: 18px;

      &.selected {
        border-color: #3370ff;
        box-shadow: 0 0 0 1px #3370ff inset;
      }
    }
  }

  .home-tag-marker {
    display: inline-flex;
    width: 18px;
    height: 18px;
    flex: 0 0 18px;

    :deep(svg),
    :deep(img) {
      width: 18px;
      height: 18px;
    }
  }

  .home-tag-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
</style>
