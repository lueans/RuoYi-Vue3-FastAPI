import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyCrossNodeState,
  detailListTouchesCrossNodeState,
  extractCrossNodeState,
  stripCrossNodeData,
} from '../yjs-cross-node-state.js'

function createCrossNodeTree() {
  return {
    data: {
      uid: 'root',
      text: '根节点',
      associativeLineTargets: ['right'],
      associativeLineTargetControlOffsets: [[1, 2]],
      associativeLinePoint: [[3, 4]],
      associativeLineText: { right: '关联' },
      associativeLineStyle: { right: { lineColor: '#f00' } },
      generalization: [{ uid: 'summary-1', range: [0, 1], text: '概要' }],
      imgMap: { cover: 'data:image/png;base64,AA==' },
    },
    children: [
      {
        data: { uid: 'left', text: '左', outerFrame: { groupId: 'group-1', lineColor: '#0f0' } },
        children: [],
      },
      {
        data: { uid: 'right', text: '右', outerFrame: { groupId: 'group-1', lineColor: '#0f0' } },
        children: [],
      },
    ],
  }
}

test('跨节点状态可拆分并无损恢复 simple-mind-map 数据形态', () => {
  const tree = createCrossNodeTree()
  const state = extractCrossNodeState(tree)
  assert.deepEqual(Object.keys(state.relations), ['assoc:root:right'])
  assert.equal(Object.values(state.summaries)[0].startChildUid, 'left')
  assert.deepEqual(state.groups['group-1'].memberUids, ['left', 'right'])
  assert.equal(state.assets.cover.uri, 'data:image/png;base64,AA==')

  const stripped = structuredClone(tree)
  const walk = node => {
    node.data = stripCrossNodeData(node.data)
    node.children.forEach(walk)
  }
  walk(stripped)
  applyCrossNodeState(stripped, state)

  assert.deepEqual(stripped, tree)
})

test('关联数据被移除时旧节点快照也会触发独立状态同步', () => {
  const oldNode = createCrossNodeTree()
  const nextNode = structuredClone(oldNode)
  delete nextNode.data.associativeLineTargets
  delete nextNode.data.associativeLineTargetControlOffsets
  delete nextNode.data.associativeLinePoint
  delete nextNode.data.associativeLineText
  delete nextNode.data.associativeLineStyle

  assert.equal(detailListTouchesCrossNodeState([{
    action: 'update',
    oldData: oldNode,
    data: nextNode,
  }]), true)
})

test('关联目标节点删除后不会保留悬空关联记录', () => {
  const tree = createCrossNodeTree()
  tree.children = tree.children.filter(child => child.data.uid !== 'right')

  const state = extractCrossNodeState(tree)

  assert.deepEqual(state.relations, {})
})

test('一万二千层跨节点状态可拆分恢复且循环引用不会耗尽调用栈', () => {
  const root = {
    data: {
      uid: 'node-0',
      associativeLineTargets: ['node-11999'],
      associativeLineText: { 'node-11999': '深层关联' },
    },
    children: [],
  }
  let cursor = root
  for (let index = 1; index < 12000; index += 1) {
    const child = { data: { uid: `node-${index}` }, children: [] }
    cursor.children.push(child)
    cursor = child
  }
  cursor.data.outerFrame = { groupId: 'deep-group', lineColor: '#0f0' }
  cursor.children.push(root)

  const state = extractCrossNodeState(root)
  assert.equal(state.relations['assoc:node-0:node-11999'].text, '深层关联')
  assert.deepEqual(state.groups['deep-group'].memberUids, ['node-11999'])

  applyCrossNodeState(root, state)
  assert.deepEqual(root.data.associativeLineTargets, ['node-11999'])
  assert.equal(root.data.associativeLineText['node-11999'], '深层关联')
  assert.equal(cursor.data.outerFrame.groupId, 'deep-group')
})

test('旧浏览器缺少 structuredClone 时跨节点数据使用迭代复制并拒绝循环对象', () => {
  const previousStructuredClone = globalThis.structuredClone
  globalThis.structuredClone = undefined
  try {
    const deepStyle = { level: 0 }
    let cursor = deepStyle
    for (let level = 1; level < 20_000; level += 1) {
      cursor.child = { level }
      cursor = cursor.child
    }
    const tree = createCrossNodeTree()
    tree.data.associativeLineStyle.right = deepStyle
    const state = extractCrossNodeState(tree)
    cursor = state.relations['assoc:root:right'].styleData
    let depth = 1
    while (cursor.child) {
      cursor = cursor.child
      depth += 1
    }
    assert.equal(depth, 20_000)

    const cycle = {}
    cycle.self = cycle
    tree.data.associativeLineStyle.right = cycle
    assert.throws(() => extractCrossNodeState(tree), /无法安全复制/)
  } finally {
    globalThis.structuredClone = previousStructuredClone
  }
})
