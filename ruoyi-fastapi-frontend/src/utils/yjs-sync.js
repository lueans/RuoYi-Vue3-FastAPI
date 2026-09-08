/**
 * Yjs 脑图同步管理器
 *
 * 数据模型（细粒度，非整体替换）：
 *   Y.Doc
 *   ├── Y.Map('meta')    → { layout: string, theme: object, documentData: object }
 *   ├── Y.Map('tagDefinitions') → { [tagId]: 当前可渲染定义（不写入节点） }
 *   ├── Y.Map('nodes')   → { [uid]: Y.Map({ data: Y.Map, children: Y.Array<string>, parentUid: string }) }
 *   ├── legacy Y.Map('relations' / 'summaries' / 'groups' / 'assets')
 *   └── crossNode*V2 maps → 跨节点记录的 presence / field / member CRDT
 *
 * 桥接 simple-mind-map 的 data_change_detail 事件和 Yjs 操作。
 */
import * as Y from 'yjs'
import { ref } from 'vue'
import { isSameObject } from '../libs/simple-mind-map/src/utils/deepEqual.js'
import {
  cloneJsonValueIterative,
  stringifyJsonValueIterative,
} from '../libs/simple-mind-map/src/utils/jsonClone.js'
import { applyAuthoritativeMindmapDocument } from './mindmap-document-apply.js'
import { MindmapWsClient } from './ws-client.js'
import {
  applyCrossNodeState,
  buildCrossNodeStateDelta,
  CROSS_NODE_DATA_KEYS,
  detailListTouchesCrossNodeState,
  extractCrossNodeState,
  mergeJsonValueDelta,
  stripCrossNodeData,
} from './yjs-cross-node-state.js'
import {
  applyCrossNodeRecordDeltaV2,
  CROSS_NODE_EPOCHS_MAP,
  CROSS_NODE_FIELD_TOMBSTONES_MAP,
  CROSS_NODE_FIELDS_MAP,
  CROSS_NODE_MEMBER_TOMBSTONES_MAP,
  CROSS_NODE_MEMBERS_MAP,
  CROSS_NODE_SCHEMA_VERSION,
  CROSS_NODE_TOMBSTONES_MAP,
  hasCrossNodeRecordStateV2,
  readCrossNodeRecordStateV2,
  replaceCrossNodeRecordStateV2,
} from './yjs-cross-node-record-store.js'
import {
  applyLocalActiveNodeState,
  deleteYjsSubtree,
  deriveNormalizedYjsTopology,
  flattenMindmapTree,
  normalizeNodeDataForYjs,
  replaceYArrayValues,
  replaceYMapEntries,
  setYMapValueIfChanged,
  synchronizeYjsParentUids,
} from './yjs-tree-state.js'

const MAX_AWARENESS_NODE_COUNT = 100
const MAX_AWARENESS_NODE_UID_LENGTH = 64
const MAX_AWARENESS_SESSION_ID_LENGTH = 128
const AWARENESS_REFRESH_INTERVAL_MS = 15 * 1000
const AWARENESS_STALE_TIMEOUT_MS = 30 * 1000
const MAX_PERSISTED_STATE_SOURCE_COUNT = 32
const MAX_PERSISTED_STATE_SOURCE_ID_LENGTH = 128
const MAX_PERSISTED_STATE_BYTES = 15 * 1024 * 1024
const MAX_PERSISTED_STATE_ENCODED_LENGTH = Math.ceil(MAX_PERSISTED_STATE_BYTES / 3) * 4
const MAX_RUNTIME_UPDATE_BYTES = 5 * 1024 * 1024
const MAX_STRUCTURED_PATCH_NODE_COUNT = 20000
const MAX_STRUCTURED_PATCH_CHILD_COUNT = 50000
const MAX_STRUCTURED_PATCH_UID_LENGTH = 64
const MAX_STRUCTURED_PATCH_BYTES = 2 * 1024 * 1024
const MAX_STRUCTURED_PATCH_JSON_DEPTH = 64
const LOCAL_NODE_DETAIL_ORIGIN = 'local-node-detail'
const CONDITIONAL_NODE_PATCH_CAPABILITY = 'conditional-node-patch-v1'
const YJS_CHECKPOINT_CAPABILITY = 'yjs-checkpoint-v1'
const YJS_MUTATION_SEQUENCE_CAPABILITY = 'yjs-mutation-sequence-v1'
const YJS_LINEAGE_CAPABILITY = 'yjs-lineage-v1'
const YJS_SOURCE_CAS_CAPABILITY = 'yjs-source-cas-v1'
const NODE_EDIT_LEASE_CAPABILITY = 'node-edit-lease-v1'
const NODE_EDIT_LEASE_REQUEST_TIMEOUT_MS = 5000
const NODE_EDIT_LEASE_REFRESH_INTERVAL_MS = 10 * 1000
const NODE_EDIT_LEASE_FAILURE_REASONS = new Set([
  'occupied',
  'connecting',
  'unavailable',
  'readonly',
])
const MAX_YJS_LINEAGE_ID_LENGTH = 128
const CHECKPOINT_INTERVAL_MS = 5000
const MAX_CONFIRMED_MUTATION_IDS = 100
const MAX_YJS_UPDATES_PER_MUTATION = 10000
const CONFIRMED_MUTATION_DELIVERY_TIMEOUT_MS = 1500
const UNCONFIRMED_MUTATION_TIMEOUT_MS = 30 * 1000
const DOCUMENT_PREPARE_RETRY_DELAYS = [1000, 3000, 10000, 30000]
const DOCUMENT_PREPARE_ERROR = '协作内容渲染能力加载失败，正在重试'
const DOCUMENT_PREPARE_EXHAUSTED_ERROR = '协作内容渲染能力加载失败，请检查网络后刷新页面'

function deletedTopLevelYMapKeys(update, mapName) {
  const deletedKeys = new Set()
  let decoded
  try {
    decoded = Y.decodeUpdate(update)
  } catch {
    return deletedKeys
  }
  const deleteSets = decoded?.ds?.clients
  const isDeletedStruct = (struct) => {
    const ranges = deleteSets?.get?.(struct?.id?.client) || []
    const start = Number(struct?.id?.clock)
    const length = Number(struct?.length)
    if (!Number.isInteger(start) || !Number.isInteger(length) || length <= 0) return false
    const end = start + length
    return ranges.some(range => (
      range.clock <= start && range.clock + range.len >= end
    ))
  }
  for (const struct of decoded?.structs || []) {
    if (struct?.parent !== mapName || typeof struct.parentSub !== 'string') continue
    // 完整状态会携带已删除顶层 Map 项的 DeleteSet；启用 GC 后内容还会
    // 折叠成 ContentDeleted。两种形式都能证明该 UID 曾存在于同一 Y.Doc，
    // 可兼容升级前没有 nodeLedger 的合法删除，而不是把缺失节点当作损坏。
    if (
      struct.content?.constructor?.name === 'ContentDeleted'
      || isDeletedStruct(struct)
    ) deletedKeys.add(struct.parentSub)
  }
  return deletedKeys
}

function normalizeReadonlyFlag(value) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value !== 'string') return false
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase())
}

function getDetailNodeData(node) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return null
  const data = (
    Array.isArray(node.children)
    && node.data
    && typeof node.data === 'object'
    && !Array.isArray(node.data)
  ) ? node.data : node
  return stripCrossNodeData(normalizeNodeDataForYjs(data))
}

function captureRuntimeCrossNodeState(document) {
  const root = document?.root || document
  if (!root || typeof root !== 'object') return null
  try {
    return extractCrossNodeState(root)
  } catch {
    // Invalid third-party plugin data must not turn an ordinary local edit into
    // a destructive full-state inference. The next authoritative rebuild can
    // re-establish the shadow once the document is serializable again.
    return null
  }
}

function captureRuntimeNodeState(document) {
  const root = document?.root || document
  if (!root || typeof root !== 'object') return null
  try {
    const flat = flattenMindmapTree(root)
    return Object.fromEntries(Object.entries(flat).map(([uid, node]) => [
      uid,
      {
        data: stripCrossNodeData(normalizeNodeDataForYjs(node.data || {})),
        children: [...(node.children || [])],
      },
    ]))
  } catch {
    return null
  }
}

function collectRuntimeSubtreeNodeUids(root, target = new Set()) {
  const pending = [root]
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    const uid = node.data?.uid || node.uid
    if (uid !== undefined && uid !== null && String(uid)) target.add(String(uid))
    for (const child of (Array.isArray(node.children) ? node.children : [])) {
      pending.push(child)
    }
  }
  return target
}

/** Advance the rendered-node shadow from command details without cloning the whole tree. */
function advanceRuntimeNodeState(runtimeState, detailList = []) {
  if (!runtimeState || typeof runtimeState !== 'object') return null
  const pendingState = new Map()
  const deletedUids = new Set()
  const readPendingNode = uid => (
    pendingState.has(uid)
      ? pendingState.get(uid)
      : (deletedUids.has(uid) ? null : runtimeState[uid])
  )
  try {
    for (const detail of detailList) {
      if (detail?.action === 'delete') {
        for (const uid of collectRuntimeSubtreeNodeUids(detail.oldData || detail.data)) {
          deletedUids.add(uid)
          pendingState.delete(uid)
        }
        continue
      }
      if (detail?.action === 'create') {
        const created = captureRuntimeNodeState(detail.data)
        if (!created) return null
        for (const [uid, node] of Object.entries(created)) {
          deletedUids.delete(uid)
          pendingState.set(uid, node)
        }
        continue
      }
      const uidValue = detail?.data?.data?.uid
        || detail?.data?.uid
        || detail?.oldData?.data?.uid
        || detail?.oldData?.uid
      if (!uidValue) continue
      const uid = String(uidValue)
      const previous = readPendingNode(uid)
      const data = getDetailNodeData(detail.data)
      const children = getDetailChildUids(detail.data)
      if (!data && !children) continue
      const clonedData = data
        ? cloneJsonValueIterative(data)
        : cloneJsonValueIterative(previous?.data || {})
      if (!clonedData || typeof clonedData !== 'object') return null
      deletedUids.delete(uid)
      pendingState.set(uid, {
        data: clonedData,
        children: children ? [...children] : [...(previous?.children || [])],
      })
    }
  } catch {
    return null
  }
  for (const uid of deletedUids) delete runtimeState[uid]
  for (const [uid, node] of pendingState) {
    Object.defineProperty(runtimeState, uid, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: node,
    })
  }
  return runtimeState
}

function applyLocalNodeDataDelta(yData, detail, runtimePreviousNode = null) {
  const nextData = getDetailNodeData(detail?.data)
  if (!nextData) return false
  const previousData = getDetailNodeData(detail?.oldData)
    || runtimePreviousNode?.data
  // Without an observed runtime before-state, a full snapshot cannot prove
  // which fields changed locally. Replacing the current Y.Map here would
  // overwrite remote fields that have arrived but are not rendered yet.
  if (!previousData) return false

  let changed = false
  const keys = new Set([
    ...Object.keys(previousData),
    ...Object.keys(nextData),
  ])
  for (const key of keys) {
    const previousHasKey = Object.prototype.hasOwnProperty.call(previousData, key)
    const nextHasKey = Object.prototype.hasOwnProperty.call(nextData, key)
    if (
      previousHasKey === nextHasKey
      && (!previousHasKey || isSameObject(previousData[key], nextData[key]))
    ) continue
    if (nextHasKey) {
      const mergedValue = mergeJsonValueDelta(
        yData.get(key),
        previousHasKey ? previousData[key] : undefined,
        nextData[key],
      )
      changed = setYMapValueIfChanged(yData, key, mergedValue) || changed
    } else if (yData.has(key)) {
      yData.delete(key)
      changed = true
    }
  }
  return changed
}

function getDetailChildUids(node) {
  if (!Array.isArray(node?.children)) return null
  return node.children.map(child => child?.data?.uid).filter(Boolean)
}

function applyLocalNodeChildrenDelta(yChildren, detail, runtimePreviousNode = null) {
  const nextChildren = getDetailChildUids(detail?.data)
  if (!nextChildren) return false
  const previousChildren = getDetailChildUids(detail?.oldData)
    || runtimePreviousNode?.children
  // A text/style command carries the whole stale subtree snapshot. If its
  // child list did not change locally, leave the already-merged Y.Array alone.
  if (previousChildren && isSameObject(previousChildren, nextChildren)) return false
  if (!previousChildren) return false

  const currentChildren = yChildren.toArray()
  const previousSet = new Set(previousChildren)
  const nextSet = new Set(nextChildren)
  const removedLocally = new Set(
    previousChildren.filter(uid => !nextSet.has(uid)),
  )
  const currentSet = new Set()
  const retainedCurrentChildren = currentChildren.filter(uid => {
    if (removedLocally.has(uid) || currentSet.has(uid)) return false
    currentSet.add(uid)
    return true
  })

  // Preserve children that arrived remotely after the stale runtime snapshot.
  // Insert only genuinely local additions, using the nearest surviving local
  // neighbor as an anchor instead of replacing the complete parent list.
  const nextExistingChild = new Array(nextChildren.length)
  let followingAnchor = null
  for (let index = nextChildren.length - 1; index >= 0; index -= 1) {
    nextExistingChild[index] = followingAnchor
    if (currentSet.has(nextChildren[index])) followingAnchor = nextChildren[index]
  }
  const additionsBefore = new Map()
  const additionsAfter = new Map()
  const trailingAdditions = []
  const queuedAdditions = new Set()
  let precedingAnchor = null
  for (let index = 0; index < nextChildren.length; index += 1) {
    const uid = nextChildren[index]
    if (currentSet.has(uid)) {
      precedingAnchor = uid
      continue
    }
    if (previousSet.has(uid) || queuedAdditions.has(uid)) continue
    queuedAdditions.add(uid)
    if (precedingAnchor) {
      const additions = additionsAfter.get(precedingAnchor) || []
      additions.push(uid)
      additionsAfter.set(precedingAnchor, additions)
    } else if (nextExistingChild[index]) {
      const additions = additionsBefore.get(nextExistingChild[index]) || []
      additions.push(uid)
      additionsBefore.set(nextExistingChild[index], additions)
    } else {
      trailingAdditions.push(uid)
    }
  }
  const mergedChildren = []
  for (const uid of retainedCurrentChildren) {
    mergedChildren.push(...(additionsBefore.get(uid) || []))
    mergedChildren.push(uid)
    mergedChildren.push(...(additionsAfter.get(uid) || []))
  }
  mergedChildren.push(...trailingAdditions)

  // A real local reorder should affect the locally known retained children,
  // while remotely-added entries keep their occupied slots and are never lost.
  const previousRetained = previousChildren.filter(uid => nextSet.has(uid))
  const nextRetained = nextChildren.filter(uid => previousSet.has(uid))
  if (!isSameObject(previousRetained, nextRetained)) {
    const retainedSet = new Set(nextRetained)
    const retainedSlots = []
    for (let index = 0; index < mergedChildren.length; index += 1) {
      if (retainedSet.has(mergedChildren[index])) retainedSlots.push(index)
    }
    const mergedSet = new Set(mergedChildren)
    const retainedOrder = nextRetained.filter(uid => mergedSet.has(uid))
    retainedSlots.forEach((slot, index) => {
      mergedChildren[slot] = retainedOrder[index]
    })
  }

  return replaceYArrayValues(yChildren, mergedChildren)
}

/**
 * 分块 base64 编码，避免大数组调用栈溢出
 */
function uint8ArrayToBase64(bytes) {
  let binary = ''
  const chunkSize = 8192
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length))
    binary += String.fromCharCode.apply(null, chunk)
  }
  return btoa(binary)
}

/**
 * base64 解码为 Uint8Array
 */
function base64ToUint8Array(base64Str) {
  const binary = atob(base64Str)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

function uint8ArraysEqual(left, right) {
  if (left === right) return true
  if (!left || !right || left.length !== right.length) return false
  for (let index = 0; index < left.length; index++) {
    if (left[index] !== right[index]) return false
  }
  return true
}

function normalizeYjsLineageId(value) {
  if (typeof value !== 'string') return ''
  const normalized = value.trim()
  return normalized
    && new TextEncoder().encode(normalized).length <= MAX_YJS_LINEAGE_ID_LENGTH
    ? normalized
    : ''
}

function createYjsLineageId(clientId) {
  const uuid = globalThis.crypto?.randomUUID?.()
  if (uuid) return uuid
  const safeClientId = Number.isInteger(clientId) && clientId >= 0
    ? clientId.toString(36)
    : 'client'
  return `${safeClientId}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
    .slice(0, MAX_YJS_LINEAGE_ID_LENGTH)
}

function getYjsTypeIdentity(type) {
  const id = type?._item?.id
  if (!Number.isInteger(id?.client) || !Number.isInteger(id?.clock)) return ''
  return `${id.client}:${id.clock}`
}

function getSerializedJsonDepth(serialized) {
  let depth = 0
  let maxDepth = 0
  let inString = false
  let escaped = false
  for (const character of serialized) {
    if (inString) {
      if (escaped) escaped = false
      else if (character === '\\') escaped = true
      else if (character === '"') inString = false
      continue
    }
    if (character === '"') {
      inString = true
    } else if (character === '{' || character === '[') {
      depth += 1
      maxDepth = Math.max(maxDepth, depth)
    } else if (character === '}' || character === ']') {
      depth -= 1
    }
  }
  return maxDepth
}

export function isStructuredPatchTransportSafe(patch) {
  try {
    const serialized = stringifyJsonValueIterative(patch)
    if (
      typeof serialized !== 'string'
      || serialized.length > MAX_STRUCTURED_PATCH_BYTES
      || getSerializedJsonDepth(serialized) > MAX_STRUCTURED_PATCH_JSON_DEPTH
    ) return false
    return new TextEncoder().encode(serialized).byteLength <= MAX_STRUCTURED_PATCH_BYTES
  } catch {
    return false
  }
}

/**
 * Runtime update 帧必须满足服务端 WebSocket 协议的解码后大小上限。
 * MindmapWsClient#send 返回 true 只表示消息进入了浏览器 socket，并不能
 * 证明服务端会接受该帧，因此必须在分配 mutation 序号前完成同口径校验。
 */
export function isRuntimeYjsUpdateTransportSafe(update) {
  return update instanceof Uint8Array
    && update.byteLength > 0
    && update.byteLength <= MAX_RUNTIME_UPDATE_BYTES
}

function normalizePersistedStateSources(values, expectedCount) {
  if (
    !Array.isArray(values)
    || !Number.isInteger(expectedCount)
    || values.length !== expectedCount
    || values.length > MAX_PERSISTED_STATE_SOURCE_COUNT
  ) return []
  const result = []
  const seen = new Set()
  for (const value of values) {
    if (typeof value !== 'string') return []
    const sourceId = value.trim()
    if (
      !sourceId
      || sourceId.length > MAX_PERSISTED_STATE_SOURCE_ID_LENGTH
      || seen.has(sourceId)
    ) return []
    seen.add(sourceId)
    result.push(sourceId)
  }
  return result
}

function normalizePersistedStateDigests(values, expectedCount) {
  if (!Array.isArray(values) || values.length !== expectedCount) return []
  const result = []
  for (const value of values) {
    if (
      typeof value !== 'string'
      || !/^[0-9a-f]{64}$/.test(value)
    ) return []
    result.push(value)
  }
  return result
}

function stagePersistedYjsStates(encodedStates, stateSources, stateDigests) {
  const states = Array.isArray(encodedStates) ? encodedStates : []
  if (states.length > MAX_PERSISTED_STATE_SOURCE_COUNT) {
    return {
      mergedUpdate: null,
      acceptedUpdates: [],
      acceptedSourceIds: [],
      sourceDigests: {},
      invalidSourceIds: [],
      invalidStateCount: states.length,
    }
  }
  const normalizedSources = normalizePersistedStateSources(stateSources, states.length)
  const normalizedDigests = normalizePersistedStateDigests(stateDigests, states.length)
  const sourcesAligned = normalizedSources.length === states.length
  const digestsAligned = normalizedDigests.length === states.length
  const sourceDigests = sourcesAligned && digestsAligned
    ? Object.fromEntries(normalizedSources.map((sourceId, index) => [
      sourceId,
      normalizedDigests[index],
    ]))
    : {}
  const acceptedUpdates = []
  const acceptedSourceIds = []
  const invalidSourceIds = []
  let invalidStateCount = 0

  states.forEach((encodedState, index) => {
    let probeDoc = null
    try {
      if (
        typeof encodedState !== 'string'
        || !encodedState
        || encodedState.length > MAX_PERSISTED_STATE_ENCODED_LENGTH
      ) throw new Error('invalid state size')
      const update = base64ToUint8Array(encodedState)
      probeDoc = new Y.Doc()
      Y.applyUpdate(probeDoc, update)
      acceptedUpdates.push(update)
      if (sourcesAligned) acceptedSourceIds.push(normalizedSources[index])
    } catch {
      invalidStateCount += 1
      if (sourcesAligned) invalidSourceIds.push(normalizedSources[index])
    } finally {
      probeDoc?.destroy()
    }
  })

  const stagedDoc = new Y.Doc()
  try {
    for (const update of acceptedUpdates) Y.applyUpdate(stagedDoc, update)
    return {
      mergedUpdate: acceptedUpdates.length ? Y.encodeStateAsUpdate(stagedDoc) : null,
      acceptedUpdates,
      acceptedSourceIds,
      sourceDigests,
      invalidSourceIds,
      invalidStateCount,
    }
  } catch {
    return {
      mergedUpdate: null,
      acceptedUpdates: [],
      acceptedSourceIds: [],
      sourceDigests,
      invalidSourceIds: sourcesAligned ? normalizedSources : [],
      invalidStateCount: states.length,
    }
  } finally {
    stagedDoc.destroy()
  }
}

function validateRuntimeYjsUpdate(encodedUpdate, maxBytes) {
  const maxEncodedLength = Math.ceil(maxBytes / 3) * 4
  if (
    typeof encodedUpdate !== 'string'
    || !encodedUpdate
    || encodedUpdate.length > maxEncodedLength
  ) throw new Error('invalid runtime update size')
  const update = base64ToUint8Array(encodedUpdate)
  if (update.byteLength > maxBytes) throw new Error('invalid runtime update size')
  const probeDoc = new Y.Doc()
  try {
    Y.applyUpdate(probeDoc, update)
    return update
  } finally {
    probeDoc.destroy()
  }
}

export class YjsMindmapSync {
  constructor(mindmapId, mindMapInstance, contentRevision = 1, options = {}) {
    this.mindmapId = mindmapId
    this.mindMap = mindMapInstance
    this.doc = new Y.Doc()
    this.collaborators = ref([])
    this.isSynced = ref(false)
    this.connectionState = ref('connecting')
    this.syncError = ref('')
    this.readonly = normalizeReadonlyFlag(options.readonly)
    this.options = {
      ...options,
      readonly: this.readonly,
    }
    this._applyingRemote = false
    this._mutatingMindmapFromRemote = false
    this._preparingRemote = false
    this._paused = false
    this._destroyed = false
    this._receivedServerState = false
    this._localYjsChange = false
    this._pendingStructuredPatch = null
    this._pendingPreSyncChanges = []
    this._checkpointTimer = null
    this._checkpointDirty = false
    this._hasUncorrelatedLocalState = false
    this._hasUnconfirmedRemoteState = false
    this._hasLegacyUnconfirmedRemoteState = false
    this._unconfirmedRemoteMutationIds = new Set()
    this._confirmedRemoteMutationIds = new Map()
    this._localMutationIds = new Set()
    this._pendingLocalMutationIds = new Set()
    this._outgoingMutationUpdateCounts = new Map()
    this._outgoingMutationBaseRevisions = new Map()
    this._unreliableLocalMutationIds = new Set()
    this._sealedLocalMutationIds = new Set()
    this._receivedRemoteMutationIds = new Set()
    this._pendingRemoteMutationApplyIds = new Set()
    this._appliedRemoteMutationIds = new Set()
    this._pendingRemoteMutationApplySequences = new Map()
    this._appliedRemoteMutationSequences = new Map()
    this._remoteMutationSequenceFingerprints = new Map()
    this._confirmedMutationDeliveryTimers = new Map()
    this._unconfirmedMutationTimers = new Map()
    this._legacyUnconfirmedMutationTimer = null
    this._outgoingClientMutationId = null
    this._sendingAuthoritativeSeed = false
    this._authoritativeSeedSendResult = null
    this._pendingCheckpointReplacesSources = []
    this._pendingCheckpointInvalidSources = []
    this._pendingCheckpointSourceDigests = {}
    this._authoritativeRevisionPending = null
    this._pendingRemoteApply = false
    this._pendingRemoteApplyMeta = false
    this._remoteApplyFallbackTimer = null
    this._remoteApplyReleaseTimer = null
    this._remotePrepareRetryTimer = null
    this._remotePrepareRetryAttempt = 0
    this._documentPrepareFailed = false
    this._remoteRenderEndHandler = null
    this._syncInitTimer = null
    this._hadLocalDataBeforeSync = false
    this._localActiveNodeUids = []
    this._localEditingNodeUid = ''
    this._remoteAwareness = new Map()
    this._awarenessEventsBound = false
    this._awarenessRefreshTimer = null
    this._awarenessExpiryTimer = null
    this._nodeEditLeaseUid = ''
    this._nodeEditLeaseRequestSequence = 0
    this._nodeEditLeaseAcquireGeneration = 0
    this._nodeEditLeaseAcquireChain = Promise.resolve()
    this._pendingNodeEditLeaseRequests = new Map()
    this._nodeEditLeaseRefreshTimer = null
    this._nodeEditLeaseFailureReason = ''
    this.sessionId = null
    this.contentRevision = contentRevision
    this.confirmedMutationDeliveryTimeoutMs = (
      Number.isInteger(options.confirmedMutationDeliveryTimeoutMs)
      && options.confirmedMutationDeliveryTimeoutMs > 0
    )
      ? options.confirmedMutationDeliveryTimeoutMs
      : CONFIRMED_MUTATION_DELIVERY_TIMEOUT_MS
    this.unconfirmedMutationTimeoutMs = (
      Number.isInteger(options.unconfirmedMutationTimeoutMs)
      && options.unconfirmedMutationTimeoutMs > 0
    )
      ? options.unconfirmedMutationTimeoutMs
      : UNCONFIRMED_MUTATION_TIMEOUT_MS
    this.nodeEditLeaseRequestTimeoutMs = (
      Number.isInteger(options.nodeEditLeaseRequestTimeoutMs)
      && options.nodeEditLeaseRequestTimeoutMs > 0
    )
      ? options.nodeEditLeaseRequestTimeoutMs
      : NODE_EDIT_LEASE_REQUEST_TIMEOUT_MS
    this.nodeEditLeaseRefreshIntervalMs = (
      Number.isInteger(options.nodeEditLeaseRefreshIntervalMs)
      && options.nodeEditLeaseRefreshIntervalMs > 0
    )
      ? options.nodeEditLeaseRefreshIntervalMs
      : NODE_EDIT_LEASE_REFRESH_INTERVAL_MS
    this.currentUser = this._normalizeUser(options.user)
    this.serverCapabilities = new Set()
    this.tagDefinitions = new Map()
    const initialRuntimeDocument = this._captureAuthoritativeBaseline()
    // This is the state actually rendered on the canvas, not the newer Y.Map
    // state that may already contain a remote update waiting for UI apply.
    // Legacy detail emitters without oldData need this three-way merge base.
    this._runtimeCrossNodeState = captureRuntimeCrossNodeState(
      initialRuntimeDocument,
    )
    this._runtimeNodeState = captureRuntimeNodeState(
      initialRuntimeDocument,
    )

    this.yMeta = this.doc.getMap('meta')
    this.yTagDefinitions = this.doc.getMap('tagDefinitions')
    this.yNodes = this.doc.getMap('nodes')
    // 节点账本只增不减，用来区分“节点曾存在后被协作者合法删除”和
    // “残缺状态从未包含 HTTP 权威基线中的节点”。直接比较 nodes 会把
    // 自动保存前的实时删除误判为缓存损坏。
    this.yNodeLedger = this.doc.getMap('nodeLedger')
    this.yRelations = this.doc.getMap('relations')
    this.ySummaries = this.doc.getMap('summaries')
    this.yGroups = this.doc.getMap('groups')
    this.yAssets = this.doc.getMap('assets')
    this.yCrossNodeEpochs = this.doc.getMap(CROSS_NODE_EPOCHS_MAP)
    this.yCrossNodeTombstones = this.doc.getMap(CROSS_NODE_TOMBSTONES_MAP)
    this.yCrossNodeFields = this.doc.getMap(CROSS_NODE_FIELDS_MAP)
    this.yCrossNodeFieldTombstones = this.doc.getMap(CROSS_NODE_FIELD_TOMBSTONES_MAP)
    this.yCrossNodeGroupMembers = this.doc.getMap(CROSS_NODE_MEMBERS_MAP)
    this.yCrossNodeGroupMemberTombstones = this.doc.getMap(
      CROSS_NODE_MEMBER_TOMBSTONES_MAP,
    )
    this.wsClient = new MindmapWsClient(mindmapId, {
      onAuthenticated: (user, capabilities, authData) => {
        const authenticatedUser = this._normalizeUser(user)
        this.currentUser = {
          ...this.currentUser,
          ...authenticatedUser,
          avatar: this.currentUser?.avatar || authenticatedUser?.avatar || '',
        }
        const previousReadonly = this.readonly
        if (authData && typeof authData.readonly === 'boolean') {
          this.readonly = authData.readonly
          this.options = {
            ...this.options,
            readonly: this.readonly,
          }
        }
        if (this.readonly !== previousReadonly) {
          this.options.onReadonlyChanged?.(this.readonly, authData)
        }
        // 上层可能在服务端把可写会话降级为只读时立即终止并销毁当前实例。
        // 不能在销毁后继续握手或发送 awareness。
        if (this._destroyed) return
        this.sessionId = this._normalizeAwarenessSessionId(authData?.sessionId)
        this.serverCapabilities = new Set(
          Array.isArray(capabilities)
            ? capabilities.filter(capability => typeof capability === 'string')
            : []
        )
        this._beginSyncHandshake()
        this._sendAwareness(this._localActiveNodeUids)
        this._scheduleAwarenessRefresh()
      },
      onClose: () => {
        if (!this._destroyed) this._markPendingLocalMutationsUnreliable()
        clearTimeout(this._syncInitTimer)
        this._clearAwarenessRefreshTimer()
        this._handleNodeEditLeaseDisconnect()
        this.sessionId = null
        this.isSynced.value = false
        this._clearRemotePresence()
      },
      onConnectionState: (state, detail) => {
        this.connectionState.value = state
        if (detail) this.syncError.value = detail
      },
      onAuthError: (message) => {
        this.isSynced.value = false
        this.syncError.value = message || '协作认证失败'
      },
      onHeartbeat: (data) => this._handleRevisionHeartbeat(data),
      sync_init: (data) => this._handleSyncInit(data),
      seed_pending: (data) => this._handleSeedPending(data),
      seed_request: (data) => this._handleSeedRequest(data),
      seed_granted: (data) => this._handleSeedGranted(data),
      update: (data) => this._handleUpdate(data),
      stale_state: (data) => this._handleStaleState(data),
      content_revision_changed: (data) => this._handleContentRevisionChanged(data),
      document_reset: (data) => this._handleDocumentReset(data),
      document_deleted: (data) => this._handleDocumentDeleted(data),
      document_archived: (data) => this._handleDocumentArchived(data),
      access_revoked: (data) => this._handleAccessRevoked(data),
      session_ended: (data) => this._handleSessionEnded(data),
      user_joined: (data) => this._handleUserJoined(data),
      user_left: (data) => this._handleUserLeft(data),
      room_users: (data) => this._handleRoomUsers(data),
      awareness: (data) => this._handleAwareness(data),
      node_edit_lease_result: (data) => this._handleNodeEditLeaseResult(data),
      protocol_error: (data) => {
        this.syncError.value = data.message || '协作消息格式错误'
        // protocol_error 没有可靠携带所拒绝帧的 mutationId。只要本地仍有
        // 待确认批次，就不能继续向 HTTP 声明其全部序号已被实时通道接收；
        // 保守降级为 reload，避免观察端一直等到缺帧超时才回源。
        this._markPendingLocalMutationsUnreliable()
        this.options.onProtocolError?.(data)
      },
      tag_definition_changed: (data) => this._handleTagDefinitionChanged(data),
      tag_replaced: (data) => this._handleTagReplaced(data),
      tag_unbound: (data) => this._handleTagUnbound(data),
      comment_changed: (data) => this.options.onCommentChanged?.(data),
    }, {
      readonly: this.readonly,
    })
  }

  start() {
    this._bindAwarenessEvents()
    // 监听 Yjs 文档变更 → 转发到 WebSocket
    this.doc.on('update', (update, origin) => {
      if (
        !this._destroyed
        && !this.readonly
        && origin !== 'remote'
        && origin !== 'authoritative-baseline'
        && !this._paused
        && this._authoritativeRevisionPending === null
      ) {
        const supportsConditionalPatch = this._supportsConditionalNodePatchProtocol()
        const patch = (
          origin === LOCAL_NODE_DETAIL_ORIGIN
          && supportsConditionalPatch
        )
          ? this._pendingStructuredPatch
          : null
        const patchPayload = patch || (supportsConditionalPatch ? {
          schemaVersion: 1,
          nodes: [],
          deletedNodeUids: [],
          applyMeta: origin === 'local-meta',
        } : null)
        const clientMutationId = this._normalizeClientMutationId(
          this._outgoingClientMutationId,
        )
        if (
          !clientMutationId
          && (origin === LOCAL_NODE_DETAIL_ORIGIN || origin === 'local-meta')
        ) {
          // 业务正文事务必须和随后 HTTP 保存使用同一个 mutationId。底层
          // 仍做失联兜底：允许实时展示，但在权威回源前绝不生成完整状态
          // 或检查点，避免未落库修改被伪装成当前 revision 的持久化基线。
          this._hasUncorrelatedLocalState = true
          this._handleStaleState({
            contentRevision: this.contentRevision,
            reason: 'uncorrelated_local_yjs_update',
            message: '检测到未关联保存批次的本地修改，正在从云端重建安全基线',
          })
          return
        }
        let realtimeTransportAllowed = true
        if (clientMutationId && this.options.canSendRealtimeMutation) {
          try {
            realtimeTransportAllowed = (
              this.options.canSendRealtimeMutation(clientMutationId) !== false
            )
          } catch {
            // 上层状态读取失败时关闭快速通道；HTTP 权威保存仍会继续，
            // 不能因一个展示优化回调异常而丢弃用户操作。
            realtimeTransportAllowed = false
          }
        }
        if (clientMutationId && !realtimeTransportAllowed) {
          // 前一 HTTP mutation 尚在途时，下一批更新的 base revision 可能
          // 在任意一帧之间推进。此时发送部分旧 revision 帧只会触发服务端
          // stale 栅栏。保留本地 Y.Doc 与 mutation，跳过快速通道并声明
          // reload；随后的 HTTP 保存会成为这一批的唯一权威提交点。
          this.markLocalMutation(clientMutationId)
          this._rememberBoundedMutationId(
            this._unreliableLocalMutationIds,
            clientMutationId,
          )
          this._scheduleCheckpoint()
          return
        }
        if (
          clientMutationId
          && !isRuntimeYjsUpdateTransportSafe(update)
        ) {
          // 服务端会拒绝超过 MAX_RUNTIME_UPDATE_BYTES 的 update。若仍把
          // WebSocket.send=true 当作可靠送达并声明 sequenced，观察端只能
          // 等缺帧定时器后才发现内容不完整。该批次不分配任何实时序号，
          // 直接由 HTTP 权威保存携带 reload 交付语义，revision 广播到达时
          // 其他标签页会立即回源。
          this.markLocalMutation(clientMutationId)
          this._rememberBoundedMutationId(
            this._unreliableLocalMutationIds,
            clientMutationId,
          )
          this._scheduleCheckpoint()
          this.options.onRealtimeFallback?.({
            reason: 'runtime_update_too_large',
            clientMutationId,
            updateBytes: update.byteLength,
            maxUpdateBytes: MAX_RUNTIME_UPDATE_BYTES,
          })
          return
        }
        const mutationBaseRevision = clientMutationId
          ? this._getOrCreateOutgoingMutationBaseRevision(clientMutationId)
          : this.contentRevision
        const mutationUpdateSeq = clientMutationId
          ? this._nextOutgoingMutationUpdateSequence(clientMutationId)
          : null
        // 冻结 HTTP 批次后，握手队列中迟到的旧操作只能用于补齐本地
        // Y.Doc；不能再以已经封存的 mutationId 发出未计入 count 的帧。
        if (clientMutationId && mutationUpdateSeq === null) {
          this._rememberBoundedMutationId(this._unreliableLocalMutationIds, clientMutationId)
          if (this._authoritativeRevisionPending === null) {
            this._handleStaleState({
              contentRevision: this.contentRevision,
              reason: 'sealed_or_invalid_local_mutation',
              message: '检测到保存批次封存后的迟到修改，正在从云端重建安全基线',
            })
          }
          return
        }
        this.markLocalMutation(clientMutationId)
        const correlation = clientMutationId ? {
          clientMutationId,
          mutationUpdateSeq,
        } : {}
        const seedCorrelation = (
          origin === 'init'
          && this._sendingAuthoritativeSeed
          && !clientMutationId
        ) ? { seedState: true } : {}
        const lineageId = this._getYjsLineageId()
        const lineageCorrelation = lineageId ? { lineageId } : {}
        let sent
        if (origin !== 'init' && this._supportsCheckpointProtocol()) {
          sent = this.wsClient.send({
            type: 'update',
            update: this._encodeUpdate(update),
            ...correlation,
            ...seedCorrelation,
            ...lineageCorrelation,
            ...(patchPayload ? { patch: patchPayload } : {}),
            contentRevision: mutationBaseRevision,
          })
          this._scheduleCheckpoint()
        } else {
          sent = this.wsClient.send({
            type: 'update',
            update: this._encodeUpdate(update),
            ...correlation,
            ...seedCorrelation,
            ...lineageCorrelation,
            state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
            ...(patch ? { patch } : {}),
            contentRevision: mutationBaseRevision,
          })
          // 握手期间的本地编辑会随 HTTP 当前画布一次性初始化 Y.Doc。
          // 这份 full state 只是实时传输，服务端不会在旧 revision 下持久化；
          // 先标记 dirty，待同 mutation 的 HTTP 确认推进 revision 后再检查点。
          if (
            origin === 'init'
            && clientMutationId
            && this._supportsCheckpointProtocol()
          ) this._scheduleCheckpoint()
        }
        if (!sent && clientMutationId) {
          // WebSocket.send=false 表示该序号只在本地生成、并未进入当前连接。
          // 仍保留完整 update count 让服务端确认批次边界，但 HTTP 保存必须
          // 声明 reload，促使观察端在 revision 确认时立即回源，不能等待
          // “缺帧”超时后才发现画布与云端不一致。
          this._rememberBoundedMutationId(
            this._unreliableLocalMutationIds,
            clientMutationId,
          )
        }
        if (
          origin === 'init'
          && this._sendingAuthoritativeSeed
          && !clientMutationId
        ) {
          // Y.Doc 的 update 事件与 transact 同步派发，把首次权威种子的
          // 实际发送结果反馈给握手状态机。仅仅在本地创建了 Y.Doc 不代表
          // 房间已经收到种子，发送失败时绝不能显示为 connected。
          this._authoritativeSeedSendResult = sent === true
        }
      }
    })

    // 监听节点变更 → 同步到脑图实例
    // 仅在远程变更时触发 _applyYjsToMindmap
    // 本地编辑写入 Yjs 时也会触发 observeDeep，需要跳过（_localYjsChange 标志）
    this.yNodes.observeDeep(() => {
      if (!this._destroyed && !this._paused && !this._localYjsChange && this.mindMap) {
        this._requestYjsApply()
      }
    })

    this.yMeta.observe(() => {
      if (!this._destroyed && !this._paused && !this._localYjsChange && this.mindMap) {
        this._requestYjsApply({ applyMeta: true })
      }
    })

    this.yTagDefinitions.observe(event => {
      if (this._destroyed) return
      // WebSocket 批量应用远端 Yjs 更新时会临时设置 _localYjsChange，
      // 以免各 Map 在结构化补丁完成前分别刷新画布；但标签缓存仍须在
      // 事务内精确收敛删除。画布刷新由 _handleUpdate 在批次结束后统一触发。
      const isRemoteTransaction = event.transaction.origin === 'remote'
      if (this._localYjsChange && !isRemoteTransaction) return
      const deletedKeys = []
      event.changes.keys.forEach((change, key) => {
        if (change.action === 'delete') deletedKeys.push(String(key))
      })
      const definitionsChanged = this._syncTagDefinitionsFromYjs(deletedKeys)
      if (definitionsChanged && this.mindMap && !this._localYjsChange) {
        this._requestYjsApply()
      }
    })

    const applyCrossNodeChange = () => {
      if (!this._destroyed && !this._paused && !this._localYjsChange && this.mindMap) {
        this._requestYjsApply()
      }
    }
    this.yRelations.observe(applyCrossNodeChange)
    this.ySummaries.observe(applyCrossNodeChange)
    this.yGroups.observe(applyCrossNodeChange)
    this.yAssets.observe(applyCrossNodeChange)
    this.yCrossNodeEpochs.observe(applyCrossNodeChange)
    this.yCrossNodeTombstones.observe(applyCrossNodeChange)
    this.yCrossNodeFields.observe(applyCrossNodeChange)
    this.yCrossNodeFieldTombstones.observe(applyCrossNodeChange)
    this.yCrossNodeGroupMembers.observe(applyCrossNodeChange)
    this.yCrossNodeGroupMemberTombstones.observe(applyCrossNodeChange)

    this.wsClient.connect()
  }

  retryConnection() {
    if (this._destroyed || this._paused) return false
    const retried = this.wsClient.retryNow('正在手动重新连接实时协作')
    if (!retried) return false
    this.isSynced.value = false
    this.syncError.value = '正在手动重新连接实时协作'
    return true
  }

  destroy({ flushCheckpoint = true } = {}) {
    if (this._destroyed) return
    if (flushCheckpoint) this._flushCheckpoint({ reschedule: false })
    this.releaseNodeEditLease()
    this._clearPendingNodeEditLeaseRequests()
    this._destroyed = true
    clearTimeout(this._checkpointTimer)
    this._checkpointTimer = null
    this._checkpointDirty = false
    clearTimeout(this._syncInitTimer)
    clearTimeout(this._remoteApplyFallbackTimer)
    clearTimeout(this._remoteApplyReleaseTimer)
    clearTimeout(this._remotePrepareRetryTimer)
    this._clearAwarenessRefreshTimer()
    if (this._remoteRenderEndHandler) {
      this.mindMap?.off?.('node_tree_render_end', this._remoteRenderEndHandler)
    }
    this._sendAwareness([], true, '')
    this._unbindAwarenessEvents()
    this._clearRemotePresence()
    this._pendingPreSyncChanges = []
    this._pendingCheckpointReplacesSources = []
    this._pendingCheckpointInvalidSources = []
    this._pendingCheckpointSourceDigests = {}
    this._clearConfirmedMutationDeliveryTimers()
    this._clearUnconfirmedMutationTimers()
    this._clearLegacyUnconfirmedMutationTimer()
    this._confirmedRemoteMutationIds.clear()
    this._localMutationIds.clear()
    this._pendingLocalMutationIds.clear()
    this._outgoingMutationUpdateCounts.clear()
    this._outgoingMutationBaseRevisions.clear()
    this._unreliableLocalMutationIds.clear()
    this._sealedLocalMutationIds.clear()
    this._receivedRemoteMutationIds.clear()
    this._pendingRemoteMutationApplyIds.clear()
    this._appliedRemoteMutationIds.clear()
    this._pendingRemoteMutationApplySequences.clear()
    this._appliedRemoteMutationSequences.clear()
    this._remoteMutationSequenceFingerprints.clear()
    this.wsClient.disconnect()
    this.doc.destroy()
    this.mindMap = null
    this.options = {}
  }

  /** 检查当前是否正在应用远程变更 */
  isApplyingRemote() {
    return this._applyingRemote
  }

  /** 仅在远端文档同步调用正在直接改动画布的同步调用栈内为 true。 */
  isMutatingMindmapFromRemote() {
    return this._mutatingMindmapFromRemote
  }

  /** 检查是否正在等待远端文档所需的异步渲染能力。 */
  isPreparingRemoteDocument() {
    return this._preparingRemote
  }

  /** 检查同步是否已暂停（版本预览时使用） */
  isPaused() {
    return this._paused
  }

  setContentRevision(revision, clientMutationId = null) {
    // contentRevision 是权威内容的单调版本栅栏。HTTP 响应、WebSocket
    // 广播和心跳可能乱序到达，任何旧消息都不能让它倒退。
    if (Number.isInteger(revision) && revision > this.contentRevision) {
      this.contentRevision = revision
    }
    this.confirmLocalMutation(clientMutationId)
    this._discardConfirmedMutationsAtOrBelowCurrentRevision()
    this._flushConfirmedMutationRevisions()
  }

  markLocalMutation(clientMutationId, baseRevision = null) {
    const normalized = this._normalizeClientMutationId(clientMutationId)
    if (!normalized) return false
    this._rememberBoundedMutationId(this._localMutationIds, normalized)
    this._rememberBoundedMutationId(this._pendingLocalMutationIds, normalized)
    if (
      !this._outgoingMutationBaseRevisions.has(normalized)
      && Number.isInteger(baseRevision)
      && baseRevision > 0
    ) this._outgoingMutationBaseRevisions.set(normalized, baseRevision)
    this._clearConfirmedMutationDeliveryTimer(normalized)
    this._clearUnconfirmedMutationTimer(normalized)
    return true
  }

  _markPendingLocalMutationsUnreliable() {
    for (const clientMutationId of this._pendingLocalMutationIds) {
      this._rememberBoundedMutationId(
        this._unreliableLocalMutationIds,
        clientMutationId,
      )
    }
  }

  _getOrCreateOutgoingMutationBaseRevision(clientMutationId) {
    const existing = this._outgoingMutationBaseRevisions.get(clientMutationId)
    if (Number.isInteger(existing) && existing > 0) return existing
    const supplied = Number(this.options.getClientMutationBaseRevision?.(
      clientMutationId,
    ))
    const revision = Number.isInteger(supplied) && supplied > 0
      ? supplied
      : this.contentRevision
    this._outgoingMutationBaseRevisions.set(clientMutationId, revision)
    return revision
  }

  getLocalMutationBaseRevision(clientMutationId) {
    const normalized = this._normalizeClientMutationId(clientMutationId)
    if (!normalized) return null
    return this._getOrCreateOutgoingMutationBaseRevision(normalized)
  }

  /**
   * 前一 HTTP 批次在途期间，上层会禁止下一批 Yjs 帧进入网络。前一批普通
   * 保存成功后，这个完全未发送的批次可以安全改用刚提交的 revision；否则
   * 它会把同一浏览器自己的上一批修改误认为远端冲突。
   *
   * 已经分配过序号即代表至少尝试过实时发送，服务端可能已接收其中一部分，
   * 此时绝不能改写 base revision，只能继续走既有的 reload/冲突恢复流程。
   */
  rebaseUnsentLocalMutation(clientMutationId, baseRevision) {
    const normalized = this._normalizeClientMutationId(clientMutationId)
    const nextRevision = Number(baseRevision)
    if (
      !normalized
      || !Number.isInteger(nextRevision)
      || nextRevision <= 0
      || !this._pendingLocalMutationIds.has(normalized)
      || (this._outgoingMutationUpdateCounts.get(normalized) || 0) > 0
    ) return false

    const currentRevision = this._getOrCreateOutgoingMutationBaseRevision(normalized)
    if (nextRevision < currentRevision) return false
    this._outgoingMutationBaseRevisions.set(normalized, nextRevision)
    return true
  }

  _nextOutgoingMutationUpdateSequence(clientMutationId) {
    if (this._sealedLocalMutationIds.has(clientMutationId)) return null
    const current = this._outgoingMutationUpdateCounts.get(clientMutationId) || 0
    const next = current + 1
    if (next > MAX_YJS_UPDATES_PER_MUTATION) {
      this._rememberBoundedMutationId(this._unreliableLocalMutationIds, clientMutationId)
      this._handleStaleState({
        contentRevision: this.contentRevision,
        reason: 'mutation_update_limit',
        message: '单次协作修改过多，正在从云端重新建立安全基线',
      })
      return null
    }
    this._outgoingMutationUpdateCounts.set(clientMutationId, next)
    return next
  }

  sealLocalMutation(clientMutationId) {
    const normalized = this._normalizeClientMutationId(clientMutationId)
    if (!normalized) return 0
    if (this._pendingPreSyncChanges.some(
      change => this._normalizeClientMutationId(change?.clientMutationId) === normalized,
    )) this._rememberBoundedMutationId(this._unreliableLocalMutationIds, normalized)
    this._rememberBoundedMutationId(this._sealedLocalMutationIds, normalized)
    return this._outgoingMutationUpdateCounts.get(normalized) || 0
  }

  getLocalMutationDeliveryMode(clientMutationId) {
    const normalized = this._normalizeClientMutationId(clientMutationId)
    return normalized && !this._unreliableLocalMutationIds.has(normalized)
      ? 'sequenced'
      : 'reload'
  }

  confirmLocalMutation(clientMutationId) {
    const normalized = this._normalizeClientMutationId(clientMutationId)
    if (!normalized) return false
    const confirmedRevision = this._confirmedRemoteMutationIds.get(normalized)?.revision
    this._pendingLocalMutationIds.delete(normalized)
    this._outgoingMutationUpdateCounts.delete(normalized)
    this._outgoingMutationBaseRevisions.delete(normalized)
    this._unreliableLocalMutationIds.delete(normalized)
    if (this._checkpointDirty) this._scheduleCheckpoint()
    // WebSocket 的 revision 广播可能先于同一 HTTP 响应到达。此时虽然
    // mutation 已确认，但 contentRevision 尚未推进，不能用旧 revision
    // 写压缩检查点；待连续 revision 真正消费后再补发。
    if (
      (!Number.isInteger(confirmedRevision) || confirmedRevision <= this.contentRevision)
      && !this.requiresAuthoritativeReconciliation()
    ) {
      this._flushPendingCheckpointConsolidation()
    }
    return true
  }

  _normalizeClientMutationId(value) {
    if (typeof value !== 'string') return null
    const normalized = value.trim()
    return normalized && normalized.length <= 100 ? normalized : null
  }

  _normalizeMutationUpdateSequence(value) {
    return Number.isInteger(value)
      && value >= 1
      && value <= MAX_YJS_UPDATES_PER_MUTATION
      ? value
      : null
  }

  _withOutgoingClientMutationId(clientMutationId, action) {
    const previous = this._outgoingClientMutationId
    this._outgoingClientMutationId = this._normalizeClientMutationId(clientMutationId)
    try {
      return action()
    } finally {
      this._outgoingClientMutationId = previous
    }
  }

  _refreshUnconfirmedRemoteState() {
    this._hasUnconfirmedRemoteState = this._hasLegacyUnconfirmedRemoteState
      || this._unconfirmedRemoteMutationIds.size > 0
  }

  _rememberConfirmedRemoteMutation(clientMutationId, revision, data = {}) {
    if (!clientMutationId || !Number.isInteger(revision)) return null
    const record = {
      revision,
      data: { ...data, clientMutationId, contentRevision: revision },
      yjsUpdateCount: Number.isInteger(data?.yjsUpdateCount)
        && data.yjsUpdateCount >= 0
        && data.yjsUpdateCount <= MAX_YJS_UPDATES_PER_MUTATION
        ? data.yjsUpdateCount
        : null,
      authoritativeReloadRequired: (
        data?.authoritativeReloadRequired === true
        || data?.yjsDeliveryMode === 'reload'
        || (
          data?.concurrentMerge === true
          && data?.authoritativeReloadRequired !== false
        )
      ),
      notified: false,
    }
    this._confirmedRemoteMutationIds.delete(clientMutationId)
    this._confirmedRemoteMutationIds.set(clientMutationId, record)
    while (this._confirmedRemoteMutationIds.size > MAX_CONFIRMED_MUTATION_IDS) {
      const oldestId = this._confirmedRemoteMutationIds.keys().next().value
      const oldestRecord = this._confirmedRemoteMutationIds.get(oldestId)
      this._clearConfirmedMutationDeliveryTimer(oldestId)
      this._confirmedRemoteMutationIds.delete(oldestId)
      if (oldestRecord && !oldestRecord.notified) {
        this._handleStaleState({
          contentRevision: Math.max(this.contentRevision, oldestRecord.revision),
          reason: 'mutation_confirmation_capacity',
          message: '协作确认积压超过安全上限，正在从云端校准画布',
        })
        break
      }
    }
    return record
  }

  _discardConfirmedMutationsAtOrBelowCurrentRevision() {
    for (const [clientMutationId, record] of this._confirmedRemoteMutationIds) {
      if (
        record.revision <= this.contentRevision
        && this._isConfirmedMutationReady(clientMutationId, record)
      ) {
        record.notified = true
        this._unconfirmedRemoteMutationIds.delete(clientMutationId)
        this._clearConfirmedMutationDeliveryTimer(clientMutationId)
        this._forgetRemoteMutationSequences(clientMutationId)
      }
    }
    this._refreshUnconfirmedRemoteState()
  }

  _isConfirmedMutationReady(clientMutationId, record = null) {
    if (this._localMutationIds.has(clientMutationId)) return true
    // 缺少精确 count 时，“至少收到一帧”不能证明批次完整。旧服务端
    // 也统一通过确认超时回源，避免滚动升级期间重新引入原来的竞态。
    if (!record || record.yjsUpdateCount === null) return false
    if (record.yjsUpdateCount === 0) return false
    const appliedSequences = this._appliedRemoteMutationSequences.get(clientMutationId)
    if (!appliedSequences || appliedSequences.size !== record.yjsUpdateCount) return false
    for (let sequence = 1; sequence <= record.yjsUpdateCount; sequence += 1) {
      if (!appliedSequences.has(sequence)) return false
    }
    return true
  }

  _hasPendingConfirmedRemoteMutation() {
    for (const [clientMutationId, record] of this._confirmedRemoteMutationIds) {
      if (
        !record.notified
        && record.revision > this.contentRevision
        && !this._isConfirmedMutationReady(clientMutationId, record)
      ) return true
    }
    return false
  }

  _flushConfirmedMutationRevisions() {
    if (
      this._destroyed
      || this._authoritativeRevisionPending !== null
      || this._hasLegacyUnconfirmedRemoteState
    ) return false
    let advanced = false
    while (true) {
      const nextRevision = this.contentRevision + 1
      const candidate = [...this._confirmedRemoteMutationIds.entries()].find(
        ([clientMutationId, record]) => (
          !record.notified
          && record.revision === nextRevision
          && this._isConfirmedMutationReady(clientMutationId, record)
          // 当前客户端的并发合并结果可能不同于本地 Yjs 内容，必须等待
          // HTTP 响应应用权威树，不能被抢先到达的广播抬高保存基线。
          && !(
            record.authoritativeReloadRequired
            && this._localMutationIds.has(clientMutationId)
          )
        ),
      )
      if (!candidate) break
      const [, record] = candidate
      record.notified = true
      this._clearConfirmedMutationDeliveryTimer(record.data.clientMutationId)
      this._unconfirmedRemoteMutationIds.delete(record.data.clientMutationId)
      this._forgetRemoteMutationSequences(record.data.clientMutationId)
      this._refreshUnconfirmedRemoteState()
      this.contentRevision = record.revision
      this.options.onContentRevision?.(record.revision, record.data)
      if (this._checkpointDirty) this._scheduleCheckpoint()
      advanced = true
    }
    if (advanced) this._flushPendingCheckpointConsolidation()
    return advanced
  }

  _markPendingRemoteMutationsApplied() {
    for (const clientMutationId of this._pendingRemoteMutationApplyIds) {
      this._rememberBoundedMutationId(this._appliedRemoteMutationIds, clientMutationId)
    }
    this._pendingRemoteMutationApplyIds.clear()
    for (const [clientMutationId, sequences] of this._pendingRemoteMutationApplySequences) {
      let applied = this._appliedRemoteMutationSequences.get(clientMutationId)
      if (!applied) {
        applied = new Set()
        this._appliedRemoteMutationSequences.set(clientMutationId, applied)
      }
      for (const sequence of sequences) applied.add(sequence)
    }
    this._pendingRemoteMutationApplySequences.clear()
    this._flushConfirmedMutationRevisions()
  }

  _rememberPendingRemoteMutationSequence(clientMutationId, sequence) {
    if (!clientMutationId || sequence === null) return
    let sequences = this._pendingRemoteMutationApplySequences.get(clientMutationId)
    if (!sequences) {
      sequences = new Set()
      this._pendingRemoteMutationApplySequences.set(clientMutationId, sequences)
    }
    sequences.add(sequence)
  }

  _forgetRemoteMutationSequences(clientMutationId) {
    this._pendingRemoteMutationApplySequences.delete(clientMutationId)
    this._appliedRemoteMutationSequences.delete(clientMutationId)
    this._remoteMutationSequenceFingerprints.delete(clientMutationId)
  }

  _rememberRemoteMutationSequenceFingerprint(
    clientMutationId,
    sequence,
    encodedUpdate,
    patch,
  ) {
    if (!clientMutationId || sequence === null) return 'unsequenced'
    let fingerprints = this._remoteMutationSequenceFingerprints.get(clientMutationId)
    if (!fingerprints) {
      if (this._remoteMutationSequenceFingerprints.size >= MAX_CONFIRMED_MUTATION_IDS) {
        const oldestId = this._remoteMutationSequenceFingerprints.keys().next().value
        const oldestConfirmation = this._confirmedRemoteMutationIds.get(oldestId)
        if (
          this._unconfirmedRemoteMutationIds.has(oldestId)
          || (oldestConfirmation && !oldestConfirmation.notified)
        ) return 'capacity'
        this._remoteMutationSequenceFingerprints.delete(oldestId)
      }
      fingerprints = new Map()
      this._remoteMutationSequenceFingerprints.set(clientMutationId, fingerprints)
    }
    let fingerprint
    try {
      fingerprint = `${encodedUpdate}\n${stringifyJsonValueIterative(patch ?? null)}`
    } catch {
      return 'invalid'
    }
    const existing = fingerprints.get(sequence)
    if (existing !== undefined) return existing === fingerprint ? 'duplicate' : 'conflict'
    fingerprints.set(sequence, fingerprint)
    return 'new'
  }

  _rememberBoundedMutationId(target, clientMutationId) {
    if (!clientMutationId) return
    target.delete(clientMutationId)
    target.add(clientMutationId)
    while (target.size > MAX_CONFIRMED_MUTATION_IDS) {
      target.delete(target.values().next().value)
    }
  }

  _clearConfirmedMutationDeliveryTimer(clientMutationId) {
    const timer = this._confirmedMutationDeliveryTimers.get(clientMutationId)
    if (timer === undefined) return
    clearTimeout(timer)
    this._confirmedMutationDeliveryTimers.delete(clientMutationId)
  }

  _clearConfirmedMutationDeliveryTimers() {
    for (const timer of this._confirmedMutationDeliveryTimers.values()) {
      clearTimeout(timer)
    }
    this._confirmedMutationDeliveryTimers.clear()
  }

  _clearUnconfirmedMutationTimer(clientMutationId) {
    const timer = this._unconfirmedMutationTimers.get(clientMutationId)
    if (timer === undefined) return
    clearTimeout(timer)
    this._unconfirmedMutationTimers.delete(clientMutationId)
  }

  _clearUnconfirmedMutationTimers() {
    for (const timer of this._unconfirmedMutationTimers.values()) clearTimeout(timer)
    this._unconfirmedMutationTimers.clear()
  }

  _clearLegacyUnconfirmedMutationTimer() {
    clearTimeout(this._legacyUnconfirmedMutationTimer)
    this._legacyUnconfirmedMutationTimer = null
  }

  _scheduleLegacyUnconfirmedMutationCheck(data = {}) {
    if (
      this._destroyed
      || this._authoritativeRevisionPending !== null
      || !this._hasLegacyUnconfirmedRemoteState
    ) return false
    this._clearLegacyUnconfirmedMutationTimer()
    this._legacyUnconfirmedMutationTimer = setTimeout(() => {
      this._legacyUnconfirmedMutationTimer = null
      if (
        this._destroyed
        || this._authoritativeRevisionPending !== null
        || !this._hasLegacyUnconfirmedRemoteState
      ) return
      this._handleStaleState({
        ...data,
        contentRevision: this.contentRevision,
        reason: 'legacy_unconfirmed_mutation_timeout',
        message: '旧版实时预览未收到云端保存确认，正在恢复服务器版本',
      })
    }, this.unconfirmedMutationTimeoutMs)
    this._legacyUnconfirmedMutationTimer?.unref?.()
    return true
  }

  _scheduleUnconfirmedMutationCheck(clientMutationId, data = {}) {
    if (
      !clientMutationId
      || this._destroyed
      || this._authoritativeRevisionPending !== null
      || this._localMutationIds.has(clientMutationId)
      || this._confirmedRemoteMutationIds.has(clientMutationId)
    ) return false
    const isNewMutation = !this._unconfirmedMutationTimers.has(clientMutationId)
    if (
      isNewMutation
      && this._unconfirmedMutationTimers.size >= MAX_CONFIRMED_MUTATION_IDS
    ) {
      this._handleStaleState({
        ...data,
        contentRevision: this.contentRevision,
        reason: 'unconfirmed_mutation_capacity',
        message: '未确认的实时协作批次超过安全上限，正在从云端校准画布',
      })
      return false
    }
    // 正在连续输入的同一 mutation 会持续产生帧；每帧都延后一次静默
    // 回源。停止输入后若 HTTP 保存确认始终没有到达，远端预览不能永久
    // 冒充云端内容，必须恢复数据库权威版本。
    this._clearUnconfirmedMutationTimer(clientMutationId)
    const timer = setTimeout(() => {
      this._unconfirmedMutationTimers.delete(clientMutationId)
      if (
        this._destroyed
        || this._authoritativeRevisionPending !== null
        || this._localMutationIds.has(clientMutationId)
        || this._confirmedRemoteMutationIds.has(clientMutationId)
        || !this._unconfirmedRemoteMutationIds.has(clientMutationId)
      ) return
      this._handleStaleState({
        ...data,
        contentRevision: this.contentRevision,
        reason: 'unconfirmed_mutation_timeout',
        message: '实时预览未收到云端保存确认，正在恢复服务器版本',
      })
    }, this.unconfirmedMutationTimeoutMs)
    timer?.unref?.()
    this._unconfirmedMutationTimers.set(clientMutationId, timer)
    return true
  }

  _scheduleConfirmedMutationDeliveryCheck(clientMutationId, revision, data) {
    if (
      !clientMutationId
      || this._destroyed
      || this._authoritativeRevisionPending !== null
      || this._localMutationIds.has(clientMutationId)
      || this._confirmedMutationDeliveryTimers.has(clientMutationId)
    ) return false
    const timer = setTimeout(() => {
      this._confirmedMutationDeliveryTimers.delete(clientMutationId)
      if (
        this._destroyed
        || this._authoritativeRevisionPending !== null
        || this._localMutationIds.has(clientMutationId)
        || this._confirmedRemoteMutationIds.get(clientMutationId)?.notified
      ) return
      const record = this._confirmedRemoteMutationIds.get(clientMutationId)
      const updateApplied = this._isConfirmedMutationReady(clientMutationId, record)
      // HTTP 已确认这个批次，但对应 Yjs 增量没有成功应用到画布，或更早
      // revision 的确认丢失。两种情况都不能把旧画布伪装成最新保存基线。
      this._handleStaleState({
        ...data,
        contentRevision: Math.max(this.contentRevision, revision),
        message: updateApplied
          ? '实时协作版本确认不连续，正在从云端校准画布'
          : '实时协作增量未完整到达，正在从云端校准画布',
        reason: updateApplied
          ? 'confirmed_revision_gap'
          : 'confirmed_mutation_missing',
      })
    }, this.confirmedMutationDeliveryTimeoutMs)
    this._confirmedMutationDeliveryTimers.set(clientMutationId, timer)
    return true
  }

  /** 当前 Yjs 内容需要由 HTTP 权威文档重新确认后才能继续持久化。 */
  requiresAuthoritativeReconciliation() {
    return this._hasUncorrelatedLocalState
      || this._hasUnconfirmedRemoteState
      || this._pendingLocalMutationIds.size > 0
      || this._hasPendingConfirmedRemoteMutation()
      || this._authoritativeRevisionPending !== null
  }

  _beginSyncHandshake() {
    if (this._destroyed) return
    // 来源清理声明只对产生它的那次 sync_init 快照有效。断线重连后即使
    // source id 相同，数据库内容也可能已经被另一浏览器更新，不能复用旧
    // CAS 声明；等待新握手重新携带 id + digest。
    this._pendingCheckpointReplacesSources = []
    this._pendingCheckpointInvalidSources = []
    this._pendingCheckpointSourceDigests = {}
    // 同一个编辑器实例可能经历多次断线重连。只有当前 Y.Doc 已经没有
    // 未确认状态时，画布才是当前 revision 的安全权威副本，可更新本次
    // 握手的比较基线；离线编辑期间则继续保留断线前的云端基线。
    if (!this.requiresAuthoritativeReconciliation()) {
      this._captureAuthoritativeBaseline()
    }
    clearTimeout(this._syncInitTimer)
    this._receivedServerState = false
    this._hadLocalDataBeforeSync = this.hasData()
    this.isSynced.value = false
    this.connectionState.value = 'syncing'
    this.syncError.value = ''
    this._syncInitTimer = setTimeout(() => {
      if (this.readonly) this._completeReadonlyHandshake()
      else this._requestSeedLease()
    }, 1200)
  }

  _requestSeedLease() {
    if (
      this._destroyed
      || this.readonly
      || this._receivedServerState
    ) return
    this.wsClient.send({
      type: 'request_seed',
      contentRevision: this.contentRevision,
    })
    clearTimeout(this._syncInitTimer)
    this._syncInitTimer = setTimeout(() => this._requestSeedLease(), 3000)
  }

  _completeReadonlyHandshake() {
    if (this._destroyed) return
    clearTimeout(this._syncInitTimer)
    // 只读观察者继续展示 HTTP 权威树，但 Yjs 文档保持空白，直到收到已有
    // 编辑者或唯一可写种子提供的共享状态。只读端绝不能独立创建同名嵌套
    // Yjs 类型，否则之后与真正房间种子合并时可能永久停留在旧分支。
    this._receivedServerState = false
    this.isSynced.value = true
    this.connectionState.value = 'connected'
    this.syncError.value = ''
  }

  _completeSyncHandshake(receivedServerState, {
    repairTagDefinitions = false,
  } = {}) {
    if (this._destroyed || this._authoritativeRevisionPending !== null) return false
    // 空房间播种必须来自已经被 HTTP 权威版本确认的画布。保存请求冻结后，
    // Edit 会清空当前 mutationId，但 Yjs 仍保留待确认批次；若此时仅依赖
    // getter，就会把尚未落库（甚至随后保存失败）的画布误标成 seedState。
    // 这里作为所有调用方的最后一道栅栏，避免未来新增握手入口绕过校验。
    if (!receivedServerState && this.requiresAuthoritativeReconciliation()) {
      this.isSynced.value = false
      this.connectionState.value = 'syncing'
      this.syncError.value = '正在等待本地修改确认后初始化协作状态'
      return false
    }
    clearTimeout(this._syncInitTimer)
    const currentData = this.mindMap?.getData?.(true)
    const currentDocument = currentData?.root ? {
      ...currentData,
      documentData: this.options.getDocumentData?.(),
    } : currentData
    if (!this.hasData() && !this.readonly) {
      const root = currentDocument?.root || currentDocument
      if (root) {
        const pendingMutationId = this._normalizeClientMutationId(
          this.options.getClientMutationId?.(),
        )
        this._sendingAuthoritativeSeed = !receivedServerState && !pendingMutationId
        this._authoritativeSeedSendResult = null
        try {
          this.initFromMindmap(currentDocument, pendingMutationId)
        } finally {
          this._sendingAuthoritativeSeed = false
        }
        if (
          !receivedServerState
          && !pendingMutationId
          && this._authoritativeSeedSendResult === null
        ) {
          // The production client binds the Y.Doc update observer in start(),
          // but initialization must not rely on that incidental ordering.  A
          // reconnect/test harness may already dispatch seed_granted while the
          // observer is being rebound.  Send the completed full state directly
          // when no synchronous observer result was recorded.
          this._authoritativeSeedSendResult = this._sendFullState({
            authoritativeSeed: true,
          })
        }
        if (
          !receivedServerState
          && !pendingMutationId
          && this._authoritativeSeedSendResult !== true
        ) {
          // 当前租约仍可能由服务端保留到短 TTL；继续 request_seed 可由
          // 同一连接重新获得 grant，随后 hasData 分支会补发完整状态。
          // 保留本地 Y.Doc 供重试，但不清握手定时器、不宣告同步完成。
          this._authoritativeSeedSendResult = null
          this.isSynced.value = false
          this.connectionState.value = 'syncing'
          this.syncError.value = '协作种子尚未送达，正在重试初始化'
          this._requestSeedLease()
          return false
        }
        this._authoritativeSeedSendResult = null
        // 当前完整画布已经包含握手期间发生的本地修改，不再逐条重放。
        this._pendingPreSyncChanges = []
      }
    }
    if (currentDocument?.root && !this.readonly) {
      const missingMeta = {}
      if (!this.yMeta.has('layout')) missingMeta.layout = currentDocument.layout
      if (!this.yMeta.has('theme')) missingMeta.theme = currentDocument.theme
      if (
        !this.yMeta.has('documentData')
        && currentDocument.documentData !== undefined
      ) {
        missingMeta.documentData = currentDocument.documentData
      }
      if (this._repairAuthoritativeBaselineMetadata(missingMeta, {
        repairTagDefinitions,
      })) {
        this._scheduleCheckpoint()
      }
    }
    this._receivedServerState = receivedServerState
    this.isSynced.value = true
    this.connectionState.value = 'connected'
    this.syncError.value = ''
    return true
  }

  _sendFullState({ authoritativeSeed = false } = {}) {
    if (
      this._destroyed
      || this._authoritativeRevisionPending !== null
      || this.readonly
      // 无 mutationId 的完整状态无法证明其中的删除/移动已经由 HTTP
      // 提交。断线期间或远端确认尚未完成时禁止补发，先让保存/权威回源
      // 收口；否则服务端或新加入者可能把临时 Y.Doc 当成当前 revision
      // 的基线，复活旧节点或把完整树收缩成残缺树。
      || this.requiresAuthoritativeReconciliation()
      || !this._yjsDocumentMatchesCurrentCanvas()
    ) return false
    const state = Y.encodeStateAsUpdate(this.doc)
    const lineageId = this._getYjsLineageId()
    const sent = this.wsClient.send({
      type: 'update',
      update: this._encodeUpdate(state),
      state: this._encodeUpdate(state),
      contentRevision: this.contentRevision,
      ...(lineageId ? { lineageId } : {}),
      ...(authoritativeSeed ? { seedState: true } : {}),
    })
    // 只有租约种子会被服务端立即持久化。普通 seed_request 响应只是实时
    // 帮新连接补齐状态，不能因此丢掉尚待写入数据库的检查点。
    if (sent && authoritativeSeed) this._clearCheckpoint()
    return sent
  }

  _sendConsolidatedCheckpoint(
    replacesSources,
    invalidSources = [],
    sourceDigests = {},
  ) {
    const mergedSources = Array.isArray(replacesSources) ? replacesSources : []
    const rejectedSources = Array.isArray(invalidSources) ? invalidSources : []
    if (
      this._destroyed
      || this.readonly
      || this._authoritativeRevisionPending !== null
      || this.requiresAuthoritativeReconciliation()
      || !this._supportsCheckpointProtocol()
      || !this._supportsSourceCasProtocol()
      || (!mergedSources.length && !rejectedSources.length)
    ) return false
    const lineageId = this._getYjsLineageId()
    const sent = this.wsClient.send({
      type: 'checkpoint',
      state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
      contentRevision: this.contentRevision,
      ...(lineageId ? { lineageId } : {}),
      ...(mergedSources.length ? { replacesSources: mergedSources } : {}),
      ...(rejectedSources.length ? { invalidSources: rejectedSources } : {}),
      sourceDigests: Object.fromEntries(
        [...mergedSources, ...rejectedSources].map(sourceId => [
          sourceId,
          sourceDigests[sourceId],
        ]),
      ),
    })
    if (sent) this._clearCheckpoint()
    return sent
  }

  _rememberPendingCheckpointConsolidation(
    replacesSources,
    invalidSources,
    sourceDigests = {},
  ) {
    if (!this._supportsSourceCasProtocol()) return
    const hasDigest = sourceId => (
      typeof sourceDigests[sourceId] === 'string'
      && /^[0-9a-f]{64}$/.test(sourceDigests[sourceId])
    )
    const safeReplaces = (Array.isArray(replacesSources) ? replacesSources : [])
      .filter(hasDigest)
    const safeInvalid = (Array.isArray(invalidSources) ? invalidSources : [])
      .filter(hasDigest)
    this._pendingCheckpointReplacesSources = [
      ...new Set([
        ...this._pendingCheckpointReplacesSources,
        ...safeReplaces,
      ]),
    ]
    this._pendingCheckpointInvalidSources = [
      ...new Set([
        ...this._pendingCheckpointInvalidSources,
        ...safeInvalid,
      ]),
    ]
    for (const sourceId of [...safeReplaces, ...safeInvalid]) {
      this._pendingCheckpointSourceDigests[sourceId] = sourceDigests[sourceId]
    }
  }

  _flushPendingCheckpointConsolidation() {
    if (!this.hasData()) return false
    const replacesSources = this._pendingCheckpointReplacesSources
    const invalidSources = this._pendingCheckpointInvalidSources
    if (!replacesSources.length && !invalidSources.length) return false
    const sent = this._sendConsolidatedCheckpoint(
      replacesSources,
      invalidSources,
      this._pendingCheckpointSourceDigests,
    )
    if (sent) {
      this._pendingCheckpointReplacesSources = []
      this._pendingCheckpointInvalidSources = []
      this._pendingCheckpointSourceDigests = {}
      if (
        this.connectionState.value === 'degraded'
        && this._authoritativeRevisionPending === null
        && !this.requiresAuthoritativeReconciliation()
      ) {
        this.isSynced.value = true
        this.connectionState.value = 'connected'
        this.syncError.value = ''
      }
    }
    return sent
  }

  _supportsCheckpointProtocol() {
    return this.serverCapabilities.has(YJS_CHECKPOINT_CAPABILITY)
  }

  _supportsConditionalNodePatchProtocol() {
    return this.serverCapabilities.has(CONDITIONAL_NODE_PATCH_CAPABILITY)
  }

  _supportsSourceCasProtocol() {
    return this.serverCapabilities.has(YJS_SOURCE_CAS_CAPABILITY)
  }

  _supportsNodeEditLeaseProtocol() {
    return this.serverCapabilities.has(NODE_EDIT_LEASE_CAPABILITY)
  }

  usesAuthoritativeNodeEditLease() {
    return this._supportsNodeEditLeaseProtocol()
  }

  getNodeEditLeaseFailureReason() {
    return this._nodeEditLeaseFailureReason
  }

  _setNodeEditLeaseFailureReason(reason, generation = null) {
    if (
      generation !== null
      && generation !== this._nodeEditLeaseAcquireGeneration
    ) return
    this._nodeEditLeaseFailureReason = NODE_EDIT_LEASE_FAILURE_REASONS.has(reason)
      ? reason
      : 'unavailable'
  }

  _getNodeEditLeaseAvailabilityFailureReason() {
    if (this.readonly) return 'readonly'
    if (this._destroyed || this._paused) return 'unavailable'
    if (!this.wsClient?.isAuthenticated) {
      return [
        'idle',
        'connecting',
        'reconnecting',
        'authenticating',
      ].includes(this.wsClient?.connectionState)
        ? 'connecting'
        : 'unavailable'
    }
    if (!this._supportsNodeEditLeaseProtocol()) return 'unavailable'
    // 认证完成并不代表已应用房间里的 Yjs 状态。握手完成前按 HTTP 旧树
    // 获锁会让下一位编辑者从前一位刚发布、尚未渲染的旧文本开始。
    if (this.isSynced.value !== true) return 'connecting'
    if (typeof this.options.canAcquireNodeEditLease === 'function') {
      try {
        if (this.options.canAcquireNodeEditLease() === false) return 'unavailable'
      } catch {
        return 'unavailable'
      }
    }
    return ''
  }

  _isNodeEditLeaseConnectionHealthy() {
    return Boolean(
      !this.readonly
      && !this._destroyed
      && !this._paused
      && this.wsClient?.isAuthenticated
      && this.isSynced.value === true
      && this._supportsNodeEditLeaseProtocol()
    )
  }

  hasNodeEditLease(nodeOrUid) {
    const nodeUid = this._normalizeAwarenessEditingNodeUid(
      typeof nodeOrUid === 'object'
        ? nodeOrUid?.uid || nodeOrUid?.getData?.('uid')
        : nodeOrUid
    )
    return Boolean(
      nodeUid
      && nodeUid === this._nodeEditLeaseUid
      && this._supportsNodeEditLeaseProtocol()
      && !this._destroyed
      && !this._paused
      && !this.readonly
      && this.isSynced.value === true
    )
  }

  hasActiveNodeEditLease() {
    return Boolean(this._nodeEditLeaseUid)
  }

  async acquireNodeEditLease(nodeOrUid) {
    this._nodeEditLeaseFailureReason = ''
    const nodeUid = this._normalizeAwarenessEditingNodeUid(
      typeof nodeOrUid === 'object'
        ? nodeOrUid?.uid || nodeOrUid?.getData?.('uid')
        : nodeOrUid
    )
    const availabilityFailure = this._getNodeEditLeaseAvailabilityFailureReason()
    if (!nodeUid || availabilityFailure) {
      this._setNodeEditLeaseFailureReason(
        availabilityFailure || 'unavailable',
      )
      return false
    }
    if (this.hasNodeEditLease(nodeUid)) {
      this._nodeEditLeaseFailureReason = ''
      return true
    }

    const generation = ++this._nodeEditLeaseAcquireGeneration
    const acquire = this._nodeEditLeaseAcquireChain.then(async () => {
      if (
        generation !== this._nodeEditLeaseAcquireGeneration
        || this._destroyed
        || this._paused
        || this.readonly
      ) {
        this._setNodeEditLeaseFailureReason(
          this._getNodeEditLeaseAvailabilityFailureReason() || 'unavailable',
          generation,
        )
        return false
      }
      if (this._nodeEditLeaseUid && this._nodeEditLeaseUid !== nodeUid) {
        const previousNodeUid = this._nodeEditLeaseUid
        this._nodeEditLeaseUid = ''
        clearTimeout(this._nodeEditLeaseRefreshTimer)
        this._nodeEditLeaseRefreshTimer = null
        this._sendNodeEditLeaseRelease(previousNodeUid)
      }
      return this._requestNodeEditLease(nodeUid, { generation })
    })
    this._nodeEditLeaseAcquireChain = acquire.catch(() => false)
    return acquire
  }

  releaseNodeEditLease(nodeOrUid = this._nodeEditLeaseUid) {
    const nodeUid = this._normalizeAwarenessEditingNodeUid(
      typeof nodeOrUid === 'object'
        ? nodeOrUid?.uid || nodeOrUid?.getData?.('uid')
        : nodeOrUid
    )
    if (nodeUid && this._nodeEditLeaseUid && nodeUid !== this._nodeEditLeaseUid) {
      return false
    }
    this._nodeEditLeaseAcquireGeneration += 1
    clearTimeout(this._nodeEditLeaseRefreshTimer)
    this._nodeEditLeaseRefreshTimer = null
    if (!nodeUid || !this._nodeEditLeaseUid) return false
    this._nodeEditLeaseUid = ''
    this._sendNodeEditLeaseRelease(nodeUid)
    return true
  }

  _requestNodeEditLease(nodeUid, { generation, renewal = false } = {}) {
    const availabilityFailure = this._getNodeEditLeaseAvailabilityFailureReason()
    if (availabilityFailure) {
      this._setNodeEditLeaseFailureReason(
        availabilityFailure,
        generation,
      )
      return Promise.resolve(false)
    }
    const requestId = [
      'node-edit',
      Date.now().toString(36),
      (++this._nodeEditLeaseRequestSequence).toString(36),
    ].join('-')
    const requestContentRevision = this.contentRevision
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        const pending = this._pendingNodeEditLeaseRequests.get(requestId)
        if (!pending) return
        this._pendingNodeEditLeaseRequests.delete(requestId)
        // 服务端可能已获取/续期租约，只是结果帧丢失。超时后立即
        // best-effort 发送 owner-only release，避免其他浏览器被 30 秒 TTL 假锁阻塞。
        // 先同步触发编辑器提交/flush，再释放服务端所有权；否则另一浏览器
        // 可能在当前 DOM 最终文本进入 Yjs 之前从旧值获锁。
        if (renewal && this._nodeEditLeaseUid === nodeUid) {
          this._loseNodeEditLease(nodeUid)
        }
        this._sendNodeEditLeaseRelease(nodeUid)
        this._setNodeEditLeaseFailureReason('unavailable', generation)
        resolve(false)
      }, this.nodeEditLeaseRequestTimeoutMs)
      timer?.unref?.()
      this._pendingNodeEditLeaseRequests.set(requestId, {
        nodeUid,
        generation,
        renewal,
        contentRevision: requestContentRevision,
        resolve,
        timer,
      })
      if (!this.wsClient.send({
        type: 'node_edit_lease_acquire',
        requestId,
        nodeUid,
        contentRevision: requestContentRevision,
      })) {
        clearTimeout(timer)
        this._pendingNodeEditLeaseRequests.delete(requestId)
        this._setNodeEditLeaseFailureReason(
          this._getNodeEditLeaseAvailabilityFailureReason() || 'unavailable',
          generation,
        )
        resolve(false)
      }
    })
  }

  _handleNodeEditLeaseResult(data) {
    const requestId = typeof data?.requestId === 'string'
      ? data.requestId.trim()
      : ''
    const pending = this._pendingNodeEditLeaseRequests.get(requestId)
    if (!pending) return
    this._pendingNodeEditLeaseRequests.delete(requestId)
    clearTimeout(pending.timer)
    const responseNodeUid = this._normalizeAwarenessEditingNodeUid(data?.nodeUid)
    let granted = data?.granted === true && responseNodeUid === pending.nodeUid
    let releaseSent = false
    const stale = (
      this._destroyed
      || this._paused
      || this.readonly
      || pending.generation !== this._nodeEditLeaseAcquireGeneration
      // 初次获锁必须绑定当前树快照；续租则延续同一所有权，其他节点的
      // HTTP 保存可合法推进 room revision，不能因此打断正在编辑的节点。
      || (!pending.renewal && pending.contentRevision !== this.contentRevision)
      || (pending.renewal && this._nodeEditLeaseUid !== pending.nodeUid)
    )
    if (granted && stale) {
      this._sendNodeEditLeaseRelease(pending.nodeUid)
      releaseSent = true
      granted = false
    }
    if (pending.renewal) {
      if (granted) this._scheduleNodeEditLeaseRefresh(pending.nodeUid)
      else if (this._nodeEditLeaseUid === pending.nodeUid) {
        // 先让 lease_lost 的同步消费者关闭编辑器并把最终文本 flush 进
        // Yjs，再显式归还服务端所有权。即使服务端返回 unavailable 而旧
        // TTL 仍有效，owner-only release 也能避免其他浏览器假锁 30 秒。
        this._loseNodeEditLease(pending.nodeUid)
        if (!releaseSent) this._sendNodeEditLeaseRelease(pending.nodeUid)
      }
    } else if (granted) {
      this._nodeEditLeaseFailureReason = ''
      this._nodeEditLeaseUid = pending.nodeUid
      this._scheduleNodeEditLeaseRefresh(pending.nodeUid)
    } else if (!stale) {
      const serverReason = NODE_EDIT_LEASE_FAILURE_REASONS.has(data?.reason)
        ? data.reason
        : ''
      const explicitlyDenied = (
        data?.granted === false
        && responseNodeUid === pending.nodeUid
      )
      this._setNodeEditLeaseFailureReason(
        serverReason
        || (
          explicitlyDenied && this._isNodeEditLeaseConnectionHealthy()
            ? 'occupied'
            : this._getNodeEditLeaseAvailabilityFailureReason() || 'unavailable'
        ),
        pending.generation,
      )
    }
    pending.resolve(granted)
  }

  _scheduleNodeEditLeaseRefresh(nodeUid) {
    clearTimeout(this._nodeEditLeaseRefreshTimer)
    this._nodeEditLeaseRefreshTimer = null
    if (!this.hasNodeEditLease(nodeUid)) return
    const generation = this._nodeEditLeaseAcquireGeneration
    this._nodeEditLeaseRefreshTimer = setTimeout(() => {
      this._nodeEditLeaseRefreshTimer = null
      if (!this.hasNodeEditLease(nodeUid)) return
      void this._requestNodeEditLease(nodeUid, {
        generation,
        renewal: true,
      })
    }, this.nodeEditLeaseRefreshIntervalMs)
    this._nodeEditLeaseRefreshTimer?.unref?.()
  }

  _sendNodeEditLeaseRelease(nodeUid) {
    if (!nodeUid || !this._supportsNodeEditLeaseProtocol()) return false
    return this.wsClient.send({
      type: 'node_edit_lease_release',
      nodeUid,
      contentRevision: this.contentRevision,
    })
  }

  _loseNodeEditLease(nodeUid) {
    if (!nodeUid || this._nodeEditLeaseUid !== nodeUid) return
    this._nodeEditLeaseUid = ''
    clearTimeout(this._nodeEditLeaseRefreshTimer)
    this._nodeEditLeaseRefreshTimer = null
    const runtimeNode = this.mindMap?.renderer?.findNodeByUid?.(nodeUid)
    this.mindMap?.emit?.('node_text_edit_lease_lost', runtimeNode, nodeUid)
  }

  _clearPendingNodeEditLeaseRequests() {
    for (const pending of this._pendingNodeEditLeaseRequests.values()) {
      clearTimeout(pending.timer)
      pending.resolve(false)
    }
    this._pendingNodeEditLeaseRequests.clear()
  }

  _handleNodeEditLeaseDisconnect() {
    const nodeUid = this._nodeEditLeaseUid
    this._nodeEditLeaseUid = ''
    this._nodeEditLeaseAcquireGeneration += 1
    clearTimeout(this._nodeEditLeaseRefreshTimer)
    this._nodeEditLeaseRefreshTimer = null
    this._clearPendingNodeEditLeaseRequests()
    if (!this._destroyed) this._nodeEditLeaseFailureReason = 'connecting'
    if (nodeUid && !this._destroyed) {
      const runtimeNode = this.mindMap?.renderer?.findNodeByUid?.(nodeUid)
      this.mindMap?.emit?.('node_text_edit_lease_lost', runtimeNode, nodeUid)
    }
  }

  _clearCheckpoint() {
    clearTimeout(this._checkpointTimer)
    this._checkpointTimer = null
    this._checkpointDirty = false
  }

  _scheduleCheckpoint() {
    if (
      this._destroyed
      || this._paused
      || !this._supportsCheckpointProtocol()
    ) return
    this._checkpointDirty = true
    if (this.requiresAuthoritativeReconciliation()) return
    if (this._checkpointTimer) return
    this._checkpointTimer = setTimeout(() => {
      this._checkpointTimer = null
      this._flushCheckpoint()
    }, CHECKPOINT_INTERVAL_MS)
  }

  _flushCheckpoint({ reschedule = true } = {}) {
    clearTimeout(this._checkpointTimer)
    this._checkpointTimer = null
    if (
      !this._checkpointDirty
      || this.readonly
      || this._destroyed
      || this._paused
      || this.requiresAuthoritativeReconciliation()
      || !this.hasData()
      || !this._supportsCheckpointProtocol()
    ) return false
    const lineageId = this._getYjsLineageId()
    const sent = this.wsClient.send({
      type: 'checkpoint',
      state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
      contentRevision: this.contentRevision,
      ...(lineageId ? { lineageId } : {}),
    })
    if (sent) {
      this._checkpointDirty = false
    } else if (reschedule) {
      this._scheduleCheckpoint()
    }
    return sent
  }

  /** 暂停同步（版本预览时使用） */
  pause() {
    this.releaseNodeEditLease()
    this._sendAwareness([], true, '')
    this._flushCheckpoint({ reschedule: false })
    this._paused = true
    this._clearRemoteAwareness()
    clearTimeout(this._remotePrepareRetryTimer)
    this._remotePrepareRetryTimer = null
  }

  /** 恢复同步 */
  resume() {
    this._paused = false
    if (this._checkpointDirty) this._scheduleCheckpoint()
    this._sendAwareness(this._localActiveNodeUids)
    if (this._pendingRemoteApply && !this.isApplyingRemote()) {
      this._requestYjsApply()
    }
  }

  /** 检查 Yjs 文档是否已有数据 */
  hasData() {
    return this.yNodes.size > 0
  }

  _getDerivedYjsLineageId(sourceDoc = this.doc) {
    const nodes = sourceDoc.getMap('nodes')
    const preferredRootUid = this._initialAuthoritativeRootUid
    const preferredRoot = preferredRootUid ? nodes.get(preferredRootUid) : null
    const preferredIdentity = getYjsTypeIdentity(preferredRoot)
    if (preferredIdentity) return `node:${preferredIdentity}`
    const identities = []
    nodes.forEach((node) => {
      const identity = getYjsTypeIdentity(node)
      if (identity) identities.push(identity)
    })
    identities.sort()
    return identities.length ? `node:${identities[0]}` : ''
  }

  _getYjsLineageId(sourceDoc = this.doc) {
    return normalizeYjsLineageId(sourceDoc.getMap('meta').get('lineageId'))
      || this._getDerivedYjsLineageId(sourceDoc)
  }

  _ensureYjsLineageId(sourceDoc = this.doc) {
    const meta = sourceDoc.getMap('meta')
    const current = normalizeYjsLineageId(meta.get('lineageId'))
    if (current) return current
    const derived = this._getDerivedYjsLineageId(sourceDoc)
      || createYjsLineageId(sourceDoc.clientID)
    meta.set('lineageId', derived)
    return derived
  }

  /**
   * Yjs 的嵌套类型只能在同一创建历史上安全合并。仅比较最终 JSON 不足以
   * 发现两个浏览器各自创建了同名 Y.Map 的情况；它们当前看起来相同，败方
   * 分支的后续更新却会永久不可见。lineageId 为新协议的显式证明，节点类型
   * 的 item id 则为旧缓存提供可验证的兼容路径。
   */
  _documentsShareNodeLineage(leftDoc, rightDoc) {
    const leftNodes = leftDoc.getMap('nodes')
    const rightNodes = rightDoc.getMap('nodes')
    if (leftNodes.size === 0 || rightNodes.size === 0) return true
    const leftLineage = normalizeYjsLineageId(leftDoc.getMap('meta').get('lineageId'))
    const rightLineage = normalizeYjsLineageId(rightDoc.getMap('meta').get('lineageId'))
    if (leftLineage && rightLineage && leftLineage !== rightLineage) return false

    const preferredRootUid = this._initialAuthoritativeRootUid
    if (preferredRootUid && leftNodes.has(preferredRootUid) && rightNodes.has(preferredRootUid)) {
      const leftIdentity = getYjsTypeIdentity(leftNodes.get(preferredRootUid))
      const rightIdentity = getYjsTypeIdentity(rightNodes.get(preferredRootUid))
      return Boolean(leftIdentity && leftIdentity === rightIdentity)
    }
    for (const [uid, leftNode] of leftNodes.entries()) {
      if (!rightNodes.has(uid)) continue
      const leftIdentity = getYjsTypeIdentity(leftNode)
      const rightIdentity = getYjsTypeIdentity(rightNodes.get(uid))
      if (leftIdentity && leftIdentity === rightIdentity) return true
    }
    return false
  }

  _persistedUpdatesHaveSingleLineage(updates) {
    const nodeDocuments = []
    try {
      for (const update of (Array.isArray(updates) ? updates : [])) {
        const probeDoc = new Y.Doc()
        Y.applyUpdate(probeDoc, update)
        if (probeDoc.getMap('nodes').size > 0) nodeDocuments.push(probeDoc)
        else probeDoc.destroy()
      }
      if (nodeDocuments.length < 2) return true
      const reference = nodeDocuments[0]
      return nodeDocuments.slice(1).every(document => (
        this._documentsShareNodeLineage(reference, document)
      ))
    } catch {
      return false
    } finally {
      for (const document of nodeDocuments) document.destroy()
    }
  }

  _updateSharesCurrentNodeLineage(update) {
    if (!this.hasData() || !update) return true
    const probeDoc = new Y.Doc()
    try {
      Y.applyUpdate(probeDoc, update)
      return this._documentsShareNodeLineage(this.doc, probeDoc)
    } catch {
      return false
    } finally {
      probeDoc.destroy()
    }
  }

  /** 检查是否已收到服务端的 sync_init 状态 */
  hasReceivedServerState() {
    return this._receivedServerState
  }

  /**
   * 首次握手收到的非空 Yjs 树必须覆盖 HTTP 权威基线中的全部节点，或者
   * 通过只增不减的节点账本证明缺失节点曾存在、随后被实时协作合法删除。
   * 完全不含 nodes 的旧元数据状态仍可接受，并由当前 HTTP 文档补齐节点树。
   */
  _isInitialNodeStateIncomplete(update) {
    if (!update || this._initialAuthoritativeNodeUids.size === 0) return false
    const probeDoc = new Y.Doc()
    try {
      Y.applyUpdate(probeDoc, update)
      const nodes = probeDoc.getMap('nodes')
      const nodeLedger = probeDoc.getMap('nodeLedger')
      const legacyDeletedNodeUids = deletedTopLevelYMapKeys(update, 'nodes')
      if (nodes.size === 0) return false
      for (const uid of this._initialAuthoritativeNodeUids) {
        if (
          !nodes.has(uid)
          && nodeLedger.get(uid) !== true
          && !legacyDeletedNodeUids.has(uid)
        ) return true
      }
      return false
    } catch {
      return true
    } finally {
      probeDoc.destroy()
    }
  }

  _captureAuthoritativeBaseline() {
    const document = this.mindMap?.getData?.(true)
    const root = document?.root || document
    this._initialAuthoritativeRootUid = root?.data?.uid === undefined
      || root?.data?.uid === null
      ? ''
      : String(root.data.uid)
    const semanticSnapshot = this._createSemanticTreeSnapshot(root)
    this._initialAuthoritativeTree = semanticSnapshot.tree
    this._initialAuthoritativeCrossNodeState = semanticSnapshot.crossNodeState
    const definitions = this._captureTagDefinitions(document)
    this._initialAuthoritativeTagDefinitions = cloneJsonValueIterative(
      Object.fromEntries(definitions),
    ) || {}
    const documentData = this.options.getDocumentData?.()
      ?? document?.documentData
      ?? document?.document_data
    const meta = {}
    if (document?.layout !== undefined) meta.layout = document.layout
    if (document?.theme !== undefined) meta.theme = document.theme
    if (documentData !== undefined) meta.documentData = documentData
    this._initialAuthoritativeMeta = cloneJsonValueIterative(meta) || {}
    this._initialAuthoritativeNodeUids = new Set(
      Object.keys(this._initialAuthoritativeTree),
    )
    return document
  }

  _persistedTagDefinitionsAreCompatible(probeTagDefinitions) {
    for (const [key, definition] of probeTagDefinitions.entries()) {
      if (!definition || typeof definition !== 'object' || Array.isArray(definition)) {
        return false
      }
      const expected = this._initialAuthoritativeTagDefinitions[String(key)]
      if (!expected) continue
      const expectedRevision = Number(expected.definitionRevision)
      const incomingRevision = Number(definition.definitionRevision)
      if (Number.isInteger(expectedRevision) && Number.isInteger(incomingRevision)) {
        // 标签定义拥有独立于 contentRevision 的单调版本。HTTP 详情读取后
        // 到达的更高版本是合法实时更新；较旧版本稍后由 HTTP 基线修复。
        if (incomingRevision !== expectedRevision) continue
      } else if (Number.isInteger(expectedRevision) !== Number.isInteger(incomingRevision)) {
        // 有版本的一侧可建立确定顺序：HTTP 有版本而缓存无版本时回填 HTTP；
        // 缓存有版本而旧 HTTP 无版本时保留缓存。
        continue
      }
      if (!isSameObject(cloneJsonValueIterative(definition), expected)) return false
    }
    return true
  }

  _repairAuthoritativeBaselineMetadata(missingMeta = {}, {
    repairTagDefinitions = false,
  } = {}) {
    let changed = false
    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        if (Object.keys(missingMeta).length) {
          this._writeDocumentMeta(missingMeta)
          changed = true
        }
        for (const [key, expected] of (
          repairTagDefinitions
            ? Object.entries(this._initialAuthoritativeTagDefinitions)
            : []
        )) {
          const current = this.yTagDefinitions.get(key)
          const expectedRevision = Number(expected?.definitionRevision)
          const currentRevision = Number(current?.definitionRevision)
          const shouldRestore = !current || (
            Number.isInteger(expectedRevision)
            && (
              !Number.isInteger(currentRevision)
              || currentRevision < expectedRevision
            )
          ) || (
            !Number.isInteger(expectedRevision)
            && !Number.isInteger(currentRevision)
            && !isSameObject(current, expected)
          )
          if (!shouldRestore) continue
          const restored = cloneJsonValueIterative(expected)
          this.yTagDefinitions.set(key, restored)
          this.tagDefinitions.set(key, restored)
          changed = true
        }
        if (!normalizeYjsLineageId(this.yMeta.get('lineageId')) && this.hasData()) {
          this._ensureYjsLineageId()
          changed = true
        }
      }, 'authoritative-baseline')
    } finally {
      this._localYjsChange = false
    }
    return changed
  }

  _createSemanticTreeSnapshot(root) {
    const tree = flattenMindmapTree(root)
    for (const node of Object.values(tree)) {
      node.data = stripCrossNodeData(node.data || {})
    }
    return {
      tree: cloneJsonValueIterative(tree) || {},
      crossNodeState: cloneJsonValueIterative(
        extractCrossNodeState(root),
      ) || { relations: {}, summaries: {}, groups: {}, assets: {} },
    }
  }

  /**
   * 持久化协作缓存只是当前 revision 的派生副本，不能反过来覆盖刚从 HTTP
   * 读取的权威正文。同 revision 下只有用户可见的完整树与文档元数据都与
   * HTTP 基线一致时才接纳；纯元数据/旧格式空状态仍可由当前文档补齐。
   */
  _persistedStateMatchesInitialAuthoritativeDocument(update) {
    if (!update) return false
    const probeDoc = new Y.Doc()
    try {
      Y.applyUpdate(probeDoc, update)
      const probeNodes = probeDoc.getMap('nodes')
      const probeMeta = probeDoc.getMap('meta')
      const probeCrossNodeState = this._readCrossNodeState(probeDoc)
      const hasStoredCrossNodeState = Object.values(probeCrossNodeState)
        .some(collection => Object.keys(collection).length > 0)
      // 没有节点的兼容状态只能携带文档 meta。孤立的跨节点 Map 既无法
      // 验证引用，又会在稍后种子合并时与新 lineage 竞争，必须隔离。
      if (probeNodes.size === 0 && hasStoredCrossNodeState) return false
      if (
        probeNodes.size > 0
        && Number(probeMeta.get('crossNodeSchemaVersion')) >= 1
      ) {
        if (!isSameObject(
          probeCrossNodeState,
          this._initialAuthoritativeCrossNodeState,
        )) return false
      } else if (hasStoredCrossNodeState) {
        return false
      }
      if (probeNodes.size > 0) {
        const probeTree = this._rebuildTreeFromYjs({
          sourceDoc: probeDoc,
          applyTagDefinitions: false,
        })
        const probeSnapshot = this._createSemanticTreeSnapshot(probeTree)
        if (
          !probeTree
          || !isSameObject(probeSnapshot.tree, this._initialAuthoritativeTree)
          || !isSameObject(
            probeSnapshot.crossNodeState,
            this._initialAuthoritativeCrossNodeState,
          )
        ) return false
      }

      if (!this._persistedTagDefinitionsAreCompatible(
        probeDoc.getMap('tagDefinitions'),
      )) return false
      for (const key of ['layout', 'theme', 'documentData']) {
        if (!probeMeta.has(key)) continue
        if (
          !Object.prototype.hasOwnProperty.call(this._initialAuthoritativeMeta, key)
          || !isSameObject(
            probeMeta.get(key),
            this._initialAuthoritativeMeta[key],
          )
        ) return false
      }
      return true
    } catch {
      return false
    } finally {
      probeDoc.destroy()
    }
  }

  _writeDocumentMeta(document = {}) {
    if (document.layout !== undefined) {
      setYMapValueIfChanged(this.yMeta, 'layout', document.layout)
    }
    if (document.theme !== undefined) {
      setYMapValueIfChanged(this.yMeta, 'theme', document.theme)
    }
    if (document.documentData !== undefined) {
      setYMapValueIfChanged(this.yMeta, 'documentData', document.documentData)
    }
  }

  _getPreferredRootUid() {
    // Root identity belongs to the authoritative baseline. Reading the whole
    // canvas here used to clone the complete tree on every keystroke merely to
    // obtain one UID; synchronizeYjsParentUids already has a deterministic
    // fallback when a full-document replacement introduces a different root.
    return this._initialAuthoritativeRootUid || ''
  }

  _readLegacyCrossNodeState(sourceDoc = this.doc) {
    return {
      relations: cloneJsonValueIterative(
        Object.fromEntries(sourceDoc.getMap('relations').entries()),
      ) || {},
      summaries: cloneJsonValueIterative(
        Object.fromEntries(sourceDoc.getMap('summaries').entries()),
      ) || {},
      groups: cloneJsonValueIterative(
        Object.fromEntries(sourceDoc.getMap('groups').entries()),
      ) || {},
      assets: cloneJsonValueIterative(
        Object.fromEntries(sourceDoc.getMap('assets').entries()),
      ) || {},
    }
  }

  _readCrossNodeState(sourceDoc = this.doc) {
    const schemaVersion = Number(sourceDoc.getMap('meta').get('crossNodeSchemaVersion'))
    if (
      schemaVersion >= CROSS_NODE_SCHEMA_VERSION
      || hasCrossNodeRecordStateV2(sourceDoc)
    ) {
      return cloneJsonValueIterative(readCrossNodeRecordStateV2(sourceDoc))
        || { relations: {}, summaries: {}, groups: {}, assets: {} }
    }
    return this._readLegacyCrossNodeState(sourceDoc)
  }

  _replaceCrossNodeState(state = {}) {
    const changed = replaceCrossNodeRecordStateV2(this.doc, state)
    // Keep a semantic v1 mirror during the rolling-upgrade window. Current
    // clients never read it once schema v2 exists, so its whole-record LWW
    // conflicts cannot corrupt the canonical field-addressable state.
    replaceYMapEntries(this.yRelations, state.relations || {})
    replaceYMapEntries(this.ySummaries, state.summaries || {})
    replaceYMapEntries(this.yGroups, state.groups || {})
    replaceYMapEntries(this.yAssets, state.assets || {})
    return changed
  }

  _applyCrossNodeStateDelta(delta) {
    if (!delta) return false
    let changed = applyCrossNodeRecordDeltaV2(this.doc, delta)
    const maps = {
      relations: this.yRelations,
      summaries: this.ySummaries,
      groups: this.yGroups,
      assets: this.yAssets,
    }
    for (const [domain, yMap] of Object.entries(maps)) {
      for (const key of (delta[domain]?.deletedKeys || [])) {
        if (!yMap.has(key)) continue
        yMap.delete(key)
        changed = true
      }
      for (const [key, value] of Object.entries(delta[domain]?.upserts || {})) {
        changed = setYMapValueIfChanged(yMap, key, value) || changed
      }
    }
    return changed
  }

  _hasEmbeddedCrossNodeState() {
    let found = false
    this.yNodes.forEach(yNode => {
      if (found) return
      const yData = yNode.get('data')
      if (yData && CROSS_NODE_DATA_KEYS.some(key => yData.has(key))) found = true
    })
    return found
  }

  /**
   * Upgrade persisted states produced by clients that still embedded relation
   * data in nodes. New-format records win when both formats are present; legacy
   * records are imported only for keys they explicitly carry.
   */
  _normalizeEmbeddedCrossNodeState() {
    const schemaVersion = Number(this.yMeta.get('crossNodeSchemaVersion'))
    const hasEmbeddedState = this._hasEmbeddedCrossNodeState()
    if (schemaVersion >= CROSS_NODE_SCHEMA_VERSION && !hasEmbeddedState) return false
    const embeddedState = hasEmbeddedState
      ? extractCrossNodeState(this._rebuildTreeFromYjs({ applyCrossNode: false }))
      : { relations: {}, summaries: {}, groups: {}, assets: {} }
    const migratedState = schemaVersion >= CROSS_NODE_SCHEMA_VERSION
      ? this._readCrossNodeState()
      : this._readLegacyCrossNodeState()
    // Node-embedded records are the oldest representation. Any independently
    // stored v1/v2 record wins; embedded data only fills missing keys.
    for (const domain of ['relations', 'summaries', 'groups', 'assets']) {
      for (const [key, value] of Object.entries(embeddedState[domain])) {
        if (!Object.prototype.hasOwnProperty.call(migratedState[domain], key)) {
          migratedState[domain][key] = value
        }
      }
    }

    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        this._replaceCrossNodeState(migratedState)
        this.yNodes.forEach(yNode => {
          const yData = yNode.get('data')
          if (!yData) return
          for (const key of CROSS_NODE_DATA_KEYS) yData.delete(key)
        })
        this.yMeta.set('crossNodeSchemaVersion', CROSS_NODE_SCHEMA_VERSION)
      }, 'local-cross-node-migration')
    } finally {
      this._localYjsChange = false
    }
    return true
  }

  syncDocumentMeta(document = {}, clientMutationId = null) {
    if (this.readonly || this._paused || this._destroyed) return
    if (!this.hasData() && !this.isSynced.value) {
      this._pendingPreSyncChanges.push({
        kind: 'meta',
        document,
        clientMutationId,
      })
      return
    }
    this._applyDocumentMetaChange(document, clientMutationId)
  }

  _applyDocumentMetaChange(document = {}, clientMutationId = null) {
    this._localYjsChange = true
    try {
      this._withOutgoingClientMutationId(clientMutationId, () => {
        this.doc.transact(() => this._writeDocumentMeta(document), 'local-meta')
      })
    } finally {
      this._localYjsChange = false
    }
  }

  /** 将当前完整脑图写入 Yjs（初始化或文档重置时调用）。 */
  initFromMindmap(document, clientMutationId = null) {
    if (this.readonly || this._paused || this._destroyed) return
    const fullDocument = document?.root ? document : { root: document }
    const flat = flattenMindmapTree(fullDocument.root)
    const definitions = this._captureTagDefinitions(fullDocument)
    const crossNodeState = extractCrossNodeState(fullDocument)

    this._localYjsChange = true
    try {
      this._withOutgoingClientMutationId(clientMutationId, () => {
        this.doc.transact(() => {
          replaceYMapEntries(this.yTagDefinitions, Object.fromEntries(definitions))
          this._replaceCrossNodeState(crossNodeState)
          for (const uid of Array.from(this.yNodes.keys())) {
            if (!flat[uid]) this.yNodes.delete(uid)
          }
          for (const [uid, nodeInfo] of Object.entries(flat)) {
            let yNode = this.yNodes.get(uid)
            if (!yNode) {
              yNode = new Y.Map()
              yNode.set('data', new Y.Map())
              yNode.set('children', new Y.Array())
              this.yNodes.set(uid, yNode)
            }
            replaceYMapEntries(yNode.get('data'), stripCrossNodeData(nodeInfo.data || {}))
            replaceYArrayValues(yNode.get('children'), nodeInfo.children || [])
            setYMapValueIfChanged(yNode, 'parentUid', nodeInfo.parentUid)
            this.yNodeLedger.set(uid, true)
          }
          synchronizeYjsParentUids(
            this.yNodes,
            fullDocument.root?.data?.uid,
          )
          this._writeDocumentMeta(fullDocument)
          this.yMeta.set('crossNodeSchemaVersion', CROSS_NODE_SCHEMA_VERSION)
          this._ensureYjsLineageId()
        }, 'init')
      })
    } finally {
      this._localYjsChange = false
    }
    this._runtimeCrossNodeState = crossNodeState
    this._runtimeNodeState = captureRuntimeNodeState(fullDocument)
  }

  /** 监听 simple-mind-map 的 data_change_detail 事件，翻译为 Yjs 操作 */
  onDataChangeDetail(detailList, clientMutationId = null) {
    if (!detailList || !detailList.length) return
    if (this.readonly || this._paused || this._destroyed) return
    // 唯一协作基线尚未确定时不能在空 Y.Doc 中物化局部节点。尤其是 create
    // 会让 hasData() 提前变真，从而跳过种子租约并把残缺树广播给整个房间。
    // 先保留操作顺序；收到持久化/在线种子后再重放，若当前连接获得种子
    // 租约，则直接从包含这些修改的实时画布建立完整文档。
    if (!this.hasData() && !this.isSynced.value) {
      this._pendingPreSyncChanges.push({
        kind: 'detail',
        detailList,
        clientMutationId,
      })
      return
    }
    this._applyDataChangeDetail(detailList, clientMutationId)
  }

  _applyDataChangeDetail(
    detailList,
    clientMutationId = null,
    {
      currentRuntimeDocument = null,
      applyNodeChanges = true,
      applyCrossNodeChanges = true,
      advanceRuntimeShadows = true,
    } = {},
  ) {
    const touchesCrossNodeState = applyCrossNodeChanges
      && detailListTouchesCrossNodeState(detailList)
    // Most data_change_detail events are keystrokes or node-style edits. Do
    // not clone/flatten the complete canvas for those hot-path operations;
    // only cross-node derivation needs a whole rendered document snapshot.
    const resolvedRuntimeDocument = currentRuntimeDocument || (
      touchesCrossNodeState || (advanceRuntimeShadows && !this._runtimeNodeState)
        ? this.mindMap?.getData?.(true)
        : null
    )
    const nextRuntimeCrossNodeState = (
      advanceRuntimeShadows && touchesCrossNodeState
    ) ? captureRuntimeCrossNodeState(resolvedRuntimeDocument) : null
    const nextRuntimeNodeState = (
      advanceRuntimeShadows && resolvedRuntimeDocument
    ) ? captureRuntimeNodeState(resolvedRuntimeDocument) : null
    let crossNodeStateDelta = null
    let crossNodeDeltaSafe = true
    let transactionCompleted = false
    this._localYjsChange = true
    try {
      this._pendingStructuredPatch = this._buildStructuredPatch(detailList)
      if (
        touchesCrossNodeState
      ) {
        try {
          if (!resolvedRuntimeDocument || !nextRuntimeCrossNodeState) {
            throw new TypeError('Cross-node runtime snapshot is unavailable')
          }
          crossNodeStateDelta = buildCrossNodeStateDelta(
            detailList,
            resolvedRuntimeDocument,
            this._readCrossNodeState(),
            this._runtimeCrossNodeState,
          )
        } catch {
          // Third-party plugins may temporarily expose non-cloneable values in
          // relation metadata. Keep the ordinary node edit, but neither write
          // an inferred cross-record patch nor advance its runtime baseline.
          crossNodeDeltaSafe = false
        }
      }
      this._withOutgoingClientMutationId(clientMutationId, () => this.doc.transact(() => {
        for (const detail of (applyNodeChanges ? detailList : [])) {
          const uid = detail.data?.data?.uid
            || detail.data?.uid
            || detail.oldData?.data?.uid
            || detail.oldData?.uid
          if (!uid) continue
          const runtimePreviousNode = this._runtimeNodeState?.[String(uid)] || null

          switch (detail.action) {
            case 'create': {
              this._captureTagDefinitions(detail.data, true)
              const yNode = new Y.Map()
              // 先接入 Y.Doc，再读写嵌套类型。未接入文档的 Y.Map 不可读取，
              // 否则 Yjs 会告警且创建节点的结构化状态可能处于半初始化状态。
              this.yNodes.set(uid, yNode)
              const yData = new Y.Map()
              yNode.set('data', yData)
              const yChildren = new Y.Array()
              yNode.set('children', yChildren)
              replaceYMapEntries(
                yData,
                stripCrossNodeData(normalizeNodeDataForYjs(detail.data?.data || {})),
              )
              replaceYArrayValues(
                yChildren,
                (detail.data?.children || []).map(child => child.data?.uid).filter(Boolean),
              )
              yNode.set('parentUid', '')
              this.yNodeLedger.set(uid, true)
              break
            }

            case 'update': {
              this._captureTagDefinitions(detail.data, true)
              const yNode = this.yNodes.get(uid)
              if (yNode) {
                const yData = yNode.get('data')
                if (yData && detail.data?.data) {
                  // Command details contain complete node snapshots. Apply only
                  // fields changed from oldData so a DOM text commit cannot
                  // roll an already-received remote style/property back.
                  applyLocalNodeDataDelta(yData, detail, runtimePreviousNode)
                }
                if (Array.isArray(detail.data?.children)) {
                  applyLocalNodeChildrenDelta(
                    yNode.get('children'),
                    detail,
                    runtimePreviousNode,
                  )
                }
              }
              break
            }

            case 'delete': {
              deleteYjsSubtree(this.yNodes, uid)
              break
            }
          }
        }
        synchronizeYjsParentUids(this.yNodes, this._getPreferredRootUid())
        if (crossNodeStateDelta) {
          this._applyCrossNodeStateDelta(crossNodeStateDelta)
          this.yMeta.set('crossNodeSchemaVersion', CROSS_NODE_SCHEMA_VERSION)
        }
      }, LOCAL_NODE_DETAIL_ORIGIN))
      transactionCompleted = true
    } finally {
      this._pendingStructuredPatch = null
      this._localYjsChange = false
    }
    if (
      transactionCompleted
      && advanceRuntimeShadows
      && touchesCrossNodeState
      && crossNodeDeltaSafe
      && nextRuntimeCrossNodeState
    ) {
      this._runtimeCrossNodeState = nextRuntimeCrossNodeState
    }
    if (transactionCompleted && advanceRuntimeShadows) {
      const advancedNodeState = nextRuntimeNodeState
        || advanceRuntimeNodeState(this._runtimeNodeState, detailList)
      if (advancedNodeState) {
        this._runtimeNodeState = advancedNodeState
      } else {
        // A malformed plugin snapshot must never leave a plausible-but-stale
        // before-state that could later be mistaken for the user's intent.
        this._runtimeNodeState = null
      }
    }
  }

  _flushPendingPreSyncChanges() {
    if (!this.hasData() || this.readonly || this._destroyed) return false
    const pending = this._pendingPreSyncChanges
    this._pendingPreSyncChanges = []
    const finalRuntimeDocument = this.mindMap?.getData?.(true)
    const allDetailChanges = []
    let finalDetailMutationId = null
    for (const change of pending) {
      if (change.kind === 'detail') {
        allDetailChanges.push(...change.detailList)
        finalDetailMutationId = change.clientMutationId
        // Every queued detail already sees the same final runtime canvas.
        // Replay node deltas under their original mutation IDs, but do not
        // advance the runtime shadow or infer cross-node state per item.
        this._applyDataChangeDetail(change.detailList, change.clientMutationId, {
          currentRuntimeDocument: finalRuntimeDocument,
          applyCrossNodeChanges: false,
          advanceRuntimeShadows: false,
        })
      } else if (change.kind === 'meta') {
        this._applyDocumentMetaChange(change.document, change.clientMutationId)
      }
    }
    if (allDetailChanges.length) {
      // Cross-node records are derived from the final canvas once, using the
      // shadow from before the whole pre-sync queue. This avoids the first
      // ordinary update hiding a later relation/summary change.
      this._applyDataChangeDetail(allDetailChanges, finalDetailMutationId, {
        currentRuntimeDocument: finalRuntimeDocument,
        applyNodeChanges: false,
      })
    }
    return pending.length > 0
  }

  /**
   * 旧客户端可能分别初始化了同名嵌套 Y.Map，单独增量无法可靠覆盖该冲突。
   * 仅附带本次操作涉及节点的权威快照，避免向所有协作者广播完整文档。
   */
  _buildStructuredPatch(detailList) {
    const nodes = new Map()
    const deletedNodeUids = new Set()
    for (const detail of detailList) {
      const uid = String(detail?.data?.data?.uid || detail?.oldData?.uid || '').trim()
      if (!uid || uid.length > MAX_STRUCTURED_PATCH_UID_LENGTH) continue
      if (detail.action === 'delete') {
        deletedNodeUids.add(uid)
        nodes.delete(uid)
        continue
      }
      if (!['create', 'update'].includes(detail.action) || !detail.data?.data) continue
      const children = (detail.data.children || [])
        .map(child => String(child?.data?.uid || '').trim())
        .filter(childUid => childUid && childUid.length <= MAX_STRUCTURED_PATCH_UID_LENGTH)
      const oldNode = detail.oldData
      const previousDataSource = (
        oldNode
        && typeof oldNode === 'object'
        && !Array.isArray(oldNode)
        && Array.isArray(oldNode.children)
        && oldNode.data
        && typeof oldNode.data === 'object'
        && !Array.isArray(oldNode.data)
      ) ? oldNode.data : oldNode
      const previousChildren = Array.isArray(oldNode?.children)
        ? oldNode.children
          .map(child => String(child?.data?.uid || '').trim())
          .filter(childUid => childUid && childUid.length <= MAX_STRUCTURED_PATCH_UID_LENGTH)
        : undefined
      nodes.set(uid, {
        uid,
        data: stripCrossNodeData(normalizeNodeDataForYjs(detail.data.data)),
        children,
        ...(detail.action === 'update' ? {
          ...(previousDataSource && typeof previousDataSource === 'object' ? {
            previousData: stripCrossNodeData(normalizeNodeDataForYjs(previousDataSource)),
          } : {}),
          ...(previousChildren === undefined ? {} : { previousChildren }),
        } : {}),
      })
      deletedNodeUids.delete(uid)
    }
    if (!nodes.size && !deletedNodeUids.size) return null
    const patch = {
      schemaVersion: 1,
      nodes: Array.from(nodes.values()),
      deletedNodeUids: Array.from(deletedNodeUids),
      applyMeta: false,
    }
    // 节点扩展数据可能由 simple-mind 插件提供。补丁只是兼容期修复快照；
    // 不适合 JSON 传输时省略它，真实 Yjs 增量和后续检查点仍必须发送。
    return isStructuredPatchTransportSafe(patch) ? patch : null
  }

  _normalizeStructuredPatch(patch) {
    if (!patch || patch.schemaVersion !== 1 || !Array.isArray(patch.nodes)) return null
    if (!Array.isArray(patch.deletedNodeUids)) return null
    if (
      patch.nodes.length > MAX_STRUCTURED_PATCH_NODE_COUNT
      || patch.deletedNodeUids.length > MAX_STRUCTURED_PATCH_NODE_COUNT
    ) return null

    const nodes = []
    let childCount = 0
    for (const node of patch.nodes) {
      const uid = typeof node?.uid === 'string' ? node.uid.trim() : ''
      if (
        !uid
        || uid.length > MAX_STRUCTURED_PATCH_UID_LENGTH
        || !node.data
        || typeof node.data !== 'object'
        || Array.isArray(node.data)
        || !Array.isArray(node.children)
      ) return null
      const children = []
      for (const value of node.children) {
        const childUid = typeof value === 'string' ? value.trim() : ''
        if (!childUid || childUid.length > MAX_STRUCTURED_PATCH_UID_LENGTH) return null
        children.push(childUid)
      }
      childCount += children.length
      if (childCount > MAX_STRUCTURED_PATCH_CHILD_COUNT) return null
      let previousData
      if (node.previousData !== undefined) {
        if (
          !node.previousData
          || typeof node.previousData !== 'object'
          || Array.isArray(node.previousData)
        ) return null
        previousData = node.previousData
      }
      let previousChildren
      if (node.previousChildren !== undefined) {
        if (!Array.isArray(node.previousChildren)) return null
        previousChildren = []
        for (const value of node.previousChildren) {
          const childUid = typeof value === 'string' ? value.trim() : ''
          if (!childUid || childUid.length > MAX_STRUCTURED_PATCH_UID_LENGTH) return null
          previousChildren.push(childUid)
        }
        childCount += previousChildren.length
        if (childCount > MAX_STRUCTURED_PATCH_CHILD_COUNT) return null
      }
      nodes.push({
        uid,
        data: node.data,
        children,
        ...(previousData === undefined ? {} : { previousData }),
        ...(previousChildren === undefined ? {} : { previousChildren }),
      })
    }
    const deletedNodeUids = []
    for (const value of patch.deletedNodeUids) {
      const uid = typeof value === 'string' ? value.trim() : ''
      if (!uid || uid.length > MAX_STRUCTURED_PATCH_UID_LENGTH) return null
      deletedNodeUids.push(uid)
    }
    return {
      schemaVersion: 1,
      nodes,
      deletedNodeUids,
      applyMeta: patch.applyMeta === true,
    }
  }

  _applyStructuredPatch(patch) {
    this.doc.transact(() => {
      // 顶层节点删除由 Yjs update 自身确定性合并。再次按快照无条件删除会
      // 抹掉同 UID 的并发更新，并让两个接收顺序不同的客户端产生分叉。
      for (const node of patch.nodes) {
        let yNode = this.yNodes.get(node.uid)
        let repairedNode = false
        if (!yNode) {
          // 账本记录“这个 UID 曾经属于权威文档”，但节点当前不存在时，
          // Yjs 顶层删除已经赢得了并发竞争。此时兼容补丁不得复活节点；
          // 只有旧文档从未建立过该节点时，才允许用快照修复缺失嵌套类型。
          if (this.yNodeLedger.get(node.uid) === true) continue
          yNode = new Y.Map()
          yNode.set('data', new Y.Map())
          yNode.set('children', new Y.Array())
          this.yNodes.set(node.uid, yNode)
          repairedNode = true
        }
        let yData = yNode.get('data')
        if (!(yData instanceof Y.Map)) {
          yData = new Y.Map()
          yNode.set('data', yData)
          repairedNode = true
        }
        let yChildren = yNode.get('children')
        if (!(yChildren instanceof Y.Array)) {
          yChildren = new Y.Array()
          yNode.set('children', yChildren)
          repairedNode = true
        }
        if (repairedNode) {
          replaceYMapEntries(yData, node.data)
          replaceYArrayValues(yChildren, node.children)
        } else if (node.previousData !== undefined) {
          const keys = new Set([
            ...Object.keys(node.previousData),
            ...Object.keys(node.data),
          ])
          for (const key of keys) {
            const previousHasKey = Object.prototype.hasOwnProperty.call(node.previousData, key)
            const desiredHasKey = Object.prototype.hasOwnProperty.call(node.data, key)
            const previousValue = node.previousData[key]
            const desiredValue = node.data[key]
            // 未变化字段不是本次增量的一部分，不能被整节点快照用来覆盖并发编辑。
            if (
              previousHasKey === desiredHasKey
              && (!previousHasKey || isSameObject(previousValue, desiredValue))
            ) continue
            const currentHasKey = yData.has(key)
            const currentValue = yData.get(key)
            const alreadyApplied = currentHasKey === desiredHasKey
              && (!desiredHasKey || isSameObject(currentValue, desiredValue))
            if (alreadyApplied) continue
            const stillAtPreviousValue = currentHasKey === previousHasKey
              && (!previousHasKey || isSameObject(currentValue, previousValue))
            if (!stillAtPreviousValue) continue
            if (desiredHasKey) yData.set(key, desiredValue)
            else yData.delete(key)
          }
          // Child topology is always derived from the converged Yjs records.
          // Replaying a conditional children snapshot here would create a
          // receiver-local Y.Array rewrite (the transaction is intentionally
          // not rebroadcast), so later moves could diverge across replicas.
        } else {
          // 旧补丁没有前态，无法区分“增量丢失”和“本地并发胜出”。仅补
          // 缺失字段，不再破坏已由 Yjs 收敛的现有值；检查点/云端版本负责兜底。
          for (const [key, value] of Object.entries(node.data)) {
            if (!yData.has(key)) yData.set(key, value)
          }
        }
        // 修复补丁可能是在增量中对应节点缺失时唯一成功落地的完整快照。
        // 同步写入账本，避免该自愈节点在下次握手完整性校验中又被误判为
        // “从未存在”，导致反复隔离同一份可用协作状态。
        setYMapValueIfChanged(this.yNodeLedger, node.uid, true)
      }
    }, 'remote')
  }

  /** 从 Yjs 扁平节点重建 simple-mind-map 树形结构 */
  _rebuildTreeFromYjs({
    applyCrossNode = true,
    sourceDoc = this.doc,
    applyTagDefinitions = true,
  } = {}) {
    const yMeta = sourceDoc.getMap('meta')
    const yNodes = sourceDoc.getMap('nodes')
    const {
      rootUid,
      childrenByParent,
    } = deriveNormalizedYjsTopology(
      yNodes,
      this._getPreferredRootUid(),
    )
    const nodes = {}
    yNodes.forEach((yNode, uid) => {
      const yData = yNode.get('data')
      nodes[uid] = {
        data: yData ? Object.fromEntries(yData.entries()) : {},
        children: [],
        _childUids: childrenByParent.get(String(uid)) || [],
      }
    })

    if (!rootUid || !nodes[rootUid]) return null

    // 显式 DFS 栈保留按路径循环检测语义，同时避免深链脑图耗尽
    // JavaScript 调用栈。activePath 在退出分支时释放，因此异常 DAG
    // 中同一节点被不同父级引用时仍与旧实现一样各自生成一份视图。
    const rootNode = nodes[rootUid]
    const tree = { data: rootNode.data, children: [] }
    const activePath = new Set([rootUid])
    const pending = [{ uid: rootUid, output: tree, childIndex: 0 }]
    while (pending.length) {
      const frame = pending[pending.length - 1]
      const source = nodes[frame.uid]
      if (frame.childIndex >= source._childUids.length) {
        activePath.delete(frame.uid)
        pending.pop()
        continue
      }
      const childUid = String(source._childUids[frame.childIndex])
      frame.childIndex += 1
      const child = nodes[childUid]
      if (!child || activePath.has(childUid)) continue
      const childOutput = { data: child.data, children: [] }
      frame.output.children.push(childOutput)
      activePath.add(childUid)
      pending.push({ uid: childUid, output: childOutput, childIndex: 0 })
    }
    if (applyCrossNode && Number(yMeta.get('crossNodeSchemaVersion')) >= 1) {
      applyCrossNodeState(tree, this._readCrossNodeState(sourceDoc))
    }
    if (applyTagDefinitions) this._applyTagDefinitions(tree)
    return tree
  }

  _readDocumentMeta() {
    const meta = {
      layout: this.yMeta.get('layout'),
      theme: this.yMeta.get('theme'),
    }
    if (this.yMeta.has('documentData')) meta.documentData = this.yMeta.get('documentData')
    return meta
  }

  _yjsDocumentMatchesCurrentCanvas() {
    // 重连会补发完整 Yjs 状态。不同客户端即使拥有完全相同的脑图，Yjs
    // 内部结构和状态向量也可能不同，因此不能用二进制 update 是否为空
    // 判断“是否有未确认修改”；只比较用户可见的节点与正文配置。
    if (!this.hasData()) return true
    const yjsTree = this._rebuildTreeFromYjs()
    const currentDocument = this.mindMap?.getData?.(true)
    const currentTree = currentDocument?.root || currentDocument
    const yjsSnapshot = this._createSemanticTreeSnapshot(yjsTree)
    const currentSnapshot = this._createSemanticTreeSnapshot(currentTree)
    if (
      !yjsTree
      || !currentTree
      || !isSameObject(yjsSnapshot.tree, currentSnapshot.tree)
      || !isSameObject(
        yjsSnapshot.crossNodeState,
        currentSnapshot.crossNodeState,
      )
    ) return false

    const currentDocumentData = this.options.getDocumentData?.()
      ?? currentDocument?.documentData
      ?? currentDocument?.document_data
    const semanticMeta = [
      ['layout', currentDocument?.layout],
      ['theme', currentDocument?.theme],
      ['documentData', currentDocumentData],
    ]
    return semanticMeta.every(([key, currentValue]) => (
      !this.yMeta.has(key) || isSameObject(this.yMeta.get(key), currentValue)
    ))
  }

  _requestYjsApply({ applyMeta = false } = {}) {
    if (
      this._destroyed
      || !this.mindMap
      || this._authoritativeRevisionPending !== null
    ) return
    if (this._paused) {
      this._pendingRemoteApply = true
      this._pendingRemoteApplyMeta ||= applyMeta
      return
    }
    if (this._applyingRemote || this._preparingRemote) {
      this._pendingRemoteApply = true
      this._pendingRemoteApplyMeta ||= applyMeta
      return
    }
    applyMeta ||= this._pendingRemoteApplyMeta
    this._pendingRemoteApply = false
    this._pendingRemoteApplyMeta = false
    clearTimeout(this._remotePrepareRetryTimer)
    this._remotePrepareRetryTimer = null
    void this._applyYjsToMindmap({ applyMeta }).catch(error => {
      if (this._destroyed) return
      this.syncError.value = error?.message || '应用协作内容失败'
    })
  }

  _beginRemoteApplication() {
    this._applyingRemote = true
    clearTimeout(this._remoteApplyFallbackTimer)
    clearTimeout(this._remoteApplyReleaseTimer)
    if (this._remoteRenderEndHandler) {
      this.mindMap?.off?.('node_tree_render_end', this._remoteRenderEndHandler)
    }

    let releaseScheduled = false
    const scheduleRelease = () => {
      if (releaseScheduled) return
      releaseScheduled = true
      clearTimeout(this._remoteApplyFallbackTimer)
      this.mindMap?.off?.('node_tree_render_end', this._remoteRenderEndHandler)
      this._remoteRenderEndHandler = null
      // render_end 的同一调用栈仍可能继续派发 data_change/view_data_change。
      this._remoteApplyReleaseTimer = setTimeout(() => {
        this._finishRemoteApplication()
      }, 0)
    }
    this._remoteRenderEndHandler = scheduleRelease
    this.mindMap?.on?.('node_tree_render_end', scheduleRelease)
    // 异常插件不能让同步保护永久挂起。
    this._remoteApplyFallbackTimer = setTimeout(scheduleRelease, 2000)
    return scheduleRelease
  }

  _finishRemoteApplication() {
    this._applyingRemote = false
    this._remoteApplyFallbackTimer = null
    this._remoteApplyReleaseTimer = null
    if (this._destroyed || !this._pendingRemoteApply) return
    const applyMeta = this._pendingRemoteApplyMeta
    this._pendingRemoteApply = false
    this._pendingRemoteApplyMeta = false
    this._requestYjsApply({ applyMeta })
  }

  _scheduleDocumentPrepareRetry(applyMeta) {
    // A cloud-authoritative refresh owns the canvas while its revision fence
    // is active. A rejected renderer promise from the superseded Y.Doc must
    // not queue that stale document again or overwrite the recovery status.
    if (
      this._destroyed
      || this._paused
      || this._authoritativeRevisionPending !== null
      || this._remotePrepareRetryTimer
    ) return false
    this._pendingRemoteApply = true
    this._pendingRemoteApplyMeta ||= applyMeta
    const delays = Array.isArray(this.options.documentPrepareRetryDelays)
      ? this.options.documentPrepareRetryDelays
      : DOCUMENT_PREPARE_RETRY_DELAYS
    if (this._remotePrepareRetryAttempt >= delays.length) {
      this.syncError.value = DOCUMENT_PREPARE_EXHAUSTED_ERROR
      this.options.onDocumentPrepareExhausted?.()
      return false
    }
    const delay = Math.max(0, Number(delays[this._remotePrepareRetryAttempt]) || 0)
    this._remotePrepareRetryAttempt += 1
    this._remotePrepareRetryTimer = setTimeout(() => {
      this._remotePrepareRetryTimer = null
      this._requestYjsApply()
    }, delay)
    return true
  }

  async _applyYjsToMindmap({ applyMeta = false } = {}) {
    if (
      this._destroyed
      || !this.mindMap
      || this._authoritativeRevisionPending !== null
    ) return false
    if (this._applyingRemote || this._preparingRemote) {
      this._pendingRemoteApply = true
      this._pendingRemoteApplyMeta ||= applyMeta
      return false
    }
    const targetMindMap = this.mindMap
    const buildDocument = () => {
      const tree = this._rebuildTreeFromYjs()
      if (!tree) return null
      let appliedMeta = null
      let document = { root: tree }
      if (applyMeta) {
        const current = targetMindMap.getData?.(true) || {}
        appliedMeta = this._readDocumentMeta()
        document = {
          root: tree,
          layout: appliedMeta.layout ?? current.layout,
          theme: appliedMeta.theme ?? current.theme,
          view: appliedMeta.view ?? current.view,
        }
      }
      return { tree, appliedMeta, document }
    }
    let preparedDocument = buildDocument()
    if (!preparedDocument) return false

    if (typeof this.options.prepareDocument === 'function') {
      try {
        // 只有回调真实返回 Promise（例如首次加载 KaTeX）才进入等待状态。
        // 等待期间本地编辑仍正常写入 Yjs；状态向量变化后重新构建并准备
        // 最新文档，避免用等待前的快照覆盖用户输入或后续远端更新。
        while (true) {
          const stateVector = Y.encodeStateVector(this.doc)
          const preparation = this.options.prepareDocument(
            preparedDocument.document,
            targetMindMap,
          )
          if (!preparation || typeof preparation.then !== 'function') break
          this._preparingRemote = true
          try {
            await preparation
          } finally {
            this._preparingRemote = false
          }
          if (
            this._destroyed
            || this._authoritativeRevisionPending !== null
          ) return false
          const stateChanged = !uint8ArraysEqual(stateVector, Y.encodeStateVector(this.doc))
          const queuedApply = this._pendingRemoteApply
          if (!stateChanged && !queuedApply) break
          applyMeta ||= this._pendingRemoteApplyMeta
          this._pendingRemoteApply = false
          this._pendingRemoteApplyMeta = false
          preparedDocument = buildDocument()
          if (!preparedDocument) return false
        }
        if (this._documentPrepareFailed) {
          this._documentPrepareFailed = false
          if (
            this.syncError.value === DOCUMENT_PREPARE_ERROR
            || this.syncError.value === DOCUMENT_PREPARE_EXHAUSTED_ERROR
          ) this.syncError.value = ''
          this.options.onDocumentPrepareRecovered?.()
        }
        this._remotePrepareRetryAttempt = 0
      } catch (error) {
        if (
          !this._destroyed
          && !this._paused
          && this._authoritativeRevisionPending === null
          && this.mindMap === targetMindMap
        ) {
          this._documentPrepareFailed = true
          this.syncError.value = DOCUMENT_PREPARE_ERROR
          this.options.onDocumentPrepareError?.(error)
          this._scheduleDocumentPrepareRetry(applyMeta)
        }
        return false
      }
    }

    if (this._authoritativeRevisionPending !== null) return false
    if (this._destroyed || this._paused || this.mindMap !== targetMindMap) {
      if (!this._destroyed) {
        this._pendingRemoteApply = true
        this._pendingRemoteApplyMeta ||= applyMeta
      }
      return false
    }

    // isActive 是当前客户端的 UI 状态，不属于共享文档。Yjs 回放可能由
    // 本地刚完成的编辑或远端协作者触发，渲染前必须以本地 awareness
    // 选区覆盖协作树，否则连续 Enter/Tab 后的异步刷新会清掉选中标记。
    applyLocalActiveNodeState(
      preparedDocument.tree,
      this._localActiveNodeUids,
    )

    // 浮层文本编辑器的最终输入通常只存在 DOM 中，直到编辑器被关闭才会
    // 写回 simple-mind-map。上层必须有机会在远端树替换画布前同步提交并
    // 保护这段输入，尤其是协作者恰好删除了当前正在编辑的节点时。
    const beforeApplyResult = this.options.beforeRemoteDocumentApply?.(
      preparedDocument.tree,
      targetMindMap,
      preparedDocument.document,
    )
    if (beforeApplyResult === 'local-edit-committed') {
      // 关闭浮层会把最后输入同步写入当前 Y.Doc。旧 preparedDocument 已
      // 失效，下一微任务从合并后的 Yjs 状态重建，不能先覆盖一遍旧树。
      this._pendingRemoteApply = true
      this._pendingRemoteApplyMeta ||= applyMeta
      setTimeout(() => {
        if (!this._destroyed && !this._paused) this._requestYjsApply()
      }, 0)
      return false
    }

    // The preparation or editor-protection callback may synchronously start a
    // cloud-authoritative recovery. Never let its older staged Y.Doc cross the
    // fence or advance the runtime shadows.
    if (this._authoritativeRevisionPending !== null) return false

    const scheduleRelease = this._beginRemoteApplication()
    let protectedDocument = null
    try {
      // renderer 可能在 setFullData/updateData 中途抛错并留下半应用 runtime。
      // 必须在第一次写入前冻结完整旧文档，错误回调不能再从损坏后的画布取值。
      protectedDocument = typeof this.options.captureDocumentBeforeRemoteApply === 'function'
        ? this.options.captureDocumentBeforeRemoteApply(targetMindMap)
        : targetMindMap.getData?.(true)
      // 节点增量也统一经过运行时状态保护。node_active 使用 0ms 防抖，
      // 协作回放可能先到；此时需从正在编辑的节点补回本地选区。
      this._mutatingMindmapFromRemote = true
      try {
        applyAuthoritativeMindmapDocument(
          targetMindMap,
          applyMeta ? preparedDocument.document : { root: preparedDocument.tree },
        )
      } finally {
        this._mutatingMindmapFromRemote = false
      }
      this._runtimeCrossNodeState = extractCrossNodeState(preparedDocument.tree)
      this._runtimeNodeState = captureRuntimeNodeState(preparedDocument.tree)
      this.options.onDocumentApplied?.(
        preparedDocument.tree,
        preparedDocument.appliedMeta,
      )
      // 只有脑图运行时已经接受这批 Yjs 状态，才能同步推进对应的数据库
      // revision。网络“收到”不等于用户画布“已应用”，尤其首次加载插件时
      // 两者之间可能存在异步窗口。
      this._markPendingRemoteMutationsApplied()
      return true
    } catch (error) {
      this._mutatingMindmapFromRemote = false
      scheduleRelease()
      try {
        const recovery = this.options.onDocumentApplyError?.(error, {
          protectedDocument,
          targetMindMap,
          sourceSync: this,
        })
        if (recovery && typeof recovery.then === 'function') {
          void recovery.catch(callbackError => {
            if (!this._destroyed) {
              this.syncError.value = callbackError?.message || '协作画布恢复失败'
            }
          })
        }
      } catch (callbackError) {
        if (!this._destroyed) {
          this.syncError.value = callbackError?.message || '协作画布恢复失败'
        }
      }
      throw error
    }
  }

  _handleSyncInit(data) {
    if (this._destroyed || this._authoritativeRevisionPending !== null) return
    const snapshotRevision = Number(data?.contentRevision)
    const hasSnapshotRevision = Number.isInteger(snapshotRevision) && snapshotRevision > 0
    if (hasSnapshotRevision && snapshotRevision < this.contentRevision) return
    const snapshotRevisionAdvanced = hasSnapshotRevision
      && snapshotRevision > this.contentRevision
    const states = Array.isArray(data.states) && data.states.length
      ? data.states
      : [data.state]
    const hadLocalData = this.hasData()
    const staged = stagePersistedYjsStates(
      states,
      data.stateSources,
      data.stateDigests,
    )
    const persistedLineageConflict = !this._persistedUpdatesHaveSingleLineage(
      staged.acceptedUpdates,
    )
    const rejectsAuthoritativeBaseline = Boolean(staged.mergedUpdate && (
      persistedLineageConflict
      || this._isInitialNodeStateIncomplete(staged.mergedUpdate)
      || !this._persistedStateMatchesInitialAuthoritativeDocument(
        staged.mergedUpdate,
      )
    ))
    const localLineageConflict = Boolean(
      hadLocalData
      && staged.mergedUpdate
      && !rejectsAuthoritativeBaseline
      && !this._updateSharesCurrentNodeLineage(staged.mergedUpdate)
    )
    const rejectedBaselineSources = rejectsAuthoritativeBaseline
      ? staged.acceptedSourceIds
      : []
    const invalidSourceIds = [
      ...new Set([...staged.invalidSourceIds, ...rejectedBaselineSources]),
    ]
    const invalidStateCount = staged.invalidStateCount + (
      rejectsAuthoritativeBaseline ? Math.max(1, rejectedBaselineSources.length) : 0
    )
    if (snapshotRevisionAdvanced) {
      // HTTP 详情与 WebSocket 握手之间可能已有其他协作者完成保存。没有
      // 对应新 revision 的完整 Yjs 状态时，绝不能仅抬高版本号后用旧 HTTP
      // 画布播种，否则会把旧树伪装成新基线并覆盖刚保存的云端内容。
      // 重连客户端即便拿到了完整状态也不能把它合入旧 revision 的非空
      // Y.Doc：客户端离线期间可能发生过权威重置，而 Yjs update 只有合并
      // 语义、没有替换语义，会复活已经从新基线删除的旧节点。统一回源后
      // 由编辑器销毁旧 Doc，再以新 HTTP 正文创建全新的同步实例。
      this._handleStaleState({
        ...data,
        contentRevision: snapshotRevision,
        message: '云端内容在协作初始化期间已更新，正在加载最新版本',
        reason: 'handshake_revision_advanced',
      })
      return
    }
    if (hadLocalData && (rejectsAuthoritativeBaseline || localLineageConflict)) {
      // 重连实例不能自行选择本地或缓存中的某条独立 Yjs 创建历史，更不能
      // 直接用本地 checkpoint 覆盖另一条仍被其他浏览器使用的 lineage。
      // 先由上层重新 GET 权威正文并销毁当前 Doc；新空 Doc 随后接纳唯一
      // 合法缓存，或在缓存损坏时通过种子租约建立全新基线。
      this._handleStaleState({
        ...data,
        contentRevision: this.contentRevision,
        message: '检测到协作基线已分叉，正在从云端安全重建',
        reason: localLineageConflict
          ? 'yjs_lineage_changed'
          : 'persisted_yjs_state_invalid',
      })
      return
    }
    this._localYjsChange = true
    try {
      if (
        staged.mergedUpdate
        && !rejectsAuthoritativeBaseline
      ) {
        Y.applyUpdate(this.doc, staged.mergedUpdate, 'remote')
      }
      this.doc.transact(() => {
        if (this.hasData()) this._ensureYjsLineageId()
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
    this._normalizeEmbeddedCrossNodeState()
    if (
      staged.mergedUpdate
      && !rejectsAuthoritativeBaseline
      && !hadLocalData
      && !this._yjsDocumentMatchesCurrentCanvas()
    ) {
      this._hasLegacyUnconfirmedRemoteState = true
      this._refreshUnconfirmedRemoteState()
      this._scheduleLegacyUnconfirmedMutationCheck(data)
    }
    this._rememberPendingCheckpointConsolidation(
      rejectsAuthoritativeBaseline ? [] : staged.acceptedSourceIds,
      invalidSourceIds,
      staged.sourceDigests,
    )
    if (this.hasData()) {
      this._flushPendingPreSyncChanges()
      // 队列重放可能发现 mutation 已在 HTTP 冻结边界封存，并在事务观察器
      // 中触发 stale。该状态是单调权威栅栏；后续握手步骤不得继续应用
      // Yjs 画布或把连接重新标记为 connected。
      if (this._authoritativeRevisionPending !== null) return
      this._requestYjsApply({ applyMeta: true })
      if (!this._completeSyncHandshake(true, { repairTagDefinitions: true })) return
      // 当前完整检查点已经包含握手接受的全部来源，可以原子替换这些旧副本。
      // 新来源若在并发窗口写入，服务端不会出现在 replacesSources 中，仍会保留。
      this._flushPendingCheckpointConsolidation()
    } else if (this.readonly) {
      this._completeReadonlyHandshake()
    } else {
      // 全部损坏、仅有元数据或节点树不完整都不再由每个加入者各自补树。
      // 统一竞争种子租约，确保同名嵌套 Yjs 类型只由一个客户端创建。
      this.connectionState.value = 'syncing'
      this.syncError.value = '正在等待唯一协作种子重建完整画布'
      this._requestSeedLease()
    }
    if (
      invalidStateCount
      && (
        this._pendingCheckpointInvalidSources.length > 0
        || !this.hasData()
      )
    ) {
      this.connectionState.value = 'degraded'
      this.syncError.value = `检测到 ${invalidStateCount} 份异常协作缓存，已隔离并继续同步`
    }
  }

  _handleSeedPending(data) {
    if (this._destroyed || this._authoritativeRevisionPending !== null) return
    const revision = Number(data?.contentRevision)
    if (Number.isInteger(revision) && revision > this.contentRevision) {
      this._handleStaleState({
        ...data,
        contentRevision: revision,
        message: '云端内容在协作初始化期间已更新，正在加载最新版本',
        reason: 'handshake_revision_advanced',
      })
      return
    }
    if (Number.isInteger(revision) && revision < this.contentRevision) return
    // 新连接加入空缓存房间时，其他客户端的权威种子广播可能先于本连接的
    // seed_pending 送达。此时握手已经完成，迟到的等待消息不能把连接状态
    // 从 connected 倒退回 syncing。
    if (this._receivedServerState) return
    if (this.readonly) {
      this._completeReadonlyHandshake()
      return
    }
    this.connectionState.value = 'syncing'
    this.syncError.value = '正在等待房间协作状态'
  }

  _handleSeedRequest(data) {
    if (this._destroyed || this._authoritativeRevisionPending !== null) return
    const revision = Number(data?.contentRevision)
    if (Number.isInteger(revision) && revision > this.contentRevision) {
      this._handleStaleState({
        ...data,
        contentRevision: revision,
        message: '检测到更新的云端协作版本，正在重新同步',
        reason: 'seed_request_revision_advanced',
      })
      return
    }
    if (
      this._destroyed
      || this._paused
      || !this.hasData()
      || (Number.isInteger(revision) && revision !== this.contentRevision)
    ) return
    this._sendFullState()
  }

  _handleSeedGranted(data) {
    if (this._destroyed || this._authoritativeRevisionPending !== null) return
    const revision = Number(data?.contentRevision)
    if (Number.isInteger(revision) && revision > this.contentRevision) {
      this._handleStaleState({
        ...data,
        contentRevision: revision,
        message: '云端内容在协作初始化期间已更新，正在加载最新版本',
        reason: 'handshake_revision_advanced',
      })
      return
    }
    if (Number.isInteger(revision) && revision !== this.contentRevision) return
    if (this.readonly) {
      this._completeReadonlyHandshake()
      return
    }
    if (this.requiresAuthoritativeReconciliation()) {
      // 画布可能包含握手期间已封存、但 HTTP 尚未确认的本地修改。无论
      // Y.Doc 当前是否已有数据，都不能把它作为空房间的权威种子。
      this.isSynced.value = false
      this.connectionState.value = 'syncing'
      this.syncError.value = '正在等待本地修改确认后初始化协作状态'
      return
    }
    if (this.hasData()) {
      // 空缓存房间授予本连接租约时，只有完全无待确认修改的当前云端
      // 副本才能成为权威种子。普通重连握手不再互相合并未知 Yjs
      // lineage；这样不会让败方嵌套 Y.Map 后续更新变成不可见。
      const sent = this._sendFullState({ authoritativeSeed: true })
      if (!sent) {
        // pending HTTP 批次或运行时尚未完成应用时，完整状态还不能被证明为
        // 云端基线。保留 seed 重试计时器和租约，不要伪装成已同步状态。
        this.isSynced.value = false
        this.connectionState.value = 'syncing'
        this.syncError.value = '正在等待本地修改确认后初始化协作状态'
        return
      }
      this._completeSyncHandshake(true)
      this._flushPendingCheckpointConsolidation()
      return
    }
    this._completeSyncHandshake(false)
    this._flushPendingCheckpointConsolidation()
  }

  _handleUpdate(data) {
    if (this._destroyed) return
    const clientMutationId = this._normalizeClientMutationId(data?.clientMutationId)
    const mutationUpdateSeq = this._normalizeMutationUpdateSequence(
      data?.mutationUpdateSeq,
    )
    if (
      clientMutationId
      && this.serverCapabilities.has(YJS_MUTATION_SEQUENCE_CAPABILITY)
      && mutationUpdateSeq === null
    ) {
      this._handleStaleState({
        ...data,
        reason: 'missing_mutation_sequence',
        message: '实时协作批次缺少合法序号，正在从云端校准画布',
      })
      return
    }
    const wasAlreadyConfirmed = clientMutationId
      && this._confirmedRemoteMutationIds.has(clientMutationId)
    const messageRevision = Number(data?.contentRevision)
    if (
      this._authoritativeRevisionPending !== null
      || (
        Number.isInteger(messageRevision)
        && messageRevision !== this.contentRevision
        && !wasAlreadyConfirmed
      )
    ) {
      // 权威重置开始后，旧 revision 的在途增量和断开检查点都必须失效；
      // 已由同 clientMutationId 确认的乱序保存批次仍可补应用到当前画布。
      if (Number.isInteger(messageRevision) && messageRevision > this.contentRevision) {
        this._handleStaleState({
          ...data,
          contentRevision: messageRevision,
          message: '检测到更新的服务器协作状态，正在安全同步',
          reason: 'newer_yjs_revision',
        })
      }
      return
    }
    const confirmedRecord = clientMutationId
      ? this._confirmedRemoteMutationIds.get(clientMutationId)
      : null
    if (confirmedRecord?.notified) {
      // 已提交批次的所有合法帧此前都已应用。迟到重传必须直接丢弃，
      // 不能再次写入结构化 patch；超出 seal 的帧则说明协议已分叉。
      if (
        confirmedRecord.yjsUpdateCount === null
        || (
          mutationUpdateSeq !== null
          && mutationUpdateSeq <= confirmedRecord.yjsUpdateCount
        )
      ) return
      this._handleStaleState({
        ...data,
        contentRevision: confirmedRecord.revision,
        reason: 'committed_mutation_extra_update',
        message: '已提交协作批次收到额外更新，正在从云端校准画布',
      })
      return
    }
    if (
      confirmedRecord
      && Number.isInteger(confirmedRecord.yjsUpdateCount)
      && mutationUpdateSeq !== null
      && mutationUpdateSeq > confirmedRecord.yjsUpdateCount
    ) {
      this._handleStaleState({
        ...data,
        contentRevision: confirmedRecord.revision,
        reason: 'mutation_sequence_overflow',
        message: '实时协作批次在确认后仍收到额外更新，正在从云端校准画布',
      })
      return
    }
    if (wasAlreadyConfirmed && confirmedRecord?.authoritativeReloadRequired) {
      // 本客户端的原始 Yjs 变更已经存在于画布；并发合并后的权威树由
      // HTTP 响应负责应用。远端客户端则必须立即回源，不能应用非权威增量。
      if (this._localMutationIds.has(clientMutationId)) return
      this._handleStaleState({
        ...data,
        contentRevision: data?.contentRevision || this.contentRevision,
        message: '协作内容已在服务器合并，正在加载权威版本',
        reason: 'concurrent_merge',
      })
      return
    }
    // 客户端声明能力不代表服务端已经采用该协议。只有 auth_ok 明确回显
    // 条件补丁能力后才接收修复快照；连接旧服务端时始终退回标准 Yjs。
    const patch = this._supportsConditionalNodePatchProtocol()
      ? this._normalizeStructuredPatch(data.patch)
      : null
    const isAuthoritativeSeedState = Boolean(
      data?.seedState === true
      && !clientMutationId
      && !patch
      && data?.state,
    )
    const incomingLineageId = normalizeYjsLineageId(data?.lineageId)
    // 新协议只广播增量和受影响节点快照；旧服务端仍可提供完整状态自愈。
    const encodedUpdate = patch ? data.update : (data.state || data.update)
    if (!encodedUpdate) return
    let update
    try {
      update = validateRuntimeYjsUpdate(
        encodedUpdate,
        !patch && data.state
          ? MAX_PERSISTED_STATE_BYTES
          : MAX_RUNTIME_UPDATE_BYTES,
      )
    } catch {
      const message = '检测到异常协作更新，已隔离并正在重新同步'
      this.isSynced.value = false
      this.connectionState.value = 'degraded'
      this.syncError.value = message
      this.options.onProtocolError?.({
        code: 'invalid_yjs_update',
        message,
      })
      this.wsClient.reconnect(message)
      return
    }
    if (
      this.serverCapabilities.has(YJS_LINEAGE_CAPABILITY)
      && (clientMutationId || patch)
      && !incomingLineageId
    ) {
      this._handleStaleState({
        ...data,
        reason: 'missing_yjs_lineage',
        message: '协作更新缺少基线标识，正在从云端校准画布',
      })
      return
    }
    const sequenceFingerprintStatus = this._rememberRemoteMutationSequenceFingerprint(
      clientMutationId,
      mutationUpdateSeq,
      encodedUpdate,
      patch,
    )
    if (sequenceFingerprintStatus === 'duplicate') return
    if (
      sequenceFingerprintStatus === 'conflict'
      || sequenceFingerprintStatus === 'capacity'
      || sequenceFingerprintStatus === 'invalid'
    ) {
      this._handleStaleState({
        ...data,
        reason: sequenceFingerprintStatus === 'conflict'
          ? 'mutation_sequence_payload_conflict'
          : 'mutation_sequence_tracking_failed',
        message: sequenceFingerprintStatus === 'conflict'
          ? '同一协作序号携带了不同内容，正在从云端校准画布'
          : '协作序号无法安全跟踪，正在从云端校准画布',
      })
      return
    }
    if (
      !patch
      && !this._receivedServerState
      && this._isInitialNodeStateIncomplete(update)
    ) {
      // 旧标签页可能在权威重置后仍把残缺内存态作为房间种子。不能让它
      // 覆盖刚由 HTTP 加载的完整画布；保留握手计时器并立即争取种子租约，
      // 由当前云端基线重新建立协作状态。
      this.connectionState.value = 'degraded'
      this.syncError.value = '检测到不完整协作状态，正在使用云端内容修复'
      if (this.readonly) this._completeReadonlyHandshake()
      else this._requestSeedLease()
      return
    }
    if (
      isAuthoritativeSeedState
      && !this._persistedStateMatchesInitialAuthoritativeDocument(update)
    ) {
      this._handleStaleState({
        ...data,
        reason: 'authoritative_seed_semantic_mismatch',
        message: '协作种子与云端正文不一致，正在重新加载权威版本',
      })
      return
    }
    const currentLineageId = this._getYjsLineageId()
    if (
      this.hasData()
      && (
        (incomingLineageId && currentLineageId && incomingLineageId !== currentLineageId)
        || !this._updateSharesCurrentNodeLineage(update)
      )
    ) {
      this._handleStaleState({
        ...data,
        reason: 'yjs_lineage_changed',
        message: '检测到另一条协作基线，正在从云端安全重建',
      })
      return
    }
    this._localYjsChange = true
    try {
      Y.applyUpdate(this.doc, update, 'remote')
      if (patch) this._applyStructuredPatch(patch)
      this.doc.transact(() => {
        if (this.hasData()) this._ensureYjsLineageId()
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
    if (!wasAlreadyConfirmed && !isAuthoritativeSeedState) {
      if (clientMutationId) {
        this._unconfirmedRemoteMutationIds.add(clientMutationId)
        this._scheduleUnconfirmedMutationCheck(clientMutationId, data)
      } else if (!this._yjsDocumentMatchesCurrentCanvas()) {
        this._hasLegacyUnconfirmedRemoteState = true
        this._scheduleLegacyUnconfirmedMutationCheck(data)
      }
      this._refreshUnconfirmedRemoteState()
    }
    this._normalizeEmbeddedCrossNodeState()
    if (clientMutationId) {
      this._rememberBoundedMutationId(this._receivedRemoteMutationIds, clientMutationId)
      this._rememberBoundedMutationId(this._pendingRemoteMutationApplyIds, clientMutationId)
      this._rememberPendingRemoteMutationSequence(
        clientMutationId,
        mutationUpdateSeq,
      )
    }
    this._flushPendingPreSyncChanges()
    this._requestYjsApply({ applyMeta: patch?.applyMeta === true || !patch })
    if (!this._receivedServerState && this.hasData()) {
      this._completeSyncHandshake(true)
      this._flushPendingCheckpointConsolidation()
    }
  }

  _handleStaleState(data) {
    const revision = Number(data?.contentRevision ?? data?.currentRevision)
    const pendingRevision = Number.isInteger(this._authoritativeRevisionPending)
      ? this._authoritativeRevisionPending
      : 0
    this._authoritativeRevisionPending = Math.max(
      this.contentRevision,
      pendingRevision,
      Number.isInteger(revision) && revision > 0 ? revision : 0,
    )
    this._clearCheckpoint()
    this._clearConfirmedMutationDeliveryTimers()
    this._clearUnconfirmedMutationTimers()
    this._clearLegacyUnconfirmedMutationTimer()
    this.isSynced.value = false
    this.connectionState.value = 'stale'
    this.syncError.value = data?.message || '协作状态已落后，正在合并最新内容'
    this.options.onStaleState?.(data)
  }

  _handleContentRevisionChanged(data) {
    const revision = Number(data?.contentRevision)
    if (!Number.isInteger(revision)) return
    const clientMutationId = this._normalizeClientMutationId(data?.clientMutationId)
    if (clientMutationId) this._clearUnconfirmedMutationTimer(clientMutationId)
    const isLocalMutation = clientMutationId
      && this._localMutationIds.has(clientMutationId)
    let confirmedRecord = null
    if (clientMutationId) {
      confirmedRecord = this._rememberConfirmedRemoteMutation(
        clientMutationId,
        revision,
        data,
      )
      this._scheduleConfirmedMutationDeliveryCheck(
        clientMutationId,
        revision,
        data,
      )
    }
    // 普通语义保存的广播会要求远端回源，而发起端应等待同一 HTTP
    // 请求返回后再解除本地 mutation 栅栏。若这里抢先确认，检查点定时器
    // 可能在 HTTP 响应前把新正文配上旧 revision 发回服务器，造成一次
    // 无意义的 stale/reload，甚至在异常链路中污染协作缓存。
    if (isLocalMutation && !confirmedRecord?.authoritativeReloadRequired) {
      this.confirmLocalMutation(clientMutationId)
    }
    this._refreshUnconfirmedRemoteState()

    const hasUnconfirmedMutationState = Boolean(
      clientMutationId
      && this._unconfirmedRemoteMutationIds.has(clientMutationId),
    )
    // 跨 worker 广播可能在更高 revision 已经应用后才到达。没有遗留的
    // 同批实时状态时，旧确认只用于建立去重墓碑，绝不能再次把画布打入
    // stale；若确实混入了未确认旧状态，则仍需权威回源清理。
    if (revision < this.contentRevision) {
      if (hasUnconfirmedMutationState) {
        this._handleStaleState({
          ...data,
          contentRevision: this.contentRevision,
          message: '检测到未确认的旧协作状态，正在加载当前云端版本',
          reason: 'obsolete_unconfirmed_mutation',
        })
      } else if (confirmedRecord) {
        confirmedRecord.notified = true
        this._clearConfirmedMutationDeliveryTimer(clientMutationId)
        this._forgetRemoteMutationSequences(clientMutationId)
      }
      return
    }
    if (
      confirmedRecord?.authoritativeReloadRequired
      && !isLocalMutation
    ) {
      // 当前 revision 的重复确认可能在权威 GET 完成后才到达。此时既无
      // 待确认帧也无需要合并的画布状态，直接记为已消费即可。
      if (revision === this.contentRevision && !hasUnconfirmedMutationState) {
        confirmedRecord.notified = true
        this._clearConfirmedMutationDeliveryTimer(clientMutationId)
        this._forgetRemoteMutationSequences(clientMutationId)
        return
      }
      this._handleStaleState({
        ...data,
        contentRevision: revision,
        message: '协作内容已在服务器合并，正在加载权威版本',
        reason: 'concurrent_merge',
      })
      return
    }
    if (this._hasLegacyUnconfirmedRemoteState) {
      if (this._authoritativeRevisionPending === revision) return
      this._handleStaleState({
        ...data,
        contentRevision: revision,
        message: '协作内容需要与服务器已保存版本重新校准',
        reason: 'unconfirmed_yjs_state',
      })
      return
    }
    if (clientMutationId) {
      if (
        revision === this.contentRevision
        && this._isConfirmedMutationReady(clientMutationId, confirmedRecord)
      ) {
        confirmedRecord.notified = true
        this._unconfirmedRemoteMutationIds.delete(clientMutationId)
        this._clearConfirmedMutationDeliveryTimer(clientMutationId)
        this._forgetRemoteMutationSequences(clientMutationId)
        this._refreshUnconfirmedRemoteState()
      }
      this._flushConfirmedMutationRevisions()
      return
    }
    // 兼容没有批次关联标识的旧服务端。新协议必须等待同一 mutation 的
    // Yjs 更新真正应用到画布，旧协议只能继续使用版本心跳式校准。
    if (revision === this.contentRevision) return
    this.contentRevision = revision
    this.options.onContentRevision?.(revision, data)
    this._discardConfirmedMutationsAtOrBelowCurrentRevision()
    this._flushConfirmedMutationRevisions()
  }

  _handleDocumentReset(data) {
    const revision = Number(data?.contentRevision)
    if (
      !Number.isInteger(revision)
      || revision <= this.contentRevision
      || (
        Number.isInteger(this._authoritativeRevisionPending)
        && revision <= this._authoritativeRevisionPending
      )
    ) return
    this._authoritativeRevisionPending = revision
    this._clearCheckpoint()
    this._clearConfirmedMutationDeliveryTimers()
    this._clearUnconfirmedMutationTimers()
    this._clearLegacyUnconfirmedMutationTimer()
    this.isSynced.value = false
    this.connectionState.value = 'syncing'
    this.syncError.value = data?.message || '协作基线已重置，正在加载最新内容'
    this.options.onDocumentReset?.(data)
  }

  _handleRevisionHeartbeat(data) {
    const revision = Number(data?.contentRevision)
    if (
      !Number.isInteger(revision)
      || revision <= this.contentRevision
      || this._authoritativeRevisionPending !== null
    ) return
    // Redis/pubsub 或浏览器网络短暂抖动可能让更新及保存确认同时丢失。
    // 心跳 revision 来自数据库，落后时不能只推进数字而假装已拥有正文。
    this._handleStaleState({
      ...data,
      currentRevision: revision,
      message: '检测到云端存在未送达的协作内容，正在重新同步',
      reason: 'heartbeat_revision_ahead',
    })
  }

  _handleDocumentDeleted(data) {
    this._terminateCollaboration(data, 'deleted', 'onDocumentDeleted')
  }

  _handleDocumentArchived(data) {
    this._terminateCollaboration(data, 'archived', 'onDocumentArchived')
  }

  _handleAccessRevoked(data) {
    this._terminateCollaboration(data, 'access-revoked', 'onAccessRevoked')
  }

  _handleSessionEnded(data) {
    this._terminateCollaboration(data, 'session-ended', 'onSessionEnded')
  }

  _terminateCollaboration(data, state, callbackName) {
    if (this._destroyed) return
    const callback = this.options[callbackName]
    this.destroy({ flushCheckpoint: false })
    // 先关闭连接并禁止检查点回写，再通知上层跳转/卸载，避免同步回调触发普通销毁。
    this.isSynced.value = false
    this.connectionState.value = state
    this.syncError.value = data?.message || '当前协作会话已结束'
    callback?.(data)
  }

  _handleUserJoined(data) {
    const user = this._normalizeUser(data.user)
    if (!user || String(user.id) === String(this.currentUser?.id)) return
    if (this.collaborators.value.some(item => String(item.id) === String(user.id))) return
    this.collaborators.value = [...this.collaborators.value, user]
  }

  _handleUserLeft(data) {
    this.collaborators.value = this.collaborators.value.filter(
      user => String(user.id) !== String(data.userId)
    )
    this._removeRemoteAwarenessByUserId(data.userId)
    this._scheduleAwarenessExpiry()
  }

  _handleRoomUsers(data) {
    const allUsers = (Array.isArray(data.users) ? data.users : [])
      .map(user => this._normalizeUser(user))
      .filter(Boolean)
    const activeUserIds = new Set(allUsers.map(user => String(user.id)))
    for (const [awarenessKey, awareness] of this._remoteAwareness) {
      if (!activeUserIds.has(String(awareness.user.id))) {
        this._removeRemoteAwareness(awarenessKey)
      }
    }
    this.collaborators.value = allUsers.filter((user, index) => (
      String(user.id) !== String(this.currentUser?.id)
      && allUsers.findIndex(candidate => String(candidate.id) === String(user.id)) === index
    ))
    // 新加入的浏览器需要立即看到已存在会话的节点选区，不能等到用户
    // 再次点击节点；周期刷新同时覆盖跨 worker 丢包和异常断线恢复。
    if (!this._paused) this._sendAwareness(this._localActiveNodeUids)
    this._scheduleAwarenessExpiry()
  }

  _normalizeUser(user) {
    if (!user || user.id === undefined || user.id === null) return null
    let avatar = typeof user.avatar === 'string' ? user.avatar : ''
    if (avatar && !/^(https?:|data:|blob:)/i.test(avatar)) {
      const base = import.meta.env?.VITE_APP_BASE_API || ''
      avatar = `${base.replace(/\/$/, '')}/${avatar.replace(/^\//, '')}`
    }
    return {
      id: user.id,
      name: user.name || user.nickName || user.user_name || user.userName || String(user.id),
      avatar,
      color: user.color,
    }
  }

  _normalizeAwarenessNodeUids(nodeUids) {
    if (!Array.isArray(nodeUids)) return []
    return [...new Set(nodeUids.map(String).filter(Boolean))].slice(0, MAX_AWARENESS_NODE_COUNT)
  }

  _normalizeAwarenessEditingNodeUid(value) {
    if (typeof value !== 'string') return ''
    const uid = value.trim()
    return uid && uid.length <= MAX_AWARENESS_NODE_UID_LENGTH ? uid : ''
  }

  _normalizeAwarenessSessionId(value) {
    if (typeof value !== 'string') return null
    const sessionId = value.trim()
    return sessionId && sessionId.length <= MAX_AWARENESS_SESSION_ID_LENGTH
      ? sessionId
      : null
  }

  _awarenessKey(sessionId, userId) {
    return sessionId ? `session:${sessionId}` : `user:${String(userId)}`
  }

  _clearAwarenessRefreshTimer() {
    clearTimeout(this._awarenessRefreshTimer)
    this._awarenessRefreshTimer = null
  }

  _scheduleAwarenessRefresh() {
    this._clearAwarenessRefreshTimer()
    if (this._destroyed || this.readonly) return
    this._awarenessRefreshTimer = setTimeout(() => {
      this._awarenessRefreshTimer = null
      if (!this._destroyed && !this._paused) {
        this._sendAwareness(this._localActiveNodeUids)
      }
      this._scheduleAwarenessRefresh()
    }, AWARENESS_REFRESH_INTERVAL_MS)
    this._awarenessRefreshTimer?.unref?.()
  }

  _scheduleAwarenessExpiry() {
    clearTimeout(this._awarenessExpiryTimer)
    this._awarenessExpiryTimer = null
    if (this._destroyed || this._remoteAwareness.size === 0) return
    const now = Date.now()
    let expiresAt = Number.POSITIVE_INFINITY
    for (const awareness of this._remoteAwareness.values()) {
      expiresAt = Math.min(
        expiresAt,
        awareness.lastSeenAt + AWARENESS_STALE_TIMEOUT_MS,
      )
    }
    this._awarenessExpiryTimer = setTimeout(() => {
      this._awarenessExpiryTimer = null
      this._expireStaleAwareness()
    }, Math.max(1, expiresAt - now))
    this._awarenessExpiryTimer?.unref?.()
  }

  _expireStaleAwareness(now = Date.now()) {
    for (const [awarenessKey, awareness] of this._remoteAwareness) {
      if (now - awareness.lastSeenAt >= AWARENESS_STALE_TIMEOUT_MS) {
        this._removeRemoteAwareness(awarenessKey)
      }
    }
    this._scheduleAwarenessExpiry()
  }

  _bindAwarenessEvents() {
    if (this._awarenessEventsBound || !this.mindMap?.on) return
    this._localActiveNodeUids = this._normalizeAwarenessNodeUids(
      (this.mindMap?.renderer?.activeNodeList || [])
        .map(node => node?.uid || node?.getData?.('uid'))
        .filter(Boolean)
    )
    const currentTextEditor = this.mindMap?.renderer?.textEdit
    if (currentTextEditor?.isShowTextEdit?.()) {
      const currentEditingNode = currentTextEditor.getCurrentEditNode?.()
      this._localEditingNodeUid = this._normalizeAwarenessEditingNodeUid(
        currentEditingNode?.uid || currentEditingNode?.getData?.('uid')
      )
    }
    this._onNodeActive = (_node, nodeList = []) => {
      this._localActiveNodeUids = this._normalizeAwarenessNodeUids(
        nodeList.map(node => node?.uid).filter(Boolean)
      )
      if (!this.isApplyingRemote() && !this._paused) {
        this._sendAwareness(this._localActiveNodeUids)
      }
    }
    this._onNodeTreeRenderEnd = () => this._renderAllRemoteAwareness()
    this._onNodeTextEditStart = (node) => {
      const editingNodeUid = this._normalizeAwarenessEditingNodeUid(
        node?.uid || node?.getData?.('uid')
      )
      if (!editingNodeUid || editingNodeUid === this._localEditingNodeUid) return
      if (
        this._supportsNodeEditLeaseProtocol()
        && !this.hasNodeEditLease(editingNodeUid)
      ) {
        queueMicrotask(() => {
          if (this._destroyed) return
          this.mindMap?.emit?.('node_text_edit_lease_lost', node, editingNodeUid)
        })
        return
      }
      this._localEditingNodeUid = editingNodeUid
      if (!this.isApplyingRemote() && !this._paused) {
        this._sendAwareness(this._localActiveNodeUids)
      }
    }
    this._onNodeTextEditEnd = (node) => {
      const editingNodeUid = this._normalizeAwarenessEditingNodeUid(
        node?.uid || node?.getData?.('uid')
      )
      // 迟到的旧编辑器关闭事件不能释放刚切换到另一节点的新租约。
      if (
        editingNodeUid
        && this._localEditingNodeUid
        && editingNodeUid !== this._localEditingNodeUid
      ) return
      // 大纲在异步申请期间可能被关闭；迟到的 grant 没有对应 start，仍会
      // 以 end 事件归还刚获得的服务端租约。
      this.releaseNodeEditLease(editingNodeUid || this._localEditingNodeUid)
      if (!this._localEditingNodeUid) return
      this._localEditingNodeUid = ''
      if (!this.isApplyingRemote() && !this._paused) {
        this._sendAwareness(this._localActiveNodeUids)
      }
    }
    this.mindMap.on('node_active', this._onNodeActive)
    this.mindMap.on('node_tree_render_end', this._onNodeTreeRenderEnd)
    this.mindMap.on('node_text_edit_start', this._onNodeTextEditStart)
    this.mindMap.on('node_text_edit_end', this._onNodeTextEditEnd)
    this._awarenessEventsBound = true
  }

  _unbindAwarenessEvents() {
    if (!this._awarenessEventsBound) return
    this.mindMap?.off?.('node_active', this._onNodeActive)
    this.mindMap?.off?.('node_tree_render_end', this._onNodeTreeRenderEnd)
    this.mindMap?.off?.('node_text_edit_start', this._onNodeTextEditStart)
    this.mindMap?.off?.('node_text_edit_end', this._onNodeTextEditEnd)
    this._awarenessEventsBound = false
  }

  _sendAwareness(
    nodeUids,
    force = false,
    editingNodeUid = this._localEditingNodeUid,
  ) {
    if ((this._destroyed || this.readonly) && !force) return false
    return this.wsClient.send({
      type: 'awareness',
      nodeUids: this._normalizeAwarenessNodeUids(nodeUids),
      editingNodeUid: this._normalizeAwarenessEditingNodeUid(editingNodeUid),
    })
  }

  _handleAwareness(data) {
    const user = this._normalizeUser(data?.user)
    if (!user) return
    const sessionId = this._normalizeAwarenessSessionId(data?.sessionId)
    if (
      (sessionId && sessionId === this.sessionId)
      || (!sessionId && String(user.id) === String(this.currentUser?.id))
    ) return
    const awarenessKey = this._awarenessKey(sessionId, user.id)
    const sameAccount = String(user.id) === String(this.currentUser?.id)
    const sessionUser = sessionId ? {
      ...user,
      sessionId,
      ...(sameAccount ? { name: `${user.name}（其他浏览器）` } : {}),
    } : user
    const nodeUids = this._normalizeAwarenessNodeUids(data?.nodeUids ?? data?.update?.nodeUids)
    const editingNodeUid = this._normalizeAwarenessEditingNodeUid(
      data?.editingNodeUid ?? data?.update?.editingNodeUid
    )
    this._removeRemoteAwareness(awarenessKey)
    if (!nodeUids.length && !editingNodeUid) {
      this._scheduleAwarenessExpiry()
      return
    }
    this._remoteAwareness.set(awarenessKey, {
      user: sessionUser,
      nodeUids,
      editingNodeUid,
      lastSeenAt: Date.now(),
    })
    this._renderRemoteAwareness(sessionUser, nodeUids, editingNodeUid)
    this._scheduleAwarenessExpiry()
  }

  _renderRemoteAwareness(user, nodeUids, editingNodeUid = '') {
    for (const uid of nodeUids) {
      this.mindMap?.renderer?.findNodeByUid?.(uid)?.addUser?.(user)
    }
    if (editingNodeUid) {
      this.mindMap?.renderer?.findNodeByUid?.(editingNodeUid)?.addEditingUser?.(user)
    }
  }

  _renderAllRemoteAwareness() {
    for (const { user, nodeUids, editingNodeUid } of this._remoteAwareness.values()) {
      this._renderRemoteAwareness(user, nodeUids, editingNodeUid)
    }
  }

  _removeRemoteAwareness(awarenessKey) {
    const current = this._remoteAwareness.get(awarenessKey)
    if (!current) return
    for (const uid of current.nodeUids) {
      this.mindMap?.renderer?.findNodeByUid?.(uid)?.removeUser?.(current.user)
    }
    if (current.editingNodeUid) {
      this.mindMap?.renderer
        ?.findNodeByUid?.(current.editingNodeUid)
        ?.removeEditingUser?.(current.user)
    }
    this._remoteAwareness.delete(awarenessKey)
  }

  _removeRemoteAwarenessByUserId(userId) {
    for (const [awarenessKey, awareness] of this._remoteAwareness) {
      if (String(awareness.user.id) === String(userId)) {
        this._removeRemoteAwareness(awarenessKey)
      }
    }
  }

  _clearRemoteAwareness() {
    clearTimeout(this._awarenessExpiryTimer)
    this._awarenessExpiryTimer = null
    for (const awarenessKey of Array.from(this._remoteAwareness.keys())) {
      this._removeRemoteAwareness(awarenessKey)
    }
  }

  _clearRemotePresence() {
    this.collaborators.value = []
    this._clearRemoteAwareness()
  }

  _shouldAcceptTagDefinition(current, incoming) {
    const currentRevision = Number(current?.definitionRevision)
    const incomingRevision = Number(incoming?.definitionRevision)
    if (Number.isInteger(currentRevision) && !Number.isInteger(incomingRevision)) return false
    if (Number.isInteger(currentRevision) && Number.isInteger(incomingRevision)) {
      return incomingRevision > currentRevision
    }
    return true
  }

  _captureTagDefinitions(root, syncYjs = false) {
    root = root?.root || root
    const captured = new Map()
    const pending = [root]
    const visited = new WeakSet()
    while (pending.length) {
      const node = pending.pop()
      if (!node || typeof node !== 'object' || visited.has(node)) continue
      visited.add(node)
      for (const tag of (node.data?.tag || [])) {
        if (tag && typeof tag === 'object' && tag.tagId) {
          const key = String(tag.tagId)
          const definition = {
            tagId: tag.tagId,
            categoryId: tag.categoryId,
            uuid: tag.uuid,
            tagKey: tag.tagKey,
            text: tag.text,
            style: tag.style || {},
            status: tag.status,
            definitionRevision: tag.definitionRevision,
          }
          const current = this.tagDefinitions.get(key)
          if (!current || this._shouldAcceptTagDefinition(current, definition)) {
            this.tagDefinitions.set(key, definition)
          }
          captured.set(key, this.tagDefinitions.get(key))
          if (syncYjs) {
            const yCurrent = this.yTagDefinitions.get(key)
            if (!yCurrent || this._shouldAcceptTagDefinition(yCurrent, definition)) {
              this.yTagDefinitions.set(key, definition)
            }
          }
        }
      }
      const children = Array.isArray(node.children) ? node.children : []
      for (let index = children.length - 1; index >= 0; index -= 1) {
        pending.push(children[index])
      }
    }
    return captured
  }

  _syncTagDefinitionsFromYjs(deletedKeys = []) {
    let changed = false
    // 只按本次 Yjs 事件明确删除的键清理缓存。不能用当前 Map 全量
    // 覆盖本地定义：滚动升级期间旧 Yjs 状态可能尚无 tagDefinitions，
    // 此时仍要保留从服务端详情捕获的渲染定义。
    for (const key of deletedKeys) {
      if (this.tagDefinitions.delete(String(key))) changed = true
    }
    this.yTagDefinitions.forEach((definition, key) => {
      if (!definition || typeof definition !== 'object') return
      const current = this.tagDefinitions.get(String(key))
      if (!current || this._shouldAcceptTagDefinition(current, definition)) {
        this.tagDefinitions.set(String(key), {
          ...definition,
          style: { ...(definition.style || {}) },
        })
        changed = true
      }
    })
    return changed
  }

  _setYjsTagDefinition(key, definition) {
    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        this.yTagDefinitions.set(String(key), {
          ...definition,
          style: { ...(definition.style || {}) },
        })
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
  }

  _applyTagDefinitions(root) {
    let changed = false
    const pending = [root]
    const visited = new WeakSet()
    while (pending.length) {
      const node = pending.pop()
      if (!node || typeof node !== 'object' || visited.has(node)) continue
      visited.add(node)
      if (Array.isArray(node.data?.tag)) {
        node.data.tag = node.data.tag.map(tag => {
          if (!tag || typeof tag !== 'object' || !tag.tagId) return tag
          const definition = this.tagDefinitions.get(String(tag.tagId))
          if (!definition) return tag
          changed = true
          return {
            ...tag,
            ...definition,
            style: { ...(definition.style || {}) },
          }
        })
      }
      const children = Array.isArray(node.children) ? node.children : []
      for (let index = children.length - 1; index >= 0; index -= 1) {
        pending.push(children[index])
      }
    }
    return changed
  }

  _handleTagDefinitionChanged(data) {
    if (!data?.tagId || !data.definition) return
    const key = String(data.tagId)
    const current = this.tagDefinitions.get(key)
    const incomingRevision = Number(
      data.definitionRevision ?? data.definition.definitionRevision
    )
    const currentRevision = Number(current?.definitionRevision)
    if (
      Number.isInteger(incomingRevision)
      && Number.isInteger(currentRevision)
      && incomingRevision <= currentRevision
    ) return
    const acceptedDefinition = {
      ...data.definition,
      definitionRevision: Number.isInteger(incomingRevision)
        ? incomingRevision
        : data.definition.definitionRevision,
    }
    this.tagDefinitions.set(key, acceptedDefinition)
    this._setYjsTagDefinition(key, acceptedDefinition)
    this.options.onTagDefinitionChanged?.({
      ...data,
      definitionRevision: Number.isInteger(incomingRevision)
        ? incomingRevision
        : data.definition.definitionRevision,
    })
    // 由 Yjs 权威树重新解析托管标签，并复用统一的远端渲染保护。
    // simple-mind-map 的 updateData 可能在当前调用栈结束后继续派发
    // data_change；使用 0ms 解锁会把这类远端样式刷新误回传为本地编辑。
    if (this.mindMap) this._requestYjsApply()
  }

  _acceptOrderedDocumentEventRevision(data, eventName) {
    if (this._authoritativeRevisionPending !== null) return null
    const revision = Number(data?.contentRevision)
    if (!Number.isInteger(revision) || revision <= 0) {
      this._handleStaleState({
        ...data,
        reason: 'document_event_revision_missing',
        message: `${eventName}缺少内容版本，正在从云端校准画布`,
      })
      return null
    }
    if (revision < this.contentRevision) return null
    if (revision > this.contentRevision + 1) {
      // 标签治理事件只携带当前 revision 的增量，不是完整正文。直接
      // 跳号会掩盖中间丢失的节点更新，随后数据库心跳也无法再发现分叉。
      this._handleStaleState({
        ...data,
        contentRevision: revision,
        reason: 'document_event_revision_gap',
        message: `${eventName}前存在未送达的协作内容，正在从云端校准画布`,
      })
      return null
    }
    return revision
  }

  _mutateManagedTags(mutator, contentRevision) {
    let changed = false
    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        this.yNodes.forEach(yNode => {
          const yData = yNode.get('data')
          const tags = yData?.get('tag')
          if (!Array.isArray(tags)) return
          const nextTags = mutator(tags)
          if (nextTags !== tags) {
            yData.set('tag', nextTags)
            changed = true
          }
        })
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
    const previousRevision = this.contentRevision
    this.setContentRevision(contentRevision)
    if (this.contentRevision > previousRevision) {
      this.options.onContentRevision?.(this.contentRevision)
    }
    if (changed) this._requestYjsApply()
  }

  _handleTagReplaced(data) {
    if (!data?.sourceTagId || !data?.targetTagId || !data?.definition) return
    const contentRevision = this._acceptOrderedDocumentEventRevision(
      data,
      '标签替换事件',
    )
    if (contentRevision === null) return
    const sourceKey = String(data.sourceTagId)
    const targetKey = String(data.targetTagId)
    const incomingTargetDefinition = {
      ...data.definition,
      definitionRevision: data.definitionRevision ?? data.definition.definitionRevision,
    }
    const cachedTargetDefinition = this.tagDefinitions.get(targetKey)
    const yCurrentTargetDefinition = this.yTagDefinitions.get(targetKey)
    const currentTargetDefinition = (
      yCurrentTargetDefinition
      && (
        !cachedTargetDefinition
        || this._shouldAcceptTagDefinition(cachedTargetDefinition, yCurrentTargetDefinition)
      )
    ) ? yCurrentTargetDefinition : cachedTargetDefinition
    const acceptsIncomingTarget = !currentTargetDefinition
      || this._shouldAcceptTagDefinition(currentTargetDefinition, incomingTargetDefinition)
    const targetDefinition = acceptsIncomingTarget
      ? incomingTargetDefinition
      : currentTargetDefinition
    this.tagDefinitions.delete(sourceKey)
    this.tagDefinitions.set(targetKey, {
      ...targetDefinition,
      style: { ...(targetDefinition.style || {}) },
    })
    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        this.yTagDefinitions.delete(sourceKey)
        if (
          !yCurrentTargetDefinition
          || this._shouldAcceptTagDefinition(yCurrentTargetDefinition, incomingTargetDefinition)
        ) {
          this.yTagDefinitions.set(targetKey, {
            ...incomingTargetDefinition,
            style: { ...(incomingTargetDefinition.style || {}) },
          })
        }
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
    this._mutateManagedTags(tags => {
      let changed = false
      const seen = new Set()
      const next = []
      for (const tag of tags) {
        if (!tag || typeof tag !== 'object') {
          next.push(tag)
          continue
        }
        const tagId = Number(tag.tagId)
        let replacement = tag
        if (tagId === Number(data.sourceTagId)) {
          replacement = { ...tag, tagId: data.targetTagId }
          if (targetDefinition.categoryId === undefined) delete replacement.categoryId
          else replacement.categoryId = targetDefinition.categoryId
        }
        const key = replacement.tagId ? String(replacement.tagId) : null
        if (key && seen.has(key)) {
          changed = true
          continue
        }
        if (key) seen.add(key)
        if (replacement !== tag) changed = true
        next.push(replacement)
      }
      return changed ? next : tags
    }, contentRevision)
  }

  _handleTagUnbound(data) {
    const ids = new Set((data?.tagIds || []).map(String))
    if (!ids.size) return
    const contentRevision = this._acceptOrderedDocumentEventRevision(
      data,
      '标签解绑事件',
    )
    if (contentRevision === null) return
    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        for (const id of ids) {
          this.tagDefinitions.delete(id)
          this.yTagDefinitions.delete(id)
        }
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
    this._mutateManagedTags(tags => {
      const next = tags.filter(tag => !tag || typeof tag !== 'object' || !ids.has(String(tag.tagId)))
      return next.length === tags.length ? tags : next
    }, contentRevision)
  }

  _encodeUpdate(uint8Array) {
    return uint8ArrayToBase64(uint8Array)
  }

  _decodeUpdate(base64Str) {
    return base64ToUint8Array(base64Str)
  }
}
