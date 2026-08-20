// Linear breadth-first traversal shared by search, selection, drag and
// keyboard navigation. Object identity de-duplication makes malformed legacy
// graphs terminate without changing valid tree traversal order.
export const bfsWalk = (root, callback) => {
  const queue = [{ node: root, parent: null }]
  const enqueued = new WeakSet()
  if (root && typeof root === 'object') enqueued.add(root)
  let cursor = 0

  while (cursor < queue.length) {
    const { node, parent } = queue[cursor]
    cursor += 1

    if (callback(node, parent) === 'stop') return

    const children = Array.isArray(node?.children) ? node.children : []
    for (let index = 0; index < children.length; index += 1) {
      const child = children[index]
      const isObjectChild = Boolean(child && typeof child === 'object')
      if (isObjectChild && enqueued.has(child)) continue
      if (isObjectChild) enqueued.add(child)
      queue.push({ node: child, parent: node })
    }
  }
}
