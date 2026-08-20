import {
  DEFAULT_MINDMAP_LIST_PREFERENCES,
  MINDMAP_LIST_SORT_OPTIONS,
} from './mindmap-list-preferences.js'
import { MAX_MINDMAP_FILE_KEYWORD_LENGTH } from './mindmap-file.js'

export const DEFAULT_MINDMAP_LIST_PAGE_SIZE = 10
export const MAX_MINDMAP_LIST_PAGE_SIZE = 100
export const MAX_MINDMAP_LIST_RETURN_STATE_LENGTH = 512

const LIST_ROUTE_KEYS = Object.freeze([
  'scope', 'q', 'status', 'folder', 'tag', 'page', 'size', 'sort',
])

function firstQueryValue(value) {
  return Array.isArray(value) ? value[0] : value
}

function parsePositiveInteger(value, { fallback = null, max = Number.MAX_SAFE_INTEGER } = {}) {
  const normalized = String(firstQueryValue(value) ?? '').trim()
  if (!/^[1-9]\d*$/.test(normalized)) return fallback
  const parsed = Number(normalized)
  return Number.isSafeInteger(parsed) && parsed <= max ? parsed : fallback
}

function normalizeKeyword(value) {
  const normalized = String(firstQueryValue(value) ?? '').trim()
  if (!normalized) return ''
  if ([...normalized].some(char => {
    const code = char.codePointAt(0)
    return code < 32 || code === 127
  })) return ''
  return Array.from(normalized).slice(0, MAX_MINDMAP_FILE_KEYWORD_LENGTH).join('')
}

function normalizeSortKey(value, fallbackSortKey) {
  const requested = String(firstQueryValue(value) ?? '')
  if (Object.hasOwn(MINDMAP_LIST_SORT_OPTIONS, requested)) return requested
  if (Object.hasOwn(MINDMAP_LIST_SORT_OPTIONS, fallbackSortKey)) return fallbackSortKey
  return DEFAULT_MINDMAP_LIST_PREFERENCES.sortKey
}

export function parseMindmapListRouteQuery(
  query,
  fallbackSortKey = DEFAULT_MINDMAP_LIST_PREFERENCES.sortKey,
) {
  const source = query && typeof query === 'object' && !Array.isArray(query) ? query : {}
  const requestedScope = firstQueryValue(source.scope)
  const scope = ['shared', 'trash'].includes(requestedScope) ? requestedScope : 'owned'
  const requestedStatus = firstQueryValue(source.status)
  const defaultStatus = scope === 'trash' ? null : 0
  const status = requestedStatus === 'all'
    ? null
    : ['0', '1', 0, 1].includes(requestedStatus)
      ? Number(requestedStatus)
      : defaultStatus
  return {
    scope,
    keyword: normalizeKeyword(source.q),
    status: scope === 'trash' ? null : status,
    folderId: scope === 'owned' ? parsePositiveInteger(source.folder) : null,
    tagId: scope === 'owned' ? parsePositiveInteger(source.tag) : null,
    pageNum: parsePositiveInteger(source.page, { fallback: 1 }),
    pageSize: parsePositiveInteger(source.size, {
      fallback: DEFAULT_MINDMAP_LIST_PAGE_SIZE,
      max: MAX_MINDMAP_LIST_PAGE_SIZE,
    }),
    sortKey: normalizeSortKey(source.sort, fallbackSortKey),
  }
}

export function buildMindmapListRouteQuery(state) {
  const normalized = parseMindmapListRouteQuery({
    scope: state?.scope,
    q: state?.keyword,
    status: state?.status === null ? 'all' : state?.status,
    folder: state?.folderId,
    tag: state?.tagId,
    page: state?.pageNum,
    size: state?.pageSize,
    sort: state?.sortKey,
  })
  const query = { sort: normalized.sortKey }
  if (normalized.scope !== 'owned') query.scope = normalized.scope
  if (normalized.keyword) query.q = normalized.keyword
  if (normalized.scope !== 'trash') {
    if (normalized.status === null) query.status = 'all'
    else if (normalized.status === 1) query.status = '1'
  }
  if (normalized.scope === 'owned' && normalized.folderId) {
    query.folder = String(normalized.folderId)
  }
  if (normalized.scope === 'owned' && normalized.tagId) query.tag = String(normalized.tagId)
  if (normalized.pageNum > 1) query.page = String(normalized.pageNum)
  if (normalized.pageSize !== DEFAULT_MINDMAP_LIST_PAGE_SIZE) {
    query.size = String(normalized.pageSize)
  }
  return query
}

export function isSameMindmapListRouteQuery(left, right) {
  return LIST_ROUTE_KEYS.every(key => (
    String(firstQueryValue(left?.[key]) ?? '') === String(firstQueryValue(right?.[key]) ?? '')
  ))
}

export function isSameMindmapListState(left, right) {
  return (
    left?.scope === right?.scope
    && left?.keyword === right?.keyword
    && left?.status === right?.status
    && left?.folderId === right?.folderId
    && left?.tagId === right?.tagId
    && left?.pageNum === right?.pageNum
    && left?.pageSize === right?.pageSize
    && left?.sortKey === right?.sortKey
  )
}

export function encodeMindmapListReturnState(state) {
  return JSON.stringify(buildMindmapListRouteQuery(state))
}

export function decodeMindmapListReturnState(
  value,
  fallbackSortKey = DEFAULT_MINDMAP_LIST_PREFERENCES.sortKey,
) {
  if (typeof value !== 'string' || !value || value.length > MAX_MINDMAP_LIST_RETURN_STATE_LENGTH) {
    return null
  }
  try {
    const parsed = JSON.parse(value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const normalized = parseMindmapListRouteQuery(parsed, fallbackSortKey)
    const canonical = buildMindmapListRouteQuery(normalized)
    const parsedKeys = Object.keys(parsed)
    if (
      parsedKeys.length !== Object.keys(canonical).length
      || parsedKeys.some(key => !LIST_ROUTE_KEYS.includes(key) || typeof parsed[key] !== 'string')
      || !isSameMindmapListRouteQuery(parsed, canonical)
    ) return null
    return normalized
  } catch {
    return null
  }
}
