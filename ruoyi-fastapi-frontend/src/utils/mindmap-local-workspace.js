import { layoutValueList } from '../libs/simple-mind-map/src/constants/constant.js'
import {
  stringifyJsonValueIterative,
} from '../libs/simple-mind-map/src/utils/jsonClone.js'
import { normalizeViewTransformData } from '../libs/simple-mind-map/src/utils/viewState.js'
import { normalizeMindmapDocumentData } from './mindmap-document-config.js'
import { assertMindmapImportDocument } from './mindmap-import-validation.js'

export const MINDMAP_LOCAL_WORKSPACE_SCHEMA_VERSION = 1
export const MINDMAP_LOCAL_WORKSPACE_MAX_BYTES = 2 * 1024 * 1024

const DEFAULT_LAYOUT = 'logicalStructure'
const DEFAULT_THEME_TEMPLATE = 'default'
const ALLOWED_LAYOUTS = new Set(layoutValueList)
const WORKSPACE_FIELDS = ['root', 'layout', 'theme', 'view', 'documentData']
const DOCUMENT_META_FIELDS = ['layout', 'theme', 'view', 'documentData']

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key)
const isRecord = value => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
)

function normalizeRoot(value) {
  assertMindmapImportDocument({ root: value })
  const root = normalizeMindmapDocumentData({ root: value }).root
  assertMindmapImportDocument({ root })
  return root
}

function normalizeLayout(value) {
  return typeof value === 'string' && ALLOWED_LAYOUTS.has(value)
    ? value
    : undefined
}

function normalizeTheme(value) {
  if (!isRecord(value)) return undefined
  const template = typeof value.template === 'string'
    && value.template.length > 0
    && value.template.length <= 100
    ? value.template
    : DEFAULT_THEME_TEMPLATE
  return {
    template,
    config: normalizeMindmapDocumentData(value.config),
  }
}

function normalizeView(value) {
  if (value === null) return null
  return normalizeViewTransformData(value)
}

function normalizeFields(source, { strictPatch = false } = {}) {
  if (!isRecord(source)) return null
  const output = {}

  if (hasOwn(source, 'root')) {
    try {
      output.root = normalizeRoot(source.root)
    } catch (error) {
      if (strictPatch) throw error
    }
  }

  if (hasOwn(source, 'layout')) {
    const layout = normalizeLayout(source.layout)
    if (layout !== undefined) output.layout = layout
    else if (strictPatch) throw new TypeError('脑图布局类型无效')
  }

  if (hasOwn(source, 'theme')) {
    const theme = normalizeTheme(source.theme)
    if (theme !== undefined) output.theme = theme
    else if (strictPatch) throw new TypeError('脑图主题配置无效')
  }

  if (hasOwn(source, 'view')) {
    const view = normalizeView(source.view)
    if (view !== null || source.view === null) output.view = view
    else if (strictPatch) throw new TypeError('脑图视图状态无效')
  }

  if (hasOwn(source, 'documentData')) {
    output.documentData = normalizeMindmapDocumentData(source.documentData)
  }

  return output
}

function getRecordValues(value) {
  if (!isRecord(value)) return null
  if (!hasOwn(value, 'schemaVersion')) return value
  if (
    value.schemaVersion !== MINDMAP_LOCAL_WORKSPACE_SCHEMA_VERSION
    || !isRecord(value.values)
  ) return null
  return value.values
}

export function isUnsupportedMindmapLocalWorkspaceRecord(value) {
  return isRecord(value)
    && hasOwn(value, 'schemaVersion')
    && value.schemaVersion !== MINDMAP_LOCAL_WORKSPACE_SCHEMA_VERSION
}

export function normalizeMindmapLocalWorkspaceRecord(value) {
  const source = getRecordValues(value)
  return source ? normalizeFields(source) : null
}

export function hasMindmapLocalWorkspaceRoot(value) {
  const source = getRecordValues(value)
  return Boolean(source && hasOwn(source, 'root'))
}

export function normalizeMindmapLocalWorkspacePatch(value) {
  if (!isRecord(value)) throw new TypeError('本地脑图快照必须是对象')
  return normalizeFields(value, { strictPatch: true })
}

/**
 * Normalize the file-level metadata emitted by editor sidebars. The same
 * boundary is shared by anonymous local workspaces and server-backed Yjs
 * sessions so both resource types accept exactly the same values.
 */
export function normalizeMindmapDocumentMetaPatch(value) {
  if (!isRecord(value)) throw new TypeError('脑图文档元数据必须是对象')
  const normalized = normalizeFields(value, { strictPatch: true })
  const output = {}
  for (const field of DOCUMENT_META_FIELDS) {
    if (hasOwn(normalized, field)) output[field] = normalized[field]
  }
  return output
}

export function createMindmapLocalWorkspaceRecord(value) {
  const normalized = normalizeMindmapLocalWorkspacePatch(value)
  const values = {}
  for (const field of WORKSPACE_FIELDS) {
    if (hasOwn(normalized, field)) values[field] = normalized[field]
  }
  return {
    schemaVersion: MINDMAP_LOCAL_WORKSPACE_SCHEMA_VERSION,
    values,
  }
}

function getUtf8ByteLength(value) {
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(value).byteLength
  }
  return encodeURIComponent(value).replace(/%[0-9A-F]{2}|./g, 'x').length
}

export function serializeMindmapLocalWorkspaceRecord(
  value,
  maxBytes = MINDMAP_LOCAL_WORKSPACE_MAX_BYTES,
) {
  const serialized = stringifyJsonValueIterative(
    createMindmapLocalWorkspaceRecord(value),
  )
  if (getUtf8ByteLength(serialized) > maxBytes) {
    const error = new Error(`本地脑图快照不能超过 ${maxBytes} 字节`)
    error.code = 'MINDMAP_LOCAL_WORKSPACE_TOO_LARGE'
    throw error
  }
  return serialized
}

export function getDefaultMindmapLocalWorkspace() {
  return {
    layout: DEFAULT_LAYOUT,
    theme: { template: DEFAULT_THEME_TEMPLATE, config: {} },
    view: null,
    documentData: {},
  }
}
