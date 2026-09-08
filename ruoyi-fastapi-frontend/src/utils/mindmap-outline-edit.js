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

export function createOutlineRefreshGate({
  isOpen,
  hasLocalEdit,
  schedule,
  refresh,
}) {
  let pending = false
  let scheduled = false

  const flush = () => {
    if (
      !pending
      || scheduled
      || !isOpen()
      || hasLocalEdit()
    ) return false
    scheduled = true
    schedule(() => {
      scheduled = false
      if (!pending || !isOpen() || hasLocalEdit()) return
      pending = false
      refresh()
    })
    return true
  }

  return {
    request() {
      if (!isOpen()) return false
      pending = true
      flush()
      return true
    },
    flush,
    clear() {
      pending = false
    },
    get pending() {
      return pending
    },
  }
}
