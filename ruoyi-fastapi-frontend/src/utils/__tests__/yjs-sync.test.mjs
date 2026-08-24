import assert from 'node:assert/strict'
import test from 'node:test'
import * as Y from 'yjs'

import {
  isStructuredPatchTransportSafe,
  YjsMindmapSync,
} from '../yjs-sync.js'

function createMindmap(document) {
  let current = structuredClone(document)
  const calls = []
  const listeners = new Map()
  const markerUsers = new Map()
  const nodeByUid = new Map()
  const registerNodes = (node) => {
    if (!node?.data?.uid) return
    const users = markerUsers.get(node.data.uid) || new Set()
    markerUsers.set(node.data.uid, users)
    nodeByUid.set(node.data.uid, {
      uid: node.data.uid,
      addUser(user) { users.add(String(user.id)) },
      removeUser(user) { users.delete(String(user.id)) },
    })
    for (const child of (node.children || [])) registerNodes(child)
  }
  registerNodes(current.root)
  return {
    calls,
    markerUsers,
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
        tag: [{ tagId: 8, text: '托管名称', style: { fill: '#f00' } }],
      },
      children: [{ data: { uid: 'child', text: '子节点' }, children: [] }],
    },
    layout: 'logicalStructure',
    theme: { template: 'default', config: { lineColor: '#999' } },
    view: { transform: { scaleX: 1, scaleY: 1 } },
    documentData: { simpleMindMap: { config: { imgTextMargin: 8 } } },
  }
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

test('不安全节点修复快照被省略但不会阻断 Yjs 增量生成', () => {
  const document = createDocument()
  const sync = new YjsMindmapSync(1, createMindmap(document))
  sync.initFromMindmap(document)
  sync.serverCapabilities.add('yjs-checkpoint-v1')
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
  }])

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

test('初始化同时写入节点、标签引用和文档元数据', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(createDocument())

  assert.equal(sync.yNodes.size, 2)
  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{ tagId: 8 }])
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

  assert.deepEqual(sourceSync.yNodes.get('root').get('data').get('tag'), [{ tagId: 8 }])
  assert.equal(targetSync.tagDefinitions.get('8').text, '托管名称')
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
  assert.deepEqual(mindMap.getData().data.tag, [{ tagId: 8 }])
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
    style: { fill: '#123456', color: '#fff' },
  })
  sync._handleUpdate({
    state: sync._encodeUpdate(Y.encodeStateAsUpdate(remoteDoc)),
  })

  assert.equal(sync.tagDefinitions.get('8').text, '重连后的名称')
  assert.equal(sync.tagDefinitions.get('8').definitionRevision, 6)
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

test('节点完整更新会清除已经移除的图片字段', () => {
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(createDocument())

  sync.onDataChangeDetail([{
    action: 'update',
    data: {
      data: { uid: 'root', text: '已清除图片' },
      children: [{ data: { uid: 'child' } }],
    },
  }])

  const data = Object.fromEntries(sync.yNodes.get('root').get('data').entries())
  assert.equal(data.image, undefined)
  assert.equal(data.text, '已清除图片')
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
  source.destroy()
  target.destroy()
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
  }])

  const updateMessage = sent.find(message => message.type === 'update')
  assert.ok(updateMessage.update)
  assert.ok(updateMessage.state)
  assert.deepEqual(updateMessage.patch, {
    schemaVersion: 1,
    nodes: [{
      uid: 'child',
      data: { uid: 'child', text: '<p>紧凑补丁</p>' },
      children: [],
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
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
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
  }])

  const updateMessage = sent.find(message => message.type === 'update')
  assert.ok(updateMessage.update)
  assert.equal(updateMessage.state, undefined)
  assert.equal(updateMessage.patch.applyMeta, false)
  assert.equal(sync._checkpointDirty, true)

  assert.equal(sync._flushCheckpoint({ reschedule: false }), true)
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.ok(checkpoint.state)
  assert.equal(checkpoint.contentRevision, 1)
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
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
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
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  const sent = []
  sync.wsClient.connect = () => {}
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }
  sync.start()

  sync.syncDocumentMeta({ layout: 'fishbone' })

  const updateMessage = sent.find(message => message.type === 'update')
  assert.equal(updateMessage.state, undefined)
  assert.deepEqual(updateMessage.patch, {
    schemaVersion: 1,
    nodes: [],
    deletedNodeUids: [],
    applyMeta: true,
  })
  sync.destroy()
  assert.ok(sent.some(message => message.type === 'checkpoint'))
})

test('远端紧凑元数据补丁会立即应用布局而无需等待完整检查点', () => {
  const document = createDocument()
  const source = new YjsMindmapSync(1, createMindmap(document))
  source.initFromMindmap(document)
  const targetMindMap = createMindmap(document)
  const target = new YjsMindmapSync(1, targetMindMap)
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

test('节点删除补丁会在远端清理整个子树及父节点引用', () => {
  const document = createDocument()
  document.root.children[0].children = [{
    data: { uid: 'grandchild', text: '孙节点' },
    children: [],
  }]
  const target = new YjsMindmapSync(1, createMindmap(document))
  target.initFromMindmap(document)
  const emptyDoc = new Y.Doc()

  target._handleUpdate({
    update: target._encodeUpdate(Y.encodeStateAsUpdate(emptyDoc)),
    patch: {
      schemaVersion: 1,
      nodes: [],
      deletedNodeUids: ['child'],
    },
  })

  assert.equal(target.yNodes.has('child'), false)
  assert.equal(target.yNodes.has('grandchild'), false)
  assert.deepEqual(target.yNodes.get('root').get('children').toArray(), [])
  emptyDoc.destroy()
  target.destroy()
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

test('远程渲染结束前持续阻止异步 data_change 被当成本地修改', async () => {
  const mindMap = createMindmap(createDocument())
  const originalUpdateData = mindMap.updateData
  const applyingStates = []
  const sync = new YjsMindmapSync(1, mindMap)
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
  sync._localActiveNodeUids = ['child']

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

test('远端与本地修改同一节点时仍会安全清空撤销历史', async () => {
  const document = createDocument()
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
  }
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync.yNodes.get('child').get('data').set('text', '远端竞争值')

  assert.equal(await sync._applyYjsToMindmap(), true)

  assert.equal(clearHistoryCount, 1)
  assert.deepEqual(mindMap.command.history, [])
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
  const sync = new YjsMindmapSync(1, mindMap, 1, {
    prepareDocument: async () => {
      prepareCount += 1
      if (prepareCount === 1) {
        await new Promise(resolve => { releaseFirstPrepare = resolve })
      }
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
  assert.equal(mindMap.calls.length, 0)

  sync.yNodes.get('child').get('data').set('text', '加载期间到达的新内容')
  releaseFirstPrepare()
  assert.equal(await firstApply, true)
  assert.equal(prepareCount, 2)
  assert.equal(mindMap.getData().children[0].data.text, '加载期间到达的新内容')
  mindMap.emit('node_tree_render_end')
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

test('远程元数据通过完整文档接口应用布局、主题、视图和展示设置', () => {
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
  assert.equal(call.value.view.transform.scaleX, 1.5)
  assert.equal(appliedMeta.documentData.simpleMindMap.config.textContentMargin, 6)
  sync.destroy()
})

test('仅视图协作更新不走清空选区的完整数据替换', async () => {
  const document = createDocument()
  const mindMap = createMindmap(document)
  const sync = new YjsMindmapSync(1, mindMap)
  sync.initFromMindmap(document)
  sync._localActiveNodeUids = ['child']
  sync.yMeta.set('viewData', {
    transform: { scaleX: 1.25, scaleY: 1.25, translateX: -200 },
  })

  assert.equal(await sync._applyYjsToMindmap({ applyMeta: true }), true)
  assert.deepEqual(mindMap.calls.map(call => call.type), ['tree', 'view'])
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
  })
  assert.deepEqual(sync.collaborators.value.map(user => user.id), [2])
  assert.deepEqual([...mindMap.markerUsers.get('child')], ['2'])

  sync.wsClient.handlers.onClose()

  assert.deepEqual(sync.collaborators.value, [])
  assert.deepEqual([...mindMap.markerUsers.get('child')], [])
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
  sync.destroy()
})

test('同步握手会合并服务端保存的多个并发 Yjs 状态', () => {
  const first = new Y.Doc()
  first.getMap('proof').set('fromA', 'A')
  const second = new Y.Doc()
  second.getMap('proof').set('fromB', 'B')
  const mindMap = createMindmap(createDocument())
  const sync = new YjsMindmapSync(1, mindMap)

  sync._handleSyncInit({
    states: [
      sync._encodeUpdate(Y.encodeStateAsUpdate(first)),
      sync._encodeUpdate(Y.encodeStateAsUpdate(second)),
    ],
  })

  assert.equal(sync.doc.getMap('proof').get('fromA'), 'A')
  assert.equal(sync.doc.getMap('proof').get('fromB'), 'B')
  sync.destroy()
  first.destroy()
  second.destroy()
})

test('同步握手确认已覆盖来源并发送安全压缩检查点', () => {
  const first = new Y.Doc()
  first.getMap('proof').set('fromA', 'A')
  const second = new Y.Doc()
  second.getMap('proof').set('fromB', 'B')
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 6)
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit({
    states: [
      sync._encodeUpdate(Y.encodeStateAsUpdate(first)),
      sync._encodeUpdate(Y.encodeStateAsUpdate(second)),
    ],
    stateSources: ['source-a', 'source-b'],
  })

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

test('明确使用云端版本时丢弃同 revision 协作缓存并替换其来源', () => {
  const document = createDocument()
  const remote = new Y.Doc()
  const staleSync = new YjsMindmapSync(1, createMindmap(document), 6)
  staleSync.initFromMindmap(document)
  Y.applyUpdate(remote, Y.encodeStateAsUpdate(staleSync.doc))
  remote.getMap('nodes').get('root').get('data').set('text', '已丢弃的协作缓存')

  const sync = new YjsMindmapSync(1, createMindmap(document), 6, {
    preferAuthoritativeDocument: true,
    getDocumentData: () => document.documentData,
  })
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit({
    states: [sync._encodeUpdate(Y.encodeStateAsUpdate(remote))],
    stateSources: ['stale-source'],
  })

  assert.equal(sync.yNodes.get('root').get('data').get('text'), '根节点')
  assert.equal(sync.requiresAuthoritativeReconciliation(), false)
  const checkpoint = sent.find(message => message.type === 'checkpoint')
  assert.deepEqual(checkpoint.replacesSources, ['stale-source'])
  const authoritative = new Y.Doc()
  Y.applyUpdate(authoritative, sync._decodeUpdate(checkpoint.state))
  assert.equal(authoritative.getMap('nodes').get('root').get('data').get('text'), '根节点')

  authoritative.destroy()
  sync.destroy({ flushCheckpoint: false })
  staleSync.destroy({ flushCheckpoint: false })
  remote.destroy()
})

test('同步握手隔离损坏来源并用有效状态生成修复检查点', () => {
  const validDoc = new Y.Doc()
  validDoc.getMap('proof').set('valid', '保留内容')
  const sync = new YjsMindmapSync(1, createMindmap(createDocument()), 7)
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit({
    states: [
      sync._encodeUpdate(Y.encodeStateAsUpdate(validDoc)),
      'not-valid-base64!',
    ],
    stateSources: ['valid-source', 'corrupt-source'],
  })

  assert.equal(sync.doc.getMap('proof').get('valid'), '保留内容')
  assert.equal(sync.connectionState.value, 'degraded')
  assert.match(sync.syncError.value, /1 份异常/)
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
  sync.serverCapabilities = new Set(['yjs-checkpoint-v1'])
  const sent = []
  sync.wsClient.send = message => {
    sent.push(message)
    return true
  }

  sync._handleSyncInit({
    states: ['not-valid-base64!'],
    stateSources: ['corrupt-only'],
  })

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
  assert.equal(sync.yNodes.size, 2)
  assert.equal(sync.connectionState.value, 'degraded')
  assert.match(sync.syncError.value, /33 份异常/)
  assert.equal(sent.some(message => message.type === 'checkpoint'), false)

  sync.destroy()
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
    definitionRevision: 3,
    definition: { tagId: 9, text: '替换标签', style: { fill: '#0f0' } },
  })

  assert.equal(definitionChanges.length, 1)
  assert.deepEqual(new Set(definitionChanges[0]), new Set(['8', '9']))
  assert.equal(sync.yTagDefinitions.has('8'), false)
  assert.equal(sync.yTagDefinitions.get('9').text, '替换标签')
  assert.deepEqual(sync.yNodes.get('root').get('data').get('tag'), [{ tagId: 9 }])
  sync.destroy()
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
