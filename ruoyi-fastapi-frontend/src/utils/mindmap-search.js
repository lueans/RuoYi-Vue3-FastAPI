export function buildMindmapTagFilterOptions(tags) {
  const unique = []
  const seenIds = new Set()
  for (const tag of Array.isArray(tags) ? tags : []) {
    const id = Number(tag?.id)
    if (!Number.isSafeInteger(id) || id <= 0 || seenIds.has(id)) continue
    seenIds.add(id)
    const tagKey = String(tag?.tagKey || '').trim()
    const name = String(tag?.name || tagKey || `标签 #${id}`).trim()
    unique.push({ ...tag, id, name, tagKey })
  }

  const nameCounts = new Map()
  for (const tag of unique) {
    nameCounts.set(tag.name, (nameCounts.get(tag.name) || 0) + 1)
  }

  return unique.map(tag => {
    if (nameCounts.get(tag.name) === 1) return { ...tag, optionLabel: tag.name }
    const scope = Number(tag.ownerId) === 0 ? '全局' : '我的'
    return {
      ...tag,
      optionLabel: `${tag.name} · ${scope} · ${tag.tagKey || `#${tag.id}`}`,
    }
  })
}

export function buildMindmapSearchHighlightSegments(value, keyword, options = {}) {
  const source = String(value ?? '')
  const needle = String(keyword ?? '').trim()
  if (!source) return []
  if (!needle) return [{ text: source, match: false }]

  const escapedNeedle = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const expression = new RegExp(
    escapedNeedle,
    options.caseSensitive === true ? 'g' : 'gi',
  )
  const segments = []
  let cursor = 0
  let result
  while ((result = expression.exec(source)) !== null) {
    if (result.index > cursor) {
      segments.push({ text: source.slice(cursor, result.index), match: false })
    }
    segments.push({ text: result[0], match: true })
    cursor = result.index + result[0].length
  }
  if (cursor < source.length) {
    segments.push({ text: source.slice(cursor), match: false })
  }
  return segments.length > 0 ? segments : [{ text: source, match: false }]
}

export function matchesMindmapFilterText(value, operator, target) {
  const source = String(value ?? '')
  const needle = String(target ?? '')
  if (operator === 'equals') return source === needle
  if (operator === 'notContains') return !source.includes(needle)
  if (operator === 'notEquals') return source !== needle
  return source.includes(needle)
}

export function isMindmapCaseTitleData(data) {
  const tags = Array.isArray(data?.tag) ? data.tag : []
  return tags.some(tag => {
    const text = typeof tag === 'object' && tag !== null
      ? tag.text ?? tag.name ?? ''
      : tag
    return String(text ?? '').trim() === '用例标题'
  })
}

export function collectMindmapCaseReviewNodes(root, rows, options = {}) {
  if (!root || typeof root !== 'object') return []
  const activeRows = (Array.isArray(rows) ? rows : [])
    .filter(row => row && String(row.value ?? '').trim())
  if (activeRows.length === 0) return []

  const getChildren = typeof options.getChildren === 'function'
    ? options.getChildren
    : node => node?.children
  const getData = typeof options.getData === 'function'
    ? options.getData
    : node => node?.data || {}
  const getText = typeof options.getText === 'function'
    ? options.getText
    : node => String(node?.text ?? getData(node)?.text ?? '')
  const walk = (start, visit) => {
    const visited = new WeakSet()
    const stack = [start]
    while (stack.length > 0) {
      const node = stack.pop()
      if (!node || typeof node !== 'object' || visited.has(node)) continue
      visited.add(node)
      visit(node)
      const rawChildren = getChildren(node)
      const children = Array.isArray(rawChildren) ? rawChildren : []
      for (let index = children.length - 1; index >= 0; index -= 1) {
        stack.push(children[index])
      }
    }
  }

  const titleRows = activeRows.filter(row => row.field === 'title')
  const anyNodeRows = activeRows.filter(row => row.field !== 'title')
  const candidates = []
  walk(root, node => {
    if (!isMindmapCaseTitleData(getData(node))) return
    const title = getText(node)
    if (titleRows.every(row => matchesMindmapFilterText(title, row.operator, row.value))) {
      candidates.push(node)
    }
  })
  if (anyNodeRows.length === 0) return candidates

  return candidates.filter(caseTitleNode => {
    let matched = false
    walk(caseTitleNode, node => {
      if (matched) return
      const text = getText(node)
      matched = anyNodeRows.every(row => (
        matchesMindmapFilterText(text, row.operator, row.value)
      ))
    })
    return matched
  })
}

export function resolveMindmapSearchNavigationIndex(currentIndex, resultCount, key) {
  const count = Number(resultCount)
  if (!Number.isSafeInteger(count) || count <= 0) return -1

  const normalizedCurrent = Number.isSafeInteger(currentIndex)
    && currentIndex >= 0
    && currentIndex < count
    ? currentIndex
    : -1

  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  if (key === 'ArrowDown') {
    return normalizedCurrent < 0 ? 0 : (normalizedCurrent + 1) % count
  }
  if (key === 'ArrowUp') {
    return normalizedCurrent < 0 ? count - 1 : (normalizedCurrent - 1 + count) % count
  }
  return normalizedCurrent
}

export function resolveMindmapCaseReviewIndex(currentIndex, caseCount, action) {
  const count = Number(caseCount)
  if (!Number.isSafeInteger(count) || count <= 0) return -1

  const normalizedCurrent = Number.isSafeInteger(currentIndex)
    && currentIndex >= 0
    && currentIndex < count
    ? currentIndex
    : -1

  if (action === 'restart') return 0
  if (action === 'next') {
    if (normalizedCurrent < 0) return 0
    return Math.min(normalizedCurrent + 1, count - 1)
  }
  return normalizedCurrent
}

export function resolveMindmapSearchResultListHeight(viewportHeight, panelBottom) {
  const viewport = Number(viewportHeight)
  const bottom = Number(panelBottom)
  const safeViewport = Number.isFinite(viewport) ? Math.max(0, viewport) : 0
  const safeBottom = Number.isFinite(bottom) ? Math.max(0, bottom) : 0
  const availableHeight = Math.max(0, safeViewport - safeBottom - 12)
  return Math.max(96, Math.min(availableHeight, 480))
}
