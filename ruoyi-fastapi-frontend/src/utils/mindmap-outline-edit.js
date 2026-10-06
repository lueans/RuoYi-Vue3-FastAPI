function toPlainOutlineLabel(data) {
  const text = String(data?.text ?? '')
  // Plain nodes can contain HTML examples or comparisons; only an explicit
  // rich-text node is markup. Keep paragraph boundaries when editing it.
  if (!data?.richText) return text
  const plain = text.replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(?:div|p|h[1-6]|li)>\s*(?=<)/gi, '\n')
    .replace(/<[^>]*>/g, '')
  if (typeof document !== 'undefined') {
    const template = document.createElement('template')
    template.innerHTML = plain.replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return template.content.textContent || ''
  }
  const entities = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }
  return plain.replace(/&(#x[\da-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (match, name) => {
    const key = name.toLowerCase()
    if (key[0] !== '#') return entities[key]
    const point = Number.parseInt(key.slice(key[1] === 'x' ? 2 : 1), key[1] === 'x' ? 16 : 10)
    return point >= 0 && point <= 0x10ffff ? String.fromCodePoint(point) : match
  })
}

export function createOutlineTreeNode(node, createUid) {
  const makeNode = source => {
    const originalData = { ...(source?.data || {}) }
    const uid = originalData.uid || createUid()
    const label = toPlainOutlineLabel(originalData)
    return { label, originalLabel: label, uid, originalData: { ...originalData, uid }, isNew: false, children: [] }
  }
  const root = makeNode(node)
  const pending = [{ source: node, target: root }]
  const seen = new WeakSet()
  if (node && typeof node === 'object') seen.add(node)
  while (pending.length) {
    const { source, target } = pending.pop()
    for (const child of Array.isArray(source?.children) ? source.children : []) {
      if (!child || typeof child !== 'object' || seen.has(child)) continue
      seen.add(child)
      const next = makeNode(child)
      target.children.push(next)
      pending.push({ source: child, target: next })
    }
  }
  return root
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

// 大纲始终包含完整文档；画布折叠后代尚无运行时实例。只在当前大纲
// 会话中临时展开目标路径，不修改持久化的 expand 或撤销/协作数据。
export async function ensureOutlineRuntimeNodes(mindMap, uids, isCurrent = () => true) {
  const renderer = mindMap?.renderer
  const root = renderer?.renderTree
  if (!root || renderer.destroyed || !isCurrent()) return null
  const keys = [...new Set(uids.map(String))]
  const existing = keys.map(uid => renderer.findNodeByUid(uid))
  if (!renderer.isRendering && existing.every(Boolean)) return existing

  const wanted = new Set(keys)
  const found = new Map()
  const parents = new WeakMap()
  const seen = new WeakSet()
  const pending = [{ node: root, parent: null }]
  while (pending.length && wanted.size) {
    const { node, parent } = pending.pop()
    if (!node || typeof node !== 'object' || seen.has(node)) continue
    seen.add(node)
    parents.set(node, parent)
    const uid = String(node.data?.uid)
    if (wanted.delete(uid)) found.set(uid, node)
    for (const child of node.children || []) pending.push({ node: child, parent: node })
  }
  if (wanted.size || !isCurrent()) return null
  const expanded = new Set(renderer.outlineExpandedNodeUids || [])
  for (const node of found.values()) {
    for (let parent = parents.get(node); parent; parent = parents.get(parent)) {
      if (parent.data?.expand === false) expanded.add(String(parent.data.uid))
    }
  }
  renderer.outlineExpandedNodeUids = expanded
  await new Promise((resolve, reject) => {
    let settled = false
    const finish = error => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      if (error) reject(error)
      else resolve()
    }
    const timeout = setTimeout(() => finish(new Error('大纲节点准备超时，请重试')), 15000)
    try {
      mindMap.renderAsync(() => finish(), 'outline_reveal', finish)
    } catch (error) {
      finish(error)
    }
  })
  if (!isCurrent() || renderer.destroyed || renderer.renderTree !== root) return null
  const nodes = keys.map(uid => renderer.findNodeByUid(uid))
  return nodes.every(Boolean) ? nodes : null
}

export function clearOutlineRuntimeExpansion(mindMap) {
  const renderer = mindMap?.renderer
  if (!renderer?.outlineExpandedNodeUids) return
  renderer.outlineExpandedNodeUids = null
  if (!renderer.destroyed) mindMap.render(undefined, 'outline_reveal_cleanup')
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
