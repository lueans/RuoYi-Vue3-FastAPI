import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import * as Y from 'yjs'

import {
  isRuntimeYjsUpdateTransportSafe,
  isStructuredPatchTransportSafe,
  YjsMindmapSync,
} from '../yjs-sync.js'
import {
  applyMindmapFileMetaIntents,
  captureMindmapFileMetaIntents,
  findConflictingMindmapFileMetaIntents,
} from '../mindmap-operations.js'
import { createMindmapSaveMutation } from '../mindmap-save-mutation.js'

function createMindmap(document) {
  let current = structuredClone(document)
  const calls = []
  const listeners = new Map()
  const markerUsers = new Map()
  const editingMarkerUsers = new Map()
  const nodeByUid = new Map()
  const registerNodes = (node) => {
    if (!node?.data?.uid) return
    const users = markerUsers.get(node.data.uid) || new Set()
    const editingUsers = editingMarkerUsers.get(node.data.uid) || new Set()
    markerUsers.set(node.data.uid, users)
    editingMarkerUsers.set(node.data.uid, editingUsers)
    nodeByUid.set(node.data.uid, {
      uid: node.data.uid,
      addUser(user) { users.add(String(user.sessionId || user.id)) },
      removeUser(user) { users.delete(String(user.sessionId || user.id)) },
      addEditingUser(user) { editingUsers.add(String(user.sessionId || user.id)) },
      removeEditingUser(user) { editingUsers.delete(String(user.sessionId || user.id)) },
    })
    for (const child of (node.children || [])) registerNodes(child)
  }
  registerNodes(current.root)
  return {
    calls,
    markerUsers,
    editingMarkerUsers,
    command: { clearHistory() {} },
    renderer: { findNodeByUid: uid => nodeByUid.get(uid) },
    view: {
      setTransformData(value) {
        current.view = structuredClone(value)
        calls.push({ type: 'view', value })
      },
    },
    on(event, handler) {
      const handlers = listeners.get(event) || new Set()
      handlers.add(handler)
      listeners.set(event, handlers)
    },
    off(event, handler) {
      listeners.get(event)?.delete(handler)
    },
    emit(event, ...args) {
      for (const handler of (listeners.get(event) || [])) handler(...args)
    },
    getData(full = false) {
      return full ? structuredClone(current) : structuredClone(current.root)
    },
    setFullData(next) {
      current = structuredClone(next)
      calls.push({ type: 'full', value: next })
    },
    updateData(root) {
      current.root = structuredClone(root)
      calls.push({ type: 'tree', value: root })
    },
  }
}

function createDocument() {
  return {
    root: {
      data: {
        uid: 'root',
        text: '根节点',
        image: 'old.png',
        tag: [{
          tagId: 8,
          categoryId: 3,
          text: '托管名称',
          style: { fill: '#f00' },
        }],
      },
      children: [{ data: { uid: 'child', text: '子节点' }, children: [] }],
    },
    layout: 'logicalStructure',
    theme: { template: 'default', config: { lineColor: '#999' } },
    view: { transform: { scaleX: 1, scaleY: 1 } },
    documentData: { simpleMindMap: { config: { imgTextMargin: 8 } } },
  }
}

function getStateDigest(encodedState) {
  return createHash('sha256')
    .update(Buffer.from(encodedState, 'base64'))
    .digest('hex')
}

function withStateDigests(payload) {
  const states = Array.isArray(payload.states) ? payload.states : [payload.state]
  return {
    ...payload,
    stateDigests: states.map(getStateDigest),
  }
}

function applyRemoteCrossNodeDelta(sync, domain, { upserts = {}, deletedKeys = [] }) {
  sync.doc.transact(() => {
    sync._applyCrossNodeStateDelta({
      [domain]: { upserts, deletedKeys },
    })
  }, 'remote')
}

function getCrossNodeRecord(sync, domain, key) {
  return sync._readCrossNodeState()[domain][key]
}

test('结构化修复补丁只接受有界可序列化的 simple-mind 扩展数据', () => {
  const createPatch = data => ({
    schemaVersion: 1,
    nodes: [{ uid: 'root', data, children: [] }],
    deletedNodeUids: [],
    applyMeta: false,
  })
  assert.equal(isStructuredPatchTransportSafe(createPatch({ text: '正常补丁' })), true)

  let deepValue = { value: 'leaf' }
  for (let index = 0; index < 70; index += 1) deepValue = { child: deepValue }
  assert.equal(isStructuredPatchTransportSafe(createPatch({ extension: deepValue })), false)

  const cyclicValue = {}
  cyclicValue.self = cyclicValue
  assert.equal(isStructuredPatchTransportSafe(createPatch({ extension: cyclicValue })), false)
  assert.equal(
    isStructuredPatchTransportSafe(createPatch({ text: '中'.repeat(800000) })),
    false,
  )
})

test('Yjs 实时帧使用与服务端一致的 5 MiB 解码后上限', () => {
  assert.equal(
    isRuntimeYjsUpdateTransportSafe(new Uint8Array(5 * 1024 * 1024)),
    true,
  )
  assert.equal(
    isRuntimeYjsUpdateTransportSafe(new Uint8Array(5 * 1024 * 1024 + 1)),
    false,
  )
  assert.equal(isRuntimeYjsUpdateTransportSafe(new Uint8Array()), false)
  assert.equal(isRuntimeYjsUpdateTransportSafe('not-an-update'), false)
})

test('不安全节点修复快照被省略但不会阻断 Yjs 增量生成', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document))
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'conditional-node-patch-v1',
  ])
  const sent = []
  sync.wsClient.send = data => {
    JSON.stringify(data)
    sent.push(data)
    return true
  }
  sync.start()
  let deepValue = { value: 'leaf' }
  for (let index = 0; index < 70; index += 1) deepValue = { child: deepValue }
  const updatedRoot = structuredClone(document.root)
  updatedRoot.data.text = '继续协作'
  updatedRoot.data.extension = deepValue
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: updatedRoot,
  }], 'unsafe-structured-patch')

  assert.equal(sent.length, 1)
  assert.equal(sent[0].type, 'update')
  assert.equal(typeof sent[0].update, 'string')
  assert.deepEqual(sent[0].patch, {
    schemaVersion: 1,
    nodes: [],
    deletedNodeUids: [],
    applyMeta: false,
  })
  sync.destroy()
})

test('旧服务端未确认条件补丁能力时只发送标准 Yjs 增量', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document))
  sync.initFromMindmap(document)
  sync.serverCapabilities.add('yjs-checkpoint-v1')
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = data => {
    sent.push(data)
    return true
  }
  sync.start()
  const updatedChild = structuredClone(document.root.children[0])
  updatedChild.data.text = '旧服务端兼容更新'

  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: updatedChild,
  }], 'legacy-server-update')

  assert.equal(sent.length, 1)
  assert.equal(typeof sent[0].update, 'string')
  assert.equal(sent[0].state, undefined)
  assert.equal(sent[0].patch, undefined)
  sync.destroy({ flushCheckpoint: false })
})

test('Yjs 手动重连只作用于存活且未暂停的编辑会话', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  const retryDetails = []
  sync.wsClient.retryNow = detail => {
    retryDetails.push(detail)
    return true
  }
  sync.isSynced.value = true

  assert.equal(sync.retryConnection(), true)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.syncError.value, '正在手动重新连接实时协作')
  assert.deepEqual(retryDetails, ['正在手动重新连接实时协作'])

  sync._paused = true
  assert.equal(sync.retryConnection(), false)
  assert.equal(retryDetails.length, 1)
  sync._paused = false
  sync.destroy({ flushCheckpoint: false })
  assert.equal(sync.retryConnection(), false)
  assert.equal(retryDetails.length, 1)
})

test('服务端认证把可写会话降级为只读时通知上层并禁止后续本地写入', () => {
  const document = createDocument()
  const readonlyChanges = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 4, {
    user: { id: 1, name: '用户 A' },
    onReadonlyChanged: (readonly, authData) => {
      readonlyChanges.push({ readonly, authData })
    },
  })
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.wsClient.handlers.onAuthenticated(
    { id: 1, name: '用户 A' },
    ['yjs-checkpoint-v1'],
    { readonly: true },
  )

  assert.equal(sync.readonly, true)
  assert.deepEqual(readonlyChanges, [{
    readonly: true,
    authData: { readonly: true },
  }])
  const stateBeforeLocalWrite = Y.encodeStateVector(sync.doc)
  sync.initFromMindmap(document, 'downgraded-reset')
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: {
      ...document.root.children[0],
      data: { uid: 'child', text: '不应写入' },
    },
  }], 'downgraded-edit')
  sync.syncDocumentMeta({ layout: 'mindMap' }, 'downgraded-meta')

  assert.deepEqual(Y.encodeStateVector(sync.doc), stateBeforeLocalWrite)
  assert.equal(
    sent.some(message => (
      message.type === 'update'
      || message.type === 'checkpoint'
      || message.type === 'request_seed'
    )),
    false,
  )
  sync.destroy({ flushCheckpoint: false })
})

test('初始化同时写入节点、标签引用和文档元数据', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(createDocument())

  assert.equal(sync.yNodes.size, 2)
  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{
    tagId: 8,
    categoryId: 3,
  }])
  assert.equal(sync.yMeta.get('layout'), 'logicalStructure')
  assert.deepEqual(sync.yMeta.get('theme'), createDocument().theme)
  assert.deepEqual(sync.yMeta.get('documentData'), createDocument().documentData)
  sync.destroy()
})

test('旧协作状态缺少 documentData 时不会伪造空配置覆盖服务器设置', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    getDocumentData: () => document.documentData,
  })
  sync.initFromMindmap({ ...document, documentData: undefined })
  sync.yMeta.delete('documentData')

  assert.equal(Object.prototype.hasOwnProperty.call(sync._readDocumentMeta(), 'documentData'), false)
  sync._completeSyncHandshake(true)
  assert.deepEqual(sync.yMeta.get('documentData'), document.documentData)
  sync.destroy()
})

test('新标签定义通过独立 Yjs 缓存同步且不复制进节点数据', () => {
  const sourceMindMap = createMindmap(createDocument())
  const sourceSync = new YjsMindmapSync(1, sourceMindMap)
  sourceSync.initFromMindmap(createDocument())

  const targetDocument = createDocument()
  targetDocument.root.data.tag = []
  const targetMindMap = createMindmap(targetDocument)
  const targetSync = new YjsMindmapSync(1, targetMindMap)
  Y.applyUpdate(targetSync.doc, Y.encodeStateAsUpdate(sourceSync.doc), 'remote')
  targetSync._syncTagDefinitionsFromYjs()
  targetSync._applyYjsToMindmap()

  assert.deepEqual(sourceSync.yNodes.get('root').get('data').get('tag'), [{
    tagId: 8,
    categoryId: 3,
  }])
  assert.equal(targetSync.tagDefinitions.get('8').text, '托管名称')
  assert.equal(targetSync.tagDefinitions.get('8').categoryId, 3)
  assert.equal(targetMindMap.getData().data.tag[0].text, '托管名称')
  sourceSync.destroy()
  targetSync.destroy()
})

test('漏掉业务广播后仍通过 Yjs 删除事件清理过期标签定义', () => {
  const document = createDocument()
  document.root.data.tag[0].definitionRevision = 4
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.wsClient.connect = () => {}
  sync.start()

  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('tagDefinitions').delete('8')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
  })

  assert.equal(sync.yTagDefinitions.has('8'), false)
  assert.equal(sync.tagDefinitions.has('8'), false)
  assert.deepEqual(mindMap.getData().data.tag, [{ tagId: 8, categoryId: 3 }])
  mindMap.emit('node_tree_render_end')
  remoteDoc.destroy()
  sync.destroy()
})

test('漏掉业务广播后仍通过 WebSocket Yjs 更新收敛标签名称和样式', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.wsClient.connect = () => {}
  sync.start()

  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('tagDefinitions').set('8', {
    tagId: 8,
    text: '重连后的名称',
    definitionRevision: 6,
    categoryId: 5,
    style: { fill: '#123456', color: '#fff' },
  })
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
  })

  assert.equal(sync.tagDefinitions.get('8').text, '重连后的名称')
  assert.equal(sync.tagDefinitions.get('8').definitionRevision, 6)
  assert.equal(mindMap.getData().data.tag[0].categoryId, 5)
  assert.equal(mindMap.getData().data.tag[0].text, '重连后的名称')
  assert.deepEqual(mindMap.getData().data.tag[0].style, {
    fill: '#123456',
    color: '#fff',
  })
  mindMap.emit('node_tree_render_end')
  remoteDoc.destroy()
  sync.destroy()
})

test('旧 Yjs 状态缺少定义 Map 时保留服务端详情中的标签样式', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)

  assert.equal(sync.yTagDefinitions.size, 0)
  assert.equal(sync._syncTagDefinitionsFromYjs(), false)
  assert.equal(sync.tagDefinitions.get('8').text, '托管名称')
  assert.deepEqual(sync.tagDefinitions.get('8').style, { fill: '#f00' })
  sync.destroy()
})

test('持久化标签定义按独立 revision 接受新版本并修复旧版本', () => {
  const document = createDocument()
  document.root.data.tag[0].definitionRevision = 4
  const newerSource = new YjsMindmapSync(1, createMindmap(document), 4)
  newerSource.initFromMindmap(document)
  newerSource.yTagDefinitions.set('8', {
    ...newerSource.yTagDefinitions.get('8'),
    text: '实时新名称',
    definitionRevision: 5,
  })
  const newerTarget = new YjsMindmapSync(1, createMindmap(document), 4)
  newerTarget.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  newerTarget.wsClient.send = () => true
  const newerState = newerTarget._encodeUpdate(Y.encodeStateAsUpdate(newerSource.doc))

  newerTarget._handleSyncInit(withStateDigests({
    contentRevision: 4,
    states: [newerState],
    stateSources: ['newer-tag-source'],
  }))

  assert.equal(newerTarget.yTagDefinitions.get('8').definitionRevision, 5)
  assert.equal(newerTarget.yTagDefinitions.get('8').text, '实时新名称')

  const olderSource = new YjsMindmapSync(1, createMindmap(document), 4)
  olderSource.initFromMindmap(document)
  olderSource.yTagDefinitions.set('8', {
    ...olderSource.yTagDefinitions.get('8'),
    text: '过期名称',
    definitionRevision: 3,
  })
  const olderTarget = new YjsMindmapSync(1, createMindmap(document), 4)
  olderTarget.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  olderTarget.wsClient.send = () => true
  const olderState = olderTarget._encodeUpdate(Y.encodeStateAsUpdate(olderSource.doc))

  olderTarget._handleSyncInit(withStateDigests({
    contentRevision: 4,
    states: [olderState],
    stateSources: ['older-tag-source'],
  }))

  assert.equal(olderTarget.yTagDefinitions.get('8').definitionRevision, 4)
  assert.equal(olderTarget.yTagDefinitions.get('8').text, '托管名称')

  newerSource.destroy()
  newerTarget.destroy()
  olderSource.destroy()
  olderTarget.destroy()
})

test('同 revision 标签定义内容不同会隔离而不是任意覆盖 HTTP 基线', () => {
  const document = createDocument()
  document.root.data.tag[0].definitionRevision = 4
  const source = new YjsMindmapSync(1, createMindmap(document), 4)
  source.initFromMindmap(document)
  source.yTagDefinitions.set('8', {
    ...source.yTagDefinitions.get('8'),
    text: '错误同版本名称',
  })
  const target = new YjsMindmapSync(1, createMindmap(document), 4)
  target.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  target.wsClient.send = message => {
    sent.push(message)
    return true
  }
  const state = target._encodeUpdate(Y.encodeStateAsUpdate(source.doc))

  target._handleSyncInit(withStateDigests({
    contentRevision: 4,
    states: [state],
    stateSources: ['conflicting-tag-source'],
  }))

  assert.equal(target.hasData(), false)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)
  assert.deepEqual(target._pendingCheckpointInvalidSources, [
    'conflicting-tag-source',
  ])
  source.destroy()
  target.destroy({ flushCheckpoint: false })
})

test('六千层 Yjs 节点可非递归重建并解析最深层托管标签', () => {
  const mindMap = {
    getData: () => ({ data: { uid: 'bootstrap' }, children: [] }),
    on() {},
    off() {},
    renderer: { findNodeByUid: () => null },
  }
  const sync = new YjsMindmapSync(1, mindMap)
  sync.tagDefinitions.set('8', {
    tagId: 8,
    text: '深层标签',
    style: { fill: '#f00' },
  })
  sync.doc.transact(() => {
    for (let index = 0; index < 6000; index += 1) {
      const uid = `node-${index}`
      const yNode = new Y.Map()
      const yData = new Y.Map()
      yData.set('uid', uid)
      if (index === 5999) yData.set('tag', [{ tagId: 8 }])
      yNode.set('data', yData)
      yNode.set(
        'children',
        Y.Array.from(index < 5999 ? [`node-${index + 1}`] : ['node-0']),
      )
      yNode.set('parentUid', index ? `node-${index - 1}` : '')
      sync.yNodes.set(uid, yNode)
    }
  }, 'remote')

  const tree = sync._rebuildTreeFromYjs()
  let cursor = tree
  let depth = 1
  while (cursor.children.length) {
    cursor = cursor.children[0]
    depth += 1
  }

  assert.equal(depth, 6000)
  assert.equal(cursor.children.length, 0)
  assert.equal(cursor.data.tag[0].text, '深层标签')
  assert.deepEqual(cursor.data.tag[0].style, { fill: '#f00' })
  sync.tagDefinitions.clear()
  const captured = sync._captureTagDefinitions(tree)
  assert.equal(captured.get('8').text, '深层标签')
  sync.destroy()
})

test('关联线、概要、外框和资源使用独立 Yjs 集合并可重建', () => {
  const document = createDocument()
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineTargetControlOffsets = [[1, 2]]
  document.root.data.associativeLinePoint = [[3, 4]]
  document.root.data.associativeLineText = { child: '关联' }
  document.root.data.generalization = [{ uid: 'summary-1', range: [0, 0], text: '概要' }]
  document.root.data.imgMap = { image1: 'data:image/png;base64,AA==' }
  document.root.children[0].data.outerFrame = { groupId: 'group-1', lineColor: '#0f0' }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)

  sync.initFromMindmap(document)

  const rootData = Object.fromEntries(sync.yNodes.get('root').get('data').entries())
  assert.equal(rootData.associativeLineTargets, undefined)
  assert.equal(rootData.generalization, undefined)
  assert.equal(rootData.imgMap, undefined)
  assert.equal(sync.yRelations.size, 1)
  assert.equal(sync.ySummaries.size, 1)
  assert.equal(sync.yGroups.size, 1)
  assert.equal(sync.yAssets.size, 1)
  const rebuilt = sync._rebuildTreeFromYjs()
  assert.deepEqual(rebuilt.data.associativeLineTargets, ['child'])
  assert.deepEqual(rebuilt.data.associativeLineTargetControlOffsets, [[1, 2]])
  assert.deepEqual(rebuilt.data.generalization, document.root.data.generalization)
  assert.deepEqual(rebuilt.data.imgMap, document.root.data.imgMap)
  assert.deepEqual(rebuilt.children[0].data.outerFrame, document.root.children[0].data.outerFrame)
  sync.destroy()
})

test('规范化后的跨节点持久化状态不会被误判为偏离 HTTP 基线', () => {
  const document = createDocument()
  // 故意省略控制点数组，覆盖拆分存储重建时产生规范化默认值的兼容场景。
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineText = { child: '关联' }
  document.root.children[0].data.outerFrame = {
    groupId: 'group-normalized',
    lineColor: '#0f0',
  }
  const source = new YjsMindmapSync(1, createMindmap(document), 5)
  source.initFromMindmap(document)
  const target = new YjsMindmapSync(1, createMindmap(document), 5)
  target.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  target.wsClient.send = message => {
    sent.push(message)
    return true
  }

  target._handleSyncInit(withStateDigests({
    contentRevision: 5,
    states: [target._encodeUpdate(Y.encodeStateAsUpdate(source.doc))],
    stateSources: ['normalized-cross-node-source'],
  }))

  assert.equal(target.yNodes.size, 2)
  assert.equal(target.connectionState.value, 'connected')
  assert.deepEqual(target._pendingCheckpointInvalidSources, [])
  assert.deepEqual(
    target._rebuildTreeFromYjs().data.associativeLineTargets,
    ['child'],
  )
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.deepEqual(checkpoint.replacesSources, ['normalized-cross-node-source'])

  target.destroy({ flushCheckpoint: false })
  source.destroy({ flushCheckpoint: false })
})

test('移除外框最后成员后的空分组壳不会让合法检查点偏离 HTTP 语义', () => {
  const groupedDocument = createDocument()
  groupedDocument.root.children[0].data.outerFrame = {
    groupId: 'group-empty-after-remove',
    lineColor: '#f00',
  }
  const currentDocument = structuredClone(groupedDocument)
  delete currentDocument.root.children[0].data.outerFrame
  const sourceMindMap = createMindmap(groupedDocument)
  const source = new YjsMindmapSync(1, sourceMindMap, 5)
  source.initFromMindmap(groupedDocument)
  sourceMindMap.updateData(currentDocument.root)
  source.onDataChangeDetail([{
    action: 'update',
    oldData: groupedDocument.root.children[0],
    data: currentDocument.root.children[0],
  }])
  const target = new YjsMindmapSync(1, createMindmap(currentDocument), 5)
  const persistedUpdate = Y.encodeStateAsUpdate(source.doc)

  assert.deepEqual(source._readCrossNodeState().groups, {})
  assert.equal(source.yGroups.size, 1)
  assert.equal(target._persistedStateMatchesInitialAuthoritativeDocument(persistedUpdate), true)

  source.destroy({ flushCheckpoint: false })
  target.destroy({ flushCheckpoint: false })
})

test('旧版节点内跨节点数据会迁移到独立 Yjs 集合', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(createDocument())
  sync.yRelations.clear()
  sync.yNodes.get('root').get('data').set('associativeLineTargets', ['child'])
  sync.yNodes.get('root').get('data').set('associativeLineText', { child: '旧状态' })

  assert.equal(sync._normalizeEmbeddedCrossNodeState(), true)

  assert.equal(sync.yNodes.get('root').get('data').has('associativeLineTargets'), false)
  assert.equal(sync.yRelations.get('assoc:root:child').text, '旧状态')
  assert.deepEqual(sync._rebuildTreeFromYjs().data.associativeLineTargets, ['child'])
  sync.destroy()
})

test('删除关联线会清理独立记录且节点不残留定义副本', () => {
  const document = createDocument()
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineTargetControlOffsets = [[1, 2]]
  document.root.data.associativeLinePoint = [[3, 4]]
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  const nextDocument = structuredClone(document)
  delete nextDocument.root.data.associativeLineTargets
  delete nextDocument.root.data.associativeLineTargetControlOffsets
  delete nextDocument.root.data.associativeLinePoint
  mindMap.updateData(nextDocument.root)

  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: nextDocument.root,
  }])

  assert.equal(sync.yRelations.size, 0)
  assert.equal(sync.yNodes.get('root').get('data').has('associativeLineTargets'), false)
  assert.equal(sync._rebuildTreeFromYjs().data.associativeLineTargets, undefined)
  sync.destroy()
})

test('不同客户端新增的关联记录通过独立键并发合并', () => {
  const document = createDocument()
  document.root.children.push({ data: { uid: 'child-2', text: '子节点 2' }, children: [] })
  const source = new YjsMindmapSync(1, createMindmap(document))
  source.initFromMindmap(document)
  const baseState = Y.encodeStateAsUpdate(source.doc)
  const first = new Y.Doc()
  const second = new Y.Doc()
  Y.applyUpdate(first, baseState)
  Y.applyUpdate(second, baseState)
  first.getMap('relations').set('assoc:root:child', {
    relationUid: 'assoc:root:child', relationType: 'associative_line',
    sourceUid: 'root', targetUid: 'child', sortOrder: 0, controlData: {},
  })
  second.getMap('relations').set('assoc:root:child-2', {
    relationUid: 'assoc:root:child-2', relationType: 'associative_line',
    sourceUid: 'root', targetUid: 'child-2', sortOrder: 1, controlData: {},
  })
  const merged = new Y.Doc()
  Y.applyUpdate(merged, Y.encodeStateAsUpdate(first))
  Y.applyUpdate(merged, Y.encodeStateAsUpdate(second))

  assert.deepEqual(
    new Set(merged.getMap('relations').keys()),
    new Set(['assoc:root:child', 'assoc:root:child-2']),
  )
  source.destroy()
  first.destroy()
  second.destroy()
  merged.destroy()
})

test('缺少 oldData 的节点快照只提交本地字段和子节点差异', () => {
  const document = createDocument()
  document.root.data.pluginConfig = {
    localSetting: 'old',
    remoteSetting: 'old',
  }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  sync.doc.transact(() => {
    sync.yNodes.get('root').get('data').set('fillColor', '#0000ff')
    sync.yNodes.get('root').get('data').set('pluginConfig', {
      localSetting: 'old',
      remoteSetting: 'remote',
    })
    const remoteSibling = new Y.Map()
    sync.yNodes.set('remote-sibling', remoteSibling)
    const remoteData = new Y.Map()
    remoteSibling.set('data', remoteData)
    remoteData.set('uid', 'remote-sibling')
    remoteData.set('text', '远端节点')
    remoteSibling.set('children', new Y.Array())
    remoteSibling.set('parentUid', 'root')
    sync.yNodes.get('root').get('children').push(['remote-sibling'])
  }, 'remote')

  const currentRoot = structuredClone(document.root)
  currentRoot.data.text = '已清除图片'
  currentRoot.data.pluginConfig.localSetting = 'local'
  delete currentRoot.data.image
  const localSibling = {
    data: { uid: 'local-sibling', text: '本地节点' },
    children: [],
  }
  currentRoot.children.push(localSibling)
  mindMap.updateData(currentRoot)

  sync.onDataChangeDetail([
    { action: 'create', data: localSibling },
    {
      action: 'update',
      data: currentRoot,
    },
  ])

  const data = Object.fromEntries(sync.yNodes.get('root').get('data').entries())
  assert.equal(data.image, undefined)
  assert.equal(data.text, '已清除图片')
  assert.equal(data.fillColor, '#0000ff')
  assert.deepEqual(data.pluginConfig, {
    localSetting: 'local',
    remoteSetting: 'remote',
  })
  assert.deepEqual(
    sync.yNodes.get('root').get('children').toArray(),
    ['child', 'local-sibling', 'remote-sibling'],
  )
  sync.destroy()
})

test('DOM 文本提交只更新真实差异并保留已接收的同节点及结构远端变更', () => {
  const document = createDocument()
  document.root.data.fillColor = '#ff0000'
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineText = { child: '旧关联文字' }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  const relationKey = 'assoc:root:child'
  const remoteRelation = structuredClone(sync.yRelations.get(relationKey))
  remoteRelation.text = '协作者更新的关联文字'
  sync.doc.transact(() => {
    // 模拟 prepared remote tree 已经进入 Y.Doc、但尚未替换旧 runtime。
    sync.yNodes.get('root').get('data').set('fillColor', '#0000ff')
    sync._applyCrossNodeStateDelta({
      relations: { upserts: { [relationKey]: remoteRelation }, deletedKeys: [] },
    })

    const remoteSibling = new Y.Map()
    sync.yNodes.set('remote-sibling', remoteSibling)
    const remoteSiblingData = new Y.Map()
    remoteSibling.set('data', remoteSiblingData)
    remoteSiblingData.set('uid', 'remote-sibling')
    remoteSiblingData.set('text', '协作者新增节点')
    remoteSibling.set('children', new Y.Array())
    remoteSibling.set('parentUid', 'root')
    sync.yNodeLedger.set('remote-sibling', true)
    sync.yNodes.get('root').get('children').push(['remote-sibling'])
  }, 'remote')

  const editedRoot = structuredClone(document.root)
  editedRoot.data.text = '本地 DOM 最后输入'
  const localSibling = {
    data: { uid: 'local-sibling', text: '本地新增节点' },
    children: [],
  }
  editedRoot.children.push(localSibling)
  sync.onDataChangeDetail([
    { action: 'create', data: localSibling },
    {
      action: 'update',
      oldData: document.root,
      data: editedRoot,
    },
  ])

  const mergedRoot = sync._rebuildTreeFromYjs()
  assert.equal(mergedRoot.data.text, '本地 DOM 最后输入')
  assert.equal(mergedRoot.data.fillColor, '#0000ff')
  assert.deepEqual(
    mergedRoot.children.map(node => node.data.uid),
    ['child', 'local-sibling', 'remote-sibling'],
  )
  assert.equal(
    getCrossNodeRecord(sync, 'relations', relationKey).text,
    '协作者更新的关联文字',
  )
  sync.destroy()
})

test('普通节点输入不会为运行时影子反复读取和克隆完整画布', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const originalGetData = mindMap.getData
  let getDataCalls = 0
  mindMap.getData = (...args) => {
    getDataCalls += 1
    return originalGetData(...args)
  }
  const sync = new YjsMindmapSync(1, mindMap)
  assert.equal(getDataCalls, 1)
  sync.initFromMindmap(document)
  getDataCalls = 0
  const updatedChild = structuredClone(document.root.children[0])
  updatedChild.data.text = '连续输入'

  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: updatedChild,
  }], 'typing-without-full-canvas-clone')

  assert.equal(getDataCalls, 0)
  assert.equal(sync.yNodes.get('child').get('data').get('text'), '连续输入')
  assert.equal(sync._runtimeNodeState.child.data.text, '连续输入')
  sync.destroy({ flushCheckpoint: false })
})

test('本地关系变更不会回滚另一条已接收的远端关系', () => {
  const document = createDocument()
  document.root.children.push({
    data: { uid: 'child-2', text: '子节点 2' },
    children: [],
  })
  document.root.data.associativeLineTargets = ['child', 'child-2']
  document.root.data.associativeLineText = {
    child: 'A-old',
    'child-2': 'B-old',
  }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  const remoteRelation = structuredClone(sync.yRelations.get('assoc:root:child-2'))
  remoteRelation.text = 'B-remote'
  applyRemoteCrossNodeDelta(sync, 'relations', {
    upserts: { 'assoc:root:child-2': remoteRelation },
  })

  const currentRoot = structuredClone(document.root)
  currentRoot.data.associativeLineText.child = 'A-local'
  mindMap.updateData(currentRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: currentRoot,
  }])

  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child').text, 'A-local')
  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child-2').text, 'B-remote')
  sync.destroy()
})

test('缺少 oldData 的节点快照可清理最后一条关系', () => {
  const document = createDocument()
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineText = { child: '待删除关系' }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  const currentRoot = structuredClone(document.root)
  delete currentRoot.data.associativeLineTargets
  delete currentRoot.data.associativeLineText
  mindMap.updateData(currentRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    data: currentRoot,
  }])

  assert.equal(sync.yRelations.size, 0)
  sync.destroy()
})

test('缺少 oldData 的普通更新不会回滚未渲染的远端关系', () => {
  const document = createDocument()
  document.root.children.push({
    data: { uid: 'child-2', text: '子节点 2' },
    children: [],
  })
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineText = { child: 'A-old' }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  const updatedRemoteRelation = structuredClone(sync.yRelations.get('assoc:root:child'))
  updatedRemoteRelation.text = 'A-remote'
  applyRemoteCrossNodeDelta(sync, 'relations', {
    upserts: {
      'assoc:root:child': updatedRemoteRelation,
      'assoc:root:child-2': {
      relationUid: 'assoc:root:child-2',
      relationType: 'associative_line',
      sourceUid: 'root',
      targetUid: 'child-2',
      text: 'C-remote',
      controlData: {},
      sortOrder: 1,
      },
    },
  })

  const currentRoot = structuredClone(document.root)
  currentRoot.data.text = '本地普通文字'
  mindMap.updateData(currentRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    data: currentRoot,
  }])

  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child').text, 'A-remote')
  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child-2').text, 'C-remote')
  sync.destroy()
})

test('第三方不可复制的关系元数据不会锁死本地同步标志或阻断普通节点编辑', () => {
  const document = createDocument()
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineText = { child: '原关联' }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  const previousCrossNodeShadow = sync._runtimeCrossNodeState
  const editedRoot = structuredClone(document.root)
  editedRoot.data.text = '普通字段仍应保存'
  editedRoot.data.associativeLineStyle = {
    child: { formatter: () => '插件运行时函数' },
  }
  mindMap.getData = full => (full ? { ...document, root: editedRoot } : editedRoot)

  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: editedRoot,
  }])

  assert.equal(sync.yNodes.get('root').get('data').get('text'), '普通字段仍应保存')
  assert.equal(sync.yRelations.get('assoc:root:child').text, '原关联')
  assert.equal(sync._runtimeCrossNodeState, previousCrossNodeShadow)
  assert.equal(sync._localYjsChange, false)
  assert.equal(sync._pendingStructuredPatch, null)
  sync.destroy()
})

test('删除前一条关系引起的顺移不会覆盖后一条关系的远端字段', () => {
  const document = createDocument()
  document.root.children.push({
    data: { uid: 'child-2', text: '子节点 2' },
    children: [],
  })
  document.root.data.associativeLineTargets = ['child', 'child-2']
  document.root.data.associativeLineText = { child: 'A-old', 'child-2': 'B-old' }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  const remoteB = structuredClone(sync.yRelations.get('assoc:root:child-2'))
  remoteB.text = 'B-remote'
  remoteB.styleData = { lineColor: '#00f' }
  applyRemoteCrossNodeDelta(sync, 'relations', {
    upserts: { 'assoc:root:child-2': remoteB },
  })

  const currentRoot = structuredClone(document.root)
  currentRoot.data.associativeLineTargets = ['child-2']
  currentRoot.data.associativeLineText = { 'child-2': 'B-old' }
  mindMap.updateData(currentRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: currentRoot,
  }])

  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child'), undefined)
  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child-2').sortOrder, 0)
  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child-2').text, 'B-remote')
  assert.deepEqual(getCrossNodeRecord(sync, 'relations', 'assoc:root:child-2').styleData, {
    lineColor: '#00f',
  })
  sync.destroy()
})

test('远端删除关系后旧画布上的迟到编辑不会复活残缺记录', () => {
  const document = createDocument()
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineText = { child: '旧关系' }
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  applyRemoteCrossNodeDelta(sync, 'relations', {
    deletedKeys: ['assoc:root:child'],
  })

  const currentRoot = structuredClone(document.root)
  currentRoot.data.associativeLineText.child = '本地迟到编辑'
  mindMap.updateData(currentRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: currentRoot,
  }])

  assert.equal(getCrossNodeRecord(sync, 'relations', 'assoc:root:child'), undefined)
  assert.equal(sync._rebuildTreeFromYjs().data.associativeLineTargets, undefined)
  sync.destroy()
})

test('子节点重排同时更新概要的稳定端点', () => {
  const document = createDocument()
  document.root.children.push({
    data: { uid: 'child-2', text: '子节点 2' },
    children: [],
  })
  document.root.data.generalization = [{
    uid: 'summary-1',
    range: [0, 0],
    text: '第一项概要',
  }]
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  const remoteSummary = structuredClone(sync.ySummaries.get('root:summary-1'))
  remoteSummary.payload.text = '协作者修改的概要'
  applyRemoteCrossNodeDelta(sync, 'summaries', {
    upserts: { 'root:summary-1': remoteSummary },
  })

  const currentRoot = structuredClone(document.root)
  currentRoot.children.reverse()
  mindMap.updateData(currentRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: currentRoot,
  }])

  const summary = getCrossNodeRecord(sync, 'summaries', 'root:summary-1')
  assert.equal(summary.startChildUid, 'child-2')
  assert.equal(summary.endChildUid, 'child-2')
  assert.equal(summary.payload.text, '协作者修改的概要')
  assert.deepEqual(
    sync._rebuildTreeFromYjs().data.generalization[0].range,
    [0, 0],
  )
  sync.destroy()
})

test('本地概要内容更新不会覆盖未渲染的远端范围端点', () => {
  const document = createDocument()
  document.root.children.push({
    data: { uid: 'child-2', text: '子节点 2' },
    children: [],
  })
  document.root.data.generalization = [{
    uid: 'summary-1',
    range: [0, 0],
    text: '旧概要',
  }]
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)

  const remoteSummary = structuredClone(sync.ySummaries.get('root:summary-1'))
  remoteSummary.startChildUid = 'child-2'
  remoteSummary.endChildUid = 'child-2'
  applyRemoteCrossNodeDelta(sync, 'summaries', {
    upserts: { 'root:summary-1': remoteSummary },
  })

  const currentRoot = structuredClone(document.root)
  currentRoot.data.generalization[0].text = '本地概要内容'
  mindMap.updateData(currentRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: currentRoot,
  }])

  const merged = getCrossNodeRecord(sync, 'summaries', 'root:summary-1')
  assert.equal(merged.payload.text, '本地概要内容')
  assert.equal(merged.startChildUid, 'child-2')
  assert.equal(merged.endChildUid, 'child-2')
  sync.destroy()
})

test('富文本节点更新通过 Yjs 同步后保留完整 HTML 文本', () => {
  const sourceDocument = createDocument()
  sourceDocument.root.children[0].data.text = '<p>前额23</p>'
  sourceDocument.root.children[0].data.richText = true
  const sourceMindMap = createMindmap(sourceDocument)
  const sourceSync = new YjsMindmapSync(1, sourceMindMap)
  sourceSync.initFromMindmap(sourceDocument)

  const targetMindMap = createMindmap(sourceDocument)
  const targetSync = new YjsMindmapSync(1, targetMindMap)
  Y.applyUpdate(targetSync.doc, Y.encodeStateAsUpdate(sourceSync.doc), 'remote')

  const updatedChild = structuredClone(sourceDocument.root.children[0])
  updatedChild.data.text = '<p>协作验收临时节点</p>'
  sourceSync.onDataChangeDetail([{
    action: 'update',
    oldData: sourceDocument.root.children[0],
    data: updatedChild,
  }])
  Y.applyUpdate(targetSync.doc, Y.encodeStateAsUpdate(sourceSync.doc), 'remote')
  targetSync._applyYjsToMindmap()

  assert.equal(
    targetMindMap.getData().children[0].data.text,
    '<p>协作验收临时节点</p>',
  )
  assert.equal(targetMindMap.getData().children[0].data.richText, true)
  sourceSync.destroy()
  targetSync.destroy()
})

test('两个客户端从同一种子初始化后可用增量更新富文本', () => {
  const document = createDocument()
  document.root.children[0].data.text = '<p>前额23</p>'
  document.root.children[0].data.richText = true
  const seed = new YjsMindmapSync(1, createMindmap(document))
  seed.initFromMindmap(document)
  const seedState = Y.encodeStateAsUpdate(seed.doc)
  const admin = new YjsMindmapSync(1, createMindmap(document))
  const member = new YjsMindmapSync(1, createMindmap(document))
  Y.applyUpdate(admin.doc, seedState, 'remote')
  Y.applyUpdate(member.doc, seedState, 'remote')
  let incrementalUpdate
  member.doc.on('update', update => { incrementalUpdate = update })
  const updatedChild = structuredClone(document.root.children[0])
  updatedChild.data.text = '<p>唯一种子协作验收</p>'

  member.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: updatedChild,
  }])
  Y.applyUpdate(admin.doc, incrementalUpdate, 'remote')

  assert.equal(
    admin._rebuildTreeFromYjs().children[0].data.text,
    '<p>唯一种子协作验收</p>',
  )
  seed.destroy()
  admin.destroy()
  member.destroy()
})

test('远端消息通过增量和节点修复补丁自愈且无需完整状态', () => {
  const document = createDocument()
  const source = new YjsMindmapSync(1, createMindmap(document))
  source.initFromMindmap(document)
  const target = new YjsMindmapSync(1, createMindmap(document))
  target.serverCapabilities.add('conditional-node-patch-v1')
  Y.applyUpdate(target.doc, Y.encodeStateAsUpdate(source.doc), 'remote')
  let deletionUpdate
  source.doc.on('update', update => { deletionUpdate ||= update })
  source.doc.transact(() => {
    source.yNodes.get('child').get('data').delete('text')
  })
  source.doc.transact(() => {
    source.yNodes.get('child').get('data').set('text', '<p>完整状态修复</p>')
    source.yNodes.get('child').get('data').set('richText', true)
  })

  target._handleUpdate({
    update: target._encodeUpdate(deletionUpdate),
    patch: {
      schemaVersion: 1,
      nodes: [{
        uid: 'child',
        data: { uid: 'child', text: '<p>节点补丁修复</p>', richText: true },
        children: [],
      }],
      deletedNodeUids: [],
    },
  })

  assert.equal(
    target._rebuildTreeFromYjs().children[0].data.text,
    '<p>节点补丁修复</p>',
  )
  assert.equal(target.yNodeLedger.get('child'), true)
  source.destroy()
  target.destroy()
})

test('结构化补丁创建的自愈节点同步进入完整性账本', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document))
  sync.initFromMindmap(document)
  sync._applyStructuredPatch({
    schemaVersion: 1,
    nodes: [
      {
        uid: 'root',
        data: document.root.data,
        children: ['child', 'repaired-child'],
      },
      {
        uid: 'repaired-child',
        data: { uid: 'repaired-child', text: '补丁恢复节点' },
        children: [],
      },
    ],
    deletedNodeUids: [],
  })

  assert.equal(sync.yNodes.has('repaired-child'), true)
  assert.equal(sync.yNodeLedger.get('repaired-child'), true)
  assert.equal(sync._rebuildTreeFromYjs().children[1].data.text, '补丁恢复节点')
  sync.destroy({ flushCheckpoint: false })
})

test('损坏的运行期增量会在隔离文档中拒绝且不应用节点补丁', () => {
  const document = createDocument()
  const protocolErrors = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onProtocolError: error => protocolErrors.push(error),
  })
  sync.initFromMindmap(document)
  sync.isSynced.value = true
  const reconnects = []
  sync.wsClient.reconnect = detail => {
    reconnects.push(detail)
    return true
  }

  sync._handleUpdate({
    update: sync._encodeUpdate(new Uint8Array([1, 2, 3])),
    patch: {
      schemaVersion: 1,
      nodes: [{
        uid: 'child',
        data: { uid: 'child', text: '不应写入的补丁' },
        children: [],
      }],
      deletedNodeUids: [],
    },
  })

  assert.equal(sync._rebuildTreeFromYjs().children[0].data.text, '子节点')
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'degraded')
  assert.match(sync.syncError.value, /已隔离/)
  assert.equal(reconnects.length, 1)
  assert.equal(protocolErrors[0].code, 'invalid_yjs_update')
  sync.destroy()
})

test('损坏的旧版完整协作状态不会污染实时文档并触发恢复', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document))
  sync.initFromMindmap(document)
  let reconnectCount = 0
  sync.wsClient.reconnect = () => {
    reconnectCount += 1
    return true
  }

  sync._handleUpdate({
    state: sync._encodeUpdate(new Uint8Array([255, 255, 255])),
  })

  assert.equal(sync._rebuildTreeFromYjs().data.text, '根节点')
  assert.equal(sync.yNodes.size, 2)
  assert.equal(reconnectCount, 1)
  sync.destroy()
})

test('旧服务端未协商检查点时本地详情事务继续携带完整状态', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.serverCapabilities.add('conditional-node-patch-v1')
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  sent.length = 0
  const updatedChild = structuredClone(document.root.children[0])
  updatedChild.data.text = '<p>紧凑补丁</p>'

  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: updatedChild,
  }], 'mutation-live-1')

  const updateMessage = sent.find(message => message.type === 'update')
  assert.ok(updateMessage.update)
  assert.equal(updateMessage.clientMutationId, 'mutation-live-1')
  assert.ok(updateMessage.state)
  assert.deepEqual(updateMessage.patch, {
    schemaVersion: 1,
    nodes: [{
      uid: 'child',
      data: { uid: 'child', text: '<p>紧凑补丁</p>' },
      children: [],
      previousData: { uid: 'child', text: '子节点' },
      previousChildren: [],
    }],
    deletedNodeUids: [],
    applyMeta: false,
  })
  sync.destroy()
})

test('检查点协议下常规编辑只发送增量并周期补发完整状态', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'conditional-node-patch-v1',
  ])
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  const updatedChild = structuredClone(document.root.children[0])
  updatedChild.data.text = '<p>周期检查点</p>'

  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: updatedChild,
  }], 'mutation-checkpoint')

  const updateMessage = sent.find(message => message.type === 'update')
  assert.ok(updateMessage.update)
  assert.equal(updateMessage.state, undefined)
  assert.equal(updateMessage.patch.applyMeta, false)
  assert.equal(sync._checkpointDirty, true)
  assert.equal(sync._flushCheckpoint({ reschedule: false }), false)
  sync.setContentRevision(2, 'mutation-checkpoint')
  assert.equal(sync._flushCheckpoint({ reschedule: false }), true)
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.ok(checkpoint.state)
  assert.equal(checkpoint.contentRevision, 2)
  assert.equal(sync._checkpointDirty, false)
  sync.destroy()
})

test('未确认远端状态不会随内容版本推进被提升为检查点', () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '尚未由 HTTP 确认')
  sync._handleUpdate({ state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)) })
  sync._checkpointDirty = true
  sync._handleContentRevisionChanged({ contentRevision: 2 })

  assert.equal(sync.contentRevision, 1)
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.equal(sync.connectionState.value, 'stale')
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'unconfirmed_yjs_state')
  assert.equal(sync._flushCheckpoint({ reschedule: false }), false)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('Yjs 实时批次收到同 clientMutationId 的 HTTP 确认后不误判 stale', () => {
  const document = createDocument()
  let staleCount = 0
  let observedRevision = 0
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onStaleState: () => { staleCount += 1 },
    onContentRevision: revision => { observedRevision = revision },
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '已持久化协作内容')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    clientMutationId: 'mutation-remote-1',
    mutationUpdateSeq: 1,
    contentRevision: 1,
  })

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-remote-1',
    concurrentMerge: false,
    yjsUpdateCount: 1,
  })

  assert.equal(staleCount, 0)
  assert.equal(sync.contentRevision, 2)
  assert.equal(observedRevision, 2)
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('远端实时预览长期未收到 HTTP 保存确认时恢复云端权威版本', async () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    unconfirmedMutationTimeoutMs: 5,
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  sync._receivedServerState = true
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '尚未保存的实时预览')

  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    contentRevision: 1,
    clientMutationId: 'mutation-never-confirmed',
    mutationUpdateSeq: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'unconfirmed_mutation_timeout')
  assert.equal(sync.contentRevision, 1)
  assert.equal(sync.connectionState.value, 'stale')
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.equal(sync._unconfirmedMutationTimers.size, 0)
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('远端实时预览收到 HTTP 保存确认后取消未提交超时', async () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    unconfirmedMutationTimeoutMs: 5,
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  sync._receivedServerState = true
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '已经保存的实时预览')

  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    contentRevision: 1,
    clientMutationId: 'mutation-confirmed-before-timeout',
    mutationUpdateSeq: 1,
  })
  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-confirmed-before-timeout',
    yjsUpdateCount: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.deepEqual(staleEvents, [])
  assert.equal(sync._unconfirmedMutationTimers.size, 0)
  assert.equal(sync.contentRevision, 2)
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('滚动升级期间旧版无 mutationId 预览也不会永久停留在画布', async () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    unconfirmedMutationTimeoutMs: 5,
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  sync._receivedServerState = true
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '旧版未保存预览')

  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    contentRevision: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'legacy_unconfirmed_mutation_timeout')
  assert.equal(sync.connectionState.value, 'stale')
  assert.equal(sync._legacyUnconfirmedMutationTimer, null)
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('HTTP 确认先到且对应 Yjs 增量永久缺失时自动回源校准', async () => {
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    confirmedMutationDeliveryTimeoutMs: 5,
    onStaleState: data => staleEvents.push(data),
  })

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-missing-update',
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'confirmed_mutation_missing')
  assert.equal(sync.connectionState.value, 'stale')
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  sync.destroy({ flushCheckpoint: false })
})

test('HTTP 确认先到但 Yjs 增量随后到达时取消自动回源', async () => {
  const document = createDocument()
  let staleCount = 0
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    confirmedMutationDeliveryTimeoutMs: 5,
    onStaleState: () => { staleCount += 1 },
  })
  sync.initFromMindmap(document)
  sync._receivedServerState = true
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '迟到但完整的协作内容')

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-late-update',
    yjsUpdateCount: 1,
  })
  assert.equal(sync.contentRevision, 1)
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    contentRevision: 1,
    clientMutationId: 'mutation-late-update',
    mutationUpdateSeq: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(staleCount, 0)
  assert.equal(sync.contentRevision, 2)
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  assert.equal(sync._confirmedMutationDeliveryTimers.size, 0)
  assert.equal(
    sync.yNodes.get('child').get('data').get('text'),
    '迟到但完整的协作内容',
  )
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('Yjs 增量已收到但画布准备未完成时仍禁止推进保存 revision', async () => {
  const document = createDocument()
  let finishPreparation
  const preparation = new Promise(resolve => { finishPreparation = resolve })
  const revisions = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    confirmedMutationDeliveryTimeoutMs: 100,
    prepareDocument: () => preparation,
    onContentRevision: revision => revisions.push(revision),
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '等待渲染能力')

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-awaiting-canvas',
    yjsUpdateCount: 1,
  })
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    contentRevision: 1,
    clientMutationId: 'mutation-awaiting-canvas',
    mutationUpdateSeq: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 0))

  assert.equal(sync.contentRevision, 1)
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.deepEqual(revisions, [])

  finishPreparation()
  await new Promise(resolve => setTimeout(resolve, 0))

  assert.equal(sync.contentRevision, 2)
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  assert.deepEqual(revisions, [2])
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('同一 mutation 的全部有序 Yjs 更新应用后才消费 HTTP revision', async () => {
  const document = createDocument()
  const revisions = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    confirmedMutationDeliveryTimeoutMs: 100,
    onContentRevision: revision => revisions.push(revision),
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  const updates = []
  remoteDoc.on('update', update => updates.push(sync._encodeUpdate(update)))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '临时输入')
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '最终输入')

  sync._handleUpdate({
    update: updates[0],
    contentRevision: 1,
    clientMutationId: 'mutation-sequenced',
    mutationUpdateSeq: 1,
  })
  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-sequenced',
    yjsUpdateCount: 2,
  })
  await new Promise(resolve => setTimeout(resolve, 0))

  assert.equal(sync.contentRevision, 1)
  assert.deepEqual(revisions, [])
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.deepEqual(
    [...(sync._appliedRemoteMutationSequences.get('mutation-sequenced') || [])],
    [1],
  )
  sync._finishRemoteApplication()

  sync._handleUpdate({
    update: updates[1],
    contentRevision: 1,
    clientMutationId: 'mutation-sequenced',
    mutationUpdateSeq: 2,
  })
  await new Promise(resolve => setTimeout(resolve, 20))

  assert.equal(sync.contentRevision, 2)
  assert.deepEqual(revisions, [2])
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  assert.equal(sync.yNodes.get('child').get('data').get('text'), '最终输入')
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('同账号双标签页收到部分帧时乱序或丢失的 HTTP 确认都不会伪装成完整文档', async () => {
  const document = createDocument()
  const seed = new YjsMindmapSync(1, createMindmap(document), 1)
  seed.initFromMindmap(document)
  const seedUpdate = Y.encodeStateAsUpdate(seed.doc)
  const writer = new YjsMindmapSync(1, createMindmap(document), 1, {
    user: { id: 42, name: '同一账号' },
  })
  Y.applyUpdate(writer.doc, seedUpdate, 'remote')
  const updates = []
  writer.doc.on('update', update => updates.push(writer._encodeUpdate(update)))
  writer.yNodes.get('child').get('data').set('text', '已收到的第一帧')
  writer.yNodes.get('child').get('data').set('text', '缺失的第二帧')

  const confirmedStaleEvents = []
  const confirmedReceiver = new YjsMindmapSync(1, createMindmap(document), 1, {
    user: { id: 42, name: '同一账号' },
    confirmedMutationDeliveryTimeoutMs: 5,
    onStaleState: data => confirmedStaleEvents.push(data),
  })
  Y.applyUpdate(confirmedReceiver.doc, seedUpdate, 'remote')
  confirmedReceiver.serverCapabilities.add('yjs-mutation-sequence-v1')
  confirmedReceiver._receivedServerState = true
  confirmedReceiver._handleUpdate({
    update: updates[0],
    contentRevision: 1,
    clientMutationId: 'same-account-partial-confirmed',
    mutationUpdateSeq: 1,
  })
  await Promise.resolve()
  confirmedReceiver._finishRemoteApplication()
  confirmedReceiver._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'same-account-partial-confirmed',
    yjsUpdateCount: 2,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(confirmedReceiver.contentRevision, 1)
  assert.equal(
    confirmedReceiver.yNodes.get('child').get('data').get('text'),
    '已收到的第一帧',
  )
  assert.equal(confirmedStaleEvents.at(-1)?.reason, 'confirmed_mutation_missing')

  const lostAckStaleEvents = []
  const lostAckReceiver = new YjsMindmapSync(1, createMindmap(document), 1, {
    user: { id: 42, name: '同一账号' },
    unconfirmedMutationTimeoutMs: 5,
    onStaleState: data => lostAckStaleEvents.push(data),
  })
  Y.applyUpdate(lostAckReceiver.doc, seedUpdate, 'remote')
  lostAckReceiver.serverCapabilities.add('yjs-mutation-sequence-v1')
  lostAckReceiver._receivedServerState = true
  lostAckReceiver._handleUpdate({
    update: updates[0],
    contentRevision: 1,
    clientMutationId: 'same-account-partial-lost-ack',
    mutationUpdateSeq: 1,
  })
  await Promise.resolve()
  lostAckReceiver._finishRemoteApplication()
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(lostAckReceiver.contentRevision, 1)
  assert.equal(lostAckStaleEvents.at(-1)?.reason, 'unconfirmed_mutation_timeout')
  seed.destroy({ flushCheckpoint: false })
  writer.destroy({ flushCheckpoint: false })
  confirmedReceiver.destroy({ flushCheckpoint: false })
  lostAckReceiver.destroy({ flushCheckpoint: false })
})

test('本地 Yjs 序号包含发送失败帧并把 HTTP 交付模式降级为立即回源', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 1)
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-mutation-sequence-v1',
  ])
  const sent = []
  sync.wsClient.send = (data) => {
    sent.push(data)
    return sent.length > 1
  }
  sync.start()
  const first = structuredClone(document.root.children[0])
  first.data.text = '第一次'
  const second = structuredClone(first)
  second.data.text = '第二次'

  sync.onDataChangeDetail([{
    action: 'update',
    data: first,
    oldData: document.root.children[0].data,
  }], 'mutation-local-sequence')
  sync.onDataChangeDetail([{
    action: 'update',
    data: second,
    oldData: first.data,
  }], 'mutation-local-sequence')

  const updates = sent.filter(item => item.type === 'update')
  assert.deepEqual(updates.map(item => item.mutationUpdateSeq), [1, 2])
  assert.equal(sync.getLocalMutationBaseRevision('mutation-local-sequence'), 1)
  assert.equal(sync.rebaseUnsentLocalMutation('mutation-local-sequence', 2), false)
  assert.equal(sync.getLocalMutationBaseRevision('mutation-local-sequence'), 1)
  assert.equal(sync.sealLocalMutation('mutation-local-sequence'), 2)
  assert.equal(sync.getLocalMutationDeliveryMode('mutation-local-sequence'), 'reload')
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  sync.setContentRevision(2, 'mutation-local-sequence')
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  sync.destroy({ flushCheckpoint: false })
})

test('超过服务端上限的本地 Yjs 帧在发送前降级为 HTTP 权威回源', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 1)
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-mutation-sequence-v1',
  ])
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()

  sync._withOutgoingClientMutationId('mutation-oversized-update', () => {
    sync.doc.transact(() => {
      sync.yNodes.get('child').get('data').set(
        'text',
        'x'.repeat(5 * 1024 * 1024 + 1024),
      )
    }, 'local-meta')
  })

  assert.equal(sent.some(message => message.type === 'update'), false)
  assert.equal(sync.sealLocalMutation('mutation-oversized-update'), 0)
  assert.equal(
    sync.getLocalMutationDeliveryMode('mutation-oversized-update'),
    'reload',
  )
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.equal(sync._flushCheckpoint({ reschedule: false }), false)
  sync.setContentRevision(2, 'mutation-oversized-update')
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  sync.destroy({ flushCheckpoint: false })
})

test('socket 断线或服务端协议拒绝会把尚未封存的本地批次降级为权威回源', () => {
  const createPendingSync = (mutationId) => {
    const document = createDocument()
    const sync = new YjsMindmapSync(1, createMindmap(document), 1)
    sync.initFromMindmap(document)
    sync.serverCapabilities = new Set([
      'yjs-checkpoint-v1',
      'yjs-mutation-sequence-v1',
    ])
    sync.wsClient.connect = () => {}
    sync.wsClient.send = () => true
    sync.start()
    const updated = structuredClone(document.root.children[0])
    updated.data.text = mutationId
    sync.onDataChangeDetail([{
      action: 'update',
      oldData: document.root.children[0],
      data: updated,
    }], mutationId)
    assert.equal(sync.getLocalMutationDeliveryMode(mutationId), 'sequenced')
    return sync
  }

  const protocolRejected = createPendingSync('mutation-protocol-rejected')
  const markProtocolMutationUnreliable = (
    protocolRejected._markPendingLocalMutationsUnreliable.bind(protocolRejected)
  )
  let protocolMarkCount = 0
  protocolRejected._markPendingLocalMutationsUnreliable = () => {
    protocolMarkCount += 1
    return markProtocolMutationUnreliable()
  }
  protocolRejected.wsClient.handlers.protocol_error({
    code: 'rate_limited',
    message: 'server rejected queued frame',
  })
  assert.equal(
    protocolRejected.getLocalMutationDeliveryMode('mutation-protocol-rejected'),
    'reload',
  )
  assert.equal(protocolMarkCount, 1)

  const disconnected = createPendingSync('mutation-disconnected')
  const markDisconnectedMutationUnreliable = (
    disconnected._markPendingLocalMutationsUnreliable.bind(disconnected)
  )
  let disconnectMarkCount = 0
  disconnected._markPendingLocalMutationsUnreliable = () => {
    disconnectMarkCount += 1
    return markDisconnectedMutationUnreliable()
  }
  disconnected.wsClient.handlers.onClose()
  assert.equal(
    disconnected.getLocalMutationDeliveryMode('mutation-disconnected'),
    'reload',
  )
  assert.equal(disconnectMarkCount, 1)
  protocolRejected.destroy({ flushCheckpoint: false })
  disconnected.destroy({ flushCheckpoint: false })
})

test('前一 HTTP 保存仍在途时下一批本地编辑不发送旧 revision 实时帧', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    canSendRealtimeMutation: () => false,
  })
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-mutation-sequence-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  const updated = structuredClone(document.root.children[0])
  updated.data.text = '保存期间继续输入'

  sync.onDataChangeDetail([{
    action: 'update',
    data: updated,
    oldData: document.root.children[0].data,
  }], 'mutation-during-previous-save')

  assert.equal(sent.some(message => message.type === 'update'), false)
  assert.equal(sync.getLocalMutationBaseRevision('mutation-during-previous-save'), 1)
  assert.equal(sync.rebaseUnsentLocalMutation('mutation-during-previous-save', 2), true)
  assert.equal(sync.getLocalMutationBaseRevision('mutation-during-previous-save'), 2)
  assert.equal(sync.sealLocalMutation('mutation-during-previous-save'), 0)
  assert.equal(sync.getLocalMutationDeliveryMode('mutation-during-previous-save'), 'reload')
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.equal(sync._checkpointDirty, true)
  sync.destroy({ flushCheckpoint: false })
})

test('同一远端序号仅接受完全相同的重传并拒绝异载荷', async () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  sync._receivedServerState = true
  sync.serverCapabilities.add('yjs-mutation-sequence-v1')
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  const updates = []
  remoteDoc.on('update', update => updates.push(sync._encodeUpdate(update)))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '第一帧')
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '冲突重用序号')

  const frame = {
    update: updates[0],
    contentRevision: 1,
    clientMutationId: 'mutation-duplicate-seq',
    mutationUpdateSeq: 1,
  }
  sync._handleUpdate(frame)
  sync._handleUpdate(frame)
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(staleEvents.length, 0)
  const trackedSequences = new Set([
    ...(sync._pendingRemoteMutationApplySequences.get('mutation-duplicate-seq') || []),
    ...(sync._appliedRemoteMutationSequences.get('mutation-duplicate-seq') || []),
  ])
  assert.deepEqual([...trackedSequences], [1])

  sync._handleUpdate({ ...frame, update: updates[1] })
  assert.equal(staleEvents.at(-1)?.reason, 'mutation_sequence_payload_conflict')
  assert.equal(sync.yNodes.get('child').get('data').get('text'), '第一帧')
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('已提交 mutation 丢弃迟到重传并对 seal 之外的额外序号回源', async () => {
  const document = createDocument()
  const staleEvents = []
  const mindmap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindmap, 1, {
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  sync._receivedServerState = true
  sync.serverCapabilities.add('yjs-mutation-sequence-v1')
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  let update
  remoteDoc.on('update', value => { update = sync._encodeUpdate(value) })
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '已提交')
  const frame = {
    update,
    contentRevision: 1,
    clientMutationId: 'mutation-committed-late',
    mutationUpdateSeq: 1,
  }
  sync._handleUpdate(frame)
  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-committed-late',
    yjsUpdateCount: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 0))
  sync._finishRemoteApplication()
  assert.equal(sync.contentRevision, 2)

  sync._handleUpdate(frame)
  assert.equal(staleEvents.length, 0)
  sync._handleUpdate({ ...frame, mutationUpdateSeq: 2, contentRevision: 2 })
  assert.equal(staleEvents.at(-1)?.reason, 'committed_mutation_extra_update')
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('本地 mutation 的 WebSocket 与 HTTP 基线固定在首次修改 revision', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 5)
  sync.initFromMindmap(document)
  sync.serverCapabilities.add('yjs-checkpoint-v1')
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  const first = structuredClone(document.root.children[0])
  first.data.text = 'revision 5 输入'
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: first,
  }], 'mutation-fixed-base')
  sync.setContentRevision(6)
  const second = structuredClone(first)
  second.data.text = 'revision 变化后继续输入'
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: first,
    data: second,
  }], 'mutation-fixed-base')

  const updates = sent.filter(message => message.type === 'update')
  assert.deepEqual(updates.map(message => message.contentRevision), [5, 5])
  assert.equal(sync.getLocalMutationBaseRevision('mutation-fixed-base'), 5)
  sync.destroy({ flushCheckpoint: false })
})

test('序号超限或封存后迟到事务会废弃交付并禁止旧文档检查点', () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  sync.serverCapabilities.add('yjs-checkpoint-v1')
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  sync.markLocalMutation('mutation-overflow', 1)
  sync._outgoingMutationUpdateCounts.set('mutation-overflow', 10000)
  const changed = structuredClone(document.root.children[0])
  changed.data.text = '超限输入'
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changed,
  }], 'mutation-overflow')

  assert.equal(sync.getLocalMutationDeliveryMode('mutation-overflow'), 'reload')
  assert.equal(staleEvents.at(-1)?.reason, 'mutation_update_limit')
  assert.equal(sync._flushCheckpoint({ reschedule: false }), false)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)

  const sealedSync = new YjsMindmapSync(2, createMindmap(document), 1, {
    onStaleState: data => staleEvents.push(data),
  })
  sealedSync.initFromMindmap(document)
  sealedSync.serverCapabilities.add('yjs-checkpoint-v1')
  sealedSync.wsClient.send = () => true
  sealedSync.start()
  sealedSync.markLocalMutation('mutation-sealed', 1)
  sealedSync.sealLocalMutation('mutation-sealed')
  sealedSync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changed,
  }], 'mutation-sealed')
  assert.equal(sealedSync.getLocalMutationDeliveryMode('mutation-sealed'), 'reload')
  assert.equal(staleEvents.at(-1)?.reason, 'sealed_or_invalid_local_mutation')
  assert.equal(sealedSync._flushCheckpoint({ reschedule: false }), false)
  sync.destroy({ flushCheckpoint: false })
  sealedSync.destroy({ flushCheckpoint: false })
})

test('旧服务端缺少精确帧数时即使收到一帧也不会快进 revision', async () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    confirmedMutationDeliveryTimeoutMs: 5,
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '旧协议帧')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    contentRevision: 1,
    clientMutationId: 'legacy-unknown-count',
  })
  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'legacy-unknown-count',
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(sync.contentRevision, 1)
  assert.equal(staleEvents.at(-1)?.reason, 'confirmed_mutation_missing')
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('当前客户端自己的保存确认不等待 WebSocket 回环增量', async () => {
  let staleCount = 0
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    confirmedMutationDeliveryTimeoutMs: 5,
    onStaleState: () => { staleCount += 1 },
  })
  sync.markLocalMutation('mutation-local-save')

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-local-save',
    authoritativeReloadRequired: false,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(staleCount, 0)
  assert.equal(sync.contentRevision, 2)
  assert.equal(sync._confirmedMutationDeliveryTimers.size, 0)
  sync.destroy({ flushCheckpoint: false })
})

test('AI 直写预览延后自身 revision 广播并在结束时只消费最新版本', () => {
  const staleEvents = []
  let deferAiRevision = true
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    shouldDeferContentRevision: data => (
      deferAiRevision && String(data?.clientMutationId || '').startsWith('ai:job-direct:')
    ),
    onStaleState: data => staleEvents.push(data),
  })

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'ai:job-direct:1',
    authoritativeReloadRequired: true,
    yjsUpdateCount: 0,
  })
  sync._handleContentRevisionChanged({
    contentRevision: 3,
    clientMutationId: 'ai:job-direct:2',
    authoritativeReloadRequired: true,
    yjsUpdateCount: 0,
  })

  assert.equal(sync.contentRevision, 1)
  assert.deepEqual(staleEvents, [])
  assert.equal(sync._deferredContentRevision?.contentRevision, 3)

  deferAiRevision = false
  assert.equal(sync.flushDeferredContentRevision(), true)
  assert.equal(sync.flushDeferredContentRevision(), false)
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].contentRevision, 3)
  assert.equal(staleEvents[0].reason, 'concurrent_merge')
  sync.destroy({ flushCheckpoint: false })
})

test('本地权威保存广播必须等 HTTP 响应后才解除检查点栅栏', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1)
  sync.initFromMindmap(createDocument())
  sync.serverCapabilities.add('yjs-checkpoint-v1')
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.markLocalMutation('mutation-local-authoritative', 1)
  sync._checkpointDirty = true

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-local-authoritative',
    authoritativeReloadRequired: true,
    yjsUpdateCount: 1,
  })

  assert.equal(sync.contentRevision, 1)
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.equal(sync._pendingLocalMutationIds.has('mutation-local-authoritative'), true)
  assert.equal(sync._flushCheckpoint({ reschedule: false }), false)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)

  sync.setContentRevision(2, 'mutation-local-authoritative')
  assert.equal(sync.contentRevision, 2)
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  assert.equal(sync._pendingLocalMutationIds.has('mutation-local-authoritative'), false)
  sync.destroy({ flushCheckpoint: false })
})

test('已同步客户端忽略迟到和重复的权威 revision 广播', async () => {
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 5, {
    confirmedMutationDeliveryTimeoutMs: 5,
    onStaleState: data => staleEvents.push(data),
  })
  sync.connectionState.value = 'connected'

  sync._handleContentRevisionChanged({
    contentRevision: 4,
    clientMutationId: 'mutation-obsolete-authoritative',
    authoritativeReloadRequired: true,
    yjsUpdateCount: 1,
  })
  sync._handleContentRevisionChanged({
    contentRevision: 5,
    clientMutationId: 'mutation-duplicate-authoritative',
    authoritativeReloadRequired: true,
    yjsUpdateCount: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(sync.contentRevision, 5)
  assert.equal(sync.connectionState.value, 'connected')
  assert.deepEqual(staleEvents, [])
  assert.equal(sync._confirmedMutationDeliveryTimers.size, 0)
  assert.equal(
    sync._confirmedRemoteMutationIds.get('mutation-obsolete-authoritative')?.notified,
    true,
  )
  assert.equal(
    sync._confirmedRemoteMutationIds.get('mutation-duplicate-authoritative')?.notified,
    true,
  )
  sync.destroy({ flushCheckpoint: false })
})

test('服务端并发合并会让对应 Yjs 批次回到权威校准', () => {
  const document = createDocument()
  let staleReason = ''
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onStaleState: data => { staleReason = data.reason },
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '需要服务端合并')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    clientMutationId: 'mutation-merge-1',
  })

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-merge-1',
    concurrentMerge: true,
  })

  assert.equal(staleReason, 'concurrent_merge')
  assert.equal(sync.connectionState.value, 'stale')
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('同节点不同字段的服务端并发合并无需重载完整画布', () => {
  const document = createDocument()
  let staleCount = 0
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onStaleState: () => { staleCount += 1 },
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '远端字段修改')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    clientMutationId: 'mutation-field-merge',
    mutationUpdateSeq: 1,
  })

  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-field-merge',
    concurrentMerge: true,
    authoritativeReloadRequired: false,
    yjsUpdateCount: 1,
  })

  assert.equal(staleCount, 0)
  assert.equal(sync.contentRevision, 2)
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('乱序 revision 广播只在各自 Yjs 状态已应用后按连续顺序推进', async () => {
  const document = createDocument()
  const mindmap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindmap, 1)
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '批次一')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    clientMutationId: 'mutation-order-1',
    mutationUpdateSeq: 1,
  })
  mindmap.emit('node_tree_render_end')
  await new Promise(resolve => setTimeout(resolve, 0))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '批次二')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    clientMutationId: 'mutation-order-2',
    mutationUpdateSeq: 1,
  })

  sync._handleContentRevisionChanged({
    contentRevision: 3,
    clientMutationId: 'mutation-order-2',
    yjsUpdateCount: 1,
  })
  sync._handleContentRevisionChanged({
    contentRevision: 2,
    clientMutationId: 'mutation-order-1',
    yjsUpdateCount: 1,
  })

  assert.equal(sync.contentRevision, 3)
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('更早 revision 确认永久缺失时已应用的后续批次也会自动回源', async () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    confirmedMutationDeliveryTimeoutMs: 5,
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', 'revision 3')
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
    clientMutationId: 'mutation-gap-r3',
    mutationUpdateSeq: 1,
  })
  sync._handleContentRevisionChanged({
    contentRevision: 3,
    clientMutationId: 'mutation-gap-r3',
    yjsUpdateCount: 1,
  })
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(sync.contentRevision, 1)
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'confirmed_revision_gap')
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('HTTP 响应先更新本地版本时同版本广播仍会触发权威校准', () => {
  const document = createDocument()
  let staleCount = 0
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    onStaleState: () => { staleCount += 1 },
  })
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '并发内容')
  sync._handleUpdate({ state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)) })

  sync.setContentRevision(2)
  sync._handleContentRevisionChanged({ contentRevision: 2 })

  assert.equal(staleCount, 1)
  assert.equal(sync.connectionState.value, 'stale')
  remoteDoc.destroy()
  sync.destroy({ flushCheckpoint: false })
})

test('没有未确认远端状态时内容版本仍可正常推进', () => {
  let observedRevision = 0
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    onContentRevision: revision => { observedRevision = revision },
  })

  sync._handleContentRevisionChanged({ contentRevision: 2 })

  assert.equal(sync.contentRevision, 2)
  assert.equal(observedRevision, 2)
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  sync.destroy({ flushCheckpoint: false })
})

test('检查点协议通过补丁标志立即同步文档布局元数据', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document))
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'conditional-node-patch-v1',
  ])
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()

  sync.syncDocumentMeta({ layout: 'fishbone' }, 'mutation-layout')

  const updateMessage = sent.find(message => message.type === 'update')
  assert.equal(updateMessage.state, undefined)
  assert.deepEqual(updateMessage.patch, {
    schemaVersion: 1,
    nodes: [],
    deletedNodeUids: [],
    applyMeta: true,
  })
  assert.equal(sync._flushCheckpoint({ reschedule: false }), false)
  sync.setContentRevision(2, 'mutation-layout')
  sync.destroy()
  assert.ok(sent.some(message => message.type === 'checkpoint'))
})

test('远端紧凑元数据补丁会立即应用布局而无需等待完整检查点', () => {
  const document = createDocument()
  const source = new YjsMindmapSync(1, createMindmap(document))
  source.initFromMindmap(document)
  const targetMindMap = createMindmap(document)
  const target = new YjsMindmapSync(1, targetMindMap)
  target.serverCapabilities.add('conditional-node-patch-v1')
  Y.applyUpdate(target.doc, Y.encodeStateAsUpdate(source.doc), 'remote')
  let metaUpdate
  source.doc.on('update', (update, origin) => {
    if (origin === 'local-meta') metaUpdate = update
  })

  source.syncDocumentMeta({ layout: 'fishbone' })
  target._handleUpdate({
    update: target._encodeUpdate(metaUpdate),
    patch: {
      schemaVersion: 1,
      nodes: [],
      deletedNodeUids: [],
      applyMeta: true,
    },
  })

  assert.equal(targetMindMap.calls.at(-1).type, 'full')
  assert.equal(targetMindMap.calls.at(-1).value.layout, 'fishbone')
  source.destroy()
  target.destroy()
})

test('远端 Yjs 元数据先胜出时 HTTP mutation 仍冻结本地字段意图', async () => {
  const document = createDocument()
  const seed = new YjsMindmapSync(1, createMindmap(document))
  seed.initFromMindmap(document)
  const seedUpdate = Y.encodeStateAsUpdate(seed.doc)
  const firstMindMap = createMindmap(document)
  const secondMindMap = createMindmap(document)
  const first = new YjsMindmapSync(1, firstMindMap)
  const second = new YjsMindmapSync(1, secondMindMap)
  Y.applyUpdate(first.doc, seedUpdate, 'remote')
  Y.applyUpdate(second.doc, seedUpdate, 'remote')

  // Concurrent Y.Map writes with the same logical clock resolve by client ID.
  // Make the lower-ID client the local editor so the remote value deterministically wins.
  const local = first.doc.clientID < second.doc.clientID ? first : second
  const remote = local === first ? second : first
  const localMindMap = local === first ? firstMindMap : secondMindMap
  const operations = [{ type: 'file.document_data.update' }]
  const localDocumentData = { simpleMindMap: { config: { imgTextMargin: 17 } } }
  const remoteDocumentData = { simpleMindMap: { config: { imgTextMargin: 31 } } }
  const localDocument = { ...document, documentData: localDocumentData }
  const intents = captureMindmapFileMetaIntents({}, localDocument, operations)
  let remoteUpdate
  remote.doc.on('update', update => { remoteUpdate = update })

  local.syncDocumentMeta({ documentData: localDocumentData }, 'local-file-meta')
  remote.syncDocumentMeta({ documentData: remoteDocumentData }, 'remote-file-meta')
  Y.applyUpdate(local.doc, remoteUpdate, 'remote')
  let appliedMeta
  local.options.onDocumentApplied = (_root, meta) => { appliedMeta = meta }
  await local._applyYjsToMindmap({ applyMeta: true })

  assert.deepEqual(appliedMeta.documentData, remoteDocumentData)
  assert.deepEqual(
    findConflictingMindmapFileMetaIntents(intents, appliedMeta),
    ['file.document_data.update'],
  )
  const protectedDocument = applyMindmapFileMetaIntents({
    ...localMindMap.getData(true),
    documentData: appliedMeta.documentData,
  }, intents)
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'local-file-meta',
    baseRevision: 1,
    operations,
    document: protectedDocument,
    viewChangeVersion: 0,
    yjsUpdateCount: 1,
  })
  assert.deepEqual(mutation.payload.documentData, localDocumentData)
  assert.notDeepEqual(mutation.payload.documentData, remoteDocumentData)

  seed.destroy({ flushCheckpoint: false })
  first.destroy({ flushCheckpoint: false })
  second.destroy({ flushCheckpoint: false })
})

test('节点删除由 Yjs 增量在远端清理整个子树及父节点引用', () => {
  const document = createDocument()
  document.root.children[0].children = [{
    data: { uid: 'grandchild', text: '孙节点' },
    children: [],
  }]
  const source = new YjsMindmapSync(1, createMindmap(document))
  source.initFromMindmap(document)
  const target = new YjsMindmapSync(1, createMindmap(document))
  Y.applyUpdate(target.doc, Y.encodeStateAsUpdate(source.doc), 'remote')
  let deletionUpdate
  source.doc.on('update', update => { deletionUpdate = update })
  source.onDataChangeDetail([{
    action: 'delete',
    oldData: { uid: 'child' },
  }])

  target._handleUpdate({
    update: target._encodeUpdate(deletionUpdate),
    patch: {
      schemaVersion: 1,
      nodes: [],
      deletedNodeUids: ['child'],
    },
  })

  assert.equal(target.yNodes.has('child'), false)
  assert.equal(target.yNodes.has('grandchild'), false)
  assert.deepEqual(target.yNodes.get('root').get('children').toArray(), [])
  source.destroy()
  target.destroy()
})

test('远端树覆盖画布前允许上层同步保护仍停留在浮层编辑器中的输入', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sequence = []
  const originalUpdateData = mindMap.updateData
  mindMap.updateData = root => {
    sequence.push('apply')
    originalUpdateData(root)
  }
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    beforeRemoteDocumentApply: (tree, targetMindMap, remoteDocument) => {
      sequence.push('protect')
      assert.strictEqual(targetMindMap, mindMap)
      assert.equal(tree.children.length, 0)
      assert.strictEqual(remoteDocument.root, tree)
      assert.equal(mindMap.getData().children.length, 1)
    },
  })
  sync.initFromMindmap(document)
  sync.yNodes.delete('child')
  sync.yNodes.get('root').get('children').delete(0, 1)

  assert.equal(await sync._applyYjsToMindmap(), true)
  assert.deepEqual(sequence, ['protect', 'apply'])
  assert.equal(mindMap.getData().children.length, 0)
  mindMap.emit('node_tree_render_end')
  sync.destroy()
})

test('AI 播放期间消费云端 Yjs 但不让完整权威树抢占展示画布', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  let deferredDocument = null
  let applyCount = 0
  const originalUpdateData = mindMap.updateData
  mindMap.updateData = root => {
    applyCount += 1
    originalUpdateData(root)
  }
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    shouldDeferRemoteDocumentApply: () => true,
    onRemoteDocumentDeferred: documentToCommit => {
      deferredDocument = structuredClone(documentToCommit)
    },
  })
  sync.initFromMindmap(document)
  sync.yNodes.delete('child')
  sync.yNodes.get('root').get('children').delete(0, 1)

  assert.equal(await sync._applyYjsToMindmap(), true)
  assert.equal(applyCount, 0)
  assert.equal(mindMap.getData().children.length, 1)
  assert.equal(deferredDocument.root.children.length, 0)
  sync.destroy()
})

test('远端画布半应用抛错时只回调一次并携带写入前的完整保护快照', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const protectedBeforeApply = mindMap.getData(true)
  const originalUpdateData = mindMap.updateData
  let applyFailure = null
  let callbackCount = 0
  mindMap.updateData = root => {
    originalUpdateData(root)
    throw new Error('模拟 renderer 半应用失败')
  }
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    captureDocumentBeforeRemoteApply: targetMindMap => targetMindMap.getData(true),
    onDocumentApplyError: (error, context) => {
      callbackCount += 1
      applyFailure = { error, context }
    },
  })
  sync.initFromMindmap(document)
  sync.yNodes.get('child').get('data').set('text', '远端新文本')

  await assert.rejects(
    sync._applyYjsToMindmap(),
    /模拟 renderer 半应用失败/,
  )
  assert.equal(callbackCount, 1)
  assert.equal(applyFailure.error.message, '模拟 renderer 半应用失败')
  assert.deepEqual(applyFailure.context.protectedDocument, protectedBeforeApply)
  assert.strictEqual(applyFailure.context.targetMindMap, mindMap)
  assert.strictEqual(applyFailure.context.sourceSync, sync)
  assert.equal(mindMap.getData().children[0].data.text, '远端新文本')

  sync.destroy({ flushCheckpoint: false })
})

test('远端并发移动合并后只保留 CRDT 胜出父级并维持当前根', () => {
  const document = createDocument()
  document.root.children = [
    {
      data: { uid: 'a', text: 'A' },
      children: [{ data: { uid: 'shared', text: '共享节点' }, children: [] }],
    },
    { data: { uid: 'b', text: 'B' }, children: [] },
    { data: { uid: 'c', text: 'C' }, children: [] },
  ]
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  const remoteNodes = remoteDoc.getMap('nodes')
  const replaceChildren = (uid, children) => {
    const yChildren = remoteNodes.get(uid).get('children')
    if (yChildren.length) yChildren.delete(0, yChildren.length)
    if (children.length) yChildren.push(children)
  }
  replaceChildren('a', [])
  replaceChildren('b', ['shared'])
  replaceChildren('c', ['shared', 'root'])
  remoteNodes.get('shared').set('parentUid', 'c')
  const orphan = new Y.Map()
  orphan.set('data', new Y.Map(Object.entries({ uid: 'orphan', text: '孤立节点' })))
  orphan.set('children', new Y.Array())
  orphan.set('parentUid', '')
  remoteNodes.set('orphan', orphan)

  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
  })

  const rebuilt = sync._rebuildTreeFromYjs()
  const rootChildUids = rebuilt.children.map(node => node.data.uid)
  const b = rebuilt.children.find(node => node.data.uid === 'b')
  const c = rebuilt.children.find(node => node.data.uid === 'c')
  assert.equal(rebuilt.data.uid, 'root')
  assert.deepEqual(rootChildUids, ['a', 'b', 'c', 'orphan'])
  assert.deepEqual(b.children, [])
  assert.deepEqual(c.children.map(node => node.data.uid), ['shared'])
  assert.equal(sync.yNodes.get('shared').get('parentUid'), 'c')
  assert.equal(sync.yNodes.get('root').get('parentUid'), '')
  mindMap.emit('node_tree_render_end')
  remoteDoc.destroy()
  sync.destroy()
})

test('同账号双浏览器的并发成环与后续重排不会因远端规范化产生副本分叉', () => {
  const createNode = (uid, children = []) => ({
    data: { uid, text: uid },
    children,
  })
  const document = {
    root: createNode('root', [
      createNode('c'),
      createNode('e', [createNode('f')]),
      createNode('x'),
    ]),
    layout: 'logicalStructure',
    theme: {},
    view: null,
  }
  const mindMapA = createMindmap(document)
  const mindMapB = createMindmap(document)
  const writerA = new YjsMindmapSync(127, mindMapA, 4, {
    user: { id: 1, name: '同账号用户' },
  })
  const writerB = new YjsMindmapSync(127, mindMapB, 4, {
    user: { id: 1, name: '同账号用户' },
  })
  const messagesA = []
  const messagesB = []
  writerA.wsClient.connect = () => {}
  writerB.wsClient.connect = () => {}
  writerA.serverCapabilities.add('conditional-node-patch-v1')
  writerB.serverCapabilities.add('conditional-node-patch-v1')
  writerA.wsClient.send = message => {
    messagesA.push(message)
    return true
  }
  writerB.wsClient.send = message => {
    messagesB.push(message)
    return true
  }
  writerA.start()
  writerB.start()
  writerA.initFromMindmap(document)
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))
  messagesA.length = 0
  messagesB.length = 0

  const findNode = (root, uid) => {
    const pending = [root]
    while (pending.length) {
      const node = pending.pop()
      if (node?.data?.uid === uid) return node
      pending.push(...(node?.children || []))
    }
    return null
  }
  const moveNodeToParentEnd = (root, uid, parentUid) => {
    const pending = [root]
    let movedNode = null
    while (pending.length) {
      const node = pending.pop()
      const childIndex = (node?.children || []).findIndex(
        child => child?.data?.uid === uid,
      )
      if (childIndex >= 0) {
        movedNode = node.children.splice(childIndex, 1)[0]
      }
      pending.push(...(node?.children || []))
    }
    assert.ok(movedNode)
    const targetParent = findNode(root, parentUid)
    assert.ok(targetParent)
    targetParent.children.push(movedNode)
    return root
  }
  const buildDetails = (before, after, nodeUids) => nodeUids.map(uid => ({
    action: 'update',
    oldData: findNode(before, uid),
    data: findNode(after, uid),
  }))
  const exchangeRound = ({ mutateA, mutateB, changedA, changedB, suffix }) => {
    const beforeA = writerA._rebuildTreeFromYjs()
    const beforeB = writerB._rebuildTreeFromYjs()
    const afterA = mutateA(structuredClone(beforeA))
    const afterB = mutateB(structuredClone(beforeB))
    mindMapA.updateData(afterA)
    mindMapB.updateData(afterB)
    writerA.onDataChangeDetail(
      buildDetails(beforeA, afterA, changedA),
      `topology-a-${suffix}`,
    )
    writerB.onDataChangeDetail(
      buildDetails(beforeB, afterB, changedB),
      `topology-b-${suffix}`,
    )
    const updateA = messagesA.find(message => message.type === 'update')
    const updateB = messagesB.find(message => message.type === 'update')
    assert.ok(updateA)
    assert.ok(updateB)
    writerA._handleUpdate(updateB)
    writerB._handleUpdate(updateA)
    messagesA.length = 0
    messagesB.length = 0
  }

  // Each move is valid against its local sibling tree, but together they form
  // c <-> e. Both replicas must only derive the same deterministic repair;
  // neither may write a private repair transaction into its canonical Y.Doc.
  exchangeRound({
    mutateA: root => moveNodeToParentEnd(root, 'c', 'e'),
    mutateB: root => moveNodeToParentEnd(root, 'e', 'c'),
    changedA: ['root', 'e'],
    changedB: ['root', 'c'],
    suffix: 'cycle',
  })
  assert.deepEqual(writerA._rebuildTreeFromYjs(), writerB._rebuildTreeFromYjs())

  // Reorder different branches afterwards. Receiver-local repair structs used
  // to leave a causal clock gap, so these otherwise independent updates never
  // integrated on the peer and one canvas promoted c/f to root.
  exchangeRound({
    mutateA: root => moveNodeToParentEnd(root, 'x', 'root'),
    mutateB: root => moveNodeToParentEnd(root, 'f', 'e'),
    changedA: ['root'],
    changedB: ['e'],
    suffix: 'reorder',
  })
  const treeA = writerA._rebuildTreeFromYjs()
  const treeB = writerB._rebuildTreeFromYjs()
  assert.deepEqual(treeA, treeB)
  assert.deepEqual(
    treeA.children.map(node => node.data.uid),
    ['x', 'e'],
  )
  assert.deepEqual(
    findNode(treeA, 'e').children.map(node => node.data.uid),
    ['c', 'f'],
  )

  // Full-state updates must also commute. This catches hidden client-local
  // structs even when a deterministic renderer happens to mask them visually.
  const stateA = Y.encodeStateAsUpdate(writerA.doc)
  const stateB = Y.encodeStateAsUpdate(writerB.doc)
  assert.deepEqual(stateA, stateB)
  const mergedAB = new Y.Doc()
  const mergedBA = new Y.Doc()
  Y.applyUpdate(mergedAB, stateA)
  Y.applyUpdate(mergedAB, stateB)
  Y.applyUpdate(mergedBA, stateB)
  Y.applyUpdate(mergedBA, stateA)
  assert.deepEqual(
    Y.encodeStateAsUpdate(mergedAB),
    Y.encodeStateAsUpdate(mergedBA),
  )
  assert.deepEqual(
    writerA._rebuildTreeFromYjs({ sourceDoc: mergedAB, applyTagDefinitions: false }),
    writerB._rebuildTreeFromYjs({ sourceDoc: mergedBA, applyTagDefinitions: false }),
  )

  mergedAB.destroy()
  mergedBA.destroy()
  writerA.destroy({ flushCheckpoint: false })
  writerB.destroy({ flushCheckpoint: false })
})

test('远程渲染结束前持续阻止异步 data_change 被当成本地修改', async () => {
  const mindMap = createMindmap(createDocument())
  const originalUpdateData = mindMap.updateData
  const applyingStates = []
  const structureWriteBlockedChanges = []
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    onStructureWriteBlockedChange: blocked => {
      structureWriteBlockedChanges.push(blocked)
    },
  })
  sync.initFromMindmap(createDocument())
  mindMap.updateData = root => {
    originalUpdateData(root)
    setTimeout(() => mindMap.emit('data_change', root), 10)
    setTimeout(() => mindMap.emit('node_tree_render_end'), 20)
  }
  mindMap.on('data_change', () => applyingStates.push(sync.isApplyingRemote()))

  sync._applyYjsToMindmap()
  await new Promise(resolve => setTimeout(resolve, 35))

  assert.deepEqual(applyingStates, [true])
  assert.equal(sync.isApplyingRemote(), false)
  assert.equal(sync.isStructureWriteBlocked(), false)
  assert.deepEqual(structureWriteBlockedChanges, [true, false])
  sync.destroy()
})

test('远端画布写入标记只覆盖同步变更调用栈而不吞掉随后本地输入', async () => {
  const mindMap = createMindmap(createDocument())
  const originalUpdateData = mindMap.updateData
  const mutationStates = []
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(createDocument())
  mindMap.updateData = root => {
    mutationStates.push(sync.isMutatingMindmapFromRemote())
    originalUpdateData(root)
    setTimeout(() => mutationStates.push(sync.isMutatingMindmapFromRemote()), 0)
  }

  assert.equal(await sync._applyYjsToMindmap(), true)
  await new Promise(resolve => setTimeout(resolve, 5))

  assert.deepEqual(mutationStates, [true, false])
  assert.equal(sync.isApplyingRemote(), true)
  mindMap.emit('node_tree_render_end')
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(sync.isApplyingRemote(), false)
  sync.destroy()
})

test('协作重渲染保留本地选中节点且不采用共享选中状态', async () => {
  const document = createDocument()
  document.root.data.isActive = true
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  mindMap.renderer.activeNodeList = [
    mindMap.renderer.findNodeByUid('child'),
  ]
  // 模拟 node_active 的 0ms 回调尚未刷新 awareness；runtime 才是 UI 真源。
  sync._localActiveNodeUids = ['root']

  assert.equal(await sync._applyYjsToMindmap(), true)
  assert.equal(mindMap.getData().data.isActive, false)
  assert.equal(mindMap.getData().children[0].data.isActive, true)
  mindMap.emit('node_tree_render_end')
  sync.destroy()
})

test('远端修改不同节点时保留并重放本地撤销历史', async () => {
  const document = createDocument()
  document.root.children.push({
    data: { uid: 'remote-child', text: '远端旧值' },
    children: [],
  })
  const beforeLocalEdit = structuredClone(document.root)
  document.root.children[0].data.text = '本地新值'
  const mindMap = createMindmap(document)
  let clearHistoryCount = 0
  const addHistory = () => {}
  addHistory.cancel = () => {}
  mindMap.command = {
    history: [JSON.stringify(beforeLocalEdit), JSON.stringify(document.root)],
    activeHistoryIndex: 1,
    isPause: false,
    mindMap: { opt: { maxHistoryCount: 500, maxHistoryMemoryBytes: 1024 * 1024 } },
    addHistory,
    getCopyData: () => mindMap.getData(),
    pause() { this.isPause = true },
    recovery() { this.isPause = false },
    clearHistory() {
      clearHistoryCount += 1
      this.history = []
      this.activeHistoryIndex = 0
    },
  }
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.yNodes.get('remote-child').get('data').set('text', '远端新值')

  assert.equal(await sync._applyYjsToMindmap(), true)

  assert.equal(clearHistoryCount, 0)
  assert.equal(mindMap.command.history.length, 2)
  const undoSnapshot = JSON.parse(mindMap.command.history[0])
  assert.equal(undoSnapshot.children[0].data.text, '子节点')
  assert.equal(undoSnapshot.children[1].data.text, '远端新值')
  assert.equal(mindMap.command.isPause, false)
  mindMap.emit('node_tree_render_end')
  sync.destroy()
})

test('远端与本地修改同一节点时丢弃旧撤销栈并建立当前静默基线', async () => {
  const document = createDocument()
  const beforeLocalEdit = structuredClone(document.root)
  document.root.children[0].data.text = '本地新值'
  const mindMap = createMindmap(document)
  let clearHistoryCount = 0
  let resetBaselineCount = 0
  const addHistory = () => {}
  addHistory.cancel = () => {}
  mindMap.command = {
    history: [JSON.stringify(beforeLocalEdit), JSON.stringify(document.root)],
    activeHistoryIndex: 1,
    isPause: false,
    mindMap: { opt: {} },
    addHistory,
    getCopyData: () => mindMap.getData(),
    pause() { this.isPause = true },
    recovery() { this.isPause = false },
    clearHistory() {
      clearHistoryCount += 1
      this.history = []
      this.activeHistoryIndex = 0
    },
    resetHistoryBaseline() {
      resetBaselineCount += 1
      this.history = [JSON.stringify(this.getCopyData())]
      this.activeHistoryIndex = 0
      return true
    },
  }
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.yNodes.get('child').get('data').set('text', '远端竞争值')

  assert.equal(await sync._applyYjsToMindmap(), true)

  assert.equal(clearHistoryCount, 0)
  assert.equal(resetBaselineCount, 1)
  assert.equal(mindMap.command.history.length, 1)
  assert.equal(
    JSON.parse(mindMap.command.history[0]).children[0].data.text,
    '远端竞争值',
  )
  assert.equal(mindMap.command.isPause, false)
  mindMap.emit('node_tree_render_end')
  sync.destroy()
})

test('远端标签定义刷新复用渲染结束保护且不会回传为本地修改', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const originalUpdateData = mindMap.updateData
  const applyingStates = []
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  mindMap.calls.length = 0
  mindMap.updateData = root => {
    originalUpdateData(root)
    setTimeout(() => mindMap.emit('data_change', root), 10)
    setTimeout(() => mindMap.emit('node_tree_render_end'), 20)
  }
  mindMap.on('data_change', () => applyingStates.push(sync.isApplyingRemote()))

  sync._handleTagDefinitionChanged({
    tagId: 8,
    definitionRevision: 2,
    definition: {
      tagId: 8,
      text: '远端新名称',
      style: { fill: '#0f0', color: '#111' },
    },
  })
  await new Promise(resolve => setTimeout(resolve, 35))

  assert.equal(mindMap.calls.length, 1)
  assert.equal(mindMap.getData().data.tag[0].text, '远端新名称')
  assert.deepEqual(mindMap.getData().data.tag[0].style, {
    fill: '#0f0',
    color: '#111',
  })
  assert.deepEqual(applyingStates, [true])
  assert.equal(sync.isApplyingRemote(), false)
  sync.destroy()
})

test('远端公式能力准备完成前不更新画布且期间本地状态不会被覆盖', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  let releaseFirstPrepare
  let prepareCount = 0
  const structureWriteBlockedChanges = []
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    prepareDocument: async () => {
      prepareCount += 1
      if (prepareCount === 1) {
        await new Promise(resolve => { releaseFirstPrepare = resolve })
      }
    },
    onStructureWriteBlockedChange: blocked => {
      structureWriteBlockedChanges.push(blocked)
    },
  })
  sync.initFromMindmap(document)
  sync.yNodes.get('child').get('data').set(
    'text',
    '<span class="ql-formula" data-value="x"></span>',
  )

  const firstApply = sync._applyYjsToMindmap()
  await Promise.resolve()
  assert.equal(sync.isApplyingRemote(), false)
  assert.equal(sync.isPreparingRemoteDocument(), true)
  assert.equal(sync.isStructureWriteBlocked(), true)
  assert.equal(mindMap.calls.length, 0)
  assert.deepEqual(structureWriteBlockedChanges, [true])

  sync.yNodes.get('child').get('data').set('text', '加载期间到达的新内容')
  releaseFirstPrepare()
  assert.equal(await firstApply, true)
  assert.equal(prepareCount, 2)
  assert.equal(mindMap.getData().children[0].data.text, '加载期间到达的新内容')
  assert.equal(structureWriteBlockedChanges.at(-1), true)
  mindMap.emit('node_tree_render_end')
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(sync.isStructureWriteBlocked(), false)
  assert.equal(structureWriteBlockedChanges.at(-1), false)
  sync.destroy()
})

test('远端渲染能力失败会有界重试并在恢复后清除错误', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  let prepareCount = 0
  let errorCount = 0
  let recoveredCount = 0
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    documentPrepareRetryDelays: [0],
    prepareDocument: async () => {
      prepareCount += 1
      if (prepareCount === 1) throw new Error('模拟模块下载失败')
    },
    onDocumentPrepareError: () => { errorCount += 1 },
    onDocumentPrepareRecovered: () => { recoveredCount += 1 },
  })
  sync.initFromMindmap(document)

  assert.equal(await sync._applyYjsToMindmap(), false)
  assert.match(sync.syncError.value, /渲染能力加载失败/)
  await new Promise(resolve => setTimeout(resolve, 10))

  assert.equal(prepareCount, 2)
  assert.equal(errorCount, 1)
  assert.equal(recoveredCount, 1)
  assert.equal(sync.syncError.value, '')
  assert.equal(mindMap.calls.at(-1).type, 'tree')
  mindMap.emit('node_tree_render_end')
  sync.destroy()
})

test('远端渲染能力超过重试上限后不会继续伪报正在重试', async () => {
  const document = createDocument()
  let exhaustedCount = 0
  const sync = new YjsMindmapSync(1, createMindmap(document), 1, {
    documentPrepareRetryDelays: [],
    prepareDocument: async () => { throw new Error('持续失败') },
    onDocumentPrepareExhausted: () => { exhaustedCount += 1 },
  })
  sync.initFromMindmap(document)

  assert.equal(await sync._applyYjsToMindmap(), false)
  assert.equal(exhaustedCount, 1)
  assert.match(sync.syncError.value, /请检查网络后刷新页面/)
  sync.destroy()
})

test('能力加载期间销毁实例不会让迟到结果更新旧画布', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  let releasePrepare
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    prepareDocument: () => new Promise(resolve => { releasePrepare = resolve }),
  })
  sync.initFromMindmap(document)

  const applying = sync._applyYjsToMindmap()
  await Promise.resolve()
  sync.destroy()
  releasePrepare()

  assert.equal(await applying, false)
  assert.equal(mindMap.calls.length, 0)
})

test('能力加载期间进入权威恢复会拒绝迟到的旧 Yjs 画布', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  let releasePrepare
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    prepareDocument: () => new Promise(resolve => { releasePrepare = resolve }),
    onStaleState: () => {},
  })
  sync.initFromMindmap(document)
  sync.yNodes.get('child').get('data').set('text', '不可信旧内容')

  const applying = sync._applyYjsToMindmap()
  await Promise.resolve()
  sync._handleStaleState({ currentRevision: 2, reason: 'test-fence' })
  releasePrepare()

  assert.equal(await applying, false)
  assert.equal(sync._authoritativeRevisionPending, 2)
  assert.equal(mindMap.calls.length, 0)
  assert.equal(mindMap.getData().children[0].data.text, '子节点')
  sync.destroy({ flushCheckpoint: false })
})

test('能力加载拒绝晚于权威恢复时不会覆盖 stale 状态或安排旧文档重试', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  let rejectPrepare
  let prepareErrorCount = 0
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    documentPrepareRetryDelays: [0],
    prepareDocument: () => new Promise((resolve, reject) => {
      rejectPrepare = reject
    }),
    onDocumentPrepareError: () => { prepareErrorCount += 1 },
    onStaleState: () => {},
  })
  sync.initFromMindmap(document)

  const applying = sync._applyYjsToMindmap()
  await Promise.resolve()
  sync._handleStaleState({ currentRevision: 2, reason: 'test-fence' })
  const staleMessage = sync.syncError.value
  rejectPrepare(new Error('已失效的能力加载失败'))

  assert.equal(await applying, false)
  assert.equal(sync.connectionState.value, 'stale')
  assert.equal(sync.syncError.value, staleMessage)
  assert.equal(prepareErrorCount, 0)
  assert.equal(sync._remotePrepareRetryTimer, null)
  assert.equal(sync._pendingRemoteApply, false)
  sync.destroy({ flushCheckpoint: false })
})

test('版本预览暂停期间到达的远端状态会在恢复后应用', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  const remoteDoc = new Y.Doc()
  Y.applyUpdate(remoteDoc, Y.encodeStateAsUpdate(sync.doc))
  remoteDoc.getMap('nodes').get('child').get('data').set('text', '预览期间远端更新')
  sync.pause()
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
  })

  assert.equal(mindMap.calls.length, 0)
  sync.resume()
  assert.equal(mindMap.getData().children[0].data.text, '预览期间远端更新')
  mindMap.emit('node_tree_render_end')
  remoteDoc.destroy()
  sync.destroy()
})

test('版本预览暂停期间的标签定义变化在恢复后统一重放', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.pause()

  sync._handleTagDefinitionChanged({
    tagId: 8,
    definitionRevision: 3,
    definition: {
      tagId: 8,
      text: '预览期间的新名称',
      style: { fill: '#00f' },
    },
  })

  assert.equal(mindMap.calls.length, 0)
  assert.equal(mindMap.getData().data.tag[0].text, '托管名称')
  sync.resume()
  assert.equal(mindMap.getData().data.tag[0].text, '预览期间的新名称')
  assert.deepEqual(mindMap.getData().data.tag[0].style, { fill: '#00f' })
  mindMap.emit('node_tree_render_end')
  sync.destroy()
})

test('远程元数据只应用语义配置，视图保持当前客户端工作区', () => {
  const mindMap = createMindmap(createDocument())
  let appliedMeta
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    onDocumentApplied: (_root, meta) => { appliedMeta = meta },
  })
  sync.initFromMindmap(createDocument())
  sync.yMeta.set('layout', 'fishbone')
  sync.yMeta.set('theme', { template: 'dark', config: {} })
  sync.yMeta.set('viewData', { transform: { scaleX: 1.5, scaleY: 1.5 } })
  sync.yMeta.set('documentData', { simpleMindMap: { config: { textContentMargin: 6 } } })

  sync._applyYjsToMindmap({ applyMeta: true })

  const call = mindMap.calls.at(-1)
  assert.equal(call.type, 'full')
  assert.equal(call.value.layout, 'fishbone')
  assert.equal(call.value.theme.template, 'dark')
  assert.equal(call.value.view.transform.scaleX, 1)
  assert.equal(mindMap.getData(true).view.transform.scaleX, 1)
  assert.equal(appliedMeta.documentData.simpleMindMap.config.textContentMargin, 6)
  sync.destroy()
})

test('旧版 Yjs 视图缓存不会覆盖本地视角或选区', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  mindMap.renderer.activeNodeList = [
    mindMap.renderer.findNodeByUid('child'),
  ]
  sync._localActiveNodeUids = ['root']
  sync.yMeta.set('viewData', {
    transform: { scaleX: 1.25, scaleY: 1.25, translateX: -200 },
  })

  assert.equal(await sync._applyYjsToMindmap({ applyMeta: true }), true)
  assert.deepEqual(mindMap.calls.map(call => call.type), ['tree'])
  assert.equal(mindMap.getData(true).view.transform.scaleX, 1)
  assert.equal(mindMap.getData().children[0].data.isActive, true)
  mindMap.emit('node_tree_render_end')
  sync.destroy()
})

test('远程节点选区会显示协作者并在成员离开时清理', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })

  sync._handleAwareness({
    user: { id: 2, name: '协作者' },
    nodeUids: ['child'],
  })
  assert.deepEqual([...mindMap.markerUsers.get('child')], ['2'])

  sync._handleRoomUsers({ users: [{ id: 1, name: '当前用户' }] })
  assert.deepEqual([...mindMap.markerUsers.get('child')], [])
  sync.destroy()
})

test('节点选区不构成编辑占用，实际文本编辑开始和结束会独立获取并释放短租约', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })

  sync._handleAwareness({
    sessionId: 'browser-b',
    user: { id: 2, name: '协作者' },
    nodeUids: ['child'],
    editingNodeUid: '',
  })
  assert.deepEqual([...mindMap.markerUsers.get('child')], ['browser-b'])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('child')], [])

  sync._handleAwareness({
    sessionId: 'browser-b',
    user: { id: 2, name: '协作者' },
    nodeUids: ['child'],
    editingNodeUid: 'child',
  })
  assert.deepEqual([...mindMap.editingMarkerUsers.get('child')], ['browser-b'])

  sync._handleAwareness({
    sessionId: 'browser-b',
    user: { id: 2, name: '协作者' },
    nodeUids: ['child'],
    editingNodeUid: '',
  })
  assert.deepEqual([...mindMap.markerUsers.get('child')], ['browser-b'])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('child')], [])
  sync.destroy()
})

test('同一账号的不同浏览器会话拥有独立选区且单个会话离开不误清其他会话', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })
  sync.sessionId = 'browser-a'

  sync._handleAwareness({
    sessionId: 'browser-a',
    user: { id: 1, name: '当前用户' },
    nodeUids: ['child'],
  })
  assert.deepEqual([...mindMap.markerUsers.get('child')], [])

  sync._handleAwareness({
    sessionId: 'browser-b',
    user: { id: 1, name: '当前用户' },
    nodeUids: ['child'],
    editingNodeUid: 'child',
  })
  sync._handleAwareness({
    sessionId: 'browser-c',
    user: { id: 1, name: '当前用户' },
    nodeUids: ['root'],
    editingNodeUid: 'root',
  })
  assert.deepEqual(
    [...mindMap.markerUsers.get('child')],
    ['browser-b'],
  )
  assert.deepEqual([...mindMap.editingMarkerUsers.get('child')], ['browser-b'])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('root')], ['browser-c'])

  sync._handleAwareness({
    sessionId: 'browser-b',
    user: { id: 1, name: '当前用户' },
    nodeUids: [],
    editingNodeUid: '',
  })
  assert.deepEqual([...mindMap.markerUsers.get('child')], [])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('child')], [])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('root')], ['browser-c'])

  const remoteSession = sync._remoteAwareness.get('session:browser-c')
  remoteSession.lastSeenAt = 0
  sync._expireStaleAwareness(Number.MAX_SAFE_INTEGER)
  assert.deepEqual([...mindMap.markerUsers.get('root')], [])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('root')], [])
  sync.destroy()
})

test('协作断线会清理过期在线成员和远程选区等待权威快照', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })

  sync._handleRoomUsers({ users: [
    { id: 1, name: '当前用户' },
    { id: 2, name: '协作者' },
  ] })
  sync._handleAwareness({
    user: { id: 2, name: '协作者' },
    nodeUids: ['child'],
    editingNodeUid: 'child',
  })
  assert.deepEqual(sync.collaborators.value.map(user => user.id), [2])
  assert.deepEqual([...mindMap.markerUsers.get('child')], ['2'])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('child')], ['2'])

  sync.wsClient.handlers.onClose()

  assert.deepEqual(sync.collaborators.value, [])
  assert.deepEqual([...mindMap.markerUsers.get('child')], [])
  assert.deepEqual([...mindMap.editingMarkerUsers.get('child')], [])
  assert.equal(sync.isSynced.value, false)
  sync.destroy({ flushCheckpoint: false })
})

test('版本预览暂停清理远程选区但保留仍在线的成员名单', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })
  sync.wsClient.send = () => true
  sync._handleRoomUsers({ users: [
    { id: 1, name: '当前用户' },
    { id: 2, name: '协作者' },
  ] })
  sync._handleAwareness({
    user: { id: 2, name: '协作者' },
    nodeUids: ['child'],
  })

  sync.pause()

  assert.deepEqual(sync.collaborators.value.map(user => user.id), [2])
  assert.deepEqual([...mindMap.markerUsers.get('child')], [])
  assert.equal(sync.isPaused(), true)
  sync.destroy({ flushCheckpoint: false })
})

test('本地节点选区通过 awareness 协议发送且限制数量', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._bindAwarenessEvents()

  mindMap.emit('node_active', null, [
    { uid: 'root' },
    { uid: 'root' },
    ...Array.from({ length: 120 }, (_, index) => ({ uid: `node-${index}` })),
  ])

  assert.equal(sent.at(-1).type, 'awareness')
  assert.equal(sent.at(-1).nodeUids[0], 'root')
  assert.equal(sent.at(-1).nodeUids.length, 100)
  assert.equal(sent.at(-1).editingNodeUid, '')
  sync.destroy()
})

test('本地实际文本编辑占用独立发布并在结束时立即释放', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._bindAwarenessEvents()

  mindMap.emit('node_active', null, [{ uid: 'child' }])
  mindMap.emit('node_text_edit_start', { uid: 'child' })
  assert.equal(sent.at(-1).editingNodeUid, 'child')
  assert.deepEqual(sent.at(-1).nodeUids, ['child'])

  mindMap.emit('node_text_edit_start', { uid: 'root' })
  assert.equal(sent.at(-1).editingNodeUid, 'root')
  const sentBeforeStaleEnd = sent.length
  mindMap.emit('node_text_edit_end', { uid: 'child' })
  assert.equal(sent.length, sentBeforeStaleEnd)
  assert.equal(sync._localEditingNodeUid, 'root')

  mindMap.emit('node_text_edit_end', { uid: 'root' })
  assert.equal(sent.at(-1).editingNodeUid, '')
  assert.deepEqual(sent.at(-1).nodeUids, ['child'])
  sync.destroy()
})

test('节点编辑在服务端未协商权威租约时 fail-closed', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  sync.wsClient.isAuthenticated = true

  assert.equal(await sync.acquireNodeEditLease('child'), false)
  assert.equal(sync.hasNodeEditLease('child'), false)
  assert.equal(sync.getNodeEditLeaseFailureReason(), 'unavailable')
  sync.destroy({ flushCheckpoint: false })
})

test('节点编辑租约在连接期间返回 connecting 而非误报占用', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  sync.wsClient.connectionState = 'reconnecting'

  assert.equal(await sync.acquireNodeEditLease('child'), false)
  assert.equal(sync.getNodeEditLeaseFailureReason(), 'connecting')
  sync.destroy({ flushCheckpoint: false })
})

function enableAuthoritativeNodeEditLease(sync) {
  sync.serverCapabilities.add('node-edit-lease-v1')
  sync.serverCapabilities.add('node-edit-lease-renewal-v1')
  sync.wsClient.isAuthenticated = true
  sync.isSynced.value = true
}

test('节点编辑租约在房间状态尚未同步或保存栅栏关闭时 fail-closed', async () => {
  let canAcquire = true
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    canAcquireNodeEditLease: () => canAcquire,
  })
  sync.serverCapabilities.add('node-edit-lease-v1')
  sync.wsClient.isAuthenticated = true
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  assert.equal(await sync.acquireNodeEditLease('child'), false)
  assert.equal(sync.getNodeEditLeaseFailureReason(), 'connecting')
  assert.equal(sent.length, 0)

  sync.isSynced.value = true
  canAcquire = false
  assert.equal(await sync.acquireNodeEditLease('child'), false)
  assert.equal(sync.getNodeEditLeaseFailureReason(), 'unavailable')
  assert.equal(sent.length, 0)
  sync.destroy({ flushCheckpoint: false })
})

test('初次租约等待状态阻止重复准入并在结果落定后通知保存层', async () => {
  let settledCount = 0
  const structureWriteBlockedChanges = []
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    onNodeEditLeaseSettled: () => { settledCount += 1 },
    onStructureWriteBlockedChange: blocked => {
      structureWriteBlockedChanges.push(blocked)
    },
  })
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  const summaryNode = {
    uid: 'runtime-summary',
    getData: key => key === 'uid' ? 'summary-persisted' : undefined,
  }

  const leasePromise = sync.acquireNodeEditLease(summaryNode)
  await Promise.resolve()
  assert.equal(sync.hasPendingNodeEditLeaseAcquire(), true)
  assert.equal(sync.isStructureWriteBlocked(), true)
  assert.equal(sync.canAcquireNodeEditLease(), false)
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.equal(request.nodeUid, 'summary-persisted')
  assert.equal(request.renewal, false)
  assert.deepEqual(structureWriteBlockedChanges, [true])

  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'summary-persisted',
    granted: true,
  })
  assert.equal(await leasePromise, true)
  assert.equal(sync.hasPendingNodeEditLeaseAcquire(), false)
  assert.equal(sync.isStructureWriteBlocked(), false)
  assert.equal(sync.isStructureWriteBlocked(), false)
  assert.equal(sync.hasNodeEditLease(summaryNode), true)
  assert.equal(settledCount, 1)
  assert.deepEqual(structureWriteBlockedChanges, [true, false])
  assert.equal(sync.releaseNodeEditLease(summaryNode), true)
  assert.equal(sent.at(-1).nodeUid, 'summary-persisted')
  assert.equal(settledCount, 2)
  sync.destroy({ flushCheckpoint: false })
})

test('初次租约等待远端准备和渲染都空闲后才出网', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  let releasePrepare
  let firstPrepare = true
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    prepareDocument: () => {
      if (!firstPrepare) return undefined
      firstPrepare = false
      return new Promise(resolve => { releasePrepare = resolve })
    },
  })
  sync.initFromMindmap(document)
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const remoteApply = sync._applyYjsToMindmap()
  await Promise.resolve()
  assert.equal(sync.isPreparingRemoteDocument(), true)
  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  assert.equal(
    sent.some(message => message.type === 'node_edit_lease_acquire'),
    false,
  )

  releasePrepare()
  assert.equal(await remoteApply, true)
  assert.equal(sync.isApplyingRemote(), true)
  assert.equal(
    sent.some(message => message.type === 'node_edit_lease_acquire'),
    false,
  )

  mindMap.emit('node_tree_render_end')
  await new Promise(resolve => setTimeout(resolve, 0))
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.ok(request)
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })

  assert.equal(await leasePromise, true)
  sync.destroy({ flushCheckpoint: false })
})

test('初次租约 grant 途中开始远端重绘时等待 render_end 后才准入', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.ok(request)
  sync._applyingRemote = true
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })
  let settled = false
  void leasePromise.then(() => { settled = true })
  await Promise.resolve()
  assert.equal(settled, false)

  sync._finishRemoteApplication()
  assert.equal(await leasePromise, true)
  assert.equal(settled, true)
  sync.destroy({ flushCheckpoint: false })
})

test('取消或销毁会唤醒尚未出网的远端空闲等待者', async () => {
  for (const action of ['release', 'destroy']) {
    const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
    enableAuthoritativeNodeEditLease(sync)
    const sent = []
    sync.wsClient.send = message => {
      sent.push(message)
      return true
    }
    sync._applyingRemote = true

    const leasePromise = sync.acquireNodeEditLease('child')
    await Promise.resolve()
    if (action === 'release') sync.releaseNodeEditLease('child')
    else sync.destroy({ flushCheckpoint: false })

    assert.equal(await leasePromise, false, action)
    assert.equal(
      sent.some(message => message.type === 'node_edit_lease_acquire'),
      false,
      action,
    )
    if (action === 'release') {
      sync._applyingRemote = false
      sync.destroy({ flushCheckpoint: false })
    }
  }
})

test('暂停和销毁会逐个归还所有在途租约请求的服务端所有权', async () => {
  for (const action of ['pause', 'destroy']) {
    const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
    enableAuthoritativeNodeEditLease(sync)
    const sent = []
    sync.wsClient.send = message => {
      sent.push(message)
      return true
    }
    const generation = sync._nodeEditLeaseAcquireGeneration
    const childLease = sync._requestNodeEditLease('child', { generation })
    const rootLease = sync._requestNodeEditLease('root', { generation })

    if (action === 'pause') sync.pause()
    else sync.destroy({ flushCheckpoint: false })

    assert.deepEqual(await Promise.all([childLease, rootLease]), [false, false])
    assert.deepEqual(
      sent
        .filter(message => message.type === 'node_edit_lease_release')
        .map(message => message.nodeUid)
        .sort(),
      ['child', 'root'],
      action,
    )
    if (action === 'pause') sync.destroy({ flushCheckpoint: false })
  }
})

test('取消待定初次租约会立即结算 Promise 并归还可能已授予的服务端锁', async () => {
  let settledCount = 0
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    onNodeEditLeaseSettled: () => { settledCount += 1 },
  })
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  assert.equal(sync.hasPendingNodeEditLeaseAcquire(), true)
  assert.equal(sync.releaseNodeEditLease(''), false)
  assert.equal(sync.hasPendingNodeEditLeaseAcquire(), true)
  assert.equal(sync.releaseNodeEditLease('child'), true)
  assert.equal(await leasePromise, false)
  assert.equal(sync.hasPendingNodeEditLeaseAcquire(), false)
  assert.equal(settledCount, 1)
  assert.deepEqual(sent.map(message => message.type), [
    'node_edit_lease_acquire',
    'node_edit_lease_release',
  ])
  sync.destroy({ flushCheckpoint: false })
})

test('迟到的无关节点释放不会使当前在途租约申请失效', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const request = sent.find(message => (
    message.type === 'node_edit_lease_acquire'
    && message.nodeUid === 'child'
  ))
  assert.ok(request)
  const generation = sync._nodeEditLeaseAcquireGeneration

  assert.equal(sync.releaseNodeEditLease('stale-node'), false)
  assert.equal(sync._nodeEditLeaseAcquireGeneration, generation)
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })

  assert.equal(await leasePromise, true)
  assert.equal(sync.hasNodeEditLease('child'), true)
  assert.equal(sent.some(message => (
    message.type === 'node_edit_lease_release'
    && message.nodeUid === 'child'
  )), false)
  sync.destroy({ flushCheckpoint: false })
})

test('销毁持有租约的实例不会由旧回调恢复页面自动保存', () => {
  let settledCount = 0
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    onNodeEditLeaseSettled: () => { settledCount += 1 },
  })
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._nodeEditLeaseUid = 'child'

  sync.destroy({ flushCheckpoint: false })

  assert.equal(settledCount, 0)
  assert.equal(
    sent.some(message => (
      message.type === 'node_edit_lease_release'
      && message.nodeUid === 'child'
    )),
    true,
  )
})

test('保存门闩关闭时现有节点租约仍可续期', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    canAcquireNodeEditLease: () => false,
  })
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._nodeEditLeaseUid = 'child'

  const renewal = sync._requestNodeEditLease('child', {
    generation: sync._nodeEditLeaseAcquireGeneration,
    renewal: true,
  })
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.ok(request)
  assert.equal(request.renewal, true)
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })
  assert.equal(await renewal, true)
  assert.equal(sync.hasNodeEditLease('child'), true)
  sync.destroy({ flushCheckpoint: false })
})

test('旧服务端未协商 owner 续租能力时使用带 revision 的兼容申请', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  sync.serverCapabilities.add('node-edit-lease-v1')
  sync.wsClient.isAuthenticated = true
  sync.isSynced.value = true
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._nodeEditLeaseUid = 'child'

  const renewal = sync._requestNodeEditLease('child', {
    generation: sync._nodeEditLeaseAcquireGeneration,
    renewal: true,
  })
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.ok(request)
  assert.equal(request.renewal, false)
  assert.equal(request.contentRevision, sync.contentRevision)
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })

  assert.equal(await renewal, true)
  assert.equal(sync.hasNodeEditLease('child'), true)
  sync.destroy({ flushCheckpoint: false })
})

test('续租帧发送失败会立即结束本地编辑态并尝试归还服务端锁', async () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  let lostNodeUid = ''
  mindMap.on('node_text_edit_lease_lost', (_node, nodeUid) => {
    lostNodeUid = nodeUid
  })
  sync.wsClient.send = message => {
    sent.push(message)
    return message.type !== 'node_edit_lease_acquire'
  }
  sync._nodeEditLeaseUid = 'child'

  assert.equal(await sync._requestNodeEditLease('child', {
    generation: sync._nodeEditLeaseAcquireGeneration,
    renewal: true,
  }), false)
  assert.equal(lostNodeUid, 'child')
  assert.equal(sync.hasActiveNodeEditLease(), false)
  assert.deepEqual(sent.map(message => message.type), [
    'node_edit_lease_acquire',
    'node_edit_lease_release',
  ])
  sync.destroy({ flushCheckpoint: false })
})

test('节点编辑仅在服务端 grant 后发布占用并在提交结束时释放', async () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    user: { id: 1, name: '当前用户' },
  })
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._bindAwarenessEvents()

  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.ok(request)
  assert.equal(request.contentRevision, 1)
  assert.equal(sync._localEditingNodeUid, '')
  sync._handleNodeEditLeaseResult({
    type: 'node_edit_lease_result',
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })
  assert.equal(await leasePromise, true)
  assert.equal(sync.hasNodeEditLease('child'), true)

  mindMap.emit('node_text_edit_start', { uid: 'child' })
  assert.equal(sent.at(-1).editingNodeUid, 'child')
  mindMap.emit('node_text_edit_end', { uid: 'child' })
  const releaseIndex = sent.findIndex(
    message => message.type === 'node_edit_lease_release',
  )
  const releasedAwarenessIndex = sent.findIndex(
    (message, index) => index > releaseIndex
      && message.type === 'awareness'
      && message.editingNodeUid === '',
  )
  assert.ok(releaseIndex >= 0)
  assert.equal(sent[releaseIndex].contentRevision, 1)
  assert.ok(releasedAwarenessIndex > releaseIndex)
  assert.equal(sync.hasNodeEditLease('child'), false)
  sync.destroy({ flushCheckpoint: false })
})

test('并发本地申请会串行化且迟到 grant 在下一节点申请前释放', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const firstPromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const firstRequest = sent.find(message => message.type === 'node_edit_lease_acquire')
  const secondPromise = sync.acquireNodeEditLease('root')
  sync._handleNodeEditLeaseResult({
    requestId: firstRequest.requestId,
    nodeUid: 'child',
    granted: true,
  })
  assert.equal(await firstPromise, false)
  await Promise.resolve()
  const releaseIndex = sent.findIndex(
    message => message.type === 'node_edit_lease_release' && message.nodeUid === 'child',
  )
  const secondRequestIndex = sent.findIndex(
    message => message.type === 'node_edit_lease_acquire' && message.nodeUid === 'root',
  )
  assert.ok(releaseIndex >= 0)
  assert.ok(secondRequestIndex > releaseIndex)
  const secondRequest = sent[secondRequestIndex]
  sync._handleNodeEditLeaseResult({
    requestId: secondRequest.requestId,
    nodeUid: 'root',
    granted: true,
  })
  assert.equal(await secondPromise, true)
  sync.destroy({ flushCheckpoint: false })
})

test('租约拒绝仅在健康连接上标记占用，服务故障保留 unavailable', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()))
  enableAuthoritativeNodeEditLease(sync)
  sync.wsClient.send = () => true

  const occupiedPromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const occupiedRequest = [...sync._pendingNodeEditLeaseRequests.keys()][0]
  sync._handleNodeEditLeaseResult({
    requestId: occupiedRequest,
    nodeUid: 'child',
    granted: false,
    reason: 'occupied',
  })
  assert.equal(await occupiedPromise, false)
  assert.equal(sync.getNodeEditLeaseFailureReason(), 'occupied')

  const unavailablePromise = sync.acquireNodeEditLease('root')
  await Promise.resolve()
  const unavailableRequest = [...sync._pendingNodeEditLeaseRequests.keys()][0]
  sync._handleNodeEditLeaseResult({
    requestId: unavailableRequest,
    nodeUid: 'root',
    granted: false,
    reason: 'unavailable',
  })
  assert.equal(await unavailablePromise, false)
  assert.equal(sync.getNodeEditLeaseFailureReason(), 'unavailable')
  sync.destroy({ flushCheckpoint: false })
})

test('续租被拒绝时先提交编辑器再显式归还可能仍存活的服务端租约', async () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  const lifecycle = []
  sync.wsClient.send = message => {
    sent.push(message)
    if (message.type === 'node_edit_lease_release') lifecycle.push('release')
    return true
  }
  mindMap.on('node_text_edit_lease_lost', (_node, nodeUid) => {
    lifecycle.push('commit')
    // 编辑器结束事件会经过公开 release，但本地 UID 已由 _lose 清空，
    // 因而只有结果处理器随后发送的一次 owner-only release 会出网。
    sync.releaseNodeEditLease(nodeUid)
  })
  sync._nodeEditLeaseUid = 'child'

  const renewal = sync._requestNodeEditLease('child', {
    generation: sync._nodeEditLeaseAcquireGeneration,
    renewal: true,
  })
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: false,
    reason: 'unavailable',
  })

  assert.equal(await renewal, false)
  assert.deepEqual(lifecycle, ['commit', 'release'])
  assert.equal(sync.hasActiveNodeEditLease(), false)
  assert.equal(
    sent.filter(message => message.type === 'node_edit_lease_release').length,
    1,
  )
  sync.destroy({ flushCheckpoint: false })
})

test('初次租约结果丢失时超时主动释放服务端可能已授予的租约', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 1, {
    nodeEditLeaseRequestTimeoutMs: 5,
  })
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  assert.equal(await sync.acquireNodeEditLease('child'), false)
  assert.deepEqual(sent.map(message => message.type), [
    'node_edit_lease_acquire',
    'node_edit_lease_release',
  ])
  assert.equal(sync.getNodeEditLeaseFailureReason(), 'unavailable')
  sync.destroy({ flushCheckpoint: false })
})

test('续租结果丢失时主动释放并立即结束本地编辑态', async () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    nodeEditLeaseRequestTimeoutMs: 5,
  })
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  const lifecycle = []
  let lostNodeUid = ''
  mindMap.on('node_text_edit_lease_lost', (_node, nodeUid) => {
    lostNodeUid = nodeUid
    lifecycle.push('commit')
    // 编辑器的 node_text_edit_end 会尝试释放，但 _loseNodeEditLease 已先
    // 清空本地所有权；超时处理随后只发送一次 owner-only release。
    sync.releaseNodeEditLease(nodeUid)
  })
  const originalSend = sync.wsClient.send
  sync.wsClient.send = message => {
    if (message.type === 'node_edit_lease_release') lifecycle.push('release')
    return originalSend(message)
  }
  sync._nodeEditLeaseUid = 'child'

  const renewed = await sync._requestNodeEditLease('child', {
    generation: sync._nodeEditLeaseAcquireGeneration,
    renewal: true,
  })

  assert.equal(renewed, false)
  assert.equal(sync.hasNodeEditLease('child'), false)
  assert.equal(lostNodeUid, 'child')
  assert.deepEqual(sent.map(message => message.type), [
    'node_edit_lease_acquire',
    'node_edit_lease_release',
  ])
  assert.deepEqual(sent.map(message => message.contentRevision), [1, 1])
  assert.deepEqual(lifecycle, ['commit', 'release'])
  assert.equal(
    sent.filter(message => message.type === 'node_edit_lease_release').length,
    1,
  )
  sync.destroy({ flushCheckpoint: false })
})

test('节点租约请求携带内容世代且连续版本推进不丢弃合法 grant', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 4)
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.equal(request.contentRevision, 4)

  sync.setContentRevision(5)
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })

  assert.equal(await leasePromise, true)
  assert.equal(sync.hasNodeEditLease('child'), true)
  assert.equal(
    sent.filter(message => message.type === 'node_edit_lease_release').length,
    0,
  )
  sync.destroy({ flushCheckpoint: false })
})

test('权威重置栅栏开启后迟到的旧世代 grant 会被归还', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 4)
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  sync._authoritativeRevisionPending = 5
  sync.isSynced.value = false
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })

  assert.equal(await leasePromise, false)
  assert.equal(sync.hasNodeEditLease('child'), false)
  assert.deepEqual(
    sent.filter(message => message.type === 'node_edit_lease_release'),
    [{
      type: 'node_edit_lease_release',
      nodeUid: 'child',
      contentRevision: 4,
    }],
  )
  sync.destroy({ flushCheckpoint: false })
})

test('其他节点保存推进内容版本时不打断当前节点的已持有租约', async () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 4)
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._nodeEditLeaseUid = 'child'

  const renewal = sync._requestNodeEditLease('child', {
    generation: sync._nodeEditLeaseAcquireGeneration,
    renewal: true,
  })
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  assert.equal(request.contentRevision, 4)
  sync.setContentRevision(5)
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })

  assert.equal(await renewal, true)
  assert.equal(sync.hasNodeEditLease('child'), true)
  assert.equal(
    sent.filter(message => message.type === 'node_edit_lease_release').length,
    0,
  )
  sync.destroy({ flushCheckpoint: false })
})

test('连接中断会立即使本地编辑租约失效并关闭编辑入口', async () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  enableAuthoritativeNodeEditLease(sync)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  let lostNodeUid = ''
  mindMap.on('node_text_edit_lease_lost', (_node, nodeUid) => {
    lostNodeUid = nodeUid
  })
  const leasePromise = sync.acquireNodeEditLease('child')
  await Promise.resolve()
  const request = sent.find(message => message.type === 'node_edit_lease_acquire')
  sync._handleNodeEditLeaseResult({
    requestId: request.requestId,
    nodeUid: 'child',
    granted: true,
  })
  assert.equal(await leasePromise, true)

  sync.wsClient.handlers.onClose()

  assert.equal(sync.hasNodeEditLease('child'), false)
  assert.equal(lostNodeUid, 'child')
  sync.destroy({ flushCheckpoint: false })
})

test('只读会话不能发布会被编辑端解释为节点占用的 awareness', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    readonly: true,
    user: { id: 2, name: '只读观察者' },
  })
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._bindAwarenessEvents()

  mindMap.emit('node_active', null, [{ uid: 'child' }])
  assert.equal(sent.length, 0)
  assert.equal(sync._awarenessRefreshTimer, null)

  sync.destroy({ flushCheckpoint: false })
  assert.deepEqual(sent, [{ type: 'awareness', nodeUids: [], editingNodeUid: '' }])
})

test('同步握手会合并服务端保存的多个并发 Yjs 状态', () => {
  const first = new Y.Doc()
  first.getMap('proof').set('fromA', 'A')
  const second = new Y.Doc()
  second.getMap('proof').set('fromB', 'B')
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)

  sync._handleSyncInit(withStateDigests({
    states: [
      sync._encodeUpdate(Y.encodeStateAsUpdate(first)),
      sync._encodeUpdate(Y.encodeStateAsUpdate(second)),
    ],
  }))

  assert.equal(sync.doc.getMap('proof').get('fromA'), 'A')
  assert.equal(sync.doc.getMap('proof').get('fromB'), 'B')
  sync.destroy()
  first.destroy()
  second.destroy()
})

test('与 HTTP 画布语义一致的持久化状态不会制造未确认冲突', () => {
  const document = createDocument()
  const source = new YjsMindmapSync(1, createMindmap(document), 4)
  source.initFromMindmap(document)
  const target = new YjsMindmapSync(1, createMindmap(document), 4)

  target._handleSyncInit({
    contentRevision: 4,
    states: [target._encodeUpdate(Y.encodeStateAsUpdate(source.doc))],
    stateSources: ['same-cloud-baseline'],
  })

  assert.equal(target.requiresAuthoritativeReconciliation(), false)
  source.destroy({ flushCheckpoint: false })
  target.destroy({ flushCheckpoint: false })
})

test('重连收到语义相同但独立 lineage 的完整状态时回源重建', () => {
  const document = createDocument()
  const source = new YjsMindmapSync(1, createMindmap(document), 4)
  const target = new YjsMindmapSync(1, createMindmap(document), 4)
  source.initFromMindmap(document)
  target.initFromMindmap(document)

  target._handleUpdate({
    state: target._encodeUpdate(Y.encodeStateAsUpdate(source.doc)),
    contentRevision: 4,
  })
  assert.equal(target.contentRevision, 4)
  assert.equal(target.requiresAuthoritativeReconciliation(), true)
  assert.equal(target.connectionState.value, 'stale')
  source.destroy({ flushCheckpoint: false })
  target.destroy({ flushCheckpoint: false })
})

test('同步握手确认已覆盖来源并发送安全压缩检查点', () => {
  const first = new Y.Doc()
  first.getMap('proof').set('fromA', 'A')
  const second = new Y.Doc()
  second.getMap('proof').set('fromB', 'B')
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 6)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit(withStateDigests({
    states: [
      sync._encodeUpdate(Y.encodeStateAsUpdate(first)),
      sync._encodeUpdate(Y.encodeStateAsUpdate(second)),
    ],
    stateSources: ['source-a', 'source-b'],
  }))

  assert.equal(sync.yNodes.size, 0)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)
  sync._handleSeedGranted({ contentRevision: 6 })

  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.deepEqual(checkpoint.replacesSources, ['source-a', 'source-b'])
  assert.equal(checkpoint.contentRevision, 6)
  const merged = new Y.Doc()
  Y.applyUpdate(merged, sync._decodeUpdate(checkpoint.state))
  assert.equal(merged.getMap('proof').get('fromA'), 'A')
  assert.equal(merged.getMap('proof').get('fromB'), 'B')

  merged.destroy()
  sync.destroy()
  first.destroy()
  second.destroy()
})

test('权威云端重置开始后忽略旧 revision 的在途 Yjs 增量', () => {
  const document = createDocument()
  const staleSource = new YjsMindmapSync(1, createMindmap(document), 6)
  staleSource.initFromMindmap(document)
  const target = new YjsMindmapSync(1, createMindmap(document), 6)
  target.initFromMindmap(document)
  const staleDocument = new Y.Doc()
  Y.applyUpdate(staleDocument, Y.encodeStateAsUpdate(staleSource.doc))
  staleDocument.getMap('nodes').get('root').get('data').set('text', '不应复活的旧内容')

  target._handleStaleState({
    contentRevision: 7,
    reason: 'authoritative_cloud_reset',
  })
  target._handleUpdate({
    state: target._encodeUpdate(Y.encodeStateAsUpdate(staleDocument)),
    contentRevision: 6,
  })

  assert.equal(target._rebuildTreeFromYjs().data.text, '根节点')
  assert.equal(target.connectionState.value, 'stale')
  target.destroy({ flushCheckpoint: false })
  staleSource.destroy({ flushCheckpoint: false })
  staleDocument.destroy()
})

test('服务端 stale_state 的 currentRevision 也会建立最新版本栅栏', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 6)
  sync._handleStaleState({
    currentRevision: 9,
    message: '协作状态已落后',
  })

  assert.equal(sync._authoritativeRevisionPending, 9)
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  sync.destroy({ flushCheckpoint: false })
})

test('乱序状态消息不能降低内容版本或待回源版本栅栏', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 6)

  sync.setContentRevision(9)
  sync.setContentRevision(7)
  sync._handleStaleState({ contentRevision: 12 })
  sync._handleStaleState({ contentRevision: 10 })

  assert.equal(sync.contentRevision, 9)
  assert.equal(sync._authoritativeRevisionPending, 12)
  sync.destroy({ flushCheckpoint: false })
})

test('document_reset 立即建立版本栅栏并阻止旧检查点和在途更新', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 7)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  sync._checkpointDirty = true
  let resetEvent = null
  sync.options.onDocumentReset = data => { resetEvent = data }
  sync._handleDocumentReset({
    contentRevision: 8,
    reason: 'authoritative_cloud_reset',
    message: '正在加载服务器内容',
  })

  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.equal(sync._flushCheckpoint(), false)
  assert.equal(sync.syncError.value, '正在加载服务器内容')
  assert.equal(resetEvent.contentRevision, 8)
  sync.destroy({ flushCheckpoint: false })
})

test('乱序到达的旧 document_reset 不会覆盖更新的待回源版本', () => {
  const resetEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 7, {
    onDocumentReset: data => resetEvents.push(data),
  })

  sync._handleDocumentReset({ contentRevision: 10 })
  sync._handleDocumentReset({ contentRevision: 9 })

  assert.equal(sync._authoritativeRevisionPending, 10)
  assert.equal(resetEvents.length, 1)
  assert.equal(resetEvents[0].contentRevision, 10)
  sync.destroy({ flushCheckpoint: false })
})

test('数据库心跳发现广播整段丢失时触发权威回源而不伪推进版本', () => {
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 7, {
    onStaleState: data => staleEvents.push(data),
  })

  sync._handleRevisionHeartbeat({ contentRevision: 9 })

  assert.equal(sync.contentRevision, 7)
  assert.equal(sync._authoritativeRevisionPending, 9)
  assert.equal(sync.connectionState.value, 'stale')
  assert.equal(staleEvents[0].reason, 'heartbeat_revision_ahead')
  sync.destroy({ flushCheckpoint: false })
})

test('同版本或旧版本数据库心跳不会打断正常编辑', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 7)

  sync._handleRevisionHeartbeat({ contentRevision: 7 })
  sync._handleRevisionHeartbeat({ contentRevision: 6 })

  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  assert.notEqual(sync.connectionState.value, 'stale')
  sync.destroy({ flushCheckpoint: false })
})

test('同步握手隔离损坏来源并用有效状态生成修复检查点', () => {
  const validDoc = new Y.Doc()
  validDoc.getMap('proof').set('valid', '保留内容')
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 7)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit(withStateDigests({
    states: [
      sync._encodeUpdate(Y.encodeStateAsUpdate(validDoc)),
      'not-valid-base64!',
    ],
    stateSources: ['valid-source', 'corrupt-source'],
  }))

  assert.equal(sync.doc.getMap('proof').get('valid'), '保留内容')
  assert.equal(sync.connectionState.value, 'degraded')
  assert.match(sync.syncError.value, /1 份异常/)
  assert.equal(sync.yNodes.size, 0)
  sync._handleSeedGranted({ contentRevision: 7 })
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.deepEqual(checkpoint.replacesSources, ['valid-source'])
  assert.deepEqual(checkpoint.invalidSources, ['corrupt-source'])
  const repaired = new Y.Doc()
  Y.applyUpdate(repaired, sync._decodeUpdate(checkpoint.state))
  assert.equal(repaired.getMap('proof').get('valid'), '保留内容')

  repaired.destroy()
  sync.destroy()
  validDoc.destroy()
})

test('全部持久化状态损坏时从 HTTP 主文档恢复并精确隔离来源', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 8)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit(withStateDigests({
    states: ['not-valid-base64!'],
    stateSources: ['corrupt-only'],
  }))

  assert.equal(sync.yNodes.size, 0)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)
  sync._handleSeedGranted({ contentRevision: 8 })
  assert.equal(sync.yNodes.size, 2)
  assert.equal(sync.yNodes.get('root').get('data').get('text'), '根节点')
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.equal(Object.hasOwn(checkpoint, 'replacesSources'), false)
  assert.deepEqual(checkpoint.invalidSources, ['corrupt-only'])

  const repaired = new Y.Doc()
  Y.applyUpdate(repaired, sync._decodeUpdate(checkpoint.state))
  assert.equal(repaired.getMap('nodes').size, 2)

  repaired.destroy()
  sync.destroy()
})

test('不含节点却携带跨节点引用的持久化状态会被隔离', () => {
  const orphaned = new Y.Doc()
  orphaned.getMap('relations').set('orphaned-relation', {
    startNodeUid: 'missing-a',
    endNodeUid: 'missing-b',
  })
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 6)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  const state = sync._encodeUpdate(Y.encodeStateAsUpdate(orphaned))

  sync._handleSyncInit(withStateDigests({
    contentRevision: 6,
    states: [state],
    stateSources: ['orphaned-cross-state'],
  }))

  assert.equal(sync.hasData(), false)
  assert.deepEqual(sync._pendingCheckpointInvalidSources, [
    'orphaned-cross-state',
  ])
  assert.equal(sent.some(message => message.type === 'request_seed'), true)
  sync.destroy({ flushCheckpoint: false })
  orphaned.destroy()
})

test('持久化来源数量超过协议上限时不创建无界临时文档', () => {
  const remote = new Y.Doc()
  remote.getMap('proof').set('oversized', true)
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 9)
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  const encoded = sync._encodeUpdate(Y.encodeStateAsUpdate(remote))

  sync._handleSyncInit({
    states: Array.from({ length: 33 }, () => encoded),
    stateSources: Array.from({ length: 33 }, (_, index) => `source-${index}`),
  })

  assert.equal(sync.doc.getMap('proof').has('oversized'), false)
  assert.equal(sync.yNodes.size, 0)
  assert.equal(sync.connectionState.value, 'degraded')
  assert.match(sync.syncError.value, /33 份异常/)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)

  sync._handleSeedGranted({ contentRevision: 9 })
  assert.equal(sync.yNodes.size, 2)
  assert.equal(sync.connectionState.value, 'connected')

  sync.destroy()
  remote.destroy()
})

test('同 lineage 重连会补齐语义已回退的 Yjs 时钟并继续接收后续增量', () => {
  const document = createDocument()
  const seed = new YjsMindmapSync(1, createMindmap(document), 4)
  seed.initFromMindmap(document)
  const seedState = Y.encodeStateAsUpdate(seed.doc)
  const target = new YjsMindmapSync(1, createMindmap(document), 4)
  Y.applyUpdate(target.doc, seedState, 'remote')
  const remote = new Y.Doc()
  Y.applyUpdate(remote, seedState)
  const remoteChildData = remote.getMap('nodes').get('child').get('data')
  remoteChildData.set('text', '临时编辑')
  remoteChildData.set('text', '子节点')
  const reconnectState = target._encodeUpdate(Y.encodeStateAsUpdate(remote))
  target.serverCapabilities = new Set(['yjs-lineage-v1'])
  target.wsClient.send = () => true

  target._handleSyncInit(withStateDigests({
    contentRevision: 4,
    states: [reconnectState],
    stateSources: ['same-lineage-reconnect'],
  }))

  let nextUpdate = null
  const captureUpdate = update => { nextUpdate = update }
  remote.on('update', captureUpdate)
  remoteChildData.set('text', '重连后的编辑')
  remote.off('update', captureUpdate)
  target._handleUpdate({
    type: 'update',
    update: target._encodeUpdate(nextUpdate),
    contentRevision: 4,
    lineageId: remote.getMap('meta').get('lineageId'),
  })

  assert.equal(
    target.yNodes.get('child').get('data').get('text'),
    '重连后的编辑',
  )
  seed.destroy()
  target.destroy({ flushCheckpoint: false })
  remote.destroy()
})

test('无缓存房间只有获得种子租约后才初始化 Yjs 文档', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 4)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.wsClient.connect = () => {}
  sync.start()
  sync._beginSyncHandshake()
  sync._handleSeedPending({ contentRevision: 4 })

  assert.equal(sync.hasData(), false)
  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sync.hasData(), true)
  assert.equal(sent.some(message => message.type === 'update'), true)
  sync.destroy()
})

test('首次权威种子发送失败时保持同步中并在再次授权后补发', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 4)
  const sent = []
  let transportAvailable = false
  sync.wsClient.send = message => {
    sent.push(message)
    return transportAvailable
  }
  sync.wsClient.connect = () => {}
  sync.start()
  sync._beginSyncHandshake()

  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sync.hasData(), true)
  assert.equal(sync.hasReceivedServerState(), false)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'syncing')
  assert.match(sync.syncError.value, /重试初始化/)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)

  transportAvailable = true
  sync._handleSeedGranted({ contentRevision: 4 })

  const seeds = sent.filter(message => message.seedState === true)
  assert.equal(seeds.length, 2)
  assert.equal(sync.hasReceivedServerState(), true)
  assert.equal(sync.isSynced.value, true)
  assert.equal(sync.connectionState.value, 'connected')
  sync.destroy({ flushCheckpoint: false })
})

test('新一轮握手不会复用上次连接的状态来源 CAS 清理声明', () => {
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 4)
  sync._pendingCheckpointReplacesSources = ['old-source']
  sync._pendingCheckpointInvalidSources = ['old-invalid-source']
  sync._pendingCheckpointSourceDigests = {
    'old-source': 'a'.repeat(64),
    'old-invalid-source': 'b'.repeat(64),
  }

  sync._beginSyncHandshake()

  assert.deepEqual(sync._pendingCheckpointReplacesSources, [])
  assert.deepEqual(sync._pendingCheckpointInvalidSources, [])
  assert.deepEqual(sync._pendingCheckpointSourceDigests, {})
  sync.destroy({ flushCheckpoint: false })
})

test('本地批次待确认时 seed_granted 保持等待且不伪装成已同步', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 4)
  sync.initFromMindmap(document)
  sync.markLocalMutation('pending-http-save')
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._beginSyncHandshake()

  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sent.some(message => message.type === 'update'), false)
  assert.equal(sync.hasReceivedServerState(), false)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'syncing')
  assert.match(sync.syncError.value, /等待本地修改确认/)
  sync.destroy({ flushCheckpoint: false })
})

test('握手队列批次封存并清空当前 mutationId 后不能被误播种', () => {
  const document = createDocument()
  let currentMutationId = 'queued-http-save'
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap, 4, {
    getClientMutationId: () => currentMutationId,
    getClientMutationBaseRevision: () => 4,
  })
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  sync._beginSyncHandshake()

  const changedRoot = structuredClone(document.root)
  changedRoot.data.text = '握手期间修改'
  mindMap.updateData(changedRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.data,
    data: changedRoot,
  }], currentMutationId)
  sync.markLocalMutation(currentMutationId, 4)

  assert.equal(sync.sealLocalMutation(currentMutationId), 0)
  assert.equal(sync.getLocalMutationDeliveryMode(currentMutationId), 'reload')
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)

  // 模拟 Edit 在 HTTP 请求发出后清空当前批次 ID；待确认状态仍由 Yjs 持有。
  currentMutationId = null
  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sent.some(message => message.type === 'update'), false)
  assert.equal(sent.some(message => message.seedState === true), false)
  assert.equal(sync.hasData(), false)
  assert.equal(sync.hasReceivedServerState(), false)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'syncing')
  assert.match(sync.syncError.value, /等待本地修改确认/)
  assert.equal(sync._pendingPreSyncChanges.length, 1)
  sync.destroy({ flushCheckpoint: false })
})

test('持久化状态重放封存队列触发 stale 后握手不能反向标记已连接', () => {
  const document = createDocument()
  const persisted = new YjsMindmapSync(1, createMindmap(document), 4)
  persisted.initFromMindmap(document)
  const mindMap = createMindmap(document)
  const staleEvents = []
  const sync = new YjsMindmapSync(1, mindMap, 4, {
    onStaleState: data => staleEvents.push(data),
  })
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  sync._beginSyncHandshake()

  const changedChild = structuredClone(document.root.children[0])
  changedChild.data.text = '已经进入 HTTP 请求的修改'
  const changedRoot = structuredClone(document.root)
  changedRoot.children[0] = changedChild
  mindMap.updateData(changedRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0].data,
    data: changedChild,
  }], 'sealed-before-sync-init')
  sync.markLocalMutation('sealed-before-sync-init', 4)
  assert.equal(sync.sealLocalMutation('sealed-before-sync-init'), 0)

  sync._handleSyncInit(withStateDigests({
    contentRevision: 4,
    states: [sync._encodeUpdate(Y.encodeStateAsUpdate(persisted.doc))],
    stateSources: ['persisted-source'],
  }))

  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'sealed_or_invalid_local_mutation')
  assert.equal(sync._authoritativeRevisionPending, 4)
  assert.equal(sync.hasReceivedServerState(), false)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'stale')
  assert.match(sync.syncError.value, /封存后的迟到修改/)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)
  persisted.destroy({ flushCheckpoint: false })
  sync.destroy({ flushCheckpoint: false })
})

test('HTTP 详情落后于握手 revision 时不会把旧画布播种为新云端基线', () => {
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 4, {
    onStaleState: data => staleEvents.push(data),
  })
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSeedPending({ contentRevision: 5 })
  sync._handleSeedGranted({ contentRevision: 5 })

  assert.equal(sync.contentRevision, 4)
  assert.equal(sync.hasData(), false)
  assert.equal(sync._authoritativeRevisionPending, 5)
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'handshake_revision_advanced')
  assert.equal(sent.some(message => message.type === 'update'), false)
  sync.destroy({ flushCheckpoint: false })
})

test('携带更新 revision 的完整握手状态也必须回源验证而不能替换旧 HTTP 快照', () => {
  const latestDocument = createDocument()
  latestDocument.root.children[0].data.text = 'revision 5 的云端节点'
  const source = new YjsMindmapSync(1, createMindmap(latestDocument), 5)
  source.initFromMindmap(latestDocument)
  const staleEvents = []
  const target = new YjsMindmapSync(1, createMindmap(createDocument()), 4, {
    onStaleState: data => staleEvents.push(data),
  })

  target._handleSyncInit({
    contentRevision: 5,
    states: [target._encodeUpdate(Y.encodeStateAsUpdate(source.doc))],
    stateSources: ['revision-5-writer'],
  })

  assert.equal(target.contentRevision, 4)
  assert.equal(target.hasData(), false)
  assert.equal(target._authoritativeRevisionPending, 5)
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'handshake_revision_advanced')
  target.destroy({ flushCheckpoint: false })
  source.destroy({ flushCheckpoint: false })
})

test('非空旧 Yjs 文档重连收到更高 revision 完整状态时必须回源重建', () => {
  const staleDocument = createDocument()
  staleDocument.root.children.push({
    data: { uid: 'deleted-before-reset', text: '重置前已删除节点' },
    children: [],
  })
  const target = new YjsMindmapSync(1, createMindmap(staleDocument), 4)
  target.initFromMindmap(staleDocument)

  const latestDocument = createDocument()
  latestDocument.root.children[0].data.text = 'revision 5 的权威内容'
  const source = new YjsMindmapSync(1, createMindmap(latestDocument), 5)
  source.initFromMindmap(latestDocument)
  const staleEvents = []
  target.options.onStaleState = data => staleEvents.push(data)

  target._handleSyncInit({
    contentRevision: 5,
    states: [target._encodeUpdate(Y.encodeStateAsUpdate(source.doc))],
    stateSources: ['revision-5-after-reset'],
  })

  assert.equal(target.contentRevision, 4)
  assert.equal(target.yNodes.has('deleted-before-reset'), true)
  assert.equal(target._authoritativeRevisionPending, 5)
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'handshake_revision_advanced')
  target.destroy({ flushCheckpoint: false })
  source.destroy({ flushCheckpoint: false })
})

test('更新 revision 只有损坏或残缺握手状态时必须回源而不能本地补树', () => {
  const staleEvents = []
  const target = new YjsMindmapSync(1, createMindmap(createDocument()), 4, {
    onStaleState: data => staleEvents.push(data),
  })

  target._handleSyncInit({
    contentRevision: 5,
    states: ['not-valid-base64!'],
    stateSources: ['broken-revision-5'],
  })

  assert.equal(target.contentRevision, 4)
  assert.equal(target.hasData(), false)
  assert.equal(target._authoritativeRevisionPending, 5)
  assert.equal(staleEvents[0].reason, 'handshake_revision_advanced')
  target.destroy({ flushCheckpoint: false })
})

test('握手完成前的新增操作不会创建残缺 Yjs 树并会进入完整权威种子', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap, 4, {
    getClientMutationId: () => 'mutation-before-seed',
  })
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  sync._beginSyncHandshake()

  const addedNode = { data: { uid: 'early-child', text: '握手期间新增' }, children: [] }
  const changedRoot = structuredClone(document.root)
  changedRoot.children.push(addedNode)
  mindMap.updateData(changedRoot)
  sync.onDataChangeDetail([{
    action: 'create',
    data: addedNode,
  }, {
    action: 'update',
    oldData: document.root,
    data: changedRoot,
  }], 'mutation-before-seed')

  assert.equal(sync.hasData(), false)
  assert.equal(sent.some(message => message.type === 'update'), false)

  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sync.yNodes.size, 3)
  assert.equal(sync.yNodes.has('root'), true)
  assert.equal(sync.yNodes.has('child'), true)
  assert.equal(sync.yNodes.has('early-child'), true)
  const seedMessage = sent.find(message => message.type === 'update')
  assert.equal(seedMessage.clientMutationId, 'mutation-before-seed')
  assert.equal(seedMessage.seedState, undefined)
  sync.destroy({ flushCheckpoint: false })
})

test('握手前多条队列以同一旧画布基线重放跨节点变化', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap, 4)

  const textChangedRoot = structuredClone(document.root)
  textChangedRoot.data.text = '握手前普通更新'
  mindMap.updateData(textChangedRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: textChangedRoot,
  }], 'mutation-before-sync')

  const relationChangedRoot = structuredClone(textChangedRoot)
  relationChangedRoot.data.associativeLineTargets = ['child']
  relationChangedRoot.data.associativeLineText = { child: '握手前关系' }
  mindMap.updateData(relationChangedRoot)
  sync.onDataChangeDetail([{
    action: 'update',
    oldData: textChangedRoot,
    data: relationChangedRoot,
  }], 'mutation-before-sync')

  const seed = new YjsMindmapSync(1, createMindmap(document), 4)
  seed.initFromMindmap(document)
  Y.applyUpdate(sync.doc, Y.encodeStateAsUpdate(seed.doc), 'remote')
  sync._flushPendingPreSyncChanges()

  assert.equal(sync.yNodes.get('root').get('data').get('text'), '握手前普通更新')
  assert.equal(sync.yRelations.get('assoc:root:child').text, '握手前关系')
  seed.destroy({ flushCheckpoint: false })
  sync.destroy({ flushCheckpoint: false })
})

test('纯云端种子带权威标记且不会让第二个写入者首轮保存误判 stale', () => {
  const document = createDocument()
  const seed = new YjsMindmapSync(1, createMindmap(document), 4)
  const seedMessages = []
  seed.wsClient.connect = () => {}
  seed.wsClient.send = message => {
    seedMessages.push(message)
    return true
  }
  seed.start()
  seed._beginSyncHandshake()
  seed._handleSeedGranted({ contentRevision: 4 })
  const seedMessage = seedMessages.find(message => message.type === 'update')

  assert.equal(seedMessage.seedState, true)

  const follower = new YjsMindmapSync(1, createMindmap(document), 4)
  follower._handleUpdate(seedMessage)
  follower.markLocalMutation('first-real-edit')
  follower._handleContentRevisionChanged({
    contentRevision: 5,
    clientMutationId: 'first-real-edit',
    concurrentMerge: false,
  })

  assert.equal(follower.connectionState.value, 'connected')
  assert.equal(follower.contentRevision, 5)
  assert.equal(follower.requiresAuthoritativeReconciliation(), false)
  seed.destroy({ flushCheckpoint: false })
  follower.destroy({ flushCheckpoint: false })
})

test('权威种子先到时迟到的 seed_pending 不会让连接状态倒退', () => {
  const document = createDocument()
  const seed = new YjsMindmapSync(1, createMindmap(document), 4)
  seed.wsClient.send = () => true
  seed._completeSyncHandshake(false)
  const seedState = seed._encodeUpdate(Y.encodeStateAsUpdate(seed.doc))

  const follower = new YjsMindmapSync(1, createMindmap(document), 4)
  follower._beginSyncHandshake()
  follower._handleUpdate({
    state: seedState,
    seedState: true,
    contentRevision: 4,
  })
  assert.equal(follower.hasReceivedServerState(), true)
  assert.equal(follower.connectionState.value, 'connected')

  follower._handleSeedPending({ contentRevision: 4 })

  assert.equal(follower.hasReceivedServerState(), true)
  assert.equal(follower.isSynced.value, true)
  assert.equal(follower.connectionState.value, 'connected')
  seed.destroy({ flushCheckpoint: false })
  follower.destroy({ flushCheckpoint: false })
})

test('已有本地 Yjs 状态的客户端重连空缓存房间时仍会竞争租约并补发状态', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 4)
  sync.initFromMindmap(document)
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  sync._beginSyncHandshake()
  sync._requestSeedLease()

  assert.equal(sent.some(message => message.type === 'request_seed'), true)

  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sync.connectionState.value, 'connected')
  assert.equal(sync.isSynced.value, true)
  assert.equal(
    sent.some(message => message.type === 'update' && typeof message.state === 'string'),
    true,
  )
  sync.destroy({ flushCheckpoint: false })
})

test('断线未提交修改与服务器缓存合并后禁止补发无关联完整状态', () => {
  const document = createDocument()
  const seed = new YjsMindmapSync(1, createMindmap(document), 4)
  seed.initFromMindmap(document)
  const seedState = Y.encodeStateAsUpdate(seed.doc)

  const local = new YjsMindmapSync(1, createMindmap(document), 4)
  const remote = new YjsMindmapSync(1, createMindmap(document), 4)
  Y.applyUpdate(local.doc, seedState, 'remote')
  Y.applyUpdate(remote.doc, seedState, 'remote')

  const sent = []
  local.wsClient.connect = () => {}
  local.wsClient.send = message => {
    sent.push(message)
    return true
  }
  local.start()

  const changedChild = structuredClone(document.root.children[0])
  changedChild.data.text = '断线期间的本地修改'
  local.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changedChild,
  }], 'offline-local-edit')

  const changedRoot = structuredClone(document.root)
  changedRoot.data.text = '服务器期间的远端修改'
  remote.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: changedRoot,
  }], 'remote-edit')

  sent.length = 0
  local._beginSyncHandshake()
  local._handleSyncInit({
    states: [local._encodeUpdate(Y.encodeStateAsUpdate(remote.doc))],
    stateSources: ['remote-cache'],
  })

  const fullStateMessage = sent.find(message => (
    message.type === 'update' && typeof message.state === 'string'
  ))
  assert.equal(fullStateMessage, undefined)
  assert.equal(local.requiresAuthoritativeReconciliation(), true)
  const retainedLocalTree = local._rebuildTreeFromYjs()
  assert.equal(retainedLocalTree.data.text, '根节点')
  assert.equal(retainedLocalTree.children[0].data.text, '断线期间的本地修改')
  assert.deepEqual(local._pendingCheckpointInvalidSources, [])
  assert.equal(local.connectionState.value, 'stale')

  seed.destroy({ flushCheckpoint: false })
  local.destroy({ flushCheckpoint: false })
  remote.destroy({ flushCheckpoint: false })
})

test('缺少 mutationId 的本地正文事务立即回源且不发送未关联状态', () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 4, {
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()
  sent.length = 0

  sync.doc.transact(() => {
    sync.yMeta.set('layout', 'mindMap')
  }, 'local-meta')

  assert.equal(sent.length, 0)
  assert.equal(sync.requiresAuthoritativeReconciliation(), true)
  assert.equal(sync.connectionState.value, 'stale')
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'uncorrelated_local_yjs_update')
  sync.destroy({ flushCheckpoint: false })
})

test('同 revision 的持久化删除即使有节点账本也不能覆盖 HTTP 权威树', () => {
  const document = createDocument()
  const dirtySource = new YjsMindmapSync(1, createMindmap(document), 5)
  dirtySource.initFromMindmap(document)
  dirtySource.onDataChangeDetail([{
    action: 'delete',
    oldData: { uid: 'child' },
  }], 'uncommitted-persisted-delete')
  assert.equal(dirtySource.yNodeLedger.get('child'), true)

  const sync = new YjsMindmapSync(1, createMindmap(document), 5)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit(withStateDigests({
    contentRevision: 5,
    states: [sync._encodeUpdate(Y.encodeStateAsUpdate(dirtySource.doc))],
    stateSources: ['dirty-delete-source'],
  }))

  assert.equal(sync.hasData(), false)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)
  sync._handleSeedGranted({ contentRevision: 5 })

  assert.equal(sync.yNodes.size, 2)
  assert.equal(sync.yNodes.has('child'), true)
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.deepEqual(checkpoint.invalidSources, ['dirty-delete-source'])
  assert.equal(Object.hasOwn(checkpoint, 'replacesSources'), false)

  sync.destroy({ flushCheckpoint: false })
  dirtySource.destroy({ flushCheckpoint: false })
})

test('同 revision 的持久化文档元数据必须与 HTTP 权威基线一致', () => {
  const document = createDocument()
  const dirtyDocument = structuredClone(document)
  dirtyDocument.layout = 'mindMap'
  dirtyDocument.documentData.simpleMindMap.config.imgTextMargin = 99
  const dirtySource = new YjsMindmapSync(1, createMindmap(dirtyDocument), 5)
  dirtySource.initFromMindmap(dirtyDocument)
  const sync = new YjsMindmapSync(1, createMindmap(document), 5)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit(withStateDigests({
    contentRevision: 5,
    states: [sync._encodeUpdate(Y.encodeStateAsUpdate(dirtySource.doc))],
    stateSources: ['dirty-meta-source'],
  }))

  assert.equal(sync.hasData(), false)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)
  assert.deepEqual(sync._pendingCheckpointInvalidSources, ['dirty-meta-source'])

  sync.destroy({ flushCheckpoint: false })
  dirtySource.destroy({ flushCheckpoint: false })
})

test('待确认 mutation 期间不压缩持久化来源并在 HTTP 确认后自动补发', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 5)
  sync.initFromMindmap(document)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync._rememberPendingCheckpointConsolidation(
    ['accepted-source'],
    ['invalid-source'],
    {
      'accepted-source': 'a'.repeat(64),
      'invalid-source': 'b'.repeat(64),
    },
  )
  sync.markLocalMutation('pending-http-save', 5)

  assert.equal(sync._flushPendingCheckpointConsolidation(), false)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)

  sync.setContentRevision(6, 'pending-http-save')

  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.equal(checkpoint.contentRevision, 6)
  assert.deepEqual(checkpoint.replacesSources, ['accepted-source'])
  assert.deepEqual(checkpoint.invalidSources, ['invalid-source'])
  assert.deepEqual(sync._pendingCheckpointReplacesSources, [])
  assert.deepEqual(sync._pendingCheckpointInvalidSources, [])

  sync.destroy({ flushCheckpoint: false })
})

test('节点账本允许自动保存前的合法实时删除通过初始完整性校验', () => {
  const document = createDocument()
  const source = new YjsMindmapSync(1, createMindmap(document), 4)
  source.initFromMindmap(document)
  source.onDataChangeDetail([{
    action: 'delete',
    oldData: { uid: 'child' },
  }], 'delete-before-http-save')

  assert.equal(source.yNodes.has('child'), false)
  assert.equal(source.yNodeLedger.get('child'), true)

  const target = new YjsMindmapSync(1, createMindmap(document), 4)
  target._handleUpdate({
    state: target._encodeUpdate(Y.encodeStateAsUpdate(source.doc)),
    contentRevision: 4,
  })

  assert.equal(target.connectionState.value, 'connected')
  assert.equal(target.hasReceivedServerState(), true)
  assert.equal(target.yNodes.has('child'), false)
  assert.equal(target.yNodeLedger.get('child'), true)
  source.destroy({ flushCheckpoint: false })
  target.destroy({ flushCheckpoint: false })
})

test('旧客户端没有节点账本时以 Yjs 删除墓碑证明合法实时删除', () => {
  const document = createDocument()
  const source = new YjsMindmapSync(1, createMindmap(document), 4)
  source.initFromMindmap(document)
  // 模拟滚动升级前创建的 Y.Doc：它没有只增不减的 nodeLedger，但完整
  // 状态仍保留 nodes 顶层键的 Yjs 删除墓碑。
  source.yNodeLedger.clear()
  source.onDataChangeDetail([{
    action: 'delete',
    data: document.root.children[0],
  }], 'legacy-delete-before-http-save')

  assert.equal(source.yNodes.has('child'), false)
  assert.notEqual(source.yNodeLedger.get('child'), true)

  const target = new YjsMindmapSync(1, createMindmap(document), 4)
  target._handleUpdate({
    state: target._encodeUpdate(Y.encodeStateAsUpdate(source.doc)),
    contentRevision: 4,
  })

  assert.equal(target.connectionState.value, 'connected')
  assert.equal(target.hasReceivedServerState(), true)
  assert.equal(target.yNodes.has('child'), false)
  source.destroy({ flushCheckpoint: false })
  target.destroy({ flushCheckpoint: false })
})

test('只读观察者不竞争种子租约且等待可写客户端提供共享 Yjs 状态', () => {
  const document = createDocument()
  const readonlySync = new YjsMindmapSync(
    1,
    createMindmap(document),
    4,
    { readonly: true },
  )
  const sent = []
  readonlySync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  readonlySync._beginSyncHandshake()
  readonlySync._handleSeedPending({ contentRevision: 4 })
  readonlySync._requestSeedLease()

  assert.equal(readonlySync.wsClient.readonly, true)
  assert.equal(readonlySync.hasData(), false)
  assert.equal(readonlySync.isSynced.value, true)
  assert.equal(readonlySync.connectionState.value, 'connected')
  assert.equal(sent.some(message => message.type === 'request_seed'), false)

  // 即便旧服务端错误授予租约，只读端也不能独立初始化 Yjs 嵌套类型。
  readonlySync._handleSeedGranted({ contentRevision: 4 })
  assert.equal(readonlySync.hasData(), false)

  const writerSync = new YjsMindmapSync(1, createMindmap(document), 4)
  writerSync.initFromMindmap(document)
  readonlySync._handleUpdate({
    state: readonlySync._encodeUpdate(Y.encodeStateAsUpdate(writerSync.doc)),
    contentRevision: 4,
  })

  assert.equal(readonlySync.yNodes.size, 2)
  assert.equal(readonlySync.yNodes.has('child'), true)
  readonlySync.destroy()
  writerSync.destroy()
})

test('独立身份的可写用户实时更新只读观察者且观察者全程不能反向写入', async () => {
  const document = createDocument()
  const writerMindMap = createMindmap(document)
  const observerMindMap = createMindmap(document)
  const writer = new YjsMindmapSync(127, writerMindMap, 4, {
    user: { id: 1, name: '用户 A' },
  })
  const observer = new YjsMindmapSync(127, observerMindMap, 4, {
    readonly: true,
    user: { id: 2, name: '用户 B' },
  })
  const writerMessages = []
  const observerMessages = []
  writer.wsClient.connect = () => {}
  observer.wsClient.connect = () => {}
  writer.wsClient.send = message => {
    writerMessages.push(message)
    return true
  }
  observer.wsClient.send = message => {
    observerMessages.push(message)
    return true
  }
  writer.start()
  observer.start()

  observer._beginSyncHandshake()
  observer._handleSeedPending({ contentRevision: 4 })
  writer._beginSyncHandshake()
  writer._handleSeedGranted({ contentRevision: 4 })
  const seedMessage = writerMessages.find(message => (
    message.type === 'update' && typeof message.state === 'string'
  ))
  assert.ok(seedMessage)
  observer._handleUpdate(seedMessage)
  observerMindMap.emit('node_tree_render_end')
  await new Promise(resolve => setTimeout(resolve, 0))

  assert.equal(writer.currentUser.id, 1)
  assert.equal(observer.currentUser.id, 2)
  assert.equal(observer.yNodes.size, 2)
  assert.equal(observer._rebuildTreeFromYjs().children[0].data.text, '子节点')

  writerMessages.length = 0
  const updatedChild = structuredClone(document.root.children[0])
  updatedChild.data.text = '用户 A 的实时修改'
  writer.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: updatedChild,
  }], 'mutation-user-a')
  const incrementalMessage = writerMessages.find(message => message.type === 'update')
  assert.ok(incrementalMessage)
  assert.equal(incrementalMessage.clientMutationId, 'mutation-user-a')
  observer._handleUpdate(incrementalMessage)
  observerMindMap.emit('node_tree_render_end')
  await new Promise(resolve => setTimeout(resolve, 0))

  assert.equal(
    observer._rebuildTreeFromYjs().children[0].data.text,
    '用户 A 的实时修改',
  )
  assert.equal(
    observerMindMap.getData().children[0].data.text,
    '用户 A 的实时修改',
  )

  const observerStateBeforeLocalWrite = Y.encodeStateVector(observer.doc)
  observer.onDataChangeDetail([{
    action: 'update',
    oldData: updatedChild,
    data: {
      ...updatedChild,
      data: { ...updatedChild.data, text: '用户 B 不应写入' },
    },
  }], 'mutation-user-b')
  observer.syncDocumentMeta({ layout: 'mindMap' }, 'mutation-user-b-meta')
  observer.initFromMindmap({
    ...document,
    root: { ...document.root, children: [] },
  }, 'mutation-user-b-reset')

  assert.deepEqual(Y.encodeStateVector(observer.doc), observerStateBeforeLocalWrite)
  assert.equal(
    observer._rebuildTreeFromYjs().children[0].data.text,
    '用户 A 的实时修改',
  )
  assert.equal(
    observerMessages.some(message => (
      message.type === 'update'
      || message.type === 'checkpoint'
      || message.type === 'request_seed'
    )),
    false,
  )

  writer.destroy({ flushCheckpoint: false })
  observer.destroy({ flushCheckpoint: false })
})

test('同一账号的两个浏览器会话并发修改不同节点时实时状态双向收敛', async () => {
  const document = createDocument()
  const mindMapA = createMindmap(document)
  const mindMapB = createMindmap(document)
  const writerA = new YjsMindmapSync(127, mindMapA, 4, {
    user: { id: 1, name: '用户 A' },
  })
  const writerB = new YjsMindmapSync(127, mindMapB, 4, {
    user: { id: 1, name: '用户 A（浏览器 B）' },
  })
  const messagesA = []
  const messagesB = []
  writerA.wsClient.connect = () => {}
  writerB.wsClient.connect = () => {}
  writerA.serverCapabilities.add('conditional-node-patch-v1')
  writerB.serverCapabilities.add('conditional-node-patch-v1')
  writerA.wsClient.send = message => {
    messagesA.push(message)
    return true
  }
  writerB.wsClient.send = message => {
    messagesB.push(message)
    return true
  }
  writerA.start()
  writerB.start()
  writerA._beginSyncHandshake()
  writerA._handleSeedGranted({ contentRevision: 4 })
  writerB._beginSyncHandshake()
  const seedMessage = messagesA.find(message => message.type === 'update')
  writerB._handleUpdate(seedMessage)

  messagesA.length = 0
  messagesB.length = 0
  const changedRoot = structuredClone(document.root)
  changedRoot.data.text = '用户 A 修改根节点'
  const changedChild = structuredClone(document.root.children[0])
  changedChild.data.text = '用户 B 修改子节点'
  writerA.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: changedRoot,
  }], 'mutation-user-a')
  writerB.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changedChild,
  }], 'mutation-user-b')

  const updateA = messagesA.find(message => message.type === 'update')
  const updateB = messagesB.find(message => message.type === 'update')
  assert.equal(updateA.clientMutationId, 'mutation-user-a')
  assert.equal(updateB.clientMutationId, 'mutation-user-b')

  // 刻意让消息以相反顺序到达，证明结果不依赖网络调度顺序。
  writerA._handleUpdate(updateB)
  writerB._handleUpdate(updateA)
  mindMapA.emit('node_tree_render_end')
  mindMapB.emit('node_tree_render_end')
  await new Promise(resolve => setTimeout(resolve, 0))

  const treeA = writerA._rebuildTreeFromYjs()
  const treeB = writerB._rebuildTreeFromYjs()
  assert.deepEqual(treeA, treeB)
  assert.equal(treeA.data.text, '用户 A 修改根节点')
  assert.equal(treeA.children[0].data.text, '用户 B 修改子节点')
  assert.equal(mindMapA.getData().children[0].data.text, '用户 B 修改子节点')
  assert.equal(mindMapB.getData().data.text, '用户 A 修改根节点')

  writerA.destroy({ flushCheckpoint: false })
  writerB.destroy({ flushCheckpoint: false })
})

test('两个浏览器并发修改同一关系深层样式、概要端点和分组成员时完整收敛', () => {
  const document = createDocument()
  document.root.children.push({
    data: { uid: 'child-2', text: '子节点 2' },
    children: [],
  })
  document.root.data.associativeLineTargets = ['child']
  document.root.data.associativeLineStyle = {
    child: { color: 'red', width: 1 },
  }
  document.root.data.generalization = [{
    uid: 'summary-1',
    range: [0, 0],
    text: '旧概要',
    style: { color: 'red' },
  }]
  document.root.children[0].data.outerFrame = {
    groupId: 'group-1',
    lineColor: 'red',
  }
  const mindMapA = createMindmap(document)
  const mindMapB = createMindmap(document)
  const writerA = new YjsMindmapSync(127, mindMapA, 4)
  const writerB = new YjsMindmapSync(127, mindMapB, 4)
  const messagesA = []
  const messagesB = []
  writerA.wsClient.connect = () => {}
  writerB.wsClient.connect = () => {}
  writerA.serverCapabilities.add('conditional-node-patch-v1')
  writerB.serverCapabilities.add('conditional-node-patch-v1')
  writerA.wsClient.send = message => {
    messagesA.push(message)
    return true
  }
  writerB.wsClient.send = message => {
    messagesB.push(message)
    return true
  }
  writerA.start()
  writerB.start()
  writerA.initFromMindmap(document)
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))
  messagesA.length = 0
  messagesB.length = 0

  const rootA = structuredClone(document.root)
  rootA.data.associativeLineStyle.child.color = 'blue'
  rootA.children.reverse()
  delete rootA.children[1].data.outerFrame
  mindMapA.updateData(rootA)
  writerA.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: rootA,
  }], 'cross-record-a')

  const rootB = structuredClone(document.root)
  rootB.data.associativeLineStyle.child.width = 5
  rootB.data.generalization[0].text = '协作者概要'
  rootB.children[1].data.outerFrame = {
    groupId: 'group-1',
    lineColor: 'red',
  }
  mindMapB.updateData(rootB)
  writerB.onDataChangeDetail([{
    action: 'update',
    oldData: document.root,
    data: rootB,
  }], 'cross-record-b')

  writerA._handleUpdate(messagesB.find(message => message.type === 'update'))
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))

  const treeA = writerA._rebuildTreeFromYjs()
  const treeB = writerB._rebuildTreeFromYjs()
  assert.deepEqual(treeA, treeB)
  assert.deepEqual(treeA.data.associativeLineStyle.child, {
    color: 'blue',
    width: 5,
  })
  assert.equal(treeA.children[0].data.uid, 'child-2')
  assert.equal(treeA.data.generalization[0].text, '协作者概要')
  assert.deepEqual(treeA.data.generalization[0].range, [0, 0])
  assert.equal(treeA.children[0].data.outerFrame.groupId, 'group-1')
  assert.equal(treeA.children[1].data.outerFrame, undefined)

  writerA.destroy({ flushCheckpoint: false })
  writerB.destroy({ flushCheckpoint: false })
})

test('两个客户端并发修改同一节点的不同字段时修复补丁不会覆盖 CRDT 合并结果', () => {
  const document = createDocument()
  document.root.children[0].data.fillColor = '#ffffff'
  const writerA = new YjsMindmapSync(127, createMindmap(document), 4)
  const writerB = new YjsMindmapSync(127, createMindmap(document), 4)
  const messagesA = []
  const messagesB = []
  writerA.wsClient.connect = () => {}
  writerB.wsClient.connect = () => {}
  writerA.serverCapabilities.add('conditional-node-patch-v1')
  writerB.serverCapabilities.add('conditional-node-patch-v1')
  writerA.wsClient.send = message => {
    messagesA.push(message)
    return true
  }
  writerB.wsClient.send = message => {
    messagesB.push(message)
    return true
  }
  writerA.start()
  writerB.start()
  writerA.initFromMindmap(document)
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))
  messagesA.length = 0
  messagesB.length = 0

  const changedByA = structuredClone(document.root.children[0])
  changedByA.data.text = '用户 A 修改文字'
  const changedByB = structuredClone(document.root.children[0])
  changedByB.data.fillColor = '#ff0000'
  writerA.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changedByA,
  }], 'same-node-field-a')
  writerB.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changedByB,
  }], 'same-node-field-b')

  const updateA = messagesA.find(message => message.type === 'update')
  const updateB = messagesB.find(message => message.type === 'update')
  assert.deepEqual(updateA.patch.nodes[0].previousData, document.root.children[0].data)
  assert.deepEqual(updateB.patch.nodes[0].previousData, document.root.children[0].data)
  writerA._handleUpdate(updateB)
  writerB._handleUpdate(updateA)

  const treeA = writerA._rebuildTreeFromYjs()
  const treeB = writerB._rebuildTreeFromYjs()
  assert.deepEqual(treeA, treeB)
  assert.equal(treeA.children[0].data.text, '用户 A 修改文字')
  assert.equal(treeA.children[0].data.fillColor, '#ff0000')
  writerA.destroy({ flushCheckpoint: false })
  writerB.destroy({ flushCheckpoint: false })
})

test('两个客户端并发修改同一节点同一字段时仍采用 Yjs 的确定性胜者', () => {
  const document = createDocument()
  const writerA = new YjsMindmapSync(127, createMindmap(document), 4)
  const writerB = new YjsMindmapSync(127, createMindmap(document), 4)
  const messagesA = []
  const messagesB = []
  writerA.wsClient.connect = () => {}
  writerB.wsClient.connect = () => {}
  writerA.serverCapabilities.add('conditional-node-patch-v1')
  writerB.serverCapabilities.add('conditional-node-patch-v1')
  writerA.wsClient.send = message => {
    messagesA.push(message)
    return true
  }
  writerB.wsClient.send = message => {
    messagesB.push(message)
    return true
  }
  writerA.start()
  writerB.start()
  writerA.initFromMindmap(document)
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))
  messagesA.length = 0
  messagesB.length = 0

  const changedByA = structuredClone(document.root.children[0])
  changedByA.data.text = '用户 A 的竞争值'
  const changedByB = structuredClone(document.root.children[0])
  changedByB.data.text = '用户 B 的竞争值'
  writerA.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changedByA,
  }], 'same-field-a')
  writerB.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changedByB,
  }], 'same-field-b')

  writerA._handleUpdate(messagesB.find(message => message.type === 'update'))
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))

  const treeA = writerA._rebuildTreeFromYjs()
  const treeB = writerB._rebuildTreeFromYjs()
  assert.deepEqual(treeA, treeB)
  assert.ok([
    '用户 A 的竞争值',
    '用户 B 的竞争值',
  ].includes(treeA.children[0].data.text))
  writerA.destroy({ flushCheckpoint: false })
  writerB.destroy({ flushCheckpoint: false })
})

test('节点更新与删除并发时修复补丁不会复活已由 CRDT 删除的节点', () => {
  const document = createDocument()
  const writerA = new YjsMindmapSync(127, createMindmap(document), 4)
  const writerB = new YjsMindmapSync(127, createMindmap(document), 4)
  const messagesA = []
  const messagesB = []
  writerA.wsClient.connect = () => {}
  writerB.wsClient.connect = () => {}
  writerA.serverCapabilities.add('conditional-node-patch-v1')
  writerB.serverCapabilities.add('conditional-node-patch-v1')
  writerA.wsClient.send = message => {
    messagesA.push(message)
    return true
  }
  writerB.wsClient.send = message => {
    messagesB.push(message)
    return true
  }
  writerA.start()
  writerB.start()
  writerA.initFromMindmap(document)
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))
  messagesA.length = 0
  messagesB.length = 0

  const changedByA = structuredClone(document.root.children[0])
  changedByA.data.text = '删除并发期间的修改'
  writerA.onDataChangeDetail([{
    action: 'update',
    oldData: document.root.children[0],
    data: changedByA,
  }], 'update-against-delete')
  writerB.onDataChangeDetail([{
    action: 'delete',
    oldData: { uid: 'child' },
  }], 'delete-against-update')

  writerA._handleUpdate(messagesB.find(message => message.type === 'update'))
  writerB._handleUpdate(messagesA.find(message => message.type === 'update'))

  assert.equal(writerA.yNodes.has('child'), false)
  assert.equal(writerB.yNodes.has('child'), false)
  assert.deepEqual(writerA._rebuildTreeFromYjs(), writerB._rebuildTreeFromYjs())
  writerA.destroy({ flushCheckpoint: false })
  writerB.destroy({ flushCheckpoint: false })
})

test('只读观察者隔离残缺持久化树后仍能采用可写客户端的完整种子', () => {
  const document = createDocument()
  const staleDocument = structuredClone(document)
  staleDocument.root.children = []
  const staleSync = new YjsMindmapSync(1, createMindmap(staleDocument), 4)
  staleSync.initFromMindmap(staleDocument)
  const readonlySync = new YjsMindmapSync(
    1,
    createMindmap(document),
    4,
    { readonly: true },
  )

  readonlySync._handleSyncInit({
    states: [readonlySync._encodeUpdate(Y.encodeStateAsUpdate(staleSync.doc))],
    stateSources: ['stale-readonly-source'],
  })

  assert.equal(readonlySync.hasData(), false)
  assert.equal(readonlySync.hasReceivedServerState(), false)
  assert.equal(readonlySync.connectionState.value, 'degraded')

  const writerSync = new YjsMindmapSync(1, createMindmap(document), 4)
  writerSync.initFromMindmap(document)
  readonlySync._handleUpdate({
    state: readonlySync._encodeUpdate(Y.encodeStateAsUpdate(writerSync.doc)),
    contentRevision: 4,
  })

  assert.equal(readonlySync.yNodes.size, 2)
  assert.equal(readonlySync.yNodes.has('child'), true)
  readonlySync.destroy()
  writerSync.destroy()
  staleSync.destroy()
})

test('首次握手拒绝旧标签页提供的残缺节点树并改用 HTTP 权威种子', () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const staleDocument = structuredClone(document)
  staleDocument.root.children = []
  const staleSource = new YjsMindmapSync(1, createMindmap(staleDocument), 4)
  staleSource.initFromMindmap(staleDocument)
  const sync = new YjsMindmapSync(1, mindMap, 4)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.wsClient.connect = () => {}
  sync.start()
  sync._beginSyncHandshake()

  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(staleSource.doc)),
    contentRevision: 4,
  })

  assert.equal(sync.hasData(), false)
  assert.equal(sync.connectionState.value, 'degraded')
  assert.match(sync.syncError.value, /不完整协作状态/)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)

  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sync.yNodes.size, 2)
  assert.equal(sync.yNodes.has('child'), true)
  assert.equal(sent.some(message => message.type === 'update'), true)
  sync.destroy()
  staleSource.destroy()
})

test('已有完整状态的客户端重连时拒绝残缺同版本种子并回传正确状态', () => {
  const document = createDocument()
  const staleDocument = structuredClone(document)
  staleDocument.root.children = []
  const staleSource = new YjsMindmapSync(1, createMindmap(staleDocument), 4)
  staleSource.initFromMindmap(staleDocument)
  const sync = new YjsMindmapSync(1, createMindmap(document), 4)
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.initFromMindmap(document)
  sent.length = 0
  sync._beginSyncHandshake()

  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(staleSource.doc)),
    contentRevision: 4,
  })

  assert.equal(sync.yNodes.size, 2)
  assert.equal(sync.yNodes.has('child'), true)
  assert.equal(sync.connectionState.value, 'degraded')
  assert.equal(sent.some(message => message.type === 'request_seed'), true)

  sync._handleSeedGranted({ contentRevision: 4 })

  assert.equal(sync.connectionState.value, 'connected')
  assert.equal(sent.some(message => (
    message.type === 'update'
    && message.state
    && message.seedState === true
  )), true)
  sync.destroy()
  staleSource.destroy()
})

test('持久化根节点残缺缓存会被隔离并由 HTTP 权威文档替换', () => {
  const document = createDocument()
  const staleDocument = structuredClone(document)
  staleDocument.root.children = []
  const staleSource = new YjsMindmapSync(1, createMindmap(staleDocument), 5)
  staleSource.initFromMindmap(staleDocument)
  const sync = new YjsMindmapSync(1, createMindmap(document), 5)
  sync.serverCapabilities = new Set([
    'yjs-checkpoint-v1',
    'yjs-source-cas-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit(withStateDigests({
    states: [sync._encodeUpdate(Y.encodeStateAsUpdate(staleSource.doc))],
    stateSources: ['root-only-source'],
  }))

  assert.equal(sync.yNodes.size, 0)
  assert.equal(sent.some(message => message.type === 'request_seed'), true)
  sync._handleSeedGranted({ contentRevision: 5 })
  assert.equal(sync.yNodes.size, 2)
  assert.equal(sync.yNodes.has('child'), true)
  assert.equal(sync.connectionState.value, 'connected')
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.deepEqual(checkpoint.invalidSources, ['root-only-source'])
  assert.equal(Object.hasOwn(checkpoint, 'replacesSources'), false)
  sync.destroy()
  staleSource.destroy()
})

test('已有 Yjs 状态的客户端会响应房间种子请求', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 5)
  sync.initFromMindmap(createDocument())
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSeedRequest({ contentRevision: 5 })
  sync._handleSeedRequest({ contentRevision: 4 })

  assert.equal(sent.length, 1)
  assert.equal(sent[0].type, 'update')
  assert.equal(sent[0].contentRevision, 5)
  sync.destroy()
})

test('乱序到达的旧标签定义事件不会覆盖新版本', () => {
  const document = createDocument()
  document.root.data.tag[0].definitionRevision = 5
  const mindMap = createMindmap(document)
  const acceptedEvents = []
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    onTagDefinitionChanged: data => acceptedEvents.push(data),
  })

  sync._handleTagDefinitionChanged({
    tagId: 8,
    definitionRevision: 7,
    definition: { tagId: 8, text: '最新名称', style: { fill: '#0f0' } },
  })
  sync._handleTagDefinitionChanged({
    tagId: 8,
    definitionRevision: 6,
    definition: { tagId: 8, text: '过期名称', style: { fill: '#00f' } },
  })

  assert.equal(sync.tagDefinitions.get('8').definitionRevision, 7)
  assert.equal(sync.tagDefinitions.get('8').text, '最新名称')
  assert.equal(acceptedEvents.length, 1)
  assert.equal(acceptedEvents[0].definition.text, '最新名称')
  sync.destroy()
})

test('标签替换会在同一事务中删除旧定义并写入新定义', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(createDocument())
  const definitionChanges = []
  sync.yTagDefinitions.observe(event => {
    definitionChanges.push([...event.changes.keys.keys()])
  })

  sync._handleTagReplaced({
    sourceTagId: 8,
    targetTagId: 9,
    contentRevision: 2,
    definitionRevision: 3,
    definition: { tagId: 9, categoryId: 4, text: '替换标签', style: { fill: '#0f0' } },
  })

  assert.equal(definitionChanges.length, 1)
  assert.deepEqual(new Set(definitionChanges[0]), new Set(['8', '9']))
  assert.equal(sync.yTagDefinitions.has('8'), false)
  assert.equal(sync.yTagDefinitions.get('9').text, '替换标签')
  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{
    tagId: 9,
    categoryId: 4,
  }])
  sync.destroy()
})

test('乱序到达的旧标签替换仍更新绑定但不会覆盖目标标签的新定义', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document))
  sync.initFromMindmap(document)
  const latestDefinition = {
    tagId: 9,
    categoryId: 6,
    text: '目标标签最新名称',
    style: { fill: '#f00' },
    definitionRevision: 5,
  }
  sync.tagDefinitions.set('9', {
    ...latestDefinition,
    text: '缓存中的较旧名称',
    definitionRevision: 3,
  })
  sync.yTagDefinitions.set('9', latestDefinition)

  sync._handleTagReplaced({
    sourceTagId: 8,
    targetTagId: 9,
    contentRevision: 2,
    definitionRevision: 4,
    definition: {
      tagId: 9,
      categoryId: 4,
      text: '目标标签过期名称',
      style: { fill: '#0f0' },
    },
  })

  assert.equal(sync.tagDefinitions.has('8'), false)
  assert.equal(sync.yTagDefinitions.has('8'), false)
  assert.deepEqual(sync.tagDefinitions.get('9'), latestDefinition)
  assert.deepEqual(sync.yTagDefinitions.get('9'), latestDefinition)
  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{
    tagId: 9,
    categoryId: 6,
  }])
  sync.destroy()
})

test('服务器标签事件不会被当成本地 Yjs 修改回传且按顺序推进 revision', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 4)
  sync.initFromMindmap(document)
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()

  sync._handleTagReplaced({
    sourceTagId: 8,
    targetTagId: 9,
    contentRevision: 5,
    definitionRevision: 3,
    definition: {
      tagId: 9,
      categoryId: 4,
      text: '替换标签',
      style: { fill: '#0f0' },
    },
  })

  assert.equal(sync.contentRevision, 5)
  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{
    tagId: 9,
    categoryId: 4,
  }])
  assert.equal(sent.some(message => message.type === 'update'), false)
  sync.destroy({ flushCheckpoint: false })
})

test('标签增量跨越 revision 缺口时不掩盖缺失正文并立即回源', () => {
  const document = createDocument()
  const staleEvents = []
  const sync = new YjsMindmapSync(1, createMindmap(document), 4, {
    onStaleState: data => staleEvents.push(data),
  })
  sync.initFromMindmap(document)

  sync._handleTagUnbound({
    tagIds: [8],
    contentRevision: 6,
  })

  assert.equal(sync.contentRevision, 4)
  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{
    tagId: 8,
    categoryId: 3,
  }])
  assert.equal(staleEvents.length, 1)
  assert.equal(staleEvents[0].reason, 'document_event_revision_gap')
  assert.equal(sync.connectionState.value, 'stale')
  sync.destroy({ flushCheckpoint: false })
})

test('过期标签解绑事件不会反向修改已推进的画布', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document), 7)
  sync.initFromMindmap(document)

  sync._handleTagUnbound({
    tagIds: [8],
    contentRevision: 6,
  })

  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{
    tagId: 8,
    categoryId: 3,
  }])
  assert.equal(sync.contentRevision, 7)
  sync.destroy({ flushCheckpoint: false })
})

test('脑图删除事件会通知上层并立即销毁协作连接', () => {
  const mindMap = createMindmap(createDocument())
  const deletedEvents = []
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    onDocumentDeleted: data => deletedEvents.push(data),
  })

  sync.wsClient.handlers.document_deleted({
    type: 'document_deleted',
    mindmapId: 1,
    message: '该脑图已被所有者删除',
  })

  assert.equal(deletedEvents.length, 1)
  assert.equal(deletedEvents[0].mindmapId, 1)
  assert.equal(sync._destroyed, true)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'deleted')
})

test('权限撤销事件会定向通知上层并立即销毁协作连接', () => {
  const mindMap = createMindmap(createDocument())
  const revokedEvents = []
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    onAccessRevoked: data => revokedEvents.push(data),
  })
  sync.initFromMindmap(createDocument())
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  sync._checkpointDirty = true
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync.wsClient.handlers.access_revoked({
    type: 'access_revoked',
    mindmapId: 1,
    targetUserId: 7,
    message: '权限已撤销',
  })

  assert.equal(revokedEvents.length, 1)
  assert.equal(revokedEvents[0].targetUserId, 7)
  assert.equal(sync._destroyed, true)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'access-revoked')
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)
})

test('登录会话失效会禁止检查点回写并安全终止协作', () => {
  const mindMap = createMindmap(createDocument())
  const endedEvents = []
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    onSessionEnded: data => endedEvents.push(data),
  })
  sync.initFromMindmap(createDocument())
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  sync._checkpointDirty = true
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync.wsClient.handlers.session_ended({
    type: 'session_ended',
    mindmapId: 1,
    reason: 'session_revoked',
    message: '登录会话已失效，请重新登录',
  })

  assert.equal(endedEvents.length, 1)
  assert.equal(endedEvents[0].reason, 'session_revoked')
  assert.equal(sync._destroyed, true)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.connectionState.value, 'session-ended')
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)
})

test('长期会话的暂时认证故障保留 Yjs 文档等待自动重连', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 1)
  sync.initFromMindmap(createDocument())
  const rootCount = sync.yNodes.size

  sync.wsClient.handlers.onAuthError(
    '认证服务暂时不可用，请稍后重试',
    { code: 'auth_unavailable', retryable: true },
  )
  sync.wsClient.handlers.onClose()

  assert.equal(sync._destroyed, false)
  assert.equal(sync.yNodes.size, rootCount)
  assert.equal(sync.isSynced.value, false)
  assert.equal(sync.syncError.value, '认证服务暂时不可用，请稍后重试')

  sync.destroy({ flushCheckpoint: false })
})

test('AI 协作栅栏冻结写入并仅在强制检查点之后发送 ready ACK', async () => {
  const token = '0123456789abcdef0123456789abcdef'
  const released = []
  const resets = []
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 4, {
    onCollaborationBarrierPrepare: async () => ({
      ready: true,
      contentRevision: 4,
    }),
    onCollaborationBarrierReleased: data => released.push(data),
    onDocumentReset: data => resets.push(data),
  })
  sync.initFromMindmap(createDocument())
  sync.serverCapabilities = new Set([
    'collaboration-mutation-barrier-v1',
    'yjs-checkpoint-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  await sync._handleCollaborationBarrierPrepare({
    type: 'collaboration_barrier_prepare',
    token,
    operation: 'apply',
    contentRevision: 4,
  })

  assert.equal(sync.isStructureWriteBlocked(), true)
  assert.equal(sync.canAcquireNodeEditLease(), false)
  const protocolMessages = sent.filter(message => message.type !== 'awareness')
  assert.deepEqual(protocolMessages.map(message => message.type), [
    'checkpoint',
    'collaboration_barrier_ack',
  ])
  assert.equal(protocolMessages[0].barrierToken, token)
  assert.equal(protocolMessages[0].contentRevision, 4)
  assert.equal(protocolMessages[1].ready, true)
  assert.equal(protocolMessages[1].token, token)

  sync._handleCollaborationBarrierReleased({
    type: 'collaboration_barrier_released',
    token,
    status: 'committed',
    contentRevision: 5,
  })
  assert.equal(sync.isStructureWriteBlocked(), false)
  assert.equal(released.length, 1)
  assert.equal(resets.length, 1)
  assert.equal(sync._authoritativeRevisionPending, 5)
  sync.destroy({ flushCheckpoint: false })
})

test('AI 预览暂停期间仍以原 Yjs 文档确认云端应用栅栏', async () => {
  const token = 'abcdef0123456789abcdef0123456789'
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap, 4, {
    onCollaborationBarrierPrepare: async () => ({
      ready: true,
      contentRevision: 4,
    }),
  })
  sync.initFromMindmap(createDocument())
  sync.serverCapabilities = new Set([
    'collaboration-mutation-barrier-v1',
    'yjs-checkpoint-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.pause()
  // The canvas can now show speculative AI content. The Y.Doc checkpoint
  // must still describe the original committed tree.
  const originalNodeCount = sync.yNodes.size
  mindMap.updateData({
    data: { uid: 'root', text: '预览' },
    children: [
      { data: { uid: 'child', text: '原节点' }, children: [] },
      { data: { uid: 'preview-only', text: 'AI 新节点' }, children: [] },
    ],
  })
  assert.equal(sync.yNodes.size, originalNodeCount)
  sync._checkpointDirty = true
  assert.equal(sync._flushCheckpoint(), false)

  await sync._handleCollaborationBarrierPrepare({
    token,
    operation: 'apply',
    contentRevision: 4,
  })
  const messages = sent.filter(message => (
    message.type === 'checkpoint' || message.type === 'collaboration_barrier_ack'
  ))
  assert.deepEqual(messages.map(message => message.type), [
    'checkpoint',
    'collaboration_barrier_ack',
  ])
  assert.equal(messages[0].barrierToken, token)
  assert.equal(messages[1].ready, true)
  assert.equal(sync.yNodes.size, originalNodeCount)
  sync.destroy({ flushCheckpoint: false })
})

test('AI 协作栅栏在排空后版本变化或检查点发送失败时拒绝 ready ACK', async () => {
  const token = 'fedcba9876543210fedcba9876543210'
  const revisionChanged = new YjsMindmapSync(
    1,
    createMindmap(createDocument()),
    7,
    {
      onCollaborationBarrierPrepare: async () => ({
        ready: true,
        contentRevision: 8,
      }),
    },
  )
  revisionChanged.initFromMindmap(createDocument())
  revisionChanged.serverCapabilities = new Set([
    'collaboration-mutation-barrier-v1',
    'yjs-checkpoint-v1',
  ])
  const changedMessages = []
  revisionChanged.wsClient.send = message => {
    changedMessages.push(message)
    return true
  }
  await revisionChanged._handleCollaborationBarrierPrepare({
    token,
    operation: 'undo',
    contentRevision: 7,
  })
  const changedProtocolMessages = changedMessages.filter(
    message => message.type !== 'awareness',
  )
  assert.deepEqual(changedProtocolMessages.map(message => message.type), [
    'collaboration_barrier_ack',
  ])
  assert.equal(changedProtocolMessages[0].ready, false)
  revisionChanged._handleCollaborationBarrierReleased({
    token,
    status: 'aborted',
    contentRevision: 7,
  })
  revisionChanged.destroy({ flushCheckpoint: false })

  const checkpointFailed = new YjsMindmapSync(
    2,
    createMindmap(createDocument()),
    7,
    {
      onCollaborationBarrierPrepare: async () => ({
        ready: true,
        contentRevision: 7,
      }),
    },
  )
  checkpointFailed.initFromMindmap(createDocument())
  checkpointFailed.serverCapabilities = new Set([
    'collaboration-mutation-barrier-v1',
    'yjs-checkpoint-v1',
  ])
  const failedMessages = []
  checkpointFailed.wsClient.send = message => {
    failedMessages.push(message)
    return message.type !== 'checkpoint'
  }
  await checkpointFailed._handleCollaborationBarrierPrepare({
    token,
    operation: 'apply',
    contentRevision: 7,
  })
  const failedProtocolMessages = failedMessages.filter(
    message => message.type !== 'awareness',
  )
  assert.deepEqual(failedProtocolMessages.map(message => message.type), [
    'checkpoint',
    'collaboration_barrier_ack',
  ])
  assert.equal(failedProtocolMessages[1].ready, false)
  checkpointFailed._handleCollaborationBarrierReleased({
    token,
    status: 'aborted',
    contentRevision: 7,
  })
  checkpointFailed.destroy({ flushCheckpoint: false })
})

test('AI 栅栏超时进入权威未知态且慢提交期间绝不伪装 aborted 解锁', async () => {
  const token = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  const unknownEvents = []
  const released = []
  const sync = new YjsMindmapSync(3, createMindmap(createDocument()), 11, {
    onCollaborationBarrierPrepare: async () => ({
      ready: true,
      contentRevision: 11,
    }),
    onCollaborationBarrierUnknown: data => unknownEvents.push(data),
    onCollaborationBarrierReleased: data => released.push(data),
  })
  sync.initFromMindmap(createDocument())
  sync.serverCapabilities = new Set([
    'collaboration-mutation-barrier-v1',
    'yjs-checkpoint-v1',
  ])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  await sync._handleCollaborationBarrierPrepare({
    token,
    operation: 'apply',
    contentRevision: 11,
  })

  clearTimeout(sync._collaborationBarrierTimer)
  sync._handleCollaborationBarrierTimeout(token, 11)
  assert.equal(sync.isStructureWriteBlocked(), true)
  assert.equal(sync._collaborationBarrierToken, token)
  assert.equal(sync.connectionState.value, 'syncing')
  assert.equal(unknownEvents.length, 1)
  assert.equal(
    sent.some(message => (
      message.type === 'collaboration_barrier_status_request'
      && message.token === token
      && message.contentRevision === 11
    )),
    true,
  )

  // 服务端持有 DB 行锁或仍在 committing 时只能返回 active/unknown。
  // 任意等待时长都不得合成 aborted 并恢复旧画布写入。
  sync._handleCollaborationBarrierStatus({
    token,
    status: 'active',
    contentRevision: 11,
  })
  sync._handleCollaborationBarrierStatus({
    token,
    status: 'aborted',
    contentRevision: 12,
  })
  assert.equal(sync.isStructureWriteBlocked(), true)
  assert.equal(sync._collaborationBarrierToken, token)
  assert.equal(released.length, 0)

  sync._handleCollaborationBarrierStatus({
    token,
    status: 'aborted',
    contentRevision: 11,
  })
  assert.equal(sync.isStructureWriteBlocked(), false)
  assert.equal(released.length, 1)
  assert.equal(released[0].reason, 'barrier_status_confirmed')
  sync.destroy({ flushCheckpoint: false })
})

test('丢失 committed release 后仅凭更高权威 revision 收敛并触发重载', async () => {
  const token = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
  const resets = []
  const sync = new YjsMindmapSync(4, createMindmap(createDocument()), 15, {
    onCollaborationBarrierPrepare: async () => ({
      ready: true,
      contentRevision: 15,
    }),
    onDocumentReset: data => resets.push(data),
  })
  sync.initFromMindmap(createDocument())
  sync.serverCapabilities = new Set([
    'collaboration-mutation-barrier-v1',
    'yjs-checkpoint-v1',
  ])
  sync.wsClient.send = () => true
  await sync._handleCollaborationBarrierPrepare({
    token,
    operation: 'undo',
    contentRevision: 15,
  })

  clearTimeout(sync._collaborationBarrierTimer)
  sync._handleCollaborationBarrierTimeout(token, 15)
  sync._handleCollaborationBarrierStatus({
    token,
    status: 'committed',
    contentRevision: 16,
  })

  assert.equal(sync._collaborationBarrierToken, '')
  assert.equal(sync.isStructureWriteBlocked(), false)
  assert.equal(sync._authoritativeRevisionPending, 16)
  assert.equal(resets.length, 1)
  assert.equal(resets[0].contentRevision, 16)
  sync.destroy({ flushCheckpoint: false })
})
