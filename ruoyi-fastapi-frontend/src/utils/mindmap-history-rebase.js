import { isSameObject } from '../libs/simple-mind-map/src/utils/deepEqual.js'
import {
  cloneJsonValueIterative,
  stringifyJsonValueIterative,
} from '../libs/simple-mind-map/src/utils/jsonClone.js'
import { trimHistoryEntries } from '../libs/simple-mind-map/src/utils/historyBuffer.js'

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key)
const MAX_REBASE_HISTORY_ENTRIES = 200
const MAX_REBASE_HISTORY_BYTES = 16 * 1024 * 1024

function normalizeNodePropsForComparison(props) {
  const normalized = cloneJsonValueIterative(props)
  if (!normalized || typeof normalized !== 'object') return normalized
  delete normalized.smmVersion
  if (normalized.data && typeof normalized.data === 'object') {
    delete normalized.data.isActive
  }
  return normalized
}

function flattenHistoryTree(root) {
  if (!root || typeof root !== 'object') return null
  const records = new Map()
  const stack = [root]
  while (stack.length) {
    const node = stack.pop()
    const uidValue = node?.data?.uid
    if (uidValue === undefined || uidValue === null) return null
    const uid = String(uidValue)
    if (!uid || records.has(uid)) return null
    const children = Array.isArray(node.children) ? node.children : []
    const props = {}
    for (const [key, value] of Object.entries(node)) {
      if (key !== 'children') props[key] = value
    }
    const clonedProps = cloneJsonValueIterative(props)
    if (!clonedProps || typeof clonedProps !== 'object') return null
    const childUids = []
    for (let index = children.length - 1; index >= 0; index -= 1) {
      const child = children[index]
      const childUidValue = child?.data?.uid
      if (childUidValue === undefined || childUidValue === null) return null
      childUids.unshift(String(childUidValue))
      stack.push(child)
    }
    records.set(uid, {
      props: clonedProps,
      comparableProps: normalizeNodePropsForComparison(clonedProps),
      childUids,
    })
  }
  return {
    rootUid: String(root.data.uid),
    records,
  }
}

function collectChangedUids(before, after) {
  const changed = new Set()
  const uids = new Set([...before.records.keys(), ...after.records.keys()])
  for (const uid of uids) {
    const beforeRecord = before.records.get(uid)
    const afterRecord = after.records.get(uid)
    if (
      !beforeRecord
      || !afterRecord
      || !isSameObject(beforeRecord.comparableProps, afterRecord.comparableProps)
      || !isSameObject(beforeRecord.childUids, afterRecord.childUids)
    ) changed.add(uid)
  }
  if (before.rootUid !== after.rootUid) {
    changed.add(before.rootUid)
    changed.add(after.rootUid)
  }
  return changed
}

function buildRebasedTree(historyTree, remoteTree, remoteChangedUids) {
  const rootUid = remoteTree.rootUid
  const rootRecord = remoteChangedUids.has(rootUid)
    ? remoteTree.records.get(rootUid)
    : historyTree.records.get(rootUid)
  if (!rootRecord) return null

  const createOutputNode = (uid, record) => {
    const props = cloneJsonValueIterative(record.props)
    if (!props || typeof props !== 'object') return null
    const historicalRecord = historyTree.records.get(uid)
    const historicalData = historicalRecord?.props?.data
    if (remoteChangedUids.has(uid) && props.data && typeof props.data === 'object') {
      delete props.data.isActive
      if (historicalData && hasOwn(historicalData, 'isActive')) {
        props.data.isActive = historicalData.isActive
      }
    }
    if (
      remoteChangedUids.has(uid)
      && historicalRecord
      && hasOwn(historicalRecord.props, 'smmVersion')
    ) props.smmVersion = historicalRecord.props.smmVersion
    props.children = []
    return props
  }

  const root = createOutputNode(rootUid, rootRecord)
  if (!root) return null
  const stack = [{ uid: rootUid, output: root, record: rootRecord }]
  const visited = new Set([rootUid])
  while (stack.length) {
    const frame = stack.pop()
    for (let index = frame.record.childUids.length - 1; index >= 0; index -= 1) {
      const childUid = frame.record.childUids[index]
      if (visited.has(childUid)) return null
      const childRecord = remoteChangedUids.has(childUid)
        ? remoteTree.records.get(childUid)
        : historyTree.records.get(childUid)
      if (!childRecord) return null
      const child = createOutputNode(childUid, childRecord)
      if (!child) return null
      frame.output.children.unshift(child)
      visited.add(childUid)
      stack.push({ uid: childUid, output: child, record: childRecord })
    }
  }
  return root
}

/**
 * 把远端的非重叠修改重放到每一份本地撤销快照中。
 *
 * 任一历史快照与远端修改触及相同节点时返回 null，由调用方清空历史。
 * 这是保守边界：不会为了保留 Ctrl+Z 而允许旧快照覆盖协作者内容。
 */
export function rebaseMindmapHistory({
  history,
  activeHistoryIndex,
  currentTree,
  remoteTree,
  maxHistoryCount,
  maxHistoryMemoryBytes,
}) {
  try {
    const current = flattenHistoryTree(currentTree)
    const remote = flattenHistoryTree(remoteTree)
    if (!current || !remote) return null

    const normalizedHistory = Array.isArray(history) ? [...history] : []
    const normalizedIndex = normalizedHistory.length
      ? Math.min(Math.max(0, Number(activeHistoryIndex) || 0), normalizedHistory.length - 1)
      : -1
    let activeHistory = normalizedIndex >= 0
      ? normalizedHistory.slice(0, normalizedIndex + 1)
      : []
    const currentSerialized = stringifyJsonValueIterative(currentTree)
    if (activeHistory.at(-1) !== currentSerialized) activeHistory.push(currentSerialized)
    trimHistoryEntries(activeHistory, maxHistoryCount, maxHistoryMemoryBytes)
    if (
      activeHistory.length > MAX_REBASE_HISTORY_ENTRIES
      || activeHistory.reduce((total, entry) => total + String(entry).length * 2, 0)
        > MAX_REBASE_HISTORY_BYTES
    ) return null

    const parsedHistory = activeHistory.map(entry => flattenHistoryTree(JSON.parse(entry)))
    if (parsedHistory.some(item => !item)) return null
    const remoteChangedUids = collectChangedUids(current, remote)
    const localTouchedUids = new Set()
    for (const historyTree of parsedHistory) {
      for (const uid of collectChangedUids(historyTree, current)) localTouchedUids.add(uid)
    }
    for (const uid of remoteChangedUids) {
      if (localTouchedUids.has(uid)) return null
    }

    const rebasedHistory = parsedHistory.map(historyTree => {
      const tree = buildRebasedTree(historyTree, remote, remoteChangedUids)
      if (!tree) throw new Error('invalid rebased history tree')
      return stringifyJsonValueIterative(tree)
    })
    return {
      history: rebasedHistory,
      activeHistoryIndex: Math.max(0, rebasedHistory.length - 1),
    }
  } catch {
    return null
  }
}
