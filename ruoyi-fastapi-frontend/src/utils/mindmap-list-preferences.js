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
  viewMode: 'table',
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
  return readMindmapListPreferenceState(storage).preferences
}

export function readMindmapListPreferenceState(storage) {
  const target = resolveStorage(storage)
  const fallback = {
    preferences: { ...DEFAULT_MINDMAP_LIST_PREFERENCES },
    hasExplicitViewPreference: false,
  }
  if (!target?.getItem) return fallback
  try {
    const raw = target.getItem(MINDMAP_LIST_PREFERENCE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    if (![1, 2].includes(parsed?.schemaVersion)) return fallback
    return {
      preferences: normalizeMindmapListPreferences(parsed.values),
      // Version 1 predates responsive defaults, so its stored mode came from
      // the user's workspace and must continue to win on every viewport.
      hasExplicitViewPreference: parsed.schemaVersion === 1
        || parsed.viewModeExplicit === true,
    }
  } catch {
    return fallback
  }
}

export function writeMindmapListPreferences(preferences, storage, options = {}) {
  const target = resolveStorage(storage)
  if (!target?.setItem) return false
  const values = normalizeMindmapListPreferences(preferences)
  try {
    target.setItem(MINDMAP_LIST_PREFERENCE_KEY, JSON.stringify({
      schemaVersion: 2,
      viewModeExplicit: options.viewModeExplicit !== false,
      values,
    }))
    return true
  } catch {
    return false
  }
}

export function resolveInitialMindmapListViewMode(preferenceState, isCompactViewport = false) {
  if (preferenceState?.hasExplicitViewPreference) {
    return normalizeMindmapListPreferences(preferenceState.preferences).viewMode
  }
  return isCompactViewport ? 'grid' : DEFAULT_MINDMAP_LIST_PREFERENCES.viewMode
}

export function resolveMindmapListSort(sortKey) {
  return MINDMAP_LIST_SORT_OPTIONS[sortKey]
    || MINDMAP_LIST_SORT_OPTIONS[DEFAULT_MINDMAP_LIST_PREFERENCES.sortKey]
}
