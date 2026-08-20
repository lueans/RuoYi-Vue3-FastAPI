import { walk } from './treeWalk.js'

// Convert a nested node tree to the flat object shape used by collaboration.
// The shared iterative walker keeps deep input independent of the call stack.
export const transformTreeDataToObject = data => {
  const result = {}

  walk(
    data,
    null,
    (node, parent, isRoot) => {
      const uid = node.data.uid
      if (parent) result[parent.data.uid]?.children.push(uid)
      result[uid] = {
        isRoot,
        data: { ...node.data },
        children: []
      }
    },
    null,
    true
  )

  return result
}

// Rebuild only the graph reachable from the declared root. UID identity is the
// collaboration protocol's node identity, so repeated links and ancestor
// cycles are ignored after their first ordered occurrence.
export const transformObjectMapToTree = (data, cloneData = value => value) => {
  if (!data || typeof data !== 'object') return null
  const uids = Object.keys(data)
  if (uids.length === 0) return null

  const rootUid = uids.find(uid => data[uid]?.isRoot)
  if (!rootUid) return null

  const createNode = uid => ({
    data: cloneData(data[uid]?.data),
    children: []
  })
  const root = createNode(rootUid)
  const visited = new Set([rootUid])
  const stack = [{ uid: rootUid, node: root }]

  while (stack.length > 0) {
    const frame = stack.pop()
    const childUids = Array.isArray(data[frame.uid]?.children)
      ? data[frame.uid].children
      : []
    const childFrames = []

    for (let index = 0; index < childUids.length; index += 1) {
      const childUid = childUids[index]
      if (!Object.prototype.hasOwnProperty.call(data, childUid)) continue
      if (visited.has(childUid)) continue

      visited.add(childUid)
      const childNode = createNode(childUid)
      frame.node.children.push(childNode)
      childFrames.push({ uid: childUid, node: childNode })
    }

    for (let index = childFrames.length - 1; index >= 0; index -= 1) {
      stack.push(childFrames[index])
    }
  }

  return root
}

// Materialize one flat collaboration/history record as a nested subtree
// without mutating the flat map. The returned records preserve protocol fields
// such as isRoot while children become ordered node objects.
export const materializeObjectSubtree = (data, rootUid) => {
  if (!data || typeof data !== 'object') return null
  if (!Object.prototype.hasOwnProperty.call(data, rootUid)) return null

  const createNode = uid => ({ ...data[uid], children: [] })
  const root = createNode(rootUid)
  const visited = new Set([rootUid])
  const stack = [{ uid: rootUid, node: root }]

  while (stack.length > 0) {
    const frame = stack.pop()
    const childUids = Array.isArray(data[frame.uid]?.children)
      ? data[frame.uid].children
      : []
    const childFrames = []

    for (let index = 0; index < childUids.length; index += 1) {
      const childUid = childUids[index]
      if (!Object.prototype.hasOwnProperty.call(data, childUid)) continue
      if (visited.has(childUid)) continue
      visited.add(childUid)

      const childNode = createNode(childUid)
      frame.node.children.push(childNode)
      childFrames.push({ uid: childUid, node: childNode })
    }

    for (let index = childFrames.length - 1; index >= 0; index -= 1) {
      stack.push(childFrames[index])
    }
  }

  return root
}
