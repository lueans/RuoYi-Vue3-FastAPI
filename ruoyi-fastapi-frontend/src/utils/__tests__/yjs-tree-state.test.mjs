import assert from 'node:assert/strict'
import test from 'node:test'
import * as Y from 'yjs'

import {
  applyLocalActiveNodeState,
  deleteYjsSubtree,
  flattenMindmapTree,
  normalizeNodeDataForYjs,
  replaceYArrayValues,
  replaceYMapEntries,
  setYMapValueIfChanged,
  stripManagedTagDefinitions,
  synchronizeYjsParentUids,
} from '../yjs-tree-state.js'

function createYNode(doc, uid, children = [], parentUid = '') {
  const yNodes = doc.getMap('nodes')
  const yNode = new Y.Map()
  const yData = new Y.Map()
  yData.set('uid', uid)
  yData.set('image', `${uid}.png`)
  yNode.set('data', yData)
  yNode.set('children', Y.Array.from(children))
  yNode.set('parentUid', parentUid)
  yNodes.set(uid, yNode)
  return yNode
}

test('托管标签只保留身份和局部布局', () => {
  const result = stripManagedTagDefinitions({
    tag: [{ tagId: 7, text: '旧名称', style: { fill: '#f00' }, placement: 'right' }],
  })
  assert.deepEqual(result.tag, [{ tagId: 7, placement: 'right' }])
})

test('Yjs 节点数据排除本地选中状态', () => {
  assert.deepEqual(
    normalizeNodeDataForYjs({ uid: 'node-1', text: '节点', isActive: true }),
    { uid: 'node-1', text: '节点' },
  )
})

test('协作树刷新只恢复当前客户端的活动节点', () => {
  const root = {
    data: { uid: 'root', isActive: true },
    children: [{ data: { uid: 'child', isActive: false }, children: [] }],
  }

  assert.equal(applyLocalActiveNodeState(root, ['child']), root)
  assert.equal(root.data.isActive, false)
  assert.equal(root.children[0].data.isActive, true)
})

test('扁平化保留稳定父子关系', () => {
  const flat = flattenMindmapTree({
    data: { uid: 'root', text: '根' },
    children: [{ data: { uid: 'child', text: '子' }, children: [] }],
  })
  assert.equal(flat.root.parentUid, '')
  assert.deepEqual(flat.root.children, ['child'])
  assert.equal(flat.child.parentUid, 'root')
})

test('二万层脑图可非递归扁平化且循环对象会确定终止', () => {
  const root = { data: { uid: 'node-0' }, children: [] }
  let cursor = root
  for (let index = 1; index < 20000; index += 1) {
    const child = { data: { uid: `node-${index}` }, children: [] }
    cursor.children.push(child)
    cursor = child
  }
  cursor.children.push(root)

  const flat = flattenMindmapTree(root)

  assert.equal(Object.keys(flat).length, 20000)
  assert.equal(flat['node-0'].parentUid, '')
  assert.equal(flat['node-19999'].parentUid, 'node-19998')
  assert.deepEqual(flat['node-19999'].children, ['node-0'])
})

test('节点更新会删除已移除字段而不是保留幽灵数据', () => {
  const doc = new Y.Doc()
  const yNode = createYNode(doc, 'root')
  const yData = yNode.get('data')
  replaceYMapEntries(yData, { uid: 'root', text: '更新后' })
  assert.deepEqual(Object.fromEntries(yData.entries()), { uid: 'root', text: '更新后' })
})

test('Yjs 节点判等忽略对象键序并可比较二万层插件数据', () => {
  const stored = { first: 1, nested: { alpha: true, beta: false } }
  const equivalent = { nested: { beta: false, alpha: true }, first: 1 }
  const writes = []
  const yMap = {
    get: () => stored,
    set: (key, value) => writes.push([key, value]),
  }
  assert.equal(setYMapValueIfChanged(yMap, 'config', equivalent), false)
  assert.deepEqual(writes, [])

  const left = { level: 0 }
  const right = { level: 0 }
  let leftCursor = left
  let rightCursor = right
  for (let level = 1; level < 20_000; level += 1) {
    leftCursor.child = { level }
    rightCursor.child = { level }
    leftCursor = leftCursor.child
    rightCursor = rightCursor.child
  }
  yMap.get = () => left
  assert.equal(setYMapValueIfChanged(yMap, 'deepConfig', right), false)
  rightCursor.level = -1
  assert.equal(setYMapValueIfChanged(yMap, 'deepConfig', right), true)
  assert.equal(writes.length, 1)
})

test('移动节点后重新计算 parentUid', () => {
  const doc = new Y.Doc()
  const root = createYNode(doc, 'root', ['a', 'b'])
  const a = createYNode(doc, 'a', ['child'], 'root')
  const b = createYNode(doc, 'b', [], 'root')
  const child = createYNode(doc, 'child', [], 'a')
  replaceYArrayValues(a.get('children'), [])
  replaceYArrayValues(b.get('children'), ['child'])
  synchronizeYjsParentUids(doc.getMap('nodes'))
  assert.equal(root.get('parentUid'), '')
  assert.equal(child.get('parentUid'), 'b')
})

test('并发多父、环、孤立和非法边归一化为单根确定性拓扑', () => {
  const doc = new Y.Doc()
  const root = createYNode(doc, 'root', ['a', 'b', 'root', 'ghost', 'a'])
  const a = createYNode(doc, 'a', ['shared'], 'root')
  const b = createYNode(doc, 'b', ['shared'], 'root')
  const shared = createYNode(doc, 'shared', [], 'b')
  const x = createYNode(doc, 'x', ['y'], 'y')
  const y = createYNode(doc, 'y', ['x'], 'x')
  const z = createYNode(doc, 'z', [], '')

  const normalizedRoot = synchronizeYjsParentUids(doc.getMap('nodes'), 'root')

  assert.equal(normalizedRoot, 'root')
  assert.deepEqual(root.get('children').toArray(), ['a', 'b', 'y', 'z'])
  assert.deepEqual(a.get('children').toArray(), [])
  assert.deepEqual(b.get('children').toArray(), ['shared'])
  assert.equal(shared.get('parentUid'), 'b')
  assert.deepEqual(x.get('children').toArray(), [])
  assert.deepEqual(y.get('children').toArray(), ['x'])
  assert.equal(x.get('parentUid'), 'y')
  assert.equal(y.get('parentUid'), 'root')
  assert.equal(z.get('parentUid'), 'root')
  assert.equal(root.get('parentUid'), '')
})

test('删除节点会递归删除子树并清理父节点引用', () => {
  const doc = new Y.Doc()
  const root = createYNode(doc, 'root', ['a', 'b'])
  createYNode(doc, 'a', ['child'], 'root')
  createYNode(doc, 'child', [], 'a')
  createYNode(doc, 'b', [], 'root')
  const deleted = deleteYjsSubtree(doc.getMap('nodes'), 'a')
  assert.deepEqual([...deleted].sort(), ['a', 'child'])
  assert.deepEqual(root.get('children').toArray(), ['b'])
  assert.equal(doc.getMap('nodes').has('child'), false)
})
