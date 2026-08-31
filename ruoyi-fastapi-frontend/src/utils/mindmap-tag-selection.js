export const MINDMAP_TAG_SELECTION_MODE_SINGLE = 'single'
export const MINDMAP_TAG_SELECTION_MODE_MULTIPLE = 'multiple'

export function normalizeMindmapTagSelectionMode(value) {
  return value === MINDMAP_TAG_SELECTION_MODE_SINGLE
    ? MINDMAP_TAG_SELECTION_MODE_SINGLE
    : MINDMAP_TAG_SELECTION_MODE_MULTIPLE
}

function idKey(value) {
  return value === null || value === undefined || value === '' ? '' : String(value)
}

function managedTagId(tag) {
  if (!tag || typeof tag !== 'object') return ''
  return idKey(tag.tagId ?? tag.id)
}

export function hasMindmapManagedTag(currentTags, selectedTag) {
  const selectedTagId = managedTagId(selectedTag)
  return Boolean(selectedTagId) && currentTags.some(tag => managedTagId(tag) === selectedTagId)
}

export function buildMindmapTagSelectionIndex(categories = [], tags = []) {
  const categoryModeById = new Map()
  const categoryIdByTagId = new Map()

  categories.forEach(category => {
    const categoryId = idKey(category?.id)
    if (!categoryId) return
    categoryModeById.set(categoryId, normalizeMindmapTagSelectionMode(category.selectionMode))
  })
  tags.forEach(tag => {
    const tagId = managedTagId(tag)
    const categoryId = idKey(tag?.categoryId)
    if (tagId && categoryId) categoryIdByTagId.set(tagId, categoryId)
  })

  return { categoryModeById, categoryIdByTagId }
}

function resolveTagCategoryId(tag, index) {
  const directCategoryId = idKey(tag?.categoryId)
  if (directCategoryId) return directCategoryId
  return index.categoryIdByTagId.get(managedTagId(tag)) || ''
}

export function getMindmapTagSelectionMode(tag, index) {
  const categoryId = resolveTagCategoryId(tag, index)
  return normalizeMindmapTagSelectionMode(index.categoryModeById.get(categoryId))
}

export function removeMindmapSingleSelectionPeers(currentTags, selectedTag, index) {
  const selectedCategoryId = resolveTagCategoryId(selectedTag, index)
  if (
    !selectedCategoryId
    || index.categoryModeById.get(selectedCategoryId) !== MINDMAP_TAG_SELECTION_MODE_SINGLE
  ) {
    return [...currentTags]
  }
  return currentTags.filter(tag => resolveTagCategoryId(tag, index) !== selectedCategoryId)
}

export function normalizeMindmapSingleSelectionTags(currentTags, index) {
  const seenSingleCategories = new Set()
  const normalizedReversed = []

  for (let offset = currentTags.length - 1; offset >= 0; offset -= 1) {
    const tag = currentTags[offset]
    const categoryId = resolveTagCategoryId(tag, index)
    const isSingle = categoryId
      && index.categoryModeById.get(categoryId) === MINDMAP_TAG_SELECTION_MODE_SINGLE
    if (isSingle && seenSingleCategories.has(categoryId)) continue
    if (isSingle) seenSingleCategories.add(categoryId)
    normalizedReversed.push(tag)
  }

  return normalizedReversed.reverse()
}
