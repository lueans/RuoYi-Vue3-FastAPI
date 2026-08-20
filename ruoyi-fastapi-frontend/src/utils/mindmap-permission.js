export const MINDMAP_FILE_PERMISSIONS = Object.freeze({
  list: Object.freeze(['mindmap:mindmap:list', 'mindmap:list']),
  query: Object.freeze(['mindmap:mindmap:query', 'mindmap:query']),
  add: Object.freeze(['mindmap:mindmap:add', 'mindmap:add']),
  edit: Object.freeze(['mindmap:mindmap:edit', 'mindmap:edit']),
  remove: Object.freeze(['mindmap:mindmap:remove', 'mindmap:remove'])
})

export function hasAnyPermission(permissions, required) {
  if (!Array.isArray(permissions) || !Array.isArray(required)) return false
  return permissions.includes('*:*:*') || required.some(permission => permissions.includes(permission))
}

export function canUseMindmapFolders(permissions) {
  return hasAnyPermission(permissions, ['mindmap:folder:list'])
}
