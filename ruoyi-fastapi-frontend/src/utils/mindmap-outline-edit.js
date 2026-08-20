function toPlainOutlineLabel(text) {
  return String(text ?? '').replace(/<[^>]*>/g, '')
}

export function createOutlineTreeNode(node, createUid) {
  const originalData = { ...(node?.data || {}) }
  const originalText = String(originalData.text ?? '')
  const uid = originalData.uid || createUid()
  const label = toPlainOutlineLabel(originalText)
  return {
    label,
    originalLabel: label,
    uid,
    originalData: {
      ...originalData,
      uid,
    },
    isNew: false,
    children: (node?.children || []).map(child => createOutlineTreeNode(child, createUid)),
  }
}

export function createNewOutlineNode(createUid, label = '新节点') {
  const uid = createUid()
  return {
    label,
    originalLabel: label,
    uid,
    originalData: {
      text: label,
      uid,
    },
    isNew: true,
    children: [],
  }
}
