import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyCrossNodeOperationIntents,
  applyMindmapFileMetaIntents,
  applyMindmapNodeDataOperationIntents,
  applyMindmapOperationIntents,
  applyMindmapNodeRevisionChanges,
  appendUniqueMindmapOperation,
  buildCrossNodeContentOperations,
  buildMindmapDocumentOperations,
  buildMindmapContentOperations,
  buildMindmapTreeDetailList,
  buildNodeTagContentOperations,
  captureMindmapFileMetaIntents,
  compactMindmapContentOperations,
  detectMindmapFileOperations,
  findConflictingMindmapFileMetaIntents,
  mergePendingCrossNodeOperation,
  rebaseMindmapOperationTargetRevisions,
  snapshotMindmapDocumentMeta,
} from '../mindmap-operations.js'

function cloneJson(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

function testPayloadValue(payload, camelKey, snakeKey) {
  return payload?.[camelKey] ?? payload?.[snakeKey]
}

function testCrossNodeReferences(payload = {}, prefix = '') {
  if (prefix === 'relation') {
    return [
      testPayloadValue(payload, 'sourceUid', 'source_uid'),
      testPayloadValue(payload, 'targetUid', 'target_uid'),
    ]
  }
  if (prefix === 'summary') {
    return [
      testPayloadValue(payload, 'ownerUid', 'owner_uid'),
      testPayloadValue(payload, 'startChildUid', 'start_child_uid'),
      testPayloadValue(payload, 'endChildUid', 'end_child_uid'),
    ]
  }
  if (prefix === 'group') {
    const memberUids = testPayloadValue(payload, 'memberUids', 'member_uids')
    return Array.isArray(memberUids) ? memberUids : []
  }
  return []
}

/** Replay the identity/edge domains affected by provisional subtree compaction. */
function replayStructuralOperations(operations, initialNodes = []) {
  const nodes = new Map(initialNodes.map(node => [node.uid, {
    uid: node.uid,
    childUids: [...(node.childUids || [])],
  }]))
  const tagBindings = new Map()
  const crossRecords = new Map()

  for (const operation of operations) {
    const nodeUid = operation.nodeUid ?? operation.node_uid
    const payload = operation.payload || {}
    if (operation.type === 'node.create') {
      nodes.set(nodeUid, {
        uid: nodeUid,
        childUids: [...(testPayloadValue(payload, 'childUids', 'child_uids') || [])],
      })
      continue
    }
    if (operation.type === 'node.update') {
      const node = nodes.get(nodeUid)
      if (node && payload.childrenChanged === true) {
        node.childUids = [...(testPayloadValue(payload, 'childUids', 'child_uids') || [])]
      }
      continue
    }
    if (operation.type === 'node.delete') {
      const declaredScope = testPayloadValue(payload, 'deletedNodeUids', 'deleted_node_uids')
      const deleted = new Set((declaredScope || [nodeUid]).map(String))
      for (const uid of deleted) nodes.delete(uid)
      for (const node of nodes.values()) {
        node.childUids = node.childUids.filter(uid => !deleted.has(String(uid)))
      }
      for (const [key, binding] of tagBindings) {
        if (deleted.has(String(binding.nodeUid))) tagBindings.delete(key)
      }
      for (const [key, record] of crossRecords) {
        if (record.references.some(uid => deleted.has(String(uid)))) crossRecords.delete(key)
      }
      continue
    }
    if (operation.type?.startsWith('node.tag.')) {
      const key = String(payload.key || `${nodeUid}:${payload.tagKey || ''}`)
      if (operation.type === 'node.tag.unbind') tagBindings.delete(key)
      else tagBindings.set(key, { nodeUid, payload: cloneJson(payload) })
      continue
    }
    const prefix = operation.type?.split('.')[0]
    if (!['relation', 'summary', 'group', 'asset'].includes(prefix)) continue
    const key = String(payload.key || '')
    if (operation.type.endsWith('.delete')) crossRecords.delete(`${prefix}:${key}`)
    else {
      crossRecords.set(`${prefix}:${key}`, {
        payload: cloneJson(payload),
        references: testCrossNodeReferences(payload, prefix),
      })
    }
  }

  return {
    nodes: [...nodes.values()].sort((left, right) => left.uid.localeCompare(right.uid)),
    tagBindings: [...tagBindings].sort(([left], [right]) => left.localeCompare(right)),
    crossRecords: [...crossRecords].sort(([left], [right]) => left.localeCompare(right)),
  }
}

/** Replay the per-field node patch semantics used by the backend merger. */
function replayNodeDataUpdates(initialData, operations) {
  const data = cloneJson(initialData)
  for (const operation of operations) {
    if (operation.type !== 'node.update' || operation.payload?.dataChanged !== true) continue
    const payload = operation.payload
    const previousData = testPayloadValue(payload, 'previousData', 'previous_data') || {}
    const currentData = payload.data || {}
    const ignoredFields = new Set()
    if (testPayloadValue(payload, 'tagBindingsSeparated', 'tag_bindings_separated') === true) {
      ignoredFields.add('tag')
    }
    if (testPayloadValue(payload, 'crossNodeDataSeparated', 'cross_node_data_separated') === true) {
      for (const key of [
        'associativeLineTargets',
        'associativeLineTargetControlOffsets',
        'associativeLinePoint',
        'associativeLineText',
        'associativeLineStyle',
        'generalization',
        'outerFrame',
        'imgMap',
      ]) ignoredFields.add(key)
    }
    for (const key of new Set([...Object.keys(previousData), ...Object.keys(currentData)])) {
      if (ignoredFields.has(key)) continue
      if (JSON.stringify(previousData[key]) === JSON.stringify(currentData[key])) continue
      if (Object.hasOwn(currentData, key)) data[key] = cloneJson(currentData[key])
      else delete data[key]
    }
  }
  return data
}

test('同一保存窗口内的节点修改与移动撤销会折叠为净操作', () => {
  const operations = compactMindmapContentOperations([
    {
      type: 'node.update',
      nodeUid: 'node-a',
      targetRevision: 7,
      payload: {
        data: { uid: 'node-a', text: '第一次修改' },
        previousData: { uid: 'node-a', text: '原文' },
        childUids: ['child'],
        oldChildUids: [],
        dataChanged: true,
        childrenChanged: true,
        crossNodeDataSeparated: true,
        tagBindingsSeparated: true,
      },
    },
    { type: 'file.theme.update' },
    {
      type: 'node.update',
      nodeUid: 'node-a',
      targetRevision: 7,
      payload: {
        data: { uid: 'node-a', text: '原文' },
        previousData: { uid: 'node-a', text: '第一次修改' },
        childUids: [],
        oldChildUids: ['child'],
        dataChanged: true,
        childrenChanged: true,
        crossNodeDataSeparated: true,
        tagBindingsSeparated: true,
      },
    },
  ])

  assert.deepEqual(operations, [{ type: 'file.theme.update' }])
})

test('连续节点修改保留最初前态、最终状态和节点 revision', () => {
  const operations = compactMindmapContentOperations([
    {
      type: 'node.update',
      nodeUid: 'node-a',
      targetRevision: 4,
      payload: {
        data: { uid: 'node-a', text: '中间值', color: 'red' },
        previousData: { uid: 'node-a', text: '旧值', color: 'red' },
        childUids: [], oldChildUids: [],
        dataChanged: true, childrenChanged: false,
        crossNodeDataSeparated: true, tagBindingsSeparated: true,
      },
    },
    {
      type: 'node.update',
      nodeUid: 'node-a',
      payload: {
        data: { uid: 'node-a', text: '最终值', color: 'blue' },
        previousData: { uid: 'node-a', text: '中间值', color: 'red' },
        childUids: ['child'], oldChildUids: [],
        dataChanged: true, childrenChanged: true,
        crossNodeDataSeparated: true, tagBindingsSeparated: true,
      },
    },
  ])

  assert.equal(operations.length, 1)
  assert.equal(operations[0].targetRevision, 4)
  assert.deepEqual(operations[0].payload.previousData, {
    uid: 'node-a', text: '旧值', color: 'red',
  })
  assert.deepEqual(operations[0].payload.data, {
    uid: 'node-a', text: '最终值', color: 'blue',
  })
  assert.deepEqual(operations[0].payload.childUids, ['child'])
  assert.deepEqual(operations[0].payload.oldChildUids, [])
})

test('新建后删除被吸收，但删除后撤销恢复仍保留原操作顺序', () => {
  const create = {
    type: 'node.create',
    nodeUid: 'temporary',
    payload: {
      data: { uid: 'temporary', text: '临时节点' },
      childUids: [], oldChildUids: [],
      dataChanged: true, childrenChanged: false,
      crossNodeDataSeparated: true, tagBindingsSeparated: true,
    },
  }
  const remove = {
    type: 'node.delete',
    nodeUid: 'temporary',
    payload: { deletedNodeUids: ['temporary'] },
  }

  assert.deepEqual(compactMindmapContentOperations([create, remove]), [])
  assert.deepEqual(compactMindmapContentOperations([remove, create]), [remove, create])
})

test('新建临时子树后删除会吸收后代、标签及跨节点临时操作', () => {
  const createNode = (uid, childUids = []) => ({
    type: 'node.create',
    nodeUid: uid,
    payload: {
      data: { uid, text: uid },
      childUids,
      oldChildUids: [],
      dataChanged: true,
      childrenChanged: childUids.length > 0,
      crossNodeDataSeparated: true,
      tagBindingsSeparated: true,
    },
  })
  const originalOperations = [
    createNode('parent', ['child']),
    createNode('child'),
    {
      type: 'node.tag.bind',
      nodeUid: 'child',
      payload: { key: 'child:7', tagKey: '7', tag: { tagId: 7 } },
    },
    {
      type: 'relation.upsert',
      payload: {
        key: 'assoc:parent:child',
        sourceUid: 'parent',
        targetUid: 'child',
      },
    },
    {
      type: 'node.delete',
      nodeUid: 'parent',
      payload: { deletedNodeUids: ['parent', 'child'] },
    },
  ]
  const operations = compactMindmapContentOperations(originalOperations)

  assert.deepEqual(operations, [])
  assert.deepEqual(
    replayStructuralOperations(operations),
    replayStructuralOperations(originalOperations),
  )
})

test('节点领域分离标志变化时不合并载荷以避免静默删除数据', () => {
  const originalOperations = [
    {
      type: 'node.update',
      nodeUid: 'node-a',
      payload: {
        data: { uid: 'node-a', text: '旧协议', tag: [{ tagId: 8 }] },
        previousData: { uid: 'node-a', text: '原文', tag: [{ legacy: true }] },
        childUids: [], oldChildUids: [],
        dataChanged: true, childrenChanged: false,
        crossNodeDataSeparated: false, tagBindingsSeparated: false,
      },
    },
    {
      type: 'node.update',
      nodeUid: 'node-a',
      payload: {
        data: { uid: 'node-a', text: '新协议' },
        previousData: { uid: 'node-a', text: '旧协议' },
        childUids: [], oldChildUids: [],
        dataChanged: true, childrenChanged: false,
        crossNodeDataSeparated: true, tagBindingsSeparated: true,
      },
    },
  ]
  const operations = compactMindmapContentOperations(originalOperations)

  assert.equal(operations.length, 2)
  assert.equal(operations[0].payload.tagBindingsSeparated, false)
  assert.deepEqual(operations[0].payload.data.tag, [{ tagId: 8 }])
  assert.equal(operations[1].payload.tagBindingsSeparated, true)
  const initialData = { uid: 'node-a', text: '原文', tag: [{ legacy: true }] }
  assert.deepEqual(
    replayNodeDataUpdates(initialData, operations),
    replayNodeDataUpdates(initialData, originalOperations),
  )
  assert.deepEqual(
    replayNodeDataUpdates(initialData, operations).tag,
    [{ tagId: 8 }],
  )
})

test('任一单独的领域分离标志变化都会保留原始 update/create 顺序', () => {
  const update = (text, previousText, flags) => ({
    type: 'node.update',
    nodeUid: 'node-a',
    payload: {
      data: { uid: 'node-a', text },
      previousData: { uid: 'node-a', text: previousText },
      childUids: [], oldChildUids: [],
      dataChanged: true, childrenChanged: false,
      ...flags,
    },
  })
  for (const [firstFlags, secondFlags] of [
    [
      { crossNodeDataSeparated: true, tagBindingsSeparated: false },
      { crossNodeDataSeparated: true, tagBindingsSeparated: true },
    ],
    [
      { crossNodeDataSeparated: false, tagBindingsSeparated: true },
      { crossNodeDataSeparated: true, tagBindingsSeparated: true },
    ],
  ]) {
    assert.equal(compactMindmapContentOperations([
      update('中间值', '原文', firstFlags),
      update('最终值', '中间值', secondFlags),
    ]).length, 2)
  }

  const createThenUpdate = compactMindmapContentOperations([{
    type: 'node.create',
    nodeUid: 'new-node',
    payload: {
      data: { uid: 'new-node', text: '新建' },
      childUids: [], oldChildUids: [],
      dataChanged: true, childrenChanged: false,
      crossNodeDataSeparated: true, tagBindingsSeparated: false,
    },
  }, {
    ...update('编辑后', '新建', {
      crossNodeDataSeparated: true,
      tagBindingsSeparated: true,
    }),
    nodeUid: 'new-node',
  }])
  assert.deepEqual(createThenUpdate.map(operation => operation.type), [
    'node.create',
    'node.update',
  ])
})

test('删除现存父节点时只吸收其临时后代操作，并保留无节点引用的资源', () => {
  const originalOperations = [{
    type: 'node.update',
    nodeUid: 'stable-parent',
    payload: {
      data: { uid: 'stable-parent' },
      childUids: ['temporary-child'], oldChildUids: [],
      dataChanged: false, childrenChanged: true,
      crossNodeDataSeparated: true, tagBindingsSeparated: true,
    },
  }, {
    type: 'node.create',
    nodeUid: 'temporary-child',
    payload: {
      data: { uid: 'temporary-child' },
      childUids: [], oldChildUids: [],
      dataChanged: true, childrenChanged: false,
      crossNodeDataSeparated: true, tagBindingsSeparated: true,
    },
  }, {
    type: 'summary.upsert',
    payload: {
      key: 'stable-parent:temporary-summary',
      ownerUid: 'stable-parent',
      startChildUid: 'temporary-child',
      endChildUid: 'temporary-child',
    },
  }, {
    type: 'asset.upsert',
    payload: {
      key: 'asset-1',
      assetKey: 'asset-1',
      // An arbitrary payload string equal to a node UID is not a node reference.
      uri: 'temporary-child',
    },
  }, {
    type: 'node.delete',
    nodeUid: 'stable-parent',
    targetRevision: 4,
    payload: { deletedNodeUids: ['stable-parent', 'temporary-child'] },
  }]
  const operations = compactMindmapContentOperations(originalOperations)

  assert.deepEqual(operations.map(operation => operation.type), [
    'asset.upsert',
    'node.delete',
  ])
  assert.deepEqual(
    replayStructuralOperations(operations, [{ uid: 'stable-parent' }]),
    replayStructuralOperations(originalOperations, [{ uid: 'stable-parent' }]),
  )
})

test('只删除临时子节点时会从仍保留的 create 父节点中移除其子引用', () => {
  const originalOperations = [{
    type: 'node.create',
    nodeUid: 'temporary-parent',
    payload: {
      data: { uid: 'temporary-parent' },
      childUids: ['temporary-child'], oldChildUids: [],
      dataChanged: true, childrenChanged: true,
      crossNodeDataSeparated: true, tagBindingsSeparated: true,
    },
  }, {
    type: 'node.create',
    nodeUid: 'temporary-child',
    payload: {
      data: { uid: 'temporary-child' },
      childUids: [], oldChildUids: [],
      dataChanged: true, childrenChanged: false,
      crossNodeDataSeparated: true, tagBindingsSeparated: true,
    },
  }, {
    type: 'node.delete',
    nodeUid: 'temporary-child',
    payload: { deletedNodeUids: ['temporary-child'] },
  }]
  const operations = compactMindmapContentOperations(originalOperations)

  assert.equal(operations.length, 1)
  assert.equal(operations[0].type, 'node.create')
  assert.deepEqual(operations[0].payload.childUids, [])
  assert.equal(operations[0].payload.childrenChanged, false)
  assert.deepEqual(
    replayStructuralOperations(operations),
    replayStructuralOperations(originalOperations),
  )
})

test('新建后的连续编辑会折叠进最终 create 载荷', () => {
  const operations = compactMindmapContentOperations([
    {
      type: 'node.create', nodeUid: 'new-node',
      payload: {
        data: { uid: 'new-node', text: '新节点' },
        childUids: [], oldChildUids: [],
        dataChanged: true, childrenChanged: false,
        crossNodeDataSeparated: true, tagBindingsSeparated: true,
      },
    },
    {
      type: 'node.update', nodeUid: 'new-node',
      payload: {
        data: { uid: 'new-node', text: '已编辑' },
        previousData: { uid: 'new-node', text: '新节点' },
        childUids: ['child'], oldChildUids: [],
        dataChanged: true, childrenChanged: true,
        crossNodeDataSeparated: true, tagBindingsSeparated: true,
      },
    },
  ])

  assert.equal(operations.length, 1)
  assert.equal(operations[0].type, 'node.create')
  assert.deepEqual(operations[0].payload.data, { uid: 'new-node', text: '已编辑' })
  assert.deepEqual(operations[0].payload.childUids, ['child'])
  assert.equal(operations[0].targetRevision, undefined)
})

test('已提交批次会原子更新节点 revision 并重定基于旧栅栏的后续操作', () => {
  const revisions = new Map([['edited', 4], ['deleted', 2]])
  applyMindmapNodeRevisionChanges(revisions, [
    { action: 'update', nodeUid: 'edited', nodeRevision: 5 },
    { action: 'delete', nodeUid: 'deleted' },
    { action: 'create', nodeUid: 'created', nodeRevision: 1 },
  ])
  assert.deepEqual([...revisions], [['edited', 5], ['created', 1]])

  const edgeOnly = {
    type: 'node.update',
    nodeUid: 'edited',
    payload: { dataChanged: false, childrenChanged: true },
  }
  const operations = rebaseMindmapOperationTargetRevisions([
    { type: 'node.update', nodeUid: 'edited', targetRevision: 4 },
    { type: 'node.delete', nodeUid: 'created', targetRevision: 9 },
    edgeOnly,
    { type: 'node.create', nodeUid: 'created' },
  ], revisions)

  assert.equal(operations[0].targetRevision, 5)
  assert.equal(operations[1].targetRevision, 1)
  assert.strictEqual(operations[2], edgeOnly)
  assert.equal(operations[3].targetRevision, undefined)
})

test('文档元数据比较不受对象 key 顺序影响', () => {
  const saved = snapshotMindmapDocumentMeta({
    layout: 'logicalStructure',
    theme: { config: { b: 2, a: 1 }, template: 'default' },
    view: { scale: 1 },
    documentData: { simpleMindMap: { config: { imgTextMargin: 8 } } },
  })
  const operations = detectMindmapFileOperations({
    layout: 'logicalStructure',
    theme: { template: 'default', config: { a: 1, b: 2 } },
    viewData: { scale: 1 },
    documentData: { simpleMindMap: { config: { imgTextMargin: 8 } } },
  }, saved)
  assert.deepEqual(operations, [])
})

test('布局、主题和文档扩展配置进入正文冲突域，视图独立保存', () => {
  const saved = snapshotMindmapDocumentMeta({
    layout: 'logicalStructure',
    theme: { template: 'default' },
    view: null,
    documentData: {},
  })
  const operations = detectMindmapFileOperations({
    layout: 'fishbone',
    theme: { template: 'dark' },
    view: { scale: 1.2 },
    documentData: { simpleMindMap: { config: { imgTextMargin: 12 } } },
  }, saved)
  assert.deepEqual(operations, [
    'file.layout.update',
    'file.theme.update',
    'file.document_data.update',
  ])
})

test('文件元数据意图按操作域深冻结并覆盖临时远端预览', () => {
  const local = {
    layout: 'fishbone',
    theme: { template: 'local', config: { lineColor: '#123' } },
    documentData: { simpleMindMap: { config: { imgTextMargin: 16 } } },
  }
  const intents = captureMindmapFileMetaIntents({}, local, [
    { type: 'file.layout.update' },
    { type: 'file.document_data.update' },
  ])
  local.documentData.simpleMindMap.config.imgTextMargin = 99
  const remotePreview = {
    layout: 'logicalStructure',
    theme: { template: 'remote' },
    documentData: { simpleMindMap: { config: { imgTextMargin: 32 } } },
  }

  assert.deepEqual(
    findConflictingMindmapFileMetaIntents(intents, remotePreview),
    ['file.layout.update', 'file.document_data.update'],
  )
  assert.deepEqual(applyMindmapFileMetaIntents(remotePreview, intents), {
    layout: 'fishbone',
    theme: { template: 'remote' },
    documentData: { simpleMindMap: { config: { imgTextMargin: 16 } } },
  })
  assert.equal(remotePreview.layout, 'logicalStructure')
  assert.equal(remotePreview.documentData.simpleMindMap.config.imgTextMargin, 32)
})

test('本地草稿恢复生成细粒度操作且忽略纯视图变化', () => {
  const previous = {
    root: {
      data: { uid: 'root', text: '根节点' },
      children: [{ data: { uid: 'old', text: '旧节点' }, children: [] }],
    },
    layout: 'logicalStructure',
    theme: { template: 'default' },
    view: { scale: 1 },
    documentData: {},
  }
  const current = {
    ...previous,
    root: {
      data: { uid: 'root', text: '根节点' },
      children: [{ data: { uid: 'new', text: '新节点' }, children: [] }],
    },
    view: { scale: 1.5 },
  }
  const operations = buildMindmapDocumentOperations(
    previous,
    current,
    new Map([['old', 4]]),
  )

  assert.deepEqual(operations.map(operation => operation.type), [
    'node.update',
    'node.create',
    'node.delete',
  ])
  assert.equal(operations.some(operation => operation.type === 'document.update'), false)
  assert.equal(operations.some(operation => operation.type === 'file.view.update'), false)
  assert.equal(operations.at(-1).targetRevision, 4)
  assert.deepEqual(operations.at(-1).payload.deletedNodeUids, ['old'])
})

test('删除父分支会记录完整子树身份用于检测后代并发编辑', () => {
  const deletedBranch = {
    data: { uid: 'parent', text: '父节点' },
    children: [{
      data: { uid: 'child', text: '子节点' },
      children: [{ data: { uid: 'leaf', text: '叶子' }, children: [] }],
    }],
  }

  const operations = buildMindmapContentOperations([{
    action: 'delete',
    // Command.emitDataUpdatesEvent 的在线删除事件使用 data；草稿恢复额外
    // 携带 oldData。这里覆盖真实在线事件形态。
    data: deletedBranch,
  }, {
    action: 'delete',
    data: deletedBranch.children[0],
  }, {
    action: 'delete',
    data: deletedBranch.children[0].children[0],
  }], new Map([['parent', 3]]))

  assert.equal(operations.length, 1)
  assert.deepEqual(
    operations[0].payload.deletedNodeUids,
    ['parent', 'child', 'leaf'],
  )
  assert.equal(operations[0].targetRevision, 3)
})

test('草稿差异只物化直接子节点并对超大批次安全回退', () => {
  const previousRoot = {
    data: { uid: 'root', text: '旧根节点' },
    children: [{
      data: { uid: 'child', text: '子节点' },
      children: [{ data: { uid: 'grandchild', text: '孙节点' }, children: [] }],
    }],
  }
  const currentRoot = {
    ...previousRoot,
    data: { uid: 'root', text: '新根节点' },
  }
  const details = buildMindmapTreeDetailList(previousRoot, currentRoot)
  assert.equal(details[0].data.children[0].data.uid, 'child')
  assert.deepEqual(details[0].data.children[0].children, [])

  const createWideDocument = suffix => ({
    root: {
      data: { uid: 'root', text: '根节点' },
      children: Array.from({ length: 2001 }, (_, index) => ({
        data: { uid: `node-${index}`, text: `节点 ${index} ${suffix}` },
        children: [],
      })),
    },
    layout: 'logicalStructure',
    theme: {},
    documentData: {},
  })
  assert.deepEqual(
    buildMindmapDocumentOperations(
      createWideDocument('旧'),
      createWideDocument('新'),
    ),
    [{ type: 'document.content.update' }],
  )
})

test('相同文件操作只入队一次', () => {
  const operations = []
  assert.equal(appendUniqueMindmapOperation(operations, 'file.view.update'), true)
  assert.equal(appendUniqueMindmapOperation(operations, 'file.view.update'), false)
  assert.deepEqual(operations, [{ type: 'file.view.update' }])
})

test('新增子节点会生成可并发合并的父边增量', () => {
  const oldRoot = { data: { uid: 'root', text: 'root' }, children: [] }
  const child = { data: { uid: 'child', text: 'child' }, children: [] }
  const root = { data: { uid: 'root', text: 'root' }, children: [child] }
  const operations = buildMindmapContentOperations([
    { action: 'update', oldData: oldRoot, data: root },
    { action: 'create', data: child },
  ], new Map([['root', 7]]))

  assert.equal(operations[0].type, 'node.update')
  assert.equal(operations[0].targetRevision, undefined)
  assert.deepEqual(operations[0].payload, {
    data: { uid: 'root', text: 'root' },
    childUids: ['child'],
    oldChildUids: [],
    dataChanged: false,
    childrenChanged: true,
    crossNodeDataSeparated: true,
    tagBindingsSeparated: true,
  })
  assert.equal(operations[1].type, 'node.create')
  assert.equal(operations[1].nodeUid, 'child')
})

test('节点标签绑定使用独立操作且定义样式不进入节点冲突域', () => {
  const oldNode = {
    data: {
      uid: 'root', text: 'root',
      tag: [{ tagId: 11, text: '旧名称', style: { color: 'red' }, placement: 'top' }],
    },
    children: [],
  }
  const nextNode = {
    data: {
      uid: 'root', text: 'root',
      tag: [
        { tagId: 11, text: '新名称', style: { color: 'blue' }, placement: 'top' },
        { tagId: 12, text: '第二个标签' },
      ],
    },
    children: [],
  }
  const detail = [{ action: 'update', oldData: oldNode, data: nextNode }]

  assert.deepEqual(buildMindmapContentOperations(detail), [])
  assert.deepEqual(buildNodeTagContentOperations(detail), [{
    type: 'node.tag.bind',
    nodeUid: 'root',
    payload: {
      key: 'root:12',
      tagKey: '12',
      tag: { tagId: 12 },
    },
  }])
})

test('标签布局变化和纯重排产生最小操作', () => {
  const oldNode = {
    data: { uid: 'root', tag: [{ tagId: 11 }, { tagId: 12, placement: 'top' }] },
    children: [],
  }
  const nextNode = {
    data: { uid: 'root', tag: [{ tagId: 12, placement: 'bottom' }, { tagId: 11 }] },
    children: [],
  }

  assert.deepEqual(buildNodeTagContentOperations([{
    action: 'update', oldData: oldNode, data: nextNode,
  }]), [
    {
      type: 'node.tag.bind',
      nodeUid: 'root',
      payload: {
        key: 'root:12', tagKey: '12', tag: { tagId: 12, placement: 'bottom' },
      },
    },
    {
      type: 'node.tag.reorder',
      nodeUid: 'root',
      payload: { key: 'root', tagKeys: ['12', '11'] },
    },
  ])
})

test('标签新增或删除后的目标顺序会显式进入重排操作', () => {
  const operations = buildNodeTagContentOperations([{
    action: 'update',
    oldData: {
      data: { uid: 'root', tag: [{ tagId: 1 }, { tagId: 2 }, { tagId: 3 }] },
      children: [],
    },
    data: {
      data: { uid: 'root', tag: [{ tagId: 4 }, { tagId: 3 }, { tagId: 1 }] },
      children: [],
    },
  }])

  assert.deepEqual(operations.map(operation => operation.type), [
    'node.tag.unbind',
    'node.tag.bind',
    'node.tag.reorder',
  ])
  assert.deepEqual(operations.at(-1).payload.tagKeys, ['4', '3', '1'])
})

test('只修改标签属性不会生成改变原顺序的重排操作', () => {
  const operations = buildNodeTagContentOperations([{
    action: 'update',
    oldData: {
      data: { uid: 'root', tag: [{ tagId: 1, placement: 'top' }, { tagId: 2 }] },
      children: [],
    },
    data: {
      data: { uid: 'root', tag: [{ tagId: 1, placement: 'bottom' }, { tagId: 2 }] },
      children: [],
    },
  }])

  assert.deepEqual(operations.map(operation => operation.type), ['node.tag.bind'])
})

test('节点属性更新与删除保留节点 revision 保护', () => {
  const revisions = new Map([['a', 3], ['b', 4]])
  const operations = buildMindmapContentOperations([
    {
      action: 'update',
      oldData: { data: { uid: 'a', text: 'old' }, children: [] },
      data: { data: { uid: 'a', text: 'new' }, children: [] },
    },
    {
      action: 'delete',
      data: { data: { uid: 'b', text: 'deleted' }, children: [] },
    },
  ], revisions)

  assert.equal(operations[0].targetRevision, 3)
  assert.equal(operations[0].payload.dataChanged, true)
  assert.equal(operations[0].payload.childrenChanged, false)
  assert.deepEqual(operations[0].payload.previousData, {
    uid: 'a',
    text: 'old',
  })
  assert.equal(operations[1].nodeUid, 'b')
  assert.equal(operations[1].targetRevision, 4)
})

test('跨节点实体使用独立操作且不污染节点数据冲突域', () => {
  const oldNode = {
    data: { uid: 'root', text: 'root', associativeLineTargets: [] },
    children: [],
  }
  const nextNode = {
    data: { uid: 'root', text: 'root', associativeLineTargets: ['target'] },
    children: [],
  }
  assert.deepEqual(buildMindmapContentOperations([{
    action: 'update', oldData: oldNode, data: nextNode,
  }]), [])

  const relation = {
    relationUid: 'assoc:root:target', relationType: 'associative_line',
    sourceUid: 'root', targetUid: 'target', sortOrder: 0, controlData: {},
  }
  assert.deepEqual(buildCrossNodeContentOperations(
    { relations: {}, summaries: {}, groups: {}, assets: {} },
    { relations: { 'assoc:root:target': relation }, summaries: {}, groups: {}, assets: {} },
  ), [{
    type: 'relation.upsert',
    payload: {
      key: 'assoc:root:target',
      ...relation,
      before: null,
      after: relation,
    },
  }])
})

test('同一保存窗口的跨节点操作保留最初前态并消除净零变化', () => {
  const initial = { relationUid: 'r', text: '旧', styleData: { color: 'red' } }
  const middle = { ...initial, text: '中间' }
  const latest = { ...middle, styleData: { color: 'blue' } }
  const first = buildCrossNodeContentOperations(
    { relations: { r: initial } },
    { relations: { r: middle } },
  )[0]
  const second = buildCrossNodeContentOperations(
    { relations: { r: middle } },
    { relations: { r: latest } },
  )[0]

  const merged = mergePendingCrossNodeOperation(first, second)
  assert.deepEqual(merged.payload.before, initial)
  assert.deepEqual(merged.payload.after, latest)
  const reverted = buildCrossNodeContentOperations(
    { relations: { r: latest } },
    { relations: { r: initial } },
  )[0]
  assert.equal(mergePendingCrossNodeOperation(merged, reverted), null)
})

test('远端预览插入两次本地编辑之间时保留两段本地时序意图', () => {
  const initial = {
    relationUid: 'r',
    styleData: { color: 'red', width: 1 },
    text: '初始文本',
  }
  const firstLocal = {
    ...initial,
    styleData: { color: 'blue', width: 1 },
  }
  const remotePreview = {
    ...initial,
    styleData: { color: 'green', width: 1 },
    text: '远端文本',
  }
  const secondLocal = {
    ...remotePreview,
    styleData: { color: 'green', width: 2 },
  }
  const firstOperation = buildCrossNodeContentOperations(
    { relations: { r: initial } },
    { relations: { r: firstLocal } },
  )[0]
  const secondOperation = buildCrossNodeContentOperations(
    { relations: { r: remotePreview } },
    { relations: { r: secondLocal } },
  )[0]

  const merged = mergePendingCrossNodeOperation(
    firstOperation,
    secondOperation,
  )

  assert.deepEqual(merged, [firstOperation, secondOperation])
  assert.equal(merged[0].payload.after.styleData.color, 'blue')
  assert.equal(merged[1].payload.before.text, '远端文本')
  assert.equal(merged[1].payload.after.styleData.width, 2)
})

test('跨记录删除边界的重建或净零创建删除不会丢失 generation 语义', () => {
  const record = { assetKey: 'asset', uri: 'old.png' }
  const removed = buildCrossNodeContentOperations(
    { assets: { asset: record } },
    { assets: {} },
  )[0]
  const recreated = buildCrossNodeContentOperations(
    { assets: {} },
    { assets: { asset: { ...record, uri: 'new.png' } } },
  )[0]
  assert.deepEqual(
    mergePendingCrossNodeOperation(removed, recreated),
    [removed, recreated],
  )

  const created = buildCrossNodeContentOperations(
    { assets: {} },
    { assets: { asset: record } },
  )[0]
  const deletedAgain = buildCrossNodeContentOperations(
    { assets: { asset: record } },
    { assets: {} },
  )[0]
  assert.deepEqual(
    mergePendingCrossNodeOperation(created, deletedAgain),
    [created, deletedAgain],
  )
})

test('冻结 HTTP 批次时重放本地跨节点意图并保留远端无关字段', () => {
  const before = {
    relationUid: 'assoc:source:target',
    relationType: 'associative_line',
    sourceUid: 'source',
    targetUid: 'target',
    text: '原文本',
    styleData: { color: 'red', width: 1 },
    controlData: {},
    sortOrder: 0,
  }
  const localAfter = {
    ...before,
    styleData: { ...before.styleData, color: 'blue' },
  }
  const liveRemotePreview = {
    ...before,
    text: '远端文本',
    styleData: { color: 'green', width: 3 },
  }
  const document = {
    root: {
      data: {
        uid: 'source',
        associativeLineTargets: ['target'],
        associativeLineText: { target: liveRemotePreview.text },
        associativeLineStyle: { target: liveRemotePreview.styleData },
      },
      children: [{ data: { uid: 'target' }, children: [] }],
    },
    view: null,
    layout: 'mindMap',
    theme: {},
    documentData: {},
  }
  const [operation] = buildCrossNodeContentOperations(
    { relations: { 'assoc:source:target': before } },
    { relations: { 'assoc:source:target': localAfter } },
  )

  const frozen = applyCrossNodeOperationIntents(document, [operation])

  assert.equal(
    frozen.root.data.associativeLineStyle.target.color,
    'blue',
  )
  assert.equal(frozen.root.data.associativeLineStyle.target.width, 3)
  assert.equal(frozen.root.data.associativeLineText.target, '远端文本')
  assert.equal(document.root.data.associativeLineStyle.target.color, 'green')
})

test('远端预览已删实体时冻结快照仍完整物化本地更新供冲突草稿恢复', () => {
  const before = {
    relationUid: 'assoc:source:target',
    relationType: 'associative_line',
    sourceUid: 'source',
    targetUid: 'target',
    text: '原文本',
    controlData: {},
    styleData: { color: 'red' },
    sortOrder: 0,
  }
  const after = { ...before, text: '本地文本' }
  const [operation] = buildCrossNodeContentOperations(
    { relations: { 'assoc:source:target': before } },
    { relations: { 'assoc:source:target': after } },
  )
  const remoteDeletedPreview = {
    root: {
      data: { uid: 'source' },
      children: [{ data: { uid: 'target' }, children: [] }],
    },
  }

  const frozen = applyCrossNodeOperationIntents(
    remoteDeletedPreview,
    [operation],
  )

  assert.deepEqual(frozen.root.data.associativeLineTargets, ['target'])
  assert.equal(frozen.root.data.associativeLineText.target, '本地文本')
  assert.equal(
    frozen.root.data.associativeLineStyle.target.color,
    'red',
  )
})

test('冻结 HTTP 批次时节点本地字段意图覆盖同字段远端预览', () => {
  const remotePreview = {
    root: {
      data: {
        uid: 'root',
        text: '远端文本',
        style: { color: 'green', fontSize: 18 },
        note: '远端新增说明',
      },
      children: [],
    },
    layout: 'mindMap',
  }
  const operation = {
    type: 'node.update',
    nodeUid: 'root',
    targetRevision: 3,
    payload: {
      previousData: {
        uid: 'root',
        text: '原文本',
        style: { color: 'red', fontSize: 18 },
      },
      data: {
        uid: 'root',
        text: '本地文本',
        style: { color: 'red', fontSize: 18 },
      },
      dataChanged: true,
      childrenChanged: false,
      childUids: [],
      oldChildUids: [],
    },
  }

  const frozen = applyMindmapNodeDataOperationIntents(remotePreview, [operation])

  assert.equal(frozen.root.data.text, '本地文本')
  assert.equal(frozen.root.data.style.color, 'green')
  assert.equal(frozen.root.data.note, '远端新增说明')
  assert.equal(remotePreview.root.data.text, '远端文本')
})

test('统一意图重放同时保护节点字段和跨节点记录', () => {
  const beforeRelation = {
    relationUid: 'assoc:root:target',
    relationType: 'associative_line',
    sourceUid: 'root',
    targetUid: 'target',
    text: '原关系',
    controlData: {},
    styleData: {},
    sortOrder: 0,
  }
  const [relationOperation] = buildCrossNodeContentOperations(
    { relations: { 'assoc:root:target': beforeRelation } },
    { relations: { 'assoc:root:target': { ...beforeRelation, text: '本地关系' } } },
  )
  const document = {
    root: {
      data: {
        uid: 'root',
        text: '远端节点',
        associativeLineTargets: ['target'],
        associativeLineText: { target: '远端关系' },
        associativeLineStyle: { target: {} },
      },
      children: [{ data: { uid: 'target' }, children: [] }],
    },
  }
  const nodeOperation = {
    type: 'node.update',
    nodeUid: 'root',
    payload: {
      previousData: { uid: 'root', text: '原节点' },
      data: { uid: 'root', text: '本地节点' },
      dataChanged: true,
      childrenChanged: false,
      childUids: ['target'],
      oldChildUids: ['target'],
    },
  }

  const frozen = applyMindmapOperationIntents(
    document,
    [nodeOperation, relationOperation],
  )

  assert.equal(frozen.root.data.text, '本地节点')
  assert.equal(frozen.root.data.associativeLineText.target, '本地关系')
  assert.equal(document.root.data.text, '远端节点')
  assert.equal(document.root.data.associativeLineText.target, '远端关系')
})

test('分组最后成员移除只重放成员差量并保留远端新增成员', () => {
  const before = {
    groupUid: 'group-1',
    groupType: 'outer_frame',
    payload: { color: 'red' },
    memberUids: ['local'],
  }
  const document = {
    root: {
      data: { uid: 'root' },
      children: [
        { data: { uid: 'local' }, children: [] },
        {
          data: {
            uid: 'remote',
            outerFrame: { groupId: 'group-1', color: 'blue' },
          },
          children: [],
        },
      ],
    },
  }
  const [operation] = buildCrossNodeContentOperations(
    { groups: { 'group-1': before } },
    { groups: {} },
  )
  assert.equal(operation.type, 'group.upsert')
  assert.deepEqual(operation.payload.after.memberUids, [])

  const frozen = applyCrossNodeOperationIntents(document, [operation])

  assert.equal(frozen.root.children[0].data.outerFrame, undefined)
  assert.deepEqual(frozen.root.children[1].data.outerFrame, {
    groupId: 'group-1',
    color: 'blue',
  })
})
