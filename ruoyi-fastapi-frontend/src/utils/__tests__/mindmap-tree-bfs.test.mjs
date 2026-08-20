import assert from 'node:assert/strict'
import test from 'node:test'

import { bfsWalk } from '../../libs/simple-mind-map/src/utils/treeBfs.js'

test('bfsWalk preserves breadth-first order and parent identity', () => {
  const leftLeaf = { id: 'left-leaf', children: [] }
  const rightLeaf = { id: 'right-leaf', children: [] }
  const left = { id: 'left', children: [leftLeaf] }
  const right = { id: 'right', children: [rightLeaf] }
  const root = { id: 'root', children: [left, right] }
  const visited = []

  bfsWalk(root, (node, parent) => {
    visited.push([node.id, parent?.id ?? null])
  })

  assert.deepEqual(visited, [
    ['root', null],
    ['left', 'root'],
    ['right', 'root'],
    ['left-leaf', 'left'],
    ['right-leaf', 'right']
  ])
})

test('bfsWalk stops immediately when callback returns stop', () => {
  const root = {
    id: 'root',
    children: [
      { id: 'first', children: [] },
      { id: 'second', children: [] }
    ]
  }
  const visited = []

  bfsWalk(root, node => {
    visited.push(node.id)
    if (node.id === 'first') return 'stop'
  })

  assert.deepEqual(visited, ['root', 'first'])
})

test('bfsWalk terminates cycles and visits shared objects once', () => {
  const shared = { id: 'shared', children: [] }
  const left = { id: 'left', children: [shared] }
  const right = { id: 'right', children: [shared] }
  const root = { id: 'root', children: [left, right] }
  shared.children.push(root)
  const visited = []

  bfsWalk(root, node => {
    visited.push(node.id)
  })

  assert.deepEqual(visited, ['root', 'left', 'right', 'shared'])
})

test('bfsWalk handles a 20,000-node wide tree with a linear queue', () => {
  const children = Array.from({ length: 20_000 }, (_, index) => ({
    id: index,
    children: []
  }))
  const root = { id: 'root', children }
  let count = 0

  bfsWalk(root, () => {
    count += 1
  })

  assert.equal(count, 20_001)
})
