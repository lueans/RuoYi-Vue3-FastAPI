export function normalizeNodeIconList(iconList) {
  if (!Array.isArray(iconList)) return []
  return [...new Set(iconList.filter(item => typeof item === 'string' && item.includes('_')))]
}

function getNodeIconType(iconKey) {
  return iconKey.split('_')[0]
}

export function toggleNodeIcon(iconList, iconType, iconName) {
  const list = normalizeNodeIconList(iconList)
  const key = `${iconType}_${iconName}`
  const selectedIndex = list.indexOf(key)
  if (selectedIndex >= 0) {
    list.splice(selectedIndex, 1)
    return { list, selected: false }
  }

  const typeIndex = list.findIndex(item => getNodeIconType(item) === iconType)
  if (typeIndex >= 0) list.splice(typeIndex, 1, key)
  else list.push(key)
  return { list, selected: true }
}

export function removeNodeIconType(iconList, iconType) {
  return normalizeNodeIconList(iconList)
    .filter(item => getNodeIconType(item) !== iconType)
}

export function setNodeIconSelection(iconList, iconType, iconName, selected) {
  const list = normalizeNodeIconList(iconList)
  const typeIndex = list.findIndex(item => getNodeIconType(item) === iconType)
  if (!selected) {
    return list.filter(item => getNodeIconType(item) !== iconType)
  }

  const key = `${iconType}_${iconName}`
  if (typeIndex >= 0) list.splice(typeIndex, 1, key)
  else list.push(key)
  return list
}

export function toggleNodeIconAcrossLists(iconLists, iconType, iconName) {
  if (!Array.isArray(iconLists) || iconLists.length === 0) {
    return { lists: [], selected: false }
  }

  const key = `${iconType}_${iconName}`
  const lists = iconLists.map(normalizeNodeIconList)
  const selected = !lists.every(list => list.includes(key))
  return {
    lists: lists.map(list => setNodeIconSelection(list, iconType, iconName, selected)),
    selected,
  }
}

export function getCommonNodeIcons(iconLists) {
  if (!Array.isArray(iconLists) || iconLists.length === 0) return []
  const lists = iconLists.map(normalizeNodeIconList)
  return lists[0].filter(icon => lists.every(list => list.includes(icon)))
}
