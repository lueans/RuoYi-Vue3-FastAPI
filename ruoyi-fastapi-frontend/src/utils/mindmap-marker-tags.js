import iconsSvg from '../libs/simple-mind-map/src/svg/icons.js'
import {
  getMindmapManagedMarkerTagIconKey,
  getMindmapMarkerGroupType,
  getMindmapMarkerTagIconKey,
  MINDMAP_MARKER_TAG_KEY_PREFIX,
  MINDMAP_MARKER_GROUP_SPECS,
  normalizeMindmapMarkerIconKey,
  replaceMindmapMarkerInTagList,
} from './mindmap-marker-tag-core.js'

export {
  getMindmapManagedMarkerTagIconKey,
  getMindmapMarkerGroupType,
  getMindmapMarkerTagIconKey,
  MINDMAP_MARKER_TAG_KEY_PREFIX,
  normalizeMindmapMarkerIconKey,
  replaceMindmapMarkerInTagList,
}

export const MINDMAP_MARKER_GROUPS = Object.freeze(
  MINDMAP_MARKER_GROUP_SPECS.map(group => Object.freeze({
    ...group,
    options: Object.freeze(group.options.map(option => Object.freeze({
      ...option,
      markup: iconsSvg.getNodeIconListIcon(option.iconKey),
    }))),
  })),
)

const MARKER_OPTIONS = MINDMAP_MARKER_GROUPS.flatMap(group => group.options)
const MARKER_OPTION_MAP = new Map(MARKER_OPTIONS.map(option => [option.iconKey, option]))

export function getMindmapMarkerIconMarkup(value) {
  const iconKey = normalizeMindmapMarkerIconKey(value)
  return iconKey ? MARKER_OPTION_MAP.get(iconKey).markup : ''
}
