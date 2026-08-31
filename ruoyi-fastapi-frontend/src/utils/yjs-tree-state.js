/** Yjs 脑图树状态的纯同步工具。 */

import { isSameObject } from '../libs/simple-mind-map/src/utils/deepEqual.js'

function jsonEquals(left, right) {
  return isSameObject(left, right)
}

export function stripManagedTagDefinitions(data = {}) {
  const output = { ...data }
  if (Array.isArray(output.tag)) {
    output.tag = output.tag.map(tag => {
      if (!tag || typeof tag !== 'object' || !tag.tagId) return tag
      return Object.fromEntries(Object.entries({
        tagId: tag.tagId,
        categoryId: tag.categoryId,
        placement: tag.placement,
        align: tag.align,
      }).filter(([, value]) => value !== undefined))
    })
  }
  return output
}

// 节点选中状态只属于当前客户端的 UI，不能进入共享 Yjs 文档。
export function normalizeNodeDataForYjs(data = {}) {
  const output = stripManagedTagDefinitions(data)
  delete output.isActive
  return output
}

// 协作树刷新前恢复当前客户端自己的选区，并清除其他客户端或旧数据中
// 遗留的 isActive。使用迭代遍历以兼容超深脑图和损坏的循环数据。
export function applyLocalActiveNodeState(root, nodeUids = []) {
  if (!root || typeof root !== 'object') return root
  const activeUids = new Set(
    (Array.isArray(nodeUids) ? nodeUids : []).map(String).filter(Boolean),
  )
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    if (node.data && typeof node.data === 'object') {
      node.data.isActive = activeUids.has(String(node.data.uid || ''))
    }
    const children = Array.isArray(node.children) ? node.children : []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push(children[index])
    }
  }
  return root
}

export function flattenMindmapTree(node, parentUid = '', result = {}) {
  if (!node || typeof node !== 'object') return result
  const pending = [{ node, parentUid }]
  const visited = new WeakSet()
  while (pending.length) {
    const current = pending.pop()
    if (!current?.node || typeof current.node !== 'object' || visited.has(current.node)) continue
    visited.add(current.node)
    const uid = current.node.data?.uid
    if (!uid) continue
    const children = Array.isArray(current.node.children) ? current.node.children : []
    result[uid] = {
      data: normalizeNodeDataForYjs(current.node.data),
      children: children.map(child => child?.data?.uid).filter(Boolean),
      parentUid: current.parentUid || '',
    }
    // 逆序压栈以保持原递归实现的深度优先访问顺序。
    for (let index = children.length - 1; index >= 0; index -= 1) {
      pending.push({ node: children[index], parentUid: uid })
    }
  }
  return result
}

export function setYMapValueIfChanged(yMap, key, value) {
  if (jsonEquals(yMap.get(key), value)) return false
  yMap.set(key, value)
  return true
}

export function replaceYMapEntries(yMap, values = {}) {
  let changed = false
  const desiredKeys = new Set(Object.keys(values))
  for (const key of Array.from(yMap.keys())) {
    if (!desiredKeys.has(key)) {
      yMap.delete(key)
      changed = true
    }
  }
  for (const [key, value] of Object.entries(values)) {
    changed = setYMapValueIfChanged(yMap, key, value) || changed
  }
  return changed
}

export function replaceYArrayValues(yArray, values = []) {
  const current = yArray.toArray()
  if (current.length === values.length && current.every((value, index) => value === values[index])) {
    return false
  }
  if (yArray.length) yArray.delete(0, yArray.length)
  if (values.length) yArray.push(values)
  return true
}

export function synchronizeYjsParentUids(yNodes, preferredRootUid = '') {
  const nodeUids = Array.from(yNodes.keys()).map(String).sort()
  if (!nodeUids.length) return ''
  const nodeUidSet = new Set(nodeUids)
  const normalizedPreferredRoot = String(preferredRootUid || '')
  const previousParentByChild = new Map(nodeUids.map(uid => [
    uid,
    String(yNodes.get(uid)?.get('parentUid') || ''),
  ]))

  // 先清理每个父节点内部的重复、自引用和悬空引用，但暂不解决多父。
  const childrenByParent = new Map()
  for (const parentUid of nodeUids) {
    const seen = new Set()
    const children = []
    for (const rawChildUid of (yNodes.get(parentUid)?.get('children')?.toArray() || [])) {
      const childUid = String(rawChildUid || '')
      if (
        !childUid
        || childUid === parentUid
        || !nodeUidSet.has(childUid)
        || seen.has(childUid)
      ) continue
      seen.add(childUid)
      children.push(childUid)
    }
    childrenByParent.set(parentUid, children)
  }

  const referencedUids = new Set(Array.from(childrenByParent.values()).flat())
  const previousRoots = nodeUids.filter(uid => !previousParentByChild.get(uid))
  const unreferencedUids = nodeUids.filter(uid => !referencedUids.has(uid))
  const rootUid = nodeUidSet.has(normalizedPreferredRoot)
    ? normalizedPreferredRoot
    : (previousRoots[0] || unreferencedUids[0] || nodeUids[0])

  // 根节点身份稳定优先，任何把根挂到其他节点的并发边都直接丢弃。
  for (const parentUid of nodeUids) {
    childrenByParent.set(
      parentUid,
      childrenByParent.get(parentUid).filter(childUid => childUid !== rootUid),
    )
  }

  const candidateParents = new Map()
  for (const parentUid of nodeUids) {
    for (const childUid of childrenByParent.get(parentUid)) {
      const candidates = candidateParents.get(childUid) || []
      candidates.push(parentUid)
      candidateParents.set(childUid, candidates)
    }
  }

  // parentUid 是 Y.Map 中已经 CRDT 收敛的单值，若它仍是候选父级则优先；
  // 否则按父 UID 排序后的第一个确定性胜出，所有客户端得到同一拓扑。
  const parentByChild = new Map()
  for (const [childUid, candidates] of candidateParents) {
    const previousParentUid = previousParentByChild.get(childUid)
    parentByChild.set(
      childUid,
      candidates.includes(previousParentUid) ? previousParentUid : candidates[0],
    )
  }
  for (const parentUid of nodeUids) {
    childrenByParent.set(
      parentUid,
      childrenByParent.get(parentUid).filter(
        childUid => parentByChild.get(childUid) === parentUid,
      ),
    )
  }

  // parentByChild 是每个节点最多一条出边的函数图。逐路径找环，并从
  // 每个环中移除 UID 最大节点的父边，保证修复结果与遍历/插入顺序无关。
  const processed = new Set()
  for (const startUid of nodeUids) {
    if (processed.has(startUid)) continue
    const path = []
    const pathIndex = new Map()
    let currentUid = startUid
    while (parentByChild.has(currentUid) && !processed.has(currentUid)) {
      if (pathIndex.has(currentUid)) {
        const cycle = path.slice(pathIndex.get(currentUid)).sort()
        const detachedUid = cycle[cycle.length - 1]
        const parentUid = parentByChild.get(detachedUid)
        parentByChild.delete(detachedUid)
        childrenByParent.set(
          parentUid,
          childrenByParent.get(parentUid).filter(childUid => childUid !== detachedUid),
        )
        break
      }
      pathIndex.set(currentUid, path.length)
      path.push(currentUid)
      currentUid = parentByChild.get(currentUid)
    }
    for (const uid of path) processed.add(uid)
  }

  // 不丢弃并发创建、断链或打断环后形成的分支；按 UID 稳定追加到根。
  const rootChildren = childrenByParent.get(rootUid)
  for (const uid of nodeUids) {
    if (uid === rootUid || parentByChild.has(uid)) continue
    rootChildren.push(uid)
    parentByChild.set(uid, rootUid)
  }

  for (const parentUid of nodeUids) {
    const yChildren = yNodes.get(parentUid)?.get('children')
    if (yChildren) replaceYArrayValues(yChildren, childrenByParent.get(parentUid))
  }
  yNodes.forEach((yNode, uid) => {
    setYMapValueIfChanged(yNode, 'parentUid', uid === rootUid ? '' : parentByChild.get(uid) || '')
  })
  return rootUid
}

export function deleteYjsSubtree(yNodes, rootUid) {
  const pending = [rootUid]
  const deleted = new Set()
  while (pending.length) {
    const uid = pending.pop()
    if (!uid || deleted.has(uid)) continue
    const yNode = yNodes.get(uid)
    if (!yNode) continue
    deleted.add(uid)
    pending.push(...(yNode.get('children')?.toArray() || []))
  }
  for (const uid of deleted) yNodes.delete(uid)
  yNodes.forEach(yNode => {
    const yChildren = yNode.get('children')
    if (!yChildren) return
    replaceYArrayValues(
      yChildren,
      yChildren.toArray().filter(uid => !deleted.has(uid)),
    )
  })
  return deleted
}
