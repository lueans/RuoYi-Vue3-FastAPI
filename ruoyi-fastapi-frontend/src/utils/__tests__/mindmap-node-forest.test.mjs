import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  calculateNodeForestRect,
  walkNodeForest,
} from '../../libs/simple-mind-map/src/utils/nodeForest.js'

test('node forest traversal preserves preorder, metadata and subtree stop', () => {
  const blockedChild = { id: 'blocked-child' }
  const roots = [
    { id: 'a', children: [{ id: 'a1' }, { id: 'a2' }] },
    { id: 'blocked', children: [blockedChild] },
    { id: 'b' },
  ]
  const visits = []
  const count = walkNodeForest(roots, (node, frame) => {
    visits.push([node.id, frame.parent?.id || null, frame.depth, frame.index])
    return node.id === 'blocked' ? false : undefined
  })

  assert.equal(count, 5)
  assert.deepEqual(visits, [
    ['a', null, 0, 0],
    ['a1', 'a', 1, 0],
    ['a2', 'a', 1, 1],
    ['blocked', null, 0, 1],
    ['b', null, 0, 2],
  ])
})

test('node forest traversal processes shared and cyclic objects only once', () => {
  const shared = { id: 'shared', children: [] }
  const root = { id: 'root', children: [shared, shared] }
  shared.children.push(root)
  const order = []
  assert.equal(walkNodeForest(root, node => order.push(node.id)), 2)
  assert.deepEqual(order, ['root', 'shared'])

  assert.throws(
    () => walkNodeForest(
      root,
      () => {},
      node => node.children,
      { onDuplicateNode: () => { throw new Error('duplicate') } }
    ),
    /duplicate/
  )
  assert.throws(
    () => walkNodeForest(
      [null],
      () => {},
      undefined,
      { onInvalidNode: () => { throw new Error('invalid') } }
    ),
    /invalid/
  )
})

test('node forest traversal handles a 20,000-level chain without recursion', () => {
  const root = { children: [] }
  let current = root
  for (let depth = 1; depth < 20_000; depth += 1) {
    const child = { children: [] }
    current.children.push(child)
    current = child
  }
  assert.equal(walkNodeForest(root, () => {}), 20_000)
})

test('node forest rectangle is finite, excludes roots and ignores invalid measurements', () => {
  const root = {
    rect: { x: -100, y: -100, width: 10, height: 10 },
    children: [
      { rect: { x: 10, y: 20, width: 30, height: 40 } },
      { rect: { x: -5, y: 5, width: 10, height: 10 } },
      { rect: { x: Infinity, y: 0, width: 1, height: 1 } },
    ],
  }
  assert.deepEqual(calculateNodeForestRect({
    roots: root,
    excludeRoots: true,
    measureNode: node => node.rect,
  }), {
    left: -5,
    top: 5,
    width: 45,
    height: 55,
    measuredCount: 2,
  })
  assert.equal(calculateNodeForestRect({
    roots: { children: [] },
    measureNode: () => null,
  }), null)
})

test('appointed-node mutation and bounding boxes use the shared iterative forest', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/utils/index.js', import.meta.url),
    'utf8'
  )
  assert.match(source, /const walkAppointNodeForest[\s\S]*walkNodeForest\(/)
  assert.match(source, /export const addDataToAppointNodes[\s\S]*walkAppointNodeForest\(appointNodes/)
  assert.match(source, /export const createUidForAppointNodes[\s\S]*walkAppointNodeForest\(appointNodes/)
  assert.match(source, /onDuplicateNode\(\)[\s\S]*指定节点包含循环或重复引用/)
  assert.match(source, /指定节点 data 必须是对象/)
  assert.match(source, /指定节点概要必须是对象/)
  assert.match(source, /const measureNodeTreeBoundingRect[\s\S]*calculateNodeForestRect\(/)
  assert.doesNotMatch(source, /const walk = list => \{\s*list\.forEach\(node/)
  assert.doesNotMatch(source, /const walk = \(root, isRoot\) =>/)
})
