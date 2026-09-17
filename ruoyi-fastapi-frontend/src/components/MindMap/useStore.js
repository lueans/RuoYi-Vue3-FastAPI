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
const STORAGE_KEY_AI_RECOVERY = 'MIND_MAP_AI_RECOVERY_V1'

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

function createLocalDocumentId() {
  const value = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  return `local:${value}`
}

function storeData(data, options = {}) {
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
  const next = { ...existing, ...patch }
  const hasContentPatch = ['root', 'layout', 'theme', 'documentData']
    .some(field => Object.prototype.hasOwnProperty.call(patch, field))
  if (next.root) {
    next.documentId = existing.documentId || createLocalDocumentId()
    if (hasContentPatch) {
      next.revision = Number.isSafeInteger(options.revision)
        ? options.revision
        : Math.max(Number(existing.revision) || 0, 0) + 1
      next.documentHash = options.documentHash || null
      // 任意后续正文编辑都会使“直接撤销 AI 应用”的条件失效。
      next.lastAppliedProposal = options.lastAppliedProposal || null
    } else {
      next.revision = Number(existing.revision) || 1
    }
  }
  try {
    const serialized = serializeMindmapLocalWorkspaceRecord(next)
    localStorage.setItem(
      STORAGE_KEY_DATA,
      serialized,
    )
    if (localStorage.getItem(STORAGE_KEY_DATA) !== serialized) return false
    return true
  } catch {
    return false
  }
}

function replaceData(data, options = {}) {
  let normalized
  try {
    normalized = normalizeMindmapLocalWorkspacePatch(data)
  } catch {
    return false
  }
  if (!normalized?.root) return false
  const next = {
    ...normalized,
    documentId: createLocalDocumentId(),
    revision: 1,
    documentHash: options.documentHash || null,
    lastAppliedProposal: options.lastAppliedProposal || null,
  }
  let serialized
  let previousRaw = null
  let previousRecoveryRaw = null
  try {
    serialized = serializeMindmapLocalWorkspaceRecord(next)
    previousRaw = localStorage.getItem(STORAGE_KEY_DATA)
    previousRecoveryRaw = localStorage.getItem(STORAGE_KEY_AI_RECOVERY)
    if (previousRaw) {
      localStorage.setItem(STORAGE_KEY_AI_RECOVERY, JSON.stringify({
        schemaVersion: 1,
        reason: options.reason || 'ai-open-local',
        createdAt: Date.now(),
        expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000,
        workspace: previousRaw,
      }))
    }
    localStorage.setItem(STORAGE_KEY_DATA, serialized)
    if (localStorage.getItem(STORAGE_KEY_DATA) !== serialized) {
      throw new Error('本地工作区写入后校验失败')
    }
    return next
  } catch {
    try {
      if (previousRaw === null) localStorage.removeItem(STORAGE_KEY_DATA)
      else localStorage.setItem(STORAGE_KEY_DATA, previousRaw)
      if (previousRecoveryRaw === null) localStorage.removeItem(STORAGE_KEY_AI_RECOVERY)
      else localStorage.setItem(STORAGE_KEY_AI_RECOVERY, previousRecoveryRaw)
    } catch {}
    return false
  }
}

// Restore the exact durable local-workspace identity after a transactional AI
// apply fails. Unlike storeData/replaceData this must not advance the revision,
// create a new documentId, or alter lastAppliedProposal.
function restoreData(data) {
  try {
    if (data == null) {
      localStorage.removeItem(STORAGE_KEY_DATA)
      return true
    }
    const normalized = normalizeMindmapLocalWorkspaceRecord(data)
    if (!normalized?.root) return false
    const serialized = serializeMindmapLocalWorkspaceRecord(normalized)
    localStorage.setItem(STORAGE_KEY_DATA, serialized)
    return localStorage.getItem(STORAGE_KEY_DATA) === serialized
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
  if (normalized.root) {
    normalized.documentId ||= createLocalDocumentId()
    normalized.revision = Number(normalized.revision) || 1
    if (!Object.prototype.hasOwnProperty.call(normalized, 'documentHash')) {
      normalized.documentHash = null
    }
  }
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
  replaceData,
  restoreData,
  getData,
  storeConfig,
  getConfig,
  nextSidebarZIndex,
  resetState,
}

export default { store, actions }
