/**
 * Yjs 脑图同步管理器
 *
 * 数据模型（细粒度，非整体替换）：
 *   Y.Doc
 *   ├── Y.Map('meta')    → { layout: string, theme: object, documentData: object }
 *   ├── Y.Map('tagDefinitions') → { [tagId]: 当前可渲染定义（不写入节点） }
 *   ├── Y.Map('nodes')   → { [uid]: Y.Map({ data: Y.Map, children: Y.Array<string>, parentUid: string }) }
 *   ├── Y.Map('relations') / Y.Map('summaries') / Y.Map('groups')
 *   └── Y.Map('assets')  → 跨节点及大对象数据（不写入节点）
 *
 * 桥接 simple-mind-map 的 data_change_detail 事件和 Yjs 操作。
 */
import * as Y from 'yjs'
import { ref } from 'vue'
import { stringifyJsonValueIterative } from '../libs/simple-mind-map/src/utils/jsonClone.js'
import { applyMindmapDocumentPreservingRuntimeState } from './mindmap-document-apply.js'
import { rebaseMindmapHistory } from './mindmap-history-rebase.js'
import { MindmapWsClient } from './ws-client.js'
import {
  applyCrossNodeState,
  CROSS_NODE_DATA_KEYS,
  detailListTouchesCrossNodeState,
  extractCrossNodeState,
  stripCrossNodeData,
} from './yjs-cross-node-state.js'
import {
  applyLocalActiveNodeState,
  deleteYjsSubtree,
  flattenMindmapTree,
  normalizeNodeDataForYjs,
  replaceYArrayValues,
  replaceYMapEntries,
  setYMapValueIfChanged,
  synchronizeYjsParentUids,
} from './yjs-tree-state.js'

const MAX_AWARENESS_NODE_COUNT = 100
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
const YJS_CHECKPOINT_CAPABILITY = 'yjs-checkpoint-v1'
const CHECKPOINT_INTERVAL_MS = 5000
const MAX_CONFIRMED_MUTATION_IDS = 100
const DOCUMENT_PREPARE_RETRY_DELAYS = [1000, 3000, 10000, 30000]
const DOCUMENT_PREPARE_ERROR = '协作内容渲染能力加载失败，正在重试'
const DOCUMENT_PREPARE_EXHAUSTED_ERROR = '协作内容渲染能力加载失败，请检查网络后刷新页面'

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

function stagePersistedYjsStates(encodedStates, stateSources) {
  const states = Array.isArray(encodedStates) ? encodedStates : []
  if (states.length > MAX_PERSISTED_STATE_SOURCE_COUNT) {
    return {
      mergedUpdate: null,
      acceptedSourceIds: [],
      invalidSourceIds: [],
      invalidStateCount: states.length,
    }
  }
  const normalizedSources = normalizePersistedStateSources(stateSources, states.length)
  const sourcesAligned = normalizedSources.length === states.length
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
      acceptedSourceIds,
      invalidSourceIds,
      invalidStateCount,
    }
  } catch {
    return {
      mergedUpdate: null,
      acceptedSourceIds: [],
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
    this.options = options
    this._applyingRemote = false
    this._mutatingMindmapFromRemote = false
    this._preparingRemote = false
    this._paused = false
    this._destroyed = false
    this._receivedServerState = false
    this._localYjsChange = false
    this._pendingStructuredPatch = null
    this._checkpointTimer = null
    this._checkpointDirty = false
    this._hasUnconfirmedRemoteState = false
    this._hasLegacyUnconfirmedRemoteState = false
    this._unconfirmedRemoteMutationIds = new Set()
    this._confirmedRemoteMutationIds = new Map()
    this._outgoingClientMutationId = null
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
    this._remoteAwareness = new Map()
    this._awarenessEventsBound = false
    this.contentRevision = contentRevision
    this.currentUser = this._normalizeUser(options.user)
    this.serverCapabilities = new Set()
    this.tagDefinitions = new Map()

    this.yMeta = this.doc.getMap('meta')
    this.yTagDefinitions = this.doc.getMap('tagDefinitions')
    this.yNodes = this.doc.getMap('nodes')
    this.yRelations = this.doc.getMap('relations')
    this.ySummaries = this.doc.getMap('summaries')
    this.yGroups = this.doc.getMap('groups')
    this.yAssets = this.doc.getMap('assets')
    this._captureTagDefinitions(this.mindMap?.getData?.(true))

    this.wsClient = new MindmapWsClient(mindmapId, {
      onAuthenticated: (user, capabilities) => {
        const authenticatedUser = this._normalizeUser(user)
        this.currentUser = {
          ...this.currentUser,
          ...authenticatedUser,
          avatar: this.currentUser?.avatar || authenticatedUser?.avatar || '',
        }
        this.serverCapabilities = new Set(
          Array.isArray(capabilities)
            ? capabilities.filter(capability => typeof capability === 'string')
            : []
        )
        this._beginSyncHandshake()
        this._sendAwareness(this._localActiveNodeUids)
      },
      onClose: () => {
        clearTimeout(this._syncInitTimer)
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
      protocol_error: (data) => {
        this.syncError.value = data.message || '协作消息格式错误'
        this.options.onProtocolError?.(data)
      },
      tag_definition_changed: (data) => this._handleTagDefinitionChanged(data),
      tag_replaced: (data) => this._handleTagReplaced(data),
      tag_unbound: (data) => this._handleTagUnbound(data),
      comment_changed: (data) => this.options.onCommentChanged?.(data),
    })
  }

  start() {
    this._bindAwarenessEvents()
    // 监听 Yjs 文档变更 → 转发到 WebSocket
    this.doc.on('update', (update, origin) => {
      if (
        !this._destroyed
        && origin !== 'remote'
        && !this._paused
        && this._authoritativeRevisionPending === null
      ) {
        const patch = origin === LOCAL_NODE_DETAIL_ORIGIN
          ? this._pendingStructuredPatch
          : null
        const clientMutationId = this._normalizeClientMutationId(
          this._outgoingClientMutationId,
        )
        const correlation = clientMutationId ? { clientMutationId } : {}
        if (origin !== 'init' && this._supportsCheckpointProtocol()) {
          this.wsClient.send({
            type: 'update',
            update: this._encodeUpdate(update),
            ...correlation,
            patch: patch || {
              schemaVersion: 1,
              nodes: [],
              deletedNodeUids: [],
              applyMeta: origin === 'local-meta',
            },
            contentRevision: this.contentRevision,
          })
          this._scheduleCheckpoint()
        } else {
          this.wsClient.send({
            type: 'update',
            update: this._encodeUpdate(update),
            ...correlation,
            state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
            ...(patch ? { patch } : {}),
            contentRevision: this.contentRevision,
          })
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
    this._destroyed = true
    clearTimeout(this._checkpointTimer)
    this._checkpointTimer = null
    this._checkpointDirty = false
    clearTimeout(this._syncInitTimer)
    clearTimeout(this._remoteApplyFallbackTimer)
    clearTimeout(this._remoteApplyReleaseTimer)
    clearTimeout(this._remotePrepareRetryTimer)
    if (this._remoteRenderEndHandler) {
      this.mindMap?.off?.('node_tree_render_end', this._remoteRenderEndHandler)
    }
    this._sendAwareness([], true)
    this._unbindAwarenessEvents()
    this._clearRemotePresence()
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

  setContentRevision(revision) {
    if (Number.isInteger(revision) && revision > 0) {
      this.contentRevision = revision
    }
  }

  _normalizeClientMutationId(value) {
    if (typeof value !== 'string') return null
    const normalized = value.trim()
    return normalized && normalized.length <= 100 ? normalized : null
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

  _rememberConfirmedRemoteMutation(clientMutationId, concurrentMerge = false) {
    if (!clientMutationId) return
    this._confirmedRemoteMutationIds.delete(clientMutationId)
    this._confirmedRemoteMutationIds.set(clientMutationId, concurrentMerge === true)
    while (this._confirmedRemoteMutationIds.size > MAX_CONFIRMED_MUTATION_IDS) {
      this._confirmedRemoteMutationIds.delete(
        this._confirmedRemoteMutationIds.keys().next().value,
      )
    }
  }

  /** 当前 Yjs 内容需要由 HTTP 权威文档重新确认后才能继续持久化。 */
  requiresAuthoritativeReconciliation() {
    return this._hasUnconfirmedRemoteState || this._authoritativeRevisionPending !== null
  }

  _beginSyncHandshake() {
    if (this._destroyed) return
    clearTimeout(this._syncInitTimer)
    this._receivedServerState = false
    this._hadLocalDataBeforeSync = this.hasData()
    this.isSynced.value = false
    this.connectionState.value = 'syncing'
    this.syncError.value = ''
    this._syncInitTimer = setTimeout(() => {
      this._requestSeedLease()
    }, 1200)
  }

  _requestSeedLease() {
    if (this._destroyed || this._receivedServerState || this.hasData()) return
    this.wsClient.send({
      type: 'request_seed',
      contentRevision: this.contentRevision,
    })
    clearTimeout(this._syncInitTimer)
    this._syncInitTimer = setTimeout(() => this._requestSeedLease(), 3000)
  }

  _completeSyncHandshake(receivedServerState) {
    if (this._destroyed) return
    clearTimeout(this._syncInitTimer)
    const currentData = this.mindMap?.getData?.(true)
    const currentDocument = currentData?.root ? {
      ...currentData,
      documentData: this.options.getDocumentData?.(),
    } : currentData
    if (!this.hasData()) {
      const root = currentDocument?.root || currentDocument
      if (root) {
        this.initFromMindmap(
          currentDocument,
          this.options.getClientMutationId?.(),
        )
      }
    } else if (this._hadLocalDataBeforeSync) {
      // 重连时补发完整状态，覆盖断网期间未能通过 WebSocket 发送的增量。
      this._sendFullState()
    }
    if (currentDocument?.root) {
      const missingMeta = {}
      if (!this.yMeta.has('layout')) missingMeta.layout = currentDocument.layout
      if (!this.yMeta.has('theme')) missingMeta.theme = currentDocument.theme
      if (
        !this.yMeta.has('documentData')
        && currentDocument.documentData !== undefined
      ) {
        missingMeta.documentData = currentDocument.documentData
      }
      if (Object.keys(missingMeta).length) this.syncDocumentMeta(missingMeta)
    }
    this._receivedServerState = receivedServerState
    this.isSynced.value = true
    this.connectionState.value = 'connected'
    this.syncError.value = ''
  }

  _sendFullState() {
    if (this._destroyed || this.requiresAuthoritativeReconciliation()) return false
    const state = Y.encodeStateAsUpdate(this.doc)
    const sent = this.wsClient.send({
      type: 'update',
      update: this._encodeUpdate(state),
      state: this._encodeUpdate(state),
      contentRevision: this.contentRevision,
    })
    if (sent) this._clearCheckpoint()
    return sent
  }

  _sendConsolidatedCheckpoint(replacesSources, invalidSources = []) {
    const mergedSources = Array.isArray(replacesSources) ? replacesSources : []
    const rejectedSources = Array.isArray(invalidSources) ? invalidSources : []
    if (
      this._destroyed
      || this._authoritativeRevisionPending !== null
      || !this._supportsCheckpointProtocol()
      || (!mergedSources.length && !rejectedSources.length)
    ) return false
    const sent = this.wsClient.send({
      type: 'checkpoint',
      state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
      contentRevision: this.contentRevision,
      ...(mergedSources.length ? { replacesSources: mergedSources } : {}),
      ...(rejectedSources.length ? { invalidSources: rejectedSources } : {}),
    })
    if (sent) this._clearCheckpoint()
    return sent
  }

  _supportsCheckpointProtocol() {
    return this.serverCapabilities.has(YJS_CHECKPOINT_CAPABILITY)
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
      || this.requiresAuthoritativeReconciliation()
      || !this._supportsCheckpointProtocol()
    ) return
    this._checkpointDirty = true
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
      || this._destroyed
      || this._paused
      || this.requiresAuthoritativeReconciliation()
      || !this.hasData()
      || !this._supportsCheckpointProtocol()
    ) return false
    const sent = this.wsClient.send({
      type: 'checkpoint',
      state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
      contentRevision: this.contentRevision,
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
    this._sendAwareness([], true)
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

  /** 检查是否已收到服务端的 sync_init 状态 */
  hasReceivedServerState() {
    return this._receivedServerState
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
    const current = this.mindMap?.getData?.()
    const root = current?.root || current
    const uid = root?.data?.uid
    return uid === undefined || uid === null ? '' : String(uid)
  }

  _replaceCrossNodeState(state = {}) {
    replaceYMapEntries(this.yRelations, state.relations || {})
    replaceYMapEntries(this.ySummaries, state.summaries || {})
    replaceYMapEntries(this.yGroups, state.groups || {})
    replaceYMapEntries(this.yAssets, state.assets || {})
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
    const hasCurrentSchema = Number(this.yMeta.get('crossNodeSchemaVersion')) >= 1
    const hasEmbeddedState = this._hasEmbeddedCrossNodeState()
    if (hasCurrentSchema && !hasEmbeddedState) return false
    const legacyState = hasEmbeddedState
      ? extractCrossNodeState(this._rebuildTreeFromYjs({ applyCrossNode: false }))
      : { relations: {}, summaries: {}, groups: {}, assets: {} }

    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        if (hasCurrentSchema) {
          for (const [key, value] of Object.entries(legacyState.relations)) {
            if (!this.yRelations.has(key)) this.yRelations.set(key, value)
          }
          for (const [key, value] of Object.entries(legacyState.summaries)) {
            if (!this.ySummaries.has(key)) this.ySummaries.set(key, value)
          }
          for (const [key, value] of Object.entries(legacyState.groups)) {
            if (!this.yGroups.has(key)) this.yGroups.set(key, value)
          }
          for (const [key, value] of Object.entries(legacyState.assets)) {
            if (!this.yAssets.has(key)) this.yAssets.set(key, value)
          }
        } else {
          this._replaceCrossNodeState(legacyState)
        }
        this.yNodes.forEach(yNode => {
          const yData = yNode.get('data')
          if (!yData) return
          for (const key of CROSS_NODE_DATA_KEYS) yData.delete(key)
        })
        this.yMeta.set('crossNodeSchemaVersion', 1)
      }, 'local-cross-node-migration')
    } finally {
      this._localYjsChange = false
    }
    return true
  }

  syncDocumentMeta(document = {}, clientMutationId = null) {
    if (this._paused || this._destroyed) return
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
          }
          synchronizeYjsParentUids(
            this.yNodes,
            fullDocument.root?.data?.uid,
          )
          this._writeDocumentMeta(fullDocument)
          this.yMeta.set('crossNodeSchemaVersion', 1)
        }, 'init')
      })
    } finally {
      this._localYjsChange = false
    }
  }

  /** 监听 simple-mind-map 的 data_change_detail 事件，翻译为 Yjs 操作 */
  onDataChangeDetail(detailList, clientMutationId = null) {
    if (!detailList || !detailList.length) return
    if (this._paused) return

    this._localYjsChange = true
    this._pendingStructuredPatch = this._buildStructuredPatch(detailList)
    const syncCrossNodeState = detailListTouchesCrossNodeState(detailList)
    try {
      this._withOutgoingClientMutationId(clientMutationId, () => this.doc.transact(() => {
        for (const detail of detailList) {
          const uid = detail.data?.data?.uid || detail.oldData?.uid
          if (!uid) continue

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
              break
            }

            case 'update': {
              this._captureTagDefinitions(detail.data, true)
              const yNode = this.yNodes.get(uid)
              if (yNode) {
                const yData = yNode.get('data')
                if (yData && detail.data?.data) {
                  replaceYMapEntries(
                    yData,
                    stripCrossNodeData(normalizeNodeDataForYjs(detail.data.data)),
                  )
                }
                if (detail.data?.children) {
                  replaceYArrayValues(
                    yNode.get('children'),
                    detail.data.children.map(child => child.data?.uid).filter(Boolean),
                  )
                }
              }
              break
            }

            case 'delete': {
              deleteYjsSubtree(this.yNodes, detail.oldData?.uid || uid)
              break
            }
          }
        }
        synchronizeYjsParentUids(this.yNodes, this._getPreferredRootUid())
        if (syncCrossNodeState) {
          this._replaceCrossNodeState(extractCrossNodeState(this.mindMap?.getData?.(true)))
          this.yMeta.set('crossNodeSchemaVersion', 1)
        }
      }, LOCAL_NODE_DETAIL_ORIGIN))
    } finally {
      this._pendingStructuredPatch = null
      this._localYjsChange = false
    }
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
      nodes.set(uid, {
        uid,
        data: stripCrossNodeData(normalizeNodeDataForYjs(detail.data.data)),
        children,
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
      nodes.push({ uid, data: node.data, children })
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
      for (const uid of patch.deletedNodeUids) deleteYjsSubtree(this.yNodes, uid)
      for (const node of patch.nodes) {
        let yNode = this.yNodes.get(node.uid)
        if (!yNode) {
          yNode = new Y.Map()
          yNode.set('data', new Y.Map())
          yNode.set('children', new Y.Array())
          this.yNodes.set(node.uid, yNode)
        }
        let yData = yNode.get('data')
        if (!(yData instanceof Y.Map)) {
          yData = new Y.Map()
          yNode.set('data', yData)
        }
        let yChildren = yNode.get('children')
        if (!(yChildren instanceof Y.Array)) {
          yChildren = new Y.Array()
          yNode.set('children', yChildren)
        }
        replaceYMapEntries(yData, node.data)
        replaceYArrayValues(yChildren, node.children)
      }
      synchronizeYjsParentUids(this.yNodes, this._getPreferredRootUid())
    }, 'remote')
  }

  /** 从 Yjs 扁平节点重建 simple-mind-map 树形结构 */
  _rebuildTreeFromYjs({ applyCrossNode = true } = {}) {
    const nodes = {}
    this.yNodes.forEach((yNode, uid) => {
      const yData = yNode.get('data')
      nodes[uid] = {
        data: yData ? Object.fromEntries(yData.entries()) : {},
        children: [],
        _parentUid: yNode.get('parentUid') || '',
        _childUids: yNode.get('children')?.toArray() || [],
      }
    })

    const rootUid = Object.keys(nodes).find(id => !nodes[id]._parentUid)
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
    if (applyCrossNode && Number(this.yMeta.get('crossNodeSchemaVersion')) >= 1) {
      applyCrossNodeState(tree, {
        relations: this.yRelations,
        summaries: this.ySummaries,
        groups: this.yGroups,
        assets: this.yAssets,
      })
    }
    this._applyTagDefinitions(tree)
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

  _requestYjsApply({ applyMeta = false } = {}) {
    if (this._destroyed || !this.mindMap) return
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
      this.options.onDocumentApplyError?.(error)
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
    this._pendingRemoteApply = true
    this._pendingRemoteApplyMeta ||= applyMeta
    if (this._destroyed || this._paused || this._remotePrepareRetryTimer) return
    const delays = Array.isArray(this.options.documentPrepareRetryDelays)
      ? this.options.documentPrepareRetryDelays
      : DOCUMENT_PREPARE_RETRY_DELAYS
    if (this._remotePrepareRetryAttempt >= delays.length) {
      this.syncError.value = DOCUMENT_PREPARE_EXHAUSTED_ERROR
      this.options.onDocumentPrepareExhausted?.()
      return
    }
    const delay = Math.max(0, Number(delays[this._remotePrepareRetryAttempt]) || 0)
    this._remotePrepareRetryAttempt += 1
    this._remotePrepareRetryTimer = setTimeout(() => {
      this._remotePrepareRetryTimer = null
      this._requestYjsApply()
    }, delay)
  }

  async _applyYjsToMindmap({ applyMeta = false } = {}) {
    if (this._destroyed || !this.mindMap) return
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
          if (this._destroyed) return false
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
        if (!this._destroyed) {
          this._documentPrepareFailed = true
          this.syncError.value = DOCUMENT_PREPARE_ERROR
          this.options.onDocumentPrepareError?.(error)
          this._scheduleDocumentPrepareRetry(applyMeta)
        }
        return false
      }
    }

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

    const command = targetMindMap.command
    command?.addHistory?.cancel?.()
    const currentHistoryTree = command?.getCopyData?.()
      || targetMindMap.getData?.()
    const rebasedHistory = (
      command
      && Array.isArray(command.history)
      && currentHistoryTree
    ) ? rebaseMindmapHistory({
        history: command.history,
        activeHistoryIndex: command.activeHistoryIndex,
        currentTree: currentHistoryTree,
        remoteTree: preparedDocument.tree,
        maxHistoryCount: command.mindMap?.opt?.maxHistoryCount,
        maxHistoryMemoryBytes: command.mindMap?.opt?.maxHistoryMemoryBytes,
      }) : null
    const historyWasPaused = command?.isPause === true
    command?.pause?.()
    const scheduleRelease = this._beginRemoteApplication()
    try {
      // 节点增量也统一经过运行时状态保护。node_active 使用 0ms 防抖，
      // 协作回放可能先到；此时需从正在编辑的节点补回本地选区。
      this._mutatingMindmapFromRemote = true
      try {
        applyMindmapDocumentPreservingRuntimeState(
          targetMindMap,
          applyMeta ? preparedDocument.document : { root: preparedDocument.tree },
        )
      } finally {
        this._mutatingMindmapFromRemote = false
      }
      // updateData 会延迟 addHistory。先取消它，再把互不重叠的远端修改
      // 重放到每个本地快照；同一节点存在竞争时保守清空，避免 Ctrl+Z
      // 用旧快照覆盖协作者内容。
      command?.addHistory?.cancel?.()
      if (rebasedHistory) {
        command.history = rebasedHistory.history
        command.activeHistoryIndex = rebasedHistory.activeHistoryIndex
        targetMindMap.emit?.(
          'back_forward',
          command.activeHistoryIndex,
          command.history.length,
        )
      } else {
        command?.clearHistory?.()
      }
      if (!historyWasPaused) command?.recovery?.()
      this.options.onDocumentApplied?.(
        preparedDocument.tree,
        preparedDocument.appliedMeta,
      )
      return true
    } catch (error) {
      this._mutatingMindmapFromRemote = false
      command?.addHistory?.cancel?.()
      if (!historyWasPaused) command?.recovery?.()
      scheduleRelease()
      throw error
    }
  }

  _handleSyncInit(data) {
    if (this._destroyed) return
    const states = Array.isArray(data.states) && data.states.length
      ? data.states
      : [data.state]
    const staged = stagePersistedYjsStates(states, data.stateSources)
    if (staged.mergedUpdate) {
      this._hasLegacyUnconfirmedRemoteState = true
      this._refreshUnconfirmedRemoteState()
    }
    this._localYjsChange = true
    try {
      if (staged.mergedUpdate) Y.applyUpdate(this.doc, staged.mergedUpdate, 'remote')
      this.doc.transact(() => {
        synchronizeYjsParentUids(this.yNodes, this._getPreferredRootUid())
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
    this._normalizeEmbeddedCrossNodeState()
    this._requestYjsApply({ applyMeta: true })
    this._completeSyncHandshake(true)
    // 当前完整检查点已经包含握手接受的全部来源，可以原子替换这些旧副本。
    // 新来源若在并发窗口写入，服务端不会出现在 replacesSources 中，仍会保留。
    this._sendConsolidatedCheckpoint(
      staged.acceptedSourceIds,
      staged.invalidSourceIds,
    )
    if (staged.invalidStateCount) {
      this.connectionState.value = 'degraded'
      this.syncError.value = `检测到 ${staged.invalidStateCount} 份异常协作缓存，已隔离并继续同步`
    }
  }

  _handleSeedPending(data) {
    const revision = Number(data?.contentRevision)
    if (Number.isInteger(revision) && revision > this.contentRevision) {
      this.setContentRevision(revision)
      this.options.onContentRevision?.(revision, data)
    }
    this.connectionState.value = 'syncing'
    this.syncError.value = '正在等待房间协作状态'
  }

  _handleSeedRequest(data) {
    const revision = Number(data?.contentRevision)
    if (
      this._destroyed
      || this._paused
      || !this.hasData()
      || (Number.isInteger(revision) && revision !== this.contentRevision)
    ) return
    this._sendFullState()
  }

  _handleSeedGranted(data) {
    const revision = Number(data?.contentRevision)
    if (Number.isInteger(revision) && revision !== this.contentRevision) return
    if (this.hasData()) {
      this._completeSyncHandshake(true)
      return
    }
    this._completeSyncHandshake(false)
  }

  _handleUpdate(data) {
    if (this._destroyed) return
    const clientMutationId = this._normalizeClientMutationId(data?.clientMutationId)
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
    if (
      wasAlreadyConfirmed
      && this._confirmedRemoteMutationIds.get(clientMutationId) === true
    ) {
      this._handleStaleState({
        ...data,
        contentRevision: data?.contentRevision || this.contentRevision,
        message: '协作内容已在服务器合并，正在加载权威版本',
        reason: 'concurrent_merge',
      })
      return
    }
    const patch = this._normalizeStructuredPatch(data.patch)
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
    this._localYjsChange = true
    try {
      Y.applyUpdate(this.doc, update, 'remote')
      if (patch) this._applyStructuredPatch(patch)
      this.doc.transact(() => {
        synchronizeYjsParentUids(this.yNodes, this._getPreferredRootUid())
      }, 'remote')
    } finally {
      this._localYjsChange = false
    }
    if (!wasAlreadyConfirmed) {
      if (clientMutationId) this._unconfirmedRemoteMutationIds.add(clientMutationId)
      else this._hasLegacyUnconfirmedRemoteState = true
      this._refreshUnconfirmedRemoteState()
    }
    this._normalizeEmbeddedCrossNodeState()
    this._requestYjsApply({ applyMeta: patch?.applyMeta === true || !patch })
    if (!this._receivedServerState && this.hasData()) {
      this._completeSyncHandshake(true)
    }
  }

  _handleStaleState(data) {
    const revision = Number(data?.contentRevision ?? data?.currentRevision)
    this._authoritativeRevisionPending = Number.isInteger(revision) && revision > 0
      ? revision
      : this.contentRevision
    this._clearCheckpoint()
    this.isSynced.value = false
    this.connectionState.value = 'stale'
    this.syncError.value = data?.message || '协作状态已落后，正在合并最新内容'
    this.options.onStaleState?.(data)
  }

  _handleContentRevisionChanged(data) {
    const revision = Number(data?.contentRevision)
    if (!Number.isInteger(revision)) return
    const clientMutationId = this._normalizeClientMutationId(data?.clientMutationId)
    const confirmsRemoteMutation = clientMutationId
      && this._unconfirmedRemoteMutationIds.delete(clientMutationId)
    if (clientMutationId) {
      this._rememberConfirmedRemoteMutation(
        clientMutationId,
        data?.concurrentMerge === true,
      )
    }
    this._refreshUnconfirmedRemoteState()

    if (confirmsRemoteMutation && data?.concurrentMerge === true) {
      this._handleStaleState({
        ...data,
        contentRevision: revision,
        message: '协作内容已在服务器合并，正在加载权威版本',
        reason: 'concurrent_merge',
      })
      return
    }
    // 跨实例广播可能乱序到达；旧 revision 仍可确认它对应的实时批次，
    // 但不能让当前内容版本倒退，也不能再次触发旧式校准。
    if (revision < this.contentRevision) return
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
    // 带 clientMutationId 的实时更新和 HTTP 保存属于同一不可变批次。
    // 确认一个批次后可安全推进 revision；其他尚未落库的远端批次继续留在
    // Yjs 顶层，等各自的确认到达，无需把正常协作误判为 stale。
    if (revision === this.contentRevision) return
    this.setContentRevision(revision)
    this.options.onContentRevision?.(revision, data)
  }

  _handleDocumentReset(data) {
    const revision = Number(data?.contentRevision)
    if (!Number.isInteger(revision) || revision <= this.contentRevision) return
    this._authoritativeRevisionPending = revision
    this._clearCheckpoint()
    this.isSynced.value = false
    this.connectionState.value = 'syncing'
    this.syncError.value = data?.message || '协作基线已重置，正在加载最新内容'
    this.options.onDocumentReset?.(data)
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
    this._removeRemoteAwareness(data.userId)
  }

  _handleRoomUsers(data) {
    const allUsers = (Array.isArray(data.users) ? data.users : [])
      .map(user => this._normalizeUser(user))
      .filter(Boolean)
    const activeUserIds = new Set(allUsers.map(user => String(user.id)))
    for (const userId of this._remoteAwareness.keys()) {
      if (!activeUserIds.has(String(userId))) this._removeRemoteAwareness(userId)
    }
    this.collaborators.value = allUsers.filter((user, index) => (
      String(user.id) !== String(this.currentUser?.id)
      && allUsers.findIndex(candidate => String(candidate.id) === String(user.id)) === index
    ))
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

  _bindAwarenessEvents() {
    if (this._awarenessEventsBound || !this.mindMap?.on) return
    this._onNodeActive = (_node, nodeList = []) => {
      this._localActiveNodeUids = this._normalizeAwarenessNodeUids(
        nodeList.map(node => node?.uid).filter(Boolean)
      )
      if (!this.isApplyingRemote() && !this._paused) {
        this._sendAwareness(this._localActiveNodeUids)
      }
    }
    this._onNodeTreeRenderEnd = () => this._renderAllRemoteAwareness()
    this.mindMap.on('node_active', this._onNodeActive)
    this.mindMap.on('node_tree_render_end', this._onNodeTreeRenderEnd)
    this._awarenessEventsBound = true
  }

  _unbindAwarenessEvents() {
    if (!this._awarenessEventsBound) return
    this.mindMap?.off?.('node_active', this._onNodeActive)
    this.mindMap?.off?.('node_tree_render_end', this._onNodeTreeRenderEnd)
    this._awarenessEventsBound = false
  }

  _sendAwareness(nodeUids, force = false) {
    if (this._destroyed && !force) return false
    return this.wsClient.send({
      type: 'awareness',
      nodeUids: this._normalizeAwarenessNodeUids(nodeUids),
    })
  }

  _handleAwareness(data) {
    const user = this._normalizeUser(data?.user)
    if (!user || String(user.id) === String(this.currentUser?.id)) return
    const nodeUids = this._normalizeAwarenessNodeUids(data?.nodeUids ?? data?.update?.nodeUids)
    this._removeRemoteAwareness(user.id)
    if (!nodeUids.length) return
    this._remoteAwareness.set(String(user.id), { user, nodeUids })
    this._renderRemoteAwareness(user, nodeUids)
  }

  _renderRemoteAwareness(user, nodeUids) {
    for (const uid of nodeUids) {
      this.mindMap?.renderer?.findNodeByUid?.(uid)?.addUser?.(user)
    }
  }

  _renderAllRemoteAwareness() {
    for (const { user, nodeUids } of this._remoteAwareness.values()) {
      this._renderRemoteAwareness(user, nodeUids)
    }
  }

  _removeRemoteAwareness(userId) {
    const key = String(userId)
    const current = this._remoteAwareness.get(key)
    if (!current) return
    for (const uid of current.nodeUids) {
      this.mindMap?.renderer?.findNodeByUid?.(uid)?.removeUser?.(current.user)
    }
    this._remoteAwareness.delete(key)
  }

  _clearRemoteAwareness() {
    for (const userId of Array.from(this._remoteAwareness.keys())) {
      this._removeRemoteAwareness(userId)
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
      }, 'local-tag-definition')
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

  _mutateManagedTags(mutator, contentRevision) {
    if (Number.isInteger(contentRevision)) {
      this.setContentRevision(contentRevision)
      this.options.onContentRevision?.(contentRevision)
    }
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
    if (changed) this._requestYjsApply()
  }

  _handleTagReplaced(data) {
    if (!data?.sourceTagId || !data?.targetTagId || !data?.definition) return
    const sourceKey = String(data.sourceTagId)
    const targetKey = String(data.targetTagId)
    const targetDefinition = {
      ...data.definition,
      definitionRevision: data.definitionRevision ?? data.definition.definitionRevision,
    }
    this.tagDefinitions.delete(sourceKey)
    this.tagDefinitions.set(targetKey, targetDefinition)
    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        this.yTagDefinitions.delete(sourceKey)
        this.yTagDefinitions.set(targetKey, {
          ...targetDefinition,
          style: { ...(targetDefinition.style || {}) },
        })
      }, 'local-tag-definition')
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
    }, data.contentRevision)
  }

  _handleTagUnbound(data) {
    const ids = new Set((data?.tagIds || []).map(String))
    if (!ids.size) return
    this._localYjsChange = true
    try {
      this.doc.transact(() => {
        for (const id of ids) {
          this.tagDefinitions.delete(id)
          this.yTagDefinitions.delete(id)
        }
      }, 'local-tag-definition')
    } finally {
      this._localYjsChange = false
    }
    this._mutateManagedTags(tags => {
      const next = tags.filter(tag => !tag || typeof tag !== 'object' || !ids.has(String(tag.tagId)))
      return next.length === tags.length ? tags : next
    }, data.contentRevision)
  }

  _encodeUpdate(uint8Array) {
    return uint8ArrayToBase64(uint8Array)
  }

  _decodeUpdate(base64Str) {
    return base64ToUint8Array(base64Str)
  }
}
