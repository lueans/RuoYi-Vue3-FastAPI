const MARKER_GROUP_DEFINITIONS = Object.freeze([
  Object.freeze({ type: 'priority', label: '优先级', count: 10 }),
  Object.freeze({ type: 'progress', label: '任务', count: 8 }),
  Object.freeze({ type: 'expression', label: '表情', count: 20 }),
  Object.freeze({ type: 'sign', label: '符号', count: 23 }),
])

export const MINDMAP_MARKER_GROUP_SPECS = Object.freeze(
  MARKER_GROUP_DEFINITIONS.map(group => Object.freeze({
    type: group.type,
    label: group.label,
    options: Object.freeze(Array.from({ length: group.count }, (_, index) => Object.freeze({
      iconKey: `${group.type}_${index + 1}`,
      label: `${group.label} ${index + 1}`,
    }))),
  })),
)

const MARKER_ICON_KEYS = new Set(
  MINDMAP_MARKER_GROUP_SPECS.flatMap(group => group.options.map(option => option.iconKey)),
)
export const MINDMAP_MARKER_TAG_KEY_PREFIX = 'builtin_marker_'

export function normalizeMindmapMarkerIconKey(value) {
  const iconKey = typeof value === 'string' ? value.trim() : ''
  return MARKER_ICON_KEYS.has(iconKey) ? iconKey : ''
}

export function getMindmapMarkerTagIconKey(tag) {
  return normalizeMindmapMarkerIconKey(tag?.style?.iconKey)
}

export function getMindmapManagedMarkerTagIconKey(tag) {
  const iconKey = getMindmapMarkerTagIconKey(tag)
  return iconKey && tag?.tagKey === `${MINDMAP_MARKER_TAG_KEY_PREFIX}${iconKey}`
    ? iconKey
    : ''
}

export function getMindmapMarkerGroupType(value) {
  return normalizeMindmapMarkerIconKey(value).split('_')[0] || ''
}

export function replaceMindmapMarkerInTagList(tags, nextTag) {
  const nextIconKey = getMindmapMarkerTagIconKey(nextTag)
  if (!nextIconKey) return [...tags, nextTag]
  const nextGroup = getMindmapMarkerGroupType(nextIconKey)
  return [
    ...tags.filter(tag => (
      getMindmapMarkerGroupType(getMindmapMarkerTagIconKey(tag)) !== nextGroup
    )),
    nextTag,
  ]
}
