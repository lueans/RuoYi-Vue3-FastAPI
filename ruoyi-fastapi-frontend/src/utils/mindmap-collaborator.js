export const MINDMAP_COLLABORATOR_PERMISSION = Object.freeze({
  view: 0,
  edit: 1,
})

export function normalizeCollaboratorSearchKeyword(value, maxLength = 64) {
  return String(value ?? '').trim().slice(0, maxLength)
}

export function isCollaboratorPermissionDowngrade(currentPermission, nextPermission) {
  return Number(currentPermission) === MINDMAP_COLLABORATOR_PERMISSION.edit
    && Number(nextPermission) === MINDMAP_COLLABORATOR_PERMISSION.view
}

export function getCollaboratorErrorMessage(error, fallback) {
  return error?.response?.data?.msg || error?.message || fallback
}
