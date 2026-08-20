import {
  buildMindmapListRouteQuery,
  decodeMindmapListReturnState,
} from './mindmap-list-route.js'

export function parseMindmapRouteId(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return null
  const normalized = String(value).trim()
  if (!/^[1-9]\d*$/.test(normalized)) return null
  const id = Number(normalized)
  return Number.isSafeInteger(id) ? id : null
}

export function parseMindmapFocusNodeUid(value) {
  if (typeof value !== 'string') return ''
  const normalized = value.trim()
  if (!normalized || normalized.length > 64) return ''
  if ([...normalized].some(char => {
    const code = char.codePointAt(0)
    return code < 32 || code === 127
  })) return ''
  return normalized
}

export function createMindmapEditorSessionKey(mindmapId, readonly = false) {
  const normalizedId = parseMindmapRouteId(mindmapId)
  if (normalizedId === null) return 'invalid'
  return `${normalizedId}:${readonly ? 'readonly' : 'edit'}`
}

export function isSharedMindmapContext(value) {
  return value === 'shared'
}

export function buildMindmapListRoute(accessType, returnListState) {
  const returnState = decodeMindmapListReturnState(returnListState)
  if (returnState) {
    return {
      path: '/mindmap/index',
      query: buildMindmapListRouteQuery(returnState),
    }
  }
  return {
    path: '/mindmap/index',
    ...(isSharedMindmapContext(accessType) ? { query: { scope: 'shared' } } : {}),
  }
}

export function buildMindmapNodeSearchRoute(item, { returnList } = {}) {
  const mindmapId = parseMindmapRouteId(item?.mindmapId)
  const nodeUid = parseMindmapFocusNodeUid(item?.nodeUid)
  if (mindmapId === null || !nodeUid) return null
  return {
    path: '/mindmap/edit',
    query: {
      id: mindmapId,
      focusNode: nodeUid,
      ...(item?.canEdit === true ? {} : { readonly: '1' }),
      ...(item?.accessType === 'shared' ? { from: 'shared' } : {}),
      ...(decodeMindmapListReturnState(returnList) ? { returnList } : {}),
    },
  }
}
