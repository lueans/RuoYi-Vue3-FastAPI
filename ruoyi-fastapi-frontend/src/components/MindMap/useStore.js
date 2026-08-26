import { reactive, readonly, markRaw } from 'vue'
import {
  DEFAULT_MINDMAP_LOCAL_CONFIG,
  createMindmapLocalConfigRecord,
  createMindmapRuntimeConfigRecord,
  normalizeMindmapLocalConfigPatch,
  normalizeMindmapLocalConfigRecord,
  normalizeMindmapRuntimeConfigPatch,
  normalizeMindmapRuntimeConfigRecord,
} from '../../utils/mindmap-local-config.js'
import {
  hasMindmapLocalWorkspaceRoot,
  isUnsupportedMindmapLocalWorkspaceRecord,
  normalizeMindmapLocalWorkspacePatch,
  normalizeMindmapLocalWorkspaceRecord,
  serializeMindmapLocalWorkspaceRecord,
} from '../../utils/mindmap-local-workspace.js'

const STORAGE_KEY_DATA = 'MIND_MAP_DATA'
const STORAGE_KEY_CONFIG = 'MIND_MAP_CONFIG'
const STORAGE_KEY_LOCAL_CONFIG = 'MIND_MAP_LOCAL_CONFIG'

const READONLY_SAFE_SIDEBARS = new Set([
  'outline',
  'shortcutKey',
  'versionHistory',
  'collaboratorManager',
  'noteSidebar',
  'comments',
])
const GLOBAL_PROPERTY_SIDEBARS = new Set(['baseStyle', 'structure', 'theme'])

export function isMindmapSidebarReadonlySafe(name) {
  return typeof name === 'string' && READONLY_SAFE_SIDEBARS.has(name)
}

const state = reactive({
  mindMap: null,
  activeSidebar: null,
  lastPropertySidebar: 'baseStyle',
  isReadonly: false,
  canManageCollaborators: false,
  localConfig: { ...DEFAULT_MINDMAP_LOCAL_CONFIG },
  sidebarZIndex: 2001,
})

function setMindMap(instance) {
  state.mindMap = instance ? markRaw(instance) : null
}

function setActiveSidebar(name) {
  if (name && state.isReadonly && !isMindmapSidebarReadonlySafe(name)) {
    return false
  }
  state.activeSidebar = name
  if (GLOBAL_PROPERTY_SIDEBARS.has(name)) state.lastPropertySidebar = name
  return true
}

function setIsReadonly(val) {
  state.isReadonly = val === true
  if (
    state.isReadonly
    && state.activeSidebar
    && !isMindmapSidebarReadonlySafe(state.activeSidebar)
  ) {
    state.activeSidebar = null
  }
}

function setCanManageCollaborators(val) {
  state.canManageCollaborators = val === true
  if (!state.canManageCollaborators && state.activeSidebar === 'collaboratorManager') {
    state.activeSidebar = null
  }
}

function setLocalConfig(config) {
  Object.assign(state.localConfig, normalizeMindmapLocalConfigPatch(config))
  try {
    localStorage.setItem(
      STORAGE_KEY_LOCAL_CONFIG,
      JSON.stringify(createMindmapLocalConfigRecord(state.localConfig)),
    )
  } catch {}
}

function initLocalConfig() {
  Object.assign(state.localConfig, DEFAULT_MINDMAP_LOCAL_CONFIG)
  try {
    const saved = localStorage.getItem(STORAGE_KEY_LOCAL_CONFIG)
    if (saved) {
      const parsed = JSON.parse(saved)
      Object.assign(state.localConfig, normalizeMindmapLocalConfigRecord(parsed))
      localStorage.setItem(
        STORAGE_KEY_LOCAL_CONFIG,
        JSON.stringify(createMindmapLocalConfigRecord(state.localConfig)),
      )
    }
  } catch {
    Object.assign(state.localConfig, DEFAULT_MINDMAP_LOCAL_CONFIG)
    try {
      localStorage.removeItem(STORAGE_KEY_LOCAL_CONFIG)
    } catch {}
  }
}

function storeData(data) {
  let patch
  try {
    patch = normalizeMindmapLocalWorkspacePatch(data)
  } catch {
    return false
  }
  let existing = {}
  let saved
  try {
    saved = localStorage.getItem(STORAGE_KEY_DATA)
  } catch {
    return false
  }
  if (saved) {
    try {
      const parsed = JSON.parse(saved)
      if (isUnsupportedMindmapLocalWorkspaceRecord(parsed)) return false
      existing = normalizeMindmapLocalWorkspaceRecord(parsed) || {}
      if (
        hasMindmapLocalWorkspaceRoot(parsed)
        && !Object.prototype.hasOwnProperty.call(existing, 'root')
        && !Object.prototype.hasOwnProperty.call(patch, 'root')
      ) return false
    } catch {
      existing = {}
    }
  }
  try {
    localStorage.setItem(
      STORAGE_KEY_DATA,
      serializeMindmapLocalWorkspaceRecord({ ...existing, ...patch }),
    )
    return true
  } catch {
    return false
  }
}

function getData() {
  let parsed
  try {
    const saved = localStorage.getItem(STORAGE_KEY_DATA)
    if (!saved) return null
    parsed = JSON.parse(saved)
  } catch {
    try {
      localStorage.removeItem(STORAGE_KEY_DATA)
    } catch {}
    return null
  }
  if (isUnsupportedMindmapLocalWorkspaceRecord(parsed)) return null
  const normalized = normalizeMindmapLocalWorkspaceRecord(parsed)
  if (!normalized) {
    try {
      localStorage.removeItem(STORAGE_KEY_DATA)
    } catch {}
    return null
  }
  if (
    hasMindmapLocalWorkspaceRoot(parsed)
    && !Object.prototype.hasOwnProperty.call(normalized, 'root')
  ) return null
  try {
    localStorage.setItem(
      STORAGE_KEY_DATA,
      serializeMindmapLocalWorkspaceRecord(normalized),
    )
  } catch {
    // 迁移回写失败不影响已安全解析的旧快照，也不能因此删除用户数据。
  }
  return normalized
}

function storeConfig(config) {
  let existing = {}
  try {
    existing = normalizeMindmapRuntimeConfigRecord(
      JSON.parse(localStorage.getItem(STORAGE_KEY_CONFIG) || '{}'),
    )
  } catch {}
  const next = {
    ...existing,
    ...normalizeMindmapRuntimeConfigPatch(config),
  }
  try {
    localStorage.setItem(
      STORAGE_KEY_CONFIG,
      JSON.stringify(createMindmapRuntimeConfigRecord(next)),
    )
  } catch {}
}

function getConfig() {
  try {
    const config = normalizeMindmapRuntimeConfigRecord(
      JSON.parse(localStorage.getItem(STORAGE_KEY_CONFIG) || '{}'),
    )
    localStorage.setItem(
      STORAGE_KEY_CONFIG,
      JSON.stringify(createMindmapRuntimeConfigRecord(config)),
    )
    return config
  } catch {
    try {
      localStorage.removeItem(STORAGE_KEY_CONFIG)
    } catch {}
    return {}
  }
}

function nextSidebarZIndex() {
  return ++state.sidebarZIndex
}

function resetState() {
  state.mindMap = null
  state.activeSidebar = null
  state.lastPropertySidebar = 'baseStyle'
  state.isReadonly = false
  state.canManageCollaborators = false
  state.sidebarZIndex = 2001
}

export const store = readonly(state)
export const actions = {
  setMindMap,
  setActiveSidebar,
  setIsReadonly,
  setCanManageCollaborators,
  setLocalConfig,
  initLocalConfig,
  storeData,
  getData,
  storeConfig,
  getConfig,
  nextSidebarZIndex,
  resetState,
}

export default { store, actions }
