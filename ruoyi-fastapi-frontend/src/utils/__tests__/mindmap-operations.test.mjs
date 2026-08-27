import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendUniqueMindmapOperation,
  buildCrossNodeContentOperations,
  buildMindmapDocumentOperations,
  buildMindmapContentOperations,
  buildMindmapTreeDetailList,
  buildNodeTagContentOperations,
  detectMindmapFileOperations,
  snapshotMindmapDocumentMeta,
} from '../mindmap-operations.js'

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
    payload: { key: 'assoc:root:target', ...relation },
  }])
})
