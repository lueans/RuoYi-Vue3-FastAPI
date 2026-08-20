export const MINDMAP_LIST_PREFERENCE_KEY = 'mindmap:file-list-preferences:v1'

export const MINDMAP_LIST_VIEW_MODES = Object.freeze(['grid', 'table'])

export const MINDMAP_LIST_SORT_OPTIONS = Object.freeze({
  'updated-desc': Object.freeze({ sortField: 'update_time', sortOrder: 'desc' }),
  'updated-asc': Object.freeze({ sortField: 'update_time', sortOrder: 'asc' }),
  'created-desc': Object.freeze({ sortField: 'create_time', sortOrder: 'desc' }),
  'name-asc': Object.freeze({ sortField: 'name', sortOrder: 'asc' }),
  'name-desc': Object.freeze({ sortField: 'name', sortOrder: 'desc' }),
})

export const DEFAULT_MINDMAP_LIST_PREFERENCES = Object.freeze({
  viewMode: 'grid',
  sortKey: 'updated-desc',
})

export function normalizeMindmapListPreferences(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { ...DEFAULT_MINDMAP_LIST_PREFERENCES }
  }
  return {
    viewMode: MINDMAP_LIST_VIEW_MODES.includes(value.viewMode)
      ? value.viewMode
      : DEFAULT_MINDMAP_LIST_PREFERENCES.viewMode,
    sortKey: Object.hasOwn(MINDMAP_LIST_SORT_OPTIONS, value.sortKey)
      ? value.sortKey
      : DEFAULT_MINDMAP_LIST_PREFERENCES.sortKey,
  }
}

function resolveStorage(storage) {
  if (storage !== undefined) return storage
  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

export function readMindmapListPreferences(storage) {
  const target = resolveStorage(storage)
  if (!target?.getItem) return { ...DEFAULT_MINDMAP_LIST_PREFERENCES }
  try {
    const raw = target.getItem(MINDMAP_LIST_PREFERENCE_KEY)
    if (!raw) return { ...DEFAULT_MINDMAP_LIST_PREFERENCES }
    const parsed = JSON.parse(raw)
    if (parsed?.schemaVersion !== 1) return { ...DEFAULT_MINDMAP_LIST_PREFERENCES }
    return normalizeMindmapListPreferences(parsed.values)
  } catch {
    return { ...DEFAULT_MINDMAP_LIST_PREFERENCES }
  }
}

export function writeMindmapListPreferences(preferences, storage) {
  const target = resolveStorage(storage)
  if (!target?.setItem) return false
  const values = normalizeMindmapListPreferences(preferences)
  try {
    target.setItem(MINDMAP_LIST_PREFERENCE_KEY, JSON.stringify({
      schemaVersion: 1,
      values,
    }))
    return true
  } catch {
    return false
  }
}

export function resolveMindmapListSort(sortKey) {
  return MINDMAP_LIST_SORT_OPTIONS[sortKey]
    || MINDMAP_LIST_SORT_OPTIONS[DEFAULT_MINDMAP_LIST_PREFERENCES.sortKey]
}
