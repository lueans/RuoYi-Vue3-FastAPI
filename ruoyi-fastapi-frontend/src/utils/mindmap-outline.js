export const MINDMAP_OUTLINE_ITEM_HEIGHT = 40
export const MINDMAP_OUTLINE_OVERSCAN = 6

function normalizeCollapsedKeys(collapsedKeys) {
  return collapsedKeys instanceof Set ? collapsedKeys : new Set(collapsedKeys || [])
}

export function flattenMindmapOutline(root, collapsedKeys = new Set()) {
  if (!root || typeof root !== 'object') return []

  const collapsed = normalizeCollapsedKeys(collapsedKeys)
  const pending = [{
    node: root,
    level: 0,
    parentKey: null,
    positionInSet: 1,
    setSize: 1,
  }]
  const visited = new WeakSet()
  const usedKeys = new Map()
  const result = []
  let fallbackKeyIndex = 0

  while (pending.length > 0) {
    const frame = pending.pop()
    const node = frame.node
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)

    const uid = String(node.data?.uid ?? '').trim()
    const keyBase = uid ? `uid:${uid}` : `fallback:${fallbackKeyIndex++}`
    const keyOccurrence = usedKeys.get(keyBase) || 0
    usedKeys.set(keyBase, keyOccurrence + 1)
    const key = keyOccurrence === 0 ? keyBase : `${keyBase}#${keyOccurrence}`
    const children = Array.isArray(node.children)
      ? node.children.filter(child => child && typeof child === 'object')
      : []
    const expanded = children.length > 0 && !collapsed.has(key)

    result.push({
      key,
      uid,
      text: String(node.data?.text ?? ''),
      level: frame.level,
      parentKey: frame.parentKey,
      positionInSet: frame.positionInSet,
      setSize: frame.setSize,
      hasChildren: children.length > 0,
      expanded,
    })

    if (!expanded) continue
    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push({
        node: children[index],
        level: frame.level + 1,
        parentKey: key,
        positionInSet: index + 1,
        setSize: children.length,
      })
    }
  }

  return result
}

export function resolveMindmapOutlineWindow(
  items,
  scrollTop,
  viewportHeight,
  itemHeight = MINDMAP_OUTLINE_ITEM_HEIGHT,
  overscan = MINDMAP_OUTLINE_OVERSCAN,
) {
  const list = Array.isArray(items) ? items : []
  const safeItemHeight = Math.max(1, Number(itemHeight) || MINDMAP_OUTLINE_ITEM_HEIGHT)
  const safeScrollTop = Math.max(0, Number(scrollTop) || 0)
  const safeViewportHeight = Math.max(0, Number(viewportHeight) || 0)
  const safeOverscan = Math.max(0, Math.trunc(Number(overscan) || 0))
  const start = Math.max(0, Math.floor(safeScrollTop / safeItemHeight) - safeOverscan)
  const visibleCount = Math.max(1, Math.ceil(safeViewportHeight / safeItemHeight))
  const end = Math.min(list.length, start + visibleCount + safeOverscan * 2)

  return {
    start,
    end,
    totalHeight: list.length * safeItemHeight,
    items: list.slice(start, end).map((item, offset) => ({
      item,
      index: start + offset,
      top: (start + offset) * safeItemHeight,
    })),
  }
}

export function resolveMindmapOutlineNavigation(items, currentKey, key) {
  const list = Array.isArray(items) ? items : []
  if (list.length === 0) return null
  const currentIndex = Math.max(0, list.findIndex(item => item.key === currentKey))
  const current = list[currentIndex]

  switch (key) {
    case 'ArrowUp':
      return { type: 'focus', index: Math.max(0, currentIndex - 1) }
    case 'ArrowDown':
      return { type: 'focus', index: Math.min(list.length - 1, currentIndex + 1) }
    case 'Home':
      return { type: 'focus', index: 0 }
    case 'End':
      return { type: 'focus', index: list.length - 1 }
    case 'ArrowLeft': {
      if (current.hasChildren && current.expanded) return { type: 'collapse', index: currentIndex }
      const parentIndex = current.parentKey
        ? list.findIndex(item => item.key === current.parentKey)
        : -1
      return parentIndex >= 0 ? { type: 'focus', index: parentIndex } : null
    }
    case 'ArrowRight':
      if (current.hasChildren && !current.expanded) return { type: 'expand', index: currentIndex }
      if (current.hasChildren && current.expanded && list[currentIndex + 1]?.parentKey === current.key) {
        return { type: 'focus', index: currentIndex + 1 }
      }
      return null
    default:
      return null
  }
}
