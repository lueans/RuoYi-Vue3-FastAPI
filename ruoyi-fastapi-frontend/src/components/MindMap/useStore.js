import { reactive, readonly, markRaw } from 'vue'

const STORAGE_KEY_DATA = 'MIND_MAP_DATA'
const STORAGE_KEY_CONFIG = 'MIND_MAP_CONFIG'
const STORAGE_KEY_LOCAL_CONFIG = 'MIND_MAP_LOCAL_CONFIG'

const defaultLocalConfig = {
  isDark: false,
  isZenMode: false,
  openNodeRichText: true,
  isShowScrollbar: false,
  useLeftKeySelectionRightKeyDrag: true,
  enableAi: false,
}

const state = reactive({
  mindMap: null,
  activeSidebar: null,
  isReadonly: false,
  localConfig: { ...defaultLocalConfig },
  sidebarZIndex: 2001,
})

function setMindMap(instance) {
  state.mindMap = instance ? markRaw(instance) : null
}

function setActiveSidebar(name) {
  state.activeSidebar = name
}

function setIsReadonly(val) {
  state.isReadonly = val
}

function setLocalConfig(config) {
  Object.assign(state.localConfig, config)
  try {
    // 只保存与默认值不同的项，避免新默认值被旧 localStorage 覆盖
    const toSave = {}
    for (const key of Object.keys(state.localConfig)) {
      if (state.localConfig[key] !== defaultLocalConfig[key]) {
        toSave[key] = state.localConfig[key]
      }
    }
    localStorage.setItem(STORAGE_KEY_LOCAL_CONFIG, JSON.stringify(toSave))
  } catch {}
}

function initLocalConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_LOCAL_CONFIG)
    if (saved) {
      const parsed = JSON.parse(saved)
      // 以默认值为基底，仅覆盖用户显式修改过的项
      Object.assign(state.localConfig, defaultLocalConfig, parsed)
    }
  } catch {}
}

function storeData(data) {
  try {
    const existing = JSON.parse(localStorage.getItem(STORAGE_KEY_DATA) || '{}')
    Object.assign(existing, data)
    localStorage.setItem(STORAGE_KEY_DATA, JSON.stringify(existing))
  } catch {}
}

function getData() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY_DATA) || 'null')
  } catch {
    return null
  }
}

function storeConfig(config) {
  try {
    const existing = JSON.parse(localStorage.getItem(STORAGE_KEY_CONFIG) || '{}')
    Object.assign(existing, config)
    localStorage.setItem(STORAGE_KEY_CONFIG, JSON.stringify(existing))
  } catch {}
}

function getConfig() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY_CONFIG) || '{}')
  } catch {
    return {}
  }
}

function nextSidebarZIndex() {
  return ++state.sidebarZIndex
}

function resetState() {
  state.mindMap = null
  state.activeSidebar = null
  state.isReadonly = false
  state.sidebarZIndex = 2001
}

export const store = readonly(state)
export const actions = {
  setMindMap,
  setActiveSidebar,
  setIsReadonly,
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
